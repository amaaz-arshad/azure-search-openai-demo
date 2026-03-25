import base64
import io
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

from pypdf import PdfReader

from .blobmanager import AdlsBlobManager, BaseBlobManager, BlobManager
from .embeddings import ImageEmbeddings, OpenAIEmbeddings
from .figureprocessor import FigureProcessor, MediaDescriptionStrategy, process_page_image
from .fileprocessor import FileProcessor
from .listfilestrategy import File, ListFileStrategy
from .mediadescriber import ContentUnderstandingDescriber
from .searchmanager import SearchManager, Section
from .strategy import DocumentAction, SearchInfo, Strategy
from .textprocessor import process_text

logger = logging.getLogger("scripts")


@dataclass(frozen=True)
class ChatbotUploadManifest:
    filename: str
    blob_name: str
    upload_id: str
    uploaded_at: str
    page_count: Optional[int] = None
    file_extension: Optional[str] = None
    user_identifier: Optional[str] = None


@dataclass(frozen=True)
class ChatbotUploadRules:
    allowed_extensions: Optional[frozenset[str]] = None
    max_total_pdf_pages: Optional[int] = None
    user_scoped: bool = False


class ChatbotUploadCancelled(Exception):
    def __init__(self, filename: str):
        super().__init__(f"Upload canceled for {filename}")
        self.filename = filename


async def parse_file(
    file: File,
    file_processors: dict[str, FileProcessor],
    category: Optional[str] = None,
    blob_manager: Optional[BaseBlobManager] = None,
    image_embeddings_client: Optional[ImageEmbeddings] = None,
    figure_processor: Optional[FigureProcessor] = None,
    user_oid: Optional[str] = None,
    check_cancel: Optional[Callable[[], Awaitable[None]]] = None,
) -> list[Section]:
    key = file.file_extension().lower()
    processor = file_processors.get(key)
    if processor is None:
        logger.info("Skipping '%s', no parser found.", file.filename())
        return []

    logger.info("Ingesting '%s'", file.filename())
    pages = []
    async for page in processor.parser.parse(content=file.content):
        if check_cancel is not None:
            await check_cancel()
        pages.append(page)

    if check_cancel is not None:
        await check_cancel()

    for page in pages:
        if check_cancel is not None:
            await check_cancel()
        for image in page.images:
            logger.info("Processing image '%s' on page %d", image.filename, page.page_num)
            await process_page_image(
                image=image,
                document_filename=file.filename(),
                blob_manager=blob_manager,
                image_embeddings_client=image_embeddings_client,
                figure_processor=figure_processor,
                user_oid=user_oid,
            )

    if check_cancel is not None:
        await check_cancel()

    sections = process_text(pages, file, processor.splitter, category)
    if check_cancel is not None:
        await check_cancel()
    return sections


class FileStrategy(Strategy):
    """
    Strategy for ingesting documents into a search service from files stored either locally or in a data lake storage account
    """

    def __init__(
        self,
        list_file_strategy: ListFileStrategy,
        blob_manager: BlobManager,
        search_info: SearchInfo,
        file_processors: dict[str, FileProcessor],
        document_action: DocumentAction = DocumentAction.Add,
        embeddings: Optional[OpenAIEmbeddings] = None,
        image_embeddings: Optional[ImageEmbeddings] = None,
        search_analyzer_name: Optional[str] = None,
        search_field_name_embedding: Optional[str] = None,
        use_acls: bool = False,
        category: Optional[str] = None,
        figure_processor: Optional[FigureProcessor] = None,
        enforce_access_control: bool = False,
        use_web_source: bool = False,
        use_sharepoint_source: bool = False,
    ):
        self.list_file_strategy = list_file_strategy
        self.blob_manager = blob_manager
        self.file_processors = file_processors
        self.document_action = document_action
        self.embeddings = embeddings
        self.image_embeddings = image_embeddings
        self.search_analyzer_name = search_analyzer_name
        self.search_field_name_embedding = search_field_name_embedding
        self.search_info = search_info
        self.use_acls = use_acls
        self.category = category
        self.figure_processor = figure_processor
        self.enforce_access_control = enforce_access_control
        self.use_web_source = use_web_source
        self.use_sharepoint_source = use_sharepoint_source

    def setup_search_manager(self):
        self.search_manager = SearchManager(
            self.search_info,
            self.search_analyzer_name,
            self.use_acls,
            False,  # use_parent_index_projection disabled for file-based ingestion
            self.embeddings,
            field_name_embedding=self.search_field_name_embedding,
            search_images=self.image_embeddings is not None,
            enforce_access_control=self.enforce_access_control,
            use_web_source=self.use_web_source,
            use_sharepoint_source=self.use_sharepoint_source,
        )

    async def setup(self):
        self.setup_search_manager()
        await self.search_manager.create_index()

        if (
            self.figure_processor is not None
            and self.figure_processor.strategy == MediaDescriptionStrategy.CONTENTUNDERSTANDING
        ):
            media_describer = await self.figure_processor.get_media_describer()
            if isinstance(media_describer, ContentUnderstandingDescriber):
                await media_describer.create_analyzer()
                self.figure_processor.mark_content_understanding_ready()

    async def run(self):
        self.setup_search_manager()
        blob_prefix = BaseBlobManager.normalize_blob_prefix(self.category)
        if self.document_action == DocumentAction.Add:
            files = self.list_file_strategy.list()
            async for file in files:
                try:
                    blob_url = await self.blob_manager.upload_blob(file, prefix=blob_prefix)
                    sections = await parse_file(
                        file,
                        self.file_processors,
                        self.category,
                        self.blob_manager,
                        self.image_embeddings,
                        figure_processor=self.figure_processor,
                    )
                    if sections:
                        await self.search_manager.update_content(sections, url=blob_url)
                finally:
                    if file:
                        file.close()
        elif self.document_action == DocumentAction.Remove:
            paths = self.list_file_strategy.list_paths()
            async for path in paths:
                await self.blob_manager.remove_blob(path, prefix=blob_prefix)
                await self.search_manager.remove_content(path)
        elif self.document_action == DocumentAction.RemoveAll:
            await self.blob_manager.remove_blob()
            await self.search_manager.remove_content()


class UploadUserFileStrategy:
    """
    Strategy for ingesting a file that has already been uploaded to a ADLS2 storage account
    """

    def __init__(
        self,
        search_info: SearchInfo,
        file_processors: dict[str, FileProcessor],
        blob_manager: AdlsBlobManager,
        search_field_name_embedding: Optional[str] = None,
        embeddings: Optional[OpenAIEmbeddings] = None,
        image_embeddings: Optional[ImageEmbeddings] = None,
        enforce_access_control: bool = False,
        figure_processor: Optional[FigureProcessor] = None,
    ):
        self.file_processors = file_processors
        self.embeddings = embeddings
        self.image_embeddings = image_embeddings
        self.search_info = search_info
        self.blob_manager = blob_manager
        self.figure_processor = figure_processor
        self.search_manager = SearchManager(
            search_info=self.search_info,
            search_analyzer_name=None,
            use_acls=True,
            use_parent_index_projection=False,
            embeddings=self.embeddings,
            field_name_embedding=search_field_name_embedding,
            search_images=image_embeddings is not None,
            enforce_access_control=enforce_access_control,
        )
        self.search_field_name_embedding = search_field_name_embedding

    async def add_file(self, file: File, user_oid: str):
        sections = await parse_file(
            file,
            self.file_processors,
            None,
            self.blob_manager,
            self.image_embeddings,
            figure_processor=self.figure_processor,
            user_oid=user_oid,
        )
        if sections:
            await self.search_manager.update_content(sections, url=file.url)

    async def remove_file(self, filename: str, oid: str):
        if filename is None or filename == "":
            logging.warning("Filename is required to remove a file")
            return
        await self.search_manager.remove_content(filename, oid)


class ChatbotUploadStrategy:
    """
    Strategy for chatbot-specific shared uploads stored in blob storage without per-user ACLs.
    """

    def __init__(
        self,
        chatbot_name: str,
        search_info: SearchInfo,
        file_processors: dict[str, FileProcessor],
        blob_manager: BlobManager,
        search_field_name_embedding: Optional[str] = None,
        embeddings: Optional[OpenAIEmbeddings] = None,
        rules: Optional[ChatbotUploadRules] = None,
    ):
        self.chatbot_name = chatbot_name
        self.file_processors = file_processors
        self.embeddings = embeddings
        self.search_info = search_info
        self.blob_manager = blob_manager
        self.rules = rules or ChatbotUploadRules()
        self.storage_root = self.chatbot_name
        self.legacy_storage_root = f"chatbot-uploads/{self.chatbot_name}"
        self.category = self.chatbot_name
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

    def logical_filename(self, filename: str) -> str:
        return os.path.basename(filename)

    def filename_token(self, filename: str) -> str:
        return self.encode_token(self.logical_filename(filename))

    def upload_token(self, upload_id: str) -> str:
        return self.encode_token(upload_id)

    def normalize_user_identifier(self, user_identifier: Optional[str]) -> Optional[str]:
        if not self.rules.user_scoped:
            return None
        normalized_user_identifier = (user_identifier or "").strip().lower()
        if not normalized_user_identifier:
            raise ValueError(f"{self.chatbot_name} uploads require a user identifier.")
        return normalized_user_identifier

    def user_token(self, user_identifier: Optional[str]) -> Optional[str]:
        normalized_user_identifier = self.normalize_user_identifier(user_identifier)
        if normalized_user_identifier is None:
            return None
        return self.encode_token(normalized_user_identifier)

    def storage_prefix(self, user_identifier: Optional[str] = None) -> str:
        user_token = self.user_token(user_identifier)
        if user_token is None:
            return self.storage_root
        return f"{self.storage_root}/{user_token}"

    def legacy_storage_prefix(self, user_identifier: Optional[str] = None) -> str:
        user_token = self.user_token(user_identifier)
        if user_token is None:
            return self.legacy_storage_root
        return f"{self.legacy_storage_root}/{user_token}/uploaded-files"

    def files_prefix(self, user_identifier: Optional[str] = None) -> str:
        return f"{self.legacy_storage_prefix(user_identifier)}/files"

    def manifest_prefix(self, user_identifier: Optional[str] = None) -> str:
        return f"{self.storage_prefix(user_identifier)}/.manifests"

    def legacy_manifest_prefix(self, user_identifier: Optional[str] = None) -> str:
        return f"{self.legacy_storage_prefix(user_identifier)}/.manifests"

    def cancel_prefix(self, user_identifier: Optional[str] = None) -> str:
        return f"{self.storage_prefix(user_identifier)}/.cancel"

    def legacy_cancel_prefix(self, user_identifier: Optional[str] = None) -> str:
        return f"{self.legacy_storage_prefix(user_identifier)}/.cancel"

    def file_blob_name(self, filename: str, user_identifier: Optional[str] = None) -> str:
        return f"{self.storage_prefix(user_identifier)}/{self.logical_filename(filename)}"

    def legacy_blob_name(self, filename: str, user_identifier: Optional[str] = None) -> str:
        return f"{self.legacy_storage_prefix(user_identifier)}/{self.logical_filename(filename)}"

    def version_blob_prefix(self, filename: str, user_identifier: Optional[str] = None) -> str:
        return f"{self.files_prefix(user_identifier)}/{self.filename_token(filename)}/"

    def version_blob_name(self, filename: str, upload_id: str, user_identifier: Optional[str] = None) -> str:
        return (
            f"{self.version_blob_prefix(filename, user_identifier)}"
            f"{self.upload_token(upload_id)}/{self.logical_filename(filename)}"
        )

    def manifest_blob_name(self, filename: str, user_identifier: Optional[str] = None) -> str:
        return f"{self.manifest_prefix(user_identifier)}/{self.filename_token(filename)}.json"

    def legacy_manifest_blob_name(self, filename: str, user_identifier: Optional[str] = None) -> str:
        return f"{self.legacy_manifest_prefix(user_identifier)}/{self.filename_token(filename)}.json"

    def cancel_blob_name(self, upload_id: str, user_identifier: Optional[str] = None) -> str:
        return f"{self.cancel_prefix(user_identifier)}/{self.upload_token(upload_id)}.cancel"

    def legacy_cancel_blob_name(self, upload_id: str, user_identifier: Optional[str] = None) -> str:
        return f"{self.legacy_cancel_prefix(user_identifier)}/{self.upload_token(upload_id)}.cancel"

    def is_supported(self, filename: str) -> bool:
        extension = os.path.splitext(filename)[1].lower()
        if extension not in self.file_processors:
            return False
        if self.rules.allowed_extensions is None:
            return True
        return extension in self.rules.allowed_extensions

    def is_own_storage_url(
        self,
        storage_url: Optional[str],
        filename: str,
        user_identifier: Optional[str] = None,
    ) -> bool:
        if not storage_url:
            return False
        return (
            storage_url.endswith(self.file_blob_name(filename, user_identifier))
            or storage_url.endswith(self.legacy_blob_name(filename, user_identifier))
            or self.version_blob_prefix(filename, user_identifier) in storage_url
        )

    async def get_manifest(
        self,
        filename: str,
        user_identifier: Optional[str] = None,
    ) -> Optional[ChatbotUploadManifest]:
        normalized_user_identifier = self.normalize_user_identifier(user_identifier)
        for manifest_blob_name in (
            self.manifest_blob_name(filename, normalized_user_identifier),
            self.legacy_manifest_blob_name(filename, normalized_user_identifier),
        ):
            manifest_blob = await self.blob_manager.download_blob(manifest_blob_name)
            if manifest_blob is None:
                continue

            try:
                payload, _ = manifest_blob
                manifest_data = json.loads(payload.decode("utf-8"))
                return ChatbotUploadManifest(
                    filename=self.logical_filename(manifest_data["filename"]),
                    blob_name=manifest_data["blob_name"],
                    upload_id=manifest_data["upload_id"],
                    uploaded_at=manifest_data["uploaded_at"],
                    page_count=manifest_data.get("page_count"),
                    file_extension=manifest_data.get("file_extension"),
                    user_identifier=manifest_data.get("user_identifier"),
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                logger.warning("Invalid upload manifest for %s", filename)

        return None

    async def save_manifest(self, manifest: ChatbotUploadManifest) -> None:
        manifest_buffer = io.BytesIO(json.dumps(asdict(manifest)).encode("utf-8"))
        await self.blob_manager.upload_blob_data(
            manifest_buffer,
            self.manifest_blob_name(manifest.filename, manifest.user_identifier),
            content_type="application/json",
        )

    async def remove_manifest(self, filename: str, user_identifier: Optional[str] = None) -> None:
        normalized_user_identifier = self.normalize_user_identifier(user_identifier)
        for manifest_blob_name in (
            self.manifest_blob_name(filename, normalized_user_identifier),
            self.legacy_manifest_blob_name(filename, normalized_user_identifier),
        ):
            if await self.blob_manager.blob_exists(manifest_blob_name):
                await self.blob_manager.remove_blob_name(manifest_blob_name)

    async def request_cancel(self, upload_id: str, user_identifier: Optional[str] = None) -> None:
        normalized_user_identifier = self.normalize_user_identifier(user_identifier)
        cancel_buffer = io.BytesIO(b"cancel")
        await self.blob_manager.upload_blob_data(
            cancel_buffer,
            self.cancel_blob_name(upload_id, normalized_user_identifier),
            content_type="text/plain",
        )

    async def is_cancel_requested(self, upload_id: str, user_identifier: Optional[str] = None) -> bool:
        normalized_user_identifier = self.normalize_user_identifier(user_identifier)
        return await self.blob_manager.blob_exists(
            self.cancel_blob_name(upload_id, normalized_user_identifier)
        ) or await self.blob_manager.blob_exists(self.legacy_cancel_blob_name(upload_id, normalized_user_identifier))

    async def clear_cancel_request(self, upload_id: str, user_identifier: Optional[str] = None) -> None:
        normalized_user_identifier = self.normalize_user_identifier(user_identifier)
        for cancel_blob_name in (
            self.cancel_blob_name(upload_id, normalized_user_identifier),
            self.legacy_cancel_blob_name(upload_id, normalized_user_identifier),
        ):
            if await self.blob_manager.blob_exists(cancel_blob_name):
                await self.blob_manager.remove_blob_name(cancel_blob_name)

    async def list_upload_documents(
        self,
        filename: str,
        user_identifier: Optional[str] = None,
    ) -> list[dict]:
        normalized_user_identifier = self.normalize_user_identifier(user_identifier)
        documents = await self.search_manager.list_documents(
            path=filename,
            category=self.category,
            user=normalized_user_identifier,
        )
        return [
            document
            for document in documents
            if self.is_own_storage_url(document.get("storageUrl"), filename, user_identifier=normalized_user_identifier)
        ]

    async def delete_documents_for_storage_url(
        self,
        filename: str,
        storage_url: Optional[str],
        user_identifier: Optional[str] = None,
    ) -> None:
        if not storage_url:
            return
        documents = await self.list_upload_documents(filename, user_identifier=user_identifier)
        document_ids = [document["id"] for document in documents if document.get("storageUrl") == storage_url]
        await self.search_manager.delete_documents_by_ids(document_ids)

    async def remove_stale_upload_documents(
        self,
        filename: str,
        keep_storage_url: Optional[str],
        user_identifier: Optional[str] = None,
    ) -> None:
        documents = await self.list_upload_documents(filename, user_identifier=user_identifier)
        document_ids = [
            document["id"]
            for document in documents
            if keep_storage_url is None or document.get("storageUrl") != keep_storage_url
        ]
        await self.search_manager.delete_documents_by_ids(document_ids)

    async def list_managed_blob_names(
        self,
        filename: str,
        user_identifier: Optional[str] = None,
    ) -> list[str]:
        normalized_user_identifier = self.normalize_user_identifier(user_identifier)
        blob_names = []
        current_blob_name = self.file_blob_name(filename, normalized_user_identifier)
        if await self.blob_manager.blob_exists(current_blob_name):
            blob_names.append(current_blob_name)
        legacy_blob_name = self.legacy_blob_name(filename, normalized_user_identifier)
        if await self.blob_manager.blob_exists(legacy_blob_name):
            blob_names.append(legacy_blob_name)
        blob_names.extend(await self.blob_manager.list_blob_names(self.version_blob_prefix(filename, normalized_user_identifier)))
        return blob_names

    async def remove_stale_blobs(
        self,
        filename: str,
        keep_blob_name: Optional[str],
        user_identifier: Optional[str] = None,
    ) -> None:
        blob_names = await self.list_managed_blob_names(filename, user_identifier=user_identifier)
        for blob_name in blob_names:
            if keep_blob_name is not None and blob_name == keep_blob_name:
                continue
            await self.blob_manager.remove_blob_name(blob_name)

    async def cleanup_canceled_upload(
        self,
        filename: str,
        new_blob_name: Optional[str],
        new_storage_url: Optional[str],
        user_identifier: Optional[str] = None,
    ) -> None:
        await self.delete_documents_for_storage_url(filename, new_storage_url, user_identifier=user_identifier)
        if new_blob_name is not None:
            await self.blob_manager.remove_blob_name(new_blob_name)

    async def has_conflicting_non_upload_document(
        self,
        filename: str,
        user_identifier: Optional[str] = None,
    ) -> bool:
        normalized_user_identifier = self.normalize_user_identifier(user_identifier)
        path_for_filter = self.logical_filename(filename).replace("'", "''")
        category_for_filter = self.category.replace("'", "''")
        filter_expression = f"sourcefile eq '{path_for_filter}' and category eq '{category_for_filter}'"

        async with self.search_info.create_search_client() as search_client:
            result = await search_client.search(search_text="", filter=filter_expression, top=1000)
            async for document in result:
                document_user = str(document.get("user") or "").strip().lower() or None
                if normalized_user_identifier and document_user and document_user != normalized_user_identifier:
                    continue
                if not self.is_own_storage_url(
                    document.get("storageUrl"),
                    filename,
                    user_identifier=normalized_user_identifier,
                ):
                    return True
        return False

    @staticmethod
    def count_pdf_pages(file_content, filename: str) -> int:
        try:
            file_content.seek(0)
            reader = PdfReader(file_content)
            page_count = len(reader.pages)
            file_content.seek(0)
            return page_count
        except Exception as error:
            try:
                file_content.seek(0)
            except Exception:
                pass
            raise ValueError(f"Unable to read PDF page count from {filename}") from error

    async def get_uploaded_pdf_page_count(self, filename: str, user_identifier: Optional[str] = None) -> int:
        normalized_user_identifier = self.normalize_user_identifier(user_identifier)
        manifest = await self.get_manifest(filename, user_identifier=normalized_user_identifier)
        file_extension = manifest.file_extension if manifest is not None else os.path.splitext(filename)[1].lower()
        if file_extension != ".pdf":
            return 0

        if manifest is not None and manifest.page_count is not None:
            return manifest.page_count

        blob_name = (
            manifest.blob_name
            if manifest is not None
            else self.file_blob_name(filename, normalized_user_identifier)
        )
        blob = await self.blob_manager.download_blob(blob_name)
        if blob is None and manifest is None:
            blob = await self.blob_manager.download_blob(self.legacy_blob_name(filename, normalized_user_identifier))
        if blob is None:
            return 0

        content, _ = blob
        return self.count_pdf_pages(io.BytesIO(content), filename)

    async def get_total_uploaded_pdf_pages(
        self,
        excluding_filename: Optional[str] = None,
        user_identifier: Optional[str] = None,
    ) -> int:
        total_pages = 0
        normalized_excluding_filename = self.logical_filename(excluding_filename) if excluding_filename else None

        for existing_filename in await self.list_files(user_identifier=user_identifier):
            normalized_filename = self.logical_filename(existing_filename)
            if normalized_excluding_filename is not None and normalized_filename == normalized_excluding_filename:
                continue
            total_pages += await self.get_uploaded_pdf_page_count(normalized_filename, user_identifier=user_identifier)

        return total_pages

    async def validate_upload_constraints(
        self,
        file: File,
        filename: str,
        user_identifier: Optional[str] = None,
    ) -> Optional[int]:
        if self.rules.max_total_pdf_pages is None or os.path.splitext(filename)[1].lower() != ".pdf":
            return None

        pdf_page_count = self.count_pdf_pages(file.content, filename)
        existing_pdf_pages = await self.get_total_uploaded_pdf_pages(
            excluding_filename=filename,
            user_identifier=user_identifier,
        )
        total_pdf_pages = existing_pdf_pages + pdf_page_count

        if total_pdf_pages > self.rules.max_total_pdf_pages:
            raise ValueError(
                f"{self.chatbot_name} allows up to {self.rules.max_total_pdf_pages} uploaded PDF pages in total. "
                f"Existing uploads use {existing_pdf_pages} pages and {filename} adds {pdf_page_count} pages."
            )

        return pdf_page_count

    async def add_file(
        self,
        file: File,
        upload_id: Optional[str] = None,
        user_identifier: Optional[str] = None,
    ) -> str:
        normalized_user_identifier = self.normalize_user_identifier(user_identifier)
        filename = self.logical_filename(file.filename())
        file_extension = os.path.splitext(filename)[1].lower()
        if not self.is_supported(filename):
            raise ValueError(f"Unsupported file type: {filename}")
        if await self.has_conflicting_non_upload_document(filename, user_identifier=normalized_user_identifier):
            raise ValueError(
                f"Filename '{filename}' conflicts with existing {self.chatbot_name} content. Rename the file and upload it again."
            )
        pdf_page_count = await self.validate_upload_constraints(
            file,
            filename,
            user_identifier=normalized_user_identifier,
        )

        upload_id = upload_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        new_blob_name: Optional[str] = None
        new_storage_url: Optional[str] = None

        async def check_cancel() -> None:
            if await self.is_cancel_requested(upload_id, user_identifier=normalized_user_identifier):
                raise ChatbotUploadCancelled(filename)

        try:
            await check_cancel()
            sections = await parse_file(
                file,
                self.file_processors,
                self.category,
                check_cancel=check_cancel,
            )
            if not sections:
                raise ValueError(f"Unable to extract searchable content from {filename}")

            await check_cancel()
            await self.remove_stale_upload_documents(
                filename,
                keep_storage_url=None,
                user_identifier=normalized_user_identifier,
            )
            new_blob_name = self.file_blob_name(filename, user_identifier=normalized_user_identifier)
            new_storage_url = await self.blob_manager.upload_blob_data(
                file.content,
                new_blob_name,
                content_type=getattr(file.content, "content_type", None),
            )

            await check_cancel()
            await self.search_manager.update_content(
                sections,
                url=new_storage_url,
                document_id_suffix=f"-upload-{self.upload_token(upload_id)}",
                check_cancel=check_cancel,
                extra_fields={"user": normalized_user_identifier} if normalized_user_identifier else None,
            )

            await check_cancel()
            await self.save_manifest(
                ChatbotUploadManifest(
                    filename=filename,
                    blob_name=new_blob_name,
                    upload_id=upload_id,
                    uploaded_at=datetime.now(timezone.utc).isoformat(),
                    page_count=pdf_page_count,
                    file_extension=file_extension,
                    user_identifier=normalized_user_identifier,
                )
            )
            await self.blob_manager.remove_blob_name(
                self.legacy_manifest_blob_name(filename, normalized_user_identifier)
            )
            await self.remove_stale_blobs(
                filename,
                keep_blob_name=new_blob_name,
                user_identifier=normalized_user_identifier,
            )
            return new_storage_url
        except ChatbotUploadCancelled:
            await self.cleanup_canceled_upload(
                filename,
                new_blob_name,
                new_storage_url,
                user_identifier=normalized_user_identifier,
            )
            raise
        except Exception:
            await self.cleanup_canceled_upload(
                filename,
                new_blob_name,
                new_storage_url,
                user_identifier=normalized_user_identifier,
            )
            raise

    async def remove_file(self, filename: str, user_identifier: Optional[str] = None) -> None:
        normalized_user_identifier = self.normalize_user_identifier(user_identifier)
        if filename is None or filename == "":
            logging.warning("Filename is required to remove a file")
            return

        filename = self.logical_filename(filename)
        await self.remove_stale_upload_documents(
            filename,
            keep_storage_url=None,
            user_identifier=normalized_user_identifier,
        )
        await self.remove_stale_blobs(filename, keep_blob_name=None, user_identifier=normalized_user_identifier)
        await self.remove_manifest(filename, user_identifier=normalized_user_identifier)

    async def remove_all_files(self, user_identifier: Optional[str] = None) -> tuple[list[str], list[dict[str, str]]]:
        deleted: list[str] = []
        failed: list[dict[str, str]] = []
        normalized_user_identifier = self.normalize_user_identifier(user_identifier)

        for filename in await self.list_files(user_identifier=normalized_user_identifier):
            try:
                await self.remove_file(filename, user_identifier=normalized_user_identifier)
                deleted.append(filename)
            except Exception as error:
                logger.error("Failed to remove chatbot upload '%s': %s", filename, error)
                failed.append({"filename": filename, "message": "Unexpected delete failure"})

        return deleted, failed

    async def list_files(self, user_identifier: Optional[str] = None) -> list[str]:
        normalized_user_identifier = self.normalize_user_identifier(user_identifier)
        filenames = set()

        manifest_prefix = f"{self.manifest_prefix(normalized_user_identifier)}/"
        manifest_blob_names = await self.blob_manager.list_blob_names(manifest_prefix)
        for blob_name in manifest_blob_names:
            if not blob_name.startswith(manifest_prefix) or not blob_name.endswith(".json"):
                continue
            encoded_name = blob_name[len(manifest_prefix) : -5]
            try:
                filenames.add(self.decode_token(encoded_name))
            except Exception:
                logger.warning("Skipping unreadable manifest blob %s", blob_name)

        legacy_manifest_prefix = f"{self.legacy_manifest_prefix(normalized_user_identifier)}/"
        legacy_manifest_blob_names = await self.blob_manager.list_blob_names(legacy_manifest_prefix)
        for blob_name in legacy_manifest_blob_names:
            if not blob_name.startswith(legacy_manifest_prefix) or not blob_name.endswith(".json"):
                continue
            encoded_name = blob_name[len(legacy_manifest_prefix) : -5]
            try:
                filenames.add(self.decode_token(encoded_name))
            except Exception:
                logger.warning("Skipping unreadable manifest blob %s", blob_name)

        storage_prefix = f"{self.storage_prefix(normalized_user_identifier)}/"
        current_blob_names = await self.blob_manager.list_blob_names(storage_prefix)
        for blob_name in current_blob_names:
            if not blob_name.startswith(storage_prefix):
                continue
            relative_name = blob_name[len(storage_prefix) :]
            if not relative_name or "/" in relative_name or relative_name.startswith("."):
                continue
            filenames.add(os.path.basename(relative_name))

        legacy_storage_prefix = f"{self.legacy_storage_prefix(normalized_user_identifier)}/"
        legacy_blob_names = await self.blob_manager.list_blob_names(legacy_storage_prefix)
        for blob_name in legacy_blob_names:
            if not blob_name.startswith(legacy_storage_prefix):
                continue
            relative_name = blob_name[len(legacy_storage_prefix) :]
            if not relative_name or "/" in relative_name or relative_name.startswith("."):
                continue
            filenames.add(os.path.basename(relative_name))

        return sorted(filenames)

    async def download_file(self, filename: str, user_identifier: Optional[str] = None):
        normalized_user_identifier = self.normalize_user_identifier(user_identifier)
        filename = self.logical_filename(filename)
        manifest = await self.get_manifest(filename, user_identifier=normalized_user_identifier)
        if manifest is not None:
            blob = await self.blob_manager.download_blob(manifest.blob_name)
            if blob is not None:
                return blob
        blob = await self.blob_manager.download_blob(self.file_blob_name(filename, normalized_user_identifier))
        if blob is not None:
            return blob
        return await self.blob_manager.download_blob(self.legacy_blob_name(filename, normalized_user_identifier))
