"""Apply the selected skin to a run: the player ship, player shots and trails, and the dash afterimage.

The selection is read once per run start from progress (wave-1 progress.py and skins.py). When
those modules are missing, or the save cannot be read, the run uses the default skin, which is
the legacy in-run look. Enemy bullets are never recoloured here.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_SKIN_ID = "default"

# Palette keys every skin provides. Each one maps to one part of the in-run ship or its shots:
#   body    hull                      accent  cockpit
#   eye     gun core                  glow    aura behind the ship
#   trail   thrusters, shot trails    bullet  plain player shot
PALETTE_KEYS = ("body", "accent", "eye", "glow", "trail", "bullet")

# The in-run look from before skins existed. The default skin reproduces this exactly.
LEGACY_PALETTE = {
    "body": (132, 224, 255),
    "accent": (10, 200, 255),
    "eye": (255, 255, 255),
    "glow": (60, 140, 220),
    "trail": (130, 210, 255),
    "bullet": (255, 245, 190),
}
LEGACY_GLOW2 = (80, 120, 220)  # the outer halo behind the ship in the legacy look


def aura_outer(palette=None) -> tuple:
    """Outer halo colour: the legacy halo shifted by the palette's change to the glow.

    The default palette gives exactly LEGACY_GLOW2, and a skin's halo keeps the same two-tone relation to its glow.
    """
    glow = complete_palette(palette)["glow"]
    base = LEGACY_PALETTE["glow"]
    return tuple(max(0, min(255, LEGACY_GLOW2[i] + glow[i] - base[i])) for i in range(3))


def complete_palette(palette=None) -> dict:
    """Return a full palette of RGB tuples; missing or None keys fall back to the legacy look."""
    src = palette or {}
    out = {}
    for key in PALETTE_KEYS:
        value = src.get(key)
        if value is None:
            value = LEGACY_PALETTE[key]
        out[key] = (int(value[0]), int(value[1]), int(value[2]))
    return out


@dataclass(frozen=True)
class RunSkin:
    """The skin a run uses, resolved at run start."""

    skin_id: str
    palette: dict

    @property
    def is_default(self) -> bool:
        return self.skin_id == DEFAULT_SKIN_ID

    @property
    def shot_palette(self) -> dict | None:
        """Palette for player shots and their trails, or None to keep the per-weapon colours."""
        return None if self.is_default else self.palette

    @property
    def dash_color(self) -> tuple | None:
        """Colour for the dash afterimage, or None to keep the legacy colour."""
        return None if self.is_default else self.palette["trail"]


def default_run_skin() -> RunSkin:
    return RunSkin(DEFAULT_SKIN_ID, complete_palette(LEGACY_PALETTE))


def read_run_skin(progress=None) -> RunSkin:
    """Resolve the selected skin for a run start.

    ``progress`` is a progress dict; when omitted it is loaded with progress.load_progress().
    A missing wave-1 module or an unreadable selection gives the default skin, so a bad save
    never blocks a run.
    """
    try:
        if progress is None:
            from progress import load_progress

            progress = load_progress()
        from skins import selected

        skin = selected(progress)
        return RunSkin(str(skin.id), complete_palette(skin.palette))
    except Exception:
        # ImportError (wave-1 module missing) or a bad save: the run keeps the legacy look.
        return default_run_skin()
