"""Shared animation helpers: a damped spring, easing tweens, a one-shot timer and a capped pool.

Pure Python with no pyglet import, so the helpers run headless in tests and any module can use them.
Nothing here draws anything. Callers read the values and decide what to show, and they must honour
config.REDUCE_MOTION themselves (for example by snapping a spring to its target or skipping a tween).

Hot-path notes: Spring.update, tween, Timer.update and Pool.acquire/release create no lists, dicts or
helper objects per call. Pool creates its objects only up to ``cap`` and reuses them afterwards.
"""

import math

__all__ = [
    "clamp",
    "lerp",
    "tween",
    "EASINGS",
    "ease_linear",
    "ease_out_cubic",
    "ease_in_out_sine",
    "ease_out_back",
    "Spring",
    "Timer",
    "Pool",
]

# Springs use semi-implicit Euler in fixed sub-steps of at most 1/240 s, which stays stable for stiff
# springs at 60 fps and at lower frame rates. dt is capped so a long hitch cannot run many sub-steps;
# the cap only makes the motion lag behind real time, it never makes the spring blow up.
SPRING_SUBSTEP = 1.0 / 240.0
SPRING_MAX_DT = 0.25
DEFAULT_DAMPING_RATIO = 0.7

_NOTHING = object()


def clamp(x, lo, hi):
    """Return ``x`` limited to the closed range [lo, hi]."""
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def lerp(a, b, t):
    """Blend from ``a`` to ``b`` by ``t`` (not clamped). Exact at both ends: t=0 gives a, t=1 gives b."""
    return a * (1.0 - t) + b * t


# ---------------------------------------------------------------- easings
# Each maps t in [0, 1] to an eased fraction in [0, 1]. out_back overshoots above 1 before it returns.

_BACK_S = 1.70158
_BACK_S1 = _BACK_S + 1.0


def ease_linear(t):
    return t


def ease_out_cubic(t):
    u = 1.0 - t
    return 1.0 - u * u * u


def ease_in_out_sine(t):
    return 0.5 - 0.5 * math.cos(math.pi * t)


def ease_out_back(t):
    u = t - 1.0
    return 1.0 + _BACK_S1 * u * u * u + _BACK_S * u * u


EASINGS = {
    "linear": ease_linear,
    "out_cubic": ease_out_cubic,
    "in_out_sine": ease_in_out_sine,
    "out_back": ease_out_back,
}


def tween(a, b, t, ease="linear"):
    """Value between ``a`` and ``b`` at time ``t`` in [0, 1] under the named easing.

    ``ease`` is a key of EASINGS or any callable taking t. t is clamped, so t<=0 returns ``a`` and
    t>=1 returns ``b`` exactly, whatever the easing does.
    """
    if t <= 0.0:
        return a
    if t >= 1.0:
        return b
    if isinstance(ease, str):
        fn = EASINGS.get(ease)
        if fn is None:
            raise ValueError("unknown easing %r; choose from %s" % (ease, sorted(EASINGS)))
    else:
        fn = ease
    return lerp(a, b, fn(t))


# ---------------------------------------------------------------- spring

class Spring:
    """A damped spring (mass 1) that moves ``value`` toward ``target``.

    Acceleration = stiffness * (target - value) - damping * velocity. The default damping is a damping
    ratio of 0.7: a small overshoot, then a settle. Call ``update(dt)`` once per frame and read
    ``value``. Once the spring is within ``epsilon`` of its target and nearly still, it snaps onto the
    target with zero velocity and ``settled`` becomes True. After that, update() costs almost nothing.

    Set ``spring.target`` to retarget it. Use ``reset(value, target)`` to jump with no motion.
    """

    __slots__ = ("value", "velocity", "target", "stiffness", "damping", "epsilon")

    def __init__(self, value=0.0, target=None, stiffness=120.0, damping=None, epsilon=1e-3):
        stiffness = float(stiffness)
        if stiffness <= 0.0:
            raise ValueError("stiffness must be positive")
        self.stiffness = stiffness
        if damping is None:
            damping = 2.0 * DEFAULT_DAMPING_RATIO * math.sqrt(stiffness)
        self.damping = float(damping)
        self.epsilon = float(epsilon)
        self.value = 0.0
        self.velocity = 0.0
        self.target = 0.0
        self.reset(value, target)

    def reset(self, value=0.0, target=None):
        """Jump to ``value`` with zero velocity. ``target`` defaults to ``value`` (already settled)."""
        value = float(value)
        self.value = value
        self.target = value if target is None else float(target)
        self.velocity = 0.0

    @property
    def settled(self):
        """True when the spring sits exactly on its target and is not moving."""
        return self.velocity == 0.0 and self.value == self.target

    def update(self, dt):
        """Advance the spring by ``dt`` seconds and return the new value."""
        if dt <= 0.0:
            return self.value
        target = self.target
        x = self.value
        v = self.velocity
        if v == 0.0 and x == target:
            return x
        if dt > SPRING_MAX_DT:
            dt = SPRING_MAX_DT
        k = self.stiffness
        c = self.damping
        steps = max(1, math.ceil(dt / SPRING_SUBSTEP))
        h = dt / steps
        i = 0
        while i < steps:
            v += (k * (target - x) - c * v) * h
            x += v * h
            i += 1
        eps = self.epsilon
        if abs(x - target) < eps and abs(v) < eps:
            x = target
            v = 0.0
        self.value = x
        self.velocity = v
        return x


# ---------------------------------------------------------------- timer

class Timer:
    """A one-shot countdown. ``start()`` it, call ``update(dt)`` each frame, then read ``done``/``progress``.

    ``done`` is True once ``duration`` seconds have elapsed. A zero-length timer is done as soon as it
    is started. ``progress`` runs 0 to 1 and is 1 for a zero-length timer. Apply an easing yourself with
    ``tween(0, 1, timer.progress, ease)``.
    """

    __slots__ = ("duration", "elapsed", "running")

    def __init__(self, duration=0.0):
        self.duration = max(0.0, float(duration))
        self.elapsed = 0.0
        self.running = False

    def start(self, duration=None):
        """Begin counting from zero. Pass ``duration`` to change the length first."""
        if duration is not None:
            self.duration = max(0.0, float(duration))
        self.elapsed = 0.0
        self.running = True

    def update(self, dt):
        """Advance by ``dt`` seconds while running. Returns ``done``."""
        if self.running:
            if dt > 0.0:
                self.elapsed += dt
            if self.elapsed >= self.duration:
                self.elapsed = self.duration
                self.running = False
        return self.elapsed >= self.duration

    @property
    def done(self):
        return self.elapsed >= self.duration

    @property
    def progress(self):
        if self.duration <= 0.0:
            return 1.0
        return clamp(self.elapsed / self.duration, 0.0, 1.0)


# ---------------------------------------------------------------- pool

class Pool:
    """Reuses objects from ``factory`` and never holds more than ``cap`` of them.

    ``acquire()`` returns a free object, or creates one while under the cap. Once the cap is reached it
    returns None, so the caller skips the spawn rather than allocating. ``release(obj)`` returns an
    object to the free list. It raises ValueError for an object this pool did not hand out or one that
    is already free. An optional ``reset(obj)`` runs on release, so a reused object starts clean.
    Objects that are acquired and never released stay counted against the cap.
    """

    __slots__ = ("_factory", "_reset", "cap", "_free", "_busy", "_made")

    def __init__(self, factory, cap, reset=None):
        cap = int(cap)
        if cap < 1:
            raise ValueError("cap must be at least 1")
        self._factory = factory
        self._reset = reset
        self.cap = cap
        self._free = []
        self._busy = {}
        self._made = 0

    def acquire(self):
        """Return a free object, a new one under the cap, or None when the pool is exhausted."""
        if self._free:
            obj = self._free.pop()
        elif self._made < self.cap:
            obj = self._factory()
            self._made += 1
        else:
            return None
        self._busy[id(obj)] = obj
        return obj

    def release(self, obj):
        """Return ``obj`` to the pool so a later acquire() can reuse it."""
        if self._busy.pop(id(obj), _NOTHING) is not obj:
            raise ValueError("object was not acquired from this pool, or was already released")
        if self._reset is not None:
            self._reset(obj)
        self._free.append(obj)

    def release_all(self):
        """Return every acquired object to the free list, e.g. when a level ends."""
        reset = self._reset
        for obj in self._busy.values():
            if reset is not None:
                reset(obj)
            self._free.append(obj)
        self._busy.clear()

    @property
    def in_use(self):
        """Number of objects currently acquired."""
        return len(self._busy)

    @property
    def free_count(self):
        """Number of created objects waiting to be acquired."""
        return len(self._free)

    @property
    def created(self):
        """Number of objects the factory has made. Never exceeds ``cap``."""
        return self._made
