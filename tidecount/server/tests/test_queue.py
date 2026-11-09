from fastapi.testclient import TestClient

from tidecount import analysis_queue, db
from tidecount.app import app

client = TestClient(app)
NOW = 1_000_000.0


def add(video_id, status="Queued", duration=60.0, detector="cfd-nano", queued_at=None, started_at=None, finished_at=None):
    with db.session() as con:
        con.execute(
            "INSERT INTO videos (id, name, path, status, duration, detector, queued_at, started_at, finished_at)"
            " VALUES (?, ?, '/n.mp4', ?, ?, ?, ?, ?, ?)",
            (video_id, f"{video_id}.mp4", status, duration, detector, queued_at, started_at, finished_at),
        )


def finished(video_id, duration, took, detector="cfd-nano"):
    """A run that took `took` seconds for `duration` seconds of footage."""
    add(video_id, "Ready to review", duration, detector, queued_at=0, started_at=100, finished_at=100 + took)


def estimate():
    with db.session() as con:
        return analysis_queue.estimate(con, now=NOW)


def test_the_queue_goes_by_queued_time_and_a_tie_by_insertion_order():
    add("b", queued_at=5)
    add("a", queued_at=5)
    add("c", queued_at=1)
    with db.session() as con:
        assert analysis_queue.next_queued(con) == "c"
    assert {k: v["ahead"] for k, v in estimate().items()} == {"c": 0, "b": 1, "a": 2}


def test_a_retry_waits_behind_what_was_already_queued():
    add("old", "Failed", queued_at=1)
    add("new", queued_at=2)
    assert client.post("/api/videos/old/retry").status_code == 200
    with db.session() as con:
        assert analysis_queue.next_queued(con) == "new"
    assert estimate()["old"]["ahead"] == 1


def test_without_a_finished_run_there_is_a_place_but_no_times():
    add("running", "Analyzing", started_at=NOW - 10)
    add("waiting", queued_at=1)
    assert estimate() == {
        "running": {"ahead": 0, "starts_in_s": 0.0, "done_in_s": None},
        "waiting": {"ahead": 1, "starts_in_s": None, "done_in_s": None},
    }


def test_times_add_up_from_this_computers_own_rate():
    finished("f1", duration=100, took=200)  # 2 s of work per second of footage
    add("running", "Analyzing", duration=60, started_at=NOW - 20)  # 120 s expected, 100 left
    add("w1", duration=30, queued_at=1)  # 60 s
    add("w2", duration=10, queued_at=2)  # 20 s
    got = estimate()
    assert got["running"] == {"ahead": 0, "starts_in_s": 0.0, "done_in_s": 100.0}
    assert got["w1"] == {"ahead": 1, "starts_in_s": 100.0, "done_in_s": 160.0}
    assert got["w2"] == {"ahead": 2, "starts_in_s": 160.0, "done_in_s": 180.0}


def test_the_rate_is_the_detectors_own_when_it_has_one():
    finished("fast", duration=100, took=100, detector="cfd-nano")
    finished("slow", duration=100, took=500, detector="cfd-medium")
    add("w", duration=10, detector="cfd-medium", queued_at=1)
    add("x", duration=10, detector="cfd-small", queued_at=2)  # no history: the median over all runs, 3
    got = estimate()
    assert got["w"]["done_in_s"] == 50.0
    assert got["x"]["done_in_s"] == 50.0 + 30.0


def test_a_run_past_its_estimate_has_nothing_left_not_a_negative_time():
    finished("f1", duration=100, took=100)
    add("running", "Analyzing", duration=10, started_at=NOW - 60)
    assert estimate()["running"]["done_in_s"] == 0.0


def test_a_video_of_unknown_length_is_taken_as_the_usual_length():
    finished("f1", duration=100, took=100)
    add("unknown", duration=0, queued_at=1)
    assert estimate()["unknown"]["done_in_s"] == 100.0


def test_the_api_puts_the_queue_on_waiting_videos_only():
    finished("f1", duration=100, took=100)
    add("w", duration=30, queued_at=1)
    rows = {v["id"]: v for v in client.get("/api/videos").json()}
    assert rows["f1"]["queue"] is None
    assert rows["w"]["queue"] == {"ahead": 0, "starts_in_s": 0.0, "done_in_s": 30.0}
    assert client.get("/api/videos/w").json()["queue"]["ahead"] == 0


def test_an_upload_ffmpeg_cant_read_is_still_queued_with_no_length():
    r = client.post("/api/videos", files={"file": ("x.mp4", b"not a video")})
    v = client.get(f"/api/videos/{r.json()['id']}").json()
    assert (v["status"], v["duration"]) == ("Queued", 0)
    assert v["queue"]["ahead"] == 0
