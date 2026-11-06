"""Checks on finished tracks."""
from .settings import Still

Row = tuple[int, float, float, float, float, float, float]  # track, t, x, y, w, h, confidence


def crop_for(frame, box, scale: float, pad: float = 0.15):
    """Cut a box out of the original frame. `box` is xyxy on the detector's smaller picture."""
    x1, y1, x2, y2 = (float(v) * scale for v in box)
    pad_x, pad_y = (x2 - x1) * pad, (y2 - y1) * pad
    return frame[max(0, int(y1 - pad_y)):int(y2 + pad_y), max(0, int(x1 - pad_x)):int(x2 + pad_x)]


def is_static(items: list[Row], still: Still) -> bool:
    """True for a long track that barely moves, like a bait bag or a post."""
    if items[-1][1] - items[0][1] < still.min_seconds:
        return False
    x, y = zip(*[(r[2] + r[4] / 2, r[3] + r[5] / 2) for r in items])
    spread = max(max(x) - min(x), max(y) - min(y))
    return spread < still.reach * max(max(r[4], r[5]) for r in items)
