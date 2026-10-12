"""Game states logic."""

import random
import math
from enum import Enum
import pyglet

from config import ENEMY_COLORS, POWERUP_COLORS
import config
from utils import (
    Vec2,
    clamp_to_map,
    iso_to_world,
    dist,
    dist_sq,
    point_segment_distance,
    point_segment_distance_sq,
    enemy_behavior_name,
)
from physics import resolve_circle_obstacles
from level import spawn_wave, maybe_spawn_powerup, spawn_loot_on_enemy_death, get_difficulty_mods
from enemy import update_enemy
from powerup import apply_powerup
from weapons import get_weapon_for_wave, get_effective_fire_rate
from projectile import spawn_projectiles, Projectile
from fsm import State
from hazards import LaserBeam
from player import perform_dash, recharge_dash, format_dash_hud, update_boost, format_boost_hud
from rpg import format_temp_hud, format_perm_hud


# Render-only randomness (screen shake). Kept off the seeded run RNG so gameplay
# stays reproducible regardless of frame rate or time spent paused.
_SHAKE_RNG = random.Random()


def add_shake(s, amount: float, limit: float | None = None) -> None:
    """Stack screen shake onto state ``s``: scaled by the reduced-shake setting, capped at SHAKE_CAP.

    ``limit`` is an optional ceiling for this one contribution, used by sustained sources such
    as ramming. It stops that source from pushing the shake past ``limit``, but it never lowers
    shake that is already higher, so bigger impacts still stack on top.
    """
    impulse = float(amount) * float(config.SHAKE_SCALE)
    if impulse <= 0.0:
        return
    current = float(s.shake)
    cap = float(config.SHAKE_CAP)
    if limit is not None:
        ceiling = min(cap, float(limit) * float(config.SHAKE_SCALE))
        if current >= ceiling:
            return
        cap = ceiling
    s.shake = min(cap, current + impulse)


class GameStateName(str, Enum):
    MENU = "MenuState"
    SETTINGS = "SettingsState"
    GUIDE = "GuideState"
    PLAYING = "PlayingState"
    PAUSED = "PausedState"
    BOSS_REWARD = "BossRewardState"
    GAME_OVER = "GameOverState"


# Weapon name -> shot sound (see tools/synth_sfx.py for the sounds themselves).
_SHOT_SFX = {
    "Basic Gun": "shot_basic",
    "Spread Shot": "shot_spread",
    "Rapid Fire": "shot_rapid",
    "Heavy Cannon": "shot_heavy",
    "Plasma Rifle": "shot_plasma",
    "Hyper Railgun": "shot_railgun",
    "Flak Battery": "shot_flak",
}


def _draw_playing_scene(game) -> None:
    if GameStateName.PLAYING.value in game.fsm._states:
        game.fsm._states[GameStateName.PLAYING.value].draw()

class MenuState(State):
    def enter(self):
        self.game._reset_input_flags()
        self.game.audio.play_music("menu")

    def on_mouse_press(self, x, y, button, modifiers):
        action = self.game.main_menu.on_mouse_press(x, y, button)
        if action == "start_game":
            self.game._init_game()
            self.game.fsm.set_state(GameStateName.PLAYING)
        elif action == "guide":
            self.game.fsm.set_state(GameStateName.GUIDE)
        elif action == "settings":
            self.game.fsm.set_state(GameStateName.SETTINGS)
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
            self.game._persist_audio_settings()
            self.game.fsm.set_state(GameStateName.MENU)

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        self.game.settings_menu.on_mouse_drag(x, y, dx, dy)

    def on_mouse_motion(self, x, y, dx, dy):
        self.game.settings_menu.on_mouse_motion(x, y)

    def on_mouse_release(self, x, y, button, modifiers):
        self.game.settings_menu.on_mouse_release(x, y, button)

    def on_key_press(self, symbol, modifiers):
        if symbol == pyglet.window.key.ESCAPE:
            self.game.fsm.set_state(GameStateName.MENU)

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
            self.game.fsm.set_state(GameStateName.MENU)

    def on_mouse_motion(self, x, y, dx, dy):
        self.game.guide_menu.on_mouse_motion(x, y)

    def on_key_press(self, symbol, modifiers):
        if symbol == pyglet.window.key.ESCAPE:
            self.game.fsm.set_state(GameStateName.MENU)
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
        self.game.audio.play_music("battle")
        self.game.audio.duck(1.0)

    def on_key_press(self, symbol, modifiers):
        if symbol == pyglet.window.key.ESCAPE:
            self.game.fsm.set_state(GameStateName.PAUSED)
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
    def _damage_enemy(game, s, e, amount: int, is_crit: bool = False) -> None:
        if amount <= 0:
            return
        e.hit_flash_timer = 0.12
        game.audio.play("hit_crit" if is_crit else "hit", volume=0.5, pitch_jitter=0.06, min_gap=0.02)
        if game.popups:
            if is_crit:
                game.popups.spawn(e.pos, f"{amount}!", color=(255, 225, 75), big=True)
            else:
                game.popups.spawn(e.pos, str(amount), color=(255, 255, 255))
        if is_crit and game.particle_system:
            game.particle_system.add_crit_spark(e.pos)
        if getattr(e, "shield", 0) > 0:
            absorbed = min(e.shield, amount)
            e.shield -= absorbed
            amount -= absorbed
            if absorbed > 0 and game.particle_system:
                game.particle_system.add_shield_hit(e.pos, absorbed)
        if amount > 0:
            e.hp -= amount

    @staticmethod
    def _spawn_cluster_shrapnel(game, s, p, ignore_entity_id: int | None = None) -> None:
        if game.particle_system:
            game.particle_system.add_flak_burst(p.pos)
        add_shake(s, 5.0)
        base_dmg = max(1, int(round(p.damage * 0.45)))
        for angle_deg in (0.0, 90.0, 180.0, 270.0):
            ang = math.radians(angle_deg + s.rng.uniform(-20.0, 20.0))
            sdir = Vec2(math.cos(ang), math.sin(ang))
            svel = sdir * s.rng.uniform(340.0, 460.0)
            spawn_pos = Vec2(p.pos.x + sdir.x * 8.0, p.pos.y + sdir.y * 8.0)
            shrapnel = Projectile(
                spawn_pos, svel, base_dmg,
                ttl=s.rng.uniform(0.24, 0.40),
                owner="player",
                projectile_type="bullet",
                is_crit=getattr(p, "is_crit", False),
                cluster_on_death=False,
            )
            shrapnel.prev_pos = Vec2(p.pos.x, p.pos.y)
            if ignore_entity_id is not None:
                shrapnel._hit_entities = {ignore_entity_id}
            s.projectiles.append(shrapnel)

    @staticmethod
    def _remove_projectile(game, s, p, detonating_enemy=None) -> None:
        if getattr(p, "cluster_on_death", False):
            p.cluster_on_death = False
            ignore_id = id(detonating_enemy) if detonating_enemy is not None else None
            PlayingState._spawn_cluster_shrapnel(game, s, p, ignore_entity_id=ignore_id)
        if p in s.projectiles:
            s.projectiles.remove(p)
        if game.visuals:
            game.visuals.drop_projectile(p)

    @staticmethod
    def _is_enemy_bomb(p) -> bool:
        return p.owner == "enemy" and str(getattr(p, "projectile_type", "bullet")) == "bomb"

    @staticmethod
    def _segment_hits_circle(psd2, center: Vec2, prev: Vec2, pos: Vec2, hit_r2: float) -> bool:
        return psd2(center, prev, pos) <= hit_r2

    @staticmethod
    def _projectile_hits_obstacle(psd2, prev: Vec2, pos: Vec2, pr: float, obstacles) -> bool:
        for ob in obstacles:
            hit_r2 = (float(ob.radius) + float(pr)) ** 2
            if psd2(ob.pos, prev, pos) <= hit_r2:
                return True
        return False

    def _explode_enemy_bomb(self, game, s, p) -> None:
        blast_r = game.balance.bomb_blast_radius
        blast_r2 = float(blast_r) * float(blast_r)
        blast_dmg = game.balance.bomb_blast_damage(int(getattr(p, "damage", 0)))
        if game.particle_system:
            game.particle_system.add_death_explosion(p.pos, (255, 145, 90), "bomber")
        if dist_sq(p.pos, game.player.pos) <= blast_r2:
            # Shake comes from _damage_player, scaled by the damage that actually lands.
            game._damage_player(blast_dmg)

    @staticmethod
    def _kill_enemy(game, s, e, death_particles: bool = True) -> None:
        """Centralized enemy kill: visuals cleanup, particles, loot, and score."""
        if getattr(e, "_is_dead", False):
            return
        e._is_dead = True
        behavior_name = enemy_behavior_name(e)
        enemy_color = ENEMY_COLORS.get(behavior_name, (200, 200, 200))
        if e in s.enemies:
            s.enemies.remove(e)
        if game.visuals:
            game.visuals.drop_enemy(e)
        if death_particles and game.particle_system:
            game.particle_system.add_death_explosion(e.pos, enemy_color, behavior_name)

        is_elite = bool(getattr(e, "is_elite", False))
        if behavior_name.startswith("boss_"):
            game.audio.play("boss_die", volume=1.0)
            game._hitstop = max(game._hitstop, 0.12)
            if game.particle_system:
                game.particle_system.add_boss_death(e.pos, enemy_color)
        else:
            if is_elite or behavior_name in ("tank", "bomber"):
                game.audio.play("explode", volume=0.8, pitch_jitter=0.05)
            else:
                game.audio.play("kill", volume=0.6, pitch_jitter=0.06, min_gap=0.02)
            if is_elite:
                game._hitstop = max(game._hitstop, 0.04)
            if game.particle_system:
                game.particle_system.add_kill_burst(e.pos, enemy_color, big=is_elite)

        # Elite volatile affix death explosion
        if getattr(e, "elite_affix", None) == "volatile":
            v_r = 130.0
            v_dmg = 45
            if game.particle_system:
                game.particle_system.add_death_explosion(e.pos, (255, 100, 30), "bomber")
            add_shake(s, 14.0)
            for other in list(s.enemies):
                if other not in s.enemies or other.hp <= 0 or getattr(other, "_is_dead", False):
                    continue
                if dist(other.pos, e.pos) <= v_r:
                    PlayingState._damage_enemy(game, s, other, v_dmg)
                    if other.hp <= 0:
                        PlayingState._kill_enemy(game, s, other)
            if dist(game.player.pos, e.pos) <= v_r:
                game._damage_player(20)

        spawn_loot_on_enemy_death(s, behavior_name, e.pos)
        if getattr(game, 'score', None):
            game.score.on_enemy_kill(behavior_name, multiplier=(float(config.ELITE_SCORE_MULT) if is_elite else 1.0))

    def update(self, dt: float):
        game = self.game
        if not game.state:
            return
        # Clamp unstable frame spikes for more consistent simulation behavior.
        dt = max(0.0, min(float(dt), game.balance.sim_dt_cap))

        if game._hitstop > 0.0:
            # Brief freeze on big impacts; the frame still renders.
            game._hitstop = max(0.0, game._hitstop - dt)
            return

        s = game.state
        s.time += dt
        if game.player.invincibility_timer > 0:
            game.player.invincibility_timer -= dt

        # Boost handling (LSHIFT or RSHIFT)
        k = pyglet.window.key
        keys = game.keys
        idir = game._input_dir()
        boost_requested = bool(keys[k.LSHIFT] or keys[k.RSHIFT]) and (idir.length() > 0 or game.player.is_dashing)
        has_inf_boost = game._has_infinite_boost()
        is_boosting = update_boost(game.player, dt, boost_requested, s.time, has_infinite=has_inf_boost)

        # Damage flash timers & elite visual aura
        if getattr(game.player, "damage_flash_timer", 0.0) > 0:
            game.player.damage_flash_timer = max(0.0, game.player.damage_flash_timer - dt)
        for e in s.enemies:
            if getattr(e, "hit_flash_timer", 0.0) > 0:
                e.hit_flash_timer = max(0.0, e.hit_flash_timer - dt)
            if getattr(e, "is_elite", False) and game.particle_system:
                game.particle_system.add_elite_aura(e.pos, getattr(config, "ELITE_AURA_COLOR", (255, 215, 60)))

        if not s.wave_active and (s.time - s.last_wave_clear) >= game.balance.wave_cooldown:
            spawn_wave(s, Vec2(0.0, 0.0))
            boss_now = next((e for e in s.enemies if enemy_behavior_name(e).startswith("boss_")), None)
            if boss_now is not None:
                boss_title = enemy_behavior_name(boss_now)[5:].replace("_", " ").upper()
                game.audio.play("boss_warn", volume=0.9)
                game.hud.show_banner("BOSS INCOMING", boss_title, color=(255, 120, 120), duration=2.6)
            else:
                game.hud.show_banner(f"WAVE {int(s.wave):02d}", f"{str(s.difficulty).upper()}  -  {len(s.enemies)} hostiles", duration=2.0)

        # Weapon-style hits this frame. They sum here and reach the shake once, after the
        # hit loops (see the flush before the decay), so many hits in one frame stay bounded.
        hit_shake = 0.0

        if s.time < game.player.vortex_until:
            game.particle_system.add_vortex_swirl(game.player.pos, s.time, game.player.vortex_radius)
            vortex_r2 = float(game.player.vortex_radius) * float(game.player.vortex_radius)
            dps = game.player.vortex_dps
            for e in list(s.enemies):
                if e not in s.enemies or e.hp <= 0 or getattr(e, "_is_dead", False):
                    continue
                if dist_sq(e.pos, game.player.pos) <= vortex_r2:
                    acc = getattr(e, "_vortex_acc", 0.0) + dps * dt
                    dmg = int(acc)
                    e._vortex_acc = acc - dmg
                    if dmg > 0:
                        PlayingState._damage_enemy(game, s, e, dmg)
                        hit_shake += float(config.SHAKE_HIT_IMPULSE)
                        if e.hp <= 0:
                            self._kill_enemy(game, s, e, death_particles=False)

        player_radius = game._player_radius()
        for tr in list(getattr(s, "traps", [])):
            tr.t += dt
            tr.ttl -= dt
            if tr.ttl <= 0:
                s.traps.remove(tr)
                game.visuals.drop_trap(tr)
                continue
            if tr.damage > 0 and tr.t >= tr.armed_delay:
                hit_r = float(tr.radius) + float(player_radius)
                if dist_sq(tr.pos, game.player.pos) <= hit_r * hit_r:
                    game._damage_player(tr.damage)
                    s.traps.remove(tr)
                    game.visuals.drop_trap(tr)

        for th in list(getattr(s, "thunders", [])):
            th.t += dt
            if th.t >= th.warn and not th.hit_done:
                hit_r = th.thickness * 0.6 + player_radius * 0.35
                if point_segment_distance_sq(game.player.pos, th.start, th.end) <= hit_r * hit_r:
                    th.hit_done = True
                    game._damage_player(th.damage)
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
            if idir.length() > 0:
                nd = idir.normalized()
                player_speed = game._effective_player_speed()
                if is_boosting:
                    player_speed *= float(getattr(config, "BOOST_SPEED_MULT", 1.65))
                    game.particle_system.add_boost_flame(game.player.pos, nd)
                    if getattr(game, "advanced_fx", None):
                        game.advanced_fx.trigger_boost(0.18)
                game.player.pos = game.player.pos + nd * player_speed * dt
                game.particle_system.add_step_dust(game.player.pos, nd)

        # Recharge dash charges
        recharge_dash(
            game.player, s.time, game.balance,
            float(getattr(game, "_dash_cd_difficulty", 1.0)),
            float(getattr(game, "_dash_cd_mult", 1.0)),
        )
        game.player.pos = clamp_to_map(game.player.pos, config.ROOM_RADIUS * 0.9, s.map_type)
        if config.ENABLE_OBSTACLES and getattr(s, "obstacles", None):
            game.player.pos = resolve_circle_obstacles(game.player.pos, player_radius, s.obstacles)
            game.player.pos = clamp_to_map(game.player.pos, config.ROOM_RADIUS * 0.9, s.map_type)
        if dt > 1e-6:
            player_vel = (game.player.pos - old_pos) * (1.0 / dt)
        else:
            player_vel = Vec2(0.0, 0.0)

        weapon = game.player.current_weapon
        if weapon and game.player.recoil > 0:
            game.player.recoil = max(0.0, game.player.recoil - float(weapon.recoil_recover) * dt)

        weapon_cd = get_effective_fire_rate(weapon, game._effective_player_fire_rate())
        if weapon and weapon.cadence_jitter:
            jitter = s.rng.uniform(1.0 - weapon.cadence_jitter, 1.0 + weapon.cadence_jitter)
            weapon_cd *= jitter
        weapon_cd = max(float(getattr(config, "FIRE_RATE_MIN", 0.06)), weapon_cd)

        if game.auto_shoot and s.time >= float(game.player.next_shot_time):
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
                game.audio.play("laser_charge", volume=0.4, min_gap=0.1)
                for e in list(s.enemies):
                    if e not in s.enemies or e.hp <= 0 or getattr(e, "_is_dead", False):
                        continue
                    hit_r = (beam.thickness * 0.5) + game._enemy_radius(e)
                    if point_segment_distance_sq(e.pos, muzzle, end) <= hit_r * hit_r:
                        PlayingState._damage_enemy(game, s, e, dmg)
                        hit_shake += float(config.SHAKE_HIT_IMPULSE)
                        if e.hp <= 0:
                            self._kill_enemy(game, s, e, death_particles=False)
            else:
                game.player.recoil = min(float(weapon.recoil_max), float(game.player.recoil) + float(weapon.recoil_kick))
                crit_cb = game._effective_crit_chance()
                crit_mb = game._effective_crit_mult()
                projectiles = spawn_projectiles(
                    muzzle, aim, weapon, s.time, game._effective_player_damage(),
                    recoil_deg=float(game.player.recoil),
                    rng=s.rng,
                    crit_chance_bonus=crit_cb,
                    crit_mult_bonus=crit_mb,
                )
                s.projectiles.extend(projectiles)
                game.audio.play(_SHOT_SFX.get(getattr(weapon, "name", ""), "shot_basic"), volume=0.45, pitch_jitter=0.04, min_gap=0.03)

            game.particle_system.add_muzzle_flash(muzzle, aim)
            game.player.last_shot = s.time
            game.player.next_shot_time = s.time + weapon_cd

        for e in list(s.enemies):
            if e not in s.enemies or e.hp <= 0 or getattr(e, "_is_dead", False):
                continue
            update_enemy(e, game.player.pos, s, dt, game, player_vel=player_vel)
            behavior_name = enemy_behavior_name(e)
            e._behavior_name = behavior_name
            e._radius = game.balance.enemy_radius(behavior_name)
            e.pos = clamp_to_map(e.pos, config.ROOM_RADIUS * 0.96, s.map_type)
            if config.ENABLE_OBSTACLES and getattr(s, "obstacles", None):
                e.pos = resolve_circle_obstacles(e.pos, e._radius, s.obstacles)
                e.pos = clamp_to_map(e.pos, config.ROOM_RADIUS * 0.96, s.map_type)
            hit_r = float(e._radius) + float(player_radius)
            d_sq = dist_sq(e.pos, game.player.pos)
            if d_sq <= hit_r * hit_r:
                if game.player.is_boosting:
                    ram_dmg = int(getattr(config, "BOOST_RAM_DAMAGE", 28))
                    PlayingState._damage_enemy(game, s, e, ram_dmg, is_crit=True)
                    # Ramming can touch every frame, so this source holds at 8 instead of stacking.
                    add_shake(s, 8.0, limit=8.0)
                    diff = e.pos - game.player.pos
                    cur_d = math.sqrt(d_sq)
                    if cur_d > 1e-4:
                        push_dir = diff / cur_d
                    else:
                        push_dir = idir.normalized() if idir.length() > 0 else Vec2(1.0, 0.0)

                    is_boss = behavior_name.startswith("boss_")
                    if is_boss:
                        push_dist = 20.0
                        e.pos = clamp_to_map(e.pos + push_dir * push_dist, config.ROOM_RADIUS * 0.96, s.map_type)
                        game.player.pos = clamp_to_map(game.player.pos - push_dir * 36.0, config.ROOM_RADIUS * 0.90, s.map_type)
                    else:
                        push_dist = max(45.0, (hit_r - cur_d) + 24.0)
                        e.pos = clamp_to_map(e.pos + push_dir * push_dist, config.ROOM_RADIUS * 0.96, s.map_type)

                    if e.hp <= 0:
                        self._kill_enemy(game, s, e)

                    if game.player.invincibility_timer <= 0:
                        game._damage_player(int(game.balance.enemy_contact_damage * 0.4))
                        game.player.invincibility_timer = max(game.player.invincibility_timer, 0.25)
                elif behavior_name.startswith("boss_"):
                    # Bosses never die from contact: they hurt, then shove the player clear.
                    if game.player.invincibility_timer <= 0:
                        game._damage_player(game.balance.enemy_contact_damage)
                        game.player.invincibility_timer = max(game.player.invincibility_timer, 0.6)
                    cur_d = math.sqrt(d_sq)
                    push_dir = (game.player.pos - e.pos) / cur_d if cur_d > 1e-4 else Vec2(1.0, 0.0)
                    game.player.pos = clamp_to_map(game.player.pos + push_dir * 40.0, config.ROOM_RADIUS * 0.90, s.map_type)
                else:
                    game._damage_player(game.balance.enemy_contact_damage)
                    self._kill_enemy(game, s, e, death_particles=False)

        psd2 = point_segment_distance_sq
        projectile_radius = game._projectile_radius
        obstacles = s.obstacles if (config.ENABLE_OBSTACLES and getattr(s, "obstacles", None)) else None

        for p in list(s.projectiles):
            p.update(dt)
            if obstacles:
                pr = projectile_radius(p)
                prev = p.prev_pos or p.pos
                if self._projectile_hits_obstacle(psd2, prev, p.pos, pr, obstacles):
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
            pr = projectile_radius(p)
            p_prev = p.prev_pos or p.pos
            if p.owner == "player":
                hit_entities = getattr(p, "_hit_entities", None)
                if hit_entities is None:
                    hit_entities = set()
                    p._hit_entities = hit_entities

                for e in list(s.enemies):
                    if e not in s.enemies or e.hp <= 0 or getattr(e, "_is_dead", False):
                        continue
                    if id(e) in hit_entities:
                        continue
                    er = getattr(e, "_radius", game._enemy_radius(e))
                    reach = er + pr
                    # Broadphase AABB pre-check
                    if (
                        e.pos.x < min(p_prev.x, p.pos.x) - reach
                        or e.pos.x > max(p_prev.x, p.pos.x) + reach
                        or e.pos.y < min(p_prev.y, p.pos.y) - reach
                        or e.pos.y > max(p_prev.y, p.pos.y) + reach
                    ):
                        continue

                    hit_r2 = reach * reach
                    if self._segment_hits_circle(psd2, e.pos, p_prev, p.pos, hit_r2):
                        hit_entities.add(id(e))
                        is_crit = getattr(p, "is_crit", False)
                        PlayingState._damage_enemy(game, s, e, p.damage, is_crit=is_crit)
                        hit_shake += float(config.SHAKE_CRIT_IMPULSE if is_crit else config.SHAKE_HIT_IMPULSE)

                        behavior_name = getattr(e, "_behavior_name", enemy_behavior_name(e))
                        enemy_color = ENEMY_COLORS.get(behavior_name, (200, 200, 200))
                        game.particle_system.add_hit_particles(e.pos, enemy_color)

                        if e.hp <= 0:
                            self._kill_enemy(game, s, e)
                            if behavior_name == "tank" and dist(e.pos, game.player.pos) < game.balance.tank_death_blast_radius:
                                game._damage_player(game.balance.tank_death_blast_damage)
                                add_shake(s, 15.0)

                        pierce = getattr(p, "pierce", 0)
                        if pierce > 0:
                            p.pierce = pierce - 1
                        else:
                            self._remove_projectile(game, s, p, detonating_enemy=e)
                            break
            else:
                ptype = str(getattr(p, "projectile_type", "bullet"))
                hit_r = pr + player_radius
                # Broadphase AABB pre-check
                if (
                    game.player.pos.x < min(p_prev.x, p.pos.x) - hit_r
                    or game.player.pos.x > max(p_prev.x, p.pos.x) + hit_r
                    or game.player.pos.y < min(p_prev.y, p.pos.y) - hit_r
                    or game.player.pos.y > max(p_prev.y, p.pos.y) + hit_r
                ):
                    continue

                hit_r2 = hit_r * hit_r
                if ptype == "bomb":
                    if self._segment_hits_circle(psd2, game.player.pos, p_prev, p.pos, hit_r2):
                        self._explode_enemy_bomb(game, s, p)
                        self._remove_projectile(game, s, p)
                elif self._segment_hits_circle(psd2, game.player.pos, p_prev, p.pos, hit_r2):
                    game._damage_player(p.damage)
                    self._remove_projectile(game, s, p)

        for pu in list(s.powerups):
            dpu2 = dist_sq(pu.pos, game.player.pos)
            kind = getattr(pu, "kind", "")
            magnet_r = game.balance.pickup_magnet_radius(kind, game._pickup_magnet_bonus)
            magnet_r2 = float(magnet_r) * float(magnet_r)
            if 1e-12 < dpu2 < magnet_r2:
                dpu = math.sqrt(dpu2)
                pull = (game.player.pos - pu.pos).normalized()
                pull_speed = game.balance.pickup_pull_speed(magnet_r, dpu)
                pu.pos = pu.pos + pull * pull_speed * dt
                dpu2 = dist_sq(pu.pos, game.player.pos)

            pickup_r = game.balance.pickup_radius(kind)
            if dpu2 < float(pickup_r) * float(pickup_r):
                color = POWERUP_COLORS.get(pu.kind, (200, 200, 200))
                game.particle_system.add_powerup_collection(pu.pos, color)
                rare = kind in ("ultra", "weapon", "vortex", "laser")
                game.audio.play("pickup_rare" if rare else "pickup", volume=0.7, pitch_jitter=0.03)
                if rare:
                    game.particle_system.add_pickup_ring(pu.pos, color)
                if game.popups:
                    game.popups.spawn(pu.pos, kind.upper(), color=color)
                apply_powerup(game.player, pu, s.time)
                s.powerups.remove(pu)
                game.visuals.drop_powerup(pu)

        # Enemies that left the fight without a kill (e.g. egg sacs that hatched) must not block the wave forever.
        for e in list(s.enemies):
            if e.hp <= 0 and not getattr(e, "_is_dead", False):
                e._is_dead = True
                s.enemies.remove(e)
                if game.visuals:
                    game.visuals.drop_enemy(e)
                if game.particle_system:
                    behavior_name = enemy_behavior_name(e)
                    game.particle_system.add_death_explosion(e.pos, ENEMY_COLORS.get(behavior_name, (200, 200, 200)), behavior_name)

        if s.wave_active and not s.enemies:
            cleared_wave = int(s.wave)
            s.wave_active = False
            s.last_wave_clear = s.time
            s.wave += 1
            game._advance_temp_rewards()
            game.audio.play("wave_clear", volume=0.8)
            if cleared_wave % 5 != 0:
                game.hud.show_banner(f"WAVE {cleared_wave:02d} CLEARED", "Next wave incoming", color=(120, 240, 170), duration=2.0)
            new_segment = (s.wave - 1) // 5
            if config.ENABLE_OBSTACLES and new_segment != getattr(s, "layout_segment", 0):
                game._regen_layout(new_segment)
            game.player.current_weapon = get_weapon_for_wave(s.wave)
            maybe_spawn_powerup(s, Vec2(0.0, 0.0))

            if cleared_wave % 5 == 0:
                game._roll_boss_rewards()
                game.fsm.set_state(GameStateName.BOSS_REWARD)
            if getattr(game, 'score', None):
                game.score.on_wave_clear(cleared_wave)

        if hit_shake > 0.0:
            add_shake(s, min(float(config.SHAKE_HIT_FRAME_MAX), hit_shake), limit=float(config.SHAKE_HIT_CEILING))

        if s.shake > 0:
            s.shake = max(0.0, s.shake - dt * float(config.SHAKE_DECAY))

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
                hit_r = lb.thickness * 0.55 + player_radius * 0.35
                if point_segment_distance_sq(game.player.pos, lb.start, lb.end) <= hit_r * hit_r:
                    lb.hit_done = True
                    game._damage_player(lb.damage)
                    game.particle_system.add_laser_beam(lb.start, lb.end, color=lb.color)
            if lb.t >= lb.warn + lb.ttl:
                s.lasers.remove(lb)
                game.visuals.drop_laser(lb)

        if game.player.hp <= 0:
            game.fsm.set_state(GameStateName.GAME_OVER)

    def draw(self):
        game = self.game
        if not game.state:
            return

        s = game.state
        shake = Vec2(0.0, 0.0)
        if s.shake > 0:
            amplitude = min(float(s.shake), float(config.SHAKE_CAP))
            shake = Vec2(_SHAKE_RNG.uniform(-1, 1), _SHAKE_RNG.uniform(-1, 1)) * amplitude

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

        game.particle_system.render(shake)
        game.batch.draw()
        if game.popups:
            game.popups.sync(shake)
            game.popups.draw()

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
            boss_max = max(1, int(getattr(boss, "max_hp", boss.hp) or 1))
            game.hud.set_boss(boss_name[5:].replace("_", " ").title(), int(boss.hp), boss_max)
        else:
            game.hud.set_boss(None, 0, 1)
        
        boost_txt = format_boost_hud(game.player, game.state.time, has_infinite=game._has_infinite_boost())
        dash_txt = format_dash_hud(game.player, game.state.time)
        temp_txt = format_temp_hud(game._active_temp_rewards)
        perm_txt = format_perm_hud(game._run_permanent_rewards)
        status_parts = [p for p in (boost_txt, dash_txt, laser_txt, vortex_txt, ultra_txt, temp_txt, perm_txt, boss_txt) if p]
        status_text = "   |   ".join(status_parts) if status_parts else "No active effects"

        game.hud.update_bars(
            game.player,
            game.state,
            score=getattr(game, 'score', None),
            status_text=status_text,
            has_infinite_boost=game._has_infinite_boost(),
            crit_chance_bonus=game._effective_crit_chance(),
        )
        game.hud.draw()

        if game._pause_hint:
            game._pause_hint.draw()


class PausedState(State):
    def enter(self):
        self.game._reset_input_flags()
        self.game.audio.duck(0.35)

    def on_key_press(self, symbol, modifiers):
        if symbol == pyglet.window.key.ESCAPE:
            self.game.fsm.set_state(GameStateName.PLAYING)

    def on_mouse_press(self, x, y, button, modifiers):
        action = self.game.pause_menu.on_mouse_press(x, y, button)
        if action == "resume":
            self.game.fsm.set_state(GameStateName.PLAYING)
        elif action == "quit_to_menu":
            self.game._return_to_menu()
            self.game.fsm.set_state(GameStateName.MENU)

    def on_mouse_motion(self, x, y, dx, dy):
        self.game.pause_menu.on_mouse_motion(x, y)

    def draw(self):
        _draw_playing_scene(self.game)
        self.game.pause_menu.draw()


class BossRewardState(State):
    def enter(self):
        self.game._reset_input_flags()
        self.game.audio.duck(0.5)

    def _finish_reward(self):
        if self.game.state:
            self.game.state.last_wave_clear = self.game.state.time - float(self.game.balance.wave_cooldown)
        self.game.fsm.set_state(GameStateName.PLAYING)

    def update(self, dt: float):
        self.game.rpg_menu.update(dt)

    def on_mouse_press(self, x, y, button, modifiers):
        chosen = self.game.rpg_menu.on_mouse_press(x, y, button)
        if chosen == "done":
            self._finish_reward()

    def on_key_press(self, symbol, modifiers):
        if self.game.rpg_menu.on_key_press(symbol) == "done":
            self._finish_reward()

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
        self.game.audio.play("game_over", volume=0.9)
        self.game.audio.play_music(None, fade=1.5)

    def on_mouse_press(self, x, y, button, modifiers):
        action = self.game.game_over_menu.on_mouse_press(x, y, button)
        if action == "retry":
            self.game._init_game()
            self.game.fsm.set_state(GameStateName.PLAYING)
        elif action == "quit_to_menu":
            self.game._return_to_menu()
            self.game.fsm.set_state(GameStateName.MENU)

    def on_mouse_motion(self, x, y, dx, dy):
        self.game.game_over_menu.on_mouse_motion(x, y)

    def draw(self):
        _draw_playing_scene(self.game)
        self.game.game_over_menu.draw()
