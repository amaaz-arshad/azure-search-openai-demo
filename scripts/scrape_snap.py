#!/usr/bin/env python3
"""Scrape the snap.de website into data/snap.json for ingestion under category "snap".

snap.de is a small WordPress site (Rank Math SEO). Instead of crawling rendered
HTML, this pulls structured content from the public WordPress REST API
(``/wp-json/wp/v2/pages`` and ``/wp-json/wp/v2/posts``), which returns clean JSON
with a first-class ``link`` (live page URL) and ``content.rendered`` body — no
nav/footer/cookie-banner noise.

Tool pages are built with the Divi page builder, so ``content.rendered`` is real
prose wrapped in ``[et_pb_*]`` shortcodes and HTML entities. ``clean_html`` converts
that body to GitHub-flavored markdown: it recovers text-bearing shortcode attributes,
maps HTML headings/emphasis/links/lists/tables/images to markdown, decodes entities,
and collapses whitespace.

Output shape (consumed by ``app/backend/prepdocslib/snapjson.py``)::

    {
      "feed": "snap.de",
      "generated_at": "<ISO8601 UTC>",
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
import html
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

DEFAULT_BASE_URL = "https://www.snap.de"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "snap.json"
USER_AGENT = "snap-content-scraper/1.0 (+https://www.snap.de)"
PER_PAGE = 100
REQUEST_TIMEOUT = 30
FEED_MARKER = "snap.de"

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
    blockquotes. Drops <script>/<style>. Block structure is emitted as newlines that
    ``collapse_whitespace`` later tidies; ``suppress_leading_space`` keeps stray source
    whitespace from leaking in at the start of a line."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
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
        if tag in {"script", "style"}:
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
        if tag in {"script", "style"}:
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
            self.link_href = None
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
    """Collapse all whitespace (including newlines) in an inline fragment to single spaces."""
    return re.sub(r"\s+", " ", text or "").strip()


def collapse_whitespace(text: str) -> str:
    # Normalize spaces/tabs/NBSP within each line (preserving the leading indent that marks
    # nested markdown list items), drop trailing space, then collapse blank-line runs to one.
    text = text.replace("\xa0", " ")
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


def clean_html(raw: str, base_url: str) -> str:
    """Turn a WordPress content.rendered string into markdown, recovering text-bearing
    Divi shortcode attributes (titles, names, headlines, CTA labels) as inline text."""
    without_shortcodes = SHORTCODE_RE.sub(replace_shortcode, raw or "")
    extractor = _MarkdownExtractor(base_url)
    extractor.feed(without_shortcodes)
    extractor.close()
    return collapse_whitespace(extractor.text())


def clean_inline(raw: str) -> str:
    """Clean a short inline field such as a title (strip tags + decode entities)."""
    text = SHORTCODE_RE.sub(" ", raw or "")
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


def fetch_remote_state(base_url: str) -> dict[str, Any]:
    """Cheap change-detection watermark for snap.de — the latest ``modified`` timestamp
    and total record count for ``pages`` and ``posts`` (two tiny requests, no bodies).

    Comparing this dict across runs decides whether a full re-scrape/re-index is needed
    without downloading the whole site: the timestamp catches edits and additions, the
    count catches additions and deletions. Shape::

        {"pages": {"count": 35, "latest_modified": "2026-06-20T10:11:12"},
         "posts": {"count": 8,  "latest_modified": "2026-06-22T09:00:00"}}
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
    return state


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


def scrape(base_url: str) -> list[dict[str, Any]]:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape snap.de into data/snap.json via the WordPress REST API.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Site base URL (default: %(default)s)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output path (default: data/snap.json)")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    documents = scrape(base_url)
    if not documents:
        print("No documents scraped — aborting without writing output.", file=sys.stderr)
        return 1

    feed = {
        "feed": FEED_MARKER,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": base_url,
        "count": len(documents),
        "documents": documents,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(documents)} documents to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
