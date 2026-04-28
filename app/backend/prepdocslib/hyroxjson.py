import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import tiktoken

from .listfilestrategy import File
from .page import Chunk
from .searchmanager import Section
from .textsplitter import ENCODING_MODEL

logger = logging.getLogger("scripts")

HYROX_SOURCE_CATEGORY = "HYROX Academy Level 1"
DEFAULT_MAX_CHUNK_TOKENS = 650


@dataclass(frozen=True)
class HyroxPreparedDocument:
    id: str
    content: str
    category: str
    sourcepage: str
    sourcefile: str
    title: str
    url: str
    tags: list[str]

    def to_search_document(
        self,
        *,
        storage_url: str,
        acls: Optional[dict[str, list[str]]] = None,
    ) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "sourcepage": self.sourcepage,
            "sourcefile": self.sourcefile,
            "storageUrl": storage_url,
            "title": self.title,
            "url": self.url,
            "tags": self.tags,
            **(acls or {}),
        }


@dataclass(frozen=True)
class HyroxPreparedDataset:
    documents: list[HyroxPreparedDocument]


def sanitize_identifier(value: str) -> str:
    normalized_value = value.replace("_", "-")
    return re.sub(r"[^0-9A-Za-z-]+", "-", normalized_value).strip("-").lower() or "document"


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def get_required_string_field(record: dict[str, Any], field_name: str, *, allow_empty: bool = False) -> str:
    value = record.get(field_name)
    if not isinstance(value, str):
        raise ValueError(f"HYROX record field '{field_name}' must be a string")
    if not allow_empty and not value:
        raise ValueError(f"HYROX record field '{field_name}' must be a non-empty string")
    return value


def get_optional_string_field(record: dict[str, Any], field_name: str) -> str | None:
    value = record.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"HYROX record field '{field_name}' must be a string when present")
    return value


def get_required_string_list_field(record: dict[str, Any], field_name: str) -> list[str]:
    value = record.get(field_name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"HYROX record field '{field_name}' must be an array of strings")
    return value


def validate_hyrox_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("HYROX payload must be a top-level JSON array")
    if not payload:
        raise ValueError("HYROX payload must contain at least one record")

    records: list[dict[str, Any]] = []
    seen_lms_ids: set[str] = set()
    for index, record in enumerate(payload):
        if not isinstance(record, dict):
            raise ValueError(f"HYROX record at index {index} must be a JSON object")

        for field_name in ["id", "title", "category", "lms_id", "url"]:
            get_required_string_field(record, field_name)
        get_required_string_field(record, "content", allow_empty=True)
        get_required_string_list_field(record, "tags")

        for optional_field_name in ["summary", "author", "date", "version"]:
            get_optional_string_field(record, optional_field_name)

        source_category = get_required_string_field(record, "category")
        if source_category != HYROX_SOURCE_CATEGORY:
            raise ValueError(f"HYROX record at index {index} has unsupported category '{source_category}'")

        lms_id = get_required_string_field(record, "lms_id")
        if lms_id in seen_lms_ids:
            raise ValueError(f"HYROX payload contains duplicate lms_id '{lms_id}'")
        seen_lms_ids.add(lms_id)
        records.append(record)

    return records


def is_hyrox_payload(payload: Any) -> bool:
    try:
        validate_hyrox_payload(payload)
    except ValueError:
        return False
    return True


def has_hyrox_source_category(payload: Any) -> bool:
    if not isinstance(payload, list):
        return False
    return any(isinstance(record, dict) and record.get("category") == HYROX_SOURCE_CATEGORY for record in payload)


def load_json_payload(file: File) -> Any:
    file.content.seek(0)
    raw_content = file.content.read()
    file.content.seek(0)
    if isinstance(raw_content, bytes):
        return json.loads(raw_content.decode("utf-8"))
    return json.loads(raw_content)


def split_content_exact(content: str, max_chunk_tokens: int = DEFAULT_MAX_CHUNK_TOKENS) -> list[str]:
    if content == "":
        return [""]

    encoding = tiktoken.encoding_for_model(ENCODING_MODEL)
    if len(encoding.encode(content)) <= max_chunk_tokens:
        return [content]

    chunks: list[str] = []
    start = 0
    while start < len(content):
        remaining_text = content[start:]
        if len(encoding.encode(remaining_text)) <= max_chunk_tokens:
            chunks.append(remaining_text)
            break

        hard_end = find_max_token_end(content, start, max_chunk_tokens, encoding)
        if hard_end <= start:
            hard_end = min(len(content), start + 1)

        split_end = choose_split_boundary(content, start, hard_end)
        if split_end <= start:
            split_end = hard_end

        chunks.append(content[start:split_end])
        start = split_end

    return chunks or [content]


def find_max_token_end(content: str, start: int, max_chunk_tokens: int, encoding: tiktoken.Encoding) -> int:
    low = start + 1
    high = len(content)
    best = start

    while low <= high:
        mid = (low + high) // 2
        token_count = len(encoding.encode(content[start:mid]))
        if token_count <= max_chunk_tokens:
            best = mid
            low = mid + 1
        else:
            high = mid - 1

    return best


def choose_split_boundary(content: str, start: int, hard_end: int) -> int:
    if hard_end >= len(content):
        return len(content)

    lower_bound = start + max(1, int((hard_end - start) * 0.55))
    candidates: list[int] = []

    for separator in ["\n\n", "\n"]:
        index = content.rfind(separator, lower_bound, hard_end)
        if index > start:
            candidates.append(index + len(separator))

    sentence_match = None
    for match in re.finditer(r"[.!?]\s+", content[lower_bound:hard_end]):
        sentence_match = match
    if sentence_match is not None:
        candidates.append(lower_bound + sentence_match.end())

    space_index = content.rfind(" ", lower_bound, hard_end)
    if space_index > start:
        candidates.append(space_index + 1)

    return max(candidates) if candidates else hard_end


def prepare_hyrox_dataset(
    payload: Any,
    *,
    dataset_filename: str,
    category: str,
    max_chunk_tokens: int = DEFAULT_MAX_CHUNK_TOKENS,
) -> HyroxPreparedDataset:
    records = validate_hyrox_payload(payload)
    sourcefile = os.path.basename(dataset_filename)
    dataset_slug = sanitize_identifier(Path(sourcefile).stem)
    prepared_documents: list[HyroxPreparedDocument] = []

    for record in records:
        lms_id = get_required_string_field(record, "lms_id")
        title = get_required_string_field(record, "title")
        source_category = get_required_string_field(record, "category")
        tags = dedupe_preserve_order([*get_required_string_list_field(record, "tags"), source_category])
        content_chunks = split_content_exact(
            get_required_string_field(record, "content", allow_empty=True),
            max_chunk_tokens=max_chunk_tokens,
        )

        for chunk_index, chunk_text in enumerate(content_chunks, start=1):
            prepared_documents.append(
                HyroxPreparedDocument(
                    id=f"{dataset_slug}-{sanitize_identifier(lms_id)}-chunk-{chunk_index:03d}",
                    content=chunk_text,
                    category=category,
                    sourcepage=lms_id,
                    sourcefile=sourcefile,
                    title=title,
                    url=get_required_string_field(record, "url"),
                    tags=tags,
                )
            )

    return HyroxPreparedDataset(documents=prepared_documents)


def prepared_document_to_section(document: HyroxPreparedDocument, file: File, page_num: int) -> Section:
    return Section(
        chunk=Chunk(page_num=page_num, text=document.content),
        content=file,
        category=document.category,
        id=document.id,
        sourcepage=document.sourcepage,
        sourcefile=document.sourcefile,
        title=document.title,
        url=document.url,
        tags=document.tags,
    )


def prepare_hyrox_sections(
    payload: Any,
    *,
    file: File,
    category: str,
    max_chunk_tokens: int = DEFAULT_MAX_CHUNK_TOKENS,
) -> list[Section]:
    dataset = prepare_hyrox_dataset(
        payload,
        dataset_filename=file.filename(),
        category=category,
        max_chunk_tokens=max_chunk_tokens,
    )
    return [
        prepared_document_to_section(document, file, page_num=index) for index, document in enumerate(dataset.documents)
    ]


async def build_hyrox_sections_if_applicable(
    *,
    file: File,
    category: Optional[str],
    check_cancel: Optional[Callable[[], Awaitable[None]]] = None,
) -> Optional[list[Section]]:
    if (category or "").strip().lower() != "lemon" or file.file_extension().lower() != ".json":
        return None

    if check_cancel is not None:
        await check_cancel()

    payload = load_json_payload(file)
    if not has_hyrox_source_category(payload):
        return None

    logger.info("Using HYROX-specific JSON parser for '%s'", file.filename())
    sections = prepare_hyrox_sections(payload, file=file, category="lemon")

    if check_cancel is not None:
        await check_cancel()

    return sections
