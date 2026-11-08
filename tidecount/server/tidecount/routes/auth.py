"""Sign-in, sign-out, the signed-in person, first-manager setup, and invite and reset links.

Every failure to sign in gives the same answer, whether the email exists or not, and sign-in is
limited per visitor address and per email.
"""
import secrets
import sqlite3
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import auth, db
from ..auth import User

router = APIRouter()
WRONG = "Email or password is wrong."


def _signed_in(con, request: Request, response: Response, user_id: int) -> dict:
    token = auth.start_session(con, user_id)
    auth.set_session_cookie(response, request, token)
    row = con.execute("SELECT id, email, name, role FROM users WHERE id = ?", (user_id,)).fetchone()
    return {"user": dict(row)}


@router.get("/api/auth/me")
def me(user: User | None = Depends(auth.viewer)):
    """The signed-in person, or null for a guest. `setup_needed` says whether there are no accounts
    yet. Sign-up (/api/auth/register) doesn't need setup, so nothing waits on it."""
    with db.session() as con:
        setup_needed = not auth.users_exist(con)
    return {"user": user.public() if user else None, "setup_needed": setup_needed}


class Demo(BaseModel):
    role: str


@router.post("/api/auth/demo")
def demo(body: Demo, request: Request, response: Response):
    """The demo sign-in: pick a role, no password. Signs into the one shared demo account for that
    role (made on first use, with a random password nobody knows, so the ordinary sign-in can never
    open it). The role is still the account's, on the server, and every permission check applies.
    Off when TIDECOUNT_DEMO_SIGNIN=0; a manager can also switch a demo account off on the Team page."""
    if not auth.demo_signin_enabled():
        raise HTTPException(404, "Demo sign-in is off on this server. Sign in with your own account.")
    auth.too_many(auth.login_by_ip.check(auth.client_ip(request)))
    if body.role not in auth.ROLES:
        raise HTTPException(400, "Choose Volunteer or Manager.")
    email, name = auth.DEMO_ACCOUNTS[body.role]
    with db.session() as con:
        row = con.execute("SELECT id, role, active FROM users WHERE email = ?", (email,)).fetchone()
        if row is None:
            try:
                user_id = con.execute("INSERT INTO users (email, name, role, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                                      (email, name, body.role, auth.hash_password(secrets.token_urlsafe(32)), time.time())).lastrowid
            except sqlite3.IntegrityError:  # two first demo sign-ins at once
                user_id = con.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()["id"]
        elif row["role"] != body.role or not row["active"]:
            raise HTTPException(403, f"The demo {body.role} account has been switched off or changed. Sign in with your own account.")
        else:
            user_id = row["id"]
        return _signed_in(con, request, response, user_id)


class Register(BaseModel):
    name: str
    email: str
    role: str


@router.post("/api/auth/register")
def register(body: Register, request: Request, response: Response):
    """Anyone may create an account, as a volunteer or a manager (the team's choice: a manager gets
    every manager permission). The server makes the password, stores only its hash, and returns it
    this once; the person is signed in straight away. An email that already has an account is
    refused, and nothing about that account changes, so knowing an email gets nobody in."""
    auth.too_many(auth.register_by_ip.check(auth.client_ip(request)))
    if body.role not in auth.ROLES:
        raise HTTPException(400, "Choose Volunteer or Manager.")
    name, email = auth.clean_name(body.name), auth.clean_email(body.email)
    if email.endswith(auth.DEMO_DOMAIN):
        raise HTTPException(400, "That address is kept for the demo accounts. Use your own email.")
    password = auth.generate_password()
    with db.session() as con:
        if con.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise HTTPException(409, "There's already an account for this email. Sign in instead, or ask a manager for a password reset link.")
        try:
            user_id = con.execute("INSERT INTO users (email, name, role, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                                  (email, name, body.role, auth.hash_password(password), time.time())).lastrowid
        except sqlite3.IntegrityError:  # the same email signed up at the same moment
            raise HTTPException(409, "There's already an account for this email. Sign in instead.") from None
        out = _signed_in(con, request, response, user_id)
    response.headers["Cache-Control"] = "no-store"  # the one response that holds the password
    return {**out, "password": password}


class Login(BaseModel):
    email: str
    password: str


@router.post("/api/auth/login")
def login(body: Login, request: Request, response: Response):
    auth.too_many(auth.login_by_ip.check(auth.client_ip(request)))
    email = (body.email or "").strip().lower()[:254]
    auth.too_many(auth.failures_by_email.peek(email))
    with db.session() as con:
        row = con.execute("SELECT id, password_hash, active FROM users WHERE email = ?", (email,)).fetchone()
        # The password is checked before `active`, so a deactivated account answers in the same time.
        if row and auth.verify_password(body.password[: auth.MAX_PASSWORD], row["password_hash"]) and row["active"]:
            return _signed_in(con, request, response, row["id"])
    if not row:
        auth.burn_time(body.password[: auth.MAX_PASSWORD])
    auth.failures_by_email.check(email)
    raise HTTPException(401, WRONG)


@router.post("/api/auth/logout", status_code=204)
def logout(request: Request, user: User | None = Depends(auth.viewer)):
    response = Response(status_code=204)
    if user:
        with db.session() as con:
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (user.session,))
    auth.clear_session_cookie(response, request)
    return response


class Profile(BaseModel):
    name: str


@router.patch("/api/auth/me")
def update_me(body: Profile, user: User = Depends(auth.require_user)):
    name = auth.clean_name(body.name)
    with db.session() as con:
        con.execute("UPDATE users SET name = ? WHERE id = ?", (name, user.id))
    return {"user": {**user.public(), "name": name}}


class PasswordChange(BaseModel):
    current: str
    new: str


@router.post("/api/auth/password", status_code=204)
def change_password(body: PasswordChange, request: Request, user: User = Depends(auth.require_user)):
    """A new password signs this person out everywhere else."""
    auth.too_many(auth.sensitive_by_ip.peek(auth.client_ip(request)))
    with db.session() as con:
        stored = con.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()["password_hash"]
        if not auth.verify_password(body.current[: auth.MAX_PASSWORD], stored):
            auth.sensitive_by_ip.check(auth.client_ip(request))
            raise HTTPException(400, "The current password is wrong.")
        problem = auth.password_problem(body.new)
        if problem:
            raise HTTPException(400, problem)
        con.execute("UPDATE users SET password_hash = ? WHERE id = ?", (auth.hash_password(body.new), user.id))
        auth.end_sessions(con, user.id, keep=user.session)
        con.execute("UPDATE sessions SET reauth_at = ? WHERE token_hash = ?", (time.time(), user.session))
    return Response(status_code=204)


class Confirm(BaseModel):
    password: str


@router.post("/api/auth/reauth", status_code=204)
def reauth(body: Confirm, request: Request, user: User = Depends(auth.require_user)):
    """Confirm the password, so sensitive manager actions are allowed for the next few minutes."""
    auth.too_many(auth.sensitive_by_ip.peek(auth.client_ip(request)))
    with db.session() as con:
        stored = con.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()["password_hash"]
        if not auth.verify_password(body.password[: auth.MAX_PASSWORD], stored):
            auth.sensitive_by_ip.check(auth.client_ip(request))
            raise HTTPException(400, "That password is wrong.")
        con.execute("UPDATE sessions SET reauth_at = ? WHERE token_hash = ?", (time.time(), user.session))
    return Response(status_code=204)


class Setup(BaseModel):
    code: str
    name: str
    email: str
    password: str


@router.post("/api/auth/setup")
def setup(body: Setup, request: Request, response: Response):
    """Create the first manager with the setup code from the server's console. Gone once anyone exists."""
    with db.session() as con:
        if auth.users_exist(con):
            raise HTTPException(404, "Tideflow already has accounts. Sign in instead.")
    auth.too_many(auth.sensitive_by_ip.check(auth.client_ip(request)))
    name, email = auth.clean_name(body.name), auth.clean_email(body.email)
    problem = auth.password_problem(body.password)
    if problem:
        raise HTTPException(400, problem)
    if not auth.take_setup_code(body.code):
        raise HTTPException(400, "That setup code isn't right, or it has expired. The server's console shows the current one.")
    with db.session() as con:
        if auth.users_exist(con):  # someone finished first
            raise HTTPException(404, "Tideflow already has accounts. Sign in instead.")
        cur = con.execute("INSERT INTO users (email, name, role, password_hash, created_at) VALUES (?, ?, 'manager', ?, ?)",
                          (email, name, auth.hash_password(body.password), time.time()))
        return _signed_in(con, request, response, cur.lastrowid)


def _open_link(con, token: str):
    row = con.execute("SELECT * FROM invites WHERE token_hash = ?", (auth.digest(token or ""),)).fetchone()
    if not row or row["used_at"] or row["expires_at"] < time.time():
        raise HTTPException(404, "This link has expired or was already used. Ask a manager for a new one.")
    return row


@router.get("/api/auth/invite/{token}")
def invite(token: str):
    """What an invite or password-reset link is for, so the page can say so."""
    with db.session() as con:
        row = _open_link(con, token)
        name = ""
        if row["kind"] == "reset":
            user = con.execute("SELECT name FROM users WHERE id = ?", (row["user_id"],)).fetchone()
            name = user["name"] if user else ""
    return {"email": row["email"], "role": row["role"], "kind": row["kind"], "name": name}


class Accept(BaseModel):
    token: str
    name: str = ""
    password: str


@router.post("/api/auth/accept-invite")
def accept_invite(body: Accept, request: Request, response: Response):
    """Set a password from an invite (a new account) or a reset link (an existing one), then sign in."""
    auth.too_many(auth.sensitive_by_ip.check(auth.client_ip(request)))
    problem = auth.password_problem(body.password)
    if problem:
        raise HTTPException(400, problem)
    with db.session() as con:
        row = _open_link(con, body.token)
        if row["kind"] == "reset":
            user = con.execute("SELECT id, active FROM users WHERE id = ?", (row["user_id"],)).fetchone()
            if not user or not user["active"]:
                raise HTTPException(404, "This account is no longer active. Ask a manager.")
            con.execute("UPDATE users SET password_hash = ? WHERE id = ?", (auth.hash_password(body.password), user["id"]))
            auth.end_sessions(con, user["id"])
            user_id = user["id"]
        else:
            name = auth.clean_name(body.name)
            if con.execute("SELECT 1 FROM users WHERE email = ?", (row["email"],)).fetchone():
                raise HTTPException(409, "There's already an account for this email. Sign in instead.")
            user_id = con.execute("INSERT INTO users (email, name, role, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                                  (row["email"], name, row["role"], auth.hash_password(body.password), time.time())).lastrowid
        con.execute("UPDATE invites SET used_at = ? WHERE id = ?", (time.time(), row["id"]))
        return _signed_in(con, request, response, user_id)
