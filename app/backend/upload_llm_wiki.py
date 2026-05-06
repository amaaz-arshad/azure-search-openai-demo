from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from azure.identity.aio import AzureDeveloperCliCredential

from load_azd_env import load_azd_env
from prepdocslib.servicesetup import clean_key_if_exists, setup_blob_manager

if TYPE_CHECKING:
    from prepdocslib.blobmanager import BlobManager

logger = logging.getLogger("scripts")

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_LLM_WIKI_ROOT = REPO_ROOT / "data" / "llm-wiki"
LLM_WIKI_BLOB_ROOT = "__llm_wiki__"


def normalize_source_chatbot(source_chatbot: str) -> str:
    normalized_source = source_chatbot.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", normalized_source):
        raise ValueError("Source chatbot must contain only lowercase letters, numbers, dashes, or underscores.")
    return normalized_source


def default_wiki_dir(source_chatbot: str) -> Path:
    return LOCAL_LLM_WIKI_ROOT / normalize_source_chatbot(source_chatbot) / "wiki"


def get_blob_prefix(source_chatbot: str, blob_root: str = LLM_WIKI_BLOB_ROOT) -> str:
    normalized_root = blob_root.strip().strip("/\\") or LLM_WIKI_BLOB_ROOT
    return f"{normalized_root}/{normalize_source_chatbot(source_chatbot)}/wiki"


def build_wiki_uploads(source_chatbot: str, wiki_dir: Path, blob_root: str = LLM_WIKI_BLOB_ROOT) -> list[tuple[Path, str]]:
    if not wiki_dir.exists():
        raise FileNotFoundError(f"LLM Wiki directory does not exist: {wiki_dir}")
    if not wiki_dir.is_dir():
        raise NotADirectoryError(f"LLM Wiki path is not a directory: {wiki_dir}")

    blob_prefix = get_blob_prefix(source_chatbot, blob_root)
    uploads: list[tuple[Path, str]] = []
    for markdown_path in sorted(wiki_dir.rglob("*.md")):
        if not markdown_path.is_file():
            continue
        relative_path = markdown_path.relative_to(wiki_dir).as_posix()
        uploads.append((markdown_path, f"{blob_prefix}/{relative_path}"))
    return uploads


async def upload_wiki_pages(
    blob_manager: BlobManager | None,
    uploads: list[tuple[Path, str]],
    *,
    dry_run: bool,
) -> None:
    if not uploads:
        logger.warning("No Markdown files found to upload.")
        return

    for local_path, blob_name in uploads:
        if dry_run:
            logger.info("Would upload %s -> %s", local_path, blob_name)
            continue
        if blob_manager is None:
            raise ValueError("blob_manager is required unless dry_run is enabled.")
        logger.info("Uploading %s -> %s", local_path, blob_name)
        with local_path.open("rb") as file:
            await blob_manager.upload_blob_data(file, blob_name, content_type="text/markdown; charset=utf-8")


async def run(args: argparse.Namespace) -> None:
    load_azd_env()

    wiki_dir = Path(args.wikidir).resolve() if args.wikidir else default_wiki_dir(args.chatbot)
    uploads = build_wiki_uploads(args.chatbot, wiki_dir, args.prefix)
    if args.dry_run:
        await upload_wiki_pages(blob_manager=None, uploads=uploads, dry_run=True)
        return

    tenant_id = os.getenv("AZURE_TENANT_ID")
    if tenant_id:
        azure_credential = AzureDeveloperCliCredential(tenant_id=tenant_id, process_timeout=60)
    else:
        azure_credential = AzureDeveloperCliCredential(process_timeout=60)

    blob_manager: BlobManager | None = None
    try:
        blob_manager = setup_blob_manager(
            azure_credential=azure_credential,
            storage_account=os.environ["AZURE_STORAGE_ACCOUNT"],
            storage_container=os.environ["AZURE_STORAGE_CONTAINER"],
            storage_resource_group=os.environ.get("AZURE_STORAGE_RESOURCE_GROUP"),
            subscription_id=os.environ.get("AZURE_SUBSCRIPTION_ID"),
            storage_key=clean_key_if_exists(args.storagekey),
            image_storage_container=os.environ.get("AZURE_IMAGESTORAGE_CONTAINER"),
        )
        await upload_wiki_pages(blob_manager, uploads, dry_run=args.dry_run)
    finally:
        if blob_manager is not None:
            await blob_manager.close_clients()
        await azure_credential.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Upload a compiled Markdown LLM Wiki to global blob storage.")
    parser.add_argument("chatbot", help="Source chatbot id, for example nerilio, moodle, publishone, or lemon.")
    parser.add_argument(
        "--wikidir",
        help="Directory containing compiled Markdown pages. Defaults to data/llm-wiki/<chatbot>/wiki.",
    )
    parser.add_argument("--prefix", default=LLM_WIKI_BLOB_ROOT, help="Blob root prefix for wiki pages.")
    parser.add_argument("--storagekey", help="Optional Azure Storage account key override.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned uploads without writing blobs.")
    parser.set_defaults(func=run)
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
    logging.getLogger("azure.identity").setLevel(logging.WARNING)
    parser = build_arg_parser()
    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
