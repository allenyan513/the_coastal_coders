"""Test a background-subtraction gate on sequential river frames, and time the cheap stages.

For each clip: how many frames the gate skips, and how many fish frames and fish crossings
survive. Also measures visibility and colour metrics on clean and simulated water.
"""
import collections
import json
import re
import time

import cv2
import numpy as np

sel = json.load(open("data/sel2.json"))
fish = collections.Counter(a["image_id"] for a in sel["annotations"] if a["category_id"] == 1)
frames = collections.defaultdict(list)
for i in sel["images"]:
    if i["dataset"] != "mit_river_herring":
        continue
    m = re.match(r"mit_river_herring_(.+)_frame_(\d+)\.PNG", i["file_name"])
    frames[m.group(1)].append((int(m.group(2)), i))

SIZE = (320, 180)
t_gate = []
for clip, fs in frames.items():
    fs.sort(key=lambda x: x[0])
    for var, ratio in [(16, 0.0005), (16, 0.002), (32, 0.002)]:
        sub = cv2.createBackgroundSubtractorMOG2(history=120, varThreshold=var, detectShadows=False)
        keep = []
        for k, (_, i) in enumerate(fs):
            im = cv2.imread("data/images2/" + i["file_name"])
            t0 = time.perf_counter()
            small = cv2.resize(im, SIZE, interpolation=cv2.INTER_AREA)
            g = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
            mask = sub.apply(g)
            active = (mask > 0).mean() > ratio
            t_gate.append(time.perf_counter() - t0)
            # the first frames only train the background, so keep them
            keep.append(active or k < 15)
        keep = np.array(keep)
        has = np.array([fish[i["id"]] > 0 for _, i in fs])
        # dilate by 1 s worth of frames so a gate hit keeps neighbouring frames
        wide = np.convolve(keep.astype(int), np.ones(11), mode="same") > 0
        runs, seen = 0, 0
        k = 0
        while k < len(has):
            if has[k]:
                j = k
                while j < len(has) and has[j]:
                    j += 1
                runs += 1
                seen += bool(wide[k:j].any())
                k = j
            else:
                k += 1
        print(f"{clip} var {var} ratio {ratio}: frames {len(has)}, fish frames {has.sum()}, gate keeps {wide.mean():.2f}, "
              f"fish frames kept {wide[has].mean():.2f}, crossings seen {seen}/{runs}")
t_gate = sorted(t_gate)
print(f"gate ms per frame, 1 thread default: median {t_gate[len(t_gate) // 2] * 1000:.2f}, p95 {t_gate[int(len(t_gate) * .95)] * 1000:.2f}")


def metrics(bgr):
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    return g.std(), cv2.Laplacian(g, cv2.CV_64F).var(), lab[..., 1].mean() - 128, lab[..., 2].mean() - 128


def water(bgr, kind):
    a = bgr.astype(np.float32) / 255
    if kind == "tannin":
        a = a * np.array([0.22, 0.60, 0.95], dtype=np.float32)
    elif kind == "turbid":
        a = 0.45 * a + 0.55 * np.array([0.50, 0.60, 0.55], dtype=np.float32)
    out = (a.clip(0, 1) * 255).astype(np.uint8)
    return cv2.GaussianBlur(out, (0, 0), 1.2) if kind == "turbid" else out


sel1 = json.load(open("data/sel.json"))["images"]
pick = [i for i in sel1 if i["dataset"] in ("griffith_seagrass", "fjordfish")][::8] + [i for i in sel1 if i["dataset"] == "pebl_farm_fauna"][::20]
rows = collections.defaultdict(list)
for i in pick:
    im = cv2.imread("data/images/" + i["file_name"])
    im = cv2.resize(im, (960, 540), interpolation=cv2.INTER_AREA)
    for kind in ("clean", "tannin", "turbid"):
        rows[kind].append(metrics(water(im, kind)))
for kind, v in rows.items():
    a = np.array(v)
    print(f"{kind}: n {len(a)}, RMS contrast {a[:, 0].mean():.1f}, Laplacian var {a[:, 1].mean():.1f}, Lab a* {a[:, 2].mean():+.1f}, Lab b* {a[:, 3].mean():+.1f}")
