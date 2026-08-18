"""
Azure Function: external feed auto indexer.

Watches external drop folders inside blob storage, copies supported files into
chatbot-owned folders such as `content/moodle/` and `content/publishone/`, and
indexes them into Azure AI Search under the corresponding chatbot category.

Also hosts the `content2` dynamic multi-bot indexer: it watches the whole
`content2` container (layout `content2/<bot_name>/<file>`), derives the search
category from the per-bot folder, parses files with the generic parsers only,
and indexes them in place without mirroring into `content`.

The `publishone2` feed additionally accepts ZIP packages: one archive holds feed
XML plus the image files those documents reference, so the images can be read by
a vision model at ingestion time and displayed in answers.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

import azure.functions as func
from azure.identity.aio import ManagedIdentityCredential

from prepdocslib.blobautoindex import (
    AutoBlobIndexer,
    AutoBlobIndexerConfig,
    blob_name_from_event_grid_subject,
    parse_allowed_extensions,
)
from prepdocslib.feedarchive import (
    DEFAULT_DESCRIBE_CONCURRENCY,
    DEFAULT_MAX_IMAGES_PER_ARCHIVE,
    BlobImageDescriptionCache,
    FeedArchiveOptions,
)
from prepdocslib.fhgjson import prepare_fhg_dataset
from prepdocslib.mediadescriber import FEED_IMAGE_DESCRIPTION_PROMPT, MultimodalModelDescriber
from prepdocslib.page import Chunk
from prepdocslib.publishonefeed import build_publishone_feed_sections
from prepdocslib.servicesetup import (
    OpenAIHost,
    build_file_processors,
    setup_blob_manager,
    setup_embeddings_service,
    setup_openai_client,
    setup_search_info,
)
from prepdocslib.searchmanager import SearchManager, Section

app = func.FunctionApp()

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeedDefinition:
    name: str
    source_prefix: str
    target_prefix: str
    category: str
    allowed_extensions: tuple[str, ...]
    source_prefix_env: Optional[str] = None
    target_prefix_env: Optional[str] = None
    category_env: Optional[str] = None
    allowed_extensions_env: Optional[str] = None
    # Extensions this feed treats as archive packages (see AutoBlobIndexerConfig.archive_extensions).
    archive_extensions: tuple[str, ...] = ()


TRIGGER_CONTAINER = os.getenv("MOODLE_AUTO_INDEX_TRIGGER_CONTAINER", "content")
FEED_DEFINITIONS = {
    "moodle": FeedDefinition(
        name="moodle",
        source_prefix="nerilio/Nerilio-Moodle",
        target_prefix="moodle",
        category="moodle",
        allowed_extensions=(".xml",),
        source_prefix_env="MOODLE_AUTO_INDEX_SOURCE_PREFIX",
        target_prefix_env="MOODLE_AUTO_INDEX_TARGET_PREFIX",
        category_env="MOODLE_AUTO_INDEX_CATEGORY",
        allowed_extensions_env="MOODLE_AUTO_INDEX_ALLOWED_EXTENSIONS",
    ),
    "publishone": FeedDefinition(
        name="publishone",
        source_prefix="nerilio/Nerilio-Amsterdam",
        target_prefix="publishone",
        category="publishone",
        allowed_extensions=(".xml",),
        source_prefix_env="PUBLISHONE_AUTO_INDEX_SOURCE_PREFIX",
        target_prefix_env="PUBLISHONE_AUTO_INDEX_TARGET_PREFIX",
        category_env="PUBLISHONE_AUTO_INDEX_CATEGORY",
        allowed_extensions_env="PUBLISHONE_AUTO_INDEX_ALLOWED_EXTENSIONS",
    ),
    # publishone2 is the ZIP-capable sibling of the publishone feed: the drop folder receives either
    # a plain feed XML (handled exactly like publishone) or a ZIP holding feed XML plus the image
    # files those documents reference. Archive images are described by a vision model at ingestion
    # time and mirrored alongside the documents, which is what lets the bot both answer from and
    # display them.
    "publishone2": FeedDefinition(
        name="publishone2",
        source_prefix="nerilio/Nerilio-Amsterdam-ZIP-zip",
        target_prefix="publishone2",
        category="publishone2",
        allowed_extensions=(".xml", ".zip"),
        archive_extensions=(".zip",),
        source_prefix_env="PUBLISHONE2_AUTO_INDEX_SOURCE_PREFIX",
        target_prefix_env="PUBLISHONE2_AUTO_INDEX_TARGET_PREFIX",
        category_env="PUBLISHONE2_AUTO_INDEX_CATEGORY",
        allowed_extensions_env="PUBLISHONE2_AUTO_INDEX_ALLOWED_EXTENSIONS",
    ),
    "fhg": FeedDefinition(
        name="fhg",
        source_prefix="nerilio/Nerilio-fhg",
        target_prefix="fhg",
        category="fhg",
        allowed_extensions=(".json",),
        source_prefix_env="FHG_AUTO_INDEX_SOURCE_PREFIX",
        target_prefix_env="FHG_AUTO_INDEX_TARGET_PREFIX",
        category_env="FHG_AUTO_INDEX_CATEGORY",
        allowed_extensions_env="FHG_AUTO_INDEX_ALLOWED_EXTENSIONS",
    ),
}

# --- content2 dynamic multi-bot indexer -------------------------------------------------------
# Provisioned ("generic") chatbots receive their knowledge-base files in a dedicated `content2`
# container, one folder per bot: content2/<bot_name>/<file>. Unlike the feeds above this indexer:
#   * watches the whole content2 container (no fixed source prefix),
#   * derives the search category dynamically from the <bot_name> folder,
#   * never mirrors into `content` (files are indexed in place; storageUrl points at content2),
#   * never lets a built-in bot's category-keyed feed parser claim a file (force_generic_parsing),
#     but does route .json/.xml through the provisioned-bot record parsers first
#     (dynamic_record_parsing -> prepdocslib.dynamicjson / dynamicxml), falling back to the generic
#     extension parsers for everything else.
# One event-subscription pair covers all bots; a brand-new bot folder "just works" with no config.
CONTENT2_FEED_NAME = "content2"
CONTENT2_CONTAINER = os.getenv("CONTENT2_AUTO_INDEX_CONTAINER", "content2")
# Local-parseable generic extensions (Document Intelligence is not wired into this function app,
# so Office/image formats are intentionally out of scope). is_supported() further intersects this
# with the actually-available file_processors.
CONTENT2_DEFAULT_EXTENSIONS = (".pdf", ".html", ".txt", ".md", ".csv", ".json", ".xml")


@dataclass
class GlobalSettings:
    auto_indexers: dict[str, AutoBlobIndexer]

    def auto_indexer_for(self, feed_name: str) -> AutoBlobIndexer:
        return self.auto_indexers[feed_name]


settings: Optional[GlobalSettings] = None


def resolve_feed_value(explicit_env_name: Optional[str], default_value: str) -> str:
    if explicit_env_name:
        return os.getenv(explicit_env_name, default_value)
    return default_value


async def build_fhg_json_sections(*, file, file_processors, category: str) -> list[Section]:
    del file_processors

    payload = json.loads(file.content.read().decode("utf-8-sig"))
    prepared_dataset = prepare_fhg_dataset(
        payload,
        dataset_filename=file.filename(),
        category=category,
    )

    return [
        Section(
            chunk=Chunk(page_num=0, text=document.content),
            content=file,
            category=document.category,
            id=document.id,
            sourcepage=document.sourcepage,
            sourcefile=document.sourcefile,
            title=document.title,
            url=document.url,
            tags=document.tags,
            user=document.user,
        )
        for document in prepared_dataset.documents
    ]


def build_archive_options(
    *,
    target_prefix: str,
    openai_client,
    blob_manager,
) -> FeedArchiveOptions:
    """Vision describer + description cache for archive images.

    The chat deployment the backend uses by default is a reasoning model, which the describer
    cannot drive, so the image model is configured separately and defaults to gpt-4.1 (deployed
    here, vision-capable, non-reasoning). With no OpenAI client the archive still indexes — images
    are mirrored and displayed, just not transcribed.
    """
    describer = None
    if openai_client is not None:
        image_model = os.getenv("PUBLISHONE2_IMAGE_MODEL", "gpt-4.1")
        image_deployment = os.getenv("PUBLISHONE2_IMAGE_DEPLOYMENT", image_model)
        describer = MultimodalModelDescriber(
            openai_client=openai_client,
            model=image_model,
            deployment=image_deployment if OpenAIHost(os.getenv("OPENAI_HOST", "azure")) == OpenAIHost.AZURE else None,
            prompt=FEED_IMAGE_DESCRIPTION_PROMPT,
            max_tokens=int(os.getenv("PUBLISHONE2_IMAGE_MAX_TOKENS", "1500")),
        )

    return FeedArchiveOptions(
        describer=describer,
        description_cache=BlobImageDescriptionCache(blob_manager, f"{target_prefix}/.image-descriptions"),
        describe_concurrency=int(os.getenv("PUBLISHONE2_IMAGE_CONCURRENCY", str(DEFAULT_DESCRIBE_CONCURRENCY))),
        max_images=int(os.getenv("PUBLISHONE2_IMAGE_MAX_PER_ARCHIVE", str(DEFAULT_MAX_IMAGES_PER_ARCHIVE))),
    )


def build_auto_indexer(
    *,
    feed: FeedDefinition,
    azure_credential: ManagedIdentityCredential,
    blob_manager,
    search_info,
    embeddings,
    embedding_field_name: str,
    file_processors,
    openai_client=None,
) -> AutoBlobIndexer:
    source_prefix = resolve_feed_value(feed.source_prefix_env, feed.source_prefix)
    target_prefix = resolve_feed_value(feed.target_prefix_env, feed.target_prefix)
    category = resolve_feed_value(feed.category_env, feed.category)
    allowed_extensions_raw = os.getenv(feed.allowed_extensions_env) if feed.allowed_extensions_env else None
    allowed_extensions = parse_allowed_extensions(allowed_extensions_raw, feed.allowed_extensions)
    archive_options = (
        build_archive_options(target_prefix=target_prefix, openai_client=openai_client, blob_manager=blob_manager)
        if feed.archive_extensions
        else None
    )

    return AutoBlobIndexer(
        config=AutoBlobIndexerConfig(
            trigger_container=TRIGGER_CONTAINER,
            source_prefix=source_prefix,
            target_prefix=target_prefix,
            category=category,
            allowed_extensions=allowed_extensions,
            manage_search_index=False,
            remove_by_storage_url=feed.name == "fhg",
            archive_extensions=frozenset(feed.archive_extensions),
        ),
        archive_options=archive_options,
        blob_manager=blob_manager,
        search_manager=SearchManager(
            search_info=search_info,
            search_analyzer_name=os.getenv("AZURE_SEARCH_ANALYZER_NAME"),
            use_acls=False,
            use_parent_index_projection=False,
            embeddings=embeddings,
            field_name_embedding=embedding_field_name,
            search_images=False,
            enforce_access_control=False,
        ),
        file_processors=file_processors,
        section_builder=build_fhg_json_sections if feed.name == "fhg" else build_publishone_feed_sections,
    )


def build_content2_auto_indexer(
    *,
    blob_manager,
    search_info,
    embeddings,
    embedding_field_name: str,
    file_processors,
) -> AutoBlobIndexer:
    allowed_extensions = parse_allowed_extensions(
        os.getenv("CONTENT2_AUTO_INDEX_ALLOWED_EXTENSIONS"),
        CONTENT2_DEFAULT_EXTENSIONS,
    )

    return AutoBlobIndexer(
        config=AutoBlobIndexerConfig(
            trigger_container=CONTENT2_CONTAINER,
            source_prefix="",
            target_prefix="",
            category="",
            allowed_extensions=allowed_extensions,
            manage_search_index=False,
            remove_by_storage_url=False,
            source_container=CONTENT2_CONTAINER,
            mirror_blob=False,
            dynamic_category_from_path=True,
            force_generic_parsing=True,
            dynamic_record_parsing=True,
        ),
        blob_manager=blob_manager,
        search_manager=SearchManager(
            search_info=search_info,
            search_analyzer_name=os.getenv("AZURE_SEARCH_ANALYZER_NAME"),
            use_acls=False,
            use_parent_index_projection=False,
            embeddings=embeddings,
            field_name_embedding=embedding_field_name,
            search_images=False,
            enforce_access_control=False,
        ),
        file_processors=file_processors,
        section_builder=None,
    )


async def handle_create_event(event: func.EventGridEvent, feed_name: str) -> None:
    if settings is None:
        raise RuntimeError("Settings not initialized")

    if event.event_type != "Microsoft.Storage.BlobCreated":
        logger.info("Skipping unexpected event type for %s auto-index: %s", feed_name, event.event_type)
        return

    source_blob_name = blob_name_from_event_grid_subject(event.subject or "")
    if not source_blob_name:
        logger.warning("Unable to parse blob name from %s create event subject: %s", feed_name, event.subject)
        return

    logger.info("%s auto-index trigger received blob event for: %s", feed_name, source_blob_name)
    result = await settings.auto_indexer_for(feed_name).index_blob_from_storage(blob_name=source_blob_name)
    logger.info(
        "%s auto-index result for %s: status=%s indexed_sections=%d target_blob=%s",
        feed_name,
        result.source_blob_name,
        result.status,
        result.indexed_sections,
        result.target_blob_name,
    )


async def handle_delete_event(event: func.EventGridEvent, feed_name: str) -> None:
    if settings is None:
        raise RuntimeError("Settings not initialized")

    if event.event_type != "Microsoft.Storage.BlobDeleted":
        logger.info("Skipping unexpected event type for %s delete sync: %s", feed_name, event.event_type)
        return

    source_blob_name = blob_name_from_event_grid_subject(event.subject or "")
    if not source_blob_name:
        logger.warning("Unable to parse blob name from %s delete event subject: %s", feed_name, event.subject)
        return

    result = await settings.auto_indexer_for(feed_name).delete_blob(blob_name=source_blob_name)
    logger.info(
        "%s delete-sync result for %s: status=%s target_blob=%s",
        feed_name,
        result.source_blob_name,
        result.status,
        result.target_blob_name,
    )


def configure_global_settings() -> None:
    global settings

    storage_account = os.environ["AZURE_STORAGE_ACCOUNT"]
    storage_container = os.environ["AZURE_STORAGE_CONTAINER"]
    search_service = os.environ["AZURE_SEARCH_SERVICE"]
    search_index = os.environ["AZURE_SEARCH_INDEX"]
    embedding_field_name = os.getenv("AZURE_SEARCH_FIELD_NAME_EMBEDDING", "embedding")
    use_vectors = os.getenv("USE_VECTORS", "true").lower() == "true"
    embedding_dimensions = int(os.getenv("AZURE_OPENAI_EMB_DIMENSIONS", "3072"))

    if azure_client_id := os.getenv("AZURE_CLIENT_ID"):
        logger.info("Using Managed Identity with client ID: %s", azure_client_id)
        azure_credential = ManagedIdentityCredential(client_id=azure_client_id)
    else:
        logger.info("Using default Managed Identity without client ID")
        azure_credential = ManagedIdentityCredential()

    blob_manager = setup_blob_manager(
        azure_credential=azure_credential,
        storage_account=storage_account,
        storage_container=storage_container,
        storage_resource_group=os.getenv("AZURE_STORAGE_RESOURCE_GROUP"),
        subscription_id=os.getenv("AZURE_SUBSCRIPTION_ID"),
    )

    search_info = setup_search_info(
        search_service=search_service,
        index_name=search_index,
        azure_credential=azure_credential,
        use_agentic_knowledgebase=False,
        azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    )

    # The OpenAI client is shared by the embeddings service and the archive image describer, so it
    # is built even when vectors are off.
    openai_host = OpenAIHost(os.getenv("OPENAI_HOST", "azure"))
    openai_client, azure_openai_endpoint = setup_openai_client(
        openai_host=openai_host,
        azure_credential=azure_credential,
        azure_openai_service=os.getenv("AZURE_OPENAI_SERVICE"),
        azure_openai_custom_url=os.getenv("AZURE_OPENAI_CUSTOM_URL"),
        azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY_OVERRIDE"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_organization=os.getenv("OPENAI_ORGANIZATION"),
    )

    embeddings = None
    if use_vectors:
        embeddings = setup_embeddings_service(
            openai_host,
            open_ai_client=openai_client,
            emb_model_name=os.environ["AZURE_OPENAI_EMB_MODEL_NAME"],
            emb_model_dimensions=embedding_dimensions,
            azure_openai_deployment=os.getenv("AZURE_OPENAI_EMB_DEPLOYMENT"),
            azure_openai_endpoint=azure_openai_endpoint,
        )

    file_processors = build_file_processors(
        azure_credential=azure_credential,
        document_intelligence_service=None,
        document_intelligence_key=None,
        use_local_pdf_parser=False,
        use_local_html_parser=False,
        process_figures=False,
    )

    auto_indexers = {
        feed_name: build_auto_indexer(
            feed=feed,
            azure_credential=azure_credential,
            blob_manager=blob_manager,
            search_info=search_info,
            embeddings=embeddings,
            embedding_field_name=embedding_field_name,
            file_processors=file_processors,
            openai_client=openai_client,
        )
        for feed_name, feed in FEED_DEFINITIONS.items()
    }
    auto_indexers[CONTENT2_FEED_NAME] = build_content2_auto_indexer(
        blob_manager=blob_manager,
        search_info=search_info,
        embeddings=embeddings,
        embedding_field_name=embedding_field_name,
        file_processors=file_processors,
    )
    settings = GlobalSettings(auto_indexers=auto_indexers)


@app.function_name(name="moodle_auto_index")
@app.event_grid_trigger(arg_name="event")
async def moodle_auto_index(event: func.EventGridEvent) -> None:
    try:
        await handle_create_event(event, "moodle")
    except Exception:
        logger.exception("Unhandled exception in moodle_auto_index")
        raise


@app.function_name(name="moodle_delete_sync")
@app.event_grid_trigger(arg_name="event")
async def moodle_delete_sync(event: func.EventGridEvent) -> None:
    try:
        await handle_delete_event(event, "moodle")
    except Exception:
        logger.exception("Unhandled exception in moodle_delete_sync")
        raise


@app.function_name(name="publishone_auto_index")
@app.event_grid_trigger(arg_name="event")
async def publishone_auto_index(event: func.EventGridEvent) -> None:
    try:
        await handle_create_event(event, "publishone")
    except Exception:
        logger.exception("Unhandled exception in publishone_auto_index")
        raise


@app.function_name(name="publishone_delete_sync")
@app.event_grid_trigger(arg_name="event")
async def publishone_delete_sync(event: func.EventGridEvent) -> None:
    try:
        await handle_delete_event(event, "publishone")
    except Exception:
        logger.exception("Unhandled exception in publishone_delete_sync")
        raise


@app.function_name(name="publishone2_auto_index")
@app.event_grid_trigger(arg_name="event")
async def publishone2_auto_index(event: func.EventGridEvent) -> None:
    try:
        await handle_create_event(event, "publishone2")
    except Exception:
        logger.exception("Unhandled exception in publishone2_auto_index")
        raise


@app.function_name(name="publishone2_delete_sync")
@app.event_grid_trigger(arg_name="event")
async def publishone2_delete_sync(event: func.EventGridEvent) -> None:
    try:
        await handle_delete_event(event, "publishone2")
    except Exception:
        logger.exception("Unhandled exception in publishone2_delete_sync")
        raise


@app.function_name(name="fhg_auto_index")
@app.event_grid_trigger(arg_name="event")
async def fhg_auto_index(event: func.EventGridEvent) -> None:
    try:
        await handle_create_event(event, "fhg")
    except Exception:
        logger.exception("Unhandled exception in fhg_auto_index")
        raise


@app.function_name(name="fhg_delete_sync")
@app.event_grid_trigger(arg_name="event")
async def fhg_delete_sync(event: func.EventGridEvent) -> None:
    try:
        await handle_delete_event(event, "fhg")
    except Exception:
        logger.exception("Unhandled exception in fhg_delete_sync")
        raise


@app.function_name(name="content2_auto_index")
@app.event_grid_trigger(arg_name="event")
async def content2_auto_index(event: func.EventGridEvent) -> None:
    try:
        await handle_create_event(event, CONTENT2_FEED_NAME)
    except Exception:
        logger.exception("Unhandled exception in content2_auto_index")
        raise


@app.function_name(name="content2_delete_sync")
@app.event_grid_trigger(arg_name="event")
async def content2_delete_sync(event: func.EventGridEvent) -> None:
    try:
        await handle_delete_event(event, CONTENT2_FEED_NAME)
    except Exception:
        logger.exception("Unhandled exception in content2_delete_sync")
        raise


if os.environ.get("PYTEST_CURRENT_TEST") is None:
    try:
        configure_global_settings()
    except KeyError as error:
        logger.warning("Could not initialize settings at module load time: %s", error)
