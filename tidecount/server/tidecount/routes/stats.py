"""Statistics endpoints. The numbers are worked out in tidecount/stats.py."""
from fastapi import APIRouter

from .. import db, stats
from .common import get_video

router = APIRouter()


@router.get("/api/videos/{video_id}/stats/maxn")
def maxn(video_id: str):
    with db.session() as con:
        get_video(con, video_id)  # a video that doesn't exist answers 404
        return stats.maxn(con, video_id)


@router.get("/api/videos/{video_id}/stats/diversity")
def diversity(video_id: str):
    with db.session() as con:
        get_video(con, video_id)
        return stats.diversity(con, video_id)
