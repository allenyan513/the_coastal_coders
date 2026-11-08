"""The team: who has an account, open invites, roles and access. Managers only.

Changing anyone's access is a sensitive action, so it also needs a recent password confirmation.
Tideflow sends no email: invite and reset links are returned once, for the manager to pass on.
"""
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from .. import auth, db
from ..auth import User

router = APIRouter(dependencies=auth.MANAGER)


def _link(con, *, email: str, role: str, kind: str, created_by: int, user_id: int | None = None) -> dict:
    token = secrets.token_urlsafe(32)
    now = time.time()
    cur = con.execute(
        "INSERT INTO invites (token_hash, email, role, kind, user_id, created_by, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (auth.digest(token), email, role, kind, user_id, created_by, now, now + auth.LINK_S),
    )
    return {"id": cur.lastrowid, "email": email, "role": role, "kind": kind, "token": token, "expires_at": now + auth.LINK_S}


@router.get("/api/team")
def team():
    now = time.time()
    with db.session() as con:
        members = db.rows(con.execute("SELECT id, email, name, role, active, created_at FROM users ORDER BY active DESC, name"))
        invites = db.rows(con.execute(
            "SELECT id, email, role, created_at, expires_at FROM invites WHERE kind = 'invite' AND used_at IS NULL AND expires_at > ? ORDER BY created_at",
            (now,),
        ))
    for m in members:
        m["active"] = bool(m["active"])
    return {"members": members, "invites": invites}


class NewInvites(BaseModel):
    emails: list[str]
    role: str


@router.post("/api/team/invites", dependencies=auth.RECENT_MANAGER)
def add_invites(body: NewInvites, user: User = Depends(auth.require_manager)):
    if body.role not in auth.ROLES:
        raise HTTPException(400, "Choose a role.")
    emails = list(dict.fromkeys(auth.clean_email(e) for e in body.emails))
    if not emails or len(emails) > 50:
        raise HTTPException(400, "Enter between 1 and 50 email addresses.")
    with db.session() as con:
        taken = [e for e in emails if con.execute("SELECT 1 FROM users WHERE email = ?", (e,)).fetchone()]
        if taken:
            raise HTTPException(409, f"Already on the team: {', '.join(taken)}")
        # A new invite replaces any open one for the same email, so only the newest link works.
        con.executemany("UPDATE invites SET used_at = ? WHERE kind = 'invite' AND used_at IS NULL AND email = ?",
                        [(time.time(), e) for e in emails])
        return {"invites": [_link(con, email=e, role=body.role, kind="invite", created_by=user.id) for e in emails]}


@router.delete("/api/team/invites/{invite_id}", status_code=204, dependencies=auth.RECENT_MANAGER)
def cancel_invite(invite_id: int):
    with db.session() as con:
        con.execute("UPDATE invites SET used_at = ? WHERE id = ? AND kind = 'invite' AND used_at IS NULL", (time.time(), invite_id))
    return Response(status_code=204)


@router.post("/api/team/invites/{invite_id}/renew", dependencies=auth.RECENT_MANAGER)
def renew_invite(invite_id: int, user: User = Depends(auth.require_manager)):
    """A fresh link for an open invite; the old link stops working."""
    with db.session() as con:
        row = con.execute("SELECT email, role FROM invites WHERE id = ? AND kind = 'invite' AND used_at IS NULL", (invite_id,)).fetchone()
        if not row:
            raise HTTPException(404, "That invite isn't open any more.")
        con.execute("UPDATE invites SET used_at = ? WHERE id = ?", (time.time(), invite_id))
        return _link(con, email=row["email"], role=row["role"], kind="invite", created_by=user.id)


class MemberChange(BaseModel):
    role: str | None = None
    active: bool | None = None


def _active_managers(con) -> int:
    return con.execute("SELECT COUNT(*) FROM users WHERE role = 'manager' AND active = 1").fetchone()[0]


@router.patch("/api/team/{user_id}", dependencies=auth.RECENT_MANAGER)
def change_member(user_id: int, body: MemberChange, user: User = Depends(auth.require_manager)):
    """Change a role or switch access off or on. Nobody changes their own, and the last active
    manager stays a manager, so the team can't lock itself out. Their sessions end at once."""
    if user_id == user.id:
        raise HTTPException(400, "You can't change your own role or access. Ask another manager.")
    if body.role is not None and body.role not in auth.ROLES:
        raise HTTPException(400, "Choose a role.")
    with db.session() as con:
        row = con.execute("SELECT role, active FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "No such person.")
        role = body.role if body.role is not None else row["role"]
        active = int(body.active) if body.active is not None else row["active"]
        losing_manager = row["role"] == "manager" and row["active"] and (role != "manager" or not active)
        if losing_manager and _active_managers(con) <= 1:
            raise HTTPException(400, "Tideflow needs at least one active manager.")
        con.execute("UPDATE users SET role = ?, active = ? WHERE id = ?", (role, active, user_id))
        auth.end_sessions(con, user_id)
        out = dict(con.execute("SELECT id, email, name, role, active, created_at FROM users WHERE id = ?", (user_id,)).fetchone())
    out["active"] = bool(out["active"])
    return out


@router.post("/api/team/{user_id}/reset-link", dependencies=auth.RECENT_MANAGER)
def reset_link(user_id: int, user: User = Depends(auth.require_manager)):
    """A one-time link for someone who forgot their password. Older reset links for them stop working."""
    with db.session() as con:
        row = con.execute("SELECT email, role, active FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or not row["active"]:
            raise HTTPException(404, "No active account for that person.")
        con.execute("UPDATE invites SET used_at = ? WHERE kind = 'reset' AND used_at IS NULL AND user_id = ?", (time.time(), user_id))
        return _link(con, email=row["email"], role=row["role"], kind="reset", created_by=user.id, user_id=user_id)
