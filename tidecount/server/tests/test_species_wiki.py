"""The species wiki: profiles, checked names and the OBIS map proxy. No test touches the network."""
import json
import urllib.error
import urllib.parse
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from tidecount import models, api_cache, api_guard, occurrences, species_media
from tidecount.app import app

client = TestClient(app)


@pytest.fixture
def obis(monkeypatch, tmp_path):
    """A fake OBIS. Records every URL asked for, and answers from `answers` by path prefix."""
    monkeypatch.setattr(api_cache.config, "DATA", tmp_path)
    monkeypatch.setattr(api_cache, "MIN_FREE_BYTES", 0)  # the test machine's free disk is no business of these tests
    api_guard.reset()  # visitor limits, the request budget and background jobs are shared state
    calls, answers = [], {}

    def fake_get(url):
        calls.append(url)
        path = url.split("/v3/", 1)[1].split("?", 1)[0]
        for prefix, answer in answers.items():
            if path.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                if callable(answer):  # answers that depend on the query, e.g. absence=true or datasetid
                    return answer(dict(urllib.parse.parse_qsl(url.split("?", 1)[1])))
                return answer
        raise AssertionError(f"unexpected OBIS call {url}")

    monkeypatch.setattr(occurrences, "_get", fake_get)
    yield calls, answers
    # A background job must not outlive the fake OBIS: it would go on to call the real one.
    for _ in range(200):
        if api_guard.jobs.active() == 0:
            break
        time.sleep(0.05)
    assert api_guard.jobs.active() == 0


def cell(w, s, e, n, count):
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}, "properties": {"n": count}}


def a_cell(precision=5, col=2650, row=2400) -> str:
    """`west,south,east,north` of a real OBIS geohash cell, rounded to five decimals as the grid reports them."""
    cw, ch = occurrences._cell_size(precision)
    return ",".join(str(round(v, 5)) for v in (-180 + col * cw, -90 + row * ch, -180 + (col + 1) * cw, -90 + (row + 1) * ch))


def test_the_ai_list_is_untouched_by_the_wiki():
    assert len(models.species_list()) == 182


def test_every_listed_name_has_been_checked_and_uses_its_aphia_id():
    for row in models.species_table():
        assert species_media.taxonomy(row["species"]) is not None, row["species"]
    assert occurrences.taxon_filter("Gadus morhua") == {"taxonid": 126436}


def test_a_synonym_on_the_list_is_queried_by_its_accepted_id():
    names = species_media.taxonomy("Gadus ogac")
    assert names["status"] != "accepted"
    assert occurrences.taxon_filter("Gadus ogac") == {"taxonid": names["accepted_aphia_id"]}


def test_profile_links_back_from_entries_that_mention_a_species():
    # Haddock's entry compares itself with cod, so cod's profile should know.
    cod = client.get("/api/species/Gadus morhua/profile").json()
    assert "Melanogrammus aeglefinus" in {m["species"] for m in cod["mentioned_by"]}
    assert cod["names"]["aphia_id"] == 126436


def test_profile_for_an_unlisted_species_is_404():
    assert client.get("/api/species/Homo sapiens/profile").status_code == 404


def test_an_unknown_api_path_answers_json_not_the_web_page():
    # The bug: the UI's catch-all route sent index.html, so the map failed with "Unexpected token '<'".
    for path in ["/api/species/Gadus morhua/occurrences/nonsense", "/api/nope", "/api"]:
        r = client.get(path)
        assert r.status_code == 404, path
        assert r.headers["content-type"].startswith("application/json"), path
        assert "No such API endpoint" in r.json()["detail"]


def test_every_occurrence_endpoint_the_map_calls_is_registered():
    # The map's three calls must reach real routes, never the UI's catch-all.
    # The OpenAPI schema lists what is really registered; app.routes hides routes of included routers.
    paths = set(client.get("/openapi.json").json()["paths"])
    for p in ["/api/species/{name}/occurrences/summary", "/api/species/{name}/occurrences/grid", "/api/species/{name}/occurrences/records",
              "/api/species/{name}/occurrences/nondetections", "/api/species/{name}/occurrences/edna", "/api/species/{name}/profile"]:
        assert p in paths, p


def test_profile_always_has_the_fields_the_drawer_reads():
    for name in ["Gadus morhua", "Tautogolabrus adspersus", "Gadus ogac", "Mola mola", "Myoxocephalus aenaeus"]:
        p = client.get(f"/api/species/{name}/profile").json()
        assert {"species", "curated", "taxon", "images", "profile", "names", "mentioned_by"} <= p.keys(), name
        assert isinstance(p["images"], list) and isinstance(p["mentioned_by"], list), name


def test_a_malformed_look_alike_entry_does_not_break_profiles(monkeypatch, tmp_path):
    broken = tmp_path / "profiles.json"
    broken.write_text('{"species": {"Gadus morhua": {"summary": "x", "similar": [{"note": "no name"}, "junk", {"species": "Pollachius virens"}]}}}', encoding="utf-8")
    monkeypatch.setattr(species_media.config, "SPECIES_PROFILES", broken)
    r = client.get("/api/species/Pollachius virens/profile")
    assert r.status_code == 200
    assert r.json()["mentioned_by"] == [{"species": "Gadus morhua", "note": ""}]


def test_grid_counts_occurrence_records_only(obis):
    calls, answers = obis
    answers["occurrence/grid/4"] = {"features": [cell(-64, 44, -63.65, 44.18, 12), cell(-63, 44, -62.65, 44.18, 3000)]}

    g = client.get("/api/species/Gadus morhua/occurrences/grid", params={"bbox": "-65,43,-60,46", "precision": 4}).json()

    assert g["present"][0] == [-63, 44, -62.65, 44.18, 3000]  # busiest first
    assert "absent" not in g  # raw absence rows are never gridded; see /nondetections
    assert len(calls) == 1 and "absence" not in calls[0] and "taxonid=126436" in calls[0]
    assert g["source"] == "OBIS" and not g["cached"]


def test_a_second_request_comes_from_the_cache(obis):
    calls, answers = obis
    answers["occurrence/grid/3"] = {"features": []}
    params = {"bbox": "-70,40,-50,53", "precision": 3}
    client.get("/api/species/Gadus morhua/occurrences/grid", params=params)
    again = client.get("/api/species/Gadus morhua/occurrences/grid", params=params).json()
    assert len(calls) == 1
    assert again["cached"]


def test_an_old_copy_is_used_when_obis_is_down(obis, monkeypatch):
    calls, answers = obis
    answers["occurrence/grid/3"] = {"features": [cell(-64, 44, -62.6, 45.4, 5)]}
    params = {"bbox": "-70,40,-50,53", "precision": 3}
    client.get("/api/species/Gadus morhua/occurrences/grid", params=params)
    monkeypatch.setattr(occurrences, "CACHE_TTL_S", -1)  # everything cached is now out of date
    answers["occurrence/grid/3"] = urllib.error.URLError("offline")

    g = client.get("/api/species/Gadus morhua/occurrences/grid", params=params).json()

    assert g["stale"] and g["present"][0][4] == 5


def test_obis_down_with_nothing_cached_is_503(obis):
    _, answers = obis
    answers["occurrence"] = urllib.error.URLError("offline")
    r = client.get("/api/species/Gadus morhua/occurrences/grid", params={"bbox": "-70,40,-50,53", "precision": 3})
    assert r.status_code == 503


def test_fine_grids_need_a_small_area(obis):
    r = client.get("/api/species/Gadus morhua/occurrences/grid", params={"bbox": "-70,40,-50,53", "precision": 5})
    assert r.status_code == 400
    r = client.get("/api/species/Gadus morhua/occurrences/grid", params={"bbox": "1,2,3", "precision": 3})
    assert r.status_code == 400


def test_records_are_newest_first(obis):
    _, answers = obis
    answers["occurrence"] = {"total": 3, "results": [
        {"id": "a", "eventDate": "1990-07-30T12:45:00-0300", "decimalLatitude": 44.1, "decimalLongitude": -63.2, "datasetName": "Summer survey", "dataset_id": "d1"},
        {"id": "b", "eventDate": "2022-06-09 20:04:16", "decimalLatitude": 44.2, "decimalLongitude": -63.3, "absence": True},
        {"id": "c", "date_year": 2005, "decimalLatitude": 44.3, "decimalLongitude": -63.4},
    ]}

    r = client.get("/api/species/Gadus morhua/occurrences/records", params={"bbox": a_cell()}).json()

    assert [x["id"] for x in r["records"]] == ["b", "c", "a"]
    assert r["records"][0]["date"] == "2022-06-09"
    assert r["records"][2]["dataset_url"] == "https://obis.org/dataset/d1"


def test_summary_flags_tag_detections_that_inflate_counts(obis):
    _, answers = obis
    answers["statistics/years"] = []
    answers["dataset"] = {"total": 2, "results": [
        {"id": "t", "title": "Gilbert Bay Telemetry", "records": 900},
        {"id": "s", "title": "Maritimes Summer Research Vessel Surveys", "records": 100},
    ]}
    answers["occurrence"] = {"total": 1000, "results": []}

    s = client.get("/api/species/Gadus morhua/occurrences/summary").json()

    assert [d["telemetry"] for d in s["datasets"]] == [True, False]
    assert s["telemetry_share"] == 0.9


def test_mark_and_recapture_tagging_is_not_counted_as_telemetry():
    flagged = occurrences._dataset({"id": "m", "title": "DFO Maritimes - Groundfish and Small Pelagic Tagging database. 1953-1999"})
    otn = occurrences._dataset({"id": "o", "title": "Inner Bay of Fundy Striped Bass", "institutes": [{"name": "Ocean Tracking Network"}]})
    assert (flagged["telemetry"], otn["telemetry"]) == (False, True)


def test_records_sort_on_the_parsed_date_not_the_text(obis):
    # Found in the browser on cunner: "9/1/2022" sorted above every ISO date and was shown as newest.
    _, answers = obis
    answers["occurrence"] = {"total": 3, "results": [
        {"id": "us", "eventDate": "9/1/2022", "date_year": 2022, "decimalLatitude": 44.9, "decimalLongitude": -62.4},
        {"id": "new", "eventDate": "2025-08-06", "date_mid": 1754438400000, "decimalLatitude": 44.9, "decimalLongitude": -62.4},
        {"id": "old", "eventDate": "1999-05-01T10:00:00", "date_mid": 925552800000, "decimalLatitude": 44.9, "decimalLongitude": -62.4},
    ]}

    r = client.get("/api/species/Tautogolabrus adspersus/occurrences/records", params={"bbox": a_cell()}).json()

    assert [x["id"] for x in r["records"]] == ["new", "us", "old"]
    assert [x["date"] for x in r["records"]] == ["2025-08-06", "9/1/2022 (as recorded)", "1999-05-01"]


def test_records_before_1970_have_dates(obis):
    # Found in the browser on brook trout: a 1923 record's negative timestamp made the endpoint 500 on Windows.
    _, answers = obis
    ms = lambda y, m, d: int((datetime(y, m, d, tzinfo=timezone.utc) - occurrences.EPOCH).total_seconds() * 1000)
    answers["occurrence"] = {"total": 2, "results": [
        {"id": "1923", "eventDate": "1923-07-15", "date_mid": ms(1923, 7, 15), "decimalLatitude": 44.9, "decimalLongitude": -62.5},
        {"id": "1753", "date_mid": ms(1753, 1, 1), "date_year": 1753, "decimalLatitude": 44.9, "decimalLongitude": -62.5},
    ]}

    r = client.get("/api/species/Salvelinus fontinalis/occurrences/records", params={"bbox": a_cell()})

    assert r.status_code == 200
    assert [x["date"] for x in r.json()["records"]] == ["1923-07-15", "1753-01-01"]


def test_records_refuse_a_huge_area(obis):
    r = client.get("/api/species/Gadus morhua/occurrences/records", params={"bbox": "-70,40,-50,53"})
    assert r.status_code == 400


def test_summary_counts_records_years_and_datasets_and_no_absence_total(obis):
    _, answers = obis
    answers["statistics/years"] = [{"year": 1970, "records": 4}, {"year": 2012, "records": 6}, {"year": 2020, "records": 0}]
    answers["dataset"] = {"total": 1, "results": [{"id": "d1", "title": "Maritimes survey", "records": 10, "institutes": [{"name": "BIO"}]}]}
    answers["occurrence"] = {"total": 10, "results": []}

    s = client.get("/api/species/Gadus morhua/occurrences/summary", params={"region": "nova-scotia"}).json()

    assert (s["first_year"], s["last_year"], s["since_2010"]) == (1970, 2012, 6)
    assert s["datasets"][0] == {"id": "d1", "title": "Maritimes survey", "records": 10, "institution": "BIO", "url": "https://obis.org/dataset/d1", "telemetry": False}
    assert s["telemetry_share"] == 0.0
    assert "absent" not in s  # the raw absence total misled more than it told
    assert client.get("/api/species/Gadus morhua/occurrences/summary", params={"region": "mars"}).status_code == 400


# --- non-detections, modelled on what OBIS really holds for mackerel in Atlantic Canada ---------

def row(i, lat, lon, day):
    return {"id": f"r{i}", "decimalLatitude": lat, "decimalLongitude": lon, "eventDate": day}


def edna_world(obis):
    """Two eDNA marker datasets from the same water samples, a seabed-imagery dataset, a trawl
    survey and a COI-only zooplankton dataset, with the zero-filled rows eDNA tables really have."""
    _, answers = obis
    datasets = [
        {"id": "e12", "title": "Coastal eDNA metabarcoding (12S)", "records": 9, "extensions": ["dnaderiveddata"]},
        {"id": "e16", "title": "Coastal eDNA metabarcoding (16S)", "records": 3, "extensions": ["dnaderiveddata"]},
        {"id": "img", "title": "Taxa from near-seafloor optical surveys", "abstract": "<p>High-resolution still images from a drop camera.</p>", "records": 2},
        {"id": "rv", "title": "Gulf Region Groundfish Research Vessel Surveys", "records": 1},
        {"id": "coi", "title": "Zooplankton Metabarcoding (COI) 2019", "abstract": "COI marker", "records": 1, "extensions": ["dnaderiveddata"]},
    ]
    answers["dataset"] = lambda q: {"total": len(datasets), "results": datasets}
    absent = {
        # Sample A: zero rows for three sequence variants, but the species WAS found there (see present).
        # Sample B: zero rows for three variants and no detection: one real non-detection.
        "e12": [row(1, 44.82182, -62.48502, "2022-08-08")] * 3 + [row(2, 44.9, -62.3, "2022-08-08")] * 3
               + [row(3, 44.9, -62.3, "2023-08-10")] * 3,
        # The same sample B, published again under 16S: must not count twice.
        "e16": [row(4, 44.9, -62.3, "2022-08-08")] * 3,
        "img": [row(5, 44.0, -66.0, "2023-09-24"), row(6, 44.1, -66.1, "2023-09-24")],
        "rv": [row(7, 47.0, -64.0, "1999-09-10")],
        "coi": [row(8, 45.0, -66.5, "2019-06-01")],
    }
    present = {"e12": [row(9, 44.82182, -62.48502, "2022-08-08")], "e16": [], "img": [], "rv": [row(10, 47.1, -64.1, "1999-09-11")] * 5, "coi": []}

    def occurrence(q):
        rows = (absent if q.get("absence") == "true" else present)[q["datasetid"]]
        return {"total": len(rows), "results": rows}
    answers["occurrence"] = occurrence


def ask_nd(name="Scomber scombrus"):
    """Follow the background job until the survey summary is in. The endpoint is withdrawn (410), so
    these tests call the calculation it kept, occurrences.nondetections, directly."""
    for _ in range(100):
        d = occurrences.nondetections(name, "atlantic-canada", wait=0.05)
        if d.get("status") not in ("computing", "queued"):
            return d
        time.sleep(0.05)
    raise AssertionError("non-detection summary never finished")


def test_the_survey_nondetections_endpoint_is_withdrawn(obis):
    calls, _ = obis
    r = client.get("/api/species/Pseudopleuronectes americanus/occurrences/nondetections")
    assert r.status_code == 410 and "withdrawn" in r.json()["detail"] and "/occurrences/edna" in r.json()["detail"]
    assert calls == []  # nothing is asked of OBIS
    assert client.get("/api/species/Homo sapiens/occurrences/nondetections").status_code == 410


def test_nondetections_count_site_dates_not_zero_filled_rows(obis):
    edna_world(obis)

    nd = ask_nd()

    # eDNA datasets (12S, 16S and COI) are not in here: they have their own section and endpoint.
    assert nd["status"] == "ok" and nd["absence_rows"] == 3
    assert [m["method"] for m in nd["methods"]] == ["capture"]
    trawl = nd["methods"][0]
    assert trawl["site_dates"] == 1 and trawl["detected_site_dates"] == 1


def test_nondetections_withhold_imagery_with_a_reason_and_leave_edna_to_its_own_section(obis):
    edna_world(obis)

    nd = ask_nd()

    withheld = {w["method"]: w for w in nd["withheld"]}
    assert set(withheld) == {"imagery"}
    assert withheld["imagery"]["site_dates"] == 2 and "open water" in withheld["imagery"]["reason"]
    assert {m["method"] for m in nd["methods"]} == {"capture"}
    assert {p["method"] for p in nd["points"]} == {"capture"}


def test_nondetections_refuse_more_rows_than_they_can_check(obis, monkeypatch):
    edna_world(obis)
    monkeypatch.setattr(occurrences, "ND_MAX_ROWS", 2)

    nd = ask_nd()

    assert nd["status"] == "too_many" and nd["methods"] == [] and nd["points"] == []


def test_nondetections_when_obis_has_none(obis):
    _, answers = obis
    answers["dataset"] = {"total": 0, "results": []}

    nd = ask_nd("Misgurnus anguillicaudatus")

    assert nd["status"] == "none" and nd["methods"] == []


def test_a_species_with_only_tag_detections_has_no_nondetections_to_show(obis):
    # Presence-only datasets never reach the non-detection summary at all.
    _, answers = obis
    answers["dataset"] = {"total": 1, "results": [{"id": "t", "title": "Northwest Arm Telemetry", "records": 0}]}
    nd = ask_nd()
    assert nd["status"] == "none"


def test_nondetections_are_cached_and_survive_obis_going_down(obis, monkeypatch):
    calls, answers = obis
    edna_world(obis)
    ask_nd()
    n = len(calls)
    again = occurrences.nondetections("Scomber scombrus", "atlantic-canada", wait=0.05)
    assert len(calls) == n and again["cached"]
    monkeypatch.setattr(occurrences, "CACHE_TTL_S", -1)
    answers["dataset"] = urllib.error.URLError("offline")
    stale = occurrences.nondetections("Scomber scombrus", "atlantic-canada", wait=0.05)
    assert stale["stale"] and stale["methods"]


def test_paging_follows_after_until_a_short_page(obis, monkeypatch):
    calls, answers = obis
    monkeypatch.setattr(occurrences, "ND_PAGE", 2)
    pages = {None: [row(1, 1, 1, "2020-01-01"), row(2, 1, 1, "2020-01-01")], "r2": [row(3, 1, 1, "2020-01-02")]}
    answers["occurrence"] = lambda q: {"results": pages[q.get("after")]}
    keys, rows_read, cut = occurrences._site_dates({"taxonid": 1}, 100)
    # Three rows, but only two sampling events: the first two rows are the same place on the same day.
    assert keys == {(1, 1, "2020-01-01"), (1, 1, "2020-01-02")} and rows_read == 3 and not cut


def test_method_classification_from_obis_metadata():
    m = occurrences._method
    assert m({"title": "Monitoring offshore subtidal biodiversity", "extensions": ["measurementorfact", "dnaderiveddata"], "abstract": "12S MiFish"}) == "edna"
    assert m({"title": "DFO Quebec eDNA metabarcoding (16S) 2020-2022"}) == "edna"
    assert m({"title": "DFO Maritimes Zooplankton Metabarcoding (COI) AEIP 2019"}) == "edna_coi"
    # A COI title with an abstract that also mentions the programme's 12S and 16S work is still the COI dataset.
    assert m({"title": "DFO Monthly GRDI Survey eDNA metabarcoding (COI) in Halifax", "abstract": "Samples were also sequenced with 12S and 16S primers.", "extensions": ["dnaderiveddata"]}) == "edna_coi"
    assert m({"title": "DFO Monthly GRDI Survey eDNA metabarcoding (12S) in the Bay of Fundy", "abstract": "COI was used for zooplankton.", "extensions": ["dnaderiveddata"]}) == "edna"
    # 18S reads all eukaryotes, so like COI it is no basis for saying a fish was not there.
    assert m({"title": "DFO Maritimes Zooplankton Metabarcoding (18S) AEIP 2019", "extensions": ["dnaderiveddata"]}) == "edna_coi"
    assert m({"title": "Maritimes Summer Research Vessel Surveys"}) == "capture"
    assert m({"title": "Near-seafloor taxa", "abstract": "Still images from a camera"}) == "imagery"
    assert m({"title": "Coastal monitoring"}) == "other"


def test_look_alike_cards_get_a_side_profile_with_its_credit():
    media = client.get("/api/species/media").json()
    cod = media["Gadus morhua"]["compare"]
    assert cod["view"] == "side" and cod["creator"] and cod["license"] and cod["source_url"].startswith("https://")
    assert species_media.compare_image([{"url": "u1", "view": "illustration"}, {"url": "u2", "view": "underwater"}])["thumb"] == "u2"
    assert species_media.compare_image([]) is None


# --- eDNA evidence ----------------------------------------------------------------------------

import threading
import time


def erow(i, ds, lat, lon, day):
    return {"id": f"x{i}", "dataset_id": ds, "decimalLatitude": lat, "decimalLongitude": lon, "eventDate": day}


def edna_fake(obis, gate=None):
    """12S and 16S datasets from the same water samples plus a COI-only one, as OBIS holds them.
    `gate`, an Event, holds back the non-detection rows to show the detections arrive first."""
    calls, answers = obis
    datasets = [
        {"id": "e12", "title": "Coastal eDNA metabarcoding (12S)", "extensions": ["dnaderiveddata"]},
        {"id": "e16", "title": "Coastal eDNA metabarcoding (16S)", "extensions": ["dnaderiveddata"]},
        {"id": "coi", "title": "Zooplankton Metabarcoding (COI) 2019", "abstract": "COI marker", "extensions": ["dnaderiveddata"]},
    ]
    present = [erow(1, "e12", 44.82182, -62.48502, "2022-08-08"), erow(2, "e12", 44.82182, -62.48502, "2022-08-08"),
               erow(3, "coi", 45.0, -66.5, "2019-06-01")]
    absent = (
        # Sample A has zeros for variants that weren't found even though the species WAS found there.
        [erow(10, "e12", 44.82182, -62.48502, "2022-08-08")] * 3
        # Sample B (twice, plus the same sample under 16S) and a 2023 visit: real non-detections.
        + [erow(11, "e12", 44.9, -62.3, "2022-08-08")] * 3 + [erow(12, "e12", 44.9, -62.3, "2023-08-10")] * 3
        + [erow(13, "e16", 44.9, -62.3, "2022-08-08")] * 3
        + [erow(14, "coi", 45.0, -66.5, "2019-06-02")] * 2
    )
    answers["dataset"] = lambda q: {"total": len(datasets), "results": datasets}
    answers["statistics/years"] = lambda q: []

    def occurrence(q):
        if q.get("absence") == "true" and q.get("size") != "0" and gate is not None:
            gate.wait(5)  # only the rows are held back; counting them is quick
        rows = absent if q.get("absence") == "true" else present
        if q.get("datasetid"):
            rows = [r for r in rows if r["dataset_id"] == q["datasetid"]]
        if q.get("startdate"):
            rows = [r for r in rows if q["startdate"] <= r["eventDate"] <= q["enddate"]]
        return {"total": len(rows)} if q.get("size") == "0" else {"results": rows}
    answers["occurrence"] = occurrence


def ask_edna(name="Scomber scombrus", **params):
    """Follow the job the way the browser does, until the non-detections are in."""
    for _ in range(100):
        d = client.get(f"/api/species/{name}/occurrences/edna", params=params).json()
        if d.get("nondetections", {}).get("state") not in ("computing", "queued"):
            return d
        time.sleep(0.05)
    raise AssertionError("eDNA evidence never finished")


def test_edna_counts_sampling_site_dates_and_keeps_detections_apart_from_non_detections(obis):
    edna_fake(obis)

    d = ask_edna()

    # Detections: sample A, and the COI sample. Rows (2 for A) are never the unit.
    assert (d["detections"]["site_dates"], d["detections"]["sites"]) == (2, 2)
    nd = d["nondetections"]
    assert nd["state"] == "ready"
    # A is a detection, so its zero rows don't count. B appears under 12S and 16S but is one site-date, plus the 2023 visit.
    assert (nd["site_dates"], nd["sites"]) == (2, 1)
    assert (nd["first_date"], nd["last_date"]) == ("2022-08-08", "2023-08-10")
    # The COI-only non-detection is withheld with its reason, not shown.
    assert [w["method"] for w in nd["withheld"]] == ["edna_coi"] and nd["withheld"][0]["site_dates"] == 1
    assert "site_dates" not in d  # the per-event list stays on the server
    by = {p["lat"]: p for p in d["points"]}
    assert (by[44.8218]["detected"], by[44.8218]["not_detected"]) == (1, 0)
    assert (by[44.9]["detected"], by[44.9]["not_detected"]) == (0, 2)
    assert (by[45.0]["detected"], by[45.0]["not_detected"]) == (1, 0)  # the COI non-detection is not drawn
    ds = {x["id"]: x for x in d["datasets"]}
    assert ds["e12"]["marker"] == "12S" and ds["e16"]["marker"] == "16S" and ds["coi"]["marker"] == "COI"
    assert ds["coi"]["nondetected_site_dates"] == 0 and ds["coi"]["withheld_site_dates"] == 1
    assert {y["year"]: (y["detected"], y["not_detected"]) for y in d["by_year"]} == {2019: (1, 0), 2022: (1, 1), 2023: (0, 1)}


def test_edna_detections_arrive_before_the_non_detections_finish(obis):
    gate = threading.Event()
    edna_fake(obis, gate)

    first = client.get("/api/species/Scomber scombrus/occurrences/edna").json()

    assert first["detections"]["site_dates"] == 2
    assert first["nondetections"]["state"] == "computing"
    assert first["nondetections"]["site_dates"] == 0 and first["nondetections"]["progress"] is not None
    gate.set()
    assert ask_edna()["nondetections"]["site_dates"] == 2


def test_edna_result_is_cached_for_a_month_and_survives_obis_going_down(obis, monkeypatch):
    calls, answers = obis
    edna_fake(obis)
    ask_edna()
    n = len(calls)

    again = client.get("/api/species/Scomber scombrus/occurrences/edna").json()

    assert len(calls) == n and again["cached"] and again["nondetections"]["state"] == "ready"
    # An expired copy is served at once, marked, while a new one is built from a dead OBIS: it never turns into an error.
    monkeypatch.setattr(occurrences, "EDNA_TTL_S", -1)
    answers["dataset"] = urllib.error.URLError("offline")
    stale = client.get("/api/species/Scomber scombrus/occurrences/edna").json()
    assert stale["stale"] and stale["nondetections"]["site_dates"] == 2


def test_edna_with_nothing_cached_and_obis_down_is_503(obis):
    _, answers = obis
    answers["dataset"] = urllib.error.URLError("offline")
    assert client.get("/api/species/Scomber scombrus/occurrences/edna").status_code == 503


def test_a_species_with_no_edna_records_says_so(obis):
    _, answers = obis
    answers["dataset"] = lambda q: {"total": 0, "results": []}
    answers["occurrence"] = lambda q: {"total": 0, "results": []}

    d = ask_edna("Misgurnus anguillicaudatus")

    assert d["status"] == "none" and d["detections"]["site_dates"] == 0 and d["points"] == []


def test_edna_refuses_more_non_detection_rows_than_it_can_reduce(obis, monkeypatch):
    edna_fake(obis)
    monkeypatch.setattr(occurrences, "EDNA_MAX_ROWS", 5)

    d = ask_edna()

    assert d["nondetections"]["state"] == "too_many" and d["nondetections"]["site_dates"] == 0
    assert d["detections"]["site_dates"] == 2  # the detections are still shown


def by_dataset_obis(answers, per_dataset, delay=0.0):
    """A fake OBIS that hands one dataset's rows out in id order after a given id, as documented,
    and notes how many datasets are being read at the same moment."""
    seen = {"now": 0, "peak": 0, "afters": []}
    lock = threading.Lock()

    def occurrence(q):
        ds = q.get("datasetid")
        rows = sorted(per_dataset[ds] if ds else [r for rs in per_dataset.values() for r in rs], key=lambda r: r["id"])
        if q.get("size") == "0":
            return {"total": len(rows)}
        with lock:
            seen["now"] += 1
            seen["peak"] = max(seen["peak"], seen["now"])
            seen["afters"].append(q.get("after"))
        time.sleep(delay)
        with lock:
            seen["now"] -= 1
        later = [r for r in rows if not q.get("after") or r["id"] > q["after"]]
        return {"results": later[: int(q["size"])]}
    answers["occurrence"] = occurrence
    return seen


def event(i, id_, day="2022-08-08"):  # every row its own sampling event unless two share a place and day
    return {"id": id_, "decimalLatitude": 40 + i / 1000, "decimalLongitude": -60, "eventDate": day}


def test_each_dataset_is_read_on_its_own_with_documented_paging(obis, monkeypatch):
    calls, answers = obis
    monkeypatch.setattr(occurrences, "ND_PAGE", 2)  # pages of two, so the cursor has to be followed
    per = {"A": [event(i, f"a{i}") for i in range(5)] + [event(0, "a9")],  # a9 repeats a0's place and day
           "B": [event(10 + i, f"b{i}") for i in range(2)]}
    seen = by_dataset_obis(answers, per)
    progress = {}

    items, rows_read, skipped, too_many = occurrences._by_dataset({"taxonid": 1}, [{"id": "A"}, {"id": "B"}], 100, progress)

    assert not too_many and skipped == 0 and rows_read == 8
    assert len(items) == 7  # eight rows, but a0 and a9 are one sampling event
    assert {ds for _k, ds in items} == {"A", "B"}
    assert set(seen["afters"]) <= {None, "a1", "a3", "a9", "b1"}  # only ever the last id of a page OBIS had just sent
    assert progress == {"total": 8, "done": 8}
    assert all("datasetid=" in u for u in calls if "size=0" not in u)


def test_only_two_datasets_are_read_at_once(obis):
    _, answers = obis
    per = {f"d{i}": [event(i, f"x{i}")] for i in range(6)}
    seen = by_dataset_obis(answers, per, delay=0.05)
    occurrences._by_dataset({"taxonid": 1}, [{"id": d} for d in per], 100)
    assert seen["peak"] == 2


def test_reading_refuses_a_query_over_the_limit_and_skips_an_empty_one(obis):
    _, answers = obis
    by_dataset_obis(answers, {"A": [event(i, f"a{i}") for i in range(5)]})
    assert occurrences._by_dataset({"taxonid": 1}, [{"id": "A"}], 3) == (set(), 0, 0, True)
    answers["occurrence"] = lambda q: {"total": 0, "results": []}
    assert occurrences._by_dataset({"taxonid": 1}, [{"id": "A"}], 3) == (set(), 0, 0, False)


def test_a_failure_in_one_dataset_stops_the_others_and_fails_the_job(obis):
    _, answers = obis
    per = {f"d{i}": [event(i, f"x{i}")] for i in range(4)}
    by_dataset_obis(answers, per)
    real = answers["occurrence"]
    answers["occurrence"] = lambda q: (_ for _ in ()).throw(urllib.error.URLError("boom")) if q.get("datasetid") == "d0" else real(q)
    q = api_guard.JobQueue(max_running=1, max_queued=0)
    job, _ = q.start("x", lambda job: occurrences._by_dataset({"taxonid": 1}, [{"id": d} for d in per], 100, job=job))
    assert job.ready.wait(5) and job.state == "failed" and "boom" in job.error


def test_nearby_site_dates_returns_matches_with_their_caveats(obis):
    edna_fake(obis)
    ask_edna()

    near = occurrences.nearby_site_dates("Scomber scombrus", "atlantic-canada", 44.9, -62.3, radius_km=5)

    # The detection at 44.82, -62.49 is about 17 km away, outside 5 km.
    assert {(m["date"], m["status"]) for m in near["matches"]} == {("2022-08-08", "not_detected"), ("2023-08-10", "not_detected")}
    assert near["matches"][0]["distance_km"] <= near["matches"][-1]["distance_km"]
    assert any("not evidence the fish was absent" in c for c in near["caveats"])
    later = occurrences.nearby_site_dates("Scomber scombrus", "atlantic-canada", 44.9, -62.3, radius_km=5, since="2023-01-01")
    assert [m["date"] for m in later["matches"]] == ["2023-08-10"]
    assert occurrences.nearby_site_dates("Gadus morhua", "atlantic-canada", 44.9, -62.3) is None  # nothing computed for cod


# --- year ranges ------------------------------------------------------------------------------

def test_a_year_range_counts_the_cached_events_and_asks_obis_for_nothing(obis):
    calls, answers = obis
    edna_fake(obis)
    everything = ask_edna()
    n = len(calls)

    r2020s = ask_edna(since=2020, until=2024)
    r2010s = ask_edna(since=2015, until=2019)
    nothing = ask_edna(since=2000, until=2004)

    assert len(calls) == n  # three ranges, no new request: they are counted from the events already kept
    assert (everything["detections"]["site_dates"], everything["nondetections"]["site_dates"]) == (2, 2)
    # 2020-2024: the 2022 detection, and the two 2022 and 2023 non-detections at the one site
    assert (r2020s["detections"]["site_dates"], r2020s["nondetections"]["site_dates"]) == (1, 2)
    assert r2020s["range"] == {"since": 2020, "until": 2024}
    assert {y["year"] for y in r2020s["by_year"]} == {2022, 2023}
    # 2015-2019: only the 2019 COI sample, whose detection counts and whose non-detection is withheld
    assert (r2010s["detections"]["site_dates"], r2010s["nondetections"]["site_dates"]) == (1, 0)
    assert r2010s["nondetections"]["withheld"][0]["site_dates"] == 1
    # a range with no samples says so, and still says where the samples are
    assert nothing["status"] == "none" and nothing["detections"]["site_dates"] == 0
    assert nothing["available"] == {"first_date": "2019-06-01", "last_date": "2023-08-10"}
    assert everything["range"] == {"since": None, "until": None}


def test_open_ended_year_ranges_and_per_dataset_counts_follow_the_range(obis):
    edna_fake(obis)
    ask_edna()

    late = ask_edna(since=2020)  # open at the recent end
    early = ask_edna(until=2019)  # open at the old end

    assert late["range"] == {"since": 2020, "until": None}
    assert (late["detections"]["site_dates"], late["nondetections"]["site_dates"]) == (1, 2)
    assert (early["detections"]["site_dates"], early["nondetections"]["site_dates"]) == (1, 0)
    ds = {d["id"]: d for d in late["datasets"]}
    assert ds["e12"]["detected_site_dates"] == 1 and ds["e12"]["nondetected_site_dates"] == 2
    assert "coi" not in ds  # datasets with nothing in the range are not listed
    assert {d["id"] for d in early["datasets"]} == {"coi"}


def test_a_range_applies_to_the_partial_result_while_the_non_detections_are_still_coming(obis):
    gate = threading.Event()
    edna_fake(obis, gate)

    partial = client.get("/api/species/Scomber scombrus/occurrences/edna", params={"since": 2015, "until": 2019}).json()

    assert partial["nondetections"]["state"] == "computing" and partial["range"] == {"since": 2015, "until": 2019}
    assert partial["detections"]["site_dates"] == 1  # only the 2019 COI sample, not the 2022 one
    gate.set()
    ask_edna()


def test_nearby_site_dates_still_works_from_the_kept_events(obis):
    edna_fake(obis)
    ask_edna()
    near = occurrences.nearby_site_dates("Scomber scombrus", "atlantic-canada", 45.0, -66.5, radius_km=5)
    # the COI sample's detection is evidence; its COI non-detection is withheld, as on the map
    assert [(m["date"], m["status"]) for m in near["matches"]] == [("2019-06-01", "detected")]


# --- method and dataset filters ---------------------------------------------------------------

TEL, RV, TAG, MUS, DNA = (c * 8 + "-0000-4000-8000-" + c * 12 for c in "abcde")


def filter_fake(obis):
    """Five datasets as OBIS lists them for mackerel; every count is the sum over the datasets asked for."""
    calls, answers = obis
    datasets = [
        {"id": TEL, "title": "Quoddy Region Pelagics Telemetry", "records": 600, "institutes": [{"name": "Ocean Tracking Network"}]},
        {"id": RV, "title": "Maritimes Spring Research Vessel Surveys", "abstract": "Stratified random bottom trawl survey.", "records": 300},
        # Tagging: one record per release or catch, by anyone, so not a research survey even though it says "groundfish".
        {"id": TAG, "title": "DFO Maritimes - Groundfish and Small Pelagic Tagging database. 1953-1999", "records": 50},
        {"id": MUS, "title": "Canadian Museum of Nature Fish Collection", "records": 40},
        {"id": DNA, "title": "Coastal eDNA metabarcoding (12S)", "records": 10, "extensions": ["dnaderiveddata"]},
    ]
    per = {d["id"]: d["records"] for d in datasets}
    chosen = lambda q: q["datasetid"].split(",") if q.get("datasetid") else list(per)
    answers["dataset"] = lambda q: {"total": len(datasets), "results": datasets}
    answers["occurrence/grid"] = lambda q: {"features": [cell(-64, 44, -63.65, 44.18, sum(per[i] for i in chosen(q)))]}
    answers["statistics/years"] = lambda q: [{"year": 2020, "records": sum(per[i] for i in chosen(q))}]
    answers["occurrence"] = lambda q: {"total": sum(per[i] for i in chosen(q)), "results": []}
    return calls


def ask_grid(**params):
    return client.get("/api/species/Scomber scombrus/occurrences/grid",
                      params={"bbox": "-65,43,-60,46", "precision": 4, "region": "atlantic-canada", **params})


def test_each_dataset_gets_a_method_only_from_what_its_metadata_says(obis):
    filter_fake(obis)
    cat = client.get("/api/species/Scomber scombrus/occurrences/datasets").json()
    assert {d["id"]: d["method"] for d in cat["datasets"]} == {TEL: "telemetry", RV: "survey", TAG: "other", MUS: "other", DNA: "edna"}
    assert cat["complete"] and [d["id"] for d in cat["datasets"]][:2] == [TEL, RV]  # largest first
    assert {m["key"]: (m["datasets"], m["records"]) for m in cat["methods"]} == {
        "survey": (1, 300), "telemetry": (1, 600), "edna": (1, 10), "other": (2, 90)}


def test_hiding_tag_detections_sends_every_other_dataset_and_the_counts_follow(obis):
    calls = filter_fake(obis)
    everything = client.get("/api/species/Scomber scombrus/occurrences/summary").json()
    assert everything["present"] == 1000 and everything["telemetry_share"] == 0.6

    g = ask_grid(method="no_telemetry").json()
    assert g["present"][0][4] == 400 and g["filter"] == {"method": "no_telemetry", "dataset": None, "datasets": 4}
    sent = dict(urllib.parse.parse_qsl(calls[-1].split("?", 1)[1]))["datasetid"].split(",")
    assert sorted(sent) == sorted([RV, TAG, MUS, DNA])
    s = client.get("/api/species/Scomber scombrus/occurrences/summary", params={"method": "no_telemetry"}).json()
    assert (s["present"], s["dataset_count"], s["telemetry_share"]) == (400, 4, 0.0)
    assert s["by_year"] == [{"year": 2020, "records": 400}] and TEL not in {d["id"] for d in s["datasets"]}


def test_a_method_or_one_dataset_works_with_the_year_range(obis):
    calls = filter_fake(obis)
    g = ask_grid(method="survey", since=2018, until=2022).json()
    assert g["present"][0][4] == 300
    assert f"datasetid={RV}" in calls[-1] and "startdate=2018-01-01" in calls[-1] and "enddate=2022-12-31" in calls[-1]
    assert ask_grid(dataset=MUS).json()["present"][0][4] == 40
    s = client.get("/api/species/Scomber scombrus/occurrences/summary", params={"dataset": TEL}).json()
    assert (s["present"], s["dataset_count"], s["telemetry_share"]) == (600, 1, 1.0)
    r = client.get("/api/species/Scomber scombrus/occurrences/records",
                   params={"bbox": a_cell(), "region": "atlantic-canada", "method": "telemetry", "since": 2018})
    assert r.status_code == 200 and f"datasetid={TEL}" in calls[-1] and "startdate=2018-01-01" in calls[-1]


def test_filters_are_checked_and_an_empty_one_asks_obis_for_nothing(obis):
    calls = filter_fake(obis)
    for bad in ({"method": "trawl"}, {"dataset": "not-an-id"}, {"dataset": "f" * 8 + "-0000-4000-8000-" + "f" * 12}):
        assert ask_grid(**bad).status_code == 400, bad
    n = len(calls)
    g = ask_grid(method="survey", dataset=TEL).json()  # a telemetry dataset is not a survey: nothing left
    assert g["present"] == [] and g["filter"]["datasets"] == 0 and len(calls) == n
    # The dataset list is one cached request however many filters are tried.
    assert sum(1 for u in calls if "/v3/dataset?" in u) == 1


def test_too_many_datasets_to_filter_is_refused_not_guessed(obis, monkeypatch):
    filter_fake(obis)
    monkeypatch.setattr(occurrences, "FILTER_MAX_IDS", 3)
    assert ask_grid(method="no_telemetry").status_code == 400
    assert ask_grid(method="other").status_code == 200


# --- conservation status ----------------------------------------------------------------------

def test_atlantic_whitefish_has_its_verified_status_with_sources():
    c = client.get("/api/species/Coregonus huntsmani/profile").json()["conservation"]
    assert c["kind"] == "at_risk" and c["badge"] == "Endangered" and c["verified_on"]
    assert {s["authority"] for s in c["statuses"]} >= {"COSEWIC", "Species at Risk Act (Canada)", "Nova Scotia Endangered Species Act"}
    assert "Petite Rivière" in c["population"] and c["threats"]
    assert c["sources"] and all(s["url"].startswith("https://") for s in c["sources"])
    # The list's badge comes from the same entry, even though the whitefish has no photos yet.
    assert client.get("/api/species/media").json()["Coregonus huntsmani"]["conservation"] == {"kind": "at_risk", "badge": "Endangered", "scope": "species"}
    # Each status says what sort of statement it is, so an assessment and a listing never merge.
    types = {s["authority"]: s["type"] for s in c["statuses"]}
    assert types == {"COSEWIC": "assessment", "Species at Risk Act (Canada)": "legal", "Nova Scotia Endangered Species Act": "legal"}


def test_a_fish_without_a_verified_entry_has_no_status_rather_than_a_safe_one():
    assert client.get("/api/species/Pollachius virens/profile").json()["conservation"] is None
    assert client.get("/api/species/media").json()["Pollachius virens"]["conservation"] is None


def test_population_specific_statuses_are_never_shown_as_the_whole_species():
    for name in ("Salmo salar", "Gadus morhua"):
        c = client.get(f"/api/species/{name}/profile").json()["conservation"]
        assert c["scope"] == "populations"
        cosewic = [s for s in c["statuses"] if s["authority"] == "COSEWIC"]
        assert cosewic and all(s["population"] and s["type"] == "assessment" for s in cosewic)
        assert client.get("/api/species/media").json()[name]["conservation"]["scope"] == "populations"
    salmon = client.get("/api/species/Salmo salar/profile").json()["conservation"]
    listed = [s for s in salmon["statuses"] if s["type"] == "legal" and s["status"].startswith("Endangered")]
    assert [s["population"] for s in listed] == ["Inner Bay of Fundy population"]  # the only SARA listing


def test_status_types_population_and_source_are_checked(monkeypatch, tmp_path):
    f = tmp_path / "conservation.json"
    f.write_text(json.dumps({"species": {
        "Scomber scombrus": {"kind": "at_risk", "badge": "Endangered", "verified_on": "2026-01-01", "sources": [{"url": "https://example.org"}], "statuses": [
            {"authority": "COSEWIC", "status": "Endangered", "population": "Some population", "source": "http://insecure.example"},
            {"authority": "Species at Risk Act (Canada)", "status": "Not listed"},
            {"authority": "Someone else", "status": "Rare", "type": "nonsense"},
        ]},
        "Esox niger": {"kind": "invasive_ns", "badge": "Introduced", "verified_on": "2026-01-01", "sources": [{"url": "https://example.org"}],
                       "statuses": [{"authority": "Nova Scotia Fisheries and Aquaculture", "status": "Mandatory retention"}]},
    }}), encoding="utf-8")
    monkeypatch.setattr(species_media.config, "SPECIES_CONSERVATION", f)
    c = species_media.conservation()
    assert c["Scomber scombrus"]["scope"] == "populations"
    assert [s["type"] for s in c["Scomber scombrus"]["statuses"]] == ["assessment", "legal", "other"]
    assert c["Scomber scombrus"]["statuses"][0]["source"] == ""  # only https sources are kept
    assert c["Esox niger"]["scope"] == "species" and c["Esox niger"]["statuses"][0]["type"] == "introduced"


def test_an_unverified_or_unsourced_entry_is_never_shown(monkeypatch, tmp_path):
    f = tmp_path / "conservation.json"
    f.write_text(json.dumps({"species": {
        "Gadus morhua": {"kind": "at_risk", "badge": "Endangered", "sources": [{"url": "https://example.org"}]},  # no verified_on
        "Pollachius virens": {"kind": "at_risk", "badge": "Threatened", "verified_on": "2026-01-01", "sources": []},
        "Mola mola": {"kind": "safe", "badge": "Secure", "verified_on": "2026-01-01", "sources": [{"url": "https://example.org"}]},
        "Scomber scombrus": {"kind": "invasive_ns", "badge": "Locally invasive", "verified_on": "2026-01-01", "sources": [{"url": "https://example.org/x"}]},
    }}), encoding="utf-8")
    monkeypatch.setattr(species_media.config, "SPECIES_CONSERVATION", f)
    assert set(species_media.conservation()) == {"Scomber scombrus"}
    assert client.get("/api/species/Pollachius virens/profile").json()["conservation"] is None


def test_atlantic_whitefish_compares_with_lake_whitefish_without_adding_it_to_the_ai_list():
    p = client.get("/api/species/Coregonus huntsmani/profile").json()
    similar = {s["species"]: s for s in p["profile"]["similar"]}
    assert {"Coregonus clupeaformis", "Salvelinus fontinalis", "Salmo salar"} <= similar.keys()
    assert similar["Coregonus clupeaformis"]["common"] == "Lake Whitefish"
    listed = {row["species"] for row in models.species_table()}
    assert "Coregonus clupeaformis" not in listed  # a reference look-alike only; BioCLIP never sees it
    assert any("coastalaction.org" in s["url"] for s in p["profile"]["sources"])
    c = p["conservation"]
    # Where it lived before and where wild fish are known now are kept apart.
    assert "Tusket" in c["historical_range"] and "Petite Rivière" in c["current_range"]
    assert "extirpated" in c["current_range"] and c["range_note"]
    # The population's environment now (fresh water only) is said apart from WoRMS's species-level flags.
    assert c["environment_now"] == "Freshwater" and "nadromous" in c["environment_historical"]
    assert p["names"]["is_marine"] is True  # WoRMS still says marine for the species; kept, not overwritten


def test_a_look_alike_that_is_not_on_the_list_carries_its_own_common_name():
    listed = {row["species"] for row in models.species_table()}
    for name, entry in species_media.load().items():
        for s in ((entry.get("profile") or {}).get("similar") or []):
            if isinstance(s, dict) and s.get("species") and s["species"] not in listed:
                assert s.get("common"), f"{name}: look-alike {s['species']} is unlisted and needs a common name"
