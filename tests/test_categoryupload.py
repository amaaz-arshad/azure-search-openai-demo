import base64
from datetime import datetime, timezone
from io import BytesIO

import pytest
from azure.core.credentials import AzureKeyCredential

from prepdocslib.blobmanager import BlobListEntry
from prepdocslib.categoryupload import CategoryUploadStrategy
from prepdocslib.listfilestrategy import File
from prepdocslib.strategy import SearchInfo


def filename_token(filename: str) -> str:
    return base64.urlsafe_b64encode(filename.encode("utf-8")).decode("ascii").rstrip("=")


class FakeBlobManager:
    def __init__(self, blobs=None):
        self.endpoint = "https://test.blob.core.windows.net"
        self.container = "content"
        self.blobs: dict[str, datetime] = dict(blobs or {})
        self.removed: list[str] = []

    async def list_blob_prefixes(self, prefix=None, delimiter="/"):
        return sorted({f"{name.split('/', 1)[0]}/" for name in self.blobs})

    async def list_blobs(self, prefix=None):
        return [
            BlobListEntry(name=name, last_modified=last_modified)
            for name, last_modified in sorted(self.blobs.items())
            if name.startswith(prefix or "")
        ]

    async def blob_exists(self, blob_name):
        return blob_name in self.blobs

    async def remove_blob_name(self, blob_name):
        self.removed.append(blob_name)
        self.blobs.pop(blob_name, None)

    async def download_blob(self, blob_path):
        return None

    async def upload_blob_data(self, file, blob_name, content_type=None):
        self.blobs[blob_name] = datetime(2026, 7, 3, tzinfo=timezone.utc)
        return f"{self.endpoint}/{self.container}/{blob_name}"


class FakeSearchManager:
    def __init__(self, facet_categories=None, documents=None):
        self.facet_categories = list(facet_categories or [])
        self.documents = list(documents or [])
        self.deleted_ids: list[str] = []
        self.list_calls: list[dict] = []
        self.updated_sections: list = []

    async def list_category_facets(self):
        return list(self.facet_categories)

    async def list_documents(self, path=None, category=None, storage_url=None, user=None):
        self.list_calls.append({"path": path, "category": category, "storage_url": storage_url})
        return [
            document
            for document in self.documents
            if storage_url is None or document.get("storageUrl") == storage_url
        ]

    async def delete_documents_by_ids(self, document_ids):
        self.deleted_ids.extend(document_ids)
        remaining_ids = set(document_ids)
        self.documents = [document for document in self.documents if document["id"] not in remaining_ids]

    async def update_content(self, sections, url=None, document_id_suffix=None):
        self.updated_sections.extend(sections)


def make_manager(blobs, facet_categories=(), documents=(), known_categories=(), file_processors=None):
    manager = CategoryUploadStrategy(
        search_info=SearchInfo(
            endpoint="https://search.test",
            credential=AzureKeyCredential("key"),
            index_name="test-index",
        ),
        file_processors=file_processors or {},
        blob_manager=FakeBlobManager(blobs),
        known_categories=set(known_categories),
    )
    manager.search_manager = FakeSearchManager(facet_categories=facet_categories, documents=documents)
    return manager


LAST_MODIFIED = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_list_entries_shows_files_from_all_ingestion_paths():
    blobs = {
        # Feed auto-indexer mirror and script-ingested files: no managed manifests.
        "moodle/kurs.xml": LAST_MODIFIED,
        "snap/snap.json": LAST_MODIFIED,
        # Admin managed upload with its manifest.
        f"steuertipps/handbuch.pdf": LAST_MODIFIED,
        f"steuertipps/.managed-uploads/manifests/{filename_token('handbuch.pdf')}.json": LAST_MODIFIED,
        # Per-bot chatbot upload with its own manifest style.
        "demo/notes.txt": LAST_MODIFIED,
        f"demo/.manifests/{filename_token('notes.txt')}.json": LAST_MODIFIED,
        # Feed source drop: nested, must not surface.
        "nerilio/Nerilio-Moodle/kurs.xml": LAST_MODIFIED,
        # User-scoped chatbot uploads: nested, must not surface.
        "free/dXNlcg/upload.pdf": LAST_MODIFIED,
        # Infrastructure prefixes: not known, not indexed, no manifests.
        "hyrox-assessment-logs/run1.json": LAST_MODIFIED,
        "prompts/demo.json": LAST_MODIFIED,
    }
    manager = make_manager(
        blobs,
        facet_categories=["moodle", "snap", "steuertipps", "demo"],
        known_categories=["moodle", "snap", "steuertipps", "demo", "free"],
    )

    entries = await manager.list_entries()

    assert {(entry.category, entry.filename) for entry in entries} == {
        ("moodle", "kurs.xml"),
        ("snap", "snap.json"),
        ("steuertipps", "handbuch.pdf"),
        ("demo", "notes.txt"),
    }
    for entry in entries:
        assert entry.storage_url == (
            f"https://test.blob.core.windows.net/content/{entry.category}/{entry.filename}"
        )
        assert entry.uploaded_at == LAST_MODIFIED.isoformat()

    assert await manager.list_category_counts() == {"demo": 1, "moodle": 1, "snap": 1, "steuertipps": 1}
    # Explicitly requesting a non-content prefix must not expose it either.
    assert await manager.list_entries(category="hyrox-assessment-logs") == []


@pytest.mark.asyncio
async def test_list_entries_gates_unknown_categories_on_index_and_manifests():
    blobs = {
        # Unknown category, but present in the search index.
        "customcat/data.json": LAST_MODIFIED,
        # Unknown category with a managed-upload manifest (legacy admin upload).
        "cbtx/doc.pdf": LAST_MODIFIED,
        f"cbtx/.managed-uploads/manifests/{filename_token('doc.pdf')}.json": LAST_MODIFIED,
        # Unknown category with neither: hidden.
        "junk/x.json": LAST_MODIFIED,
    }
    manager = make_manager(blobs, facet_categories=["customcat"])

    entries = await manager.list_entries()

    assert {(entry.category, entry.filename) for entry in entries} == {
        ("customcat", "data.json"),
        ("cbtx", "doc.pdf"),
    }


@pytest.mark.asyncio
async def test_list_entries_survives_search_facet_failure():
    blobs = {"moodle/kurs.xml": LAST_MODIFIED}
    manager = make_manager(blobs, known_categories=["moodle"])

    async def failing_facets():
        raise RuntimeError("search unavailable")

    manager.search_manager.list_category_facets = failing_facets

    entries = await manager.list_entries()
    assert [(entry.category, entry.filename) for entry in entries] == [("moodle", "kurs.xml")]


@pytest.mark.asyncio
async def test_remove_file_without_manifest_deletes_documents_blob_and_sibling_manifest():
    storage_url = "https://test.blob.core.windows.net/content/demo/notes.txt"
    sibling_manifest = f"demo/.manifests/{filename_token('notes.txt')}.json"
    blobs = {
        "demo/notes.txt": LAST_MODIFIED,
        sibling_manifest: LAST_MODIFIED,
    }
    documents = [
        {"id": "script-1", "storageUrl": storage_url},
        {"id": "script-2", "storageUrl": storage_url},
        {"id": "other", "storageUrl": "https://test.blob.core.windows.net/content/demo/other.txt"},
    ]
    manager = make_manager(blobs, documents=documents, known_categories=["demo"])

    await manager.remove_file("notes.txt", "demo")

    assert manager.search_manager.deleted_ids == ["script-1", "script-2"]
    assert all(call["storage_url"] for call in manager.search_manager.list_calls)
    assert "demo/notes.txt" in manager.blob_manager.removed
    assert sibling_manifest in manager.blob_manager.removed
    assert "demo/notes.txt" not in manager.blob_manager.blobs


@pytest.mark.asyncio
async def test_add_file_replaces_documents_from_other_ingestion_paths(monkeypatch):
    storage_url = "https://test.blob.core.windows.net/content/demo/notes.txt"
    blobs = {"demo/notes.txt": LAST_MODIFIED}
    documents = [{"id": "script-1", "storageUrl": storage_url}]
    manager = make_manager(
        blobs,
        documents=documents,
        known_categories=["demo"],
        file_processors={".txt": object()},
    )

    async def fake_parse_file(file, file_processors, category=None, check_cancel=None):
        return [object()]

    monkeypatch.setattr("prepdocslib.categoryupload.parse_file", fake_parse_file)

    content = BytesIO(b"new content")
    content.name = "notes.txt"
    result = await manager.add_file(File(content=content), category="demo", upload_id="upload-1")

    assert result.replaced_existing is True
    assert result.entry.category == "demo"
    assert result.entry.filename == "notes.txt"
    assert manager.search_manager.deleted_ids == ["script-1"]
    assert manager.search_manager.updated_sections
    manifest_blob_name = f"demo/.managed-uploads/manifests/{filename_token('notes.txt')}.json"
    assert manifest_blob_name in manager.blob_manager.blobs
