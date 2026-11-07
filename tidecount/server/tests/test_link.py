from fastapi.testclient import TestClient
from pytest import approx

from tidecount import db, link
from tidecount.app import app

client = TestClient(app)

# Upper LaHave's water site in these tests. 0.009 degrees of latitude is about 1 km.
WATER = (44.37, -64.52)


def add_water_site(site_id="1", name="Upper LaHave", lat=WATER[0], lon=WATER[1]):
    with db.session() as con:
        con.execute(
            "INSERT INTO water_readings (site_id, site_name, lat, lon, date, time, measurement, value, unit) "
            "VALUES (?, ?, ?, ?, '2020-07-01', '12:00:00', 'pH', 7.5, '')",
            (site_id, name, lat, lon),
        )


def add_station(station_coords="", site_coords="", station_id="st1"):
    with db.session() as con:
        con.execute("DELETE FROM stations")  # the sample survey structure isn't needed here
        con.execute("INSERT OR REPLACE INTO sites (id, name, coordinates) VALUES ('s1', 'LaHave estuary', ?)", (site_coords,))
        con.execute("INSERT OR REPLACE INTO transects (id, site_id, name) VALUES ('t1', 's1', 'T1')")
        con.execute("INSERT INTO stations (id, transect_id, name, coordinates) VALUES (?, 't1', 'STAT1', ?)",
                    (station_id, station_coords))


def add_video(video_id="v1", station_id="st1", filmed_on="2021-07-14", source_id=""):
    with db.session() as con:
        con.execute(
            "INSERT INTO videos (id, name, path, status, station_id, filmed_on, source_id) "
            "VALUES (?, ?, '/nowhere.mp4', 'Ready to review', ?, ?, ?)",
            (video_id, f"{video_id}.mp4", station_id, filmed_on, source_id),
        )


def add_fish(first_t, last_t, species="Mummichog", state="Confirmed", video_id="v1"):
    with db.session() as con:
        track = con.execute("INSERT INTO tracks (video_id, ext_id, first_t, last_t) VALUES (?, 1, ?, ?)",
                            (video_id, first_t, last_t)).lastrowid
        if state:
            con.execute("INSERT INTO decisions (track_id, state, species) VALUES (?, ?, ?)", (track, state, species))


def rebuild():
    with db.session() as con:
        result = link.rebuild(con)
        counts = [dict(r) for r in con.execute(
            "SELECT site_id, date, species, count FROM fish_counts WHERE source = 'video' ORDER BY species")]
    return result, counts


# Reading coordinates.

def test_parse_coordinates():
    assert link.parse_coordinates("44.1, -64.7") == (44.1, -64.7)
    assert link.parse_coordinates("44.37,-64.52") == (44.37, -64.52)
    assert link.parse_coordinates("") is None
    assert link.parse_coordinates("near the bridge") is None
    assert link.parse_coordinates("44.1") is None
    assert link.parse_coordinates("95, -64.7") is None  # no latitude is above 90


def test_distance_km():
    assert link.distance_km(WATER, WATER) == 0
    assert link.distance_km((44.0, -64.5), (45.0, -64.5)) == approx(111.2, abs=0.1)  # one degree of latitude


# Linking videos to water sites.

def test_a_reviewed_video_at_a_water_site_gives_its_maxn_per_species():
    add_water_site()
    add_station(station_coords="44.371, -64.521")  # about 140 m from the water site
    add_video()
    add_fish(0, 10)
    add_fish(5, 15)  # two mummichogs on screen together
    add_fish(20, 30, species="Atlantic silverside")
    add_fish(40, 50, species=None)  # unidentified: left out

    result, counts = rebuild()

    assert counts == [
        {"site_id": "1", "date": "2021-07-14", "species": "Atlantic silverside", "count": 1},
        {"site_id": "1", "date": "2021-07-14", "species": "Mummichog", "count": 2},
    ]
    assert result["linked"][0]["site_name"] == "Upper LaHave"
    assert result["linked"][0]["km"] < 0.2


def test_a_video_filmed_somewhere_else_is_not_counted():
    add_water_site()
    add_station(station_coords="44.10, -64.70")  # about 33 km away: another place
    add_video()
    add_fish(0, 10)

    result, counts = rebuild()

    assert counts == []
    assert "no water sampling site within 1 km" in result["not_linked"][0]["reason"]


def test_just_inside_and_just_outside_the_limit():
    add_water_site()
    add_station(station_coords="44.3785, -64.52")  # about 0.95 km north
    add_video()
    add_fish(0, 10)
    assert len(rebuild()[1]) == 1

    add_station(station_coords="44.3800, -64.52")  # about 1.1 km north
    assert rebuild()[1] == []


def test_the_site_coordinates_are_used_when_the_station_has_none():
    add_water_site()
    add_station(station_coords="", site_coords="44.37, -64.52")
    add_video()
    add_fish(0, 10)

    assert len(rebuild()[1]) == 1


def test_videos_without_a_place_date_or_finished_review_wait():
    add_water_site()
    add_station(station_coords="44.37, -64.52")
    add_video("no-date", filmed_on="")
    add_video("no-station", station_id="")
    add_video("unfinished")
    add_fish(0, 10, video_id="unfinished")
    add_fish(5, 15, state=None, video_id="unfinished")  # nobody has decided on this one yet

    result, counts = rebuild()

    assert counts == []
    reasons = {n["video"]: n["reason"] for n in result["not_linked"]}
    assert reasons["no-date.mp4"] == "no station or filming date yet"
    assert reasons["no-station.mp4"] == "no station or filming date yet"
    assert reasons["unfinished.mp4"] == "review isn't finished, or no fish were confirmed"


def test_a_video_and_its_re_analysis_count_once():
    add_water_site()
    add_station(station_coords="44.37, -64.52")
    add_video("v1")
    add_video("v1-run2", source_id="v1")
    add_fish(0, 10, video_id="v1")
    add_fish(0, 10, video_id="v1-run2")
    add_fish(5, 15, video_id="v1-run2")  # the run with more confirmed fish is used

    result, counts = rebuild()

    assert counts == [{"site_id": "1", "date": "2021-07-14", "species": "Mummichog", "count": 2}]
    assert len(result["linked"]) == 1


def test_rebuilding_replaces_old_video_counts_but_keeps_demo_counts():
    add_water_site()
    add_station(station_coords="44.37, -64.52")
    add_video()
    add_fish(0, 10)
    with db.session() as con:
        con.execute("INSERT INTO fish_counts (site_id, date, species, count, source) VALUES ('1', '2020-01-01', 'Mummichog', 4, 'demo')")
    rebuild()
    with db.session() as con:
        con.execute("UPDATE videos SET filmed_on = '2022-08-01'")  # someone fixes the date

    _, counts = rebuild()

    assert [c["date"] for c in counts] == ["2022-08-01"]
    with db.session() as con:
        assert con.execute("SELECT COUNT(*) AS n FROM fish_counts WHERE source = 'demo'").fetchone()["n"] == 1


def test_the_trends_page_shows_video_counts():
    add_water_site()
    add_station(station_coords="44.37, -64.52")
    add_video()
    add_fish(0, 10)

    options = client.get("/api/fish/sites/1/options").json()
    series = client.get("/api/fish/sites/1/series?metric=total").json()

    assert options["videos"]["linked"][0]["video"] == "v1.mp4"
    assert options["species"] == ["Mummichog"]
    assert series["points"] == [{"date": "2021-07-14", "value": 1}]
    assert series["from_videos"] is True and series["demo"] is False
