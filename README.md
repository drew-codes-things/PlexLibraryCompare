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
                ->  serves web dashboard (6 tabs) reading plex_compare.db
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
- Its own sign-in, on by default (see [First run and sign-in](#first-run-and-sign-in));
  HTTP Basic Auth instead when `WEB_USERNAME` / `WEB_PASSWORD` are set
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
and `WEB_PASSWORD` empty to use the app's own sign-in.

### 3. Start the app

```bash
python app.py
```

Then open `http://127.0.0.1:5001` in your browser and make the owner
account (see below). The first time you run this, there's no data yet, so it kicks off a scan in the background
automatically - refresh the page in a minute or two once it finishes. After
that, use the **Scan Now** button whenever you want fresher data. That's the
whole workflow - you never need to run `scan.py` by hand unless you want it
on a Task Scheduler/cron schedule instead (see [Windows Deployment](#windows-deployment)).

### First run and sign-in

Plex Library Compare has its own sign-in, switched on by default (see
"Other ways to sign in" below for the alternatives). There is one owner
account and no sign-up page.

1. Start it (`python app.py`) and open `http://127.0.0.1:5001`. With no
   account yet every page goes to **Set up**.
2. The app writes a one-time setup code to its log when it starts, a line
   like `no owner account yet: open /setup and enter the setup code ...`.
   Enter that code, a user name and a password (10 characters or more,
   twice). The code stops anyone else who reaches the page first from
   making the account, and it works once: if the owner file is ever
   deleted, the next visit to **Set up** writes a new code to the log.
3. After that, every page goes to **Sign in** until you sign in. A session
   lasts 30 days. `/signout` signs out on every device.

How it is protected:

- The password is stored as an scrypt hash in `owner.json` next to
  `plex_compare.db` (mode 600), never in plain text.
- 5 wrong passwords or setup codes from one address within 15 minutes lock
  that address out for the rest of the 15 minutes (`429`). Attempts sent
  at once are counted before they are checked, IPv6 addresses count by
  their `/64` network, and after 100 failures from everywhere within 15
  minutes each address gets one try and each network three (IPv4 by `/24`,
  IPv6 by `/48`). A right password from a locked address is refused too.
- During such an attack one wrong password from a neighbour on the same
  provider network does not keep your new browser out: that takes three
  wrong passwords within 15 minutes from three of their addresses (IPv4)
  or three of their home lines (IPv6, where a line's whole `/56` counts as
  one address).
- A browser that has signed in before keeps a signed device cookie and has
  its own 5 tries, so a stranger who locks out your address (or the
  address of the proxy in front) cannot lock you out of that browser.
  During an attack from many networks that browser is the way in.
  Making a new owner account ends every device cookie of the old one.
- The session cookie is `HttpOnly`, `SameSite=Lax` and signed with the app's
  secret key (`SECRET_KEY`, or `secret_key` next to `plex_compare.db`, made
  on first start, mode 600). It is `Secure` everywhere except plain `http`
  on `localhost`, `127.0.0.1` or `[::1]` (`SECURE_COOKIES=auto`). On a plain
  `http` address on your home network the browser drops a `Secure` cookie
  and the sign-in page says so: use https, or set `SECURE_COOKIES=false`
  there.
- Forget the password? Stop the app, delete `owner.json` next to
  `plex_compare.db`, start it again and set up a new owner with the new
  setup code from the log. Your scans stay.

Behind a reverse proxy for https, with the own sign-in still on: list the
proxy's address in `TRUSTED_PROXIES` so the lockout counts each visitor's
address from `X-Forwarded-For` instead of the proxy's (the header is read
only from those addresses), and put the public host name in
`ALLOWED_HOSTS`. By default the own sign-in answers only on `localhost`,
`127.0.0.1`, `[::1]`, IP addresses and this machine's own name; any other
`Host` gets `421`, so a web page cannot reach a copy on your machine by
DNS rebinding.

Other ways to sign in:

- `WEB_USERNAME` and `WEB_PASSWORD` set: HTTP Basic Auth with those two
  values instead (no setup page, no lockout).
- `ALLOW_INSECURE=true`: the app has no sign-in at all and leaves it to a
  reverse proxy in front that signs people in. Never set it on an address
  other people can reach directly. The host name check above stays on in
  this mode, so a web page that rebinds its own name to your machine still
  gets `421`. **Upgrading a proxy setup that already used
  `ALLOW_INSECURE=true`:** put the host name the proxy sends in
  `ALLOWED_HOSTS`, or every page answers `421`.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PLEX_TOKEN` | required | Your personal Plex `X-Plex-Token` |
| `PLEX_SERVER_NAME` | required | Name of your Plex server resource (as shown in your Plex account) |
| `LOW_LIBRARY_NAME` | `Anime Shows` | First show library section name |
| `HIGH_LIBRARY_NAME` | `Anime Shows - High` | Second show library section name |
| `WEB_USERNAME` | _(empty)_ | HTTP Basic Auth username instead of the own sign-in (leave blank to use the own sign-in) |
| `WEB_PASSWORD` | _(empty)_ | HTTP Basic Auth password |
| `BIND_HOST` | `127.0.0.1` | Host to bind the Flask server to |
| `PORT` | `5001` | Port to bind the Flask server to |
| `ALLOW_INSECURE` | `false` | Set `true` only behind a reverse proxy that signs people in: the app then has no sign-in of its own but keeps the `ALLOWED_HOSTS` check |
| `SECURE_COOKIES` | `auto` | The own sign-in's cookie is `Secure` except on plain `http` to `localhost`, `127.0.0.1` or `[::1]`; `true` or `false` force it |
| `TRUSTED_PROXIES` | _(empty)_ | Own sign-in only: addresses or private networks of a reverse proxy in front, comma separated; their `X-Forwarded-For` gives the visitor's address to the lockout |
| `ALLOWED_HOSTS` | _(empty)_ | Own sign-in and `ALLOW_INSECURE=true` (not Basic Auth): the only host names the app answers on, comma separated (others get 421). Empty: `localhost`, `127.0.0.1`, `[::1]`, IP addresses and this machine's own name |
| `SESSION_COOKIE_SECURE` | `false` | Mark the session cookie `Secure` (only enable if served over HTTPS, e.g. behind a TLS-terminating reverse proxy) |
| `SECRET_KEY` | _(random per start)_ | Flask session key and the key that signs the own sign-in's cookie. Set it to any long random string so the CSRF token behind **Scan Now** survives restarts. Without it the sign-in key is kept in `secret_key` next to `plex_compare.db`. With the own sign-in a key shorter than 32 bytes stops the app at start-up |
| `PLEX_COMPARE_DB_PATH` | `plex_compare.db` (next to `db.py`) | Override where the SQLite database file is stored. The owner account (`owner.json`) and `secret_key` live in the same folder |

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
