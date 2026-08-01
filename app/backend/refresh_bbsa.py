#!/usr/bin/env python3
"""End-to-end refresh of the breitband.tirol dataset in Azure AI Search
(single manual command).

Runs the whole pipeline in order:

  1. **Change check** — compares a cheap watermark against ``data/bbsa.state.json``
     from the last successful refresh: the latest ``modified`` timestamp and record
     count for ``pages`` and ``posts``, the per-municipality ``modified`` map from the
     ``gemeinde`` post type (which is what moves when a municipality's Elementor
     fields are edited, since the shared page IDs never change), and a hash of the
     rendered homepage header/footer chrome. If nothing changed it exits without
     touching anything, unless ``--force`` is given.
  2. **Scrape** — runs ``scripts/scrape_bbsa.py`` to (re)write ``data/bbsa.json`` as
     markdown covering the statewide portal, its header/footer, the municipality
     index, and one document per municipality subdomain. Aborts (without deleting
     anything) if the scrape fails or either half of the feed is empty.
  3. **Re-index** — deletes the existing ``bbsa`` category from the search index and
     ``content/bbsa/`` blobs (``delete_category_data.py``), then re-indexes
     ``data/bbsa.json`` under category ``bbsa`` via the custom bbsa parser
     (``prepdocs.py``). Delete-then-add guarantees the index mirrors the live site
     (removed pages and municipalities leave no orphan chunks); there is a brief
     window during the run where ``/bbsa`` has no results.

The state watermark is written only after a successful re-index, so a failed run is
retried on the next invocation.

Prerequisites: run with the backend virtualenv while ``azd``/``az``-logged-in with the
deployment env selected (currently ``rg-agentic-retrieval-nerilio``). ``azd`` must be on
PATH — the delete/index steps resolve Azure config and credentials via ``load_azd_env``.

Usage (from the repo root)::

    app/.venv/Scripts/python.exe app/backend/refresh_bbsa.py             # change-gated refresh
    app/.venv/Scripts/python.exe app/backend/refresh_bbsa.py --force     # reindex even if unchanged
    app/.venv/Scripts/python.exe app/backend/refresh_bbsa.py --check-only # report changed/not, do nothing
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
SCRAPER = REPO_ROOT / "scripts" / "scrape_bbsa.py"
BBSA_JSON = REPO_ROOT / "data" / "bbsa.json"
STATE_FILE = REPO_ROOT / "data" / "bbsa.state.json"
DELETE_SCRIPT = BACKEND_DIR / "delete_category_data.py"
PREPDOCS_SCRIPT = BACKEND_DIR / "prepdocs.py"
CATEGORY = "bbsa"
FEED_MARKER = "breitband.tirol"

# Reuse the scraper's watermark helper so all site-specific knowledge lives in one module.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from scrape_bbsa import DEFAULT_BASE_URL, fetch_remote_state  # noqa: E402


def log(message: str) -> None:
    print(f"[refresh_bbsa] {message}", flush=True)


def load_state() -> Optional[dict[str, Any]]:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        log(f"WARNING: could not read {STATE_FILE.name} ({error}); treating as changed.")
        return None


def save_state(remote_state: dict[str, Any], payload: dict[str, Any]) -> None:
    state = {
        "remote": remote_state,
        "bbsa_generated_at": payload.get("generated_at"),
        "doc_count": len(payload.get("documents") or []),
    }
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"Wrote watermark to {STATE_FILE.relative_to(REPO_ROOT)}")


def run_step(title: str, argv: list[str], cwd: Path) -> None:
    """Run a sub-step, streaming its output live; raise SystemExit on failure."""
    log(f"=> {title}")
    log(f"   $ {' '.join(argv)}  (cwd={cwd})")
    completed = subprocess.run(argv, cwd=str(cwd))
    if completed.returncode != 0:
        raise SystemExit(f"[refresh_bbsa] STEP FAILED: {title} (exit {completed.returncode}). Aborting.")


def load_scraped_payload() -> dict[str, Any]:
    """Read + lightly validate data/bbsa.json after scraping, before any destructive step."""
    try:
        payload = json.loads(BBSA_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise SystemExit(f"[refresh_bbsa] Could not read scraped {BBSA_JSON}: {error}")
    if not isinstance(payload, dict) or payload.get("feed") != FEED_MARKER:
        raise SystemExit(f"[refresh_bbsa] {BBSA_JSON.name} is missing the '{FEED_MARKER}' feed marker; aborting.")
    documents = payload.get("documents")
    if not isinstance(documents, list) or not documents:
        raise SystemExit(
            f"[refresh_bbsa] {BBSA_JSON.name} has no documents; aborting before delete to avoid wiping the index."
        )
    # Both halves must be present before the destructive delete+reindex: a feed missing the
    # municipality documents (or the statewide pages) would silently drop that half from the
    # index while looking like a successful refresh.
    gemeinde_count = sum(1 for doc in documents if isinstance(doc, dict) and doc.get("type") == "gemeinde")
    site_count = len(documents) - gemeinde_count
    if not gemeinde_count or not site_count:
        raise SystemExit(
            f"[refresh_bbsa] {BBSA_JSON.name} is missing one half of the feed "
            f"(site pages: {site_count}, municipalities: {gemeinde_count}); aborting before delete."
        )
    return payload


def describe_change(stored_remote: Optional[dict[str, Any]], remote_state: dict[str, Any]) -> None:
    """Log which part of the watermark moved, so a refresh is explainable after the fact."""
    if stored_remote is None:
        log("No previous watermark found (first run or missing state) -> treating as changed.")
        return
    for key in ("pages", "posts", "chrome_hash"):
        changed = stored_remote.get(key) != remote_state.get(key)
        log(f"  {key}: {'CHANGED' if changed else 'unchanged'}")
    stored_gemeinde = (stored_remote.get("gemeinde") or {}).get("modified") or {}
    current_gemeinde = (remote_state.get("gemeinde") or {}).get("modified") or {}
    added = sorted(set(current_gemeinde) - set(stored_gemeinde))
    removed = sorted(set(stored_gemeinde) - set(current_gemeinde))
    edited = sorted(slug for slug in set(stored_gemeinde) & set(current_gemeinde) if stored_gemeinde[slug] != current_gemeinde[slug])
    if not (added or removed or edited):
        log(f"  gemeinde: unchanged ({len(current_gemeinde)} municipalities)")
        return
    log(f"  gemeinde: CHANGED (added={added or '-'} removed={removed or '-'} edited={edited or '-'})")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape breitband.tirol and refresh the 'bbsa' category in Azure AI Search."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Site base URL (default: %(default)s)")
    parser.add_argument("--force", action="store_true", help="Re-scrape and re-index even if no change is detected")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only report whether breitband.tirol changed since the last refresh; do not scrape or index",
    )
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    # Step 1: change detection.
    log(f"Checking breitband.tirol ({base_url}) for changes ...")
    remote_state = fetch_remote_state(base_url)
    stored = load_state()
    stored_remote = stored.get("remote") if stored else None
    changed = stored_remote != remote_state
    describe_change(stored_remote, remote_state)
    log(f"Change detected: {changed}")

    if args.check_only:
        log("CHANGED" if changed else "UP-TO-DATE")
        return 0

    if not changed and not args.force:
        log("No changes since last successful refresh; nothing to do. Use --force to reindex anyway.")
        return 0

    # Step 2: scrape (non-destructive; leaves the existing index intact if it fails).
    run_step(
        "Scrape breitband.tirol -> data/bbsa.json",
        [sys.executable, str(SCRAPER), "--base-url", base_url],
        cwd=REPO_ROOT,
    )
    payload = load_scraped_payload()
    log(f"Scraped {len(payload['documents'])} documents.")

    # Step 3a: delete the existing 'bbsa' category (search docs + content/bbsa/ blobs).
    run_step(
        f"Delete category '{CATEGORY}' (search + blobs)", [sys.executable, str(DELETE_SCRIPT), CATEGORY], cwd=BACKEND_DIR
    )

    # Step 3b: re-index data/bbsa.json under category 'bbsa' via the custom bbsa parser.
    run_step(
        f"Index data/bbsa.json (category={CATEGORY})",
        [sys.executable, str(PREPDOCS_SCRIPT), str(BBSA_JSON), "--category", CATEGORY],
        cwd=BACKEND_DIR,
    )

    # Step 4: persist the watermark only after a clean re-index.
    save_state(remote_state, payload)
    log(f"DONE: breitband.tirol re-scraped and re-indexed under category '{CATEGORY}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
