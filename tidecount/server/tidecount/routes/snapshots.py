"""Snapshot count endpoints. The rules are in tidecount/snapshots.py."""
import json
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .. import config, db, settings, snapshots as rules, video
from .common import get_video
from .schools import Dot

router = APIRouter()


def get_snapshot(con, count_id: int) -> dict:
    row = con.execute(f"SELECT * FROM school_counts WHERE id = ? AND {rules.FRAME_KINDS}", (count_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Snapshot frame not found")
    return dict(row)


@router.get("/api/videos/{video_id}/snapshots")
def snapshot_list(video_id: str):
    """Opening the screen creates the frames, so videos analysed earlier work with no rerun."""
    with db.session() as con:
        v = get_video(con, video_id)
        if v["status"] != "Ready to review":
            raise HTTPException(409, "Snapshot count opens once analysis has finished.")
        rules.ensure_frames(con, v)
        return {
            "video": {k: v[k] for k in ("id", "name", "duration", "width", "height")},
            "frames": rules.frames(con, video_id),
            "stats": rules.stats(con, video_id),
            "protocol": rules.window(con, v),
        }


class ProtocolSave(BaseModel):
    window_start: float | None = None
    visibility: str = ""
    juveniles: int | None = Field(None, ge=0, le=1)


@router.put("/api/videos/{video_id}/protocol")
def protocol_save(video_id: str, body: ProtocolSave):
    """The window, and what's recorded once per video. No window means the suggested one."""
    if body.visibility and body.visibility not in config.VISIBILITY:
        raise HTTPException(400, "Unknown visibility category")
    with db.session() as con:
        v = get_video(con, video_id)
        if body.window_start is not None and not 0 <= body.window_start < v["duration"]:
            raise HTTPException(400, "The analysis window has to start inside the video.")
        con.execute(
            "UPDATE videos SET window_start = ?, visibility = ?, juveniles = ? WHERE id = ?",
            (body.window_start, body.visibility, body.juveniles, video_id),
        )
        db.log_event(con, video_id, "protocol_save", body.model_dump())
    return {"ok": True}


@router.get("/api/snapshot-frames/{count_id}")
def snapshot_frame(count_id: int, blind: bool = False):
    """A saved frame shows what the person saved. Any other frame shows AI dots, which aren't stored.

    A blind request gets no AI dots at all, so they never reach the screen. Any other request for
    an unsaved frame shows AI's answer, even when that answer is no dots, so the frame is marked
    and can't be saved as blind later.
    """
    with db.session() as con:
        row = get_snapshot(con, count_id)
        if row["status"] == "checked":
            dots = db.rows(con.execute("SELECT x, y, source FROM school_dots WHERE count_id = ?", (count_id,)))
        elif blind:
            dots = []
        else:
            dots = rules.ai_dots(con, row["video_id"], row["t"])
            con.execute("UPDATE school_counts SET ai_shown = 1 WHERE id = ?", (count_id,))
            row["ai_shown"] = 1
    return {"id": count_id, "t": row["t"], "kind": row["kind"], "status": row["status"], "dots": dots, "model": row["note"],
            "ai_shown": bool(row["ai_shown"]), "invertebrates": row["invertebrates"], "species": json.loads(row["species"] or "[]"),
            "visibility": row["visibility"], "comment": row["comment"]}


@router.get("/api/snapshot-frames/{count_id}/image")
def snapshot_image(count_id: int):
    """Taken from the original video the first time it's needed, then cached."""
    with db.session() as con:
        row = get_snapshot(con, count_id)
        v = get_video(con, row["video_id"])
    frame = Path(row["frame_path"])
    if not frame.exists():
        part = frame.with_name(f"{frame.stem}-{uuid.uuid4().hex[:8]}.jpg")
        try:
            video.extract_frame(v["path"], row["t"], part)
            part.replace(frame)
        except (subprocess.CalledProcessError, OSError):
            raise HTTPException(409, "This frame can't be read from the original video.")
        finally:
            part.unlink(missing_ok=True)
    return FileResponse(frame, media_type="image/jpeg")


@router.get("/api/snapshot-frames/{count_id}/clip")
def snapshot_clip(count_id: int):
    """The seconds either side of a frame, from the original video, made the first time and then cached."""
    with db.session() as con:
        row = get_snapshot(con, count_id)
        v = get_video(con, row["video_id"])
    context = settings.current().protocol.context_s
    start = max(0.0, row["t"] - context)
    clip = config.FRAMES / f"clip-{row['video_id']}-{row['t']:.3f}-{context}.mp4"
    if not clip.exists():
        part = clip.with_name(f"{clip.stem}-{uuid.uuid4().hex[:8]}.mp4")
        try:
            video.extract_clip(v["path"], start, row["t"] + context - start, part)
            part.replace(clip)
        except (subprocess.CalledProcessError, OSError):
            raise HTTPException(409, "This clip can't be read from the original video.")
        finally:
            part.unlink(missing_ok=True)
    return FileResponse(clip, media_type="video/mp4")


class SpeciesCount(BaseModel):
    name: str = Field(min_length=1)
    n: int = Field(ge=1)


class SnapshotSave(BaseModel):
    status: str
    dots: list[Dot] = []
    ai_hidden: bool = False
    blind: bool = False
    invertebrates: int = Field(0, ge=0)
    species: list[SpeciesCount] = []
    visibility: str = ""
    comment: str = ""
    counter: str = ""  # who counted it, from the web's simulated sign-in, so they can't validate their own point


@router.put("/api/snapshot-frames/{count_id}")
def snapshot_save(count_id: int, body: SnapshotSave):
    if body.status not in ("checked", "could_not_see"):
        raise HTTPException(400, "Unknown status")
    dots = body.dots if body.status == "checked" else []
    total = len(dots) if body.status == "checked" else None
    if body.visibility and body.visibility not in config.VISIBILITY:
        raise HTTPException(400, "Unknown visibility category")
    species = [s.model_dump() for s in body.species] if body.status == "checked" else []
    if total is not None and sum(s["n"] for s in species) > total:
        raise HTTPException(400, "Species counts add up to more than the fish in this frame.")
    invertebrates = body.invertebrates if body.status == "checked" else None
    with db.session() as con:
        row = get_snapshot(con, count_id)
        # Blind only holds if every dot is the person's own and AI's dots never showed on this frame.
        # A frame saved blind stays blind when it's saved again, whichever way it was opened.
        blind = (body.blind or bool(row["blind"])) and not row["ai_shown"] and all(d.source == "user" for d in dots)
        proposed = 0 if blind else len(rules.ai_dots(con, row["video_id"], row["t"]))
        kept = sum(1 for d in dots if d.source == "ai")
        added = len(dots) - kept
        removed = max(0, proposed - kept) if body.status == "checked" else 0
        con.execute("DELETE FROM school_dots WHERE count_id = ?", (count_id,))
        con.executemany(
            "INSERT INTO school_dots (count_id, x, y, source) VALUES (?, ?, ?, ?)",
            [(count_id, d.x, d.y, d.source) for d in dots],
        )
        con.execute(
            "UPDATE school_counts SET saved = 1, status = ?, total = ?, proposed = ?, removed = ?, added = ?, blind = ?, "
            "invertebrates = ?, species = ?, visibility = ?, comment = ?, counter = COALESCE(NULLIF(?, ''), counter) WHERE id = ?",
            (body.status, total, proposed, removed, added, int(blind), invertebrates, json.dumps(species), body.visibility, body.comment,
             body.counter.strip(), count_id),
        )
        db.log_event(con, row["video_id"], "snapshot_save", {
            "count": count_id, "kind": row["kind"], "t": row["t"], "status": body.status, "total": total,
            "proposed": proposed, "removed": removed, "added": added, "ai_hidden": body.ai_hidden, "blind": blind,
        })
        return {"stats": rules.stats(con, row["video_id"])}


@router.get("/api/accuracy")
def accuracy():
    """Opening the page creates each video's frames, as the snapshot screen does."""
    with db.session() as con:
        return rules.accuracy(con)


@router.get("/api/videos/{video_id}/labels.json")
def labels(video_id: str):
    with db.session() as con:
        v = get_video(con, video_id)
        body = rules.label_file(con, video_id)
    name = Path(v["name"]).stem
    return JSONResponse(body, headers={"Content-Disposition": f'attachment; filename="{name}-labels.json"'})
