"""Tests for the benchmark's geometry and scoring. Run from tidecount/server: uv run pytest ../ml"""
import json

import numpy as np
import pytest

import bench


def test_tiles_cover_the_frame_and_overlap():
    pieces = bench.tiles(1920, 1080, 1024)
    assert len(pieces) == 3  # 1080 is barely taller than a tile, so one row
    assert pieces[0][:2] == (0, 0) and pieces[-1][2:] == (1920, 1080)
    assert all(b[0] < a[2] for a, b in zip(pieces, pieces[1:]))  # neighbours share a strip

    assert len(bench.tiles(3840, 2160, 1024)) == 15
    assert bench.tiles(960, 540, 1024) == [(0, 0, 960, 540)]


def test_merge_drops_repeats_and_cut_boxes():
    boxes = np.array([
        [100, 100, 200, 200],  # a fish
        [105, 102, 205, 198],  # the same fish from another tile
        [100, 100, 150, 200],  # its half, cut by a tile edge
        [400, 400, 450, 450],  # another fish
    ], dtype=float)
    kept, confidence = bench.merge(boxes, np.array([0.9, 0.8, 0.7, 0.6]))
    assert kept.tolist() == [[100, 100, 200, 200], [400, 400, 450, 450]]
    assert confidence.tolist() == [0.9, 0.6]


def test_each_dot_is_claimed_once():
    two_boxes_one_fish = [[0.1, 0.1, 0.3, 0.3], [0.1, 0.1, 0.3, 0.3]]
    assert bench.claimed(two_boxes_one_fish, [[0.2, 0.2]]) == 1
    assert bench.claimed([[0.1, 0.1, 0.3, 0.3]], [[0.2, 0.2], [0.25, 0.25], [0.9, 0.9]]) == 1


FOUND = {
    "a.jpg": {"boxes": [[0.1, 0.1, 0.3, 0.3], [0.6, 0.6, 0.8, 0.8]], "confidence": [0.9, 0.2]},
    "b.jpg": {"boxes": [[0.5, 0.5, 0.6, 0.6]], "confidence": [0.4]},
    "c.jpg": {"boxes": [], "confidence": []},
    "d.jpg": {"boxes": [[0.0, 0.0, 0.1, 0.1]], "confidence": [0.9]},
}
LABELS = {
    "a.jpg": {"status": "labelled", "points": [[0.2, 0.2], [0.7, 0.7]]},  # two fish
    "b.jpg": {"status": "labelled", "points": []},  # empty water with a false box
    "c.jpg": {"status": "labelled", "points": [[0.5, 0.5]]},  # a fish nobody boxed
    "d.jpg": {"status": "unclear", "points": []},  # left out of every score
}


def test_metrics_at_two_thresholds():
    low = bench.metrics(bench.frame_rows(FOUND, LABELS, 0.1))
    assert low["frames"] == 3 and low["fish"] == 3
    assert low["recall"] == pytest.approx(2 / 3)
    assert low["precision"] == pytest.approx(2 / 3)
    assert low["fish_frames_flagged"] == 0.5
    assert low["empty_frames_flagged"] == 1.0
    assert low["count_error"] == pytest.approx(2 / 3)
    assert (low["maxn_ai"], low["maxn_person"]) == (2, 2)

    high = bench.metrics(bench.frame_rows(FOUND, LABELS, 0.5))
    assert high["recall"] == pytest.approx(1 / 3)
    assert high["empty_frames_flagged"] == 0.0
    assert high["count_error_by_density"] == {"no fish": 0.0, "1 to 5": 1.0}


def test_queue_threshold_keeps_fish_and_warns_when_it_cannot():
    by_threshold = {t: bench.frame_rows(FOUND, LABELS, t) for t in (0.1, 0.5, 0.95)}
    picked = bench.pick_thresholds(by_threshold, target=0.5)
    assert picked["queue"] == 0.5 and picked["queue_met_target"]
    assert picked["count"] == 0.5  # same error as 0.1, and the higher threshold wins a tie

    assert not bench.pick_thresholds(by_threshold, target=0.95)["queue_met_target"]


def test_queue_follows_the_app_rule():
    # 2 samples per second, 30 seconds. Boxes at seconds 2 and 4 join up, and second 20 stands alone.
    confidence = [[] for _ in range(60)]
    confidence[4], confidence[8], confidence[40] = [0.9], [0.4], [0.9]
    keep = bench.queue_keep(confidence, 0.3, 2, 30)
    assert np.flatnonzero(keep).tolist() == [1, 2, 3, 4, 5, 19, 20, 21, 22]

    assert not bench.queue_keep(confidence, 0.95, 2, 30).any()
    assert bench.queue_keep(confidence, 0.5, 2, 30).sum() == 8  # the two boxes no longer join up


def test_score_freezes_on_dev_and_reuses_on_locked(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "BENCH", tmp_path)
    monkeypatch.setattr(bench, "FROZEN", tmp_path / "frozen.json")
    monkeypatch.setattr(bench, "ROUNDS", 20)

    def make(video_id, split):
        video = bench.Video(video_id, "none", split)
        video.folder.mkdir()
        video.labels.write_text(json.dumps(LABELS))
        video.boxes("medium").write_text(json.dumps({"ms_per_frame": 100.0, "frames": FOUND}))
        return video

    locked = [make("test-video", "locked")]
    with pytest.raises(SystemExit):
        bench.score(locked, "locked", freeze=False)  # nothing chosen on dev yet

    sheet = bench.score([make("dev-video", "dev")], "dev", freeze=True)
    frozen = json.loads((tmp_path / "frozen.json").read_text())
    assert set(frozen["setups"]) == {"medium"}
    assert "| dev-video | medium | 3 | 3 |" in sheet.read_text()

    (tmp_path / "frozen.json").write_text(json.dumps({**frozen, "setups": {"medium": {"queue": 0.95, "queue_met_target": True, "count": 0.95}}}))
    text = bench.score(locked, "locked", freeze=False).read_text()
    assert "| medium | 100 | 0.95 | 0%" in text  # used the frozen thresholds, not its own best
