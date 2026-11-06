"""Time detector inference on CPU only, with a thread limit, at several resolutions.

Usage: cpu_bench.py CKPT THREADS RES [RES ...]
Uses frames of mixed size from the sample. The first 5 frames warm up and are dropped.
Weights-only loading is kept, so the checkpoint cannot run code.
"""
import json
import random
import sys
import time

import torch

ckpt, threads, sizes = sys.argv[1], int(sys.argv[2]), [int(x) for x in sys.argv[3:]]
torch.set_num_threads(threads)
torch.set_num_interop_threads(1)

from PIL import Image  # noqa: E402
from rfdetr import from_checkpoint  # noqa: E402

random.seed(3)
sel = json.load(open("data/sel.json"))["images"]
frames = [Image.open("data/images/" + i["file_name"]).convert("RGB") for i in random.sample(sel, 45)]

for res in sizes:
    model = from_checkpoint(ckpt, trust_checkpoint=False, resolution=res, device="cpu")
    try:
        print("device", next(model.model.model.parameters()).device, flush=True)
    except Exception:
        pass
    t = []
    for k, im in enumerate(frames):
        t0 = time.perf_counter()
        model.predict(im, threshold=0.3)
        if k >= 5:
            t.append(time.perf_counter() - t0)
    t.sort()
    print(f"res {res} threads {threads}: mean {sum(t) / len(t) * 1000:.0f} ms, median {t[len(t) // 2] * 1000:.0f} ms, p95 {t[int(len(t) * .95)] * 1000:.0f} ms, n {len(t)}", flush=True)
