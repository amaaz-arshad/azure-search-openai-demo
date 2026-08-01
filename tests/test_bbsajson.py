import io
import json

import pytest

from prepdocslib.listfilestrategy import File
from prepdocslib.bbsajson import (
    build_bbsa_sections_if_applicable,
    is_bbsa_payload,
    prepare_bbsa_dataset,
    prepare_bbsa_sections,
    validate_bbsa_payload,
)


class NamedBytesIO(io.BytesIO):
    """BytesIO with a .name so prepdocslib.File can derive a filename/extension."""

    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name


def build_bbsa_record(
    *,
    record_id: str = "faqs-hp",
    title: str = "FAQs",
    url: str = "https://breitband.tirol/faqs-hp/",
    content: str = "Erste Zeile.\n\nZweiter Absatz.",
    tags: list[str] | None = None,
    page_type: str = "page",
) -> dict:
    return {
        "id": record_id,
        "title": title,
        "url": url,
        "content": content,
        "tags": tags if tags is not None else ["website"],
        "type": page_type,
        "date": "2026-07-31",
    }


def build_gemeinde_record(slug: str = "schwoich", name: str = "Schwoich") -> dict:
    return build_bbsa_record(
        record_id=f"gemeinde-{slug}",
        title=f"{name} – Glasfaser in der Gemeinde (Gemeindeinfos)",
        url=f"https://{slug}.breitband.tirol/gemeindeinfos/",
        content=f"# Glasfaser in {name}\n\nDie Gemeinde {name} verlegt ihr Glasfasernetz kostenlos.",
        tags=["gemeinde", slug],
        page_type="gemeinde",
    )


def build_bbsa_payload(documents: list[dict] | None = None) -> dict:
    docs = documents if documents is not None else [build_bbsa_record()]
    return {
        "feed": "breitband.tirol",
        "generated_at": "2026-07-31T10:00:00Z",
        "sources": ["https://breitband.tirol"],
        "count": len(docs),
        "documents": docs,
    }


def make_file(payload: dict, name: str = "bbsa.json") -> File:
    return File(content=NamedBytesIO(json.dumps(payload).encode("utf-8"), name))


def test_prepare_bbsa_dataset_maps_record_fields_with_first_class_url():
    content = "Erste Zeile.\n\nZweiter Absatz."
    dataset = prepare_bbsa_dataset(
        build_bbsa_payload([build_bbsa_record(content=content)]),
        dataset_filename="bbsa.json",
        category="bbsa",
    )

    assert len(dataset.documents) == 1
    document = dataset.documents[0]
    assert document.id == "bbsa-faqs-hp-chunk-001"
    assert document.content == content
    assert document.category == "bbsa"
    assert document.sourcepage == "faqs-hp"
    assert document.sourcefile == "bbsa.json"
    assert document.title == "FAQs"
    # Citation target for bbsa is the live page url.
    assert document.url == "https://breitband.tirol/faqs-hp/"
    assert document.tags == ["website", "page"]


def test_municipality_documents_keep_the_subdomain_url_and_name_in_the_title():
    # Attribution contract: with citation_target="url" the source label the model sees IS the
    # municipality subdomain, so every chunk of a municipality document can be traced back to
    # the right municipality even though only the first chunk repeats the name in its body.
    dataset = prepare_bbsa_dataset(
        build_bbsa_payload([build_gemeinde_record("virgen", "Virgen")]),
        dataset_filename="bbsa.json",
        category="bbsa",
    )

    document = dataset.documents[0]
    assert document.id == "bbsa-gemeinde-virgen-chunk-001"
    assert document.sourcepage == "gemeinde-virgen"
    assert document.url == "https://virgen.breitband.tirol/gemeindeinfos/"
    assert document.title.startswith("Virgen – ")
    assert document.tags == ["gemeinde", "virgen"]


def test_every_chunk_of_a_split_municipality_document_keeps_its_municipality_url():
    long_record = build_gemeinde_record("kals", "Kals")
    long_record["content"] = "Die Gemeinde Kals baut aus. " * 200
    dataset = prepare_bbsa_dataset(
        build_bbsa_payload([long_record]),
        dataset_filename="bbsa.json",
        category="bbsa",
        max_chunk_tokens=25,
    )

    assert len(dataset.documents) > 1
    assert {document.url for document in dataset.documents} == {"https://kals.breitband.tirol/gemeindeinfos/"}
    assert {document.sourcepage for document in dataset.documents} == {"gemeinde-kals"}


def test_prepare_bbsa_dataset_appends_type_to_tags_without_duplicates():
    dataset = prepare_bbsa_dataset(
        build_bbsa_payload([build_bbsa_record(tags=["website", "page"], page_type="page")]),
        dataset_filename="bbsa.json",
        category="bbsa",
    )

    assert dataset.documents[0].tags == ["website", "page"]


def test_prepare_bbsa_dataset_splits_long_content_without_rewriting_it():
    content = "Absatz eins. " + "Alpha beta gamma delta epsilon. " * 80
    dataset = prepare_bbsa_dataset(
        build_bbsa_payload([build_bbsa_record(content=content)]),
        dataset_filename="bbsa.json",
        category="bbsa",
        max_chunk_tokens=25,
    )

    assert len(dataset.documents) > 1
    assert "".join(document.content for document in dataset.documents) == content
    assert dataset.documents[0].id == "bbsa-faqs-hp-chunk-001"
    assert dataset.documents[-1].id.startswith("bbsa-faqs-hp-chunk-")


def test_validate_bbsa_payload_rejects_duplicate_ids():
    payload = build_bbsa_payload([build_bbsa_record(), build_bbsa_record()])

    with pytest.raises(ValueError, match="duplicate id"):
        validate_bbsa_payload(payload)


def test_validate_bbsa_payload_requires_feed_marker():
    payload = build_bbsa_payload()
    assert is_bbsa_payload(payload)

    payload["feed"] = "snap.de"
    assert not is_bbsa_payload(payload)
    with pytest.raises(ValueError, match="feed"):
        validate_bbsa_payload(payload)


def test_validate_bbsa_payload_requires_documents():
    payload = build_bbsa_payload()
    payload["documents"] = []
    with pytest.raises(ValueError, match="non-empty 'documents'"):
        validate_bbsa_payload(payload)


def test_to_search_document_includes_title_and_url():
    dataset = prepare_bbsa_dataset(build_bbsa_payload(), dataset_filename="bbsa.json", category="bbsa")
    search_document = dataset.documents[0].to_search_document(
        storage_url="https://storage.example.net/content/bbsa/bbsa.json"
    )
    assert search_document["storageUrl"].endswith("/content/bbsa/bbsa.json")
    assert search_document["title"] == "FAQs"
    assert search_document["url"] == "https://breitband.tirol/faqs-hp/"
    assert search_document["category"] == "bbsa"


def test_prepare_bbsa_sections_builds_sections_from_file():
    payload = build_bbsa_payload([build_bbsa_record(), build_gemeinde_record()])
    sections = prepare_bbsa_sections(payload, file=make_file(payload), category="bbsa")
    assert len(sections) == 2
    assert sections[0].url == "https://breitband.tirol/faqs-hp/"
    assert sections[1].url == "https://schwoich.breitband.tirol/gemeindeinfos/"
    assert {section.category for section in sections} == {"bbsa"}


@pytest.mark.asyncio
async def test_build_bbsa_sections_if_applicable_only_for_bbsa_json():
    payload = build_bbsa_payload()

    # Right category + .json + bbsa payload -> sections.
    sections = await build_bbsa_sections_if_applicable(file=make_file(payload), category="bbsa")
    assert sections is not None and len(sections) == 1

    # Wrong category -> not claimed.
    assert await build_bbsa_sections_if_applicable(file=make_file(payload), category="snap") is None

    # bbsa category but a non-bbsa JSON payload -> not claimed (falls through to generic parser).
    other_file = File(content=NamedBytesIO(json.dumps({"documents": []}).encode("utf-8"), "other.json"))
    assert await build_bbsa_sections_if_applicable(file=other_file, category="bbsa") is None


@pytest.mark.asyncio
async def test_bbsa_and_snap_parsers_do_not_claim_each_others_feeds():
    """Both feeds are JSON web-scrape feeds; the category gate plus the feed marker keep them
    disjoint, so a mis-categorized upload falls through instead of being silently mis-parsed."""
    from prepdocslib.snapjson import build_snap_sections_if_applicable

    bbsa_payload = build_bbsa_payload()
    snap_payload = {
        "feed": "snap.de",
        "count": 1,
        "documents": [
            {
                "id": "tools-nerilio",
                "title": "Nerilio",
                "url": "https://www.snap.de/tools/nerilio/",
                "content": "Text.",
                "tags": [],
            }
        ],
    }

    # bbsa payload uploaded under category "snap": snap's marker check rejects it.
    assert await build_snap_sections_if_applicable(file=make_file(bbsa_payload, "bbsa.json"), category="snap") is None
    # snap payload uploaded under category "bbsa": bbsa's marker check rejects it.
    assert await build_bbsa_sections_if_applicable(file=make_file(snap_payload, "snap.json"), category="bbsa") is None
