# Water quality data

`lahave.csv` holds the on-site probe readings and main lab results from **Coastal Action's LaHave
River Water Quality Monitoring**, published on DataStream:

> Coastal Action. LaHave River Water Quality Monitoring. DataStream. https://doi.org/10.25976/r245-z904

The data is licensed under the [Open Data Commons Attribution License (ODC-By)](https://opendatacommons.org/licenses/by/1-0/).
You may share and adapt it, as long as Coastal Action is credited wherever it is used or shown.
The Fish and water trends page shows this credit with a link.

## What's in it

Downloaded in November 2026, covering 2007-08-03 to 2026-02-19 at 20 sites. This is a trimmed copy of
the 14 MB download: 36,617 readings, one row per reading, of

- six probe measurements: water temperature, pH, dissolved oxygen, dissolved oxygen saturation,
  specific conductance and salinity;
- seven lab results: total phosphorus, total nitrogen, nitrate and nitrite, total suspended solids,
  chloride, fecal coliform and fecal streptococcus (enterococci).

The columns are:

`site_id, site_name, lat, lon, date, time, measurement, value, unit, qualifier`

`qualifier` is empty for a measured value. For a lab result too small to measure it is `<`, and
`value` holds the lab's detection limit (3,396 readings). `>` means too large to measure.

It has already been cleaned by `tidecount/water.py`:

- conductance in mS/cm converted to uS/cm, and pH's unit "None" left blank;
- 13 impossible readings left out (see `LIMITS`), such as dissolved oxygen above 20 mg/L;
- 739 conductance readings at the three estuary sites, labelled uS/cm but really mS/cm, multiplied
  by 1,000 (see `fix_salty_conductance`).
- fecal coliform results from 2007 to 2012 labelled #/mL are left out: their values don't fit that
  unit, so they wait until Coastal Action confirms it.

Times are as given in the source, with no time zone (Nova Scotia local time).

## Water Quality Index

`tidecount/wqi.py` turns these readings into the CCME Water Quality Index for each site and year,
shown as a report card table on the Fish and water trends page. Its guidelines (`FRESH` and `SALTY`)
were chosen to match Coastal Action's published LaHave scores for 2017 to 2023: within about 5 points
on average, with the same rating 48 times out of 70. They are not Coastal Action's official list.
To see one year's scores: `uv run python -m tidecount.wqi 2023`.

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
