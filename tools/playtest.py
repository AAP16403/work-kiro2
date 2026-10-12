"""Headless bot playtest: seeded full runs that look for crashes, invariant breaks and softlocks.

Usage, from the project root:

    python tools/playtest.py --runs 3 --out playtest_report.json
    python tools/playtest.py --runs 2 --difficulties easy,hard --wave-limit 8 --time-limit 240 --out report.json

--runs N is the number of seeded runs per difficulty (default 3), so the default sweep is
3 runs at easy, 3 at normal and 3 at hard. Run k of every difficulty uses seed seed-base + k
(default seed-base 1000). Each run ends at game over, at the wave limit (--wave-limit, default 6)
or at the game-time limit (--time-limit seconds, default 180), whichever comes first.

Exit status: 0 when no run raised, broke an invariant or softlocked; 1 otherwise; 2 for bad arguments.
The report is written even when a run fails.

The bot plays the real game. It sends the same events a player would: WASD movement, mouse aim,
Q for Ultra, SPACE for dash and the number and ENTER keys of the boss reward menu. It steps the real
fixed-step update loop. Its choices depend only on the game state and its seed.

Headless: the window stays hidden. The audio is a silent stand-in. The damage popups and the wave
banners are switched off because they are visual only. The high score file is redirected to a temp
directory. Nothing in the project root is written except --out.

Determinism: the enemy AI, the boss patterns and the spawn planner draw from the global random module.
Each run reseeds it with the run seed and restores the previous state afterwards, so the same seed
gives the same run and the same report bytes.

Invariants checked after every fixed step:
    - every position, velocity and timer is finite (no NaN or infinity);
    - player HP is at most max_hp, and not below zero unless the run has ended (GAME_OVER);
    - the enemy count is at most the wave cap plus ADD_ALLOWANCE (adds spawned by bosses and egg sacs);
    - the projectile count is at most PROJECTILE_LIMIT;
    - every state transition is a legal FSM edge (ALLOWED_TRANSITIONS) to a registered state.

Softlock: while a wave is active and enemies are alive, a run softlocks when no enemy has lost HP or
shield, and none has been killed or has left, for SOFTLOCK_SECONDS of game time. A new wave starts
the clock. The run stops and records the seed.

Report (JSON, written to --out; keys are written sorted):
    format           "plouto-playtest"
    format_version   1
    options          the sweep arguments: runs (per difficulty), difficulties, seed_base, wave_limit, time_limit
    runs             one record per run, in order: difficulty by difficulty, then seed by seed
    summary          runs, outcomes (count of runs per outcome), failed_runs, softlock_seeds,
                     max_wave_reached, total_kills, total_steps, violation_count, powerups_used (totals),
                     ultra_used, dashes, mutators_module (true when mutators.py is importable), mutators_used
    ok               true when failed_runs is empty

Run record:
    seed             the run seed
    difficulty       "easy", "normal" or "hard"
    outcome          how the run ended: "game_over", "wave_limit", "time_limit", "softlock", "invariant" or "error"
    wave_reached     the wave number when the run ended
    kills            enemies killed in the run (score tracker count)
    game_time        game seconds simulated, rounded to milliseconds
    steps            fixed simulation steps taken
    powerups_used    power-up kind -> pickups in the run (every kind picked up)
    ultra_used       Ultra activations
    dashes           dash activations
    mutators         mutator ids chosen for the run ([] when mutators.py is not present)
    rewards          boss reward picks, in order: {"temp": key, "perm": key}
    violations       the first 10 invariant or transition violations, as text
    violation_count  total violations seen in the run
    softlock         null, or {"wave", "game_time", "enemies", "last_progress_time", "behaviors"}
    error            null, or {"type", "message", "where"} for a run that raised
    final_state      name of the FSM state when the run ended
"""

import argparse
import json
import math
import os
import random
import shutil
import sys
import tempfile
import traceback
from dataclasses import dataclass
from enum import Enum

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pyglet

import config
import score as score_module
from config import FPS
from fsm import State
from game import Game as _Game
from level import _SPAWN_LOGIC
from logic import BalanceLogic
from states import GameStateName
from utils import Vec2, enemy_behavior_name, to_iso

FORMAT_NAME = "plouto-playtest"
FORMAT_VERSION = 1
DIFFICULTIES = ("easy", "normal", "hard")
DEFAULT_RUNS = 3
DEFAULT_SEED_BASE = 1000
DEFAULT_WAVE_LIMIT = 6
DEFAULT_TIME_LIMIT = 180.0
DEFAULT_OUT = "playtest_report.json"
FAILURE_OUTCOMES = ("softlock", "invariant", "error")
MAX_REPORTED_VIOLATIONS = 10

# Invariant bounds.
SOFTLOCK_SECONDS = 60.0
ADD_ALLOWANCE = 16  # boss adds: swarm queen cap (+4), egg-sac hatch (3 sacs x 3 swarm), one spawn tick (+2), the boss (+1)
PROJECTILE_LIMIT = 500

# Transitions the game makes, read from states.py. A transition not listed here is a violation.
ALLOWED_TRANSITIONS = {
    "MenuState": ("PlayingState", "GuideState", "SettingsState", "HangarState"),
    "SettingsState": ("MenuState",),
    "GuideState": ("MenuState",),
    "HangarState": ("MenuState",),
    "PlayingState": ("PausedState", "BossRewardState", "GameOverState"),
    "PausedState": ("PlayingState", "MenuState"),
    "BossRewardState": ("PlayingState",),
    "GameOverState": ("PlayingState", "MenuState"),
}

# Bot tuning. Every value is a constant or a draw from the bot's seeded RNG.
STANDOFF_MIN = 110.0  # inside a kiter's 130-unit retreat line, so the bot closes on ranged enemies
STANDOFF_MAX = 160.0
ENGAGE_BAND = 20.0
DEFAULT_SHOT_SPEED = 320.0
FLIP_MIN = 120
FLIP_MAX = 240
ENEMY_AVOID_PAD = 90.0
ENEMY_PUSH = 1.5
CONTACT_DASH_PAD = 45.0
PROJECTILE_LOOKAHEAD = 0.6
PROJECTILE_DODGE_RADIUS = 30.0
PROJECTILE_PUSH = 2.0
PROJECTILE_DASH_TIME = 0.25
PROJECTILE_DASH_MISS = 20.0
HAZARD_PAD = 40.0
HAZARD_PUSH = 2.0
HAZARD_DASH_TIME = 0.2
TRAP_PAD = 30.0
TRAP_PUSH = 1.5
EDGE_START = 0.8
EDGE_PULL = 2.5
FLEE_THRESHOLD = 0.15
PICKUP_RANGE = 260.0
ULTRA_RANGE = 420.0
REWARD_ATTEMPTS = 40

_BALANCE = BalanceLogic(fps=float(FPS))
_MOVE_COMBOS = (
    (True, False, False, False),  # W: world (+1, +1)
    (False, True, False, False),  # S: world (-1, -1)
    (False, False, True, False),  # A: world (-1, +1)
    (False, False, False, True),  # D: world (+1, -1)
    (True, False, False, True),   # W+D: world (+2, 0)
    (True, False, True, False),   # W+A: world (0, +2)
    (False, True, False, True),   # S+D: world (0, -2)
    (False, True, True, False),   # S+A: world (-2, 0)
)
_NO_KEYS = (False, False, False, False)


@dataclass(frozen=True)
class Plan:
    """The inputs the bot sends for one fixed step."""

    keys: tuple  # (W, S, A, D) pressed
    aim: Vec2  # world point the mouse is put on
    dash: bool
    ultra: bool
    mode: str  # flee, pickup, engage, back, strafe, center, hold


def _perp(v: Vec2) -> Vec2:
    return Vec2(-v.y, v.x)


def _away(p: Vec2, q: Vec2) -> Vec2:
    return (p - q).normalized()


def _finite_point(v) -> bool:
    return math.isfinite(float(v.x)) and math.isfinite(float(v.y))


def _closest_on_segment(p: Vec2, a: Vec2, b: Vec2) -> Vec2:
    ab = b - a
    length_sq = ab.length_squared()
    if length_sq <= 1e-12:
        return a
    t = max(0.0, min(1.0, (p - a).dot(ab) / length_sq))
    return a + ab * t


def _combo_vector(combo) -> Vec2:
    w, s, a, d = (1.0 if pressed else 0.0 for pressed in combo)
    return Vec2(w - s - a + d, w - s + a - d)


def _best_keys(desire: Vec2) -> tuple:
    """The movement key combination whose world direction is closest to ``desire``."""
    if desire.length() <= 1e-9:
        return _NO_KEYS
    best = _NO_KEYS
    best_dot = -2.0
    for combo in _MOVE_COMBOS:
        dot = _combo_vector(combo).normalized().dot(desire)
        if dot > best_dot:
            best, best_dot = combo, dot
    return best


def _nearest_powerup(state, p: Vec2):
    best = None
    best_d = PICKUP_RANGE
    for pu in getattr(state, "powerups", []):
        d = (pu.pos - p).length()
        if d < best_d:
            best, best_d = pu, d
    return best


class Bot:
    """Seeded player. ``plan`` reads a game state and returns the inputs for one step."""

    def __init__(self, seed: int) -> None:
        rng = random.Random(f"playtest-bot:{seed}")
        self.standoff = rng.uniform(STANDOFF_MIN, STANDOFF_MAX)
        self.strafe_sign = rng.choice((-1.0, 1.0))
        self._flip_every = rng.randint(FLIP_MIN, FLIP_MAX)
        self._ticks = 0
        self._reward_rng = rng

    def pick_reward_index(self) -> int:
        return self._reward_rng.randrange(3)

    def plan(self, player, state, room_radius: float) -> Plan:
        self._ticks += 1
        if self._ticks % self._flip_every == 0:
            self.strafe_sign = -self.strafe_sign
        p = player.pos
        push = Vec2(0.0, 0.0)
        dash = False
        player_radius = float(_BALANCE.player_radius)

        enemies = [e for e in state.enemies if e.hp > 0 and not getattr(e, "_is_dead", False)]
        nearest = None
        nearest_d = 0.0
        for e in enemies:
            dist = (e.pos - p).length()
            if nearest is None or dist < nearest_d:
                nearest, nearest_d = e, dist
            radius = float(_BALANCE.enemy_radius(enemy_behavior_name(e)))
            avoid = radius + ENEMY_AVOID_PAD
            if dist < avoid:
                push = push + _away(p, e.pos) * (ENEMY_PUSH * (avoid - dist) / avoid)
            if dist < radius + player_radius + CONTACT_DASH_PAD:
                dash = True

        for pr in state.projectiles:
            if pr.owner != "enemy":
                continue
            v = pr.vel
            vv = v.length_squared()
            if vv <= 1e-9:
                continue
            t = (p - pr.pos).dot(v) / vv  # seconds until the projectile is closest to the player
            if t <= 0.0 or t > PROJECTILE_LOOKAHEAD:
                continue
            miss_vec = p - (pr.pos + v * t)
            if miss_vec.length() >= PROJECTILE_DODGE_RADIUS:
                continue
            side = _perp(v.normalized())
            push = push + side * (PROJECTILE_PUSH if side.dot(miss_vec) >= 0.0 else -PROJECTILE_PUSH)
            if t <= PROJECTILE_DASH_TIME and miss_vec.length() <= PROJECTILE_DASH_MISS:
                dash = True

        for h in list(getattr(state, "lasers", [])) + list(getattr(state, "thunders", [])):
            if getattr(h, "owner", "enemy") != "enemy" or h.hit_done or h.t >= h.warn:
                continue
            offset = p - _closest_on_segment(p, h.start, h.end)
            gap = offset.length()
            reach = float(h.thickness) * 0.55 + player_radius
            if gap < reach + HAZARD_PAD:
                away = offset.normalized() if gap > 1e-6 else _perp((h.end - h.start).normalized())
                push = push + away * HAZARD_PUSH
            if float(h.warn) - float(h.t) <= HAZARD_DASH_TIME and gap <= reach:
                dash = True

        for tr in getattr(state, "traps", []):
            if tr.damage <= 0 or tr.t < tr.armed_delay:
                continue
            gap = (p - tr.pos).length()
            reach = float(tr.radius) + player_radius
            if gap < reach + TRAP_PAD:
                push = push + _away(p, tr.pos) * TRAP_PUSH
            if gap < reach + 6.0:
                dash = True

        r = p.length()
        edge = float(room_radius) * EDGE_START
        if r > edge:
            span = max(1.0, float(room_radius) - edge)
            push = push + (-p.normalized()) * (EDGE_PULL * min(1.0, (r - edge) / span))

        pickup = _nearest_powerup(state, p)
        if push.length() > FLEE_THRESHOLD:
            desire, mode = push.normalized(), "flee"
        elif pickup is not None:
            desire, mode = (pickup.pos - p).normalized(), "pickup"
        elif nearest is not None:
            desire, mode = self._engage(p, nearest)
        elif r > 60.0:
            desire, mode = (-p).normalized(), "center"
        else:
            desire, mode = Vec2(0.0, 0.0), "hold"

        keys = _best_keys(desire)
        dash_now = bool(dash and int(player.dash_charges) > 0 and not player.is_dashing)
        if dash_now:
            if push.length() > 1e-9:
                escape = push
            elif nearest is not None:
                escape = _away(p, nearest.pos)
            else:
                escape = desire
            keys = _best_keys(escape)
            mode = "dash"

        if nearest is not None:
            # Lead the target: shots travel at the weapon's speed, so aim where the enemy will be when they arrive.
            shot_speed = float(getattr(getattr(player, "current_weapon", None), "projectile_speed", 0.0) or DEFAULT_SHOT_SPEED)
            lead_t = nearest_d / max(1.0, shot_speed)
            aim = nearest.pos + getattr(nearest, "vel", Vec2(0.0, 0.0)) * lead_t
        elif desire.length() > 1e-9:
            aim = p + desire * 100.0
        else:
            aim = p + Vec2(100.0, 0.0)

        ultra = bool(
            int(player.ultra_charges) > 0
            and float(state.time) >= float(player.ultra_cd_until)
            and nearest is not None
            and nearest_d <= ULTRA_RANGE
        )
        return Plan(keys=keys, aim=aim, dash=dash_now, ultra=ultra, mode=mode)

    def _engage(self, p: Vec2, target) -> tuple:
        d = target.pos - p
        dist = d.length()
        u = d.normalized()
        if dist > self.standoff + ENGAGE_BAND:
            return u, "engage"
        if dist < self.standoff - ENGAGE_BAND:
            return (-u) * 0.5 + _perp(u) * (0.5 * self.strafe_sign), "back"
        return _perp(u) * self.strafe_sign, "strafe"

    def act(self, game) -> Plan:
        """Send one step of input to the live game, through the same paths the keyboard and mouse use."""
        k = pyglet.window.key
        plan = self.plan(game.player, game.state, float(config.ROOM_RADIUS))
        held = game.keys  # pyglet KeyStateHandler: state changes go through its key events
        w, s_key, a, d = plan.keys
        for symbol, down in ((k.W, w), (k.S, s_key), (k.A, a), (k.D, d),
                             (k.UP, False), (k.DOWN, False), (k.LEFT, False), (k.RIGHT, False),
                             (k.LSHIFT, False), (k.RSHIFT, False)):
            if down:
                held.on_key_press(symbol, 0)
            else:
                held.on_key_release(symbol, 0)
        game.auto_shoot = True
        sx, sy = to_iso(plan.aim, Vec2(0.0, 0.0))
        game.on_mouse_motion(sx, sy, 0.0, 0.0)
        if plan.ultra:
            game.fsm.on_key_press(k.Q, 0)
        if plan.dash:
            game.fsm.on_key_press(k.SPACE, 0)
        return plan


def _state_key(state) -> str:
    """The FSM name of a state: the class name for a State, the value for a GameStateName."""
    if state is None:
        return ""
    if isinstance(state, Enum):
        return str(state.value)
    if isinstance(state, type):
        return state.__name__
    if isinstance(state, State):
        return type(state).__name__
    return str(state)


def check_frame(state, player, fsm_state: str, wave_cap: int,
                projectile_limit: int = PROJECTILE_LIMIT, add_allowance: int = ADD_ALLOWANCE) -> list:
    """Return the invariant violations of one frame as text. An empty list means the frame is clean."""
    problems = []
    if not math.isfinite(float(state.time)):
        problems.append(f"game time is not finite ({state.time})")
    if not _finite_point(player.pos):
        problems.append(f"player position is not finite ({player.pos.x}, {player.pos.y})")
    if not math.isfinite(float(player.hp)):
        problems.append(f"player hp is not finite ({player.hp})")
    else:
        max_hp = float(player.max_hp)
        if float(player.hp) > max_hp:
            problems.append(f"player hp {player.hp} is above max_hp {player.max_hp}")
        if float(player.hp) < 0.0 and fsm_state != "GameOverState":
            problems.append(f"player hp {player.hp} is below zero outside game over")
    for e in state.enemies:
        if not _finite_point(e.pos):
            problems.append(f"enemy {enemy_behavior_name(e)} position is not finite")
            break
    for p in state.projectiles:
        if not (_finite_point(p.pos) and _finite_point(p.vel)):
            problems.append("projectile position or velocity is not finite")
            break
    for pu in state.powerups:
        if not _finite_point(pu.pos):
            problems.append(f"power-up {pu.kind} position is not finite")
            break
    for beam in list(getattr(state, "lasers", [])) + list(getattr(state, "thunders", [])):
        if not (_finite_point(beam.start) and _finite_point(beam.end)):
            problems.append("beam endpoint is not finite")
            break
    enemy_limit = int(wave_cap) + int(add_allowance)
    if len(state.enemies) > enemy_limit:
        problems.append(
            f"{len(state.enemies)} enemies alive, limit {enemy_limit} (wave cap {wave_cap} + adds {add_allowance})"
        )
    if len(state.projectiles) > int(projectile_limit):
        problems.append(f"{len(state.projectiles)} projectiles alive, limit {projectile_limit}")
    return problems


class TransitionGuard:
    """Records every FSM transition made while installed. Illegal edges and unknown targets are violations."""

    def __init__(self, fsm, allowed=ALLOWED_TRANSITIONS) -> None:
        self._fsm = fsm
        self._allowed = allowed
        self._known = {member.value for member in GameStateName}
        self.violations: list = []
        self._installed = False

    def install(self) -> None:
        fsm = self._fsm
        original = fsm.set_state

        def guarded_set_state(state_name):
            target = _state_key(state_name)
            source = _state_key(fsm.current_state) if fsm.current_state is not None else None
            if target not in self._known:
                self.violations.append(f"transition to unknown state {target}")
            elif source is not None and target not in self._allowed.get(source, ()):
                self.violations.append(f"illegal transition {source} -> {target}")
            return original(state_name)

        fsm.set_state = guarded_set_state
        self._installed = True

    def uninstall(self) -> None:
        if self._installed:
            self._fsm.__dict__.pop("set_state", None)
            self._installed = False


class SoftlockWatch:
    """Softlock detector. Feed it once per fixed step; it returns True when a softlock is confirmed."""

    def __init__(self, limit_s: float = SOFTLOCK_SECONDS) -> None:
        self.limit = float(limit_s)
        self.last_progress = 0.0
        self._active = False
        self._seen: dict = {}  # id(enemy) -> (enemy, hp + shield) at the previous step

    def update(self, game_time: float, wave_active: bool, enemies) -> bool:
        if not wave_active:
            self._active = False
            self._seen = {}
            self.last_progress = float(game_time)
            return False
        if not self._active:
            self._active = True
            self._seen = {}
            self.last_progress = float(game_time)

        current = {}
        for e in enemies:
            current[id(e)] = (e, int(e.hp) + int(getattr(e, "shield", 0)))
        progress = False
        for key, (obj, total) in self._seen.items():
            now = current.get(key)
            if now is None or now[0] is not obj or now[1] < total:
                progress = True  # killed, left the fight, or lost HP or shield
                break
        self._seen = current
        if progress:
            self.last_progress = float(game_time)
        return bool(enemies) and float(game_time) - self.last_progress >= self.limit - 1e-9

    def behaviours(self, enemies) -> dict:
        counts: dict = {}
        for e in enemies:
            name = enemy_behavior_name(e)
            counts[name] = counts.get(name, 0) + 1
        return dict(sorted(counts.items()))


class _SilentAudio:
    """Stand-in for AudioManager. Every call is a no-op, so runs never open the sound device."""

    def play(self, *args, **kwargs):
        pass

    def play_music(self, *args, **kwargs):
        pass

    def stop_music(self, *args, **kwargs):
        pass

    def duck(self, *args, **kwargs):
        pass

    def set_volumes(self, *args, **kwargs):
        pass

    def update(self, dt):
        pass


def _no_banner(*args, **kwargs):
    return None


def _mutator_ids_for_seed(seed: int):
    """Mutator ids chosen for a run, or None when mutators.py (wave 1) is not present."""
    try:
        from mutators import MUTATORS
    except ModuleNotFoundError as exc:
        if exc.name == "mutators":
            return None
        raise
    ids = sorted(m.id for m in MUTATORS)
    rng = random.Random(f"playtest-mutators:{seed}")
    count = rng.randint(0, min(2, len(ids)))
    return sorted(rng.sample(ids, count))


def _mutators_available() -> bool:
    return _mutator_ids_for_seed(0) is not None


def _step_budget(time_limit: float) -> int:
    return int(float(time_limit) * FPS * 4) + 3600


def _empty_record(seed: int, difficulty: str) -> dict:
    return {
        "seed": int(seed),
        "difficulty": difficulty,
        "outcome": "error",
        "wave_reached": 0,
        "kills": 0,
        "game_time": 0.0,
        "steps": 0,
        "powerups_used": {},
        "ultra_used": 0,
        "dashes": 0,
        "mutators": [],
        "rewards": [],
        "violations": [],
        "violation_count": 0,
        "softlock": None,
        "error": None,
        "final_state": "",
    }


def _add_violation(record: dict, text: str) -> None:
    record["violation_count"] += 1
    if len(record["violations"]) < MAX_REPORTED_VIOLATIONS:
        record["violations"].append(text)


def _start_run(game, seed: int, difficulty: str, mutator_ids) -> None:
    """Put the game into a fresh PlayingState for this seed. Global random must already be seeded."""
    if _state_key(game.fsm.current_state) != GameStateName.MENU.value:
        game._return_to_menu()
        game.fsm.set_state(GameStateName.MENU)
    game.settings["difficulty"] = difficulty
    if mutator_ids:
        game.settings["mutators"] = list(mutator_ids)
    else:
        game.settings.pop("mutators", None)
    game._accumulator = 0.0
    game._init_game()
    game.state.init_rng(seed)
    game.popups = None
    game.hud.show_banner = _no_banner
    game.fsm.set_state(GameStateName.PLAYING)


def _record_events(record: dict, game, before_powerups, before_ultra: int, before_dash: int) -> None:
    """Count the pickups, Ultra activations and dashes made since the snapshot taken before the step."""
    alive = {id(pu) for pu in game.state.powerups}
    for pu in before_powerups:
        if id(pu) not in alive:  # the game removes a power-up only when the player picks it up
            record["powerups_used"][pu.kind] = record["powerups_used"].get(pu.kind, 0) + 1
    if int(game.player.ultra_charges) < before_ultra:
        record["ultra_used"] += 1
    if int(game.player.dash_charges) < before_dash:
        record["dashes"] += 1


def _pick_reward(game, bot: Bot, record: dict) -> None:
    """Choose one card per stage from the boss reward menu through its key path."""
    k = pyglet.window.key
    index_keys = (k._1, k._2, k._3)
    for _ in range(REWARD_ATTEMPTS):
        if _state_key(game.fsm.current_state) != GameStateName.BOSS_REWARD.value:
            record["rewards"].append({
                "temp": str(getattr(game, "_last_reward_temp_key", "")),
                "perm": str(getattr(game, "_last_reward_perm_key", "")),
            })
            return
        game.fsm.on_key_press(index_keys[bot.pick_reward_index()], 0)
        game.fsm.on_key_press(k.ENTER, 0)
    raise RuntimeError("boss reward menu did not finish")


def _play(game, record: dict, wave_limit: int, time_limit: float, mutator_ids) -> None:
    seed = record["seed"]
    fsm = game.fsm
    bot = Bot(seed)
    spawn_logic = _SPAWN_LOGIC
    guard = TransitionGuard(fsm)
    watch = SoftlockWatch()
    budget = _step_budget(time_limit)
    fixed_dt = float(game.balance.fixed_dt)
    outcome = None
    steps = 0
    record["mutators"] = list(mutator_ids or [])

    guard.install()
    try:
        while True:
            key = _state_key(fsm.current_state)
            if key == GameStateName.GAME_OVER.value:
                outcome = "game_over"
                break
            s = game.state
            # Checked only while the player is in play, so a boss reward menu after the last cleared wave is still handled.
            if key == GameStateName.PLAYING.value and int(s.wave) >= int(wave_limit):
                outcome = "wave_limit"
                break
            if float(s.time) >= float(time_limit):
                outcome = "time_limit"
                break
            if steps >= budget:
                raise RuntimeError(f"no end condition within {budget} steps (game time {float(s.time):.1f}s)")

            before_powerups = list(s.powerups)
            before_ultra = int(game.player.ultra_charges)
            before_dash = int(game.player.dash_charges)
            if key == GameStateName.BOSS_REWARD.value:
                _pick_reward(game, bot, record)
            elif key == GameStateName.PLAYING.value:
                bot.act(game)
            game.update(fixed_dt)
            steps += 1
            _record_events(record, game, before_powerups, before_ultra, before_dash)

            s = game.state
            new_key = _state_key(fsm.current_state)
            problems = list(guard.violations)
            problems += check_frame(s, game.player, new_key, spawn_logic.wave_cap(int(s.wave), int(s.max_enemies)))
            if problems:
                for text in problems:
                    _add_violation(record, text)
                outcome = "invariant"
                break
            if watch.update(float(s.time), bool(s.wave_active), s.enemies) and new_key == GameStateName.PLAYING.value:
                record["softlock"] = {
                    "wave": int(s.wave),
                    "game_time": round(float(s.time), 3),
                    "enemies": len(s.enemies),
                    "last_progress_time": round(float(watch.last_progress), 3),
                    "behaviors": watch.behaviours(s.enemies),
                }
                outcome = "softlock"
                break
    finally:
        guard.uninstall()
        record["steps"] = steps
        _finish_record(game, record)
    record["outcome"] = outcome


def _finish_record(game, record: dict) -> None:
    """Fill the progress fields from the game. Runs even when the run raised, so an error still shows where it stopped."""
    s = getattr(game, "state", None)
    record["wave_reached"] = int(s.wave) if s is not None else 0
    record["game_time"] = round(float(s.time), 3) if s is not None else 0.0
    record["kills"] = int(getattr(getattr(game, "score", None), "kills", 0))
    record["final_state"] = _state_key(getattr(getattr(game, "fsm", None), "current_state", None))


def _run_one(game, seed: int, difficulty: str, wave_limit: int, time_limit: float, mutator_ids) -> dict:
    record = _empty_record(seed, difficulty)
    saved = random.getstate()
    try:
        random.seed(seed)  # enemy AI, boss patterns and spawn planning draw from the global RNG
        _start_run(game, seed, difficulty, mutator_ids)
        _play(game, record, wave_limit, time_limit, mutator_ids)
    except Exception as exc:  # any exception in a run is a failure, recorded, and the sweep goes on
        tb = traceback.extract_tb(exc.__traceback__)
        where = f"{os.path.basename(tb[-1].filename)}:{tb[-1].lineno}" if tb else ""
        record["outcome"] = "error"
        record["error"] = {"type": type(exc).__name__, "message": str(exc), "where": where}
        _finish_record(game, record)
    finally:
        random.setstate(saved)
    return record


def _create_game():
    game = _Game()
    game.set_visible(False)
    return game


def run_playtest(runs: int = DEFAULT_RUNS, difficulties=DIFFICULTIES, seed_base: int = DEFAULT_SEED_BASE,
                 wave_limit: int = DEFAULT_WAVE_LIMIT, time_limit: float = DEFAULT_TIME_LIMIT,
                 game=None, log=None) -> dict:
    """Run the sweep and return the report dict. Pass ``game`` to reuse a window that is already open."""
    difficulties = tuple(difficulties)
    options = {
        "runs": int(runs),
        "difficulties": list(difficulties),
        "seed_base": int(seed_base),
        "wave_limit": int(wave_limit),
        "time_limit": float(time_limit),
    }
    mutators_module = _mutators_available()
    own_game = game is None
    if own_game:
        game = _create_game()
    real_audio = game.audio
    real_score_file = score_module.HIGH_SCORE_FILE
    real_progress_path = game.progress_path
    scratch = tempfile.mkdtemp(prefix="plouto-playtest-")
    records = []
    try:
        score_module.HIGH_SCORE_FILE = os.path.join(scratch, "high_scores.json")
        # Every run ends in the game's meta-progress save: keep it in the scratch folder, not the player's progress.json.
        game.progress_path = os.path.join(scratch, "progress.json")
        game.audio = _SilentAudio()
        for difficulty in difficulties:
            for index in range(int(runs)):
                seed = int(seed_base) + index
                mutator_ids = _mutator_ids_for_seed(seed) if mutators_module else None
                record = _run_one(game, seed, difficulty, int(wave_limit), float(time_limit), mutator_ids)
                records.append(record)
                if log is not None:
                    log(_format_run_line(record))
    finally:
        score_module.HIGH_SCORE_FILE = real_score_file
        game.progress_path = real_progress_path
        game.audio = real_audio
        shutil.rmtree(scratch, ignore_errors=True)
        if own_game:
            game.close()
    return build_report(options, records, mutators_module)


def build_report(options: dict, records: list, mutators_module: bool) -> dict:
    """Assemble the JSON report from the run records."""
    outcomes: dict = {}
    powerups: dict = {}
    mutators_used: set = set()
    failed = []
    softlock_seeds = set()
    for rec in records:
        outcomes[rec["outcome"]] = outcomes.get(rec["outcome"], 0) + 1
        for kind, count in rec["powerups_used"].items():
            powerups[kind] = powerups.get(kind, 0) + count
        mutators_used.update(rec["mutators"])
        if rec["outcome"] in FAILURE_OUTCOMES:
            failed.append({"seed": rec["seed"], "difficulty": rec["difficulty"], "outcome": rec["outcome"]})
        if rec["outcome"] == "softlock":
            softlock_seeds.add(rec["seed"])
    summary = {
        "runs": len(records),
        "outcomes": dict(sorted(outcomes.items())),
        "failed_runs": failed,
        "softlock_seeds": sorted(softlock_seeds),
        "max_wave_reached": max((rec["wave_reached"] for rec in records), default=0),
        "total_kills": sum(rec["kills"] for rec in records),
        "total_steps": sum(rec["steps"] for rec in records),
        "violation_count": sum(rec["violation_count"] for rec in records),
        "powerups_used": dict(sorted(powerups.items())),
        "ultra_used": sum(rec["ultra_used"] for rec in records),
        "dashes": sum(rec["dashes"] for rec in records),
        "mutators_module": bool(mutators_module),
        "mutators_used": sorted(mutators_used),
    }
    return {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "options": options,
        "runs": records,
        "summary": summary,
        "ok": not failed,
    }


def _format_run_line(rec: dict) -> str:
    line = (
        f"{rec['difficulty']:<7} seed={rec['seed']:<6} {rec['outcome']:<10} "
        f"wave={rec['wave_reached']:<3} kills={rec['kills']:<4} "
        f"time={rec['game_time']:>8.1f}s steps={rec['steps']}"
    )
    if rec["error"]:
        line += f"  ERROR {rec['error']['type']}: {rec['error']['message']} ({rec['error']['where']})"
    if rec["softlock"]:
        line += f"  SOFTLOCK wave {rec['softlock']['wave']}, {rec['softlock']['enemies']} enemies"
    if rec["violation_count"]:
        line += f"  VIOLATION {rec['violations'][0]}"
    return line


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Headless seeded bot playtest for crashes, invariant breaks and softlocks.")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS, help="seeded runs per difficulty (default 3)")
    parser.add_argument("--out", default=DEFAULT_OUT, help="JSON report path (default playtest_report.json)")
    parser.add_argument("--difficulties", default=",".join(DIFFICULTIES), help="comma list of easy, normal, hard")
    parser.add_argument("--seed-base", type=int, default=DEFAULT_SEED_BASE, help="seed of run 0 (default 1000)")
    parser.add_argument("--wave-limit", type=int, default=DEFAULT_WAVE_LIMIT, help="stop a run at this wave (default 6)")
    parser.add_argument("--time-limit", type=float, default=DEFAULT_TIME_LIMIT,
                        help="stop a run at this many game seconds (default 180)")
    args = parser.parse_args(argv)

    difficulties = [d.strip().lower() for d in args.difficulties.split(",") if d.strip()]
    if not difficulties or any(d not in DIFFICULTIES for d in difficulties):
        parser.error(f"--difficulties must be a comma list of {', '.join(DIFFICULTIES)}")
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    if args.wave_limit < 1:
        parser.error("--wave-limit must be at least 1")
    if args.time_limit <= 0:
        parser.error("--time-limit must be positive")

    out_path = os.path.abspath(args.out)
    report = run_playtest(
        runs=args.runs,
        difficulties=difficulties,
        seed_base=args.seed_base,
        wave_limit=args.wave_limit,
        time_limit=args.time_limit,
        log=print,
    )
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")

    summary = report["summary"]
    print(f"runs={summary['runs']} outcomes={summary['outcomes']} max_wave={summary['max_wave_reached']} "
          f"kills={summary['total_kills']} violations={summary['violation_count']}")
    print(f"report: {out_path}")
    print("RESULT: PASS" if report["ok"] else f"RESULT: FAIL ({len(summary['failed_runs'])} failed runs)")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
