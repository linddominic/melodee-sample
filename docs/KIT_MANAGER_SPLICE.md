# Kit Manager: Splice account access (Milestone 4)

What the official Splice MCP server offers the Kit Manager, tried on
2026-11-15 with `tools/companion/splice_probe.py` and a real Splice account
(docs/KIT_MANAGER_PLAN.md, 5.3 and 5.4). Melodee is the work of Kerem Kiliç
(Ellic Studio); this is a fork's investigation on top of it.

## Confirmed

- **The server**: `https://mcp.splice.com/mcp`, streamable HTTP,
  `splice-mcp-server` (version "dev"), protocol 2025-06-18.
- **Sign-in from our own client works.** OAuth 2.1 from
  `/.well-known/oauth-authorization-server`: dynamic client registration
  (`/oauth/register`, no secret: `token_endpoint_auth_method: none`),
  authorization code with PKCE (S256), the login in the browser, the code on
  a local port. Scopes `openid profile email offline_access`. The token lasts
  an hour and comes with a refresh token. No developer account or agreement
  was asked for.
- **Six tools, no resources, no prompts:**

  | Tool | Does | Notes |
  | --- | --- | --- |
  | `describe_a_sound(query, type?, bpm_min?, bpm_max?)` | Searches the whole Splice catalog | Read only. Tried: "punchy 808 kick" found 112532, 10 shown |
  | `download_asset(asset_uuid, download_path?)` | Buys a sound, answers a short-lived presigned URL | Not tried: the first download of a sound spends a credit |
  | `create_stack`, `prompt_to_stack`, `update_stack`, `share_stack` | Splice "stacks" (layered loop arrangements) | Not for kits |

- **A search result is Markdown text only**, no structured content: file
  name, BPM, key, duration, one-shot or loop, pack, tags, a splice.com page
  link and the asset UUID. **No audio preview URL**: a sound can be heard
  before it is bought only on its splice.com page.

## Not available

- **The user's own library**: nothing reaches licensed or downloaded sounds,
  likes, saved sounds, **Collections** or Collection membership. No tool,
  resource or prompt names them. This is the blocker the plan asked to
  document; the plan forbids private APIs and scraping, so none are used.

## From Splice's documents, not tried

- Downloads need a Sounds+, Creator or Creator+ plan; one credit for a sound
  the first time, free after; at most 100 a rolling day
  ([Splice support](https://support.splice.com/en/articles/14442749-getting-started-with-the-splice-mcp-server-beta)).
- Sounds are licensed, not sold; using them to train AI is not allowed
  ([licensing FAQ](https://intercom.help/splice-b7a2d5b83f2e/en/articles/8652642-splice-sounds-licensing-faq)).
- **Not settled**: whether Splice's terms allow the MCP server in an app of
  one's own like this one ([Terms](https://www.splice.com/terms)). Read them
  before building on it.

## The workflow instead

1. **Collections and one's library (Milestone 3):** download the sounds from
   a Collection in the Splice app; they land in the Splice folder on the Mac
   (`~/Splice/sounds` by default). The Mac companion indexes that folder as a
   "Splice" source in Sounds; a sound dropped on a pad is copied to the card,
   so the kit plays without the Mac.
2. **Optional, catalog search:** the companion could run `describe_a_sound`
   for a "Splice catalog" search in Sounds, with a link to hear each result
   on splice.com, and `download_asset` (after a "spends one credit" question)
   into the Splice folder, from where (1) takes it. The results are Markdown,
   so the companion would parse text Splice may change; with no previews it
   is worth less than (1). The token stays in the companion's memory or the
   Mac's Keychain, never in the firmware or the browser.

## Built (the Mac companion)

All of it through the official MCP and splice.com's public pages, signed in
once (`tools/companion/splice_mcp.py`, the refresh token in the Mac's login
Keychain). Nothing reads Splice's private API, gets past its bot check, or
unscrambles its previews.

- **Catalog** in Sounds (`splice_catalog.py`, `/companion/splice/catalog`):
  `describe_a_sound` with the One-shots/Loops filter, its Markdown read into
  rows (label, type, BPM, key, length, tags); 10 a search, as the tool gives.
  Sounds one has in the Splice folder are marked ✓ and play from there; a
  sound got before is free again.
- **Listen**: splice.com may not be shown inside another page
  (`X-Frame-Options: SAMEORIGIN`), so its page opens in a small window of its
  own beside the Kits page (460×250, used again for each Listen; Stop or Esc
  closes it). With the **Melodee Listen** browser extension
  (`tools/companion/listen-extension`: Chrome, Edge, Brave or Arc, "Load
  unpacked") that window shows only the sound's name, waveform and Play
  button and presses Play, Splice's own page and player in one's own browser;
  it acts only in that window (its name, or `#melodee-listen` on the link).
- **Get** (`/companion/splice/get`): asked first on the page; `download_asset`
  (one credit the first time), the file kept in `~/Music/Melodee Splice/<label>/`
  and copied to `Melodee/Samples/Splice/<label>/` on the card. A drop of a
  catalog sound on a pad gets it the same way. A session may get 20
  (`--credit-limit`).
- **Packs** (`/companion/splice/pack`): a catalog sound's public page names
  its pack and links the pack's page (title, cover); the pack's sounds are
  gathered with a search per kind ("<title> kick", "<title> snare"…), kept
  when of the same label and starting with the same file prefix as the sound
  opened from. Ten searches of ten, so not always the whole pack.
- **Kit from this pack**: the pack's one-shots planned as for a folder, the
  credits it costs said first (sounds one has are free), each got and put on
  its pad.
- **Pack artwork** for the Mac's packs: see docs/KIT_MANAGER.md; a
  `cover.jpg`, `.png` or `.webp` in a pack's folder wins.

Splice's pages are read one every three seconds across all of this, and on
429 the lookups pause.

## Try it

    python3 tools/companion/splice_probe.py --search "punchy 808 kick"

opens the browser to sign in, prints the tools and the search's first
results, and saves them to `.local/splice-mcp.json` (no token). It never calls
`download_asset`.
