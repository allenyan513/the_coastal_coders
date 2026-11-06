"""Merging tracks a person says are one fish, and undoing that.

Plain functions on a connection, so they can be called and tested without HTTP. They raise
MergeError for a request that can't be carried out.
"""
import json

from . import db


class MergeError(ValueError):
    pass


def merge(con, track_ids: list[int]) -> int:
    """Keep the earliest track and its decision, and return its id."""
    ids = sorted(set(track_ids))
    if len(ids) < 2:
        raise MergeError("Choose at least two tracks.")
    marks = ",".join("?" * len(ids))
    items = db.rows(con.execute(f"SELECT * FROM tracks WHERE id IN ({marks}) ORDER BY first_t", ids))
    if len(items) != len(ids) or len({t["video_id"] for t in items}) != 1:
        raise MergeError("These tracks can't be merged.")
    keep = items[0]
    others = [t["id"] for t in items[1:]]
    strongest = max(items, key=lambda t: t["conf"])
    snapshot = _snapshot(con, items, ids, others, marks)
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
    db.log_event(con, keep["video_id"], "merge", {"keep": keep["id"], "merged": others})
    db.log_event(con, keep["video_id"], "merge_snapshot", {"keep": keep["id"], "snapshot": snapshot})
    return keep["id"]


def _snapshot(con, items: list[dict], ids: list[int], others: list[int], marks: str) -> dict:
    """What a merge is about to change, logged beside its event so the merge can be undone."""
    rest = ",".join("?" * len(others))
    return {
        "tracks": items,
        "detections": [[r["rowid"], r["track_id"]] for r in con.execute(f"SELECT rowid, track_id FROM detections WHERE track_id IN ({rest})", others)],
        "candidates": db.rows(con.execute(f"SELECT * FROM candidates WHERE track_id IN ({marks})", ids)),
        "decisions": db.rows(con.execute(f"SELECT * FROM decisions WHERE track_id IN ({marks})", ids)),
    }


def unmerge(con, track_id: int) -> list[int]:
    """Undo the latest merge into this track, putting its tracks, candidates and decisions back."""
    row = con.execute(
        "SELECT video_id, payload FROM events WHERE type = 'merge_snapshot' AND json_extract(payload, '$.keep') = ? ORDER BY id DESC LIMIT 1",
        (track_id,),
    ).fetchone()
    snapshot = json.loads(row["payload"]).get("snapshot") if row else None
    if not snapshot or con.execute("SELECT 1 FROM tracks WHERE id = ?", (snapshot["tracks"][1]["id"],)).fetchone():
        raise MergeError("This merge can't be undone.")
    ids = [t["id"] for t in snapshot["tracks"]]
    marks = ",".join("?" * len(ids))
    con.execute(f"DELETE FROM tracks WHERE id IN ({marks})", ids)
    con.execute(f"DELETE FROM candidates WHERE track_id IN ({marks})", ids)
    con.execute(f"DELETE FROM decisions WHERE track_id IN ({marks})", ids)
    for table, items in (("tracks", snapshot["tracks"]), ("candidates", snapshot["candidates"]), ("decisions", snapshot["decisions"])):
        for item in items:
            con.execute(f"INSERT INTO {table} ({','.join(item)}) VALUES ({','.join('?' * len(item))})", list(item.values()))
    con.executemany("UPDATE detections SET track_id = ? WHERE rowid = ?", [(owner, rowid) for rowid, owner in snapshot["detections"]])
    db.log_event(con, row["video_id"], "unmerge", {"keep": track_id, "restored": ids[1:]})
    return ids
