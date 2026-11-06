"""Experiment E7 in #49: teach a small detector one video, using a larger detector's boxes as labels.

The larger model is the teacher and the small one the student. No person corrects anything here.
Frames near every test frame are left out of training, so test frames stay unseen by the student
however many of them get labelled later. A student is only worth keeping if it beats its starting
model on those frames.

Run from tidecount/server, after `bench.py scan --setup medium` has saved the teacher's boxes:

    uv run python ../ml/adapt.py prepare --video holston-trout --run teacher
    uv run python ../ml/adapt.py prepare --video holston-trout --run teacher-steady --drop-flicker
    uv run python ../ml/adapt.py train --video holston-trout --run teacher --base cfd-small
    uv run python ../ml/adapt.py scan --video holston-trout --run teacher
    uv run python ../ml/adapt.py score
"""
import argparse
import json
import random
import time
from pathlib import Path

import numpy as np
from PIL import Image
from tqdm.auto import tqdm

import bench
import still

SAMPLES = 600  # frames drawn from the video
GUARD = 5.0  # seconds kept clear around every test frame
VALID_EVERY = 6  # each sixth minute of footage checks training, and the rest trains
TEACHER_KEEP = 0.5  # teacher boxes under this count as background
FLICKER_SIDE, FLICKER_NEED = 4, 2  # a teacher box needs 2 of the 8 frames beside it to have one nearby
EPOCHS = 12
BATCH = 4
LR = 5e-5
THRESHOLDS = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
SHEET = bench.BENCH / "adapt-dev.md"
BASELINES = {"cfd-nano": "app-today", "cfd-small": "small", "cfd-medium": "medium"}


def video_named(name: str) -> bench.Video:
    return next(v for v in bench.manifest() if v.id == name)


def folder(video: bench.Video, run: str) -> Path:
    return video.folder / "adapt" / run


def usable(seconds: float, every: float = bench.EVERY, guard: float = GUARD) -> bool:
    """False within the guard of a test frame, so nothing close to one is trained on."""
    gap = seconds % every
    return min(gap, every - gap) > guard


def choose(frames: int, fps: float, samples: int = SAMPLES, seed: int = bench.SEED) -> dict[str, list[int]]:
    """Pick frames across the video, and give whole minutes to validation."""
    open_frames = [i for i in range(frames) if usable(i / fps)]
    picked = sorted(random.Random(seed).sample(open_frames, min(samples, len(open_frames))))
    split = {"train": [], "valid": []}
    for index in picked:
        minute = int(index / fps / 60)
        split["valid" if minute % VALID_EVERY == VALID_EVERY - 1 else "train"].append(index)
    return split


def coco(images: list[dict], annotations: list[dict]) -> dict:
    return {
        "info": {"description": "Teacher boxes, not checked by a person"},
        "images": images,
        "annotations": annotations,
        "categories": [{"id": 0, "name": "fish", "supercategory": "none"}],
    }


def prepare(video: bench.Video, run: str, drop_flicker: bool, keep: float) -> None:
    from tidecount import settings
    from tidecount import video as ffmpeg

    teacher = still.load(video, "medium")
    if not teacher:
        raise SystemExit(f"{video.id} has no saved teacher boxes. Run bench.py scan --setup medium first")
    fps, count = teacher["fps"], len(teacher["boxes"])
    masks = (
        still.flicker_mask(teacher["boxes"], teacher["confidence"], keep, FLICKER_SIDE, FLICKER_NEED)
        if drop_flicker
        else [np.zeros(len(b), dtype=bool) for b in teacher["boxes"]]
    )
    split = choose(count, fps)
    where = {index: name for name, part in split.items() for index in part}
    root = folder(video, run) / "dataset"
    for name in split:
        (root / name).mkdir(parents=True, exist_ok=True)

    info = ffmpeg.probe(str(video.clip))
    width, height = info["width"], info["height"]
    images = {name: [] for name in split}
    annotations = {name: [] for name in split}
    boxes_used = 0
    decoded = ffmpeg.decode_frames(str(video.clip), width, height, settings.current().fps)
    for index, buffer in enumerate(tqdm(decoded, total=count, desc=f"prepare {video.id}")):
        name = where.get(index)
        if name is None:
            continue
        file = f"{index:06d}.jpg"
        picture = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 3)[:, :, ::-1]
        Image.fromarray(picture).save(root / name / file, quality=92)
        image_id = len(images[name])
        images[name].append({"id": image_id, "file_name": file, "width": width, "height": height})
        wanted = (teacher["confidence"][index] >= keep) & ~masks[index]
        for x1, y1, x2, y2 in teacher["boxes"][index][wanted]:
            w, h = (x2 - x1) * width, (y2 - y1) * height
            annotations[name].append({
                "id": len(annotations[name]), "image_id": image_id, "category_id": 0,
                "bbox": [x1 * width, y1 * height, w, h], "area": w * h, "iscrowd": 0,
            })
            boxes_used += 1
    for name in split:
        (root / name / "_annotations.coco.json").write_text(json.dumps(coco(images[name], annotations[name])))
    test = root / "test"
    test.mkdir(exist_ok=True)
    (test / "_annotations.coco.json").write_text(json.dumps(coco(images["valid"], annotations["valid"])))
    for item in images["valid"]:
        link = test / item["file_name"]
        if not link.exists():
            link.symlink_to(root / "valid" / item["file_name"])
    print(f"{video.id} {run}: {len(split['train'])} train, {len(split['valid'])} valid, {boxes_used} teacher boxes")


def train(video: bench.Video, run: str, base: str, epochs: int, batch: int) -> None:
    from rfdetr import from_checkpoint

    from tidecount import models

    out = folder(video, run) / f"student-{base}"
    out.mkdir(parents=True, exist_ok=True)
    model = from_checkpoint(str(models.ensure_weights(base)), trust_checkpoint=False, device=models.device())
    started = time.time()
    model.train(
        dataset_dir=str(folder(video, run) / "dataset"),
        output_dir=str(out),
        epochs=epochs,
        batch_size=batch,
        lr=LR,
        lr_encoder=LR,
        device=models.device(),
        num_workers=2,
        multi_scale=False,
        run_test=False,
        progress_bar="tqdm",
    )
    (out / "trained.json").write_text(json.dumps({
        "base": base, "epochs": epochs, "batch": batch, "minutes": (time.time() - started) / 60, "device": models.device(),
        "teacher_keep": TEACHER_KEEP,
    }))


def best_weights(out: Path) -> Path:
    for name in ("checkpoint_best_total.pth", "checkpoint_best_ema.pth", "checkpoint_best_regular.pth"):
        if (out / name).exists():
            return out / name
    raise SystemExit(f"No trained weights in {out}")


def scan(video: bench.Video, run: str, base: str) -> None:
    """Run a student over the whole clip, in the same form as bench.py scan."""
    from rfdetr import from_checkpoint

    from tidecount import models, settings
    from tidecount import video as ffmpeg

    out = folder(video, run) / f"student-{base}"
    path = out / "scan.json"
    if path.exists():
        return
    model = from_checkpoint(str(best_weights(out)), trust_checkpoint=False, device=models.device())
    info = ffmpeg.probe(str(video.clip))
    width, height = info["width"], info["height"]
    scale = np.array([width, height, width, height])
    confidence, found = [], []
    fps = settings.current().fps
    frames = ffmpeg.decode_frames(str(video.clip), width, height, fps)
    total = int(info["duration"] * fps)
    for buffer in tqdm(frames, total=total, desc=f"scan {run} {video.id}"):
        image = Image.fromarray(np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 3)[:, :, ::-1])
        d = model.predict(image, threshold=bench.LOW)
        boxes = np.asarray(d.xyxy, dtype=float).reshape(-1, 4) if len(d) else np.zeros((0, 4))
        scores = np.asarray(d.confidence, dtype=float) if len(d) else np.zeros(0)
        confidence.append(np.round(scores, 3).tolist())
        found.append((boxes / scale).round(4).tolist())
    path.write_text(json.dumps({
        "setup": f"{run}-{base}", "fps": fps, "duration": info["duration"], "confidence": confidence, "boxes": found,
    }))


def read_run(path: Path) -> dict:
    run = json.loads(path.read_text())
    run["boxes"] = [np.array(b, dtype=float).reshape(-1, 4) for b in run["boxes"]]
    run["confidence"] = [np.array(c, dtype=float) for c in run["confidence"]]
    return run


def row(video: str, name: str, threshold: float, m: dict) -> str:
    recall = f"{m['claimed'] / m['dots']:.0%}" if m["dots"] else "n/a"
    precision = f"{m['claimed'] / m['labelled_boxes']:.0%}" if m["labelled_boxes"] else "n/a"
    frames = f"{m['frames_kept']} of {m['frames_with_fish']}"
    return f"| {video} | {name} | {threshold:.1f} | {m['queue']:.0%} | {frames} | {recall} | {precision} |"


def score() -> None:
    lines = [
        "# Per-video students: dev",
        "",
        "Students learned from teacher boxes alone, with no person correcting them. Each row is one threshold.",
        "Queue is the share of footage kept by the app's rule. The other columns use labelled frames only, so they're thin.",
        "Confidence isn't comparable between models, so compare the trade-off, not one threshold.",
        "",
        "| Video | Model | Threshold | Queue | Fish frames in queue | Recall | Precision |",
        "|---|---|---|---|---|---|---|",
    ]
    for video in [v for v in bench.manifest() if v.split == "dev"]:
        students = sorted((video.folder / "adapt").glob("*/student-*/scan.json"))
        if not students:
            continue
        labels = still.label_frames(video)
        for base in dict.fromkeys(p.parent.name.removeprefix("student-") for p in students):
            setup = BASELINES[base]
            if video.scan(setup).exists():
                run = still.load(video, setup)
                for t in tqdm(THRESHOLDS, desc=f"{video.id} {setup}", leave=False):
                    lines.append(row(video.id, f"start: {setup}", t, still.measure(run, labels, t)))
        for path in students:
            run = read_run(path)
            name = f"{path.parents[1].name}, {path.parent.name}"
            for t in tqdm(THRESHOLDS, desc=f"{video.id} {name}", leave=False):
                lines.append(row(video.id, name, t, still.measure(run, labels, t)))
    SHEET.write_text("\n".join(lines) + "\n")
    print(SHEET.read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["prepare", "train", "scan", "score"])
    parser.add_argument("--video")
    parser.add_argument("--run", default="teacher")
    parser.add_argument("--base", default="cfd-small", choices=list(BASELINES))
    parser.add_argument("--drop-flicker", action="store_true")
    parser.add_argument("--keep", type=float, default=TEACHER_KEEP)
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--batch", type=int, default=BATCH)
    args = parser.parse_args()
    if args.step == "score":
        return score()
    video = video_named(args.video)
    if args.step == "prepare":
        prepare(video, args.run, args.drop_flicker, args.keep)
    elif args.step == "train":
        train(video, args.run, args.base, args.epochs, args.batch)
    else:
        scan(video, args.run, args.base)


if __name__ == "__main__":
    main()
