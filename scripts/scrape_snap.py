#!/usr/bin/env python3
"""Scrape the snap.de AND nerilio.ai websites into data/snap.json (category "snap").

snap.de is a small WordPress site (Rank Math SEO). Instead of crawling rendered
HTML, this pulls structured content from the public WordPress REST API
(``/wp-json/wp/v2/pages`` and ``/wp-json/wp/v2/posts``), which returns clean JSON
with a first-class ``link`` (live page URL) and ``content.rendered`` body — no
nav/footer/cookie-banner noise. Because the API returns no theme chrome, the
site-wide header/footer (nav, office addresses, phone/fax, e-mail, legal links)
is scraped separately from the rendered homepage HTML into one dedicated
"website-header-footer" document.

Tool pages are built with the Divi page builder, so ``content.rendered`` is real
prose wrapped in ``[et_pb_*]`` shortcodes and HTML entities. ``clean_html`` converts
that body to GitHub-flavored markdown: it recovers text-bearing shortcode attributes,
maps HTML headings/emphasis/links/lists/tables/images to markdown, decodes entities,
and collapses whitespace.

nerilio.ai is NOT WordPress — it is a pre-rendered static site (Apache) with a
``sitemap.xml`` listing every page (DE/EN homepage + FAQ, German-only legal pages).
``scrape_nerilio`` crawls the sitemap URLs (plus any same-site links discovered in
the HTML as a safety net), converts each page's ``<body>`` to markdown while
excluding the repeated ``<header>``/``<footer>``/``<nav>`` chrome, and emits that
chrome once as a dedicated "nerilio-website-header-footer" document (built from
the DE and EN homepages). Its cookie banner is injected by JavaScript at runtime,
so dropping ``<script>`` tags keeps the scraped text clean. All nerilio record ids
are prefixed ``nerilio-`` so they can never collide with snap.de ids.

Output shape (consumed by ``app/backend/prepdocslib/snapjson.py``) — one merged
feed for both sites, still marked ``"feed": "snap.de"`` for parser compatibility::

    {
      "feed": "snap.de",
      "generated_at": "<ISO8601 UTC>",
      "sources": ["https://www.snap.de", "https://nerilio.ai"],
      "count": <int>,
      "documents": [
        {"id", "title", "url", "content", "tags": [...], "type", "date"}
      ]
    }

The produced file is meant to be uploaded via the admin managed-file uploader
under category "snap"; it is NOT indexed by this script.

Pure standard library — no third-party dependencies. Run from the repo root::

    python scripts/scrape_snap.py
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

DEFAULT_BASE_URL = "https://www.snap.de"
NERILIO_BASE_URL = "https://nerilio.ai"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "snap.json"
USER_AGENT = "snap-content-scraper/1.0 (+https://www.snap.de)"
PER_PAGE = 100
REQUEST_TIMEOUT = 30
FEED_MARKER = "snap.de"

# Content of these tags is never readable page text.
SKIP_TAGS = frozenset({"script", "style", "noscript"})
# Site-wide chrome excluded from every rendered nerilio page body; it is captured
# once instead in the dedicated "nerilio-website-header-footer" document.
CHROME_TAGS = ("header", "footer", "nav")
# Safety cap for the nerilio link-discovery crawl (the site has < 10 real pages).
MAX_CRAWL_PAGES = 200

# WordPress shortcodes such as Divi's [et_pb_section ...] / [/et_pb_text]. Non-nested
# square-bracket tokens; the prose lives between opening and closing tags, so removing
# only the tags keeps the readable text.
SHORTCODE_RE = re.compile(r"\[/?[a-zA-Z][^\]]*\]")

# HTML → markdown mapping for the page body. Heading tags become ATX headings, emphasis
# tags wrap their text, and the remaining block tags emit paragraph breaks. Lists, links,
# images, tables, and blockquotes are handled explicitly in _MarkdownExtractor.
HEADING_TAGS = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### ", "h5": "##### ", "h6": "###### "}
INLINE_EMPHASIS = {"strong": "**", "b": "**", "em": "*", "i": "*"}
BLOCK_TAGS = {"p", "div", "section", "article", "header", "footer", "figure", "figcaption"}

# Divi stores some VISIBLE text inside shortcode ATTRIBUTES rather than between the tags:
# section/card titles, team-member names, hero headlines, and CTA button labels, e.g.
# [et_pb_blurb title=&#8220;Ulrich Zimmer&#8220;]. The delimiters are HTML-entity smart
# quotes (&#8220;), so we unescape each opening tag first, then pull a whitelist of
# text-bearing attributes and emit them AT the shortcode's position (so a name precedes
# its bio, a card title precedes its description, the hero headline lands at the top).
SHORTCODE_ATTR_WHITELIST = ("title", "subhead", "button_text", "button_one_text", "button_two_text", "heading")
_QUOTE_CHARS = "\"'“”‘’″′«»"
_SHORTCODE_ATTR_RE = re.compile(
    r"([a-zA-Z_]+)\s*=\s*[" + re.escape(_QUOTE_CHARS) + r"]([^" + re.escape(_QUOTE_CHARS) + r"]*)[" + re.escape(_QUOTE_CHARS) + r"]"
)


def extract_shortcode_attr_text(open_tag: str) -> str:
    """Pull whitelisted, human-readable attribute values out of a Divi opening shortcode."""
    unescaped = html.unescape(open_tag)
    parts: list[str] = []
    seen: set[str] = set()
    for name, value in _SHORTCODE_ATTR_RE.findall(unescaped):
        if name.lower() not in SHORTCODE_ATTR_WHITELIST:
            continue
        cleaned = value.strip()
        lowered = cleaned.lower()
        if not cleaned or cleaned in seen:
            continue
        # Skip values that are clearly not readable copy (urls, css, ids, percentages).
        if lowered.startswith(("http", "//", "#", "{", "rgba(", "rgb(", "%")) or cleaned.endswith("%"):
            continue
        seen.add(cleaned)
        parts.append(cleaned)
    return ". ".join(parts)


def replace_shortcode(match: "re.Match[str]") -> str:
    """Drop closing shortcode tags; turn opening tags into their recovered attribute text."""
    tag = match.group(0)
    if tag.startswith("[/"):
        return " "
    attr_text = extract_shortcode_attr_text(tag)
    return f" {attr_text}. " if attr_text else " "


def normalize_href(href: str, base_url: str) -> str:
    """Resolve an anchor/image URL for markdown (absolute where possible), dropping
    non-navigational targets such as ``#`` anchors and ``javascript:``/``data:`` URIs."""
    href = (href or "").strip()
    if not href:
        return ""
    lowered = href.lower()
    if href.startswith("#") or lowered.startswith(("javascript:", "data:")):
        return ""
    if lowered.startswith(("http://", "https://", "mailto:", "tel:")):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return base_url.rstrip("/") + href
    return href


class _MarkdownExtractor(HTMLParser):
    """Convert a WordPress/Divi HTML body into GitHub-flavored markdown: headings,
    bold/italic, links, ordered/unordered lists, images (with alt text), tables, and
    blockquotes. Drops <script>/<style>/<noscript> plus any caller-supplied
    ``exclude_tags`` (e.g. header/footer/nav chrome on rendered pages). Block
    structure is emitted as newlines that ``collapse_whitespace`` later tidies;
    ``suppress_leading_space`` keeps stray source whitespace from leaking in at the
    start of a line."""

    def __init__(self, base_url: str, exclude_tags: tuple[str, ...] = ()) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.skip_tags = SKIP_TAGS | {tag.lower() for tag in exclude_tags}
        self.parts: list[str] = []
        self.skip_depth = 0
        self.suppress_leading_space = True
        self.list_stack: list[dict[str, Any]] = []
        self.link_href: Optional[str] = None
        self.in_table = False
        self.table_rows: list[list[str]] = []
        self.current_row: Optional[list[str]] = None
        self.cell_parts: Optional[list[str]] = None

    def emit(self, text: str) -> None:
        # Inline output is buffered into the current table cell when inside one.
        if self.cell_parts is not None:
            self.cell_parts.append(text)
        else:
            self.parts.append(text)

    def emit_block(self, text: str) -> None:
        self.emit(text)
        self.suppress_leading_space = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in self.skip_tags:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        attr_map = {name: (value or "") for name, value in attrs}
        if tag in HEADING_TAGS:
            self.emit_block("\n\n" + HEADING_TAGS[tag])
        elif tag == "br":
            self.emit_block("  \n")
        elif tag in INLINE_EMPHASIS:
            self.emit(INLINE_EMPHASIS[tag])
        elif tag == "code":
            self.emit("`")
        elif tag == "a":
            href = normalize_href(attr_map.get("href", ""), self.base_url)
            if href:
                self.link_href = href
                self.emit("[")
            else:
                self.link_href = None
        elif tag == "img":
            alt = collapse_inline(attr_map.get("alt", ""))
            src = normalize_href(attr_map.get("src", ""), self.base_url)
            if alt and src:
                self.emit(f"![{alt}]({src})")
            elif alt:
                self.emit(alt)
        elif tag == "button":
            self.emit(" ")
        elif tag in {"ul", "ol"}:
            if not self.list_stack:
                self.emit_block("\n\n")
            self.list_stack.append({"type": tag, "n": 0})
        elif tag == "li":
            depth = max(0, len(self.list_stack) - 1)
            if self.list_stack and self.list_stack[-1]["type"] == "ol":
                self.list_stack[-1]["n"] += 1
                marker = f"{self.list_stack[-1]['n']}. "
            else:
                marker = "- "
            self.emit_block("\n" + "  " * depth + marker)
        elif tag == "table":
            self.in_table = True
            self.table_rows = []
        elif tag == "tr" and self.in_table:
            self.current_row = []
        elif tag in {"td", "th"} and self.in_table:
            self.cell_parts = []
        elif tag == "blockquote":
            self.emit_block("\n\n> ")
        elif tag in BLOCK_TAGS:
            self.emit_block("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.skip_tags:
            if self.skip_depth > 0:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in HEADING_TAGS:
            self.emit_block("\n\n")
        elif tag in INLINE_EMPHASIS:
            self.emit(INLINE_EMPHASIS[tag])
        elif tag == "code":
            self.emit("`")
        elif tag == "a":
            if self.link_href:
                self.emit(f"]({self.link_href})")
            else:
                # Linkless anchors (client-side navigation) sit flush against each other
                # in the source; separate them so labels don't concatenate ("VorteileUse Cases").
                self.emit(" ")
            self.link_href = None
        elif tag == "button":
            self.emit(" ")
        elif tag in {"ul", "ol"}:
            if self.list_stack:
                self.list_stack.pop()
            self.emit_block("\n")
        elif tag in {"td", "th"} and self.in_table:
            cell_text = collapse_inline("".join(self.cell_parts or []))
            if self.current_row is not None:
                self.current_row.append(cell_text)
            self.cell_parts = None
        elif tag == "tr" and self.in_table:
            if self.current_row is not None:
                self.table_rows.append(self.current_row)
            self.current_row = None
        elif tag == "table":
            self.flush_table()
            self.in_table = False
            self.table_rows = []
        elif tag == "blockquote":
            self.emit_block("\n\n")
        elif tag in BLOCK_TAGS:
            self.emit_block("\n\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = re.sub(r"\s+", " ", data)
        if self.cell_parts is None and self.suppress_leading_space:
            text = text.lstrip()
        if not text:
            return
        self.suppress_leading_space = False
        self.emit(text)

    def flush_table(self) -> None:
        rows = [row for row in self.table_rows if any(cell.strip() for cell in row)]
        if not rows:
            return
        ncol = max(len(row) for row in rows)

        def fmt(row: list[str]) -> str:
            padded = row + [""] * (ncol - len(row))
            return "| " + " | ".join(padded) + " |"

        # Tables are emitted directly (never inside another cell), so write to self.parts.
        self.parts.append("\n\n")
        self.parts.append(fmt(rows[0]) + "\n")
        self.parts.append("| " + " | ".join(["---"] * ncol) + " |\n")
        for row in rows[1:]:
            self.parts.append(fmt(row) + "\n")
        self.suppress_leading_space = True

    def text(self) -> str:
        return "".join(self.parts)


def collapse_inline(text: str) -> str:
    """Collapse all whitespace (including newlines) in an inline fragment to single
    spaces, dropping soft hyphens and icon-font glyphs (same cleanup as
    ``collapse_whitespace``, so a glyph-only image alt collapses to empty)."""
    text = (text or "").replace("\u00ad", "")
    text = re.sub(r"[\ue000-\uf8ff]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def collapse_whitespace(text: str) -> str:
    # Normalize spaces/tabs/NBSP within each line (preserving the leading indent that marks
    # nested markdown list items), drop trailing space, then collapse blank-line runs to one.
    # Soft hyphens (U+00AD, e.g. snap.de's "Softwareentwicklungs(shy)gesellschaft") would
    # break search-term matching, and Divi renders icons as private-use-area font glyphs
    # (U+E000-U+F8FF); drop both.
    text = text.replace("\xa0", " ").replace("\u00ad", "")
    text = re.sub(r"[\ue000-\uf8ff]", "", text)
    out: list[str] = []
    blank = False
    for raw_line in text.splitlines():
        indent = re.match(r"[ \t]*", raw_line).group(0)
        body = re.sub(r"[ \t]+", " ", raw_line[len(indent):]).rstrip()
        line = indent + body if body else ""
        if line:
            out.append(line)
            blank = False
        elif not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def clean_html(
    raw: str,
    base_url: str,
    *,
    strip_shortcodes: bool = True,
    exclude_tags: tuple[str, ...] = (),
) -> str:
    """Turn an HTML fragment into markdown. For WordPress ``content.rendered`` bodies
    (``strip_shortcodes=True``) text-bearing Divi shortcode attributes (titles, names,
    headlines, CTA labels) are recovered as inline text. Rendered-page HTML (nerilio.ai,
    the snap.de homepage chrome) is cleaned with ``strip_shortcodes=False`` so literal
    ``[bracketed]`` prose is not eaten, and ``exclude_tags`` drops site chrome such as
    header/footer/nav."""
    prepared = SHORTCODE_RE.sub(replace_shortcode, raw or "") if strip_shortcodes else (raw or "")
    extractor = _MarkdownExtractor(base_url, exclude_tags=exclude_tags)
    extractor.feed(prepared)
    extractor.close()
    markdown = collapse_whitespace(extractor.text())
    # Icon-font anchors (e.g. social links) lose their glyph-only text to PUA stripping;
    # keep the bare URL instead of an empty [](url) link. The lookbehind protects image
    # tokens ![](src) from being rewritten into a stray "!" + URL.
    return re.sub(r"(?<!!)\[\]\(([^)\s]+)\)", r"\1", markdown)


def clean_inline(raw: str, *, strip_shortcodes: bool = True) -> str:
    """Clean a short inline field such as a title (strip tags + decode entities).
    Non-WordPress sources pass ``strip_shortcodes=False`` — SHORTCODE_RE matches ANY
    ``[bracketed]`` token, which would eat literal bracketed prose."""
    text = SHORTCODE_RE.sub(" ", raw or "") if strip_shortcodes else (raw or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return collapse_whitespace(html.unescape(text)).replace("\n", " ").strip()


def slugify(value: str) -> str:
    slug = re.sub(r"[^0-9a-zA-Z]+", "-", value).strip("-").lower()
    return slug or "page"


def id_and_tags_from_url(link: str, page_type: str) -> tuple[str, list[str]]:
    path = urlparse(link).path.strip("/")
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        # Parser prepends the dataset slug ("snap"), so a bare "home" yields "snap-home".
        return "home", [page_type]
    record_id = slugify("-".join(segments))
    # Parent path segments make useful retrieval tags (e.g. tools/, news/allgemein/).
    tags = [segment for segment in segments[:-1]]
    tags.append(page_type)
    # Dedupe preserving order.
    return record_id, list(dict.fromkeys(tags))


def fetch_json(url: str) -> tuple[Any, dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310 (trusted host)
        payload = json.loads(response.read().decode("utf-8"))
        headers = {key.lower(): value for key, value in response.headers.items()}
    return payload, headers


def fetch_collection(base_url: str, resource: str) -> list[dict[str, Any]]:
    """Fetch all records of a WP REST collection (pages/posts), paginating as needed."""
    records: list[dict[str, Any]] = []
    page = 1
    while True:
        url = f"{base_url}/wp-json/wp/v2/{resource}?per_page={PER_PAGE}&page={page}&_fields=id,link,type,title,content,date,modified"
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


def fetch_head(url: str) -> dict[str, Any]:
    """HEAD a URL and return its change-detection headers. An HTTP error status is
    recorded in the state (rather than raised) so a page turning 404 counts as a
    change; network-level failures still raise and abort the check."""
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310 (trusted host)
            headers = {key.lower(): value for key, value in response.headers.items()}
            status = response.status
    except urllib.error.HTTPError as error:
        headers = {key.lower(): value for key, value in (error.headers or {}).items()}
        status = error.code
    return {
        "status": status,
        "last_modified": headers.get("last-modified"),
        "etag": headers.get("etag"),
        "content_length": headers.get("content-length"),
    }


def http_date_to_iso_date(value: Optional[str]) -> str:
    """Convert an HTTP Last-Modified header to YYYY-MM-DD (empty string if absent/invalid)."""
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return ""


def extract_body(page_html: str) -> str:
    """Slice out the <body> of a rendered page so <head> text (e.g. <title>) never
    leaks into extracted content. Falls back to the whole document if no body tag."""
    match = re.search(r"<body[^>]*>", page_html, re.IGNORECASE)
    start = match.end() if match else 0
    end = page_html.rfind("</body>")
    return page_html[start : end if end != -1 else len(page_html)]


def extract_tag_blocks(page_html: str, tag: str) -> list[str]:
    """Return the outermost ``<tag>...</tag>`` blocks (raw HTML, document order),
    tracking nesting so an inner same-name tag does not end the block early."""
    token_re = re.compile(rf"<(/?){tag}(?=[\s>/])[^>]*>", re.IGNORECASE)
    blocks: list[str] = []
    depth = 0
    start: Optional[int] = None
    for match in token_re.finditer(page_html):
        if match.group(1) != "/":
            if depth == 0:
                start = match.start()
            depth += 1
        elif depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                blocks.append(page_html[start : match.end()])
                start = None
    return blocks


def extract_site_chrome(body_html: str, base_url: str) -> dict[str, str]:
    """Extract the site-wide chrome from a rendered page body: markdown for every
    top-level <header> and <footer> block (nav links, addresses, contact data)."""
    chrome: dict[str, str] = {}
    for tag in ("header", "footer"):
        parts = [
            markdown
            for block in extract_tag_blocks(body_html, tag)
            if (markdown := clean_html(block, base_url, strip_shortcodes=False))
        ]
        if parts:
            chrome[tag] = "\n\n".join(parts)
    return chrome


def extract_html_title(page_html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", page_html, re.IGNORECASE | re.DOTALL)
    return clean_inline(match.group(1), strip_shortcodes=False) if match else ""


def is_same_site(url: str, base_url: str) -> bool:
    """True when both URLs share a host (treating an optional ``www.`` prefix as equal)."""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    base_host = urlparse(base_url).netloc.lower().removeprefix("www.")
    return bool(host) and host == base_host


def parse_sitemap_urls(sitemap_xml: str, base_url: str) -> list[str]:
    """Pull same-site page URLs out of a sitemap.xml body (order-preserving, deduped)."""
    urls: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"<loc>\s*([^<\s]+)\s*</loc>", sitemap_xml):
        url = html.unescape(match.group(1))
        if is_same_site(url, base_url) and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def extract_internal_links(page_html: str, page_url: str, base_url: str) -> list[str]:
    """Same-site links found in a rendered page (fragment-stripped, absolute, deduped).
    nerilio.ai navigates mostly client-side, so this is a safety net on top of the
    sitemap rather than the primary page discovery."""
    links: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"<a\s[^>]*href=[\"']([^\"']+)[\"']", page_html, re.IGNORECASE):
        href = html.unescape(match.group(1)).split("#")[0].strip()
        if not href:
            continue
        absolute = urljoin(page_url, href)
        if not absolute.lower().startswith(("http://", "https://")):
            continue
        if not is_same_site(absolute, base_url) or absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)
    return links


def extract_faq_pairs(page_html: str) -> list[tuple[str, str]]:
    """Question/answer pairs from schema.org FAQPage JSON-LD. nerilio.ai renders FAQ
    answers only on interaction (accordion), so the static DOM carries bare questions —
    the full answers live exclusively in the page's structured data."""
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in re.finditer(
        r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", page_html, re.DOTALL | re.IGNORECASE
    ):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if not isinstance(node, dict):
                continue
            graph = node.get("@graph") if isinstance(node.get("@graph"), list) else [node]
            for entity in graph:
                if not isinstance(entity, dict):
                    continue
                entity_type = entity.get("@type")
                if "FAQPage" not in (entity_type if isinstance(entity_type, list) else [entity_type]):
                    continue
                main_entity = entity.get("mainEntity")
                for question in main_entity if isinstance(main_entity, list) else []:
                    if not isinstance(question, dict):
                        continue
                    name = clean_inline(str(question.get("name") or ""), strip_shortcodes=False)
                    accepted = question.get("acceptedAnswer")
                    answer = (
                        clean_inline(str(accepted.get("text") or ""), strip_shortcodes=False)
                        if isinstance(accepted, dict)
                        else ""
                    )
                    if name and answer and name not in seen:
                        seen.add(name)
                        pairs.append((name, answer))
    return pairs


def nerilio_id_and_tags(link: str, page_type: str) -> tuple[str, list[str]]:
    """Site-prefixed id/tags for a nerilio.ai page so ids can never collide with
    snap.de records in the shared feed (e.g. /de/faq -> nerilio-de-faq)."""
    record_id, tags = id_and_tags_from_url(link, page_type)
    return f"nerilio-{record_id}", list(dict.fromkeys(["nerilio", *tags]))


def build_nerilio_document(page_html: str, headers: dict[str, str], final_url: str, base_url: str) -> dict[str, Any]:
    body_html = extract_body(page_html)
    content = clean_html(body_html, base_url, strip_shortcodes=False, exclude_tags=CHROME_TAGS)
    faq_pairs = extract_faq_pairs(page_html)
    if faq_pairs:
        faq_markdown = "\n\n".join(f"### {question}\n\n{answer}" for question, answer in faq_pairs)
        faq_section = f"## FAQ – Fragen & Antworten\n\n{faq_markdown}"
        content = f"{content}\n\n{faq_section}" if content else faq_section
    record_id, tags = nerilio_id_and_tags(final_url, "page")
    return {
        "id": record_id,
        "title": extract_html_title(page_html) or final_url,
        "url": final_url,
        "content": content,
        "tags": tags,
        "type": "page",
        "date": http_date_to_iso_date(headers.get("last-modified")),
    }


def compose_chrome_content(site_heading: str, sections: list[tuple[str, dict[str, str]]]) -> str:
    """Assemble the dedicated site-info document body from per-locale chrome parts."""
    lines = [f"# {site_heading}"]
    for label, chrome in sections:
        suffix = f" ({label})" if label else ""
        if chrome.get("header"):
            lines.append(f"## Header / Navigation{suffix}\n\n{chrome['header']}")
        if chrome.get("footer"):
            lines.append(f"## Footer{suffix}\n\n{chrome['footer']}")
    return "\n\n".join(lines)


def scrape_snap_site_chrome(base_url: str) -> dict[str, Any]:
    """Scrape the snap.de header/footer (nav, both office addresses, phone/fax, e-mail,
    legal links) from the rendered homepage — the WP REST API never returns theme chrome.
    Raises if nothing can be extracted, so a site redesign fails the run loudly instead
    of silently dropping the contact data from the index."""
    print(f"Fetching site header/footer from {base_url} ...", file=sys.stderr)
    page_html, _, final_url = fetch_text(base_url + "/")
    chrome = extract_site_chrome(extract_body(page_html), base_url)
    if not chrome:
        raise RuntimeError(f"could not extract header/footer chrome from {final_url}")
    return {
        "id": "website-header-footer",
        "title": "SNAP Innovation – Adresse, Kontakt & Website-Navigation (snap.de Header & Footer)",
        "url": final_url,
        "content": compose_chrome_content("snap.de – Website-Navigation, Adresse & Kontakt", [("", chrome)]),
        "tags": ["website"],
        "type": "site-info",
        "date": datetime.now(timezone.utc).date().isoformat(),
    }


def build_nerilio_chrome_document(base_url: str, locale_home_html: dict[str, str]) -> dict[str, Any]:
    """Build the dedicated nerilio.ai site-info document from the DE/EN homepage chrome.
    Raises when no chrome is extractable (same loud-failure contract as snap.de)."""
    sections: list[tuple[str, dict[str, str]]] = []
    for locale in ("de", "en"):
        page_html = locale_home_html.get(locale)
        if not page_html:
            continue
        chrome = extract_site_chrome(extract_body(page_html), base_url)
        if chrome:
            sections.append((locale.upper(), chrome))
    if not sections:
        raise RuntimeError(f"could not extract header/footer chrome from {base_url} homepages")
    return {
        "id": "nerilio-website-header-footer",
        "title": "nerilio – Kontakt & Website-Navigation (nerilio.ai Header & Footer)",
        "url": f"{base_url}/de/",
        "content": compose_chrome_content("nerilio.ai – Website-Navigation & Kontakt", sections),
        "tags": ["nerilio", "website"],
        "type": "site-info",
        "date": datetime.now(timezone.utc).date().isoformat(),
    }


def scrape_nerilio(base_url: str) -> list[dict[str, Any]]:
    """Crawl nerilio.ai (sitemap-seeded, same-site link discovery as safety net) into
    feed documents: one per page (body content without header/footer/nav chrome) plus
    one dedicated site-info document holding that chrome once.

    Failure contract: a page answering 404/410 is dropped from the feed (the index
    mirrors the live site); ANY other fetch failure (5xx, timeout, network error)
    raises so the refresh pipeline aborts before its destructive delete+reindex —
    a partial outage must never silently shrink the index."""
    base_url = base_url.rstrip("/")
    seeds = parse_sitemap_urls(fetch_text(base_url + "/sitemap.xml")[0], base_url)
    if not seeds:
        # The sitemap is the authoritative page list (navigation is client-side, so link
        # discovery finds almost nothing). Crawling on without it would produce a nearly
        # empty feed that the delete+reindex would then mirror into the index.
        raise RuntimeError(f"no usable page URLs in {base_url}/sitemap.xml; refusing to crawl blind")

    queue: list[str] = list(seeds)
    requested: set[str] = set()
    seen_final: set[str] = set()
    documents: dict[str, dict[str, Any]] = {}
    locale_home_html: dict[str, str] = {}

    while queue:
        url = queue.pop(0)
        if url in requested:
            continue
        if len(requested) >= MAX_CRAWL_PAGES:
            # The real site has < 10 pages; hitting the cap means a crawler trap or a
            # sitemap explosion. The feed would be incomplete, so fail the run rather
            # than let the delete+reindex silently drop the uncrawled pages. (Checked
            # after the dedupe skip so leftover duplicates never trip it.)
            raise RuntimeError(f"nerilio crawl hit the {MAX_CRAWL_PAGES}-page cap; refusing to emit a truncated feed")
        requested.add(url)
        print(f"Fetching {url} ...", file=sys.stderr)
        try:
            page_html, headers, final_url = fetch_text(url)
        except urllib.error.HTTPError as error:
            if error.code in (404, 410):
                # A genuinely removed page must drop out of the feed (the index mirrors
                # the live site); anything else (5xx, auth, rate limit) means the crawl
                # is incomplete and the run must fail before the destructive reindex.
                print(f"Note: {url} is gone (HTTP {error.code}); dropping it from the feed.", file=sys.stderr)
                continue
            raise RuntimeError(f"failed to fetch {url} (HTTP {error.code})") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"failed to fetch {url} ({error.reason})") from error
        if not is_same_site(final_url, base_url):
            # An off-site redirect means the content no longer lives on this site; index
            # nothing from the third-party target (its page would otherwise be injected
            # into the feed under a nerilio id with a foreign citation URL).
            print(f"Note: {url} redirected off-site to {final_url}; dropping it from the feed.", file=sys.stderr)
            continue
        if "text/html" not in (headers.get("content-type") or ""):
            continue
        if final_url in seen_final:
            continue
        seen_final.add(final_url)

        path = urlparse(final_url).path.rstrip("/")
        if path in ("/de", "/en"):
            locale_home_html[path.lstrip("/")] = page_html

        document = build_nerilio_document(page_html, headers, final_url, base_url)
        if document["id"] in documents:
            print(f"Warning: duplicate nerilio id '{document['id']}' for {final_url}; keeping first.", file=sys.stderr)
        else:
            documents[document["id"]] = document

        for link in extract_internal_links(page_html, final_url, base_url):
            if link not in requested:
                queue.append(link)

    chrome_document = build_nerilio_chrome_document(base_url, locale_home_html)
    documents[chrome_document["id"]] = chrome_document
    return sorted(documents.values(), key=lambda document: document["url"])


def fetch_snap_remote_state(base_url: str) -> dict[str, Any]:
    """Change-detection watermark for snap.de — the latest ``modified`` timestamp and
    total record count for ``pages`` and ``posts`` (two tiny requests, no bodies), plus
    a hash of the extracted homepage header/footer markdown (theme chrome edits never
    bump the pages/posts watermark). Shape::

        {"pages": {"count": 35, "latest_modified": "2026-06-20T10:11:12"},
         "posts": {"count": 8,  "latest_modified": "2026-06-22T09:00:00"},
         "chrome_hash": "<sha256 of extracted header/footer markdown>"}
    """
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
    chrome = extract_site_chrome(extract_body(fetch_text(base_url + "/")[0]), base_url)
    chrome_blob = json.dumps(chrome, sort_keys=True, ensure_ascii=False).encode("utf-8")
    state["chrome_hash"] = hashlib.sha256(chrome_blob).hexdigest()
    return state


def fetch_nerilio_remote_state(base_url: str) -> dict[str, Any]:
    """Change-detection watermark for nerilio.ai — sitemap + per-page HEAD headers
    (Last-Modified/ETag/Content-Length from Apache static files, no bodies). The
    timestamp/etag catches edits, the sitemap URL set catches added/removed pages."""
    base_url = base_url.rstrip("/")
    sitemap_url = base_url + "/sitemap.xml"
    urls = parse_sitemap_urls(fetch_text(sitemap_url)[0], base_url)
    return {
        "sitemap": fetch_head(sitemap_url),
        "pages": {url: fetch_head(url) for url in urls},
    }


def fetch_remote_state(base_url: str, nerilio_base_url: str = NERILIO_BASE_URL) -> dict[str, Any]:
    """Combined change-detection watermark for both scraped sites. A difference in
    either sub-dict means the feed must be re-scraped and re-indexed."""
    return {
        "snap": fetch_snap_remote_state(base_url),
        "nerilio": fetch_nerilio_remote_state(nerilio_base_url),
    }


def build_document(record: dict[str, Any], base_url: str) -> Optional[dict[str, Any]]:
    link = str(record.get("link") or "").strip()
    if not link:
        return None
    page_type = str(record.get("type") or "page").strip() or "page"
    title = clean_inline(str((record.get("title") or {}).get("rendered", "")))
    content = clean_html(str((record.get("content") or {}).get("rendered", "")), base_url)
    record_id, tags = id_and_tags_from_url(link, page_type)
    date_value = str(record.get("modified") or record.get("date") or "")[:10]
    return {
        "id": record_id,
        "title": title or link,
        "url": link,
        "content": content,
        "tags": tags,
        "type": page_type,
        "date": date_value,
    }


def scrape_snap_wp(base_url: str) -> list[dict[str, Any]]:
    """Scrape all snap.de pages/posts (body content) via the WordPress REST API."""
    documents: dict[str, dict[str, Any]] = {}
    empty: list[str] = []
    for resource in ("pages", "posts"):
        print(f"Fetching {resource} from {base_url} ...", file=sys.stderr)
        for record in fetch_collection(base_url, resource):
            document = build_document(record, base_url)
            if document is None:
                continue
            if not document["content"]:
                empty.append(document["url"])
            # Last write wins on id collisions (rare); keep deterministic order by url.
            documents[document["id"]] = document
    if empty:
        print(f"Warning: {len(empty)} page(s) had empty content after cleaning:", file=sys.stderr)
        for url in empty:
            print(f"  - {url}", file=sys.stderr)
    return sorted(documents.values(), key=lambda document: document["url"])


def merge_documents(*document_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge per-site document lists into one feed, failing hard on id collisions
    (duplicate ids would be rejected by the snap parser at index time anyway)."""
    merged: dict[str, dict[str, Any]] = {}
    for documents in document_lists:
        for document in documents:
            if document["id"] in merged:
                raise RuntimeError(f"duplicate feed document id '{document['id']}' ({document['url']})")
            merged[document["id"]] = document
    return sorted(merged.values(), key=lambda document: document["url"])


def scrape(base_url: str, nerilio_base_url: str = NERILIO_BASE_URL) -> list[dict[str, Any]]:
    """Scrape both sites into one feed document list. Each site must yield content
    (body documents AND the chrome doc) or the whole scrape fails, so a partial
    outage can never silently shrink the index."""
    snap_documents = scrape_snap_wp(base_url)
    if not snap_documents:
        raise RuntimeError(f"no documents scraped from {base_url}")
    snap_chrome = scrape_snap_site_chrome(base_url)

    nerilio_documents = scrape_nerilio(nerilio_base_url)
    # scrape_nerilio always appends the chrome doc; require at least one real page too.
    if len(nerilio_documents) < 2:
        raise RuntimeError(f"no page documents scraped from {nerilio_base_url}")

    print(
        f"Scraped {len(snap_documents) + 1} snap.de and {len(nerilio_documents)} nerilio.ai documents.",
        file=sys.stderr,
    )
    return merge_documents(snap_documents, [snap_chrome], nerilio_documents)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape snap.de (WordPress REST API + rendered header/footer) and nerilio.ai "
        "(sitemap crawl) into data/snap.json."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="snap.de base URL (default: %(default)s)")
    parser.add_argument(
        "--nerilio-base-url", default=NERILIO_BASE_URL, help="nerilio.ai base URL (default: %(default)s)"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output path (default: data/snap.json)")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    nerilio_base_url = args.nerilio_base_url.rstrip("/")
    try:
        documents = scrape(base_url, nerilio_base_url)
    except (RuntimeError, urllib.error.URLError) as error:
        # URLError covers HTTPError too (sitemap/WP-API fetch failures raise directly).
        print(f"Scrape failed: {error} — aborting without writing output.", file=sys.stderr)
        return 1

    feed = {
        "feed": FEED_MARKER,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": [base_url, nerilio_base_url],
        "count": len(documents),
        "documents": documents,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(documents)} documents to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
