"""HYROX assessment visit tracking + the admin CSV export.

The bot pings ``/hyrox-assessment/visit`` on every page load; each recorded ping is one blob whose
NAME carries the whole row, so an export is a prefix listing with no downloads. Two policies gate
what is recorded at all: only a real Lemon LMS launch (i.e. one carrying an ``account_id``), and
only a deployed environment (a locally-run backend would otherwise write into the same production
container).
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

from approaches.chatbots.hyrox_assessment import visits
from prepdocslib.blobmanager import BlobListEntry

NOON = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)
PROD_HOST = "nerilio.snap.de"


class FakeBlobManager:
    """Records uploads and serves them back from list_blobs, like the real overwrite=True manager."""

    def __init__(self, entries: list[BlobListEntry] | None = None) -> None:
        self.writes: list[tuple[str, dict]] = []
        self.entries: list[BlobListEntry] = list(entries or [])

    async def upload_blob_data(self, file, blob_name: str, content_type: str | None = None) -> str:
        file.seek(0)
        self.writes.append((blob_name, json.loads(file.read().decode("utf-8"))))
        self.entries.append(BlobListEntry(name=blob_name, last_modified=NOON))
        return f"https://example.invalid/{blob_name}"

    async def list_blobs(self, prefix: str | None = None) -> list[BlobListEntry]:
        normalized = (prefix or "").strip("/")
        return [entry for entry in self.entries if entry.name.startswith(normalized)]


def visit_entry(user_id: str, moment: datetime, nonce: str = "abcd1234") -> BlobListEntry:
    return BlobListEntry(name=visits.visit_blob_name(user_id, moment, nonce), last_modified=moment)


def record(blob_manager, account_id, host=PROD_HOST, moment=NOON, nonce="aaaa1111"):
    return asyncio.run(visits.record_visit(blob_manager, account_id, host=host, moment=moment, nonce=nonce))


def test_the_blob_name_carries_the_whole_row_so_an_export_needs_no_downloads() -> None:
    name = visits.visit_blob_name("104477", NOON, "abcd1234")
    assert name == "hyrox-assessment-visits/2026-08/20260814T120000000Z__104477__abcd1234.json"

    row = visits.parse_visit_blob_name(name)
    assert row is not None
    assert row.user_id == "104477"
    assert row.timestamp == NOON


def test_an_id_containing_the_field_separator_still_round_trips() -> None:
    # The sanitizer rewrites unsafe characters to single underscores, so an id CAN end up holding the
    # "__" separator. Rebuilding it from every middle part is what keeps that exact.
    user_id = visits.normalize_user_id("a$$b")
    assert user_id == "a__b"

    row = visits.parse_visit_blob_name(visits.visit_blob_name(user_id, NOON, "ff00ff00"))
    assert row is not None and row.user_id == "a__b"


def test_user_ids_are_blob_safe_and_an_absent_id_is_not_a_visit() -> None:
    assert visits.normalize_user_id("104477") == "104477"
    assert visits.normalize_user_id(104477) == "104477"
    # No id at all means the bot was not launched from Lemon: there is nothing to record.
    assert visits.normalize_user_id(None) is None
    assert visits.normalize_user_id("  ") is None
    # Path traversal in a caller-supplied id cannot escape the month folder.
    name = visits.visit_blob_name(str(visits.normalize_user_id("../../etc/passwd")), NOON, "ff00ff00")
    assert name.startswith("hyrox-assessment-visits/2026-08/") and name.count("/") == 2
    # A hostile caller cannot write an unbounded blob name.
    assert len(str(visits.normalize_user_id("x" * 500))) == visits.MAX_USER_ID_LENGTH


def test_only_a_lemon_launch_is_recorded() -> None:
    blob_manager = FakeBlobManager()
    assert record(blob_manager, "104477") is not None
    # Opened outside the LMS (no account_id on the launch URL) -> nothing at all is written.
    assert record(blob_manager, None) is None
    assert record(blob_manager, "") is None
    assert record(blob_manager, "   ") is None
    assert [name for name, _ in blob_manager.writes] == [visits.visit_blob_name("104477", NOON, "aaaa1111")]


def test_only_a_deployed_environment_is_recorded() -> None:
    blob_manager = FakeBlobManager()
    # start.ps1 loads the azd env and there is no storage emulator, so a local run would otherwise
    # write straight into the production container.
    for local_host in ["localhost:50505", "127.0.0.1:50505", "LOCALHOST", "[::1]:50505", "app.localhost"]:
        assert record(blob_manager, "104477", host=local_host) is None
    assert blob_manager.writes == []

    # Deployed hosts record, and so does an unknown/absent Host: failing open keeps production
    # recording even if something upstream rewrites the header.
    for deployed_host in [PROD_HOST, "bot-backend.happyocean.azurecontainerapps.io", None, ""]:
        assert record(blob_manager, "104477", host=deployed_host) is not None


def test_the_gate_is_one_function_so_both_policies_stay_together() -> None:
    assert visits.should_record_visit("104477", PROD_HOST)
    assert not visits.should_record_visit(None, PROD_HOST)
    assert not visits.should_record_visit("104477", "localhost:50505")
    assert not visits.should_record_visit(None, "localhost:50505")


def test_each_ping_is_its_own_blob_so_concurrent_visits_never_overwrite_each_other() -> None:
    blob_manager = FakeBlobManager()
    record(blob_manager, "104477", nonce="aaaa1111")
    # Same learner, same millisecond: only the nonce keeps these apart.
    record(blob_manager, "104477", nonce="bbbb2222")

    assert len({name for name, _ in blob_manager.writes}) == 2
    assert blob_manager.writes[0][1]["user_id"] == "104477"
    # Stored in UTC; only what the admin reads is converted.
    assert blob_manager.writes[0][1]["recorded_at"] == NOON.isoformat()


def test_the_body_keeps_the_raw_id_the_launch_url_carried() -> None:
    blob_manager = FakeBlobManager()
    record(blob_manager, "a$$b")

    _name, stored = blob_manager.writes[0]
    assert stored["user_id"] == "a__b"  # the sanitized form the CSV shows
    assert stored["account_id"] == "a$$b"  # ... and what it was before sanitizing


def test_recording_a_visit_never_raises_into_the_learners_page() -> None:
    class Boom:
        async def upload_blob_data(self, file, blob_name, content_type=None):
            raise RuntimeError("storage is down")

    assert record(Boom(), "104477") is None
    # No blob backend at all (local dev): logged, not raised.
    assert record(None, "104477") is None


def test_the_export_holds_only_real_pings_with_no_reconstructed_history() -> None:
    # Session logs are NOT a source: the export starts from the day tracking shipped.
    blob_manager = FakeBlobManager(
        [
            BlobListEntry(name="hyrox-assessment-logs/104477/sess-1.json", last_modified=NOON - timedelta(days=30)),
            visit_entry("104477", NOON),
            visit_entry("200", NOON + timedelta(hours=1)),
        ]
    )

    rows = asyncio.run(visits.collect_rows(blob_manager))

    assert [row.user_id for row in rows] == ["104477", "200"]
    # Oldest first: the CSV reads chronologically.
    assert [row.timestamp for row in rows] == sorted(row.timestamp for row in rows)


def test_unrecognized_blob_names_are_skipped_rather_than_breaking_the_export() -> None:
    blob_manager = FakeBlobManager(
        [
            BlobListEntry(name="hyrox-assessment-visits/2026-08/not-a-visit.json", last_modified=NOON),
            BlobListEntry(name="hyrox-assessment-visits/2026-08/20260814T120000000Z__104477.json", last_modified=NOON),
            BlobListEntry(name="hyrox-assessment-visits/2026-08/20260814T120000000Z____ff00.json", last_modified=NOON),
            visit_entry("104477", NOON),
        ]
    )

    rows = asyncio.run(visits.collect_rows(blob_manager))

    assert [row.user_id for row in rows] == ["104477"]


def test_a_storage_failure_degrades_to_fewer_rows_not_a_500() -> None:
    class Boom:
        async def list_blobs(self, prefix=None):
            raise RuntimeError("storage is down")

    assert asyncio.run(visits.collect_rows(Boom())) == []
    assert asyncio.run(visits.collect_rows(None)) == []


def test_rows_slice_by_german_month_and_summarize_per_month() -> None:
    rows = [
        # 01:30 on 1 August German time -> the August bucket, matching the date the preview shows.
        visits.VisitRow("104477", datetime(2026, 7, 31, 23, 30, tzinfo=timezone.utc)),
        # 23:30 on 31 July German time -> still July, though UTC already calls it August.
        visits.VisitRow("104477", datetime(2026, 7, 31, 21, 30, tzinfo=timezone.utc)),
        visits.VisitRow("104477", NOON),
        visits.VisitRow("200", NOON),
    ]

    assert len(visits.filter_rows_by_month(rows, "2026-08")) == 3
    assert len(visits.filter_rows_by_month(rows, "2026-07")) == 1
    assert len(visits.filter_rows_by_month(rows, visits.ALL_MONTHS)) == 4
    assert len(visits.filter_rows_by_month(rows, "")) == 4

    # Newest month first, so the picker opens on the month an admin is most likely exporting.
    assert visits.month_summaries(rows) == [
        {"month": "2026-08", "totalCount": 3},
        {"month": "2026-07", "totalCount": 1},
    ]


def test_the_displayed_month_and_the_blob_folder_are_allowed_to_disagree() -> None:
    # The folder is UTC forever (one unchanging storage convention, and no read depends on it); the
    # export bucket is the German-time month, so it matches the timestamp an admin is looking at.
    late_july = datetime(2026, 7, 31, 23, 30, tzinfo=timezone.utc)

    assert visits.blob_month_of(late_july) == "2026-07"
    assert visits.display_month_of(late_july) == "2026-08"
    assert visits.visit_blob_name("104477", late_july, "ff00ff00").startswith("hyrox-assessment-visits/2026-07/")
    # ... and the row is still recovered from the file name, not from the folder it sits in.
    row = visits.parse_visit_blob_name(visits.visit_blob_name("104477", late_july, "ff00ff00"))
    assert row is not None and row.timestamp == late_july


def test_german_time_follows_the_eu_daylight_saving_rule() -> None:
    # CET in winter, CEST in summer, switching at 01:00 UTC on the last Sunday of March/October.
    # Computed from the rule rather than read from `zoneinfo`, which cannot resolve Europe/Berlin on
    # a stock Windows dev machine -- so these are the assertions that pin it.
    assert visits.last_sunday_at_one_utc(2026, 3) == datetime(2026, 3, 29, 1, tzinfo=timezone.utc)
    assert visits.last_sunday_at_one_utc(2026, 10) == datetime(2026, 10, 25, 1, tzinfo=timezone.utc)
    assert visits.last_sunday_at_one_utc(2027, 3) == datetime(2027, 3, 28, 1, tzinfo=timezone.utc)
    assert visits.last_sunday_at_one_utc(2027, 10) == datetime(2027, 10, 31, 1, tzinfo=timezone.utc)

    winter = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    summer = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    assert visits.to_german_time(winter).isoformat() == "2026-01-15T13:00:00+01:00"
    assert visits.to_german_time(summer).isoformat() == "2026-08-14T14:00:00+02:00"

    # The exact changeover instants, from either side.
    assert visits.to_german_time(datetime(2026, 3, 29, 0, 59, 59, tzinfo=timezone.utc)).isoformat() == "2026-03-29T01:59:59+01:00"
    assert visits.to_german_time(datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc)).isoformat() == "2026-03-29T03:00:00+02:00"
    assert visits.to_german_time(datetime(2026, 10, 25, 0, 59, 59, tzinfo=timezone.utc)).isoformat() == "2026-10-25T02:59:59+02:00"
    assert visits.to_german_time(datetime(2026, 10, 25, 1, 0, tzinfo=timezone.utc)).isoformat() == "2026-10-25T02:00:00+01:00"

    # A naive timestamp is read as UTC rather than dropped, exactly like everywhere else here.
    assert visits.to_german_time(datetime(2026, 8, 14, 12, 0)).isoformat() == "2026-08-14T14:00:00+02:00"


def test_month_parameters_are_validated() -> None:
    assert visits.is_valid_month("2026-08")
    assert not visits.is_valid_month("2026-13")
    assert not visits.is_valid_month("2026-8")
    assert not visits.is_valid_month("")
    assert not visits.is_valid_month("../../etc")


def test_the_csv_is_exactly_user_id_and_timestamp() -> None:
    rows = [visits.VisitRow("104477", NOON), visits.VisitRow("200", NOON + timedelta(seconds=5))]

    # German local time carrying its offset: the clock the admin reads, unmistakable for UTC.
    assert visits.render_visits_csv(rows).splitlines() == [
        "user_id,timestamp",
        "104477,2026-08-14T14:00:00+02:00",
        "200,2026-08-14T14:00:05+02:00",
    ]
    assert visits.csv_filename("2026-08") == "hyrox-visits-2026-08.csv"
    assert visits.csv_filename(visits.ALL_MONTHS) == "hyrox-visits-all.csv"
    assert visits.csv_filename("") == "hyrox-visits-all.csv"


def test_a_recorded_visit_is_readable_back_out_of_the_listing() -> None:
    blob_manager = FakeBlobManager()
    record(blob_manager, "104477", nonce="aaaa1111")
    record(blob_manager, "200", moment=NOON + timedelta(minutes=1), nonce="bbbb2222")

    rows = asyncio.run(visits.collect_rows(blob_manager))

    assert visits.render_visits_csv(rows).splitlines() == [
        "user_id,timestamp",
        "104477,2026-08-14T14:00:00+02:00",
        "200,2026-08-14T14:01:00+02:00",
    ]
