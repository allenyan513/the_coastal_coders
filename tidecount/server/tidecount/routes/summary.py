"""Summary and CSV export endpoints. The numbers are worked out in tidecount/summary.py."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from .. import auth, db, summary as report
from .common import get_video

router = APIRouter()


# Public: the home page's statistics read every ready video's summary, for guests too.
@router.get("/api/videos/{video_id}/summary")
def summary(video_id: str):
    with db.session() as con:
        return report.build(con, get_video(con, video_id))


@router.get("/api/videos/{video_id}/export.csv", dependencies=auth.SIGNED_IN)
def export(video_id: str):
    with db.session() as con:
        s = report.build(con, get_video(con, video_id))
    name = Path(s["video"]["name"]).stem
    return PlainTextResponse(report.to_csv(s), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}-summary.csv"'})


@router.get("/api/videos/{video_id}/protocol.csv", dependencies=auth.SIGNED_IN)
def protocol_export(video_id: str):
    """The per-point sheet from Coastal Action's procedure."""
    with db.session() as con:
        v = get_video(con, video_id)
        body = report.protocol_csv(con, v)
    return PlainTextResponse(body, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{Path(v["name"]).stem}-protocol.csv"'})
