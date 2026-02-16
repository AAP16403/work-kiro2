"""UI font registration for local runs and packaged builds."""

from __future__ import annotations

import os
import sys

import pyglet


_UI_FONT_FILES = (
    "Orbitron-Variable.ttf",
    "Rajdhani-Regular.ttf",
    "Rajdhani-SemiBold.ttf",
)
_loaded = False


def resource_path(*parts: str) -> str:
    """Resolve paths for both source and PyInstaller (_MEIPASS) runtime."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def register_ui_fonts() -> None:
    """Register bundled TTF files with pyglet font manager."""
    global _loaded
    if _loaded:
        return
    for filename in _UI_FONT_FILES:
        path = resource_path("assets", "fonts", filename)
        if os.path.exists(path):
            pyglet.font.add_file(path)
    _loaded = True
