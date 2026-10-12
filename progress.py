"""Persistent meta-progress: best run, lifetime totals, unlocked skins and achievements.

The record lives in one JSON file, ``progress.json``, at the project root. Public API:

    default_progress() -> dict
        A fresh record with every key set.
    load(path=None) -> dict
        Never raises. A missing, unreadable or corrupt file gives default_progress(), and
        fields with a bad type or a negative count fall back to their defaults.
    save(data, path=None) -> bool
        Atomic write: the JSON goes to a temp file in the same folder, then os.replace
        swaps it in, so a crash mid-write never leaves a half-written progress.json.
        Never raises. Returns False when the write failed.
    apply_run(data, stats) -> dict
        Folds one finished run's stats into the lifetime record. Pure, no I/O.
    end_run(run, path=None) -> dict
        Call once when a run ends. Loads the record, merges the run, evaluates achievements,
        refreshes skin unlocks, and saves once. Returns a summary dict with the keys
        "saved", "progress", "new_achievements" and "new_skins".

``path=None`` means PROGRESS_FILE, read at call time, so tests can point it at a temp file
by assigning ``progress.PROGRESS_FILE``. Importing this module does no I/O.
"""

import math
import os

import savefile

import achievements
import skins


SCHEMA_VERSION = 1
PROGRESS_FILENAME = "progress.json"
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PROGRESS_FILE = os.path.join(PROJECT_ROOT, PROGRESS_FILENAME)

_COUNT_FIELDS = ("best_wave", "best_score", "total_kills", "bosses_defeated", "runs_played")
_ID_LIST_FIELDS = ("unlocked_skins", "achievements")


def default_progress() -> dict:
    """A fresh record: no runs, nothing unlocked beyond the default skin."""
    return {
        "version": SCHEMA_VERSION,
        "best_wave": 0,
        "best_score": 0,
        "total_kills": 0,
        "bosses_defeated": 0,
        "runs_played": 0,
        "unlocked_skins": [],
        "achievements": [],
        "selected_skin": skins.DEFAULT_SKIN_ID,
    }


def _coerce_count(value, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    if not math.isfinite(value) or value < 0:
        return default
    return int(value)


def _coerce_ids(value) -> list:
    if not isinstance(value, list):
        return []
    seen: list[str] = []
    for item in value:
        if isinstance(item, str) and item and item not in seen:
            seen.append(item)
    return seen


def _normalise(raw) -> dict:
    """Return a complete record built from ``raw``. Unknown keys are kept for forward compatibility."""
    base = default_progress()
    if not isinstance(raw, dict):
        return base
    data = dict(raw)
    for key in _COUNT_FIELDS:
        data[key] = _coerce_count(raw.get(key), base[key])
    for key in _ID_LIST_FIELDS:
        data[key] = _coerce_ids(raw.get(key))
    selected = raw.get("selected_skin")
    data["selected_skin"] = selected if isinstance(selected, str) and selected else base["selected_skin"]
    data["version"] = SCHEMA_VERSION
    return data


def load(path=None) -> dict:
    """Read the progress record through savefile. Never raises.

    A missing file gives defaults. A corrupt file is quarantined by savefile (renamed to
    progress.json.corrupt-<n>) and the caller gets defaults. Fields with a bad type fall back.
    """
    target = PROGRESS_FILE if path is None else path
    data = savefile.load_versioned(target, savefile.PROGRESS_VERSION, savefile.migrate_progress, default_progress)
    return _normalise(data)


def save(data: dict, path=None) -> bool:
    """Write the record through savefile's atomic helper. Returns True on success and never raises.

    The temp file sits beside the target so os.replace is a same-volume rename. On any
    failure the temp file is removed and the previous progress.json is left as it was.
    """
    target = os.path.abspath(PROGRESS_FILE if path is None else path)
    if not os.path.isdir(os.path.dirname(target)):
        return False  # progress.json is written into an existing folder; savefile would create one
    return savefile.save_versioned(target, _normalise(data), savefile.PROGRESS_VERSION)


def apply_run(data: dict, stats: dict) -> dict:
    """Fold one finished run into the lifetime record and return ``data``. Pure, no I/O.

    ``stats`` is the dict from achievements.RunStats.to_dict(). Bests only ever go up.
    """
    data["runs_played"] = int(data.get("runs_played", 0)) + 1
    data["total_kills"] = int(data.get("total_kills", 0)) + int(stats.get("kills", 0))
    data["bosses_defeated"] = int(data.get("bosses_defeated", 0)) + int(stats.get("boss_kills", 0))
    data["best_wave"] = max(int(data.get("best_wave", 0)), int(stats.get("wave", 0)))
    data["best_score"] = max(int(data.get("best_score", 0)), int(stats.get("score", 0)))
    return data


def end_run(run, path=None) -> dict:
    """Merge a finished run into the saved record. Call once per run, when it ends.

    ``run`` is an achievements.RunStats that has had finish() called, or its to_dict() form.
    The record is read, updated and written once, so this costs one file write per run.
    """
    stats = run.to_dict() if hasattr(run, "to_dict") else dict(run)
    data = load(path)
    apply_run(data, stats)
    new_achievements = achievements.evaluate(stats, data)
    new_skins = skins.refresh_unlocks(data)
    saved = save(data, path)
    return {
        "saved": saved,
        "progress": data,
        "new_achievements": new_achievements,
        "new_skins": new_skins,
    }


# Names from the cross-wave contract. daily.py, hangar.py and hud.py import these.
PROGRESS_PATH = PROGRESS_FILE
# Contract spellings for load and save, so callers written against the cross-wave contract also work.
load_progress = load
save_progress = save
