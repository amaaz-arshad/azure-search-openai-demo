import io
import xml.etree.ElementTree as ET

import pytest

from prepdocslib.listfilestrategy import File
from prepdocslib.lemonxml import (
    TITLE_SEPARATOR,
    build_lemon_xml_sections_if_applicable,
    is_lemon_knowledge_xml,
    prepare_lemon_xml_dataset,
)

DATASET_FILENAME = "lemon_demo_knowledge.xml"

# Body lines are flush-left (like the real export); the <content>/<chunk> tags are indented.
KNOWLEDGE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<knowledge version="2.1" client="Lemon Demo" lang="de-DE">
  <meta>
    <course>Lifelong Learning</course>
  </meta>
  <units>
    <unit id="u001" module="Module 1" content_id="90001" unit_url="PLACEHOLDER">
      <title>Introduction to lifelong learning</title>
      <course>Lifelong Learning</course>
      <unit_summary>This summary must not be indexed as content.</unit_summary>
      <chunks>
        <chunk id="c0001" type="freetext" tags="informal-learning" unit_url="PLACEHOLDER">
          <section_title>Chapter 01: What lifelong learning means</section_title>
          <content>
Lifelong learning is the ongoing pursuit of knowledge.

| Form | Structure |
|---|---|
| Formal learning | Highly structured |
          </content>
          <key_facts>
            <fact id="c0001-f01">A fact that must not be indexed as content.</fact>
          </key_facts>
        </chunk>
      </chunks>
    </unit>
  </units>
</knowledge>
"""


def parse_dataset(xml_text: str, *, max_chunk_tokens: int = 650):
    root = ET.fromstring(xml_text.encode("utf-8"))
    return prepare_lemon_xml_dataset(
        root,
        dataset_filename=DATASET_FILENAME,
        category="lemon",
        max_chunk_tokens=max_chunk_tokens,
    )


def build_file(xml_text: str, *, name: str) -> File:
    stream = io.BytesIO(xml_text.encode("utf-8"))
    stream.name = name
    return File(stream)


def test_prepare_lemon_xml_dataset_maps_chunk_fields():
    dataset = parse_dataset(KNOWLEDGE_XML)

    assert len(dataset.documents) == 1
    document = dataset.documents[0]
    assert document.id == "lemon-demo-knowledge-u001-c0001-001"
    assert document.category == "lemon"
    assert document.sourcepage == "c0001"
    assert document.sourcefile == DATASET_FILENAME
    assert document.title == f"Introduction to lifelong learning{TITLE_SEPARATOR}Chapter 01: What lifelong learning means"
    assert document.url is None
    assert document.tags == ["informal-learning", "Module 1", "Lifelong Learning"]


def test_prepare_lemon_xml_dataset_content_keeps_markdown_and_drops_extras():
    document = parse_dataset(KNOWLEDGE_XML).documents[0]

    assert document.content.startswith("## Chapter 01: What lifelong learning means")
    assert "Lifelong learning is the ongoing pursuit of knowledge." in document.content
    # markdown table survives cleanup
    assert "| Form | Structure |" in document.content
    assert "| Formal learning | Highly structured |" in document.content
    # unit_summary and key_facts are not indexed
    assert "must not be indexed" not in document.content


def test_prepare_lemon_xml_dataset_populates_real_unit_url():
    xml_text = KNOWLEDGE_XML.replace(
        '<chunk id="c0001" type="freetext" tags="informal-learning" unit_url="PLACEHOLDER">',
        '<chunk id="c0001" type="freetext" tags="informal-learning" unit_url="https://learn.example.test/u001">',
    )
    document = parse_dataset(xml_text).documents[0]
    assert document.url == "https://learn.example.test/u001"


def test_prepare_lemon_xml_dataset_splits_long_content_without_rewriting_it():
    long_body = "Alpha beta gamma delta epsilon. " * 80
    xml_text = KNOWLEDGE_XML.replace("Lifelong learning is the ongoing pursuit of knowledge.", long_body.strip())

    single = parse_dataset(xml_text, max_chunk_tokens=650).documents
    split = parse_dataset(xml_text, max_chunk_tokens=25).documents

    assert len(single) == 1
    assert len(split) > 1
    assert "".join(document.content for document in split) == single[0].content
    assert split[0].id == "lemon-demo-knowledge-u001-c0001-001"
    assert split[1].id == "lemon-demo-knowledge-u001-c0001-002"


def test_prepare_lemon_xml_dataset_rejects_duplicate_chunk_ids():
    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<knowledge>
  <units>
    <unit id="u001" module="Module 1">
      <title>Unit</title>
      <chunks>
        <chunk id="c0001"><section_title>One</section_title><content>First body.</content></chunk>
        <chunk id="c0001"><section_title>Two</section_title><content>Second body.</content></chunk>
      </chunks>
    </unit>
  </units>
</knowledge>"""
    with pytest.raises(ValueError, match="duplicate chunk id"):
        parse_dataset(xml_text)


def test_prepare_lemon_xml_dataset_rejects_empty_content():
    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<knowledge>
  <units>
    <unit id="u001" module="Module 1">
      <title>Unit</title>
      <chunks>
        <chunk id="c0001"><section_title>One</section_title><content>   </content></chunk>
      </chunks>
    </unit>
  </units>
</knowledge>"""
    with pytest.raises(ValueError, match="empty <content>"):
        parse_dataset(xml_text)


def test_is_lemon_knowledge_xml_detects_root_and_units():
    assert is_lemon_knowledge_xml(ET.fromstring(KNOWLEDGE_XML.encode("utf-8")))
    assert not is_lemon_knowledge_xml(ET.fromstring(b"<root><a/></root>"))
    assert not is_lemon_knowledge_xml(ET.fromstring(b"<knowledge><meta/></knowledge>"))


@pytest.mark.asyncio
async def test_build_lemon_xml_sections_if_applicable_returns_sections_for_lemon_xml():
    file = build_file(KNOWLEDGE_XML, name=DATASET_FILENAME)
    try:
        sections = await build_lemon_xml_sections_if_applicable(file=file, category="lemon")
    finally:
        file.close()

    assert sections is not None
    assert len(sections) == 1
    section = sections[0]
    assert section.category == "lemon"
    assert section.sourcepage == "c0001"
    assert section.url is None
    assert section.chunk.text.startswith("## Chapter 01: What lifelong learning means")


@pytest.mark.asyncio
async def test_build_lemon_xml_sections_if_applicable_declines_wrong_category():
    file = build_file(KNOWLEDGE_XML, name=DATASET_FILENAME)
    try:
        assert await build_lemon_xml_sections_if_applicable(file=file, category="fhg") is None
    finally:
        file.close()


@pytest.mark.asyncio
async def test_build_lemon_xml_sections_if_applicable_declines_non_xml_extension():
    file = build_file(KNOWLEDGE_XML, name="lemon_demo_knowledge.json")
    try:
        assert await build_lemon_xml_sections_if_applicable(file=file, category="lemon") is None
    finally:
        file.close()


@pytest.mark.asyncio
async def test_build_lemon_xml_sections_if_applicable_declines_non_knowledge_xml():
    file = build_file("<root><units/></root>", name="something.xml")
    try:
        assert await build_lemon_xml_sections_if_applicable(file=file, category="lemon") is None
    finally:
        file.close()
