# Water quality data

`lahave.csv` holds the on-site probe readings from **Coastal Action's LaHave River Water Quality
Monitoring**, published on DataStream:

> Coastal Action. LaHave River Water Quality Monitoring. DataStream. https://doi.org/10.25976/r245-z904

The data is licensed under the [Open Data Commons Attribution License (ODC-By)](https://opendatacommons.org/licenses/by/1-0/).
You may share and adapt it, as long as Coastal Action is credited wherever it is used or shown.
The Fish and water trends page shows this credit with a link.

## What's in it

Downloaded in November 2026, covering 2007-08-03 to 2026-02-19 at 20 sites. This is a trimmed copy of
the 14 MB download: 24,240 readings of six measurements (water temperature, pH, dissolved oxygen,
dissolved oxygen saturation, specific conductance and salinity), one row per reading, with these columns:

`site_id, site_name, lat, lon, date, time, measurement, value, unit`

It has already been cleaned by `tidecount/water.py`:

- conductance in mS/cm converted to uS/cm, and pH's unit "None" left blank;
- 13 impossible readings left out (see `LIMITS`), such as dissolved oxygen above 20 mg/L;
- 739 conductance readings at the three estuary sites, labelled uS/cm but really mS/cm, multiplied
  by 1,000 (see `fix_salty_conductance`).

Times are as given in the source, with no time zone (Nova Scotia local time).

## How it's used

When the app starts and its `water_readings` table is empty, it loads this file
(`water.load_bundled`). A database that already has readings is left alone.

## Updating it

Download the dataset again from DataStream (CSV), then, from `tidecount/server`:

```
uv run python -m tidecount.water bundle path\to\download.csv
```

That rewrites `lahave.csv`. To reload a database that already has readings, import the download
directly instead: `uv run python -m tidecount.water path\to\download.csv`.
