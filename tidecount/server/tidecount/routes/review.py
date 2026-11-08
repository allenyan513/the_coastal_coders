"""The review queue: segment status and the event log."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import auth, db

# Review is research work: any signed-in volunteer or manager.
router = APIRouter(dependencies=auth.SIGNED_IN)


class SegmentStatus(BaseModel):
    status: str


@router.post("/api/segments/{segment_id}/status")
def segment_status(segment_id: int, body: SegmentStatus):
    if body.status not in ("needs_review", "reviewed", "could_not_see"):
        raise HTTPException(400, "Unknown status")
    with db.session() as con:
        row = con.execute("SELECT video_id FROM segments WHERE id = ?", (segment_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Segment not found")
        con.execute("UPDATE segments SET status = ? WHERE id = ?", (body.status, segment_id))
        db.log_event(con, row["video_id"], "segment", {"segment": segment_id, "status": body.status})
    return {"ok": True}


class Event(BaseModel):
    type: str
    payload: dict = {}


@router.post("/api/videos/{video_id}/events")
def event(video_id: str, body: Event):
    with db.session() as con:
        db.log_event(con, video_id, body.type, body.payload)
    return {"ok": True}
