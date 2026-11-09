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

from . import analysis_queue, config, db, settings, surveys, trends, water
from .routes import review, scan, schools, snapshots, species, species_library, stats, summary, surveys as survey_routes, tracks, validation as validation_routes, videos, water as water_routes, web


def worker_loop() -> None:
    """Analyze queued videos one at a time, so one PC never runs two heavy jobs."""
    with db.session() as con:
        con.execute("UPDATE videos SET status = 'Queued', stage = '' WHERE status = 'Analyzing'")
    server_dir = Path(__file__).resolve().parents[1]
    while True:
        with db.session() as con:
            video_id = analysis_queue.next_queued(con)
        if video_id:
            done = subprocess.run([sys.executable, "-m", "tidecount.worker", video_id], cwd=server_dir)
            # A worker killed from outside (out of memory, say) can't mark its own row, which would
            # otherwise stay Analyzing and hold up every wait time after it.
            with db.session() as con:
                con.execute("UPDATE videos SET status = 'Failed', stage = '', error = ? WHERE id = ? AND status = 'Analyzing'",
                            (f"The analysis stopped unexpectedly (exit code {done.returncode}). Try again.", video_id))
        else:
            time.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.current()  # a broken settings file stops the app here, with the reason
    config.ensure_folders()
    with db.session() as con:
        new_fish_table = not trends.has_fish_table(con)
    if db.init():
        with db.session() as con:
            surveys.sample(con)  # a first run starts with a structure to try, which a manager can change
    with db.session() as con:
        water.load_bundled(con)  # Coastal Action's water readings, on any computer that doesn't have them yet
        if new_fish_table:
            # Demo fish counts for the trends page, made once. Deleting them later keeps them gone.
            trends.make_demo(con)
    if config.RUN_WORKER:
        threading.Thread(target=worker_loop, daemon=True).start()
    yield


app = FastAPI(title="Tideflow", lifespan=lifespan)
for module in (survey_routes, videos, tracks, review, schools, snapshots, species_library, species, summary, stats, water_routes, validation_routes, scan):
    app.include_router(module.router)
app.include_router(web.router)  # last, because its catch-all path would hide the API
