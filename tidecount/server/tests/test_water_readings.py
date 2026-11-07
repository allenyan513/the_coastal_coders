from pytest import approx

from tidecount import db
from tidecount.water import KEEP, LIMITS, fix_salty_conductance, reading, series, sites


def row(measurement="pH", value="8.07", unit="None", **other):
    """A row like one from Coastal Action's file. Only what a test cares about needs to be given."""
    r = {
        "MonitoringLocationID": "1",
        "MonitoringLocationName": "Upper LaHave",
        "MonitoringLocationLatitude": "44.3521",
        "MonitoringLocationLongitude": "-64.4346",
        "ActivityStartDate": "2007-08-03",
        "ActivityStartTime": "11:58:00",
        "CharacteristicName": measurement,
        "ResultValue": value,
        "ResultUnit": unit,
    }
    r.update(other)
    return r


def add_readings(*readings):
    """Puts readings straight into the test database. Each is (site_id, site_name, date, measurement, value, unit)."""
    with db.session() as con:
        con.executemany(
            "INSERT INTO water_readings (site_id, site_name, lat, lon, date, time, measurement, value, unit) "
            "VALUES (?, ?, 44.0, -64.0, ?, '12:00:00', ?, ?, ?)",
            readings,
        )


def open_db():
    return db.connect()


def test_a_ph_reading_is_kept():
    r = reading(row())
    assert r is not None
    assert r["value"] == 8.07


def test_ph_has_no_unit():
    r = reading(row())
    assert r is not None
    assert r["unit"] == ""


def test_a_blank_value_is_skipped():
    assert reading(row(value="")) is None


def test_other_measurements_are_skipped():
    assert reading(row("Total Phosphorus, mixed forms", "0.02", "mg/L")) is None


def test_ms_cm_is_converted_to_us_cm():
    r = reading(row("Specific conductance", "0.034", "mS/cm"))
    assert r is not None
    assert r["value"] == approx(34) and r["unit"] == "uS/cm"


def test_us_cm_is_left_alone():
    r = reading(row("Specific conductance", "33.974", "uS/cm"))
    assert r is not None
    assert r["value"] == approx(33.974) and r["unit"] == "uS/cm"


def test_an_impossible_reading_is_skipped():
    # 1357 mg/L of dissolved oxygen is in the real file. Natural water holds at most about 20.
    assert reading(row("Dissolved oxygen (DO)", "1357", "mg/L")) is None
    assert reading(row("Dissolved oxygen saturation", "938", "%")) is None


def test_the_limits_are_included():
    # 14 is exactly pH's upper limit and 0 its lower one, so both are kept.
    assert reading(row(value="14")) is not None
    assert reading(row(value="0")) is not None
    assert reading(row(value="14.01")) is None


def test_site_and_position_are_kept():
    r = reading(row())
    assert r is not None
    assert r["site_id"] == "1" and r["site_name"] == "Upper LaHave"
    assert r["lat"] == approx(44.3521) and r["lon"] == approx(-64.4346)
    assert r["date"] == "2007-08-03" and r["time"] == "11:58:00"


def test_every_kept_measurement_has_limits():
    # Adding a measurement to KEEP without limits would crash the import on its first row.
    assert KEEP == set(LIMITS)


def test_sites_lists_each_site_once():
    add_readings(
        ("1", "Upper LaHave", "2020-05-01", "pH", 7.5, ""),
        ("1", "Upper LaHave", "2020-05-01", "Temperature, water", 12.0, "deg C"),
        ("1", "Upper LaHave", "2020-06-01", "pH", 7.8, ""),
        ("2", "Dayspring", "2020-05-01", "pH", 7.2, ""),
    )
    found = sites(open_db())

    assert len(found) == 2


def test_sites_counts_visits_and_dates():
    add_readings(
        ("1", "Upper LaHave", "2020-05-01", "pH", 7.5, ""),
        ("1", "Upper LaHave", "2020-05-01", "Temperature, water", 12.0, "deg C"),
        ("1", "Upper LaHave", "2020-06-01", "pH", 7.8, ""),
        ("2", "Dayspring", "2020-05-01", "pH", 7.2, ""),
    )

    found = sites(open_db())
    upper = next(s for s in found if s["site_id"] == "1")

    # Two readings on May 1 are one visit, so site 1 has 2 visits, not 3.
    assert upper["visits"] == 2
    assert upper["first_date"] == "2020-05-01" and upper["last_date"] == "2020-06-01"
    assert [s["site_name"] for s in found] == ["Dayspring", "Upper LaHave"]  # sorted by name


def test_series_is_one_site_and_measurement_oldest_first():
    add_readings(
        ("1", "Upper LaHave", "2020-06-01", "pH", 7.8, ""),  # added newest first on purpose
        ("1", "Upper LaHave", "2020-05-01", "pH", 7.5, ""),
        ("1", "Upper LaHave", "2020-05-01", "Temperature, water", 12.0, "deg C"),  # another measurement
        ("2", "Dayspring", "2020-05-01", "pH", 7.2, ""),  # another site
    )

    s = series(open_db(), "1", "pH")

    assert [p["date"] for p in s["points"]] == ["2020-05-01", "2020-06-01"]
    assert [p["value"] for p in s["points"]] == [7.5, 7.8]
    assert s["site_id"] == "1" and s["measurement"] == "pH" and s["unit"] == ""


def test_series_gives_the_unit():
    add_readings(("1", "Upper LaHave", "2020-05-01", "Temperature, water", 12.0, "deg C"))

    assert series(open_db(), "1", "Temperature, water")["unit"] == "deg C"


def test_series_with_no_readings_is_empty():
    s = series(open_db(), "1", "pH")

    assert s["points"] == [] and s["unit"] == ""

# Conductance at salty visits: labelled uS/cm in the file, but really mS/cm.

def visit(measurement, value, site="1", date="2012-01-25", time="08:36:00"):
    return {"site_id": site, "date": date, "time": time, "measurement": measurement, "value": value, "unit": ""}


def test_low_conductance_at_a_salty_visit_is_multiplied():
    # The real Upper LaHave visit on 2012-01-25: salinity 23.55, conductance 38.106 "uS/cm" (really mS/cm).
    readings = [visit("Salinity", 23.55), visit("Specific conductance", 38.106)]

    assert fix_salty_conductance(readings) == 1
    assert readings[1]["value"] == approx(38106)


def test_fresh_water_conductance_is_left_alone():
    readings = [visit("Salinity", 0.02), visit("Specific conductance", 39.6)]

    assert fix_salty_conductance(readings) == 0
    assert readings[1]["value"] == 39.6


def test_conductance_already_big_enough_is_left_alone():
    # Already in uS/cm, for example a reading that was converted from mS/cm on import.
    readings = [visit("Salinity", 3.41), visit("Specific conductance", 6328)]

    assert fix_salty_conductance(readings) == 0
    assert readings[1]["value"] == 6328


def test_only_salinity_from_the_same_visit_counts():
    readings = [
        visit("Salinity", 23.55, time="08:36:00"),
        visit("Specific conductance", 39.6, time="09:06:00"),  # another visit, with no salinity
        visit("Specific conductance", 39.6, site="2"),  # another site
    ]

    assert fix_salty_conductance(readings) == 0
