"""Run a Community Fish Detector checkpoint over the sampled frames.

Loads with trust_checkpoint=False (torch.load weights_only=True), so the checkpoint
cannot execute code. A static pickle scan showed only tensors and an OrderedDict.
Writes detections at a low threshold so precision/recall can be computed later.
"""
import json
import sys
import time

from PIL import Image
from rfdetr import from_checkpoint

name, ckpt, out = sys.argv[1:4]
sel = json.load(open("data/sel.json"))
model = from_checkpoint(ckpt, trust_checkpoint=False)

res, times, bad = [], [], 0
for n, img in enumerate(sel["images"]):
    try:
        im = Image.open("data/images/" + img["file_name"]).convert("RGB")
    except Exception:
        bad += 1
        continue
    t0 = time.perf_counter()
    d = model.predict(im, threshold=0.05)
    times.append(time.perf_counter() - t0)
    res.append({"id": img["id"], "xyxy": d.xyxy.tolist(), "conf": d.confidence.tolist(), "cls": d.class_id.tolist()})
    if n % 300 == 0:
        recent = times[-50:]
        print(n, round(sum(recent) / len(recent), 4), flush=True)

t = sorted(times[10:])
summary = {"mean_s": sum(t) / len(t), "p50": t[len(t) // 2], "p95": t[int(len(t) * 0.95)], "bad": bad, "n": len(t)}
json.dump({"res": res, **summary}, open(out, "w"))
print("done", name, summary, "fps", len(t) / sum(t), flush=True)
