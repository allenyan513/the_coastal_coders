"""Tests for the student's training data. Run from tidecount/server: uv run pytest ../ml/test_adapt.py"""
import json

import numpy as np

import adapt


def test_frames_near_a_test_frame_are_never_used():
    for test_frame in (15.0, 45.0, 3585.0):  # where bench.py and the app's snapshot count take frames
        assert not adapt.usable(test_frame)
        assert not adapt.usable(test_frame + 4.0)
        assert not adapt.usable(test_frame - 4.0)
        assert adapt.usable(test_frame + 6.0)
    assert adapt.usable(30.0)


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


def test_blocks_take_turns_between_the_two_students():
    assert [adapt.fold_of(t) for t in (15.0, 105.0, 135.0, 225.0, 255.0)] == [0, 0, 1, 1, 0]


def test_counted_frames_reads_an_export_from_0_to_1(tmp_path):
    (tmp_path / "frames").mkdir()
    (tmp_path / "frames" / "_annotations.coco.json").write_text(json.dumps({
        "images": [
            {"id": 0, "file_name": "snapshot-00045.000.jpg", "width": 200, "height": 100, "t": 45.0, "kind": "snapshot", "blind": True},
            {"id": 1, "file_name": "snapshot-00015.000.jpg", "width": 200, "height": 100, "t": 15.0, "kind": "snapshot", "blind": False},
        ],
        "annotations": [{"id": 0, "image_id": 0, "category_id": 0, "bbox": [20, 20, 40, 40]}],
        "fish_without_box": [{"image_id": 0, "x": 180, "y": 90}],
    }))

    first, second = adapt.counted_frames(tmp_path)

    assert (first["t"], first["boxes"], first["points"]) == (15.0, [], [])
    assert second["boxes"] == [[0.1, 0.2, 0.3, 0.6]] and second["points"] == [[0.9, 0.9]]
    assert adapt.dots(second) == [[0.2, 0.4], [0.9, 0.9]]
    assert second["path"] == tmp_path / "frames" / "snapshot-00045.000.jpg"


def test_a_fish_without_a_box_takes_the_surest_teacher_box_around_it():
    frame = {"boxes": [[0.1, 0.1, 0.3, 0.3]], "points": [[0.7, 0.7]]}
    teacher = np.array([[0.6, 0.6, 0.8, 0.8], [0.5, 0.5, 0.9, 0.9], [0.0, 0.0, 0.2, 0.2]])

    boxes = adapt.corrected_boxes(frame, teacher, np.array([0.1, 0.4, 0.9]))

    assert boxes.tolist() == [[0.1, 0.1, 0.3, 0.3], [0.5, 0.5, 0.9, 0.9]]


def test_a_teacher_box_that_is_already_a_fish_is_not_used_twice():
    frame = {"boxes": [[0.1, 0.1, 0.5, 0.5]], "points": [[0.3, 0.3]]}  # a second fish inside a confirmed box
    teacher = np.array([[0.1, 0.1, 0.5, 0.5]])

    assert adapt.corrected_boxes(frame, teacher, np.array([0.9])) is None


def test_a_frame_with_a_fish_no_teacher_box_covers_is_left_out():
    frame = {"boxes": [], "points": [[0.7, 0.7]]}

    assert adapt.corrected_boxes(frame, np.zeros((0, 4)), np.zeros(0)) is None
    assert adapt.corrected_boxes({"boxes": [], "points": []}, np.zeros((0, 4)), np.zeros(0)).shape == (0, 4)
