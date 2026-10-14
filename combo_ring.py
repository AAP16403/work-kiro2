"""Combo timer ring: a radial sweep beside the score panel, coloured by the combo's multiplier tier.

The sweep is the share of the combo timeout still open (score.ScoreTracker.combo_window_left): full right after
a kill, empty at the timeout, and empty while the combo decays. Its colour is the multiplier tier (combo_tier).
Each tier change starts one pulse. In full motion the pulse is a halo that grows and fades out. With
config.REDUCE_MOTION set the pulse is a colour flash only: nothing moves.

ComboRing is pooled. Its three pyglet arcs (track, sweep and halo) are created once in __init__. place() and
update() move, re-angle and re-colour them in place, so a frame creates no shapes. pyglet rebuilds an arc's vertices
on every radius, thickness or angle write, so the sweep is re-angled only when its fraction changes, and the halo
is re-sized only while a pulse runs.

Every number comes from config.py.
"""

from pyglet import shapes

import config
from anim import clamp, ease_out_cubic
from ui_theme import MUTED

WHITE = (255, 255, 255)


def combo_tier(combo) -> int:
    """Tier index of a combo multiplier: the highest tier whose threshold in COMBO_RING_TIER_MIN it reaches."""
    value = float(combo)
    tier = 0
    for index, lo in enumerate(config.COMBO_RING_TIER_MIN):
        if value >= float(lo):
            tier = index
    return tier


def combo_tier_color(tier) -> tuple:
    """RGB colour of a tier index, clamped to the tiers that config defines."""
    colors = config.COMBO_RING_TIER_COLORS
    index = max(0, min(len(colors) - 1, int(tier)))
    return tuple(colors[index])


def _mix(a, b, t: float) -> tuple:
    """Linear blend of two RGB tuples, t clamped to 0..1."""
    t = clamp(float(t), 0.0, 1.0)
    return (
        int(round(a[0] + (b[0] - a[0]) * t)),
        int(round(a[1] + (b[1] - a[1]) * t)),
        int(round(a[2] + (b[2] - a[2]) * t)),
    )


def ring_reach(radius: float, thickness: float) -> float:
    """Outer reach of a ring from its centre, at the pulse's largest extent.

    The track and sweep reach radius + thickness (more than their band's edge, which is radius + thickness / 2). The halo
    reaches its largest at (1 + COMBO_RING_PULSE_GROW) times the radius, with the thickness place() gives it. The larger
    of the two is what layout must keep clear of its neighbours, so a pulse never runs into them.
    """
    radius = float(radius)
    thickness = float(thickness)
    halo = max(1.0, thickness * float(config.COMBO_RING_HALO_THICKNESS))
    return max(radius + thickness, radius * (1.0 + float(config.COMBO_RING_PULSE_GROW)) + halo)


def fit_ring(radius: float, thickness: float, room: float) -> tuple:
    """(radius, thickness) scaled down together until ring_reach fits in room. A ring that already fits is unchanged.

    The halo's thickness has a floor, so the reach does not scale exactly with the pair. The scale is corrected until
    the reach fits. A room of zero or less gives a ring of zero size.
    """
    radius = float(radius)
    thickness = float(thickness)
    room = max(0.0, float(room))
    if ring_reach(radius, thickness) <= room:
        return radius, thickness
    k = room / ring_reach(radius, thickness)
    for _ in range(16):
        if k <= 0.0:
            break
        reach = ring_reach(radius * k, thickness * k)
        if reach <= room + 1e-9:
            break
        k *= room / reach
    return radius * k, thickness * k


class ComboRing:
    """Track, sweep and halo arcs around the score panel. update() takes the combo state, tick() runs the pulse."""

    def __init__(self, batch):
        segments = max(8, int(config.COMBO_RING_SEGMENTS))
        self._track_rgb = (int(MUTED[0]), int(MUTED[1]), int(MUTED[2]))
        self._track_alpha = int(config.COMBO_RING_TRACK_ALPHA)
        self._sweep_alpha = int(config.COMBO_RING_SWEEP_ALPHA)
        base = combo_tier_color(0)
        self._track = shapes.Arc(
            0.0, 0.0, 1.0, segments=segments, angle=360.0, thickness=1.0,
            color=(*self._track_rgb, self._track_alpha), batch=batch,
        )
        self._sweep = shapes.Arc(
            0.0, 0.0, 1.0, segments=segments, angle=0.0, start_angle=90.0, thickness=1.0,
            color=(*base, self._sweep_alpha), batch=batch,
        )
        self._halo = shapes.Arc(
            0.0, 0.0, 1.0, segments=segments, angle=360.0, thickness=1.0,
            color=(*base, 255), batch=batch,
        )
        # pyglet rebuilds an arc's vertices on every visible write, so a shown state is written only when it changes.
        self._sweep.visible = False
        self._halo.visible = False
        self._sweep_shown = False
        self._halo_shown = False
        self._enabled = True   # False hides the whole ring (the HUD does this where the status line cannot clear it)
        self._geom = None      # (cx, cy, radius, thickness) once place() has run
        self._tier = -1        # tier now shown; -1 before the first update, so the first tier does not pulse
        self._tier_rgb = base
        self._frac = -1.0      # sweep fraction last written to the arc
        self._pulse_t = -1.0   # seconds into the running pulse; negative when none runs
        self._flash_k = 0.0    # reduced-motion flash level last written (0.0 means the base colours)
        self.pulse_count = 0   # pulses started so far: one per tier change

    # ------------------------------------------------------------------
    # Read-only state (tests and the HUD read these; nothing here draws)
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def tier(self) -> int:
        return self._tier

    @property
    def sweep_fraction(self) -> float:
        return max(0.0, self._frac)

    @property
    def sweep_color(self) -> tuple:
        return tuple(self._sweep.color[:3])

    @property
    def track_color(self) -> tuple:
        return tuple(self._track.color)

    @property
    def sweep_visible(self) -> bool:
        return bool(self._sweep.visible)

    @property
    def pulsing(self) -> bool:
        return self._pulse_t >= 0.0

    @property
    def halo_visible(self) -> bool:
        return bool(self._halo.visible)

    @property
    def halo_radius(self) -> float:
        return float(self._halo.radius)

    @property
    def geometry(self):
        """(cx, cy, radius, thickness) as placed, or None before place()."""
        return self._geom

    # ------------------------------------------------------------------
    # Layout and per-frame update
    # ------------------------------------------------------------------

    def place(self, cx: float, cy: float, radius: float, thickness: float) -> None:
        """Position and size the ring. HUD.layout calls this on a resize, never per frame."""
        cx = float(cx)
        cy = float(cy)
        radius = float(radius)
        thickness = float(thickness)
        self._geom = (cx, cy, radius, thickness)
        for shp in (self._track, self._sweep, self._halo):
            shp.x = cx
            shp.y = cy
        self._track.radius = radius
        self._track.thickness = thickness
        self._sweep.radius = radius
        self._sweep.thickness = thickness
        self._halo.radius = radius
        self._halo.thickness = max(1.0, thickness * float(config.COMBO_RING_HALO_THICKNESS))
        self._frac = -1.0  # force the sweep to be re-angled for the new geometry

    def set_enabled(self, on: bool) -> None:
        """Show or hide the whole ring. Hidden, it keeps its state and its pulse, and draws nothing."""
        on = bool(on)
        if on == self._enabled:
            return
        self._enabled = on
        self._track.visible = on
        self._sync_sweep()
        if not on:
            self._show_halo(False)
            self._flash(0.0)

    def update(self, combo: float, window_left: float) -> None:
        """Show the combo: the tier colour, and the share of the combo timeout still open as the sweep.

        A tier change starts a pulse (see tick). The sweep is empty with no combo (multiplier 1.0).
        """
        tier = combo_tier(combo)
        if tier != self._tier:
            if self._tier >= 0:
                self._start_pulse()
            self._tier = tier
            self._tier_rgb = combo_tier_color(tier)
            self._sweep.color = (*self._tier_rgb, self._sweep_alpha)
            self._halo.color = (*self._tier_rgb, 255)
            self._flash_k = -1.0  # the next tick writes the flash again, if a pulse runs
        frac = clamp(float(window_left), 0.0, 1.0) if float(combo) > 1.0 else 0.0
        if frac != self._frac:
            self._frac = frac
            self._sweep.angle = 360.0 * frac
            self._sync_sweep()

    def _sync_sweep(self) -> None:
        """Show the sweep while the ring is on and some of the combo window is left. Writes only on a change."""
        want = self._enabled and self._frac > 0.0
        if want != self._sweep_shown:
            self._sweep_shown = want
            self._sweep.visible = want

    def tick(self, dt: float, reduce_motion: bool = False) -> None:
        """Advance the running pulse by dt seconds. Idle frames return at once, and a hidden ring holds its pulse.

        Full motion: the halo grows to (1 + COMBO_RING_PULSE_GROW) times the radius and fades out.
        Reduced motion: the track and sweep flash toward the tier colour and white, then settle. Nothing moves.
        """
        if self._pulse_t < 0.0 or self._geom is None or not self._enabled:
            return
        self._pulse_t += max(0.0, float(dt))
        span = max(1e-6, float(config.COMBO_RING_PULSE_SECONDS))
        if self._pulse_t >= span:
            self._end_pulse()
            return
        p = self._pulse_t / span
        if reduce_motion:
            self._show_halo(False)
            self._flash(1.0 - ease_out_cubic(p))
        else:
            self._flash(0.0)
            eased = ease_out_cubic(p)
            self._show_halo(True)
            self._halo.radius = self._geom[2] * (1.0 + float(config.COMBO_RING_PULSE_GROW) * eased)
            self._halo.opacity = int(round(255 * (1.0 - p)))

    # ------------------------------------------------------------------
    # Pulse internals
    # ------------------------------------------------------------------

    def _start_pulse(self) -> None:
        self._pulse_t = 0.0
        self.pulse_count += 1

    def _end_pulse(self) -> None:
        self._pulse_t = -1.0
        self._show_halo(False)
        self._flash(0.0)

    def _show_halo(self, shown: bool) -> None:
        """Show or hide the halo. The write happens only on a change, since every visible write rebuilds the arc."""
        if shown != self._halo_shown:
            self._halo_shown = shown
            self._halo.visible = shown

    def _flash(self, k: float) -> None:
        """Set the reduced-motion colour flash: k 1.0 at the start of a pulse, 0.0 at rest. Writes only on change."""
        if k == self._flash_k:
            return
        self._flash_k = k
        rgb = self._tier_rgb
        if k <= 0.0:
            self._track.color = (*self._track_rgb, self._track_alpha)
            self._sweep.color = (*rgb, self._sweep_alpha)
            return
        self._sweep.color = (*_mix(rgb, WHITE, float(config.COMBO_RING_FLASH_WHITE) * k), self._sweep_alpha)
        track_rgb = _mix(self._track_rgb, rgb, k)
        alpha = int(round(self._track_alpha + (255 - self._track_alpha) * k))
        self._track.color = (*track_rgb, alpha)
