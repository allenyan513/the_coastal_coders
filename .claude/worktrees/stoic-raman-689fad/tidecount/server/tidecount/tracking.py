"""Checks on finished tracks."""
from . import config

Row = tuple[int, float, float, float, float, float, float]  # track, t, x, y, w, h, confidence


def is_static(items: list[Row]) -> bool:
    """True for a long track that barely moves, like a bait bag or a post."""
    if items[-1][1] - items[0][1] < config.STATIC_MIN_S:
        return False
    x, y = zip(*[(r[2] + r[4] / 2, r[3] + r[5] / 2) for r in items])
    spread = max(max(x) - min(x), max(y) - min(y))
    return spread < config.STATIC_REACH * max(max(r[4], r[5]) for r in items)
