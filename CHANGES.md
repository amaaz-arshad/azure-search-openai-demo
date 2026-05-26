<!-- markdownlint-disable MD024 -->
# Project changes log

Reverse chronological. Newest entries at the top.

Maintained by coding agents: at the end of any session that produced file
edits or recorded design decisions, append a new dated entry here before
signing off.

Two categories per date:

- **Decisions** — design choices, scope changes, "things we explicitly chose
  not to do". The *why*, which can't be recovered from a diff.
- **Changes** — file edits, creations, deletions. The *what*.

---

## 2026-05-26

### Decisions

- **Ported `nerilio backend` admin design into `/verwaltung` as React TSX.**
  Faithful design-only port of the sibling PHP project at
  `D:\working student\snap\nerilio backend\` (7 views + monolithic CSS) into a
  new admin surface at `/verwaltung`. Decisions:
  - Nested sub-routes (`/verwaltung/dashboard`, `/customers`, `/users`,
    `/knowledge-bases`, `/configure/:botId?`) — not a single-page tab switcher.
  - Reused existing `useInternalAdminAccess` hook for the auth gate (same gate
    as `/chatbots`, `/manage-prompts`). The ported `login.php` design renders
    as the unlock screen.
  - Empty UI shells: tables show their headers + empty-state rows; modals and
    slide-in detail panels open/close; "submit" handlers just toast. No mock
    data, no AJAX. Backend Python endpoints are explicitly out of scope and
    will be a follow-up.
  - Source CSS (`public/css/style.css`, 593 lines) ported into a single global
    file (`app/frontend/src/pages/verwaltung/verwaltung.css`) with every
    selector prefixed by `.verwaltung-root` to prevent class-name collisions
    with the rest of the app. Chose this over CSS Modules because the source's
    very short class names (`.app`, `.modal`, `.dp`, `.cm`, …) would have
    required renaming every `className` in the TSX; the wrapper scope is
    enough to isolate the new code.
  - Inline SVG icons kept verbatim (stroke weights, viewBoxes, points) in
    `components/icons.tsx` rather than swapped for Fluent UI icons — the
    source's specific look is part of the design.
  - `/verwaltung/portal` is a sibling top-level route (no sidebar, no admin
    gate) — matches the source's customer-user surface.
  - No i18n — admin pages in this repo are not translated; source German
    strings preserved verbatim.
- **Attributed OpenLIT LLM request spans with chatbot metadata instead of editing
  the external OpenLIT dashboard UI.** This repo only sends telemetry to the
  configured `OPENLIT_ENDPOINT`; it does not own the OpenLIT Requests page.
  Per-request custom span attributes (`chatbot.name`,
  `chatbot.effective_name`, and for `/internal`, `chatbot.source_name`) give
  OpenLIT data to filter/group by while keeping dashboard customization outside
  the app code.
- **Swapped canonical agent-instructions file from `AGENTS.md` to `CLAUDE.md`.**
  All repo contracts, change workflows, tests, and deployment notes now live in
  `CLAUDE.md`; `AGENTS.md` is a thin pointer that defers to it. Reason: align
  the canonical playbook with the file Claude loads automatically, while
  keeping `AGENTS.md` available for tools (Codex, others) that look for it.
- **Adopted the thesis-project changes-log pattern.** Added `CHANGES.md` at
  the repo root with reverse-chronological dated entries split into Decisions
  and Changes, plus a "Changes log maintenance" section in `CLAUDE.md` so
  Claude, Codex, and any other agent reads it at session start and appends at
  session end. Mirrors the convention from `D:\study-material\5th\thesis\thesis`.

### Changes

- Created `app/frontend/src/pages/verwaltung/` with the new admin surface:
  - `verwaltung.css` (590+ lines, scoped under `.verwaltung-root`).
  - `VerwaltungLayout.tsx` (auth gate + sidebar + `<Outlet/>`).
  - `index.ts` (barrel exports).
  - `components/Sidebar.tsx`, `components/Toast.tsx` (toast hook),
    `components/icons.tsx` (inline SVG icon set).
  - `pages/LoginPage.tsx` (ported from `views/login.php`; wired to
    `useInternalAdminAccess.login`).
  - `pages/DashboardPage.tsx` (chatbot table + create modal + confirm modal).
  - `pages/CustomersPage.tsx` (table, wide create/edit modal, delete confirm,
    slide-in detail panel with inline new-bot form).
  - `pages/UsersPage.tsx` (table + role/status/customer filters + modal +
    detail panel with bot assignments).
  - `pages/KnowledgeBasesPage.tsx` (table + create modal + delete confirm +
    text-entry modal + detail panel with usage bars, dropzone, file list,
    text list, URL crawl section).
  - `pages/ConfigurePage.tsx` (page-tabs general/qa/tutor/assessment, 12
    collapsible sections in general tab, language pills + per-language tabs,
    color picker, upload zones, mode-driven tab visibility).
  - `pages/PortalPage.tsx` (standalone customer-user bot grid + profile modal).
- Edited `app/frontend/src/index.tsx`: imported the verwaltung exports and
  registered nested routes for `/verwaltung/{dashboard,customers,users,
  knowledge-bases,configure/:botId?}` plus sibling `/verwaltung/portal`.
- Edited `app/backend/app.py`: registered `/verwaltung`, `/verwaltung/`, and
  `/verwaltung/<path:subpath>` to serve the SPA index, and added
  `"verwaltung"` to `NON_CHATBOT_FRONTEND_PREFIXES`. Without these, the
  catch-all chatbot route at `/<chatbot_name>` was redirecting `/verwaltung`
  back to `/` because it wasn't in `KNOWN_CHATBOT_NAMES`.
- Edited `CLAUDE.md`: added `/verwaltung/*` (excluding `/verwaltung/portal`)
  to the "Shared internal admin auth gates" contract.
- Edited `app/backend/app.py`: chat and streaming chat routes now wrap OpenLIT
  instrumented work in request-specific chatbot attributes when
  `OPENLIT_ENDPOINT` is configured. Streaming responses keep the attributes
  active while the async generator is consumed.
- Edited `tests/test_app.py`: added focused tests for OpenLIT chatbot metadata
  on normal chat, `/internal` route/source attribution, and streaming lifetime.
- Deployed the `backend` service to Azure Container Apps with `azd deploy
  backend`; active revision is
  `capps-backend-ylubdsyknmmcc--azd-1779797065` with 100% traffic.
- Ran `graphify update .`, updating `graphify-out/graph.json` and
  `graphify-out/GRAPH_REPORT.md`.
- Edited `CLAUDE.md`: now holds the full agent playbook (graphify rules,
  operating rules, where to start, contracts to preserve, adding data /
  chatbot / azd variable / developer settings, tests, deployment, style).
  Previously a thin pointer to `AGENTS.md`.
- Edited `AGENTS.md`: reduced to a thin pointer that defers to `CLAUDE.md`.
  Previously held the full playbook.
- Created `CHANGES.md`: new project changes log (this file).
- Edited `CLAUDE.md`: added a "Changes log maintenance" section and listed
  `CHANGES.md` in the canonical artifacts so future sessions know to read
  and update it.
