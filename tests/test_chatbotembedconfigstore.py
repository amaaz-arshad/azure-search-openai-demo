from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceNotFoundError

from core.chatbotembedconfigstore import ChatbotEmbedConfigStore


class InMemoryContainerClient:
    def __init__(self):
        self.created = False
        self.blobs: dict[str, bytes] = {}

    async def exists(self):
        return self.created

    async def create_container(self):
        self.created = True

    async def upload_blob(self, blob_name, data, overwrite=False, content_settings=None):
        self.created = True
        payload = data.getvalue() if hasattr(data, "getvalue") else data
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
        return container_client.blobs[blob_name], {"content_settings": {"content_type": "application/json"}}


@pytest.mark.asyncio
async def test_save_and_load_round_trip_normalizes_rules():
    store = ChatbotEmbedConfigStore(blob_manager=InMemoryBlobManager())

    saved = await store.save_rules("Publishone", ["https://*.snap.de", "*.snap.de", "publishone.snap.de/Preise.html"])
    assert saved.chatbot_name == "publishone"
    assert saved.allowed_rules == ["*.snap.de", "publishone.snap.de/Preise.html"]  # scheme stripped + deduped

    loaded = await store.load_config("publishone")
    assert loaded is not None
    assert loaded.allowed_rules == saved.allowed_rules
    assert await store.load_allowed_rules("publishone") == saved.allowed_rules


@pytest.mark.asyncio
async def test_empty_rules_clears_the_record():
    store = ChatbotEmbedConfigStore(blob_manager=InMemoryBlobManager())

    await store.save_rules("demo", ["*.snap.de"])
    cleared = await store.save_rules("demo", ["   ", ""])

    assert cleared.allowed_rules == []
    assert await store.load_config("demo") is None
    assert await store.load_allowed_rules("demo") == []


@pytest.mark.asyncio
async def test_missing_config_is_allow_all():
    store = ChatbotEmbedConfigStore(blob_manager=InMemoryBlobManager())
    assert await store.load_config("knoll") is None
    assert await store.load_allowed_rules("knoll") == []
