"""Re-index provisioned ("generic") chatbot knowledge-base files from the content2 container.

Files for a provisioned bot land in `content2/<bot_name>/<file>` and are normally indexed by the
`content2_auto_index` Azure Function on blob-created events. This script drives the *same*
`AutoBlobIndexer` over files that are already there, which is what makes it a re-ingest command: it
is how a corpus indexed by an older parser gets rebuilt without asking the customer to re-upload.

    python app/backend/prep_content2_reindex.py --dry-run          # report only, writes nothing
    python app/backend/prep_content2_reindex.py                    # re-index every .json/.xml
    python app/backend/prep_content2_reindex.py --bot xba          # one bot folder
    python app/backend/prep_content2_reindex.py --prune-orphans    # also drop docs whose blob is gone

Two things worth knowing before running it:

* **Re-indexing one file is delete-then-write, in that order.** `AutoBlobIndexer.index_blob` calls
  `remove_content(category, storage_url)` before `update_content`, so a file's old documents are gone
  the moment the new ones are being built. A failure in between (a 429 that exhausts its retries, an
  expired credential, Ctrl-C) leaves that one file with zero documents until it is re-run. That is
  why the default is to stop on the first failure rather than press on, and why `--dry-run` exists.
* **`--prune-orphans` only ever deletes documents whose `storageUrl` points into content2 and whose
  blob no longer exists.** Deleting a blob is supposed to remove its documents via the
  `content2_delete_sync` Function, but a blob deleted while that subscription was not in place leaves
  documents behind that still get retrieved - the bot answers from a file its owner deleted.
  Documents in the same category whose `storageUrl` points anywhere else are never touched.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any, Optional

from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import (
    AzureCliCredential,
    AzureDeveloperCliCredential,
    ChainedTokenCredential,
)

from load_azd_env import load_azd_env

if TYPE_CHECKING:
    from prepdocslib.blobautoindex import AutoBlobIndexer
    from prepdocslib.blobmanager import BlobManager

logger = logging.getLogger("scripts")

# Mirrors CONTENT2_DEFAULT_EXTENSIONS in app/functions/moodle_auto_indexer/function_app.py. Document
# Intelligence is not wired into that Function, so Office/image formats are out of scope there and
# must be out of scope here too, or this script would index files the Function never will.
CONTENT2_DEFAULT_EXTENSIONS = (".pdf", ".html", ".txt", ".md", ".csv", ".json", ".xml")
# Statuses that mean "this file now has no documents in the index". `index_blob` has already deleted
# the old ones by the time it can report these, so they are failures, not no-ops.
EMPTY_RESULT_STATUSES = frozenset({"no-content", "copied-no-content", "archive-no-content"})


def build_credential() -> AsyncTokenCredential:
    """Azure CLI first, azd as the fallback.

    `azd auth token` has been measured at 22-121 s per call on a dev machine while
    `az account get-access-token` returns the same scopes in 1.5-3.5 s, and azd additionally hands
    back tokens stamped as already expired, which defeats every token cache. The chain rather than a
    swap is what keeps azd-only setups working: an absent or unauthenticated `az` raises
    `CredentialUnavailableError`, which is exactly what makes ChainedTokenCredential move on.
    """
    tenant_id = os.getenv("AZURE_TENANT_ID")
    if tenant_id:
        return ChainedTokenCredential(
            AzureCliCredential(tenant_id=tenant_id),
            AzureDeveloperCliCredential(tenant_id=tenant_id, process_timeout=60),
        )
    return ChainedTokenCredential(AzureCliCredential(), AzureDeveloperCliCredential(process_timeout=60))


def content2_container() -> str:
    return os.getenv("AZURE_STORAGE_CONTAINER2", os.getenv("CONTENT2_AUTO_INDEX_CONTAINER", "content2"))


def bot_folder_for(blob_name: str) -> Optional[str]:
    segments = blob_name.strip("/").split("/")
    if len(segments) < 2 or not segments[0].strip():
        return None
    return segments[0].strip()


def build_indexer(*, blob_manager, search_info, embeddings, file_processors, extensions: frozenset[str]):
    """The content2 indexer, configured exactly as `build_content2_auto_indexer` configures it.

    `tests/test_prep_content2_reindex.py` compares the two configs field by field: a difference would
    mean this script writes documents that differ from what the Function writes for the same file,
    so the corpus would depend on which of the two last touched it.
    """
    from prepdocslib.blobautoindex import AutoBlobIndexer, AutoBlobIndexerConfig
    from prepdocslib.searchmanager import SearchManager

    container = content2_container()
    return AutoBlobIndexer(
        config=AutoBlobIndexerConfig(
            trigger_container=container,
            source_prefix="",
            target_prefix="",
            category="",
            allowed_extensions=extensions,
            manage_search_index=False,
            remove_by_storage_url=False,
            source_container=container,
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
            field_name_embedding=os.getenv("AZURE_SEARCH_FIELD_NAME_EMBEDDING", "embedding"),
            search_images=False,
            enforce_access_control=False,
        ),
        file_processors=file_processors,
        section_builder=None,
    )


async def list_target_blobs(blob_manager, *, extensions: frozenset[str], bot: Optional[str]) -> list[str]:
    prefix = f"{bot.strip('/')}/" if bot else ""
    blob_names = await blob_manager.list_blob_names(prefix, container=content2_container())
    selected = []
    for blob_name in sorted(blob_names):
        if bot_folder_for(blob_name) is None:
            continue
        if os.path.splitext(blob_name)[1].lower() not in extensions:
            continue
        selected.append(blob_name)
    return selected


async def describe_blob(indexer: AutoBlobIndexer, blob_name: str) -> str:
    """Parse one blob and report what would be indexed, writing nothing."""
    from prepdocslib.filestrategy import parse_file

    category = indexer.category_for_blob(blob_name)
    source_blob = await indexer.blob_manager.download_blob(blob_name, container=indexer.config.source_container)
    if source_blob is None:
        return f"{blob_name}: MISSING"

    content, _ = source_blob
    file_wrapper = indexer.build_file(os.path.basename(blob_name), content)
    try:
        sections = await parse_file(
            file=file_wrapper,
            file_processors=indexer.file_processors,
            category=category,
            force_generic=indexer.config.force_generic_parsing,
            dynamic_record_parsing=indexer.config.dynamic_record_parsing,
        )
    finally:
        file_wrapper.close()

    with_url = sum(1 for section in sections if section.url)
    titles = {section.title for section in sections if section.title}
    sample = sorted(titles)[:3]
    return (
        f"{blob_name}: category={category} sections={len(sections)} with_url={with_url} "
        f"distinct_titles={len(titles)} sample_titles={sample}"
    )


async def prune_orphans(indexer: AutoBlobIndexer, *, existing_blob_names: set[str], dry_run: bool) -> int:
    """Delete documents whose content2 source blob no longer exists.

    Scoped twice over: only categories that are content2 bot folders, and within those only documents
    whose `storageUrl` is under the content2 container. A document indexed into the same category from
    anywhere else (an admin upload lands in `content`, not `content2`) is left alone.
    """
    search_manager = indexer.search_manager
    endpoint = indexer.blob_manager.endpoint.rstrip("/")
    content2_prefix = f"{endpoint}/{content2_container()}/"
    live_storage_urls = {f"{content2_prefix}{blob_name}" for blob_name in existing_blob_names}
    categories = sorted({folder for folder in (bot_folder_for(name) for name in existing_blob_names) if folder})

    removed_total = 0
    async with search_manager.search_info.create_search_client() as search_client:
        for category in categories:
            orphan_counts: dict[str, int] = {}
            skip = 0
            while True:
                results = await search_client.search(
                    search_text="",
                    filter=f"category eq '{category}'",
                    top=1000,
                    skip=skip,
                    select=["id", "storageUrl"],
                    include_total_count=True,
                )
                page_size = 0
                async for document in results:
                    page_size += 1
                    storage_url = str(document.get("storageUrl") or "")
                    if not storage_url.startswith(content2_prefix):
                        continue
                    if storage_url in live_storage_urls:
                        continue
                    orphan_counts[storage_url] = orphan_counts.get(storage_url, 0) + 1
                if page_size == 0:
                    break
                skip += page_size

            for storage_url, count in sorted(orphan_counts.items()):
                removed_total += count
                if dry_run:
                    logger.info("[dry-run] orphan: %s (%d document(s)) in category %s", storage_url, count, category)
                    continue
                logger.info("Removing %d orphaned document(s) for deleted blob %s", count, storage_url)
                await search_manager.remove_content(category=category, storage_url=storage_url)

    return removed_total


async def run(args: argparse.Namespace) -> None:
    from prepdocslib.servicesetup import (
        OpenAIHost,
        build_file_processors,
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

    extensions = frozenset(
        extension if extension.startswith(".") else f".{extension}"
        for extension in (part.strip().lower() for part in args.extensions.split(","))
        if extension
    )

    azure_credential = build_credential()
    blob_manager: BlobManager | None = None
    openai_client = None
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
        openai_client, _ = setup_openai_client(
            openai_host=OpenAIHost(os.environ["OPENAI_HOST"]),
            azure_credential=azure_credential,
            azure_openai_service=os.getenv("AZURE_OPENAI_SERVICE"),
            azure_openai_custom_url=os.getenv("AZURE_OPENAI_CUSTOM_URL"),
            azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY_OVERRIDE"),
            openai_api_key=clean_key_if_exists(os.getenv("OPENAI_API_KEY")),
            openai_organization=os.getenv("OPENAI_ORGANIZATION"),
        )
        embeddings = setup_embeddings_service(
            OpenAIHost(os.environ["OPENAI_HOST"]),
            openai_client,
            emb_model_name=os.environ["AZURE_OPENAI_EMB_MODEL_NAME"],
            emb_model_dimensions=int(os.getenv("AZURE_OPENAI_EMB_DIMENSIONS", "3072")),
            azure_openai_deployment=os.getenv("AZURE_OPENAI_EMB_DEPLOYMENT"),
            azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            disable_batch=args.disablebatchvectors,
        )
        indexer = build_indexer(
            blob_manager=blob_manager,
            search_info=search_info,
            embeddings=embeddings,
            file_processors=build_file_processors(
                azure_credential=azure_credential,
                document_intelligence_service=None,
                use_local_pdf_parser=True,
                use_local_html_parser=True,
            ),
            extensions=extensions,
        )

        all_blob_names = await blob_manager.list_blob_names("", container=content2_container())
        targets = await list_target_blobs(blob_manager, extensions=extensions, bot=args.bot)
        logger.info(
            "content2 container holds %d blob(s); %d match %s%s",
            len(all_blob_names),
            len(targets),
            sorted(extensions),
            f" under {args.bot}/" if args.bot else "",
        )

        if args.dry_run:
            for blob_name in targets:
                logger.info("[dry-run] %s", await describe_blob(indexer, blob_name))
        else:
            failures: list[tuple[str, str]] = []
            indexed_sections = 0
            for position, blob_name in enumerate(targets, start=1):
                result = await indexer.index_blob_from_storage(blob_name=blob_name)
                logger.info(
                    "[%d/%d] %s -> status=%s sections=%d",
                    position,
                    len(targets),
                    blob_name,
                    result.status,
                    result.indexed_sections,
                )
                indexed_sections += result.indexed_sections
                if result.status != "indexed":
                    failures.append((blob_name, result.status))
                    # An empty result means this file's documents were deleted and nothing replaced
                    # them, so pressing on would keep widening the damage.
                    if result.status in EMPTY_RESULT_STATUSES and not args.continue_on_error:
                        raise RuntimeError(
                            f"{blob_name} produced no searchable sections (status={result.status}); "
                            "its previous documents have already been removed. Re-run for this file "
                            "after fixing the cause, or pass --continue-on-error to ignore."
                        )
                if args.sleep:
                    await asyncio.sleep(args.sleep)
            logger.info("Re-indexed %d file(s), %d section(s) total", len(targets), indexed_sections)
            for blob_name, status in failures:
                logger.warning("Not indexed: %s (status=%s)", blob_name, status)

        if args.prune_orphans:
            removed = await prune_orphans(
                indexer,
                existing_blob_names={name for name in all_blob_names if bot_folder_for(name)},
                dry_run=args.dry_run,
            )
            logger.info(
                "%s %d orphaned document(s) whose content2 blob no longer exists",
                "Would remove" if args.dry_run else "Removed",
                removed,
            )
    finally:
        if blob_manager is not None:
            await blob_manager.close_clients()
        if openai_client is not None:
            await openai_client.close()
        await azure_credential.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Re-index provisioned (generic) chatbot knowledge-base files already in the content2 container."
    )
    parser.add_argument("--bot", default=None, help="Only this content2/<bot_name>/ folder (default: every bot)")
    parser.add_argument(
        "--extensions",
        default=",".join(CONTENT2_DEFAULT_EXTENSIONS),
        help="Comma-separated file extensions to re-index",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report what would be indexed (and which orphans would be removed) without writing",
    )
    parser.add_argument(
        "--prune-orphans",
        action="store_true",
        help="Also delete index documents whose content2 source blob no longer exists",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Keep going after a file yields no sections (its old documents are already deleted)",
    )
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to wait between files (eases 429 pressure)")
    parser.add_argument(
        "--disablebatchvectors", action="store_true", help="Do not batch embedding requests when generating vectors"
    )
    parser.add_argument("--searchkey", required=False, help="Optional Azure AI Search key instead of the azd identity")
    parser.add_argument("--storagekey", required=False, help="Optional Blob Storage key instead of the azd identity")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    return parser


if __name__ == "__main__":  # pragma: no cover
    parsed_args = build_arg_parser().parse_args()
    logging.basicConfig(level=logging.DEBUG if parsed_args.verbose else logging.INFO, format="%(message)s")
    logger.setLevel(logging.DEBUG if parsed_args.verbose else logging.INFO)
    # The Azure SDKs log every request and response header at INFO, which buries this script's own
    # per-file report. --verbose opts back into it.
    if not parsed_args.verbose:
        for noisy in ("azure", "azure.core.pipeline.policies.http_logging_policy", "openai", "httpx"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
    reconfigure: Any = getattr(__import__("sys").stdout, "reconfigure", None)
    if callable(reconfigure):
        # Titles carved out of scraped German pages are routinely non-ASCII and the Windows console
        # defaults to cp1252, which would abort the run on a print rather than on an ingest problem.
        reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(run(parsed_args))
