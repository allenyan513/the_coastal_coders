from tidecount.settings import Still
from tidecount.tracking import is_static


def piece(track, start, x0, speed, frames=4, size=0.05, step=0.5):
    return [(track, start + i * step, x0 + speed * i * step, 0.5, size, size, 0.8) for i in range(frames)]


def test_flags_a_track_that_never_moves():
    assert is_static(piece(1, 0, 0.5, 0.0, frames=10), Still())
    assert not is_static(piece(1, 0, 0.1, 0.05, frames=10), Still())
    assert not is_static(piece(1, 0, 0.5, 0.0, frames=3), Still())
