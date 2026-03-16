from argparse import Namespace

import pytest

import delete_documents_by_category as delete_module


class FakeSearchClient:
    def __init__(self, result_pages: list[list[dict[str, str]]]) -> None:
        self.result_pages = list(result_pages)
        self.search_calls: list[dict[str, object]] = []
        self.deleted_batches: list[list[dict[str, str]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def search(self, *, search_text: str, filter: str, top: int, select: list[str]):
        self.search_calls.append(
            {"search_text": search_text, "filter": filter, "top": top, "select": select}
        )
        documents = self.result_pages.pop(0)

        async def iterator():
            for document in documents:
                yield document

        return iterator()

    async def delete_documents(self, documents: list[dict[str, str]]) -> None:
        self.deleted_batches.append(documents)


class FakeSearchInfo:
    def __init__(self, search_client: FakeSearchClient) -> None:
        self.search_client = search_client

    def create_search_client(self) -> FakeSearchClient:
        return self.search_client


@pytest.mark.asyncio
async def test_delete_documents_by_category_removes_documents_in_batches() -> None:
    search_client = FakeSearchClient(
        [
            [{"id": "one"}, {"id": "two"}],
            [{"id": "three"}],
            [],
        ]
    )

    deleted_count = await delete_module.delete_documents_by_category(
        FakeSearchInfo(search_client),
        "fhg",
        batch_size=2,
        wait_after_delete_seconds=0,
    )

    assert deleted_count == 3
    assert search_client.deleted_batches == [
        [{"id": "one"}, {"id": "two"}],
        [{"id": "three"}],
    ]
    assert [call["filter"] for call in search_client.search_calls] == [
        "category eq 'fhg'",
        "category eq 'fhg'",
        "category eq 'fhg'",
    ]
    assert search_client.search_calls[0]["top"] == 2
    assert search_client.search_calls[0]["select"] == ["id"]


@pytest.mark.asyncio
async def test_delete_documents_by_category_escapes_single_quotes() -> None:
    search_client = FakeSearchClient([[]])

    deleted_count = await delete_module.delete_documents_by_category(
        FakeSearchInfo(search_client),
        "men's health",
        wait_after_delete_seconds=0,
    )

    assert deleted_count == 0
    assert search_client.search_calls[0]["filter"] == "category eq 'men''s health'"


@pytest.mark.asyncio
async def test_main_passes_search_key_and_closes_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_SEARCH_SERVICE", "searchsvc")
    monkeypatch.setenv("AZURE_SEARCH_INDEX", "searchindex")

    monkeypatch.setattr(delete_module, "load_azd_env", lambda: None)

    captured: dict[str, object] = {}

    class DummyAzureCredential:
        def __init__(self, *args, **kwargs) -> None:
            captured["credential_kwargs"] = kwargs

        async def close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(delete_module, "AzureDeveloperCliCredential", DummyAzureCredential)

    def fake_setup_search_info(*, search_service: str, index_name: str, azure_credential, search_key: str | None):
        captured["search_service"] = search_service
        captured["index_name"] = index_name
        captured["search_key"] = search_key
        captured["azure_credential"] = azure_credential
        return "search-info"

    async def fake_delete_documents_by_category(search_info, category: str, **kwargs) -> int:
        captured["search_info"] = search_info
        captured["category"] = category
        captured["delete_kwargs"] = kwargs
        return 4

    monkeypatch.setattr(delete_module, "setup_search_info", fake_setup_search_info)
    monkeypatch.setattr(delete_module, "delete_documents_by_category", fake_delete_documents_by_category)

    result = await delete_module.main(
        Namespace(
            category="fhg",
            batchsize=250,
            waitseconds=0.5,
            searchkey="secret",
        )
    )

    assert result == 4
    assert captured["search_service"] == "searchsvc"
    assert captured["index_name"] == "searchindex"
    assert captured["search_key"] == "secret"
    assert captured["search_info"] == "search-info"
    assert captured["category"] == "fhg"
    assert captured["delete_kwargs"] == {"batch_size": 250, "wait_after_delete_seconds": 0.5}
    assert captured["closed"] is True
