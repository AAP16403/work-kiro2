"""Wave 4 shared animation helpers: anim.py.

Covers: a spring settling onto its target and then staying put, retargeting and reset, stability with
a large dt; tween endpoints for every easing and callable easings; out_back overshooting and returning
while the other easings stay inside [0, 1]; clamp and lerp; the Timer; Pool capping objects, reusing
released ones, rejecting foreign and double releases, and running its reset hook; and anim.py not
importing pyglet, checked both statically and in a fresh interpreter.

Run with the venv python: ``python test_w4_anim.py``. Also collectable by pytest.
"""

import ast
import os
import random
import subprocess
import sys
import traceback

from anim import EASINGS, Pool, Spring, Timer, clamp, lerp, tween

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAME = 1.0 / 60.0


def test_spring_settles_and_stops():
    s = Spring(0.0, target=10.0)
    peak = 0.0
    t = 0.0
    while t < 10.0 and not s.settled:
        s.update(FRAME)
        peak = max(peak, s.value)
        t += FRAME
    assert s.settled, "spring did not settle within 10 s"
    assert s.value == 10.0, s.value
    assert s.velocity == 0.0, s.velocity
    assert t < 4.0, "default spring took %.2f s to settle" % t
    # Default damping ratio 0.7 overshoots by about 4.6 percent, so it is underdamped but not wild.
    assert 10.3 < peak < 10.6, "overshoot peak %.4f" % peak
    for _ in range(300):
        assert s.update(FRAME) == 10.0
    assert s.value == 10.0 and s.velocity == 0.0


def test_spring_retarget_and_reset():
    s = Spring(0.0, target=5.0)
    s.reset(3.0)
    assert s.value == 3.0 and s.target == 3.0 and s.velocity == 0.0
    assert s.settled
    s.target = 5.0
    assert not s.settled
    first = s.update(FRAME)
    assert 3.0 < first < 5.0, first
    s.reset(7.0, 1.0)
    assert s.value == 7.0 and s.target == 1.0 and s.velocity == 0.0
    assert not s.settled


def test_spring_zero_dt_and_bad_stiffness():
    s = Spring(0.0, target=1.0)
    assert s.update(0.0) == 0.0
    assert s.update(-1.0) == 0.0
    assert s.velocity == 0.0
    try:
        Spring(0.0, 1.0, stiffness=0.0)
    except ValueError:
        pass
    else:
        raise AssertionError("stiffness 0 should raise ValueError")


def test_spring_stable_with_large_dt_and_stiff_spring():
    # A stiff spring stepped with a long hitch must stay finite and converge, not explode.
    s = Spring(0.0, target=100.0, stiffness=5000.0)
    for dt in (1.0 / 30.0, 1.0, 0.05, 2.0, FRAME):
        v = s.update(dt)
        assert v == v and abs(v) < 1e6, "spring diverged: %r" % v
    for _ in range(600):
        s.update(FRAME)
    assert s.settled and s.value == 100.0, (s.value, s.velocity)


def test_tween_endpoints_for_every_easing():
    for name in sorted(EASINGS):
        for a, b in ((0.0, 1.0), (2.0, 6.0), (-3.5, 9.25)):
            assert tween(a, b, 0.0, name) == a, name
            assert tween(a, b, 1.0, name) == b, name
            assert tween(a, b, -0.5, name) == a, name
            assert tween(a, b, 1.5, name) == b, name
    # Callable easings are accepted too.
    assert tween(2.0, 4.0, 0.0, lambda t: t * t) == 2.0
    assert tween(2.0, 4.0, 1.0, lambda t: t * t) == 4.0
    assert tween(2.0, 4.0, 0.5, lambda t: t * t) == 2.0 + 2.0 * 0.25


def test_tween_default_is_linear_and_unknown_name_raises():
    assert abs(tween(0.0, 10.0, 0.3) - 3.0) < 1e-12
    try:
        tween(0.0, 1.0, 0.5, "bounce")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown easing should raise ValueError")


def test_easing_raw_endpoints():
    for name, fn in EASINGS.items():
        assert abs(fn(0.0)) < 1e-12, (name, fn(0.0))
        assert abs(fn(1.0) - 1.0) < 1e-12, (name, fn(1.0))


def test_out_back_overshoots_and_returns():
    samples = [tween(0.0, 1.0, i / 1000.0, "out_back") for i in range(1001)]
    peak = max(samples)
    peak_at = samples.index(peak) / 1000.0
    assert peak > 1.05, "out_back peak %.4f does not overshoot" % peak
    assert 0.4 < peak_at < 0.8, "out_back peak at t=%.3f" % peak_at
    assert samples[-1] == 1.0, samples[-1]
    # After the peak it falls back and never dips below the target by much.
    after = samples[samples.index(peak):]
    assert all(after[i + 1] <= after[i] + 1e-12 for i in range(len(after) - 1)), "not monotone after peak"
    assert min(after) >= 1.0 - 1e-12, min(after)


def test_other_easings_stay_inside_unit_range():
    for name in ("linear", "out_cubic", "in_out_sine"):
        vals = [tween(0.0, 1.0, i / 500.0, name) for i in range(501)]
        assert min(vals) >= -1e-12 and max(vals) <= 1.0 + 1e-12, name
        assert all(vals[i + 1] >= vals[i] - 1e-12 for i in range(500)), name


def test_clamp_and_lerp():
    assert clamp(5, 0, 3) == 3
    assert clamp(-1, 0, 3) == 0
    assert clamp(2, 0, 3) == 2
    assert clamp(0, 0, 3) == 0 and clamp(3, 0, 3) == 3
    assert lerp(2.0, 4.0, 0.0) == 2.0
    assert lerp(2.0, 4.0, 1.0) == 4.0
    assert lerp(2.0, 4.0, 0.5) == 3.0
    assert lerp(0.1, 0.3, 1.0) == 0.3


def test_timer_counts_and_finishes():
    t = Timer(1.0)
    assert not t.running and not t.done and t.progress == 0.0
    assert t.update(0.5) is False, "a timer that was never started must not advance"
    assert t.elapsed == 0.0
    t.start()
    assert t.running
    assert t.update(0.4) is False
    assert abs(t.progress - 0.4) < 1e-12
    assert t.update(0.7) is True
    assert t.done and not t.running and t.progress == 1.0
    assert t.elapsed == 1.0
    assert t.update(5.0) is True
    assert t.elapsed == 1.0


def test_timer_restart_and_zero_length():
    t = Timer(0.5)
    t.start()
    t.update(0.5)
    assert t.done
    t.start(2.0)
    assert t.duration == 2.0 and t.elapsed == 0.0 and not t.done
    z = Timer(0.0)
    assert z.progress == 1.0
    z.start()
    assert z.update(FRAME) is True and z.done


def test_pool_never_exceeds_cap():
    made = []

    def factory():
        obj = {"id": len(made)}
        made.append(obj)
        return obj

    pool = Pool(factory, 3)
    got = [pool.acquire() for _ in range(3)]
    assert all(g is not None for g in got)
    assert pool.acquire() is None and pool.acquire() is None
    assert pool.created == 3 and len(made) == 3
    assert pool.in_use == 3 and pool.free_count == 0


def test_pool_reuses_released_objects():
    made = []

    def factory():
        obj = object()
        made.append(obj)
        return obj

    pool = Pool(factory, 2)
    a = pool.acquire()
    b = pool.acquire()
    assert pool.acquire() is None
    pool.release(a)
    again = pool.acquire()
    assert again is a, "released object was not reused"
    assert len(made) == 2, "factory ran again instead of reusing"
    pool.release(again)
    pool.release(b)
    assert pool.in_use == 0 and pool.free_count == 2


def test_pool_reset_hook_and_release_all():
    cleared = []

    def reset(o):
        cleared.append(id(o))
        o[0] = 0

    pool = Pool(lambda: [0], 4, reset=reset)
    objs = [pool.acquire() for _ in range(4)]
    for o in objs:
        o[0] = 99
    pool.release(objs[0])
    assert objs[0][0] == 0 and cleared == [id(objs[0])]
    pool.release_all()
    assert pool.in_use == 0 and pool.free_count == 4
    assert all(o[0] == 0 for o in objs)
    assert len(cleared) == 4
    created_before = pool.created
    for _ in range(4):
        assert pool.acquire() is not None
    assert pool.created == created_before, "release_all then acquire must not create objects"


def test_pool_rejects_foreign_and_double_release():
    pool = Pool(object, 2)
    mine = pool.acquire()
    try:
        pool.release(object())
    except ValueError:
        pass
    else:
        raise AssertionError("foreign object release should raise ValueError")
    try:
        pool.release(None)
    except ValueError:
        pass
    else:
        raise AssertionError("release(None) should raise ValueError")
    pool.release(mine)
    try:
        pool.release(mine)
    except ValueError:
        pass
    else:
        raise AssertionError("double release should raise ValueError")
    assert pool.in_use == 0 and pool.free_count == 1


def test_pool_random_churn_respects_cap_and_stops_allocating():
    rng = random.Random(4417)
    calls = [0]

    def factory():
        calls[0] += 1
        return [calls[0]]

    cap = 7
    pool = Pool(factory, cap)
    held = []
    for _ in range(5000):
        if held and (len(held) >= cap or rng.random() < 0.5):
            pool.release(held.pop(rng.randrange(len(held))))
        else:
            obj = pool.acquire()
            if obj is not None:
                held.append(obj)
        assert len(held) <= cap and pool.in_use == len(held)
        assert pool.created <= cap and calls[0] <= cap
        assert len({id(o) for o in held}) == len(held), "same object handed out twice"
    calls_after_churn = calls[0]
    for _ in range(10000):
        obj = pool.acquire()
        assert obj is not None or pool.in_use == cap
        if obj is not None:
            pool.release(obj)
    assert calls[0] == calls_after_churn, "pool allocated after warm-up"


def test_pool_rejects_bad_cap():
    try:
        Pool(object, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("cap 0 should raise ValueError")


def test_anim_does_not_import_pyglet():
    with open(os.path.join(ROOT, "anim.py"), "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert not name.split(".")[0].startswith("pyglet"), "anim.py imports %s" % name
    code = (
        "import sys, anim; "
        "bad = sorted(m for m in sys.modules if m == 'pyglet' or m.startswith('pyglet.')); "
        "print(','.join(bad))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "", "pyglet loaded by anim: %s" % out.stdout.strip()


def run_all():
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception:
            failed += 1
            print("FAIL %s" % name)
            traceback.print_exc()
        else:
            print("ok   %s" % name)
    print("%d passed, %d failed" % (len(tests) - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_all())
