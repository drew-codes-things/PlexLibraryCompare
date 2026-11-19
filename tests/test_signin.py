import ipaddress
import os
import stat
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app
import db
from signin import SESSION_SECONDS, FailureLimiter, OwnerAccount

REPO = os.path.join(os.path.dirname(__file__), "..")
COOKIE = "plexcompare_session"
OWNER_NAME = "owner"
PASSWORD = "correct horse battery"
HEADER = "X-Forwarded-User"
PAGE = "/missing-seasons"
PROGRESS = "/scan-progress"


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def web(tmp_path, monkeypatch, clock):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "compare.db"))
    monkeypatch.setattr(app, "WEB_USERNAME", "")
    monkeypatch.setattr(app, "WEB_PASSWORD", "")
    monkeypatch.setattr(app, "ALLOW_INSECURE", False)
    monkeypatch.setattr(app, "_start_background_scan", lambda: True)
    monkeypatch.setattr(app.OWN_SIGN_IN, "owner", OwnerAccount(tmp_path / "owner.json"))
    monkeypatch.setattr(app.OWN_SIGN_IN, "limiter", FailureLimiter(clock=clock))
    monkeypatch.setattr(app.OWN_SIGN_IN, "device_limiter", FailureLimiter(clock=clock, before_strict=None))
    monkeypatch.setattr(app.OWN_SIGN_IN, "clock", clock)
    monkeypatch.setattr(app.OWN_SIGN_IN, "_setup_code", None)
    return app.app.test_client()


def set_up_owner(web, form=None, **kwargs):
    details = {"code": app.OWN_SIGN_IN.setup_code(), "user": OWNER_NAME, "password": PASSWORD, "confirm": PASSWORD}
    details.update(form or {})
    return web.post("/setup", data=details, **kwargs)


def sign_in(web, password=PASSWORD, **kwargs):
    return web.post("/signin", data={"user": OWNER_NAME, "password": password}, **kwargs)


def forget_the_browser(web) -> None:
    web.delete_cookie(COOKIE)
    web.delete_cookie(COOKIE + "_device", path="/signin")


def session_cookie(response) -> str:
    return next(value for value in response.headers.getlist("Set-Cookie") if value.startswith(COOKIE + "="))


def test_the_own_sign_in_is_the_default(web):
    assert app.sign_in_method() == "builtin"


def test_a_signed_out_visit_goes_to_setup_then_to_sign_in(web):
    assert web.get("/").headers["Location"].endswith("/setup")
    assert web.get(PAGE).headers["Location"].endswith("/setup")
    set_up_owner(web)
    web.delete_cookie(COOKIE)
    assert web.get(PAGE).headers["Location"].endswith("/signin")


def test_progress_and_scans_need_a_sign_in(web):
    assert web.get(PROGRESS).status_code == 401
    assert web.post("/scan", data={"csrf_token": "x"}).status_code == 401


def test_the_health_check_stays_open(web):
    assert web.get("/health").status_code == 200


def test_the_user_header_is_ignored(web):
    set_up_owner(web)
    web.delete_cookie(COOKIE)
    assert web.get(PROGRESS, headers={HEADER: OWNER_NAME}).status_code == 401


def test_setup_needs_the_code_and_happens_once(web, tmp_path):
    assert set_up_owner(web, form={"code": "not-the-code"}).status_code == 401
    assert set_up_owner(web).status_code == 303
    assert stat.S_IMODE(os.stat(tmp_path / "owner.json").st_mode) == 0o600
    assert web.get(PAGE).status_code == 200
    assert web.get(PROGRESS).status_code == 200
    assert set_up_owner(web, form={"user": "intruder"}).headers["Location"].endswith("/signin")
    assert app.OWN_SIGN_IN.owner.read()["user"] == OWNER_NAME


def test_a_signed_in_owner_can_start_a_scan(web):
    set_up_owner(web)
    web.get(PAGE)
    with web.session_transaction() as flask_session:
        token = flask_session["_csrf_token"]
    started = web.post("/scan", data={"csrf_token": token}, headers={"Referer": "http://localhost" + PAGE})
    assert started.status_code == 302
    assert started.headers["Location"].endswith(PAGE + "?scan=started")


def test_wrong_passwords_are_rate_limited(web):
    set_up_owner(web)
    forget_the_browser(web)
    for _attempt in range(5):
        assert sign_in(web, password="wrong password!").status_code == 401
    assert sign_in(web).status_code == 429
    assert sign_in(web, environ_base={"REMOTE_ADDR": "192.0.2.7"}).status_code == 303


def test_signing_out_and_expiry_end_the_session(web, clock):
    set_up_owner(web)
    assert web.get(PROGRESS).status_code == 200
    clock.now += SESSION_SECONDS + 1
    assert web.get(PROGRESS).status_code == 401
    clock.now -= SESSION_SECONDS + 1
    assert web.get(PROGRESS).status_code == 200
    assert web.post("/signout").status_code == 303
    assert web.get(PROGRESS).status_code == 401


@pytest.mark.parametrize("token", ["é.é", "abc.\udcff", "no-dot", "", None])
def test_an_odd_session_value_is_refused_not_crashed(web, token):
    assert app.OWN_SIGN_IN.user_for_token(token) is None


def test_the_session_cookie_flags(web):
    local = set_up_owner(web)
    assert "HttpOnly" in session_cookie(local) and "SameSite=Lax" in session_cookie(local)
    assert "Secure" not in session_cookie(local)
    remote = sign_in(web, base_url="http://192.0.2.1")
    assert "Secure" in session_cookie(remote)


def test_the_no_sign_in_setting_leaves_it_to_a_proxy(web, monkeypatch):
    monkeypatch.setattr(app, "ALLOW_INSECURE", True)
    assert app.sign_in_method() == "proxy"
    assert web.get(PAGE).status_code == 200
    assert web.get(PROGRESS).status_code == 200
    assert web.get("/setup").status_code == 404
    assert web.get("/signin").status_code == 404


def test_basic_credentials_still_win_when_set(web, monkeypatch):
    monkeypatch.setattr(app, "WEB_USERNAME", "basic-user")
    monkeypatch.setattr(app, "WEB_PASSWORD", "a long basic password")
    assert app.sign_in_method() == "basic"
    assert web.get(PAGE).status_code == 401
    assert web.get(PAGE, auth=("basic-user", "a long basic password")).status_code == 200
    assert web.get("/setup").status_code == 404


def import_app(tmp_path, shown="app.OWN_SIGN_IN.secret.decode()", **settings):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path),
           "PLEX_COMPARE_DB_PATH": str(tmp_path / "state" / "plex_compare.db")}
    env.update(settings)
    return subprocess.run([sys.executable, "-c", f"import app; print({shown})"], cwd=REPO, env=env, capture_output=True,
                          text=True, timeout=60)


def test_the_sign_in_key_is_saved_and_reused_when_imported(tmp_path):
    first = import_app(tmp_path)
    second = import_app(tmp_path)
    assert first.returncode == 0, first.stderr
    key_file = tmp_path / "state" / "secret_key"
    assert stat.S_IMODE(os.stat(key_file).st_mode) == 0o600
    assert first.stdout.strip() == second.stdout.strip() == key_file.read_text()


@pytest.mark.parametrize("settings", [{"SECRET_KEY": "a"}, {"SECRET_KEY": "y" * 31}])
def test_a_short_sign_in_key_is_refused(tmp_path, settings):
    started = import_app(tmp_path, **settings)
    assert started.returncode != 0
    assert "SECRET_KEY holds" in started.stderr


def test_a_short_key_file_is_refused(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "secret_key").write_bytes(b"short")
    started = import_app(tmp_path)
    assert started.returncode != 0
    assert "fewer than the 32" in started.stderr


def test_the_proxy_and_basic_modes_need_no_key_file_and_take_any_key(tmp_path):
    assert import_app(tmp_path, ALLOW_INSECURE="true", SECRET_KEY="a", TRUSTED_PROXIES="0.0.0.0/0").returncode == 0
    assert import_app(tmp_path, WEB_USERNAME="basic-user", WEB_PASSWORD="a long basic password").returncode == 0
    assert not (tmp_path / "state" / "secret_key").exists()


def test_allowed_hosts_and_trusted_proxies_come_from_the_environment(tmp_path):
    shown = "app.OWN_SIGN_IN.accepts_host('localhost'), app.OWN_SIGN_IN.accepts_host('plex.example.com'), " \
            "app.OWN_SIGN_IN.client_address('192.0.2.10', {'X-Forwarded-For': '203.0.113.9'})"
    started = import_app(tmp_path, shown, ALLOWED_HOSTS="plex.example.com", TRUSTED_PROXIES="192.0.2.10")
    assert started.returncode == 0, started.stderr
    assert started.stdout.split() == ["False", "True", "203.0.113.9"]
    assert import_app(tmp_path, shown).stdout.split() == ["True", "False", "192.0.2.10"]


@pytest.mark.parametrize("value", ["0.0.0.0/0", "::/0", "10.0.0.5/8", "not-an-address"])
def test_trusted_proxies_that_reach_too_far_are_refused(tmp_path, value):
    started = import_app(tmp_path, TRUSTED_PROXIES=value)
    assert started.returncode != 0
    assert "TRUSTED_PROXIES" in started.stderr


def test_a_rebinding_host_name_gets_421(web):
    set_up_owner(web)
    attacker = app.app.test_client()
    for _attempt in range(6):
        assert sign_in(attacker, password="wrong password!", base_url="http://rebind.evil.example:5001").status_code == 421
    assert attacker.get(PROGRESS, base_url="http://rebind.evil.example:5001").status_code == 421
    assert sign_in(attacker).status_code == 303


def test_the_proxy_mode_answers_on_any_host_name(web, monkeypatch):
    monkeypatch.setattr(app, "ALLOW_INSECURE", True)
    assert web.get(PAGE, base_url="http://plex.example.com").status_code == 200


def test_a_browser_that_signed_in_before_is_not_locked_out_by_others(web):
    set_up_owner(web)
    assert web.post("/signout").status_code == 303
    attacker = app.app.test_client()
    for _attempt in range(5):
        assert sign_in(attacker, password="wrong password!").status_code == 401
    assert sign_in(attacker).status_code == 429
    assert sign_in(web).status_code == 303


def test_the_forwarded_address_counts_only_from_a_trusted_proxy(web, monkeypatch):
    monkeypatch.setattr(app.OWN_SIGN_IN, "trusted_proxies", (ipaddress.ip_network("192.0.2.10"),))
    set_up_owner(web)
    via_proxy = {"REMOTE_ADDR": "192.0.2.10"}
    attacker = app.app.test_client()
    for _attempt in range(5):
        sign_in(attacker, password="wrong password!", environ_base=via_proxy, headers={"X-Forwarded-For": "203.0.113.9"})
    assert sign_in(attacker, environ_base=via_proxy, headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 429
    owner = app.app.test_client()
    assert sign_in(owner, environ_base=via_proxy, headers={"X-Forwarded-For": "198.51.100.4"}).status_code == 303
