from typing import Any

import pytest
from types import SimpleNamespace

from prepdocslib.blobautoindex import AutoBlobIndexer, AutoBlobIndexerConfig, normalize_blob_name


class MockBlobManager:
    def __init__(self) -> None:
        self.uploads: list[dict[str, Any]] = []
        self.removals: list[str] = []
        self.downloads: dict[str, tuple[bytes, dict[str, Any]]] = {}
        self.download_calls: list[tuple[str, str | None]] = []
        self.endpoint = "https://storage.example.com"
        self.container = "content"

    async def upload_blob_data(self, file, blob_name: str, content_type: str | None = None) -> str:
        self.uploads.append(
            {
                "blob_name": blob_name,
                "content": file.read(),
                "content_type": content_type,
            }
        )
        file.seek(0)
        return f"https://storage.example.com/content/{blob_name}"

    async def remove_blob_name(self, blob_name: str) -> None:
        self.removals.append(blob_name)

    async def list_blob_names(self, prefix: str) -> list[str]:
        return [
            upload["blob_name"]
            for upload in self.uploads
            if upload["blob_name"].startswith(prefix) and upload["blob_name"] not in self.removals
        ]

    async def download_blob(self, blob_name: str, container: str | None = None):
        self.download_calls.append((blob_name, container))
        return self.downloads.get(blob_name)

    def url_for_blob_name(self, blob_name: str) -> str:
        return f"https://storage.example.com/content/{blob_name}"


class MockSearchManager:
    def __init__(self) -> None:
        self.created = 0
        self.removals: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []

    async def create_index(self) -> None:
        self.created += 1

    async def remove_content(self, path=None, category=None, **kwargs) -> None:
        self.removals.append({"path": path, "category": category, **kwargs})

    async def update_content(self, sections, url=None, **kwargs) -> None:
        self.updates.append({"sections": sections, "url": url, **kwargs})


@pytest.mark.asyncio
async def test_auto_blob_indexer_indexes_into_target_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    sections = [object(), object()]

    async def fake_parse_file(*args, **kwargs):
        return sections

    monkeypatch.setattr("prepdocslib.blobautoindex.parse_file", fake_parse_file)

    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = AutoBlobIndexer(
        config=AutoBlobIndexerConfig(
            trigger_container="content",
            source_prefix="nerilio/Nerilio-Moodle",
            target_prefix="moodle",
            category="moodle",
            allowed_extensions=frozenset({".xml"}),
        ),
        blob_manager=blob_manager,
        search_manager=search_manager,
        file_processors={".xml": object()},  # parse_file is monkeypatched
    )

    result = await indexer.index_blob(
        blob_name="content/nerilio/Nerilio-Moodle/course-export.xml",
        content=b"<root />",
        content_type="application/xml",
    )

    assert result.status == "indexed"
    assert result.target_blob_name == "moodle/course-export.xml"
    assert result.storage_url == "https://storage.example.com/content/moodle/course-export.xml"
    assert result.indexed_sections == 2
    assert search_manager.created == 1
    assert search_manager.removals == [
        {
            "path": "course-export.xml",
            "category": "moodle",
            "storage_url_suffix": "moodle/course-export.xml",
        }
    ]
    assert len(search_manager.updates) == 1
    assert search_manager.updates[0]["sections"] == sections
    assert search_manager.updates[0]["url"] == "https://storage.example.com/content/moodle/course-export.xml"
    assert blob_manager.uploads == [
        {
            "blob_name": "moodle/course-export.xml",
            "content": b"<root />",
            "content_type": "application/xml",
        }
    ]


@pytest.mark.asyncio
async def test_auto_blob_indexer_copies_but_does_not_index_when_no_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_parse_file(*args, **kwargs):
        return []

    monkeypatch.setattr("prepdocslib.blobautoindex.parse_file", fake_parse_file)

    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = AutoBlobIndexer(
        config=AutoBlobIndexerConfig(
            trigger_container="content",
            source_prefix="nerilio/Nerilio-Moodle",
            target_prefix="moodle",
            category="moodle",
            allowed_extensions=frozenset({".xml"}),
        ),
        blob_manager=blob_manager,
        search_manager=search_manager,
        file_processors={".xml": object()},
    )

    result = await indexer.index_blob(
        blob_name="content/nerilio/Nerilio-Moodle/empty.xml",
        content=b"",
        content_type="application/xml",
    )

    assert result.status == "copied-no-content"
    assert search_manager.removals == [
        {
            "path": "empty.xml",
            "category": "moodle",
            "storage_url_suffix": "moodle/empty.xml",
        }
    ]
    assert search_manager.updates == []
    assert blob_manager.uploads[0]["blob_name"] == "moodle/empty.xml"


@pytest.mark.asyncio
async def test_auto_blob_indexer_skips_wrong_prefix_without_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_parse_file(*args, **kwargs):
        raise AssertionError("parse_file should not be called")

    monkeypatch.setattr("prepdocslib.blobautoindex.parse_file", fake_parse_file)

    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = AutoBlobIndexer(
        config=AutoBlobIndexerConfig(
            trigger_container="content",
            source_prefix="nerilio/Nerilio-Moodle",
            target_prefix="moodle",
            category="moodle",
            allowed_extensions=frozenset({".xml"}),
        ),
        blob_manager=blob_manager,
        search_manager=search_manager,
        file_processors={".xml": object()},
    )

    result = await indexer.index_blob(
        blob_name="content/other/folder/file.xml",
        content=b"<root />",
        content_type="application/xml",
    )

    assert result.status == "skipped-prefix"
    assert search_manager.created == 0
    assert search_manager.removals == []
    assert search_manager.updates == []
    assert blob_manager.uploads == []


def test_normalize_blob_name_strips_container_prefix() -> None:
    assert (
        normalize_blob_name("content/nerilio/Nerilio-Moodle/sample.xml", "content")
        == "nerilio/Nerilio-Moodle/sample.xml"
    )
    assert (
        normalize_blob_name("/content/nerilio/Nerilio-Moodle/sample.xml", "content")
        == "nerilio/Nerilio-Moodle/sample.xml"
    )


@pytest.mark.asyncio
async def test_auto_blob_indexer_delete_removes_target_blob_and_index_docs() -> None:
    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = AutoBlobIndexer(
        config=AutoBlobIndexerConfig(
            trigger_container="content",
            source_prefix="nerilio/Nerilio-Moodle",
            target_prefix="moodle",
            category="moodle",
            allowed_extensions=frozenset({".xml"}),
        ),
        blob_manager=blob_manager,
        search_manager=search_manager,
        file_processors={".xml": object()},
    )

    result = await indexer.delete_blob(blob_name="content/nerilio/Nerilio-Moodle/course-export.xml")

    assert result.status == "deleted"
    assert result.target_blob_name == "moodle/course-export.xml"
    assert search_manager.removals == [
        {
            "path": "course-export.xml",
            "category": "moodle",
            "storage_url_suffix": "moodle/course-export.xml",
        }
    ]
    assert blob_manager.removals == ["moodle/course-export.xml"]


@pytest.mark.asyncio
async def test_auto_blob_indexer_reads_source_blob_from_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    sections = [object()]

    async def fake_parse_file(*args, **kwargs):
        return sections

    monkeypatch.setattr("prepdocslib.blobautoindex.parse_file", fake_parse_file)

    blob_manager = MockBlobManager()
    blob_manager.downloads["nerilio/Nerilio-Moodle/course-export.xml"] = (
        b"<root />",
        {"content_settings": {"content_type": "application/xml"}},
    )
    search_manager = MockSearchManager()
    indexer = AutoBlobIndexer(
        config=AutoBlobIndexerConfig(
            trigger_container="content",
            source_prefix="nerilio/Nerilio-Moodle",
            target_prefix="moodle",
            category="moodle",
            allowed_extensions=frozenset({".xml"}),
        ),
        blob_manager=blob_manager,
        search_manager=search_manager,
        file_processors={".xml": object()},
    )

    result = await indexer.index_blob_from_storage(blob_name="content/nerilio/Nerilio-Moodle/course-export.xml")

    assert result.status == "indexed"
    assert blob_manager.uploads == [
        {
            "blob_name": "moodle/course-export.xml",
            "content": b"<root />",
            "content_type": "application/xml",
        }
    ]


@pytest.mark.asyncio
async def test_auto_blob_indexer_can_skip_index_schema_management() -> None:
    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = AutoBlobIndexer(
        config=AutoBlobIndexerConfig(
            trigger_container="content",
            source_prefix="nerilio/Nerilio-Moodle",
            target_prefix="moodle",
            category="moodle",
            allowed_extensions=frozenset({".xml"}),
            manage_search_index=False,
        ),
        blob_manager=blob_manager,
        search_manager=search_manager,
        file_processors={".xml": object()},
    )

    await indexer.ensure_index()

    assert search_manager.created == 0


@pytest.mark.asyncio
async def test_auto_blob_indexer_uses_custom_section_builder() -> None:
    built_sections = [object()]

    async def custom_section_builder(*, file, file_processors, category):
        assert file.filename() == "course-export.xml"
        assert category == "publishone"
        assert ".xml" in file_processors
        return built_sections

    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = AutoBlobIndexer(
        config=AutoBlobIndexerConfig(
            trigger_container="content",
            source_prefix="nerilio/Nerilio-PublishOne",
            target_prefix="publishone",
            category="publishone",
            allowed_extensions=frozenset({".xml"}),
        ),
        blob_manager=blob_manager,
        search_manager=search_manager,
        file_processors={".xml": object()},
        section_builder=custom_section_builder,
    )

    result = await indexer.index_blob(
        blob_name="content/nerilio/Nerilio-PublishOne/course-export.xml",
        content=b"<root />",
        content_type="application/xml",
    )

    assert result.status == "indexed"
    assert search_manager.updates[0]["sections"] == built_sections


@pytest.mark.asyncio
async def test_auto_blob_indexer_can_remove_by_storage_url_for_custom_sourcefiles() -> None:
    built_sections = [object()]

    async def custom_section_builder(*, file, file_processors, category):
        return built_sections

    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = AutoBlobIndexer(
        config=AutoBlobIndexerConfig(
            trigger_container="content",
            source_prefix="nerilio/Nerilio-fhg",
            target_prefix="fhg",
            category="fhg",
            allowed_extensions=frozenset({".json"}),
            remove_by_storage_url=True,
        ),
        blob_manager=blob_manager,
        search_manager=search_manager,
        file_processors={".json": object()},
        section_builder=custom_section_builder,
    )

    result = await indexer.index_blob(
        blob_name="content/nerilio/Nerilio-fhg/fhg.json",
        content=b'{"documents":[]}',
        content_type="application/json",
    )

    assert result.status == "indexed"
    assert search_manager.removals == [
        {
            "path": None,
            "category": "fhg",
            "storage_url_suffix": "fhg/fhg.json",
            "storage_url": "https://storage.example.com/content/fhg/fhg.json",
        }
    ]


@pytest.mark.asyncio
async def test_auto_blob_indexer_delete_can_remove_by_storage_url_for_custom_sourcefiles() -> None:
    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = AutoBlobIndexer(
        config=AutoBlobIndexerConfig(
            trigger_container="content",
            source_prefix="nerilio/Nerilio-fhg",
            target_prefix="fhg",
            category="fhg",
            allowed_extensions=frozenset({".json"}),
            remove_by_storage_url=True,
        ),
        blob_manager=blob_manager,
        search_manager=search_manager,
        file_processors={".json": object()},
    )

    result = await indexer.delete_blob(blob_name="content/nerilio/Nerilio-fhg/fhg.json")

    assert result.status == "deleted"
    assert search_manager.removals == [
        {
            "path": None,
            "category": "fhg",
            "storage_url_suffix": "fhg/fhg.json",
            "storage_url": "https://storage.example.com/content/fhg/fhg.json",
        }
    ]
    assert blob_manager.removals == ["fhg/fhg.json"]


def make_content2_indexer(blob_manager, search_manager, file_processors=None) -> AutoBlobIndexer:
    """A content2 dynamic indexer: whole-container watch, per-bot category, no mirror, generic only."""
    return AutoBlobIndexer(
        config=AutoBlobIndexerConfig(
            trigger_container="content2",
            source_prefix="",
            target_prefix="",
            category="",
            allowed_extensions=frozenset({".pdf", ".txt", ".json"}),
            manage_search_index=False,
            source_container="content2",
            mirror_blob=False,
            dynamic_category_from_path=True,
            force_generic_parsing=True,
            dynamic_record_parsing=True,
        ),
        blob_manager=blob_manager,
        search_manager=search_manager,
        file_processors=file_processors or {".pdf": object(), ".txt": object(), ".json": object()},
    )


@pytest.mark.asyncio
async def test_content2_indexer_indexes_in_place_without_mirror(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    sections = [object()]

    async def fake_parse_file(*args, **kwargs):
        captured.update(kwargs)
        return sections

    monkeypatch.setattr("prepdocslib.blobautoindex.parse_file", fake_parse_file)

    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = make_content2_indexer(blob_manager, search_manager)

    result = await indexer.index_blob(
        blob_name="content2/bxa/faq.pdf",
        content=b"%PDF-1.4",
        content_type="application/pdf",
    )

    assert result.status == "indexed"
    # Category is derived from the per-bot folder and generic parsing is forced.
    assert captured["category"] == "bxa"
    assert captured["force_generic"] is True
    # No mirror copy into the `content` container.
    assert blob_manager.uploads == []
    assert result.target_blob_name is None
    # storageUrl points at the in-place content2 source blob.
    assert result.storage_url == "https://storage.example.com/content2/bxa/faq.pdf"
    assert search_manager.updates[0]["url"] == "https://storage.example.com/content2/bxa/faq.pdf"
    # Stale docs for the file are purged by exact source storageUrl within the bot category.
    assert search_manager.removals == [
        {"path": None, "category": "bxa", "storage_url": "https://storage.example.com/content2/bxa/faq.pdf"}
    ]


@pytest.mark.asyncio
async def test_content2_indexer_skips_blob_without_bot_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse_file(*args, **kwargs):
        raise AssertionError("parse_file should not be called for a blob without a bot folder")

    monkeypatch.setattr("prepdocslib.blobautoindex.parse_file", fake_parse_file)

    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = make_content2_indexer(blob_manager, search_manager)

    result = await indexer.index_blob(
        blob_name="content2/orphan.pdf",
        content=b"%PDF",
        content_type="application/pdf",
    )

    assert result.status == "skipped-no-category"
    assert search_manager.updates == []
    assert search_manager.removals == []
    assert blob_manager.uploads == []


@pytest.mark.asyncio
async def test_content2_indexer_delete_purges_docs_without_deleting_blob() -> None:
    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = make_content2_indexer(blob_manager, search_manager)

    result = await indexer.delete_blob(blob_name="content2/bxa/faq.pdf")

    assert result.status == "deleted"
    assert search_manager.removals == [
        {"path": None, "category": "bxa", "storage_url": "https://storage.example.com/content2/bxa/faq.pdf"}
    ]
    # Nothing was ever mirrored into `content`, so no blob is deleted here.
    assert blob_manager.removals == []


@pytest.mark.asyncio
async def test_content2_indexer_from_storage_reads_source_container(monkeypatch: pytest.MonkeyPatch) -> None:
    sections = [object()]

    async def fake_parse_file(*args, **kwargs):
        return sections

    monkeypatch.setattr("prepdocslib.blobautoindex.parse_file", fake_parse_file)

    blob_manager = MockBlobManager()
    blob_manager.downloads["bxa/guide.txt"] = (
        b"hello world",
        {"content_settings": {"content_type": "text/plain"}},
    )
    search_manager = MockSearchManager()
    indexer = make_content2_indexer(blob_manager, search_manager)

    result = await indexer.index_blob_from_storage(blob_name="content2/bxa/guide.txt")

    assert result.status == "indexed"
    # The download is scoped to the content2 source container, not the default `content`.
    assert blob_manager.download_calls == [("bxa/guide.txt", "content2")]
    assert blob_manager.uploads == []
    assert result.storage_url == "https://storage.example.com/content2/bxa/guide.txt"


# --- publishone2 archive packages ------------------------------------------------------------

PACKAGE_FEED_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<folder id="1"><naam>Package</naam><meta />
  <document id="99"><naam>Doc</naam><meta />
    <document version="1">
      <p><img id="Grafik 1" href="https://snap-em.publishone.nl/api/content/8798" po-ref-id="8798">
        <asset id="8798"><title>Doc-image1</title><manifest media-type="image/jpeg" /></asset>
      </img></p>
    </document>
  </document>
</folder>
"""


def build_zip(entries: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


class StubDescriber:
    def __init__(self) -> None:
        self.calls = 0

    async def describe_image(self, image_bytes: bytes) -> str:
        self.calls += 1
        return "a transcribed table"


def make_publishone2_indexer(blob_manager, search_manager, section_builder, describer=None):
    from prepdocslib.feedarchive import FeedArchiveOptions

    return AutoBlobIndexer(
        config=AutoBlobIndexerConfig(
            trigger_container="content",
            source_prefix="nerilio/Nerilio-Amsterdam-ZIP-zip",
            target_prefix="publishone2",
            category="publishone2",
            allowed_extensions=frozenset({".xml", ".zip"}),
            archive_extensions=frozenset({".zip"}),
        ),
        blob_manager=blob_manager,
        search_manager=search_manager,
        file_processors={".xml": object()},
        section_builder=section_builder,
        archive_options=FeedArchiveOptions(describer=describer),
    )


@pytest.mark.asyncio
async def test_archive_indexes_each_document_and_mirrors_its_images() -> None:
    captured: list[dict[str, Any]] = []

    async def section_builder(*, file, file_processors, category, image_bundle=None):
        captured.append({"filename": file.filename(), "category": category, "bundle": image_bundle})
        return [object()]

    describer = StubDescriber()
    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = make_publishone2_indexer(blob_manager, search_manager, section_builder, describer)

    result = await indexer.index_blob(
        blob_name="content/nerilio/Nerilio-Amsterdam-ZIP-zip/nerilio2.zip",
        content=build_zip({"Doc.xml": PACKAGE_FEED_XML, "8798.jpg": b"jpeg-bytes"}),
    )

    assert result.status == "indexed"
    assert result.indexed_sections == 1
    assert describer.calls == 1

    # Everything is namespaced by the archive stem so a package owns its own prefix.
    uploaded = {upload["blob_name"]: upload for upload in blob_manager.uploads}
    assert set(uploaded) == {"publishone2/nerilio2/images/8798.jpg", "publishone2/nerilio2/Doc.xml"}
    assert uploaded["publishone2/nerilio2/images/8798.jpg"]["content"] == b"jpeg-bytes"
    assert uploaded["publishone2/nerilio2/images/8798.jpg"]["content_type"] == "image/jpeg"

    # The section builder receives a bundle resolving the document's <img> to the mirrored blob.
    assert captured[0]["filename"] == "Doc.xml"
    assert captured[0]["category"] == "publishone2"
    resolved = captured[0]["bundle"].lookup(["8798"])
    assert resolved.public_path == "/content/publishone2/nerilio2/images/8798.jpg"
    assert resolved.description == "a transcribed table"

    assert search_manager.updates[0]["url"] == "https://storage.example.com/content/publishone2/nerilio2/Doc.xml"


@pytest.mark.asyncio
async def test_archive_purges_its_whole_package_prefix_before_reindexing() -> None:
    async def section_builder(*, file, file_processors, category, image_bundle=None):
        return [object()]

    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = make_publishone2_indexer(blob_manager, search_manager, section_builder)

    await indexer.index_blob(
        blob_name="content/nerilio/Nerilio-Amsterdam-ZIP-zip/nerilio2.zip",
        content=build_zip({"Doc.xml": PACKAGE_FEED_XML}),
    )

    # A package whose contents shrank must not leave orphaned documents behind, so the purge is
    # keyed on the package prefix rather than on the individual files.
    assert search_manager.removals == [
        {
            "path": None,
            "category": "publishone2",
            "storage_url_prefix": "https://storage.example.com/content/publishone2/nerilio2/",
        }
    ]


@pytest.mark.asyncio
async def test_deleting_an_archive_removes_its_documents_and_blobs() -> None:
    async def section_builder(*, file, file_processors, category, image_bundle=None):
        return [object()]

    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = make_publishone2_indexer(blob_manager, search_manager, section_builder)

    await indexer.index_blob(
        blob_name="content/nerilio/Nerilio-Amsterdam-ZIP-zip/nerilio2.zip",
        content=build_zip({"Doc.xml": PACKAGE_FEED_XML, "8798.jpg": b"jpeg-bytes"}),
    )
    result = await indexer.delete_blob(blob_name="content/nerilio/Nerilio-Amsterdam-ZIP-zip/nerilio2.zip")

    assert result.status == "deleted"
    assert search_manager.removals[-1] == {
        "path": None,
        "category": "publishone2",
        "storage_url_prefix": "https://storage.example.com/content/publishone2/nerilio2/",
    }
    assert sorted(blob_manager.removals) == [
        "publishone2/nerilio2/Doc.xml",
        "publishone2/nerilio2/images/8798.jpg",
    ]


@pytest.mark.asyncio
async def test_a_plain_xml_in_the_archive_feed_behaves_like_publishone() -> None:
    async def section_builder(*, file, file_processors, category, image_bundle=None):
        assert image_bundle is None
        return [object()]

    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = make_publishone2_indexer(blob_manager, search_manager, section_builder)

    result = await indexer.index_blob(
        blob_name="content/nerilio/Nerilio-Amsterdam-ZIP-zip/loose.xml",
        content=PACKAGE_FEED_XML,
        content_type="application/xml",
    )

    assert result.status == "indexed"
    assert result.target_blob_name == "publishone2/loose.xml"
    assert search_manager.removals == [
        {"path": "loose.xml", "category": "publishone2", "storage_url_suffix": "publishone2/loose.xml"}
    ]


@pytest.mark.asyncio
async def test_an_unreadable_archive_is_skipped_without_touching_the_index() -> None:
    async def section_builder(*, file, file_processors, category, image_bundle=None):
        raise AssertionError("must not parse an unreadable archive")

    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = make_publishone2_indexer(blob_manager, search_manager, section_builder)

    result = await indexer.index_blob(
        blob_name="content/nerilio/Nerilio-Amsterdam-ZIP-zip/broken.zip",
        content=b"this is not a zip",
    )

    assert result.status == "skipped-bad-archive"
    assert search_manager.removals == []
    assert blob_manager.uploads == []


@pytest.mark.asyncio
async def test_an_archive_with_no_documents_still_clears_its_prefix() -> None:
    async def section_builder(*, file, file_processors, category, image_bundle=None):
        raise AssertionError("no documents to build sections from")

    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = make_publishone2_indexer(blob_manager, search_manager, section_builder)

    result = await indexer.index_blob(
        blob_name="content/nerilio/Nerilio-Amsterdam-ZIP-zip/images-only.zip",
        content=build_zip({"8798.jpg": b"jpeg-bytes"}),
    )

    assert result.status == "archive-no-content"
    assert len(search_manager.removals) == 1
    assert search_manager.updates == []


@pytest.mark.asyncio
async def test_zip_is_supported_without_a_file_processor_entry() -> None:
    async def section_builder(*, file, file_processors, category, image_bundle=None):
        return []

    indexer = make_publishone2_indexer(MockBlobManager(), MockSearchManager(), section_builder)

    # There is deliberately no ".zip" FileProcessor; the documents inside the archive have one.
    assert indexer.is_supported("nerilio/Nerilio-Amsterdam-ZIP-zip/pkg.zip") is True
    assert indexer.is_archive("nerilio/Nerilio-Amsterdam-ZIP-zip/pkg.zip") is True
    assert indexer.is_supported("nerilio/Nerilio-Amsterdam-ZIP-zip/notes.pdf") is False


@pytest.mark.asyncio
async def test_a_zip_named_xml_is_still_read_as_an_archive() -> None:
    """Real PublishOne exports ship ZIP packages carrying a .xml extension, so archive detection
    falls back to the payload's own magic bytes."""
    captured: list[Any] = []

    async def section_builder(*, file, file_processors, category, image_bundle=None):
        captured.append(file.filename())
        return [object()]

    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = make_publishone2_indexer(blob_manager, search_manager, section_builder)

    result = await indexer.index_blob(
        blob_name="content/nerilio/Nerilio-Amsterdam-ZIP-zip/b8b748e2.xml",
        content=build_zip({"Guidebook.xml": PACKAGE_FEED_XML, "5499.png": b"png-bytes"}),
        content_type="application/xml",
    )

    assert result.status == "indexed"
    assert captured == ["Guidebook.xml"]
    assert {upload["blob_name"] for upload in blob_manager.uploads} == {
        "publishone2/b8b748e2/images/5499.png",
        "publishone2/b8b748e2/Guidebook.xml",
    }


@pytest.mark.asyncio
async def test_deleting_a_zip_named_xml_clears_its_package_prefix() -> None:
    async def section_builder(*, file, file_processors, category, image_bundle=None):
        return [object()]

    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()
    indexer = make_publishone2_indexer(blob_manager, search_manager, section_builder)

    await indexer.index_blob(
        blob_name="content/nerilio/Nerilio-Amsterdam-ZIP-zip/b8b748e2.xml",
        content=build_zip({"Guidebook.xml": PACKAGE_FEED_XML, "5499.png": b"png-bytes"}),
    )
    # On delete the payload is gone, so the package prefix is cleared on extension alone.
    await indexer.delete_blob(blob_name="content/nerilio/Nerilio-Amsterdam-ZIP-zip/b8b748e2.xml")

    assert {
        "path": None,
        "category": "publishone2",
        "storage_url_prefix": "https://storage.example.com/content/publishone2/b8b748e2/",
    } in search_manager.removals
    assert sorted(blob_manager.removals) == [
        "publishone2/b8b748e2/Guidebook.xml",
        "publishone2/b8b748e2/images/5499.png",
    ]


@pytest.mark.asyncio
async def test_deleting_a_plain_document_in_an_archive_feed_still_removes_the_single_file() -> None:
    blob_manager = MockBlobManager()
    search_manager = MockSearchManager()

    async def section_builder(*, file, file_processors, category, image_bundle=None):
        return [object()]

    indexer = make_publishone2_indexer(blob_manager, search_manager, section_builder)

    result = await indexer.delete_blob(blob_name="content/nerilio/Nerilio-Amsterdam-ZIP-zip/loose.xml")

    assert result.status == "deleted"
    assert result.target_blob_name == "publishone2/loose.xml"
    # The speculative package purge runs first and finds nothing; the single-file removal follows.
    assert search_manager.removals[-1] == {
        "path": "loose.xml",
        "category": "publishone2",
        "storage_url_suffix": "publishone2/loose.xml",
    }
    assert blob_manager.removals == ["publishone2/loose.xml"]


@pytest.mark.asyncio
async def test_publishone_feed_never_treats_a_zip_as_an_archive() -> None:
    # Archive mode is opt-in per feed: the publishone feed must reject a stray zip outright.
    indexer = AutoBlobIndexer(
        config=AutoBlobIndexerConfig(
            trigger_container="content",
            source_prefix="nerilio/Nerilio-Amsterdam",
            target_prefix="publishone",
            category="publishone",
            allowed_extensions=frozenset({".xml"}),
        ),
        blob_manager=MockBlobManager(),
        search_manager=MockSearchManager(),
        file_processors={".xml": object()},
    )

    assert indexer.is_archive("nerilio/Nerilio-Amsterdam/pkg.zip") is False
    assert indexer.is_supported("nerilio/Nerilio-Amsterdam/pkg.zip") is False


@pytest.mark.asyncio
async def test_content2_indexer_asks_for_the_provisioned_bot_record_parsers(monkeypatch: pytest.MonkeyPatch) -> None:
    # Both flags together are the content2 contract: never claimed by a built-in bot's category-keyed
    # feed parser (force_generic), but .json/.xml go through the record parsers rather than the
    # generic ones (dynamic_record_parsing).
    captured: dict[str, Any] = {}

    async def fake_parse_file(*args, **kwargs):
        captured.update(kwargs)
        return [object()]

    monkeypatch.setattr("prepdocslib.blobautoindex.parse_file", fake_parse_file)

    indexer = make_content2_indexer(MockBlobManager(), MockSearchManager())
    await indexer.index_blob(blob_name="content2/xba/www.snap.de.json", content=b"[]")

    assert captured["force_generic"] is True
    assert captured["dynamic_record_parsing"] is True
    assert captured["category"] == "xba"


def test_the_deployed_content2_indexer_enables_the_record_parsers() -> None:
    # The Function app builds its own config; a flag set only in the test helper above would ship
    # nothing. prepdocslib is copied into app/functions/* by scripts/copy_prepdocslib.py, so the
    # deployed indexer resolves this module from the backend copy - assert on the real builder.
    from moodle_auto_indexer import function_app

    indexer = function_app.build_content2_auto_indexer(
        blob_manager=MockBlobManager(),
        search_info=SimpleNamespace(index_name="idx", endpoint="https://s.search.windows.net"),
        embeddings=None,
        embedding_field_name="embedding3",
        file_processors={},
    )

    assert indexer.config.dynamic_record_parsing is True
    assert indexer.config.force_generic_parsing is True
