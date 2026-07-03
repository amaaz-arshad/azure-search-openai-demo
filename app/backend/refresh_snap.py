#!/usr/bin/env python3
"""End-to-end refresh of the snap.de + nerilio.ai dataset in Azure AI Search
(single manual command).

Runs the whole pipeline in order:

  1. **Change check** — compares a cheap per-site watermark against
     ``data/snap.state.json`` from the last successful refresh: for snap.de the WP
     REST watermark (latest ``modified`` + record count for pages/posts, plus a hash
     of the rendered homepage header/footer chrome), for nerilio.ai the sitemap +
     per-page HEAD headers (Last-Modified/ETag). If NEITHER site changed it exits
     without touching anything, unless ``--force`` is given.
  2. **Scrape** — runs ``scripts/scrape_snap.py`` to (re)write ``data/snap.json`` as
     markdown covering BOTH sites (body content + one dedicated header/footer
     site-info document per site). Aborts (without deleting anything) if the scrape
     fails or either site yields no docs.
  3. **Re-index** — deletes the existing ``snap`` category from the search index and
     ``content/snap/`` blobs (``delete_category_data.py``), then re-indexes
     ``data/snap.json`` under category ``snap`` via the custom snap parser
     (``prepdocs.py``). Delete-then-add guarantees the index mirrors the live sites
     (removed pages leave no orphan chunks); there is a brief window during the run
     where ``/snap`` has no results.

The state watermark is written only after a successful re-index, so a failed run is
retried on the next invocation.

Prerequisites: run with the backend virtualenv while ``azd``/``az``-logged-in with the
deployment env selected (currently ``rg-agentic-retrieval-nerilio``). ``azd`` must be on
PATH — the delete/index steps resolve Azure config and credentials via ``load_azd_env``.

Usage (from the repo root)::

    app/.venv/Scripts/python.exe app/backend/refresh_snap.py             # change-gated refresh
    app/.venv/Scripts/python.exe app/backend/refresh_snap.py --force     # reindex even if unchanged
    app/.venv/Scripts/python.exe app/backend/refresh_snap.py --check-only # report changed/not, do nothing
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "app" / "backend"
SCRAPER = REPO_ROOT / "scripts" / "scrape_snap.py"
SNAP_JSON = REPO_ROOT / "data" / "snap.json"
STATE_FILE = REPO_ROOT / "data" / "snap.state.json"
DELETE_SCRIPT = BACKEND_DIR / "delete_category_data.py"
PREPDOCS_SCRIPT = BACKEND_DIR / "prepdocs.py"
CATEGORY = "snap"
FEED_MARKER = "snap.de"

# Reuse the scraper's watermark helpers so all site-specific knowledge lives in one module.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from scrape_snap import DEFAULT_BASE_URL, NERILIO_BASE_URL, fetch_remote_state  # noqa: E402


def log(message: str) -> None:
    print(f"[refresh_snap] {message}", flush=True)


def load_state() -> Optional[dict[str, Any]]:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        log(f"WARNING: could not read {STATE_FILE.name} ({error}); treating as changed.")
        return None


def save_state(remote_state: dict[str, Any], snap_payload: dict[str, Any]) -> None:
    state = {
        "remote": remote_state,
        "snap_generated_at": snap_payload.get("generated_at"),
        "doc_count": len(snap_payload.get("documents") or []),
    }
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"Wrote watermark to {STATE_FILE.relative_to(REPO_ROOT)}")


def run_step(title: str, argv: list[str], cwd: Path) -> None:
    """Run a sub-step, streaming its output live; raise SystemExit on failure."""
    log(f"=> {title}")
    log(f"   $ {' '.join(argv)}  (cwd={cwd})")
    completed = subprocess.run(argv, cwd=str(cwd))
    if completed.returncode != 0:
        raise SystemExit(f"[refresh_snap] STEP FAILED: {title} (exit {completed.returncode}). Aborting.")


def load_scraped_payload() -> dict[str, Any]:
    """Read + lightly validate data/snap.json after scraping, before any destructive step."""
    try:
        payload = json.loads(SNAP_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise SystemExit(f"[refresh_snap] Could not read scraped {SNAP_JSON}: {error}")
    if not isinstance(payload, dict) or payload.get("feed") != FEED_MARKER:
        raise SystemExit(f"[refresh_snap] {SNAP_JSON.name} is missing the '{FEED_MARKER}' feed marker; aborting.")
    documents = payload.get("documents")
    if not isinstance(documents, list) or not documents:
        raise SystemExit(f"[refresh_snap] {SNAP_JSON.name} has no documents; aborting before delete to avoid wiping the index.")
    # Both sites must be present before the destructive delete+reindex; a feed missing
    # one site would silently drop that site's content from the index.
    nerilio_count = sum(1 for doc in documents if isinstance(doc, dict) and str(doc.get("id", "")).startswith("nerilio-"))
    snap_count = len(documents) - nerilio_count
    if not nerilio_count or not snap_count:
        raise SystemExit(
            f"[refresh_snap] {SNAP_JSON.name} is missing one site's documents "
            f"(snap.de: {snap_count}, nerilio.ai: {nerilio_count}); aborting before delete."
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape snap.de + nerilio.ai and refresh the 'snap' category in Azure AI Search."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="snap.de base URL (default: %(default)s)")
    parser.add_argument(
        "--nerilio-base-url", default=NERILIO_BASE_URL, help="nerilio.ai base URL (default: %(default)s)"
    )
    parser.add_argument("--force", action="store_true", help="Re-scrape and re-index even if no change is detected")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only report whether snap.de or nerilio.ai changed since the last refresh; do not scrape or index",
    )
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    nerilio_base_url = args.nerilio_base_url.rstrip("/")

    # Step 1: change detection (a change on EITHER site triggers the full refresh).
    log(f"Checking snap.de ({base_url}) and nerilio.ai ({nerilio_base_url}) for changes ...")
    remote_state = fetch_remote_state(base_url, nerilio_base_url)
    stored = load_state()
    stored_remote = stored.get("remote") if stored else None
    changed = stored_remote != remote_state
    log(f"Remote watermark: {json.dumps(remote_state)}")
    if stored_remote is None:
        log("No previous watermark found (first run or missing state) -> treating as changed.")
    else:
        for site in ("snap", "nerilio"):
            site_changed = (stored_remote or {}).get(site) != remote_state.get(site)
            log(f"  {site}: {'CHANGED' if site_changed else 'unchanged'}")
        log(f"Change detected: {changed}")

    if args.check_only:
        log("CHANGED" if changed else "UP-TO-DATE")
        return 0

    if not changed and not args.force:
        log("No changes since last successful refresh; nothing to do. Use --force to reindex anyway.")
        return 0

    # Step 2: scrape (non-destructive; leaves the existing index intact if it fails).
    run_step(
        "Scrape snap.de + nerilio.ai -> data/snap.json",
        [sys.executable, str(SCRAPER), "--base-url", base_url, "--nerilio-base-url", nerilio_base_url],
        cwd=REPO_ROOT,
    )
    payload = load_scraped_payload()
    log(f"Scraped {len(payload['documents'])} documents.")

    # Step 3a: delete the existing 'snap' category (search docs + content/snap/ blobs).
    run_step(f"Delete category '{CATEGORY}' (search + blobs)", [sys.executable, str(DELETE_SCRIPT), CATEGORY], cwd=BACKEND_DIR)

    # Step 3b: re-index data/snap.json under category 'snap' via the custom snap parser.
    run_step(
        f"Index data/snap.json (category={CATEGORY})",
        [sys.executable, str(PREPDOCS_SCRIPT), str(SNAP_JSON), "--category", CATEGORY],
        cwd=BACKEND_DIR,
    )

    # Step 4: persist the watermark only after a clean re-index.
    save_state(remote_state, payload)
    log("DONE: snap.de + nerilio.ai re-scraped and re-indexed under category 'snap'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
