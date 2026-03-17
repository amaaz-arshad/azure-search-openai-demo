import base64
import io
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

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
        if self.document_action == DocumentAction.Add:
            files = self.list_file_strategy.list()
            async for file in files:
                try:
                    blob_url = await self.blob_manager.upload_blob(file)
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
                await self.blob_manager.remove_blob(path)
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
    ):
        self.chatbot_name = chatbot_name
        self.file_processors = file_processors
        self.embeddings = embeddings
        self.search_info = search_info
        self.blob_manager = blob_manager
        self.storage_prefix = f"chatbot-uploads/{self.chatbot_name}"
        self.files_prefix = f"{self.storage_prefix}/files"
        self.manifest_prefix = f"{self.storage_prefix}/.manifests"
        self.cancel_prefix = f"{self.storage_prefix}/.cancel"
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

    def legacy_blob_name(self, filename: str) -> str:
        return f"{self.storage_prefix}/{self.logical_filename(filename)}"

    def version_blob_prefix(self, filename: str) -> str:
        return f"{self.files_prefix}/{self.filename_token(filename)}/"

    def version_blob_name(self, filename: str, upload_id: str) -> str:
        return f"{self.version_blob_prefix(filename)}{self.upload_token(upload_id)}/{self.logical_filename(filename)}"

    def manifest_blob_name(self, filename: str) -> str:
        return f"{self.manifest_prefix}/{self.filename_token(filename)}.json"

    def cancel_blob_name(self, upload_id: str) -> str:
        return f"{self.cancel_prefix}/{self.upload_token(upload_id)}.cancel"

    def is_supported(self, filename: str) -> bool:
        return os.path.splitext(filename)[1].lower() in self.file_processors

    def is_own_storage_url(self, storage_url: Optional[str], filename: str) -> bool:
        if not storage_url:
            return False
        return storage_url.endswith(self.legacy_blob_name(filename)) or self.version_blob_prefix(filename) in storage_url

    async def get_manifest(self, filename: str) -> Optional[ChatbotUploadManifest]:
        manifest_blob = await self.blob_manager.download_blob(self.manifest_blob_name(filename))
        if manifest_blob is None:
            return None

        try:
            payload, _ = manifest_blob
            manifest_data = json.loads(payload.decode("utf-8"))
            return ChatbotUploadManifest(
                filename=self.logical_filename(manifest_data["filename"]),
                blob_name=manifest_data["blob_name"],
                upload_id=manifest_data["upload_id"],
                uploaded_at=manifest_data["uploaded_at"],
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("Invalid upload manifest for %s", filename)
            return None

    async def save_manifest(self, manifest: ChatbotUploadManifest) -> None:
        manifest_buffer = io.BytesIO(json.dumps(asdict(manifest)).encode("utf-8"))
        await self.blob_manager.upload_blob_data(
            manifest_buffer,
            self.manifest_blob_name(manifest.filename),
            content_type="application/json",
        )

    async def remove_manifest(self, filename: str) -> None:
        await self.blob_manager.remove_blob_name(self.manifest_blob_name(filename))

    async def request_cancel(self, upload_id: str) -> None:
        cancel_buffer = io.BytesIO(b"cancel")
        await self.blob_manager.upload_blob_data(
            cancel_buffer,
            self.cancel_blob_name(upload_id),
            content_type="text/plain",
        )

    async def is_cancel_requested(self, upload_id: str) -> bool:
        return await self.blob_manager.blob_exists(self.cancel_blob_name(upload_id))

    async def clear_cancel_request(self, upload_id: str) -> None:
        await self.blob_manager.remove_blob_name(self.cancel_blob_name(upload_id))

    async def list_upload_documents(self, filename: str) -> list[dict]:
        documents = await self.search_manager.list_documents(path=filename, category=self.category)
        return [document for document in documents if self.is_own_storage_url(document.get("storageUrl"), filename)]

    async def delete_documents_for_storage_url(self, filename: str, storage_url: Optional[str]) -> None:
        if not storage_url:
            return
        documents = await self.list_upload_documents(filename)
        document_ids = [document["id"] for document in documents if document.get("storageUrl") == storage_url]
        await self.search_manager.delete_documents_by_ids(document_ids)

    async def remove_stale_upload_documents(self, filename: str, keep_storage_url: Optional[str]) -> None:
        documents = await self.list_upload_documents(filename)
        document_ids = [
            document["id"]
            for document in documents
            if keep_storage_url is None or document.get("storageUrl") != keep_storage_url
        ]
        await self.search_manager.delete_documents_by_ids(document_ids)

    async def list_managed_blob_names(self, filename: str) -> list[str]:
        blob_names = []
        legacy_blob_name = self.legacy_blob_name(filename)
        if await self.blob_manager.blob_exists(legacy_blob_name):
            blob_names.append(legacy_blob_name)
        blob_names.extend(await self.blob_manager.list_blob_names(self.version_blob_prefix(filename)))
        return blob_names

    async def remove_stale_blobs(self, filename: str, keep_blob_name: Optional[str]) -> None:
        blob_names = await self.list_managed_blob_names(filename)
        for blob_name in blob_names:
            if keep_blob_name is not None and blob_name == keep_blob_name:
                continue
            await self.blob_manager.remove_blob_name(blob_name)

    async def cleanup_canceled_upload(
        self,
        filename: str,
        new_blob_name: Optional[str],
        new_storage_url: Optional[str],
    ) -> None:
        await self.delete_documents_for_storage_url(filename, new_storage_url)
        if new_blob_name is not None:
            await self.blob_manager.remove_blob_name(new_blob_name)

    async def has_conflicting_non_upload_document(self, filename: str) -> bool:
        path_for_filter = self.logical_filename(filename).replace("'", "''")
        category_for_filter = self.category.replace("'", "''")
        filter_expression = f"sourcefile eq '{path_for_filter}' and category eq '{category_for_filter}'"

        async with self.search_info.create_search_client() as search_client:
            result = await search_client.search(search_text="", filter=filter_expression, top=1000)
            async for document in result:
                if not self.is_own_storage_url(document.get("storageUrl"), filename):
                    return True
        return False

    async def add_file(self, file: File, upload_id: Optional[str] = None) -> str:
        filename = self.logical_filename(file.filename())
        if not self.is_supported(filename):
            raise ValueError(f"Unsupported file type: {filename}")
        if await self.has_conflicting_non_upload_document(filename):
            raise ValueError(
                f"Filename '{filename}' conflicts with existing {self.chatbot_name} content. Rename the file and upload it again."
            )

        upload_id = upload_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        new_blob_name: Optional[str] = None
        new_storage_url: Optional[str] = None

        async def check_cancel() -> None:
            if await self.is_cancel_requested(upload_id):
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
            new_blob_name = self.version_blob_name(filename, upload_id)
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
            )

            await check_cancel()
            await self.remove_stale_upload_documents(filename, keep_storage_url=new_storage_url)
            await self.save_manifest(
                ChatbotUploadManifest(
                    filename=filename,
                    blob_name=new_blob_name,
                    upload_id=upload_id,
                    uploaded_at=datetime.now(timezone.utc).isoformat(),
                )
            )
            await self.remove_stale_blobs(filename, keep_blob_name=new_blob_name)
            return new_storage_url
        except ChatbotUploadCancelled:
            await self.cleanup_canceled_upload(filename, new_blob_name, new_storage_url)
            raise
        except Exception:
            await self.cleanup_canceled_upload(filename, new_blob_name, new_storage_url)
            raise

    async def remove_file(self, filename: str) -> None:
        if filename is None or filename == "":
            logging.warning("Filename is required to remove a file")
            return

        filename = self.logical_filename(filename)
        await self.remove_stale_upload_documents(filename, keep_storage_url=None)
        await self.remove_stale_blobs(filename, keep_blob_name=None)
        await self.remove_manifest(filename)

    async def list_files(self) -> list[str]:
        filenames = set()

        manifest_blob_names = await self.blob_manager.list_blob_names(f"{self.manifest_prefix}/")
        manifest_prefix = f"{self.manifest_prefix}/"
        for blob_name in manifest_blob_names:
            if not blob_name.startswith(manifest_prefix) or not blob_name.endswith(".json"):
                continue
            encoded_name = blob_name[len(manifest_prefix) : -5]
            try:
                filenames.add(self.decode_token(encoded_name))
            except Exception:
                logger.warning("Skipping unreadable manifest blob %s", blob_name)

        legacy_blob_names = await self.blob_manager.list_blob_names(f"{self.storage_prefix}/")
        storage_prefix = f"{self.storage_prefix}/"
        for blob_name in legacy_blob_names:
            if not blob_name.startswith(storage_prefix):
                continue
            relative_name = blob_name[len(storage_prefix) :]
            if not relative_name or "/" in relative_name or relative_name.startswith("."):
                continue
            filenames.add(os.path.basename(relative_name))

        return sorted(filenames)

    async def download_file(self, filename: str):
        filename = self.logical_filename(filename)
        manifest = await self.get_manifest(filename)
        if manifest is not None:
            blob = await self.blob_manager.download_blob(manifest.blob_name)
            if blob is not None:
                return blob
        return await self.blob_manager.download_blob(self.legacy_blob_name(filename))
