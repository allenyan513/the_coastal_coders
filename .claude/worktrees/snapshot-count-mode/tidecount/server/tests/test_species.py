import numpy as np

from fastapi.testclient import TestClient

from tidecount import db, models, tracking
from tidecount.app import app

client = TestClient(app)


def test_keeps_fish_with_no_class_in_the_list():
    species = models.species_list()
    names = {s["species"] for s in species}
    assert len(species) == 182
    assert "Myoxocephalus aenaeus" in names  # a blank class in the file
    assert "Salvelinus fontinalis" in names


def test_prompt_uses_both_names_when_there_are_two():
    brook = {"species": "Salvelinus fontinalis", "common": "Brook Trout"}
    assert models.species_prompt(brook) == "a photo of Salvelinus fontinalis with common name Brook Trout"
    only_one = {"species": "Ammodytes marinus", "common": "Ammodytes marinus"}
    assert models.species_prompt(only_one) == "a photo of Ammodytes marinus"


def test_crop_comes_from_the_original_frame():
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[200:400, 400:800] = 255  # a 400 by 200 fish in the original

    crop = tracking.crop_for(frame, (200, 100, 400, 200), scale=2, pad=0)  # the same fish at half size

    assert crop.shape[:2] == (200, 400)
    assert crop.min() == 255


def test_crop_padding_stops_at_the_edge():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    assert tracking.crop_for(frame, (0, 0, 10, 10), scale=1).shape[:2] == (11, 11)


def test_species_endpoint_lists_the_fish_and_counts_names_people_gave():
    with db.session() as con:
        con.execute("INSERT INTO videos (id, name, path) VALUES ('v', 'v.mp4', 'v.mp4')")
        for track, state, name in [(1, "Confirmed", "Brook Trout"), (2, "Corrected", "Brook Trout"), (3, "Rejected", None)]:
            con.execute("INSERT INTO tracks (id, video_id, ext_id, first_t, last_t, conf) VALUES (?, 'v', ?, 0, 1, 0.9)", (track, track))
            con.execute("INSERT INTO decisions (track_id, state, species) VALUES (?, ?, ?)", (track, state, name))

    rows = client.get("/api/species").json()

    assert len(rows) == 182
    brook = next(r for r in rows if r["species"] == "Salvelinus fontinalis")
    assert (brook["common"], brook["group"], brook["confirmed"]) == ("Brook Trout", "Actinopterygii", 2)
    assert brook["inat_obs"] > 0
    sculpin = next(r for r in rows if r["species"] == "Myoxocephalus aenaeus")
    assert (sculpin["common"], sculpin["group"], sculpin["confirmed"]) == ("Myoxocephalus aenaeus", "", 0)
