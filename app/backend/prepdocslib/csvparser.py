import csv
import io
import os
import re
from collections.abc import AsyncGenerator
from typing import IO, Any, Optional

from .page import Page
from .parser import Parser

CSV_SNIFF_DELIMITERS = ",;\t|"
DEFAULT_TEXT_HEAVY_HEADERS = {
    "abstract",
    "body",
    "content",
    "description",
    "details",
    "excerpt",
    "notes",
    "summary",
}
TITLE_HEADER_CANDIDATES = {
    "course",
    "course title",
    "document title",
    "event",
    "event title",
    "headline",
    "name",
    "seminar",
    "subject",
    "title",
}
URL_HEADER_KEYWORDS = ("url", "link", "href", "website")
USER_HEADER_CANDIDATES = {"user", "user id", "userid", "username", "email", "mail", "oid"}
TAG_HEADER_CANDIDATES = {
    "audience",
    "category",
    "department",
    "group",
    "organizer",
    "organiser",
    "person",
    "speaker",
    "topic",
    "user",
    "user id",
    "userid",
    "username",
}
SKIPPED_CONTENT_HEADERS = {"welcome"}
SPECIAL_HEADER_LABELS = {
    "email": "Email",
    "oid": "OID",
    "url": "URL",
    "user": "User",
    "user id": "User ID",
    "userid": "User ID",
    "username": "Username",
}


class CsvParser(Parser):
    """
    Parse CSV-like tabular files into one Page per logical row.

    Goals:
    - Handle common dialects such as comma, semicolon, tab, or pipe separated data.
    - Preserve quoted multiline cells as part of the same logical row.
    - Emit retrieval-friendly labeled text instead of raw delimiter-joined values.
    - Surface row metadata such as title, URL, row citation, tags, and optional user scope.
    """

    async def parse(self, content: IO) -> AsyncGenerator[Page, None]:
        content_text = self.read_text(content)
        if not content_text.strip():
            return

        dialect = self.detect_dialect(content_text)
        reader = csv.reader(io.StringIO(content_text, newline=""), dialect)

        try:
            raw_headers = next(reader)
        except StopIteration:
            return

        headers = self.normalize_headers(raw_headers)
        offset = 0

        for row_index, raw_row in enumerate(reader, start=2):
            normalized_row = self.normalize_row(raw_row, len(headers))
            if not any(normalized_row):
                continue

            row_data = self.build_row_mapping(headers, normalized_row)
            page_text = self.render_row_text(row_data)
            if not page_text:
                continue

            filename = self.content_filename(content)
            sourcepage = f"{filename}#row={row_index}"
            title = self.extract_title(row_data)
            url = self.extract_url(row_data)
            tags = self.extract_tags(row_data)
            user = self.extract_user(row_data)

            yield Page(
                page_num=row_index - 2,
                offset=offset,
                text=page_text,
                sourcepage=sourcepage,
                title=title,
                url=url,
                tags=tags,
                user=user,
            )
            offset += len(page_text) + 1

    def read_text(self, content: IO) -> str:
        raw: Any
        if isinstance(content, (bytes, bytearray)):
            raw = bytes(content)
        elif hasattr(content, "read"):
            if hasattr(content, "seek"):
                try:
                    content.seek(0)
                except Exception:
                    pass
            raw = content.read()
            if hasattr(content, "seek"):
                try:
                    content.seek(0)
                except Exception:
                    pass
        else:
            raise ValueError("Unsupported CSV content object")

        if isinstance(raw, str):
            return raw
        if not isinstance(raw, (bytes, bytearray)):
            raise ValueError("CSV content read() must return bytes or string data")

        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    def detect_dialect(self, content_text: str) -> csv.Dialect:
        sample = content_text[:8192]
        sniffer = csv.Sniffer()
        try:
            return sniffer.sniff(sample, delimiters=CSV_SNIFF_DELIMITERS)
        except csv.Error:
            delimiter = self.pick_fallback_delimiter(sample)
            return self.make_dialect(delimiter)

    def pick_fallback_delimiter(self, sample: str) -> str:
        first_line = sample.splitlines()[0] if sample.splitlines() else sample
        counts = {delimiter: first_line.count(delimiter) for delimiter in CSV_SNIFF_DELIMITERS}
        delimiter, count = max(counts.items(), key=lambda item: item[1])
        return delimiter if count > 0 else ","

    def make_dialect(self, delimiter: str) -> type[csv.Dialect]:
        return type(
            "FallbackDialect",
            (csv.Dialect,),
            {
                "quoting": csv.QUOTE_MINIMAL,
                "delimiter": delimiter,
                "quotechar": '"',
                "doublequote": True,
                "escapechar": None,
                "skipinitialspace": False,
                "lineterminator": "\n",
            },
        )

    def normalize_headers(self, headers: list[str]) -> list[str]:
        normalized_headers: list[str] = []
        counts: dict[str, int] = {}
        for index, header in enumerate(headers):
            cleaned = self.clean_header(header) or f"column_{index + 1}"
            occurrence = counts.get(cleaned, 0)
            counts[cleaned] = occurrence + 1
            normalized_headers.append(cleaned if occurrence == 0 else f"{cleaned}_{occurrence + 1}")
        return normalized_headers

    def clean_header(self, value: str) -> str:
        cleaned = value.replace("\ufeff", "").strip().strip('"').strip("'")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned

    def normalize_row(self, row: list[str], header_count: int) -> list[str]:
        if len(row) > header_count and header_count > 0:
            row = row[: header_count - 1] + ["\n".join(value for value in row[header_count - 1 :] if value)]
        normalized_row = [self.clean_cell(value) for value in row[:header_count]]
        if len(normalized_row) < header_count:
            normalized_row.extend([""] * (header_count - len(normalized_row)))
        return normalized_row

    def clean_cell(self, value: str) -> str:
        collapsed = value.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n").strip()
        collapsed = re.sub(r"[ \t]+\n", "\n", collapsed)
        collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
        return collapsed

    def build_row_mapping(self, headers: list[str], row: list[str]) -> dict[str, str]:
        return {header: value for header, value in zip(headers, row) if value}

    def render_row_text(self, row_data: dict[str, str]) -> str:
        title = self.extract_title(row_data)
        title_header = self.find_title_header(row_data)
        short_lines: list[str] = []
        long_sections: list[str] = []

        if title:
            short_lines.append(f"Title: {title}")

        for header, value in row_data.items():
            if self.normalize_header_key(header) in SKIPPED_CONTENT_HEADERS:
                continue
            if title and header == title_header:
                continue

            label = self.header_to_label(header)
            if self.is_text_heavy_field(header, value):
                long_sections.append(f"{label}:\n{value}")
            else:
                short_lines.append(f"{label}: {self.normalize_scalar_value(header, value)}")

        sections = []
        if short_lines:
            sections.append("\n".join(short_lines))
        if long_sections:
            sections.extend(long_sections)
        return "\n\n".join(section for section in sections if section.strip()).strip()

    def normalize_scalar_value(self, header: str, value: str) -> str:
        lowered_header = self.normalize_header_key(header)
        lowered_value = value.strip().lower()
        if lowered_header == "online":
            if lowered_value in {"x", "yes", "y", "true", "1", "ja"}:
                return "Yes"
            if lowered_value in {"no", "n", "false", "0", "nein"}:
                return "No"
        return value

    def is_text_heavy_field(self, header: str, value: str) -> bool:
        normalized_header = self.normalize_header_key(header)
        if normalized_header in DEFAULT_TEXT_HEAVY_HEADERS:
            return True
        if "\n" in value:
            return True
        return len(value) > 240

    def extract_title(self, row_data: dict[str, str]) -> Optional[str]:
        title_header = self.find_title_header(row_data)
        if title_header:
            return row_data.get(title_header)
        return None

    def find_title_header(self, row_data: dict[str, str]) -> Optional[str]:
        for header in row_data:
            if self.normalize_header_key(header) in TITLE_HEADER_CANDIDATES:
                return header
        return None

    def extract_url(self, row_data: dict[str, str]) -> Optional[str]:
        for header, value in row_data.items():
            normalized_header = self.normalize_header_key(header)
            if any(keyword in normalized_header for keyword in URL_HEADER_KEYWORDS):
                if value.lower().startswith(("http://", "https://")):
                    return value
        return None

    def extract_tags(self, row_data: dict[str, str]) -> list[str]:
        tags: list[str] = []
        seen: set[str] = set()
        for header, value in row_data.items():
            normalized_header = self.normalize_header_key(header)
            if normalized_header not in TAG_HEADER_CANDIDATES:
                continue
            tag_value = self.normalize_scalar_value(header, value)
            tag = f"{self.header_to_label(header)}: {tag_value}"
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
        return tags

    def extract_user(self, row_data: dict[str, str]) -> Optional[str]:
        for header, value in row_data.items():
            if self.normalize_header_key(header) in USER_HEADER_CANDIDATES:
                normalized_value = value.strip().lower()
                if normalized_value:
                    return normalized_value
        return None

    def header_to_label(self, header: str) -> str:
        normalized_key = self.normalize_header_key(header)
        if normalized_key in SPECIAL_HEADER_LABELS:
            return SPECIAL_HEADER_LABELS[normalized_key]
        if any(keyword in normalized_key for keyword in URL_HEADER_KEYWORDS):
            return "URL"

        normalized = re.sub(r"[_/]+", " ", header)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        parts = [
            part.upper() if part.upper() in {"ID", "URL", "URI", "OID"} else part.capitalize()
            for part in normalized.split(" ")
        ]
        return " ".join(parts)

    def normalize_header_key(self, header: str) -> str:
        normalized = header.replace("_", " ").replace("/", " ").strip().lower()
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized

    def content_filename(self, content: IO) -> str:
        if hasattr(content, "filename") and getattr(content, "filename"):
            return os.path.basename(getattr(content, "filename"))
        if hasattr(content, "name") and getattr(content, "name"):
            return os.path.basename(getattr(content, "name"))
        return "table.csv"
