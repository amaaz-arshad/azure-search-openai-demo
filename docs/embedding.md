# Embedding a chatbot on an external website

Website owners can add a chatbot to any site — WordPress, TYPO3, Drupal, or a custom site — by
pasting a single `<script>` snippet, the same way you would add Google Analytics or Intercom. A
floating chat bubble renders itself; no HTML, CSS, or UI work is required, and widget updates roll
out automatically.

## Quick start

Paste this just before the closing `</body>` tag, replacing `YOUR_PUBLIC_ID` with the chatbot's
**public embed ID** (an anonymous, generated identifier such as `muw0oowcw3` — never the readable
chatbot name):

```html
<script async src="https://chat.nerilio.ai/widget.js" data-chatbot-id="YOUR_PUBLIC_ID"></script>
```

That's it. The script injects a launcher button (bottom-right by default) and, on first open,
loads the chatbot in an isolated iframe.

Get the public ID (and manage the allowed-domains whitelist) from the internal **Chatbot
Directory** page (`/admin/chatbots`): every bot card has an **Embed** button that shows the
ready-to-copy snippet, a domain whitelist editor, and a live preview. The directory lists both
built-in and provisioned (dynamic) bots — see [Provisioned bots](#provisioned-dynamic-bots).

> There is also an **`/embed-demo`** page (gated by the internal admin password, like the other
> admin tools) — pick any chatbot from the dropdown to preview its popup, copy the public-ID
> snippet, and **edit that bot's domain whitelist** (the same setting as the Embed dialog; both
> write to the same store). Bots that restrict embedding to specific domains will not render the
> bubble on the demo page.

## Anonymous public identifier

The embed snippet references a chatbot by an opaque, generated public ID (GA/Clarity style), not by
its route name. The internal route name stays unchanged and is still how the app is browsed
directly (`/<chatbot_name>`); only the public ID is used for widget integration, and it never
appears in the host page DOM or the iframe `src` (the iframe loads `/embed/<publicId>`, which
resolves the bot server-side).

IDs come from two places, one per kind of bot:

- **Built-in bots** — the ID↔name map committed in `app/backend/embed_public_ids.py`, so embed codes
  are stable across deploys. Run `python -m embed_public_ids` to mint an ID for a new built-in bot,
  then paste the printed line and commit it.
- **Provisioned (dynamic) bots** — minted at create time and stored on the bot's registry record
  (`embedPublicId`), because there is no source file to commit for a bot the control panel invents
  at runtime.

Minting checks both sets, so the ID space stays 1:1 and a dynamic bot can never collide with a
built-in. Resolution follows the same order: the committed map first (no I/O, so built-in embeds
never depend on the registry), then the registry. An ID is **write-once** — no update, restart, or
admin action rotates it, since live snippets already point at it.

## Provisioned (dynamic) bots

Bots created through the provisioning API (`POST /provisioning/chatbots`, see
[provisioning-api.md](provisioning-api.md)) are embeddable exactly like built-in bots, with no extra
step:

- **`create` mints the public ID** and returns it as `publicId`, plus a ready-to-paste
  `embedSnippet`, so the control panel can show the customer their embed code without anyone opening
  the admin UI.
- They appear on **`/admin/chatbots`** (tagged `PROVISIONED`) and in the **`/admin/embed`** picker
  (under a `Provisioned` group, fetched live — a new bot needs no redeploy).
- **Stopped bots** (`active: false`) are still listed in the directory, tagged `STOPPED`, but offer
  no **Embed** button and are absent from the embed picker: a stopped bot's route redirects home, so
  its embed would load a broken iframe. Existing embeds of a bot that is later stopped go dark the
  same way (`/embed/<publicId>` redirects, and the widget config 404s). Starting it again restores
  them — the ID never changed.
- The launcher bubble color comes from the bot's provisioned `design.color_primary` (falling back to
  the shared default), rather than the per-bot table used for built-in bots.
- The whitelist editor accepts a stopped bot, so domains can be prepared before the bot is started.
- **`delete` also deletes the bot's whitelist**, because that store is keyed by bot *name*: leaving
  it behind would silently apply one customer's allowed domains to the next bot provisioned under
  the same name.

Bots provisioned before this existed have no stored ID; one is minted and saved the first time an
admin surface lists them (or on the bot's next provisioning operation), so no migration is needed.

## Domain whitelist

Each chatbot supports a configurable whitelist of pages where its widget may render, edited per bot
in the **Embed** dialog (stored server-side, no redeploy needed). Rules are one per line:

| Rule | Matches |
| --- | --- |
| _(empty list)_ | any site (the permissive default) |
| `*.snap.de` | any subdomain of `snap.de` (apex `snap.de` excluded) |
| `publishone.snap.de` | that host, any path |
| `publishone.snap.de/preise.html` | that host, that exact path |
| `help.customer-website.com/*` | that host, any path beneath it |

A leading scheme (`https://`) is ignored; host matching is case-insensitive, path matching is
case-sensitive, and the query string is ignored. When the widget loads it fetches the bot's config
and, if the current page does not match the whitelist, **renders nothing**. Enforcement is layered:
the widget hides itself client-side (the only place path-level rules can be checked), and the
backend additionally locks the iframe's `Content-Security-Policy: frame-ancestors` to the
whitelisted **origins** (CSP cannot match paths), so the chatbot refuses to frame on disallowed
domains even if the client check is bypassed.

## Options (data attributes)

| Attribute | Default | Description |
| --- | --- | --- |
| `data-chatbot-id` | _(required)_ | The chatbot route name to load. |
| `data-position` | `right` | Launcher side: `right` or `left`. |
| `data-primary-color` | `#4f46e5` | Launcher button color (the chat itself uses the bot's own theme). |
| `data-launcher-text` | `Open chat` | Accessible label for the launcher. |
| `data-locale` | bot default | Forces a locale (`en`, `de`, `nl`). |
| `data-auto-open` | `false` | Set `true` to open the panel automatically on load. |

## Programmatic API (SPAs / open on demand)

For single-page apps or to open/close the widget from your own code, use the command-queue stub so
calls made before the async script loads are not lost:

```html
<script async src="https://chat.nerilio.ai/widget.js"></script>
<script>
  window.chatbot = window.chatbot || { q: [], init(o){this.q.push(["init",o])},
    open(){this.q.push(["open"])}, close(){this.q.push(["close"])} };
  chatbot.init({ chatbotId: "lemon" });
  // chatbot.open(); chatbot.close();
</script>
```

## How it works

- `widget.js` is a tiny, dependency-free loader served by the backend at `/widget.js`. It derives
  the backend origin from its own `<script src>`, so it always talks back to the host that served
  it.
- On load it fetches `<origin>/embed/<publicId>/config` (CORS-enabled, returns only the launcher
  color + whitelist rules, never the chatbot name) to resolve theming and enforce the whitelist
  before rendering anything.
- On open it injects an iframe pointing at `<origin>/embed/<publicId>?embed=1`, which resolves the
  bot server-side. Because the iframe document is served by the chatbot backend, all chat traffic
  inside it is same-origin — **no CORS configuration is required on the customer site** for chat.
- The iframe fully isolates the chatbot's CSS/JS from the host page (and vice versa).
- A `postMessage` bridge (origin-checked) lets the page and iframe coordinate ready/close.
- On desktop the panel is **resizable**: drag the top edge, the inner side edge, or the corner
  (a subtle grip shows on hover). The chosen size is remembered per chatbot in `localStorage`
  (`chatbot-widget-size:<chatbotId>`) and restored on the next visit. Resizing is disabled on
  small screens, where the panel is near-fullscreen.

## Authentication-gated chatbots

Bots protected by the per-chatbot simple login still work inside the iframe: when served over
HTTPS the login cookie is issued as `SameSite=None; Secure; Partitioned` (CHIPS), which modern
browsers send inside a cross-site iframe.

Known limitations:

- Chatbots that require **Microsoft Entra ID (MSAL) login** cannot be embedded — interactive MSAL
  sign-in does not run inside a third-party iframe.
- Hardened privacy modes that block all partitioned/third-party storage may still prevent gated
  logins. Public (ungated) bots are unaffected.

## Security note

Framing is controlled per chatbot. With no whitelist the backend advertises
`Content-Security-Policy: frame-ancestors *` (any site may embed). Once a bot has a whitelist,
`serve_spa_index` in `app/backend/app.py` emits `frame-ancestors 'self' <whitelisted hosts>` on
both the anonymized `/embed/<publicId>` route and the canonical `/<chatbot_name>` route, so the
chatbot cannot be framed on a non-whitelisted origin. Path-level rules are enforced only by the
client-side widget matcher (CSP has no notion of paths). The Python matcher
(`app/backend/embed_rules.py`) and the TypeScript matcher (`app/frontend/src/widget/widget.ts`)
must stay in lockstep.
