"""Pod-robot player character, drawn from pyglet shapes in one batch.

PlayerArt owns every shape that draws the player: ground shadow, halo, thruster glow with a
per-jet flicker, a dark rim, shell body with a shade and a soft highlight, a dash afterimage of
four ghost shells, blush cheeks, two large eyes with glints that ease toward the aim, a blink lid,
worry marks, a short antenna with a glowing tip, a muzzle nub, the shield, laser and boost auras,
and a death dissolve (four pieces that fly off while the body fades).

Motion, all visual only:
  - idle: a slow breath in the body scale, and the legacy float bob;
  - banking: a damped Spring leans the shell into sideways movement, and the antenna lags behind;
  - eyes: two springs ease the pupils toward the aim point;
  - hit: a short Spring recoil away from the aim, plus a squash, when damage lands;
  - death: when hp reaches 0 the body dissolves over DISSOLVE_S seconds of real time, because the
    game clock stops at game over.
config.REDUCE_MOTION stills every ambient and recoil motion: breath, bob, flicker, bank, recoil,
afterimage and dissolve pieces. The eyes and the dissolve fade still run, so the player can read the state.

sync() reads the player and the clocks and never writes to them, so hit-boxes and positions are
untouched. It returns the screen centre of the body. ``ground_y`` holds the shaken screen y of the
ground point, which is the depth to sort by: the body bobs, so its own y would cross depth buckets.

Usage::

    art = PlayerArt(batch, group)
    cx, cy = art.sync(player, shake, t=time, aim_dir=aim, palette=DEFAULT_PALETTE, real_t=wall)

A palette is a dict of colours. A skin may pass any dict that holds the keys of DEFAULT_PALETTE;
keys it leaves out fall back to DEFAULT_PALETTE. The dict is read when it is passed, so pass a new
dict object to change the colours (visuals.apply_skin does).
"""

from __future__ import annotations

import math

from pyglet import shapes

import motion
from anim import Spring, ease_out_cubic
from config import ISO_SCALE_X, ISO_SCALE_Y, PLAYER_SPEED, SHIELD_MAX
from utils import Vec2, to_iso

# Colours a skin can recolour. Every key here is read by PlayerArt.sync.
DEFAULT_PALETTE: dict[str, tuple[int, int, int]] = {
    "body": (132, 224, 255),    # shell
    "accent": (255, 206, 90),   # glowing antenna tip
    "eye": (16, 24, 46),        # pupils, brows, mouth, closed-eye lash, rim
    "glow": (100, 220, 255),    # halo, thruster glow and afterimage
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

BREATH_RATE = 2.6           # rad/s; one breath every 2.4 s
BREATH_AMP = 0.03           # share of the body scale that a breath adds at its peak
BANK_PX = 2.2               # most the shell leans sideways, in px
BANK_SPEED = 200.0          # screen px/s of sideways speed that gives a full lean
BANK_STIFFNESS = 60.0       # spring for the lean; a little underdamped, so the lean wobbles back
GAZE_X = 1.9                # pupils travel this far toward the aim, in px
GAZE_Y = 1.5
GAZE_STIFFNESS = 220.0      # spring for the pupils; critically damped, so they do not overshoot
STAGGER_PX = 3.0            # recoil when a hit lands, in px
STAGGER_STIFFNESS = 700.0   # quick recoil that settles in about a fifth of a second
GHOST_N = 4                 # afterimage shells kept alive; the dissolve reuses them as its pieces
GHOST_STEP_S = 0.07         # one afterimage sample per step while the dash burst lasts
GHOST_LIFE_S = 0.28         # each afterimage fades out over this long
GHOST_ALPHA = 0.42          # peak afterimage opacity, as a share of 255
DISSOLVE_S = 0.9            # death dissolve length, in real seconds
EYE_KEY_NAMES = ("cheek_col", "cheek", "eye_col", "eye", "glint", "glint2", "lid_pos", "lid_col", "lid_op",
                 "lash_pos", "lash_col", "lash_op", "brow_pos", "brow_col", "brow_op")
DISSOLVE_REACH = 26.0       # px the dissolve pieces fly from the body centre
DISSOLVE_LIFT = 14.0        # px the pieces sink back by the end of the dissolve
DISSOLVE_R = 3.0            # radius of a dissolve piece, in px
OUTLINE_PAD = 1.2           # dark rim width outside the shell, in px
REAL_STEP_MAX = 0.1         # longest real-time step one dissolve frame may take, in seconds


_JET_DIST = (18.0, 23.5, 29.0)  # px behind the body centre for the three exhaust jets
_JET_ALPHA = (200, 150, 95)     # their peak opacity before the flicker
_SHADE_CACHE: dict = {}


def _shade(rgb) -> tuple[int, int, int]:
    """Darker tone of a colour, used for the underside of the shell and the stalk. Cached per colour."""
    shade = _SHADE_CACHE.get(rgb)
    if shade is None:
        shade = tuple(int(c * 0.6) for c in rgb)
        _SHADE_CACHE[rgb] = shade
    return shade


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _half_px(v: float) -> float:
    return round(v * 2.0) / 2.0


def _screen_dir(x: float, y: float) -> tuple[float, float]:
    """Unit screen-space direction of a world-space direction (x, y).

    The isometric map is linear, so the screen direction of a world direction is the projected vector,
    normalised. Returns (1, 0) for a zero vector.
    """
    sx = (x - y) * ISO_SCALE_X
    sy = (x + y) * ISO_SCALE_Y
    n = math.hypot(sx, sy)
    if n <= 1e-9:
        return 1.0, 0.0
    return sx / n, sy / n


def _ease_dir(cx: float, cy: float, tx: float, ty: float, k: float) -> tuple[float, float]:
    """Turn the smoothed axis (cx, cy) toward the target (tx, ty) by fraction k and renormalise."""
    x = cx + (tx - cx) * k
    y = cy + (ty - cy) * k
    n = math.hypot(x, y)
    if n <= 1e-6:
        return tx, ty
    return x / n, y / n


def _spring(stiffness: float, ratio: float) -> Spring:
    """A spring at rest on zero, with the given damping ratio (1.0 is critical, below 1 wobbles)."""
    return Spring(0.0, target=0.0, stiffness=stiffness, damping=2.0 * ratio * math.sqrt(stiffness))


def _flicker(t: float, boost: bool, phase: float) -> float:
    """Thruster brightness, about 0.56 to 1.0, with an uneven flutter. Each jet passes its own phase."""
    slow = 23.0 if boost else 15.0
    fast = 53.0 if boost else 37.0
    return 0.78 + 0.13 * math.sin(t * slow + phase) + 0.09 * math.sin(t * fast + phase * 1.7)


class PlayerArt:
    """Shape-built pod-robot character. Create once per visual; call sync() every frame."""

    def __init__(self, batch, group=None):
        self.batch = batch
        self.group = group
        self.shapes: list = []
        self._last: dict = {}           # last value written per key, so unchanged state costs nothing
        self._fixed: list = []          # (key, shape, opacity) for parts that keep a fixed opacity
        self._pal_src = None
        self._rgb = dict(DEFAULT_PALETTE)
        self._alpha = 1.0               # dissolve fade: 1 when alive, falls to 0 as the body goes
        self.ground_y = 0.0             # shaken screen y of the ground point, the depth to sort by
        self._last_t: float | None = None
        self._px = 0.0                  # world position at the last sync
        self._py = 0.0
        self._vx = 0.0                  # smoothed world velocity, units per second
        self._vy = 0.0
        self._dx, self._dy = 1.0, 0.0   # smoothed screen axis the body stretches along
        self._was_dashing = False
        self._dash_t0: float | None = None
        self._dash_dx, self._dash_dy = 1.0, 0.0  # screen direction of the current dash
        self._flash_prev = 0.0
        self._fresh = True              # the next sync shows its targets at once
        self._gaze_x = _spring(GAZE_STIFFNESS, 0.9)
        self._gaze_y = _spring(GAZE_STIFFNESS, 0.9)
        self._bank = _spring(BANK_STIFFNESS, 0.6)
        self._stagger = _spring(STAGGER_STIFFNESS, 0.45)
        self._ghost_t = [-1e9] * GHOST_N   # ring buffer of afterimage samples, reused every dash
        self._ghost_x = [0.0] * GHOST_N
        self._ghost_y = [0.0] * GHOST_N
        self._ghost_a = [0.0] * GHOST_N
        self._ghost_b = [0.0] * GHOST_N
        self._ghost_r = [0.0] * GHOST_N
        self._ghost_next = 0
        self._ghost_last = -1e9
        self._ghost_keys = [(f"ghost{i}_pos", f"ghost{i}_a", f"ghost{i}_b", f"ghost{i}_rot", f"ghost{i}_col",
                             f"ghost{i}_op") for i in range(GHOST_N)]
        self._jet_keys = [(f"jet{i}_col", f"jet{i}_pos", f"jet{i}_op") for i in range(3)]
        self._fixed_alpha = None        # the alpha the fixed parts were last written at
        self._dying = False
        self._death_s = 0.0             # real seconds since hp reached 0
        self._real_last: float | None = None
        self._build()

    # ------------------------------------------------------------------ build

    def _add(self, shape, opacity: int = 255):
        shape.opacity = opacity
        self.shapes.append(shape)
        return shape

    def _fix(self, key: str, shape, opacity: int):
        """Register a part whose opacity never changes except through the dissolve fade."""
        self._fixed.append((key, shape, int(opacity)))
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
        self.shadow = self._fix("shadow_op", ellipse(20.0, 7.0, (0, 0, 0), opacity=120), 120)
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

        # Dash afterimage: body-shaped ghosts, behind the body and above the halo.
        self.ghosts = [ellipse(BODY_A, BODY_B, pal["glow"], opacity=0, segments=BODY_SEGMENTS)
                       for _ in range(GHOST_N)]

        # Aura rings, behind the body. Same styling as the legacy ship.
        self.aura_shield2 = arc(24.0, 0.0, 360.0, 2.0, (255, 255, 255), 48, opacity=0)
        self.aura_shield = arc(19.0, 0.0, 360.0, 4.0, (120, 220, 255), 48, opacity=0)
        self.aura_laser = arc(22.0, 0.0, 360.0, 3.0, (255, 120, 255), 64, opacity=0)
        self.aura_boost = arc(26.0, 0.0, 360.0, 3.0, (255, 145, 45), 48, opacity=0)

        # The dark rim keeps the silhouette readable over bright arena effects. Behind the shade.
        self.rim = self._fix("rim_op", ellipse(BODY_A + OUTLINE_PAD, BODY_B + OUTLINE_PAD, pal["eye"],
                                               opacity=170, segments=BODY_SEGMENTS), 170)
        # The shade sits just below the shell and takes the same squash, so the rim never peeks out.
        self.shell_shade = self._fix("shade_op", ellipse(BODY_A, BODY_B, _shade(hull), segments=BODY_SEGMENTS), 255)
        self.body = self._fix("body_op", ellipse(BODY_A, BODY_B, hull, segments=BODY_SEGMENTS), 255)
        self.hl_out = self._fix("hl_out_op", ellipse(6.2, 3.6, (255, 255, 255), opacity=60, segments=20), 60)
        self.hl_core = self._fix("hl_core_op", ellipse(3.2, 1.8, (255, 255, 255), opacity=170, segments=14), 170)

        self._eyes = []
        self._eye_keys: dict = {}  # side -> {name: key}, so the per-frame loop builds no strings
        for side in (-1, 1):
            cheek = self._fix(f"cheek{side}_op", ellipse(3.0, 2.0, pal["cheek"], opacity=150, segments=16), 150)
            eye = self._fix(f"eye{side}_op", ellipse(EYE_A, EYE_B, pal["eye"], segments=20), 255)
            glint = self._fix(f"glint{side}_op", circle(1.5, (255, 255, 255), segments=12), 255)
            glint2 = self._fix(f"glint2{side}_op", circle(0.8, (255, 255, 255), opacity=200, segments=10), 200)
            lid = ellipse(EYE_A + 0.5, EYE_B + 0.4, hull, opacity=0, segments=20)
            lash = rect(6.6, 1.4, pal["eye"], anchor=(3.3, 0.7), opacity=0)
            brow = rect(5.0, 1.5, pal["eye"], anchor=(2.5, 0.75), opacity=0)
            brow.rotation = 20.0 * side  # inner ends lift: the worried slant
            self._eyes.append((side, cheek, eye, glint, glint2, lid, lash, brow))
            self._eye_keys[side] = {name: f"{name}{side}" for name in EYE_KEY_NAMES}  # built once, not per frame

        self.sweat = circle(1.5, (96, 176, 235), opacity=0, segments=10)
        self.smile = arc(2.2, 180.0, 180.0, 1.2, pal["eye"], 12)
        self.frown = arc(2.2, 0.0, 180.0, 1.2, pal["eye"], 12, opacity=0)

        self.stalk = self._fix("stalk_op", rect(1.6, ANTENNA_LEN, _shade(hull), anchor=(0.8, 0.0)), 255)
        self.ant_halo = circle(4.6, pal["accent"], opacity=80, segments=16)
        self.ant_tip = self._fix("tip_op", circle(2.2, pal["accent"], segments=12), 255)

        self.muzzle = self._fix("muzzle_op", rect(7.0, 3.4, pal["bullet"], anchor=(0.0, 1.7)), 255)
        self.muzzle_glow = circle(2.3, pal["bullet"], opacity=140, segments=12)

    def delete(self) -> None:
        """Free every shape. The instance must not be synced afterwards."""
        for s in self.shapes:
            s.delete()
        self.shapes = []
        self._fixed = []

    # ------------------------------------------------------------- per frame

    @property
    def _vel(self) -> Vec2:
        """Smoothed world velocity as a Vec2 (a read-only view; the floats are the state)."""
        return Vec2(self._vx, self._vy)

    def _put(self, key: str, shape, attr: str, value) -> None:
        """Write one attribute only when its value changed since the last write."""
        if self._last.get(key) != value:
            self._last[key] = value
            setattr(shape, attr, value)

    def _op(self, key: str, shape, value: float) -> None:
        """Write an opacity, scaled by the dissolve fade."""
        self._put(key, shape, "opacity", int(value * self._alpha))

    def _gated(self, key: str, shape, attr: str, value, opacity: int) -> None:
        """Like _put, but a fully transparent part is not moved or recoloured.

        Hidden parts skip the GPU write. Forgetting the cached value makes the first frame the part
        shows again write its real value, so it never appears at a stale place.
        """
        if opacity <= 0:
            self._last.pop(key, None)
            return
        self._put(key, shape, attr, value)

    def _use_palette(self, palette) -> None:
        """Resolve the colour dict to RGB tuples once per palette object, not once per frame."""
        if palette is self._pal_src:
            return
        merged = dict(DEFAULT_PALETTE)
        if palette:
            merged.update(palette)
        self._rgb = {k: tuple(v) for k, v in merged.items()}
        self._pal_src = palette

    def _real_step(self, real_t, dt: float) -> float:
        """Seconds to advance the dissolve by. Real time when given, else the game clock step."""
        if real_t is None:
            return dt
        real_t = float(real_t)
        last = self._real_last
        self._real_last = real_t
        if last is None:
            return 0.0
        return _clamp(real_t - last, 0.0, REAL_STEP_MAX)

    def _advance(self, player, t: float) -> float:
        """Update smoothed velocity, dash and hit state from the player and the clock.

        Returns the seconds of game clock since the last sync (0 when the clock did not move).
        """
        px = float(player.pos.x)
        py = float(player.pos.y)
        dashing = bool(getattr(player, "is_dashing", False))
        flash = float(getattr(player, "damage_flash_timer", 0.0))
        if self._last_t is None or t < self._last_t - 1e-9:
            # First sync of a visual, or the clock restarted for a new run.
            self._px, self._py = px, py
            self._last_t = t
            self._vx = 0.0
            self._vy = 0.0
            self._dash_t0 = None
            self._was_dashing = False
            self._flash_prev = flash
            self._dying = False
            self._death_s = 0.0
            self._ghost_last = -1e9
            for i in range(GHOST_N):
                self._ghost_t[i] = -1e9
            self._stagger.reset(0.0, 0.0)
            self._fresh = True
        dt = t - self._last_t
        if dt > 0.0:
            mx = px - self._px
            my = py - self._py
            if math.hypot(mx, my) <= TELEPORT_PER_S * dt + 1.0:
                k = 1.0 - math.exp(-VELOCITY_SMOOTHING * dt)
                self._vx += (mx / dt - self._vx) * k
                self._vy += (my / dt - self._vy) * k
            else:
                self._vx = 0.0  # a push or respawn is not movement
                self._vy = 0.0
            self._px, self._py = px, py
            self._last_t = t
        if dashing and not self._was_dashing:
            self._dash_t0 = t
            dd = getattr(player, "dash_direction", None)
            self._dash_dx, self._dash_dy = _screen_dir(float(dd.x), float(dd.y)) if dd is not None else (1.0, 0.0)
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
             palette: dict | None = None, real_t: float | None = None) -> tuple[float, float]:
        """Pose the character for this frame and return the screen centre of its body.

        Args:
            player: anything with pos, hp, max_hp, is_dashing, dash_direction, is_boosting,
                invincibility_timer, damage_flash_timer, shield, laser_until and speed.
            shake: the frame's screen shake offset.
            t: game clock in seconds. Dashes, the laser timer and the blink run on it. Idle pulses
                use motion.clock(t), so they stop with config.REDUCE_MOTION.
            aim_dir: world-space aim direction. Defaults to +x when missing or zero.
            palette: colour overrides, see DEFAULT_PALETTE.
            real_t: wall-clock seconds, used only to time the death dissolve, because the game clock
                stops at game over. Omit it and the dissolve follows the game clock.
        """
        self._use_palette(palette)
        rgb = self._rgb
        t = float(t)
        ta = motion.clock(t)                     # ambient pulses: zero with reduced motion
        reduced = motion.reduced()
        aim = aim_dir if (aim_dir is not None and aim_dir.length() > 1e-6) else Vec2(1.0, 0.0)
        ax, ay = _screen_dir(aim.x, aim.y)
        dt = self._advance(player, t)
        real_dt = self._real_step(real_t, dt)
        # With no clock time, or no motion, the springs show their targets at once.
        snap = self._fresh or dt <= 0.0 or reduced

        vx, vy = self._vx, self._vy
        vsx = (vx - vy) * ISO_SCALE_X
        vsy = (vx + vy) * ISO_SCALE_Y
        speed = math.hypot(vx, vy)
        speed_n = min(1.0, speed / max(1.0, float(getattr(player, "speed", PLAYER_SPEED)) * 1.2))
        moving = speed_n > 0.04
        burst = self._dash_burst(t)
        boosting = bool(getattr(player, "is_boosting", False))
        dashing = bool(getattr(player, "is_dashing", False))
        boost_on = boosting or dashing

        # Death: hp at 0 starts the dissolve, which then runs on real time.
        hp = float(getattr(player, "hp", 0.0))
        max_hp = max(1.0, float(getattr(player, "max_hp", 100.0)))
        if hp <= 0.0:
            if not self._dying:
                self._dying = True
                self._death_s = 0.0
        elif self._dying:
            self._dying = False
            self._death_s = 0.0
        if self._dying:
            self._death_s += real_dt
            dis = _clamp(self._death_s / DISSOLVE_S, 0.0, 1.0)
        else:
            dis = 0.0
        self._alpha = 1.0 - dis
        alpha = self._alpha
        if alpha != self._fixed_alpha:  # the fixed parts only change while the dissolve fades
            self._fixed_alpha = alpha
            for key, shape, base in self._fixed:
                self._put(key, shape, "opacity", int(base * alpha))

        # Stretch axis: the dash while it bursts, else the motion, else rest.
        if burst > 0.02:
            tx, ty = self._dash_dx, self._dash_dy
        elif moving:
            n = math.hypot(vsx, vsy) or 1.0
            tx, ty = vsx / n, vsy / n
        else:
            tx, ty = 1.0, 0.0
        self._dx, self._dy = _ease_dir(self._dx, self._dy, tx, ty, 1.0 - math.exp(-DIR_SMOOTHING * dt))

        # Hit: a new or refreshed flash starts a short recoil away from the aim.
        flash = float(getattr(player, "damage_flash_timer", 0.0))
        if flash > self._flash_prev + 1e-6 and not reduced and not self._dying:
            self._stagger.reset(STAGGER_PX, 0.0)
        self._flash_prev = flash
        if reduced:
            self._stagger.reset(0.0, 0.0)
        elif dt > 0.0:
            self._stagger.update(dt)
        kick = self._stagger.value

        # Banking: the shell leans toward the sideways motion, on a damped spring.
        bank_target = _clamp(vsx / BANK_SPEED, -1.0, 1.0) * BANK_PX * motion.factor()
        self._bank.target = bank_target
        if snap:
            self._bank.reset(bank_target, bank_target)
        else:
            self._bank.update(dt)
        bank = self._bank.value

        # Eyes: the pupils ease toward the aim point.
        gaze_tx = ax * GAZE_X
        gaze_ty = ay * GAZE_Y
        self._gaze_x.target = gaze_tx
        self._gaze_y.target = gaze_ty
        if snap:
            self._gaze_x.reset(gaze_tx, gaze_tx)
            self._gaze_y.reset(gaze_ty, gaze_ty)
        else:
            self._gaze_x.update(dt)
            self._gaze_y.update(dt)
        gaze_x = self._gaze_x.value
        gaze_y = self._gaze_y.value

        # Squash and stretch: area-preserving along the axis, a slow breath at rest, a squash on hit.
        breath = math.sin(ta * BREATH_RATE)
        # The stretch with movement and with the dash is motion too, so it is scaled to zero when reduced.
        mf = motion.factor()
        s = 1.0 + mf * (0.12 * speed_n + 0.28 * burst) + BREATH_AMP * breath + 0.10 * abs(kick) / STAGGER_PX
        if self._dying and not reduced:
            s *= 1.0 - 0.15 * dis
        s = max(0.85, s)
        # Quarter-pixel steps: an ellipse rebuilds its vertices whenever a semi-axis changes.
        body_a = round(BODY_A * s * 4.0) / 4.0
        body_b = round(BODY_B / s * 4.0) / 4.0
        angle = -math.degrees(math.atan2(self._dy, self._dx))

        gx, gy = to_iso(player.pos, shake)
        self.ground_y = float(gy)
        bob = math.sin(ta * 6.0) * BOB_AMP
        # The body stands on the ground point, plus the bob and the recoil. Face and muzzle follow it.
        cx = float(gx) - ax * kick
        cy = float(gy) + bob - ay * kick
        shell_x = cx + bank * 0.6
        shell_y = cy

        # Hull colour. Legacy feedback states keep their tints.
        flashing = flash > 0.0
        invuln = float(getattr(player, "invincibility_timer", 0.0)) > 0.0
        if flashing:
            hull = HULL_FLASH
        elif boosting:
            hull = HULL_BOOST
        elif invuln:
            hull = HULL_INVULN
        else:
            hull = rgb["body"]
        shade = _shade(hull)

        self._put("hull", self.body, "color", hull)
        self._put("shade", self.shell_shade, "color", shade)
        self._put("stalk", self.stalk, "color", shade)
        self._put("body_a", self.body, "a", body_a)
        self._put("body_b", self.body, "b", body_b)
        self._put("body_rot", self.body, "rotation", angle)
        self._put("body_pos", self.body, "position", (shell_x, shell_y))
        self._put("shade_a", self.shell_shade, "a", body_a)
        self._put("shade_b", self.shell_shade, "b", body_b)
        self._put("shade_rot", self.shell_shade, "rotation", angle)
        self._put("shade_pos", self.shell_shade, "position", (shell_x, shell_y - 1.6))
        rim_a = round((body_a + OUTLINE_PAD) * 4.0) / 4.0
        rim_b = round((body_b + OUTLINE_PAD) * 4.0) / 4.0
        self._put("rim_a", self.rim, "a", rim_a)
        self._put("rim_b", self.rim, "b", rim_b)
        self._put("rim_rot", self.rim, "rotation", angle)
        self._put("rim_pos", self.rim, "position", (shell_x, shell_y - 0.8))
        self._put("rim_col", self.rim, "color", rgb["eye"])
        self._put("hl_out_pos", self.hl_out, "position", (shell_x - 3.8 + bank * 0.6, shell_y + 4.6))
        self._put("hl_core_pos", self.hl_core, "position", (shell_x - 4.2 + bank * 0.6, shell_y + 5.2))

        # Halo and thruster glow. The halos hang on the ground point, so they stay put at rest.
        glow = BOOST_JET if boosting else rgb["glow"]
        jet_rgb = BOOST_JET if boosting else rgb["trail"]
        halo_pulse = 0.5 + 0.5 * math.sin(ta * 1.8)
        boost_lift = 10 if boost_on else 0
        self._put("halo_far_pos", self.halo_far, "position", (gx, gy))
        self._put("halo_far_col", self.halo_far, "color", glow)
        self._op("halo_far_op", self.halo_far, _clamp(7 + 5 * halo_pulse + boost_lift, 0, 255))
        self._put("halo_out_pos", self.halo_out, "position", (gx, gy))
        self._put("halo_out_col", self.halo_out, "color", glow)
        self._op("halo_out_op", self.halo_out, _clamp(11 + 5 * halo_pulse + boost_lift, 0, 255))
        self._put("halo_in_pos", self.halo_in, "position", (gx, gy))
        self._put("halo_in_col", self.halo_in, "color", glow)
        self._op("halo_in_op", self.halo_in, _clamp(16 + 5 * halo_pulse + boost_lift, 0, 255))
        self._put("shadow_pos", self.shadow, "position", (gx, gy - 19.0))

        level = _clamp(0.35 + 0.5 * speed_n + (0.45 if boost_on else 0.0), 0.0, 1.0)
        bx, by = -ax, -ay
        flick = _flicker(ta, boost_on, 0.0)
        self._put("thrust_col", self.thrust, "color", glow)
        self._put("thrust_pos", self.thrust, "position", (cx + bx * 13.0, cy + by * 13.0))
        self._op("thrust_op", self.thrust, 110 * level * flick)
        self._put("thrust_core_col", self.thrust_core, "color", jet_rgb)
        self._put("thrust_core_pos", self.thrust_core, "position", (cx + bx * 12.0, cy + by * 12.0))
        self._op("thrust_core_op", self.thrust_core, 190 * level * _flicker(ta, boost_on, 2.1))
        for i, jet in enumerate(self.jets):
            dist = _JET_DIST[i]
            k_col, k_pos, k_op = self._jet_keys[i]
            jf = _flicker(ta, boost_on, 1.3 * (i + 1))
            self._put(k_col, jet, "color", jet_rgb)
            self._put(k_pos, jet, "position", (cx + bx * dist, cy + by * dist))
            self._op(k_op, jet, _JET_ALPHA[i] * level * jf)

        if self._dying and not reduced:
            self._update_dissolve(cx, cy, hull, dis)
        else:
            self._update_ghosts(t, burst, body_a, body_b, angle, shell_x, shell_y, glow, reduced)
        self._update_auras(player, t, ta, cx, cy)

        # Face. Eyes look at the aim point, blink on a fixed clock, worry under 30% HP.
        worried = hp / max_hp < WORRY_HP_FRAC
        if worried:
            gaze_x += math.sin(ta * 37.0) * 0.6  # the worried pupils tremble
            gaze_y += math.cos(ta * 29.0) * 0.4
        phase = (ta + BLINK_PHASE_OFFSET) % BLINK_PERIOD
        closed = phase < BLINK_CLOSED_S or self._dying  # a knocked-out body keeps its eyes shut

        eye_rgb = rgb["eye"]
        cheek_rgb = rgb["cheek"]
        lid_op = 255 if closed else 0
        brow_op = 235 if worried else 0
        for side, cheek, eye, glint, glint2, lid, lash, brow in self._eyes:
            k = self._eye_keys[side]
            ex = cx + side * EYE_X + gaze_x
            ey = cy + EYE_Y + gaze_y
            self._put(k["cheek_col"], cheek, "color", cheek_rgb)
            self._put(k["cheek"], cheek, "position", (cx + side * CHEEK_X, cy + CHEEK_Y))
            self._put(k["eye_col"], eye, "color", eye_rgb)
            self._put(k["eye"], eye, "position", (ex, ey))
            self._put(k["glint"], glint, "position", (ex + 1.3, ey + 1.9))
            self._put(k["glint2"], glint2, "position", (ex - 1.2, ey - 1.7))
            self._gated(k["lid_pos"], lid, "position", (ex, ey), lid_op)
            self._gated(k["lid_col"], lid, "color", hull, lid_op)
            self._op(k["lid_op"], lid, lid_op)
            self._gated(k["lash_pos"], lash, "position", (ex, ey), lid_op)
            self._gated(k["lash_col"], lash, "color", eye_rgb, lid_op)
            self._op(k["lash_op"], lash, lid_op)
            self._gated(k["brow_pos"], brow, "position", (cx + side * EYE_X, cy + EYE_Y + EYE_B + 2.6), brow_op)
            self._gated(k["brow_col"], brow, "color", eye_rgb, brow_op)
            self._op(k["brow_op"], brow, brow_op)

        sweat_op = 230 if worried else 0
        self._gated("sweat_pos", self.sweat, "position", (cx - 13.4, cy + 7.8), sweat_op)
        self._op("sweat_op", self.sweat, sweat_op)
        smile_op = 0 if worried else 255
        self._gated("smile_pos", self.smile, "position", (cx, cy - 1.6), smile_op)
        self._gated("smile_col", self.smile, "color", eye_rgb, smile_op)
        self._op("smile_op", self.smile, smile_op)
        frown_op = 255 if worried else 0
        self._gated("frown_pos", self.frown, "position", (cx, cy - 3.6), frown_op)
        self._gated("frown_col", self.frown, "color", eye_rgb, frown_op)
        self._op("frown_op", self.frown, frown_op)

        # Antenna sways at rest, leans back against the motion, and lags behind the banking spring.
        bank_n = _clamp(bank / BANK_PX, -1.0, 1.0)
        sway = 8.0 * math.sin(ta * 2.3) - mf * 12.0 * _clamp(vsx / 220.0, -1.0, 1.0) - 6.0 * bank_n
        pivot_x = shell_x
        pivot_y = shell_y + ANTENNA_Y
        rad = math.radians(sway)
        tip_x = pivot_x + math.sin(rad) * ANTENNA_LEN
        tip_y = pivot_y + math.cos(rad) * ANTENNA_LEN
        self._put("stalk_pos", self.stalk, "position", (pivot_x, pivot_y))
        self._put("stalk_rot", self.stalk, "rotation", sway)
        self._put("tip_pos", self.ant_tip, "position", (tip_x, tip_y))
        self._put("tip_col", self.ant_tip, "color", rgb["accent"])
        self._put("ant_halo_pos", self.ant_halo, "position", (tip_x, tip_y))
        self._put("ant_halo_col", self.ant_halo, "color", rgb["accent"])
        self._op("ant_halo_op", self.ant_halo, 70 + 50 * (0.5 + 0.5 * math.sin(ta * 3.5)))

        # Muzzle nub on the aim side.
        self._put("muzzle_pos", self.muzzle, "position", (cx + ax * 11.0, cy + ay * 11.0))
        self._put("muzzle_rot", self.muzzle, "rotation", -math.degrees(math.atan2(ay, ax)))
        self._put("muzzle_col", self.muzzle, "color", rgb["bullet"])
        self._put("muzzle_glow_pos", self.muzzle_glow, "position", (cx + ax * 18.5, cy + ay * 18.5))
        self._put("muzzle_glow_col", self.muzzle_glow, "color", rgb["bullet"])
        self._op("muzzle_glow_op", self.muzzle_glow, 120 + 60 * (0.5 + 0.5 * math.sin(ta * 12.0)))

        self._fresh = False
        return cx, cy

    def _update_ghosts(self, t: float, burst: float, body_a: float, body_b: float, angle: float,
                       x: float, y: float, color, reduced: bool) -> None:
        """Afterimage: sample the body into a ring during the dash burst, then fade each sample out.

        The ring holds GHOST_N samples and is reused, so a dash allocates nothing. Reduced motion
        takes no samples, so no ghost ever shows.
        """
        if not reduced and burst > 0.0 and t - self._ghost_last >= GHOST_STEP_S:
            i = self._ghost_next
            self._ghost_t[i] = t
            self._ghost_x[i] = x
            self._ghost_y[i] = y
            self._ghost_a[i] = body_a
            self._ghost_b[i] = body_b
            self._ghost_r[i] = angle
            self._ghost_next = (i + 1) % GHOST_N
            self._ghost_last = t
        for i, ghost in enumerate(self.ghosts):
            k_pos, k_a, k_b, k_rot, k_col, k_op = self._ghost_keys[i]
            age = t - self._ghost_t[i]
            if reduced or age < 0.0 or age >= GHOST_LIFE_S:
                self._op(k_op, ghost, 0)
                continue
            fade = 1.0 - age / GHOST_LIFE_S
            self._put(k_pos, ghost, "position", (self._ghost_x[i], self._ghost_y[i]))
            self._put(k_a, ghost, "a", self._ghost_a[i])
            self._put(k_b, ghost, "b", self._ghost_b[i])
            self._put(k_rot, ghost, "rotation", self._ghost_r[i])
            self._put(k_col, ghost, "color", color)
            self._op(k_op, ghost, GHOST_ALPHA * 255.0 * fade)

    def _update_dissolve(self, cx: float, cy: float, hull, dis: float) -> None:
        """Death dissolve: the body breaks into GHOST_N pieces that fly out and sink back under gravity.

        The pieces are the afterimage shells, which stay idle while the player is dead, so the dissolve
        adds no shapes. Each piece keeps one size for the whole dissolve, so its vertices are built once;
        only its position and its fade change per frame.
        """
        reach = DISSOLVE_REACH * ease_out_cubic(dis)
        lift = DISSOLVE_LIFT * dis * dis
        for i, ghost in enumerate(self.ghosts):
            k_pos, k_a, k_b, k_rot, k_col, k_op = self._ghost_keys[i]
            ang = i * 1.5707963 + 0.6  # four pieces, spread a quarter turn apart
            self._put(k_a, ghost, "a", DISSOLVE_R)
            self._put(k_b, ghost, "b", DISSOLVE_R * 0.8)
            self._put(k_rot, ghost, "rotation", 0.0)
            self._put(k_pos, ghost, "position",
                      (cx + math.cos(ang) * reach, cy + math.sin(ang) * reach * 0.6 - lift))
            self._put(k_col, ghost, "color", hull)
            self._op(k_op, ghost, 255)

    def _update_auras(self, player, t: float, ta: float, cx: float, cy: float) -> None:
        """Shield, laser and overdrive rings, as the legacy ship drew them.

        The conditions read the game clock ``t``; the pulses read the motion clock ``ta``.
        """
        # Arc radii are quantised to half pixels because each change rebuilds the ring's vertices.
        shield = float(getattr(player, "shield", 0) or 0)
        if shield > 0:
            pulse = 0.65 + 0.35 * math.sin(ta * 6.5)
            self._put("sh1_pos", self.aura_shield, "position", (cx, cy))
            self._put("sh2_pos", self.aura_shield2, "position", (cx, cy))
            self._put("sh1_r", self.aura_shield, "radius", _half_px(18.0 + 2.0 * pulse))
            self._put("sh2_r", self.aura_shield2, "radius", _half_px(24.0 + 3.0 * pulse))
            cap = float(SHIELD_MAX)
            self._op("sh1_op", self.aura_shield, 90 + min(cap, shield) * pulse)
            self._op("sh2_op", self.aura_shield2, 60 + min(cap, shield) * 0.5 * pulse)
        else:
            self._op("sh1_op", self.aura_shield, 0)
            self._op("sh2_op", self.aura_shield2, 0)

        if float(getattr(player, "laser_until", 0.0)) > t:
            pulse = 0.6 + 0.4 * math.sin(ta * 10.0)
            self._put("laser_pos", self.aura_laser, "position", (cx, cy))
            self._put("laser_r", self.aura_laser, "radius", _half_px(22.0 + 3.0 * pulse))
            self._op("laser_op", self.aura_laser, 160 * pulse)
        else:
            self._op("laser_op", self.aura_laser, 0)

        if bool(getattr(player, "is_boosting", False)):
            bpulse = 0.65 + 0.35 * math.sin(ta * 22.0)
            self._put("boost_pos", self.aura_boost, "position", (cx, cy))
            self._put("boost_r", self.aura_boost, "radius", _half_px(26.0 + 3.0 * bpulse))
            self._op("boost_op", self.aura_boost, 140 + 80 * bpulse)
        else:
            self._op("boost_op", self.aura_boost, 0)
