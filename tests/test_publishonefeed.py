import io
import re

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
    assert section.url == "https://amsterdam.publishone.nl/document/8786/content"
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
        "https://amsterdam.publishone.nl/document/6446/content",
        "https://amsterdam.publishone.nl/document/6447/content",
    }


@pytest.mark.asyncio
async def test_build_publishone_feed_sections_preserves_direct_metadata_without_duplication() -> None:
    xml_text = """<?xml version="1.0" encoding="utf-8"?>
<folder id="9000" documentTypeName="Guide" document-type-key="guide">
  <naam>Handbook</naam>
  <document
      id="9001"
      documentTypeName="Guide"
      document-type-key="guide"
      state-id="7"
      state="Draft"
      final="false"
      custom-attr="custom-value">
    <naam>Safety handbook</naam>
    <lastmodified>2026-03-27T12:00:00Z</lastmodified>
    <language>de</language>
    <meta>
      <audience>students</audience>
      <owner system="moodle">training-team</owner>
    </meta>
    <document version="3">
      <section orientation="portrait">
        <h1>Intro</h1>
        <p>Always follow the process.</p>
      </section>
    </document>
  </document>
</folder>
"""

    sections = await build_sections(xml_text, category="publishone")

    assert len(sections) == 1
    section = sections[0]
    assert section.sourcepage == "9001"
    assert section.title == "Safety handbook"
    assert section.url == "https://amsterdam.publishone.nl/document/9001/content"
    assert section.tags is not None
    assert "meta-audience:students" in section.tags
    assert "meta-owner-system:moodle" in section.tags
    assert "language:de" in section.tags
    assert "folder-path:Handbook" in section.tags
    assert "Custom Attr: custom-value" in section.chunk.text
    assert "Language: de" in section.chunk.text
    assert "Metadata:" in section.chunk.text
    assert section.chunk.text.count("audience: students") == 1
    assert section.chunk.text.count("owner: training-team") == 1
    assert section.chunk.text.count("owner-system: moodle") == 1
    assert "# Intro" in section.chunk.text


@pytest.mark.asyncio
async def test_build_publishone_feed_sections_preserves_folder_metadata_and_inline_targets() -> None:
    xml_text = """<?xml version="1.0" encoding="utf-8"?>
<folder id="6" documentTypeName="Standard" document-type-key="1_Default">
  <naam>PublishOne Product</naam>
  <meta>
    <template-design key="product">Product Documentation</template-design>
  </meta>
  <folder id="217" documentTypeName="Standard" document-type-key="1_Default">
    <naam>Technical Documentation</naam>
    <meta>
      <guidesummary>The PublishOne Technical Architecture</guidesummary>
      <template-design key="product">Product Documentation</template-design>
    </meta>
    <document id="8779" documentTypeName="Standard" document-type-key="1_Default" state-id="2" state="Review">
      <naam>PublishOne Technical Architecture</naam>
      <lastmodified>2023-04-14T11:40:00.2205125Z</lastmodified>
      <meta>
        <bi_category key="product">Product</bi_category>
      </meta>
      <document version="1">
        <section orientation="portrait">
          <p><img id="Picture 1" href="https://amsterdam-em.publishone.nl/api/content/5499" width="450" height="189" /></p>
          <p>Read more at <a href="https://swagger.io/resources/open-api/">Open API docs</a>.</p>
        </section>
      </document>
    </document>
  </folder>
</folder>
"""

    sections = await build_sections(xml_text, category="publishone")

    assert len(sections) == 1
    section = sections[0]
    assert section.tags is not None
    assert "folder-meta-guidesummary:The PublishOne Technical Architecture" in section.tags
    assert "folder-meta-template-design-key:product" in section.tags
    assert "folder-document-type:Standard" in section.tags
    assert "folder-path:PublishOne Product > Technical Documentation" in section.tags
    assert "Technical Documentation guidesummary: The PublishOne Technical Architecture" in section.chunk.text
    assert "Technical Documentation template-design-key: product" in section.chunk.text
    assert "Image: https://amsterdam-em.publishone.nl/api/content/5499 (id: Picture 1, width: 450, height: 189)" in section.chunk.text
    assert "Open API docs (https://swagger.io/resources/open-api/)." in section.chunk.text


# --- publishone2 archive image support -------------------------------------------------------

PACKAGE_XML = """<?xml version="1.0" encoding="utf-8"?>
<folder id="8796">
  <naam>Speiseplan</naam>
  <meta />
  <document id="8799" documentTypeName="PublishOne" document-type-key="publishone">
    <naam>Der Speiseplan für die KW 31</naam>
    <meta />
    <document version="1">
      <p>Der Speiseplan für die KW 31</p>
      <p><img id="Grafik 1" href="https://snap-em.publishone.nl/api/content/8798" po-ref-id="8798">
        <asset id="8798" parent-id="8797"><title>Speiseplan-image1</title>
          <meta><reference /><type /></meta>
          <manifest id="1693" media-type="image/jpeg" width="1386" height="981" />
        </asset>
      </img></p>
    </document>
  </document>
</folder>
"""


def build_bundle(description: str = "| Montag | Lasagne |", key: str = "8798"):
    from prepdocslib.feedarchive import FeedImageAsset, build_image_bundle

    return build_image_bundle(
        [FeedImageAsset(key=key, filename=f"{key}.jpg", data=b"jpeg")],
        {key: description} if description else {},
        target_prefix="publishone2",
        package_name="nerilio2",
    )


async def build_sections_with_bundle(xml_text: str, *, category: str, image_bundle) -> list:
    xml_bytes = xml_text.encode("utf-8")
    stream = io.BytesIO(xml_bytes)
    stream.name = "Speiseplan.xml"
    file = File(stream)
    try:
        return await build_publishone_feed_sections(
            file=file,
            file_processors={".xml": FileProcessor(parser=None, splitter=SentenceTextSplitter())},
            category=category,
            image_bundle=image_bundle,
        )
    finally:
        file.close()


@pytest.mark.asyncio
async def test_archive_image_renders_markdown_and_transcription() -> None:
    sections = await build_sections_with_bundle(
        PACKAGE_XML, category="publishone2", image_bundle=build_bundle()
    )

    text = "\n".join(section.chunk.text for section in sections)
    assert "Image: Speiseplan-image1" in text
    assert "![Speiseplan-image1](/content/publishone2/nerilio2/images/8798.jpg)" in text
    # The transcription is what makes an image-only document retrievable at all.
    assert "Image content:" in text
    assert "| Montag | Lasagne |" in text
    # The bare external URL line is replaced, not appended.
    assert "Image: https://snap-em.publishone.nl/api/content/8798" not in text


@pytest.mark.asyncio
async def test_archive_image_without_a_description_is_still_displayable() -> None:
    sections = await build_sections_with_bundle(
        PACKAGE_XML, category="publishone2", image_bundle=build_bundle(description="")
    )

    text = "\n".join(section.chunk.text for section in sections)
    assert "![Speiseplan-image1](/content/publishone2/nerilio2/images/8798.jpg)" in text
    assert "Image content:" not in text


@pytest.mark.asyncio
async def test_unresolved_image_falls_back_to_the_legacy_url_line() -> None:
    # An image the archive does not contain must render exactly as it does for publishone/moodle.
    sections = await build_sections_with_bundle(
        PACKAGE_XML, category="publishone2", image_bundle=build_bundle(key="9999")
    )

    text = "\n".join(section.chunk.text for section in sections)
    assert "Image: https://snap-em.publishone.nl/api/content/8798 (id: Grafik 1)" in text
    assert "![" not in text


@pytest.mark.asyncio
async def test_publishone_output_is_unchanged_when_no_bundle_is_supplied() -> None:
    # The regression guard for publishone/moodle: the shared parser must behave identically for
    # every feed that ships no image bytes.
    with_bundle_arg = await build_sections_with_bundle(PACKAGE_XML, category="publishone", image_bundle=None)
    without_bundle_arg = await build_sections(PACKAGE_XML, category="publishone")

    assert [section.chunk.text for section in with_bundle_arg] == [
        section.chunk.text for section in without_bundle_arg
    ]
    assert "Image: https://snap-em.publishone.nl/api/content/8798 (id: Grafik 1)" in without_bundle_arg[0].chunk.text


@pytest.mark.asyncio
async def test_every_chunk_of_a_split_document_keeps_the_image_reference() -> None:
    # A long transcription splits across chunks; without the trailer only the first chunk could
    # ever display the image the answer came from.
    long_description = "\n".join(f"| Tag {index} | Gericht {index} | Suppe {index} |" for index in range(400))
    sections = await build_sections_with_bundle(
        PACKAGE_XML, category="publishone2", image_bundle=build_bundle(description=long_description)
    )

    assert len(sections) > 1
    for section in sections:
        assert "![Speiseplan-image1](/content/publishone2/nerilio2/images/8798.jpg)" in section.chunk.text


@pytest.mark.asyncio
async def test_the_image_reference_is_not_duplicated_in_a_chunk_that_already_has_it() -> None:
    sections = await build_sections_with_bundle(
        PACKAGE_XML, category="publishone2", image_bundle=build_bundle()
    )

    assert sections[0].chunk.text.count("](/content/publishone2/nerilio2/images/8798.jpg)") == 1


@pytest.mark.asyncio
async def test_the_bundle_does_not_leak_into_a_later_document() -> None:
    from prepdocslib.publishonefeed import active_image_bundle

    await build_sections_with_bundle(PACKAGE_XML, category="publishone2", image_bundle=build_bundle())

    assert active_image_bundle.get() is None
    leftover = await build_sections(PACKAGE_XML, category="publishone")
    assert "![" not in leftover[0].chunk.text


def test_strip_truncated_image_links_removes_only_the_cut_opener() -> None:
    from prepdocslib.publishonefeed import strip_truncated_image_links

    # What a split mid-link actually produces: the closing "png)" ended up in the next chunk.
    cut = "Some text.\n![Picture 3](/content/publishone2/pkg/images/15802."
    assert strip_truncated_image_links(cut) == "Some text."

    # A complete link on the same line is untouched, including one followed by trailing prose.
    intact = "![Picture 3](/content/publishone2/pkg/images/15802.png)"
    assert strip_truncated_image_links(intact) == intact
    assert strip_truncated_image_links(f"{intact} and more") == f"{intact} and more"

    # An alt-only fragment with no link at all is also a cut opener.
    assert strip_truncated_image_links("Text\n![Picture 3]") == "Text"

    # Ordinary prose containing brackets or an exclamation mark is left alone.
    prose = "Great! [see the docs](https://example.test) for details"
    assert strip_truncated_image_links(prose) == prose


@pytest.mark.asyncio
async def test_a_link_cut_by_chunking_never_survives_into_a_chunk() -> None:
    """Markdown does not recognise a half-link as an image, so it would render as literal
    "![alt](/content/..." text in the answer."""
    long_description = "\n".join(f"| Tag {index} | Gericht {index} | Suppe {index} |" for index in range(400))
    sections = await build_sections_with_bundle(
        PACKAGE_XML, category="publishone2", image_bundle=build_bundle(description=long_description)
    )

    for section in sections:
        for line in section.chunk.text.splitlines():
            if "![" in line:
                assert re.search(r"!\[[^\]]*\]\([^)\s]+\)", line), f"truncated image link: {line!r}"
