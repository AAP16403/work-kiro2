"""Daily challenge: one seeded run per local date, with one mutator and a best score per date.

Everything here is pure except settle_daily_run, which loads and saves progress.json through the
wave-1 store (progress.py). That module is imported inside the function, so this file loads without it.

Dates are local calendar dates. Callers and tests pass a date in explicitly. local_today() is the
only clock read, and nothing in the test suite calls it.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from dataclasses import dataclass

# Mixed into the seed hash so the daily seed is not just a plain hash of the date text.
SEED_SALT = "ploto-daily-v1"

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class DailyResult:
    """What one finished daily run did to that date's record."""

    date_iso: str
    run_score: int
    run_wave: int
    best_score: int              # today's best after this run
    best_wave: int               # wave reached by the run that set best_score
    previous_score: int | None   # the record before this run, or None on the day's first run
    changed: bool                # the stored record changed (progress.json needs a save)
    new_best: bool               # this run beat the record; a first run only counts when it scored above zero


def local_today() -> _dt.date:
    """Local calendar date. The only clock read in this module."""
    return _dt.date.today()


def normalise_date(date_iso: str) -> str:
    """Canonical YYYY-MM-DD form of date_iso. Raises ValueError for anything else."""
    text = str(date_iso)
    if not _ISO_DATE.fullmatch(text):
        raise ValueError(f"expected YYYY-MM-DD, got {date_iso!r}")
    return _dt.date.fromisoformat(text).isoformat()


def today_iso(today: _dt.date | None = None) -> str:
    """The date as YYYY-MM-DD. Pass ``today`` to use a fixed date; omit it to use the local date."""
    if today is None:
        today = local_today()
    return today.isoformat()


def daily_seed(date_iso: str) -> int:
    """Seed for the run on this date. hashlib keeps it the same in every process, unlike hash()."""
    key = f"{SEED_SALT}|{normalise_date(date_iso)}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")


def mutator_pool() -> tuple[str, ...]:
    """Every mutator id in mutators.py, sorted so the pick does not depend on dict order."""
    import mutators  # wave-1 module; imported lazily so this file loads without it

    return tuple(sorted(m.id for m in mutators.MUTATORS))


def daily_mutator(date_iso: str, pool: tuple[str, ...] | None = None) -> str:
    """The one mutator id for this date, chosen from the pool by the date's seed."""
    ids = tuple(pool) if pool is not None else mutator_pool()
    if not ids:
        raise ValueError("the daily mutator pool is empty")
    return ids[daily_seed(date_iso) % len(ids)]


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def best_for_date(progress: dict, date_iso: str) -> dict | None:
    """Stored record for the date as {"score", "wave"}, or None when the date has no record."""
    table = progress.get("daily")
    if not isinstance(table, dict):
        return None
    entry = table.get(normalise_date(date_iso))
    if not isinstance(entry, dict):
        return None
    score = _as_int(entry.get("score"))
    if score is None:
        return None
    wave = _as_int(entry.get("wave"))
    return {"score": score, "wave": 0 if wave is None else wave}


def record_daily(progress: dict, date_iso: str, score: int, wave: int) -> bool:
    """Store a daily run as the date's record when its score is strictly higher than the stored one.

    The first run of a date always stores its result, so the date has a record even at zero.
    Ties and lower scores leave the record alone. Returns True when the stored record changed.
    progress is updated in place; the caller saves it.
    """
    key = normalise_date(date_iso)
    table = progress.get("daily")
    if not isinstance(table, dict):
        table = {}
        progress["daily"] = table
    current = best_for_date(progress, key)
    score = int(score)
    if current is not None and score <= current["score"]:
        return False
    table[key] = {"score": score, "wave": int(wave)}
    return True


def record_run(progress: dict, date_iso: str, score: int, wave: int) -> DailyResult:
    """Apply one finished daily run to progress in memory. Does no file I/O."""
    key = normalise_date(date_iso)
    previous = best_for_date(progress, key)
    changed = record_daily(progress, key, score, wave)
    best = best_for_date(progress, key)
    if best is None:  # record_daily always leaves a record behind
        raise RuntimeError("daily record missing after update")
    return DailyResult(
        date_iso=key,
        run_score=int(score),
        run_wave=int(wave),
        best_score=best["score"],
        best_wave=best["wave"],
        previous_score=None if previous is None else previous["score"],
        changed=changed,
        new_best=changed and int(score) > 0,
    )


def settle_daily_run(date_iso: str, score: int, wave: int, path: str | None = None) -> DailyResult:
    """Record a finished daily run in progress.json. Saves only when the record changed.

    path=None uses the wave-1 store's default location. Tests pass a temp file.
    """
    import progress as store  # wave-1 store; imported here so this file loads without it

    data = store.load_progress(path)
    result = record_run(data, date_iso, score, wave)
    if result.changed:
        store.save_progress(data, path)
    return result
