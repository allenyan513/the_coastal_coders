"""Paths, the model catalogue and machine settings. What an experiment may change is in settings.toml."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("TIDECOUNT_DATA", ROOT / "data"))
DB_PATH = DATA / "tidecount.db"
VIDEOS = DATA / "videos"
PROXIES = DATA / "proxies"
CROPS = DATA / "crops"
FRAMES = DATA / "frames"
EXPORTS = DATA / "exports"
WEIGHTS = ROOT / "data" / "weights"
WEB_DIST = ROOT / "web" / "dist"
SPECIES_CSV = Path(__file__).parent / "species.csv"
SPECIES_MEDIA = Path(__file__).parent / "species_media.json"        # images, credits, licences
SPECIES_PROFILES = Path(__file__).parent / "species_profiles.json"  # identification notes
SPECIES_TAXONOMY = Path(__file__).parent / "species_taxonomy.json"  # names checked against WoRMS
SPECIES_CONSERVATION = Path(__file__).parent / "species_conservation.json"  # verified at-risk / invasive status
# Photos people upload in the Media Library, and which species each curated or uploaded photo is
# shown on. Data, not code: it lives with the videos, never in the package beside species.csv.
SPECIES_LIBRARY = DATA / "species_library"
# Permanently deleting an uploaded photo is allowed from the computer running Tideflow, or with this
# key in the X-Tideflow-Admin-Token header (e.g. on a server behind Caddy). Unset: no key works.
MEDIA_ADMIN_TOKEN = os.environ.get("TIDECOUNT_MEDIA_ADMIN_TOKEN", "")

CFD_RELEASE = "https://github.com/WildHackers/community-fish-detector/releases/download/2026.07.06-release/"
DETECTORS = {
    "cfd-nano": {
        "label": "Community Fish Detector Nano",
        "kind": "rfdetr",
        "file": "cfd-rf-detr-nano-640-2026.02.02.cp-011.20260706-release.pth",
        "url": CFD_RELEASE + "cfd-rf-detr-nano-640-2026.02.02.cp-011.20260706-release.pth",
    },
    "cfd-small": {
        "label": "Community Fish Detector Small",
        "kind": "rfdetr",
        "file": "cfd-rf-detr-small-1024-2026.06.06.cp-016.20260706-release.pth",
        "url": CFD_RELEASE + "cfd-rf-detr-small-1024-2026.06.06.cp-016.20260706-release.pth",
    },
    "cfd-medium": {
        "label": "Community Fish Detector Medium",
        "kind": "rfdetr",
        "file": "cfd-rf-detr-medium-1024-2026.03.24.cp-011.20260706-release.pth",
        "url": CFD_RELEASE + "cfd-rf-detr-medium-1024-2026.03.24.cp-011.20260706-release.pth",
    },
    "megalodon": {
        "label": "FathomNet Megalodon, all marine objects",
        "kind": "yolo",
        "file": "mbari-megalodon-yolo11x.pt",
        "url": "https://huggingface.co/FathomNet/megalodon-2024-yolov11/resolve/main/mbari-megalodon-yolo11x.pt",
    },
    "noaa-gray": {
        "label": "NOAA YOLO11n grayscale",
        "kind": "yolo",
        "file": "noaa-yolo11n-fish-gray.pt",
        "url": "https://huggingface.co/akridge/yolo11-fish-detector-grayscale/resolve/main/train/weights/best.pt",
    },
}
# Ultralytics checkpoints are full pickles, so loading one can run code. Allen enabled them on
# 2026-11-05 after a static scan. Set TIDECOUNT_ALLOW_YOLO=0 to turn them off.
ALLOW_YOLO = os.environ.get("TIDECOUNT_ALLOW_YOLO", "1") == "1"
DEVICE = os.environ.get("TIDECOUNT_DEVICE", "auto")
# Set TIDECOUNT_WORKER=0 to run the API without analysing queued videos, e.g. for UI work.
RUN_WORKER = os.environ.get("TIDECOUNT_WORKER", "1") == "1"
THREADS = 6

# Following a fish a person boxed, in follow.py. Tried on the Galway clips on 2026-11-06: looser
# values ended on marks on the lens or on a neighbour in a school.
FOLLOW_FPS = 10             # frames looked at per second, so a fish moves little between two of them
FOLLOW_THRESHOLD = 0.05     # the detector's confidence floor inside the window, far under the queue's
FOLLOW_ZOOM = 3.0           # the window's side, in fish lengths
FOLLOW_MIN_WINDOW = 320     # and its smallest side, in pixels of the original video
FOLLOW_OVERLAP = 0.25       # a box fits when it shares this much area with where the fish should be,
FOLLOW_NEARBY = 0.4         # or when its centre is within this many fish lengths
FOLLOW_RESIZE = 2.5         # and its area hasn't changed by more than this factor
FOLLOW_LOST_S = 0.5         # give up after this long with no box that fits
FOLLOW_STILL_S = 3.0        # stop when the box has moved less than FOLLOW_STILL_REACH fish lengths in
FOLLOW_STILL_REACH = 0.5    # this long: the "Barely moves" rule, since that is usually a mark on the lens
FOLLOW_CUT = 0.1            # two frames in a row that differ by this share of their brightness are a scene
                            # cut. Inside one scene the Galway clips stay under 0.02, and a wipe reaches 0.3.
FOLLOW_MAX_S = 5            # follow at most this long each way: a person waits less, and in a school the
                            # box has less time to slip onto a neighbour
FOLLOW_CHUNK_S = 2          # seconds of video decoded at a time

VISIBILITY = ("<0.5 m", "0.5-1.0 m", "1.0-1.5 m", ">1.5 m")  # the protocol's four categories
SNAPSHOT_PEAKS = 5
SNAPSHOT_PEAK_GAP_S = 60
SNAPSHOT_DOT_REACH_S = 0.5
# Analysis saves every box at or above this, far below any threshold in use, so a count threshold
# can be chosen later from saved boxes without analysing the video again.
BOX_FLOOR = 0.05
SNAPSHOT_ORDER_SEED = 42  # the benchmark's seed, so both offer a video's frames in the same order



def ensure_folders() -> None:
    """Create the data folders. Called at start-up, not on import, so importing config is free."""
    for folder in (DATA, VIDEOS, PROXIES, CROPS, FRAMES, EXPORTS, WEIGHTS, SPECIES_LIBRARY):
        folder.mkdir(parents=True, exist_ok=True)
