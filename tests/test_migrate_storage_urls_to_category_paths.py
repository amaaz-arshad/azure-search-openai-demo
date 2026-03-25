from migrate_storage_urls_to_category_paths import (
    build_category_blob_name,
    build_storage_url_migrations,
    extract_blob_name_from_storage_url,
)
from prepdocslib.blobmanager import BlobManager

from .mocks import MockAzureCredential


def build_blob_manager() -> BlobManager:
    return BlobManager(
        endpoint="https://teststorage.blob.core.windows.net",
        credential=MockAzureCredential(),
        container="content",
    )


def test_extract_blob_name_from_storage_url():
    assert (
        extract_blob_name_from_storage_url(
            "https://teststorage.blob.core.windows.net/content/a.txt",
            container="content",
        )
        == "a.txt"
    )
    assert (
        extract_blob_name_from_storage_url(
            "https://teststorage.blob.core.windows.net/content/sartorius/a.txt",
            container="content",
        )
        == "sartorius/a.txt"
    )
    assert (
        extract_blob_name_from_storage_url(
            "https://teststorage.blob.core.windows.net/other/a.txt",
            container="content",
        )
        is None
    )


def test_build_category_blob_name():
    assert build_category_blob_name("a.txt", "sartorius") == "sartorius/a.txt"
    assert build_category_blob_name("folder/a.txt", "sartorius") == "sartorius/a.txt"


def test_build_storage_url_migrations_skips_already_prefixed_urls():
    blob_manager = build_blob_manager()
    documents = [
        {
            "id": "1",
            "category": "sartorius",
            "storageUrl": "https://teststorage.blob.core.windows.net/content/a.txt",
        },
        {
            "id": "2",
            "category": "sartorius",
            "storageUrl": "https://teststorage.blob.core.windows.net/content/sartorius/b.txt",
        },
    ]

    migrations = build_storage_url_migrations(documents, blob_manager=blob_manager)

    assert len(migrations) == 1
    assert migrations[0].old_blob_name == "a.txt"
    assert migrations[0].new_blob_name == "sartorius/a.txt"
    assert migrations[0].new_storage_url == "https://teststorage.blob.core.windows.net/content/sartorius/a.txt"
    assert migrations[0].document_ids == ["1"]
