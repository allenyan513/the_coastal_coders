"""Water quality readings from Coastal Action's LaHave River monitoring, and matching them to videos.

The data is Coastal Action's LaHave River Water Quality Monitoring on DataStream
(https://doi.org/10.25976/r245-z904), licensed ODC-By: credit Coastal Action wherever it's shown.
The file has one row per measurement. Only the probe readings taken on site are imported for now.
"""
import csv
import sys

from . import db

# The measurements to keep, by their name in the file.
KEEP = {
    "Temperature, water",
    "pH",
    "Dissolved oxygen (DO)",
    "Dissolved oxygen saturation",
    "Specific conductance",
    "Salinity",
}


# Readings outside these limits are mistakes in the source data, not real water, so they're left out.
# (lowest, highest), in the units after any conversion.
LIMITS = {
    "Temperature, water": (-2, 35),
    "pH": (0, 14),
    "Dissolved oxygen (DO)": (0, 20),
    "Dissolved oxygen saturation": (0, 200),
    "Specific conductance": (0, 60000),
    "Salinity": (0, 40),
}


def reading(row: dict) -> dict | None:
    """One row of the file as a reading, or None if it isn't one to keep."""
    if row["CharacteristicName"] not in KEEP:
        return None
    try:
        value = float(row["ResultValue"])
    except ValueError:
        return None
    unit = row["ResultUnit"]
    if row["CharacteristicName"] == "Specific conductance" and unit == "mS/cm":
        value = value * 1000
        unit = "uS/cm"
    if unit == "None":
        unit = ""
    low, high = LIMITS[row["CharacteristicName"]]
    if not low <= value <= high:
        return None
    return {
        "site_id": row["MonitoringLocationID"],
        "site_name": row["MonitoringLocationName"],
        "lat": float(row["MonitoringLocationLatitude"]),
        "lon": float(row["MonitoringLocationLongitude"]),
        "date": row["ActivityStartDate"],
        "time": row["ActivityStartTime"],
        "measurement": row["CharacteristicName"],
        "value": value,
        "unit": unit,
    }


def import_file(path: str) -> int:
    """Read the whole file and save its readings, replacing any imported before. Returns how many."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = csv.DictReader(f)
        readings = []
        for row in rows:
            r = reading(row)
            if r is not None:
                readings.append(r)

    with db.session() as con:
        con.execute("DELETE FROM water_readings")
        con.executemany(
            "INSERT INTO water_readings (site_id, site_name, lat, lon, date, time, measurement, value, unit) "
            "VALUES (:site_id, :site_name, :lat, :lon, :date, :time, :measurement, :value, :unit)",
            readings,
        )
    return len(readings)


def sites(con) -> list[dict]:
    """Every sampling site, with when it was first and last sampled and how many visits."""
    return db.rows(con.execute(
        "SELECT site_id, site_name, lat, lon, MIN(date) AS first_date, MAX(date) AS last_date, COUNT(DISTINCT date) AS visits "
        "FROM water_readings "
        "GROUP BY site_id ORDER BY site_name"
    ))


def series(con, site_id: str, measurement: str) -> dict:
    """One measurement at one site, oldest first, for a chart."""
    rows = db.rows(con.execute(
        "SELECT date, value FROM water_readings WHERE site_id = ? AND measurement = ? "
        "ORDER BY date", 
        (site_id, measurement),
    ))
    found = con.execute("SELECT unit FROM water_readings WHERE measurement = ? LIMIT 1", (measurement,)).fetchone()
    unit = "" if found is None else found["unit"]  # no readings of this measurement at all: no unit to show
    return {"site_id": site_id, "measurement": measurement, "unit": unit, "points": rows}


if __name__ == "__main__":
    db.init()
    count = import_file(sys.argv[1])
    print(f"Imported {count} water readings.")