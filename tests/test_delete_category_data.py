from argparse import Namespace

import pytest

import delete_category_data as delete_data


class FakeBlobManager:
    def __init__(self, blob_names: list[str]) -> None:
        self.blob_names = blob_names
        self.listed_prefixes: list[str] = []
        self.removed: list[str] = []
        self.closed = False

    async def list_blob_names(self, prefix: str) -> list[str]:
        self.listed_prefixes.append(prefix)
        return [blob_name for blob_name in self.blob_names if blob_name.startswith(prefix)]

    async def remove_blob_name(self, blob_name: str) -> None:
        self.removed.append(blob_name)

    async def close_clients(self) -> None:
        self.closed = True


def test_normalize_chatbot_category_accepts_chatbot_names() -> None:
    assert delete_data.normalize_chatbot_category("fhg") == "fhg"
    assert delete_data.normalize_chatbot_category("hyrox-assessment") == "hyrox-assessment"
    assert delete_data.normalize_chatbot_category("vjoonk4") == "vjoonk4"


def test_normalize_chatbot_category_rejects_unsafe_values() -> None:
    with pytest.raises(ValueError, match="Category must start"):
        delete_data.normalize_chatbot_category("../fhg")


def test_normalize_blob_prefix_defaults_to_folder_under_content_container() -> None:
    assert delete_data.normalize_blob_prefix("fhg", storage_container="content") == "fhg/"
    assert delete_data.normalize_blob_prefix("/content/fhg/", storage_container="content") == "fhg/"
    assert delete_data.normalize_blob_prefix("publishone/custom", storage_container="content") == "publishone/custom/"


@pytest.mark.asyncio
async def test_delete_blobs_with_prefix_removes_only_matching_folder() -> None:
    blob_manager = FakeBlobManager(["fhg/data.json", "fhg/nested/file.json", "fhg-other/file.json"])

    deleted_count = await delete_data.delete_blobs_with_prefix(blob_manager, "fhg/")

    assert deleted_count == 2
    assert blob_manager.listed_prefixes == ["fhg/"]
    assert blob_manager.removed == ["fhg/data.json", "fhg/nested/file.json"]


@pytest.mark.asyncio
async def test_delete_category_data_deletes_search_docs_and_storage_blobs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_delete_documents_by_category(search_info, category: str, **kwargs) -> int:
        captured["search_info"] = search_info
        captured["category"] = category
        captured["delete_kwargs"] = kwargs
        return 7

    monkeypatch.setattr(delete_data, "delete_documents_by_category", fake_delete_documents_by_category)
    blob_manager = FakeBlobManager(["fhg/data.json", "other/data.json"])

    result = await delete_data.delete_category_data(
        search_info="search-info",
        blob_manager=blob_manager,
        category="fhg",
        blob_prefix="fhg/",
        batch_size=250,
        wait_after_delete_seconds=0.25,
    )

    assert result == delete_data.DeleteCategoryDataResult(
        deleted_documents=7,
        deleted_blobs=1,
        blob_prefix="fhg/",
    )
    assert captured == {
        "search_info": "search-info",
        "category": "fhg",
        "delete_kwargs": {"batch_size": 250, "wait_after_delete_seconds": 0.25},
    }
    assert blob_manager.removed == ["fhg/data.json"]


@pytest.mark.asyncio
async def test_main_sets_up_search_and_storage_and_closes_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_SEARCH_SERVICE", "searchsvc")
    monkeypatch.setenv("AZURE_SEARCH_INDEX", "searchindex")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT", "storageacct")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "content")
    monkeypatch.setenv("AZURE_STORAGE_RESOURCE_GROUP", "storagerg")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "subid")

    monkeypatch.setattr(delete_data, "load_azd_env", lambda: None)

    captured: dict[str, object] = {}

    class DummyAzureCredential:
        def __init__(self, *args, **kwargs) -> None:
            captured["credential_kwargs"] = kwargs
            self.closed = False

        async def close(self) -> None:
            self.closed = True
            captured["credential_closed"] = True

    monkeypatch.setattr(delete_data, "AzureDeveloperCliCredential", DummyAzureCredential)

    def fake_setup_search_info(*, search_service: str, index_name: str, azure_credential, search_key: str | None):
        captured["search_service"] = search_service
        captured["index_name"] = index_name
        captured["search_key"] = search_key
        captured["search_credential"] = azure_credential
        return "search-info"

    blob_manager = FakeBlobManager(["fhg/data.json"])

    def fake_setup_blob_manager(**kwargs):
        captured["blob_kwargs"] = kwargs
        return blob_manager

    async def fake_delete_category_data(**kwargs):
        captured["delete_category_data_kwargs"] = kwargs
        return delete_data.DeleteCategoryDataResult(deleted_documents=3, deleted_blobs=1, blob_prefix="fhg/")

    monkeypatch.setattr(delete_data, "setup_search_info", fake_setup_search_info)
    monkeypatch.setattr(delete_data, "setup_blob_manager", fake_setup_blob_manager)
    monkeypatch.setattr(delete_data, "delete_category_data", fake_delete_category_data)

    result = await delete_data.main(
        Namespace(
            category="fhg",
            blobprefix="content/fhg",
            batchsize=500,
            waitseconds=0,
            searchkey="search-secret",
            storagekey="storage-secret",
        )
    )

    assert result == delete_data.DeleteCategoryDataResult(deleted_documents=3, deleted_blobs=1, blob_prefix="fhg/")
    assert captured["search_service"] == "searchsvc"
    assert captured["index_name"] == "searchindex"
    assert captured["search_key"] == "search-secret"
    assert captured["blob_kwargs"]["storage_account"] == "storageacct"
    assert captured["blob_kwargs"]["storage_container"] == "content"
    assert captured["blob_kwargs"]["storage_key"] == "storage-secret"
    assert captured["delete_category_data_kwargs"]["category"] == "fhg"
    assert captured["delete_category_data_kwargs"]["blob_prefix"] == "fhg/"
    assert captured["delete_category_data_kwargs"]["batch_size"] == 500
    assert captured["delete_category_data_kwargs"]["wait_after_delete_seconds"] == 0
    assert blob_manager.closed is True
    assert captured["credential_closed"] is True
