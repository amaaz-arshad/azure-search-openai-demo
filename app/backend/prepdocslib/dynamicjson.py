"""Record-oriented JSON parser for provisioned ("generic") chatbot knowledge bases.

A provisioned bot's files are dropped into the dedicated ``content2`` container as
``content2/<bot_name>/<file>`` and auto-indexed in place by the content2 dynamic indexer
(``AutoBlobIndexer`` with ``force_generic_parsing=True``). For ``.json`` that used to mean
``JsonParser``, which is wrong in three compounding ways for the record collections the nerilio
side actually drops there:

  * it re-serialises each record with ``json.dumps``, so the indexed ``content`` was raw JSON
    syntax carrying literal backslash-u escapes instead of readable prose - which made German
    umlauts unsearchable and showed the model JSON punctuation as if it were source text;
  * the sentence splitter then ran over the *whole file*, so one chunk spanned several records
    (mixing unrelated pages) and cut mid-word at both ends;
  * ``title``/``url``/``tags`` were never populated, so a citation could only ever point at the
    JSON blob itself even when the record carried the live page URL.

Unlike ``fhgjson``/``snapjson``/``bbsajson`` - which each serve one known first-party feed and may
raise on anything unexpected - the files here come from whatever tooling a customer's knowledge
base was exported with. So this parser is deliberately **shape-tolerant**: field names resolve
through alias sets, every unmapped scalar is preserved as a metadata line so nothing is silently
dropped, and an unrecognised payload returns ``None`` to fall back to the generic parser rather
than failing the ingest for that bot.

Three invariants worth keeping:

  * **A chunk never spans two records.** Each record is split on its own, so a retrieved chunk
    always belongs to exactly one page/document and its citation is truthful.
  * **``url`` is only ever set to an absolute http(s) URL.** The frontend decides per citation
    whether to render an external link purely from that ``http``/``https`` prefix
    (``answerParsing.ts`` ``isWebCitation``), so a non-URL value here would produce a citation
    string that is neither a working link nor a resolvable file path.
  * **``sourcepage`` is always the source filename**, never a record id. When a record has no URL
    the citation IS the sourcepage, and the frontend resolves it as ``/content2/<bot>/<sourcepage>``
    - which only exists as a blob for the file itself.
"""

import itertools
import json
import logging
import math
import os
import re
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .hyroxjson import (
    DEFAULT_MAX_CHUNK_TOKENS,
    dedupe_preserve_order,
    sanitize_identifier,
    split_content_exact,
)
from .listfilestrategy import File
from .page import Chunk
from .searchmanager import Section

logger = logging.getLogger("scripts")

# --- field aliases -----------------------------------------------------------------------------
# Resolved case-insensitively, first non-empty match wins. Ordered most- to least-specific so a
# record carrying both `content` and `body` uses `content`.
CONTENT_FIELD_ALIASES = (
    "content",
    "text",
    "body",
    "markdown",
    "md",
    "page_content",
    "plain_text",
    "article",
    "answer",
    "value",
)
TITLE_FIELD_ALIASES = (
    "title",
    "page_title",
    "heading",
    "headline",
    "name",
    "subject",
    "question",
    "label",
)
# `source`/`uri` are included but, like every alias here, only accepted when the value is an
# absolute http(s) URL - `source` in particular is often a plain feed name rather than a link.
URL_FIELD_ALIASES = (
    "url",
    "link",
    "href",
    "permalink",
    "canonical_url",
    "page_url",
    "source_url",
    "uri",
    "source",
)
ID_FIELD_ALIASES = (
    "id",
    "doc_id",
    "document_id",
    "_id",
    "uuid",
    "guid",
    "slug",
    "identifier",
    "key",
)
TAG_FIELD_ALIASES = ("tags", "keywords", "topics", "labels", "categories", "category")

# Nested containers that are also searched for title/url/id/tags (never for content, which must be
# top-level). `metadata` is the shape the FHG export uses, so it is the likeliest to recur.
METADATA_CONTAINER_KEYS = ("metadata", "meta", "fields", "properties", "attributes")

# Wrapper keys whose value may hold the record array. A dict with exactly one list-of-dicts value
# is also accepted regardless of its key name, which covers wrappers not listed here.
RECORD_ARRAY_KEYS = (
    "documents",
    "records",
    "items",
    "pages",
    "entries",
    "results",
    "chunks",
    "docs",
    "data",
)

# Fields consumed into first-class Section attributes; excluded from the metadata lines so they are
# not rendered twice.
RESERVED_FIELD_NAMES = frozenset(
    name.lower()
    for group in (CONTENT_FIELD_ALIASES, TITLE_FIELD_ALIASES, URL_FIELD_ALIASES, ID_FIELD_ALIASES, TAG_FIELD_ALIASES)
    for name in group
)

# A derived title is only trusted when the boilerplate it was cut at starts within this many
# characters - further in and the match is probably a footer, not the page's nav chrome.
MAX_DERIVED_TITLE_CHARS = 200
# Leading-text fallback when no shared boilerplate is detectable.
FALLBACK_TITLE_CHARS = 110
# Boilerplate detection (see build_boilerplate_index). A word n-gram that opens this many of the
# file's records is navigation chrome, not prose. The fraction is deliberately low so a site served
# in two languages still has each language's nav recognised - an English nav shared by 2% of the
# pages is still nav. The floor of 2 is what makes a two-record file work at all.
BOILERPLATE_NGRAM_WORDS = 6
BOILERPLATE_MIN_DOC_FRACTION = 0.02
BOILERPLATE_MIN_DOC_COUNT = 2
# Words of each record indexed when building the n-gram frequencies. Must comfortably exceed the
# longest plausible title so a record's nav n-grams are indexed even when its title is long.
BOILERPLATE_INDEX_WORDS = 160
# How far into a record the nav start is looked for. A page title beyond this is not a title.
TITLE_SCAN_WORDS = 40
# Minimum ratio between the document frequency at the nav start and the position before it. Four is
# comfortably below the rises actually observed (33x to 350x) and comfortably above the noise from a
# phrase that merely recurs in prose.
BOILERPLATE_RISE_FACTOR = 4
# Record slug length cap: the positional index already guarantees id uniqueness, so the slug only
# needs to stay human-readable.
MAX_RECORD_SLUG_CHARS = 48

HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
PAGE_EXTENSION_RE = re.compile(r"\.(html?|php|aspx?|cfm|jsp)$", re.IGNORECASE)
# Entry-point basenames that identify a CMS rather than a page, so they make a useless label.
GENERIC_PATH_SEGMENTS = frozenset(
    {"page", "index", "default", "home", "main", "view", "show", "detail", "details", "node", "id"}
)

# Character classes are built from explicit codepoints rather than written as literal characters or
# backslash escapes: the source then contains no invisible glyph that a later edit could silently
# mangle, and a reader can see exactly which codepoints are covered.
#
# Soft hyphen and the zero-width family are dropped outright. German government pages
# (bsi.bund.de) hyphenate every heading with U+00AD, which indexes "Gebaerdensprache" as
# "Ge<shy>bae<shy>rden<shy>spra<shy>che" and matches no query a user would ever type.
INVISIBLE_CODEPOINTS = (0x00AD, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF)
# Unicode spaces (NBSP, narrow NBSP, figure/en/em spaces, ideographic space) become a plain space so
# token boundaries are the ones the search analyzer expects.
UNICODE_SPACE_CODEPOINTS = (
    0x00A0,
    0x1680,
    0x2000,
    0x2001,
    0x2002,
    0x2003,
    0x2004,
    0x2005,
    0x2006,
    0x2007,
    0x2008,
    0x2009,
    0x200A,
    0x202F,
    0x205F,
    0x3000,
)
# C0/C1 controls except tab (0x09) and newline (0x0A), which carry real structure.
CONTROL_CODEPOINTS = tuple(range(0x00, 0x09)) + (0x0B, 0x0C) + tuple(range(0x0E, 0x20)) + (0x7F,)

TEXT_TRANSLATION_TABLE: dict[int, Optional[str]] = {
    **{codepoint: None for codepoint in INVISIBLE_CODEPOINTS},
    **{codepoint: None for codepoint in CONTROL_CODEPOINTS},
    **{codepoint: " " for codepoint in UNICODE_SPACE_CODEPOINTS},
}

# Punctuation stripped from the ends of a derived title: whitespace, hyphen/en/em dash, pipe, colon,
# middle dot, bullet, angle bracket, guillemets, quote, apostrophe.
TITLE_TRIM_CODEPOINTS = (
    0x20,
    0x09,
    0x0A,
    0x0D,
    0x2D,
    0x2013,
    0x2014,
    0x7C,
    0x3A,
    0x00B7,
    0x2022,
    0x3E,
    0x00AB,
    0x00BB,
    0x22,
    0x27,
)
TITLE_TRIM_CHARS = "".join(chr(codepoint) for codepoint in TITLE_TRIM_CODEPOINTS)


@dataclass(frozen=True)
class DynamicJsonPreparedDocument:
    id: str
    content: str
    category: str
    sourcepage: str
    sourcefile: str
    title: str
    url: Optional[str]
    tags: list[str]


@dataclass(frozen=True)
class DynamicJsonPreparedDataset:
    documents: list[DynamicJsonPreparedDocument]


def load_dynamic_json_payload(file: File) -> Any:
    """Read the file as JSON, tolerating a UTF-8 BOM.

    ``hyroxjson.load_json_payload`` decodes strict UTF-8; several of the live content2 exports are
    written by Windows tooling that prepends a BOM, and falling back to the generic parser for that
    alone would be a silent quality loss.
    """
    file.content.seek(0)
    raw_content = file.content.read()
    file.content.seek(0)
    if isinstance(raw_content, bytes):
        return json.loads(raw_content.decode("utf-8-sig"))
    return json.loads(raw_content.lstrip(chr(0xFEFF)))


def normalize_record_text(value: str) -> str:
    """Make scraped/exported text searchable without changing its wording.

    Only invisible and whitespace characters are touched: nothing is transliterated, no markup is
    stripped and no words are removed, so the indexed prose still says exactly what the source said
    - it is merely tokenizable.
    """
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = text.translate(TEXT_TRANSLATION_TABLE)
    text = re.sub(r"[^\S\n]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def estimate_tokens(text: str) -> int:
    """Cheap upper-bound token estimate for header budgeting (avoids a tiktoken call per record)."""
    return len(text) // 3 + 1


def lowercase_key_map(record: dict[str, Any]) -> dict[str, Any]:
    """Map lowercased key -> value. First occurrence wins on a case-only collision."""
    mapping: dict[str, Any] = {}
    for key, value in record.items():
        if not isinstance(key, str):
            continue
        lowered = key.strip().lower()
        if lowered not in mapping:
            mapping[lowered] = value
    return mapping


def scalar_to_text(value: Any) -> str:
    if isinstance(value, str):
        return normalize_record_text(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def pick_text_field(keyed: dict[str, Any], aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        text = scalar_to_text(keyed.get(alias))
        if text:
            return text
    return ""


def pick_text_field_deep(record: dict[str, Any], aliases: tuple[str, ...]) -> str:
    """Look for an aliased field on the record, then one level into a metadata-style container."""
    keyed = lowercase_key_map(record)
    text = pick_text_field(keyed, aliases)
    if text:
        return text
    for container_key in METADATA_CONTAINER_KEYS:
        container = keyed.get(container_key)
        if isinstance(container, dict):
            text = pick_text_field(lowercase_key_map(container), aliases)
            if text:
                return text
    return ""


def coerce_tags(value: Any) -> list[str]:
    """Accept a list of scalars, or a delimited string, as a tag list."""
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,;|]", value) if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [text for text in (scalar_to_text(item) for item in value) if text]
    text = scalar_to_text(value)
    return [text] if text else []


def collect_tags(record: dict[str, Any]) -> list[str]:
    keyed = lowercase_key_map(record)
    tags: list[str] = []
    for alias in TAG_FIELD_ALIASES:
        if alias in keyed:
            tags.extend(coerce_tags(keyed[alias]))
    for container_key in METADATA_CONTAINER_KEYS:
        container = keyed.get(container_key)
        if isinstance(container, dict):
            container_keyed = lowercase_key_map(container)
            for alias in TAG_FIELD_ALIASES:
                if alias in container_keyed:
                    tags.extend(coerce_tags(container_keyed[alias]))
    return dedupe_preserve_order(tags)


def resolve_url(record: dict[str, Any]) -> Optional[str]:
    """Return the record's absolute http(s) URL, or ``None``.

    Anything that is not an absolute http(s) URL is rejected rather than stored: the citation layer
    reads a ``url`` as "link to this externally", so a relative path or a bare hostname there would
    render as a dead link.
    """
    candidate = pick_text_field_deep(record, URL_FIELD_ALIASES)
    if candidate and HTTP_URL_RE.match(candidate):
        return candidate.strip()
    return None


@dataclass(frozen=True)
class BoilerplateIndex:
    """How often each opening word n-gram occurs across the records of one file."""

    document_frequency: Counter
    threshold: int


def head_word_matches(content: str, limit: int) -> list[re.Match]:
    return list(itertools.islice(re.finditer(r"\S+", content), limit))


def build_boilerplate_index(contents: list[str]) -> Optional[BoilerplateIndex]:
    """Learn which word n-grams are navigation chrome rather than page content.

    Scraped-page records begin with the HTML ``<title>`` text and run straight into the site's
    navigation, which is identical on every page of that site. So an n-gram that opens many records
    is nav, and an n-gram that opens one is that page's own title - which makes the boundary between
    them findable per record without knowing anything about the site.

    This is document-frequency based rather than a longest-common-substring reduction because a site
    served in two languages has two different navs: intersecting all records collapses to a short,
    useless fragment, whereas counting keeps both navs above the threshold. Returns ``None`` when
    there are too few records to learn anything, in which case callers fall back to other signals.
    """
    document_frequency: Counter = Counter()
    counted_records = 0
    for content in contents:
        words = [match.group(0) for match in head_word_matches(content, BOILERPLATE_INDEX_WORDS)]
        if len(words) < BOILERPLATE_NGRAM_WORDS:
            continue
        counted_records += 1
        # Counted once per record: a nav block that repeats inside one page must not inflate its own
        # document frequency.
        for gram in {
            " ".join(words[index : index + BOILERPLATE_NGRAM_WORDS]).lower()
            for index in range(len(words) - BOILERPLATE_NGRAM_WORDS + 1)
        }:
            document_frequency[gram] += 1

    if counted_records < 2:
        return None
    threshold = max(BOILERPLATE_MIN_DOC_COUNT, math.ceil(counted_records * BOILERPLATE_MIN_DOC_FRACTION))
    return BoilerplateIndex(document_frequency=document_frequency, threshold=threshold)


def title_before_boilerplate(content: str, index: Optional[BoilerplateIndex]) -> str:
    """Return the text before the record's navigation block, or "" if it cannot be located.

    The cut is made at the *most* widely shared n-gram in the record's head, not the first one above
    the threshold. That single choice is what makes this reliable on real sites:

      * A page title that several pages share (a CMS listing template titled "Beitraege | fh
        gesundheit" on hundreds of URLs) is itself above the threshold, so cutting at the first
        match would cut at position 0 and throw the title away. The site-wide nav that follows is
        shared by *more* records still, so the most-shared n-gram is the nav.
      * A phrase that genuinely recurs in prose ("bei Erhebung von personenbezogenen Daten bei",
        shared by two of 25 legal pages) is above a small file's threshold but far below the nav, so
        the title is no longer truncated at it.

    An empty result means the record opens with the site-wide nav and so has no title of its own,
    or no nav was found at all; the caller falls through to its next signal either way.
    """
    if index is None:
        return ""
    matches = head_word_matches(content, TITLE_SCAN_WORDS + BOILERPLATE_NGRAM_WORDS)
    if len(matches) < BOILERPLATE_NGRAM_WORDS:
        return ""
    words = [match.group(0) for match in matches]
    scan_limit = min(TITLE_SCAN_WORDS, len(words) - BOILERPLATE_NGRAM_WORDS + 1)

    frequencies = [
        index.document_frequency.get(" ".join(words[position : position + BOILERPLATE_NGRAM_WORDS]).lower(), 0)
        for position in range(scan_limit)
    ]

    # Cut at the earliest sharp *rise* in document frequency, not simply at the first n-gram above
    # the threshold. Measured profiles across the live files are step functions: a title plateau of
    # 1-2 followed by a nav plateau of hundreds, e.g. [1, 1, 2, 357, 366, 413, ...]. Keying on the
    # rise is what makes the three awkward cases work:
    #   * a title shared by many pages sits on its own low-but-above-threshold plateau (a CMS
    #     listing template on ~90 URLs reads [91, 91, ..., 90, 463, ...]) - "first above threshold"
    #     would cut at word 0 and lose the title, while the rise still lands on the nav;
    #   * a phrase that recurs in prose lifts one position slightly and never clears the factor;
    #   * a site served in two languages has a lower per-language nav plateau followed by a higher
    #     language-independent one, and taking the *earliest* qualifying rise stops at the former
    #     rather than swallowing a whole nav.
    for position in range(1, scan_limit):
        if frequencies[position] < index.threshold:
            continue
        if frequencies[position] < BOILERPLATE_RISE_FACTOR * frequencies[position - 1]:
            continue
        candidate = content[: matches[position].start()].strip(TITLE_TRIM_CHARS)
        return candidate if candidate and len(candidate) <= MAX_DERIVED_TITLE_CHARS else ""

    return ""


def title_from_leading_text(content: str) -> str:
    """Best-effort title from the start of the body when nothing better exists."""
    head = content[: FALLBACK_TITLE_CHARS * 2].strip()
    if not head:
        return ""
    first_line = head.split("\n", 1)[0].strip()
    if first_line and len(first_line) <= FALLBACK_TITLE_CHARS:
        return first_line.strip(TITLE_TRIM_CHARS)
    truncated = first_line[:FALLBACK_TITLE_CHARS]
    cut = truncated.rfind(" ")
    if cut > FALLBACK_TITLE_CHARS // 3:
        truncated = truncated[:cut]
    return truncated.strip(TITLE_TRIM_CHARS)


def humanize_slug(slug: str) -> str:
    # Whitespace is a separator too: a query value can hold a path ("vpath=beitraege/details"), which
    # the caller turns into a space, and every word of it should be capitalised.
    words = [word for word in re.split(r"[-_+.\s]+", slug) if word]
    return " ".join(word if word.isupper() else word.capitalize() for word in words)


def title_from_url(url: str) -> str:
    """Readable label from a URL's last meaningful path segment, else its query, else its host.

    A generic CMS entry point carries no meaning ("page.cfm" would otherwise label every one of the
    several hundred `page.cfm?vpath=...` records "Page"), so those fall through to the query string,
    which is where such a site actually identifies the page.
    """
    without_scheme = HTTP_URL_RE.sub("", url)
    host = without_scheme.split("/", 1)[0]
    path_and_query = without_scheme.split("#", 1)[0]
    path = path_and_query.split("?", 1)[0].strip("/")
    query = path_and_query.split("?", 1)[1] if "?" in path_and_query else ""

    if "/" in path:
        segment = PAGE_EXTENSION_RE.sub("", path.rsplit("/", 1)[1])
        if segment.lower() not in GENERIC_PATH_SEGMENTS and not segment.isdigit():
            label = humanize_slug(segment)
            if label:
                return label

    if query:
        # Longest value wins: on a `?vpath=beitraege/details&genericpageid=12925` style URL the
        # descriptive parameter is the long one, and which key holds it varies per CMS.
        values: list[str] = [value for _, _, value in (part.partition("=") for part in query.split("&")) if value]
        if values:
            longest_value: str = max(values, key=lambda candidate: len(candidate))
            label = humanize_slug(longest_value.replace("/", " "))
            if label:
                return label

    return host


def derive_title(
    *,
    explicit_title: str,
    content: str,
    url: Optional[str],
    boilerplate_index: Optional[BoilerplateIndex],
    fallback: str,
) -> str:
    """Resolve the citation label for one record.

    Priority: an explicit title field, then the page title carved out of the body, then the URL's
    path slug, then the leading body text, then the source filename. A raw URL is never the label
    when a slug can be built from it - a citation pill showing a full URL is exactly what deriving
    a title is meant to avoid.
    """
    if explicit_title:
        return explicit_title

    candidate = title_before_boilerplate(content, boilerplate_index)
    if candidate:
        return candidate

    if url:
        candidate = title_from_url(url)
        if candidate:
            return candidate

    candidate = title_from_leading_text(content)
    if candidate:
        return candidate

    return url or fallback


def build_metadata_lines(
    record: dict[str, Any],
    *,
    title: str,
    url: Optional[str],
    tags: list[str],
) -> list[str]:
    """Header prefixed to every chunk of a record.

    Chunks 2..N of a long page would otherwise carry no indication of which page they came from,
    which hurts both retrieval and the model's ability to attribute an answer. Unmapped scalar
    fields are rendered here too, so a field this parser does not understand is still searchable
    rather than dropped.
    """
    lines: list[str] = []
    if title:
        lines.append(f"title: {title}")
    if url:
        lines.append(f"url: {url}")
    if tags:
        lines.append(f"tags: {', '.join(tags)}")

    for key, value in record.items():
        if not isinstance(key, str):
            continue
        if key.strip().lower() in RESERVED_FIELD_NAMES:
            continue
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                if not isinstance(nested_key, str):
                    continue
                if nested_key.strip().lower() in RESERVED_FIELD_NAMES:
                    continue
                nested_text = scalar_to_text(nested_value)
                if nested_text:
                    lines.append(f"{key}.{nested_key}: {nested_text}")
            continue
        if isinstance(value, (list, tuple, set)):
            joined = ", ".join(text for text in (scalar_to_text(item) for item in value) if text)
            if joined:
                lines.append(f"{key}: {joined}")
            continue
        text = scalar_to_text(value)
        if text:
            lines.append(f"{key}: {text}")

    return lines


def extract_records(payload: Any) -> Optional[list[tuple[Optional[str], dict[str, Any]]]]:
    """Normalise a payload into ``(explicit key, record)`` pairs, or ``None`` if it is not one.

    Recognised shapes: a top-level array of objects; a wrapper object holding the array under a
    known key (or under its only list-of-dicts key); a mapping of id -> object; and a single object
    that is itself one record.
    """
    if isinstance(payload, list):
        return [(None, item) for item in payload if isinstance(item, dict)] or None

    if not isinstance(payload, dict):
        return None

    keyed = lowercase_key_map(payload)
    for array_key in RECORD_ARRAY_KEYS:
        value = keyed.get(array_key)
        if isinstance(value, list):
            records = [(None, item) for item in value if isinstance(item, dict)]
            if records:
                return records

    # A wrapper whose key name we do not know, but which has exactly one list-of-dicts value.
    list_values = [
        value for value in payload.values() if isinstance(value, list) and any(isinstance(item, dict) for item in value)
    ]
    if len(list_values) == 1:
        records = [(None, item) for item in list_values[0] if isinstance(item, dict)]
        if records:
            return records

    # A single object that is itself the record. Checked before the id -> record mapping so a record
    # whose own fields happen to be objects is not mistaken for a collection.
    if pick_text_field_deep(payload, CONTENT_FIELD_ALIASES):
        return [(None, payload)]

    # A mapping of identifier -> record (every value is an object).
    if payload and all(isinstance(value, dict) for value in payload.values()):
        return [(str(key), value) for key, value in payload.items() if isinstance(value, dict)]

    return None


def looks_like_record_collection(records: list[tuple[Optional[str], dict[str, Any]]]) -> bool:
    """At least one record must carry body text, or this is not a knowledge-base payload."""
    return any(pick_text_field_deep(record, CONTENT_FIELD_ALIASES) for _, record in records)


def prepare_dynamic_json_dataset(
    payload: Any,
    *,
    dataset_filename: str,
    category: str,
    max_chunk_tokens: int = DEFAULT_MAX_CHUNK_TOKENS,
) -> Optional[DynamicJsonPreparedDataset]:
    records = extract_records(payload)
    if not records or not looks_like_record_collection(records):
        return None

    sourcefile = os.path.basename(dataset_filename)
    dataset_slug = sanitize_identifier(Path(sourcefile).stem)
    contents = [pick_text_field_deep(record, CONTENT_FIELD_ALIASES) for _, record in records]
    boilerplate_index = build_boilerplate_index(contents)

    prepared_documents: list[DynamicJsonPreparedDocument] = []
    for record_index, ((explicit_key, record), content) in enumerate(zip(records, contents)):
        if not content:
            # A record with no body text has nothing to retrieve. Indexing it would emit a
            # header-only document, and an empty embedding input is a 400 from the embeddings API -
            # which is not a RateLimitError, so it is not retried, and it would be raised *after*
            # the indexer already deleted the file's existing documents.
            logger.info("Skipping record %d of '%s': no content", record_index, sourcefile)
            continue
        url = resolve_url(record)
        tags = collect_tags(record)
        title = derive_title(
            explicit_title=pick_text_field_deep(record, TITLE_FIELD_ALIASES),
            content=content,
            url=url,
            boilerplate_index=boilerplate_index,
            fallback=sourcefile,
        )
        record_identifier = explicit_key or pick_text_field_deep(record, ID_FIELD_ALIASES) or url or title
        record_slug = sanitize_identifier(record_identifier)[:MAX_RECORD_SLUG_CHARS].strip("-") or "record"

        metadata_lines = build_metadata_lines(record, title=title, url=url, tags=tags)
        header = "\n".join(metadata_lines)
        # The header repeats on every chunk, so it is charged against the chunk budget to keep each
        # indexed document inside the embedding model's window.
        body_budget = max(max_chunk_tokens // 4, max_chunk_tokens - estimate_tokens(header) - 8)

        for chunk_index, chunk_text in enumerate(split_content_exact(content, max_chunk_tokens=body_budget), start=1):
            rendered = "\n".join([*metadata_lines, "", "content:", chunk_text]) if metadata_lines else chunk_text
            prepared_documents.append(
                DynamicJsonPreparedDocument(
                    # The positional index is what guarantees uniqueness: two records can share a
                    # slug (e.g. "https://example.de/" and "https://example.de" normalise to the
                    # same one), and a collision would make them overwrite each other.
                    id=f"{dataset_slug}-{record_index:04d}-{record_slug}-chunk-{chunk_index:03d}",
                    content=rendered,
                    category=category,
                    sourcepage=sourcefile,
                    sourcefile=sourcefile,
                    title=title,
                    url=url,
                    tags=tags,
                )
            )

    # None, never an empty dataset: `parse_file` treats a returned `[]` as "this parser handled the
    # file", and the content2 indexer deletes a file's existing documents *before* writing the new
    # ones - so an empty result would silently drop the whole file from the index instead of falling
    # back to the generic parser.
    return DynamicJsonPreparedDataset(documents=prepared_documents) if prepared_documents else None


def prepared_document_to_section(document: DynamicJsonPreparedDocument, file: File, page_num: int) -> Section:
    return Section(
        chunk=Chunk(page_num=page_num, text=document.content),
        content=file,
        category=document.category,
        id=document.id,
        sourcepage=document.sourcepage,
        sourcefile=document.sourcefile,
        title=document.title,
        url=document.url,
        tags=document.tags,
    )


def prepare_dynamic_json_sections(
    payload: Any,
    *,
    file: File,
    category: str,
    max_chunk_tokens: int = DEFAULT_MAX_CHUNK_TOKENS,
) -> Optional[list[Section]]:
    dataset = prepare_dynamic_json_dataset(
        payload,
        dataset_filename=file.filename(),
        category=category,
        max_chunk_tokens=max_chunk_tokens,
    )
    if dataset is None:
        return None
    return [
        prepared_document_to_section(document, file, page_num=index) for index, document in enumerate(dataset.documents)
    ]


async def build_dynamic_json_sections_if_applicable(
    *,
    file: File,
    category: Optional[str],
    check_cancel: Optional[Callable[[], Awaitable[None]]] = None,
) -> Optional[list[Section]]:
    """Parse a provisioned bot's ``.json`` knowledge-base file, or ``None`` to fall back.

    Unlike the per-feed parsers this is not gated on a category: the caller opts in (the content2
    dynamic indexer), and the category is whichever bot folder the file arrived in.
    """
    normalized_category = (category or "").strip()
    if not normalized_category or file.file_extension().lower() != ".json":
        return None

    if check_cancel is not None:
        await check_cancel()

    try:
        payload = load_dynamic_json_payload(file)
    except ValueError:
        # Malformed JSON (json.JSONDecodeError and UnicodeDecodeError are both ValueErrors): let the
        # generic parser report it the way it always has.
        logger.warning("Could not read '%s' as JSON; falling back to the generic parser", file.filename())
        return None

    sections = prepare_dynamic_json_sections(payload, file=file, category=normalized_category)
    if sections is None:
        logger.info("'%s' is not a JSON record collection; falling back to the generic parser", file.filename())
        return None

    logger.info("Using the dynamic-bot JSON record parser for '%s' (%d section(s))", file.filename(), len(sections))

    if check_cancel is not None:
        await check_cancel()

    return sections
