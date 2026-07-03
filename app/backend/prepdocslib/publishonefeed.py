import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Optional

from .fileprocessor import FileProcessor
from .listfilestrategy import File
from .page import Page
from .searchmanager import Section
from .textprocessor import process_text
from .xmlparser import cleanup_xml_text, normalize_tag

logger = logging.getLogger("scripts")

PUBLISHONE_DOCUMENT_URL_TEMPLATE = "https://amsterdam.publishone.nl/document/{document_id}/content"
HEADING_LEVELS = {f"h{level}": level for level in range(1, 7)}
INLINE_BREAK_TAGS = {"br"}
SKIPPED_CONTENT_TAGS = {"naam", "lastmodified", "meta"}
BLOCK_RENDER_TAGS = {"document", "section", "meta", "p", "list", "li", *HEADING_LEVELS.keys()}
DIRECT_VALUE_SKIP_TAGS = {"naam", "lastmodified", "meta", "document"}


@dataclass(frozen=True)
class FolderContext:
    name: Optional[str]
    id: Optional[str]
    document_type: Optional[str] = None
    document_type_key: Optional[str] = None
    meta_fields: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class FeedDocument:
    document_id: str
    title: str
    url: str
    tags: list[str]
    content: str


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


def sanitize_identifier(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]+", "-", value).strip("-") or "document"


def format_field_label(value: str) -> str:
    normalized_value = normalize_tag(value).replace("-", " ").replace("_", " ").strip()
    return " ".join(part.capitalize() for part in normalized_value.split()) or "Field"


def collect_meta_fields(meta_element: Optional[ET.Element]) -> list[tuple[str, str]]:
    if meta_element is None:
        return []

    values: list[tuple[str, str]] = []
    for child in iter_child_elements(meta_element):
        key = normalize_tag(child.tag)
        value = normalize_text("".join(child.itertext()))
        if value:
            values.append((key, value))
        for attribute_name, attribute_value in child.attrib.items():
            normalized_attribute_value = normalize_text(attribute_value)
            if normalized_attribute_value:
                values.append((f"{key}-{normalize_tag(attribute_name)}", normalized_attribute_value))
    return values


def collect_logical_documents(root: ET.Element) -> list[tuple[ET.Element, list[FolderContext]]]:
    logical_documents: list[tuple[ET.Element, list[FolderContext]]] = []

    def visit(element: ET.Element, folder_path: list[FolderContext]) -> None:
        tag = normalize_tag(element.tag)

        if tag == "folder":
            current_folder = FolderContext(
                name=get_direct_child_text(element, "naam") or None,
                id=normalize_text(element.attrib.get("id")) or None,
                document_type=normalize_text(element.attrib.get("documentTypeName")) or None,
                document_type_key=normalize_text(element.attrib.get("document-type-key")) or None,
                meta_fields=tuple(collect_meta_fields(get_direct_child(element, "meta"))),
            )
            next_folder_path = folder_path + [current_folder]
            for child in iter_child_elements(element):
                visit(child, next_folder_path)
            return

        if tag == "document" and normalize_text(element.attrib.get("id")):
            logical_documents.append((element, folder_path))
            return

        for child in iter_child_elements(element):
            visit(child, folder_path)

    visit(root, [])
    return logical_documents


def join_inline_fragments(fragments: list[str]) -> str:
    result = ""
    for fragment in fragments:
        if not fragment:
            continue
        if fragment == "\n":
            result = result.rstrip() + "\n"
            continue
        if not result or result.endswith((" ", "\n", "(", "/", "-")):
            result += fragment
            continue
        if fragment.startswith((".", ",", ":", ";", "?", "!", ")", "%", "/")):
            result += fragment
            continue
        result += f" {fragment}"
    return cleanup_xml_text(result)


def extract_inline_text(element: ET.Element) -> str:
    tag = normalize_tag(element.tag)
    if tag == "img":
        return describe_image_element(element)

    fragments: list[str] = []
    text = normalize_text(element.text)
    if text:
        fragments.append(text)

    for child in iter_child_elements(element):
        tag = normalize_tag(child.tag)
        if tag in INLINE_BREAK_TAGS:
            fragments.append("\n")
        else:
            child_text = extract_inline_text(child)
            if child_text:
                fragments.append(child_text)
        tail = normalize_text(child.tail)
        if tail:
            fragments.append(tail)

    joined_text = join_inline_fragments(fragments)
    if tag == "a":
        href = normalize_text(element.attrib.get("href") or element.attrib.get("url"))
        if href:
            if joined_text and joined_text != href:
                return f"{joined_text} ({href})"
            return href
    return joined_text


def describe_image_element(element: ET.Element) -> str:
    href = normalize_text(element.attrib.get("href") or element.attrib.get("src"))
    image_id = normalize_text(element.attrib.get("id"))
    width = normalize_text(element.attrib.get("width"))
    height = normalize_text(element.attrib.get("height"))

    primary_value = href or image_id or "embedded image"
    details: list[str] = []
    if image_id and image_id != primary_value:
        details.append(f"id: {image_id}")
    if width:
        details.append(f"width: {width}")
    if height:
        details.append(f"height: {height}")

    image_text = f"Image: {primary_value}"
    if details:
        image_text += f" ({', '.join(details)})"
    return image_text


def render_lines_from_text(text: str, *, prefix: str = "") -> list[str]:
    if not text:
        return []
    return [f"{prefix}{line}".rstrip() for line in text.splitlines() if line.strip()]


def render_meta_lines(element: ET.Element) -> list[str]:
    return [f"{key}: {value}" for key, value in collect_meta_fields(element)]


def render_document_body_lines(element: ET.Element, indent: int = 0) -> list[str]:
    lines: list[str] = []
    for child in iter_child_elements(element):
        tag = normalize_tag(child.tag)
        if tag in SKIPPED_CONTENT_TAGS:
            continue
        lines.extend(render_element_lines(child, indent))
    return lines


def render_list_item_lines(element: ET.Element, indent: int = 0) -> list[str]:
    prefix = " " * indent
    nested_lists = [child for child in iter_child_elements(element) if normalize_tag(child.tag) == "list"]
    inline_fragments: list[str] = []

    if normalize_text(element.text):
        inline_fragments.append(normalize_text(element.text))

    for child in iter_child_elements(element):
        tag = normalize_tag(child.tag)
        if tag == "list":
            continue
        child_text = extract_inline_text(child)
        if child_text:
            inline_fragments.append(child_text)
        tail = normalize_text(child.tail)
        if tail:
            inline_fragments.append(tail)

    item_text = join_inline_fragments(inline_fragments)
    lines = render_lines_from_text(item_text, prefix=f"{prefix}- ")

    for nested_list in nested_lists:
        lines.extend(render_element_lines(nested_list, indent + 2))
        tail = normalize_text(nested_list.tail)
        if tail:
            lines.extend(render_lines_from_text(tail, prefix=prefix))

    return lines


def render_element_lines(element: ET.Element, indent: int = 0) -> list[str]:
    tag = normalize_tag(element.tag)
    prefix = " " * indent

    if tag in {"document", "section"}:
        return render_document_body_lines(element, indent)

    if tag == "meta":
        return [f"{prefix}{line}" for line in render_meta_lines(element)]

    if tag in HEADING_LEVELS:
        heading_text = extract_inline_text(element)
        if not heading_text:
            return []
        marker = "#" * HEADING_LEVELS[tag]
        return [f"{prefix}{marker} {heading_text}"]

    if tag == "p":
        return render_lines_from_text(extract_inline_text(element), prefix=prefix)

    if tag == "list":
        lines: list[str] = []
        for child in iter_child_elements(element):
            child_tag = normalize_tag(child.tag)
            if child_tag == "li":
                lines.extend(render_list_item_lines(child, indent))
            else:
                lines.extend(render_element_lines(child, indent))
        return lines

    if tag == "li":
        return render_list_item_lines(element, indent)

    child_elements = iter_child_elements(element)
    if not child_elements:
        text = extract_inline_text(element)
        if not text:
            return []
        return render_lines_from_text(text, prefix=prefix)

    lines: list[str] = []
    has_block_children = any(normalize_tag(child.tag) in BLOCK_RENDER_TAGS for child in child_elements)
    inline_text = extract_inline_text(element)
    if inline_text and tag not in {"bold", "italic"} and not has_block_children:
        lines.extend(render_lines_from_text(inline_text, prefix=prefix))
    for child in child_elements:
        lines.extend(render_element_lines(child, indent))
    return lines


def collect_unique_descendant_attribute_values(element: ET.Element, tag_name: str, attribute_name: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for candidate in element.iter():
        if not isinstance(candidate.tag, str) or normalize_tag(candidate.tag) != tag_name:
            continue
        value = normalize_text(candidate.attrib.get(attribute_name))
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return values


def collect_direct_value_fields(element: ET.Element) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for child in iter_child_elements(element):
        key = normalize_tag(child.tag)
        if key in DIRECT_VALUE_SKIP_TAGS:
            continue
        if iter_child_elements(child):
            continue
        value = normalize_text("".join(child.itertext()))
        if value:
            values.append((key, value))
    return values


def collect_direct_meta_fields(element: ET.Element) -> list[tuple[str, str]]:
    return collect_meta_fields(get_direct_child(element, "meta"))


def append_tag(
    tags: list[str], seen: set[str], value: Optional[str], label: Optional[str] = None, *, include_raw: bool = True
) -> None:
    normalized_value = normalize_text(value)
    if not normalized_value:
        return
    raw_tag = normalized_value
    if include_raw and raw_tag not in seen:
        tags.append(raw_tag)
        seen.add(raw_tag)
    if label:
        labeled_tag = f"{label}:{normalized_value}"
        if labeled_tag not in seen:
            tags.append(labeled_tag)
            seen.add(labeled_tag)


def build_tags(element: ET.Element, folder_path: list[FolderContext]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()

    append_tag(tags, seen, element.attrib.get("documentTypeName"), "document-type")
    append_tag(tags, seen, element.attrib.get("document-type-key"), "document-type-key")
    append_tag(tags, seen, element.attrib.get("state"), "state")
    append_tag(tags, seen, element.attrib.get("state-id"), "state-id")
    append_tag(tags, seen, element.attrib.get("final"), "final")
    append_tag(tags, seen, get_direct_child_text(element, "lastmodified"), "lastmodified")

    for version in collect_unique_descendant_attribute_values(element, "document", "version"):
        append_tag(tags, seen, version, "version")
    for orientation in collect_unique_descendant_attribute_values(element, "section", "orientation"):
        append_tag(tags, seen, orientation, "orientation")

    for field_name, field_value in collect_direct_value_fields(element):
        append_tag(tags, seen, field_value, field_name)

    for field_name, field_value in collect_direct_meta_fields(element):
        append_tag(tags, seen, field_value, f"meta-{field_name}")

    for folder in folder_path:
        append_tag(tags, seen, folder.name, "folder")
        append_tag(tags, seen, folder.id, "folder-id")
        append_tag(tags, seen, folder.document_type, "folder-document-type")
        append_tag(tags, seen, folder.document_type_key, "folder-document-type-key")
        for field_name, field_value in folder.meta_fields:
            append_tag(tags, seen, field_value, f"folder-meta-{field_name}")

    folder_names = [folder.name for folder in folder_path if folder.name]
    if folder_names:
        append_tag(tags, seen, " > ".join(folder_names), "folder-path", include_raw=False)

    return tags


def build_document_content(element: ET.Element, folder_path: list[FolderContext], title: str, document_id: str) -> str:
    lines = [
        f"Title: {title}",
        f"Document ID: {document_id}",
    ]

    document_type = normalize_text(element.attrib.get("documentTypeName"))
    if document_type:
        lines.append(f"Document type: {document_type}")

    document_type_key = normalize_text(element.attrib.get("document-type-key"))
    if document_type_key:
        lines.append(f"Document type key: {document_type_key}")

    state = normalize_text(element.attrib.get("state"))
    if state:
        lines.append(f"State: {state}")

    state_id = normalize_text(element.attrib.get("state-id"))
    if state_id:
        lines.append(f"State ID: {state_id}")

    final_flag = normalize_text(element.attrib.get("final"))
    if final_flag:
        lines.append(f"Final: {final_flag}")

    last_modified = get_direct_child_text(element, "lastmodified")
    if last_modified:
        lines.append(f"Last modified: {last_modified}")

    known_attribute_names = {"id", "documentTypeName", "document-type-key", "state", "state-id", "final"}
    for attribute_name, attribute_value in element.attrib.items():
        if attribute_name in known_attribute_names:
            continue
        normalized_attribute_value = normalize_text(attribute_value)
        if normalized_attribute_value:
            lines.append(f"{format_field_label(attribute_name)}: {normalized_attribute_value}")

    for field_name, field_value in collect_direct_value_fields(element):
        lines.append(f"{format_field_label(field_name)}: {field_value}")

    folder_names = [folder.name for folder in folder_path if folder.name]
    if folder_names:
        lines.append(f"Folder path: {' > '.join(folder_names)}")
    folder_context_lines = build_folder_context_lines(folder_path)
    if folder_context_lines:
        lines.append("Folder metadata:")
        lines.extend(f"- {line}" for line in folder_context_lines)

    versions = collect_unique_descendant_attribute_values(element, "document", "version")
    if versions:
        lines.append(f"Versions: {', '.join(versions)}")

    orientations = collect_unique_descendant_attribute_values(element, "section", "orientation")
    if orientations:
        lines.append(f"Section orientations: {', '.join(orientations)}")

    meta_lines = render_meta_lines(meta_element) if (meta_element := get_direct_child(element, "meta")) is not None else []
    if meta_lines:
        lines.append("Metadata:")
        lines.extend(f"- {line}" for line in meta_lines)

    body_lines = render_document_body_lines(element)
    if body_lines:
        lines.append("")
        lines.append("Content:")
        lines.extend(body_lines)
    else:
        fallback_text = normalize_text(" ".join(element.itertext()))
        if fallback_text:
            lines.append("")
            lines.append("Content:")
            lines.extend(render_lines_from_text(fallback_text))

    return cleanup_xml_text("\n".join(line for line in lines if line is not None))


def build_folder_context_lines(folder_path: list[FolderContext]) -> list[str]:
    lines: list[str] = []
    for folder in folder_path:
        folder_label = folder.name or folder.id or "Folder"
        if folder.id:
            lines.append(f"{folder_label} id: {folder.id}")
        if folder.document_type:
            lines.append(f"{folder_label} document type: {folder.document_type}")
        if folder.document_type_key:
            lines.append(f"{folder_label} document type key: {folder.document_type_key}")
        for field_name, field_value in folder.meta_fields:
            lines.append(f"{folder_label} {field_name}: {field_value}")
    return lines


def build_feed_document(element: ET.Element, folder_path: list[FolderContext]) -> FeedDocument:
    document_id = normalize_text(element.attrib.get("id"))
    if not document_id:
        raise ValueError("Logical PublishOne document is missing required id attribute")

    title = get_direct_child_text(element, "naam") or f"Document {document_id}"
    url = PUBLISHONE_DOCUMENT_URL_TEMPLATE.format(document_id=document_id)
    tags = build_tags(element, folder_path)
    content = build_document_content(element, folder_path, title, document_id)
    return FeedDocument(document_id=document_id, title=title, url=url, tags=tags, content=content)


async def build_publishone_feed_sections(
    *,
    file: File,
    file_processors: dict[str, FileProcessor],
    category: Optional[str] = None,
) -> list[Section]:
    processor = file_processors.get(file.file_extension().lower())
    if processor is None:
        logger.info("Skipping '%s', no processor found for PublishOne feed", file.filename())
        return []

    file.content.seek(0)
    root = ET.fromstring(file.content.read())
    logical_documents = collect_logical_documents(root)
    if not logical_documents:
        logger.info("No logical PublishOne documents found in '%s'", file.filename())
        return []

    sections: list[Section] = []
    for element, folder_path in logical_documents:
        feed_document = build_feed_document(element, folder_path)
        pages = [Page(page_num=0, offset=0, text=feed_document.content)]
        document_sections = process_text(pages, file, processor.splitter, category)
        document_id_slug = sanitize_identifier(feed_document.document_id)
        category_prefix = sanitize_identifier(category or "document")
        for chunk_index, section in enumerate(document_sections, start=1):
            section.id = f"{file.filename_to_id()}-{category_prefix}-{document_id_slug}-chunk-{chunk_index:03d}"
            section.sourcepage = feed_document.document_id
            section.sourcefile = file.filename()
            section.title = feed_document.title
            section.url = feed_document.url
            section.tags = feed_document.tags
        sections.extend(document_sections)

    return sections


FEED_CATEGORIES = frozenset({"moodle", "publishone"})


async def build_feed_sections_if_applicable(
    *,
    file: File,
    file_processors: dict[str, FileProcessor],
    category: Optional[str],
    check_cancel: Optional[Callable[[], Awaitable[None]]] = None,
) -> Optional[list[Section]]:
    normalized_category = (category or "").strip().lower()
    if normalized_category not in FEED_CATEGORIES or file.file_extension().lower() != ".xml":
        return None

    if check_cancel is not None:
        await check_cancel()

    logger.info("Using PublishOne feed XML parser for '%s'", file.filename())
    sections = await build_publishone_feed_sections(
        file=file,
        file_processors=file_processors,
        category=normalized_category,
    )

    if check_cancel is not None:
        await check_cancel()

    return sections
