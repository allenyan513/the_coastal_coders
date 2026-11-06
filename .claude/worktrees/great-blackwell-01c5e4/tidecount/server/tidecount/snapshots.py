"""Snapshot counts: a fixed set of frames a person checks, for MeanCount and MaxN.

Frames are rows in school_counts with kind 'snapshot' or 'peak'. Status '' means not done, and
those rows hold no total. AI dots are read from saved detections, so no model loads here and the
review UI still only reads saved results.
"""
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


def ai_dots(con, video_id: str, t: float) -> list[dict]:
    """Box centres from the sample nearest t. Skips tracks a person rejected or added by hand."""
    reach = config.SNAPSHOT_DOT_REACH_S
    rows = db.rows(con.execute(f"SELECT d.t, d.x, d.y, d.w, d.h {AI_SAMPLES} AND d.t BETWEEN ? AND ?", (video_id, t - reach, t + reach)))
    if not rows:
        return []
    sample = min({r["t"] for r in rows}, key=lambda s: (abs(s - t), s))
    return [{"x": r["x"] + r["w"] / 2, "y": r["y"] + r["h"] / 2, "source": "ai"} for r in rows if r["t"] == sample]


def frames(con, video_id: str) -> list[dict]:
    return db.rows(con.execute(
        f"SELECT id, kind, t, status, total, proposed, removed, added FROM school_counts WHERE video_id = ? AND {FRAME_KINDS} ORDER BY t",
        (video_id,),
    ))


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
