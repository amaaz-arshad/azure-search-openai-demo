from typing import Any

import pytest

from prepdocslib.blobautoindex import AutoBlobIndexer, AutoBlobIndexerConfig, normalize_blob_name


class MockBlobManager:
    def __init__(self) -> None:
        self.uploads: list[dict[str, Any]] = []
        self.removals: list[str] = []
        self.downloads: dict[str, tuple[bytes, dict[str, Any]]] = {}

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

    async def download_blob(self, blob_name: str):
        return self.downloads.get(blob_name)


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
    assert normalize_blob_name("content/nerilio/Nerilio-Moodle/sample.xml", "content") == "nerilio/Nerilio-Moodle/sample.xml"
    assert normalize_blob_name("/content/nerilio/Nerilio-Moodle/sample.xml", "content") == "nerilio/Nerilio-Moodle/sample.xml"


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
