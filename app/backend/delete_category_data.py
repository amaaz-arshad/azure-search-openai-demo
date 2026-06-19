from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import AzureDeveloperCliCredential

from delete_documents_by_category import delete_documents_by_category
from load_azd_env import load_azd_env
from prepdocslib.servicesetup import clean_key_if_exists, setup_blob_manager, setup_search_info

try:
    from rich.logging import RichHandler
except ImportError:  # pragma: no cover - optional dependency for nicer local logs
    RichHandler = None

if TYPE_CHECKING:
    from prepdocslib.blobmanager import BlobManager
    from prepdocslib.strategy import SearchInfo

logger = logging.getLogger("scripts")

CATEGORY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class DeleteCategoryDataResult:
    deleted_documents: int
    deleted_blobs: int
    blob_prefix: str


def normalize_chatbot_category(category: str) -> str:
    normalized = category.strip()
    if not CATEGORY_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Category must start with a letter or digit and contain only letters, digits, hyphens, or underscores."
        )
    return normalized


def normalize_blob_prefix(prefix: str, *, storage_container: str | None = None) -> str:
    normalized = prefix.strip().strip("/\\").replace("\\", "/")
    container = (storage_container or "").strip().strip("/\\")
    if container and normalized == container:
        normalized = ""
    elif container and normalized.startswith(f"{container}/"):
        normalized = normalized[len(container) + 1 :]

    normalized = normalized.strip("/")
    if not normalized:
        raise ValueError("Blob prefix must not be empty.")
    return f"{normalized}/"


async def delete_blobs_with_prefix(blob_manager: BlobManager, prefix: str) -> int:
    blob_names = await blob_manager.list_blob_names(prefix)
    deleted_count = 0

    for blob_name in blob_names:
        logger.info("Removing blob '%s'", blob_name)
        await blob_manager.remove_blob_name(blob_name)
        deleted_count += 1

    if deleted_count == 0:
        logger.info("No blobs found under prefix '%s'", prefix)
    else:
        logger.info("Removed %d blobs under prefix '%s'", deleted_count, prefix)
    return deleted_count


async def delete_category_data(
    *,
    search_info: SearchInfo,
    blob_manager: BlobManager,
    category: str,
    blob_prefix: str,
    batch_size: int = 1000,
    wait_after_delete_seconds: float = 2,
) -> DeleteCategoryDataResult:
    deleted_documents = await delete_documents_by_category(
        search_info,
        category,
        batch_size=batch_size,
        wait_after_delete_seconds=wait_after_delete_seconds,
    )
    deleted_blobs = await delete_blobs_with_prefix(blob_manager, blob_prefix)
    return DeleteCategoryDataResult(
        deleted_documents=deleted_documents,
        deleted_blobs=deleted_blobs,
        blob_prefix=blob_prefix,
    )


async def close_clients(
    *,
    blob_manager: BlobManager | None,
    azure_credential: AsyncTokenCredential | None,
) -> None:
    if blob_manager is not None:
        await blob_manager.close_clients()
    if azure_credential is not None:
        await azure_credential.close()


async def main(args: Any) -> DeleteCategoryDataResult:
    load_azd_env()

    if os.getenv("AZURE_PUBLIC_NETWORK_ACCESS") == "Disabled" and os.getenv("AZURE_USE_VPN_GATEWAY", "").lower() != "true":
        raise RuntimeError("AZURE_PUBLIC_NETWORK_ACCESS is set to Disabled and no VPN gateway is enabled.")

    category = normalize_chatbot_category(args.category)
    storage_container = os.environ["AZURE_STORAGE_CONTAINER"]
    blob_prefix = normalize_blob_prefix(args.blobprefix or category, storage_container=storage_container)

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
            storage_container=storage_container,
            storage_resource_group=os.environ["AZURE_STORAGE_RESOURCE_GROUP"],
            subscription_id=os.environ["AZURE_SUBSCRIPTION_ID"],
            storage_key=clean_key_if_exists(args.storagekey),
            image_storage_container=os.environ.get("AZURE_IMAGESTORAGE_CONTAINER"),
        )
        result = await delete_category_data(
            search_info=search_info,
            blob_manager=blob_manager,
            category=category,
            blob_prefix=blob_prefix,
            batch_size=args.batchsize,
            wait_after_delete_seconds=args.waitseconds,
        )
        logger.info(
            "Deleted %d search documents for category '%s' and %d blobs under 'content/%s'",
            result.deleted_documents,
            category,
            result.deleted_blobs,
            result.blob_prefix,
        )
        return result
    finally:
        await close_clients(blob_manager=blob_manager, azure_credential=azure_credential)


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(
        description=(
            "Delete chatbot/category data from Azure AI Search and from the matching folder in the content storage "
            "container."
        )
    )
    parser.add_argument("category", help="Search category value to remove, usually the chatbot name")
    parser.add_argument(
        "--blobprefix",
        required=False,
        help=(
            "Blob prefix under the content container to delete. Defaults to '<category>/'. "
            "A leading 'content/' container segment is accepted and stripped."
        ),
    )
    parser.add_argument(
        "--batchsize",
        type=int,
        default=1000,
        help="Maximum number of matching search documents to delete per batch",
    )
    parser.add_argument(
        "--waitseconds",
        type=float,
        default=2,
        help="Seconds to wait between search delete batches to allow the index to settle",
    )
    parser.add_argument(
        "--searchkey",
        required=False,
        help="Optional. Azure AI Search key override instead of the current azd identity",
    )
    parser.add_argument(
        "--storagekey",
        required=False,
        help="Optional. Azure Blob Storage key override instead of the current azd identity",
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

    asyncio.run(main(parsed_args))
