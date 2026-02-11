"""Menu system for game configuration and navigation."""

from dataclasses import dataclass
from typing import Callable, List, Optional
import math
import random
import pyglet
from pyglet import shapes
import config


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
    font_name: str = "Segoe UI"
    font_size: int = 16
    text_color: tuple = (255, 255, 255, 255)
    is_hovered: bool = False
    
    def contains_point(self, px: float, py: float) -> bool:
        """Check if point is inside button."""
        return self.x <= px <= self.x + self.width and self.y <= py <= self.y + self.height
    
    def draw(self, batch) -> List:
        """Draw button and return list of visual objects."""
        objects = []
        color = self.hover_color if self.is_hovered else self.color
        shadow_off = max(2, int(self.height * 0.08))
        border_pad = max(2, int(self.height * 0.06))
        
        # Shadow
        shadow = shapes.Rectangle(
            self.x + shadow_off,
            self.y - shadow_off,
            self.width,
            self.height,
            color=(0, 0, 0),
            batch=batch,
        )
        shadow.opacity = 85
        objects.append(shadow)

        # Border (slightly larger rectangle behind)
        border = shapes.Rectangle(
            self.x - border_pad,
            self.y - border_pad,
            self.width + border_pad * 2,
            self.height + border_pad * 2,
            color=(220, 235, 255),
            batch=batch,
        )
        border.opacity = 70 if self.is_hovered else 35
        objects.append(border)

        # Button background
        bg = shapes.Rectangle(
            self.x, self.y, self.width, self.height,
            color=color, batch=batch
        )
        bg.opacity = 235 if self.is_hovered else 210
        objects.append(bg)
        
        # Subtle top shine
        shine_h = max(3, int(self.height * 0.16))
        shine = shapes.Rectangle(
            self.x + 2,
            self.y + self.height - shine_h - 2,
            max(1, self.width - 4),
            shine_h,
            color=(255, 255, 255),
            batch=batch,
        )
        shine.opacity = 55 if self.is_hovered else 32
        objects.append(shine)
        
        # Button text
        label = pyglet.text.Label(
            self.text,
            font_name=self.font_name,
            font_size=self.font_size,
            x=self.x + self.width // 2,
            y=self.y + self.height // 2,
            anchor_x="center",
            anchor_y="center",
            batch=batch,
            color=self.text_color,
        )
        objects.append(label)
        
        return objects


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
    font_name: str = "Segoe UI"
    font_size: int = 14
    knob_radius: float = 8.0
    track_thickness: float = 2.0
    value_fmt: str = "{:.0f}"
    value_suffix: str = ""
    
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
        objects = []
        val_str = self.value_fmt.format(self.current_val)
        
        # Label
        label = pyglet.text.Label(
            f"{self.label}: {val_str}{self.value_suffix}",
            font_name=self.font_name,
            font_size=self.font_size,
            x=self.x,
            y=self.y + 20,
            anchor_x="left",
            anchor_y="bottom",
            batch=batch,
            color=(255, 255, 255, 255)
        )
        objects.append(label)
        
        # Track
        track_shadow = shapes.Line(
            self.x, self.y, self.x + self.width, self.y,
            thickness=max(1.0, self.track_thickness + 3.0),
            color=(0, 0, 0),
            batch=batch,
        )
        track_shadow.opacity = 90
        objects.append(track_shadow)

        track = shapes.Line(
            self.x, self.y, self.x + self.width, self.y,
            thickness=self.track_thickness,
            color=(120, 130, 155),
            batch=batch,
        )
        track.opacity = 160
        objects.append(track)
        
        # Knob
        knob_back = shapes.Circle(
            self.get_knob_x(), self.y, self.knob_radius + 3,
            color=(255, 255, 255), batch=batch
        )
        knob_back.opacity = 55
        objects.append(knob_back)

        knob = shapes.Circle(
            self.get_knob_x(), self.y, self.knob_radius,
            color=(150, 210, 255) if self.is_dragging else (130, 190, 240),
            batch=batch,
        )
        knob.opacity = 240
        objects.append(knob)
        
        return objects


class Menu:
    """Main menu screen."""
    
    def __init__(self, width: int, height: int):
        self.screen_width = width
        self.screen_height = height
        self.batch = pyglet.graphics.Batch()
        self._t = 0.0
        self._orbs: List[tuple[shapes.Circle, float, float, float]] = []

        self._bg_a = shapes.Rectangle(0, 0, width, height, color=(12, 14, 22), batch=self.batch)
        self._bg_b = shapes.Rectangle(0, 0, width, height, color=(7, 9, 16), batch=self.batch)
        self._bg_b.opacity = 120

        count = max(10, min(22, int((width * height) / 90_000)))
        for _ in range(count):
            r = random.uniform(18, 55)
            x = random.uniform(0, width)
            y = random.uniform(0, height)
            col = random.choice([(45, 90, 150), (110, 70, 170), (60, 120, 170)])
            orb = shapes.Circle(x, y, r, color=col, batch=self.batch)
            orb.opacity = random.randint(14, 36)
            vx = random.uniform(-14, 14)
            vy = random.uniform(-10, 10)
            phase = random.uniform(0, math.tau)
            self._orbs.append((orb, vx, vy, phase))

        # Panel backing for buttons.
        self._panel_border = shapes.Rectangle(0, 0, 1, 1, color=(130, 160, 230), batch=self.batch)
        self._panel_border.opacity = 38
        self._panel = shapes.Rectangle(0, 0, 1, 1, color=(16, 20, 30), batch=self.batch)
        self._panel.opacity = 180
        self._panel_shine = shapes.Rectangle(0, 0, 1, 1, color=(255, 255, 255), batch=self.batch)
        self._panel_shine.opacity = 16

        self.buttons: List[MenuButton] = []
        self.buttons.append(MenuButton(0, 0, 160, 50, "Start Game", lambda: None, color=(45, 170, 125), hover_color=(80, 220, 160)))
        self.buttons.append(MenuButton(0, 0, 160, 50, "Settings", lambda: None, color=(70, 125, 220), hover_color=(105, 170, 255)))
        self.buttons.append(MenuButton(0, 0, 160, 50, "Quit", lambda: None, color=(200, 70, 90), hover_color=(245, 95, 120)))

        self.title = pyglet.text.Label(
            "ISOMETRIC ROOM SURVIVAL",
            font_name="Segoe UI",
            font_size=32,
            x=width // 2,
            y=height - 80,
            anchor_x="center",
            anchor_y="center",
            color=(200, 220, 255, 255),
        )

        self.subtitle = pyglet.text.Label(
            "WASD/Arrows to move, Hold LMB to shoot, RMB Ultra, ESC for menu",
            font_name="Segoe UI",
            font_size=12,
            x=width // 2,
            y=height - 120,
            anchor_x="center",
            anchor_y="center",
            color=(150, 150, 150, 255),
        )

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

        self._bg_a.width = width
        self._bg_a.height = height
        self._bg_b.width = width
        self._bg_b.height = height
    
    def on_mouse_motion(self, x: float, y: float):
        """Handle mouse motion for button hover."""
        for button in self.buttons:
            button.is_hovered = button.contains_point(x, y)
    
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
        self.title.draw()
        self.subtitle.draw()
        for btn in self.buttons:
            temp_batch = pyglet.graphics.Batch()
            _ = btn.draw(temp_batch)
            temp_batch.draw()


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
        self.window_sizes = [(800, 600), (1024, 768), (1280, 720), (1920, 1080)]
        self.window_size_names = ["800x600", "1024x768", "1280x720", "1920x1080"]
        if display_size:
            dw, dh = int(display_size[0]), int(display_size[1])
            if dw > 0 and dh > 0 and (dw, dh) not in self.window_sizes:
                self.window_sizes.append((dw, dh))
                self.window_size_names.append(f"Native ({dw}x{dh})")
        self.window_sizes.append(None)
        self.window_size_names.append("Fullscreen")
        try:
            self.window_size_idx = self.window_sizes.index((width, height))
        except ValueError:
            self.window_size_idx = 0
        
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
            font_name="Segoe UI",
            font_size=28,
            x=width // 2,
            y=height - 40,
            anchor_x="center",
            anchor_y="center",
            color=(200, 220, 255, 255)
        )
        
        self.difficulty_label = pyglet.text.Label(
            "Difficulty:",
            font_name="Segoe UI",
            font_size=16,
            x=150,
            y=height // 2 + 100,
            anchor_x="left",
            anchor_y="center",
            color=(255, 255, 255, 255)
        )
        
        self.window_label = pyglet.text.Label(
            "Window Size:",
            font_name="Segoe UI",
            font_size=16,
            x=0,
            y=height // 2 - 10,
            anchor_x="left",
            anchor_y="center",
            color=(255, 255, 255, 255)
        )

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
            orb.opacity = int(10 + 16 * (0.5 + 0.5 * math.sin(self._t * 0.7 + phase)))

    def resize(self, width: int, height: int):
        self.screen_width = width
        self.screen_height = height
        cx = width // 2
        # Settings has more content than the main menu; cap scale so it stays usable.
        scale = min(_ui_scale(width, height), 1.55)

        gap = int(18 * scale)
        button_h = int(56 * scale)
        button_w = int(175 * scale)
        max_row3 = int((width * 0.88 - 2 * gap) / 3)
        max_col2 = int((width * 0.88 - gap) / 2)
        button_w = max(int(120 * scale), min(button_w, max_row3, max_col2))

        btn_font = max(12, int(16 * scale))
        for btn in self.difficulty_buttons + self.size_buttons + [self.back_button]:
            btn.width = button_w
            btn.height = button_h
            btn.font_size = btn_font

        # Content panel.
        title_pad = int(85 * scale)
        panel_top = height - title_pad
        panel_y = max(16, int(22 * scale))
        panel_w = min(int(width * 0.88), int((button_w * 3) + (gap * 2) + (160 * scale)))
        panel_h = max(260, int(panel_top - panel_y))
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

        left_x = panel_x + int(30 * scale)
        content_top = panel_y + panel_h - int(46 * scale)

        # Difficulty row
        total_w = 3 * button_w + 2 * gap
        start_x = cx - total_w // 2
        y = content_top - int(64 * scale)
        for i, btn in enumerate(self.difficulty_buttons):
            btn.x = start_x + i * (button_w + gap)
            btn.y = y

        # Window sizes (2 columns)
        grid_total_w = 2 * button_w + gap
        grid_start_x = cx - grid_total_w // 2
        rows = (len(self.size_buttons) + 1) // 2
        row_gap = max(8, int(12 * scale))
        base_y = y - button_h - int(86 * scale)
        for i, btn in enumerate(self.size_buttons):
            col = i % 2
            row = i // 2
            btn.x = grid_start_x + col * (button_w + gap)
            btn.y = base_y - row * (button_h + row_gap)

        # Labels & slider aligned to left edge of the panel content.
        self.difficulty_label.font_size = max(12, int(17 * scale))
        self.window_label.font_size = max(12, int(17 * scale))
        self.difficulty_label.x = left_x
        self.difficulty_label.y = min(
            int(content_top - int(8 * scale)),
            int(y + button_h + int(26 * scale)),
        )
        self.window_label.x = left_x
        self.window_label.y = int(base_y + button_h + int(26 * scale))

        slider_y = base_y - rows * (button_h + row_gap) - int(74 * scale)
        self.arena_slider.x = left_x
        min_slider_y = int(panel_y + int(18 * scale) + button_h + int(52 * scale))
        self.arena_slider.y = max(int(slider_y), int(min_slider_y))
        self.arena_slider.width = min(int(380 * scale), int(panel_w - (left_x - panel_x) * 2))
        self.arena_slider.font_size = max(11, int(14 * scale))
        self.arena_slider.knob_radius = max(6.0, 9.0 * scale)
        self.arena_slider.track_thickness = max(2.0, 3.0 * scale)

        self.back_button.x = cx - self.back_button.width // 2
        self.back_button.y = panel_y + int(18 * scale)

        self.title.x = cx
        self.title.font_size = max(18, int(32 * scale))
        self.title.y = height - int(60 * scale)

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

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float):
        """Handle mouse drag for sliders."""
        if self.arena_slider.is_dragging:
            self.arena_slider.set_value_from_x(x)
    
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
        
        return None
    
    def on_mouse_release(self, x: float, y: float, button: int):
        """Handle mouse release."""
        self.arena_slider.is_dragging = False
    
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
        self.batch.draw()
        self.title.draw()
        self.difficulty_label.draw()
        self.window_label.draw()
        
        # Draw difficulty buttons
        for btn in self.difficulty_buttons:
            temp_batch = pyglet.graphics.Batch()
            _ = btn.draw(temp_batch)
            temp_batch.draw()
        
        # Draw window size buttons
        for btn in self.size_buttons:
            temp_batch = pyglet.graphics.Batch()
            _ = btn.draw(temp_batch)
            temp_batch.draw()
        
        # Draw slider
        temp_batch = pyglet.graphics.Batch()
        _ = self.arena_slider.draw(temp_batch)
        temp_batch.draw()
        
        # Draw back button
        temp_batch = pyglet.graphics.Batch()
        _ = self.back_button.draw(temp_batch)
        temp_batch.draw()
        
        # Highlight selected options
        selected_diff = self.difficulty_buttons[self.difficulty]
        highlight = shapes.Rectangle(
            selected_diff.x - 2, selected_diff.y - 2,
            selected_diff.width + 4, selected_diff.height + 4,
            color=(255, 255, 255)
        )
        highlight.opacity = 60
        highlight.draw()
        
        selected_size = self.size_buttons[self.window_size_idx]
        highlight2 = shapes.Rectangle(
            selected_size.x - 2, selected_size.y - 2,
            selected_size.width + 4, selected_size.height + 4,
            color=(255, 255, 255)
        )
        highlight2.opacity = 60
        highlight2.draw()


class PauseMenu:
    """Pause menu screen."""
    
    def __init__(self, width: int, height: int):
        self.buttons: List[MenuButton] = []
        self.buttons.append(MenuButton(0, 0, 160, 50, "Resume", lambda: None, color=(45, 170, 125), hover_color=(80, 220, 160)))
        self.buttons.append(MenuButton(0, 0, 160, 50, "Quit to Menu", lambda: None, color=(200, 70, 90), hover_color=(245, 95, 120)))
        
        self.title = pyglet.text.Label(
            "PAUSED",
            font_name="Segoe UI",
            font_size=32,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            color=(255, 255, 255, 255)
        )
        
        self.overlay = shapes.Rectangle(0, 0, width, height, color=(0, 0, 0))
        self.overlay.opacity = 150
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

    def on_mouse_motion(self, x: float, y: float):
        for button in self.buttons:
            button.is_hovered = button.contains_point(x, y)

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
        self.overlay.draw()
        self.title.draw()
        for btn in self.buttons:
            temp_batch = pyglet.graphics.Batch()
            _ = btn.draw(temp_batch)
            temp_batch.draw()


class GameOverMenu:
    """Game Over screen."""
    
    def __init__(self, width: int, height: int):
        self.buttons: List[MenuButton] = []
        self.buttons.append(MenuButton(0, 0, 160, 50, "Try Again", lambda: None, color=(45, 170, 125), hover_color=(80, 220, 160)))
        self.buttons.append(MenuButton(0, 0, 160, 50, "Main Menu", lambda: None, color=(70, 125, 220), hover_color=(105, 170, 255)))
        
        self.title = pyglet.text.Label(
            "GAME OVER",
            font_name="Segoe UI",
            font_size=40,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            color=(255, 50, 50, 255)
        )
        
        self.score_label = pyglet.text.Label(
            "Reached Wave 1",
            font_name="Segoe UI",
            font_size=20,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            color=(255, 255, 255, 255)
        )
        
        self.overlay = shapes.Rectangle(0, 0, width, height, color=(20, 0, 0))
        self.overlay.opacity = 200
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

    def set_wave(self, wave: int):
        self.score_label.text = f"You reached Wave {wave}"

    def on_mouse_motion(self, x: float, y: float):
        for button in self.buttons:
            button.is_hovered = button.contains_point(x, y)

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
        self.overlay.draw()
        self.title.draw()
        self.score_label.draw()
        for btn in self.buttons:
            temp_batch = pyglet.graphics.Batch()
            _ = btn.draw(temp_batch)
            temp_batch.draw()
