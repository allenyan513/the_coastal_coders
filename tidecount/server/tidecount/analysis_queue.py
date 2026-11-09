"""Where each waiting video stands in the analysis queue, and roughly how long it has to wait.

The worker analyses one video at a time, in ORDER. A video's place is how many will start before it.

Times come from this computer's own history: the median seconds of work per second of footage over
the last few finished runs, with the same detector when there are some. A video's expected run is
that rate times its length. Nothing is guessed on a computer that hasn't finished a run yet, so the
answer then has the place and no times. A video whose length isn't known yet (the upload couldn't
be read) is taken to be as long as the usual video here.
"""
import statistics
import time

# A retry sets queued_at, so it waits behind what was already queued. Rows from before the column
# existed, or added without it, fall back to when they were made. rowid breaks ties within a second.
ORDER = "COALESCE(queued_at, (julianday(created_at) - 2440587.5) * 86400.0), rowid"
HISTORY = 10  # finished runs the rate is taken from


def next_queued(con) -> str | None:
    row = con.execute(f"SELECT id FROM videos WHERE status = 'Queued' ORDER BY {ORDER} LIMIT 1").fetchone()
    return row["id"] if row else None


def _rates(con) -> tuple[dict[str, float], float | None]:
    """Seconds of work per second of footage: by detector, and over every detector."""
    rows = con.execute(
        "SELECT detector, (finished_at - started_at) / duration AS rate FROM videos"
        " WHERE status = 'Ready to review' AND duration > 0 AND finished_at > started_at"
        " ORDER BY finished_at DESC"
    ).fetchall()
    by: dict[str, list[float]] = {}
    for r in rows:
        by.setdefault(r["detector"], []).append(r["rate"])
    per = {d: statistics.median(v[:HISTORY]) for d, v in by.items()}
    overall = statistics.median([r["rate"] for r in rows[:HISTORY]]) if rows else None
    return per, overall


def _usual_length(con) -> float | None:
    rows = con.execute(f"SELECT duration FROM videos WHERE duration > 0 ORDER BY {ORDER} DESC LIMIT {HISTORY}").fetchall()
    return statistics.median([r["duration"] for r in rows]) if rows else None


def estimate(con, now: float | None = None) -> dict[str, dict]:
    """{video id: {ahead, starts_in_s, done_in_s}} for every Queued or Analyzing video. A time is
    None when it can't be estimated. A running video past its estimate has done_in_s 0."""
    now = time.time() if now is None else now
    per, overall = _rates(con)
    usual = _usual_length(con)

    def expected(v) -> float | None:
        rate = per.get(v["detector"], overall)
        length = v["duration"] or usual
        return rate * length if rate and length else None

    out: dict[str, dict] = {}
    wait: float | None = 0.0  # until the next queued video starts
    running = con.execute("SELECT id, detector, duration, started_at FROM videos WHERE status = 'Analyzing' ORDER BY started_at").fetchall()
    for v in running:
        run = expected(v)
        left = max(0.0, run - (now - v["started_at"])) if run is not None and v["started_at"] else None
        out[v["id"]] = {"ahead": 0, "starts_in_s": 0.0, "done_in_s": left}
        wait = wait + left if wait is not None and left is not None else None
    ahead = len(running)
    for v in con.execute(f"SELECT id, detector, duration FROM videos WHERE status = 'Queued' ORDER BY {ORDER}").fetchall():
        run = expected(v)
        done = wait + run if wait is not None and run is not None else None
        out[v["id"]] = {"ahead": ahead, "starts_in_s": wait, "done_in_s": done}
        wait, ahead = done, ahead + 1
    return out
