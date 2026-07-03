import logging
import os
import re
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .hyroxjson import (
    DEFAULT_MAX_CHUNK_TOKENS,
    dedupe_preserve_order,
    sanitize_identifier,
    split_content_exact,
)
from .listfilestrategy import File
from .page import Chunk
from .searchmanager import Section
from .xmlparser import cleanup_xml_text, normalize_tag

logger = logging.getLogger("scripts")

LEMON_CATEGORY = "lemon"
LEMON_KNOWLEDGE_ROOT_TAG = "knowledge"
# Citation title is "<unit title> — <section title>" so citations carry module context.
TITLE_SEPARATOR = " — "
# unit_url / url_template values in the demo export are literal placeholders; a value
# containing this marker is treated as "no URL yet" so citations omit the link until the
# client supplies live URLs (re-running the same parser then populates them automatically).
PLACEHOLDER_URL_MARKER = "PLACEHOLDER"


@dataclass(frozen=True)
class LemonXmlPreparedDocument:
    id: str
    content: str
    category: str
    sourcepage: str
    sourcefile: str
    title: str
    url: Optional[str]
    tags: list[str]


@dataclass(frozen=True)
class LemonXmlPreparedDataset:
    documents: list[LemonXmlPreparedDocument]


def normalize_text(value: Optional[str]) -> str:
    return cleanup_xml_text(value or "")


def iter_child_elements(element: ET.Element) -> list[ET.Element]:
    return [child for child in list(element) if isinstance(child.tag, str)]


def get_direct_child(element: ET.Element, tag_name: str) -> Optional[ET.Element]:
    for child in iter_child_elements(element):
        if normalize_tag(child.tag) == tag_name:
            return child
    return None


def get_direct_child_text(element: ET.Element, tag_name: str) -> str:
    child = get_direct_child(element, tag_name)
    if child is None:
        return ""
    return normalize_text("".join(child.itertext()))


def split_tag_values(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [value for value in re.split(r"[,\s]+", raw.strip()) if value]


def resolve_citation_url(*candidates: Optional[str]) -> Optional[str]:
    for candidate in candidates:
        value = normalize_text(candidate)
        if value and PLACEHOLDER_URL_MARKER not in value.upper():
            return value
    return None


def is_lemon_knowledge_xml(root: ET.Element) -> bool:
    if normalize_tag(root.tag) != LEMON_KNOWLEDGE_ROOT_TAG:
        return False
    return get_direct_child(root, "units") is not None


def load_xml_root(file: File) -> ET.Element:
    file.content.seek(0)
    raw_content = file.content.read()
    file.content.seek(0)
    if isinstance(raw_content, str):
        raw_content = raw_content.encode("utf-8")
    return ET.fromstring(raw_content)


def prepare_lemon_xml_dataset(
    root: ET.Element,
    *,
    dataset_filename: str,
    category: str,
    max_chunk_tokens: int = DEFAULT_MAX_CHUNK_TOKENS,
) -> LemonXmlPreparedDataset:
    if normalize_tag(root.tag) != LEMON_KNOWLEDGE_ROOT_TAG:
        raise ValueError("Lemon knowledge XML must have a <knowledge> root element")

    units_element = get_direct_child(root, "units")
    if units_element is None:
        raise ValueError("Lemon knowledge XML is missing a <units> element")

    sourcefile = os.path.basename(dataset_filename)
    dataset_slug = sanitize_identifier(Path(sourcefile).stem)
    meta_element = get_direct_child(root, "meta")
    course_default = get_direct_child_text(meta_element, "course") if meta_element is not None else ""

    prepared_documents: list[LemonXmlPreparedDocument] = []
    seen_chunk_ids: set[str] = set()

    for unit in iter_child_elements(units_element):
        if normalize_tag(unit.tag) != "unit":
            continue

        unit_id = normalize_text(unit.attrib.get("id")) or "unit"
        module = normalize_text(unit.attrib.get("module"))
        unit_title = get_direct_child_text(unit, "title")
        unit_course = get_direct_child_text(unit, "course") or course_default
        unit_url_attr = unit.attrib.get("unit_url")

        chunks_element = get_direct_child(unit, "chunks")
        if chunks_element is None:
            continue

        for chunk in iter_child_elements(chunks_element):
            if normalize_tag(chunk.tag) != "chunk":
                continue

            chunk_id = normalize_text(chunk.attrib.get("id"))
            if not chunk_id:
                raise ValueError(f"Lemon knowledge chunk in unit '{unit_id}' is missing an id attribute")
            if chunk_id in seen_chunk_ids:
                raise ValueError(f"Lemon knowledge XML contains duplicate chunk id '{chunk_id}'")
            seen_chunk_ids.add(chunk_id)

            section_title = get_direct_child_text(chunk, "section_title")
            content_element = get_direct_child(chunk, "content")
            body = normalize_text("".join(content_element.itertext())) if content_element is not None else ""
            if not body:
                raise ValueError(f"Lemon knowledge chunk '{chunk_id}' has empty <content>")

            title = TITLE_SEPARATOR.join(part for part in [unit_title, section_title] if part) or f"Chunk {chunk_id}"
            heading = f"## {section_title}\n\n" if section_title else ""
            full_content = f"{heading}{body}"
            url = resolve_citation_url(chunk.attrib.get("unit_url"), unit_url_attr)
            tags = dedupe_preserve_order(
                [value for value in [*split_tag_values(chunk.attrib.get("tags")), module, unit_course] if value]
            )

            for sub_index, chunk_text in enumerate(split_content_exact(full_content, max_chunk_tokens=max_chunk_tokens), start=1):
                prepared_documents.append(
                    LemonXmlPreparedDocument(
                        id=f"{dataset_slug}-{sanitize_identifier(unit_id)}-{sanitize_identifier(chunk_id)}-{sub_index:03d}",
                        content=chunk_text,
                        category=category,
                        sourcepage=chunk_id,
                        sourcefile=sourcefile,
                        title=title,
                        url=url,
                        tags=tags,
                    )
                )

    if not prepared_documents:
        raise ValueError("Lemon knowledge XML must contain at least one chunk with content")

    return LemonXmlPreparedDataset(documents=prepared_documents)


def prepared_document_to_section(document: LemonXmlPreparedDocument, file: File, page_num: int) -> Section:
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


def prepare_lemon_xml_sections(
    root: ET.Element,
    *,
    file: File,
    category: str,
    max_chunk_tokens: int = DEFAULT_MAX_CHUNK_TOKENS,
) -> list[Section]:
    dataset = prepare_lemon_xml_dataset(
        root,
        dataset_filename=file.filename(),
        category=category,
        max_chunk_tokens=max_chunk_tokens,
    )
    return [
        prepared_document_to_section(document, file, page_num=index) for index, document in enumerate(dataset.documents)
    ]


async def build_lemon_xml_sections_if_applicable(
    *,
    file: File,
    category: Optional[str],
    check_cancel: Optional[Callable[[], Awaitable[None]]] = None,
) -> Optional[list[Section]]:
    if (category or "").strip().lower() != LEMON_CATEGORY or file.file_extension().lower() != ".xml":
        return None

    if check_cancel is not None:
        await check_cancel()

    try:
        root = load_xml_root(file)
    except ET.ParseError:
        return None
    if not is_lemon_knowledge_xml(root):
        return None

    logger.info("Using lemon knowledge XML parser for '%s'", file.filename())
    sections = prepare_lemon_xml_sections(root, file=file, category=LEMON_CATEGORY)

    if check_cancel is not None:
        await check_cancel()

    return sections
