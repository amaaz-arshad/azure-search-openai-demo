import logging
import re
from dataclasses import dataclass
from typing import Any

import tiktoken

from .page import Page
from .textsplitter import ENCODING_MODEL, SentenceTextSplitter

logger = logging.getLogger("scripts")

DEFAULT_MAX_CHUNK_TOKENS = 650
MIN_CONTENT_CHUNK_TOKENS = 200


@dataclass
class FhgPreparedDocument:
    id: str
    content: str
    category: str
    sourcepage: str
    sourcefile: str
    title: str
    url: str
    tags: list[str]
    user: str | None = None

    def to_search_document(
        self,
        *,
        storage_url: str,
        acls: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        document = {
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
        if self.user is not None:
            document["user"] = self.user
        return document


@dataclass
class FhgPreparedDataset:
    documents: list[FhgPreparedDocument]


def prepare_fhg_dataset(
    payload: dict[str, Any],
    *,
    dataset_filename: str,
    category: str,
    max_chunk_tokens: int = DEFAULT_MAX_CHUNK_TOKENS,
) -> FhgPreparedDataset:
    documents_payload, dataset_count = validate_fhg_payload(payload)

    prepared_documents: list[FhgPreparedDocument] = []

    for study_index, study in enumerate(documents_payload, start=1):
        doc_id = resolve_doc_id(study, study_index)
        title = resolve_title(study, doc_id)
        url = get_text_field(study, "url").strip()
        chunk_texts = build_chunk_texts(
            study=study,
            dataset_filename=dataset_filename,
            dataset_count=dataset_count,
            category=category,
            max_chunk_tokens=max_chunk_tokens,
        )

        for chunk_index, chunk_text in enumerate(chunk_texts, start=1):
            prepared_documents.append(
                FhgPreparedDocument(
                    id=f"fhg-{doc_id}-chunk-{chunk_index:03d}",
                    content=chunk_text,
                    category=category,
                    sourcepage=make_sourcepage_value(study, doc_id=doc_id),
                    sourcefile=get_text_field(study, "filename").strip(),
                    title=title,
                    url=url,
                    tags=require_string_list_field(study, "tags"),
                )
            )

    return FhgPreparedDataset(documents=prepared_documents)


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


def make_sourcepage_value(study: dict[str, Any], *, doc_id: str) -> str:
    parent_id = get_text_field(study, "parent_id").strip() or "none"
    return f"doc_id={doc_id};parent_id={parent_id}"


def build_chunk_texts(
    *,
    study: dict[str, Any],
    dataset_filename: str,
    dataset_count: int,
    category: str,
    max_chunk_tokens: int,
) -> list[str]:
    _ = dataset_filename, dataset_count, category
    metadata_lines = build_metadata_lines(study)
    header_without_chunk = "\n".join(metadata_lines)
    content_value = get_text_field(study, "content")
    content_chunks = split_content_into_chunks(content_value, header_without_chunk, max_chunk_tokens)

    rendered_chunks: list[str] = []
    for chunk in content_chunks:
        rendered_chunks.append(
            "\n".join(
                [
                    *metadata_lines,
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

    categories = require_string_list_field(study, "category")
    tags = require_string_list_field(study, "tags")

    title = (
        get_text_field(study, "title").strip()
        or get_text_field(study, "filename").strip()
        or get_text_field(study, "url").strip()
        or get_text_field(study, "doc_id").strip()
        or "Untitled FHG document"
    )

    lines = [f"title: {title}"]

    if categories:
        lines.append(f"categories: {', '.join(categories)}")
    if tags:
        lines.append(f"tags: {', '.join(tags)}")

    for key in [
        "studium_name",
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

def require_string_field(study: dict[str, Any], field_name: str) -> str:
    value = study.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"FHG study field '{field_name}' must be a non-empty string")
    return value


def resolve_doc_id(study: dict[str, Any], fallback_index: int) -> str:
    doc_id = get_text_field(study, "doc_id").strip()
    if doc_id:
        return doc_id
    return f"fhg-record-{fallback_index:04d}"


def resolve_title(study: dict[str, Any], doc_id: str) -> str:
    title = get_text_field(study, "title").strip()
    if title:
        return title
    filename = get_text_field(study, "filename").strip()
    if filename:
        return filename
    url = get_text_field(study, "url").strip()
    if url:
        return url
    return doc_id


def get_text_field(study: dict[str, Any], field_name: str) -> str:
    value = study.get(field_name)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"FHG study field '{field_name}' must be a string when present")
    return value


def get_optional_string_field(study: dict[str, Any], field_name: str) -> str | None:
    value = study.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"FHG study field '{field_name}' must be a non-empty string when present")
    return value


def require_string_list_field(study: dict[str, Any], field_name: str) -> list[str]:
    value = study.get(field_name)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"FHG study field '{field_name}' must be an array of strings")
    return value
