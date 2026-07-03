import base64
import io
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional
from urllib.parse import unquote

from .blobmanager import BlobListEntry, BlobManager
from .embeddings import OpenAIEmbeddings
from .fileprocessor import FileProcessor
from .filestrategy import ChatbotUploadCancelled, parse_file
from .listfilestrategy import File
from .searchmanager import SearchManager
from .strategy import SearchInfo

logger = logging.getLogger("scripts")

MANAGED_UPLOAD_METADATA_FOLDER = ".managed-uploads"
MANAGED_UPLOAD_CATEGORY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MANAGED_UPLOAD_MANIFEST_PATTERN = re.compile(
    rf"^(?P<category>[a-z0-9][a-z0-9_-]*)/{MANAGED_UPLOAD_METADATA_FOLDER}/manifests/(?P<token>[^/]+)\.json$"
)


@dataclass(frozen=True)
class CategoryUploadManifest:
    category: str
    filename: str
    blob_name: str
    storage_url: str
    upload_id: str
    uploaded_at: str
    file_extension: Optional[str] = None


@dataclass(frozen=True)
class CategoryUploadEntry:
    category: str
    filename: str
    storage_url: str
    uploaded_at: Optional[str] = None


@dataclass(frozen=True)
class CategoryUploadPage:
    entries: list[CategoryUploadEntry]
    total_count: int
    page: int
    page_size: int


@dataclass(frozen=True)
class CategoryUploadAddResult:
    entry: CategoryUploadEntry
    replaced_existing: bool


class CategoryUploadStrategy:
    """
    Strategy for managing the shared content files of a search category.
    Every ingestion path (this manager, the prepdocs scripts, and the feed
    auto-indexers) stores a category's source files flat at <category>/<filename>
    in blob storage, so listing and deletion are driven by those blobs directly —
    files show up here no matter which path uploaded them. Hidden manifest blobs
    under <category>/.managed-uploads/ additionally record the uploads this
    manager performed itself.
    """

    def __init__(
        self,
        search_info: SearchInfo,
        file_processors: dict[str, FileProcessor],
        blob_manager: BlobManager,
        search_field_name_embedding: Optional[str] = None,
        embeddings: Optional[OpenAIEmbeddings] = None,
        known_categories: Optional[Iterable[str]] = None,
    ):
        self.file_processors = file_processors
        self.embeddings = embeddings
        self.search_info = search_info
        self.blob_manager = blob_manager
        self.known_categories = {
            name
            for name in (known_categories or [])
            if MANAGED_UPLOAD_CATEGORY_PATTERN.fullmatch(name)
        }
        self.search_manager = SearchManager(
            search_info=self.search_info,
            search_analyzer_name=None,
            use_acls=False,
            use_parent_index_projection=False,
            embeddings=self.embeddings,
            field_name_embedding=search_field_name_embedding,
            search_images=False,
            enforce_access_control=False,
        )

    @staticmethod
    def encode_token(value: str) -> str:
        return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")

    @staticmethod
    def decode_token(value: str) -> str:
        padded_value = value + "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(padded_value.encode("ascii")).decode("utf-8")

    def normalize_category(self, category: str) -> str:
        normalized_category = (category or "").strip().lower()
        if not normalized_category:
            raise ValueError("Category is required.")
        if not MANAGED_UPLOAD_CATEGORY_PATTERN.fullmatch(normalized_category):
            raise ValueError("Category must use lowercase letters, numbers, hyphens, or underscores only.")
        return normalized_category

    def logical_filename(self, filename: str) -> str:
        return os.path.basename(filename)

    def filename_token(self, filename: str) -> str:
        return self.encode_token(self.logical_filename(filename))

    def upload_token(self, upload_id: str) -> str:
        return self.encode_token(upload_id)

    def category_token(self, category: str) -> str:
        return self.encode_token(self.normalize_category(category))

    def storage_prefix(self, category: str) -> str:
        return self.normalize_category(category)

    def manifest_prefix(self, category: str) -> str:
        return f"{self.storage_prefix(category)}/{MANAGED_UPLOAD_METADATA_FOLDER}/manifests"

    def cancel_prefix(self, category: str) -> str:
        return f"{self.storage_prefix(category)}/{MANAGED_UPLOAD_METADATA_FOLDER}/cancel"

    def file_blob_name(self, category: str, filename: str) -> str:
        return f"{self.storage_prefix(category)}/{self.logical_filename(filename)}"

    def manifest_blob_name(self, category: str, filename: str) -> str:
        return f"{self.manifest_prefix(category)}/{self.filename_token(filename)}.json"

    def cancel_blob_name(self, category: str, upload_id: str) -> str:
        return f"{self.cancel_prefix(category)}/{self.upload_token(upload_id)}.cancel"

    def blob_url_for_name(self, blob_name: str) -> str:
        return unquote(f"{self.blob_manager.endpoint}/{self.blob_manager.container}/{blob_name}")

    def manifest_to_entry(self, manifest: CategoryUploadManifest) -> CategoryUploadEntry:
        return CategoryUploadEntry(
            category=manifest.category,
            filename=self.logical_filename(manifest.filename),
            storage_url=manifest.storage_url,
            uploaded_at=manifest.uploaded_at,
        )

    def entry_from_file_blob(self, category: str, blob: BlobListEntry) -> Optional[CategoryUploadEntry]:
        file_prefix = f"{self.storage_prefix(category)}/"
        if not blob.name.startswith(file_prefix):
            return None
        relative_name = blob.name[len(file_prefix) :]
        # Only blobs directly under <category>/ are content files; nested blobs are
        # metadata (.managed-uploads/, .manifests/), feed source folders, or
        # per-user chatbot uploads and must not surface here.
        if not relative_name or "/" in relative_name:
            return None
        return CategoryUploadEntry(
            category=category,
            filename=relative_name,
            storage_url=self.blob_url_for_name(blob.name),
            uploaded_at=blob.last_modified.isoformat() if blob.last_modified is not None else None,
        )

    async def list_category_files(self, category: str) -> list[CategoryUploadEntry]:
        normalized_category = self.normalize_category(category)
        blobs = await self.blob_manager.list_blobs(f"{self.storage_prefix(normalized_category)}/")
        return [
            entry
            for entry in (self.entry_from_file_blob(normalized_category, blob) for blob in blobs)
            if entry is not None
        ]

    async def has_managed_manifests(self, category: str) -> bool:
        normalized_category = self.normalize_category(category)
        blobs = await self.blob_manager.list_blobs(f"{self.manifest_prefix(normalized_category)}/")
        return any(MANAGED_UPLOAD_MANIFEST_PATTERN.match(blob.name) for blob in blobs)

    async def list_indexed_categories(self) -> set[str]:
        try:
            facet_categories = await self.search_manager.list_category_facets()
        except Exception:
            logger.warning(
                "Unable to list indexed categories from search; falling back to known and manifest categories",
                exc_info=True,
            )
            return set()
        return {name for name in facet_categories if MANAGED_UPLOAD_CATEGORY_PATTERN.fullmatch(name)}

    async def candidate_categories(self) -> list[str]:
        """Top-level blob prefixes that hold real category content. Gated to known
        chatbot categories, categories present in the search index, or categories
        with managed-upload manifests, so infrastructure prefixes (prompts/, bots/,
        log folders, ...) never surface as categories."""
        allowed_categories = self.known_categories | await self.list_indexed_categories()
        candidates: set[str] = set()
        for top_level_prefix in await self.blob_manager.list_blob_prefixes():
            normalized_prefix = top_level_prefix.strip("/\\")
            if not normalized_prefix:
                continue
            category_name = normalized_prefix.split("/", 1)[0]
            if not MANAGED_UPLOAD_CATEGORY_PATTERN.fullmatch(category_name):
                continue
            if category_name in allowed_categories or await self.has_managed_manifests(category_name):
                candidates.add(category_name)
        return sorted(candidates)

    async def list_category_counts(self) -> dict[str, int]:
        category_counts: dict[str, int] = {}
        for category_name in await self.candidate_categories():
            file_count = len(await self.list_category_files(category_name))
            if file_count:
                category_counts[category_name] = file_count
        return dict(sorted(category_counts.items()))

    async def get_manifest(self, category: str, filename: str) -> Optional[CategoryUploadManifest]:
        category = self.normalize_category(category)
        manifest_blob = await self.blob_manager.download_blob(self.manifest_blob_name(category, filename))
        if manifest_blob is None:
            return None

        try:
            payload, _ = manifest_blob
            manifest_data = json.loads(payload.decode("utf-8"))
            blob_name = str(manifest_data["blob_name"])
            storage_url = str(manifest_data.get("storage_url") or self.blob_url_for_name(blob_name))
            return CategoryUploadManifest(
                category=self.normalize_category(str(manifest_data.get("category") or category)),
                filename=self.logical_filename(str(manifest_data["filename"])),
                blob_name=blob_name,
                storage_url=storage_url,
                upload_id=str(manifest_data["upload_id"]),
                uploaded_at=str(manifest_data["uploaded_at"]),
                file_extension=manifest_data.get("file_extension"),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("Invalid category upload manifest for %s/%s", category, filename)
            return None

    async def save_manifest(self, manifest: CategoryUploadManifest) -> None:
        manifest_buffer = io.BytesIO(json.dumps(asdict(manifest)).encode("utf-8"))
        await self.blob_manager.upload_blob_data(
            manifest_buffer,
            self.manifest_blob_name(manifest.category, manifest.filename),
            content_type="application/json",
        )

    async def remove_manifest(self, category: str, filename: str) -> None:
        await self.blob_manager.remove_blob_name(self.manifest_blob_name(category, filename))

    async def request_cancel(self, category: str, upload_id: str) -> None:
        cancel_buffer = io.BytesIO(b"cancel")
        await self.blob_manager.upload_blob_data(
            cancel_buffer,
            self.cancel_blob_name(category, upload_id),
            content_type="text/plain",
        )

    async def is_cancel_requested(self, category: str, upload_id: str) -> bool:
        return await self.blob_manager.blob_exists(self.cancel_blob_name(category, upload_id))

    async def clear_cancel_request(self, category: str, upload_id: str) -> None:
        await self.blob_manager.remove_blob_name(self.cancel_blob_name(category, upload_id))

    async def delete_documents_for_storage_url(self, storage_url: Optional[str]) -> None:
        # storageUrl is the join key every ingestion path (managed upload, prepdocs
        # scripts, feed auto-indexers) stamps on its documents, so this removes a
        # file's documents regardless of which path indexed them.
        if not storage_url:
            return
        documents = await self.search_manager.list_documents(storage_url=storage_url)
        await self.search_manager.delete_documents_by_ids([document["id"] for document in documents])

    async def delete_documents_for_file(self, filename: str, category: str) -> None:
        normalized_category = self.normalize_category(category)
        normalized_filename = self.logical_filename(filename)
        storage_urls = {self.blob_url_for_name(self.file_blob_name(normalized_category, normalized_filename))}
        manifest = await self.get_manifest(normalized_category, normalized_filename)
        if manifest is not None and manifest.storage_url:
            storage_urls.add(manifest.storage_url)
        for storage_url in storage_urls:
            await self.delete_documents_for_storage_url(storage_url)

    async def list_managed_blob_names(self, filename: str, category: str) -> list[str]:
        blob_names = []
        file_blob_name = self.file_blob_name(category, filename)
        if await self.blob_manager.blob_exists(file_blob_name):
            blob_names.append(file_blob_name)
        manifest_blob_name = self.manifest_blob_name(category, filename)
        if await self.blob_manager.blob_exists(manifest_blob_name):
            blob_names.append(manifest_blob_name)
        return list(dict.fromkeys(blob_names))

    async def remove_stale_blobs(self, filename: str, category: str, keep_blob_name: Optional[str]) -> None:
        blob_names = await self.list_managed_blob_names(filename, category=category)
        for blob_name in blob_names:
            if keep_blob_name is not None and blob_name == keep_blob_name:
                continue
            await self.blob_manager.remove_blob_name(blob_name)

    async def cleanup_canceled_upload(
        self,
        new_blob_name: Optional[str],
        new_storage_url: Optional[str],
    ) -> None:
        await self.delete_documents_for_storage_url(new_storage_url)
        if new_blob_name is not None:
            await self.blob_manager.remove_blob_name(new_blob_name)

    async def add_file(self, file: File, category: str, upload_id: Optional[str] = None) -> CategoryUploadAddResult:
        normalized_category = self.normalize_category(category)
        filename = self.logical_filename(file.filename())
        file_extension = os.path.splitext(filename)[1].lower()
        if file_extension not in self.file_processors:
            raise ValueError(f"Unsupported file type: {filename}")
        existing_manifest = await self.get_manifest(normalized_category, filename)
        target_blob_name = self.file_blob_name(normalized_category, filename)
        replaced_existing = existing_manifest is not None or await self.blob_manager.blob_exists(target_blob_name)

        upload_id = upload_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        new_blob_name: Optional[str] = None
        new_storage_url: Optional[str] = None

        async def check_cancel() -> None:
            if await self.is_cancel_requested(normalized_category, upload_id):
                raise ChatbotUploadCancelled(filename)

        try:
            await check_cancel()
            sections = await parse_file(
                file,
                self.file_processors,
                normalized_category,
                check_cancel=check_cancel,
            )
            if not sections:
                raise ValueError(f"Unable to extract searchable content from {filename}")

            await check_cancel()
            # Replace any previous version of this file, no matter which ingestion
            # path (managed upload, script, feed) indexed it.
            await self.delete_documents_for_file(filename, category=normalized_category)
            new_blob_name = target_blob_name
            new_storage_url = await self.blob_manager.upload_blob_data(
                file.content,
                new_blob_name,
                content_type=getattr(file.content, "content_type", None),
            )

            await check_cancel()
            await self.search_manager.update_content(
                sections,
                url=new_storage_url,
                document_id_suffix=(
                    f"-{self.category_token(normalized_category)}-upload-{self.upload_token(upload_id)}"
                ),
            )

            await check_cancel()
            manifest = CategoryUploadManifest(
                category=normalized_category,
                filename=filename,
                blob_name=new_blob_name,
                storage_url=new_storage_url,
                upload_id=upload_id,
                uploaded_at=datetime.now(timezone.utc).isoformat(),
                file_extension=file_extension,
            )
            await self.save_manifest(manifest)
            return CategoryUploadAddResult(
                entry=self.manifest_to_entry(manifest),
                replaced_existing=replaced_existing,
            )
        except ChatbotUploadCancelled:
            await self.cleanup_canceled_upload(
                new_blob_name=new_blob_name,
                new_storage_url=new_storage_url,
            )
            raise
        except Exception:
            await self.cleanup_canceled_upload(
                new_blob_name=new_blob_name,
                new_storage_url=new_storage_url,
            )
            raise

    async def remove_sibling_chatbot_manifest(self, category: str, filename: str) -> None:
        # Per-bot chatbot uploads (ChatbotUploadStrategy) track the same
        # <category>/<filename> blob in <category>/.manifests/; drop that record too
        # so the bot's own upload list doesn't keep a ghost entry after an admin delete.
        blob_name = f"{self.storage_prefix(category)}/.manifests/{self.filename_token(filename)}.json"
        if await self.blob_manager.blob_exists(blob_name):
            await self.blob_manager.remove_blob_name(blob_name)

    async def remove_file(self, filename: str, category: str) -> None:
        normalized_category = self.normalize_category(category)
        normalized_filename = self.logical_filename(filename)
        await self.delete_documents_for_file(normalized_filename, category=normalized_category)
        await self.remove_stale_blobs(
            normalized_filename,
            category=normalized_category,
            keep_blob_name=None,
        )
        await self.remove_manifest(normalized_category, normalized_filename)
        await self.remove_sibling_chatbot_manifest(normalized_category, normalized_filename)

    async def list_entries(self, category: Optional[str] = None) -> list[CategoryUploadEntry]:
        if category is not None:
            normalized_category = self.normalize_category(category)
            if normalized_category not in await self.candidate_categories():
                return []
            entries = await self.list_category_files(normalized_category)
        else:
            entries = []
            for category_name in await self.candidate_categories():
                entries.extend(await self.list_category_files(category_name))
        return sorted(
            entries,
            key=lambda entry: (
                -(datetime.fromisoformat(entry.uploaded_at).timestamp()) if entry.uploaded_at else 0,
                entry.category,
                entry.filename.lower(),
            ),
        )

    async def list_categories(self) -> list[str]:
        return sorted((await self.list_category_counts()).keys())

    async def list_entries_page(
        self,
        category: Optional[str] = None,
        query: Optional[str] = None,
        page: int = 1,
        page_size: int = 15,
    ) -> CategoryUploadPage:
        if page < 1:
            raise ValueError("Page must be 1 or greater.")
        if page_size < 1 or page_size > 100:
            raise ValueError("Page size must be between 1 and 100.")

        normalized_query = (query or "").strip().lower()
        entries = await self.list_entries(category=category)
        if normalized_query:
            entries = [
                entry
                for entry in entries
                if normalized_query in entry.filename.lower() or normalized_query in entry.category.lower()
            ]

        total_count = len(entries)
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        return CategoryUploadPage(
            entries=entries[start_index:end_index],
            total_count=total_count,
            page=page,
            page_size=page_size,
        )

    async def remove_all_files(self, category: Optional[str] = None) -> tuple[list[CategoryUploadEntry], list[dict[str, str]]]:
        deleted: list[CategoryUploadEntry] = []
        failed: list[dict[str, str]] = []

        for entry in await self.list_entries(category=category):
            try:
                await self.remove_file(entry.filename, entry.category)
                deleted.append(entry)
            except Exception as error:
                logger.error(
                    "Failed to remove managed upload '%s' from '%s': %s",
                    entry.filename,
                    entry.category,
                    error,
                )
                failed.append(
                    {
                        "category": entry.category,
                        "filename": entry.filename,
                        "message": "Unexpected delete failure",
                    }
                )

        return deleted, failed
