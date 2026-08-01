#!/usr/bin/env python3
"""Scrape the breitband.tirol website into data/bbsa.json (category "bbsa").

breitband.tirol is the Breitbandserviceagentur Tirol (BBSA) portal for the
community-owned open fiber networks of Tyrol. It is a WordPress site built with
Elementor, and structured content is pulled from the public WordPress REST API
(``/wp-json/wp/v2/pages``, ``/posts`` and the ``gemeinde`` custom post type) rather
than from crawled HTML: the API returns a first-class ``link`` (live page URL) and a
``content.rendered`` body with no nav/footer/cookie-banner noise. Because the API
returns no theme chrome, the site-wide header/footer (navigation, office address,
phone, e-mail, legal links) is scraped separately from the rendered homepage HTML
into one dedicated "website-header-footer" document.

ONE WORDPRESS INSTALL, MANY HOSTS. The same install is served on a wildcard
subdomain per municipality (``schwoich.breitband.tirol``, ``virgen.breitband.tirol``,
…), and the REST API is host-aware: the *same* page IDs return
municipality-specific rendered content per host. Almost every page is byte-identical
across hosts — only ``gemeindeinfos`` (build status, who pays for the house
connection, the local contact person, the providers selling service over that
municipality's network) and the ``home`` hero line actually vary. So the shared
pages are scraped ONCE from the main host and each municipality contributes exactly
one document assembled from its varying parts. Indexing all pages for all hosts was
deliberately rejected: ~90% would be byte-identical boilerplate, which degrades
retrieval and makes citations point at arbitrary subdomains.

``breitband.tirol/gemeinde/<slug>/`` (the ``gemeinde`` post type) is only a directory
stub — it renders nav/footer and nothing else — so it is used purely as the list of
municipalities (and as the per-municipality change-detection watermark, since each
record carries its own ``modified`` timestamp), never as content.

Output shape (consumed by ``app/backend/prepdocslib/bbsajson.py``)::

    {
      "feed": "breitband.tirol",
      "generated_at": "<ISO8601 UTC>",
      "sources": ["https://breitband.tirol"],
      "count": <int>,
      "documents": [
        {"id", "title", "url", "content", "tags": [...], "type", "date"}
      ]
    }

Pure standard library. The HTML-to-markdown machinery is imported from the sibling
``scrape_snap`` module so both site scrapers share one converter; the HTTP layer is
owned here so outgoing requests carry a bbsa User-Agent. Run from the repo root::

    python scripts/scrape_bbsa.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

# Shared HTML -> markdown conversion (Elementor and Divi bodies need the same treatment).
# sys.path[0] is already this directory when run as a script; the insert keeps the import
# working when refresh_bbsa.py imports this module for its change check.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrape_snap import (  # noqa: E402
    clean_html,
    clean_inline,
    extract_body,
    extract_site_chrome,
    slugify,
)

DEFAULT_BASE_URL = "https://breitband.tirol"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "bbsa.json"
USER_AGENT = "bbsa-content-scraper/1.0 (+https://breitband.tirol)"
PER_PAGE = 100
REQUEST_TIMEOUT = 45
FEED_MARKER = "breitband.tirol"

# Custom post type holding one record per participating municipality.
GEMEINDE_RESOURCE = "gemeinde"

# Municipality subdomains are fetched concurrently (one REST list request each).
GEMEINDE_FETCH_WORKERS = 6

# A main-site page whose extracted markdown is shorter than this is a shell: an
# Elementor template with no prose of its own, or a page whose body is a JavaScript
# widget (the address availability checker). Indexing those adds noise, not answers.
MIN_CONTENT_CHARS = 250

# Pages whose rendered content varies per municipality. Never indexed from the main
# host (where they render as empty shells); they are the raw material for the
# per-municipality documents instead. Keyed by WP slug, which is stable across hosts.
GEMEINDE_CONTENT_SLUGS = ("home", "gemeindeinfos")

# Superseded or non-content pages, skipped everywhere. "home-alt" and "notpublished"
# are alternate/placeholder copies of the municipality homepage template;
# "gemeinde-suchen" and "verfuegbarkeitsanzeige" are JavaScript widget hosts with no
# prose; "blog-hp" is an empty post-listing page.
SKIP_PAGE_SLUGS = frozenset({"home-alt", "notpublished", "gemeinde-suchen", "verfuegbarkeitsanzeige", "blog-hp"})

# The statewide portal and the per-municipality website template are BOTH live and
# share several page titles ("FAQs", "Deshalb Glasfaser", …) with different, shorter
# copy. These slugs belong to the municipality template (reachable under every
# subdomain), so their titles are suffixed to keep the two apart in a citation list.
GEMEINDE_TEMPLATE_SLUGS = frozenset(
    {"deshalb-glasfaser", "mein-glasfaser", "faqs", "faq-glasfaser", "allgemeine-information", "datenschutzerklaerung", "cookie-erklaerung"}
)
GEMEINDE_TEMPLATE_TITLE_SUFFIX = " (Gemeinde-Website)"

# Below this, a municipality's Gemeindeinfos page is considered not yet filled in: the
# subdomain exists but carries no municipality-specific prose. Such a municipality is
# reported in the index document and contributes no document of its own.
MIN_GEMEINDE_CONTENT_CHARS = 200


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def fetch_json(url: str) -> tuple[Any, dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310 (trusted host)
        payload = json.loads(response.read().decode("utf-8"))
        headers = {key.lower(): value for key, value in response.headers.items()}
    return payload, headers


def fetch_text(url: str) -> tuple[str, dict[str, str], str]:
    """GET a URL (following redirects) and return (decoded body, lower-cased headers,
    final URL after redirects)."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310 (trusted host)
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        headers = {key.lower(): value for key, value in response.headers.items()}
        final_url = response.geturl()
    return raw.decode(charset, errors="replace"), headers, final_url


def fetch_collection(base_url: str, resource: str, fields: str = "id,slug,link,type,title,content,date,modified") -> list[dict[str, Any]]:
    """Fetch all records of a WP REST collection, paginating as needed."""
    records: list[dict[str, Any]] = []
    page = 1
    while True:
        url = f"{base_url}/wp-json/wp/v2/{resource}?per_page={PER_PAGE}&page={page}&_fields={fields}"
        try:
            payload, headers = fetch_json(url)
        except urllib.error.HTTPError as error:
            # WP returns 400 when paging past the last page — treat as end of collection.
            if error.code == 400 and page > 1:
                break
            raise
        if not isinstance(payload, list) or not payload:
            break
        records.extend(payload)
        total_pages = int(headers.get("x-wp-totalpages", "1") or "1")
        if page >= total_pages:
            break
        page += 1
    return records


def record_slug(record: dict[str, Any]) -> str:
    return str(record.get("slug") or "").strip().lower()


def record_title(record: dict[str, Any]) -> str:
    return clean_inline(str((record.get("title") or {}).get("rendered", "")))


def record_markdown(record: dict[str, Any], base_url: str) -> str:
    return clean_html(str((record.get("content") or {}).get("rendered", "")), base_url)


def record_date(record: dict[str, Any]) -> str:
    """Prefer the last-modified date, falling back to the publish date."""
    for field in ("modified", "date"):
        value = str(record.get(field) or "").strip()
        if value:
            return value[:10]
    return ""


def id_and_tags_from_url(link: str, page_type: str) -> tuple[str, list[str]]:
    """Derive a stable record id plus retrieval tags from a page URL path."""
    segments = [segment for segment in urlparse(link).path.strip("/").split("/") if segment]
    if not segments:
        # Parser prepends the dataset slug ("bbsa"), so a bare "home" yields "bbsa-home".
        return "home", [page_type]
    tags = list(segments[:-1])
    tags.append(page_type)
    return slugify("-".join(segments)), list(dict.fromkeys(tags))


def gemeinde_host(base_url: str, slug: str) -> str:
    """Map a municipality slug to its wildcard subdomain, preserving the scheme."""
    parsed = urlparse(base_url)
    host = parsed.netloc.lower().removeprefix("www.")
    return f"{parsed.scheme or 'https'}://{slug}.{host}"


def build_main_documents(base_url: str) -> list[dict[str, Any]]:
    """Scrape the statewide portal's pages and posts (one document each), skipping
    shells, superseded copies, and the pages whose content is per-municipality."""
    documents: list[dict[str, Any]] = []
    for resource in ("pages", "posts"):
        records = fetch_collection(base_url, resource)
        log(f"Fetched {len(records)} {resource} from {base_url}")
        for record in records:
            slug = record_slug(record)
            link = str(record.get("link") or "").strip()
            if not link:
                continue
            if slug in SKIP_PAGE_SLUGS:
                log(f"  skip {slug}: superseded or non-content page")
                continue
            if slug in GEMEINDE_CONTENT_SLUGS:
                log(f"  skip {slug}: per-municipality page (scraped per subdomain)")
                continue
            content = record_markdown(record, base_url)
            if len(content) < MIN_CONTENT_CHARS:
                log(f"  skip {slug}: only {len(content)} chars of content (shell page)")
                continue
            page_type = str(record.get("type") or "page").strip() or "page"
            record_id, tags = id_and_tags_from_url(link, page_type)
            title = record_title(record)
            if slug in GEMEINDE_TEMPLATE_SLUGS:
                title += GEMEINDE_TEMPLATE_TITLE_SUFFIX
                tags.append("gemeinde-website")
            documents.append(
                {
                    "id": record_id,
                    "title": title,
                    "url": link,
                    "content": content,
                    "tags": list(dict.fromkeys(tags)),
                    "type": page_type,
                    "date": record_date(record),
                }
            )
    return documents


def build_chrome_document(base_url: str) -> dict[str, Any]:
    """Scrape the site-wide header/footer (navigation, BBSA address, phone, e-mail,
    legal links) from the rendered homepage — the WP REST API never returns theme
    chrome. Raises if nothing is extractable, so a redesign fails the run loudly
    instead of silently dropping the contact data from the index."""
    log(f"Fetching site header/footer from {base_url} ...")
    page_html, _, final_url = fetch_text(base_url + "/")
    chrome = extract_site_chrome(extract_body(page_html), base_url)
    if not chrome:
        raise RuntimeError(f"could not extract header/footer chrome from {final_url}")
    parts = ["# Breitband.Tirol – Website-Navigation, Adresse & Kontakt"]
    if chrome.get("header"):
        parts.append(f"## Header / Navigation\n\n{chrome['header']}")
    if chrome.get("footer"):
        parts.append(f"## Footer\n\n{chrome['footer']}")
    return {
        "id": "website-header-footer",
        "title": "Breitband.Tirol – Adresse, Kontakt & Website-Navigation (Header & Footer)",
        "url": final_url,
        "content": "\n\n".join(parts),
        "tags": ["website"],
        "type": "site-info",
        "date": datetime.now(timezone.utc).date().isoformat(),
    }


def fetch_gemeinde_records(base_url: str) -> list[dict[str, Any]]:
    """List the municipalities from the ``gemeinde`` custom post type. The records
    carry no usable body (the directory stub renders chrome only); they supply the
    municipality name, slug and per-municipality ``modified`` watermark."""
    records = fetch_collection(base_url, GEMEINDE_RESOURCE, fields="id,slug,link,title,date,modified")
    named = [record for record in records if record_slug(record) and record_title(record)]
    named.sort(key=record_title)
    log(f"Fetched {len(named)} municipalities from the '{GEMEINDE_RESOURCE}' post type")
    return named


def build_gemeinde_document(base_url: str, record: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Assemble one municipality's document from its subdomain (a single REST list
    request): the ``home`` hero line plus the ``gemeindeinfos`` body, which is where
    the build status, connection costs, local contact and available providers live.

    Returns None when the municipality's page is not yet filled in. A 404/410 from the
    subdomain is likewise treated as "no document" (the index mirrors the live site);
    any other failure propagates so a partial scrape cannot silently shrink the feed.
    """
    slug = record_slug(record)
    name = record_title(record)
    host = gemeinde_host(base_url, slug)
    try:
        pages = fetch_collection(host, "pages", fields="id,slug,link,title,content,modified")
    except urllib.error.HTTPError as error:
        if error.code in (404, 410):
            log(f"  {slug}: subdomain returned {error.code}; skipping")
            return None
        raise

    by_slug = {record_slug(page): page for page in pages}
    hero = record_markdown(by_slug["home"], host) if "home" in by_slug else ""
    infos_page = by_slug.get("gemeindeinfos")
    infos = record_markdown(infos_page, host) if infos_page else ""

    if len(infos) < MIN_GEMEINDE_CONTENT_CHARS:
        log(f"  {slug}: Gemeindeinfos has only {len(infos)} chars; not yet published, skipping")
        return None

    sections = [
        f"# Glasfaser in {name}",
        f"Gemeinde: {name}. Website zum Glasfaserausbau dieser Gemeinde: {host}/",
    ]
    if hero:
        sections.append(hero)
    sections.append(infos)

    return {
        "id": f"gemeinde-{slugify(slug)}",
        "title": f"{name} – Glasfaser in der Gemeinde (Gemeindeinfos)",
        "url": f"{host}/gemeindeinfos/",
        "content": "\n\n".join(sections),
        "tags": ["gemeinde", slug],
        "type": "gemeinde",
        "date": record_date(infos_page or record),
    }


def build_gemeinde_documents(base_url: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fetch every municipality's subdomain concurrently, preserving input order."""
    log(f"Fetching {len(records)} municipality subdomains ...")
    with ThreadPoolExecutor(max_workers=GEMEINDE_FETCH_WORKERS) as executor:
        results = list(executor.map(lambda record: build_gemeinde_document(base_url, record), records))
    documents = [document for document in results if document]
    log(f"Built {len(documents)} municipality documents ({len(records) - len(documents)} skipped)")
    return documents


def build_gemeinde_index_document(
    base_url: str, records: list[dict[str, Any]], documents: list[dict[str, Any]]
) -> dict[str, Any]:
    """One document listing every participating municipality and its site, so
    "which municipalities are covered?" retrieves as a single clean source."""
    published = {document["id"] for document in documents}
    lines = [
        "# Gemeinden mit einem Glasfaser-Portal auf breitband.tirol",
        (
            f"Auf breitband.tirol haben derzeit {len(records)} Tiroler Gemeinden eine eigene "
            "Glasfaser-Website. Jede Gemeinde hat eine eigene Adresse in der Form "
            "https://<gemeinde>.breitband.tirol/ mit den Infos zum Ausbaustand, zu den Kosten, "
            "zur Ansprechperson und zu den verfügbaren Providern dieser Gemeinde."
        ),
        "## Liste der Gemeinden",
    ]
    for record in records:
        slug = record_slug(record)
        name = record_title(record)
        host = gemeinde_host(base_url, slug)
        note = "" if f"gemeinde-{slugify(slug)}" in published else " (Gemeindeseite noch in Arbeit)"
        lines.append(f"- {name}: {host}/{note}")
    return {
        "id": "gemeinden-index",
        "title": "Übersicht: Gemeinden mit Glasfaser-Portal auf Breitband.Tirol",
        "url": f"{base_url}/glasfaser-gemeinden-hp/",
        "content": "\n".join(lines),
        "tags": ["gemeinde", "index"],
        "type": "site-info",
        "date": datetime.now(timezone.utc).date().isoformat(),
    }


def fetch_remote_state(base_url: str) -> dict[str, Any]:
    """Cheap change-detection watermark for breitband.tirol: the latest ``modified``
    timestamp and record count for ``pages`` and ``posts``, the per-municipality
    ``modified`` map from the ``gemeinde`` post type (which is what changes when a
    municipality's Elementor fields are edited), and a hash of the extracted
    header/footer markdown (theme chrome edits never bump a post's watermark)."""
    base_url = base_url.rstrip("/")
    state: dict[str, Any] = {}
    for resource in ("pages", "posts"):
        url = f"{base_url}/wp-json/wp/v2/{resource}?per_page=1&orderby=modified&order=desc&_fields=modified"
        payload, headers = fetch_json(url)
        latest = None
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            latest = payload[0].get("modified")
        total = headers.get("x-wp-total")
        state[resource] = {
            "count": int(total) if total and total.isdigit() else None,
            "latest_modified": latest,
        }
    gemeinde_records = fetch_collection(base_url, GEMEINDE_RESOURCE, fields="slug,modified")
    state[GEMEINDE_RESOURCE] = {
        "count": len(gemeinde_records),
        "modified": {record_slug(record): record.get("modified") for record in gemeinde_records if record_slug(record)},
    }
    chrome = extract_site_chrome(extract_body(fetch_text(base_url + "/")[0]), base_url)
    chrome_blob = json.dumps(chrome, sort_keys=True, ensure_ascii=False).encode("utf-8")
    state["chrome_hash"] = hashlib.sha256(chrome_blob).hexdigest()
    return state


def scrape(base_url: str, *, limit_gemeinden: Optional[int] = None) -> list[dict[str, Any]]:
    """Scrape the whole feed: statewide pages, the site chrome, the municipality index,
    and one document per municipality. Raises when either half is empty, so a partial
    outage can never produce a feed that would half-wipe the index on re-import."""
    base_url = base_url.rstrip("/")
    documents = build_main_documents(base_url)
    if not documents:
        raise RuntimeError(f"no page/post documents scraped from {base_url}")
    documents.append(build_chrome_document(base_url))

    records = fetch_gemeinde_records(base_url)
    if not records:
        raise RuntimeError(f"no '{GEMEINDE_RESOURCE}' records found at {base_url}")
    if limit_gemeinden is not None:
        records = records[:limit_gemeinden]
        log(f"--limit-gemeinden: restricted to {len(records)} municipalities")
    gemeinde_documents = build_gemeinde_documents(base_url, records)
    if not gemeinde_documents:
        raise RuntimeError("no municipality documents scraped; aborting rather than emitting a half feed")
    documents.append(build_gemeinde_index_document(base_url, records, gemeinde_documents))
    documents.extend(gemeinde_documents)

    seen: set[str] = set()
    for document in documents:
        if document["id"] in seen:
            raise RuntimeError(f"duplicate document id '{document['id']}'")
        seen.add(document["id"])
    return documents


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape breitband.tirol into data/bbsa.json (category 'bbsa').")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Site base URL (default: %(default)s)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output path (default: %(default)s)")
    parser.add_argument(
        "--limit-gemeinden",
        type=int,
        default=None,
        help="Only scrape the first N municipalities (for a quick smoke test)",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    documents = scrape(base_url, limit_gemeinden=args.limit_gemeinden)
    payload = {
        "feed": FEED_MARKER,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "sources": [base_url],
        "count": len(documents),
        "documents": documents,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gemeinde_count = sum(1 for document in documents if document["type"] == "gemeinde")
    log(
        f"Wrote {len(documents)} documents ({len(documents) - gemeinde_count} site pages, "
        f"{gemeinde_count} municipalities) to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
