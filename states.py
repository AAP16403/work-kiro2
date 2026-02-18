"""Game states logic."""

import random
import math
import pyglet
from pyglet import shapes

from config import WAVE_COOLDOWN, ENEMY_COLORS, POWERUP_COLORS, ROOM_RADIUS, ENABLE_OBSTACLES
import config
from utils import (
    Vec2,
    clamp_to_map,
    iso_to_world,
    dist,
    point_segment_distance,
    resolve_circle_obstacles,
    enemy_behavior_name,
)
from level import spawn_wave, maybe_spawn_powerup, spawn_loot_on_enemy_death, get_difficulty_mods
from enemy import update_enemy
from powerup import apply_powerup
from weapons import get_weapon_for_wave, get_effective_fire_rate
from projectile import spawn_projectiles
from particles import ParticleSystem
from fsm import State
from hazards import LaserBeam
from player import perform_dash, recharge_dash, format_dash_hud
from rpg import format_temp_hud, format_perm_hud

# Import helper functions from rpg module that might be needed or used via game instance but 
# some logic was in PlayingState directly? Checking usage...
# PlayingState uses game.rpg_menu, game._advance_temp_rewards, etc.

def _draw_playing_scene(game) -> None:
    # We access the state from the FSM map to avoid circular import issues if we tried to import PlayingState class
    # But since we are in states.py, we can just look it up on the game.fsm or pass it.
    # The original code did: game.fsm._states["PlayingState"].draw()
    # We can keep that pattern.
    if "PlayingState" in game.fsm._states:
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

    def update(self, dt: float):
        self.game.guide_menu.update(dt)

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
        elif symbol == pyglet.window.key.SPACE:
            self.game._dash()

    def on_mouse_press(self, x, y, button, modifiers):
        self.game.mouse_xy = (x, y)
        if button == pyglet.window.mouse.LEFT:
            self.game.auto_shoot = not self.game.auto_shoot
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
        if button == pyglet.window.mouse.RIGHT:
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
        blast_r = game.balance.bomb_blast_radius
        blast_dmg = game.balance.bomb_blast_damage(int(getattr(p, "damage", 0)))
        if game.particle_system:
            game.particle_system.add_death_explosion(p.pos, (255, 145, 90), "bomber")
        if dist(p.pos, game.player.pos) <= blast_r:
            game._damage_player(blast_dmg)
            s.shake = max(s.shake, 12.0)

    @staticmethod
    def _kill_enemy(game, s, e, death_particles: bool = True) -> None:
        """Centralized enemy kill: visuals cleanup, particles, loot, and score."""
        behavior_name = enemy_behavior_name(e)
        enemy_color = ENEMY_COLORS.get(behavior_name, (200, 200, 200))
        if e in s.enemies:
            s.enemies.remove(e)
        if game.visuals:
            game.visuals.drop_enemy(e)
        if death_particles and game.particle_system:
            game.particle_system.add_death_explosion(e.pos, enemy_color, behavior_name)
        spawn_loot_on_enemy_death(s, behavior_name, e.pos)
        if getattr(game, 'score', None):
            game.score.on_enemy_kill(behavior_name)

    def update(self, dt: float):
        game = self.game
        if not game.state:
            return
        # Clamp unstable frame spikes for more consistent simulation behavior.
        dt = max(0.0, min(float(dt), game.balance.sim_dt_cap))

        s = game.state
        s.time += dt
        if game.player.invincibility_timer > 0:
            game.player.invincibility_timer -= dt

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
                            self._kill_enemy(game, s, e, death_particles=False)

        for tr in list(getattr(s, "traps", [])):
            tr.t += dt
            tr.ttl -= dt
            if tr.ttl <= 0:
                s.traps.remove(tr)
                game.visuals.drop_trap(tr)
                continue
            if tr.damage > 0 and tr.t >= tr.armed_delay and dist(tr.pos, game.player.pos) <= tr.radius + game._player_radius():
                game._damage_player(tr.damage)
                s.shake = max(s.shake, 10.0)
                s.traps.remove(tr)
                game.visuals.drop_trap(tr)

        for th in list(getattr(s, "thunders", [])):
            th.t += dt
            if th.t >= th.warn and not th.hit_done:
                if point_segment_distance(game.player.pos, th.start, th.end) <= th.thickness * 0.6 + game._player_radius() * 0.35:
                    th.hit_done = True
                    game._damage_player(th.damage)
                    s.shake = max(s.shake, 14.0)
                    game.particle_system.add_laser_beam(th.start, th.end, color=th.color)
            if th.t >= th.warn + th.ttl:
                s.thunders.remove(th)
                game.visuals.drop_thunder(th)

        old_pos = Vec2(game.player.pos.x, game.player.pos.y)
        if game.player.is_dashing:
            game.player.pos += game.player.dash_direction * game.player.dash_speed * dt
            game.player.dash_timer -= dt
            if game.player.dash_timer <= 0:
                game.player.is_dashing = False
        else:
            idir = game._input_dir()
            if idir.length() > 0:
                nd = idir.normalized()
                game.player.pos = game.player.pos + nd * game._effective_player_speed() * dt
                game.particle_system.add_step_dust(game.player.pos, nd)

        # Recharge dash charges
        recharge_dash(
            game.player, s.time, game.balance,
            float(getattr(game, "_dash_cd_difficulty", 1.0)),
            float(getattr(game, "_dash_cd_mult", 1.0)),
        )
        game.player.pos = clamp_to_map(game.player.pos, config.ROOM_RADIUS * 0.9, s.map_type)
        if config.ENABLE_OBSTACLES and getattr(s, "obstacles", None):
            game.player.pos = resolve_circle_obstacles(game.player.pos, game._player_radius(), s.obstacles)
            game.player.pos = clamp_to_map(game.player.pos, config.ROOM_RADIUS * 0.9, s.map_type)
        if dt > 1e-6:
            player_vel = (game.player.pos - old_pos) * (1.0 / dt)
        else:
            player_vel = Vec2(0.0, 0.0)

        weapon_cd = get_effective_fire_rate(game.player.current_weapon, game._effective_player_fire_rate())
        if game.auto_shoot and (s.time - game.player.last_shot) >= weapon_cd:
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
                    if point_segment_distance(e.pos, muzzle, end) <= (beam.thickness * 0.5) + game._enemy_radius(e):
                        e.hp -= dmg
                        s.shake = max(s.shake, 4.0)
                        if e.hp <= 0:
                            self._kill_enemy(game, s, e, death_particles=False)
            else:
                weapon = game.player.current_weapon
                projectiles = spawn_projectiles(muzzle, aim, weapon, s.time, game._effective_player_damage())
                s.projectiles.extend(projectiles)

            game.particle_system.add_muzzle_flash(muzzle, aim)
            game.player.last_shot = s.time

        for e in list(s.enemies):
            update_enemy(e, game.player.pos, s, dt, game, player_vel=player_vel)
            e.pos = clamp_to_map(e.pos, config.ROOM_RADIUS * 0.96, s.map_type)
            if config.ENABLE_OBSTACLES and getattr(s, "obstacles", None):
                e.pos = resolve_circle_obstacles(e.pos, game._enemy_radius(e), s.obstacles)
                e.pos = clamp_to_map(e.pos, config.ROOM_RADIUS * 0.96, s.map_type)
            if dist(e.pos, game.player.pos) <= game._enemy_radius(e) + game._player_radius():
                game._damage_player(game.balance.enemy_contact_damage)
                self._kill_enemy(game, s, e, death_particles=False)
                s.shake = 9.0

        prev_projectile_pos: dict[int, Vec2] = {}
        for p in list(s.projectiles):
            prev_projectile_pos[id(p)] = Vec2(p.pos.x, p.pos.y)
            p.update(dt) # Use method now! Or custom logic? 
            # Original: p.pos = p.pos + p.vel * dt; p.ttl -= dt;
            # Projectile update method I added does this.
            # But wait, original code also handled obstacles specifically.
            # I can rely on p.update(dt) for movement/ttl, but obstacle checks need to be here or moved to physics/projectile.
            
            # Since I already updated projectile.py to include update method, let's use it, 
            # BUT I need to check the exact implementation in game.py vs projectile.py.
            # game.py handles collision.
            # I'll stick to manual update in game.py for now to be safe, OR invoke p.update(dt) and verify return.
            # Actually, `projectile.py` `update` returns bool (alive).
            # I'll keep the logic as is in PlayingState (copied from game.py) but replace the movement lines with `if not p.update(dt): ...` if consistent.
            # For this copy, I will PRESERVE original logic to minimize risk, just ensuring variables are correct.
            # Reverting to manual pos update for safety in this copy.
            
            # Wait, I copied the code verbatim from game.py, so it has p.pos += ...
            # game.py line 335: p.pos = p.pos + p.vel * dt
            # p.ttl -= dt
            
            if config.ENABLE_OBSTACLES and getattr(s, "obstacles", None):
                blocked = False
                pr = game._projectile_radius(p)
                prev = prev_projectile_pos.get(id(p), p.pos)
                for ob in s.obstacles:
                    if point_segment_distance(ob.pos, prev, p.pos) <= ob.radius + pr:
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
                pr = game._projectile_radius(p)
                p_prev = prev_projectile_pos.get(id(p), p.pos)
                for e in list(s.enemies):
                    if point_segment_distance(e.pos, p_prev, p.pos) <= pr + game._enemy_radius(e):
                        e.hp -= p.damage
                        s.shake = max(s.shake, 4.0)

                        behavior_name = enemy_behavior_name(e)
                        enemy_color = ENEMY_COLORS.get(behavior_name, (200, 200, 200))
                        game.particle_system.add_hit_particles(e.pos, enemy_color)

                        if e.hp <= 0:
                            self._kill_enemy(game, s, e)
                            if behavior_name == "tank" and dist(e.pos, game.player.pos) < game.balance.tank_death_blast_radius:
                                game._damage_player(game.balance.tank_death_blast_damage)
                                s.shake = 15.0
                        self._remove_projectile(game, s, p)
                        break
            else:
                ptype = str(getattr(p, "projectile_type", "bullet"))
                p_prev = prev_projectile_pos.get(id(p), p.pos)
                if ptype == "bomb":
                    if point_segment_distance(game.player.pos, p_prev, p.pos) <= game._projectile_radius(p) + game._player_radius():
                        self._explode_enemy_bomb(game, s, p)
                        self._remove_projectile(game, s, p)
                elif point_segment_distance(game.player.pos, p_prev, p.pos) <= game._projectile_radius(p) + game._player_radius():
                    game._damage_player(p.damage)
                    s.shake = max(s.shake, 6.0)
                    self._remove_projectile(game, s, p)

        for pu in list(s.powerups):
            dpu = dist(pu.pos, game.player.pos)
            kind = getattr(pu, "kind", "")
            magnet_r = game.balance.pickup_magnet_radius(kind, game._pickup_magnet_bonus)
            if dpu < magnet_r and dpu > 1e-6:
                pull = (game.player.pos - pu.pos).normalized()
                pull_speed = game.balance.pickup_pull_speed(magnet_r, dpu)
                pu.pos = pu.pos + pull * pull_speed * dt
                dpu = dist(pu.pos, game.player.pos)

            pickup_r = game.balance.pickup_radius(kind)
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
            if getattr(game, 'score', None):
                game.score.on_wave_clear(cleared_wave)

        if s.shake > 0:
            s.shake = max(0.0, s.shake - dt * 20)

        game.particle_system.update(dt)
        if getattr(game, 'score', None):
            game.score.update(dt)
        if game.room:
            # Compute combat intensity from game state.
            n_enemies = len(s.enemies)
            has_boss = any(
                str(getattr(e, "behavior", "")).startswith("boss_")
                for e in s.enemies
            )
            if n_enemies == 0:
                ci = 0.0
            elif has_boss:
                ci = 0.8 + 0.2 * min(1.0, n_enemies / 4.0)
            else:
                ci = min(0.55, 0.08 * n_enemies)
            game.room.set_combat_intensity(ci)
            game.room.update(dt)

        for lb in list(getattr(s, "lasers", [])):
            lb.t += dt
            if lb.owner == "enemy" and lb.t >= lb.warn and not lb.hit_done:
                if point_segment_distance(game.player.pos, lb.start, lb.end) <= lb.thickness * 0.55 + game._player_radius() * 0.35:
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

        game.visuals.sync_scene(s.time, shake, combat_intensity=float(getattr(game.room, "combat_intensity", 0.0)))

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
        
        dash_txt = format_dash_hud(game.player, game.state.time)
        temp_txt = format_temp_hud(game._active_temp_rewards)
        perm_txt = format_perm_hud(game._run_permanent_rewards)
        status_parts = [p for p in (dash_txt, laser_txt, vortex_txt, ultra_txt, temp_txt, perm_txt, boss_txt) if p]
        status_text = "   |   ".join(status_parts) if status_parts else "No active effects"

        game.hud.update_bars(game.player, game.state, score=getattr(game, 'score', None), status_text=status_text)
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
        wave = int(self.game.state.wave)
        score_obj = getattr(self.game, 'score', None)
        final_score = score_obj.score if score_obj else 0
        is_new_high = False
        high_score = 0
        if score_obj:
            is_new_high = score_obj.submit_score(wave)
            high_score = score_obj.get_high_score()
        self.game.game_over_menu.set_results(wave, final_score, high_score, is_new_high)
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
