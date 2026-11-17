"""Pure enemy coordination steering on plain snapshots.

``steer_velocity`` is the one implementation of role steering. The serial path
(``enemy._apply_type_coordination``) and the batch path (``steer_chunk``, run in-process or in
a worker process from ``parallel.py``) both call it, so the same inputs give the same floats.

Nothing in this module touches Enemy objects, pyglet, the run RNG or global state. It imports
only ``utils`` and ``config``, so a spawned worker can import it without loading the game.
"""

import os
import struct
from dataclasses import dataclass

from utils import Vec2


# Per-behaviour coordination reach (world units) and forward-pressure floor.
COORD_RADIUS = {
    "ranged": 260.0,
    "spitter": 230.0,
    "engineer": 260.0,
    "tank": 190.0,
    "charger": 170.0,
    "chaser": 170.0,
    "swarm": 180.0,
    "flyer": 210.0,
    "bomber": 220.0,
}
MIN_FORWARD = {
    "ranged": -0.05,
    "spitter": 0.04,
    "engineer": -0.08,
    "tank": 0.06,
    "charger": 0.2,
    "chaser": 0.24,
    "swarm": 0.22,
    "flyer": 0.13,
    "bomber": 0.08,
}
ROLE_SLOT_WEIGHT = {
    "front_heavy": 0.62,
    "front_dive": 0.66,
    "front": 0.63,
    "flank": 0.7,
    "mid_lob": 0.74,
    "backline": 0.84,
    "support": 0.86,
}
ROLE_PLAYER_WEIGHT = {
    "front_heavy": 0.66,
    "front_dive": 0.7,
    "front": 0.62,
    "flank": 0.56,
    "mid_lob": 0.44,
    "backline": 0.36,
    "support": 0.24,
}


def coord_radius(key: str) -> float:
    """Neighbour reach used for cohesion and separation of a behaviour."""
    return COORD_RADIUS.get(key, 200.0)


def safe_dir(v: Vec2, fallback: Vec2 | None = None) -> Vec2:
    """Unit vector of ``v``; ``fallback`` (or +x) when ``v`` is (near) zero."""
    n = v.normalized()
    if n.length_squared() > 1e-9:
        return n
    if fallback is not None:
        fb = fallback.normalized()
        if fb.length_squared() > 1e-9:
            return fb
    return Vec2(1.0, 0.0)


def steer_velocity(key, pos, vel, speed, lock_t, slot_target, role, player_pos, prof, dt, nearby):
    """Steering for one unit. Returns ``(new_vel, new_forward_lock_t)``.

    ``nearby`` lists every other non-boss unit inside ``coord_radius(key)``, in enemy-list order,
    as ``(pos, same_behaviour)`` pairs. The caller filters by range, so this function never reads
    the rest of the room. Positions are read only, never written.
    """
    coord_r = coord_radius(key)

    to_player_vec = player_pos - pos
    to_player = safe_dir(to_player_vec)

    center = Vec2(pos.x, pos.y)
    for a_pos, _same in nearby:
        center = center + a_pos
    center = center / float(len(nearby) + 1)
    cohesion = safe_dir(center - pos, to_player)

    # Local separation keeps allies from stacking (stronger for same-type).
    separation = Vec2(0.0, 0.0)
    sep_count = 0
    for a_pos, same in nearby:
        dvec = pos - a_pos
        d = dvec.length()
        if d <= 1e-6:
            continue
        if d < coord_r * 0.45:
            wt = 1.0 if same else 0.55
            separation = separation + dvec.normalized() * (1.0 - d / (coord_r * 0.45)) * wt
            sep_count += 1
    if sep_count > 0:
        separation = safe_dir(separation / float(sep_count), to_player)

    to_slot = safe_dir(slot_target - pos, to_player)

    vel_dir = safe_dir(vel, to_player)

    # Keep role identity, but ensure forward combat pressure.
    min_forward = MIN_FORWARD.get(key, 0.08)
    min_forward *= float(prof["pressure_mult"])

    role_slot_weight = ROLE_SLOT_WEIGHT.get(role, 0.66)
    role_player_weight = ROLE_PLAYER_WEIGHT.get(role, 0.52)

    desired_dir = safe_dir(
        vel_dir * 0.45
        + to_slot * role_slot_weight
        + cohesion * 0.36
        + separation * 0.72
        + to_player * role_player_weight
    , to_player)

    # Forward-pressure hysteresis avoids frame-to-frame retreat jitter.
    fwd = desired_dir.dot(to_player)
    if fwd < min_forward:
        lock_t = min(0.35, lock_t + dt * 2.6)
    else:
        lock_t = max(0.0, lock_t - dt * 2.0)
    if lock_t > 0.0 and fwd < min_forward:
        desired_dir = safe_dir(desired_dir + to_player * (0.28 + lock_t * 0.9), to_player)

    desired_speed = speed * (1.02 if key in ("chaser", "swarm", "charger") else 0.98) * float(prof["pressure_mult"])
    desired_vel = desired_dir * desired_speed

    # Reynolds-style bounded steering: smooth and continuous velocity changes.
    steering = desired_vel - vel
    max_force = speed * 3.2 * float(prof["steer_mult"])
    max_step = max_force * dt
    sl = steering.length()
    if sl > max_step and sl > 1e-6:
        steering = steering * (max_step / sl)

    new_vel = vel + steering
    max_speed = speed * 1.28
    vl = new_vel.length()
    if vl > max_speed and vl > 1e-6:
        new_vel = new_vel * (max_speed / vl)
    return new_vel, lock_t


@dataclass(frozen=True)
class Snapshot:
    """One non-boss enemy at the moment of steering. Plain floats and strings only.

    ``tx``/``ty`` is the formation slot target and ``steer`` says whether coordination applies
    (a coordinated behaviour that is not holding a telegraph and whose frame is still live).
    """
    x: float
    y: float
    vx: float
    vy: float
    key: str
    speed: float
    seed: float
    lock_t: float
    tx: float
    ty: float
    role: str
    steer: bool


@dataclass(frozen=True)
class SteerBatch:
    """Everything one frame of steering needs. Picklable, so it can cross a process boundary."""
    snaps: tuple
    px: float
    py: float
    dt: float
    pressure_mult: float
    steer_mult: float


def steer_one(batch: SteerBatch, i: int, pts=None):
    """Steering result ``(vx, vy, lock_t)`` for snapshot ``i``, or None when it is not steered.

    ``pts`` optionally holds ``Vec2`` positions for every snapshot (built once per chunk).
    """
    snaps = batch.snaps
    s = snaps[i]
    if not s.steer:
        return None
    if pts is None:
        pts = [Vec2(o.x, o.y) for o in snaps]
    pos = pts[i]
    coord_r = coord_radius(s.key)
    r2 = coord_r * coord_r
    nearby = []
    for j, o in enumerate(snaps):
        if j == i:
            continue
        if (pts[j] - pos).length_squared() > r2:
            continue
        nearby.append((pts[j], o.key == s.key))
    prof = {"pressure_mult": batch.pressure_mult, "steer_mult": batch.steer_mult}
    new_vel, lock_t = steer_velocity(
        s.key,
        pos,
        Vec2(s.vx, s.vy),
        s.speed,
        s.lock_t,
        Vec2(s.tx, s.ty),
        s.role,
        Vec2(batch.px, batch.py),
        prof,
        batch.dt,
        nearby,
    )
    return (new_vel.x, new_vel.y, lock_t)


def steer_chunk(batch: SteerBatch, start: int, stop: int) -> list:
    """Steer snapshots ``[start, stop)``. This is the worker entry point for the process pool.

    Each result depends only on ``batch``, so any split into chunks gives the same list.
    """
    if batch.dt <= 0.0:
        return [None] * max(0, stop - start)
    pts = [Vec2(o.x, o.y) for o in batch.snaps]
    return [steer_one(batch, i, pts) for i in range(start, stop)]


# ---------------------------------------------------------------------------------------------
# Shared-memory batch layout, used by parallel.SteerBatcher's persistent worker pool. A frame is
# written once into float64 arrays, so nothing is pickled per frame.
#
#   input:  HEADER slots, then FIELDS slots per unit, in snapshot order.
#           header: [0] unit count, [1] player x, [2] player y, [3] dt, [4] pressure_mult,
#                   [5] steer_mult
#           unit:   x, y, vx, vy, key code, speed, lock_t, tx, ty, role code, steer (1.0 or 0.0)
#   output: OUT_FIELDS slots per unit: steered flag (1.0 or 0.0), vx, vy, lock_t
#
# Behavior and role names travel as codes into KEY_NAMES and ROLE_NAMES. ``Snapshot.seed`` is not
# packed: steer_velocity never reads it. A batch that uses a name outside these tables is not
# packable, and the caller steers it inline, so an unexpected name costs speed, never correctness.
# ---------------------------------------------------------------------------------------------

HEADER = 8
FIELDS = 11
OUT_FIELDS = 4
KEY_NAMES = ("", "chaser", "chase", "ranged", "swarm", "charger", "tank", "spitter", "flyer", "engineer", "bomber", "egg_sac")
ROLE_NAMES = ("front", "front_heavy", "front_dive", "flank", "mid_lob", "backline", "support")
_KEY_CODE = {name: i for i, name in enumerate(KEY_NAMES)}
_ROLE_CODE = {name: i for i, name in enumerate(ROLE_NAMES)}

# Pipe messages between the pool and its workers: raw bytes, never pickled objects.
MSG_QUIT = b""  # an empty message tells a worker to exit
MSG_ACK = b"k"  # a worker's reply once its range is written to the output array
RANGE_MSG = struct.Struct("<II")  # (start, stop) of the chunk a worker should steer


def packable(batch) -> bool:
    """True when every behavior and role name in ``batch`` has a code."""
    for s in batch.snaps:
        if s.key not in _KEY_CODE or s.role not in _ROLE_CODE:
            return False
    return True


def pack_batch(batch, inp) -> None:
    """Write ``batch`` into the float64 input array ``inp``.

    The caller checks ``packable`` and that the batch fits in ``inp``. Values are stored as doubles,
    so a worker reads back exactly the floats the batch holds.
    """
    snaps = batch.snaps
    n = len(snaps)
    if HEADER + n * FIELDS > len(inp):
        raise ValueError("batch of %d units does not fit the shared steering array" % n)
    inp[0] = n
    inp[1] = batch.px
    inp[2] = batch.py
    inp[3] = batch.dt
    inp[4] = batch.pressure_mult
    inp[5] = batch.steer_mult
    base = HEADER
    for s in snaps:
        inp[base] = s.x
        inp[base + 1] = s.y
        inp[base + 2] = s.vx
        inp[base + 3] = s.vy
        inp[base + 4] = _KEY_CODE[s.key]
        inp[base + 5] = s.speed
        inp[base + 6] = s.lock_t
        inp[base + 7] = s.tx
        inp[base + 8] = s.ty
        inp[base + 9] = _ROLE_CODE[s.role]
        inp[base + 10] = 1.0 if s.steer else 0.0
        base += FIELDS


def steer_packed(inp, out, start: int, stop: int) -> None:
    """Steer units ``[start, stop)`` of a packed batch and write the results into ``out``.

    This is the worker kernel. It applies the same arithmetic as ``steer_one`` and ``steer_chunk``
    to the same floats, so its results equal theirs. The neighbour test uses the raw coordinate
    difference, which is the expression ``(p_j - p_i).length_squared()`` evaluates, so the test
    is decided the same way.
    """
    n = int(inp[0])
    dt = inp[3]
    if dt <= 0.0:
        for i in range(start, stop):
            out[i * OUT_FIELDS] = 0.0
        return
    player = Vec2(inp[1], inp[2])
    prof = {"pressure_mult": inp[4], "steer_mult": inp[5]}
    xs = [inp[HEADER + j * FIELDS] for j in range(n)]
    ys = [inp[HEADER + j * FIELDS + 1] for j in range(n)]
    kc = [inp[HEADER + j * FIELDS + 4] for j in range(n)]
    for i in range(start, stop):
        base = HEADER + i * FIELDS
        o = i * OUT_FIELDS
        if inp[base + 10] == 0.0:
            out[o] = 0.0
            continue
        key = KEY_NAMES[int(kc[i])]
        role = ROLE_NAMES[int(inp[base + 9])]
        xi = xs[i]
        yi = ys[i]
        coord_r = coord_radius(key)
        r2 = coord_r * coord_r
        nearby = []
        for j in range(n):
            if j == i:
                continue
            dx = xs[j] - xi
            dy = ys[j] - yi
            if dx * dx + dy * dy > r2:
                continue
            nearby.append((Vec2(xs[j], ys[j]), kc[j] == kc[i]))
        new_vel, lock_t = steer_velocity(
            key,
            Vec2(xi, yi),
            Vec2(inp[base + 2], inp[base + 3]),
            inp[base + 5],
            inp[base + 6],
            Vec2(inp[base + 7], inp[base + 8]),
            role,
            player,
            prof,
            dt,
            nearby,
        )
        out[o] = 1.0
        out[o + 1] = new_vel.x
        out[o + 2] = new_vel.y
        out[o + 3] = lock_t


def unpack_results(out, start: int, stop: int) -> list:
    """Results for units ``[start, stop)`` read from the output array, in the ``steer_chunk`` format."""
    res = []
    for i in range(start, stop):
        o = i * OUT_FIELDS
        if out[o] == 0.0:
            res.append(None)
        else:
            res.append((out[o + 1], out[o + 2], out[o + 3]))
    return res


def steer_worker_main(conn, in_name: str, out_name: str) -> None:
    """Entry point of a persistent steering worker, started by parallel.py with the spawn method.

    The worker attaches to the pool's two shared arrays, then waits on ``conn``. For each
    ``RANGE_MSG`` it steers that range from the input array, writes the output array and answers
    ``MSG_ACK``. An empty message, or a closed pipe, ends the loop.
    """
    from multiprocessing import shared_memory

    in_sh = shared_memory.SharedMemory(name=in_name)
    out_sh = shared_memory.SharedMemory(name=out_name)
    if os.name == "posix":
        # Attaching registers the segment with this process's resource tracker, which would unlink
        # it when the worker exits. The parent owns the segments, so the registration is dropped.
        from multiprocessing import resource_tracker

        for sh in (in_sh, out_sh):
            resource_tracker.unregister(sh._name, "shared_memory")
    inp = out = None
    try:
        inp = memoryview(in_sh.buf).cast("d")
        out = memoryview(out_sh.buf).cast("d")
        while True:
            try:
                msg = conn.recv_bytes()
            except (EOFError, OSError):
                break
            if msg == MSG_QUIT:
                break
            start, stop = RANGE_MSG.unpack(msg)
            steer_packed(inp, out, start, stop)
            conn.send_bytes(MSG_ACK)
    finally:
        for view in (inp, out):
            if view is not None:
                view.release()
        in_sh.close()
        out_sh.close()
        conn.close()
