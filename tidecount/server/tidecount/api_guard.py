"""Safeguards for a public site that calls someone else's API, so it can't hurt itself or them.

Nothing here knows about fish or about OBIS. The species wiki uses it for OBIS, and another service
such as GBIF can use the same pieces by asking for its own budget (see "Adding another service" at
the bottom). Everything lives in this one process, which is how the Docker deployment runs (a
single uvicorn); with more processes each would keep its own copy of these limits.

- `Budget`: one outbound budget per service. A few requests in flight, a gentle rate, caps per
  minute and per hour, and a circuit breaker: a 429 or a run of failures pauses the service, and
  callers fall back to cached answers at once instead of waiting on a sick server.
- `call`: sends one request through a budget, retrying a background job's timeouts, 429s and 5xx
  with backoff, and trying a visitor's request once.
- `Limiter`: how often one visitor may ask, with bounded memory.
- `JobQueue`: the few slow calculations that run in the background. One runs at a time, a few
  wait, identical requests share one job, and finished jobs aren't kept.
- `SingleFlight`: callers asking for the same thing at the same moment share one request.

Limits can be changed with environment variables, for example TIDECOUNT_OBIS_PER_MINUTE=120.
"""
import collections
import ipaddress
import os
import random
import threading
import time
import urllib.error
from concurrent.futures import Future, ThreadPoolExecutor


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class Busy(urllib.error.URLError):
    """Too much is going on right now. A URLError, so every caller that falls back to a cached
    answer when OBIS can't be reached does the same here."""

    def __init__(self, message: str, retry_after: float = 5.0):
        super().__init__(message)
        self.retry_after = max(1.0, float(retry_after))


class RateLimited(Exception):
    """One visitor asked too often."""

    def __init__(self, message: str, retry_after: float):
        super().__init__(message)
        self.retry_after = max(1.0, float(retry_after))


# --- the outbound budget ------------------------------------------------------------------------

class Budget:
    """Concurrency, rate and volume limits for requests to OBIS, plus a circuit breaker.

    Two kinds of caller share it. A visitor's own request (the map, the totals) is small and someone
    is waiting for it. A background job (eDNA, net surveys) sends dozens in a row. Left to compete,
    a handful of jobs would use every turn and the maps would fail, so each kind has its own places
    among the requests in flight and its own rate, and jobs may use at most `job_share` of the
    per-minute and per-hour volume. Together they stay inside the totals."""

    def __init__(self, concurrent=10, reserved=3, job_per_second=3.0, visitor_per_second=2.0, burst=6,
                 per_minute=240, per_hour=3000, job_share=0.75, trip_after=5, clock=time.monotonic, sleep=time.sleep):
        self.concurrent, self.reserved, self.burst, self.trip_after = concurrent, reserved, burst, trip_after
        self.per_minute, self.per_hour = per_minute, per_hour
        self._rate = {True: job_per_second, False: visitor_per_second}
        self._caps = {True: (int(per_minute * job_share), int(per_hour * job_share)), False: (per_minute, per_hour)}
        self._clock, self._sleep = clock, sleep
        self._slots = {True: threading.BoundedSemaphore(max(1, concurrent - reserved)), False: threading.BoundedSemaphore(max(1, reserved))}
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._tokens = {True: float(self.burst), False: float(self.burst)}
            self._stamp = {True: self._clock(), False: self._clock()}
            self._minute = {True: collections.deque(), False: collections.deque()}  # when each kind's requests were let through
            self._hour = {True: collections.deque(), False: collections.deque()}
            self._failures = 0
            self._trips = 0
            self._open_until = 0.0
            self.sent = 0  # requests let through, for reports

    def paused_for(self) -> float:
        return max(0.0, self._open_until - self._clock())

    @staticmethod
    def _count(windows, span, now) -> tuple[int, float | None]:
        """How many events (both kinds) fall in the last `span` seconds, and the oldest one's time."""
        for d in windows.values():
            while d and now - d[0] > span:
                d.popleft()
        times = [d[0] for d in windows.values() if d]
        return sum(len(d) for d in windows.values()), min(times) if times else None

    def acquire(self, wait_s: float, patient: bool = False) -> None:
        """Wait up to `wait_s` for permission to send one request, or raise Busy. `patient` is for
        background jobs; call release(patient) when the request is over."""
        left = self.paused_for()
        if left:
            raise Busy(f"OBIS is not answering well, so requests are paused for about {int(left) + 1} s.", left)
        deadline = self._clock() + wait_s
        cap_minute, cap_hour = self._caps[patient]
        # First a turn in the rate and volume limits, without holding a place among the requests in
        # flight, so callers waiting for the minute to clear can't shut out everyone else.
        while True:
            with self._lock:
                now = self._clock()
                self._tokens[patient] = min(self.burst, self._tokens[patient] + (now - self._stamp[patient]) * self._rate[patient])
                self._stamp[patient] = now
                pause = 0.0 if self._tokens[patient] >= 1.0 else (1.0 - self._tokens[patient]) / self._rate[patient]
                for windows, span, total_cap, kind_cap in ((self._minute, 60.0, self.per_minute, cap_minute), (self._hour, 3600.0, self.per_hour, cap_hour)):
                    everyone, oldest = self._count(windows, span, now)
                    mine = windows[patient]
                    if everyone >= total_cap and oldest is not None:
                        pause = max(pause, span - (now - oldest))
                    if len(mine) >= kind_cap and mine:
                        pause = max(pause, span - (now - mine[0]))
                if pause <= 0.0:
                    self._tokens[patient] -= 1.0
                    self._minute[patient].append(now)
                    self._hour[patient].append(now)
                    self.sent += 1
                    break
            if self._clock() + pause > deadline:
                raise Busy(f"This server is already making as many OBIS requests as it allows. Try again in about {int(pause) + 1} s.", pause)
            self._sleep(pause)
        if not self._slots[patient].acquire(timeout=max(0.0, deadline - self._clock())):
            raise Busy("The server is already making as many OBIS requests as it allows. Try again in a few seconds.", 3)

    def release(self, patient: bool = False) -> None:
        self._slots[patient].release()

    def success(self) -> None:
        with self._lock:
            self._failures = 0
            self._trips = 0

    def failure(self, pause_s: float | None = None) -> None:
        """A request failed in a way that suggests OBIS is struggling. `pause_s` (from a 429's
        Retry-After) pauses everything at once; otherwise a run of failures opens the breaker."""
        with self._lock:
            now = self._clock()
            if pause_s is not None:
                self._open_until = max(self._open_until, now + min(120.0, max(1.0, pause_s)))
                return
            self._failures += 1
            if self._failures >= self.trip_after:
                self._trips += 1
                self._failures = 0
                self._open_until = now + min(300.0, 30.0 * 2 ** (self._trips - 1))


def backoff(attempt: int, retry_after: float | None = None) -> float:
    """Seconds to wait before retry number `attempt` (0 for the first retry): OBIS's own
    Retry-After when it gave one, else 1 s, 2 s, 4 s plus a little jitter."""
    if retry_after:
        return min(20.0, retry_after)
    return min(20.0, 2.0 ** attempt) + random.random() * 0.5


# --- visitors ----------------------------------------------------------------------------------

class Limiter:
    """At most `limit` events per `window_s` for each key (a visitor's address). It remembers at
    most `max_keys` visitors, forgetting the quietest, so strangers can't make it grow."""

    def __init__(self, limit: int, window_s: float, max_keys: int = 4096, clock=time.monotonic):
        self.limit, self.window_s, self.max_keys, self._clock = limit, window_s, max_keys, clock
        self._hits: collections.OrderedDict[str, collections.deque] = collections.OrderedDict()
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def check(self, key: str) -> float | None:
        """None when the event is allowed (and counted), else seconds until it would be."""
        with self._lock:
            now = self._clock()
            q = self._hits.pop(key, None) or collections.deque()
            while q and now - q[0] > self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                self._hits[key] = q
                return self.window_s - (now - q[0])
            q.append(now)
            self._hits[key] = q  # most recently used goes last
            while len(self._hits) > self.max_keys:
                self._hits.popitem(last=False)
            return None


def client_ip(peer: str | None, forwarded: str | None) -> str:
    """The visitor's address. Caddy, in front of the app, sets X-Forwarded-For to the address it
    saw, so when the direct peer is a private one (Caddy, on Docker's network) the last entry is
    the visitor. From anywhere else the header is ignored, since a visitor could write it."""
    try:
        private = ipaddress.ip_address(peer or "").is_private
    except ValueError:
        private = False
    if private and forwarded:
        last = forwarded.split(",")[-1].strip()
        try:
            return str(ipaddress.ip_address(last))
        except ValueError:
            pass
    return peer or "unknown"


# --- shared requests ---------------------------------------------------------------------------

class SingleFlight:
    """Callers asking for the same key at the same moment share one run of `fn`."""

    def __init__(self):
        self._lock = threading.Lock()
        self._running: dict[str, Future] = {}

    def do(self, key: str, fn, wait_s: float = 60.0):
        with self._lock:
            future = self._running.get(key)
            leader = future is None
            if leader:
                future = self._running[key] = Future()
        if not leader:
            return future.result(timeout=wait_s)  # the leader's answer, or its error
        try:
            result = fn()
        except BaseException as e:
            future.set_exception(e)
            raise
        else:
            future.set_result(result)
            return result
        finally:
            with self._lock:
                self._running.pop(key, None)


# --- background jobs ---------------------------------------------------------------------------

class Job:
    """One background calculation. `check()` is called by the work itself between requests, so a
    job that runs too long or asks OBIS too often stops."""

    def __init__(self, key: str, deadline_s: float, max_requests: int):
        self.key = key
        self.state = "queued"        # queued, running, done, failed
        self.created = time.monotonic()
        self.finished = 0.0
        self.deadline_s, self.max_requests = deadline_s, max_requests
        self.deadline = 0.0
        self.requests = 0
        self.partial = None          # what can be shown before the job is done
        self.progress: dict | None = None
        self.result = None           # only kept when the disk cache couldn't hold it
        self.error = ""
        self.cancelled = False       # set when part of the work has failed, so the rest stops
        self.fetched_at = 0.0        # when the result was made, as a wall-clock time
        self.ready = threading.Event()  # set once there is something to show, or the job ended
        self._lock = threading.Lock()

    def check(self) -> None:
        if self.cancelled:
            raise RuntimeError("the calculation was stopped")
        with self._lock:
            self.requests += 1
            if self.requests > self.max_requests:
                raise TimeoutError(f"the calculation needed more than {self.max_requests} OBIS requests")
        if self.deadline and time.monotonic() > self.deadline:
            raise TimeoutError(f"the calculation ran longer than {int(self.deadline_s)} s")


class JobQueue:
    """Runs `max_running` jobs at once and lets `max_queued` more wait. A request for work that is
    already queued or running joins it. Finished jobs are forgotten (their answer is in the disk
    cache) unless they hold a result the cache couldn't store, and failures are remembered briefly
    so a broken calculation isn't restarted by every poll."""

    def __init__(self, max_running=2, max_queued=6, deadline_s=240.0, max_requests=400,
                 fail_hold_s=60.0, result_hold_s=600.0, max_kept=8, name="api-job"):
        self.max_running, self.max_queued = max_running, max_queued
        self.deadline_s, self.max_requests = deadline_s, max_requests
        self.fail_hold_s, self.result_hold_s, self.max_kept = fail_hold_s, result_hold_s, max_kept
        self._exec = ThreadPoolExecutor(max_workers=max_running, thread_name_prefix=name)
        self._jobs: collections.OrderedDict[str, Job] = collections.OrderedDict()
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._jobs.clear()

    def _prune(self) -> None:
        now = time.monotonic()
        for key, job in list(self._jobs.items()):
            if job.state == "done" and (job.result is None or now - job.finished > self.result_hold_s):
                del self._jobs[key]
            elif job.state == "failed" and now - job.finished > self.fail_hold_s:
                del self._jobs[key]
        kept = [k for k, j in self._jobs.items() if j.state in ("done", "failed")]
        for key in kept[: max(0, len(kept) - self.max_kept)]:
            del self._jobs[key]

    def get(self, key: str) -> Job | None:
        with self._lock:
            self._prune()
            return self._jobs.get(key)

    def active(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.state in ("queued", "running"))

    def ahead_of(self, job: Job) -> int:
        """Jobs that will be taken before this queued one."""
        with self._lock:
            return sum(1 for j in self._jobs.values() if j is not job and (j.state == "running" or (j.state == "queued" and j.created < job.created)))

    def start(self, key: str, work, on_start=None) -> tuple[Job, bool]:
        """Join the job for `key`, or start it. Returns (job, started). Raises Busy when the queue
        is full; `on_start`, which may raise RateLimited, is called only when a new job would start."""
        with self._lock:
            self._prune()
            job = self._jobs.get(key)
            if job and job.state in ("queued", "running", "failed"):
                return job, False
            if sum(1 for j in self._jobs.values() if j.state in ("queued", "running")) >= self.max_running + self.max_queued:
                raise Busy("Several large calculations are already running or waiting. Try again in a minute.", 30)
            if on_start:
                on_start()
            job = Job(key, self.deadline_s, self.max_requests)
            self._jobs[key] = job
        self._exec.submit(self._run, job, work)
        return job, True

    def _run(self, job: Job, work) -> None:
        job.state = "running"
        job.deadline = time.monotonic() + job.deadline_s
        try:
            work(job)
            job.state = "done"
        except BaseException as e:  # reported to whoever polls; nothing escapes into the pool
            job.error = f"{e.__class__.__name__}: {e}"
            job.state = "failed"
        finally:
            job.partial = None if job.state == "done" else job.partial
            job.finished = time.monotonic()
            job.ready.set()


def patient_thread() -> bool:
    """Background jobs (and the helper threads they use, all named "api-job…") may wait longer for
    a budget and retry; a visitor's own request may not."""
    return threading.current_thread().name.startswith("api-job")


RETRY_CODES = (429, 502, 503, 504)


def _retry_after(e: urllib.error.HTTPError) -> float | None:
    try:
        value = e.headers.get("Retry-After") if e.headers else None
        return float(value) if value else None
    except (TypeError, ValueError):
        return None


def call(budget: "Budget", url: str, opener, *, timeout=25.0, job_timeout=60.0, wait_s=5.0, job_wait_s=60.0, retries=2):
    """Send one request through `budget` and return what `opener(url, timeout)` returns.

    A visitor's request tries once and gives up quickly. A background job waits for its turn and
    retries a timeout, a 429 or a 5xx with backoff. A 429 pauses the whole service for its
    Retry-After; a run of failures opens the breaker. Our own mistakes (a 400) are neither retried
    nor counted against the service. Raises Busy when the budget or breaker says no, otherwise the
    last error."""
    patient = patient_thread()
    last: BaseException | None = None
    for attempt in range(1 + (retries if patient else 0)):
        budget.acquire(job_wait_s if patient else wait_s, patient)  # raises Busy
        retry_after = None
        try:
            data = opener(url, job_timeout if patient else timeout)
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_CODES:
                raise
            retry_after = _retry_after(e)
            budget.failure(pause_s=(retry_after or 30) if e.code == 429 else None)
            last = e
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            budget.failure()
            last = e
        else:
            budget.success()
            return data
        finally:
            budget.release(patient)
        if isinstance(last, urllib.error.HTTPError) and last.code == 429:
            break  # the whole service is paused now; retrying would only be refused
        if attempt < retries and patient:
            time.sleep(backoff(attempt, retry_after))
    raise last


# --- the limits this deployment uses -----------------------------------------------------------

_budgets: dict[str, Budget] = {}


def budget(service: str) -> Budget:
    """The outbound budget for a service, made on first use. Defaults are deliberately gentle for
    a public API we don't pay for: four requests in flight (two kept for visitors), about two a
    second, 180 a minute and 2,000 an hour. Each can be changed with TIDECOUNT_<SERVICE>_CONCURRENT,
    _RESERVED, _JOB_PER_SECOND, _VISITOR_PER_SECOND, _BURST, _PER_MINUTE and _PER_HOUR."""
    if service not in _budgets:
        p = f"TIDECOUNT_{service.upper()}_"
        _budgets[service] = Budget(
            concurrent=_int(p + "CONCURRENT", 4),
            reserved=_int(p + "RESERVED", 2),
            job_per_second=float(_int(p + "JOB_PER_SECOND", 1)),
            visitor_per_second=float(_int(p + "VISITOR_PER_SECOND", 2)),
            burst=_int(p + "BURST", 4),
            per_minute=_int(p + "PER_MINUTE", 180),   # background jobs may use three quarters of the volume
            per_hour=_int(p + "PER_HOUR", 2000),
        )
    return _budgets[service]


# Background jobs, shared by every service: one at a time and a few waiting is plenty here.
jobs = JobQueue(
    max_running=_int("TIDECOUNT_API_JOBS_RUNNING", 1),
    max_queued=_int("TIDECOUNT_API_JOBS_QUEUED", 4),
    deadline_s=float(_int("TIDECOUNT_API_JOB_SECONDS", 300)),
    max_requests=_int("TIDECOUNT_API_JOB_REQUESTS", 400),
)
flight = SingleFlight()
visits = Limiter(_int("TIDECOUNT_WIKI_PER_MINUTE", 300), 60.0)          # every species-wiki map call; one eDNA section polls about 24 times a minute, and a classroom may share an address
job_starts = Limiter(_int("TIDECOUNT_WIKI_JOBS_PER_10_MIN", 12), 600.0)  # new background calculations
inflight = threading.BoundedSemaphore(_int("TIDECOUNT_WIKI_INFLIGHT", 12))  # map calls at once; the rest of the app keeps its threads


def charge_job_start(ip: str) -> None:
    wait = job_starts.check(ip)
    if wait is not None:
        raise RateLimited("You've started several large calculations in a short time. Try again in a few minutes.", wait)


def reset() -> None:
    """Forget all state. For tests."""
    for b in _budgets.values():
        b.reset()
    jobs.reset()
    visits.reset()
    job_starts.reset()


# Adding another service, for example GBIF:
#   1. in its module, `BUDGET = api_guard.budget("gbif")`, and fetch with
#      `api_guard.call(BUDGET, url, opener)`, where opener(url, timeout) returns parsed JSON;
#   2. cache answers with api_cache.read/write(..., namespace="gbif");
#   3. share requests with api_guard.flight.do(url, fn) and run slow work with api_guard.jobs.
# The per-visitor limits, request threads and job queue are already shared.
