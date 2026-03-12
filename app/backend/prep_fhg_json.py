from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import AzureDeveloperCliCredential
from azure.storage.blob import ContentSettings
from openai import AsyncOpenAI

try:
    from rich.logging import RichHandler
except ImportError:  # pragma: no cover - optional dependency for nicer local logs
    RichHandler = None

from load_azd_env import load_azd_env

DEFAULT_SOURCEPAGE_PREFIX = "fhg"

if TYPE_CHECKING:
    from prepdocslib.blobmanager import BlobManager
    from prepdocslib.embeddings import OpenAIEmbeddings
    from prepdocslib.fhgjson import FhgPreparedDataset
    from prepdocslib.strategy import SearchInfo

logger = logging.getLogger("scripts")


async def upload_source_blobs(blob_manager: BlobManager, dataset: FhgPreparedDataset) -> None:
    container_client = blob_manager.blob_service_client.get_container_client(blob_manager.container)
    if not await container_client.exists():
        await container_client.create_container()

    for source_blob in dataset.source_blobs:
        logger.info("Uploading FHG source blob '%s'", source_blob.name)
        await container_client.upload_blob(
            source_blob.name,
            source_blob.text.encode("utf-8"),
            overwrite=True,
            content_settings=ContentSettings(content_type="text/plain; charset=utf-8"),
        )


async def remove_blobs_with_prefix(blob_manager: BlobManager, prefix: str) -> None:
    container_client = blob_manager.blob_service_client.get_container_client(blob_manager.container)
    if not await container_client.exists():
        return

    async for blob_name in container_client.list_blob_names(name_starts_with=prefix):
        logger.info("Removing existing FHG source blob '%s'", blob_name)
        await container_client.delete_blob(blob_name)


async def remove_existing_category(search_info: SearchInfo, category: str) -> None:
    escaped_category = category.replace("'", "''")
    async with search_info.create_search_client() as search_client:
        while True:
            results = await search_client.search(search_text="", filter=f"category eq '{escaped_category}'", top=1000)
            documents_to_remove = [{"id": document["id"]} async for document in results]
            if not documents_to_remove:
                break

            logger.info("Removing %d existing documents for category '%s'", len(documents_to_remove), category)
            await search_client.delete_documents(documents_to_remove)
            await asyncio.sleep(2)


async def upload_dataset_documents(
    search_info: SearchInfo,
    dataset: FhgPreparedDataset,
    embeddings: OpenAIEmbeddings,
    embedding_field_name: str,
    global_acls: dict[str, list[str]],
) -> None:
    max_batch_size = 1000
    async with search_info.create_search_client() as search_client:
        for offset in range(0, len(dataset.documents), max_batch_size):
            batch = dataset.documents[offset : offset + max_batch_size]
            documents = [document.to_search_document(global_acls) for document in batch]
            vectors = await embeddings.create_embeddings([document["content"] for document in documents])

            for index, document in enumerate(documents):
                document[embedding_field_name] = vectors[index]

            logger.info(
                "Uploading FHG batch %d with %d documents to index '%s'",
                (offset // max_batch_size) + 1,
                len(documents),
                search_info.index_name,
            )
            await search_client.upload_documents(documents)


async def close_clients(
    *,
    blob_manager: BlobManager | None,
    openai_client: AsyncOpenAI | None,
    azure_credential: AsyncTokenCredential | None,
) -> None:
    if blob_manager is not None:
        await blob_manager.close_clients()
    if openai_client is not None:
        await openai_client.close()
    if azure_credential is not None:
        await azure_credential.close()


async def run(args: argparse.Namespace) -> None:
    from prepdocslib.fhgjson import prepare_fhg_dataset
    from prepdocslib.searchmanager import SearchManager
    from prepdocslib.servicesetup import (
        OpenAIHost,
        clean_key_if_exists,
        setup_blob_manager,
        setup_embeddings_service,
        setup_openai_client,
        setup_search_info,
    )

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
    openai_client: AsyncOpenAI | None = None
    try:
        search_info = setup_search_info(
            search_service=os.environ["AZURE_SEARCH_SERVICE"],
            index_name=os.environ["AZURE_SEARCH_INDEX"],
            use_agentic_knowledgebase=os.getenv("USE_AGENTIC_KNOWLEDGEBASE", "").lower() == "true",
            knowledgebase_name=os.getenv("AZURE_SEARCH_KNOWLEDGEBASE_NAME"),
            azure_openai_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            azure_openai_knowledgebase_deployment=os.getenv("AZURE_OPENAI_KNOWLEDGEBASE_DEPLOYMENT"),
            azure_openai_knowledgebase_model=os.getenv("AZURE_OPENAI_KNOWLEDGEBASE_MODEL"),
            azure_credential=azure_credential,
            search_key=clean_key_if_exists(args.searchkey),
            azure_vision_endpoint=os.getenv("AZURE_VISION_ENDPOINT"),
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

        openai_host = OpenAIHost(os.environ["OPENAI_HOST"])
        openai_client, azure_openai_endpoint = setup_openai_client(
            openai_host=openai_host,
            azure_credential=azure_credential,
            azure_openai_service=os.getenv("AZURE_OPENAI_SERVICE"),
            azure_openai_custom_url=os.getenv("AZURE_OPENAI_CUSTOM_URL"),
            azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY_OVERRIDE"),
            openai_api_key=clean_key_if_exists(os.getenv("OPENAI_API_KEY")),
            openai_organization=os.getenv("OPENAI_ORGANIZATION"),
        )

        emb_model_dimensions = int(os.getenv("AZURE_OPENAI_EMB_DIMENSIONS", "1536"))
        embedding_field_name = os.getenv("AZURE_SEARCH_FIELD_NAME_EMBEDDING", "embedding")
        embeddings = setup_embeddings_service(
            openai_host,
            openai_client,
            emb_model_name=os.environ["AZURE_OPENAI_EMB_MODEL_NAME"],
            emb_model_dimensions=emb_model_dimensions,
            azure_openai_deployment=os.getenv("AZURE_OPENAI_EMB_DEPLOYMENT"),
            azure_openai_endpoint=azure_openai_endpoint,
            disable_batch=args.disablebatchvectors,
        )

        use_acls = os.getenv("AZURE_USE_AUTHENTICATION", "").lower() == "true"
        enforce_access_control = os.getenv("AZURE_ENFORCE_ACCESS_CONTROL", "").lower() == "true"
        enable_global_documents = os.getenv("AZURE_ENABLE_GLOBAL_DOCUMENT_ACCESS", "").lower() == "true"
        global_acls = {"oids": ["all"], "groups": ["all"]} if enable_global_documents else {}

        search_manager = SearchManager(
            search_info=search_info,
            search_analyzer_name=os.getenv("AZURE_SEARCH_ANALYZER_NAME"),
            use_acls=use_acls,
            embeddings=embeddings,
            field_name_embedding=embedding_field_name,
            search_images=False,
            enforce_access_control=enforce_access_control,
        )
        await search_manager.create_index()

        dataset_path = Path(args.file)
        payload = json.loads(dataset_path.read_text(encoding="utf-8"))
        prepared_dataset = prepare_fhg_dataset(
            payload,
            dataset_filename=dataset_path.name,
            category=args.category,
            sourcepage_prefix=args.sourceprefix,
        )

        if not args.preserveexisting:
            await remove_existing_category(search_info, args.category)
            await remove_blobs_with_prefix(blob_manager, f"{args.sourceprefix}/")

        await upload_source_blobs(blob_manager, prepared_dataset)
        await upload_dataset_documents(
            search_info=search_info,
            dataset=prepared_dataset,
            embeddings=embeddings,
            embedding_field_name=embedding_field_name,
            global_acls=global_acls,
        )

        logger.info(
            "Indexed %d FHG search documents and uploaded %d source blobs",
            len(prepared_dataset.documents),
            len(prepared_dataset.source_blobs),
        )
    finally:
        await close_clients(blob_manager=blob_manager, openai_client=openai_client, azure_credential=azure_credential)


if __name__ == "__main__":  # pragma: no cover
    default_dataset_path = Path(__file__).resolve().parents[2] / "data" / "fhg_alle_studien_20260310.json"
    parser = argparse.ArgumentParser(
        description="Ingest the FHG studies JSON file into Azure AI Search with FHG-specific chunking and embeddings."
    )
    parser.add_argument(
        "file",
        nargs="?",
        default=str(default_dataset_path),
        help="Path to the FHG JSON file to ingest",
    )
    parser.add_argument("--category", default="fhg", help="Category value to set in the search index")
    parser.add_argument(
        "--sourceprefix",
        default=DEFAULT_SOURCEPAGE_PREFIX,
        help="Blob path prefix used for generated source documents",
    )
    parser.add_argument(
        "--preserveexisting",
        action="store_true",
        help="Do not purge existing documents and source blobs for this category before indexing",
    )
    parser.add_argument(
        "--disablebatchvectors",
        action="store_true",
        help="Do not batch embedding requests when generating vectors",
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

    asyncio.run(run(parsed_args))
