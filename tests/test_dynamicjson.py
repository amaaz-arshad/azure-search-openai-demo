"""Tests for the provisioned ("generic") bot JSON record parser.

The parser exists because `JsonParser` mangled these files: it re-serialised each record so the
indexed text was JSON syntax with escaped unicode, chunked across record boundaries, and never set
title/url/tags. Every test here pins one of those properties, or one of the safety rules that keep a
customer's unexpected payload from taking a bot's whole corpus down.
"""

import asyncio
import io
import json

import pytest

from prepdocslib.dynamicjson import (
    build_boilerplate_index,
    build_dynamic_json_sections_if_applicable,
    normalize_record_text,
    prepare_dynamic_json_sections,
    resolve_url,
    title_before_boilerplate,
    title_from_url,
)
from prepdocslib.listfilestrategy import File

SOFT_HYPHEN = chr(0x00AD)
NON_BREAKING_SPACE = chr(0x00A0)
ZERO_WIDTH_SPACE = chr(0x200B)
BOM = chr(0xFEFF)

# The two shapes every live content2 JSON file uses: an array of {url, content} scraped pages, and a
# single {title, content} document.
SCRAPED_NAV = (
    "Direkt zum Inhalt Direkt zur Hauptnavigation Direkt zum Fussbereich Direkteinstieg "
    "Studieninteressierte Studierende Internationales Intern Suche"
)


def build_file(payload, *, filename: str = "www.example.de_20260818.json") -> File:
    raw = payload if isinstance(payload, (bytes, str)) else json.dumps(payload, ensure_ascii=False)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    stream = io.BytesIO(raw)
    stream.name = filename
    return File(content=stream)


def parse(payload, *, category: str = "fhp", filename: str = "www.example.de_20260818.json"):
    return asyncio.run(
        build_dynamic_json_sections_if_applicable(file=build_file(payload, filename=filename), category=category)
    )


def scraped_pages(count: int = 20) -> list[dict]:
    """Records shaped like a real website scrape.

    Each record opens with that page's own HTML <title>, continues into the site name and then the
    site-wide navigation, and ends with body text unique to the page. The site name is shared by
    every page, so the parser treats it as chrome and the derived title is the unique part.
    """
    return [
        {
            "url": f"https://www.example.de/seite-{index}",
            "content": (
                f"Thema Nummer {index} | Example Hochschule {SCRAPED_NAV} "
                f"Ausfuehrlicher Fliesstext ueber Thema {index} mit genug Inhalt zum Indexieren."
            ),
        }
        for index in range(count)
    ]


def test_each_record_becomes_its_own_chunks_and_carries_its_own_url_and_title():
    sections = parse(scraped_pages(20))

    assert sections is not None
    # Every section belongs to exactly one record: its url header matches its own url field.
    for section in sections:
        assert section.url is not None
        assert f"url: {section.url}" in section.chunk.text
    # ...and every record contributed at least one section.
    assert {section.url for section in sections} == {f"https://www.example.de/seite-{index}" for index in range(20)}
    # The page title is carved out of the body, so the citation label is not the raw URL. The site
    # name is shared by every page, so it is chrome and is excluded.
    assert {section.title for section in sections} == {f"Thema Nummer {index}" for index in range(20)}


def test_a_single_object_document_uses_its_title_and_has_no_url():
    sections = parse({"title": "Geschichte ueber Olaf", "content": "One morning, when Gregor Samsa woke."})

    assert sections is not None and len(sections) == 1
    assert sections[0].title == "Geschichte ueber Olaf"
    assert sections[0].url is None
    assert "One morning" in sections[0].chunk.text


def test_sourcepage_is_the_source_filename_so_a_urlless_citation_resolves():
    # With no url the citation IS the sourcepage, and the frontend resolves it as
    # /content2/<bot>/<sourcepage>. Only the filename exists as a blob there - a record id would 404.
    sections = parse({"title": "FAQ", "content": "Bla Blubb"}, filename="Olafs_FAQ_20260724110146.json")

    assert sections is not None
    assert sections[0].sourcepage == "Olafs_FAQ_20260724110146.json"
    assert sections[0].sourcefile == "Olafs_FAQ_20260724110146.json"


def test_indexed_text_is_prose_not_json_syntax():
    sections = parse([{"url": "https://www.example.de/a", "content": "Preis: 5 EUR fuer Mitglieder"}])

    assert sections is not None
    text = sections[0].chunk.text
    assert "Preis: 5 EUR fuer Mitglieder" in text
    # The old JsonParser wrote json.dumps(record), which is what these two assertions rule out.
    assert not text.lstrip().startswith("{")
    assert '"content":' not in text


@pytest.mark.parametrize(
    "payload",
    [
        {"documents": [{"url": "https://a.de/x", "content": "Erster Text hier."}]},
        {"records": [{"url": "https://a.de/x", "content": "Erster Text hier."}]},
        {"items": [{"url": "https://a.de/x", "content": "Erster Text hier."}]},
        # An unknown wrapper key with exactly one list-of-dicts value.
        {"count": 1, "payloadRows": [{"url": "https://a.de/x", "content": "Erster Text hier."}]},
    ],
)
def test_wrapper_shapes_are_unwrapped(payload):
    sections = parse(payload)

    assert sections is not None and len(sections) == 1
    assert sections[0].url == "https://a.de/x"


def test_an_id_to_record_mapping_is_accepted_and_the_key_seeds_the_id():
    sections = parse({"page-812": {"content": "Radiologietechnologie Inhalt."}})

    assert sections is not None and len(sections) == 1
    assert "page-812" in sections[0].id


@pytest.mark.parametrize(
    ("record", "expected_content", "expected_title", "expected_url"),
    [
        ({"heading": "Titel A", "body": "Body text"}, "Body text", "Titel A", None),
        ({"name": "Titel B", "text": "Text field"}, "Text field", "Titel B", None),
        ({"headline": "Titel C", "markdown": "Markdown body"}, "Markdown body", "Titel C", None),
        ({"title": "Titel D", "content": "x", "link": "https://a.de/d"}, "x", "Titel D", "https://a.de/d"),
        ({"title": "Titel E", "content": "x", "href": "https://a.de/e"}, "x", "Titel E", "https://a.de/e"),
        ({"title": "Titel F", "content": "x", "permalink": "https://a.de/f"}, "x", "Titel F", "https://a.de/f"),
    ],
)
def test_field_aliases_resolve(record, expected_content, expected_title, expected_url):
    sections = parse([record])

    assert sections is not None and len(sections) == 1
    assert expected_content in sections[0].chunk.text
    assert sections[0].title == expected_title
    assert sections[0].url == expected_url


def test_field_names_are_matched_case_insensitively():
    sections = parse([{"Title": "Gross geschrieben", "CONTENT": "Inhalt", "URL": "https://a.de/x"}])

    assert sections is not None
    assert sections[0].title == "Gross geschrieben"
    assert sections[0].url == "https://a.de/x"


@pytest.mark.parametrize(
    "tag_field",
    [
        {"tags": ["alpha", "beta"]},
        {"keywords": ["alpha", "beta"]},
        {"topics": "alpha, beta"},
        {"labels": "alpha; beta"},
    ],
)
def test_tags_accept_lists_and_delimited_strings(tag_field):
    sections = parse([{"title": "T", "content": "Inhalt", **tag_field}])

    assert sections is not None
    assert sections[0].tags == ["alpha", "beta"]
    assert "tags: alpha, beta" in sections[0].chunk.text


def test_unmapped_fields_are_preserved_as_searchable_metadata_lines():
    sections = parse(
        [
            {
                "title": "Kurs",
                "content": "Inhalt",
                "date": "2026-05-07",
                "author": "Olaf",
                "published": True,
                "views": 42,
                "metadata": {"degree_name": "Radiologietechnologie (BSc)"},
            }
        ]
    )

    assert sections is not None
    text = sections[0].chunk.text
    assert "date: 2026-05-07" in text
    assert "author: Olaf" in text
    assert "published: true" in text
    assert "views: 42" in text
    assert "metadata.degree_name: Radiologietechnologie (BSc)" in text


def test_title_and_url_are_found_inside_a_metadata_container():
    sections = parse([{"content": "Inhalt", "metadata": {"title": "Aus Metadaten", "url": "https://a.de/m"}}])

    assert sections is not None
    assert sections[0].title == "Aus Metadaten"
    assert sections[0].url == "https://a.de/m"


@pytest.mark.parametrize(
    "url_value",
    ["/relative/path", "www.example.de", "ftp://example.de/x", "mailto:a@b.de", "snap.de feed", ""],
)
def test_only_an_absolute_http_url_is_stored(url_value):
    # The frontend decides "render an external link" purely from the http(s) prefix, so anything else
    # here would become a citation that is neither a link nor a resolvable file path.
    sections = parse([{"title": "T", "content": "Inhalt", "url": url_value}])

    assert sections is not None
    assert sections[0].url is None


def test_a_source_field_that_is_not_a_url_does_not_become_one():
    # `source` is a url alias, but feeds also use it for a plain feed name.
    assert resolve_url({"source": "breitband.tirol"}) is None
    assert resolve_url({"source": "https://breitband.tirol/faqs/"}) == "https://breitband.tirol/faqs/"


def test_records_without_content_are_skipped_not_indexed_as_header_only_documents():
    sections = parse(
        [
            {"url": "https://a.de/leer", "content": "   "},
            {"url": "https://a.de/voll", "content": "Echter Inhalt hier."},
            {"url": "https://a.de/fehlt"},
        ]
    )

    assert sections is not None
    assert [section.url for section in sections] == ["https://a.de/voll"]


@pytest.mark.parametrize(
    "payload",
    [
        # Not a record collection at all.
        [1, 2, 3],
        ["a", "b"],
        {"feed": "snap.de", "generated_at": "2026-06-24T10:00:00Z"},
        {"config": {"retries": 3}, "timeout": 30},
        [],
        {},
        "just a string",
        42,
        # Records exist but none carries body text.
        [{"url": "https://a.de/x"}, {"url": "https://a.de/y"}],
    ],
)
def test_an_unrecognised_payload_declines_so_the_generic_parser_still_runs(payload):
    # Declining must be `None`, never `[]`: parse_file reads an empty list as "handled", and the
    # content2 indexer deletes the file's existing documents *before* writing the new ones - so `[]`
    # would silently drop the whole file from the index.
    assert parse(payload) is None


def test_malformed_json_declines_rather_than_failing_the_ingest():
    assert parse(b"{not json at all", category="fhp") is None


def test_a_utf8_bom_is_tolerated():
    payload = BOM + json.dumps([{"title": "Mit BOM", "content": "Inhalt"}])

    sections = parse(payload.encode("utf-8"))

    assert sections is not None
    assert sections[0].title == "Mit BOM"


def test_a_json_file_is_only_claimed_when_the_extension_and_category_fit():
    assert (
        asyncio.run(
            build_dynamic_json_sections_if_applicable(
                file=build_file({"title": "T", "content": "x"}, filename="notes.txt"), category="fhp"
            )
        )
        is None
    )
    assert (
        asyncio.run(
            build_dynamic_json_sections_if_applicable(
                file=build_file({"title": "T", "content": "x"}, filename="notes.json"), category=None
            )
        )
        is None
    )


def test_ids_are_unique_even_when_two_records_normalise_to_the_same_slug():
    # Both of these appear in the live dsgvo-gesetz.de export and slug-normalise identically; without
    # the positional index in the id they would overwrite each other in the index.
    sections = parse(
        [
            {"url": "https://dsgvo-gesetz.de/", "content": "Erster Datensatz mit Inhalt."},
            {"url": "https://dsgvo-gesetz.de", "content": "Zweiter Datensatz mit Inhalt."},
        ]
    )

    assert sections is not None
    assert len({section.id for section in sections}) == len(sections)


def test_ids_are_deterministic_so_a_re_upload_overwrites_rather_than_duplicates():
    payload = scraped_pages(3)

    first = parse(payload)
    second = parse(payload)

    assert first is not None and second is not None
    assert [section.id for section in first] == [section.id for section in second]


def test_a_long_record_is_split_into_several_chunks_that_all_keep_the_record_metadata():
    long_body = "Ein ausreichend langer Satz zum Aufteilen des Inhalts. " * 400
    sections = parse([{"title": "Langer Text", "url": "https://a.de/lang", "content": long_body}])

    assert sections is not None and len(sections) > 1
    for section in sections:
        assert section.title == "Langer Text"
        assert section.url == "https://a.de/lang"
        assert "title: Langer Text" in section.chunk.text
        assert "url: https://a.de/lang" in section.chunk.text


def test_chunk_boundaries_do_not_cut_words_in_half():
    long_body = "Donaudampfschiffahrtsgesellschaftskapitaen faehrt heute wieder aus. " * 300
    sections = parse([{"title": "T", "content": long_body}])

    assert sections is not None and len(sections) > 1
    for section in sections:
        body = section.chunk.text.split("content:", 1)[1]
        for fragment in body.split():
            assert fragment in long_body


def test_soft_hyphens_and_unicode_spaces_are_normalised_so_words_are_searchable():
    # bsi.bund.de hyphenates every heading with U+00AD, which made "Gebaerdensprache" unmatchable.
    hyphenated = f"Ge{SOFT_HYPHEN}baer{SOFT_HYPHEN}den{SOFT_HYPHEN}spra{SOFT_HYPHEN}che"
    sections = parse([{"title": "T", "content": f"{hyphenated}{NON_BREAKING_SPACE}und{ZERO_WIDTH_SPACE} mehr"}])

    assert sections is not None
    text = sections[0].chunk.text
    assert "Gebaerdensprache" in text
    assert SOFT_HYPHEN not in text
    assert NON_BREAKING_SPACE not in text
    assert ZERO_WIDTH_SPACE not in text


def test_normalize_record_text_does_not_change_wording():
    assert normalize_record_text("Preis:  5  EUR\r\n\r\n\r\nZeile") == "Preis: 5 EUR\n\nZeile"


def test_boilerplate_detection_needs_more_than_one_record():
    assert build_boilerplate_index(["ein einzelner Datensatz mit genug Text darin"]) is None
    assert title_before_boilerplate("egal welcher Text", None) == ""


def test_a_title_shared_by_many_pages_is_still_used_as_the_title():
    # A CMS listing template gives many URLs the same page title, so the title itself is repeated
    # text. Cutting at the first n-gram above the threshold would treat it as chrome and throw it
    # away; the site-wide nav that follows is repeated more often still, so keying the cut on the
    # frequency *rise* keeps the title. Proportions here mirror the live fhg-tirol export, where the
    # shared title appeared on 91 of 500 pages and the nav on 463.
    listing_pages = [
        {
            "url": f"https://www.example.de/page.cfm?id={index}",
            "content": f"Beitraege Uebersicht {SCRAPED_NAV} Nachricht Nummer {index} mit echtem Inhalt.",
        }
        for index in range(30)
    ]
    unique_pages = [
        {
            "url": f"https://www.example.de/thema-{index}",
            "content": f"Fachbereich {index} Profil {SCRAPED_NAV} Fliesstext zu Fachbereich {index}.",
        }
        for index in range(170)
    ]

    sections = parse([*listing_pages, *unique_pages])

    assert sections is not None
    titles = {section.title for section in sections}
    # The listing template's title is shared by 30 URLs and is still kept...
    assert "Beitraege Uebersicht" in titles
    # ...while pages with their own title keep theirs. "Profil" is shared by all 170 of them, so it
    # is chrome too and is correctly excluded - only the part unique to the page survives.
    assert "Fachbereich 0" in titles
    assert "Fachbereich 169" in titles
    # Had the shared title been mistaken for nav, every listing page would have fallen back to its URL
    # slug, which for a `page.cfm` entry point is the query value.
    assert not any(title.isdigit() for title in titles)


def test_a_phrase_that_merely_recurs_in_prose_does_not_truncate_a_title():
    # Two of the pages open with the same long phrase; the nav is shared by all of them, exactly as in
    # the live dsgvo-gesetz.de export. Keying the cut on the frequency rise rather than on "first
    # n-gram above the threshold" is what stops the shared prose from truncating those two titles.
    topics = [
        "Auskunftsrecht",
        "Berichtigung",
        "Loeschung",
        "Einschraenkung",
        "Datenuebertragbarkeit",
        "Widerspruchsrecht",
        "Profiling",
        "Beschraenkungen",
        "Verantwortung",
        "Technikgestaltung",
        "Auftragsverarbeiter",
        "Verzeichnis",
        "Aufsichtsbehoerde",
        "Meldepflicht",
        "Folgenabschaetzung",
        "Datenschutzbeauftragter",
        "Verhaltensregeln",
        "Zertifizierung",
        "Drittland",
        "Garantien",
        "Zusammenarbeit",
        "Amtshilfe",
        "Kohaerenz",
    ]
    records = [
        {
            "url": "https://a.de/art-13",
            "content": "Art. 13 Informationspflicht bei Erhebung von Daten " + SCRAPED_NAV + " Volltext eins.",
        },
        {
            "url": "https://a.de/art-14",
            "content": "Art. 14 Informationspflicht bei Erhebung von Daten " + SCRAPED_NAV + " Volltext zwei.",
        },
        *(
            {
                "url": f"https://a.de/art-{15 + offset}",
                "content": f"Art. {15 + offset} {topic} {SCRAPED_NAV} Volltext zu {topic}.",
            }
            for offset, topic in enumerate(topics)
        ),
    ]

    sections = parse(records)

    assert sections is not None
    titles = {section.title for section in sections}
    assert "Art. 13 Informationspflicht bei Erhebung von Daten" in titles
    assert "Art. 14 Informationspflicht bei Erhebung von Daten" in titles
    assert "Art. 15 Auskunftsrecht" in titles


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.fh-potsdam.de/studium-weiterbildung", "Studium Weiterbildung"),
        ("https://www.bsi.bund.de/DE/Themen/Cloud/kriterienkatalog-c5_node.html", "Kriterienkatalog C5 Node"),
        # A generic CMS entry point carries no meaning, so the query string is used instead.
        ("https://www.fhg-tirol.ac.at/page.cfm?vpath=beitraege/details&id=12925", "Beitraege Details"),
        # Nothing usable at all falls back to the host.
        ("https://dsgvo-gesetz.de/", "dsgvo-gesetz.de"),
        ("https://www.example.de/1234", "www.example.de"),
    ],
)
def test_title_from_url_prefers_a_meaningful_segment(url, expected):
    assert title_from_url(url) == expected


def test_the_category_is_the_provisioned_bot_folder():
    sections = prepare_dynamic_json_sections(
        [{"title": "T", "content": "Inhalt"}], file=build_file({"a": 1}), category="rptestbot"
    )

    assert sections is not None
    assert {section.category for section in sections} == {"rptestbot"}
