"""Real sign-in: accounts, sessions, cookies, cross-site writes, limits, first setup, the team,
and what guests, volunteers and managers may each reach. Everything here signs in for real."""
import hashlib
import re
import time
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tidecount import auth, db
from tidecount.app import app

pytestmark = pytest.mark.real_auth
ORIGIN = "http://testserver"
PASSWORD = "correct horse battery"


def browser(**kw) -> TestClient:
    """A fresh browser: its own cookie jar, and the Origin header a browser sends with writes."""
    return TestClient(app, headers={"Origin": kw.pop("origin", ORIGIN)}, **kw)


def make_user(email: str, role: str, password: str = PASSWORD, active: bool = True) -> int:
    with db.session() as con:
        return con.execute("INSERT INTO users (email, name, role, password_hash, active, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                           (email, email.split("@")[0].title(), role, auth.hash_password(password), int(active), time.time())).lastrowid


def signed_in(role: str, email: str | None = None) -> TestClient:
    email = email or f"{role}@example.org"
    make_user(email, role)
    b = browser()
    assert b.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return b


def cookie_of(b: TestClient) -> str:
    return b.cookies.get(auth.PLAIN_COOKIE) or b.cookies.get(auth.SECURE_COOKIE)


# --- first manager ------------------------------------------------------------------------------

def test_the_kept_setup_route_still_needs_the_console_code(capsys):
    # Sign-up doesn't need setup any more, and nothing prints a code on its own; the route is kept.
    b = browser()
    me = b.get("/api/auth/me").json()
    assert me == {"user": None, "setup_needed": True}
    assert "setup code" not in capsys.readouterr().out
    auth.ensure_setup_code()
    code = re.search(r"setup code: ([A-Z0-9-]{19})", capsys.readouterr().out).group(1)
    form = {"name": "First Manager", "email": "first@example.org", "password": PASSWORD}

    assert b.post("/api/auth/setup", json={**form, "code": "AAAA-BBBB-CCCC-DDDD"}).status_code == 400
    r = b.post("/api/auth/setup", json={**form, "code": code})
    assert r.status_code == 200 and r.json()["user"]["role"] == "manager"
    assert b.get("/api/auth/me").json()["user"]["email"] == "first@example.org"
    # Once anyone exists, setup is gone, and the code can't be used again.
    other = browser()
    assert other.post("/api/auth/setup", json={**form, "email": "second@example.org", "code": code}).status_code == 404
    assert other.get("/api/auth/me").json()["setup_needed"] is False


def test_setup_refuses_weak_passwords_and_has_no_default_account():
    b = browser()
    b.get("/api/auth/me")
    assert b.post("/api/auth/setup", json={"name": "x", "email": "a@b.org", "password": "short", "code": "x"}).status_code == 400
    for email, password in (("admin@tideflow.demo", "admin"), ("manager@tideflow.demo", "demo-password")):
        assert b.post("/api/auth/login", json={"email": email, "password": password}).status_code == 401


# --- signing up ---------------------------------------------------------------------------------

def register(b, name="New Person", email="new@example.org", role="volunteer"):
    return b.post("/api/auth/register", json={"name": name, "email": email, "role": role})


@pytest.mark.parametrize("role", ["volunteer", "manager"])
def test_anyone_can_sign_up_and_is_signed_in_with_a_generated_password(role):
    b = browser()
    r = register(b, email=f"{role}@example.org", role=role)
    assert r.status_code == 200 and r.json()["user"]["role"] == role
    password = r.json()["password"]
    assert re.fullmatch(r"([a-zA-Z2-9]{5}-){3}[a-zA-Z2-9]{5}", password)
    assert r.headers["cache-control"] == "no-store" and "httponly" in r.headers["set-cookie"].lower()
    # Signed in at once, with the role chosen, and the session lasts like any other.
    assert b.get("/api/auth/me").json()["user"]["email"] == f"{role}@example.org"
    assert b.get("/api/surveys").status_code == 200
    assert b.get("/api/team").status_code == (200 if role == "manager" else 403)
    # Only a hash is kept, and the password works for signing in later.
    with db.session() as con:
        stored = con.execute("SELECT password_hash FROM users").fetchone()[0]
    assert stored.startswith("scrypt$") and password not in stored
    assert browser().post("/api/auth/login", json={"email": f"{role}@example.org", "password": password}).status_code == 200


def test_signing_up_needs_no_invite_or_setup_even_as_the_first_account():
    b = browser()
    assert b.get("/api/auth/me").json()["setup_needed"] is True
    assert register(b, role="manager").status_code == 200
    assert b.get("/api/auth/me").json()["setup_needed"] is False


def test_every_account_gets_its_own_password():
    passwords = {register(browser(), email=f"p{i}@example.org").json()["password"] for i in range(5)}
    assert len(passwords) == 5


def test_an_existing_email_cant_be_signed_up_again_or_taken_over():
    owner = browser()
    original = register(owner, email="owner@example.org", role="manager").json()["password"]
    before = owner.get("/api/auth/me").json()["user"]
    with db.session() as con:
        stored = con.execute("SELECT password_hash FROM users").fetchone()[0]

    intruder = browser()
    for email in ("owner@example.org", "OWNER@Example.org ", " owner@example.org"):
        r = register(intruder, email=email, role="manager")
        assert r.status_code == 409 and "password" not in r.json() and "set-cookie" not in r.headers
    assert intruder.get("/api/auth/me").json()["user"] is None and intruder.get("/api/team").status_code == 401
    with db.session() as con:
        assert tuple(con.execute("SELECT COUNT(*), password_hash FROM users").fetchone()) == (1, stored)
    assert owner.get("/api/auth/me").json()["user"] == before  # nothing about the account changed
    assert browser().post("/api/auth/login", json={"email": "owner@example.org", "password": original}).status_code == 200


def test_sign_up_checks_what_it_is_given():
    b = browser()
    assert register(b, role="admin").status_code == 400
    assert register(b, role="").status_code == 400
    assert register(b, email="not-an-email").status_code == 400
    assert register(b, name="   ").status_code == 400
    assert b.post("/api/auth/register", json={"name": "X", "email": "x@example.org", "role": "volunteer", "password": "mine123456"}).json()["password"] != "mine123456"
    with db.session() as con:
        assert con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_sign_up_is_limited_per_address_and_refused_from_other_sites(monkeypatch):
    assert register(browser(origin="https://evil.example")).status_code == 403
    monkeypatch.setattr(auth, "register_by_ip", auth.api_guard.Limiter(2, 3600.0))
    b = browser()
    assert register(b, email="a@example.org").status_code == 200
    assert register(b, email="b@example.org").status_code == 200
    r = register(b, email="c@example.org")
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_a_generated_password_can_be_changed_in_settings():
    b = browser()
    generated = register(b).json()["password"]
    assert b.post("/api/auth/password", json={"current": generated, "new": "my own long password"}).status_code == 204
    assert browser().post("/api/auth/login", json={"email": "new@example.org", "password": generated}).status_code == 401
    assert browser().post("/api/auth/login", json={"email": "new@example.org", "password": "my own long password"}).status_code == 200


# --- the demo sign-in ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["volunteer", "manager"])
def test_the_demo_sign_in_opens_that_roles_shared_account(role):
    b = browser()
    r = b.post("/api/auth/demo", json={"role": role})
    assert r.status_code == 200 and r.json()["user"] == {**r.json()["user"], "role": role, "email": f"{role}@tideflow.demo"}
    assert "httponly" in r.headers["set-cookie"].lower()
    assert b.get("/api/surveys").status_code == 200
    assert b.get("/api/team").status_code == (200 if role == "manager" else 403)  # the server's role checks still apply
    # The same shared account every time, made once.
    browser().post("/api/auth/demo", json={"role": role})
    with db.session() as con:
        assert con.execute("SELECT COUNT(*) FROM users WHERE email = ?", (f"{role}@tideflow.demo",)).fetchone()[0] == 1


def test_the_demo_accounts_cant_be_opened_or_claimed_any_other_way():
    browser().post("/api/auth/demo", json={"role": "manager"})
    # The filled-in password isn't the account's password, so the ordinary sign-in can't open it.
    assert browser().post("/api/auth/login", json={"email": "manager@tideflow.demo", "password": "demo-password"}).status_code == 401
    assert register(browser(), email="someone@tideflow.demo").status_code == 400
    assert browser().post("/api/auth/demo", json={"role": "admin"}).status_code == 400
    assert browser(origin="https://evil.example").post("/api/auth/demo", json={"role": "manager"}).status_code == 403


def test_the_demo_sign_in_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("TIDECOUNT_DEMO_SIGNIN", "0")
    r = browser().post("/api/auth/demo", json={"role": "manager"})
    assert r.status_code == 404 and "set-cookie" not in r.headers


def test_the_demo_manager_deletes_without_a_password_prompt():
    b = browser()
    b.post("/api/auth/demo", json={"role": "manager"})
    with db.session() as con:
        con.execute("UPDATE sessions SET reauth_at = 0")  # long after sign-in
    site = b.post("/api/surveys/sites", json={"name": "Temporary site"}).json()["id"]
    r = b.delete(f"/api/surveys/sites/{site}")
    assert r.status_code not in (401, 403) and auth.REAUTH_HEADER not in r.headers
    assert b.delete("/api/species/library/upload-000000000000").status_code == 404  # allowed; nothing there
    # A real manager account still has to confirm its password.
    real = signed_in("manager", "real.manager@example.org")
    with db.session() as con:
        con.execute("UPDATE sessions SET reauth_at = 0")
    assert real.delete("/api/species/library/upload-000000000000").status_code == 403


def test_a_switched_off_demo_account_stays_off():
    manager = signed_in("manager")
    browser().post("/api/auth/demo", json={"role": "volunteer"})
    with db.session() as con:
        demo_id = con.execute("SELECT id FROM users WHERE email = 'volunteer@tideflow.demo'").fetchone()[0]
    assert manager.patch(f"/api/team/{demo_id}", json={"active": False}).status_code == 200
    r = browser().post("/api/auth/demo", json={"role": "volunteer"})
    assert r.status_code == 403 and "set-cookie" not in r.headers


# --- signing in and out -------------------------------------------------------------------------

def test_wrong_password_and_unknown_email_look_the_same():
    make_user("vol@example.org", "volunteer")
    b = browser()
    wrong = b.post("/api/auth/login", json={"email": "vol@example.org", "password": "not the password"})
    unknown = b.post("/api/auth/login", json={"email": "nobody@example.org", "password": "not the password"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Email or password is wrong."}
    make_user("off@example.org", "volunteer", active=False)
    assert b.post("/api/auth/login", json={"email": "off@example.org", "password": PASSWORD}).json() == wrong.json()


def test_sign_in_sets_a_persistent_httponly_cookie_and_stores_only_hashes():
    make_user("vol@example.org", "volunteer")
    b = browser()
    r = b.post("/api/auth/login", json={"email": "VOL@example.org ", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["role"] == "volunteer"
    header = r.headers["set-cookie"].lower()
    assert header.startswith(f"{auth.PLAIN_COOKIE}=") and "httponly" in header and "samesite=lax" in header and "path=/" in header
    assert f"max-age={auth.ABSOLUTE_S}" in header and "secure" not in header  # plain HTTP here
    token = cookie_of(b)
    with db.session() as con:
        stored = [r["token_hash"] for r in con.execute("SELECT token_hash FROM sessions")]
        password_hash = con.execute("SELECT password_hash FROM users").fetchone()[0]
    assert stored == [hashlib.sha256(token.encode()).hexdigest()] and token not in stored
    assert password_hash.startswith("scrypt$") and PASSWORD not in password_hash


def test_a_session_survives_a_browser_restart_and_a_server_restart():
    b = signed_in("volunteer")
    token = cookie_of(b)
    reopened = TestClient(app, headers={"Origin": ORIGIN}, cookies={auth.PLAIN_COOKIE: token})
    assert reopened.get("/api/auth/me").json()["user"]["role"] == "volunteer"
    auth.reset_state()  # nothing in memory matters: the session is in the database
    assert reopened.get("/api/surveys").status_code == 200


def test_sessions_end_after_30_idle_days_or_90_days_in_all():
    b = signed_in("volunteer")
    th = hashlib.sha256(cookie_of(b).encode()).hexdigest()
    now = time.time()
    with db.session() as con:
        con.execute("UPDATE sessions SET last_seen = ? WHERE token_hash = ?", (now - 29 * 86400, th))
    assert b.get("/api/surveys").status_code == 200  # still in, and that use counts
    with db.session() as con:
        assert con.execute("SELECT last_seen FROM sessions").fetchone()[0] > now - 60
        con.execute("UPDATE sessions SET created_at = ? WHERE token_hash = ?", (now - 91 * 86400, th))
    assert b.get("/api/surveys").status_code == 401
    with db.session() as con:
        assert con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0

    b = signed_in("volunteer", "other@example.org")
    with db.session() as con:
        con.execute("UPDATE sessions SET last_seen = ?", (now - 31 * 86400,))
    assert b.get("/api/auth/me").json()["user"] is None


def test_sign_out_ends_the_session_for_good():
    b = signed_in("volunteer")
    token = cookie_of(b)
    assert b.post("/api/auth/logout").status_code == 204
    replay = TestClient(app, headers={"Origin": ORIGIN}, cookies={auth.PLAIN_COOKIE: token})
    assert replay.get("/api/auth/me").json()["user"] is None
    assert replay.get("/api/surveys").status_code == 401


def test_a_forged_or_tampered_cookie_is_a_guest():
    signed_in("manager")
    for value in ("not-a-session", "x" * 500):
        forged = TestClient(app, headers={"Origin": ORIGIN}, cookies={auth.PLAIN_COOKIE: value})
        assert forged.get("/api/team").status_code == 401


def test_the_role_comes_from_the_database_on_every_request():
    b = signed_in("volunteer")
    assert b.get("/api/team").status_code == 403
    with db.session() as con:
        con.execute("UPDATE users SET role = 'manager'")
    assert b.get("/api/team").status_code == 200
    with db.session() as con:
        con.execute("UPDATE users SET active = 0")
    assert b.get("/api/surveys").status_code == 401


def test_nothing_the_browser_says_about_its_role_counts():
    b = signed_in("volunteer")
    b.cookies.set("tideflow-session", '{"role":"manager"}')
    assert b.get("/api/team", headers={"X-Role": "manager"}).status_code == 403
    assert b.post("/api/surveys/sites", json={"name": "Mine", "role": "manager"}).status_code == 403


def test_password_change_signs_out_everywhere_else():
    make_user("vol@example.org", "volunteer")
    phone, laptop = browser(), browser()
    for b in (phone, laptop):
        b.post("/api/auth/login", json={"email": "vol@example.org", "password": PASSWORD})
    assert laptop.post("/api/auth/password", json={"current": "wrong one!", "new": "a new long password"}).status_code == 400
    assert laptop.post("/api/auth/password", json={"current": PASSWORD, "new": "short"}).status_code == 400
    assert laptop.post("/api/auth/password", json={"current": PASSWORD, "new": "a new long password"}).status_code == 204
    assert laptop.get("/api/surveys").status_code == 200
    assert phone.get("/api/surveys").status_code == 401
    assert browser().post("/api/auth/login", json={"email": "vol@example.org", "password": "a new long password"}).status_code == 200


# --- cookies on HTTPS --------------------------------------------------------------------------

def test_https_gets_a_secure_host_only_cookie():
    make_user("vol@example.org", "volunteer")
    b = TestClient(app, base_url="https://testserver", headers={"Origin": "https://testserver"})
    r = b.post("/api/auth/login", json={"email": "vol@example.org", "password": PASSWORD})
    header = r.headers["set-cookie"].lower()
    assert header.startswith(f"{auth.SECURE_COOKIE.lower()}=") and "secure" in header and "httponly" in header
    assert "domain=" not in header and "path=/" in header
    assert b.get("/api/surveys").status_code == 200


def test_forwarded_https_is_believed_only_from_the_proxy(monkeypatch):
    monkeypatch.delenv("TIDECOUNT_SECURE_COOKIES", raising=False)
    req = lambda peer, headers: SimpleNamespace(url=SimpleNamespace(scheme="http"), headers=headers, client=SimpleNamespace(host=peer))
    caddy = {"x-forwarded-proto": "https"}
    assert auth.is_https(req("172.18.0.3", caddy))       # Caddy on Docker's network
    # A visitor writing the header themselves. (Not 203.0.113.x: Python counts documentation ranges as private.)
    assert not auth.is_https(req("8.8.8.8", caddy))
    assert not auth.is_https(req("172.18.0.3", {}))
    monkeypatch.setenv("TIDECOUNT_SECURE_COOKIES", "1")
    assert auth.is_https(req("8.8.8.8", {}))


# --- cross-site writes -------------------------------------------------------------------------

def test_writes_from_another_site_are_refused():
    b = signed_in("manager")
    name = lambda: b.get("/api/auth/me").json()["user"]["name"]
    evil = {"Origin": "https://evil.example"}
    r = b.patch("/api/auth/me", json={"name": "Planted"}, headers=evil)
    assert r.status_code == 403 and "another site" in r.json()["detail"]
    assert b.post("/api/auth/logout", headers={"Origin": "null"}).status_code == 403
    assert b.patch("/api/auth/me", json={"name": "Planted"}, headers={"Origin": "http://testserver.evil.example"}).status_code == 403
    # Neither Origin nor Referer, with a session cookie: refused. A Referer from Tideflow itself: fine.
    assert b.patch("/api/auth/me", json={"name": "Planted"}, headers={"Origin": ""}).status_code == 403
    assert name() == "Manager"
    assert b.patch("/api/auth/me", json={"name": "Ours"}, headers={"Origin": "", "Referer": f"{ORIGIN}/settings"}).status_code == 200
    assert name() == "Ours"
    assert b.get("/api/videos", headers=evil).status_code == 200  # reading isn't a write
    assert b.get("/api/auth/me").json()["user"] is not None  # the refused logout didn't sign out


def test_signing_in_from_another_site_is_refused():
    make_user("vol@example.org", "volunteer")
    r = browser(origin="https://evil.example").post("/api/auth/login", json={"email": "vol@example.org", "password": PASSWORD})
    assert r.status_code == 403 and "set-cookie" not in r.headers


def test_extra_origins_can_be_allowed(monkeypatch):
    make_user("vol@example.org", "volunteer")
    monkeypatch.setenv("TIDECOUNT_ALLOWED_ORIGINS", "http://localhost:5183")
    assert browser(origin="http://localhost:5183").post("/api/auth/login", json={"email": "vol@example.org", "password": PASSWORD}).status_code == 200


# --- limits ------------------------------------------------------------------------------------

def test_sign_in_is_limited_per_email():
    make_user("vol@example.org", "volunteer")
    b = browser()
    for _ in range(5):
        assert b.post("/api/auth/login", json={"email": "vol@example.org", "password": "wrong password"}).status_code == 401
    r = b.post("/api/auth/login", json={"email": "vol@example.org", "password": PASSWORD})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_sign_in_is_limited_per_address():
    b = browser()
    for i in range(10):
        assert b.post("/api/auth/login", json={"email": f"n{i}@example.org", "password": "wrong password"}).status_code == 401
    assert b.post("/api/auth/login", json={"email": "n99@example.org", "password": "wrong password"}).status_code == 429


# --- sensitive manager actions -----------------------------------------------------------------

def test_sensitive_actions_need_a_recent_password_confirmation():
    b = signed_in("manager")
    vol = make_user("vol@example.org", "volunteer")
    with db.session() as con:
        con.execute("UPDATE sessions SET reauth_at = ?", (time.time() - auth.REAUTH_S - 1,))
    r = b.patch(f"/api/team/{vol}", json={"role": "manager"})
    assert r.status_code == 403 and r.headers[auth.REAUTH_HEADER] == "required"
    assert b.delete("/api/species/library/upload-000000000000").status_code == 403
    assert b.patch("/api/surveys/sites/s-none", json={"name": "Not sensitive"}).status_code not in (401, 403)
    assert b.post("/api/auth/reauth", json={"password": "wrong password"}).status_code == 400
    assert b.post("/api/auth/reauth", json={"password": PASSWORD}).status_code == 204
    assert b.patch(f"/api/team/{vol}", json={"role": "manager"}).status_code == 200
    assert b.delete("/api/species/library/upload-000000000000").status_code == 404  # allowed, just nothing there


# --- the team ----------------------------------------------------------------------------------

def test_an_invite_link_creates_an_account_once():
    manager = signed_in("manager")
    r = manager.post("/api/team/invites", json={"emails": ["New.Person@example.org"], "role": "volunteer"})
    invite = r.json()["invites"][0]
    assert invite["email"] == "new.person@example.org"
    with db.session() as con:
        assert con.execute("SELECT token_hash FROM invites").fetchone()[0] == hashlib.sha256(invite["token"].encode()).hexdigest()

    newcomer = browser()
    assert newcomer.get(f"/api/auth/invite/{invite['token']}").json()["role"] == "volunteer"
    r = newcomer.post("/api/auth/accept-invite", json={"token": invite["token"], "name": "New Person", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["role"] == "volunteer"
    assert newcomer.get("/api/surveys").status_code == 200
    assert browser().post("/api/auth/accept-invite", json={"token": invite["token"], "name": "Again", "password": PASSWORD}).status_code == 404
    assert browser().get("/api/auth/invite/not-a-real-token").status_code == 404


def test_expired_and_cancelled_invites_dont_work():
    manager = signed_in("manager")
    first, second = manager.post("/api/team/invites", json={"emails": ["a@example.org", "b@example.org"], "role": "volunteer"}).json()["invites"]
    with db.session() as con:
        con.execute("UPDATE invites SET expires_at = ? WHERE id = ?", (time.time() - 1, first["id"]))
    assert browser().get(f"/api/auth/invite/{first['token']}").status_code == 404
    assert manager.delete(f"/api/team/invites/{second['id']}").status_code == 204
    assert browser().get(f"/api/auth/invite/{second['token']}").status_code == 404


def test_a_reset_link_sets_a_new_password_and_ends_old_sessions():
    manager = signed_in("manager")
    vol_browser = signed_in("volunteer")
    vol_id = vol_browser.get("/api/auth/me").json()["user"]["id"]
    link = manager.post(f"/api/team/{vol_id}/reset-link").json()
    assert link["kind"] == "reset"
    fresh = browser()
    assert fresh.post("/api/auth/accept-invite", json={"token": link["token"], "password": "a brand new password"}).status_code == 200
    assert vol_browser.get("/api/surveys").status_code == 401
    assert browser().post("/api/auth/login", json={"email": "volunteer@example.org", "password": "a brand new password"}).status_code == 200


def test_managers_change_others_but_never_themselves():
    manager = signed_in("manager")
    me = manager.get("/api/auth/me").json()["user"]["id"]
    assert manager.patch(f"/api/team/{me}", json={"role": "volunteer"}).status_code == 400
    assert manager.patch(f"/api/team/{me}", json={"active": False}).status_code == 400

    other = make_user("m2@example.org", "manager")
    m2 = browser()
    m2.post("/api/auth/login", json={"email": "m2@example.org", "password": PASSWORD})
    assert manager.patch(f"/api/team/{other}", json={"active": False}).status_code == 200
    assert m2.get("/api/auth/me").json()["user"] is None  # signed out at once
    assert browser().post("/api/auth/login", json={"email": "m2@example.org", "password": PASSWORD}).status_code == 401

    assert manager.patch(f"/api/team/{other}", json={"active": True, "role": "volunteer"}).status_code == 200
    m2 = browser()
    assert m2.post("/api/auth/login", json={"email": "m2@example.org", "password": PASSWORD}).json()["user"]["role"] == "volunteer"
    assert m2.patch(f"/api/team/{me}", json={"role": "volunteer"}).status_code == 403


# --- who may reach what ------------------------------------------------------------------------

PUBLIC = {
    ("GET", "/api/models"), ("GET", "/api/species"), ("GET", "/api/species/media"), ("GET", "/api/species/{name}/profile"),
    ("GET", "/api/species/{name}/occurrences/summary"), ("GET", "/api/species/{name}/occurrences/datasets"),
    ("GET", "/api/species/{name}/occurrences/nondetections"), ("GET", "/api/species/{name}/occurrences/edna"),
    ("GET", "/api/species/{name}/occurrences/grid"), ("GET", "/api/species/{name}/occurrences/records"),
    ("GET", "/api/species/library"), ("GET", "/api/species/library/{photo_id}/file"),
    ("GET", "/api/water/sites"), ("GET", "/api/water/sites/{site_id}/series"),
    # The home page's data, public for guests as before sign-in existed.
    ("GET", "/api/videos"), ("GET", "/api/videos/{video_id}/summary"), ("GET", "/api/videos/{video_id}/proxy"),
    ("GET", "/api/auth/me"), ("POST", "/api/auth/login"), ("POST", "/api/auth/logout"), ("POST", "/api/auth/setup"),
    ("POST", "/api/auth/register"), ("POST", "/api/auth/demo"),
    ("GET", "/api/auth/invite/{token}"), ("POST", "/api/auth/accept-invite"),
}
GUARDS = {auth.require_user, auth.require_manager, auth.require_recent_manager}


def _guarded(dependant) -> bool:
    return any(d.call in GUARDS or _guarded(d) for d in dependant.dependencies)


def api_routes():
    """Every API route, from each router module (app.routes hides included routers' routes in this
    FastAPI). A router's own dependencies are part of each of its routes' dependencies."""
    from tidecount.routes import (auth as a, review, schools, snapshots, species, species_library, stats, summary,
                                  surveys, team, tracks, videos, water)
    for module in (a, team, surveys, videos, tracks, review, schools, snapshots, species_library, species, summary, stats, water):
        for r in module.router.routes:
            if isinstance(r, APIRoute) and r.path.startswith("/api/"):
                for method in r.methods:
                    yield method, r.path, r


def test_the_route_list_covers_every_registered_endpoint():
    schema = TestClient(app).get("/openapi.json").json()["paths"]
    registered = {(m.upper(), p) for p, ops in schema.items() if p.startswith("/api/") for m in ops}
    assert registered == {(m, p) for m, p, _ in api_routes()}


def test_every_api_route_is_public_by_decision_or_needs_sign_in():
    unguarded = {(m, p) for m, p, r in api_routes() if not _guarded(r.dependant)}
    assert unguarded == PUBLIC, f"Decide who may call: {sorted(unguarded ^ PUBLIC)}"
    assert all(m == "GET" or p.startswith("/api/auth/") for m, p in PUBLIC)  # no public write outside sign-in


GUEST_REFUSED = [
    ("GET", "/api/videos/v1"), ("GET", "/api/videos/v1/tracks"),
    ("GET", "/api/tracks/1/crop"), ("GET", "/api/videos/v1/export.csv"), ("GET", "/api/videos/v1/protocol.csv"),
    ("GET", "/api/videos/v1/snapshots"), ("GET", "/api/snapshot-frames/1/image"), ("GET", "/api/videos/v1/frame-boxes?t=1"),
    ("GET", "/api/fish/sites/1/options"), ("GET", "/api/fish/sites/1/series"), ("GET", "/api/compare/sites/1"),
    ("GET", "/api/surveys"), ("GET", "/api/accuracy"), ("GET", "/api/team"),
    ("POST", "/api/videos"), ("POST", "/api/videos/v1/retry"), ("PUT", "/api/tracks/1/decision"), ("POST", "/api/tracks/merge"),
    ("POST", "/api/segments/1/status"), ("PUT", "/api/school-counts/1"), ("PUT", "/api/snapshot-frames/1"),
    ("POST", "/api/surveys/sites"), ("POST", "/api/species/library"), ("PUT", "/api/species/Gadus morhua/photos"),
    ("DELETE", "/api/species/library/upload-000000000000"), ("POST", "/api/team/invites"), ("POST", "/api/auth/reauth"),
]
MANAGER_ONLY = [
    ("POST", "/api/videos/v1/reanalyze"), ("POST", "/api/videos/import-path"), ("PUT", "/api/videos/v1/place"),
    ("PUT", "/api/videos/places"), ("POST", "/api/surveys/sites"), ("PATCH", "/api/surveys/sites/s1"),
    ("DELETE", "/api/surveys/sites/s1"), ("POST", "/api/species/library"),
    ("PATCH", "/api/species/library/upload-000000000000"), ("DELETE", "/api/species/library/upload-000000000000"),
    ("PUT", "/api/species/Gadus morhua/photos"), ("GET", "/api/team"), ("POST", "/api/team/invites"),
    ("PATCH", "/api/team/1"), ("POST", "/api/team/1/reset-link"), ("DELETE", "/api/team/invites/1"),
]
VOLUNTEER_WORK = [
    ("GET", "/api/videos"), ("GET", "/api/surveys"), ("GET", "/api/videos/v1"), ("GET", "/api/fish/sites/1/options"),
    ("POST", "/api/videos/v1/retry"), ("PUT", "/api/tracks/1/decision"), ("DELETE", "/api/tracks/1/decision"),
    ("PUT", "/api/tracks/decisions"), ("POST", "/api/tracks/merge"), ("POST", "/api/videos/v1/tracks"),
    ("POST", "/api/segments/1/status"), ("POST", "/api/videos/v1/events"), ("PUT", "/api/school-counts/1"),
    ("PUT", "/api/videos/v1/protocol"), ("PUT", "/api/snapshot-frames/1"), ("GET", "/api/species/library"),
    ("GET", "/api/accuracy"),  # the Summary page's accuracy figures
]


def call(b, method, path):
    return b.request(method, path, json={})


@pytest.mark.parametrize("method, path", GUEST_REFUSED)
def test_guests_are_refused_research_and_management(method, path):
    assert call(browser(), method, path).status_code == 401


@pytest.mark.parametrize("method, path", MANAGER_ONLY)
def test_volunteers_are_refused_management(method, path):
    assert call(signed_in("volunteer"), method, path).status_code == 403


@pytest.mark.parametrize("method, path", VOLUNTEER_WORK)
def test_volunteers_can_do_their_work(method, path):
    # Unknown ids give 404 or 422 here; what matters is that sign-in and role let the request through.
    assert call(signed_in("volunteer"), method, path).status_code not in (401, 403)


@pytest.mark.parametrize("method, path", MANAGER_ONLY)
def test_managers_can_do_everything(method, path):
    assert call(signed_in("manager"), method, path).status_code not in (401, 403)


def test_guests_get_the_home_pages_data_but_not_the_exports():
    b = browser()
    assert b.get("/api/videos").status_code == 200
    # Past the sign-in check (404: no such video here), as the home page needs.
    assert b.get("/api/videos/v1/summary").status_code == 404
    assert b.get("/api/videos/v1/proxy").status_code == 404
    assert b.get("/api/videos/v1/export.csv").status_code == 401
    assert b.get("/api/videos/v1/protocol.csv").status_code == 401


def test_guests_can_browse_the_public_reference_pages():
    b = browser()
    for path in ("/api/species", "/api/species/media", "/api/species/Gadus morhua/profile", "/api/species/library",
                 "/api/water/sites", "/api/models", "/api/auth/me", "/api/videos"):
        assert b.get(path).status_code == 200, path
    named = b.get("/api/species").json()[0]
    assert set(named) >= {"species", "common", "confirmed"} and not {"video", "videos", "site", "station"} & set(named)
