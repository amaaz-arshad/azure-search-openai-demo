"""Tests for the content2 re-index driver.

The driver's whole value is that it produces the *same* documents the `content2_auto_index` Function
would, so the parity test below is the important one: if the two configurations diverge, a bot's
corpus starts depending on which of the two last touched each file.
"""

from dataclasses import fields
from types import SimpleNamespace

import pytest

import prep_content2_reindex
from moodle_auto_indexer import function_app
from prepdocslib.blobautoindex import AutoBlobIndexerConfig


class StubBlobManager:
    endpoint = "https://stub.blob.core.windows.net"
    container = "content"

    def __init__(self, blob_names: list[str] | None = None):
        self.blob_names = blob_names or []
        self.listed: list[tuple[str, str | None]] = []

    async def list_blob_names(self, prefix: str, container: str | None = None) -> list[str]:
        self.listed.append((prefix, container))
        return [name for name in self.blob_names if name.startswith(prefix)]


def build_search_info() -> SimpleNamespace:
    return SimpleNamespace(index_name="gptkbindex", endpoint="https://stub.search.windows.net")


def test_the_driver_and_the_function_configure_the_indexer_identically(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_STORAGE_CONTAINER2", raising=False)
    monkeypatch.delenv("CONTENT2_AUTO_INDEX_CONTAINER", raising=False)
    monkeypatch.delenv("CONTENT2_AUTO_INDEX_ALLOWED_EXTENSIONS", raising=False)
    monkeypatch.delenv("AZURE_SEARCH_ANALYZER_NAME", raising=False)

    from_function = function_app.build_content2_auto_indexer(
        blob_manager=StubBlobManager(),
        search_info=build_search_info(),
        embeddings=None,
        embedding_field_name="embedding3",
        file_processors={},
    ).config
    from_driver = prep_content2_reindex.build_indexer(
        blob_manager=StubBlobManager(),
        search_info=build_search_info(),
        embeddings=None,
        file_processors={},
        extensions=frozenset(prep_content2_reindex.CONTENT2_DEFAULT_EXTENSIONS),
    ).config

    for field in fields(AutoBlobIndexerConfig):
        assert getattr(from_driver, field.name) == getattr(from_function, field.name), field.name


def test_the_driver_enables_the_provisioned_bot_record_parsers() -> None:
    config = prep_content2_reindex.build_indexer(
        blob_manager=StubBlobManager(),
        search_info=build_search_info(),
        embeddings=None,
        file_processors={},
        extensions=frozenset({".json"}),
    ).config

    assert config.dynamic_record_parsing is True
    assert config.force_generic_parsing is True
    assert config.mirror_blob is False
    assert config.dynamic_category_from_path is True


def test_the_default_extensions_match_the_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    # The Function has no Document Intelligence wired in, so indexing an extension it will never
    # handle would create documents that silently stop being maintained.
    assert set(prep_content2_reindex.CONTENT2_DEFAULT_EXTENSIONS) == set(function_app.CONTENT2_DEFAULT_EXTENSIONS)


@pytest.mark.parametrize(
    ("blob_name", "expected"),
    [
        ("xba/www.snap.de.json", "xba"),
        ("tdiso/sub/dir/file.pdf", "tdiso"),
        # A blob at the container root belongs to no bot, so it has no category and is skipped.
        ("loose.json", None),
        ("/leading-slash/file.json", "leading-slash"),
        ("  ", None),
    ],
)
def test_the_bot_folder_is_the_first_path_segment(blob_name, expected) -> None:
    assert prep_content2_reindex.bot_folder_for(blob_name) == expected


@pytest.mark.asyncio
async def test_only_matching_extensions_inside_a_bot_folder_are_selected() -> None:
    blob_manager = StubBlobManager(
        [
            "xba/www.snap.de.json",
            "xba/brochure.pdf",
            "xba/notes.docx",
            "tdiso/dsgvo.json",
            "root-level.json",
        ]
    )

    selected = await prep_content2_reindex.list_target_blobs(blob_manager, extensions=frozenset({".json"}), bot=None)

    assert selected == ["tdiso/dsgvo.json", "xba/www.snap.de.json"]


@pytest.mark.asyncio
async def test_a_bot_filter_restricts_the_listing_prefix() -> None:
    blob_manager = StubBlobManager(["xba/a.json", "tdiso/b.json"])

    selected = await prep_content2_reindex.list_target_blobs(blob_manager, extensions=frozenset({".json"}), bot="xba")

    assert selected == ["xba/a.json"]
    # Listing is server-side by prefix, not a whole-container scan filtered afterwards.
    assert blob_manager.listed == [("xba/", "content2")]


def test_an_empty_result_status_is_treated_as_a_failure() -> None:
    # index_blob deletes a file's documents before writing the new ones, so "indexed zero sections"
    # means that file is now absent from the index - never a success.
    assert "no-content" in prep_content2_reindex.EMPTY_RESULT_STATUSES
    assert "copied-no-content" in prep_content2_reindex.EMPTY_RESULT_STATUSES
    assert "indexed" not in prep_content2_reindex.EMPTY_RESULT_STATUSES
