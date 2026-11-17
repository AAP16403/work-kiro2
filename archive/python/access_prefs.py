"""Persisted Accessibility options: reduced motion, colour-blind enemy palette and high-contrast HUD.

Stored in user_settings.json beside the audio volumes and the Screen Shake level (same file, same
folder as audio.py). Writes read the file first and keep every other key, so each save path leaves
the others alone. Every read and write is guarded: a broken settings file never reaches the game loop.

apply() copies saved values into the runtime flags in config (REDUCE_MOTION, COLORBLIND_PALETTE,
HIGH_CONTRAST_HUD). The colour-blind palette is applied by swapping the entries of config.ENEMY_COLORS
in place, so every module that imported that dict sees the change without being edited.
"""

import audio as _audio
import config
import savefile

REDUCED_MOTION_KEY = "reduced_motion"
COLORBLIND_KEY = "colorblind_palette"
HIGH_CONTRAST_KEY = "high_contrast_hud"
ACCESS_KEYS = (REDUCED_MOTION_KEY, COLORBLIND_KEY, HIGH_CONTRAST_KEY)

# Enemy colours as they were before the colour-blind palette existed. Captured at import so that
# turning the palette off restores exactly these values.
_STANDARD_ENEMY_COLORS = dict(config.ENEMY_COLORS)


def _coerce_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    return default


def _config_defaults() -> dict:
    return {
        REDUCED_MOTION_KEY: bool(getattr(config, "REDUCE_MOTION", False)),
        COLORBLIND_KEY: bool(getattr(config, "COLORBLIND_PALETTE", False)),
        HIGH_CONTRAST_KEY: bool(getattr(config, "HIGH_CONTRAST_HUD", False)),
    }


def coerce_access_value(key: str, value) -> bool:
    """Return ``value`` as a bool for an Accessibility key, or the config default when it is not one."""
    return _coerce_bool(value, _config_defaults().get(key, False))


def load_access_settings() -> dict:
    """Return {key: bool} for the three Accessibility options. Missing or unreadable data reads as the config defaults.

    Reads through savefile.load_settings, so a corrupt user_settings.json is quarantined and never half-used.
    """
    values = _config_defaults()
    try:
        data = savefile.load_settings(_audio._SETTINGS_PATH)
        for key in ACCESS_KEYS:
            values[key] = _coerce_bool(data.get(key), values[key])
    except Exception:
        pass
    return values


def save_access_settings(values: dict) -> None:
    """Write the Accessibility keys present in ``values`` to user_settings.json, keeping every other key. Never raises.

    The write goes through savefile.update_settings, the same versioned, atomic helper audio and shake_prefs use,
    so a corrupt file is quarantined rather than overwritten and the write is all-or-nothing.
    """
    changes = {key: coerce_access_value(key, values[key]) for key in ACCESS_KEYS if key in values}
    if not changes:
        return
    try:
        savefile.update_settings(_audio._SETTINGS_PATH, changes)
    except Exception:
        pass


def set_colorblind_palette(on: bool) -> None:
    """Make config.ENEMY_COLORS hold the colour-blind palette (on) or the standard one (off), in place."""
    source = config.COLORBLIND_ENEMY_COLORS if on else _STANDARD_ENEMY_COLORS
    config.ENEMY_COLORS.clear()
    config.ENEMY_COLORS.update(source)


def apply(values: dict) -> dict:
    """Copy the Accessibility keys named in ``values`` into the runtime config. Returns the resulting {key: bool}.

    Keys that are not named keep their current runtime value.
    """
    if REDUCED_MOTION_KEY in values:
        config.REDUCE_MOTION = coerce_access_value(REDUCED_MOTION_KEY, values[REDUCED_MOTION_KEY])
    if COLORBLIND_KEY in values:
        config.COLORBLIND_PALETTE = coerce_access_value(COLORBLIND_KEY, values[COLORBLIND_KEY])
        set_colorblind_palette(config.COLORBLIND_PALETTE)
    if HIGH_CONTRAST_KEY in values:
        config.HIGH_CONTRAST_HUD = coerce_access_value(HIGH_CONTRAST_KEY, values[HIGH_CONTRAST_KEY])
    return current()


def current() -> dict:
    """The runtime Accessibility flags as {key: bool}."""
    return {
        REDUCED_MOTION_KEY: bool(config.REDUCE_MOTION),
        COLORBLIND_KEY: bool(config.COLORBLIND_PALETTE),
        HIGH_CONTRAST_KEY: bool(config.HIGH_CONTRAST_HUD),
    }
