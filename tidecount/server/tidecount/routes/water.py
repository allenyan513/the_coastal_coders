"""Water quality endpoints for the River Sensor page. The work is done in tidecount/water.py."""
from fastapi import APIRouter

from .. import db, water

router = APIRouter()


@router.get("/api/water/sites")
def sites():
    with db.session() as con:
        return water.sites(con)


@router.get("/api/water/sites/{site_id}/series")
def series(site_id: str, measurement: str):
    with db.session() as con:
        return water.series(con, site_id, measurement)