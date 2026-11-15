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

Two parts, each through what Splice offers for it, and nothing else:

| Part | Through | Does |
| --- | --- | --- |
| The Splice library | The Splice app's folder on the Mac | Every sound one has: heard, drawn and put on pads. One finds sounds in the Splice app. |
| Describe a kit | The official MCP (`describe_a_sound`, `download_asset`) | Words to a 16-pad draft, bought with one's credits. |

Splice's own pages are not read, its private API is not used, and its
previews are not unscrambled.

- **Sign-in** (`splice_mcp.py`): once, in the browser; the refresh token in
  the Mac's login Keychain ("Melodee companion: Splice MCP").
- **Describe a kit** (`splice_kits.py`, `/companion/splice/describe`): a
  search per kind of pad (14 for 16 pads: the pad's word, then the words
  described), each answer checked against the pad by the sound's own name and
  Splice's tags (Splice's search weighs the description more than "808"), up
  to six choices a pad, melodic pads leaning to the key most of them share.
  On the page: the draft, each pad's role, label, key and whether it is one's
  already (✓, free) or a credit; Swap goes to the next choice; ↗ opens the
  sound on splice.com in a tab. Make kit says the credits first, then gets
  each (`/companion/splice/get`) and fills a new kit, or one's own kit's
  empty pads. 20 gets a session (`--credit-limit`).
- **While it searches** the page shows each kind of pad as Splice answers
  (`?stream=1`: a JSON line a search and a line a pad done, the draft last).
- **Drafts** are kept in the browser (local storage, the last 20) and listed
  as **Recent** under the box: one opens again at once, without a search.
- **Credits**: no MCP tool tells one's balance. The companion shows the one
  the Splice app saved (its `appState.json`, `user.credits`, and when: that
  file can be months old), or, once something is got, the one Splice's
  download answer gives if it says. The draft says what a kit leaves.
- **Listen** (a pad one does not have): the sound's splice.com page in a
  window of its own beside the page (520×720; used again; Stop or Esc closes
  it), to press Play in. The optional **Melodee Listen** Chrome extension
  (`tools/companion/listen-extension`, Load unpacked) marks the page so the
  window opens small (460×250) and shows only the waveform and Play, and
  presses Play; it acts only in that window.
- **What is got** is kept in `~/Music/Melodee Splice/<label>/` and shown in
  the Splice source as **Got with Melodee**, beside the Splice app's packs.
- **Covers**: made from a pack's name, or a `cover.jpg`, `.png` or `.webp`
  one puts in its folder.

## Try it

    python3 tools/companion/splice_probe.py --search "punchy 808 kick"

opens the browser to sign in, prints the tools and the search's first
results, and saves them to `.local/splice-mcp.json` (no token). It never calls
`download_asset`.
