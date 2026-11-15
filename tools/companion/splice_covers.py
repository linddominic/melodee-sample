# SPDX-License-Identifier: AGPL-3.0-only
"""Pack artwork for the Splice packs on the Mac, found the way a link preview finds a page's image.

For a pack folder ("Berlin Techno"): the official Splice MCP's catalog search
for its name gives sounds with their splice.com pages; a sound's public page
names its pack and links the pack's own page, whose og:image is the cover. A
title must fit the folder's name, else no cover is taken. One page at a time,
a second apart, under the companion's own name; what is found (or not) is
kept in ~/Library/Caches/Melodee/splice-covers, so each pack is looked up
once (a miss again after a week).
"""
import html
import json
import queue
import re
import threading
import time
import unicodedata
from pathlib import Path

from splice_mcp import http

CACHE = Path.home() / "Library/Caches/Melodee/splice-covers"
RETRY = 7 * 24 * 3600
GAP = 3.0           # seconds between splice.com pages
PAUSE = (60, 900)   # after "Too many requests": a minute at first, doubling to fifteen


class TooMany(Exception):
    """splice.com asked us to slow down (429); `wait` seconds, if it said."""
    def __init__(self, wait=0):
        super().__init__("splice.com asked to slow down")
        self.wait = wait


def words(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"\((.*?)\)", r" \1 ", text)
    return [w for w in re.findall(r"[a-z0-9]+", text) if w not in ("vol", "the", "and", "by", "pack", "sample", "samples", "sounds")]


def fits(folder, title):
    """Whether a pack's title is the folder's pack: every word of the folder's name in the title."""
    want, have = words(folder), set(words(title))
    return bool(want) and all(w in have for w in want)


def exact(folder, title):
    """The same words both ways: "Berlin Techno" is "Berlin Techno", not "Berlin Techno Vol. 2"."""
    return set(words(folder)) == set(words(title))


def slug(text):
    return "-".join(re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()))


def results(text):
    """[(file name, page link)] of a describe_a_sound answer (Markdown: "### 1. <name>" ... "**Link:** <url>")."""
    return [(name.strip(), link) for name, link in re.findall(r"### \d+\. ([^\n]+)\n(?:(?!### ).)*?\*\*Link:\*\* (\S+)", text, re.S)]


class SpliceCovers:
    def __init__(self, mcp, files_of=lambda pack: [], root=None):
        self.mcp = mcp
        self.files_of = files_of   # the pack's own sound files, by name: found again in the catalog, they name the pack
        self.root = Path(root) if root else None   # the Splice folder: a cover.jpg/png/webp in a pack's folder wins
        self.pace = threading.Lock()
        self.last = 0.0
        self.lock = threading.Lock()
        CACHE.mkdir(parents=True, exist_ok=True)
        self.index_file = CACHE / "index.json"
        try:
            self.index = json.loads(self.index_file.read_text())
        except (OSError, ValueError):
            self.index = {}
        self.queue, self.queued = queue.Queue(), set()
        threading.Thread(target=self.work, daemon=True).start()

    def save(self):
        tmp = self.index_file.with_suffix(".part")
        tmp.write_text(json.dumps(self.index, indent=1))
        tmp.replace(self.index_file)

    def own(self, pack):
        """A cover one put in the pack's folder oneself (cover.jpg, .png or .webp), or None."""
        if not self.root or "/" in pack or pack.startswith("."):
            return None
        for ext in ("jpg", "jpeg", "png", "webp"):
            path = self.root / pack / ("cover." + ext)
            if path.is_file():
                return path
        return None

    def state(self, pack):
        """"found", "none", "pending", or "signedout"."""
        if self.own(pack):
            return "found"
        with self.lock:
            got = self.index.get(pack)
            if got and got.get("state") == "found" and (CACHE / got["file"]).is_file():
                return "found"
            if got and got.get("state") == "none" and time.time() - got.get("at", 0) < RETRY:
                return "none"
            if not self.mcp.signed_in():
                return "signedout"
            if pack not in self.queued:
                self.queued.add(pack)
                self.queue.put(pack)
            return "pending"

    def image(self, pack):
        own = self.own(pack)
        if own:
            return own.read_bytes(), {"png": "image/png", "webp": "image/webp"}.get(own.suffix[1:].lower(), "image/jpeg")
        with self.lock:
            got = self.index.get(pack)
        if got and got.get("state") == "found":
            path = CACHE / got["file"]
            if path.is_file():
                return path.read_bytes(), got.get("type", "image/jpeg")
        return None, None

    def work(self):
        pause = PAUSE[0]
        while True:
            pack = self.queue.get()
            try:
                found = self.find(pack)
                pause = PAUSE[0]
            except TooMany as e:             # not a miss: the pack waits its turn again, and every lookup pauses
                self.queue.put(pack)
                time.sleep(max(e.wait, pause))
                pause = min(pause * 2, PAUSE[1])
                continue
            except PermissionError:
                found = None                 # signed out meanwhile: asked again later
                with self.lock:
                    self.queued.discard(pack)
                continue
            except Exception as e:           # a page that changed, a network hiccup: tried again in a week
                found = {"state": "none", "why": str(e)[:200]}
            with self.lock:
                self.index[pack] = {**found, "at": time.time()}
                self.queued.discard(pack)
                self.save()

    def page(self, url):
        with self.pace:                     # every lookup, covers and packs alike, one page each GAP
            wait = self.last + GAP - time.time()
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
        status, head, body = http(url, headers={"User-Agent": "melodee-kit-manager/0.1 (link preview)"}, timeout=30)
        if status == 429:
            wait = {k.lower(): v for k, v in head.items()}.get("retry-after", "")
            raise TooMany(int(wait) if wait.isdigit() else 0)
        text = body.decode(errors="replace")
        if status != 200 or "Just a moment..." in text[:2000]:
            raise OSError("splice.com answered %d" % status)
        return text

    def own_pack(self, sample):
        """(title, /sounds/packs/... path) of the pack a sound's page belongs to, or None."""
        m = re.search(r'og:title" content="[^"]*? from (.+?) \| Splice', sample)
        if not m:
            return None
        title = html.unescape(m.group(1))
        own = re.search(r'/sounds/packs/[a-z0-9_-]+/' + re.escape(slug(title)) + r'\b', sample)
        return (title, own.group(0)) if own else None

    def cover(self, pack, title, path):
        page_url = "https://splice.com" + path
        packpage = self.page(page_url)
        img = re.search(r'og:image" content="([^"]+)"', packpage)
        if not img:
            return None
        status, head, data = http(html.unescape(img.group(1)), timeout=30)
        kind = {k.lower(): v for k, v in head.items()}.get("content-type", "image/jpeg").split(";")[0]
        if status != 200 or not kind.startswith("image/") or len(data) > 2_000_000:
            return None
        name = slug(pack)[:60] + {"image/png": ".png", "image/webp": ".webp"}.get(kind, ".jpg")
        (CACHE / name).write_bytes(data)
        return {"state": "found", "file": name, "type": kind, "title": title, "page": page_url}

    def pack_of(self, link):
        """The pack a catalog sound's page belongs to: {title, path, cover} (cover kept under the pack's title, so
        /companion/splice/cover?pack=<title> gives it), cached; None when the page names none."""
        with self.lock:
            known = self.index.get("@link " + link)
        if known:
            return known
        got = self.own_pack(self.page(link))
        if not got:
            return None
        title, path = got
        with self.lock:
            has = self.index.get(title, {}).get("state") == "found"
        if not has:
            done = self.cover(title, title, path)
            with self.lock:
                self.index[title] = {**(done or {"state": "none", "why": "the pack page has no image"}), "at": time.time()}
        result = {"title": title, "path": path, "page": "https://splice.com" + path}
        with self.lock:
            self.index["@link " + link] = result
            self.save()
        return result

    def find(self, pack):
        # First by a sound of the pack's own: the catalog's sound of the same file name is from the same pack, whatever
        # the pack's title. Up to three of its files, the longest names first (the likeliest to be one of a kind).
        for name in sorted(set(self.files_of(pack)), key=len, reverse=True)[:3]:
            stem = re.sub(r"\.[a-z0-9]{2,4}$", "", name, flags=re.I)
            text = self.mcp.call("describe_a_sound", {"query": " ".join(re.findall(r"[A-Za-z0-9#]+", stem))[:200]})
            for found, link in results(text)[:5]:
                if found.lower() != name.lower():
                    continue
                got = self.own_pack(self.page(link))
                if got:
                    done = self.cover(pack, *got)
                    if done:
                        return {**done, "by": "sound"}
                break
        # Else by the pack's name: a sound whose pack is titled like the folder.
        text = self.mcp.call("describe_a_sound", {"query": pack})
        links = re.findall(r"\*\*Link:\*\* (\S+)", text)[:4]
        # The sounds' pages name their packs: an exact title first, else the first that fits.
        best = None
        for link in links:
            sample = self.page(link)
            m = re.search(r'og:title" content="[^"]*? from (.+?) \| Splice', sample)
            if not m:
                continue
            title = html.unescape(m.group(1))
            own = re.search(r'/sounds/packs/[a-z0-9_-]+/' + re.escape(slug(title)) + r'\b', sample)
            if not own or not fits(pack, title):
                continue
            if exact(pack, title):
                best = (title, own.group(0))
                break
            best = best or (title, own.group(0))
        if best:
            done = self.cover(pack, *best)
            if done:
                return {**done, "by": "name"}
        return {"state": "none", "why": "no sound or pack of it among the results"}
