"""Test detector counts on crowded frames: whole frame versus a 2x2 tiled pass.

Measures how far low-threshold detections get as starting points for a person to correct.
Datasets are grouped as a single pool of frames with at least 30 labelled fish.
"""
import collections
import json
import sys

import numpy as np
from PIL import Image
from rfdetr import from_checkpoint

ckpt, res = sys.argv[1], int(sys.argv[2])
sel = json.load(open("data/sel3.json"))
gt = collections.defaultdict(list)
for a in sel["annotations"]:
    if a["category_id"] == 1:
        x, y, w, h = a["bbox"]
        gt[a["image_id"]].append((x + w / 2, y + h / 2, max(w, h)))
model = from_checkpoint(ckpt, trust_checkpoint=False, resolution=res)


def centres(d, ox=0, oy=0):
    return [((b[0] + b[2]) / 2 + ox, (b[1] + b[3]) / 2 + oy, c) for b, c in zip(d.xyxy.tolist(), d.confidence.tolist())]


def tiled(im):
    W, H = im.size
    pts = []
    tw, th = int(W * 0.6), int(H * 0.6)
    for ox, oy in [(0, 0), (W - tw, 0), (0, H - th), (W - tw, H - th)]:
        pts += centres(model.predict(im.crop((ox, oy, ox + tw, oy + th)), threshold=0.1), ox, oy)
    pts.sort(key=lambda p: -p[2])
    keep = []
    r = max(W, H) * 0.012
    for p in pts:
        if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 > r * r for q in keep):
            keep.append(p)
    return keep


rows = {"whole": [], "tiled": []}
for img in sel["images"]:
    g = gt[img["id"]]
    im = Image.open("data/images3/" + img["file_name"]).convert("RGB")
    whole = centres(model.predict(im, threshold=0.1))
    for name, pts in (("whole", whole), ("tiled", tiled(im))):
        for t in (0.1, 0.3, 0.5):
            p = [x for x in pts if x[2] >= t]
            used = set()
            tp = 0
            for x, y, c in p:
                best, bj = None, -1
                for j, (a, b, s) in enumerate(g):
                    if j in used:
                        continue
                    dist = ((x - a) ** 2 + (y - b) ** 2) ** 0.5
                    if dist <= s / 2 and (best is None or dist < best):
                        best, bj = dist, j
                if bj >= 0:
                    used.add(bj)
                    tp += 1
            rows[name].append((img["dataset"], t, len(g), len(p), tp))

for name, r in rows.items():
    for t in (0.1, 0.3, 0.5):
        v = np.array([(x[2], x[3], x[4]) for x in r if x[1] == t], dtype=float)
        n = v[:, 0].sum()
        fp = (v[:, 1] - v[:, 2]).sum()
        miss = (v[:, 0] - v[:, 2]).sum()
        print(f"{name} t={t}: frames {len(v)}, true fish {n:.0f}, nMAE {np.abs(v[:, 1] - v[:, 0]).sum() / n:.3f}, point recall {v[:, 2].sum() / n:.3f}, "
              f"precision {v[:, 2].sum() / max(v[:, 1].sum(), 1):.3f}, median true {np.median(v[:, 0]):.0f}, median proposed {np.median(v[:, 1]):.0f}, "
              f"corrections per frame {(fp + miss) / len(v):.1f} of {n / len(v):.1f}")
