"""Statistics on the fish a person confirmed. Only human decisions reach these numbers.

MaxN here is worked out from reviewed tracks, so it can be split by species. It is the largest
number of confirmed fish of one species seen at the same moment. Because no single fish can be in
the frame twice at once, MaxN can't be inflated by one fish being split into several tracks, the
way "entries" can.

This is different from the snapshot MaxN in snapshots.py, which comes from frames a person counted
by hand and has no species. The two are returned side by side so they can be compared.

A fish counts as on screen from its first to its last sighting, including any short gap where the
detector lost it. Plain functions on a database connection, so they can be tested without HTTP.
"""
from . import db, snapshots

UNIDENTIFIED = "Fish, unidentified"


def max_overlap(spans: list[tuple[float, float]]) -> tuple[int, float | None]:
    """The most spans that cover one moment, and the earliest moment that happens.

    Each span is (first seen, last seen) in seconds. A fish that leaves at the same moment another
    arrives was on that frame with it, so both count there.
    """
    # Walk through time. Each arrival adds one fish, each departure takes one away.
    # At the same moment, arrivals go first (0 sorts before 1), so touching spans overlap.
    events = sorted([(start, 0) for start, _ in spans] + [(end, 1) for _, end in spans])
    on_screen = best = 0
    best_t = None
    for t, kind in events:
        on_screen += 1 if kind == 0 else -1
        if on_screen > best:
            best, best_t = on_screen, t
    return best, best_t


def maxn(con, video_id: str) -> dict:
    """MaxN for all confirmed fish together and for each species, with the time it happens."""
    fish = db.rows(con.execute(
        "SELECT d.species, t.first_t, t.last_t FROM decisions d JOIN tracks t ON t.id = d.track_id "
        "WHERE t.video_id = ? AND d.state IN ('Confirmed', 'Corrected')",
        (video_id,),
    ))
    undecided = con.execute(
        "SELECT COUNT(*) AS n FROM tracks t LEFT JOIN decisions d ON d.track_id = t.id WHERE t.video_id = ? AND d.track_id IS NULL",
        (video_id,),
    ).fetchone()["n"]

    # Group each confirmed fish's time on screen by its species.
    by_species: dict[str, list[tuple[float, float]]] = {}
    for f in fish:
        by_species.setdefault(f["species"] or UNIDENTIFIED, []).append((f["first_t"], f["last_t"]))

    species = []
    for name, spans in by_species.items():
        count, t = max_overlap(spans)
        species.append({"species": name, "maxn": count, "t": t, "tracks": len(spans)})
    # Biggest MaxN first, then by name, with unidentified fish last.
    species.sort(key=lambda r: (r["species"] == UNIDENTIFIED, -r["maxn"], r["species"]))

    total, total_t = max_overlap([(f["first_t"], f["last_t"]) for f in fish])
    snap = snapshots.stats(con, video_id)
    return {
        "maxn": total,
        "maxn_t": total_t,
        "species": species,
        "confirmed_tracks": len(fish),
        # Tracks nobody has decided on yet. While any are left, MaxN may still go up.
        "undecided_tracks": undecided,
        "partial": undecided > 0,
        # The hand-counted MaxN from snapshot frames, for comparison.
        "snapshot_maxn": snap["largest_count"],
        "snapshot_complete": snap["complete"],
    }
