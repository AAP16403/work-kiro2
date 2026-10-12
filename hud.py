"""HUD (Heads-Up Display) – health, shield, wave, status, score, banners and boss bar."""

import pyglet
from pyglet import shapes

from menu import UI_FONT_HEAD, UI_FONT_BODY, UI_FONT_META


BANNER_IN_S = 0.25        # ease-out slide/scale-in
BANNER_OUT_S = 0.45       # fade-out at the end of a banner
BOSS_LAG_HOLD_S = 0.10    # damage trail waits this long before it starts shrinking
BOSS_LAG_SHRINK_S = 0.40  # then shrinks toward the real HP (about 0.5 s in total)


def _ui_scale(width: int, height: int) -> float:
    """1.0 at the 980x620 reference size, growing to 1.35 on fullscreen 1080p."""
    return max(1.0, min(1.35, min(width / 980.0, height / 620.0)))


def _set_text(label, text: str) -> None:
    """Assign label text only when it changed (pyglet relayouts on every assignment)."""
    if label.text != text:
        label.text = text


def _set_size(label, size: int) -> None:
    if int(label.font_size) != size:
        label.font_size = size


def _fit_text(label, text: str, max_w: float) -> None:
    """Set label text, trimmed with '...' so its width stays within max_w pixels."""
    label.text = text
    if max_w <= 0 or label.content_width <= max_w:
        return
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        label.text = text[:mid].rstrip() + "..."
        if label.content_width <= max_w:
            lo = mid
        else:
            hi = mid - 1
    label.text = text[:lo].rstrip() + "..."


class HUD:
    """In-game overlay: HP/shield/boost, wave chip, status bar, score, banners and boss bar."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self._s = 1.0
        self._bar_w = 240
        self._status_max_chars = 120
        self._scaled_labels = []  # (label, reference font size) pairs resized in layout()
        self._meta_src = ""
        self._meta_max_w = 200.0

        self.batch = pyglet.graphics.Batch()

        # ── Health / Shield panel (top-left) ────────────────────────
        self.panel_shadow = shapes.Rectangle(0, 0, 1, 1, color=(0, 0, 0), batch=self.batch)
        self.panel_shadow.opacity = 78
        self.panel_bg = shapes.Rectangle(0, 0, 1, 1, color=(14, 21, 30), batch=self.batch)
        self.panel_bg.opacity = 216
        self.panel_border = shapes.BorderedRectangle(
            0, 0, 1, 1, border=2, color=(20, 28, 40), border_color=(82, 146, 212), batch=self.batch
        )
        self.panel_border.opacity = 228

        self.hp_bar_bg = shapes.Rectangle(0, 0, 1, 1, color=(42, 45, 55), batch=self.batch)
        self.hp_bar = shapes.Rectangle(0, 0, 1, 1, color=(120, 210, 120), batch=self.batch)
        self.shield_bar_bg = shapes.Rectangle(0, 0, 1, 1, color=(36, 44, 58), batch=self.batch)
        self.shield_bar = shapes.Rectangle(0, 0, 1, 1, color=(84, 176, 232), batch=self.batch)
        self.boost_bar_bg = shapes.Rectangle(0, 0, 1, 1, color=(48, 34, 20), batch=self.batch)
        self.boost_bar = shapes.Rectangle(0, 0, 1, 1, color=(255, 145, 45), batch=self.batch)

        # ── Wave chip (top-center) ──────────────────────────────────
        self.wave_chip_shadow = shapes.Rectangle(0, 0, 1, 1, color=(0, 0, 0), batch=self.batch)
        self.wave_chip_shadow.opacity = 86
        self.wave_chip_bg = shapes.Rectangle(0, 0, 1, 1, color=(18, 28, 42), batch=self.batch)
        self.wave_chip_bg.opacity = 230
        self.wave_chip_border = shapes.BorderedRectangle(
            0, 0, 1, 1, border=2, color=(18, 28, 42), border_color=(110, 186, 255), batch=self.batch
        )

        # ── Status bar (below wave chip) ────────────────────────────
        self.status_bg = shapes.Rectangle(0, 0, 1, 1, color=(10, 16, 24), batch=self.batch)
        self.status_bg.opacity = 196
        self.status_border = shapes.BorderedRectangle(
            0, 0, 1, 1, border=1, color=(10, 16, 24), border_color=(70, 128, 184), batch=self.batch
        )

        # ── Score panel (top-right) ─────────────────────────────────
        self.score_shadow = shapes.Rectangle(0, 0, 1, 1, color=(0, 0, 0), batch=self.batch)
        self.score_shadow.opacity = 78
        self.score_bg = shapes.Rectangle(0, 0, 1, 1, color=(14, 21, 30), batch=self.batch)
        self.score_bg.opacity = 216
        self.score_border = shapes.BorderedRectangle(
            0, 0, 1, 1, border=2, color=(20, 28, 40), border_color=(212, 180, 82), batch=self.batch
        )
        self.score_border.opacity = 228

        # ── Labels ──────────────────────────────────────────────────
        self.hp_label = self._label("HULL", UI_FONT_META, 9)
        self.hp_value_label = self._label("", UI_FONT_BODY, 10, ax="right", color=(244, 250, 255, 255))
        self.shield_label = self._label("SHIELD", UI_FONT_META, 9, color=(188, 210, 232, 220))
        self.shield_value_label = self._label("", UI_FONT_BODY, 10, ax="right", color=(232, 244, 255, 255))
        self.boost_label = self._label("BOOST", UI_FONT_META, 9, color=(255, 185, 95, 220))
        self.boost_value_label = self._label("", UI_FONT_BODY, 10, ax="right", color=(255, 210, 130, 255))
        self.weapon_label = self._label("", UI_FONT_META, 9, color=(160, 215, 255, 220))

        # Wave chip text sits on baselines (title above the meta line), so it cannot leave the chip.
        self.wave_label = self._label("", UI_FONT_HEAD, 22, ax="center", ay="baseline", color=(238, 245, 255, 255))
        self.meta_label = self._label("", UI_FONT_META, 10, ax="center", ay="baseline", color=(168, 194, 222, 230))
        self.status_label = self._label("", UI_FONT_BODY, 12, ax="center", ay="center", color=(170, 186, 206, 255))

        self.score_title_label = self._label("SCORE", UI_FONT_META, 10, color=(214, 200, 160, 220))
        self.score_value_label = self._label("0", UI_FONT_HEAD, 20, ax="right", color=(255, 240, 180, 255))
        self.combo_label = self._label("", UI_FONT_META, 10, ax="right", color=(255, 200, 100, 210))

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
            0, 0, 1, 1, border=2, color=(10, 12, 18), border_color=(196, 78, 70),
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

        self.layout(width, height)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _label(self, text, font, size, ax="left", ay="bottom",
               color=(214, 225, 238, 220), batch=None, group=None):
        """Create a label that is resized with the HUD scale in layout()."""
        lbl = pyglet.text.Label(
            text, font_name=font, font_size=size, x=0, y=0,
            anchor_x=ax, anchor_y=ay, color=color,
            batch=batch if batch is not None else self.batch, group=group,
        )
        self._scaled_labels.append((lbl, size))
        return lbl

    def _sz(self, value: float) -> int:
        """Scale a reference (980x620) pixel value to the current window."""
        return int(round(value * self._s))

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
        panel_w = sz(max(220, min(360, int(width * 0.33))))
        panel_h = sz(104)
        panel_x = margin
        panel_y = height - margin - panel_h

        # Health / shield / boost panel
        self.panel_shadow.x = panel_x + sz(3)
        self.panel_shadow.y = panel_y - sz(3)
        self.panel_shadow.width = panel_w
        self.panel_shadow.height = panel_h
        self.panel_bg.x = panel_x
        self.panel_bg.y = panel_y
        self.panel_bg.width = panel_w
        self.panel_bg.height = panel_h
        self.panel_border.x = panel_x
        self.panel_border.y = panel_y
        self.panel_border.width = panel_w
        self.panel_border.height = panel_h

        bar_margin_x = sz(14)
        self._bar_w = panel_w - (bar_margin_x * 2)
        bar_h = sz(10)
        hp_y = panel_y + sz(68)
        sh_y = panel_y + sz(45)
        boost_y = panel_y + sz(22)
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
        self.weapon_label.x = bar_x
        self.weapon_label.y = panel_y + sz(8)

        # Wave chip (top-center). Reference 56 px tall: meta baseline at 11, wave baseline at 26,
        # which leaves ~11 px above the title and below the meta line with a 6 px gap between them.
        chip_w = sz(max(160, min(320, int(width * 0.26))))
        chip_h = sz(56)
        chip_x = (width - chip_w) // 2
        chip_y = height - margin - chip_h
        min_gap = sz(12)
        panel_right = panel_x + panel_w
        chip_left = chip_x
        chip_right = chip_x + chip_w
        chip_overlaps_panel = not (chip_left >= panel_right + min_gap or chip_right <= panel_x - min_gap)
        if chip_overlaps_panel:
            chip_y = panel_y - chip_h - sz(8)

        self.wave_chip_shadow.x = chip_x + sz(3)
        self.wave_chip_shadow.y = chip_y - sz(3)
        self.wave_chip_shadow.width = chip_w
        self.wave_chip_shadow.height = chip_h
        self.wave_chip_bg.x = chip_x
        self.wave_chip_bg.y = chip_y
        self.wave_chip_bg.width = chip_w
        self.wave_chip_bg.height = chip_h
        self.wave_chip_border.x = chip_x
        self.wave_chip_border.y = chip_y
        self.wave_chip_border.width = chip_w
        self.wave_chip_border.height = chip_h

        self.wave_label.x = chip_x + chip_w // 2
        self.wave_label.y = chip_y + sz(26)
        self.meta_label.x = chip_x + chip_w // 2
        self.meta_label.y = chip_y + sz(11)
        self._meta_max_w = chip_w - sz(24)
        _fit_text(self.meta_label, self._meta_src, self._meta_max_w)

        # Status bar
        is_stacked = chip_y < panel_y
        if is_stacked:
            status_w = min(sz(700), max(sz(220), int(width * 0.9)))
        else:
            status_w = max(sz(240), min(sz(640), int(width * 0.58)))
        status_h = sz(28)
        status_x = (width - status_w) // 2
        status_y = max(sz(6), chip_y - status_h - sz(10))
        self.status_bg.x = status_x
        self.status_bg.y = status_y
        self.status_bg.width = status_w
        self.status_bg.height = status_h
        self.status_border.x = status_x
        self.status_border.y = status_y
        self.status_border.width = status_w
        self.status_border.height = status_h
        self.status_label.x = status_x + status_w // 2
        self.status_label.y = status_y + status_h // 2
        self._status_max_chars = max(24, int((status_w - sz(28)) / (7.2 * self._s)))

        # Score panel (top-right)
        score_panel_w = sz(max(160, min(260, int(width * 0.22))))
        score_panel_h = sz(68)
        score_panel_x = width - margin - score_panel_w
        score_panel_y = height - margin - score_panel_h

        # Avoid overlapping with wave chip
        if score_panel_x < chip_right + min_gap:
            score_panel_y = panel_y - score_panel_h - sz(8)

        self.score_shadow.x = score_panel_x + sz(3)
        self.score_shadow.y = score_panel_y - sz(3)
        self.score_shadow.width = score_panel_w
        self.score_shadow.height = score_panel_h
        self.score_bg.x = score_panel_x
        self.score_bg.y = score_panel_y
        self.score_bg.width = score_panel_w
        self.score_bg.height = score_panel_h
        self.score_border.x = score_panel_x
        self.score_border.y = score_panel_y
        self.score_border.width = score_panel_w
        self.score_border.height = score_panel_h

        score_pad = sz(12)
        self.score_title_label.x = score_panel_x + score_pad
        self.score_title_label.y = score_panel_y + score_panel_h - sz(14)
        self.score_value_label.x = score_panel_x + score_panel_w - score_pad
        self.score_value_label.y = score_panel_y + score_panel_h - sz(36)
        self.combo_label.x = score_panel_x + score_panel_w - score_pad
        self.combo_label.y = score_panel_y + sz(8)

        # Boss bar sits below the status bar and the health panel, whichever is lower.
        self._layout_boss(min(status_y, panel_y) - sz(8))
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
    # Banner and boss bar API
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

    def tick(self, dt: float) -> None:
        """Advance banner timing and the boss damage trail by one frame of real time."""
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

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def update_bars(
        self,
        player,
        state,
        score=None,
        status_text: str = "",
        has_infinite_boost: bool = False,
        crit_chance_bonus: float = 0.0,
    ) -> None:
        """Sync HUD elements with current game state."""
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

        # Shield bar
        shield_cap = 100
        shield_now = max(0, int(player.shield))
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
            self.boost_value_label.color = (255, 245, 120, 255)
        else:
            self.boost_bar.color = (255, 155, 50) if getattr(player, "is_boosting", False) else (205, 120, 40)
            _set_text(self.boost_value_label, f"{int(boost_now)}%")
            self.boost_value_label.color = (255, 210, 130, 255)

        # Weapon readout
        wp = getattr(player, "current_weapon", None)
        if wp:
            pierce_str = f" [P+{wp.pierce}]" if getattr(wp, "pierce", 0) > 0 else ""
            total_crit = min(1.0, max(0.0, getattr(wp, "crit_chance", 0.10) + float(crit_chance_bonus)))
            crit_pct = int(round(total_crit * 100))
            _set_text(self.weapon_label, f"{wp.name.upper()}{pierce_str}  CRIT {crit_pct}%")
        else:
            _set_text(self.weapon_label, "")

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

        # Status text
        max_chars = self._status_max_chars
        if len(status_text) > max_chars:
            status_text = status_text[: max(3, max_chars - 3)].rstrip() + "..."
        _set_text(self.status_label, status_text)

        # Score
        if score is not None:
            _set_text(self.score_value_label, f"{score.score:,}")
            if score.combo > 1.05:
                _set_text(self.combo_label, f"x{score.combo:.1f} COMBO")
                # Gold-orange pulsing as combo rises
                intensity = min(1.0, (score.combo - 1.0) / (6.0 - 1.0))
                g = int(200 - 80 * intensity)
                self.combo_label.color = (255, g, 80, 230)
            else:
                _set_text(self.combo_label, "")
        else:
            _set_text(self.score_value_label, "0")
            _set_text(self.combo_label, "")

    def draw(self) -> None:
        self.batch.draw()
        if self._boss_active:
            self._boss_batch.draw()
        if self._banner_active:
            self._banner_batch.draw()
