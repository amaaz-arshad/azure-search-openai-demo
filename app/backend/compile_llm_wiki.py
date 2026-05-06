from __future__ import annotations

import argparse
import asyncio
import io
import logging
import os
import re
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath
from typing import IO, TYPE_CHECKING, Any, Optional, cast

import pymupdf
from azure.core.credentials import AzureKeyCredential
from azure.identity.aio import AzureDeveloperCliCredential
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from approaches.approach import Approach
from approaches.chatbot_prompt_registry import get_registered_chatbot_names, normalize_chatbot_name
from load_azd_env import load_azd_env
from prepdocslib.blobmanager import BlobListEntry
from prepdocslib.csvparser import CsvParser
from prepdocslib.htmlparser import LocalHTMLParser
from prepdocslib.jsonparser import JsonParser
from prepdocslib.page import Page
from prepdocslib.parser import Parser
from prepdocslib.pdfparser import DocumentAnalysisParser
from prepdocslib.servicesetup import OpenAIHost, clean_key_if_exists, setup_blob_manager, setup_openai_client
from prepdocslib.textparser import TextParser
from prepdocslib.xmlparser import XmlParser

if TYPE_CHECKING:
    from azure.core.credentials_async import AsyncTokenCredential

    from prepdocslib.blobmanager import BlobManager

logger = logging.getLogger("scripts")

DEFAULT_EXCLUDED_CHATBOTS = {"steuertipps", "fbn", "free", "demo"}
INTERNAL_ROUTER_CHATBOT = "internal"
LLM_WIKI_BLOB_ROOT = "__llm_wiki__"
DEFAULT_RAW_CHUNK_CHARS = 160000
DEFAULT_MAX_SOURCE_PAGES = 10000
SOURCE_PAGE_TOKEN_LIMIT = 8192
PARTIAL_NOTES_TOKEN_LIMIT = 4096
EMPTY_COMPLETION_RETRY_LIMIT = 2
EMPTY_COMPLETION_TOKEN_MULTIPLIER = 2
DEFAULT_MAX_CHUNKS_PER_WIKI_PAGE = 40

STUB_PHRASES = (
    r"no usable content",
    r"no substantive (notes|content|chatbot)",
    r"no extractable (notes|content|facts|text)",
    r"no content notes were provided",
    r"no partial notes were provided",
    r"the partial notes (section was empty|contained no|are empty|were empty)",
    r"the provided notes for this source are empty",
    r"no source facts were provided",
    r"no facts were provided",
    r"no factual claims can be derived",
    r"no facts.*could be derived",
    r"this split part contains no extractable",
    r"only the source name and file path",
    r"no further explanations.*are present",
    r"only the source and page headers",
    r"no additional source passages were available",
    r"no additional extracted notes",
    r"no actual dialogue or content",
    r"empty notes block",
    r"input notes:[\s\-`]*(\n[\s\-`]*){2,}",  # "Input notes:" followed by --- --- ---
    r"no content was provided",
    r"no content notes",
    r"no notes (were |to compile|are available)",
    r"only.*available information is the source name",
    r"only the (file ?name|source)",
    r"only available information is the (source name|file path)",
    r"partial notes were empty",
    r"partial notes are empty",
    r"only the source metadata",
    r"only the file name and source chatbot",
    r"only.*(blob name|blob path|source name).*(provided|available)",
    r"the only information available",
    r"the only.*information.*provided",
    r"the only substantive text present",
    r"no.*(text|content).*was supplied",
    r"the source text appears to be (entirely|mostly).*page headers",
    r"this source page (appears to be|contains only)",
    r"contains only header (and )?metadata",
    r"contains only the source identification",
)
_STUB_RX = re.compile("|".join(STUB_PHRASES), re.IGNORECASE)


def looks_like_stub(markdown: str) -> bool:
    if not markdown:
        return True
    text = markdown.strip()
    if not text:
        return True
    # Genuine wiki pages compiled from any of our raw inputs run multi-KB.
    # Anything under ~1100 chars is almost certainly a stub regardless of phrasing.
    if len(text) < 1100:
        return True
    # Up to ~3 KB: trust the phrase regex.
    if len(text) < 3000 and bool(_STUB_RX.search(text)):
        return True
    return False
SUPPORTED_LOCAL_EXTENSIONS = {".csv", ".htm", ".html", ".json", ".md", ".pdf", ".txt", ".xml"}
DOCUMENT_INTELLIGENCE_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}


@dataclass(frozen=True)
class RawBlob:
    chatbot: str
    blob_name: str
    relative_path: str


@dataclass(frozen=True)
class ExtractedPage:
    page_num: int
    text: str
    citation: str
    title: Optional[str] = None
    url: Optional[str] = None


@dataclass(frozen=True)
class CompiledPage:
    source_blob: RawBlob
    wiki_blob_name: str
    markdown: str


def normalize_source_chatbot(source_chatbot: str) -> str:
    normalized = normalize_chatbot_name(source_chatbot) or source_chatbot.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", normalized):
        raise ValueError(f"Invalid chatbot name: {source_chatbot}")
    return normalized


def get_default_chatbots(excluded: set[str]) -> list[str]:
    return [
        chatbot
        for chatbot in get_registered_chatbot_names()
        if chatbot not in excluded and chatbot != INTERNAL_ROUTER_CHATBOT
    ]


def get_llm_wiki_blob_prefix(chatbot: str, wiki_root: str = LLM_WIKI_BLOB_ROOT) -> str:
    normalized_wiki_root = wiki_root.strip().strip("/\\") or LLM_WIKI_BLOB_ROOT
    return f"{normalized_wiki_root}/{normalize_source_chatbot(chatbot)}/wiki"


def get_raw_blob_prefix(chatbot: str) -> str:
    return f"{normalize_source_chatbot(chatbot)}/"


def is_direct_child_blob(blob_name: str, prefix: str) -> bool:
    relative = blob_name.removeprefix(prefix)
    return bool(relative) and "/" not in relative


def should_compile_blob(
    blob_name: str,
    chatbot: str,
    *,
    nerilio_direct_only: bool,
    recursive: bool,
) -> bool:
    prefix = get_raw_blob_prefix(chatbot)
    if not blob_name.startswith(prefix):
        return False
    relative = blob_name.removeprefix(prefix)
    if not relative or relative.endswith("/"):
        return False
    if relative.startswith(".managed-uploads/") or "/.managed-uploads/" in relative:
        return False
    if relative.startswith(".manifests/") or "/.manifests/" in relative:
        return False
    if chatbot == "nerilio" and nerilio_direct_only and "/" in relative:
        return False
    if not recursive and "/" in relative:
        return False
    return PurePosixPath(relative).suffix.lower() in SUPPORTED_LOCAL_EXTENSIONS | DOCUMENT_INTELLIGENCE_EXTENSIONS


def slugify(value: str, *, max_length: int = 80) -> str:
    stem = PurePosixPath(value).stem or "source"
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return (slug or "source")[:max_length].strip("-") or "source"


def get_source_wiki_relative_path(raw_blob: RawBlob) -> str:
    path_slug = slugify(raw_blob.relative_path.replace("/", "-"))
    return f"sources/{path_slug}.md"


def get_source_wiki_blob_name(raw_blob: RawBlob, wiki_root: str = LLM_WIKI_BLOB_ROOT) -> str:
    return f"{get_llm_wiki_blob_prefix(raw_blob.chatbot, wiki_root)}/{get_source_wiki_relative_path(raw_blob)}"


def get_source_wiki_part_blob_name(
    raw_blob: RawBlob,
    *,
    part_number: int,
    wiki_root: str = LLM_WIKI_BLOB_ROOT,
) -> str:
    path_slug = slugify(raw_blob.relative_path.replace("/", "-"))
    return f"{get_llm_wiki_blob_prefix(raw_blob.chatbot, wiki_root)}/sources/{path_slug}-part-{part_number:03d}.md"


class LocalPyMuPdfParser(Parser):
    """PDF parser backed by PyMuPDF. Extracts more text than pypdf for many PDFs
    (better Unicode handling, layout-aware extraction) and avoids the cost of
    Azure Document Intelligence. No OCR — image-only PDFs still come back empty.
    """

    async def parse(self, content: IO) -> AsyncGenerator[Page, None]:
        try:
            content.seek(0)
        except Exception:
            pass
        data = content.read()
        logger.info("Extracting text from '%s' using PyMuPDF", getattr(content, "name", "<pdf>"))
        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            offset = 0
            for page_num in range(len(doc)):
                page_text = doc[page_num].get_text("text") or ""
                yield Page(page_num=page_num, offset=offset, text=page_text)
                offset += len(page_text)
        finally:
            doc.close()


def guess_parser(blob_name: str, *, document_intelligence_parser: Optional[Parser]) -> Optional[Parser]:
    extension = PurePosixPath(blob_name).suffix.lower()
    if extension == ".csv":
        return CsvParser()
    if extension in {".htm", ".html"}:
        return LocalHTMLParser()
    if extension == ".json":
        return JsonParser()
    if extension == ".xml":
        return XmlParser()
    if extension in {".md", ".txt"}:
        return TextParser()
    if extension == ".pdf":
        return document_intelligence_parser or LocalPyMuPdfParser()
    if extension in DOCUMENT_INTELLIGENCE_EXTENSIONS:
        return document_intelligence_parser
    return None


def make_named_bytes_io(content: bytes, name: str) -> IO[bytes]:
    stream = io.BytesIO(content)
    stream.name = PurePosixPath(name).name  # type: ignore[attr-defined]
    return stream


async def extract_pages(
    raw_blob: RawBlob,
    content: bytes,
    *,
    document_intelligence_parser: Optional[Parser],
    max_pages: int,
) -> list[ExtractedPage]:
    parser = guess_parser(raw_blob.blob_name, document_intelligence_parser=document_intelligence_parser)
    if parser is None:
        logger.warning("Skipping unsupported source blob: %s", raw_blob.blob_name)
        return []

    stream = make_named_bytes_io(content, raw_blob.blob_name)
    extracted_pages: list[ExtractedPage] = []
    async for page in parser.parse(stream):
        text = (page.text or "").strip()
        if not text:
            continue
        sourcepage = page.sourcepage or raw_blob.relative_path
        citation = sourcepage if sourcepage.startswith(raw_blob.relative_path) else f"{raw_blob.relative_path}#{sourcepage}"
        extracted_pages.append(
            ExtractedPage(
                page_num=page.page_num,
                text=text,
                citation=citation,
                title=page.title,
                url=page.url,
            )
        )
        if len(extracted_pages) >= max_pages:
            logger.warning("Truncated %s to first %d extracted pages", raw_blob.blob_name, max_pages)
            break
    return extracted_pages


def render_extracted_pages(raw_blob: RawBlob, pages: Sequence[ExtractedPage]) -> str:
    rendered_pages = [
        f"Source blob: {raw_blob.blob_name}",
        f"Source chatbot: {raw_blob.chatbot}",
        "",
    ]
    for page in pages:
        rendered_pages.append(f"--- Page {page.page_num + 1} [{page.citation}]")
        if page.title:
            rendered_pages.append(f"Title: {page.title}")
        if page.url:
            rendered_pages.append(f"URL: {page.url}")
        rendered_pages.append(page.text)
        rendered_pages.append("")
    return "\n".join(rendered_pages).strip()


def chunk_text(text: str, chunk_chars: int) -> list[str]:
    if len(text) <= chunk_chars:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for block in re.split(r"(\n--- Page \d+ \[[^\n]+\]\n)", text):
        if not block:
            continue
        for piece in split_oversized_block(block, chunk_chars):
            piece_size = len(piece)
            if current and current_size + piece_size > chunk_chars:
                chunks.append("".join(current).strip())
                current = []
                current_size = 0
            current.append(piece)
            current_size += piece_size
    if current:
        chunks.append("".join(current).strip())
    return chunks


def split_oversized_block(block: str, chunk_chars: int) -> list[str]:
    if len(block) <= chunk_chars:
        return [block]

    pieces: list[str] = []
    remaining = block
    while len(remaining) > chunk_chars:
        split_at = remaining.rfind("\n\n", 0, chunk_chars)
        if split_at < chunk_chars // 2:
            split_at = remaining.rfind("\n", 0, chunk_chars)
        if split_at < chunk_chars // 2:
            split_at = chunk_chars
        pieces.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        pieces.append(remaining)
    return pieces


def clean_markdown_response(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:markdown|md)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def build_source_page_prompt(
    raw_blob: RawBlob,
    source_text: str,
    *,
    partial: bool,
    part_label: Optional[str] = None,
) -> list[ChatCompletionMessageParam]:
    if partial:
        instruction = (
            "Extract durable source notes from this portion of a raw chatbot document. "
            "Do not write a final wiki page yet."
        )
    else:
        instruction = "Compile this raw chatbot document into one durable Markdown LLM Wiki source page."
    if part_label:
        instruction += f" This content is {part_label}; keep the page scoped to that part."

    return [
        {
            "role": "system",
            "content": (
                "You compile raw chatbot source documents into a persistent Markdown LLM Wiki.\n"
                "Use only the supplied source text. Do not invent facts. Preserve important identifiers, URLs, dates, "
                "titles, product/course names, and source caveats. Prefer concise, reusable knowledge over transcript-like copying."
            ),
        },
        {
            "role": "user",
            "content": (
                f"{instruction}\n\n"
                f"Source chatbot: {raw_blob.chatbot}\n"
                f"Raw blob: {raw_blob.blob_name}\n\n"
                + (f"Split part: {part_label}\n\n" if part_label else "")
                +
                "Required output:\n"
                "- Markdown only\n"
                "- A clear H1 title\n"
                "- A short summary\n"
                "- Key facts grouped under practical headings\n"
                "- Source trace section listing the raw blob path and page/row citations when present\n"
                "- Open questions or conflicts only when the source text itself shows uncertainty\n\n"
                f"Source text:\n{source_text}"
            ),
        },
    ]


def build_final_from_notes_prompt(
    raw_blob: RawBlob,
    partial_notes: list[str],
    *,
    part_label: Optional[str] = None,
) -> list[ChatCompletionMessageParam]:
    return [
        {
            "role": "system",
            "content": (
                "You compile partial source notes into one persistent Markdown LLM Wiki source page. "
                "Use only the supplied notes. Do not invent facts."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Source chatbot: {raw_blob.chatbot}\n"
                f"Raw blob: {raw_blob.blob_name}\n\n"
                + (f"Split part: {part_label}\n\n" if part_label else "")
                +
                "Write one Markdown page with an H1 title, summary, grouped key facts, source trace, and open questions if any.\n\n"
                "Partial notes:\n"
                + "\n\n---\n\n".join(partial_notes)
            ),
        },
    ]


async def create_chat_completion(
    openai_client: AsyncOpenAI,
    *,
    chatgpt_model: str,
    chatgpt_deployment: Optional[str],
    messages: list[ChatCompletionMessageParam],
    response_token_limit: int,
    reasoning_effort: Optional[str],
    allow_stub: bool = False,
) -> str:
    is_reasoning = chatgpt_model in Approach.GPT_REASONING_MODELS
    token_limit = response_token_limit
    last_response = ""
    for attempt in range(EMPTY_COMPLETION_RETRY_LIMIT + 1):
        if is_reasoning:
            params: dict[str, Any] = {
                "max_completion_tokens": token_limit,
                "reasoning_effort": (
                    reasoning_effort or Approach.GPT_REASONING_MODELS[chatgpt_model].supported_efforts[0]
                ),
            }
        else:
            params = {"max_tokens": token_limit, "temperature": 0.0}

        create_completion = cast(Any, openai_client.chat.completions.create)
        completion = await create_completion(
            model=chatgpt_deployment or chatgpt_model,
            messages=messages,
            **params,
        )
        raw = completion.choices[0].message.content or ""
        cleaned = clean_markdown_response(raw)
        finish_reason = getattr(completion.choices[0], "finish_reason", None)
        if cleaned and not (not allow_stub and looks_like_stub(cleaned)):
            return cleaned
        last_response = cleaned
        if attempt >= EMPTY_COMPLETION_RETRY_LIMIT:
            break
        # Reasoning models can spend the entire budget on internal reasoning and
        # leave nothing for visible output; doubling the budget on retry usually
        # gets a real answer back.
        token_limit *= EMPTY_COMPLETION_TOKEN_MULTIPLIER
        logger.warning(
            "LLM returned empty/stub content (finish_reason=%s, attempt %d/%d). Retrying with token_limit=%d",
            finish_reason,
            attempt + 1,
            EMPTY_COMPLETION_RETRY_LIMIT,
            token_limit,
        )
    if allow_stub:
        return last_response
    raise RuntimeError(
        f"LLM returned empty or stub content after {EMPTY_COMPLETION_RETRY_LIMIT + 1} attempts"
    )


async def compile_chunks_to_markdown(
    raw_blob: RawBlob,
    chunks: Sequence[str],
    *,
    openai_client: AsyncOpenAI,
    chatgpt_model: str,
    chatgpt_deployment: Optional[str],
    reasoning_effort: Optional[str],
    part_label: Optional[str] = None,
) -> str:
    if len(chunks) == 1:
        return await create_chat_completion(
            openai_client,
            chatgpt_model=chatgpt_model,
            chatgpt_deployment=chatgpt_deployment,
            messages=build_source_page_prompt(raw_blob, chunks[0], partial=False, part_label=part_label),
            response_token_limit=SOURCE_PAGE_TOKEN_LIMIT,
            reasoning_effort=reasoning_effort,
        )

    partial_notes: list[str] = []
    for chunk_number, chunk in enumerate(chunks, start=1):
        logger.info("Compiling partial notes %d/%d for %s", chunk_number, len(chunks), raw_blob.blob_name)
        notes = await create_chat_completion(
            openai_client,
            chatgpt_model=chatgpt_model,
            chatgpt_deployment=chatgpt_deployment,
            messages=build_source_page_prompt(raw_blob, chunk, partial=True, part_label=part_label),
            response_token_limit=PARTIAL_NOTES_TOKEN_LIMIT,
            reasoning_effort=reasoning_effort,
            allow_stub=True,
        )
        if notes.strip():
            partial_notes.append(notes)
    if not partial_notes:
        raise RuntimeError(f"All partial notes were empty for {raw_blob.blob_name}")

    return await create_chat_completion(
        openai_client,
        chatgpt_model=chatgpt_model,
        chatgpt_deployment=chatgpt_deployment,
        messages=build_final_from_notes_prompt(raw_blob, partial_notes, part_label=part_label),
        response_token_limit=SOURCE_PAGE_TOKEN_LIMIT,
        reasoning_effort=reasoning_effort,
    )


async def compile_source_pages(
    raw_blob: RawBlob,
    pages: Sequence[ExtractedPage],
    *,
    openai_client: AsyncOpenAI,
    chatgpt_model: str,
    chatgpt_deployment: Optional[str],
    reasoning_effort: Optional[str],
    raw_chunk_chars: int,
    max_chunks_per_wiki_page: int,
    wiki_root: str,
) -> list[tuple[str, str]]:
    source_text = render_extracted_pages(raw_blob, pages)
    chunks = chunk_text(source_text, raw_chunk_chars)
    if len(chunks) <= max_chunks_per_wiki_page:
        return [
            (
                get_source_wiki_blob_name(raw_blob, wiki_root),
                await compile_chunks_to_markdown(
                    raw_blob,
                    chunks,
                    openai_client=openai_client,
                    chatgpt_model=chatgpt_model,
                    chatgpt_deployment=chatgpt_deployment,
                    reasoning_effort=reasoning_effort,
                ),
            )
        ]

    compiled_pages: list[tuple[str, str]] = []
    total_parts = (len(chunks) + max_chunks_per_wiki_page - 1) // max_chunks_per_wiki_page
    for part_index in range(total_parts):
        part_number = part_index + 1
        part_chunks = chunks[part_index * max_chunks_per_wiki_page : part_number * max_chunks_per_wiki_page]
        part_label = f"part {part_number} of {total_parts} from {raw_blob.blob_name}"
        logger.info("Compiling wiki source page part %d/%d for %s", part_number, total_parts, raw_blob.blob_name)
        compiled_pages.append(
            (
                get_source_wiki_part_blob_name(raw_blob, part_number=part_number, wiki_root=wiki_root),
                await compile_chunks_to_markdown(
                    raw_blob,
                    part_chunks,
                    openai_client=openai_client,
                    chatgpt_model=chatgpt_model,
                    chatgpt_deployment=chatgpt_deployment,
                    reasoning_effort=reasoning_effort,
                    part_label=part_label,
                ),
            )
        )
    return compiled_pages


def build_index_markdown(chatbot: str, compiled_pages: Sequence[CompiledPage]) -> str:
    compiled_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        f"# {chatbot} LLM Wiki",
        "",
        f"Compiled at: {compiled_at}",
        "",
        "## Source Pages",
        "",
    ]
    for compiled_page in sorted(compiled_pages, key=lambda page: page.source_blob.relative_path.lower()):
        relative_wiki_path = get_compiled_page_relative_wiki_path(chatbot, compiled_page)
        title = first_markdown_heading(compiled_page.markdown) or compiled_page.source_blob.relative_path
        lines.append(f"- [{title}]({relative_wiki_path})")
    if not compiled_pages:
        lines.append("- No source pages compiled.")
    return "\n".join(lines).strip() + "\n"


def get_compiled_page_relative_wiki_path(chatbot: str, compiled_page: CompiledPage) -> str:
    marker = f"/{normalize_source_chatbot(chatbot)}/wiki/"
    if marker in compiled_page.wiki_blob_name:
        return compiled_page.wiki_blob_name.split(marker, 1)[1]
    return get_source_wiki_relative_path(compiled_page.source_blob)


def build_log_markdown(chatbot: str, raw_blobs: Sequence[RawBlob], compiled_pages: Sequence[CompiledPage]) -> str:
    compiled_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    compiled_blob_names = {page.source_blob.blob_name for page in compiled_pages}
    lines = [
        f"# {chatbot} LLM Wiki Log",
        "",
        f"- Compiled at: {compiled_at}",
        f"- Raw blobs considered: {len(raw_blobs)}",
        f"- Source pages available: {len(compiled_pages)}",
        "",
        "## Raw Blobs",
        "",
    ]
    for raw_blob in raw_blobs:
        status = "compiled" if raw_blob.blob_name in compiled_blob_names else "skipped"
        lines.append(f"- `{raw_blob.blob_name}` - {status}")
    return "\n".join(lines).strip() + "\n"


def first_markdown_heading(markdown: str) -> Optional[str]:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
    return None


async def list_raw_blobs(
    blob_manager: BlobManager,
    chatbot: str,
    *,
    recursive: bool,
    nerilio_direct_only: bool,
) -> list[RawBlob]:
    prefix = get_raw_blob_prefix(chatbot)
    entries = await blob_manager.list_blobs(prefix)
    raw_blobs: list[RawBlob] = []
    for entry in entries:
        if not isinstance(entry, BlobListEntry):
            continue
        if not should_compile_blob(
            entry.name,
            chatbot,
            nerilio_direct_only=nerilio_direct_only,
            recursive=recursive,
        ):
            continue
        raw_blobs.append(RawBlob(chatbot=chatbot, blob_name=entry.name, relative_path=entry.name.removeprefix(prefix)))
    return sorted(raw_blobs, key=lambda blob: blob.relative_path.lower())


def list_local_raw_blobs(
    local_content_root: Path,
    chatbot: str,
    *,
    recursive: bool,
    nerilio_direct_only: bool,
) -> list[RawBlob]:
    chatbot = normalize_source_chatbot(chatbot)
    source_root = local_content_root / chatbot
    if not source_root.exists():
        logger.warning("Local content folder does not exist: %s", source_root)
        return []
    if not source_root.is_dir():
        logger.warning("Local content path is not a folder: %s", source_root)
        return []

    candidates = source_root.rglob("*") if recursive else source_root.glob("*")
    raw_blobs: list[RawBlob] = []
    for path in candidates:
        if not path.is_file():
            continue
        relative_path = path.relative_to(source_root).as_posix()
        blob_name = f"{chatbot}/{relative_path}"
        if not should_compile_blob(
            blob_name,
            chatbot,
            nerilio_direct_only=nerilio_direct_only,
            recursive=recursive,
        ):
            continue
        raw_blobs.append(RawBlob(chatbot=chatbot, blob_name=blob_name, relative_path=relative_path))
    return sorted(raw_blobs, key=lambda blob: blob.relative_path.lower())


def read_local_raw_blob(local_content_root: Path, raw_blob: RawBlob) -> Optional[bytes]:
    source_path = local_content_root / raw_blob.chatbot / Path(raw_blob.relative_path)
    try:
        return source_path.read_bytes()
    except FileNotFoundError:
        logger.warning("Skipping missing local file: %s", source_path)
        return None


async def compile_chatbot_wiki(
    blob_manager: BlobManager,
    chatbot: str,
    *,
    document_intelligence_parser: Optional[Parser],
    openai_client: Optional[AsyncOpenAI],
    chatgpt_model: str,
    chatgpt_deployment: Optional[str],
    reasoning_effort: Optional[str],
    raw_chunk_chars: int,
    max_source_pages: int,
    max_chunks_per_wiki_page: int,
    recursive: bool,
    nerilio_direct_only: bool,
    wiki_root: str,
    dry_run: bool,
    overwrite: bool,
    local_content_root: Optional[Path] = None,
) -> list[CompiledPage]:
    if local_content_root is None:
        raw_blobs = await list_raw_blobs(
            blob_manager,
            chatbot,
            recursive=recursive,
            nerilio_direct_only=nerilio_direct_only,
        )
    else:
        raw_blobs = list_local_raw_blobs(
            local_content_root,
            chatbot,
            recursive=recursive,
            nerilio_direct_only=nerilio_direct_only,
        )
    logger.info("Found %d raw blob(s) for %s", len(raw_blobs), chatbot)
    for raw_blob in raw_blobs:
        logger.info("Raw source: %s", raw_blob.blob_name)
    if dry_run:
        return []

    compiled_pages: list[CompiledPage] = []
    for raw_blob in raw_blobs:
        wiki_blob_name = get_source_wiki_blob_name(raw_blob, wiki_root)
        if not overwrite and await blob_manager.blob_exists(wiki_blob_name):
            existing_markdown = await download_markdown(blob_manager, wiki_blob_name)
            if existing_markdown is not None and not looks_like_stub(existing_markdown):
                logger.info("Skipping existing wiki page %s", wiki_blob_name)
                compiled_pages.append(CompiledPage(raw_blob, wiki_blob_name, existing_markdown))
                continue
            if existing_markdown is None:
                logger.warning("Existing wiki page could not be read, recompiling %s", wiki_blob_name)
            else:
                logger.warning(
                    "Existing wiki page %s is empty or stub-shaped; recompiling", wiki_blob_name
                )

        logger.info("Downloading %s", raw_blob.blob_name)
        content = (
            read_local_raw_blob(local_content_root, raw_blob)
            if local_content_root is not None
            else await download_raw_blob(blob_manager, raw_blob)
        )
        if content is None:
            logger.warning("Skipping missing blob: %s", raw_blob.blob_name)
            continue

        try:
            pages = await extract_pages(
                raw_blob,
                content,
                document_intelligence_parser=document_intelligence_parser,
                max_pages=max_source_pages,
            )
            if not pages:
                logger.warning("Skipping blob with no extracted text: %s", raw_blob.blob_name)
                continue
            if openai_client is None:
                raise ValueError("openai_client is required to compile missing wiki pages.")
            markdown_pages = await compile_source_pages(
                raw_blob,
                pages,
                openai_client=openai_client,
                chatgpt_model=chatgpt_model,
                chatgpt_deployment=chatgpt_deployment,
                reasoning_effort=reasoning_effort,
                raw_chunk_chars=raw_chunk_chars,
                max_chunks_per_wiki_page=max_chunks_per_wiki_page,
                wiki_root=wiki_root,
            )
        except Exception:
            logger.exception("Failed to compile %s", raw_blob.blob_name)
            continue

        for compiled_wiki_blob_name, markdown in markdown_pages:
            await upload_markdown(blob_manager, compiled_wiki_blob_name, markdown)
            compiled_pages.append(CompiledPage(raw_blob, compiled_wiki_blob_name, markdown))

    await upload_markdown(
        blob_manager,
        f"{get_llm_wiki_blob_prefix(chatbot, wiki_root)}/index.md",
        build_index_markdown(chatbot, compiled_pages),
    )
    await upload_markdown(
        blob_manager,
        f"{get_llm_wiki_blob_prefix(chatbot, wiki_root)}/log.md",
        build_log_markdown(chatbot, raw_blobs, compiled_pages),
    )
    return compiled_pages


async def download_raw_blob(blob_manager: BlobManager, raw_blob: RawBlob) -> Optional[bytes]:
    download_result = await blob_manager.download_blob(raw_blob.blob_name)
    if download_result is None:
        return None
    return download_result[0]


async def upload_markdown(blob_manager: BlobManager, blob_name: str, markdown: str) -> None:
    if not markdown or not markdown.strip():
        raise RuntimeError(f"Refusing to upload empty markdown for {blob_name}")
    logger.info("Uploading wiki page %s", blob_name)
    await blob_manager.upload_blob_data(
        io.BytesIO(markdown.encode("utf-8")),
        blob_name,
        content_type="text/markdown; charset=utf-8",
    )


async def download_markdown(blob_manager: BlobManager, blob_name: str) -> Optional[str]:
    download_result = await blob_manager.download_blob(blob_name)
    if download_result is None:
        return None
    return download_result[0].decode("utf-8", errors="replace")


def build_document_intelligence_parser(credential: AsyncTokenCredential | str) -> Optional[Parser]:
    document_intelligence_service = os.getenv("AZURE_DOCUMENTINTELLIGENCE_SERVICE")
    if not document_intelligence_service:
        return None
    document_intelligence_key = clean_key_if_exists(os.getenv("AZURE_DOCUMENTINTELLIGENCE_KEY"))
    parser_credential: AsyncTokenCredential | AzureKeyCredential
    if document_intelligence_key:
        parser_credential = AzureKeyCredential(document_intelligence_key)
    elif isinstance(credential, str):
        return None
    else:
        parser_credential = credential
    return DocumentAnalysisParser(
        endpoint=f"https://{document_intelligence_service}.cognitiveservices.azure.com/",
        credential=parser_credential,
    )


async def run(args: argparse.Namespace) -> None:
    load_azd_env()

    excluded = {normalize_source_chatbot(chatbot) for chatbot in args.exclude}
    chatbots = (
        [normalize_source_chatbot(chatbot) for chatbot in args.chatbot]
        if args.chatbot
        else get_default_chatbots(excluded)
    )

    tenant_id = os.getenv("AZURE_TENANT_ID")
    azure_credential = (
        AzureDeveloperCliCredential(tenant_id=tenant_id, process_timeout=60)
        if tenant_id
        else AzureDeveloperCliCredential(process_timeout=60)
    )

    blob_manager: BlobManager | None = None
    openai_client: AsyncOpenAI | None = None
    try:
        storage_key = clean_key_if_exists(args.storagekey)
        blob_manager = setup_blob_manager(
            azure_credential=azure_credential,
            storage_account=os.environ["AZURE_STORAGE_ACCOUNT"],
            storage_container=os.environ["AZURE_STORAGE_CONTAINER"],
            storage_resource_group=os.environ.get("AZURE_STORAGE_RESOURCE_GROUP"),
            subscription_id=os.environ.get("AZURE_SUBSCRIPTION_ID"),
            storage_key=storage_key,
            image_storage_container=os.environ.get("AZURE_IMAGESTORAGE_CONTAINER"),
        )
        document_intelligence_parser = (
            build_document_intelligence_parser(storage_key or azure_credential)
            if args.use_doc_intelligence
            else None
        )
        if document_intelligence_parser is not None:
            logger.info("Document Intelligence parser ENABLED (--use-doc-intelligence)")
        else:
            logger.info("Document Intelligence parser disabled; PDFs will be parsed with PyMuPDF")

        if not args.dry_run:
            openai_host = OpenAIHost(os.getenv("OPENAI_HOST", "azure"))
            openai_client, _azure_openai_endpoint = setup_openai_client(
                openai_host=openai_host,
                azure_credential=azure_credential,
                azure_openai_service=os.getenv("AZURE_OPENAI_SERVICE"),
                azure_openai_custom_url=os.getenv("AZURE_OPENAI_CUSTOM_URL"),
                azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY_OVERRIDE"),
                openai_api_key=clean_key_if_exists(os.getenv("OPENAI_API_KEY")),
                openai_organization=os.getenv("OPENAI_ORGANIZATION"),
            )

        chatgpt_model = args.model or os.environ["AZURE_OPENAI_CHATGPT_MODEL"]
        openai_host = OpenAIHost(os.getenv("OPENAI_HOST", "azure"))
        chatgpt_deployment = (
            args.deployment
            or (os.getenv("AZURE_OPENAI_CHATGPT_DEPLOYMENT") if openai_host in {OpenAIHost.AZURE, OpenAIHost.AZURE_CUSTOM} else None)
        )
        local_content_root = Path(args.local_content_root).resolve() if args.local_content_root else None

        total_compiled = 0
        for chatbot in chatbots:
            compiled_pages = await compile_chatbot_wiki(
                blob_manager,
                chatbot,
                document_intelligence_parser=document_intelligence_parser,
                openai_client=openai_client,
                chatgpt_model=chatgpt_model,
                chatgpt_deployment=chatgpt_deployment,
                reasoning_effort=args.reasoning_effort,
                raw_chunk_chars=args.raw_chunk_chars,
                max_source_pages=args.max_source_pages,
                max_chunks_per_wiki_page=args.max_chunks_per_wiki_page,
                recursive=not args.direct_only,
                nerilio_direct_only=not args.include_nerilio_folders,
                wiki_root=args.wiki_root,
                dry_run=args.dry_run,
                overwrite=args.overwrite,
                local_content_root=local_content_root,
            )
            total_compiled += len(compiled_pages)
        logger.info("Prepared %d wiki source page(s)", total_compiled)
    finally:
        if openai_client is not None:
            await openai_client.close()
        if blob_manager is not None:
            await blob_manager.close_clients()
        await azure_credential.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compile raw chatbot blobs into persistent Markdown LLM Wiki pages in blob storage."
    )
    parser.add_argument("--chatbot", action="append", default=[], help="Chatbot to compile. May be repeated.")
    parser.add_argument(
        "--exclude",
        action="append",
        default=sorted(DEFAULT_EXCLUDED_CHATBOTS),
        help="Chatbot to exclude when --chatbot is not provided. May be repeated.",
    )
    parser.add_argument("--wiki-root", default=LLM_WIKI_BLOB_ROOT, help="Root blob prefix for compiled wiki pages.")
    parser.add_argument(
        "--local-content-root",
        help="Read raw source files from this local content root instead of the configured blob container.",
    )
    parser.add_argument("--storagekey", help="Optional Azure Storage key override.")
    parser.add_argument("--model", help="Chat model id override.")
    parser.add_argument("--deployment", help="Azure OpenAI deployment override.")
    parser.add_argument("--reasoning-effort", default="low", help="Reasoning effort for reasoning-capable models.")
    parser.add_argument("--raw-chunk-chars", type=int, default=DEFAULT_RAW_CHUNK_CHARS)
    parser.add_argument("--max-source-pages", type=int, default=DEFAULT_MAX_SOURCE_PAGES)
    parser.add_argument("--max-chunks-per-wiki-page", type=int, default=DEFAULT_MAX_CHUNKS_PER_WIKI_PAGE)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Recompile and overwrite wiki pages that already exist. By default existing pages are reused.",
    )
    parser.add_argument("--direct-only", action="store_true", help="Only compile blobs directly under each chatbot prefix.")
    parser.add_argument(
        "--include-nerilio-folders",
        action="store_true",
        help="Also compile nested blobs under nerilio/. By default they are ignored.",
    )
    parser.add_argument("--dry-run", action="store_true", help="List target raw blobs without calling the LLM or writing wiki pages.")
    parser.add_argument(
        "--use-doc-intelligence",
        action="store_true",
        help="Use Azure Document Intelligence for PDF parsing (extra cost). Off by default; PyMuPDF is used instead.",
    )
    parser.set_defaults(func=run)
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
    logging.getLogger("azure.identity").setLevel(logging.WARNING)
    parser = build_arg_parser()
    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
