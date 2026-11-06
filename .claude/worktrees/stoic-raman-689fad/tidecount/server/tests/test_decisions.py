import json

import pytest
from fastapi.testclient import TestClient

from tidecount import db
from tidecount.api import app

client = TestClient(app)


@pytest.fixture
def tracks():
    """Three tracks in a fresh video. The second has the highest confidence and its own candidates."""
    with db.session() as con:
        for table in ("videos", "tracks", "detections", "candidates", "decisions", "events"):
            con.execute(f"DELETE FROM {table}")
        con.execute("INSERT INTO videos (id, name, path, status) VALUES ('v', 'v.mp4', '/nowhere', 'Ready to review')")
        ids = []
        for n, (start, conf) in enumerate([(0.0, 0.4), (5.0, 0.9), (20.0, 0.5)]):
            cur = con.execute(
                "INSERT INTO tracks (video_id, ext_id, first_t, last_t, conf, crop_path, static) VALUES ('v', ?, ?, ?, ?, ?, ?)",
                (n, start, start + 2, conf, f"/crops/{n}.jpg", int(n == 0)),
            )
            ids.append(cur.lastrowid)
            con.execute("INSERT INTO detections (track_id, t, x, y, w, h, conf) VALUES (?, ?, 0.1, 0.1, 0.1, 0.1, ?)", (ids[-1], start, conf))
            con.execute("INSERT INTO candidates (track_id, rank, species, common, score) VALUES (?, 0, ?, ?, 0.5)", (ids[-1], f"Species {n}", f"Fish {n}"))
    return ids


def state(track_id):
    with db.session() as con:
        row = con.execute("SELECT state, species FROM decisions WHERE track_id = ?", (track_id,)).fetchone()
    return tuple(row) if row else None


def events():
    with db.session() as con:
        return [(r["type"], json.loads(r["payload"])) for r in con.execute("SELECT type, payload FROM events ORDER BY id")]


def test_bulk_writes_the_same_decisions_and_events_as_one_at_a_time(tracks):
    a, b, _ = tracks
    client.put(f"/api/tracks/{a}/decision", json={"state": "Confirmed", "species": "Fish 0"})
    client.put(f"/api/tracks/{b}/decision", json={"state": "Rejected", "species": None})
    single = ([state(a), state(b)], events())

    with db.session() as con:
        con.execute("DELETE FROM decisions")
        con.execute("DELETE FROM events")
    res = client.put("/api/tracks/decisions", json={"items": [
        {"track_id": a, "state": "Confirmed", "species": "Fish 0"},
        {"track_id": b, "state": "Rejected", "species": None},
    ]})

    assert res.status_code == 200
    assert ([state(a), state(b)], events()) == single


def test_bulk_can_clear_and_restore_decisions_for_undo(tracks):
    a, b, _ = tracks
    client.put(f"/api/tracks/{a}/decision", json={"state": "Corrected", "species": "Fish 2"})
    client.put("/api/tracks/decisions", json={"items": [
        {"track_id": a, "state": "Rejected"},
        {"track_id": b, "state": "Rejected"},
    ]})

    client.put("/api/tracks/decisions", json={"items": [
        {"track_id": a, "state": "Corrected", "species": "Fish 2"},
        {"track_id": b, "state": None},
    ]})

    assert state(a) == ("Corrected", "Fish 2")
    assert state(b) is None
    assert events()[-1] == ("undo", {"track": b})


@pytest.mark.parametrize("bad, status", [({"track_id": 999999, "state": "Rejected"}, 404), ("unknown state", 400)])
def test_bulk_saves_all_or_nothing(tracks, bad, status):
    a, b, _ = tracks
    item = {"track_id": b, "state": "Sideways"} if bad == "unknown state" else bad

    res = client.put("/api/tracks/decisions", json={"items": [{"track_id": a, "state": "Rejected"}, item]})

    assert res.status_code == status
    assert state(a) is None
    assert events() == []


def test_unmerge_restores_tracks_candidates_and_decisions(tracks):
    a, b, _ = tracks
    client.put(f"/api/tracks/{a}/decision", json={"state": "Corrected", "species": "Fish 2"})
    client.put(f"/api/tracks/{b}/decision", json={"state": "Rejected"})
    before = client.get("/api/videos/v/tracks").json()

    kept = client.post("/api/tracks/merge", json={"ids": [a, b]}).json()["id"]
    merged = client.get("/api/videos/v/tracks").json()
    assert kept == a and len(merged) == 2 and len(merged[0]["points"]) == 2
    assert ("merge", {"keep": a, "merged": [b]}) in events()

    res = client.post(f"/api/tracks/{kept}/unmerge")

    assert res.status_code == 200
    assert client.get("/api/videos/v/tracks").json() == before
    assert events()[-1] == ("unmerge", {"keep": a, "restored": [b]})


def test_unmerge_refuses_a_merge_already_undone_or_never_made(tracks):
    a, b, c = tracks
    client.post("/api/tracks/merge", json={"ids": [a, b]})
    assert client.post(f"/api/tracks/{a}/unmerge").status_code == 200

    assert client.post(f"/api/tracks/{a}/unmerge").status_code == 400
    assert client.post(f"/api/tracks/{c}/unmerge").status_code == 400
