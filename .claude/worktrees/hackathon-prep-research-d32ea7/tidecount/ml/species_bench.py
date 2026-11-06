"""Species suggestion bake-off on FjordFish crops (experiment E5 in issue #49).

Run from tidecount/server: uv run python ../ml/species_bench.py
Everything is seeded, and results land in tidecount/data/species_bench as JSON and markdown.
Only the milliseconds per crop change between runs.
"""

import argparse
import concurrent.futures
import csv
import hashlib
import io
import itertools
import json
import re
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image
from tqdm.auto import tqdm

ML = Path(__file__).resolve().parent
DATA = ML.parent / "data"
DATASET = DATA / "datasets" / "fjordfish"
OUT = DATA / "species_bench"
SPECIES_CSV = ML.parent / "server" / "tidecount" / "species.csv"
FAMILIES_CSV = ML / "species_families.csv"

ZIP_URL = "https://zenodo.org/api/records/17496689/files/FjordFish.zip/content"
ZIP_MD5 = "8f51ff51c3313a8183ebdc6586abc737"
ZIP_BYTES = 6091713700

MODELS = {
    "bioclip-1": "hf-hub:imageomics/bioclip",
    "bioclip-2": "hf-hub:imageomics/bioclip-2",
    "bioclip-2.5": "hf-hub:imageomics/bioclip-2.5-vith14",
}
NAMINGS = ("scientific", "common", "both")
LISTS = ("full", "short")

PADDING = 0.15  # same context around a box as worker.py
MIN_SIDE = 12  # boxes smaller than this many pixels are skipped, as in the Brackish notebooks
SEED = 42
ROUNDS = 1000  # redrawn test sets per bootstrap
DRAWS = 20  # random train and test splits per few-shot setting
SHOTS = (1, 5, 10, 20)
MIN_TEST = 5  # a species needs this many test crops in a draw to be scored
MIN_CROPS = 30  # species below this are left out of the few-shot heads
LOGISTIC_C = 10.0  # fixed in advance, because one label per class leaves nothing to tune on
LOGIT_SCALE = 100  # the app turns similarities into scores with the same factor
MARGINS = (0.0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.01)
SCENE_SIZE = (16, 9)  # images shrink to this before clustering, so fish vanish and the background stays
SCENE_DISTANCE = 1200.0  # scenes further apart than this stay separate. See scene_groups
COARSE_SCENE_DISTANCE = 1800.0  # a stricter cut, to show how much the first guess matters
CHOSEN = ("bioclip-2.5", "both")  # the setup named in the summary, shown species by species
VIDEO_SIZES = {"1920x1080", "1920x1090", "3840x2160", "2160x3840", "2448x2048", "2704x1520"}  # other sizes are stills
SIZE_BANDS = ((0, 64), (64, 128), (128, 256), (256, 1 << 20))  # shorter box side in full-resolution pixels

# FjordFish class id -> (scientific name, common name). None means the class has no species,
# so its boxes are left out. Male, female and young-of-the-year classes merge into one species.
CLASSES = {
    0: ("Labrus bergylta", "Ballan Wrasse"),
    1: ("Labrus mixtus", "Cuckoo Wrasse"),
    2: ("Labrus mixtus", "Cuckoo Wrasse"),
    3: ("Symphodus melops", "Corkwing Wrasse"),
    4: ("Symphodus melops", "Corkwing Wrasse"),
    5: ("Ctenolabrus rupestris", "Goldsinny Wrasse"),
    6: ("Centrolabrus exoletus", "Rock Cook"),
    7: None,  # labrids_unknown
    8: ("Gadus morhua", "Atlantic Cod"),
    9: ("Gadus morhua", "Atlantic Cod"),
    10: ("Melanogrammus aeglefinus", "Haddock"),
    11: ("Pollachius pollachius", "Pollack"),
    12: ("Trisopterus minutus", "Poor Cod"),
    13: ("Pollachius virens", "Saithe"),
    14: ("Merlangius merlangus", "Whiting"),
    15: None,  # gadids_unknown
    16: ("Squalus acanthias", "Spiny Dogfish"),
    18: ("Cancer pagurus", "Brown Crab"),
    19: ("Carcinus maenas", "Green Crab"),
    20: None,  # hermit crabs, labelled only to family
    21: ("Homarus gammarus", "European Lobster"),
    22: None,  # decapods_unknown
    23: ("Molva molva", "Ling"),
    24: ("Pomatoschistus flavescens", "Two-spotted Goby"),
    25: ("Gobius niger", "Black Goby"),
    26: ("Pomatoschistus minutus", "Sand Goby"),
}


# ---- Names and candidate lists ----


def prompt(naming, scientific, common):
    """The text a model compares each crop against. Species with no common name use the scientific one."""
    common = common or scientific
    if naming == "scientific":
        return f"a photo of {scientific}"
    if naming == "common":
        return f"a photo of {common}"
    if naming == "both":
        return f"a photo of {scientific} with common name {common}" if common != scientific else f"a photo of {scientific}"
    raise ValueError(naming)


def candidate_lists(app_rows, dataset_taxa):
    """Return {list name: [(scientific, common)]}. The app's name wins when both sources have a species."""
    known = {row["species"]: row["common"] for row in app_rows}
    extra = [(name, common) for name, common in dataset_taxa if name not in known]
    full = list(known.items()) + extra
    short = [(name, known.get(name) or common) for name, common in dataset_taxa]
    return {"full": full, "short": short}


def dataset_taxa():
    seen = dict(value for value in CLASSES.values() if value)
    return sorted(seen.items())


def read_app_species():
    with open(SPECIES_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_families(names):
    """Scientific name -> family, from the file in this folder, asking GBIF only for names it lacks."""
    table = {}
    if FAMILIES_CSV.exists():
        with open(FAMILIES_CSV, newline="", encoding="utf-8") as f:
            table = {row["species"]: row["family"] for row in csv.DictReader(f)}
    missing = [name for name in names if name not in table]
    for name in tqdm(missing, desc="looking up families"):
        query = urllib.parse.urlencode({"name": name, "kingdom": "Animalia"})
        with urllib.request.urlopen(f"https://api.gbif.org/v1/species/match?{query}", timeout=30) as response:
            table[name] = json.load(response).get("family") or "unknown"
    if missing:
        with open(FAMILIES_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["species", "family"])
            writer.writerows(sorted(table.items()))
    return table


# ---- Data ----


def yolo_box(line, width, height):
    """Turn a YOLO label line into (class id, x1, y1, x2, y2) in pixels, clipped to the image."""
    parts = line.split()
    class_id = int(parts[0])
    cx, cy, w, h = (float(value) for value in parts[1:5])
    x1, y1 = (cx - w / 2) * width, (cy - h / 2) * height
    x2, y2 = (cx + w / 2) * width, (cy + h / 2) * height
    return class_id, max(0.0, x1), max(0.0, y1), min(float(width), x2), min(float(height), y2)


def padded(box, width, height, padding=PADDING):
    """Widen a box the way worker.py does before cutting it out."""
    x1, y1, x2, y2 = box
    pad_x, pad_y = (x2 - x1) * padding, (y2 - y1) * padding
    return (max(0, int(x1 - pad_x)), max(0, int(y1 - pad_y)), min(width, int(x2 + pad_x)), min(height, int(y2 + pad_y)))


def scene_groups(thumbs, distance=SCENE_DISTANCE):
    """Guess which images share a place or recording. FjordFish publishes no video or site ids.

    Images are clustered by how their tiny thumbnails look, wherever they sit in the file order,
    because neighbouring numbers are often different deployments and one deployment can recur.
    Complete linkage keeps a chain of slowly changing scenes from swallowing everything.
    """
    from sklearn.cluster import AgglomerativeClustering

    flat = np.asarray(thumbs, dtype=np.float32).reshape(len(thumbs), -1)
    return AgglomerativeClustering(n_clusters=None, distance_threshold=distance, linkage="complete").fit_predict(flat)


def ensure_zip():
    path = DATASET / "FjordFish.zip"
    if path.exists() and path.stat().st_size == ZIP_BYTES:
        return path
    DATASET.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    done = part.stat().st_size if part.exists() else 0
    request = urllib.request.Request(ZIP_URL, headers={"Range": f"bytes={done}-"} if done else {})
    with urllib.request.urlopen(request, timeout=60) as response, open(part, "ab" if done else "wb") as f:
        if done and response.status != 206:
            raise RuntimeError("Zenodo ignored the resume request. Delete the .part file and rerun.")
        with tqdm(total=ZIP_BYTES, initial=done, unit="B", unit_scale=True, desc="downloading FjordFish") as bar:
            while chunk := response.read(1 << 20):
                f.write(chunk)
                bar.update(len(chunk))
    digest = hashlib.md5()
    with open(part, "rb") as f, tqdm(total=ZIP_BYTES, unit="B", unit_scale=True, desc="checking download") as bar:
        while chunk := f.read(1 << 22):
            digest.update(chunk)
            bar.update(len(chunk))
    if digest.hexdigest() != ZIP_MD5:
        raise RuntimeError("FjordFish.zip does not match the checksum Zenodo publishes.")
    part.replace(path)
    return path


def prepare_crops(zip_path):
    """Cut every labelled box out of its full-resolution image, once. Reads the zip without unpacking it."""
    manifest = DATASET / "boxes.csv"
    if manifest.exists():
        with open(manifest, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    folder = DATASET / "crops"
    folder.mkdir(parents=True, exist_ok=True)
    rows, thumbs, numbers = [], [], []
    with zipfile.ZipFile(zip_path) as archive:
        members = {}
        for name in archive.namelist():
            found = re.fullmatch(r"FjordFish/images/(\d+)\.jpg", name)
            if found:
                members[int(found[1])] = name
        labels = {name for name in archive.namelist() if re.fullmatch(r"FjordFish/labels/\d+\.txt", name)}
        for number in tqdm(sorted(members), desc="cutting crops"):
            with Image.open(io.BytesIO(archive.read(members[number]))) as opened:
                image = opened.convert("RGB")
            width, height = image.size
            thumbs.append(np.asarray(image.resize(SCENE_SIZE, Image.BILINEAR)))
            numbers.append(number)
            label_name = f"FjordFish/labels/{number}.txt"
            if label_name not in labels:
                continue
            text = archive.read(label_name).decode("utf-8")
            for index, line in enumerate(line for line in text.splitlines() if line.strip()):
                class_id, *box = yolo_box(line, width, height)
                row = {"image": number, "box": index, "class_id": class_id, "species": "", "file": "", "frame": f"{width}x{height}",
                       "box_w": round(box[2] - box[0], 1), "box_h": round(box[3] - box[1], 1)}
                taxon = CLASSES.get(class_id)
                if taxon and min(row["box_w"], row["box_h"]) >= MIN_SIDE:
                    row["species"] = taxon[0]
                    row["file"] = f"{number}-{index}.jpg"
                    image.crop(padded(box, width, height)).save(folder / row["file"], quality=95)
                rows.append(row)
    np.savez(DATASET / "thumbs.npz", numbers=np.array(numbers), thumbs=np.stack(thumbs))
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with open(manifest, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---- Scoring ----


def normalise(matrix):
    return matrix / np.clip(np.linalg.norm(matrix, axis=-1, keepdims=True), 1e-12, None)


def softmax(scores):
    shifted = scores - scores.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=1, keepdims=True)


def top_k(scores, k):
    """Indices of the k highest scores per row, best first."""
    k = min(k, scores.shape[1])
    part = np.argpartition(-scores, k - 1, axis=1)[:, :k]
    order = np.argsort(np.take_along_axis(-scores, part, axis=1), axis=1)
    return np.take_along_axis(part, order, axis=1)


def hits(scores, truth, families):
    """Per crop: right in top 1, right in top 3, and top 1 in the right family. truth holds column indices."""
    best = top_k(scores, 3)
    top1 = best[:, 0] == truth
    top3 = (best == truth[:, None]).any(axis=1)
    family = np.asarray(families, dtype=object)
    same_family = (family[best[:, 0]] == family[truth]) & (family[truth] != "unknown")
    return top1, top3, same_family


def family_sum_hits(probs, truth, families):
    """Pick the family with the highest summed score, so several weak relatives can outvote one stranger."""
    family = np.asarray(families, dtype=object)
    names, index = np.unique(family.astype(str), return_inverse=True)
    totals = np.zeros((len(names), len(probs)))
    np.add.at(totals, index, probs.T)
    return (names[totals.argmax(axis=0)].astype(object) == family[truth]) & (family[truth] != "unknown")


def bootstrap(values, species, groups, rounds=ROUNDS, seed=SEED):
    """Accuracy overall, averaged across species, and per species, with 95% intervals.

    Crops from one image or recording aren't independent, so whole groups are redrawn rather than
    single crops. Pass the difference of two hit arrays to get an interval on a paired comparison.
    """
    values = np.asarray(values, dtype=float)
    names, s = np.unique(species, return_inverse=True)
    _, g = np.unique(groups, return_inverse=True)
    total = np.zeros((g.max() + 1, len(names)))
    summed = np.zeros_like(total)
    np.add.at(total, (g, s), 1)
    np.add.at(summed, (g, s), values)
    n_groups = len(total)
    weights = np.random.default_rng(seed).multinomial(n_groups, np.full(n_groups, 1 / n_groups), size=rounds)
    drawn_total, drawn_sum = weights @ total, weights @ summed
    with np.errstate(divide="ignore", invalid="ignore"):
        per_species = drawn_sum / drawn_total
    micro = drawn_sum.sum(axis=1) / drawn_total.sum(axis=1)
    macro = np.nanmean(per_species, axis=1)
    point = summed.sum(axis=0) / total.sum(axis=0)

    def interval(samples):
        low, high = np.nanpercentile(samples, [2.5, 97.5], axis=0)
        return low, high

    micro_low, micro_high = interval(micro)
    macro_low, macro_high = interval(macro)
    low, high = interval(per_species)
    return {
        "overall": {"value": float(summed.sum() / total.sum()), "low": float(micro_low), "high": float(micro_high)},
        "per_species_mean": {"value": float(point.mean()), "low": float(macro_low), "high": float(macro_high)},
        "species": {
            str(name): {"value": float(point[i]), "low": float(low[i]), "high": float(high[i]),
                        "crops": int(total[:, i].sum()), "groups": int((total[:, i] > 0).sum())}
            for i, name in enumerate(names)
        },
    }


def fallback_curve(probs, truth, families, margins=MARGINS):
    """Answer with the family whenever the top two scores are closer than the margin.

    species_share is how often a species is named, species_precision how often that name is right,
    and any_correct how often the answer is right at whichever level it was given.
    """
    best = top_k(probs, 2)
    rows = np.arange(len(probs))
    gap = probs[rows, best[:, 0]] - probs[rows, best[:, 1]]
    species_right = best[:, 0] == truth
    family_right = family_sum_hits(probs, truth, families)
    curve = []
    for margin in margins:
        named = gap >= margin
        right = np.where(named, species_right, family_right)
        curve.append({
            "margin": margin,
            "species_share": float(named.mean()),
            "species_precision": float(species_right[named].mean()) if named.any() else None,
            "family_precision": float(family_right[~named].mean()) if (~named).any() else None,
            "any_correct": float(right.mean()),
        })
    return curve


# ---- Few labels ----


def split_groups(groups, labels, species, shots, rng, tries=200):
    """Pick half the groups for labelling and half for testing, so no source lands on both sides.

    Returns train and test masks plus the species that have enough crops on both sides. It keeps
    the split that serves the most species, because rare ones sit in very few recordings.
    """
    names = np.unique(groups)
    best = None
    for _ in range(tries):
        chosen = rng.permutation(names)[: len(names) // 2]
        train = np.isin(groups, chosen)
        served = [s for s in species if (labels[train] == s).sum() >= shots and (labels[~train] == s).sum() >= MIN_TEST]
        if best is None or len(served) > len(best[2]):
            best = (train, ~train, served)
        if len(served) == len(species):
            break
    return best


def support(labels, train, species, shots, rng):
    """Nested draws: each species' first n crops are also part of its first n + k crops."""
    picked = {}
    for name in species:
        pool = np.flatnonzero(train & (labels == name))
        order = rng.permutation(pool)
        for n in shots:
            picked.setdefault(n, []).extend(order[:n])
    return {n: np.asarray(rows) for n, rows in picked.items()}


def prototype_probs(train_x, train_y, test_x, classes):
    """Average each species' labelled crops, then score by similarity to those averages."""
    prototypes = normalise(np.stack([train_x[train_y == i].mean(axis=0) for i in range(classes)]))
    return softmax(LOGIT_SCALE * test_x @ prototypes.T)


def logistic_probs(train_x, train_y, test_x, classes):
    """Fit a logistic regression, a single-layer classifier, on the frozen features."""
    from sklearn.linear_model import LogisticRegression

    head = LogisticRegression(C=LOGISTIC_C, max_iter=2000)
    head.fit(train_x, train_y)
    return head.predict_proba(test_x)


HEADS = {"prototype": prototype_probs, "logistic": logistic_probs}


def few_shot(features, labels, groups, family_of, text=None, shots=SHOTS, draws=DRAWS, seed=SEED):
    """Score the heads on random group splits. text is {species: vector} for the no-label baseline."""
    names, counts = np.unique(labels, return_counts=True)
    eligible = [str(n) for n, c in zip(names, counts) if c >= MIN_CROPS and len(set(groups[labels == n])) >= 2]
    records = []
    for draw in tqdm(range(draws), desc="few-label draws", leave=False):
        rng = np.random.default_rng([seed, draw])
        train, test, served = split_groups(groups, labels, eligible, max(shots), rng)
        if len(served) < 2:
            continue
        index = {name: i for i, name in enumerate(served)}
        families = [family_of[name] for name in served]
        rows = test & np.isin(labels, served)
        test_x, test_labels = features[rows], labels[rows]
        truth = np.array([index[name] for name in test_labels])
        picks = support(labels, train, served, shots, rng)
        cases = [(head, n) for head in HEADS for n in shots]
        results = []
        for head, n in cases:
            chosen = picks[n]
            train_y = np.array([index[name] for name in labels[chosen]])
            results.append((head, n, HEADS[head](features[chosen], train_y, test_x, len(served))))
        if text is not None:
            matrix = np.stack([text[name] for name in served])
            results.append(("text only", 0, softmax(LOGIT_SCALE * test_x @ matrix.T)))
        for head, n, probs in results:
            top1, top3, family = hits(probs, truth, families)
            records.append({
                "head": head, "shots": n, "draw": draw, "species_used": len(served), "test_crops": len(truth),
                "overall": float(top1.mean()),
                "per_species_mean": float(np.mean([top1[truth == i].mean() for i in range(len(served))])),
                "top3": float(top3.mean()), "family": float(family.mean()),
                "fallback": fallback_curve(probs, truth, families),
            })
    return eligible, records


def summarise_few_shot(records):
    out = []
    keys = sorted({(r["head"], r["shots"]) for r in records}, key=lambda key: (key[0], key[1]))
    for head, shots in keys:
        rows = [r for r in records if (r["head"], r["shots"]) == (head, shots)]
        item = {"head": head, "shots": shots, "draws": len(rows),
                "species_used": float(np.mean([r["species_used"] for r in rows]))}
        for key in ("overall", "per_species_mean", "top3", "family"):
            values = [r[key] for r in rows]
            low, high = np.percentile(values, [2.5, 97.5])
            item[key] = {"value": float(np.mean(values)), "low": float(low), "high": float(high)}
        curve = []
        for i, margin in enumerate(MARGINS):
            points = [r["fallback"][i] for r in rows]
            entry = {"margin": margin}
            for key in ("species_share", "species_precision", "family_precision", "any_correct"):
                values = [p[key] for p in points if p[key] is not None]
                entry[key] = float(np.mean(values)) if values else None
            curve.append(entry)
        item["fallback"] = curve
        out.append(item)
    return out


# ---- Model runs ----


def device():
    import torch

    return "mps" if torch.backends.mps.is_available() else "cpu"


def load_model(name):
    import open_clip

    model, _, preprocess = open_clip.create_model_and_transforms(MODELS[name])
    return model.eval(), preprocess, open_clip.get_tokenizer(MODELS[name])


def encode_images(model, preprocess, files, where, name, batch_size=48):
    import torch

    def load(file):
        with Image.open(file) as image:
            return preprocess(image.convert("RGB"))

    batches = [files[i:i + batch_size] for i in range(0, len(files), batch_size)]
    out = []
    model.to(where)
    with concurrent.futures.ThreadPoolExecutor(8) as pool, torch.no_grad():
        for batch in tqdm(batches, desc=f"{name}: encoding crops"):
            pixels = torch.stack(list(pool.map(load, batch))).to(where)
            out.append(model.encode_image(pixels).float().cpu().numpy())
    return normalise(np.concatenate(out))


def encode_text(model, tokenizer, prompts, where, batch_size=128):
    import torch

    out = []
    with torch.no_grad():
        for i in range(0, len(prompts), batch_size):
            out.append(model.encode_text(tokenizer(prompts[i:i + batch_size]).to(where)).float().cpu().numpy())
    return normalise(np.concatenate(out))


def measure_speed(model, preprocess, text, files, name, samples=40):
    """Milliseconds per crop, one at a time as the app does: resize, encode and compare, on each device."""
    import torch

    rng = np.random.default_rng(SEED)
    chosen = rng.choice(files, size=min(samples + 5, len(files)), replace=False)
    images = []
    for file in chosen:
        with Image.open(file) as image:
            images.append(image.convert("RGB"))
    speed = {}
    for where in sorted({"cpu", device()}):
        model.to(where)
        matrix = torch.as_tensor(text, device=where)
        times = []
        with torch.no_grad():
            for i, image in enumerate(tqdm(images, desc=f"{name}: speed on {where}", leave=False)):
                start = time.perf_counter()
                vector = model.encode_image(preprocess(image)[None].to(where))
                vector = vector / vector.norm(dim=-1, keepdim=True)
                (vector.float() @ matrix.T).softmax(-1).cpu()
                if where == "mps":
                    torch.mps.synchronize()
                if i >= 5:  # the first few include one-off setup
                    times.append((time.perf_counter() - start) * 1000)
        speed[where] = {"median_ms": float(np.median(times)), "p90_ms": float(np.percentile(times, 90))}
    return speed


def run_model(name, files, manifest_key, lists, families_by_list, labels, groups, splits, family_of, args):
    """All measurements for one model."""
    import torch

    where = device()
    model, preprocess, tokenizer = load_model(name)
    cache = OUT / "features" / f"{name}-{manifest_key}.npy"
    if cache.exists():
        features = np.load(cache)
    else:
        features = encode_images(model, preprocess, files, where, name)
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.save(cache, features)
    model.to(where)

    configs, texts = [], {}
    for naming, list_name in tqdm(list(itertools.product(NAMINGS, LISTS)), desc=f"{name}: scoring", leave=False):
        taxa = lists[list_name]
        text = encode_text(model, tokenizer, [prompt(naming, *taxon) for taxon in taxa], where)
        texts[naming, list_name] = text
        index = {taxon[0]: i for i, taxon in enumerate(taxa)}
        truth = np.array([index[label] for label in labels])
        scores = LOGIT_SCALE * features @ text.T
        top1, top3, family = hits(scores, truth, families_by_list[list_name])
        probs = softmax(scores)
        configs.append({
            "model": name, "naming": naming, "list": list_name, "candidates": len(taxa),
            "top1": bootstrap(top1, labels, groups, args.rounds),
            "top3": bootstrap(top3, labels, groups, args.rounds),
            "family": bootstrap(family, labels, groups, args.rounds),
            "family_summed": bootstrap(family_sum_hits(probs, truth, families_by_list[list_name]), labels, groups, args.rounds),
            "fallback": fallback_curve(probs, truth, families_by_list[list_name]),
            "_top1_hits": top1, "_family_summed_hits": family_sum_hits(probs, truth, families_by_list[list_name]),
        })

    speed = measure_speed(model, preprocess, texts["scientific", "full"], files, name)

    best = max((c for c in configs if c["list"] == "short"), key=lambda c: c["top1"]["per_species_mean"]["value"])
    short_text = dict(zip((t[0] for t in lists["short"]), texts[best["naming"], "short"]))
    blocks = []
    for split, split_on in splits.items():
        eligible, records = few_shot(features, labels, split_on, family_of, short_text, draws=args.draws)
        blocks.append({"model": name, "split": split, "text_naming": best["naming"], "species": eligible,
                       "results": summarise_few_shot(records)})
    del model
    if where == "mps":
        torch.mps.empty_cache()
    return configs, speed, blocks


# ---- Report ----


def percent(item):
    return f"{item['value'] * 100:.1f} ({item['low'] * 100:.1f} to {item['high'] * 100:.1f})"


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines


def curve_rows(curve):
    rows = []
    for point in curve:
        precision = point["species_precision"]
        family = point["family_precision"]
        rows.append((
            f"{point['margin']:.2f}", f"{point['species_share'] * 100:.0f}%",
            "-" if precision is None else f"{precision * 100:.1f}%",
            "-" if family is None else f"{family * 100:.1f}%", f"{point['any_correct'] * 100:.1f}%",
        ))
    return rows


def report(results):
    data = results["data"]
    lines = ["# Species suggestion bake-off", "", f"FjordFish crops: {data['crops']}, covering {data['species']} species, "
             f"from {data['images_with_crops']} images in {data['groups']} guessed scenes.",
             f"Left out: {data['left_out_no_species']} boxes with no species label and "
             f"{data['left_out_small']} boxes under {MIN_SIDE} pixels.",
             f"Guessing at random gives {100 / data['species']:.1f}% on the short list, and always "
             f"answering the commonest species gives {data['commonest_share'] * 100:.1f}% of crops. Always answering "
             f"{data['commonest_family']} is right at family level for {data['commonest_family_share'] * 100:.1f}% of crops.",
             "", "Percentages are followed by 95% intervals. Whole scenes are redrawn, not single crops.",
             "", "## No labels", "", "\"Mean per species\" counts every species equally, so common ones can't hide weak ones.", ""]
    rows = [(c["model"], c["naming"], f"{c['list']} ({c['candidates']})", percent(c["top1"]["overall"]),
             percent(c["top1"]["per_species_mean"]), percent(c["top3"]["per_species_mean"]),
             percent(c["family"]["overall"]), percent(c["family_summed"]["overall"])) for c in results["zero_shot"]]
    lines += table(("Model", "Names", "List", "Top-1 crops %", "Top-1 mean per species %", "Top-3 mean per species %",
                    "Family of top answer, crops %", "Family by summed scores, crops %"), rows)
    for title, key in (("Chosen setup, full list", "chosen_full"), ("Chosen setup, short list", "chosen_short")):
        c = results[key]
        lines += ["", f"### {title}: {c['model']}, {c['naming']} names", ""]
        rows = sorted(c["top1"]["species"].items(), key=lambda kv: -kv[1]["crops"])
        lines += table(("Species", "Crops", "Groups", "Top-1 %", "Top-3 %", "Family %"), [
            (name, v["crops"], v["groups"], percent(v), percent(c["top3"]["species"][name]),
             percent(c["family"]["species"][name])) for name, v in rows])
    lines += ["", "### By fish size, chosen setup", "", "Shorter side of the box in full-resolution pixels. Models take "
              "224 pixels, so anything smaller is enlarged first.", ""]
    lines += table(("List", "Box side", "Crops", "Top-1 crops %", "Family by summed scores, crops %"), [
        (r["list"], r["band"], r["crops"], percent(r["top1"]), percent(r["family_summed"])) for r in results["by_size"]])
    lines += ["", "### Video frames against still photos, chosen setup", "", "Images at the camera sizes count as "
              "video frames. The rest are mostly sharp photographs, the kind a species model may have trained on.", ""]
    lines += table(("List", "Source", "Crops", "Top-1 crops %", "Top-1 mean per species %", "Family by summed scores, crops %"), [
        (r["list"], r["source"], r["crops"], percent(r["top1"]), percent(r["top1_per_species"]), percent(r["family_summed"]))
        for r in results["by_source"]])
    lines += ["", "### Paired differences", ""]
    lines += table(("Comparison", "Top-1 mean per species, points", "Top-1 crops, points"), [
        (d["name"], f"{d['per_species_mean']['value'] * 100:+.1f} ({d['per_species_mean']['low'] * 100:+.1f} to "
                    f"{d['per_species_mean']['high'] * 100:+.1f})",
         f"{d['overall']['value'] * 100:+.1f} ({d['overall']['low'] * 100:+.1f} to {d['overall']['high'] * 100:+.1f})")
        for d in results["differences"]])
    lines += ["", "## With a few labels", "", "Short list only, since a head can only name species it was shown. "
              "Ranges are the middle 95% of the random draws.",
              "\"Scene\" keeps labelled and test crops in different guessed scenes, which is the main estimate. "
              "\"Coarse scene\" uses a stricter guess, and \"image\" only keeps them in different images, "
              "so it is an upper bound."]
    for block in results["few_shot"]:
        lines += ["", f"### {block['model']}, split by {block['split']}", "",
                  f"Species in the heads: {', '.join(block['species'])}.",
                  f"Zero labels uses {block['text_naming']} names.", ""]
        lines += table(("Head", "Labels per species", "Species used", "Top-1 crops %", "Top-1 mean per species %",
                        "Top-3 crops %", "Family crops %"), [
            (r["head"], r["shots"], f"{r['species_used']:.1f}", percent(r["overall"]), percent(r["per_species_mean"]),
             percent(r["top3"]), percent(r["family"])) for r in block["results"]])
    lines += ["", "## Falling back to the family", "", "The margin is the gap between the top two scores. "
              "Below it the suggester names only the family.", ""]
    for title, curve in results["fallback_views"]:
        lines += [f"### {title}", ""]
        lines += table(("Margin", "Answers at species level", "Species answers right", "Family answers right",
                        "Right at either level"), curve_rows(curve))
        lines.append("")
    lines += ["## Speed", "", "One crop at a time, against the full list. These numbers change from run to run.", ""]
    lines += table(("Model", "Device", "Median ms per crop", "90th percentile ms"), [
        (name, where, f"{v['median_ms']:.0f}", f"{v['p90_ms']:.0f}")
        for name, devices in results["speed"].items() for where, v in devices.items()])
    return "\n".join(lines) + "\n"


# ---- Main ----


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draws", type=int, default=DRAWS)
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    rows = prepare_crops(ensure_zip())
    kept = [row for row in rows if row["file"]]
    files = [str(DATASET / "crops" / row["file"]) for row in kept]
    labels = np.array([row["species"] for row in kept])
    images = np.array([int(row["image"]) for row in kept])
    saved = np.load(DATASET / "thumbs.npz")
    scene_of = dict(zip(saved["numbers"].tolist(), scene_groups(saved["thumbs"]).tolist()))
    groups = np.array([scene_of[number] for number in images.tolist()])
    coarse_of = dict(zip(saved["numbers"].tolist(), scene_groups(saved["thumbs"], COARSE_SCENE_DISTANCE).tolist()))
    splits = {"scene": groups, "coarse scene": np.array([coarse_of[number] for number in images.tolist()]), "image": images}
    manifest_key = hashlib.sha1("\n".join(files).encode()).hexdigest()[:10]

    # The zip lacks the boxes for classes 18 to 26, so the short list holds only species with crops.
    present = set(labels.tolist())
    lists = candidate_lists(read_app_species(), [taxon for taxon in dataset_taxa() if taxon[0] in present])
    family_of = load_families([taxon[0] for taxon in lists["full"]])
    families_by_list = {name: [family_of[taxon[0]] for taxon in taxa] for name, taxa in lists.items()}

    names, counts = np.unique(labels, return_counts=True)
    family_names, family_counts = np.unique([family_of[label] for label in labels.tolist()], return_counts=True)
    no_species = sum(1 for row in rows if int(row["class_id"]) not in CLASSES or not CLASSES[int(row["class_id"])])
    results = {
        "data": {
            "crops": len(kept), "species": len(names), "groups": len(set(groups.tolist())), "boxes_published": 6350,
            "images_with_crops": len({row["image"] for row in kept}), "boxes": len(rows),
            "left_out_no_species": no_species, "left_out_small": len(rows) - len(kept) - no_species,
            "commonest_share": float(counts.max() / counts.sum()),
            "commonest_family": str(family_names[family_counts.argmax()]),
            "commonest_family_share": float(family_counts.max() / family_counts.sum()),
            "scenes_coarse": len(set(splits["coarse scene"].tolist())),
            "crops_per_species": {str(n): int(c) for n, c in zip(names, counts)},
        },
        "settings": {"padding": PADDING, "min_side": MIN_SIDE, "seed": SEED, "rounds": args.rounds, "draws": args.draws,
                     "shots": SHOTS, "logistic_c": LOGISTIC_C, "logit_scale": LOGIT_SCALE,
                     "scene_distance": SCENE_DISTANCE, "coarse_scene_distance": COARSE_SCENE_DISTANCE},
        "zero_shot": [], "speed": {}, "few_shot": [],
    }
    for name in tqdm(MODELS, desc="models"):
        configs, speed, blocks = run_model(
            name, files, manifest_key, lists, families_by_list, labels, groups, splits, family_of, args)
        results["zero_shot"] += configs
        results["speed"][name] = speed
        results["few_shot"] += blocks

    zero = results["zero_shot"]
    find = lambda model, naming, list_name: next(
        c for c in zero if (c["model"], c["naming"], c["list"]) == (model, naming, list_name))
    chosen_full, chosen_short = find(*CHOSEN, "full"), find(*CHOSEN, "short")
    today = find("bioclip-1", "scientific", "full")

    def difference(title, a, b):
        result = bootstrap(a["_top1_hits"].astype(float) - b["_top1_hits"].astype(float), labels, groups, args.rounds)
        return {"name": title, "overall": result["overall"], "per_species_mean": result["per_species_mean"]}

    pairs = [("chosen setup on the full list against today's setup", chosen_full, today),
             ("chosen setup on the short list against the full list", chosen_short, chosen_full)]
    for list_name in LISTS:
        for naming in ("scientific", "both"):
            pairs.append((f"bioclip-2.5 against bioclip-2 ({list_name} list, {naming} names)",
                          find("bioclip-2.5", naming, list_name), find("bioclip-2", naming, list_name)))
        pairs.append((f"both names against scientific names (bioclip-2.5, {list_name} list)",
                      find("bioclip-2.5", "both", list_name), find("bioclip-2.5", "scientific", list_name)))
    results["differences"] = [difference(*pair) for pair in tqdm(pairs, desc="paired differences")]

    sides = np.array([min(float(row["box_w"]), float(row["box_h"])) for row in kept])
    results["by_size"] = []
    for config in (chosen_full, chosen_short):
        for low, high in SIZE_BANDS:
            band = (sides >= low) & (sides < high)
            results["by_size"].append({
                "list": config["list"], "band": f"{low} to {high}" if high < 1 << 20 else f"{low} and over",
                "crops": int(band.sum()),
                "top1": bootstrap(config["_top1_hits"][band], labels[band], groups[band], args.rounds)["overall"],
                "family_summed": bootstrap(config["_family_summed_hits"][band], labels[band], groups[band], args.rounds)["overall"],
            })

    is_video = np.array([row["frame"] in VIDEO_SIZES for row in kept])
    results["by_source"] = []
    for config in (chosen_full, chosen_short):
        for source, mask in (("video frames", is_video), ("still photos", ~is_video)):
            top1 = bootstrap(config["_top1_hits"][mask], labels[mask], groups[mask], args.rounds)
            results["by_source"].append({
                "list": config["list"], "source": source, "crops": int(mask.sum()), "top1": top1["overall"],
                "top1_per_species": top1["per_species_mean"],
                "family_summed": bootstrap(config["_family_summed_hits"][mask], labels[mask], groups[mask], args.rounds)["overall"],
            })

    for config in zero:
        config.pop("_top1_hits")
        config.pop("_family_summed_hits")
    results["chosen_full"], results["chosen_short"] = chosen_full, chosen_short

    views = [(f"No labels, full list: {CHOSEN[0]}, {CHOSEN[1]} names", chosen_full["fallback"]),
             (f"No labels, short list: {CHOSEN[0]}, {CHOSEN[1]} names", chosen_short["fallback"])]
    for block in results["few_shot"]:
        for item in block["results"]:
            if block["split"] == "scene" and item["head"] == "logistic" and item["shots"] in (5, 20):
                views.append((f"{block['model']}, logistic head, {item['shots']} labels per species", item["fallback"]))
    results["fallback_views"] = views

    (OUT / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    (OUT / "results.md").write_text(report(results))
    print(f"Wrote {OUT / 'results.json'} and {OUT / 'results.md'}")


if __name__ == "__main__":
    main()
