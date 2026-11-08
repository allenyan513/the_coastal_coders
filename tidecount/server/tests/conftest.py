import os
import tempfile
import time

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


def pytest_configure(config):
    config.addinivalue_line("markers", "real_auth: sign in for real (cookies, sessions) instead of as the default test manager")


def _person(role: str):
    from tidecount import auth
    return auth.User(1, f"{role}@example.org", role.title(), role, "test-session", time.time())


@pytest.fixture(autouse=True)
def signed_in(request):
    """Tests run as a signed-in manager who just confirmed their password, so tests written before
    sign-in existed keep testing what they test. `real_auth` tests get no stand-in and sign in for real."""
    from tidecount import auth
    from tidecount.app import app
    auth.reset_state()
    if "real_auth" not in request.keywords:
        app.dependency_overrides[auth.viewer] = lambda: _person("manager")
    yield
    app.dependency_overrides.pop(auth.viewer, None)


@pytest.fixture
def as_role():
    """Switch the stand-in: as_role("volunteer"), as_role("manager"), or as_role(None) for a guest."""
    from tidecount import auth
    from tidecount.app import app

    def use(role):
        app.dependency_overrides[auth.viewer] = (lambda: None) if role is None else (lambda: _person(role))
    return use
