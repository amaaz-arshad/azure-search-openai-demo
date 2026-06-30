import io
import logging
import re

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import ContentSettings

from prepdocslib.blobmanager import BlobManager

logger = logging.getLogger(__name__)

CHATBOT_WIKIS_CONTAINER = "chatbot-wikis"
CHATBOT_WIKIS_PREFIX = "wiki"

# Wiki page slugs are kebab-case identifiers; keep the matcher strict so a model-supplied
# slug can never escape the category's pages/ folder (path traversal guard).
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def normalize_category(category: str | None) -> str | None:
    """A wiki is keyed by a single category. Accept the same value the backend puts in
    ``include_category`` (which may be a comma-joined list for internal) and reduce it to
    the primary, lowercased category folder name."""
    if not isinstance(category, str):
        return None
    primary = category.split(",", 1)[0].strip().lower()
    return primary or None


def normalize_slug(slug: str | None) -> str | None:
    if not isinstance(slug, str):
        return None
    candidate = slug.strip().lower().removesuffix(".md")
    return candidate if SLUG_RE.match(candidate) else None


class ChatbotWikiStore:
    """Blob-backed store for the LLM-Wiki retrieval mode.

    Mirrors ``ChatbotPromptStore`` but stores plain markdown (not JSON). Layout::

        chatbot-wikis/
          wiki/<category>/index.md            # master table of contents
          wiki/<category>/pages/<slug>.md     # YAML frontmatter + markdown body
          wiki/<category>/log.md              # optional build audit log

    The backend only reads (``load_*`` / ``has_wiki`` / ``list_page_slugs``); the authoring
    build script (``scripts/build_wiki.py``) writes via ``save_*``.
    """

    def __init__(
        self,
        *,
        blob_manager: BlobManager,
        container: str = CHATBOT_WIKIS_CONTAINER,
        wiki_prefix: str = CHATBOT_WIKIS_PREFIX,
    ):
        self.blob_manager = blob_manager
        self.container = container
        self.wiki_prefix = wiki_prefix.strip("/").strip()

    async def ensure_container_exists(self):
        container_client = self.blob_manager.blob_service_client.get_container_client(self.container)
        if not await container_client.exists():
            await container_client.create_container()
        return container_client

    def category_prefix(self, category: str) -> str:
        normalized = normalize_category(category)
        if normalized is None:
            raise ValueError("A valid wiki category is required.")
        return f"{self.wiki_prefix}/{normalized}"

    def index_blob_name(self, category: str) -> str:
        return f"{self.category_prefix(category)}/index.md"

    def page_blob_name(self, category: str, slug: str) -> str:
        normalized_slug = normalize_slug(slug)
        if normalized_slug is None:
            raise ValueError(f"Invalid wiki page slug: {slug!r}")
        return f"{self.category_prefix(category)}/pages/{normalized_slug}.md"

    def log_blob_name(self, category: str) -> str:
        return f"{self.category_prefix(category)}/log.md"

    async def load_text_blob(self, blob_name: str) -> str | None:
        result = await self.blob_manager.download_blob(blob_name, container=self.container)
        if result is None:
            return None
        content, _properties = result
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning("Invalid UTF-8 payload for wiki blob %s", blob_name)
            return None

    async def save_text_blob(self, blob_name: str, markdown: str) -> None:
        container_client = await self.ensure_container_exists()
        await container_client.upload_blob(
            blob_name,
            io.BytesIO(markdown.encode("utf-8")),
            overwrite=True,
            content_settings=ContentSettings(content_type="text/markdown; charset=utf-8"),
        )

    async def delete_blob_if_exists(self, blob_name: str) -> None:
        container_client = await self.ensure_container_exists()
        try:
            await container_client.delete_blob(blob_name, delete_snapshots="include")
        except ResourceNotFoundError:
            logger.debug("Wiki blob already removed from %s: %s", self.container, blob_name)

    # --- Read API (used at query time by run_wiki_approach) ----------------

    async def has_wiki(self, category: str) -> bool:
        """A wiki exists for a category iff its index.md is present."""
        if normalize_category(category) is None:
            return False
        return await self.load_text_blob(self.index_blob_name(category)) is not None

    async def load_index(self, category: str) -> str | None:
        if normalize_category(category) is None:
            return None
        return await self.load_text_blob(self.index_blob_name(category))

    async def load_page(self, category: str, slug: str) -> str | None:
        if normalize_category(category) is None or normalize_slug(slug) is None:
            return None
        return await self.load_text_blob(self.page_blob_name(category, slug))

    async def list_page_slugs(self, category: str) -> list[str]:
        normalized_category = normalize_category(category)
        if normalized_category is None:
            return []
        container_client = self.blob_manager.blob_service_client.get_container_client(self.container)
        if not await container_client.exists():
            return []
        prefix = f"{self.category_prefix(category)}/pages/"
        slugs: list[str] = []
        async for blob in container_client.list_blobs(name_starts_with=prefix):
            blob_name = getattr(blob, "name", None)
            if not blob_name or not blob_name.endswith(".md"):
                continue
            slug = normalize_slug(blob_name.rsplit("/", 1)[-1])
            if slug is not None:
                slugs.append(slug)
        return slugs

    # --- Write API (used by scripts/build_wiki.py) -------------------------

    async def save_index(self, category: str, markdown: str) -> None:
        await self.save_text_blob(self.index_blob_name(category), markdown)

    async def save_page(self, category: str, slug: str, markdown: str) -> None:
        await self.save_text_blob(self.page_blob_name(category, slug), markdown)

    async def save_log(self, category: str, markdown: str) -> None:
        await self.save_text_blob(self.log_blob_name(category), markdown)
