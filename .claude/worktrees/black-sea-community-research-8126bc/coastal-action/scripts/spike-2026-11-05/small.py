"""Two checks for tiny distant fish, the case on the technician's grid slide.

1. Detector recall by fish size in source pixels, per resolution.
2. A motion-speck proposer: temporal median background, difference, connected components.
   Scored on sequential Brackish frames at native size against labelled fish centres.
"""
import collections
import json
import re
import sys
import time

import cv2
import numpy as np

sel = json.load(open("data/sel.json"))
sel2 = json.load(open("data/sel2.json"))
images = {i["id"]: i for i in sel["images"] + sel2["images"]}
gt = collections.defaultdict(list)
for a in sel["annotations"] + sel2["annotations"]:
    if a["category_id"] == 1:
        gt[a["image_id"]].append(a["bbox"])
BINS = [(0, 16), (16, 32), (32, 64), (64, 128), (128, 9999)]
SETS = ("pebl_farm_fauna", "kso_mussel_bruv", "fjordfish", "griffith_seagrass", "orange_chromide")


def iou(a, b):
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[2], b[3]
    ix = max(0, min(ax2, bx2) - max(a[0], b[0]))
    iy = max(0, min(ay2, by2) - max(a[1], b[1]))
    inter = ix * iy
    union = a[2] * a[3] + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0


for path in sys.argv[1:]:
    res = json.load(open(path))["res"]
    tot = collections.Counter()
    hit = collections.Counter()
    for r in res:
        img = images[r["id"]]
        if img["dataset"] not in SETS:
            continue
        boxes = [b for b, c in zip(r["xyxy"], r["conf"]) if c >= 0.3]
        scale = 1920 / img["width"]
        for g in gt[r["id"]]:
            size = max(g[2], g[3]) * scale
            b = next(k for k, (lo, hi) in enumerate(BINS) if lo <= size < hi)
            tot[b] += 1
            hit[b] += any(iou(g, d) >= 0.3 for d in boxes)
    print(path, "recall at t=0.3, IoU 0.3, by longest side in 1080p-equivalent pixels:",
          ", ".join(f"{BINS[b][0]}-{BINS[b][1]}px {hit[b] / max(tot[b], 1):.2f} (n={tot[b]})" for b in range(len(BINS))))

clips = collections.defaultdict(list)
for i in sel["images"]:
    if i["dataset"] == "brackish_dataset":
        m = re.search(r"brackish_dataset_(.+)-(\d{4})_jpg", i["file_name"])
        clips[m.group(1)].append((int(m.group(2)), i))
HALF = 7
for clip, fs in clips.items():
    fs.sort(key=lambda x: x[0])
    grey = [cv2.imread("data/images/" + i["file_name"], cv2.IMREAD_GRAYSCALE) for _, i in fs]
    for thr, area in [(14, 3), (20, 3)]:
        tp = fp = miss = 0
        times = []
        for k in range(HALF, len(fs) - HALF, 5):
            t0 = time.perf_counter()
            bg = np.median(np.stack(grey[k - HALF:k + HALF + 1:2]), axis=0).astype(np.uint8)
            mask = (cv2.absdiff(grey[k], bg) > thr).astype(np.uint8)
            n, _, stats, cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
            pts = [cent[j] for j in range(1, n) if stats[j, cv2.CC_STAT_AREA] >= area]
            times.append(time.perf_counter() - t0)
            boxes = gt[fs[k][1]["id"]]
            used = set()
            for x, y in pts:
                found = -1
                for j, (a, b, w, h) in enumerate(boxes):
                    if j not in used and a - 3 <= x <= a + w + 3 and b - 3 <= y <= b + h + 3:
                        found = j
                        break
                if found >= 0:
                    used.add(found)
                    tp += 1
                else:
                    fp += 1
            miss += len(boxes) - len(used)
        print(f"{clip[:30]} thr {thr}: fish {tp + miss}, point recall {tp / max(tp + miss, 1):.2f}, precision {tp / max(tp + fp, 1):.2f}, "
              f"{np.median(times) * 1000:.1f} ms per frame at {grey[0].shape[1]}x{grey[0].shape[0]}")
