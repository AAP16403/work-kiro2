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
        on_shoot: Callable[[bool], None],
        on_upgrade_pick: Callable[[int], None],
        show_fire_button: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self._on_ultra = on_ultra
        self._on_restart = on_restart
        self._on_shoot = on_shoot
        self._on_upgrade_pick = on_upgrade_pick

        self.hud = Label(
            text="",
            size_hint=(1, None),
            height=dp(26),
            pos_hint={"x": 0, "top": 1},
            halign="left",
            valign="middle",
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
            size_hint=(0.74, None),
            height=dp(220),
            pos_hint={"center_x": 0.5, "center_y": 0.5},
            spacing=dp(10),
            opacity=0.0,
            disabled=True,
        )
        title = Label(
            text="Pick an upgrade",
            size_hint=(1, None),
            height=dp(32),
            color=(0.95, 0.95, 0.98, 1.0),
        )
        self._upgrade_overlay.add_widget(title)

        self._upgrade_buttons: list[Button] = []
        for idx in range(3):
            b = Button(text="...", size_hint=(1, None), height=dp(48))
            b.bind(on_release=lambda _btn, i=idx: self._on_upgrade_pick(i))
            self._upgrade_buttons.append(b)
            self._upgrade_overlay.add_widget(b)
        self.add_widget(self._upgrade_overlay)

    def reserved_widgets(self) -> list:
        widgets = [self._ultra_btn, self._restart_btn, self._upgrade_overlay]
        if self._fire_btn is not None:
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
