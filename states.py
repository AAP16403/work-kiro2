"""Game states logic."""

import random
import math

from config import WAVE_COOLDOWN, ENEMY_COLORS, POWERUP_COLORS, ROOM_RADIUS, ENABLE_OBSTACLES
import config
from utils import (
    Vec2,
    clamp_to_map,
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

class MenuState(State):
    def enter(self):
        print("DEBUG: Entering MenuState")
        self.game.main_menu.show()
    def exit(self):
        self.game.main_menu.hide()
    def update(self, dt: float):
        pass
    def draw(self):
        pass

class SettingsState(State):
    def enter(self):
        self.game.settings_menu.show()
    def exit(self):
        self.game.settings_menu.hide()
    def update(self, dt: float):
        pass

class GuideState(State):
    def enter(self):
        self.game.guide_menu.show()
    def exit(self):
        self.game.guide_menu.hide()
    def update(self, dt: float):
        pass

class PlayingState(State):
    def enter(self):
        print("DEBUG: Entering PlayingState")
        if hasattr(self.game, "_init_game"):
             if not self.game.state:
                 self.game._init_game()
        # Show HUD
        if hasattr(self.game, "hud"):
            self.game.hud.show()

    def exit(self):
        if hasattr(self.game, "hud"):
            self.game.hud.hide()

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
        
        if hasattr(game, "hud"):
            game.hud.update(game.player, s)

        if game.player.invincibility_timer > 0:
            game.player.invincibility_timer -= dt

        if not s.wave_active and (s.time - s.last_wave_clear) >= WAVE_COOLDOWN:
            print(f"DEBUG: Spawning wave {s.wave} at {s.time}")
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
            aim = game.get_aim_direction(game.player.pos)
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
            p.update(dt)
            
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

        # Update sub-systems
        game.particle_system.update(dt)
        if getattr(game, 'score', None):
            game.score.update(dt)
        if game.room:
            # Sync combat intensity
            n_enemies = len(s.enemies)
            has_boss = any(str(getattr(e, "behavior", "")).startswith("boss_") for e in s.enemies)
            if n_enemies == 0: ci = 0.0
            elif has_boss: ci = 0.8 + 0.2 * min(1.0, n_enemies / 4.0)
            else: ci = min(0.55, 0.08 * n_enemies)
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


class PausedState(State):
    def enter(self):
        self.game.pause_menu.show()
    def exit(self):
        self.game.pause_menu.hide()
    def update(self, dt: float):
        pass

class BossRewardState(State):
    def enter(self):
        if hasattr(self.game, "rpg_menu"):
            self.game.rpg_menu.complete = False
            self.game.rpg_menu.active = True

    def update(self, dt: float):
        menu = getattr(self.game, "rpg_menu", None)
        if not menu:
            self.game.consume_pending_boss_rewards(temp_index=0, perm_index=0)
            self.game.fsm.set_state("PlayingState")
            return
        if menu.complete:
            self.game.fsm.set_state("PlayingState")

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
        if hasattr(self.game, "game_over_menu"):
            self.game.game_over_menu.set_results(wave, final_score, high_score, is_new_high)
            self.game.game_over_menu.show()
            
    def exit(self):
        if hasattr(self.game, "game_over_menu"):
            self.game.game_over_menu.hide()

    def update(self, dt: float):
        pass
