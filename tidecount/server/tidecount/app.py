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

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import auth, config, db, settings, surveys, trends, water
from .routes import auth as auth_routes, review, schools, snapshots, species, species_library, stats, summary, surveys as survey_routes, team, tracks, videos, water as water_routes, web


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


@app.middleware("http")
async def refuse_cross_site_writes(request: Request, call_next):
    """Every API write must come from Tideflow's own pages (see auth.origin_problem)."""
    problem = auth.origin_problem(request)
    if problem:
        return JSONResponse({"detail": problem}, status_code=403)
    return await call_next(request)


for module in (auth_routes, team, survey_routes, videos, tracks, review, schools, snapshots, species_library, species, summary, stats, water_routes):
    app.include_router(module.router)
app.include_router(web.router)  # last, because its catch-all path would hide the API
