"""Boss reward menu: temporary cards + permanent run boosts."""

from __future__ import annotations

import random
from typing import Optional, TYPE_CHECKING

import pyglet
from pyglet import shapes

from menu import MenuButton, _ui_scale, UI_FONT_HEAD, UI_FONT_BODY, UI_FONT_META

if TYPE_CHECKING:
    from player import Player

# ---------------------------------------------------------------------------
# Reward pool definitions
# ---------------------------------------------------------------------------

TEMP_REWARD_POOL: list[dict] = [
    {"key": "temp_overdrive", "title": "Overdrive", "desc": "+28% damage for 2 waves", "duration": 2},
    {"key": "temp_haste", "title": "Haste Drive", "desc": "+22% move speed for 3 waves", "duration": 3},
    {"key": "temp_rapidfire", "title": "Hot Trigger", "desc": "22% faster fire-rate for 2 waves", "duration": 2},
    {"key": "temp_magnet", "title": "Magnet Core", "desc": "Wider pickup magnet for 3 waves", "duration": 3},
    {"key": "temp_guard", "title": "Aegis Skin", "desc": "-18% incoming damage for 2 waves", "duration": 2},
    {"key": "temp_ultra_flux", "title": "Ultra Flux", "desc": "Ultra cooldown reduced for 3 waves", "duration": 3},
]

PERM_REWARD_POOL: list[dict] = [
    {"key": "perm_damage", "title": "Core Damage", "desc": "+1 damage this run"},
    {"key": "perm_speed", "title": "Servo Boost", "desc": "+6 move speed this run"},
    {"key": "perm_hp", "title": "Hull Plating", "desc": "+6 max HP this run"},
    {"key": "perm_fire", "title": "Trigger Tuning", "desc": "Slightly faster shots this run"},
    {"key": "perm_shield", "title": "Shield Layer", "desc": "+18 shield now"},
    {"key": "perm_ultra", "title": "Ultra Charge", "desc": "+1 Ultra charge now"},
    {"key": "perm_dash", "title": "Quick Dash", "desc": "Dash cooldown reduced this run"},
    {"key": "perm_double_dash", "title": "Double Dash", "desc": "+1 dash charge this run"},
]

TEMP_REWARD_NAMES: dict[str, str] = {
    "temp_overdrive": "Overdrive",
    "temp_haste": "Haste",
    "temp_rapidfire": "Rapidfire",
    "temp_magnet": "Magnet",
    "temp_guard": "Guard",
    "temp_ultra_flux": "Ultra Flux",
}

PERM_REWARD_NAMES: dict[str, str] = {
    "perm_damage": "Core Damage",
    "perm_speed": "Servo",
    "perm_hp": "Hull",
    "perm_fire": "Trigger",
    "perm_shield": "Shield",
    "perm_ultra": "Ultra+",
    "perm_dash": "Dash+",
    "perm_double_dash": "Dash\u00b2",
}

# ---------------------------------------------------------------------------
# Reward computation helpers
# ---------------------------------------------------------------------------


def recompute_temp_mods(active_temp_rewards: list[dict]) -> dict[str, float]:
    """Return a dict of computed modifier values from active temp rewards."""
    dmg = 1.0
    speed = 1.0
    fire = 1.0
    magnet = 0.0
    incoming = 1.0
    ultra_cd = 1.0
    for fx in list(active_temp_rewards):
        k = str(fx.get("key", ""))
        if k == "temp_overdrive":
            dmg *= 1.28
        elif k == "temp_haste":
            speed *= 1.22
        elif k == "temp_rapidfire":
            fire *= 0.78
        elif k == "temp_magnet":
            magnet += 80.0
        elif k == "temp_guard":
            incoming *= 0.82
        elif k == "temp_ultra_flux":
            ultra_cd *= 0.7
    return {
        "damage": dmg,
        "speed": speed,
        "fire_rate": fire,
        "magnet": magnet,
        "incoming_damage": incoming,
        "ultra_cd": ultra_cd,
    }


def advance_temp_rewards(active_list: list[dict]) -> list[dict]:
    """Decrement wave counters and return kept rewards."""
    kept: list[dict] = []
    for fx in active_list:
        left = int(fx.get("waves_left", 0)) - 1
        if left > 0:
            fx["waves_left"] = left
            kept.append(fx)
    return kept


def apply_temp_reward(active_list: list[dict], key: str, duration: int) -> list[dict]:
    """Add or refresh a temp reward in the active list, return updated list."""
    k = str(key or "").strip().lower()
    dur = max(2, min(3, int(duration)))
    for fx in active_list:
        if str(fx.get("key", "")) == k:
            fx["waves_left"] = max(int(fx.get("waves_left", 0)), dur)
            return active_list
    active_list.append({"key": k, "waves_left": dur})
    return active_list


def apply_perm_reward(
    player: "Player",
    run_perms: list[str],
    key: str,
    dash_cd_mult: float,
    ultra_max_charges: int = 2,
) -> tuple[float, bool]:
    """Apply a permanent reward to the player.

    Returns ``(updated_dash_cd_mult, applied)``."""
    k = str(key or "").strip().lower()
    applied = True
    if k == "perm_damage":
        player.damage = int(player.damage) + 1
    elif k == "perm_speed":
        player.speed = float(player.speed) + 6.0
    elif k == "perm_hp":
        player.max_hp = int(getattr(player, "max_hp", player.hp)) + 6
        player.hp = min(int(player.max_hp), int(player.hp) + 6)
    elif k == "perm_fire":
        player.fire_rate = max(0.12, float(player.fire_rate) - 0.006)
    elif k == "perm_shield":
        player.shield = min(120, int(getattr(player, "shield", 0)) + 18)
    elif k == "perm_ultra":
        player.ultra_charges = min(ultra_max_charges, int(player.ultra_charges) + 1)
    elif k == "perm_dash":
        dash_cd_mult = max(0.6, float(dash_cd_mult) * 0.90)
    elif k == "perm_double_dash":
        player.dash_max_charges = min(2, int(getattr(player, "dash_max_charges", 1)) + 1)
        player.dash_charges = int(player.dash_max_charges)
    else:
        applied = False

    if applied and k not in run_perms:
        run_perms.append(k)

    return dash_cd_mult, applied


def roll_boss_rewards(
    active_temp_rewards: list[dict],
    last_temp_key: str,
    last_perm_key: str,
) -> tuple[list[dict], list[dict]]:
    """Pick 3 temp and 3 perm reward candidates. Returns (temp_opts, perm_opts)."""
    active_temp = {str(x.get("key", "")) for x in active_temp_rewards}
    temp_candidates = [
        x for x in TEMP_REWARD_POOL
        if x["key"] not in active_temp and x["key"] != last_temp_key
    ]
    if len(temp_candidates) < 3:
        temp_candidates = [x for x in TEMP_REWARD_POOL if x["key"] not in active_temp] or list(TEMP_REWARD_POOL)

    perm_candidates = [x for x in PERM_REWARD_POOL if x["key"] != last_perm_key]
    if len(perm_candidates) < 3:
        perm_candidates = list(PERM_REWARD_POOL)

    temp_opts = random.sample(temp_candidates, k=3)
    perm_opts = random.sample(perm_candidates, k=3)
    return temp_opts, perm_opts


def format_temp_hud(active_list: list[dict]) -> str:
    """Build the HUD string for active temporary rewards."""
    if not active_list:
        return ""
    parts: list[str] = []
    for fx in active_list[:2]:
        key = str(fx.get("key", ""))
        left = int(fx.get("waves_left", 0))
        if key in TEMP_REWARD_NAMES and left > 0:
            parts.append(f"{TEMP_REWARD_NAMES[key]}:{left}")
    if not parts:
        return ""
    return "Temp " + ", ".join(parts)


def format_perm_hud(run_perms: list[str]) -> str:
    """Build the HUD string for permanent run rewards."""
    if not run_perms:
        return ""
    shown: list[str] = []
    for k in run_perms[:3]:
        if k in PERM_REWARD_NAMES:
            shown.append(PERM_REWARD_NAMES[k])
    if not shown:
        return ""
    return "Run " + ",".join(shown)


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
