# Pyglet isometric room survival prototype
# Controls: WASD/Arrows move, hold Left Mouse to shoot, ESC for menu.
# Install: py -m pip install pyglet

import random
import math

import pyglet

pyglet.options["shadow_window"] = False

import config
from config import SCREEN_W, SCREEN_H, FPS, WAVE_COOLDOWN, HUD_TEXT, ENEMY_COLORS, POWERUP_COLORS
from player import Player
from map import Room
from level import GameState as GameStateData, spawn_wave, maybe_spawn_powerup, spawn_loot_on_enemy_death
from enemy import update_enemy
from powerup import apply_powerup
from utils import (
    Vec2,
    clamp_to_room,
    iso_to_world,
    dist,
    set_view_size,
    compute_room_radius,
    point_segment_distance,
    resolve_circle_obstacles,
    enemy_behavior_name,
)
from visuals import Visuals, GroupCache
from weapons import get_weapon_for_wave, spawn_weapon_projectiles, get_effective_fire_rate
from particles import ParticleSystem
from menu import Menu, SettingsMenu, PauseMenu, GameOverMenu, UpgradeMenu
from hazards import LaserBeam
from layout import generate_obstacles
from fsm import State, StateMachine


def _draw_playing_scene(game) -> None:
    game.fsm._states["PlayingState"].draw()


class MenuState(State):
    def enter(self):
        self.game._reset_input_flags()

    def on_mouse_press(self, x, y, button, modifiers):
        action = self.game.main_menu.on_mouse_press(x, y, button)
        if action == "start_game":
            self.game._init_game()
            self.game.fsm.set_state("PlayingState")
        elif action == "settings":
            self.game.fsm.set_state("SettingsState")
        elif action == "quit":
            self.game._quit_game()

    def on_mouse_motion(self, x, y, dx, dy):
        self.game.main_menu.on_mouse_motion(x, y)

    def update(self, dt: float):
        self.game.main_menu.update(dt)

    def draw(self):
        self.game.main_menu.draw()


class SettingsState(State):
    def on_mouse_press(self, x, y, button, modifiers):
        action = self.game.settings_menu.on_mouse_press(x, y, button)
        if action == "back":
            self.game.fsm.set_state("MenuState")

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        self.game.settings_menu.on_mouse_drag(x, y, dx, dy)

    def on_mouse_motion(self, x, y, dx, dy):
        self.game.settings_menu.on_mouse_motion(x, y)

    def on_mouse_release(self, x, y, button, modifiers):
        self.game.settings_menu.on_mouse_release(x, y, button)

    def on_key_press(self, symbol, modifiers):
        if symbol == pyglet.window.key.ESCAPE:
            self.game.fsm.set_state("MenuState")

    def update(self, dt: float):
        self.game.settings_menu.update(dt)

    def draw(self):
        self.game.settings_menu.draw()


class PlayingState(State):
    def enter(self):
        if not self.game.state:
            self.game._init_game()
        self.game._reset_input_flags()

    def on_key_press(self, symbol, modifiers):
        if symbol == pyglet.window.key.ESCAPE:
            self.game.fsm.set_state("PausedState")
        elif symbol == pyglet.window.key.Q:
            self.game._use_ultra()

    def on_mouse_press(self, x, y, button, modifiers):
        self.game.mouse_xy = (x, y)
        if button == pyglet.window.mouse.LEFT:
            self.game.mouse_down = True
        elif button == pyglet.window.mouse.RIGHT:
            self.game._rmb_down = True
            self.game._use_ultra()

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        self.game.mouse_xy = (x, y)
        rmb_pressed = bool(buttons & pyglet.window.mouse.RIGHT)
        if rmb_pressed and not self.game._rmb_down:
            self.game._use_ultra()
        self.game._rmb_down = rmb_pressed

    def on_mouse_release(self, x, y, button, modifiers):
        if button == pyglet.window.mouse.LEFT:
            self.game.mouse_down = False
        elif button == pyglet.window.mouse.RIGHT:
            self.game._rmb_down = False

    @staticmethod
    def _remove_projectile(game, s, p) -> None:
        if p in s.projectiles:
            s.projectiles.remove(p)
        game.visuals.drop_projectile(p)

    @staticmethod
    def _is_enemy_bomb(p) -> bool:
        return p.owner == "enemy" and str(getattr(p, "projectile_type", "bullet")) == "bomb"

    def _explode_enemy_bomb(self, game, s, p) -> None:
        blast_r = 72.0
        blast_dmg = max(10, int(getattr(p, "damage", 0)))
        if game.particle_system:
            game.particle_system.add_death_explosion(p.pos, (255, 145, 90), "bomber")
        if dist(p.pos, game.player.pos) <= blast_r:
            game._damage_player(blast_dmg)
            s.shake = max(s.shake, 12.0)

    def update(self, dt: float):
        game = self.game
        if not game.state:
            return

        s = game.state
        s.time += dt

        if not s.wave_active and (s.time - s.last_wave_clear) >= WAVE_COOLDOWN:
            spawn_wave(s, Vec2(0.0, 0.0))

        if s.time < game.player.vortex_until:
            game.particle_system.add_vortex_swirl(game.player.pos, s.time, game.player.vortex_radius)
            dps = game.player.vortex_dps
            for e in list(s.enemies):
                if dist(e.pos, game.player.pos) <= game.player.vortex_radius:
                    acc = getattr(e, "_vortex_acc", 0.0) + dps * dt
                    dmg = int(acc)
                    e._vortex_acc = acc - dmg
                    if dmg > 0:
                        e.hp -= dmg
                        s.shake = max(s.shake, 2.5)
                        if e.hp <= 0:
                            s.enemies.remove(e)
                            game.visuals.drop_enemy(e)
                            spawn_loot_on_enemy_death(s, enemy_behavior_name(e), e.pos)

        for tr in list(getattr(s, "traps", [])):
            tr.t += dt
            tr.ttl -= dt
            if tr.ttl <= 0:
                s.traps.remove(tr)
                game.visuals.drop_trap(tr)
                continue
            if tr.damage > 0 and tr.t >= tr.armed_delay and dist(tr.pos, game.player.pos) <= tr.radius:
                game._damage_player(tr.damage)
                s.shake = max(s.shake, 10.0)
                s.traps.remove(tr)
                game.visuals.drop_trap(tr)

        for th in list(getattr(s, "thunders", [])):
            th.t += dt
            if th.t >= th.warn and not th.hit_done:
                if point_segment_distance(game.player.pos, th.start, th.end) <= th.thickness * 0.6:
                    th.hit_done = True
                    game._damage_player(th.damage)
                    s.shake = max(s.shake, 14.0)
                    game.particle_system.add_laser_beam(th.start, th.end, color=th.color)
            if th.t >= th.warn + th.ttl:
                s.thunders.remove(th)
                game.visuals.drop_thunder(th)

        old_pos = Vec2(game.player.pos.x, game.player.pos.y)
        idir = game._input_dir()
        if idir.length() > 0:
            nd = idir.normalized()
            game.player.pos = game.player.pos + nd * game.player.speed * dt
            game.particle_system.add_step_dust(game.player.pos, nd)
        game.player.pos = clamp_to_room(game.player.pos, config.ROOM_RADIUS * 0.9)
        if config.ENABLE_OBSTACLES and getattr(s, "obstacles", None):
            game.player.pos = resolve_circle_obstacles(game.player.pos, 14.0, s.obstacles)
            game.player.pos = clamp_to_room(game.player.pos, config.ROOM_RADIUS * 0.9)
        if dt > 1e-6:
            player_vel = (game.player.pos - old_pos) * (1.0 / dt)
        else:
            player_vel = Vec2(0.0, 0.0)

        weapon_cd = get_effective_fire_rate(game.player.current_weapon, game.player.fire_rate)
        if game.mouse_down and (s.time - game.player.last_shot) >= weapon_cd:
            world_mouse = iso_to_world(game.mouse_xy)
            aim = (world_mouse - game.player.pos).normalized()
            muzzle = game.player.pos + aim * 14.0

            if s.time < game.player.laser_until:
                beam_len = config.ROOM_RADIUS * 1.6
                end = muzzle + aim * beam_len
                dmg = int(game.player.damage * 0.9) + 14
                beam = LaserBeam(start=muzzle, end=end, damage=dmg, thickness=12.0, ttl=0.08, owner="player")
                s.lasers.append(beam)
                game.particle_system.add_laser_beam(muzzle, end, color=beam.color)
                for e in list(s.enemies):
                    if point_segment_distance(e.pos, muzzle, end) <= 14:
                        e.hp -= dmg
                        s.shake = max(s.shake, 4.0)
                        if e.hp <= 0:
                            s.enemies.remove(e)
                            game.visuals.drop_enemy(e)
                            spawn_loot_on_enemy_death(s, enemy_behavior_name(e), e.pos)
            else:
                weapon = game.player.current_weapon
                projectiles = spawn_weapon_projectiles(muzzle, aim, weapon, s.time, game.player.damage)
                s.projectiles.extend(projectiles)

            game.particle_system.add_muzzle_flash(muzzle, aim)
            game.player.last_shot = s.time

        for e in list(s.enemies):
            update_enemy(e, game.player.pos, s, dt, game, player_vel=player_vel)
            e.pos = clamp_to_room(e.pos, config.ROOM_RADIUS * 0.96)
            if config.ENABLE_OBSTACLES and getattr(s, "obstacles", None):
                e.pos = resolve_circle_obstacles(e.pos, game._enemy_radius(e), s.obstacles)
                e.pos = clamp_to_room(e.pos, config.ROOM_RADIUS * 0.96)
            if dist(e.pos, game.player.pos) < 12:
                game._damage_player(10)
                s.enemies.remove(e)
                game.visuals.drop_enemy(e)
                s.shake = 9.0
                spawn_loot_on_enemy_death(s, enemy_behavior_name(e), game.player.pos)

        for p in list(s.projectiles):
            p.pos = p.pos + p.vel * dt
            p.ttl -= dt
            if config.ENABLE_OBSTACLES and getattr(s, "obstacles", None):
                blocked = False
                for ob in s.obstacles:
                    if dist(p.pos, ob.pos) <= ob.radius:
                        blocked = True
                        break
                if blocked:
                    if self._is_enemy_bomb(p):
                        self._explode_enemy_bomb(game, s, p)
                    self._remove_projectile(game, s, p)
                    game.particle_system.add_hit_particles(p.pos, (160, 160, 170))
                    continue
            if p.ttl <= 0:
                if self._is_enemy_bomb(p):
                    self._explode_enemy_bomb(game, s, p)
                self._remove_projectile(game, s, p)
                continue

        for p in list(s.projectiles):
            if p.owner == "player":
                ptype = str(getattr(p, "projectile_type", "bullet"))
                hit_r = 16.0 if ptype == "missile" else 12.0 if ptype == "plasma" else 11.0
                for e in list(s.enemies):
                    if dist(p.pos, e.pos) < hit_r:
                        e.hp -= p.damage
                        s.shake = max(s.shake, 4.0)

                        behavior_name = enemy_behavior_name(e)
                        enemy_color = ENEMY_COLORS.get(behavior_name, (200, 200, 200))
                        game.particle_system.add_hit_particles(e.pos, enemy_color)

                        if e.hp <= 0:
                            s.enemies.remove(e)
                            game.visuals.drop_enemy(e)
                            game.particle_system.add_death_explosion(e.pos, enemy_color, behavior_name)
                            if behavior_name == "tank" and dist(e.pos, game.player.pos) < 70:
                                game._damage_player(15)
                                s.shake = 15.0
                            spawn_loot_on_enemy_death(s, behavior_name, e.pos)
                        self._remove_projectile(game, s, p)
                        break
            else:
                ptype = str(getattr(p, "projectile_type", "bullet"))
                if ptype == "bomb":
                    if dist(p.pos, game.player.pos) < 18:
                        self._explode_enemy_bomb(game, s, p)
                        self._remove_projectile(game, s, p)
                elif dist(p.pos, game.player.pos) < 12:
                    game._damage_player(p.damage)
                    s.shake = max(s.shake, 6.0)
                    self._remove_projectile(game, s, p)

        for pu in list(s.powerups):
            dpu = dist(pu.pos, game.player.pos)
            kind = getattr(pu, "kind", "")
            is_special = kind in ("weapon", "ultra")
            magnet_r = 190.0 if is_special else 150.0
            if dpu < magnet_r and dpu > 1e-6:
                pull = (game.player.pos - pu.pos).normalized()
                pull_speed = 220.0 + (magnet_r - dpu) * 2.0
                pu.pos = pu.pos + pull * pull_speed * dt
                dpu = dist(pu.pos, game.player.pos)

            pickup_r = 20.0 if is_special else 16.0
            if dpu < pickup_r:
                color = POWERUP_COLORS.get(pu.kind, (200, 200, 200))
                game.particle_system.add_powerup_collection(pu.pos, color)
                apply_powerup(game.player, pu, s.time)
                s.powerups.remove(pu)
                game.visuals.drop_powerup(pu)

        if s.wave_active and not s.enemies:
            cleared_wave = int(s.wave)
            s.wave_active = False
            s.last_wave_clear = s.time
            s.wave += 1
            new_segment = (s.wave - 1) // 5
            if config.ENABLE_OBSTACLES and new_segment != getattr(s, "layout_segment", 0):
                game._regen_layout(new_segment)
            game.player.current_weapon = get_weapon_for_wave(s.wave)
            maybe_spawn_powerup(s, Vec2(0.0, 0.0))

            if cleared_wave % 3 == 0:
                game._roll_upgrade_options()
                game.fsm.set_state("UpgradeState")

        if s.shake > 0:
            s.shake = max(0.0, s.shake - dt * 20)

        game.particle_system.update(dt)
        if game.room:
            game.room.update(dt)

        for lb in list(getattr(s, "lasers", [])):
            lb.t += dt
            if lb.owner == "enemy" and lb.t >= lb.warn and not lb.hit_done:
                if point_segment_distance(game.player.pos, lb.start, lb.end) <= lb.thickness * 0.55:
                    lb.hit_done = True
                    game._damage_player(lb.damage)
                    s.shake = max(s.shake, 10.0)
                    game.particle_system.add_laser_beam(lb.start, lb.end, color=lb.color)
            if lb.t >= lb.warn + lb.ttl:
                s.lasers.remove(lb)
                game.visuals.drop_laser(lb)

        if game.player.hp <= 0:
            game.fsm.set_state("GameOverState")

    def draw(self):
        game = self.game
        if not game.state:
            return

        s = game.state
        shake = Vec2(0.0, 0.0)
        if s.shake > 0:
            shake = Vec2(random.uniform(-1, 1), random.uniform(-1, 1)) * s.shake

        if config.ENABLE_OBSTACLES:
            for ob in getattr(game.state, "obstacles", []):
                game.visuals.ensure_obstacle(ob)
                game.visuals.sync_obstacle(ob, shake)

        aim_dir = (iso_to_world(game.mouse_xy) - game.player.pos).normalized()
        game.visuals.sync_player(game.player, shake, t=s.time, aim_dir=aim_dir)

        for e in game.state.enemies:
            game.visuals.ensure_enemy(e)
            game.visuals.sync_enemy(e, shake)

        for p in game.state.projectiles:
            game.visuals.ensure_projectile(p)
            game.visuals.sync_projectile(p, shake)

        for pu in game.state.powerups:
            game.visuals.ensure_powerup(pu)
            game.visuals.sync_powerup(pu, shake)

        for tr in getattr(game.state, "traps", []):
            game.visuals.ensure_trap(tr)
            game.visuals.sync_trap(tr, shake)

        for lb in getattr(game.state, "lasers", []):
            game.visuals.ensure_laser(lb)
            game.visuals.sync_laser(lb, shake)

        for th in getattr(game.state, "thunders", []):
            game.visuals.ensure_thunder(th)
            game.visuals.sync_thunder(th, shake)

        game.batch.draw()
        game.particle_system.render(shake)

        laser_left = max(0.0, game.player.laser_until - game.state.time)
        laser_txt = f"   Laser: {laser_left:.0f}s" if laser_left > 0 else ""
        vortex_left = max(0.0, game.player.vortex_until - game.state.time)
        vortex_txt = f"   Vortex: {vortex_left:.0f}s" if vortex_left > 0 else ""
        ultra_charges = int(getattr(game.player, "ultra_charges", 0))
        ultra_cd = max(0.0, float(getattr(game.player, "ultra_cd_until", 0.0)) - game.state.time)
        ultra_txt = ""
        if ultra_charges > 0:
            ultra_txt = f"   Ultra: {ultra_charges} [{game._ultra_variant_name(game.player)}]"
            if ultra_cd > 0:
                ultra_txt += f" ({ultra_cd:.0f}s)"
        boss = next((e for e in game.state.enemies if enemy_behavior_name(e).startswith("boss_")), None)
        boss_txt = ""
        if boss:
            boss_name = enemy_behavior_name(boss)
            boss_txt = f"   BOSS: {boss_name[5:].replace('_', ' ').title()} HP:{boss.hp}"
        diff_txt = f"   Diff: {str(getattr(game.state, 'difficulty', 'normal')).capitalize()}"
        hp_cap = int(getattr(game.player, "max_hp", game.player.hp))
        game.hud.text = f"HP: {game.player.hp}/{hp_cap}   Shield: {game.player.shield}   Wave: {game.state.wave}   Enemies: {len(game.state.enemies)}   Weapon: {game.player.current_weapon.name.capitalize()}{laser_txt}{vortex_txt}{ultra_txt}{boss_txt}{diff_txt}"
        game.hud.draw()

        if game._pause_hint:
            game._pause_hint.draw()


class PausedState(State):
    def enter(self):
        self.game._reset_input_flags()

    def on_key_press(self, symbol, modifiers):
        if symbol == pyglet.window.key.ESCAPE:
            self.game.fsm.set_state("PlayingState")

    def on_mouse_press(self, x, y, button, modifiers):
        action = self.game.pause_menu.on_mouse_press(x, y, button)
        if action == "resume":
            self.game.fsm.set_state("PlayingState")
        elif action == "quit_to_menu":
            self.game._return_to_menu()
            self.game.fsm.set_state("MenuState")

    def on_mouse_motion(self, x, y, dx, dy):
        self.game.pause_menu.on_mouse_motion(x, y)

    def draw(self):
        _draw_playing_scene(self.game)
        self.game.pause_menu.draw()


class UpgradeState(State):
    def enter(self):
        self.game._reset_input_flags()

    def on_mouse_press(self, x, y, button, modifiers):
        chosen = self.game.upgrade_menu.on_mouse_press(x, y, button)
        if chosen:
            self.game._apply_run_upgrade(chosen)
            if self.game.state:
                self.game.state.last_wave_clear = self.game.state.time - float(WAVE_COOLDOWN)
            self.game.fsm.set_state("PlayingState")

    def on_mouse_motion(self, x, y, dx, dy):
        self.game.upgrade_menu.on_mouse_motion(x, y)

    def draw(self):
        _draw_playing_scene(self.game)
        self.game.upgrade_menu.draw()


class GameOverState(State):
    def enter(self):
        self.game.game_over_menu.set_wave(self.game.state.wave)
        self.game._reset_input_flags()

    def on_mouse_press(self, x, y, button, modifiers):
        action = self.game.game_over_menu.on_mouse_press(x, y, button)
        if action == "retry":
            self.game._init_game()
            self.game.fsm.set_state("PlayingState")
        elif action == "quit_to_menu":
            self.game._return_to_menu()
            self.game.fsm.set_state("MenuState")

    def on_mouse_motion(self, x, y, dx, dy):
        self.game.game_over_menu.on_mouse_motion(x, y)

    def draw(self):
        _draw_playing_scene(self.game)
        self.game.game_over_menu.draw()


# ============================
# Main Game Class
# ============================
class Game(pyglet.window.Window):
    """Main game window and logic."""

    def __init__(self):
        super().__init__(width=SCREEN_W, height=SCREEN_H, caption="Isometric Room Survival (pyglet)", vsync=True)
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
            "fullscreen": False,
            "arena_margin": float(getattr(config, "ARENA_MARGIN", 0.97)),
        }
        self._windowed_size = (self.width, self.height)
        
        # Menu system
        self.main_menu = Menu(self.width, self.height)
        self.settings_menu = SettingsMenu(self.width, self.height, self._on_settings_change, display_size=self._display_size)
        self.pause_menu = PauseMenu(self.width, self.height)
        self.upgrade_menu = UpgradeMenu(self.width, self.height)
        self.game_over_menu = GameOverMenu(self.width, self.height)
        
        # Game objects (will be initialized when game starts)
        self.batch = None
        self.groups = None
        self.room = None
        self.state = None
        self.player = None
        self.visuals = None
        self.particle_system = None
        self.hud = None
        
        self.keys = pyglet.window.key.KeyStateHandler()
        self.push_handlers(self.keys)

        self.mouse_xy = (self.width / 2, self.height / 2)
        self.mouse_down = False
        self._rmb_down = False

        # Cached UI labels to avoid per-frame allocations.
        self._pause_hint = pyglet.text.Label(
            "Press ESC to pause",
            font_name="Arial",
            font_size=10,
            x=self.width - 10,
            y=self.height - 14,
            anchor_x="right",
            anchor_y="top",
            color=(150, 150, 150, 200),
        )

        pyglet.clock.schedule_interval(self.update, 1.0 / FPS)

        self.fsm = StateMachine(MenuState(self))
        self.fsm.add_state(SettingsState(self))
        self.fsm.add_state(PlayingState(self))
        self.fsm.add_state(PausedState(self))
        self.fsm.add_state(UpgradeState(self))
        self.fsm.add_state(GameOverState(self))

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
        try:
            from pyglet.event import WeakMethod
        except Exception:
            return

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
        self.room = Room(self.batch, self.width, self.height)

        difficulty = str(self.settings.get("difficulty", "normal")).lower()
        self.state = GameStateData(difficulty=difficulty)
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

        self.visuals = Visuals(self.batch, self.groups)
        self.visuals.make_player()
        
        self.particle_system = ParticleSystem(self.batch)

        self.hud = pyglet.text.Label(
            "",
            font_name="Consolas",
            font_size=14,
            x=12,
            y=self.height - 14,
            anchor_x="left",
            anchor_y="top",
            color=(HUD_TEXT[0], HUD_TEXT[1], HUD_TEXT[2], 255),
        )

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
        if amount <= 0:
            return
        mult = getattr(self, "_incoming_damage_mult", 1.0)
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
        dmg = int(config.ULTRA_DAMAGE_BASE + self.player.damage * config.ULTRA_DAMAGE_MULT)
        beam_thickness = float(config.ULTRA_BEAM_THICKNESS)
        beam_ttl = float(config.ULTRA_BEAM_TTL)

        def _hit_enemy(e, amount: int):
            e.hp -= int(amount)
            behavior_name = enemy_behavior_name(e)
            enemy_color = ENEMY_COLORS.get(behavior_name, (200, 200, 200))
            if self.particle_system:
                self.particle_system.add_hit_particles(e.pos, enemy_color)
            if e.hp <= 0:
                s.enemies.remove(e)
                if self.visuals:
                    self.visuals.drop_enemy(e)
                if self.particle_system:
                    self.particle_system.add_death_explosion(e.pos, enemy_color, behavior_name)
                spawn_loot_on_enemy_death(s, behavior_name, e.pos)

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
            hit_r = float(thickness) * 0.75
            for e in list(s.enemies):
                if point_segment_distance(e.pos, start, end) <= hit_r:
                    _hit_enemy(e, int(damage))

        # Cycle variants for built-in variety while preserving predictable control.
        variant = int(getattr(self.player, "ultra_variant_idx", 0)) % 3
        self.player.ultra_variant_idx = variant + 1

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
        self.player.ultra_cd_until = s.time + float(config.ULTRA_COOLDOWN)

    def _enemy_radius(self, enemy) -> float:
        b = enemy_behavior_name(enemy)
        if b.startswith("boss_"):
            return 24.0
        return {
            "tank": 16.0,
            "swarm": 9.0,
            "flyer": 11.0,
            "engineer": 13.0,
            "charger": 13.0,
            "spitter": 12.0,
            "ranged": 12.0,
            "chaser": 12.0,
        }.get(b, 12.0)

    @staticmethod
    def _ultra_variant_name(player) -> str:
        names = ("Beam", "Tri-Beam", "Shockwave")
        idx = int(getattr(player, "ultra_variant_idx", 0)) % len(names)
        return names[idx]

    def _roll_upgrade_options(self) -> None:
        if not self.player:
            return

        p = self.player
        opts: list[dict] = []

        opts.append(
            {
                "key": "max_hp",
                "title": "Max HP +10",
                "desc": f"{int(getattr(p, 'max_hp', p.hp))} -> {int(getattr(p, 'max_hp', p.hp)) + 10}",
            }
        )
        opts.append({"key": "damage", "title": "Damage +2", "desc": f"{int(p.damage)} -> {int(p.damage) + 2}"})
        opts.append({"key": "speed", "title": "Move Speed +12", "desc": f"{int(p.speed)} -> {int(p.speed) + 12}"})

        fr_now = float(getattr(p, "fire_rate", 0.28))
        fr_new = max(0.14, fr_now - 0.01)
        if fr_new < fr_now - 1e-6:
            opts.append(
                {
                    "key": "fire_rate",
                    "title": "Faster Shots (-0.01s)",
                    "desc": f"{fr_now:.2f}s -> {fr_new:.2f}s (lower is faster)",
                }
            )

        sh_now = int(getattr(p, "shield", 0))
        sh_new = min(120, sh_now + 35)
        if sh_new > sh_now:
            opts.append({"key": "shield", "title": "Shield +35", "desc": f"{sh_now} -> {sh_new}"})

        if len(opts) <= 3:
            chosen = opts
        else:
            chosen = random.sample(opts, k=3)

        self.upgrade_menu.set_options(chosen)

    def _apply_run_upgrade(self, key: str) -> None:
        if not self.player:
            return
        k = str(key or "").strip().lower()
        p = self.player

        if k == "max_hp":
            cur = int(getattr(p, "max_hp", p.hp))
            p.max_hp = cur + 10
            p.hp = min(int(p.max_hp), int(p.hp) + 10)
        elif k == "damage":
            p.damage = int(p.damage) + 2
        elif k == "speed":
            p.speed = float(p.speed) + 12.0
        elif k == "fire_rate":
            p.fire_rate = max(0.14, float(p.fire_rate) - 0.01)
        elif k == "shield":
            p.shield = min(120, int(getattr(p, "shield", 0)) + 35)
        else:
            return

        if self.particle_system:
            self.particle_system.add_powerup_collection(p.pos, (200, 220, 255))
        if self.state:
            self.state.shake = max(self.state.shake, 4.0)
    
    def _quit_game(self):
        """Quit the game."""
        self._schedule_app_close()

    def _schedule_app_close(self):
        def _close(_dt):
            self.close()
            pyglet.app.exit()
        pyglet.clock.schedule_once(_close, 0)
    
    def _on_settings_change(self, value):
        """Callback for settings changes."""
        if not isinstance(value, dict):
            return
        self.settings.update(value)
        fullscreen = value.get("fullscreen")
        arena_margin = value.get("arena_margin")
        if arena_margin is not None:
            try:
                config.ARENA_MARGIN = float(arena_margin)
            except Exception:
                pass
            self._update_room_radius_from_view()
            if self.room:
                self.room.rebuild()
            if self.player:
                self.player.pos = clamp_to_room(self.player.pos, config.ROOM_RADIUS)

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
        self.pause_menu.resize(width, height)
        self.upgrade_menu.resize(width, height)
        self.game_over_menu.resize(width, height)

        if self.hud:
            self.hud.y = height - 14
        if getattr(self, "_pause_hint", None):
            self._pause_hint.x = width - 10
            self._pause_hint.y = height - 14

        if self.room:
            self.room.resize(width, height)
        if self.state:
            if config.ENABLE_OBSTACLES:
                self._regen_layout(getattr(self.state, "layout_segment", 0))
    
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
        self.fsm.update(dt)

    def on_draw(self):
        """Render the game."""
        self.clear()
        self.fsm.draw()


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
