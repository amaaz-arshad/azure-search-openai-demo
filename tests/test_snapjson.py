import io
import json

import pytest

from prepdocslib.listfilestrategy import File
from prepdocslib.snapjson import (
    build_snap_sections_if_applicable,
    is_snap_payload,
    prepare_snap_dataset,
    prepare_snap_sections,
    validate_snap_payload,
)


class NamedBytesIO(io.BytesIO):
    """BytesIO with a .name so prepdocslib.File can derive a filename/extension."""

    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name


def build_snap_record(
    *,
    record_id: str = "tools-nerilio",
    title: str = "Nerilio",
    url: str = "https://www.snap.de/tools/nerilio/",
    content: str = "Erste Zeile.\n\nZweiter Absatz.",
    tags: list[str] | None = None,
    page_type: str = "page",
) -> dict:
    return {
        "id": record_id,
        "title": title,
        "url": url,
        "content": content,
        "tags": tags if tags is not None else ["tools"],
        "type": page_type,
        "date": "2026-05-07",
    }


def build_snap_payload(documents: list[dict] | None = None) -> dict:
    docs = documents if documents is not None else [build_snap_record()]
    return {
        "feed": "snap.de",
        "generated_at": "2026-06-24T10:00:00Z",
        "source": "https://www.snap.de",
        "count": len(docs),
        "documents": docs,
    }


def make_file(payload: dict, name: str = "snap.json") -> File:
    return File(content=NamedBytesIO(json.dumps(payload).encode("utf-8"), name))


def test_prepare_snap_dataset_maps_record_fields_with_first_class_url():
    content = "Erste Zeile.\n\nZweiter Absatz."
    dataset = prepare_snap_dataset(
        build_snap_payload([build_snap_record(content=content)]),
        dataset_filename="snap.json",
        category="snap",
    )

    assert len(dataset.documents) == 1
    document = dataset.documents[0]
    assert document.id == "snap-tools-nerilio-chunk-001"
    assert document.content == content
    assert document.category == "snap"
    assert document.sourcepage == "tools-nerilio"
    assert document.sourcefile == "snap.json"
    assert document.title == "Nerilio"
    # Citation target for snap is the live page url.
    assert document.url == "https://www.snap.de/tools/nerilio/"
    assert document.tags == ["tools", "page"]


def test_prepare_snap_dataset_appends_type_to_tags_without_duplicates():
    dataset = prepare_snap_dataset(
        build_snap_payload([build_snap_record(tags=["news", "page"], page_type="page")]),
        dataset_filename="snap.json",
        category="snap",
    )

    assert dataset.documents[0].tags == ["news", "page"]


def test_prepare_snap_dataset_splits_long_content_without_rewriting_it():
    content = "Absatz eins. " + "Alpha beta gamma delta epsilon. " * 80
    dataset = prepare_snap_dataset(
        build_snap_payload([build_snap_record(content=content)]),
        dataset_filename="snap.json",
        category="snap",
        max_chunk_tokens=25,
    )

    assert len(dataset.documents) > 1
    assert "".join(document.content for document in dataset.documents) == content
    assert dataset.documents[0].id == "snap-tools-nerilio-chunk-001"
    assert dataset.documents[-1].id.startswith("snap-tools-nerilio-chunk-")


def test_validate_snap_payload_rejects_duplicate_ids():
    payload = build_snap_payload([build_snap_record(), build_snap_record()])

    with pytest.raises(ValueError, match="duplicate id"):
        validate_snap_payload(payload)


def test_validate_snap_payload_requires_feed_marker():
    payload = build_snap_payload()
    assert is_snap_payload(payload)

    payload["feed"] = "something-else"
    assert not is_snap_payload(payload)
    with pytest.raises(ValueError, match="feed"):
        validate_snap_payload(payload)


def test_to_search_document_includes_title_and_url():
    dataset = prepare_snap_dataset(build_snap_payload(), dataset_filename="snap.json", category="snap")
    search_document = dataset.documents[0].to_search_document(
        storage_url="https://storage.example.net/content/snap/snap.json"
    )
    assert search_document["storageUrl"].endswith("/content/snap/snap.json")
    assert search_document["title"] == "Nerilio"
    assert search_document["url"] == "https://www.snap.de/tools/nerilio/"
    assert search_document["category"] == "snap"


def test_prepare_snap_sections_builds_sections_from_file():
    sections = prepare_snap_sections(build_snap_payload(), file=make_file(build_snap_payload()), category="snap")
    assert len(sections) == 1
    assert sections[0].url == "https://www.snap.de/tools/nerilio/"
    assert sections[0].category == "snap"


@pytest.mark.asyncio
async def test_build_snap_sections_if_applicable_only_for_snap_json():
    payload = build_snap_payload()

    # Right category + .json + snap payload -> sections.
    sections = await build_snap_sections_if_applicable(file=make_file(payload), category="snap")
    assert sections is not None and len(sections) == 1

    # Wrong category -> not claimed.
    assert await build_snap_sections_if_applicable(file=make_file(payload), category="nerilio") is None

    # snap category but a non-snap JSON payload -> not claimed (falls through to generic parser).
    other_file = File(content=NamedBytesIO(json.dumps({"documents": []}).encode("utf-8"), "other.json"))
    assert await build_snap_sections_if_applicable(file=other_file, category="snap") is None
