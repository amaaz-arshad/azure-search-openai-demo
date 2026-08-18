"""Tests for the provisioned ("generic") bot XML dispatch.

The content2 indexer used to parse a structured knowledge export with the generic `XmlParser`, which
flattened the tree into `path: value` lines and let the splitter run over the whole document. This
module re-dispatches a recognised export to the parser that already understands it (`lemonxml`) with
the provisioned bot's own category, and declines anything else so the generic parser still runs.
"""

import asyncio
import io

import pytest

from prepdocslib.dynamicxml import build_dynamic_xml_sections_if_applicable
from prepdocslib.listfilestrategy import File

KNOWLEDGE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<knowledge version="2.1" client="ACME" lang="en-US">
  <meta><course>Mastering Performance</course></meta>
  <units>
    <unit id="u001">
      <title>Reflection in Action</title>
      <course>Mastering Performance</course>
      <chunks>
        <chunk id="c0001">
          <section_title>The Coaching Mindset</section_title>
          <content>Welcome coaches to module one, the coaching mindset.</content>
        </chunk>
        <chunk id="c0002">
          <section_title>Reflecting Afterwards</section_title>
          <content>Reviewing a session afterwards is how practice improves.</content>
        </chunk>
      </chunks>
    </unit>
  </units>
</knowledge>
"""

# Same shape, but with a live unit_url instead of the placeholder the demo export ships.
KNOWLEDGE_XML_WITH_URL = KNOWLEDGE_XML.replace(
    '<unit id="u001">', '<unit id="u001" unit_url="https://lms.example.de/unit/u001">'
)

FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<documents><document id="8786"><naam>Erste Hilfe</naam></document></documents>
"""


def build_file(raw: str, *, filename: str = "hyrox_knowledge_20260722.xml") -> File:
    stream = io.BytesIO(raw.encode("utf-8"))
    stream.name = filename
    return File(content=stream)


def parse(raw: str, *, category: str = "hyroxlemon", filename: str = "hyrox_knowledge_20260722.xml"):
    return asyncio.run(
        build_dynamic_xml_sections_if_applicable(file=build_file(raw, filename=filename), category=category)
    )


def test_a_knowledge_export_becomes_one_section_per_chunk_with_its_own_title():
    sections = parse(KNOWLEDGE_XML)

    assert sections is not None and len(sections) == 2
    assert [section.title for section in sections] == [
        "Reflection in Action — The Coaching Mindset",
        "Reflection in Action — Reflecting Afterwards",
    ]
    assert "Welcome coaches to module one" in sections[0].chunk.text
    assert "Reviewing a session afterwards" in sections[1].chunk.text


def test_the_category_is_the_provisioned_bot_folder_not_lemon():
    # lemonxml's own dispatcher hardcodes category "lemon"; a provisioned bot must keep its own, or
    # its documents would land in the real lemon bot's corpus.
    sections = parse(KNOWLEDGE_XML, category="hyroxlemon")

    assert sections is not None
    assert {section.category for section in sections} == {"hyroxlemon"}


def test_sourcepage_is_the_filename_so_the_citation_resolves():
    # lemonxml sets sourcepage to the chunk id, which is right for the lemon corpus (cited by unit
    # URL) but here would be the citation string itself: /content2/<bot>/c0001 is not a blob.
    sections = parse(KNOWLEDGE_XML, filename="hyrox_knowledge_Level_2_complete_rj_20260722104241.xml")

    assert sections is not None
    assert {section.sourcepage for section in sections} == {"hyrox_knowledge_Level_2_complete_rj_20260722104241.xml"}
    assert {section.sourcefile for section in sections} == {"hyrox_knowledge_Level_2_complete_rj_20260722104241.xml"}


def test_every_chunk_carries_its_unit_and_section_title_in_the_body():
    # With the citation reduced to a filename, the title header is the only thing telling the model
    # (and the reader of Supporting Content) which unit a chunk came from.
    sections = parse(KNOWLEDGE_XML)

    assert sections is not None
    for section in sections:
        assert section.chunk.text.startswith(f"title: {section.title}")


def test_a_live_unit_url_is_preserved_so_the_citation_can_link_out():
    sections = parse(KNOWLEDGE_XML_WITH_URL)

    assert sections is not None
    assert {section.url for section in sections} == {"https://lms.example.de/unit/u001"}


def test_placeholder_unit_urls_stay_unlinked():
    placeholder = KNOWLEDGE_XML.replace('<unit id="u001">', '<unit id="u001" unit_url="PLACEHOLDER">')

    sections = parse(placeholder)

    assert sections is not None
    assert {section.url for section in sections} == {None}


def test_ids_are_unique_and_deterministic():
    first = parse(KNOWLEDGE_XML)
    second = parse(KNOWLEDGE_XML)

    assert first is not None and second is not None
    assert [section.id for section in first] == [section.id for section in second]
    assert len({section.id for section in first}) == len(first)


@pytest.mark.parametrize(
    "raw",
    [
        FEED_XML,
        "<notknowledge><a>1</a></notknowledge>",
        # A <knowledge> root with no <units> is not this shape.
        '<knowledge version="1"><meta/></knowledge>',
    ],
)
def test_an_unrecognised_xml_shape_declines_so_the_generic_parser_still_runs(raw):
    # Declining must be `None`, never `[]`: parse_file reads `[]` as "handled", and the content2
    # indexer deletes the file's existing documents before writing, so `[]` would drop the file.
    assert parse(raw) is None


def test_malformed_xml_declines_rather_than_raising():
    assert parse("<knowledge><units>  not closed") is None


def test_a_knowledge_export_that_fails_validation_declines_rather_than_failing_the_ingest():
    # lemonxml raises on a duplicate chunk id. That is right for a first-party feed; for a customer's
    # file it would fail that bot's whole ingest, so it must degrade to the generic parser instead.
    duplicate_ids = KNOWLEDGE_XML.replace('<chunk id="c0002">', '<chunk id="c0001">')

    assert parse(duplicate_ids) is None


def test_an_empty_content_chunk_declines_rather_than_raising():
    empty_content = KNOWLEDGE_XML.replace(
        "<content>Welcome coaches to module one, the coaching mindset.</content>", "<content></content>"
    )

    assert parse(empty_content) is None


def test_only_xml_files_with_a_category_are_claimed():
    assert (
        asyncio.run(
            build_dynamic_xml_sections_if_applicable(
                file=build_file(KNOWLEDGE_XML, filename="export.json"), category="hyroxlemon"
            )
        )
        is None
    )
    assert asyncio.run(build_dynamic_xml_sections_if_applicable(file=build_file(KNOWLEDGE_XML), category=None)) is None
