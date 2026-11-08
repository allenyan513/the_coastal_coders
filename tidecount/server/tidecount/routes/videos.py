"""Videos and runs: import, list, detail, the playable copy, reruns and model comparison."""
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import auth, config, db, models, settings, surveys
from .common import check_detector, get_video

router = APIRouter()


# Public: the detection models on offer, with nothing from any recording (the front page lists them).
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


@router.post("/api/videos/{video_id}/reanalyze", dependencies=auth.MANAGER)
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
            "INSERT INTO videos (id, name, path, site, detector, source_id, station_id, filmed_on) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id, v["name"], v["path"], v["site"], body.detector, root, v["station_id"], v["filmed_on"]),
        )
    return {"id": new_id}


@router.get("/api/videos/{video_id}/compare", dependencies=auth.SIGNED_IN)
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


# Public: the home page's statistics and sample preview are built from this list, for guests too.
@router.get("/api/videos")
def list_videos():
    with db.session() as con:
        out = db.rows(con.execute("SELECT * FROM videos ORDER BY created_at DESC"))
        for v in out:
            r = con.execute(
                "SELECT COALESCE(SUM(end - start), 0) AS s FROM segments WHERE video_id = ? AND status = 'needs_review'", (v["id"],)
            ).fetchone()
            v["to_review"] = r["s"]
            del v["settings_json"]
        return out


@router.post("/api/videos", dependencies=auth.SIGNED_IN)
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
    with db.session() as con:
        con.execute(
            "INSERT INTO videos (id, name, path, site, detector, station_id, filmed_on) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (video_id, name, str(target), site, detector, station_id, filmed_on),
        )
    return {"id": video_id}


class ImportPath(BaseModel):
    path: str
    site: str = ""
    detector: str = ""
    station_id: str = ""
    filmed_on: str = ""


@router.post("/api/videos/import-path", dependencies=auth.MANAGER)
def import_path(body: ImportPath):
    """Reference a large file where it is, without copying it."""
    detector = body.detector or settings.current().default_detector
    check_detector(detector)
    check_place(body.station_id, body.filmed_on)
    path = Path(body.path.strip().strip('"'))
    if not path.is_file():
        raise HTTPException(400, "That file doesn't exist on this computer.")
    video_id = uuid.uuid4().hex[:10]
    with db.session() as con:
        con.execute(
            "INSERT INTO videos (id, name, path, site, detector, station_id, filmed_on) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (video_id, path.name, str(path), body.site, detector, body.station_id, body.filmed_on),
        )
    return {"id": video_id}


def check_place(station_id: str, filmed_on: str) -> None:
    """Checked before the file is saved, so a bad station doesn't leave an upload behind."""
    with db.session() as con:
        try:
            surveys.check_place(con, station_id, filmed_on)
        except surveys.Problem as e:
            raise HTTPException(e.status, str(e)) from None


@router.post("/api/videos/{video_id}/retry", dependencies=auth.SIGNED_IN)
def retry(video_id: str):
    with db.session() as con:
        get_video(con, video_id)
        con.execute("UPDATE videos SET status = 'Queued', error = '', progress = 0 WHERE id = ?", (video_id,))
    return {"ok": True}


@router.get("/api/videos/{video_id}", dependencies=auth.SIGNED_IN)
def video_detail(video_id: str):
    with db.session() as con:
        v = get_video(con, video_id)
        del v["settings_json"]
        v["segments"] = db.rows(con.execute("SELECT * FROM segments WHERE video_id = ? ORDER BY start", (video_id,)))
        v["seconds"] = db.rows(con.execute("SELECT second, detections, clarity FROM seconds WHERE video_id = ? ORDER BY second", (video_id,)))
        return v


# Public: the home page's sample preview plays this for guests too.
@router.get("/api/videos/{video_id}/proxy")
def proxy(video_id: str):
    with db.session() as con:
        v = get_video(con, video_id)
    if not v["proxy_path"] or not Path(v["proxy_path"]).exists():
        raise HTTPException(404, "The playable copy isn't ready")
    return FileResponse(v["proxy_path"], media_type="video/mp4")
