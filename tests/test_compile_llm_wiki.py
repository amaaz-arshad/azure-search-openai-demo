import io

import pytest

from compile_llm_wiki import (
    CompiledPage,
    DEFAULT_EXCLUDED_CHATBOTS,
    RawBlob,
    build_index_markdown,
    chunk_text,
    compile_chatbot_wiki,
    get_default_chatbots,
    get_compiled_page_relative_wiki_path,
    get_llm_wiki_blob_prefix,
    get_source_wiki_blob_name,
    get_source_wiki_part_blob_name,
    list_local_raw_blobs,
    should_compile_blob,
)
from prepdocslib.blobmanager import BlobListEntry


EXISTING_MANUAL_MARKDOWN = b"""# Existing Manual

## Summary
This is a previously compiled wiki page for the Nerilio user manual. It documents the
core workflows, role permissions, and integration touchpoints captured from the source
PDF and should be reused on subsequent compile runs unless the operator passes
`--overwrite`. Reusing avoids unnecessary LLM calls when nothing about the source has
changed.

## Key Facts
- The manual covers user account creation, authentication flows, and document upload
  procedures used by Nerilio operators.
- Section three explains the approval pipeline including the four-eyes rule applied
  before any document leaves the staging environment.
- Section seven walks through the reporting dashboard, the export formats supported,
  and the retention policy for archived runs.
- The audit trail format is described in appendix A and is the canonical reference for
  downstream tooling.

## Source Trace
- `nerilio/Manual.pdf`
- Page 1: cover page and revision history
- Pages 3-12: account and authentication flow
- Pages 13-22: approval pipeline and four-eyes rule
- Pages 23-30: reporting dashboard, export formats, retention policy
- Appendix A: audit trail schema reference

## Open Questions
- None for this revision; the document is final and signed off.
"""


class FakeBlobManager:
    def __init__(self) -> None:
        self.existing_blobs = {
            "__llm_wiki__/nerilio/wiki/sources/manual.md": EXISTING_MANUAL_MARKDOWN,
        }
        self.uploaded_blobs: dict[str, bytes] = {}
        self.raw_downloads: list[str] = []

    async def list_blobs(self, prefix: str | None = None) -> list[BlobListEntry]:
        return [BlobListEntry(name="nerilio/Manual.pdf")]

    async def blob_exists(self, blob_name: str) -> bool:
        return blob_name in self.existing_blobs

    async def download_blob(self, blob_name: str):
        if blob_name == "nerilio/Manual.pdf":
            self.raw_downloads.append(blob_name)
            return b"raw", {}
        if blob_name in self.existing_blobs:
            return self.existing_blobs[blob_name], {}
        return None

    async def upload_blob_data(self, file: io.BytesIO, blob_name: str, content_type: str | None = None) -> str:
        self.uploaded_blobs[blob_name] = file.read()
        return f"https://example.test/{blob_name}"


def test_get_default_chatbots_excludes_requested_bots() -> None:
    chatbots = get_default_chatbots(DEFAULT_EXCLUDED_CHATBOTS)

    assert "nerilio" in chatbots
    assert "moodle" in chatbots
    assert "publishone" in chatbots
    assert "steuertipps" not in chatbots
    assert "fbn" not in chatbots
    assert "free" not in chatbots
    assert "demo" not in chatbots
    assert "internal" not in chatbots


def test_should_compile_blob_ignores_nerilio_folders_by_default() -> None:
    assert should_compile_blob(
        "nerilio/root.pdf",
        "nerilio",
        nerilio_direct_only=True,
        recursive=True,
    )
    assert not should_compile_blob(
        "nerilio/Nerilio-Moodle/course.xml",
        "nerilio",
        nerilio_direct_only=True,
        recursive=True,
    )


def test_should_compile_blob_allows_nested_non_nerilio_sources() -> None:
    assert should_compile_blob(
        "moodle/Nerilio-Moodle/course.xml",
        "moodle",
        nerilio_direct_only=True,
        recursive=True,
    )


def test_should_compile_blob_skips_unsupported_extensions() -> None:
    assert not should_compile_blob(
        "lemon/image.png",
        "lemon",
        nerilio_direct_only=True,
        recursive=True,
    )


def test_should_compile_blob_skips_upload_manifests() -> None:
    assert not should_compile_blob(
        "knoll/.managed-uploads/manifests/source.json",
        "knoll",
        nerilio_direct_only=True,
        recursive=True,
    )
    assert not should_compile_blob(
        "rak/user/.manifests/source.json",
        "rak",
        nerilio_direct_only=True,
        recursive=True,
    )


def test_source_wiki_blob_name_is_scoped_to_chatbot() -> None:
    raw_blob = RawBlob(chatbot="nerilio", blob_name="nerilio/Manual.pdf", relative_path="Manual.pdf")

    assert get_llm_wiki_blob_prefix("nerilio") == "__llm_wiki__/nerilio/wiki"
    assert get_source_wiki_blob_name(raw_blob) == "__llm_wiki__/nerilio/wiki/sources/manual.md"


def test_source_wiki_part_blob_name_is_scoped_to_chatbot() -> None:
    raw_blob = RawBlob(chatbot="steuertipps", blob_name="steuertipps/product.xml", relative_path="product.xml")

    assert (
        get_source_wiki_part_blob_name(raw_blob, part_number=2)
        == "__llm_wiki__/steuertipps/wiki/sources/product-part-002.md"
    )


def test_build_index_markdown_links_compiled_source_pages() -> None:
    raw_blob = RawBlob(chatbot="nerilio", blob_name="nerilio/Manual.pdf", relative_path="Manual.pdf")

    index = build_index_markdown(
        "nerilio",
        [
            CompiledPage(
                source_blob=raw_blob,
                wiki_blob_name="__llm_wiki__/nerilio/wiki/sources/manual.md",
                markdown="# Manual\n\nSummary",
            )
        ],
    )

    assert "# nerilio LLM Wiki" in index
    assert "[Manual](sources/manual.md)" in index


def test_compiled_page_relative_path_uses_actual_part_blob_name() -> None:
    raw_blob = RawBlob(chatbot="steuertipps", blob_name="steuertipps/product.xml", relative_path="product.xml")
    compiled_page = CompiledPage(
        source_blob=raw_blob,
        wiki_blob_name="__llm_wiki__/steuertipps/wiki/sources/product-part-002.md",
        markdown="# Product Part 2",
    )

    assert get_compiled_page_relative_wiki_path("steuertipps", compiled_page) == "sources/product-part-002.md"


def test_chunk_text_splits_oversized_single_page_blocks() -> None:
    chunks = chunk_text("Source\n\n--- Page 1 [huge]\n" + ("A" * 75), 25)

    assert len(chunks) > 1
    assert all(len(chunk) <= 25 for chunk in chunks)


def test_list_local_raw_blobs_reads_files_from_content_root(tmp_path) -> None:
    source_root = tmp_path / "fbn"
    source_root.mkdir()
    (source_root / "Wetstoelichtingen IB - SNAP demo.xml").write_text("<document>content</document>")
    (source_root / "ignore.png").write_bytes(b"image")

    raw_blobs = list_local_raw_blobs(
        tmp_path,
        "fbn",
        recursive=True,
        nerilio_direct_only=True,
    )

    assert raw_blobs == [
        RawBlob(
            chatbot="fbn",
            blob_name="fbn/Wetstoelichtingen IB - SNAP demo.xml",
            relative_path="Wetstoelichtingen IB - SNAP demo.xml",
        )
    ]


@pytest.mark.asyncio
async def test_compile_chatbot_wiki_reuses_existing_source_page() -> None:
    blob_manager = FakeBlobManager()

    compiled_pages = await compile_chatbot_wiki(
        blob_manager,
        "nerilio",
        document_intelligence_parser=None,
        openai_client=None,
        chatgpt_model="gpt-4o",
        chatgpt_deployment=None,
        reasoning_effort=None,
        raw_chunk_chars=28000,
        max_source_pages=100,
        max_chunks_per_wiki_page=40,
        recursive=True,
        nerilio_direct_only=True,
        wiki_root="__llm_wiki__",
        dry_run=False,
        overwrite=False,
    )

    assert blob_manager.raw_downloads == []
    assert compiled_pages[0].markdown == EXISTING_MANUAL_MARKDOWN.decode("utf-8")
    assert "__llm_wiki__/nerilio/wiki/index.md" in blob_manager.uploaded_blobs
    assert b"[Existing Manual](sources/manual.md)" in blob_manager.uploaded_blobs[
        "__llm_wiki__/nerilio/wiki/index.md"
    ]
