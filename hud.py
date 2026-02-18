"""HUD (Heads-Up Display) – health, shield, wave, status, and score readout."""

import pyglet
from pyglet import shapes

from menu import UI_FONT_HEAD, UI_FONT_BODY, UI_FONT_META


class HUD:
    """In-game overlay showing HP, shield, wave info, status effects, and score."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.batch = pyglet.graphics.Batch()
        self._bar_w = 240

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
        _lbl = lambda text, font, size, ax="left", ay="bottom", color=(214, 225, 238, 220): pyglet.text.Label(
            text, font_name=font, font_size=size, x=0, y=0,
            anchor_x=ax, anchor_y=ay, color=color, batch=self.batch,
        )

        self.hp_label = _lbl("HULL", UI_FONT_META, 10)
        self.hp_value_label = _lbl("", UI_FONT_BODY, 11, ax="right", color=(244, 250, 255, 255))
        self.shield_label = _lbl("SHIELD", UI_FONT_META, 10, color=(188, 210, 232, 220))
        self.shield_value_label = _lbl("", UI_FONT_BODY, 11, ax="right", color=(232, 244, 255, 255))

        self.wave_label = _lbl("", UI_FONT_HEAD, 22, ax="center", ay="center", color=(238, 245, 255, 255))
        self.meta_label = _lbl("", UI_FONT_META, 10, ax="center", ay="top", color=(168, 194, 222, 230))
        self.status_label = _lbl("", UI_FONT_BODY, 12, ax="center", ay="center", color=(170, 186, 206, 255))

        self.score_title_label = _lbl("SCORE", UI_FONT_META, 10, color=(214, 200, 160, 220))
        self.score_value_label = _lbl("0", UI_FONT_HEAD, 20, ax="right", color=(255, 240, 180, 255))
        self.combo_label = _lbl("", UI_FONT_META, 10, ax="right", color=(255, 200, 100, 210))

        self._status_max_chars = 120

        self.layout(width, height)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def layout(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

        margin = 14
        panel_w = max(220, min(360, int(width * 0.33)))
        panel_h = 88
        panel_x = margin
        panel_y = height - margin - panel_h

        # Health / shield panel
        self.panel_shadow.x = panel_x + 3
        self.panel_shadow.y = panel_y - 3
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

        bar_margin_x = 14
        self._bar_w = panel_w - (bar_margin_x * 2)
        bar_h = 12
        hp_y = panel_y + 44
        sh_y = panel_y + 22
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

        self.hp_label.x = bar_x
        self.hp_label.y = hp_y + bar_h + 3
        self.hp_value_label.x = bar_x + self._bar_w
        self.hp_value_label.y = hp_y + bar_h + 2
        self.shield_label.x = bar_x
        self.shield_label.y = sh_y + bar_h + 3
        self.shield_value_label.x = bar_x + self._bar_w
        self.shield_value_label.y = sh_y + bar_h + 2

        # Wave chip (top-center)
        chip_w = max(160, min(320, int(width * 0.26)))
        chip_h = 46
        chip_x = (width - chip_w) // 2
        chip_y = height - margin - chip_h
        min_gap = 12
        panel_right = panel_x + panel_w
        chip_left = chip_x
        chip_right = chip_x + chip_w
        chip_overlaps_panel = not (chip_left >= panel_right + min_gap or chip_right <= panel_x - min_gap)
        if chip_overlaps_panel:
            chip_y = panel_y - chip_h - 8

        self.wave_chip_shadow.x = chip_x + 3
        self.wave_chip_shadow.y = chip_y - 3
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
        self.wave_label.y = chip_y + int(chip_h * 0.62)
        self.meta_label.x = chip_x + chip_w // 2
        self.meta_label.y = chip_y + int(chip_h * 0.28)

        # Status bar
        is_stacked = chip_y < panel_y
        if is_stacked:
            status_w = max(220, min(700, int(width * 0.9)))
        else:
            status_w = max(240, min(640, int(width * 0.58)))
        status_h = 28
        status_x = (width - status_w) // 2
        status_y = max(6, chip_y - status_h - 10)
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
        self._status_max_chars = max(24, int((status_w - 28) / 7.2))

        # Score panel (top-right)
        score_panel_w = max(160, min(260, int(width * 0.22)))
        score_panel_h = 68
        score_panel_x = width - margin - score_panel_w
        score_panel_y = height - margin - score_panel_h

        # Avoid overlapping with wave chip
        if score_panel_x < chip_right + min_gap:
            score_panel_y = panel_y - score_panel_h - 8

        self.score_shadow.x = score_panel_x + 3
        self.score_shadow.y = score_panel_y - 3
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

        score_pad = 12
        self.score_title_label.x = score_panel_x + score_pad
        self.score_title_label.y = score_panel_y + score_panel_h - 14
        self.score_value_label.x = score_panel_x + score_panel_w - score_pad
        self.score_value_label.y = score_panel_y + score_panel_h - 36
        self.combo_label.x = score_panel_x + score_panel_w - score_pad
        self.combo_label.y = score_panel_y + 8

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def update_bars(self, player, state, score=None, status_text: str = "") -> None:
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
        self.hp_value_label.text = f"{hp_now}/{hp_cap}"

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
        self.shield_value_label.text = f"{shield_now}/{shield_cap}"

        # Wave label
        self.wave_label.text = f"WAVE {int(state.wave):02d}"
        combo_value = int(getattr(state, "enemy_combo_value", 0))
        combo_text = str(getattr(state, "enemy_combo_text", "")).strip()
        if combo_text:
            self.meta_label.text = (
                f"{str(getattr(state, 'difficulty', 'normal')).upper()}  "
                f"T+{int(state.time):03d}s  "
                f"CMB {combo_value}  {combo_text}"
            )
        else:
            self.meta_label.text = f"{str(getattr(state, 'difficulty', 'normal')).upper()}  T+{int(state.time):03d}s"

        # Status text
        max_chars = self._status_max_chars
        if len(status_text) > max_chars:
            status_text = status_text[: max(3, max_chars - 3)].rstrip() + "..."
        self.status_label.text = status_text

        # Score
        if score is not None:
            self.score_value_label.text = f"{score.score:,}"
            if score.combo > 1.05:
                self.combo_label.text = f"x{score.combo:.1f} COMBO"
                # Gold-orange pulsing as combo rises
                intensity = min(1.0, (score.combo - 1.0) / (6.0 - 1.0))
                g = int(200 - 80 * intensity)
                self.combo_label.color = (255, g, 80, 230)
            else:
                self.combo_label.text = ""
        else:
            self.score_value_label.text = "0"
            self.combo_label.text = ""

    def draw(self) -> None:
        self.batch.draw()
