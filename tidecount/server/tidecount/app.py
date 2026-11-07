"""The app: one router per feature, plus start-up work. Run with `uvicorn tidecount.app:app`.

Nothing happens on import. Folders, the database and the worker start in `lifespan`, which runs
when uvicorn starts the app. Tests that build a TestClient without `with` skip it entirely.
"""
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from . import config, db, settings
from .routes import review, schools, snapshots, species, stats, summary, tracks, videos, web


def worker_loop() -> None:
    """Analyze queued videos one at a time, so one PC never runs two heavy jobs."""
    with db.session() as con:
        con.execute("UPDATE videos SET status = 'Queued', stage = '' WHERE status = 'Analyzing'")
    server_dir = Path(__file__).resolve().parents[1]
    while True:
        with db.session() as con:
            row = con.execute("SELECT id FROM videos WHERE status = 'Queued' ORDER BY created_at LIMIT 1").fetchone()
        if row:
            subprocess.run([sys.executable, "-m", "tidecount.worker", row["id"]], cwd=server_dir)
        else:
            time.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.current()  # a broken settings file stops the app here, with the reason
    config.ensure_folders()
    db.init()
    if config.RUN_WORKER:
        threading.Thread(target=worker_loop, daemon=True).start()
    yield


app = FastAPI(title="TideCount", lifespan=lifespan)
for module in (videos, tracks, review, schools, snapshots, species, summary, stats):
    app.include_router(module.router)
app.include_router(web.router)  # last, because its catch-all path would hide the API
