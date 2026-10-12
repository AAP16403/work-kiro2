"""Wave-2 skin tests: the selected skin drives the run's character, player shots, trails and dash afterimage.

The default skin is wave 1's look: its palette is player_art.DEFAULT_PALETTE, its shots keep their
weapon colours, and the legacy ship keeps its pre-skin colours. Enemy shots are never recoloured.
While wave 1 is absent, the run-start tests use a stub progress/skins pair that is installed for the
whole run. Tests that need the real wave-1 modules print [SKIP requires-wave1] when they are missing.
"""

import random
import sys
import types

import pyglet

import config
from game import Game
from particles import ParticleSystem
from player_art import DEFAULT_PALETTE
from projectile import Projectile
from projectile_art import ENEMY_HEAD, ENEMY_TRAIL, GOLD_TRAIL, WEAPON_STYLES
from skin_apply import (
    DEFAULT_SKIN_ID,
    LEGACY_GLOW2,
    LEGACY_PALETTE,
    PALETTE_KEYS,
    RunSkin,
    aura_outer,
    complete_palette,
    default_run_skin,
    read_run_skin,
)
from skin_preview import SkinPreview, draw_skin_preview
from states import GameStateName
from utils import Vec2

EMBER = {
    "body": (255, 150, 70),
    "accent": (255, 90, 30),
    "eye": (255, 240, 200),
    "glow": (200, 90, 40),
    "trail": (255, 80, 200),
    "bullet": (120, 255, 140),
}
FROST = {
    "body": (170, 240, 255),
    "accent": (120, 200, 255),
    "eye": (255, 255, 255),
    "glow": (90, 160, 255),
    "trail": (200, 240, 255),
    "bullet": (225, 250, 255),
}
DASH_LEGACY = (160, 220, 255)


class _StubStore:
    """Stands in for progress.py and skins.py so the run-start wiring runs without wave 1."""

    def __init__(self):
        self.selected_skin = DEFAULT_SKIN_ID
        self.skins = {DEFAULT_SKIN_ID: dict(DEFAULT_PALETTE), "ember": EMBER, "frost": FROST}
        self._saved = {}

    def install(self):
        store = self

        progress_mod = types.ModuleType("progress")
        progress_mod.load = lambda path=None: {"selected_skin": store.selected_skin}

        skins_mod = types.ModuleType("skins")

        def selected(progress):
            sid = progress.get("selected_skin", DEFAULT_SKIN_ID)
            return types.SimpleNamespace(id=sid, name=sid.title(), description="", palette=store.skins[sid])

        skins_mod.selected = selected
        self._saved = {name: sys.modules.get(name) for name in ("progress", "skins")}
        sys.modules["progress"] = progress_mod
        sys.modules["skins"] = skins_mod

    def uninstall(self):
        for name, mod in self._saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


_STORE = _StubStore()


def _rgb(shape):
    return tuple(int(c) for c in shape.color[:3])


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _shot_colours(vis, proj):
    """(body colour, first trail piece's colour or None) for a shot after ensure_projectile."""
    pv = vis._proj_handles[id(proj)]
    trail = _rgb(pv._trail[0]) if pv._trail else None
    return _rgb(pv._body), trail


def _hull_colour(g):
    """The PlayerArt hull colour after a sync, which is what the player sees."""
    g.visuals.sync_player(g.player, Vec2(0.0, 0.0), t=0.0)
    return _rgb(g.visuals._player_art.body)


def _player_shot(kind="bullet", crit=False):
    return Projectile(
        pos=Vec2(0.0, 0.0),
        vel=Vec2(400.0, 0.0),
        damage=10,
        owner="player",
        projectile_type=kind,
        is_crit=crit,
    )


def _enemy_shot(kind="bullet"):
    return Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(-200.0, 0.0), damage=8, owner="enemy", projectile_type=kind)


def _real_wave1():
    """The real progress and skins modules, or None when wave 1 is not in this worktree. Call with the stub removed."""
    try:
        import progress
        import skins
    except ImportError:
        return None
    return progress, skins


def test_default_palette_is_wave1_look(g):
    _STORE.selected_skin = DEFAULT_SKIN_ID
    _new_run(g)
    assert default_run_skin().palette == complete_palette(DEFAULT_PALETTE)
    assert g.run_skin.is_default and g.run_skin.palette == complete_palette(DEFAULT_PALETTE), "default skin must be DEFAULT_PALETTE"
    assert g.visuals.player_palette == DEFAULT_PALETTE, "PlayerArt must get wave 1's palette exactly"
    assert g.visuals.player_bullet_tint is None and g.visuals.shot_palette is None, "default shots keep weapon colours"
    assert _hull_colour(g) == DEFAULT_PALETTE["body"], "default hull must be wave 1's body colour"

    saved = config.USE_PLAYER_ART
    config.USE_PLAYER_ART = False
    try:
        _new_run(g)
        assert g.run_skin.ship_palette == complete_palette(LEGACY_PALETTE), "default legacy ship keeps the pre-skin colours"
        h = g.visuals._player_handle.objs
        glow, body, cockpit, gun_core, thruster_l = h[1], h[8], h[9], h[12], h[13]
        assert _rgb(body) == (132, 224, 255), "legacy hull must keep the legacy colour"
        assert _rgb(cockpit) == (10, 200, 255), "legacy cockpit must keep the legacy colour"
        assert _rgb(glow) == (60, 140, 220), "legacy aura must keep the legacy colour"
        assert _rgb(gun_core) == (255, 255, 255), "legacy gun core must keep the legacy colour"
        assert _rgb(thruster_l) == (130, 210, 255), "legacy thrusters must keep the legacy colour"
    finally:
        config.USE_PLAYER_ART = saved
    print("[PASS] test_default_palette_is_wave1_look passed (default = DEFAULT_PALETTE; legacy ship keeps its colours)")


def test_default_skin_keeps_shot_look(g):
    _STORE.selected_skin = DEFAULT_SKIN_ID
    _new_run(g)
    assert g.run_skin.is_default and g.run_skin.shot_palette is None and g.run_skin.dash_color is None
    vis = g.visuals
    basic = WEAPON_STYLES["Basic Gun"]
    mine = _player_shot()
    vis.ensure_projectile(mine)
    body, trail = _shot_colours(vis, mine)
    assert body == basic.head, f"default player shot colour changed: {body}"
    assert trail == basic.trail_color, f"default player trail colour changed: {trail}"
    enemy = _enemy_shot()
    vis.ensure_projectile(enemy)
    body, trail = _shot_colours(vis, enemy)
    assert body == ENEMY_HEAD and trail == ENEMY_TRAIL, f"enemy shot must stay red-orange, got {body} {trail}"
    vis.drop_projectile(mine)
    vis.drop_projectile(enemy)
    print("[PASS] test_default_skin_keeps_shot_look passed (default shots keep weapon colours, enemy shots red-orange)")


def test_skin_palette_drives_player_shots(g):
    _new_run(g)
    ember = RunSkin("ember", complete_palette(EMBER))
    g.visuals.apply_skin(ember)
    basic = WEAPON_STYLES["Basic Gun"]

    plain = _player_shot()
    g.visuals.ensure_projectile(plain)
    body, trail = _shot_colours(g.visuals, plain)
    assert body == EMBER["bullet"], f"plain shot should use the skin bullet colour, got {body}"
    assert trail == EMBER["trail"], f"plain shot should get the skin trail colour, got {trail}"

    spread = _player_shot("spread")
    g.visuals.ensure_projectile(spread)
    body, trail = _shot_colours(g.visuals, spread)
    assert body == EMBER["bullet"] and trail == EMBER["trail"], f"spread shot look {body} {trail}"

    railgun = _player_shot("railgun")
    g.visuals.ensure_projectile(railgun)
    body, trail = _shot_colours(g.visuals, railgun)
    assert body == WEAPON_STYLES["Hyper Railgun"].head, "heavy weapons keep their identity colour"
    assert trail == EMBER["trail"], "heavy weapon trails use the skin trail colour"

    crit = _player_shot(crit=True)
    g.visuals.ensure_projectile(crit)
    body, trail = _shot_colours(g.visuals, crit)
    assert body == basic.head and trail == GOLD_TRAIL, f"crit must keep gold, got {body} {trail}"

    enemy = _enemy_shot()
    g.visuals.ensure_projectile(enemy)
    body, trail = _shot_colours(g.visuals, enemy)
    assert body == ENEMY_HEAD and trail == ENEMY_TRAIL, "enemy shots ignore the player's skin"

    for p in (plain, spread, railgun, crit, enemy):
        g.visuals.drop_projectile(p)
    g.visuals.apply_skin(default_run_skin())
    print("[PASS] test_skin_palette_drives_player_shots passed (player shot heads and trails take the skin, crit and enemy unchanged)")


def test_switching_skin_changes_next_run(g):
    _STORE.selected_skin = DEFAULT_SKIN_ID
    _new_run(g)
    assert g.run_skin.is_default, "run 1 should use the default skin"
    assert g.visuals.shot_palette is None
    first = _player_shot()
    g.visuals.ensure_projectile(first)
    assert _shot_colours(g.visuals, first)[0] == WEAPON_STYLES["Basic Gun"].head

    _STORE.selected_skin = "ember"
    _new_run(g)
    assert g.run_skin.skin_id == "ember", f"run 2 should read the new selection, got {g.run_skin.skin_id}"
    assert _hull_colour(g) == EMBER["body"], "PlayerArt hull must take the skin body colour"
    second = _player_shot()
    g.visuals.ensure_projectile(second)
    body, trail = _shot_colours(g.visuals, second)
    assert body == EMBER["bullet"] and trail == EMBER["trail"], f"run 2 bullets not recoloured: {body} {trail}"

    g._dash()
    afterimage = [p.color for p in g.particle_system.particles[-8:]]
    assert len(afterimage) == 8 and all(c == EMBER["trail"] for c in afterimage), f"dash afterimage colours {afterimage}"

    _STORE.selected_skin = "frost"
    _new_run(g)
    assert g.run_skin.skin_id == "frost", "run 3 should pick up the frost skin"
    assert _hull_colour(g) == FROST["body"]
    _STORE.selected_skin = DEFAULT_SKIN_ID
    print("[PASS] test_switching_skin_changes_next_run passed (default -> ember -> frost, hull, bullets and dash follow each run)")


def test_run_skin_read_leaves_run_rng_alone(g):
    _STORE.selected_skin = "ember"
    _new_run(g)
    rng_state = g.state.rng.getstate()
    global_state = random.getstate()
    read_run_skin()
    assert g.state.rng.getstate() == rng_state, "reading the skin must not touch the seeded run RNG"
    assert random.getstate() == global_state, "reading the skin must not touch the global random state"
    _STORE.selected_skin = DEFAULT_SKIN_ID
    print("[PASS] test_run_skin_read_leaves_run_rng_alone passed (no RNG draws while reading the skin)")


def test_bad_or_missing_save_falls_back_to_default(g):
    _STORE.selected_skin = "does-not-exist"
    skin = read_run_skin()
    assert skin.is_default and skin.palette == complete_palette(DEFAULT_PALETTE), "unknown skin must fall back"
    _STORE.selected_skin = DEFAULT_SKIN_ID

    saved = {name: sys.modules.get(name) for name in ("progress", "skins")}
    sys.modules["progress"] = None  # importing a module set to None raises ImportError
    sys.modules["skins"] = None
    try:
        skin = read_run_skin()
        assert skin.is_default, "missing wave-1 modules must give the default skin"
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
    print("[PASS] test_bad_or_missing_save_falls_back_to_default passed (unknown skin and missing modules -> default)")


def test_complete_palette_fills_missing_keys(g):
    partial = complete_palette({"body": (1, 2, 3)})
    assert partial["body"] == (1, 2, 3)
    for key in PALETTE_KEYS:
        if key != "body":
            assert partial[key] == DEFAULT_PALETTE[key], f"{key} should fall back to the default look"
    print("[PASS] test_complete_palette_fills_missing_keys passed (partial palettes fall back per key)")


def test_aura_outer_keeps_default_and_follows_skin(g):
    assert aura_outer(LEGACY_PALETTE) == LEGACY_GLOW2 == (80, 120, 220), "legacy halo must stay the legacy colour"
    warm = aura_outer(EMBER)
    assert warm[0] > warm[2], f"ember halo should be warm, got {warm}"
    print("[PASS] test_aura_outer_keeps_default_and_follows_skin passed (legacy halo exact, ember halo warm)")


def test_dash_afterimage_colour(g):
    ps = ParticleSystem(pyglet.graphics.Batch())
    ps.add_dash_effect(Vec2(0.0, 0.0), Vec2(1.0, 0.0))
    assert ps.particles and all(p.color == DASH_LEGACY for p in ps.particles), "default afterimage keeps the legacy colour"
    ps.particles.clear()
    ps.add_dash_effect(Vec2(0.0, 0.0), Vec2(1.0, 0.0), color=EMBER["trail"])
    assert ps.particles and all(p.color == EMBER["trail"] for p in ps.particles), "skin afterimage colour not applied"
    print("[PASS] test_dash_afterimage_colour passed (legacy colour by default, skin colour when given)")


def test_skin_preview_draws_at_size(g):
    batch = pyglet.graphics.Batch()
    preview = draw_skin_preview(batch, 100.0, 200.0, size=1.0, palette=EMBER)
    assert isinstance(preview, SkinPreview)
    assert preview.shape_count == 11, f"preview should be 11 shapes, got {preview.shape_count}"
    body = preview._shapes[4]
    assert _rgb(body) == EMBER["body"], "preview hull must use the skin body colour"
    assert abs(body.x - 100.0) < 1e-6 and abs(body.y - 200.0) < 1e-6, "preview must sit at the requested centre"
    engine = preview._shapes[6]
    assert abs(engine.radius - 4.0) < 1e-6, f"size 1.0 engine radius should be 4, got {engine.radius}"

    before = list(preview._shapes)
    preview.set(300.0, 220.0, size=1.0, palette=EMBER)
    assert all(a is b for a, b in zip(before, preview._shapes)), "moving alone must not rebuild the shapes"
    assert abs(preview._shapes[4].x - 300.0) < 1e-6 and abs(preview._shapes[4].y - 220.0) < 1e-6

    preview.set(300.0, 220.0, size=2.0, palette=EMBER)
    assert preview.shape_count == 11
    assert abs(preview._shapes[6].radius - 8.0) < 1e-6, "size 2.0 should double the engine radius"

    preview.set(300.0, 220.0, size=2.0, palette=FROST)
    assert _rgb(preview._shapes[4]) == FROST["body"], "palette change must recolour the hull"

    preview.delete()
    assert preview.shape_count == 0
    print("[PASS] test_skin_preview_draws_at_size passed (11 shapes, moves without rebuild, scales and recolours)")


def test_skin_preview_two_skins_side_by_side(g):
    batch = pyglet.graphics.Batch()
    a = draw_skin_preview(batch, 200.0, 300.0, size=1.5, palette=LEGACY_PALETTE)
    b = draw_skin_preview(batch, 520.0, 300.0, size=1.5, palette=EMBER)
    assert _rgb(a._shapes[4]) == (132, 224, 255) and _rgb(b._shapes[4]) == EMBER["body"]
    a.delete()
    b.delete()
    print("[PASS] test_skin_preview_two_skins_side_by_side passed (two skins coexist in one batch)")


def test_real_progress_and_skins_select_next_run(g):
    mods = _real_wave1()
    if mods is None:
        print("[SKIP requires-wave1] real progress.py / skins.py path not in this worktree")
        return
    progress, skins = mods
    data = progress.default_progress()
    ids = [skin.id for skin in skins.SKINS]
    locked = [sid for sid in ids if not skins.unlocked(data, sid)]
    if locked:
        assert skins.select(data, locked[0]) is False, "a locked skin must be refused"
        assert skins.selected(data).id == DEFAULT_SKIN_ID, "refused selection must leave the default in place"
    target = next((sid for sid in ids if sid != DEFAULT_SKIN_ID), None)
    if target is None:
        print("[SKIP requires-wave1] only the default skin exists")
        return
    data.setdefault("unlocked_skins", []).append(target)
    assert skins.select(data, target) is True, "an unlocked skin must be selectable"
    skin = read_run_skin(progress=data)
    assert skin.skin_id == target, f"expected {target}, got {skin.skin_id}"
    assert skin.palette == complete_palette(skins.get(target).palette)
    print("[PASS] test_real_progress_and_skins_select_next_run passed (locked refused, unlocked read at run start)")


def test_default_skin_matches_wave1_default_palette(g):
    mods = _real_wave1()
    if mods is None:
        print("[SKIP requires-wave1] wave-1 progress.py / skins.py not in this worktree")
        return
    progress, skins = mods
    assert DEFAULT_SKIN_ID == skins.DEFAULT_SKIN_ID, "skin_apply and skins must name the same default"
    catalogue = complete_palette(skins.get(skins.DEFAULT_SKIN_ID).palette)
    assert catalogue == complete_palette(DEFAULT_PALETTE), "the catalogue's default palette must equal DEFAULT_PALETTE"
    skin = read_run_skin(progress=progress.default_progress())
    assert skin.is_default and skin.palette == complete_palette(DEFAULT_PALETTE), "the default run must use DEFAULT_PALETTE"
    print("[PASS] test_default_skin_matches_wave1_default_palette passed (catalogue default == DEFAULT_PALETTE == run default)")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        _STORE.install()
        try:
            test_default_palette_is_wave1_look(g)
            test_default_skin_keeps_shot_look(g)
            test_skin_palette_drives_player_shots(g)
            test_switching_skin_changes_next_run(g)
            test_run_skin_read_leaves_run_rng_alone(g)
            test_bad_or_missing_save_falls_back_to_default(g)
            test_complete_palette_fills_missing_keys(g)
            test_aura_outer_keeps_default_and_follows_skin(g)
            test_dash_afterimage_colour(g)
            test_skin_preview_draws_at_size(g)
            test_skin_preview_two_skins_side_by_side(g)
        finally:
            _STORE.uninstall()
        test_real_progress_and_skins_select_next_run(g)
        test_default_skin_matches_wave1_default_palette(g)
    finally:
        g.close()
    print("\nALL WAVE2 SKINAPPLY TESTS PASSED")


if __name__ == "__main__":
    run_all()
