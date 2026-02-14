from __future__ import annotations

from typing import Callable

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label


class GameOverlay(FloatLayout):
    def __init__(
        self,
        *,
        on_ultra: Callable[[], None],
        on_restart: Callable[[], None],
        on_pause_toggle: Callable[[], None],
        on_menu_start: Callable[[], None],
        on_menu_difficulty: Callable[[], None],
        on_shoot: Callable[[bool], None],
        on_upgrade_pick: Callable[[int], None],
        show_fire_button: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self._on_ultra = on_ultra
        self._on_restart = on_restart
        self._on_pause_toggle = on_pause_toggle
        self._on_menu_start = on_menu_start
        self._on_menu_difficulty = on_menu_difficulty
        self._on_shoot = on_shoot
        self._on_upgrade_pick = on_upgrade_pick

        self.hud = Label(
            text="",
            size_hint=(1, None),
            height=dp(26),
            pos_hint={"x": 0, "top": 1},
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right",
            color=(0.92, 0.92, 0.92, 1.0),
        )
        self.hud.bind(size=self.hud.setter("text_size"))
        self.add_widget(self.hud)

        # Right-side buttons
        self._fire_btn: Button | None = None
        if show_fire_button:
            self._fire_btn = Button(
                text="FIRE",
                size_hint=(None, None),
                width=dp(92),
                height=dp(44),
                pos_hint={"right": 0.99, "y": 0.02},
            )
            self._fire_btn.bind(on_press=lambda _btn: self._on_shoot(True))
            self._fire_btn.bind(on_release=lambda _btn: self._on_shoot(False))
            self.add_widget(self._fire_btn)

        self._ultra_btn = Button(
            text="ULTRA",
            size_hint=(None, None),
            width=dp(92),
            height=dp(44),
            pos_hint={"right": 0.99, "y": 0.11},
        )
        self._ultra_btn.bind(on_release=lambda _btn: self._on_ultra())
        self.add_widget(self._ultra_btn)

        self._pause_btn = Button(
            text="PAUSE",
            size_hint=(None, None),
            width=dp(92),
            height=dp(40),
            pos_hint={"right": 0.99, "top": 0.985},
        )
        self._pause_btn.bind(on_release=lambda _btn: self._on_pause_toggle())
        self.add_widget(self._pause_btn)

        # Restart button (game over)
        self._restart_btn = Button(
            text="RESTART",
            size_hint=(None, None),
            width=dp(180),
            height=dp(52),
            pos_hint={"center_x": 0.5, "center_y": 0.52},
            opacity=0.0,
            disabled=True,
        )
        self._restart_btn.bind(on_release=lambda _btn: self._on_restart())
        self.add_widget(self._restart_btn)

        # Upgrade overlay
        self._upgrade_overlay = BoxLayout(
            orientation="vertical",
            size_hint=(0.84, None),
            height=dp(220),
            pos_hint={"center_x": 0.5, "center_y": 0.5},
            spacing=dp(10),
            padding=(dp(10), dp(10), dp(10), dp(10)),
            opacity=0.0,
            disabled=True,
        )
        self._upgrade_title = Label(
            text="Pick an upgrade",
            size_hint=(1, None),
            height=dp(32),
            halign="center",
            valign="middle",
            color=(0.95, 0.95, 0.98, 1.0),
        )
        self._upgrade_title.bind(size=self._sync_label_text_size)
        self._upgrade_overlay.add_widget(self._upgrade_title)

        self._upgrade_buttons: list[Button] = []
        for idx in range(3):
            b = Button(text="...", size_hint=(1, None), height=dp(48))
            b.halign = "left"
            b.valign = "middle"
            b.bind(size=self._sync_button_text_size)
            b.bind(on_release=lambda _btn, i=idx: self._on_upgrade_pick(i))
            self._upgrade_buttons.append(b)
            self._upgrade_overlay.add_widget(b)
        self.add_widget(self._upgrade_overlay)

        self._menu_overlay = BoxLayout(
            orientation="vertical",
            size_hint=(0.84, None),
            height=dp(280),
            pos_hint={"center_x": 0.5, "center_y": 0.5},
            spacing=dp(12),
            padding=(dp(14), dp(14), dp(14), dp(14)),
            opacity=0.0,
            disabled=True,
        )
        self._menu_title = Label(
            text="KIRO2",
            size_hint=(1, None),
            height=dp(44),
            halign="center",
            valign="middle",
            color=(0.97, 0.97, 0.99, 1.0),
        )
        self._menu_title.bind(size=self._sync_label_text_size)
        self._menu_overlay.add_widget(self._menu_title)

        self._menu_start_btn = Button(text="START", size_hint=(1, None), height=dp(56))
        self._menu_start_btn.bind(on_release=lambda _btn: self._on_menu_start())
        self._menu_overlay.add_widget(self._menu_start_btn)

        self._menu_difficulty_btn = Button(text="DIFFICULTY: NORMAL", size_hint=(1, None), height=dp(56))
        self._menu_difficulty_btn.bind(on_release=lambda _btn: self._on_menu_difficulty())
        self._menu_overlay.add_widget(self._menu_difficulty_btn)
        self.add_widget(self._menu_overlay)

        self.bind(size=self._sync_layout)
        self._sync_layout()

    def _sync_label_text_size(self, label: Label, _size) -> None:
        label.text_size = (max(0.0, label.width - dp(4)), max(0.0, label.height))

    def _sync_button_text_size(self, btn: Button, _size) -> None:
        btn.text_size = (max(0.0, btn.width - dp(16)), max(0.0, btn.height - dp(8)))

    def _sync_layout(self, *_args) -> None:
        short_side = max(dp(240), min(self.width, self.height))
        side_btn_w = max(dp(84), min(dp(116), self.width * 0.24))
        side_btn_h = max(dp(40), min(dp(56), short_side * 0.1))

        self.hud.height = max(dp(28), min(dp(40), short_side * 0.075))
        self.hud.font_size = max(dp(11), min(dp(16), short_side * 0.035))

        self._ultra_btn.width = side_btn_w
        self._ultra_btn.height = side_btn_h
        self._ultra_btn.font_size = max(dp(12), min(dp(16), short_side * 0.036))
        self._pause_btn.width = side_btn_w
        self._pause_btn.height = max(dp(34), min(dp(44), short_side * 0.085))
        self._pause_btn.font_size = max(dp(11), min(dp(14), short_side * 0.03))
        if self._fire_btn is not None:
            self._fire_btn.width = side_btn_w
            self._fire_btn.height = side_btn_h
            self._fire_btn.font_size = self._ultra_btn.font_size

        self._restart_btn.width = max(dp(170), min(dp(280), self.width * 0.58))
        self._restart_btn.height = max(dp(48), min(dp(68), short_side * 0.12))
        self._restart_btn.font_size = max(dp(14), min(dp(22), short_side * 0.042))

        self._upgrade_overlay.height = max(dp(240), min(dp(380), self.height * 0.62))
        self._upgrade_title.height = max(dp(30), min(dp(44), short_side * 0.09))
        self._upgrade_title.font_size = max(dp(13), min(dp(20), short_side * 0.04))

        btn_h = max(dp(54), min(dp(90), self._upgrade_overlay.height * 0.24))
        btn_font = max(dp(11), min(dp(15), short_side * 0.031))
        for b in self._upgrade_buttons:
            b.height = btn_h
            b.font_size = btn_font
            self._sync_button_text_size(b, None)

        self._menu_overlay.height = max(dp(250), min(dp(360), self.height * 0.7))
        self._menu_title.height = max(dp(34), min(dp(56), short_side * 0.12))
        self._menu_title.font_size = max(dp(18), min(dp(30), short_side * 0.065))
        self._menu_start_btn.height = max(dp(50), min(dp(72), short_side * 0.14))
        self._menu_difficulty_btn.height = self._menu_start_btn.height
        self._menu_start_btn.font_size = max(dp(14), min(dp(22), short_side * 0.046))
        self._menu_difficulty_btn.font_size = self._menu_start_btn.font_size

        self._sync_label_text_size(self._upgrade_title, None)
        self._sync_label_text_size(self._menu_title, None)

    def reserved_widgets(self) -> list:
        widgets = []
        if self._pause_btn.opacity > 0.0 and not self._pause_btn.disabled:
            widgets.append(self._pause_btn)
        if self._ultra_btn.opacity > 0.0 and not self._ultra_btn.disabled:
            widgets.append(self._ultra_btn)
        if self._restart_btn.opacity > 0.0 and not self._restart_btn.disabled:
            widgets.append(self._restart_btn)
        if self._upgrade_overlay.opacity > 0.0 and not self._upgrade_overlay.disabled:
            widgets.append(self._upgrade_overlay)
        if self._menu_overlay.opacity > 0.0 and not self._menu_overlay.disabled:
            widgets.append(self._menu_overlay)
        if self._fire_btn is not None:
            if self._fire_btn.opacity > 0.0 and not self._fire_btn.disabled:
                widgets.insert(0, self._fire_btn)
        return widgets

    def show_game_over(self) -> None:
        self._restart_btn.opacity = 1.0
        self._restart_btn.disabled = False

    def hide_game_over(self) -> None:
        self._restart_btn.opacity = 0.0
        self._restart_btn.disabled = True

    def show_upgrade(self, options: list[dict]) -> None:
        self._upgrade_overlay.opacity = 1.0
        self._upgrade_overlay.disabled = False
        for i, b in enumerate(self._upgrade_buttons):
            if i >= len(options):
                b.text = "..."
                b.disabled = True
                continue
            o = options[i]
            b.text = f"{o['title']}\n{o['desc']}"
            b.disabled = False

    def hide_upgrade(self) -> None:
        self._upgrade_overlay.opacity = 0.0
        self._upgrade_overlay.disabled = True

    def set_ultra_enabled(self, enabled: bool) -> None:
        self._ultra_btn.disabled = not bool(enabled)
        self._ultra_btn.opacity = 1.0 if enabled else 0.25

    def set_fire_enabled(self, enabled: bool) -> None:
        if self._fire_btn is None:
            return
        self._fire_btn.disabled = not bool(enabled)
        self._fire_btn.opacity = 1.0 if enabled else 0.25

    def set_pause_visible(self, visible: bool) -> None:
        self._pause_btn.disabled = not bool(visible)
        self._pause_btn.opacity = 1.0 if visible else 0.0

    def set_pause_state(self, paused: bool) -> None:
        self._pause_btn.text = "RESUME" if paused else "PAUSE"

    def show_menu(self, difficulty_text: str) -> None:
        self._menu_difficulty_btn.text = f"DIFFICULTY: {difficulty_text.upper()}"
        self._menu_overlay.opacity = 1.0
        self._menu_overlay.disabled = False

    def hide_menu(self) -> None:
        self._menu_overlay.opacity = 0.0
        self._menu_overlay.disabled = True
