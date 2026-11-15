# SPDX-License-Identifier: AGPL-3.0-only
"""The Splice sounds on this Mac, for the companion (docs/KIT_MANAGER_PLAN.md 5.1).

The Splice app keeps the sounds one has downloaded in a folder per pack
(~/Splice/sounds/packs/<Pack>/...). This lists them for the Kits page's
Sounds, serves them to hear, and copies one to the MPC's card
(Melodee/Samples/Splice/<Pack>/) when it goes on a pad, so the kit plays
without the Mac. Only audio files under the folder are ever read; nothing
is written on the Mac.
"""
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

AUDIO = {".wav", ".aif", ".aiff", ".flac", ".ogg", ".oga", ".mp3"}
TYPES = {".wav": "audio/wav", ".aif": "audio/aiff", ".aiff": "audio/aiff", ".flac": "audio/flac", ".ogg": "audio/ogg",
         ".oga": "audio/ogg", ".mp3": "audio/mpeg"}
CARD_DIR = ["Melodee", "Samples", "Splice"]
GOT = "Got with Melodee"   # the top folder the Splice source shows ~/Music/Melodee Splice as (Describe a kit's sounds)
PACK_CHARS = 40   # a kit holds a sample's whole path in 160 bytes: /media/<card>/Melodee/Samples/Splice/<pack>/<file>
FILE_CHARS = 60


def default_root():
    """~/Splice/sounds/packs, else ~/Splice/sounds, else ~/Splice."""
    base = Path.home() / "Splice"
    for p in (base / "sounds" / "packs", base / "sounds", base):
        if p.is_dir():
            return p
    return base / "sounds" / "packs"


def shortened(name, most):
    """`name` cut to `most` characters, its extension kept."""
    if len(name) <= most:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot or len(ext) > 5:
        return name[:most].strip()
    return stem[:most - len(ext) - 1].strip() + "." + ext


class SpliceLibrary:
    def __init__(self, root, got=None):
        self.root = Path(root).expanduser().resolve()
        self.got = Path(got).expanduser() if got else None
        self.lock = threading.Lock()
        self.listed, self.listed_at = None, 0.0

    def available(self):
        return self.root.is_dir()

    def sounds(self):
        """{"source", "files": [path under the root...], "sizes": [...], "full"}; walked again after 30 s."""
        with self.lock:
            if self.listed is not None and time.time() - self.listed_at < 30:
                return self.listed
            files, sizes = [], []
            for base, prefix in [(self.root, "")] + ([(self.got, GOT + "/")] if self.got and self.got.is_dir() else []):
                self.walk(base.resolve(), prefix, files, sizes)
            self.listed = {"source": "splice", "files": files, "sizes": sizes, "full": False}
            self.listed_at = time.time()
            return self.listed

    def forget(self):
        with self.lock:
            self.listed = None

    def walk(self, base, prefix, files, sizes):
        for top, dirs, names in os.walk(base):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for name in sorted(names):
                if name.startswith(".") or Path(name).suffix.lower() not in AUDIO:
                    continue
                path = Path(top) / name
                if path.is_symlink():
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                files.append(prefix + path.relative_to(base).as_posix())
                sizes.append(size)

    def place(self, rel):
        """The file `rel` names under the root, or None: no way out of the folder, audio only, no hidden parts."""
        if not rel or rel.startswith("/") or "\\" in rel or any(p in ("", ".", "..") or p.startswith(".") for p in rel.split("/")):
            return None
        base = self.root
        if rel.startswith(GOT + "/") and self.got:
            base, rel = self.got.resolve(), rel[len(GOT) + 1:]
        path = (base / rel).resolve()
        if base not in path.parents or not path.is_file() or path.suffix.lower() not in AUDIO:
            return None
        return path

    def cover(self, pack):
        """A cover one put in a pack's folder (cover.jpg, .png or .webp): (bytes, type), or (None, None)."""
        if not pack or "/" in pack or pack.startswith("."):
            return None, None
        for ext, kind in (("jpg", "image/jpeg"), ("jpeg", "image/jpeg"), ("png", "image/png"), ("webp", "image/webp")):
            path = self.root / pack / ("cover." + ext)
            if path.is_file():
                return path.read_bytes(), kind
        return None, None

    def icon(self):
        """The installed Splice app's own icon as a small PNG (read from the app at run time, never kept in the
        repository: it is Splice's), or None."""
        if not hasattr(self, "_icon"):
            self._icon = None
            for app in (Path("/Applications/Splice.app"), Path.home() / "Applications/Splice.app"):
                icns = app / "Contents/Resources/app.icns"
                if not icns.is_file():
                    continue
                with tempfile.TemporaryDirectory() as temp:
                    out = Path(temp) / "icon.png"
                    made = subprocess.run(["sips", "-s", "format", "png", "--resampleWidth", "64", str(icns), "--out", str(out)],
                                          capture_output=True)
                    if made.returncode == 0 and out.is_file():
                        self._icon = out.read_bytes()
                break
        return self._icon

    @staticmethod
    def credits():
        """One's Splice credits as the Splice app last saved them (its appState.json, user.credits), and when: (n, unix
        time) or (None, None). Only that number is read."""
        state = Path.home() / "Library/Application Support/com.splice.Splice/appState.json"
        try:
            n = json.loads(state.read_text()).get("user", {}).get("credits")
            return (int(n), state.stat().st_mtime) if isinstance(n, (int, float)) else (None, None)
        except (OSError, ValueError):
            return None, None

    def hello(self):
        packs = 0
        if self.available():
            packs = sum(1 for p in self.root.iterdir() if p.is_dir() and not p.name.startswith("."))
        credits, at = self.credits()
        return {"splice": self.available(), "root": str(self.root), "packs": packs, "icon": self.icon() is not None,
                "credits": credits, "creditsAt": at}

    def import_to_card(self, rel, mpc):
        """Copies a sound of the folder to Melodee/Samples/Splice/<Pack>/ on the card (see copy_to_card). The card id."""
        path = self.place(rel)
        if path is None:
            raise LookupError("No such sound in the Splice folder")
        parts = rel.split("/")
        pack = parts[1] if parts[0] == GOT and len(parts) > 2 else parts[0] if len(parts) > 1 else "Sounds"
        return copy_to_card(path, pack, mpc)


def copy_to_card(path, pack, mpc):
    """Copies a file on the Mac to Melodee/Samples/Splice/<pack>/ on the card through `mpc` (the MPC's own Files
    requests: mkdir, list, upload); a copy already there with the same name and size is used again. The card id."""
    pack = shortened(pack, PACK_CHARS)
    name = shortened(path.name, FILE_CHARS)
    where = ""
    for part in CARD_DIR + [pack]:
        status, data = mpc("POST", "/mkdir", {"path": where, "name": part})
        if status == 200:
            part = json.loads(data).get("name", part)
        elif status != 409:
            raise OSError(json.loads(data or b"{}").get("error", "Could not make a folder on the card"))
        where = part if not where else where + "/" + part
    status, data = mpc("GET", "/list", {"path": where})
    size = path.stat().st_size
    if status == 200:
        stem, ext = os.path.splitext(name)
        for e in json.loads(data).get("entries", []):
            n = e.get("name", "")
            if not e.get("dir") and e.get("size") == size and n.lower().endswith(ext.lower()) and \
                    (n.lower() == name.lower() or (n.lower().startswith(stem.lower() + " ") and n[len(stem) + 1:-len(ext) or None].isdigit())):
                return "sd:%s/%s" % (where, n)
    status, data = mpc("POST", "/upload", {"path": where, "name": name}, path.read_bytes())
    if status != 200:
        raise OSError(json.loads(data or b"{}").get("error", "Could not copy it to the card"))
    return "sd:%s/%s" % (where, json.loads(data)["name"])
