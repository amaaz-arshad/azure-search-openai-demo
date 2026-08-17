import asyncio
import io
import logging
import mimetypes
import os
import zipfile
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from typing import Optional

from .blobmanager import BlobManager
from .feedarchive import (
    FeedArchiveOptions,
    build_image_bundle,
    describe_archive_images,
    document_blob_name,
    expand_feed_archive,
    image_blob_name,
    looks_like_zip,
    package_name_for_archive,
)
from .fileprocessor import FileProcessor
from .filestrategy import parse_file
from .listfilestrategy import File
from .searchmanager import SearchManager, Section

logger = logging.getLogger("scripts")

SectionBuilder = Callable[..., Awaitable[list[Section]]]


@dataclass(frozen=True)
class AutoBlobIndexerConfig:
    trigger_container: str
    source_prefix: str
    target_prefix: str
    category: str
    allowed_extensions: frozenset[str]
    manage_search_index: bool = True
    remove_by_storage_url: bool = False
    # --- dynamic / no-mirror / generic mode (content2 provisioned-bot indexer) ---
    # Download the source blob from this container instead of the blob manager's default container.
    source_container: Optional[str] = None
    # When False, do NOT copy the source blob into target_prefix; index it in place and point
    # storageUrl at the source blob URL (used by content2, which is never mirrored into `content`).
    mirror_blob: bool = True
    # When True, derive the search category from the first path segment after source_prefix
    # (e.g. content2/<bot_name>/<file> -> category "<bot_name>") instead of using `category`.
    dynamic_category_from_path: bool = False
    # When True, force generic extension-based parsing (bypass all custom content-specific parsers).
    force_generic_parsing: bool = False
    # --- archive mode (publishone2 ZIP packages) ---
    # Extensions treated as archives: one source blob expands into several documents plus the image
    # assets they reference. Everything mirrored out of an archive is namespaced by the archive's
    # filename stem, which is what makes re-upload and delete scoped to that package.
    archive_extensions: frozenset[str] = frozenset()


@dataclass(frozen=True)
class AutoBlobIndexResult:
    source_blob_name: str
    target_blob_name: Optional[str]
    storage_url: Optional[str]
    indexed_sections: int
    status: str


def normalize_blob_name(blob_name: str, container_name: Optional[str] = None) -> str:
    normalized_blob_name = blob_name.strip().lstrip("/").replace("\\", "/")
    if container_name:
        container_prefix = f"{container_name.strip().strip('/').strip()}".strip("/")
        if container_prefix and normalized_blob_name.startswith(f"{container_prefix}/"):
            return normalized_blob_name[len(container_prefix) + 1 :]
    return normalized_blob_name


def blob_name_from_event_grid_subject(subject: str) -> Optional[str]:
    normalized_subject = subject.strip()
    if "/containers/" not in normalized_subject or "/blobs/" not in normalized_subject:
        return None

    subject_tail = normalized_subject.split("/containers/", 1)[1]
    container_name, blob_path = subject_tail.split("/blobs/", 1)
    if not container_name or not blob_path:
        return None
    return f"{container_name}/{blob_path}"


def normalize_prefix(prefix: str) -> str:
    return prefix.strip().strip("/\\")


def parse_allowed_extensions(value: Optional[str], default_extensions: tuple[str, ...] = (".xml",)) -> frozenset[str]:
    if value is None:
        return frozenset(default_extensions)

    extensions = {
        extension if extension.startswith(".") else f".{extension}"
        for extension in (part.strip().lower() for part in value.split(","))
        if extension
    }
    return frozenset(extensions or default_extensions)


class AutoBlobIndexer:
    def __init__(
        self,
        *,
        config: AutoBlobIndexerConfig,
        blob_manager: BlobManager,
        search_manager: SearchManager,
        file_processors: dict[str, FileProcessor],
        section_builder: Optional[SectionBuilder] = None,
        archive_options: Optional[FeedArchiveOptions] = None,
    ):
        self.config = config
        self.blob_manager = blob_manager
        self.search_manager = search_manager
        self.file_processors = file_processors
        self.section_builder = section_builder
        self.archive_options = archive_options or FeedArchiveOptions()
        self.index_ready = False
        self.index_lock = asyncio.Lock()

    async def ensure_index(self) -> None:
        if self.index_ready:
            return

        async with self.index_lock:
            if self.index_ready:
                return
            if self.config.manage_search_index:
                await self.search_manager.create_index()
            self.index_ready = True

    def normalize_source_blob_name(self, blob_name: str) -> str:
        return normalize_blob_name(blob_name, container_name=self.config.trigger_container)

    def source_matches_prefix(self, blob_name: str) -> bool:
        normalized_blob_name = self.normalize_source_blob_name(blob_name)
        source_prefix = normalize_prefix(self.config.source_prefix)
        if not source_prefix:
            # Empty prefix means "watch the whole container" (content2 dynamic indexer).
            return bool(normalized_blob_name)
        return normalized_blob_name == source_prefix or normalized_blob_name.startswith(f"{source_prefix}/")

    def relative_to_source_prefix(self, normalized_blob_name: str) -> str:
        source_prefix = normalize_prefix(self.config.source_prefix)
        if source_prefix and normalized_blob_name.startswith(f"{source_prefix}/"):
            return normalized_blob_name[len(source_prefix) + 1 :]
        return normalized_blob_name

    def category_for_blob(self, normalized_blob_name: str) -> Optional[str]:
        """Return the search category for a blob.

        In dynamic mode the category is the first path segment after source_prefix
        (the per-bot folder in content2). Returns None when no bot folder is present.
        """
        if not self.config.dynamic_category_from_path:
            return self.config.category
        relative = self.relative_to_source_prefix(normalized_blob_name)
        segments = relative.split("/")
        if len(segments) < 2 or not segments[0].strip():
            return None
        return segments[0].strip()

    def source_storage_url(self, normalized_blob_name: str) -> str:
        container = self.config.source_container or self.blob_manager.container
        endpoint = self.blob_manager.endpoint.rstrip("/")
        return f"{endpoint}/{container}/{normalized_blob_name}"

    def build_remove_kwargs(
        self,
        *,
        category: str,
        filename: str,
        target_blob_name: Optional[str],
        storage_url: Optional[str],
    ) -> dict:
        if not self.config.mirror_blob:
            # No-mirror mode: docs for one source file are uniquely identified by the exact
            # source storageUrl (full content2 path), scoped to the bot's category.
            return {"category": category, "storage_url": storage_url}
        remove_kwargs = {
            "path": None if self.config.remove_by_storage_url else filename,
            "category": category,
            "storage_url_suffix": target_blob_name,
        }
        if self.config.remove_by_storage_url and storage_url is not None:
            remove_kwargs["storage_url"] = storage_url
        return remove_kwargs

    def target_blob_name_for_source(self, blob_name: str) -> str:
        normalized_blob_name = self.normalize_source_blob_name(blob_name)
        filename = os.path.basename(normalized_blob_name)
        target_prefix = normalize_prefix(self.config.target_prefix)
        if target_prefix:
            return f"{target_prefix}/{filename}"
        return filename

    def storage_url_for_target_blob(self, target_blob_name: str) -> Optional[str]:
        url_for_blob_name = getattr(self.blob_manager, "url_for_blob_name", None)
        if not callable(url_for_blob_name):
            return None
        return url_for_blob_name(target_blob_name)

    def extension_for(self, blob_name: str) -> str:
        filename = os.path.basename(self.normalize_source_blob_name(blob_name))
        return os.path.splitext(filename)[1].lower()

    def archive_mode_enabled(self) -> bool:
        return bool(self.config.archive_extensions)

    def is_archive(self, blob_name: str, content: Optional[bytes] = None) -> bool:
        """Whether a blob should be read as an archive package.

        Extension first, then the payload's own magic bytes: real PublishOne exports ship ZIP
        packages named `.xml`, and an unreadable-XML crash on every one of them is a poor trade for
        a four-byte check. Sniffing only ever applies to a feed that has archives enabled, so
        publishone/moodle behaviour cannot change.
        """
        if self.extension_for(blob_name) in self.config.archive_extensions:
            return True
        return self.archive_mode_enabled() and content is not None and looks_like_zip(content)

    def is_supported(self, blob_name: str) -> bool:
        extension = self.extension_for(blob_name)
        if extension not in self.config.allowed_extensions:
            return False
        # Archives have no FileProcessor of their own — the documents inside them do.
        if extension in self.config.archive_extensions:
            return True
        return extension in self.file_processors

    def package_storage_url_prefix(self, package_name: str) -> str:
        """storageUrl prefix shared by every document mirrored out of one archive."""
        endpoint = self.blob_manager.endpoint.rstrip("/")
        target_prefix = normalize_prefix(self.config.target_prefix)
        package_prefix = f"{target_prefix}/{package_name}" if target_prefix else package_name
        return f"{endpoint}/{self.blob_manager.container}/{package_prefix}/"

    def package_blob_prefix(self, package_name: str) -> str:
        target_prefix = normalize_prefix(self.config.target_prefix)
        return f"{target_prefix}/{package_name}/" if target_prefix else f"{package_name}/"

    async def purge_package(self, package_name: str, category: str) -> int:
        """Drop every search doc and mirrored blob belonging to one archive package.

        Run before re-indexing an archive as well as on delete: an archive whose contents shrank
        would otherwise leave orphaned documents and images behind. Returns the number of mirrored
        blobs removed, which is also how a delete recognises a package that arrived under a
        non-archive extension.
        """
        await self.search_manager.remove_content(
            category=category,
            storage_url_prefix=self.package_storage_url_prefix(package_name),
        )
        blob_prefix = self.package_blob_prefix(package_name)
        list_blob_names = getattr(self.blob_manager, "list_blob_names", None)
        if not callable(list_blob_names):
            logger.info("Blob manager cannot list by prefix; leaving mirrored blobs under %s", blob_prefix)
            return 0
        removed = 0
        for blob_name in await list_blob_names(blob_prefix):
            await self.blob_manager.remove_blob_name(blob_name)
            removed += 1
        return removed

    @staticmethod
    def content_type_for_filename(filename: str, content_type: Optional[str]) -> str:
        if content_type:
            return content_type
        guessed_content_type, _ = mimetypes.guess_type(filename)
        return guessed_content_type or "application/octet-stream"

    @staticmethod
    def build_file(filename: str, content: bytes) -> File:
        stream = io.BytesIO(content)
        stream.name = filename
        return File(content=stream)

    async def index_blob(
        self,
        *,
        blob_name: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> AutoBlobIndexResult:
        normalized_source_blob_name = self.normalize_source_blob_name(blob_name)
        if not self.source_matches_prefix(normalized_source_blob_name):
            logger.info("Skipping blob outside source prefix: %s", normalized_source_blob_name)
            return AutoBlobIndexResult(
                source_blob_name=normalized_source_blob_name,
                target_blob_name=None,
                storage_url=None,
                indexed_sections=0,
                status="skipped-prefix",
            )

        if not self.is_supported(normalized_source_blob_name):
            logger.info("Skipping unsupported blob type: %s", normalized_source_blob_name)
            return AutoBlobIndexResult(
                source_blob_name=normalized_source_blob_name,
                target_blob_name=None,
                storage_url=None,
                indexed_sections=0,
                status="skipped-extension",
            )

        category = self.category_for_blob(normalized_source_blob_name)
        if category is None:
            logger.info("Skipping blob without a per-bot folder: %s", normalized_source_blob_name)
            return AutoBlobIndexResult(
                source_blob_name=normalized_source_blob_name,
                target_blob_name=None,
                storage_url=None,
                indexed_sections=0,
                status="skipped-no-category",
            )

        await self.ensure_index()

        if self.is_archive(normalized_source_blob_name, content):
            return await self.index_archive_blob(
                normalized_source_blob_name=normalized_source_blob_name,
                content=content,
                category=category,
            )

        filename = os.path.basename(normalized_source_blob_name)
        file_wrapper = self.build_file(filename, content)

        try:
            if self.section_builder is not None:
                sections = await self.section_builder(
                    file=file_wrapper,
                    file_processors=self.file_processors,
                    category=category,
                )
            else:
                sections = await parse_file(
                    file=file_wrapper,
                    file_processors=self.file_processors,
                    category=category,
                    force_generic=self.config.force_generic_parsing,
                )
        finally:
            file_wrapper.close()

        if self.config.mirror_blob:
            target_blob_name = self.target_blob_name_for_source(normalized_source_blob_name)
            target_content_type = self.content_type_for_filename(filename, content_type)
            storage_url = await self.blob_manager.upload_blob_data(
                io.BytesIO(content),
                target_blob_name,
                content_type=target_content_type,
            )
        else:
            # No mirror: index in place, storageUrl points at the source blob (content2).
            target_blob_name = None
            storage_url = self.source_storage_url(normalized_source_blob_name)

        remove_kwargs = self.build_remove_kwargs(
            category=category,
            filename=filename,
            target_blob_name=target_blob_name,
            storage_url=storage_url,
        )
        await self.search_manager.remove_content(**remove_kwargs)

        if not sections:
            logger.info("No searchable sections extracted from %s; index cleared for that file", filename)
            return AutoBlobIndexResult(
                source_blob_name=normalized_source_blob_name,
                target_blob_name=target_blob_name,
                storage_url=storage_url,
                indexed_sections=0,
                status="copied-no-content" if self.config.mirror_blob else "no-content",
            )

        await self.search_manager.update_content(sections, url=storage_url)
        return AutoBlobIndexResult(
            source_blob_name=normalized_source_blob_name,
            target_blob_name=target_blob_name,
            storage_url=storage_url,
            indexed_sections=len(sections),
            status="indexed",
        )

    async def index_archive_blob(
        self,
        *,
        normalized_source_blob_name: str,
        content: bytes,
        category: str,
    ) -> AutoBlobIndexResult:
        """Index one archive package: several feed documents plus the images they reference.

        Everything is mirrored under `<target_prefix>/<archive stem>/`, and that whole prefix is
        purged first so a re-uploaded archive can never leave a removed document behind.
        """
        if self.section_builder is None:
            raise RuntimeError("Archive indexing requires a section_builder that accepts an image_bundle")

        package_name = package_name_for_archive(normalized_source_blob_name)
        try:
            archive = expand_feed_archive(content)
        except zipfile.BadZipFile:
            logger.warning("Skipping unreadable archive: %s", normalized_source_blob_name)
            return AutoBlobIndexResult(
                source_blob_name=normalized_source_blob_name,
                target_blob_name=None,
                storage_url=None,
                indexed_sections=0,
                status="skipped-bad-archive",
            )

        await self.purge_package(package_name, category)

        if not archive.documents:
            logger.info("Archive '%s' contains no feed documents", normalized_source_blob_name)
            return AutoBlobIndexResult(
                source_blob_name=normalized_source_blob_name,
                target_blob_name=None,
                storage_url=None,
                indexed_sections=0,
                status="archive-no-content",
            )

        descriptions = await describe_archive_images(
            archive.images.values(),
            describer=self.archive_options.describer,
            cache=self.archive_options.description_cache,
            concurrency=self.archive_options.describe_concurrency,
            max_images=self.archive_options.max_images,
        )

        target_prefix = normalize_prefix(self.config.target_prefix)
        for asset in archive.images.values():
            await self.blob_manager.upload_blob_data(
                io.BytesIO(asset.data),
                image_blob_name(target_prefix, package_name, asset.filename),
                content_type=self.content_type_for_filename(asset.filename, None),
            )

        image_bundle = build_image_bundle(
            archive.images.values(),
            descriptions,
            target_prefix=target_prefix,
            package_name=package_name,
            content_root=self.archive_options.content_root,
        )

        indexed_sections = 0
        for document in archive.documents:
            file_wrapper = self.build_file(document.name, document.data)
            try:
                sections = await self.section_builder(
                    file=file_wrapper,
                    file_processors=self.file_processors,
                    category=category,
                    image_bundle=image_bundle,
                )
            finally:
                file_wrapper.close()

            target_blob_name = document_blob_name(target_prefix, package_name, document.name)
            storage_url = await self.blob_manager.upload_blob_data(
                io.BytesIO(document.data),
                target_blob_name,
                content_type=self.content_type_for_filename(document.name, None),
            )
            if not sections:
                logger.info("No searchable sections extracted from '%s' in archive '%s'", document.name, package_name)
                continue
            await self.search_manager.update_content(sections, url=storage_url)
            indexed_sections += len(sections)

        logger.info(
            "Indexed archive '%s': %d document(s), %d image(s), %d described, %d section(s)",
            normalized_source_blob_name,
            len(archive.documents),
            len(archive.images),
            len(descriptions),
            indexed_sections,
        )
        return AutoBlobIndexResult(
            source_blob_name=normalized_source_blob_name,
            target_blob_name=self.package_blob_prefix(package_name),
            storage_url=self.package_storage_url_prefix(package_name),
            indexed_sections=indexed_sections,
            status="indexed" if indexed_sections else "archive-no-content",
        )

    async def index_blob_from_storage(self, *, blob_name: str) -> AutoBlobIndexResult:
        normalized_source_blob_name = self.normalize_source_blob_name(blob_name)
        if not self.source_matches_prefix(normalized_source_blob_name):
            logger.info("Skipping blob outside source prefix: %s", normalized_source_blob_name)
            return AutoBlobIndexResult(
                source_blob_name=normalized_source_blob_name,
                target_blob_name=None,
                storage_url=None,
                indexed_sections=0,
                status="skipped-prefix",
            )

        if not self.is_supported(normalized_source_blob_name):
            logger.info("Skipping unsupported blob type: %s", normalized_source_blob_name)
            return AutoBlobIndexResult(
                source_blob_name=normalized_source_blob_name,
                target_blob_name=None,
                storage_url=None,
                indexed_sections=0,
                status="skipped-extension",
            )

        source_blob = await self.blob_manager.download_blob(
            normalized_source_blob_name, container=self.config.source_container
        )
        if source_blob is None:
            logger.warning("Source blob not found for auto-indexing: %s", normalized_source_blob_name)
            return AutoBlobIndexResult(
                source_blob_name=normalized_source_blob_name,
                target_blob_name=None,
                storage_url=None,
                indexed_sections=0,
                status="missing-source",
            )

        content, properties = source_blob
        content_type = None
        content_settings = properties.get("content_settings") or {}
        if isinstance(content_settings, dict):
            content_type = content_settings.get("content_type")

        return await self.index_blob(
            blob_name=normalized_source_blob_name,
            content=content,
            content_type=content_type,
        )

    async def delete_blob(self, *, blob_name: str) -> AutoBlobIndexResult:
        normalized_source_blob_name = self.normalize_source_blob_name(blob_name)
        if not self.source_matches_prefix(normalized_source_blob_name):
            logger.info("Skipping delete for blob outside source prefix: %s", normalized_source_blob_name)
            return AutoBlobIndexResult(
                source_blob_name=normalized_source_blob_name,
                target_blob_name=None,
                storage_url=None,
                indexed_sections=0,
                status="skipped-prefix",
            )

        if not self.is_supported(normalized_source_blob_name):
            logger.info("Skipping delete for unsupported blob type: %s", normalized_source_blob_name)
            return AutoBlobIndexResult(
                source_blob_name=normalized_source_blob_name,
                target_blob_name=None,
                storage_url=None,
                indexed_sections=0,
                status="skipped-extension",
            )

        category = self.category_for_blob(normalized_source_blob_name)
        if category is None:
            logger.info("Skipping delete for blob without a per-bot folder: %s", normalized_source_blob_name)
            return AutoBlobIndexResult(
                source_blob_name=normalized_source_blob_name,
                target_blob_name=None,
                storage_url=None,
                indexed_sections=0,
                status="skipped-no-category",
            )

        filename = os.path.basename(normalized_source_blob_name)

        if self.archive_mode_enabled():
            # The blob is already gone, so its payload cannot be sniffed the way index_blob does.
            # Clearing the package prefix unconditionally covers an archive that arrived under any
            # extension, and is a no-op for a file that was not one (nothing was ever mirrored to
            # `<target>/<stem>/`). A plain document then falls through to the single-file delete.
            package_name = package_name_for_archive(normalized_source_blob_name)
            removed_package_blobs = await self.purge_package(package_name, category)
            if self.is_archive(normalized_source_blob_name) or removed_package_blobs:
                return AutoBlobIndexResult(
                    source_blob_name=normalized_source_blob_name,
                    target_blob_name=self.package_blob_prefix(package_name),
                    storage_url=None,
                    indexed_sections=0,
                    status="deleted",
                )

        if not self.config.mirror_blob:
            # No-mirror mode: nothing was copied into `content`, and the source blob is already gone.
            # Only purge the indexed docs for that exact source storageUrl within the bot's category.
            storage_url = self.source_storage_url(normalized_source_blob_name)
            await self.search_manager.remove_content(**self.build_remove_kwargs(
                category=category,
                filename=filename,
                target_blob_name=None,
                storage_url=storage_url,
            ))
            return AutoBlobIndexResult(
                source_blob_name=normalized_source_blob_name,
                target_blob_name=None,
                storage_url=storage_url,
                indexed_sections=0,
                status="deleted",
            )

        target_blob_name = self.target_blob_name_for_source(normalized_source_blob_name)
        storage_url = self.storage_url_for_target_blob(target_blob_name) if self.config.remove_by_storage_url else None
        if self.config.remove_by_storage_url and storage_url is None:
            raise RuntimeError("Blob manager must provide url_for_blob_name when remove_by_storage_url is enabled")
        remove_kwargs = self.build_remove_kwargs(
            category=category,
            filename=filename,
            target_blob_name=target_blob_name,
            storage_url=storage_url,
        )
        await self.search_manager.remove_content(**remove_kwargs)
        await self.blob_manager.remove_blob_name(target_blob_name)
        return AutoBlobIndexResult(
            source_blob_name=normalized_source_blob_name,
            target_blob_name=target_blob_name,
            storage_url=None,
            indexed_sections=0,
            status="deleted",
        )
