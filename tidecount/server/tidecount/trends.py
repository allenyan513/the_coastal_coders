"""Fish counts over time at a water sampling site, their diversity, and removing the seasonal pattern.

Fish counts live in the fish_counts table: one row per survey date, site and species. For now they
are made-up DEMO data from make_demo(), so the Fish and water trends page can show how fish trends
will look. Every demo row has source 'demo', and the page labels it. Once videos are linked to a
site and filming date, each video's MaxN per species can be saved in the same table with another source.

Plain functions on a database connection, so they can be tested without HTTP. Run
`python -m tidecount.trends demo` from server/ to (re)make the demo data.
"""
import math
import random
import sys
from collections import defaultdict

from datetime import date as Date

from . import db, water
from .stats import shannon, simpson

# Metrics a fish chart can show, besides one species' count. Diversity uses each survey's species counts.
METRICS = {
    "total": "Total fish",
    "richness": "Number of species",
    "shannon": "Shannon index (H)",
    "evenness": "Evenness (J)",
    "simpson": "Simpson's diversity (1 - D)",
    "inverse_simpson": "Inverse Simpson (1 / D)",
}

# --- Removing the seasonal pattern -------------------------------------------------------------

def deseasonalize(points: list[dict]) -> list[dict]:
    """The same points with the usual pattern for each calendar month taken out.

    Each value has its month's average (over all years) subtracted, then the overall average added
    back, so values stay in the same units and range. What's left shows change from year to year
    and unusual months, not the summer-winter cycle. A month seen only once can't be compared with
    other years, so its points are left out.
    """
    by_month: dict[str, list[float]] = defaultdict(list)
    for p in points:
        by_month[p["date"][5:7]].append(p["value"])
    if not points:
        return []
    overall = sum(p["value"] for p in points) / len(points)
    month_mean = {m: sum(v) / len(v) for m, v in by_month.items()}
    return [
        {"date": p["date"], "value": p["value"] - month_mean[p["date"][5:7]] + overall}
        for p in points if len(by_month[p["date"][5:7]]) > 1
    ]


# --- Fish counts -------------------------------------------------------------------------------

def fish_sites(con) -> list[str]:
    """Water sites that have any fish counts."""
    return [r["site_id"] for r in con.execute("SELECT DISTINCT site_id FROM fish_counts ORDER BY site_id")]


def species(con, site_id: str) -> list[str]:
    """Species counted at a site, most common first."""
    return [r["species"] for r in con.execute(
        "SELECT species FROM fish_counts WHERE site_id = ? GROUP BY species ORDER BY SUM(count) DESC, species",
        (site_id,),
    )]


def fish_series(con, site_id: str, metric: str) -> dict:
    """One fish measure over time at a site, one point per survey date, oldest first.

    `metric` is a key of METRICS, or a species name for that species' count.
    """
    surveys: dict[str, dict[str, int]] = defaultdict(dict)
    sources: set[str] = set()
    for r in con.execute("SELECT date, species, count, source FROM fish_counts WHERE site_id = ? ORDER BY date", (site_id,)):
        surveys[r["date"]][r["species"]] = surveys[r["date"]].get(r["species"], 0) + r["count"]
        sources.add(r["source"])

    points = []
    for date, counts in surveys.items():
        value = survey_value(counts, metric)
        if value is not None:
            points.append({"date": date, "value": value})
    label = METRICS.get(metric, metric)
    unit = "fish" if metric == "total" or metric not in METRICS else ""
    return {"site_id": site_id, "metric": metric, "label": label, "unit": unit, "points": points,
            "demo": "demo" in sources}


def survey_value(counts: dict[str, int], metric: str) -> float | None:
    """One survey's value for a metric. None where it can't be worked out, such as evenness with one species."""
    numbers = list(counts.values())
    if metric == "total":
        return sum(numbers)
    if metric == "richness":
        return sum(1 for n in numbers if n > 0)
    if metric in ("shannon", "evenness"):
        h, j = shannon(numbers)
        return h if metric == "shannon" else j
    if metric in ("simpson", "inverse_simpson"):
        d, inverse = simpson(numbers)
        return d if metric == "simpson" else inverse
    return counts.get(metric, 0)  # one species: a survey without it counted zero


# --- Comparing fish with water -----------------------------------------------------------------

MAX_GAP_DAYS = 15  # a fish survey is paired with a water reading at most this many days away


def compare(con, site_id: str, metric: str, measurement: str, deseason: bool = False) -> dict:
    """A fish measure and a water measurement at one site, on one shared scale, with their correlation.

    Each line is standardized: its own average is taken away and the result divided by its own
    standard deviation, so 0 is usual for that line, +1 is one standard deviation above it, and both
    lines share one axis whatever their units. The correlation pairs each fish survey with the water
    reading closest in time, if it is within MAX_GAP_DAYS.
    """
    fish = fish_series(con, site_id, metric)
    wat = water.series(con, site_id, measurement)
    fish_points, water_points = fish["points"], wat["points"]
    if deseason:
        fish_points, water_points = deseasonalize(fish_points), deseasonalize(water_points)
    if fish_points:  # the water line covers the same years as the fish
        first, last = fish_points[0]["date"], fish_points[-1]["date"]
        water_points = [p for p in water_points if first <= p["date"] <= last]

    pairs = pair_up(fish_points, water_points)
    rho, p = spearman([f for _, f, _ in pairs], [w for _, _, w in pairs])
    return {
        "fish": {"label": fish["label"], "unit": fish["unit"], "points": standardize(fish_points)},
        "water": {"label": measurement, "unit": wat["unit"], "points": standardize(water_points)},
        "pairs": len(pairs),
        "max_gap_days": MAX_GAP_DAYS,
        "spearman": rho,
        "p_value": p,
        "strength": describe(rho),
        "demo": fish["demo"],
    }


def standardize(points: list[dict]) -> list[dict]:
    """Each point with `z`, how many standard deviations it is from the line's own average, and its `value`."""
    if len(points) < 2:
        return [{**p, "z": 0.0} for p in points]
    values = [p["value"] for p in points]
    mean = sum(values) / len(values)
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))
    return [{**p, "z": 0.0 if sd == 0 else (p["value"] - mean) / sd} for p in points]


def pair_up(fish_points: list[dict], water_points: list[dict]) -> list[tuple[str, float, float]]:
    """(date, fish value, water value) for each fish survey with a water reading close enough in time."""
    days = [(Date.fromisoformat(p["date"]).toordinal(), p["value"]) for p in water_points]
    pairs = []
    for f in fish_points:
        day = Date.fromisoformat(f["date"]).toordinal()
        near = min(days, key=lambda d: abs(d[0] - day), default=None)
        if near is not None and abs(near[0] - day) <= MAX_GAP_DAYS:
            pairs.append((f["date"], f["value"], near[1]))
    return pairs


def ranks(values: list[float]) -> list[float]:
    """Each value's rank, 1 for the smallest. Tied values share the average of their ranks."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(xs: list[float], ys: list[float]) -> tuple[float | None, float | None]:
    """Spearman's rank correlation, from -1 to 1, and an approximate two-sided p-value.

    It's the ordinary (Pearson) correlation of the ranks, so it measures whether one goes up when
    the other goes up (or down), without assuming a straight line, and odd values can't dominate.
    The p-value uses the normal approximation to the t statistic, fine for about 30 pairs or more.
    """
    n = len(xs)
    if n < 3:
        return None, None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if sx == 0 or sy == 0:
        return None, None  # one side never changes, so there's nothing to correlate
    rho = cov / (sx * sy)
    if abs(rho) >= 1:
        return rho, 0.0
    t = rho * math.sqrt((n - 2) / (1 - rho * rho))
    return rho, math.erfc(abs(t) / math.sqrt(2))


def describe(rho: float | None) -> str:
    """Plain words for a correlation's size and direction."""
    if rho is None:
        return "not enough paired data"
    size = abs(rho)
    word = "very weak" if size < 0.1 else "weak" if size < 0.3 else "moderate" if size < 0.5 else "strong"
    if size < 0.1:
        return "no clear relationship"
    return f"{word} {'positive' if rho > 0 else 'negative'}"


# --- Demo data ---------------------------------------------------------------------------------

# Made-up estuary fish for the demo: (name, typical count, how strongly summer raises it, change per year).
DEMO_SPECIES = [
    ("Atlantic silverside", 18, 0.9, 0.04),
    ("Mummichog", 12, 0.7, 0.0),
    ("Threespine stickleback", 10, 0.5, -0.06),
    ("Atlantic tomcod", 5, -0.6, 0.0),
    ("Winter flounder", 3, 0.3, -0.03),
    ("American eel", 2, 0.8, 0.02),
]
DEMO_SITES = ["1", "2", "3"]  # Upper LaHave, Dayspring and Bridgewater: the estuary sites


def make_demo(con, first_year: int = 2015, last_year: int = 2025, seed: int = 7) -> int:
    """Replaces any demo fish counts with a made-up monthly survey at each estuary site. Returns how many rows.

    Counts follow the seasons (most species peak in summer, tomcod in winter), drift slowly over the
    years (silverside up, stickleback down), and vary at random, so trends, seasonality and diversity
    all have something to show. They are not real observations.
    """
    rng = random.Random(seed)
    rows = []
    for site in DEMO_SITES:
        site_factor = 0.7 + 0.3 * DEMO_SITES.index(site)
        for year in range(first_year, last_year + 1):
            for month in range(1, 13):
                day = rng.randint(5, 25)
                summer = math.cos((month - 7) / 12 * 2 * math.pi)  # 1 in July, -1 in January
                for name, typical, season, per_year in DEMO_SPECIES:
                    mean = typical * site_factor * math.exp(season * summer) * math.exp(per_year * (year - first_year))
                    count = poisson(rng, mean)
                    if count:
                        rows.append((site, f"{year}-{month:02d}-{day:02d}", name, count))
    con.execute("DELETE FROM fish_counts WHERE source = 'demo'")
    con.executemany("INSERT INTO fish_counts (site_id, date, species, count, source) VALUES (?, ?, ?, ?, 'demo')", rows)
    return len(rows)


def poisson(rng: random.Random, mean: float) -> int:
    """A random whole-number count around `mean`, as real counts vary."""
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


if __name__ == "__main__":
    if sys.argv[1:] != ["demo"]:
        sys.exit("Usage: python -m tidecount.trends demo")
    db.init()
    with db.session() as con:
        print(f"Made {make_demo(con)} demo fish count rows.")
