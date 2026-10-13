"""Wave 4 weapon timer tests: a weapon pickup equips for WEAPON_PICKUP_SECONDS, then reverts.

Covers: the config default and the new Player fields; a pickup equipping and reverting at the expiry edge; a
second pickup replacing the timed weapon and restarting the timer while the base stays the weapon held before the
first; the upgrade-only rule against the timed weapon; an expired timer reverting before the next pickup is
compared; wave-clear upgrades staying permanent (unit and through PlayingState.update); the speed, damage and
fire-rate boosts staying permanent; the HUD countdown and revert; the chip rewritten only when its values change;
and no new objects on steady frames. Plain functions that print [PASS] lines, run from run_all().
"""

import tracemalloc

import config
import states
from game import Game
from player import Player
from powerup import (
    PowerUp, apply_powerup, equip_permanent_weapon, expire_weapon_pickup, weapon_pickup_secs_left,
)
from states import GameStateName
from utils import Vec2
from weapons import WEAPONS

SECS = float(config.WEAPON_PICKUP_SECONDS)


def _player(weapon_key=None):
    p = Player(pos=Vec2(0.0, 0.0))
    p.current_weapon = WEAPONS[weapon_key] if weapon_key else None
    return p


def _pickup(player, key, now):
    apply_powerup(player, PowerUp(pos=Vec2(0.0, 0.0), kind="weapon", data=key), now)


def _name(wp):
    """The chip's name text for a weapon, built the same way the HUD builds it."""
    pierce = f" [P+{wp.pierce}]" if getattr(wp, "pierce", 0) > 0 else ""
    return f"{wp.name.upper()}{pierce}"


def _crit_text(wp, bonus=0.0):
    total = min(1.0, max(0.0, float(wp.crit_chance) + float(bonus)))
    return f"CRIT {int(round(total * 100))}%"


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _tick(g):
    # Call update() directly: pyglet.clock.tick() would also fire the game's scheduled update.
    g.dispatch_events()
    g.update(1.0 / 60.0)


def _refresh(g):
    """Push the current run state through the HUD the same way PlayingState.draw does."""
    g.hud.update_bars(
        g.player,
        g.state,
        score=g.score,
        has_infinite_boost=False,
        crit_chance_bonus=0.0,
        status_segments=[],
    )


# ----------------------------------------------------------------------
# Config and fields
# ----------------------------------------------------------------------

def test_config_default_and_player_fields():
    assert SECS == 20.0, f"WEAPON_PICKUP_SECONDS default must be 20, got {SECS}"
    p = Player(pos=Vec2(0.0, 0.0))
    assert p.weapon_until == 0.0 and p.weapon_base is None, "a new player holds a permanent weapon"
    print("[PASS] test_config_default_and_player_fields passed (20 s default, no timer on a new player)")


# ----------------------------------------------------------------------
# Pickup, expiry and revert (powerup level)
# ----------------------------------------------------------------------

def test_pickup_equips_then_reverts_at_expiry():
    p = _player("basic")
    _pickup(p, "heavy", 5.0)
    assert p.current_weapon is WEAPONS["heavy"], "an upgrade pickup equips"
    assert abs(p.weapon_until - (5.0 + SECS)) < 1e-9, p.weapon_until
    expire_weapon_pickup(p, 5.0 + SECS - 0.001)
    assert p.current_weapon is WEAPONS["heavy"], "still equipped just before the expiry"
    expire_weapon_pickup(p, 5.0 + SECS)
    assert p.current_weapon is WEAPONS["basic"], "reverts to the weapon held before the pickup"
    assert p.weapon_until == 0.0 and p.weapon_base is None, "the timer clears after the revert"
    print("[PASS] test_pickup_equips_then_reverts_at_expiry passed (equipped until 20 s, basic after)")


def test_second_pickup_replaces_and_restarts_timer_and_base_stays():
    p = _player("basic")
    _pickup(p, "heavy", 5.0)
    _pickup(p, "flak", 10.0)
    assert p.current_weapon is WEAPONS["flak"], "a second upgrade replaces the timed weapon"
    assert abs(p.weapon_until - (10.0 + SECS)) < 1e-9, "the timer restarts from the second pickup"
    assert p.weapon_base is WEAPONS["basic"], "the base stays the weapon held before the first pickup"
    expire_weapon_pickup(p, 29.9)
    assert p.current_weapon is WEAPONS["flak"], "flak runs its full time"
    expire_weapon_pickup(p, 30.0)
    assert p.current_weapon is WEAPONS["basic"], "expiry returns to the original base, not the replaced weapon"
    print("[PASS] test_second_pickup_replaces_and_restarts_timer_and_base_stays passed (flak 10-30 s, basic after)")


def test_second_pickup_below_the_timed_weapon_keeps_the_timer():
    p = _player("basic")
    _pickup(p, "flak", 5.0)
    until = p.weapon_until
    _pickup(p, "heavy", 10.0)  # heavy (rank 2) does not outrank the timed flak (rank 7)
    assert p.current_weapon is WEAPONS["flak"], "a pickup below the timed weapon must not replace it"
    assert p.shield == 20, "it pays off as a +20 shield top-up"
    assert p.weapon_until == until, "nothing changed, so the timer does not restart"
    assert p.weapon_base is WEAPONS["basic"], "the base is unchanged"
    print("[PASS] test_second_pickup_below_the_timed_weapon_keeps_the_timer passed (upgrade-only holds against flak)")


def test_expired_timer_reverts_before_the_next_pickup_is_compared():
    p = _player("basic")
    _pickup(p, "flak", 5.0)  # runs out at 25 with no expire call in between
    _pickup(p, "heavy", 30.0)
    assert p.current_weapon is WEAPONS["heavy"], "compared with the reverted basic, heavy is an upgrade"
    assert abs(p.weapon_until - (30.0 + SECS)) < 1e-9, p.weapon_until
    assert p.weapon_base is WEAPONS["basic"], "the new base is the weapon held after the revert"
    assert p.shield == 0, "no shield top-up: the pickup equipped"
    print("[PASS] test_expired_timer_reverts_before_the_next_pickup_is_compared passed (heavy equips over reverted basic)")


def test_permanent_weapon_still_only_upgrades_and_starts_no_timer():
    p = _player("plasma")
    _pickup(p, "basic", 5.0)
    assert p.current_weapon is WEAPONS["plasma"] and p.shield == 20, "a downgrade pays off as shield"
    assert p.weapon_until == 0.0 and p.weapon_base is None, "a shield top-up starts no timer"
    print("[PASS] test_permanent_weapon_still_only_upgrades_and_starts_no_timer passed (plasma holds, no timer)")


def test_no_weapon_before_the_pickup_reverts_to_none():
    p = _player(None)
    _pickup(p, "heavy", 0.0)
    assert p.current_weapon is WEAPONS["heavy"] and p.weapon_base is None
    expire_weapon_pickup(p, SECS)
    assert p.current_weapon is None and p.weapon_until == 0.0, "the held weapon before the pickup was none"
    print("[PASS] test_no_weapon_before_the_pickup_reverts_to_none passed (base None reverts to None)")


def test_countdown_rounds_up_and_is_zero_when_permanent():
    p = _player("basic")
    assert weapon_pickup_secs_left(p, 0.0) == 0, "no timer, no countdown"
    _pickup(p, "heavy", 5.0)
    assert weapon_pickup_secs_left(p, 5.0) == 20
    assert weapon_pickup_secs_left(p, 5.5) == 20, "19.5 s left rounds up to 20"
    assert weapon_pickup_secs_left(p, 6.0) == 19
    assert weapon_pickup_secs_left(p, 24.2) == 1, "0.8 s left shows 1"
    assert weapon_pickup_secs_left(p, 25.0) == 0, "at the expiry the countdown is gone"
    print("[PASS] test_countdown_rounds_up_and_is_zero_when_permanent passed (20 down to 1, then 0)")


# ----------------------------------------------------------------------
# Permanent rewards
# ----------------------------------------------------------------------

def test_wave_clear_upgrade_cancels_the_timer_and_is_kept():
    p = _player("basic")
    _pickup(p, "heavy", 5.0)
    equip_permanent_weapon(p, WEAPONS["flak"])
    assert p.current_weapon is WEAPONS["flak"] and p.weapon_until == 0.0 and p.weapon_base is None
    expire_weapon_pickup(p, 1000.0)
    assert p.current_weapon is WEAPONS["flak"], "the revert never undoes a wave-clear upgrade"
    print("[PASS] test_wave_clear_upgrade_cancels_the_timer_and_is_kept passed (flak kept far past 20 s)")


def test_speed_damage_and_firerate_boosts_stay_permanent():
    p = _player("basic")
    _pickup(p, "flak", 0.0)
    base_speed, base_damage, base_fr = p.speed, p.damage, p.fire_rate
    for kind in ("speed", "damage", "firerate"):
        apply_powerup(p, PowerUp(pos=Vec2(0.0, 0.0), kind=kind), 1.0)
    boosted = (p.speed, p.damage, p.fire_rate)
    assert boosted[0] > base_speed and boosted[1] > base_damage and boosted[2] < base_fr, "the boosts applied"
    expire_weapon_pickup(p, 100.0)
    assert (p.speed, p.damage, p.fire_rate) == boosted, "expiry leaves the boosts in place"
    assert p.current_weapon is WEAPONS["basic"], "only the weapon reverted"
    print("[PASS] test_speed_damage_and_firerate_boosts_stay_permanent passed (boosts kept after the revert)")


# ----------------------------------------------------------------------
# Through the game (PlayingState.update, wave clear, HUD)
# ----------------------------------------------------------------------

def test_playing_update_reverts_the_weapon_when_time_runs_out(g):
    s = _new_run(g)
    g.player.current_weapon = WEAPONS["basic"]
    s.time = 100.0
    _pickup(g.player, "heavy", s.time)
    s.time = 100.0 + SECS - 0.5
    _tick(g)
    assert g.player.current_weapon is WEAPONS["heavy"], "still equipped before the expiry"
    s.time = 100.0 + SECS + 0.5
    _tick(g)
    assert g.player.current_weapon is WEAPONS["basic"], "update() reverts the weapon at expiry"
    assert g.player.weapon_until == 0.0
    print("[PASS] test_playing_update_reverts_the_weapon_when_time_runs_out passed (update() reverts at 20 s)")


def test_wave_clear_upgrade_is_kept_after_the_timer_runs_out(g):
    s = _new_run(g)
    assert 1 % config.BOSS_WAVE_EVERY != 0, "this test needs a non-boss wave"
    real_roll = states.roll_wave_clear_upgrade
    states.roll_wave_clear_upgrade = lambda *a, **k: WEAPONS["flak"]
    try:
        g.player.current_weapon = WEAPONS["basic"]
        s.time = 100.0
        _pickup(g.player, "heavy", s.time)
        s.wave_active = True
        s.enemies = []
        _tick(g)
    finally:
        states.roll_wave_clear_upgrade = real_roll
    assert g.player.current_weapon is WEAPONS["flak"], "the wave-clear upgrade equips"
    assert g.player.weapon_until == 0.0, "and it cancels the pickup timer"
    s.time = 100.0 + SECS + 5.0
    _tick(g)
    assert g.player.current_weapon is WEAPONS["flak"], "the wave-clear upgrade outlives the timer"
    print("[PASS] test_wave_clear_upgrade_is_kept_after_the_timer_runs_out passed (flak kept after 20 s)")


def test_wave_clear_roll_below_the_timed_weapon_is_discarded(g):
    s = _new_run(g)
    real_roll = states.roll_wave_clear_upgrade
    states.roll_wave_clear_upgrade = lambda *a, **k: None
    try:
        g.player.current_weapon = WEAPONS["basic"]
        s.time = 100.0
        _pickup(g.player, "heavy", s.time)
        s.wave_active = True
        s.enemies = []
        _tick(g)
    finally:
        states.roll_wave_clear_upgrade = real_roll
    assert g.player.current_weapon is WEAPONS["heavy"], "no roll means the timed weapon stays this wave"
    assert g.player.weapon_until > 0.0, "the timer is still running"
    s.time = 100.0 + SECS + 5.0
    _tick(g)
    assert g.player.current_weapon is WEAPONS["basic"], "without a permanent upgrade the timer reverts as usual"
    print("[PASS] test_wave_clear_roll_below_the_timed_weapon_is_discarded passed (timer reverts when no roll wins)")


def test_hud_chip_counts_down_then_reverts(g):
    s = _new_run(g)
    g.player.current_weapon = WEAPONS["basic"]
    s.time = 100.0
    _pickup(g.player, "heavy", s.time)
    chip = g.hud.weapon_chip
    heavy, basic = WEAPONS["heavy"], WEAPONS["basic"]

    _refresh(g)
    assert chip.name_text == _name(heavy), chip.name_text
    assert chip.crit_text == f"{_crit_text(heavy)}  20s", chip.crit_text
    s.time = 105.0
    _refresh(g)
    assert chip.crit_text == f"{_crit_text(heavy)}  15s", chip.crit_text
    s.time = 112.2
    _refresh(g)
    assert chip.crit_text == f"{_crit_text(heavy)}  8s", chip.crit_text

    s.time = 120.5
    _tick(g)
    _refresh(g)
    assert chip.name_text == _name(basic), chip.name_text
    assert chip.crit_text == _crit_text(basic), "no countdown once the weapon has reverted"
    print(f"[PASS] test_hud_chip_counts_down_then_reverts passed ({chip.name_text!r}, 20s to 8s, then {chip.crit_text!r})")


def test_chip_is_rewritten_only_when_its_values_change(g):
    s = _new_run(g)
    g.player.current_weapon = WEAPONS["basic"]
    s.time = 100.0
    _pickup(g.player, "heavy", s.time)
    chip = g.hud.weapon_chip
    _refresh(g)  # warm the cache with the countdown at 20 s
    real = chip.set_weapon
    writes = []

    def spy(name_text, crit_text, swatch_color):
        writes.append(crit_text)
        real(name_text, crit_text, swatch_color)

    chip.set_weapon = spy
    try:
        for t in (100.1, 100.2, 100.3):  # same whole second, so the text cannot change
            s.time = t
            _refresh(g)
        assert writes == [], f"steady frames rewrote the chip: {writes}"
        s.time = 101.0  # 19 s left
        _refresh(g)
        assert len(writes) == 1 and writes[0].endswith("  19s"), writes
    finally:
        del chip.set_weapon
    print("[PASS] test_chip_is_rewritten_only_when_its_values_change passed (0 writes on steady frames, 1 at the second tick)")


def test_steady_frames_build_no_new_objects(g):
    s = _new_run(g)
    g.player.current_weapon = WEAPONS["basic"]
    s.time = 100.0
    _pickup(g.player, "heavy", s.time)
    hud = g.hud
    _refresh(g)  # warm the chip cache
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        for _ in range(5000):
            hud._sync_weapon_chip(g.player, 100.5, 0.0)
            expire_weapon_pickup(g.player, 100.5)
        after = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()
    growth = after - before
    assert growth < 4096, f"steady-frame path kept {growth} bytes over 5000 frames"
    print(f"[PASS] test_steady_frames_build_no_new_objects passed (net {growth} bytes over 5000 frames)")


def run_all():
    test_config_default_and_player_fields()
    test_pickup_equips_then_reverts_at_expiry()
    test_second_pickup_replaces_and_restarts_timer_and_base_stays()
    test_second_pickup_below_the_timed_weapon_keeps_the_timer()
    test_expired_timer_reverts_before_the_next_pickup_is_compared()
    test_permanent_weapon_still_only_upgrades_and_starts_no_timer()
    test_no_weapon_before_the_pickup_reverts_to_none()
    test_countdown_rounds_up_and_is_zero_when_permanent()
    test_wave_clear_upgrade_cancels_the_timer_and_is_kept()
    test_speed_damage_and_firerate_boosts_stay_permanent()
    g = Game()
    g.set_visible(False)
    try:
        test_playing_update_reverts_the_weapon_when_time_runs_out(g)
        test_wave_clear_upgrade_is_kept_after_the_timer_runs_out(g)
        test_wave_clear_roll_below_the_timed_weapon_is_discarded(g)
        test_hud_chip_counts_down_then_reverts(g)
        test_chip_is_rewritten_only_when_its_values_change(g)
        test_steady_frames_build_no_new_objects(g)
    finally:
        g.close()
    print("\nALL W4 WEAPON TIMER TESTS PASSED")


if __name__ == "__main__":
    run_all()
