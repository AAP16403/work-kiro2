"""Persisted Screen Shake level (Full / Reduced / Off).

Stored in user_settings.json beside the audio volumes (same file, same folder as audio.py).
Writes read the file first and keep every other key, so audio saves never drop this setting and
vice versa. Every read and write is guarded: a broken settings file must never reach the game loop.
Reads and writes go through savefile (versioned, atomic, corrupt files quarantined).

The canonical key is SHAKE_LEVEL_KEY ("shake_level"). The older boolean REDUCED_SHAKE_KEY is still
read when the level key is missing (true maps to Reduced, false to Full), and every save writes it
back as a derived flag (level is not Full) so older readers keep working.
"""

import audio as _audio
import config
from savefile import load_settings, update_settings

SHAKE_LEVEL_KEY = "shake_level"
REDUCED_SHAKE_KEY = "reduced_shake"


def normalize_shake_level(level, default: str = "full") -> str:
    """Return ``level`` when it is a known shake level, otherwise ``default``."""
    if isinstance(level, str) and level in config.SHAKE_LEVELS:
        return level
    return default if default in config.SHAKE_LEVELS else "full"


def shake_scale_for_level(level) -> float:
    """SHAKE_SCALE for a level: Full 1.0, Reduced 0.5, Off 0.0 (from config)."""
    lvl = normalize_shake_level(level)
    if lvl == "reduced":
        return float(config.SHAKE_REDUCED_SCALE)
    if lvl == "off":
        return float(config.SHAKE_OFF_SCALE)
    return float(config.SHAKE_FULL_SCALE)


def shake_level_is_reduced(level) -> bool:
    """Legacy boolean view of a level: True when shake is reduced or off."""
    return normalize_shake_level(level) != "full"


def load_shake_level(default: str = "full") -> str:
    """Return the saved shake level, or ``default`` when absent or unreadable. Never raises."""
    try:
        data = load_settings(_audio._SETTINGS_PATH)
        level = data.get(SHAKE_LEVEL_KEY)
        if isinstance(level, str) and level in config.SHAKE_LEVELS:
            return level
        legacy = data.get(REDUCED_SHAKE_KEY)
        if isinstance(legacy, bool):
            return "reduced" if legacy else "full"
    except Exception:
        pass
    return normalize_shake_level(default)


def save_shake_level(level) -> None:
    """Write the shake level and its derived reduced flag to user_settings.json. Never raises."""
    lvl = normalize_shake_level(level)
    try:
        update_settings(_audio._SETTINGS_PATH, {
            SHAKE_LEVEL_KEY: lvl,
            REDUCED_SHAKE_KEY: shake_level_is_reduced(lvl),
        })
    except Exception:
        pass


def load_reduced_shake(default: bool = False) -> bool:
    """Legacy boolean API: True when the saved level is Reduced or Off. Returns ``default`` when unreadable."""
    return shake_level_is_reduced(load_shake_level("reduced" if default else "full"))


def save_reduced_shake(enabled: bool) -> None:
    """Legacy boolean API: saves Reduced (True) or Full (False). Use save_shake_level for Off."""
    save_shake_level("reduced" if enabled else "full")
