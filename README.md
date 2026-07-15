<div align="center">

# Plex Library Compare

**Scans two Plex show libraries (a low-bitrate and a high-bitrate copy), compares them season-by-season, and serves a searchable dashboard of mismatches and duplicates. Works with any two show libraries - defaults to comparing anime libraries.**

[![Python](https://img.shields.io/badge/python-3.9+-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-web%20ui-lightgrey?style=flat-square&logo=flask)](https://flask.palletsprojects.com/)

</div>

---

## Overview

**Run it with one command: `python app.py`.** It connects to Plex via
`plexapi`, scans two library sections, and compares which shows and seasons
exist in each. Point `LOW_LIBRARY_NAME` / `HIGH_LIBRARY_NAME` at any two Plex
**show** libraries you want to compare - regular TV, anime, whatever - they
default to `Anime Shows` / `Anime Shows - High`. The scan-and-compare logic
lives in `scan.py`, which `app.py` calls automatically in the background (on
first run, and whenever you click **Scan Now**), writing results to a local
SQLite database (`plex_compare.db`). The dashboard reads that database:
season mismatches, high-only shows, low-only shows, and duplicate entries,
each with search/sort/pagination and "Copy title" / "Open in Plex" actions.

Note: the comparison is season-based, so it only applies to **show/series**
libraries (anything with `.seasons()` in Plex) - not movie libraries.

---

## How It Works

```
python app.py  ->  runs scan.py in the background (first run + "Scan Now")
                ->  scan both Plex libraries -> compare seasons -> plex_compare.db
                ->  serves web dashboard (5 tabs) reading plex_compare.db
```

### scan.py

- Connects to Plex using `PLEX_TOKEN` (your personal Plex account token) and
  `PLEX_SERVER_NAME` (resolved via `MyPlexAccount`, so you don't need to know
  the server's IP/URL)
- Resolves the two library sections named by `LOW_LIBRARY_NAME` and
  `HIGH_LIBRARY_NAME`
- Scans every show and season in both libraries, with a `tqdm` progress bar
  per library so you can see it's working on large libraries
- Normalizes titles (case, punctuation, whitespace, unicode) and matches shows
  across libraries by title + year
- Computes, per show: `match_complete`, `season_mismatch`, `missing_in_high`
  (exists only in the low library), or `high_only` (exists only in the high
  library)
- For seasons that exist in both libraries, compares exact episode numbers
  (not just counts) to find episode-level gaps - e.g. low has episodes 1-25
  but high only has 1-20, so 21-25 are flagged as missing in high
- Finds duplicate shows within the same library (same normalized title + year)
- Writes everything to `plex_compare.db` under one `scan_runs` row, so each
  scan is a clean, inspectable snapshot

You normally don't need to run this directly - `app.py` runs it for you (see
below). It's here as a standalone entrypoint for scheduled scans (e.g.
Windows Task Scheduler, cron) so the database stays fresh without needing the
web UI open:

```bash
python scan.py
```

### app.py

**This is the only command you need day-to-day: `python app.py`.**

- On startup, if the database has no completed scan yet, it automatically
  kicks off a scan in the background (same `run_scan()` as `scan.py`), so a
  first-time run doesn't need a separate manual step
- Flask server binding to `BIND_HOST` (default `127.0.0.1`) on `PORT`
  (default `5001`)
- Six tabs, each a sortable/searchable/paginated table read from the latest
  successful scan:
  - **Missing Seasons** - shows present in both libraries, with per-season
    match status
  - **Episode Gaps** - seasons present in both libraries but with a different
    episode count, listing the exact episode numbers missing on each side
  - **High Only** - shows that exist only in the high-bitrate library
  - **Low Only** - shows that exist only in the low-bitrate library
  - **Duplicates** - shows that appear more than once in the same library
  - **Scan Status** - last run time, show counts, and any error
- **Scan Now** button in the header triggers another background scan without
  blocking the UI, whenever you want fresher data - a live progress bar next
  to the button (polling `/scan-progress`) shows which library is being
  scanned and how far through it is, on every page, and the page auto-reloads
  once the scan finishes
- Copy title (clipboard) and Open in Plex (direct deep link via
  `getWebURL()`) actions on every row
- Optional HTTP Basic Auth via `WEB_USERNAME` / `WEB_PASSWORD` - leave both
  blank to disable it entirely. The server **refuses to bind to a
  non-loopback interface without auth** (set `ALLOW_INSECURE=true` only if a
  reverse proxy handles auth)
- Security headers (CSP, `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`) on every response; CSRF token on the scan-trigger form;
  a `/health` endpoint returns `{"status":"ok"}`

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

Requires: `flask`, `plexapi`, `python-dotenv`, `markupsafe`, `tqdm`

### 2. Configure environment

Copy `.env.example` to `.env` and fill in your values:

```env
PLEX_TOKEN=your_plex_user_token_here
PLEX_SERVER_NAME=YourServerName

LOW_LIBRARY_NAME=Anime Shows
HIGH_LIBRARY_NAME=Anime Shows - High

WEB_USERNAME=
WEB_PASSWORD=
BIND_HOST=127.0.0.1
PORT=5001
ALLOW_INSECURE=false
```

`LOW_LIBRARY_NAME`/`HIGH_LIBRARY_NAME` can point at any two show libraries -
e.g. `TV Shows` / `TV Shows - High` - not just anime. Leave `WEB_USERNAME`
and `WEB_PASSWORD` empty to disable HTTP Basic Auth (fine when bound to
`127.0.0.1`).

### 3. Start the app

```bash
python app.py
```

Then open `http://127.0.0.1:5001` in your browser. The first time you run
this, there's no data yet, so it kicks off a scan in the background
automatically - refresh the page in a minute or two once it finishes. After
that, use the **Scan Now** button whenever you want fresher data. That's the
whole workflow - you never need to run `scan.py` by hand unless you want it
on a Task Scheduler/cron schedule instead (see [Windows Deployment](#windows-deployment)).

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PLEX_TOKEN` | required | Your personal Plex `X-Plex-Token` |
| `PLEX_SERVER_NAME` | required | Name of your Plex server resource (as shown in your Plex account) |
| `LOW_LIBRARY_NAME` | `Anime Shows` | First show library section name |
| `HIGH_LIBRARY_NAME` | `Anime Shows - High` | Second show library section name |
| `WEB_USERNAME` | _(empty)_ | HTTP Basic Auth username (leave blank to disable) |
| `WEB_PASSWORD` | _(empty)_ | HTTP Basic Auth password |
| `BIND_HOST` | `127.0.0.1` | Host to bind the Flask server to |
| `PORT` | `5001` | Port to bind the Flask server to |
| `ALLOW_INSECURE` | `false` | Allow non-loopback bind without auth (reverse proxy setups only) |
| `SESSION_COOKIE_SECURE` | `false` | Mark the session cookie `Secure` (only enable if served over HTTPS, e.g. behind a TLS-terminating reverse proxy) |
| `PLEX_COMPARE_DB_PATH` | `plex_compare.db` (next to `db.py`) | Override where the SQLite database file is stored |

---

## Windows Deployment

1. Install Python, create a venv, `pip install -r requirements.txt`
2. Set `PLEX_TOKEN` / `PLEX_SERVER_NAME` and the rest in `.env`
3. Run `python app.py` continuously (or as a Windows service via NSSM) - that's
   the only process you need; it scans on first run and whenever you click
   **Scan Now**

Optional: if you'd rather have fresh data waiting on a schedule instead of
clicking Scan Now, add a Task Scheduler entry that runs `python scan.py` on
its own (e.g. nightly). `app.py` always reads whatever the most recent
successful scan wrote, regardless of which process triggered it.

---

## License

MIT
