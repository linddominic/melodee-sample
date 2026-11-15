# Projects and files

Previous: [MIDI and sync](midi-and-sync.md) · [Contents](../GUIDE.md) · Next: [Settings](settings.md)

## The Project page

Press **SHIFT** + **Pad 16**.

![Project](../images/screens/project.png)

- **B1** (**SAVE**): save the project. The first time, name it.
- **B2** (**OPEN**): the list of projects.
- **B3** (**NEW**): start a new project (asks first).

Or turn the encoder to pick one and push it.

The header shows **UNSAVED** in amber while the project has changes.

![The project list](../images/screens/projectlist.png)

In the list:

- Turn the encoder to move. **K1** jumps, **K2** sorts.
- Push the encoder or press **B3** to open a folder. **B1** goes back.
  At the top of `Melodee/Projects`, **B1** goes up to the card's own folders,
  so a project or kit anywhere on the card can be loaded. At the card's top,
  **B1** closes the list.
- **B2** switches between the card and the MPC's internal drive
  (**INTERNAL**). The internal drive holds the stock app's projects, its
  **Autosave**, and the factory **Demos** and **Kits**. It is read only:
  its projects have Load and Load kit.
- The list opens on the open project the first time, then where you left
  it. Each drive keeps its own folder and row.
- Push the encoder or press **B3** on a project to open its sheet. Its jobs
  are cards. The open project has Save, Save as new, Rename, Duplicate,
  Move to folder, New folder here, Open at start and Delete. Another
  project has Load and **Load kit** (no patterns) first, which loads its
  first kit onto the selected track.
- Save (or Load) is picked when the sheet opens. Turn the encoder to pick
  another card and push it. **B1** closes the sheet. Delete says **PRESS
  AGAIN**: push once more to delete.

![A project's sheet](../images/screens/filesheetscroll.png)

While a project loads, a Loading sheet shows its progress. The audio fades
out and back in.

## Naming

The Name sheet opens when you save or rename a project, sample, bank or
marker.

![The Name sheet](../images/screens/nameproject.png)

- The pads type like phone keys. Each pad shows the letter it types next.
  Pad 14 types a space, pad 15 switches to digits, pad 16 deletes.
- Turn the encoder to move the cursor. **K1** chooses a suggested name.
- **K2**, or **SHIFT** + encoder, changes the character under the cursor.
- **ERASE** deletes. **SHIFT** + **ERASE** clears the name.
- **B2** switches between capitals and lower case.
- **B3** (**SAVE**) or encoder push saves. **B1** cancels.

## MPC Sample projects

Melodee opens stock MPC Sample projects (`.xpj`), wherever they are on the
card. When the card has the stock app's `MPC-Sample/Projects` folder, the
project list shows it as the **MPC Sample** folder. Press **B2**
(**INTERNAL**) for the projects on the MPC's internal drive, with the
factory demos and kits.

Their sheet has Load and Load kit. Load opens a copy. The stock project is
not changed. Save makes a Melodee
project (`.mldp`) that plays the samples from where they are.

- Each Drum track becomes a kit track. Each sequence becomes that numbered
  pattern, with its tempo.
- Carried over: pad regions, tune, volume, pan, play type, mono, mute
  group, envelope, loop, Warp, filter, and pads with several layers.
- Not carried over: Pad FX, insert effects, sends and songs.

## SD card access

Connect the MPC to a computer to copy files to and from the card, without
taking it out.

1. Connect the MPC to the computer with a USB-C cable.
2. Open the project list (**SHIFT** + **Pad 16**, **B2**) and push the
   encoder on **SD card access** at the top.
3. The card appears on the computer as a drive. Copy your files.
4. Eject the drive on the computer.
5. Press **B1** (**EJECT**). Melodee reads the card again.

![SD card access](../images/screens/cardaccess.png)

While the card is mounted on the computer, the pads still play the selected track.
USB audio and USB MIDI keep working. If you press **B1** before you eject
the drive, Melodee asks whether to eject anyway.

## Files on the card

| Folder | Contents |
| --- | --- |
| `autorun/` | Melodee itself. Do not change it. |
| `Melodee/Projects/` | Projects (`.mldp`), and each project's `Loops` and `Prints` folders |
| `Melodee/Mixdowns/` | Song mixdowns |
| `Melodee/Stems/` | Stems |
| `Melodee/MIDI/` | Exported MIDI files |
| `Melodee/Sounds/` | Sounds you save |
| `Melodee/Cache/` | Decoded instrument samples. Safe to delete: Melodee makes them again. |
| `Melodee/Plugins/` | VST3, LV2, CLAP and VST2 plug-ins |
| `Melodee/Plugin Data/` | Plug-in settings and presets |
| `Melodee/Crashes/` | Crash reports, one file a crash (see [Troubleshooting](exit-and-troubleshooting.md#troubleshooting)) |
| `Melodee/settings` | Melodee's settings |
| `Samples/` | Your samples. Melodee writes `Recorded/`, `Edits/`, `Banks/`, `Looper/` and `Expansions/` here. |
| `SysEx/` | `.syx` files for MIDI tracks |

## The web page

While Melodee runs, connect the MPC to a computer with USB-C and open
**http://melodee.local** (or **http://192.168.155.1**) in a browser. It has
five tabs:

- **Device**: the version running, the card's free space and the plug-ins
  in `Melodee/Plugins`. Drop a Melodee release zip on **Update** and press
  **Send** (see [Update Melodee](#update-melodee)), or a plug-in's
  `-mpc-sample.zip` on **Plug-ins** and press **Install** (see
  [What runs](plug-ins.md#what-runs)).
- **Files**: the folders on the card. Play audio files in the browser,
  download files, upload files (with **Upload** or by dropping them on the
  list), make folders and delete files or folders. The browser asks before
  it deletes. An upload never replaces a file of the same name.
  `autorun` and `sample-base` are not shown.
- **Kits**: the factory kits and the kits on the card. See
  [Kits in the browser](#kits-in-the-browser).
- **Quickstart** and **Manual**: the quickstart and this guide. They work
  without an internet connection.

Uploads wait while the card is on a computer with SD card access. When
Melodee stops, the MPC's own web page comes back.

## Kits in the browser

The **Kits** tab lists the MPC's factory kits (read only) and the projects
on the card that hold a kit: `Melodee/Projects` and the stock app's
`MPC-Sample/Projects`. Search the list, or show only **Factory**,
**My kits** or **SD card**.

- The page has three columns: the kits on the left, the open kit's pads
  in the middle, and **Sounds** on the right. It fits the window; each
  column scrolls on its own.
- Click a kit to open it. Its pads are laid out as on the MPC, pad 13 at
  the top left, pad 1 at the bottom left. **A** to **H** switch banks.
- Each pad shows its sample's waveform, with the pad's region bright and
  the rest of the file dim. Press a pad to hear it: a line runs across the
  waveform as it plays. The browser plays the pad's region at its level,
  pan and tune, a **Note on** pad only while you hold it, and a pad in a
  mute group stops the others in its group.
- A sound stops when it can no longer be seen: a pad of another bank or
  kit, or a sound gone from the list. **Stop** above Sounds (or **Esc**
  outside a text box) stops everything.
- Play the pads from the computer's keyboard: **1** to **4** are the top
  row (pads 13 to 16), then **Q** to **R**, **A** to **F**, and **Z** to
  **V** the bottom row (pads 1 to 4). The keys go by their place on the
  keyboard, so other layouts work too.
- Click a pad to see its sample, its layers and its level, pan, tune and
  play type. A pad whose sample is missing has a red edge. A pad that plays
  an instrument (an SFZ or a stock layered pad) shows no waveform and no
  preview.
- **New kit** makes an empty kit. **Duplicate** copies any kit, a factory
  one too, into an editable kit of your own.
- **Sounds**, on the right, browses the card or the factory samples by
  folder. Each sound shows its waveform, and a line runs across it as it
  plays. Under its name: its folder, whether it is a one-shot or a loop,
  what it is (kick, snare, hat, 808, vocal, FX…), and its BPM and key when
  its name says them. These are read from the names of the file and its
  folders, so they can be wrong.
- Type in **Search sounds** to find a sound anywhere under the folder you
  are in: every word must fit the file's name, its folders or what it is
  ("hat" also finds `HH_01.wav`). Matches in the file's name come first.
  **One-shots** and **Loops**, and the categories under them with how many
  there are, narrow the list; a category alone lists every sound of it.
- Folders whose name fits the words show above the sounds, with how many
  sounds are in each: open one and the search box searches in it. **✕**
  beside the folder's path searches everything again, and **‹** (or
  Backspace in the list) goes back to where you were, with the words,
  filters and scroll you had. A long path shows its last two folders; **…**
  shows the rest.
- Click a sound to hear it. With the list or the search box in use, **↑**
  and **↓** step through the sounds and play each, **Enter** puts the one
  picked on the pad picked, and **Esc** clears the search.
- With the Kits page opened through the Mac companion
  (`python3 tools/companion/companion.py`, then http://localhost:8800/kits),
  **Splice** in Sounds lists the packs the Splice app has downloaded to the
  Mac. A Splice sound put on a pad is copied to `Melodee/Samples/Splice` on
  the card first, so the kit plays without the Mac.
- **Kit from this folder** (in any folder or pack) puts sounds that belong
  together on the pads: kicks, snares, hats, claps and percussion on the
  bottom rows, then 808 or bass, cymbal and FX, and melodic and vocal hits in
  the folder's most common key on the top row. In a kit of your own it fills
  the empty pads of the bank in view; otherwise it makes a new kit named
  after the folder. Each go picks again.
- Drag a sound onto a pad to put it there. In a kit of your own you can
  also pick a pad and press **Assign** on a sound. Dropping a sound on a
  factory kit, or another kit that is read only, asks for a name and makes
  an editable copy with the sound on that pad.
- In a kit of your own, change a pad's level, pan, tune or play type, or
  **Clear pad**. Each change is saved to the card at once. **Rename** and
  **Delete** work on your own kits.

A kit keeps each sample's whole path on the card, and has room for about
150 characters of it. A sample deeper in a pack's folders than that is
copied to `Melodee/Samples/Kits` on the card when you put it on a pad, and
the pad plays the copy; putting the same sample on another pad uses the
same copy.

Your kits are saved in `Melodee/Projects/Kits` on the card. To play one,
open the project list on the MPC (**SHIFT** + **Pad 16**, **B2**), open
the **Kits** folder, push the encoder on the kit and pick **Load kit**.
Its pads load onto the selected track. A kit needs at least one pad with
a sample before Load kit takes it.

A duplicated factory kit plays the factory samples from the MPC's
internal drive, where they are. Factory kits, the stock app's projects and
your other Melodee projects are never changed from the browser.

If you edit a kit in the browser while it is the project open on the MPC,
saving that project on the MPC writes over the browser's changes. The
Kits tab warns you when this can happen.

## Update Melodee

1. Download the new release zip (`Melodee-MPC-Sample-<version>.zip`).
   Do not unzip it.
2. Copy the zip to the top level of the card, with **SD card access** or
   a card reader. Or send it from a browser: with the MPC connected to the
   computer by USB-C, open **http://melodee.local** (or **http://192.168.155.1**), choose the zip
   under **Update** and press **Send**.
3. When playback is stopped, Melodee asks **Update to <version>?**. Press
   **B3** (**INSTALL**). To keep this version for now, press **B1**
   (**LATER**). Melodee asks again after SD card access or the next time
   it starts.
4. Melodee saves the project, checks the zip, writes it to the card and
   restarts. The header then shows **Updated to <version>**. Melodee
   deletes the zip from the card.

![Update question](../images/screens/updateask.png)

Melodee only offers official releases. A zip that was changed, or that
did not come from Melodee's releases page, is ignored. If the update fails
(for example, the card is full), the screen shows the reason and nothing is
changed. Press **B1** to close it. The previous version stays on the card
in `autorun/melodee.prev`.

Melodee 0.1.0 cannot update this way. To move from 0.1.0, install the new
version by hand, as in [Install](../../README.md#install).

---

Previous: [MIDI and sync](midi-and-sync.md) · [Contents](../GUIDE.md) · Next: [Settings](settings.md)
