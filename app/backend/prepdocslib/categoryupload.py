import base64
import io
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import unquote, urlparse

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
    Strategy for uploading shared files into an arbitrary search category.
    Files are stored directly under <category>/ in blob storage. Hidden manifest
    blobs under <category>/.managed-uploads/ track which filenames are owned by
    this manager so built-in category content is left untouched.
    """

    def __init__(
        self,
        search_info: SearchInfo,
        file_processors: dict[str, FileProcessor],
        blob_manager: BlobManager,
        search_field_name_embedding: Optional[str] = None,
        embeddings: Optional[OpenAIEmbeddings] = None,
    ):
        self.file_processors = file_processors
        self.embeddings = embeddings
        self.search_info = search_info
        self.blob_manager = blob_manager
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

    def storage_url_to_blob_name(self, storage_url: Optional[str]) -> Optional[str]:
        if not storage_url:
            return None
        parsed_url = urlparse(storage_url)
        decoded_path = unquote(parsed_url.path).lstrip("/")
        container_prefix = f"{self.blob_manager.container}/"
        if decoded_path.startswith(container_prefix):
            return decoded_path[len(container_prefix) :]
        return None

    def is_own_storage_url(self, storage_url: Optional[str], category: str, filename: str) -> bool:
        blob_name = self.storage_url_to_blob_name(storage_url)
        if blob_name is None:
            return False
        return blob_name == self.file_blob_name(category, filename)

    def manifest_category_from_blob_name(self, blob_name: str) -> Optional[str]:
        match = MANAGED_UPLOAD_MANIFEST_PATTERN.match(blob_name)
        if not match:
            return None
        return match.group("category")

    def manifest_to_entry(self, manifest: CategoryUploadManifest) -> CategoryUploadEntry:
        return CategoryUploadEntry(
            category=manifest.category,
            filename=self.logical_filename(manifest.filename),
            storage_url=manifest.storage_url,
            uploaded_at=manifest.uploaded_at,
        )

    def entry_from_manifest_blob(self, manifest_blob: BlobListEntry) -> Optional[CategoryUploadEntry]:
        manifest_category = self.manifest_category_from_blob_name(manifest_blob.name)
        if manifest_category is None:
            return None
        token = manifest_blob.name.rsplit("/", 1)[-1][:-5]
        try:
            filename = self.decode_token(token)
        except Exception:
            logger.warning("Skipping unreadable managed upload manifest blob %s", manifest_blob.name)
            return None
        uploaded_at = manifest_blob.last_modified.isoformat() if manifest_blob.last_modified is not None else None
        return CategoryUploadEntry(
            category=manifest_category,
            filename=self.logical_filename(filename),
            storage_url=self.blob_url_for_name(self.file_blob_name(manifest_category, filename)),
            uploaded_at=uploaded_at,
        )

    async def iter_manifest_blobs(self, category: Optional[str] = None) -> list[BlobListEntry]:
        if category is not None:
            normalized_category = self.normalize_category(category)
            return [
                blob
                for blob in await self.blob_manager.list_blobs(f"{self.manifest_prefix(normalized_category)}/")
                if MANAGED_UPLOAD_MANIFEST_PATTERN.match(blob.name)
            ]

        manifest_blobs: list[BlobListEntry] = []
        top_level_prefixes = await self.blob_manager.list_blob_prefixes()
        for top_level_prefix in top_level_prefixes:
            normalized_prefix = top_level_prefix.strip("/\\")
            if not normalized_prefix:
                continue
            category_name = normalized_prefix.split("/", 1)[0]
            if not MANAGED_UPLOAD_CATEGORY_PATTERN.fullmatch(category_name):
                continue
            manifest_blobs.extend(
                [
                    blob
                    for blob in await self.blob_manager.list_blobs(f"{self.manifest_prefix(category_name)}/")
                    if MANAGED_UPLOAD_MANIFEST_PATTERN.match(blob.name)
                ]
            )
        return manifest_blobs

    async def list_category_counts(self) -> dict[str, int]:
        category_counts: dict[str, int] = {}
        for manifest_blob in await self.iter_manifest_blobs():
            manifest_category = self.manifest_category_from_blob_name(manifest_blob.name)
            if manifest_category is None:
                continue
            category_counts[manifest_category] = category_counts.get(manifest_category, 0) + 1
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

    async def list_upload_documents(self, filename: str, category: str) -> list[dict]:
        manifest = await self.get_manifest(category, filename)
        if manifest is None:
            return []
        documents = await self.search_manager.list_documents(path=filename, category=self.normalize_category(category))
        return [
            document
            for document in documents
            if document.get("storageUrl") == manifest.storage_url
        ]

    async def delete_documents_for_storage_url(self, filename: str, category: str, storage_url: Optional[str]) -> None:
        if not storage_url:
            return
        documents = await self.search_manager.list_documents(path=filename, category=self.normalize_category(category))
        document_ids = [document["id"] for document in documents if document.get("storageUrl") == storage_url]
        await self.search_manager.delete_documents_by_ids(document_ids)

    async def remove_stale_upload_documents(self, filename: str, category: str, keep_storage_url: Optional[str]) -> None:
        documents = await self.list_upload_documents(filename, category=category)
        document_ids = [
            document["id"]
            for document in documents
            if keep_storage_url is None or document.get("storageUrl") != keep_storage_url
        ]
        await self.search_manager.delete_documents_by_ids(document_ids)

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
        filename: str,
        category: str,
        new_blob_name: Optional[str],
        new_storage_url: Optional[str],
    ) -> None:
        await self.delete_documents_for_storage_url(filename, category=category, storage_url=new_storage_url)
        if new_blob_name is not None:
            await self.blob_manager.remove_blob_name(new_blob_name)

    async def has_conflicting_non_upload_document(self, filename: str, category: str) -> bool:
        documents = await self.search_manager.list_documents(path=filename, category=self.normalize_category(category))
        manifest = await self.get_manifest(category, filename)
        if manifest is None:
            return len(documents) > 0
        for document in documents:
            if document.get("storageUrl") != manifest.storage_url:
                return True
        return False

    async def add_file(self, file: File, category: str, upload_id: Optional[str] = None) -> CategoryUploadAddResult:
        normalized_category = self.normalize_category(category)
        filename = self.logical_filename(file.filename())
        file_extension = os.path.splitext(filename)[1].lower()
        if file_extension not in self.file_processors:
            raise ValueError(f"Unsupported file type: {filename}")
        existing_manifest = await self.get_manifest(normalized_category, filename)
        if await self.has_conflicting_non_upload_document(filename, category=normalized_category):
            raise ValueError(
                f"Filename '{filename}' conflicts with existing {normalized_category} content. Rename the file and upload it again."
            )

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
            await self.remove_stale_upload_documents(
                filename,
                category=normalized_category,
                keep_storage_url=None,
            )
            new_blob_name = self.file_blob_name(normalized_category, filename)
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
                replaced_existing=existing_manifest is not None,
            )
        except ChatbotUploadCancelled:
            await self.cleanup_canceled_upload(
                filename,
                category=normalized_category,
                new_blob_name=new_blob_name,
                new_storage_url=new_storage_url,
            )
            raise
        except Exception:
            await self.cleanup_canceled_upload(
                filename,
                category=normalized_category,
                new_blob_name=new_blob_name,
                new_storage_url=new_storage_url,
            )
            raise

    async def remove_file(self, filename: str, category: str) -> None:
        normalized_category = self.normalize_category(category)
        normalized_filename = self.logical_filename(filename)
        await self.remove_stale_upload_documents(
            normalized_filename,
            category=normalized_category,
            keep_storage_url=None,
        )
        await self.remove_stale_blobs(
            normalized_filename,
            category=normalized_category,
            keep_blob_name=None,
        )
        await self.remove_manifest(normalized_category, normalized_filename)

    async def iter_manifest_blob_names(self, category: Optional[str] = None) -> list[str]:
        return [blob.name for blob in await self.iter_manifest_blobs(category=category)]

    async def list_entries(self, category: Optional[str] = None) -> list[CategoryUploadEntry]:
        entries = [
            entry
            for entry in (self.entry_from_manifest_blob(blob) for blob in await self.iter_manifest_blobs(category=category))
            if entry is not None
        ]
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
        categories = [self.normalize_category(category)] if category is not None else await self.list_categories()

        for managed_category in categories:
            entries = await self.list_entries(category=managed_category)
            for entry in entries:
                try:
                    await self.remove_file(entry.filename, managed_category)
                    deleted.append(entry)
                except Exception as error:
                    logger.error(
                        "Failed to remove managed upload '%s' from '%s': %s",
                        entry.filename,
                        managed_category,
                        error,
                    )
                    failed.append(
                        {
                            "category": managed_category,
                            "filename": entry.filename,
                            "message": "Unexpected delete failure",
                        }
                    )

        return deleted, failed
