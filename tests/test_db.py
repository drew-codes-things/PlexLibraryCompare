import importlib
import os

import db


def reload_db_with_path(monkeypatch, value):
    monkeypatch.setenv("PLEX_COMPARE_DB_PATH", value)
    return importlib.reload(db)


def test_an_empty_db_path_falls_back_to_the_default(monkeypatch):
    reloaded = reload_db_with_path(monkeypatch, "")
    assert reloaded.DB_PATH == os.path.join(reloaded.BASE_DIR, "plex_compare.db")


def test_a_saved_scan_is_seen_by_the_next_connection(monkeypatch, tmp_path):
    reloaded = reload_db_with_path(monkeypatch, str(tmp_path / "compare.db"))
    with reloaded.connect() as conn:
        run_id = reloaded.start_scan_run(conn)
        reloaded.finish_scan_run(conn, run_id, "success")
    with reloaded.connect() as conn:
        assert reloaded.get_latest_scan_run(conn)["id"] == run_id
