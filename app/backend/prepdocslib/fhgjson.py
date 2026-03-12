import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import tiktoken

from .page import Page
from .textsplitter import ENCODING_MODEL, SentenceTextSplitter

logger = logging.getLogger("scripts")

DEFAULT_SOURCEPAGE_PREFIX = "fhg"
DEFAULT_MAX_CHUNK_TOKENS = 650
MIN_CONTENT_CHUNK_TOKENS = 200


@dataclass
class FhgPreparedDocument:
    id: str
    content: str
    category: str
    sourcepage: str
    sourcefile: str
    storage_url: str

    def to_search_document(self, acls: dict[str, list[str]] | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "sourcepage": self.sourcepage,
            "sourcefile": self.sourcefile,
            "storageUrl": self.storage_url,
            **(acls or {}),
        }


@dataclass
class FhgSourceBlob:
    name: str
    text: str


@dataclass
class FhgPreparedDataset:
    documents: list[FhgPreparedDocument]
    source_blobs: list[FhgSourceBlob]


def prepare_fhg_dataset(
    payload: dict[str, Any],
    *,
    dataset_filename: str,
    category: str,
    sourcepage_prefix: str = DEFAULT_SOURCEPAGE_PREFIX,
    max_chunk_tokens: int = DEFAULT_MAX_CHUNK_TOKENS,
) -> FhgPreparedDataset:
    documents_payload, dataset_count = validate_fhg_payload(payload)

    prepared_documents: list[FhgPreparedDocument] = []
    source_blobs: list[FhgSourceBlob] = []

    for study in documents_payload:
        sourcepage = make_sourcepage_name(study, prefix=sourcepage_prefix)
        source_text = build_source_blob_text(
            study=study,
            dataset_filename=dataset_filename,
            dataset_count=dataset_count,
            category=category,
        )
        source_blobs.append(FhgSourceBlob(name=sourcepage, text=source_text))

        chunk_texts = build_chunk_texts(
            study=study,
            dataset_filename=dataset_filename,
            dataset_count=dataset_count,
            category=category,
            max_chunk_tokens=max_chunk_tokens,
        )

        doc_id = require_string_field(study, "doc_id")
        for chunk_index, chunk_text in enumerate(chunk_texts, start=1):
            prepared_documents.append(
                FhgPreparedDocument(
                    id=f"fhg-{doc_id}-chunk-{chunk_index:03d}",
                    content=chunk_text,
                    category=category,
                    sourcepage=sourcepage,
                    sourcefile=dataset_filename,
                    storage_url=require_string_field(study, "url"),
                )
            )

    return FhgPreparedDataset(documents=prepared_documents, source_blobs=source_blobs)


def validate_fhg_payload(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict):
        raise ValueError("FHG payload must be a JSON object")

    documents = payload.get("documents")
    if not isinstance(documents, list):
        raise ValueError("FHG payload must contain a top-level 'documents' array")

    normalized_documents: list[dict[str, Any]] = []
    for index, study in enumerate(documents):
        if not isinstance(study, dict):
            raise ValueError(f"FHG document at index {index} must be a JSON object")
        normalized_documents.append(study)

    dataset_count = payload.get("count")
    if dataset_count is None:
        dataset_count = len(normalized_documents)
    elif not isinstance(dataset_count, int):
        raise ValueError("FHG payload field 'count' must be an integer when present")
    elif dataset_count != len(normalized_documents):
        logger.warning(
            "FHG payload count is %d but documents array contains %d entries; using the documents array length",
            dataset_count,
            len(normalized_documents),
        )
        dataset_count = len(normalized_documents)

    return normalized_documents, dataset_count


def make_sourcepage_name(study: dict[str, Any], *, prefix: str) -> str:
    title_slug = slugify(require_string_field(study, "title"))
    doc_id = slugify(require_string_field(study, "doc_id"))
    filename_slug = slugify(require_string_field(study, "filename").split("/")[-1])
    stable_slug = title_slug or filename_slug or doc_id or "fhg-document"
    return f"{prefix}/{stable_slug}-{doc_id}.txt"


def build_source_blob_text(
    *,
    study: dict[str, Any],
    dataset_filename: str,
    dataset_count: int,
    category: str,
) -> str:
    dataset_json = build_dataset_json(
        dataset_filename=dataset_filename,
        dataset_count=dataset_count,
        category=category,
    )
    return "\n".join(
        [
            f"title: {require_string_field(study, 'title')}",
            f"url: {require_string_field(study, 'url')}",
            f"dataset_json: {dataset_json}",
            "document_json:",
            json.dumps(study, ensure_ascii=False, indent=2, sort_keys=True),
        ]
    )


def build_chunk_texts(
    *,
    study: dict[str, Any],
    dataset_filename: str,
    dataset_count: int,
    category: str,
    max_chunk_tokens: int,
) -> list[str]:
    dataset_json = build_dataset_json(
        dataset_filename=dataset_filename,
        dataset_count=dataset_count,
        category=category,
    )
    metadata_lines = build_metadata_lines(study)
    header_without_chunk = "\n".join(
        [
            *metadata_lines,
            f"dataset_json: {dataset_json}",
        ]
    )
    content_value = require_string_field(study, "content")
    content_chunks = split_content_into_chunks(content_value, header_without_chunk, max_chunk_tokens)

    rendered_chunks: list[str] = []
    chunk_count = len(content_chunks)
    for chunk_index, chunk in enumerate(content_chunks, start=1):
        rendered_chunks.append(
            "\n".join(
                [
                    *metadata_lines,
                    f"dataset_json: {dataset_json}",
                    f"chunk: {chunk_index}/{chunk_count}",
                    "",
                    "content:",
                    chunk,
                ]
            )
        )

    return rendered_chunks


def build_metadata_lines(study: dict[str, Any]) -> list[str]:
    metadata = study.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("FHG study field 'metadata' must be an object")

    categories = study.get("category")
    if categories is None:
        categories = []
    if not isinstance(categories, list) or not all(isinstance(item, str) for item in categories):
        raise ValueError("FHG study field 'category' must be an array of strings")

    tags = study.get("tags")
    if tags is None:
        tags = []
    if not isinstance(tags, list) or not all(isinstance(item, str) for item in tags):
        raise ValueError("FHG study field 'tags' must be an array of strings")

    lines = [
        f"title: {require_string_field(study, 'title')}",
        f"doc_id: {require_string_field(study, 'doc_id')}",
        f"parent_id: {require_string_field(study, 'parent_id')}",
        f"filename: {require_string_field(study, 'filename')}",
        f"url: {require_string_field(study, 'url')}",
        f"categories: {json.dumps(categories, ensure_ascii=False)}",
        f"tags: {json.dumps(tags, ensure_ascii=False)}",
        f"metadata_json: {json.dumps(metadata, ensure_ascii=False, sort_keys=True)}",
    ]

    study_name = metadata.get("studium_name")
    if isinstance(study_name, str) and study_name:
        lines.append(f"studium_name: {study_name}")

    for key in [
        "degree_type",
        "degree_name",
        "degree_abbreviation",
        "subtitle",
        "description",
        "keywords",
        "ausbildungszweige",
    ]:
        value = metadata.get(key)
        if isinstance(value, str) and value:
            lines.append(f"{key}: {value}")

    return lines


def split_content_into_chunks(content: str, header_without_chunk: str, max_chunk_tokens: int) -> list[str]:
    paragraphs = split_paragraphs(content)
    if not paragraphs:
        return [""]

    encoding = tiktoken.encoding_for_model(ENCODING_MODEL)
    header_tokens = len(encoding.encode(header_without_chunk))
    body_budget = max(MIN_CONTENT_CHUNK_TOKENS, max_chunk_tokens - header_tokens - 25)

    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    for paragraph in paragraphs:
        paragraph_tokens = len(encoding.encode(paragraph))
        if paragraph_tokens > body_budget:
            if current_parts:
                chunks.append("\n\n".join(current_parts))
                current_parts = []
                current_tokens = 0
            chunks.extend(split_oversized_paragraph(paragraph, body_budget))
            continue

        separator_tokens = 0 if not current_parts else len(encoding.encode("\n\n"))
        if current_tokens + separator_tokens + paragraph_tokens <= body_budget:
            current_parts.append(paragraph)
            current_tokens += separator_tokens + paragraph_tokens
            continue

        chunks.append("\n\n".join(current_parts))
        current_parts = [paragraph]
        current_tokens = paragraph_tokens

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks or [content.strip()]


def split_oversized_paragraph(paragraph: str, body_budget: int) -> list[str]:
    splitter = SentenceTextSplitter(max_tokens_per_section=body_budget)
    splitter.max_section_length = max(splitter.max_section_length, body_budget * 5)
    splitter.section_overlap = int(splitter.max_section_length * 0.1)

    pages = [Page(page_num=0, offset=0, text=paragraph)]
    return [chunk.text.strip() for chunk in splitter.split_pages(pages) if chunk.text.strip()] or [paragraph.strip()]


def split_paragraphs(content: str) -> list[str]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    return [paragraph.strip() for paragraph in re.split(r"\n\s*\n+", normalized) if paragraph.strip()]


def build_dataset_json(*, dataset_filename: str, dataset_count: int, category: str) -> str:
    return json.dumps(
        {
            "dataset_filename": dataset_filename,
            "dataset_count": dataset_count,
            "index_category": category,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def require_string_field(study: dict[str, Any], field_name: str) -> str:
    value = study.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"FHG study field '{field_name}' must be a non-empty string")
    return value


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^0-9a-zA-Z]+", "-", ascii_value).strip("-").lower()
    return slug
