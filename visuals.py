"""Visual rendering system."""

from __future__ import annotations

import math
import random

import pyglet
from pyglet import shapes
from pyglet.graphics import Group

from config import ENEMY_COLORS, SCREEN_H
from utils import to_iso, Vec2, enemy_behavior_name


class GroupCache:
    """Cache for rendering groups for depth sorting."""

    def __init__(self):
        self._cache: dict[int, object] = {}

    def get(self, order: int):
        g = self._cache.get(order)
        if g is None:
            g = Group(order=order)
            self._cache[order] = g
        return g


class RenderHandle:
    """Handle for managing render objects."""

    def __init__(self, *objs):
        self.objs = list(objs)

    def set_group(self, group):
        if group is None:
            return
        for o in self.objs:
            o.group = group

    def delete(self):
        for o in self.objs:
            if hasattr(o, "delete"):
                o.delete()


class Visuals:
    """Visual rendering system."""

    def __init__(self, batch, group_cache: GroupCache):
        self.batch = batch
        self.groups = group_cache
        self._scene_group = Group(order=-20000)
        self._overlay_group = Group(order=22000)

        self._enemy_handles: dict[int, RenderHandle] = {}
        self._proj_handles: dict[int, RenderHandle] = {}
        self._power_handles: dict[int, RenderHandle] = {}
        self._obstacle_handles: dict[int, RenderHandle] = {}
        self._trap_handles: dict[int, RenderHandle] = {}
        self._laser_handles: dict[int, RenderHandle] = {}
        self._thunder_handles: dict[int, RenderHandle] = {}
        self._player_handle: RenderHandle | None = None
        self._scene_stars: list[tuple[shapes.Circle, float, float, float]] = []
        self._scene_rings: list[shapes.Arc] = []
        self._vignette: list[shapes.Rectangle] = []
        self._init_scene_fx()

    def _init_scene_fx(self) -> None:
        self._scene_glows = [
            shapes.Circle(0, 0, 320, color=(30, 75, 130), batch=self.batch, group=self._scene_group),
            shapes.Circle(0, 0, 240, color=(160, 70, 120), batch=self.batch, group=self._scene_group),
            shapes.Circle(0, 0, 180, color=(70, 180, 165), batch=self.batch, group=self._scene_group),
        ]
        self._scene_glows[0].opacity = 28
        self._scene_glows[1].opacity = 18
        self._scene_glows[2].opacity = 16

        for i in range(3):
            ring = shapes.Arc(
                0,
                0,
                180 + i * 42,
                segments=128,
                thickness=2,
                color=(130, 185, 245),
                batch=self.batch,
                group=self._scene_group,
            )
            ring.opacity = 22 + i * 5
            self._scene_rings.append(ring)

        for _ in range(32):
            star = shapes.Circle(
                random.uniform(0.0, 1920.0),
                random.uniform(0.0, 1080.0),
                random.uniform(1.2, 2.6),
                color=(210, 235, 255),
                batch=self.batch,
                group=self._scene_group,
            )
            star.opacity = random.randint(20, 70)
            self._scene_stars.append((star, random.uniform(-8.0, 8.0), random.uniform(-5.0, 5.0), random.uniform(0.0, math.tau)))

        for _ in range(4):
            vg = shapes.Rectangle(0, 0, 1, 1, color=(0, 0, 0), batch=self.batch, group=self._overlay_group)
            vg.opacity = 0
            self._vignette.append(vg)

    def _set_depth(self, handle: RenderHandle, y: float) -> None:
        handle.set_group(self.groups.get(int(SCREEN_H + 1000 - y)))

    def sync_scene(self, t: float, shake: Vec2, combat_intensity: float = 0.0) -> None:
        center_x, center_y = to_iso(Vec2(0.0, 0.0), shake)
        ci = max(0.0, min(1.0, float(combat_intensity)))

        offsets = ((-220.0, 120.0), (210.0, -60.0), (30.0, 190.0))
        for i, glow in enumerate(self._scene_glows):
            ox, oy = offsets[i]
            glow.x = center_x + ox + math.sin(t * (0.25 + i * 0.07)) * 30.0
            glow.y = center_y + oy + math.cos(t * (0.22 + i * 0.09)) * 24.0
            glow.opacity = int((14 + i * 6) + (16 + i * 4) * (0.5 + 0.5 * math.sin(t * (0.7 + i * 0.2))))

        for i, ring in enumerate(self._scene_rings):
            ring.x = center_x
            ring.y = center_y
            ring.radius = (180 + i * 42) + 6.0 * math.sin(t * (0.8 + i * 0.3))
            ring.opacity = int(16 + 10 * i + (8 + 10 * ci) * (0.5 + 0.5 * math.sin(t * (1.1 + i * 0.15))))

        for star, vx, vy, phase in self._scene_stars:
            star.x += vx * (0.22 + ci * 0.6)
            star.y += vy * (0.22 + ci * 0.6)
            if star.x < -24:
                star.x = 1944
            elif star.x > 1944:
                star.x = -24
            if star.y < -24:
                star.y = 1104
            elif star.y > 1104:
                star.y = -24
            star.opacity = int(14 + 64 * (0.5 + 0.5 * math.sin(t * 1.4 + phase)))

        top, bot, left, right = self._vignette
        top.x, top.y, top.width, top.height = 0, 1048, 1920, 32
        bot.x, bot.y, bot.width, bot.height = 0, 0, 1920, 32
        left.x, left.y, left.width, left.height = 0, 0, 38, 1080
        right.x, right.y, right.width, right.height = 1882, 0, 38, 1080
        v_op = int(22 + 18 * ci)
        top.opacity = v_op
        bot.opacity = v_op
        left.opacity = int(v_op * 0.8)
        right.opacity = int(v_op * 0.8)

    def make_player(self):
        """Create player visual."""
        sh = shapes.Ellipse(0, 0, 30, 12, color=(0, 0, 0), batch=self.batch)
        sh.opacity = 130

        # Glow + layered body rig (helmet, torso, limbs, gear).
        glow = shapes.Circle(0, 0, 22, color=(60, 140, 220), batch=self.batch)
        glow.opacity = 65
        glow2 = shapes.Circle(0, 0, 28, color=(80, 120, 220), batch=self.batch)
        glow2.opacity = 28

        torso_back = shapes.Ellipse(0, 0, 18, 16, color=(20, 38, 62), batch=self.batch)
        torso_back.opacity = 230
        outline = shapes.Circle(0, 0, 16, color=(10, 20, 35), batch=self.batch)
        outline.opacity = 255
        body = shapes.Circle(0, 0, 14, color=(70, 160, 220), batch=self.batch)
        chest = shapes.Ellipse(0, 0, 10, 9, color=(42, 108, 164), batch=self.batch)
        core = shapes.Circle(0, 0, 6, color=(130, 228, 255), batch=self.batch)
        core_glow = shapes.Circle(0, 0, 10, color=(145, 220, 255), batch=self.batch)
        core_glow.opacity = 42
        highlight = shapes.Circle(0, 0, 5, color=(255, 255, 255), batch=self.batch)
        highlight.opacity = 60

        helmet = shapes.Ellipse(0, 0, 13, 10, color=(92, 180, 240), batch=self.batch)
        visor = shapes.Rectangle(0, 0, 14, 4, color=(238, 245, 255), batch=self.batch)
        visor.anchor_x = 7
        visor.anchor_y = 2
        visor_glow = shapes.Rectangle(0, 0, 16, 2, color=(200, 236, 255), batch=self.batch)
        visor_glow.anchor_x = 8
        visor_glow.anchor_y = 1
        visor_glow.opacity = 110

        shoulder_l = shapes.Circle(0, 0, 4, color=(54, 108, 152), batch=self.batch)
        shoulder_r = shapes.Circle(0, 0, 4, color=(54, 108, 152), batch=self.batch)
        arm_l = shapes.Line(0, 0, 0, 0, thickness=4, color=(44, 86, 128), batch=self.batch)
        arm_r = shapes.Line(0, 0, 0, 0, thickness=4, color=(44, 86, 128), batch=self.batch)
        arm_l.opacity = 220
        arm_r.opacity = 220

        leg_l = shapes.Line(0, 0, 0, 0, thickness=4, color=(36, 78, 120), batch=self.batch)
        leg_r = shapes.Line(0, 0, 0, 0, thickness=4, color=(36, 78, 120), batch=self.batch)
        boot_l = shapes.Circle(0, 0, 3, color=(165, 210, 245), batch=self.batch)
        boot_r = shapes.Circle(0, 0, 3, color=(165, 210, 245), batch=self.batch)

        backpack = shapes.Rectangle(0, 0, 12, 12, color=(30, 45, 60), batch=self.batch)
        backpack.anchor_x = 6
        backpack.anchor_y = 6
        backpack.opacity = 220
        antenna = shapes.Line(0, 0, 0, 0, thickness=2, color=(140, 190, 230), batch=self.batch)
        antenna.opacity = 180
        antenna_tip = shapes.Circle(0, 0, 2, color=(190, 240, 255), batch=self.batch)
        antenna_tip.opacity = 180

        gun = shapes.Line(0, 0, 0, 0, thickness=3, color=(230, 230, 240), batch=self.batch)
        gun.opacity = 210
        gun_core = shapes.Line(0, 0, 0, 0, thickness=1, color=(255, 255, 255), batch=self.batch)
        gun_core.opacity = 220
        thruster_l = shapes.Line(0, 0, 0, 0, thickness=4, color=(130, 210, 255), batch=self.batch)
        thruster_r = shapes.Line(0, 0, 0, 0, thickness=4, color=(130, 210, 255), batch=self.batch)
        thruster_l.opacity = 0
        thruster_r.opacity = 0

        # Shield/laser aura rings (toggled in sync)
        shield_ring = shapes.Arc(0, 0, 19, segments=48, thickness=4, color=(120, 220, 255), batch=self.batch)
        shield_ring.opacity = 0
        shield_ring2 = shapes.Arc(0, 0, 24, segments=48, thickness=2, color=(255, 255, 255), batch=self.batch)
        shield_ring2.opacity = 0
        laser_ring = shapes.Arc(0, 0, 22, segments=64, thickness=3, color=(255, 120, 255), batch=self.batch)
        laser_ring.opacity = 0

        self._player_handle = RenderHandle(
            sh,
            glow,
            glow2,
            shield_ring2,
            shield_ring,
            laser_ring,
            torso_back,
            leg_l,
            leg_r,
            boot_l,
            boot_r,
            outline,
            body,
            chest,
            core_glow,
            core,
            highlight,
            backpack,
            antenna,
            antenna_tip,
            helmet,
            visor,
            visor_glow,
            shoulder_l,
            shoulder_r,
            arm_l,
            arm_r,
            gun,
            gun_core,
            thruster_l,
            thruster_r,
        )

    def sync_player(self, player, shake: Vec2, t: float = 0.0, aim_dir: Vec2 | None = None):
        """Update player visual position."""
        assert self._player_handle is not None
        (
            sh,
            glow,
            glow2,
            shield_ring2,
            shield_ring,
            laser_ring,
            torso_back,
            leg_l,
            leg_r,
            boot_l,
            boot_r,
            outline,
            body,
            chest,
            core_glow,
            core,
            highlight,
            backpack,
            antenna,
            antenna_tip,
            helmet,
            visor,
            visor_glow,
            shoulder_l,
            shoulder_r,
            arm_l,
            arm_r,
            gun,
            gun_core,
            thruster_l,
            thruster_r,
        ) = self._player_handle.objs
        sx, sy = to_iso(player.pos, shake)
        if aim_dir is None or aim_dir.length() <= 1e-6:
            aim_dir = Vec2(1, 0)
        bob = math.sin(t * 6.0) * 1.5
        gait = math.sin(t * 10.5)
        lean_x = aim_dir.x * 2.2
        lean_y = aim_dir.y * 1.1

        cx = sx + lean_x
        cy = sy + bob + lean_y
        sh.x, sh.y = sx, sy - 19
        glow.x, glow.y = cx, cy
        glow2.x, glow2.y = cx, cy + 1
        torso_back.x, torso_back.y = cx - 0.5, cy + 0.5
        outline.x, outline.y = cx, cy
        body.x, body.y = cx, cy
        chest.x, chest.y = cx + 1.0, cy - 1.0
        core_glow.x, core_glow.y = cx + 1.0, cy - 1.0
        core.x, core.y = cx + 1.0, cy - 1.0
        core_glow.opacity = int(34 + 18 * (0.5 + 0.5 * math.sin(t * 7.8)))
        highlight.x, highlight.y = cx - 4, cy + 5

        hip_x, hip_y = cx - 1, cy - 8
        leg_l.x, leg_l.y = hip_x - 3, hip_y
        leg_l.x2, leg_l.y2 = hip_x - 3 + gait * 1.2, hip_y - 7
        leg_r.x, leg_r.y = hip_x + 3, hip_y
        leg_r.x2, leg_r.y2 = hip_x + 3 - gait * 1.2, hip_y - 7
        boot_l.x, boot_l.y = leg_l.x2, leg_l.y2 - 1
        boot_r.x, boot_r.y = leg_r.x2, leg_r.y2 - 1

        backpack.x, backpack.y = cx - 12, cy + 1
        antenna.x, antenna.y = backpack.x - 1, backpack.y + 4
        antenna.x2, antenna.y2 = antenna.x - 2, antenna.y + 8
        antenna_tip.x, antenna_tip.y = antenna.x2, antenna.y2

        helmet.x, helmet.y = cx + 2, cy + 5
        visor.x, visor.y = cx + 3, cy + 5
        visor_glow.x, visor_glow.y = cx + 3, cy + 5
        visor_glow.opacity = int(90 + 40 * (0.5 + 0.5 * math.sin(t * 5.4)))

        # Aim direction affects gun orientation.
        gun_len = 18
        gx = cx + 4
        gy = cy + 2
        gun.x, gun.y = gx, gy
        gun.x2, gun.y2 = gx + aim_dir.x * gun_len, gy + aim_dir.y * gun_len * 0.65
        gun_core.x, gun_core.y = gun.x, gun.y
        gun_core.x2, gun_core.y2 = gun.x2, gun.y2
        shoulder_l.x, shoulder_l.y = cx - 6, cy + 1
        shoulder_r.x, shoulder_r.y = cx + 5, cy + 1
        arm_l.x, arm_l.y = shoulder_l.x, shoulder_l.y
        arm_l.x2, arm_l.y2 = cx - 1, cy + 4
        arm_r.x, arm_r.y = shoulder_r.x, shoulder_r.y
        arm_r.x2, arm_r.y2 = gun.x, gun.y

        if bool(getattr(player, "is_dashing", False)):
            dash_pulse = 0.6 + 0.4 * math.sin(t * 40.0)
            back = Vec2(-aim_dir.x, -aim_dir.y)
            tx1, ty1 = cx - 9, cy - 1
            tx2, ty2 = cx - 3, cy - 4
            thruster_l.x, thruster_l.y = tx1, ty1
            thruster_l.x2, thruster_l.y2 = tx1 + back.x * (20 + 12 * dash_pulse), ty1 + back.y * (14 + 10 * dash_pulse)
            thruster_r.x, thruster_r.y = tx2, ty2
            thruster_r.x2, thruster_r.y2 = tx2 + back.x * (20 + 12 * dash_pulse), ty2 + back.y * (14 + 10 * dash_pulse)
            thruster_l.opacity = int(120 + 110 * dash_pulse)
            thruster_r.opacity = int(90 + 90 * dash_pulse)
        else:
            thruster_l.opacity = 0
            thruster_r.opacity = 0

        # Shield aura
        if getattr(player, "shield", 0) > 0:
            pulse = 0.65 + 0.35 * math.sin(t * 6.5)
            shield_ring.x, shield_ring.y = cx, cy
            shield_ring2.x, shield_ring2.y = cx, cy
            shield_ring.radius = 18 + 2.0 * pulse
            shield_ring2.radius = 24 + 3.0 * pulse
            shield_ring.opacity = int(90 + min(120, player.shield) * 1.0 * pulse)
            shield_ring2.opacity = int(60 + min(120, player.shield) * 0.5 * pulse)
        else:
            shield_ring.opacity = 0
            shield_ring2.opacity = 0

        # Laser aura
        if getattr(player, "laser_until", 0.0) > t:
            pulse = 0.6 + 0.4 * math.sin(t * 10.0)
            laser_ring.x, laser_ring.y = cx, cy
            laser_ring.radius = 22 + 3.0 * pulse
            laser_ring.opacity = int(160 * pulse)
        else:
            laser_ring.opacity = 0

        self._set_depth(self._player_handle, cy)

    def ensure_enemy(self, enemy):
        """Ensure enemy visual exists."""
        if id(enemy) in self._enemy_handles:
            return
        behavior = enemy_behavior_name(enemy)
        base = ENEMY_COLORS.get(behavior, (200, 120, 120))

        sh = shapes.Ellipse(0, 0, 20, 7, color=(0, 0, 0), batch=self.batch)
        sh.opacity = 110

        if behavior.startswith("boss_"):
            sh.width = 40
            sh.height = 14
            body = shapes.Circle(0, 0, 22, color=base, batch=self.batch)
            glow = shapes.Circle(0, 0, 30, color=base, batch=self.batch)
            glow.opacity = 45
            ring = shapes.Arc(0, 0, 28, segments=64, thickness=6, color=(20, 25, 40), batch=self.batch)
            ring.opacity = 220
            crown = shapes.Arc(0, 0, 24, segments=32, thickness=4, color=(255, 255, 255), batch=self.batch)
            crown.opacity = 60

            if behavior == "boss_thunder":
                sig = shapes.Line(0, 0, 0, 0, thickness=3, color=(200, 230, 255), batch=self.batch)
                sig.opacity = 220
                self._enemy_handles[id(enemy)] = RenderHandle(sh, glow, ring, crown, body, sig)
            elif behavior == "boss_laser":
                eye = shapes.Circle(0, 0, 6, color=(255, 255, 255), batch=self.batch)
                eye.opacity = 200
                iris = shapes.Circle(0, 0, 3, color=(255, 120, 255), batch=self.batch)
                iris.opacity = 220
                self._enemy_handles[id(enemy)] = RenderHandle(sh, glow, ring, crown, body, eye, iris)
            elif behavior == "boss_trapmaster":
                gear = shapes.Arc(0, 0, 26, segments=32, thickness=5, color=(255, 210, 120), batch=self.batch)
                gear.opacity = 120
                self._enemy_handles[id(enemy)] = RenderHandle(sh, glow, ring, crown, body, gear)
            elif behavior == "boss_swarmqueen":
                orb1 = shapes.Circle(0, 0, 6, color=(255, 255, 255), batch=self.batch)
                orb2 = shapes.Circle(0, 0, 6, color=(255, 255, 255), batch=self.batch)
                orb3 = shapes.Circle(0, 0, 6, color=(255, 255, 255), batch=self.batch)
                orb1.opacity = 90
                orb2.opacity = 90
                orb3.opacity = 90
                self._enemy_handles[id(enemy)] = RenderHandle(sh, glow, ring, crown, body, orb1, orb2, orb3)
            elif behavior == "boss_brute":
                horn = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(255, 250, 240), batch=self.batch)
                horn.opacity = 220
                scar = shapes.Line(0, 0, 0, 0, thickness=4, color=(40, 10, 10), batch=self.batch)
                scar.opacity = 200
                self._enemy_handles[id(enemy)] = RenderHandle(sh, glow, ring, crown, body, horn, scar)
            else:
                self._enemy_handles[id(enemy)] = RenderHandle(sh, glow, ring, crown, body)
            return

        if behavior == "bomber":
            body = shapes.Circle(0, 0, 14, color=base, batch=self.batch)
            core = shapes.Circle(0, 0, 8, color=(255, 255, 255), batch=self.batch)
            core.opacity = 200
            # Orbiting fuse spark
            fuse = shapes.Circle(0, 0, 3, color=(255, 200, 60), batch=self.batch)
            fuse.opacity = 220
            fuse_trail = shapes.Arc(0, 0, 16, segments=20, thickness=2, color=(255, 180, 80), batch=self.batch)
            fuse_trail.opacity = 60
            self._enemy_handles[id(enemy)] = RenderHandle(sh, body, core, fuse, fuse_trail)
            return

        if behavior == "tank":
            sh.width = 28
            sh.height = 10
            body = shapes.Circle(0, 0, 16, color=base, batch=self.batch)
            armor = shapes.Arc(0, 0, 18, segments=40, thickness=5, color=(30, 40, 55), batch=self.batch)
            armor.opacity = 220
            plate = shapes.Rectangle(0, 0, 18, 10, color=(45, 70, 65), batch=self.batch)
            plate.anchor_x = 9
            plate.anchor_y = 5
            plate.opacity = 220
            eye = shapes.Circle(0, 0, 3, color=(20, 20, 20), batch=self.batch)
            # Rotating outer shield ring
            shield_ring = shapes.Arc(0, 0, 22, segments=24, thickness=3, color=(80, 180, 80), batch=self.batch)
            shield_ring.opacity = 70
            self._enemy_handles[id(enemy)] = RenderHandle(sh, body, armor, plate, eye, shield_ring)
            return

        if behavior == "ranged":
            body = shapes.Circle(0, 0, 12, color=base, batch=self.batch)
            cannon = shapes.Rectangle(0, 0, 18, 6, color=(30, 40, 55), batch=self.batch)
            cannon.anchor_x = 4
            cannon.anchor_y = 3
            cannon.opacity = 230
            muzzle = shapes.Circle(0, 0, 3, color=(255, 255, 255), batch=self.batch)
            muzzle.opacity = 160
            eye = shapes.Circle(0, 0, 2.5, color=(20, 20, 20), batch=self.batch)
            # Scope crosshair lines
            scope_h = shapes.Line(0, 0, 0, 0, thickness=1, color=(180, 220, 255), batch=self.batch)
            scope_v = shapes.Line(0, 0, 0, 0, thickness=1, color=(180, 220, 255), batch=self.batch)
            scope_h.opacity = 100
            scope_v.opacity = 100
            self._enemy_handles[id(enemy)] = RenderHandle(sh, body, cannon, muzzle, eye, scope_h, scope_v)
            return

        if behavior == "charger":
            body = shapes.Circle(0, 0, 13, color=base, batch=self.batch)
            horn1 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(250, 240, 220), batch=self.batch)
            horn2 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(250, 240, 220), batch=self.batch)
            horn1.opacity = 220
            horn2.opacity = 220
            eye = shapes.Circle(0, 0, 2.5, color=(20, 20, 20), batch=self.batch)
            # Speed trail lines
            trail1 = shapes.Line(0, 0, 0, 0, thickness=2, color=(255, 200, 100), batch=self.batch)
            trail2 = shapes.Line(0, 0, 0, 0, thickness=2, color=(255, 200, 100), batch=self.batch)
            trail1.opacity = 0
            trail2.opacity = 0
            self._enemy_handles[id(enemy)] = RenderHandle(sh, body, horn1, horn2, eye, trail1, trail2)
            return

        if behavior == "flyer":
            body = shapes.Circle(0, 0, 11, color=base, batch=self.batch)
            wing1 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=base, batch=self.batch)
            wing2 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=base, batch=self.batch)
            wing1.opacity = 170
            wing2.opacity = 170
            tail = shapes.Line(0, 0, 0, 0, thickness=2, color=(230, 230, 240), batch=self.batch)
            tail.opacity = 200
            eye = shapes.Circle(0, 0, 2, color=(20, 20, 20), batch=self.batch)
            # Jet trail
            jet = shapes.Line(0, 0, 0, 0, thickness=3, color=(150, 200, 255), batch=self.batch)
            jet.opacity = 90
            self._enemy_handles[id(enemy)] = RenderHandle(sh, body, wing1, wing2, tail, eye, jet)
            return

        if behavior == "spitter":
            body = shapes.Circle(0, 0, 12, color=base, batch=self.batch)
            sac1 = shapes.Circle(0, 0, 5, color=(255, 240, 170), batch=self.batch)
            sac2 = shapes.Circle(0, 0, 4, color=(255, 240, 170), batch=self.batch)
            sac1.opacity = 160
            sac2.opacity = 140
            mouth = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(30, 30, 30), batch=self.batch)
            mouth.opacity = 210
            # Pulsing acid glow
            acid_glow = shapes.Circle(0, 0, 16, color=(180, 255, 80), batch=self.batch)
            acid_glow.opacity = 25
            self._enemy_handles[id(enemy)] = RenderHandle(sh, body, sac1, sac2, mouth, acid_glow)
            return

        if behavior == "swarm":
            sh.width = 16
            sh.height = 6
            body = shapes.Circle(0, 0, 9, color=base, batch=self.batch)
            dot1 = shapes.Circle(0, 0, 2.5, color=(255, 255, 255), batch=self.batch)
            dot2 = shapes.Circle(0, 0, 2.5, color=(255, 255, 255), batch=self.batch)
            dot3 = shapes.Circle(0, 0, 2.5, color=(255, 255, 255), batch=self.batch)
            dot1.opacity = 120
            dot2.opacity = 120
            dot3.opacity = 120
            # Flickering antenna lines
            ant1 = shapes.Line(0, 0, 0, 0, thickness=1, color=(255, 200, 255), batch=self.batch)
            ant2 = shapes.Line(0, 0, 0, 0, thickness=1, color=(255, 200, 255), batch=self.batch)
            ant1.opacity = 110
            ant2.opacity = 110
            self._enemy_handles[id(enemy)] = RenderHandle(sh, body, dot1, dot2, dot3, ant1, ant2)
            return

        if behavior == "chaser":
            body = shapes.Circle(0, 0, 12, color=base, batch=self.batch)
            # Pulsing aura ring
            aura = shapes.Arc(0, 0, 18, segments=32, thickness=2, color=base, batch=self.batch)
            aura.opacity = 50
            spike1 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(250, 250, 250), batch=self.batch)
            spike2 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(250, 250, 250), batch=self.batch)
            spike3 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(250, 250, 250), batch=self.batch)
            spike1.opacity = 160
            spike2.opacity = 160
            spike3.opacity = 160
            eye1 = shapes.Circle(0, 0, 2, color=(20, 20, 20), batch=self.batch)
            eye2 = shapes.Circle(0, 0, 2, color=(20, 20, 20), batch=self.batch)
            self._enemy_handles[id(enemy)] = RenderHandle(sh, body, aura, spike1, spike2, spike3, eye1, eye2)
            return

        if behavior == "engineer":
            body = shapes.Circle(0, 0, 13, color=base, batch=self.batch)
            backpack = shapes.Rectangle(0, 0, 12, 10, color=(40, 60, 70), batch=self.batch)
            backpack.anchor_x = 6
            backpack.anchor_y = 5
            backpack.opacity = 220
            visor = shapes.Rectangle(0, 0, 10, 4, color=(230, 255, 245), batch=self.batch)
            visor.anchor_x = 5
            visor.anchor_y = 2
            visor.opacity = 210
            tool = shapes.Line(0, 0, 10, 10, thickness=2, color=(240, 240, 240), batch=self.batch)
            tool2 = shapes.Line(0, 0, 10, -10, thickness=2, color=(240, 240, 240), batch=self.batch)
            # Rotating gear arc
            gear = shapes.Arc(0, 0, 17, segments=16, thickness=2, color=(80, 240, 180), batch=self.batch)
            gear.opacity = 60
            self._enemy_handles[id(enemy)] = RenderHandle(sh, body, backpack, visor, tool, tool2, gear)
            return

        if behavior == "egg_sac":
            # Organic pulsating sac
            sh.width = 18
            sh.height = 8
            body = shapes.Circle(0, 0, 15, color=(200, 180, 190), batch=self.batch)
            vein1 = shapes.Arc(0, 0, 14, segments=16, thickness=2, color=(160, 60, 80), batch=self.batch)
            vein1.opacity = 140
            vein2 = shapes.Arc(0, 0, 10, segments=16, thickness=2, color=(160, 60, 80), batch=self.batch)
            vein2.rotation = 90
            vein2.opacity = 140
            core = shapes.Circle(0, 0, 6, color=(255, 100, 120), batch=self.batch)
            core.opacity = 180
            self._enemy_handles[id(enemy)] = RenderHandle(sh, body, vein1, vein2, core)
            return

        body = shapes.Circle(0, 0, 12, color=base, batch=self.batch)
        shine = shapes.Circle(0, 0, 7, color=(255, 255, 255), batch=self.batch)
        shine.opacity = 60
        eye1 = shapes.Circle(0, 0, 2, color=(20, 20, 20), batch=self.batch)
        eye2 = shapes.Circle(0, 0, 2, color=(20, 20, 20), batch=self.batch)
        self._enemy_handles[id(enemy)] = RenderHandle(sh, body, shine, eye1, eye2)

    def sync_enemy(self, enemy, shake: Vec2):
        """Update enemy visual position."""
        h = self._enemy_handles[id(enemy)]
        behavior = enemy_behavior_name(enemy)
        sx, sy = to_iso(enemy.pos, shake)
        bob = math.sin(enemy.t * 6.0) * 1.5

        if behavior.startswith("boss_"):
            objs = h.objs
            sh = objs[0]
            sh.x, sh.y = sx, sy - 26
            # common: glow, ring, crown, body
            if len(objs) >= 5:
                glow, ring, crown, body = objs[1], objs[2], objs[3], objs[4]
                glow.x, glow.y = sx, sy + bob
                ring.x, ring.y = sx, sy + bob
                crown.x, crown.y = sx, sy + bob
                body.x, body.y = sx, sy + bob
                crown.radius = 24 + 2.0 * (0.5 + 0.5 * math.sin(enemy.t * 4.0))

            if behavior == "boss_thunder":
                sig = objs[5]
                sig.x, sig.y = sx - 10, sy + 20 + bob
                sig.x2, sig.y2 = sx + 10, sy + 10 + bob
            elif behavior == "boss_laser":
                eye, iris = objs[5], objs[6]
                eye.x, eye.y = sx + 6, sy + 8 + bob
                iris.x, iris.y = sx + 6 + 2.0 * math.sin(enemy.t * 9.0), sy + 8 + bob
            elif behavior == "boss_trapmaster":
                gear = objs[5]
                gear.x, gear.y = sx, sy + bob
                gear.radius = 26 + 1.5 * math.sin(enemy.t * 3.2)
            elif behavior == "boss_swarmqueen":
                orb1, orb2, orb3 = objs[5], objs[6], objs[7]
                r = 20
                orb1.x, orb1.y = sx + math.cos(enemy.t * 2.2) * r, sy + bob + math.sin(enemy.t * 2.2) * r
                orb2.x, orb2.y = sx + math.cos(enemy.t * 2.2 + 2.1) * r, sy + bob + math.sin(enemy.t * 2.2 + 2.1) * r
                orb3.x, orb3.y = sx + math.cos(enemy.t * 2.2 + 4.2) * r, sy + bob + math.sin(enemy.t * 2.2 + 4.2) * r
            elif behavior == "boss_brute":
                horn, scar = objs[5], objs[6]
                horn.x, horn.y = sx, sy + bob + 26
                horn.x2, horn.y2 = sx + 18, sy + bob + 16
                horn.x3, horn.y3 = sx - 18, sy + bob + 16
                scar.x, scar.y, scar.x2, scar.y2 = sx - 10, sy + bob + 2, sx + 10, sy + bob - 6
            self._set_depth(h, sy)
            return

        if behavior == "bomber":
            sh, body, core, fuse, fuse_trail = h.objs
            sh.x, sh.y = sx, sy - 18
            body.x, body.y = sx, sy + bob
            core.x, core.y = sx, sy + bob
            fuse_trail.x, fuse_trail.y = sx, sy + bob
            exploding = bool(getattr(enemy, "ai", {}).get("bomber_exploding", False))
            if exploding:
                pulse = 0.5 + 0.5 * math.sin(enemy.t * 30)
                core.radius = 8 + 4 * pulse
                core.opacity = 255
                fuse_speed = 18.0
            else:
                core.radius = 8
                core.opacity = 200
                fuse_speed = 4.0
            # Fuse spark orbits the body
            fr = 16
            fuse.x = sx + math.cos(enemy.t * fuse_speed) * fr
            fuse.y = sy + bob + math.sin(enemy.t * fuse_speed) * fr
            fuse.opacity = 160 + int(95 * (0.5 + 0.5 * math.sin(enemy.t * 12.0)))
            self._set_depth(h, sy)
            return

        if behavior == "engineer":
            sh, body, backpack, visor, tool, tool2, gear = h.objs
            sh.x, sh.y = sx, sy - 18
            body.x, body.y = sx, sy + bob
            backpack.x, backpack.y = sx - 12, sy + 2 + bob
            visor.x, visor.y = sx + 1, sy + 2 + bob
            tool.x, tool.y, tool.x2, tool.y2 = sx + 10, sy + 6 + bob, sx + 16, sy + 0 + bob
            tool2.x, tool2.y, tool2.x2, tool2.y2 = sx + 10, sy + 6 + bob, sx + 16, sy + 12 + bob
            # Rotating gear arc
            gear.x, gear.y = sx - 12, sy + 2 + bob
            gear.radius = 17 + 1.5 * math.sin(enemy.t * 5.0)
            gear.opacity = 40 + int(30 * (0.5 + 0.5 * math.sin(enemy.t * 3.0)))
            self._set_depth(h, sy)
            return

        if behavior == "egg_sac":
            sh, body, vein1, vein2, core = h.objs
            sh.x, sh.y = sx, sy - 18
            
            # Heartbeat pulse
            pulse = 0.8 + 0.2 * math.sin(enemy.t * 8.0)
            if hasattr(enemy, "ai") and enemy.ai.get("hatch_timer", 0) < 1.0:
                 # Fast pulse before hatching
                 pulse = 0.8 + 0.3 * math.sin(enemy.t * 18.0)
            
            body.x, body.y = sx, sy + bob
            body.radius = 15 * pulse
            
            vein1.x, vein1.y = sx, sy + bob
            vein1.radius = 14 * pulse
            
            vein2.x, vein2.y = sx, sy + bob
            vein2.radius = 10 * pulse

            core.x, core.y = sx, sy + bob
            core.radius = 6 * pulse + 2 * math.sin(enemy.t * 12.0)
            
            self._set_depth(h, sy)
            return

        if behavior == "tank":
            sh, body, armor, plate, eye, shield_ring = h.objs
            sh.x, sh.y = sx, sy - 19
            body.x, body.y = sx, sy + bob * 0.4
            armor.x, armor.y = sx, sy + bob * 0.4
            plate.x, plate.y = sx + 8, sy + 1 + bob * 0.4
            eye.x, eye.y = sx + 6, sy + 2 + bob * 0.4
            # Rotating shield ring
            shield_ring.x, shield_ring.y = sx, sy + bob * 0.4
            shield_ring.radius = 22 + 1.0 * math.sin(enemy.t * 2.0)
            shield_ring.opacity = 50 + int(30 * (0.5 + 0.5 * math.sin(enemy.t * 1.5)))
            self._set_depth(h, sy)
            return

        if behavior == "ranged":
            sh, body, cannon, muzzle, eye, scope_h, scope_v = h.objs
            sh.x, sh.y = sx, sy - 18
            body.x, body.y = sx, sy + bob
            cannon.x, cannon.y = sx + 6, sy + 2 + bob
            muzzle.x, muzzle.y = sx + 18, sy + 2 + bob
            eye.x, eye.y = sx + 1, sy + 2 + bob
            # Scope crosshairs rotate slowly
            sr = 20
            sa = enemy.t * 1.2
            scope_h.x, scope_h.y = sx + 18 - math.cos(sa) * sr, sy + 2 + bob
            scope_h.x2, scope_h.y2 = sx + 18 + math.cos(sa) * sr, sy + 2 + bob
            scope_v.x, scope_v.y = sx + 18, sy + 2 + bob - math.sin(sa) * sr
            scope_v.x2, scope_v.y2 = sx + 18, sy + 2 + bob + math.sin(sa) * sr
            scope_h.opacity = 60 + int(40 * (0.5 + 0.5 * math.sin(enemy.t * 3.0)))
            scope_v.opacity = scope_h.opacity
            self._set_depth(h, sy)
            return

        if behavior == "charger":
            sh, body, horn1, horn2, eye, trail1, trail2 = h.objs
            sh.x, sh.y = sx, sy - 18
            body.x, body.y = sx, sy + bob
            # Horns
            horn1.x, horn1.y = sx + 2, sy + 16 + bob
            horn1.x2, horn1.y2 = sx + 12, sy + 10 + bob
            horn1.x3, horn1.y3 = sx + 6, sy + 4 + bob
            horn2.x, horn2.y = sx - 2, sy + 16 + bob
            horn2.x2, horn2.y2 = sx - 12, sy + 10 + bob
            horn2.x3, horn2.y3 = sx - 6, sy + 4 + bob
            eye.x, eye.y = sx + 2, sy + 2 + bob
            # Speed trails — visible when charging
            is_charging = bool(getattr(enemy, "ai", {}).get("charger_dashing", False))
            if is_charging:
                trail1.x, trail1.y = sx - 12, sy + 6 + bob
                trail1.x2, trail1.y2 = sx - 32, sy + 10 + bob
                trail2.x, trail2.y = sx - 12, sy - 2 + bob
                trail2.x2, trail2.y2 = sx - 32, sy + 2 + bob
                trail1.opacity = 140
                trail2.opacity = 110
            else:
                trail1.opacity = 0
                trail2.opacity = 0
            self._set_depth(h, sy)
            return

        if behavior == "flyer":
            sh, body, wing1, wing2, tail, eye, jet = h.objs
            sh.x, sh.y = sx, sy - 17
            body.x, body.y = sx, sy + bob
            flap = 6 + 4 * math.sin(enemy.t * 10.0)
            wing1.x, wing1.y = sx, sy + bob + 6
            wing1.x2, wing1.y2 = sx + 22, sy + bob + flap
            wing1.x3, wing1.y3 = sx + 10, sy + bob - 2
            wing2.x, wing2.y = sx, sy + bob + 6
            wing2.x2, wing2.y2 = sx - 22, sy + bob + flap
            wing2.x3, wing2.y3 = sx - 10, sy + bob - 2
            tail.x, tail.y, tail.x2, tail.y2 = sx - 3, sy + bob - 6, sx - 14, sy + bob - 14
            eye.x, eye.y = sx + 2, sy + bob + 2
            # Jet trail behind
            jet.x, jet.y = sx - 4, sy + bob - 4
            jet.x2, jet.y2 = sx - 18, sy + bob - 16
            jet.opacity = 50 + int(40 * (0.5 + 0.5 * math.sin(enemy.t * 8.0)))
            self._set_depth(h, sy)
            return

        if behavior == "spitter":
            sh, body, sac1, sac2, mouth, acid_glow = h.objs
            sh.x, sh.y = sx, sy - 18
            body.x, body.y = sx, sy + bob
            sac1.x, sac1.y = sx - 9, sy + 2 + bob
            sac2.x, sac2.y = sx + 8, sy + 4 + bob
            mouth.x, mouth.y = sx + 8, sy + bob
            mouth.x2, mouth.y2 = sx + 18, sy + 4 + bob
            mouth.x3, mouth.y3 = sx + 18, sy - 4 + bob
            # Pulsing acid glow
            acid_glow.x, acid_glow.y = sx, sy + bob
            acid_glow.radius = 14 + 3 * math.sin(enemy.t * 4.0)
            acid_glow.opacity = 18 + int(14 * (0.5 + 0.5 * math.sin(enemy.t * 5.0)))
            self._set_depth(h, sy)
            return

        if behavior == "swarm":
            sh, body, dot1, dot2, dot3, ant1, ant2 = h.objs
            sh.x, sh.y = sx, sy - 18
            body.x, body.y = sx, sy + bob
            r = 8
            dot1.x, dot1.y = sx + math.cos(enemy.t * 6.0) * r, sy + bob + math.sin(enemy.t * 6.0) * r
            dot2.x, dot2.y = sx + math.cos(enemy.t * 6.0 + 2.1) * r, sy + bob + math.sin(enemy.t * 6.0 + 2.1) * r
            dot3.x, dot3.y = sx + math.cos(enemy.t * 6.0 + 4.2) * r, sy + bob + math.sin(enemy.t * 6.0 + 4.2) * r
            # Flickering antenna
            jitter = math.sin(enemy.t * 20.0) * 3.0
            ant1.x, ant1.y = sx - 3, sy + bob + 8
            ant1.x2, ant1.y2 = sx - 5 + jitter, sy + bob + 15
            ant2.x, ant2.y = sx + 3, sy + bob + 8
            ant2.x2, ant2.y2 = sx + 5 - jitter, sy + bob + 15
            ant1.opacity = 70 + int(50 * (0.5 + 0.5 * math.sin(enemy.t * 14.0)))
            ant2.opacity = 70 + int(50 * (0.5 + 0.5 * math.sin(enemy.t * 14.0 + 1.5)))
            self._set_depth(h, sy)
            return

        if behavior == "chaser":
            sh, body, aura, spike1, spike2, spike3, eye1, eye2 = h.objs
            sh.x, sh.y = sx, sy - 18
            body.x, body.y = sx, sy + bob
            # Pulsing aura ring
            aura.x, aura.y = sx, sy + bob
            aura.radius = 16 + 4 * math.sin(enemy.t * 3.5)
            aura.opacity = 30 + int(30 * (0.5 + 0.5 * math.sin(enemy.t * 2.5)))
            # Rotating spikes
            t_rot = enemy.t * 1.8
            for i, spike in enumerate((spike1, spike2, spike3)):
                a = t_rot + i * (math.tau / 3)
                sr = 18
                tip_x = sx + math.cos(a) * sr
                tip_y = sy + bob + math.sin(a) * sr
                base_a1 = a + 0.35
                base_a2 = a - 0.35
                br = 10
                spike.x, spike.y = tip_x, tip_y
                spike.x2, spike.y2 = sx + math.cos(base_a1) * br, sy + bob + math.sin(base_a1) * br
                spike.x3, spike.y3 = sx + math.cos(base_a2) * br, sy + bob + math.sin(base_a2) * br
            eye1.x, eye1.y = sx - 3, sy + bob + 2
            eye2.x, eye2.y = sx + 3, sy + bob + 2
            self._set_depth(h, sy)
            return

        sh, body, shine, eye1, eye2 = h.objs
        sh.x, sh.y = sx, sy - 18
        body.x, body.y = sx, sy
        shine.x, shine.y = sx - 3, sy + 3
        eye1.x, eye1.y = sx - 4, sy + 1
        eye2.x, eye2.y = sx + 2, sy + 1
        self._set_depth(h, sy)

    def drop_enemy(self, enemy):
        """Remove enemy visual."""
        h = self._enemy_handles.pop(id(enemy), None)
        if h:
            h.delete()

    def ensure_projectile(self, proj):
        """Ensure projectile visual exists."""
        if id(proj) in self._proj_handles:
            return
        
        # Different visuals for different projectile types
        projectile_type = getattr(proj, 'projectile_type', 'bullet')
        is_enemy = str(getattr(proj, "owner", "player")) == "enemy"
        
        if projectile_type == "bomb":
            # Bomb: heavy orange core with dark casing.
            sh = shapes.Circle(0, 0, 7, color=(120, 70, 45), batch=self.batch)
            core = shapes.Circle(0, 0, 4, color=(255, 145, 90), batch=self.batch)
        elif projectile_type == "missile":
            # Larger missile
            if is_enemy:
                sh = shapes.Circle(0, 0, 6, color=(170, 60, 60), batch=self.batch)
                core = shapes.Circle(0, 0, 3, color=(255, 120, 120), batch=self.batch)
            else:
                sh = shapes.Circle(0, 0, 6, color=(200, 100, 50), batch=self.batch)
                core = shapes.Circle(0, 0, 3, color=(255, 150, 100), batch=self.batch)
        elif projectile_type == "plasma":
            # Plasma projectile
            if is_enemy:
                sh = shapes.Circle(0, 0, 4, color=(255, 90, 180), batch=self.batch)
                core = shapes.Circle(0, 0, 2, color=(255, 180, 220), batch=self.batch)
            else:
                sh = shapes.Circle(0, 0, 4, color=(150, 100, 255), batch=self.batch)
                core = shapes.Circle(0, 0, 2, color=(200, 150, 255), batch=self.batch)
        elif projectile_type == "spread":
            # Spread pellets
            if is_enemy:
                sh = shapes.Circle(0, 0, 4, color=(255, 110, 90), batch=self.batch)
                core = shapes.Circle(0, 0, 2, color=(255, 220, 220), batch=self.batch)
            else:
                sh = shapes.Circle(0, 0, 4, color=(255, 200, 100), batch=self.batch)
                core = shapes.Circle(0, 0, 2, color=(255, 255, 255), batch=self.batch)
        else:  # bullet or default
            # Default bullet
            if is_enemy:
                sh = shapes.Circle(0, 0, 4, color=(255, 90, 90), batch=self.batch)
                core = shapes.Circle(0, 0, 2, color=(255, 220, 220), batch=self.batch)
            else:
                sh = shapes.Circle(0, 0, 4, color=(255, 245, 190), batch=self.batch)
                core = shapes.Circle(0, 0, 2, color=(255, 255, 255), batch=self.batch)
        
        # Clean projectile rendering: light streak + core, without heavy blob glow.
        trail = shapes.Line(0, 0, 0, 0, thickness=max(1, int(sh.radius * 0.65)), color=sh.color, batch=self.batch)
        trail.opacity = 95 if is_enemy else 125
        flare = shapes.Circle(0, 0, max(2, int(sh.radius * 0.55)), color=(255, 255, 255), batch=self.batch)
        flare.opacity = 120
        self._proj_handles[id(proj)] = RenderHandle(trail, sh, core, flare)

    def sync_projectile(self, proj, shake: Vec2):
        """Update projectile visual position."""
        h = self._proj_handles[id(proj)]
        trail, sh, core, flare = h.objs
        sx, sy = to_iso(proj.pos, shake)
        v = getattr(proj, "vel", Vec2(0.0, 0.0))
        v2 = Vec2(v.x, v.y)
        if v2.length() <= 1e-6:
            v2 = Vec2(1.0, 0.0)
        vd = v2.normalized()
        trail_len = 8 + min(16.0, v2.length() * 0.03)
        trail.x, trail.y = sx, sy
        trail.x2, trail.y2 = sx - vd.x * trail_len, sy - vd.y * trail_len * 0.65
        trail.opacity = 95 if str(getattr(proj, "owner", "player")) == "enemy" else 125
        sh.x, sh.y = sx, sy
        core.x, core.y = sx, sy
        flare.x, flare.y = sx + vd.x * 1.8, sy + vd.y * 1.2
        flare.opacity = 90 if str(getattr(proj, "owner", "player")) == "enemy" else 130
        self._set_depth(h, sy)

    def drop_projectile(self, proj):
        """Remove projectile visual."""
        h = self._proj_handles.pop(id(proj), None)
        if h:
            h.delete()

    def ensure_powerup(self, p):
        """Ensure powerup visual exists."""
        if id(p) in self._power_handles:
            return
        
        # Powerup type - distinct bright colors
        color, glyph, size = {
            "heal": ((100, 255, 150), "+", 14),      # Bright green
            "damage": ((255, 100, 100), "!", 14),    # Bright red  
            "speed": ((100, 200, 255), ">", 14),     # Bright blue
            "firerate": ((255, 220, 100), "*", 14),  # Bright yellow/gold
            "shield": ((120, 220, 255), "O", 14),    # Cyan shield
            "laser": ((255, 120, 255), "=", 14),     # Magenta beam
            "vortex": ((180, 140, 255), "@", 14),    # Vortex
            "weapon": ((220, 230, 255), "W", 14),    # Weapon pickup
            "ultra": ((255, 230, 170), "U", 14),     # Ultra ability charge
        }.get(p.kind, ((200, 200, 200), "?", 12))

        # Large, glowing center orb
        orb = shapes.Circle(0, 0, size, color=color, batch=self.batch)
        
        # Inner bright core
        core = shapes.Circle(0, 0, size // 2, color=(255, 255, 255), batch=self.batch)
        core.opacity = 200
        
        # Outer pulsing rings for visibility
        ring1 = shapes.Circle(0, 0, size + 4, color=(255, 255, 255), batch=self.batch)
        ring1.opacity = 200
        
        ring2 = shapes.Circle(0, 0, size + 10, color=color, batch=self.batch)
        ring2.opacity = 80
        
        # Symbol label - larger and more visible
        label = pyglet.text.Label(
            glyph,
            font_name="Consolas",
            font_size=16,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            batch=self.batch,
            color=(255, 255, 255, 255),
        )
        self._power_handles[id(p)] = RenderHandle(ring2, ring1, orb, core, label)

    def sync_powerup(self, p, shake: Vec2):
        """Update powerup visual position."""
        h = self._power_handles[id(p)]
        ring2, ring1, orb, core, label = h.objs
        sx, sy = to_iso(p.pos, shake)
        ring2.x, ring2.y = sx, sy
        ring1.x, ring1.y = sx, sy
        orb.x, orb.y = sx, sy
        core.x, core.y = sx, sy
        label.x, label.y = sx, sy
        self._set_depth(h, sy)

    def drop_powerup(self, p):
        """Remove powerup visual."""
        h = self._power_handles.pop(id(p), None)
        if h:
            h.delete()

    def ensure_obstacle(self, ob):
        if id(ob) in self._obstacle_handles:
            return
        r = float(getattr(ob, "radius", 28.0))
        kind = getattr(ob, "kind", "pillar")

        shadow = shapes.Ellipse(0, 0, r * 2.2, max(6.0, r * 0.75), color=(0, 0, 0), batch=self.batch)
        shadow.opacity = 110

        if kind == "crystal":
            base = shapes.Circle(0, 0, r * 0.9, color=(120, 90, 180), batch=self.batch)
            base.opacity = 200
            shard1 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(210, 190, 255), batch=self.batch)
            shard1.opacity = 200
            shard2 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(170, 140, 230), batch=self.batch)
            shard2.opacity = 180
            glow = shapes.Circle(0, 0, r * 1.25, color=(180, 140, 255), batch=self.batch)
            glow.opacity = 40
            self._obstacle_handles[id(ob)] = RenderHandle(shadow, glow, base, shard1, shard2)
            return

        if kind == "crate":
            base = shapes.Rectangle(0, 0, r * 1.9, r * 1.35, color=(95, 75, 55), batch=self.batch)
            base.anchor_x = base.width / 2
            base.anchor_y = base.height / 2
            base.opacity = 220
            border = shapes.Rectangle(0, 0, r * 1.9, r * 1.35, color=(160, 140, 120), batch=self.batch)
            border.anchor_x = border.width / 2
            border.anchor_y = border.height / 2
            border.opacity = 60
            strap = shapes.Line(0, 0, 0, 0, thickness=3, color=(50, 40, 30), batch=self.batch)
            strap.opacity = 170
            self._obstacle_handles[id(ob)] = RenderHandle(shadow, base, border, strap)
            return

        # pillar
        base = shapes.Circle(0, 0, r, color=(80, 90, 110), batch=self.batch)
        base.opacity = 230
        top = shapes.Circle(0, 0, max(6.0, r * 0.65), color=(140, 155, 180), batch=self.batch)
        top.opacity = 200
        ring = shapes.Arc(0, 0, r * 1.05, segments=40, thickness=3, color=(255, 255, 255), batch=self.batch)
        ring.opacity = 35
        self._obstacle_handles[id(ob)] = RenderHandle(shadow, base, top, ring)

    def sync_obstacle(self, ob, shake: Vec2):
        h = self._obstacle_handles[id(ob)]
        r = float(getattr(ob, "radius", 28.0))
        kind = getattr(ob, "kind", "pillar")
        sx, sy = to_iso(ob.pos, shake)

        if kind == "crystal":
            shadow, glow, base, shard1, shard2 = h.objs
            shadow.x, shadow.y = sx, sy - 18
            glow.x, glow.y = sx, sy + 6
            base.x, base.y = sx, sy + 2
            shard1.x, shard1.y = sx - r * 0.6, sy + 6
            shard1.x2, shard1.y2 = sx, sy + r * 1.55
            shard1.x3, shard1.y3 = sx + r * 0.35, sy + 6
            shard2.x, shard2.y = sx + r * 0.25, sy + 2
            shard2.x2, shard2.y2 = sx + r * 0.9, sy + r * 1.25
            shard2.x3, shard2.y3 = sx + r * 0.55, sy + 2
            self._set_depth(h, sy)
            return

        if kind == "crate":
            shadow, base, border, strap = h.objs
            shadow.x, shadow.y = sx, sy - 18
            base.x, base.y = sx, sy + 4
            border.x, border.y = sx, sy + 4
            strap.x, strap.y, strap.x2, strap.y2 = sx - r * 0.9, sy + 4, sx + r * 0.9, sy + 4
            self._set_depth(h, sy)
            return

        shadow, base, top, ring = h.objs
        shadow.x, shadow.y = sx, sy - 18
        base.x, base.y = sx, sy + 2
        top.x, top.y = sx, sy + 12
        ring.x, ring.y = sx, sy + 2
        ring.radius = r * (1.02 + 0.03 * math.sin(sy * 0.02))
        self._set_depth(h, sy)

    def drop_obstacle(self, ob):
        h = self._obstacle_handles.pop(id(ob), None)
        if h:
            h.delete()

    def ensure_trap(self, tr):
        if id(tr) in self._trap_handles:
            return
        if getattr(tr, "kind", "") in ("slam", "slam_warn"):
            base = shapes.Circle(0, 0, tr.radius, color=(255, 80, 80), batch=self.batch)
            base.opacity = 40 if getattr(tr, "kind", "") == "slam_warn" else 65
            ring = shapes.Arc(0, 0, tr.radius * 1.05, segments=48, thickness=5, color=(255, 255, 255), batch=self.batch)
            ring.opacity = 170
            core = shapes.Circle(0, 0, max(10, tr.radius * 0.2), color=(255, 220, 200), batch=self.batch)
            core.opacity = 200
            self._trap_handles[id(tr)] = RenderHandle(base, ring, core)
        else:
            base = shapes.Circle(0, 0, tr.radius, color=(220, 120, 60), batch=self.batch)
            base.opacity = 80
            core = shapes.Circle(0, 0, max(6, tr.radius * 0.25), color=(255, 220, 180), batch=self.batch)
            core.opacity = 200
            spike = shapes.Line(0, 0, 0, 0, thickness=3, color=(255, 210, 170), batch=self.batch)
            spike2 = shapes.Line(0, 0, 0, 0, thickness=3, color=(255, 210, 170), batch=self.batch)
            self._trap_handles[id(tr)] = RenderHandle(base, core, spike, spike2)

    def sync_trap(self, tr, shake: Vec2):
        h = self._trap_handles[id(tr)]
        if getattr(tr, "kind", "") in ("slam", "slam_warn"):
            base, ring, core = h.objs
            sx, sy = to_iso(tr.pos, shake)
            base.x, base.y = sx, sy
            ring.x, ring.y = sx, sy
            core.x, core.y = sx, sy
            pulse = 0.6 + 0.4 * math.sin(tr.t * 16.0)
            ring.opacity = int(110 + 110 * pulse)
            if getattr(tr, "kind", "") == "slam_warn":
                base.opacity = int(40 + 60 * pulse)
            self._set_depth(h, sy)
            return

        base, core, spike, spike2 = h.objs
        sx, sy = to_iso(tr.pos, shake)
        base.x, base.y = sx, sy
        core.x, core.y = sx, sy
        arm = tr.radius * 0.75
        spike.x, spike.y, spike.x2, spike.y2 = sx - arm, sy - 2, sx + arm, sy + 2
        spike2.x, spike2.y, spike2.x2, spike2.y2 = sx - 2, sy - arm, sx + 2, sy + arm
        # Telegraph arming: faint until armed.
        if tr.t < getattr(tr, "armed_delay", 0.0):
            base.opacity = 40
            core.opacity = 120
            spike.opacity = 0
            spike2.opacity = 0
        else:
            base.opacity = 80
            core.opacity = 200
            spike.opacity = 220
            spike2.opacity = 220
        self._set_depth(h, sy)

    def drop_trap(self, tr):
        h = self._trap_handles.pop(id(tr), None)
        if h:
            h.delete()

    def ensure_laser(self, lb):
        if id(lb) in self._laser_handles:
            return
        line = shapes.Line(0, 0, 0, 0, thickness=lb.thickness, color=lb.color, batch=self.batch)
        line.opacity = 200
        core = shapes.Line(0, 0, 0, 0, thickness=max(2, lb.thickness * 0.35), color=(255, 255, 255), batch=self.batch)
        core.opacity = 180
        self._laser_handles[id(lb)] = RenderHandle(line, core)

    def sync_laser(self, lb, shake: Vec2):
        h = self._laser_handles[id(lb)]
        line, core = h.objs
        line.color = lb.color
        x1, y1 = to_iso(lb.start, shake)
        x2, y2 = to_iso(lb.end, shake)
        line.x, line.y, line.x2, line.y2 = x1, y1, x2, y2
        core.x, core.y, core.x2, core.y2 = x1, y1, x2, y2
        # Telegraph: low opacity + thinner look before firing.
        if getattr(lb, "t", 0.0) < getattr(lb, "warn", 0.0):
            line.opacity = 70
            core.opacity = 40
        else:
            line.opacity = 200
            core.opacity = 180
        self._set_depth(h, max(y1, y2))

    def drop_laser(self, lb):
        h = self._laser_handles.pop(id(lb), None)
        if h:
            h.delete()

    def ensure_thunder(self, th):
        if id(th) in self._thunder_handles:
            return
        outer = shapes.Line(0, 0, 0, 0, thickness=th.thickness, color=th.color, batch=self.batch)
        outer.opacity = 160
        core = shapes.Line(0, 0, 0, 0, thickness=max(2, th.thickness * 0.35), color=(255, 255, 255), batch=self.batch)
        core.opacity = 200
        self._thunder_handles[id(th)] = RenderHandle(outer, core)

    def sync_thunder(self, th, shake: Vec2):
        h = self._thunder_handles[id(th)]
        outer, core = h.objs
        outer.color = th.color
        x1, y1 = to_iso(th.start, shake)
        x2, y2 = to_iso(th.end, shake)
        outer.x, outer.y, outer.x2, outer.y2 = x1, y1, x2, y2
        core.x, core.y, core.x2, core.y2 = x1, y1, x2, y2
        if getattr(th, "t", 0.0) < getattr(th, "warn", 0.0):
            # Warning line: subtle and steady.
            outer.opacity = 55
            core.opacity = 20
        else:
            outer.opacity = int(140 + 70 * (0.5 + 0.5 * math.sin(th.t * 40.0)))
            core.opacity = int(200 + 40 * (0.5 + 0.5 * math.sin(th.t * 55.0)))
        self._set_depth(h, max(y1, y2))

    def drop_thunder(self, th):
        h = self._thunder_handles.pop(id(th), None)
        if h:
            h.delete()

