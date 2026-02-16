"""Menu system for game configuration and navigation."""

from dataclasses import dataclass, field
from typing import Callable, List, Optional
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
        self._label.font_name = self.font_name
        self._label.font_size = self.font_size
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
    
    def draw(self, batch) -> List:
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
        self._label_obj.font_name = self.font_name
        self._label_obj.font_size = self.font_size
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
        self._orbs: List[tuple[shapes.Circle, float, float, float]] = []

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

        self.buttons: List[MenuButton] = []
        self.buttons.append(MenuButton(0, 0, 160, 50, "Start Game", lambda: None, color=(45, 170, 125), hover_color=(80, 220, 160)))
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
        self.title.font_size = max(22, int(38 * scale))
        self.title.y = height - int(85 * scale)
        self.subtitle.x = cx
        self.subtitle.font_size = max(10, int(13 * scale))
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
    
    def on_mouse_press(self, x: float, y: float, button: int) -> Optional[str]:
        """Handle mouse clicks. Returns action string or None."""
        if button != pyglet.window.mouse.LEFT:
            return None
        
        for btn in self.buttons:
            if btn.contains_point(x, y):
                btn.callback()
                if btn.text == "Start Game":
                    return "start_game"
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
    
    def __init__(self, width: int, height: int, on_save: Callable, display_size: Optional[tuple[int, int]] = None):
        self.screen_width = width
        self.screen_height = height
        self.on_save = on_save
        self.batch = pyglet.graphics.Batch()
        self._t = 0.0
        self._orbs: List[tuple[shapes.Circle, float, float, float]] = []

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
        self.menu_note = pyglet.text.Label(
            "Resolution and arena scale update instantly.",
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

        for btn in self.difficulty_buttons + self.size_buttons + [self.back_button]:
            btn.ensure(self.batch)
        self.arena_slider.ensure(self.batch)

        self.resize(width, height)

    def _build_window_size_options(self, display_size: Optional[tuple[int, int]]) -> tuple[list[tuple[int, int]], list[str]]:
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
        self.difficulty_label.font_size = max(12, int(17 * scale))
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

        self.window_label.font_size = max(12, int(17 * scale))
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

        rows = max(1, (len(self.size_buttons) + size_cols - 1) // size_cols)
        grid_bottom = size_top_y - (rows - 1) * (button_h + gap_y)
        slider_floor_y = self.back_button.y + self.back_button.height + int(26 * scale)
        slider_pref_y = grid_bottom - int(68 * scale)
        self.arena_slider.x = content_left
        self.arena_slider.y = max(int(slider_floor_y), int(slider_pref_y))
        self.arena_slider.width = min(int(500 * scale), content_w)
        self.arena_slider.font_size = max(11, int(14 * scale))
        self.arena_slider.knob_radius = max(6.0, 9.0 * scale)
        self.arena_slider.track_thickness = max(2.0, 3.0 * scale)

        self.title.x = cx
        self.title.font_size = max(18, int(32 * scale))
        self.title.y = height - int(60 * scale)
        self.menu_note.x = cx
        self.menu_note.y = self.title.y - int(26 * scale)
        self.menu_note.font_size = max(9, int(11 * scale))

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
    
    def on_mouse_motion(self, x: float, y: float):
        """Handle mouse motion for button hover."""
        for btn in self.difficulty_buttons + self.size_buttons + [self.back_button]:
            btn.is_hovered = btn.contains_point(x, y)
            btn.sync()

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float):
        """Handle mouse drag for sliders."""
        if self.arena_slider.is_dragging:
            self.arena_slider.set_value_from_x(x)
            self.arena_slider.sync()
    
    def on_mouse_press(self, x: float, y: float, button: int) -> Optional[str]:
        """Handle mouse clicks. Returns action string or None."""
        if button != pyglet.window.mouse.LEFT:
            return None
        
        if self.back_button.contains_point(x, y):
            self.on_save(self.get_settings())
            return "back"
        
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

        for btn in self.difficulty_buttons + self.size_buttons + [self.back_button]:
            btn.sync()
        self.arena_slider.sync()
        self.batch.draw()


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
        self.title.font_size = max(20, int(38 * scale))
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
        self.resize(width, height)

    def resize(self, width: int, height: int):
        cx = width // 2
        cy = height // 2
        scale = min(_ui_scale(width, height), 1.6)
        self.overlay.width = width
        self.overlay.height = height
        self.title.x = cx
        self.title.font_size = max(24, int(46 * scale))
        self.title.y = height - int(115 * scale)
        self.score_label.x = cx
        self.score_label.font_size = max(12, int(22 * scale))
        self.score_label.y = cy + int(78 * scale)

        button_w = int(260 * scale)
        button_h = int(62 * scale)
        font = max(12, int(18 * scale))
        for btn in self.buttons:
            btn.width = button_w
            btn.height = button_h
            btn.font_size = font

        gap = int(18 * scale)
        ys = [cy - int(10 * scale), cy - int(10 * scale) - (button_h + gap)]
        for btn, y in zip(self.buttons, ys):
            btn.x = cx - btn.width // 2
            btn.y = y
            btn.sync()

    def set_wave(self, wave: int):
        self.score_label.text = f"You reached Wave {wave}"

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

