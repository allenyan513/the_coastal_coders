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
import math

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


def shannon(counts: list[int]) -> tuple[float | None, float | None]:
    """The Shannon index H and evenness J, from how many fish there are of each species.

    H = -sum(p * ln p), where p is each species' share of all the fish. H is 0 with one species
    and grows with more species and with a more even split between them.
    J = H / ln(S), where S is the number of species. J runs from 0 (one species has nearly all
    the fish) to 1 (every species has the same number). It needs at least two species.
    """
    counts = [n for n in counts if n > 0]  # a species with no fish takes no share
    total = sum(counts)
    if total == 0:
        return None, None  # no fish: there is nothing to measure
    h = -sum((n / total) * math.log(n / total) for n in counts)
    h = abs(h)  # one species gives -0.0, which should read as 0.0
    j = h / math.log(len(counts)) if len(counts) > 1 else None
    return h, j


def simpson(counts: list[int]) -> tuple[float | None, float | None]:
    """Simpson's diversity (1 - D) and inverse Simpson (1 / D), where D = sum(p squared).

    1 - D is the chance two fish picked at random are different species, from 0 to 1.
    1 / D is the effective number of species: how many equally common species give the same D.
    """
    counts = [n for n in counts if n > 0]
    total = sum(counts)
    if total == 0:
        return None, None
    d = (sum((n/total)**2 for n in counts))
    return 1-d, 1/d


def diversity(con, video_id: str) -> dict:
    """Shannon and Simpson diversity of the confirmed fish, using each species' MaxN as its number of fish.

    MaxN is used rather than entries because one fish split into several tracks would count
    as several entries and make that species look more common than it is. MaxN can't be
    raised that way. "Fish, unidentified" is left out, since it isn't one species.
    """
    m = maxn(con, video_id)
    named = [r for r in m["species"] if r["species"] != UNIDENTIFIED]
    h, j = shannon([r["maxn"] for r in named])
    simpson_d, inverse_d = simpson([r["maxn"] for r in named])
    total = sum([r["maxn"] for r in named])
    return {
        "shannon": h,
        "evenness": j,
        "simpson_diversity": simpson_d,
        "inverse_simpson": inverse_d,
        "richness": len(named),
        "species": [{"species": r["species"], "maxn": r["maxn"], "share": r["maxn"] / total} for r in named],
        "unidentified_maxn": next((r["maxn"] for r in m["species"] if r["species"] == UNIDENTIFIED), 0),
        "undecided_tracks": m["undecided_tracks"],
        "partial": m["partial"],
    }
