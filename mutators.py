"""Opt-in run mutators: challenge modifiers that change the rules of one run, with a score bonus for risk.

Each mutator is a small record: a name, a one-line description, a score multiplier and one ``apply``
function. ``apply`` takes the run configuration (a RunRules) and returns a modified copy. Gameplay code
never checks mutator names; it only reads the RunRules values that _init_game built for the run, and the
few per-frame helpers below (steering, shield recharge, enemy volleys) are pure functions of those values.

The chosen mutator ids persist under the "mutators" key of user_settings.json, next to the volume and
shake keys. Every read and write is guarded, and writes keep the other keys.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, replace
from typing import Callable, Iterable, Sequence

from projectile import Projectile
from utils import Vec2

MUTATORS_KEY = "mutators"

# Tuning, one place per value.
GLASS_CANNON_DAMAGE_MULT = 1.5      # outgoing player damage
GLASS_CANNON_MAX_HP_MULT = 0.6      # max HP falls to 60 percent of PLAYER_HP
BULLET_HELL_PROJECTILE_MULT = 1.25  # enemy shot speed
BULLET_HELL_EXTRA_PER_VOLLEY = 1    # extra enemy shots added to every volley
BULLET_HELL_LONE_SHOT_SPREAD_DEG = 12.0  # a volley of one gets its extra shot this far to the side
DRIFT_ACCEL = 5.0                   # 1/s: how quickly steering eases toward the input (stock is instant)
DRIFT_DECEL = 2.4                   # 1/s: how slowly the ship slides to a halt after input is released
FRENZY_ENEMY_SPEED_MULT = 1.2
# Still bounded by the wave cap. On normal difficulty the cap binds from wave 6, so this only adds bodies
# in waves 1 to 5 (measured in the wave1 report); scale the cap as well to make it show in every wave.
FRENZY_SPAWN_SIZE_MULT = 1.25
IRON_MAN_SHIELD_REGEN = 2.0         # shield points per second


@dataclass(frozen=True)
class RunRules:
    """The rule values one run plays with. The defaults are the stock game."""

    player_damage_mult: float = 1.0      # multiplies outgoing player damage
    player_max_hp_mult: float = 1.0      # multiplies PLAYER_HP for the run's max HP
    player_accel: float = 0.0            # steering ease rate in 1/s; 0 keeps the stock instant steering
    player_decel: float = 0.0            # slide rate in 1/s when there is no input (used when player_accel is set)
    enemy_projectile_speed_mult: float = 1.0
    enemy_volley_extra: int = 0          # extra enemy shots per volley
    enemy_speed_mult: float = 1.0        # applied to enemies as they spawn
    spawn_size_mult: float = 1.0         # applied to the regular wave head count, before the wave cap
    pickups_enabled: bool = True
    shield_regen_per_s: float = 0.0      # passive shield recharge, points per second


def _glass_cannon(r: RunRules) -> RunRules:
    return replace(
        r,
        player_damage_mult=r.player_damage_mult * GLASS_CANNON_DAMAGE_MULT,
        player_max_hp_mult=r.player_max_hp_mult * GLASS_CANNON_MAX_HP_MULT,
    )


def _bullet_hell(r: RunRules) -> RunRules:
    return replace(
        r,
        enemy_projectile_speed_mult=r.enemy_projectile_speed_mult * BULLET_HELL_PROJECTILE_MULT,
        enemy_volley_extra=r.enemy_volley_extra + BULLET_HELL_EXTRA_PER_VOLLEY,
    )


def _drift(r: RunRules) -> RunRules:
    return replace(r, player_accel=DRIFT_ACCEL, player_decel=DRIFT_DECEL)


def _frenzy(r: RunRules) -> RunRules:
    return replace(
        r,
        enemy_speed_mult=r.enemy_speed_mult * FRENZY_ENEMY_SPEED_MULT,
        spawn_size_mult=r.spawn_size_mult * FRENZY_SPAWN_SIZE_MULT,
    )


def _iron_man(r: RunRules) -> RunRules:
    return replace(
        r,
        pickups_enabled=False,
        shield_regen_per_s=r.shield_regen_per_s + IRON_MAN_SHIELD_REGEN,
    )


@dataclass(frozen=True)
class Mutator:
    """One opt-in run modifier."""

    id: str
    name: str
    description: str
    score_mult: float
    apply: Callable[[RunRules], RunRules]


# Canonical order: the title chips, the saved list and the Game Over line all use it.
MUTATORS: tuple[Mutator, ...] = (
    Mutator(
        "glass_cannon", "Glass Cannon",
        "Deal 1.5x damage, but your max HP drops to 60 percent.",
        1.25, _glass_cannon,
    ),
    Mutator(
        "bullet_hell", "Bullet Hell",
        "Enemy shots fly 25 percent faster and every volley gains one extra shot.",
        1.20, _bullet_hell,
    ),
    Mutator(
        "drift", "Drift",
        "Steering is sluggish and the ship slides for a while after you let go.",
        1.10, _drift,
    ),
    Mutator(
        "frenzy", "Frenzy",
        "Enemies move 20 percent faster and early waves field more bodies, still within the wave cap.",
        1.30, _frenzy,
    ),
    Mutator(
        "iron_man", "Iron Man",
        "No pickups spawn, but your shields slowly recharge over time.",
        1.15, _iron_man,
    ),
)

_BY_ID: dict[str, Mutator] = {m.id: m for m in MUTATORS}


def mutator_by_id(mutator_id: str) -> Mutator | None:
    """The mutator with this id, or None for an unknown id."""
    return _BY_ID.get(str(mutator_id or ""))


def normalize_selection(ids: Iterable[str] | None) -> tuple[str, ...]:
    """Known ids only, unique, in canonical order. Unknown or non-string entries are dropped."""
    if not ids or isinstance(ids, (str, bytes)):
        return ()
    wanted = {str(i) for i in ids if isinstance(i, str)}
    return tuple(m.id for m in MUTATORS if m.id in wanted)


def toggle_selection(ids: Iterable[str] | None, mutator_id: str) -> tuple[str, ...]:
    """Return the selection with ``mutator_id`` switched on or off. Unknown ids leave it unchanged."""
    current = normalize_selection(ids)
    if mutator_by_id(mutator_id) is None:
        return current
    if mutator_id in current:
        return tuple(i for i in current if i != mutator_id)
    return normalize_selection((*current, mutator_id))


def mutator_names(ids: Iterable[str] | None) -> list[str]:
    """Display names of the selected mutators, in canonical order."""
    return [mutator_by_id(mid).name for mid in normalize_selection(ids)]


def apply_mutators(ids: Iterable[str] | None, base: RunRules | None = None) -> RunRules:
    """Fold the selected mutators' apply functions over ``base`` (stock rules by default)."""
    rules = base if base is not None else RunRules()
    selected = set(normalize_selection(ids))
    for m in MUTATORS:
        if m.id in selected:
            rules = m.apply(rules)
    return rules


def combined_score_multiplier(ids: Iterable[str] | None) -> float:
    """Product of the selected mutators' score multipliers. An empty selection gives 1.0."""
    mult = 1.0
    for mid in normalize_selection(ids):
        mult *= float(mutator_by_id(mid).score_mult)
    return mult


def format_score_mult(mult: float) -> str:
    """Score multiplier as shown to the player, e.g. 'x1.63'. Rounds half up, so 1.625 reads 1.63 (format() gives 1.62)."""
    cents = math.floor(float(mult) * 100.0 + 0.5 + 1e-9)
    return f"x{cents / 100.0:.2f}"


def scaled_max_hp(base_hp: int, rules: RunRules) -> int:
    """Max HP for a run: the base scaled by the run's max HP multiplier, never below 1."""
    return max(1, int(round(float(base_hp) * float(rules.player_max_hp_mult))))


def steer_velocity(vel: Vec2, desired: Vec2, dt: float, rules: RunRules) -> Vec2:
    """Next player velocity. Stock steering (player_accel 0) snaps to the desired velocity.

    With steering eased (Drift), the velocity moves toward the desired velocity at player_accel while
    there is input and at player_decel while there is none, so the ship slides after input stops.
    """
    if float(rules.player_accel) <= 0.0:
        return desired
    rate = float(rules.player_accel) if desired.length() > 0.0 else float(rules.player_decel)
    k = 1.0 - math.exp(-max(0.0, rate) * max(0.0, float(dt)))
    return vel + (desired - vel) * k


def tick_shield_regen(player, carry: float, dt: float, rules: RunRules, cap: float) -> float:
    """Advance passive shield recharge by one frame. Returns the fractional carry for the next frame.

    The shield is an int, so the fraction is kept in ``carry``. Runs without a recharge rule return 0.
    """
    rate = float(rules.shield_regen_per_s)
    cap_i = int(cap)
    if rate <= 0.0 or int(player.shield) >= cap_i:
        return 0.0
    carry += rate * max(0.0, float(dt))
    whole = int(carry)
    if whole > 0:
        player.shield = min(cap_i, int(player.shield) + whole)
        carry -= whole
    return carry if int(player.shield) < cap_i else 0.0


def _wrap_angle(a: float) -> float:
    return (a + math.pi) % math.tau - math.pi


def shape_enemy_volley(projectiles: list, start: int, rules: RunRules | None) -> int:
    """Apply Bullet Hell to the enemy shots added to ``projectiles`` since index ``start``.

    Call it once after an enemy update that fired. Shots are scaled by enemy_projectile_speed_mult, and
    enemy_volley_extra extra shots go into the widest gap of the volley (or to either side of a lone shot).
    Bombs are left alone because they are slow, one-off explosives rather than shots.
    Returns the number of extra shots added. Stock rules change nothing and return 0.
    """
    if rules is None:
        return 0
    speed_mult = float(rules.enemy_projectile_speed_mult)
    extra = int(rules.enemy_volley_extra)
    if speed_mult == 1.0 and extra <= 0:
        return 0
    volley = [p for p in projectiles[start:] if p.owner == "enemy" and str(p.projectile_type) != "bomb"]
    if not volley:
        return 0
    if speed_mult != 1.0:
        for p in volley:
            p.vel = p.vel * speed_mult
    if extra <= 0:
        return 0

    template = volley[0]
    speed = template.vel.length()
    if speed <= 1e-9:
        return 0
    angles = [math.atan2(p.vel.y, p.vel.x) for p in volley]
    sum_x = sum(math.cos(a) for a in angles)
    sum_y = sum(math.sin(a) for a in angles)
    ref = math.atan2(sum_y, sum_x) if math.hypot(sum_x, sum_y) > 1e-9 else angles[0]

    new_angles: list[float] = []
    if len(volley) == 1:
        spread = math.radians(BULLET_HELL_LONE_SHOT_SPREAD_DEG)
        for k in range(extra):
            side = 1.0 if k % 2 == 0 else -1.0
            new_angles.append(ref + side * spread * (k // 2 + 1))
    else:
        rel = sorted(_wrap_angle(a - ref) for a in angles)
        for _ in range(extra):
            # Widest gap between neighbours, never the wrap-around gap, so a 2-shot fan stays a fan.
            gaps = [(rel[j + 1] - rel[j], j) for j in range(len(rel) - 1)]
            width, j = max(gaps)
            mid = rel[j] + width * 0.5
            rel.insert(j + 1, mid)
            new_angles.append(ref + mid)

    for a in new_angles:
        d = Vec2(math.cos(a), math.sin(a))
        projectiles.append(Projectile(
            pos=Vec2(template.pos.x, template.pos.y),
            vel=d * speed,
            damage=template.damage,
            ttl=template.ttl,
            owner=template.owner,
            projectile_type=template.projectile_type,
            is_crit=template.is_crit,
        ))
    return len(new_angles)


# ---------------------------------------------------------------------------
# Persistence (user_settings.json)
# ---------------------------------------------------------------------------

def _settings_path() -> str:
    # Looked up at call time so tests can point audio._SETTINGS_PATH at a temp file.
    import audio
    return audio._SETTINGS_PATH


def load_selection(path: str | None = None) -> tuple[str, ...]:
    """Saved mutator ids in canonical order. A missing, unreadable or mistyped file gives no mutators."""
    target = path or _settings_path()
    try:
        with open(target, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return normalize_selection(data.get(MUTATORS_KEY))
    except Exception:
        pass
    return ()


def save_selection(ids: Sequence[str] | None, path: str | None = None) -> None:
    """Write the selection to user_settings.json, keeping every other key. Never raises."""
    target = path or _settings_path()
    tmp = target + ".tmp"
    try:
        data = {}
        try:
            with open(target, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
            if isinstance(existing, dict):
                data = existing
        except Exception:
            data = {}
        data[MUTATORS_KEY] = list(normalize_selection(ids))
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, target)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
