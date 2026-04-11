import json
import logging
import os
import tempfile
from datetime import datetime, timezone

log = logging.getLogger(__name__)

DATA_DIR = os.environ.get("DATA_DIR", "/data")
STATE_FILE = os.path.join(DATA_DIR, "wake-history.json")
MAX_HISTORY = 10
STALE_SECONDS = 300  # Clean active entries older than 5 minutes


def _load():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"history": {}, "active": {}}


def _save(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, STATE_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _cleanup_stale(data):
    now = datetime.now(timezone.utc)
    active = data.get("active", {})
    stale = [
        k for k, v in active.items()
        if (now - datetime.fromisoformat(v)).total_seconds() > STALE_SECONDS
    ]
    for k in stale:
        del active[k]
        log.info("Cleaned stale active wake: %s", k)


def record_wake_start(namespace, name):
    key = f"{namespace}/{name}"
    data = _load()
    data.setdefault("active", {})[key] = datetime.now(timezone.utc).isoformat()
    _cleanup_stale(data)
    _save(data)
    log.info("Recorded wake start for %s", key)


def record_wake_complete(namespace, name):
    key = f"{namespace}/{name}"
    data = _load()
    start_str = data.get("active", {}).pop(key, None)
    if not start_str:
        _save(data)
        return None
    start = datetime.fromisoformat(start_str)
    duration = round((datetime.now(timezone.utc) - start).total_seconds(), 1)
    history = data.setdefault("history", {})
    durations = history.setdefault(key, [])
    durations.append(duration)
    if len(durations) > MAX_HISTORY:
        history[key] = durations[-MAX_HISTORY:]
    _save(data)
    log.info("Wake complete for %s: %.1fs", key, duration)
    return duration


def get_eta(namespace, name):
    key = f"{namespace}/{name}"
    data = _load()
    durations = data.get("history", {}).get(key, [])
    if not durations:
        return None
    return round(sum(durations) / len(durations), 1)


def get_wake_start(namespace, name):
    key = f"{namespace}/{name}"
    data = _load()
    start_str = data.get("active", {}).get(key)
    if not start_str:
        return None
    return datetime.fromisoformat(start_str)
