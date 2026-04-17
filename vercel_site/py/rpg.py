"""Boss reward helpers for the browser build."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from player import Player


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
    "perm_double_dash": "Dash2",
}


def recompute_temp_mods(active_temp_rewards: list[dict]) -> dict[str, float]:
    """Return computed modifier values from active temp rewards."""
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
    """Add or refresh a temp reward in the active list."""
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
    """Apply a permanent reward to the player."""
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
    """Pick 3 temp and 3 perm reward candidates."""
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
