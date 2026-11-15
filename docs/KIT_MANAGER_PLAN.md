# Melodee MPC Sample — Kit Manager & Splice Library Integration

The plan the Kit Manager is built to, as written by the fork's owner. It
names the upstream repository (keremimo/melodee-sample, Melodee by Kerem
Kiliç, Ellic Studio); the work happens in a fork. What has been built so far,
and what was found, is in [KIT_MANAGER.md](KIT_MANAGER.md): Milestones 0–2
are implemented; Milestones 3 and 4 (Splice) are not started.

## 1. Objective

Extend keremimo/melodee-sample with a browser-based Kit Manager that can:

1. Browse factory kits stored on the MPC Sample’s internal storage.
2. Browse custom kits and projects stored on the SD card.
3. Inspect kit contents, including pad assignments and sample settings.
4. Audition individual samples from the browser.
5. Create, duplicate, edit and save custom kits.
6. Browse locally available samples from the user’s Splice library.
7. Import Splice samples into custom kits.
8. Investigate direct Splice account integration, including the user’s saved sounds and named Collections.

Primary requirement: Normal kit-management operations must not require rebooting the MPC Sample or restarting Melodee.

Initial workflow: Create and save a kit in the browser, then load it using Melodee’s existing on-device Project → Load kit workflow.

Do not implement live updates to the active project in the initial version.

## 2. Existing architecture and constraints

Repository: https://github.com/keremimo/melodee-sample

Relevant source files identified during preliminary inspection:

| File | Responsibility |
| --- | --- |
| `src/melodee/web/static/shell.html` | Existing browser interface |
| `src/melodee/web/web_app.cpp` | HTTP routes, file browsing and upload/download |
| `src/melodee/web/card_files.h` | SD-card path validation and file operations |
| `src/melodee/shell/project_kits.h` | Existing kit import logic |
| `docs/guide/projects-and-files.md` | Project formats, factory storage and loading behavior |
| `tools/web_bundle.py` | Bundles web assets |

### Confirmed existing behavior

* Melodee exposes a web interface at http://melodee.local or http://192.168.155.1.
* The existing web interface can browse, preview, upload and delete SD-card files.
* The MPC’s internal storage contains factory Kits, Demos and projects.
* Internal storage is read-only.
* Melodee supports loading kits from both internal storage and the SD card.
* Melodee supports stock MPC Sample .xpj projects and its native .mldp projects.
* Loading a kit from the on-device project browser does not load its patterns.
* Existing kit-import code supports importing a kit or individual bank into a track.

### Important architectural limitation

The current web API is centered on SD-card file operations. Factory-kit access is available through Melodee’s on-device project browser, but has not yet been exposed through the HTTP API.

Do not assume the existing web server can already read factory kits or their sample audio. Investigate and reuse the on-device implementation.

### Compatibility

Preserve existing project formats and existing Melodee behavior.

Do not introduce a separate, incompatible kit format unless unavoidable. Prefer native Melodee project serialization and the existing kit import mechanisms.

The repository is AGPL-3.0 licensed. Preserve licensing requirements and existing source conventions.

## 3. Product design

Introduce a new Kits section in the existing Melodee web interface.

The Kit Manager should have three primary areas:

* Factory Kits: Internal, read-only MPC Sample kits.
* My Kits: Custom kits on the SD card, including kits extracted from supported projects.
* Sample Browser: Samples from the SD card, local files and eventually the user’s Splice library.

### 3.1 Kit browser

Display kits in a searchable list or grid.

Each entry should include:

* Kit name.
* Source: Factory or SD card.
* Number of populated pads.
* Read-only/editable status.
* Actions: Open, Preview, Duplicate and, for editable kits, Rename/Delete.

Do not assume every project is a kit. Only show projects with a valid kit track or clearly indicate when no usable kit exists.

### 3.2 Kit editor

Display a 4×4 pad grid matching the MPC Sample’s physical pad arrangement.

Support the existing eight-bank model (A–H), where applicable.

Selecting a pad should show:

* Assigned sample name.
* Sample waveform or basic preview.
* Sample source/path.
* Playback controls.
* Supported pad parameters, such as volume, pan, tune, start/end and play mode.
* Multiple sample layers where supported by the project format.

For the MVP, prioritize correct sample assignment and playback. Add advanced pad parameters incrementally.

### 3.3 Kit creation

Support:

* Create empty kit.
* Duplicate a factory kit.
* Duplicate a custom kit.
* Replace a pad’s sample.
* Clear a pad.
* Rename a kit.
* Save as a new kit.

Factory kits must never be modified.

Duplicating a factory kit should produce an editable SD-card project with valid references to all required samples.

## 4. Backend implementation

### 4.1 Shared kit discovery

Implement a backend service that discovers supported kit sources and exposes normalized metadata.

Avoid duplicating project parsing logic already used by Melodee.

The service should distinguish:

* Internal factory projects.
* SD-card .mldp projects.
* Supported stock .xpj projects.
* Other supported bank/kit formats, if applicable.

Suggested internal model:

```ts
type KitSummary = {
  id: string;
  name: string;
  source: "factory" | "sd";
  format: "mldp" | "xpj" | "bank";
  readOnly: boolean;
  padCount: number;
  bankCount: number;
};
type KitDetail = KitSummary & {
  banks: Array<{
    index: number;
    pads: Array<{
      index: number;
      name: string;
      layers: Array<{
        sampleId: string;
        sampleName: string;
        samplePath?: string;
      }>;
    }>;
  }>;
};
```

These TypeScript types describe the proposed API contract, not necessarily the C++ implementation.

IDs must be stable and safely map to validated storage locations. Never trust arbitrary browser-provided absolute paths.

### 4.2 Proposed HTTP endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/kits` | List factory and SD kits |
| GET | `/api/kits/:id` | Inspect kit metadata and pad assignments |
| GET | `/api/kits/:id/pads/:pad/preview` | Preview sample audio |
| POST | `/api/kits` | Create an empty kit |
| POST | `/api/kits/:id/duplicate` | Duplicate kit to SD |
| PUT | `/api/kits/:id` | Save edited custom kit |
| DELETE | `/api/kits/:id` | Delete custom kit |

Exact endpoint naming can change to fit the repository’s conventions.

Use the existing HTTP server and routing architecture. Do not introduce a separate MPC-side server unless necessary.

### 4.3 Serialization and sample references

Investigate native .mldp serialization before implementing writes.

Requirements:

* New kits must load through Melodee’s existing project browser.
* Pad/sample assignments must survive save and reload.
* Sample references must resolve correctly on the MPC.
* Internal factory sample references must remain valid after duplication.
* Missing samples must produce useful warnings.
* Saving must not overwrite unrelated projects.
* Use temporary files and atomic replacement where supported.
* Reject path traversal and unauthorized writes.

Prefer invoking existing project serialization code rather than constructing project files manually.

### 4.4 Audio preview

Browser audition must not alter the currently playing project.

Investigate how factory samples are represented and decoded.

Prefer serving existing compatible audio files directly. Where the browser cannot decode a source format, implement a lightweight conversion or preview path.

Preview generation must not block the real-time audio thread.

If a factory sample cannot be previewed, show its metadata and an explicit unsupported-preview state rather than failing the entire kit.

## 5. Splice integration

Splice support has two distinct requirements:

1. Access the user’s locally downloaded/licensed Splice samples.
2. Access the user’s actual Splice account library, including saved sounds and named Collections.

These must not be treated as equivalent.

### 5.1 Phase one: Local Splice library

Implement a lightweight Mac companion service.

Its responsibilities:

* Discover or configure the user’s local Splice sample directory.
* Recursively index supported audio files.
* Expose sample metadata to the Kit Manager.
* Support searching, filtering and auditioning samples.
* Upload selected samples to the MPC’s SD card.
* Preserve sample provenance and avoid duplicate imports.

The default Splice directory on macOS may be ~/Splice, but the location must be configurable.

Suggested companion API:

```
GET  /api/library/samples
GET  /api/library/samples/:id
GET  /api/library/samples/:id/audio
POST /api/library/samples/:id/import
```

The companion should communicate with the MPC’s existing HTTP interface.

Avoid introducing cloud infrastructure, accounts or databases unless justified.

### 5.2 Sample metadata

Extract or infer:

* Filename.
* Local file path.
* Duration.
* Audio format.
* Sample rate.
* Channels.
* BPM, if available.
* Musical key, if available.
* Instrument/category, if available.
* Source: Splice/local/SD.
* Imported-to-MPC status.

Do not present guessed BPM/key as verified metadata.

Use filename parsing as an initial fallback, with explicit unknown values where necessary.

### 5.3 Named Splice Collections

This is a product requirement, but currently an unresolved integration capability.

Investigate whether Splice exposes an officially supported method to retrieve:

* The authenticated user’s licensed sounds.
* Their saved/liked sounds.
* Named Collections.
* Collection membership.
* Sample metadata.
* Audio preview URLs.
* Licensed sample downloads.

Do not assume the local ~/Splice folder contains Collection membership.

If an official integration is unavailable, implement a flat local sample library first and document the limitation. Do not scrape private Splice APIs or rely on undocumented authentication endpoints.

### 5.4 Splice MCP investigation

Investigate the official Splice MCP server:

https://mcp.splice.com/mcp

Determine:

1. Which tools are actually available.
2. Whether OAuth authentication works from a custom client.
3. Whether the user’s existing Splice subscription is sufficient.
4. Whether a separate developer account or commercial agreement is required.
5. Whether tools expose personal library and Collections.
6. Whether downloads provide usable file bytes or local artifacts.
7. Whether Splice’s terms permit embedding the integration in a custom browser application.

Do not assume MCP access is equivalent to a public REST API.

Keep any authentication tokens on the Mac companion, never in MPC firmware or browser-persisted secrets.

### 5.5 Splice-to-kit workflow

Target user experience:

1. Open Kit Manager.
2. Select My Splice Library.
3. Browse or search available samples.
4. Audition a kick, snare, hat or other sound.
5. Assign it to a kit pad.
6. Import the required audio to the MPC’s SD card.
7. Save the kit.
8. Load the kit on the MPC Sample.

Imported kits must remain playable without the Mac connected.

## 6. Implementation milestones

### Milestone 0 — Technical investigation

Before modifying project serialization, inspect:

* Factory/internal storage discovery.
* Existing .xpj and .mldp readers.
* Native project writers.
* Sample reference resolution.
* Bank/kit import behavior.
* Web server threading and file access.
* Audio decoding and preview options.

Deliver a short technical note documenting confirmed behavior, unknowns and chosen approach.

Acceptance: Demonstrate that a factory kit and an SD-card kit can be parsed into the same normalized model, or clearly identify the blocker.

### Milestone 1 — Read-only Kit Browser

Implement:

* Factory kit listing.
* SD-card kit listing.
* Kit details.
* Bank and pad inspection.
* Sample audition where supported.

Acceptance: The browser can inspect a factory kit without modifying it or interrupting MPC playback.

### Milestone 2 — Kit Creation and Editing

Implement:

* Empty kit creation.
* Factory kit duplication.
* Custom kit duplication.
* Pad sample assignment.
* Kit renaming.
* Save to SD card.

Acceptance: Create a 16-pad kit, save it, load it using the MPC’s existing Project → Load kit operation, and play the assigned samples without rebooting.

### Milestone 3 — Local Splice Integration

Implement:

* Mac companion.
* Local Splice indexing.
* Sample search/filter.
* Audio preview.
* Sample upload and pad assignment.
* Offline-safe kit saving.

Acceptance: Select a locally downloaded Splice sample, assign it to a pad, save the kit, disconnect the Mac, and play it on the MPC.

### Milestone 4 — Splice Account/Collections Proof of Concept

Investigate and prototype supported Splice authentication and personal library access.

Acceptance: Either demonstrate retrieval of real Collection names and membership using an authorized interface, or provide a documented blocker and an alternative user workflow.

Only proceed to a production account integration after this validation.

## 7. Non-goals for MVP

Do not implement:

* Live editing of the MPC’s currently loaded kit.
* Automatically loading a saved kit into the running project.
* Two-way synchronization between browser and MPC.
* Pattern or song editing.
* Full DAW functionality.
* A replacement for the existing MPC project browser.
* Unsupported Splice scraping or credential extraction.
* A cloud-hosted user account system.

## 8. Testing and quality requirements

Implement tests for:

* Factory kit parsing.
* SD-card kit parsing.
* Empty and partially populated kits.
* Multi-bank kits.
* Multi-layer pads.
* Missing or moved sample files.
* Kit duplication.
* Save/reload round trips.
* Path traversal prevention.
* Read-only factory storage enforcement.
* Insufficient SD-card space.
* Interrupted writes.
* Unsupported audio formats.
* Companion disconnected or unavailable.
* Duplicate Splice sample imports.

Hardware testing must confirm:

* No reboot is needed for normal kit operations.
* Existing MPC playback remains unaffected by browser browsing and previews.
* Saved kits appear in the existing project browser.
* Saved kits load correctly and play offline.

## 9. Engineering instructions

* Follow existing repository architecture and coding conventions.
* Prefer incremental changes over broad refactoring.
* Reuse native project parsing, serialization and sample-loading code.
* Keep browser/UI changes lightweight.
* Avoid expensive operations on the audio thread.
* Maintain backward compatibility with existing projects.
* Treat factory storage as strictly read-only.
* Keep Splice integration modular and optional.
* Add focused tests for each new backend capability.
* Update documentation for the new web workflows.
* Do not silently invent unsupported APIs or data structures.

## 10. Definition of done

The core feature is complete when a user can:

1. Connect an MPC Sample running Melodee to a Mac.
2. Open http://melodee.local.
3. Browse and inspect factory kits.
4. Audition supported factory samples.
5. Duplicate a factory kit or create an empty kit.
6. Assign samples, including locally downloaded Splice samples.
7. Save the new kit to the SD card.
8. Load it using the MPC’s existing kit-loading interface.
9. Play the kit without restarting Melodee or keeping the Mac connected.

Personal Splice Collections and direct account integration are a separate milestone, subject to official API capabilities.

## 11. Instructions to the implementing agent

Start with Milestone 0. Inspect the actual repository code and document the architecture before writing new code.

Then implement Milestones 1 and 2 as the first deliverable. Prefer a small, working end-to-end path over building a large UI without functional persistence.

After the core kit workflow works, implement the local Splice companion.

Investigate official Splice MCP/account access independently, and report what is confirmed versus what remains unsupported.

For each milestone, provide:

* Files changed.
* Architectural decisions.
* Tests added and run.
* Hardware-dependent tests still required.
* Known limitations.
* Instructions for trying the feature.

Do not claim that hardware behavior or Splice integration has been verified unless it has actually been tested.
