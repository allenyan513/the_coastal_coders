"""Freeze frame on the Video tab: saved boxes at a lower threshold, offered as possible fish."""
import pytest
from fastapi.testclient import TestClient

from tidecount import db, settings
from tidecount.app import app

client = TestClient(app)


def add_video(video_id="v1"):
    with db.session() as con:
        con.execute("INSERT INTO videos (id, name, path, status) VALUES (?, 'v.mp4', '/nowhere', 'Ready to review')", (video_id,))


def add_frame_box(t, x=0.1, y=0.2, w=0.2, h=0.2, conf=0.9):
    with db.session() as con:
        con.execute("INSERT INTO frame_boxes (video_id, t, x, y, w, h, conf) VALUES ('v1', ?, ?, ?, ?, ?, ?)", (t, x, y, w, h, conf))


def add_track(t, x=0.1, y=0.2, w=0.2, h=0.2, state=None):
    with db.session() as con:
        cur = con.execute("INSERT INTO tracks (video_id, ext_id, first_t, last_t, conf) VALUES ('v1', 0, ?, ?, 0.9)", (t, t + 1))
        con.execute("INSERT INTO detections (track_id, t, x, y, w, h, conf) VALUES (?, ?, ?, ?, ?, ?, 0.9)", (cur.lastrowid, t, x, y, w, h))
        if state:
            con.execute("INSERT INTO decisions (track_id, state, species) VALUES (?, ?, NULL)", (cur.lastrowid, state))


def frozen(t):
    r = client.get("/api/videos/v1/frame-boxes", params={"t": t})
    assert r.status_code == 200
    return r.json()


def test_boxes_come_from_the_nearest_analysed_frame_at_the_freeze_threshold():
    add_video()
    add_frame_box(10.0, x=0.1, conf=0.9)
    add_frame_box(10.0, x=0.5, conf=0.26)  # too unsure to track, sure enough to offer
    add_frame_box(10.0, x=0.7, conf=0.2)   # under the freeze threshold of 0.25
    add_frame_box(10.5, x=0.3, conf=0.9)   # a different frame

    got = frozen(10.2)
    assert got["t"] == 10.0
    assert got["threshold"] == 0.25
    assert [b["x"] for b in got["boxes"]] == pytest.approx([0.1, 0.5])


def test_a_box_on_a_track_is_not_offered_again_even_a_rejected_one():
    add_video()
    add_track(10.0, x=0.1)
    add_track(10.0, x=0.5, state="Rejected")
    add_frame_box(10.0, x=0.1)
    add_frame_box(10.0, x=0.5)
    add_frame_box(10.0, x=0.75, w=0.1, h=0.1, conf=0.3)

    assert [b["x"] for b in frozen(10.0)["boxes"]] == pytest.approx([0.75])


def test_two_boxes_on_one_fish_are_offered_once():
    add_video()
    add_frame_box(10.0, x=0.60, y=0.52, w=0.065, h=0.144, conf=0.46)
    add_frame_box(10.0, x=0.60, y=0.52, w=0.065, h=0.145, conf=0.45)

    assert [b["conf"] for b in frozen(10.0)["boxes"]] == pytest.approx([0.46])


def test_the_threshold_is_the_one_the_run_was_analysed_with():
    add_video()
    add_frame_box(10.0, x=0.1, conf=0.9)
    add_frame_box(10.0, x=0.5, conf=0.3)
    with db.session() as con:
        con.execute("UPDATE videos SET settings_json = ? WHERE id = 'v1'", (settings.Settings(defaults={"freeze_threshold": 0.5}).model_dump_json(),))

    assert [b["x"] for b in frozen(10.0)["boxes"]] == pytest.approx([0.1])
