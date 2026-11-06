import numpy as np

from tidecount.settings import Flicker, Still
from tidecount.tracking import flicker, is_static


def piece(track, start, x0, speed, frames=4, size=0.05, step=0.5):
    return [(track, start + i * step, x0 + speed * i * step, 0.5, size, size, 0.8) for i in range(frames)]


def test_flags_a_track_that_never_moves():
    assert is_static(piece(1, 0, 0.5, 0.0, frames=10), Still())
    assert not is_static(piece(1, 0, 0.1, 0.05, frames=10), Still())
    assert not is_static(piece(1, 0, 0.5, 0.0, frames=3), Still())


# Flicker: at 2 frames a second the default rule looks 4 frames each way and needs 2 of them.

NONE = np.zeros((0, 2))


def swim(index):
    return np.array([[0.3 + index * 0.01, 0.5]])


def test_a_one_frame_box_is_flicker_and_a_passing_fish_isnt():
    frames = [swim(i) for i in range(20)]
    frames[10] = np.concatenate([frames[10], [[0.8, 0.8]]])

    masks = flicker(frames, 2, Flicker())

    assert masks[10].tolist() == [False, True]
    assert not any(m.any() for i, m in enumerate(masks) if i != 10)


def test_a_fish_seen_on_three_frames_in_a_row_is_kept():
    frames = [NONE] * 6 + [swim(0), swim(1), swim(2)] + [NONE] * 6

    assert not any(m.any() for m in flicker(frames, 2, Flicker()))


def test_a_box_seen_twice_is_still_flicker_when_two_neighbours_are_needed():
    frames = [NONE] * 6 + [swim(0), swim(1)] + [NONE] * 6

    assert all(m.all() for m in flicker(frames, 2, Flicker()) if len(m))
    assert not any(m.any() for m in flicker(frames, 2, Flicker(need=1)))


def test_a_box_far_away_is_no_support():
    frames = [np.array([[0.2, 0.2]]), np.array([[0.8, 0.8]]), np.array([[0.2, 0.8]])]

    assert all(m.all() for m in flicker(frames, 2, Flicker()))


def test_need_zero_turns_the_rule_off():
    frames = [NONE, np.array([[0.5, 0.5]]), NONE]

    assert not any(m.any() for m in flicker(frames, 2, Flicker(need=0)))


def test_reach_is_in_seconds_whatever_the_frame_rate():
    frames = [NONE] * 20
    frames[2] = frames[10] = frames[18] = np.array([[0.5, 0.5]])  # 4 seconds apart at 2 frames a second

    assert flicker(frames, 2, Flicker(need=1))[10].all()
    assert not flicker(frames, 2, Flicker(need=1, reach_s=4.0))[10].any()
