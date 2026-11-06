"""Test two rules that stop false alarms from filling the review queue, without losing fish.

Still: rocks, weed and camera parts can get a box in the same place for minutes on end, and a
swimming fish doesn't. A box counts as still when most frames around it have a box in the same place.

Flicker: a false alarm often lasts one frame, and a real fish stays in view a little longer. A box
counts as flicker when too few of the frames right beside it have a box nearby.

Boxes caught by a rule can't put footage in the queue on their own. A resting fish looks still and a
fast one looks like flicker, so the sheet also shows how many labelled fish lose their box.

Uses the boxes saved by `bench.py scan`. Run from tidecount/server:

    uv run python ../ml/still.py
"""
import json
from pathlib import Path

import numpy as np
from tqdm.auto import tqdm

import bench

THRESHOLDS = [0.2, 0.3]
REACHES = [30, 60, 120]  # seconds looked at on each side
SHARES = [0.5, 0.7, 0.9]  # share of the frames around a box that must have a box in the same place
OVERLAP = 0.5
LOOK_EVERY = 2.0  # seconds between the frames looked at
FLICKER = [(1, 1), (2, 1), (2, 2), (4, 1), (4, 2), (4, 3)]  # frames looked at on each side, and how many need a box
NEARBY = 0.1  # how far a box's centre may move and still be the same thing, as a share of frame width and height
SHEET = bench.BENCH / "still-dev.md"


def overlaps(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Intersection over union of every box in `a` with every box in `b`."""
    left, top = np.maximum(a[:, None, 0], b[:, 0]), np.maximum(a[:, None, 1], b[:, 1])
    right, bottom = np.minimum(a[:, None, 2], b[:, 2]), np.minimum(a[:, None, 3], b[:, 3])
    shared = np.clip(right - left, 0, None) * np.clip(bottom - top, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return shared / np.maximum(area_a[:, None] + area_b - shared, 1e-9)


def still_mask(
    frames: list[np.ndarray], confidence: list[np.ndarray], threshold: float, fps: float, reach: float, share: float
) -> list[np.ndarray]:
    """For each box at or above the threshold, whether it's still. Boxes below it only count as support."""
    step, span = max(1, round(LOOK_EVERY * fps)), round(reach * fps)
    masks = []
    for index, (boxes, scores) in enumerate(zip(frames, confidence)):
        mask = np.zeros(len(boxes), dtype=bool)
        wanted = np.flatnonzero(scores >= threshold)
        around = [j for j in range(index - span, index + span + 1, step) if j != index and 0 <= j < len(frames)]
        if len(wanted) and around:
            hits = np.zeros(len(wanted))
            for j in around:
                if len(frames[j]):
                    hits += overlaps(boxes[wanted], frames[j]).max(axis=1) >= OVERLAP
            mask[wanted] = hits >= share * len(around)
        masks.append(mask)
    return masks


def flicker_mask(
    frames: list[np.ndarray], confidence: list[np.ndarray], threshold: float, side: int, need: int
) -> list[np.ndarray]:
    """For each box at or above the threshold, whether too few frames beside it have one nearby."""
    centres = [((b[:, :2] + b[:, 2:]) / 2)[c >= threshold] for b, c in zip(frames, confidence)]
    masks = []
    for index, scores in enumerate(confidence):
        mask = np.zeros(len(scores), dtype=bool)
        wanted = np.flatnonzero(scores >= threshold)
        if len(wanted):
            hits = np.zeros(len(wanted), dtype=int)
            for j in range(max(0, index - side), min(len(frames), index + side + 1)):
                if j != index and len(centres[j]):
                    apart = np.abs(centres[index][:, None] - centres[j]).max(axis=2)
                    hits += (apart <= NEARBY).any(axis=1)
            mask[wanted] = hits < need
        masks.append(mask)
    return masks


def load(video: bench.Video, setup: str) -> dict | None:
    if not video.scan(setup).exists():
        return None
    run = json.loads(video.scan(setup).read_text())
    if "boxes" not in run:
        return None
    run["boxes"] = [np.array(b, dtype=float).reshape(-1, 4) for b in run["boxes"]]
    run["confidence"] = [np.array(c, dtype=float) for c in run["confidence"]]
    return run


def label_frames(video: bench.Video) -> list[tuple[float, list]]:
    """Seconds and dots of each frame a person labelled, with or without fish."""
    if not video.labels.exists():
        return []
    labels = json.loads(video.labels.read_text())
    return [(float(Path(n).stem), a["points"]) for n, a in labels.items() if a.get("status") == "labelled"]


def measure(run: dict, labels: list, threshold: float, masks: list[np.ndarray] | None = None) -> dict:
    """Queue share and labelled fish kept, leaving out the boxes that `masks` marks."""
    fps = run["fps"]
    masks = masks or [np.zeros(len(b), dtype=bool) for b in run["boxes"]]
    moving = [c[~m] for c, m in zip(run["confidence"], masks)]
    keep = bench.queue_keep(moving, threshold, fps, run["duration"])

    frames_with_fish, kept, dots, claimed, labelled_boxes = 0, 0, 0, 0, 0
    for seconds, points in labels:
        index = min(len(run["boxes"]) - 1, int(seconds * fps))
        boxes = run["boxes"][index][(run["confidence"][index] >= threshold) & ~masks[index]]
        labelled_boxes += len(boxes)
        if points:
            frames_with_fish += 1
            kept += bool(keep[min(len(keep) - 1, int(seconds))])
            dots += len(points)
            claimed += bench.claimed(boxes.tolist(), points)
    boxes_above = sum(int((c >= threshold).sum()) for c in run["confidence"])
    return {
        "queue": float(keep.mean()),
        "seconds_kept": int(keep.sum()),
        "seconds": len(keep),
        "frames_with_fish": frames_with_fish,
        "frames_kept": kept,
        "dots": dots,
        "claimed": claimed,
        "labelled_boxes": labelled_boxes,
        "dropped_share": sum(int(m.sum()) for m in masks) / max(1, boxes_above),
    }


def add(rows: list[dict]) -> dict:
    keys = ("seconds_kept", "seconds", "frames_with_fish", "frames_kept", "dots", "claimed")
    total = {k: sum(r[k] for r in rows) for k in keys}
    total["queue"] = total["seconds_kept"] / max(1, total["seconds"])
    return total


def rules(run: dict, threshold: float):
    """Each rule's name and the boxes it marks."""
    boxes, confidence, fps = run["boxes"], run["confidence"], run["fps"]
    yield "none", None
    for reach in REACHES:
        for share in SHARES:
            yield f"still, {reach} s, {share:.0%}", still_mask(boxes, confidence, threshold, fps, reach, share)
    for side, need in FLICKER:
        yield f"flicker, {need} of {side * 2} beside it", flicker_mask(boxes, confidence, threshold, side, need)


def main() -> None:
    videos = [v for v in bench.manifest() if v.split == "dev"]
    lines = [
        "# Still and flicker boxes in the review queue: dev",
        "",
        "Every row applies the app's queue rule at 2 frames a second, after leaving out the boxes the rule marks.",
        "Fish counts come from labelled frames only, so they're thin.",
        "",
    ]
    for setup in tqdm(bench.SCAN_SETUPS, desc="setups"):
        runs = {v.id: (load(v, setup), label_frames(v)) for v in tqdm(videos, desc=f"load {setup}", leave=False)}
        runs = {k: r for k, r in runs.items() if r[0]}
        if not runs:
            continue
        lines += [
            f"## {setup}",
            "",
            "| Threshold | Rule | " + " | ".join(runs) + " | All videos | Fish frames in queue | Fish boxed |",
            "|---|---|" + "---|" * (len(runs) + 3),
        ]
        for threshold in THRESHOLDS:
            results: dict[str, list[dict]] = {}
            for run, labels in tqdm(runs.values(), desc=f"{setup} at {threshold}", leave=False):
                for name, masks in rules(run, threshold):
                    results.setdefault(name, []).append(measure(run, labels, threshold, masks))
            for name, rows in results.items():
                total = add(rows)
                cells = " | ".join(f"{r['queue']:.0%}" for r in rows)
                lines.append(
                    f"| {threshold:.2f} | {name} | {cells} | {total['queue']:.0%} "
                    f"| {total['frames_kept']} of {total['frames_with_fish']} | {total['claimed']} of {total['dots']} |"
                )
        lines.append("")
    SHEET.write_text("\n".join(lines))
    print(SHEET.read_text())


if __name__ == "__main__":
    main()
