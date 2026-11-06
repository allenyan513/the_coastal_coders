"""Turn clear underwater frames into simulated tea-coloured and murky ones.

No public footage of fish in tannin water exists, so this is a stress test and a training aid.
It is not proof of how real tea water behaves, and every output says "simulated".

The physics is the underwater image formation model, in its revised form (Akkaynak and Treibitz,
CVPR 2018), applied to each colour channel c in linear light:

    I_c = J_c * exp(-D_c * z) + A_c * (1 - exp(-B_c * z))

J is the clear picture, I the simulated one, z the distance the light travels, D how fast the
scene fades, B how fast the veil of scattered light builds up, and A the colour of that veil.
Turbidity adds blur that grows with z and small bright drifting specks, randomly placed and shaped
as in the marine snow model of Sato et al. (2021). Their larger soft blobs are left out, because
no reference footage shows any.

Run from tidecount/server:

    uv run python ../ml/water.py fit                  # refit TANNIN and TURBIDITY, print them
    uv run python ../ml/water.py make                 # degraded frames and the contact sheet
    uv run python ../ml/water.py measure              # the detector table
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from tqdm.auto import tqdm

ROOT = Path(__file__).resolve().parents[1]
BANNER = "SIMULATED"
JPEG_COMMENT = b"TideCount simulated water, not real footage"

# Printed by `water.py fit`, which matches the clear frames to the real reference frames.
# direct is D, veil is B, colour is A in linear RGB, and fade is how fast the veil dims from the top
# of the frame to the bottom, as an exponent, because light dies away exponentially with depth.
TANNIN = {
    "direct": (0.976, 2.998, 5.474),
    "veil": (1.2, 1.2, 1.2),
    "colour": (0.117, 0.0782, 0.0185),
    "fade": 0.0,
}
TURBIDITY = {
    "direct": (2.989, 3.629, 10.625),
    "veil": (2.5, 2.5, 2.5),
    "colour": (0.0762, 0.117, 0.0018),
    "fade": 2.115,
}

# Medium has the reference footage's water colour. Heavy goes beyond anything we have seen.
STRENGTHS = {"light": 0.5, "medium": 1.0, "heavy": 1.75}
SHEET_FRAMES = "00045.00.jpg,01245.00.jpg,01275.00.jpg"  # holston-trout frames with fish near and far
DEPTH = "dark"  # kept over "flat", which wipes out near fish and rock that stay clear in the reference

BLUR_SIGMA = 3.0  # pixels at full turbidity and full distance, on a 720-line frame
SPECKS = 120  # particles at full turbidity, on a 1280x720 frame
DRIFT = 18.0  # pixels per second
NEAREST = 0.25  # the share of the full distance that the closest things in a depth map get


def settings() -> list[dict]:
    """Every effect at every strength, then both together at matching strengths."""
    rows = []
    for level, s in STRENGTHS.items():
        rows.append({"name": f"tannin-{level}", "tannin": s, "turbidity": 0.0})
    for level, s in STRENGTHS.items():
        rows.append({"name": f"turbidity-{level}", "tannin": 0.0, "turbidity": s})
    for level, s in STRENGTHS.items():
        rows.append({"name": f"both-{level}", "tannin": s, "turbidity": s})
    return rows


def to_linear(image: np.ndarray) -> np.ndarray:
    """Undo the camera's sRGB curve, because light adds up in linear values."""
    a = image.astype(np.float32) / 255.0
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def to_srgb(linear: np.ndarray) -> np.ndarray:
    a = np.clip(linear, 0.0, 1.0)
    a = np.where(a <= 0.0031308, a * 12.92, 1.055 * a ** (1 / 2.4) - 0.055)
    return np.round(a * 255.0).astype(np.uint8)


def luminance(linear: np.ndarray) -> np.ndarray:
    return linear @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def local_contrast(image: np.ndarray) -> float:
    """How far brightness strays from its neighbourhood's mean, as a share of that mean, averaged.

    This measures the scene detail that is left. Comparing to the local mean leaves out slow
    changes such as the veil's top-to-bottom fade, which would otherwise count as contrast. Dimming
    alone doesn't count as a loss. Morphological opening removes bright spots smaller than its
    kernel, so particles go first: they are bright dots on a dim picture, and would otherwise read
    as extra detail in the murkiest water.
    """
    size = max(3, round(image.shape[0] / 80)) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    y = cv2.morphologyEx(luminance(to_linear(image)), cv2.MORPH_OPEN, kernel)
    sigma = image.shape[0] / 40
    mean = cv2.GaussianBlur(y, (0, 0), sigma)
    spread = np.sqrt(cv2.GaussianBlur((y - mean) ** 2, (0, 0), sigma))
    return float((spread / np.maximum(mean, 1e-4)).mean())


def depth_map(linear: np.ndarray, mode: str) -> np.ndarray:
    """Distance for each pixel, from NEAREST to 1. There is no real depth in these frames.

    "flat" gives every pixel the full distance. "dark" is a dark-channel stand-in (He et al. 2009):
    open water looks like the veil in all three channels, so a pixel with one channel far below
    the veil colour has something solid in front of the water, and is treated as closer.
    """
    h, w = linear.shape[:2]
    if mode == "flat":
        return np.ones((h, w), dtype=np.float32)
    if mode != "dark":
        raise ValueError(f"Unknown depth mode: {mode}")
    small = cv2.resize(linear, (320, max(1, round(320 * h / w))), interpolation=cv2.INTER_AREA)
    kernel = np.ones((5, 5), np.uint8)
    dark = cv2.erode(small.min(axis=2), kernel)
    water = small[dark >= np.quantile(dark, 0.5)].mean(axis=0)  # typical water, so sun glare clips
    near = cv2.erode((small / np.maximum(water, 1e-3)).min(axis=2), kernel)
    near = cv2.GaussianBlur(np.clip(near, 0.0, 1.0), (0, 0), 3)
    z = cv2.resize(near, (w, h), interpolation=cv2.INTER_LINEAR)
    return NEAREST + (1.0 - NEAREST) * z


def veil_layer(colour: np.ndarray, fade: np.ndarray, h: int) -> np.ndarray:
    """Veil colour for each row. Light comes from above, so the veil dims towards the bottom."""
    y = np.linspace(0.5, -0.5, h, dtype=np.float32)[:, None, None]
    return colour * np.exp(fade * y)


def water_terms(tannin: float, turbidity: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Add the two waters' coefficients, and mix the veil colours by how much each one scatters."""
    t_veil = tannin * np.array(TANNIN["veil"], dtype=np.float32)
    m_veil = turbidity * np.array(TURBIDITY["veil"], dtype=np.float32)
    veil = t_veil + m_veil
    direct = tannin * np.array(TANNIN["direct"], dtype=np.float32) + turbidity * np.array(
        TURBIDITY["direct"], dtype=np.float32
    )
    share = t_veil / np.maximum(veil, 1e-6)
    colour = share * np.array(TANNIN["colour"], dtype=np.float32) + (1 - share) * np.array(
        TURBIDITY["colour"], dtype=np.float32
    )
    fade = share * TANNIN["fade"] + (1 - share) * TURBIDITY["fade"]
    return direct, veil, colour, fade


def blur_with_distance(linear: np.ndarray, z: np.ndarray, sigma: float) -> np.ndarray:
    """Blur that grows with distance, blended between a few fixed blur levels."""
    if sigma <= 0:
        return linear
    if z.min() == z.max():
        return cv2.GaussianBlur(linear, (0, 0), max(sigma * float(z.max()), 1e-3))
    levels = [linear] + [cv2.GaussianBlur(linear, (0, 0), sigma * i / 3) for i in (1, 2, 3)]
    position = np.clip(z, 0.0, 1.0) * 3
    low = np.minimum(position.astype(np.int32), 2)
    share = (position - low)[..., None]
    stack = np.stack(levels)
    rows, cols = np.indices(z.shape)
    return stack[low, rows, cols] * (1 - share) + stack[low + 1, rows, cols] * share


def particle_alpha(h: int, w: int, strength: float, seed: int, t: float) -> np.ndarray:
    """How much each pixel is covered by particles. The same seed and time give the same field."""
    rng = np.random.default_rng(seed)
    scale = h / 720
    count = int(round(SPECKS * strength * (h * w) / (720 * 1280)))
    start = rng.uniform((0, 0), (w, h), size=(count, 2))
    velocity = rng.normal(0, DRIFT * scale, size=(count, 2))
    where = (start + velocity * t) % (w, h)
    axes = rng.lognormal(0, 0.4, size=(count, 2)) * (1.6, 0.9) * scale
    turn = rng.uniform(0, 180, size=count)
    shine = rng.uniform(0.35, 0.95, size=count) * 255
    mask = np.zeros((h, w), dtype=np.uint8)
    for (x, y), (a, b), angle, value in zip(where, axes, turn, shine):
        centre = (int(x * 16), int(y * 16))
        size = (max(int(a * 16), 8), max(int(b * 16), 8))
        cv2.ellipse(mask, centre, size, float(angle), 0, 360, int(value), -1, cv2.LINE_AA, 4)
    return cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), 0.5 * scale)


def simulate(
    image: np.ndarray,
    tannin: float = 0.0,
    turbidity: float = 0.0,
    depth: str | None = None,
    seed: int = 0,
    t: float = 0.0,
) -> np.ndarray:
    """Return a simulated copy of an RGB frame. Size stays the same, so labels stay valid.

    tannin and turbidity are strengths, where 1 matches the reference footage. t is the frame's
    time in seconds, so particles drift between frames of one video.
    """
    if tannin == 0 and turbidity == 0:
        return image.copy()
    h = image.shape[0]
    linear = to_linear(image)
    z = depth_map(linear, depth or DEPTH)
    direct, veil, colour, fade = water_terms(tannin, turbidity)
    clear = blur_with_distance(linear, z, turbidity * BLUR_SIGMA * h / 720)
    A = veil_layer(colour, np.asarray(fade, dtype=np.float32), h)
    z3 = z[..., None]
    out = clear * np.exp(-direct * z3) + A * (1 - np.exp(-veil * z3))
    if turbidity > 0:
        alpha = particle_alpha(h, image.shape[1], turbidity, seed, t)[..., None]
        tint = colour / max(float(colour.max()), 1e-6)
        out = out * (1 - alpha) + (0.25 + 0.75 * tint) * 0.85 * alpha
    return to_srgb(out)


# Fitting to the real reference frames


TEA_WATER = (0.3, 0.55)  # the rows of the tea frames that show open water: below the mirror-like
# surface, above the sunlit riverbed
ANCHOR = 0.9  # which brightness of open water has to land on A. Near the top, or sunlit water turns red
VEIL = {"tannin": 1.2, "turbidity": 2.5}  # B, set by eye, see fit_effect


def read_frame(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


def smooth_pixels(linear: np.ndarray) -> np.ndarray:
    """Which pixels show plain water rather than objects: the flattest 30% of the picture."""
    y = cv2.GaussianBlur(luminance(linear), (0, 0), 1.5)
    edges = np.hypot(cv2.Sobel(y, cv2.CV_32F, 1, 0), cv2.Sobel(y, cv2.CV_32F, 0, 1))
    edges = cv2.GaussianBlur(edges, (0, 0), 3)
    return edges <= np.quantile(edges, 0.3)


def small_linear(path: Path) -> np.ndarray:
    return to_linear(cv2.resize(read_frame(path), (320, 180), interpolation=cv2.INTER_AREA))


def fit_effect(clear: list[Path], reference: list[Path], rows: tuple[float, float] | None, depth: str, veil: float) -> dict:
    """Fit one water to its reference frames, so strength 1 has the reference's water colour.

    A is plain water in the reference. Scattering hardly depends on colour, so all channels share
    one B, and A carries the colour. Each D then follows from B: bright open water in the clear
    frames, at its distance z, must land exactly on A, so J * exp(-D * z) = A * exp(-B * z).

    B can't be fitted, because that needs the distance to things in the reference, and the two
    scenes differ too much to compare their contrast. It is set by eye: by the reference's far
    edge of the lake bed for turbidity, and by how far back the riverbank still shows for tannin.
    """
    water, tops, bottoms = [], [], []
    for path in tqdm(reference, desc="Reading reference frames"):
        linear = small_linear(path)
        flat = smooth_pixels(linear)
        third = linear.shape[0] // 3
        start, stop = (0, linear.shape[0]) if rows is None else (int(rows[0] * 180), int(rows[1] * 180))
        water.append(linear[start:stop][flat[start:stop]])
        tops.append(linear[:third][flat[:third]])
        bottoms.append(linear[-third:][flat[-third:]])
    colour = np.median(np.concatenate(water), axis=0)
    # The veil's fade, for the lake only: the river's top third is the surface. The centres of the
    # two thirds sit two thirds of a frame apart.
    top, bottom = (luminance(np.concatenate(x)).mean() for x in (tops, bottoms))
    fade = 0.0 if rows else float(np.log(top / bottom) * 1.5)

    open_water, open_distance = [], []
    for path in tqdm(clear, desc="Reading clear frames"):
        linear = small_linear(path)
        flat = smooth_pixels(linear)
        open_water.append(linear[flat])
        open_distance.append(depth_map(linear, depth)[flat])
    clear_water = np.quantile(np.concatenate(open_water), ANCHOR, axis=0)
    z = float(np.median(np.concatenate(open_distance)))
    direct = np.maximum(np.log(clear_water / colour) / z + veil, 0.0)
    return {
        "direct": tuple(round(float(x), 3) for x in direct),
        "veil": (veil,) * 3,
        "colour": tuple(round(float(x), 4) for x in colour),
        "fade": round(fade, 3),
    }


# Writing frames and the contact sheet


def frame_time(path: Path, index: int) -> float:
    """Frames are named by their time in seconds. Fall back to the frame's position."""
    try:
        return float(path.stem)
    except ValueError:
        return float(index)


def list_frames(folder: Path) -> list[Path]:
    frames = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not frames:
        raise SystemExit(f"No frames in {folder}")
    return frames


def folder_name(setting: dict) -> str:
    return f"simulated-{setting['name']}"


def make_frames(frames: list[Path], out: Path, depth: str, seed: int) -> None:
    for setting in tqdm(settings(), desc="Settings"):
        folder = out / folder_name(setting)
        folder.mkdir(parents=True, exist_ok=True)
        for index, path in enumerate(tqdm(frames, desc=setting["name"], leave=False)):
            sim = simulate(
                read_frame(path), setting["tannin"], setting["turbidity"], depth, seed, frame_time(path, index)
            )
            Image.fromarray(sim).save(folder / f"{path.stem}.jpg", quality=95, comment=JPEG_COMMENT)
        manifest = {**setting, "simulated": True, "depth": depth, "seed": seed, "tannin_fit": TANNIN, "turbidity_fit": TURBIDITY}
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def stamp(cell: np.ndarray, text: str, colour: tuple[int, int, int]) -> np.ndarray:
    cell = cell.copy()
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(cell, (0, 0), (tw + 10, th + 10), colour, -1)
    cv2.putText(cell, text, (5, th + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return cell


def fit_cell(image: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Centre-crop to the cell's shape, then resize."""
    w, h = size
    ih, iw = image.shape[:2]
    if iw / ih > w / h:
        keep = round(ih * w / h)
        image = image[:, (iw - keep) // 2 : (iw - keep) // 2 + keep]
    else:
        keep = round(iw * h / w)
        image = image[(ih - keep) // 2 : (ih - keep) // 2 + keep]
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def contact_sheet(
    frames: list[Path],
    picks: list[str],
    out: Path,
    tea: list[Path],
    murky: list[Path],
    depth: str,
    seed: int,
    cell: tuple[int, int] = (384, 216),
) -> Path:
    """One row per setting: simulated frames on the left, real reference frames on the right."""
    chosen = [p for p in frames if p.name in picks] or frames[:: max(1, len(frames) // 3)][:3]
    position = {p: frames.index(p) for p in chosen}
    label_w = 170
    title_h = 44

    def real(paths: list[Path], index: int) -> np.ndarray:
        return stamp(fit_cell(read_frame(paths[index % len(paths)]), cell), "REAL", (40, 110, 40))

    rows = [{"name": "original", "tannin": 0.0, "turbidity": 0.0}] + settings()
    sheet = []
    for r, setting in enumerate(tqdm(rows, desc="Contact sheet")):
        cells = []
        for path in chosen:
            image = simulate(
                read_frame(path), setting["tannin"], setting["turbidity"], depth, seed, frame_time(path, position[path])
            )
            shown = fit_cell(image, cell)
            cells.append(stamp(shown, BANNER, (170, 40, 40)) if setting["name"] != "original" else stamp(shown, "CLEAR ORIGINAL", (70, 70, 70)))
        cells.append(real(murky if setting["turbidity"] and not setting["tannin"] else tea, r * 5))
        cells.append(real(murky if setting["turbidity"] else tea, r * 5 + 3))
        label = np.full((cell[1], label_w, 3), 245, dtype=np.uint8)
        words = setting["name"].split("-") + ([] if setting["name"] == "original" else ["simulated"])
        for i, word in enumerate(words):
            cv2.putText(label, word, (10, 40 + i * 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (20, 20, 20), 1, cv2.LINE_AA)
        sheet.append(np.hstack([label, *cells]))
    grid = np.vstack(sheet)
    title = np.full((title_h, grid.shape[1], 3), 255, dtype=np.uint8)
    text = f"SIMULATED water on clear frames (depth: {depth}, seed {seed}). The two right columns are REAL reference footage."
    cv2.putText(title, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (170, 40, 40), 2, cv2.LINE_AA)
    path = out / "simulated-contact-sheet.jpg"
    Image.fromarray(np.vstack([title, grid])).save(path, quality=92, comment=JPEG_COMMENT)
    return path


# Measuring the detector


def box_iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Overlap of every box in a with every box in b, from 0 to 1."""
    if not len(a) or not len(b):
        return np.zeros((len(a), len(b)))
    left = np.maximum(a[:, None, :2], b[None, :, :2])
    right = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter = np.prod(np.clip(right - left, 0, None), axis=2)
    area_a = np.prod(a[:, 2:] - a[:, :2], axis=1)
    area_b = np.prod(b[:, 2:] - b[:, :2], axis=1)
    return inter / np.maximum(area_a[:, None] + area_b[None, :] - inter, 1e-9)


def boxes_kept(original: np.ndarray, degraded: np.ndarray, iou: float = 0.5) -> int:
    """How many original boxes still have their own box in the degraded frame."""
    overlap = box_iou(original, degraded)
    kept = 0
    while overlap.size and overlap.max() >= iou:
        i, j = np.unravel_index(overlap.argmax(), overlap.shape)
        overlap[i, :] = 0
        overlap[:, j] = 0
        kept += 1
    return kept


def score_points(boxes: np.ndarray, scores: np.ndarray, points: list, width: int, height: int) -> int:
    """Count fish found. A box finds a fish when a point sits inside it, and each point is claimed once."""
    free = [(x * width, y * height) for x, y in points]
    found = 0
    for i in np.argsort(-np.asarray(scores)):
        x0, y0, x1, y1 = boxes[i]
        inside = [p for p in free if x0 <= p[0] <= x1 and y0 <= p[1] <= y1]
        if inside:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            free.remove(min(inside, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2))
            found += 1
    return found


def detect_folder(detector, folder: Path, threshold: float, desc: str) -> dict:
    found = {}
    for path in tqdm(list_frames(folder), desc=desc, leave=False):
        boxes, scores = detector.detect(Image.open(path).convert("RGB"), threshold)
        found[path.stem] = {"boxes": np.asarray(boxes, dtype=float).reshape(-1, 4).tolist(), "scores": np.asarray(scores, dtype=float).tolist()}
    return found


def summarise(found: dict, baseline: dict, labels: dict | None, size: tuple[int, int]) -> dict:
    total = sum(len(f["boxes"]) for f in found.values())
    base_total = sum(len(f["boxes"]) for f in baseline.values())
    kept = 0
    for stem, f in found.items():
        kept += boxes_kept(np.array(baseline[stem]["boxes"]).reshape(-1, 4), np.array(f["boxes"]).reshape(-1, 4))
    scores = [s for f in found.values() for s in f["scores"]]
    row = {
        "boxes": total,
        "change": total / base_total - 1 if base_total else None,
        "frames_flagged": sum(1 for f in found.values() if f["boxes"]) / max(len(found), 1),
        "kept": kept / base_total if base_total else None,
        "new": (total - kept) / total if total else 0.0,
        "median_confidence": float(np.median(scores)) if scores else None,
    }
    if labels:
        hits = fish = boxes_on_labelled = 0
        for name, entry in labels.items():
            f = found.get(Path(name).stem)
            if f is None or entry.get("status") != "labelled":
                continue
            fish += len(entry["points"])
            boxes_on_labelled += len(f["boxes"])
            hits += score_points(np.array(f["boxes"]).reshape(-1, 4), f["scores"], entry["points"], *size)
        row["recall"] = hits / fish if fish else None
        row["precision"] = hits / boxes_on_labelled if boxes_on_labelled else None
    return row


def percent(x: float | None, sign: bool = False) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:+.0f}%" if sign else f"{x * 100:.0f}%"


def table(results: dict, threshold: float, frames: int, depth: str, seed: int, labelled: tuple[int, int] | None) -> str:
    head = ["Detector", "Setting", "Local contrast", "Boxes", "Change", "Frames flagged", "Original boxes kept", "New boxes", "Median confidence"]
    if labelled:
        head += ["Recall", "Precision"]
    lines = [
        "# Simulated water: detector results",
        "",
        f"All degraded rows are simulated, not real tannin or turbid footage. {frames} frames, boxes above {threshold},"
        f" depth {depth}, seed {seed}.",
        "",
        "- **Local contrast:** scene detail left in the picture, leaving out the particles. See `local_contrast` in water.py.",
        "- **Change:** boxes against the clear original. Boxes aren't fish, so this counts false alarms too.",
        "- **Original boxes kept:** share of the clear frame's boxes that still have a box in the same place (overlap 0.5 or more).",
        "- **New boxes:** share of this row's boxes with no match in the clear frame.",
    ]
    if labelled:
        lines.append(f"- **Recall and precision:** on the {labelled[0]} labelled frames only, with {labelled[1]} fish marked.")
    lines += ["", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for key, rows in results.items():
        for name, row in rows.items():
            cells = [
                key,
                name,
                f"{row['contrast']:.3f}",
                str(row["boxes"]),
                percent(row["change"], sign=True),
                percent(row["frames_flagged"]),
                percent(row["kept"]),
                percent(row["new"]),
                "n/a" if row["median_confidence"] is None else f"{row['median_confidence']:.2f}",
            ]
            if labelled:
                cells += [percent(row.get("recall")), percent(row.get("precision"))]
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def measure(frames_dir: Path, out: Path, keys: list[str], labels_path: Path, threshold: float, depth: str, seed: int) -> Path:
    sys.path.insert(0, str(ROOT / "server"))
    from tidecount import models

    labels = json.loads(labels_path.read_text()) if labels_path.exists() else None
    if labels and not any(v.get("status") == "labelled" for v in labels.values()):
        labels = None
    width, height = Image.open(list_frames(frames_dir)[0]).size
    folders = {"original": frames_dir} | {s["name"]: out / folder_name(s) for s in settings()}
    missing = [str(p) for p in folders.values() if not p.exists()]
    if missing:
        raise SystemExit(f"Run `water.py make` first. Missing: {missing[0]}")
    contrast = {
        name: float(np.mean([local_contrast(read_frame(p)) for p in tqdm(list_frames(folder), desc=f"Contrast {name}", leave=False)]))
        for name, folder in folders.items()
    }
    results, raw = {}, {}
    for key in keys:
        detector = models.load_detector(key)
        found = {name: detect_folder(detector, folder, threshold, f"{key} {name}") for name, folder in tqdm(folders.items(), desc=key)}
        results[key] = {name: summarise(f, found["original"], labels, (width, height)) for name, f in found.items()}
        for name, row in results[key].items():
            row["contrast"] = contrast[name]
        raw[key] = found
    (out / "simulated-detector-boxes.json").write_text(json.dumps(raw))
    (out / "simulated-detector-table.json").write_text(json.dumps(results, indent=2) + "\n")
    path = out / "simulated-detector-table.md"
    marked = [v for v in (labels or {}).values() if v.get("status") == "labelled"]
    counts = (len(marked), sum(len(v["points"]) for v in marked)) if marked else None
    path.write_text(table(results, threshold, len(list_frames(frames_dir)), depth, seed, counts))
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate tea-coloured and murky water on clear frames.")
    parser.add_argument("command", choices=["fit", "make", "measure"])
    parser.add_argument("--bench", type=Path, default=ROOT / "data" / "bench", help="folder holding the benchmark videos")
    parser.add_argument("--clear", default="holston-trout", help="video to degrade")
    parser.add_argument("--frames", type=Path, help="frames to degrade, instead of the benchmark video's")
    parser.add_argument("--tea", default="ns-river-fish-2", help="real tea-water reference video")
    parser.add_argument("--murky", default="muskrat-lake", help="real murky reference video")
    parser.add_argument("--out", type=Path, help="default: data/simulated-water/<clear>")
    parser.add_argument("--depth", choices=["flat", "dark"], default=DEPTH)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--sheet-frames", default=SHEET_FRAMES, help="comma-separated frame names for the contact sheet")
    parser.add_argument("--detectors", default="cfd-medium,cfd-nano")
    parser.add_argument("--threshold", type=float, default=0.3)
    parser.add_argument("--labels", type=Path, help="default: labels.json next to the frames")
    args = parser.parse_args()

    frames_dir = args.frames or args.bench / args.clear / "frames"
    out = args.out or ROOT / "data" / "simulated-water" / args.clear
    tea = list_frames(args.bench / args.tea / "frames")
    murky = list_frames(args.bench / args.murky / "frames")
    frames = list_frames(frames_dir)

    if args.command == "fit":
        clear = frames[:: max(1, len(frames) // 25)]
        print("TANNIN =", fit_effect(clear, tea, TEA_WATER, args.depth, VEIL["tannin"]))
        print("TURBIDITY =", fit_effect(clear, murky, None, args.depth, VEIL["turbidity"]))
    elif args.command == "make":
        out.mkdir(parents=True, exist_ok=True)
        make_frames(frames, out, args.depth, args.seed)
        picks = [x for x in args.sheet_frames.split(",") if x]
        print(contact_sheet(frames, picks, out, tea, murky, args.depth, args.seed))
    else:
        labels = args.labels or frames_dir.parent / "labels.json"
        keys = args.detectors.split(",")
        print(measure(frames_dir, out, keys, labels, args.threshold, args.depth, args.seed))


if __name__ == "__main__":
    main()
