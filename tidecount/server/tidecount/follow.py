"""Follow one fish from a box a person drew, so a fish AI missed becomes a track like AI's own.

The detector looks at a small window around where the fish should be, frame by frame, forwards
and backwards from the person's box. A window shows the fish larger than the whole frame does, so
the detector can often see a fish it missed at full size.

Following stops early rather than risk ending on another fish or on the background: when no box
fits for a moment, when the box stops moving, when the scene cuts, or after FOLLOW_MAX_S. A short
track that is right is worth more than a long one that wanders.
"""
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

from . import config, tracking, video

Box = tuple[float, float, float, float]  # x, y, w, h in pixels of the original frame
Hit = tuple[float, Box, float]  # time, box, the detector's confidence


@dataclass
class Followed:
    hits: list[Hit]  # in time order, and never empty: the person's box is always one of them
    crop: np.ndarray | None = None  # the largest view of the fish, cut from the original frame
    crop_side: float = 0.0  # its shorter side in pixels, which decides whether it can be named
    snapped: bool = False  # True when the detector saw a fish inside the person's box
    stopped: dict = field(default_factory=dict)  # why following ended, by direction, for the log


def centre(box: Box) -> tuple[float, float]:
    return box[0] + box[2] / 2, box[1] + box[3] / 2


def overlap(a: Box, b: Box) -> float:
    """Shared area over total area, from 0 to 1."""
    wide = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    high = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    shared = max(0.0, wide) * max(0.0, high)
    return shared / (a[2] * a[3] + b[2] * b[3] - shared + 1e-9)


def pick(found: list[tuple[Box, float]], expected: Box) -> tuple[Box, float] | None:
    """The box that fits where the fish should be, or None when nothing fits well enough."""
    cx, cy = centre(expected)
    side = max(expected[2], expected[3])
    best, best_score = None, 0.0
    for box, conf in found:
        shared = overlap(box, expected)
        bx, by = centre(box)
        apart = float(np.hypot(bx - cx, by - cy)) / side
        ratio = (box[2] * box[3]) / (expected[2] * expected[3] + 1e-9)
        if not (shared >= config.FOLLOW_OVERLAP or apart <= config.FOLLOW_NEARBY):
            continue
        if not 1 / config.FOLLOW_RESIZE <= ratio <= config.FOLLOW_RESIZE:
            continue
        score = 1 + shared - apart + 0.2 * conf
        if score > best_score:
            best, best_score = (box, conf), score
    return best


def snap(found: list[tuple[Box, float]], drawn: Box) -> tuple[Box, float] | None:
    """The detector's box for the fish a person boxed. A hand-drawn box is loose, so this is too."""
    inside = [
        (box, conf) for box, conf in found
        if drawn[0] <= centre(box)[0] <= drawn[0] + drawn[2] and drawn[1] <= centre(box)[1] <= drawn[1] + drawn[3]
        and 0.1 <= (box[2] * box[3]) / (drawn[2] * drawn[3] + 1e-9) <= 2
    ]
    return max(inside, key=lambda item: overlap(item[0], drawn), default=None)


def is_still(hits: list[Hit]) -> bool:
    """True when the latest FOLLOW_STILL_S of hits barely moved. `hits` is in the order followed."""
    recent = [h for h in hits if abs(h[0] - hits[-1][0]) <= config.FOLLOW_STILL_S]
    if abs(recent[0][0] - recent[-1][0]) < 0.8 * config.FOLLOW_STILL_S or len(recent) < 0.5 * config.FOLLOW_STILL_S * config.FOLLOW_FPS:
        return False
    xs, ys = zip(*[centre(h[1]) for h in recent])
    spread = max(max(xs) - min(xs), max(ys) - min(ys))
    return spread < config.FOLLOW_STILL_REACH * max(max(h[1][2], h[1][3]) for h in recent)


def look(detector, frame: np.ndarray, expected: Box) -> list[tuple[Box, float]]:
    """Every box the detector finds in a window around `expected`, in whole-frame pixels."""
    height, width = frame.shape[:2]
    cx, cy = centre(expected)
    side = int(min(max(config.FOLLOW_ZOOM * max(expected[2], expected[3]), config.FOLLOW_MIN_WINDOW), width, height))
    x0 = int(min(max(cx - side / 2, 0), width - side))
    y0 = int(min(max(cy - side / 2, 0), height - side))
    window = np.ascontiguousarray(frame[y0:y0 + side, x0:x0 + side, ::-1])
    boxes, conf = detector.detect(Image.fromarray(window), config.FOLLOW_THRESHOLD)
    return [((x0 + x1, y0 + y1, x2 - x1, y2 - y1), float(c)) for (x1, y1, x2, y2), c in zip(np.asarray(boxes).tolist(), np.asarray(conf).tolist())]


def thumb(frame: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(cv2.resize(frame, (64, 36), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(float)


def one_way(detector, path: str, width: int, height: int, duration: float, t0: float, start: Box, last: np.ndarray, forward: bool):
    """Follow from the person's box in one direction. Returns the hits in the order followed, the
    largest crop seen, and why it stopped."""
    fps = config.FOLLOW_FPS
    hits: list[Hit] = []
    best: tuple[float, np.ndarray | None, float] = (0.0, None, 0.0)
    box, speed, misses = start, np.zeros(2), 0
    cursor = t0
    while True:
        if forward:
            begin = cursor
            if begin >= duration or begin - t0 >= config.FOLLOW_MAX_S:
                return hits, best, "video end" if begin >= duration else "time limit"
            frames = [f for f in video.decode_span(path, begin, min(config.FOLLOW_CHUNK_S, duration - begin), width, height, fps) if f[0] > t0 + 1e-6]
            cursor = begin + config.FOLLOW_CHUNK_S
        else:
            begin = max(0.0, cursor - config.FOLLOW_CHUNK_S)
            if cursor <= 0 or t0 - cursor >= config.FOLLOW_MAX_S:
                return hits, best, "video start" if cursor <= 0 else "time limit"
            frames = [f for f in video.decode_span(path, begin, cursor - begin, width, height, fps) if f[0] < t0 - 1e-6][::-1]
            cursor = begin
        for t, frame in frames:
            small = thumb(frame)
            cut = float(np.abs(small - last).mean()) / (float(small.mean() + last.mean()) / 2 + 10) > config.FOLLOW_CUT
            last = small
            if cut:
                return hits, best, "scene cut"
            expected = (box[0] + speed[0], box[1] + speed[1], box[2], box[3])
            found = pick(look(detector, frame, expected), expected)
            if found is None:
                misses += 1
                box, speed = expected, speed * 0.8
                cx, cy = centre(box)
                if misses > config.FOLLOW_LOST_S * fps:
                    return hits, best, "lost"
                if not (0 <= cx <= width and 0 <= cy <= height):
                    return hits, best, "left the frame"
                continue
            new, conf = found
            moved = (np.array(centre(new)) - np.array(centre(box))) / (misses + 1)
            speed = 0.5 * speed + 0.5 * moved
            box, misses = new, 0
            hits.append((t, new, conf))
            if new[2] * new[3] > best[0]:
                crop = tracking.crop_for(frame, (new[0], new[1], new[0] + new[2], new[1] + new[3]), 1.0)
                if crop.size:
                    best = (new[2] * new[3], crop.copy(), min(new[2], new[3]))
            if is_still(hits):
                # A fish that swam and then stopped has most likely been lost to a mark behind it, so
                # the still stretch goes. One that was still from the person's box on is kept: the
                # person said a fish is there, and a resting fish is still a fish.
                moved = [h for h in hits if abs(h[0] - hits[-1][0]) > config.FOLLOW_STILL_S]
                return moved or hits, best, "stopped moving"


def follow(detector, path: str, width: int, height: int, duration: float, t0: float, drawn: Box) -> Followed:
    """`drawn` is the person's box at time `t0`. The detector's own box replaces it when it sees the fish."""
    t0 = max(0.0, min(t0, duration - 0.5))
    # Half a second, since asking ffmpeg for a single frame's worth can come back empty.
    frames = video.decode_span(path, t0, 0.5, width, height, config.FOLLOW_FPS)
    if not frames:
        return Followed(hits=[(t0, drawn, 0.0)])
    frame = frames[0][1]
    seen = snap(look(detector, frame, drawn), drawn)
    start, conf = seen if seen else (drawn, 0.0)
    crop = tracking.crop_for(frame, (start[0], start[1], start[0] + start[2], start[1] + start[3]), 1.0)
    best = (start[2] * start[3], crop.copy() if crop.size else None, min(start[2], start[3]))
    out = Followed(hits=[(t0, start, conf)], snapped=bool(seen))
    for forward in (False, True):
        hits, found, why = one_way(detector, path, width, height, duration, t0, start, thumb(frame), forward)
        out.stopped["after" if forward else "before"] = why
        out.hits = out.hits + hits if forward else hits[::-1] + out.hits
        if hits and found[1] is not None and found[0] > best[0] and any(found[0] == h[1][2] * h[1][3] for h in hits):
            best = found
    out.crop, out.crop_side = best[1], best[2]
    return out
