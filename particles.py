"""Simple Panda3D particle effects."""

from __future__ import annotations

import random

from panda3d.core import CardMaker, LineSegs, NodePath

from utils import Vec2


class ParticleSystem:
    def __init__(self, parent: NodePath | None = None):
        self._parent = parent
        if self._parent is None:
            from direct.showbase import ShowBaseGlobal

            self._parent = getattr(ShowBaseGlobal, "render", None)
        self.root = self._parent.attachNewNode("particle_fx") if self._parent is not None else NodePath("particle_fx")
        self._effects: list[dict] = []

    def _spawn_quad(self, pos: Vec2, size: float, color, ttl: float, vel: Vec2 | None = None, z: float = 12.0) -> None:
        cm = CardMaker("pfx_quad")
        cm.setFrame(-size, size, -size, size)
        node = self.root.attachNewNode(cm.generate())
        node.setP(-90)
        node.setPos(pos.x, pos.y, z)
        # Boost alpha/color for bloom?
        node.setColor(color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, 1.0)
        node.setTransparency(True)
        self._effects.append({"node": node, "ttl": float(ttl), "life": float(ttl), "vel": vel or Vec2(0.0, 0.0), "kind": "quad"})

    def _spawn_line(self, start: Vec2, end: Vec2, color, ttl: float, thickness: float = 2.0) -> None:
        ls = LineSegs("pfx_line")
        ls.setColor(color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, 1.0)
        ls.setThickness(float(thickness))
        ls.moveTo(start.x, start.y, 13.0)
        ls.drawTo(end.x, end.y, 13.0)
        node = self.root.attachNewNode(ls.create())
        node.setTransparency(True)
        self._effects.append({"node": node, "ttl": float(ttl), "life": float(ttl), "vel": Vec2(0.0, 0.0), "kind": "line"})

    def update(self, dt: float):
        step = float(dt)
        for fx in list(self._effects):
            fx["ttl"] -= step
            node = fx["node"]
            if fx["kind"] == "quad":
                vel = fx["vel"]
                node.setPos(node.getX() + vel.x * step, node.getY() + vel.y * step, node.getZ())
            life = max(1e-4, fx["life"])
            a = max(0.0, min(1.0, fx["ttl"] / life))
            node.setAlphaScale(a)
            if fx["ttl"] <= 0.0:
                node.removeNode()
                self._effects.remove(fx)

    def render(self, shake: Vec2):
        if not self.root:
            return
        self.root.setPos(float(shake.x), float(shake.y), 0.0)

    def add_hit_particles(self, pos: Vec2, color):
        for _ in range(5):
            v = Vec2(random.uniform(-90.0, 90.0), random.uniform(-90.0, 90.0))
            self._spawn_quad(pos, random.uniform(2.0, 3.5), color, ttl=0.28, vel=v, z=12.5)

    def add_death_explosion(self, pos: Vec2, color, behavior=""):
        count = 8 if str(behavior or "").startswith("boss_") else 5
        for _ in range(count):
            v = Vec2(random.uniform(-120.0, 120.0), random.uniform(-120.0, 120.0))
            self._spawn_quad(pos, random.uniform(2.5, 4.5), color, ttl=0.35, vel=v, z=12.5)

    def add_muzzle_flash(self, pos: Vec2, direction: Vec2):
        self._spawn_quad(pos + direction * 4.0, 3.2, (255, 230, 180), ttl=0.08, vel=direction * 40.0, z=13.0)

    def add_step_dust(self, pos: Vec2, direction: Vec2):
        if random.random() < 0.45:
            self._spawn_quad(pos - direction * 2.0, 1.7, (170, 170, 170), ttl=0.18, vel=direction * -18.0, z=10.5)

    def add_dash_trail(self, pos: Vec2):
        self._spawn_quad(pos, 3.0, (160, 220, 255), ttl=0.15, vel=Vec2(0.0, 0.0), z=11.5)

    def add_dash_effect(self, pos: Vec2, direction: Vec2):
        for _ in range(6):
            v = direction * random.uniform(35.0, 105.0) + Vec2(random.uniform(-35.0, 35.0), random.uniform(-35.0, 35.0))
            self._spawn_quad(pos, random.uniform(1.8, 3.2), (180, 240, 255), ttl=0.26, vel=v, z=12.0)

    def add_laser_beam(self, start: Vec2, end: Vec2, color):
        self._spawn_line(start, end, color, ttl=0.1, thickness=2.4)

    def add_powerup_collection(self, pos: Vec2, color):
        for _ in range(6):
            v = Vec2(random.uniform(-95.0, 95.0), random.uniform(-95.0, 95.0))
            self._spawn_quad(pos, random.uniform(2.0, 3.3), color, ttl=0.3, vel=v, z=12.0)

    def add_vortex_swirl(self, pos: Vec2, t: float, radius: float):
        if random.random() > 0.4:
            return
        ang = float(t) * 9.0 + random.uniform(-0.45, 0.45)
        p = Vec2(pos.x + radius * 0.55 * random.uniform(0.3, 1.0) * random.choice([-1.0, 1.0]), pos.y)
        v = Vec2(-40.0 * random.choice([-1.0, 1.0]), 50.0 * random.choice([-1.0, 1.0]))
        self._spawn_quad(Vec2(p.x, p.y + radius * 0.15 * random.uniform(-1.0, 1.0)), 1.6, (190, 150, 255), ttl=0.24, vel=v, z=12.3)

    def add_shield_hit(self, pos: Vec2, amount):
        size = min(6.0, 2.0 + float(amount) * 0.08)
        self._spawn_quad(pos, size, (130, 220, 255), ttl=0.18, vel=Vec2(0.0, 0.0), z=13.0)

    def destroy(self) -> None:
        for fx in list(self._effects):
            fx["node"].removeNode()
        self._effects.clear()
        if self.root:
            self.root.removeNode()
