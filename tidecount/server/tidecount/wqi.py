"""The Water Quality Index (WQI) for each water sampling site and year, like Coastal Action's report cards.

It's the Canadian Council of Ministers of the Environment (CCME) Water Quality Index. Every reading
in a site's year is checked against a guideline. Three things are measured:

  F1, scope:      the share of measurements that broke their guideline at least once
  F2, frequency:  the share of all tests that broke a guideline
  F3, amplitude:  how far the failing tests were from their guidelines

and combined into a score from 0 (worst) to 100 (best): WQI = 100 - sqrt(F1² + F2² + F3²) / 1.732.

The guidelines are a starting point chosen by us, not Coastal Action's official ones: their report
cards may use other measurements or limits. They're all in FRESH and SALTY below, so they're easy to change.
"""
import math
import sys

from .stats import shannon
from . import db, water

# Each guideline: (lowest allowed, highest allowed, where it comes from). None means no limit that way.
# Chosen to match Coastal Action's published LaHave scores for 2017-2023 as closely as possible
# (on average within 5 points, and the same rating 48 times out of 70). Their exact list isn't published.
FRESH = {
    "pH": (6.5, 9.0, "CCME, freshwater aquatic life"),
    "Dissolved oxygen (DO)": (5.5, None, "CCME, warm freshwater, other life stages"),
    "Temperature, water": (None, 20, "Stress level for trout and salmon"),
    "Total Phosphorus, mixed forms": (None, 0.03, "CCME trigger range, upper limit for mesotrophic water"),
    "Total Nitrogen, mixed forms": (None, 1.0, "Matched to Coastal Action's scores"),
    "Inorganic nitrogen (nitrate and nitrite)": (None, 2.9, "CCME nitrate, long-term, as nitrogen"),
    "Chloride": (None, 120, "CCME, freshwater long-term"),
    "Fecal Coliform": (None, 200, "Recreational water, cfu/100 mL"),
}
# Estuary sites use marine guidelines and their own list, as Coastal Action's report cards do.
SALTY = {
    "pH": (7.0, 8.7, "CCME, marine aquatic life"),
    "Dissolved oxygen (DO)": (8.0, None, "CCME, marine aquatic life"),
    "Total Phosphorus, mixed forms": (None, 0.05, "Matched to Coastal Action's scores"),
    "Total Nitrogen, mixed forms": (None, 1.0, "Matched to Coastal Action's scores"),
    "Fecal Streptococcus Group Bacteria": (None, 70, "Health Canada, enterococci in marine recreation, cfu/100 mL"),
}


# CCME: a WQI needs at least this many measurements, sampled on at least this many days.
MIN_MEASUREMENTS = 4
MIN_SAMPLE_DAYS = 4

RATINGS = [(95, "Excellent"), (80, "Good"), (65, "Fair"), (45, "Marginal"), (0, "Poor")]


def rating(wqi: float) -> str:
    """The CCME word for a score."""
    return next(word for lowest, word in RATINGS if wqi >= lowest)


def excursion(value: float, low: float | None, high: float | None) -> float:
    """How far a reading is past its guideline, as a fraction of the guideline. 0 when it passes."""
    if high is not None and value > high:
        return value / high - 1
    if low is not None and value < low:
        return low / max(value, 0.01) - 1
    return 0.0


def judge(value: float, qualifier: str, low: float | None, high: float | None) -> float | None:
    """A reading's excursion, or None when it can't say whether the guideline was met.

    A lab result marked "<" was below what the lab could measure: it passes if that limit is within
    the guideline, and can't be judged if not. One marked ">" was above what the lab could measure.
    """
    if qualifier == "<":
        if high is not None and value > high:
            return None  # the lab's limit is above the guideline, so we can't tell
        return 0.0 if low is None else None
    if qualifier == ">":
        return excursion(value, low, high) if high is not None and value >= high else None
    return excursion(value, low, high)


def score(tests: list[tuple[str, float]]) -> dict:
    """The WQI from tests, each (measurement, excursion). Excursion 0 means it passed."""
    measurements = {m for m, _ in tests}
    failed_measurements = {m for m, e in tests if e > 0}
    failed = [e for _, e in tests if e > 0]

    f1 = 100 * len(failed_measurements) / len(measurements)
    f2 = 100 * len(failed) / len(tests)
    nse = sum(failed) / len(tests)  # normalized sum of excursions
    f3 = nse / (0.01 * nse + 0.01)
    wqi = 100 - math.sqrt(f1 * f1 + f2 * f2 + f3 * f3) / 1.732
    return {"wqi": round(wqi, 1), "rating": rating(wqi), "f1": round(f1, 1), "f2": round(f2, 1), "f3": round(f3, 1)}


def is_salty(con, site_id: str) -> bool:
    """Whether a site is in the estuary: its typical salinity is at least water.SALTY_PPTH."""
    values = sorted(r["value"] for r in con.execute(
        "SELECT value FROM water_readings WHERE site_id = ? AND measurement = 'Salinity'", (site_id,)))
    return bool(values) and values[len(values) // 2] >= water.SALTY_PPTH


def site_year(con, site_id: str, year: int) -> dict:
    """One site's report card for one year: its WQI, rating, and how each measurement did."""
    guidelines = SALTY if is_salty(con, site_id) else FRESH
    rows = con.execute(
        "SELECT date, measurement, value, qualifier FROM water_readings "
        "WHERE site_id = ? AND date LIKE ? AND measurement IN (%s)" % ",".join("?" * len(guidelines)),
        (site_id, f"{year}-%", *guidelines),
    ).fetchall()

    tests, days = [], set()
    per_measurement: dict[str, dict] = {}
    for r in rows:
        low, high, _ = guidelines[r["measurement"]]
        e = judge(r["value"], r["qualifier"] or "", low, high)
        if e is None:
            continue
        tests.append((r["measurement"], e))
        days.add(r["date"])
        m = per_measurement.setdefault(r["measurement"], {"measurement": r["measurement"], "tests": 0, "failed": 0})
        m["tests"] += 1
        m["failed"] += e > 0

    card = {
        "site_id": site_id,
        "year": year,
        "salty": guidelines is SALTY,
        "tests": len(tests),
        "sample_days": len(days),
        "measurements": sorted(per_measurement.values(), key=lambda m: -m["failed"] / m["tests"]),
    }
    if len(per_measurement) < MIN_MEASUREMENTS or len(days) < MIN_SAMPLE_DAYS:
        return {**card, "wqi": None, "rating": "Not enough data"}
    return {**card, **score(tests)}


def fish_year(con, site_id: str, year: int) -> dict | None:
    """What the fish surveys at a site found in one year, for the report card's Fish column. None if there were none."""
    rows = con.execute(
        "SELECT date, species, SUM(count) AS n, MAX(source = 'demo') AS demo FROM fish_counts "
        "WHERE site_id = ? AND date LIKE ? GROUP BY date, species",
        (site_id, f"{year}-%"),
    ).fetchall()
    if not rows:
        return None
    by_species: dict[str, int] = {}
    for r in rows:
        by_species[r["species"]] = by_species.get(r["species"], 0) + r["n"]
    surveys = len({r["date"] for r in rows})
    fish = sum(by_species.values())
    h, _ = shannon(list(by_species.values()))
    return {
        "surveys": surveys,
        "fish": fish,
        "per_survey": round(fish / surveys, 1),
        "species": sum(1 for n in by_species.values() if n > 0),
        "shannon": None if h is None else round(h, 2),
        "most_common": max(by_species, key=by_species.get),
        "demo": any(r["demo"] for r in rows),
    }


# Sites in the order the river flows, from the headwaters down to the estuary, as in Coastal Action's
# report card table. Sites not listed here go after them.
RIVER_ORDER = ["14", "15", "12", "9", "8", "7", "5", "4", "3", "1"]


def table(con, last: int = 7) -> dict:
    """The report card table: each site's WQI for the last `last` years with scores, and its fish.

    Sites run in river order. A site with no score in any of those years is left out.
    """
    names = {s["site_id"]: s["site_name"] for s in water.sites(con)}
    newest = max((y for y in years(con) if any(site_year(con, s, y)["wqi"] is not None for s in names)), default=None)
    if newest is None:
        return {"years": [], "sites": []}
    shown = list(range(newest - last + 1, newest + 1))
    order = sorted(names, key=lambda s: (RIVER_ORDER.index(s) if s in RIVER_ORDER else len(RIVER_ORDER), names[s]))

    rows = []
    for site_id in order:
        cards = [site_year(con, site_id, y) for y in shown]
        if all(c["wqi"] is None for c in cards):
            continue
        rows.append({
            "site_id": site_id,
            "site_name": names[site_id],
            "salty": cards[-1]["salty"],
            "scores": [{"year": c["year"], "wqi": c["wqi"], "rating": c["rating"]} for c in cards],
            "fish": [{"year": y, **f} for y in shown if (f := fish_year(con, site_id, y))],
        })
    return {"years": shown, "sites": rows}


def table(con, last: int = 7) -> dict:
    """The report card table: each site's WQI for the last `last` years with scores, and its fish.

    Sites run in river order. A site with no score in any of those years is left out.
    """
    names = {s["site_id"]: s["site_name"] for s in water.sites(con)}
    newest = max((y for y in years(con) if any(site_year(con, s, y)["wqi"] is not None for s in names)), default=None)
    if newest is None:
        return {"years": [], "sites": []}
    shown = list(range(newest - last + 1, newest + 1))
    order = sorted(names, key=lambda s: (RIVER_ORDER.index(s) if s in RIVER_ORDER else len(RIVER_ORDER), names[s]))

    rows = []
    for site_id in order:
        cards = [site_year(con, site_id, y) for y in shown]
        if all(c["wqi"] is None for c in cards):
            continue
        rows.append({
            "site_id": site_id,
            "site_name": names[site_id],
            "salty": cards[-1]["salty"],
            "scores": [{"year": c["year"], "wqi": c["wqi"], "rating": c["rating"]} for c in cards],
            "fish": [{"year": y, **f} for y in shown if (f := fish_year(con, site_id, y))],
        })
    return {"years": shown, "sites": rows}


def years(con) -> list[int]:
    """Years with any water readings, newest first."""
    return [int(r["y"]) for r in con.execute(
        "SELECT DISTINCT substr(date, 1, 4) AS y FROM water_readings ORDER BY y DESC")]


def report_card(con, year: int) -> list[dict]:
    """Every site's report card for one year, best water first; sites without enough data last."""
    cards = [site_year(con, s["site_id"], year) for s in water.sites(con)]
    names = {s["site_id"]: s["site_name"] for s in water.sites(con)}
    for c in cards:
        c["site_name"] = names[c["site_id"]]
    return sorted(cards, key=lambda c: (c["wqi"] is None, -(c["wqi"] or 0)))


if __name__ == "__main__":
    # python -m tidecount.wqi 2024    print every site's report card for that year
    db.init()
    with db.session() as con:
        water.load_bundled(con)
        for c in report_card(con, int(sys.argv[1])):
            score_text = "-" if c["wqi"] is None else c["wqi"]
            fish = fish_year(con, c["site_id"], int(sys.argv[1]))
            fish_text = "" if fish is None else (f"  fish: {fish['species']} species, {fish['per_survey']} per survey"
            + (" (demo)" if fish["demo"] else ""))
            print(f"{c['site_name']:28} {score_text:>6}  {c['rating']:16}{fish_text}")