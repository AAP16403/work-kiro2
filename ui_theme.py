"""Shared UI theme: colour tokens, type scale, spacing and panel/chip helpers.

Sizes are base values for the 980x620 reference window. font_size() and space()
multiply them by the factor from ui_scale(), the same responsive scale the menus
already use, so a screen that adopts the theme keeps its proportions.

draw_panel() and draw_chip() create pyglet shapes in a batch and return them as a
list. Keep the list and call delete() on each item to remove the widget.
place_panel() moves a panel built by draw_panel() without rebuilding it.
"""

from __future__ import annotations

import pyglet
from pyglet import shapes

import config

# Fonts. fonts.register_ui_fonts() must have run before a label uses them.
FONT_HEAD = "Orbitron"
FONT_BODY = "Rajdhani"
FONT_META = "Rajdhani"

# Colour tokens (RGB).
BACKGROUND = (9, 16, 26)
PANEL = (10, 20, 34)
ACCENT = (155, 205, 255)
TEXT = (224, 236, 255)
MUTED = (166, 184, 202)
DANGER = (200, 70, 90)
SUCCESS = (45, 170, 125)

TOKENS = {
    "background": BACKGROUND,
    "panel": PANEL,
    "accent": ACCENT,
    "text": TEXT,
    "muted": MUTED,
    "danger": DANGER,
    "success": SUCCESS,
}

# Type roles: role -> (base px at 980x620, smallest px after scaling, font family).
TYPE_SCALE: dict[str, tuple[int, int, str]] = {
    "display": (38, 22, FONT_HEAD),  # title screen wordmark
    "heading": (30, 18, FONT_HEAD),  # screen header title
    "section": (12, 9, FONT_HEAD),   # small section labels
    "subhead": (15, 11, FONT_BODY),  # subtitles under a header
    "button": (18, 12, FONT_BODY),   # button labels
    "note": (13, 10, FONT_BODY),     # secondary notes beside a control
    "tagline": (13, 10, FONT_META),  # title screen tagline
    "eyebrow": (11, 9, FONT_META),   # small line above a header
    "caption": (12, 9, FONT_META),   # key hints and tips
}

# Spacing steps in base px (multiply by the UI scale).
SPACING: dict[str, int] = {"xs": 4, "sm": 8, "md": 14, "lg": 22, "xl": 34}


def ui_scale(width: int, height: int) -> float:
    """Responsive UI scale factor based on window size."""
    base_w, base_h = 980.0, 620.0
    s = min(max(1.0, float(width)) / base_w, max(1.0, float(height)) / base_h)
    return max(0.85, min(1.85, s))


def reduce_motion() -> bool:
    """True when config.REDUCE_MOTION asks the UI to stop ambient animation."""
    return bool(getattr(config, "REDUCE_MOTION", False))


def mix_rgb(a: tuple, b: tuple, t: float) -> tuple[int, int, int]:
    """Linear blend of two RGB tuples, t clamped to 0..1."""
    t = max(0.0, min(1.0, float(t)))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]


def font_name(role: str) -> str:
    """Font family for a type role."""
    return TYPE_SCALE[role][2]


def font_size(role: str, scale: float) -> int:
    """Pixel size for a type role at the given UI scale."""
    base, smallest, _ = TYPE_SCALE[role]
    return max(smallest, int(base * scale))


def space(step: str, scale: float = 1.0) -> float:
    """Spacing step (xs, sm, md, lg, xl) in px at the given UI scale."""
    return SPACING[step] * scale


def text_width(text: str, role: str, scale: float = 1.0) -> float:
    """Rendered width in px of text set in a type role. Creates and frees a temporary label."""
    label = pyglet.text.Label(text, font_name=font_name(role), font_size=font_size(role, scale))
    width = float(label.content_width)
    label.delete()
    return width


def place_panel(parts: list, x: float, y: float, w: float, h: float, *, border_pad: float = 3.0) -> None:
    """Move and size a panel returned by draw_panel(). (x, y) is the bottom-left of the body."""
    edge, body, shine = parts
    pad = float(border_pad)
    edge.x = x - pad
    edge.y = y - pad
    edge.width = w + 2 * pad
    edge.height = h + 2 * pad
    body.x = x
    body.y = y
    body.width = w
    body.height = h
    strip = max(4.0, min(24.0, h * 0.08))
    shine.x = x + 4
    shine.y = y + h - strip - 2
    shine.width = max(1.0, w - 8)
    shine.height = strip


def draw_panel(
    batch: pyglet.graphics.Batch,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    alpha: float = 1.0,
    border_pad: float = 3.0,
    fill: tuple = PANEL,
    edge: tuple = ACCENT,
    group: pyglet.graphics.Group | None = None,
) -> list:
    """Backing card: a faint edge, a filled body and a soft top shine.

    Returns [edge, body, shine]. Use place_panel() to move it, and delete() on each
    item to remove it. The alpha argument scales all three layers.
    """
    a = max(0.0, min(1.0, float(alpha)))
    parts = [
        shapes.Rectangle(0, 0, 1, 1, color=edge, batch=batch, group=group),
        shapes.Rectangle(0, 0, 1, 1, color=fill, batch=batch, group=group),
        shapes.Rectangle(0, 0, 1, 1, color=(255, 255, 255), batch=batch, group=group),
    ]
    parts[0].opacity = int(48 * a)
    parts[1].opacity = int(196 * a)
    parts[2].opacity = int(16 * a)
    place_panel(parts, x, y, w, h, border_pad=border_pad)
    return parts


def chip_height(scale: float = 1.0) -> float:
    """Height in px of a chip at the given UI scale."""
    return max(20.0, 26.0 * scale)


def chip_width(text: str, role: str = "caption", scale: float = 1.0) -> float:
    """Width in px of a chip that holds text. Use it to lay out a row before drawing."""
    return text_width(text, role, scale) + 2.0 * space("md", scale) * 0.7


def draw_chip(
    batch: pyglet.graphics.Batch,
    x: float,
    y: float,
    text: str,
    *,
    role: str = "caption",
    scale: float = 1.0,
    active: bool = False,
    group: pyglet.graphics.Group | None = None,
) -> list:
    """Keycap or toggle tag with a centred label. (x, y) is the bottom-left corner.

    Returns [edge, body, label]; the chip width is parts[1].width. An active chip takes
    the accent fill (for a toggle that is on), an idle chip the panel fill.
    """
    w = chip_width(text, role, scale)
    h = chip_height(scale)
    if active:
        edge_col, fill_col, edge_op, fill_op, text_col = ACCENT, ACCENT, 170, 236, BACKGROUND
    else:
        edge_col, fill_col, edge_op, fill_op, text_col = ACCENT, PANEL, 70, 214, TEXT
    edge_rect = shapes.Rectangle(x - 1, y - 1, w + 2, h + 2, color=edge_col, batch=batch, group=group)
    edge_rect.opacity = edge_op
    body = shapes.Rectangle(x, y, w, h, color=fill_col, batch=batch, group=group)
    body.opacity = fill_op
    label = pyglet.text.Label(
        text,
        font_name=font_name(role),
        font_size=font_size(role, scale),
        x=x + w / 2.0,
        y=y + h / 2.0,
        anchor_x="center",
        anchor_y="center",
        color=(*text_col, 255),
        batch=batch,
        group=group,
    )
    return [edge_rect, body, label]
