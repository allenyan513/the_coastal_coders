"""Tests for the scoring code in species_bench.py. Run from tidecount/server with uv run pytest ../ml/test_species_bench.py"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))

import species_bench as sb


def test_prompts():
    assert sb.prompt("scientific", "Gadus morhua", "Atlantic Cod") == "a photo of Gadus morhua"
    assert sb.prompt("common", "Gadus morhua", "Atlantic Cod") == "a photo of Atlantic Cod"
    assert sb.prompt("both", "Gadus morhua", "Atlantic Cod") == "a photo of Gadus morhua with common name Atlantic Cod"


def test_prompts_without_a_common_name_use_the_scientific_one():
    assert sb.prompt("common", "Alosa fallax", "") == "a photo of Alosa fallax"
    assert sb.prompt("both", "Alosa fallax", "") == "a photo of Alosa fallax"


def test_candidate_lists_extend_the_app_list_and_keep_its_names():
    app = [{"species": "Pollachius virens", "common": "Pollock"}, {"species": "Fundulus diaphanus", "common": "Banded Killifish"}]
    taxa = [("Pollachius virens", "Saithe"), ("Molva molva", "Ling")]
    lists = sb.candidate_lists(app, taxa)
    assert lists["full"] == [("Pollachius virens", "Pollock"), ("Fundulus diaphanus", "Banded Killifish"), ("Molva molva", "Ling")]
    assert lists["short"] == [("Pollachius virens", "Pollock"), ("Molva molva", "Ling")]


def test_sexes_and_ages_merge_into_one_species():
    assert sb.CLASSES[3][0] == sb.CLASSES[4][0]
    assert sb.CLASSES[8][0] == sb.CLASSES[9][0]
    assert sb.CLASSES[7] is None
    assert len(sb.dataset_taxa()) == 19


def test_yolo_box_converts_and_clips():
    assert sb.yolo_box("5 0.5 0.5 0.2 0.4", 100, 50) == (5, 40.0, 15.0, 60.0, 35.0)
    assert sb.yolo_box("1 0.05 0.5 0.2 0.2", 100, 100)[1] == 0.0


def test_padding_matches_the_worker_and_stays_in_the_image():
    assert sb.padded((40, 40, 60, 60), 100, 100) == (37, 37, 63, 63)
    assert sb.padded((0, 0, 100, 100), 100, 100) == (0, 0, 100, 100)


def test_scene_groups_join_look_alikes_wherever_they_sit():
    dark, light = np.zeros((9, 16, 3)), np.full((9, 16, 3), 200.0)
    groups = sb.scene_groups(np.stack([dark, light, dark + 1, light - 1]))
    assert groups[0] == groups[2] and groups[1] == groups[3] and groups[0] != groups[1]


def test_top_k_is_ordered():
    scores = np.array([[0.1, 0.9, 0.5, 0.2]])
    assert sb.top_k(scores, 3).tolist() == [[1, 2, 3]]


def test_hits_at_each_level():
    scores = np.array([[0.9, 0.5, 0.1], [0.9, 0.5, 0.1], [0.9, 0.1, 0.0]])
    top1, top3, family = sb.hits(scores, np.array([0, 1, 2]), ["a", "a", "b"])
    assert top1.tolist() == [True, False, False]
    assert top3.tolist() == [True, True, True]
    assert family.tolist() == [True, True, False]


def test_unknown_family_never_counts_as_a_match():
    scores = np.array([[0.9, 0.5]])
    assert not sb.hits(scores, np.array([1]), ["unknown", "unknown"])[2][0]


def test_family_sum_lets_relatives_outvote_the_top_answer():
    probs = np.array([[0.4, 0.3, 0.3]])
    assert sb.family_sum_hits(probs, np.array([1]), ["a", "b", "b"]).tolist() == [True]
    assert sb.family_sum_hits(probs, np.array([0]), ["a", "b", "b"]).tolist() == [False]
    assert sb.family_sum_hits(probs, np.array([1]), ["a", "unknown", "unknown"]).tolist() == [False]


def test_bootstrap_point_values_and_macro():
    values = [1, 1, 1, 0]
    species = ["a", "a", "a", "b"]
    result = sb.bootstrap(values, species, [0, 1, 2, 3], rounds=200)
    assert result["overall"]["value"] == pytest.approx(0.75)
    assert result["per_species_mean"]["value"] == pytest.approx(0.5)
    assert result["species"]["a"]["crops"] == 3
    assert result["species"]["b"]["groups"] == 1


def test_bootstrap_is_seeded():
    values = np.random.default_rng(0).integers(0, 2, 100)
    species, groups = np.array(["a", "b"] * 50), np.arange(100) // 5
    assert sb.bootstrap(values, species, groups, rounds=100) == sb.bootstrap(values, species, groups, rounds=100)


def test_bootstrap_interval_widens_when_crops_share_a_source():
    values = np.repeat([0, 1], 500)
    species = np.array(["a"] * 1000)
    scattered = sb.bootstrap(values, species, np.arange(1000), rounds=300)["overall"]
    clumped = sb.bootstrap(values, species, np.repeat([0, 1], 500), rounds=300)["overall"]
    assert clumped["high"] - clumped["low"] > 5 * (scattered["high"] - scattered["low"])


def test_bootstrap_of_a_difference_is_zero_for_identical_arms():
    same = np.array([1.0, 0.0, 1.0, 1.0])
    result = sb.bootstrap(same - same, ["a", "a", "b", "b"], [0, 1, 2, 3], rounds=100)
    assert result["overall"] == {"value": 0.0, "low": 0.0, "high": 0.0}


def test_fallback_curve_ends():
    probs = np.array([[0.6, 0.3, 0.1], [0.5, 0.45, 0.05], [0.1, 0.1, 0.8]])
    truth = np.array([0, 1, 1])
    curve = sb.fallback_curve(probs, truth, ["a", "a", "b"], margins=(0.0, 0.1, 1.01))
    assert curve[0]["species_share"] == 1.0 and curve[0]["family_precision"] is None
    assert curve[0]["species_precision"] == pytest.approx(1 / 3)
    assert curve[1]["species_share"] == pytest.approx(2 / 3)
    assert curve[1]["species_precision"] == pytest.approx(1 / 2)
    assert curve[1]["family_precision"] == 1.0
    assert curve[1]["any_correct"] == pytest.approx(2 / 3)
    assert curve[2]["species_share"] == 0.0 and curve[2]["species_precision"] is None
    assert curve[2]["any_correct"] == pytest.approx(2 / 3)


def test_split_keeps_sources_apart_and_serves_species():
    groups = np.arange(100) // 10
    labels = np.array(["a", "b"] * 50)
    train, test, served = sb.split_groups(groups, labels, ["a", "b"], 5, np.random.default_rng(0))
    assert not set(groups[train]) & set(groups[test])
    assert served == ["a", "b"]


def test_split_drops_a_species_it_cannot_serve():
    groups = np.arange(100) // 10
    labels = np.array(["a"] * 95 + ["rare"] * 5)
    _, _, served = sb.split_groups(groups, labels, ["a", "rare"], 5, np.random.default_rng(0), tries=20)
    assert served == ["a"]


def test_support_is_nested_and_stays_in_train():
    labels = np.array(["a"] * 30 + ["b"] * 30)
    train = np.arange(60) % 2 == 0
    picks = sb.support(labels, train, ["a", "b"], (1, 5, 10), np.random.default_rng(0))
    assert len(picks[1]) == 2 and len(picks[5]) == 10
    assert set(picks[1]) <= set(picks[5]) <= set(picks[10])
    assert train[picks[10]].all()


def clusters(seed=0, per_class=30):
    rng = np.random.default_rng(seed)
    centres = sb.normalise(rng.normal(size=(3, 32)))
    x = sb.normalise(np.repeat(centres, per_class, axis=0) + rng.normal(scale=0.03, size=(3 * per_class, 32)))
    return x, np.repeat(np.arange(3), per_class)


@pytest.mark.parametrize("head", sorted(sb.HEADS))
def test_heads_separate_clear_clusters(head):
    x, y = clusters()
    train = np.arange(len(y)) % 3 == 0
    probs = sb.HEADS[head](x[train], y[train], x[~train], 3)
    assert probs.shape == (int((~train).sum()), 3)
    assert probs.sum(axis=1) == pytest.approx(1)
    assert (probs.argmax(axis=1) == y[~train]).mean() == 1.0


def test_few_shot_scores_every_setting_and_is_seeded():
    x, y = clusters(per_class=40)
    labels = np.array(["s0", "s1", "s2"])[y]
    groups = np.arange(len(y)) % 12
    family_of = {"s0": "f0", "s1": "f0", "s2": "f1"}
    text = {name: x[y == i].mean(axis=0) for i, name in enumerate(["s0", "s1", "s2"])}
    run = lambda: sb.few_shot(x, labels, groups, family_of, text, shots=(1, 5), draws=3)
    eligible, records = run()
    assert eligible == ["s0", "s1", "s2"]
    assert {(r["head"], r["shots"]) for r in records} == {
        ("prototype", 1), ("prototype", 5), ("logistic", 1), ("logistic", 5), ("text only", 0)}
    assert all(r["overall"] > 0.9 for r in records)
    assert records == run()[1]
    summary = sb.summarise_few_shot(records)
    assert len(summary) == 5 and all(item["draws"] == 3 for item in summary)
