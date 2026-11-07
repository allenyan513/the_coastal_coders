import csv
import io

from fastapi.testclient import TestClient

from tidecount import db, surveys
from tidecount.app import app

client = TestClient(app)


def add_sample():
    with db.session() as con:
        surveys.sample(con)


def add_video(video_id="v1", source_id="", station_id="", status="Queued"):
    with db.session() as con:
        con.execute(
            "INSERT INTO videos (id, name, path, source_id, station_id, status) VALUES (?, 'T1-STAT2 411.MP4', '/nowhere.mp4', ?, ?, ?)",
            (video_id, source_id, station_id, status),
        )


def tree():
    return client.get("/api/surveys").json()


def test_a_new_database_starts_empty_and_init_says_the_tables_are_new(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "fresh.db")
    assert db.init() is True
    assert db.init() is False  # the second start keeps what a manager changed
    assert tree() == {"sites": [], "transects": [], "stations": [], "places": {}, "filmedOn": {}}


def test_the_sample_matches_the_web_report_ids():
    add_sample()
    t = tree()
    assert [s["id"] for s in t["sites"]] == ["mahone-bay", "lahave"]
    assert {"id": "t1", "siteId": "mahone-bay", "name": "T1", "archived": False} in t["transects"]
    assert len(t["stations"]) == 12
    assert t["stations"][0] == {"id": "t1-s1", "transectId": "t1", "name": "STAT1", "coordinates": "", "depth": "", "archived": False}


def test_add_change_and_archive_a_whole_branch():
    site = client.post("/api/surveys/sites", json={"name": " Medway River ", "flag": "reference"}).json()["id"]
    transect = client.post("/api/surveys/transects", json={"name": "T1", "parent_id": site}).json()["id"]
    r = client.post("/api/surveys/stations", json={"id": "chosen-id", "name": "STAT1", "depth": "2.5", "parent_id": transect})
    assert r.json() == {"id": "chosen-id"}

    assert client.patch(f"/api/surveys/sites/{site}", json={"coordinates": "44.1, -64.7"}).status_code == 200
    assert client.patch(f"/api/surveys/stations/chosen-id", json={"archived": True}).status_code == 200
    t = tree()
    assert t["sites"][0] == {"id": site, "name": "Medway River", "coordinates": "44.1, -64.7", "flag": "reference", "archived": False}
    assert t["stations"][0]["archived"] is True and t["stations"][0]["depth"] == "2.5"


def test_names_are_unique_among_siblings_only():
    add_sample()
    r = client.post("/api/surveys/transects", json={"name": "t1", "parent_id": "mahone-bay"})
    assert r.status_code == 409 and r.json()["detail"] == "There's already a transect called t1 here."
    # Another site can have its own T1.
    assert client.post("/api/surveys/sites", json={"name": "Medway"}).status_code == 200
    assert client.patch("/api/surveys/stations/t1-s1", json={"name": "STAT2"}).status_code == 409
    assert client.patch("/api/surveys/stations/t1-s1", json={"name": "stat1"}).status_code == 200  # its own name, new case


def test_bad_input_is_refused():
    add_sample()
    assert client.post("/api/surveys/sites", json={"name": "  "}).status_code == 400
    assert client.post("/api/surveys/sites", json={"name": "X", "flag": "control"}).status_code == 400
    assert client.post("/api/surveys/stations", json={"name": "STAT9"}).status_code == 400
    assert client.post("/api/surveys/stations", json={"name": "STAT9", "parent_id": "nope"}).status_code == 404
    assert client.post("/api/surveys/sites", json={"id": "lahave", "name": "Again"}).status_code == 409
    assert client.patch("/api/surveys/sites/nope", json={"name": "X"}).status_code == 404
    assert client.post("/api/surveys/rivers", json={"name": "X"}).status_code == 422


def test_delete_takes_what_sits_under_it_but_never_filed_footage():
    add_sample()
    add_video(station_id="t1-s2")
    r = client.delete("/api/surveys/sites/mahone-bay")
    assert r.status_code == 409 and "1 video is filed here" in r.json()["detail"]
    assert client.delete("/api/surveys/stations/t1-s2").status_code == 409

    assert client.delete("/api/surveys/transects/t2").status_code == 200
    t = tree()
    assert "t2" not in {x["id"] for x in t["transects"]}
    assert not [s for s in t["stations"] if s["transectId"] == "t2"]

    assert client.delete("/api/surveys/sites/lahave").status_code == 200
    t = tree()
    assert [s["id"] for s in t["sites"]] == ["mahone-bay"]
    assert {x["siteId"] for x in t["transects"]} == {"mahone-bay"}


def test_a_place_is_shared_by_every_run_of_a_video():
    add_sample()
    add_video("v1")
    add_video("v2", source_id="v1")  # the same footage, run with another model
    assert client.put("/api/videos/v2/place", json={"station_id": "t1-s2", "filmed_on": "2026-09-30"}).status_code == 200
    t = tree()
    assert t["places"] == {"v1": "t1-s2"} and t["filmedOn"] == {"v1": "2026-09-30"}

    # A field left out stays; an empty one clears it.
    client.put("/api/videos/v1/place", json={"filmed_on": ""})
    t = tree()
    assert t["places"] == {"v1": "t1-s2"} and t["filmedOn"] == {}
    with db.session() as con:
        assert {r["station_id"] for r in con.execute("SELECT station_id FROM videos")} == {"t1-s2"}
    # Two runs, one video: the station counts it once.
    assert client.delete("/api/surveys/stations/t1-s2").json()["detail"].startswith("1 video is")


def test_a_place_must_exist_and_a_date_must_be_a_real_day():
    add_sample()
    add_video()
    assert client.put("/api/videos/v1/place", json={"station_id": "nope"}).status_code == 404
    assert client.put("/api/videos/v1/place", json={"filmed_on": "2026-02-30"}).status_code == 400
    assert client.put("/api/videos/v1/place", json={"filmed_on": "30/09/2026"}).status_code == 400
    assert client.put("/api/videos/nope/place", json={"station_id": "t1-s1"}).status_code == 404


def test_filing_many_is_all_or_nothing():
    add_sample()
    add_video("v1")
    add_video("v2")
    assert client.put("/api/videos/places", json={"items": {"v1": "t1-s1", "v2": "nope"}}).status_code == 404
    assert tree()["places"] == {}
    assert client.put("/api/videos/places", json={"items": {"v1": "t1-s1", "v2": "l2-s3"}}).status_code == 200
    assert tree()["places"] == {"v1": "t1-s1", "v2": "l2-s3"}


def test_import_files_the_video_in_the_same_request(tmp_path):
    add_sample()
    clip = tmp_path / "T1-STAT2 411.MP4"
    clip.write_bytes(b"not really a video")
    r = client.post("/api/videos/import-path", json={"path": str(clip), "station_id": "t1-s2", "filmed_on": "2026-10-01"})
    video_id = r.json()["id"]
    r = client.post("/api/videos", files={"file": ("b.mp4", b"x")}, data={"station_id": "l1-s1", "filmed_on": "2026-10-02"})
    upload_id = r.json()["id"]
    assert tree()["places"] == {video_id: "t1-s2", upload_id: "l1-s1"}

    # A bad station is refused before the file is kept.
    r = client.post("/api/videos", files={"file": ("c.mp4", b"x")}, data={"station_id": "nope"})
    assert r.status_code == 404
    assert len(client.get("/api/videos").json()) == 2

    # A rerun keeps the place.
    with db.session() as con:
        con.execute("UPDATE videos SET status = 'Ready to review'")
    assert client.post(f"/api/videos/{video_id}/reanalyze", json={"detector": "cfd-medium"}).status_code == 200
    with db.session() as con:
        rerun = con.execute("SELECT station_id, filmed_on FROM videos WHERE source_id = ?", (video_id,)).fetchone()
        assert (rerun["station_id"], rerun["filmed_on"]) == ("t1-s2", "2026-10-01")


def test_the_report_names_the_place_as_it_is_now():
    add_sample()
    add_video(station_id="t1-s2", status="Ready to review")
    client.put("/api/videos/v1/place", json={"filmed_on": "2026-10-01"})
    client.patch("/api/surveys/sites/mahone-bay", json={"name": "Mahone Bay"})
    with db.session() as con:
        v = dict(con.execute("SELECT * FROM videos WHERE id = 'v1'").fetchone())
        assert surveys.where(con, v) == {"site": "Mahone Bay", "transect": "T1", "station": "STAT2"}
    with db.session() as con:
        con.execute("UPDATE videos SET station_id = '', site = 'Typed by hand' WHERE id = 'v1'")
        v = dict(con.execute("SELECT * FROM videos WHERE id = 'v1'").fetchone())
        assert surveys.where(con, v)["site"] == "Typed by hand"


def test_the_sheets_use_the_station_a_person_chose():
    add_sample()
    add_video(station_id="l2-s3", status="Ready to review")  # the file name says T1-STAT2
    client.put("/api/videos/v1/place", json={"filmed_on": "2026-10-01"})
    with db.session() as con:
        con.execute("UPDATE videos SET duration = 1200 WHERE id = 'v1'")  # long enough for sub-sample points

    rows = list(csv.reader(io.StringIO(client.get("/api/videos/v1/export.csv").text)))
    values = {r[0]: r[1] for r in rows if len(r) == 2}
    assert (values["site"], values["transect"], values["station"], values["filmed_on"]) == ("LaHave River Estuary", "T2", "STAT3", "2026-10-01")

    sheet = list(csv.reader(io.StringIO(client.get("/api/videos/v1/protocol.csv").text.lstrip("\ufeff"))))
    assert sheet[0][1:3] == ["Transect", "STAT"]
    assert sheet[1][1:3] == ["T2", "3"]
