import json
import tomllib

import pytest
from fastapi.testclient import TestClient

from tidecount import config, db, settings, video, worker
from tidecount.app import app

client = TestClient(app)
REAL_FILE = config.ROOT / "settings.toml"


def write(tmp_path, text):
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def test_the_committed_file_is_valid():
    assert settings.load(REAL_FILE).version == 1


def test_the_committed_file_names_every_setting():
    """Nothing in it should silently fall back to a default in the code."""
    raw = tomllib.loads(REAL_FILE.read_text())
    assert set(raw) == set(settings.Settings.model_fields) - {"detector"}
    for name, value in raw.items():
        if isinstance(value, dict):
            assert set(value) == set(getattr(settings.Settings(), name).__class__.model_fields)


def test_a_missing_file_means_the_defaults(tmp_path):
    assert settings.load(tmp_path / "none.toml") == settings.Settings()


def test_a_missing_field_means_its_default(tmp_path):
    loaded = settings.load(write(tmp_path, "fps = 4\n"))
    assert (loaded.fps, loaded.defaults.queue_threshold) == (4, 0.3)


@pytest.mark.parametrize("text, reason", [
    ("[defaults]\nqueue_treshold = 0.2\n", "defaults.queue_treshold"),
    ("[defaults]\nqueue_threshold = 3\n", "defaults.queue_threshold"),
    ("fps = = 2\n", "isn't valid TOML"),
    ('default_detector = "cfd-huge"\n', "unknown detector cfd-huge"),
    ("[detector.cfd-meduim]\nwidth = 0\n", "unknown detector cfd-meduim"),
    ("version = 2\n", "version"),
])
def test_a_broken_file_stops_and_says_why(tmp_path, text, reason):
    with pytest.raises(settings.SettingsError, match=reason):
        settings.load(write(tmp_path, text))


def test_a_detector_block_overrides_only_what_it_names(tmp_path):
    loaded = settings.load(write(tmp_path, "[detector.cfd-medium]\nwidth = 0\nqueue_threshold = 0.1\n"))
    chosen = loaded.for_detector("cfd-medium")
    assert (chosen.width, chosen.queue_threshold, chosen.dot_threshold) == (0, 0.1, 0.15)
    assert loaded.for_detector("cfd-nano") == loaded.defaults


def test_the_hash_changes_with_any_value(tmp_path):
    assert settings.Settings().hash() != settings.load(write(tmp_path, "fps = 4\n")).hash()


def test_a_run_reads_its_own_saved_settings():
    saved = settings.Settings(fps=5).model_dump_json()
    assert settings.for_run({"settings_json": saved}).fps == 5
    assert settings.for_run({"settings_json": ""}).fps == 2


def test_the_environment_can_pick_a_smaller_species_model(tmp_path, monkeypatch):
    monkeypatch.setenv("TIDECOUNT_SPECIES_MODEL", "small-model")
    assert settings.load(tmp_path / "none.toml").species.model == "small-model"


def test_models_marks_the_default_detector(monkeypatch):
    monkeypatch.setattr(settings, "current", lambda: settings.Settings(default_detector="cfd-small"))
    assert [m["key"] for m in client.get("/api/models").json() if m["default"]] == ["cfd-small"]


def test_import_uses_the_default_detector_when_none_is_named(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "current", lambda: settings.Settings(default_detector="cfd-small"))
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    video_id = client.post("/api/videos/import-path", json={"path": str(clip)}).json()["id"]
    assert client.get(f"/api/videos/{video_id}").json()["detector"] == "cfd-small"


def test_settings_json_stays_out_of_the_api():
    with db.session() as con:
        con.execute("INSERT INTO videos (id, name, path, settings_json) VALUES ('v1', 'c.mp4', '/n.mp4', '{}')")
    assert "settings_json" not in client.get("/api/videos").json()[0]
    assert "settings_json" not in client.get("/api/videos/v1").json()


# A whole analysis on a short clip, with a stand-in detector.


class OneBox:
    """A box on every frame. Remembers what it was asked and how wide the picture was."""

    name = "stand-in"

    def __init__(self, confidence):
        self.confidence, self.thresholds, self.widths = confidence, set(), set()

    def detect(self, image, threshold):
        import numpy as np

        self.thresholds.add(threshold)
        self.widths.add(image.width)
        return np.array([[10.0, 10.0, 100.0, 100.0]]), np.array([self.confidence])


@pytest.fixture
def clip(tmp_path):
    import subprocess

    path = tmp_path / "clip.mp4"
    subprocess.run(
        [video.FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10:duration=8",
         "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )
    return path


class OneFlash(OneBox):
    """A box on one frame only, as a false alarm often is."""

    def detect(self, image, threshold):
        import numpy as np

        self.seen = getattr(self, "seen", 0) + 1
        if self.seen == 5:
            return super().detect(image, threshold)
        return np.zeros((0, 4)), np.zeros(0)


def analyse(clip, monkeypatch, tmp_path, text, confidence=0.9, detector=None):
    from tidecount import models

    detector = detector or OneBox(confidence)
    monkeypatch.setattr(settings, "load", lambda path=None: settings.Settings(**tomllib.loads(text)))
    monkeypatch.setattr(models, "load_detector", lambda key: detector)
    monkeypatch.setattr(models, "load_suggester", lambda name: models.NullSuggester())
    monkeypatch.setattr(video, "make_proxy", lambda src, dst: dst.write_bytes(b"x"))
    monkeypatch.setattr(config, "PROXIES", tmp_path)
    monkeypatch.setattr(config, "CROPS", tmp_path)
    with db.session() as con:
        con.execute("INSERT INTO videos (id, name, path, detector) VALUES ('v1', 'clip.mp4', ?, 'cfd-medium')", (str(clip),))
    worker.run("v1")
    with db.session() as con:
        row = dict(con.execute("SELECT * FROM videos WHERE id = 'v1'").fetchone())
        tracks = con.execute("SELECT COUNT(*) AS n FROM tracks").fetchone()["n"]
    return detector, row, tracks


def test_a_run_uses_the_file_and_saves_what_it_used(clip, monkeypatch, tmp_path):
    text = "fps = 4\n[detector.cfd-medium]\nwidth = 320\nqueue_threshold = 0.2\n"
    detector, row, tracks = analyse(clip, monkeypatch, tmp_path, text)
    assert detector.thresholds == {config.BOX_FLOOR} and detector.widths == {320}  # asked for every box, and filtered after
    assert row["status"] == "Ready to review" and tracks == 1
    assert row["frames"] == 32
    saved = json.loads(row["settings_json"])
    assert (saved["fps"], saved["detector"]["cfd-medium"]["width"]) == (4, 320)
    assert row["settings_hash"] in row["notes"]


def test_width_zero_means_the_original_width(clip, monkeypatch, tmp_path):
    detector, *_ = analyse(clip, monkeypatch, tmp_path, "[defaults]\nwidth = 0\n")
    assert detector.widths == {640}


def test_start_confidence_decides_which_boxes_can_start_a_track(clip, monkeypatch, tmp_path):
    assert analyse(clip, monkeypatch, tmp_path, "", confidence=0.4)[2] == 0
    with db.session() as con:
        con.execute("DELETE FROM videos")
    assert analyse(clip, monkeypatch, tmp_path, "[tracker]\nstart_confidence = 0.3\n", confidence=0.4)[2] == 1


def active_seconds():
    with db.session() as con:
        return con.execute("SELECT COUNT(*) AS n FROM seconds WHERE detections > 0").fetchone()["n"]


def test_a_box_that_flashes_once_puts_nothing_in_the_queue(clip, monkeypatch, tmp_path):
    _, row, _ = analyse(clip, monkeypatch, tmp_path, "", detector=OneFlash(0.9))

    assert active_seconds() == 0
    assert "Flicker: 1 of 1 boxes" in row["notes"]


def test_with_the_rule_off_a_flash_still_reaches_the_queue(clip, monkeypatch, tmp_path):
    _, row, _ = analyse(clip, monkeypatch, tmp_path, "[flicker]\nneed = 0\n", detector=OneFlash(0.9))

    assert active_seconds() == 1
    assert "Flicker" not in row["notes"]


def test_a_box_on_every_frame_is_not_flicker(clip, monkeypatch, tmp_path):
    _, row, _ = analyse(clip, monkeypatch, tmp_path, "")

    assert active_seconds() == 8
    assert "Flicker: 0 of 16 boxes" in row["notes"]


def test_a_broken_file_fails_the_video_and_keeps_its_results(monkeypatch):
    def broken(path=None):
        raise settings.SettingsError("settings.toml: defaults.queue_threshold: too high")

    monkeypatch.setattr(settings, "load", broken)
    monkeypatch.setattr(worker.sys, "argv", ["worker", "v1"])
    with db.session() as con:
        con.execute("INSERT INTO videos (id, name, path, status) VALUES ('v1', 'c.mp4', '/n.mp4', 'Queued')")
        con.execute("INSERT INTO tracks (video_id, ext_id, first_t, last_t) VALUES ('v1', 1, 0, 1)")
    with pytest.raises(settings.SettingsError):
        worker.main()
    with db.session() as con:
        row = con.execute("SELECT status, error FROM videos").fetchone()
        assert row["status"] == "Failed" and "queue_threshold" in row["error"]
        assert con.execute("SELECT COUNT(*) AS n FROM tracks").fetchone()["n"] == 1


def test_an_unsure_box_is_saved_for_counting_but_stays_out_of_the_queue_and_tracks(clip, monkeypatch, tmp_path):
    _, _, tracks = analyse(clip, monkeypatch, tmp_path, "", confidence=0.2)  # under the queue threshold of 0.3
    worker.run("v1")  # a rerun replaces the boxes, so they don't double
    with db.session() as con:
        saved = dict(con.execute("SELECT COUNT(*) AS n, MIN(conf) AS low, COUNT(DISTINCT t) AS frames FROM frame_boxes WHERE video_id = 'v1'").fetchone())

    assert (tracks, active_seconds()) == (0, 0)
    assert saved == {"n": 16, "low": 0.2, "frames": 16}  # one box on each of 8 seconds at 2 frames a second
