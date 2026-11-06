"""Freeze-frame school counts: AI proposes dots on one frame and a person corrects them."""
import threading
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel

from .. import config, db, models, settings, video
from .common import get_video

router = APIRouter()

_detectors: dict = {}
_detector_lock = threading.Lock()


def detector(key: str):
    """School counts fall back to manual dots if the model can't load."""
    with _detector_lock:
        if key not in _detectors:
            try:
                _detectors[key] = models.load_detector(key)
            except Exception:
                _detectors[key] = models.NullDetector()
        return _detectors[key]


class SchoolStart(BaseModel):
    t: float


@router.post("/api/videos/{video_id}/school-counts")
def start_school(video_id: str, body: SchoolStart):
    with db.session() as con:
        v = get_video(con, video_id)
    frame = config.FRAMES / f"{uuid.uuid4().hex[:12]}.jpg"
    video.extract_frame(v["path"], body.t, frame)
    image = Image.open(frame).convert("RGB")
    d = detector(v["detector"])
    boxes, _ = d.detect(image, settings.current().for_detector(v["detector"]).dot_threshold)
    w, h = image.size
    dots = [((x1 + x2) / 2 / w, (y1 + y2) / 2 / h) for x1, y1, x2, y2 in boxes.tolist()]
    with db.session() as con:
        cur = con.execute(
            "INSERT INTO school_counts (video_id, t, frame_path, proposed, note) VALUES (?, ?, ?, ?, ?)",
            (video_id, body.t, str(frame), len(dots), d.name),
        )
        con.executemany(
            "INSERT INTO school_dots (count_id, x, y, source) VALUES (?, ?, ?, 'ai')",
            [(cur.lastrowid, x, y) for x, y in dots],
        )
        db.log_event(con, video_id, "school_start", {"count": cur.lastrowid})
    return {"id": cur.lastrowid, "t": body.t, "dots": [{"x": x, "y": y, "source": "ai"} for x, y in dots], "model": d.name}


@router.get("/api/school-counts/{count_id}/frame")
def school_frame(count_id: int):
    with db.session() as con:
        row = con.execute("SELECT frame_path FROM school_counts WHERE id = ?", (count_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Count not found")
    return FileResponse(row["frame_path"], media_type="image/jpeg")


class Dot(BaseModel):
    x: float
    y: float
    source: str


class SchoolSave(BaseModel):
    dots: list[Dot]
    removed: int = 0


@router.put("/api/school-counts/{count_id}")
def save_school(count_id: int, body: SchoolSave):
    added = sum(1 for d in body.dots if d.source == "user")
    with db.session() as con:
        row = con.execute("SELECT video_id FROM school_counts WHERE id = ?", (count_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Count not found")
        con.execute("DELETE FROM school_dots WHERE count_id = ?", (count_id,))
        con.executemany(
            "INSERT INTO school_dots (count_id, x, y, source) VALUES (?, ?, ?, ?)",
            [(count_id, d.x, d.y, d.source) for d in body.dots],
        )
        con.execute(
            "UPDATE school_counts SET saved = 1, total = ?, removed = ?, added = ? WHERE id = ?",
            (len(body.dots), body.removed, added, count_id),
        )
        db.log_event(con, row["video_id"], "school_save", {"count": count_id, "total": len(body.dots)})
    return {"ok": True}
