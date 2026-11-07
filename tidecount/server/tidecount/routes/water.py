"""Water quality and fish trend endpoints for the Fish and water trends page.

The work is done in tidecount/water.py and tidecount/trends.py.
"""
from fastapi import APIRouter

from .. import db, trends, water

router = APIRouter()


@router.get("/api/water/sites")
def sites():
    with db.session() as con:
        return water.sites(con)


@router.get("/api/water/sites/{site_id}/series")
def series(site_id: str, measurement: str, deseason: bool = False):
    """`deseason=true` takes the usual pattern for each month out, leaving the year-to-year trend."""
    with db.session() as con:
        s = water.series(con, site_id, measurement)
    if deseason:
        s["points"] = trends.deseasonalize(s["points"])
    return s


@router.get("/api/fish/sites/{site_id}/options")
def fish_options(site_id: str):
    """What a fish chart at this site can show: the overall measures, then each species."""
    with db.session() as con:
        return {"metrics": [{"key": k, "label": v} for k, v in trends.METRICS.items()],
                "species": trends.species(con, site_id)}


@router.get("/api/compare/sites/{site_id}")
def compare(site_id: str, metric: str = "total", measurement: str = "Temperature, water", deseason: bool = False):
    """A fish measure and a water measurement on one shared scale, with their Spearman correlation."""
    with db.session() as con:
        return trends.compare(con, site_id, metric, measurement, deseason)


@router.get("/api/fish/sites/{site_id}/series")
def fish_series(site_id: str, metric: str = "total", deseason: bool = False):
    with db.session() as con:
        s = trends.fish_series(con, site_id, metric)
    if deseason:
        s["points"] = trends.deseasonalize(s["points"])
    return s
