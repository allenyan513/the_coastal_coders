"""Survey structure endpoints: sites, transects and stations, and filing videos under a station.

The rules live in tidecount/surveys.py. This module only turns them into HTTP.
"""
from contextlib import contextmanager
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import auth, db, surveys

# Anyone signed in reads the survey tree (volunteers file uploads under a station); changing it,
# and filing videos afterwards, is survey administration: managers. Deleting also needs a recent
# password confirmation.
router = APIRouter(dependencies=auth.SIGNED_IN)
Kind = Literal["sites", "transects", "stations"]


@contextmanager
def answer():
    """One transaction, with a broken rule answered as its HTTP status and message."""
    try:
        with db.session() as con:
            yield con
    except surveys.Problem as e:
        raise HTTPException(e.status, str(e)) from None


@router.get("/api/surveys")
def tree():
    with answer() as con:
        return surveys.tree(con)


class NewItem(BaseModel):
    id: str | None = None
    name: str = ""
    coordinates: str = ""
    depth: str = ""
    flag: str = ""
    archived: bool = False
    # The site of a new transect, or the transect of a new station.
    parent_id: str | None = None


class ItemChange(BaseModel):
    name: str | None = None
    coordinates: str | None = None
    depth: str | None = None
    flag: str | None = None
    archived: bool | None = None


@router.post("/api/surveys/{kind}", dependencies=auth.MANAGER)
def add(kind: Kind, body: NewItem):
    with answer() as con:
        values = body.model_dump(exclude={"id", "parent_id"})
        return {"id": surveys.add(con, kind, values, body.parent_id, body.id)}


@router.patch("/api/surveys/{kind}/{item_id}", dependencies=auth.MANAGER)
def change(kind: Kind, item_id: str, body: ItemChange):
    with answer() as con:
        surveys.change(con, kind, item_id, body.model_dump())
    return {"ok": True}


@router.delete("/api/surveys/{kind}/{item_id}", dependencies=auth.RECENT_MANAGER)
def remove(kind: Kind, item_id: str):
    with answer() as con:
        surveys.remove(con, kind, item_id)
    return {"ok": True}


class Place(BaseModel):
    station_id: str | None = None
    filmed_on: str | None = None


@router.put("/api/videos/{video_id}/place", dependencies=auth.MANAGER)
def place(video_id: str, body: Place):
    """The station and filmed date of a video. A field left out stays as it is; an empty one clears it."""
    with answer() as con:
        surveys.place(con, video_id, body.station_id, body.filmed_on)
    return {"ok": True}


class PlaceMany(BaseModel):
    items: dict[str, str]  # station id by video id


@router.put("/api/videos/places", dependencies=auth.MANAGER)
def place_many(body: PlaceMany):
    """File several videos at once, all or none, as when they're filed by their names."""
    with answer() as con:
        for video_id, station_id in body.items.items():
            surveys.place(con, video_id, station_id)
    return {"ok": True}
