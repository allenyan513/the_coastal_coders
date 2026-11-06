import cv2
import numpy as np
import pytest

import water


@pytest.fixture
def frame():
    """A textured picture of green water, with no real footage needed."""
    rng = np.random.default_rng(1)
    noise = cv2.GaussianBlur(rng.random((180, 320)).astype(np.float32), (0, 0), 6)
    noise = (noise - noise.min()) / (noise.max() - noise.min())
    base = np.stack([noise * 90 + 20, noise * 170 + 40, noise * 150 + 35], axis=2)
    return base.astype(np.uint8)


EFFECTS = [
    pytest.param({"tannin": 1.0}, id="tannin"),
    pytest.param({"turbidity": 1.0}, id="turbidity"),
    pytest.param({"tannin": 1.0, "turbidity": 1.0}, id="both"),
]


@pytest.mark.parametrize("depth", ["flat", "dark"])
@pytest.mark.parametrize("effect", EFFECTS)
def test_same_seed_gives_same_output(frame, effect, depth):
    a = water.simulate(frame, depth=depth, seed=7, t=30.0, **effect)
    b = water.simulate(frame, depth=depth, seed=7, t=30.0, **effect)
    assert np.array_equal(a, b)


def test_seed_and_time_move_the_particles(frame):
    start = water.simulate(frame, turbidity=1.0, seed=7, t=0.0)
    assert not np.array_equal(start, water.simulate(frame, turbidity=1.0, seed=8, t=0.0))
    assert not np.array_equal(start, water.simulate(frame, turbidity=1.0, seed=7, t=30.0))


@pytest.mark.parametrize("depth", ["flat", "dark"])
@pytest.mark.parametrize("effect", EFFECTS)
@pytest.mark.parametrize("shape", [(180, 320, 3), (181, 323, 3), (720, 1280, 3)])
def test_size_never_changes(effect, depth, shape):
    image = np.full(shape, 90, dtype=np.uint8)
    out = water.simulate(image, depth=depth, **effect)
    assert out.shape == shape
    assert out.dtype == np.uint8


def falling_contrast(image, effect, depth):
    """Contrast at no water, then at each strength, for one effect."""
    contrast = [water.local_contrast(image)]
    for strength in water.STRENGTHS.values():
        scaled = {k: v * strength for k, v in effect.items()}
        contrast.append(water.local_contrast(water.simulate(image, depth=depth, seed=3, **scaled)))
    return contrast


CONTRAST_EFFECTS = [{"tannin": 1}, {"turbidity": 1}, {"tannin": 1, "turbidity": 1}]


@pytest.mark.parametrize("depth", ["flat", "dark"])
@pytest.mark.parametrize("effect", CONTRAST_EFFECTS, ids=str)
def test_contrast_falls_as_strength_rises(depth, effect):
    # Full size, because particles are scaled to the frame and must be as big as in real use.
    rng = np.random.default_rng(1)
    noise = cv2.GaussianBlur(rng.random((720, 1280)).astype(np.float32), (0, 0), 3)
    noise = (noise - noise.min()) / (noise.max() - noise.min())
    dark_lower_half = np.linspace(1.0, 0.25, 720, dtype=np.float32)[:, None]
    image = (np.stack([noise * 90 + 20, noise * 170 + 40, noise * 150 + 35], axis=2) * dark_lower_half[..., None])
    contrast = falling_contrast(image.astype(np.uint8), effect, depth)
    assert contrast == sorted(contrast, reverse=True)
    assert contrast[-1] < contrast[0] * 0.9


REAL_FRAMES = water.ROOT / "data" / "bench" / "holston-trout" / "frames"


@pytest.mark.skipif(not REAL_FRAMES.exists(), reason="needs the benchmark frames")
@pytest.mark.parametrize("effect", CONTRAST_EFFECTS, ids=str)
def test_contrast_falls_on_real_frames(effect):
    frames = [water.read_frame(p) for p in water.list_frames(REAL_FRAMES)[::25]]
    runs = np.array([falling_contrast(frame, effect, water.DEPTH) for frame in frames])
    contrast = runs.mean(axis=0).tolist()
    assert contrast == sorted(contrast, reverse=True)


def test_tannin_shifts_the_picture_towards_brown(frame):
    def red_over_blue(image):
        linear = water.to_linear(image)
        return linear[..., 0].mean() / linear[..., 2].mean()

    shifts = [red_over_blue(water.simulate(frame, tannin=s)) for s in water.STRENGTHS.values()]
    assert red_over_blue(frame) < shifts[0] < shifts[1] < shifts[2]


def test_no_water_leaves_the_frame_alone(frame):
    assert np.array_equal(water.simulate(frame), frame)


def test_srgb_round_trip_is_exact():
    every = np.arange(256, dtype=np.uint8).reshape(1, 256, 1)
    assert np.array_equal(water.to_srgb(water.to_linear(every)), every)


def test_every_folder_says_simulated():
    names = [water.folder_name(s) for s in water.settings()]
    assert len(set(names)) == len(names) >= 9
    assert all(name.startswith("simulated-") for name in names)


def test_a_point_is_claimed_once_and_the_surest_box_claims_first():
    boxes = np.array([[0, 0, 100, 100], [10, 10, 90, 90], [200, 200, 300, 300]], dtype=float)
    scores = np.array([0.5, 0.9, 0.8])
    assert water.score_points(boxes, scores, [[0.05, 0.05]], 1000, 1000) == 1
    assert water.score_points(boxes, scores, [[0.05, 0.05], [0.05, 0.05]], 1000, 1000) == 2
    assert water.score_points(boxes, scores, [[0.5, 0.5]], 1000, 1000) == 0


def test_boxes_kept_matches_each_box_once():
    original = np.array([[0, 0, 10, 10], [100, 100, 110, 110]], dtype=float)
    degraded = np.array([[0, 0, 10, 10], [1, 0, 11, 10], [300, 300, 310, 310]], dtype=float)
    assert water.boxes_kept(original, degraded) == 1
    assert water.boxes_kept(original, degraded[:0]) == 0


def test_summary_reports_recall_and_precision_on_labelled_frames_only():
    box = {"boxes": [[0, 0, 100, 100], [500, 500, 600, 600]], "scores": [0.9, 0.8]}
    found = {"00015.00": box, "00045.00": box}
    labels = {
        "00015.00.jpg": {"status": "labelled", "points": [[0.05, 0.05], [0.9, 0.9]]},
        "00045.00.jpg": {"status": "unclear", "points": []},
    }
    row = water.summarise(found, found, labels, (1000, 1000))
    assert row["recall"] == 0.5
    assert row["precision"] == 0.5
    assert row["kept"] == 1.0
    assert row["new"] == 0.0
