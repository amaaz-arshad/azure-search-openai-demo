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
Directory** page (`/chatbots`): every bot card has an **Embed** button that shows the ready-to-copy
snippet, a domain whitelist editor, and a live preview.

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
resolves the bot server-side). The ID↔name map is committed in `app/backend/embed_public_ids.py`
so embed codes are stable across deploys; run `python -m embed_public_ids` to mint an ID for a new
chatbot.

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
