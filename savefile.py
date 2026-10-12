"""Versioned, crash-safe JSON persistence for every file the game writes.

Covered formats (each one is a JSON object with an integer "version" key):

- progress.json      PROGRESS_VERSION      owned by progress.py (wave 1); it calls load_versioned / save_versioned.
- user_settings.json USER_SETTINGS_VERSION audio volumes and the screen shake level (audio.py, shake_prefs.py).
- high_scores.json   HIGH_SCORES_VERSION   per-difficulty boards (score.py).

Rules shared by every format:

- Load never raises. A missing file, or a file in a missing folder, reads as the defaults.
- An unversioned file (no "version" key, or an invalid one) is treated as version 0. Each load runs the
  format's migrate step, which brings the data up to the current shape in memory and stamps the version.
  The file on disk is rewritten at the current version on the next save.
- A corrupt file is renamed once to <name>.corrupt-<n> (n is the first free number) and the caller gets
  the defaults. A corrupt file is "not JSON", "not valid UTF-8", or "a top-level value that is not an
  object". The bad bytes stay on disk for inspection. They are never silently overwritten.
- A file written by a newer build (version above the current one) is read best effort, its version is
  kept, and unknown keys are kept on save. Nothing is downgraded.
- Every write goes through atomic_write_json: a temp file in the same folder, flush and fsync, then
  os.replace. A failed write leaves the previous file intact and returns False. Missing folders are created.
- Save and update helpers never raise.

Settings helpers (load_settings, update_settings) are the shared path for user_settings.json. Code that
adds a new key should call update_settings(path, {...}) so every other key is preserved.
"""

import json
import math
import os
import shutil
import tempfile

VERSION_KEY = "version"

PROGRESS_VERSION = 1
USER_SETTINGS_VERSION = 1
HIGH_SCORES_VERSION = 1

_SHAKE_LEVEL_KEY = "shake_level"
_LEGACY_SHAKE_KEY = "reduced_shake"


# ---------------------------------------------------------------------------
# Atomic writes and corrupt-file quarantine
# ---------------------------------------------------------------------------

def atomic_write_json(path: str, data: dict, indent: int = 2) -> bool:
    """Write ``data`` as JSON to ``path`` atomically. Returns True on success. Never raises.

    The text is serialised first, so a bad value never leaves a partial temp file. The temp file lives in
    the target's folder so os.replace is a rename on one volume.
    """
    try:
        text = json.dumps(data, indent=indent)
    except (TypeError, ValueError):
        return False
    tmp = None
    try:
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=os.path.basename(path) + ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        tmp = None
        return True
    except Exception:
        return False
    finally:
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass


def quarantine(path: str):
    """Rename a corrupt file to <path>.corrupt-<n>, using the first free n. Returns the new path or None.

    Falls back to a copy when the rename is refused, so the bad bytes survive either way. Never raises.
    """
    try:
        n = 1
        while os.path.exists(f"{path}.corrupt-{n}"):
            n += 1
        dest = f"{path}.corrupt-{n}"
        try:
            os.replace(path, dest)
            return dest
        except OSError:
            shutil.copyfile(path, dest)
            return dest
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Generic versioned load and save
# ---------------------------------------------------------------------------

def _read_version(data: dict) -> int:
    value = data.get(VERSION_KEY)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _with_version(data: dict, version: int) -> dict:
    """Return a copy with the version key first, so files read as {"version": 1, ...}."""
    out = {VERSION_KEY: version}
    for key, value in data.items():
        if key != VERSION_KEY:
            out[key] = value
    return out


def load_versioned(path: str, current: int, migrate, default) -> dict:
    """Return the file at ``path`` migrated to version ``current``. Never raises.

    ``migrate(data, version)`` receives a copy of the object and the version it was written at. It must
    return a dict in the current shape and must not raise. ``default()`` gives a fresh dict for missing
    or unreadable input. A corrupt file is quarantined first.
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return default()
    try:
        data = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("top-level JSON value is not an object")
        version = _read_version(data)
        migrated = migrate(dict(data), version)
        if not isinstance(migrated, dict):
            raise ValueError("migrate did not return an object")
    except Exception:
        quarantine(path)
        return default()
    return _with_version(migrated, max(current, version))


def save_versioned(path: str, data: dict, current: int) -> bool:
    """Write ``data`` with its version stamped (never lower than ``current``). Returns True on success."""
    if not isinstance(data, dict):
        return False
    stamp = current
    existing = data.get(VERSION_KEY)
    if not isinstance(existing, bool) and isinstance(existing, int) and existing > current:
        stamp = existing
    body = {k: v for k, v in data.items() if k != VERSION_KEY}
    return atomic_write_json(path, _with_version(body, stamp))


# ---------------------------------------------------------------------------
# Format: user_settings.json
# ---------------------------------------------------------------------------

def migrate_user_settings(data: dict, version: int) -> dict:
    """v0 -> v1: stamp the version, and derive shake_level from the legacy reduced_shake flag.

    Current-build files already carry shake_level and reduced_shake. The derivation only matters for
    the oldest builds, which wrote reduced_shake alone.
    """
    out = dict(data)
    if not isinstance(out.get(_SHAKE_LEVEL_KEY), str):
        legacy = out.get(_LEGACY_SHAKE_KEY)
        if isinstance(legacy, bool):
            out[_SHAKE_LEVEL_KEY] = "reduced" if legacy else "full"
    return out


def load_settings(path: str) -> dict:
    """Return the settings object at ``path`` (version stamped). Missing or corrupt reads as {}."""
    return load_versioned(path, USER_SETTINGS_VERSION, migrate_user_settings, dict)


def update_settings(path: str, changes: dict) -> bool:
    """Merge ``changes`` into the settings file, keeping every other key. Returns True on success. Never raises."""
    try:
        data = load_settings(path)
        data.update(changes)
        return save_versioned(path, data, USER_SETTINGS_VERSION)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Format: high_scores.json
# ---------------------------------------------------------------------------

def _to_int(value):
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _clean_board(entries: list) -> list:
    """Keep only dict entries whose score is an integer. Other keys in an entry are kept as-is."""
    clean = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        score = _to_int(entry.get("score"))
        if score is None:
            continue
        item = dict(entry)
        item["score"] = score
        clean.append(item)
    return clean


def migrate_high_scores(data: dict, version: int) -> dict:
    """v0 -> v1: the board shape is unchanged. The step stamps the version and drops malformed entries.

    Every list-valued key is treated as a board and cleaned. Other keys are extras and are kept untouched,
    so a file with extra keys still loads and keeps them on save.
    """
    out = dict(data)
    for key, value in list(out.items()):
        if key != VERSION_KEY and isinstance(value, list):
            out[key] = _clean_board(value)
    return out


def board_entries(data: dict, difficulty: str) -> list:
    """Return a fresh list of the valid entries for ``difficulty``. A missing or non-list board is empty."""
    entries = data.get(difficulty)
    if not isinstance(entries, list):
        return []
    return _clean_board(entries)


# ---------------------------------------------------------------------------
# Format: progress.json (the progress.py owner calls these)
# ---------------------------------------------------------------------------

def migrate_progress(data: dict, version: int) -> dict:
    """v0 -> v1: stamp the version. progress.py adds its own key migrations here as the format grows."""
    return dict(data)
