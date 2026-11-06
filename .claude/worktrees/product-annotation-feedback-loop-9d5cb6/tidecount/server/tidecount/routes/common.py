"""Helpers several routers share."""
from fastapi import HTTPException

from .. import models


def get_video(con, video_id: str) -> dict:
    row = con.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Video not found")
    return dict(row)


def check_detector(key: str) -> None:
    ok, why = models.available(key)
    if not ok:
        raise HTTPException(400, why)
