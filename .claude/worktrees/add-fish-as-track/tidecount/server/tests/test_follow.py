import numpy as np
import pytest
from fastapi.testclient import TestClient

from tidecount import config, db, follow, summary
from tidecount.app import app

client = TestClient(app)
FPS = config.FOLLOW_FPS


def box(x, y, w=40.0, h=20.0):
    return (float(x), float(y), float(w), float(h))


# Choosing the box that is the same fish.

def test_takes_the_box_where_the_fish_should_be_and_not_a_neighbour():
    expected = box(100, 100)
    same = (box(104, 101), 0.06)
    neighbour = (box(170, 100), 0.9)

    assert follow.pick([neighbour, same], expected) == same


def test_takes_nothing_when_no_box_fits():
    expected = box(100, 100)

    assert follow.pick([(box(300, 300), 0.9)], expected) is None
    assert follow.pick([], expected) is None


def test_a_box_that_changed_size_too_much_is_another_thing():
    expected = box(100, 100)
    whole_school = (box(60, 60, 160, 120), 0.9)

    assert follow.pick([whole_school], expected) is None


def test_a_loose_hand_drawn_box_snaps_to_the_fish_inside_it():
    drawn = box(100, 100, 120, 80)
    fish = (box(130, 125, 50, 25), 0.07)
    outside = (box(300, 125, 50, 25), 0.9)

    assert follow.snap([outside, fish], drawn) == fish
    assert follow.snap([outside], drawn) is None


# Stopping on something that doesn't move, such as a mark on the lens.

def hits(seconds, speed):
    return [(i / FPS, box(100 + speed * i / FPS, 100), 0.1) for i in range(int(seconds * FPS) + 1)]


def test_a_box_that_stays_put_counts_as_still_and_a_swimming_fish_doesnt():
    assert follow.is_still(hits(4.0, speed=0))
    assert not follow.is_still(hits(4.0, speed=60))


def test_a_short_stretch_is_never_called_still():
    assert not follow.is_still(hits(0.5, speed=0))


# The endpoint. No video file exists here, so nothing can be followed.

@pytest.fixture
def video():
    with db.session() as con:
        con.execute("INSERT INTO videos (id, name, path, status, width, height, duration) VALUES ('v', 'v.mp4', '/nowhere', 'Ready to review', 1920, 1080, 60)")
        con.execute("INSERT INTO segments (video_id, idx, start, end, kind, status) VALUES ('v', 0, 0, 60, 'active', 'needs_review')")


def tracks():
    return client.get("/api/videos/v/tracks").json()


def test_a_fish_that_cant_be_followed_is_still_added_and_counted(video):
    added = client.post("/api/videos/v/tracks", json={"t": 5.0, "x": 0.2, "y": 0.3, "w": 0.1, "h": 0.05}).json()

    [track] = tracks()
    assert track["id"] == added["id"] and added["points"] == 1
    assert track["manual"] == 1 and track["state"] == "Corrected" and track["decided_species"] == "Fish, unidentified"
    assert track["points"] == [[5.0, 0.2, 0.3, 0.1, 0.05]]
    assert track["first_t"] == 5.0 and track["last_t"] > 5.0


def test_a_box_drawn_past_the_edge_is_pulled_back_into_the_frame(video):
    client.post("/api/videos/v/tracks", json={"t": 5.0, "x": -0.04, "y": 0.97, "w": 0.1, "h": 0.08})

    [[_, x, y, w, h]] = tracks()[0]["points"]
    assert x == 0 and y + h == pytest.approx(1)


def test_removing_an_added_fish_leaves_nothing_behind(video):
    added = client.post("/api/videos/v/tracks", json={"t": 5.0, "x": 0.2, "y": 0.3}).json()

    assert client.delete(f"/api/tracks/{added['id']}").status_code == 200

    assert tracks() == []
    with db.session() as con:
        assert con.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM detections").fetchone()[0] == 0


def test_an_ai_track_cant_be_removed(video):
    with db.session() as con:
        cur = con.execute("INSERT INTO tracks (video_id, ext_id, first_t, last_t, conf) VALUES ('v', 1, 0, 2, 0.8)")

    assert client.delete(f"/api/tracks/{cur.lastrowid}").status_code == 400
    assert len(tracks()) == 1


def test_the_report_says_how_many_fish_a_person_added(video):
    with db.session() as con:
        cur = con.execute("INSERT INTO tracks (video_id, ext_id, first_t, last_t, conf) VALUES ('v', 1, 0, 2, 0.8)")
        con.execute("INSERT INTO decisions (track_id, state, species) VALUES (?, 'Confirmed', 'Atlantic Cod')", (cur.lastrowid,))
    client.post("/api/videos/v/tracks", json={"t": 5.0, "x": 0.2, "y": 0.3})
    client.post("/api/videos/v/tracks", json={"t": 9.0, "x": 0.5, "y": 0.5})

    s = client.get("/api/videos/v/summary").json()

    assert s["entries"] == 3 and s["entries_added"] == 2
    assert "entries_ai_missed_and_a_person_added,2" in summary.to_csv(s)


# Following end to end, with stand-ins for the video and the detector.

class Frame:
    """A frame that only knows its time, which is all the stand-in detector needs."""

    def __init__(self, t):
        self.t = t


@pytest.fixture
def stand_ins(monkeypatch):
    """A fake video, and a detector that sees one 40 by 20 fish from x = 100, swimming right until `until`."""
    def use(speed, until):
        monkeypatch.setattr(follow.video, "decode_span", lambda path, start, seconds, w, h, fps: [(start + i / fps, Frame(start + i / fps)) for i in range(round(seconds * fps))])
        monkeypatch.setattr(follow, "look", lambda detector, frame, expected: [] if frame.t > until else [(box(100 + speed * frame.t, 200), 0.08)])
        monkeypatch.setattr(follow, "thumb", lambda frame: np.zeros((36, 64)))
        monkeypatch.setattr(follow.tracking, "crop_for", lambda frame, xyxy, scale: np.ones((20, 40, 3), dtype=np.uint8))
    return use


def test_follows_a_fish_both_ways_until_the_detector_loses_it(stand_ins):
    stand_ins(speed=80, until=3.0)

    got = follow.follow(None, "/nowhere", 640, 480, 60.0, 1.0, box(170, 190, 60, 40))

    assert got.snapped
    assert got.hits[0][0] == pytest.approx(0.0) and got.hits[-1][0] == pytest.approx(3.0)
    assert got.stopped == {"before": "video start", "after": "lost"}
    assert all(b[0] == pytest.approx(100 + 80 * t) for t, b, _ in got.hits)
    assert got.crop is not None


def test_a_fish_that_rests_where_it_was_boxed_is_kept_for_a_few_seconds(stand_ins):
    stand_ins(speed=0, until=99)

    got = follow.follow(None, "/nowhere", 640, 480, 60.0, 10.0, box(90, 190, 60, 40))

    assert got.stopped == {"before": "stopped moving", "after": "stopped moving"}
    assert 1.5 * config.FOLLOW_STILL_S <= got.hits[-1][0] - got.hits[0][0] <= 2 * config.FOLLOW_STILL_S


def test_a_fish_that_swam_and_then_stops_loses_the_still_stretch(monkeypatch, stand_ins):
    stand_ins(speed=80, until=99)
    # Swims right until 2 s, then the box sits on one spot, as it does on a mark on the lens.
    monkeypatch.setattr(follow, "look", lambda detector, frame, expected: [(box(100 + 80 * min(frame.t, 2.0), 200), 0.08)])

    got = follow.follow(None, "/nowhere", 640, 480, 60.0, 1.0, box(170, 190, 60, 40))

    assert got.stopped["after"] == "stopped moving"
    assert got.hits[-1][0] == pytest.approx(2.0, abs=0.35)
