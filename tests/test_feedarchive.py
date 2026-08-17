import io
import zipfile

import pytest

from prepdocslib.feedarchive import (
    FeedArchiveOptions,
    FeedImageAsset,
    build_image_bundle,
    content_public_path,
    describe_archive_images,
    document_blob_name,
    expand_feed_archive,
    image_blob_name,
    image_cache_key,
    normalize_asset_key,
    package_name_for_archive,
)

# A minimal PublishOne package shaped like the real exports: the <img> references its asset by
# po-ref-id and the archive entry is "<asset id>.jpg".
FEED_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<folder id="8796"><naam>Speiseplan</naam><meta />
  <document id="8799"><naam>Der Speiseplan</naam><meta />
    <document version="1">
      <p><img id="Grafik 1" href="https://snap-em.publishone.nl/api/content/8798" po-ref-id="8798">
        <asset id="8798"><title>Speiseplan-image1</title>
          <manifest id="1693" media-type="image/jpeg" />
        </asset>
      </img></p>
    </document>
  </document>
</folder>
"""


def build_archive(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


class RecordingDescriber:
    def __init__(self, description: str = "described", fail_for: set[bytes] | None = None) -> None:
        self.description = description
        self.fail_for = fail_for or set()
        self.calls: list[bytes] = []

    async def describe_image(self, image_bytes: bytes) -> str:
        self.calls.append(image_bytes)
        if image_bytes in self.fail_for:
            raise RuntimeError("vision call failed")
        return f"{self.description}:{image_bytes.decode()}"


class MemoryCache:
    def __init__(self) -> None:
        self.entries: dict[str, str] = {}
        self.writes = 0

    async def get(self, cache_key: str):
        return self.entries.get(cache_key)

    async def set(self, cache_key: str, description: str) -> None:
        self.writes += 1
        self.entries[cache_key] = description


def test_expand_feed_archive_splits_documents_and_images() -> None:
    archive = expand_feed_archive(build_archive({"Speiseplan.xml": FEED_XML, "8798.jpg": b"jpeg-bytes"}))

    assert [document.name for document in archive.documents] == ["Speiseplan.xml"]
    assert set(archive.images) == {"8798"}
    assert archive.images["8798"].filename == "8798.jpg"
    assert archive.images["8798"].data == b"jpeg-bytes"


def test_expand_feed_archive_flattens_folders_and_skips_noise() -> None:
    archive = expand_feed_archive(
        build_archive(
            {
                "package/Speiseplan.xml": FEED_XML,
                "package/images/8798.jpg": b"jpeg-bytes",
                "__MACOSX/._Speiseplan.xml": b"junk",
                ".DS_Store": b"junk",
                "notes.docx": b"unsupported",
            }
        )
    )

    assert [document.name for document in archive.documents] == ["Speiseplan.xml"]
    assert set(archive.images) == {"8798"}


def test_expand_feed_archive_handles_a_package_without_images() -> None:
    archive = expand_feed_archive(build_archive({"Speiseplan.xml": FEED_XML}))

    assert len(archive.documents) == 1
    assert archive.images == {}


def test_expand_feed_archive_keeps_an_image_with_no_matching_document_reference() -> None:
    # An unreferenced image is mirrored and described but simply never rendered.
    archive = expand_feed_archive(build_archive({"Speiseplan.xml": FEED_XML, "9999.png": b"png-bytes"}))

    assert set(archive.images) == {"9999"}


def test_expand_feed_archive_rejects_a_non_archive() -> None:
    with pytest.raises(zipfile.BadZipFile):
        expand_feed_archive(b"not a zip file")


@pytest.mark.parametrize(
    "value,expected",
    [
        ("8798", "8798"),
        ("8798.jpg", "8798"),
        ("8798.JPEG", "8798"),
        ("https://snap-em.publishone.nl/api/content/8798", "8798"),
        ("https://snap-em.publishone.nl/api/content/8798/", "8798"),
        ("https://example.test/api/content/8798?size=large", "8798"),
        ("  8798  ", "8798"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_asset_key(value, expected) -> None:
    assert normalize_asset_key(value) == expected


def test_normalize_asset_key_keeps_non_image_extensions_intact() -> None:
    # Only known image extensions are stripped, so a document id containing a dot survives.
    assert normalize_asset_key("8798.2") == "8798.2"


def test_blob_names_and_public_paths_are_namespaced_by_package() -> None:
    assert image_blob_name("publishone2", "nerilio2", "8798.jpg") == "publishone2/nerilio2/images/8798.jpg"
    assert document_blob_name("publishone2", "nerilio2", "Speiseplan.xml") == "publishone2/nerilio2/Speiseplan.xml"
    assert package_name_for_archive("nerilio/Nerilio-Amsterdam-ZIP-zip/nerilio2.zip") == "nerilio2"


def test_content_public_path_percent_encodes_so_markdown_survives() -> None:
    # A space in a Markdown image path terminates the URL, so it has to be encoded.
    assert content_public_path("publishone2/pkg/images/Tiroler Stadt.jpg") == (
        "/content/publishone2/pkg/images/Tiroler%20Stadt.jpg"
    )


def test_build_image_bundle_resolves_by_every_reference_shape() -> None:
    bundle = build_image_bundle(
        [FeedImageAsset(key="8798", filename="8798.jpg", data=b"x")],
        {"8798": "a table"},
        target_prefix="publishone2",
        package_name="nerilio2",
    )

    resolved = bundle.lookup(["8798"])
    assert resolved is not None
    assert resolved.public_path == "/content/publishone2/nerilio2/images/8798.jpg"
    assert resolved.description == "a table"
    assert bundle.lookup(["https://snap-em.publishone.nl/api/content/8798"]) is resolved
    assert bundle.lookup(["8798.jpg"]) is resolved
    assert bundle.lookup(["Grafik 1", "8798"]) is resolved
    assert bundle.lookup(["Grafik 1"]) is None


def test_build_image_bundle_leaves_an_undescribed_image_displayable() -> None:
    bundle = build_image_bundle(
        [FeedImageAsset(key="8798", filename="8798.jpg", data=b"x")],
        {},
        target_prefix="publishone2",
        package_name="nerilio2",
    )

    resolved = bundle.lookup(["8798"])
    assert resolved is not None
    assert resolved.description == ""
    assert resolved.public_path.endswith("8798.jpg")


@pytest.mark.asyncio
async def test_describe_archive_images_without_a_describer_returns_nothing() -> None:
    assets = [FeedImageAsset(key="1", filename="1.jpg", data=b"one")]

    assert await describe_archive_images(assets, describer=None) == {}


@pytest.mark.asyncio
async def test_describe_archive_images_describes_each_asset() -> None:
    describer = RecordingDescriber()
    assets = [
        FeedImageAsset(key="1", filename="1.jpg", data=b"one"),
        FeedImageAsset(key="2", filename="2.jpg", data=b"two"),
    ]

    descriptions = await describe_archive_images(assets, describer=describer)

    assert descriptions == {"1": "described:one", "2": "described:two"}
    assert len(describer.calls) == 2


@pytest.mark.asyncio
async def test_describe_archive_images_survives_a_failed_image() -> None:
    describer = RecordingDescriber(fail_for={b"one"})
    assets = [
        FeedImageAsset(key="1", filename="1.jpg", data=b"one"),
        FeedImageAsset(key="2", filename="2.jpg", data=b"two"),
    ]

    descriptions = await describe_archive_images(assets, describer=describer)

    # The failed image is simply undescribed; it is still mirrored and displayable.
    assert descriptions == {"2": "described:two"}


@pytest.mark.asyncio
async def test_describe_archive_images_caps_the_number_of_images() -> None:
    describer = RecordingDescriber()
    assets = [FeedImageAsset(key=str(i), filename=f"{i}.jpg", data=str(i).encode()) for i in range(5)]

    descriptions = await describe_archive_images(assets, describer=describer, max_images=2)

    assert len(descriptions) == 2
    assert len(describer.calls) == 2


@pytest.mark.asyncio
async def test_describe_archive_images_serves_and_fills_the_cache() -> None:
    describer = RecordingDescriber()
    cache = MemoryCache()
    asset = FeedImageAsset(key="1", filename="1.jpg", data=b"one")

    first = await describe_archive_images([asset], describer=describer, cache=cache)
    second = await describe_archive_images([asset], describer=describer, cache=cache)

    assert first == second == {"1": "described:one"}
    # The second run is served entirely from the cache: re-uploading a package costs no vision calls.
    assert len(describer.calls) == 1
    assert cache.writes == 1
    assert image_cache_key(b"one") in cache.entries


@pytest.mark.asyncio
async def test_describe_archive_images_ignores_a_broken_cache() -> None:
    class BrokenCache:
        async def get(self, cache_key: str):
            raise RuntimeError("cache down")

        async def set(self, cache_key: str, description: str) -> None:
            raise RuntimeError("cache down")

    describer = RecordingDescriber()
    asset = FeedImageAsset(key="1", filename="1.jpg", data=b"one")

    descriptions = await describe_archive_images([asset], describer=describer, cache=BrokenCache())

    assert descriptions == {"1": "described:one"}


def test_image_cache_key_changes_with_content() -> None:
    assert image_cache_key(b"one") != image_cache_key(b"two")
    assert image_cache_key(b"one") == image_cache_key(b"one")


def test_feed_archive_options_default_to_no_describer() -> None:
    options = FeedArchiveOptions()

    assert options.describer is None
    assert options.content_root == "content"
