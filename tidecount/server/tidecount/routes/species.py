"""The species list, read-only, and the species wiki built on it.

The list is edited in tidecount/species.csv and is what BioCLIP chooses from. The wiki's photos,
notes, checked names and OBIS maps sit beside it and never change it.
"""
import math

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .. import db, models, api_guard, occurrences, species_media

router = APIRouter()


@router.get("/api/species")
def species():
    """Every fish the suggester may name, and how many tracks a person has given that name here."""
    with db.session() as con:
        named = dict(con.execute("SELECT species, COUNT(*) FROM decisions WHERE state != 'Rejected' AND species IS NOT NULL GROUP BY species").fetchall())
    return [{**row, "confirmed": named.get(row["common"], 0)} for row in models.species_table()]


@router.get("/api/species/media")
def species_media_summary():
    """Which species have reference photos or notes, keyed by scientific name."""
    return species_media.summaries()


def _listed(name: str) -> str:
    if name not in {row["species"] for row in models.species_table()}:
        raise HTTPException(404, "That species is not on the list")
    return name


@router.get("/api/species/{name}/profile")
def species_profile(name: str):
    """Reference photos with credits and licences, identification notes and the checked name for
    one scientific name. Species nobody has curated yet come back with `curated: false`."""
    return species_media.profile(_listed(name))


def _retry(seconds) -> dict:
    return {"Retry-After": str(max(1, int(math.ceil(seconds or 5))))}


def wiki_guard(request: Request):
    """Runs before every map and eDNA call, which can reach out to OBIS. A visitor who asks too
    often gets a 429. Only a few such calls run at once, so a burst can't take every request thread
    the video review and uploads share; the rest are told to try again. Cached answers count too:
    it is the number of requests, not only the number that reach OBIS, that is limited."""
    ip = api_guard.client_ip(request.client.host if request.client else None, request.headers.get("x-forwarded-for"))
    wait = api_guard.visits.check(ip)
    if wait is not None:
        raise HTTPException(429, "You're asking for map data very quickly. Wait a moment and try again.", headers=_retry(wait))
    if not api_guard.inflight.acquire(blocking=False):
        raise HTTPException(503, "The server is busy with other map requests. Try again in a few seconds.", headers=_retry(3))
    try:
        yield ip
    finally:
        api_guard.inflight.release()


def _obis(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except occurrences.RateLimited as e:
        raise HTTPException(429, str(e), headers=_retry(e.retry_after))
    except occurrences.Unavailable as e:
        raise HTTPException(503, str(e), headers=_retry(e.retry_after))
    except occurrences.Busy as e:  # the outbound budget, a full job queue or a paused OBIS
        raise HTTPException(503, str(e.reason), headers=_retry(e.retry_after))


guard = [Depends(wiki_guard)]


@router.get("/api/species/{name}/occurrences/summary", dependencies=guard)
def occurrence_summary(name: str, region: str = "atlantic-canada", method: str | None = None, dataset: str | None = None):
    """OBIS record totals, years and main datasets for one region, optionally only for one
    observation method or one dataset (see /occurrences/datasets)."""
    return _obis(occurrences.summary, _listed(name), region, method or None, dataset or None)


@router.get("/api/species/{name}/occurrences/datasets", dependencies=guard)
def occurrence_datasets(name: str, region: str = "atlantic-canada"):
    """Every OBIS dataset with records of the species in a region, each with its observation method
    as its OBIS metadata states it. The map's method and dataset filters choose from this list."""
    return _obis(occurrences.catalog, _listed(name), region)


@router.get("/api/species/{name}/occurrences/nondetections")
def occurrence_nondetections(name: str):
    """Withdrawn: always 410 Gone, and nothing is asked of OBIS. The net, trawl and seine
    non-detection counts weren't defensible. OBIS flags a zero count as an absence even where the
    survey recorded the fish as present with a catch weight (all 4 Winter Flounder "absences" in the
    DFO Gulf groundfish survey), and the tows that caught nothing aren't published. The calculation,
    occurrences.nondetections, is kept for a sounder version. eDNA evidence is unaffected: see
    /occurrences/edna."""
    raise HTTPException(410, "Survey non-detections have been withdrawn: OBIS's zero-count records "
                             "for net, trawl and seine surveys don't reliably mean the fish wasn't caught. "
                             "eDNA evidence is still available at /occurrences/edna.")


@router.get("/api/species/{name}/occurrences/edna")
def occurrence_edna(
    name: str,
    region: str = "atlantic-canada",
    since: int | None = Query(None, ge=1700, le=2100),
    until: int | None = Query(None, ge=1700, le=2100),
    ip: str = Depends(wiki_guard),
):
    """eDNA detections and non-detections as sampling site-dates, for every year or for the year
    range `since`..`until` (counted from one cached calculation, so a range costs no OBIS request).
    Returns the detections within seconds and, while `nondetections.state` is "computing" or
    "queued", the rest is being built in the background: ask again. Cached for a month once finished."""
    return _obis(lambda: occurrences.edna_evidence(_listed(name), region, on_start=lambda: api_guard.charge_job_start(ip), since=since, until=until))


@router.get("/api/species/{name}/occurrences/grid", dependencies=guard)
def occurrence_grid(
    name: str,
    bbox: str = "",
    precision: int = Query(3, ge=2, le=6),
    since: int | None = Query(None, ge=1700, le=2100),
    until: int | None = Query(None, ge=1700, le=2100),
    region: str | None = None,
    method: str | None = None,
    dataset: str | None = None,
):
    """OBIS records counted in grid cells, for every year or the whole years `since`..`until`. The
    view is rounded out to the map's own steps, so near-identical requests share one answer.
    `method` or `dataset` keep only those datasets of `region`'s list (see /occurrences/datasets)."""
    return _obis(lambda: occurrences.grid(_listed(name), occurrences.parse_bbox(bbox), precision, since, until,
                                          region, method or None, dataset or None))


@router.get("/api/species/{name}/occurrences/records", dependencies=guard)
def occurrence_records(
    name: str,
    bbox: str,
    since: int | None = Query(None, ge=1700, le=2100),
    until: int | None = Query(None, ge=1700, le=2100),
    region: str | None = None,
    method: str | None = None,
    dataset: str | None = None,
):
    """Individual OBIS occurrence records inside one of the map's grid cells, newest first, for every
    year or the years `since`..`until`, with the same method and dataset filters as /grid. Absence
    records aren't listed one by one: see /occurrences/nondetections."""
    return _obis(lambda: occurrences.records(_listed(name), occurrences.parse_bbox(bbox), since, until=until,
                                             region=region, method=method or None, dataset=dataset or None))
