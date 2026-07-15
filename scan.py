import os
import sys
import traceback
from collections import Counter

from dotenv import load_dotenv

import db
from compare import build_match_key, compare_libraries
from duplicates import find_duplicate_shows
from plex_client import get_library_sections, get_plex
from scanner import scan_library

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _with_match_key(shows):
    for show in shows:
        show["match_key"] = build_match_key(show["title"], show["year"])
    return shows


def run_scan(on_progress=None, show_cli_progress=True):
    with db.connect() as conn:
        run_id = db.start_scan_run(conn)
        try:
            plex = get_plex()
            low_section, high_section = get_library_sections(plex)

            low_shows = _with_match_key(scan_library(low_section, on_progress=on_progress, show_cli_progress=show_cli_progress))
            high_shows = _with_match_key(scan_library(high_section, on_progress=on_progress, show_cli_progress=show_cli_progress))

            comparisons = compare_libraries(low_shows, high_shows)
            duplicates = find_duplicate_shows(low_shows + high_shows)

            db.save_shows(conn, run_id, low_shows + high_shows)
            db.save_comparisons(conn, run_id, comparisons)
            db.save_duplicates(conn, run_id, duplicates)

            db.finish_scan_run(
                conn,
                run_id,
                status="success",
                low_show_count=len(low_shows),
                high_show_count=len(high_shows),
            )

            return {
                "run_id": run_id,
                "low_show_count": len(low_shows),
                "high_show_count": len(high_shows),
                "comparison_count": len(comparisons),
                "duplicate_count": len(duplicates),
                "status_counts": Counter(c["status"] for c in comparisons),
            }
        except Exception as exc:
            db.finish_scan_run(conn, run_id, status="error", error_message=str(exc))
            raise


def main():
    print("Plex Library Comparison Tool - Scan")
    print("=" * 60)
    try:
        summary = run_scan()
    except Exception:
        traceback.print_exc()
        sys.exit(1)

    counts = summary["status_counts"]
    print(f"Low library shows:  {summary['low_show_count']}")
    print(f"High library shows: {summary['high_show_count']}")
    print(f"Comparisons:        {summary['comparison_count']}")
    print(f"  match_complete    : {counts.get('match_complete', 0)}")
    print(f"  season_mismatch   : {counts.get('season_mismatch', 0)}")
    print(f"  missing_in_high   : {counts.get('missing_in_high', 0)}  (low-only)")
    print(f"  high_only         : {counts.get('high_only', 0)}")
    print(f"Duplicate groups:   {summary['duplicate_count']}")
    print("=" * 60)
    print(f"Scan run #{summary['run_id']} saved to {db.DB_PATH}")


if __name__ == "__main__":
    main()
