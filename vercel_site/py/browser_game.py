"""Browser game runtime for the Vercel build."""

from __future__ import annotations

from dataclasses import dataclass
import math
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
        self._frame_dt_cap = self.balance.frame_dt_cap
        self._max_catchup_steps = self.balance.max_catchup_steps
        self._accumulator = 0.0
        self._last_ts = 0.0
        self.background_t = 0.0
        self.flash = 0.0
        self.impact = 0.0

        self.state_name = STATE_MENU
        self.state: GameStateData | None = None
        self.player: Player | None = None
        self.score = ScoreTracker()
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
        rect = self.canvas.getBoundingClientRect()
        width = max(640, int(rect.width or SCREEN_W))
        height = max(480, int(rect.height or SCREEN_H))
        dpr = max(1.0, float(window.devicePixelRatio or 1.0))
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
        py = self.view_h * 0.5 + 92 * scale
        self.pause_buttons = [
            UIButton("Resume", self.view_w * 0.5 - pw * 0.5, py, pw, ph, "resume"),
            UIButton("Restart", self.view_w * 0.5 - pw * 0.5, py + ph + gap, pw, ph, "restart"),
            UIButton("Main Menu", self.view_w * 0.5 - pw * 0.5, py + 2 * (ph + gap), pw, ph, "menu"),
        ]

        gy = self.view_h * 0.5 + 110 * scale
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
        dt = max(0.0, min((ts - self._last_ts) / 1000.0, self._frame_dt_cap))
        self._last_ts = ts
        self.background_t += dt

        self._accumulator += dt
        steps = 0
        while self._accumulator >= self._fixed_dt and steps < self._max_catchup_steps:
            self.update(self._fixed_dt)
            self._accumulator -= self._fixed_dt
            steps += 1

        self.render()
        window.requestAnimationFrame(self._frame_proxy)

    def update(self, dt: float) -> None:
        self.flash = max(0.0, self.flash - dt * 2.6)
        self.impact = max(0.0, self.impact - dt * 6.0)
        self._wave_banner_t = max(0.0, self._wave_banner_t - dt)

        if self.state_name == STATE_PLAYING and self.state and self.player:
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

        recharge_dash(self.player, s.time, self.balance, self._dash_cd_difficulty, self._dash_cd_mult)
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
        ctx.clearRect(0, 0, self.view_w, self.view_h)
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
            self._draw_world(shake)
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
            ctx.fillStyle = f"rgba(255, 248, 236, {0.08 * self.flash})"
            ctx.fillRect(0, 0, self.view_w, self.view_h)

    def _draw_background(self, combat_intensity: float) -> None:
        ctx = self.ctx
        grad = ctx.createLinearGradient(0, 0, 0, self.view_h)
        grad.addColorStop(0, f"rgb({18 + int(40 * combat_intensity)}, {26 + int(10 * combat_intensity)}, {42 - int(6 * combat_intensity)})")
        grad.addColorStop(1, f"rgb({6 + int(25 * combat_intensity)}, {12}, {20})")
        ctx.fillStyle = grad
        ctx.fillRect(0, 0, self.view_w, self.view_h)

        ctx.save()
        ctx.globalAlpha = 0.13
        ctx.strokeStyle = "rgba(130, 180, 255, 0.3)"
        ctx.lineWidth = 1
        step = 44
        drift = (self.background_t * 18.0) % step
        for x in range(-step, self.view_w + step, step):
            ctx.beginPath()
            ctx.moveTo(x + drift, 0)
            ctx.lineTo(x + drift - self.view_h * 0.22, self.view_h)
            ctx.stroke()
        ctx.restore()

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

        ctx.save()
        self._trace_polygon(outer_screen)
        floor_grad = ctx.createLinearGradient(self.view_w * 0.3, self.view_h * 0.2, self.view_w * 0.7, self.view_h * 0.82)
        floor_grad.addColorStop(0, "rgba(38, 56, 78, 0.96)")
        floor_grad.addColorStop(1, f"rgba({24 + int(26 * combat_intensity)}, {32}, {38 - int(6 * combat_intensity)}, 0.96)")
        ctx.fillStyle = floor_grad
        ctx.fill()

        if map_type == MAP_DONUT:
            inner = self._sample_map_points(config.ROOM_RADIUS * 0.4, MAP_CIRCLE)
            inner_screen = [to_iso(point, shake) for point in inner]
            self._trace_polygon(inner_screen)
            ctx.fillStyle = "rgba(5, 10, 18, 0.88)"
            ctx.fill()

        ctx.strokeStyle = f"rgba({150 + int(70 * combat_intensity)}, {205}, {255}, 0.55)"
        ctx.lineWidth = 2.2
        self._trace_polygon(outer_screen)
        ctx.stroke()

        step = max(58, int(config.ROOM_RADIUS * 0.14))
        ctx.strokeStyle = "rgba(110, 145, 190, 0.24)"
        ctx.lineWidth = 1
        for line_pos in range(-int(config.ROOM_RADIUS), int(config.ROOM_RADIUS) + step, step):
            a = Vec2(line_pos, -config.ROOM_RADIUS)
            b = Vec2(line_pos, config.ROOM_RADIUS)
            ax, ay = to_iso(a, shake)
            bx, by = to_iso(b, shake)
            ctx.beginPath()
            ctx.moveTo(ax, ay)
            ctx.lineTo(bx, by)
            ctx.stroke()
            a = Vec2(-config.ROOM_RADIUS, line_pos)
            b = Vec2(config.ROOM_RADIUS, line_pos)
            ax, ay = to_iso(a, shake)
            bx, by = to_iso(b, shake)
            ctx.beginPath()
            ctx.moveTo(ax, ay)
            ctx.lineTo(bx, by)
            ctx.stroke()

        if preview_only:
            for idx in range(5):
                angle = self.background_t * 0.4 + idx * 1.26
                radius = config.ROOM_RADIUS * (0.24 + idx * 0.08)
                world = Vec2(math.cos(angle) * radius, math.sin(angle) * radius * 0.8)
                sx, sy = to_iso(world, shake)
                self._draw_glow_circle(sx, sy - 8, 11 + idx, (120 + idx * 18, 180, 255), 0.18)

        ctx.restore()

    def _draw_glow_circle(self, x: float, y: float, radius: float, color: tuple[int, int, int], alpha: float) -> None:
        ctx = self.ctx
        grad = ctx.createRadialGradient(x, y, 0, x, y, radius * 2.4)
        grad.addColorStop(0, f"rgba({color[0]}, {color[1]}, {color[2]}, {alpha})")
        grad.addColorStop(1, "rgba(0, 0, 0, 0)")
        ctx.fillStyle = grad
        ctx.beginPath()
        ctx.arc(x, y, radius * 2.4, 0, TAU)
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
        pulse = 1.0 + 0.15 * math.sin(self.background_t * 4.0 + powerup.pos.x * 0.02)
        self._draw_glow_circle(sx, sy - 14, 10 * pulse, color, 0.22)
        ctx = self.ctx
        ctx.fillStyle = f"rgb({color[0]}, {color[1]}, {color[2]})"
        ctx.beginPath()
        ctx.moveTo(sx, sy - 28 * pulse)
        ctx.lineTo(sx + 12 * pulse, sy - 14)
        ctx.lineTo(sx, sy)
        ctx.lineTo(sx - 12 * pulse, sy - 14)
        ctx.closePath()
        ctx.fill()

    def _draw_trap(self, trap, shake: Vec2) -> None:
        sx, sy = to_iso(trap.pos, shake)
        ctx = self.ctx
        armed = trap.t >= trap.armed_delay
        ctx.strokeStyle = "rgba(255, 128, 92, 0.9)" if armed else "rgba(255, 220, 120, 0.55)"
        ctx.lineWidth = 2.2
        ctx.beginPath()
        ctx.ellipse(sx, sy - 8, trap.radius, trap.radius * 0.56, 0, 0, TAU)
        ctx.stroke()

    def _draw_beam(self, beam, shake: Vec2) -> None:
        ax, ay = to_iso(beam.start, shake)
        bx, by = to_iso(beam.end, shake)
        ctx = self.ctx
        color = getattr(beam, "color", (255, 120, 255))
        alpha = 0.75 if getattr(beam, "owner", "player") == "player" else 0.55
        if getattr(beam, "warn", 0.0) and getattr(beam, "t", 0.0) < beam.warn:
            alpha = 0.25
        ctx.strokeStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, {alpha})"
        ctx.lineWidth = max(2.0, float(getattr(beam, "thickness", 4.0)) * 0.65)
        ctx.beginPath()
        ctx.moveTo(ax, ay)
        ctx.lineTo(bx, by)
        ctx.stroke()

    def _draw_projectile(self, projectile, shake: Vec2) -> None:
        sx, sy = to_iso(projectile.pos, shake)
        ptype = str(getattr(projectile, "projectile_type", "bullet"))
        palette = {
            "bullet": (255, 242, 196),
            "spread": (255, 200, 108),
            "missile": (255, 132, 132),
            "plasma": (175, 130, 255),
            "bomb": (255, 152, 88),
        }
        color = palette.get(ptype, (240, 240, 240))
        radius = max(3.0, self._projectile_radius(projectile) * 0.72)
        self._draw_glow_circle(sx, sy - 10, radius, color, 0.22)
        ctx = self.ctx
        ctx.fillStyle = f"rgb({color[0]}, {color[1]}, {color[2]})"
        ctx.beginPath()
        ctx.arc(sx, sy - 10, radius, 0, TAU)
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

        ctx.fillStyle = "rgba(10, 12, 18, 0.5)"
        ctx.beginPath()
        ctx.ellipse(sx, sy + 10, rx * 0.95, ry * 0.74, 0, 0, TAU)
        ctx.fill()

        self._draw_glow_circle(sx, sy - 16, rx * 0.8, color, 0.18 if not boss else 0.28)
        ctx.fillStyle = f"rgb({color[0]}, {color[1]}, {color[2]})"
        ctx.beginPath()
        ctx.ellipse(sx, sy - 14, rx, ry, 0, 0, TAU)
        ctx.fill()
        ctx.strokeStyle = "rgba(255,255,255,0.16)"
        ctx.lineWidth = 1.6
        ctx.stroke()

        if boss:
            max_hp = max(1, int(enemy_obj.ai.get("max_hp", enemy_obj.hp)))
            self._draw_entity_bar(sx - 28, sy - 44, 56, max(0.0, min(1.0, enemy_obj.hp / max_hp)), color)

    def _draw_player(self, shake: Vec2) -> None:
        if not self.player:
            return
        sx, sy = to_iso(self.player.pos, shake)
        ctx = self.ctx
        aim_dir = (iso_to_world((self.mouse_screen.x, self.mouse_screen.y)) - self.player.pos).normalized()
        if aim_dir.length() <= 1e-6:
            aim_dir = Vec2(1.0, 0.0)
        angle = math.atan2(aim_dir.y, aim_dir.x)
        hull = (132, 224, 255) if self.player.invincibility_timer <= 0 else (255, 236, 160)

        ctx.fillStyle = "rgba(8, 14, 22, 0.56)"
        ctx.beginPath()
        ctx.ellipse(sx, sy + 12, 18, 10, 0, 0, TAU)
        ctx.fill()

        self._draw_glow_circle(sx, sy - 18, 16, hull, 0.18)
        ctx.save()
        ctx.translate(sx, sy - 18)
        ctx.rotate(angle + math.pi * 0.25)
        ctx.fillStyle = f"rgb({hull[0]}, {hull[1]}, {hull[2]})"
        ctx.beginPath()
        ctx.moveTo(0, -18)
        ctx.lineTo(12, 2)
        ctx.lineTo(0, 14)
        ctx.lineTo(-12, 2)
        ctx.closePath()
        ctx.fill()
        ctx.strokeStyle = "rgba(255,255,255,0.32)"
        ctx.lineWidth = 1.5
        ctx.stroke()
        ctx.restore()

    def _draw_entity_bar(self, x: float, y: float, width: float, ratio: float, color: tuple[int, int, int]) -> None:
        ctx = self.ctx
        ctx.fillStyle = "rgba(8, 12, 20, 0.7)"
        ctx.fillRect(x, y, width, 7)
        ctx.fillStyle = f"rgb({color[0]}, {color[1]}, {color[2]})"
        ctx.fillRect(x, y, width * ratio, 7)

    def _draw_hud(self) -> None:
        if not self.state or not self.player:
            return
        ctx = self.ctx
        ctx.save()
        ctx.fillStyle = "rgba(5, 9, 16, 0.72)"
        ctx.fillRect(24, 24, 380, 142)
        ctx.strokeStyle = "rgba(150, 220, 255, 0.18)"
        ctx.strokeRect(24, 24, 380, 142)

        self._draw_bar(44, 52, 210, 12, self.player.hp / max(1, self.player.max_hp), (110, 230, 170), "HP")
        self._draw_bar(44, 78, 210, 12, max(0.0, min(1.0, self.player.shield / 120.0)), (110, 180, 255), "Shield")

        ctx.fillStyle = "rgba(232, 240, 255, 0.95)"
        ctx.font = "700 16px Rajdhani, sans-serif"
        ctx.fillText(f"Wave {self.state.wave}", 282, 58)
        ctx.fillText(f"Score {self.score.score}", 282, 82)
        ctx.fillText(f"Combo x{self.score.combo:.2f}", 282, 106)
        ctx.fillText(f"Weapon {self.player.current_weapon.name}", 282, 130)

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
        status = "  |  ".join(status_parts) if status_parts else "LMB auto-fire  |  Space dash  |  Q or RMB ultra"

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
            y = 28
            ctx.fillStyle = "rgba(8, 12, 18, 0.8)"
            ctx.fillRect(x, y, width, 12)
            ctx.fillStyle = "rgba(255, 142, 142, 0.95)"
            ctx.fillRect(x, y, width * ratio, 12)
            ctx.fillStyle = "rgba(244, 248, 255, 0.95)"
            ctx.font = "700 14px Orbitron, sans-serif"
            ctx.fillText(f"BOSS {boss_name}  HP {boss.hp}", x, y - 8)
        ctx.restore()

    def _draw_bar(self, x: float, y: float, width: float, height: float, ratio: float, color: tuple[int, int, int], label: str) -> None:
        ctx = self.ctx
        ctx.fillStyle = "rgba(8, 12, 18, 0.72)"
        ctx.fillRect(x, y, width, height)
        ctx.fillStyle = f"rgb({color[0]}, {color[1]}, {color[2]})"
        ctx.fillRect(x, y, width * max(0.0, min(1.0, ratio)), height)
        ctx.fillStyle = "rgba(245, 248, 255, 0.92)"
        ctx.font = "700 12px Orbitron, sans-serif"
        ctx.fillText(label, x, y - 6)

    def _draw_wave_banner(self) -> None:
        if not self.state:
            return
        ctx = self.ctx
        alpha = min(1.0, self._wave_banner_t)
        text = f"WAVE {self.state.wave}"
        if self._last_cleared_wave and self._last_cleared_wave % 5 == 0:
            text = f"BOSS CLEAR  //  {text}"
        ctx.save()
        ctx.globalAlpha = 0.18 + alpha * 0.72
        ctx.fillStyle = "rgba(7, 11, 20, 0.65)"
        width = min(self.view_w * 0.34, 360)
        x = (self.view_w - width) * 0.5
        y = 110
        ctx.fillRect(x, y, width, 52)
        ctx.fillStyle = "rgba(235, 242, 255, 0.96)"
        ctx.font = "700 22px Orbitron, sans-serif"
        ctx.textAlign = "center"
        ctx.fillText(text, self.view_w * 0.5, y + 32)
        ctx.restore()
        ctx.textAlign = "start"

    def _draw_menu(self) -> None:
        ctx = self.ctx
        self._draw_panel(44, 44, min(self.view_w * 0.4, 520), self.view_h - 88)
        ctx.fillStyle = "rgba(240, 245, 255, 0.98)"
        ctx.font = "700 42px Orbitron, sans-serif"
        ctx.fillText("PLOUTO", 78, 118)
        ctx.font = "600 18px Rajdhani, sans-serif"
        ctx.fillStyle = "rgba(200, 216, 236, 0.92)"
        self._wrap_text("Stellar Survival rebuilt for the browser. The simulation stays in Python and now runs directly in Vercel as a static deployment.", 78, 152, min(self.view_w * 0.34, 430), 24)
        self._wrap_text("Controls: WASD or arrows move, left click toggles auto-fire, right click or Q uses Ultra, Space dashes, Esc pauses.", 78, 238, min(self.view_w * 0.34, 430), 22)

        high_score = ScoreTracker(difficulty=self.settings["difficulty"]).get_high_score()
        ctx.font = "700 16px Rajdhani, sans-serif"
        ctx.fillStyle = "rgba(160, 214, 255, 0.96)"
        ctx.fillText(f"Best {self.settings['difficulty'].title()} Score: {high_score}", 78, 336)
        ctx.fillText(f"Arena Radius: {int(config.ROOM_RADIUS)}", 78, 364)

        for button in self.menu_buttons:
            self._draw_button(button)

    def _draw_pause(self) -> None:
        self._draw_panel(self.view_w * 0.5 - 190, self.view_h * 0.5 - 180, 380, 340)
        ctx = self.ctx
        ctx.fillStyle = "rgba(244, 247, 255, 0.98)"
        ctx.font = "700 34px Orbitron, sans-serif"
        ctx.fillText("PAUSED", self.view_w * 0.5 - 72, self.view_h * 0.5 - 110)
        ctx.font = "600 18px Rajdhani, sans-serif"
        ctx.fillStyle = "rgba(192, 208, 228, 0.92)"
        ctx.fillText("Take a breath, then jump back in.", self.view_w * 0.5 - 102, self.view_h * 0.5 - 76)
        for button in self.pause_buttons:
            self._draw_button(button)

    def _draw_reward_panel(self) -> None:
        self._draw_panel(34, 34, self.view_w - 68, self.view_h - 68)
        ctx = self.ctx
        title = "Temporary Card" if self.reward_step == "temp" else "Permanent Run Boost"
        ctx.fillStyle = "rgba(244, 247, 255, 0.98)"
        ctx.font = "700 34px Orbitron, sans-serif"
        ctx.fillText(title, 64, 96)
        ctx.font = "600 18px Rajdhani, sans-serif"
        ctx.fillStyle = "rgba(192, 208, 228, 0.92)"
        ctx.fillText(self.reward_message or "Choose one", 64, 126)

        for button in self.reward_buttons:
            self._draw_button(button, card_text=button.payload.get("desc", ""))

    def _draw_game_over(self) -> None:
        self._draw_panel(self.view_w * 0.5 - 240, self.view_h * 0.5 - 210, 480, 390)
        ctx = self.ctx
        ctx.fillStyle = "rgba(244, 247, 255, 0.98)"
        ctx.font = "700 34px Orbitron, sans-serif"
        ctx.fillText("RUN COMPLETE", self.view_w * 0.5 - 146, self.view_h * 0.5 - 136)
        ctx.font = "700 20px Rajdhani, sans-serif"
        ctx.fillStyle = "rgba(208, 220, 238, 0.95)"
        ctx.fillText(f"Wave Reached: {self.final_wave}", self.view_w * 0.5 - 90, self.view_h * 0.5 - 86)
        ctx.fillText(f"Final Score: {self.final_score}", self.view_w * 0.5 - 90, self.view_h * 0.5 - 58)
        ctx.fillText(f"High Score: {self.high_score}", self.view_w * 0.5 - 90, self.view_h * 0.5 - 30)
        if self.is_new_high:
            ctx.fillStyle = "rgba(255, 216, 132, 0.98)"
            ctx.font = "700 24px Orbitron, sans-serif"
            ctx.fillText("NEW HIGH SCORE", self.view_w * 0.5 - 112, self.view_h * 0.5 + 12)
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
        ctx.fillStyle = "rgba(5, 10, 18, 0.78)"
        ctx.fillRect(x, y, width, height)
        ctx.strokeStyle = "rgba(154, 214, 255, 0.24)"
        ctx.lineWidth = 2
        ctx.strokeRect(x, y, width, height)

    def _draw_button(self, button: UIButton, card_text: str = "") -> None:
        hovered = button.contains(self.mouse_screen.x, self.mouse_screen.y)
        ctx = self.ctx
        accent = button.accent
        fill_alpha = 0.28 if hovered else 0.18
        ctx.fillStyle = f"rgba({accent[0]}, {accent[1]}, {accent[2]}, {fill_alpha})"
        ctx.fillRect(button.x, button.y, button.width, button.height)
        ctx.strokeStyle = f"rgba({accent[0]}, {accent[1]}, {accent[2]}, {0.9 if hovered else 0.46})"
        ctx.lineWidth = 2
        ctx.strokeRect(button.x, button.y, button.width, button.height)
        ctx.fillStyle = "rgba(245, 248, 255, 0.98)"
        ctx.font = "700 20px Rajdhani, sans-serif"
        ctx.fillText(button.label, button.x + 20, button.y + 32)
        if card_text:
            ctx.font = "500 16px Rajdhani, sans-serif"
            ctx.fillStyle = "rgba(212, 224, 240, 0.92)"
            self._wrap_text(card_text, button.x + 20, button.y + 62, button.width - 32, 22)

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
