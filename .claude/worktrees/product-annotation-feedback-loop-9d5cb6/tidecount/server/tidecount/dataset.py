"""Export what a person decided on one video as training data. The folder stays on this machine.

A person makes two kinds of statement in the app, and each becomes its own kind of label:

- A counted snapshot frame says where every fish on that frame is. That's a whole-frame label, which
  is what a detector trains on, so it goes to `frames/` with the boxes in COCO form.
- A decision on a track says what one box is: a named fish, or not a fish. It says nothing about the
  rest of the frame, so it goes to `crops/` as a picture with a label, which is what a species model
  trains on.

Only a person's answers are exported. A track nobody decided and a frame nobody counted are left out.

A dot marks a fish but has no size. So a counted fish gets a box only when an AI box sits on its dot.
A fish no AI box covers is listed under `fish_without_box` as a point, and its frame says how many
it has, so training can skip frames whose boxes are incomplete.

Nobody draws or moves a box in the app. Every box here has the place and size AI gave it, and the
person only said a fish is there. So these labels can teach a detector which of its boxes are fish
and where it missed one, but not to fit a box more tightly.

Run `python -m tidecount.dataset` from tidecount/server to export every analysed video, or name ids.
"""
import csv
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from . import config, db, snapshots, video

FORMAT = 1
FISH = {"id": 0, "name": "fish", "supercategory": "none"}  # the category ml/adapt.py trains on
NOT_A_FISH = "Not a fish"
UNIDENTIFIED = "Fish, unidentified"
CENTRE_REACH = 0.005  # an AI dot is its box's centre, so it's matched to the box this close to it
CROP_COLUMNS = ["file", "label", "state", "track_id", "first_t", "last_t", "ai_suggestion", "ai_score"]


class NothingToExport(ValueError):
    pass


def match(boxes: list[dict], dots: list[dict]) -> tuple[list[dict], list[dict]]:
    """The boxes a person's dots confirm, and the dots no box covers.

    A dot AI proposed and the person kept confirms its own box. Any other dot is claimed by the
    surest box around it, one dot per box, which is how snapshots.claimed scores AI.
    """
    free, loose, kept = list(boxes), [], []
    for dot in dots:
        own = None
        if dot["source"] == "ai":
            def apart(b):
                return max(abs(b["x"] + b["w"] / 2 - dot["x"]), abs(b["y"] + b["h"] / 2 - dot["y"]))
            own = min(free, key=apart, default=None)
            if own is not None and apart(own) > CENTRE_REACH:
                own = None
        if own is None:
            loose.append(dot)
        else:
            free.remove(own)
            kept.append(own)
    for box in free:
        for dot in loose:
            if box["x"] <= dot["x"] <= box["x"] + box["w"] and box["y"] <= dot["y"] <= box["y"] + box["h"]:
                loose.remove(dot)
                kept.append(box)
                break
    return kept, loose


def save_frame(v: dict, row: dict, dst: Path) -> bool:
    """Copy the frame the person counted on, or take it from the original video if it was never opened."""
    cached = Path(row["frame_path"] or "")
    try:
        if cached.is_file():
            shutil.copyfile(cached, dst)
        else:
            video.extract_frame(v["path"], row["t"], dst)
    except (subprocess.CalledProcessError, OSError):
        return False
    return dst.is_file()


def export_frames(con, v: dict, folder: Path) -> dict:
    rows = db.rows(con.execute(
        f"SELECT id, kind, t, status, blind, frame_path FROM school_counts WHERE video_id = ? AND {snapshots.FRAME_KINDS} ORDER BY t, kind",
        (v["id"],),
    ))
    images, annotations, points = [], [], []
    counts = {"counted": 0, "empty": 0, "blind": 0, "boxes": 0, "fish_without_box": 0,
              "could_not_see": 0, "unreadable": 0, "not_counted": 0}
    for row in rows:
        if row["status"] != "checked":
            counts["could_not_see" if row["status"] == "could_not_see" else "not_counted"] += 1
            continue
        name = f"{row['kind']}-{row['t']:09.3f}.jpg"
        if not save_frame(v, row, folder / name):
            counts["unreadable"] += 1
            continue
        with Image.open(folder / name) as picture:
            width, height = picture.size
        dots = db.rows(con.execute("SELECT x, y, source FROM school_dots WHERE count_id = ?", (row["id"],)))
        kept, loose = match(snapshots.ai_box_rows(con, v["id"], row["t"]), dots)
        image_id = len(images)
        images.append({
            "id": image_id, "file_name": name, "width": width, "height": height, "t": row["t"], "kind": row["kind"],
            "blind": bool(row["blind"]), "fish": len(dots), "fish_without_box": len(loose),
        })
        for box in kept:
            # The tracker can place a box partly off the picture.
            x1, y1 = max(0.0, box["x"]) * width, max(0.0, box["y"]) * height
            x2, y2 = min(1.0, box["x"] + box["w"]) * width, min(1.0, box["y"] + box["h"]) * height
            named = box["state"] in ("Confirmed", "Corrected") and box["species"] != UNIDENTIFIED
            annotations.append({
                "id": len(annotations), "image_id": image_id, "category_id": FISH["id"],
                "bbox": [x1, y1, x2 - x1, y2 - y1], "area": (x2 - x1) * (y2 - y1), "iscrowd": 0,
                "track_id": box["track_id"], "species": box["species"] if named else None,
            })
        points += [{"image_id": image_id, "x": dot["x"] * width, "y": dot["y"] * height} for dot in loose]
        counts["counted"] += 1
        counts["empty"] += not dots
        counts["blind"] += bool(row["blind"])
        counts["boxes"] += len(kept)
        counts["fish_without_box"] += len(loose)
    (folder / "_annotations.coco.json").write_text(json.dumps({
        "info": {"description": "Fish a person counted on TideCount snapshot frames. Each box is an AI box that a person's dot confirmed, with the place and size AI gave it."},
        "images": images,
        "annotations": annotations,
        "categories": [FISH],
        "fish_without_box": points,
    }))
    return counts


def export_crops(con, v: dict, folder: Path) -> dict:
    rows = db.rows(con.execute(
        "SELECT t.id, t.first_t, t.last_t, t.crop_path, t.manual, d.state, d.species, c.common AS ai_suggestion, c.score AS ai_score "
        "FROM tracks t JOIN decisions d ON d.track_id = t.id LEFT JOIN candidates c ON c.track_id = t.id AND c.rank = 0 "
        "WHERE t.video_id = ? ORDER BY t.first_t, t.id",
        (v["id"],),
    ))
    tracks = con.execute("SELECT COUNT(*) AS n FROM tracks WHERE video_id = ?", (v["id"],)).fetchone()["n"]
    counts = {"exported": 0, "not_a_fish": 0, "labels": {}, "added_by_hand": 0, "no_picture": 0, "undecided": tracks - len(rows)}
    with open(folder / "crops.csv", "w", newline="", encoding="utf-8") as f:
        sheet = csv.DictWriter(f, CROP_COLUMNS)
        sheet.writeheader()
        for row in rows:
            if row["manual"]:
                counts["added_by_hand"] += 1  # a click on the video, with no box to cut a picture from
                continue
            name = f"{row['id']}.jpg"
            try:
                shutil.copyfile(row["crop_path"], folder / name)
            except OSError:
                counts["no_picture"] += 1
                continue
            label = NOT_A_FISH if row["state"] == "Rejected" else row["species"] or UNIDENTIFIED
            sheet.writerow({
                "file": name, "label": label, "state": row["state"], "track_id": row["id"],
                "first_t": row["first_t"], "last_t": row["last_t"],
                "ai_suggestion": row["ai_suggestion"] or "", "ai_score": "" if row["ai_score"] is None else round(row["ai_score"], 4),
            })
            counts["exported"] += 1
            counts["not_a_fish"] += label == NOT_A_FISH
            counts["labels"][label] = counts["labels"].get(label, 0) + 1
    return counts


def export(con, v: dict) -> dict:
    """Write the folder and return its manifest. An earlier export of this video is replaced."""
    out = config.EXPORTS / v["id"]
    part = out.with_name(f"{out.name}.part")
    shutil.rmtree(part, ignore_errors=True)
    (part / "frames").mkdir(parents=True)
    (part / "crops").mkdir()
    frames = export_frames(con, v, part / "frames")
    crops = export_crops(con, v, part / "crops")
    if not frames["counted"] and not crops["exported"]:
        shutil.rmtree(part)
        raise NothingToExport("Nothing to export yet. Count some snapshot frames or decide some fish first.")
    manifest = {
        "format": FORMAT,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "video": {
            "id": v["id"], "name": v["name"], "site": v["site"], "duration": v["duration"],
            # Runs of one video show the same footage, so training and testing must split by this, not by id.
            "footage": v["source_id"] or v["id"],
            "detector": v["detector"], "settings": v["settings_hash"], "notes": v["notes"],
        },
        "frames": frames,
        "crops": crops,
    }
    (part / "manifest.json").write_text(json.dumps(manifest, indent=2))
    shutil.rmtree(out, ignore_errors=True)
    part.replace(out)
    return manifest


def main() -> None:
    config.ensure_folders()
    db.init()
    with db.session() as con:
        videos = db.rows(con.execute("SELECT * FROM videos WHERE status = 'Ready to review' ORDER BY created_at"))
        for v in videos:
            if sys.argv[1:] and v["id"] not in sys.argv[1:]:
                continue
            try:
                m = export(con, v)
            except NothingToExport:
                print(f"{v['id']}  {v['name']}: nothing decided or counted yet")
                continue
            print(f"{v['id']}  {v['name']}: {m['frames']['counted']} frames, {m['frames']['boxes']} boxes, "
                  f"{m['frames']['fish_without_box']} fish without a box, {m['crops']['exported']} crops -> {config.EXPORTS / v['id']}")


if __name__ == "__main__":
    main()
