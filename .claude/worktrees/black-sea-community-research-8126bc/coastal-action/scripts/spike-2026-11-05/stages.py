"""Time the non-detector stages on CPU: decode, tracker and crop embedding.

Decode: encodes 300 real 1080p frames to H.264 at a GoPro-like bitrate with the bundled
ffmpeg, then times decoding every frame while keeping every 6th (30 to 5 fps).
"""
import glob
import json
import os
import subprocess
import time

import cv2
import imageio_ffmpeg
import numpy as np
import supervision as sv
import timm
from trackers import ByteTrackTracker
import torch
from PIL import Image

torch.set_num_threads(6)
ff = imageio_ffmpeg.get_ffmpeg_exe()
sel = json.load(open("data/sel.json"))["images"]
pebl = sorted(i["file_name"] for i in sel if i["dataset"] == "pebl_farm_fauna")
os.makedirs("data/clip", exist_ok=True)
for k, n in enumerate(pebl[:30]):
    if not os.path.exists(f"data/clip/f{k:04d}.jpg"):
        os.symlink(os.path.abspath("data/images/" + n), f"data/clip/f{k:04d}.jpg")
dets = json.load(open("out_nano.json"))["res"]
tracker = ByteTrackTracker(frame_rate=5, track_activation_threshold=0.3, high_conf_det_threshold=0.5)
t = []
for r in dets[:3000]:
    xy = np.array(r["xyxy"], dtype=float).reshape(-1, 4)
    c = np.array(r["conf"], dtype=float)
    keep = c >= 0.3
    d = sv.Detections(xyxy=xy[keep], confidence=c[keep], class_id=np.zeros(keep.sum(), dtype=int))
    t0 = time.perf_counter()
    tracker.update(d)
    t.append(time.perf_counter() - t0)
print(f"ByteTrack ms per frame: mean {np.mean(t) * 1000:.2f}, p95 {np.percentile(t, 95) * 1000:.2f}")

model = timm.create_model("vit_small_patch14_dinov2.lvd142m", pretrained=True, num_classes=0, img_size=224).eval()
cfg = timm.data.resolve_model_data_config(model)
cfg["input_size"] = (3, 224, 224)
tf = timm.data.create_transform(**cfg, is_training=False)
crops = [Image.open("data/images/" + n).convert("RGB").crop((600, 300, 1000, 700)) for n in pebl[:25]]
ts = []
with torch.inference_mode():
    for k, c in enumerate(crops):
        x = tf(c).unsqueeze(0)
        t0 = time.perf_counter()
        model(x)
        if k >= 5:
            ts.append(time.perf_counter() - t0)
print(f"DINOv2 ViT-S 224 crop on CPU, 6 threads: mean {np.mean(ts) * 1000:.1f} ms, p95 {np.percentile(ts, 95) * 1000:.1f}")
