import csv
import io
import json
import sqlite3
import subprocess

import pytest
from fastapi.testclient import TestClient

from tidecount import config, db, snapshots, video
from tidecount.app import app

client = TestClient(app)
FPS = 2
PARTIAL = "Largest count in checked frames"


def add_video(duration=125.0, counts=None, status="Ready to review", video_id="v1"):
    with db.session() as con:
        con.execute(
            "INSERT INTO videos (id, name, path, duration, width, height, status) VALUES (?, 'clip.mp4', '/nowhere.mp4', ?, 1280, 720, ?)",
            (video_id, duration, status),
        )
        con.executemany(
            "INSERT INTO seconds (video_id, second, detections, clarity) VALUES (?, ?, ?, 1)",
            [(video_id, s, n) for s, n in (counts or {}).items()],
        )
    return video_id


def add_box(t, x=0.1, y=0.2, w=0.2, h=0.4, video_id="v1", manual=0, decision=None):
    with db.session() as con:
        track = con.execute(
            "INSERT INTO tracks (video_id, ext_id, manual, first_t, last_t) VALUES (?, 1, ?, ?, ?)", (video_id, manual, t, t),
        ).lastrowid
        con.execute("INSERT INTO detections (track_id, t, x, y, w, h, conf) VALUES (?, ?, ?, ?, ?, ?, 0.9)", (track, t, x, y, w, h))
        if decision:
            con.execute("INSERT INTO decisions (track_id, state) VALUES (?, ?)", (track, decision))
    return track


def add_school(total, saved=1, video_id="v1"):
    with db.session() as con:
        con.execute("INSERT INTO school_counts (video_id, t, total, saved) VALUES (?, 7, ?, ?)", (video_id, total, saved))


def opened(video_id="v1"):
    res = client.get(f"/api/videos/{video_id}/snapshots")
    assert res.status_code == 200
    return res.json()


def of_kind(data, kind):
    return [f for f in data["frames"] if f["kind"] == kind]


def save(frame, count=0, status="checked", source="user"):
    dots = [{"x": 0.5, "y": 0.5, "source": source}] * count
    res = client.put(f"/api/snapshot-frames/{frame['id']}", json={"status": status, "dots": dots})
    assert res.status_code == 200
    return res.json()["stats"]


def summary(video_id="v1"):
    return client.get(f"/api/videos/{video_id}/summary").json()


def export(video_id="v1"):
    rows = list(csv.reader(io.StringIO(client.get(f"/api/videos/{video_id}/export.csv").text)))
    return rows, {r[0]: r[1] for r in rows if len(r) == 2}


# Frame times


def test_one_video_hour_is_120_frames_on_the_sampling_grid():
    times = snapshots.snapshot_times(3600, FPS)
    assert len(times) == 120
    assert (times[0], times[1], times[-1]) == (15, 45, 3585)
    assert all(t * FPS == int(t * FPS) for t in times)


@pytest.mark.parametrize("start, snapped", [(15.2, 15.0), (15.3, 15.5)])
def test_times_snap_to_the_nearest_sample(monkeypatch, start, snapped):
    monkeypatch.setattr(config, "SNAPSHOT_START_S", start)
    assert snapshots.snapshot_times(40, FPS)[0] == snapped


@pytest.mark.parametrize("duration, expected", [(0, []), (14.9, []), (15, []), (15.1, [15]), (45, [15]), (45.5, [15, 45])])
def test_no_frame_at_or_past_the_end(duration, expected):
    assert snapshots.snapshot_times(duration, FPS) == expected


# Peak selection


def test_peaks_take_the_highest_counts_at_least_a_minute_apart():
    seconds = [(100, 9), (130, 8), (160, 8), (170, 7), (300, 5), (10, 4)]
    assert snapshots.pick_peaks(seconds, set()) == [10, 100, 160, 300]


def test_spacing_is_inclusive_at_exactly_60_seconds():
    assert snapshots.pick_peaks([(100, 5), (160, 4)], set()) == [100, 160]
    assert snapshots.pick_peaks([(100, 5), (159, 4)], set()) == [100]


def test_at_most_five_peaks_and_ties_go_to_the_earliest():
    seconds = [(s, 3) for s in range(0, 1000, 100)]
    assert snapshots.pick_peaks(seconds, set()) == [0, 100, 200, 300, 400]


def test_seconds_without_fish_are_never_peaks():
    assert snapshots.pick_peaks([(5, 0), (100, 0)], set()) == []


def test_peaks_skip_frames_already_covered_and_use_their_slot_elsewhere():
    assert snapshots.pick_peaks([(45, 9), (200, 5)], {45.0}) == [200]


def test_peak_is_the_busiest_sample_inside_its_second():
    assert snapshots.pick_peaks([(100, 5)], set(), {100: 100.5}) == [100.5]


def test_a_snapshot_on_a_quieter_sample_of_that_second_does_not_cover_the_peak():
    add_video(duration=125, counts={45: 2})
    add_box(45.0)
    add_box(45.5)
    add_box(45.5)
    assert [f["t"] for f in of_kind(opened(), "peak")] == [45.5]


# Creating frames


def test_opening_twice_creates_frames_once():
    add_video(duration=125, counts={50: 4})
    first = opened()
    assert [f["t"] for f in of_kind(first, "snapshot")] == [15, 45, 75, 105]
    assert [f["t"] for f in of_kind(first, "peak")] == [50]
    assert opened()["frames"] == first["frames"]


def test_duplicate_rows_are_refused_by_the_database():
    add_video()
    opened()
    with pytest.raises(sqlite3.IntegrityError), db.session() as con:
        con.execute("INSERT INTO school_counts (video_id, t, kind) VALUES ('v1', 15, 'snapshot')")


def test_a_clip_under_15_seconds_has_no_snapshots_but_can_have_peaks():
    add_video(duration=12, counts={3: 2})
    data = opened()
    assert [(f["kind"], f["t"]) for f in data["frames"]] == [("peak", 3)]
    assert data["stats"]["complete"] is False


def test_a_peak_past_the_end_of_the_video_is_dropped():
    add_video(duration=20.0, counts={20: 9})
    assert of_kind(opened(), "peak") == []


def test_screen_waits_for_analysis():
    add_video(status="Analyzing")
    assert client.get("/api/videos/v1/snapshots").status_code == 409


# Migration


def test_migration_keeps_existing_school_counts(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(db.SCHEMA)
    assert "kind" not in {r[1] for r in con.execute("PRAGMA table_info(school_counts)")}
    con.execute("INSERT INTO school_counts (video_id, t, total, saved) VALUES ('old', 3, 12, 1)")
    con.commit()
    con.close()

    monkeypatch.setattr(db, "DB_PATH", path)
    db.init()
    db.init()
    with db.session() as con:
        row = dict(con.execute("SELECT kind, status, total, saved FROM school_counts").fetchone())
    assert row == {"kind": "school", "status": "", "total": 12, "saved": 1}


# AI dots


def test_ai_dots_are_box_centres_in_the_nearest_sample():
    add_video()
    add_box(15.0, x=0.1, y=0.2, w=0.2, h=0.4)
    add_box(15.5, x=0.8, y=0.8)
    frame = client.get(f"/api/snapshot-frames/{opened()['frames'][0]['id']}").json()
    assert frame["dots"] == [pytest.approx({"x": 0.2, "y": 0.4, "source": "ai"})]


def test_ai_dots_reach_half_a_second_and_no_further():
    add_video()
    add_box(45.5)
    add_box(15.75)
    with db.session() as con:
        assert len(snapshots.ai_dots(con, "v1", 45.0)) == 1
        assert snapshots.ai_dots(con, "v1", 15.0) == []


def test_an_earlier_and_a_later_sample_tie_to_the_earlier():
    add_video()
    add_box(14.5, x=0.1)
    add_box(15.5, x=0.7)
    with db.session() as con:
        assert snapshots.ai_dots(con, "v1", 15.0)[0]["x"] == pytest.approx(0.2)


def test_ai_dots_skip_tracks_a_person_rejected_or_added():
    add_video()
    add_box(15.0, decision="Rejected")
    add_box(15.0, manual=1, decision="Corrected")
    add_box(15.0, decision="Confirmed")
    with db.session() as con:
        assert len(snapshots.ai_dots(con, "v1", 15.0)) == 1


def test_a_saved_frame_shows_what_was_saved():
    add_video()
    add_box(15.0)
    frame = opened()["frames"][0]
    client.put(f"/api/snapshot-frames/{frame['id']}", json={"status": "checked", "dots": [
        {"x": 0.2, "y": 0.4, "source": "ai"}, {"x": 0.9, "y": 0.9, "source": "user"}, {"x": 0.1, "y": 0.1, "source": "user"},
    ]})
    shown = client.get(f"/api/snapshot-frames/{frame['id']}").json()
    assert sorted(d["source"] for d in shown["dots"]) == ["ai", "user", "user"]
    assert shown["status"] == "checked"
    assert (summary()["snapshot_frames"][0]["proposed"], summary()["snapshot_frames"][0]["added"]) == (1, 2)


# MeanCount


def test_mean_count_leaves_out_could_not_see_and_peak_frames():
    add_video(counts={50: 9})
    data = opened()
    a, b, c, d = of_kind(data, "snapshot")
    save(a, 2)
    save(b, 4)
    save(c, status="could_not_see")
    save(of_kind(data, "peak")[0], 90)
    stats = summary()["snapshots"]
    assert stats["mean_count"] == 3
    assert (stats["frames_checked"], stats["frames_total"], stats["could_not_see"]) == (2, 4, 1)
    assert (stats["peak_checked"], stats["peak_total"]) == (1, 1)


def test_a_frame_with_no_dots_counts_as_zero():
    add_video()
    a, b, *_ = opened()["frames"]
    save(a, 0)
    assert summary()["snapshots"]["mean_count"] == 0
    assert summary()["snapshots"]["largest_count"] == 0
    save(b, 3)
    assert summary()["snapshots"]["mean_count"] == 1.5


def test_could_not_see_alone_gives_no_number_at_all():
    add_video()
    a, *_ = opened()["frames"]
    save(a, status="could_not_see")
    stats = summary()["snapshots"]
    assert stats["mean_count"] is None
    assert stats["largest_count"] is None


def test_could_not_see_stores_no_total_and_replaces_an_earlier_count():
    add_video()
    a, b, *_ = opened()["frames"]
    save(a, 5)
    save(b, 1)
    save(a, 5, status="could_not_see")
    assert summary()["snapshots"]["mean_count"] == 1
    with db.session() as con:
        assert con.execute("SELECT total FROM school_counts WHERE id = ?", (a["id"],)).fetchone()["total"] is None
        assert con.execute("SELECT COUNT(*) AS n FROM school_dots WHERE count_id = ?", (a["id"],)).fetchone()["n"] == 0


# Largest count and the MaxN label


def test_largest_count_covers_every_checked_frame_including_peaks_and_schools():
    add_video(counts={50: 9})
    data = opened()
    save(of_kind(data, "snapshot")[0], 3)
    assert summary()["snapshots"]["largest_count"] == 3
    save(of_kind(data, "peak")[0], 6)
    assert summary()["snapshots"]["largest_count"] == 6
    add_school(11)
    assert summary()["snapshots"]["largest_count"] == 11


def test_could_not_see_never_sets_the_largest_count():
    add_video(counts={50: 9})
    data = opened()
    save(of_kind(data, "snapshot")[0], 3)
    save(of_kind(data, "peak")[0], 50, status="could_not_see")
    assert summary()["snapshots"]["largest_count"] == 3


def test_label_is_partial_until_every_snapshot_frame_is_done():
    add_video(counts={50: 9})
    data = opened()
    a, b, c, d = of_kind(data, "snapshot")
    assert data["stats"]["largest_label"] == PARTIAL
    save(a, 1)
    save(b, 1)
    assert save(c, status="could_not_see")["largest_label"] == PARTIAL
    stats = save(d, 2)
    assert stats["largest_label"] == "MaxN"
    assert stats["complete"] is True
    assert stats["peak_checked"] == 0
    assert summary()["snapshots"]["largest_label"] == "MaxN"


def test_a_peak_frame_does_not_complete_the_review():
    add_video(duration=12, counts={3: 2})
    frame, = opened()["frames"]
    assert save(frame, 2)["largest_label"] == PARTIAL


def test_a_school_count_alone_is_partial():
    add_video()
    add_school(40)
    stats = summary()["snapshots"]
    assert (stats["largest_count"], stats["largest_label"], stats["complete"]) == (40, PARTIAL, False)


# Unsaved work


def test_unsaved_ai_dots_never_count():
    add_video(counts={15: 3})
    add_box(15.0)
    add_box(15.0)
    data = opened()
    client.get(f"/api/snapshot-frames/{data['frames'][0]['id']}")
    add_school(99, saved=0)
    s = summary()
    assert s["snapshots"]["mean_count"] is None
    assert s["snapshots"]["largest_count"] is None
    assert s["snapshots"]["frames_checked"] == 0
    assert s["snapshot_frames"] == []
    with db.session() as con:
        assert con.execute("SELECT COUNT(*) AS n FROM school_dots").fetchone()["n"] == 0


def test_only_dots_sent_by_the_person_reach_the_total():
    add_video()
    add_box(15.0)
    add_box(15.0)
    frame = opened()["frames"][0]
    save(frame, 0)
    s = summary()
    assert s["snapshots"]["mean_count"] == 0
    assert (s["snapshot_frames"][0]["proposed"], s["snapshot_frames"][0]["removed"]) == (2, 2)


# Summary and export


def test_snapshots_stay_out_of_the_school_table():
    add_video()
    add_school(5)
    save(opened()["frames"][0], 3)
    s = summary()
    assert [r["total"] for r in s["schools"]] == [5]


def test_csv_agrees_with_the_summary():
    add_video(counts={50: 9})
    data = opened()
    a, b, c, d = of_kind(data, "snapshot")
    save(a, 1)
    save(b, 2)
    save(c, status="could_not_see")
    rows, facts = export()
    assert facts["mean_count"] == "1.50"
    assert facts["snapshot_frames_checked"] == "2"
    assert facts["snapshot_frames_total"] == "4"
    assert facts["snapshot_frames_could_not_see"] == "1"
    assert facts["largest_count_in_checked_frames"] == "2"
    assert "maxn" not in facts
    start = rows.index(["snapshot_time_s", "kind", "status", "total", "ai_proposed", "removed", "added"])
    assert rows[start + 1:] == [
        ["15.0", "snapshot", "checked", "1", "0", "0", "1"],
        ["45.0", "snapshot", "checked", "2", "0", "0", "2"],
        ["75.0", "snapshot", "could_not_see", "", "0", "0", "0"],
    ]
    save(d, 0)
    assert export()[1]["maxn"] == "2"


def test_csv_leaves_numbers_blank_before_anything_is_checked():
    add_video()
    facts = export()[1]
    assert facts["mean_count"] == ""
    assert facts["largest_count_in_checked_frames"] == ""


# Saving


def test_each_save_is_logged_for_the_timed_trial():
    add_video()
    frame = opened()["frames"][0]
    client.put(f"/api/snapshot-frames/{frame['id']}", json={"status": "checked", "dots": [], "ai_hidden": True})
    with db.session() as con:
        row = con.execute("SELECT type, payload FROM events WHERE type = 'snapshot_save'").fetchone()
    payload = json.loads(row["payload"])
    assert (payload["count"], payload["status"], payload["total"], payload["ai_hidden"]) == (frame["id"], "checked", 0, True)


def test_unknown_status_is_refused():
    add_video()
    frame = opened()["frames"][0]
    assert client.put(f"/api/snapshot-frames/{frame['id']}", json={"status": "", "dots": []}).status_code == 400


def test_a_school_count_is_not_a_snapshot_frame():
    add_video()
    add_school(5)
    with db.session() as con:
        school = con.execute("SELECT id FROM school_counts").fetchone()["id"]
    assert client.get(f"/api/snapshot-frames/{school}").status_code == 404
    assert client.put(f"/api/snapshot-frames/{school}", json={"status": "checked", "dots": []}).status_code == 404


# Frame images


def test_image_is_extracted_once_then_cached(monkeypatch):
    add_video()
    calls = []

    def fake(path, t, dst):
        calls.append(t)
        dst.write_bytes(b"jpeg")

    monkeypatch.setattr(video, "extract_frame", fake)
    frame = opened()["frames"][0]
    first = client.get(f"/api/snapshot-frames/{frame['id']}/image")
    second = client.get(f"/api/snapshot-frames/{frame['id']}/image")
    assert (first.status_code, second.status_code, first.content) == (200, 200, b"jpeg")
    assert calls == [15.0]


@pytest.mark.parametrize("failure", [subprocess.CalledProcessError(1, "ffmpeg"), None])
def test_unreadable_frame_is_a_clear_error_and_leaves_no_file(monkeypatch, failure):
    add_video(video_id="broken" if failure else "empty")
    video_id = "broken" if failure else "empty"

    def fake(path, t, dst):
        if failure:
            raise failure

    monkeypatch.setattr(video, "extract_frame", fake)
    frame = opened(video_id)["frames"][0]
    assert client.get(f"/api/snapshot-frames/{frame['id']}/image").status_code == 409
    assert not list(config.FRAMES.glob(f"snapshot-{video_id}-*"))


# Blind frames and AI accuracy

def save_blind(frame, dots, status="checked"):
    body = {"status": status, "dots": [{"x": x, "y": y, "source": "user"} for x, y in dots], "blind": True}
    assert client.put(f"/api/snapshot-frames/{frame['id']}", json=body).status_code == 200


def test_a_blind_request_never_gets_ai_dots():
    add_video()
    add_box(15)
    frame = of_kind(opened(), "snapshot")[0]

    assert len(client.get(f"/api/snapshot-frames/{frame['id']}").json()["dots"]) == 1
    assert client.get(f"/api/snapshot-frames/{frame['id']}?blind=true").json()["dots"] == []


def test_accuracy_counts_fish_found_missed_and_extra_boxes_on_blind_frames_only():
    add_video()
    add_box(15, x=0.1, y=0.2, w=0.2, h=0.4)  # a box around (0.2, 0.4)
    add_box(15, x=0.7, y=0.7, w=0.1, h=0.1, decision="Rejected")  # a box with no fish in it, still scored
    add_box(45)
    first, second = of_kind(opened(), "snapshot")[:2]
    save_blind(first, [(0.2, 0.4), (0.9, 0.1)])  # one fish inside the first box, one AI missed
    save(second, 1, source="ai")  # counted with AI dots showing, so left out

    row = client.get("/api/accuracy").json()["videos"][0]

    assert (row["frames_blind"], row["frames_assisted"]) == (1, 1)
    assert (row["fish"], row["found"], row["missed"], row["extra_boxes"]) == (2, 1, 1, 1)


def test_a_save_with_an_ai_dot_is_not_blind():
    add_video()
    add_box(15)
    frame = of_kind(opened(), "snapshot")[0]
    body = {"status": "checked", "dots": [{"x": 0.2, "y": 0.4, "source": "ai"}], "blind": True}
    client.put(f"/api/snapshot-frames/{frame['id']}", json=body)

    assert of_kind(opened(), "snapshot")[0]["blind"] == 0


def test_runs_of_one_video_share_blind_labels():
    add_video()
    add_video(video_id="v2")
    with db.session() as con:
        con.execute("UPDATE videos SET source_id = 'v1' WHERE id = 'v2'")
    add_box(15, video_id="v2")
    save_blind(of_kind(opened(), "snapshot")[0], [(0.2, 0.4)])

    rows = {r["id"]: r for r in client.get("/api/accuracy").json()["videos"]}

    assert (rows["v1"]["fish"], rows["v1"]["found"]) == (1, 0)  # v1 has no box there
    assert (rows["v2"]["fish"], rows["v2"]["found"]) == (1, 1)


def test_label_file_is_in_the_benchmark_form():
    add_video()
    first, second, third = of_kind(opened(), "snapshot")[:3]
    save_blind(first, [(0.25, 0.5)])
    save_blind(second, [], status="could_not_see")
    save(third, 1)  # not blind, so not exported

    res = client.get("/api/videos/v1/labels.json")

    assert res.json() == {
        "00015.00.jpg": {"status": "labelled", "points": [[0.25, 0.5]]},
        "00045.00.jpg": {"status": "could_not_see", "points": []},
    }
    assert "clip-labels.json" in res.headers["content-disposition"]


def test_a_frame_that_showed_ai_dots_can_never_be_blind():
    add_video()
    first, second = of_kind(opened(), "snapshot")[:2]
    client.get(f"/api/snapshot-frames/{first['id']}")  # AI's answer was on screen, even though it was no dots
    client.get(f"/api/snapshot-frames/{second['id']}?blind=true")
    save_blind(first, [(0.2, 0.4)])
    save_blind(second, [(0.2, 0.4)])

    first, second = of_kind(opened(), "snapshot")[:2]

    assert (first["blind"], first["ai_shown"]) == (0, 1)
    assert (second["blind"], second["ai_shown"]) == (1, 0)


def test_a_blind_frame_stays_blind_when_saved_again_from_the_ai_view():
    add_video()
    add_box(15)
    frame = of_kind(opened(), "snapshot")[0]
    save_blind(frame, [(0.9, 0.9)])
    shown = client.get(f"/api/snapshot-frames/{frame['id']}").json()  # a saved frame shows the person's dots, not AI's
    save(frame, 1)

    assert [d["source"] for d in shown["dots"]] == ["user"]
    assert of_kind(opened(), "snapshot")[0]["blind"] == 1


def test_count_order_is_the_benchmarks_and_puts_peaks_last():
    import random

    add_video(duration=305, counts={50: 4})
    data = opened()
    times = [f["t"] for f in of_kind(data, "snapshot")]
    names = [f"{t:08.2f}.jpg" for t in times]
    random.Random(42).shuffle(names)  # what ml/bench.py did with the same frames

    ranked = sorted(data["frames"], key=lambda f: f["rank"])

    assert [f"{f['t']:08.2f}.jpg" for f in ranked[:-1]] == names
    assert names != sorted(names)
    assert ranked[-1]["kind"] == "peak"
    assert [f["t"] for f in data["frames"]] == sorted(f["t"] for f in data["frames"])


def test_migration_marks_frames_counted_with_ai_dots_showing(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(db.SCHEMA)
    for name, kind in (("kind", "TEXT DEFAULT 'school'"), ("status", "TEXT DEFAULT ''"), ("blind", "INTEGER DEFAULT 0")):
        con.execute(f"ALTER TABLE school_counts ADD COLUMN {name} {kind}")
    con.executemany(
        "INSERT INTO school_counts (video_id, t, kind, status, saved, blind) VALUES ('old', ?, 'snapshot', ?, ?, ?)",
        [(15, "checked", 1, 0), (45, "checked", 1, 1), (75, "", 0, 0)],
    )
    con.commit()
    con.close()

    monkeypatch.setattr(db, "DB_PATH", path)
    db.init()
    db.init()
    with db.session() as con:
        assert [r["ai_shown"] for r in con.execute("SELECT ai_shown FROM school_counts ORDER BY t")] == [1, 0, 0]
