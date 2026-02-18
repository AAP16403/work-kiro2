"""Panda3D game controller."""

from __future__ import annotations

import math
import random

import config
from config import SCREEN_W, SCREEN_H, FPS, MAP_CIRCLE, MAP_DONUT, MAP_CROSS, MAP_DIAMOND

from direct.showbase.DirectObject import DirectObject
from direct.showbase.ShowBaseGlobal import globalClock
from panda3d.core import KeyboardButton, Plane, Point3, Vec3, WindowProperties

from map import Room
from level import GameState as GameStateData, get_difficulty_mods, spawn_loot_on_enemy_death
from utils import set_view_size, compute_room_radius, Vec2, clamp_to_map, enemy_behavior_name, dist, point_segment_distance
from visuals import Visuals, GroupCache
from weapons import get_weapon_for_wave
from particles import ParticleSystem
from menu import MainMenu, SettingsMenu, GuideMenu, PauseMenu, GameOverMenu, load_fonts
from hud import HUD
from rpg import (
    BossRewardMenu,
    recompute_temp_mods,
    advance_temp_rewards,
    apply_temp_reward as rpg_apply_temp,
    apply_perm_reward as rpg_apply_perm,
    roll_boss_rewards as rpg_roll_rewards,
)
from hazards import LaserBeam
from layout import generate_obstacles
from logic import BalanceLogic
from player import Player, perform_dash
from fsm import StateMachine
from advanced_fx import AdvancedFX
from score import ScoreTracker
from states import MenuState, SettingsState, GuideState, PlayingState, PausedState, BossRewardState, GameOverState


class Game(DirectObject):
    """Main game logic controller."""

    def __init__(self, showbase):
        super().__init__()
        self.base = showbase
        print("DEBUG: Game.__init__ called")

        set_view_size(SCREEN_W, SCREEN_H)
        self.settings = {
            "difficulty": "normal",
            "window_size": (SCREEN_W, SCREEN_H),
            "fullscreen": True,
            "arena_margin": float(getattr(config, "ARENA_MARGIN", 0.97)),
            "advanced_fx": bool(getattr(config, "ENABLE_ADVANCED_FX", True)),
            "map_type": MAP_CIRCLE,
        }
        self._windowed_size = (SCREEN_W, SCREEN_H)
        self._pending_boss_rewards: tuple[list[dict], list[dict]] | None = None

        self.batch = None
        self.groups: GroupCache | None = None
        self.room: Room | None = None
        self.state: GameStateData | None = None
        self.player: Player | None = None
        self.visuals: Visuals | None = None
        self.particle_system: ParticleSystem | None = None
        self.score: ScoreTracker | None = None

        self.auto_shoot = False
        self._rmb_down = False
        self._last_mouse_world = Vec2(0.0, 0.0)
        self._last_aim_dir = Vec2(1.0, 0.0)
        self.balance = BalanceLogic(fps=float(FPS))
        self._frame_dt_cap = self.balance.frame_dt_cap
        self.advanced_fx = AdvancedFX(SCREEN_W, SCREEN_H)
        self.advanced_fx.enabled = bool(self.settings.get("advanced_fx", True))

        # Load UI fonts
        load_fonts(self.base.loader)

        self.main_menu = MainMenu(self)
        self.settings_menu = SettingsMenu(self)
        self.guide_menu = GuideMenu(self)
        self.pause_menu = PauseMenu(self)
        self.game_over_menu = GameOverMenu(self)
        self.hud = HUD(self)
        self.rpg_menu = BossRewardMenu(SCREEN_W, SCREEN_H, self._on_pick_temp_reward, self._on_pick_perm_reward)

        self.fsm = StateMachine(MenuState(self))
        self.fsm.add_state(SettingsState(self))
        self.fsm.add_state(GuideState(self))
        self.fsm.add_state(PlayingState(self))
        self.fsm.add_state(PausedState(self))
        print("DEBUG: StateMachine initialized with MenuState")
        self.fsm.add_state(BossRewardState(self))
        self.fsm.add_state(GameOverState(self))

        self._setup_input()
        self._update_room_radius_from_view()
        self.base.taskMgr.add(self.update, "GameUpdate")

    def _setup_input(self) -> None:
        self.accept("mouse1", self._on_mouse_1)
        self.accept("mouse3", self._on_mouse_3)
        self.accept("mouse3-up", self._on_mouse_3_up)
        self.accept("space", self._on_dash_key)
        self.accept("q", self._on_ultra_key)
        self.accept("escape", self._on_pause_key)

    def _is_playing_state(self) -> bool:
        return bool(self.fsm.current_state and self.fsm.current_state.__class__.__name__ == "PlayingState")

    def _on_mouse_1(self) -> None:
        if self._is_playing_state():
            self.auto_shoot = not self.auto_shoot

    def _on_mouse_3(self) -> None:
        self._rmb_down = True
        if self._is_playing_state():
            self._use_ultra()

    def _on_mouse_3_up(self) -> None:
        self._rmb_down = False

    def _on_dash_key(self) -> None:
        if self._is_playing_state():
            self._dash()

    def _on_ultra_key(self) -> None:
        if self._is_playing_state():
            self._use_ultra()

    def _on_pause_key(self) -> None:
        if not self.fsm.current_state:
            return
        name = self.fsm.current_state.__class__.__name__
        if name == "PlayingState":
            self.fsm.set_state("PausedState")
        elif name == "PausedState":
            self.fsm.set_state("PlayingState")

    def _update_room_radius_from_view(self) -> None:
        margin = float(self.settings.get("arena_margin", getattr(config, "ARENA_MARGIN", 0.97)))
        config.ROOM_RADIUS = compute_room_radius(SCREEN_W, SCREEN_H, margin=margin)

    def _init_game(self) -> None:
        if self.visuals:
            self.visuals.destroy()
        print("DEBUG: _init_game called - resetting state")
        if self.particle_system:
            self.particle_system.destroy()
        if self.room:
            self.room.destroy()
        self.groups = GroupCache()
        self.room = Room(None, SCREEN_W, SCREEN_H, map_type=self.settings.get("map_type", MAP_CIRCLE), parent=self.base.render)
        
        # Test Safe Zone
        # self.room.set_safe_zone(True, radius=150.0)

        difficulty = str(self.settings.get("difficulty", "normal")).lower()
        self.state = GameStateData(difficulty=difficulty, map_type=self.settings.get("map_type", MAP_CIRCLE))
        if difficulty == "easy":
            self.state.max_enemies = 10
            self._incoming_damage_mult = 0.85
        elif difficulty == "hard":
            self.state.max_enemies = 14
            self._incoming_damage_mult = 1.15
        else:
            self.state.max_enemies = 12
            self._incoming_damage_mult = 1.0

        if config.ENABLE_OBSTACLES:
            self.state.layout_seed = random.randint(0, 1_000_000_000)
            self.state.layout_segment = 0
            self.state.obstacles = generate_obstacles(
                self.state.layout_seed,
                self.state.layout_segment,
                config.ROOM_RADIUS,
                difficulty=self.state.difficulty,
            )
        else:
            self.state.obstacles = []

        self.player = Player(pos=Vec2(0.0, 0.0))
        self.player.current_weapon = get_weapon_for_wave(1)

        self._active_temp_rewards: list[dict] = []
        self._run_permanent_rewards: list[str] = []
        self._last_reward_temp_key = ""
        self._last_reward_perm_key = ""
        self._pickup_magnet_bonus = 0.0
        self._temp_damage_mult = 1.0
        self._temp_speed_mult = 1.0
        self._temp_fire_rate_mult = 1.0
        self._temp_incoming_damage_mult = 1.0
        self._ultra_cd_mult = 1.0
        self._dash_cd_mult = 1.0
        self._dash_cd_difficulty = float(get_difficulty_mods(difficulty).get("dash_cd", 1.0))

        self.visuals = Visuals(self.base.render, self.groups, loader=self.base.loader)
        self.visuals.make_player()
        self.particle_system = ParticleSystem(parent=self.base.render)
        self.score = ScoreTracker(difficulty=difficulty)
        self.auto_shoot = False
        self._pending_boss_rewards = None
        if self.rpg_menu:
            self.rpg_menu.complete = False
            self.rpg_menu.active = False
            self.rpg_menu.hide()

    def _effective_player_damage(self) -> int:
        if not self.player:
            return 0
        return max(1, int(round(float(self.player.damage) * float(getattr(self, "_temp_damage_mult", 1.0)))))

    def _effective_player_speed(self) -> float:
        if not self.player:
            return 0.0
        return float(self.player.speed) * float(getattr(self, "_temp_speed_mult", 1.0))

    def _effective_player_fire_rate(self) -> float:
        if not self.player:
            return 0.28
        return max(0.08, float(self.player.fire_rate) * float(getattr(self, "_temp_fire_rate_mult", 1.0)))

    def _recompute_temp_reward_mods(self) -> None:
        mods = recompute_temp_mods(getattr(self, "_active_temp_rewards", []))
        self._temp_damage_mult = mods["damage"]
        self._temp_speed_mult = mods["speed"]
        self._temp_fire_rate_mult = mods["fire_rate"]
        self._pickup_magnet_bonus = mods["magnet"]
        self._temp_incoming_damage_mult = mods["incoming_damage"]
        self._ultra_cd_mult = mods["ultra_cd"]

    def _advance_temp_rewards(self) -> None:
        if not getattr(self, "_active_temp_rewards", None):
            return
        self._active_temp_rewards = advance_temp_rewards(self._active_temp_rewards)
        self._recompute_temp_reward_mods()

    def _roll_boss_rewards(self) -> None:
        if not self.player:
            return
        temp_opts, perm_opts = rpg_roll_rewards(
            self._active_temp_rewards,
            self._last_reward_temp_key,
            self._last_reward_perm_key,
        )
        self._pending_boss_rewards = (temp_opts, perm_opts)
        self.rpg_menu.begin(temp_opts, perm_opts)

    def consume_pending_boss_rewards(self, temp_index: int = 0, perm_index: int = 0) -> None:
        if not self._pending_boss_rewards:
            return
        temp_opts, perm_opts = self._pending_boss_rewards
        if temp_opts:
            t = temp_opts[max(0, min(int(temp_index), len(temp_opts) - 1))]
            self._apply_temp_reward(str(t.get("key", "")), int(t.get("duration", 2)))
        if perm_opts:
            p = perm_opts[max(0, min(int(perm_index), len(perm_opts) - 1))]
            self._apply_perm_reward(str(p.get("key", "")))
        self._pending_boss_rewards = None

    def _on_pick_temp_reward(self, key: str, duration: int = 2) -> None:
        self._apply_temp_reward(key, duration)

    def _on_pick_perm_reward(self, key: str) -> None:
        self._apply_perm_reward(key)

    def _apply_temp_reward(self, key: str, duration: int) -> None:
        if not self.player:
            return
        k = str(key or "").strip().lower()
        rpg_apply_temp(self._active_temp_rewards, k, duration)
        self._last_reward_temp_key = k
        if k == "temp_ultra_flux":
            self.player.ultra_charges = min(int(getattr(config, "ULTRA_MAX_CHARGES", 2)), int(self.player.ultra_charges) + 1)
        if self.particle_system:
            self.particle_system.add_powerup_collection(self.player.pos, (255, 235, 170))
        if self.state:
            self.state.shake = max(self.state.shake, 5.0)
        self._recompute_temp_reward_mods()

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
        if not applied:
            return
        self._last_reward_perm_key = k
        if self.particle_system:
            self.particle_system.add_powerup_collection(self.player.pos, (200, 235, 255))
        if self.state:
            self.state.shake = max(self.state.shake, 6.0)

    def _regen_layout(self, segment: int | None = None) -> None:
        if not config.ENABLE_OBSTACLES:
            if self.state:
                self.state.obstacles = []
            return
        if not self.state:
            return

        if segment is None:
            segment = int(getattr(self.state, "layout_segment", 0))

        if self.visuals:
            for ob in list(getattr(self.state, "obstacles", [])):
                self.visuals.drop_obstacle(ob)

        self.state.layout_segment = int(segment)
        self.state.obstacles = generate_obstacles(
            int(getattr(self.state, "layout_seed", 0)),
            self.state.layout_segment,
            config.ROOM_RADIUS,
            difficulty=getattr(self.state, "difficulty", "normal"),
        )

    def _damage_player(self, amount: int) -> None:
        if not self.player:
            return
        if self.player.invincibility_timer > 0:
            return
        if amount <= 0:
            return

        mult = getattr(self, "_incoming_damage_mult", 1.0) * getattr(self, "_temp_incoming_damage_mult", 1.0)
        if mult != 1.0:
            amount = max(1, int(round(amount * mult)))

        if self.player.shield > 0:
            absorbed = min(self.player.shield, amount)
            self.player.shield -= absorbed
            amount -= absorbed
            if absorbed > 0 and self.particle_system:
                self.particle_system.add_shield_hit(self.player.pos, absorbed)

        if amount > 0:
            self.player.hp -= amount
            if getattr(self, "advanced_fx", None):
                self.advanced_fx.trigger_hit(min(1.0, 0.28 + amount * 0.03))
            if self.score:
                self.score.on_player_hit()

    def _use_ultra(self) -> None:
        if not self.state or not self.player:
            return

        s = self.state
        if int(getattr(self.player, "ultra_charges", 0)) <= 0:
            return
        if s.time < float(getattr(self.player, "ultra_cd_until", 0.0)):
            return

        aim = self.get_aim_direction(self.player.pos)

        muzzle = self.player.pos + aim * 14.0
        dmg = int(config.ULTRA_DAMAGE_BASE + self._effective_player_damage() * config.ULTRA_DAMAGE_MULT)
        beam_thickness = float(config.ULTRA_BEAM_THICKNESS)
        beam_ttl = float(config.ULTRA_BEAM_TTL)

        def _hit_enemy(enemy_obj, amount: int) -> None:
            enemy_obj.hp -= int(amount)
            behavior_name = enemy_behavior_name(enemy_obj)
            enemy_color = config.ENEMY_COLORS.get(behavior_name, (200, 200, 200))
            if self.particle_system:
                self.particle_system.add_hit_particles(enemy_obj.pos, enemy_color)
            if enemy_obj.hp <= 0:
                if enemy_obj in s.enemies:
                    s.enemies.remove(enemy_obj)
                if self.visuals:
                    self.visuals.drop_enemy(enemy_obj)
                if self.particle_system:
                    self.particle_system.add_death_explosion(enemy_obj.pos, enemy_color, behavior_name)
                spawn_loot_on_enemy_death(s, behavior_name, enemy_obj.pos)
                if self.score:
                    self.score.on_enemy_kill(behavior_name)

        def _spawn_player_beam(start: Vec2, direction: Vec2, length: float, damage: int, thickness: float, color) -> None:
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
            s.lasers.append(beam)
            if self.particle_system:
                self.particle_system.add_laser_beam(start, end, color=beam.color)

            hit_r = float(thickness) * 0.5
            for enemy_obj in list(s.enemies):
                if point_segment_distance(enemy_obj.pos, start, end) <= hit_r + self._enemy_radius(enemy_obj):
                    _hit_enemy(enemy_obj, int(damage))

        variant = int(getattr(self.player, "ultra_variant_idx", 0)) % 3
        self.player.ultra_variant_idx = (variant + 1) % 3

        if variant == 0:
            _spawn_player_beam(
                muzzle,
                aim,
                length=config.ROOM_RADIUS * 2.05,
                damage=dmg,
                thickness=beam_thickness,
                color=tuple(config.ULTRA_BEAM_COLOR),
            )
            s.shake = max(s.shake, 12.0)
        elif variant == 1:
            for deg in (-16.0, 0.0, 16.0):
                a = math.radians(deg)
                c = math.cos(a)
                si = math.sin(a)
                d = Vec2(aim.x * c - aim.y * si, aim.x * si + aim.y * c).normalized()
                _spawn_player_beam(
                    muzzle,
                    d,
                    length=config.ROOM_RADIUS * 1.9,
                    damage=int(dmg * 0.72),
                    thickness=beam_thickness * 0.8,
                    color=(255, 180, 180),
                )
            s.shake = max(s.shake, 14.0)
        else:
            blast_r = 160.0
            blast_dmg = int(dmg * 0.58)
            for enemy_obj in list(s.enemies):
                if dist(enemy_obj.pos, self.player.pos) <= blast_r:
                    _hit_enemy(enemy_obj, blast_dmg)
            if self.particle_system:
                self.particle_system.add_powerup_collection(self.player.pos, (255, 220, 180))
            _spawn_player_beam(
                muzzle,
                aim,
                length=config.ROOM_RADIUS * 1.55,
                damage=int(dmg * 0.62),
                thickness=beam_thickness * 0.7,
                color=(255, 210, 120),
            )
            s.shake = max(s.shake, 16.0)

        self.player.ultra_charges = max(0, int(self.player.ultra_charges) - 1)
        self.player.ultra_cd_until = s.time + float(config.ULTRA_COOLDOWN) * float(getattr(self, "_ultra_cd_mult", 1.0))

    def _dash(self) -> None:
        if not self.state or not self.player:
            return

        world_mouse = self.get_mouse_world_pos()
        did_dash = perform_dash(
            self.player,
            self.state.time,
            self.balance,
            float(getattr(self, "_dash_cd_difficulty", 1.0)),
            float(getattr(self, "_dash_cd_mult", 1.0)),
            self._input_dir(),
            world_mouse,
        )
        if did_dash and self.particle_system:
            self.particle_system.add_dash_effect(self.player.pos, self.player.dash_direction)

    def _enemy_radius(self, enemy) -> float:
        return self.balance.enemy_radius(enemy_behavior_name(enemy))

    def _player_radius(self) -> float:
        return self.balance.player_radius

    def _projectile_radius(self, projectile) -> float:
        ptype = str(getattr(projectile, "projectile_type", "bullet"))
        return self.balance.projectile_radius(ptype)

    def _quit_game(self) -> None:
        self.base.userExit()

    @staticmethod
    def _coerce_bool(value, default: bool = True) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {"1", "true", "yes", "on", "enabled"}:
                return True
            if v in {"0", "false", "no", "off", "disabled"}:
                return False
        return bool(default)

    def _on_settings_change(self, setting_key, value=None) -> None:
        if isinstance(setting_key, dict):
            for k, v in setting_key.items():
                self._on_settings_change(k, v)
            return

        if setting_key == "difficulty":
            self.settings["difficulty"] = str(value or "normal").lower()
            return

        if setting_key == "window_size" and isinstance(value, (tuple, list)) and len(value) == 2:
            width = int(value[0])
            height = int(value[1])
            self.settings["window_size"] = (width, height)
            self._windowed_size = (width, height)
            props = WindowProperties()
            props.setSize(width, height)
            self.base.win.requestProperties(props)
            return

        if setting_key == "fullscreen":
            fs = self._coerce_bool(value, default=True)
            self.settings["fullscreen"] = fs
            props = WindowProperties()
            props.setFullscreen(fs)
            self.base.win.requestProperties(props)
            return

        if setting_key == "arena_margin":
            margin = max(0.5, min(0.98, float(value)))
            self.settings["arena_margin"] = margin
            config.ARENA_MARGIN = margin
            self._update_room_radius_from_view()
            return

        if setting_key == "advanced_fx":
            fx = self._coerce_bool(value, default=True)
            self.settings["advanced_fx"] = fx
            config.ENABLE_ADVANCED_FX = fx
            if self.advanced_fx:
                self.advanced_fx.enabled = fx
            return

        if setting_key == "map_type":
            allowed = {MAP_CIRCLE, MAP_DONUT, MAP_CROSS, MAP_DIAMOND}
            map_type = str(value or MAP_CIRCLE).lower()
            if map_type not in allowed:
                map_type = MAP_CIRCLE
            self.settings["map_type"] = map_type
            if self.state:
                self.state.map_type = map_type
                if self.player:
                    self.player.pos = clamp_to_map(self.player.pos, config.ROOM_RADIUS * 0.9, map_type)
            if self.room:
                self.room.rebuild(map_type)
            return

        self.settings[str(setting_key)] = value

    def _input_dir(self) -> Vec2:
        mwn = self.base.mouseWatcherNode
        if not mwn:
            return Vec2(0.0, 0.0)

        x = 0.0
        y = 0.0
        is_down = mwn.isButtonDown

        if is_down(KeyboardButton.asciiKey("w")) or is_down(KeyboardButton.up()):
            y += 1.0
        if is_down(KeyboardButton.asciiKey("s")) or is_down(KeyboardButton.down()):
            y -= 1.0
        if is_down(KeyboardButton.asciiKey("d")) or is_down(KeyboardButton.right()):
            x += 1.0
        if is_down(KeyboardButton.asciiKey("a")) or is_down(KeyboardButton.left()):
            x -= 1.0

        return Vec2(x, y)

    def get_mouse_world_pos(self) -> Vec2:
        mwn = self.base.mouseWatcherNode
        if not mwn or not mwn.hasMouse():
            return Vec2(self._last_mouse_world.x, self._last_mouse_world.y)

        mpos = mwn.getMouse()
        near_point = Point3()
        far_point = Point3()
        self.base.camLens.extrude(mpos, near_point, far_point)

        plane = Plane(Vec3(0, 0, 1), Point3(0, 0, 10))
        cam_np = self.base.cam
        near_world = self.base.render.getRelativePoint(cam_np, near_point)
        far_world = self.base.render.getRelativePoint(cam_np, far_point)

        intersection = Point3()
        if plane.intersectsLine(intersection, near_world, far_world):
            self._last_mouse_world = Vec2(intersection.x, intersection.y)
            return Vec2(intersection.x, intersection.y)

        return Vec2(self._last_mouse_world.x, self._last_mouse_world.y)

    def get_aim_direction(self, origin: Vec2 | None = None) -> Vec2:
        if origin is None:
            if self.player:
                origin = self.player.pos
            else:
                origin = Vec2(0.0, 0.0)

        mouse_world = self.get_mouse_world_pos()
        aim = (mouse_world - origin).normalized()
        if aim.length() <= 1e-6 and self.state and self.state.enemies:
            nearest = min(self.state.enemies, key=lambda e: dist(e.pos, origin))
            aim = (nearest.pos - origin).normalized()
        if aim.length() <= 1e-6:
            aim = Vec2(self._last_aim_dir.x, self._last_aim_dir.y)
        else:
            self._last_aim_dir = Vec2(aim.x, aim.y)
        return aim

    def _sync_visuals(self) -> None:
        if not self.state or not self.player or not self.visuals:
            return

        s = self.state
        shake_mag = max(0.0, float(s.shake))
        if shake_mag > 0.0:
            shake = Vec2(random.uniform(-1.0, 1.0) * min(5.0, shake_mag * 0.25), random.uniform(-1.0, 1.0) * min(5.0, shake_mag * 0.25))
        else:
            shake = Vec2(0.0, 0.0)

        aim_dir = self.get_aim_direction(self.player.pos)
        self.visuals.sync_player(self.player, shake, t=s.time, aim_dir=aim_dir)

        for ob in s.obstacles:
            self.visuals.ensure_obstacle(ob)
            self.visuals.sync_obstacle(ob, shake)

        for enemy_obj in s.enemies:
            self.visuals.ensure_enemy(enemy_obj)
            self.visuals.sync_enemy(enemy_obj, shake)

        for proj in s.projectiles:
            self.visuals.ensure_projectile(proj)
            self.visuals.sync_projectile(proj, shake)

        for powerup in s.powerups:
            self.visuals.ensure_powerup(powerup)
            self.visuals.sync_powerup(powerup, shake)

        for laser in s.lasers:
            self.visuals.ensure_laser(laser)
            self.visuals.sync_laser(laser, shake)

        for thunder in s.thunders:
            self.visuals.ensure_thunder(thunder)
            self.visuals.sync_thunder(thunder, shake)

        for trap in s.traps:
            self.visuals.ensure_trap(trap)
            self.visuals.sync_trap(trap, shake)

        self.visuals.sync_scene(s.time, shake, combat_intensity=getattr(self.room, "combat_intensity", 0.0))
        if self.particle_system:
            self.particle_system.render(shake)

    def update(self, task):
        dt = globalClock.getDt()
        dt = max(0.0, min(float(dt), float(self._frame_dt_cap)))

        self.fsm.update(dt)
        self._sync_visuals()
        if self.player and self.state and self.advanced_fx:
            hp_ratio = max(0.0, min(1.0, float(self.player.hp) / max(1.0, float(self.player.max_hp))))
            boss_active = any(str(getattr(e, "behavior", "")).startswith("boss_") for e in self.state.enemies)
            self.advanced_fx.render(self.state.time, getattr(self.room, "combat_intensity", 0.0), hp_ratio, boss_active)
        return task.cont
