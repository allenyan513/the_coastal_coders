"""Use river herring metadata to test how frame sampling affects fast fish, and pick extra samples.

The clips contain fish and empty frames in sequence, so continuous runs of fish frames
approximate crossings. No images are needed for the sampling test. Also selects the
freshwater frames used for the detector and motion filter tests.
"""
import collections
import json
import random
import re

import numpy as np

random.seed(11)
d = json.load(open("data/community_fish_detector_20261029.json"))
fish = collections.Counter(a["image_id"] for a in d["annotations"] if a["category_id"] == 1)

clips = collections.defaultdict(list)
for i in d["images"]:
    if i.get("dataset") != "mit_river_herring":
        continue
    m = re.match(r"mit_river_herring_(.+)_frame_(\d+)\.PNG", i["file_name"])
    if m:
        clips[m.group(1)].append((int(m.group(2)), i))

episodes = []
lengths = []
for name, frames in clips.items():
    frames.sort(key=lambda x: x[0])
    lengths.append(len(frames))
    run = 0
    for _, i in frames:
        if fish[i["id"]] > 0:
            run += 1
        elif run:
            episodes.append(run)
            run = 0
    if run:
        episodes.append(run)
ep = np.array(episodes)
print("clips", len(clips), "frames", sum(lengths), "median clip", np.median(lengths))
print("crossings", len(ep), "median frames", np.median(ep), "p10", np.percentile(ep, 10), "p25", np.percentile(ep, 25), "p90", np.percentile(ep, 90))
print("share of frames with fish", sum(1 for i in fish if i.startswith("mit_river")) / sum(lengths))
for stride in (2, 3, 6, 10, 15, 30, 60):
    # chance a run of length L contains a sampled frame at a random phase = min(1, L / stride)
    p = np.minimum(1, ep / stride)
    print(f"stride {stride}: expected share of crossings seen {p.mean():.3f}")

# Clips with both empty and fish frames, for the motion filter.
scored = []
for name, frames in clips.items():
    n = len(frames)
    k = sum(1 for _, i in frames if fish[i["id"]] > 0)
    if n >= 200 and 0.05 <= k / n <= 0.5:
        scored.append((name, n, k))
print("candidate clips", len(scored), scored[:5])
site = collections.defaultdict(list)
for s in scored:
    site[s[0].split("_")[0]].append(s)
chosen = [random.choice(v) for v in site.values()][:3]
print("chosen", chosen)

sel_frames = []
for name, n, k in chosen:
    sel_frames += [i for _, i in sorted(clips[name], key=lambda x: x[0])[:700]]
extra = [i for i in d["images"] if i.get("dataset") == "orange_chromide"]
extra = random.sample(extra, 150)
pom = [i for i in d["images"] if i.get("dataset") == "pomerfish" and fish[i["id"]] > 0]
pom = random.sample(pom, 60)
images = sel_frames + extra + pom
ids = {i["id"] for i in images}
ann = [a for a in d["annotations"] if a["image_id"] in ids]
json.dump({"images": images, "annotations": ann, "categories": d["categories"], "clips": [c[0] for c in chosen]}, open("data/sel2.json", "w"))
open("data/urls2.txt", "w").write("\n".join(
    "https://storage.googleapis.com/public-datasets-lila/community-fish-detection-dataset-2026/images/" + i["file_name"] for i in images))
print(len(images), collections.Counter(i["dataset"] for i in images))
