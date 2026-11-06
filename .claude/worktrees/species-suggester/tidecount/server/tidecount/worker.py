"""Analyze one video: proxy, detection and tracking, species, then segments.

Run as `python -m tidecount.worker <video_id>`. It's a separate process so heavy work can't
freeze the API. A rerun replaces earlier results, and the proxy is reused if it exists.
"""
import hashlib
import random
import sys
import time

import cv2
import numpy as np
import supervision as sv
from PIL import Image
from trackers import ByteTrackTracker

from . import config, db, models, tracking, video


def update(video_id: str, **fields) -> None:
    keys = ", ".join(f"{k} = ?" for k in fields)
    with db.session() as con:
        con.execute(f"UPDATE videos SET {keys} WHERE id = ?", (*fields.values(), video_id))


def clear_results(video_id: str) -> None:
    with db.session() as con:
        ids = [r["id"] for r in con.execute("SELECT id FROM tracks WHERE video_id = ?", (video_id,))]
        for table in ("detections", "candidates", "decisions"):
            con.executemany(f"DELETE FROM {table} WHERE track_id = ?", [(i,) for i in ids])
        counts = [r["id"] for r in con.execute("SELECT id FROM school_counts WHERE video_id = ?", (video_id,))]
        con.executemany("DELETE FROM school_dots WHERE count_id = ?", [(i,) for i in counts])
        for table in ("tracks", "segments", "seconds", "school_counts", "events"):
            con.execute(f"DELETE FROM {table} WHERE video_id = ?", (video_id,))


def analyze_frames(video_id: str, v: dict, detector) -> tuple[dict, dict, list]:
    """One pass over the video. Returns per-second stats, the best crop per track, and detections."""
    width = config.DETECT_WIDTH
    height = int(round(width * v["height"] / v["width"] / 2)) * 2
    full_w, full_h = v["width"] // 2 * 2, v["height"] // 2 * 2
    scale = full_w / width
    tracker = ByteTrackTracker(
        frame_rate=config.DETECT_FPS,
        lost_track_buffer=60,
        track_activation_threshold=config.DETECT_THRESHOLD,
        high_conf_det_threshold=0.5,
        minimum_consecutive_frames=2,
    )
    stats: dict[int, dict] = {}
    best: dict[int, tuple] = {}
    rows: list[tuple] = []
    last_update = 0.0

    for idx, buf in enumerate(video.decode_frames(v["path"], full_w, full_h, config.DETECT_FPS)):
        t = idx / config.DETECT_FPS
        original = np.frombuffer(buf, dtype=np.uint8).reshape(full_h, full_w, 3)
        frame = cv2.resize(original, (width, height), interpolation=cv2.INTER_AREA)
        stat = stats.setdefault(int(t), {"detections": 0, "clarity": []})
        gray = cv2.cvtColor(cv2.resize(frame, (320, 180)), cv2.COLOR_BGR2GRAY)
        stat["clarity"].append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))

        image = Image.fromarray(frame[:, :, ::-1])
        boxes, conf = detector.detect(image, config.DETECT_THRESHOLD)
        stat["detections"] = max(stat["detections"], len(boxes))
        if len(boxes):
            found = sv.Detections(xyxy=boxes, confidence=conf, class_id=np.zeros(len(boxes), dtype=int))
        else:
            found = sv.Detections.empty()
        tracked = tracker.update(found)
        for i in range(len(tracked)):
            tid = int(tracked.tracker_id[i])
            if tid < 0:
                continue
            x1, y1, x2, y2 = tracked.xyxy[i]
            c = float(tracked.confidence[i]) if tracked.confidence is not None else 0.0
            rows.append((tid, t, x1 / width, y1 / height, (x2 - x1) / width, (y2 - y1) / height, c))
            # Keep the largest view of each fish, since size matters most for naming it.
            area = float((x2 - x1) * (y2 - y1))
            if tid not in best or area > best[tid][0]:
                crop = tracking.crop_for(original, (x1, y1, x2, y2), scale)
                if crop.size:
                    best[tid] = (area, crop.copy(), min(x2 - x1, y2 - y1) * scale)

        now = time.time()
        if now - last_update > 1:
            update(video_id, progress=min(0.99, t / max(v["duration"], 1)))
            last_update = now
    return stats, best, rows


def save_tracks(video_id: str, rows: list, best: dict) -> dict[int, int]:
    """Drop one-frame tracks, which are mostly noise, and save the rest."""
    grouped: dict[int, list] = {}
    for r in sorted(rows, key=lambda r: r[1]):
        grouped.setdefault(r[0], []).append(r)
    folder = config.CROPS / video_id
    folder.mkdir(exist_ok=True)
    ids = {}
    with db.session() as con:
        for tid, items in grouped.items():
            if len(items) < 2:
                continue
            crop_path = ""
            if tid in best:
                crop_path = str(folder / f"{tid}.jpg")
                cv2.imwrite(crop_path, best[tid][1])
            cur = con.execute(
                "INSERT INTO tracks (video_id, ext_id, first_t, last_t, conf, crop_path, static) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (video_id, tid, items[0][1], items[-1][1], max(r[6] for r in items), crop_path, int(tracking.is_static(items))),
            )
            ids[tid] = cur.lastrowid
            con.executemany(
                "INSERT INTO detections (track_id, t, x, y, w, h, conf) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(cur.lastrowid, *r[1:]) for r in items],
            )
    return ids


def build_segments(video_id: str, stats: dict, duration: float) -> None:
    count = max(int(np.ceil(duration)), max(stats, default=0) + 1)
    dets = np.array([stats.get(s, {}).get("detections", 0) for s in range(count)])
    clarity = np.array([np.mean(stats[s]["clarity"]) if s in stats else 0.0 for s in range(count)])

    score = np.clip(dets / 3, 0, 1)
    active = dets >= 1

    spans: list[list[int]] = []
    for s in np.flatnonzero(active):
        if spans and s - spans[-1][1] <= config.MERGE_GAP_S:
            spans[-1][1] = int(s)
        else:
            spans.append([int(s), int(s)])
    active_spans = []
    for a, b in spans:
        a, b = max(0, a - 1), min(count, b + 2)
        if b - a < config.MIN_SEGMENT_S:
            b = min(count, a + config.MIN_SEGMENT_S)
        while b - a > config.MAX_SEGMENT_S + config.MIN_SEGMENT_S:
            active_spans.append((a, a + config.MAX_SEGMENT_S))
            a += config.MAX_SEGMENT_S
        active_spans.append((a, b))

    quiet, cursor = [], 0
    for a, b in active_spans + [(count, count)]:
        while cursor < a:
            end = min(a, cursor + config.QUIET_CHUNK_S)
            quiet.append((cursor, end))
            cursor = end
        cursor = max(cursor, b)

    seed = int(hashlib.sha256(video_id.encode()).hexdigest()[:8], 16)
    picks = max(1, round(len(quiet) * config.AUDIT_SHARE)) if quiet else 0
    audit = set(random.Random(seed).sample(quiet, picks)) if quiet else set()

    typical = np.median(clarity[clarity > 0]) if (clarity > 0).any() else 0
    items = [(a, b, "active") for a, b in active_spans] + [(a, b, "quiet") for a, b in quiet]
    items.sort()
    with db.session() as con:
        con.executemany(
            "INSERT INTO seconds (video_id, second, detections, clarity) VALUES (?, ?, ?, ?)",
            [(video_id, s, int(dets[s]), float(clarity[s])) for s in range(count)],
        )
        for i, (a, b, kind) in enumerate(items):
            is_audit = int((a, b) in audit and kind == "quiet")
            status = "needs_review" if kind == "active" or is_audit else "skipped"
            con.execute(
                "INSERT INTO segments (video_id, idx, start, end, kind, is_audit, is_dense, low_vis, score, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (video_id, i, float(a), float(min(b, duration)), kind, is_audit,
                 int(dets[a:b].max(initial=0) >= config.DENSE_DETECTIONS),
                 int(typical > 0 and clarity[a:b].mean() < typical * 0.5),
                 float(score[a:b].mean()), status),
            )


def run(video_id: str) -> None:
    with db.session() as con:
        v = dict(con.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone())
    clear_results(video_id)
    notes = []

    update(video_id, status="Analyzing", stage="Probing video", progress=0, error="")
    v.update(video.probe(v["path"]))
    update(video_id, duration=v["duration"], fps=v["fps"], width=v["width"], height=v["height"])

    proxy = config.PROXIES / f"{v['source_id'] or video_id}.mp4"
    if not proxy.exists():
        update(video_id, stage="Creating playable copy")
        video.make_proxy(v["path"], proxy)
    update(video_id, proxy_path=str(proxy))

    update(video_id, stage="Loading model")
    detector = models.load_detector(v["detector"])
    notes.append(f"Detector: {detector.name}")

    update(video_id, stage="Finding fish", progress=0)
    started = time.time()
    stats, best, rows = analyze_frames(video_id, v, detector)
    update(video_id, analysis_s=time.time() - started, frames=int(v["duration"] * config.DETECT_FPS))
    ids = save_tracks(video_id, rows, best)

    update(video_id, stage="Suggesting species", progress=0.99)
    suggester = models.load_suggester()
    notes.append(f"Species: {suggester.name}")
    crops = [(ids[t], best[t][1]) for t in ids if t in best and best[t][2] >= config.MIN_SPECIES_SIDE]
    notes.append(f"{len(crops)} of {len(ids)} tracks large enough to name")
    images = [Image.fromarray(c[:, :, ::-1]) for _, c in crops]
    with db.session() as con:
        for (track_id, _), found in zip(crops, suggester.suggest(images)):
            con.executemany(
                "INSERT INTO candidates (track_id, rank, species, common, score) VALUES (?, ?, ?, ?, ?)",
                [(track_id, i, c["species"], c["common"], c["score"]) for i, c in enumerate(found)],
            )

    update(video_id, stage="Building review queue")
    build_segments(video_id, stats, v["duration"])
    update(video_id, status="Ready to review", stage="", progress=1, notes=" · ".join(notes))


def main() -> None:
    db.init()
    video_id = sys.argv[1]
    try:
        run(video_id)
    except Exception as exc:
        update(video_id, status="Failed", stage="", error=str(exc)[:300])
        raise


if __name__ == "__main__":
    main()
