import numpy as np

from tidecount import models, tracking


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
