# Pyglet isometric room survival prototype
# Controls: WASD/Arrows move, LMB toggles auto-fire, SPACE dash, ESC menu.
# Install: py -m pip install pyglet

import math
import random

import pyglet
from pyglet import shapes

pyglet.options["shadow_window"] = False

import config
from config import SCREEN_W, SCREEN_H, FPS, WAVE_COOLDOWN, MAP_CIRCLE, ENEMY_COLORS

from map import Room
from level import GameState as GameStateData, get_difficulty_mods, spawn_loot_on_enemy_death

from utils import set_view_size, compute_room_radius, Vec2, clamp_to_map, enemy_behavior_name, iso_to_world, dist, point_segment_distance

from visuals import Visuals, GroupCache
from weapons import get_weapon_for_wave, get_effective_fire_rate

from particles import ParticleSystem
from menu import (
    Menu,
    SettingsMenu,
    GuideMenu,
    PauseMenu,
    GameOverMenu,
    UI_FONT_META,
)
from rpg import (
    BossRewardMenu,
    recompute_temp_mods,
    advance_temp_rewards,
    apply_temp_reward as rpg_apply_temp,
    apply_perm_reward as rpg_apply_perm,
    roll_boss_rewards as rpg_roll_rewards
)
from hazards import LaserBeam
from layout import generate_obstacles
from logic import BalanceLogic
from player import Player, perform_dash

from fsm import StateMachine
from advanced_fx import AdvancedFX
from score import ScoreTracker
from hud import HUD
from states import (
    MenuState,
    SettingsState,
    GuideState,
    PlayingState,
    PausedState,
    BossRewardState,
    GameOverState
)





# ============================
# Main Game Class
# ============================
class Game(pyglet.window.Window):
    """Main game window and logic."""

    def __init__(self):
        super().__init__(width=SCREEN_W, height=SCREEN_H, caption="PLOUTO // Stellar Survival", vsync=True)
        for event_name in ("on_activate", "on_deactivate"):
            type(self).register_event_type(event_name)
        set_view_size(self.width, self.height)
        self._display_size = self._get_display_size()
        if self._display_size:
            dw, dh = self._display_size
            if self.width > dw or self.height > dh:
                self.set_size(min(self.width, dw), min(self.height, dh))
        self._update_room_radius_from_view()
        
        self.settings = {
            "difficulty": "normal",
            "window_size": (self.width, self.height),
            "fullscreen": True,
            "arena_margin": float(getattr(config, "ARENA_MARGIN", 0.97)),
            "advanced_fx": bool(getattr(config, "ENABLE_ADVANCED_FX", True)),
            "map_type": MAP_CIRCLE,
        }
        self._windowed_size = (self.width, self.height)
        
        # Menu system
        self.main_menu = Menu(self.width, self.height)
        self.settings_menu = SettingsMenu(
            self.width,
            self.height,
            self._on_settings_change,
            display_size=self._display_size,
            advanced_fx_enabled=bool(self.settings.get("advanced_fx", True)),
            map_type=self.settings.get("map_type", MAP_CIRCLE),
        )
        self.guide_menu = GuideMenu(self.width, self.height)
        self.pause_menu = PauseMenu(self.width, self.height)
        self.rpg_menu = BossRewardMenu(self.width, self.height, self._apply_temp_reward, self._apply_perm_reward)
        self.game_over_menu = GameOverMenu(self.width, self.height)
        
        # Game objects (will be initialized when game starts)
        self.batch = None
        self.groups = None
        self.room = None
        self.state = None
        self.player = None
        self.visuals = None
        self.particle_system = None
        
        self.keys = pyglet.window.key.KeyStateHandler()
        self.push_handlers(self.keys)

        self.mouse_xy = (self.width / 2, self.height / 2)
        self.mouse_down = False
        self._rmb_down = False
        self.auto_shoot = False
        self.balance = BalanceLogic(fps=float(FPS))
        self._fixed_dt = self.balance.fixed_dt
        self._frame_dt_cap = self.balance.frame_dt_cap
        self._max_catchup_steps = self.balance.max_catchup_steps
        self._accumulator = 0.0
        self._render_time = 0.0
        self.advanced_fx = AdvancedFX(self.width, self.height)
        self.advanced_fx.enabled = bool(self.settings.get("advanced_fx", True))

        # Cached UI labels to avoid per-frame allocations.
        self._pause_hint = pyglet.text.Label(
            "Press ESC to pause",
            font_name=UI_FONT_META,
            font_size=11,
            x=self.width - 10,
            y=self.height - 14,
            anchor_x="right",
            anchor_y="top",
            color=(168, 186, 206, 210),
        )

        pyglet.clock.schedule_interval(self.update, 1.0 / FPS)

        self.fsm = StateMachine(MenuState(self))
        self.fsm.add_state(SettingsState(self))
        self.fsm.add_state(GuideState(self))
        self.fsm.add_state(PlayingState(self))
        self.fsm.add_state(PausedState(self))
        self.fsm.add_state(BossRewardState(self))
        self.fsm.add_state(GameOverState(self))
        self._enable_startup_fullscreen()

    def _enable_startup_fullscreen(self) -> None:
        """Start in fullscreen while preserving the current windowed size."""
        self.settings["window_size"] = (self.width, self.height)
        self._windowed_size = (self.width, self.height)
        self.settings_menu.window_size_idx = len(self.settings_menu.window_sizes) - 1
        self._on_settings_change({"fullscreen": True, "window_size": self._windowed_size})

    def _reset_input_flags(self) -> None:
        self.mouse_down = False
        self._rmb_down = False

    def _get_display_size(self):
        try:
            display = pyglet.canvas.get_display()
            screen = display.get_default_screen()
            return (int(screen.width), int(screen.height))
        except Exception:
            return None

    def _update_room_radius_from_view(self):
        margin = float(getattr(config, "ARENA_MARGIN", 0.92))
        config.ROOM_RADIUS = compute_room_radius(self.width, self.height, margin=margin)

    def _prune_dead_weak_handlers(self) -> None:
        """Remove collected WeakMethod handlers to prevent pyglet assertions on dispatch."""
        from pyglet.event import WeakMethod

        stack = getattr(self, "_event_stack", None)
        if not stack:
            return

        for frame in list(stack):
            if not isinstance(frame, dict):
                continue
            for event_name, handler in list(frame.items()):
                is_pyglet_weakmethod = isinstance(handler, WeakMethod)
                is_weakmethod_like = (
                    handler.__class__.__name__ == "WeakMethod"
                    and callable(getattr(handler, "__call__", None))
                )
                if (is_pyglet_weakmethod or is_weakmethod_like) and handler() is None:
                    del frame[event_name]

    def dispatch_event(self, *args):
        self._prune_dead_weak_handlers()
        try:
            return super().dispatch_event(*args)
        except AssertionError:
            if args and args[0] in ("on_activate", "on_deactivate"):
                return False
            raise
    
    def _init_game(self):
        """Initialize game objects."""
        self.batch = pyglet.graphics.Batch()
        self.groups = GroupCache()
        self.room = Room(self.batch, self.width, self.height, map_type=self.settings.get("map_type", MAP_CIRCLE))

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
                self.state.layout_seed, self.state.layout_segment, config.ROOM_RADIUS, difficulty=self.state.difficulty
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

        self.visuals = Visuals(self.batch, self.groups)
        self.visuals.make_player()
        
        self.particle_system = ParticleSystem()

        self.score = ScoreTracker(difficulty=difficulty)
        self.hud = HUD(self.width, self.height)




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
            self._active_temp_rewards, self._last_reward_temp_key, self._last_reward_perm_key
        )
        self.rpg_menu.begin(temp_opts, perm_opts)

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
            self.player, self._run_permanent_rewards, k,
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

    def _regen_layout(self, segment: int | None = None):
        if not config.ENABLE_OBSTACLES:
            if self.state:
                self.state.obstacles = []
            return
        if not self.state:
            return
        if segment is None:
            segment = int(getattr(self.state, "layout_segment", 0))
        # Drop visuals for old obstacles.
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

    def _damage_player(self, amount: int):
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
            if getattr(self, 'score', None):
                self.score.on_player_hit()

    def _use_ultra(self):
        if not self.state or not self.player:
            return

        s = self.state
        if getattr(self.player, "ultra_charges", 0) <= 0:
            return
        if s.time < getattr(self.player, "ultra_cd_until", 0.0):
            return

        world_mouse = iso_to_world(self.mouse_xy)
        aim = (world_mouse - self.player.pos).normalized()
        if aim.length() <= 1e-6:
            aim = Vec2(1.0, 0.0)

        muzzle = self.player.pos + aim * 14.0
        dmg = int(config.ULTRA_DAMAGE_BASE + self._effective_player_damage() * config.ULTRA_DAMAGE_MULT)
        beam_thickness = float(config.ULTRA_BEAM_THICKNESS)
        beam_ttl = float(config.ULTRA_BEAM_TTL)

        def _hit_enemy(e, amount: int):
            e.hp -= int(amount)
            behavior_name = enemy_behavior_name(e)
            enemy_color = ENEMY_COLORS.get(behavior_name, (200, 200, 200))
            if self.particle_system:
                self.particle_system.add_hit_particles(e.pos, enemy_color)
            if e.hp <= 0:
                if e in s.enemies:
                    s.enemies.remove(e)
                if self.visuals:
                    self.visuals.drop_enemy(e)
                if self.particle_system:
                    self.particle_system.add_death_explosion(e.pos, enemy_color, behavior_name)
                spawn_loot_on_enemy_death(s, behavior_name, e.pos)
                if getattr(self, 'score', None):
                    self.score.on_enemy_kill(behavior_name)

        def _spawn_player_beam(start: Vec2, direction: Vec2, length: float, damage: int, thickness: float, color):
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
            for e in list(s.enemies):
                if point_segment_distance(e.pos, start, end) <= hit_r + self._enemy_radius(e):
                    _hit_enemy(e, int(damage))

        # Cycle variants for built-in variety while preserving predictable control.
        variant = int(getattr(self.player, "ultra_variant_idx", 0)) % 3
        self.player.ultra_variant_idx = (variant + 1) % 3

        if variant == 0:
            # Classic piercing beam.
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
            # Tri-beam spread for multi-target pressure.
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
            # Shockwave + forward finisher beam.
            blast_r = 160.0
            blast_dmg = int(dmg * 0.58)
            for e in list(s.enemies):
                if dist(e.pos, self.player.pos) <= blast_r:
                    _hit_enemy(e, blast_dmg)
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
        if getattr(self, "advanced_fx", None):
            self.advanced_fx.trigger_ultra(1.0)

    def _dash(self):
        if not self.state or not self.player:
            return
        world_mouse = iso_to_world(self.mouse_xy)
        did_dash = perform_dash(
            self.player, self.state.time, self.balance,
            float(getattr(self, "_dash_cd_difficulty", 1.0)),
            float(getattr(self, "_dash_cd_mult", 1.0)),
            self._input_dir(), world_mouse,
        )
        if did_dash:
            self.particle_system.add_dash_effect(self.player.pos, self.player.dash_direction)
            if getattr(self, "advanced_fx", None):
                self.advanced_fx.trigger_dash(0.7)

    def _enemy_radius(self, enemy) -> float:
        return self.balance.enemy_radius(enemy_behavior_name(enemy))

    def _player_radius(self) -> float:
        return self.balance.player_radius

    def _projectile_radius(self, projectile) -> float:
        ptype = str(getattr(projectile, "projectile_type", "bullet"))
        return self.balance.projectile_radius(ptype)

    @staticmethod
    def _ultra_variant_name(player) -> str:
        names = ("Beam", "Tri-Beam", "Shockwave")
        idx = int(getattr(player, "ultra_variant_idx", 0)) % len(names)
        return names[idx]

    def _quit_game(self):
        """Quit the game."""
        self._schedule_app_close()

    def _schedule_app_close(self):
        def _close(_dt):
            self.close()
            pyglet.app.exit()
        pyglet.clock.schedule_once(_close, 0)

    @staticmethod
    def _coerce_bool(value, default: bool = True) -> bool:
        """Parse common bool-ish values safely (including string forms)."""
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
    
    def _on_settings_change(self, value):
        """Callback for settings changes."""
        if not isinstance(value, dict):
            return
        self.settings.update(value)
        advanced_fx = value.get("advanced_fx")
        if advanced_fx is not None:
            fx_enabled = self._coerce_bool(advanced_fx, default=bool(getattr(config, "ENABLE_ADVANCED_FX", True)))
            self.settings["advanced_fx"] = fx_enabled
            config.ENABLE_ADVANCED_FX = fx_enabled
            if getattr(self, "advanced_fx", None):
                self.advanced_fx.enabled = fx_enabled
            if getattr(self, "settings_menu", None):
                self.settings_menu.advanced_fx = fx_enabled
                self.settings_menu._refresh_fx_button_text()
        fullscreen = value.get("fullscreen")
        arena_margin = value.get("arena_margin")
        if arena_margin is not None:
            config.ARENA_MARGIN = float(arena_margin)
            self._update_room_radius_from_view()
            if self.room:
                self.room.rebuild(map_type=self.settings.get("map_type"))
            if self.player:
                # clamp_to_map not imported here, but usually this just resets pos if out of bounds.
                # simpler to just let next update loop handle it or ignore.
                pass
        
        map_type = value.get("map_type")
        if map_type:
            self.settings["map_type"] = map_type
            if self.room:
                self.room.rebuild(map_type=map_type)
            # If in game, we should update state too?
            if self.state:
                self.state.map_type = map_type

        if fullscreen is True:
            if not self.fullscreen:
                self._windowed_size = (self.width, self.height)
            self.set_fullscreen(True)
            return

        if fullscreen is False and self.fullscreen:
            self.set_fullscreen(False)

        size = value.get("window_size")
        if size is None and not self.fullscreen:
            size = self._windowed_size
        if size and isinstance(size, (tuple, list)) and len(size) == 2:
            w, h = int(size[0]), int(size[1])
            if self._display_size:
                dw, dh = self._display_size
                w = min(w, dw)
                h = min(h, dh)
            if w > 0 and h > 0 and (w != self.width or h != self.height):
                self.set_size(w, h)

    def on_resize(self, width, height):
        super().on_resize(width, height)
        is_fullscreen = bool(getattr(self, "fullscreen", False))
        self.settings["fullscreen"] = is_fullscreen
        if not is_fullscreen:
            self.settings["window_size"] = (width, height)
            self._windowed_size = (width, height)
        if not isinstance(self.fsm.current_state, PlayingState):
            self.mouse_xy = (width / 2, height / 2)
        set_view_size(width, height)
        self._update_room_radius_from_view()

        self.main_menu.resize(width, height)
        self.settings_menu.resize(width, height)
        self.guide_menu.resize(width, height)
        self.pause_menu.resize(width, height)
        self.rpg_menu.resize(width, height)
        self.game_over_menu.resize(width, height)

        if getattr(self, "_pause_hint", None):
            self._pause_hint.x = width - 10
            self._pause_hint.y = height - 14
        if getattr(self, "hud", None):
            self.hud.layout(width, height)

        if self.room:
            self.room.resize(width, height)
        if self.state:
            if config.ENABLE_OBSTACLES:
                self._regen_layout(getattr(self.state, "layout_segment", 0))
        if getattr(self, "advanced_fx", None):
            self.advanced_fx.resize(width, height)
    
    def _return_to_menu(self):
        """Return to main menu."""
        # Clean up game objects
        if self.batch:
            self.batch = None
        self.groups = None
        self.room = None
        self.state = None
        self.player = None
        self.visuals = None
        self.particle_system = None

    def on_mouse_motion(self, x, y, dx, dy):
        self.mouse_xy = (x, y)
        self.fsm.on_mouse_motion(x, y, dx, dy)

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        self.fsm.on_mouse_drag(x, y, dx, dy, buttons, modifiers)

    def on_mouse_press(self, x, y, button, modifiers):
        self.fsm.on_mouse_press(x, y, button, modifiers)

    def on_mouse_release(self, x, y, button, modifiers):
        self.fsm.on_mouse_release(x, y, button, modifiers)
    
    def on_key_press(self, symbol, modifiers):
        """Handle key presses."""
        self.fsm.on_key_press(symbol, modifiers)

    def on_close(self):
        """Handle window close event."""
        self._schedule_app_close()
        return True

    def _input_dir(self) -> Vec2:
        """Get input direction from keyboard.
        
        Isometric controls:
        W: Northeast, S: Southwest, A: Northwest, D: Southeast
        """
        k = pyglet.window.key
        d = Vec2(0.0, 0.0)
        # W: Move northeast (x+, y+)
        if self.keys[k.W] or self.keys[k.UP]:
            d.x += 1
            d.y += 1
        # S: Move southwest (x-, y-)
        if self.keys[k.S] or self.keys[k.DOWN]:
            d.x -= 1
            d.y -= 1
        # A: Move northwest (x-, y+)
        if self.keys[k.A] or self.keys[k.LEFT]:
            d.x -= 1
            d.y += 1
        # D: Move southeast (x+, y-)
        if self.keys[k.D] or self.keys[k.RIGHT]:
            d.x += 1
            d.y -= 1
        return d

    def update(self, dt: float):
        """Update game logic."""
        frame_dt = max(0.0, min(float(dt), self._frame_dt_cap))
        self._render_time += frame_dt
        self._accumulator += frame_dt
        steps = 0
        while self._accumulator >= self._fixed_dt and steps < self._max_catchup_steps:
            self.fsm.update(self._fixed_dt)
            self._accumulator -= self._fixed_dt
            steps += 1
        if steps >= self._max_catchup_steps:
            # Drop extra accumulated time to avoid spiral-of-death stalls.
            self._accumulator = 0.0

    def on_draw(self):
        """Render the game."""
        self.clear()
        self.fsm.draw()
        ci = float(getattr(getattr(self, "room", None), "combat_intensity", 0.0))
        hp_ratio = 1.0
        boss_active = False
        if getattr(self, "player", None):
            hp_max = max(1, int(getattr(self.player, "max_hp", 100)))
            hp_ratio = max(0.0, min(1.0, float(getattr(self.player, "hp", hp_max)) / float(hp_max)))
        if getattr(self, "state", None):
            boss_active = any(enemy_behavior_name(e).startswith("boss_") for e in getattr(self.state, "enemies", []))
        self.advanced_fx.render(self._render_time, ci, hp_ratio=hp_ratio, boss_active=boss_active)


def main():
    """Start the game."""
    try:
        _ = Game()
        pyglet.app.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print("Fatal error:", e)
        raise


if __name__ == "__main__":
    main()
