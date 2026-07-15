import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("PLEX_COMPARE_DB_PATH", os.path.join(BASE_DIR, "plex_compare.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    error_message TEXT,
    low_show_count INTEGER,
    high_show_count INTEGER
);

CREATE TABLE IF NOT EXISTS shows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_run_id INTEGER NOT NULL REFERENCES scan_runs(id),
    rating_key INTEGER NOT NULL,
    title TEXT NOT NULL,
    year INTEGER,
    library_name TEXT NOT NULL,
    plex_web_url TEXT,
    match_key TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shows_scan_run ON shows(scan_run_id);

CREATE TABLE IF NOT EXISTS seasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    show_id INTEGER NOT NULL REFERENCES shows(id),
    season_rating_key INTEGER,
    season_number INTEGER NOT NULL,
    season_title TEXT,
    episode_count INTEGER,
    episode_numbers TEXT
);
CREATE INDEX IF NOT EXISTS idx_seasons_show ON seasons(show_id);

CREATE TABLE IF NOT EXISTS comparisons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_run_id INTEGER NOT NULL REFERENCES scan_runs(id),
    title TEXT NOT NULL,
    year INTEGER,
    status TEXT NOT NULL,
    low_seasons TEXT NOT NULL,
    high_seasons TEXT NOT NULL,
    missing_in_high TEXT NOT NULL,
    missing_in_low TEXT NOT NULL,
    episode_mismatches TEXT NOT NULL DEFAULT '[]',
    low_exists INTEGER NOT NULL,
    high_exists INTEGER NOT NULL,
    plex_url_low TEXT,
    plex_url_high TEXT
);
CREATE INDEX IF NOT EXISTS idx_comparisons_scan_run ON comparisons(scan_run_id, status);

CREATE TABLE IF NOT EXISTS duplicates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_run_id INTEGER NOT NULL REFERENCES scan_runs(id),
    library_name TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    year INTEGER,
    count INTEGER NOT NULL,
    items_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_duplicates_scan_run ON duplicates(scan_run_id);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def connect():
    conn = get_connection()
    init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


def _now():
    return datetime.now(timezone.utc).isoformat()


def start_scan_run(conn):
    cur = conn.execute(
        "INSERT INTO scan_runs (started_at, status) VALUES (?, 'running')",
        (_now(),),
    )
    conn.commit()
    return cur.lastrowid


def finish_scan_run(conn, run_id, status, error_message=None, low_show_count=None, high_show_count=None):
    conn.execute(
        """UPDATE scan_runs
           SET finished_at = ?, status = ?, error_message = ?,
               low_show_count = ?, high_show_count = ?
           WHERE id = ?""",
        (_now(), status, error_message, low_show_count, high_show_count, run_id),
    )
    conn.commit()


def save_shows(conn, run_id, shows_with_match_key):
    for show in shows_with_match_key:
        cur = conn.execute(
            """INSERT INTO shows (scan_run_id, rating_key, title, year, library_name, plex_web_url, match_key)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                show["rating_key"],
                show["title"],
                show["year"],
                show["library_name"],
                show["plex_web_url"],
                show["match_key"],
            ),
        )
        show_id = cur.lastrowid
        for season in show["seasons"]:
            conn.execute(
                """INSERT INTO seasons
                   (show_id, season_rating_key, season_number, season_title, episode_count, episode_numbers)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    show_id,
                    season["season_rating_key"],
                    season["season_number"],
                    season["season_title"],
                    season["episode_count"],
                    json.dumps(season["episode_numbers"]),
                ),
            )
    conn.commit()


def save_comparisons(conn, run_id, comparisons):
    for c in comparisons:
        conn.execute(
            """INSERT INTO comparisons
               (scan_run_id, title, year, status, low_seasons, high_seasons,
                missing_in_high, missing_in_low, episode_mismatches, low_exists, high_exists,
                plex_url_low, plex_url_high)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                c["title"],
                c["year"],
                c["status"],
                json.dumps(c["low_seasons"]),
                json.dumps(c["high_seasons"]),
                json.dumps(c["missing_in_high"]),
                json.dumps(c["missing_in_low"]),
                json.dumps(c["episode_mismatches"]),
                int(c["low_exists"]),
                int(c["high_exists"]),
                c.get("plex_url_low"),
                c.get("plex_url_high"),
            ),
        )
    conn.commit()


def save_duplicates(conn, run_id, duplicates):
    for d in duplicates:
        conn.execute(
            """INSERT INTO duplicates (scan_run_id, library_name, normalized_title, year, count, items_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                d["library_name"],
                d["normalized_title"],
                d["year"],
                d["count"],
                json.dumps([
                    {
                        "rating_key": item["rating_key"],
                        "title": item["title"],
                        "year": item["year"],
                        "plex_web_url": item["plex_web_url"],
                    }
                    for item in d["items"]
                ]),
            ),
        )
    conn.commit()


def get_latest_scan_run(conn, status="success"):
    row = conn.execute(
        "SELECT * FROM scan_runs WHERE status = ? ORDER BY id DESC LIMIT 1",
        (status,),
    ).fetchone()
    return dict(row) if row else None


def get_last_scan_run(conn):
    row = conn.execute("SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def _row_to_comparison(row):
    d = dict(row)
    d["low_seasons"] = json.loads(d["low_seasons"])
    d["high_seasons"] = json.loads(d["high_seasons"])
    d["missing_in_high"] = json.loads(d["missing_in_high"])
    d["missing_in_low"] = json.loads(d["missing_in_low"])
    d["episode_mismatches"] = json.loads(d["episode_mismatches"])
    return d


def get_comparisons(conn, run_id, statuses=None):
    if statuses:
        placeholders = ",".join("?" for _ in statuses)
        rows = conn.execute(
            f"SELECT * FROM comparisons WHERE scan_run_id = ? AND status IN ({placeholders}) ORDER BY title",
            (run_id, *statuses),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM comparisons WHERE scan_run_id = ? ORDER BY title",
            (run_id,),
        ).fetchall()
    return [_row_to_comparison(r) for r in rows]


def get_episode_mismatches(conn, run_id):
    """Flatten per-show episode_mismatches into one row per (show, season) gap."""
    rows = conn.execute(
        "SELECT * FROM comparisons WHERE scan_run_id = ? AND episode_mismatches != '[]' ORDER BY title",
        (run_id,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        for m in json.loads(d["episode_mismatches"]):
            result.append({
                "title": d["title"],
                "year": d["year"],
                "season_number": m["season_number"],
                "low_episode_count": m["low_episode_count"],
                "high_episode_count": m["high_episode_count"],
                "missing_in_high": m["missing_in_high"],
                "missing_in_low": m["missing_in_low"],
                "plex_url_low": d["plex_url_low"],
                "plex_url_high": d["plex_url_high"],
            })
    return result


def get_duplicates(conn, run_id):
    rows = conn.execute(
        "SELECT * FROM duplicates WHERE scan_run_id = ? ORDER BY normalized_title",
        (run_id,),
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["items"] = json.loads(d["items_json"])
        del d["items_json"]
        result.append(d)
    return result
