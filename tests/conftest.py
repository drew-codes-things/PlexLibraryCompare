import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TEST_STATE_DIR = tempfile.mkdtemp(prefix="plexcompare-tests-")
os.environ.setdefault("PLEX_COMPARE_DB_PATH", os.path.join(TEST_STATE_DIR, "plex_compare.db"))


def pytest_unconfigure(config):
    shutil.rmtree(TEST_STATE_DIR, ignore_errors=True)
