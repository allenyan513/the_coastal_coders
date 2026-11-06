"""Experiment E7 in #49: teach a small detector one video, using a larger detector's boxes as labels.

The larger model is the teacher and the small one the student. Frames near every test frame are
left out of training, so test frames stay unseen by the student however many of them get labelled
later. A student is only worth keeping if it beats its starting model on those frames.

Run from tidecount/server, after `bench.py scan --setup medium` has saved the teacher's boxes:

    uv run python ../ml/adapt.py prepare --video holston-trout --run teacher
    uv run python ../ml/adapt.py prepare --video holston-trout --run teacher-steady --drop-flicker
    uv run python ../ml/adapt.py train --video holston-trout --run teacher --base cfd-small
    uv run python ../ml/adapt.py scan --video holston-trout --run teacher
    uv run python ../ml/adapt.py score

The second arm adds frames a person counted in the app, from `python -m tidecount.dataset`. A
counted frame replaces the teacher's answer for that frame: the boxes the person confirmed stay,
every other box goes, and a fish the person marked that had no box takes the teacher's box around
it, however unsure the teacher was. A frame with a fish no teacher box covers is left out, because
it would teach that fish as background.

The counted frames are also the only test frames such a video has. So the video is cut into
two-minute blocks, and the blocks take turns: student 0 learns from the counted frames in even
blocks and is scored on the odd ones, and student 1 the other way round. `--file` names a video
that isn't in bench_videos.csv, as it does in bench.py:

    uv run python ../ml/adapt.py prepare --file VIDEO --run teacher
    uv run python ../ml/adapt.py correct --file VIDEO --export ../data/exports/ID --fold 0
    uv run python ../ml/adapt.py train --file VIDEO --run corrected-0 --base cfd-nano --epochs 6
    uv run python ../ml/adapt.py scan --file VIDEO --run corrected-0 --base cfd-nano
    uv run python ../ml/adapt.py score --file VIDEO --export ../data/exports/ID
"""
import argparse
import json
import random
import shutil
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
BLOCK = 120.0  # seconds. Counted frames in one block train a student, and the next block's test it
REPEAT = 4  # times each counted frame appears in training, so a few dozen aren't lost among 500 teacher frames
SAME_FISH = 0.5  # two boxes that overlap this much are one fish


def video_named(name: str) -> bench.Video:
    return next(v for v in bench.manifest() if v.id == name)


def video_file(path: str) -> bench.Video:
    """A video that isn't in bench_videos.csv, named after its file as bench.py --file names it."""
    file = Path(path).expanduser().resolve()
    return bench.Video(file.stem, str(file), "file")


def folder(video: bench.Video, run: str) -> Path:
    return video.folder / "adapt" / run


def usable(seconds: float, every: float = bench.EVERY, guard: float = GUARD) -> bool:
    """False within the guard of a test frame, so nothing close to one is trained on.

    Test frames sit halfway through each `every` seconds: 15, 45, 75 and so on, as bench.py and the
    app's snapshot count take them.
    """
    gap = (seconds - every / 2) % every
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


def coco(images: list[dict], annotations: list[dict], description: str = "Teacher boxes, not checked by a person") -> dict:
    return {
        "info": {"description": description},
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


def counted_frames(export: Path) -> list[dict]:
    """The frames a person counted in the app, read from an export, in time order.

    `boxes` are the corners of the AI boxes the person confirmed and `points` the fish that had no
    box, both from 0 to 1.
    """
    data = json.loads((export / "frames" / "_annotations.coco.json").read_text())
    frames = {i["id"]: {**i, "path": export / "frames" / i["file_name"], "boxes": [], "points": []} for i in data["images"]}
    for a in data["annotations"]:
        f = frames[a["image_id"]]
        x, y, w, h = a["bbox"]
        f["boxes"].append([x / f["width"], y / f["height"], (x + w) / f["width"], (y + h) / f["height"]])
    for point in data["fish_without_box"]:
        f = frames[point["image_id"]]
        f["points"].append([point["x"] / f["width"], point["y"] / f["height"]])
    return sorted(frames.values(), key=lambda f: f["t"])


def fold_of(seconds: float, block: float = BLOCK) -> int:
    """Which student learns from a frame at this time: 0 for even blocks of the video, 1 for odd ones."""
    return int(seconds // block) % 2


def dots(frame: dict) -> list[list[float]]:
    """One dot for each fish the person counted: the middle of its box, or its point when it had none."""
    return [[(x1 + x2) / 2, (y1 + y2) / 2] for x1, y1, x2, y2 in frame["boxes"]] + frame["points"]


def corrected_boxes(frame: dict, teacher_boxes: np.ndarray, teacher_confidence: np.ndarray) -> np.ndarray | None:
    """The boxes a counted frame trains on, or None when one of its fish can't be given a box.

    Confirmed boxes stay. Each fish without one takes the surest teacher box around its point that
    isn't already a fish on this frame.
    """
    boxes = np.array(frame["boxes"], dtype=float).reshape(-1, 4)
    for x, y in frame["points"]:
        for i in np.argsort(-teacher_confidence):
            x1, y1, x2, y2 = teacher_boxes[i]
            taken = len(boxes) and (still.overlaps(teacher_boxes[i][None], boxes) >= SAME_FISH).any()
            if x1 <= x <= x2 and y1 <= y <= y2 and not taken:
                boxes = np.vstack([boxes, teacher_boxes[i]])
                break
        else:
            return None
    return boxes


def correct(video: bench.Video, export: Path, fold: int) -> None:
    """Build one student's training data: the teacher run's frames, with this fold's counted frames put in."""
    teacher = still.load(video, "medium")
    source = folder(video, "teacher") / "dataset"
    if not teacher or not (source / "train" / "_annotations.coco.json").exists():
        raise SystemExit(f"{video.id} has no teacher dataset. Run prepare --run teacher first")
    root = folder(video, f"corrected-{fold}") / "dataset"
    if root.exists():
        shutil.rmtree(root)
    (root / "train").mkdir(parents=True)
    for name in ("valid", "test"):
        (root / name).symlink_to(source / name, target_is_directory=True)

    fps = teacher["fps"]
    frames = [f for f in counted_frames(export) if fold_of(f["t"]) == fold]
    index_of = {id(f): min(len(teacher["boxes"]) - 1, round(f["t"] * fps)) for f in frames}
    images, annotations = [], []

    def add(file: str, width: int, height: int, boxes) -> None:
        images.append({"id": len(images), "file_name": file, "width": width, "height": height})
        for x1, y1, x2, y2 in boxes:
            w, h = (x2 - x1) * width, (y2 - y1) * height
            annotations.append({
                "id": len(annotations), "image_id": images[-1]["id"], "category_id": 0,
                "bbox": [x1 * width, y1 * height, w, h], "area": w * h, "iscrowd": 0,
            })

    # A counted frame replaces the teacher's answer for the same moment.
    base = json.loads((source / "train" / "_annotations.coco.json").read_text())
    theirs: dict[int, list] = {}
    for a in base["annotations"]:
        theirs.setdefault(a["image_id"], []).append(a["bbox"])
    for image in tqdm(base["images"], desc=f"teacher frames {video.id}"):
        if int(Path(image["file_name"]).stem) in index_of.values():
            continue
        (root / "train" / image["file_name"]).symlink_to(source / "train" / image["file_name"])
        w, h = image["width"], image["height"]
        add(image["file_name"], w, h, [(x / w, y / h, (x + bw) / w, (y + bh) / h) for x, y, bw, bh in theirs.get(image["id"], [])])
    notes = {"fold": fold, "export": str(export), "teacher_frames": len(images), "counted_frames": 0, "left_out": 0,
             "confirmed_boxes": 0, "fish_given_a_teacher_box": 0, "teacher_boxes_dropped": 0, "repeat": REPEAT}
    for f in tqdm(frames, desc=f"counted frames {video.id}"):
        index = index_of[id(f)]
        boxes = corrected_boxes(f, teacher["boxes"][index], teacher["confidence"][index])
        if boxes is None:
            notes["left_out"] += 1
            continue
        for copy in range(REPEAT):
            name = f"counted-{index:06d}-{copy}.jpg"
            (root / "train" / name).symlink_to(f["path"].resolve())
            add(name, f["width"], f["height"], boxes)
        sure = teacher["boxes"][index][teacher["confidence"][index] >= TEACHER_KEEP]
        kept = (still.overlaps(sure, boxes) >= SAME_FISH).any(axis=1) if len(sure) and len(boxes) else np.zeros(len(sure), dtype=bool)
        notes["counted_frames"] += 1
        notes["confirmed_boxes"] += len(f["boxes"])
        notes["fish_given_a_teacher_box"] += len(f["points"])
        notes["teacher_boxes_dropped"] += int((~kept).sum())
    description = "Teacher boxes, with the frames a person counted in the app put in"
    (root / "train" / "_annotations.coco.json").write_text(json.dumps(coco(images, annotations, description)))
    (root.parent / "corrected.json").write_text(json.dumps(notes, indent=1))
    print(json.dumps(notes, indent=1))


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


def tally(runs: dict[int, dict], frames: list[dict], threshold: float) -> dict:
    """Score a model on counted frames. `runs` maps a fold to the scan of the student that learned
    from it, and each scan is scored only on the other fold's frames. A model that learned from no
    counted frame has the same scan under both."""
    total = {"frames_with_fish": 0, "frames_kept": 0, "dots": 0, "claimed": 0, "labelled_boxes": 0, "queue": 0.0}
    for fold, run in runs.items():
        labels = [(f["t"], dots(f)) for f in frames if fold_of(f["t"]) != fold]
        m = still.measure(run, labels, threshold)
        for key in total:
            total[key] += m[key] / len(runs) if key == "queue" else m[key]
    return total


def score_corrected(video: bench.Video, export: Path, base: str) -> None:
    """Compare the starting model, the teacher, and students with and without a person's counted frames."""
    counted = counted_frames(export)
    # Peak frames were chosen by AI for having many boxes, so they can train a student but not test one.
    snapshots = [f for f in counted if f["kind"] == "snapshot"]
    sets = {
        "Every counted snapshot frame": snapshots,
        "Only the frames counted without seeing AI's dots": [f for f in snapshots if f["blind"]],
    }
    models: dict[str, dict[int, dict]] = {}
    for name, setup in ((f"start: {BASELINES[base]}", BASELINES[base]), ("teacher: medium", "medium")):
        run = still.load(video, setup)
        if run:
            models[name] = {0: run, 1: run}
    path = folder(video, "teacher") / f"student-{base}" / "scan.json"
    if path.exists():
        run = read_run(path)
        models["student, teacher boxes only"] = {0: run, 1: run}
    paths = {fold: folder(video, f"corrected-{fold}") / f"student-{base}" / "scan.json" for fold in (0, 1)}
    notes = [json.loads(p.parents[1].joinpath("corrected.json").read_text()) for p in paths.values() if p.exists()]
    if all(p.exists() for p in paths.values()):
        models["student, teacher boxes and counted frames"] = {fold: read_run(p) for fold, p in paths.items()}

    lines = [
        f"# Students with a person's counted frames: {video.id}",
        "",
        f"Counted frames come from {export}. The video is cut into blocks of {BLOCK:.0f} seconds. One student learns from",
        "the counted frames in even blocks and is scored on the odd ones, the other the other way round, and their",
        "scores are added. Every other model is scored on the same frames. No model was trained on a frame within",
        f"{GUARD:.0f} seconds of a frame it is scored on.",
        "",
        "Recall is the share of counted fish that got a box. Precision is the share of boxes on those frames that",
        "hold a counted fish. Queue is the share of the whole video the app's rule would send to review.",
        "Confidence isn't comparable between models, so compare the trade-off, not one threshold.",
        "",
        "## What the counted frames changed in training",
        "",
        "| Student learns from | Teacher frames | Counted frames used | Left out | Boxes the person confirmed | Fish given a teacher box | Teacher boxes dropped |",
        "|---|---|---|---|---|---|---|",
    ]
    for n in notes:
        lines.append(
            f"| {'even' if n['fold'] == 0 else 'odd'} blocks | {n['teacher_frames']} | {n['counted_frames']}, each {n['repeat']} times | {n['left_out']} "
            f"| {n['confirmed_boxes']} | {n['fish_given_a_teacher_box']} | {n['teacher_boxes_dropped']} |"
        )
    lines += [
        "",
        "A frame is left out when one of its fish has no teacher box around it. A teacher box is dropped when the",
        f"teacher was at least {TEACHER_KEEP} sure of it and the person didn't count a fish there.",
    ]
    for title, frames in sets.items():
        fish = sum(len(dots(f)) for f in frames)
        lines += [
            "",
            f"## {title}",
            "",
            f"{len(frames)} frames, {sum(1 for f in frames if dots(f))} with fish, {fish} fish.",
            "",
            "| Model | Threshold | Queue | Fish frames in queue | Recall | Precision |",
            "|---|---|---|---|---|---|",
        ]
        for name, runs in models.items():
            for t in tqdm(THRESHOLDS, desc=f"{name}, {len(frames)} frames", leave=False):
                m = tally(runs, frames, t)
                recall = f"{m['claimed']} of {m['dots']}, {m['claimed'] / m['dots']:.0%}" if m["dots"] else "n/a"
                precision = f"{m['claimed']} of {m['labelled_boxes']}, {m['claimed'] / m['labelled_boxes']:.0%}" if m["labelled_boxes"] else "n/a"
                lines.append(f"| {name} | {t:.1f} | {m['queue']:.0%} | {m['frames_kept']} of {m['frames_with_fish']} | {recall} | {precision} |")
    sheet = bench.BENCH / f"adapt-corrected-{video.id}.md"
    sheet.write_text("\n".join(lines) + "\n")
    print(sheet.read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["prepare", "correct", "train", "scan", "score"])
    parser.add_argument("--video")
    parser.add_argument("--file", help="a video file that isn't in bench_videos.csv")
    parser.add_argument("--export", help="a folder written by python -m tidecount.dataset, for correct and score")
    parser.add_argument("--fold", type=int, choices=[0, 1], default=0, help="which blocks' counted frames the student learns from")
    parser.add_argument("--run", default="teacher")
    parser.add_argument("--base", default="cfd-small", choices=list(BASELINES))
    parser.add_argument("--drop-flicker", action="store_true")
    parser.add_argument("--keep", type=float, default=TEACHER_KEEP)
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--batch", type=int, default=BATCH)
    args = parser.parse_args()
    if args.step == "score" and not args.export:
        return score()
    video = video_file(args.file) if args.file else video_named(args.video)
    if args.step == "score":
        score_corrected(video, Path(args.export), args.base)
    elif args.step == "correct":
        correct(video, Path(args.export), args.fold)
    elif args.step == "prepare":
        prepare(video, args.run, args.drop_flicker, args.keep)
    elif args.step == "train":
        train(video, args.run, args.base, args.epochs, args.batch)
    else:
        scan(video, args.run, args.base)


if __name__ == "__main__":
    main()
