"""The limits that keep the species wiki from hurting the hosted site or OBIS. No test touches the network."""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
from email.message import Message

import pytest
from fastapi.testclient import TestClient

from tidecount import api_cache, api_guard, occurrences
from tidecount.app import app
from tidecount.api_guard import Budget, Busy, JobQueue, Limiter, SingleFlight

client = TestClient(app)


class Clock:
    """A clock the tests move by hand, so rate limits are checked without waiting."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(api_cache.config, "DATA", tmp_path)
    monkeypatch.setattr(api_cache, "MIN_FREE_BYTES", 0)
    # The real OBIS budget is slow on purpose; tests of everything else shouldn't wait on it.
    monkeypatch.setitem(api_guard._budgets, "obis", Budget(concurrent=8, reserved=2, **FAST))
    api_guard.reset()


# --- the outbound budget ----------------------------------------------------------------------

FAST = dict(job_per_second=1000, visitor_per_second=1000, burst=1000, per_minute=1000, per_hour=1000)


def test_budget_limits_requests_in_flight_and_keeps_places_for_visitors():
    b = Budget(concurrent=4, reserved=2, **FAST)  # two places for jobs, two for visitors
    b.acquire(0.1, patient=True)
    b.acquire(0.1, patient=True)
    with pytest.raises(Busy):
        b.acquire(0.05, patient=True)  # background jobs can't take the visitors' places, and give up quickly
    b.acquire(0.1)
    b.acquire(0.1)  # the maps still get theirs
    with pytest.raises(Busy):
        b.acquire(0.05)
    b.release()
    b.acquire(0.1)  # a place is free again


def test_budget_spaces_requests_and_caps_the_minute_and_the_hour():
    clock = Clock()
    b = Budget(concurrent=50, reserved=10, job_per_second=2, visitor_per_second=2, burst=2, per_minute=5, per_hour=6,
               job_share=1.0, clock=clock, sleep=clock.sleep)
    start = clock.now
    for _ in range(4):  # two from the burst, then one every half second
        b.acquire(5)
        b.release()
    assert clock.now - start >= 0.99
    b.acquire(5)
    b.release()
    with pytest.raises(Busy) as e:  # a sixth within the minute is refused, and says when to come back
        b.acquire(5)
    assert 1 <= e.value.retry_after <= 60
    clock.now += 61
    b.acquire(5)
    b.release()
    clock.now += 61
    with pytest.raises(Busy):  # the hourly cap of 6 is reached however slowly they come
        b.acquire(5)


def test_jobs_may_use_only_part_of_the_volume_so_visitors_are_never_shut_out():
    clock = Clock()
    b = Budget(concurrent=50, reserved=10, job_per_second=1000, visitor_per_second=1000, burst=1000, per_minute=8, per_hour=1000,
               job_share=0.5, clock=clock, sleep=clock.sleep)
    for _ in range(4):  # a job's share of eight a minute is four
        b.acquire(5, patient=True)
        b.release(True)
    with pytest.raises(Busy):
        b.acquire(5, patient=True)
    for _ in range(4):  # and the other four are still there for visitors
        b.acquire(5)
        b.release()
    with pytest.raises(Busy):  # then the total is spent
        b.acquire(5)


def test_a_run_of_failures_opens_the_breaker_and_it_closes_again():
    clock = Clock()
    b = Budget(concurrent=5, trip_after=3, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        b.acquire(1)
        b.release()
        b.failure()
    with pytest.raises(Busy) as e:
        b.acquire(1)  # no request is sent while OBIS is struggling
    assert "paused" in str(e.value.reason)
    clock.now += 31
    b.acquire(1)
    b.release()
    b.success()


def test_a_429_pauses_every_caller_for_retry_after():
    clock = Clock()
    b = Budget(concurrent=5, clock=clock, sleep=clock.sleep)
    b.failure(pause_s=45)
    with pytest.raises(Busy):
        b.acquire(1)
    clock.now += 46
    b.acquire(1)


# --- _get: what is sent to OBIS, retried and refused ---------------------------------------------

def http_error(code, retry_after=None):
    headers = Message()
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("https://api.obis.org/v3/x", code, "err", headers, None)


def run_in(thread_name, fn):
    out = {}

    def target():
        try:
            out["value"] = fn()
        except BaseException as e:
            out["error"] = e
    t = threading.Thread(target=target, name=thread_name)
    t.start()
    t.join(10)
    return out


def test_a_visitors_request_is_tried_once_and_a_429_rests_the_whole_server(monkeypatch):
    sent = []

    def fake_open(url, timeout):
        sent.append(url)
        raise http_error(429, retry_after=20)
    monkeypatch.setattr(occurrences, "_open", fake_open)

    assert isinstance(run_in("anyio-worker", lambda: occurrences._get("u1"))["error"], urllib.error.HTTPError)
    assert len(sent) == 1
    again = run_in("anyio-worker", lambda: occurrences._get("u2"))["error"]
    assert isinstance(again, Busy) and len(sent) == 1  # nothing more goes to OBIS while it asked for a pause


def test_a_background_job_retries_a_busy_obis_with_backoff_and_then_succeeds(monkeypatch):
    attempts = []
    monkeypatch.setattr(api_guard, "backoff", lambda attempt, retry_after=None: 0)

    def fake_open(url, timeout):
        attempts.append(timeout)
        if len(attempts) < 3:
            raise http_error(503)
        return {"ok": True}
    monkeypatch.setattr(occurrences, "_open", fake_open)

    out = run_in("api-job-test", lambda: occurrences._get("u"))

    assert out["value"] == {"ok": True} and len(attempts) == 3
    assert attempts[0] == occurrences.JOB_TIMEOUT_S  # jobs wait longer for the big pages


def test_a_visitors_request_does_not_retry_a_5xx(monkeypatch):
    sent = []
    monkeypatch.setattr(occurrences, "_open", lambda url, timeout: sent.append(url) or (_ for _ in ()).throw(http_error(503)))
    assert isinstance(run_in("anyio-worker", lambda: occurrences._get("u"))["error"], urllib.error.HTTPError)
    assert len(sent) == 1


def test_our_own_mistakes_are_not_retried_and_do_not_trip_the_breaker(monkeypatch):
    sent = []
    monkeypatch.setattr(occurrences, "_open", lambda url, timeout: sent.append(url) or (_ for _ in ()).throw(http_error(400)))
    for _ in range(10):
        run_in("api-job-test", lambda: occurrences._get("u"))
    assert len(sent) == 10 and api_guard.budget("obis").paused_for() == 0


def test_timeouts_open_the_breaker_after_a_run_and_cached_answers_still_come_back(monkeypatch):
    monkeypatch.setattr(occurrences, "_open", lambda url, timeout: (_ for _ in ()).throw(TimeoutError("slow")))
    monkeypatch.setattr(api_guard, "backoff", lambda attempt, retry_after=None: 0)
    for _ in range(3):  # three attempts per background job, five failures trip it
        run_in("api-job-test", lambda: occurrences._get("u"))
    assert api_guard.budget("obis").paused_for() > 0
    assert isinstance(run_in("anyio-worker", lambda: occurrences._get("v"))["error"], Busy)


def test_a_busy_budget_serves_the_older_cached_answer(monkeypatch):
    path, params = "occurrence/grid/3", {"taxonid": 1}
    monkeypatch.setattr(occurrences, "_get", lambda url: {"features": ["old"]})
    occurrences._fetch(path, params)
    monkeypatch.setattr(occurrences, "CACHE_TTL_S", -1)

    def busy(url):
        raise Busy("full", 5)
    monkeypatch.setattr(occurrences, "_get", busy)

    data, meta = occurrences._fetch(path, params)
    assert data == {"features": ["old"]} and meta["stale"]


def test_identical_requests_at_the_same_moment_share_one_call(monkeypatch):
    gate, calls = threading.Event(), []

    def slow(url):
        calls.append(url)
        gate.wait(5)
        return {"features": []}
    monkeypatch.setattr(occurrences, "_get", slow)
    results = []
    threads = [threading.Thread(target=lambda: results.append(occurrences._fetch("occurrence/grid/3", {"taxonid": 1}))) for _ in range(6)]
    for t in threads:
        t.start()
    time.sleep(0.3)
    gate.set()
    for t in threads:
        t.join(5)
    assert len(calls) == 1 and len(results) == 6


# --- visitors ---------------------------------------------------------------------------------

def test_a_visitor_over_the_limit_waits_and_others_are_unaffected():
    clock = Clock()
    lim = Limiter(3, 60, clock=clock)
    assert [lim.check("a") for _ in range(3)] == [None, None, None]
    wait = lim.check("a")
    assert wait is not None and 0 < wait <= 60
    assert lim.check("b") is None
    clock.now += 61
    assert lim.check("a") is None


def test_the_limiter_forgets_quiet_visitors_instead_of_growing():
    lim = Limiter(5, 60, max_keys=100)
    for i in range(5000):
        lim.check(f"10.0.{i // 250}.{i % 250}")
    assert len(lim._hits) <= 100


def test_a_visitors_address_comes_from_the_proxy_only_when_the_proxy_is_the_peer():
    assert api_guard.client_ip("172.18.0.3", "203.0.113.9") == "203.0.113.9"      # Caddy on Docker's network
    assert api_guard.client_ip("172.18.0.3", "1.2.3.4, 203.0.113.9") == "203.0.113.9"  # the last entry is the one Caddy added
    assert api_guard.client_ip("8.8.8.8", "9.9.9.9") == "8.8.8.8"                  # anyone else can't choose their address
    assert api_guard.client_ip("172.18.0.3", "not an address") == "172.18.0.3"
    assert api_guard.client_ip(None, None) == "unknown"


def test_the_wiki_limits_a_visitor_and_header_spoofing_does_not_help(monkeypatch):
    monkeypatch.setattr(api_guard.visits, "limit", 3)
    monkeypatch.setattr(occurrences, "_get", lambda url: [] if "statistics/years" in url else {"total": 0, "results": []})
    codes = [client.get("/api/species/Gadus morhua/occurrences/summary", headers={"X-Forwarded-For": f"9.9.9.{i}"}).status_code for i in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]
    r = client.get("/api/species/Gadus morhua/occurrences/summary")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1


def test_only_a_few_map_calls_run_at_once_so_the_rest_of_the_app_keeps_its_threads(monkeypatch):
    held = threading.BoundedSemaphore(2)
    monkeypatch.setattr(api_guard, "inflight", held)
    held.acquire()
    held.acquire()  # two calls already running
    r = client.get("/api/species/Gadus morhua/occurrences/summary")
    assert r.status_code == 503 and "Retry-After" in r.headers


# --- the parameters that make cache entries -------------------------------------------------------

def test_views_are_rounded_out_to_the_maps_steps_so_near_identical_requests_share_a_cache_entry(monkeypatch):
    calls = []
    monkeypatch.setattr(occurrences, "_get", lambda url: calls.append(url) or {"features": []})
    for bbox in ("-64.2,43.1,-61.7,44.9", "-64.9,43.9,-61.1,44.1", "-63,43,-62,44"):
        r = client.get("/api/species/Gadus morhua/occurrences/grid", params={"bbox": bbox, "precision": 5})
        assert r.status_code == 200
    assert len(calls) == 2  # the first two round out to the same box at precision 5 (1 degree steps); the third is its own...
    calls.clear()
    for bbox in ("-64.2,43.1,-61.7,44.9", "-64.9,43.9,-61.1,44.8"):
        client.get("/api/species/Gadus morhua/occurrences/grid", params={"bbox": bbox, "precision": 4})
    assert len(calls) == 1  # ...but at precision 4 (5 degree steps) these two are one entry
    assert occurrences.snap_bbox((-64.2, 43.1, -61.7, 44.9), 4) == (-65.0, 40.0, -60.0, 45.0)


def test_the_year_range_takes_single_years_and_refuses_the_rest():
    assert occurrences.check_range(2018, 2022) == (2018, 2022)
    assert occurrences.check_range(2020, 2020) == (2020, 2020)  # one year
    assert occurrences.check_range(None, None) == (None, None)
    assert occurrences.check_range(2020, None) == (2020, None) and occurrences.check_range(None, 1949) == (None, 1949)
    for since, until in [(1899, None), (2101, None), (None, 1899), (None, 2101), (2020, 2014)]:
        with pytest.raises(ValueError):
            occurrences.check_range(since, until)
    base = {"bbox": "-70,40,-50,53", "precision": 3}
    for bad in ({"since": 1899}, {"until": 2101}, {"since": 2020, "until": 2014}, {"since": "2018.5"}):
        # 400 from check_range, 422 when FastAPI refuses a value that isn't a whole number
        assert client.get("/api/species/Gadus morhua/occurrences/grid", params={**base, **bad}).status_code in (400, 422)
        assert client.get("/api/species/Gadus morhua/occurrences/edna", params=bad).status_code in (400, 422)


def test_a_year_range_reaches_obis_as_dates_and_each_range_is_one_cache_entry(monkeypatch):
    calls = []
    monkeypatch.setattr(occurrences, "_get", lambda url: calls.append(url) or {"features": []})
    ask = lambda **kw: client.get("/api/species/Gadus morhua/occurrences/grid", params={"bbox": "-70,40,-50,53", "precision": 3, **kw})

    assert ask(since=2018, until=2022).status_code == 200
    assert "startdate=2018-01-01" in calls[-1] and "enddate=2022-12-31" in calls[-1]
    ask(since=2018, until=2022)  # the same range again
    assert len(calls) == 1
    ask(since=2010, until=2019)
    assert "startdate=2010-01-01" in calls[-1] and "enddate=2019-12-31" in calls[-1]
    calls.pop()
    ask(since=2020)  # open at the end: a start date and no end date
    assert "startdate=2020-01-01" in calls[-1] and "enddate" not in calls[-1]
    ask(until=2009)
    assert "enddate=2009-12-31" in calls[-1] and "startdate" not in calls[-1]
    ask()
    assert "startdate" not in calls[-1] and "enddate" not in calls[-1] and len(calls) == 4
    assert ask(since=2010, until=2019).json()["until"] == 2019


def test_records_take_the_same_year_range(monkeypatch):
    calls = []
    monkeypatch.setattr(occurrences, "_get", lambda url: calls.append(url) or {"total": 0, "results": []})
    cw, ch = occurrences._cell_size(5)
    cell = ",".join(str(round(v, 5)) for v in (-180 + 2650 * cw, -90 + 2400 * ch, -180 + 2651 * cw, -90 + 2401 * ch))
    assert client.get("/api/species/Gadus morhua/occurrences/records", params={"bbox": cell, "since": 2000, "until": 2009}).status_code == 200
    assert "startdate=2000-01-01" in calls[-1] and "enddate=2009-12-31" in calls[-1]


@pytest.mark.parametrize("precision", [2, 3, 4, 5, 6])
def test_records_are_listed_only_for_real_grid_cells(precision):
    cw, ch = occurrences._cell_size(precision)
    col, row = 7, 9
    w, s = -180 + col * cw, -90 + row * ch
    asked = (round(w, 5), round(s, 5), round(w + cw, 5), round(s + ch, 5))  # as OBIS reports a cell: five decimals
    got = occurrences.grid_cell(asked)
    assert all(abs(a - b) < 2e-5 for a, b in zip(got, (w, s, w + cw, s + ch)))
    assert occurrences.grid_cell(got) == got  # idempotent, so it makes one cache entry per cell
    with pytest.raises(ValueError):
        occurrences.grid_cell((asked[0] + cw / 2, asked[1], asked[2] + cw / 2, asked[3]))  # right size, but off the grid
    with pytest.raises(ValueError):
        occurrences.grid_cell((asked[0], asked[1], asked[2] + cw, asked[3]))  # wrong size


def test_the_records_endpoint_refuses_a_made_up_box(monkeypatch):
    monkeypatch.setattr(occurrences, "_get", lambda url: pytest.fail("a made-up box must not reach OBIS"))
    assert client.get("/api/species/Gadus morhua/occurrences/records", params={"bbox": "-63.5,44,-63,44.5"}).status_code == 400


# --- the disk cache --------------------------------------------------------------------------------

def test_the_cache_stays_under_its_size_limit_and_keeps_what_is_slow_to_rebuild(monkeypatch):
    monkeypatch.setattr(api_cache, "MAX_BYTES", 60_000)
    blob = {"x": "y" * 2000}
    api_cache.write("slow", blob, "edna-")
    old = time.time() - 86400
    os.utime(api_cache._file("slow", "edna-"), (old, old))  # the oldest of all, yet it should outlast the cheap ones
    for i in range(80):
        api_cache.write(f"cheap-{i}", blob)
    u = api_cache.usage()
    assert u["bytes"] <= 60_000 and u["files"] < 81
    assert api_cache.read("slow", "edna-") is not None
    assert sum(f.stat().st_size for f in api_cache.folder().glob("*.json")) <= 60_000


def test_the_cache_evicts_the_least_recently_used_first(monkeypatch):
    monkeypatch.setattr(api_cache, "MAX_BYTES", 30_000)
    blob = {"x": "y" * 2000}
    base = time.time() - 10_000
    for i in range(10):
        api_cache.write(f"k{i}", blob)
        os.utime(api_cache._file(f"k{i}", ""), (base + i, base + i))
    api_cache.read("k0")  # reading counts as use: k0 is now the newest
    for i in range(10, 16):
        api_cache.write(f"k{i}", blob)
    assert api_cache.read("k0") is not None
    assert api_cache.read("k1") is None


def test_an_oversized_answer_and_a_nearly_full_disk_are_not_cached(monkeypatch):
    assert api_cache.write("big", {"x": "y" * (api_cache.MAX_FILE_BYTES + 10)}) is False
    monkeypatch.setattr(api_cache, "MIN_FREE_BYTES", 10 ** 15)  # more free space than any disk has
    assert api_cache.write("small", {"x": 1}) is False
    assert api_cache.read("small") is None


def test_a_full_disk_clears_cheap_answers_but_not_the_slow_ones(monkeypatch):
    api_cache.write("slow", {"x": 1}, "edna-")
    for i in range(5):
        api_cache.write(f"cheap{i}", {"x": 1})
    monkeypatch.setattr(api_cache, "MIN_FREE_BYTES", 10 ** 15)
    api_cache.write("new", {"x": 1})
    assert api_cache.read("slow", "edna-") is not None and api_cache.read("cheap0") is None


def test_old_answers_and_leftover_temp_files_are_removed(monkeypatch):
    api_cache.write("old", {"x": 1})
    api_cache.write("fresh", {"x": 1})
    long_ago = time.time() - api_cache.STALE_MAX_S - 100
    os.utime(api_cache._file("old", ""), (long_ago, long_ago))
    tmp = api_cache.folder() / "abc.json.deadbeef.tmp"
    tmp.write_text("half a file")
    os.utime(tmp, (time.time() - 3600, time.time() - 3600))
    api_cache.sweep()
    assert api_cache.read("old") is None and api_cache.read("fresh") is not None and not tmp.exists()


def test_two_requests_writing_the_same_answer_cannot_corrupt_or_lose_it():
    errors = []

    def writer(n):
        try:
            for _ in range(30):
                api_cache.write("same", {"writer": n, "pad": "z" * 5000})
                got = api_cache.read("same")
                assert got is None or got["data"]["pad"] == "z" * 5000  # whole, never half-written
        except BaseException as e:
            errors.append(e)
    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert not errors
    assert json.loads(api_cache._file("same", "").read_text())["data"]["pad"] == "z" * 5000
    assert not list(api_cache.folder().glob("*.tmp"))  # every temp file was renamed away


# --- background jobs --------------------------------------------------------------------------------

def test_the_queue_runs_few_at_once_queues_a_few_and_refuses_the_rest():
    q = JobQueue(max_running=1, max_queued=1)
    gate, started = threading.Event(), []

    def work(job):
        started.append(job.key)
        gate.wait(5)
    a, new_a = q.start("a", work)
    b, new_b = q.start("b", work)
    again, new_again = q.start("a", work)  # the same request joins the job already there
    assert (new_a, new_b, new_again) == (True, True, False) and again is a
    with pytest.raises(Busy) as e:
        q.start("c", work)
    assert e.value.retry_after >= 1
    time.sleep(0.2)
    assert started == ["a"] and b.state == "queued" and q.ahead_of(b) == 1  # one at a time
    gate.set()
    assert b.ready.wait(5)
    q.reset()


def test_a_visitor_over_their_job_limit_is_refused_before_a_job_starts():
    q = JobQueue()
    calls = []

    def refuse():
        calls.append(1)
        raise api_guard.RateLimited("too many", 30)
    with pytest.raises(api_guard.RateLimited):
        q.start("x", lambda job: None, on_start=refuse)
    assert calls == [1] and q.active() == 0
    gate = threading.Event()
    z, _ = q.start("z", lambda job: gate.wait(5), on_start=lambda: None)
    joined, started = q.start("z", lambda job: None, on_start=refuse)  # joining work already under way is never charged
    assert joined is z and not started and calls == [1]
    gate.set()
    z.ready.wait(5)


def test_a_job_that_runs_too_long_or_asks_too_often_is_stopped():
    def slow(job):
        while True:
            job.check()
            time.sleep(0.05)
    long = JobQueue(deadline_s=0.2, max_requests=10_000)
    j, _ = long.start("slow", slow)
    assert j.ready.wait(5) and j.state == "failed" and "longer than" in j.error

    chatty = JobQueue(max_requests=3)
    j2, _ = chatty.start("chatty", lambda job: [job.check() for _ in range(10)])
    assert j2.ready.wait(5) and j2.state == "failed" and "OBIS requests" in j2.error


def test_finished_jobs_are_not_kept_and_failures_are_remembered_only_briefly():
    q = JobQueue(fail_hold_s=0.2)
    ok, _ = q.start("ok", lambda job: None)
    bad, _ = q.start("bad", lambda job: 1 / 0)
    assert ok.ready.wait(5) and bad.ready.wait(5)
    time.sleep(0.05)
    assert q.get("ok") is None  # its answer lives in the disk cache, not in memory
    assert q.get("bad") is bad  # a poll right after a failure doesn't start the same calculation again
    time.sleep(0.3)
    assert q.get("bad") is None and q.active() == 0


def test_a_result_the_cache_could_not_hold_is_kept_briefly_and_the_number_kept_is_bounded():
    q = JobQueue(max_kept=3)
    for i in range(10):
        def work(job, i=i):
            job.result = {"n": i}
        q.start(f"k{i}", work)[0].ready.wait(5)
    time.sleep(0.1)
    q.get("anything")  # tidying happens whenever the queue is used
    assert len(q._jobs) <= 3


# --- through the real endpoints ----------------------------------------------------------------------

def dataset_world(answers):
    answers["dataset"] = lambda q: {"total": 1, "results": [{"id": "e12", "title": "Coastal eDNA metabarcoding (12S)", "extensions": ["dnaderiveddata"], "records": 4}]}

    def occurrence(q):
        if q.get("size") == "0":
            return {"total": 2}
        return {"results": [{"id": "a", "decimalLatitude": 44.1, "decimalLongitude": -63.2, "eventDate": "2022-08-08", "dataset_id": "e12"},
                            {"id": "b", "decimalLatitude": 44.2, "decimalLongitude": -63.3, "eventDate": "2022-08-09", "dataset_id": "e12"}]}
    answers["occurrence"] = occurrence


@pytest.fixture
def fake_obis(monkeypatch):
    monkeypatch.setattr(occurrences, "RESULT_WAIT_S", 0.3)  # polls come back quickly instead of waiting for a held-back job
    calls, answers = [], {}

    def fake_get(url):
        calls.append(url)
        path = url.split("/v3/", 1)[1].split("?", 1)[0]
        for prefix, answer in answers.items():
            if path.startswith(prefix):
                return answer(dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))) if callable(answer) else answer
        raise AssertionError(f"unexpected OBIS call {url}")
    monkeypatch.setattr(occurrences, "_get", fake_get)
    yield calls, answers
    # A background job must not outlive the fake: it would go on to call the real OBIS.
    for _ in range(100):
        if api_guard.jobs.active() == 0:
            break
        time.sleep(0.05)
    assert api_guard.jobs.active() == 0


def test_the_edna_calculation_is_charged_to_a_visitor_only_when_it_starts(fake_obis, monkeypatch):
    calls, answers = fake_obis
    dataset_world(answers)
    gate = threading.Event()
    real = answers["occurrence"]
    answers["occurrence"] = lambda q: (gate.wait(5), real(q))[1] if q.get("size") != "0" else real(q)
    monkeypatch.setattr(api_guard.job_starts, "limit", 1)

    first = client.get("/api/species/Scomber scombrus/occurrences/edna")
    poll = client.get("/api/species/Scomber scombrus/occurrences/edna")  # following the same job costs nothing
    other = client.get("/api/species/Gadus morhua/occurrences/edna")  # a second, different calculation is over this visitor's limit

    assert first.status_code == 200 and poll.status_code == 200
    assert other.status_code == 429 and int(other.headers["Retry-After"]) >= 1
    gate.set()


def test_a_full_queue_answers_503_with_retry_after_unless_an_older_copy_exists(fake_obis, monkeypatch):
    calls, answers = fake_obis
    dataset_world(answers)
    gate = threading.Event()
    real = answers["occurrence"]
    answers["occurrence"] = lambda q: (gate.wait(5), real(q))[1] if q.get("size") != "0" else real(q)
    monkeypatch.setattr(api_guard, "jobs", JobQueue(max_running=1, max_queued=0))

    assert client.get("/api/species/Scomber scombrus/occurrences/edna").status_code == 200  # takes the only place
    full = client.get("/api/species/Gadus morhua/occurrences/edna")
    assert full.status_code == 503 and "Retry-After" in full.headers and "calculations" in full.json()["detail"]
    gate.set()


def test_identical_requests_share_one_job(fake_obis):
    calls, answers = fake_obis
    dataset_world(answers)
    for _ in range(4):
        assert client.get("/api/species/Scomber scombrus/occurrences/edna").status_code == 200
    for _ in range(100):
        d = client.get("/api/species/Scomber scombrus/occurrences/edna").json()
        if d["nondetections"]["state"] not in ("computing", "queued"):
            break
        time.sleep(0.05)
    pages = [u for u in calls if "fields=" in u and "absence" not in u]
    assert len(pages) <= 1  # one detections request, however many polls


def test_ordinary_requests_stay_responsive_while_a_calculation_runs(fake_obis):
    calls, answers = fake_obis
    dataset_world(answers)
    gate = threading.Event()
    real = answers["occurrence"]
    answers["occurrence"] = lambda q: (gate.wait(5), real(q))[1] if q.get("size") != "0" else real(q)
    client.get("/api/species/Scomber scombrus/occurrences/edna")  # the job is now stuck waiting for OBIS
    t = time.time()
    r = client.get("/api/species/media")
    assert r.status_code == 200 and time.time() - t < 1.0
    gate.set()
