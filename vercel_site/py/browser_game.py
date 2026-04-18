"""Browser game runtime for the Vercel build."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Any

from js import document, window
from pyodide.ffi import create_proxy

import config
from config import (
    SCREEN_W,
    SCREEN_H,
    FPS,
    MAP_CIRCLE,
    MAP_DONUT,
    MAP_CROSS,
    MAP_DIAMOND,
    POWERUP_COLORS,
    ENEMY_COLORS,
)
from enemy import update_enemy
from hazards import LaserBeam
from layout import generate_obstacles
from level import (
    GameState as GameStateData,
    spawn_wave,
    maybe_spawn_powerup,
    spawn_loot_on_enemy_death,
    get_difficulty_mods,
)
from logic import BalanceLogic
from physics import resolve_circle_obstacles
from player import Player, perform_dash, recharge_dash, format_dash_hud
from powerup import apply_powerup
from particles import ParticleSystem
from projectile import spawn_projectiles
from rpg import (
    recompute_temp_mods,
    advance_temp_rewards,
    apply_temp_reward as rpg_apply_temp,
    apply_perm_reward as rpg_apply_perm,
    roll_boss_rewards as rpg_roll_rewards,
    format_temp_hud,
    format_perm_hud,
)
from score import ScoreTracker
from utils import (
    Vec2,
    clamp_to_map,
    compute_room_radius,
    dist,
    dist_sq,
    enemy_behavior_name,
    iso_to_world,
    point_segment_distance,
    point_segment_distance_sq,
    set_view_size,
    to_iso,
)
from weapons import get_effective_fire_rate, get_weapon_for_wave


TAU = math.tau
MAP_OPTIONS = [MAP_CIRCLE, MAP_DONUT, MAP_CROSS, MAP_DIAMOND]
DIFFICULTY_OPTIONS = ["easy", "normal", "hard"]
STATE_MENU = "menu"
STATE_GUIDE = "guide"
STATE_PLAYING = "playing"
STATE_PAUSED = "paused"
STATE_REWARD = "boss_reward"
STATE_GAME_OVER = "game_over"


@dataclass
class UIButton:
    label: str
    x: float
    y: float
    width: float
    height: float
    action: str
    payload: Any = None
    accent: tuple[int, int, int] = (126, 197, 255)

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px <= self.x + self.width and self.y <= py <= self.y + self.height


class BrowserGame:
    """Canvas-based browser runtime that reuses the existing Python game logic."""

    def __init__(self) -> None:
        self.canvas = document.getElementById("game-canvas")
        self.ctx = self.canvas.getContext("2d")
        self.loading = document.getElementById("loading-status")
        self.shell = document.getElementById("shell")

        self.balance = BalanceLogic(fps=float(FPS))
        self._fixed_dt = self.balance.fixed_dt
        self._frame_dt_cap = 0.10  # Much tighter cap — prevents speed spikes
        self._max_catchup_steps = 3  # Was 6 — prevents burst-speed after tab switch
        self._accumulator = 0.0
        self._last_ts = 0.0
        self.background_t = 0.0
        self.flash = 0.0
        self.impact = 0.0

        # Atmospheric star field (persistent across frames)
        self._stars: list[dict] = []
        for _ in range(30):
            self._stars.append({
                "x": random.random(),
                "y": random.random(),
                "vx": random.uniform(-0.005, 0.005),
                "vy": random.uniform(-0.004, 0.004),
                "r": random.uniform(0.8, 3.0),
                "phase": random.uniform(0, math.tau),
            })
        self._is_playing = False  # cached for perf

        self.state_name = STATE_MENU
        self.state: GameStateData | None = None
        self.player: Player | None = None
        self.score = ScoreTracker()
        self.particles = ParticleSystem()

        self.menu_buttons: list[UIButton] = []
        self.reward_buttons: list[UIButton] = []
        self.pause_buttons: list[UIButton] = []
        self.game_over_buttons: list[UIButton] = []

        self.keys_down: set[str] = set()
        self.mouse_screen = Vec2(SCREEN_W * 0.5, SCREEN_H * 0.5)
        self._mouse_down = False
        self._rmb_down = False
        self.auto_shoot = False

        self.settings = {
            "difficulty": "normal",
            "map_type": MAP_CIRCLE,
        }

        self.reward_temp_options: list[dict] = []
        self.reward_perm_options: list[dict] = []
        self.reward_step = "temp"
        self.reward_message = ""
        self.final_score = 0
        self.final_wave = 0
        self.high_score = 0
        self.is_new_high = False

        self._active_temp_rewards: list[dict] = []
        self._run_permanent_rewards: list[str] = []
        self._last_reward_temp_key = ""
        self._last_reward_perm_key = ""
        self._pickup_magnet_bonus = 0.0
        self._temp_damage_mult = 1.0
        self._temp_speed_mult = 1.0
        self._temp_fire_rate_mult = 1.0
        self._temp_incoming_damage_mult = 1.0
        self._incoming_damage_mult = 1.0
        self._ultra_cd_mult = 1.0
        self._dash_cd_mult = 1.0
        self._dash_cd_difficulty = 1.0
        self._wave_banner_t = 0.0
        self._last_cleared_wave = 0

        self._resize_proxy = create_proxy(self._on_resize)
        self._keydown_proxy = create_proxy(self._on_key_down)
        self._keyup_proxy = create_proxy(self._on_key_up)
        self._mousemove_proxy = create_proxy(self._on_mouse_move)
        self._mousedown_proxy = create_proxy(self._on_mouse_down)
        self._mouseup_proxy = create_proxy(self._on_mouse_up)
        self._context_proxy = create_proxy(self._on_context_menu)
        self._frame_proxy = create_proxy(self._frame)

        window.addEventListener("resize", self._resize_proxy)
        window.addEventListener("keydown", self._keydown_proxy)
        window.addEventListener("keyup", self._keyup_proxy)
        self.canvas.addEventListener("mousemove", self._mousemove_proxy)
        self.canvas.addEventListener("mousedown", self._mousedown_proxy)
        self.canvas.addEventListener("mouseup", self._mouseup_proxy)
        self.canvas.addEventListener("contextmenu", self._context_proxy)

        self._on_resize(None)
        self._rebuild_ui()
        self._set_loading("Python runtime ready. Launching browser build...")

    def start(self) -> None:
        """Start the animation loop."""
        if self.shell:
            self.shell.setAttribute("data-ready", "true")
        window.requestAnimationFrame(self._frame_proxy)

    def _set_loading(self, text: str) -> None:
        if self.loading:
            self.loading.textContent = text

    def _on_resize(self, _event) -> None:
        # Use full window dimensions for true fullscreen
        win_w = int(window.innerWidth or SCREEN_W)
        win_h = int(window.innerHeight or SCREEN_H)
        width = max(640, win_w)
        height = max(480, win_h)
        dpr = max(1.0, min(2.0, float(window.devicePixelRatio or 1.0)))  # Cap DPR for perf
        self.canvas.width = int(width * dpr)
        self.canvas.height = int(height * dpr)
        self.canvas.style.width = f"{width}px"
        self.canvas.style.height = f"{height}px"
        self.view_w = width
        self.view_h = height
        self.dpr = dpr
        self.ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
        set_view_size(width, height)
        config.ROOM_RADIUS = compute_room_radius(width, height, margin=float(getattr(config, "ARENA_MARGIN", 0.94)))
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        scale = max(0.85, min(1.4, min(self.view_w / 1280.0, self.view_h / 820.0)))
        btn_w = 250 * scale
        btn_h = 58 * scale
        cx = self.view_w * 0.5 - btn_w * 0.5
        start_y = self.view_h * 0.46
        gap = 18 * scale

        difficulty = self.settings["difficulty"].title()
        arena = self.settings["map_type"].replace("_", " ").title()
        self.menu_buttons = [
            UIButton("Start Run", cx, start_y, btn_w, btn_h, "start"),
            UIButton(f"Difficulty: {difficulty}", cx, start_y + (btn_h + gap), btn_w, btn_h, "difficulty"),
            UIButton(f"Arena: {arena}", cx, start_y + 2 * (btn_h + gap), btn_w, btn_h, "map"),
            UIButton("How To Play", cx, start_y + 3 * (btn_h + gap), btn_w, btn_h, "guide"),
        ]

        pw = 230 * scale
        ph = 54 * scale
        py = self.view_h * 0.5 - 20 * scale
        self.pause_buttons = [
            UIButton("Resume", self.view_w * 0.5 - pw * 0.5, py, pw, ph, "resume"),
            UIButton("Restart", self.view_w * 0.5 - pw * 0.5, py + ph + gap, pw, ph, "restart"),
            UIButton("Main Menu", self.view_w * 0.5 - pw * 0.5, py + 2 * (ph + gap), pw, ph, "menu"),
        ]

        gy = self.view_h * 0.5 + 80 * scale
        self.game_over_buttons = [
            UIButton("Run Again", self.view_w * 0.5 - pw * 0.5, gy, pw, ph, "restart"),
            UIButton("Main Menu", self.view_w * 0.5 - pw * 0.5, gy + ph + gap, pw, ph, "menu"),
        ]

        self._rebuild_reward_buttons()

    def _rebuild_reward_buttons(self) -> None:
        self.reward_buttons = []
        options = self.reward_temp_options if self.reward_step == "temp" else self.reward_perm_options
        if not options:
            return
        scale = max(0.85, min(1.3, min(self.view_w / 1280.0, self.view_h / 840.0)))
        gap = 18 * scale
        width = min(self.view_w * 0.26, 290 * scale)
        height = 170 * scale
        total_w = width * len(options) + gap * (len(options) - 1)
        start_x = (self.view_w - total_w) * 0.5
        y = self.view_h * 0.42
        for idx, option in enumerate(options):
            self.reward_buttons.append(
                UIButton(
                    option["title"],
                    start_x + idx * (width + gap),
                    y,
                    width,
                    height,
                    "reward",
                    option,
                    (255, 212, 132) if self.reward_step == "temp" else (164, 225, 255),
                )
            )

    def _frame(self, ts: float) -> None:
        if not self._last_ts:
            self._last_ts = ts
        raw_dt = (ts - self._last_ts) / 1000.0
        self._last_ts = ts

        # Tab-switch protection: if the browser was backgrounded for >100ms,
        # discard the accumulated time instead of fast-forwarding the game.
        if raw_dt > 0.1:
            raw_dt = self._fixed_dt  # Pretend only one frame passed
            self._accumulator = 0.0

        dt = max(0.0, min(raw_dt, self._frame_dt_cap))
        self.background_t += dt

        self._accumulator += dt
        steps = 0
        while self._accumulator >= self._fixed_dt and steps < self._max_catchup_steps:
            self.update(self._fixed_dt)
            self._accumulator -= self._fixed_dt
            steps += 1
        # Drain leftover to prevent gradual accumulation on slow frames
        if self._accumulator > self._fixed_dt * 2.0:
            self._accumulator = self._fixed_dt * 0.5

        self.render()
        window.requestAnimationFrame(self._frame_proxy)

    def update(self, dt: float) -> None:
        self._is_playing = self.state_name == STATE_PLAYING
        self.flash = max(0.0, self.flash - dt * 2.6)
        self.impact = max(0.0, self.impact - dt * 6.0)
        self._wave_banner_t = max(0.0, self._wave_banner_t - dt)

        if self.state_name == STATE_PLAYING and self.state and self.player:
            self.particles.update(dt)
            self._update_playing(dt)


    def _input_dir(self) -> Vec2:
        x = 0.0
        y = 0.0
        if "a" in self.keys_down or "arrowleft" in self.keys_down:
            x -= 1.0
        if "d" in self.keys_down or "arrowright" in self.keys_down:
            x += 1.0
        if "w" in self.keys_down or "arrowup" in self.keys_down:
            y -= 1.0
        if "s" in self.keys_down or "arrowdown" in self.keys_down:
            y += 1.0
        return Vec2(x, y)

    def _effective_player_damage(self) -> int:
        if not self.player:
            return 10
        return max(1, int(round(float(self.player.damage) * float(self._temp_damage_mult))))

    def _effective_player_speed(self) -> float:
        if not self.player:
            return 0.0
        return float(self.player.speed) * float(self._temp_speed_mult)

    def _effective_player_fire_rate(self) -> float:
        if not self.player:
            return 0.28
        return max(0.08, float(self.player.fire_rate) * float(self._temp_fire_rate_mult))

    def _recompute_temp_reward_mods(self) -> None:
        mods = recompute_temp_mods(self._active_temp_rewards)
        self._temp_damage_mult = mods["damage"]
        self._temp_speed_mult = mods["speed"]
        self._temp_fire_rate_mult = mods["fire_rate"]
        self._pickup_magnet_bonus = mods["magnet"]
        self._temp_incoming_damage_mult = mods["incoming_damage"]
        self._ultra_cd_mult = mods["ultra_cd"]

    def _advance_temp_rewards(self) -> None:
        self._active_temp_rewards = advance_temp_rewards(self._active_temp_rewards)
        self._recompute_temp_reward_mods()

    def _roll_boss_rewards(self) -> None:
        self.reward_temp_options, self.reward_perm_options = rpg_roll_rewards(
            self._active_temp_rewards,
            self._last_reward_temp_key,
            self._last_reward_perm_key,
        )
        self.reward_step = "temp"
        self.reward_message = "Pick one temporary card"
        self._rebuild_reward_buttons()

    def _apply_temp_reward(self, key: str, duration: int) -> None:
        if not self.player:
            return
        k = str(key or "").strip().lower()
        rpg_apply_temp(self._active_temp_rewards, k, duration)
        self._last_reward_temp_key = k
        if k == "temp_ultra_flux":
            self.player.ultra_charges = min(int(getattr(config, "ULTRA_MAX_CHARGES", 2)), int(self.player.ultra_charges) + 1)
        self._recompute_temp_reward_mods()
        self.flash = max(self.flash, 0.42)

    def _apply_perm_reward(self, key: str) -> None:
        if not self.player:
            return
        k = str(key or "").strip().lower()
        self._dash_cd_mult, applied = rpg_apply_perm(
            self.player,
            self._run_permanent_rewards,
            k,
            self._dash_cd_mult,
            ultra_max_charges=int(getattr(config, "ULTRA_MAX_CHARGES", 2)),
        )
        if applied:
            self._last_reward_perm_key = k
            self.flash = max(self.flash, 0.56)

    def _regen_layout(self, segment: int | None = None) -> None:
        if not config.ENABLE_OBSTACLES or not self.state:
            if self.state:
                self.state.obstacles = []
            return
        if segment is None:
            segment = int(getattr(self.state, "layout_segment", 0))
        self.state.layout_segment = int(segment)
        self.state.obstacles = generate_obstacles(
            int(getattr(self.state, "layout_seed", 0)),
            self.state.layout_segment,
            config.ROOM_RADIUS,
            difficulty=getattr(self.state, "difficulty", "normal"),
        )

    def _enemy_radius(self, enemy) -> float:
        return self.balance.enemy_radius(enemy_behavior_name(enemy))

    def _player_radius(self) -> float:
        return self.balance.player_radius

    def _projectile_radius(self, projectile) -> float:
        return self.balance.projectile_radius(str(getattr(projectile, "projectile_type", "bullet")))

    def _ultra_variant_name(self) -> str:
        names = ("Beam", "Tri-Beam", "Shockwave")
        idx = int(getattr(self.player, "ultra_variant_idx", 0)) % len(names)
        return names[idx]

    def _damage_player(self, amount: int) -> None:
        if not self.player or self.player.invincibility_timer > 0 or amount <= 0:
            return
        mult = float(self._incoming_damage_mult) * float(self._temp_incoming_damage_mult)
        amount = max(1, int(round(amount * mult)))
        if self.player.shield > 0:
            absorbed = min(self.player.shield, amount)
            self.player.shield -= absorbed
            amount -= absorbed
        if amount > 0:
            self.player.hp -= amount
            self.score.on_player_hit()
            self.particles.add_hit_particles(self.player.pos, (255, 100, 100))
            self.flash = max(self.flash, 0.34)

    def _use_ultra(self) -> None:
        if not self.state or not self.player:
            return
        if self.player.ultra_charges <= 0 or self.state.time < self.player.ultra_cd_until:
            return

        world_mouse = iso_to_world((self.mouse_screen.x, self.mouse_screen.y))
        aim = (world_mouse - self.player.pos).normalized()
        if aim.length() <= 1e-6:
            aim = Vec2(1.0, 0.0)

        muzzle = self.player.pos + aim * 14.0
        dmg = int(config.ULTRA_DAMAGE_BASE + self._effective_player_damage() * config.ULTRA_DAMAGE_MULT)
        beam_thickness = float(config.ULTRA_BEAM_THICKNESS)
        beam_ttl = float(config.ULTRA_BEAM_TTL)

        def hit_enemy(enemy_obj, amount: int) -> None:
            enemy_obj.hp -= int(amount)
            if enemy_obj.hp <= 0:
                self._kill_enemy(enemy_obj)

        def spawn_beam(start: Vec2, direction: Vec2, length: float, damage: int, thickness: float, color: tuple[int, int, int]) -> None:
            end = start + direction * length
            beam = LaserBeam(
                start=start,
                end=end,
                damage=int(damage),
                thickness=float(thickness),
                ttl=beam_ttl,
                owner="player",
                color=tuple(color),
            )
            self.state.lasers.append(beam)
            hit_r = float(thickness) * 0.5
            for enemy_obj in list(self.state.enemies):
                if point_segment_distance(enemy_obj.pos, start, end) <= hit_r + self._enemy_radius(enemy_obj):
                    hit_enemy(enemy_obj, int(damage))

        variant = int(getattr(self.player, "ultra_variant_idx", 0)) % 3
        self.player.ultra_variant_idx = (variant + 1) % 3

        if variant == 0:
            spawn_beam(muzzle, aim, config.ROOM_RADIUS * 2.05, dmg, beam_thickness, tuple(config.ULTRA_BEAM_COLOR))
        elif variant == 1:
            for deg in (-16.0, 0.0, 16.0):
                a = math.radians(deg)
                c = math.cos(a)
                s = math.sin(a)
                direction = Vec2(aim.x * c - aim.y * s, aim.x * s + aim.y * c).normalized()
                spawn_beam(muzzle, direction, config.ROOM_RADIUS * 1.9, int(dmg * 0.72), beam_thickness * 0.8, (255, 180, 180))
        else:
            blast_r = 160.0
            for enemy_obj in list(self.state.enemies):
                if dist(enemy_obj.pos, self.player.pos) <= blast_r:
                    hit_enemy(enemy_obj, int(dmg * 0.58))
            spawn_beam(muzzle, aim, config.ROOM_RADIUS * 1.55, int(dmg * 0.62), beam_thickness * 0.7, (255, 210, 120))

        self.player.ultra_charges = max(0, int(self.player.ultra_charges) - 1)
        self.player.ultra_cd_until = self.state.time + float(config.ULTRA_COOLDOWN) * float(self._ultra_cd_mult)
        self.flash = max(self.flash, 0.8)

    def _dash(self) -> None:
        if not self.state or not self.player:
            return
        world_mouse = iso_to_world((self.mouse_screen.x, self.mouse_screen.y))
        if perform_dash(
            self.player,
            self.state.time,
            self.balance,
            float(self._dash_cd_difficulty),
            float(self._dash_cd_mult),
            self._input_dir(),
            world_mouse,
        ):
            if self.player.is_dashing:
                self.particles.add_dash_effect(self.player.pos, self.player.dash_direction)
            self.flash = max(self.flash, 0.2)

    def _remove_projectile(self, projectile) -> None:
        if self.state and projectile in self.state.projectiles:
            self.state.projectiles.remove(projectile)

    def _kill_enemy(self, enemy_obj) -> None:
        if not self.state:
            return
        behavior = enemy_behavior_name(enemy_obj)
        if enemy_obj in self.state.enemies:
            self.state.enemies.remove(enemy_obj)
        spawn_loot_on_enemy_death(self.state, behavior, enemy_obj.pos)
        self.particles.add_death_explosion(enemy_obj.pos, ENEMY_COLORS.get(behavior, (220, 220, 220)), behavior)
        self.score.on_enemy_kill(behavior)
        self.impact = max(self.impact, 0.32)

    def _explode_enemy_bomb(self, projectile) -> None:
        if not self.state or not self.player:
            return
        blast_r2 = float(self.balance.bomb_blast_radius) ** 2
        blast_dmg = self.balance.bomb_blast_damage(int(getattr(projectile, "damage", 0)))
        if dist_sq(projectile.pos, self.player.pos) <= blast_r2:
            self._damage_player(blast_dmg)
            self.state.shake = max(self.state.shake, 12.0)

    def _projectile_hits_obstacle(self, prev: Vec2, pos: Vec2, radius: float, obstacles) -> bool:
        for obstacle in obstacles:
            hit_r2 = (float(obstacle.radius) + float(radius)) ** 2
            if point_segment_distance_sq(obstacle.pos, prev, pos) <= hit_r2:
                return True
        return False

    def _segment_hits_circle(self, center: Vec2, prev: Vec2, pos: Vec2, hit_r2: float) -> bool:
        return point_segment_distance_sq(center, prev, pos) <= hit_r2

    def _start_game(self) -> None:
        difficulty = str(self.settings.get("difficulty", "normal")).lower()
        map_type = self.settings.get("map_type", MAP_CIRCLE)

        self.state = GameStateData(difficulty=difficulty, map_type=map_type)
        self.state.init_rng()
        self.state.last_wave_clear = -self.balance.wave_cooldown
        self.player = Player(pos=Vec2(0.0, 0.0))
        self.player.current_weapon = get_weapon_for_wave(1)
        self.auto_shoot = False
        self.mouse_screen = Vec2(self.view_w * 0.5, self.view_h * 0.5)
        self.reward_temp_options = []
        self.reward_perm_options = []
        self.reward_step = "temp"
        self.reward_message = ""
        self._active_temp_rewards = []
        self._run_permanent_rewards = []
        self._last_reward_temp_key = ""
        self._last_reward_perm_key = ""
        self._pickup_magnet_bonus = 0.0
        self._temp_damage_mult = 1.0
        self._temp_speed_mult = 1.0
        self._temp_fire_rate_mult = 1.0
        self._temp_incoming_damage_mult = 1.0
        self._ultra_cd_mult = 1.0
        self._dash_cd_mult = 1.0
        self._wave_banner_t = 2.0
        self._last_cleared_wave = 0
        self.score = ScoreTracker(difficulty=difficulty)
        self._recompute_temp_reward_mods()

        if difficulty == "easy":
            self.state.max_enemies = 10
            self._incoming_damage_mult = 0.85
        elif difficulty == "hard":
            self.state.max_enemies = 14
            self._incoming_damage_mult = 1.15
        else:
            self.state.max_enemies = 12
            self._incoming_damage_mult = 1.0

        self._dash_cd_difficulty = float(get_difficulty_mods(difficulty).get("dash_cd", 1.0))

        if config.ENABLE_OBSTACLES:
            self.state.layout_seed = self.state.rng.randint(0, 1_000_000_000)
            self.state.layout_segment = 0
            self.state.obstacles = generate_obstacles(
                self.state.layout_seed,
                self.state.layout_segment,
                config.ROOM_RADIUS,
                difficulty=self.state.difficulty,
            )
        else:
            self.state.obstacles = []

        self.state_name = STATE_PLAYING
        self.flash = 0.25

    def _return_to_menu(self) -> None:
        self.state = None
        self.player = None
        self.auto_shoot = False
        self.reward_temp_options = []
        self.reward_perm_options = []
        self.state_name = STATE_MENU

    def _finish_run(self) -> None:
        if not self.state:
            return
        self.final_wave = int(self.state.wave)
        self.final_score = int(self.score.score)
        self.is_new_high = self.score.submit_score(self.final_wave)
        self.high_score = self.score.get_high_score()
        self.state_name = STATE_GAME_OVER

    def _update_playing(self, dt: float) -> None:
        if not self.state or not self.player:
            return
        s = self.state
        s.time += dt
        self.score.update(dt)

        if self.player.invincibility_timer > 0:
            self.player.invincibility_timer -= dt

        if not s.wave_active and (s.time - s.last_wave_clear) >= self.balance.wave_cooldown:
            spawn_wave(s, Vec2(0.0, 0.0))
            self._wave_banner_t = 1.5

        if s.time < self.player.vortex_until:
            vortex_r2 = float(self.player.vortex_radius) ** 2
            dps = float(self.player.vortex_dps)
            self.particles.add_vortex_swirl(self.player.pos, s.time, float(self.player.vortex_radius))
            for enemy_obj in list(s.enemies):
                if dist_sq(enemy_obj.pos, self.player.pos) <= vortex_r2:
                    acc = getattr(enemy_obj, "_vortex_acc", 0.0) + dps * dt
                    dmg = int(acc)
                    enemy_obj._vortex_acc = acc - dmg
                    if dmg > 0:
                        enemy_obj.hp -= dmg
                        if enemy_obj.hp <= 0:
                            self._kill_enemy(enemy_obj)

        player_radius = self._player_radius()

        for trap in list(getattr(s, "traps", [])):
            trap.t += dt
            trap.ttl -= dt
            if trap.ttl <= 0:
                s.traps.remove(trap)
                continue
            if trap.t >= trap.armed_delay:
                hit_r = float(trap.radius) + float(player_radius)
                if dist_sq(trap.pos, self.player.pos) <= hit_r * hit_r:
                    self._damage_player(trap.damage)
                    s.shake = max(s.shake, 10.0)
                    s.traps.remove(trap)

        for thunder in list(getattr(s, "thunders", [])):
            thunder.t += dt
            if thunder.t >= thunder.warn and not thunder.hit_done:
                hit_r = thunder.thickness * 0.6 + player_radius * 0.35
                if point_segment_distance_sq(self.player.pos, thunder.start, thunder.end) <= hit_r * hit_r:
                    thunder.hit_done = True
                    self._damage_player(thunder.damage)
                    s.shake = max(s.shake, 14.0)
            if thunder.t >= thunder.warn + thunder.ttl:
                s.thunders.remove(thunder)

        old_pos = Vec2(self.player.pos.x, self.player.pos.y)
        if self.player.is_dashing:
            self.player.pos += self.player.dash_direction * self.player.dash_speed * dt
            self.player.dash_timer -= dt
            if self.player.dash_timer <= 0:
                self.player.is_dashing = False
        else:
            input_dir = self._input_dir()
            if input_dir.length() > 0:
                self.player.pos = self.player.pos + input_dir.normalized() * self._effective_player_speed() * dt
                # Step dust particles
                if s.rng.random() < 0.3:
                    self.particles.add_step_dust(self.player.pos, input_dir.normalized())

        recharge_dash(self.player, s.time, self.balance, self._dash_cd_difficulty, self._dash_cd_mult)
        if self.player.is_dashing:
            self.particles.add_dash_effect(self.player.pos, self.player.dash_direction)
        self.player.pos = clamp_to_map(self.player.pos, config.ROOM_RADIUS * 0.9, s.map_type)
        if config.ENABLE_OBSTACLES and getattr(s, "obstacles", None):
            self.player.pos = resolve_circle_obstacles(self.player.pos, player_radius, s.obstacles)
            self.player.pos = clamp_to_map(self.player.pos, config.ROOM_RADIUS * 0.9, s.map_type)

        if dt > 1e-6:
            player_vel = (self.player.pos - old_pos) * (1.0 / dt)
        else:
            player_vel = Vec2(0.0, 0.0)

        weapon = self.player.current_weapon
        if weapon and self.player.recoil > 0:
            self.player.recoil = max(0.0, self.player.recoil - float(weapon.recoil_recover) * dt)

        weapon_cd = get_effective_fire_rate(weapon, self._effective_player_fire_rate()) if weapon else 0.28
        if weapon and weapon.cadence_jitter:
            weapon_cd *= s.rng.uniform(1.0 - weapon.cadence_jitter, 1.0 + weapon.cadence_jitter)
        weapon_cd = max(float(getattr(config, "FIRE_RATE_MIN", 0.06)), weapon_cd)

        if weapon and self.auto_shoot and s.time >= float(self.player.next_shot_time):
            world_mouse = iso_to_world((self.mouse_screen.x, self.mouse_screen.y))
            aim = (world_mouse - self.player.pos).normalized()
            if aim.length() <= 1e-6:
                aim = Vec2(1.0, 0.0)
            muzzle = self.player.pos + aim * 14.0

            if s.time < self.player.laser_until:
                beam_len = config.ROOM_RADIUS * 1.6
                end = muzzle + aim * beam_len
                dmg = int(self._effective_player_damage() * 0.9) + 14
                beam = LaserBeam(start=muzzle, end=end, damage=dmg, thickness=12.0, ttl=0.08, owner="player")
                s.lasers.append(beam)
                for enemy_obj in list(s.enemies):
                    hit_r = beam.thickness * 0.5 + self._enemy_radius(enemy_obj)
                    if point_segment_distance_sq(enemy_obj.pos, muzzle, end) <= hit_r * hit_r:
                        enemy_obj.hp -= dmg
                        if enemy_obj.hp <= 0:
                            self._kill_enemy(enemy_obj)
            else:
                self.player.recoil = min(float(weapon.recoil_max), float(self.player.recoil) + float(weapon.recoil_kick))
                self.particles.add_muzzle_flash(muzzle, aim)
                s.projectiles.extend(
                    spawn_projectiles(
                        muzzle,
                        aim,
                        weapon,
                        s.time,
                        self._effective_player_damage(),
                        recoil_deg=float(self.player.recoil),
                        rng=s.rng,
                    )
                )

            self.player.last_shot = s.time
            self.player.next_shot_time = s.time + weapon_cd

        for enemy_obj in list(s.enemies):
            update_enemy(enemy_obj, self.player.pos, s, dt, self, player_vel=player_vel)
            behavior = enemy_behavior_name(enemy_obj)
            enemy_obj._behavior_name = behavior
            enemy_obj._radius = self.balance.enemy_radius(behavior)
            enemy_obj.pos = clamp_to_map(enemy_obj.pos, config.ROOM_RADIUS * 0.96, s.map_type)
            if config.ENABLE_OBSTACLES and getattr(s, "obstacles", None):
                enemy_obj.pos = resolve_circle_obstacles(enemy_obj.pos, enemy_obj._radius, s.obstacles)
                enemy_obj.pos = clamp_to_map(enemy_obj.pos, config.ROOM_RADIUS * 0.96, s.map_type)
            hit_r = float(enemy_obj._radius) + float(player_radius)
            if dist_sq(enemy_obj.pos, self.player.pos) <= hit_r * hit_r:
                self._damage_player(self.balance.enemy_contact_damage)
                self._kill_enemy(enemy_obj)
                s.shake = 9.0

        obstacles = s.obstacles if (config.ENABLE_OBSTACLES and getattr(s, "obstacles", None)) else None
        for projectile in list(s.projectiles):
            projectile.update(dt)
            if obstacles:
                prev = projectile.prev_pos or projectile.pos
                if self._projectile_hits_obstacle(prev, projectile.pos, self._projectile_radius(projectile), obstacles):
                    if projectile.owner == "enemy" and str(getattr(projectile, "projectile_type", "bullet")) == "bomb":
                        self._explode_enemy_bomb(projectile)
                    self._remove_projectile(projectile)
                    continue
            if projectile.ttl <= 0:
                if projectile.owner == "enemy" and str(getattr(projectile, "projectile_type", "bullet")) == "bomb":
                    self._explode_enemy_bomb(projectile)
                self._remove_projectile(projectile)

        for projectile in list(s.projectiles):
            p_prev = projectile.prev_pos or projectile.pos
            pr = self._projectile_radius(projectile)
            if projectile.owner == "player":
                for enemy_obj in list(s.enemies):
                    er = getattr(enemy_obj, "_radius", self._enemy_radius(enemy_obj))
                    hit_r2 = (float(pr) + float(er)) ** 2
                    if self._segment_hits_circle(enemy_obj.pos, p_prev, projectile.pos, hit_r2):
                        enemy_obj.hp -= projectile.damage
                        self._remove_projectile(projectile)
                        if enemy_obj.hp <= 0:
                            behavior = getattr(enemy_obj, "_behavior_name", enemy_behavior_name(enemy_obj))
                            self._kill_enemy(enemy_obj)
                            if behavior == "tank" and dist(enemy_obj.pos, self.player.pos) < self.balance.tank_death_blast_radius:
                                self._damage_player(self.balance.tank_death_blast_damage)
                        break
            else:
                hit_r2 = (float(pr) + float(player_radius)) ** 2
                ptype = str(getattr(projectile, "projectile_type", "bullet"))
                if ptype == "bomb":
                    if self._segment_hits_circle(self.player.pos, p_prev, projectile.pos, hit_r2):
                        self._explode_enemy_bomb(projectile)
                        self._remove_projectile(projectile)
                elif self._segment_hits_circle(self.player.pos, p_prev, projectile.pos, hit_r2):
                    self._damage_player(projectile.damage)
                    self._remove_projectile(projectile)

        for powerup in list(s.powerups):
            dpu2 = dist_sq(powerup.pos, self.player.pos)
            magnet_r = self.balance.pickup_magnet_radius(getattr(powerup, "kind", ""), self._pickup_magnet_bonus)
            if 1e-12 < dpu2 < float(magnet_r) * float(magnet_r):
                distance_to_player = math.sqrt(dpu2)
                pull = (self.player.pos - powerup.pos).normalized()
                pull_speed = self.balance.pickup_pull_speed(magnet_r, distance_to_player)
                powerup.pos = powerup.pos + pull * pull_speed * dt
                dpu2 = dist_sq(powerup.pos, self.player.pos)
            pickup_r = self.balance.pickup_radius(getattr(powerup, "kind", ""))
            if dpu2 < float(pickup_r) * float(pickup_r):
                apply_powerup(self.player, powerup, s.time)
                self.particles.add_powerup_collection(powerup.pos, POWERUP_COLORS.get(getattr(powerup, 'kind', ''), (220, 220, 220)))
                s.powerups.remove(powerup)
                self.flash = max(self.flash, 0.18)

        if s.wave_active and not s.enemies:
            cleared_wave = int(s.wave)
            s.wave_active = False
            s.last_wave_clear = s.time
            s.wave += 1
            self._advance_temp_rewards()
            new_segment = (s.wave - 1) // 5
            if config.ENABLE_OBSTACLES and new_segment != getattr(s, "layout_segment", 0):
                self._regen_layout(new_segment)
            self.player.current_weapon = get_weapon_for_wave(s.wave)
            maybe_spawn_powerup(s, Vec2(0.0, 0.0))
            self.score.on_wave_clear(cleared_wave)
            self._last_cleared_wave = cleared_wave
            self._wave_banner_t = 1.8

            if cleared_wave % 5 == 0:
                self._roll_boss_rewards()
                self.state_name = STATE_REWARD

        for beam in list(getattr(s, "lasers", [])):
            beam.t += dt
            if beam.owner == "enemy" and beam.t >= beam.warn and not beam.hit_done:
                hit_r = beam.thickness * 0.55 + player_radius * 0.35
                if point_segment_distance_sq(self.player.pos, beam.start, beam.end) <= hit_r * hit_r:
                    beam.hit_done = True
                    self._damage_player(beam.damage)
                    s.shake = max(s.shake, 10.0)
            if beam.t >= beam.warn + beam.ttl:
                s.lasers.remove(beam)

        if s.shake > 0:
            s.shake = max(0.0, s.shake - dt * 20.0)

        if self.player.hp <= 0:
            self._finish_run()

    def render(self) -> None:
        ctx = self.ctx
        # Motion blur clear via alpha overlay
        ctx.globalCompositeOperation = "source-over"
        ctx.fillStyle = "rgba(4, 6, 12, 0.25)"
        ctx.fillRect(0, 0, self.view_w, self.view_h)
        combat_intensity = 0.0
        if self.state:
            n_enemies = len(self.state.enemies)
            if n_enemies:
                has_boss = any(str(getattr(enemy_obj, "behavior", "")).startswith("boss_") for enemy_obj in self.state.enemies)
                combat_intensity = 0.8 if has_boss else min(0.55, 0.08 * n_enemies)

        self._draw_background(combat_intensity)
        shake = Vec2(0.0, 0.0)
        if self.state and self.state.shake > 0:
            magnitude = self.state.shake
            t = self.background_t * 22.0
            shake = Vec2(math.sin(t) * magnitude, math.cos(t * 1.21) * magnitude)

        if self.state and self.player:
            self._draw_arena(shake, combat_intensity)
            ctx.globalCompositeOperation = "screen"
            self._draw_world(shake)
            ctx.globalCompositeOperation = "source-over"
            self._draw_hud()
        else:
            self._draw_arena(shake, 0.12, preview_only=True)

        if self._wave_banner_t > 0.0 and self.state:
            self._draw_wave_banner()

        if self.state_name == STATE_MENU:
            self._draw_menu()
        elif self.state_name == STATE_GUIDE:
            self._draw_menu()
            self._draw_guide()
        elif self.state_name == STATE_PAUSED:
            self._draw_pause()
        elif self.state_name == STATE_REWARD:
            self._draw_reward_panel()
        elif self.state_name == STATE_GAME_OVER:
            self._draw_game_over()

        if self.flash > 0:
            flash_alpha = min(0.42, 0.22 * self.flash)
            # Color tint based on flash intensity
            if self.flash > 0.6:
                # Ultra / major event — warm gold flash
                ctx.fillStyle = f"rgba(255, 230, 180, {flash_alpha})"
            elif self.flash > 0.3:
                # Damage taken — red-orange tint
                ctx.fillStyle = f"rgba(255, 180, 140, {flash_alpha * 0.85})"
            else:
                # Pickup / minor — cool cyan tint
                ctx.fillStyle = f"rgba(180, 230, 255, {flash_alpha * 0.55})"
            ctx.fillRect(0, 0, self.view_w, self.view_h)

    def _draw_background(self, combat_intensity: float) -> None:
        ctx = self.ctx
        ci = max(0.0, min(1.0, combat_intensity))
        t = self.background_t
        playing = self._is_playing
        
        px = self.player.pos.x if self.player else 0.0
        py = self.player.pos.y if self.player else 0.0

        if not playing:
            grad = ctx.createLinearGradient(0, 0, self.view_w * 0.3, self.view_h)
            r0 = 10 + int(35 * ci)
            g0 = 16 + int(12 * ci)
            b0 = 32 - int(4 * ci)
            grad.addColorStop(0, f"rgb({r0}, {g0}, {b0})")
            grad.addColorStop(0.5, f"rgb({4 + int(20 * ci)}, {8 + int(5 * ci)}, {22})")
            grad.addColorStop(1, f"rgb({3 + int(15 * ci)}, {6}, {14})")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, self.view_w, self.view_h)
        else:
            # Soft tint to prevent complete washout
            ctx.fillStyle = f"rgba({4 + int(10*ci)}, {6 + int(8*ci)}, {12}, 0.08)"
            ctx.fillRect(0, 0, self.view_w, self.view_h)

        # ── Nebula glow orbs ──
        nebulae = [
            (0.25, 0.30, 380, (25, 65, 140), 0.28, 0.06),
            (0.75, 0.72, 260, (120, 50, 100), 0.18, 0.08),
        ] if playing else [
            (0.22, 0.28, 380, (30, 75, 140), 0.28, 0.06),
            (0.78, 0.68, 280, (160, 70, 120), 0.22, 0.09),
            (0.52, 0.82, 200, (70, 180, 165), 0.20, 0.11),
        ]
        for fx, fy, radius, color, amp, freq in nebulae:
            nx = self.view_w * fx + math.sin(t * freq) * 40.0 - (px * 0.02)
            ny = self.view_h * fy + math.cos(t * (freq + 0.02)) * 32.0 - (py * 0.01)
            pulse = 0.5 + 0.5 * math.sin(t * (0.7 + freq * 3.0))
            alpha = (0.08 + 0.05 * pulse) * (1.0 + ci * 0.7)
            rg = ctx.createRadialGradient(nx, ny, 0, nx, ny, radius)
            rg.addColorStop(0, f"rgba({color[0]}, {color[1]}, {color[2]}, {alpha:.3f})")
            rg.addColorStop(0.6, f"rgba({color[0]}, {color[1]}, {color[2]}, {alpha * 0.3:.3f})")
            rg.addColorStop(1, "rgba(0,0,0,0)")
            ctx.fillStyle = rg
            ctx.fillRect(nx - radius, ny - radius, radius * 2, radius * 2)

        # ── Drifting star field with Parallax ──
        ctx.beginPath()
        for idx, star in enumerate(self._stars):
            star["x"] += star["vx"] * 0.4
            star["y"] += star["vy"] * 0.4
            if star["x"] < -0.2: star["x"] += 1.4
            elif star["x"] > 1.2: star["x"] -= 1.4
            if star["y"] < -0.2: star["y"] += 1.4
            elif star["y"] > 1.2: star["y"] -= 1.4
            
            layer = (idx % 3) + 1.0
            px_mod = (px * 0.08) / layer
            py_mod = (py * 0.04) / layer
            
            sx = (star["x"] * self.view_w - px_mod) % self.view_w
            sy = (star["y"] * self.view_h - py_mod) % self.view_h
            
            twinkle = 0.6 + 0.4 * math.sin(t * 3.0 + star["phase"])
            r = star["r"] * twinkle
            ctx.moveTo(sx + r, sy)
            ctx.arc(sx, sy, r, 0, TAU)
            
        ctx.fillStyle = "rgba(180, 220, 255, 0.45)"
        ctx.fill()

        # ── Retro Parallax Wireframe Floor ──
        if playing:
            ctx.save()
            grid = 120
            p_alpha = 0.05 + 0.05 * ci
            ctx.strokeStyle = f"rgba(100, 180, 255, {p_alpha})"
            ctx.lineWidth = 1
            ox = (px * 0.9) % grid
            oy = (py * 0.45) % grid
            ctx.beginPath()
            for x in range(0, self.view_w + grid, grid):
                ctx.moveTo(x - ox, 0)
                ctx.lineTo(x - ox, self.view_h)
            for y in range(0, self.view_h + grid, grid):
                ctx.moveTo(0, y - oy)
                ctx.lineTo(self.view_w, y - oy)
            ctx.stroke()
            ctx.restore()
        else:
            # Scan-line grid menu
            ctx.save()
            ctx.globalAlpha = 0.08
            ctx.strokeStyle = "rgba(130, 180, 255, 0.2)"
            ctx.lineWidth = 1
            step = 44
            drift = (t * 18.0) % step
            for x in range(-step, self.view_w + step, step):
                ctx.beginPath()
                ctx.moveTo(x + drift, 0)
                ctx.lineTo(x + drift - self.view_h * 0.22, self.view_h)
                ctx.stroke()
            ctx.restore()

        # ── Vignette — always active, stronger during combat ──
        vign_strength = 0.12 + ci * 0.06
        vg = ctx.createRadialGradient(
            self.view_w * 0.5, self.view_h * 0.5, min(self.view_w, self.view_h) * 0.25,
            self.view_w * 0.5, self.view_h * 0.5, max(self.view_w, self.view_h) * 0.68,
        )
        vg.addColorStop(0, "rgba(0,0,0,0)")
        vg.addColorStop(1, f"rgba(0,0,0,{vign_strength:.3f})")
        ctx.fillStyle = vg
        ctx.fillRect(0, 0, self.view_w, self.view_h)

    def _sample_map_points(self, radius: float, map_type: str) -> list[Vec2]:
        if map_type == MAP_DIAMOND:
            r = radius * 0.84
            return [Vec2(r, 0), Vec2(0, r), Vec2(-r, 0), Vec2(0, -r)]
        if map_type == MAP_CROSS:
            w = radius * 0.34
            r = radius
            return [
                Vec2(w, w), Vec2(r, w), Vec2(r, -w), Vec2(w, -w),
                Vec2(w, -r), Vec2(-w, -r), Vec2(-w, -w), Vec2(-r, -w),
                Vec2(-r, w), Vec2(-w, w), Vec2(-w, r), Vec2(w, r),
            ]
        segments = 40
        return [Vec2(math.cos((i / segments) * TAU) * radius, math.sin((i / segments) * TAU) * radius) for i in range(segments)]

    def _trace_polygon(self, points: list[tuple[float, float]]) -> None:
        ctx = self.ctx
        if not points:
            return
        ctx.beginPath()
        ctx.moveTo(points[0][0], points[0][1])
        for x, y in points[1:]:
            ctx.lineTo(x, y)
        ctx.closePath()

    def _draw_arena(self, shake: Vec2, combat_intensity: float, preview_only: bool = False) -> None:
        ctx = self.ctx
        map_type = self.state.map_type if self.state else self.settings["map_type"]
        outer = self._sample_map_points(config.ROOM_RADIUS, map_type)
        outer_screen = [to_iso(point, shake) for point in outer]
        t = self.background_t
        ci = max(0.0, min(1.0, combat_intensity))

        ctx.save()
        # ── Floor fill — rich dark gradient ──
        self._trace_polygon(outer_screen)
        floor_grad = ctx.createLinearGradient(self.view_w * 0.2, self.view_h * 0.15, self.view_w * 0.8, self.view_h * 0.85)
        floor_grad.addColorStop(0, f"rgba({28 + int(20 * ci)}, {42 + int(8 * ci)}, {62}, 0.97)")
        floor_grad.addColorStop(0.5, f"rgba({18 + int(12 * ci)}, {28 + int(6 * ci)}, {44}, 0.97)")
        floor_grad.addColorStop(1, f"rgba({12 + int(22 * ci)}, {20}, {30 - int(4 * ci)}, 0.97)")
        ctx.fillStyle = floor_grad
        ctx.fill()

        # ── Center energy glow ──
        center_x, center_y = to_iso(Vec2(0, 0), shake)
        glow_r = config.ROOM_RADIUS * 0.4
        glow_pulse = 0.5 + 0.5 * math.sin(t * 0.8)
        glow_alpha = (0.04 + 0.03 * glow_pulse) * (1.0 + ci * 0.8)
        cg = ctx.createRadialGradient(center_x, center_y, 0, center_x, center_y, glow_r)
        cg.addColorStop(0, f"rgba({60 + int(40 * ci)}, {100 + int(30 * ci)}, {180}, {glow_alpha:.3f})")
        cg.addColorStop(1, "rgba(0,0,0,0)")
        ctx.fillStyle = cg
        ctx.fillRect(center_x - glow_r, center_y - glow_r, glow_r * 2, glow_r * 2)

        # ── Donut hole ──
        if map_type == MAP_DONUT:
            inner = self._sample_map_points(config.ROOM_RADIUS * 0.4, MAP_CIRCLE)
            inner_screen = [to_iso(point, shake) for point in inner]
            self._trace_polygon(inner_screen)
            ctx.fillStyle = "rgba(3, 6, 14, 0.92)"
            ctx.fill()

        # ── Border — pulsing glow ──
        border_pulse = 0.5 + 0.5 * math.sin(t * 1.5)
        border_alpha = 0.4 + 0.25 * border_pulse + ci * 0.2
        ctx.strokeStyle = f"rgba({140 + int(80 * ci)}, {200 + int(30 * ci)}, {255}, {border_alpha:.3f})"
        ctx.lineWidth = 2.5
        self._trace_polygon(outer_screen)
        ctx.stroke()
        # Outer glow layer
        ctx.strokeStyle = f"rgba({100 + int(60 * ci)}, {170}, {240}, {border_alpha * 0.3:.3f})"
        ctx.lineWidth = 6
        self._trace_polygon(outer_screen)
        ctx.stroke()

        # ── Grid lines — subtle pulsing ──
        step = max(58, int(config.ROOM_RADIUS * 0.14))
        grid_alpha = 0.12 + 0.08 * math.sin(t * 0.6) + ci * 0.06
        ctx.strokeStyle = f"rgba(90, 140, 200, {grid_alpha:.3f})"
        ctx.lineWidth = 1
        ctx.beginPath()
        for line_pos in range(-int(config.ROOM_RADIUS), int(config.ROOM_RADIUS) + step, step):
            a = Vec2(line_pos, -config.ROOM_RADIUS)
            b = Vec2(line_pos, config.ROOM_RADIUS)
            ax, ay = to_iso(a, shake)
            bx, by = to_iso(b, shake)
            ctx.moveTo(ax, ay)
            ctx.lineTo(bx, by)
            a = Vec2(-config.ROOM_RADIUS, line_pos)
            b = Vec2(config.ROOM_RADIUS, line_pos)
            ax, ay = to_iso(a, shake)
            bx, by = to_iso(b, shake)
            ctx.moveTo(ax, ay)
            ctx.lineTo(bx, by)
        ctx.stroke()

        if preview_only:
            for idx in range(5):
                angle = t * 0.4 + idx * 1.26
                radius = config.ROOM_RADIUS * (0.24 + idx * 0.08)
                world = Vec2(math.cos(angle) * radius, math.sin(angle) * radius * 0.8)
                sx, sy = to_iso(world, shake)
                self._draw_glow_circle(sx, sy - 8, 11 + idx, (120 + idx * 18, 180, 255), 0.18)

        # ── Pulsing concentric rings ──
        for ri, (r_base, r_speed, r_phase) in enumerate([(200, 0.8, 0.0), (280, 0.6, 1.5)]):
            ring_r = r_base + 8.0 * math.sin(t * r_speed + r_phase)
            ring_alpha = (0.05 + 0.04 * (0.5 + 0.5 * math.sin(t * (1.1 + ri * 0.3)))) * (1.0 + ci * 0.4)
            ring_screen_r = ring_r * 0.72
            ctx.strokeStyle = f"rgba({120 + ri * 20}, {180 + ri * 10}, {245}, {ring_alpha:.3f})"
            ctx.lineWidth = 1.5 + ri * 0.5
            ctx.beginPath()
            ctx.ellipse(center_x, center_y, ring_screen_r, ring_screen_r * 0.56, 0, 0, TAU)
            ctx.stroke()

        ctx.restore()

    def _draw_glow_circle(self, x: float, y: float, radius: float, color: tuple[int, int, int], alpha: float) -> None:
        """Cheap glow: two-layer semi-transparent filled circle for soft falloff."""
        ctx = self.ctx
        # Outer soft layer
        ctx.fillStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, {alpha * 0.25:.3f})"
        ctx.beginPath()
        ctx.arc(x, y, radius * 2.0, 0, TAU)
        ctx.fill()
        # Inner brighter layer
        ctx.fillStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, {alpha * 0.55:.3f})"
        ctx.beginPath()
        ctx.arc(x, y, radius * 1.2, 0, TAU)
        ctx.fill()

    def _draw_world(self, shake: Vec2) -> None:
        if not self.state or not self.player:
            return
        for obstacle in getattr(self.state, "obstacles", []):
            self._draw_obstacle(obstacle, shake)
        for powerup in self.state.powerups:
            self._draw_powerup(powerup, shake)
        for trap in getattr(self.state, "traps", []):
            self._draw_trap(trap, shake)
        for beam in getattr(self.state, "lasers", []):
            self._draw_beam(beam, shake)
        for thunder in getattr(self.state, "thunders", []):
            self._draw_beam(thunder, shake)
        for projectile in self.state.projectiles:
            self._draw_projectile(projectile, shake)
        enemies_sorted = sorted(self.state.enemies, key=lambda enemy_obj: enemy_obj.pos.x + enemy_obj.pos.y)
        for enemy_obj in enemies_sorted:
            self._draw_enemy(enemy_obj, shake)
        self._draw_player(shake)
        # ── Render particles on top of all world entities ──
        self.particles.render(self.ctx, shake, to_iso)

    def _draw_obstacle(self, obstacle, shake: Vec2) -> None:
        sx, sy = to_iso(obstacle.pos, shake)
        rx = max(12.0, obstacle.radius)
        ry = max(8.0, obstacle.radius * 0.52)
        ctx = self.ctx
        ctx.fillStyle = "rgba(12, 18, 28, 0.5)"
        ctx.beginPath()
        ctx.ellipse(sx, sy + 12, rx * 1.05, ry * 0.9, 0, 0, TAU)
        ctx.fill()
        color = {"pillar": (120, 160, 200), "crystal": (148, 200, 255), "crate": (170, 140, 110)}.get(obstacle.kind, (130, 160, 185))
        ctx.fillStyle = f"rgb({color[0]}, {color[1]}, {color[2]})"
        ctx.beginPath()
        ctx.ellipse(sx, sy - 6, rx, ry, 0, 0, TAU)
        ctx.fill()
        ctx.strokeStyle = "rgba(255,255,255,0.18)"
        ctx.lineWidth = 1.5
        ctx.stroke()

    def _draw_powerup(self, powerup, shake: Vec2) -> None:
        color = POWERUP_COLORS.get(getattr(powerup, "kind", ""), (220, 220, 220))
        sx, sy = to_iso(powerup.pos, shake)
        t = self.background_t
        seed = getattr(powerup, "id", powerup.pos.x)
        pulse = 1.0 + 0.15 * math.sin(t * 4.0 + seed * 0.02)
        float_y = 6.0 * math.sin(t * 3.0 + seed)
        cy = sy - 14 + float_y
        
        ctx = self.ctx

        # Ground shadow
        shadow_w = 14 * pulse
        shadow_h = 6 * pulse
        ctx.fillStyle = "rgba(4, 8, 16, 0.45)"
        ctx.beginPath()
        ctx.ellipse(sx, sy, shadow_w, shadow_h, 0, 0, TAU)
        ctx.fill()

        # Deep glow
        self._draw_glow_circle(sx, cy, 16 * pulse, color, 0.3)
        self._draw_glow_circle(sx, cy, 30 * pulse, color, 0.12)

        # Sci-Fi Orb Core
        core_r = 7.5 * pulse
        ctx.fillStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, 0.95)"
        ctx.beginPath()
        ctx.arc(sx, cy, core_r, 0, TAU)
        ctx.fill()
        # Brilliant center
        ctx.fillStyle = "rgba(255, 255, 255, 0.8)"
        ctx.beginPath()
        ctx.arc(sx, cy, core_r * 0.4, 0, TAU)
        ctx.fill()

        # Orbiting Wireframe Halos
        for i in range(2):
            ring_scale = 14.0 * pulse + (i * 5.0)
            tilt = 0.5 + 0.4 * math.sin(t * (2.0 + i) + seed)
            rot = t * (3.5 - i * 1.5) + seed * 1.2
            
            ctx.save()
            ctx.translate(sx, cy)
            ctx.rotate(rot)
            
            ctx.strokeStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, {0.6 + 0.3 * math.cos(t * 5.0):.3f})"
            ctx.lineWidth = 2.0 - i * 0.5
            ctx.beginPath()
            ctx.ellipse(0, 0, ring_scale, ring_scale * tilt, 0, 0, TAU)
            ctx.stroke()
            
            # Orbiting node on the ring
            node_x = math.cos(t * (5.0 + i) + seed) * ring_scale
            node_y = math.sin(t * (5.0 + i) + seed) * (ring_scale * tilt)
            ctx.fillStyle = "rgba(255, 255, 255, 0.9)"
            ctx.beginPath()
            ctx.arc(node_x, node_y, 2.5, 0, TAU)
            ctx.fill()
            
            ctx.restore()

    def _draw_trap(self, trap, shake: Vec2) -> None:
        sx, sy = to_iso(trap.pos, shake)
        ctx = self.ctx
        armed = trap.t >= trap.armed_delay
        kind = getattr(trap, "kind", "spike")
        tr = float(trap.radius)

        # Slam/womb warn — large expanding AoE circle
        if kind in ("slam", "slam_warn", "womb_warn", "womb_pulse"):
            pulse = 0.6 + 0.4 * math.sin(trap.t * 16.0)
            base_alpha = 0.12 if kind.endswith("warn") else 0.22
            base_alpha += 0.18 * pulse
            self._draw_glow_circle(sx, sy - 8, tr, (255, 80, 80), base_alpha)
            ctx.strokeStyle = f"rgba(255, 255, 255, {0.4 + 0.35 * pulse:.3f})"
            ctx.lineWidth = 3
            ctx.beginPath()
            ctx.ellipse(sx, sy - 8, tr, tr * 0.56, 0, 0, TAU)
            ctx.stroke()
            return

        # Regular spike trap
        # Filled base glow
        base_alpha = 0.25 if armed else 0.1
        base_color = (220, 120, 60) if armed else (255, 220, 120)
        self._draw_glow_circle(sx, sy - 8, tr * 0.7, base_color, base_alpha)

        # Inner core
        core_alpha = 0.7 if armed else 0.35
        core_r = max(4, tr * 0.25)
        ctx.fillStyle = f"rgba(255, 220, 180, {core_alpha:.2f})"
        ctx.beginPath()
        ctx.arc(sx, sy - 8, core_r, 0, TAU)
        ctx.fill()

        # Outer ellipse outline
        ctx.strokeStyle = "rgba(255, 128, 92, 0.85)" if armed else "rgba(255, 220, 120, 0.4)"
        ctx.lineWidth = 2.2
        ctx.beginPath()
        ctx.ellipse(sx, sy - 8, tr, tr * 0.56, 0, 0, TAU)
        ctx.stroke()

        # Cross-hair spikes (only when armed)
        if armed:
            arm_len = tr * 0.75
            spike_alpha = 0.75 + 0.2 * math.sin(self.background_t * 12.0)
            ctx.strokeStyle = f"rgba(255, 210, 170, {spike_alpha:.3f})"
            ctx.lineWidth = 3
            # Horizontal
            ctx.beginPath()
            ctx.moveTo(sx - arm_len, sy - 8 - 2)
            ctx.lineTo(sx + arm_len, sy - 8 + 2)
            ctx.stroke()
            # Vertical
            ctx.beginPath()
            ctx.moveTo(sx - 2, sy - 8 - arm_len * 0.56)
            ctx.lineTo(sx + 2, sy - 8 + arm_len * 0.56)
            ctx.stroke()

    def _draw_beam(self, beam, shake: Vec2) -> None:
        ax, ay = to_iso(beam.start, shake)
        bx, by = to_iso(beam.end, shake)
        ctx = self.ctx
        color = getattr(beam, "color", (255, 120, 255))
        thickness = max(2.0, float(getattr(beam, "thickness", 4.0)))
        warn_time = float(getattr(beam, "warn", 0.0))
        beam_t = float(getattr(beam, "t", 0.0))
        is_warning = warn_time > 0 and beam_t < warn_time

        if is_warning:
            # Warning telegraph: thin dashed faint line
            ctx.strokeStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, 0.18)"
            ctx.lineWidth = max(1.5, thickness * 0.28)
            ctx.setLineDash([8, 6])
            ctx.beginPath()
            ctx.moveTo(ax, ay)
            ctx.lineTo(bx, by)
            ctx.stroke()
            ctx.setLineDash([])
        else:
            # Active beam — outer glow layer
            flicker = 0.7 + 0.3 * math.sin(beam_t * 40.0)
            outer_alpha = (0.65 if getattr(beam, "owner", "player") == "player" else 0.5) * flicker
            ctx.strokeStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, {outer_alpha:.3f})"
            ctx.lineWidth = thickness * 0.65
            ctx.beginPath()
            ctx.moveTo(ax, ay)
            ctx.lineTo(bx, by)
            ctx.stroke()

            # Inner white-hot core
            core_flicker = 0.6 + 0.4 * math.sin(beam_t * 55.0)
            core_alpha = 0.55 * core_flicker
            core_w = max(1.5, thickness * 0.22)
            ctx.strokeStyle = f"rgba(255, 255, 255, {core_alpha:.3f})"
            ctx.lineWidth = core_w
            ctx.beginPath()
            ctx.moveTo(ax, ay)
            ctx.lineTo(bx, by)
            ctx.stroke()

    def _draw_projectile(self, projectile, shake: Vec2) -> None:
        sx, sy = to_iso(projectile.pos, shake)
        ptype = str(getattr(projectile, "projectile_type", "bullet"))
        is_enemy = str(getattr(projectile, "owner", "player")) == "enemy"
        ctx = self.ctx
        py = sy - 10

        palette = {
            "bullet": (255, 242, 196),
            "spread": (255, 200, 108),
            "missile": (255, 132, 132),
            "plasma": (175, 130, 255),
            "bomb": (255, 152, 88),
        }
        if is_enemy:
            palette = {
                "bullet": (255, 110, 110),
                "spread": (255, 130, 100),
                "missile": (200, 80, 80),
                "plasma": (255, 100, 200),
                "bomb": (255, 152, 88),
            }
        color = palette.get(ptype, (240, 240, 240))
        radius = max(3.0, self._projectile_radius(projectile) * 0.72)

        vel = getattr(projectile, "vel", None)
        # Ribbons via History
        history = getattr(projectile, "history", [])
        if len(history) > 1:
            trail_alpha = 0.35 if is_enemy else 0.55
            ctx.strokeStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, {trail_alpha:.2f})"
            ctx.lineWidth = max(1.5, radius * 0.8)
            ctx.lineJoin = "round"
            ctx.lineCap = "round"
            ctx.beginPath()
            hsx, hsy = to_iso(history[0], shake)
            ctx.moveTo(hsx, hsy - 10)
            for point in history[1:]:
                hx, hy = to_iso(point, shake)
                ctx.lineTo(hx, hy - 10)
            ctx.lineTo(sx, py)
            ctx.stroke()
        elif ptype in ("missile", "bomb", "plasma") and vel:
            # Fallback streak
            speed = math.sqrt(vel.x * vel.x + vel.y * vel.y)
            if speed > 1e-6:
                vdx, vdy = vel.x / speed, vel.y / speed
                trail_len = 8 + min(16.0, speed * 0.03)
                trail_alpha = 0.32 if is_enemy else 0.42
                ctx.strokeStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, {trail_alpha:.2f})"
                ctx.lineWidth = max(1.5, radius * 0.65)
                ctx.beginPath()
                ctx.moveTo(sx, py)
                ctx.lineTo(sx - vdx * trail_len, py - vdy * trail_len * 0.65)
                ctx.stroke()        # Bomb: dark casing ring + orange core
        if ptype == "bomb":
            ctx.fillStyle = f"rgba(120, 70, 45, 0.85)"
            ctx.beginPath()
            ctx.arc(sx, py, radius * 1.3, 0, TAU)
            ctx.fill()
            ctx.fillStyle = f"rgb({color[0]}, {color[1]}, {color[2]})"
            ctx.beginPath()
            ctx.arc(sx, py, radius * 0.7, 0, TAU)
            ctx.fill()
            return

        # Plasma: pulsing outer ring
        if ptype == "plasma":
            pulse = 0.7 + 0.3 * math.sin(self.background_t * 10.0 + projectile.pos.x * 0.1)
            ctx.strokeStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, {0.35 * pulse:.3f})"
            ctx.lineWidth = 1.5
            ctx.beginPath()
            ctx.arc(sx, py, radius * 1.6, 0, TAU)
            ctx.stroke()

        # Outer Soft Glow
        glow_alpha = 0.25 if is_enemy else 0.45
        self._draw_glow_circle(sx, py, radius * 1.8, color, glow_alpha)

        # Main body
        ctx.fillStyle = f"rgb({color[0]}, {color[1]}, {color[2]})"
        ctx.beginPath()
        ctx.arc(sx, py, radius, 0, TAU)
        ctx.fill()

        # White-hot flare
        flare_r = max(1.5, radius * 0.45)
        ctx.fillStyle = f"rgba(255, 255, 255, {0.5 if is_enemy else 0.75})"
        ctx.beginPath()
        ctx.arc(sx, py, flare_r, 0, TAU)
        ctx.fill()

    def _draw_enemy(self, enemy_obj, shake: Vec2) -> None:
        sx, sy = to_iso(enemy_obj.pos, shake)
        name = getattr(enemy_obj, "_behavior_name", enemy_behavior_name(enemy_obj))
        color = ENEMY_COLORS.get(name, (220, 220, 220))
        radius = getattr(enemy_obj, "_radius", self._enemy_radius(enemy_obj))
        boss = name.startswith("boss_")
        rx = max(10.0, radius * 0.95)
        ry = max(8.0, radius * 0.58)
        ctx = self.ctx
        bob = math.sin(enemy_obj.t * 6.0) * 1.5

        if boss:
            sy -= 26
        
        ctx.fillStyle = "rgba(10, 12, 18, 0.5)"
        ctx.beginPath()
        ctx.ellipse(sx, sy + 10 + (26 if boss else 0), rx * 0.95, ry * 0.74, 0, 0, TAU)
        ctx.fill()



        ctx.fillStyle = f"rgb({color[0]}, {color[1]}, {color[2]})"
        ctx.beginPath()
        ctx.ellipse(sx, sy - 14 + bob, rx, ry, 0, 0, TAU)
        ctx.fill()
        
        ctx.lineWidth = 1.6
        if name == "bomber":
            exploding = bool(getattr(enemy_obj, "ai", {}).get("bomber_exploding", False))
            pulse = 0.5 + 0.5 * math.sin(enemy_obj.t * 30) if exploding else 0
            fuse_speed = 18.0 if exploding else 4.0
            
            ctx.fillStyle = "rgba(255, 100, 50, 0.9)" if exploding else "rgba(255, 160, 50, 0.8)"
            ctx.beginPath()
            ctx.arc(sx, sy + bob - 14, 8 + 4 * pulse, 0, TAU)
            ctx.fill()
            
            fr = 16
            fx = sx + math.cos(enemy_obj.t * fuse_speed) * fr
            fy = sy + bob - 14 + math.sin(enemy_obj.t * fuse_speed) * fr
            self._draw_glow_circle(fx, fy, 6, (255, 200, 50), 0.6 + 0.4 * math.sin(enemy_obj.t * 12.0))
            
        elif name == "engineer":
            gear_r = 17 + 1.5 * math.sin(enemy_obj.t * 5.0)
            ctx.strokeStyle = f"rgba(180, 200, 220, {0.2 + 0.2 * math.sin(enemy_obj.t * 3.0)})"
            ctx.beginPath()
            ctx.arc(sx - 12, sy + 2 + bob - 14, gear_r, 0, TAU)
            ctx.stroke()
            
            ctx.fillStyle = "rgba(100, 150, 180, 0.8)"
            ctx.fillRect(sx - 16, sy + bob - 16, 8, 12)
            ctx.fillStyle = "rgba(200, 200, 200, 0.9)"
            ctx.fillRect(sx + 10, sy + bob - 12, 6, 2)
            
        elif name == "egg_sac":
            pulse = 0.8 + 0.2 * math.sin(enemy_obj.t * 8.0)
            if getattr(enemy_obj, "ai", {}).get("hatch_timer", 0) < 1.0:
                pulse = 0.8 + 0.3 * math.sin(enemy_obj.t * 18.0)
            
            ctx.fillStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, 0.8)"
            ctx.beginPath()
            ctx.arc(sx, sy + bob - 14, 15 * pulse, 0, TAU)
            ctx.fill()
            
            ctx.fillStyle = "rgba(255, 50, 50, 0.9)"
            ctx.beginPath()
            ctx.arc(sx, sy + bob - 14, 6 * pulse + 2 * math.sin(enemy_obj.t * 12.0), 0, TAU)
            ctx.fill()

        elif name == "tank":
            ctx.fillStyle = "rgba(40, 50, 40, 0.9)"
            ctx.beginPath()
            ctx.ellipse(sx - 10, sy + bob - 12, 6, 12, 0, 0, TAU)
            ctx.ellipse(sx + 10, sy + bob - 12, 6, 12, 0, 0, TAU)
            ctx.fill()
            
            ctx.fillStyle = f"rgba({max(0, color[0]-40)}, {max(0, color[1]-40)}, {max(0, color[2]-40)}, 0.9)"
            ctx.beginPath()
            ctx.ellipse(sx, sy + bob - 16, 14, 10, 0, 0, TAU)
            ctx.fill()
            
            ctx.fillStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, 0.95)"
            ctx.beginPath()
            ctx.arc(sx, sy + bob - 16, 6, 0, TAU)
            ctx.fill()
            ctx.strokeStyle = "rgba(200, 255, 200, 0.7)"
            ctx.lineWidth = 4
            ctx.beginPath()
            ctx.moveTo(sx, sy + bob - 16)
            ctx.lineTo(sx, sy + bob - 28)
            ctx.stroke()
            
            shield_r = 24 + 1.5 * math.sin(enemy_obj.t * 3.0)
            ctx.strokeStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, {0.2 + 0.2 * math.cos(enemy_obj.t * 2.5):.3f})"
            ctx.lineWidth = 2.5
            ctx.beginPath()
            ctx.ellipse(sx, sy + bob * 0.4 - 14, shield_r, shield_r * 0.6, 0, 0, TAU)
            ctx.stroke()
            ctx.fillStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, {0.05 + 0.05 * math.cos(enemy_obj.t * 2.5):.3f})"
            ctx.fill()
            
        elif name == "ranged":
            sr = 20
            sa = enemy_obj.t * 1.2
            cx = sx + 16
            cy = sy + bob - 14
            
            # Articulated turret
            ctx.fillStyle = f"rgba({max(0, color[0]-30)}, {max(0, color[1]-30)}, {max(0, color[2]-30)}, 0.95)"
            ctx.beginPath()
            ctx.ellipse(cx - 10, cy, 14, 6, 0, 0, TAU)
            ctx.fill()
            
            # Turret ring
            ctx.strokeStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, 0.8)"
            ctx.lineWidth = 2.5
            ctx.beginPath()
            ctx.arc(cx, cy, 6, 0, TAU)
            ctx.stroke()
            
            # Rotating crosshairs
            ctx.strokeStyle = f"rgba(255, 100, 100, {0.25 + 0.15 * math.sin(enemy_obj.t * 3.0)})"
            ctx.lineWidth = 1.5
            ctx.beginPath()
            ctx.moveTo(cx - math.cos(sa) * sr, cy - math.sin(sa) * sr * 0.5)
            ctx.lineTo(cx + math.cos(sa) * sr, cy + math.sin(sa) * sr * 0.5)
            ctx.moveTo(cx + math.sin(sa) * sr, cy - math.cos(sa) * sr * 0.5)
            ctx.lineTo(cx - math.sin(sa) * sr, cy + math.cos(sa) * sr * 0.5)
            ctx.stroke()

        elif name == "charger":
            ctx.fillStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, 0.85)"
            ctx.beginPath()
            ctx.moveTo(sx, sy + bob - 28)
            ctx.lineTo(sx + 16, sy + bob)
            ctx.lineTo(sx + 6, sy + bob - 6)
            ctx.lineTo(sx, sy + bob - 2)
            ctx.lineTo(sx - 6, sy + bob - 6)
            ctx.lineTo(sx - 16, sy + bob)
            ctx.closePath()
            ctx.fill()
            
            core_pulse = 0.6 + 0.4 * math.sin(enemy_obj.t * 25.0)
            self._draw_glow_circle(sx, sy + bob - 12, 6, (255, 255, 255), core_pulse)
            
            if getattr(enemy_obj, "ai", {}).get("charger_dashing", False):
                ctx.strokeStyle = "rgba(255, 200, 100, 0.6)"
                ctx.lineWidth = 3
                ctx.beginPath()
                ctx.moveTo(sx - 4, sy + bob - 2)
                ctx.lineTo(sx - 10, sy + bob + 16)
                ctx.stroke()
                ctx.beginPath()
                ctx.moveTo(sx + 4, sy + bob - 2)
                ctx.lineTo(sx + 10, sy + bob + 16)
                ctx.stroke()

        elif name == "flyer":
            flap = 4 + 6 * math.sin(enemy_obj.t * 12.0)
            ctx.fillStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, 0.9)"
            ctx.beginPath()
            ctx.ellipse(sx, sy + bob - 14, 4, 12, 0, 0, TAU)
            ctx.fill()
            
            ctx.fillStyle = f"rgba({max(0, color[0]-20)}, {max(0, color[1]-20)}, {max(0, color[2]-20)}, 0.85)"
            ctx.beginPath()
            ctx.moveTo(sx, sy + bob - 10)
            ctx.lineTo(sx + 24, sy + bob + flap - 14)
            ctx.lineTo(sx + 4, sy + bob - 20)
            ctx.fill()
            ctx.beginPath()
            ctx.moveTo(sx, sy + bob - 10)
            ctx.lineTo(sx - 24, sy + bob + flap - 14)
            ctx.lineTo(sx - 4, sy + bob - 20)
            ctx.fill()
            
            # Jet trails
            jet_pulse = 0.5 + 0.5 * math.sin(enemy_obj.t * 15.0)
            ctx.strokeStyle = f"rgba(100, 200, 255, {0.4 * jet_pulse})"
            ctx.lineWidth = 2.5
            ctx.beginPath()
            ctx.moveTo(sx - 2, sy + bob - 4)
            ctx.lineTo(sx - 6, sy + bob + 8 + 4 * jet_pulse)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(sx + 2, sy + bob - 4)
            ctx.lineTo(sx + 6, sy + bob + 8 + 4 * jet_pulse)
            ctx.stroke()
            
        elif name == "spitter":
            ctx.fillStyle = "rgba(100, 200, 100, 0.8)"
            ctx.beginPath()
            ctx.arc(sx - 9, sy + 2 + bob - 14, 5, 0, TAU)
            ctx.fill()
            ctx.beginPath()
            ctx.arc(sx + 8, sy + 4 + bob - 14, 5, 0, TAU)
            ctx.fill()
            
            acid_r = 14 + 3 * math.sin(enemy_obj.t * 4.0)
            self._draw_glow_circle(sx, sy + bob - 14, acid_r, (100, 255, 100), 0.1 + 0.1 * math.sin(enemy_obj.t * 5.0))

        elif name == "swarm":
            r = 8
            dot_color = (255, 100, 255)
            for offset in (0, 2.1, 4.2):
                dx = sx + math.cos(enemy_obj.t * 6.0 + offset) * r
                dy = sy + bob - 14 + math.sin(enemy_obj.t * 6.0 + offset) * r
                ctx.fillStyle = f"rgb({dot_color[0]}, {dot_color[1]}, {dot_color[2]})"
                ctx.beginPath()
                ctx.arc(dx, dy, 3, 0, TAU)
                ctx.fill()
            
            jitter = math.sin(enemy_obj.t * 20.0) * 3.0
            ctx.strokeStyle = f"rgba(255, 150, 255, {0.3 + 0.2 * math.sin(enemy_obj.t * 14.0)})"
            ctx.lineWidth = 1.5
            ctx.beginPath()
            ctx.moveTo(sx - 3, sy + bob + 8 - 14)
            ctx.lineTo(sx - 5 + jitter, sy + bob + 15 - 14)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(sx + 3, sy + bob + 8 - 14)
            ctx.lineTo(sx + 5 - jitter, sy + bob + 15 - 14)
            ctx.stroke()

        elif name == "chaser":
            aura_r = 16 + 4 * math.sin(enemy_obj.t * 3.5)
            ctx.strokeStyle = f"rgba(255, 50, 50, {0.15 + 0.15 * math.sin(enemy_obj.t * 2.5)})"
            ctx.lineWidth = 2
            ctx.beginPath()
            ctx.arc(sx, sy + bob - 14, aura_r, 0, TAU)
            ctx.stroke()
            
            t_rot = enemy_obj.t * 1.8
            ctx.fillStyle = "rgba(200, 50, 50, 0.9)"
            for i in range(3):
                a = t_rot + i * (math.tau / 3)
                tip_x = sx + math.cos(a) * 18
                tip_y = sy + bob - 14 + math.sin(a) * 18
                b1 = a + 0.35
                b2 = a - 0.35
                ctx.beginPath()
                ctx.moveTo(tip_x, tip_y)
                ctx.lineTo(sx + math.cos(b1) * 10, sy + bob - 14 + math.sin(b1) * 10)
                ctx.lineTo(sx + math.cos(b2) * 10, sy + bob - 14 + math.sin(b2) * 10)
                ctx.fill()
        
        elif boss:
            # Crown ring (all bosses)
            ctx.strokeStyle = f"rgba(255, 200, 50, {0.5 + 0.3 * math.sin(enemy_obj.t * 4.0)})"
            ctx.lineWidth = 3
            crown_r = 24 + 2.0 * (0.5 + 0.5 * math.sin(enemy_obj.t * 4.0))
            ctx.beginPath()
            ctx.ellipse(sx, sy + bob - 14, crown_r, crown_r * 0.5, 0, 0, TAU)
            ctx.stroke()

            # Dark armor ring
            ctx.strokeStyle = "rgba(20, 25, 40, 0.7)"
            ctx.lineWidth = 5
            ctx.beginPath()
            ctx.ellipse(sx, sy + bob - 14, rx * 1.15, ry * 1.15, 0, 0, TAU)
            ctx.stroke()

            # Per-boss signature
            if name == "boss_thunder":
                # Zigzag lightning bolt
                ctx.strokeStyle = f"rgba(200, 230, 255, {0.6 + 0.3 * math.sin(enemy_obj.t * 8.0)})"
                ctx.lineWidth = 3
                ctx.beginPath()
                ctx.moveTo(sx - 10, sy + 20 + bob - 14)
                ctx.lineTo(sx + 2, sy + 14 + bob - 14)
                ctx.lineTo(sx - 4, sy + 10 + bob - 14)
                ctx.lineTo(sx + 10, sy + 4 + bob - 14)
                ctx.stroke()
            elif name == "boss_laser":
                # Eye + iris tracking
                ex, ey = sx + 6, sy + 8 + bob - 14
                ctx.fillStyle = "rgba(255, 255, 255, 0.8)"
                ctx.beginPath()
                ctx.arc(ex, ey, 6, 0, TAU)
                ctx.fill()
                iris_off = 2.0 * math.sin(enemy_obj.t * 9.0)
                ctx.fillStyle = "rgba(255, 120, 255, 0.85)"
                ctx.beginPath()
                ctx.arc(ex + iris_off, ey, 3, 0, TAU)
                ctx.fill()
            elif name == "boss_trapmaster":
                # Rotating gear arc
                gear_r = 26 + 1.5 * math.sin(enemy_obj.t * 3.2)
                gear_alpha = 0.35 + 0.2 * math.sin(enemy_obj.t * 2.0)
                ctx.strokeStyle = f"rgba(255, 210, 120, {gear_alpha:.3f})"
                ctx.lineWidth = 4
                gear_start = enemy_obj.t * 1.5
                ctx.beginPath()
                ctx.arc(sx, sy + bob - 14, gear_r, gear_start, gear_start + 4.2)
                ctx.stroke()
            elif name == "boss_swarmqueen":
                # Orbiting orbs
                orb_r = 20
                for orb_i in range(3):
                    oa = enemy_obj.t * 2.2 + orb_i * 2.1
                    ox = sx + math.cos(oa) * orb_r
                    oy = sy + bob - 14 + math.sin(oa) * orb_r
                    ctx.fillStyle = "rgba(255, 255, 255, 0.35)"
                    ctx.beginPath()
                    ctx.arc(ox, oy, 5, 0, TAU)
                    ctx.fill()
            elif name == "boss_brute":
                # Horn triangle
                ctx.fillStyle = "rgba(255, 250, 240, 0.85)"
                ctx.beginPath()
                ctx.moveTo(sx, sy + bob - 14 + 26)
                ctx.lineTo(sx + 18, sy + bob - 14 + 16)
                ctx.lineTo(sx - 18, sy + bob - 14 + 16)
                ctx.closePath()
                ctx.fill()
                # Scar
                ctx.strokeStyle = "rgba(40, 10, 10, 0.7)"
                ctx.lineWidth = 4
                ctx.beginPath()
                ctx.moveTo(sx - 10, sy + bob - 14 + 2)
                ctx.lineTo(sx + 10, sy + bob - 14 - 6)
                ctx.stroke()
                # Charge telegraph circle
                b_state = getattr(enemy_obj, "ai", {}).get("brute_state", "")
                if b_state == "telegraph":
                    tele_pulse = 0.5 + 0.5 * math.sin(enemy_obj.t * 20.0)
                    ctx.strokeStyle = f"rgba(255, 100, 50, {0.3 + 0.4 * tele_pulse:.3f})"
                    ctx.lineWidth = 3
                    ctx.beginPath()
                    ctx.arc(sx, sy + bob - 14, 30 + 8 * tele_pulse, 0, TAU)
                    ctx.stroke()
            elif name == "boss_abyss_gaze":
                # Multiple pulsing eye rings
                for ei in range(2):
                    e_alpha = 0.25 + 0.2 * math.sin(enemy_obj.t * (4.0 + ei * 1.5))
                    e_r = 18 + ei * 8 + 2 * math.sin(enemy_obj.t * 3.0)
                    ctx.strokeStyle = f"rgba(190, 210, 255, {e_alpha:.3f})"
                    ctx.lineWidth = 2
                    ctx.beginPath()
                    ctx.arc(sx, sy + bob - 14, e_r, 0, TAU)
                    ctx.stroke()
            elif name == "boss_womb_core":
                # Pulsing veins
                for vi in range(3):
                    va = enemy_obj.t * 1.2 + vi * (TAU / 3)
                    vr = 16 + 4 * math.sin(enemy_obj.t * 5.0 + vi)
                    vx1 = sx + math.cos(va) * 4
                    vy1 = sy + bob - 14
                    vx2 = sx + math.cos(va) * vr
                    vy2 = sy + bob - 14 + math.sin(va) * vr
                    ctx.strokeStyle = f"rgba(160, 60, 80, {0.4 + 0.2 * math.sin(enemy_obj.t * 8.0 + vi):.3f})"
                    ctx.lineWidth = 2
                    ctx.beginPath()
                    ctx.moveTo(vx1, vy1)
                    ctx.lineTo(vx2, vy2)
                    ctx.stroke()

        ctx.strokeStyle = "rgba(255,255,255,0.16)"
        ctx.lineWidth = 1.6
        ctx.beginPath()
        ctx.ellipse(sx, sy - 14 + bob, rx, ry, 0, 0, TAU)
        ctx.stroke()

        if boss:
            max_hp = max(1, int(enemy_obj.ai.get("max_hp", enemy_obj.hp)))
            self._draw_entity_bar(sx - 28, sy - 44 + 26, 56, max(0.0, min(1.0, enemy_obj.hp / max_hp)), color)


    def _draw_player(self, shake: Vec2) -> None:
        if not self.player:
            return
        sx, sy = to_iso(self.player.pos, shake)
        ctx = self.ctx
        t = self.background_t
        aim_dir = (iso_to_world((self.mouse_screen.x, self.mouse_screen.y)) - self.player.pos).normalized()
        if aim_dir.length() <= 1e-6:
            aim_dir = Vec2(1.0, 0.0)
        angle = math.atan2(aim_dir.y, aim_dir.x)
        hull = (132, 224, 255) if self.player.invincibility_timer <= 0 else (255, 236, 160)
        bob = math.sin(t * 6.0) * 1.5
        cy = sy - 18 + bob

        # ── Shadow ──
        ctx.fillStyle = "rgba(8, 14, 22, 0.56)"
        ctx.beginPath()
        ctx.ellipse(sx, sy + 12, 18, 10, 0, 0, TAU)
        ctx.fill()

        # ── Shield ring ──
        if getattr(self.player, "shield", 0) > 0:
            pulse = 0.65 + 0.35 * math.sin(t * 6.5)
            shield_alpha = 0.25 + min(120, self.player.shield) * 0.003 * pulse
            ctx.strokeStyle = f"rgba(120, 220, 255, {shield_alpha:.3f})"
            ctx.lineWidth = 3
            ctx.beginPath()
            ctx.arc(sx, cy, 20 + 2 * pulse, 0, TAU)
            ctx.stroke()
            # Outer thin ring
            ctx.strokeStyle = f"rgba(255, 255, 255, {shield_alpha * 0.5:.3f})"
            ctx.lineWidth = 1.5
            ctx.beginPath()
            ctx.arc(sx, cy, 26 + 3 * pulse, 0, TAU)
            ctx.stroke()

        # ── Laser aura ring ──
        if self.state and self.state.time < getattr(self.player, "laser_until", 0.0):
            pulse = 0.6 + 0.4 * math.sin(t * 10.0)
            ctx.strokeStyle = f"rgba(255, 120, 255, {0.45 * pulse:.3f})"
            ctx.lineWidth = 2.5
            ctx.beginPath()
            ctx.arc(sx, cy, 22 + 3 * pulse, 0, TAU)
            ctx.stroke()

        # ── Outer glow ──
        self._draw_glow_circle(sx, cy, 20, hull, 0.15)
        self._draw_glow_circle(sx, cy, 28, (80, 120, 220), 0.06)

        # ── Thruster jets (dash) ──
        if getattr(self.player, "is_dashing", False):
            dash_pulse = 0.6 + 0.4 * math.sin(t * 40.0)
            jet_len = 20 + 12 * dash_pulse
            ctx.strokeStyle = f"rgba(130, 210, 255, {0.5 + 0.35 * dash_pulse:.3f})"
            ctx.lineWidth = 4
            ctx.beginPath()
            ctx.moveTo(sx - aim_dir.x * 9, cy - aim_dir.y * 4)
            ctx.lineTo(sx - aim_dir.x * jet_len, cy - aim_dir.y * (jet_len * 0.6))
            ctx.stroke()
            ctx.strokeStyle = f"rgba(200, 240, 255, {0.3 + 0.25 * dash_pulse:.3f})"
            ctx.lineWidth = 3
            ctx.beginPath()
            ctx.moveTo(sx - aim_dir.x * 5, cy - aim_dir.y * 7)
            ctx.lineTo(sx - aim_dir.x * (jet_len * 0.8), cy - aim_dir.y * (jet_len * 0.5))
            ctx.stroke()

        # ── Body diamond (main hull) ──
        aberration = self.flash > 0 or getattr(self.player, "is_dashing", False)
        passes = 3 if aberration else 1
        
        for p_idx in range(passes):
            ctx.save()
            if passes > 1:
                ctx.globalCompositeOperation = "lighter"
                off_x = (p_idx - 1) * 3.5
                off_y = (p_idx - 1) * -1.5
                ctx.translate(sx + off_x, cy + off_y)
                ctx.rotate(angle + math.pi * 0.25)
                color = f"rgba({255 if p_idx==0 else 0}, {255 if p_idx==1 else 0}, {255 if p_idx==2 else 0}, 0.85)"
                ctx.fillStyle = color
                ctx.beginPath()
                ctx.moveTo(0, -19); ctx.lineTo(13, 2); ctx.lineTo(0, 15); ctx.lineTo(-13, 2)
                ctx.closePath()
                ctx.fill()
            else:
                ctx.translate(sx, cy)
                ctx.rotate(angle + math.pi * 0.25)
        
                # Dark outline hull
                ctx.fillStyle = "rgba(10, 20, 35, 0.85)"
                ctx.beginPath()
                ctx.moveTo(0, -19); ctx.lineTo(13, 2); ctx.lineTo(0, 15); ctx.lineTo(-13, 2)
                ctx.closePath()
                ctx.fill()
        
                # Colored hull
                ctx.fillStyle = f"rgb({hull[0]}, {hull[1]}, {hull[2]})"
                ctx.beginPath()
                ctx.moveTo(0, -17); ctx.lineTo(11, 2); ctx.lineTo(0, 13); ctx.lineTo(-11, 2)
                ctx.closePath()
                ctx.fill()
        
                # Chest plate accent
                ctx.fillStyle = f"rgba({hull[0] - 30}, {hull[1] - 50}, {hull[2] - 30}, 0.7)"
                ctx.beginPath()
                ctx.moveTo(0, -10); ctx.lineTo(6, 0); ctx.lineTo(0, 8); ctx.lineTo(-6, 0)
                ctx.closePath()
                ctx.fill()
        
                # Core energy dot
                core_pulse = 0.7 + 0.3 * math.sin(t * 7.8)
                ctx.fillStyle = f"rgba(200, 245, 255, {0.6 * core_pulse:.3f})"
                ctx.beginPath()
                ctx.arc(0, 0, 4, 0, TAU)
                ctx.fill()
        
                # Highlight & Edge stroke
                ctx.fillStyle = "rgba(255, 255, 255, 0.22)"
                ctx.beginPath()
                ctx.arc(-3, 4, 4, 0, TAU)
                ctx.fill()
                ctx.strokeStyle = "rgba(255,255,255,0.28)"
                ctx.lineWidth = 1.5
                ctx.beginPath()
                ctx.moveTo(0, -17); ctx.lineTo(11, 2); ctx.lineTo(0, 13); ctx.lineTo(-11, 2)
                ctx.closePath()
                ctx.stroke()
            ctx.restore()

        # ── Gun barrel (world space, pointing at aim) ──
        gun_len = 18
        gx = sx + aim_dir.x * 8
        gy = cy + aim_dir.y * 4
        ctx.strokeStyle = "rgba(230, 230, 240, 0.75)"
        ctx.lineWidth = 3
        ctx.beginPath()
        ctx.moveTo(gx, gy)
        ctx.lineTo(gx + aim_dir.x * gun_len, gy + aim_dir.y * gun_len * 0.65)
        ctx.stroke()
        # Inner barrel highlight
        ctx.strokeStyle = "rgba(255, 255, 255, 0.6)"
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.moveTo(gx, gy)
        ctx.lineTo(gx + aim_dir.x * gun_len, gy + aim_dir.y * gun_len * 0.65)
        ctx.stroke()

        # ── Visor glow ──
        visor_pulse = 0.7 + 0.3 * math.sin(t * 5.4)
        ctx.fillStyle = f"rgba(238, 245, 255, {0.6 * visor_pulse:.3f})"
        vx = sx + aim_dir.x * 3
        vy = cy + aim_dir.y * 1.5 + 3
        ctx.fillRect(vx - 6, vy - 1.5, 12, 3)

        # ── Vortex swirl ring ──
        if self.state and self.state.time < getattr(self.player, "vortex_until", 0.0):
            vort_r = float(getattr(self.player, "vortex_radius", 100))
            vort_screen_r = vort_r * 0.72
            vort_pulse = 0.5 + 0.5 * math.sin(t * 4.0)
            ctx.strokeStyle = f"rgba(180, 140, 255, {0.2 + 0.15 * vort_pulse:.3f})"
            ctx.lineWidth = 2
            ctx.beginPath()
            ctx.arc(sx, cy, vort_screen_r, t * 2.0, t * 2.0 + 4.5)
            ctx.stroke()
            ctx.strokeStyle = f"rgba(220, 200, 255, {0.12 + 0.08 * vort_pulse:.3f})"
            ctx.lineWidth = 1.5
            ctx.beginPath()
            ctx.arc(sx, cy, vort_screen_r * 0.7, -t * 1.5, -t * 1.5 + 3.8)
            ctx.stroke()

    def _draw_entity_bar(self, x: float, y: float, width: float, ratio: float, color: tuple[int, int, int]) -> None:
        ctx = self.ctx
        # Background
        ctx.fillStyle = "rgba(6, 10, 18, 0.8)"
        ctx.fillRect(x, y, width, 8)
        # Fill gradient
        if ratio > 0:
            bar_g = ctx.createLinearGradient(x, y, x + width * ratio, y)
            bar_g.addColorStop(0, f"rgb({color[0]}, {color[1]}, {color[2]})")
            bar_g.addColorStop(1, f"rgba({min(255, color[0] + 40)}, {min(255, color[1] + 30)}, {min(255, color[2] + 20)}, 0.9)")
            ctx.fillStyle = bar_g
            ctx.fillRect(x, y, width * ratio, 8)
        # Border
        ctx.strokeStyle = "rgba(255, 255, 255, 0.08)"
        ctx.lineWidth = 1
        ctx.strokeRect(x, y, width, 8)

    def _draw_hud(self) -> None:
        if not self.state or not self.player:
            return
        ctx = self.ctx
        ctx.save()
        self._draw_panel(20, 20, 400, 148)

        # HP bar with gradient
        self._draw_bar(42, 50, 220, 14, self.player.hp / max(1, self.player.max_hp), (90, 230, 160), "HP")
        # Shield bar
        self._draw_bar(42, 80, 220, 14, max(0.0, min(1.0, self.player.shield / 120.0)), (90, 170, 255), "SHD")

        # Stats column
        ctx.fillStyle = "rgba(120, 200, 255, 0.6)"
        ctx.font = "700 12px Orbitron, sans-serif"
        ctx.fillText("WAVE", 288, 50)
        ctx.fillText("SCORE", 288, 78)
        ctx.fillText("COMBO", 288, 106)
        ctx.fillText("WEAPON", 288, 134)

        ctx.fillStyle = "rgba(240, 248, 255, 0.96)"
        ctx.font = "700 18px Rajdhani, sans-serif"
        ctx.fillText(f"{self.state.wave}", 348, 52)
        ctx.fillText(f"{self.score.score}", 348, 80)
        ctx.fillText(f"x{self.score.combo:.1f}", 348, 108)
        ctx.font = "600 16px Rajdhani, sans-serif"
        ctx.fillText(f"{self.player.current_weapon.name}", 348, 136)

        laser_left = max(0.0, self.player.laser_until - self.state.time)
        laser_txt = f"Laser {laser_left:.0f}s" if laser_left > 0 else ""
        vortex_left = max(0.0, self.player.vortex_until - self.state.time)
        vortex_txt = f"Vortex {vortex_left:.0f}s" if vortex_left > 0 else ""
        ultra_charges = int(getattr(self.player, "ultra_charges", 0))
        ultra_cd = max(0.0, float(getattr(self.player, "ultra_cd_until", 0.0)) - self.state.time)
        ultra_txt = ""
        if ultra_charges > 0:
            ultra_txt = f"Ultra {ultra_charges} [{self._ultra_variant_name()}]"
            if ultra_cd > 0:
                ultra_txt += f" {ultra_cd:.0f}s"
        dash_txt = format_dash_hud(self.player, self.state.time)
        temp_txt = format_temp_hud(self._active_temp_rewards)
        perm_txt = format_perm_hud(self._run_permanent_rewards)
        status_parts = [text for text in (dash_txt, laser_txt, vortex_txt, ultra_txt, temp_txt, perm_txt) if text]
        status = "  \u2502  ".join(status_parts) if status_parts else "LMB auto-fire  \u2502  Space dash  \u2502  Q or RMB ultra"

        ctx.fillStyle = "rgba(232, 240, 255, 0.88)"
        ctx.font = "600 15px Rajdhani, sans-serif"
        self._wrap_text(status, 24, self.view_h - 62, self.view_w - 48, 18)

        boss = next((enemy_obj for enemy_obj in self.state.enemies if enemy_behavior_name(enemy_obj).startswith("boss_")), None)
        if boss:
            boss_name = enemy_behavior_name(boss)[5:].replace("_", " ").title()
            max_hp = max(1, int(boss.ai.get("max_hp", boss.hp)))
            ratio = max(0.0, min(1.0, boss.hp / max_hp))
            width = min(self.view_w * 0.44, 520)
            x = (self.view_w - width) * 0.5
            y = 24
            # Dark background bar
            self._draw_panel(x - 8, y - 22, width + 16, 42)
            ctx.fillStyle = "rgba(18, 22, 30, 0.85)"
            ctx.fillRect(x, y, width, 12)
            # HP fill with gradient
            if ratio > 0:
                bar_grad = ctx.createLinearGradient(x, y, x + width * ratio, y)
                bar_grad.addColorStop(0, "rgba(255, 100, 100, 0.95)")
                bar_grad.addColorStop(1, "rgba(255, 160, 120, 0.85)")
                ctx.fillStyle = bar_grad
                ctx.fillRect(x, y, width * ratio, 12)
            ctx.fillStyle = "rgba(244, 248, 255, 0.95)"
            ctx.font = "700 13px Orbitron, sans-serif"
            ctx.textAlign = "center"
            ctx.fillText(f"BOSS  {boss_name}  \u2014  HP {boss.hp}", self.view_w * 0.5, y - 6)
            ctx.textAlign = "start"
        ctx.restore()

    def _draw_bar(self, x: float, y: float, width: float, height: float, ratio: float, color: tuple[int, int, int], label: str) -> None:
        ctx = self.ctx
        # Background
        ctx.fillStyle = "rgba(6, 10, 18, 0.78)"
        ctx.fillRect(x, y, width, height)
        # Fill with gradient
        fill_w = width * max(0.0, min(1.0, ratio))
        if fill_w > 0:
            bg = ctx.createLinearGradient(x, y, x + fill_w, y)
            bg.addColorStop(0, f"rgb({color[0]}, {color[1]}, {color[2]})")
            bg.addColorStop(1, f"rgba({min(255, color[0] + 50)}, {min(255, color[1] + 40)}, {min(255, color[2] + 30)}, 0.85)")
            ctx.fillStyle = bg
            ctx.fillRect(x, y, fill_w, height)
        # Border
        ctx.strokeStyle = "rgba(255, 255, 255, 0.06)"
        ctx.lineWidth = 1
        ctx.strokeRect(x, y, width, height)
        # Label
        ctx.fillStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, 0.7)"
        ctx.font = "700 11px Orbitron, sans-serif"
        ctx.fillText(label, x, y - 5)

    def _draw_wave_banner(self) -> None:
        if not self.state:
            return
        ctx = self.ctx
        t = self._wave_banner_t
        alpha = min(1.0, t)
        text = f"WAVE {self.state.wave}"
        is_boss_clear = self._last_cleared_wave and self._last_cleared_wave % 5 == 0
        if is_boss_clear:
            text = f"BOSS CLEAR  //  {text}"

        ctx.save()
        # Slide-in from top
        slide_offset = max(0.0, (1.0 - min(1.0, t * 3.0))) * -40.0
        ctx.globalAlpha = 0.18 + alpha * 0.72

        width = min(self.view_w * 0.38, 420)
        x = (self.view_w - width) * 0.5
        y = 100 + slide_offset

        # Background panel with gradient
        bg_grad = ctx.createLinearGradient(x, y, x + width, y)
        if is_boss_clear:
            bg_grad.addColorStop(0, "rgba(40, 18, 12, 0.85)")
            bg_grad.addColorStop(1, "rgba(12, 8, 20, 0.85)")
        else:
            bg_grad.addColorStop(0, "rgba(7, 11, 20, 0.82)")
            bg_grad.addColorStop(1, "rgba(10, 16, 28, 0.82)")
        ctx.fillStyle = bg_grad
        ctx.fillRect(x, y, width, 56)

        # Accent top line
        accent_color = "rgba(255, 200, 100, 0.75)" if is_boss_clear else "rgba(130, 200, 255, 0.55)"
        ctx.fillStyle = accent_color
        ctx.fillRect(x, y, width, 2)
        # Accent bottom line
        ctx.fillRect(x, y + 54, width, 2)

        # Side glow
        glow_alpha = 0.12 * alpha
        glow_color = (255, 200, 100) if is_boss_clear else (130, 185, 245)
        glow = ctx.createRadialGradient(self.view_w * 0.5, y + 28, 10, self.view_w * 0.5, y + 28, width * 0.6)
        glow.addColorStop(0, f"rgba({glow_color[0]}, {glow_color[1]}, {glow_color[2]}, {glow_alpha:.3f})")
        glow.addColorStop(1, "rgba(0,0,0,0)")
        ctx.fillStyle = glow
        ctx.fillRect(x - 40, y - 20, width + 80, 96)

        # Text
        ctx.fillStyle = "rgba(235, 242, 255, 0.98)" if not is_boss_clear else "rgba(255, 230, 180, 0.98)"
        ctx.font = "700 24px Orbitron, sans-serif"
        ctx.textAlign = "center"
        ctx.fillText(text, self.view_w * 0.5, y + 36)
        ctx.restore()
        ctx.textAlign = "start"

    def _draw_menu(self) -> None:
        ctx = self.ctx
        pw = min(self.view_w * 0.42, 480)
        ph = self.view_h - 72
        px = 36
        py = 36
        t = self.background_t

        self._draw_panel(px, py, pw, ph)

        # Title glow
        title_x = px + 40
        title_y = py + 72
        glow_pulse = 0.6 + 0.4 * math.sin(t * 1.5)
        glow = ctx.createRadialGradient(title_x + 90, title_y - 10, 10, title_x + 90, title_y - 10, 180)
        glow.addColorStop(0, f"rgba(100, 200, 255, {0.06 * glow_pulse:.3f})")
        glow.addColorStop(1, "rgba(0,0,0,0)")
        ctx.fillStyle = glow
        ctx.fillRect(px, py, pw, 120)

        # Title
        ctx.fillStyle = "rgba(240, 248, 255, 0.98)"
        ctx.font = "900 48px Orbitron, sans-serif"
        ctx.fillText("PLOUTO", title_x, title_y)

        # Subtitle
        ctx.fillStyle = "rgba(255, 211, 128, 0.85)"
        ctx.font = "600 16px Orbitron, sans-serif"
        ctx.fillText("STELLAR SURVIVAL", title_x, title_y + 26)

        # Accent line under title
        accent_alpha = 0.3 + 0.15 * math.sin(t * 2.0)
        ctx.strokeStyle = f"rgba(120, 210, 255, {accent_alpha:.3f})"
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.moveTo(title_x, title_y + 36)
        ctx.lineTo(title_x + 200, title_y + 36)
        ctx.stroke()

        # Description
        ctx.font = "500 17px Rajdhani, sans-serif"
        ctx.fillStyle = "rgba(180, 200, 220, 0.88)"
        self._wrap_text(
            "Fight through waves of enemies, collect devastating powerups, and face colossal bosses.",
            title_x, title_y + 62, pw - 80, 22
        )

        # Stats
        high_score = ScoreTracker(difficulty=self.settings["difficulty"]).get_high_score()
        stats_y = title_y + 126
        ctx.font = "700 15px Rajdhani, sans-serif"

        # High score with icon accent
        ctx.fillStyle = "rgba(255, 211, 128, 0.75)"
        ctx.fillText("\u2605", title_x, stats_y)
        ctx.fillStyle = "rgba(160, 200, 235, 0.9)"
        ctx.fillText(f"Best Score: {high_score}", title_x + 18, stats_y)

        ctx.fillStyle = "rgba(120, 200, 255, 0.5)"
        ctx.fillText("\u25C6", title_x, stats_y + 24)
        ctx.fillStyle = "rgba(160, 200, 235, 0.9)"
        ctx.fillText(f"Arena: {int(config.ROOM_RADIUS)}", title_x + 18, stats_y + 24)

        for button in self.menu_buttons:
            self._draw_button(button)

    def _draw_pause(self) -> None:
        pw = 380
        ph = 340
        px = self.view_w * 0.5 - pw * 0.5
        py = self.view_h * 0.5 - ph * 0.5
        self._draw_panel(px, py, pw, ph)
        ctx = self.ctx
        cx = self.view_w * 0.5

        ctx.textAlign = "center"
        ctx.fillStyle = "rgba(244, 247, 255, 0.98)"
        ctx.font = "700 34px Orbitron, sans-serif"
        ctx.fillText("PAUSED", cx, py + 60)

        ctx.strokeStyle = "rgba(120, 200, 255, 0.2)"
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.moveTo(cx - 80, py + 72)
        ctx.lineTo(cx + 80, py + 72)
        ctx.stroke()

        ctx.font = "600 18px Rajdhani, sans-serif"
        ctx.fillStyle = "rgba(192, 208, 228, 0.92)"
        ctx.fillText("Take a breath, then jump back in.", cx, py + 100)
        ctx.textAlign = "start"
        for button in self.pause_buttons:
            self._draw_button(button)

    def _draw_reward_panel(self) -> None:
        pw = min(1000, self.view_w - 80)
        ph = min(800, self.view_h - 80)
        px = self.view_w * 0.5 - pw * 0.5
        py = self.view_h * 0.5 - ph * 0.5
        
        # Dimming backdrop overlay
        ctx = self.ctx
        ctx.fillStyle = "rgba(4, 6, 12, 0.6)"
        ctx.fillRect(0, 0, self.view_w, self.view_h)
        
        self._draw_panel(px, py, pw, ph)
        
        # Top banner highlight
        banner_grad = ctx.createLinearGradient(px, py, px, py + 140)
        banner_grad.addColorStop(0, "rgba(80, 160, 255, 0.12)")
        banner_grad.addColorStop(1, "rgba(80, 160, 255, 0)")
        ctx.fillStyle = banner_grad
        ctx.fillRect(px, py, pw, 140)

        title = "TEMPORARY CARD" if self.reward_step == "temp" else "PERMANENT BOOST"
        title_color = "rgba(180, 220, 255, 0.98)" if self.reward_step == "temp" else "rgba(255, 210, 130, 0.98)"
        
        ctx.fillStyle = title_color
        ctx.font = "900 36px Orbitron, sans-serif"
        ctx.fillText(title, px + 50, py + 80)
        
        ctx.font = "600 20px Rajdhani, sans-serif"
        ctx.fillStyle = "rgba(180, 200, 220, 0.9)"
        ctx.fillText((self.reward_message or "CHOOSE AN UPGRADE").upper(), px + 50, py + 115)

        # Title underline
        ctx.strokeStyle = "rgba(120, 200, 255, 0.2)"
        ctx.lineWidth = 1.5
        ctx.beginPath()
        ctx.moveTo(px + 40, py + 130)
        ctx.lineTo(px + pw - 40, py + 130)
        ctx.stroke()

        for button in self.reward_buttons:
            self._draw_button(button, card_text=button.payload.get("desc", ""))

    def _draw_game_over(self) -> None:
        pw = 480
        ph = 420
        px = self.view_w * 0.5 - pw * 0.5
        py = self.view_h * 0.5 - ph * 0.5
        
        # Dimming backdrop overlay
        ctx = self.ctx
        ctx.fillStyle = "rgba(12, 4, 4, 0.75)"
        ctx.fillRect(0, 0, self.view_w, self.view_h)
        
        self._draw_panel(px, py, pw, ph)
        cx = self.view_w * 0.5

        # Top banner highlight
        banner_grad = ctx.createLinearGradient(px, py, px, py + 100)
        banner_grad.addColorStop(0, "rgba(255, 80, 80, 0.15)")
        banner_grad.addColorStop(1, "rgba(255, 80, 80, 0)")
        ctx.fillStyle = banner_grad
        ctx.fillRect(px, py, pw, 100)

        ctx.textAlign = "center"
        ctx.fillStyle = "rgba(255, 180, 160, 0.98)"
        ctx.font = "900 38px Orbitron, sans-serif"
        ctx.fillText("RUN COMPLETE", cx, py + 70)

        # Accent line
        ctx.strokeStyle = "rgba(255, 120, 100, 0.3)"
        ctx.lineWidth = 1.5
        ctx.beginPath()
        ctx.moveTo(cx - 120, py + 95)
        ctx.lineTo(cx + 120, py + 95)
        ctx.stroke()

        ctx.font = "700 22px Rajdhani, sans-serif"
        ctx.fillStyle = "rgba(208, 220, 238, 0.95)"
        ctx.fillText(f"Wave Reached:  {self.final_wave}", cx, py + 140)
        ctx.fillText(f"Final Score:  {self.final_score:,}", cx, py + 175)
        ctx.fillStyle = "rgba(180, 200, 220, 0.7)"
        ctx.fillText(f"High Score:  {self.high_score:,}", cx, py + 210)

        if self.is_new_high:
            ctx.fillStyle = "rgba(255, 216, 100, 1.0)"
            ctx.font = "800 24px Orbitron, sans-serif"
            pulse_y = 4 * math.sin(self.background_t * 6.0)
            ctx.fillText("\u2605  NEW HIGH SCORE  \u2605", cx, py + 260 + pulse_y)

        ctx.textAlign = "start"
        for button in self.game_over_buttons:
            self._draw_button(button)

    def _draw_guide(self) -> None:
        self._draw_panel(self.view_w * 0.5 - 280, self.view_h * 0.5 - 220, 560, 440)
        ctx = self.ctx
        ctx.fillStyle = "rgba(244, 247, 255, 0.98)"
        ctx.font = "700 30px Orbitron, sans-serif"
        ctx.fillText("HOW TO PLAY", self.view_w * 0.5 - 116, self.view_h * 0.5 - 164)
        ctx.font = "600 19px Rajdhani, sans-serif"
        ctx.fillStyle = "rgba(208, 220, 238, 0.95)"
        lines = [
            "Move: WASD or arrow keys",
            "Attack: Left click toggles auto-fire",
            "Dash: Space",
            "Ultra: Right click or Q after collecting Ultra charges",
            "Boss waves happen every 5 waves",
            "After each boss, pick a temporary card and a permanent boost",
            "Press Escape to close this screen",
        ]
        y = self.view_h * 0.5 - 104
        for line in lines:
            ctx.fillText(line, self.view_w * 0.5 - 188, y)
            y += 38

    def _draw_panel(self, x: float, y: float, width: float, height: float) -> None:
        ctx = self.ctx
        r = 16  # corner radius
        ctx.save()

        # Rounded rect path helper
        def _rrect():
            ctx.beginPath()
            ctx.moveTo(x + r, y)
            ctx.lineTo(x + width - r, y)
            ctx.arcTo(x + width, y, x + width, y + r, r)
            ctx.lineTo(x + width, y + height - r)
            ctx.arcTo(x + width, y + height, x + width - r, y + height, r)
            ctx.lineTo(x + r, y + height)
            ctx.arcTo(x, y + height, x, y + height - r, r)
            ctx.lineTo(x, y + r)
            ctx.arcTo(x, y, x + r, y, r)
            ctx.closePath()

        # Outer glow shadow
        _rrect()
        ctx.shadowColor = "rgba(60, 140, 255, 0.12)"
        ctx.shadowBlur = 30
        ctx.fillStyle = "rgba(0,0,0,0)"
        ctx.fill()
        ctx.shadowColor = "transparent"
        ctx.shadowBlur = 0

        # Glassmorphism fill — dark with subtle gradient
        _rrect()
        panel_grad = ctx.createLinearGradient(x, y, x, y + height)
        panel_grad.addColorStop(0, "rgba(8, 14, 26, 0.92)")
        panel_grad.addColorStop(0.5, "rgba(6, 10, 20, 0.94)")
        panel_grad.addColorStop(1, "rgba(4, 8, 16, 0.96)")
        ctx.fillStyle = panel_grad
        ctx.fill()

        # Border with glow
        _rrect()
        ctx.strokeStyle = "rgba(80, 170, 255, 0.2)"
        ctx.lineWidth = 1.5
        ctx.stroke()

        # Top accent line — vivid
        top_grad = ctx.createLinearGradient(x + r + 10, y, x + width - r - 10, y)
        top_grad.addColorStop(0, "rgba(80, 180, 255, 0)")
        top_grad.addColorStop(0.3, "rgba(100, 200, 255, 0.3)")
        top_grad.addColorStop(0.7, "rgba(100, 200, 255, 0.3)")
        top_grad.addColorStop(1, "rgba(80, 180, 255, 0)")
        ctx.strokeStyle = top_grad
        ctx.lineWidth = 2
        ctx.beginPath()
        ctx.moveTo(x + r + 10, y + 1)
        ctx.lineTo(x + width - r - 10, y + 1)
        ctx.stroke()

        ctx.restore()

    def _draw_button(self, button: UIButton, card_text: str = "") -> None:
        hovered = button.contains(self.mouse_screen.x, self.mouse_screen.y)
        ctx = self.ctx
        accent = button.accent
        bx, by, bw, bh = button.x, button.y, button.width, button.height
        r = 12  # corner radius

        ctx.save()

        # Rounded rect path helper
        def _rrect():
            ctx.beginPath()
            ctx.moveTo(bx + r, by)
            ctx.lineTo(bx + bw - r, by)
            ctx.arcTo(bx + bw, by, bx + bw, by + r, r)
            ctx.lineTo(bx + bw, by + bh - r)
            ctx.arcTo(bx + bw, by + bh, bx + bw - r, by + bh, r)
            ctx.lineTo(bx + r, by + bh)
            ctx.arcTo(bx, by + bh, bx, by + bh - r, r)
            ctx.lineTo(bx, by + r)
            ctx.arcTo(bx, by, bx + r, by, r)
            ctx.closePath()

        # Hover underglow
        if hovered:
            _rrect()
            ctx.shadowColor = f"rgba({accent[0]}, {accent[1]}, {accent[2]}, 0.3)"
            ctx.shadowBlur = 20
            ctx.fillStyle = "rgba(0,0,0,0)"
            ctx.fill()
            ctx.shadowColor = "transparent"
            ctx.shadowBlur = 0

        # Glassmorphism Fill
        _rrect()
        fill_alpha1 = 0.25 if hovered else 0.08
        fill_alpha2 = 0.15 if hovered else 0.04
        btn_grad = ctx.createLinearGradient(bx, by, bx, by + bh)
        btn_grad.addColorStop(0, f"rgba({accent[0]}, {accent[1]}, {accent[2]}, {fill_alpha1})")
        btn_grad.addColorStop(1, f"rgba({accent[0]}, {accent[1]}, {accent[2]}, {fill_alpha2})")
        ctx.fillStyle = btn_grad
        ctx.fill()

        # Border
        border_alpha = 0.8 if hovered else 0.25
        ctx.strokeStyle = f"rgba({accent[0]}, {accent[1]}, {accent[2]}, {border_alpha})"
        ctx.lineWidth = 2 if hovered else 1
        ctx.stroke()

        # Left accent bar
        bar_w = 4 if hovered else 3
        bar_alpha = 0.95 if hovered else 0.4
        ctx.fillStyle = f"rgba({accent[0]}, {accent[1]}, {accent[2]}, {bar_alpha})"
        ctx.beginPath()
        ctx.moveTo(bx, by + r)
        ctx.lineTo(bx, by + bh - r)
        ctx.arcTo(bx, by + bh, bx + bar_w, by + bh, r)
        ctx.lineTo(bx + bar_w, by + r)
        ctx.arcTo(bx + bar_w, by, bx, by, r)
        ctx.closePath()
        ctx.fill()

        # Label
        ctx.fillStyle = "rgba(255, 255, 255, 1.0)" if hovered else "rgba(210, 224, 240, 0.9)"
        ctx.font = "700 20px Rajdhani, sans-serif"
        ctx.fillText(button.label, bx + 22, by + 30)
        ctx.restore()

        if card_text:
            ctx.font = "500 15px Rajdhani, sans-serif"
            ctx.fillStyle = "rgba(200, 220, 240, 0.9)" if hovered else "rgba(180, 200, 220, 0.85)"
            self._wrap_text(card_text, bx + 22, by + 56, bw - 40, 20)

    def _wrap_text(self, text: str, x: float, y: float, max_width: float, line_height: float) -> None:
        ctx = self.ctx
        words = text.split()
        line = ""
        cursor_y = y
        for word in words:
            test = word if not line else f"{line} {word}"
            if ctx.measureText(test).width > max_width and line:
                ctx.fillText(line, x, cursor_y)
                line = word
                cursor_y += line_height
            else:
                line = test
        if line:
            ctx.fillText(line, x, cursor_y)

    def _dispatch_click(self, x: float, y: float, button: int) -> None:
        if self.state_name == STATE_PLAYING:
            if button == 0:
                self.auto_shoot = not self.auto_shoot
            elif button == 2:
                self._use_ultra()
            return

        if self.state_name == STATE_MENU:
            for btn in self.menu_buttons:
                if btn.contains(x, y):
                    self._handle_menu_action(btn.action)
                    return
        elif self.state_name == STATE_GUIDE:
            self.state_name = STATE_MENU
        elif self.state_name == STATE_PAUSED:
            for btn in self.pause_buttons:
                if btn.contains(x, y):
                    self._handle_pause_action(btn.action)
                    return
        elif self.state_name == STATE_REWARD:
            for btn in self.reward_buttons:
                if btn.contains(x, y):
                    option = btn.payload
                    if self.reward_step == "temp":
                        self._apply_temp_reward(option["key"], int(option.get("duration", 2)))
                        self.reward_step = "perm"
                        self.reward_message = "Pick one permanent boost"
                        self._rebuild_reward_buttons()
                    else:
                        self._apply_perm_reward(option["key"])
                        if self.state:
                            self.state.last_wave_clear = self.state.time - float(self.balance.wave_cooldown)
                        self.state_name = STATE_PLAYING
                    return
        elif self.state_name == STATE_GAME_OVER:
            for btn in self.game_over_buttons:
                if btn.contains(x, y):
                    if btn.action == "restart":
                        self._start_game()
                    elif btn.action == "menu":
                        self._return_to_menu()
                    return

    def _handle_menu_action(self, action: str) -> None:
        if action == "start":
            self._start_game()
        elif action == "difficulty":
            idx = DIFFICULTY_OPTIONS.index(self.settings["difficulty"])
            self.settings["difficulty"] = DIFFICULTY_OPTIONS[(idx + 1) % len(DIFFICULTY_OPTIONS)]
            self._rebuild_ui()
        elif action == "map":
            idx = MAP_OPTIONS.index(self.settings["map_type"])
            self.settings["map_type"] = MAP_OPTIONS[(idx + 1) % len(MAP_OPTIONS)]
            self._rebuild_ui()
        elif action == "guide":
            self.state_name = STATE_GUIDE

    def _handle_pause_action(self, action: str) -> None:
        if action == "resume":
            self.state_name = STATE_PLAYING
        elif action == "restart":
            self._start_game()
        elif action == "menu":
            self._return_to_menu()

    def _normalized_key(self, event) -> str:
        key = str(event.key or "").lower()
        if key == " ":
            key = "space"
        return key

    def _on_key_down(self, event) -> None:
        key = self._normalized_key(event)
        if key in {"arrowup", "arrowdown", "arrowleft", "arrowright", "space"}:
            event.preventDefault()
        self.keys_down.add(key)

        if key == "escape":
            if self.state_name == STATE_PLAYING:
                self.state_name = STATE_PAUSED
            elif self.state_name == STATE_PAUSED:
                self.state_name = STATE_PLAYING
            elif self.state_name == STATE_GUIDE:
                self.state_name = STATE_MENU
            return

        if self.state_name != STATE_PLAYING:
            return
        if key == "q":
            self._use_ultra()
        elif key == "space":
            self._dash()

    def _on_key_up(self, event) -> None:
        key = self._normalized_key(event)
        self.keys_down.discard(key)

    def _event_to_canvas(self, event) -> tuple[float, float]:
        rect = self.canvas.getBoundingClientRect()
        x = float(event.clientX) - float(rect.left)
        y = float(event.clientY) - float(rect.top)
        return x, y

    def _on_mouse_move(self, event) -> None:
        x, y = self._event_to_canvas(event)
        self.mouse_screen = Vec2(x, y)

    def _on_mouse_down(self, event) -> None:
        event.preventDefault()
        x, y = self._event_to_canvas(event)
        self.mouse_screen = Vec2(x, y)
        self._mouse_down = True
        self._dispatch_click(x, y, int(event.button))

    def _on_mouse_up(self, event) -> None:
        event.preventDefault()
        self._mouse_down = False
        if int(event.button) == 2:
            self._rmb_down = False

    def _on_context_menu(self, event) -> None:
        event.preventDefault()


GAME: BrowserGame | None = None


def boot() -> None:
    """Entrypoint called from JavaScript after the modules are loaded."""
    global GAME
    GAME = BrowserGame()
    GAME.start()
