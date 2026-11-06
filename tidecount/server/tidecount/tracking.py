"""Checks on boxes and finished tracks."""
import numpy as np

from .settings import Flicker, Still

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


def flicker(frames: list[np.ndarray], fps: float, rule: Flicker) -> list[np.ndarray]:
    """For each box, True when too few of the frames beside it have a box nearby.

    A false alarm often lasts one frame, and a real fish stays in view a little longer. `frames`
    holds the box centres of each sampled frame, from 0 to 1. The same rule as `flicker_mask` in
    ml/still.py, which is where its values were measured.
    """
    side = max(1, round(rule.reach_s * fps))
    masks = []
    for index, centres in enumerate(frames):
        hits = np.zeros(len(centres), dtype=int)
        if len(centres):
            for j in range(max(0, index - side), min(len(frames), index + side + 1)):
                if j != index and len(frames[j]):
                    apart = np.abs(centres[:, None] - frames[j]).max(axis=2)
                    hits += (apart <= rule.nearby).any(axis=1)
        masks.append(hits < rule.need)
    return masks
