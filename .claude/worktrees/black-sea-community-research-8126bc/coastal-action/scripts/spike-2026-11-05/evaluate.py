"""Score detector output per dataset: AP50, P/R/F1, frame counts, MaxN and MeanCount.

Ground truth is category 1 (fish). Detections overlapping a non-fish box are ignored,
so a crab labelled as a crab is neither credited nor penalised. Videos are recovered
from file names, so MaxN and MeanCount can be compared per deployment or clip.
"""
import collections
import json
import re
import sys

import numpy as np


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0


def video_key(ds, name):
    n = name[len(ds) + 1:]
    return re.split(r"_frame_|-\d{4}_jpg|_\d{6}\.|_5fps", n)[0]


sel = json.load(open("data/sel.json"))
sel2 = json.load(open("data/sel2.json"))
sel["annotations"] += sel2["annotations"]
sel["images"] += sel2["images"]
gt = collections.defaultdict(lambda: {"fish": [], "other": []})
for a in sel["annotations"]:
    x, y, w, h = a["bbox"]
    gt[a["image_id"]]["fish" if a["category_id"] == 1 else "other"].append([x, y, x + w, y + h])
img = {i["id"]: i for i in sel["images"]}

for label, path in [a.split("=") for a in sys.argv[1:]]:
    out = json.load(open(path))
    print(f"\n=== {label}: {out['n']} frames, mean {out['mean_s'] * 1000:.0f} ms, p95 {out['p95'] * 1000:.0f} ms, "
          f"{1 / out['mean_s']:.1f} fps, unreadable {out['bad']}")
    by = collections.defaultdict(list)
    for r in out["res"]:
        by[img[r["id"]]["dataset"]].append(r)
    for ds, rs in by.items():
        scored = []
        n_gt = 0
        per = []
        for r in rs:
            g = gt[r["id"]]
            n_gt += len(g["fish"])
            order = np.argsort(r["conf"])[::-1]
            used = set()
            kept = []
            for k in order:
                box, c = r["xyxy"][k], r["conf"][k]
                best, bj = 0, -1
                for j, b in enumerate(g["fish"]):
                    if j not in used:
                        v = iou(box, b)
                        if v > best:
                            best, bj = v, j
                if best >= 0.5:
                    used.add(bj)
                    scored.append((c, 1))
                    kept.append((c, 1))
                elif any(iou(box, b) >= 0.5 for b in g["other"]):
                    continue
                else:
                    scored.append((c, 0))
                    kept.append((c, 0))
            per.append((r["id"], len(g["fish"]), kept))
        scored.sort(key=lambda x: -x[0])
        tp = np.cumsum([s[1] for s in scored])
        fp = np.cumsum([1 - s[1] for s in scored])
        rec = tp / max(n_gt, 1)
        prec = tp / np.maximum(tp + fp, 1)
        env = np.maximum.accumulate(prec[::-1])[::-1] if len(prec) else np.array([0])
        ap = np.mean([env[rec >= t].max() if (rec >= t).any() else 0 for t in np.linspace(0, 1, 101)])
        best = None
        for t in np.arange(0.05, 0.95, 0.05):
            t_ = sum(s[1] for s in scored if s[0] >= t)
            f_ = sum(1 - s[1] for s in scored if s[0] >= t)
            p = t_ / max(t_ + f_, 1)
            q = t_ / max(n_gt, 1)
            f1 = 2 * p * q / max(p + q, 1e-9)
            if best is None or f1 > best[0]:
                best = (f1, t, p, q)
        line = [f"{ds}: frames {len(rs)}, fish boxes {n_gt}, AP50 {ap:.3f}, best F1 {best[0]:.3f} @ {best[1]:.2f} "
                f"(P {best[2]:.3f} R {best[3]:.3f})"]
        for t in (0.3, 0.5):
            t_ = sum(s[1] for s in scored if s[0] >= t)
            f_ = sum(1 - s[1] for s in scored if s[0] >= t)
            p = t_ / max(t_ + f_, 1)
            q = t_ / max(n_gt, 1)
            err = [sum(1 for k in kept if k[0] >= t) - n for _, n, kept in per]
            empty = [sum(1 for k in kept if k[0] >= t) for _, n, kept in per if n == 0]
            s = f"  t={t}: P {p:.3f} R {q:.3f} F1 {2 * p * q / max(p + q, 1e-9):.3f}, frame count MAE {np.mean(np.abs(err)):.2f}, bias {np.mean(err):+.2f}"
            if empty:
                s += f", empty frames {len(empty)} with any detection {np.mean(np.array(empty) > 0):.2f}"
            line.append(s)
        print("\n".join(line))
        if ds in ("kso_mussel_bruv", "pebl_farm_fauna", "brackish_dataset"):
            for t in (0.3, 0.5):
                vids = collections.defaultdict(list)
                for rid, n, kept in per:
                    vids[video_key(ds, rid)].append((n, sum(1 for k in kept if k[0] >= t)))
                vids = {k: v for k, v in vids.items() if len(v) >= 20}
                if len(vids) < 2:
                    continue
                a_g = np.array([max(n for n, _ in v) for v in vids.values()], float)
                a_d = np.array([max(d for _, d in v) for v in vids.values()], float)
                m_g = np.array([np.mean([n for n, _ in v]) for v in vids.values()])
                m_d = np.array([np.mean([d for _, d in v]) for v in vids.values()])
                print(f"  videos(>=20 frames) t={t}: n={len(vids)} MaxN MAE {np.abs(a_d - a_g).mean():.2f} (true mean {a_g.mean():.2f}), "
                      f"nMAE {np.abs(a_d - a_g).sum() / max(a_g.sum(), 1):.2f}; MeanCount MAE {np.abs(m_d - m_g).mean():.3f} "
                      f"(true mean {m_g.mean():.3f}), nMAE {np.abs(m_d - m_g).sum() / max(m_g.sum(), 1e-9):.2f}, "
                      f"r {np.corrcoef(m_d, m_g)[0, 1]:.3f}")
