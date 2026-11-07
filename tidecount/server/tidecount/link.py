"""Turning reviewed videos into fish counts at a water sampling site, for the Fish and water trends page.

A video counts when it has a station (from the survey structure) and a filming date, and its
filming spot is within MATCH_KM of a water sampling site. Only then do the fish and the water
readings come from the same place. Video filmed anywhere else is left out, rather than matched to
the nearest site, which could be on another river. The water sites are whatever is in
water_readings: LaHave for now, other Coastal Action locations once they are imported.

The counts are each species' MaxN from the tracks a person confirmed (stats.maxn), saved in
fish_counts with source 'video'. rebuild() replaces all of them each time, so a newly reviewed,
moved or redated video is always picked up.
"""
import math

from . import stats, water

MATCH_KM = 1.0  # a filming spot this close to a water site counts as the same place
EARTH_RADIUS_KM = 6371.0


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """(latitude, longitude) from text like "44.1, -64.7". None when it's empty or not two sensible numbers."""
    pieces = (text or "").split(",")
    if len(pieces) != 2:
        return None
    try:
        lat, lon = float(pieces[0]), float(pieces[1])
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """The distance between two (latitude, longitude) points along the earth's surface (the haversine formula)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def matching_site(spot: tuple[float, float], sites: list[dict]) -> tuple[dict | None, float | None]:
    """The water site at the same place as `spot` (the closest within MATCH_KM), and how far the closest site is."""
    best, best_km = None, None
    for s in sites:
        if s["lat"] is None or s["lon"] is None:
            continue
        km = distance_km(spot, (s["lat"], s["lon"]))
        if best_km is None or km < best_km:
            best, best_km = s, km
    return (best if best_km is not None and best_km <= MATCH_KM else None), best_km


def filming_spot(con, station_id: str) -> tuple[float, float] | None:
    """The station's coordinates, or its site's when the station has none."""
    row = con.execute(
        "SELECT st.coordinates AS station, si.coordinates AS site FROM stations st "
        "JOIN transects t ON t.id = st.transect_id JOIN sites si ON si.id = t.site_id WHERE st.id = ?",
        (station_id,),
    ).fetchone()
    if not row:
        return None
    return parse_coordinates(row["station"]) or parse_coordinates(row["site"])


def rebuild(con) -> dict:
    """Replace every 'video' fish count, and say which videos were linked and why others weren't.

    A video and its re-analysis runs share one station and date, so each is counted once, from the
    run with the most confirmed fish. A video still being reviewed (tracks nobody has decided on)
    waits until it's done, so a half-finished count doesn't look like a real drop in fish.
    "Fish, unidentified" is left out, since it isn't one species and would skew diversity.
    """
    sites = water.sites(con)
    runs: dict[str, list[dict]] = {}
    for v in con.execute(
        "SELECT id, name, station_id, filmed_on, CASE WHEN source_id != '' THEN source_id ELSE id END AS root "
        "FROM videos ORDER BY created_at"
    ):
        runs.setdefault(v["root"], []).append(dict(v))

    rows, linked, not_linked = [], [], []
    for group in runs.values():
        first = group[0]
        name, station_id, filmed_on = first["name"], first["station_id"] or "", first["filmed_on"] or ""
        if not station_id or not filmed_on:
            not_linked.append({"video": name, "reason": "no station or filming date yet"})
            continue
        spot = filming_spot(con, station_id)
        if spot is None:
            not_linked.append({"video": name, "reason": "its station and site have no coordinates"})
            continue
        site, km = matching_site(spot, sites)
        if site is None:
            away = f", the closest is {km:.1f} km away" if km is not None else ""
            not_linked.append({"video": name, "reason": f"no water sampling site within {MATCH_KM:g} km{away}"})
            continue

        done = [m for m in (stats.maxn(con, v["id"]) for v in group) if not m["partial"] and m["confirmed_tracks"] > 0]
        if not done:
            not_linked.append({"video": name, "reason": "review isn't finished, or no fish were confirmed"})
            continue
        best = max(done, key=lambda m: m["confirmed_tracks"])
        for s in best["species"]:
            if s["species"] != stats.UNIDENTIFIED:
                rows.append((site["site_id"], filmed_on, s["species"], s["maxn"]))
        linked.append({"video": name, "site_id": site["site_id"], "site_name": site["site_name"],
                       "date": filmed_on, "km": round(km, 2)})

    con.execute("DELETE FROM fish_counts WHERE source = 'video'")
    con.executemany("INSERT INTO fish_counts (site_id, date, species, count, source) VALUES (?, ?, ?, ?, 'video')", rows)
    return {"match_km": MATCH_KM, "linked": linked, "not_linked": not_linked}
