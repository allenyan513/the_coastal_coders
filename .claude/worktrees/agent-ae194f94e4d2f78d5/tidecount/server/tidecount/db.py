"""SQLite storage. One local file, in WAL mode so the worker and API can share it."""
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL, site TEXT DEFAULT '',
  duration REAL DEFAULT 0, fps REAL DEFAULT 0, width INTEGER DEFAULT 0, height INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'Queued', stage TEXT DEFAULT '', progress REAL DEFAULT 0,
  error TEXT DEFAULT '', proxy_path TEXT DEFAULT '', notes TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS seconds (
  video_id TEXT, second INTEGER, detections INTEGER, clarity REAL,
  PRIMARY KEY (video_id, second)
);
CREATE TABLE IF NOT EXISTS segments (
  id INTEGER PRIMARY KEY, video_id TEXT, idx INTEGER, start REAL, end REAL,
  kind TEXT, is_audit INTEGER DEFAULT 0, is_dense INTEGER DEFAULT 0, low_vis INTEGER DEFAULT 0,
  score REAL DEFAULT 0, status TEXT DEFAULT 'needs_review'
);
CREATE TABLE IF NOT EXISTS tracks (
  id INTEGER PRIMARY KEY, video_id TEXT, ext_id INTEGER, manual INTEGER DEFAULT 0,
  first_t REAL, last_t REAL, conf REAL DEFAULT 0, crop_path TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS detections (
  track_id INTEGER, t REAL, x REAL, y REAL, w REAL, h REAL, conf REAL
);
CREATE INDEX IF NOT EXISTS detections_track ON detections (track_id, t);
CREATE TABLE IF NOT EXISTS candidates (
  track_id INTEGER, rank INTEGER, species TEXT, common TEXT, score REAL
);
CREATE TABLE IF NOT EXISTS decisions (
  track_id INTEGER PRIMARY KEY, state TEXT NOT NULL, species TEXT, decided_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS school_counts (
  id INTEGER PRIMARY KEY, video_id TEXT, t REAL, frame_path TEXT, proposed INTEGER DEFAULT 0,
  removed INTEGER DEFAULT 0, added INTEGER DEFAULT 0, total INTEGER DEFAULT 0, saved INTEGER DEFAULT 0,
  note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS school_dots (count_id INTEGER, x REAL, y REAL, source TEXT);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, video_id TEXT, type TEXT, payload TEXT DEFAULT '',
  created_at REAL DEFAULT ((julianday('now') - 2440587.5) * 86400.0)
);
"""


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=OFF")
    return con


@contextmanager
def session():
    con = connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    with session() as con:
        con.executescript(SCHEMA)
        if "static" not in {r["name"] for r in con.execute("PRAGMA table_info(tracks)")}:
            con.execute("ALTER TABLE tracks ADD COLUMN static INTEGER DEFAULT 0")
        columns = {r["name"] for r in con.execute("PRAGMA table_info(videos)")}
        for name, kind in (("detector", "TEXT DEFAULT 'cfd-nano'"), ("source_id", "TEXT DEFAULT ''"),
                           ("analysis_s", "REAL DEFAULT 0"), ("frames", "INTEGER DEFAULT 0")):
            if name not in columns:
                con.execute(f"ALTER TABLE videos ADD COLUMN {name} {kind}")
        columns = {r["name"] for r in con.execute("PRAGMA table_info(school_counts)")}
        for name, kind in (("kind", "TEXT DEFAULT 'school'"), ("status", "TEXT DEFAULT ''")):
            if name not in columns:
                con.execute(f"ALTER TABLE school_counts ADD COLUMN {name} {kind}")
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS snapshot_frame ON school_counts (video_id, kind, t) "
            "WHERE kind IN ('snapshot', 'peak')"
        )


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]
