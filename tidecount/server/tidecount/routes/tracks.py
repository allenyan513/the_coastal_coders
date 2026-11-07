"""Tracks: listing, crops, a person's decisions, merging, and fish AI missed."""
import logging
import threading
from pathlib import Path

import cv2
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel

from .. import config, db, follow, merge as merging, settings, video
from .common import detector, get_video, suggester

router = APIRouter()
log = logging.getLogger("tidecount.tracks")


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


def name_later(track_id: int, crop) -> None:
    """Ask the species model about a fish a person added, off the request so nobody waits for it."""
    def work():
        try:
            found = suggester().suggest([Image.fromarray(crop[:, :, ::-1])], settings.current().species.top_k)[0]
            with db.session() as con:
                if con.execute("SELECT 1 FROM tracks WHERE id = ?", (track_id,)).fetchone():
                    con.executemany(
                        "INSERT INTO candidates (track_id, rank, species, common, score) VALUES (?, ?, ?, ?, ?)",
                        [(track_id, i, c["species"], c["common"], c["score"]) for i, c in enumerate(found)],
                    )
        except Exception:
            log.exception("No species suggestions for added track %s", track_id)

    threading.Thread(target=work, daemon=True).start()


@router.post("/api/videos/{video_id}/tracks")
def add_track(video_id: str, body: NewTrack):
    """A fish AI missed, from a box a person drew. It counts as a person's decision straight away.

    The box is followed through the video so the fish gets a track, a crop and species suggestions
    like AI's own. When it can't be followed, the track is the person's box at that one moment.
    """
    with db.session() as con:
        v = get_video(con, video_id)
    w, h = min(max(body.w, 0.01), 1), min(max(body.h, 0.01), 1)
    x, y = min(max(body.x, 0), 1 - w), min(max(body.y, 0), 1 - h)
    t = max(0.0, body.t)
    found = follow.Followed(hits=[(t, (x, y, w, h), 0.0)])
    width, height = v["width"] // 2 * 2, v["height"] // 2 * 2
    if width and height and Path(v["path"]).exists():
        try:
            got = follow.follow(detector(v["detector"]), v["path"], width, height, v["duration"], t, (x * width, y * height, w * width, h * height))
            got.hits = [(at, (bx / width, by / height, bw / width, bh / height), conf) for at, (bx, by, bw, bh), conf in got.hits]
            found = got
        except Exception:
            log.exception("Couldn't follow the fish added at %.2f s in %s", t, video_id)
    first, last = found.hits[0][0], found.hits[-1][0]
    with db.session() as con:
        cur = con.execute(
            # A track must end after the moment it was added, or a fish added on a segment's first frame falls outside it.
            "INSERT INTO tracks (video_id, ext_id, manual, first_t, last_t) VALUES (?, -1, 1, ?, ?)",
            (video_id, first, max(last, t + 0.1)),
        )
        track_id = cur.lastrowid
        con.executemany(
            "INSERT INTO detections (track_id, t, x, y, w, h, conf) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(track_id, at, *box, conf) for at, box, conf in found.hits],
        )
        if found.crop is not None:
            folder = config.CROPS / video_id
            folder.mkdir(parents=True, exist_ok=True)
            crop_path = folder / f"added-{track_id}.jpg"
            cv2.imwrite(str(crop_path), found.crop)
            con.execute("UPDATE tracks SET crop_path = ? WHERE id = ?", (str(crop_path), track_id))
        con.execute("INSERT INTO decisions (track_id, state, species) VALUES (?, 'Corrected', 'Fish, unidentified')", (track_id,))
        db.log_event(con, video_id, "add_fish", {"track": track_id, "points": len(found.hits), "seconds": round(last - first, 2), "stopped": found.stopped})
    if found.crop is not None and found.crop_side >= settings.current().species.min_side:
        name_later(track_id, found.crop)
    return {"id": track_id, "points": len(found.hits), "seconds": last - first}


@router.delete("/api/tracks/{track_id}")
def remove_track(track_id: int):
    """Take back a fish a person added. AI's tracks can't be removed, only marked Not a fish."""
    with db.session() as con:
        row = con.execute("SELECT video_id, manual, crop_path FROM tracks WHERE id = ?", (track_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Track not found")
        if not row["manual"]:
            raise HTTPException(400, "Only a fish a person added can be removed.")
        for table in ("detections", "candidates", "decisions"):
            con.execute(f"DELETE FROM {table} WHERE track_id = ?", (track_id,))
        con.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        db.log_event(con, row["video_id"], "remove_fish", {"track": track_id})
    if row["crop_path"]:
        Path(row["crop_path"]).unlink(missing_ok=True)
    return {"ok": True}


def overlap(a: tuple, b: tuple) -> float:
    """Intersection over union of two (x, y, w, h) boxes."""
    ix = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


@router.get("/api/videos/{video_id}/frame-boxes")
def frame_boxes(video_id: str, t: float):
    """Freeze frame: every box on the analysed frame nearest t at the run's freeze threshold, which is
    lower than the one that starts tracks, so a person can confirm fish AI wasn't sure enough to track.

    Boxes that sit on a track already (any state, a rejected one too) are left out, since that fish
    has been offered. Runs from before every box was saved run the detector on the frame instead.
    """
    with db.session() as con:
        v = get_video(con, video_id)
        threshold = settings.for_run(v).for_detector(v["detector"]).freeze_threshold
        near = con.execute(
            "SELECT t FROM frame_boxes WHERE video_id = ? ORDER BY ABS(t - ?) LIMIT 1", (video_id, t),
        ).fetchone()
        if near:
            at = near["t"]
            found = [(b["x"], b["y"], b["w"], b["h"], b["conf"]) for b in con.execute(
                "SELECT x, y, w, h, conf FROM frame_boxes WHERE video_id = ? AND ABS(t - ?) < 0.001 AND conf >= ? ORDER BY conf DESC",
                (video_id, at, threshold),
            )]
        else:
            at, found = t, None
        taken = [(d["x"], d["y"], d["w"], d["h"]) for d in con.execute(
            "SELECT d.x, d.y, d.w, d.h FROM detections d JOIN tracks tr ON tr.id = d.track_id WHERE tr.video_id = ? AND ABS(d.t - ?) <= 0.26",
            (video_id, at),
        )]
    if found is None:
        frame = config.FRAMES / f"freeze-{video_id}.jpg"
        video.extract_frame(v["path"], at, frame)
        image = Image.open(frame).convert("RGB")
        boxes, conf = detector(v["detector"]).detect(image, threshold)
        w, h = image.size
        found = [(x1 / w, y1 / h, (x2 - x1) / w, (y2 - y1) / h, float(c)) for (x1, y1, x2, y2), c in zip(boxes.tolist(), conf)]
    fresh: list[tuple] = []
    for b in sorted(found, key=lambda b: -b[4]):
        # The detector can draw two boxes on one fish, so the less sure of a near-copy is dropped.
        if all(overlap(b[:4], k) < 0.3 for k in taken) and all(overlap(b[:4], f[:4]) < 0.5 for f in fresh):
            fresh.append(b)
    return {"t": at, "threshold": threshold, "boxes": [{"x": x, "y": y, "w": w, "h": h, "conf": c} for x, y, w, h, c in fresh]}
