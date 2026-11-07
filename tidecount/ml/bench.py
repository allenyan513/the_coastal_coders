"""A benchmark for the fish detector: long videos nobody has labelled, dots from a person, one score sheet.

The dots come from the app. Add a video's `clip.mp4` there by its file path, wait for analysis, open
its snapshot count and choose "Count on my own". `pull` then copies those counts into `labels.json`.

Run it from `tidecount/server`, so it uses the app's own model code:

    uv run python ../ml/bench.py list
    uv run python ../ml/bench.py fetch --split dev     # download each video and cut its clip
    uv run python ../ml/bench.py frames --split dev    # save one frame every 30 seconds
    uv run python ../ml/bench.py pull --split dev      # copy the counts made in the app into labels.json
    uv run python ../ml/bench.py detect --split dev    # run every detector setup on those frames
    uv run python ../ml/bench.py score --split dev     # choose thresholds and write the score sheet
    uv run python ../ml/bench.py score --split locked  # the fair score, with those thresholds frozen

`scan` runs a setup over every sampled frame of each clip, the way the app does, so the score sheet
can show how much footage really lands in the review queue. It's slow, about 2 frames per video
second, so it covers `app-today` and `medium` unless you name others with `--setup`.

`run` does fetch, frames, detect and score in one go. `--file PATH` uses a video that isn't in
`bench_videos.csv`, such as footage from Coastal Action. Everything is saved under `data/bench`.

Two optional columns in `bench_videos.csv` handle 360° cameras. `height` asks for a sharper
download than 1080p. `flatten` turns the all-round picture into an ordinary one facing one way,
using ffmpeg's v360 options, such as `yaw=180:pitch=0:h_fov=100:v_fov=68:w=1280:h=720`.
"""
import argparse
import csv
import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from tqdm.auto import tqdm

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).with_name("bench_videos.csv")
BENCH = ROOT / "data" / "bench"
FROZEN = BENCH / "frozen.json"
sys.path.insert(0, str(ROOT / "server"))

EVERY = 30  # seconds between test frames, the spacing MeanCount was first tested with
LOW = 0.05  # keep every box above this once, and try higher thresholds without running the model again
THRESHOLDS = [round(0.05 * i, 2) for i in range(1, 20)]
TARGET = 0.95  # share of frames with a fish that the review queue must keep
OVERLAP = 0.2  # how far neighbouring tiles overlap, so a fish on a seam is whole in one of them
MAX_HEIGHT = 1080
SEED = 42
ROUNDS = 1000  # redrawn test sets per bootstrap
MIN_VIDEOS = 4  # fewer videos than this are too few to redraw, so we redraw frames and say so
SCAN_SETUPS = ["app-today", "medium"]
DENSITY = {"no fish": (0, 0), "1 to 5": (1, 5), "6 to 20": (6, 20), "over 20": (21, 10**9)}

# What we compare. `width` shrinks the frame first, as the app does today. `tile` cuts the frame
# into pieces of that size, so a small fish fills more of what the model sees.
SETUPS = {
    "app-today": {"detector": "cfd-nano", "width": 960, "tile": None},
    "small": {"detector": "cfd-small", "width": None, "tile": None},
    "medium": {"detector": "cfd-medium", "width": None, "tile": None},
    "nano-tiles": {"detector": "cfd-nano", "width": None, "tile": 640},
    "medium-tiles": {"detector": "cfd-medium", "width": None, "tile": 1024},
}


@dataclass
class Video:
    id: str
    ref: str  # a YouTube id, or a path to a file
    split: str
    condition: str = ""
    start: float = 0
    seconds: float = 0  # 0 means to the end
    note: str = ""
    height: int = 0  # the tallest download to accept. 0 means MAX_HEIGHT
    flatten: str = ""  # ffmpeg v360 options for a 360° picture. Empty for an ordinary camera

    @property
    def folder(self) -> Path:
        return BENCH / self.id

    @property
    def clip(self) -> Path:
        return self.folder / "clip.mp4"

    @property
    def labels(self) -> Path:
        return self.folder / "labels.json"

    def frames(self) -> list[Path]:
        return sorted((self.folder / "frames").glob("*.jpg"))

    def boxes(self, setup: str) -> Path:
        return self.folder / f"boxes-{setup}.json"

    def scan(self, setup: str) -> Path:
        return self.folder / f"scan-{setup}.json"


def manifest() -> list[Video]:
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        return [
            Video(r["id"], r["ref"], r["split"], r["condition"], float(r["start"] or 0), float(r["seconds"] or 0), r["note"],
                  int(r.get("height") or 0), r.get("flatten") or "")
            for r in csv.DictReader(f)
        ]


# Geometry and scoring. These use only numpy, so they can be tested without loading a model.


def tiles(width: int, height: int, size: int, overlap: float = OVERLAP) -> list[tuple[int, int, int, int]]:
    """Evenly spaced tiles that cover the frame. A side barely longer than `size` gets one tile."""

    def starts(length: int) -> tuple[list[int], int]:
        if length <= size * 1.1:
            return [0], length
        count = math.ceil((length - size) / (size * (1 - overlap))) + 1
        return [round(i * (length - size) / (count - 1)) for i in range(count)], size

    xs, w = starts(width)
    ys, h = starts(height)
    return [(x, y, x + w, y + h) for y in ys for x in xs]


def merge(boxes: np.ndarray, confidence: np.ndarray, iou: float = 0.5, inside: float = 0.7) -> tuple[np.ndarray, np.ndarray]:
    """Drop repeats of one fish found in several tiles, keeping the most confident box.

    A box also goes if most of it sits inside a kept one, which is how a fish cut by a tile edge
    shows up. That can hide a small fish in front of a large one.
    """
    order = np.argsort(-confidence)
    boxes, confidence = boxes[order], confidence[order]
    area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    keep: list[int] = []
    for i in range(len(boxes)):
        if keep:
            k = boxes[keep]
            w = np.clip(np.minimum(boxes[i, 2], k[:, 2]) - np.maximum(boxes[i, 0], k[:, 0]), 0, None)
            h = np.clip(np.minimum(boxes[i, 3], k[:, 3]) - np.maximum(boxes[i, 1], k[:, 1]), 0, None)
            shared = w * h
            union = area[i] + area[keep] - shared
            smaller = np.minimum(area[i], area[keep])
            if (shared / np.maximum(union, 1e-9) > iou).any() or (shared / np.maximum(smaller, 1e-9) > inside).any():
                continue
        keep.append(i)
    return boxes[keep], confidence[keep]


def claimed(boxes: list, dots: list) -> int:
    """Each box, best first, can claim one dot that sits inside it. A claimed dot is a fish found."""
    open_dots, found = list(dots), 0
    for x1, y1, x2, y2 in boxes:
        for dot in open_dots:
            if x1 <= dot[0] <= x2 and y1 <= dot[1] <= y2:
                open_dots.remove(dot)
                found += 1
                break
    return found


def frame_rows(found: dict, labels: dict, threshold: float) -> np.ndarray:
    """One row per labelled frame: fish found, boxes drawn, fish marked."""
    rows = []
    for name, answer in labels.items():
        if answer.get("status") != "labelled" or name not in found:
            continue
        result = found[name]
        boxes = [b for b, c in zip(result["boxes"], result["confidence"]) if c >= threshold]
        rows.append((claimed(boxes, answer["points"]), len(boxes), len(answer["points"])))
    return np.array(rows, dtype=float).reshape(-1, 3)


def metrics(rows: np.ndarray) -> dict:
    found, boxes, marked = rows.sum(0)
    has_fish, flagged = rows[:, 2] > 0, rows[:, 1] > 0
    gap = np.abs(rows[:, 1] - rows[:, 2])

    def share(mask):
        return float(flagged[mask].mean()) if mask.any() else float("nan")

    return {
        "frames": len(rows),
        "fish": int(marked),
        "recall": float(found / max(marked, 1)),
        "precision": float(found / max(boxes, 1)),
        "fish_frames_flagged": share(has_fish),
        "empty_frames_flagged": share(~has_fish),
        "frames_flagged": float(flagged.mean()),
        "count_error": float(gap.mean()),
        "count_error_by_density": {
            name: float(gap[(rows[:, 2] >= low) & (rows[:, 2] <= high)].mean())
            for name, (low, high) in DENSITY.items()
            if ((rows[:, 2] >= low) & (rows[:, 2] <= high)).any()
        },
        "mean_count_person": float(rows[:, 2].mean()),
        "mean_count_ai": float(rows[:, 1].mean()),
        "maxn_person": int(rows[:, 2].max()),
        "maxn_ai": int(rows[:, 1].max()),
    }


def pick_thresholds(by_threshold: dict[float, np.ndarray], target: float = TARGET) -> dict:
    """Two thresholds, because the queue and the count want different things.

    The queue must not lose fish, so it takes the highest threshold that still flags `target` of
    the frames with a fish. The count wants the number of boxes to match the number of fish.
    """
    scores = {t: metrics(rows) for t, rows in by_threshold.items()}
    enough = [t for t, m in scores.items() if m["fish_frames_flagged"] >= target]
    return {
        "queue": max(enough) if enough else min(scores),
        "queue_met_target": bool(enough),
        "count": min(scores, key=lambda t: (scores[t]["count_error"], -t)),
    }


def queue_keep(confidence: list[list[float]], threshold: float, fps: float, duration: float) -> np.ndarray:
    """Which seconds land in the review queue. The same rule as build_segments in the app's worker."""
    from tidecount import settings

    rules = settings.current().queue
    count = int(np.ceil(duration))
    active = np.zeros(count, dtype=bool)
    for index, scores in enumerate(confidence):
        if any(c >= threshold for c in scores):
            active[min(count - 1, int(index / fps))] = True
    spans: list[list[int]] = []
    for second in np.flatnonzero(active):
        if spans and second - spans[-1][1] <= rules.merge_gap_s:
            spans[-1][1] = int(second)
        else:
            spans.append([int(second), int(second)])
    keep = np.zeros(count, dtype=bool)
    for start, end in spans:
        start, end = max(0, start - 1), min(count, end + 2)
        if end - start < rules.min_segment_s:
            end = min(count, start + rules.min_segment_s)
        keep[start:end] = True
    return keep


def interval(parts: list[np.ndarray], key: str) -> tuple[float, float, str]:
    """The middle 95% of a score when the test set is redrawn. Redraws videos when there are enough."""
    rng = np.random.default_rng(SEED)
    by_video = len(parts) >= MIN_VIDEOS
    pooled = np.concatenate(parts)
    draws = []
    for _ in range(ROUNDS):
        if by_video:
            rows = np.concatenate([parts[i] for i in rng.integers(0, len(parts), len(parts))])
        else:
            rows = pooled[rng.integers(0, len(pooled), len(pooled))]
        draws.append(metrics(rows)[key])
    low, high = np.nanpercentile(draws, [2.5, 97.5])
    return float(low), float(high), "videos" if by_video else "frames"


# Steps that touch video and models. The app's code is imported inside them, since it loads torch.


def download(ref: str, height: int) -> Path:
    """Fetch a YouTube video once. Videos that share a source, such as two views of one 360° film, reuse it."""
    import yt_dlp

    folder = BENCH / "sources"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{ref}-{height}"
    done = [p for p in folder.glob(f"{stem}.*") if p.suffix != ".part"]
    if done:
        return done[0]
    bar = tqdm(unit="B", unit_scale=True, desc=f"download {ref}")

    def progress(update):
        if update["status"] == "downloading":
            bar.total = update.get("total_bytes") or update.get("total_bytes_estimate")
            bar.n = update["downloaded_bytes"]
            bar.refresh()

    # Up to 1080p, prefer H.264, which every tool reads quickly. Above that YouTube has no H.264.
    best = f"bv*[height<={height}]"
    options = {
        "format": f"{best}[vcodec^=avc1]/{best}[ext=mp4]/{best}" if height <= 1080 else best,
        "outtmpl": str(folder / f"{stem}.%(ext)s"),
        # YouTube slows a long single request to a crawl and then drops it. Asking for 10 MB at a
        # time avoids that, and a dropped piece is retried from where it stopped.
        "http_chunk_size": 10 * 1024 * 1024,
        "retries": 20,
        "socket_timeout": 30,
        "progress_hooks": [progress],
        "quiet": True,
        "noprogress": True,
    }
    with yt_dlp.YoutubeDL(options) as loader:
        loader.download([f"https://www.youtube.com/watch?v={ref}"])
    bar.close()
    return next(p for p in folder.glob(f"{stem}.*") if p.suffix != ".part")


def encode(ffmpeg: str, args: list[str], seconds: float, label: str) -> None:
    """Run an ffmpeg job that re-encodes, with a progress bar in seconds of video."""
    proc = subprocess.Popen(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-progress", "pipe:1", "-nostats", *args],
        stdout=subprocess.PIPE, text=True,
    )
    with tqdm(total=round(seconds), unit="s", desc=label) as bar:
        for line in proc.stdout:
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and value.lstrip("-").isdigit():
                bar.n = min(bar.total, max(0, int(value) // 1_000_000))
                bar.refresh()
    if proc.wait():
        raise RuntimeError(f"ffmpeg failed on {label}")


def fetch(video: Video) -> None:
    """Get the video, then cut the clip. An ordinary clip is copied as it is. A 360° one is flattened."""
    from tidecount import video as ffmpeg

    if video.clip.exists():
        return
    video.folder.mkdir(parents=True, exist_ok=True)
    source = Path(video.ref).expanduser()
    if not source.exists():
        source = download(video.ref, video.height or MAX_HEIGHT)
    length = ["-t", str(video.seconds)] if video.seconds else []
    cut = ["-ss", str(video.start), "-i", str(source), *length, "-an"]
    tmp = video.clip.with_suffix(".part.mp4")
    if video.flatten:
        seconds = video.seconds or ffmpeg.probe(str(source))["duration"] - video.start
        encode(
            ffmpeg.FFMPEG,
            [*cut, "-vf", f"v360=input=equirect:output=flat:{video.flatten}", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "18", "-pix_fmt", "yuv420p", str(tmp)],
            seconds, f"flatten {video.id}",
        )
    else:
        subprocess.run([ffmpeg.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *cut, "-c:v", "copy", str(tmp)], check=True)
    tmp.replace(video.clip)


def extract_frames(video: Video) -> None:
    """Evenly spaced frames at full size. Evenly spaced, not chosen by eye, so empty water is tested too."""
    from tidecount import video as ffmpeg

    folder = video.folder / "frames"
    folder.mkdir(exist_ok=True)
    duration = ffmpeg.probe(str(video.clip))["duration"]
    for second in tqdm(np.arange(EVERY / 2, duration - 0.5, EVERY), desc=f"frames {video.id}"):
        path = folder / f"{second:08.2f}.jpg"
        if not path.exists():
            subprocess.run(
                [ffmpeg.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{second:.3f}", "-i", str(video.clip),
                 "-frames:v", "1", "-q:v", "2", str(path)],
                check=True,
            )


def pull(video: Video) -> str:
    """Copy counts a person made on their own in the app into this video's labels.

    Only frames at the same times as `frames` here match by name, so label with the app's `[protocol]`
    set to this spacing. A frame that already has an answer keeps it, so labels made earlier are never replaced.
    """
    from tidecount import db, snapshots

    db.init()  # adds any column a newer app expects, as starting the app does
    clip = video.clip.resolve()
    with db.session() as con:
        runs = [
            r for r in db.rows(con.execute("SELECT id, name, path FROM videos WHERE status = 'Ready to review' ORDER BY created_at"))
            if Path(r["path"]).resolve() == clip or Path(r["name"]).stem == video.id
        ]
        answers = [snapshots.label_file(con, r["id"]) for r in runs]
    if not runs:
        return f"{video.id}: not in the app yet. Add {clip} there by its file path and let it finish analysing."
    labels = json.loads(video.labels.read_text()) if video.labels.exists() else {}
    known = {f.name for f in video.frames()}
    added = kept = strangers = 0
    for answer in answers:
        for name, a in answer.items():
            if name not in known:
                strangers += 1
            elif name in labels:
                kept += 1
            else:
                labels[name] = {"status": "labelled" if a["status"] == "labelled" else "unclear", "points": a["points"]}
                added += 1
    if added:
        tmp = video.labels.with_suffix(".part")
        tmp.write_text(json.dumps(labels, indent=1))
        tmp.replace(video.labels)
    note = f", {strangers} at times the benchmark has no frame for" if strangers else ""
    return f"{video.id}: {added} added, {kept} already had an answer{note}"


def detect_frame(detector, image, tile: int | None) -> tuple[np.ndarray, np.ndarray]:
    """Boxes in pixels for one frame. With tiles, the whole frame is also run, for fish larger than a tile."""
    boxes, confidence = detector.detect(image, LOW)
    if not tile:
        return boxes, confidence
    pieces = tiles(*image.size, tile)
    if len(pieces) == 1:
        return boxes, confidence
    all_boxes, all_confidence = [boxes.reshape(-1, 4)], [confidence]
    for x1, y1, x2, y2 in pieces:
        b, c = detector.detect(image.crop((x1, y1, x2, y2)), LOW)
        if len(b):
            all_boxes.append(b + np.array([x1, y1, x1, y1]))
            all_confidence.append(c)
    return merge(np.concatenate(all_boxes), np.concatenate(all_confidence))


def detect(video: Video, setup: str, cache: dict) -> None:
    """Run one setup on every test frame and save the boxes, with sizes from 0 to 1 like the labels."""
    from PIL import Image

    from tidecount import models

    path = video.boxes(setup)
    frames = video.frames()
    if path.exists() or not frames:
        return
    spec = SETUPS[setup]
    if spec["detector"] not in cache:
        cache.clear()  # one model in memory at a time
        cache[spec["detector"]] = models.load_detector(spec["detector"])
    detector = cache[spec["detector"]]
    found, took = {}, []
    for frame in tqdm(frames, desc=f"{setup} {video.id}"):
        started = time.time()
        image = Image.open(frame).convert("RGB")
        if spec["width"] and image.width > spec["width"]:
            height = int(round(spec["width"] * image.height / image.width / 2)) * 2  # the app's rounding
            image = image.resize((spec["width"], height))
        boxes, confidence = detect_frame(detector, image, spec["tile"])
        order = np.argsort(-confidence)
        scale = np.array([image.width, image.height, image.width, image.height])
        found[frame.name] = {
            "boxes": (boxes[order].reshape(-1, 4) / scale).round(5).tolist(),
            "confidence": confidence[order].round(4).tolist(),
        }
        took.append(time.time() - started)
    # The median, because the first frame also pays for warming the model up.
    result = {"setup": setup, **spec, "device": models.device(), "ms_per_frame": float(np.median(took)) * 1000, "frames": found}
    path.write_text(json.dumps(result))


def scan(video: Video, setup: str, cache: dict) -> None:
    """Run one setup over the whole clip at the app's frame rate and save every box and confidence."""
    from PIL import Image

    from tidecount import models, settings
    from tidecount import video as ffmpeg

    path = video.scan(setup)
    if not video.clip.exists() or (path.exists() and "boxes" in json.loads(path.read_text())):
        return
    spec = SETUPS[setup]
    if spec["detector"] not in cache:
        cache.clear()
        cache[spec["detector"]] = models.load_detector(spec["detector"])
    detector = cache[spec["detector"]]
    info = ffmpeg.probe(str(video.clip))
    width = spec["width"] or info["width"]
    height = int(round(width * info["height"] / info["width"] / 2)) * 2
    fps = settings.current().fps
    frames, confidence, found = ffmpeg.decode_frames(str(video.clip), width, height, fps), [], []
    scale = np.array([width, height, width, height])
    for buffer in tqdm(frames, total=int(info["duration"] * fps), desc=f"scan {setup} {video.id}"):
        image = Image.fromarray(np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 3)[:, :, ::-1])
        boxes, scores = detect_frame(detector, image, spec["tile"])
        confidence.append(np.round(scores, 3).tolist())
        found.append((boxes.reshape(-1, 4) / scale).round(4).tolist())
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps({"setup": setup, "fps": fps, "duration": info["duration"], "confidence": confidence, "boxes": found}))
    tmp.replace(path)


def queue_lines(videos: list[Video], chosen: dict) -> list[str]:
    """The review queue on whole videos, at the frozen threshold and at the app's current one."""
    from tidecount import settings

    current = settings.current()
    rows = []
    for setup, picked in chosen.items():
        for threshold in dict.fromkeys([picked["queue"], current.for_detector(SETUPS[setup]["detector"]).queue_threshold]):
            kept_s, total_s, fish_kept, fish_frames = 0, 0, 0, 0
            for v in videos:
                if not v.scan(setup).exists():
                    continue
                run = json.loads(v.scan(setup).read_text())
                keep = queue_keep(run["confidence"], threshold, run["fps"], run["duration"])
                labels = json.loads(v.labels.read_text()) if v.labels.exists() else {}
                seconds = [float(Path(n).stem) for n, a in labels.items() if a.get("status") == "labelled" and a["points"]]
                hits = sum(keep[min(len(keep) - 1, int(t))] for t in seconds)
                kept_s, total_s, fish_kept, fish_frames = kept_s + keep.sum(), total_s + len(keep), fish_kept + hits, fish_frames + len(seconds)
                rows.append(f"| {setup} | {threshold:.2f} | {v.id} | {pct(keep.mean())} | {hits} of {len(seconds)} |")
            if total_s:
                rows.append(f"| {setup} | {threshold:.2f} | **all** | **{pct(kept_s / total_s)}** | **{fish_kept} of {fish_frames}** |")
    if not rows:
        return []
    return [
        "",
        "## Review queue on whole videos",
        "",
        "These apply the app's own queue rule to every sampled frame, at the frozen threshold and at the app's current one.",
        f"The audit adds {current.queue.audit_share:.0%} of what's left out. Labelled fish frames are the frames where a person marked a fish.",
        "",
        "| Setup | Threshold | Video | Footage in queue | Labelled fish frames in queue |",
        "|---|---|---|---|---|",
        *rows,
    ]


def load_rows(videos: list[Video], setup: str) -> tuple[dict[str, dict[float, np.ndarray]], float]:
    """Rows for every video and threshold, and the setup's average speed."""
    out, speeds = {}, []
    for v in videos:
        if not (v.labels.exists() and v.boxes(setup).exists()):
            continue
        labels = json.loads(v.labels.read_text())
        result = json.loads(v.boxes(setup).read_text())
        by_threshold = {t: frame_rows(result["frames"], labels, t) for t in THRESHOLDS}
        if len(by_threshold[THRESHOLDS[0]]):
            out[v.id] = by_threshold
            speeds.append(result["ms_per_frame"])
    return out, float(np.mean(speeds)) if speeds else float("nan")


def pct(x: float) -> str:
    return "n/a" if x != x else f"{x:.0%}"


def score(videos: list[Video], split: str, freeze: bool) -> Path | None:
    """Write the score sheet. Thresholds are chosen on the dev split and reused everywhere else."""
    frozen = json.loads(FROZEN.read_text()) if FROZEN.exists() else {}
    if not any(load_rows(videos, setup)[0] for setup in SETUPS):
        print(f"Nothing to score in '{split}'. Count frames on your own in the app, run pull, then run detect.")
        return None
    if not freeze and not frozen:
        sys.exit("No frozen thresholds yet. Score the dev split first, so settings are never chosen on the test videos.")
    from tidecount import settings

    summary, by_video, density, chosen = [], [], [], {}
    for setup in SETUPS:
        rows, speed = load_rows(videos, setup)
        if not rows:
            continue
        pooled = {t: np.concatenate([r[t] for r in rows.values()]) for t in THRESHOLDS}
        picked = pick_thresholds(pooled) if freeze else frozen["setups"].get(setup)
        if picked is None:
            continue
        chosen[setup] = picked
        q, c = picked["queue"], picked["count"]
        queue, count = metrics(pooled[q]), metrics(pooled[c])
        with_fish = float((pooled[q][:, 2] > 0).mean())
        low, high, unit = interval([r[q] for r in rows.values()], "fish_frames_flagged")
        mean_gaps = [
            abs(m["mean_count_ai"] - m["mean_count_person"]) / m["mean_count_person"]
            for m in (metrics(r[c]) for r in rows.values()) if m["mean_count_person"] > 0
        ]
        summary.append(
            f"| {setup} | {speed:.0f} | {q:.2f}{'' if picked['queue_met_target'] else ' ⚠'} | {pct(queue['fish_frames_flagged'])} ({pct(low)} to {pct(high)}) "
            f"| {pct(queue['frames_flagged'])} | {pct(queue['empty_frames_flagged'])} | {c:.2f} | {count['count_error']:.2f} "
            f"| {pct(float(np.mean(mean_gaps))) if mean_gaps else 'n/a'} | {pct(count['recall'])} | {pct(count['precision'])} |"
        )
        density.append(f"| {setup} | " + " | ".join(
            f"{count['count_error_by_density'][name]:.2f}" if name in count["count_error_by_density"] else "n/a" for name in DENSITY
        ) + " |")
        for video_id, r in rows.items():
            mq, mc = metrics(r[q]), metrics(r[c])
            by_video.append(
                f"| {video_id} | {setup} | {mc['frames']} | {mc['fish']} | {pct(mq['fish_frames_flagged'])} | {pct(mq['frames_flagged'])} "
                f"| {mc['count_error']:.2f} | {mc['mean_count_ai']:.2f} / {mc['mean_count_person']:.2f} | {mc['maxn_ai']} / {mc['maxn_person']} |"
            )
    if not summary:
        sys.exit("The frozen thresholds cover none of the setups that ran here. Score the dev split again.")

    commit = subprocess.run(["git", "describe", "--always", "--dirty"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    if freeze:
        FROZEN.write_text(json.dumps({"chosen_on": split, "at": stamp, "commit": commit, "target": TARGET, "setups": chosen}, indent=1))
    source = "chosen on these videos, so these scores flatter the setups" if freeze else f"frozen on '{frozen['chosen_on']}' at {frozen['at']}"
    lines = [
        f"# Detector benchmark: {split}",
        "",
        f"{stamp}, commit `{commit}`, settings `{settings.current().hash()}`. Thresholds were {source}.",
        f"The interval redraws {unit}{'' if unit == 'videos' else ', because there are too few videos to redraw, so it is too narrow'}.",
        "",
        "## Summary",
        "",
        "- **Fish frames flagged:** of the frames where a person marked a fish, the share that got at least one box. This stands in for queue recall.",
        "- **All frames flagged:** the share of every frame that got a box. This stands in for footage to watch, before the app pads each segment.",
        f"  A person marked a fish in {pct(with_fish)} of these frames, so no setup can flag fewer than that without losing fish.",
        "- **Count error:** the average gap between the number of boxes and the number of fish marked, per frame.",
        f"- ⚠ means no threshold kept {TARGET:.0%} of fish frames, so the lowest was used.",
        "",
        "| Setup | ms per frame | Queue threshold | Fish frames flagged | All frames flagged | Empty frames flagged | Count threshold | Count error | MeanCount gap | Recall | Precision |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
        *summary,
        "",
        "## Count error by how many fish are in the frame",
        "",
        "| Setup | " + " | ".join(DENSITY) + " |",
        "|---|" + "---|" * len(DENSITY),
        *density,
        "",
        "## By video",
        "",
        "| Video | Setup | Frames | Fish | Fish frames flagged | All frames flagged | Count error | MeanCount, AI / person | MaxN, AI / person |",
        "|---|---|---|---|---|---|---|---|---|",
        *by_video,
        "",
        "MaxN here is the largest count among the test frames, not across the whole video.",
        *queue_lines(videos, chosen),
    ]
    path = BENCH / f"scores-{split}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nSaved to {path}")
    return path


def status(videos: list[Video]) -> None:
    print(f"{'id':26s}{'split':8s}{'condition':28s}{'clip':6s}{'frames':>7s}{'labelled':>10s}  setups run")
    for v in videos:
        labels = json.loads(v.labels.read_text()) if v.labels.exists() else {}
        done = sum(a.get("status") == "labelled" for a in labels.values())
        ran = ", ".join(s for s in SETUPS if v.boxes(s).exists())
        print(f"{v.id:26s}{v.split:8s}{v.condition:28s}{'yes' if v.clip.exists() else 'no':6s}{len(v.frames()):7d}{done:10d}  {ran}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["list", "fetch", "frames", "pull", "detect", "scan", "score", "run"])
    parser.add_argument("--split", default="dev", help="dev, locked, or all")
    parser.add_argument("--only", help="one video id from bench_videos.csv")
    parser.add_argument("--file", help="a video file that isn't in bench_videos.csv")
    parser.add_argument("--setup", action="append", choices=list(SETUPS), help="repeat to run several. Default: all")
    args = parser.parse_args()

    if args.file:
        path = Path(args.file).expanduser().resolve()
        videos, split = [Video(path.stem, str(path), "file")], path.stem
    else:
        videos = [v for v in manifest() if args.split in ("all", v.split) and args.only in (None, v.id)]
        split = args.only or args.split
    BENCH.mkdir(parents=True, exist_ok=True)

    if args.step == "list":
        return status(videos)
    if args.step in ("fetch", "run"):
        for v in videos:
            fetch(v)
    if args.step in ("frames", "run"):
        for v in videos:
            if v.clip.exists():
                extract_frames(v)
    if args.step == "pull":
        for v in videos:
            print(pull(v))
    if args.step in ("detect", "run"):
        cache: dict = {}
        for setup in args.setup or list(SETUPS):  # setup first, so each model loads once
            for v in videos:
                detect(v, setup, cache)
    if args.step == "scan":
        cache = {}
        for setup in args.setup or SCAN_SETUPS:
            for v in videos:
                scan(v, setup, cache)
    if args.step in ("score", "run"):
        # Only a whole dev split may choose thresholds. One video or a file always reuses them.
        score(videos, split, freeze=args.split == "dev" and not args.only and not args.file)


if __name__ == "__main__":
    main()
