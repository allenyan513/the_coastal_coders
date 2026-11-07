from fastapi.testclient import TestClient
from pytest import approx

from tidecount import db, trends
from tidecount.app import app

client = TestClient(app)


def add_counts(*rows, source="demo"):
    """Each row is (site_id, date, species, count)."""
    with db.session() as con:
        con.executemany(
            "INSERT INTO fish_counts (site_id, date, species, count, source) VALUES (?, ?, ?, ?, ?)",
            [(*r, source) for r in rows],
        )


# Removing the seasonal pattern.

def test_deseasonalize_removes_a_repeating_yearly_pattern():
    # Every July is 10 higher than every January, and nothing else changes: no trend is left.
    points = [{"date": f"{y}-01-15", "value": 5.0} for y in (2020, 2021)] + \
             [{"date": f"{y}-07-15", "value": 15.0} for y in (2020, 2021)]

    out = trends.deseasonalize(points)

    assert [p["value"] for p in out] == [10.0, 10.0, 10.0, 10.0]  # all at the overall average


def test_deseasonalize_keeps_a_year_to_year_change():
    # The same seasons, but 2021 is 4 higher all year: that change must survive.
    points = [
        {"date": "2020-01-15", "value": 5.0}, {"date": "2020-07-15", "value": 15.0},
        {"date": "2021-01-15", "value": 9.0}, {"date": "2021-07-15", "value": 19.0},
    ]

    out = {p["date"]: p["value"] for p in trends.deseasonalize(points)}

    assert out["2021-01-15"] - out["2020-01-15"] == approx(4)
    assert out["2021-07-15"] - out["2020-07-15"] == approx(4)


def test_deseasonalize_leaves_out_a_month_seen_once():
    points = [{"date": "2020-01-15", "value": 5.0}, {"date": "2021-01-15", "value": 7.0}, {"date": "2020-07-15", "value": 15.0}]

    assert [p["date"] for p in trends.deseasonalize(points)] == ["2020-01-15", "2021-01-15"]


# Fish measures per survey.

def test_total_species_and_diversity_per_survey():
    add_counts(("1", "2020-05-01", "Mummichog", 5), ("1", "2020-05-01", "American eel", 5),
               ("1", "2020-06-01", "Mummichog", 4))

    def values(metric):
        with db.session() as con:
            return [p["value"] for p in trends.fish_series(con, "1", metric)["points"]]

    assert values("total") == [10, 4]
    assert values("richness") == [2, 1]
    assert values("Mummichog") == [5, 4]
    assert values("American eel") == [5, 0]  # not seen on June 1 counts as zero
    assert values("shannon") == approx([0.6931, 0.0], abs=0.001)
    assert values("simpson") == approx([0.5, 0.0])
    assert values("evenness") == approx([1.0])  # one species on June 1: no evenness, so no point


def test_species_are_most_common_first():
    add_counts(("1", "2020-05-01", "Mummichog", 2), ("1", "2020-05-01", "Atlantic silverside", 9),
               ("2", "2020-05-01", "Winter flounder", 50))

    with db.session() as con:
        assert trends.species(con, "1") == ["Atlantic silverside", "Mummichog"]


def test_demo_data_is_labelled_and_repeatable():
    with db.session() as con:
        first = trends.make_demo(con, 2020, 2020)
    with db.session() as con:
        again = trends.make_demo(con, 2020, 2020)  # replaces, doesn't add
        rows = con.execute("SELECT COUNT(*) AS n, MIN(source) AS lo, MAX(source) AS hi FROM fish_counts").fetchone()
        series = trends.fish_series(con, "1", "total")

    assert first == again == rows["n"] > 0
    assert rows["lo"] == rows["hi"] == "demo"
    assert series["demo"] is True and len(series["points"]) == 12  # one survey a month


# The endpoints.

def test_fish_endpoints():
    add_counts(("1", "2020-05-01", "Mummichog", 3), ("1", "2021-05-01", "Mummichog", 5))

    options = client.get("/api/fish/sites/1/options").json()
    series = client.get("/api/fish/sites/1/series?metric=total&deseason=true").json()

    assert options["species"] == ["Mummichog"] and options["metrics"][0]["key"] == "total"
    assert [p["value"] for p in series["points"]] == [3, 5]  # one month only, both years kept
    assert series["demo"] is True and series["label"] == "Total fish"

# Comparing fish with water.

def test_spearman_of_a_perfect_rise_and_fall():
    assert trends.spearman([1, 2, 3, 4], [10, 20, 30, 40])[0] == approx(1)
    assert trends.spearman([1, 2, 3, 4], [9, 7, 5, 1])[0] == approx(-1)


def test_spearman_only_cares_about_order():
    # Not a straight line, but always rising: still a perfect rank correlation.
    assert trends.spearman([1, 2, 3, 4, 5], [1, 4, 9, 100, 1000])[0] == approx(1)


def test_spearman_with_too_little_or_flat_data_has_no_answer():
    assert trends.spearman([1, 2], [3, 4]) == (None, None)
    assert trends.spearman([1, 2, 3], [5, 5, 5]) == (None, None)


def test_ranks_share_ties():
    assert trends.ranks([10, 30, 20, 20]) == [1, 4, 2.5, 2.5]


def test_standardize_centres_on_zero():
    out = trends.standardize([{"date": "a", "value": v} for v in (2, 4, 6)])
    assert [p["z"] for p in out] == approx([-1, 0, 1])


def test_compare_pairs_surveys_with_nearby_water_readings():
    add_counts(("1", "2020-05-01", "Mummichog", 3), ("1", "2020-06-01", "Mummichog", 6),
               ("1", "2020-07-01", "Mummichog", 9), ("1", "2020-08-01", "Mummichog", 12))
    with db.session() as con:
        con.executemany(
            "INSERT INTO water_readings (site_id, site_name, lat, lon, date, time, measurement, value, unit) "
            "VALUES ('1', 'Upper LaHave', 44, -64, ?, '12:00:00', 'Temperature, water', ?, 'deg C')",
            [("2020-05-03", 8.0), ("2020-06-05", 12.0), ("2020-07-02", 16.0), ("2020-09-30", 20.0)],  # last is too far
        )

    c = client.get("/api/compare/sites/1?metric=total&measurement=Temperature%2C%20water").json()

    assert c["pairs"] == 3  # the August survey has no reading within 15 days
    assert c["spearman"] == approx(1) and c["strength"] == "strong positive"
    assert len(c["fish"]["points"]) == 4 and "z" in c["fish"]["points"][0]


# Starting the app.

def test_a_new_database_gets_water_and_demo_fish_once(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "new.db")  # as on a computer that has never run the app

    def count(source):
        with db.session() as con:
            return con.execute("SELECT COUNT(*) AS n FROM fish_counts WHERE source = ?", (source,)).fetchone()["n"]

    with TestClient(app):
        pass
    assert count("demo") > 2000
    with db.session() as con:
        assert con.execute("SELECT COUNT(*) AS n FROM water_readings").fetchone()["n"] > 20000
        con.execute("DELETE FROM fish_counts WHERE source = 'demo'")  # someone removes the demo data

    with TestClient(app):  # the next start
        pass
    assert count("demo") == 0