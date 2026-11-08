"""Validate: a second person blind-counts a random sample of the counted sub-sample points.

From the protocol's Video Validation section. A different person counts a few random points without
seeing the first count. Two counts more than `max_difference` apart mean the point is counted again,
preferably by someone else. Every count keeps who made it, and the agreeing pair's average is the
point's validated value. A manager then approves the video, which isn't in the protocol: it's ours.

The draft can't decide between "6 sub-points", "6 - 12 frames" and "10%", or between "95% agreement"
and "less than 6% difference", so both numbers are settings.
"""
import random
from itertools import combinations

from . import db, settings

NOT_READY_COUNTING = "Validation opens once every sub-sample point is counted or marked could not see."
NOT_READY_EMPTY = "There are no counted points to validate."


def difference(a: int, b: int) -> float:
    """How far apart two counts are, as a share of their mean. Two zeros agree."""
    if a == b:
        return 0.0
    return abs(a - b) / ((a + b) / 2)


def _points(con, video_id: str) -> list[dict]:
    return db.rows(con.execute(
        "SELECT id, t, status, total, counter FROM school_counts WHERE video_id = ? AND kind = 'snapshot' ORDER BY t",
        (video_id,),
    ))


def ensure_sample(con, video_id: str) -> tuple[list[int], str]:
    """The sampled point ids, chosen once and kept. Empty with a reason while Count isn't finished."""
    chosen = [r["count_id"] for r in con.execute("SELECT count_id FROM validation_samples WHERE video_id = ?", (video_id,))]
    if chosen:
        return chosen, ""
    points = _points(con, video_id)
    if not points or any(p["status"] not in ("checked", "could_not_see") for p in points):
        return [], NOT_READY_COUNTING
    counted = [p["id"] for p in points if p["status"] == "checked"]
    if not counted:
        return [], NOT_READY_EMPTY
    size = min(settings.current().protocol.validate_points, len(counted))
    chosen = sorted(random.sample(counted, size))
    con.executemany("INSERT INTO validation_samples (video_id, count_id) VALUES (?, ?)", [(video_id, c) for c in chosen])
    db.log_event(con, video_id, "validation_sample", {"points": chosen})
    return chosen, ""


def _judge(counts: list[dict], limit: float) -> tuple[str, float | None, float | None]:
    """The point's state, the closest pair's difference, and the agreed value when two counts agree."""
    if len(counts) < 2:
        return "to_count", None, None
    best = min(combinations(counts, 2), key=lambda pair: difference(pair[0]["total"], pair[1]["total"]))
    gap = difference(best[0]["total"], best[1]["total"])
    if gap <= limit:
        return "agree", gap, (best[0]["total"] + best[1]["total"]) / 2
    return "recount", gap, None


def report(con, video_id: str, viewer: str = "") -> dict:
    """Every sampled point with its counts. A count's total stays hidden from anyone who hasn't
    counted that point yet, so their own count is blind, until the point agrees."""
    protocol = settings.current().protocol
    chosen, reason = ensure_sample(con, video_id)
    numbers = {p["id"]: i + 1 for i, p in enumerate(_points(con, video_id))}
    out = []
    for count_id in chosen:
        row = con.execute("SELECT id, t, total, counter FROM school_counts WHERE id = ?", (count_id,)).fetchone()
        if not row:
            continue
        counts = [{"id": None, "counter": row["counter"] or "", "total": row["total"] or 0, "original": True, "created_at": None}]
        counts += [
            {**r, "original": False}
            for r in db.rows(con.execute(
                "SELECT id, counter, total, created_at FROM validation_counts WHERE count_id = ? ORDER BY id", (count_id,),
            ))
        ]
        state, gap, agreed = _judge(counts, protocol.max_difference)
        mine = bool(viewer) and any(c["counter"] == viewer for c in counts)
        visible = state == "agree" or mine
        out.append({
            "id": count_id, "t": row["t"], "number": numbers.get(count_id), "state": state,
            "difference": gap if visible else None, "agreed": agreed,
            "original_counter": row["counter"] or "", "counted_by_viewer": mine,
            "counts": [{**c, "total": c["total"] if visible else None} for c in counts],
        })
    approval = con.execute("SELECT approver, approved_at FROM approvals WHERE video_id = ?", (video_id,)).fetchone()
    return {
        "ready": bool(chosen), "reason": reason, "sample_size": protocol.validate_points,
        "max_difference": protocol.max_difference, "points": out,
        "all_agree": bool(out) and all(p["state"] == "agree" for p in out),
        "approval": dict(approval) if approval else None,
    }
