import base64
from io import BytesIO
from types import SimpleNamespace

import azure.core.exceptions
import azure.storage.blob.aio
import azure.storage.filedatalake
import azure.storage.filedatalake.aio
import pytest
from azure.search.documents.aio import SearchClient
from azure.storage.blob.aio import ContainerClient
from azure.storage.filedatalake.aio import DataLakeDirectoryClient, DataLakeFileClient
from quart.datastructures import FileStorage

from prepdocslib.embeddings import OpenAIEmbeddings


class BlobListIterator:
    def __init__(self, names):
        self.names = [SimpleNamespace(name=name) for name in names]

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.names:
            raise StopAsyncIteration
        return self.names.pop(0)


class MockBlobClient:
    def __init__(self, name: str, existing_blobs: set[str]):
        self.name = name
        self.url = f"https://test.blob.core.windows.net/test-storage-container/{name}"
        self.existing_blobs = existing_blobs

    async def exists(self):
        return self.name in self.existing_blobs


@pytest.mark.asyncio
@pytest.mark.parametrize("directory_exists", [True, False])
async def test_upload_file(auth_client, monkeypatch, mock_data_lake_service_client, directory_exists):

    # Create a mock class for DataLakeDirectoryClient that includes the _client attribute
    class MockDataLakeDirectoryClient:
        def __init__(self, *args, **kwargs):
            self._client = object()  # Mock the _client attribute
            self.url = "https://test.blob.core.windows.net/container/path"

        async def get_directory_properties(self, *args, **kwargs):
            if directory_exists:
                return {"name": "test-directory"}
            else:
                raise azure.core.exceptions.ResourceNotFoundError()

        async def create_directory(self, *args, **kwargs):
            directory_created[0] = True
            return None

        async def set_access_control(self, *args, **kwargs):
            assert kwargs.get("owner") == "OID_X"
            return None

        async def get_access_control(self, *args, **kwargs):
            return {"owner": "OID_X"}

        def get_file_client(self, *args, **kwargs):
            return azure.storage.filedatalake.aio.DataLakeFileClient(
                account_url="https://test.blob.core.windows.net/", file_system_name="user-content", file_path=args[0]
            )

    # Replace the DataLakeDirectoryClient with our mock
    monkeypatch.setattr(
        azure.storage.filedatalake.aio.FileSystemClient,
        "get_directory_client",
        lambda *args, **kwargs: MockDataLakeDirectoryClient(),
    )

    directory_created = [False]

    async def mock_upload_file(self, *args, **kwargs):
        assert kwargs.get("overwrite") is True
        return None

    monkeypatch.setattr(DataLakeFileClient, "upload_data", mock_upload_file)

    async def mock_create_embeddings(self, texts):
        return [[0.0023064255, -0.009327292, -0.0028842222] for _ in texts]

    documents_uploaded = []

    async def mock_upload_documents(self, documents):
        documents_uploaded.extend(documents)

    monkeypatch.setattr(SearchClient, "upload_documents", mock_upload_documents)
    monkeypatch.setattr(OpenAIEmbeddings, "create_embeddings", mock_create_embeddings)

    response = await auth_client.post(
        "/upload",
        headers={"Authorization": "Bearer test"},
        files={"file": FileStorage(BytesIO(b"foo;bar"), filename="a.txt")},
    )
    message = (await response.get_json())["message"]
    assert message == "File uploaded successfully"
    assert response.status_code == 200
    assert len(documents_uploaded) == 1
    assert documents_uploaded[0]["id"] == "file-a_txt-612E7478747B276F696473273A205B274F49445F58275D7D-page-0"
    assert documents_uploaded[0]["sourcepage"] == "a.txt"
    assert documents_uploaded[0]["sourcefile"] == "a.txt"
    assert documents_uploaded[0]["embedding"] == [0.0023064255, -0.009327292, -0.0028842222]
    assert documents_uploaded[0]["category"] is None
    assert documents_uploaded[0]["oids"] == ["OID_X"]
    assert directory_created[0] == (not directory_exists)


@pytest.mark.asyncio
async def test_upload_file_error_wrong_directory_owner(auth_client, monkeypatch, mock_data_lake_service_client):

    # Create a mock class for DataLakeDirectoryClient that includes the _client attribute
    class MockDataLakeDirectoryClient:
        def __init__(self, *args, **kwargs):
            self._client = object()
            self.url = "https://test.blob.core.windows.net/container/path"

        async def get_directory_properties(self, *args, **kwargs):
            return {"name": "test-directory"}

        async def get_access_control(self, *args, **kwargs):
            return {"owner": "OID_Y"}

    # Replace the DataLakeDirectoryClient with our mock
    monkeypatch.setattr(
        azure.storage.filedatalake.aio.FileSystemClient,
        "get_directory_client",
        lambda *args, **kwargs: MockDataLakeDirectoryClient(),
    )

    response = await auth_client.post(
        "/upload",
        headers={"Authorization": "Bearer test"},
        files={"file": FileStorage(BytesIO(b"foo;bar"), filename="a.txt")},
    )
    message = (await response.get_json())["message"]
    assert message == "Error uploading file, check server logs for details."
    assert response.status_code == 500


@pytest.mark.asyncio
async def test_list_uploaded(auth_client, monkeypatch, mock_data_lake_service_client):
    response = await auth_client.get("/list_uploaded", headers={"Authorization": "Bearer test"})
    assert response.status_code == 200
    assert (await response.get_json()) == ["a.txt", "b.txt", "c.txt"]


@pytest.mark.asyncio
async def test_list_uploaded_nopaths(auth_client, monkeypatch, mock_data_lake_service_client):
    class MockResponse:
        def __init__(self):
            self.reason = "No path found"
            self.status_code = 404

    class MockAsyncIteratorError:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise azure.core.exceptions.ResourceNotFoundError(
                response=azure.core.exceptions.HttpResponseError(response=MockResponse())
            )

    def mock_get_paths(self, *args, **kwargs):
        return MockAsyncIteratorError()

    monkeypatch.setattr(azure.storage.filedatalake.aio.FileSystemClient, "get_paths", mock_get_paths)

    response = await auth_client.get("/list_uploaded", headers={"Authorization": "Bearer test"})
    assert response.status_code == 200
    assert (await response.get_json()) == []


@pytest.mark.asyncio
async def test_delete_uploaded(auth_client, monkeypatch, mock_data_lake_service_client):

    async def mock_delete_file(self):
        return None

    monkeypatch.setattr(DataLakeFileClient, "delete_file", mock_delete_file)

    def mock_directory_get_file_client(self, *args, **kwargs):
        return azure.storage.filedatalake.aio.DataLakeFileClient(
            account_url="https://test.blob.core.windows.net/", file_system_name="user-content", file_path=args[0]
        )

    monkeypatch.setattr(DataLakeDirectoryClient, "get_file_client", mock_directory_get_file_client)

    class AsyncSearchResultsIterator:
        def __init__(self):
            self.results = [
                {
                    "sourcepage": "a's doc.txt",
                    "sourcefile": "a's doc.txt",
                    "content": "This is a test document.",
                    "embedding": [],
                    "category": None,
                    "id": "file-a_txt-7465737420646F63756D656E742E706466",
                    "oids": ["OID_X"],
                    "@search.score": 0.03279569745063782,
                    "@search.reranker_score": 3.4577205181121826,
                },
                {
                    "sourcepage": "a's doc.txt",
                    "sourcefile": "a's doc.txt",
                    "content": "This is a test document.",
                    "embedding": [],
                    "category": None,
                    "id": "file-a_txt-7465737420646F63756D656E742E706422",
                    "oids": [],
                    "@search.score": 0.03279569745063782,
                    "@search.reranker_score": 3.4577205181121826,
                },
                {
                    "sourcepage": "a's doc.txt",
                    "sourcefile": "a's doc.txt",
                    "content": "This is a test document.",
                    "embedding": [],
                    "category": None,
                    "id": "file-a_txt-7465737420646F63756D656E742E706433",
                    "oids": ["OID_X", "OID_Y"],
                    "@search.score": 0.03279569745063782,
                    "@search.reranker_score": 3.4577205181121826,
                },
            ]

        def __aiter__(self):
            return self

        async def __anext__(self):
            if len(self.results) == 0:
                raise StopAsyncIteration
            return self.results.pop()

        async def get_count(self):
            return len(self.results)

    search_results = AsyncSearchResultsIterator()

    searched_filters = []

    async def mock_search(self, *args, **kwargs):
        self.filter = kwargs.get("filter")
        searched_filters.append(self.filter)
        return search_results

    monkeypatch.setattr(SearchClient, "search", mock_search)

    deleted_documents = []
    deleted_directories = []

    async def mock_delete_documents(self, documents):
        deleted_documents.extend(documents)
        return documents

    monkeypatch.setattr(SearchClient, "delete_documents", mock_delete_documents)

    async def mock_delete_directory(self):
        deleted_directories.append("mock_directory_url")
        return None

    monkeypatch.setattr(DataLakeDirectoryClient, "delete_directory", mock_delete_directory)

    response = await auth_client.post(
        "/delete_uploaded", headers={"Authorization": "Bearer test"}, json={"filename": "a's doc.txt"}
    )
    assert response.status_code == 200
    assert len(searched_filters) == 2, "It should have searched twice (with no results on second try)"
    assert searched_filters[0] == "sourcefile eq 'a''s doc.txt'"
    assert len(deleted_documents) == 1, "It should have only deleted the document solely owned by OID_X"
    assert deleted_documents[0]["id"] == "file-a_txt-7465737420646F63756D656E742E706466"
    assert len(deleted_directories) == 1, "It should have deleted the directory for the file"


@pytest.mark.asyncio
async def test_chatbot_upload_file(client, monkeypatch):
    existing_blobs = set()
    uploaded_blob_names = []

    async def mock_exists(*args, **kwargs):
        return True

    async def mock_upload_blob(self, name, *args, **kwargs):
        uploaded_blob_names.append(name)
        existing_blobs.add(name)
        return None

    monkeypatch.setattr(ContainerClient, "exists", mock_exists)
    monkeypatch.setattr(ContainerClient, "upload_blob", mock_upload_blob)
    monkeypatch.setattr(
        ContainerClient,
        "get_blob_client",
        lambda *args, **kwargs: MockBlobClient(args[1], existing_blobs),
    )
    monkeypatch.setattr(
        ContainerClient,
        "list_blobs",
        lambda *args, **kwargs: BlobListIterator(
            [name for name in existing_blobs if name.startswith(kwargs.get("name_starts_with", ""))]
        ),
    )

    async def mock_create_embeddings(self, texts):
        return [[0.0023064255, -0.009327292, -0.0028842222] for _ in texts]

    documents_uploaded = []

    async def mock_upload_documents(self, documents):
        documents_uploaded.extend(documents)

    monkeypatch.setattr(SearchClient, "upload_documents", mock_upload_documents)
    monkeypatch.setattr(OpenAIEmbeddings, "create_embeddings", mock_create_embeddings)

    class EmptyAsyncSearchResultsIterator:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def get_count(self):
            return 0

    async def mock_search(self, *args, **kwargs):
        return EmptyAsyncSearchResultsIterator()

    monkeypatch.setattr(SearchClient, "search", mock_search)

    response = await client.post(
        "/chatbot_uploads/demo",
        headers={"X-Upload-Id": "upload-123"},
        files={"files": FileStorage(BytesIO(b"demo upload content"), filename="demo-notes.txt")},
    )

    payload = await response.get_json()
    filename_token = base64.urlsafe_b64encode(b"demo-notes.txt").decode("ascii").rstrip("=")
    upload_token = base64.urlsafe_b64encode(b"upload-123").decode("ascii").rstrip("=")
    version_blob_name = f"chatbot-uploads/demo/files/{filename_token}/{upload_token}/demo-notes.txt"
    manifest_blob_name = f"chatbot-uploads/demo/.manifests/{filename_token}.json"
    assert response.status_code == 200
    assert payload["uploadedFiles"] == ["demo-notes.txt"]
    assert version_blob_name in uploaded_blob_names
    assert manifest_blob_name in uploaded_blob_names
    assert len(documents_uploaded) == 1
    assert documents_uploaded[0]["id"].endswith(f"-upload-{upload_token}")
    assert documents_uploaded[0]["sourcefile"] == "demo-notes.txt"
    assert documents_uploaded[0]["category"] == "demo"
    assert documents_uploaded[0]["storageUrl"].endswith(version_blob_name)


@pytest.mark.asyncio
async def test_list_chatbot_uploaded_files(client, monkeypatch):
    async def mock_exists(*args, **kwargs):
        return True

    monkeypatch.setattr(ContainerClient, "exists", mock_exists)
    alpha_token = base64.urlsafe_b64encode(b"alpha.txt").decode("ascii").rstrip("=")
    upload_token = base64.urlsafe_b64encode(b"upload-1").decode("ascii").rstrip("=")
    monkeypatch.setattr(
        ContainerClient,
        "list_blobs",
        lambda *args, **kwargs: BlobListIterator(
            [
                f"chatbot-uploads/demo/.manifests/{alpha_token}.json",
                f"chatbot-uploads/demo/files/{alpha_token}/{upload_token}/alpha.txt",
                "chatbot-uploads/demo/zeta.pdf",
            ]
        ),
    )

    response = await client.get("/chatbot_uploads/demo")
    assert response.status_code == 200
    assert await response.get_json() == ["alpha.txt", "zeta.pdf"]


@pytest.mark.asyncio
async def test_delete_chatbot_uploaded_file(client, monkeypatch):
    existing_blobs = {
        "chatbot-uploads/demo/files/ZGVtby1ub3Rlcy50eHQ/dXBsb2FkLTE/demo-notes.txt",
        "chatbot-uploads/demo/.manifests/ZGVtby1ub3Rlcy50eHQ.json",
    }

    async def mock_exists(*args, **kwargs):
        return True

    deleted_blob_names = []

    async def mock_delete_blob(self, blob_name, *args, **kwargs):
        deleted_blob_names.append(blob_name)
        existing_blobs.discard(blob_name)
        return None

    class SearchResultsIterator:
        def __init__(self, documents):
            self.documents = documents

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.documents:
                raise StopAsyncIteration
            return self.documents.pop(0)

        async def get_count(self):
            return len(self.documents)

    searched_filters = []
    search_calls = {"count": 0}

    async def mock_search(self, *args, **kwargs):
        searched_filters.append(kwargs.get("filter"))
        search_calls["count"] += 1
        if search_calls["count"] == 1:
            return SearchResultsIterator(
                [
                    {
                        "id": "file-demo_notes_txt-page-0",
                        "sourcefile": "demo-notes.txt",
                        "category": "demo",
                        "storageUrl": "https://test.blob.core.windows.net/test-storage-container/chatbot-uploads/demo/demo-notes.txt",
                    },
                    {
                        "id": "file-built_in_demo_notes_txt-page-0",
                        "sourcefile": "demo-notes.txt",
                        "category": "demo",
                        "storageUrl": "https://test.blob.core.windows.net/test-storage-container/demo/demo-notes.txt",
                    }
                ]
            )
        return SearchResultsIterator([])

    deleted_documents = []

    async def mock_delete_documents(self, documents):
        deleted_documents.extend(documents)
        return documents

    monkeypatch.setattr(ContainerClient, "exists", mock_exists)
    monkeypatch.setattr(ContainerClient, "delete_blob", mock_delete_blob)
    monkeypatch.setattr(
        ContainerClient,
        "get_blob_client",
        lambda *args, **kwargs: MockBlobClient(args[1], existing_blobs),
    )
    monkeypatch.setattr(
        ContainerClient,
        "list_blobs",
        lambda *args, **kwargs: BlobListIterator(
            [name for name in existing_blobs if name.startswith(kwargs.get("name_starts_with", ""))]
        ),
    )
    monkeypatch.setattr(SearchClient, "search", mock_search)
    monkeypatch.setattr(SearchClient, "delete_documents", mock_delete_documents)

    response = await client.delete("/chatbot_uploads/demo/demo-notes.txt")

    assert response.status_code == 200
    assert deleted_blob_names == [
        "chatbot-uploads/demo/files/ZGVtby1ub3Rlcy50eHQ/dXBsb2FkLTE/demo-notes.txt",
        "chatbot-uploads/demo/.manifests/ZGVtby1ub3Rlcy50eHQ.json",
    ]
    assert searched_filters[0] == "sourcefile eq 'demo-notes.txt' and category eq 'demo'"
    assert deleted_documents == [{"id": "file-demo_notes_txt-page-0"}]


@pytest.mark.asyncio
async def test_chatbot_upload_rejects_filename_conflict_with_builtin_demo_content(client, monkeypatch):
    async def mock_exists(*args, **kwargs):
        return True

    async def mock_search(self, *args, **kwargs):
        class SearchResultsIterator:
            def __init__(self):
                self.documents = [
                    {
                        "id": "file-built_in_demo_notes_txt-page-0",
                        "sourcefile": "demo-notes.txt",
                        "category": "demo",
                        "storageUrl": "https://test.blob.core.windows.net/test-storage-container/demo/demo-notes.txt",
                    }
                ]

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self.documents:
                    raise StopAsyncIteration
                return self.documents.pop(0)

        return SearchResultsIterator()

    monkeypatch.setattr(ContainerClient, "exists", mock_exists)
    monkeypatch.setattr(SearchClient, "search", mock_search)

    response = await client.post(
        "/chatbot_uploads/demo",
        files={"files": FileStorage(BytesIO(b"demo upload content"), filename="demo-notes.txt")},
    )

    payload = await response.get_json()
    assert response.status_code == 400
    assert "conflicts with existing demo content" in payload["message"]


@pytest.mark.asyncio
async def test_cancel_chatbot_upload_prevents_indexing(client, monkeypatch):
    existing_blobs = set()
    uploaded_blob_names = []
    deleted_blob_names = []

    async def mock_exists(*args, **kwargs):
        return True

    async def mock_upload_blob(self, name, *args, **kwargs):
        uploaded_blob_names.append(name)
        existing_blobs.add(name)
        return None

    async def mock_delete_blob(self, blob_name, *args, **kwargs):
        deleted_blob_names.append(blob_name)
        existing_blobs.discard(blob_name)
        return None

    monkeypatch.setattr(ContainerClient, "exists", mock_exists)
    monkeypatch.setattr(ContainerClient, "upload_blob", mock_upload_blob)
    monkeypatch.setattr(ContainerClient, "delete_blob", mock_delete_blob)
    monkeypatch.setattr(
        ContainerClient,
        "get_blob_client",
        lambda *args, **kwargs: MockBlobClient(args[1], existing_blobs),
    )
    monkeypatch.setattr(
        ContainerClient,
        "list_blobs",
        lambda *args, **kwargs: BlobListIterator(
            [name for name in existing_blobs if name.startswith(kwargs.get("name_starts_with", ""))]
        ),
    )

    class EmptyAsyncSearchResultsIterator:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def get_count(self):
            return 0

    async def mock_search(self, *args, **kwargs):
        return EmptyAsyncSearchResultsIterator()

    documents_uploaded = []

    async def mock_upload_documents(self, documents):
        documents_uploaded.extend(documents)

    monkeypatch.setattr(SearchClient, "search", mock_search)
    monkeypatch.setattr(SearchClient, "upload_documents", mock_upload_documents)

    cancel_response = await client.post("/chatbot_uploads/demo/cancel/upload-123")
    assert cancel_response.status_code == 202

    response = await client.post(
        "/chatbot_uploads/demo",
        headers={"X-Upload-Id": "upload-123"},
        files={"files": FileStorage(BytesIO(b"demo upload content"), filename="demo-notes.txt")},
    )

    payload = await response.get_json()
    cancel_marker_name = f"chatbot-uploads/demo/.cancel/{base64.urlsafe_b64encode(b'upload-123').decode('ascii').rstrip('=')}.cancel"
    assert response.status_code == 409
    assert payload["failedFiles"] == [{"filename": "demo-notes.txt", "message": "Upload canceled"}]
    assert uploaded_blob_names == [cancel_marker_name]
    assert deleted_blob_names == [cancel_marker_name]
    assert documents_uploaded == []
