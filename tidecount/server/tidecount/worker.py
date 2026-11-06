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

from . import config, db, models, settings, tracking, video


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
        for table in ("tracks", "segments", "seconds", "school_counts", "events", "frame_boxes"):
            con.execute(f"DELETE FROM {table} WHERE video_id = ?", (video_id,))


def analyze_frames(video_id: str, v: dict, detector, s: settings.Settings) -> tuple[dict, dict, list]:
    """One pass over the video. Returns per-second stats, the best crop per track, and detections.

    A second's `detections` is the most boxes on one of its frames, leaving out flicker. `boxes` and
    `flicker` under the key -1 count every box and the ones left out, for the run's notes.

    Every box the detector draws is saved to frame_boxes as it goes, including ones too unsure for
    the queue or the tracker. Counting needs them: a track only starts on a confident box that
    lasts, which keeps false alarms out of the queue but drops most fish in a busy frame.
    """
    chosen = s.for_detector(v["detector"])
    full_w, full_h = v["width"] // 2 * 2, v["height"] // 2 * 2
    width = chosen.width or full_w
    height = int(round(width * v["height"] / v["width"] / 2)) * 2
    scale = full_w / width
    tracker = ByteTrackTracker(
        frame_rate=s.fps,
        lost_track_buffer=s.tracker.lost_track_buffer,
        track_activation_threshold=chosen.queue_threshold,
        high_conf_det_threshold=s.tracker.start_confidence,
        minimum_consecutive_frames=s.tracker.min_consecutive,
    )
    floor = min(config.BOX_FLOOR, chosen.queue_threshold, chosen.dot_threshold)
    stats: dict[int, dict] = {}
    best: dict[int, tuple] = {}
    rows: list[tuple] = []
    centres: list[np.ndarray] = []
    unsaved: list[tuple] = []
    last_update = 0.0

    def save_boxes() -> None:
        with db.session() as con:
            con.executemany("INSERT INTO frame_boxes (video_id, t, x, y, w, h, conf) VALUES (?, ?, ?, ?, ?, ?, ?)", unsaved)
        unsaved.clear()

    for idx, buf in enumerate(video.decode_frames(v["path"], full_w, full_h, s.fps)):
        t = idx / s.fps
        original = np.frombuffer(buf, dtype=np.uint8).reshape(full_h, full_w, 3)
        frame = cv2.resize(original, (width, height), interpolation=cv2.INTER_AREA)
        stat = stats.setdefault(int(t), {"detections": 0, "clarity": []})
        gray = cv2.cvtColor(cv2.resize(frame, (320, 180)), cv2.COLOR_BGR2GRAY)
        stat["clarity"].append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))

        image = Image.fromarray(frame[:, :, ::-1])
        every, sure = detector.detect(image, floor)
        every, sure = np.asarray(every, dtype=float).reshape(-1, 4), np.asarray(sure, dtype=float)
        unsaved.extend(
            (video_id, t, x1 / width, y1 / height, (x2 - x1) / width, (y2 - y1) / height, float(c))
            for (x1, y1, x2, y2), c in zip(every, sure) if c >= floor
        )
        # The queue and the tracker see what they always did: boxes at or above the queue threshold.
        boxes, conf = every[sure >= chosen.queue_threshold], sure[sure >= chosen.queue_threshold]
        centres.append(np.asarray(boxes, dtype=float).reshape(-1, 4)[:, [0, 2, 1, 3]].reshape(-1, 2, 2).mean(axis=2) / (width, height))
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
            save_boxes()
            update(video_id, progress=min(0.99, t / max(v["duration"], 1)))
            last_update = now

    save_boxes()
    masks = tracking.flicker(centres, s.fps, s.flicker)
    for idx, mask in enumerate(masks):
        stat = stats[int(idx / s.fps)]
        stat["detections"] = max(stat["detections"], int((~mask).sum()))
    stats[-1] = {"boxes": sum(len(m) for m in masks), "flicker": sum(int(m.sum()) for m in masks)}
    return stats, best, rows


def save_tracks(video_id: str, rows: list, best: dict, s: settings.Settings) -> dict[int, int]:
    """Drop very short tracks, which are mostly noise, and save the rest."""
    grouped: dict[int, list] = {}
    for r in sorted(rows, key=lambda r: r[1]):
        grouped.setdefault(r[0], []).append(r)
    folder = config.CROPS / video_id
    folder.mkdir(parents=True, exist_ok=True)
    ids = {}
    with db.session() as con:
        for tid, items in grouped.items():
            if len(items) < s.tracker.min_points:
                continue
            crop_path = ""
            if tid in best:
                crop_path = str(folder / f"{tid}.jpg")
                cv2.imwrite(crop_path, best[tid][1])
            cur = con.execute(
                "INSERT INTO tracks (video_id, ext_id, first_t, last_t, conf, crop_path, static) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (video_id, tid, items[0][1], items[-1][1], max(r[6] for r in items), crop_path, int(tracking.is_static(items, s.still))),
            )
            ids[tid] = cur.lastrowid
            con.executemany(
                "INSERT INTO detections (track_id, t, x, y, w, h, conf) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(cur.lastrowid, *r[1:]) for r in items],
            )
    return ids


def build_segments(video_id: str, stats: dict, duration: float, q: settings.Queue) -> None:
    count = max(int(np.ceil(duration)), max(stats, default=0) + 1)
    dets = np.array([stats.get(s, {}).get("detections", 0) for s in range(count)])
    clarity = np.array([np.mean(stats[s]["clarity"]) if s in stats else 0.0 for s in range(count)])

    score = np.clip(dets / 3, 0, 1)
    active = dets >= 1

    spans: list[list[int]] = []
    for s in np.flatnonzero(active):
        if spans and s - spans[-1][1] <= q.merge_gap_s:
            spans[-1][1] = int(s)
        else:
            spans.append([int(s), int(s)])
    active_spans = []
    for a, b in spans:
        a, b = max(0, a - 1), min(count, b + 2)
        if b - a < q.min_segment_s:
            b = min(count, a + q.min_segment_s)
        while b - a > q.max_segment_s + q.min_segment_s:
            active_spans.append((a, a + q.max_segment_s))
            a += q.max_segment_s
        active_spans.append((a, b))

    quiet, cursor = [], 0
    for a, b in active_spans + [(count, count)]:
        while cursor < a:
            end = min(a, cursor + q.quiet_chunk_s)
            quiet.append((cursor, end))
            cursor = end
        cursor = max(cursor, b)

    seed = int(hashlib.sha256(video_id.encode()).hexdigest()[:8], 16)
    picks = max(1, round(len(quiet) * q.audit_share)) if quiet else 0
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
                 int(dets[a:b].max(initial=0) >= q.dense_detections),
                 int(typical > 0 and clarity[a:b].mean() < typical * 0.5),
                 float(score[a:b].mean()), status),
            )


def run(video_id: str) -> None:
    s = settings.load()  # first, so a broken file can't clear the earlier results
    with db.session() as con:
        v = dict(con.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone())
    clear_results(video_id)
    notes = []

    update(video_id, status="Analyzing", stage="Probing video", progress=0, error="",
           settings_json=s.model_dump_json(), settings_hash=s.hash())
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
    stats, best, rows = analyze_frames(video_id, v, detector, s)
    totals = stats.pop(-1)
    if s.flicker.need:
        notes.append(f"Flicker: {totals['flicker']} of {totals['boxes']} boxes came and went, so they didn't count towards the queue")
    update(video_id, analysis_s=time.time() - started, frames=int(v["duration"] * s.fps))
    ids = save_tracks(video_id, rows, best, s)

    update(video_id, stage="Suggesting species", progress=0.99)
    suggester = models.load_suggester(s.species.model)
    notes.append(f"Species: {suggester.name}")
    crops = [(ids[t], best[t][1]) for t in ids if t in best and best[t][2] >= s.species.min_side]
    notes.append(f"{len(crops)} of {len(ids)} tracks large enough to name")
    images = [Image.fromarray(c[:, :, ::-1]) for _, c in crops]
    with db.session() as con:
        for (track_id, _), found in zip(crops, suggester.suggest(images, s.species.top_k)):
            con.executemany(
                "INSERT INTO candidates (track_id, rank, species, common, score) VALUES (?, ?, ?, ?, ?)",
                [(track_id, i, c["species"], c["common"], c["score"]) for i, c in enumerate(found)],
            )

    update(video_id, stage="Building review queue")
    build_segments(video_id, stats, v["duration"], s.queue)
    notes.append(f"Settings: {s.hash()}" if settings.PATH.exists() else f"Settings: {s.hash()}, built-in defaults")
    update(video_id, status="Ready to review", stage="", progress=1, notes=" · ".join(notes))


def main() -> None:
    config.ensure_folders()
    db.init()
    video_id = sys.argv[1]
    try:
        run(video_id)
    except Exception as exc:
        update(video_id, status="Failed", stage="", error=str(exc)[:300])
        raise


if __name__ == "__main__":
    main()
