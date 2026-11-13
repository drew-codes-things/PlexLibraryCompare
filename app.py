import os
import secrets
import sys
import threading
from functools import wraps
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, redirect, render_template_string, request, session
from markupsafe import Markup

import db
from scan import run_scan

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__)
app.secret_key = (os.getenv("SECRET_KEY") or "").strip() or secrets.token_hex(32)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = (os.getenv("SESSION_COOKIE_SECURE") or "false").strip().lower() == "true"

WEB_USERNAME = (os.getenv("WEB_USERNAME") or "").strip()
WEB_PASSWORD = (os.getenv("WEB_PASSWORD") or "").strip()

_scan_lock = threading.Lock()
_scan_in_progress = False
_scan_progress = {"active": False, "library": None, "scanned": 0, "total": 0}


def _update_scan_progress(library, scanned, total):
    with _scan_lock:
        _scan_progress["library"] = library
        _scan_progress["scanned"] = scanned
        _scan_progress["total"] = total

NAV_TABS = [
    ("missing-seasons", "Missing Seasons"),
    ("episode-gaps", "Episode Gaps"),
    ("high-only", "High Only"),
    ("low-only", "Low Only"),
    ("duplicates", "Duplicates"),
    ("scan-status", "Scan Status"),
]


def auth_enabled():
    return bool(WEB_USERNAME and WEB_PASSWORD)


def constant_time_equals(left, right):
    return secrets.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def requires_auth(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not auth_enabled():
            return view_func(*args, **kwargs)
        auth = request.authorization
        if auth and constant_time_equals(auth.username or "", WEB_USERNAME) and constant_time_equals(auth.password or "", WEB_PASSWORD):
            return view_func(*args, **kwargs)
        return Response(
            "Authentication required",
            status=401,
            headers={"WWW-Authenticate": 'Basic realm="Plex Library Compare"'},
        )
    return wrapped


@app.after_request
def set_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; script-src 'self' 'unsafe-inline'",
    )
    return resp


def get_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def has_valid_csrf(submitted_token):
    expected = session.get("_csrf_token")
    if not expected or not submitted_token:
        return False
    return constant_time_equals(expected, submitted_token)


@app.route("/health")
def health():
    return Response('{"status": "ok"}', mimetype="application/json")


CSS = """
@font-face { font-family: "IBM Plex Sans"; font-style: normal; font-weight: 400; font-display: swap; src: url(/static/fonts/ibm-plex-sans-latin-400-normal.woff2) format("woff2"); }
@font-face { font-family: "IBM Plex Sans"; font-style: normal; font-weight: 500; font-display: swap; src: url(/static/fonts/ibm-plex-sans-latin-500-normal.woff2) format("woff2"); }
@font-face { font-family: "IBM Plex Sans"; font-style: normal; font-weight: 600; font-display: swap; src: url(/static/fonts/ibm-plex-sans-latin-600-normal.woff2) format("woff2"); }
@font-face { font-family: "IBM Plex Mono"; font-style: normal; font-weight: 400; font-display: swap; src: url(/static/fonts/ibm-plex-mono-latin-400-normal.woff2) format("woff2"); }
:root {
    color-scheme: dark;
    --bg: #19191c;
    --surface: #222226;
    --raised: #2c2c31;
    --text: #eeeef0;
    --muted: #b4b4bd;
    --faint: #9a9aa5;
    --accent: #e5383b;
    --accent-fill: #d52c30;
    --accent-fill-hover: #e5383b;
    --accent-text: #ff7a7c;
    --on-accent: #ffffff;
    --ok: #5fd990;
    --warn: #f2b552;
    --line: color-mix(in srgb, var(--text) 10%, transparent);
    --line-strong: color-mix(in srgb, var(--text) 18%, transparent);
    --line-control: color-mix(in srgb, var(--text) 46%, transparent);
    --hover: color-mix(in srgb, var(--text) 7%, transparent);
    --accent-tint: color-mix(in srgb, var(--accent) 14%, transparent);
    --ok-tint: color-mix(in srgb, var(--ok) 12%, transparent);
    --warn-tint: color-mix(in srgb, var(--warn) 12%, transparent);
    --r-xs: 6px;
    --r-md: 12px;
    --r-lg: 16px;
    --r-pill: 999px;
    --control-h: 36px;
    --control-h-sm: 28px;
    --touch: 44px;
    --sans: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
    --mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
    --fs-xs: .75rem;
    --fs-sm: .8125rem;
    --fs-md: .875rem;
    --fs-lg: .9375rem;
    --dur: .16s;
    --dur-rise: .24s;
    --ease: cubic-bezier(.2, .7, .3, 1);
    --focus: color-mix(in srgb, var(--accent-text) 72%, transparent);
    --ring: 0 0 0 3px var(--accent-tint);
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; text-size-adjust: 100%; background: var(--bg); }
body {
    font-family: var(--sans);
    font-size: var(--fs-md);
    background: var(--bg);
    min-height: 100vh;
    color: var(--text);
    margin: 0;
    padding: 0;
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
    -webkit-tap-highlight-color: transparent;
}
::selection { background: color-mix(in srgb, var(--accent) 35%, transparent); }
* { scrollbar-width: thin; scrollbar-color: var(--line-strong) transparent; }
code { font-family: var(--mono); font-size: .88em; padding: 2px 6px; border-radius: var(--r-xs); background: var(--raised); }
.warning-banner, .success-banner {
    border-radius: var(--r-lg);
    padding: 12px 16px;
    margin: 0 0 16px 0;
    font-size: var(--fs-md);
}
.warning-banner { background: var(--accent-tint); color: var(--accent-text); }
.success-banner { background: var(--ok-tint); color: var(--ok); }
h1, h2 { font-weight: 600; letter-spacing: -.012em; color: var(--text); }
h2 {
    font-size: var(--fs-lg);
    margin-top: 0;
    margin-bottom: 12px;
}
.section {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: var(--r-lg);
    margin-bottom: 16px;
    animation: rise-in var(--dur-rise) var(--ease);
}
a { color: var(--accent-text); text-decoration: none; transition: color var(--dur) var(--ease); }
a:hover { color: var(--text); }
.btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: var(--control-h);
    background: var(--accent-fill);
    color: var(--on-accent);
    border: 1px solid transparent;
    border-radius: var(--r-pill);
    cursor: pointer;
    font: 600 var(--fs-sm) var(--sans);
    white-space: nowrap;
    text-decoration: none;
    transition: background-color var(--dur) var(--ease), color var(--dur) var(--ease), transform var(--dur) var(--ease);
}
.btn:hover { background: var(--accent-fill-hover); color: var(--on-accent); }
.btn:active:not(:disabled) { transform: scale(.97); }
.btn:disabled { opacity: .45; cursor: not-allowed; }
.btn-secondary, td .btn { background: transparent; border-color: var(--line-strong); color: var(--text); font-weight: 500; }
.btn-secondary:hover, td .btn:hover { background: var(--hover); color: var(--text); }
td .btn { height: var(--control-h-sm); padding: 0 12px; font-size: var(--fs-xs); }
input[type=text], input[type=search] {
    display: block;
    height: var(--control-h);
    background: var(--bg);
    border: 1px solid var(--line-strong);
    color: var(--text);
    padding: 0 16px;
    border-radius: var(--r-pill);
    font: var(--fs-sm) var(--sans);
    width: 100%;
    min-width: 0;
    margin-bottom: 16px;
    appearance: none;
    -webkit-appearance: none;
    outline: none;
    transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
input[type=text]::placeholder, input[type=search]::placeholder { color: var(--faint); opacity: 1; }
input[type=text]:hover, input[type=search]:hover { border-color: var(--line-control); }
input[type=text]:focus, input[type=search]:focus { border-color: var(--focus); box-shadow: var(--ring); }
table { width: 100%; border-collapse: collapse; }
thead tr { border-bottom: 1px solid var(--line-strong); }
th {
    text-align: left;
    color: var(--faint);
    font-weight: 500;
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
    font-size: var(--fs-xs);
    transition: color var(--dur) var(--ease);
}
th:hover { color: var(--text); }
tbody tr { border-bottom: 1px solid var(--line); transition: background-color var(--dur) var(--ease); }
tbody tr:last-child { border-bottom: none; }
tbody tr:hover { background: var(--hover); }
td { vertical-align: middle; }
.badge {
    border: 1px solid var(--line-strong);
    border-radius: var(--r-pill);
    font-size: var(--fs-xs);
    color: var(--muted);
    display: inline-block;
    white-space: nowrap;
}
.stat-box { background: var(--bg); border: 1px solid var(--line); border-radius: var(--r-lg); padding: 16px; text-align: center; }
.stat-box .val { font-size: 1.5rem; font-weight: 600; letter-spacing: -.02em; color: var(--text); }
.stat-box .lbl { font-size: var(--fs-xs); color: var(--faint); margin-top: 4px; }
.pagination { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 16px; align-items: center; }
.page-btn {
    min-width: var(--control-h-sm);
    height: var(--control-h-sm);
    background: transparent;
    color: var(--muted);
    border: 1px solid var(--line-strong);
    border-radius: var(--r-pill);
    cursor: pointer;
    font: 500 var(--fs-xs) var(--sans);
    transition: background-color var(--dur) var(--ease), color var(--dur) var(--ease);
}
.page-btn.active { background: var(--accent-fill); border-color: transparent; color: var(--on-accent); }
.page-btn:hover:not(.active) { background: var(--hover); color: var(--text); }
.topbar {
    display: flex; align-items: center; gap: 16px;
    padding: calc(14px + env(safe-area-inset-top)) 24px 14px;
    background: var(--bg);
    border-bottom: 1px solid var(--line);
}
.topbar h1 { margin: 0; font-size: 1.0625rem; font-weight: 600; color: var(--text); }
.wordmark-accent { color: var(--accent-text); }
.topbar .header-sub { color: var(--muted); font-size: var(--fs-sm); margin: 2px 0 0; }
.empty-state { color: var(--muted); padding: 16px; border: 1px dashed var(--line-strong); border-radius: var(--r-lg); text-align: center; }

.container { max-width: 1400px; margin: 0 auto; padding: 0 24px calc(64px + env(safe-area-inset-bottom)); }
.section { padding: 24px; }
.btn { padding: 0 16px; }
th { padding: 0 8px 8px; }
td { padding: 10px 8px; font-size: var(--fs-sm); }
th:first-child, td:first-child { padding-left: 0; }
th:last-child, td:last-child { padding-right: 0; }
.badge { padding: 1px 8px; margin: 1px; }
.badge-missing { border-color: transparent; background: var(--accent-tint); color: var(--accent-text); }
.status-pill { display: inline-block; border-radius: var(--r-pill); padding: 2px 10px; font-size: var(--fs-xs); font-weight: 500; white-space: nowrap; }
.status-match_complete { background: var(--ok-tint); color: var(--ok); }
.status-season_mismatch { background: var(--warn-tint); color: var(--warn); }
.status-high_only, .status-missing_in_high { border: 1px solid var(--line-strong); color: var(--muted); }
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 12px; }
.page-btn { padding: 0 10px; }
.topbar { justify-content: space-between; flex-wrap: wrap; margin: 0 0 24px; }
.nav-tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px; }
.nav-tab {
    display: inline-flex;
    align-items: center;
    height: var(--control-h);
    border: 1px solid transparent;
    color: var(--muted);
    padding: 0 16px;
    border-radius: var(--r-pill);
    font-size: var(--fs-sm);
    font-weight: 500;
    transition: background-color var(--dur) var(--ease), color var(--dur) var(--ease);
}
.nav-tab.active { background: var(--raised); border-color: var(--line-strong); color: var(--text); }
.nav-tab:hover:not(.active) { background: var(--hover); color: var(--text); }
.scan-controls { display: flex; align-items: center; gap: 12px; }
.scan-progress-wrap {
    display: none;
    align-items: center;
    gap: 12px;
    font-size: var(--fs-sm);
    color: var(--muted);
}
.scan-progress-wrap.active { display: flex; }
.scan-progress-track { width: 140px; height: 4px; background: var(--line-strong); border-radius: var(--r-pill); overflow: hidden; }
.scan-progress-fill { height: 100%; background: var(--accent-fill); width: 0%; transition: width .3s var(--ease); }
@keyframes rise-in { from { opacity: 0; transform: translateY(8px); } }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .001ms !important; animation-iteration-count: 1 !important; transition-duration: .001ms !important; }
}
:focus { outline: none; }
:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
@media (max-width: 800px) { .stat-grid { grid-template-columns: 1fr 1fr; } }
@media (max-width: 640px) {
    .topbar { padding-left: 16px; padding-right: 16px; }
    .container { padding-left: 16px; padding-right: 16px; }
    .section { padding: 20px 16px; }
    .nav-tabs { flex-wrap: nowrap; overflow-x: auto; margin-left: -16px; margin-right: -16px; padding: 0 16px; }
    .nav-tab { flex-shrink: 0; }
    table { display: block; overflow-x: auto; }
    td { white-space: nowrap; }
}
@media (max-width: 820px), (pointer: coarse) {
    input[type=text], input[type=search] { font-size: 16px; }
    input[type=text], input[type=search], .btn, td .btn, .nav-tab, .page-btn { height: var(--touch); }
    .page-btn { min-width: var(--touch); }
}
@media (max-width: 820px), (pointer: coarse) {
    input[type=text], input[type=search] { font-size: 16px; }
    .btn, .page-btn { min-height: 44px; }
    .nav-tab { display: inline-flex; align-items: center; min-height: 44px; }
}
"""

TABLE_JS = """
const PAGE_SIZE = 50;
let currentPage = 1;
let sortCol = -1;
let sortAsc = true;
let visibleRows = [];

function getAllRows() {
  return Array.from(document.querySelectorAll('#data-table tbody tr'));
}

function filterTable() {
  const box = document.getElementById('search-box');
  const q = box ? box.value.toLowerCase() : '';
  visibleRows = getAllRows().filter(row => {
    const match = row.dataset.search.includes(q);
    row.style.display = match ? '' : 'none';
    return match;
  });
  currentPage = 1;
  paginate();
}

function paginate() {
  const start = (currentPage - 1) * PAGE_SIZE;
  visibleRows.forEach((row, i) => {
    row.style.display = (i >= start && i < start + PAGE_SIZE) ? '' : 'none';
  });
  renderPagination();
}

function renderPagination() {
  const total = visibleRows.length;
  const pages = Math.ceil(total / PAGE_SIZE);
  const el = document.getElementById('pagination');
  if (!el) return;
  if (pages <= 1) { el.innerHTML = `<span style="color:var(--faint);font-size:var(--fs-sm)">${total} results</span>`; return; }
  let html = `<span style="color:var(--faint);font-size:var(--fs-sm)">${total} results</span>`;
  for (let p = 1; p <= pages; p++) {
    html += `<button class="page-btn${p === currentPage ? ' active' : ''}" onclick="goPage(${p})">${p}</button>`;
  }
  el.innerHTML = html;
}

function goPage(p) {
  currentPage = p;
  paginate();
  window.scrollTo({top: 0, behavior: 'smooth'});
}

function sortTable(col) {
  if (sortCol === col) { sortAsc = !sortAsc; } else { sortCol = col; sortAsc = true; }
  const tbody = document.querySelector('#data-table tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  rows.sort((a, b) => {
    let av = a.cells[col].textContent.trim();
    let bv = b.cells[col].textContent.trim();
    const an = parseFloat(av), bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) { av = an; bv = bn; }
    if (av < bv) return sortAsc ? -1 : 1;
    if (av > bv) return sortAsc ? 1 : -1;
    return 0;
  });
  rows.forEach(r => tbody.appendChild(r));
  filterTable();
}

function copyTitle(title) {
  navigator.clipboard.writeText(title);
}

const searchBox = document.getElementById('search-box');
if (searchBox) searchBox.addEventListener('input', filterTable);
visibleRows = getAllRows();
paginate();
"""

BASE_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ page_title }} - Plex Library Compare</title>
    <style>{{ css }}</style>
</head>
<body>
<header class="topbar">
    <div>
        <h1>Plex Library <span class="wordmark-accent">Compare</span></h1>
        <p class="header-sub">{{ header_sub }}</p>
    </div>
    <div class="scan-controls">
        <div class="scan-progress-wrap" id="scan-progress-wrap">
            <span id="scan-progress-label">Scanning...</span>
            <div class="scan-progress-track"><div class="scan-progress-fill" id="scan-progress-fill"></div></div>
        </div>
        <form method="post" action="/scan" id="scan-form">
            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
            <button type="submit" class="btn" id="scan-btn">Scan Now</button>
        </form>
    </div>
</header>
<div class="container">
{% if scan_message %}
<div class="{{ 'warning-banner' if scan_message_kind == 'warning' else 'success-banner' }}">{{ scan_message }}</div>
{% endif %}
<div class="nav-tabs">
{% for slug, label in nav_tabs %}
  <a class="nav-tab{{ ' active' if slug == active_tab else '' }}" href="/{{ slug }}">{{ label }}</a>
{% endfor %}
</div>
{{ content }}
</div>
<script>{{ scan_progress_js }}</script>
</body>
</html>
"""

SCAN_PROGRESS_JS = """
(function() {
  const wrap = document.getElementById('scan-progress-wrap');
  const fill = document.getElementById('scan-progress-fill');
  const label = document.getElementById('scan-progress-label');
  const btn = document.getElementById('scan-btn');
  const form = document.getElementById('scan-form');
  let wasActive = false;

  function render(data) {
    if (data.active) {
      wasActive = true;
      wrap.classList.add('active');
      btn.disabled = true;
      const pct = data.total ? Math.round((data.scanned / data.total) * 100) : 0;
      fill.style.width = pct + '%';
      label.textContent = 'Scanning ' + (data.library || '...') + ' ' + data.scanned + '/' + data.total;
    } else {
      wrap.classList.remove('active');
      btn.disabled = false;
      if (wasActive) {
        wasActive = false;
        window.location.reload();
      }
    }
  }

  function poll() {
    fetch('/scan-progress')
      .then(r => r.json())
      .then(data => { render(data); setTimeout(poll, 1000); })
      .catch(() => setTimeout(poll, 2000));
  }

  if (form) {
    form.addEventListener('submit', function(e) {
      e.preventDefault();
      fetch('/scan', { method: 'POST', body: new FormData(form) });
    });
  }

  poll();
})();
"""

COMPARISON_TABLE_TEMPLATE = r"""
<div class="section">
  <h2>{{ page_title }}</h2>
  <p style="color:var(--muted);font-size:var(--fs-sm);margin:-8px 0 16px">{{ description }}</p>
  {% if rows %}
  <input type="search" id="search-box" placeholder="Search by title or year...">
  <table id="data-table">
    <thead>
      <tr>
        <th onclick="sortTable(0)">Title</th>
        <th onclick="sortTable(1)">Year</th>
        <th>Low seasons</th>
        <th>High seasons</th>
        <th>Missing in high</th>
        <th>Missing in low</th>
        <th onclick="sortTable(6)">Status</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>
    {% for row in rows %}
      <tr data-search="{{ (row.title ~ ' ' ~ (row.year or ''))|lower }}">
        <td>{{ row.title }}</td>
        <td>{{ row.year or '' }}</td>
        <td>{% for s in row.low_seasons %}<span class="badge">S{{ '%02d'|format(s) }}</span>{% else %}<span class="badge">-</span>{% endfor %}</td>
        <td>{% for s in row.high_seasons %}<span class="badge">S{{ '%02d'|format(s) }}</span>{% else %}<span class="badge">-</span>{% endfor %}</td>
        <td>{% for s in row.missing_in_high %}<span class="badge badge-missing">S{{ '%02d'|format(s) }}</span>{% endfor %}</td>
        <td>{% for s in row.missing_in_low %}<span class="badge badge-missing">S{{ '%02d'|format(s) }}</span>{% endfor %}</td>
        <td><span class="status-pill status-{{ row.status }}">{{ row.status.replace('_', ' ') }}</span></td>
        <td>
          <button type="button" class="btn btn-secondary" onclick='copyTitle({{ row.title|tojson }})'>Copy</button>
          {% if row.plex_url_low %}<a class="btn" href="{{ row.plex_url_low }}" target="_blank" rel="noopener">Low</a>{% endif %}
          {% if row.plex_url_high %}<a class="btn" href="{{ row.plex_url_high }}" target="_blank" rel="noopener">High</a>{% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  <div class="pagination" id="pagination"></div>
  {% else %}
  <div class="empty-state">Nothing to show here{{ ' yet - run a scan first.' if not has_scan else '.' }}</div>
  {% endif %}
</div>
<script>{{ table_js }}</script>
"""

DUPLICATES_TEMPLATE = r"""
<div class="section">
  <h2>Duplicates</h2>
  <p style="color:var(--muted);font-size:var(--fs-sm);margin:-8px 0 16px">Shows that appear more than once in the same library.</p>
  {% if groups %}
  <input type="search" id="search-box" placeholder="Search by title...">
  <table id="data-table">
    <thead>
      <tr>
        <th onclick="sortTable(0)">Title</th>
        <th>Library</th>
        <th onclick="sortTable(2)">Year</th>
        <th onclick="sortTable(3)">Count</th>
        <th>Items</th>
      </tr>
    </thead>
    <tbody>
    {% for group in groups %}
      <tr data-search="{{ group.normalized_title|lower }}">
        <td>{{ group.normalized_title }}</td>
        <td>{{ group.library_name }}</td>
        <td>{{ group.year or '' }}</td>
        <td>{{ group.count }}</td>
        <td>
        {% for item in group['items'] %}
          <a class="btn btn-secondary" style="margin:2px" href="{{ item.plex_web_url }}" target="_blank" rel="noopener">{{ item.title }} ({{ item.rating_key }})</a>
        {% endfor %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  <div class="pagination" id="pagination"></div>
  {% else %}
  <div class="empty-state">No duplicates found{{ ' yet - run a scan first.' if not has_scan else '.' }}</div>
  {% endif %}
</div>
<script>{{ table_js }}</script>
"""

EPISODE_GAPS_TEMPLATE = r"""
<div class="section">
  <h2>Episode Gaps</h2>
  <p style="color:var(--muted);font-size:var(--fs-sm);margin:-8px 0 16px">Seasons that exist in both libraries but have different episode counts - exact episode numbers missing on each side.</p>
  {% if rows %}
  <input type="search" id="search-box" placeholder="Search by title...">
  <table id="data-table">
    <thead>
      <tr>
        <th onclick="sortTable(0)">Title</th>
        <th onclick="sortTable(1)">Year</th>
        <th onclick="sortTable(2)">Season</th>
        <th onclick="sortTable(3)">Low Eps</th>
        <th onclick="sortTable(4)">High Eps</th>
        <th>Missing in High</th>
        <th>Missing in Low</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>
    {% for row in rows %}
      <tr data-search="{{ (row.title ~ ' ' ~ (row.year or ''))|lower }}">
        <td>{{ row.title }}</td>
        <td>{{ row.year or '' }}</td>
        <td>S{{ '%02d'|format(row.season_number) }}</td>
        <td>{{ row.low_episode_count }}</td>
        <td>{{ row.high_episode_count }}</td>
        <td>{% for e in row.missing_in_high %}<span class="badge badge-missing">E{{ '%02d'|format(e) }}</span>{% endfor %}</td>
        <td>{% for e in row.missing_in_low %}<span class="badge badge-missing">E{{ '%02d'|format(e) }}</span>{% endfor %}</td>
        <td>
          <button type="button" class="btn btn-secondary" onclick='copyTitle({{ row.title|tojson }})'>Copy</button>
          {% if row.plex_url_low %}<a class="btn" href="{{ row.plex_url_low }}" target="_blank" rel="noopener">Low</a>{% endif %}
          {% if row.plex_url_high %}<a class="btn" href="{{ row.plex_url_high }}" target="_blank" rel="noopener">High</a>{% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  <div class="pagination" id="pagination"></div>
  {% else %}
  <div class="empty-state">No episode gaps found{{ ' yet - run a scan first.' if not has_scan else '.' }}</div>
  {% endif %}
</div>
<script>{{ table_js }}</script>
"""

SCAN_STATUS_TEMPLATE = r"""
<div class="section">
  <h2>Scan Status</h2>
  {% if last_run %}
  <div class="stat-grid">
    <div class="stat-box"><div class="val">{{ last_run.status }}</div><div class="lbl">Last Status</div></div>
    <div class="stat-box"><div class="val">{{ last_run.low_show_count if last_run.low_show_count is not none else '-' }}</div><div class="lbl">Low Library Shows</div></div>
    <div class="stat-box"><div class="val">{{ last_run.high_show_count if last_run.high_show_count is not none else '-' }}</div><div class="lbl">High Library Shows</div></div>
    <div class="stat-box"><div class="val">#{{ last_run.id }}</div><div class="lbl">Scan Run ID</div></div>
  </div>
  <p style="color:var(--muted);font-size:var(--fs-sm)">Started: {{ last_run.started_at }}</p>
  <p style="color:var(--muted);font-size:var(--fs-sm)">Finished: {{ last_run.finished_at or 'in progress' }}</p>
  {% if last_run.error_message %}
  <div class="warning-banner">{{ last_run.error_message }}</div>
  {% endif %}
  {% else %}
  <div class="empty-state">No scans have run yet. Click "Scan Now" above.</div>
  {% endif %}
</div>
"""


def render_page(active_tab, page_title, content_html, scan_message=None, scan_message_kind="success"):
    return render_template_string(
        BASE_TEMPLATE,
        page_title=page_title,
        header_sub=page_title,
        nav_tabs=NAV_TABS,
        active_tab=active_tab,
        content=Markup(content_html),
        css=Markup(CSS),
        csrf_token=get_csrf_token(),
        scan_message=scan_message,
        scan_message_kind=scan_message_kind,
        scan_progress_js=Markup(SCAN_PROGRESS_JS),
    )


def _get_active_run(conn):
    run = db.get_latest_scan_run(conn, status="success")
    return run


def _scan_banner():
    scan_param = request.args.get("scan")
    if scan_param == "started":
        return "Scan started in the background - refresh in a moment to see updated results.", "success"
    if scan_param == "busy":
        return "A scan is already running.", "warning"
    return None, "success"


@app.route("/")
@requires_auth
def index():
    return redirect("/missing-seasons")


def _comparisons_page(active_tab, page_title, description, statuses):
    with db.connect() as conn:
        run = _get_active_run(conn)
        rows = db.get_comparisons(conn, run["id"], statuses=statuses) if run else []
    content = render_template_string(
        COMPARISON_TABLE_TEMPLATE,
        page_title=page_title,
        description=description,
        rows=rows,
        has_scan=run is not None,
        table_js=Markup(TABLE_JS),
    )
    message, kind = _scan_banner()
    return render_page(active_tab, page_title, content, scan_message=message, scan_message_kind=kind)


@app.route("/missing-seasons")
@requires_auth
def missing_seasons():
    return _comparisons_page(
        "missing-seasons",
        "Missing Seasons",
        "Shows present in both libraries, plus their season match status.",
        statuses=["season_mismatch", "match_complete"],
    )


@app.route("/episode-gaps")
@requires_auth
def episode_gaps_page():
    with db.connect() as conn:
        run = _get_active_run(conn)
        rows = db.get_episode_mismatches(conn, run["id"]) if run else []
    content = render_template_string(
        EPISODE_GAPS_TEMPLATE,
        rows=rows,
        has_scan=run is not None,
        table_js=Markup(TABLE_JS),
    )
    message, kind = _scan_banner()
    return render_page("episode-gaps", "Episode Gaps", content, scan_message=message, scan_message_kind=kind)


@app.route("/high-only")
@requires_auth
def high_only():
    return _comparisons_page(
        "high-only",
        "High Only",
        "Shows that exist only in the high-bitrate library.",
        statuses=["high_only"],
    )


@app.route("/low-only")
@requires_auth
def low_only():
    return _comparisons_page(
        "low-only",
        "Low Only",
        "Shows that exist only in the low-bitrate library.",
        statuses=["missing_in_high"],
    )


@app.route("/duplicates")
@requires_auth
def duplicates_page():
    with db.connect() as conn:
        run = _get_active_run(conn)
        groups = db.get_duplicates(conn, run["id"]) if run else []
    content = render_template_string(
        DUPLICATES_TEMPLATE,
        groups=groups,
        has_scan=run is not None,
        table_js=Markup(TABLE_JS),
    )
    message, kind = _scan_banner()
    return render_page("duplicates", "Duplicates", content, scan_message=message, scan_message_kind=kind)


@app.route("/scan-status")
@requires_auth
def scan_status():
    with db.connect() as conn:
        last_run = db.get_last_scan_run(conn)
    content = render_template_string(SCAN_STATUS_TEMPLATE, last_run=last_run)
    message, kind = _scan_banner()
    return render_page("scan-status", "Scan Status", content, scan_message=message, scan_message_kind=kind)


def _run_scan_background():
    global _scan_in_progress
    try:
        run_scan(on_progress=_update_scan_progress, show_cli_progress=False)
    finally:
        with _scan_lock:
            _scan_in_progress = False
            _scan_progress.update(active=False, library=None, scanned=0, total=0)


def _redirect_with_scan_flag(flag):
    page = urlsplit(request.referrer or "").path
    if page not in {f"/{slug}" for slug, _ in NAV_TABS}:
        page = "/scan-status"
    return redirect(f"{page}?scan={flag}")


def _start_background_scan():
    global _scan_in_progress
    with _scan_lock:
        if _scan_in_progress:
            return False
        _scan_in_progress = True
        _scan_progress.update(active=True, library=None, scanned=0, total=0)
    threading.Thread(target=_run_scan_background, daemon=True).start()
    return True


@app.route("/scan-progress")
@requires_auth
def scan_progress_endpoint():
    with _scan_lock:
        return jsonify(dict(_scan_progress))


@app.route("/scan", methods=["POST"])
@requires_auth
def trigger_scan():
    if not has_valid_csrf(request.form.get("csrf_token")):
        return Response("Invalid CSRF token", status=403)
    started = _start_background_scan()
    return _redirect_with_scan_flag("started" if started else "busy")


if __name__ == "__main__":
    bind_host = os.getenv("BIND_HOST", "127.0.0.1")
    bind_port = int(os.getenv("PORT", "5001"))
    loopback = bind_host in ("127.0.0.1", "localhost", "::1")
    allow_insecure = os.getenv("ALLOW_INSECURE", "false").lower() == "true"

    if not loopback and not auth_enabled() and not allow_insecure:
        print(
            f"ERROR: refusing to bind to {bind_host} without auth.\n"
            "  Set WEB_USERNAME and WEB_PASSWORD in .env, bind to 127.0.0.1,\n"
            "  or set ALLOW_INSECURE=true if a reverse proxy handles auth."
        )
        sys.exit(1)

    with db.connect() as conn:
        has_scan = db.get_latest_scan_run(conn, status="success") is not None
    if not has_scan:
        print("No previous scan found - starting an initial scan in the background...")
        _start_background_scan()

    print("Plex Library Comparison Tool")
    print(f"   -> Web UI: http://{bind_host}:{bind_port}")
    if not auth_enabled():
        print("WARNING: WEB_USERNAME/WEB_PASSWORD not set; web auth is disabled (loopback only).")
    app.run(host=bind_host, port=bind_port, debug=False)
