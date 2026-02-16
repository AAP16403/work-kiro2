"""Coordinated swarm behavior with squad-level planning."""

import math
import random

from enemy_behaviors.base import Behavior
from utils import Vec2


class Swarm(Behavior):
    """Swarm enemies that coordinate as a squad instead of acting independently."""

    def __init__(self, perception_radius=95.0, separation_weight=1.7, align_weight=0.9, cohesion_weight=0.9):
        self.perception_radius = perception_radius
        self.separation_weight = separation_weight
        self.align_weight = align_weight
        self.cohesion_weight = cohesion_weight

    def update(self, enemy, player_pos, state, dt, player_vel):
        allies = self._get_swarm_allies(getattr(state, "enemies", []))
        if not allies:
            return

        if "slot_bias" not in enemy.ai:
            enemy.ai["slot_bias"] = ((id(enemy) % 127) / 127.0) * math.tau
        if "squad_rank" not in enemy.ai:
            enemy.ai["squad_rank"] = (id(enemy) % 97) / 97.0

        now = float(getattr(state, "time", 0.0))
        brain = self._get_swarm_brain(state, now)
        self._update_swarm_brain(brain, allies, player_pos, player_vel, now)

        neighbors = self._get_neighbors(enemy, allies)
        sep = self._separation(enemy, neighbors)
        align = self._alignment(enemy, neighbors)
        coh = self._cohesion(enemy, neighbors)
        dodge = self._dodge_player_projectiles(enemy, getattr(state, "projectiles", []))

        dvec = player_pos - enemy.pos
        d = dvec.length()
        to_player = dvec.normalized() if d > 1e-6 else Vec2(1.0, 0.0)
        flank = Vec2(-to_player.y, to_player.x) * float(brain["flank_sign"])

        focus = Vec2(brain["focus_x"], brain["focus_y"])
        squad_r = float(brain["ring_r"])
        orbit_phase = float(brain["orbit_phase"])
        slot_ang = orbit_phase + enemy.ai["slot_bias"] + enemy.ai["squad_rank"] * math.tau
        slot_r = squad_r * (0.9 + 0.25 * math.sin(now * 1.7 + enemy.seed))
        slot_target = focus + Vec2(math.cos(slot_ang), math.sin(slot_ang)) * slot_r

        to_slot = (slot_target - enemy.pos).normalized()
        to_focus = (focus - enemy.pos).normalized()
        jitter = Vec2(math.sin(enemy.t * 4.2 + enemy.seed), math.cos(enemy.t * 4.7 + enemy.seed)) * 0.14

        mode = brain["mode"]
        if mode == "surge":
            move_dir = (
                to_focus * 1.35
                + to_player * 0.95
                + sep * self.separation_weight
                + align * self.align_weight
                + coh * self.cohesion_weight * 0.75
                + dodge * 0.95
                + flank * 0.22
                + jitter
            ).normalized()
            speed_mult = 1.22
        elif mode == "regroup":
            move_dir = (
                to_slot * 1.2
                + to_player * 0.4
                + coh * (self.cohesion_weight + 0.25)
                + align * (self.align_weight + 0.15)
                + sep * (self.separation_weight * 1.05)
                + dodge * 0.7
                + jitter
            ).normalized()
            speed_mult = 0.95
        else:  # encircle
            move_dir = (
                to_slot * 1.1
                + flank * 0.35
                + to_player * 0.45
                + sep * self.separation_weight
                + align * self.align_weight
                + coh * self.cohesion_weight
                + dodge * 0.9
                + jitter
            ).normalized()
            speed_mult = 1.05

        enemy.vel = move_dir * enemy.speed * speed_mult
        enemy.pos = enemy.pos + enemy.vel * dt

    def _get_swarm_brain(self, state, now: float) -> dict:
        brain = getattr(state, "_swarm_brain", None)
        if brain is None:
            brain = {
                "mode": "encircle",
                "mode_t": 1.8,
                "focus_x": 0.0,
                "focus_y": 0.0,
                "ring_r": 120.0,
                "flank_sign": 1.0 if random.random() < 0.5 else -1.0,
                "orbit_phase": random.uniform(0.0, math.tau),
                "last_t": now,
            }
            state._swarm_brain = brain
        return brain

    def _update_swarm_brain(self, brain: dict, allies, player_pos: Vec2, player_vel: Vec2, now: float) -> None:
        dt = max(0.0, now - float(brain.get("last_t", now)))
        brain["last_t"] = now
        if not allies:
            return

        center = Vec2(0.0, 0.0)
        for a in allies:
            center += a.pos
        center /= max(1, len(allies))

        to_player = player_pos - center
        d_center = to_player.length()
        dir_to_player = to_player.normalized() if d_center > 1e-6 else Vec2(1.0, 0.0)
        flank = Vec2(-dir_to_player.y, dir_to_player.x) * float(brain["flank_sign"])

        # Keep a shared tactical mode for coordinated behavior.
        brain["mode_t"] = float(brain.get("mode_t", 0.0)) - dt
        if brain["mode_t"] <= 0.0:
            if brain["mode"] == "encircle":
                brain["mode"] = "surge"
                brain["mode_t"] = 1.05 + random.uniform(0.0, 0.35)
            elif brain["mode"] == "surge":
                brain["mode"] = "regroup"
                brain["mode_t"] = 1.15 + random.uniform(0.0, 0.45)
                brain["flank_sign"] *= -1.0
            else:
                brain["mode"] = "encircle"
                brain["mode_t"] = 1.8 + random.uniform(0.0, 0.7)

        # Shared orbit progression makes slots rotate as a team.
        orbit_speed = 0.62 if brain["mode"] == "encircle" else 0.35 if brain["mode"] == "regroup" else 0.22
        brain["orbit_phase"] = float(brain.get("orbit_phase", 0.0)) + dt * orbit_speed

        n = max(1, len(allies))
        base_r = max(52.0, 126.0 - min(55.0, n * 4.5))
        if brain["mode"] == "surge":
            ring_r = max(40.0, base_r * 0.62)
            lead = 0.22
        elif brain["mode"] == "regroup":
            ring_r = base_r * 1.2
            lead = 0.5
        else:
            ring_r = base_r
            lead = 0.34
        brain["ring_r"] = ring_r

        # Keep lead time short; large prediction makes swarms appear to retreat
        # when the player advances.
        lead_time = 0.16 if brain["mode"] == "encircle" else 0.08 if brain["mode"] == "surge" else 0.12
        predicted = player_pos + player_vel * lead_time
        if brain["mode"] == "encircle":
            focus = predicted + flank * (22.0 + n * 1.2)
        elif brain["mode"] == "regroup":
            focus = predicted - dir_to_player * min(45.0, 16.0 + n * 2.0)
        else:
            focus = predicted
        brain["focus_x"] = focus.x
        brain["focus_y"] = focus.y

    def _get_swarm_allies(self, all_enemies):
        allies = []
        for other in all_enemies:
            behavior = getattr(other, "behavior", "")
            is_swarm = behavior == "swarm" or getattr(behavior.__class__, "__name__", "").lower() == "swarm"
            if is_swarm:
                allies.append(other)
        return allies

    def _get_neighbors(self, enemy, allies):
        neighbors = []
        r2 = self.perception_radius * self.perception_radius
        for other in allies:
            if other is enemy:
                continue
            if (other.pos - enemy.pos).length_squared() < r2:
                neighbors.append(other)
        return neighbors

    def _separation(self, enemy, neighbors) -> Vec2:
        steer = Vec2(0.0, 0.0)
        count = 0
        for other in neighbors:
            dvec = enemy.pos - other.pos
            d = dvec.length()
            if d > 1e-6:
                steer += dvec.normalized() / max(0.2, d)
                count += 1
        if count <= 0:
            return Vec2(0.0, 0.0)
        return steer / count

    def _alignment(self, enemy, neighbors) -> Vec2:
        avg_vel = Vec2(0.0, 0.0)
        count = 0
        for other in neighbors:
            if other.vel.length_squared() > 1e-6:
                avg_vel += other.vel.normalized()
                count += 1
        if count <= 0:
            return Vec2(0.0, 0.0)
        avg_vel /= count
        if avg_vel.length_squared() <= 1e-6:
            return Vec2(0.0, 0.0)
        return (avg_vel - enemy.vel.normalized()).normalized()

    def _cohesion(self, enemy, neighbors) -> Vec2:
        center = Vec2(0.0, 0.0)
        count = 0
        for other in neighbors:
            center += other.pos
            count += 1
        if count <= 0:
            return Vec2(0.0, 0.0)
        center /= count
        return (center - enemy.pos).normalized()

    def _dodge_player_projectiles(self, enemy, projectiles, danger_radius: float = 90.0) -> Vec2:
        steer = Vec2(0.0, 0.0)
        count = 0
        for p in projectiles:
            if getattr(p, "owner", "") != "player":
                continue
            rel = enemy.pos - p.pos
            d2 = rel.length_squared()
            if d2 > danger_radius * danger_radius:
                continue
            vel = getattr(p, "vel", Vec2(0.0, 0.0))
            if vel.length_squared() <= 1e-6:
                continue
            toward = rel.dot(vel.normalized())
            if toward >= 0.0:
                continue
            ev = Vec2(-vel.y, vel.x).normalized()
            sign = 1.0 if rel.dot(ev) >= 0.0 else -1.0
            steer += ev * sign * (1.0 - (math.sqrt(d2) / danger_radius))
            count += 1
            if count >= 4:
                break
        if count <= 0:
            return Vec2(0.0, 0.0)
        return (steer / count).normalized()
