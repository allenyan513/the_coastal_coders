"""Water quality readings from Coastal Action's LaHave River monitoring, and matching them to videos.

The data is Coastal Action's LaHave River Water Quality Monitoring on DataStream
(https://doi.org/10.25976/r245-z904), licensed ODC-By: credit Coastal Action wherever it's shown.
The file has one row per measurement. The probe readings and the main lab results are imported.
"""
import csv
import sys
from pathlib import Path

from . import db

# The measurements to keep, by their name in the file.
KEEP = {
    "Temperature, water",
    "pH",
    "Dissolved oxygen (DO)",
    "Dissolved oxygen saturation",
    "Specific conductance",
    "Salinity",
    "Total Phosphorus, mixed forms",
    "Total Nitrogen, mixed forms",
    "Inorganic nitrogen (nitrate and nitrite)",
    "Total suspended solids",
    "Chloride",
    "Fecal Coliform",
    "Fecal Streptococcus Group Bacteria",
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
    "Total Phosphorus, mixed forms": (0, 5),
    "Total Nitrogen, mixed forms": (0, 20),
    "Inorganic nitrogen (nitrate and nitrite)": (0, 20),
    "Total suspended solids": (0, 1000),
    "Chloride": (0, 25000),  # the estuary sites are salty, so chloride there is high
    "Fecal Coliform": (0, 100000),
    "Fecal Streptococcus Group Bacteria": (0, 100000),
}


def reading(row: dict) -> dict | None:
    """One row of the file as a reading, or None if it isn't one to keep."""
    if row["CharacteristicName"] not in KEEP:
        return None
    qualifier = ""  # "<" below what the lab can measure, ">" above it, "" a measured value
    unit = row["ResultUnit"]
    try:
        value = float(row["ResultValue"])
    except ValueError:
        # A lab result too small (or too large) to measure has no value, only the lab's limit.
        try:
            value = float(row.get("ResultDetectionQuantitationLimitMeasure", ""))
        except ValueError:
            return None
        unit = row.get("ResultDetectionQuantitationLimitUnit", "")
        qualifier = "<" if row.get("ResultDetectionCondition", "").startswith("Below") else ">"
    if row["CharacteristicName"] == "Fecal Coliform" and unit != "cfu/100mL":
        return None  # 2007-2012 results say #/mL, which doesn't fit their values; left out until confirmed
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
        "qualifier": qualifier,
    }


# At a salty visit, conductance this low can only be mS/cm labelled as uS/cm. See fix_salty_conductance().
SALTY_PPTH = 1
MS_LABELLED_AS_US_BELOW = 1000


def fix_salty_conductance(readings: list[dict]) -> int:
    """Corrects conductance that Coastal Action's file labels uS/cm but that is really mS/cm. Returns how many.

    At the three estuary sites, salty water's conductance is in the tens of thousands of uS/cm, about
    1,600 for each ppth of salinity. Most of those readings say "uS/cm" but are 1,000 times too small,
    the size mS/cm would be. So at a visit with salinity, any conductance too low for it is multiplied by 1,000.
    """
    # 1. Salinity at each visit. A visit is one site, date and time.
    salinity = {
        (r["site_id"], r["date"], r["time"]): r["value"]
        for r in readings if r["measurement"] == "Salinity"
    }

    # 2. Fix the conductance readings at salty visits.
    fixed = 0
    for r in readings:
        if r["measurement"] != "Specific conductance":
            continue
        sal = salinity.get((r["site_id"], r["date"], r["time"]))
        if sal is not None and sal >= SALTY_PPTH and r["value"] < MS_LABELLED_AS_US_BELOW:
            r["value"] = r["value"] * 1000
            fixed += 1
    return fixed


def read_file(path: str) -> list[dict]:
    """The readings to keep from a file downloaded from DataStream, cleaned and corrected."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = csv.DictReader(f)
        readings = []
        for row in rows:
            r = reading(row)
            if r is not None:
                readings.append(r)

    fixed = fix_salty_conductance(readings)
    print(f"Corrected {fixed} conductance readings labelled uS/cm that were really mS/cm.")
    return readings


def save(con, readings: list[dict]) -> None:
    """Replace every water reading with these."""
    con.execute("DELETE FROM water_readings")
    con.executemany(
        "INSERT INTO water_readings (site_id, site_name, lat, lon, date, time, measurement, value, unit, qualifier) "
        "VALUES (:site_id, :site_name, :lat, :lon, :date, :time, :measurement, :value, :unit, :qualifier)",
        readings,
    )


def import_file(path: str) -> int:
    """Read the whole file and save its readings, replacing any imported before. Returns how many."""
    readings = read_file(path)
    with db.session() as con:
        save(con, readings)
    return len(readings)


# --- The copy kept in the repo ------------------------------------------------------------------
# The DataStream download is 14 MB, mostly measurements we don't use. A trimmed copy, already
# cleaned and corrected, is kept with the code (about 2 MB), so every computer and the team site
# get the water data without downloading or importing anything. See water_data/README.md.

BUNDLED = Path(__file__).parent / "water_data" / "lahave.csv"
COLUMNS = ("site_id", "site_name", "lat", "lon", "date", "time", "measurement", "value", "unit", "qualifier")


def write_bundled(path: str, out: Path = BUNDLED) -> int:
    """Make the trimmed copy from a DataStream download. Returns how many readings."""
    readings = read_file(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        for r in sorted(readings, key=lambda r: (r["site_id"], r["date"], r["time"], r["measurement"])):
            w.writerow({**r, "value": f"{r['value']:g}"})
    return len(readings)


def load_bundled(con, path: Path = BUNDLED) -> int:
    """Fill an empty water_readings table from the trimmed copy. Returns how many readings were added.

    Does nothing when readings are already there (so a newer import isn't overwritten) or the copy is missing.
    """
    if con.execute("SELECT 1 FROM water_readings LIMIT 1").fetchone() or not path.exists():
        return 0
    with open(path, encoding="utf-8", newline="") as f:
        readings = [{**r, "lat": float(r["lat"]), "lon": float(r["lon"]), "value": float(r["value"])}
                    for r in csv.DictReader(f)]
    save(con, readings)
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
    # python -m tidecount.water <download.csv>          import a DataStream download into the database
    # python -m tidecount.water bundle <download.csv>   remake the trimmed copy kept in the repo
    if sys.argv[1:2] == ["bundle"] and len(sys.argv) == 3:
        print(f"Wrote {write_bundled(sys.argv[2])} water readings to {BUNDLED}.")
    elif len(sys.argv) == 2:
        db.init()
        print(f"Imported {import_file(sys.argv[1])} water readings.")
    else:
        sys.exit("Usage: python -m tidecount.water [bundle] <download.csv>")