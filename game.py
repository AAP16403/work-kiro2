# Pyglet isometric room survival prototype
# Controls: WASD/Arrows move, hold Left Mouse to shoot, ESC for menu.
# Install: py -m pip install pyglet

import random
import math

import pyglet
from pyglet import shapes

pyglet.options["shadow_window"] = False

import config
from config import SCREEN_W, SCREEN_H, FPS, WAVE_COOLDOWN, ENEMY_COLORS, POWERUP_COLORS
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
from menu import (
    Menu,
    SettingsMenu,
    GuideMenu,
    PauseMenu,
    GameOverMenu,
    UI_FONT_HEAD,
    UI_FONT_BODY,
    UI_FONT_META,
)
from rpg import BossRewardMenu
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
        elif action == "guide":
            self.game.fsm.set_state("GuideState")
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


class GuideState(State):
    def enter(self):
        self.game._reset_input_flags()

    def on_mouse_press(self, x, y, button, modifiers):
        action = self.game.guide_menu.on_mouse_press(x, y, button)
        if action == "back":
            self.game.fsm.set_state("MenuState")

    def on_mouse_motion(self, x, y, dx, dy):
        self.game.guide_menu.on_mouse_motion(x, y)

    def on_key_press(self, symbol, modifiers):
        if symbol == pyglet.window.key.ESCAPE:
            self.game.fsm.set_state("MenuState")
        else:
            self.game.guide_menu.on_key_press(symbol)

    def draw(self):
        self.game.guide_menu.draw()


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
            game.player.pos = game.player.pos + nd * game._effective_player_speed() * dt
            game.particle_system.add_step_dust(game.player.pos, nd)
        game.player.pos = clamp_to_room(game.player.pos, config.ROOM_RADIUS * 0.9)
        if config.ENABLE_OBSTACLES and getattr(s, "obstacles", None):
            game.player.pos = resolve_circle_obstacles(game.player.pos, 14.0, s.obstacles)
            game.player.pos = clamp_to_room(game.player.pos, config.ROOM_RADIUS * 0.9)
        if dt > 1e-6:
            player_vel = (game.player.pos - old_pos) * (1.0 / dt)
        else:
            player_vel = Vec2(0.0, 0.0)

        weapon_cd = get_effective_fire_rate(game.player.current_weapon, game._effective_player_fire_rate())
        if game.mouse_down and (s.time - game.player.last_shot) >= weapon_cd:
            world_mouse = iso_to_world(game.mouse_xy)
            aim = (world_mouse - game.player.pos).normalized()
            muzzle = game.player.pos + aim * 14.0

            if s.time < game.player.laser_until:
                beam_len = config.ROOM_RADIUS * 1.6
                end = muzzle + aim * beam_len
                dmg = int(game._effective_player_damage() * 0.9) + 14
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
                projectiles = spawn_weapon_projectiles(muzzle, aim, weapon, s.time, game._effective_player_damage())
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
            magnet_r = (190.0 if is_special else 150.0) + game._pickup_magnet_bonus
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
            game._advance_temp_rewards()
            new_segment = (s.wave - 1) // 5
            if config.ENABLE_OBSTACLES and new_segment != getattr(s, "layout_segment", 0):
                game._regen_layout(new_segment)
            game.player.current_weapon = get_weapon_for_wave(s.wave)
            maybe_spawn_powerup(s, Vec2(0.0, 0.0))

            if cleared_wave % 5 == 0:
                game._roll_boss_rewards()
                game.fsm.set_state("BossRewardState")

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

        # Update HUD
        hp_cap = max(1, int(getattr(game.player, "max_hp", 100)))
        hp_now = max(0, int(game.player.hp))
        hp_frac = max(0.0, min(1.0, hp_now / hp_cap))
        game.hud_hp_bar.width = game._hud_bar_w * hp_frac
        game.hud_hp_bar.color = (
            int(210 - 120 * hp_frac),
            int(80 + 155 * hp_frac),
            int(82 + 50 * hp_frac),
        )
        game.hud_hp_value_label.text = f"{hp_now}/{hp_cap}"

        shield_cap = 100
        shield_now = max(0, int(game.player.shield))
        shield_frac = max(0.0, min(1.0, shield_now / max(1, shield_cap)))
        game.hud_shield_bar.width = game._hud_bar_w * shield_frac
        game.hud_shield_bar.color = (
            int(48 + 36 * shield_frac),
            int(122 + 88 * shield_frac),
            int(202 + 42 * shield_frac),
        )
        game.hud_shield_value_label.text = f"{shield_now}/{shield_cap}"
        game.hud_wave_label.text = f"WAVE {int(game.state.wave):02d}"
        game.hud_meta_label.text = f"{str(getattr(game.state, 'difficulty', 'normal')).upper()}  T+{int(game.state.time):03d}s"

        laser_left = max(0.0, game.player.laser_until - game.state.time)
        laser_txt = f"Laser {laser_left:.0f}s" if laser_left > 0 else ""
        vortex_left = max(0.0, game.player.vortex_until - game.state.time)
        vortex_txt = f"Vortex {vortex_left:.0f}s" if vortex_left > 0 else ""
        ultra_charges = int(getattr(game.player, "ultra_charges", 0))
        ultra_cd = max(0.0, float(getattr(game.player, "ultra_cd_until", 0.0)) - game.state.time)
        ultra_txt = ""
        if ultra_charges > 0:
            ultra_txt = f"Ultra {ultra_charges} [{game._ultra_variant_name(game.player)}]"
            if ultra_cd > 0:
                ultra_txt += f" {ultra_cd:.0f}s"
        boss = next((e for e in game.state.enemies if enemy_behavior_name(e).startswith("boss_")), None)
        boss_txt = ""
        if boss:
            boss_name = enemy_behavior_name(boss)
            boss_txt = f"BOSS {boss_name[5:].replace('_', ' ').title()} HP {boss.hp}"
        
        temp_txt = game._active_temp_hud_text()
        perm_txt = game._perm_hud_text()
        status_parts = [p for p in (laser_txt, vortex_txt, ultra_txt, temp_txt, perm_txt, boss_txt) if p]
        status_text = "   |   ".join(status_parts) if status_parts else "No active effects"
        max_chars = int(getattr(game, "_hud_status_max_chars", 120))
        if len(status_text) > max_chars:
            status_text = status_text[: max(3, max_chars - 3)].rstrip() + "..."
        game.hud_status_label.text = status_text
        
        game.hud_batch.draw()

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


class BossRewardState(State):
    def enter(self):
        self.game._reset_input_flags()

    def on_mouse_press(self, x, y, button, modifiers):
        chosen = self.game.rpg_menu.on_mouse_press(x, y, button)
        if chosen == "done":
            if self.game.state:
                self.game.state.last_wave_clear = self.game.state.time - float(WAVE_COOLDOWN)
            self.game.fsm.set_state("PlayingState")

    def on_mouse_motion(self, x, y, dx, dy):
        self.game.rpg_menu.on_mouse_motion(x, y)

    def draw(self):
        _draw_playing_scene(self.game)
        self.game.rpg_menu.draw()


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
        }
        self._windowed_size = (self.width, self.height)
        
        # Menu system
        self.main_menu = Menu(self.width, self.height)
        self.settings_menu = SettingsMenu(self.width, self.height, self._on_settings_change, display_size=self._display_size)
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
        try:
            self.settings_menu.window_size_idx = len(self.settings_menu.window_sizes) - 1
            self._on_settings_change({"fullscreen": True, "window_size": self._windowed_size})
        except Exception:
            self.settings["fullscreen"] = False

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

        self.visuals = Visuals(self.batch, self.groups)
        self.visuals.make_player()
        
        self.particle_system = ParticleSystem()

        self._init_hud()

    def _init_hud(self):
        self.hud_batch = pyglet.graphics.Batch()
        self._hud_bar_w = 240

        self.hud_panel_shadow = shapes.Rectangle(0, 0, 1, 1, color=(0, 0, 0), batch=self.hud_batch)
        self.hud_panel_shadow.opacity = 78
        self.hud_panel_bg = shapes.Rectangle(0, 0, 1, 1, color=(14, 21, 30), batch=self.hud_batch)
        self.hud_panel_bg.opacity = 216
        self.hud_panel_border = shapes.BorderedRectangle(
            0, 0, 1, 1, border=2, color=(20, 28, 40), border_color=(82, 146, 212), batch=self.hud_batch
        )
        self.hud_panel_border.opacity = 228

        self.hud_hp_bar_bg = shapes.Rectangle(0, 0, 1, 1, color=(42, 45, 55), batch=self.hud_batch)
        self.hud_hp_bar = shapes.Rectangle(0, 0, 1, 1, color=(120, 210, 120), batch=self.hud_batch)
        self.hud_shield_bar_bg = shapes.Rectangle(0, 0, 1, 1, color=(36, 44, 58), batch=self.hud_batch)
        self.hud_shield_bar = shapes.Rectangle(0, 0, 1, 1, color=(84, 176, 232), batch=self.hud_batch)

        self.hud_wave_chip_shadow = shapes.Rectangle(0, 0, 1, 1, color=(0, 0, 0), batch=self.hud_batch)
        self.hud_wave_chip_shadow.opacity = 86
        self.hud_wave_chip_bg = shapes.Rectangle(0, 0, 1, 1, color=(18, 28, 42), batch=self.hud_batch)
        self.hud_wave_chip_bg.opacity = 230
        self.hud_wave_chip_border = shapes.BorderedRectangle(
            0, 0, 1, 1, border=2, color=(18, 28, 42), border_color=(110, 186, 255), batch=self.hud_batch
        )

        self.hud_status_bg = shapes.Rectangle(0, 0, 1, 1, color=(10, 16, 24), batch=self.hud_batch)
        self.hud_status_bg.opacity = 196
        self.hud_status_border = shapes.BorderedRectangle(
            0, 0, 1, 1, border=1, color=(10, 16, 24), border_color=(70, 128, 184), batch=self.hud_batch
        )

        self.hud_hp_label = pyglet.text.Label(
            "HULL",
            font_name=UI_FONT_META,
            font_size=10,
            x=0,
            y=0,
            anchor_x="left",
            anchor_y="bottom",
            color=(214, 225, 238, 220),
            batch=self.hud_batch,
        )
        self.hud_hp_value_label = pyglet.text.Label(
            "",
            font_name=UI_FONT_BODY,
            font_size=11,
            x=0,
            y=0,
            anchor_x="right",
            anchor_y="bottom",
            color=(244, 250, 255, 255),
            batch=self.hud_batch,
        )
        self.hud_shield_label = pyglet.text.Label(
            "SHIELD",
            font_name=UI_FONT_META,
            font_size=10,
            x=0,
            y=0,
            anchor_x="left",
            anchor_y="bottom",
            color=(188, 210, 232, 220),
            batch=self.hud_batch,
        )
        self.hud_shield_value_label = pyglet.text.Label(
            "",
            font_name=UI_FONT_BODY,
            font_size=11,
            x=0,
            y=0,
            anchor_x="right",
            anchor_y="bottom",
            color=(232, 244, 255, 255),
            batch=self.hud_batch,
        )

        self.hud_wave_label = pyglet.text.Label(
            "",
            font_name=UI_FONT_HEAD,
            font_size=22,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            color=(238, 245, 255, 255),
            batch=self.hud_batch,
        )
        self.hud_meta_label = pyglet.text.Label(
            "",
            font_name=UI_FONT_META,
            font_size=10,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="top",
            color=(168, 194, 222, 230),
            batch=self.hud_batch,
        )

        self.hud_status_label = pyglet.text.Label(
            "",
            font_name=UI_FONT_BODY,
            font_size=12,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            color=(170, 186, 206, 255),
            batch=self.hud_batch,
        )
        self._layout_hud()

    def _layout_hud(self) -> None:
        if not getattr(self, "hud_batch", None):
            return

        margin = 14
        panel_w = max(220, min(360, int(self.width * 0.33)))
        panel_h = 88
        panel_x = margin
        panel_y = self.height - margin - panel_h

        self.hud_panel_shadow.x = panel_x + 3
        self.hud_panel_shadow.y = panel_y - 3
        self.hud_panel_shadow.width = panel_w
        self.hud_panel_shadow.height = panel_h
        self.hud_panel_bg.x = panel_x
        self.hud_panel_bg.y = panel_y
        self.hud_panel_bg.width = panel_w
        self.hud_panel_bg.height = panel_h
        self.hud_panel_border.x = panel_x
        self.hud_panel_border.y = panel_y
        self.hud_panel_border.width = panel_w
        self.hud_panel_border.height = panel_h

        bar_margin_x = 14
        self._hud_bar_w = panel_w - (bar_margin_x * 2)
        bar_h = 12
        hp_y = panel_y + 44
        sh_y = panel_y + 22
        bar_x = panel_x + bar_margin_x

        self.hud_hp_bar_bg.x = bar_x
        self.hud_hp_bar_bg.y = hp_y
        self.hud_hp_bar_bg.width = self._hud_bar_w
        self.hud_hp_bar_bg.height = bar_h

        self.hud_hp_bar.x = bar_x
        self.hud_hp_bar.y = hp_y
        self.hud_hp_bar.height = bar_h

        self.hud_shield_bar_bg.x = bar_x
        self.hud_shield_bar_bg.y = sh_y
        self.hud_shield_bar_bg.width = self._hud_bar_w
        self.hud_shield_bar_bg.height = bar_h

        self.hud_shield_bar.x = bar_x
        self.hud_shield_bar.y = sh_y
        self.hud_shield_bar.height = bar_h

        self.hud_hp_label.x = bar_x
        self.hud_hp_label.y = hp_y + bar_h + 3
        self.hud_hp_value_label.x = bar_x + self._hud_bar_w
        self.hud_hp_value_label.y = hp_y + bar_h + 2
        self.hud_shield_label.x = bar_x
        self.hud_shield_label.y = sh_y + bar_h + 3
        self.hud_shield_value_label.x = bar_x + self._hud_bar_w
        self.hud_shield_value_label.y = sh_y + bar_h + 2

        chip_w = max(160, min(320, int(self.width * 0.26)))
        chip_h = 46
        chip_x = (self.width - chip_w) // 2
        chip_y = self.height - margin - chip_h
        min_gap = 12
        panel_right = panel_x + panel_w
        chip_left = chip_x
        chip_right = chip_x + chip_w
        chip_overlaps_panel = not (chip_left >= panel_right + min_gap or chip_right <= panel_x - min_gap)
        if chip_overlaps_panel:
            chip_y = panel_y - chip_h - 8
        self.hud_wave_chip_shadow.x = chip_x + 3
        self.hud_wave_chip_shadow.y = chip_y - 3
        self.hud_wave_chip_shadow.width = chip_w
        self.hud_wave_chip_shadow.height = chip_h
        self.hud_wave_chip_bg.x = chip_x
        self.hud_wave_chip_bg.y = chip_y
        self.hud_wave_chip_bg.width = chip_w
        self.hud_wave_chip_bg.height = chip_h
        self.hud_wave_chip_border.x = chip_x
        self.hud_wave_chip_border.y = chip_y
        self.hud_wave_chip_border.width = chip_w
        self.hud_wave_chip_border.height = chip_h

        self.hud_wave_label.x = chip_x + chip_w // 2
        self.hud_wave_label.y = chip_y + int(chip_h * 0.62)
        self.hud_meta_label.x = chip_x + chip_w // 2
        self.hud_meta_label.y = chip_y + int(chip_h * 0.28)

        is_stacked = chip_y < panel_y
        if is_stacked:
            status_w = max(220, min(700, int(self.width * 0.9)))
        else:
            status_w = max(240, min(640, int(self.width * 0.58)))
        status_h = 28
        status_x = (self.width - status_w) // 2
        status_y = max(6, chip_y - status_h - 10)
        self.hud_status_bg.x = status_x
        self.hud_status_bg.y = status_y
        self.hud_status_bg.width = status_w
        self.hud_status_bg.height = status_h
        self.hud_status_border.x = status_x
        self.hud_status_border.y = status_y
        self.hud_status_border.width = status_w
        self.hud_status_border.height = status_h
        self.hud_status_label.x = status_x + status_w // 2
        self.hud_status_label.y = status_y + status_h // 2
        self._hud_status_max_chars = max(24, int((status_w - 28) / 7.2))




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
        dmg = 1.0
        speed = 1.0
        fire = 1.0
        magnet = 0.0
        incoming = 1.0
        ultra_cd = 1.0
        for fx in list(getattr(self, "_active_temp_rewards", [])):
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
        self._temp_damage_mult = dmg
        self._temp_speed_mult = speed
        self._temp_fire_rate_mult = fire
        self._pickup_magnet_bonus = magnet
        self._temp_incoming_damage_mult = incoming
        self._ultra_cd_mult = ultra_cd

    def _advance_temp_rewards(self) -> None:
        if not getattr(self, "_active_temp_rewards", None):
            return
        kept = []
        for fx in self._active_temp_rewards:
            left = int(fx.get("waves_left", 0)) - 1
            if left > 0:
                fx["waves_left"] = left
                kept.append(fx)
        self._active_temp_rewards = kept
        self._recompute_temp_reward_mods()

    def _active_temp_hud_text(self) -> str:
        if not getattr(self, "_active_temp_rewards", None):
            return ""
        names = {
            "temp_overdrive": "Overdrive",
            "temp_haste": "Haste",
            "temp_rapidfire": "Rapidfire",
            "temp_magnet": "Magnet",
            "temp_guard": "Guard",
            "temp_ultra_flux": "Ultra Flux",
        }
        parts = []
        for fx in self._active_temp_rewards[:2]:
            key = str(fx.get("key", ""))
            left = int(fx.get("waves_left", 0))
            if key in names and left > 0:
                parts.append(f"{names[key]}:{left}")
        if not parts:
            return ""
        return "Temp " + ", ".join(parts)

    def _perm_hud_text(self) -> str:
        vals = list(getattr(self, "_run_permanent_rewards", []))
        if not vals:
            return ""
        names = {
            "perm_damage": "Core Damage",
            "perm_speed": "Servo",
            "perm_hp": "Hull",
            "perm_fire": "Trigger",
            "perm_shield": "Shield",
            "perm_ultra": "Ultra+",
        }
        shown = []
        for k in vals[:3]:
            if k in names:
                shown.append(names[k])
        if not shown:
            return ""
        return "Run " + ",".join(shown)

    def _roll_boss_rewards(self) -> None:
        if not self.player:
            return
        temp_pool = [
            {"key": "temp_overdrive", "title": "Overdrive", "desc": "+28% damage for 2 waves", "duration": 2},
            {"key": "temp_haste", "title": "Haste Drive", "desc": "+22% move speed for 3 waves", "duration": 3},
            {"key": "temp_rapidfire", "title": "Hot Trigger", "desc": "22% faster fire-rate for 2 waves", "duration": 2},
            {"key": "temp_magnet", "title": "Magnet Core", "desc": "Wider pickup magnet for 3 waves", "duration": 3},
            {"key": "temp_guard", "title": "Aegis Skin", "desc": "-18% incoming damage for 2 waves", "duration": 2},
            {"key": "temp_ultra_flux", "title": "Ultra Flux", "desc": "Ultra cooldown reduced for 3 waves", "duration": 3},
        ]
        perm_pool = [
            {"key": "perm_damage", "title": "Core Damage", "desc": "+1 damage this run"},
            {"key": "perm_speed", "title": "Servo Boost", "desc": "+6 move speed this run"},
            {"key": "perm_hp", "title": "Hull Plating", "desc": "+6 max HP this run"},
            {"key": "perm_fire", "title": "Trigger Tuning", "desc": "Slightly faster shots this run"},
            {"key": "perm_shield", "title": "Shield Layer", "desc": "+18 shield now"},
            {"key": "perm_ultra", "title": "Ultra Charge", "desc": "+1 Ultra charge now"},
        ]
        active_temp = {str(x.get("key", "")) for x in self._active_temp_rewards}
        temp_candidates = [x for x in temp_pool if x["key"] not in active_temp and x["key"] != self._last_reward_temp_key]
        if len(temp_candidates) < 3:
            temp_candidates = [x for x in temp_pool if x["key"] not in active_temp] or list(temp_pool)
        perm_candidates = [x for x in perm_pool if x["key"] != self._last_reward_perm_key]
        if len(perm_candidates) < 3:
            perm_candidates = list(perm_pool)
        temp_opts = random.sample(temp_candidates, k=3)
        perm_opts = random.sample(perm_candidates, k=3)
        self.rpg_menu.begin(temp_opts, perm_opts)

    def _apply_temp_reward(self, key: str, duration: int) -> None:
        if not self.player:
            return
        k = str(key or "").strip().lower()
        dur = max(2, min(3, int(duration)))
        refreshed = False
        for fx in self._active_temp_rewards:
            if str(fx.get("key", "")) == k:
                fx["waves_left"] = max(int(fx.get("waves_left", 0)), dur)
                refreshed = True
                break
        if not refreshed:
            self._active_temp_rewards.append({"key": k, "waves_left": dur})
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
        p = self.player
        if k == "perm_damage":
            p.damage = int(p.damage) + 1
        elif k == "perm_speed":
            p.speed = float(p.speed) + 6.0
        elif k == "perm_hp":
            p.max_hp = int(getattr(p, "max_hp", p.hp)) + 6
            p.hp = min(int(p.max_hp), int(p.hp) + 6)
        elif k == "perm_fire":
            p.fire_rate = max(0.12, float(p.fire_rate) - 0.006)
        elif k == "perm_shield":
            p.shield = min(120, int(getattr(p, "shield", 0)) + 18)
        elif k == "perm_ultra":
            p.ultra_charges = min(int(getattr(config, "ULTRA_MAX_CHARGES", 2)), int(p.ultra_charges) + 1)
        else:
            return
        self._last_reward_perm_key = k
        if k not in self._run_permanent_rewards:
            self._run_permanent_rewards.append(k)
        if self.particle_system:
            self.particle_system.add_powerup_collection(p.pos, (200, 235, 255))
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
        self.guide_menu.resize(width, height)
        self.pause_menu.resize(width, height)
        self.rpg_menu.resize(width, height)
        self.game_over_menu.resize(width, height)

        if getattr(self, "_pause_hint", None):
            self._pause_hint.x = width - 10
            self._pause_hint.y = height - 14
        if getattr(self, "hud_batch", None):
            self._layout_hud()

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
