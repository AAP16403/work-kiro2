"""Regression tests for the polish pass: softlock, boss contact, pickups, hit-stop, audio and popups."""

import pyglet

from audio import AudioManager
from enemy import Enemy
from game import Game
from popups import DamagePopups
from powerup import PowerUp, apply_powerup
from states import GameStateName
from utils import Vec2


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _tick(g, frames=1):
    # Call update() directly: pyglet.clock.tick() would also fire the game's scheduled
    # update with real elapsed time and double-step the simulation.
    for _ in range(frames):
        g.dispatch_events()
        g.update(1.0 / 60.0)


def test_hatched_egg_sac_does_not_block_wave(g):
    s = _new_run(g)
    sac = Enemy(pos=Vec2(120.0, 0.0), hp=30, speed=0.0, behavior="egg_sac")
    sac.hp = -1  # what _update_egg_sac leaves behind when the sac hatches
    s.enemies = [sac]
    s.wave_active = True
    wave_before = s.wave
    _tick(g, 3)
    assert sac not in s.enemies, "hatched egg sac must leave the fight"
    assert not s.wave_active and s.wave == wave_before + 1, "wave must clear once the sac is gone"
    print("[PASS] test_hatched_egg_sac_does_not_block_wave passed (sac removed, wave cleared)")


def test_boss_contact_does_not_kill_boss(g):
    s = _new_run(g)
    boss = Enemy(pos=Vec2(0.0, 0.0), hp=500, speed=0.0, behavior="boss_brute", max_hp=500)
    s.enemies = [boss]
    s.wave_active = True
    hp_before = g.player.hp
    for _ in range(20):
        boss.pos = Vec2(g.player.pos.x + 4.0, g.player.pos.y)  # keep the boss on top of the player
        _tick(g)
    assert boss in s.enemies and boss.hp > 0, "boss must survive contact with the player"
    assert g.player.hp < hp_before, "contact should still hurt the player"
    print("[PASS] test_boss_contact_does_not_kill_boss passed (boss alive, player hurt)")


def test_firerate_pickup_never_slows_player(g):
    _new_run(g)
    p = g.player
    p.fire_rate = 0.154
    apply_powerup(p, PowerUp(pos=Vec2(0.0, 0.0), kind="firerate"), 0.0)
    assert p.fire_rate <= 0.154 + 1e-9, f"firerate pickup slowed the player to {p.fire_rate}"
    p.fire_rate = 0.28
    apply_powerup(p, PowerUp(pos=Vec2(0.0, 0.0), kind="firerate"), 0.0)
    assert abs(p.fire_rate - 0.25) < 1e-9, f"expected 0.25 after pickup, got {p.fire_rate}"
    print("[PASS] test_firerate_pickup_never_slows_player passed (interval only ever shrinks)")


def test_hitstop_freezes_simulation_not_frames(g):
    s = _new_run(g)
    g._hitstop = 0.1
    t0 = s.time
    _tick(g, 3)
    assert s.time == t0, "simulation must freeze while hit-stop is active"
    assert g._hitstop < 0.1, "hit-stop must count down while frames keep rendering"
    _tick(g, 12)
    assert s.time > t0 and g._hitstop == 0.0, "simulation must resume after hit-stop"
    print("[PASS] test_hitstop_freezes_simulation_not_frames passed (frozen sim, frames still tick)")


def test_screen_shake_leaves_run_rng_untouched(g):
    s = _new_run(g)
    s.shake = 6.0
    state_before = s.rng.getstate()
    g.on_draw()
    assert s.rng.getstate() == state_before, "render-time shake must not consume the seeded run RNG"
    print("[PASS] test_screen_shake_leaves_run_rng_untouched passed (run RNG unaffected by rendering)")


def test_audio_manager_tolerates_missing_assets(g):
    a = AudioManager()
    a.play("does_not_exist", min_gap=0.0)
    a.play_music("nope")
    a.update(0.05)
    a.set_volumes(music=2.0, sfx=-1.0)
    a.play_music(None, fade=0.2)
    a.update(0.5)
    print(f"[PASS] test_audio_manager_tolerates_missing_assets passed (available={a.available})")


def test_damage_popups_pool_is_bounded(g):
    _new_run(g)  # GL context and UI fonts are ready after a run starts
    pop = DamagePopups(max_items=48)
    for i in range(200):
        pop.spawn(Vec2(float(i % 40), 0.0), str(i), big=(i % 7 == 0))
    pop.update(0.05)
    pop.sync()
    pop.draw()
    assert len(pop._slots) <= 48, f"popup pool grew to {len(pop._slots)} slots"
    pop.clear()
    pop.draw()
    print("[PASS] test_damage_popups_pool_is_bounded passed (labels reused, never beyond max_items)")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_hatched_egg_sac_does_not_block_wave(g)
        test_boss_contact_does_not_kill_boss(g)
        test_firerate_pickup_never_slows_player(g)
        test_hitstop_freezes_simulation_not_frames(g)
        test_screen_shake_leaves_run_rng_untouched(g)
        test_audio_manager_tolerates_missing_assets(g)
        test_damage_popups_pool_is_bounded(g)
    finally:
        g.close()
    print("\nALL POLISH REGRESSION TESTS PASSED")


if __name__ == "__main__":
    run_all()
