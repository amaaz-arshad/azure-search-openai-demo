import io

import pytest

from prepdocslib.fileprocessor import FileProcessor
from prepdocslib.listfilestrategy import File
from prepdocslib.publishonefeed import build_publishone_feed_sections
from prepdocslib.textsplitter import SentenceTextSplitter


async def build_sections(xml_text: str, *, category: str) -> list:
    xml_bytes = xml_text.encode("utf-8")
    stream = io.BytesIO(xml_bytes)
    stream.name = "feed.xml"
    file = File(stream)
    try:
        return await build_publishone_feed_sections(
            file=file,
            file_processors={".xml": FileProcessor(parser=None, splitter=SentenceTextSplitter())},
            category=category,
        )
    finally:
        file.close()


@pytest.mark.asyncio
async def test_build_publishone_feed_sections_maps_logical_document_metadata() -> None:
    xml_text = """<?xml version="1.0" encoding="utf-8"?>
<folder id="8775" documentTypeName="Mobile Learning" document-type-key="desnapmobilelearning">
  <naam>Testkurs</naam>
  <folder id="8785" documentTypeName="Mobile Learning" document-type-key="desnapmobilelearning">
    <naam>Erste Hilfe</naam>
    <document id="8786" documentTypeName="Mobile Learning" document-type-key="desnapmobilelearning" state-id="35" state="New" final="false">
      <naam>erste_hilfe_elearning</naam>
      <lastmodified>2026-03-25T14:05:59.9814172Z</lastmodified>
      <document version="1">
        <section orientation="portrait">
          <h1>1. Einfuehrung in die Erste Hilfe</h1>
          <p>Erste Hilfe umfasst alle Massnahmen im Notfall.</p>
          <list type="bullet">
            <li><p>Leben retten</p></li>
            <li><p>Verschlimmerung verhindern</p></li>
          </list>
        </section>
      </document>
    </document>
  </folder>
</folder>
"""

    sections = await build_sections(xml_text, category="moodle")

    assert len(sections) == 1
    section = sections[0]
    assert section.sourcepage == "8786"
    assert section.sourcefile == "feed.xml"
    assert section.title == "erste_hilfe_elearning"
    assert section.url == "https://snap.publishone.nl/document/8786/content"
    assert section.id.endswith("-moodle-8786-chunk-001")
    assert section.tags is not None
    assert "Mobile Learning" in section.tags
    assert "document-type:Mobile Learning" in section.tags
    assert "desnapmobilelearning" in section.tags
    assert "state:New" in section.tags
    assert "version:1" in section.tags
    assert "orientation:portrait" in section.tags
    assert "folder:Testkurs" in section.tags
    assert "folder:Erste Hilfe" in section.tags
    assert "Title: erste_hilfe_elearning" in section.chunk.text
    assert "Document ID: 8786" in section.chunk.text
    assert "Folder path: Testkurs > Erste Hilfe" in section.chunk.text
    assert "# 1. Einfuehrung in die Erste Hilfe" in section.chunk.text
    assert "- Leben retten" in section.chunk.text


@pytest.mark.asyncio
async def test_build_publishone_feed_sections_handles_multiple_outer_documents() -> None:
    xml_text = """<?xml version="1.0" encoding="utf-8"?>
<folder id="6440" documentTypeName="PublishOne" document-type-key="publishone">
  <naam>PublishOne</naam>
  <document id="6446" documentTypeName="PublishOne" document-type-key="publishone" state-id="105" state="New" final="false">
    <naam>Liste</naam>
    <lastmodified>2023-04-13T13:38:50.3653236Z</lastmodified>
    <document version="1">
      <section orientation="portrait">
        <p>Hallo</p>
      </section>
    </document>
  </document>
  <document id="6447" documentTypeName="PublishOne" document-type-key="publishone" state-id="105" state="Published" final="true">
    <naam>Zweite Liste</naam>
    <lastmodified>2023-04-14T13:38:50.3653236Z</lastmodified>
    <document version="2">
      <section orientation="landscape">
        <p>Mehr Inhalt</p>
      </section>
    </document>
  </document>
</folder>
"""

    sections = await build_sections(xml_text, category="publishone")

    assert len(sections) == 2
    assert {section.sourcepage for section in sections} == {"6446", "6447"}
    assert {section.title for section in sections} == {"Liste", "Zweite Liste"}
    assert {section.url for section in sections} == {
        "https://snap.publishone.nl/document/6446/content",
        "https://snap.publishone.nl/document/6447/content",
    }
