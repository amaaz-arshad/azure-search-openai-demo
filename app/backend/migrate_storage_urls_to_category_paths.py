from __future__ import annotations

import argparse
import asyncio
import io
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import unquote, urlparse

from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import AzureDeveloperCliCredential

try:
    from rich.logging import RichHandler
except ImportError:  # pragma: no cover - optional dependency for nicer local logs
    RichHandler = None

from load_azd_env import load_azd_env
from prepdocslib.blobmanager import BlobManager
from prepdocslib.servicesetup import clean_key_if_exists, setup_blob_manager, setup_search_info

if TYPE_CHECKING:
    from prepdocslib.strategy import SearchInfo

logger = logging.getLogger("scripts")


@dataclass(frozen=True)
class StorageUrlMigration:
    category: str
    old_storage_url: str
    old_blob_name: str
    new_blob_name: str
    new_storage_url: str
    document_ids: list[str]


def escape_filter_value(value: str) -> str:
    return value.replace("'", "''")


def extract_blob_name_from_storage_url(storage_url: str, *, container: str) -> Optional[str]:
    parsed = urlparse(storage_url)
    if not parsed.scheme or not parsed.netloc:
        return None

    path = unquote(parsed.path).lstrip("/")
    container_prefix = f"{container}/"
    if not path.startswith(container_prefix):
        return None

    blob_name = path[len(container_prefix) :]
    return blob_name or None


def build_category_blob_name(blob_name: str, category: str) -> str:
    return BlobManager.blob_name_from_file_name(blob_name, prefix=category)


async def list_documents_with_storage_urls(
    search_info: SearchInfo,
    *,
    categories: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    skip = 0
    max_results = 1000

    async with search_info.create_search_client() as search_client:
        while True:
            result = await search_client.search(
                search_text="",
                filter="storageUrl ne ''",
                top=max_results,
                skip=skip,
                select=["id", "category", "storageUrl", "sourcefile"],
            )
            page_documents = [document async for document in result]
            if not page_documents:
                break

            for document in page_documents:
                category = str(document.get("category") or "").strip()
                if not category:
                    continue
                if categories is not None and category not in categories:
                    continue
                storage_url = str(document.get("storageUrl") or "").strip()
                if not storage_url:
                    continue
                documents.append(document)

            if len(page_documents) < max_results:
                break
            skip += max_results

    return documents


def build_storage_url_migrations(
    documents: list[dict[str, Any]],
    *,
    blob_manager: BlobManager,
) -> list[StorageUrlMigration]:
    grouped_document_ids: dict[tuple[str, str, str, str, str], list[str]] = defaultdict(list)
    container_client = blob_manager.blob_service_client.get_container_client(blob_manager.container)

    for document in documents:
        document_id = str(document["id"])
        category = str(document.get("category") or "").strip()
        old_storage_url = str(document.get("storageUrl") or "").strip()
        old_blob_name = extract_blob_name_from_storage_url(old_storage_url, container=blob_manager.container)
        if old_blob_name is None:
            logger.info("Skipping document %s because storageUrl is outside the %s container", document_id, blob_manager.container)
            continue

        new_blob_name = build_category_blob_name(old_blob_name, category)
        new_storage_url = unquote(container_client.get_blob_client(new_blob_name).url)
        if new_storage_url == old_storage_url:
            continue

        grouped_document_ids[(category, old_storage_url, old_blob_name, new_blob_name, new_storage_url)].append(document_id)

    migrations = [
        StorageUrlMigration(
            category=category,
            old_storage_url=old_storage_url,
            old_blob_name=old_blob_name,
            new_blob_name=new_blob_name,
            new_storage_url=new_storage_url,
            document_ids=document_ids,
        )
        for (category, old_storage_url, old_blob_name, new_blob_name, new_storage_url), document_ids in grouped_document_ids.items()
    ]
    migrations.sort(key=lambda migration: (migration.old_blob_name, migration.category))
    return migrations


async def copy_blob(blob_manager: BlobManager, *, source_blob_name: str, target_blob_name: str) -> None:
    download_result = await blob_manager.download_blob(source_blob_name)
    if download_result is None:
        raise FileNotFoundError(f"Blob not found: {source_blob_name}")

    content, properties = download_result
    content_type = properties.get("content_settings", {}).get("content_type")
    await blob_manager.upload_blob_data(io.BytesIO(content), target_blob_name, content_type=content_type)


async def merge_storage_url_updates(
    search_info: SearchInfo,
    *,
    document_ids: list[str],
    new_storage_url: str,
) -> None:
    if not document_ids:
        return

    max_batch_size = 1000
    async with search_info.create_search_client() as search_client:
        for start in range(0, len(document_ids), max_batch_size):
            batch_ids = document_ids[start : start + max_batch_size]
            await search_client.merge_documents(
                documents=[{"id": document_id, "storageUrl": new_storage_url} for document_id in batch_ids]
            )


async def count_documents_for_storage_url(search_info: SearchInfo, storage_url: str) -> int:
    async with search_info.create_search_client() as search_client:
        result = await search_client.search(
            search_text="",
            filter=f"storageUrl eq '{escape_filter_value(storage_url)}'",
            top=0,
            include_total_count=True,
        )
        count = await result.get_count()
        return int(count or 0)


async def run(args: argparse.Namespace) -> None:
    load_azd_env()

    if os.getenv("AZURE_PUBLIC_NETWORK_ACCESS") == "Disabled" and os.getenv("AZURE_USE_VPN_GATEWAY", "").lower() != "true":
        raise RuntimeError("AZURE_PUBLIC_NETWORK_ACCESS is set to Disabled and no VPN gateway is enabled.")

    tenant_id = os.getenv("AZURE_TENANT_ID")
    if tenant_id:
        logger.info("Connecting to Azure services using the azd credential for tenant %s", tenant_id)
        azure_credential = AzureDeveloperCliCredential(tenant_id=tenant_id, process_timeout=60)
    else:
        logger.info("Connecting to Azure services using the azd credential for home tenant")
        azure_credential = AzureDeveloperCliCredential(process_timeout=60)

    blob_manager: BlobManager | None = None
    try:
        search_info = setup_search_info(
            search_service=os.environ["AZURE_SEARCH_SERVICE"],
            index_name=os.environ["AZURE_SEARCH_INDEX"],
            azure_credential=azure_credential,
            search_key=clean_key_if_exists(args.searchkey),
        )
        blob_manager = setup_blob_manager(
            azure_credential=azure_credential,
            storage_account=os.environ["AZURE_STORAGE_ACCOUNT"],
            storage_container=os.environ["AZURE_STORAGE_CONTAINER"],
            storage_resource_group=os.environ["AZURE_STORAGE_RESOURCE_GROUP"],
            subscription_id=os.environ["AZURE_SUBSCRIPTION_ID"],
            storage_key=clean_key_if_exists(args.storagekey),
            image_storage_container=os.environ.get("AZURE_IMAGESTORAGE_CONTAINER"),
        )

        selected_categories = {category.strip() for category in args.categories if category.strip()} if args.categories else None
        documents = await list_documents_with_storage_urls(search_info, categories=selected_categories)
        migrations = build_storage_url_migrations(documents, blob_manager=blob_manager)

        if not migrations:
            logger.info("No storageUrl migrations are needed.")
            return

        logger.info("Prepared %d storageUrl migrations", len(migrations))

        migrated_old_urls: set[str] = set()
        for migration in migrations:
            logger.info(
                "Migrating %d documents for category '%s' from '%s' to '%s'",
                len(migration.document_ids),
                migration.category,
                migration.old_blob_name,
                migration.new_blob_name,
            )

            if args.dryrun:
                continue

            await copy_blob(
                blob_manager,
                source_blob_name=migration.old_blob_name,
                target_blob_name=migration.new_blob_name,
            )
            await merge_storage_url_updates(
                search_info,
                document_ids=migration.document_ids,
                new_storage_url=migration.new_storage_url,
            )
            migrated_old_urls.add(migration.old_storage_url)

        if args.dryrun or args.keepoldblobs:
            return

        for old_storage_url in migrated_old_urls:
            remaining_count = await count_documents_for_storage_url(search_info, old_storage_url)
            if remaining_count > 0:
                logger.info(
                    "Keeping old blob for %s because %d documents still reference it",
                    old_storage_url,
                    remaining_count,
                )
                continue

            old_blob_name = extract_blob_name_from_storage_url(old_storage_url, container=blob_manager.container)
            if old_blob_name is None:
                continue
            await blob_manager.remove_blob_name(old_blob_name)
    finally:
        if blob_manager is not None:
            await blob_manager.close_clients()
        await azure_credential.close()


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Move existing root-level content blobs into category-prefixed paths and update storageUrl values in Azure AI Search."
    )
    parser.add_argument(
        "--categories",
        nargs="*",
        default=None,
        help="Optional list of categories to migrate. If omitted, migrates all documents that have a category.",
    )
    parser.add_argument(
        "--dryrun",
        action="store_true",
        help="Log planned migrations without copying blobs or updating the search index.",
    )
    parser.add_argument(
        "--keepoldblobs",
        action="store_true",
        help="Do not delete the old root-level blobs after storageUrl values have been updated.",
    )
    parser.add_argument(
        "--searchkey",
        required=False,
        help="Optional. Azure AI Search key override instead of the current azd identity.",
    )
    parser.add_argument(
        "--storagekey",
        required=False,
        help="Optional. Azure Blob Storage key override instead of the current azd identity.",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parsed_args = parser.parse_args()

    if parsed_args.verbose:
        if RichHandler is not None:
            logging.basicConfig(format="%(message)s", datefmt="[%X]", handlers=[RichHandler(rich_tracebacks=True)])
        else:
            logging.basicConfig(level=logging.DEBUG, format="%(message)s")
        logger.setLevel(logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    asyncio.run(run(parsed_args))
