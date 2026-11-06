"""Snapshot count endpoints. The rules are in tidecount/snapshots.py."""
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import db, snapshots as rules, video
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
        }


@router.get("/api/snapshot-frames/{count_id}")
def snapshot_frame(count_id: int):
    """A saved frame shows what the person saved. Any other frame shows AI dots, which aren't stored."""
    with db.session() as con:
        row = get_snapshot(con, count_id)
        if row["status"] == "checked":
            dots = db.rows(con.execute("SELECT x, y, source FROM school_dots WHERE count_id = ?", (count_id,)))
        else:
            dots = rules.ai_dots(con, row["video_id"], row["t"])
    return {"id": count_id, "t": row["t"], "kind": row["kind"], "status": row["status"], "dots": dots, "model": row["note"]}


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


class SnapshotSave(BaseModel):
    status: str
    dots: list[Dot] = []
    ai_hidden: bool = False


@router.put("/api/snapshot-frames/{count_id}")
def snapshot_save(count_id: int, body: SnapshotSave):
    if body.status not in ("checked", "could_not_see"):
        raise HTTPException(400, "Unknown status")
    dots = body.dots if body.status == "checked" else []
    total = len(dots) if body.status == "checked" else None
    with db.session() as con:
        row = get_snapshot(con, count_id)
        proposed = len(rules.ai_dots(con, row["video_id"], row["t"]))
        kept = sum(1 for d in dots if d.source == "ai")
        added = len(dots) - kept
        removed = max(0, proposed - kept) if body.status == "checked" else 0
        con.execute("DELETE FROM school_dots WHERE count_id = ?", (count_id,))
        con.executemany(
            "INSERT INTO school_dots (count_id, x, y, source) VALUES (?, ?, ?, ?)",
            [(count_id, d.x, d.y, d.source) for d in dots],
        )
        con.execute(
            "UPDATE school_counts SET saved = 1, status = ?, total = ?, proposed = ?, removed = ?, added = ? WHERE id = ?",
            (body.status, total, proposed, removed, added, count_id),
        )
        db.log_event(con, row["video_id"], "snapshot_save", {
            "count": count_id, "kind": row["kind"], "t": row["t"], "status": body.status, "total": total,
            "proposed": proposed, "removed": removed, "added": added, "ai_hidden": body.ai_hidden,
        })
        return {"stats": rules.stats(con, row["video_id"])}
