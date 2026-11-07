from fastapi.testclient import TestClient

from tidecount import db
from tidecount.app import app
from tidecount.stats import max_overlap

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

