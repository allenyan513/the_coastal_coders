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

SNAPSHOT_EVERY_S = 30
SNAPSHOT_START_S = 15
SNAPSHOT_PEAKS = 5
SNAPSHOT_PEAK_GAP_S = 60
SNAPSHOT_DOT_REACH_S = 0.5
# Analysis saves every box at or above this, far below any threshold in use, so a count threshold
# can be chosen later from saved boxes without analysing the video again.
BOX_FLOOR = 0.05
SNAPSHOT_ORDER_SEED = 42  # the benchmark's seed, so both offer a video's frames in the same order



def ensure_folders() -> None:
    """Create the data folders. Called at start-up, not on import, so importing config is free."""
    for folder in (DATA, VIDEOS, PROXIES, CROPS, FRAMES, EXPORTS, WEIGHTS):
        folder.mkdir(parents=True, exist_ok=True)
