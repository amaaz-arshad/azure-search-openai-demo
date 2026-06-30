from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceNotFoundError

from core.chatbotwikistore import ChatbotWikiStore, normalize_category, normalize_slug


class InMemoryContainerClient:
    def __init__(self):
        self.created = False
        self.blobs: dict[str, bytes] = {}

    async def exists(self):
        return self.created

    async def create_container(self):
        self.created = True

    async def upload_blob(self, blob_name, data, overwrite=False, content_settings=None):
        if not overwrite and blob_name in self.blobs:
            raise ValueError(f"Blob already exists: {blob_name}")
        self.created = True
        payload = data.getvalue() if hasattr(data, "getvalue") else data.read() if hasattr(data, "read") else data
        self.blobs[blob_name] = payload

    async def delete_blob(self, blob_name, delete_snapshots="include"):
        if blob_name not in self.blobs:
            raise ResourceNotFoundError("Blob not found")
        del self.blobs[blob_name]

    def list_blobs(self, name_starts_with=""):
        async def iterator():
            for blob_name in sorted(self.blobs):
                if blob_name.startswith(name_starts_with):
                    yield SimpleNamespace(name=blob_name)

        return iterator()


class InMemoryBlobServiceClient:
    def __init__(self):
        self.containers: dict[str, InMemoryContainerClient] = {}

    def get_container_client(self, container_name: str):
        return self.containers.setdefault(container_name, InMemoryContainerClient())


class InMemoryBlobManager:
    def __init__(self):
        self.blob_service_client = InMemoryBlobServiceClient()

    async def download_blob(self, blob_name: str, user_oid=None, container=None):
        container_client = self.blob_service_client.get_container_client(container)
        if blob_name not in container_client.blobs:
            return None
        return container_client.blobs[blob_name], {"content_settings": {"content_type": "text/markdown"}}


def test_normalize_category_takes_primary_lowercased():
    assert normalize_category("Lemon") == "lemon"
    assert normalize_category("lemon,demo") == "lemon"
    assert normalize_category("  ") is None
    assert normalize_category(None) is None


def test_normalize_slug_rejects_unsafe_values():
    assert normalize_slug("Attention-Mechanism.md") == "attention-mechanism"
    assert normalize_slug("self_attention") is None  # underscores not allowed
    assert normalize_slug("../escape") is None
    assert normalize_slug("a/b") is None
    assert normalize_slug("") is None


@pytest.mark.asyncio
async def test_wiki_store_index_and_page_round_trip():
    store = ChatbotWikiStore(blob_manager=InMemoryBlobManager())

    assert await store.has_wiki("lemon") is False

    await store.save_index("lemon", "# lemon wiki index\n\n- [[intro]] Intro")
    await store.save_page("lemon", "intro", "---\ntitle: Intro\n---\n\nbody")

    assert await store.has_wiki("lemon") is True
    assert "lemon wiki index" in (await store.load_index("lemon") or "")
    assert "body" in (await store.load_page("lemon", "intro") or "")
    assert await store.list_page_slugs("lemon") == ["intro"]


@pytest.mark.asyncio
async def test_wiki_store_missing_returns_none():
    store = ChatbotWikiStore(blob_manager=InMemoryBlobManager())
    assert await store.load_index("lemon") is None
    assert await store.load_page("lemon", "nope") is None
    assert await store.list_page_slugs("lemon") == []


@pytest.mark.asyncio
async def test_wiki_store_rejects_unsafe_slug_on_save():
    store = ChatbotWikiStore(blob_manager=InMemoryBlobManager())
    with pytest.raises(ValueError):
        await store.save_page("lemon", "../escape", "x")


@pytest.mark.asyncio
async def test_wiki_store_load_page_with_unsafe_slug_returns_none():
    store = ChatbotWikiStore(blob_manager=InMemoryBlobManager())
    await store.save_page("lemon", "intro", "body")
    # A malformed slug never resolves to a blob (no path traversal).
    assert await store.load_page("lemon", "../intro") is None


@pytest.mark.asyncio
async def test_wiki_store_category_scoping():
    store = ChatbotWikiStore(blob_manager=InMemoryBlobManager())
    await store.save_page("lemon", "intro", "lemon body")
    await store.save_page("demo", "intro", "demo body")
    assert await store.load_page("lemon", "intro") == "lemon body"
    assert await store.load_page("demo", "intro") == "demo body"
    assert await store.list_page_slugs("lemon") == ["intro"]
