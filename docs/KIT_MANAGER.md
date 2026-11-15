# Kit Manager: technical note (Milestone 0)

The web page's **Kits** tab: browse the MPC's factory kits and the kits on
the card, audition their samples, and make and edit kits of one's own that
the MPC's existing **Project → Load kit** loads. This note records what the
code does today (read from the source, not from a device), what is unknown,
and the approach the Kit Manager takes. Splice (Milestones 3 and 4) is out of
scope here. The full plan, Milestones 0–4, is
[KIT_MANAGER_PLAN.md](KIT_MANAGER_PLAN.md).

Melodee is the work of Kerem Kiliç (Ellic Studio); this feature is built in a
fork on top of it.

## Confirmed behaviour (from the source)

### Factory / internal storage

- `shell/project_store.cpp` names the internal drive's folders:
  `/content/Projects/Kits` (factory kits), `/content/Projects/Demos`
  (factory demos), `/data/TempProjects` (stock autosave) and
  `/data/UserContent/Projects/User` (the stock app's own projects,
  `$MELODEE_INTERNAL_PROJECTS` on a host). The factory sample library is
  `/content/Samples` (`shell/sample_library.cpp`).
- Every one of those is read only to Melodee: `write_dir()` never returns a
  folder on the internal drive, and the project sheet offers only Load and
  Load kit there.
- Factory kits are stock `.xpj` projects. `tests/test_mpc_project.py`
  (`test_two_members`) records their shape: a gzip member with the five
  header lines, then a second gzip member with the JSON. Their samples sit
  beside them in `<name>_[ProjectData]/`.

### Readers

- `.xpj`: `import_mpc_project()` (`shell/mpc_project.cpp`, JUCE's JSON and
  gzip) turns the project into a Melodee `Project`. Each Drum track becomes a
  kit track; each pad's sample becomes a `SampleRef` whose path is the
  absolute path of the file in `<name>_[ProjectData]/` (only the file name
  from the JSON is used, so a project cannot point outside its folder).
  Pads of two or more layers become an "instrument" reference
  `<file>.xpj#<track>.<pad>`; `layers_from_programs()`
  (`shell/mpc_program.cpp`) then turns them into real pad layers where the
  files are found and slots allow. `ProjectStore`'s `import_mpc()` runs
  exactly these two steps.
- `.mldp`: `load_project()` (`model/project_file.cpp`), a tagged-section
  format that skips sections it does not know. JUCE-free.
- `.xpm` / `.xty` drum programs: `import_mpc_program()`. Not part of this
  milestone's listing (see Unknowns).
- `.mldb` bank files: `load_bank()`; one bank of sixteen pads. Not listed.

### Writer

- `save_project()` writes a full `Project` and its `PatternBank` (plug-in
  states and prints optional). `ProjectStore` saves through `<path>.new`
  and `rename()`, so a pulled card never leaves half a file.
- The format holds samples by absolute path (`SampleRef::path`, 160 bytes),
  64 sample slots a project, 16 tracks, 128 pads a kit (banks A–H), four
  layers a pad.

### Kit model and Load kit

- A kit is a Sampler track: `Track::pads` (128 `PadSound`), each pad's
  `sample` an index into `Project::samples`, with up to three more
  `layers`.
- `kit_track()` (`shell/project_kits.cpp`) picks the first Sampler track
  with a sample on a pad. `import_kit()` copies that track's pads, pad FX and
  kit values onto another track, asking for a sample slot by path. Load kit
  on the MPC (`Context::load_kit_file()` → `ProjectStore::load()` →
  `Context::load_kit()`) runs these on the project the store read, either
  `.mldp` or `.xpj` (imported first), and does not touch patterns.
- So a project file whose first kit track has pads, with sample paths that
  exist, is everything Load kit needs. No new format is needed.

### Sample references

- Paths are absolute: `/media/<card>/Samples/...` for the card,
  `/content/...` for factory files. The sampler resolves nothing relative;
  `Context::sample_slot()` reuses a slot that already holds the same path.
- A missing file leaves the pad silent (the import counts it as missing).

### Web server, threading and file access

- `web/web_server.cpp`: one thread, one connection at a time, each closed
  after its reply. Requests other than GET/HEAD need an `X-Melodee` header;
  the Host must be an IP, localhost or `.local` (DNS rebinding). Files are
  streamed from disk (`Reply::file`), never read whole.
- `web/web_app.cpp`: the service thread publishes `Facts` (the card's mount
  while it is home, empty when lent to a computer); the web thread never
  touches the project, the engine or the audio thread. `files_changed`
  tells the service thread to `rescan()` the sample library and project
  store, so the MPC's project list sees new files without a restart.
- `web/card_files.cpp`: `card_place()` resolves a browser path under a root
  and refuses `..`, dot names, backslashes, links that leave the root,
  `autorun/` and `sample-base/`.

### Audio decoding

- The sampler reads WAV itself and FLAC, Ogg, AIFF and MP3 through JUCE
  (`shell/sample_decode.cpp`), on the service thread.
- The web page's Files tab plays card files by serving them as they are
  (`file_type()` gives the MIME type) to the browser's `<audio>`.

## Unknowns (need the hardware)

- The exact file names, sample formats and bit depths inside the factory
  kits' `_[ProjectData]` folders. The reader handles any WAV; a browser
  plays 16/24-bit PCM and 32-bit float WAV. If a factory kit uses something
  else, preview says unsupported and the kit still opens.
- How long a factory `.xpj` takes to parse on the MPC's CPU. The listing
  caches each file's summary by size and modification time so it is
  parsed once a session.
- Whether a firmware update can move `/content/Projects/Kits`. A duplicated
  factory kit refers to the factory samples where they are (as Melodee's
  own Save of an opened `.xpj` does); if they moved, the pads would report
  missing.
- Whether the web thread reading the card while the MPC streams samples
  from it affects playback. The web thread is the same one that already
  serves the Files tab; nothing new runs on the audio thread.

## Chosen approach

One normalized path for every source:

```
factory .xpj ─┐                                ┌─ GET /kits, /kits/kit (JSON)
card .xpj    ─┼─ existing readers → Project ───┤
card .mldp   ─┘   (import_mpc_project +        └─ edits → save_project → .mldp
                   layers_from_programs,
                   or load_project)
```

- **Reading**: `web/kit_store.{h,cpp}` reads any kit file with the readers
  above into a `Project`, takes `kit_track()`, and describes its pads. A
  factory kit and a card kit go through the same code and give the same
  JSON (Milestone 0's acceptance, covered by `tests/kit_store.cpp`).
- **IDs**: `factory:<path under /content/Projects>` and `sd:<path under the
  card>`. Every ID is resolved with `card_place()` against its own root, so
  a browser can never name an absolute path or leave the root.
- **Where kits are written**: only `Melodee/Projects/Kits/` on the card.
  Those `.mldp` files are the only ones the Kit Manager edits, renames or
  deletes. Every other kit (factory, stock `.xpj`, Melodee projects with
  songs) is read only here and can be duplicated into Kits. This keeps the
  Kit Manager from rewriting a project someone is working on.
- **Writing**: a new kit is `starting_project()` (Melodee's own new
  project: one empty kit on track 1); a duplicate is `import_kit()` of the
  source's kit onto that track (the same call Load kit makes); an edit is
  `load_project()` → change pads → `save_project()`. Plug-in states and
  prints are carried through a load and save. Files are written to a hidden
  temporary file, flushed, and renamed over the target.
- **Sample references**: kept absolute, as Melodee writes them. A sample
  assigned from the browser is named by `sd:<path>` or `factory:<path under
  /content/Samples>` and resolved on the MPC; only audio the sampler reads
  (WAV, AIFF, FLAC, Ogg, MP3) is taken. Duplicating a factory kit keeps its
  references to the factory files.
- **Preview**: the pad's file is served as it is, after checking that it is
  under the card or the factory folders and is an audio type. Instruments
  (`.sfz`, `#pad` references) and unknown types answer "no preview"; the
  page shows that per pad. Nothing is decoded on the MPC and the project in
  play is not touched.
- **After a write**: the page sets `files_changed`, the service thread
  rescans, and the kit is in the MPC's project list (`Kits` folder) to Load
  kit without a reboot.

No blocker was found. No project serialization code changes.

## Implementation (Milestones 1 and 2)

### HTTP API

All under the existing server (`web/web_app.cpp`, `kit_request()`), with
the repository's query-string style. POSTs need the `X-Melodee` header like
every other write.

| Method | Path | Does |
| --- | --- | --- |
| GET | `/api/kits` | Factory and card kits: `id`, `name`, `source`, `format`, `readOnly`, `padCount`, `bankCount`, `kit`, `folder`, `error` |
| GET | `/api/kits/kit?id=` | The summary, `track`, `open`, `warnings`, and eight `banks` of used pads (values and `layers`: `sampleName`, `samplePath`, `kind`, `missing`, `preview`) |
| GET | `/api/kits/audio?id=&pad=&layer=` | The layer's file as it is (404 missing, 415 no browser preview) |
| GET | `/api/kits/samples?source=sd\|factory&path=` | A folder to pick samples from |
| GET | `/api/kits/sample?sample=` | A sample's file, to audition before assigning |
| GET | `/api/kits/sounds?source=sd\|factory` | Every sound under the source (`files`, paths under it; `full` when the 40000 limit was reached), searched in the page |
| POST | `/api/kits/new?name=` | An empty kit in `Melodee/Projects/Kits` |
| POST | `/api/kits/duplicate?id=&name=` | Any kit's first kit, copied into a new kit there |
| POST | `/api/kits/pad?id=&pad=&sample=\|clear=1&level=&pan=&pitch=&fine=&play=` | One pad changed and the kit saved |
| POST | `/api/kits/rename?id=&name=` | Rename a kit of one's own |
| POST | `/api/kits/delete?id=` | Delete a kit of one's own |

A successful POST sets `files_changed`, so the MPC's project list rescans
and shows the kit without a restart.

### Decisions

- Endpoints are `/api/kits...` with query parameters, not path segments
  and JSON bodies: the server has no router or JSON reader, and IDs hold
  slashes. The page itself is `/kits`.
- A pad edit is one request that loads, changes and saves the whole kit.
  Kit files are small, and it means there is never a half-saved state in
  the browser.
- Assigning a sample to a pad that had one keeps its level, pan, tune,
  envelope and other values, and resets its region and layers to the new
  file. A sample slot no pad plays any more is freed, so a kit can keep
  being edited within the 64-sample limit.
- `/api/kits/audio` serves only plain audio files under the card or the
  factory folders. The path comes from the kit file, so a crafted `.mldp`
  cannot make the page serve other files.
- Pad parameters editable now: level, pan, tune, fine and play type. The
  rest (region, envelope, filter, mute group, layer play) is shown, not
  edited.

### Playing pads in the browser

- The page fetches each pad's file once and decodes it with Web Audio, so a
  press sounds at once; the same decoded audio draws the pad's waveform. The
  open bank's pads are fetched in turn, one request at a time, since the
  server answers one at a time; a pad pressed before its turn is fetched at
  once.
- A press plays the pad's region (`start`–`end`, in the file's frames, read
  from the WAV header) at its level, pan and tune; Note on pads stop on
  release; a mute group chokes the others in it. Layers, velocity, envelopes
  and filters are not played. The playhead is the Web Audio clock less the
  output latency, so the line meets the sound.
- Keys by `KeyboardEvent.code`: 1-4, Q-R, A-F, Z-V are pads 13-16 to 1-4 of
  the open bank, so any keyboard layout plays the same places.
- `/api/kits/audio` keeps each layer's reply for the last kit played while
  its file's size and time stay the same, and forgets it on any pad edit,
  rename or delete: reading a factory `.xpj` takes about 0.4 s on the MPC,
  which every press used to pay.

### Layout, search and drag and drop

- Three columns that fill the window under the top bar: kits, the open
  kit (pads beside the pad's details), and Sounds. Only the columns scroll;
  below 760 px wide they stack and the page scrolls.
- Search fetches `/api/kits/sounds` once a visit for the source and matches
  every typed word in the path, in the page; the first 300 matches show.
  The walk skips hidden names, links, and `autorun/` and `sample-base/` at
  the card's top, as `card_place()` does, ten folders down at most.
- A sound row drags with `application/x-melodee-sound` (its id); a pad
  takes the drop and assigns it with `/api/kits/pad`. On a read-only kit the
  page asks for a name, duplicates the kit, and assigns on the copy.

### Speed

Measured on an MPC Sample over USB: a request costs about 5 ms (name, connection, a 110 KB sample sent in 1 ms).
Reading a kit costs about 0.4 s: a stock `.xpj` is a 50 KB gzip of about 3 MB of JSON, and JUCE's parse of it is
nine tenths of that (47 ms of it on an Apple M-series host, gunzip 4 ms). So the Kits tab reads a kit as seldom as
it can:

- `reading()` makes a kit's details and every pad layer's audio reply in one read, kept for the last six kits while
  their files' size and time stay the same: opening a kit and playing its pads is one read, not one per request.
- A factory kit's reading is also kept on the card (`Melodee/.cache/kits/<hash>.kit`, keyed by path, size and
  time): factory kits never change, so each is read once at all, across restarts. Card kits are not kept there.
- The listing's summaries are kept in `Melodee/.cache/kit-summaries`, written when a listing has read every kit:
  after the first start the list is complete at once. A listing reads for 250 ms at most and names the rest
  `pending`, so the server (one request at a time) stays quick while the page asks again.
- Every write here (pad, rename, delete) forgets what was read of that kit: a FAT card's two-second clock cannot
  always tell the new file from the old.
- `Connection: close` stays: with one request at a time, a browser's idle kept-alive connections would hold the
  server, and on a USB link a new connection costs about a millisecond.

The page shows waiting: a thin bar under the top bar for anything one asked for that takes over 120 ms (preloads
and the list filling in are quiet), the kit row pulsing while it opens, a pad pulsing until its sound is in or
while it is saved, and New, Duplicate, Rename, Delete and Assign held while a change is written.

### Tests

`tests/test_kit_store.py` builds `web/kit_store.cpp` with Melodee's
readers and JUCE's core for the host (`python3 tools/dependencies.py`
first) and covers: a factory kit and the same kit on the card giving the
same model; listing; multi-layer pads; missing samples; preview; factory
files unchanged after list, open and duplicate; the sample browser;
duplicating a factory kit and a custom kit; a 16-pad, two-bank kit saved
and read back; replacing and clearing pads; the 64-sample limit; rename
(also by case) and delete; read-only kits (factory, stock `.xpj`, other
`.mldp`) refusing changes; path traversal and hidden or system paths;
unsupported audio; no card; a full card (where the test can mount a small
tmpfs); a failed write leaving the kit as it was; an unreadable project.

### Hardware tests still required

None of the following has been tried on an MPC Sample:

- Factory kits list and open, and how long the first listing takes.
- Factory sample formats play in the browser.
- Browsing and previewing while the MPC plays leaves playback unaffected.
- A kit made or duplicated here shows in the project list's `Kits` folder
  without a restart, Load kit loads it, and its pads play (with the MPC
  disconnected from the computer).
- A duplicated factory kit's samples play from the internal drive.

### Known limitations

- Only a project's first kit is shown (the one Load kit takes).
- The stock app's own projects on the internal drive, `.xpm`/`.xty`
  programs and `.mldb` bank files are not listed.
- A pad that plays an instrument (an `.sfz`, or a stock layered pad whose
  layers could not be split) has no preview. A pad plays its first layer the
  browser can play, without velocity, envelope or filter.
- Duplicating a factory kit refers to its samples on the internal drive;
  it does not copy them to the card.
- Editing a kit that is open on the MPC is allowed with a warning: the
  MPC's next save of that project writes over it.
- Not tested in Safari's or Firefox's AIFF/FLAC support; the browser says
  when it cannot play a file.

### Working on the page without firmware

`python3 tools/companion/companion.py` (the start of the Mac companion,
Milestone 3) serves the page's files from `src/melodee/web/static` and passes
every other request, writes too, to the MPC at `melodee.local`. Open
http://localhost:8800/kits: a change to the page is a reload away, with the
MPC's own kits and sounds. Firmware is built only for a change on the MPC's
side (`web/kit_store.cpp`), and to put the page's latest into the page the
MPC carries for use without the Mac.

### Try it

1. Build and install as usual (`./build.sh`, then `python3 device.py start`
   or a release on the card).
2. Connect the MPC by USB-C and open **http://melodee.local/kits**.
3. Open a factory kit, click pads to hear them, press **Duplicate**.
4. In the copy, pick a pad, choose a sample under **Assign a sample**,
   press **Assign**.
5. On the MPC: **SHIFT** + **Pad 16**, **B2**, open **Kits**, push on the
   kit, **Load kit**, and play the pads.
