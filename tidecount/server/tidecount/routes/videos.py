"""Videos and runs: import, list, detail, the playable copy, reruns and model comparison."""
import shutil
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import analysis_queue, config, db, models, settings, surveys, video
from .common import check_detector, get_video

router = APIRouter()


@router.get("/api/models")
def list_models():
    out = []
    default = settings.current().default_detector
    for key, spec in config.DETECTORS.items():
        ok, why = models.available(key)
        out.append({"key": key, "label": spec["label"], "available": ok, "note": why, "default": key == default})
    return out


class Reanalyze(BaseModel):
    detector: str


@router.post("/api/videos/{video_id}/reanalyze")
def reanalyze(video_id: str, body: Reanalyze):
    """Run another model on the same footage. Each run keeps its own results and decisions."""
    check_detector(body.detector)
    with db.session() as con:
        v = get_video(con, video_id)
        root = v["source_id"] or v["id"]
        taken = con.execute(
            "SELECT id FROM videos WHERE (id = ? OR source_id = ?) AND detector = ?", (root, root, body.detector)
        ).fetchone()
        if taken:
            raise HTTPException(409, "This video already has a run with that model.")
        new_id = uuid.uuid4().hex[:10]
        con.execute(
            "INSERT INTO videos (id, name, path, site, detector, source_id, station_id, filmed_on, duration, queued_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id, v["name"], v["path"], v["site"], body.detector, root, v["station_id"], v["filmed_on"], v["duration"], time.time()),
        )
    return {"id": new_id}


@router.get("/api/videos/{video_id}/compare")
def compare(video_id: str):
    with db.session() as con:
        v = get_video(con, video_id)
        root = v["source_id"] or v["id"]
        runs = db.rows(con.execute("SELECT * FROM videos WHERE id = ? OR source_id = ? ORDER BY created_at", (root, root)))
        out = []
        for r in runs:
            seconds = db.rows(con.execute("SELECT second, detections FROM seconds WHERE video_id = ? ORDER BY second", (r["id"],)))
            tracks_n = con.execute("SELECT COUNT(*) AS n FROM tracks WHERE video_id = ?", (r["id"],)).fetchone()["n"]
            boxes = con.execute(
                "SELECT COUNT(*) AS n FROM detections d JOIN tracks t ON t.id = d.track_id WHERE t.video_id = ?", (r["id"],)
            ).fetchone()["n"]
            review = con.execute(
                "SELECT COALESCE(SUM(end - start), 0) AS s FROM segments WHERE video_id = ? AND status != 'skipped'", (r["id"],)
            ).fetchone()["s"]
            spec = config.DETECTORS.get(r["detector"], {})
            out.append({
                "id": r["id"], "detector": r["detector"], "label": spec.get("label", r["detector"]),
                "status": r["status"], "stage": r["stage"], "progress": r["progress"], "error": r["error"],
                "tracks": tracks_n, "boxes": boxes, "seconds": seconds,
                "seconds_with_fish": sum(1 for s in seconds if s["detections"]), "to_review": review,
                "ms_per_frame": r["analysis_s"] / r["frames"] * 1000 if r["frames"] else 0,
            })
        return {"name": v["name"], "duration": v["duration"], "width": v["width"], "height": v["height"], "runs": out}


@router.get("/api/videos")
def list_videos():
    with db.session() as con:
        out = db.rows(con.execute("SELECT * FROM videos ORDER BY created_at DESC"))
        waits = analysis_queue.estimate(con)
        for v in out:
            v["queue"] = waits.get(v["id"])
            r = con.execute(
                "SELECT COALESCE(SUM(end - start), 0) AS s FROM segments WHERE video_id = ? AND status = 'needs_review'", (v["id"],)
            ).fetchone()
            v["to_review"] = r["s"]
            del v["settings_json"]
        return out


@router.post("/api/videos")
def upload_video(file: UploadFile = File(...), site: str = Form(""), detector: str = Form(""),
                 station_id: str = Form(""), filmed_on: str = Form("")):
    """Upload a video, filed under its station in the same request, so a phone's upload lands in the right place."""
    detector = detector or settings.current().default_detector
    check_detector(detector)
    check_place(station_id, filmed_on)
    video_id = uuid.uuid4().hex[:10]
    name = Path(file.filename or "video").name
    target = config.VIDEOS / f"{video_id}{Path(name).suffix or '.mp4'}"
    with open(target, "wb") as out:
        shutil.copyfileobj(file.file, out, 1024 * 1024)
    add_video(video_id, name, target, site, detector, station_id, filmed_on)
    return {"id": video_id}


class ImportPath(BaseModel):
    path: str
    site: str = ""
    detector: str = ""
    station_id: str = ""
    filmed_on: str = ""


@router.post("/api/videos/import-path")
def import_path(body: ImportPath):
    """Reference a large file where it is, without copying it."""
    detector = body.detector or settings.current().default_detector
    check_detector(detector)
    check_place(body.station_id, body.filmed_on)
    path = Path(body.path.strip().strip('"'))
    if not path.is_file():
        raise HTTPException(400, "That file doesn't exist on this computer.")
    video_id = uuid.uuid4().hex[:10]
    add_video(video_id, path.name, path, body.site, detector, body.station_id, body.filmed_on)
    return {"id": video_id}


def add_video(video_id: str, name: str, path: Path, site: str, detector: str, station_id: str, filmed_on: str) -> None:
    """Queue a new video. Its length is read now, so its wait can be estimated before it starts. A
    file ffmpeg can't read is still queued, and the worker reports what's wrong with it as before."""
    try:
        meta = video.probe(str(path))
    except (ValueError, OSError):
        meta = {"duration": 0, "fps": 0, "width": 0, "height": 0}
    with db.session() as con:
        con.execute(
            "INSERT INTO videos (id, name, path, site, detector, station_id, filmed_on, duration, fps, width, height, queued_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (video_id, name, str(path), site, detector, station_id, filmed_on,
             meta["duration"], meta["fps"], meta["width"], meta["height"], time.time()),
        )


def check_place(station_id: str, filmed_on: str) -> None:
    """Checked before the file is saved, so a bad station doesn't leave an upload behind."""
    with db.session() as con:
        try:
            surveys.check_place(con, station_id, filmed_on)
        except surveys.Problem as e:
            raise HTTPException(e.status, str(e)) from None


@router.post("/api/videos/{video_id}/retry")
def retry(video_id: str):
    with db.session() as con:
        get_video(con, video_id)
        # To the back of the queue, behind what was already waiting.
        con.execute("UPDATE videos SET status = 'Queued', error = '', progress = 0, queued_at = ? WHERE id = ?", (time.time(), video_id))
    return {"ok": True}


@router.get("/api/videos/{video_id}")
def video_detail(video_id: str):
    with db.session() as con:
        v = get_video(con, video_id)
        del v["settings_json"]
        v["queue"] = analysis_queue.estimate(con).get(video_id)
        v["segments"] = db.rows(con.execute("SELECT * FROM segments WHERE video_id = ? ORDER BY start", (video_id,)))
        v["seconds"] = db.rows(con.execute("SELECT second, detections, clarity FROM seconds WHERE video_id = ? ORDER BY second", (video_id,)))
        return v


@router.get("/api/videos/{video_id}/proxy")
def proxy(video_id: str):
    with db.session() as con:
        v = get_video(con, video_id)
    if not v["proxy_path"] or not Path(v["proxy_path"]).exists():
        raise HTTPException(404, "The playable copy isn't ready")
    return FileResponse(v["proxy_path"], media_type="video/mp4")
