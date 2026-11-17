"""Regression tests for the perf pass: shake-stable depth buckets and projectile group creation."""

from config import SCREEN_H
from enemy import Enemy
from game import Game
from powerup import PowerUp
from projectile import Projectile
from states import GameStateName
from utils import Vec2, to_iso
from visuals import DEPTH_BUCKET, RenderHandle


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _bucket(sy):
    return int((SCREEN_H + 1000 - sy) / DEPTH_BUCKET)


class _MigrationCounter:
    """Counts pyglet batch migrations; every group change on a live shape triggers one."""

    def __init__(self, batch):
        self._batch = batch
        self.count = 0
        original = batch.migrate

        def counting(*args, **kwargs):
            self.count += 1
            return original(*args, **kwargs)

        batch.migrate = counting

    def stop(self):
        try:
            del self._batch.migrate
        except AttributeError:
            pass


def _enemy_grid():
    return [Enemy(pos=Vec2(float(i) * 9.0, float(i % 5) * 13.0), hp=30, speed=0.0, behavior="chaser") for i in range(40)]


SHAKES = [Vec2(0.0, s) for s in (-12.0, -7.0, -3.0, 3.0, 7.0, 12.0)] + [Vec2(9.0, 0.0), Vec2(-4.0, 11.0)]


def test_depth_bucket_ignores_screen_shake(g):
    _new_run(g)
    vis = g.visuals
    crossings = 0
    for e in _enemy_grid():
        vis.ensure_enemy(e)
        vis.sync_enemy(e, Vec2(0.0, 0.0))
        h = vis._enemy_handles[id(e)]
        _, rest_sy = to_iso(e.pos, Vec2(0.0, 0.0))
        rest_order = h._depth_order
        assert rest_order == _bucket(rest_sy), "at rest the depth key must match the original formula"
        for shake in SHAKES:
            vis.sync_enemy(e, shake)
            assert h._depth_order == rest_order, f"shake {shake.x},{shake.y} moved the depth bucket"
            _, shaken_sy = to_iso(e.pos, shake)
            if _bucket(shaken_sy) != rest_order:
                crossings += 1
    # The scenario must actually cross buckets under shake, or it would not catch the regression.
    assert crossings > 0, "shake never crossed a depth bucket in this scenario"
    print(f"[PASS] test_depth_bucket_ignores_screen_shake passed (depth stable under shake, {crossings} bucket crossings avoided)")


def test_depth_handles_do_not_migrate_while_shaking(g):
    _new_run(g)
    vis = g.visuals
    enemies = _enemy_grid()
    for e in enemies:
        vis.ensure_enemy(e)
        vis.sync_enemy(e, Vec2(0.0, 0.0))
    vis.sync_player(g.player, Vec2(0.0, 0.0), t=0.0, aim_dir=Vec2(1.0, 0.0))
    counter = _MigrationCounter(vis.batch)
    try:
        for shake in SHAKES:
            for e in enemies:
                vis.sync_enemy(e, shake)
            vis.sync_player(g.player, shake, t=0.0, aim_dir=Vec2(1.0, 0.0))
    finally:
        counter.stop()
    assert counter.count == 0, f"shaking migrated {counter.count} shapes between batch groups"
    print(f"[PASS] test_depth_handles_do_not_migrate_while_shaking passed (0 group migrations over {len(SHAKES)} shake frames)")


def test_set_depth_subtracts_shake_only_from_depth(g):
    _new_run(g)
    vis = g.visuals

    class _Stub:
        group = None

    for y in (120.0, 333.7, -41.2, 900.0):
        rest = RenderHandle(_Stub())
        moved = RenderHandle(_Stub())
        vis._set_depth(rest, y, Vec2(0.0, 0.0))
        vis._set_depth(moved, y + 11.0, Vec2(0.0, 11.0))
        assert rest._depth_order == moved._depth_order == _bucket(y), f"depth mismatch at y={y}"
    print("[PASS] test_set_depth_subtracts_shake_only_from_depth passed (depth key is the unshaken y)")


def test_projectile_shapes_are_created_in_projectile_group(g):
    _new_run(g)
    vis = g.visuals
    specs = [
        ("bullet", False, "player"), ("bullet", True, "player"), ("bullet", False, "enemy"),
        ("spread", False, "player"), ("spread", False, "enemy"),
        ("missile", False, "player"), ("missile", False, "enemy"),
        ("plasma", False, "player"), ("plasma", False, "enemy"),
        ("bomb", False, "player"), ("railgun", False, "player"), ("flak", False, "player"),
    ]
    projs = [
        Projectile(pos=Vec2(float(i) * 3.0, 0.0), vel=Vec2(300.0, 0.0), damage=10, ttl=1.0,
                   owner=owner, projectile_type=kind, is_crit=crit)
        for i, (kind, crit, owner) in enumerate(specs)
    ]
    counter = _MigrationCounter(vis.batch)
    try:
        for p in projs:
            vis.ensure_projectile(p)
    finally:
        counter.stop()
    assert counter.count == 0, f"creating projectiles migrated {counter.count} shapes after construction"
    shape_total = 0
    for p in projs:
        h = vis._proj_handles[id(p)]
        for o in h.objs:
            shape_total += 1
            assert o.group is vis._projectile_group, f"{p.projectile_type} shape not in the projectile group"
    print(f"[PASS] test_projectile_shapes_are_created_in_projectile_group passed ({shape_total} shapes born in group, 0 migrations)")


def test_projectile_visuals_still_follow_shake(g):
    _new_run(g)
    vis = g.visuals
    shake = Vec2(6.0, -9.0)
    for kind, crit in (("bullet", False), ("railgun", False), ("bullet", True)):
        p = Projectile(pos=Vec2(40.0, -20.0), vel=Vec2(200.0, 0.0), damage=10, projectile_type=kind, is_crit=crit)
        vis.ensure_projectile(p)
        vis.sync_projectile(p, shake)
        sx, sy = to_iso(p.pos, shake)
        h = vis._proj_handles[id(p)]
        sh = h.objs[-3]  # (sh, core, flare) or (trail, sh, core, flare)
        assert abs(sh.x - sx) < 1e-6 and abs(sh.y - sy) < 1e-6, f"{kind} projectile drawn off its shaken position"
    print("[PASS] test_projectile_visuals_still_follow_shake passed (drawn position still includes shake)")


def test_powerup_depth_ignores_shake(g):
    _new_run(g)
    vis = g.visuals
    pu = PowerUp(pos=Vec2(55.0, 35.0), kind="heal")
    vis.ensure_powerup(pu)
    vis.sync_powerup(pu, Vec2(0.0, 0.0))
    h = vis._power_handles[id(pu)]
    rest_order = h._depth_order
    counter = _MigrationCounter(vis.batch)
    try:
        for shake in SHAKES:
            vis.sync_powerup(pu, shake)
            assert h._depth_order == rest_order, "powerup depth moved with shake"
    finally:
        counter.stop()
    assert counter.count == 0, f"powerup shapes migrated {counter.count} times while shaking"
    print("[PASS] test_powerup_depth_ignores_shake passed (powerup bucket stable under shake)")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_depth_bucket_ignores_screen_shake(g)
        test_depth_handles_do_not_migrate_while_shaking(g)
        test_set_depth_subtracts_shake_only_from_depth(g)
        test_projectile_shapes_are_created_in_projectile_group(g)
        test_projectile_visuals_still_follow_shake(g)
        test_powerup_depth_ignores_shake(g)
    finally:
        g.close()
    print("\nALL SWARM PERF REGRESSION TESTS PASSED")


if __name__ == "__main__":
    run_all()
