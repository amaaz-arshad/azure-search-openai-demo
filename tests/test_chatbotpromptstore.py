from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceNotFoundError

from core.chatbotpromptstore import ChatbotPromptStore


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
        if user_oid is not None:
            raise AssertionError("user_oid should not be set in these prompt-store tests")

        container_client = self.blob_service_client.get_container_client(container)
        if blob_name not in container_client.blobs:
            return None
        return container_client.blobs[blob_name], {"content_settings": {"content_type": "application/json"}}


@pytest.mark.asyncio
async def test_prompt_store_save_and_load_round_trip():
    store = ChatbotPromptStore(blob_manager=InMemoryBlobManager())

    saved_prompt = await store.save_prompt("Demo", "You are a runtime prompt.")
    loaded_prompt = await store.load_prompt("demo")

    assert saved_prompt is not None
    assert saved_prompt.chatbot_name == "demo"
    assert loaded_prompt == saved_prompt


@pytest.mark.asyncio
async def test_prompt_store_rejects_blank_prompt():
    store = ChatbotPromptStore(blob_manager=InMemoryBlobManager())

    with pytest.raises(ValueError, match="Prompt cannot be empty."):
        await store.save_prompt("demo", "   ")


@pytest.mark.asyncio
async def test_prompt_store_same_as_default_deletes_existing_override():
    store = ChatbotPromptStore(blob_manager=InMemoryBlobManager())

    saved_prompt = await store.save_prompt("demo", "You are an override.")
    assert saved_prompt is not None

    collapsed_prompt = await store.save_prompt("demo", "You are the default.", default_prompt="You are the default.")

    assert collapsed_prompt is None
    assert await store.load_prompt("demo") is None


@pytest.mark.asyncio
async def test_prompt_store_lists_saved_overrides():
    store = ChatbotPromptStore(blob_manager=InMemoryBlobManager())

    await store.save_prompt("demo", "Demo override")
    await store.save_prompt("nerilio", "Nerilio override")

    prompts = await store.list_prompts()

    assert sorted(prompts) == ["demo", "nerilio"]
    assert prompts["demo"].prompt == "Demo override"
    assert prompts["nerilio"].prompt == "Nerilio override"
