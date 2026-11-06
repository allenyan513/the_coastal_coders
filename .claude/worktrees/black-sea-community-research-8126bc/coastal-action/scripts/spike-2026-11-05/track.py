"""Run ByteTrack over detections on the Brackish clips.

The sample has no ground-truth identities, so this checks tracker behaviour only:
track counts are compared against frame-based MaxN, not against true unique fish.
"""
import collections
import json
import re
import sys

import numpy as np
import supervision as sv
from trackers import ByteTrackTracker

path, thr = sys.argv[1], float(sys.argv[2])
sel = json.load(open("data/sel.json"))
gt_count = collections.Counter(a["image_id"] for a in sel["annotations"] if a["category_id"] == 1)
out = {r["id"]: r for r in json.load(open(path))["res"]}
clips = collections.defaultdict(list)
for i in sel["images"]:
    if i["dataset"] != "brackish_dataset":
        continue
    m = re.search(r"brackish_dataset_(.+)-(\d{4})_jpg", i["file_name"])
    clips[m.group(1)].append((int(m.group(2)), i["id"]))

for clip, frames in clips.items():
    frames.sort()
    tracker = ByteTrackTracker(frame_rate=15, track_activation_threshold=0.3, high_conf_det_threshold=0.5)
    lengths = collections.Counter()
    for _, fid in frames:
        r = out.get(fid)
        if r is None or not r["xyxy"]:
            d = sv.Detections.empty()
        else:
            xy = np.array(r["xyxy"], dtype=float)
            c = np.array(r["conf"], dtype=float)
            keep = c >= thr
            d = sv.Detections(xyxy=xy[keep], confidence=c[keep], class_id=np.zeros(keep.sum(), dtype=int))
        for t in tracker.update(d).tracker_id:
            if t >= 0:
                lengths[int(t)] += 1
    steps = [frames[i + 1][0] - frames[i][0] for i in range(len(frames) - 1)]
    long_tracks = sum(1 for v in lengths.values() if v >= 5)
    counts = [gt_count[f] for _, f in frames]
    print(f"{clip}: frames {len(frames)}, median step {np.median(steps):.0f}, GT MaxN {max(counts)}, GT mean {np.mean(counts):.2f}, "
          f"tracks {len(lengths)}, tracks>=5 frames {long_tracks}, median track length {np.median(list(lengths.values())) if lengths else 0:.0f}")
