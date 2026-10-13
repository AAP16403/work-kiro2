"""Wave 4 integration tests: batched steering order, and a batched replay repeated in a second process.

1. The formation order of units that have no pinned bias comes from their per-run spawn index, not from
   their addresses. The same seeded crowd gives the same slots and flank sides after the heap has moved.
2. A replay recorded with the batch path active (PARALLEL_STEER_ENABLED, with its worker pool) in one
   process reproduces every state hash when it is replayed in a second process.

Pool workers start with spawn and re-import this file as __mp_main__, so the work runs from the
__main__ guard. Each process here is started with PLOUTO_SILENT=1, so no sound reaches the speakers.
"""

import json
import math
import os
import random
import subprocess
import sys
import tempfile
from types import SimpleNamespace

os.environ.setdefault("PLOUTO_SILENT", "1")

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config  # noqa: E402
import enemy as E  # noqa: E402
from enemy import Enemy  # noqa: E402
from utils import Vec2  # noqa: E402

KEYS = ("chaser", "charger", "flyer", "tank", "swarm", "bomber", "ranged", "spitter", "engineer")
PLAYER_POS = Vec2(60.0, -40.0)
PLAYER_VEL = Vec2(20.0, 10.0)
STEPS = 600
SEED = 4242
CROWD = 20  # enemies seeded at the start of each run, so the batch path (16 or more live) runs from step 0


def _crowd(seed, n):
    """A seeded crowd with no pinned formation bias, so the ordering key is the one the game uses."""
    rng = random.Random(seed)
    st = SimpleNamespace(enemies=[], time=0.0, difficulty="normal", rng=rng, wave=15)
    for i in range(n):
        a = rng.uniform(0.0, math.tau)
        r = 480.0 * math.sqrt(rng.random())
        e = Enemy(
            pos=Vec2(r * math.cos(a), r * math.sin(a)),
            hp=20,
            speed=rng.uniform(60.0, 130.0),
            behavior=KEYS[i % len(KEYS)],
            seed=rng.uniform(0.0, math.tau),
        )
        e.vel = Vec2(rng.uniform(-90.0, 90.0), rng.uniform(-90.0, 90.0))
        st.enemies.append(e)
    return st


def _formation_rows(seed, n, shift):
    """Formation of one seeded crowd, as rows keyed by spawn index. ``shift`` live objects are allocated
    first, so the crowd sits at different addresses; the rows must not change with them."""
    junk = [object() for _ in range(shift)]  # noqa: F841 - kept alive so the crowd lands at other addresses
    st = _crowd(seed, n)
    old_keys = [id(e) % 997 for e in st.enemies]
    formation = E._build_role_formation(st, PLAYER_POS, PLAYER_VEL)
    rows = []
    for e in st.enemies:
        target = formation["slot_targets"].get(id(e))
        tx, ty = (None, None) if target is None else (round(target.x, 6), round(target.y, 6))
        rows.append((int(e.spawn_index), formation["roles"].get(id(e)), tx, ty, round(float(e.ai["formation_bias"]), 9)))
    rows.sort()
    return rows, old_keys


def test_formation_order_ignores_object_addresses():
    rows_a, keys_a = _formation_rows(seed=7, n=30, shift=0)
    rows_b, keys_b = _formation_rows(seed=7, n=30, shift=4001)
    assert keys_a != keys_b, "the two crowds must sit at different addresses for the check to mean anything"
    assert rows_a == rows_b, "formation order changed with object addresses"
    assert [r[0] for r in rows_a] == list(range(30)), "spawn indices are not 0..n-1 in spawn order"
    biases = [r[4] for r in rows_a]
    assert len(set(biases)) == len(biases), "the 7919 step should give every one of the first 997 spawns its own key"
    assert sum(1 for b in biases if b < 0.5) not in (0, len(biases)), "flank sides must not all fall on one side"
    print("[PASS] test_formation_order_ignores_object_addresses passed "
          "(30 units at 2 address layouts, slots and biases identical)")


def test_spawn_index_restarts_for_each_run():
    st_a = _crowd(seed=11, n=5)
    E._build_role_formation(st_a, PLAYER_POS, PLAYER_VEL)
    st_a.time = 1.0
    st_a.enemies.append(Enemy(pos=Vec2(0.0, 0.0), hp=5, speed=50.0, behavior="chaser"))
    E._build_role_formation(st_a, PLAYER_POS, PLAYER_VEL)
    assert st_a.enemies[-1].spawn_index == 5, "a later spawn continues the run's count"
    st_b = _crowd(seed=11, n=5)
    E._build_role_formation(st_b, PLAYER_POS, PLAYER_VEL)
    assert st_b.enemies[0].spawn_index == 0, "a new run starts again from index 0"
    print("[PASS] test_spawn_index_restarts_for_each_run passed (count lives on the run's state)")


def _script(index, game):
    """The fixed input script of test_w3_replay: movement keys in turn, boost now and then, held fire."""
    import pyglet
    k = pyglet.window.key
    phase = (index // 45) % 4
    game.keys[k.W] = phase == 0
    game.keys[k.D] = phase == 1
    game.keys[k.S] = phase == 2
    game.keys[k.A] = phase == 3
    game.keys[k.LSHIFT] = (index % 120) < 20
    game.mouse_down = True
    game.mouse_xy = (640 + 200 * math.cos(index * 0.05), 360 + 200 * math.sin(index * 0.05))
    if index in (150, 400):
        game._dash()


def _open_game(tmp):
    """A game whose save files all live in ``tmp``."""
    import replay
    import score as score_mod
    from game import Game

    score_mod.HIGH_SCORE_FILE = os.path.join(tmp, "board.json")
    replay.DEFAULT_PATH = os.path.join(tmp, "last_run.json")
    g = Game()
    g.set_visible(False)
    g.progress_path = os.path.join(tmp, "progress.json")
    return g


def _seed_crowd(game):
    """Add CROWD enemies on a ring, from the run's own RNG. Record and replay make the same draws."""
    s = game.state
    for i in range(CROWD):
        a = s.rng.uniform(0.0, math.tau)
        r = s.rng.uniform(260.0, 420.0)
        s.enemies.append(Enemy(
            pos=Vec2(r * math.cos(a), r * math.sin(a)),
            hp=20,
            speed=s.rng.uniform(60.0, 130.0),
            behavior=KEYS[i % len(KEYS)],
            max_hp=20,
        ))


def _with_crowd(start_run):
    """``start_run`` followed by the seeded crowd. Both record_scripted and replay.replay start a run through
    replay.start_run, so a recording and its replay get the same setup, and no setup is stored in the file."""
    def start(game, seed, difficulty, mutators=()):
        start_run(game, seed, difficulty, mutators)
        _seed_crowd(game)
    return start


def _child_record(path):
    """Play and record a run with batch steering on; write the recording to ``path``."""
    import parallel
    import replay

    config.PARALLEL_STEER_ENABLED = True  # the default is serial; this child tests the batch path
    tmp = tempfile.mkdtemp(prefix="w4_integrate_rec_")
    g = _open_game(tmp)
    original = replay.start_run
    replay.start_run = _with_crowd(original)
    try:
        rec = replay.record_scripted(g, SEED, "normal", (), STEPS, _script)
    finally:
        replay.start_run = original
    try:
        if not replay.save_recording(rec, path):
            raise SystemExit("could not save the recording")
        batcher = parallel.active_batcher()
        frames = batcher.frames if batcher is not None else 0
        print(json.dumps({"steps": len(rec.steps), "batched_frames": frames,
                          "fallbacks": getattr(batcher, "fallbacks", 0), "workers": getattr(batcher, "workers", 0)}))
    finally:
        g.close()
        parallel.close_batcher()


def _child_replay(path):
    """Load the recording from ``path`` and replay it on a fresh game in this process."""
    import parallel
    import replay

    config.PARALLEL_STEER_ENABLED = True  # the recording was made on the batch path
    tmp = tempfile.mkdtemp(prefix="w4_integrate_play_")
    g = _open_game(tmp)
    original = replay.start_run
    replay.start_run = _with_crowd(original)
    try:
        rec = replay.load_recording(path)
        result = replay.replay(g, rec)
    finally:
        replay.start_run = original
    try:
        batcher = parallel.active_batcher()
        print(json.dumps({"ok": bool(result.ok), "first_mismatch": result.first_mismatch,
                          "steps": len(rec.steps), "hashes_equal": result.hashes == rec.hashes,
                          "batched_frames": batcher.frames if batcher is not None else 0}))
    finally:
        g.close()
        parallel.close_batcher()


def _run_child(mode, path):
    res = subprocess.run(
        [sys.executable, os.path.abspath(__file__), mode, path],
        capture_output=True, text=True, timeout=540, cwd=ROOT,
        env=dict(os.environ, PLOUTO_SILENT="1"),
    )
    assert res.returncode == 0, "%s child failed:\n%s" % (mode, (res.stdout + res.stderr)[-2000:])
    last = [line for line in res.stdout.splitlines() if line.startswith("{")][-1]
    return json.loads(last)


def test_batched_replay_repeats_in_a_second_process():
    """A recording made with batch steering on replays with every state hash equal, in another process."""
    assert config.PARALLEL_STEER_ENABLED is True, "the shipped default is batched (user-enabled); the child processes force the flag on either way"
    fd, path = tempfile.mkstemp(suffix=".json", prefix="w4_integrate_")
    os.close(fd)
    try:
        recorded = _run_child("record", path)
        assert recorded["batched_frames"] > 0, "the recorded run never reached the batch path: %r" % (recorded,)
        assert recorded["fallbacks"] == 0, recorded
        played = _run_child("replay", path)
    finally:
        os.remove(path)
    assert played["ok"] and played["first_mismatch"] is None, played
    assert played["hashes_equal"], played
    assert played["batched_frames"] > 0, played
    print("[PASS] test_batched_replay_repeats_in_a_second_process passed (%d steps, %d batched frames, "
          "%d workers, every state hash equal in a second process)" % (
              played["steps"], recorded["batched_frames"], recorded["workers"]))


def run_all():
    test_formation_order_ignores_object_addresses()
    test_spawn_index_restarts_for_each_run()
    test_batched_replay_repeats_in_a_second_process()
    print("\nALL W4 INTEGRATE TESTS PASSED")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "record":
        _child_record(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "replay":
        _child_replay(sys.argv[2])
    else:
        run_all()
