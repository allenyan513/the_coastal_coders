"""Summary, CSV and training data endpoints. The numbers are worked out in tidecount/summary.py
and the training data in tidecount/dataset.py."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from .. import config, dataset, db, summary as report
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


@router.post("/api/videos/{video_id}/training-data")
def training_data(video_id: str):
    """Write this video's counted frames and decided fish to a folder on this machine."""
    with db.session() as con:
        v = get_video(con, video_id)
        try:
            manifest = dataset.export(con, v)
        except dataset.NothingToExport as exc:
            raise HTTPException(409, str(exc))
    return {**manifest, "folder": str(config.EXPORTS / video_id)}
