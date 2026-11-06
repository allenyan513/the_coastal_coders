"""Local API. Summary queries read only decisions a person made."""
import csv
import io
import json
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from PIL import Image
from pydantic import BaseModel

from . import config, db, models, video

app = FastAPI(title="TideCount")
db.init()

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


def worker_loop() -> None:
    """Analyze queued videos one at a time, so one PC never runs two heavy jobs."""
    with db.session() as con:
        con.execute("UPDATE videos SET status = 'Queued', stage = '' WHERE status = 'Analyzing'")
    server_dir = Path(__file__).resolve().parents[1]
    while True:
        with db.session() as con:
            row = con.execute("SELECT id FROM videos WHERE status = 'Queued' ORDER BY created_at LIMIT 1").fetchone()
        if row:
            subprocess.run([sys.executable, "-m", "tidecount.worker", row["id"]], cwd=server_dir)
        else:
            time.sleep(1)


threading.Thread(target=worker_loop, daemon=True).start()


def log_event(con, video_id: str, kind: str, payload: dict | None = None) -> None:
    con.execute("INSERT INTO events (video_id, type, payload) VALUES (?, ?, ?)", (video_id, kind, json.dumps(payload or {})))


def get_video(con, video_id: str) -> dict:
    row = con.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Video not found")
    return dict(row)


def review_seconds(con, video_id: str) -> float:
    """Active time: gaps over two minutes between events are treated as a break."""
    times = [r["created_at"] for r in con.execute("SELECT created_at FROM events WHERE video_id = ? ORDER BY id", (video_id,))]
    return sum(b - a for a, b in zip(times, times[1:]) if b - a <= 120)


def check_detector(key: str) -> None:
    ok, why = models.available(key)
    if not ok:
        raise HTTPException(400, why)


@app.get("/api/models")
def list_models():
    out = []
    for key, spec in config.DETECTORS.items():
        ok, why = models.available(key)
        out.append({"key": key, "label": spec["label"], "available": ok, "note": why})
    return out


class Reanalyze(BaseModel):
    detector: str


@app.post("/api/videos/{video_id}/reanalyze")
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
            "INSERT INTO videos (id, name, path, site, detector, source_id) VALUES (?, ?, ?, ?, ?, ?)",
            (new_id, v["name"], v["path"], v["site"], body.detector, root),
        )
    return {"id": new_id}


@app.get("/api/videos/{video_id}/compare")
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


@app.get("/api/videos")
def list_videos():
    with db.session() as con:
        out = db.rows(con.execute("SELECT * FROM videos ORDER BY created_at DESC"))
        for v in out:
            r = con.execute(
                "SELECT COALESCE(SUM(end - start), 0) AS s FROM segments WHERE video_id = ? AND status = 'needs_review'", (v["id"],)
            ).fetchone()
            v["to_review"] = r["s"]
        return out


@app.post("/api/videos")
def upload_video(file: UploadFile = File(...), site: str = Form(""), detector: str = Form(config.DEFAULT_DETECTOR)):
    check_detector(detector)
    video_id = uuid.uuid4().hex[:10]
    name = Path(file.filename or "video").name
    target = config.VIDEOS / f"{video_id}{Path(name).suffix or '.mp4'}"
    with open(target, "wb") as out:
        shutil.copyfileobj(file.file, out, 1024 * 1024)
    with db.session() as con:
        con.execute(
            "INSERT INTO videos (id, name, path, site, detector) VALUES (?, ?, ?, ?, ?)",
            (video_id, name, str(target), site, detector),
        )
    return {"id": video_id}


class ImportPath(BaseModel):
    path: str
    site: str = ""
    detector: str = config.DEFAULT_DETECTOR


@app.post("/api/videos/import-path")
def import_path(body: ImportPath):
    """Reference a large file where it is, without copying it."""
    check_detector(body.detector)
    path = Path(body.path.strip().strip('"'))
    if not path.is_file():
        raise HTTPException(400, "That file doesn't exist on this computer.")
    video_id = uuid.uuid4().hex[:10]
    with db.session() as con:
        con.execute(
            "INSERT INTO videos (id, name, path, site, detector) VALUES (?, ?, ?, ?, ?)",
            (video_id, path.name, str(path), body.site, body.detector),
        )
    return {"id": video_id}


@app.post("/api/videos/{video_id}/retry")
def retry(video_id: str):
    with db.session() as con:
        get_video(con, video_id)
        con.execute("UPDATE videos SET status = 'Queued', error = '', progress = 0 WHERE id = ?", (video_id,))
    return {"ok": True}


@app.get("/api/videos/{video_id}")
def video_detail(video_id: str):
    with db.session() as con:
        v = get_video(con, video_id)
        v["segments"] = db.rows(con.execute("SELECT * FROM segments WHERE video_id = ? ORDER BY start", (video_id,)))
        v["seconds"] = db.rows(con.execute("SELECT second, detections, clarity FROM seconds WHERE video_id = ? ORDER BY second", (video_id,)))
        return v


@app.get("/api/videos/{video_id}/proxy")
def proxy(video_id: str):
    with db.session() as con:
        v = get_video(con, video_id)
    if not v["proxy_path"] or not Path(v["proxy_path"]).exists():
        raise HTTPException(404, "The playable copy isn't ready")
    return FileResponse(v["proxy_path"], media_type="video/mp4")


@app.get("/api/videos/{video_id}/tracks")
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


@app.get("/api/tracks/{track_id}/crop")
def crop(track_id: int):
    with db.session() as con:
        row = con.execute("SELECT crop_path FROM tracks WHERE id = ?", (track_id,)).fetchone()
    if not row or not row["crop_path"]:
        raise HTTPException(404, "No crop for this track")
    return FileResponse(row["crop_path"], media_type="image/jpeg")


class Decision(BaseModel):
    state: str
    species: str | None = None


@app.put("/api/tracks/{track_id}/decision")
def decide(track_id: int, body: Decision):
    if body.state not in ("Confirmed", "Corrected", "Rejected"):
        raise HTTPException(400, "Unknown decision")
    with db.session() as con:
        row = con.execute("SELECT video_id FROM tracks WHERE id = ?", (track_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Track not found")
        con.execute(
            "INSERT INTO decisions (track_id, state, species) VALUES (?, ?, ?) "
            "ON CONFLICT(track_id) DO UPDATE SET state = excluded.state, species = excluded.species, decided_at = CURRENT_TIMESTAMP",
            (track_id, body.state, body.species),
        )
        log_event(con, row["video_id"], "decision", {"track": track_id, "state": body.state, "species": body.species})
    return {"ok": True}


@app.delete("/api/tracks/{track_id}/decision")
def undo(track_id: int):
    with db.session() as con:
        row = con.execute("SELECT video_id FROM tracks WHERE id = ?", (track_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Track not found")
        con.execute("DELETE FROM decisions WHERE track_id = ?", (track_id,))
        log_event(con, row["video_id"], "undo", {"track": track_id})
    return {"ok": True}


class Merge(BaseModel):
    ids: list[int]


@app.post("/api/tracks/merge")
def merge(body: Merge):
    """A person says these tracks are one fish. Keeps the earliest track and its decision."""
    ids = sorted(set(body.ids))
    if len(ids) < 2:
        raise HTTPException(400, "Choose at least two tracks.")
    marks = ",".join("?" * len(ids))
    with db.session() as con:
        items = db.rows(con.execute(f"SELECT * FROM tracks WHERE id IN ({marks}) ORDER BY first_t", ids))
        if len(items) != len(ids) or len({t["video_id"] for t in items}) != 1:
            raise HTTPException(400, "These tracks can't be merged.")
        keep = items[0]
        others = [t["id"] for t in items[1:]]
        strongest = max(items, key=lambda t: t["conf"])
        decision = con.execute(
            f"SELECT d.* FROM decisions d JOIN tracks t ON t.id = d.track_id WHERE d.track_id IN ({marks}) "
            "AND d.state != 'Rejected' ORDER BY t.first_t LIMIT 1", ids,
        ).fetchone()
        con.execute(
            "UPDATE tracks SET first_t = ?, last_t = ?, conf = ?, crop_path = ?, static = 0 WHERE id = ?",
            (keep["first_t"], max(t["last_t"] for t in items), strongest["conf"], strongest["crop_path"], keep["id"]),
        )
        rest = ",".join("?" * len(others))
        con.execute(f"UPDATE detections SET track_id = ? WHERE track_id IN ({rest})", (keep["id"], *others))
        if strongest["id"] != keep["id"]:
            con.execute("DELETE FROM candidates WHERE track_id = ?", (keep["id"],))
            con.execute("UPDATE candidates SET track_id = ? WHERE track_id = ?", (keep["id"], strongest["id"]))
        con.execute(f"DELETE FROM candidates WHERE track_id IN ({rest})", others)
        con.execute(f"DELETE FROM decisions WHERE track_id IN ({marks})", ids)
        if decision:
            con.execute("INSERT INTO decisions (track_id, state, species) VALUES (?, ?, ?)", (keep["id"], decision["state"], decision["species"]))
        con.execute(f"DELETE FROM tracks WHERE id IN ({rest})", others)
        log_event(con, keep["video_id"], "merge", {"keep": keep["id"], "merged": others})
    return {"id": keep["id"]}


class NewTrack(BaseModel):
    t: float
    x: float
    y: float
    w: float = 0.1
    h: float = 0.08


@app.post("/api/videos/{video_id}/tracks")
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
        log_event(con, video_id, "add_fish", {"track": cur.lastrowid})
    return {"id": cur.lastrowid}


class SegmentStatus(BaseModel):
    status: str


@app.post("/api/segments/{segment_id}/status")
def segment_status(segment_id: int, body: SegmentStatus):
    if body.status not in ("needs_review", "reviewed", "could_not_see"):
        raise HTTPException(400, "Unknown status")
    with db.session() as con:
        row = con.execute("SELECT video_id FROM segments WHERE id = ?", (segment_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Segment not found")
        con.execute("UPDATE segments SET status = ? WHERE id = ?", (body.status, segment_id))
        log_event(con, row["video_id"], "segment", {"segment": segment_id, "status": body.status})
    return {"ok": True}


class Event(BaseModel):
    type: str
    payload: dict = {}


@app.post("/api/videos/{video_id}/events")
def event(video_id: str, body: Event):
    with db.session() as con:
        log_event(con, video_id, body.type, body.payload)
    return {"ok": True}


class SchoolStart(BaseModel):
    t: float


@app.post("/api/videos/{video_id}/school-counts")
def start_school(video_id: str, body: SchoolStart):
    with db.session() as con:
        v = get_video(con, video_id)
    frame = config.FRAMES / f"{uuid.uuid4().hex[:12]}.jpg"
    video.extract_frame(v["path"], body.t, frame)
    image = Image.open(frame).convert("RGB")
    d = detector(v["detector"])
    boxes, _ = d.detect(image, config.DOT_THRESHOLD)
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
        log_event(con, video_id, "school_start", {"count": cur.lastrowid})
    return {"id": cur.lastrowid, "t": body.t, "dots": [{"x": x, "y": y, "source": "ai"} for x, y in dots], "model": d.name}


@app.get("/api/school-counts/{count_id}/frame")
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


@app.put("/api/school-counts/{count_id}")
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
        log_event(con, row["video_id"], "school_save", {"count": count_id, "total": len(body.dots)})
    return {"ok": True}


def build_summary(con, video_id: str) -> dict:
    v = get_video(con, video_id)
    segs = db.rows(con.execute("SELECT * FROM segments WHERE video_id = ?", (video_id,)))
    decided = db.rows(con.execute(
        "SELECT d.state, d.species, t.first_t, t.last_t FROM decisions d JOIN tracks t ON t.id = d.track_id "
        "WHERE t.video_id = ? AND d.state IN ('Confirmed', 'Corrected')", (video_id,),
    ))
    by_species: dict[str, int] = {}
    for d in decided:
        by_species[d["species"]] = by_species.get(d["species"], 0) + 1
    species = sorted(({"name": k, "entries": n} for k, n in by_species.items()), key=lambda r: -r["entries"])

    def seconds(status: str) -> float:
        return sum(s["end"] - s["start"] for s in segs if s["status"] == status)

    audits = [s for s in segs if s["is_audit"] and s["status"] in ("reviewed", "could_not_see")]
    audit_fish = sum(1 for d in decided for s in audits if d["first_t"] < s["end"] and d["last_t"] > s["start"])
    schools = db.rows(con.execute(
        "SELECT t, total, proposed, removed, added FROM school_counts WHERE video_id = ? AND saved = 1 ORDER BY t", (video_id,),
    ))
    open_suggestions = con.execute(
        "SELECT COUNT(*) AS n FROM tracks t LEFT JOIN decisions d ON d.track_id = t.id WHERE t.video_id = ? AND d.track_id IS NULL", (video_id,),
    ).fetchone()["n"]
    duration = v["duration"] or sum(s["end"] - s["start"] for s in segs)
    skipped = seconds("skipped")
    pending = seconds("needs_review")
    return {
        "video": {"id": v["id"], "name": v["name"], "site": v["site"], "duration": duration, "notes": v["notes"]},
        "entries": sum(by_species.values()),
        "species_count": sum(1 for k in by_species if k != "Fish, unidentified"),
        "species": species,
        "schools": schools,
        "reviewed": seconds("reviewed"),
        "could_not_see": seconds("could_not_see"),
        "skipped": skipped,
        "pending": pending,
        "open_suggestions": open_suggestions,
        "audit_segments": len(audits),
        "audit_total": sum(1 for s in segs if s["is_audit"]),
        "audit_fish": audit_fish,
        "partial": skipped + pending > 0,
        "review_seconds": review_seconds(con, video_id),
    }


@app.get("/api/videos/{video_id}/summary")
def summary(video_id: str):
    with db.session() as con:
        return build_summary(con, video_id)


@app.get("/api/videos/{video_id}/export.csv")
def export(video_id: str):
    with db.session() as con:
        s = build_summary(con, video_id)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["video", s["video"]["name"]])
    w.writerow(["site", s["video"]["site"]])
    w.writerow(["models", s["video"]["notes"]])
    w.writerow(["reviewed_s", round(s["reviewed"], 1)])
    w.writerow(["could_not_see_s", round(s["could_not_see"], 1)])
    w.writerow(["skipped_unreviewed_s", round(s["skipped"], 1)])
    w.writerow(["pending_s", round(s["pending"], 1)])
    w.writerow(["audit_segments_done", s["audit_segments"]])
    w.writerow(["audit_fish_found", s["audit_fish"]])
    w.writerow(["open_ai_suggestions_not_counted", s["open_suggestions"]])
    w.writerow(["active_review_s", round(s["review_seconds"], 1)])
    w.writerow([])
    w.writerow(["species", "entries"])
    for r in s["species"]:
        w.writerow([r["name"], r["entries"]])
    w.writerow([])
    w.writerow(["school_time_s", "total", "ai_proposed", "removed", "added"])
    for r in s["schools"]:
        w.writerow([round(r["t"], 2), r["total"], r["proposed"], r["removed"], r["added"]])
    name = Path(s["video"]["name"]).stem
    return PlainTextResponse(out.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}-summary.csv"'})


@app.get("/{path:path}")
def web(path: str):
    """Serve the built UI, so a single process runs the whole app."""
    target = (config.WEB_DIST / path).resolve()
    if path and target.is_file() and config.WEB_DIST.resolve() in target.parents:
        return FileResponse(target)
    index = config.WEB_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return Response("The UI isn't built yet. Run `pnpm build` in web/.", media_type="text/plain")
