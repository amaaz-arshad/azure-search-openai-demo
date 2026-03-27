import asyncio
import io
import logging
import mimetypes
import os
from dataclasses import dataclass
from typing import Optional

from .blobmanager import BlobManager
from .fileprocessor import FileProcessor
from .filestrategy import parse_file
from .listfilestrategy import File
from .searchmanager import SearchManager

logger = logging.getLogger("scripts")


@dataclass(frozen=True)
class AutoBlobIndexerConfig:
    trigger_container: str
    source_prefix: str
    target_prefix: str
    category: str
    allowed_extensions: frozenset[str]
    manage_search_index: bool = True


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
    ):
        self.config = config
        self.blob_manager = blob_manager
        self.search_manager = search_manager
        self.file_processors = file_processors
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
        return normalized_blob_name == source_prefix or normalized_blob_name.startswith(f"{source_prefix}/")

    def target_blob_name_for_source(self, blob_name: str) -> str:
        normalized_blob_name = self.normalize_source_blob_name(blob_name)
        filename = os.path.basename(normalized_blob_name)
        target_prefix = normalize_prefix(self.config.target_prefix)
        if target_prefix:
            return f"{target_prefix}/{filename}"
        return filename

    def is_supported(self, blob_name: str) -> bool:
        filename = os.path.basename(self.normalize_source_blob_name(blob_name))
        extension = os.path.splitext(filename)[1].lower()
        return extension in self.config.allowed_extensions and extension in self.file_processors

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

        await self.ensure_index()

        filename = os.path.basename(normalized_source_blob_name)
        file_wrapper = self.build_file(filename, content)

        try:
            sections = await parse_file(
                file=file_wrapper,
                file_processors=self.file_processors,
                category=self.config.category,
            )
        finally:
            file_wrapper.close()

        target_blob_name = self.target_blob_name_for_source(normalized_source_blob_name)
        target_content_type = self.content_type_for_filename(filename, content_type)
        storage_url = await self.blob_manager.upload_blob_data(
            io.BytesIO(content),
            target_blob_name,
            content_type=target_content_type,
        )

        await self.search_manager.remove_content(
            path=filename,
            category=self.config.category,
            storage_url_suffix=target_blob_name,
        )

        if not sections:
            logger.info("No searchable sections extracted from %s; blob copied but index cleared for that file", filename)
            return AutoBlobIndexResult(
                source_blob_name=normalized_source_blob_name,
                target_blob_name=target_blob_name,
                storage_url=storage_url,
                indexed_sections=0,
                status="copied-no-content",
            )

        await self.search_manager.update_content(sections, url=storage_url)
        return AutoBlobIndexResult(
            source_blob_name=normalized_source_blob_name,
            target_blob_name=target_blob_name,
            storage_url=storage_url,
            indexed_sections=len(sections),
            status="indexed",
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

        source_blob = await self.blob_manager.download_blob(normalized_source_blob_name)
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

        filename = os.path.basename(normalized_source_blob_name)
        target_blob_name = self.target_blob_name_for_source(normalized_source_blob_name)
        await self.search_manager.remove_content(
            path=filename,
            category=self.config.category,
            storage_url_suffix=target_blob_name,
        )
        await self.blob_manager.remove_blob_name(target_blob_name)
        return AutoBlobIndexResult(
            source_blob_name=normalized_source_blob_name,
            target_blob_name=target_blob_name,
            storage_url=None,
            indexed_sections=0,
            status="deleted",
        )
