# Embedding a chatbot on an external website

Website owners can add a chatbot to any site — WordPress, TYPO3, Drupal, or a custom site — by
pasting a single `<script>` snippet, the same way you would add Google Analytics or Intercom. A
floating chat bubble renders itself; no HTML, CSS, or UI work is required, and widget updates roll
out automatically.

## Quick start

Paste this just before the closing `</body>` tag, replacing `YOUR_CHATBOT_ID` with the chatbot's
route name (e.g. `lemon`, `nerilio`):

```html
<script async src="https://chat.nerilio.ai/widget.js" data-chatbot-id="YOUR_CHATBOT_ID"></script>
```

That's it. The script injects a launcher button (bottom-right by default) and, on first open,
loads the chatbot in an isolated iframe.

> Tip: the internal **Chatbot Directory** page (`/chatbots`) has an **Embed** button on every bot
> card that shows the ready-to-copy snippet with a live preview.
>
> There is also a public **live demo** at **`/embed-demo`** — pick any chatbot from the dropdown
> and its popup opens in the bottom-right, with the exact snippet shown for copy/paste.

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
- On open it injects an iframe pointing at `<origin>/<chatbotId>?embed=1`. Because the iframe
  document is served by the chatbot backend, all chat traffic inside it is same-origin — **no CORS
  configuration is required on the customer site**.
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

The backend advertises `Content-Security-Policy: frame-ancestors *` so any site can embed the
widget. To restrict embedding to specific customer domains, tighten that header (see
`serve_spa_index` in `app/backend/app.py`).
