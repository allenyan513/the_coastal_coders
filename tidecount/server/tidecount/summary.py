"""The summary and its CSV. Only decisions a person made reach these numbers."""
import csv
import io
import re
from pathlib import Path

from . import db, snapshots, stats, surveys


def review_seconds(con, video_id: str) -> float:
    """Active time: gaps over two minutes between events are treated as a break."""
    times = [r["created_at"] for r in con.execute("SELECT created_at FROM events WHERE video_id = ? ORDER BY id", (video_id,))]
    return sum(b - a for a, b in zip(times, times[1:]) if b - a <= 120)


def species_observed(con, video_id: str, points: list[dict]) -> list[str]:
    """Species named at a sub-sample point or confirmed while finding species, for the procedure's list."""
    named = {s["name"] for f in points for s in f["species"]}
    confirmed = {r["species"] for r in con.execute(
        "SELECT d.species FROM decisions d JOIN tracks t ON t.id = d.track_id "
        "WHERE t.video_id = ? AND d.state IN ('Confirmed', 'Corrected') AND d.species IS NOT NULL", (video_id,),
    )}
    return sorted((named | confirmed) - {"Fish, unidentified"})


def build(con, v: dict) -> dict:
    """`v` is the video's row."""
    video_id = v["id"]
    if v["status"] == "Ready to review":
        snapshots.ensure_frames(con, v)
    frames = snapshots.frames(con, video_id)
    points = [f for f in frames if f["kind"] == "snapshot"]
    plan = snapshots.window(con, v)
    segs = db.rows(con.execute("SELECT * FROM segments WHERE video_id = ?", (video_id,)))
    decided = db.rows(con.execute(
        "SELECT d.state, d.species, t.first_t, t.last_t, t.manual FROM decisions d JOIN tracks t ON t.id = d.track_id "
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
        "SELECT t, total, proposed, removed, added FROM school_counts WHERE video_id = ? AND saved = 1 AND kind = 'school' ORDER BY t", (video_id,),
    ))
    open_suggestions = con.execute(
        "SELECT COUNT(*) AS n FROM tracks t LEFT JOIN decisions d ON d.track_id = t.id WHERE t.video_id = ? AND d.track_id IS NULL", (video_id,),
    ).fetchone()["n"]
    duration = v["duration"] or sum(s["end"] - s["start"] for s in segs)
    skipped = seconds("skipped")
    pending = seconds("needs_review")
    return {
        "video": {"id": v["id"], "name": v["name"], **surveys.where(con, v), "filmed_on": v.get("filmed_on") or "",
                  "duration": duration, "notes": v["notes"]},
        "entries": sum(by_species.values()),
        "entries_added": sum(1 for d in decided if d["manual"]),  # fish AI missed and a person added
        "species_count": sum(1 for k in by_species if k != "Fish, unidentified"),
        "species": species,
        "schools": schools,
        "snapshots": snapshots.stats(con, video_id),
        "snapshot_frames": [f for f in frames if f["status"]],
        "protocol": plan,
        "points": points,
        "species_observed": species_observed(con, video_id, points),
        "peaks": sorted(
            ({**f, "ai_count": len(snapshots.ai_dots(con, video_id, f["t"])), "in_window": plan["start"] <= f["t"] < plan["end"]}
             for f in frames if f["kind"] == "peak"),
            key=lambda f: -f["ai_count"],
        ),
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
        "maxn": stats.maxn(con, video_id),
        "diversity": stats.diversity(con, video_id),

    }


def to_csv(s: dict) -> str:
    """`s` is what build() returns."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["video", s["video"]["name"]])
    w.writerow(["site", s["video"]["site"]])
    w.writerow(["transect", s["video"]["transect"]])
    w.writerow(["station", s["video"]["station"]])
    w.writerow(["filmed_on", s["video"]["filmed_on"]])
    w.writerow(["models", s["video"]["notes"]])
    w.writerow(["reviewed_s", round(s["reviewed"], 1)])
    w.writerow(["could_not_see_s", round(s["could_not_see"], 1)])
    w.writerow(["skipped_unreviewed_s", round(s["skipped"], 1)])
    w.writerow(["pending_s", round(s["pending"], 1)])
    w.writerow(["audit_segments_done", s["audit_segments"]])
    w.writerow(["audit_fish_found", s["audit_fish"]])
    w.writerow(["open_ai_suggestions_not_counted", s["open_suggestions"]])
    w.writerow(["active_review_s", round(s["review_seconds"], 1)])
    snap = s["snapshots"]
    w.writerow(["mean_count", "" if snap["mean_count"] is None else f"{snap['mean_count']:.2f}"])
    w.writerow(["snapshot_frames_checked", snap["frames_checked"]])
    w.writerow(["snapshot_frames_total", snap["frames_total"]])
    w.writerow(["snapshot_frames_could_not_see", snap["could_not_see"]])
    w.writerow(["peak_frames_checked", snap["peak_checked"]])
    w.writerow(["peak_frames_total", snap["peak_total"]])
    w.writerow(["peak_frames_could_not_see", snap["peak_could_not_see"]])
    w.writerow(["maxn" if snap["complete"] else "largest_count_in_checked_frames", "" if snap["largest_count"] is None else snap["largest_count"]])
    m = s["maxn"]
    w.writerow(["maxn_from_confirmed_tracks", m["maxn"]])
    w.writerow(["maxn_from_confirmed_tracks_time_s", "" if m["maxn_t"] is None else round(m["maxn_t"], 2)])
    dv = s["diversity"]
    w.writerow(["shannon_index", "" if dv["shannon"] is None else f"{dv['shannon']:.3f}"])
    w.writerow(["shannon_evenness", "" if dv["evenness"] is None else f"{dv['evenness']:.3f}"])
    w.writerow(["simpson_diversity", "" if dv["simpson_diversity"] is None else f"{dv['simpson_diversity']:.3f}"])
    w.writerow(["inverse_simpson", "" if dv["inverse_simpson"] is None else f"{dv['inverse_simpson']:.3f}"])
    w.writerow(["diversity_named_species", dv["richness"]])
    w.writerow(["entries_secondary_estimate_can_count_one_fish_twice", s["entries"]])
    w.writerow(["entries_ai_missed_and_a_person_added", s["entries_added"]])
    w.writerow([])
    w.writerow(["species", "entries_secondary_estimate"])
    for r in s["species"]:
        w.writerow([r["name"], r["entries"]])
    w.writerow([])
    w.writerow(["species", "maxn_from_confirmed_tracks", "maxn_from_confirmed_tracks_time_s", "confirmed_tracks"])
    for r in m["species"]:
        w.writerow([r["species"], r["maxn"], "" if r["t"] is None else round(r["t"], 2), r["tracks"]])
    w.writerow([])
    w.writerow(["species", "maxn_from_confirmed_tracks", "maxn_time_s", "confirmed_tracks"])
    for r in m["species"]:
        w.writerow([r["species"], r["maxn"], "" if r["t"] is None else round(r["t"], 2), r["tracks"]])
    w.writerow([])
    w.writerow(["school_time_s", "total", "ai_proposed", "removed", "added"])
    for r in s["schools"]:
        w.writerow([round(r["t"], 2), r["total"], r["proposed"], r["removed"], r["added"]])
    w.writerow([])
    w.writerow(["snapshot_time_s", "kind", "status", "total", "ai_proposed", "removed", "added"])
    for r in s["snapshot_frames"]:
        w.writerow([round(r["t"], 2), r["kind"], r["status"], r["total"], r["proposed"], r["removed"], r["added"]])
    return out.getvalue()


def clock(t: float) -> str:
    return f"{int(t) // 60}:{int(t) % 60:02d}"


def transect_stat(name: str) -> tuple[str, str]:
    """Reads T1 and STAT 2 out of a name like 'T1-STAT2 411.MP4'. Either is blank if it isn't there."""
    transect = re.search(r"(?<![A-Za-z0-9])T(\d+)", name, re.I)
    stat = re.search(r"STAT\s*(\d+)", name, re.I)
    return (f"T{transect.group(1)}" if transect else "", stat.group(1) if stat else "")


def protocol_csv(con, v: dict) -> str:
    """The analyst's sheet from Coastal Action's procedure: one row per sub-sample point, then the results.

    Only a person's saved answers appear. A frame nobody could see has no count, which isn't a zero,
    so its count stays blank and MeanCount leaves it out.
    """
    snapshots.ensure_frames(con, v)
    plan = snapshots.window(con, v)
    points = [f for f in snapshots.frames(con, v["id"]) if f["kind"] == "snapshot"]
    stats = snapshots.stats(con, v["id"])
    named = sorted({s["name"] for f in points for s in f["species"]})
    observed = species_observed(con, v["id"], points)
    video_id = Path(v["name"]).stem
    transect, stat = transect_stat(v["name"])
    place = surveys.where(con, v)
    if place["station"]:
        # The station a person filed it under wins over the file name. STAT2 is written as 2, like the sheet.
        transect, stat = place["transect"], re.sub(r"^STAT\s*(?=\d+$)", "", place["station"], flags=re.I)

    out = io.StringIO()
    out.write("\ufeff")  # so Excel reads the file as UTF-8
    w = csv.writer(out)
    w.writerow(["Video ID", "Transect", "STAT", "Analysis Start", "Analysis End", "Sub-sample", "Video Time", "Visibility",
                "Total Fish Count", "Invertebrate Count", *named, "Unknown/Unable to ID due to visibility", "Total Species Observed", "Notes"])
    for i, f in enumerate(points, 1):
        counted = f["status"] == "checked"
        by_name = {s["name"]: s["n"] for s in f["species"]}
        notes = "; ".join(x for x in ("Could not see" if f["status"] == "could_not_see" else "", f["comment"]) if x)
        w.writerow([
            video_id, transect, stat, clock(plan["start"]), clock(plan["end"]), i, clock(f["t"]), f["visibility"] or plan["visibility"],
            f["total"] if counted else "", f["invertebrates"] or 0 if counted else "",
            *[by_name.get(n, 0) if counted else "" for n in named],
            f["total"] - sum(by_name.values()) if counted else "", len(by_name) if counted else "", notes,
        ])
    w.writerow([])
    w.writerow(["MeanCount", "" if stats["mean_count"] is None else f"{stats['mean_count']:.2f}"])
    w.writerow(["Points counted", f"{stats['frames_checked']} of {stats['frames_total']}"])
    w.writerow(["Points could not see", stats["could_not_see"]])
    w.writerow(["Mean invertebrates", "" if stats["invertebrate_mean"] is None else f"{stats['invertebrate_mean']:.2f}"])
    w.writerow(["Species richness", len(observed)])
    w.writerow(["Species observed", "; ".join(observed)])
    w.writerow(["Horizontal visibility", plan["visibility"]])
    w.writerow(["Juveniles present", "" if plan["juveniles"] is None else plan["juveniles"]])
    return out.getvalue()
