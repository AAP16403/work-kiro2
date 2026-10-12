"""Boss reward menu: temporary cards + permanent run boosts."""

from __future__ import annotations

import math
import random
import time
from typing import TYPE_CHECKING

import pyglet
from pyglet import shapes

from config import SHIELD_MAX, ULTRA_MAX_CHARGES_HARD_CAP
from menu import (
    _ui_scale,
    UI_FONT_HEAD,
    UI_FONT_BODY,
    UI_FONT_META,
    _sync_label_style_if_ready,
)

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
    {"key": "temp_boost_overdrive", "title": "Hyper Overdrive", "desc": "Infinite Boost + 25% speed for 2 waves", "duration": 2},
    {"key": "temp_crit_lens", "title": "Targeting Optics", "desc": "+25% Crit Chance & +0.5 Crit Mult for 2 waves", "duration": 2},
]

PERM_REWARD_POOL: list[dict] = [
    {"key": "perm_damage", "title": "Core Damage", "desc": "+1 damage this run"},
    {"key": "perm_speed", "title": "Servo Boost", "desc": "+6 move speed this run"},
    {"key": "perm_hp", "title": "Hull Plating", "desc": "+6 max HP this run"},
    {"key": "perm_fire", "title": "Trigger Tuning", "desc": "Slightly faster shots this run"},
    {"key": "perm_shield", "title": "Shield Layer", "desc": "+18 shield now"},
    {"key": "perm_ultra", "title": "Ultra Charge", "desc": "+1 Ultra charge now and +1 max (up to 4)"},
    {"key": "perm_dash", "title": "Quick Dash", "desc": "Dash cooldown reduced this run"},
    {"key": "perm_double_dash", "title": "Double Dash", "desc": "+1 dash charge this run"},
    {"key": "perm_boost_cap", "title": "Boost Battery", "desc": "+30 Max Boost energy this run"},
    {"key": "perm_crit", "title": "Precision Calibration", "desc": "+10% Crit Chance & +0.4x Crit Mult this run"},
]

TEMP_REWARD_NAMES: dict[str, str] = {
    "temp_overdrive": "Overdrive",
    "temp_haste": "Haste",
    "temp_rapidfire": "Rapidfire",
    "temp_magnet": "Magnet",
    "temp_guard": "Guard",
    "temp_ultra_flux": "Ultra Flux",
    "temp_boost_overdrive": "Hyper Boost",
    "temp_crit_lens": "Optics",
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
    "perm_boost_cap": "Boost+",
    "perm_crit": "Crit+",
}

# Floors and caps shared by apply_perm_reward and the no-op filter in roll_boss_rewards.
_SHIELD_CAP = SHIELD_MAX  # same cap as pickups, the HUD bar and powerup.py
_DASH_CD_FLOOR = 0.6
_FIRE_RATE_FLOOR = 0.12

# ---------------------------------------------------------------------------
# Reward computation helpers
# ---------------------------------------------------------------------------


def recompute_temp_mods(active_temp_rewards: list[dict]) -> dict[str, float | bool]:
    """Return a dict of computed modifier values from active temp rewards."""
    dmg = 1.0
    speed = 1.0
    fire = 1.0
    magnet = 0.0
    incoming = 1.0
    ultra_cd = 1.0
    crit_chance = 0.0
    crit_mult = 0.0
    boost_inf = False
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
        elif k == "temp_boost_overdrive":
            speed *= 1.25
            boost_inf = True
        elif k == "temp_crit_lens":
            crit_chance += 0.25
            crit_mult += 0.50
    return {
        "damage": dmg,
        "speed": speed,
        "fire_rate": fire,
        "magnet": magnet,
        "incoming_damage": incoming,
        "ultra_cd": ultra_cd,
        "crit_chance": crit_chance,
        "crit_mult": crit_mult,
        "boost_inf": boost_inf,
    }


def advance_temp_rewards(active_list: list[dict]) -> list[dict]:
    """Decrement wave counters and return kept rewards."""
    kept: list[dict] = []
    for fx in active_list:
        left = int(fx.get("waves_left", fx.get("duration", 0))) - 1
        if left > 0:
            fx["waves_left"] = left
            fx["duration"] = left
            kept.append(fx)
    return kept


def apply_temp_reward(active_list: list[dict], key: str, duration: int) -> list[dict]:
    """Add or refresh a temp reward in the active list, return updated list."""
    k = str(key or "").strip().lower()
    dur = max(2, min(3, int(duration)))
    for fx in active_list:
        if str(fx.get("key", "")) == k:
            cur = int(fx.get("waves_left", fx.get("duration", 0)))
            fx["waves_left"] = max(cur, dur)
            fx["duration"] = fx["waves_left"]
            return active_list
    active_list.append({"key": k, "waves_left": dur, "duration": dur})
    return active_list


def apply_perm_reward(
    player: "Player",
    run_perms: list[str],
    key: str,
    dash_cd_mult: float,
    ultra_max_charges: int = 2,
) -> tuple[float, bool]:
    """Apply a permanent reward to the player.

    ``ultra_max_charges`` is only a fallback base capacity for players that do not
    track their own ``ultra_max_charges``. Returns ``(updated_dash_cd_mult, applied)``."""
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
        player.fire_rate = max(_FIRE_RATE_FLOOR, float(player.fire_rate) - 0.006)
    elif k == "perm_shield":
        player.shield = min(_SHIELD_CAP, int(getattr(player, "shield", 0)) + 18)
    elif k == "perm_ultra":
        cap_now = int(getattr(player, "ultra_max_charges", ultra_max_charges))
        player.ultra_max_charges = min(ULTRA_MAX_CHARGES_HARD_CAP, cap_now + 1)
        player.ultra_charges = min(int(player.ultra_max_charges), int(player.ultra_charges) + 1)
    elif k == "perm_dash":
        dash_cd_mult = max(_DASH_CD_FLOOR, float(dash_cd_mult) * 0.90)
    elif k == "perm_double_dash":
        player.dash_max_charges = min(2, int(getattr(player, "dash_max_charges", 1)) + 1)
        player.dash_charges = int(player.dash_max_charges)
    elif k == "perm_boost_cap":
        player.boost_max_energy = float(getattr(player, "boost_max_energy", 100.0)) + 30.0
        player.boost_energy = min(player.boost_max_energy, float(getattr(player, "boost_energy", 100.0)) + 30.0)
    elif k == "perm_crit":
        player.crit_chance_bonus = float(getattr(player, "crit_chance_bonus", 0.0)) + 0.10
        player.crit_mult_bonus = float(getattr(player, "crit_mult_bonus", 0.0)) + 0.40
    else:
        applied = False

    if applied and k not in run_perms:
        run_perms.append(k)

    return dash_cd_mult, applied


def _perm_is_noop(key: str, player: "Player | None", dash_cd_mult: float) -> bool:
    """True when applying this permanent reward would change nothing right now."""
    if key == "perm_dash":
        return float(dash_cd_mult) <= _DASH_CD_FLOOR
    if player is None:
        return False
    if key == "perm_shield":
        return int(getattr(player, "shield", 0)) >= _SHIELD_CAP
    if key == "perm_ultra":
        return int(getattr(player, "ultra_max_charges", 2)) >= ULTRA_MAX_CHARGES_HARD_CAP
    if key == "perm_double_dash":
        return int(getattr(player, "dash_max_charges", 1)) >= 2
    if key == "perm_fire":
        return float(getattr(player, "fire_rate", 1.0)) <= _FIRE_RATE_FLOOR
    return False


def roll_boss_rewards(
    active_temp_rewards: list[dict],
    last_temp_key: str,
    last_perm_key: str,
    player: "Player | None" = None,
    dash_cd_mult: float = 1.0,
) -> tuple[list[dict], list[dict]]:
    """Pick up to 3 temp and 3 perm reward candidates. Returns (temp_opts, perm_opts).

    Perm candidates that would be no-ops for this player are dropped. When fewer than
    3 remain, fewer cards are returned rather than re-adding the filtered pool."""
    active_temp = {str(x.get("key", "")) for x in active_temp_rewards}
    temp_candidates = [
        x for x in TEMP_REWARD_POOL
        if x["key"] not in active_temp and x["key"] != last_temp_key
    ]
    if len(temp_candidates) < 3:
        temp_candidates = [x for x in TEMP_REWARD_POOL if x["key"] not in active_temp] or list(TEMP_REWARD_POOL)

    perm_candidates = [
        x for x in PERM_REWARD_POOL
        if x["key"] != last_perm_key and not _perm_is_noop(x["key"], player, dash_cd_mult)
    ]

    temp_opts = random.sample(temp_candidates, k=min(3, len(temp_candidates)))
    perm_opts = random.sample(perm_candidates, k=min(3, len(perm_candidates)))
    return temp_opts, perm_opts


def format_temp_hud(active_list: list[dict]) -> str:
    """Build the HUD string for active temporary rewards."""
    if not active_list:
        return ""
    parts: list[str] = []
    for fx in active_list[:2]:
        key = str(fx.get("key", ""))
        left = int(fx.get("waves_left", fx.get("duration", 0)))
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


# ---------------------------------------------------------------------------
# Presentation: categories, accents and animation timing (no gameplay data)
# ---------------------------------------------------------------------------

# Category tag and accent colour per reward key. Presentation only: the reward
# pools above are unchanged.
REWARD_CATEGORY: dict[str, str] = {
    "temp_overdrive": "OFFENSE",
    "temp_haste": "MOBILITY",
    "temp_rapidfire": "OFFENSE",
    "temp_magnet": "UTILITY",
    "temp_guard": "DEFENSE",
    "temp_ultra_flux": "ULTRA",
    "temp_boost_overdrive": "MOBILITY",
    "temp_crit_lens": "OFFENSE",
    "perm_damage": "OFFENSE",
    "perm_speed": "MOBILITY",
    "perm_hp": "DEFENSE",
    "perm_fire": "OFFENSE",
    "perm_shield": "DEFENSE",
    "perm_ultra": "ULTRA",
    "perm_dash": "MOBILITY",
    "perm_double_dash": "MOBILITY",
    "perm_boost_cap": "MOBILITY",
    "perm_crit": "OFFENSE",
}

CATEGORY_COLORS: dict[str, tuple[int, int, int]] = {
    "OFFENSE": (255, 116, 98),
    "MOBILITY": (98, 196, 255),
    "DEFENSE": (122, 228, 152),
    "UTILITY": (255, 214, 110),
    "ULTRA": (200, 142, 255),
    "BOON": (160, 176, 204),
}

TEMP_ACCENT = (96, 226, 214)
PERM_ACCENT = (255, 200, 92)

_PANEL_ENTER_T = 0.35  # panel fade + slide-in duration (s)
_CARD_STAGGER_T = 0.06  # delay between consecutive cards (s)
_CARD_FADE_T = 0.28  # each card's own fade-in duration (s)
_CARD_CLOCK_START = -0.10  # cards trail the panel slightly on first open
_CARD_CLOCK_DONE = 1.0

_CARD_IDLE_FILL = (16, 30, 48)
_CARD_HOT_FILL = (34, 62, 96)
_CARD_IDLE_BORDER = (110, 160, 214)
_CARD_HOT_BORDER = (206, 234, 255)
_TEXT_BRIGHT = (236, 244, 255, 255)
_TEXT_MUTED = (170, 184, 208, 255)


def _mix(a: tuple, b: tuple, t: float) -> tuple[int, int, int]:
    """Linear blend of two RGB tuples."""
    t = max(0.0, min(1.0, float(t)))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]


def _ease_out(t: float) -> float:
    t = max(0.0, min(1.0, float(t)))
    return 1.0 - (1.0 - t) ** 3


def _approach(cur: float, target: float, dt: float, rate: float = 14.0) -> float:
    """Frame-rate independent exponential smoothing toward target."""
    return cur + (target - cur) * (1.0 - math.exp(-rate * dt))


def _put_label(label, x: float, y: float, alpha: float) -> None:
    label.x = x
    label.y = y
    label.opacity = int(255 * max(0.0, min(1.0, alpha)))


class _RewardCard:
    """One selectable reward row: accent stripe, number badge, title, description and tag."""

    def __init__(self, index: int, batch: pyglet.graphics.Batch):
        self.index = index
        self.enabled = False
        self.hovered = False
        self.selected = False
        self.lift = 0.0  # smoothed hover amount, 0..1
        self.focus = 0.0  # smoothed keyboard-selection amount, 0..1
        self.enter = 1.0  # entrance progress, set by the menu each frame
        self.active = False  # False: hidden, not laid out and not selectable
        self.accent = CATEGORY_COLORS["BOON"]

        self._glow_outer = shapes.Rectangle(0, 0, 1, 1, color=self.accent, batch=batch)
        self._glow_inner = shapes.Rectangle(0, 0, 1, 1, color=self.accent, batch=batch)
        self._border = shapes.Rectangle(0, 0, 1, 1, color=_CARD_IDLE_BORDER, batch=batch)
        self._body = shapes.Rectangle(0, 0, 1, 1, color=_CARD_IDLE_FILL, batch=batch)
        self._shine = shapes.Rectangle(0, 0, 1, 1, color=(255, 255, 255), batch=batch)
        self._stripe = shapes.Rectangle(0, 0, 1, 1, color=self.accent, batch=batch)
        self._badge = shapes.Rectangle(0, 0, 1, 1, color=self.accent, batch=batch)
        self._badge_text = pyglet.text.Label(
            str(index + 1),
            font_name=UI_FONT_HEAD,
            font_size=14,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            color=(8, 14, 24, 255),
            batch=batch,
        )
        self.title = pyglet.text.Label(
            "",
            font_name=UI_FONT_BODY,
            font_size=18,
            x=0,
            y=0,
            anchor_x="left",
            anchor_y="center",
            color=_TEXT_BRIGHT,
            batch=batch,
        )
        self.desc = pyglet.text.Label(
            "",
            font_name=UI_FONT_META,
            font_size=14,
            x=0,
            y=0,
            width=200,
            multiline=True,
            anchor_x="left",
            anchor_y="center",
            color=_TEXT_MUTED,
            batch=batch,
        )
        self.tag = pyglet.text.Label(
            "",
            font_name=UI_FONT_BODY,
            font_size=12,
            x=0,
            y=0,
            anchor_x="right",
            anchor_y="center",
            color=(*self.accent, 255),
            batch=batch,
        )
        self._parts = (
            self._glow_outer, self._glow_inner, self._border, self._body, self._shine, self._stripe,
            self._badge, self._badge_text, self.title, self.desc, self.tag,
        )
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        """Show or hide the whole card. A hidden card is not drawn, hit-tested or selectable."""
        self.active = bool(active)
        if not self.active:
            self.enabled = False
            self.hovered = False
            self.selected = False
        for part in self._parts:
            part.visible = self.active

    def set_option(self, opt: dict, stage: str) -> None:
        key = str(opt.get("key", "")).strip()
        self.enabled = bool(key)
        self.title.text = str(opt.get("title", ""))
        self.desc.text = str(opt.get("desc", ""))
        if key:
            category = REWARD_CATEGORY.get(key, "BOON")
            if stage == "temp":
                tail = f"{int(opt.get('duration', 2))} WAVES"
            else:
                tail = "THIS RUN"
            self.tag.text = f"{category}  \u00b7  {tail}"
            self.accent = CATEGORY_COLORS.get(category, CATEGORY_COLORS["BOON"])
        else:
            self.tag.text = ""
            self.accent = CATEGORY_COLORS["BOON"]
        self._glow_outer.color = self.accent
        self._glow_inner.color = self.accent
        self._stripe.color = self.accent
        self._badge.color = self.accent
        self.tag.color = (*self.accent, 255)

    def set_metrics(self, s: float, card_w: float) -> None:
        _sync_label_style_if_ready(self._badge_text, UI_FONT_HEAD, max(10, int(14 * s)))
        _sync_label_style_if_ready(self.title, UI_FONT_BODY, max(13, int(18 * s)))
        _sync_label_style_if_ready(self.desc, UI_FONT_META, max(11, int(14 * s)))
        _sync_label_style_if_ready(self.tag, UI_FONT_BODY, max(10, int(12 * s)))
        self.desc.width = max(60, int(card_w - 90 * s))

    def step(self, dt: float) -> None:
        self.lift = _approach(self.lift, 1.0 if (self.hovered and self.enabled) else 0.0, dt)
        self.focus = _approach(self.focus, 1.0 if (self.selected and self.enabled) else 0.0, dt)

    def place(self, x: float, y: float, w: float, h: float, s: float, panel_alpha: float, panel_dy: float) -> None:
        if not self.active:
            return
        hot = max(self.lift, self.focus)
        live = 1.0 if self.enabled else 0.55
        a = max(0.0, min(1.0, panel_alpha * self.enter)) * live
        base_y = y + panel_dy + (-(1.0 - self.enter) * 18.0 + 4.0 * self.lift) * s

        pad = 12.0 * s
        self._glow_outer.x = x - pad
        self._glow_outer.y = base_y - pad
        self._glow_outer.width = w + 2 * pad
        self._glow_outer.height = h + 2 * pad
        self._glow_outer.opacity = int(60 * hot * a)

        pad = 4.0 * s
        self._glow_inner.x = x - pad
        self._glow_inner.y = base_y - pad
        self._glow_inner.width = w + 2 * pad
        self._glow_inner.height = h + 2 * pad
        self._glow_inner.opacity = int(90 * hot * a)

        pad = (2.0 + 2.0 * hot) * s
        self._border.x = x - pad
        self._border.y = base_y - pad
        self._border.width = w + 2 * pad
        self._border.height = h + 2 * pad
        self._border.color = _mix(_mix(_CARD_IDLE_BORDER, _CARD_HOT_BORDER, self.lift), self.accent, self.focus)
        self._border.opacity = int(min(255.0, 70.0 + 150.0 * hot) * a)

        self._body.x = x
        self._body.y = base_y
        self._body.width = w
        self._body.height = h
        self._body.color = _mix(_CARD_IDLE_FILL, _CARD_HOT_FILL, hot)
        self._body.opacity = int(236 * a)

        strip_h = max(3, int(h * 0.14))
        self._shine.x = x + 2 * s
        self._shine.y = base_y + h - strip_h - 2 * s
        self._shine.width = max(1.0, w - 4 * s)
        self._shine.height = strip_h
        self._shine.opacity = int((14 + 40 * hot) * a)

        self._stripe.x = x
        self._stripe.y = base_y
        self._stripe.width = max(3, int(5 * s))
        self._stripe.height = h
        self._stripe.opacity = int(255 * a)

        bs = max(20.0, 30.0 * s)
        self._badge.x = x + 18 * s
        self._badge.y = base_y + (h - bs) / 2
        self._badge.width = bs
        self._badge.height = bs
        self._badge.opacity = int(min(255.0, 150.0 + 105.0 * hot) * a)
        _put_label(self._badge_text, self._badge.x + bs / 2, base_y + h / 2, a)

        text_x = x + 18 * s + bs + 14 * s
        _put_label(self.title, text_x, base_y + h * 0.64, a)
        _put_label(self.desc, text_x, base_y + h * 0.30, a)
        _put_label(self.tag, x + w - 20 * s, base_y + h * 0.64, a)


class BossRewardMenu:
    """Two-step reward menu shown after boss waves.

    Step 1 offers temporary cards (2-3 waves); step 2 offers permanent run boosts.
    Mouse: clicking a card picks it. Keyboard: 1-3 highlight a card and
    ENTER or SPACE confirms it (same path as a click). ``on_mouse_press`` and
    ``on_key_press`` return "done" when the whole flow completes.
    A step with fewer than three options shows only those cards, centred. A step
    with none shows an empty note, and ENTER or a click moves on.
    """

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
        self._section_rule = shapes.Rectangle(0, 0, 1, 1, color=TEMP_ACCENT, batch=self.batch)
        self._section_rule.opacity = 140

        self.eyebrow = pyglet.text.Label(
            "P L O U T O  //  BOSS REWARD",
            font_name=UI_FONT_META,
            font_size=11,
            x=width // 2,
            y=height // 2,
            anchor_x="center",
            anchor_y="center",
            color=(120, 150, 190, 255),
            batch=self.batch,
        )
        self.title = pyglet.text.Label(
            "BOSS DEFEATED",
            font_name=UI_FONT_HEAD,
            font_size=30,
            x=width // 2,
            y=height // 2,
            anchor_x="center",
            anchor_y="center",
            color=(230, 240, 255, 255),
            batch=self.batch,
        )
        self.subtitle = pyglet.text.Label(
            "",
            font_name=UI_FONT_BODY,
            font_size=15,
            x=width // 2,
            y=height // 2,
            anchor_x="center",
            anchor_y="center",
            color=(170, 185, 210, 255),
            batch=self.batch,
        )
        self.section = pyglet.text.Label(
            "",
            font_name=UI_FONT_HEAD,
            font_size=12,
            x=0,
            y=0,
            anchor_x="left",
            anchor_y="center",
            color=(*TEMP_ACCENT, 255),
            batch=self.batch,
        )
        self.section_note = pyglet.text.Label(
            "",
            font_name=UI_FONT_BODY,
            font_size=13,
            x=0,
            y=0,
            anchor_x="right",
            anchor_y="center",
            color=(150, 166, 194, 255),
            batch=self.batch,
        )
        self.tip = pyglet.text.Label(
            "",
            font_name=UI_FONT_META,
            font_size=12,
            x=width // 2,
            y=height // 2,
            anchor_x="center",
            anchor_y="center",
            color=(145, 160, 190, 255),
            batch=self.batch,
        )

        self._empty = pyglet.text.Label(
            "Nothing to pick this time",
            font_name=UI_FONT_BODY,
            font_size=16,
            x=width // 2,
            y=height // 2,
            anchor_x="center",
            anchor_y="center",
            color=(150, 166, 194, 255),
            batch=self.batch,
        )
        self._empty.visible = False

        self._cards: list[_RewardCard] = [_RewardCard(i, self.batch) for i in range(3)]

        self._temp_opts: list[dict] = []
        self._perm_opts: list[dict] = []
        self._stage = "temp"
        self._selected: int | None = None
        self._hovered: int | None = None
        self._panel_clock = _PANEL_ENTER_T
        self._card_clock = _CARD_CLOCK_DONE
        self._ticked = False
        self._last_draw: float | None = None
        self._s = 1.0
        self._panel_x = 0
        self._panel_y = 0
        self._panel_w = 1
        self._panel_h = 1
        self._card_x = 0.0
        self._card_top = 0.0
        self._card_region_top = 0.0
        self._avail_h = 1.0
        self._card_w = 1.0
        self._card_h = 1.0
        self._card_gap = 0.0
        self._sync_stage_labels()
        self.resize(width, height)
        self._sync_buttons()

    def begin(self, temp_options: list[dict], perm_options: list[dict]) -> None:
        # Only real options become cards: fewer than three means fewer cards, never placeholders.
        self._temp_opts = [o for o in list(temp_options or []) if str(o.get("key", "")).strip()][:3]
        self._perm_opts = [o for o in list(perm_options or []) if str(o.get("key", "")).strip()][:3]
        self._stage = "temp"
        self._reset_pointer_state()
        self._panel_clock = 0.0
        self._card_clock = _CARD_CLOCK_START
        self._sync_stage_labels()
        self._sync_buttons()

    def _reset_pointer_state(self) -> None:
        self._selected = None
        self._hovered = None
        for card in self._cards:
            card.hovered = False
            card.selected = False

    def _sync_stage_labels(self) -> None:
        if self._stage == "temp":
            accent = TEMP_ACCENT
            self.section.text = "STEP 1 OF 2  //  CHOOSE A TEMPORARY CARD"
            self.section_note.text = "lasts 2-3 waves"
        else:
            accent = PERM_ACCENT
            self.section.text = "STEP 2 OF 2  //  CHOOSE A PERMANENT BOOST"
            self.section_note.text = "lasts the rest of this run"
        self.section.color = (*accent, 255)
        self._section_rule.color = accent
        self.subtitle.text = "Step 1: temporary card (lasts 2-3 waves)   >   Step 2: permanent boost (lasts the run)"
        self.tip.text = self._tip_text()

    def _current_options(self) -> list[dict]:
        return self._temp_opts if self._stage == "temp" else self._perm_opts

    def _visible_count(self) -> int:
        """How many cards the current step shows: one per real option, at most three."""
        return min(len(self._cards), len(self._current_options()))

    def _tip_text(self) -> str:
        if self._visible_count() == 0:
            return "ENTER or click to continue"
        return "1-3 choose  |  ENTER confirm"

    def _sync_buttons(self) -> None:
        options = self._current_options()
        for i, card in enumerate(self._cards):
            if i < len(options):
                card.set_option(options[i], self._stage)
                card.set_active(True)
            else:
                card.set_active(False)
        self._empty.visible = not options
        self.tip.text = self._tip_text()
        self._layout_cards()

    def _layout_cards(self) -> None:
        """Stack the visible cards and centre that stack vertically in the card region."""
        n = self._visible_count()
        block_h = n * self._card_h + max(0, n - 1) * self._card_gap
        self._card_top = self._card_region_top - max(0.0, (self._avail_h - block_h) / 2.0)

    def _card_rect(self, i: int) -> tuple[float, float, float, float]:
        """Resting rectangle (x, y, w, h) of card i, ignoring entrance and hover motion."""
        y = self._card_top - (i + 1) * self._card_h - i * self._card_gap
        return (self._card_x, y, self._card_w, self._card_h)

    def _hit_index(self, x: float, y: float) -> int | None:
        for i in range(self._visible_count()):
            bx, by, bw, bh = self._card_rect(i)
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return i
        return None

    def resize(self, width: int, height: int):
        self.screen_width = width
        self.screen_height = height
        self.overlay.width = width
        self.overlay.height = height
        cx = width // 2
        cy = height // 2
        s = min(_ui_scale(width, height), 1.45)
        self._s = s

        panel_w = min(int(width * 0.9), int(980 * s))
        panel_h = min(int(height * 0.82), int(520 * s))
        self._panel_w = panel_w
        self._panel_h = panel_h
        self._panel_x = cx - panel_w // 2
        self._panel_y = cy - panel_h // 2

        # Header block on top, footer hint at the bottom, card stack centred between them.
        # Card height is sized for three slots so one or two cards keep the same size.
        header_h = 146.0 * s
        footer_h = 46.0 * s
        gap = 14.0 * s
        avail = max(1.0, panel_h - header_h - footer_h)
        bh = max(54.0 * s, min(88.0 * s, (avail - 2 * gap) / 3.0))
        bw = min(int(panel_w * 0.84), int(680 * s))
        self._card_w = float(bw)
        self._card_h = bh
        self._card_gap = gap
        self._card_x = cx - bw // 2
        self._card_region_top = self._panel_y + panel_h - header_h
        self._avail_h = avail
        self._layout_cards()

        _sync_label_style_if_ready(self._empty, UI_FONT_BODY, max(11, int(16 * s)))
        _sync_label_style_if_ready(self.eyebrow, UI_FONT_META, max(9, int(11 * s)))
        _sync_label_style_if_ready(self.title, UI_FONT_HEAD, max(18, int(30 * s)))
        _sync_label_style_if_ready(self.subtitle, UI_FONT_BODY, max(11, int(15 * s)))
        _sync_label_style_if_ready(self.section, UI_FONT_HEAD, max(9, int(12 * s)))
        _sync_label_style_if_ready(self.section_note, UI_FONT_BODY, max(10, int(13 * s)))
        _sync_label_style_if_ready(self.tip, UI_FONT_META, max(9, int(12 * s)))
        for card in self._cards:
            card.set_metrics(s, bw)

        self._place_all()

    def update(self, dt: float) -> None:
        """Advance the entrance and hover/focus animations. Call once per frame."""
        self._ticked = True
        dt = max(0.0, min(float(dt), 0.1))
        self._panel_clock = min(_PANEL_ENTER_T, self._panel_clock + dt)
        self._card_clock = min(_CARD_CLOCK_DONE, self._card_clock + dt)
        for card in self._cards:
            card.step(dt)

    def _place_all(self) -> None:
        s = self._s
        px, py, pw, ph = self._panel_x, self._panel_y, self._panel_w, self._panel_h
        cx = self.screen_width // 2
        pa = _ease_out(self._panel_clock / _PANEL_ENTER_T)
        dy = -(1.0 - pa) * 34.0 * s  # panel rises into place
        top = py + ph + dy

        self.overlay.opacity = int(220 * pa)
        self._panel_border.x = px - 3
        self._panel_border.y = py + dy - 3
        self._panel_border.width = pw + 6
        self._panel_border.height = ph + 6
        self._panel_border.opacity = int(52 * pa)
        self._panel.x = px
        self._panel.y = py + dy
        self._panel.width = pw
        self._panel.height = ph
        self._panel.opacity = int(228 * pa)
        self._panel_shine.x = px + 4
        self._panel_shine.y = top - max(8, int(22 * s))
        self._panel_shine.width = pw - 8
        self._panel_shine.height = max(6, int(14 * s))
        self._panel_shine.opacity = int(16 * pa)

        _put_label(self.eyebrow, cx, top - 34 * s, pa)
        _put_label(self.title, cx, top - 56 * s, pa)
        _put_label(self.subtitle, cx, top - 88 * s, pa)
        sec_y = top - 116 * s
        _put_label(self.section, px + 30 * s, sec_y, pa)
        _put_label(self.section_note, px + pw - 30 * s, sec_y, pa)
        self._section_rule.x = px + 30 * s
        self._section_rule.y = top - 128 * s
        self._section_rule.width = pw - 60 * s
        self._section_rule.height = max(2, int(2 * s))
        self._section_rule.opacity = int(140 * pa)
        _put_label(self.tip, cx, py + dy + 22 * s, pa)
        _put_label(self._empty, cx, self._card_region_top - self._avail_h / 2.0 + dy, pa)

        for i, card in enumerate(self._cards):
            card.enter = _ease_out((self._card_clock - i * _CARD_STAGGER_T) / _CARD_FADE_T)
            x, y, w, h = self._card_rect(i)
            card.place(x, y, w, h, s, pa, dy)

    def on_mouse_motion(self, x: float, y: float):
        hit = self._hit_index(x, y)
        self._hovered = hit
        for i, card in enumerate(self._cards):
            card.hovered = i == hit

    def on_mouse_press(self, x: float, y: float, button: int) -> str | None:
        if button != pyglet.window.mouse.LEFT:
            return None
        if self._visible_count() == 0:
            return self._continue_empty()
        hit = self._hit_index(x, y)
        if hit is None:
            return None
        return self._choose(hit)

    def on_key_press(self, symbol: int) -> str | None:
        """Keyboard path: 1-3 (or numpad 1-3) highlight a card; ENTER or SPACE confirms it."""
        k = pyglet.window.key
        index_for = {k._1: 0, k._2: 1, k._3: 2, k.NUM_1: 0, k.NUM_2: 1, k.NUM_3: 2}
        if symbol in index_for:
            i = index_for[symbol]
            if i < self._visible_count():
                self._selected = i
                for j, card in enumerate(self._cards):
                    card.selected = j == i
            return None
        if symbol in (k.ENTER, k.NUM_ENTER, k.SPACE):
            if self._visible_count() == 0:
                return self._continue_empty()
            if self._selected is None:
                return None
            return self._choose(self._selected)
        return None

    def _continue_empty(self) -> str | None:
        """Leave a step that has no options. The temporary step hands over to the permanent one."""
        if self._stage == "temp":
            self._stage = "perm"
            self._reset_pointer_state()
            self._card_clock = 0.0
            self._sync_stage_labels()
            self._sync_buttons()
            return None
        return "done"

    def _choose(self, i: int) -> str | None:
        options = self._current_options()
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
            self._reset_pointer_state()
            self._card_clock = 0.0  # re-stagger the cards for the permanent step
            self._sync_stage_labels()
            self._sync_buttons()
            return None
        self._on_pick_perm(key)
        return "done"

    def draw(self):
        now = time.perf_counter()
        if not self._ticked:
            # update(dt) was not called this frame: advance here so the
            # entrance and hover animations still run.
            dt = (now - self._last_draw) if self._last_draw is not None else 1.0 / 60.0
            self.update(dt)
        self._ticked = False
        self._last_draw = now
        self._place_all()
        self.batch.draw()
