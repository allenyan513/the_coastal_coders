"""The survey structure: Site → Transect → Station, and where and when each video was filmed.

A video's station and filmed date are kept on every run of it, so a rerun with another model reads
the same place. Plain functions on a database connection, so they can be tested without HTTP.
"""
import re
import uuid
from datetime import date

from . import db

# Each kind's table, the column that points at its parent, and the fields a person can change.
KINDS = {
    "sites": {"parent": None, "fields": ("name", "coordinates", "flag", "archived")},
    "transects": {"parent": "site_id", "fields": ("name", "archived")},
    "stations": {"parent": "transect_id", "fields": ("name", "coordinates", "depth", "archived")},
}
PARENT_KIND = {"transects": "sites", "stations": "transects"}
WORD = {"sites": "site", "transects": "transect", "stations": "station"}
FLAGS = ("", "treatment", "reference")


class Problem(Exception):
    """A change the structure can't take. `status` is the HTTP code the route answers with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def sample(con) -> None:
    """Sample structure. The place names are real, but these sites, transects and stations are made up.

    The ids match the sample numbers on the web's Reports page.
    """
    sites = [("mahone-bay", "Mahone Bay Living Shoreline", "treatment"), ("lahave", "LaHave River Estuary", "reference")]
    transects = [("t1", "mahone-bay", "T1"), ("t2", "mahone-bay", "T2"), ("l1", "lahave", "T1"), ("l2", "lahave", "T2")]
    con.executemany("INSERT OR IGNORE INTO sites (id, name, flag) VALUES (?, ?, ?)", sites)
    con.executemany("INSERT OR IGNORE INTO transects (id, site_id, name) VALUES (?, ?, ?)", transects)
    con.executemany(
        "INSERT OR IGNORE INTO stations (id, transect_id, name) VALUES (?, ?, ?)",
        [(f"{t}-s{n}", t, f"STAT{n}") for t, _, _ in transects for n in (1, 2, 3)],
    )


def tree(con) -> dict:
    """Everything the web needs in one answer: the structure, plus each video's station and date by its first import."""
    def items(sql: str) -> list[dict]:
        return [{**r, "archived": bool(r["archived"])} for r in db.rows(con.execute(sql))]

    videos = db.rows(con.execute(
        "SELECT CASE WHEN source_id != '' THEN source_id ELSE id END AS root, station_id, filmed_on FROM videos ORDER BY created_at"
    ))
    return {
        "sites": items("SELECT id, name, coordinates, flag, archived FROM sites ORDER BY rowid"),
        "transects": items("SELECT id, site_id AS siteId, name, archived FROM transects ORDER BY rowid"),
        "stations": items("SELECT id, transect_id AS transectId, name, coordinates, depth, archived FROM stations ORDER BY rowid"),
        "places": {v["root"]: v["station_id"] for v in videos if v["station_id"]},
        "filmedOn": {v["root"]: v["filmed_on"] for v in videos if v["filmed_on"]},
    }


def get(con, kind: str, item_id: str) -> dict:
    row = con.execute(f"SELECT * FROM {kind} WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise Problem(404, f"That {WORD[kind]} doesn't exist.")
    return dict(row)


def stations_under(con, kind: str, item_id: str) -> list[str]:
    if kind == "stations":
        return [item_id]
    transects = [item_id] if kind == "transects" else [r["id"] for r in con.execute("SELECT id FROM transects WHERE site_id = ?", (item_id,))]
    marks = ",".join("?" * len(transects))
    return [r["id"] for r in con.execute(f"SELECT id FROM stations WHERE transect_id IN ({marks})", transects)]


def video_count(con, kind: str, item_id: str) -> int:
    """How many videos are filed under an item, directly or through what sits under it. Reruns count once."""
    stations = stations_under(con, kind, item_id)
    marks = ",".join("?" * len(stations))
    return con.execute(
        f"SELECT COUNT(*) AS n FROM videos WHERE source_id = '' AND station_id IN ({marks})", stations
    ).fetchone()["n"]


def check_name(con, kind: str, name: str, parent_id: str | None, item_id: str | None) -> str:
    """Names must be unique among siblings, because file names are matched to stations by them."""
    name = name.strip()
    if not name:
        raise Problem(400, f"Enter a {WORD[kind]} name.")
    parent = KINDS[kind]["parent"]
    sql = f"SELECT 1 FROM {kind} WHERE lower(name) = lower(?) AND id != ?"
    args = [name, item_id or ""]
    if parent:
        sql += f" AND {parent} = ?"
        args.append(parent_id)
    if con.execute(sql, args).fetchone():
        raise Problem(409, f"There's already a {WORD[kind]} called {name} here.")
    return name


def clean(kind: str, values: dict) -> dict:
    out = {k: v.strip() if isinstance(v, str) else v for k, v in values.items() if k in KINDS[kind]["fields"] and v is not None}
    if "flag" in out and out["flag"] not in FLAGS:
        raise Problem(400, "A site is a treatment site, a reference site, or not set.")
    if "archived" in out:
        out["archived"] = int(bool(out["archived"]))
    return out


def add(con, kind: str, values: dict, parent_id: str | None = None, item_id: str | None = None) -> str:
    if kind in PARENT_KIND:
        if not parent_id:
            raise Problem(400, f"A {WORD[kind]} needs a {WORD[PARENT_KIND[kind]]}.")
        get(con, PARENT_KIND[kind], parent_id)
    item_id = item_id or uuid.uuid4().hex[:8]
    if con.execute(f"SELECT 1 FROM {kind} WHERE id = ?", (item_id,)).fetchone():
        raise Problem(409, f"That {WORD[kind]} already exists.")
    row = clean(kind, values)
    row["name"] = check_name(con, kind, values.get("name") or "", parent_id, None)
    row["id"] = item_id
    if KINDS[kind]["parent"]:
        row[KINDS[kind]["parent"]] = parent_id
    con.execute(f"INSERT INTO {kind} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
    return item_id


def change(con, kind: str, item_id: str, values: dict) -> None:
    current = get(con, kind, item_id)
    row = clean(kind, values)
    if "name" in row:
        parent = KINDS[kind]["parent"]
        row["name"] = check_name(con, kind, row["name"], current[parent] if parent else None, item_id)
    if row:
        con.execute(f"UPDATE {kind} SET {', '.join(f'{k} = ?' for k in row)} WHERE id = ?", [*row.values(), item_id])


def remove(con, kind: str, item_id: str) -> None:
    """Removes an item and what sits under it, only when no video is filed there, so old records stay whole."""
    get(con, kind, item_id)
    used = video_count(con, kind, item_id)
    if used:
        raise Problem(409, f"{used} {'video is' if used == 1 else 'videos are'} filed here, so it can't be deleted. Archive it instead.")
    stations = stations_under(con, kind, item_id)
    con.executemany("DELETE FROM stations WHERE id = ?", [(s,) for s in stations])
    if kind == "sites":
        con.execute("DELETE FROM transects WHERE site_id = ?", (item_id,))
    if kind != "stations":
        con.execute(f"DELETE FROM {kind} WHERE id = ?", (item_id,))


def check_place(con, station_id: str | None, filmed_on: str | None) -> None:
    """A station that exists, or blank. A date as YYYY-MM-DD, or blank."""
    if station_id:
        get(con, "stations", station_id)
    if filmed_on:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", filmed_on):
                raise ValueError
            date.fromisoformat(filmed_on)
        except ValueError:
            raise Problem(400, "Give the filmed date as YYYY-MM-DD.") from None


def place(con, video_id: str, station_id: str | None = None, filmed_on: str | None = None) -> None:
    """File a video under a station and set its filmed date, on every run of it. None leaves a value as it is."""
    row = con.execute("SELECT id, source_id FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not row:
        raise Problem(404, "Video not found")
    check_place(con, station_id, filmed_on)
    root = row["source_id"] or row["id"]
    for column, value in (("station_id", station_id), ("filmed_on", filmed_on)):
        if value is not None:
            con.execute(f"UPDATE videos SET {column} = ? WHERE id = ? OR source_id = ?", (value, root, root))


def where(con, v: dict) -> dict:
    """A video's site, transect and station names, read now so a rename shows up. Older videos fall back to their typed site."""
    row = con.execute(
        "SELECT si.name AS site, t.name AS transect, st.name AS station FROM stations st "
        "JOIN transects t ON t.id = st.transect_id JOIN sites si ON si.id = t.site_id WHERE st.id = ?",
        (v.get("station_id") or "",),
    ).fetchone()
    return dict(row) if row else {"site": v.get("site") or "", "transect": "", "station": ""}
