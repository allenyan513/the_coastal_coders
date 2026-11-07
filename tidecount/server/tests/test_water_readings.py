from pytest import approx

from tidecount.water import KEEP, LIMITS, reading


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
