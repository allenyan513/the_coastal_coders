import csv
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tidecount import config, dataset, db
from tidecount.app import app

client = TestClient(app)
WIDTH, HEIGHT = 200, 100


@pytest.fixture(autouse=True)
def exports(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EXPORTS", tmp_path / "exports")
    return config.EXPORTS


def picture(path, size=(WIDTH, HEIGHT)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "navy").save(path)
    return str(path)


def add_video(video_id="v1", source_id=""):
    with db.session() as con:
        con.execute(
            "INSERT INTO videos (id, name, path, duration, width, height, status, source_id) "
            "VALUES (?, 'clip.mp4', '/nowhere.mp4', 125, ?, ?, 'Ready to review', ?)",
            (video_id, WIDTH, HEIGHT, source_id),
        )
    return video_id


def add_track(tmp_path, t=15.0, box=(0.1, 0.2, 0.2, 0.4), conf=0.9, decision=None, species=None, manual=0, crop=True, video_id="v1"):
    with db.session() as con:
        track = con.execute(
            "INSERT INTO tracks (video_id, ext_id, manual, first_t, last_t, conf) VALUES (?, 1, ?, ?, ?, ?)",
            (video_id, manual, t, t + 2, conf),
        ).lastrowid
        if crop and not manual:
            con.execute("UPDATE tracks SET crop_path = ? WHERE id = ?", (picture(tmp_path / "crops" / f"{track}.jpg", (40, 30)), track))
        con.execute("INSERT INTO detections (track_id, t, x, y, w, h, conf) VALUES (?, ?, ?, ?, ?, ?, ?)", (track, t, *box, conf))
        con.execute("INSERT INTO candidates (track_id, rank, species, common, score) VALUES (?, 0, 'Gadus morhua', 'Atlantic cod', 0.71)", (track,))
        if decision:
            con.execute("INSERT INTO decisions (track_id, state, species) VALUES (?, ?, ?)", (track, decision, species))
    return track


def add_frame(tmp_path, t=15.0, status="checked", dots=(), blind=0, kind="snapshot", video_id="v1"):
    """`dots` are (x, y, source). The frame's picture is already cached, as it is once a person has opened it."""
    with db.session() as con:
        frame = con.execute(
            "INSERT INTO school_counts (video_id, t, frame_path, kind, status, saved, total, blind) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (video_id, t, picture(tmp_path / "frames" / f"{kind}-{t}.jpg"), kind, status, len(dots) if status == "checked" else None, blind),
        ).lastrowid
        con.executemany("INSERT INTO school_dots (count_id, x, y, source) VALUES (?, ?, ?, ?)", [(frame, *d) for d in dots])
    return frame


def export(video_id="v1"):
    res = client.post(f"/api/videos/{video_id}/training-data")
    assert res.status_code == 200, res.text
    return res.json()


def coco(exports, video_id="v1"):
    return json.loads((exports / video_id / "frames" / "_annotations.coco.json").read_text())


def crop_rows(exports, video_id="v1"):
    with open(exports / video_id / "crops" / "crops.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_a_kept_ai_dot_exports_its_box_in_pixels(tmp_path, exports):
    add_video()
    track = add_track(tmp_path, box=(0.1, 0.2, 0.2, 0.4), decision="Confirmed", species="Atlantic cod")
    add_frame(tmp_path, dots=[(0.2, 0.4, "ai")])

    manifest = export()
    data = coco(exports)

    assert manifest["frames"]["counted"] == 1 and manifest["frames"]["boxes"] == 1
    assert data["images"] == [{
        "id": 0, "file_name": "snapshot-00015.000.jpg", "width": WIDTH, "height": HEIGHT, "t": 15.0,
        "kind": "snapshot", "blind": False, "fish": 1, "fish_without_box": 0,
    }]
    [box] = data["annotations"]
    assert box["bbox"] == pytest.approx([20, 20, 40, 40])
    assert (box["category_id"], box["track_id"], box["species"]) == (0, track, "Atlantic cod")
    assert (exports / "v1" / "frames" / "snapshot-00015.000.jpg").is_file()


def test_a_box_whose_dot_was_removed_is_not_a_label(tmp_path, exports):
    add_video()
    add_track(tmp_path, box=(0.1, 0.2, 0.2, 0.4))
    add_track(tmp_path, box=(0.6, 0.2, 0.2, 0.4))
    add_frame(tmp_path, dots=[(0.7, 0.4, "ai")])  # the person kept the second fish and removed the first

    export()

    [box] = coco(exports)["annotations"]
    assert box["bbox"] == pytest.approx([120, 20, 40, 40])


def test_a_fish_ai_missed_is_a_point_and_marks_the_frame_incomplete(tmp_path, exports):
    add_video()
    add_track(tmp_path, box=(0.1, 0.2, 0.2, 0.4))
    add_frame(tmp_path, dots=[(0.2, 0.4, "ai"), (0.9, 0.9, "user")])

    manifest = export()
    data = coco(exports)

    assert manifest["frames"]["fish_without_box"] == 1
    assert data["images"][0]["fish"] == 2 and data["images"][0]["fish_without_box"] == 1
    assert len(data["annotations"]) == 1
    assert data["fish_without_box"] == [{"image_id": 0, "x": pytest.approx(180), "y": pytest.approx(90)}]


def test_a_blind_dot_inside_an_ai_box_confirms_that_box(tmp_path, exports):
    add_video()
    add_track(tmp_path, box=(0.1, 0.2, 0.2, 0.4))
    add_frame(tmp_path, dots=[(0.25, 0.5, "user")], blind=1)

    manifest = export()

    assert manifest["frames"]["blind"] == 1
    assert len(coco(exports)["annotations"]) == 1 and coco(exports)["fish_without_box"] == []


def test_two_fish_in_one_box_leave_one_without_a_box(tmp_path, exports):
    add_video()
    add_track(tmp_path, box=(0.1, 0.2, 0.2, 0.4))
    add_frame(tmp_path, dots=[(0.2, 0.4, "ai"), (0.22, 0.45, "user")])

    export()

    assert len(coco(exports)["annotations"]) == 1 and len(coco(exports)["fish_without_box"]) == 1


def test_an_ai_dot_confirms_its_own_box_even_under_a_surer_one(tmp_path, exports):
    add_video()
    add_track(tmp_path, box=(0.0, 0.0, 0.6, 0.8), conf=0.95)  # a false box that happens to cover the real one
    real = add_track(tmp_path, box=(0.1, 0.2, 0.2, 0.4), conf=0.5)
    add_frame(tmp_path, dots=[(0.2, 0.4, "ai")])

    export()

    assert [a["track_id"] for a in coco(exports)["annotations"]] == [real]


def test_an_empty_counted_frame_is_exported_and_other_frames_are_not(tmp_path, exports):
    add_video()
    add_frame(tmp_path, t=15.0)
    add_frame(tmp_path, t=45.0, status="could_not_see")
    add_frame(tmp_path, t=75.0, status="")

    manifest = export()

    assert [i["t"] for i in coco(exports)["images"]] == [15.0]
    assert manifest["frames"] == {
        "counted": 1, "empty": 1, "blind": 0, "boxes": 0, "fish_without_box": 0,
        "could_not_see": 1, "unreadable": 0, "not_counted": 1,
    }


def test_a_frame_whose_picture_cannot_be_read_is_skipped(tmp_path, exports):
    add_video()
    frame = add_frame(tmp_path, t=15.0)
    add_frame(tmp_path, t=45.0)
    with db.session() as con:
        con.execute("UPDATE school_counts SET frame_path = ? WHERE id = ?", (str(tmp_path / "gone.jpg"), frame))

    manifest = export()

    assert manifest["frames"]["unreadable"] == 1 and manifest["frames"]["counted"] == 1


def test_crops_carry_the_persons_label_and_skip_undecided_tracks(tmp_path, exports):
    add_video()
    cod = add_track(tmp_path, t=1, decision="Confirmed", species="Atlantic cod")
    other = add_track(tmp_path, t=2, decision="Corrected", species="Pollock")
    rock = add_track(tmp_path, t=3, decision="Rejected")
    add_track(tmp_path, t=4)  # still only a suggestion
    add_track(tmp_path, t=5, decision="Corrected", species="Fish, unidentified", manual=1)
    add_track(tmp_path, t=6, decision="Confirmed", species="Atlantic cod", crop=False)

    manifest = export()
    rows = crop_rows(exports)

    assert [(int(r["track_id"]), r["label"], r["state"]) for r in rows] == [
        (cod, "Atlantic cod", "Confirmed"), (other, "Pollock", "Corrected"), (rock, "Not a fish", "Rejected"),
    ]
    assert rows[0]["ai_suggestion"] == "Atlantic cod" and float(rows[0]["ai_score"]) == pytest.approx(0.71)
    assert all((exports / "v1" / "crops" / r["file"]).is_file() for r in rows)
    assert manifest["crops"] == {
        "exported": 3, "not_a_fish": 1, "labels": {"Atlantic cod": 1, "Pollock": 1, "Not a fish": 1},
        "added_by_hand": 1, "no_picture": 1, "undecided": 1,
    }


def test_the_manifest_matches_the_folder_and_names_the_footage(tmp_path, exports):
    add_video("run2", source_id="v1")
    add_track(tmp_path, decision="Confirmed", species="Atlantic cod", video_id="run2")
    add_frame(tmp_path, dots=[(0.2, 0.4, "ai")], video_id="run2")

    reply = export("run2")
    saved = json.loads((exports / "run2" / "manifest.json").read_text())

    assert reply == {**saved, "folder": str(exports / "run2")}
    assert saved["video"]["footage"] == "v1" and saved["format"] == dataset.FORMAT


def test_a_second_export_replaces_the_first(tmp_path, exports):
    add_video()
    track = add_track(tmp_path, decision="Confirmed", species="Atlantic cod")
    export()
    client.delete(f"/api/tracks/{track}/decision")  # the person takes the decision back
    add_frame(tmp_path)

    export()

    assert crop_rows(exports) == [] and not list((exports / "v1" / "crops").glob("*.jpg"))
    assert not (exports / "v1.part").exists()


def test_nothing_decided_gives_a_plain_refusal_and_no_folder(tmp_path, exports):
    add_video()
    add_track(tmp_path)

    res = client.post("/api/videos/v1/training-data")

    assert res.status_code == 409 and "Nothing to export" in res.json()["detail"]
    assert not (exports / "v1").exists() and not (exports / "v1.part").exists()


def test_the_frames_load_with_a_standard_coco_reader(tmp_path, exports):
    reader = pytest.importorskip("pycocotools.coco")
    add_video()
    add_track(tmp_path, box=(0.1, 0.2, 0.2, 0.4))
    add_frame(tmp_path, dots=[(0.2, 0.4, "ai"), (0.9, 0.9, "user")])
    export()

    data = reader.COCO(str(exports / "v1" / "frames" / "_annotations.coco.json"))

    assert len(data.getImgIds()) == 1 and len(data.getAnnIds()) == 1
    assert data.loadCats(data.getCatIds())[0]["name"] == "fish"
