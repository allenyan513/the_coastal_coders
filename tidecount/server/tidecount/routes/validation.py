"""Validate endpoints. The rules are in tidecount/validation.py.

There are no accounts on the server yet, so the counter's name and the approver's role come from the
web's simulated sign-in. They keep honest people from mixing up counts, not anyone determined.
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db, validation as rules
from .common import get_video
from .schools import Dot

router = APIRouter()


@router.get("/api/videos/{video_id}/validation")
def validation_report(video_id: str, viewer: str = ""):
    """Opening Validate picks the sample the first time, once every point is counted."""
    with db.session() as con:
        get_video(con, video_id)
        return rules.report(con, video_id, viewer.strip())


class ValidationSave(BaseModel):
    counter: str = Field(min_length=1)
    dots: list[Dot] = []


@router.post("/api/snapshot-frames/{count_id}/validation")
def validation_save(count_id: int, body: ValidationSave):
    counter = body.counter.strip()
    if not counter:
        raise HTTPException(400, "A count needs the name of the person who made it.")
    with db.session() as con:
        row = con.execute("SELECT id, video_id, counter FROM school_counts WHERE id = ? AND kind = 'snapshot'", (count_id,)).fetchone()
        if not row or not con.execute(
            "SELECT 1 FROM validation_samples WHERE video_id = ? AND count_id = ?", (row["video_id"], count_id),
        ).fetchone():
            raise HTTPException(404, "This point isn't one of the points picked for validation.")
        if con.execute("SELECT 1 FROM approvals WHERE video_id = ?", (row["video_id"],)).fetchone():
            raise HTTPException(409, "This video is already approved, so its counts are final.")
        if row["counter"] and row["counter"] == counter:
            raise HTTPException(409, "You counted this point, so someone else has to validate it.")
        point = next(p for p in rules.report(con, row["video_id"])["points"] if p["id"] == count_id)
        if point["state"] == "agree":
            raise HTTPException(409, "This point already agrees. No more counts are needed.")
        # Counting a point twice is only allowed when it needs a recount; the protocol prefers someone new.
        if point["state"] != "recount" and any(c["counter"] == counter for c in point["counts"]):
            raise HTTPException(409, "You've already counted this point.")
        dots = [d.model_dump() for d in body.dots]
        con.execute(
            "INSERT INTO validation_counts (count_id, counter, total, dots) VALUES (?, ?, ?, ?)",
            (count_id, counter, len(dots), json.dumps(dots)),
        )
        db.log_event(con, row["video_id"], "validation_count", {"count": count_id, "counter": counter, "total": len(dots)})
        return rules.report(con, row["video_id"], counter)


class Approval(BaseModel):
    name: str = Field(min_length=1)
    role: str


@router.post("/api/videos/{video_id}/validation/approve")
def validation_approve(video_id: str, body: Approval):
    if body.role != "manager":
        raise HTTPException(403, "Only a manager can approve a video.")
    with db.session() as con:
        get_video(con, video_id)
        state = rules.report(con, video_id)
        if not state["all_agree"]:
            raise HTTPException(409, "Every sampled point has to agree before the video can be approved.")
        if state["approval"]:
            raise HTTPException(409, "This video is already approved.")
        con.execute("INSERT INTO approvals (video_id, approver) VALUES (?, ?)", (video_id, body.name.strip()))
        db.log_event(con, video_id, "validation_approve", {"approver": body.name.strip()})
        return rules.report(con, video_id, body.name.strip())
