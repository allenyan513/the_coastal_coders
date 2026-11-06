"""Summary and CSV export endpoints. The numbers are worked out in tidecount/summary.py."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from .. import db, summary as report
from .common import get_video

router = APIRouter()


@router.get("/api/videos/{video_id}/summary")
def summary(video_id: str):
    with db.session() as con:
        return report.build(con, get_video(con, video_id))


@router.get("/api/videos/{video_id}/export.csv")
def export(video_id: str):
    with db.session() as con:
        s = report.build(con, get_video(con, video_id))
    name = Path(s["video"]["name"]).stem
    return PlainTextResponse(report.to_csv(s), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}-summary.csv"'})
