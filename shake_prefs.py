"""Persisted Reduced Shake preference.

Stored in user_settings.json beside the audio volumes (same file, same folder as audio.py).
Writes read the file first and keep every other key, so audio saves never drop this flag and
vice versa. Every read and write is guarded: a broken settings file must never reach the game loop.
"""

import json
import os

import audio as _audio

REDUCED_SHAKE_KEY = "reduced_shake"


def load_reduced_shake(default: bool = False) -> bool:
    """Return the saved Reduced Shake flag, or ``default`` when absent or unreadable. Never raises."""
    try:
        with open(_audio._SETTINGS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get(REDUCED_SHAKE_KEY), bool):
            return data[REDUCED_SHAKE_KEY]
    except Exception:
        pass
    return bool(default)


def save_reduced_shake(enabled: bool) -> None:
    """Write the Reduced Shake flag to user_settings.json, keeping other keys. Never raises."""
    path = _audio._SETTINGS_PATH
    tmp = path + ".tmp"
    try:
        data = {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
            if isinstance(existing, dict):
                data = existing
        except Exception:
            data = {}
        data[REDUCED_SHAKE_KEY] = bool(enabled)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
