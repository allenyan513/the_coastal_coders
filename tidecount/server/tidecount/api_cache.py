"""A disk cache for answers from other people's APIs, with a size limit so it can never take the disk
the videos and the database need. Each service has its own folder, data/cache/<namespace>/ (the
species wiki's OBIS answers are in data/cache/obis/), with one JSON file per answer.

- A folder holds at most MAX_BYTES and MAX_FILES (defaults 256 MB and 20,000 files). Past that, the
  least recently used answers go first. Answers that took minutes to compute (names starting
  "edna-" and "nd-") go last.
- An answer bigger than MAX_FILE_BYTES isn't stored.
- Nothing is stored when the disk has less than MIN_FREE_BYTES free (default 5 GB), and the
  cheap answers are cleared to make room.
- Answers older than STALE_MAX_S are removed, and leftovers of interrupted writes after ten minutes.
- Every write goes to a file of its own and is renamed into place, so two requests for the same
  answer can't corrupt or lose each other's file. A failed write is skipped; it never fails a request.

Limits can be changed with TIDECOUNT_CACHE_MB, TIDECOUNT_CACHE_FILES and TIDECOUNT_CACHE_MIN_FREE_GB.
Only one file is read into memory at a time.
"""
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from . import config


def _env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


MAX_BYTES = int(_env("TIDECOUNT_CACHE_MB", 256) * 1024 * 1024)
MAX_FILES = int(_env("TIDECOUNT_CACHE_FILES", 20000))
MIN_FREE_BYTES = int(_env("TIDECOUNT_CACHE_MIN_FREE_GB", 5) * 1024 ** 3)
MAX_FILE_BYTES = 4 * 1024 * 1024
STALE_MAX_S = 45 * 24 * 3600
SWEEP_EVERY_S = 600
EXPENSIVE = ("edna-", "nd-")  # name prefixes of answers that are slow to rebuild

_lock = threading.Lock()
_states: dict[str, dict] = {}  # per folder: what it held when last counted


def folder(namespace: str = "obis") -> Path:
    path = config.DATA / "cache" / namespace
    path.mkdir(parents=True, exist_ok=True)
    return path


def _file(key: str, kind: str = "", namespace: str = "obis") -> Path:
    return folder(namespace) / f"{kind}{hashlib.sha1(key.encode()).hexdigest()}.json"


def read(key: str, kind: str = "", namespace: str = "obis") -> dict | None:
    """The stored {"fetched_at", "data", ...}, or None. Reading counts as use for eviction."""
    file = _file(key, kind, namespace)
    try:
        stored = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(stored, dict) or "fetched_at" not in stored or "data" not in stored:
            return None
    except (OSError, ValueError):
        return None
    try:
        os.utime(file)
    except OSError:
        pass
    return stored


def write(key: str, data, kind: str = "", fetched_at: float | None = None, namespace: str = "obis") -> bool:
    """Store an answer. True when it was stored; False when it was skipped for size or disk space."""
    body = json.dumps({"key": key, "fetched_at": fetched_at or time.time(), "data": data}, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_FILE_BYTES:
        return False
    file = _file(key, kind, namespace)
    tmp = file.with_name(f"{file.name}.{uuid.uuid4().hex}.tmp")
    with _lock:
        state = _sync(namespace)
        try:
            if _free(namespace) < MIN_FREE_BYTES:
                _sweep(namespace, state, target=0.0, keep_expensive=True)  # short of space: drop what is cheap to rebuild
                if _free(namespace) < MIN_FREE_BYTES:
                    return False
            old = file.stat().st_size if file.exists() else None
            tmp.write_bytes(body)
            os.replace(tmp, file)
        except OSError:
            tmp.unlink(missing_ok=True)
            return False
        state["bytes"] += len(body) - (old or 0)
        state["files"] += 0 if old is not None else 1
        if state["bytes"] > MAX_BYTES or state["files"] > MAX_FILES or time.time() - state["swept"] > SWEEP_EVERY_S:
            _sweep(namespace, state, target=0.8)
    return True


def sweep(namespace: str = "obis") -> dict:
    """Remove what is expired or over the limits now. Returns what is left."""
    with _lock:
        state = _sync(namespace)
        _sweep(namespace, state, target=0.8)
        return {"bytes": state["bytes"], "files": state["files"]}


def usage(namespace: str = "obis") -> dict:
    with _lock:
        state = _sync(namespace)
        return {"bytes": state["bytes"], "files": state["files"], "max_bytes": MAX_BYTES, "max_files": MAX_FILES}


def _free(namespace: str) -> int:
    try:
        return shutil.disk_usage(folder(namespace)).free
    except OSError:
        return MIN_FREE_BYTES  # can't tell: don't refuse to cache


def _sync(namespace: str) -> dict:
    """The folder's counts, taken when it is first used (and again if the data folder changed)."""
    here = str(folder(namespace))
    state = _states.get(here)
    if state is None:
        state = _states[here] = {"bytes": 0, "files": 0, "swept": 0.0}
        _sweep(namespace, state, target=0.8)
    return state


def _sweep(namespace: str, state: dict, target: float, keep_expensive: bool = False) -> None:
    """Delete expired files, then the least recently used until under `target` of each limit.
    Cheap-to-rebuild answers go before expensive ones. Caller holds the lock."""
    now = time.time()
    entries = []
    try:
        listing = list(os.scandir(folder(namespace)))
    except OSError:
        return
    for e in listing:
        try:
            st = e.stat()
        except OSError:
            continue
        if e.name.endswith(".tmp"):
            if now - st.st_mtime > 600:
                try:
                    os.unlink(e.path)
                except OSError:
                    pass
            continue
        if not e.name.endswith(".json"):
            continue
        if now - st.st_mtime > STALE_MAX_S:
            try:
                os.unlink(e.path)
            except OSError:
                pass
            continue
        entries.append((e.name.startswith(EXPENSIVE), st.st_mtime, st.st_size, e.path))
    total, count = sum(x[2] for x in entries), len(entries)
    limit_bytes, limit_files = MAX_BYTES * target, MAX_FILES * target
    for expensive, _mtime, size, path in sorted(entries):  # cheap first, oldest first
        if total <= limit_bytes and count <= limit_files:
            break
        if expensive and keep_expensive:
            break  # sorted, so only expensive answers are left
        try:
            os.unlink(path)
        except OSError:
            continue
        total, count = total - size, count - 1
    state.update(bytes=total, files=count, swept=now)
