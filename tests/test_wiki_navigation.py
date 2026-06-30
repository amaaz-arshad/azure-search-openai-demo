from types import SimpleNamespace

from approaches.chatreadretrieveread import (
    extract_wiki_links,
    parse_wiki_page_selection,
    split_wiki_frontmatter,
    wiki_page_citation,
)


def make_completion(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_split_wiki_frontmatter_extracts_block_and_body():
    markdown = '---\ntitle: "Intro"\nslug: intro\nsources: ["https://x/y"]\n---\n\n# Intro\n\nBody text.'
    frontmatter, body = split_wiki_frontmatter(markdown)
    assert "title:" in frontmatter
    assert body.startswith("# Intro")


def test_split_wiki_frontmatter_no_frontmatter():
    frontmatter, body = split_wiki_frontmatter("# No frontmatter\n\nbody")
    assert frontmatter == ""
    assert body.startswith("# No frontmatter")


def test_wiki_page_citation_prefers_source_then_title_then_slug():
    fm_with_source = 'title: "Intro"\nsources: ["https://example.com/a", "https://example.com/b"]'
    assert wiki_page_citation(fm_with_source, "intro") == "https://example.com/a"

    fm_title_only = 'title: "My Title"\nrelated: []'
    assert wiki_page_citation(fm_title_only, "intro") == "My Title"

    assert wiki_page_citation("", "intro-slug") == "intro-slug"


def test_extract_wiki_links_normalizes_and_dedupes():
    body = "See [[attention-mechanism]] and [[Self-Attention.md|self attention]] and [[attention-mechanism]] again."
    assert extract_wiki_links(body) == ["attention-mechanism", "self-attention"]


def test_parse_wiki_page_selection_valid_json():
    pages, done = parse_wiki_page_selection(make_completion('{"pages": ["a", "b"], "done": true}'))
    assert pages == ["a", "b"]
    assert done is True


def test_parse_wiki_page_selection_strips_code_fence():
    pages, done = parse_wiki_page_selection(make_completion('```json\n{"pages": ["x"], "done": false}\n```'))
    assert pages == ["x"]
    assert done is False


def test_parse_wiki_page_selection_empty_means_done():
    pages, done = parse_wiki_page_selection(make_completion(""))
    assert pages == []
    assert done is True


def test_parse_wiki_page_selection_malformed_falls_back_to_quoted_slugs():
    pages, done = parse_wiki_page_selection(make_completion('I would read "intro" and "setup-guide".'))
    assert pages == ["intro", "setup-guide"]
    assert done is False
