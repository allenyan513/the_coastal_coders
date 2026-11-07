"""Values an experiment may change, read from settings.toml.

A missing file means the defaults below. A broken file raises SettingsError, so nobody runs a demo
on values they didn't mean to use. It's a ValueError, not SystemExit, so the worker marks the video
Failed instead of leaving it queued and retrying forever.
"""
import hashlib
import logging
import os
import sys
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import config

log = logging.getLogger("tidecount.settings")
PATH = Path(os.environ.get("TIDECOUNT_SETTINGS", config.ROOT / "settings.toml"))


class SettingsError(ValueError):
    pass


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a misspelt key is an error, not a silent default


class DetectorSettings(Strict):
    width: int = Field(960, ge=0)
    queue_threshold: float = Field(0.3, gt=0, lt=1)
    dot_threshold: float = Field(0.15, gt=0, lt=1)
    freeze_threshold: float = Field(0.25, gt=0, lt=1)


class DetectorOverride(Strict):
    width: int | None = Field(None, ge=0)
    queue_threshold: float | None = Field(None, gt=0, lt=1)
    dot_threshold: float | None = Field(None, gt=0, lt=1)
    freeze_threshold: float | None = Field(None, gt=0, lt=1)


class Tracker(Strict):
    start_confidence: float = Field(0.5, gt=0, lt=1)
    lost_track_buffer: int = Field(60, ge=0)
    min_consecutive: int = Field(2, ge=1)
    min_points: int = Field(2, ge=1)


class Still(Strict):
    min_seconds: float = Field(3.0, gt=0)
    reach: float = Field(0.5, gt=0)


class Flicker(Strict):
    reach_s: float = Field(2.0, gt=0)
    need: int = Field(2, ge=0)
    nearby: float = Field(0.1, gt=0, le=1)


class Queue(Strict):
    merge_gap_s: int = Field(3, ge=0)
    min_segment_s: int = Field(4, ge=1)
    max_segment_s: int = Field(45, ge=1)
    quiet_chunk_s: int = Field(20, ge=1)
    audit_share: float = Field(0.10, ge=0, le=1)
    dense_detections: int = Field(8, ge=1)


class Species(Strict):
    model: str = "hf-hub:imageomics/bioclip-2.5-vith14"
    min_side: int = Field(64, ge=0)
    top_k: int = Field(3, ge=1)


class Protocol(Strict):
    """Coastal Action's fish video analysis procedure, which is still a draft, so none of this is fixed."""
    trim_start_s: int = Field(60, ge=0)    # footage dropped at the start while sediment settles
    trim_end_s: int = Field(60, ge=0)
    window_s: int = Field(900, ge=1)       # how much footage is analysed
    every_s: int = Field(60, ge=1)         # one sub-sample point this often
    context_s: int = Field(5, ge=1, le=30)  # seconds a person watches either side of a point
    clear_share: float = Field(0.5, gt=0, le=1)  # footage this far below the video's usual clarity is too murky
    clear_for_s: int = Field(120, ge=1)    # the suggested start needs this long of clear footage after it


class Settings(Strict):
    version: Literal[1] = 1
    default_detector: str = "cfd-nano"
    fps: int = Field(2, ge=1, le=30)
    defaults: DetectorSettings = DetectorSettings()
    detector: dict[str, DetectorOverride] = {}
    tracker: Tracker = Tracker()
    still: Still = Still()
    flicker: Flicker = Flicker()
    queue: Queue = Queue()
    species: Species = Species()
    protocol: Protocol = Protocol()

    @model_validator(mode="after")
    def detectors_exist(self):
        for key in (self.default_detector, *self.detector):
            if key not in config.DETECTORS:
                raise ValueError(f"unknown detector {key}")
        return self

    def for_detector(self, key: str) -> DetectorSettings:
        chosen = self.detector.get(key)
        return self.defaults.model_copy(update=chosen.model_dump(exclude_none=True)) if chosen else self.defaults

    def hash(self) -> str:
        """A short name for these exact values, saved with each run and shown in its notes."""
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:8]


def load(path: Path | None = None) -> Settings:
    path = path or PATH
    raw = {}
    if path.exists():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise SettingsError(f"{path.name} isn't valid TOML: {exc}") from exc
    else:
        log.warning("%s is missing, so analysis uses the built-in defaults", path)
    try:
        settings = Settings(**raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(map(str, first["loc"]))
        raise SettingsError(f"{path.name}: {where + ': ' if where else ''}{first['msg']}") from exc
    # A slower machine can pick a smaller species model without editing the shared file.
    settings.species.model = os.environ.get("TIDECOUNT_SPECIES_MODEL", settings.species.model)
    return settings


@lru_cache
def current() -> Settings:
    """The API's settings, read once when it starts. The worker calls load() for each run."""
    return load()


def for_run(video: dict) -> Settings:
    """The settings a video was analysed with. Runs from before this file used the defaults."""
    return Settings.model_validate_json(video["settings_json"]) if video.get("settings_json") else Settings()


if __name__ == "__main__":
    try:
        print(f"OK, settings {load().hash()}")
    except SettingsError as exc:
        sys.exit(str(exc))
