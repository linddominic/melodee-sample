# SPDX-License-Identifier: AGPL-3.0-only
"""Splice's catalog through the official MCP, for the companion (docs/KIT_MANAGER_SPLICE.md).

search(): describe_a_sound, its Markdown answer read into rows (10 a search:
the tool has no pages). get(): download_asset (one credit the first time a
sound is downloaded, free after; asked first on the page), the file kept on
the Mac in ~/Music/Melodee Splice/<label>/ and copied to the card like the
Splice folder's sounds. A per-session limit on gets guards the credits.
"""
import re
import threading
from pathlib import Path

from splice_library import shortened
from splice_mcp import http

DOWNLOADS = Path.home() / "Music" / "Melodee Splice"


def rows(text):
    """The sounds of a describe_a_sound answer: name, bpm, key, duration, type, label, tags, link, uuid."""
    out = []
    for block in re.split(r"\n(?=### \d+\. )", text):
        head = re.match(r"### \d+\. (.+)", block)
        if not head:
            continue
        def field(name):
            m = re.search(r"\*\*%s:\*\* *(.+)" % name, block)
            return m.group(1).strip() if m else ""
        facts = dict(re.findall(r"(BPM|Key|Duration|Type): *([^|\n]+)", block))
        bpm = re.match(r"\d+", facts.get("BPM", "").strip())
        dur = re.match(r"[\d.]+", facts.get("Duration", "").strip())
        out.append({
            "name": head.group(1).strip(), "bpm": int(bpm.group(0)) if bpm else 0, "key": facts.get("Key", "").strip(),
            "duration": float(dur.group(0)) if dur else 0.0, "type": facts.get("Type", "").strip().lower(),
            "label": field("Pack"), "tags": [t.strip() for t in field("Tags").split(",") if t.strip()],
            "link": field("Link"), "uuid": field("Asset UUID"),
        })
    return out


def total(text):
    m = re.search(r"Showing (\d+) of (\d+)", text)
    return int(m.group(2)) if m else 0


def safe(part):
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", part).strip(" .") or "Splice"


class SpliceCatalog:
    def __init__(self, mcp, limit=20):
        self.mcp = mcp
        self.limit = limit          # gets a session may make: credits are money
        self.spent = 0
        self.lock = threading.Lock()

    def search(self, query, kind="", bpm_min=0, bpm_max=0):
        args = {"query": query}
        if kind in ("oneshot", "loop"):
            args["type"] = kind
        if bpm_min:
            args["bpm_min"] = int(bpm_min)
        if bpm_max:
            args["bpm_max"] = int(bpm_max)
        text = self.mcp.call("describe_a_sound", args)
        return {"query": query, "total": total(text), "sounds": rows(text), "gets": self.spent, "limit": self.limit}

    def pack(self, seed, covers):
        """The pack of a catalog sound (`seed`: one of its rows) and the sounds of it the catalog's search finds: a
        search per kind, "<title> kick", "<title> snare"..., keeping those of the same label whose names start as the
        seed's do (a pack's files share a prefix: "MDT_Kick_Hit_10"); 10 a search, so not always all of the pack."""
        about = covers.pack_of(seed["link"]) if seed.get("link") else None
        title = about["title"] if about else seed.get("label", "")
        prefix = re.match(r"[A-Za-z0-9]+", seed["name"])
        prefix = prefix.group(0).lower() if prefix and len(prefix.group(0)) >= 2 and not prefix.group(0).isdigit() \
            and prefix.group(0).lower() not in ("kick", "snare", "clap", "hat", "hats", "perc", "bass", "fx", "vox", "loop", "one", "drum") else ""
        sounds, seen = [seed], {seed["uuid"]}
        for kind, words in (("oneshot", "kick"), ("oneshot", "snare"), ("oneshot", "clap"), ("oneshot", "hat"), ("oneshot", "percussion"),
                            ("oneshot", "808 bass"), ("oneshot", "fx"), ("oneshot", "vocal"), ("oneshot", "chord stab synth"), ("loop", "loop")):
            text = self.mcp.call("describe_a_sound", {"query": "%s %s" % (title, words), "type": kind})
            for s in rows(text):
                if s["uuid"] in seen or s["label"].lower() != seed.get("label", "").lower():
                    continue
                if prefix and not s["name"].lower().startswith(prefix):
                    continue
                seen.add(s["uuid"])
                sounds.append(s)
        return {"title": title, "label": seed.get("label", ""), "page": about["page"] if about else "", "sure": bool(prefix),
                "sounds": sounds}

    def local(self, name, label):
        path = DOWNLOADS / safe(label) / safe(name)
        return path if path.is_file() else None

    def get(self, uuid, name, label):
        """The sound's file on the Mac: kept from before, else bought and downloaded. (path, fresh)."""
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", uuid or ""):
            raise LookupError("Not a Splice sound")
        kept = self.local(name, label)
        if kept:
            return kept, False
        with self.lock:
            if self.spent >= self.limit:
                raise PermissionError("This session's limit of %d gets is reached (companion --credit-limit)" % self.limit)
            self.spent += 1
        try:
            text = self.mcp.call("download_asset", {"asset_uuid": uuid})
        except Exception:
            with self.lock:
                self.spent -= 1
            raise
        url = re.search(r"https://[^\s)\]>\"'*`]+", text) # plain, or inside Markdown's [name](url)
        if not url:
            raise OSError(text.strip()[:300] or "Splice gave no file")
        status, _, data = http(url.group(0), timeout=120)
        if status != 200 or not data:
            raise OSError("The download failed (%d)" % status)
        path = DOWNLOADS / safe(label) / safe(shortened(name, 120))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path, True
