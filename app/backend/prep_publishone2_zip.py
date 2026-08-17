"""Manually ingest a publishone2 package (ZIP or plain feed XML).

The `publishone2` drop folder is normally watched by the `publishone2_auto_index` Azure Function.
This script drives the *same* AutoBlobIndexer archive path from a local file, which makes it both a
re-ingest command and the way to verify the whole pipeline — ZIP expansion, image description,
blob mirroring, indexing — without deploying the function.

    python app/backend/prep_publishone2_zip.py data/nerilio2.zip
    python app/backend/prep_publishone2_zip.py data/nerilio2.zip --dry-run   # describe + print only

`--dry-run` calls the vision model but writes nothing to blob storage or the search index, so it is
the cheap way to see exactly what text an image will contribute to the index.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import AzureDeveloperCliCredential
from openai import AsyncOpenAI

from load_azd_env import load_azd_env

RichLoggingHandler: type[Any] | None
try:
    from rich.logging import RichHandler

    RichLoggingHandler = RichHandler
except ImportError:  # pragma: no cover - optional dependency for nicer local logs
    RichLoggingHandler = None

DEFAULT_CATEGORY = "publishone2"
DEFAULT_TARGET_PREFIX = "publishone2"
DEFAULT_SOURCE_PREFIX = "nerilio/Nerilio-Amsterdam-ZIP-zip"
DEFAULT_IMAGE_MODEL = "gpt-4.1"

if TYPE_CHECKING:
    from prepdocslib.blobmanager import BlobManager

logger = logging.getLogger("scripts")


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


def build_describer(openai_client: AsyncOpenAI, args: argparse.Namespace):
    from prepdocslib.mediadescriber import FEED_IMAGE_DESCRIPTION_PROMPT, MultimodalModelDescriber
    from prepdocslib.servicesetup import OpenAIHost

    if args.no_images:
        logger.info("Image description disabled; images will be mirrored but not transcribed")
        return None

    is_azure = OpenAIHost(os.environ["OPENAI_HOST"]) == OpenAIHost.AZURE
    return MultimodalModelDescriber(
        openai_client=openai_client,
        model=args.image_model,
        deployment=(args.image_deployment or args.image_model) if is_azure else None,
        prompt=FEED_IMAGE_DESCRIPTION_PROMPT,
        max_tokens=args.image_max_tokens,
    )


async def run_dry_run(args: argparse.Namespace, openai_client: AsyncOpenAI, azure_credential) -> None:
    """Expand, describe and render — printing the exact text that would be indexed."""
    from prepdocslib.feedarchive import build_image_bundle, describe_archive_images, expand_feed_archive
    from prepdocslib.listfilestrategy import File
    from prepdocslib.publishonefeed import build_publishone_feed_sections
    from prepdocslib.servicesetup import build_file_processors

    # Feed content is routinely non-ASCII (German umlauts, combining accents) and the Windows
    # console defaults to cp1252, which would abort the print rather than the ingest.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")

    package_path = Path(args.file)
    file_processors = build_file_processors(
        azure_credential=azure_credential,
        document_intelligence_service=None,
        use_local_pdf_parser=True,
        use_local_html_parser=True,
    )

    if package_path.suffix.lower() == ".zip":
        archive = expand_feed_archive(package_path.read_bytes())
        descriptions = await describe_archive_images(
            archive.images.values(),
            describer=build_describer(openai_client, args),
            concurrency=args.image_concurrency,
            max_images=args.image_max_per_archive,
        )
        bundle = build_image_bundle(
            archive.images.values(),
            descriptions,
            target_prefix=args.targetprefix,
            package_name=package_path.stem,
        )
        documents = [(document.name, document.data) for document in archive.documents]
        logger.info(
            "Archive '%s': %d document(s), %d image(s), %d described",
            package_path.name,
            len(documents),
            len(archive.images),
            len(descriptions),
        )
    else:
        bundle = None
        documents = [(package_path.name, package_path.read_bytes())]

    for name, data in documents:
        stream = io.BytesIO(data)
        stream.name = name
        sections = await build_publishone_feed_sections(
            file=File(content=stream),
            file_processors=file_processors,
            category=args.category,
            image_bundle=bundle,
        )
        for section in sections:
            print("=" * 100)
            print(f"{name} | id={section.id} | sourcepage={section.sourcepage} | url={section.url}")
            print("-" * 100)
            print(section.chunk.text)


async def run_ingest(args: argparse.Namespace, openai_client: AsyncOpenAI, azure_credential) -> None:
    from prepdocslib.blobautoindex import AutoBlobIndexer, AutoBlobIndexerConfig
    from prepdocslib.feedarchive import BlobImageDescriptionCache, FeedArchiveOptions
    from prepdocslib.publishonefeed import build_publishone_feed_sections
    from prepdocslib.searchmanager import SearchManager
    from prepdocslib.servicesetup import (
        OpenAIHost,
        build_file_processors,
        clean_key_if_exists,
        setup_blob_manager,
        setup_embeddings_service,
        setup_search_info,
    )

    package_path = Path(args.file)
    blob_manager: BlobManager | None = None
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
        )

        openai_host = OpenAIHost(os.environ["OPENAI_HOST"])
        embeddings = setup_embeddings_service(
            openai_host,
            openai_client,
            emb_model_name=os.environ["AZURE_OPENAI_EMB_MODEL_NAME"],
            emb_model_dimensions=int(os.getenv("AZURE_OPENAI_EMB_DIMENSIONS", "3072")),
            azure_openai_deployment=os.getenv("AZURE_OPENAI_EMB_DEPLOYMENT"),
            azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            disable_batch=args.disablebatchvectors,
        )

        indexer = AutoBlobIndexer(
            config=AutoBlobIndexerConfig(
                trigger_container=os.environ["AZURE_STORAGE_CONTAINER"],
                source_prefix=args.sourceprefix,
                target_prefix=args.targetprefix,
                category=args.category,
                allowed_extensions=frozenset({".xml", ".zip"}),
                # The index is owned by prepdocs; this script only adds documents to it.
                manage_search_index=False,
                archive_extensions=frozenset({".zip"}),
            ),
            blob_manager=blob_manager,
            search_manager=SearchManager(
                search_info=search_info,
                search_analyzer_name=os.getenv("AZURE_SEARCH_ANALYZER_NAME"),
                use_acls=os.getenv("AZURE_USE_AUTHENTICATION", "").lower() == "true",
                embeddings=embeddings,
                field_name_embedding=os.getenv("AZURE_SEARCH_FIELD_NAME_EMBEDDING", "embedding"),
                search_images=False,
                enforce_access_control=os.getenv("AZURE_ENFORCE_ACCESS_CONTROL", "").lower() == "true",
            ),
            file_processors=build_file_processors(
                azure_credential=azure_credential,
                document_intelligence_service=None,
                use_local_pdf_parser=True,
                use_local_html_parser=True,
            ),
            section_builder=build_publishone_feed_sections,
            archive_options=FeedArchiveOptions(
                describer=build_describer(openai_client, args),
                description_cache=BlobImageDescriptionCache(
                    blob_manager, f"{args.targetprefix.strip('/')}/.image-descriptions"
                ),
                describe_concurrency=args.image_concurrency,
                max_images=args.image_max_per_archive,
            ),
        )

        # The blob name is what the Event Grid subscription would have delivered, so the source
        # prefix check and the mirror layout match the deployed path exactly.
        source_blob_name = f"{args.sourceprefix.strip('/')}/{package_path.name}"
        result = await indexer.index_blob(blob_name=source_blob_name, content=package_path.read_bytes())
        logger.info(
            "publishone2 ingest result for %s: status=%s indexed_sections=%d target=%s",
            result.source_blob_name,
            result.status,
            result.indexed_sections,
            result.target_blob_name,
        )
    finally:
        await close_clients(blob_manager=blob_manager, openai_client=None, azure_credential=None)


async def run(args: argparse.Namespace) -> None:
    from prepdocslib.servicesetup import OpenAIHost, clean_key_if_exists, setup_openai_client

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

    openai_client: AsyncOpenAI | None = None
    try:
        openai_client, _ = setup_openai_client(
            openai_host=OpenAIHost(os.environ["OPENAI_HOST"]),
            azure_credential=azure_credential,
            azure_openai_service=os.getenv("AZURE_OPENAI_SERVICE"),
            azure_openai_custom_url=os.getenv("AZURE_OPENAI_CUSTOM_URL"),
            azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY_OVERRIDE"),
            openai_api_key=clean_key_if_exists(os.getenv("OPENAI_API_KEY")),
            openai_organization=os.getenv("OPENAI_ORGANIZATION"),
        )

        if args.dry_run:
            await run_dry_run(args, openai_client, azure_credential)
        else:
            await run_ingest(args, openai_client, azure_credential)
    finally:
        await close_clients(blob_manager=None, openai_client=openai_client, azure_credential=azure_credential)


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Ingest a publishone2 package (ZIP of feed XML + images, or a plain feed XML) into Azure AI Search."
    )
    parser.add_argument("file", help="Path to the .zip package or .xml feed document")
    parser.add_argument("--category", default=DEFAULT_CATEGORY, help="Category value to set in the search index")
    parser.add_argument(
        "--targetprefix",
        default=DEFAULT_TARGET_PREFIX,
        help="Blob path prefix under the content container that documents and images are mirrored to",
    )
    parser.add_argument(
        "--sourceprefix",
        default=DEFAULT_SOURCE_PREFIX,
        help="Drop-folder prefix the package is treated as arriving from",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Describe images and print the text that would be indexed, without writing blobs or search documents",
    )
    parser.add_argument("--no-images", action="store_true", help="Skip image description (mirror images undescribed)")
    parser.add_argument("--image-model", default=DEFAULT_IMAGE_MODEL, help="Vision model used to describe images")
    parser.add_argument("--image-deployment", default=None, help="Azure deployment name for the vision model")
    parser.add_argument("--image-max-tokens", type=int, default=1500, help="Token budget per image description")
    parser.add_argument("--image-concurrency", type=int, default=4, help="Concurrent image description requests")
    parser.add_argument("--image-max-per-archive", type=int, default=40, help="Maximum images described per archive")
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
