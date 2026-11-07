"""Where a species has been recorded, from OBIS (the Ocean Biodiversity Information System).

These are real occurrence records, not modelled ranges. Three views of them, all fetched through
here so the browser never calls OBIS directly:

- `grid`: OBIS's own geohash aggregation, one cell with a record count instead of one marker per
  record. Precision 2 is about 11 x 6 degrees, 3 about 1.4 x 1.4, 4 about 0.35 x 0.18, 5 about
  0.04 x 0.04 and 6 about 0.01 x 0.005.
- `records`: individual records inside one cell, with date, place, dataset and licence.
- `summary`: totals, years and the datasets that hold most of the records for a region.
- `nondetections`: where net, trawl or seine surveys reported the species as not detected, counted by site and date.
- `edna_evidence`: water-sample DNA detections and non-detections, as sampling site-dates, apart from
  everything above because DNA in water is not a sighting or a catch.

All counts are occurrence records, not fish: one trawl haul, one photo or one acoustic tag ping is
one record each. A cell with no records only means nobody has shared a record there with OBIS,
which is not evidence that the fish is missing.

Absence records are never counted raw. OBIS marks a record `absence=true` when the publisher said
`occurrenceStatus=absent` or a count of 0, and in Atlantic Canada nearly all of them are eDNA
detection tables with a zero for every sequence variant in every sample: for mackerel, 79,168 rows
from 99 water samples at 74 site-dates, including the 27 site-dates where mackerel DNA was found.
`nondetections` reduces them to site-dates per sampling method; see its docstring.

Answers are cached on disk for a week, so a species opens quickly the second time and OBIS sees
few requests. When OBIS can't be reached, a cached answer is used even if it's old, and says so.

This is a public website's only door to OBIS, so every request goes through safeguards:
`api_guard` (a server-wide request budget with a circuit breaker, per-visitor limits, shared
requests and a small queue of background jobs) and `api_cache` (a disk cache with a size limit).
What a visitor may ask for is also narrowed here, so there are few distinct requests to cache.
"""
import json
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import urllib.error
import urllib.parse
import urllib.request

from . import api_cache, api_guard, species_media
from .api_guard import Busy, RateLimited  # noqa: F401  (re-exported for the routes)

OBIS = os.environ.get("TIDECOUNT_OBIS_URL", "https://api.obis.org/v3/")  # only changed to test against a stand-in server
UA = "TideCount/0.1 (species wiki; https://github.com/allenyan513/the_coastal_coders)"
CACHE_TTL_S = 7 * 24 * 3600
TIMEOUT_S = 25            # a visitor's own request gives up on OBIS after this long
JOB_TIMEOUT_S = 60        # background jobs fetch big pages, so they wait longer
WAIT_S = 5                # how long a visitor's request waits for a place in the outbound budget
JOB_WAIT_S = 60           # and a background job
RETRIES = 2               # extra tries a background job makes after a timeout, 429 or 5xx
YEAR_MIN, YEAR_MAX = 1900, 2100  # the years a range may name; an open end (None) has no limit
MAX_CELLS = 8000          # more than this would slow the map, so ask for a coarser grid
MAX_AREA = {2: None, 3: None, 4: 1500, 5: 60, 6: 6}  # square degrees a request may cover at each precision
RECORD_FIELDS = ",".join([
    "id", "occurrenceID", "eventDate", "date_mid", "date_year", "decimalLatitude", "decimalLongitude",
    "coordinateUncertaintyInMeters", "minimumDepthInMeters", "maximumDepthInMeters", "datasetName",
    "dataset_id", "institutionCode", "basisOfRecord", "recordedBy", "individualCount",
    "occurrenceStatus", "absence", "scientificName", "license",
])

# Regions the drawer offers as starting points. The map can still pan anywhere.
REGIONS = {
    "nova-scotia": {"label": "Nova Scotia", "bbox": (-66.6, 43.2, -59.6, 47.2)},
    "atlantic-canada": {"label": "Atlantic Canada", "bbox": (-70.0, 40.5, -50.0, 53.0)},
    "north-atlantic": {"label": "North Atlantic", "bbox": (-82.0, 24.0, 20.0, 75.0)},
    "world": {"label": "World", "bbox": None},
}

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="obis")  # a visitor's summary: three requests at once
# Two helpers for a background job, reading two datasets at a time. "api-job" in the name is what
# tells api_guard they may wait for their turn and retry.
_job_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="api-job-io")
RESULT_WAIT_S = 6         # how long a request for a background calculation waits for its first result

# Acoustic telemetry logs a tagged fish every time it passes a receiver, so one fish can become
# hundreds of thousands of OBIS records in one cell. On the Atlantic Canada map for cod, a single
# telemetry cell held 970,835 of about 2.2 million records. These words mark such datasets.
# "Tagging" alone is left out: the old DFO mark-and-recapture databases are tagging too, but they
# hold one record per release or catch, not a record per ping.
TELEMETRY = re.compile(r"telemetry|acoustic|receiver|detections|\bOTN\b|ocean tracking network", re.IGNORECASE)


class Unavailable(Exception):
    """OBIS couldn't be reached (or is being given a rest) and nothing was cached for this request."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def _unavailable(e: BaseException) -> Unavailable:
    wait = getattr(e, "retry_after", None)
    if isinstance(e, api_guard.Busy):
        return Unavailable(f"{e.reason} Cached answers are still available.", wait)
    return Unavailable(f"OBIS could not be reached ({e.__class__.__name__}). Try again later.", wait or 30)


def _fetch(path: str, params: dict) -> tuple[dict, dict]:
    """One OBIS request, through the disk cache. Returns the answer and where it came from.
    Identical requests made at the same moment share one call to OBIS. When OBIS can't be
    reached, or this server is at its request limits, an older cached answer is used if there is one."""
    url = OBIS + path + "?" + urllib.parse.urlencode(sorted(params.items()))
    cached = api_cache.read(url)
    if cached and time.time() - cached["fetched_at"] < CACHE_TTL_S:
        return cached["data"], {"fetched_at": cached["fetched_at"], "cached": True, "stale": False}

    def work():
        try:
            data = _get(url)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            if cached:
                return cached["data"], {"fetched_at": cached["fetched_at"], "cached": True, "stale": True}
            raise _unavailable(e) from e
        now = time.time()
        api_cache.write(url, data, fetched_at=now)
        return data, {"fetched_at": now, "cached": False, "stale": False}

    try:
        return api_guard.flight.do(url, work)
    except TimeoutError:  # another request for the same thing took too long
        raise Unavailable("OBIS is slow to answer. Try again later.", 10)


def _open(url: str, timeout: float):
    """The network call itself. Tests replace `_get`; tests of the safeguards replace this."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _get(url: str):
    """Every request to OBIS goes through here, and so through the server-wide OBIS budget, its
    circuit breaker and retries (see api_guard.call). Tests replace this."""
    return api_guard.call(api_guard.budget("obis"), url, lambda u, t: _open(u, t), timeout=TIMEOUT_S,
                          job_timeout=JOB_TIMEOUT_S, wait_s=WAIT_S, job_wait_s=JOB_WAIT_S, retries=RETRIES)


# --- what to ask OBIS for ---------------------------------------------------------------------

def taxon_filter(name: str) -> dict:
    """OBIS is keyed on WoRMS AphiaIDs. Use the checked ID when there is one, else the name itself.
    An ID also finds records filed under the species' synonyms."""
    t = species_media.taxonomy(name)
    aphia = (t or {}).get("accepted_aphia_id") or (t or {}).get("aphia_id")
    return {"taxonid": aphia} if aphia else {"scientificname": name}


def parse_bbox(text: str | None) -> tuple[float, float, float, float] | None:
    """`w,s,e,n` in degrees, clamped to the world. None or empty means the whole world."""
    if not text:
        return None
    try:
        w, s, e, n = (float(v) for v in text.split(","))
    except ValueError:
        raise ValueError("bbox must be four numbers: west,south,east,north")
    w, e = max(-180.0, min(180.0, w)), max(-180.0, min(180.0, e))
    s, n = max(-90.0, min(90.0, s)), max(-90.0, min(90.0, n))
    if w >= e or s >= n:
        raise ValueError("bbox must have west < east and south < north")
    return (w, s, e, n)


def wkt(bbox) -> str:
    w, s, e, n = bbox
    return f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"


# Every distinct request is a new cache entry and a new call to OBIS, so what a visitor may ask for
# is narrowed to what the map really asks for.
SNAP = {2: 180.0, 3: 20.0, 4: 5.0, 5: 1.0, 6: 0.25}  # degrees the map rounds a view out to, per precision


def snap_bbox(bbox, precision: int):
    """Round a view outward to the map's own steps, as the browser already does, so near-identical
    views share one cache entry however a client words them."""
    if bbox is None:
        return None
    step = SNAP[precision]
    w, s, e, n = bbox
    return (max(-180.0, math.floor(w / step) * step), max(-90.0, math.floor(s / step) * step),
            min(180.0, math.ceil(e / step) * step), min(90.0, math.ceil(n / step) * step))


def check_range(since: int | None, until: int | None = None) -> tuple[int | None, int | None]:
    """The year range the map offers: whole years from YEAR_MIN to YEAR_MAX, either end open
    (None: no limit, so "all years" really includes every older and newer record). Anything else
    is refused. Single years allow a few thousand distinct ranges per view rather than a few
    hundred; that stays bounded because the browser asks only when a handle is let go, every answer
    goes through the size-limited cache, and OBIS calls through the server-wide budget and the
    per-visitor limits."""
    for label, year in (("since", since), ("until", until)):
        if year is not None and not YEAR_MIN <= year <= YEAR_MAX:
            raise ValueError(f"{label} must be a year from {YEAR_MIN} to {YEAR_MAX}")
    if since is not None and until is not None and until < since:
        raise ValueError("until must not be before since")
    return since, until


def in_range(day: str | None, since: int | None, until: int | None) -> bool:
    """Whether an ISO date falls in a year range. Undated records are in only when there is no range."""
    if since is None and until is None:
        return True
    try:
        year = int((day or "")[:4])
    except ValueError:
        return False
    return (since is None or year >= since) and (until is None or year <= until)


def _cell_size(precision: int) -> tuple[float, float]:
    bits = 5 * precision  # a geohash alternates longitude and latitude bits, longitude first
    return 360 / 2 ** ((bits + 1) // 2), 180 / 2 ** (bits // 2)


def grid_cell(bbox) -> tuple[float, float, float, float]:
    """The exact OBIS grid cell a records request names. Records are listed for cells the map
    drew, so a box that isn't one of OBIS's geohash cells is refused rather than becoming a new
    cache entry."""
    if bbox is not None:
        w, s, e, n = bbox
        for precision in range(2, 7):
            cw, ch = _cell_size(precision)
            if abs((e - w) - cw) > cw * 0.01 or abs((n - s) - ch) > ch * 0.01:
                continue
            col, row = round((w + 180) / cw), round((s + 90) / ch)
            if abs((w + 180) / cw - col) < 0.02 and abs((s + 90) / ch - row) < 0.02:
                return (round(-180 + col * cw, 6), round(-90 + row * ch, 6), round(-180 + (col + 1) * cw, 6), round(-90 + (row + 1) * ch, 6))
    raise ValueError("records can only be listed for one of the map's grid cells")


def _filters(name: str, bbox, since: int | None, absence: bool, until: int | None = None, datasets: list[str] | None = None) -> dict:
    params = taxon_filter(name)
    if bbox:
        params["geometry"] = wkt(bbox)
    if since:
        params["startdate"] = f"{since}-01-01"
    if until:
        params["enddate"] = f"{until}-12-31"
    if absence:
        params["absence"] = "true"  # only "looked for and not found" records
    if datasets:
        params["datasetid"] = ",".join(sorted(datasets))  # OBIS takes several, comma-separated
    return params


# --- filtering by dataset and observation method -----------------------------------------------
#
# OBIS can only include datasets (`datasetid`, one or several), not exclude them, and it has no
# field for how a record was made. So the map's filters work from the list of datasets that hold the
# species in a region (one cached request), each given a method from its own OBIS metadata, and are
# sent to OBIS as the list of dataset ids to include. "Everything except acoustic telemetry" is the
# list of all the others. A visitor names a method or one dataset from that list, never ids of
# their own, so the cache sees few distinct requests.

CATALOG_MAX = 200    # datasets listed per species and region; when OBIS has more, filtering is refused
FILTER_MAX_IDS = 150  # dataset ids one request may send to OBIS (about 5.5 kB of address)
RECORD_METHODS = {
    "survey": "Research surveys",
    "telemetry": "Acoustic telemetry",
    "edna": "eDNA",
    "other": "Other or not stated",
}
METHOD_FILTERS = {**RECORD_METHODS, "no_telemetry": "All except acoustic telemetry"}
SURVEY_TITLE = re.compile(r"survey|research vessel|trawl|seine|monitoring program", re.I)
TAGGING = re.compile(r"tagging|\btags?\b|recapture", re.I)
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _record_method(d: dict) -> str:
    """How a dataset's occurrence records were made, from its OBIS metadata, or "other" when the
    metadata doesn't say clearly. eDNA: the DNA extension or eDNA in the title or abstract.
    Acoustic telemetry: telemetry words in the title or institute (the Ocean Tracking Network is a
    telemetry network). Research surveys: net, trawl or seine sampling (see `_method`) and a title
    that names a survey, a research vessel or the gear; mark-and-recapture tagging databases are
    left out, since they hold releases and catches by anyone. Museum collections, FishBase,
    iNaturalist and compilations are "other": they don't say how each record was made."""
    method = _method(d)
    if method in ("edna", "edna_coi"):
        return "edna"
    if _dataset(d)["telemetry"]:
        return "telemetry"
    title = d.get("title") or ""
    if method == "capture" and SURVEY_TITLE.search(title) and not TAGGING.search(title):
        return "survey"
    return "other"


def catalog(name: str, region: str) -> dict:
    """Every dataset holding records of the species in a region, largest first, with its method
    and record count there. One OBIS request, cached like the others."""
    if region not in REGIONS:
        raise ValueError(f"region must be one of {', '.join(REGIONS)}")
    data, meta = _fetch("dataset", {**_filters(name, REGIONS[region]["bbox"], None, False), "size": CATALOG_MAX})
    rows = [d for d in data.get("results", []) if d.get("id")]
    datasets = sorted(({**_dataset(d), "method": _record_method(d)} for d in rows), key=lambda d: -(d["records"] or 0))
    methods = [
        {"key": k, "label": label,
         "datasets": sum(1 for d in datasets if d["method"] == k),
         "records": sum(d["records"] or 0 for d in datasets if d["method"] == k)}
        for k, label in RECORD_METHODS.items()
    ]
    return {
        "species": name, "region": region, "label": REGIONS[region]["label"],
        "total": data.get("total", len(rows)), "complete": data.get("total", len(rows)) <= len(rows),
        "methods": methods, "datasets": datasets, **_provenance(meta),
    }


def dataset_ids(name: str, region: str | None, method: str | None, dataset: str | None) -> list[str] | None:
    """The datasets a filter keeps, as OBIS ids: None for no filter, [] when nothing matches.
    `method` is one of METHOD_FILTERS and `dataset` one id from the region's catalog; both may be
    given, and then the dataset must also be of that method. Anything else is refused."""
    if not method and not dataset:
        return None
    if method and method not in METHOD_FILTERS:
        raise ValueError(f"method must be one of {', '.join(METHOD_FILTERS)}")
    if dataset and not UUID.match(dataset):
        raise ValueError("dataset must be an OBIS dataset id")
    if region not in REGIONS:
        raise ValueError(f"filtering by method or dataset needs a region: one of {', '.join(REGIONS)}")
    cat = catalog(name, region)
    if not cat["complete"]:
        raise ValueError(f"OBIS lists more than {CATALOG_MAX} datasets for this fish in {cat['label']}, too many to filter. Pick a smaller region.")
    rows = cat["datasets"]
    if dataset:
        if dataset not in {d["id"] for d in rows}:
            raise ValueError(f"that dataset holds no records of this fish in {cat['label']}")
        rows = [d for d in rows if d["id"] == dataset]
    if method == "no_telemetry":
        rows = [d for d in rows if d["method"] != "telemetry"]
    elif method:
        rows = [d for d in rows if d["method"] == method]
    ids = sorted(d["id"] for d in rows)
    if len(ids) > FILTER_MAX_IDS:
        raise ValueError(f"that filter keeps {len(ids)} datasets, too many to send to OBIS. Pick a smaller region or one method.")
    return ids


# --- the three views --------------------------------------------------------------------------

def grid(name: str, bbox, precision: int, since: int | None = None, until: int | None = None,
         region: str | None = None, method: str | None = None, dataset: str | None = None) -> dict:
    """Occurrence-record cells, as [west, south, east, north, record count] lists. Absence records
    aren't gridded: a raw count of them is misleading, so `nondetections` handles them. A method or
    dataset filter keeps the records of those datasets of `region`'s catalog (see `dataset_ids`)."""
    if precision not in MAX_AREA:
        raise ValueError("precision must be between 2 and 6")
    bbox, (since, until) = snap_bbox(bbox, precision), check_range(since, until)
    ids = dataset_ids(name, region, method, dataset)
    limit = MAX_AREA[precision]
    if limit is not None:
        if bbox is None:
            raise ValueError(f"precision {precision} needs a bbox")
        area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        if area > limit:
            raise ValueError(f"that area is too large for precision {precision}; zoom in or use a coarser grid")
    if ids == []:  # the filter keeps no dataset: nothing to ask OBIS for
        data, meta = {"features": []}, None
    else:
        data, meta = _fetch(f"occurrence/grid/{precision}", _filters(name, bbox, since, False, until, ids))
    cells = []
    for f in data.get("features", []):
        ring = f["geometry"]["coordinates"][0]
        lons, lats = [p[0] for p in ring], [p[1] for p in ring]
        cells.append([round(min(lons), 5), round(min(lats), 5), round(max(lons), 5), round(max(lats), 5), int(f["properties"]["n"])])
    cells.sort(key=lambda c: -c[4])
    return {
        "species": name, "precision": precision, "bbox": bbox, "since": since, "until": until,
        "filter": {"method": method, "dataset": dataset, "datasets": None if ids is None else len(ids)},
        "present": cells[:MAX_CELLS], "present_truncated": len(cells) > MAX_CELLS,
        **_provenance(meta),
    }


def records(name: str, bbox, since: int | None = None, size: int = 100, until: int | None = None,
            region: str | None = None, method: str | None = None, dataset: str | None = None) -> dict:
    """Up to `size` records inside a small box, newest first. When the box holds more, this is a
    sample OBIS chose, and the total says how many there are. Filters as for `grid`."""
    if bbox is None:
        raise ValueError("records need a bbox")
    bbox, (since, until) = grid_cell(bbox), check_range(since, until)
    if (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) > 30:
        raise ValueError("pick a smaller area to list records")
    size = min(size, 100)
    ids = dataset_ids(name, region, method, dataset)
    if ids == []:
        return {"species": name, "bbox": bbox, "total": 0, "records": [], **_provenance(None)}
    data, meta = _fetch("occurrence", {**_filters(name, bbox, since, False, until, ids), "size": size, "fields": RECORD_FIELDS})
    raw = data.get("results", [])
    rows = [_record(r) for r in raw]
    # Sort on OBIS's parsed date, not the text: eventDate can be "9/1/2022", which sorts above "2025-…".
    keys = [_sort_key(r) for r in raw]
    rows = [row for _, row in sorted(zip(keys, rows), key=lambda kr: kr[0], reverse=True)]
    return {"species": name, "bbox": bbox, "total": data.get("total", len(rows)), "records": rows, **_provenance(meta)}


def summary(name: str, region: str, method: str | None = None, dataset: str | None = None) -> dict:
    """How many records, from when, and from which datasets, for one of REGIONS. With `method` or
    `dataset` (see `dataset_ids`), only the records of the chosen datasets are counted."""
    if region not in REGIONS:
        raise ValueError(f"region must be one of {', '.join(REGIONS)}")
    bbox = REGIONS[region]["bbox"]
    ids = dataset_ids(name, region, method, dataset)
    base = _filters(name, bbox, None, False, datasets=ids)
    if ids == []:  # nothing to ask OBIS for
        present, meta, years, top, dataset_total = {"total": 0}, None, [], [], 0
    elif ids is None:
        present_f, years_f, datasets_f = (
            _pool.submit(_fetch, "occurrence", {**base, "size": 0}),
            _pool.submit(_fetch, "statistics/years", base),
            _pool.submit(_fetch, "dataset", {**base, "size": 8}),
        )
        (present, meta), (years, _), (datasets, _) = (f.result() for f in (present_f, years_f, datasets_f))
        top, dataset_total = [_dataset(d) for d in datasets.get("results", [])], datasets.get("total", 0)
    else:
        # The chosen datasets come from the catalog, whose record counts are OBIS's own for this
        # species and region (checked against OBIS's count for mackerel and winter flounder), so
        # only the records per year are a new request.
        years, meta = _fetch("statistics/years", base)
        chosen = set(ids)
        listed = [d for d in catalog(name, region)["datasets"] if d["id"] in chosen]
        present = {"total": sum(d["records"] or 0 for d in listed)}
        top, dataset_total = listed[:8], len(listed)
    with_records = [y for y in (years or []) if y.get("records")]
    recent = sum(y["records"] for y in with_records if y["year"] >= 2010)
    total = present.get("total", 0)
    # Without a filter only the largest datasets are listed, so this is a lower bound on the telemetry share.
    telemetry = sum(d["records"] or 0 for d in top if d["telemetry"])
    return {
        "species": name, "region": region, "label": REGIONS[region]["label"], "bbox": bbox,
        "filter": {"method": method, "dataset": dataset, "datasets": None if ids is None else len(ids)},
        "present": total,
        "telemetry_share": round(min(1.0, telemetry / total), 3) if total else 0.0,
        "first_year": min((y["year"] for y in with_records), default=None),
        "last_year": max((y["year"] for y in with_records), default=None),
        "since_2010": recent,
        # Records per year (all years, one cached answer), so the page can total any year range
        # without another request.
        "by_year": [{"year": y["year"], "records": y["records"]} for y in with_records],
        "dataset_count": dataset_total,
        "datasets": top,
        "taxon": taxon_filter(name),
        **_provenance(meta),
    }


# --- non-detections ---------------------------------------------------------------------------

ND_MAX_ROWS = 200_000          # absence rows in a region; above this the summary isn't attempted
ND_MAX_PRESENCE_ROWS = 50_000  # presence rows fetched per dataset to cross-check its non-detections
ND_MAX_POINTS = 3000           # sites returned for the map
ND_PAGE = 10_000               # OBIS's largest page

# How a dataset sampled, from its OBIS metadata. Order matters: an eDNA dataset may mention a survey.
METHODS = [
    ("edna", "eDNA", re.compile(r"\bedna\b|environmental dna|metabarcod", re.I)),
    ("imagery", "Seabed imagery", re.compile(r"imag|camera|video|photograph|\brov\b", re.I)),
    ("capture", "Net, trawl or seine survey", re.compile(r"trawl|seine|gill ?net|fyke|electrofish|research vessel|groundfish", re.I)),
]
FISH_MARKERS = re.compile(r"\b12s\b|\b16s\b|mifish|teleo", re.I)
# Markers that read all animals (COI, 18S) or plankton surveys: they miss many fish, so a non-detection says little.
GENERAL_MARKERS = re.compile(r"\bcoi\b|\b18s\b|zooplankton", re.I)
# Methods whose non-detections are shown. The others are counted but withheld, with the reason.
SHOWN = {"edna", "capture"}
WITHHELD_REASON = {
    "imagery": "Photos of the seabed can't see fish in open water, so not appearing in them says little.",
    "edna_coi": "These eDNA datasets use a general-purpose marker (COI or 18S) or sample zooplankton, and often miss fish that are there.",
    "other": "The dataset doesn't say clearly how it sampled, so a non-detection can't be interpreted.",
    "unchecked": "Too many records to cross-check against this dataset's detections.",
}


def _method(d: dict) -> str:
    """eDNA, imagery, capture or other, from the DNA extension, title and abstract."""
    text = f"{d.get('title') or ''} {re.sub(r'<[^>]+>', ' ', d.get('abstract') or '')}"
    is_dna = "dnaderiveddata" in [str(e).lower() for e in (d.get("extensions") or [])]
    title = d.get("title") or ""
    for key, _label, pattern in METHODS:
        if (key == "edna" and is_dna) or pattern.search(text):
            if key == "edna":
                # The title names the marker that was sequenced; an abstract often describes the whole programme.
                if FISH_MARKERS.search(title):
                    return "edna"
                if GENERAL_MARKERS.search(title):
                    return "edna_coi"
                if not FISH_MARKERS.search(text) and GENERAL_MARKERS.search(text):
                    return "edna_coi"
            return key
    return "other"


def _site_dates(params: dict, limit: int, job=None, progress: dict | None = None, stats: dict | None = None) -> tuple[set, int, bool]:
    """The site-dates of every row for a query, paged the way OBIS documents: each page starts
    `after` the last id of the one before. Returns (site-dates, rows read, whether `limit` cut it
    short). Each page is reduced as it arrives, so memory follows the number of sampling events,
    not the number of rows. `progress` counts rows read; `stats["skipped"]` counts rows with no
    usable position."""
    keys: set = set()
    rows, after = 0, None
    while True:
        if job:
            job.check()  # stops a job that has run too long or asked for too much
        p = {**params, "size": ND_PAGE, "fields": "id,decimalLatitude,decimalLongitude,eventDate,date_mid", **({"after": after} if after else {})}
        page = _get(OBIS + "occurrence?" + urllib.parse.urlencode(sorted(p.items()))).get("results", [])
        rows += len(page)
        found = {k for k in map(_site_date, page) if k}
        if stats is not None:
            stats["skipped"] = stats.get("skipped", 0) + sum(1 for r in page if _site_date(r) is None)
        if progress is not None:
            progress["done"] = progress.get("done", 0) + len(page)
        keys |= found
        if rows > limit:
            return keys, rows, True
        if len(page) < ND_PAGE:
            return keys, rows, False
        after = page[-1]["id"]


def _site_date(r: dict) -> tuple | None:
    """One sampling site on one day: coordinates to 4 decimals (about 10 m) and the UTC date."""
    lat, lon = r.get("decimalLatitude"), r.get("decimalLongitude")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    day = ""
    if isinstance(r.get("date_mid"), (int, float)):
        try:
            day = (EPOCH + timedelta(milliseconds=r["date_mid"])).date().isoformat()
        except OverflowError:
            day = ""
    if not day and re.match(r"^\d{4}-\d{2}-\d{2}", r.get("eventDate") or ""):
        day = r["eventDate"][:10]
    return (round(lat, 4), round(lon, 4), day)


def nondetections(name: str, region: str, wait: float | None = None, on_start=None) -> dict:
    """Where surveys reported the species as not detected, as site-dates per sampling method.

    1. List the datasets holding absence records in the region, and their method (see `_method`).
    2. Fetch each one's absence and presence rows, reduced to site-dates (same place, same day).
    3. A site-date is a non-detection when it has absence rows and no presence of the species at
       that site-date in any of these datasets. eDNA tables add a zero row for every sequence
       variant in every sample, including samples where the species was found, so this step
       removes both the repetition and those contradictions.
    4. Count site-dates once per method, so a sample published as 12S and 16S datasets counts once.

    Only eDNA with fish-targeted markers and net, trawl or seine surveys are shown. Imagery, COI-only
    eDNA and unclear methods are counted and withheld with the reason. Whole-region results are
    cached like every other OBIS answer.

    eDNA datasets are left out here on purpose. They are a different kind of evidence and hold
    nearly all the rows, so `edna_evidence` handles them separately.

    This can take minutes for a species with big trawl surveys, so it runs as a background job (see
    `_serve`): the first request starts it and answers `status: "computing"`, and asking again
    follows it. The finished answer is cached for a week.
    """
    if region not in REGIONS:
        raise ValueError(f"region must be one of {', '.join(REGIONS)}")
    wait = RESULT_WAIT_S if wait is None else wait
    params = _filters(name, REGIONS[region]["bbox"], None, False)
    key = "nondetections:" + json.dumps({"p": sorted(params.items()), "v": 3})
    base = {"species": name, "region": region, "label": REGIONS[region]["label"], "absence_rows": 0, "methods": [], "withheld": [], "points": []}

    def work(job):
        data = _compute_nondetections(name, region, params, job)
        _finish(job, key, "nd-", data)

    return _serve(key, "nd-", CACHE_TTL_S, work, wait, on_start,
                  skeleton=lambda state, ahead: {**base, "status": state, "ahead": ahead})


def _compute_nondetections(name: str, region: str, params: dict, job=None) -> dict:
    base = {"species": name, "region": region, "label": REGIONS[region]["label"]}
    listing = _get(OBIS + "dataset?" + urllib.parse.urlencode(sorted({**params, "absence": "true", "size": 200}.items())))
    # eDNA has its own, much faster path with its own section: see `edna_evidence`.
    datasets = [d for d in listing.get("results", []) if d.get("records") and _method(d) not in ("edna", "edna_coi")]
    total_rows = sum(d["records"] for d in datasets)
    if not datasets:
        return {**base, "status": "none", "absence_rows": 0, "methods": [], "withheld": [], "points": []}
    if total_rows > ND_MAX_ROWS:
        return {**base, "status": "too_many", "absence_rows": total_rows, "methods": [], "withheld": [], "points": []}

    def per_dataset(d):
        absent, n_absent, _ = _site_dates({**params, "datasetid": d["id"], "absence": "true"}, ND_MAX_ROWS, job)
        present, _n, cut = _site_dates({**params, "datasetid": d["id"]}, ND_MAX_PRESENCE_ROWS, job)
        return d, absent, n_absent, present, cut

    try:
        results = list(_job_pool.map(per_dataset, datasets))
    except BaseException:
        if job:
            job.cancelled = True
        raise
    detected = set()  # site-dates where any of these datasets found the species
    for _d, _a, _n, present, _cut in results:
        detected |= present

    groups: dict[str, dict] = {}
    for d, absent, n_absent, present, cut in results:
        method = "unchecked" if cut else _method(d)
        nd = absent - detected
        g = groups.setdefault(method, {"site_dates": set(), "detected": set(), "rows": 0, "datasets": []})
        g["site_dates"] |= nd
        g["detected"] |= present
        g["rows"] += n_absent
        g["datasets"].append({
            "id": d["id"], "title": d.get("title") or "Untitled dataset",
            "url": f"https://obis.org/dataset/{d['id']}",
            "absence_rows": n_absent, "site_dates": len(nd), "sites": len({k[:2] for k in nd}),
        })

    labels = {k: label for k, label, _ in METHODS} | {"edna_coi": "eDNA, COI marker only", "other": "Method unclear", "unchecked": "Not cross-checked"}
    shown, withheld, points = [], [], []
    for method, g in sorted(groups.items(), key=lambda kv: -len(kv[1]["site_dates"])):
        sd = g["site_dates"]
        days = sorted(k[2] for k in sd if k[2])
        entry = {
            "method": method, "label": labels[method],
            "site_dates": len(sd), "sites": len({k[:2] for k in sd}),
            "detected_site_dates": len(g["detected"]), "absence_rows": g["rows"],
            "first_date": days[0] if days else None, "last_date": days[-1] if days else None,
            "datasets": sorted(g["datasets"], key=lambda x: -x["site_dates"]),
        }
        if method in SHOWN:
            shown.append(entry)
            by_site: dict[tuple, list[str]] = {}
            for lat, lon, day in sd:
                by_site.setdefault((lat, lon), []).append(day)
            for (lat, lon), ds in by_site.items():
                ds = sorted(x for x in ds if x)
                points.append({"lat": lat, "lon": lon, "method": method, "dates": len(ds) or 1,
                               "first": ds[0] if ds else None, "last": ds[-1] if ds else None})
        else:
            withheld.append({**entry, "reason": WITHHELD_REASON[method]})
    return {
        **base, "status": "ok", "absence_rows": total_rows,
        "methods": shown, "withheld": withheld,
        "points": points[:ND_MAX_POINTS], "points_truncated": len(points) > ND_MAX_POINTS,
    }


# --- eDNA evidence ----------------------------------------------------------------------------
#
# eDNA is a different kind of evidence from a sighting or a catch. A water sample is filtered, DNA
# is sequenced, and the sequences are matched to species. OBIS stores one row per species per
# sample, and for the datasets that publish a zero for every sequence variant that wasn't found,
# a "not detected" row for every sample the species wasn't in. So the unit here is the sampling
# event, reduced to a site-date, never the row.
#
# The rows are the slow part: 109,435 absence rows for mackerel, 10,000 to a page. They are read
# one dataset at a time, two datasets at once, with the paging OBIS documents, which is gentle on
# OBIS and takes about a minute for mackerel. (Splitting the ids into shards and reading them all
# at once took 20 s, but it leaned on how OBIS happens to order ids, and meant many simultaneous
# requests to a free public service. Slower and documented was the better trade for a public site.)
# The detections come first, within seconds; the non-detections follow from a background job that
# the browser polls, so nothing waits on them. The finished answer is cached for a month.

EDNA = "DNADerivedData"
EDNA_TTL_S = 30 * 24 * 3600
EDNA_MAX_ROWS = 300_000        # non-detection rows in a region; above this they are not attempted
EDNA_MAX_PRESENCE = 100_000    # detection rows in a region
EDNA_POINTS = 3000             # sites sent to the map
EDNA_EVENTS_MAX = 30_000       # sampling events kept per fish; far more than any fish has


def _edna_params(name: str, region: str) -> dict:
    return {**_filters(name, REGIONS[region]["bbox"], None, False), "hasextensions": EDNA}


def _edna_key(params: dict) -> str:
    return "edna:" + json.dumps({"p": sorted(params.items()), "v": 4})  # bump when the method changes


def _count(params: dict) -> int:
    q = urllib.parse.urlencode(sorted({**params, "size": 0}.items()))
    return int(_get(OBIS + "occurrence?" + q).get("total", 0))


def _by_dataset(params: dict, datasets: list[dict], limit: int, progress: dict | None = None, job=None) -> tuple[set, int, int, bool]:
    """The site-dates of every row for a query, read one dataset at a time, two datasets at once.
    Returns ({(site-date, dataset id)}, rows read, rows with no usable position, too_many)."""
    total = _count(params)
    if total == 0 or not datasets:
        return set(), 0, 0, False
    if total > limit:
        return set(), 0, 0, True
    if progress is not None:
        progress["total"] = progress.get("total", 0) + total
    stats = {"skipped": 0}

    def one(d: dict):
        keys, rows, _cut = _site_dates({**params, "datasetid": d["id"]}, limit, job, progress, stats)
        return {(k, d["id"]) for k in keys}, rows

    try:
        parts = list(_job_pool.map(one, datasets))
    except BaseException:
        if job:
            job.cancelled = True  # the dataset still waiting for a helper stops before sending anything
        raise
    return set().union(*(p[0] for p in parts)), sum(p[1] for p in parts), stats["skipped"], False


def _marker(d: dict) -> str:
    title = d.get("title") or ""
    text = f"{title} {re.sub(r'<[^>]+>', ' ', d.get('abstract') or '')}"
    if _method(d) == "edna_coi":
        found = re.findall(r"\bcoi\b|\b18s\b", title, re.I) or re.findall(r"\bcoi\b|\b18s\b", text, re.I)
        return "/".join(sorted({m.upper() for m in found})) or "general-purpose"
    found = sorted({m.upper() for m in FISH_MARKERS.findall(title)} or {m.upper() for m in FISH_MARKERS.findall(text)})
    return "/".join(found) if found else "not stated"


def _assemble(name, region, datasets, presence, absence, state, progress, notes) -> dict:
    """Detections and non-detections as site-dates, per dataset and per site. `absence` is None
    while the non-detections are still being fetched."""
    meta = {d["id"]: d for d in datasets}
    detected: set = set()
    det_by_ds: dict[str, set] = {}
    for k, ds in presence:  # (site-date, dataset id) pairs
        detected.add(k)
        det_by_ds.setdefault(ds, set()).add(k)
    nd_by_ds: dict[str, set] = {}
    reporting: set = set()
    for k, ds in absence or ():
        reporting.add(ds)
        # Zero-filled tables repeat the zeros for samples where the species WAS found; those are detections.
        if k not in detected:
            nd_by_ds.setdefault(ds, set()).add(k)

    ids = set(det_by_ds) | set(nd_by_ds) | reporting | {d["id"] for d in datasets}
    rows, shown_nd, withheld_nd = [], set(), set()
    for ds in ids:
        d = meta.get(ds, {"id": ds, "title": "Unknown dataset", "method": "other", "marker": "not stated"})
        method = d.get("method", "other")
        nd = nd_by_ds.get(ds, set())
        (withheld_nd if method == "edna_coi" else shown_nd).update(nd)
        rows.append({
            "id": ds, "title": d.get("title") or "Untitled dataset",
            "url": f"https://obis.org/dataset/{ds}" if ds else "",
            "marker": d.get("marker", "not stated"),
            "detected_site_dates": len(det_by_ds.get(ds, ())),
            "nondetected_site_dates": len(nd) if method != "edna_coi" else 0,
            "withheld_site_dates": len(nd) if method == "edna_coi" else 0,
            "reports_nondetections": ds in reporting,
        })
    rows = [r for r in rows if r["detected_site_dates"] or r["nondetected_site_dates"] or r["withheld_site_dates"] or r["reports_nondetections"]]
    rows.sort(key=lambda r: -(r["detected_site_dates"] + r["nondetected_site_dates"]))

    def span(keys):
        days = sorted(k[2] for k in keys if k[2])
        return (days[0], days[-1]) if days else (None, None)

    by_site: dict[tuple, dict] = {}
    by_year: dict[str, dict] = {}
    for status, keys in (("detected", detected), ("not_detected", shown_nd)):
        for lat, lon, day in keys:
            s = by_site.setdefault((lat, lon), {"lat": lat, "lon": lon, "detected": 0, "not_detected": 0, "days": []})
            s[status] += 1
            if day:
                s["days"].append(day)
                y = by_year.setdefault(day[:4], {"year": int(day[:4]), "detected": 0, "not_detected": 0})
                y[status] += 1
    points = []
    for s in by_site.values():
        days = sorted(s.pop("days"))
        s["first"], s["last"] = (days[0], days[-1]) if days else (None, None)
        points.append(s)
    points.sort(key=lambda p: (-p["detected"], -p["not_detected"]))

    d_first, d_last = span(detected)
    n_first, n_last = span(shown_nd)
    return {
        "species": name, "region": region, "label": REGIONS[region]["label"],
        "status": "ok" if (detected or reporting or shown_nd) else "none",
        "detections": {
            "site_dates": len(detected), "sites": len({k[:2] for k in detected}),
            "first_date": d_first, "last_date": d_last,
        },
        "nondetections": {
            "state": state, "progress": progress,
            "site_dates": len(shown_nd), "sites": len({k[:2] for k in shown_nd}),
            "first_date": n_first, "last_date": n_last,
            "withheld": ([{"method": "edna_coi", "label": "General-purpose marker (COI or 18S)", "site_dates": len(withheld_nd),
                           "reason": WITHHELD_REASON["edna_coi"]}] if withheld_nd else []),
        },
        "datasets": rows,
        "by_year": sorted(by_year.values(), key=lambda y: y["year"]),
        "points": points[:EDNA_POINTS], "points_truncated": len(points) > EDNA_POINTS,
        "notes": notes,
    }


def _light(d: dict) -> dict:
    """What is kept of a dataset: its name, and the method and marker read from its description."""
    return {"id": d["id"], "title": d.get("title") or "Untitled dataset", "method": _method(d), "marker": _marker(d)}


def _base(datasets, presence, absence, state, notes) -> dict:
    """What an eDNA calculation keeps: its sampling events ([lat, lon, day, dataset id]), not the
    counts made from them, so any year range can be counted from it later without asking OBIS
    again. Too many events (far more than any fish has) are refused rather than cached."""
    pres = sorted([*k, ds] for k, ds in presence)
    absn = None if absence is None else sorted([*k, ds] for k, ds in absence)
    notes = list(notes)
    if len(pres) + len(absn or ()) > EDNA_EVENTS_MAX:
        pres, absn, state = [], None, "too_many"
        notes.append("Too many sampling events to summarise.")
    return {"datasets": datasets, "presence": pres, "absence": absn, "state": state, "notes": notes}


def _edna_view(base: dict, name: str, region: str, since: int | None, until: int | None, progress=None) -> dict:
    """The eDNA answer for a year range, counted from the kept events. With no range it is all
    years. `available` always spans every year OBIS has samples for, so a range with nothing in it
    can say where the samples are."""
    keep = lambda e: in_range(e[2], since, until)
    presence = {((e[0], e[1], e[2]), e[3]) for e in base["presence"] if keep(e)}
    absence = None if base["absence"] is None else {((e[0], e[1], e[2]), e[3]) for e in base["absence"] if keep(e)}
    out = _assemble(name, region, base["datasets"], presence, absence, base["state"], progress, base["notes"])
    days = sorted(e[2] for e in (*base["presence"], *(base["absence"] or ())) if e[2])
    out["range"] = {"since": since, "until": until}
    out["available"] = {"first_date": days[0] if days else None, "last_date": days[-1] if days else None}
    if (since is not None or until is not None) and base["state"] == "too_many":
        out["notes"] = [*out["notes"], "Year ranges can't be applied to this fish."]
    return out


def _public(data: dict, meta: dict) -> dict:
    return {**{k: v for k, v in data.items() if k != "site_dates"}, **_provenance(meta)}


def _finish(job, key: str, kind: str, data: dict) -> None:
    """Store a finished result in the disk cache. If the cache won't take it (too big, or the disk
    is short of space) the job keeps it in memory for a few minutes instead, so it isn't lost."""
    job.fetched_at = time.time()
    if not api_cache.write(key, data, kind, job.fetched_at):
        job.result = data


def _serve(key: str, kind: str, ttl: float, work, wait: float, on_start, skeleton, partial=None, render=None) -> dict:
    """The answer for something computed by a background job.

    A cached answer, if still fresh, comes straight back. Otherwise the job for `key` is joined or
    started (identical requests share one job; `on_start` may refuse a visitor who starts too many).
    This waits up to `wait` seconds for the first result and then answers with whatever there is:
    the finished answer, an expired cached one marked stale, the job's partial result, or a
    "computing" or "queued" placeholder to poll again. The request never waits for the whole job.
    `render`, if given, turns what is stored into the answer for this request (a year range)."""
    shape = render or (lambda data: data)
    cached = api_cache.read(key, kind)
    if cached and time.time() - cached["fetched_at"] < ttl:
        return _public(shape(cached["data"]), {"fetched_at": cached["fetched_at"], "cached": True})

    def stale() -> dict:
        return {**_public(shape(cached["data"]), {"fetched_at": cached["fetched_at"], "cached": True, "stale": True}), "refreshing": True}

    job = api_guard.jobs.get(key)
    if job is None or (job.state == "done" and job.result is None):
        try:
            job, _ = api_guard.jobs.start(key, work, on_start)
        except (Busy, RateLimited):
            if cached:
                return stale()  # too busy to refresh, so show the older answer
            raise
    if job.state == "queued" and api_guard.jobs.ahead_of(job) > 0:
        wait = min(wait, 0.5)  # behind other calculations: don't hold a request thread for a turn that isn't near
    job.ready.wait(wait)

    if job.state == "done":
        again = api_cache.read(key, kind)
        if again:
            return _public(shape(again["data"]), {"fetched_at": again["fetched_at"], "cached": True})
        if job.result is not None:
            return _public(shape(job.result), {"fetched_at": job.fetched_at, "cached": False})
    if job.state == "failed":
        if cached:
            return {**stale(), "refreshing": False}
        raise Unavailable(f"The calculation could not finish ({job.error}). Try again later.", 60)
    if cached:
        return stale()
    if job.partial is not None and partial:
        return partial(job)
    return {**skeleton("queued" if job.state == "queued" else "computing", api_guard.jobs.ahead_of(job) if job.state == "queued" else 0), **_provenance({})}


def _edna_work(job, key: str, name: str, region: str, params: dict) -> None:
    """Detections first (published as soon as they're ready), then the non-detections."""
    notes: list[str] = []

    def datasets_of(absence: bool) -> list[dict]:
        job.check()
        q = {**params, "size": 200, **({"absence": "true"} if absence else {})}
        return _get(OBIS + "dataset?" + urllib.parse.urlencode(sorted(q.items()))).get("results", [])

    listings = [_job_pool.submit(datasets_of, a) for a in (False, True)]
    present_ds, absent_ds = (f.result() for f in listings)  # datasets with detections, and datasets with zeros
    datasets = [_light(d) for d in {d["id"]: d for d in present_ds + absent_ds}.values()]
    presence, rows_p, skipped_p, too_many = _by_dataset(params, present_ds, EDNA_MAX_PRESENCE, job=job)
    if skipped_p:
        notes.append(f"{skipped_p:,} detection rows have no usable position and are left out.")
    if too_many:
        final = _base(datasets, set(), None, "too_many", ["Too many eDNA detection rows to summarise."])
        return _finish(job, key, "edna-", final)
    job.check()
    absent_total = _count({**params, "absence": "true"})
    if absent_total == 0:
        final = _base(datasets, presence, None, "none", notes)
    elif absent_total > EDNA_MAX_ROWS:
        final = _base(datasets, presence, None, "too_many",
                      notes + [f"{absent_total:,} non-detection rows is more than can be reduced to sampling events here."])
    else:
        progress = {"done": 0, "total": 0}
        job.progress = progress
        job.partial = _base(datasets, presence, None, "computing", notes)
        job.ready.set()  # the detections can be shown now
        absence, _rows_seen, skipped, _ = _by_dataset({**params, "absence": "true"}, absent_ds, EDNA_MAX_ROWS, progress, job)
        if skipped:  # rows with no usable position can't make a site-date
            notes.append(f"{skipped:,} non-detection rows have no usable position and are left out.")
        if _rows_seen < absent_total:  # more datasets than one listing returns, or ones that changed meanwhile
            notes.append(f"{absent_total - _rows_seen:,} non-detection rows belong to datasets that couldn't be read and are left out.")
        final = _base(datasets, presence, absence, "ready", notes)
    _finish(job, key, "edna-", final)


def _edna_partial(job, name: str, region: str, since, until) -> dict:
    out = _public(_edna_view(job.partial, name, region, since, until), {"fetched_at": None})
    if job.progress:
        out["nondetections"] = {**out["nondetections"], "progress": {"done": job.progress["done"], "total": job.progress["total"]}}
    return out


def edna_evidence(name: str, region: str, wait: float | None = None, on_start=None, since: int | None = None, until: int | None = None) -> dict:
    """eDNA detections and non-detections for a species, as site-dates, in one of REGIONS.

    Detection: a water sample, at one site on one day, in which the species' DNA was found.
    Non-detection: a sample from a dataset that reports its zeros, in which it wasn't, and in which
    no dataset found it. That is not absence: eDNA misses fish that are there. A site-date counts
    once however many sequence variants, markers or datasets cover it.

    The first request for a species starts a background job and returns the detections as soon as
    they're ready (`nondetections.state == "computing"`, with progress). Ask again to follow it; the
    finished result is cached for a month, and an expired copy is served while a new one is built.

    `since` and `until` pick a year range (see check_range). The calculation always covers every
    year, once; a range only changes which of its sampling events are counted, so choosing one
    costs no request to OBIS and starts no job.
    """
    if region not in REGIONS:
        raise ValueError(f"region must be one of {', '.join(REGIONS)}")
    since, until = check_range(since, until)
    wait = RESULT_WAIT_S if wait is None else wait
    params = _edna_params(name, region)
    key = _edna_key(params)

    def skeleton(state, ahead):  # nothing to show yet: the browser asks again
        return {
            "species": name, "region": region, "label": REGIONS[region]["label"], "status": "computing",
            "detections": None, "nondetections": {"state": state, "progress": None, "ahead": ahead},
            "datasets": [], "by_year": [], "points": [], "notes": [],
        }

    return _serve(key, "edna-", EDNA_TTL_S, lambda job: _edna_work(job, key, name, region, params),
                  wait, on_start, skeleton, partial=lambda job: _edna_partial(job, name, region, since, until),
                  render=lambda data: _edna_view(data, name, region, since, until))


def nearby_site_dates(name: str, region: str, lat: float, lon: float, radius_km: float = 10.0,
                      since: str | None = None, until: str | None = None) -> dict | None:
    """The cached eDNA site-dates within `radius_km` of a point and between two ISO dates, with
    their distance. A building block for comparing eDNA with a video location later; nothing
    calls it yet. None when the evidence for this species and region hasn't been computed.

    It deliberately does not say the two kinds of evidence agree or disagree: an eDNA sample
    reflects DNA in a water volume that may have drifted or persisted for days, a video reflects
    what passed one camera in minutes, and an eDNA non-detection can't contradict a fish on video.
    The caveats are returned with the matches so a caller can't drop them by accident."""
    cached = api_cache.read(_edna_key(_edna_params(name, region)), "edna-")
    if not cached:
        return None
    from math import asin, cos, radians, sin, sqrt

    def km(a_lat, a_lon):
        p, q = radians(a_lat), radians(lat)
        h = sin((q - p) / 2) ** 2 + cos(p) * cos(q) * sin(radians(lon - a_lon) / 2) ** 2
        return 2 * 6371.0 * asin(sqrt(h))

    base = cached["data"]
    method = {d["id"]: d.get("method") for d in base["datasets"]}
    detected = {tuple(e[:3]) for e in base["presence"]}
    # Same rules as the section on the map: a zero where the fish was found is a detection, and
    # non-detections from general-purpose markers are not offered as evidence.
    events = [(*e[:3], "detected") for e in base["presence"]]
    events += [(*e[:3], "not_detected") for e in (base["absence"] or []) if tuple(e[:3]) not in detected and method.get(e[3]) != "edna_coi"]
    hits = []
    for s_lat, s_lon, day, status in events:
        d = km(s_lat, s_lon)
        if d <= radius_km and (not since or (day and day >= since)) and (not until or (day and day <= until)):
            hits.append({"lat": s_lat, "lon": s_lon, "date": day, "status": status, "distance_km": round(d, 2)})
    hits.sort(key=lambda h: h["distance_km"])
    return {
        "species": name, "center": [lat, lon], "radius_km": radius_km, "matches": hits,
        "caveats": [
            "eDNA is DNA in filtered water, not a sighting: it can drift or persist for days, and it can come from dead or processed fish.",
            "A non-detection is not evidence the fish was absent, and says nothing against a fish seen on video.",
            "Only compare when the place, the dates and the question (this species, this habitat) genuinely overlap.",
        ],
    }


def _sort_key(r: dict) -> float:
    """Milliseconds since 1970 from OBIS's parsed date, else the start of the year, else oldest."""
    if isinstance(r.get("date_mid"), (int, float)):
        return float(r["date_mid"])
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", (r.get("eventDate") or "").strip())
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc).timestamp() * 1000
        except ValueError:
            pass  # e.g. 2020-02-30: fall back to the year
    if r.get("date_year"):
        return float(datetime(int(r["date_year"]), 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    return float("-inf")


def _display_date(r: dict) -> str:
    """ISO day from OBIS's parsed date. When OBIS couldn't parse eventDate, show what was recorded."""
    if isinstance(r.get("date_mid"), (int, float)):
        # Not datetime.fromtimestamp: on Windows it refuses anything before 1970, and OBIS has records from the 1700s.
        try:
            return (EPOCH + timedelta(milliseconds=r["date_mid"])).date().isoformat()
        except OverflowError:
            pass
    text = (r.get("eventDate") or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    if text:
        return f"{text} (as recorded)"
    return str(r["date_year"]) if r.get("date_year") else ""


def _record(r: dict) -> dict:
    lic = r.get("license") or ""
    return {
        "id": r.get("id"),
        "date": _display_date(r),
        "year": r.get("date_year"),
        "lat": r.get("decimalLatitude"), "lon": r.get("decimalLongitude"),
        "uncertainty_m": r.get("coordinateUncertaintyInMeters"),
        "depth_m": r.get("minimumDepthInMeters") if r.get("minimumDepthInMeters") is not None else r.get("maximumDepthInMeters"),
        "dataset": r.get("datasetName") or "",
        "dataset_url": f"https://obis.org/dataset/{r['dataset_id']}" if r.get("dataset_id") else "",
        "institution": r.get("institutionCode") or "",
        "basis": r.get("basisOfRecord") or "",
        "recorded_by": r.get("recordedBy") or "",
        "count": r.get("individualCount"),
        "absent": bool(r.get("absence")),
        "name_as_recorded": r.get("scientificName") or "",
        "license": lic,
    }


def _dataset(d: dict) -> dict:
    title = d.get("title") or "Untitled dataset"
    institution = ", ".join(i.get("name", "") for i in (d.get("institutes") or [])[:2] if i.get("name"))
    return {
        "id": d.get("id"),
        "title": title,
        "records": d.get("records") or (d.get("statistics") or {}).get("Occurrence"),
        "institution": institution,
        "url": f"https://obis.org/dataset/{d['id']}" if d.get("id") else "",
        "telemetry": bool(TELEMETRY.search(title) or TELEMETRY.search(institution)),
    }


def _provenance(meta: dict | None) -> dict:
    meta = meta or {}
    return {
        "source": "OBIS",
        "fetched_at": meta.get("fetched_at"),
        "cached": meta.get("cached", False),
        "stale": meta.get("stale", False),
        "citation": "OBIS (2026) Ocean Biodiversity Information System. Intergovernmental Oceanographic Commission of UNESCO. https://obis.org",
    }


def warm(region: str, names: list[str]) -> None:
    """Build and cache the eDNA evidence for the species you name, so the first person to open
    their Map tab finds it ready. Nothing runs this by itself and there is deliberately no "all
    species" option. Run from the server folder:
        python -m tidecount.occurrences atlantic-canada "Scomber scombrus" "Gadus morhua"
    It goes through the same request budget and job limits as the website."""
    from . import models
    listed = {row["species"] for row in models.species_table()}
    for name in names:
        if name not in listed:
            print(f"{name}: not on the species list", flush=True)
            continue
        params = _edna_params(name, region)
        try:
            n = _job_pool.submit(lambda: _count(params) + _count({**params, "absence": "true"})).result()
        except Exception as e:  # OBIS hiccup: skip this one, keep going
            print(f"{name}: skipped ({e.__class__.__name__})", flush=True)
            continue
        if not n:
            continue
        t = time.time()
        try:
            while edna_evidence(name, region, wait=5)["nondetections"]["state"] in ("computing", "queued"):
                time.sleep(2)
        except (Busy, Unavailable) as e:  # the same limits as the website: wait, and move on to the next
            print(f"{name}: skipped ({e})", flush=True)
            continue
        print(f"{name}: {n:,} eDNA detection rows, ready in {time.time() - t:.0f}s", flush=True)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3 or sys.argv[1] not in REGIONS:
        sys.exit(f'usage: python -m tidecount.occurrences <{"|".join(REGIONS)}> "Scientific name" ["Scientific name" ...]')
    warm(sys.argv[1], sys.argv[2:])
