"""Menu system for game configuration and navigation."""

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import TYPE_CHECKING, List, Optional
import math
import random
import pyglet
from pyglet import shapes
import config
from fonts import register_ui_fonts

register_ui_fonts()

UI_FONT_HEAD = "Orbitron"
UI_FONT_BODY = "Rajdhani"
UI_FONT_META = "Rajdhani"


def _ui_scale(width: int, height: int) -> float:
    """Responsive UI scale factor based on window size."""
    base_w, base_h = 980.0, 620.0
    s = min(max(1.0, float(width)) / base_w, max(1.0, float(height)) / base_h)
    return max(0.85, min(1.85, s))


def _sync_label_style_if_ready(label, font_name: str, font_size: int) -> None:
    """Avoid pyglet font style updates when GL context is temporarily unavailable."""
    from pyglet import gl
    if getattr(gl, "current_context", None) is None:
        return
    if getattr(label, "font_name", None) != font_name:
        label.font_name = font_name
    if int(getattr(label, "font_size", 0)) != int(font_size):
        label.font_size = int(font_size)


@dataclass
class MenuButton:
    """A clickable button on the menu."""
    x: float
    y: float
    width: float
    height: float
    text: str
    callback: Callable
    color: tuple = (100, 150, 200)
    hover_color: tuple = (150, 200, 255)
    font_name: str = UI_FONT_BODY
    font_size: int = 16
    text_color: tuple = (255, 255, 255, 255)
    is_hovered: bool = False

    _batch: object = field(init=False, default=None, repr=False)
    _shadow: object = field(init=False, default=None, repr=False)
    _border: object = field(init=False, default=None, repr=False)
    _bg: object = field(init=False, default=None, repr=False)
    _shine: object = field(init=False, default=None, repr=False)
    _label: object = field(init=False, default=None, repr=False)
    
    def contains_point(self, px: float, py: float) -> bool:
        """Check if point is inside button."""
        return self.x <= px <= self.x + self.width and self.y <= py <= self.y + self.height

    def ensure(self, batch: pyglet.graphics.Batch) -> None:
        if self._batch is batch and self._bg is not None:
            return
        self._batch = batch
        self._shadow = shapes.Rectangle(0, 0, 1, 1, color=(0, 0, 0), batch=batch)
        self._shadow.opacity = 72
        self._border = shapes.Rectangle(0, 0, 1, 1, color=(185, 220, 255), batch=batch)
        self._bg = shapes.Rectangle(0, 0, 1, 1, color=self.color, batch=batch)
        self._shine = shapes.Rectangle(0, 0, 1, 1, color=(255, 255, 255), batch=batch)
        self._label = pyglet.text.Label(
            self.text,
            font_name=self.font_name,
            font_size=self.font_size,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            batch=batch,
            color=self.text_color,
        )
        self.sync()

    def sync(self) -> None:
        if self._bg is None:
            return
        color = self.hover_color if self.is_hovered else self.color
        shadow_off = max(2, int(self.height * 0.07))
        border_pad = max(2, int(self.height * 0.06))
        shine_h = max(3, int(self.height * 0.14))

        self._shadow.x = self.x + shadow_off
        self._shadow.y = self.y - shadow_off
        self._shadow.width = self.width
        self._shadow.height = self.height

        self._border.x = self.x - border_pad
        self._border.y = self.y - border_pad
        self._border.width = self.width + border_pad * 2
        self._border.height = self.height + border_pad * 2
        self._border.opacity = 86 if self.is_hovered else 32

        self._bg.x = self.x
        self._bg.y = self.y
        self._bg.width = self.width
        self._bg.height = self.height
        self._bg.color = color
        self._bg.opacity = 245 if self.is_hovered else 214

        self._shine.x = self.x + 2
        self._shine.y = self.y + self.height - shine_h - 2
        self._shine.width = max(1, self.width - 4)
        self._shine.height = shine_h
        self._shine.opacity = 70 if self.is_hovered else 24

        self._label.text = self.text
        _sync_label_style_if_ready(self._label, self.font_name, int(self.font_size))
        self._label.x = self.x + self.width // 2
        self._label.y = self.y + self.height // 2

    def delete(self) -> None:
        for o in (self._shadow, self._border, self._bg, self._shine, self._label):
            if o is None:
                continue
            if hasattr(o, "delete"):
                o.delete()
        self._batch = None
        self._shadow = None
        self._border = None
        self._bg = None
        self._shine = None
        self._label = None


@dataclass
class MenuSlider:
    """A slider control for numeric settings."""
    x: float
    y: float
    width: float
    label: str
    min_val: float
    max_val: float
    current_val: float
    callback: Callable
    is_dragging: bool = False
    font_name: str = UI_FONT_BODY
    font_size: int = 14
    knob_radius: float = 8.0
    track_thickness: float = 2.0
    value_fmt: str = "{:.0f}"
    value_suffix: str = ""

    _batch: object = field(init=False, default=None, repr=False)
    _label_obj: object = field(init=False, default=None, repr=False)
    _track_shadow: object = field(init=False, default=None, repr=False)
    _track: object = field(init=False, default=None, repr=False)
    _knob_back: object = field(init=False, default=None, repr=False)
    _knob: object = field(init=False, default=None, repr=False)
    
    def get_knob_x(self) -> float:
        """Calculate knob position based on current value."""
        ratio = (self.current_val - self.min_val) / (self.max_val - self.min_val)
        return self.x + (ratio * self.width)
    
    def set_value_from_x(self, px: float):
        """Set value based on x position."""
        ratio = max(0, min(1, (px - self.x) / self.width))
        self.current_val = self.min_val + (ratio * (self.max_val - self.min_val))
        self.callback(self.current_val)
    
    def contains_knob(self, px: float, py: float) -> bool:
        """Check if point is on the knob."""
        knob_x = self.get_knob_x()
        r = float(self.knob_radius)
        return (abs(px - knob_x) <= r and abs(py - self.y) <= r)
    
    def draw(self, batch) -> list:
        """Draw slider and return list of visual objects."""
        # Backwards compat: keep `draw(batch)` but make it persistent.
        self.ensure(batch)
        self.sync()
        return [o for o in (self._label_obj, self._track_shadow, self._track, self._knob_back, self._knob) if o is not None]

    def ensure(self, batch: pyglet.graphics.Batch) -> None:
        if self._batch is batch and self._track is not None:
            return
        self._batch = batch
        self._label_obj = pyglet.text.Label(
            "",
            font_name=self.font_name,
            font_size=self.font_size,
            x=0,
            y=0,
            anchor_x="left",
            anchor_y="bottom",
            batch=batch,
            color=(255, 255, 255, 255),
        )
        self._track_shadow = shapes.Line(0, 0, 0, 0, thickness=1.0, color=(0, 0, 0), batch=batch)
        self._track_shadow.opacity = 90
        self._track = shapes.Line(0, 0, 0, 0, thickness=1.0, color=(120, 130, 155), batch=batch)
        self._track.opacity = 160
        self._knob_back = shapes.Circle(0, 0, self.knob_radius + 3, color=(255, 255, 255), batch=batch)
        self._knob_back.opacity = 55
        self._knob = shapes.Circle(0, 0, self.knob_radius, color=(130, 190, 240), batch=batch)
        self._knob.opacity = 240
        self.sync()

    def sync(self) -> None:
        if self._track is None:
            return
        val_str = self.value_fmt.format(self.current_val)
        self._label_obj.text = f"{self.label}: {val_str}{self.value_suffix}"
        _sync_label_style_if_ready(self._label_obj, self.font_name, int(self.font_size))
        self._label_obj.x = self.x
        self._label_obj.y = self.y + 20

        thickness_shadow = max(1.0, float(self.track_thickness) + 3.0)
        self._track_shadow.x = self.x
        self._track_shadow.y = self.y
        self._track_shadow.x2 = self.x + self.width
        self._track_shadow.y2 = self.y
        self._track_shadow.thickness = thickness_shadow

        self._track.x = self.x
        self._track.y = self.y
        self._track.x2 = self.x + self.width
        self._track.y2 = self.y
        self._track.thickness = float(self.track_thickness)

        knob_x = self.get_knob_x()
        self._knob_back.x = knob_x
        self._knob_back.y = self.y
        self._knob_back.radius = float(self.knob_radius + 3)

        self._knob.x = knob_x
        self._knob.y = self.y
        self._knob.radius = float(self.knob_radius)
        self._knob.color = (150, 210, 255) if self.is_dragging else (130, 190, 240)


class Menu:
    """Main menu screen."""
    
    def __init__(self, width: int, height: int):
        self.screen_width = width
        self.screen_height = height
        self.batch = pyglet.graphics.Batch()
        self._t = 0.0
        self._title_base_y = 0.0
        self._button_base_positions: list[tuple[float, float]] = []
        self._orbs: list[tuple[shapes.Circle, float, float, float]] = []

        self._bg_a = shapes.Rectangle(0, 0, width, height, color=(9, 16, 26), batch=self.batch)
        self._bg_b = shapes.Rectangle(0, 0, width, height, color=(6, 10, 18), batch=self.batch)
        self._bg_b.opacity = 148

        count = max(10, min(22, int((width * height) / 90_000)))
        for _ in range(count):
            r = random.uniform(18, 55)
            x = random.uniform(0, width)
            y = random.uniform(0, height)
            col = random.choice([(40, 115, 170), (180, 92, 130), (70, 165, 150)])
            orb = shapes.Circle(x, y, r, color=col, batch=self.batch)
            orb.opacity = random.randint(14, 36)
            vx = random.uniform(-14, 14)
            vy = random.uniform(-10, 10)
            phase = random.uniform(0, math.tau)
            self._orbs.append((orb, vx, vy, phase))

        # Panel backing for buttons.
        self._panel_border = shapes.Rectangle(0, 0, 1, 1, color=(155, 205, 255), batch=self.batch)
        self._panel_border.opacity = 48
        self._panel = shapes.Rectangle(0, 0, 1, 1, color=(10, 20, 34), batch=self.batch)
        self._panel.opacity = 196
        self._panel_shine = shapes.Rectangle(0, 0, 1, 1, color=(255, 255, 255), batch=self.batch)
        self._panel_shine.opacity = 16

        self.buttons: list[MenuButton] = []
        self.buttons.append(MenuButton(0, 0, 160, 50, "Start Game", lambda: None, color=(45, 170, 125), hover_color=(80, 220, 160)))
        self.buttons.append(MenuButton(0, 0, 160, 50, "Guide", lambda: None, color=(120, 95, 220), hover_color=(162, 136, 255)))
        self.buttons.append(MenuButton(0, 0, 160, 50, "Settings", lambda: None, color=(70, 125, 220), hover_color=(105, 170, 255)))
        self.buttons.append(MenuButton(0, 0, 160, 50, "Quit", lambda: None, color=(200, 70, 90), hover_color=(245, 95, 120)))

        self.title = pyglet.text.Label(
            "P L O U T O",
            font_name=UI_FONT_HEAD,
            font_size=32,
            x=width // 2,
            y=height - 80,
            anchor_x="center",
            anchor_y="center",
            color=(224, 236, 255, 255),
            batch=self.batch,
        )

        self.subtitle = pyglet.text.Label(
            "Stellar Survival Protocol",
            font_name=UI_FONT_META,
            font_size=12,
            x=width // 2,
            y=height - 120,
            anchor_x="center",
            anchor_y="center",
            width=max(320, width - 64),
            multiline=True,
            align="center",
            color=(166, 184, 202, 255),
            batch=self.batch,
        )

        for btn in self.buttons:
            btn.ensure(self.batch)
        self.resize(width, height)

    def update(self, dt: float):
        self._t += dt
        w = self.screen_width
        h = self.screen_height
        for orb, vx, vy, phase in self._orbs:
            orb.x += vx * dt
            orb.y += vy * dt
            if orb.x < -60:
                orb.x = w + 60
            elif orb.x > w + 60:
                orb.x = -60
            if orb.y < -60:
                orb.y = h + 60
            elif orb.y > h + 60:
                orb.y = -60
            orb.opacity = int(14 + 18 * (0.5 + 0.5 * math.sin(self._t * 0.7 + phase)))

        # Subtle, continuous menu motion to keep the screen feeling alive.
        self.title.y = int(self._title_base_y + math.sin(self._t * 1.2) * 6.0)
        self._panel_shine.opacity = int(10 + 16 * (0.5 + 0.5 * math.sin(self._t * 1.45)))
        for i, btn in enumerate(self.buttons):
            if i >= len(self._button_base_positions):
                continue
            base_x, base_y = self._button_base_positions[i]
            wave = math.sin(self._t * 2.15 + i * 0.58)
            btn.x = base_x + int(wave * 4.0)
            btn.y = base_y + int(wave * 2.0)
            btn.sync()

    def resize(self, width: int, height: int):
        self.screen_width = width
        self.screen_height = height
        cx = width // 2
        cy = height // 2
        scale = _ui_scale(width, height)

        button_w = int(230 * scale)
        button_h = int(62 * scale)
        gap = int(18 * scale)
        font = max(12, int(18 * scale))
        for btn in self.buttons:
            btn.width = button_w
            btn.height = button_h
            btn.font_size = font

        total_h = len(self.buttons) * button_h + (len(self.buttons) - 1) * gap
        start_y = cy + total_h // 2 - button_h
        for i, btn in enumerate(self.buttons):
            btn.x = cx - button_w // 2
            btn.y = start_y - i * (button_h + gap)
            btn.sync()
        self._button_base_positions = [(btn.x, btn.y) for btn in self.buttons]

        # Panel size wraps buttons with padding.
        pad_x = int(70 * scale)
        pad_y = int(55 * scale)
        panel_w = button_w + pad_x * 2
        panel_h = total_h + pad_y * 2
        panel_x = cx - panel_w // 2
        panel_y = cy - panel_h // 2 - int(10 * scale)
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
        self._panel_shine.height = max(6, int(16 * scale))

        self.title.x = cx
        _sync_label_style_if_ready(self.title, UI_FONT_HEAD, max(22, int(38 * scale)))
        self.title.y = height - int(85 * scale)
        self._title_base_y = self.title.y
        self.subtitle.x = cx
        _sync_label_style_if_ready(self.subtitle, UI_FONT_META, max(10, int(13 * scale)))
        self.subtitle.y = height - int(130 * scale)
        self.subtitle.width = max(320, width - 64)

        self._bg_a.width = width
        self._bg_a.height = height
        self._bg_b.width = width
        self._bg_b.height = height
    
    def on_mouse_motion(self, x: float, y: float):
        """Handle mouse motion for button hover."""
        for button in self.buttons:
            button.is_hovered = button.contains_point(x, y)
            button.sync()
    
    def on_mouse_press(self, x: float, y: float, button: int) -> str | None:
        """Handle mouse clicks. Returns action string or None."""
        if button != pyglet.window.mouse.LEFT:
            return None
        
        for btn in self.buttons:
            if btn.contains_point(x, y):
                btn.callback()
                if btn.text == "Start Game":
                    return "start_game"
                elif btn.text == "Guide":
                    return "guide"
                elif btn.text == "Settings":
                    return "settings"
                elif btn.text == "Quit":
                    return "quit"
        return None
    
    def draw(self):
        """Draw the menu."""
        self.batch.draw()


class SettingsMenu:
    """Settings screen with difficulty and window size options."""
    
    def __init__(
        self,
        width: int,
        height: int,
        on_save: Callable,
        display_size: tuple[int, int] | None = None,
        advanced_fx_enabled: bool | None = None,
    ):
        self.screen_width = width
        self.screen_height = height
        self.on_save = on_save
        self.batch = pyglet.graphics.Batch()
        self._t = 0.0
        self._orbs: list[tuple[shapes.Circle, float, float, float]] = []

        self._bg_a = shapes.Rectangle(0, 0, width, height, color=(10, 12, 20), batch=self.batch)
        self._bg_b = shapes.Rectangle(0, 0, width, height, color=(6, 7, 14), batch=self.batch)
        self._bg_b.opacity = 130

        count = max(8, min(18, int((width * height) / 120_000)))
        for _ in range(count):
            r = random.uniform(16, 44)
            x = random.uniform(0, width)
            y = random.uniform(0, height)
            col = random.choice([(35, 70, 120), (90, 60, 140), (55, 105, 150)])
            orb = shapes.Circle(x, y, r, color=col, batch=self.batch)
            orb.opacity = random.randint(10, 26)
            vx = random.uniform(-10, 10)
            vy = random.uniform(-8, 8)
            phase = random.uniform(0, math.tau)
            self._orbs.append((orb, vx, vy, phase))

        # Panel backing for the settings content.
        self._panel_border = shapes.Rectangle(0, 0, 1, 1, color=(130, 160, 230), batch=self.batch)
        self._panel_border.opacity = 34
        self._panel = shapes.Rectangle(0, 0, 1, 1, color=(14, 18, 28), batch=self.batch)
        self._panel.opacity = 190
        self._panel_shine = shapes.Rectangle(0, 0, 1, 1, color=(255, 255, 255), batch=self.batch)
        self._panel_shine.opacity = 14
        
        # Settings
        self.difficulty = 1  # 0=easy, 1=normal, 2=hard
        self.arena_margin = float(getattr(config, "ARENA_MARGIN", 0.97))
        self.arena_pct = float(round(self.arena_margin * 100.0))
        self.advanced_fx = bool(getattr(config, "ENABLE_ADVANCED_FX", True) if advanced_fx_enabled is None else advanced_fx_enabled)
        self.window_size_idx = 0
        self.window_sizes, self.window_size_names = self._build_window_size_options(display_size)
        current_size = (int(width), int(height))
        if current_size[0] > 0 and current_size[1] > 0 and current_size not in self.window_sizes:
            self.window_sizes.append(current_size)
            self.window_size_names.append(f"{current_size[0]}x{current_size[1]}")
        self.window_sizes.append(None)
        self.window_size_names.append("Fullscreen")
        try:
            self.window_size_idx = self.window_sizes.index(current_size)
        except ValueError:
            self.window_size_idx = self._nearest_window_size_idx(current_size)
        
        # Difficulty buttons
        self.difficulty_buttons = []
        for i, name in enumerate(["Easy", "Normal", "Hard"]):
            btn = MenuButton(
                0,
                0,
                150,
                50,
                name,
                lambda d=i: self._set_difficulty(d),
                color=(100, 150, 200),
            )
            self.difficulty_buttons.append(btn)
        
        # Window size buttons
        self.size_buttons = []
        for i, name in enumerate(self.window_size_names):
            btn = MenuButton(
                0,
                0,
                150,
                50,
                name,
                lambda s=i: self._set_window_size(s),
                color=(100, 150, 200),
            )
            self.size_buttons.append(btn)
        
        # Arena size slider (controls arena fit within the viewport).
        self.arena_slider = MenuSlider(
            0,
            0,
            280,
            "Arena Size",
            90,
            99,
            self.arena_pct,
            lambda v: self._set_arena_pct(v),
            value_suffix="%",
        )
        
        # Back button
        self.back_button = MenuButton(0, 20, 160, 50, "Back to Menu", lambda: None, color=(100, 100, 150))
        
        self.title = pyglet.text.Label(
            "SETTINGS",
            font_name=UI_FONT_HEAD,
            font_size=28,
            x=width // 2,
            y=height - 40,
            anchor_x="center",
            anchor_y="center",
            color=(200, 220, 255, 255),
            batch=self.batch,
        )
        
        self.difficulty_label = pyglet.text.Label(
            "Difficulty",
            font_name=UI_FONT_BODY,
            font_size=16,
            x=150,
            y=height // 2 + 100,
            anchor_x="left",
            anchor_y="center",
            color=(255, 255, 255, 255),
            batch=self.batch,
        )
        
        self.window_label = pyglet.text.Label(
            "Display Mode",
            font_name=UI_FONT_BODY,
            font_size=16,
            x=0,
            y=height // 2 - 10,
            anchor_x="left",
            anchor_y="center",
            color=(255, 255, 255, 255),
            batch=self.batch,
        )
        self.fx_label = pyglet.text.Label(
            "Advanced FX",
            font_name=UI_FONT_BODY,
            font_size=16,
            x=0,
            y=0,
            anchor_x="left",
            anchor_y="center",
            color=(255, 255, 255, 255),
            batch=self.batch,
        )
        self.fx_button = MenuButton(0, 0, 210, 50, "", self._toggle_advanced_fx, color=(82, 122, 180), hover_color=(112, 156, 220))
        self._refresh_fx_button_text()
        self.menu_note = pyglet.text.Label(
            "Resolution, arena scale, and FX mode update instantly.",
            font_name=UI_FONT_META,
            font_size=11,
            x=width // 2,
            y=height - 72,
            anchor_x="center",
            anchor_y="center",
            color=(165, 175, 195, 255),
            batch=self.batch,
        )

        self._selected_diff_highlight = shapes.Rectangle(0, 0, 1, 1, color=(255, 255, 255), batch=self.batch)
        self._selected_diff_highlight.opacity = 60
        self._selected_size_highlight = shapes.Rectangle(0, 0, 1, 1, color=(255, 255, 255), batch=self.batch)
        self._selected_size_highlight.opacity = 60

        for btn in self.difficulty_buttons + self.size_buttons + [self.fx_button, self.back_button]:
            btn.ensure(self.batch)
        self.arena_slider.ensure(self.batch)

        self.resize(width, height)

    def _build_window_size_options(self, display_size: tuple[int, int] | None) -> tuple[list[tuple[int, int]], list[str]]:
        # Modern defaults focused on common desktop 16:9/16:10 resolutions.
        common = [
            (1280, 720),
            (1366, 768),
            (1600, 900),
            (1920, 1080),
            (2560, 1440),
            (3440, 1440),
            (3840, 2160),
        ]

        sizes: list[tuple[int, int]] = []
        names: list[str] = []
        seen = set()

        native = None
        if display_size:
            dw, dh = int(display_size[0]), int(display_size[1])
            if dw > 0 and dh > 0:
                native = (dw, dh)

        for w, h in common:
            if native and (w > native[0] or h > native[1]):
                continue
            key = (w, h)
            if key in seen:
                continue
            seen.add(key)
            sizes.append(key)
            names.append(f"{w}x{h} ({self._aspect_label(w, h)})")

        if native and native not in seen:
            sizes.append(native)
            names.append(f"{native[0]}x{native[1]} ({self._aspect_label(native[0], native[1])}, Native)")

        if not sizes:
            sizes = [(1280, 720)]
            names = ["1280x720 (16:9)"]

        return sizes, names

    def _nearest_window_size_idx(self, current_size: tuple[int, int]) -> int:
        if not self.window_sizes:
            return 0
        cw, ch = int(current_size[0]), int(current_size[1])
        if cw <= 0 or ch <= 0:
            return 0
        c_area = cw * ch
        best_i = 0
        best_score = None
        for i, sz in enumerate(self.window_sizes):
            if sz is None:
                continue
            w, h = int(sz[0]), int(sz[1])
            score = abs((w * h) - c_area) + abs(w - cw) * 20 + abs(h - ch) * 20
            if best_score is None or score < best_score:
                best_score = score
                best_i = i
        return best_i

    @staticmethod
    def _aspect_label(w: int, h: int) -> str:
        if h <= 0:
            return "?"
        r = float(w) / float(h)
        if abs(r - (16 / 9)) < 0.03:
            return "16:9"
        if abs(r - (16 / 10)) < 0.03:
            return "16:10"
        if abs(r - (21 / 9)) < 0.05:
            return "21:9"
        if abs(r - (4 / 3)) < 0.03:
            return "4:3"
        return f"{r:.2f}:1"

    def update(self, dt: float):
        self._t += dt
        w = self.screen_width
        h = self.screen_height
        for orb, vx, vy, phase in self._orbs:
            orb.x += vx * dt
            orb.y += vy * dt
            if orb.x < -60:
                orb.x = w + 60
            elif orb.x > w + 60:
                orb.x = -60
            if orb.y < -60:
                orb.y = h + 60
            elif orb.y > h + 60:
                orb.y = -60
            orb.opacity = int(10 + 16 * (0.5 + 0.5 * math.sin(self._t * 0.7 + phase)))

    def resize(self, width: int, height: int):
        self.screen_width = width
        self.screen_height = height
        cx = width // 2
        # Settings has denser content than other menus; cap scale to avoid crowding.
        scale = min(_ui_scale(width, height), 1.26)

        panel_top_pad = int(96 * scale)
        panel_y = max(14, int(18 * scale))
        panel_w = min(int(width * 0.92), int(1100 * scale))
        panel_h = max(280, int(height - panel_top_pad - panel_y))
        panel_x = cx - panel_w // 2
        self._panel_border.x = panel_x - 3
        self._panel_border.y = panel_y - 3
        self._panel_border.width = panel_w + 6
        self._panel_border.height = panel_h + 6
        self._panel.x = panel_x
        self._panel.y = panel_y
        self._panel.width = panel_w
        self._panel.height = panel_h
        self._panel_shine.x = panel_x + 4
        self._panel_shine.y = panel_y + panel_h - max(8, int(20 * scale))
        self._panel_shine.width = panel_w - 8
        self._panel_shine.height = max(6, int(14 * scale))

        content_pad_x = int(32 * scale)
        content_left = panel_x + content_pad_x
        content_right = panel_x + panel_w - content_pad_x
        content_w = max(240, content_right - content_left)
        content_top = panel_y + panel_h - int(44 * scale)

        button_h = int(52 * scale)
        base_btn_w = int(180 * scale)
        btn_font = max(11, int(15 * scale))
        gap_x = max(10, int(14 * scale))
        gap_y = max(8, int(12 * scale))

        # Difficulty row aligned to the content grid.
        diff_btn_w = max(int(120 * scale), min(base_btn_w, int((content_w - gap_x * 2) / 3)))
        for btn in self.difficulty_buttons:
            btn.width = diff_btn_w
            btn.height = button_h
            btn.font_size = btn_font
        _sync_label_style_if_ready(self.difficulty_label, UI_FONT_BODY, max(12, int(17 * scale)))
        self.difficulty_label.x = content_left
        self.difficulty_label.y = content_top

        diff_y = self.difficulty_label.y - int(18 * scale) - button_h
        diff_total_w = 3 * diff_btn_w + 2 * gap_x
        diff_start_x = content_left + max(0, (content_w - diff_total_w) // 2)
        for i, btn in enumerate(self.difficulty_buttons):
            btn.x = diff_start_x + i * (diff_btn_w + gap_x)
            btn.y = diff_y

        # Display options in an adaptive grid to keep spacing stable across resolutions.
        size_cols = 3 if content_w >= int(640 * scale) else 2 if content_w >= int(430 * scale) else 1
        size_btn_w = max(int(120 * scale), min(int((content_w - gap_x * (size_cols - 1)) / size_cols), int(280 * scale)))
        for btn in self.size_buttons:
            btn.width = size_btn_w
            btn.height = button_h
            btn.font_size = btn_font

        _sync_label_style_if_ready(self.window_label, UI_FONT_BODY, max(12, int(17 * scale)))
        self.window_label.x = content_left
        self.window_label.y = diff_y - int(58 * scale)

        size_top_y = self.window_label.y - int(18 * scale) - button_h
        for i, btn in enumerate(self.size_buttons):
            col = i % size_cols
            row = i // size_cols
            btn.x = content_left + col * (size_btn_w + gap_x)
            btn.y = size_top_y - row * (button_h + gap_y)

        self.back_button.width = max(int(180 * scale), int(min(300 * scale, content_w * 0.42)))
        self.back_button.height = button_h
        self.back_button.font_size = btn_font
        self.back_button.x = cx - self.back_button.width // 2
        self.back_button.y = panel_y + int(18 * scale)

        _sync_label_style_if_ready(self.fx_label, UI_FONT_BODY, max(12, int(16 * scale)))
        self.fx_label.x = content_left
        self.fx_label.y = self.back_button.y + self.back_button.height + int(24 * scale)
        self.fx_button.width = max(int(190 * scale), int(min(340 * scale, content_w * 0.5)))
        self.fx_button.height = button_h
        self.fx_button.font_size = btn_font
        self.fx_button.x = content_left
        self.fx_button.y = self.fx_label.y - int(18 * scale) - button_h

        rows = max(1, (len(self.size_buttons) + size_cols - 1) // size_cols)
        grid_bottom = size_top_y - (rows - 1) * (button_h + gap_y)
        slider_floor_y = self.fx_button.y + self.fx_button.height + int(24 * scale)
        slider_pref_y = grid_bottom - int(68 * scale)
        self.arena_slider.x = content_left
        self.arena_slider.y = max(int(slider_floor_y), int(slider_pref_y))
        self.arena_slider.width = min(int(500 * scale), content_w)
        self.arena_slider.font_size = max(11, int(14 * scale))
        self.arena_slider.knob_radius = max(6.0, 9.0 * scale)
        self.arena_slider.track_thickness = max(2.0, 3.0 * scale)

        self.title.x = cx
        _sync_label_style_if_ready(self.title, UI_FONT_HEAD, max(18, int(32 * scale)))
        self.title.y = height - int(60 * scale)
        self.menu_note.x = cx
        self.menu_note.y = self.title.y - int(26 * scale)
        _sync_label_style_if_ready(self.menu_note, UI_FONT_META, max(9, int(11 * scale)))

        self._bg_a.width = width
        self._bg_a.height = height
        self._bg_b.width = width
        self._bg_b.height = height
    
    def _set_difficulty(self, level: int):
        """Set difficulty level."""
        self.difficulty = level
        self.on_save(self.get_settings())
    
    def _set_arena_pct(self, val: float):
        v = float(val)
        v = max(90.0, min(99.0, v))
        self.arena_pct = v
        self.arena_margin = v / 100.0
        self.on_save(self.get_settings())
    
    def _set_window_size(self, idx: int):
        """Set window size."""
        self.window_size_idx = idx
        self.on_save(self.get_settings())

    def _refresh_fx_button_text(self):
        self.fx_button.text = f"Advanced FX: {'On' if self.advanced_fx else 'Off'}"
        self.fx_button.sync()

    def _toggle_advanced_fx(self):
        self.advanced_fx = not self.advanced_fx
        self._refresh_fx_button_text()
        self.on_save(self.get_settings())
    
    def on_mouse_motion(self, x: float, y: float):
        """Handle mouse motion for button hover."""
        for btn in self.difficulty_buttons + self.size_buttons + [self.fx_button, self.back_button]:
            btn.is_hovered = btn.contains_point(x, y)
            btn.sync()

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float):
        """Handle mouse drag for sliders."""
        if self.arena_slider.is_dragging:
            self.arena_slider.set_value_from_x(x)
            self.arena_slider.sync()
    
    def on_mouse_press(self, x: float, y: float, button: int) -> str | None:
        """Handle mouse clicks. Returns action string or None."""
        if button != pyglet.window.mouse.LEFT:
            return None
        
        if self.back_button.contains_point(x, y):
            self.on_save(self.get_settings())
            return "back"
        if self.fx_button.contains_point(x, y):
            self.fx_button.callback()
            return None
        
        for btn in self.difficulty_buttons + self.size_buttons:
            if btn.contains_point(x, y):
                btn.callback()
                return None
        
        if self.arena_slider.contains_knob(x, y) or (
            x >= self.arena_slider.x
            and x <= self.arena_slider.x + self.arena_slider.width
            and abs(y - self.arena_slider.y) < max(10, int(self.arena_slider.knob_radius + 4))
        ):
            self.arena_slider.is_dragging = True
            self.arena_slider.set_value_from_x(x)
            self.arena_slider.sync()
        
        return None
    
    def on_mouse_release(self, x: float, y: float, button: int):
        """Handle mouse release."""
        self.arena_slider.is_dragging = False
        self.arena_slider.sync()
    
    def get_settings(self) -> dict:
        """Get current settings."""
        difficulty_names = ["easy", "normal", "hard"]
        fullscreen = self.window_sizes[self.window_size_idx] is None
        return {
            "difficulty": difficulty_names[self.difficulty],
            "window_size": self.window_sizes[self.window_size_idx],
            "fullscreen": fullscreen,
            "arena_margin": float(self.arena_margin),
            "advanced_fx": bool(self.advanced_fx),
        }
    
    def draw(self):
        """Draw the settings menu."""
        # Keep highlights in sync with the selected buttons.
        if self.difficulty_buttons:
            selected_diff = self.difficulty_buttons[self.difficulty]
            self._selected_diff_highlight.x = selected_diff.x - 2
            self._selected_diff_highlight.y = selected_diff.y - 2
            self._selected_diff_highlight.width = selected_diff.width + 4
            self._selected_diff_highlight.height = selected_diff.height + 4
        if self.size_buttons:
            selected_size = self.size_buttons[self.window_size_idx]
            self._selected_size_highlight.x = selected_size.x - 2
            self._selected_size_highlight.y = selected_size.y - 2
            self._selected_size_highlight.width = selected_size.width + 4
            self._selected_size_highlight.height = selected_size.height + 4

        self._refresh_fx_button_text()
        for btn in self.difficulty_buttons + self.size_buttons + [self.fx_button, self.back_button]:
            btn.sync()
        self.arena_slider.sync()
        self.batch.draw()


class GuideMenu:
    """In-game encyclopedia for enemies and powerups."""

    ENEMY_INFO = [
        {"key": "chaser", "name": "Chaser", "icon": "CH", "what": "Rushes straight in for contact damage.", "deal": "Strafe and burst it before it reaches melee.", "lore": "Mass-produced hound drone tuned for reckless pursuit."},
        {"key": "ranged", "name": "Ranged", "icon": "RA", "what": "Holds distance and fires aimed shots.", "deal": "Pressure diagonally and break line-of-fire.", "lore": "A perimeter sentry rebuilt for arena suppression."},
        {"key": "charger", "name": "Charger", "icon": "CG", "what": "Telegraphs then commits to a hard dash.", "deal": "Sidestep late, then punish recovery frames.", "lore": "Impact frame with overclocked thrusters and no brakes."},
        {"key": "swarm", "name": "Swarm", "icon": "SW", "what": "Light units that collapse from flanks.", "deal": "Keep moving and clear packs with spread fire.", "lore": "Fragment drones sharing a low-latency hive link."},
        {"key": "tank", "name": "Tank", "icon": "TK", "what": "Slow frontliner with heavy durability.", "deal": "Kite and remove escorts before full commit.", "lore": "Siege chassis repurposed as a living shield."},
        {"key": "spitter", "name": "Spitter", "icon": "SP", "what": "Lobs corrosive volleys on medium arc.", "deal": "Approach from offsets; never stand still.", "lore": "Bio-mech mortar node seeded with toxic payloads."},
        {"key": "flyer", "name": "Flyer", "icon": "FL", "what": "Fast skirmisher with erratic aerial arcs.", "deal": "Lead shots ahead of movement, not at center.", "lore": "Recon interceptor tuned for vector feints."},
        {"key": "engineer", "name": "Engineer", "icon": "EN", "what": "Deploys hazards and stabilizes enemy tempo.", "deal": "Prioritize early to stop area denial setups.", "lore": "Autonomous field tech that weaponizes terrain."},
        {"key": "bomber", "name": "Bomber", "icon": "BM", "what": "Throws bombs that detonate on timer/impact.", "deal": "Bait throws, disengage, then re-enter safely.", "lore": "A demolition core with unstable combustion cells."},
        {"key": "boss_thunder", "name": "Boss: Thunder", "icon": "BT", "what": "Marks lines then detonates lightning lanes.", "deal": "Respect warning lanes and rotate outward.", "lore": "Storm-routing sovereign running a cracked weather array."},
        {"key": "boss_laser", "name": "Boss: Laser", "icon": "BL", "what": "Sweeping beams plus burst volleys.", "deal": "Play near beam edges and dash through gaps.", "lore": "An orbital cutter node dropped into close quarters."},
        {"key": "boss_trapmaster", "name": "Boss: Trapmaster", "icon": "TM", "what": "Seeds arena zones with trap timings.", "deal": "Track safe tiles; avoid panic pathing.", "lore": "Custodian AI that turned maintenance grids into snares."},
        {"key": "boss_swarmqueen", "name": "Boss: Swarmqueen", "icon": "SQ", "what": "Floods field with coordinated adds.", "deal": "Cut adds quickly to deny snowball pressure.", "lore": "Hive-mother process commanding distributed micro-drones."},
        {"key": "boss_brute", "name": "Boss: Brute", "icon": "BR", "what": "Close-range slams and brawler bursts.", "deal": "Stay mobile and punish post-slam windows.", "lore": "Execution platform stripped to raw kinetic violence."},
        {"key": "boss_abyss_gaze", "name": "Boss: Abyss Gaze", "icon": "AG", "what": "Dark pulse patterns and pressure rings.", "deal": "Keep spacing disciplined; avoid center traps.", "lore": "A deep-scan optic that learned predation."},
        {"key": "boss_womb_core", "name": "Boss: Womb Core", "icon": "WC", "what": "Spawns adds and compresses safe zones.", "deal": "Clear adds fast; save burst for pulse gaps.", "lore": "A growth reactor that treats battle as incubation."},
    ]
    POWERUP_INFO = [
        {"key": "heal", "name": "Heal (+)", "icon": "+", "what": "Restores HP instantly.", "deal": "Grab when low; avoid wasting near full HP.", "lore": "Nanite med-gel distilled from station triage kits."},
        {"key": "damage", "name": "Damage (!)", "icon": "!", "what": "Permanent run damage increase.", "deal": "Best early pickup for faster clears.", "lore": "Illegal coil tuning for hotter impact loads."},
        {"key": "speed", "name": "Speed (>)", "icon": ">", "what": "Permanent move speed increase.", "deal": "Helps dodging and formation repositioning.", "lore": "Servo firmware patch from courier exo-rigs."},
        {"key": "firerate", "name": "Fire Rate (*)", "icon": "*", "what": "Shots come out faster.", "deal": "Scales best with precise tracking.", "lore": "Trigger logic rewrite with fewer safety checks."},
        {"key": "shield", "name": "Shield (O)", "icon": "O", "what": "Adds shield buffer HP.", "deal": "Take before risky boss phases.", "lore": "Phase-shell capacitor from obsolete defense satellites."},
        {"key": "laser", "name": "Laser (=)", "icon": "=", "what": "Temporary beam mode.", "deal": "Line enemies up for efficient burns.", "lore": "Prototype mining beam rerouted for combat duty."},
        {"key": "vortex", "name": "Vortex (@)", "icon": "@", "what": "Temporary damaging aura around you.", "deal": "Play aggressively but keep exits open.", "lore": "Collapsed singularity shard in a containment ring."},
        {"key": "weapon", "name": "Weapon (W)", "icon": "W", "what": "Switches current weapon pattern.", "deal": "Adapt playstyle to the new spread/tempo.", "lore": "Recovered armament cache from dead merc squads."},
        {"key": "ultra", "name": "Ultra (U)", "icon": "U", "what": "Adds an Ultra charge for RMB/Q.", "deal": "Spend on boss spikes or dangerous swarms.", "lore": "A forbidden core spark meant for ship cannons."},
    ]
    BASICS_INFO = [
        {"key": "move", "name": "Movement", "icon": "MV", "what": "Use WASD or Arrow keys to move.", "deal": "Stay moving; linear retreats get punished.", "lore": "Mobility is your main defense layer."},
        {"key": "fire", "name": "Primary Fire", "icon": "LMB", "what": "LMB toggles auto-fire on/off.", "deal": "Keep auto-fire on, then focus on dodging and spacing.", "lore": "Auto-fire replaced hold-to-fire pacing."},
        {"key": "dash", "name": "Dash", "icon": "SP", "what": "Press SPACE to dash through pressure.", "deal": "Save dash for layered patterns, not chip damage.", "lore": "Dash timing decides most boss survivability windows."},
        {"key": "ultra_use", "name": "Ultra Use", "icon": "U!", "what": "RMB or Q consumes one Ultra charge.", "deal": "Use Ultra during spike phases or add floods.", "lore": "Ultra is burst control, not passive DPS."},
        {"key": "arena", "name": "Arena Control", "icon": "AR", "what": "Fight near edge lanes, avoid center traps.", "deal": "Rotate clockwise/counter-clockwise with intent.", "lore": "Bad pathing is deadlier than low HP."},
        {"key": "loot", "name": "Loot Priority", "icon": "LT", "what": "Powerups and weapon drops shape run tempo.", "deal": "Early damage/fire-rate usually beats greed picks.", "lore": "Boss waves guarantee high-value drops."},
        {"key": "rpg", "name": "Boss Rewards", "icon": "CRD", "what": "Boss kills open temp + permanent card picks.", "deal": "Pick consistency first, then high-risk scaling.", "lore": "Card flow is your long-run progression core."},
        {"key": "pause", "name": "Pause/Menu", "icon": "ESC", "what": "Press ESC to pause or navigate menus.", "deal": "Use pause to reset focus in dense waves.", "lore": "A short reset often saves a run."},
    ]

    def __init__(self, width: int, height: int):
        self.screen_width = width
        self.screen_height = height
        self.batch = pyglet.graphics.Batch()
        self.tab = "enemies"
        self.page = 0
        self.rows_per_page = 6
        self._t = 0.0

        self._bg_a = shapes.Rectangle(0, 0, width, height, color=(8, 14, 24), batch=self.batch)
        self._bg_b = shapes.Rectangle(0, 0, width, height, color=(6, 10, 18), batch=self.batch)
        self._bg_b.opacity = 170
        self._panel_border = shapes.Rectangle(0, 0, 1, 1, color=(160, 210, 255), batch=self.batch)
        self._panel_border.opacity = 52
        self._panel = shapes.Rectangle(0, 0, 1, 1, color=(10, 20, 34), batch=self.batch)
        self._panel.opacity = 214
        self._panel_shine = shapes.Rectangle(0, 0, 1, 1, color=(255, 255, 255), batch=self.batch)
        self._panel_shine.opacity = 14
        self._scanline = shapes.Rectangle(0, 0, width, 3, color=(125, 205, 255), batch=self.batch)
        self._scanline.opacity = 0

        self.title = pyglet.text.Label(
            "P L O U T O // FIELD GUIDE",
            font_name=UI_FONT_HEAD,
            font_size=30,
            x=width // 2,
            y=height - 70,
            anchor_x="center",
            anchor_y="center",
            color=(228, 239, 255, 255),
            batch=self.batch,
        )
        self.subtitle = pyglet.text.Label(
            "",
            font_name=UI_FONT_META,
            font_size=12,
            x=width // 2,
            y=height - 102,
            anchor_x="center",
            anchor_y="center",
            color=(165, 182, 203, 255),
            batch=self.batch,
        )

        self.btn_enemies = MenuButton(0, 0, 180, 50, "Enemies", lambda: None, color=(72, 118, 210), hover_color=(108, 154, 244))
        self.btn_powerups = MenuButton(0, 0, 180, 50, "Powerups", lambda: None, color=(72, 118, 210), hover_color=(108, 154, 244))
        self.btn_basics = MenuButton(0, 0, 180, 50, "Basics", lambda: None, color=(72, 118, 210), hover_color=(108, 154, 244))
        self.btn_prev = MenuButton(0, 0, 120, 44, "Prev", lambda: None, color=(72, 118, 210), hover_color=(108, 154, 244))
        self.btn_next = MenuButton(0, 0, 120, 44, "Next", lambda: None, color=(72, 118, 210), hover_color=(108, 154, 244))
        self.btn_back = MenuButton(0, 0, 200, 54, "Back to Menu", lambda: None, color=(110, 110, 150), hover_color=(145, 145, 195))
        self._buttons = [self.btn_enemies, self.btn_powerups, self.btn_basics, self.btn_prev, self.btn_next, self.btn_back]
        for b in self._buttons:
            b.ensure(self.batch)

        self._rows = []
        for _ in range(self.rows_per_page):
            bg = shapes.Rectangle(0, 0, 1, 1, color=(17, 33, 52), batch=self.batch)
            bg.opacity = 150
            accent = shapes.Rectangle(0, 0, 1, 1, color=(110, 180, 235), batch=self.batch)
            accent.opacity = 120
            pic_plate = shapes.Circle(0, 0, 18, color=(18, 35, 58), batch=self.batch)
            pic_plate.opacity = 245
            icon_ring = shapes.Circle(0, 0, 14, color=(255, 255, 255), batch=self.batch)
            icon_ring.opacity = 70
            icon = shapes.Circle(0, 0, 11, color=(160, 160, 160), batch=self.batch)
            icon.opacity = 255
            glyph = pyglet.text.Label("", font_name=UI_FONT_HEAD, font_size=10, x=0, y=0, anchor_x="center", anchor_y="center", color=(255, 255, 255, 255), batch=self.batch)
            name = pyglet.text.Label("", font_name=UI_FONT_BODY, font_size=15, x=0, y=0, anchor_x="left", anchor_y="center", color=(230, 238, 250, 255), batch=self.batch)
            desc = pyglet.text.Label("", font_name=UI_FONT_META, font_size=11, x=0, y=0, anchor_x="left", anchor_y="center", color=(183, 197, 216, 255), batch=self.batch)
            lore = pyglet.text.Label("", font_name=UI_FONT_META, font_size=10, x=0, y=0, anchor_x="left", anchor_y="center", color=(152, 170, 194, 255), batch=self.batch)
            phase = random.uniform(0.0, math.tau)
            self._rows.append((bg, accent, pic_plate, icon_ring, icon, glyph, name, desc, lore, phase))

        self.footer = pyglet.text.Label(
            "",
            font_name=UI_FONT_META,
            font_size=11,
            x=width // 2,
            y=26,
            anchor_x="center",
            anchor_y="center",
            color=(168, 186, 206, 255),
            batch=self.batch,
        )
        self.resize(width, height)

    def _entries(self) -> list[dict]:
        if self.tab == "enemies":
            return self.ENEMY_INFO
        if self.tab == "powerups":
            return self.POWERUP_INFO
        return self.BASICS_INFO

    def _total_pages(self) -> int:
        n = len(self._entries())
        return max(1, (n + self.rows_per_page - 1) // self.rows_per_page)

    def _page_entries(self) -> list[dict]:
        total = self._total_pages()
        self.page = max(0, min(self.page, total - 1))
        start = self.page * self.rows_per_page
        return self._entries()[start:start + self.rows_per_page]

    def _entry_color(self, e: dict) -> tuple:
        key = str(e.get("key", ""))
        if self.tab == "enemies":
            return config.ENEMY_COLORS.get(key, (200, 200, 200))
        if self.tab == "powerups":
            return config.POWERUP_COLORS.get(key, (200, 200, 200))
        return (140, 200, 255)

    def update(self, dt: float):
        self._t += dt
        self._panel_shine.opacity = int(8 + 14 * (0.5 + 0.5 * math.sin(self._t * 1.4)))
        self._scanline.y = int(36 + (self.screen_height - 72) * (0.5 + 0.5 * math.sin(self._t * 0.37)))
        self._scanline.opacity = int(12 + 26 * (0.5 + 0.5 * math.sin(self._t * 2.1)))

    def resize(self, width: int, height: int):
        self.screen_width = width
        self.screen_height = height
        self._bg_a.width = width
        self._bg_a.height = height
        self._bg_b.width = width
        self._bg_b.height = height
        self._scanline.width = width
        self._scanline.height = max(2, int(3 * min(_ui_scale(width, height), 1.25)))
        cx = width // 2
        scale = min(_ui_scale(width, height), 1.25)

        panel_w = min(int(width * 0.94), int(1220 * scale))
        panel_h = min(int(height * 0.84), int(760 * scale))
        panel_x = cx - panel_w // 2
        panel_y = max(16, int(18 * scale))
        self._panel_border.x = panel_x - 3
        self._panel_border.y = panel_y - 3
        self._panel_border.width = panel_w + 6
        self._panel_border.height = panel_h + 6
        self._panel.x = panel_x
        self._panel.y = panel_y
        self._panel.width = panel_w
        self._panel.height = panel_h
        self._panel_shine.x = panel_x + 4
        self._panel_shine.y = panel_y + panel_h - max(8, int(20 * scale))
        self._panel_shine.width = panel_w - 8
        self._panel_shine.height = max(6, int(14 * scale))

        self.title.x = cx
        self.title.y = height - int(64 * scale)
        _sync_label_style_if_ready(self.title, UI_FONT_HEAD, max(20, int(34 * scale)))
        self.subtitle.x = cx
        self.subtitle.y = self.title.y - int(30 * scale)
        _sync_label_style_if_ready(self.subtitle, UI_FONT_META, max(10, int(13 * scale)))

        top_y = panel_y + panel_h - int(86 * scale)
        self.btn_enemies.width = int(190 * scale)
        self.btn_enemies.height = int(52 * scale)
        self.btn_enemies.font_size = max(12, int(17 * scale))
        self.btn_enemies.x = panel_x + int(28 * scale)
        self.btn_enemies.y = top_y

        self.btn_powerups.width = int(190 * scale)
        self.btn_powerups.height = int(52 * scale)
        self.btn_powerups.font_size = max(12, int(17 * scale))
        self.btn_powerups.x = self.btn_enemies.x + self.btn_enemies.width + int(14 * scale)
        self.btn_powerups.y = top_y
        self.btn_basics.width = int(190 * scale)
        self.btn_basics.height = int(52 * scale)
        self.btn_basics.font_size = max(12, int(17 * scale))
        self.btn_basics.x = self.btn_powerups.x + self.btn_powerups.width + int(14 * scale)
        self.btn_basics.y = top_y

        self.btn_back.width = int(220 * scale)
        self.btn_back.height = int(52 * scale)
        self.btn_back.font_size = max(11, int(16 * scale))
        self.btn_back.x = panel_x + panel_w - self.btn_back.width - int(24 * scale)
        self.btn_back.y = top_y

        row_top = top_y - int(26 * scale)
        row_h = int(88 * scale)
        row_gap = int(10 * scale)
        row_x = panel_x + int(24 * scale)
        row_w = panel_w - int(48 * scale)
        for i, (bg, accent, pic_plate, icon_ring, icon, glyph, name, desc, lore, _) in enumerate(self._rows):
            y = row_top - i * (row_h + row_gap) - row_h
            bg.x = row_x
            bg.y = y
            bg.width = row_w
            bg.height = row_h
            accent.x = row_x
            accent.y = y
            accent.width = max(4, int(5 * scale))
            accent.height = row_h

            icon_x = row_x + int(28 * scale)
            icon_y = y + row_h // 2 + int(1 * scale)
            pic_plate.x, pic_plate.y, pic_plate.radius = icon_x, icon_y, int(18 * scale)
            icon_ring.x, icon_ring.y, icon_ring.radius = icon_x, icon_y, int(15 * scale)
            icon.x, icon.y, icon.radius = icon_x, icon_y, int(12 * scale)
            glyph.x, glyph.y = icon_x, icon_y
            _sync_label_style_if_ready(glyph, UI_FONT_HEAD, max(8, int(11 * scale)))

            text_x = row_x + int(56 * scale)
            name.x = text_x
            name.y = y + row_h - int(22 * scale)
            _sync_label_style_if_ready(name, UI_FONT_BODY, max(11, int(16 * scale)))

            desc.x = text_x
            desc.y = y + row_h - int(45 * scale)
            _sync_label_style_if_ready(desc, UI_FONT_META, max(9, int(12 * scale)))

            lore.x = text_x
            lore.y = y + row_h - int(66 * scale)
            _sync_label_style_if_ready(lore, UI_FONT_META, max(8, int(11 * scale)))

        self.btn_prev.width = int(118 * scale)
        self.btn_prev.height = int(44 * scale)
        self.btn_prev.font_size = max(10, int(14 * scale))
        self.btn_prev.x = panel_x + int(24 * scale)
        self.btn_prev.y = panel_y + int(14 * scale)
        self.btn_next.width = int(118 * scale)
        self.btn_next.height = int(44 * scale)
        self.btn_next.font_size = max(10, int(14 * scale))
        self.btn_next.x = self.btn_prev.x + self.btn_prev.width + int(12 * scale)
        self.btn_next.y = self.btn_prev.y

        self.footer.x = cx
        self.footer.y = panel_y + int(28 * scale)
        _sync_label_style_if_ready(self.footer, UI_FONT_META, max(9, int(11 * scale)))

        for b in self._buttons:
            b.sync()

    def on_mouse_motion(self, x: float, y: float):
        for b in self._buttons:
            b.is_hovered = b.contains_point(x, y)
            b.sync()

    def on_mouse_press(self, x: float, y: float, button: int) -> Optional[str]:
        if button != pyglet.window.mouse.LEFT:
            return None
        if self.btn_back.contains_point(x, y):
            return "back"
        if self.btn_enemies.contains_point(x, y):
            self.tab = "enemies"
            self.page = 0
            return None
        if self.btn_powerups.contains_point(x, y):
            self.tab = "powerups"
            self.page = 0
            return None
        if self.btn_basics.contains_point(x, y):
            self.tab = "basics"
            self.page = 0
            return None
        total_pages = self._total_pages()
        if self.btn_prev.contains_point(x, y):
            self.page = (self.page - 1) % total_pages
            return None
        if self.btn_next.contains_point(x, y):
            self.page = (self.page + 1) % total_pages
            return None
        return None

    def on_key_press(self, symbol: int):
        if symbol in (pyglet.window.key.LEFT, pyglet.window.key.A):
            self.page = (self.page - 1) % self._total_pages()
        elif symbol in (pyglet.window.key.RIGHT, pyglet.window.key.D):
            self.page = (self.page + 1) % self._total_pages()

    def draw(self):
        self.btn_enemies.is_hovered = self.btn_enemies.is_hovered or self.tab == "enemies"
        self.btn_powerups.is_hovered = self.btn_powerups.is_hovered or self.tab == "powerups"
        self.btn_basics.is_hovered = self.btn_basics.is_hovered or self.tab == "basics"
        self.btn_enemies.sync()
        self.btn_powerups.sync()
        self.btn_basics.sync()
        entries = self._page_entries()
        for i, row in enumerate(self._rows):
            bg, accent, pic_plate, icon_ring, icon, glyph, name, desc, lore, phase = row
            if i >= len(entries):
                bg.opacity = 0
                accent.opacity = 0
                pic_plate.opacity = 0
                icon.opacity = 0
                icon_ring.opacity = 0
                glyph.text = ""
                name.text = ""
                desc.text = ""
                lore.text = ""
                continue
            pulse = 0.5 + 0.5 * math.sin(self._t * 2.8 + phase)
            e = entries[i]
            bg.opacity = int(136 + 24 * pulse)
            accent.opacity = int(84 + 70 * pulse)
            pic_plate.opacity = int(200 + 45 * pulse)
            icon_ring.opacity = int(68 + 46 * pulse)
            icon.opacity = 255
            icon.color = self._entry_color(e)
            glyph.text = str(e.get("icon", "?"))
            name.text = str(e.get("name", "Unknown"))
            desc.text = f"Threat: {str(e.get('what', ''))}  |  Counter: {str(e.get('deal', ''))}"
            lore.text = f"Lore: {str(e.get('lore', ''))}"

        page_info = f"Page {self.page + 1}/{self._total_pages()}  |  Left/Right or buttons to browse"
        if self.tab == "enemies":
            self.subtitle.text = "Enemy dossiers, threat cues, and fast counterplay."
            self.footer.text = f"{page_info}  |  {len(self.ENEMY_INFO)} entries"
        elif self.tab == "powerups":
            self.subtitle.text = "Powerup effects, timing advice, and field notes."
            self.footer.text = f"{page_info}  |  {len(self.POWERUP_INFO)} entries"
        else:
            self.subtitle.text = "Core controls, movement rules, and run-flow fundamentals."
            self.footer.text = f"{page_info}  |  {len(self.BASICS_INFO)} entries"
        self.batch.draw()
        self.btn_enemies.is_hovered = False
        self.btn_powerups.is_hovered = False
        self.btn_basics.is_hovered = False


class PauseMenu:
    """Pause menu screen."""
    
    def __init__(self, width: int, height: int):
        self.batch = pyglet.graphics.Batch()
        self.overlay = shapes.Rectangle(0, 0, width, height, color=(6, 10, 18), batch=self.batch)
        self.overlay.opacity = 172

        self.buttons: List[MenuButton] = [
            MenuButton(0, 0, 160, 50, "Resume", lambda: None, color=(45, 170, 125), hover_color=(80, 220, 160)),
            MenuButton(0, 0, 160, 50, "Quit to Menu", lambda: None, color=(200, 70, 90), hover_color=(245, 95, 120)),
        ]
        for b in self.buttons:
            b.ensure(self.batch)

        self.title = pyglet.text.Label(
            "PAUSED",
            font_name=UI_FONT_HEAD,
            font_size=32,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            color=(226, 238, 255, 255),
            batch=self.batch,
        )
        self.resize(width, height)

    def resize(self, width: int, height: int):
        cx = width // 2
        cy = height // 2
        scale = min(_ui_scale(width, height), 1.6)
        self.overlay.width = width
        self.overlay.height = height
        self.title.x = cx
        _sync_label_style_if_ready(self.title, UI_FONT_HEAD, max(20, int(38 * scale)))
        self.title.y = height - int(110 * scale)

        button_w = int(240 * scale)
        button_h = int(62 * scale)
        font = max(12, int(18 * scale))
        for btn in self.buttons:
            btn.width = button_w
            btn.height = button_h
            btn.font_size = font

        gap = int(18 * scale)
        total_h = len(self.buttons) * button_h + (len(self.buttons) - 1) * gap
        start_y = cy + total_h // 2 - button_h
        ys = [start_y - i * (button_h + gap) for i in range(len(self.buttons))]
        for btn, y in zip(self.buttons, ys):
            btn.x = cx - btn.width // 2
            btn.y = y
            btn.sync()

    def on_mouse_motion(self, x: float, y: float):
        for button in self.buttons:
            button.is_hovered = button.contains_point(x, y)
            button.sync()

    def on_mouse_press(self, x: float, y: float, button: int) -> Optional[str]:
        if button != pyglet.window.mouse.LEFT:
            return None
        for btn in self.buttons:
            if btn.contains_point(x, y):
                if btn.text == "Resume":
                    return "resume"
                elif btn.text == "Quit to Menu":
                    return "quit_to_menu"
        return None

    def draw(self):
        for btn in self.buttons:
            btn.sync()
        self.batch.draw()


class GameOverMenu:
    """Game Over screen."""
    
    def __init__(self, width: int, height: int):
        self.batch = pyglet.graphics.Batch()
        self.overlay = shapes.Rectangle(0, 0, width, height, color=(22, 5, 10), batch=self.batch)
        self.overlay.opacity = 216

        self.buttons: List[MenuButton] = [
            MenuButton(0, 0, 160, 50, "Try Again", lambda: None, color=(45, 170, 125), hover_color=(80, 220, 160)),
            MenuButton(0, 0, 160, 50, "Main Menu", lambda: None, color=(70, 125, 220), hover_color=(105, 170, 255)),
        ]
        for b in self.buttons:
            b.ensure(self.batch)

        self.title = pyglet.text.Label(
            "GAME OVER",
            font_name=UI_FONT_HEAD,
            font_size=40,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            color=(255, 128, 146, 255),
            batch=self.batch,
        )

        self.score_label = pyglet.text.Label(
            "Reached Wave 1",
            font_name=UI_FONT_BODY,
            font_size=20,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            color=(255, 255, 255, 255),
            batch=self.batch,
        )

        self.final_score_label = pyglet.text.Label(
            "Score: 0",
            font_name=UI_FONT_HEAD,
            font_size=28,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            color=(255, 240, 180, 255),
            batch=self.batch,
        )

        self.high_score_label = pyglet.text.Label(
            "",
            font_name=UI_FONT_META,
            font_size=14,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            color=(188, 210, 232, 220),
            batch=self.batch,
        )

        self.new_high_label = pyglet.text.Label(
            "",
            font_name=UI_FONT_HEAD,
            font_size=18,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            color=(255, 200, 60, 255),
            batch=self.batch,
        )
        self.resize(width, height)

    def resize(self, width: int, height: int):
        cx = width // 2
        cy = height // 2
        scale = min(_ui_scale(width, height), 1.6)
        self.overlay.width = width
        self.overlay.height = height
        self.title.x = cx
        _sync_label_style_if_ready(self.title, UI_FONT_HEAD, max(24, int(46 * scale)))
        self.title.y = height - int(95 * scale)

        self.final_score_label.x = cx
        _sync_label_style_if_ready(self.final_score_label, UI_FONT_HEAD, max(16, int(30 * scale)))
        self.final_score_label.y = height - int(155 * scale)

        self.score_label.x = cx
        _sync_label_style_if_ready(self.score_label, UI_FONT_BODY, max(12, int(18 * scale)))
        self.score_label.y = height - int(195 * scale)

        self.high_score_label.x = cx
        _sync_label_style_if_ready(self.high_score_label, UI_FONT_META, max(10, int(14 * scale)))
        self.high_score_label.y = height - int(225 * scale)

        self.new_high_label.x = cx
        _sync_label_style_if_ready(self.new_high_label, UI_FONT_HEAD, max(12, int(18 * scale)))
        self.new_high_label.y = height - int(255 * scale)

        button_w = int(260 * scale)
        button_h = int(62 * scale)
        font = max(12, int(18 * scale))
        for btn in self.buttons:
            btn.width = button_w
            btn.height = button_h
            btn.font_size = font

        gap = int(18 * scale)
        btn_start_y = cy - int(10 * scale)
        ys = [btn_start_y, btn_start_y - (button_h + gap)]
        for btn, y in zip(self.buttons, ys):
            btn.x = cx - btn.width // 2
            btn.y = y
            btn.sync()

    def set_wave(self, wave: int):
        """Legacy compat."""
        self.set_results(wave, 0, 0, False)

    def set_results(self, wave: int, score: int, high_score: int, is_new_high: bool):
        """Set game-over data with score info."""
        self.score_label.text = f"You reached Wave {wave}"
        self.final_score_label.text = f"Score: {score:,}"
        self.high_score_label.text = f"High Score: {high_score:,}"
        self.new_high_label.text = "\u2605 NEW HIGH SCORE! \u2605" if is_new_high else ""

    def on_mouse_motion(self, x: float, y: float):
        for button in self.buttons:
            button.is_hovered = button.contains_point(x, y)
            button.sync()

    def on_mouse_press(self, x: float, y: float, button: int) -> Optional[str]:
        if button != pyglet.window.mouse.LEFT:
            return None
        for btn in self.buttons:
            if btn.contains_point(x, y):
                if btn.text == "Try Again":
                    return "retry"
                elif btn.text == "Main Menu":
                    return "quit_to_menu"
        return None

    def draw(self):
        for btn in self.buttons:
            btn.sync()
        self.batch.draw()

