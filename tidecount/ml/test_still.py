"""Tests for still-box filtering. Run from tidecount/server: uv run pytest ../ml/test_still.py"""
import numpy as np

import still

FPS = 2
ROCK = np.array([[0.1, 0.1, 0.2, 0.2]])


def fish_at(index: int) -> np.ndarray:
    x = 0.3 + index * 0.01
    return np.array([[x, 0.5, x + 0.05, 0.55]])


def video(frames: int, rock_every: int = 1) -> tuple[list, list]:
    boxes, confidence = [], []
    for i in range(frames):
        rock = ROCK if i % rock_every == 0 else np.zeros((0, 4))
        boxes.append(np.concatenate([rock, fish_at(i)]))
        confidence.append(np.array([0.9] * len(rock) + [0.9]))
    return boxes, confidence


def test_overlaps():
    a = np.array([[0.0, 0.0, 1.0, 1.0]])
    b = np.array([[0.0, 0.0, 1.0, 1.0], [0.0, 0.0, 0.5, 1.0], [2.0, 2.0, 3.0, 3.0]])
    assert still.overlaps(a, b).round(2).tolist() == [[1.0, 0.5, 0.0]]


def test_a_rock_is_still_and_a_swimming_fish_isnt():
    boxes, confidence = video(80)
    masks = still.still_mask(boxes, confidence, 0.3, FPS, reach=10, share=0.7)
    assert all(m[0] and not m[1] for m in masks)


def test_a_flickering_rock_counts_when_it_mostly_stays():
    boxes, confidence = video(80, rock_every=2)
    masks = still.still_mask(boxes, confidence, 0.3, FPS, reach=10, share=0.4)
    assert masks[40][0] and not masks[40][1]


def test_weak_boxes_support_but_are_not_judged():
    boxes, confidence = video(80)
    for scores in confidence:
        scores[0] = 0.1  # the rock
    masks = still.still_mask(boxes, confidence, 0.3, FPS, reach=10, share=0.7)
    assert not any(m[0] for m in masks)  # below the threshold, so nothing to judge

    confidence[40][0] = 0.9
    assert still.still_mask(boxes, confidence, 0.3, FPS, reach=10, share=0.7)[40][0]


def test_measure_drops_a_rock_from_the_queue_and_keeps_fish():
    frames = 240
    boxes = [ROCK.copy() for _ in range(frames)]
    confidence = [np.array([0.9]) for _ in range(frames)]
    boxes[100] = np.concatenate([ROCK, fish_at(0)])
    confidence[100] = np.array([0.9, 0.9])
    run = {"fps": FPS, "duration": frames / FPS, "boxes": boxes, "confidence": confidence}
    labels = [(50.0, [[0.31, 0.52]])]

    plain = still.measure(run, labels, 0.3)
    assert plain["queue"] == 1.0 and plain["dropped_share"] == 0

    masks = still.still_mask(boxes, confidence, 0.3, FPS, 10, 0.7)
    filtered = still.measure(run, labels, 0.3, masks)
    assert filtered["queue"] < 0.1
    assert (filtered["frames_kept"], filtered["claimed"]) == (1, 1)


def test_a_one_frame_box_is_flicker_and_a_passing_fish_isnt():
    boxes = [fish_at(i) for i in range(20)]
    confidence = [np.array([0.9]) for _ in range(20)]
    boxes[10] = np.concatenate([boxes[10], np.array([[0.8, 0.8, 0.85, 0.85]])])
    confidence[10] = np.array([0.9, 0.9])
    masks = still.flicker_mask(boxes, confidence, 0.3, side=2, need=1)
    assert masks[10].tolist() == [False, True]
    assert not any(m.any() for i, m in enumerate(masks) if i != 10)


def test_weak_neighbours_dont_rescue_a_flicker():
    boxes = [ROCK.copy() for _ in range(5)]
    confidence = [np.array([0.1]) for _ in range(5)]
    confidence[2] = np.array([0.9])
    assert still.flicker_mask(boxes, confidence, 0.3, side=2, need=1)[2].tolist() == [True]
