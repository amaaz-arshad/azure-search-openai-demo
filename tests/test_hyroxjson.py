import pytest

from prepdocslib.hyroxjson import (
    HYROX_SOURCE_CATEGORY,
    is_hyrox_payload,
    prepare_hyrox_dataset,
)


def build_hyrox_record(
    *,
    content: str = "Titel: Level 1 - Module 1 - Intro URL: https://example.test/hyrox Intro body.",
    lms_id: str = "17818",
    tags: list[str] | None = None,
) -> dict:
    return {
        "id": "ID040",
        "title": "Level 1 Module 1 HYROX365 philosophy in depth explained",
        "category": HYROX_SOURCE_CATEGORY,
        "author": "HYROX",
        "date": "2025-09-30",
        "version": "v1.0",
        "lms_id": lms_id,
        "url": f"https://web.lemon-mobile-learning.com/hyrox/#/inhalt/{lms_id}",
        "tags": tags if tags is not None else ["philosophy", "HYROX Academy Level 1"],
        "summary": "This summary must not be indexed as additional content.",
        "content": content,
    }


def test_prepare_hyrox_dataset_maps_record_fields_without_summary_content():
    content = "Exact source content.\n\nSecond paragraph with no generated metadata."
    payload = [build_hyrox_record(content=content)]

    prepared = prepare_hyrox_dataset(payload, dataset_filename="HYROX_Level_1.json", category="lemon")

    assert len(prepared.documents) == 1
    document = prepared.documents[0]
    assert document.id == "hyrox-level-1-17818-chunk-001"
    assert document.content == content
    assert document.category == "lemon"
    assert document.sourcepage == "17818"
    assert document.sourcefile == "HYROX_Level_1.json"
    assert document.title == "Level 1 Module 1 HYROX365 philosophy in depth explained"
    assert document.url == "https://web.lemon-mobile-learning.com/hyrox/#/inhalt/17818"
    assert document.tags == ["philosophy", "HYROX Academy Level 1"]
    assert "summary" not in document.content.lower()
    assert "title:" not in document.content.lower()

    search_document = document.to_search_document(
        storage_url="https://storage.example.net/content/lemon/HYROX_Level_1.json"
    )
    assert search_document["storageUrl"].endswith("/content/lemon/HYROX_Level_1.json")
    assert search_document["sourcepage"] == "17818"
    assert search_document["tags"] == ["philosophy", "HYROX Academy Level 1"]


def test_prepare_hyrox_dataset_appends_source_category_to_tags():
    payload = [build_hyrox_record(tags=["philosophy", "depth"])]

    prepared = prepare_hyrox_dataset(payload, dataset_filename="HYROX_Level_1.json", category="lemon")

    assert prepared.documents[0].tags == ["philosophy", "depth", "HYROX Academy Level 1"]


def test_prepare_hyrox_dataset_splits_long_content_without_rewriting_it():
    content = (
        "Titel: This text is intentionally preserved. "
        "--> 00:00:09.400 Timestamp text also stays. " + "Alpha beta gamma delta epsilon. " * 80
    )
    payload = [build_hyrox_record(content=content, lms_id="18118")]

    prepared = prepare_hyrox_dataset(
        payload,
        dataset_filename="HYROX_Level_1.json",
        category="lemon",
        max_chunk_tokens=25,
    )

    assert len(prepared.documents) > 1
    assert "".join(document.content for document in prepared.documents) == content
    assert prepared.documents[0].id == "hyrox-level-1-18118-chunk-001"
    assert prepared.documents[-1].id.startswith("hyrox-level-1-18118-chunk-")
    assert "--> 00:00:09.400" in "".join(document.content for document in prepared.documents)
    assert all("This summary must not be indexed" not in document.content for document in prepared.documents)


def test_prepare_hyrox_dataset_rejects_duplicate_lms_ids():
    payload = [
        build_hyrox_record(lms_id="17818"),
        build_hyrox_record(lms_id="17818"),
    ]

    with pytest.raises(ValueError, match="duplicate lms_id"):
        prepare_hyrox_dataset(payload, dataset_filename="HYROX_Level_1.json", category="lemon")


def test_is_hyrox_payload_requires_hyrox_source_category():
    payload = [build_hyrox_record()]
    assert is_hyrox_payload(payload)

    payload[0]["category"] = "Other Academy"
    assert not is_hyrox_payload(payload)
