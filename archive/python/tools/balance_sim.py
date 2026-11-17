#!/usr/bin/env python3
"""Offline balance simulator for PLOUTO. No window and no pyglet are needed.

It prints markdown tables to stdout. With --csv PATH it also writes one tidy CSV with the
columns section, id, wave, weapon, metric, value, unit, note.

Every number comes from the game's own functions, not from copied tables:
- shots:      weapons.get_effective_fire_rate and projectile.spawn_projectiles
- enemy HP:   logic.EnemyTuningLogic.enemy_stats and get_boss_for_wave
- waves:      logic.EnemySpawnLogic.wave_cap and plan_wave (averaged over fixed seeds)
- power-ups:  powerup.apply_powerup, applied to a stub Player and diffed
Two formulas live inline in states.py (laser beam) and game.py (ultra beam). They are
mirrored here, and test_w3_balancesim.py fails if the mirrored text changes.

Usage, from the project root:
    .venv\\Scripts\\python.exe tools\\balance_sim.py
    .venv\\Scripts\\python.exe tools\\balance_sim.py --csv balance.csv --difficulty hard --ref-wave 12

Options:
    --difficulty easy|normal|hard   difficulty for wave size and enemy HP (default normal)
    --ref-wave N                    wave used for power-up values (default 12, a regular wave;
                                    boss waves are one enemy and would shrink every value)
    --damage N                      player base damage (default config.PLAYER_DAMAGE)
    --fire-rate X                   player fire rate (default config.PLAYER_FIRE_RATE)
    --vortex-coverage X             share of a wave's time an enemy spends in the vortex aura (default 0.5)
    --csv PATH                      also write the tidy CSV

Output sections:
    1. Weapon DPS: pellets, damage per pellet, crit chance, cooldown and expected DPS.
    2. Standard wave for waves 1 to 30: kind (standard or boss), enemy count, typical HP, total HP.
    3. Time to kill a typical enemy, per weapon and wave (seconds).
    4. Time to clear a standard wave, per weapon and wave (seconds).
    5. Power-up value per pickup, in damage units, with the median and the outliers
       more than 40 percent above or below it.
    6. Mutators and skins: score multiplier and implied difficulty change. These need
       wave-1 modules. When a module is missing, a [SKIP requires-wave1] line is printed.

Model and limits (read before trusting a number):
- Single target, point blank. Every pellet of a volley is assumed to hit, the same convention
  as the rank comment in weapons.py. Pierce, flak cluster splits, recoil spread and shields are
  ignored. Cadence jitter has mean 1 and is ignored too.
- Crit damage comes from spawn_projectiles. A never-crit volley and an always-crit volley are
  mixed by the weapon crit chance.
- A standard wave is the expected composition over SEEDS fixed seeds, plus the elite HP and
  shield rolls at the spawn_wave rates. A boss wave (wave % 5 == 0) is one boss.
- Time to clear a standard wave = total wave HP / DPS. Overkill, travel and misses are not modelled.
- Power-up values are in damage units: enemy HP removed over one standard wave at the reference
  wave, with the basic gun. Heal and shield count HP restored at face value. That keeps them on
  the same numeric scale, but they are not a like-for-like gameplay comparison with damage.
- Kinds with no damage or HP model (speed, boost) show n/a and are left out of the median.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import math
import os
import random
import statistics
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config  # noqa: E402
from logic import EnemySpawnLogic, EnemyTuningLogic  # noqa: E402
from player import Player  # noqa: E402
from powerup import PowerUp, apply_powerup  # noqa: E402
from projectile import spawn_projectiles  # noqa: E402
from utils import Vec2  # noqa: E402
from weapons import (  # noqa: E402
    WEAPONS,
    _pool_weights_for_wave,
    get_effective_fire_rate,
    get_weapon_pool_for_wave,
)

WAVES = tuple(range(1, 31))
SEEDS = 64              # fixed composition samples per wave, so the expected value is deterministic
CRIT_CAP = 0.85         # spawn_projectiles clamps the effective crit chance to this
OUTLIER_PCT = 0.40      # power-up outlier threshold, relative to the median
VORTEX_DEFAULT_COVERAGE = 0.5
REF_WAVE_DEFAULT = 12   # a regular wave: boss waves (5, 10, ...) hold one enemy
DIFFICULTIES = tuple(EnemyTuningLogic().difficulty_modifiers.keys())
POWERUP_CSV_COLUMNS = ("section", "id", "wave", "weapon", "metric", "value", "unit", "note")
# Power-up kinds that wave 1 adds. They are reported as skipped until they exist in config.POWERUP_COLORS.
WAVE1_POWERUP_KINDS = ("ricochet", "homing", "time_slow", "magnet")


class _FixedRng:
    """RNG stand-in for spawn_projectiles: random() is fixed and uniform() returns the midpoint."""

    def __init__(self, value: float) -> None:
        self.value = float(value)

    def random(self) -> float:
        return self.value

    def uniform(self, a: float, b: float) -> float:
        return (float(a) + float(b)) / 2.0


_ORIGIN = Vec2(0.0, 0.0)
_AIM = Vec2(1.0, 0.0)


# ---------------------------------------------------------------------------
# Weapons
# ---------------------------------------------------------------------------

def volley_breakdown(weapon, player_damage, crit_bonus=0.0):
    """Expected single-target damage of one trigger pull, using the game's shot code.

    spawn_projectiles runs twice: with an RNG that never crits and with one that always
    crits. The two totals are mixed by the crit chance the game would use.
    Returns (expected_volley, pellets, damage_per_pellet_without_crit, crit_chance).
    """
    plain = spawn_projectiles(
        _ORIGIN, _AIM, weapon, 0.0, int(player_damage),
        rng=_FixedRng(1.0), crit_chance_bonus=float(crit_bonus),
    )
    crit = spawn_projectiles(
        _ORIGIN, _AIM, weapon, 0.0, int(player_damage),
        rng=_FixedRng(0.0), crit_chance_bonus=float(crit_bonus),
    )
    crit_chance = min(CRIT_CAP, max(0.0, float(weapon.crit_chance) + float(crit_bonus)))
    plain_total = float(sum(p.damage for p in plain))
    crit_total = float(sum(p.damage for p in crit))
    expected = (1.0 - crit_chance) * plain_total + crit_chance * crit_total
    pellets = len(plain)
    return expected, pellets, plain_total / pellets, crit_chance


def shot_cooldown(weapon, player_fire_rate):
    """Seconds between trigger pulls, as the game computes them (cadence jitter has mean 1)."""
    return float(get_effective_fire_rate(weapon, float(player_fire_rate)))


def weapon_dps(weapon, player_damage, player_fire_rate, crit_bonus=0.0):
    expected, _, _, _ = volley_breakdown(weapon, player_damage, crit_bonus)
    return expected / shot_cooldown(weapon, player_fire_rate)


def weapon_table(player_damage, player_fire_rate):
    rows = []
    for key, weapon in WEAPONS.items():
        expected, pellets, per_pellet, crit = volley_breakdown(weapon, player_damage)
        cooldown = shot_cooldown(weapon, player_fire_rate)
        rows.append({
            "weapon": key,
            "name": weapon.name,
            "pellets": pellets,
            "per_pellet": per_pellet,
            "crit_chance": crit,
            "volley": expected,
            "cooldown": cooldown,
            "dps": expected / cooldown,
        })
    return rows


# ---------------------------------------------------------------------------
# Standard waves
# ---------------------------------------------------------------------------

def elite_hp_factor(wave):
    """Expected HP multiplier from the elite rolls in level.spawn_wave.

    An elite has ELITE_HP_MULT times the HP. One affix in three is "shielded", and its shield
    is 40 percent of the elite HP. Swift only changes speed and is ignored.
    """
    base_wave = int(getattr(config, "ELITE_SPAWN_BASE_WAVE", 3))
    if int(wave) < base_wave:
        return 1.0
    chance = min(0.35, float(getattr(config, "ELITE_SPAWN_CHANCE", 0.14)) + (int(wave) - base_wave) * 0.015)
    mult = float(getattr(config, "ELITE_HP_MULT", 2.2))
    return 1.0 + chance * ((mult - 1.0) + (1.0 / 3.0) * 0.40 * mult)


def standard_wave(wave, difficulty="normal"):
    """Expected composition and HP of one standard wave, from the game's spawn functions."""
    wave = int(wave)
    tuning = EnemyTuningLogic()
    spawner = EnemySpawnLogic(tuning)
    mods = tuning.difficulty_mods(difficulty)
    saved = random.getstate()
    try:
        if wave % 5 == 0:
            random.seed(wave)
            boss = tuning.get_boss_for_wave(wave)
            hp = float(tuning.enemy_stats(boss, wave, difficulty)[0])
            return {"wave": wave, "kind": "boss", "enemies": 1, "typical_hp": hp, "total_hp": hp, "boss": boss}

        cap = spawner.wave_cap(wave, int(mods["max_enemies"]))
        elite = elite_hp_factor(wave)
        totals = []
        count = 0
        for seed in range(SEEDS):
            random.seed(wave * 1000 + seed)
            plan = spawner.plan_wave(wave, difficulty, cap)
            count = int(plan.total_count)
            total = 0.0
            for behavior, n in plan.behavior_counts.items():
                total += int(n) * float(tuning.enemy_stats(behavior, wave, difficulty)[0])
            totals.append(total * elite)
    finally:
        random.setstate(saved)

    total_hp = sum(totals) / len(totals)
    return {
        "wave": wave,
        "kind": "standard",
        "enemies": count,
        "typical_hp": total_hp / max(1, count),
        "total_hp": total_hp,
        "boss": "",
    }


# ---------------------------------------------------------------------------
# Power-ups
# ---------------------------------------------------------------------------

def _measure_powerup(kind, damage, fire_rate, data=None):
    """Apply the real apply_powerup to a stub player (basic gun, 0 HP, 0 shield) and return what changed."""
    player = Player(
        pos=Vec2(0.0, 0.0),
        max_hp=int(config.PLAYER_HP),
        hp=0,
        shield=0,
        speed=float(config.PLAYER_SPEED),
        damage=int(damage),
        fire_rate=float(fire_rate),
        current_weapon=WEAPONS["basic"],
        boost_energy=0.0,
    )
    now = 0.0
    apply_powerup(player, PowerUp(Vec2(0.0, 0.0), kind, data=data), now)
    return {
        "hp": float(player.hp),
        "shield": float(player.shield),
        "damage": int(player.damage),
        "fire_rate": float(player.fire_rate),
        "speed": float(player.speed),
        "weapon": player.current_weapon,
        "ultra": int(player.ultra_charges),
        "laser_s": max(0.0, float(player.laser_until) - now),
        "vortex_s": max(0.0, float(player.vortex_until) - now),
        "vortex_dps": float(player.vortex_dps),
        "boost_energy": float(player.boost_energy),
        "boost_s": max(0.0, float(player.infinite_boost_until) - now),
    }


def powerup_values(ref_wave, difficulty, damage, fire_rate, vortex_coverage):
    """Value of one pickup per kind, in damage units, at the reference wave with the basic gun.

    Returns {kind: (value or None, unit, basis)} in config.POWERUP_COLORS order.
    """
    basic = WEAPONS["basic"]
    base_dps = weapon_dps(basic, damage, fire_rate)
    std = standard_wave(ref_wave, difficulty)
    t_std = std["total_hp"] / base_dps
    out = {}
    for kind in config.POWERUP_COLORS:
        if kind == "heal":
            m = _measure_powerup("heal", damage, fire_rate)
            out[kind] = (m["hp"], "HP", "HP restored from 0 (apply_powerup)")
        elif kind == "shield":
            m = _measure_powerup("shield", damage, fire_rate)
            out[kind] = (m["shield"], "HP", "shield gained from 0 (apply_powerup)")
        elif kind == "damage":
            m = _measure_powerup("damage", damage, fire_rate)
            gain = weapon_dps(basic, m["damage"], fire_rate) - base_dps
            out[kind] = (gain * t_std, "damage", "basic-gun DPS gain x standard wave clear time")
        elif kind == "firerate":
            m = _measure_powerup("firerate", damage, fire_rate)
            gain = weapon_dps(basic, damage, m["fire_rate"]) - base_dps
            out[kind] = (gain * t_std, "damage", "basic-gun DPS gain x standard wave clear time")
        elif kind == "laser":
            m = _measure_powerup("laser", damage, fire_rate)
            # Mirrors the laser branch in states.py (PlayingState): the beam replaces the basic shots.
            beam = int(damage * 0.9) + 14
            beam_dps = beam / shot_cooldown(basic, fire_rate)
            out[kind] = ((beam_dps - base_dps) * min(m["laser_s"], t_std), "damage",
                         "net of basic shots: (beam DPS - basic DPS) x min(duration, clear time)")
        elif kind == "vortex":
            m = _measure_powerup("vortex", damage, fire_rate)
            out[kind] = (m["vortex_dps"] * min(m["vortex_s"], t_std) * float(vortex_coverage), "damage",
                         "aura DPS x min(duration, clear time) x vortex coverage")
        elif kind == "weapon":
            pool = get_weapon_pool_for_wave(int(ref_wave))
            weights = _pool_weights_for_wave(int(ref_wave))
            total = 0.0
            for key, wt in zip(pool, weights):
                m = _measure_powerup("weapon", damage, fire_rate, data=key)
                if m["weapon"] is WEAPONS[key]:
                    val = (weapon_dps(WEAPONS[key], damage, fire_rate) - base_dps) * t_std
                else:
                    val = m["shield"]
                total += float(wt) * val
            wsum = sum(float(w) for w in weights)
            out[kind] = (total / wsum, "damage",
                         "pool-weighted: upgrade DPS gain x clear time (one wave only; upgrades persist), "
                         "shield top-up if no upgrade")
        elif kind == "ultra":
            m = _measure_powerup("ultra", damage, fire_rate)
            # Mirrors the ultra beam damage in game.py.
            per_charge = int(config.ULTRA_DAMAGE_BASE + damage * config.ULTRA_DAMAGE_MULT)
            out[kind] = (float(per_charge * m["ultra"]), "damage", "one ultra beam per charge")
        elif kind == "speed":
            out[kind] = (None, "", "n/a: movement speed has no damage model")
        elif kind == "boost":
            out[kind] = (None, "", "n/a: boost energy and infinite boost are movement time")
        else:
            out[kind] = (None, "", "n/a: no pricing rule in balance_sim.py")
    return out


def find_outliers(values, pct=OUTLIER_PCT):
    """Median of the priced values, and the kinds more than pct away from it.

    Returns (median, [(kind, value, relative_deviation), ...]); (None, []) when nothing is priced.
    """
    priced = {k: float(v) for k, v in values.items() if v is not None}
    if not priced:
        return None, []
    median = float(statistics.median(priced.values()))
    flagged = []
    for kind in sorted(priced):
        v = priced[kind]
        if median == 0.0:
            rel = 0.0 if v == 0.0 else math.inf
        else:
            rel = (v - median) / abs(median)
        if abs(rel) > pct:
            flagged.append((kind, v, rel))
    return median, flagged


def missing_wave1_powerups():
    return [k for k in WAVE1_POWERUP_KINDS if k not in config.POWERUP_COLORS]


# ---------------------------------------------------------------------------
# Mutators and skins (wave-1 modules, loaded only when present)
# ---------------------------------------------------------------------------

def config_snapshot():
    snap = {}
    for name in dir(config):
        if not name.isupper():
            continue
        value = getattr(config, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        snap[name] = value
    return snap


def _optional_module(name):
    try:
        return importlib.import_module(name), ""
    except ImportError as exc:
        return None, str(exc)


def _mutator_records(mod):
    """(id, mutator) pairs. mutators.MUTATORS is a tuple of records; a mapping of id to record also works."""
    table = mod.MUTATORS
    if isinstance(table, dict):
        return list(table.items())
    return [(m.id, m) for m in table]


def _rules_change(mod, mut):
    """Field-by-field difference from the stock RunRules, and the player damage multiplier.

    A wave-1 mutator maps a RunRules to a RunRules. Every rule it changes is listed, so the table shows
    the enemy, pickup and steering effects as well as the damage change.
    """
    stock = mod.RunRules()
    rules = mut.apply(stock)
    diffs = []
    for name in stock.__dataclass_fields__:
        before, after = getattr(stock, name), getattr(rules, name)
        if before != after:
            diffs.append(f"{name} {before} -> {after}")
    return diffs, float(rules.player_damage_mult), float(rules.player_max_hp_mult)


def mutator_rows(damage, fire_rate):
    """Score multiplier and implied difficulty change per mutator. Returns (rows, skip_note)."""
    mod, _ = _optional_module("mutators")
    if mod is None:
        return [], "[SKIP requires-wave1] mutators.py is not in this worktree"
    base = config_snapshot()
    base_dps = weapon_dps(WEAPONS["basic"], damage, fire_rate)
    rows = []
    for mid, mut in _mutator_records(mod):
        if hasattr(mod, "RunRules"):
            diffs, dmg_mult, _hp_mult = _rules_change(mod, mut)
            # The basic gun's DPS moves with the damage multiplier; fire rate is not changed by any mutator.
            new_dmg, new_rate = float(damage) * dmg_mult, float(fire_rate)
            moves_dps = dmg_mult != 1.0
        else:
            changed = mut.apply(dict(base))
            diffs = []
            for key in sorted(changed):
                if key in base and changed[key] != base[key]:
                    diffs.append(f"{key} {base[key]} -> {changed[key]}")
            moves_dps = "PLAYER_DAMAGE" in changed or "PLAYER_FIRE_RATE" in changed
            new_dmg = float(changed.get("PLAYER_DAMAGE", base["PLAYER_DAMAGE"]))
            new_rate = float(changed.get("PLAYER_FIRE_RATE", base["PLAYER_FIRE_RATE"]))
        if moves_dps:
            ratio = weapon_dps(WEAPONS["basic"], new_dmg, new_rate) / base_dps
            diffs.append(f"basic-gun DPS x{ratio:.2f}")
        rows.append({
            "id": mid,
            "name": getattr(mut, "name", mid),
            "score_mult": float(getattr(mut, "score_mult", 1.0)),
            "change": "; ".join(diffs) if diffs else "none",
        })
    return rows, ""


def skin_rows():
    """Skins are cosmetic in the contract, so the score multiplier is read when present and defaults to 1."""
    mod, _ = _optional_module("skins")
    if mod is None:
        return [], "[SKIP requires-wave1] skins.py is not in this worktree"
    rows = []
    for sid, skin in mod.SKINS.items():
        rows.append({
            "id": sid,
            "name": getattr(skin, "name", sid),
            "score_mult": float(getattr(skin, "score_mult", 1.0)),
            "change": "none (cosmetic)",
        })
    return rows, ""


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(difficulty, ref_wave, damage, fire_rate, vortex_coverage):
    weapons = weapon_table(damage, fire_rate)
    waves = [standard_wave(w, difficulty) for w in WAVES]
    dps = {row["weapon"]: row["dps"] for row in weapons}
    ttk = {}
    clear = {}
    for wv in waves:
        for key in WEAPONS:
            ttk[(wv["wave"], key)] = wv["typical_hp"] / dps[key]
            clear[(wv["wave"], key)] = wv["total_hp"] / dps[key]
    powerups = powerup_values(ref_wave, difficulty, damage, fire_rate, vortex_coverage)
    median, outliers = find_outliers({k: v for k, (v, _, _) in powerups.items()})
    mutators, mutator_skip = mutator_rows(damage, fire_rate)
    skins, skin_skip = skin_rows()
    return {
        "difficulty": difficulty,
        "ref_wave": int(ref_wave),
        "damage": int(damage),
        "fire_rate": float(fire_rate),
        "vortex_coverage": float(vortex_coverage),
        "weapons": weapons,
        "waves": waves,
        "ttk": ttk,
        "clear": clear,
        "powerups": powerups,
        "median": median,
        "outliers": outliers,
        "mutators": mutators,
        "mutator_skip": mutator_skip,
        "skins": skins,
        "skin_skip": skin_skip,
        "wave1_powerups_missing": missing_wave1_powerups(),
    }


def _f(x, nd=1):
    return f"{x:.{nd}f}"


def md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def render_markdown(rep):
    out = []
    out.append(
        f"# Balance simulator\n\nDifficulty {rep['difficulty']}, player damage {rep['damage']}, "
        f"fire rate {rep['fire_rate']:.3f}, power-up reference wave {rep['ref_wave']}, "
        f"vortex coverage {rep['vortex_coverage']:.2f}.\n"
    )

    out.append("## 1. Weapon DPS (single target, every pellet hits)\n")
    out.append(md_table(
        ["Weapon", "Pellets", "Damage per pellet", "Crit chance", "Cooldown (s)", "Expected DPS"],
        [(r["name"], r["pellets"], _f(r["per_pellet"], 2), _f(r["crit_chance"], 2), _f(r["cooldown"], 3), _f(r["dps"], 1))
         for r in rep["weapons"]],
    ))

    out.append("\n## 2. Standard wave, waves 1 to 30\n")
    out.append(md_table(
        ["Wave", "Kind", "Enemies", "Typical HP", "Wave HP"],
        [(w["wave"], w["kind"] if w["kind"] == "standard" else f"boss ({w['boss']})", w["enemies"],
          _f(w["typical_hp"], 1), _f(w["total_hp"], 1)) for w in rep["waves"]],
    ))

    keys = list(WEAPONS.keys())
    out.append("\n## 3. Time to kill a typical enemy (s)\n")
    out.append(md_table(
        ["Wave"] + keys,
        [[w["wave"]] + [_f(rep["ttk"][(w["wave"], k)], 2) for k in keys] for w in rep["waves"]],
    ))

    out.append("\n## 4. Time to clear a standard wave (s)\n")
    out.append(md_table(
        ["Wave"] + keys,
        [[w["wave"]] + [_f(rep["clear"][(w["wave"], k)], 1) for k in keys] for w in rep["waves"]],
    ))

    out.append("\n## 5. Power-up value per pickup (damage units, reference wave "
               f"{rep['ref_wave']}, basic gun)\n")
    med = rep["median"]
    rows = []
    for kind, (val, unit, basis) in rep["powerups"].items():
        if val is None:
            rows.append((kind, "n/a", "", "", basis))
            continue
        rel = "" if not med else f"{(val - med) / abs(med) * 100:+.0f}%"
        flag = "OUTLIER" if any(o[0] == kind for o in rep["outliers"]) else ""
        rows.append((kind, _f(val, 1), unit, f"{rel} {flag}".strip(), basis))
    out.append(md_table(["Kind", "Value", "Unit", "vs median", "Basis"], rows))
    if med is None:
        out.append("\nNo power-up is priced, so there is no median.")
    else:
        out.append(f"\nMedian of priced kinds: {_f(med, 1)}. Outliers more than {int(OUTLIER_PCT * 100)} percent away:")
        if rep["outliers"]:
            for kind, val, rel in rep["outliers"]:
                out.append(f"- {kind}: {_f(val, 1)} ({rel * 100:+.0f}%)")
        else:
            out.append("- none")
    for kind in rep["wave1_powerups_missing"]:
        out.append(f"[SKIP requires-wave1] power-up '{kind}' is not in config.POWERUP_COLORS")

    out.append("\n## 6. Mutators and skins\n")
    if rep["mutator_skip"]:
        out.append(rep["mutator_skip"])
    else:
        out.append(md_table(
            ["Id", "Name", "Score multiplier", "Implied difficulty change"],
            [(r["id"], r["name"], _f(r["score_mult"], 2), r["change"]) for r in rep["mutators"]],
        ))
    out.append("")
    if rep["skin_skip"]:
        out.append(rep["skin_skip"])
    else:
        out.append(md_table(
            ["Id", "Name", "Score multiplier", "Implied difficulty change"],
            [(r["id"], r["name"], _f(r["score_mult"], 2), r["change"]) for r in rep["skins"]],
        ))
    return "\n".join(out) + "\n"


def csv_rows(rep):
    rows = []

    def add(section, id_, wave, weapon, metric, value, unit, note=""):
        rows.append({"section": section, "id": id_, "wave": wave, "weapon": weapon, "metric": metric,
                     "value": value, "unit": unit, "note": note})

    for r in rep["weapons"]:
        add("weapon", r["weapon"], "", r["weapon"], "dps", round(r["dps"], 6), "damage/s")
        add("weapon", r["weapon"], "", r["weapon"], "cooldown", round(r["cooldown"], 6), "s")
        add("weapon", r["weapon"], "", r["weapon"], "volley", round(r["volley"], 6), "damage")
    for w in rep["waves"]:
        note = w["boss"] if w["kind"] == "boss" else ""
        add("wave", w["wave"], w["wave"], "", "enemies", w["enemies"], "count", note)
        add("wave", w["wave"], w["wave"], "", "typical_hp", round(w["typical_hp"], 6), "HP", note)
        add("wave", w["wave"], w["wave"], "", "total_hp", round(w["total_hp"], 6), "HP", note)
        for key in WEAPONS:
            add("ttk", "", w["wave"], key, "time_to_kill_typical", round(rep["ttk"][(w["wave"], key)], 6), "s")
            add("clear", "", w["wave"], key, "time_to_clear_wave", round(rep["clear"][(w["wave"], key)], 6), "s")
    for kind, (val, unit, basis) in rep["powerups"].items():
        add("powerup", kind, rep["ref_wave"], "basic", "value_per_pickup",
            "" if val is None else round(val, 6), unit, basis)
    for r in rep["mutators"]:
        add("mutator", r["id"], "", "", "score_multiplier", r["score_mult"], "x", r["change"])
    for r in rep["skins"]:
        add("skin", r["id"], "", "", "score_multiplier", r["score_mult"], "x", r["change"])
    return rows


def write_csv(path, rep):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=POWERUP_CSV_COLUMNS)
        writer.writeheader()
        for row in csv_rows(rep):
            writer.writerow(row)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline PLOUTO balance simulator (markdown to stdout).")
    parser.add_argument("--csv", metavar="PATH", help="also write the tidy CSV to PATH")
    parser.add_argument("--difficulty", default="normal", choices=DIFFICULTIES)
    parser.add_argument("--ref-wave", type=int, default=REF_WAVE_DEFAULT,
                        help=f"wave used for power-up values (default {REF_WAVE_DEFAULT}, a regular wave)")
    parser.add_argument("--damage", type=int, default=int(config.PLAYER_DAMAGE))
    parser.add_argument("--fire-rate", type=float, default=float(config.PLAYER_FIRE_RATE))
    parser.add_argument("--vortex-coverage", type=float, default=VORTEX_DEFAULT_COVERAGE)
    args = parser.parse_args(argv)

    rep = build_report(args.difficulty, args.ref_wave, args.damage, args.fire_rate, args.vortex_coverage)
    sys.stdout.write(render_markdown(rep))
    if args.csv:
        write_csv(args.csv, rep)
        sys.stdout.write(f"\nCSV written to {os.path.abspath(args.csv)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
