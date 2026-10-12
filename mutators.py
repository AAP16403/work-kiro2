"""Mutators: fixed rule changes the player can switch on from the title screen.

Each mutator is a set of multipliers (1.0 means no change). A run applies the product of the
multipliers of the ids selected when the run starts. With nothing selected the run gets the
identity Mods(), so a default run plays exactly as it did before mutators existed.

Public API:

    MUTATORS             dict id -> Mutator, five entries.
    MUTATOR_ORDER        tuple of ids in display order.
    Mods                 the combined multipliers a run applies (see the field comments).
    combined(ids) -> Mods
        Product of the multipliers for ids. An empty tuple gives Mods(). Unknown ids raise KeyError.
    normalise_ids(ids) -> tuple[str, ...]
        Known ids only, de-duplicated, in MUTATOR_ORDER. Anything else is dropped.
    load_selected_ids(path=None) -> tuple[str, ...]
        The saved selection from user_settings.json. Never raises; missing or bad data gives ().
    save_selected_ids(ids, path=None) -> bool
        Writes the selection and keeps every other key in the file. Never raises.
    describe(mods) -> list[str]
        One readable entry per multiplier that is not 1.0, such as "speed x1.25".
    summary_line(ids) -> str
        The line the Game Over screen shows: the names and the combined effect.

``path=None`` means the audio settings file (audio._SETTINGS_PATH), read at call time, so tests can
point it at a temp file. Pure data and small file I/O: it loads without a window.
"""

import json
import os
from dataclasses import dataclass

SETTINGS_KEY = "mutators"

_FIELDS = ("player_damage", "player_speed", "player_fire_rate", "enemy_hp", "enemy_speed", "enemy_fire_rate")
_LABELS = (
    ("player_damage", "damage"),
    ("player_speed", "speed"),
    ("player_fire_rate", "fire rate"),
    ("enemy_hp", "enemy HP"),
    ("enemy_speed", "enemy speed"),
    ("enemy_fire_rate", "enemy fire rate"),
)


@dataclass(frozen=True)
class Mods:
    """Combined multipliers for one run. 1.0 means no change."""

    player_damage: float = 1.0      # damage per shot
    player_speed: float = 1.0       # movement speed
    player_fire_rate: float = 1.0   # shots per second (a higher value fires faster)
    enemy_hp: float = 1.0           # HP of enemies spawned by a wave
    enemy_speed: float = 1.0        # movement speed of enemies spawned by a wave
    enemy_fire_rate: float = 1.0    # attack frequency of enemies spawned by a wave (a higher value attacks more often)


@dataclass(frozen=True)
class Mutator:
    """One rule. ``name`` and ``description`` are shown to the player."""

    id: str
    name: str
    description: str
    player_damage: float = 1.0
    player_speed: float = 1.0
    player_fire_rate: float = 1.0
    enemy_hp: float = 1.0
    enemy_speed: float = 1.0
    enemy_fire_rate: float = 1.0


MUTATORS: dict[str, Mutator] = {m.id: m for m in (
    Mutator("bullet_hell", "Bullet Hell", "Enemies attack 1.5x as often.", enemy_fire_rate=1.5),
    Mutator("drift", "Drift", "You move 1.25x faster.", player_speed=1.25),
    Mutator("frenzy", "Frenzy", "You fire 1.3x as fast and enemies move 1.2x faster.",
            player_fire_rate=1.3, enemy_speed=1.2),
    Mutator("glass_cannon", "Glass Cannon", "Your shots hit 1.5x harder.", player_damage=1.5),
    Mutator("iron_man", "Iron Man", "Enemies have 1.5x HP.", enemy_hp=1.5),
)}

MUTATOR_ORDER: tuple = tuple(sorted(MUTATORS))


def combined(ids) -> Mods:
    """Multiply the multipliers of every id in ``ids``. Raises KeyError for an unknown id."""
    totals = {field: 1.0 for field in _FIELDS}
    for mutator_id in ids:
        mutator = MUTATORS[mutator_id]
        for field in _FIELDS:
            totals[field] *= getattr(mutator, field)
    return Mods(**totals)


def normalise_ids(ids) -> tuple:
    """Known ids only, unique, in MUTATOR_ORDER. A string or a non-iterable gives ()."""
    if isinstance(ids, str):
        return ()
    try:
        wanted = {item for item in ids if isinstance(item, str)}
    except TypeError:
        return ()
    return tuple(mid for mid in MUTATOR_ORDER if mid in wanted)


def _settings_path(path):
    if path is not None:
        return path
    import audio as _audio  # imported lazily so the module itself does no I/O at import time
    return _audio._SETTINGS_PATH


def load_selected_ids(path=None) -> tuple:
    """The saved mutator selection. Never raises: a missing or unreadable file gives ()."""
    try:
        with open(_settings_path(path), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return normalise_ids(data.get(SETTINGS_KEY, ()))
    except Exception:
        pass
    return ()


def save_selected_ids(ids, path=None) -> bool:
    """Write the selection to user_settings.json, keeping every other key. Returns False on failure."""
    target = _settings_path(path)
    tmp = target + ".tmp"
    try:
        data = {}
        try:
            with open(target, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
            if isinstance(existing, dict):
                data = existing
        except Exception:
            data = {}
        data[SETTINGS_KEY] = list(normalise_ids(ids))
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, target)
        return True
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        return False


def describe(mods: Mods) -> list:
    """One entry per multiplier that differs from 1.0, for example ``"speed x1.25"``."""
    lines = []
    for field, label in _LABELS:
        value = float(getattr(mods, field))
        if abs(value - 1.0) > 1e-9:
            lines.append(f"{label} x{value:.2f}")
    return lines


def summary_line(ids) -> str:
    """The Game Over line: the selected names and the combined effect of the selection."""
    chosen = normalise_ids(ids)
    if not chosen:
        return "Mutators: none"
    names = ", ".join(MUTATORS[mid].name for mid in chosen)
    effects = describe(combined(chosen))
    if not effects:
        return f"Mutators: {names}"
    return f"Mutators: {names}  |  " + ", ".join(effects)
