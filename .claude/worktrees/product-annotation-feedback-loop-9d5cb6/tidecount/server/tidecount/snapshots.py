"""Snapshot counts: a fixed set of frames a person checks, for MeanCount and MaxN.

Frames are rows in school_counts with kind 'snapshot' or 'peak'. Status '' means not done, and
those rows hold no total. AI dots are read from saved detections, so no model loads here and the
review UI still only reads saved results.

A frame is blind when a person counted it without seeing AI's dots. Only blind frames score the AI,
because a person who sees AI's dots first tends to keep them and to miss what AI missed. Once a
frame has shown AI's dots it can never be blind, even if someone counts it again without them.
"""
import random

from . import config, db, settings

FRAME_KINDS = "kind IN ('snapshot', 'peak')"
AI_SAMPLES = (
    "FROM detections d JOIN tracks tr ON tr.id = d.track_id LEFT JOIN decisions ds ON ds.track_id = tr.id "
    "WHERE tr.video_id = ? AND tr.manual = 0 AND COALESCE(ds.state, '') != 'Rejected'"
)


def snapshot_times(duration: float, fps: int) -> list[float]:
    """Evenly spaced times, snapped to the nearest frame the worker sampled."""
    out = []
    t = float(config.SNAPSHOT_START_S)
    while t < duration:
        snapped = round(t * fps) / fps
        if snapped < duration:
            out.append(snapped)
        t += config.SNAPSHOT_EVERY_S
    return out


def pick_peaks(seconds: list[tuple[int, int]], taken: set[float], best_sample: dict[int, float] | None = None) -> list[float]:
    """Times of the highest AI counts, spaced apart, leaving out frames already in `taken`.

    `seconds` is (second, AI count). `best_sample` names the busiest sample inside a second, since
    a second's count is the highest of its samples and that may not be the one on the whole second.
    """
    best_sample = best_sample or {}
    picked: list[float] = []
    for second, count in sorted(seconds, key=lambda r: (-r[1], r[0])):
        if count <= 0 or len(picked) == config.SNAPSHOT_PEAKS:
            break
        t = best_sample.get(second, float(second))
        if t not in taken and all(abs(t - p) >= config.SNAPSHOT_PEAK_GAP_S for p in picked):
            picked.append(t)
    return sorted(picked)


def ensure_frames(con, v: dict) -> None:
    """Create a video's frames once. The unique index keeps a second request from doubling them."""
    if con.execute(f"SELECT 1 FROM school_counts WHERE video_id = ? AND {FRAME_KINDS} LIMIT 1", (v["id"],)).fetchone():
        return
    snaps = snapshot_times(v["duration"], settings.for_run(v).fps)
    seconds = [(r["second"], r["detections"]) for r in con.execute("SELECT second, detections FROM seconds WHERE video_id = ?", (v["id"],))]
    best: dict[int, float] = {}  # later rows win: the busiest sample, and the earliest of a tie
    for r in con.execute(f"SELECT d.t, COUNT(*) AS n {AI_SAMPLES} GROUP BY d.t ORDER BY n, d.t DESC", (v["id"],)):
        best[int(r["t"])] = r["t"]
    peaks = [t for t in pick_peaks(seconds, set(snaps), best) if t < v["duration"]]
    model = config.DETECTORS.get(v["detector"], {}).get("label", v["detector"])
    con.executemany(
        "INSERT OR IGNORE INTO school_counts (video_id, t, frame_path, total, note, kind) VALUES (?, ?, ?, NULL, ?, ?)",
        [(v["id"], t, str(config.FRAMES / f"snapshot-{v['id']}-{t:.3f}.jpg"), model, kind)
         for kind, times in (("snapshot", snaps), ("peak", peaks)) for t in times],
    )


def nearest(rows: list[dict], t: float) -> list[dict]:
    """The rows of the sample closest to t, and of the earlier sample when two are as close."""
    if not rows:
        return []
    sample = min({r["t"] for r in rows}, key=lambda s: (abs(s - t), s))
    return [r for r in rows if r["t"] == sample]


def ai_dots(con, video_id: str, t: float) -> list[dict]:
    """Box centres from the sample nearest t. Skips tracks a person rejected or added by hand."""
    reach = config.SNAPSHOT_DOT_REACH_S
    rows = db.rows(con.execute(f"SELECT d.t, d.x, d.y, d.w, d.h {AI_SAMPLES} AND d.t BETWEEN ? AND ?", (video_id, t - reach, t + reach)))
    return [{"x": r["x"] + r["w"] / 2, "y": r["y"] + r["h"] / 2, "source": "ai"} for r in nearest(rows, t)]


def frames(con, video_id: str) -> list[dict]:
    """A video's frames by time. `rank` is the order to count them in when a person counts on their own."""
    rows = db.rows(con.execute(
        f"SELECT id, kind, t, status, total, proposed, removed, added, blind, ai_shown FROM school_counts "
        f"WHERE video_id = ? AND {FRAME_KINDS} ORDER BY t",
        (video_id,),
    ))
    for rank, row in enumerate(count_order(rows)):
        row["rank"] = rank
    return rows


def count_order(rows: list[dict]) -> list[dict]:
    """Evenly spaced frames in a fixed random order, then peak frames by time.

    Someone who stops early has then still covered the whole video. It's the order ml/bench.py used
    for the same number of frames, so labels made there are the first frames offered here.
    """
    snaps = [r for r in rows if r["kind"] == "snapshot"]
    random.Random(config.SNAPSHOT_ORDER_SEED).shuffle(snaps)
    return snaps + [r for r in rows if r["kind"] != "snapshot"]


def stats(con, video_id: str) -> dict:
    """Only frames a person saved reach these numbers. Could-not-see frames have no total at all."""
    rows = db.rows(con.execute("SELECT kind, status, saved, total FROM school_counts WHERE video_id = ?", (video_id,)))
    snaps = [r for r in rows if r["kind"] == "snapshot"]
    peaks = [r for r in rows if r["kind"] == "peak"]
    counted = [r["total"] for r in snaps if r["status"] == "checked"]
    blind = sum(1 for r in snaps if r["status"] == "could_not_see")
    every = [r["total"] for r in rows if r["status"] == "checked" or (r["kind"] == "school" and r["saved"])]
    complete = bool(snaps) and len(counted) + blind == len(snaps)
    return {
        "frames_total": len(snaps),
        "frames_checked": len(counted),
        "frames_done": len(counted) + blind,
        "could_not_see": blind,
        "peak_total": len(peaks),
        "peak_checked": sum(1 for r in peaks if r["status"] == "checked"),
        "peak_could_not_see": sum(1 for r in peaks if r["status"] == "could_not_see"),
        "mean_count": sum(counted) / len(counted) if counted else None,
        "largest_count": max(every, default=None),
        "largest_label": "MaxN" if complete else "Largest count in checked frames",
        "complete": complete,
    }


def ai_box_rows(con, video_id: str, t: float) -> list[dict]:
    """Every AI box in the sample nearest t, surest first, with its track and what a person decided about it."""
    reach = config.SNAPSHOT_DOT_REACH_S
    rows = db.rows(con.execute(
        "SELECT d.t, d.x, d.y, d.w, d.h, d.conf, d.track_id, ds.state, ds.species FROM detections d "
        "JOIN tracks tr ON tr.id = d.track_id LEFT JOIN decisions ds ON ds.track_id = tr.id "
        "WHERE tr.video_id = ? AND tr.manual = 0 AND d.t BETWEEN ? AND ?", (video_id, t - reach, t + reach),
    ))
    return sorted(nearest(rows, t), key=lambda r: -r["conf"])


def ai_boxes(con, video_id: str, t: float) -> list[tuple[float, float, float, float]]:
    """The same boxes as corners, whatever a person decided about their tracks."""
    return [(r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"]) for r in ai_box_rows(con, video_id, t)]


def claimed(boxes: list, dots: list) -> int:
    """Each box, surest first, can claim one dot inside it. A claimed dot is a fish AI found.

    The same rule as `claimed` in ml/bench.py, so the app and the benchmark score alike.
    """
    open_dots, found = list(dots), 0
    for x1, y1, x2, y2 in boxes:
        for dot in open_dots:
            if x1 <= dot[0] <= x2 and y1 <= dot[1] <= y2:
                open_dots.remove(dot)
                found += 1
                break
    return found


def blind_labels(con, root_id: str) -> dict[float, list[tuple[float, float]]]:
    """Dots from blind frames, by time. Runs of one video share them, since the footage is the same."""
    frames = db.rows(con.execute(
        "SELECT c.id, c.t FROM school_counts c JOIN videos v ON v.id = c.video_id "
        "WHERE (v.id = ? OR v.source_id = ?) AND c.kind = 'snapshot' AND c.status = 'checked' AND c.blind = 1 ORDER BY c.id",
        (root_id, root_id),
    ))
    out: dict[float, list[tuple[float, float]]] = {}
    for frame in frames:
        dots = [(r["x"], r["y"]) for r in con.execute("SELECT x, y FROM school_dots WHERE count_id = ?", (frame["id"],))]
        out.setdefault(round(frame["t"], 3), dots)
    return out


def accuracy(con) -> dict:
    """How many fish a person counted blind, and how many of them AI had boxed, for every run."""
    rows = []
    for v in db.rows(con.execute("SELECT * FROM videos WHERE status = 'Ready to review' ORDER BY created_at DESC")):
        ensure_frames(con, v)
        mine = [f for f in frames(con, v["id"]) if f["kind"] == "snapshot"]
        labels = blind_labels(con, v["source_id"] or v["id"])
        fish = found = boxes = 0
        for t, dots in labels.items():
            near = ai_boxes(con, v["id"], t)
            fish += len(dots)
            boxes += len(near)
            found += claimed(near, dots)
        rows.append({
            "id": v["id"], "name": v["name"], "site": v["site"], "detector": v["detector"],
            "model": config.DETECTORS.get(v["detector"], {}).get("label", v["detector"]),
            "frames_total": len(mine),
            "frames_blind": len(labels),
            "frames_assisted": sum(1 for f in mine if f["status"] == "checked" and not f["blind"]),
            "frames_could_not_see": sum(1 for f in mine if f["status"] == "could_not_see"),
            "fish": fish, "found": found, "missed": fish - found, "extra_boxes": boxes - found,
        })
    return {"videos": rows}


def label_file(con, video_id: str) -> dict:
    """Blind frames in the form ml/bench.py reads: a name made from the seconds, and dots from 0 to 1."""
    out = {}
    for f in frames(con, video_id):
        if f["kind"] != "snapshot" or not f["blind"] or not f["status"]:
            continue
        dots = [[r["x"], r["y"]] for r in con.execute("SELECT x, y FROM school_dots WHERE count_id = ?", (f["id"],))]
        out[f"{f['t']:08.2f}.jpg"] = {"status": "labelled" if f["status"] == "checked" else "could_not_see", "points": dots}
    return out
