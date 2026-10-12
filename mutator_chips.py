"""Title-screen toggle chips for the run mutators (see mutators.py).

The row is a caption line over one chip per mutator. A chip click flips that mutator and calls
``on_toggle(mutator_id)``; the owner decides what to save and then pushes the result back through
``set_selected``. The caption shows the combined score multiplier, or the description of the chip under
the mouse. Everything is drawn into the menu's batch and positioned by ``layout``.
"""

import pyglet
from pyglet import shapes

import mutators

_ON_BG = (255, 186, 84)
_ON_BG_HOVER = (255, 214, 140)
_OFF_BG = (14, 24, 40)
_OFF_BG_HOVER = (30, 46, 72)
_BORDER = (150, 185, 225)
_ON_TEXT = (28, 18, 6, 255)
_OFF_TEXT = (150, 168, 190, 235)
_CAPTION_RGBA = (166, 184, 202, 255)

_CHIP_W = 124   # before UI scale
_CHIP_H = 26
_CHIP_GAP = 8
_CHIP_FONT = 11
_CAPTION_FONT = 12


class _Chip:
    def __init__(self, batch, mutator: mutators.Mutator, font_name: str):
        self.mutator = mutator
        self.selected = False
        self.hovered = False
        self.x = 0.0
        self.y = 0.0
        self.w = float(_CHIP_W)
        self.h = float(_CHIP_H)
        self.border = shapes.Rectangle(0, 0, 1, 1, color=_BORDER, batch=batch)
        self.bg = shapes.Rectangle(0, 0, 1, 1, color=_OFF_BG, batch=batch)
        self.label = pyglet.text.Label(
            mutator.name,
            font_name=font_name,
            font_size=_CHIP_FONT,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            batch=batch,
            color=_OFF_TEXT,
        )

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h


class MutatorChipRow:
    """Caption plus one toggle chip per mutator, in the canonical mutators.MUTATORS order."""

    def __init__(self, batch, selected=(), on_toggle=None, font_name: str = "Rajdhani", style_label=None):
        self._on_toggle = on_toggle
        self._font_name = font_name
        self._style_label = style_label  # menu's guarded label-style helper (no-op without a GL context)
        self._chips = [_Chip(batch, m, font_name) for m in mutators.MUTATORS]
        self._caption = pyglet.text.Label(
            "",
            font_name=font_name,
            font_size=_CAPTION_FONT,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            color=_CAPTION_RGBA,
            batch=batch,
        )
        self._hover_id = ""
        self._scale = 1.0
        self.set_selected(selected)

    @property
    def selected_ids(self) -> tuple[str, ...]:
        return tuple(c.mutator.id for c in self._chips if c.selected)

    def set_selected(self, ids) -> None:
        """Show ``ids`` as on. Unknown ids are ignored."""
        chosen = set(mutators.normalize_selection(ids))
        for chip in self._chips:
            chip.selected = chip.mutator.id in chosen
        self._refresh()

    def layout(self, cx: float, top_y: float, scale: float) -> None:
        """Centre the row on cx. The caption's top edge sits at top_y; the chips hang below it."""
        self._scale = float(scale)
        s = self._scale
        chip_w = int(_CHIP_W * s)
        chip_h = int(_CHIP_H * s)
        gap = int(_CHIP_GAP * s)
        total_w = len(self._chips) * chip_w + (len(self._chips) - 1) * gap
        left = float(cx) - total_w / 2.0
        chips_top = float(top_y) - int(18 * s)
        for i, chip in enumerate(self._chips):
            chip.x = left + i * (chip_w + gap)
            chip.y = chips_top - chip_h
            chip.w = float(chip_w)
            chip.h = float(chip_h)
        self._caption.x = float(cx)
        self._caption.y = float(top_y) - int(9 * s)
        if self._style_label is not None:
            self._style_label(self._caption, self._font_name, max(10, int(_CAPTION_FONT * min(s, 1.25))))
        self._refresh()

    def on_mouse_motion(self, x: float, y: float) -> None:
        hover = ""
        for chip in self._chips:
            chip.hovered = chip.contains(x, y)
            if chip.hovered:
                hover = chip.mutator.id
        if hover != self._hover_id:
            self._hover_id = hover
            self._refresh()

    def on_mouse_press(self, x: float, y: float) -> bool:
        """Flip the chip under (x, y). Returns True when a chip was hit, so the click is not treated as a button."""
        for chip in self._chips:
            if chip.contains(x, y):
                chip.selected = not chip.selected
                self._refresh()
                if self._on_toggle is not None:
                    self._on_toggle(chip.mutator.id)
                return True
        return False

    def _caption_text(self) -> str:
        hovered = mutators.mutator_by_id(self._hover_id)
        if hovered is not None:
            return f"{hovered.name} (score {mutators.format_score_mult(hovered.score_mult)}): {hovered.description}"
        mult = mutators.combined_score_multiplier(self.selected_ids)
        return f"Run mutators, opt-in: score {mutators.format_score_mult(mult)}"

    def _refresh(self) -> None:
        self._caption.text = self._caption_text()
        s = self._scale
        font_size = max(9, int(round(_CHIP_FONT * min(s, 1.6))))
        for chip in self._chips:
            if chip.selected:
                bg = _ON_BG_HOVER if chip.hovered else _ON_BG
                text = _ON_TEXT
                border_alpha = 200
            else:
                bg = _OFF_BG_HOVER if chip.hovered else _OFF_BG
                text = _OFF_TEXT
                border_alpha = 120 if chip.hovered else 70
            chip.bg.x = chip.x
            chip.bg.y = chip.y
            chip.bg.width = chip.w
            chip.bg.height = chip.h
            chip.bg.color = bg
            chip.bg.opacity = 236 if chip.selected else 200
            chip.border.x = chip.x - 1
            chip.border.y = chip.y - 1
            chip.border.width = chip.w + 2
            chip.border.height = chip.h + 2
            chip.border.opacity = border_alpha
            chip.label.x = chip.x + chip.w / 2.0
            chip.label.y = chip.y + chip.h / 2.0
            if self._style_label is not None:
                self._style_label(chip.label, self._font_name, font_size)
            chip.label.color = text
