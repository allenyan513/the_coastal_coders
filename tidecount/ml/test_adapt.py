"""Tests for the student's training data. Run from tidecount/server: uv run pytest ../ml/test_adapt.py"""
import adapt


def test_frames_near_a_test_frame_are_never_used():
    assert not adapt.usable(30.0)
    assert not adapt.usable(34.0)
    assert not adapt.usable(26.0)
    assert adapt.usable(36.0)
    assert adapt.usable(15.0)


def test_choose_keeps_clear_of_test_frames_and_splits_by_minute():
    fps = 2
    split = adapt.choose(fps * 3600, fps, samples=600)
    assert len(split["train"]) + len(split["valid"]) == 600
    for part in split.values():
        assert all(adapt.usable(i / fps) for i in part)
    assert all(int(i / fps / 60) % adapt.VALID_EVERY == adapt.VALID_EVERY - 1 for i in split["valid"])
    assert not set(split["train"]) & set(split["valid"])
    assert split == adapt.choose(fps * 3600, fps, samples=600)  # the same draw every time


def test_a_short_video_uses_what_it_has():
    split = adapt.choose(2 * 60, 2, samples=600)
    assert len(split["train"]) + len(split["valid"]) < 600
