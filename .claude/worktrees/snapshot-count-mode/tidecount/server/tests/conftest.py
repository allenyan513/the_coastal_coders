import os
import tempfile

# Set before anything imports tidecount.config, so tests never touch real data or start analysis.
os.environ["TIDECOUNT_DATA"] = tempfile.mkdtemp(prefix="tidecount-test-")
os.environ["TIDECOUNT_WORKER"] = "0"
# No file here, so tests run on the built-in defaults, whatever ml has put in settings.toml.
os.environ["TIDECOUNT_SETTINGS"] = os.path.join(os.environ["TIDECOUNT_DATA"], "no-settings.toml")

import pytest  # noqa: E402

from tidecount import config, db  # noqa: E402

config.ensure_folders()


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Every test gets its own empty database, so no test has to clean up after another."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "tidecount.db")
    db.init()
