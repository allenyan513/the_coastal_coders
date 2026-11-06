"""Helpers several routers share."""
import threading

from fastapi import HTTPException

from .. import models, settings

_detectors: dict = {}
_suggesters: list = []
_detector_lock = threading.Lock()
_suggester_lock = threading.Lock()  # its own lock, since this model takes far longer to load


def detector(key: str):
    """Loaded once and kept. A model that can't load becomes one that finds nothing, so the page still works."""
    with _detector_lock:
        if key not in _detectors:
            try:
                _detectors[key] = models.load_detector(key)
            except Exception:
                _detectors[key] = models.NullDetector()
        return _detectors[key]


def suggester():
    """The species model, loaded the first time a person adds a fish and kept after that."""
    with _suggester_lock:
        if not _suggesters:
            _suggesters.append(models.load_suggester(settings.current().species.model))
        return _suggesters[0]


def get_video(con, video_id: str) -> dict:
    row = con.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Video not found")
    return dict(row)


def check_detector(key: str) -> None:
    ok, why = models.available(key)
    if not ok:
        raise HTTPException(400, why)
