"""Boss reward menu: temporary cards + permanent run boosts."""

from __future__ import annotations

from typing import Optional
import pyglet
from pyglet import shapes

from menu import MenuButton, _ui_scale, UI_FONT_HEAD, UI_FONT_BODY, UI_FONT_META


class BossRewardMenu:
    """Two-step reward menu shown after boss waves."""

    def __init__(self, width: int, height: int, on_pick_temp, on_pick_perm):
        self.screen_width = width
        self.screen_height = height
        self._on_pick_temp = on_pick_temp
        self._on_pick_perm = on_pick_perm
        self.batch = pyglet.graphics.Batch()

        self.overlay = shapes.Rectangle(0, 0, width, height, color=(6, 10, 18), batch=self.batch)
        self.overlay.opacity = 220
        self._panel_border = shapes.Rectangle(0, 0, 1, 1, color=(164, 214, 255), batch=self.batch)
        self._panel_border.opacity = 52
        self._panel = shapes.Rectangle(0, 0, 1, 1, color=(10, 20, 34), batch=self.batch)
        self._panel.opacity = 228
        self._panel_shine = shapes.Rectangle(0, 0, 1, 1, color=(255, 255, 255), batch=self.batch)
        self._panel_shine.opacity = 16

        self.title = pyglet.text.Label(
            "P L O U T O // BOSS REWARD",
            font_name=UI_FONT_HEAD,
            font_size=30,
            x=width // 2,
            y=height - 90,
            anchor_x="center",
            anchor_y="center",
            color=(230, 240, 255, 255),
            batch=self.batch,
        )
        self.subtitle = pyglet.text.Label(
            "",
            font_name=UI_FONT_BODY,
            font_size=14,
            x=width // 2,
            y=height - 128,
            anchor_x="center",
            anchor_y="center",
            color=(170, 185, 210, 255),
            batch=self.batch,
        )
        self.tip = pyglet.text.Label(
            "",
            font_name=UI_FONT_META,
            font_size=11,
            x=width // 2,
            y=height - 152,
            anchor_x="center",
            anchor_y="center",
            color=(145, 160, 190, 255),
            batch=self.batch,
        )

        self.buttons: list[MenuButton] = [
            MenuButton(0, 0, 300, 72, "Option 1", lambda: None, color=(36, 132, 186), hover_color=(86, 188, 236)),
            MenuButton(0, 0, 300, 72, "Option 2", lambda: None, color=(36, 132, 186), hover_color=(86, 188, 236)),
            MenuButton(0, 0, 300, 72, "Option 3", lambda: None, color=(36, 132, 186), hover_color=(86, 188, 236)),
        ]
        self.desc_labels: list[pyglet.text.Label] = []
        for _ in range(3):
            self.desc_labels.append(
                pyglet.text.Label(
                    "",
                    font_name=UI_FONT_META,
                    font_size=11,
                    x=0,
                    y=0,
                    anchor_x="left",
                    anchor_y="center",
                    color=(165, 175, 195, 255),
                    batch=self.batch,
                )
            )

        for b in self.buttons:
            b.ensure(self.batch)

        self._temp_opts: list[dict] = []
        self._perm_opts: list[dict] = []
        self._stage = "temp"
        self.resize(width, height)

    def begin(self, temp_options: list[dict], perm_options: list[dict]) -> None:
        self._temp_opts = list(temp_options or [])[:3]
        self._perm_opts = list(perm_options or [])[:3]
        self._stage = "temp"
        self._sync_stage_labels()
        self._sync_buttons()

    def _sync_stage_labels(self) -> None:
        if self._stage == "temp":
            self.subtitle.text = "Pick 1 Temporary Card (2-3 waves)"
            self.tip.text = "After this, you will pick 1 small permanent run boost."
        else:
            self.subtitle.text = "Pick 1 Permanent Run Boost"
            self.tip.text = "Applies for the rest of this run."

    def _sync_buttons(self) -> None:
        options = self._temp_opts if self._stage == "temp" else self._perm_opts
        while len(options) < 3:
            options.append({"key": "", "title": "--", "desc": ""})
        for i in range(3):
            opt = options[i]
            self.buttons[i].text = str(opt.get("title", "--"))
            self.desc_labels[i].text = str(opt.get("desc", ""))
            self.buttons[i].sync()

    def resize(self, width: int, height: int):
        self.screen_width = width
        self.screen_height = height
        self.overlay.width = width
        self.overlay.height = height
        cx = width // 2
        cy = height // 2
        scale = min(_ui_scale(width, height), 1.45)

        panel_w = min(int(width * 0.9), int(980 * scale))
        panel_h = min(int(height * 0.82), int(520 * scale))
        panel_x = cx - panel_w // 2
        panel_y = cy - panel_h // 2

        self._panel_border.x = panel_x - 3
        self._panel_border.y = panel_y - 3
        self._panel_border.width = panel_w + 6
        self._panel_border.height = panel_h + 6
        self._panel.x = panel_x
        self._panel.y = panel_y
        self._panel.width = panel_w
        self._panel.height = panel_h
        self._panel_shine.x = panel_x + 4
        self._panel_shine.y = panel_y + panel_h - max(8, int(22 * scale))
        self._panel_shine.width = panel_w - 8
        self._panel_shine.height = max(6, int(14 * scale))

        self.title.x = cx
        self.title.y = panel_y + panel_h - int(54 * scale)
        self.title.font_size = max(18, int(31 * scale))
        self.subtitle.x = cx
        self.subtitle.y = self.title.y - int(34 * scale)
        self.subtitle.font_size = max(11, int(14 * scale))
        self.tip.x = cx
        self.tip.y = self.subtitle.y - int(24 * scale)
        self.tip.font_size = max(9, int(11 * scale))

        bw = min(int(panel_w * 0.84), int(680 * scale))
        bh = int(78 * scale)
        gap = int(16 * scale)
        y0 = self.tip.y - int(54 * scale) - bh
        for i, btn in enumerate(self.buttons):
            btn.width = bw
            btn.height = bh
            btn.font_size = max(12, int(17 * scale))
            btn.x = cx - bw // 2
            btn.y = y0 - i * (bh + gap)
            btn.sync()
            self.desc_labels[i].x = btn.x + int(12 * scale)
            self.desc_labels[i].y = btn.y + int(bh * 0.28)
            self.desc_labels[i].font_size = max(9, int(11 * scale))

    def on_mouse_motion(self, x: float, y: float):
        for btn in self.buttons:
            btn.is_hovered = btn.contains_point(x, y)
            btn.sync()

    def on_mouse_press(self, x: float, y: float, button: int) -> Optional[str]:
        if button != pyglet.window.mouse.LEFT:
            return None
        options = self._temp_opts if self._stage == "temp" else self._perm_opts
        for i, btn in enumerate(self.buttons):
            if not btn.contains_point(x, y):
                continue
            if i >= len(options):
                return None
            chosen = options[i]
            key = str(chosen.get("key", "")).strip()
            if not key:
                return None
            if self._stage == "temp":
                duration = int(chosen.get("duration", 2))
                self._on_pick_temp(key, duration)
                self._stage = "perm"
                self._sync_stage_labels()
                self._sync_buttons()
                return None
            self._on_pick_perm(key)
            return "done"
        return None

    def draw(self):
        for b in self.buttons:
            b.sync()
        self.batch.draw()
