"""Run the nano detector at a chosen resolution over both samples on the GPU to score accuracy.

Accuracy does not depend on the device, so this is faster than scoring on CPU.
Optional simulated water: tannin (colour only) or turbid (veil and blur).
Usage: infer_res.py CKPT RES OUT [plain|tannin|turbid]
"""
import json
import sys

import numpy as np
from PIL import Image, ImageFilter
from rfdetr import from_checkpoint

ckpt, res, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
water = sys.argv[4] if len(sys.argv) > 4 else "plain"
model = from_checkpoint(ckpt, trust_checkpoint=False, resolution=res)


def apply(im):
    if water == "plain":
        return im
    a = np.asarray(im, dtype=np.float32) / 255
    if water.startswith("tannin"):
        a = a * np.array([0.95, 0.60, 0.22], dtype=np.float32)
        if water == "tannin_wb":
            a = (np.round(a * 255) / 255).astype(np.float32)
            a = a * (a.mean() / np.maximum(a.reshape(-1, 3).mean(0), 1e-3))
    else:
        veil = np.array([0.55, 0.60, 0.50], dtype=np.float32)
        a = 0.45 * a + 0.55 * veil
    r = Image.fromarray((a.clip(0, 1) * 255).astype("uint8"))
    return r.filter(ImageFilter.GaussianBlur(1.2)) if water == "turbid" else r


res_all = []
for path, folder in [("data/sel.json", "data/images/"), ("data/sel2.json", "data/images2/")]:
    for img in json.load(open(path))["images"]:
        im = apply(Image.open(folder + img["file_name"]).convert("RGB"))
        d = model.predict(im, threshold=0.05)
        res_all.append({"id": img["id"], "xyxy": d.xyxy.tolist(), "conf": d.confidence.tolist(), "cls": d.class_id.tolist()})
json.dump({"res": res_all, "mean_s": 1, "p95": 1, "bad": 0, "n": len(res_all)}, open(out, "w"))
print("done", res, water, len(res_all), flush=True)
