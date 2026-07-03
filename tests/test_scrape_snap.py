"""Offline unit tests for scripts/scrape_snap.py (snap.de + nerilio.ai scraper).

Network-facing fetchers are monkeypatched; everything else is exercised on small
HTML fixtures mirroring the real structures (snap.de Divi chrome, nerilio.ai
pre-rendered React pages with FAQ answers in JSON-LD structured data).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import scrape_snap  # noqa: E402

NERILIO_BASE = "https://nerilio.ai"
SNAP_BASE = "https://www.snap.de"

NERILIO_PAGE_HTML = """<!doctype html>
<html lang="de">
<head><title>FAQ – Häufige Fragen zu nerilio</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[
 {"@type":"Question","name":"Was ist nerilio?",
  "acceptedAnswer":{"@type":"Answer","text":"nerilio ist ein KI-Assistent."}},
 {"@type":"Question","name":"Was ist nerilio?",
  "acceptedAnswer":{"@type":"Answer","text":"Duplikat, wird ignoriert."}},
 {"@type":"Question","name":"Ohne Antwort?"}
]}
</script>
</head>
<body>
<header class="fixed"><nav><a>Vorteile</a><a>Use Cases</a></nav><button>de</button><button>en</button></header>
<main><h1>Häufige Fragen</h1><p>Alles über [nerilio] hier.</p>
<script>var hidden = "nicht sichtbar";</script>
<a href="/de/impressum#top">Impressum</a>
<a href="https://chat.nerilio.ai/free">Chat</a>
<a href="mailto:hallo@nerilio.ai">Mail</a>
</main>
<footer><p>Max-Brauer-Allee 50, 22765 Hamburg</p></footer>
</body></html>"""


def test_extract_tag_blocks_handles_nesting_and_multiple_blocks():
    html_text = "<header a=1><header>inner</header>tail</header><p>x</p><header>second</header>"
    blocks = scrape_snap.extract_tag_blocks(html_text, "header")
    assert blocks == ["<header a=1><header>inner</header>tail</header>", "<header>second</header>"]


def test_extract_tag_blocks_ignores_similarly_named_tags():
    assert scrape_snap.extract_tag_blocks("<headerx>nope</headerx>", "header") == []


def test_extract_body_drops_head_content():
    body = scrape_snap.extract_body(NERILIO_PAGE_HTML)
    assert "Häufige Fragen" in body
    assert "<title>" not in body


def test_extract_site_chrome_returns_header_and_footer_markdown():
    chrome = scrape_snap.extract_site_chrome(scrape_snap.extract_body(NERILIO_PAGE_HTML), NERILIO_BASE)
    assert "Vorteile" in chrome["header"] and "Use Cases" in chrome["header"]
    assert "Max-Brauer-Allee 50" in chrome["footer"]


def test_clean_html_excludes_chrome_and_keeps_bracketed_prose():
    body = scrape_snap.extract_body(NERILIO_PAGE_HTML)
    content = scrape_snap.clean_html(body, NERILIO_BASE, strip_shortcodes=False, exclude_tags=scrape_snap.CHROME_TAGS)
    assert "# Häufige Fragen" in content
    assert "[nerilio]" in content  # literal brackets survive with strip_shortcodes=False
    assert "Vorteile" not in content and "Max-Brauer-Allee" not in content  # chrome excluded
    assert "nicht sichtbar" not in content  # script dropped


def test_clean_html_separates_linkless_anchors_and_buttons():
    html_text = "<p><a>Vorteile</a><a>Use Cases</a><button>de</button><button>en</button></p>"
    content = scrape_snap.clean_html(html_text, NERILIO_BASE, strip_shortcodes=False)
    assert "Vorteile Use Cases de en" in content


def test_clean_html_strips_soft_hyphens_and_icon_glyphs():
    soft_hyphen, icon_glyph = "\u00ad", "\ue01d"  # Divi icon font uses the private use area
    html_text = f"<p>Softwareentwicklungs{soft_hyphen}gesellschaft <a href='https://x.example/y'>{icon_glyph}</a></p>"
    content = scrape_snap.clean_html(html_text, SNAP_BASE, strip_shortcodes=False)
    assert "Softwareentwicklungsgesellschaft" in content
    assert icon_glyph not in content
    # An icon-glyph-only link keeps the bare URL instead of collapsing to an empty [](url).
    assert "[](" not in content and "https://x.example/y" in content


def test_extract_html_title():
    assert scrape_snap.extract_html_title(NERILIO_PAGE_HTML) == "FAQ – Häufige Fragen zu nerilio"
    assert scrape_snap.extract_html_title("<p>no title</p>") == ""


def test_is_same_site_treats_www_prefix_as_equal():
    assert scrape_snap.is_same_site("https://www.nerilio.ai/de/", NERILIO_BASE)
    assert scrape_snap.is_same_site("https://nerilio.ai/de/", "https://www.nerilio.ai")
    assert not scrape_snap.is_same_site("https://chat.nerilio.ai/free", NERILIO_BASE)
    assert not scrape_snap.is_same_site("https://www.snap.de/", NERILIO_BASE)


def test_parse_sitemap_urls_filters_and_dedupes():
    xml = """<urlset>
      <url><loc>https://nerilio.ai/de/</loc></url>
      <url><loc> https://nerilio.ai/de/faq </loc></url>
      <url><loc>https://nerilio.ai/de/</loc></url>
      <url><loc>https://other.example/x</loc></url>
    </urlset>"""
    assert scrape_snap.parse_sitemap_urls(xml, NERILIO_BASE) == [
        "https://nerilio.ai/de/",
        "https://nerilio.ai/de/faq",
    ]


def test_extract_internal_links_resolves_and_filters():
    links = scrape_snap.extract_internal_links(NERILIO_PAGE_HTML, f"{NERILIO_BASE}/de/faq", NERILIO_BASE)
    # Relative resolved + fragment stripped; chat subdomain and mailto excluded.
    assert links == [f"{NERILIO_BASE}/de/impressum"]


def test_nerilio_id_and_tags_are_site_prefixed():
    assert scrape_snap.nerilio_id_and_tags(f"{NERILIO_BASE}/de/faq", "page") == (
        "nerilio-de-faq",
        ["nerilio", "de", "page"],
    )
    assert scrape_snap.nerilio_id_and_tags(f"{NERILIO_BASE}/de/", "page") == ("nerilio-de", ["nerilio", "page"])


def test_extract_faq_pairs_reads_json_ld_and_dedupes():
    pairs = scrape_snap.extract_faq_pairs(NERILIO_PAGE_HTML)
    assert pairs == [("Was ist nerilio?", "nerilio ist ein KI-Assistent.")]


def test_extract_faq_pairs_supports_graph_wrapper_and_ignores_bad_json():
    html_text = """<script type="application/ld+json">{not json}</script>
    <script type="application/ld+json">
    {"@graph":[{"@type":"FAQPage","mainEntity":[
      {"@type":"Question","name":"Q1","acceptedAnswer":{"text":"A1"}}]}]}
    </script>"""
    assert scrape_snap.extract_faq_pairs(html_text) == [("Q1", "A1")]


def test_build_nerilio_document_appends_faq_and_uses_last_modified():
    document = scrape_snap.build_nerilio_document(
        NERILIO_PAGE_HTML,
        {"last-modified": "Tue, 23 Jun 2026 07:18:53 GMT"},
        f"{NERILIO_BASE}/de/faq",
        NERILIO_BASE,
    )
    assert document["id"] == "nerilio-de-faq"
    assert document["title"] == "FAQ – Häufige Fragen zu nerilio"
    assert document["url"] == f"{NERILIO_BASE}/de/faq"
    assert document["date"] == "2026-06-23"
    assert document["tags"] == ["nerilio", "de", "page"]
    assert "## FAQ – Fragen & Antworten" in document["content"]
    assert "nerilio ist ein KI-Assistent." in document["content"]
    assert "Max-Brauer-Allee" not in document["content"]  # footer chrome excluded per page


def test_http_date_to_iso_date():
    assert scrape_snap.http_date_to_iso_date("Tue, 23 Jun 2026 07:18:53 GMT") == "2026-06-23"
    assert scrape_snap.http_date_to_iso_date("garbage") == ""
    assert scrape_snap.http_date_to_iso_date(None) == ""


def test_merge_documents_sorts_and_rejects_collisions():
    a = {"id": "x", "url": "https://a.example/2"}
    b = {"id": "y", "url": "https://a.example/1"}
    assert scrape_snap.merge_documents([a], [b]) == [b, a]
    with pytest.raises(RuntimeError, match="duplicate feed document id"):
        scrape_snap.merge_documents([a], [{"id": "x", "url": "https://a.example/3"}])


def test_scrape_snap_site_chrome_builds_site_info_document(monkeypatch):
    snap_home = (
        "<html><head><title>SNAP</title></head><body>"
        "<header id='main-header'><nav><a href='/beratung/'>Beratung</a></nav></header>"
        "<div>body text</div>"
        "<footer class='et-l et-l--footer'><p>Max-Brauer-Allee 50 22765 Hamburg</p></footer>"
        "</body></html>"
    )
    monkeypatch.setattr(scrape_snap, "fetch_text", lambda url: (snap_home, {}, SNAP_BASE + "/"))
    document = scrape_snap.scrape_snap_site_chrome(SNAP_BASE)
    assert document["id"] == "website-header-footer"
    assert document["type"] == "site-info"
    assert document["url"] == SNAP_BASE + "/"
    assert "[Beratung](https://www.snap.de/beratung/)" in document["content"]
    assert "Max-Brauer-Allee 50 22765 Hamburg" in document["content"]
    assert "body text" not in document["content"]


def test_scrape_snap_site_chrome_fails_loudly_without_chrome(monkeypatch):
    monkeypatch.setattr(scrape_snap, "fetch_text", lambda url: ("<html><body><p>x</p></body></html>", {}, SNAP_BASE))
    with pytest.raises(RuntimeError, match="header/footer chrome"):
        scrape_snap.scrape_snap_site_chrome(SNAP_BASE)


def test_build_nerilio_chrome_document_combines_locales():
    de = "<body><header><a>Vorteile</a></header><footer><p>Hamburg DE</p></footer></body>"
    en = "<body><header><a>Benefits</a></header><footer><p>Hamburg EN</p></footer></body>"
    document = scrape_snap.build_nerilio_chrome_document(NERILIO_BASE, {"de": de, "en": en})
    assert document["id"] == "nerilio-website-header-footer"
    assert document["type"] == "site-info"
    assert "## Header / Navigation (DE)" in document["content"]
    assert "## Footer (EN)" in document["content"]
    assert "Hamburg DE" in document["content"] and "Hamburg EN" in document["content"]
    with pytest.raises(RuntimeError, match="chrome"):
        scrape_snap.build_nerilio_chrome_document(NERILIO_BASE, {})


def test_fetch_remote_state_combines_both_sites(monkeypatch):
    monkeypatch.setattr(scrape_snap, "fetch_snap_remote_state", lambda base: {"pages": 1})
    monkeypatch.setattr(scrape_snap, "fetch_nerilio_remote_state", lambda base: {"sitemap": 2})
    state = scrape_snap.fetch_remote_state(SNAP_BASE, NERILIO_BASE)
    assert state == {"snap": {"pages": 1}, "nerilio": {"sitemap": 2}}


def test_fetch_nerilio_remote_state_heads_sitemap_pages(monkeypatch):
    sitemap = "<urlset><url><loc>https://nerilio.ai/de/</loc></url><url><loc>https://nerilio.ai/de/faq</loc></url></urlset>"
    monkeypatch.setattr(scrape_snap, "fetch_text", lambda url: (sitemap, {}, url))
    monkeypatch.setattr(scrape_snap, "fetch_head", lambda url: {"etag": f"etag:{url}"})
    state = scrape_snap.fetch_nerilio_remote_state(NERILIO_BASE)
    assert state["sitemap"] == {"etag": f"etag:{NERILIO_BASE}/sitemap.xml"}
    assert set(state["pages"]) == {"https://nerilio.ai/de/", "https://nerilio.ai/de/faq"}


def test_scrape_nerilio_crawls_sitemap_and_appends_chrome_doc(monkeypatch):
    sitemap = "<urlset><url><loc>https://nerilio.ai/de/</loc></url><url><loc>https://nerilio.ai/de/faq</loc></url></urlset>"
    home = (
        "<html><head><title>nerilio DE</title></head><body>"
        "<header><a>Vorteile</a></header><main><p>Start</p><a href='/de/agb'>AGB</a></main>"
        "<footer><p>Hamburg</p></footer></body></html>"
    )
    faq = "<html><head><title>FAQ</title></head><body><main><p>Fragen</p></main></body></html>"
    agb = "<html><head><title>AGB</title></head><body><main><p>Bedingungen</p></main></body></html>"
    pages = {
        f"{NERILIO_BASE}/sitemap.xml": (sitemap, {"content-type": "application/xml"}),
        f"{NERILIO_BASE}/de/": (home, {"content-type": "text/html"}),
        f"{NERILIO_BASE}/de/faq": (faq, {"content-type": "text/html"}),
        f"{NERILIO_BASE}/de/agb": (agb, {"content-type": "text/html"}),
    }
    monkeypatch.setattr(scrape_snap, "fetch_text", lambda url: (*pages[url], url))
    documents = scrape_snap.scrape_nerilio(NERILIO_BASE)
    ids = [document["id"] for document in documents]
    # Sitemap pages, the link-discovered AGB page, and the chrome doc.
    assert sorted(ids) == ["nerilio-de", "nerilio-de-agb", "nerilio-de-faq", "nerilio-website-header-footer"]
    home_doc = next(d for d in documents if d["id"] == "nerilio-de")
    assert "Start" in home_doc["content"] and "Vorteile" not in home_doc["content"]


def _nerilio_fixture_pages(overrides=None):
    sitemap = (
        "<urlset><url><loc>https://nerilio.ai/de/</loc></url>"
        "<url><loc>https://nerilio.ai/de/faq</loc></url></urlset>"
    )
    home = (
        "<html><head><title>nerilio DE</title></head><body>"
        "<header><a>Vorteile</a></header><main><p>Start</p></main>"
        "<footer><p>Hamburg</p></footer></body></html>"
    )
    faq = "<html><head><title>FAQ</title></head><body><main><p>Fragen</p></main></body></html>"
    pages = {
        f"{NERILIO_BASE}/sitemap.xml": (sitemap, {"content-type": "application/xml"}),
        f"{NERILIO_BASE}/de/": (home, {"content-type": "text/html"}),
        f"{NERILIO_BASE}/de/faq": (faq, {"content-type": "text/html"}),
    }
    pages.update(overrides or {})
    return pages


def _http_error(url, code):
    import urllib.error

    return urllib.error.HTTPError(url, code, "err", None, None)


def test_scrape_nerilio_aborts_on_server_error(monkeypatch):
    """A 5xx page must fail the whole run: the refresh pipeline deletes the entire
    category before reindexing, so an incomplete crawl would wipe those pages."""
    pages = _nerilio_fixture_pages()

    def fake_fetch(url):
        if url.endswith("/de/faq"):
            raise _http_error(url, 503)
        return (*pages[url], url)

    monkeypatch.setattr(scrape_snap, "fetch_text", fake_fetch)
    with pytest.raises(RuntimeError, match="HTTP 503"):
        scrape_snap.scrape_nerilio(NERILIO_BASE)


def test_scrape_nerilio_aborts_on_network_error(monkeypatch):
    import urllib.error

    pages = _nerilio_fixture_pages()

    def fake_fetch(url):
        if url.endswith("/de/faq"):
            raise urllib.error.URLError("connection reset")
        return (*pages[url], url)

    monkeypatch.setattr(scrape_snap, "fetch_text", fake_fetch)
    with pytest.raises(RuntimeError, match="failed to fetch"):
        scrape_snap.scrape_nerilio(NERILIO_BASE)


def test_scrape_nerilio_drops_gone_pages_and_continues(monkeypatch):
    """404/410 means the page was genuinely removed: it drops out of the feed
    (index mirrors the live site) without failing the run."""
    pages = _nerilio_fixture_pages()

    def fake_fetch(url):
        if url.endswith("/de/faq"):
            raise _http_error(url, 404)
        return (*pages[url], url)

    monkeypatch.setattr(scrape_snap, "fetch_text", fake_fetch)
    documents = scrape_snap.scrape_nerilio(NERILIO_BASE)
    ids = sorted(document["id"] for document in documents)
    assert ids == ["nerilio-de", "nerilio-website-header-footer"]


def test_scrape_nerilio_drops_offsite_redirect_targets(monkeypatch):
    """A page that 301s to a foreign host must not inject third-party content into
    the feed under a nerilio id (parked domain / migration scenario)."""
    pages = _nerilio_fixture_pages()
    foreign = "<html><head><title>Parked</title></head><body><main><p>Buy cheap widgets!</p></main></body></html>"

    def fake_fetch(url):
        if url.endswith("/de/faq"):
            return foreign, {"content-type": "text/html"}, "https://parked.example.com/landing"
        return (*pages[url], url)

    monkeypatch.setattr(scrape_snap, "fetch_text", fake_fetch)
    documents = scrape_snap.scrape_nerilio(NERILIO_BASE)
    ids = sorted(document["id"] for document in documents)
    assert ids == ["nerilio-de", "nerilio-website-header-footer"]
    assert not any("widgets" in document["content"] for document in documents)


def test_scrape_nerilio_aborts_on_empty_sitemap(monkeypatch):
    monkeypatch.setattr(scrape_snap, "fetch_text", lambda url: ("<urlset></urlset>", {}, url))
    with pytest.raises(RuntimeError, match="no usable page URLs"):
        scrape_snap.scrape_nerilio(NERILIO_BASE)


def test_scrape_nerilio_crawl_cap_ignores_duplicate_queue_entries(monkeypatch):
    """A complete crawl exactly at the cap must succeed; only genuinely uncrawled
    URLs beyond the cap abort the run."""
    pages = _nerilio_fixture_pages()
    # Home links back to the FAQ (already a seed) -> a duplicate queue entry remains
    # when the cap is reached; that must not abort.
    home_with_link = pages[f"{NERILIO_BASE}/de/"][0].replace(
        "<main><p>Start</p></main>", "<main><p>Start</p><a href='/de/faq'>FAQ</a></main>"
    )
    pages[f"{NERILIO_BASE}/de/"] = (home_with_link, {"content-type": "text/html"})
    monkeypatch.setattr(scrape_snap, "fetch_text", lambda url: (*pages[url], url))
    monkeypatch.setattr(scrape_snap, "MAX_CRAWL_PAGES", 2)
    documents = scrape_snap.scrape_nerilio(NERILIO_BASE)
    assert sorted(d["id"] for d in documents) == ["nerilio-de", "nerilio-de-faq", "nerilio-website-header-footer"]


def test_extract_faq_pairs_accepts_type_arrays_and_keeps_brackets():
    html_text = """<script type="application/ld+json">
    {"@type":["FAQPage","WebPage"],"mainEntity":[
      {"@type":"Question","name":"Ist das [optional]?","acceptedAnswer":{"text":"Ja, [optional] geht."}}]}
    </script>"""
    assert scrape_snap.extract_faq_pairs(html_text) == [("Ist das [optional]?", "Ja, [optional] geht.")]


def test_extract_html_title_keeps_bracketed_prose():
    assert scrape_snap.extract_html_title("<title>nerilio [Beta] FAQ</title>") == "nerilio [Beta] FAQ"


def test_glyph_only_image_alt_is_dropped_entirely():
    icon_glyph = "\ue01d"
    html_text = f'<p>Text davor <img alt="{icon_glyph}" src="https://x.example/i.png"> danach</p>'
    content = scrape_snap.clean_html(html_text, SNAP_BASE, strip_shortcodes=False)
    assert content == "Text davor danach"


def test_refresh_snap_payload_validation_requires_both_sites(monkeypatch, tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "backend"))
    import refresh_snap

    def write_payload(documents):
        payload_path = tmp_path / "snap.json"
        payload_path.write_text(
            json.dumps({"feed": "snap.de", "documents": documents}, ensure_ascii=False), encoding="utf-8"
        )
        return payload_path

    both = [{"id": "home", "url": "u"}, {"id": "nerilio-de", "url": "u"}]
    monkeypatch.setattr(refresh_snap, "SNAP_JSON", write_payload(both))
    assert refresh_snap.load_scraped_payload()["documents"] == both

    monkeypatch.setattr(refresh_snap, "SNAP_JSON", write_payload([{"id": "home", "url": "u"}]))
    with pytest.raises(SystemExit, match="missing one site"):
        refresh_snap.load_scraped_payload()

    monkeypatch.setattr(refresh_snap, "SNAP_JSON", write_payload([{"id": "nerilio-de", "url": "u"}]))
    with pytest.raises(SystemExit, match="missing one site"):
        refresh_snap.load_scraped_payload()
