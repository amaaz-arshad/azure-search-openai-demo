"""Visit tracking and the monthly CSV export for the HYROX assessment bot.

The bot posts to ``/hyrox-assessment/visit`` on every page load and each recorded ping writes ONE
tiny blob under ``hyrox-assessment-visits/<YYYY-MM>/``. One blob per visit — rather than appending
rows to a monthly file — because an append is a read-modify-write that two concurrent learners would
race on and silently lose rows to; a blob write is atomic and needs no coordination.

The blob NAME carries the whole row (``<timestamp>__<user id>__<nonce>.json``), so building a
month's CSV is one prefix listing and zero downloads. The JSON body repeats it and adds the raw,
unsanitized account id, so a row whose id was rewritten by the blob-segment sanitizer can still be
traced back to what the launch URL actually carried.

``should_record_visit`` is the single gate, and it encodes two deliberate policies:

**Only real Lemon LMS launches count.** The LMS is what puts ``account_id`` on the launch URL (both
for the native webview and for the ``web_frontend=true`` iframe), so its presence IS the signal that
a visit came from within Lemon; a visit without one is someone opening the bot's URL directly and is
not counted at all. There is no more reliable host-side check available: the native webview sends no
referrer, and inside the LMS iframe the chat calls are same-origin, so neither ``Origin`` nor
``Referer`` identifies the embedding page.

**Only production is counted.** ``app/start.ps1`` loads the azd environment and the app has no
storage emulator, so a locally-run backend would otherwise write into the very same production
container. A request whose Host is positively a loopback name is dropped. The check is deliberately
one-directional — anything not recognised as local still records — because silently recording
nothing in production is a far worse failure than a stray local row.

Timestamps are STORED in UTC (the blob name, the JSON body, the month folder) and SHOWN in German
time (the admin preview table and the CSV). See ``to_german_time`` for why the conversion is computed
rather than looked up, and ``blob_month_of``/``display_month_of`` for the one place the two clocks
disagree: a visit just before UTC midnight is filed in the older month's folder but exports under the
German-time month its displayed date reads.

Both prefixes live in the ``content`` container, which ``/content/<path>`` serves unauthenticated
(the same accepted residual the session logs carry). A visit blob holds only an account id and a
timestamp, and its name embeds a random nonce, so it is not enumerable — but it is not secret either.
"""

import csv
import io
import json
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Optional

from approaches.chatbots.hyrox_assessment.results import BLOB_SEGMENT_UNSAFE_RE

logger = logging.getLogger("hyrox_assessment")

VISIT_LOG_PREFIX = "hyrox-assessment-visits"
# Separates the fields inside a visit blob's file name. Two underscores rather than one because the
# sanitizer rewrites unsafe characters to a single underscore; splitting and re-joining the middle
# parts round-trips an id containing the separator either way (see parse_visit_blob_name).
NAME_FIELD_SEPARATOR = "__"
# Long enough for any LMS account id; a cap keeps a hostile caller from writing huge blob names.
MAX_USER_ID_LENGTH = 64
MONTH_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")
# Millisecond precision, fixed width, lexicographically sortable -> a prefix listing comes back in
# chronological order for free.
VISIT_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S%fZ"
# Selects every month at once in the admin export.
ALL_MONTHS = "all"
# Hosts that prove the request did not reach a deployed environment. Matched on the hostname only
# (the port is stripped first), plus any `*.localhost` name.
LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


@dataclass
class VisitRow:
    """One CSV row: which learner, and when."""

    user_id: str
    timestamp: datetime


def normalize_user_id(account_id: Any) -> Optional[str]:
    """The learner id as it appears in blob names and in the CSV, or None when the launch carried no
    id at all. Sanitized to blob-safe characters with the same rule the session logs use, so the same
    learner reads identically in both places."""
    text = str(account_id).strip() if account_id not in (None, "") else ""
    return BLOB_SEGMENT_UNSAFE_RE.sub("_", text[:MAX_USER_ID_LENGTH]) or None


def is_local_request_host(host: Optional[str]) -> bool:
    """True only when the Host proves this is a local (non-deployed) run. An unknown or missing host
    is NOT treated as local: failing open keeps production recording even if a proxy rewrites Host."""
    hostname = (host or "").strip().lower()
    if not hostname:
        return False
    # Strip a port, tolerating a bracketed IPv6 literal ([::1]:50505).
    if hostname.startswith("["):
        hostname = hostname[1:].split("]", 1)[0]
    elif ":" in hostname:
        hostname = hostname.rsplit(":", 1)[0]
    return hostname in LOCAL_HOSTNAMES or hostname.endswith(".localhost")


def should_record_visit(account_id: Any, host: Optional[str]) -> bool:
    """The single gate: a visit is recorded only for a real Lemon LMS launch on a deployed
    environment. See the module docstring for why these two signals, and only these two."""
    if normalize_user_id(account_id) is None:
        return False
    return not is_local_request_host(host)


# Everything the export SHOWS is German time; everything it STORES is UTC.
#
# The admins reading this log live on a German clock, so the preview table and the CSV both read in
# it. The offset is computed here rather than resolved through `zoneinfo` because no IANA database is
# available across this project's environments: `ZoneInfo("Europe/Berlin")` resolves inside the Linux
# container but raises on a stock Windows dev machine (no `tzdata` package), and a helper that only
# works in production is one no test can pin. Germany's rule is fixed EU law (Directive 2000/84/EC,
# unchanged since 1996) and is pure arithmetic: CET = UTC+1, CEST = UTC+2 from 01:00 UTC on the last
# Sunday of March until 01:00 UTC on the last Sunday of October. If the EU ever abolishes the
# switch, this is the one place to change. (The telemetry dashboard shows the same zone but converts
# browser-side, where the full IANA data does exist — see charts/scales.ts.)
GERMAN_STANDARD_OFFSET = timedelta(hours=1)
GERMAN_SUMMER_OFFSET = timedelta(hours=2)


def last_sunday_at_one_utc(year: int, month: int) -> datetime:
    """01:00 UTC on the last Sunday of a month — the instant the EU clocks change."""
    next_month_year = year + 1 if month == 12 else year
    next_month = 1 if month == 12 else month + 1
    # Midnight on the month's last day, so every time field below is already zero.
    last_day = datetime(next_month_year, next_month, 1, tzinfo=timezone.utc) - timedelta(days=1)
    # weekday() is Monday=0..Sunday=6, so (weekday + 1) % 7 is "days back to the last Sunday".
    return (last_day - timedelta(days=(last_day.weekday() + 1) % 7)).replace(hour=1)


def german_timezone(moment: datetime) -> timezone:
    """CET or CEST for one instant, as a fixed-offset zone that names itself."""
    moment = to_utc(moment)
    summer_starts = last_sunday_at_one_utc(moment.year, 3)
    summer_ends = last_sunday_at_one_utc(moment.year, 10)
    if summer_starts <= moment < summer_ends:
        return timezone(GERMAN_SUMMER_OFFSET, "CEST")
    return timezone(GERMAN_STANDARD_OFFSET, "CET")


def to_german_time(moment: datetime) -> datetime:
    """The same instant, read on a German clock."""
    return to_utc(moment).astimezone(german_timezone(moment))


def blob_month_of(moment: datetime) -> str:
    """``YYYY-MM`` in UTC — the month FOLDER, and nothing else. Storage keeps one unchanging
    convention (every blob ever written is filed by its UTC month) and no read depends on it: a row
    is recovered from the timestamp in the file name, not from the folder. The month an admin exports
    by is ``display_month_of``, which differs for a visit in the hour or two before UTC midnight."""
    return to_utc(moment).strftime("%Y-%m")


def display_month_of(moment: datetime) -> str:
    """``YYYY-MM`` in German time — what the month picker labels and the export slices by, so a row's
    displayed date always matches the month it is exported under."""
    return to_german_time(moment).strftime("%Y-%m")


def is_valid_month(month: str) -> bool:
    return bool(MONTH_RE.match(month or ""))


def to_utc(moment: datetime) -> datetime:
    """Azure hands back tz-aware UTC timestamps; a naive one is treated as UTC rather than dropped."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def format_visit_timestamp(moment: datetime) -> str:
    return to_utc(moment).strftime("%Y%m%dT%H%M%S%f")[:-3] + "Z"


def parse_visit_timestamp(text: str) -> Optional[datetime]:
    try:
        return datetime.strptime(text, VISIT_TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def visit_blob_name(user_id: str, moment: datetime, nonce: str) -> str:
    """``hyrox-assessment-visits/<YYYY-MM>/<timestamp>__<user id>__<nonce>.json``.

    The nonce keeps two visits that land in the same millisecond from overwriting each other."""
    return (
        f"{VISIT_LOG_PREFIX}/{blob_month_of(moment)}/"
        f"{format_visit_timestamp(moment)}{NAME_FIELD_SEPARATOR}{user_id}"
        f"{NAME_FIELD_SEPARATOR}{nonce}.json"
    )


def parse_visit_blob_name(blob_name: str) -> Optional[VisitRow]:
    """Recover the row from a visit blob's name, or None when the name is not one of ours."""
    if not blob_name.startswith(f"{VISIT_LOG_PREFIX}/") or not blob_name.endswith(".json"):
        return None
    filename = blob_name[: -len(".json")].rsplit("/", 1)[-1]
    parts = filename.split(NAME_FIELD_SEPARATOR)
    if len(parts) < 3:
        return None
    timestamp = parse_visit_timestamp(parts[0])
    if timestamp is None:
        return None
    # The id itself may contain the separator, so rebuild it from every part between the fixed
    # timestamp and nonce; splitting and re-joining is exact.
    user_id = NAME_FIELD_SEPARATOR.join(parts[1:-1])
    if not user_id:
        return None
    return VisitRow(user_id=user_id, timestamp=timestamp)


async def record_visit(
    blob_manager: Any,
    account_id: Any,
    host: Optional[str] = None,
    moment: Optional[datetime] = None,
    nonce: Optional[str] = None,
) -> Optional[str]:
    """Write one visit blob when ``should_record_visit`` allows it. Best-effort: never raises, so a
    storage hiccup cannot surface in the learner's page. Returns the blob name written, or None when
    nothing was written (not a Lemon launch, not production, or the write failed)."""
    user_id = normalize_user_id(account_id)
    if user_id is None or is_local_request_host(host):
        logger.debug("HYROX assessment visit not recorded (account_id=%r host=%r)", account_id, host)
        return None

    moment = to_utc(moment or datetime.now(timezone.utc))
    blob_name = visit_blob_name(user_id, moment, nonce or secrets.token_hex(4))
    record = {
        "user_id": user_id,
        # The id exactly as the launch URL carried it; `user_id` above is the sanitized form the
        # blob name — and therefore the CSV — uses.
        "account_id": str(account_id).strip()[:MAX_USER_ID_LENGTH],
        "recorded_at": moment.isoformat(),
    }

    if blob_manager is None or not hasattr(blob_manager, "upload_blob_data"):
        logger.info("HYROX assessment visit (no blob manager): %s", blob_name)
        return None

    try:
        data = BytesIO(json.dumps(record, ensure_ascii=False).encode("utf-8"))
        await blob_manager.upload_blob_data(data, blob_name, content_type="application/json")
        logger.info("HYROX assessment visit recorded: %s", blob_name)
        return blob_name
    except Exception:
        logger.exception("Failed to record HYROX assessment visit: %s", blob_name)
        return None


async def collect_rows(blob_manager: Any) -> list[VisitRow]:
    """Every recorded visit, oldest first. Tolerates a missing/blob-less manager and transient
    storage errors — the export must degrade to fewer rows rather than to a 500."""
    if blob_manager is None or not hasattr(blob_manager, "list_blobs"):
        return []
    try:
        entries = list(await blob_manager.list_blobs(VISIT_LOG_PREFIX))
    except Exception:
        logger.exception("Failed to list HYROX assessment visits under %s", VISIT_LOG_PREFIX)
        return []

    rows = []
    for entry in entries:
        row = parse_visit_blob_name(getattr(entry, "name", "") or "")
        if row is not None:
            rows.append(row)
    return sorted(rows, key=lambda row: (row.timestamp, row.user_id))


def filter_rows_by_month(rows: list[VisitRow], month: Optional[str]) -> list[VisitRow]:
    """Rows in one ``YYYY-MM`` German-time month. An empty month or ``all`` keeps everything."""
    if not month or month == ALL_MONTHS:
        return list(rows)
    return [row for row in rows if display_month_of(row.timestamp) == month]


def month_summaries(rows: list[VisitRow]) -> list[dict[str, Any]]:
    """Per-month counts for the admin month picker, newest month first."""
    counts: dict[str, int] = {}
    for row in rows:
        month = display_month_of(row.timestamp)
        counts[month] = counts.get(month, 0) + 1
    return [{"month": month, "totalCount": counts[month]} for month in sorted(counts, reverse=True)]


def format_csv_timestamp(moment: datetime) -> str:
    """German local time as ISO 8601 to the second, carrying its offset
    (``2026-08-14T14:00:00+02:00``) — the clock the admins reading the export live in, stated
    precisely enough that a reader can never mistake it for UTC and can tell CET from CEST without a
    second column. Same clock the preview table reads on, and the same one the export's month
    boundary is measured against."""
    return to_german_time(moment).isoformat(timespec="seconds")


def render_visits_csv(rows: list[VisitRow]) -> str:
    """The export itself: one row per visit, user id and timestamp."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["user_id", "timestamp"])
    for row in rows:
        writer.writerow([row.user_id, format_csv_timestamp(row.timestamp)])
    return buffer.getvalue()


def csv_filename(month: Optional[str]) -> str:
    return f"hyrox-visits-{month if month and month != ALL_MONTHS else ALL_MONTHS}.csv"
