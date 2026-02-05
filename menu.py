"""Menu system for game configuration and navigation."""

from dataclasses import dataclass
from typing import Callable, List, Optional
import pyglet
from pyglet import shapes
from utils import Vec2


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
    is_hovered: bool = False
    
    def contains_point(self, px: float, py: float) -> bool:
        """Check if point is inside button."""
        return self.x <= px <= self.x + self.width and self.y <= py <= self.y + self.height
    
    def draw(self, batch) -> List:
        """Draw button and return list of visual objects."""
        objects = []
        color = self.hover_color if self.is_hovered else self.color
        
        # Button background
        bg = shapes.Rectangle(
            self.x, self.y, self.width, self.height,
            color=color, batch=batch
        )
        objects.append(bg)
        
        # Button border
        border = shapes.Rectangle(
            self.x, self.y, self.width, self.height,
            color=(255, 255, 255), batch=batch
        )
        border.opacity = 100
        objects.append(border)
        
        # Button text
        label = pyglet.text.Label(
            self.text,
            font_name="Arial",
            font_size=16,
            x=self.x + self.width // 2,
            y=self.y + self.height // 2,
            anchor_x="center",
            anchor_y="center",
            batch=batch,
            color=(255, 255, 255, 255)
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
        return (abs(px - knob_x) <= 8 and abs(py - self.y) <= 8)
    
    def draw(self, batch) -> List:
        """Draw slider and return list of visual objects."""
        objects = []
        
        # Label
        label = pyglet.text.Label(
            f"{self.label}: {self.current_val:.0f}",
            font_name="Arial",
            font_size=14,
            x=self.x,
            y=self.y + 20,
            anchor_x="left",
            anchor_y="bottom",
            batch=batch,
            color=(255, 255, 255, 255)
        )
        objects.append(label)
        
        # Track
        track = shapes.Line(
            self.x, self.y, self.x + self.width, self.y,
            thickness=2, color=(100, 100, 100), batch=batch
        )
        objects.append(track)
        
        # Knob
        knob = shapes.Circle(
            self.get_knob_x(), self.y, 8,
            color=(150, 200, 255), batch=batch
        )
        objects.append(knob)
        
        return objects


class Menu:
    """Main menu screen."""
    
    def __init__(self, width: int, height: int):
        self.screen_width = width
        self.screen_height = height
        self.batch = pyglet.graphics.Batch()
        self.buttons: List[MenuButton] = []
        self.buttons.append(MenuButton(0, 0, 160, 50, "Start Game", lambda: None, color=(50, 150, 50)))
        self.buttons.append(MenuButton(0, 0, 160, 50, "Settings", lambda: None, color=(100, 100, 150)))
        self.buttons.append(MenuButton(0, 0, 160, 50, "Quit", lambda: None, color=(150, 50, 50)))

        self.title = pyglet.text.Label(
            "ISOMETRIC ROOM SURVIVAL",
            font_name="Arial",
            font_size=32,
            x=width // 2,
            y=height - 80,
            anchor_x="center",
            anchor_y="center",
            color=(200, 220, 255, 255),
        )

        self.subtitle = pyglet.text.Label(
            "WASD/Arrows to move, Hold Mouse to shoot, ESC for menu",
            font_name="Arial",
            font_size=12,
            x=width // 2,
            y=height - 120,
            anchor_x="center",
            anchor_y="center",
            color=(150, 150, 150, 255),
        )

        self.resize(width, height)

    def resize(self, width: int, height: int):
        self.screen_width = width
        self.screen_height = height
        cx = width // 2
        cy = height // 2

        ys = [cy + 80, cy + 10, cy - 60]
        for btn, y in zip(self.buttons, ys):
            btn.x = cx - btn.width // 2
            btn.y = y

        self.title.x = cx
        self.title.y = height - 80
        self.subtitle.x = cx
        self.subtitle.y = height - 120
    
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
        
        # Settings
        self.difficulty = 1  # 0=easy, 1=normal, 2=hard
        self.volume = 80.0
        self.window_size_idx = 0  # 0=800x600, 1=1024x768, 2=1280x720, 3=fullscreen
        self.window_sizes = [(800, 600), (1024, 768), (1280, 720), (1920, 1080)]
        self.window_size_names = ["800x600", "1024x768", "1280x720", "1920x1080"]
        if display_size:
            dw, dh = int(display_size[0]), int(display_size[1])
            if dw > 0 and dh > 0 and (dw, dh) not in self.window_sizes:
                self.window_sizes.append((dw, dh))
                self.window_size_names.append(f"Native ({dw}x{dh})")
        
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
        
        # Volume slider
        self.volume_slider = MenuSlider(
            0,
            0,
            240,
            "Master Volume",
            0,
            100,
            self.volume,
            lambda v: self._set_volume(v),
        )
        
        # Back button
        self.back_button = MenuButton(0, 20, 160, 50, "Back to Menu", lambda: None, color=(100, 100, 150))
        
        self.title = pyglet.text.Label(
            "SETTINGS",
            font_name="Arial",
            font_size=28,
            x=width // 2,
            y=height - 40,
            anchor_x="center",
            anchor_y="center",
            color=(200, 220, 255, 255)
        )
        
        self.difficulty_label = pyglet.text.Label(
            "Difficulty:",
            font_name="Arial",
            font_size=16,
            x=150,
            y=height // 2 + 100,
            anchor_x="left",
            anchor_y="center",
            color=(255, 255, 255, 255)
        )
        
        self.window_label = pyglet.text.Label(
            "Window Size:",
            font_name="Arial",
            font_size=16,
            x=0,
            y=height // 2 - 10,
            anchor_x="left",
            anchor_y="center",
            color=(255, 255, 255, 255)
        )

        self.resize(width, height)

    def resize(self, width: int, height: int):
        self.screen_width = width
        self.screen_height = height
        cx = width // 2

        button_w = 150
        button_h = 50
        gap = 20

        # Difficulty row
        total_w = 3 * button_w + 2 * gap
        start_x = cx - total_w // 2
        y = height // 2 + 40
        for i, btn in enumerate(self.difficulty_buttons):
            btn.x = start_x + i * (button_w + gap)
            btn.y = y

        # Window sizes (2 columns)
        grid_total_w = 2 * button_w + gap
        grid_start_x = cx - grid_total_w // 2
        base_y = height // 2 - 60
        for i, btn in enumerate(self.size_buttons):
            col = i % 2
            row = i // 2
            btn.x = grid_start_x + col * (button_w + gap)
            btn.y = base_y - row * (button_h + 10)

        # Labels & slider aligned to left edge of the menu block
        left_x = min(start_x, grid_start_x)
        self.difficulty_label.x = left_x
        self.difficulty_label.y = height // 2 + 100
        self.window_label.x = left_x
        self.window_label.y = height // 2 - 10

        self.volume_slider.x = left_x
        self.volume_slider.y = height // 2 - 140

        self.back_button.x = cx - self.back_button.width // 2
        self.back_button.y = 20

        self.title.x = cx
        self.title.y = height - 40
    
    def _set_difficulty(self, level: int):
        """Set difficulty level."""
        self.difficulty = level
        self.on_save(self.get_settings())
    
    def _set_volume(self, val: float):
        """Set volume."""
        self.volume = val
    
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
        if self.volume_slider.is_dragging:
            self.volume_slider.set_value_from_x(x)
    
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
        
        if self.volume_slider.contains_knob(x, y) or \
           (x >= self.volume_slider.x and x <= self.volume_slider.x + self.volume_slider.width and abs(y - self.volume_slider.y) < 10):
            self.volume_slider.is_dragging = True
            self.volume_slider.set_value_from_x(x)
        
        return None
    
    def on_mouse_release(self, x: float, y: float, button: int):
        """Handle mouse release."""
        self.volume_slider.is_dragging = False
    
    def get_settings(self) -> dict:
        """Get current settings."""
        difficulty_names = ["easy", "normal", "hard"]
        return {
            "difficulty": difficulty_names[self.difficulty],
            "window_size": self.window_sizes[self.window_size_idx],
            "volume": self.volume
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
        _ = self.volume_slider.draw(temp_batch)
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
        self.buttons.append(MenuButton(0, 0, 160, 50, "Resume", lambda: None, color=(50, 150, 50)))
        self.buttons.append(MenuButton(0, 0, 160, 50, "Quit to Menu", lambda: None, color=(150, 50, 50)))
        
        self.title = pyglet.text.Label(
            "PAUSED",
            font_name="Arial",
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
        self.overlay.width = width
        self.overlay.height = height
        self.title.x = cx
        self.title.y = height - 100
        ys = [cy + 20, cy - 50]
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
        self.buttons.append(MenuButton(0, 0, 160, 50, "Try Again", lambda: None, color=(50, 150, 50)))
        self.buttons.append(MenuButton(0, 0, 160, 50, "Main Menu", lambda: None, color=(100, 100, 150)))
        
        self.title = pyglet.text.Label(
            "GAME OVER",
            font_name="Arial",
            font_size=40,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            color=(255, 50, 50, 255)
        )
        
        self.score_label = pyglet.text.Label(
            "Reached Wave 1",
            font_name="Arial",
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
        self.overlay.width = width
        self.overlay.height = height
        self.title.x = cx
        self.title.y = height - 100
        self.score_label.x = cx
        self.score_label.y = cy + 60
        ys = [cy - 20, cy - 90]
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
