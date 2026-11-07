import csv
import io
import math

from fastapi.testclient import TestClient
from pytest import approx

from tidecount import db
from tidecount.app import app
from tidecount.stats import max_overlap, shannon, simpson

client = TestClient(app)


def add_video(video_id="v1"):
    with db.session() as con:
        con.execute(
            "INSERT INTO videos (id, name, path, duration, status) VALUES (?, 'clip.mp4', '/nowhere.mp4', 60, 'Ready to review')",
            (video_id,),
        )


def add_fish(first_t, last_t, species="Stickleback", state="Confirmed", video_id="v1"):
    """A track seen from first_t to last_t, with a person's decision. state=None leaves it undecided."""
    with db.session() as con:
        track = con.execute(
            "INSERT INTO tracks (video_id, ext_id, first_t, last_t) VALUES (?, 1, ?, ?)", (video_id, first_t, last_t),
        ).lastrowid
        if state:
            con.execute("INSERT INTO decisions (track_id, state, species) VALUES (?, ?, ?)", (track, state, species))
    return track


def get_maxn(video_id="v1"):
    res = client.get(f"/api/videos/{video_id}/stats/maxn")
    assert res.status_code == 200
    return res.json()


# The counting rule on its own, without a database.

def test_no_fish_is_zero():
    assert max_overlap([]) == (0, None)


def test_fish_one_after_another_never_overlap():
    assert max_overlap([(0, 2), (3, 5), (6, 8)]) == (1, 0)


def test_fish_on_screen_together_are_counted_together():
    # Three fish, all on screen between 4 and 5 seconds.
    assert max_overlap([(0, 5), (2, 6), (4, 9), (10, 12)]) == (3, 4)


def test_a_fish_leaving_as_another_arrives_shares_that_frame():
    assert max_overlap([(0, 3), (3, 6)]) == (2, 3)


def test_the_earliest_moment_of_maxn_is_reported():
    assert max_overlap([(1, 2), (1, 2), (5, 6), (5, 6)]) == (2, 1)


# The endpoint, on a real (temporary) database.

def test_maxn_by_species():
    add_video()
    add_fish(0, 10, "Stickleback")
    add_fish(5, 15, "Stickleback")
    add_fish(8, 9, "Stickleback")
    add_fish(20, 30, "Eel", state="Corrected")

    s = get_maxn()

    assert s["maxn"] == 3 and s["maxn_t"] == 8
    assert s["species"] == [
        {"species": "Stickleback", "maxn": 3, "t": 8, "tracks": 3},
        {"species": "Eel", "maxn": 1, "t": 20, "tracks": 1},
    ]
    assert s["confirmed_tracks"] == 4


def test_maxn_for_all_fish_can_mix_species():
    add_video()
    add_fish(0, 10, "Stickleback")
    add_fish(2, 8, "Eel")

    s = get_maxn()

    assert s["maxn"] == 2
    assert [r["maxn"] for r in s["species"]] == [1, 1]


def test_rejected_and_undecided_tracks_never_count():
    add_video()
    add_fish(0, 10, "Stickleback")
    add_fish(0, 10, "Stickleback", state="Rejected")
    add_fish(0, 10, state=None)

    s = get_maxn()

    assert s["maxn"] == 1
    assert s["undecided_tracks"] == 1 and s["partial"] is True


def test_unidentified_fish_are_listed_last():
    add_video()
    add_fish(0, 5, "Fish, unidentified")
    add_fish(0, 5, "Fish, unidentified")
    add_fish(10, 12, "Eel")

    s = get_maxn()

    assert [r["species"] for r in s["species"]] == ["Eel", "Fish, unidentified"]
    assert s["partial"] is False


def test_other_videos_are_left_out():
    add_video("v1")
    add_video("v2")
    add_fish(0, 10, video_id="v1")
    add_fish(0, 10, video_id="v2")
    add_fish(0, 10, video_id="v2")

    assert get_maxn("v1")["maxn"] == 1


def test_a_video_with_no_decisions_has_maxn_zero():
    add_video()

    s = get_maxn()

    assert s["maxn"] == 0 and s["species"] == [] and s["snapshot_maxn"] is None


def test_unknown_video_is_404():
    assert client.get("/api/videos/nope/stats/maxn").status_code == 404


# Shannon index on its own. approx() allows for tiny rounding in decimal numbers.

def test_shannon_with_no_fish_has_no_answer():
    assert shannon([]) == (None, None)


def test_shannon_with_one_species_is_zero():
    assert shannon([5]) == (0.0, None)


def test_shannon_with_an_even_split_is_ln_of_the_species_count():
    h, j = shannon([1, 1])
    assert h == approx(math.log(2)) and j == approx(1.0)

    h, j = shannon([3, 3, 3, 3])
    assert h == approx(math.log(4)) and j == approx(1.0)


def test_shannon_with_an_uneven_split_is_lower():
    # 9 of one species and 1 of another: -(0.9 ln 0.9 + 0.1 ln 0.1) = 0.325
    h, j = shannon([9, 1])
    assert h == approx(0.325, abs=0.001) and j == approx(0.469, abs=0.001)


def test_shannon_ignores_a_species_with_no_fish():
    assert shannon([3, 0, 3]) == shannon([3, 3])


# Diversity through the endpoint.

def get_diversity(video_id="v1"):
    res = client.get(f"/api/videos/{video_id}/stats/diversity")
    assert res.status_code == 200
    return res.json()


def test_diversity_uses_each_species_maxn_and_leaves_out_unidentified():
    add_video()
    add_fish(0, 10, "Stickleback")
    add_fish(5, 15, "Stickleback")  # MaxN 2
    add_fish(20, 30, "Eel")
    add_fish(25, 35, "Eel")  # MaxN 2
    add_fish(0, 5, "Fish, unidentified")

    d = get_diversity()

    assert d["shannon"] == approx(math.log(2)) and d["evenness"] == approx(1.0)
    assert d["richness"] == 2 and d["unidentified_maxn"] == 1
    assert [r["share"] for r in d["species"]] == [0.5, 0.5]


def test_diversity_with_no_named_fish_has_no_answer():
    add_video()
    add_fish(0, 5, "Fish, unidentified")

    d = get_diversity()

    assert d["shannon"] is None and d["evenness"] is None and d["richness"] == 0 and d["species"] == []


def test_diversity_of_unknown_video_is_404():
    assert client.get("/api/videos/nope/stats/diversity").status_code == 404


def test_shannon_worked_example():
    h, j = shannon([6, 3, 1])
    assert h == approx(0.897, abs=0.001) and j == approx(0.82, abs=0.01)


def test_simpson_no_fish():
    simpson_d, inverse_d = simpson([])
    assert simpson_d is None and inverse_d is None


def test_simpson_two_species_even_split():
    simpson_d, inverse_d = simpson([5,5])
    assert simpson_d == 0.5 and inverse_d == 2


def test_simpson_two_species_uneven_split():
    simpson_d, inverse_d = simpson([9,1])
    assert simpson_d == approx(0.18, abs=0.01) and inverse_d == approx(1.22, abs=0.01)


def test_simpson_three_species():
    simpson_d, inverse_d = simpson([6,3,1])
    assert simpson_d == approx(0.54, abs=0.01) and inverse_d == approx(2.17, abs=0.01)


# The new statistics in the exported CSV.

def export_rows(video_id="v1"):
    res = client.get(f"/api/videos/{video_id}/export.csv")
    assert res.status_code == 200
    return list(csv.reader(io.StringIO(res.text)))


def test_csv_has_maxn_and_diversity():
    add_video()
    add_fish(0, 10, "Stickleback")
    add_fish(5, 15, "Stickleback")
    add_fish(20, 30, "Eel")
    add_fish(25, 35, "Eel")

    rows = export_rows()
    values = {r[0]: r[1] for r in rows if len(r) == 2}

    assert values["maxn_from_confirmed_tracks"] == "2"
    assert values["shannon_index"] == "0.693"
    assert values["shannon_evenness"] == "1.000"
    assert values["simpson_diversity"] == "0.500"
    assert values["inverse_simpson"] == "2.000"
    assert values["diversity_named_species"] == "2"
    assert ["Stickleback", "2", "5.0", "2"] in rows and ["Eel", "2", "25.0", "2"] in rows


def test_csv_leaves_missing_diversity_blank():
    add_video()
    add_fish(0, 5, "Stickleback")

    values = {r[0]: r[1] for r in export_rows() if len(r) == 2}

    assert values["maxn_from_confirmed_tracks"] == "1"
    assert values["shannon_index"] == "0.000"
    assert values["shannon_evenness"] == ""
