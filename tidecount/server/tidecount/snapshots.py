"""Snapshot counts: a fixed set of frames a person checks, for MeanCount and MaxN.

The frames follow Coastal Action's procedure: a window of footage is chosen, sediment and set-up left
out, with one sub-sample point at equal intervals through it. MeanCount is the mean of those points.

Frames are rows in school_counts with kind 'snapshot' or 'peak'. Status '' means not done, and
those rows hold no total. A counted frame that leaves the grid, because the window moved, becomes
'retired': it's out of every number, but it's kept, and it comes back if the window does. AI dots are
read from boxes saved during analysis, so no model loads here and the review UI still only reads
saved results.

AI's count for a frame is every box the detector drew on it at the run's dot threshold, tracked or
not. Tracks are built for the review queue: one only starts on a confident box that lasts, so in a
busy frame most fish never get one. Runs from before boxes were saved fall back to tracked fish.

A frame is blind when a person counted it without seeing AI's dots. Only blind frames score the AI,
because a person who sees AI's dots first tends to keep them and to miss what AI missed. Once a
frame has shown AI's dots it can never be blind, even if someone counts it again without them.
"""
import json
import random
import statistics

from . import config, db, settings, surveys

FRAME_KINDS = "kind IN ('snapshot', 'peak')"
AI_SAMPLES = (
    "FROM detections d JOIN tracks tr ON tr.id = d.track_id LEFT JOIN decisions ds ON ds.track_id = tr.id "
    "WHERE tr.video_id = ? AND tr.manual = 0 AND COALESCE(ds.state, '') != 'Rejected'"
)


def snapshot_times(start: float, end: float, every: float, fps: int) -> list[float]:
    """Evenly spaced times from start up to end, snapped to the nearest frame the worker sampled."""
    out = []
    t = float(start)
    while t < end:
        snapped = round(t * fps) / fps
        if snapped < end:
            out.append(snapped)
        t += every
    return out


def trims(duration: float) -> tuple[float, float]:
    """Footage left out at each end. A clip much shorter than the procedure's videos keeps most of its length."""
    rules = settings.current().protocol
    return min(rules.trim_start_s, duration / 4), min(rules.trim_end_s, duration / 4)


def suggest_start(seconds: list[tuple[int, float]], duration: float) -> float:
    """The first time the water stays clear, leaving room for the whole window if the video has it.

    `seconds` is (second, clarity). Clarity falls in murky water, and each video has its own usual
    level, so it's compared with that video's median. With no clear stretch the earliest start stands.
    """
    rules = settings.current().protocol
    head, tail = trims(duration)
    latest = max(head, duration - tail - rules.window_s)
    clarity = dict(seconds)
    usual = statistics.median([c for c in clarity.values() if c > 0] or [0])
    for start in range(int(head + 0.999), int(latest) + 1):
        ahead = [clarity[s] for s in range(start, start + rules.clear_for_s) if s in clarity]
        if ahead and statistics.median(ahead) >= usual * rules.clear_share:
            return float(start)
    return head


def window(con, v: dict) -> dict:
    """The footage this video's frames come from, and the rest of the procedure the screen needs."""
    rules = settings.current().protocol
    fps = settings.for_run(v).fps
    rows = con.execute("SELECT second, clarity FROM seconds WHERE video_id = ?", (v["id"],)).fetchall()
    suggested = round(suggest_start([(r["second"], r["clarity"]) for r in rows], v["duration"]) * fps) / fps
    start = suggested if v.get("window_start") is None else v["window_start"]
    end = min(start + rules.window_s, v["duration"] - trims(v["duration"])[1])
    return {
        "start": start, "end": end, "suggested": suggested, "chosen": v.get("window_start") is not None,
        "every_s": rules.every_s, "context_s": rules.context_s, "visibility": v.get("visibility") or "",
        "juveniles": v.get("juveniles"), "visibility_options": config.VISIBILITY,
    }


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
    """Bring a video's frames in line with its window. The unique index keeps a second request from doubling them.

    Frames are never lost: one nobody started can go, but a counted one is set aside, and a frame
    back on the grid picks up its old count.
    """
    plan = window(con, v)
    snaps = snapshot_times(plan["start"], plan["end"], plan["every_s"], settings.for_run(v).fps)
    first = not con.execute(f"SELECT 1 FROM school_counts WHERE video_id = ? AND {FRAME_KINDS} LIMIT 1", (v["id"],)).fetchone()
    on_grid = set(snaps)
    for r in db.rows(con.execute("SELECT id, kind, t, saved FROM school_counts WHERE video_id = ? AND kind IN ('snapshot', 'retired')", (v["id"],))):
        if r["kind"] == "retired" and r["t"] in on_grid:
            con.execute("UPDATE school_counts SET kind = 'snapshot' WHERE id = ?", (r["id"],))
        elif r["kind"] == "snapshot" and r["t"] not in on_grid:
            if r["saved"]:
                con.execute("UPDATE school_counts SET kind = 'retired' WHERE id = ?", (r["id"],))
            else:
                con.execute("DELETE FROM school_counts WHERE id = ?", (r["id"],))
    model = config.DETECTORS.get(v["detector"], {}).get("label", v["detector"])
    insert = "INSERT OR IGNORE INTO school_counts (video_id, t, frame_path, total, note, kind) VALUES (?, ?, ?, NULL, ?, ?)"
    frame_file = lambda t: str(config.FRAMES / f"snapshot-{v['id']}-{t:.3f}.jpg")
    con.executemany(insert, [(v["id"], t, frame_file(t), model, "snapshot") for t in snaps])
    if not first:
        return
    seconds = [(r["second"], r["detections"]) for r in con.execute("SELECT second, detections FROM seconds WHERE video_id = ?", (v["id"],))]
    best: dict[int, float] = {}  # later rows win: the busiest sample, and the earliest of a tie
    for r in con.execute(f"SELECT d.t, COUNT(*) AS n {AI_SAMPLES} GROUP BY d.t ORDER BY n, d.t DESC", (v["id"],)):
        best[int(r["t"])] = r["t"]
    peaks = [t for t in pick_peaks(seconds, on_grid, best) if t < v["duration"]]
    con.executemany(insert, [(v["id"], t, frame_file(t), model, "peak") for t in peaks])


def frame_boxes(con, video_id: str, t: float) -> list[dict] | None:
    """Every box the detector drew on the frame at t, surest first. None if the run saved no boxes.

    Only that exact frame counts, since the picture a person sees is that frame and no other.
    """
    if not con.execute("SELECT 1 FROM frame_boxes WHERE video_id = ? LIMIT 1", (video_id,)).fetchone():
        return None
    v = dict(con.execute("SELECT detector, settings_json FROM videos WHERE id = ?", (video_id,)).fetchone())
    threshold = settings.for_run(v).for_detector(v["detector"]).dot_threshold
    return db.rows(con.execute(
        "SELECT x, y, w, h, conf FROM frame_boxes WHERE video_id = ? AND ABS(t - ?) < 0.001 AND conf >= ? ORDER BY conf DESC",
        (video_id, t, threshold),
    ))


def ai_dots(con, video_id: str, t: float) -> list[dict]:
    """Box centres on the frame at t, leaving out any box that sits on a track a person rejected.

    Runs from before boxes were saved use the tracked sample nearest t, and skip tracks a person
    rejected or added by hand.
    """
    boxes = frame_boxes(con, video_id, t)
    if boxes is not None:
        rejected = db.rows(con.execute(
            "SELECT d.x, d.y, d.w, d.h FROM detections d JOIN tracks tr ON tr.id = d.track_id JOIN decisions ds ON ds.track_id = tr.id "
            "WHERE tr.video_id = ? AND ds.state = 'Rejected' AND ABS(d.t - ?) < 0.001", (video_id, t),
        ))
        centres = [(b["x"] + b["w"] / 2, b["y"] + b["h"] / 2) for b in boxes]
        return [
            {"x": x, "y": y, "source": "ai"} for x, y in centres
            if not any(r["x"] <= x <= r["x"] + r["w"] and r["y"] <= y <= r["y"] + r["h"] for r in rejected)
        ]
    reach = config.SNAPSHOT_DOT_REACH_S
    rows = db.rows(con.execute(f"SELECT d.t, d.x, d.y, d.w, d.h {AI_SAMPLES} AND d.t BETWEEN ? AND ?", (video_id, t - reach, t + reach)))
    if not rows:
        return []
    sample = min({r["t"] for r in rows}, key=lambda s: (abs(s - t), s))
    return [{"x": r["x"] + r["w"] / 2, "y": r["y"] + r["h"] / 2, "source": "ai"} for r in rows if r["t"] == sample]


def frames(con, video_id: str) -> list[dict]:
    """A video's frames by time. `rank` is the order to count them in when a person counts on their own."""
    rows = db.rows(con.execute(
        f"SELECT id, kind, t, status, total, proposed, removed, added, blind, ai_shown, invertebrates, species, visibility, comment "
        f"FROM school_counts WHERE video_id = ? AND {FRAME_KINDS} ORDER BY t",
        (video_id,),
    ))
    for rank, row in enumerate(count_order(rows)):
        row["rank"] = rank
        row["species"] = json.loads(row["species"] or "[]")
    return rows


def count_order(rows: list[dict]) -> list[dict]:
    """Evenly spaced frames in a fixed random order, then peak frames by time.

    Someone who stops early has then still covered the whole window.
    """
    snaps = [r for r in rows if r["kind"] == "snapshot"]
    random.Random(config.SNAPSHOT_ORDER_SEED).shuffle(snaps)
    return snaps + [r for r in rows if r["kind"] != "snapshot"]


def stats(con, video_id: str) -> dict:
    """Only frames a person saved reach these numbers. Could-not-see frames have no total at all."""
    rows = db.rows(con.execute(
        "SELECT kind, status, saved, total, invertebrates, species FROM school_counts WHERE video_id = ? AND kind != 'retired'", (video_id,),
    ))
    snaps = [r for r in rows if r["kind"] == "snapshot"]
    peaks = [r for r in rows if r["kind"] == "peak"]
    counted = [r["total"] for r in snaps if r["status"] == "checked"]
    blind = sum(1 for r in snaps if r["status"] == "could_not_see")
    every = [r["total"] for r in rows if r["status"] == "checked" or (r["kind"] == "school" and r["saved"])]
    invertebrates = [r["invertebrates"] or 0 for r in snaps if r["status"] == "checked"]
    named = {s["name"] for r in snaps if r["status"] == "checked" for s in json.loads(r["species"] or "[]")}
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
        "invertebrate_mean": sum(invertebrates) / len(invertebrates) if invertebrates else None,
        "species_seen": sorted(named),
        "largest_count": max(every, default=None),
        "largest_label": "MaxN" if complete else "Largest count in checked frames",
        "complete": complete,
    }


def ai_boxes(con, video_id: str, t: float) -> list[tuple[float, float, float, float]]:
    """Every AI box on the frame at t, surest first, whatever a person decided about its track.

    They are the boxes behind the dots a person is offered, so the score is for the count they see.
    """
    boxes = frame_boxes(con, video_id, t)
    if boxes is not None:
        return [(b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]) for b in boxes]
    reach = config.SNAPSHOT_DOT_REACH_S
    rows = db.rows(con.execute(
        "SELECT d.t, d.x, d.y, d.w, d.h, d.conf FROM detections d JOIN tracks tr ON tr.id = d.track_id "
        "WHERE tr.video_id = ? AND tr.manual = 0 AND d.t BETWEEN ? AND ?", (video_id, t - reach, t + reach),
    ))
    if not rows:
        return []
    sample = min({r["t"] for r in rows}, key=lambda s: (abs(s - t), s))
    near = sorted((r for r in rows if r["t"] == sample), key=lambda r: -r["conf"])
    return [(r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"]) for r in near]


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
        "WHERE (v.id = ? OR v.source_id = ?) AND c.kind IN ('snapshot', 'retired') AND c.status = 'checked' AND c.blind = 1 ORDER BY c.id",
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
            "id": v["id"], "name": v["name"], "site": surveys.where(con, v)["site"], "detector": v["detector"],
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
