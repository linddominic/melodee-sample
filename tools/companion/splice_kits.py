# SPDX-License-Identifier: AGPL-3.0-only
"""Describe a kit: the official Splice MCP's sound search, a search per pad, to a 16-pad draft (docs/KIT_MANAGER_SPLICE.md).

draft(): "dark minimal techno, 128" becomes "<words> kick", "<words> snare"...
(describe_a_sound, one-shots), each pad given the best match and a few more
to swap to; melodic pads lean to the key most of the melodic matches share.
get(): download_asset (one credit the first time a sound is downloaded, free
after; the page asks first), the file kept in ~/Music/Melodee Splice/<label>/,
which the Splice source in Sounds also lists. A per-session limit guards the
credits. Splice's own pages are never read: only the MCP and the Mac's files.
"""
import re
import threading
from collections import Counter
from pathlib import Path

from splice_library import shortened
from splice_mcp import http

DOWNLOADS = Path.home() / "Music" / "Melodee Splice"

# The pads, 1-16, as the MPC's factory kits have them: what each is, and the words searched for it. Pads of the same
# words share one search (the second kick is the kick search's next match).
PADS = [("Kick", "kick"), ("Snare", "snare"), ("Closed hat", "closed hi hat"), ("Open hat", "open hi hat"),
        ("Kick 2", "kick"), ("Clap", "clap"), ("Perc", "percussion"), ("Perc 2", "shaker rim"),
        ("808", "808 bass"), ("Snare 2", "snare"), ("Cymbal", "crash cymbal"), ("FX", "fx impact"),
        ("Chord", "chord stab"), ("Synth", "synth stab"), ("Vocal", "vocal chop"), ("Pluck", "pluck")]
MELODIC = {"Chord", "Synth", "Vocal", "Pluck", "808"}
# What a sound must say of itself (its name or Splice's tags) to be taken for a pad: Splice's search weighs the
# description more than the pad's word, so "dark techno 808" can answer a percussion hit.
FITS = {
    "kick": r"\bkicks?\b|\bkik\b|\bbd\b", "snare": r"\bsnares?\b|\bsnr\b", "closed hi hat": r"\bhats?\b|hihat|hi[ _-]hat|\bhh\b|\bch\b",
    "open hi hat": r"\bopen\b|\boh\b|\bhats?\b|hihat", "clap": r"\bclaps?\b|\bclp\b",
    "percussion": r"perc|shaker|\brim|\btoms?\b|conga|bongo|tamb|cowbell|clave|block",
    "shaker rim": r"shaker|\brim|perc|tamb|clave|block", "808 bass": r"\b808s?\b|\bbass\b|\bsub\b",
    "crash cymbal": r"crash|\bride\b|cymbal|china", "fx impact": r"\bfx\b|impact|riser|sweep|noise|whoosh|transition",
    "chord stab": r"chords?\b|\bstabs?\b|\bkeys\b|piano", "synth stab": r"synth|\bstabs?\b|\blead\b|\bpad\b",
    "vocal chop": r"vocals?|\bvox\b|voice|chop", "pluck": r"plucks?\b|synth|\bkeys\b",
}


def fits(words, sound):
    said = (sound["name"].replace("_", " ") + " " + " ".join(sound["tags"])).lower()
    return re.search(FITS[words], said) is not None


def rows(text):
    """The sounds of a describe_a_sound answer (Markdown): name, bpm, key, duration, type, label, tags, link, uuid."""
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


def safe(part):
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", part).strip(" .") or "Splice"


class SpliceKits:
    def __init__(self, mcp, limit=20):
        self.mcp = mcp
        self.limit = limit          # gets a session may make: credits are money
        self.spent = 0
        self.lock = threading.Lock()

    def draft(self, text, mark):
        """{"text", "pads": [{"pad", "role", "words", "choices": [sound...]}...]}: a pad's first choice is its pick.
        `mark(sounds)` marks those one has already (free)."""
        text = " ".join(text.split())[:120]
        found = {}
        for _, words in PADS:
            if words in found:
                continue
            # The pad's word first, then the description's; again the other way round, then the pad's word alone,
            # until three sounds that are what the pad wants are found. Else the best there was.
            good, seen, first = [], set(), []
            for query in ("%s %s" % (words, text), "%s %s" % (text, words), words):
                answer = [s for s in rows(self.mcp.call("describe_a_sound", {"query": query, "type": "oneshot"})) if s["uuid"]]
                first = first or answer
                good += [s for s in answer if s["uuid"] not in seen and fits(words, s)]
                seen.update(s["uuid"] for s in answer)
                if len(good) >= 3:
                    break
            found[words] = good or first
            mark(found[words])
        keys = Counter(s["key"] for role, words in PADS if role in MELODIC for s in found[words][:4] if s["key"])
        key = keys.most_common(1)[0][0] if keys else ""
        used, pads = set(), []
        for n, (role, words) in enumerate(PADS):
            choices = [s for s in found[words] if s["uuid"] not in used]
            if key and role in MELODIC:
                choices.sort(key=lambda s: s["key"] != key)   # stable: in key first, the search's order kept
            if choices:
                used.add(choices[0]["uuid"])
            pads.append({"pad": n + 1, "role": role, "words": words, "choices": choices[:6]})
        return {"text": text, "key": key, "pads": pads, "gets": self.spent, "limit": self.limit}

    def local(self, name, label):
        path = DOWNLOADS / safe(label) / safe(shortened(name, 120))
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
        url = re.search(r"https://[^\s)\]>\"'*`]+", text)  # plain, or inside Markdown's [name](url)
        if not url:
            raise OSError(text.strip()[:300] or "Splice gave no file")
        status, _, data = http(url.group(0), timeout=120)
        if status != 200 or not data:
            raise OSError("The download failed (%d)" % status)
        path = DOWNLOADS / safe(label) / safe(shortened(name, 120))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path, True
