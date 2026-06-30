"""Build an "LLM Wiki" (Karpathy-style) for a chatbot category from its source content.

This is the authoring step for the LLM-Wiki retrieval mode (see CLAUDE.md and
``approaches/chatreadretrieveread.py:run_wiki_approach``). It does a one-time pass over a
category's source documents and uses the configured Azure OpenAI chat model to synthesize a
curated set of markdown pages — a master ``index.md`` plus one topic page per source document
(YAML frontmatter + clean markdown body with ``[[wikilinks]]``) — then uploads them via
``ChatbotWikiStore`` (blob container ``chatbot-wikis``).

Pilot usage (Internal bot, lemon corpus)::

    # preview locally first, no upload
    python build_wiki.py --category lemon --dry-run
    # then build + upload to blob
    python build_wiki.py --category lemon

Azure config + credentials are resolved via ``load_azd_env`` exactly like the other prep
scripts; run it azd-logged-in from app/backend with the backend venv. The raw source files are
left untouched — the wiki is an additive layer.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

from azure.identity.aio import AzureDeveloperCliCredential
from openai import AsyncOpenAI

from load_azd_env import load_azd_env
from prepdocslib.hyroxjson import sanitize_identifier

logger = logging.getLogger("scripts")

DEFAULT_CATEGORY = "lemon"
# Cap the source text fed to the model per page so a long article cannot blow the context.
# gpt-5.x has a large context window; HYROX lessons run long (longest ~95k chars), so keep this
# high enough to cover the whole corpus and never cut an article mid-way.
MAX_SOURCE_CHARS = 120000
# Generous budget: reasoning models (e.g. gpt-5.4-mini) spend tokens on reasoning before the
# JSON body, and long lessons produce long pages, so keep the output ceiling high to avoid
# truncating the page (raising the ceiling does not cost more — only tokens actually used bill).
PAGE_RESPONSE_TOKENS = 16000


def repo_root() -> Path:
    # build_wiki.py lives in app/backend/ → parents[2] is the repo root.
    return Path(__file__).resolve().parents[2]


def resolve_source_files(category: str, explicit: list[str]) -> list[Path]:
    """Resolve the raw source JSON file(s) for a category. Prefers explicit paths, then the
    canonical data/ export, then the local content/<category>/ blob mirror."""
    if explicit:
        return [Path(p) for p in explicit]
    candidates: list[Path] = []
    if category == "lemon":
        candidates.append(repo_root() / "data" / "HYROX_Level_1.json")
    content_dir = repo_root() / "content" / category
    existing = [path for path in candidates if path.exists()]
    if existing:
        return existing
    if content_dir.is_dir():
        return sorted(content_dir.glob("*.json"))
    raise FileNotFoundError(
        f"No source files found for category '{category}'. Pass explicit path(s) as positional arguments."
    )


def load_records(paths: list[Path]) -> list[dict[str, Any]]:
    """Load source documents as a flat list of records. Each record is expected to carry at
    least a title and content (the HYROX Level 1 export shape; other list-of-objects JSON
    works too as long as those fields exist)."""
    records: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"Source file {path} must contain a top-level JSON array of records.")
        for record in payload:
            if isinstance(record, dict):
                records.append(record)
    if not records:
        raise ValueError("No usable records found in the source file(s).")
    return records


def record_title(record: dict[str, Any], index: int) -> str:
    title = record.get("title")
    return title.strip() if isinstance(title, str) and title.strip() else f"Untitled {index + 1}"


def record_content(record: dict[str, Any]) -> str:
    content = record.get("content")
    return content if isinstance(content, str) else ""


def record_source(record: dict[str, Any]) -> str:
    """Citation handle stored in the page frontmatter so the bot can cite back to the original
    source, matching how normal retrieval cites (url, else lms_id/sourcepage, else title)."""
    for key in ("url", "lms_id", "sourcepage", "id"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return record_title(record, 0)


def build_slug_map(records: list[dict[str, Any]]) -> list[str]:
    """One unique kebab-case slug per record, derived from its title (compatible with the
    backend's normalize_slug)."""
    slugs: list[str] = []
    seen: dict[str, int] = {}
    for index, record in enumerate(records):
        base = sanitize_identifier(record_title(record, index))
        slug = base
        if slug in seen:
            seen[base] += 1
            slug = f"{base}-{seen[base]}"
        else:
            seen[base] = 1
        slugs.append(slug)
    return slugs


PAGE_SYSTEM_PROMPT = (
    "You are building ONE page of an 'LLM Wiki' (Andrej Karpathy style) from a single source "
    "document. Rewrite the source into a clean, self-contained, well-structured markdown "
    "knowledge page optimized for another LLM to read and reason over when answering questions. "
    "Preserve every fact and detail; drop navigation cruft, marketing fluff, and duplication. "
    "Use clear section headings (start at H2), short paragraphs, and bullet lists. When you "
    "mention a concept that matches one of the provided candidate page slugs, link it inline as "
    "[[that-slug]]. Do NOT include the page's own H1 title. "
    'Respond with ONLY a JSON object: {"summary": "<=20 word index description", '
    '"related": ["slug", ...], "body": "<markdown body>"}'
)


def strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    return text


async def synthesize_page(
    openai_client: AsyncOpenAI,
    model: str,
    record: dict[str, Any],
    index: int,
    candidate_slugs: list[str],
    reasoning_effort: str | None = None,
) -> tuple[str, list[str], str]:
    title = record_title(record, index)
    content = record_content(record)[:MAX_SOURCE_CHARS]
    raw_tags = record.get("tags")
    tags = raw_tags if isinstance(raw_tags, list) else []
    candidate_block = "\n".join(f"- {slug}" for slug in candidate_slugs if slug)
    user_message = (
        f"Source title: {title}\n"
        f"Tags: {', '.join(str(t) for t in tags)}\n\n"
        f"Candidate page slugs you may link to with [[slug]] or list under related:\n{candidate_block}\n\n"
        f"Source content:\n{content}"
    )
    request_params: dict[str, Any] = {
        "max_completion_tokens": PAGE_RESPONSE_TOKENS,
        # Force valid JSON so the model can't break parsing with unescaped control characters or
        # trailing prose (the cause of the deterministic raw-content fallbacks).
        "response_format": {"type": "json_object"},
    }
    if reasoning_effort:
        request_params["reasoning_effort"] = reasoning_effort
    try:
        completion = await openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": PAGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            **request_params,
        )
        raw = completion.choices[0].message.content or ""
        payload = json.loads(strip_code_fence(raw))
        summary = str(payload.get("summary", "")).strip()
        related = [s for s in payload.get("related", []) if isinstance(s, str)]
        body = str(payload.get("body", "")).strip()
        if body:
            return summary or title, related, body
    except Exception as error:  # noqa: BLE001 - authoring tool: fall back to a deterministic page
        logger.warning("LLM synthesis failed for '%s' (%s); using raw content.", title, error)
    # Deterministic fallback so a build never loses a source page.
    return title, [], content.strip()


def assemble_page_markdown(
    record: dict[str, Any],
    index: int,
    slug: str,
    summary: str,
    related: list[str],
    body: str,
) -> str:
    title = record_title(record, index)
    source = record_source(record)
    updated = record.get("date") if isinstance(record.get("date"), str) and record.get("date") else date.today().isoformat()
    related_json = ", ".join(json.dumps(r) for r in related)
    frontmatter = (
        "---\n"
        f"title: {json.dumps(title)}\n"
        f"slug: {slug}\n"
        "type: source-summary\n"
        f"sources: [{json.dumps(source)}]\n"
        f"related: [{related_json}]\n"
        f"updated: {updated}\n"
        "---\n"
    )
    return f"{frontmatter}\n# {title}\n\n{body}\n"


def assemble_index_markdown(category: str, entries: list[tuple[str, str, str]]) -> str:
    """entries: (slug, title, summary). One flat, scannable table of contents."""
    lines = [
        f"# {category} wiki index",
        "",
        "Master table of contents for the LLM-Wiki retrieval mode. Each entry is a page slug,",
        "its title, and a one-line description. Read this first, then load the relevant pages.",
        "",
    ]
    for slug, title, summary in entries:
        suffix = f" — {summary}" if summary else ""
        lines.append(f"- [[{slug}]] **{title}**{suffix}")
    lines.append("")
    return "\n".join(lines)


async def write_local(out_dir: Path, category: str, index_md: str, pages: list[tuple[str, str]]) -> None:
    category_dir = out_dir / category
    (category_dir / "pages").mkdir(parents=True, exist_ok=True)
    (category_dir / "index.md").write_text(index_md, encoding="utf-8")
    for slug, markdown in pages:
        (category_dir / "pages" / f"{slug}.md").write_text(markdown, encoding="utf-8")
    logger.info("Wrote %d pages + index to %s", len(pages), category_dir)


async def run(args: argparse.Namespace) -> None:
    from prepdocslib.servicesetup import OpenAIHost, clean_key_if_exists, setup_blob_manager, setup_openai_client

    load_azd_env()

    source_files = resolve_source_files(args.category, args.files)
    logger.info("Building wiki for category '%s' from: %s", args.category, ", ".join(str(p) for p in source_files))
    records = load_records(source_files)
    slugs = build_slug_map(records)
    logger.info("Loaded %d source records.", len(records))

    tenant_id = os.getenv("AZURE_TENANT_ID")
    azure_credential = (
        AzureDeveloperCliCredential(tenant_id=tenant_id, process_timeout=60)
        if tenant_id
        else AzureDeveloperCliCredential(process_timeout=60)
    )

    openai_client: AsyncOpenAI | None = None
    blob_manager = None
    try:
        openai_host = OpenAIHost(os.environ["OPENAI_HOST"])
        openai_client, _endpoint = setup_openai_client(
            openai_host=openai_host,
            azure_credential=azure_credential,
            azure_openai_service=os.getenv("AZURE_OPENAI_SERVICE"),
            azure_openai_custom_url=os.getenv("AZURE_OPENAI_CUSTOM_URL"),
            azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY_OVERRIDE"),
            openai_api_key=clean_key_if_exists(os.getenv("OPENAI_API_KEY")),
            openai_organization=os.getenv("OPENAI_ORGANIZATION"),
        )
        model = args.model or (
            os.getenv("AZURE_OPENAI_CHATGPT_DEPLOYMENT")
            if openai_host in (OpenAIHost.AZURE, OpenAIHost.AZURE_CUSTOM)
            else os.getenv("OPENAI_CHATGPT_MODEL")
        )
        if not model:
            raise ValueError("Could not resolve a chat model/deployment. Pass --model explicitly.")

        # Candidate slugs (for cross-links) always come from the FULL set; --limit only caps how
        # many pages we synthesize (cheap smoke test before committing to the whole corpus).
        limit = args.limit if args.limit and args.limit > 0 else len(records)
        index_entries: list[tuple[str, str, str]] = []
        pages: list[tuple[str, str]] = []
        for index, (record, slug) in enumerate(zip(records, slugs)):
            if index >= limit:
                break
            candidates = [s for s in slugs if s != slug]
            summary, related, body = await synthesize_page(
                openai_client, model, record, index, candidates, reasoning_effort=args.reasoning_effort
            )
            # Keep only related slugs that actually exist.
            related = [r for r in related if r in slugs and r != slug]
            page_markdown = assemble_page_markdown(record, index, slug, summary, related, body)
            pages.append((slug, page_markdown))
            index_entries.append((slug, record_title(record, index), summary))
            logger.info("  [%d/%d] %s", index + 1, len(records), slug)

        index_md = assemble_index_markdown(args.category, index_entries)
        log_md = (
            f"# {args.category} wiki build log\n\n"
            f"- built: {date.today().isoformat()}\n"
            f"- sources: {', '.join(p.name for p in source_files)}\n"
            f"- pages: {len(pages)}\n"
            f"- model: {model}\n"
        )

        if args.dry_run:
            await write_local(Path(args.out_dir), args.category, index_md, pages)
            (Path(args.out_dir) / args.category / "log.md").write_text(log_md, encoding="utf-8")
            logger.info("Dry run complete — nothing uploaded. Review the files, then re-run without --dry-run.")
            return

        from core.chatbotwikistore import ChatbotWikiStore

        blob_manager = setup_blob_manager(
            azure_credential=azure_credential,
            storage_account=os.environ["AZURE_STORAGE_ACCOUNT"],
            storage_container=os.environ["AZURE_STORAGE_CONTAINER"],
            storage_resource_group=os.getenv("AZURE_STORAGE_RESOURCE_GROUP"),
            subscription_id=os.getenv("AZURE_SUBSCRIPTION_ID"),
            storage_key=clean_key_if_exists(args.storagekey),
        )
        wiki_store = ChatbotWikiStore(blob_manager=blob_manager)
        for slug, markdown in pages:
            await wiki_store.save_page(args.category, slug, markdown)
        await wiki_store.save_index(args.category, index_md)
        await wiki_store.save_log(args.category, log_md)
        logger.info("Uploaded %d pages + index to blob container 'chatbot-wikis' under wiki/%s/.", len(pages), args.category)
    finally:
        if openai_client is not None:
            await openai_client.close()
        if blob_manager is not None:
            await blob_manager.close_clients()
        await azure_credential.close()


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(description="Build an LLM Wiki for a chatbot category from its source content.")
    parser.add_argument("files", nargs="*", help="Optional explicit source JSON file path(s). Defaults per category.")
    parser.add_argument("--category", default=DEFAULT_CATEGORY, help="Category to build the wiki for (default: lemon).")
    parser.add_argument("--model", default=None, help="Override the chat model/deployment used for synthesis.")
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        help="Reasoning effort for synthesis (reasoning models only), e.g. minimal/low/medium.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Only synthesize the first N source records (smoke test).")
    parser.add_argument("--dry-run", action="store_true", help="Write the wiki locally for review instead of uploading.")
    parser.add_argument("--out-dir", default="wiki-preview", help="Local output directory for --dry-run.")
    parser.add_argument("--storagekey", required=False, help="Optional Azure Blob Storage key override.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output.")
    parsed_args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if parsed_args.verbose else logging.INFO, format="%(message)s")
    logger.setLevel(logging.DEBUG if parsed_args.verbose else logging.INFO)

    asyncio.run(run(parsed_args))
