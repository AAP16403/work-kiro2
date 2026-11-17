"""Pure arena geometry for map.py. No pyglet calls: every function returns plain tuples.

map.py turns each record into a pyglet shape on the main thread, in the order the functions return
them. That order is the old creation order, so the batch fills the same way and the picture is the same.

Randomness: each builder takes an ``rng`` with the ``random`` module's uniform / random / choice /
randint methods, and draws from it in the same order the old map.py did. map.py passes the module
itself (the default; same global stream as before). The worker passes ``random.Random(seed)``. For one
seed the two give the same output, and the tests check this against the base-commit map.py.

Records (plain tuples):
    ("circle", x, y, radius, color, opacity)
    ("line", x1, y1, x2, y2, thickness, color, opacity)
    ("polygon", vertices, color, opacity)        vertices: tuple of (x, y)
    ("rect", x, y, width, height, color, opacity)

An op is ``(target, record, aux)``. ``target`` names the Room list the shape joins, and ``aux`` holds
the per-shape animation values the old code stored beside the shape (see map.py).

Worker: ``FloorPrefetcher`` runs ``floor_ops_seeded`` in a spawn-context process. It never blocks the
main thread. If the result is not ready, or the worker fails, the caller builds the same ops in-process.
"""

import math
import multiprocessing
import random
import secrets
from dataclasses import dataclass

import config
from utils import Vec2

# The flag default. map.py reads config.ARENA_GEOMETRY_WORKER and falls back to this value.
WORKER_ENABLED_DEFAULT = False


@dataclass(frozen=True)
class ArenaSpec:
    """Everything the floor depends on, as plain values. Hashable, so it can key a prefetch request."""

    map_type: str
    radius: float
    width: float
    height: float
    view_w: float
    view_h: float
    iso_x: float
    iso_y: float
    floor_main: tuple
    floor_edge: tuple
    floor_grid: tuple


def _iso(p: Vec2, s: ArenaSpec) -> tuple:
    """utils.to_iso with the shake at zero, and the view size and scales taken from the spec."""
    ix = (p.x - p.y) * s.iso_x
    iy = (p.x + p.y) * s.iso_y
    return (ix + s.view_w / 2 + 0, iy + s.view_h / 2 + 0)


def _circle(x, y, radius, color, opacity=255):
    return ("circle", x, y, radius, color, opacity)


def _line(x1, y1, x2, y2, thickness, color, opacity=255):
    return ("line", x1, y1, x2, y2, thickness, color, opacity)


def _poly(vertices, color, opacity=255):
    return ("polygon", tuple(vertices), color, opacity)


# ---------------------------------------------------------------- background and ambient

def background_ops(width, height, top, bottom) -> list:
    """The two gradient rectangles behind the floor. Both start at the origin."""
    return [
        ("bg_a", ("rect", 0, 0, width, height, top, 255), None),
        ("bg_b", ("rect", 0, 0, width, height, bottom, 120), None),
    ]


def ambient_ops(width, height, rng=random) -> list:
    """Drifting orbs, corner vignettes, scanlines and the background grid, in the old creation order."""
    ops = []
    count = max(8, min(18, int((width * height) / 140_000)))
    for _ in range(count):
        r = rng.uniform(14, 40)
        x = rng.uniform(0, width)
        y = rng.uniform(0, height)
        col = rng.choice([(40, 80, 140), (90, 50, 120), (60, 110, 160)])
        opacity = rng.randint(18, 40)
        vx = rng.uniform(-10, 10)
        vy = rng.uniform(-8, 8)
        phase = rng.uniform(0, math.tau)
        ops.append(("ambient", _circle(x, y, r, col, opacity), (vx, vy, phase)))

    corners = ((0, 0), (width, 0), (0, height), (width, height))
    for cx, cy in corners:
        vr = min(width, height) * rng.uniform(0.32, 0.46)
        opacity = rng.randint(34, 54)
        phase = rng.uniform(0.0, math.tau)
        ops.append(("vignette", _circle(cx, cy, vr, (6, 7, 12), opacity), phase))

    scan_count = max(12, min(24, int(height / 42)))
    for i in range(scan_count):
        y = (i / max(1, scan_count - 1)) * height
        base = rng.randint(9, 20)
        phase = rng.uniform(0.0, math.tau)
        ops.append(("scanline", _line(0, y, width, y, 1, (90, 120, 180), base), (base, phase)))

    bg_grid_count = max(10, min(20, int(width / 50)))
    for i in range(bg_grid_count):
        x = (i / max(1, bg_grid_count - 1)) * width
        base = rng.randint(5, 15)
        phase = rng.uniform(0.0, math.tau)
        ops.append(("bg_grid", _line(x, 0, x, height, 1, (100, 120, 160), base), (base, phase)))
    return ops


# ---------------------------------------------------------------- floor

def floor_ops(spec: ArenaSpec, rng=random) -> list:
    """The floor: polygons, edge, intensity overlays, light circles, grid, boundary, then the decor."""
    radius = float(spec.radius)
    ops = []

    def iso_point(angle, r=radius):
        p = Vec2(math.cos(angle) * float(r), math.sin(angle) * float(r))
        return _iso(p, spec)

    points_list = []
    if spec.map_type == config.MAP_DIAMOND:
        points = [iso_point(i * math.pi / 2, radius * 1.1) for i in range(4)]
        points_list.append(points)

    elif spec.map_type == config.MAP_CROSS:
        w = radius * 0.35
        r = radius
        logic_pts = [
            Vec2(w, w), Vec2(r, w), Vec2(r, -w), Vec2(w, -w),
            Vec2(w, -r), Vec2(-w, -r), Vec2(-w, -w), Vec2(-r, -w),
            Vec2(-r, w), Vec2(-w, w), Vec2(-w, r), Vec2(w, r),
        ]
        points_list.append([_iso(p, spec) for p in logic_pts])

    elif spec.map_type == config.MAP_DONUT:
        inner = radius * 0.4
        segments = 16
        for i in range(segments):
            a1 = (i / segments) * math.tau
            a2 = ((i + 1) / segments) * math.tau
            p1 = iso_point(a1, inner)
            p2 = iso_point(a1, radius)
            p3 = iso_point(a2, radius)
            p4 = iso_point(a2, inner)
            points_list.append([p1, p2, p3, p4])

    else:  # MAP_CIRCLE
        points_list.append([iso_point((i / 32) * math.tau, radius) for i in range(32)])

    for pts in points_list:
        ops.append(("floor", _poly(pts, spec.floor_main), None))

    if spec.map_type in (config.MAP_CIRCLE, config.MAP_DIAMOND):
        edge_pts = (
            [iso_point((i / 32) * math.tau, radius * 1.03) for i in range(32)]
            if spec.map_type == config.MAP_CIRCLE
            else [iso_point(i * math.pi / 2, radius * 1.13) for i in range(4)]
        )
        ops.append(("edge", _poly(edge_pts, spec.floor_edge, 150), None))

    for pts in points_list:
        ops.append(("intensity", _poly(pts, (60, 30, 20), 0), None))

    cx = spec.width * 0.5
    cy = spec.height * 0.5
    ops.append(("decor", _circle(cx, cy, min(spec.width, spec.height) * 0.30, (60, 80, 125), 18), None))
    ops.append(("decor", _circle(cx, cy, min(spec.width, spec.height) * 0.18, (140, 95, 190), 12), None))

    grid_step = max(52, int(radius * 0.14))
    grid_n = max(5, int(radius // grid_step))
    for i in range(-grid_n, grid_n + 1):
        ax, ay = _iso(Vec2(i * grid_step, -radius), spec)
        bx, by = _iso(Vec2(i * grid_step, radius), spec)
        ops.append(("grid", _line(ax, ay, bx, by, 1, spec.floor_grid, 120), None))

        ax, ay = _iso(Vec2(-radius, i * grid_step), spec)
        bx, by = _iso(Vec2(radius, i * grid_step), spec)
        ops.append(("grid", _line(ax, ay, bx, by, 1, spec.floor_grid, 120), None))

    fine_grid_step = max(28, int(radius * 0.075))
    fine_n = max(10, int(radius // fine_grid_step))
    for i in range(-fine_n, fine_n + 1):
        ax, ay = _iso(Vec2(i * fine_grid_step, -radius), spec)
        bx, by = _iso(Vec2(i * fine_grid_step, radius), spec)
        ops.append(("grid", _line(ax, ay, bx, by, 0.5, spec.floor_grid, 40), None))

        ax, ay = _iso(Vec2(-radius, i * fine_grid_step), spec)
        bx, by = _iso(Vec2(radius, i * fine_grid_step), spec)
        ops.append(("grid", _line(ax, ay, bx, by, 0.5, spec.floor_grid, 40), None))

    all_lines = []
    if spec.map_type == config.MAP_DONUT:
        seg = 32
        for i in range(seg):
            a1 = (i / seg) * math.tau
            p1 = iso_point(a1, radius)
            a2 = ((i + 1) / seg) * math.tau
            p2 = iso_point(a2, radius)
            all_lines.append((p1, p2))
        inner = radius * 0.4
        for i in range(seg):
            a1 = (i / seg) * math.tau
            p1 = iso_point(a1, inner)
            a2 = ((i + 1) / seg) * math.tau
            p2 = iso_point(a2, inner)
            all_lines.append((p1, p2))

    elif spec.map_type == config.MAP_CROSS:
        w = radius * 0.35
        r = radius
        logic_pts = [
            Vec2(w, w), Vec2(r, w), Vec2(r, -w), Vec2(w, -w),
            Vec2(w, -r), Vec2(-w, -r), Vec2(-w, -w), Vec2(-r, -w),
            Vec2(-r, w), Vec2(-w, w), Vec2(-w, r), Vec2(w, r),
        ]
        screen_pts = [_iso(p, spec) for p in logic_pts]
        for i in range(len(screen_pts)):
            all_lines.append((screen_pts[i], screen_pts[(i + 1) % len(screen_pts)]))

    elif spec.map_type == config.MAP_DIAMOND:
        pts = [iso_point(i * math.pi / 2, radius * 1.1) for i in range(4)]
        for i in range(4):
            all_lines.append((pts[i], pts[(i + 1) % 4]))

    else:  # circle
        seg = 40
        for i in range(seg):
            a1 = (i / seg) * math.tau
            p1 = iso_point(a1, radius)
            a2 = ((i + 1) / seg) * math.tau
            p2 = iso_point(a2, radius)
            all_lines.append((p1, p2))

    for p1, p2 in all_lines:
        phase = rng.uniform(0.0, math.tau)
        ops.append(("boundary", _line(p1[0], p1[1], p2[0], p2[1], 2, (155, 110, 180), 135), phase))

    ops.extend(_decor_ops(spec, radius, rng))
    return ops


def _decor_ops(spec: ArenaSpec, radius: float, rng) -> list:
    """Panels, seams, glows, the reactor seal, cracks, circuit lines and beacons."""
    ops = []

    panel_count = max(26, min(70, int(radius * 0.20)))
    for _ in range(panel_count):
        ang = rng.uniform(0.0, math.tau)
        r = (rng.random() ** 0.65) * (radius * 0.82)
        center = Vec2(math.cos(ang) * r, math.sin(ang) * r)

        sx = rng.uniform(18.0, 46.0)
        sy = rng.uniform(12.0, 34.0)

        p1 = center + Vec2(sx, 0.0)
        p2 = center + Vec2(0.0, sy)
        p3 = center + Vec2(-sx, 0.0)
        p4 = center + Vec2(0.0, -sy)
        x1, y1 = _iso(p1, spec)
        x2, y2 = _iso(p2, spec)
        x3, y3 = _iso(p3, spec)
        x4, y4 = _iso(p4, spec)

        col = rng.choice([(42, 45, 50), (35, 38, 42), (48, 52, 60), (32, 35, 40)])
        poly_opacity = rng.randint(22, 46)
        ops.append(("decor", _poly(((x1, y1), (x2, y2), (x3, y3), (x4, y4)), col, poly_opacity), None))

        if rng.random() < 0.22 and sx * sy > 700:
            seam_col = rng.choice([(85, 82, 78), (75, 72, 68), (95, 90, 85)])
            base = rng.randint(28, 55)
            for (ax, ay), (bx, by) in (
                ((x1, y1), (x2, y2)),
                ((x2, y2), (x3, y3)),
                ((x3, y3), (x4, y4)),
                ((x4, y4), (x1, y1)),
            ):
                ops.append(("decor", _line(ax, ay, bx, by, 1, seam_col, base), None))

        if rng.random() < 0.3:
            p1_inner = center + Vec2(sx * 0.5, 0.0)
            p2_inner = center + Vec2(0.0, sy * 0.5)
            p3_inner = center + Vec2(-sx * 0.5, 0.0)
            p4_inner = center + Vec2(0.0, -sy * 0.5)
            x1_inner, y1_inner = _iso(p1_inner, spec)
            x2_inner, y2_inner = _iso(p2_inner, spec)
            x3_inner, y3_inner = _iso(p3_inner, spec)
            x4_inner, y4_inner = _iso(p4_inner, spec)
            inner_col = rng.choice([(55, 52, 48), (46, 44, 40)])
            inner_opacity = rng.randint(30, 50)
            ops.append((
                "decor",
                _poly(((x1_inner, y1_inner), (x2_inner, y2_inner), (x3_inner, y3_inner), (x4_inner, y4_inner)),
                      inner_col, inner_opacity),
                None,
            ))

        if rng.random() < 0.15:
            cx, cy = _iso(center, spec)
            glow_radius = rng.uniform(3, 6)
            glow_opacity = rng.randint(20, 40)
            ops.append(("decor", _circle(cx, cy, glow_radius, (150, 180, 220), glow_opacity), None))

    seal_r = radius * 0.35
    seal_segments = 64
    seal_color = (60, 70, 85)
    seal_points = []
    for i in range(seal_segments):
        a = (i / seal_segments) * math.tau
        r_mod = seal_r * (0.9 + 0.1 * math.cos(a * 4))
        seal_points.append(_iso(Vec2(math.cos(a) * r_mod, math.sin(a) * r_mod), spec))
    for i in range(seal_segments):
        p1 = seal_points[i]
        p2 = seal_points[(i + 1) % seal_segments]
        ops.append(("decor", _line(p1[0], p1[1], p2[0], p2[1], 2, seal_color, 60), None))
        if i % 8 == 0:
            p3 = _iso(Vec2(0, 0), spec)
            ops.append(("decor", _line(p1[0], p1[1], p3[0], p3[1], 1, seal_color, 40), None))

    crack_count = max(8, min(18, int(radius * 0.04)))
    for _ in range(crack_count):
        ang = rng.uniform(0.0, math.tau)
        r_start = (rng.random() ** 0.6) * (radius * 0.75)
        if r_start < seal_r:
            r_start = seal_r + (seal_r * 0.2)
        start = Vec2(math.cos(ang) * r_start, math.sin(ang) * r_start)
        seg_count = rng.randint(2, 4)
        cur = start
        for _seg in range(seg_count):
            seg_len = rng.uniform(15.0, 55.0)
            seg_ang = ang + rng.uniform(-0.6, 0.6)
            nxt = cur + Vec2(math.cos(seg_ang), math.sin(seg_ang)) * seg_len
            if nxt.length() > radius * 0.9:
                break
            cx1, cy1 = _iso(cur, spec)
            cx2, cy2 = _iso(nxt, spec)
            crack_col = rng.choice([(25, 30, 35), (20, 25, 30), (15, 20, 25)])
            thickness = rng.choice([1, 1, 2])
            crack_opacity = rng.randint(50, 90)
            ops.append(("decor", _line(cx1, cy1, cx2, cy2, thickness, crack_col, crack_opacity), None))
            cur = nxt
            ang = seg_ang

    circuit_count = max(14, min(26, int(radius * 0.07)))
    dirs = [Vec2(1, 0), Vec2(0, 1), Vec2(1, 1), Vec2(1, -1)]
    for _ in range(circuit_count):
        for _attempt in range(10):
            ang = rng.uniform(0.0, math.tau)
            r = (rng.random() ** 0.7) * (radius * 0.72)
            start = Vec2(math.cos(ang) * r, math.sin(ang) * r)
            d = rng.choice(dirs).normalized()
            length = rng.uniform(radius * 0.18, radius * 0.42)
            end = start + d * length
            if start.length() <= radius * 0.88 and end.length() <= radius * 0.88:
                break
        else:
            continue

        x1, y1 = _iso(start, spec)
        x2, y2 = _iso(end, spec)
        col = rng.choice([(90, 200, 255), (200, 120, 255), (120, 240, 200)])
        thickness = rng.choice([2, 2, 3])
        base = rng.randint(42, 70)
        phase = rng.uniform(0.0, math.tau)
        ops.append(("pulse_line", _line(x1, y1, x2, y2, thickness, col, base), (base, phase)))

        for x, y in ((x1, y1), (x2, y2)):
            node_opacity = min(110, base + 45)
            node_phase = phase + rng.uniform(-0.8, 0.8)
            ops.append(("pulse_node", _circle(x, y, 3.2, col, node_opacity), (node_opacity, node_phase)))

    for i in range(10):
        a = (i / 10) * math.tau + (math.tau / 20)
        wp = Vec2(math.cos(a) * (radius * 0.985), math.sin(a) * (radius * 0.985))
        x, y = _iso(wp, spec)
        col = rng.choice([(170, 200, 255), (255, 120, 255), (120, 240, 200)])
        phase = rng.uniform(0.0, math.tau)
        ops.append(("pulse_node", _circle(x, y, 10.5, col, 26), (26, phase)))
        ops.append(("pulse_node", _circle(x, y, 4.0, (255, 255, 255), 120), (120, phase + 0.7)))

    return ops


def floor_ops_seeded(spec: ArenaSpec, seed: int) -> list:
    """Worker entry point. Same output as floor_ops(spec, random.Random(seed))."""
    return floor_ops(spec, random.Random(seed))


# ---------------------------------------------------------------- worker

class FloorPrefetcher:
    """Runs floor_ops_seeded for one ArenaSpec at a time in a spawn-context worker process.

    submit() never blocks. take() returns the worker's ops only if they are finished and succeeded.
    Otherwise it returns None and the caller builds the same ops in-process with seed_for(spec).
    A failed worker is dropped, and the next submit() starts a new one.

    ``executor_factory`` is injected by tests. It returns an object with submit() and shutdown().
    """

    def __init__(self, executor_factory=None):
        self._factory = executor_factory
        self._executor = None
        self._pending = None  # (spec, seed, future)
        self.last_error = None

    def _pool(self):
        if self._executor is None:
            if self._factory is not None:
                self._executor = self._factory()
            else:
                from concurrent.futures import ProcessPoolExecutor

                self._executor = ProcessPoolExecutor(
                    max_workers=1, mp_context=multiprocessing.get_context("spawn")
                )
        return self._executor

    def submit(self, spec: ArenaSpec, seed=None) -> bool:
        """Queue one arena. The seed is drawn from the OS when not given, so the module RNG is untouched."""
        if seed is None:
            seed = secrets.randbits(32)
        seed = int(seed)
        try:
            future = self._pool().submit(floor_ops_seeded, spec, seed)
        except Exception as exc:  # the pool cannot start or is already broken
            self._fail(exc)
            return False
        self._pending = (spec, seed, future)
        return True

    def seed_for(self, spec: ArenaSpec):
        """Seed of the queued request for this spec, or None."""
        pending = self._pending
        if pending is None or pending[0] != spec:
            return None
        return pending[1]

    def take(self, spec: ArenaSpec):
        """The worker's ops for spec if they are ready, else None. The request is consumed either way."""
        pending = self._pending
        if pending is None or pending[0] != spec:
            return None
        self._pending = None
        future = pending[2]
        if not future.done():
            future.cancel()
            return None
        try:
            return future.result()
        except Exception as exc:  # worker raised, or the pool broke
            self._fail(exc)
            return None

    def _fail(self, exc: Exception) -> None:
        self.last_error = exc
        executor = self._executor
        self._executor = None
        self._pending = None
        if executor is not None:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

    def close(self) -> None:
        self._fail(RuntimeError("closed"))
