"""Parser for the snap.de + nerilio.ai website feed (data/snap.json).

The feed is a single JSON object scraped by ``scripts/scrape_snap.py``: snap.de
pages/posts via the WordPress REST API plus nerilio.ai pages via a sitemap crawl
(their record ids are prefixed ``nerilio-``), and one dedicated header/footer
site-info document per site. Each record has a first-class ``title`` and live
``url`` so citations link back to the public page instead of a storage blob. The
feed keeps the ``"feed": "snap.de"`` marker and is ingested into Azure AI Search
under category ``snap`` either by uploading ``snap.json`` through the admin
managed-file uploader (which routes here via ``build_snap_sections_if_applicable``).

Shape::

    {
        "feed": "snap.de",
        "generated_at": "2026-06-24T10:00:00Z",
        "count": 39,
        "documents": [
            {
                "id": "snap-tools-nerilio",
                "title": "Nerilio - ...",
                "url": "https://www.snap.de/tools/nerilio/",
                "content": "clean markdown ...",
                "tags": ["tools"],
                "type": "page",
                "date": "2026-05-07"
            }
        ]
    }
"""

import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .hyroxjson import load_json_payload, sanitize_identifier, split_content_exact
from .listfilestrategy import File
from .page import Chunk
from .searchmanager import Section

logger = logging.getLogger("scripts")

SNAP_FEED_MARKER = "snap.de"
DEFAULT_MAX_CHUNK_TOKENS = 650


@dataclass(frozen=True)
class SnapPreparedDocument:
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
class SnapPreparedDataset:
    documents: list[SnapPreparedDocument]


def get_required_string_field(record: dict[str, Any], field_name: str, *, allow_empty: bool = False) -> str:
    value = record.get(field_name)
    if not isinstance(value, str):
        raise ValueError(f"snap record field '{field_name}' must be a string")
    if not allow_empty and not value:
        raise ValueError(f"snap record field '{field_name}' must be a non-empty string")
    return value


def get_string_list_field(record: dict[str, Any], field_name: str) -> list[str]:
    value = record.get(field_name)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"snap record field '{field_name}' must be an array of strings")
    return value


def is_snap_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("feed") == SNAP_FEED_MARKER


def validate_snap_payload(payload: Any) -> list[dict[str, Any]]:
    if not is_snap_payload(payload):
        raise ValueError("snap payload must be a JSON object with 'feed' set to 'snap.de'")

    documents = payload.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("snap payload must contain a non-empty 'documents' array")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, record in enumerate(documents):
        if not isinstance(record, dict):
            raise ValueError(f"snap document at index {index} must be a JSON object")

        record_id = get_required_string_field(record, "id")
        get_required_string_field(record, "title")
        get_required_string_field(record, "url")
        get_required_string_field(record, "content", allow_empty=True)
        get_string_list_field(record, "tags")

        if record_id in seen_ids:
            raise ValueError(f"snap payload contains duplicate id '{record_id}'")
        seen_ids.add(record_id)
        records.append(record)

    return records


def prepare_snap_dataset(
    payload: Any,
    *,
    dataset_filename: str,
    category: str,
    max_chunk_tokens: int = DEFAULT_MAX_CHUNK_TOKENS,
) -> SnapPreparedDataset:
    records = validate_snap_payload(payload)
    sourcefile = os.path.basename(dataset_filename)
    dataset_slug = sanitize_identifier(Path(sourcefile).stem)
    prepared_documents: list[SnapPreparedDocument] = []

    for record in records:
        record_id = get_required_string_field(record, "id")
        title = get_required_string_field(record, "title")
        url = get_required_string_field(record, "url")
        tags = list(dict.fromkeys(get_string_list_field(record, "tags")))
        page_type = (record.get("type") or "").strip() if isinstance(record.get("type"), str) else ""
        if page_type and page_type not in tags:
            tags.append(page_type)

        content_chunks = split_content_exact(
            get_required_string_field(record, "content", allow_empty=True),
            max_chunk_tokens=max_chunk_tokens,
        )

        for chunk_index, chunk_text in enumerate(content_chunks, start=1):
            prepared_documents.append(
                SnapPreparedDocument(
                    id=f"{dataset_slug}-{sanitize_identifier(record_id)}-chunk-{chunk_index:03d}",
                    content=chunk_text,
                    category=category,
                    sourcepage=record_id,
                    sourcefile=sourcefile,
                    title=title,
                    url=url,
                    tags=tags,
                )
            )

    return SnapPreparedDataset(documents=prepared_documents)


def prepared_document_to_section(document: SnapPreparedDocument, file: File, page_num: int) -> Section:
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


def prepare_snap_sections(
    payload: Any,
    *,
    file: File,
    category: str,
    max_chunk_tokens: int = DEFAULT_MAX_CHUNK_TOKENS,
) -> list[Section]:
    dataset = prepare_snap_dataset(
        payload,
        dataset_filename=file.filename(),
        category=category,
        max_chunk_tokens=max_chunk_tokens,
    )
    return [
        prepared_document_to_section(document, file, page_num=index) for index, document in enumerate(dataset.documents)
    ]


async def build_snap_sections_if_applicable(
    *,
    file: File,
    category: Optional[str],
    check_cancel: Optional[Callable[[], Awaitable[None]]] = None,
) -> Optional[list[Section]]:
    if (category or "").strip().lower() != "snap" or file.file_extension().lower() != ".json":
        return None

    if check_cancel is not None:
        await check_cancel()

    payload = load_json_payload(file)
    if not is_snap_payload(payload):
        return None

    logger.info("Using snap-specific JSON parser for '%s'", file.filename())
    sections = prepare_snap_sections(payload, file=file, category="snap")

    if check_cancel is not None:
        await check_cancel()

    return sections
