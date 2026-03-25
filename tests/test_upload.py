import base64
from io import BytesIO
from types import SimpleNamespace

import azure.core.exceptions
import azure.storage.blob.aio
import azure.storage.filedatalake
import azure.storage.filedatalake.aio
import pytest
import app
from azure.search.documents.aio import SearchClient
from azure.storage.blob.aio import ContainerClient
from azure.storage.filedatalake.aio import DataLakeDirectoryClient, DataLakeFileClient
from pypdf import PdfWriter
from quart.datastructures import FileStorage

from prepdocslib.embeddings import OpenAIEmbeddings
from prepdocslib.categoryupload import CategoryUploadEntry
from prepdocslib.filestrategy import ChatbotUploadManifest
from prepdocslib.searchmanager import Section
from prepdocslib.textsplitter import Chunk


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


def create_pdf_bytes(page_count: int) -> BytesIO:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=72, height=72)

    pdf_stream = BytesIO()
    writer.write(pdf_stream)
    pdf_stream.seek(0)
    return pdf_stream


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
    file_blob_name = "demo/demo-notes.txt"
    manifest_blob_name = f"demo/.manifests/{filename_token}.json"
    assert response.status_code == 200
    assert payload["uploadedFiles"] == ["demo-notes.txt"]
    assert file_blob_name in uploaded_blob_names
    assert manifest_blob_name in uploaded_blob_names
    assert len(documents_uploaded) == 1
    assert documents_uploaded[0]["id"].endswith(f"-upload-{upload_token}")
    assert documents_uploaded[0]["sourcefile"] == "demo-notes.txt"
    assert documents_uploaded[0]["category"] == "demo"
    assert documents_uploaded[0]["storageUrl"].endswith(file_blob_name)


@pytest.mark.asyncio
async def test_managed_upload_file_uses_category_prefix(client, monkeypatch):
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

    monkeypatch.setattr(OpenAIEmbeddings, "create_embeddings", mock_create_embeddings)
    monkeypatch.setattr(SearchClient, "search", mock_search)
    monkeypatch.setattr(SearchClient, "upload_documents", mock_upload_documents)

    response = await client.post(
        "/managed_uploads",
        headers={"X-Upload-Id": "upload-123"},
        data={"category": "sartorius"},
        files={"files": FileStorage(BytesIO(b"managed upload content"), filename="shared-notes.txt")},
    )

    payload = await response.get_json()
    filename_token = base64.urlsafe_b64encode(b"shared-notes.txt").decode("ascii").rstrip("=")
    version_blob_name = "sartorius/shared-notes.txt"
    manifest_blob_name = f"sartorius/.managed-uploads/manifests/{filename_token}.json"
    assert response.status_code == 200
    assert payload["uploadedFiles"] == [{"category": "sartorius", "filename": "shared-notes.txt"}]
    assert version_blob_name in uploaded_blob_names
    assert manifest_blob_name in uploaded_blob_names
    assert len(documents_uploaded) == 1
    assert documents_uploaded[0]["category"] == "sartorius"
    assert documents_uploaded[0]["sourcefile"] == "shared-notes.txt"
    assert documents_uploaded[0]["storageUrl"].endswith(version_blob_name)


@pytest.mark.asyncio
async def test_list_chatbot_uploaded_files(client, monkeypatch):
    async def mock_exists(*args, **kwargs):
        return True

    monkeypatch.setattr(ContainerClient, "exists", mock_exists)
    alpha_token = base64.urlsafe_b64encode(b"alpha.txt").decode("ascii").rstrip("=")
    monkeypatch.setattr(
        ContainerClient,
        "list_blobs",
        lambda *args, **kwargs: BlobListIterator(
            [
                f"demo/.manifests/{alpha_token}.json",
                "demo/alpha.txt",
                "demo/zeta.pdf",
            ]
        ),
    )

    response = await client.get("/chatbot_uploads/demo")
    assert response.status_code == 200
    assert await response.get_json() == ["alpha.txt", "zeta.pdf"]


@pytest.mark.asyncio
async def test_list_managed_uploaded_files(client, monkeypatch):
    manager = client.app.config[app.CONFIG_CATEGORY_UPLOAD_MANAGER]

    async def mock_list_entries(category=None):
        entries = [
            CategoryUploadEntry(
                category="demo",
                filename="alpha.txt",
                storage_url="https://test.blob.core.windows.net/test-storage-container/demo/alpha.txt",
                uploaded_at="2026-03-25T10:00:00+00:00",
            ),
            CategoryUploadEntry(
                category="sartorius",
                filename="beta.pdf",
                storage_url="https://test.blob.core.windows.net/test-storage-container/sartorius/beta.pdf",
                uploaded_at="2026-03-25T11:00:00+00:00",
            ),
        ]
        if category is None:
            return entries
        return [entry for entry in entries if entry.category == category]

    async def mock_list_categories():
        return ["demo", "sartorius"]

    monkeypatch.setattr(manager, "list_entries", mock_list_entries)
    monkeypatch.setattr(manager, "list_categories", mock_list_categories)

    response = await client.get("/managed_uploads")
    payload = await response.get_json()

    assert response.status_code == 200
    assert payload["categories"] == ["demo", "sartorius"]
    assert payload["files"][0]["category"] == "demo"
    assert payload["files"][1]["category"] == "sartorius"


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
async def test_delete_managed_uploaded_files_by_category(client, monkeypatch):
    manager = client.app.config[app.CONFIG_CATEGORY_UPLOAD_MANAGER]

    async def mock_remove_all_files(category=None):
        assert category == "sartorius"
        return (
            [
                CategoryUploadEntry(
                    category="sartorius",
                    filename="alpha.txt",
                    storage_url="https://test.blob.core.windows.net/test-storage-container/sartorius/alpha.txt",
                    uploaded_at="2026-03-25T10:00:00+00:00",
                )
            ],
            [],
        )

    monkeypatch.setattr(manager, "remove_all_files", mock_remove_all_files)

    response = await client.delete("/managed_uploads?category=sartorius")
    payload = await response.get_json()

    assert response.status_code == 200
    assert payload["deletedFiles"] == [
        {
            "category": "sartorius",
            "filename": "alpha.txt",
            "storage_url": "https://test.blob.core.windows.net/test-storage-container/sartorius/alpha.txt",
            "uploaded_at": "2026-03-25T10:00:00+00:00",
        }
    ]
    assert payload["failedFiles"] == []


@pytest.mark.asyncio
async def test_delete_all_chatbot_uploaded_files(client, monkeypatch):
    existing_blobs = {
        "chatbot-uploads/demo/files/YWxwaGEudHh0/dXBsb2FkLTE/alpha.txt",
        "chatbot-uploads/demo/.manifests/YWxwaGEudHh0.json",
        "chatbot-uploads/demo/files/YmV0YS5wZGY/dXBsb2FkLTI/beta.pdf",
        "chatbot-uploads/demo/.manifests/YmV0YS5wZGY.json",
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

    search_results = {
        "alpha.txt": [
            {
                "id": "file-alpha_txt-page-0",
                "sourcefile": "alpha.txt",
                "category": "demo",
                "storageUrl": "https://test.blob.core.windows.net/test-storage-container/chatbot-uploads/demo/files/YWxwaGEudHh0/dXBsb2FkLTE/alpha.txt",
            }
        ],
        "beta.pdf": [
            {
                "id": "file-beta_pdf-page-0",
                "sourcefile": "beta.pdf",
                "category": "demo",
                "storageUrl": "https://test.blob.core.windows.net/test-storage-container/chatbot-uploads/demo/files/YmV0YS5wZGY/dXBsb2FkLTI/beta.pdf",
            }
        ],
    }

    async def mock_search(self, *args, **kwargs):
        filter_value = kwargs.get("filter") or ""
        if "sourcefile eq 'alpha.txt'" in filter_value:
            return SearchResultsIterator(search_results["alpha.txt"][:])
        if "sourcefile eq 'beta.pdf'" in filter_value:
            return SearchResultsIterator(search_results["beta.pdf"][:])
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

    response = await client.delete("/chatbot_uploads/demo")

    payload = await response.get_json()
    assert response.status_code == 200
    assert payload["deletedFiles"] == ["alpha.txt", "beta.pdf"]
    assert payload["failedFiles"] == []
    assert deleted_documents == [{"id": "file-alpha_txt-page-0"}, {"id": "file-beta_pdf-page-0"}]
    assert deleted_blob_names == [
        "chatbot-uploads/demo/files/YWxwaGEudHh0/dXBsb2FkLTE/alpha.txt",
        "chatbot-uploads/demo/.manifests/YWxwaGEudHh0.json",
        "chatbot-uploads/demo/files/YmV0YS5wZGY/dXBsb2FkLTI/beta.pdf",
        "chatbot-uploads/demo/.manifests/YmV0YS5wZGY.json",
    ]


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
    cancel_marker_name = f"demo/.cancel/{base64.urlsafe_b64encode(b'upload-123').decode('ascii').rstrip('=')}.cancel"
    assert response.status_code == 409
    assert payload["failedFiles"] == [{"filename": "demo-notes.txt", "message": "Upload canceled"}]
    assert uploaded_blob_names == [cancel_marker_name]
    assert deleted_blob_names == [cancel_marker_name]
    assert documents_uploaded == []


@pytest.mark.asyncio
async def test_public_test_rejects_non_pdf_upload(client, monkeypatch):
    async def mock_get_authenticated_public_test_user():
        return SimpleNamespace(email="user@example.com")

    async def mock_exists(*args, **kwargs):
        return True

    class EmptyAsyncSearchResultsIterator:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    async def mock_search(self, *args, **kwargs):
        return EmptyAsyncSearchResultsIterator()

    monkeypatch.setattr(ContainerClient, "exists", mock_exists)
    monkeypatch.setattr(ContainerClient, "list_blobs", lambda *args, **kwargs: BlobListIterator([]))
    monkeypatch.setattr(SearchClient, "search", mock_search)
    monkeypatch.setattr(app, "get_authenticated_public_test_user", mock_get_authenticated_public_test_user)

    response = await client.post(
        "/chatbot_uploads/public-test",
        files={"files": FileStorage(BytesIO(b"demo upload content"), filename="notes.txt")},
    )

    payload = await response.get_json()
    assert response.status_code == 400
    assert payload["message"] == "Unsupported file type: notes.txt"


@pytest.mark.asyncio
async def test_public_test_rejects_pdf_over_total_page_limit(client, monkeypatch):
    async def mock_get_authenticated_public_test_user():
        return SimpleNamespace(email="user@example.com")

    async def mock_exists(*args, **kwargs):
        return True

    class EmptyAsyncSearchResultsIterator:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    async def mock_search(self, *args, **kwargs):
        return EmptyAsyncSearchResultsIterator()

    monkeypatch.setattr(ContainerClient, "exists", mock_exists)
    monkeypatch.setattr(ContainerClient, "list_blobs", lambda *args, **kwargs: BlobListIterator([]))
    monkeypatch.setattr(SearchClient, "search", mock_search)
    monkeypatch.setattr(app, "get_authenticated_public_test_user", mock_get_authenticated_public_test_user)

    response = await client.post(
        "/chatbot_uploads/public-test",
        files={"files": FileStorage(create_pdf_bytes(31), filename="too-many-pages.pdf")},
    )

    payload = await response.get_json()
    assert response.status_code == 400
    assert "allows up to 30 uploaded PDF pages in total" in payload["message"]


@pytest.mark.asyncio
async def test_public_test_rejects_pdf_when_existing_uploads_exceed_total_page_limit(client, monkeypatch):
    async def mock_get_authenticated_public_test_user():
        return SimpleNamespace(email="user@example.com")

    async def mock_exists(*args, **kwargs):
        return True

    class EmptyAsyncSearchResultsIterator:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    async def mock_search(self, *args, **kwargs):
        return EmptyAsyncSearchResultsIterator()

    manager = client.app.config[app.CONFIG_CHATBOT_UPLOAD_MANAGERS]["public-test"]

    async def mock_list_files(user_identifier=None):
        return ["existing.pdf"]

    async def mock_get_manifest(filename: str, user_identifier=None):
        if filename != "existing.pdf":
            return None
        return ChatbotUploadManifest(
            filename="existing.pdf",
            blob_name="chatbot-uploads/public-test/dXNlckBleGFtcGxlLmNvbQ/uploaded-files/files/existing/existing.pdf",
            upload_id="upload-1",
            uploaded_at="2026-03-25T00:00:00+00:00",
            page_count=20,
            file_extension=".pdf",
            user_identifier="user@example.com",
        )

    monkeypatch.setattr(ContainerClient, "exists", mock_exists)
    monkeypatch.setattr(SearchClient, "search", mock_search)
    monkeypatch.setattr(manager, "list_files", mock_list_files)
    monkeypatch.setattr(manager, "get_manifest", mock_get_manifest)
    monkeypatch.setattr(app, "get_authenticated_public_test_user", mock_get_authenticated_public_test_user)

    response = await client.post(
        "/chatbot_uploads/public-test",
        files={"files": FileStorage(create_pdf_bytes(11), filename="new-upload.pdf")},
    )

    payload = await response.get_json()
    assert response.status_code == 400
    assert "Existing uploads use 20 pages and new-upload.pdf adds 11 pages." in payload["message"]


@pytest.mark.asyncio
async def test_public_test_upload_indexes_user_and_uses_user_scoped_blob_path(client, monkeypatch):
    async def mock_get_authenticated_public_test_user():
        return SimpleNamespace(email="person@example.com")

    existing_blobs = set()
    uploaded_blob_names = []

    async def mock_exists(*args, **kwargs):
        return True

    async def mock_upload_blob(self, name, *args, **kwargs):
        uploaded_blob_names.append(name)
        existing_blobs.add(name)
        return None

    class EmptyAsyncSearchResultsIterator:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def get_count(self):
            return 0

    async def mock_search(self, *args, **kwargs):
        return EmptyAsyncSearchResultsIterator()

    async def mock_parse_file(file, *args, **kwargs):
        return [Section(chunk=Chunk(page_num=0, text="private content"), content=file, category="public-test")]

    async def mock_create_embeddings(self, texts):
        return [[0.0023064255, -0.009327292, -0.0028842222] for _ in texts]

    documents_uploaded = []

    async def mock_upload_documents(self, documents):
        documents_uploaded.extend(documents)

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
    monkeypatch.setattr("prepdocslib.filestrategy.parse_file", mock_parse_file)
    monkeypatch.setattr(OpenAIEmbeddings, "create_embeddings", mock_create_embeddings)
    monkeypatch.setattr(SearchClient, "search", mock_search)
    monkeypatch.setattr(SearchClient, "upload_documents", mock_upload_documents)
    monkeypatch.setattr(app, "get_authenticated_public_test_user", mock_get_authenticated_public_test_user)

    response = await client.post(
        "/chatbot_uploads/public-test",
        headers={"X-Upload-Id": "upload-123"},
        files={"files": FileStorage(create_pdf_bytes(2), filename="private-notes.pdf")},
    )

    payload = await response.get_json()
    filename_token = base64.urlsafe_b64encode(b"private-notes.pdf").decode("ascii").rstrip("=")
    user_token = base64.urlsafe_b64encode(b"person@example.com").decode("ascii").rstrip("=")
    file_blob_name = f"public-test/{user_token}/private-notes.pdf"
    manifest_blob_name = f"public-test/{user_token}/.manifests/{filename_token}.json"

    assert response.status_code == 200
    assert payload["uploadedFiles"] == ["private-notes.pdf"]
    assert file_blob_name in uploaded_blob_names
    assert manifest_blob_name in uploaded_blob_names
    assert len(documents_uploaded) == 1
    assert all(document["category"] == "public-test" for document in documents_uploaded)
    assert all(document["user"] == "person@example.com" for document in documents_uploaded)
    assert all(document["storageUrl"].endswith(file_blob_name) for document in documents_uploaded)
