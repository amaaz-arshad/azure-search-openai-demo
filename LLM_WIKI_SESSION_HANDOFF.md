# LLM Wiki Session Handoff

Date: 2026-05-05
Repo: `d:\working student\snap\agentic-retrieval`

Use this file as context for continuing the LLM Wiki work in a new agent session. It intentionally contains no secrets.

## User Goal

Implement a pure Karpathy-style "LLM Wiki" option for the internal bot as an alternative to the existing RAG pipeline, then compile available chatbot content into Markdown wiki pages.

The pure LLM Wiki path should not perform query-time Azure Search retrieval. It should answer from precompiled Markdown wiki pages.

## Current State

The LLM Wiki feature is implemented and ready for local testing/deployment.

Runtime behavior:

- Internal bot has a dev-settings checkbox for LLM Wiki.
- When enabled, backend reads compiled Markdown pages from blob storage under:

```text
__llm_wiki__/<chatbot>/wiki/
```

- Runtime source bot is still selected through the internal bot's `source_chatbot` override.
- LLM Wiki mode skips the normal Azure Search/RAG query pipeline and uses compiled Markdown wiki pages as the answer source.
- Citations for LLM Wiki pages are routed as `__llm_wiki__/...` citations.

The app still needs a backend restart locally, or deployment in production, for code changes to take effect.

## Important Files Changed Or Added

Backend runtime:

- `app/backend/approaches/chatreadretrieveread.py`
- `app/backend/approaches/prompts/llm_wiki_answer.system.jinja2`
- `app/backend/approaches/prompts/llm_wiki_answer.user.jinja2`

Compiler/upload utilities:

- `app/backend/compile_llm_wiki.py`
- `app/backend/upload_llm_wiki.py`

Frontend internal bot toggle:

- `app/frontend/src/api/models.ts`
- `app/frontend/src/chatbots/internal/api/api.ts`
- `app/frontend/src/chatbots/internal/components/Settings/Settings.tsx`
- `app/frontend/src/chatbots/internal/pages/chat/Chat.tsx`
- `app/frontend/src/chatbots/internal/locales/en/translation.json`
- `app/frontend/src/chatbots/internal/locales/de/translation.json`
- `app/frontend/src/chatbots/internal/locales/nl/translation.json`

Tests:

- `tests/test_chatapproach.py`
- `tests/test_app.py`
- `tests/test_app_config.py`
- `tests/test_compile_llm_wiki.py`
- `tests/test_upload_llm_wiki.py`

Docs:

- `data/llm-wiki/README.md`
- `AGENTS.md`

Graphify has been updated after code changes:

- `graphify-out/GRAPH_REPORT.md`
- `graphify-out/graph.json`
- new `graphify-out/cache/*.json` files

## Compiler Behavior

Default raw source mode reads from Azure Blob Storage:

```powershell
python app/backend/compile_llm_wiki.py --chatbot <chatbot>
```

Local source mode reads raw files from this repo's `content/<chatbot>/` folders, then uploads compiled Markdown wiki pages to blob storage:

```powershell
python app/backend/compile_llm_wiki.py --chatbot <chatbot> --local-content-root content --overwrite
```

Useful flags:

- `--overwrite`: recompile and overwrite existing wiki pages. Without it, existing source pages are reused.
- `--local-content-root content`: read raw source files locally instead of from raw blob storage.
- `--raw-chunk-chars`: controls raw text chunk size before LLM calls.
- `--max-source-pages`: extraction safety cap for parser sections/pages.
- `--max-chunks-per-wiki-page`: splits very large sources into multiple `sources/*-part-NNN.md` wiki pages.
- `--include-nerilio-folders`: by default, nested folders inside `nerilio/` are ignored.

Very large source files can compile into multiple source pages. The runtime already loads all Markdown pages under the wiki prefix, and `index.md` links the parts.

## Compiled Wiki Data

Compiled wiki pages were uploaded to blob storage and also appear locally under `content/__llm_wiki__/` in this workspace.

Current compiled source-page counts:

```text
agindo:       2 source pages
nerilio:      7 source pages
rak:          2 source pages
sartorius:    1 source page
knoll:       73 source pages
lemon:        1 source page
moodle:       2 source pages
publishone:   3 source pages
fhg:          1 source page
vjoonk4:     25 source pages
fbn:          1 source page
steuertipps: 20 source pages
```

`demo` and `free` remain uncompiled by request.

Important special cases:

- `nerilio` compile used only direct files under `content/nerilio/`; nested folders were intentionally ignored.
- `fbn` was compiled from local file:

```text
content/fbn/Wetstoelichtingen IB - SNAP demo.xml
```

- `steuertipps` was compiled from local file:

```text
content/steuertipps/steuertipps-product.xml
```

- `steuertipps-product.xml` parsed into 54,932 XML sections and was too large for one Markdown page, so it was compiled as 20 part pages:

```text
__llm_wiki__/steuertipps/wiki/sources/steuertipps-product-part-001.md
...
__llm_wiki__/steuertipps/wiki/sources/steuertipps-product-part-020.md
```

FBN output:

```text
__llm_wiki__/fbn/wiki/index.md
__llm_wiki__/fbn/wiki/log.md
__llm_wiki__/fbn/wiki/sources/wetstoelichtingen-ib-snap-demo.md
```

Steuertipps output:

```text
__llm_wiki__/steuertipps/wiki/index.md
__llm_wiki__/steuertipps/wiki/log.md
__llm_wiki__/steuertipps/wiki/sources/steuertipps-product-part-001.md
...
__llm_wiki__/steuertipps/wiki/sources/steuertipps-product-part-020.md
```

## Commands Already Run

Main blob compile for regular bots:

```powershell
python app/backend/compile_llm_wiki.py
```

The first run timed out partway through Knoll, so `compile_llm_wiki.py` was updated to reuse existing pages by default. The next run resumed and completed.

Corrective PublishOne/FHG rerun after improving chunking and page limits:

```powershell
python app/backend/compile_llm_wiki.py --chatbot publishone --chatbot fhg --overwrite --max-source-pages 10000 --raw-chunk-chars 160000
```

FBN/Steuertipps local-source dry run:

```powershell
python app/backend/compile_llm_wiki.py --chatbot fbn --chatbot steuertipps --local-content-root content --dry-run
```

FBN compile plus initial Steuertipps attempt:

```powershell
python app/backend/compile_llm_wiki.py --chatbot fbn --chatbot steuertipps --local-content-root content --overwrite
```

That successfully uploaded FBN. Steuertipps hit the 10,000 section cap, so that process was stopped before Steuertipps upload.

Full Steuertipps rerun:

```powershell
python app/backend/compile_llm_wiki.py --chatbot steuertipps --local-content-root content --overwrite --max-source-pages 60000 --raw-chunk-chars 500000 --max-chunks-per-wiki-page 20
```

This completed successfully and uploaded 20 part pages plus `index.md` and `log.md`.

## Verification Already Done

Latest focused checks:

```text
python -m pytest -q tests/test_compile_llm_wiki.py tests/test_upload_llm_wiki.py
16 passed

ruff check app/backend/compile_llm_wiki.py app/backend/upload_llm_wiki.py tests/test_compile_llm_wiki.py tests/test_upload_llm_wiki.py --ignore E402,I001
passed

ty check app/backend/compile_llm_wiki.py app/backend/upload_llm_wiki.py
passed

git diff --check
passed with CRLF line-ending warnings only

graphify update .
completed
```

Earlier checks during implementation:

- targeted LLM Wiki runtime tests passed
- app config/internal override tests passed
- frontend build passed with `npm run build` in `app/frontend`

Blob audit results for the final local-source request:

```text
fbn: source_pages=1 index=True log=True
steuertipps: source_pages=20 index=True log=True
```

No compile processes were left running after the final Steuertipps compile.

## Known Warnings Or Non-Blockers

- `requests` emits a dependency warning about `urllib3`/`chardet` versions during Python runs. This did not block compile/tests.
- `git diff --check` reports CRLF conversion warnings on some files. No whitespace errors were reported.
- `graphify update .` printed some PDF parser warnings while updating the graph. Graph update still completed.
- The git worktree is dirty and changes are not committed.
- `DEFAULT_EXCLUDED_CHATBOTS` in `compile_llm_wiki.py` still includes `steuertipps`, `fbn`, `free`, and `demo`. This only affects running the compiler with no explicit `--chatbot`; explicit `--chatbot fbn` and `--chatbot steuertipps` works.

## Suggested Next Steps

1. Restart the local backend or deploy app code so the LLM Wiki runtime path and internal toggle are active.
2. In `/internal`, select a source bot, enable the LLM Wiki checkbox, and spot-check answers.
3. Prioritize spot checks for large generated wikis:
   - `steuertipps`
   - `publishone`
   - `knoll`
   - `lemon`
   - `fbn`
4. If answers are too broad or too thin for large bots, tune the compiler prompts or split strategy, then recompile that bot.
5. Before committing or handing off code, review `git status --short` and decide whether to include graphify cache files and local `content/__llm_wiki__` files.

## Useful Commands For The Next Agent

Inspect changed files:

```powershell
git status --short
git diff -- app/backend/compile_llm_wiki.py
git diff -- app/backend/approaches/chatreadretrieveread.py
```

Run focused backend checks:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_chatapproach.py tests/test_compile_llm_wiki.py tests/test_upload_llm_wiki.py
.venv/Scripts/ruff.exe check app/backend/compile_llm_wiki.py app/backend/upload_llm_wiki.py tests/test_compile_llm_wiki.py tests/test_upload_llm_wiki.py --ignore E402,I001
.venv/Scripts/ty.exe check app/backend/compile_llm_wiki.py app/backend/upload_llm_wiki.py
```

Recompile one local-source bot:

```powershell
.venv/Scripts/python.exe app/backend/compile_llm_wiki.py --chatbot <chatbot> --local-content-root content --overwrite
```

Recompile Steuertipps full local source:

```powershell
.venv/Scripts/python.exe app/backend/compile_llm_wiki.py --chatbot steuertipps --local-content-root content --overwrite --max-source-pages 60000 --raw-chunk-chars 500000 --max-chunks-per-wiki-page 20
```

Update graph after code changes:

```powershell
graphify update .
```
