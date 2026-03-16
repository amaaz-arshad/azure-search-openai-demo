from __future__ import annotations

import argparse
import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import AzureDeveloperCliCredential

try:
    from rich.logging import RichHandler
except ImportError:  # pragma: no cover - optional dependency for nicer local logs
    RichHandler = None

from load_azd_env import load_azd_env
from prepdocslib.servicesetup import clean_key_if_exists, setup_search_info

if TYPE_CHECKING:
    from prepdocslib.strategy import SearchInfo

logger = logging.getLogger("scripts")


async def delete_documents_by_category(
    search_info: SearchInfo,
    category: str,
    *,
    batch_size: int = 1000,
    wait_after_delete_seconds: float = 2,
) -> int:
    escaped_category = category.replace("'", "''")
    deleted_count = 0

    async with search_info.create_search_client() as search_client:
        while True:
            results = await search_client.search(
                search_text="",
                filter=f"category eq '{escaped_category}'",
                top=batch_size,
                select=["id"],
            )
            documents_to_remove = [{"id": document["id"]} async for document in results]
            if not documents_to_remove:
                break

            logger.info("Removing %d existing documents for category '%s'", len(documents_to_remove), category)
            await search_client.delete_documents(documents_to_remove)
            deleted_count += len(documents_to_remove)

            if wait_after_delete_seconds > 0:
                await asyncio.sleep(wait_after_delete_seconds)

    if deleted_count == 0:
        logger.info("No documents found for category '%s'", category)
    else:
        logger.info("Removed %d documents for category '%s'", deleted_count, category)

    return deleted_count


async def main(args: Any) -> int:
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

    try:
        search_info = setup_search_info(
            search_service=os.environ["AZURE_SEARCH_SERVICE"],
            index_name=os.environ["AZURE_SEARCH_INDEX"],
            azure_credential=azure_credential,
            search_key=clean_key_if_exists(args.searchkey),
        )
        return await delete_documents_by_category(
            search_info,
            args.category,
            batch_size=args.batchsize,
            wait_after_delete_seconds=args.waitseconds,
        )
    finally:
        await azure_credential.close()


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(description="Delete all Azure AI Search documents matching a category value.")
    parser.add_argument("category", help="Category value to remove from the Azure AI Search index")
    parser.add_argument(
        "--batchsize",
        type=int,
        default=1000,
        help="Maximum number of matching documents to delete per batch",
    )
    parser.add_argument(
        "--waitseconds",
        type=float,
        default=2,
        help="Seconds to wait between delete batches to allow the index to settle",
    )
    parser.add_argument(
        "--searchkey",
        required=False,
        help="Optional. Azure AI Search key override instead of the current azd identity",
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
