"""Model adapters. The app only uses these interfaces, so a model can be swapped or missing."""
import csv
import logging
import urllib.request
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image

from . import config

log = logging.getLogger("tidecount.models")


class Detector(Protocol):
    name: str

    def detect(self, image: Image.Image, threshold: float) -> tuple[np.ndarray, np.ndarray]:
        """Return xyxy boxes in pixels and their confidence."""


class NullDetector:
    name = "none"

    def detect(self, image, threshold):
        return np.zeros((0, 4)), np.zeros(0)


def device() -> str:
    if config.DEVICE != "auto":
        return config.DEVICE
    import torch

    if torch.cuda.is_available():
        return "cuda"
    return "mps" if torch.backends.mps.is_available() else "cpu"


def available(key: str) -> tuple[bool, str]:
    spec = config.DETECTORS.get(key)
    if spec is None:
        return False, "Unknown model"
    if spec["kind"] == "yolo" and not config.ALLOW_YOLO:
        return False, "Needs TIDECOUNT_ALLOW_YOLO=1"
    return True, ""


def ensure_weights(key: str) -> Path:
    spec = config.DETECTORS[key]
    path = config.WEIGHTS / spec["file"]
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(spec["url"], tmp)
        tmp.replace(path)
    return path


class RfDetrDetector:
    def __init__(self, key: str, path: Path):
        import torch
        from rfdetr import from_checkpoint

        torch.set_num_threads(config.THREADS)
        self.name = config.DETECTORS[key]["label"]
        self.model = from_checkpoint(str(path), trust_checkpoint=False, device=device())

    def detect(self, image, threshold):
        d = self.model.predict(image, threshold=threshold)
        if not len(d):
            return np.zeros((0, 4)), np.zeros(0)
        return np.asarray(d.xyxy, dtype=float), np.asarray(d.confidence, dtype=float)


class YoloDetector:
    def __init__(self, key: str, path: Path):
        from ultralytics import YOLO

        self.name = config.DETECTORS[key]["label"]
        self.device = device()
        self.model = YOLO(str(path))

    def detect(self, image, threshold):
        boxes = self.model.predict(image, conf=threshold, device=self.device, verbose=False)[0].boxes
        return boxes.xyxy.cpu().numpy().astype(float), boxes.conf.cpu().numpy().astype(float)


def load_detector(key: str) -> Detector:
    """Load the chosen model, and fail loudly so a comparison never shows an empty result."""
    ok, why = available(key)
    if not ok:
        raise RuntimeError(f"{key}: {why}")
    path = ensure_weights(key)
    cls = RfDetrDetector if config.DETECTORS[key]["kind"] == "rfdetr" else YoloDetector
    return cls(key, path)


def species_list() -> list[dict]:
    keep = []
    with open(config.SPECIES_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            # A blank class means iNaturalist had no record. Those rows come from fish surveys.
            if row["class"] in ("Actinopterygii", "Elasmobranchii", ""):
                keep.append({"species": row["species"], "common": row["common"] or row["species"]})
    return keep


def species_prompt(entry: dict) -> str:
    """Both names, the wording that scored best on the FjordFish test."""
    if entry["common"] == entry["species"]:
        return f"a photo of {entry['species']}"
    return f"a photo of {entry['species']} with common name {entry['common']}"


class NullSuggester:
    name = "none"

    def suggest(self, crops, k=3):
        return [[] for _ in crops]


class BioClipSuggester:
    name = "BioCLIP 2.5 with the Nova Scotia species list"

    def __init__(self, model_name: str):
        import open_clip
        import torch

        self.torch = torch
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(model_name)
        tokenizer = open_clip.get_tokenizer(model_name)
        self.device = device()
        self.model.to(self.device).eval()
        self.species = species_list()
        with torch.no_grad():
            text = self.model.encode_text(tokenizer([species_prompt(s) for s in self.species]).to(self.device))
            self.text = text / text.norm(dim=-1, keepdim=True)

    def suggest(self, crops, k=3):
        out = []
        with self.torch.no_grad():
            for crop in crops:
                image = self.model.encode_image(self.preprocess(crop)[None].to(self.device))
                image = image / image.norm(dim=-1, keepdim=True)
                probs = (100 * image @ self.text.T).softmax(-1)[0]
                top = probs.topk(k)
                out.append([
                    {**self.species[int(i)], "score": float(p)}
                    for p, i in zip(top.values, top.indices)
                ])
        return out


def load_suggester(model_name: str):
    try:
        return BioClipSuggester(model_name)
    except Exception:
        log.exception("Species model failed to load, so tracks get no suggestions")
        return NullSuggester()
