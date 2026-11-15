# SPDX-License-Identifier: AGPL-3.0-only
"""The web page's Kits tab (src/melodee/web/kit_store.cpp, docs/KIT_MANAGER.md), built for the host with JUCE's
core (the .xpj reader needs it): factory and card kits read into one model, kits made, edited, renamed and
deleted in Melodee/Projects/Kits only, and every id kept inside its root."""
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_mpc_project import HEADER, instrument, project, wav  # noqa: E402

JUCE = ROOT / "build/deps/JUCE/modules"
SOURCES = ["src/melodee/web/kit_store.cpp", "src/melodee/web/card_files.cpp", "src/melodee/web/web_server.cpp",
           "src/melodee/shell/mpc_project.cpp", "src/melodee/shell/mpc_program.cpp", "src/melodee/model/project_file.cpp",
           "src/melodee/shell/project_kits.cpp", "src/melodee/engine/engine_info.cpp", "src/melodee/model/pattern.cpp",
           "src/melodee/model/print.cpp", "src/melodee/engine/keygroup.cpp", "src/melodee/engine/sfz.cpp",
           "src/melodee/engine/pad_fx_info.cpp"]
FLAGS = ["-I" + str(ROOT / "src"), "-I" + str(ROOT / "base/src"), "-I" + str(JUCE), "-DJUCE_GLOBAL_MODULE_SETTINGS_INCLUDED=1",
         "-DJUCE_STANDALONE_APPLICATION=1", "-DJUCE_USE_CURL=0", "-DNDEBUG"]


def layered(samples):
    """An MPC pad of several layers, each a whole file."""
    pad = instrument(samples[0])
    pad["layersv"] = [dict(pad["layersv"][0], sampleFile=s) for s in samples]
    return pad


def factory_kit(folder, name, pads, files):
    """A factory kit as /content/Projects/Kits keeps one: two gzip members, its samples beside it."""
    folder.mkdir(parents=True, exist_ok=True)
    data = folder / (name + "_[ProjectData]")
    data.mkdir()
    for f in files:
        (data / f).write_bytes(wav(44100))
    path = folder / (name + ".xpj")
    path.write_bytes(gzip.compress(HEADER.encode()) + gzip.compress(json.dumps(project(pads)).encode()))
    return path


@unittest.skipUnless(sys.platform.startswith("linux") and (JUCE / "juce_core").is_dir(),
                     "needs Linux and JUCE in build/deps (python3 tools/dependencies.py)")
class KitStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        out = Path(cls.build.name)
        cxx, cc = os.environ.get("CXX", "c++"), os.environ.get("CC", "cc")
        subprocess.run([cc, "-O1", "-w", *FLAGS, "-c", str(JUCE / "juce_core/juce_core_zlib.c"), "-o", str(out / "zlib.o")], check=True)
        subprocess.run([cxx, "-std=c++17", "-O1", "-w", "-pthread", *FLAGS, "-c", str(JUCE / "juce_core/juce_core.cpp"),
                        "-o", str(out / "juce_core.o")], check=True)
        # Melodee's own sources as the build takes them: no warnings
        subprocess.run([cxx, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror", "-pthread", *FLAGS, "-c",
                        str(ROOT / "src/melodee/web/kit_store.cpp"), "-o", str(out / "kit_store_check.o")], check=True)
        subprocess.run([cxx, "-std=c++17", "-O1", "-pthread", *FLAGS, str(ROOT / "tests/kit_store.cpp"),
                        *[str(ROOT / s) for s in SOURCES], str(JUCE / "juce_core/juce_core_CompilationTime.cpp"),
                        str(out / "juce_core.o"), str(out / "zlib.o"), "-ldl", "-o", str(out / "kit_store")], check=True)
        cls.binary = out / "kit_store"

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        top = Path(self.temp.name)
        self.card, self.factory, self.factory_samples = top / "card", top / "content/Projects", top / "content/Samples"
        for f in (self.card, self.factory, self.factory_samples):
            f.mkdir(parents=True)
        # A factory kit: one pad, a second of two layers, a third whose file is gone.
        factory_kit(self.factory / "Kits", "Boom Kit", [instrument("Kick.wav", 10, 90), layered(["Snare.wav", "Clap.wav"]),
                                                        instrument("Gone.wav")], ["Kick.wav", "Snare.wav", "Clap.wav"])
        (self.factory_samples / "Drums").mkdir()
        (self.factory_samples / "Drums/Hat.wav").write_bytes(wav(44100))
        # The same kit on the card, in the stock app's folder.
        factory_kit(self.card / "MPC-Sample/Projects", "Boom Kit", [instrument("Kick.wav", 10, 90), layered(["Snare.wav", "Clap.wav"]),
                                                                    instrument("Gone.wav")], ["Kick.wav", "Snare.wav", "Clap.wav"])
        samples = self.card / "Samples/Drums"
        samples.mkdir(parents=True)
        for n in range(70):
            (samples / ("Hit %02d.wav" % n)).write_bytes(wav(44100))
        (samples / "notes.txt").write_text("not audio")
        (self.card / "autorun").mkdir()
        (self.card / "autorun/melodee").write_text("binary")

    def tearDown(self):
        self.temp.cleanup()

    def run_store(self, action, card=None, **query):
        args = [str(self.binary), str(card if card is not None else self.card), str(self.factory), str(self.factory_samples), action]
        args += ["%s=%s" % (k, v) for k, v in query.items()]
        result = subprocess.run(args, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        status, _, body = result.stdout.partition("\n")
        return int(status), json.loads(body)

    def ok(self, action, **query):
        status, body = self.run_store(action, **query)
        self.assertEqual(status, 200, body)
        return body

    def pads(self, detail):
        return {p["label"]: p for b in detail["banks"] for p in b["pads"]}

    # ---- Milestone 0 / 1: reading ----

    def test_list_factory_and_card_kits(self):
        kits = self.ok("list")["kits"]
        by_id = {k["id"]: k for k in kits}
        factory = by_id["factory:Kits/Boom Kit.xpj"]
        self.assertEqual((factory["source"], factory["format"], factory["readOnly"], factory["kit"]), ("factory", "xpj", True, True))
        self.assertEqual((factory["padCount"], factory["bankCount"]), (3, 1))
        stock = by_id["sd:MPC-Sample/Projects/Boom Kit.xpj"]
        self.assertEqual((stock["source"], stock["readOnly"]), ("sd", True))
        self.assertFalse(any("ProjectData" in k["id"] for k in kits))

    def test_list_names_kits_before_reading_them(self):
        body = self.ok("list-twice")
        quick, full, after = body["quick"], body["full"], body["after"]
        self.assertEqual(quick["pending"], len(quick["kits"]))
        self.assertTrue(all(k["pending"] for k in quick["kits"]))
        self.assertEqual([k["id"] for k in quick["kits"]], [k["id"] for k in full["kits"]])
        self.assertIn("Boom Kit", [k["name"] for k in quick["kits"]])
        self.assertEqual(full["pending"], 0)
        # Read once, a listing with no time left still has every count.
        self.assertEqual(after["pending"], 0)
        self.assertEqual(after["kits"], full["kits"])

    def test_factory_kit_read_once_kept_on_the_card(self):
        first = self.ok("detail", id="factory:Kits/Boom Kit.xpj")
        records = list((self.card / "Melodee/.cache/kits").glob("*.kit"))
        self.assertEqual(len(records), 1)
        # A factory kit never changes, so a later start answers from the card: the same details, and pad audio,
        # even with the kit's sample folder gone (a fresh read would call the sample missing).
        shutil.move(str(self.factory / "Kits/Boom Kit_[ProjectData]"), str(self.factory / "Kits/elsewhere"))
        self.assertEqual(self.ok("detail", id="factory:Kits/Boom Kit.xpj"), first)
        shutil.move(str(self.factory / "Kits/elsewhere"), str(self.factory / "Kits/Boom Kit_[ProjectData]"))
        self.assertEqual(self.ok("audio", id="factory:Kits/Boom Kit.xpj", pad=0, layer=0)["type"], "audio/wav")
        # A damaged record is read past: the kit is read again.
        records[0].write_text("not a record")
        self.assertEqual(self.ok("detail", id="factory:Kits/Boom Kit.xpj"), first)
        # Card kits are not kept there: they can change.
        self.ok("detail", id="sd:MPC-Sample/Projects/Boom Kit.xpj")
        self.assertEqual(len(list((self.card / "Melodee/.cache/kits").glob("*.kit"))), 1)
        self.assertFalse(any("cache" in k["id"] for k in self.ok("list")["kits"]))

    def test_kit_summaries_kept_for_the_next_start(self):
        quick = self.ok("list-quick")
        self.assertEqual(quick["pending"], len(quick["kits"]))
        full = self.ok("list")
        self.assertTrue((self.card / "Melodee/.cache/kit-summaries").is_file())
        again = self.ok("list-quick") # a new start: nothing read yet, all known
        self.assertEqual(again["pending"], 0)
        self.assertEqual(again["kits"], full["kits"])
        # A kit changed since is read again.
        made = self.ok("create", name="Later")
        self.ok("pad", id=made["id"], pad=0, sample="sd:Samples/Drums/Hit 00.wav")
        later = {k["id"]: k for k in self.ok("list")["kits"]}
        self.assertEqual(later[made["id"]]["padCount"], 1)

    def test_factory_and_card_kit_share_one_model(self):
        factory = self.ok("detail", id="factory:Kits/Boom Kit.xpj")
        card = self.ok("detail", id="sd:MPC-Sample/Projects/Boom Kit.xpj")

        def shape(detail):
            return [[{k: v for k, v in p.items() if k != "layers"} | {"layers": [(l["sampleName"], l["missing"]) for l in p["layers"]]}
                     for p in b["pads"]] for b in detail["banks"]]
        self.assertEqual(shape(factory), shape(card))
        self.assertEqual(len(factory["banks"]), 8)
        pads = self.pads(factory)
        self.assertEqual(pads["A01"]["name"], "Kick")
        self.assertEqual((pads["A01"]["start"], pads["A01"]["end"], pads["A01"]["play"]), (10, 90, "oneshot"))
        self.assertTrue(pads["A01"]["layers"][0]["samplePath"].startswith("Factory/Projects/Kits/Boom Kit_[ProjectData]/"))
        self.assertTrue(card["banks"][0]["pads"][0]["layers"][0]["samplePath"].startswith("SD/MPC-Sample/Projects/"))

    def test_multi_layer_pad(self):
        pads = self.pads(self.ok("detail", id="factory:Kits/Boom Kit.xpj"))
        self.assertEqual([l["sampleName"] for l in pads["A02"]["layers"]], ["Snare", "Clap"])

    def test_missing_sample_warns(self):
        detail = self.ok("detail", id="factory:Kits/Boom Kit.xpj")
        gone = self.pads(detail)["A03"]["layers"][0]
        self.assertTrue(gone["missing"])
        self.assertFalse(gone["preview"])
        self.assertIn("1 sample is missing", detail["warnings"])
        status, body = self.run_store("audio", id="factory:Kits/Boom Kit.xpj", pad=2, layer=0)
        self.assertEqual(status, 404)

    def test_preview_serves_the_file(self):
        body = self.ok("audio", id="factory:Kits/Boom Kit.xpj", pad=0, layer=0)
        self.assertTrue(body["file"].endswith("Boom Kit_[ProjectData]/Kick.wav"))
        self.assertEqual(body["type"], "audio/wav")
        self.assertEqual(self.ok("sample", sample="factory:Drums/Hat.wav")["type"], "audio/wav")
        status, _ = self.run_store("sample", sample="sd:Samples/Drums/notes.txt")
        self.assertEqual(status, 415)

    def test_factory_files_untouched(self):
        before = {p: p.read_bytes() for p in self.factory.rglob("*") if p.is_file()}
        self.ok("list")
        self.ok("detail", id="factory:Kits/Boom Kit.xpj")
        self.ok("duplicate", id="factory:Kits/Boom Kit.xpj")
        self.assertEqual({p: p.read_bytes() for p in self.factory.rglob("*") if p.is_file()}, before)

    def test_sample_browser(self):
        body = self.ok("samples", source="sd", path="")
        names = [e["name"] for e in body["entries"]]
        self.assertIn("Samples", names)
        self.assertNotIn("autorun", names)
        self.assertEqual([e["name"] for e in self.ok("samples", source="factory", path="Drums")["entries"]], ["Hat.wav"])

    # ---- Milestone 2: making and editing ----

    def test_duplicate_factory_kit(self):
        dup = self.ok("duplicate", id="factory:Kits/Boom Kit.xpj")
        self.assertEqual(dup["id"], "sd:Melodee/Projects/Kits/Boom Kit copy.mldp")
        self.assertFalse(dup["readOnly"])
        self.assertTrue((self.card / "Melodee/Projects/Kits/Boom Kit copy.mldp").is_file())
        pads = self.pads(dup)
        self.assertEqual(sorted(pads), ["A01", "A02", "A03"])
        self.assertEqual([l["sampleName"] for l in pads["A02"]["layers"]], ["Snare", "Clap"])
        # The factory files are referred to where they are, so the copy plays them.
        self.assertTrue(pads["A01"]["layers"][0]["samplePath"].startswith("Factory/Projects/Kits/"))
        self.assertFalse(pads["A01"]["layers"][0]["missing"])
        self.assertEqual(self.ok("audio", id=dup["id"], pad=0, layer=0)["type"], "audio/wav")
        # Again: a free name, nothing written over.
        self.assertEqual(self.ok("duplicate", id="factory:Kits/Boom Kit.xpj")["id"], "sd:Melodee/Projects/Kits/Boom Kit copy 2.mldp")

    def test_pad_audio_follows_an_edit(self):
        # The server keeps each layer's file for the last kit played; a change to the kit is heard at once.
        made = self.ok("create", name="Replay")
        self.ok("pad", id=made["id"], pad=0, sample="sd:Samples/Drums/Hit 00.wav")
        body = self.ok("replay", id=made["id"], pad=0, sample="sd:Samples/Drums/Hit 01.wav")
        self.assertTrue(body["before"].endswith("/Hit 00.wav"), body)
        self.assertEqual(body["set"], 200)
        self.assertTrue(body["after"].endswith("/Hit 01.wav"), body)

    def test_sounds_for_search(self):
        (self.card / "autorun/boot.wav").write_bytes(wav(100))
        files = self.ok("sounds", source="sd")["files"]
        self.assertIn("Samples/Drums/Hit 00.wav", files)
        self.assertEqual(len([f for f in files if f.startswith("Samples/Drums/")]), 70)
        self.assertNotIn("Samples/Drums/notes.txt", files)
        self.assertFalse(any(f.startswith("autorun/") for f in files))
        (self.card / ".hidden").mkdir()
        (self.card / ".hidden/Secret.wav").write_bytes(wav(100))
        (self.card / "Samples/link.wav").symlink_to(self.factory_samples / "Drums/Hat.wav")
        files = self.ok("sounds", source="sd")["files"]
        self.assertFalse(any("Secret" in f or "link.wav" in f for f in files))
        self.assertEqual(self.ok("sounds", source="factory")["files"], ["Drums/Hat.wav"])
        self.assertEqual(self.run_store("sounds", source="elsewhere")[0], 400)
        self.assertEqual(self.run_store("sounds", card="-", source="sd")[0], 409)

    def test_sample_with_hash_in_its_path_plays(self):
        # A sample pack's folder named with a '#' is a plain file, not a pad of a program: it previews and plays.
        folder = self.card / "Samples/SKU#SM-1041 Piano/one-shots"
        folder.mkdir(parents=True)
        (folder / "Stab #1.wav").write_bytes(wav(44100))
        made = self.ok("create", name="Hash")
        kit = self.ok("pad", id=made["id"], pad=0, sample="sd:Samples/SKU#SM-1041 Piano/one-shots/Stab #1.wav")
        layer = self.pads(kit)["A01"]["layers"][0]
        self.assertEqual((layer["kind"], layer["preview"], layer["missing"]), ("file", True, False))
        self.assertTrue(self.ok("audio", id=made["id"], pad=0, layer=0)["file"].endswith("/Stab #1.wav"))

    def test_duplicate_custom_kit(self):
        made = self.ok("create", name="Mine")
        self.ok("pad", id=made["id"], pad=0, sample="sd:Samples/Drums/Hit 00.wav")
        dup = self.ok("duplicate", id=made["id"], name="Mine Two")
        self.assertEqual(dup["id"], "sd:Melodee/Projects/Kits/Mine Two.mldp")
        self.assertEqual(self.pads(dup)["A01"]["name"], "Hit 00")

    def test_create_sixteen_pad_kit_round_trip(self):
        made = self.ok("create", name="Sixteen")
        self.assertEqual(made["id"], "sd:Melodee/Projects/Kits/Sixteen.mldp")
        self.assertEqual((made["padCount"], made["kit"]), (0, False))
        self.assertIn("No pads yet: Load kit needs at least one", made["warnings"])
        for n in range(16):
            self.ok("pad", id=made["id"], pad=n, sample="sd:Samples/Drums/Hit %02d.wav" % n)
        self.ok("pad", id=made["id"], pad=16, sample="factory:Drums/Hat.wav") # bank B pad 1, a factory sample
        self.ok("pad", id=made["id"], pad=3, level=90, pan=-20, pitch=5, fine=-10, play="gate")
        again = self.ok("detail", id=made["id"]) # read back from the file
        self.assertEqual((again["padCount"], again["bankCount"], again["kit"]), (17, 2, True))
        self.assertEqual(again["warnings"], [])
        pads = self.pads(again)
        self.assertEqual(pads["A16"]["name"], "Hit 15")
        self.assertEqual(pads["B01"]["layers"][0]["samplePath"], "Factory/Samples/Drums/Hat.wav")
        self.assertEqual((pads["A04"]["level"], pads["A04"]["pan"], pads["A04"]["pitch"], pads["A04"]["fine"], pads["A04"]["play"]),
                         (90, -20, 5, -10, "gate"))
        self.assertEqual(pads["A04"]["name"], "Hit 03")
        listed = {k["id"]: k for k in self.ok("list")["kits"]}[made["id"]]
        self.assertEqual((listed["padCount"], listed["readOnly"]), (17, False))

    def test_replace_and_clear_pad(self):
        made = self.ok("create", name="Swap")
        self.ok("pad", id=made["id"], pad=0, sample="sd:Samples/Drums/Hit 00.wav")
        self.ok("pad", id=made["id"], pad=0, level=80)
        swapped = self.pads(self.ok("pad", id=made["id"], pad=0, sample="sd:Samples/Drums/Hit 01.wav"))
        self.assertEqual((swapped["A01"]["name"], swapped["A01"]["level"]), ("Hit 01", 80)) # its values stay
        cleared = self.ok("pad", id=made["id"], pad=0, clear=1)
        self.assertEqual(cleared["padCount"], 0)

    def test_sample_slots_fill_and_free(self):
        made = self.ok("create", name="Full")
        for n in range(64):
            self.ok("pad", id=made["id"], pad=n, sample="sd:Samples/Drums/Hit %02d.wav" % n)
        status, body = self.run_store("pad", id=made["id"], pad=64, sample="sd:Samples/Drums/Hit 64.wav")
        self.assertEqual(status, 409, body)
        # A pad's own sample swapped for another: its slot comes free first.
        self.ok("pad", id=made["id"], pad=0, sample="sd:Samples/Drums/Hit 65.wav")
        self.ok("pad", id=made["id"], pad=1, clear=1)
        self.ok("pad", id=made["id"], pad=64, sample="sd:Samples/Drums/Hit 66.wav")

    def test_rename_and_delete(self):
        made = self.ok("create", name="Old")
        other = self.ok("create", name="Taken")
        status, _ = self.run_store("rename", id=made["id"], name="Taken")
        self.assertEqual(status, 409)
        renamed = self.ok("rename", id=made["id"], name="New")
        self.assertEqual(renamed["id"], "sd:Melodee/Projects/Kits/New.mldp")
        self.assertFalse((self.card / "Melodee/Projects/Kits/Old.mldp").exists())
        self.assertEqual(self.ok("rename", id=renamed["id"], name="NEW")["id"], "sd:Melodee/Projects/Kits/NEW.mldp")
        self.ok("delete", id=other["id"])
        self.assertFalse((self.card / "Melodee/Projects/Kits/Taken.mldp").exists())
        self.assertEqual(sorted(p.name for p in (self.card / "Melodee/Projects/Kits").iterdir()), ["NEW.mldp"]) # no temporary left

    def test_read_only_kits_refuse_changes(self):
        song = self.card / "Melodee/Projects/Song.mldp" # a project of one's own, outside Kits
        made = self.ok("create", name="Song")
        shutil.copy(self.card / "Melodee/Projects/Kits/Song.mldp", song)
        for kit in ("factory:Kits/Boom Kit.xpj", "sd:MPC-Sample/Projects/Boom Kit.xpj", "sd:Melodee/Projects/Song.mldp"):
            with self.subTest(kit=kit):
                self.assertEqual(self.run_store("pad", id=kit, pad=0, sample="sd:Samples/Drums/Hit 00.wav")[0], 403)
                self.assertEqual(self.run_store("rename", id=kit, name="X")[0], 403)
                self.assertEqual(self.run_store("delete", id=kit)[0], 403)
        self.assertTrue(song.is_file())
        self.assertTrue(made)

    def test_paths_stay_inside_their_roots(self):
        (self.temp.name and Path(self.temp.name) / "secret.mldp").write_bytes(b"x")
        self.ok("create", name="Safe")
        for kit in ("sd:../secret.mldp", "factory:../../secret.mldp", "sd:Melodee/Projects/Kits/../../../../secret.mldp",
                    "/etc/passwd", "sd:/etc/passwd", "sd:autorun/melodee", "sd:Melodee/Projects/Kits/.hidden.mldp", "file:x"):
            with self.subTest(kit=kit):
                self.assertEqual(self.run_store("detail", id=kit)[0], 404)
                self.assertNotEqual(self.run_store("delete", id=kit)[0], 200)
        for sample in ("sd:../secret.mldp", "factory:../Projects/Kits/Boom Kit.xpj", "sd:autorun/melodee", "/etc/passwd"):
            with self.subTest(sample=sample):
                self.assertEqual(self.run_store("pad", id="sd:Melodee/Projects/Kits/Safe.mldp", pad=0, sample=sample)[0], 404)
                self.assertEqual(self.run_store("sample", sample=sample)[0], 404)
        self.assertEqual(self.run_store("pad", id="sd:Melodee/Projects/Kits/Safe.mldp", pad=0, sample="sd:Samples/Drums/notes.txt")[0], 415)
        self.assertEqual(self.run_store("pad", id="sd:Melodee/Projects/Kits/Safe.mldp", pad=128, sample="sd:Samples/Drums/Hit 00.wav")[0], 400)

    def test_names(self):
        self.assertEqual(self.ok("names", id="sd:Melodee/Projects/Kits/A.mldp", name=" Boom ")["file"], "Boom.mldp")
        self.assertFalse(self.ok("names", id="sd:Melodee/Projects/A.mldp", name="a/b")["editable"])
        self.assertEqual(self.ok("names", id="", name="a/b")["file"], "")
        self.assertEqual(self.ok("names", id="", name="x" * 24)["file"], "")

    def test_no_card(self):
        body = self.ok("list", card="-")
        self.assertFalse(body["card"])
        self.assertTrue(all(k["source"] == "factory" for k in body["kits"]))
        self.assertEqual(self.run_store("create", card="-", name="X")[0], 409)
        self.assertEqual(self.run_store("duplicate", card="-", id="factory:Kits/Boom Kit.xpj")[0], 409)

    def test_failed_write_keeps_the_kit(self):
        made = self.ok("create", name="Keep")
        self.ok("pad", id=made["id"], pad=0, sample="sd:Samples/Drums/Hit 00.wav")
        path = self.card / "Melodee/Projects/Kits/Keep.mldp"
        before = path.read_bytes()
        blocker = path.parent / ".Keep.mldp.part" # where the write goes first: taken, so it cannot be written
        (blocker / "x").mkdir(parents=True)
        status, _ = self.run_store("pad", id=made["id"], pad=1, sample="sd:Samples/Drums/Hit 01.wav")
        self.assertEqual(status, 500)
        self.assertEqual(path.read_bytes(), before)
        shutil.rmtree(blocker)
        self.assertEqual(self.ok("detail", id=made["id"])["padCount"], 1)

    def test_card_full(self):
        # A card with less room than a kit and the margin kept back: nothing is written, nothing left behind.
        small = Path(self.temp.name) / "small"
        small.mkdir()
        if subprocess.run(["mount", "-t", "tmpfs", "-o", "size=1m", "tmpfs", str(small)], capture_output=True).returncode:
            self.skipTest("mounting a small card needs root")
        try:
            status, body = self.run_store("create", card=small, name="Big")
            self.assertEqual(status, 507, body)
            self.assertEqual(list((small / "Melodee/Projects/Kits").iterdir()), [])
        finally:
            subprocess.run(["umount", str(small)])

    def test_not_a_project(self):
        (self.card / "Melodee/Projects").mkdir(parents=True)
        (self.card / "Melodee/Projects/Broken.mldp").write_bytes(b"garbage")
        listed = {k["id"]: k for k in self.ok("list")["kits"]}["sd:Melodee/Projects/Broken.mldp"]
        self.assertIn("error", listed)
        self.assertEqual(self.run_store("detail", id="sd:Melodee/Projects/Broken.mldp")[0], 422)


if __name__ == "__main__":
    unittest.main()
