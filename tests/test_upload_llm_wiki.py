from pathlib import Path

import pytest

from upload_llm_wiki import build_wiki_uploads, default_wiki_dir, get_blob_prefix


def test_get_blob_prefix_scopes_wiki_by_source_chatbot() -> None:
    assert get_blob_prefix("Nerilio") == "__llm_wiki__/nerilio/wiki"


def test_default_wiki_dir_uses_data_llm_wiki_layout() -> None:
    assert default_wiki_dir("nerilio").as_posix().endswith("data/llm-wiki/nerilio/wiki")


def test_build_wiki_uploads_preserves_markdown_relative_paths(tmp_path: Path) -> None:
    wiki_dir = tmp_path / "wiki"
    (wiki_dir / "concepts").mkdir(parents=True)
    (wiki_dir / "index.md").write_text("# Index\n", encoding="utf-8")
    (wiki_dir / "concepts" / "sync.md").write_text("# Sync\n", encoding="utf-8")
    (wiki_dir / "notes.txt").write_text("skip", encoding="utf-8")

    uploads = build_wiki_uploads("nerilio", wiki_dir)

    assert uploads == [
        (wiki_dir / "concepts" / "sync.md", "__llm_wiki__/nerilio/wiki/concepts/sync.md"),
        (wiki_dir / "index.md", "__llm_wiki__/nerilio/wiki/index.md"),
    ]


def test_build_wiki_uploads_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_wiki_uploads("nerilio", tmp_path / "missing")
