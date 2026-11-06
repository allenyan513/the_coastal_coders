"""Tracks: listing, crops, a person's decisions, merging, and fish AI missed."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import db, merge as merging
from .common import get_video

router = APIRouter()


@router.get("/api/videos/{video_id}/tracks")
def tracks(video_id: str):
    with db.session() as con:
        items = db.rows(con.execute(
            "SELECT t.*, d.state, d.species AS decided_species FROM tracks t LEFT JOIN decisions d ON d.track_id = t.id WHERE t.video_id = ? ORDER BY t.first_t",
            (video_id,),
        ))
        by_id = {t["id"]: t for t in items}
        for t in items:
            t["points"], t["candidates"] = [], []
            t["has_crop"] = bool(t.pop("crop_path"))
        for r in con.execute(
            "SELECT d.* FROM detections d JOIN tracks t ON t.id = d.track_id WHERE t.video_id = ? ORDER BY d.t", (video_id,)
        ):
            by_id[r["track_id"]]["points"].append([r["t"], r["x"], r["y"], r["w"], r["h"]])
        for r in con.execute(
            "SELECT c.* FROM candidates c JOIN tracks t ON t.id = c.track_id WHERE t.video_id = ? ORDER BY c.rank", (video_id,)
        ):
            by_id[r["track_id"]]["candidates"].append({"species": r["species"], "common": r["common"], "score": r["score"]})
        return items


@router.get("/api/tracks/{track_id}/crop")
def crop(track_id: int):
    with db.session() as con:
        row = con.execute("SELECT crop_path FROM tracks WHERE id = ?", (track_id,)).fetchone()
    if not row or not row["crop_path"]:
        raise HTTPException(404, "No crop for this track")
    return FileResponse(row["crop_path"], media_type="image/jpeg")


class Decision(BaseModel):
    state: str
    species: str | None = None


def save_decision(con, track_id: int, state: str | None, species: str | None) -> None:
    """Write one person's decision and log it. A state of None clears the decision, as undo does."""
    if state not in (None, "Confirmed", "Corrected", "Rejected"):
        raise HTTPException(400, "Unknown decision")
    row = con.execute("SELECT video_id FROM tracks WHERE id = ?", (track_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Track not found")
    if state is None:
        con.execute("DELETE FROM decisions WHERE track_id = ?", (track_id,))
        db.log_event(con, row["video_id"], "undo", {"track": track_id})
        return
    con.execute(
        "INSERT INTO decisions (track_id, state, species) VALUES (?, ?, ?) "
        "ON CONFLICT(track_id) DO UPDATE SET state = excluded.state, species = excluded.species, decided_at = CURRENT_TIMESTAMP",
        (track_id, state, species),
    )
    db.log_event(con, row["video_id"], "decision", {"track": track_id, "state": state, "species": species})


@router.put("/api/tracks/{track_id}/decision")
def decide(track_id: int, body: Decision):
    with db.session() as con:
        save_decision(con, track_id, body.state, body.species)
    return {"ok": True}


@router.delete("/api/tracks/{track_id}/decision")
def undo(track_id: int):
    with db.session() as con:
        save_decision(con, track_id, None, None)
    return {"ok": True}


class BulkDecision(BaseModel):
    track_id: int
    state: str | None = None
    species: str | None = None


class BulkDecisions(BaseModel):
    items: list[BulkDecision]


@router.put("/api/tracks/decisions")
def decide_many(body: BulkDecisions):
    """Decide many tracks at once, for the track sheet. Each track gets the same decision row and
    event as the single-track endpoints write. All of them are saved, or none."""
    with db.session() as con:
        for item in body.items:
            save_decision(con, item.track_id, item.state, item.species)
    return {"ok": True, "count": len(body.items)}


class Merge(BaseModel):
    ids: list[int]


@router.post("/api/tracks/merge")
def merge(body: Merge):
    """A person says these tracks are one fish. The rules are in merge.py."""
    try:
        with db.session() as con:
            return {"id": merging.merge(con, body.ids)}
    except merging.MergeError as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/tracks/{track_id}/unmerge")
def unmerge(track_id: int):
    try:
        with db.session() as con:
            return {"ids": merging.unmerge(con, track_id)}
    except merging.MergeError as exc:
        raise HTTPException(400, str(exc))


class NewTrack(BaseModel):
    t: float
    x: float
    y: float
    w: float = 0.1
    h: float = 0.08


@router.post("/api/videos/{video_id}/tracks")
def add_track(video_id: str, body: NewTrack):
    """A fish AI missed. It counts as a person's decision straight away."""
    with db.session() as con:
        get_video(con, video_id)
        cur = con.execute(
            "INSERT INTO tracks (video_id, ext_id, manual, first_t, last_t) VALUES (?, -1, 1, ?, ?)",
            (video_id, body.t, body.t + 1),
        )
        con.execute(
            "INSERT INTO detections (track_id, t, x, y, w, h, conf) VALUES (?, ?, ?, ?, ?, ?, 1)",
            (cur.lastrowid, body.t, body.x, body.y, body.w, body.h),
        )
        con.execute("INSERT INTO decisions (track_id, state, species) VALUES (?, 'Corrected', 'Fish, unidentified')", (cur.lastrowid,))
        db.log_event(con, video_id, "add_fish", {"track": cur.lastrowid})
    return {"id": cur.lastrowid}
