"""
Android/Kivy port entrypoint.

Build with Buildozer (recommended: run in Linux/WSL):
  cd android
  buildozer -v android debug
"""

from __future__ import annotations

import math
import os
import random
import sys

# Ensure the repo root is importable when this file is used as Buildozer entrypoint.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import config
from enemy import update_enemy
from hazards import LaserBeam
from layout import generate_obstacles
from level import GameState, maybe_spawn_powerup, spawn_loot_on_enemy_death, spawn_wave
from player import Player
from powerup import apply_powerup
from utils import (
    Vec2,
    clamp_to_room,
    compute_room_radius,
    dist,
    point_segment_distance,
    resolve_circle_obstacles,
    set_view_size,
    to_iso,
)
from weapons import (
    get_effective_fire_rate,
    get_weapon_color,
    get_weapon_for_wave,
    spawn_weapon_projectiles,
)

from controls import TouchControls
from overlay import GameOverlay

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, Rectangle
from kivy.metrics import dp
from kivy.uix.floatlayout import FloatLayout
class Kiro2AndroidGame(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.state = GameState(difficulty="normal")
        self.state.max_enemies = int(getattr(config, "MAX_ENEMIES", 12))
        self.player = Player(pos=Vec2(0.0, 0.0))
        self.player.current_weapon = get_weapon_for_wave(self.state.wave)

        self.controls = TouchControls(max_radius_px=float(dp(70)))
        self._shooting = False
        self._aim_dir = Vec2(1.0, 0.0)

        self._game_mode: str = "playing"  # playing | upgrade | game_over
        self._upgrade_options: list[dict] = []

        self._incoming_damage_mult = 1.0

        self.overlay = GameOverlay(
            on_ultra=self._use_ultra,
            on_restart=self._reset_run,
            on_shoot=self._set_shooting,
            on_upgrade_pick=self._on_upgrade_pick,
            show_fire_button=False,
        )
        self.add_widget(self.overlay)

        Clock.schedule_interval(self._tick, 1.0 / 60.0)
        Clock.schedule_interval(self._redraw, 1.0 / 60.0)

    def on_size(self, *_args):
        set_view_size(int(self.width), int(self.height))
        # Make the arena fit the device view.
        try:
            config.ROOM_RADIUS = compute_room_radius(int(self.width), int(self.height), margin=float(getattr(config, "ARENA_MARGIN", 0.97)))
        except Exception:
            pass
        self._ensure_layout()

    def _ensure_layout(self) -> None:
        if not getattr(config, "ENABLE_OBSTACLES", False):
            self.state.obstacles = []
            return
        if self.state.layout_seed == 0:
            self.state.layout_seed = random.randint(1, 1_000_000_000)
        seg = int(getattr(self.state, "layout_segment", 0))
        self.state.obstacles = generate_obstacles(self.state.layout_seed, seg, float(config.ROOM_RADIUS), difficulty=self.state.difficulty)

    def _reset_run(self) -> None:
        self.state = GameState(difficulty="normal")
        self.state.max_enemies = int(getattr(config, "MAX_ENEMIES", 12))
        self.player = Player(pos=Vec2(0.0, 0.0))
        self.player.current_weapon = get_weapon_for_wave(self.state.wave)
        self._game_mode = "playing"
        self._shooting = False
        self._aim_dir = Vec2(1.0, 0.0)
        self.controls.release_all()
        self._upgrade_options = []
        self._incoming_damage_mult = 1.0
        self.overlay.hide_upgrade()
        self.overlay.hide_game_over()
        self._ensure_layout()

    def _set_shooting(self, down: bool) -> None:
        if self._game_mode != "playing":
            self._shooting = False
            return
        self._shooting = bool(down)

    def on_touch_down(self, touch):
        if self._game_mode == "game_over":
            return super().on_touch_down(touch)
        if self._game_mode == "upgrade":
            return super().on_touch_down(touch)

        # Avoid stealing touches from UI elements.
        for w in self.overlay.reserved_widgets():
            if w.collide_point(*touch.pos):
                return super().on_touch_down(touch)

        if self.controls.handle_touch_down(touch, self.width, self.height):
            return True

        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self.controls.handle_touch_move(touch):
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self.controls.handle_touch_up(touch):
            return True
        return super().on_touch_up(touch)

    def _damage_player(self, amount: int) -> None:
        if not self.player or amount <= 0:
            return
        mult = getattr(self, "_incoming_damage_mult", 1.0)
        if mult != 1.0:
            amount = max(1, int(round(amount * mult)))
        if self.player.shield > 0:
            absorbed = min(int(self.player.shield), int(amount))
            self.player.shield -= absorbed
            amount -= absorbed
        if amount > 0:
            self.player.hp -= int(amount)

    def _enemy_radius(self, enemy) -> float:
        b = getattr(enemy, "behavior", "")
        if str(b).startswith("boss_"):
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

    def _use_ultra(self) -> None:
        if self._game_mode != "playing" or not self.state or not self.player:
            return
        s = self.state
        if getattr(self.player, "ultra_charges", 0) <= 0:
            return
        if s.time < getattr(self.player, "ultra_cd_until", 0.0):
            return

        aim = Vec2(self._aim_dir.x, self._aim_dir.y)
        if aim.length() <= 1e-6:
            aim = Vec2(1.0, 0.0)

        muzzle = self.player.pos + aim * 14.0
        beam_len = float(config.ROOM_RADIUS) * 2.05
        end = muzzle + aim * beam_len
        dmg = int(config.ULTRA_DAMAGE_BASE + self.player.damage * config.ULTRA_DAMAGE_MULT)

        beam = LaserBeam(
            start=muzzle,
            end=end,
            damage=dmg,
            thickness=float(config.ULTRA_BEAM_THICKNESS),
            ttl=float(config.ULTRA_BEAM_TTL),
            owner="player",
            color=tuple(config.ULTRA_BEAM_COLOR),
        )
        s.lasers.append(beam)
        s.shake = max(s.shake, 12.0)

        hit_r = float(config.ULTRA_BEAM_THICKNESS) * 0.75
        for e in list(s.enemies):
            if point_segment_distance(e.pos, muzzle, end) <= hit_r:
                e.hp -= dmg
                if e.hp <= 0:
                    s.enemies.remove(e)
                    spawn_loot_on_enemy_death(s, e.behavior, e.pos)

        self.player.ultra_charges = max(0, int(self.player.ultra_charges) - 1)
        self.player.ultra_cd_until = s.time + float(config.ULTRA_COOLDOWN)

    def _roll_upgrade_options(self) -> None:
        p = self.player
        if not p:
            return

        opts: list[dict] = []
        opts.append({"key": "max_hp", "title": "Max HP +10", "desc": f"{int(getattr(p, 'max_hp', p.hp))} -> {int(getattr(p, 'max_hp', p.hp)) + 10}"})
        opts.append({"key": "damage", "title": "Damage +2", "desc": f"{int(p.damage)} -> {int(p.damage) + 2}"})
        opts.append({"key": "speed", "title": "Move Speed +12", "desc": f"{int(p.speed)} -> {int(p.speed) + 12}"})

        fr_now = float(getattr(p, "fire_rate", 0.28))
        fr_new = max(0.14, fr_now - 0.01)
        if fr_new < fr_now - 1e-6:
            opts.append({"key": "fire_rate", "title": "Faster Shots (-0.01s)", "desc": f"{fr_now:.2f}s -> {fr_new:.2f}s"})

        sh_now = int(getattr(p, "shield", 0))
        sh_new = min(120, sh_now + 35)
        if sh_new > sh_now:
            opts.append({"key": "shield", "title": "Shield +35", "desc": f"{sh_now} -> {sh_new}"})

        self._upgrade_options = random.sample(opts, k=3) if len(opts) > 3 else opts

    def _apply_run_upgrade(self, key: str) -> None:
        k = str(key or "").strip().lower()
        p = self.player
        if not p:
            return

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

        if self.state:
            self.state.shake = max(self.state.shake, 4.0)

    def _on_upgrade_pick(self, index: int) -> None:
        if self._game_mode != "upgrade":
            return
        idx = int(index)
        if idx < 0 or idx >= len(self._upgrade_options):
            return
        self._apply_run_upgrade(self._upgrade_options[idx]["key"])
        self.overlay.hide_upgrade()
        self._game_mode = "playing"

    def _tick(self, dt: float) -> None:
        if not self.state or not self.player:
            return
        if self._game_mode != "playing":
            self._shooting = False
            self._update_ui()
            return

        s = self.state
        dt = float(max(0.0, min(1.0 / 20.0, dt)))  # clamp (pause/resume safety)
        s.time += dt

        aim_dir = self.controls.aim.direction_world()
        auto_shoot = False
        if aim_dir.length() > 1e-6:
            self._aim_dir = aim_dir
            auto_shoot = True
        self._shooting = auto_shoot

        # Waves
        if not s.wave_active and (s.time - s.last_wave_clear) >= float(config.WAVE_COOLDOWN):
            spawn_wave(s, Vec2(0.0, 0.0))

        # Vortex aura
        if s.time < self.player.vortex_until:
            dps = float(self.player.vortex_dps)
            for e in list(s.enemies):
                if dist(e.pos, self.player.pos) <= float(self.player.vortex_radius):
                    acc = getattr(e, "_vortex_acc", 0.0) + dps * dt
                    dmg = int(acc)
                    e._vortex_acc = acc - dmg
                    if dmg > 0:
                        e.hp -= dmg
                        s.shake = max(s.shake, 2.5)
                        if e.hp <= 0:
                            s.enemies.remove(e)
                            spawn_loot_on_enemy_death(s, e.behavior, e.pos)

        # Traps
        for tr in list(getattr(s, "traps", [])):
            tr.t += dt
            tr.ttl -= dt
            if tr.ttl <= 0:
                s.traps.remove(tr)
                continue
            if tr.damage > 0 and tr.t >= tr.armed_delay and dist(tr.pos, self.player.pos) <= tr.radius:
                self._damage_player(tr.damage)
                s.shake = max(s.shake, 10.0)
                s.traps.remove(tr)

        # Thunder lines
        for th in list(getattr(s, "thunders", [])):
            th.t += dt
            if th.t >= th.warn and not th.hit_done:
                if point_segment_distance(self.player.pos, th.start, th.end) <= th.thickness * 0.6:
                    th.hit_done = True
                    self._damage_player(th.damage)
                    s.shake = max(s.shake, 14.0)
            if th.t >= th.warn + th.ttl:
                s.thunders.remove(th)

        # Player movement
        old_pos = Vec2(self.player.pos.x, self.player.pos.y)
        move_dir = self.controls.move.direction_world()
        if move_dir.length() > 0:
            self.player.pos = self.player.pos + move_dir * float(self.player.speed) * dt
        self.player.pos = clamp_to_room(self.player.pos, float(config.ROOM_RADIUS) * 0.9)
        if config.ENABLE_OBSTACLES and getattr(s, "obstacles", None):
            self.player.pos = resolve_circle_obstacles(self.player.pos, 14.0, s.obstacles)
            self.player.pos = clamp_to_room(self.player.pos, float(config.ROOM_RADIUS) * 0.9)
        player_vel = (self.player.pos - old_pos) * (1.0 / dt) if dt > 1e-6 else Vec2(0.0, 0.0)

        # Player shooting
        weapon_cd = get_effective_fire_rate(self.player.current_weapon, self.player.fire_rate)
        if self._shooting and (s.time - self.player.last_shot) >= weapon_cd:
            aim = Vec2(self._aim_dir.x, self._aim_dir.y)
            if aim.length() <= 1e-6:
                aim = Vec2(1.0, 0.0)
            muzzle = self.player.pos + aim * 14.0

            if s.time < self.player.laser_until:
                beam_len = float(config.ROOM_RADIUS) * 1.6
                end = muzzle + aim * beam_len
                dmg = int(self.player.damage * 0.9) + 14
                beam = LaserBeam(start=muzzle, end=end, damage=dmg, thickness=12.0, ttl=0.08, owner="player")
                s.lasers.append(beam)
                for e in list(s.enemies):
                    if point_segment_distance(e.pos, muzzle, end) <= 14:
                        e.hp -= dmg
                        s.shake = max(s.shake, 4.0)
                        if e.hp <= 0:
                            s.enemies.remove(e)
                            spawn_loot_on_enemy_death(s, e.behavior, e.pos)
            else:
                s.projectiles.extend(spawn_weapon_projectiles(muzzle, aim, self.player.current_weapon, s.time, self.player.damage))

            self.player.last_shot = s.time

        # Enemies
        for e in list(s.enemies):
            update_enemy(e, self.player.pos, s, dt, player_vel=player_vel)
            e.pos = clamp_to_room(e.pos, float(config.ROOM_RADIUS) * 0.96)
            if config.ENABLE_OBSTACLES and getattr(s, "obstacles", None):
                e.pos = resolve_circle_obstacles(e.pos, self._enemy_radius(e), s.obstacles)
                e.pos = clamp_to_room(e.pos, float(config.ROOM_RADIUS) * 0.96)
            if dist(e.pos, self.player.pos) < 12:
                self._damage_player(10)
                s.enemies.remove(e)
                s.shake = 9.0
                spawn_loot_on_enemy_death(s, e.behavior, self.player.pos)

        # Projectiles
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
                    s.projectiles.remove(p)
                    continue
            if p.ttl <= 0:
                s.projectiles.remove(p)

        # Collisions
        for p in list(s.projectiles):
            if p.owner == "player":
                ptype = str(getattr(p, "projectile_type", "bullet"))
                hit_r = 16.0 if ptype == "missile" else 12.0 if ptype == "plasma" else 11.0
                for e in list(s.enemies):
                    if dist(p.pos, e.pos) < hit_r:
                        e.hp -= p.damage
                        s.shake = max(s.shake, 4.0)
                        if e.hp <= 0:
                            s.enemies.remove(e)
                            if e.behavior == "tank" and dist(e.pos, self.player.pos) < 70:
                                self._damage_player(15)
                                s.shake = 15.0
                            spawn_loot_on_enemy_death(s, e.behavior, e.pos)
                        if p in s.projectiles:
                            s.projectiles.remove(p)
                        break
            else:
                if dist(p.pos, self.player.pos) < 12:
                    self._damage_player(p.damage)
                    s.shake = max(s.shake, 6.0)
                    if p in s.projectiles:
                        s.projectiles.remove(p)

        # Powerups
        for pu in list(s.powerups):
            dpu = dist(pu.pos, self.player.pos)
            kind = getattr(pu, "kind", "")
            is_special = kind in ("weapon", "ultra")
            magnet_r = 190.0 if is_special else 150.0
            if dpu < magnet_r and dpu > 1e-6:
                pull = (self.player.pos - pu.pos).normalized()
                pull_speed = 220.0 + (magnet_r - dpu) * 2.0
                pu.pos = pu.pos + pull * pull_speed * dt
                dpu = dist(pu.pos, self.player.pos)
            pickup_r = 20.0 if is_special else 16.0
            if dpu < pickup_r:
                apply_powerup(self.player, pu, s.time)
                s.powerups.remove(pu)

        # Wave clear
        if s.wave_active and not s.enemies:
            cleared_wave = int(s.wave)
            s.wave_active = False
            s.last_wave_clear = s.time
            s.wave += 1
            new_segment = (s.wave - 1) // 5
            if config.ENABLE_OBSTACLES and new_segment != int(getattr(s, "layout_segment", 0)):
                s.layout_segment = int(new_segment)
                self._ensure_layout()
            self.player.current_weapon = get_weapon_for_wave(s.wave)
            maybe_spawn_powerup(s, Vec2(0.0, 0.0))

            if cleared_wave % 3 == 0:
                self._roll_upgrade_options()
                self._game_mode = "upgrade"
                self._shooting = False
                self.controls.release_all()
                self.overlay.show_upgrade(self._upgrade_options)

        # Shake decay
        if s.shake > 0:
            s.shake = max(0.0, s.shake - dt * 20.0)

        # Laser beams (timers + enemy beams damage)
        for lb in list(getattr(s, "lasers", [])):
            lb.t += dt
            if lb.owner == "enemy" and lb.t >= lb.warn and not lb.hit_done:
                if point_segment_distance(self.player.pos, lb.start, lb.end) <= lb.thickness * 0.55:
                    lb.hit_done = True
                    self._damage_player(lb.damage)
                    s.shake = max(s.shake, 10.0)
            if lb.t >= lb.warn + lb.ttl:
                s.lasers.remove(lb)

        if self.player.hp <= 0 and self._game_mode != "game_over":
            self._game_mode = "game_over"
            self._shooting = False
            self.controls.release_all()
            self.overlay.hide_upgrade()
            self.overlay.show_game_over()

        self._update_ui()

    def _update_ui(self) -> None:
        s = self.state
        p = self.player
        if not s or not p:
            return
        hp_cap = int(getattr(p, "max_hp", p.hp))
        ultra_charges = int(getattr(p, "ultra_charges", 0))
        ultra_cd = max(0.0, float(getattr(p, "ultra_cd_until", 0.0)) - s.time)
        ultra_txt = f"  Ultra:{ultra_charges}" + (f"({ultra_cd:.0f}s)" if ultra_cd > 0 else "") if ultra_charges > 0 else ""
        self.overlay.hud.text = (
            f"HP:{int(p.hp)}/{hp_cap}  Shield:{int(p.shield)}  Wave:{int(s.wave)}  "
            f"Enemies:{len(s.enemies)}  Weapon:{getattr(p.current_weapon, 'name', '??')}{ultra_txt}"
        )
        self.overlay.set_ultra_enabled(ultra_charges > 0)
        self.overlay.set_fire_enabled(False)

    def _redraw(self, _dt: float) -> None:
        if not self.state or not self.player:
            return

        s = self.state
        p = self.player

        # Screen shake.
        shake = Vec2(0.0, 0.0)
        if s.shake > 0:
            shake = Vec2(random.uniform(-1, 1), random.uniform(-1, 1)) * float(s.shake)

        self.canvas.clear()
        with self.canvas:
            # Background
            Color(config.BG_BOTTOM[0] / 255.0, config.BG_BOTTOM[1] / 255.0, config.BG_BOTTOM[2] / 255.0, 1.0)
            Rectangle(pos=self.pos, size=self.size)

            # Arena outline
            r = float(config.ROOM_RADIUS) * 0.9
            pts: list[float] = []
            n = 56
            for i in range(n):
                ang = (i / n) * (math.tau)
                wp = Vec2(math.cos(ang) * r, math.sin(ang) * r)
                sx, sy = to_iso(wp, shake)
                pts.extend([sx, sy])
            Color(0.5, 0.55, 0.7, 0.7)
            Line(points=pts, close=True, width=dp(1.2))

            draw_list: list[tuple[float, callable]] = []

            def add_draw(y: float, fn):
                draw_list.append((float(y), fn))

            def circle_at(world: Vec2, radius_world: float, rgb: tuple[int, int, int], alpha: float = 1.0):
                sx, sy = to_iso(world, shake)
                # Rough world->screen scale (visual-only).
                rr = max(dp(2.5), float(radius_world) * 0.55)
                cr, cg, cb = rgb

                def _fn():
                    Color(cr / 255.0, cg / 255.0, cb / 255.0, float(alpha))
                    Ellipse(pos=(sx - rr, sy - rr), size=(rr * 2.0, rr * 2.0))

                add_draw(sy, _fn)

            # Obstacles (visual-only)
            if config.ENABLE_OBSTACLES:
                for ob in getattr(s, "obstacles", []):
                    circle_at(ob.pos, float(ob.radius), (95, 104, 128), alpha=0.9)

            # Powerups
            for pu in getattr(s, "powerups", []):
                color = config.POWERUP_COLORS.get(getattr(pu, "kind", ""), (220, 220, 220))
                circle_at(pu.pos, 10.0, color, alpha=0.95)

            # Projectiles
            for proj in getattr(s, "projectiles", []):
                c = get_weapon_color(getattr(proj, "projectile_type", "bullet"))
                circle_at(proj.pos, 5.0, c, alpha=0.95)

            # Traps
            for tr in getattr(s, "traps", []):
                circle_at(tr.pos, float(getattr(tr, "radius", 22.0)), (255, 160, 80), alpha=0.35)

            # Enemies
            for e in getattr(s, "enemies", []):
                c = config.ENEMY_COLORS.get(getattr(e, "behavior", ""), (200, 200, 200))
                circle_at(e.pos, self._enemy_radius(e), c, alpha=0.95)

            # Player
            circle_at(p.pos, 14.0, (235, 235, 235), alpha=1.0)
            if int(getattr(p, "shield", 0)) > 0:
                circle_at(p.pos, 18.0, (120, 220, 255), alpha=0.25)

            # Lasers / thunder
            for lb in getattr(s, "lasers", []):
                sx1, sy1 = to_iso(lb.start, shake)
                sx2, sy2 = to_iso(lb.end, shake)
                r_, g_, b_ = getattr(lb, "color", (255, 120, 255))
                Color(r_ / 255.0, g_ / 255.0, b_ / 255.0, 0.85)
                Line(points=[sx1, sy1, sx2, sy2], width=max(dp(1.0), float(getattr(lb, "thickness", 10.0)) * 0.28))

            for th in getattr(s, "thunders", []):
                sx1, sy1 = to_iso(th.start, shake)
                sx2, sy2 = to_iso(th.end, shake)
                r_, g_, b_ = getattr(th, "color", (170, 200, 255))
                Color(r_ / 255.0, g_ / 255.0, b_ / 255.0, 0.75)
                Line(points=[sx1, sy1, sx2, sy2], width=max(dp(1.0), float(getattr(th, "thickness", 16.0)) * 0.25))

            # Touch sticks indicators (left move + right aim)
            if self.controls.move.active():
                ox, oy = self.controls.move.origin
                x, y = self.controls.move.pos
                Color(0.8, 0.85, 1.0, 0.15)
                Line(circle=(ox, oy, dp(44)), width=dp(1.1))
                Color(0.8, 0.85, 1.0, 0.25)
                Ellipse(pos=(x - dp(10), y - dp(10)), size=(dp(20), dp(20)))
            if self.controls.aim.active():
                ox, oy = self.controls.aim.origin
                x, y = self.controls.aim.pos
                Color(1.0, 0.9, 0.7, 0.12)
                Line(circle=(ox, oy, dp(44)), width=dp(1.1))
                Color(1.0, 0.9, 0.7, 0.22)
                Ellipse(pos=(x - dp(10), y - dp(10)), size=(dp(20), dp(20)))

            # Draw depth-sorted list
            for _y, fn in sorted(draw_list, key=lambda t: t[0]):
                fn()


class Kiro2AndroidApp(App):
    def build(self):
        root = Kiro2AndroidGame()
        return root


if __name__ == "__main__":
    Kiro2AndroidApp().run()
