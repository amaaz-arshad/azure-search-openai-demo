"""ZIP-packaged feed support for PublishOne exports.

A PublishOne ZIP export contains one or more feed XML documents plus the image files those
documents reference (`<img po-ref-id="8793">` -> `8793.jpg`). Plain XML exports reference the same
images by an external PublishOne URL we cannot fetch, so their content is unknowable; inside a ZIP
the bytes travel with the document, which is what lets us describe them at ingestion time.

This module owns the pure, side-effect-free half of that: opening the archive, pairing images with
documents, and turning image bytes into text via a MediaDescriber (with a cache so a re-uploaded
archive costs nothing). Blob mirroring and search indexing stay in blobautoindex.py.
"""

import asyncio
import hashlib
import io
import json
import logging
import os
import posixpath
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import IO, Optional, Protocol
from urllib.parse import quote

from .mediadescriber import FEED_IMAGE_DESCRIPTION_PROMPT, MediaDescriber

logger = logging.getLogger("scripts")

# Extensions treated as feed documents inside an archive.
ARCHIVE_DOCUMENT_EXTENSIONS = (".xml",)
# Extensions treated as image assets inside an archive.
ARCHIVE_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
# Archive entries we never look at (macOS resource forks); hidden files are dropped by basename.
ARCHIVE_IGNORED_PREFIXES = ("__MACOSX/",)

# Bumped whenever the describer prompt changes so cached descriptions are regenerated rather than
# silently serving text produced by an older instruction.
IMAGE_DESCRIPTION_PROMPT_VERSION = "v1"

DEFAULT_DESCRIBE_CONCURRENCY = 4
# The auto-indexer Function has a 10 minute timeout; a very large archive must not consume it all.
DEFAULT_MAX_IMAGES_PER_ARCHIVE = 40


@dataclass(frozen=True)
class FeedArchiveDocument:
    """One feed XML document found inside an archive."""

    name: str
    data: bytes


@dataclass(frozen=True)
class FeedImageAsset:
    """One image file found inside an archive.

    `key` is the filename stem, which is the PublishOne asset id (`8793.jpg` -> `8793`) and is what
    the `<img>` element references.
    """

    key: str
    filename: str
    data: bytes


@dataclass(frozen=True)
class FeedArchive:
    documents: list[FeedArchiveDocument]
    images: dict[str, FeedImageAsset]


@dataclass(frozen=True)
class ResolvedFeedImage:
    """An archive image as the feed parser should render it."""

    key: str
    filename: str
    # Same-origin path served by the backend /content route, e.g. /content/publishone2/pkg/images/8793.jpg
    public_path: str
    description: str = ""


@dataclass
class FeedImageBundle:
    """Images available to one feed document, looked up by any of an <img>'s reference ids."""

    images: dict[str, ResolvedFeedImage] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.images)

    def lookup(self, keys: Sequence[Optional[str]]) -> Optional[ResolvedFeedImage]:
        for key in keys:
            normalized_key = normalize_asset_key(key)
            if normalized_key and normalized_key in self.images:
                return self.images[normalized_key]
        return None


class ImageDescriptionCache(Protocol):
    async def get(self, cache_key: str) -> Optional[str]: ...

    async def set(self, cache_key: str, description: str) -> None: ...


@dataclass(frozen=True)
class FeedArchiveOptions:
    """How an indexer should handle archive packages.

    With no describer the archive still works end to end — images are mirrored and displayed, they
    just carry no transcription — so a deployment without a vision model degrades rather than fails.
    """

    describer: Optional[MediaDescriber] = None
    description_cache: Optional[ImageDescriptionCache] = None
    describe_concurrency: int = DEFAULT_DESCRIBE_CONCURRENCY
    max_images: int = DEFAULT_MAX_IMAGES_PER_ARCHIVE
    content_root: str = "content"


# ZIP local-file-header / end-of-central-directory / spanned magic bytes.
ZIP_MAGIC_PREFIXES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


def looks_like_zip(content: bytes) -> bool:
    """Whether a payload is a ZIP archive, regardless of what it is named.

    Real PublishOne exports arrive as archives carrying a `.xml` extension (the export names the
    file after the document id and the container type is lost), so extension alone cannot decide
    how to read a package.
    """
    return content[:4] in ZIP_MAGIC_PREFIXES


def normalize_asset_key(value: Optional[str]) -> str:
    """Reduce an <img> reference to the asset key used by archive entries.

    Accepts a bare id (`8793`), a filename (`8793.jpg`), or a URL whose last segment is the id
    (`https://snap-em.publishone.nl/api/content/8793`).
    """
    if not value:
        return ""
    candidate = str(value).strip()
    if not candidate:
        return ""
    if "?" in candidate:
        candidate = candidate.split("?", 1)[0]
    if "#" in candidate:
        candidate = candidate.split("#", 1)[0]
    candidate = candidate.rstrip("/")
    if "/" in candidate:
        candidate = candidate.rsplit("/", 1)[1]
    stem, extension = os.path.splitext(candidate)
    if extension.lower() in ARCHIVE_IMAGE_EXTENSIONS:
        candidate = stem
    return candidate.strip()


def archive_entry_name(entry_name: str) -> str:
    """Flatten an archive entry to its basename (archives may nest documents in folders)."""
    return posixpath.basename(entry_name.replace("\\", "/"))


def is_ignored_archive_entry(entry_name: str) -> bool:
    normalized = entry_name.replace("\\", "/")
    if normalized.endswith("/"):
        return True
    basename = posixpath.basename(normalized)
    if not basename:
        return True
    return normalized.startswith(ARCHIVE_IGNORED_PREFIXES) or basename.startswith(".")


def expand_feed_archive(
    content: bytes | IO[bytes],
    *,
    document_extensions: Sequence[str] = ARCHIVE_DOCUMENT_EXTENSIONS,
    image_extensions: Sequence[str] = ARCHIVE_IMAGE_EXTENSIONS,
) -> FeedArchive:
    """Read a feed ZIP into its documents and image assets.

    Raises zipfile.BadZipFile when the payload is not a readable archive; callers decide whether
    that is fatal.
    """
    normalized_document_extensions = tuple(extension.lower() for extension in document_extensions)
    normalized_image_extensions = tuple(extension.lower() for extension in image_extensions)

    documents: list[FeedArchiveDocument] = []
    images: dict[str, FeedImageAsset] = {}

    stream: IO[bytes] = io.BytesIO(content) if isinstance(content, (bytes, bytearray)) else content
    with zipfile.ZipFile(stream) as archive:
        for info in archive.infolist():
            if info.is_dir() or is_ignored_archive_entry(info.filename):
                continue
            filename = archive_entry_name(info.filename)
            extension = os.path.splitext(filename)[1].lower()
            if extension in normalized_document_extensions:
                documents.append(FeedArchiveDocument(name=filename, data=archive.read(info)))
            elif extension in normalized_image_extensions:
                key = normalize_asset_key(filename)
                if not key:
                    continue
                if key in images:
                    logger.info("Duplicate image asset '%s' in archive; keeping the first entry", filename)
                    continue
                images[key] = FeedImageAsset(key=key, filename=filename, data=archive.read(info))
            else:
                logger.info("Ignoring unsupported archive entry '%s'", info.filename)

    return FeedArchive(documents=documents, images=images)


def image_cache_key(image_bytes: bytes) -> str:
    """Cache key for one described image: content hash plus the prompt version that produced it."""
    return f"{IMAGE_DESCRIPTION_PROMPT_VERSION}-{hashlib.sha256(image_bytes).hexdigest()}"


async def describe_archive_images(
    images: Iterable[FeedImageAsset],
    *,
    describer: Optional[MediaDescriber],
    cache: Optional[ImageDescriptionCache] = None,
    concurrency: int = DEFAULT_DESCRIBE_CONCURRENCY,
    max_images: int = DEFAULT_MAX_IMAGES_PER_ARCHIVE,
) -> dict[str, str]:
    """Describe every archive image once, returning asset key -> description text.

    A failure to describe one image is never fatal: the image still gets mirrored and displayed,
    it just carries no transcription. Without a describer this returns no descriptions at all,
    which is the normal state when no vision model is configured.
    """
    image_list = list(images)
    if not image_list:
        return {}
    if describer is None:
        logger.info("No image describer configured; %d archive image(s) will be shown undescribed", len(image_list))
        return {}

    if max_images > 0 and len(image_list) > max_images:
        logger.warning(
            "Archive has %d images, describing only the first %d (raise the per-archive cap to cover the rest)",
            len(image_list),
            max_images,
        )
        image_list = image_list[:max_images]

    semaphore = asyncio.Semaphore(max(1, concurrency))
    descriptions: dict[str, str] = {}

    async def describe_one(asset: FeedImageAsset) -> None:
        cache_key = image_cache_key(asset.data)
        if cache is not None:
            try:
                cached_description = await cache.get(cache_key)
            except Exception:
                logger.exception("Failed reading the image description cache for '%s'", asset.filename)
                cached_description = None
            if cached_description:
                descriptions[asset.key] = cached_description
                return

        async with semaphore:
            try:
                description = (await describer.describe_image(asset.data)).strip()
            except Exception:
                logger.exception("Failed describing archive image '%s'", asset.filename)
                return

        if not description:
            return
        descriptions[asset.key] = description
        if cache is not None:
            try:
                await cache.set(cache_key, description)
            except Exception:
                logger.exception("Failed writing the image description cache for '%s'", asset.filename)

    await asyncio.gather(*(describe_one(asset) for asset in image_list))
    return descriptions


def content_public_path(blob_name: str, *, content_root: str = "content") -> str:
    """Same-origin URL for a mirrored blob, percent-encoded so it survives Markdown link syntax."""
    return f"/{content_root}/{quote(blob_name.strip('/'))}"


def image_blob_name(target_prefix: str, package_name: str, filename: str) -> str:
    """Mirror location for an archive image: <target_prefix>/<package>/images/<filename>."""
    parts = [part.strip("/") for part in (target_prefix, package_name, "images", filename) if part and part.strip("/")]
    return "/".join(parts)


def document_blob_name(target_prefix: str, package_name: str, filename: str) -> str:
    """Mirror location for an archive document: <target_prefix>/<package>/<filename>."""
    parts = [part.strip("/") for part in (target_prefix, package_name, filename) if part and part.strip("/")]
    return "/".join(parts)


def package_name_for_archive(blob_name: str) -> str:
    """The archive's filename stem, which namespaces every blob mirrored out of it."""
    return os.path.splitext(archive_entry_name(blob_name))[0].strip() or "archive"


def build_image_bundle(
    images: Iterable[FeedImageAsset],
    descriptions: dict[str, str],
    *,
    target_prefix: str,
    package_name: str,
    content_root: str = "content",
) -> FeedImageBundle:
    """Pair archive images with their mirrored public path and description."""
    resolved: dict[str, ResolvedFeedImage] = {}
    for asset in images:
        blob_name = image_blob_name(target_prefix, package_name, asset.filename)
        resolved[asset.key] = ResolvedFeedImage(
            key=asset.key,
            filename=asset.filename,
            public_path=content_public_path(blob_name, content_root=content_root),
            description=descriptions.get(asset.key, ""),
        )
    return FeedImageBundle(images=resolved)


class BlobImageDescriptionCache:
    """Blob-backed description cache.

    One small JSON blob per described image, keyed by content hash, so re-indexing an unchanged
    archive costs no vision calls. Misses and write failures are swallowed by the caller — the cache
    is an optimization, never a correctness requirement.
    """

    def __init__(self, blob_manager, prefix: str):
        self.blob_manager = blob_manager
        self.prefix = prefix.strip("/")

    def blob_name_for(self, cache_key: str) -> str:
        return f"{self.prefix}/{cache_key}.json"

    async def get(self, cache_key: str) -> Optional[str]:
        result = await self.blob_manager.download_blob(self.blob_name_for(cache_key))
        if not result:
            return None
        content, _ = result
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.info("Discarding unreadable cached image description '%s'", cache_key)
            return None
        description = payload.get("description")
        return description if isinstance(description, str) and description.strip() else None

    async def set(self, cache_key: str, description: str) -> None:
        payload = json.dumps({"description": description}, ensure_ascii=False).encode("utf-8")
        await self.blob_manager.upload_blob_data(
            io.BytesIO(payload),
            self.blob_name_for(cache_key),
            content_type="application/json",
        )
