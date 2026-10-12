"""Apply the selected skin to a run: the player character, player shots and trails, and the dash afterimage.

This is the one skin path. read_run_skin() resolves the selection once per run start, and
Visuals.apply_skin() hands the result to the renderers. The selection comes from wave-1 progress.py
(load) and skins.py (selected). When either module is missing or the save cannot be read, the run
uses the default skin. Enemy shots are never recoloured here.

The default skin is wave 1's look exactly: its palette is player_art.DEFAULT_PALETTE. The legacy
ship (config.USE_PLAYER_ART off) keeps its pre-skin colours (LEGACY_PALETTE) for the default skin.
"""

from __future__ import annotations

from dataclasses import dataclass

from player_art import DEFAULT_PALETTE

# Matches skins.DEFAULT_SKIN_ID. The catalogue's classic palette is DEFAULT_PALETTE, so the Hangar card
# and the in-run look agree.
DEFAULT_SKIN_ID = "classic"

# Palette keys every skin provides: the keys of player_art.DEFAULT_PALETTE.
PALETTE_KEYS = tuple(DEFAULT_PALETTE)

# The legacy ship's colours from before skins existed. Only the legacy ship reads them, and only for the default skin.
LEGACY_PALETTE = {
    "body": (132, 224, 255),
    "accent": (10, 200, 255),
    "eye": (255, 255, 255),
    "glow": (60, 140, 220),
    "trail": (130, 210, 255),
    "bullet": (255, 245, 190),
}
LEGACY_GLOW2 = (80, 120, 220)  # the outer halo behind the legacy ship


def complete_palette(palette=None) -> dict:
    """Return a full palette of RGB tuples. Missing or None keys fall back to DEFAULT_PALETTE."""
    src = palette or {}
    out = {}
    for key in PALETTE_KEYS:
        value = src.get(key)
        if value is None:
            value = DEFAULT_PALETTE[key]
        out[key] = (int(value[0]), int(value[1]), int(value[2]))
    return out


def aura_outer(palette=None) -> tuple:
    """Outer halo colour: LEGACY_GLOW2 shifted by how far the palette's glow sits from the legacy glow.

    The legacy glow gives exactly LEGACY_GLOW2, and a skin's halo keeps the same two-tone relation to its glow.
    """
    glow = complete_palette(palette)["glow"]
    base = LEGACY_PALETTE["glow"]
    return tuple(max(0, min(255, LEGACY_GLOW2[i] + glow[i] - base[i])) for i in range(3))


@dataclass(frozen=True)
class RunSkin:
    """The skin a run uses, resolved at run start. ``palette`` always holds every PALETTE_KEYS entry."""

    skin_id: str
    palette: dict

    @property
    def is_default(self) -> bool:
        return self.skin_id == DEFAULT_SKIN_ID

    @property
    def ship_palette(self) -> dict:
        """Colours for the legacy ship. The default skin keeps the pre-skin ship exactly."""
        return complete_palette(LEGACY_PALETTE) if self.is_default else dict(self.palette)

    @property
    def shot_palette(self) -> dict | None:
        """Palette for player shots, or None to keep the per-weapon colours."""
        return None if self.is_default else dict(self.palette)

    @property
    def dash_color(self) -> tuple | None:
        """Colour for the dash afterimage, or None to keep the legacy colour."""
        return None if self.is_default else self.palette["trail"]


def default_run_skin() -> RunSkin:
    return RunSkin(DEFAULT_SKIN_ID, complete_palette(DEFAULT_PALETTE))


def read_run_skin(progress=None) -> RunSkin:
    """Resolve the selected skin for a run start.

    ``progress`` is a progress dict; when omitted it is loaded with progress.load(), which reads the
    save file and never raises. A missing wave-1 module or an unreadable selection gives the default
    skin, so a bad save never blocks a run.
    """
    try:
        if progress is None:
            import progress as meta_progress

            progress = meta_progress.load()
        from skins import selected

        skin = selected(progress)
    except Exception:
        # ImportError (wave-1 module missing) or a bad save: the run keeps the default look.
        return default_run_skin()
    if str(skin.id) == DEFAULT_SKIN_ID:
        return default_run_skin()
    return RunSkin(str(skin.id), complete_palette(skin.palette))
