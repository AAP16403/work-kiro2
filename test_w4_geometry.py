"""Wave 4 geometry tests: arena floor geometry built by geometry_build.py.

What is checked:
1. Vertex data. Every shape a Room creates (its constructor and every rebuild) matches the base-commit
   map.py (ef93c82), read with `git show`. The comparison covers each shape's kind, coordinates, colour,
   thickness and opacity, the creation order, and the Room lists that drive the animation. It runs for all
   four map types at the window sizes the game can use, for several seeds. The arena depends only on the
   map type and the window size (game.py sets ROOM_RADIUS from the window), not on the wave, so each wave
   from the brief gets the same arena set.
2. Worker. A spawn-context worker returns the same ops as the in-process build for the same seed. The result
   matches the base code run under random.seed(seed).
3. Fallback. When the worker fails, or is not ready, or cannot be submitted to, the rebuild still produces the
   same geometry as the in-process build.
4. The default is off. With ARENA_GEOMETRY_WORKER unset, no worker process starts.

Shapes are replaced by recording fakes, so the comparison does not depend on the GL state.
Windows note: the worker uses the spawn start method, so the child re-imports this file as __mp_main__.
Top-level code therefore stays light, and map/pyglet are imported inside the test functions.
"""

import concurrent.futures
import os
import random
import subprocess
import sys
import time
import types

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config  # noqa: E402
import geometry_build  # noqa: E402
import utils  # noqa: E402

BASE_COMMIT = "ef93c82"
MAP_TYPES = (config.MAP_CIRCLE, config.MAP_DONUT, config.MAP_CROSS, config.MAP_DIAMOND)
WINDOWS = ((980, 620), (1280, 800), (1920, 1080))
SEEDS = (1, 5, 1234567)
WAVES = (1, 8, 15, 22, 29)

ROOM_ATTRS = (
    "_bg_a", "_bg_b", "_ambient", "_vignette", "_scanlines", "_bg_grid",
    "_floor_polys", "_edge", "_intensity_overlays", "_grid", "_boundary",
    "_pulse_lines", "_pulse_nodes", "_decor",
)
FLOOR_ATTRS = (
    "_floor_polys", "_edge", "_intensity_overlays", "_grid", "_boundary",
    "_pulse_lines", "_pulse_nodes", "_decor",
)


# ---------------------------------------------------------------- recording fakes

_REGISTRY: list = []  # every fake shape, in creation order


class _FakeShape:
    def __init__(self, kind, args, color, thickness):
        self.kind = kind
        self.args = tuple(args)
        self.color = color
        self.thickness = thickness
        self.opacity = 255
        self.deleted = False

    def delete(self):
        self.deleted = True


def _record(kind, args, color, thickness=None):
    shape = _FakeShape(kind, args, color, thickness)
    _REGISTRY.append(shape)
    return shape


class _FakeShapes:
    @staticmethod
    def Circle(x, y, radius, color=None, batch=None, group=None):
        return _record("circle", (x, y, radius), color)

    @staticmethod
    def Line(x1, y1, x2, y2, thickness=1, color=None, batch=None, group=None):
        return _record("line", (x1, y1, x2, y2), color, thickness)

    @staticmethod
    def Polygon(*coords, color=None, batch=None, group=None):
        return _record("polygon", coords, color)

    @staticmethod
    def Rectangle(x, y, width, height, color=None, batch=None, group=None):
        return _record("rect", (x, y, width, height), color)


class _FakeGroup:
    def __init__(self, order=0):
        self.order = order


def _ser(value):
    """A comparable form of a Room attribute. Shapes are serialised with their final state."""
    if isinstance(value, _FakeShape):
        return ("shape", value.kind, value.args, value.color, value.thickness, value.opacity, value.deleted)
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, tuple(_ser(v) for v in value))
    return value


def _state(room, attrs):
    return {name: _ser(getattr(room, name, None)) for name in attrs}


def _trace():
    return [_ser(s) for s in _REGISTRY]


# ---------------------------------------------------------------- loading the two implementations

_BASE_MOD = None


def _base_map():
    """The base-commit map.py, executed as its own module. Its shapes are replaced by the fakes."""
    global _BASE_MOD
    if _BASE_MOD is None:
        src = subprocess.run(
            ["git", "show", f"{BASE_COMMIT}:map.py"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
        mod = types.ModuleType("map_base_ef93c82")
        exec(compile(src, "map_base_ef93c82.py", "exec"), mod.__dict__)
        _BASE_MOD = mod
    return _BASE_MOD


def _patched(mod):
    """Swap a map module's shapes and Group for the fakes. Returns a restore callable."""
    saved = (mod.shapes, mod.Group)
    mod.shapes = _FakeShapes
    mod.Group = _FakeGroup

    def restore():
        mod.shapes, mod.Group = saved

    return restore


class _RadiusPinned:
    """Pin config.ROOM_RADIUS to the game's formula for one window, and restore it on exit."""

    def __init__(self, width, height):
        self.radius = utils.compute_room_radius(width, height, margin=float(getattr(config, "ARENA_MARGIN", 0.92)))

    def __enter__(self):
        self._saved = config.ROOM_RADIUS
        config.ROOM_RADIUS = self.radius
        return self

    def __exit__(self, *exc):
        config.ROOM_RADIUS = self._saved


class _FlagSet:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self._had = hasattr(config, "ARENA_GEOMETRY_WORKER")
        self._saved = getattr(config, "ARENA_GEOMETRY_WORKER", None)
        config.ARENA_GEOMETRY_WORKER = self.value
        return self

    def __exit__(self, *exc):
        if self._had:
            config.ARENA_GEOMETRY_WORKER = self._saved
        elif hasattr(config, "ARENA_GEOMETRY_WORKER"):
            del config.ARENA_GEOMETRY_WORKER


def _build_both(map_type, width, height, seed):
    """Constructor and one rebuild, base and new, each seeded identically. Returns the two sides' data."""
    import map as new_map  # noqa: WPS433 (imported here, see module docstring)

    base_mod = _base_map()
    out = {}
    for label, mod in (("base", base_mod), ("new", new_map)):
        restore = _patched(mod)
        try:
            with _RadiusPinned(width, height):
                random.seed(seed)
                _REGISTRY.clear()
                room = mod.Room(None, width, height, map_type=map_type)
                ctor = (_state(room, ROOM_ATTRS), _trace())
                other = config.MAP_DIAMOND if map_type != config.MAP_DIAMOND else config.MAP_CIRCLE
                random.seed(seed + 1)
                _REGISTRY.clear()
                room.rebuild(map_type=other)
                rebuild = (_state(room, FLOOR_ATTRS), _trace())
                random.seed(seed + 2)
                _REGISTRY.clear()
                room.rebuild(map_type=map_type)
                rebuild2 = (_state(room, FLOOR_ATTRS), _trace())
            out[label] = (ctor, rebuild, rebuild2)
        finally:
            restore()
    return out


# ---------------------------------------------------------------- tests

def test_vertex_data_identical_to_base():
    """Every arena the game can build, against the base code. The arena depends on the map type and the
    window size only, so the same set covers waves 1, 8, 15, 22 and 29."""
    checked = 0
    for width, height in WINDOWS:
        for map_type in MAP_TYPES:
            for seed in SEEDS:
                got = _build_both(map_type, width, height, seed)
                for i, label in enumerate(("constructor", "rebuild to other map", "rebuild back")):
                    base_part, new_part = got["base"][i], got["new"][i]
                    assert base_part[0] == new_part[0], (
                        f"{map_type} {width}x{height} seed {seed}: {label} room lists differ"
                    )
                    assert base_part[1] == new_part[1], (
                        f"{map_type} {width}x{height} seed {seed}: {label} creation trace differs"
                    )
                checked += 1
    assert checked == len(WINDOWS) * len(MAP_TYPES) * len(SEEDS)
    print(f"[PASS] vertex data identical to {BASE_COMMIT} for {checked} arena/seed cases "
          f"(each with constructor and two rebuilds)")


def test_default_path_draws_module_rng_like_base():
    """Without the worker, a rebuild consumes the module RNG exactly as the base code did."""
    import map as new_map

    with _FlagSet(False):
        restore = _patched(new_map)
        try:
            random.seed(99)
            with _RadiusPinned(980, 620):
                room = new_map.Room(None, 980, 620, map_type=config.MAP_CIRCLE)
                after_ctor = random.getstate()
            random.seed(99)
            base = _base_map()
            restore_base = _patched(base)
            try:
                with _RadiusPinned(980, 620):
                    base_room = base.Room(None, 980, 620, map_type=config.MAP_CIRCLE)
                    base_after_ctor = random.getstate()
            finally:
                restore_base()
            assert after_ctor == base_after_ctor, "constructor leaves the module RNG in a different state"
            assert room._prefetcher is None, "a worker object was created with the flag off"
            assert room.prefetch_arena() is False, "prefetch must do nothing with the flag off"
            assert room._prefetcher is None
        finally:
            restore()
    print("[PASS] default path uses the module RNG exactly as the base code, and starts no worker")


def test_worker_result_equals_in_process():
    import map as new_map

    spec = _spec(config.MAP_CROSS, 1280, 800)
    seed = 4242
    prefetcher = geometry_build.FloorPrefetcher()
    try:
        assert prefetcher.submit(spec, seed=seed), "submit should queue the request"
        worker_ops = prefetcher._pending[2].result(timeout=120)  # test-only: wait for the worker
        in_process = geometry_build.floor_ops(spec, random.Random(seed))
        assert worker_ops == in_process, "worker ops differ from the in-process ops for the same seed"
        assert prefetcher.take(spec) == in_process
        assert prefetcher.seed_for(spec) is None, "take() must consume the request"
    finally:
        prefetcher.close()

    # Floor built from those ops, through the real rebuild path, equals the base code under the same seed.
    restore = _patched(new_map)
    try:
        with _RadiusPinned(1280, 800):
            room = new_map.Room(None, 1280, 800, map_type=config.MAP_CROSS)
            room._rebuild_ops = lambda: in_process
            _REGISTRY.clear()
            room.rebuild()
            got = _state(room, FLOOR_ATTRS)
    finally:
        restore()
    assert got == _base_floor_state(config.MAP_CROSS, 1280, 800, seed), "worker-seed floor differs from base code"
    print("[PASS] worker result equals in-process result, and the floor matches the base code under the same seed")


def test_real_worker_rebuild_uses_result_and_matches_base():
    import map as new_map

    seed = 777
    with _FlagSet(True), _RadiusPinned(980, 620):
        restore = _patched(new_map)
        try:
            room = new_map.Room(None, 980, 620, map_type=config.MAP_DONUT)
            assert room.prefetch_arena() is True
            spec = room._arena_spec()
            seed_used = room._prefetcher.seed_for(spec)
            assert seed_used is not None
            room._prefetcher._pending[2].result(timeout=120)  # test-only: wait for the worker to finish
            _REGISTRY.clear()
            room.rebuild()
            assert room._prefetcher is not None and room._prefetcher.seed_for(spec) is None, "request not consumed"
            worker_state = _state(room, FLOOR_ATTRS)
            worker_trace = _trace()
            room._prefetcher.close()
        finally:
            restore()
    base = _base_map()
    restore_base = _patched(base)
    try:
        with _RadiusPinned(980, 620):
            random.seed(seed_used)
            base_room = base.Room(None, 980, 620, map_type=config.MAP_DONUT)
            random.seed(seed_used)
            _REGISTRY.clear()
            base_room._rebuild_floor()
            base_state = _state(base_room, FLOOR_ATTRS)
            base_trace = _trace()
    finally:
        restore_base()
    assert worker_state == base_state, "worker-built floor differs from base code under the same seed"
    assert worker_trace == base_trace, "worker-built creation order differs from base code"
    print("[PASS] real spawn worker: rebuild used the worker result and matches the base code")


class _FailingExecutor:
    """Returns futures that fail with the given error, like a worker that raised."""

    def __init__(self, error):
        self.error = error
        self.shut = False

    def submit(self, fn, *args, **kwargs):
        future = concurrent.futures.Future()
        future.set_exception(self.error)
        return future

    def shutdown(self, wait=True, cancel_futures=False):
        self.shut = True


class _NeverReadyExecutor:
    def __init__(self):
        self.futures = []
        self.shut = False

    def submit(self, fn, *args, **kwargs):
        future = concurrent.futures.Future()  # never set: the worker has not finished
        self.futures.append(future)
        return future

    def shutdown(self, wait=True, cancel_futures=False):
        self.shut = True


class _ClosedExecutor:
    """A real pool that has been shut down, so submit() raises RuntimeError."""

    def __init__(self):
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.pool.shutdown(wait=True)

    def submit(self, fn, *args, **kwargs):
        return self.pool.submit(fn, *args, **kwargs)

    def shutdown(self, wait=True, cancel_futures=False):
        pass


def _fallback_rebuild(executor):
    """Queue a request through `executor`, rebuild, and return (queued, seed, floor state, trace, pending left)."""
    import map as new_map

    with _FlagSet(True), _RadiusPinned(980, 620):
        restore = _patched(new_map)
        try:
            room = new_map.Room(None, 980, 620, map_type=config.MAP_DIAMOND)
            room._prefetcher = geometry_build.FloorPrefetcher(executor_factory=lambda: executor)
            queued = room.prefetch_arena()
            spec = room._arena_spec()
            seed = room._prefetcher.seed_for(spec)
            _REGISTRY.clear()
            room.rebuild()
            state = _state(room, FLOOR_ATTRS)
            trace = _trace()
            pending_left = room._prefetcher.seed_for(spec)
        finally:
            restore()
    return queued, seed, state, trace, pending_left


def test_fallback_when_worker_future_fails():
    executor = _FailingExecutor(RuntimeError("simulated worker crash"))
    queued, seed, state, _trace_got, pending_left = _fallback_rebuild(executor)
    assert queued is True and seed is not None
    assert pending_left is None, "the rebuild must consume the request"
    assert executor.shut, "a failed worker must be shut down"
    assert state == _base_floor_state(config.MAP_DIAMOND, 980, 620, seed), (
        "fallback floor differs from base code under the request seed"
    )
    print("[PASS] worker future failed: rebuild fell back in-process and matches the base code")


def test_fallback_when_worker_not_ready():
    executor = _NeverReadyExecutor()
    queued, seed, state, _trace_got, pending_left = _fallback_rebuild(executor)
    assert queued is True and seed is not None
    assert pending_left is None, "the rebuild must consume the request"
    assert state == _base_floor_state(config.MAP_DIAMOND, 980, 620, seed), (
        "not-ready fallback floor differs from base code under the request seed"
    )
    print("[PASS] worker not ready: rebuild did not wait and matches the base code")


def test_fallback_when_pool_cannot_submit():
    queued_executor = _ClosedExecutor()
    import map as new_map

    with _FlagSet(True), _RadiusPinned(980, 620):
        restore = _patched(new_map)
        try:
            room = new_map.Room(None, 980, 620, map_type=config.MAP_DIAMOND)
            room._prefetcher = geometry_build.FloorPrefetcher(executor_factory=lambda: queued_executor)
            queued = room.prefetch_arena()
            assert queued is False, "a closed pool must refuse the request"
            assert room._prefetcher.last_error is not None
            random.seed(31)
            _REGISTRY.clear()
            room.rebuild()  # no request queued: the module-RNG path
            got_state = _state(room, FLOOR_ATTRS)
        finally:
            restore()
    base = _base_map()
    restore_base = _patched(base)
    try:
        with _RadiusPinned(980, 620):
            random.seed(31)
            base_room = base.Room(None, 980, 620, map_type=config.MAP_DIAMOND)
            random.seed(31)
            base_room._rebuild_floor()
            base_state = _state(base_room, FLOOR_ATTRS)
    finally:
        restore_base()
    assert got_state == base_state, "fallback after a refused submit differs from base code"
    print("[PASS] pool refused the request: rebuild fell back and matches the base code")


def _base_floor_state(map_type, width, height, seed):
    """Floor state of the base code: constructor, then _rebuild_floor() under random.seed(seed)."""
    base = _base_map()
    restore = _patched(base)
    try:
        with _RadiusPinned(width, height):
            random.seed(seed)
            room = base.Room(None, width, height, map_type=map_type)
            random.seed(seed)
            _REGISTRY.clear()
            room._rebuild_floor()
            return _state(room, FLOOR_ATTRS)
    finally:
        restore()


def _spec(map_type, width, height):
    """The ArenaSpec a Room with these settings would build (the same fields as Room._arena_spec)."""
    return geometry_build.ArenaSpec(
        map_type=map_type,
        radius=float(utils.compute_room_radius(width, height, margin=float(getattr(config, "ARENA_MARGIN", 0.92)))),
        width=width,
        height=height,
        view_w=utils.VIEW_W,
        view_h=utils.VIEW_H,
        iso_x=utils.ISO_SCALE_X,
        iso_y=utils.ISO_SCALE_Y,
        floor_main=config.FLOOR_MAIN,
        floor_edge=config.FLOOR_EDGE,
        floor_grid=config.FLOOR_GRID,
    )


# ---------------------------------------------------------------- runner

def _run_all():
    import map as _  # noqa: F401  (import once in the parent, so pyglet loads before the tests)

    tests = [
        test_vertex_data_identical_to_base,
        test_default_path_draws_module_rng_like_base,
        test_worker_result_equals_in_process,
        test_real_worker_rebuild_uses_result_and_matches_base,
        test_fallback_when_worker_future_fails,
        test_fallback_when_worker_not_ready,
        test_fallback_when_pool_cannot_submit,
    ]
    failed = 0
    for test in tests:
        start = time.perf_counter()
        try:
            test()
        except Exception as exc:  # report every failure, not just the first
            failed += 1
            print(f"[FAIL] {test.__name__}: {exc!r}")
        else:
            print(f"       ({test.__name__} took {time.perf_counter() - start:.2f}s)")
    if failed:
        print(f"\n{failed} of {len(tests)} geometry tests FAILED")
        return 1
    print(f"\nALL {len(tests)} WAVE 4 GEOMETRY TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(_run_all())
