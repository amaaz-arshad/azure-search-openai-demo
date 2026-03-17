import re
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import IO

from .page import Page
from .parser import Parser


def cleanup_xml_text(data: str) -> str:
    output = re.sub(r"\n{3,}", "\n\n", data)
    output = re.sub(r"[^\S\n]{2,}", " ", output)
    return output.strip()


def normalize_tag(tag: str) -> str:
    if "}" in tag:
        tag = tag.rsplit("}", 1)[1]
    if ":" in tag:
        tag = tag.rsplit(":", 1)[1]
    return tag


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return cleanup_xml_text(value)


def format_path_label(path: list[str]) -> str:
    if len(path) <= 1:
        return path[-1]
    return ".".join(path[1:])


def iter_element_children(element: ET.Element) -> list[ET.Element]:
    return [child for child in list(element) if isinstance(child.tag, str)]


def format_attributes(element: ET.Element) -> list[str]:
    lines: list[str] = []
    for key, value in element.attrib.items():
        normalized_key = normalize_tag(key)
        cleaned_value = normalize_text(value)
        if cleaned_value:
            lines.append(f"@{normalized_key}: {cleaned_value}")
    return lines


def flatten_element_lines(element: ET.Element, path: list[str], depth: int = 0) -> list[str]:
    lines: list[str] = []
    tag = normalize_tag(element.tag)
    text = normalize_text(element.text)
    attrs = format_attributes(element)
    children = iter_element_children(element)
    current_label = format_path_label(path)

    if depth == 0:
        lines.append(f"XML path: {' > '.join(path)}")
        lines.append(f"Element: {tag}")

    for attr_line in attrs:
        lines.append(f"{current_label} {attr_line}" if depth > 0 else attr_line)

    if text:
        if children or attrs:
            label = "summary" if depth == 0 else f"{current_label} text"
            lines.append(f"{label}: {text}")
        else:
            lines.append(f"{current_label}: {text}")

    for child in children:
        child_tag = normalize_tag(child.tag)
        child_path = path + [child_tag]
        child_label = format_path_label(child_path)
        child_children = iter_element_children(child)
        child_text = normalize_text(child.text)
        child_attrs = format_attributes(child)
        if not child_children and not child_attrs and child_text:
            lines.append(f"{child_label}: {child_text}")
            continue

        lines.extend(flatten_element_lines(child, child_path, depth + 1))

    return lines


def summarize_context_child(child: ET.Element) -> list[str]:
    child_tag = normalize_tag(child.tag)
    child_text = normalize_text(child.text)
    child_children = iter_element_children(child)
    child_attrs = format_attributes(child)

    if not child_children and not child_attrs and child_text:
        return [f"context {child_tag}: {child_text}"]

    flattened = flatten_element_lines(child, [child_tag])
    summarized = "\n".join(flattened)
    if len(summarized) > 400:
        return []
    return [f"context {line}" for line in flattened]


def build_parent_context_lines(element: ET.Element, excluded_tags: set[str]) -> list[str]:
    lines: list[str] = []
    tag = normalize_tag(element.tag)
    text = normalize_text(element.text)
    if text:
        lines.append(f"context {tag}: {text}")

    for attr_line in format_attributes(element):
        lines.append(f"context {tag} {attr_line}")

    children = iter_element_children(element)
    counts = Counter(normalize_tag(child.tag) for child in children)
    for child in children:
        child_tag = normalize_tag(child.tag)
        if child_tag in excluded_tags or counts[child_tag] > 1:
            continue
        lines.extend(summarize_context_child(child))
    return lines


@dataclass
class XmlSection:
    element: ET.Element
    path: list[str]
    context_lines: list[str]


def collect_sections(element: ET.Element, path: list[str], context_lines: list[str]) -> tuple[bool, list[XmlSection]]:
    children = iter_element_children(element)
    if not children:
        return False, [XmlSection(element=element, path=path, context_lines=context_lines)]

    tag_counts = Counter(normalize_tag(child.tag) for child in children)
    repeated_tags = {tag for tag, count in tag_counts.items() if count > 1}

    if repeated_tags:
        parent_context = context_lines + build_parent_context_lines(element, repeated_tags)
        sections: list[XmlSection] = []
        for child in children:
            child_tag = normalize_tag(child.tag)
            if child_tag not in repeated_tags:
                continue
            child_path = path + [child_tag]
            found_nested_split, child_sections = collect_sections(child, child_path, parent_context)
            if found_nested_split:
                sections.extend(child_sections)
            else:
                sections.append(XmlSection(element=child, path=child_path, context_lines=parent_context))
        return True, sections

    descendant_sections: list[XmlSection] = []
    found_descendant_split = False
    for child in children:
        child_tag = normalize_tag(child.tag)
        child_path = path + [child_tag]
        child_context = context_lines + build_parent_context_lines(element, {child_tag})
        found_child_split, child_sections = collect_sections(child, child_path, child_context)
        if found_child_split:
            found_descendant_split = True
            descendant_sections.extend(child_sections)

    if found_descendant_split:
        return True, descendant_sections

    return False, [XmlSection(element=element, path=path, context_lines=context_lines)]


class XmlParser(Parser):
    """
    Parses XML into retrieval-friendly sections by preserving hierarchy and splitting repeated sibling records.

    This keeps collections like <product> or <item> entries isolated while carrying forward document-level context.
    """

    async def parse(self, content: IO) -> AsyncGenerator[Page, None]:
        raw_data = content.read()
        root = ET.fromstring(raw_data)
        root_tag = normalize_tag(root.tag)
        _, sections = collect_sections(root, [root_tag], [])

        offset = 0
        for page_num, section in enumerate(sections):
            section_lines = section.context_lines + flatten_element_lines(section.element, section.path)
            page_text = cleanup_xml_text("\n".join(line for line in section_lines if line))
            if not page_text:
                continue
            yield Page(page_num, offset, page_text)
            offset += len(page_text) + 1
