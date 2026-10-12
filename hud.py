"""HUD (Heads-Up Display) – health, shield, wave, status, score, banners and boss bar.

Panels and chips are drawn with ui_theme helpers (see hud_widgets.py). The in-run additions are
the radial Ultra gauge, the weapon and skin chips, and the achievement toast queue.
"""

import pyglet
from pyglet import shapes

import config
from config import SHIELD_MAX
from menu import UI_FONT_HEAD, UI_FONT_BODY, UI_FONT_META
from hud_widgets import (
    Chip,
    RadialGauge,
    ToastQueue,
    ToastView,
    WeaponChip,
    draw_panel,
    fit_text as _fit_text,
    set_text as _set_text,
    token,
    weapon_swatch,
)


CONTRAST_LIFT = 0.45      # high contrast: each HUD text channel moves this far toward white
CONTRAST_PLATE_COLOR = (6, 10, 18)
CONTRAST_PLATE_ALPHA = 215  # opacity of the dark plate behind each HUD number in high contrast
CONTRAST_PLATE_PAD = 4      # reference pixels between a number and its plate's edge

BANNER_IN_S = 0.25        # ease-out slide/scale-in
BANNER_OUT_S = 0.45       # fade-out at the end of a banner
BOSS_LAG_HOLD_S = 0.10    # damage trail waits this long before it starts shrinking
BOSS_LAG_SHRINK_S = 0.40  # then shrinks toward the real HP (about 0.5 s in total)
STATUS_SEP = "   |   "    # between status segments
STATUS_CACHE_MAX = 256    # fitted status strings kept before the cache is reset
PANEL_SHADOW_ALPHA = 78
PANEL_FILL_ALPHA = 216
PANEL_EDGE_ALPHA = 228
TOAST_KICKER = "ACHIEVEMENT UNLOCKED"
DEFAULT_SKIN_NAME = "Default"


def _ui_scale(width: int, height: int) -> float:
    """1.0 at the 980x620 reference size, growing to 1.35 on fullscreen 1080p."""
    return max(1.0, min(1.35, min(width / 980.0, height / 620.0)))


def _set_size(label, size: int) -> None:
    if int(label.font_size) != size:
        label.font_size = size


def _spans_overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    return a0 < b1 and b0 < a1


def _reduce_motion() -> bool:
    return bool(getattr(config, "REDUCE_MOTION", False))


def current_skin_name(progress=None) -> str:
    """Name of the selected skin, from `progress` or from progress.json when none is given.

    Falls back to DEFAULT_SKIN_NAME while the progress or skins modules are missing, and never
    raises, so a bad save file cannot stop a run from starting.
    """
    try:
        import skins
        import progress as progress_store
    except ImportError:
        return DEFAULT_SKIN_NAME
    try:
        data = progress if progress is not None else progress_store.load_progress()
        return str(skins.selected(data).name) or DEFAULT_SKIN_NAME
    except (AttributeError, KeyError, TypeError, ValueError):
        return DEFAULT_SKIN_NAME


def achievement_name(achievement_id) -> str:
    """Display name for an achievement id, or the id itself while achievements.py is missing."""
    try:
        import achievements
    except ImportError:
        return str(achievement_id)
    for ach in getattr(achievements, "ACHIEVEMENTS", []):
        if getattr(ach, "id", None) == achievement_id:
            return str(getattr(ach, "name", achievement_id))
    return str(achievement_id)


class HUD:
    """In-game overlay: HP/shield/boost, wave chip, status bar, score, Ultra gauge, weapon and
    skin chips, achievement toasts, banners and boss bar."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self._s = 1.0
        self._bar_w = 240
        self._scaled_labels = []  # (label, reference font size) pairs resized in layout()
        self._frames = {}         # panel key -> shapes drawn for it (rebuilt in layout)
        self._meta_src = ""
        self._meta_max_w = 200.0
        self._status_max_w = 540.0  # pixel budget for the status line; set in layout()
        self._status_cache = {}     # (segments, width) -> fitted status text
        self._pulse_t = 0.0         # clock for the Ultra gauge's full-charge pulse

        text_color = token("TEXT")
        muted = token("MUTED")
        accent = token("ACCENT")

        self.batch = pyglet.graphics.Batch()
        # Panel backgrounds live in their own batch, drawn first, so bars, chips and text sit on top.
        self._frame_batch = pyglet.graphics.Batch()
        # Order inside self.batch: panels (order 0), number plates (1), text (2). Labels default to the text group.
        self._plate_group = pyglet.graphics.Group(order=1)
        self._text_group = pyglet.graphics.Group(order=2)
        self._contrast = bool(getattr(config, "HIGH_CONTRAST_HUD", False))
        self._label_base = {}  # id(label) -> (label, base RGBA), so high contrast can be toggled at any time

        # ── Health / Shield / Boost bars (bottom-left panel; panel shapes come from layout) ──
        self.hp_bar_bg = shapes.Rectangle(0, 0, 1, 1, color=(42, 45, 55), batch=self.batch)
        self.hp_bar = shapes.Rectangle(0, 0, 1, 1, color=(120, 210, 120), batch=self.batch)
        self.shield_bar_bg = shapes.Rectangle(0, 0, 1, 1, color=(36, 44, 58), batch=self.batch)
        self.shield_bar = shapes.Rectangle(0, 0, 1, 1, color=(84, 176, 232), batch=self.batch)
        self.boost_bar_bg = shapes.Rectangle(0, 0, 1, 1, color=(48, 34, 20), batch=self.batch)
        self.boost_bar = shapes.Rectangle(0, 0, 1, 1, color=(255, 145, 45), batch=self.batch)

        # ── Labels ──────────────────────────────────────────────────
        self.hp_label = self._label("HULL", UI_FONT_META, 9, color=(*muted, 220))
        self.hp_value_label = self._label("", UI_FONT_BODY, 10, ax="right", color=(*text_color, 255))
        self.shield_label = self._label("SHIELD", UI_FONT_META, 9, color=(*muted, 220))
        self.shield_value_label = self._label("", UI_FONT_BODY, 10, ax="right", color=(*text_color, 255))
        self.boost_label = self._label("BOOST", UI_FONT_META, 9, color=(255, 185, 95, 220))
        self.boost_value_label = self._label("", UI_FONT_BODY, 10, ax="right", color=(255, 210, 130, 255))

        # Weapon and skin chips along the foot of the health panel
        self.weapon_chip = WeaponChip(self.batch, self._label, frame_batch=self._frame_batch)
        self.skin_chip = Chip(self.batch, self._label, label_color=accent, frame_batch=self._frame_batch)
        self.skin_chip.set_text(DEFAULT_SKIN_NAME)
        self._skin_name = DEFAULT_SKIN_NAME

        # Radial Ultra gauge (bottom-left)
        self.ultra_gauge = RadialGauge(self.batch, self._label)

        # Wave chip labels sit on baselines (title above the meta line), so they cannot leave the chip.
        self.wave_label = self._label("", UI_FONT_HEAD, 22, ax="center", ay="baseline", color=(*text_color, 255))
        self.meta_label = self._label("", UI_FONT_META, 10, ax="center", ay="baseline", color=(*muted, 230))
        self.status_label = self._label("", UI_FONT_BODY, 12, ax="center", ay="center", color=(*muted, 255))

        self.score_title_label = self._label("SCORE", UI_FONT_META, 10, color=(214, 200, 160, 220))
        self.score_value_label = self._label("0", UI_FONT_HEAD, 20, ax="right", color=(255, 240, 180, 255))
        self.combo_label = self._label("", UI_FONT_META, 10, ax="right", color=(255, 200, 100, 210))

        # Achievement toasts: a FIFO that shows one toast at a time, under the score panel
        self.toasts = ToastQueue()
        self.toast_view = ToastView(self.batch, self._label, frame_batch=self._frame_batch)
        # High-contrast plates: one dark plate behind each HUD number, sized to its text in _sync_number_plates().
        number_labels = [
            self.hp_value_label, self.shield_value_label, self.boost_value_label,
            self.wave_label, self.meta_label, self.status_label, self.score_value_label, self.combo_label,
            *self.weapon_chip.labels(),
        ]
        self._number_pairs = []
        for lbl in number_labels:
            plate = shapes.Rectangle(0, 0, 1, 1, color=CONTRAST_PLATE_COLOR, batch=self.batch, group=self._plate_group)
            plate.opacity = 0
            self._number_pairs.append((lbl, plate))

        # ── Banner (center-screen; own batch so it draws over the HUD) ──
        self._banner_batch = pyglet.graphics.Batch()
        self._banner_g_bg = pyglet.graphics.Group(order=0)
        self._banner_g_fx = pyglet.graphics.Group(order=1)
        self._banner_g_txt = pyglet.graphics.Group(order=2)
        self._banner_active = False
        self._banner_t = 0.0
        self._banner_dur = 2.2
        self._banner_src = ("", "")
        self._banner_px = (34, 16)
        self.banner_plate = shapes.Rectangle(
            0, 0, 1, 1, color=(6, 10, 18), batch=self._banner_batch, group=self._banner_g_bg
        )
        self.banner_accent = shapes.Rectangle(
            0, 0, 1, 1, color=(238, 245, 255), batch=self._banner_batch, group=self._banner_g_fx
        )
        self.banner_title = pyglet.text.Label(
            "", font_name=UI_FONT_HEAD, font_size=34, x=0, y=0, anchor_x="center", anchor_y="baseline",
            color=(238, 245, 255, 255), batch=self._banner_batch, group=self._banner_g_txt,
        )
        self.banner_sub = pyglet.text.Label(
            "", font_name=UI_FONT_BODY, font_size=16, x=0, y=0, anchor_x="center", anchor_y="baseline",
            color=(196, 210, 230, 230), batch=self._banner_batch, group=self._banner_g_txt,
        )
        self._paint(self.banner_title, (238, 245, 255, 255))
        self._paint(self.banner_sub, (196, 210, 230, 230))

        # ── Boss health bar (top-center, under the status bar) ──────
        self._boss_batch = pyglet.graphics.Batch()
        self._boss_g_bg = pyglet.graphics.Group(order=0)
        self._boss_g_bar = pyglet.graphics.Group(order=1)
        self._boss_g_txt = pyglet.graphics.Group(order=2)
        self._boss_active = False
        self._boss_name = ""
        self._boss_key = None
        self._boss_frac = 1.0
        self._boss_trail = 1.0
        self._boss_lag_from = 1.0
        self._boss_lag_t = 0.0
        self._boss_bar_w = 240
        self.boss_plate = shapes.BorderedRectangle(
            0, 0, 1, 1, border=2, color=token("BG"), border_color=token("DANGER"),
            batch=self._boss_batch, group=self._boss_g_bg,
        )
        self.boss_plate.opacity = 210
        self.boss_bar_bg = shapes.Rectangle(
            0, 0, 1, 1, color=(58, 30, 34), batch=self._boss_batch, group=self._boss_g_bar
        )
        self.boss_trail_bar = shapes.Rectangle(
            0, 0, 1, 1, color=(255, 214, 170), batch=self._boss_batch, group=self._boss_g_bar
        )
        self.boss_trail_bar.opacity = 230
        self.boss_fill = shapes.Rectangle(
            0, 0, 1, 1, color=(110, 220, 110), batch=self._boss_batch, group=self._boss_g_bar
        )
        self.boss_name_label = self._label(
            "", UI_FONT_HEAD, 11, ay="baseline", color=(255, 222, 206, 255),
            batch=self._boss_batch, group=self._boss_g_txt,
        )
        self.boss_pct_label = self._label(
            "", UI_FONT_BODY, 13, ax="right", ay="baseline", color=(255, 236, 220, 255),
            batch=self._boss_batch, group=self._boss_g_txt,
        )
        boss_plate = shapes.Rectangle(0, 0, 1, 1, color=CONTRAST_PLATE_COLOR, batch=self._boss_batch, group=self._boss_g_bar)
        boss_plate.opacity = 0
        self._number_pairs.append((self.boss_pct_label, boss_plate))

        self.layout(width, height)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _label(self, text, font, size, ax="left", ay="bottom",
               color=(214, 225, 238, 220), batch=None, group=None):
        """Create a label that is resized with the HUD scale in layout()."""
        lbl = pyglet.text.Label(
            text, font_name=font, font_size=size, x=0, y=0,
            anchor_x=ax, anchor_y=ay, color=self._tone(color),
            batch=batch if batch is not None else self.batch,
            group=group if group is not None else self._text_group,
        )
        self._label_base[id(lbl)] = (lbl, self._base_rgba(color))
        self._scaled_labels.append((lbl, size))
        return lbl

    @staticmethod
    def _base_rgba(color) -> tuple:
        vals = tuple(int(c) for c in color)
        return vals + (255,) if len(vals) == 3 else vals

    def _tone(self, color) -> tuple:
        """The colour a label is drawn in. High contrast moves each channel toward white and makes the text opaque."""
        rgba = self._base_rgba(color)
        if not self._contrast:
            return rgba
        r, g, b = (int(round(c + (255 - c) * CONTRAST_LIFT)) for c in rgba[:3])
        return (r, g, b, 255)

    def _paint(self, label, color) -> None:
        """Set a label's base colour and draw it toned. Every colour change goes through here, so high contrast stays in force."""
        base = self._base_rgba(color)
        self._label_base[id(label)] = (label, base)
        label.color = self._tone(base)

    def set_high_contrast(self, on: bool) -> None:
        """Turn the high-contrast HUD on or off. Applies at once to every label, plate and banner."""
        self._contrast = bool(on)
        for label, base in self._label_base.values():
            label.color = self._tone(base)

    @property
    def high_contrast(self) -> bool:
        return self._contrast

    def _sync_number_plates(self) -> None:
        """Size and place a dark plate behind every HUD number while high contrast is on. Hidden otherwise.

        The plate covers the glyphs (cap height above the baseline), not the full line box, so it does not
        stretch past the panel it sits in. Pyglet font sizes are points; the window draws them at 96 dpi.
        """
        pad_x = self._sz(CONTRAST_PLATE_PAD)
        for label, plate in self._number_pairs:
            if not self._contrast or not str(label.text or "").strip():
                plate.opacity = 0
                continue
            w = float(label.content_width)
            h = float(label.content_height)
            em = float(label.font_size) * (96.0 / 72.0)
            cap = 0.72 * em
            descent = 0.22 * em
            pad_y = 0.25 * em
            ax = label.anchor_x
            ay = label.anchor_y
            if ay == "baseline":
                baseline = label.y
            elif ay == "bottom":
                baseline = label.y + descent
            elif ay == "center":
                baseline = label.y - h / 2.0 + descent
            else:
                baseline = label.y - h + descent
            left = label.x - (w if ax == "right" else w / 2.0 if ax == "center" else 0.0)
            plate.x = left - pad_x
            plate.y = baseline - pad_y
            plate.width = w + pad_x * 2
            plate.height = cap + pad_y * 2
            plate.opacity = CONTRAST_PLATE_ALPHA

    def _sz(self, value: float) -> int:
        """Scale a reference (980x620) pixel value to the current window."""
        return int(round(value * self._s))

    def _frame(self, key: str, x: int, y: int, w: int, h: int, edge: int, shadow: bool = True) -> None:
        """Rebuild one HUD panel from ui_theme: a drop shadow, an accent edge and the fill."""
        for shp in self._frames.pop(key, []):
            shp.delete()
        shadow_shapes = []
        if shadow:
            offset = self._sz(3)
            shadow_shapes = draw_panel(self._frame_batch, x + offset, y - offset, w, h, color=token("BG"))
        edge_shapes = draw_panel(self._frame_batch, x - edge, y - edge, w + 2 * edge, h + 2 * edge, color=token("ACCENT"))
        fill_shapes = draw_panel(self._frame_batch, x, y, w, h, color=token("PANEL"))
        for shp in shadow_shapes:
            shp.opacity = PANEL_SHADOW_ALPHA
        for shp in edge_shapes:
            shp.opacity = PANEL_EDGE_ALPHA
        for shp in fill_shapes:
            shp.opacity = PANEL_FILL_ALPHA
        self._frames[key] = shadow_shapes + edge_shapes + fill_shapes

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def layout(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._s = _ui_scale(width, height)
        sz = self._sz

        for lbl, base in self._scaled_labels:
            _set_size(lbl, sz(base))
        self._banner_fonts()

        margin = sz(14)
        min_gap = sz(12)
        edge = max(1, sz(2))

        # Health / shield / boost panel (bottom-left), with the weapon and skin chips along its foot.
        # It sits low so the status line, under the wave chip, never runs into it.
        panel_w = sz(max(220, min(360, int(width * 0.33))))
        panel_h = sz(116)
        panel_x = margin
        panel_y = margin
        self._frame("hull", panel_x, panel_y, panel_w, panel_h, edge)

        bar_margin_x = sz(14)
        self._bar_w = panel_w - (bar_margin_x * 2)
        bar_h = sz(10)
        hp_y = panel_y + sz(84)
        sh_y = panel_y + sz(56)
        boost_y = panel_y + sz(28)
        bar_x = panel_x + bar_margin_x

        self.hp_bar_bg.x = bar_x
        self.hp_bar_bg.y = hp_y
        self.hp_bar_bg.width = self._bar_w
        self.hp_bar_bg.height = bar_h
        self.hp_bar.x = bar_x
        self.hp_bar.y = hp_y
        self.hp_bar.height = bar_h

        self.shield_bar_bg.x = bar_x
        self.shield_bar_bg.y = sh_y
        self.shield_bar_bg.width = self._bar_w
        self.shield_bar_bg.height = bar_h
        self.shield_bar.x = bar_x
        self.shield_bar.y = sh_y
        self.shield_bar.height = bar_h

        self.boost_bar_bg.x = bar_x
        self.boost_bar_bg.y = boost_y
        self.boost_bar_bg.width = self._bar_w
        self.boost_bar_bg.height = bar_h - sz(2)
        self.boost_bar.x = bar_x
        self.boost_bar.y = boost_y
        self.boost_bar.height = bar_h - sz(2)

        self.hp_label.x = bar_x
        self.hp_label.y = hp_y + bar_h + sz(2)
        self.hp_value_label.x = bar_x + self._bar_w
        self.hp_value_label.y = hp_y + bar_h + sz(1)
        self.shield_label.x = bar_x
        self.shield_label.y = sh_y + bar_h + sz(2)
        self.shield_value_label.x = bar_x + self._bar_w
        self.shield_value_label.y = sh_y + bar_h + sz(1)
        self.boost_label.x = bar_x
        self.boost_label.y = boost_y + bar_h
        self.boost_value_label.x = bar_x + self._bar_w
        self.boost_value_label.y = boost_y + bar_h

        chip_h = sz(16)
        row_y = panel_y + sz(6)
        chip_gap = sz(6)
        skin_w = self.skin_chip.width_for(self._bar_w * 0.42, pad=sz(6), min_w=sz(56))
        weapon_w = self._bar_w - skin_w - chip_gap
        self.weapon_chip.place(bar_x, row_y, weapon_w, chip_h, pad=sz(6), swatch=sz(8), gap=sz(5))
        self.skin_chip.place(bar_x + weapon_w + chip_gap, row_y, skin_w, chip_h, pad=sz(6))

        # Radial Ultra gauge (top-left). Its caption block is reserved so the status line keeps clear.
        ring_r = sz(34)
        ring_cx = margin + ring_r
        ring_cy = height - margin - ring_r
        ring_block_right = ring_cx + ring_r + sz(64)
        self.ultra_gauge.place(ring_cx, ring_cy, ring_r, max(2, sz(6)), caption_x=ring_cx + ring_r + sz(10))

        # Wave chip (top-center). Reference 56 px tall: meta baseline at 11, wave baseline at 26,
        # which leaves ~11 px above the title and below the meta line with a 6 px gap between them.
        chip_w = sz(max(160, min(320, int(width * 0.26))))
        wave_h = sz(56)
        chip_x = (width - chip_w) // 2
        wave_y = height - margin - wave_h
        chip_right = chip_x + chip_w
        self._frame("wave", chip_x, wave_y, chip_w, wave_h, edge)

        self.wave_label.x = chip_x + chip_w // 2
        self.wave_label.y = wave_y + sz(26)
        self.meta_label.x = chip_x + chip_w // 2
        self.meta_label.y = wave_y + sz(11)
        self._meta_max_w = chip_w - sz(24)
        _fit_text(self.meta_label, self._meta_src, self._meta_max_w)

        # Score panel (top-right)
        score_panel_w = sz(max(160, min(260, int(width * 0.22))))
        score_panel_h = sz(68)
        score_panel_x = width - margin - score_panel_w
        score_panel_y = height - margin - score_panel_h

        # Avoid overlapping with the wave chip: drop the score panel under it when they share a column
        if score_panel_x < chip_right + min_gap:
            score_panel_y = wave_y - score_panel_h - sz(8)
        self._frame("score", score_panel_x, score_panel_y, score_panel_w, score_panel_h, edge)

        score_pad = sz(12)
        self.score_title_label.x = score_panel_x + score_pad
        self.score_title_label.y = score_panel_y + score_panel_h - sz(14)
        self.score_value_label.x = score_panel_x + score_panel_w - score_pad
        self.score_value_label.y = score_panel_y + score_panel_h - sz(36)
        self.combo_label.x = score_panel_x + score_panel_w - score_pad
        self.combo_label.y = score_panel_y + sz(8)

        # Status bar (under the wave chip). Where it shares a row with the Ultra gauge block or the
        # score panel, it is centred within the free span so it never runs into either one.
        status_w = max(sz(240), min(sz(640), int(width * 0.58)))
        status_h = sz(28)
        status_y = max(sz(6), wave_y - status_h - sz(10))
        half = status_w // 2
        center = width // 2
        if _spans_overlap(status_y, status_y + status_h, ring_cy - ring_r, ring_cy + ring_r):
            half = min(half, center - (ring_block_right + min_gap))
        if _spans_overlap(status_y, status_y + status_h, score_panel_y, score_panel_y + score_panel_h):
            half = min(half, (score_panel_x - min_gap) - center)
        status_w = min(status_w, max(sz(220), 2 * half))
        status_x = (width - status_w) // 2
        self._frame("status", status_x, status_y, status_w, status_h, max(1, sz(1)), shadow=False)
        self.status_label.x = status_x + status_w // 2
        self.status_label.y = status_y + status_h // 2
        self._status_max_w = float(max(sz(60), status_w - sz(28)))
        self._status_cache.clear()  # cached widths depend on the font size and the bar width

        # Achievement toasts stack under the score panel, one at a time
        toast_h = sz(44)
        toast_y = score_panel_y - sz(8) - toast_h
        self.toast_view.place(
            score_panel_x, toast_y, score_panel_w, toast_h, pad=sz(12),
            title_y=toast_h - sz(18), sub_y=sz(11), edge=edge,
        )

        # Boss bar sits below the status bar and the health panel, whichever is lower.
        self._layout_boss(status_y - sz(8))
        if self._boss_active:
            self._refresh_boss()

        if self._banner_active:
            self._fit_banner_text()
            self._place_banner()

    def _layout_boss(self, boss_top: int) -> None:
        sz = self._sz
        boss_w = max(sz(240), min(sz(480), int(self.width * 0.42)))
        plate_h = sz(40)
        plate_x = (self.width - boss_w) // 2
        plate_y = boss_top - plate_h
        pad = sz(12)
        bar_h = sz(8)
        bar_x = plate_x + pad
        bar_y = plate_y + sz(9)
        bar_w = boss_w - pad * 2
        self._boss_bar_w = bar_w

        self.boss_plate.x = plate_x
        self.boss_plate.y = plate_y
        self.boss_plate.width = boss_w
        self.boss_plate.height = plate_h
        for shape in (self.boss_bar_bg, self.boss_trail_bar, self.boss_fill):
            shape.x = bar_x
            shape.y = bar_y
            shape.height = bar_h
        self.boss_bar_bg.width = bar_w
        self.boss_name_label.x = bar_x
        self.boss_name_label.y = plate_y + sz(24)
        self.boss_pct_label.x = bar_x + bar_w
        self.boss_pct_label.y = plate_y + sz(24)

    def _banner_fonts(self) -> None:
        title_px = min(44, self._sz(34))
        sub_px = self._sz(16)
        self._banner_px = (title_px, sub_px)
        _set_size(self.banner_title, title_px)
        _set_size(self.banner_sub, sub_px)

    def _fit_banner_text(self) -> None:
        title, sub = self._banner_src
        max_w = self.width * 0.86
        _fit_text(self.banner_title, title, max_w)
        _fit_text(self.banner_sub, sub, max_w)

    def _place_banner(self) -> None:
        """Position the banner plate and text for the current animation time."""
        sz = self._sz
        dur = self._banner_dur
        t = self._banner_t
        in_t = min(BANNER_IN_S, dur * 0.3)
        out_t = min(BANNER_OUT_S, dur * 0.45)
        alpha = 1.0
        slide = 0.0  # 1 at the start of slide-in, 0 once settled
        drift = 0.0  # 0 until the fade-out starts, then 1 at the end
        if t < in_t:
            eased = 1.0 - (1.0 - t / in_t) ** 3  # ease-out
            alpha = eased
            slide = 1.0 - eased
        elif t > dur - out_t:
            p = (t - (dur - out_t)) / out_t
            alpha = 1.0 - p
            drift = p

        title_px, sub_px = self._banner_px
        has_sub = bool(self.banner_sub.text)
        pad_x = sz(36)
        pad_y = sz(16)
        acc_h = max(2, sz(3))
        acc_gap = sz(12)
        title_cap = 0.72 * title_px
        sub_gap = sz(12)
        sub_cap = 0.66 * sub_px
        sub_desc = 0.22 * sub_px

        content_w = self.banner_title.content_width
        if has_sub:
            content_w = max(content_w, self.banner_sub.content_width)
        plate_w = min(self.width * 0.94, max(sz(320), content_w + pad_x * 2))
        plate_w *= 1.0 - 0.08 * slide
        plate_h = pad_y + acc_h + acc_gap + title_cap + pad_y
        if has_sub:
            plate_h += sub_gap + sub_cap + sub_desc

        cx = self.width / 2.0
        cy = self.height * 0.70
        dy = -slide * sz(18) + drift * sz(8)
        plate_y = cy - plate_h / 2.0 + dy
        top = plate_y + plate_h
        acc_y = top - pad_y - acc_h
        title_base = acc_y - acc_gap - title_cap
        sub_base = title_base - sub_gap - sub_cap
        acc_w = min(plate_w * 0.5, sz(200))

        self.banner_plate.x = cx - plate_w / 2.0
        self.banner_plate.y = plate_y
        self.banner_plate.width = plate_w
        self.banner_plate.height = plate_h
        self.banner_plate.opacity = int(178 * alpha)

        self.banner_accent.x = cx - acc_w / 2.0
        self.banner_accent.y = acc_y
        self.banner_accent.width = acc_w
        self.banner_accent.height = acc_h
        self.banner_accent.opacity = int(255 * alpha)

        self.banner_title.x = round(cx)
        self.banner_title.y = round(title_base)
        self.banner_title.opacity = int(255 * alpha)
        self.banner_sub.visible = has_sub
        self.banner_sub.x = round(cx)
        self.banner_sub.y = round(sub_base)
        self.banner_sub.opacity = int(230 * alpha)

    # ------------------------------------------------------------------
    # Banner, boss bar, toast and skin API
    # ------------------------------------------------------------------

    def show_banner(
        self,
        title: str,
        subtitle: str = "",
        color: tuple = (238, 245, 255),
        duration: float = 2.2,
    ) -> None:
        """Show a centre-screen announcement, replacing any banner already on screen."""
        self._banner_src = (str(title), str(subtitle))
        self._banner_dur = max(0.3, float(duration))
        self._banner_t = 0.0
        self._banner_active = True
        self.banner_accent.color = tuple(int(c) for c in tuple(color)[:3])
        self._banner_fonts()
        self._fit_banner_text()
        self._place_banner()

    def set_boss(self, name: str | None, hp: int, max_hp: int) -> None:
        """Show the boss bar for `name` at hp/max_hp, or hide it when name is None."""
        if name is None:
            self._boss_active = False
            self._boss_key = None
            return
        cap = max(1, int(max_hp))
        now = max(0, min(cap, int(hp)))
        name = str(name)
        key = (name, now, cap)
        if key == self._boss_key:
            return
        frac = now / cap
        if not self._boss_active or name != self._boss_name:
            self._boss_trail = frac  # new boss: no lag
        elif frac >= self._boss_trail:
            self._boss_trail = frac  # healed: follow immediately
        else:
            self._boss_lag_from = self._boss_trail  # damage: trail holds, then shrinks in tick()
            self._boss_lag_t = 0.0
        self._boss_active = True
        self._boss_name = name
        self._boss_key = key
        self._boss_frac = frac
        self._refresh_boss()

    def _refresh_boss(self) -> None:
        frac = self._boss_frac
        bar_w = self._boss_bar_w
        self.boss_fill.width = bar_w * frac
        self.boss_fill.color = (
            int(220 - 110 * frac),
            int(70 + 150 * frac),
            int(60 + 50 * frac),
        )
        self.boss_trail_bar.width = bar_w * max(self._boss_trail, frac)
        pct = int(round(frac * 100))
        if frac > 0.0 and pct == 0:
            pct = 1
        _set_text(self.boss_pct_label, f"{pct}%")
        name_max = bar_w - self.boss_pct_label.content_width - self._sz(14)
        _fit_text(self.boss_name_label, self._boss_name.upper(), name_max)

    def push_toast(self, title: str, subtitle: str = "") -> None:
        """Queue a toast. Toasts show one at a time, in order, each for TOAST_SECONDS."""
        self.toasts.push(title, subtitle)
        self._sync_toast()

    def push_achievement_toasts(self, achievement_ids) -> int:
        """Queue one toast per newly earned achievement id (the list achievements.evaluate returns).

        Returns how many ids were queued.
        """
        count = 0
        for achievement_id in achievement_ids or ():
            self.push_toast(achievement_name(achievement_id), TOAST_KICKER)
            count += 1
        return count

    def set_skin_name(self, name: str) -> None:
        """Show the selected skin's name on the skin chip (the chip is re-sized to fit its name)."""
        self._skin_name = str(name) or DEFAULT_SKIN_NAME
        self.skin_chip.set_text(self._skin_name)
        self.layout(self.width, self.height)

    @property
    def skin_name(self) -> str:
        return self._skin_name

    def _sync_toast(self) -> None:
        current = self.toasts.current
        if current is None:
            self.toast_view.hide()
        else:
            self.toast_view.show(current[0], current[1], self.toasts.queued, self.toasts.alpha())

    def tick(self, dt: float) -> None:
        """Advance banner timing, the boss damage trail, toasts and the Ultra pulse by one frame."""
        dt = max(0.0, float(dt))
        if self._banner_active:
            self._banner_t += dt
            if self._banner_t >= self._banner_dur:
                self._banner_active = False
            else:
                self._place_banner()
        if self._boss_active and self._boss_trail > self._boss_frac:
            self._boss_lag_t += dt
            p = (self._boss_lag_t - BOSS_LAG_HOLD_S) / BOSS_LAG_SHRINK_S
            if p >= 1.0:
                self._boss_trail = self._boss_frac
            elif p > 0.0:
                eased = 1.0 - (1.0 - p) ** 2
                self._boss_trail = self._boss_lag_from + (self._boss_frac - self._boss_lag_from) * eased
            if p > 0.0:
                self.boss_trail_bar.width = self._boss_bar_w * max(self._boss_trail, self._boss_frac)
        self.toasts.tick(dt)
        self._sync_toast()
        self._pulse_t += dt
        self.ultra_gauge.animate(self._pulse_t, reduce_motion=_reduce_motion())

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def _fit_status(self, segments) -> str:
        """Return the status line for (priority, text) segments, fitted to the status bar.

        A lower priority number is more important. The most important segments are kept and
        shown in list order; when the line is too wide, whole segments are dropped from the
        least important end and ' +N' tells how many were hidden. A lone segment that is still
        too wide is trimmed with '...'. Results are cached by (segments, width) because most
        frames repeat the same text.
        """
        items = tuple((int(prio), str(text)) for prio, text in segments if text)
        if not items:
            return ""
        key = (items, self._status_max_w)
        cached = self._status_cache.get(key)
        if cached is not None:
            return cached
        fitted = self._fit_status_uncached(items, self._status_max_w)
        if len(self._status_cache) >= STATUS_CACHE_MAX:
            self._status_cache.clear()
        self._status_cache[key] = fitted
        return fitted

    def _fit_status_uncached(self, items, max_w: float) -> str:
        label = self.status_label
        ranked = sorted(range(len(items)), key=lambda i: (items[i][0], i))  # most important first
        kept = list(ranked)
        dropped = 0

        def compose() -> str:
            line = STATUS_SEP.join(items[i][1] for i in sorted(kept))
            return f"{line} +{dropped}" if dropped else line

        text = compose()
        label.text = text
        while len(kept) > 1 and label.content_width > max_w:
            kept.pop()  # the least important segment left
            dropped += 1
            text = compose()
            label.text = text
        if label.content_width <= max_w:
            return text
        # One segment is left and still too wide: trim it and keep the ' +N' suffix readable.
        suffix = f" +{dropped}" if dropped else ""
        room = max_w
        if suffix:
            label.text = suffix
            room = max(1.0, max_w - label.content_width)
        _fit_text(label, items[kept[0]][1], room)
        return label.text + suffix

    def update_bars(
        self,
        player,
        state,
        score=None,
        status_text: str = "",
        has_infinite_boost: bool = False,
        crit_chance_bonus: float = 0.0,
        status_segments=None,
    ) -> None:
        """Sync HUD elements with current game state.

        status_segments is a list of (priority, text) pairs for the status line (see
        _fit_status). Without it, status_text is shown as a single segment.
        """
        # HP bar
        hp_cap = max(1, int(getattr(player, "max_hp", 100)))
        hp_now = max(0, int(player.hp))
        hp_frac = max(0.0, min(1.0, hp_now / hp_cap))
        self.hp_bar.width = self._bar_w * hp_frac
        self.hp_bar.color = (
            int(210 - 120 * hp_frac),
            int(80 + 155 * hp_frac),
            int(82 + 50 * hp_frac),
        )
        _set_text(self.hp_value_label, f"{hp_now}/{hp_cap}")

        # Shield bar (pickups cap at SHIELD_MAX, so the bar and its label never read past it)
        shield_cap = SHIELD_MAX
        shield_now = min(shield_cap, max(0, int(player.shield)))
        shield_frac = max(0.0, min(1.0, shield_now / max(1, shield_cap)))
        self.shield_bar.width = self._bar_w * shield_frac
        self.shield_bar.color = (
            int(48 + 36 * shield_frac),
            int(122 + 88 * shield_frac),
            int(202 + 42 * shield_frac),
        )
        _set_text(self.shield_value_label, f"{shield_now}/{shield_cap}")

        # Boost bar
        boost_max = max(1.0, float(getattr(player, "boost_max_energy", 100.0)))
        boost_now = max(0.0, float(getattr(player, "boost_energy", 100.0)))
        boost_frac = max(0.0, min(1.0, boost_now / boost_max))
        self.boost_bar.width = self._bar_w * boost_frac
        has_inf = has_infinite_boost or (state.time < float(getattr(player, "infinite_boost_until", 0.0)))
        if has_inf:
            self.boost_bar.color = (255, 235, 90)
            _set_text(self.boost_value_label, "INF")
            self._paint(self.boost_value_label, (255, 245, 120, 255))
        else:
            self.boost_bar.color = (255, 155, 50) if getattr(player, "is_boosting", False) else (205, 120, 40)
            _set_text(self.boost_value_label, f"{int(boost_now)}%")
            self._paint(self.boost_value_label, (255, 210, 130, 255))

        # Weapon chip: name (with pierce), swatch from projectile_art, and the crit chance
        wp = getattr(player, "current_weapon", None)
        if wp:
            pierce_str = f" [P+{wp.pierce}]" if getattr(wp, "pierce", 0) > 0 else ""
            total_crit = min(1.0, max(0.0, getattr(wp, "crit_chance", 0.10) + float(crit_chance_bonus)))
            crit_pct = int(round(total_crit * 100))
            self.weapon_chip.set_weapon(f"{wp.name.upper()}{pierce_str}", f"CRIT {crit_pct}%", weapon_swatch(wp))
        else:
            self.weapon_chip.set_weapon("", "", None)

        # Radial Ultra gauge: charges held out of capacity
        ultra_cap = int(getattr(player, "ultra_max_charges", config.ULTRA_MAX_CHARGES))
        self.ultra_gauge.update(int(getattr(player, "ultra_charges", 0)), ultra_cap)

        # Wave chip: title and meta line (meta is trimmed to fit the chip)
        _set_text(self.wave_label, f"WAVE {int(state.wave):02d}")
        difficulty = str(getattr(state, "difficulty", "normal")).upper()
        combo_value = int(getattr(state, "enemy_combo_value", 0))
        combo_text = str(getattr(state, "enemy_combo_text", "")).strip()
        if combo_text:
            meta_src = f"{difficulty}  T+{int(state.time):03d}s  CMB {combo_value}  {combo_text}"
        else:
            meta_src = f"{difficulty}  T+{int(state.time):03d}s"
        if meta_src != self._meta_src:
            self._meta_src = meta_src
            _fit_text(self.meta_label, meta_src, self._meta_max_w)

        # Status line: priority-fitted so boss and ultra text survive a crowded bar
        if status_segments is None:
            status_segments = [(0, status_text)] if status_text else []
        _set_text(self.status_label, self._fit_status(status_segments))

        # Score
        if score is not None:
            _set_text(self.score_value_label, f"{score.score:,}")
            if score.combo > 1.05:
                _set_text(self.combo_label, f"x{score.combo:.1f} COMBO")
                # Gold-orange pulsing as combo rises
                intensity = min(1.0, (score.combo - 1.0) / (6.0 - 1.0))
                g = int(200 - 80 * intensity)
                self._paint(self.combo_label, (255, g, 80, 230))
            else:
                _set_text(self.combo_label, "")
        else:
            _set_text(self.score_value_label, "0")
            _set_text(self.combo_label, "")

    def draw(self) -> None:
        self._sync_number_plates()
        self._frame_batch.draw()
        self.batch.draw()
        if self._boss_active:
            self._boss_batch.draw()
        if self._banner_active:
            self._banner_batch.draw()
