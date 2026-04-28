from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.identity.aio import AzureDeveloperCliCredential
from openai import AsyncOpenAI

from load_azd_env import load_azd_env
from prepdocslib.listfilestrategy import File

RichLoggingHandler: type[Any] | None
try:
    from rich.logging import RichHandler

    RichLoggingHandler = RichHandler
except ImportError:  # pragma: no cover - optional dependency for nicer local logs
    RichLoggingHandler = None

DEFAULT_CATEGORY = "lemon"
DEFAULT_BLOB_PREFIX = "lemon"

if TYPE_CHECKING:
    from prepdocslib.blobmanager import BlobManager
    from prepdocslib.searchmanager import SearchManager
    from prepdocslib.strategy import SearchInfo

logger = logging.getLogger("scripts")


async def upload_dataset_blob(blob_manager: BlobManager, dataset_path: Path, blob_prefix: str) -> str:
    normalized_prefix = blob_prefix.strip("/")
    blob_name = f"{normalized_prefix}/{dataset_path.name}" if normalized_prefix else dataset_path.name
    logger.info("Uploading raw HYROX dataset blob '%s'", blob_name)
    with dataset_path.open("rb") as dataset_file:
        return await blob_manager.upload_blob_data(
            dataset_file,
            blob_name,
            content_type="application/json; charset=utf-8",
        )


async def resolve_embedding_settings(
    search_info: SearchInfo,
    configured_field_name: str,
    configured_dimensions: int,
) -> tuple[str, int]:
    try:
        async with search_info.create_search_index_client() as search_index_client:
            existing_index = await search_index_client.get_index(search_info.index_name)
    except ResourceNotFoundError:
        return configured_field_name, configured_dimensions

    vector_fields = [
        field for field in existing_index.fields if getattr(field, "vector_search_dimensions", None) is not None
    ]
    if not vector_fields:
        return configured_field_name, configured_dimensions

    if any(field.name == configured_field_name for field in vector_fields):
        matching_field = next(field for field in vector_fields if field.name == configured_field_name)
        return configured_field_name, int(matching_field.vector_search_dimensions or configured_dimensions)

    if len(vector_fields) == 1:
        inferred_field = vector_fields[0]
        inferred_dimensions = int(inferred_field.vector_search_dimensions or configured_dimensions)
        logger.info(
            "Using existing vector field '%s' with %d dimensions from index '%s'",
            inferred_field.name,
            inferred_dimensions,
            search_info.index_name,
        )
        return inferred_field.name, inferred_dimensions

    logger.warning(
        "Configured embedding field '%s' not found in index '%s'; falling back to configured settings",
        configured_field_name,
        search_info.index_name,
    )
    return configured_field_name, configured_dimensions


async def remove_existing_hyrox_documents(
    search_manager: SearchManager,
    *,
    dataset_filename: str,
    category: str,
) -> None:
    await search_manager.remove_content(path=dataset_filename, category=category)


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
    from prepdocslib.hyroxjson import prepare_hyrox_sections
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

    if (
        os.getenv("AZURE_PUBLIC_NETWORK_ACCESS") == "Disabled"
        and os.getenv("AZURE_USE_VPN_GATEWAY", "").lower() != "true"
    ):
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

        configured_embedding_field_name = os.getenv("AZURE_SEARCH_FIELD_NAME_EMBEDDING", "embedding")
        configured_emb_dimensions = int(os.getenv("AZURE_OPENAI_EMB_DIMENSIONS", "1536"))
        embedding_field_name, emb_model_dimensions = await resolve_embedding_settings(
            search_info,
            configured_embedding_field_name,
            configured_emb_dimensions,
        )
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

        with dataset_path.open("rb") as dataset_file:
            file = File(dataset_file, acls=global_acls)
            sections = prepare_hyrox_sections(payload, file=file, category=args.category)

        if not args.preserveexisting:
            await remove_existing_hyrox_documents(
                search_manager,
                dataset_filename=dataset_path.name,
                category=args.category,
            )

        dataset_storage_url = await upload_dataset_blob(blob_manager, dataset_path, args.sourceprefix.strip("/"))
        await search_manager.update_content(sections, url=dataset_storage_url)

        logger.info(
            "Indexed %d HYROX search documents and uploaded raw dataset blob to %s",
            len(sections),
            dataset_storage_url,
        )
    finally:
        await close_clients(blob_manager=blob_manager, openai_client=openai_client, azure_credential=azure_credential)


if __name__ == "__main__":  # pragma: no cover
    default_dataset_path = Path(__file__).resolve().parents[2] / "data" / "HYROX_Level_1.json"
    parser = argparse.ArgumentParser(
        description="Ingest the HYROX Level 1 JSON file into Azure AI Search with HYROX-specific mapping."
    )
    parser.add_argument(
        "file",
        nargs="?",
        default=str(default_dataset_path),
        help="Path to the HYROX Level 1 JSON file to ingest",
    )
    parser.add_argument("--category", default=DEFAULT_CATEGORY, help="Category value to set in the search index")
    parser.add_argument(
        "--sourceprefix",
        default=DEFAULT_BLOB_PREFIX,
        help="Blob path prefix under the content container for the uploaded raw HYROX dataset file",
    )
    parser.add_argument(
        "--preserveexisting",
        action="store_true",
        help="Do not purge existing HYROX documents for this file/category before indexing",
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
        if RichLoggingHandler is not None:
            logging.basicConfig(
                format="%(message)s",
                datefmt="[%X]",
                handlers=[RichLoggingHandler(rich_tracebacks=True)],
            )
        else:
            logging.basicConfig(level=logging.DEBUG, format="%(message)s")
        logger.setLevel(logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    asyncio.run(run(parsed_args))
