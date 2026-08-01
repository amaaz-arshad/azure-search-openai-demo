"""Offline unit tests for scripts/scrape_bbsa.py (breitband.tirol scraper).

Network-facing fetchers are monkeypatched; everything else runs on small fixtures
mirroring the real structures — one WordPress + Elementor install served on a wildcard
subdomain per municipality, where the same page IDs return municipality-specific
rendered content per host.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import scrape_bbsa  # noqa: E402

BASE = "https://breitband.tirol"

HOME_HTML = """<!doctype html>
<html lang="de">
<head><title>Breitband.Tirol</title></head>
<body>
<header><a href="/home">Logo</a><nav><a href="/faqs-hp">FAQS</a></nav></header>
<main><h1>Fit für Gigabit</h1></main>
<footer><p>Anichstraße 7, 6020 Innsbruck</p><a href="mailto:office@bbsa.tirol">office@bbsa.tirol</a></footer>
</body></html>"""


def wp_page(page_id: int, slug: str, title: str, content: str, *, host: str = BASE, page_type: str = "page") -> dict:
    return {
        "id": page_id,
        "slug": slug,
        "link": f"{host}/{slug}/" if slug else f"{host}/",
        "type": page_type,
        "title": {"rendered": title},
        "content": {"rendered": content},
        "date": "2025-01-16T15:18:19",
        "modified": "2026-02-17T15:57:25",
    }


def long_body(text: str) -> str:
    """A body comfortably above MIN_CONTENT_CHARS so it is not skipped as a shell."""
    return f"<p>{text}</p>" + "<p>Glasfaser überträgt Daten mit Lichtimpulsen und ist extrem stabil.</p>" * 6


# Two of the 23 real pages carry per-municipality content ("home", "gemeindeinfos"); on the main
# host they render as near-empty shells. The rest are shared across every host.
MAIN_PAGES = [
    wp_page(1562, "", "Startseite", long_body("Fit für Gigabit")),
    wp_page(1520, "faqs-hp", "FAQs", long_body("Was ist Glasfaser?")),
    wp_page(1497, "deshalb-glasfaser-hp", "Deshalb Glasfaser", long_body("Gute Gründe")),
    wp_page(75, "faqs", "FAQs", long_body("Häufige Fragen der Gemeinde")),
    wp_page(1518, "blog-hp", "Blog", long_body("Blog")),
    wp_page(506, "verfuegbarkeitsanzeige", "Verfügbarkeitsanzeige", ""),
    wp_page(1339, "home", "Gemeindestartseite", "<p></p>"),
    wp_page(338, "gemeindeinfos", "Gemeindeinfos", "<p></p>"),
    wp_page(1320, "notpublished", "Diese Gemeinde-Website ist in Arbeit", "<p></p>"),
    wp_page(51, "home-alt", "Gemeindestartseite-Alt", "<p></p>"),
    wp_page(2000, "kurz", "Kurze Seite", "<p>Zu kurz.</p>"),
]

GEMEINDE_RECORDS = [
    {
        "id": 918,
        "slug": "schwoich",
        "link": f"{BASE}/gemeinde/schwoich/",
        "title": {"rendered": "Schwoich"},
        "date": "2025-01-16T15:18:19",
        "modified": "2026-02-17T15:57:25",
    },
    {
        "id": 3672,
        "slug": "bruck-ziller",
        "link": f"{BASE}/gemeinde/bruck-ziller/",
        "title": {"rendered": "Bruck am Ziller"},
        "date": "2025-02-01T00:00:00",
        "modified": "2026-03-01T00:00:00",
    },
    {
        "id": 4259,
        "slug": "leer",
        "link": f"{BASE}/gemeinde/leer/",
        "title": {"rendered": "Leerdorf"},
        "date": "2025-02-01T00:00:00",
        "modified": "2026-03-02T00:00:00",
    },
]


def gemeinde_pages(slug: str) -> list[dict]:
    """The subdomain's page list. 'leer' stands for a municipality whose page is not yet
    filled in — the subdomain exists but Gemeindeinfos has no municipality prose."""
    host = f"https://{slug}.breitband.tirol"
    name = {"schwoich": "Schwoich", "bruck-ziller": "Bruck am Ziller", "leer": "Leerdorf"}[slug]
    infos = (
        "<p></p>"
        if slug == "leer"
        else long_body(f"Die Gemeinde {name} verlegt ihr Glasfasernetz bis an die Grundstücksgrenze.")
    )
    return [
        wp_page(1339, "home", "Gemeindestartseite", f"<h1>Mein Glasfaseranschluss in {name}</h1>", host=host),
        wp_page(338, "gemeindeinfos", "Gemeindeinfos", infos, host=host),
        wp_page(1520, "faqs-hp", "FAQs", long_body("Was ist Glasfaser?"), host=host),
    ]


@pytest.fixture
def fake_site(monkeypatch):
    """Serve the fixture site for every host the scraper touches, with no network access."""

    def fake_fetch_collection(base_url, resource, fields="ignored"):
        host = base_url.rstrip("/")
        if resource == scrape_bbsa.GEMEINDE_RESOURCE:
            return list(GEMEINDE_RECORDS)
        if resource == "posts":
            return [wp_page(2389, "willkommen", "Willkommen!", "<p>Kurz.</p>", host=host, page_type="post")]
        if host == BASE:
            return list(MAIN_PAGES)
        slug = host.removeprefix("https://").split(".")[0]
        return gemeinde_pages(slug)

    def fake_fetch_text(url):
        return HOME_HTML, {}, url

    monkeypatch.setattr(scrape_bbsa, "fetch_collection", fake_fetch_collection)
    monkeypatch.setattr(scrape_bbsa, "fetch_text", fake_fetch_text)
    return fake_fetch_collection


def test_gemeinde_host_maps_slug_to_wildcard_subdomain():
    assert scrape_bbsa.gemeinde_host(BASE, "schwoich") == "https://schwoich.breitband.tirol"
    # A www. prefix on the base must not leak into the subdomain host.
    assert scrape_bbsa.gemeinde_host("https://www.breitband.tirol", "virgen") == "https://virgen.breitband.tirol"


def test_id_and_tags_from_url_uses_home_for_the_bare_homepage():
    assert scrape_bbsa.id_and_tags_from_url(f"{BASE}/", "page") == ("home", ["page"])
    assert scrape_bbsa.id_and_tags_from_url(f"{BASE}/faqs-hp/", "page") == ("faqs-hp", ["page"])
    assert scrape_bbsa.id_and_tags_from_url(f"{BASE}/gemeinde/schwoich/", "gemeinde") == (
        "gemeinde-schwoich",
        ["gemeinde"],
    )


def test_build_main_documents_skips_shells_dead_pages_and_per_municipality_pages(fake_site):
    documents = scrape_bbsa.build_main_documents(BASE)
    ids = [document["id"] for document in documents]

    assert "home" in ids and "faqs-hp" in ids and "deshalb-glasfaser-hp" in ids
    # Per-municipality pages are never taken from the main host (they are empty shells there).
    assert "gemeindeinfos" not in ids
    # Superseded / widget-only / empty-listing pages are skipped everywhere.
    for skipped in ("blog-hp", "verfuegbarkeitsanzeige", "notpublished", "home-alt"):
        assert skipped not in ids
    # Below MIN_CONTENT_CHARS -> shell.
    assert "kurz" not in ids
    # The thin "Willkommen!" post is a shell too.
    assert "willkommen" not in ids


def test_municipality_template_pages_get_a_disambiguating_title_suffix(fake_site):
    documents = {document["id"]: document for document in scrape_bbsa.build_main_documents(BASE)}
    # Both "FAQs" pages are live with different copy; the municipality-template one is suffixed so a
    # citation list does not show two identical titles pointing at different URLs.
    assert documents["faqs-hp"]["title"] == "FAQs"
    assert documents["faqs"]["title"] == "FAQs (Gemeinde-Website)"
    assert "gemeinde-website" in documents["faqs"]["tags"]


def test_build_chrome_document_captures_header_and_footer(fake_site):
    document = scrape_bbsa.build_chrome_document(BASE)
    assert document["id"] == "website-header-footer"
    assert document["type"] == "site-info"
    assert "office@bbsa.tirol" in document["content"]
    assert "Anichstraße 7" in document["content"]
    assert "## Header / Navigation" in document["content"]
    assert "## Footer" in document["content"]


def test_build_chrome_document_raises_when_chrome_is_gone(monkeypatch):
    monkeypatch.setattr(scrape_bbsa, "fetch_text", lambda url: ("<html><body><p>x</p></body></html>", {}, url))
    with pytest.raises(RuntimeError, match="header/footer"):
        scrape_bbsa.build_chrome_document(BASE)


def test_build_gemeinde_document_merges_hero_and_gemeindeinfos(fake_site):
    document = scrape_bbsa.build_gemeinde_document(BASE, GEMEINDE_RECORDS[0])

    assert document is not None
    assert document["id"] == "gemeinde-schwoich"
    assert document["type"] == "gemeinde"
    assert document["url"] == "https://schwoich.breitband.tirol/gemeindeinfos/"
    assert document["title"].startswith("Schwoich – ")
    assert document["tags"] == ["gemeinde", "schwoich"]
    # Both the hero line and the Gemeindeinfos body are present, and the municipality is named.
    assert "Mein Glasfaseranschluss in Schwoich" in document["content"]
    assert "bis an die Grundstücksgrenze" in document["content"]
    assert "https://schwoich.breitband.tirol/" in document["content"]


def test_build_gemeinde_document_skips_a_municipality_page_not_yet_filled_in(fake_site):
    assert scrape_bbsa.build_gemeinde_document(BASE, GEMEINDE_RECORDS[2]) is None


def test_build_gemeinde_document_skips_a_missing_subdomain(monkeypatch, fake_site):
    import urllib.error

    def raise_404(base_url, resource, fields="ignored"):
        raise urllib.error.HTTPError(base_url, 404, "Not Found", None, None)

    monkeypatch.setattr(scrape_bbsa, "fetch_collection", raise_404)
    assert scrape_bbsa.build_gemeinde_document(BASE, GEMEINDE_RECORDS[0]) is None


def test_build_gemeinde_document_propagates_a_server_error(monkeypatch, fake_site):
    import urllib.error

    def raise_500(base_url, resource, fields="ignored"):
        raise urllib.error.HTTPError(base_url, 500, "Server Error", None, None)

    monkeypatch.setattr(scrape_bbsa, "fetch_collection", raise_500)
    with pytest.raises(urllib.error.HTTPError):
        scrape_bbsa.build_gemeinde_document(BASE, GEMEINDE_RECORDS[0])


def test_scrape_emits_one_document_per_municipality_plus_the_shared_pages_once(fake_site):
    documents = scrape_bbsa.scrape(BASE)
    ids = [document["id"] for document in documents]

    assert len(ids) == len(set(ids)), "document ids must be unique"
    assert "website-header-footer" in ids
    assert "gemeinden-index" in ids
    assert "gemeinde-schwoich" in ids and "gemeinde-bruck-ziller" in ids
    # The unpublished municipality contributes no document ...
    assert "gemeinde-leer" not in ids
    # ... but is still listed in the index, flagged as in progress.
    index = next(document for document in documents if document["id"] == "gemeinden-index")
    assert "Leerdorf" in index["content"]
    assert "noch in Arbeit" in index["content"]
    assert "Schwoich: https://schwoich.breitband.tirol/" in index["content"]

    # Shared pages appear exactly once, from the main host — not once per municipality.
    assert ids.count("faqs-hp") == 1
    assert all(not document["url"].startswith("https://bruck-ziller") or document["id"] == "gemeinde-bruck-ziller" for document in documents)


def test_scrape_aborts_when_no_municipality_document_could_be_built(monkeypatch, fake_site):
    monkeypatch.setattr(scrape_bbsa, "build_gemeinde_documents", lambda base_url, records: [])
    with pytest.raises(RuntimeError, match="no municipality documents"):
        scrape_bbsa.scrape(BASE)


def test_scrape_aborts_when_the_gemeinde_post_type_is_empty(monkeypatch, fake_site):
    monkeypatch.setattr(scrape_bbsa, "fetch_gemeinde_records", lambda base_url: [])
    with pytest.raises(RuntimeError, match="no 'gemeinde' records"):
        scrape_bbsa.scrape(BASE)


def test_scrape_limit_gemeinden_restricts_the_crawl(fake_site):
    documents = scrape_bbsa.scrape(BASE, limit_gemeinden=1)
    gemeinde_ids = [document["id"] for document in documents if document["type"] == "gemeinde"]
    # Records are sorted by name: Bruck am Ziller, Leerdorf, Schwoich.
    assert gemeinde_ids == ["gemeinde-bruck-ziller"]


def test_fetch_remote_state_watermarks_pages_posts_gemeinden_and_chrome(monkeypatch, fake_site):
    def fake_fetch_json(url):
        return [{"modified": "2026-02-17T15:57:25"}], {"x-wp-total": "23"}

    monkeypatch.setattr(scrape_bbsa, "fetch_json", fake_fetch_json)
    state = scrape_bbsa.fetch_remote_state(BASE)

    assert state["pages"] == {"count": 23, "latest_modified": "2026-02-17T15:57:25"}
    assert state["posts"]["count"] == 23
    # The per-municipality map is the watermark that moves when a municipality's fields are edited;
    # the shared page IDs never change, so pages/posts alone would miss it.
    assert state["gemeinde"]["count"] == 3
    assert state["gemeinde"]["modified"]["schwoich"] == "2026-02-17T15:57:25"
    assert len(state["chrome_hash"]) == 64


def test_the_feed_payload_written_by_main_is_accepted_by_the_parser(tmp_path, fake_site, monkeypatch):
    """End-to-end contract: what the scraper writes is what prepdocslib/bbsajson.py validates."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "backend"))
    from prepdocslib.bbsajson import prepare_bbsa_dataset, validate_bbsa_payload

    output = tmp_path / "bbsa.json"
    monkeypatch.setattr(sys, "argv", ["scrape_bbsa.py", "--output", str(output)])
    assert scrape_bbsa.main() == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["feed"] == "breitband.tirol"
    assert payload["count"] == len(payload["documents"])
    validate_bbsa_payload(payload)
    dataset = prepare_bbsa_dataset(payload, dataset_filename="bbsa.json", category="bbsa")
    assert dataset.documents
    assert {document.category for document in dataset.documents} == {"bbsa"}
