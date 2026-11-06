"""End-to-end CPU worker: decode with ffmpeg, detect, track. One video per process, one thread.

Usage: pipe.py CKPT RES VIDEO FPS. Prints frames and seconds, so a parent can compute throughput.
"""
import subprocess
import sys
import time

import imageio_ffmpeg
import numpy as np
import supervision as sv
import torch

torch.set_num_threads(1)
torch.set_num_interop_threads(1)
from PIL import Image  # noqa: E402
from rfdetr import from_checkpoint  # noqa: E402
from trackers import ByteTrackTracker  # noqa: E402

ckpt, res, video, fps = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
model = from_checkpoint(ckpt, trust_checkpoint=False, resolution=res, device="cpu")
tracker = ByteTrackTracker(frame_rate=fps, track_activation_threshold=0.3, high_conf_det_threshold=0.5)
w, h = 640, 360
ff = imageio_ffmpeg.get_ffmpeg_exe()
p = subprocess.Popen([ff, "-loglevel", "error", "-threads", "1", "-i", video, "-vf", f"fps={fps},scale={w}:{h}",
                      "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
t0 = time.perf_counter()
n = 0
while True:
    buf = p.stdout.read(w * h * 3)
    if len(buf) < w * h * 3:
        break
    im = Image.fromarray(np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3))
    d = model.predict(im, threshold=0.3)
    tracker.update(d if len(d) else sv.Detections.empty())
    n += 1
dt = time.perf_counter() - t0
print(f"worker frames {n} seconds {dt:.2f} ms {dt / n * 1000:.1f}", flush=True)
