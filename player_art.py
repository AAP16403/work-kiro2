"""Pod-robot player character, drawn from pyglet shapes in one batch.

PlayerArt owns every shape that draws the player: ground shadow, halo, thruster glow,
shell body with a soft highlight, blush cheeks, two large eyes with glints that look
toward the aim direction, a blink lid, worry marks, a short antenna with a glowing tip,
a muzzle nub, and the shield, laser and boost auras. It is visual only. sync() reads the
player and the clock and never writes to them, so hit-boxes and positions are untouched.

Usage::

    art = PlayerArt(batch, group)
    cx, cy = art.sync(player, shake, t=time, aim_dir=aim, palette=DEFAULT_PALETTE)

sync() returns the screen centre of the body so the caller can depth-sort the character
with the rest of the scene. A palette is a dict of colours. A skin may pass any dict that
holds the keys of DEFAULT_PALETTE; keys it leaves out fall back to DEFAULT_PALETTE.
"""

from __future__ import annotations

import math

from pyglet import shapes

from config import ISO_SCALE_X, ISO_SCALE_Y, PLAYER_SPEED
from utils import Vec2, to_iso

# Colours a skin can recolour. Every key here is read by PlayerArt.sync.
DEFAULT_PALETTE: dict[str, tuple[int, int, int]] = {
    "body": (132, 224, 255),    # shell
    "accent": (255, 206, 90),   # glowing antenna tip
    "eye": (16, 24, 46),        # pupils, brows, mouth, closed-eye lash
    "glow": (100, 220, 255),    # halo and thruster glow
    "trail": (130, 210, 255),   # thruster jets
    "bullet": (235, 240, 255),  # muzzle nub and its glow
    "cheek": (255, 140, 175),   # blush
}

# Hull tints shared with the legacy ship: damage flash, overdrive and invulnerability.
HULL_FLASH = (255, 120, 120)
HULL_BOOST = (255, 215, 130)
HULL_INVULN = (255, 236, 160)
BOOST_JET = (255, 170, 70)

BLINK_PERIOD = 3.0          # seconds between blinks
BLINK_CLOSED_S = 0.12       # how long the eyes stay shut
BLINK_PHASE_OFFSET = 1.4    # the first blink of a run lands a little after it starts
WORRY_HP_FRAC = 0.30        # below this share of max HP the expression turns worried
DASH_BURST_S = 0.32         # stretch burst length after a dash starts
VELOCITY_SMOOTHING = 14.0   # per second; higher follows the real motion more tightly
DIR_SMOOTHING = 18.0        # per second; how fast the stretch axis turns
TELEPORT_PER_S = 900.0      # world units per second above which a position jump is not motion

BODY_A = 15.5               # base semi-axis across the screen (x)
BODY_B = 13.5               # base semi-axis up the screen (y)
BODY_SEGMENTS = 24
EYE_X = 5.2                 # eye offset from the body centre
EYE_Y = 1.6
EYE_A = 3.7
EYE_B = 4.6
CHEEK_X = 9.6
CHEEK_Y = -3.8
ANTENNA_Y = 12.0            # where the antenna stalk meets the body
ANTENNA_LEN = 8.5
BOB_AMP = 1.5               # legacy idle bob, kept so the character floats the same way


def _screen_dir(v: Vec2) -> tuple[float, float]:
    """Unit screen-space direction of a world-space vector.

    The isometric map is linear, so the screen direction of a world direction is the
    projected vector, normalised. Returns (1, 0) for a zero vector.
    """
    sx = (v.x - v.y) * ISO_SCALE_X
    sy = (v.x + v.y) * ISO_SCALE_Y
    n = math.hypot(sx, sy)
    if n <= 1e-9:
        return 1.0, 0.0
    return sx / n, sy / n


def _shade(rgb) -> tuple[int, int, int]:
    """Darker tone of a colour, used for the underside of the shell and the stalk."""
    return tuple(int(c * 0.6) for c in rgb)


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _half_px(v: float) -> float:
    return round(v * 2.0) / 2.0


class PlayerArt:
    """Shape-built pod-robot character. Create once per visual; call sync() every frame."""

    def __init__(self, batch, group=None):
        self.batch = batch
        self.group = group
        self.shapes: list = []
        self._last: dict = {}           # last value written per (key) so unchanged state costs nothing
        self._prev_pos: Vec2 | None = None
        self._last_t: float | None = None
        self._vel = Vec2(0.0, 0.0)      # smoothed world velocity, units per second
        self._dir = (1.0, 0.0)          # smoothed screen axis the body stretches along
        self._was_dashing = False
        self._dash_t0: float | None = None
        self._dash_dir = (1.0, 0.0)     # screen direction of the current dash
        self._build()

    # ------------------------------------------------------------------ build

    def _add(self, shape, opacity: int = 255):
        shape.opacity = opacity
        self.shapes.append(shape)
        return shape

    def _build(self) -> None:
        b, g = self.batch, self.group
        pal = DEFAULT_PALETTE

        def circle(r, color, opacity=255, segments=None):
            return self._add(shapes.Circle(0, 0, r, segments=segments, color=color, batch=b, group=g), opacity)

        def ellipse(a, bb, color, opacity=255, segments=None):
            return self._add(shapes.Ellipse(0, 0, a, bb, segments=segments, color=color, batch=b, group=g), opacity)

        def rect(w, h, color, anchor, opacity=255):
            r = shapes.Rectangle(0, 0, w, h, color=color, batch=b, group=g)
            r.anchor_x, r.anchor_y = anchor
            return self._add(r, opacity)

        def arc(r, start, span, thick, color, segments, opacity=255):
            return self._add(
                shapes.Arc(0, 0, r, segments=segments, angle=span, start_angle=start, thickness=thick,
                           color=color, batch=b, group=g), opacity)

        hull = pal["body"]
        self.shadow = ellipse(20.0, 7.0, (0, 0, 0), opacity=120)
        # Three stacked discs with falling opacity fake a soft falloff without a texture.
        self.halo_far = circle(34.0, pal["glow"], opacity=8, segments=28)
        self.halo_out = circle(27.0, pal["glow"], opacity=12, segments=24)
        self.halo_in = circle(20.0, pal["glow"], opacity=18, segments=20)
        self.thrust = circle(8.5, pal["glow"], opacity=0, segments=16)
        self.thrust_core = circle(4.2, pal["trail"], opacity=0, segments=12)
        self.jets = [
            circle(3.2, pal["trail"], opacity=0, segments=12),
            circle(2.2, pal["trail"], opacity=0, segments=12),
            circle(1.4, pal["trail"], opacity=0, segments=10),
        ]

        # Aura rings, behind the body. Same styling as the legacy ship.
        self.aura_shield2 = arc(24.0, 0.0, 360.0, 2.0, (255, 255, 255), 48, opacity=0)
        self.aura_shield = arc(19.0, 0.0, 360.0, 4.0, (120, 220, 255), 48, opacity=0)
        self.aura_laser = arc(22.0, 0.0, 360.0, 3.0, (255, 120, 255), 64, opacity=0)
        self.aura_boost = arc(26.0, 0.0, 360.0, 3.0, (255, 145, 45), 48, opacity=0)

        # The shade sits just below the shell and takes the same squash, so the rim never peeks out.
        self.shell_shade = ellipse(BODY_A, BODY_B, _shade(hull), segments=BODY_SEGMENTS)
        self.body = ellipse(BODY_A, BODY_B, hull, segments=BODY_SEGMENTS)
        self.hl_out = ellipse(6.2, 3.6, (255, 255, 255), opacity=60, segments=20)
        self.hl_core = ellipse(3.2, 1.8, (255, 255, 255), opacity=170, segments=14)

        self._eyes = []
        for side in (-1, 1):
            cheek = ellipse(3.0, 2.0, pal["cheek"], opacity=150, segments=16)
            eye = ellipse(EYE_A, EYE_B, pal["eye"], segments=20)
            glint = circle(1.5, (255, 255, 255), segments=12)
            glint2 = circle(0.8, (255, 255, 255), opacity=200, segments=10)
            lid = ellipse(EYE_A + 0.5, EYE_B + 0.4, hull, opacity=0, segments=20)
            lash = rect(6.6, 1.4, pal["eye"], anchor=(3.3, 0.7), opacity=0)
            brow = rect(5.0, 1.5, pal["eye"], anchor=(2.5, 0.75), opacity=0)
            brow.rotation = 20.0 * side  # inner ends lift: the worried slant
            self._eyes.append((side, cheek, eye, glint, glint2, lid, lash, brow))

        self.sweat = circle(1.5, (96, 176, 235), opacity=0, segments=10)
        self.smile = arc(2.2, 180.0, 180.0, 1.2, pal["eye"], 12)
        self.frown = arc(2.2, 0.0, 180.0, 1.2, pal["eye"], 12, opacity=0)

        self.stalk = rect(1.6, ANTENNA_LEN, _shade(hull), anchor=(0.8, 0.0))
        self.ant_halo = circle(4.6, pal["accent"], opacity=80, segments=16)
        self.ant_tip = circle(2.2, pal["accent"], segments=12)

        self.muzzle = rect(7.0, 3.4, pal["bullet"], anchor=(0.0, 1.7))
        self.muzzle_glow = circle(2.3, pal["bullet"], opacity=140, segments=12)

    def delete(self) -> None:
        """Free every shape. The instance must not be synced afterwards."""
        for s in self.shapes:
            s.delete()
        self.shapes = []

    # ------------------------------------------------------------- per frame

    def _put(self, key: str, shape, attr: str, value) -> None:
        """Write one attribute only when its value changed since the last write."""
        if self._last.get(key) != value:
            self._last[key] = value
            setattr(shape, attr, value)

    def _gated(self, key: str, shape, attr: str, value, opacity: int) -> None:
        """Like _put, but a fully transparent part is not moved or recoloured.

        Hidden parts skip the GPU write. Forgetting the cached value makes the first frame the part
        shows again write its real value, so it never appears at a stale place.
        """
        if opacity <= 0:
            self._last.pop(key, None)
            return
        self._put(key, shape, attr, value)

    def _advance(self, player, t: float) -> float:
        """Update smoothed velocity and dash state from the player and the clock.

        Returns the seconds since the last sync (0 when the clock did not move).
        """
        pos = Vec2(float(player.pos.x), float(player.pos.y))
        dashing = bool(getattr(player, "is_dashing", False))
        if self._last_t is None or t < self._last_t - 1e-9:
            # First sync of a visual, or the clock restarted for a new run.
            self._prev_pos = pos
            self._last_t = t
            self._vel = Vec2(0.0, 0.0)
            self._dash_t0 = None
            self._was_dashing = False
        dt = t - self._last_t
        if dt > 0.0:
            moved = pos - self._prev_pos
            if moved.length() <= TELEPORT_PER_S * dt + 1.0:
                inst = moved / dt
                k = 1.0 - math.exp(-VELOCITY_SMOOTHING * dt)
                self._vel = self._vel + (inst - self._vel) * k
            else:
                self._vel = Vec2(0.0, 0.0)  # a push or respawn is not movement
            self._prev_pos = pos
            self._last_t = t
        if dashing and not self._was_dashing:
            self._dash_t0 = t
            self._dash_dir = _screen_dir(getattr(player, "dash_direction", Vec2(0.0, 0.0)))
        self._was_dashing = dashing
        return max(0.0, dt)

    def _dash_burst(self, t: float) -> float:
        """1 at the start of a dash, falling to 0 over DASH_BURST_S."""
        if self._dash_t0 is None:
            return 0.0
        age = t - self._dash_t0
        if age < 0.0 or age >= DASH_BURST_S:
            return 0.0
        return 1.0 - age / DASH_BURST_S

    def sync(self, player, shake: Vec2, t: float = 0.0, aim_dir: Vec2 | None = None,
             palette: dict | None = None) -> tuple[float, float]:
        """Pose the character for this frame and return the screen centre of its body.

        Args:
            player: anything with pos, hp, max_hp, is_dashing, dash_direction, is_boosting,
                invincibility_timer, damage_flash_timer, shield, laser_until and speed.
            shake: the frame's screen shake offset.
            t: game clock in seconds, drives the idle bob, blink, expression and pulses.
            aim_dir: world-space aim direction. Defaults to +x when missing or zero.
            palette: colour overrides, see DEFAULT_PALETTE.
        """
        pal = DEFAULT_PALETTE if not palette else {**DEFAULT_PALETTE, **palette}
        t = float(t)
        aim = aim_dir if (aim_dir is not None and aim_dir.length() > 1e-6) else Vec2(1.0, 0.0)
        ax, ay = _screen_dir(aim)
        dt = self._advance(player, t)

        vx, vy = self._vel.x, self._vel.y
        vsx = (vx - vy) * ISO_SCALE_X
        vsy = (vx + vy) * ISO_SCALE_Y
        speed = math.hypot(vx, vy)
        speed_n = min(1.0, speed / max(1.0, float(getattr(player, "speed", PLAYER_SPEED)) * 1.2))
        moving = speed_n > 0.04
        burst = self._dash_burst(t)
        boosting = bool(getattr(player, "is_boosting", False))
        dashing = bool(getattr(player, "is_dashing", False))
        boost_on = boosting or dashing

        # Stretch axis: the dash while it bursts, else the motion, else rest.
        if burst > 0.02:
            target = self._dash_dir
        elif moving:
            n = math.hypot(vsx, vsy) or 1.0
            target = (vsx / n, vsy / n)
        else:
            target = (1.0, 0.0)
        self._dir = self._ease_dir(self._dir, target, 1.0 - math.exp(-DIR_SMOOTHING * dt))

        # Squash and stretch: area-preserving along the axis, plus a slow breath at rest.
        s = 1.0 + 0.12 * speed_n + 0.28 * burst + 0.025 * math.sin(t * 4.0)
        s = max(0.85, s)
        # Quarter-pixel steps: an ellipse rebuilds its vertices whenever a semi-axis changes.
        body_a = round(BODY_A * s * 4.0) / 4.0
        body_b = round(BODY_B / s * 4.0) / 4.0
        angle = -math.degrees(math.atan2(self._dir[1], self._dir[0]))

        gx, gy = to_iso(player.pos, shake)
        bob = math.sin(t * 6.0) * BOB_AMP
        cx = float(gx)
        cy = float(gy) + bob

        # Hull colour. Legacy feedback states keep their tints.
        flashing = float(getattr(player, "damage_flash_timer", 0.0)) > 0
        invuln = float(getattr(player, "invincibility_timer", 0.0)) > 0
        if flashing:
            hull = HULL_FLASH
        elif boosting:
            hull = HULL_BOOST
        elif invuln:
            hull = HULL_INVULN
        else:
            hull = tuple(pal["body"])
        shade = _shade(hull)

        self._put("hull", self.body, "color", hull)
        self._put("shade", self.shell_shade, "color", shade)
        self._put("stalk", self.stalk, "color", shade)
        self._put("body_a", self.body, "a", body_a)
        self._put("body_b", self.body, "b", body_b)
        self._put("body_rot", self.body, "rotation", angle)
        self._put("body_pos", self.body, "position", (cx, cy))
        self._put("shade_a", self.shell_shade, "a", body_a)
        self._put("shade_b", self.shell_shade, "b", body_b)
        self._put("shade_rot", self.shell_shade, "rotation", angle)
        self._put("shade_pos", self.shell_shade, "position", (cx, cy - 1.6))
        self._put("hl_out_pos", self.hl_out, "position", (cx - 3.8, cy + 4.6))
        self._put("hl_core_pos", self.hl_core, "position", (cx - 4.2, cy + 5.2))

        # Halo and thruster glow.
        is_boost_jet = BOOST_JET if boosting else tuple(pal["trail"])
        glow = BOOST_JET if boosting else tuple(pal["glow"])
        halo_pulse = 0.5 + 0.5 * math.sin(t * 1.8)
        boost_lift = 10 if boost_on else 0
        # The halos hang on the ground point rather than the bobbing body, so they stay still at rest.
        for key, disc, base in (("halo_far", self.halo_far, 7), ("halo_out", self.halo_out, 11),
                                ("halo_in", self.halo_in, 16)):
            self._put(f"{key}_pos", disc, "position", (float(gx), float(gy)))
            self._put(f"{key}_col", disc, "color", glow)
            self._put(f"{key}_op", disc, "opacity", int(_clamp(base + 5 * halo_pulse + boost_lift, 0, 255)))
        self._put("shadow_pos", self.shadow, "position", (float(gx), float(gy) - 19.0))

        level = _clamp(0.35 + 0.5 * speed_n + (0.45 if boost_on else 0.0), 0.0, 1.0)
        pulse = 0.7 + 0.3 * math.sin(t * (40.0 if boost_on else 16.0))
        bx, by = -ax, -ay
        self._put("thrust_col", self.thrust, "color", BOOST_JET if boosting else glow)
        self._put("thrust_pos", self.thrust, "position", (cx + bx * 13.0, cy + by * 13.0))
        self._put("thrust_op", self.thrust, "opacity", int(_clamp(110 * level * pulse, 0, 255)))
        self._put("thrust_core_col", self.thrust_core, "color", is_boost_jet)
        self._put("thrust_core_pos", self.thrust_core, "position", (cx + bx * 12.0, cy + by * 12.0))
        self._put("thrust_core_op", self.thrust_core, "opacity", int(_clamp(190 * level * pulse, 0, 255)))
        for i, (jet, dist, alpha) in enumerate(zip(self.jets, (18.0, 23.5, 29.0), (200, 150, 95))):
            self._put(f"jet{i}_col", jet, "color", is_boost_jet)
            self._put(f"jet{i}_pos", jet, "position", (cx + bx * dist, cy + by * dist))
            self._put(f"jet{i}_op", jet, "opacity", int(_clamp(alpha * level * pulse, 0, 255)))

        self._update_auras(player, t, cx, cy)

        # Face. Eyes look at the aim point, blink on a fixed clock, worry under 30% HP.
        hp = float(getattr(player, "hp", 0.0))
        max_hp = max(1.0, float(getattr(player, "max_hp", 100.0)))
        worried = hp / max_hp < WORRY_HP_FRAC
        gaze_x, gaze_y = ax * 1.9, ay * 1.5
        if worried:
            gaze_x += math.sin(t * 37.0) * 0.6
            gaze_y += math.cos(t * 29.0) * 0.4
        phase = (t + BLINK_PHASE_OFFSET) % BLINK_PERIOD
        closed = phase < BLINK_CLOSED_S

        eye_rgb = tuple(pal["eye"])
        cheek_rgb = tuple(pal["cheek"])
        lid_op = 255 if closed else 0
        brow_op = 235 if worried else 0
        for side, cheek, eye, glint, glint2, lid, lash, brow in self._eyes:
            ex = cx + side * EYE_X + gaze_x
            ey = cy + EYE_Y + gaze_y
            self._put(f"cheek{side}_col", cheek, "color", cheek_rgb)
            self._put(f"cheek{side}", cheek, "position", (cx + side * CHEEK_X, cy + CHEEK_Y))
            self._put(f"eye{side}_col", eye, "color", eye_rgb)
            self._put(f"eye{side}", eye, "position", (ex, ey))
            self._put(f"glint{side}", glint, "position", (ex + 1.3, ey + 1.9))
            self._put(f"glint2{side}", glint2, "position", (ex - 1.2, ey - 1.7))
            self._gated(f"lid{side}_pos", lid, "position", (ex, ey), lid_op)
            self._gated(f"lid{side}_col", lid, "color", hull, lid_op)
            self._put(f"lid{side}_op", lid, "opacity", lid_op)
            self._gated(f"lash{side}_pos", lash, "position", (ex, ey), lid_op)
            self._gated(f"lash{side}_col", lash, "color", eye_rgb, lid_op)
            self._put(f"lash{side}_op", lash, "opacity", lid_op)
            self._gated(f"brow{side}_pos", brow, "position", (cx + side * EYE_X, cy + EYE_Y + EYE_B + 2.6), brow_op)
            self._gated(f"brow{side}_col", brow, "color", eye_rgb, brow_op)
            self._put(f"brow{side}_op", brow, "opacity", brow_op)

        sweat_op = 230 if worried else 0
        self._gated("sweat_pos", self.sweat, "position", (cx - 13.4, cy + 7.8), sweat_op)
        self._put("sweat_op", self.sweat, "opacity", sweat_op)
        smile_op = 0 if worried else 255
        self._gated("smile_pos", self.smile, "position", (cx, cy - 1.6), smile_op)
        self._gated("smile_col", self.smile, "color", eye_rgb, smile_op)
        self._put("smile_op", self.smile, "opacity", smile_op)
        frown_op = 255 if worried else 0
        self._gated("frown_pos", self.frown, "position", (cx, cy - 3.6), frown_op)
        self._gated("frown_col", self.frown, "color", eye_rgb, frown_op)
        self._put("frown_op", self.frown, "opacity", frown_op)

        # Antenna sways at rest and leans back against the motion.
        sway = 8.0 * math.sin(t * 2.3) - 12.0 * _clamp(vsx / 220.0, -1.0, 1.0)
        pivot = (cx, cy + ANTENNA_Y)
        rad = math.radians(sway)
        tip = (pivot[0] + math.sin(rad) * ANTENNA_LEN, pivot[1] + math.cos(rad) * ANTENNA_LEN)
        self._put("stalk_pos", self.stalk, "position", pivot)
        self._put("stalk_rot", self.stalk, "rotation", sway)
        self._put("tip_pos", self.ant_tip, "position", tip)
        self._put("tip_col", self.ant_tip, "color", tuple(pal["accent"]))
        self._put("ant_halo_pos", self.ant_halo, "position", tip)
        self._put("ant_halo_col", self.ant_halo, "color", tuple(pal["accent"]))
        self._put("ant_halo_op", self.ant_halo, "opacity",
                  int(70 + 50 * (0.5 + 0.5 * math.sin(t * 3.5))))

        # Muzzle nub on the aim side.
        mx, my = cx + ax * 11.0, cy + ay * 11.0
        self._put("muzzle_pos", self.muzzle, "position", (mx, my))
        self._put("muzzle_rot", self.muzzle, "rotation", -math.degrees(math.atan2(ay, ax)))
        self._put("muzzle_col", self.muzzle, "color", tuple(pal["bullet"]))
        self._put("muzzle_glow_pos", self.muzzle_glow, "position", (cx + ax * 18.5, cy + ay * 18.5))
        self._put("muzzle_glow_col", self.muzzle_glow, "color", tuple(pal["bullet"]))
        self._put("muzzle_glow_op", self.muzzle_glow, "opacity",
                  int(120 + 60 * (0.5 + 0.5 * math.sin(t * 12.0))))

        return cx, cy

    def _update_auras(self, player, t: float, cx: float, cy: float) -> None:
        """Shield, laser and overdrive rings, as the legacy ship drew them."""
        # Arc radii are quantised to half pixels because each change rebuilds the ring's vertices.
        shield = float(getattr(player, "shield", 0) or 0)
        if shield > 0:
            pulse = 0.65 + 0.35 * math.sin(t * 6.5)
            self._put("sh1_pos", self.aura_shield, "position", (cx, cy))
            self._put("sh2_pos", self.aura_shield2, "position", (cx, cy))
            self._put("sh1_r", self.aura_shield, "radius", _half_px(18.0 + 2.0 * pulse))
            self._put("sh2_r", self.aura_shield2, "radius", _half_px(24.0 + 3.0 * pulse))
            self._put("sh1_op", self.aura_shield, "opacity", int(90 + min(120.0, shield) * pulse))
            self._put("sh2_op", self.aura_shield2, "opacity", int(60 + min(120.0, shield) * 0.5 * pulse))
        else:
            self._put("sh1_op", self.aura_shield, "opacity", 0)
            self._put("sh2_op", self.aura_shield2, "opacity", 0)

        if float(getattr(player, "laser_until", 0.0)) > t:
            pulse = 0.6 + 0.4 * math.sin(t * 10.0)
            self._put("laser_pos", self.aura_laser, "position", (cx, cy))
            self._put("laser_r", self.aura_laser, "radius", _half_px(22.0 + 3.0 * pulse))
            self._put("laser_op", self.aura_laser, "opacity", int(160 * pulse))
        else:
            self._put("laser_op", self.aura_laser, "opacity", 0)

        if bool(getattr(player, "is_boosting", False)):
            bpulse = 0.65 + 0.35 * math.sin(t * 22.0)
            self._put("boost_pos", self.aura_boost, "position", (cx, cy))
            self._put("boost_r", self.aura_boost, "radius", _half_px(26.0 + 3.0 * bpulse))
            self._put("boost_op", self.aura_boost, "opacity", int(140 + 80 * bpulse))
        else:
            self._put("boost_op", self.aura_boost, "opacity", 0)

    @staticmethod
    def _ease_dir(cur, target, k: float) -> tuple[float, float]:
        """Turn the smoothed axis toward the target by fraction k and renormalise."""
        x = cur[0] + (target[0] - cur[0]) * k
        y = cur[1] + (target[1] - cur[1]) * k
        n = math.hypot(x, y)
        if n <= 1e-6:
            return target
        return x / n, y / n
