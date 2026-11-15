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
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
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
            for top, dirs, names in os.walk(self.root):
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
                    files.append(path.relative_to(self.root).as_posix())
                    sizes.append(size)
            self.listed = {"source": "splice", "files": files, "sizes": sizes, "full": False}
            self.listed_at = time.time()
            return self.listed

    def place(self, rel):
        """The file `rel` names under the root, or None: no way out of the folder, audio only, no hidden parts."""
        if not rel or rel.startswith("/") or "\\" in rel or any(p in ("", ".", "..") or p.startswith(".") for p in rel.split("/")):
            return None
        path = (self.root / rel).resolve()
        if self.root not in path.parents or not path.is_file() or path.suffix.lower() not in AUDIO:
            return None
        return path

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

    def hello(self):
        packs = 0
        if self.available():
            packs = sum(1 for p in self.root.iterdir() if p.is_dir() and not p.name.startswith("."))
        return {"splice": self.available(), "root": str(self.root), "packs": packs, "icon": self.icon() is not None}

    def import_to_card(self, rel, mpc):
        """Copies the sound to Melodee/Samples/Splice/<Pack>/ on the card through `mpc` (the MPC's own Files requests:
        mkdir, list, upload); a copy already there with the same name and size is used again. The card id."""
        path = self.place(rel)
        if path is None:
            raise LookupError("No such sound in the Splice folder")
        pack = shortened(rel.split("/")[0] if "/" in rel else "Sounds", PACK_CHARS)
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
