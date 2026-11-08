from pytest import approx

from tidecount import db, wqi


def add_readings(*readings):
    """Water readings straight into the test database. Each is (site_id, date, measurement, value, qualifier)."""
    with db.session() as con:
        con.executemany(
            "INSERT INTO water_readings (site_id, site_name, lat, lon, date, time, measurement, value, unit, qualifier) "
            "VALUES (?, 'Site ' || ?, 44.0, -64.0, ?, '12:00:00', ?, ?, '', ?)",
            [(site, site, date, m, v, q) for site, date, m, v, q in readings],
        )


def add_fish(*counts):
    """Fish counts straight into the test database. Each is (site_id, date, species, count, source)."""
    with db.session() as con:
        con.executemany("INSERT INTO fish_counts (site_id, date, species, count, source) VALUES (?, ?, ?, ?, ?)", counts)


def a_good_year(site="14", year=2023, ph=7.0):
    """Four sampling days with four freshwater measurements each, all inside their guidelines (pH can be changed)."""
    readings = []
    for month in ("05", "06", "07", "08"):
        date = f"{year}-{month}-10"
        readings += [
            (site, date, "pH", ph, ""),
            (site, date, "Dissolved oxygen (DO)", 9.0, ""),
            (site, date, "Temperature, water", 15.0, ""),
            (site, date, "Chloride", 10.0, ""),
        ]
    return readings


# --- The formula --------------------------------------------------------------------------------

def test_every_test_passing_scores_100():
    s = wqi.score([("pH", 0.0), ("Chloride", 0.0)])
    assert s["wqi"] == 100 and s["rating"] == "Excellent"


def test_a_worked_example():
    # 2 measurements, 1 failed (F1 = 50). 4 tests, 1 failed (F2 = 25).
    # The failed one was 50% over its guideline, so nse = 0.5 / 4 = 0.125 and F3 = 0.125 / 0.01125 = 11.1.
    # WQI = 100 - sqrt(50² + 25² + 11.1²) / 1.732 = 67.1
    s = wqi.score([("pH", 0.0), ("pH", 0.0), ("Chloride", 0.5), ("Chloride", 0.0)])
    assert s["f1"] == 50 and s["f2"] == 25 and s["f3"] == approx(11.1)
    assert s["wqi"] == approx(67.1) and s["rating"] == "Fair"


def test_ratings_follow_ccme_boundaries():
    assert [wqi.rating(v) for v in (100, 95, 94.9, 80, 79.9, 65, 64.9, 45, 44.9, 0)] == [
        "Excellent", "Excellent", "Good", "Good", "Fair", "Fair", "Marginal", "Marginal", "Poor", "Poor"]


def test_excursion_is_how_far_past_the_guideline():
    assert wqi.excursion(0.06, None, 0.03) == approx(1.0)  # twice the limit: 100% over
    assert wqi.excursion(5.0, 6.5, 9.0) == approx(0.3)  # pH 5 against a low limit of 6.5
    assert wqi.excursion(7.0, 6.5, 9.0) == 0.0


# --- Lab results below what the lab can measure --------------------------------------------------

def test_below_detection_under_the_guideline_passes():
    assert wqi.judge(0.004, "<", None, 0.03) == 0.0


def test_below_detection_above_the_guideline_cant_be_judged():
    # The lab could only say "under 0.05", and the guideline is 0.03, so we can't tell if it passed.
    assert wqi.judge(0.05, "<", None, 0.03) is None


def test_below_detection_with_a_lowest_allowed_cant_be_judged():
    assert wqi.judge(2.0, "<", 5.5, None) is None


def test_a_measured_value_is_judged_normally():
    assert wqi.judge(0.06, "", None, 0.03) == approx(1.0)


# --- One site in one year -----------------------------------------------------------------------

def test_a_clean_year_is_excellent():
    add_readings(*a_good_year())
    card = wqi.site_year(db.connect(), "14", 2023)
    assert card["wqi"] == 100 and card["rating"] == "Excellent"
    assert card["sample_days"] == 4 and card["tests"] == 16 and not card["salty"]


def test_failures_lower_the_score():
    add_readings(*a_good_year(ph=5.0))  # pH too acidic on every visit
    card = wqi.site_year(db.connect(), "14", 2023)
    assert card["wqi"] < 80
    assert card["measurements"][0]["measurement"] == "pH"  # the worst measurement comes first
    assert card["measurements"][0]["failed"] == 4


def test_too_few_measurements_is_not_enough_data():
    add_readings(*[r for r in a_good_year() if r[2] != "Chloride"])  # only 3 measurements
    card = wqi.site_year(db.connect(), "14", 2023)
    assert card["wqi"] is None and card["rating"] == "Not enough data"


def test_too_few_sampling_days_is_not_enough_data():
    add_readings(*[r for r in a_good_year() if not r[1].endswith("08-10")])  # only 3 days
    assert wqi.site_year(db.connect(), "14", 2023)["wqi"] is None


def test_a_salty_site_uses_the_estuary_guidelines():
    add_readings(*a_good_year(site="1"), ("1", "2023-05-10", "Salinity", 20.0, ""))
    card = wqi.site_year(db.connect(), "1", 2023)
    assert card["salty"]
    # pH 7.0 passes both lists, but temperature and chloride aren't on the estuary list, so only 2 measurements count.
    assert card["rating"] == "Not enough data"


# --- Fish -----------------------------------------------------------------------------------------

def test_a_year_without_fish_surveys_has_no_fish():
    assert wqi.fish_year(db.connect(), "1", 2023) is None


def test_fish_year_sums_up_the_surveys():
    add_fish(
        ("1", "2023-06-01", "Mummichog", 6, "video"),
        ("1", "2023-06-01", "American eel", 2, "video"),
        ("1", "2023-07-01", "Mummichog", 4, "video"),
        ("1", "2022-07-01", "Winter flounder", 9, "video"),  # another year
    )
    f = wqi.fish_year(db.connect(), "1", 2023)
    assert f["surveys"] == 2 and f["fish"] == 12 and f["per_survey"] == 6.0
    assert f["species"] == 2 and f["most_common"] == "Mummichog" and not f["demo"]


def test_fish_year_says_when_any_of_it_is_demo():
    add_fish(("1", "2023-06-01", "Mummichog", 6, "video"), ("1", "2023-07-01", "Mummichog", 3, "demo"))
    assert wqi.fish_year(db.connect(), "1", 2023)["demo"]


# --- The whole table ------------------------------------------------------------------------------

def test_the_table_runs_down_the_river_and_skips_sites_without_scores():
    add_readings(*a_good_year(site="9"), *a_good_year(site="14"), ("99", "2023-05-10", "pH", 7.0, ""))
    t = wqi.table(db.connect(), last=3)
    assert t["years"] == [2021, 2022, 2023]
    assert [s["site_id"] for s in t["sites"]] == ["14", "9"]  # Franey Corner is upstream of Simpson's Corner
    assert [c["wqi"] for c in t["sites"][0]["scores"]] == [None, None, 100]


def test_the_table_includes_fish():
    add_readings(*a_good_year(site="14"))
    add_fish(("14", "2023-06-01", "Brook trout", 3, "video"))
    fish = wqi.table(db.connect())["sites"][0]["fish"]
    assert fish == [{"year": 2023, "surveys": 1, "fish": 3, "per_survey": 3.0, "species": 1,
                     "shannon": 0.0, "most_common": "Brook trout", "demo": False}]


def test_an_empty_database_gives_an_empty_table():
    assert wqi.table(db.connect()) == {"years": [], "sites": []}