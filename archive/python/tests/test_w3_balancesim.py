"""Deterministic tests for the offline balance simulator (tools/balance_sim.py), wave 3 item "balancesim".

Plain functions that print [PASS] lines. No window is opened and no real project file is written:
the one test that edits a source file does it in a temp copy.
Cross-wave checks skip with "[SKIP requires-wave1]" when the wave-1 module is not in this worktree.
"""

import csv
import importlib.util
import os
import random
import shutil
import subprocess
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import config  # noqa: E402
from logic import EnemyTuningLogic  # noqa: E402
from weapons import WEAPONS  # noqa: E402


def _load_sim(root):
    """Load tools/balance_sim.py from a given project root as a fresh module."""
    path = os.path.join(root, "tools", "balance_sim.py")
    spec = importlib.util.spec_from_file_location("balance_sim_under_test_" + os.path.basename(root).replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bs = _load_sim(HERE)


def _csv_value(path, section, id_, metric):
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["section"] == section and row["id"] == id_ and row["metric"] == metric:
                return float(row["value"])
    raise AssertionError(f"no CSV row {section}/{id_}/{metric} in {path}")


def _run_cli(root, args):
    script = os.path.join(root, "tools", "balance_sim.py")
    return subprocess.run(
        [sys.executable, script] + list(args),
        cwd=root, capture_output=True, text=True, timeout=600,
    )


def test_basic_dps_matches_hand_calculation():
    # Basic gun: damage 10 -> shot 15 (weapon.damage + 0.5 * PLAYER_DAMAGE). Crit 10% for x2.
    # Expected shot = 0.9 * 15 + 0.1 * 30 = 16.5. Cooldown at the baseline fire rate = 0.28 s.
    dps = bs.weapon_dps(WEAPONS["basic"], 10, 0.28)
    expected = 16.5 / 0.28
    assert abs(dps - expected) < 1e-9, f"basic DPS {dps} != {expected}"
    print(f"[PASS] test_basic_dps_matches_hand_calculation ({dps:.4f} DPS)")


def test_spread_volley_counts_every_pellet():
    # Spread: 3 pellets of 13 (8 + 5), crit 10% for x2 -> per pellet 0.9*13 + 0.1*26 = 14.3.
    # Volley = 42.9 over a 0.35 s cooldown. Every pellet is assumed to hit, as weapons.py does.
    dps = bs.weapon_dps(WEAPONS["spread"], 10, 0.28)
    expected = 42.9 / 0.35
    assert abs(dps - expected) < 1e-9, f"spread DPS {dps} != {expected}"
    _, pellets, per_pellet, _ = bs.volley_breakdown(WEAPONS["spread"], 10)
    assert pellets == 3 and per_pellet == 13.0, (pellets, per_pellet)
    print("[PASS] test_spread_volley_counts_every_pellet (3 pellets of 13, DPS 122.6)")


def test_standard_wave_follows_spawn_rules():
    # Wave 1: base count 4 + int(1.4) = 5, under the normal cap of 12.
    w1 = bs.standard_wave(1, "normal")
    assert w1["kind"] == "standard" and w1["enemies"] == 5, w1
    # Wave 29: base 4 + int(40.6) = 44, capped at 12 + the ramp max of 8 = 20.
    w29 = bs.standard_wave(29, "normal")
    assert w29["enemies"] == 20, w29
    for wave in (5, 10, 15, 20, 25, 30):
        boss = bs.standard_wave(wave, "normal")
        assert boss["kind"] == "boss" and boss["enemies"] == 1 and boss["boss"].startswith("boss_"), boss
    print("[PASS] test_standard_wave_follows_spawn_rules (wave 1 = 5, wave 29 = 20, boss waves = 1)")


def test_boss_hp_matches_enemy_stats():
    boss = bs.standard_wave(5, "normal")
    tuning = EnemyTuningLogic()
    name = boss["boss"]
    hp = tuning.enemy_stats(name, 5, "normal")[0]
    assert boss["typical_hp"] == float(hp) and boss["total_hp"] == float(hp), (boss, hp)
    print(f"[PASS] test_boss_hp_matches_enemy_stats ({name} at wave 5 = {hp} HP)")


def test_difficulty_moves_wave_hp_the_right_way():
    easy = bs.standard_wave(12, "easy")["total_hp"]
    normal = bs.standard_wave(12, "normal")["total_hp"]
    hard = bs.standard_wave(12, "hard")["total_hp"]
    assert easy < normal < hard, (easy, normal, hard)
    print(f"[PASS] test_difficulty_moves_wave_hp_the_right_way (wave 12: easy {easy:.0f} < normal {normal:.0f} < hard {hard:.0f})")


def test_standard_wave_is_deterministic_and_keeps_global_rng():
    random.seed(4242)
    before = random.getstate()
    a = bs.standard_wave(7, "normal")
    after = random.getstate()
    b = bs.standard_wave(7, "normal")
    assert before == after, "standard_wave must restore the global RNG state"
    assert a == b, "standard_wave must be a pure function of its inputs"
    print("[PASS] test_standard_wave_is_deterministic_and_keeps_global_rng")


def test_outlier_rule_is_strictly_more_than_forty_percent():
    values = {"a": 100.0, "b": 100.0, "c": 100.0, "d": 150.0, "e": 60.0, "f": 140.0, "h": 59.0, "n": None}
    median, flagged = bs.find_outliers(values)
    assert median == 100.0, median
    kinds = [k for k, _, _ in flagged]
    # d is +50 percent and h is -41 percent: flagged. e is exactly -40 percent and f exactly +40 percent: not flagged.
    assert kinds == ["d", "h"], kinds
    median0, flagged0 = bs.find_outliers({"x": None})
    assert median0 is None and flagged0 == []
    print("[PASS] test_outlier_rule_is_strictly_more_than_forty_percent (median 100, flagged d and h)")


def test_every_powerup_kind_is_priced_or_explained():
    rep = bs.build_report("normal", bs.REF_WAVE_DEFAULT, 10, 0.28, 0.5)
    assert set(rep["powerups"]) == set(config.POWERUP_COLORS), (sorted(rep["powerups"]), sorted(config.POWERUP_COLORS))
    for kind, (val, unit, basis) in rep["powerups"].items():
        assert val is not None or basis.startswith("n/a"), (kind, basis)
        if val is not None:
            assert unit in ("HP", "damage") and val >= 0.0, (kind, val, unit)
    priced = sum(1 for v, _, _ in rep["powerups"].values() if v is not None)
    print(f"[PASS] test_every_powerup_kind_is_priced_or_explained ({priced} priced of {len(rep['powerups'])} kinds)")


def test_wave1_powerup_kinds_skip_until_present():
    rep = bs.build_report("normal", bs.REF_WAVE_DEFAULT, 10, 0.28, 0.5)
    text = bs.render_markdown(rep)
    missing = [k for k in bs.WAVE1_POWERUP_KINDS if k not in config.POWERUP_COLORS]
    for kind in missing:
        print(f"[SKIP requires-wave1] power-up '{kind}' is not in this worktree")
        assert f"[SKIP requires-wave1] power-up '{kind}'" in text
    for kind in bs.WAVE1_POWERUP_KINDS:
        if kind in config.POWERUP_COLORS:
            assert kind in rep["powerups"]
    print(f"[PASS] test_wave1_powerup_kinds_skip_until_present ({len(missing)} kinds reported as skipped)")


def test_mutator_and_skin_tables_are_guarded():
    rows_m, note_m = bs.mutator_rows(10, 0.28)
    rows_s, note_s = bs.skin_rows()
    if importlib.util.find_spec("mutators") is None:
        print("[SKIP requires-wave1] mutators.py is not in this worktree")
        assert rows_m == [] and "[SKIP requires-wave1]" in note_m
    else:
        assert note_m == "" and all("score_mult" in r for r in rows_m)
    if importlib.util.find_spec("skins") is None:
        print("[SKIP requires-wave1] skins.py is not in this worktree")
        assert rows_s == [] and "[SKIP requires-wave1]" in note_s
    else:
        assert note_s == "" and all("score_mult" in r for r in rows_s)
    print("[PASS] test_mutator_and_skin_tables_are_guarded")


def test_mutator_table_reports_score_and_difficulty_change():
    # A fake wave-1 module is injected only for this test and then removed. It does not touch real files.
    class _FakeMutator:
        id = "fake"
        name = "Fake Pressure"
        score_mult = 1.5

        def apply(self, cfg):
            out = dict(cfg)
            out["PLAYER_DAMAGE"] = cfg["PLAYER_DAMAGE"] + 2
            return out

    fake = types.ModuleType("mutators")
    fake.MUTATORS = {"fake": _FakeMutator()}
    saved = sys.modules.get("mutators")
    sys.modules["mutators"] = fake
    try:
        rows, note = bs.mutator_rows(10, 0.28)
    finally:
        if saved is None:
            sys.modules.pop("mutators", None)
        else:
            sys.modules["mutators"] = saved
    assert note == "", note
    assert len(rows) == 1 and rows[0]["score_mult"] == 1.5, rows
    assert "PLAYER_DAMAGE 10 -> 12" in rows[0]["change"], rows[0]["change"]
    assert "basic-gun DPS x" in rows[0]["change"], rows[0]["change"]
    print("[PASS] test_mutator_table_reports_score_and_difficulty_change (fake module, score 1.50, damage 10 -> 12)")


def test_mirrored_inline_formulas_still_match_the_game():
    # Laser beam and ultra beam damage are inline in the game code, so the simulator mirrors them.
    # If either formula changes, the simulator must change with it.
    with open(os.path.join(HERE, "states.py"), encoding="utf-8") as fh:
        states_src = fh.read()
    with open(os.path.join(HERE, "game.py"), encoding="utf-8") as fh:
        game_src = fh.read()
    assert "int(game._effective_player_damage() * 0.9) + 14" in states_src, "laser beam formula changed in states.py"
    assert "config.ULTRA_DAMAGE_BASE + self._effective_player_damage() * config.ULTRA_DAMAGE_MULT" in game_src, \
        "ultra beam formula changed in game.py"
    print("[PASS] test_mirrored_inline_formulas_still_match_the_game")


def test_simulator_reads_weapon_damage_from_weapons_py():
    tmp = tempfile.mkdtemp(prefix="w3bs_copy_")
    try:
        for name in os.listdir(HERE):
            src_path = os.path.join(HERE, name)
            if name.endswith(".py") and os.path.isfile(src_path):
                shutil.copy2(src_path, os.path.join(tmp, name))
        os.makedirs(os.path.join(tmp, "tools"))
        shutil.copy2(os.path.join(HERE, "tools", "balance_sim.py"), os.path.join(tmp, "tools", "balance_sim.py"))

        weapons_copy = os.path.join(tmp, "weapons.py")
        with open(weapons_copy, encoding="utf-8", newline="") as fh:
            src = fh.read().replace("\r\n", "\n")
        anchor = '        damage=10,\n        fire_rate=0.28,'
        assert src.count(anchor) == 1, "basic gun anchor not unique in weapons.py"
        with open(weapons_copy, "w", encoding="utf-8", newline="") as fh:
            fh.write(src.replace(anchor, '        damage=20,\n        fire_rate=0.28,', 1))

        out_csv = os.path.join(tmp, "patched.csv")
        proc = _run_cli(tmp, ["--csv", out_csv])
        assert proc.returncode == 0, proc.stderr
        patched = _csv_value(out_csv, "weapon", "basic", "dps")
        # Basic gun damage 20 -> shot 25, crit 50. Expected 0.9 * 25 + 0.1 * 50 = 27.5 over 0.28 s.
        expected_patched = 27.5 / 0.28
        original = bs.weapon_dps(WEAPONS["basic"], 10, 0.28)
        assert abs(patched - expected_patched) < 1e-4, (patched, expected_patched)
        assert abs(original - 16.5 / 0.28) < 1e-9, original
        assert abs(patched - original) > 1.0, "changing weapons.py must change the output"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"[PASS] test_simulator_reads_weapon_damage_from_weapons_py (basic DPS {original:.2f} -> {patched:.2f})")


def test_cli_prints_every_section_and_is_deterministic():
    tmp = tempfile.mkdtemp(prefix="w3bs_cli_")
    try:
        a_csv = os.path.join(tmp, "a.csv")
        b_csv = os.path.join(tmp, "b.csv")
        first = _run_cli(HERE, ["--csv", a_csv])
        second = _run_cli(HERE, ["--csv", b_csv])
        assert first.returncode == 0, first.stderr
        assert second.returncode == 0, second.stderr
        for heading in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6."):
            assert heading in first.stdout, f"missing section {heading}"
        with open(a_csv, "rb") as fa, open(b_csv, "rb") as fb:
            assert fa.read() == fb.read(), "CSV must be byte-identical across runs"
        rep_a = bs.build_report("normal", bs.REF_WAVE_DEFAULT, 10, 0.28, 0.5)
        rep_b = bs.build_report("normal", bs.REF_WAVE_DEFAULT, 10, 0.28, 0.5)
        assert bs.csv_rows(rep_a) == bs.csv_rows(rep_b)
        assert bs.render_markdown(rep_a) == bs.render_markdown(rep_b)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("[PASS] test_cli_prints_every_section_and_is_deterministic (6 sections, CSV byte-identical)")


def test_table_and_csv_shape():
    rep = bs.build_report("normal", bs.REF_WAVE_DEFAULT, 10, 0.28, 0.5)
    assert len(rep["waves"]) == 30 and [w["wave"] for w in rep["waves"]] == list(range(1, 31))
    assert len(rep["ttk"]) == 30 * len(WEAPONS) and len(rep["clear"]) == 30 * len(WEAPONS)
    rows = bs.csv_rows(rep)
    ttk_rows = [r for r in rows if r["section"] == "ttk"]
    clear_rows = [r for r in rows if r["section"] == "clear"]
    assert len(ttk_rows) == 30 * len(WEAPONS) and len(clear_rows) == 30 * len(WEAPONS)
    assert all(set(r) == set(bs.POWERUP_CSV_COLUMNS) for r in rows)
    print(f"[PASS] test_table_and_csv_shape ({len(rows)} CSV rows; 30 waves x {len(WEAPONS)} weapons)")


def run_all():
    tests = (
        test_basic_dps_matches_hand_calculation,
        test_spread_volley_counts_every_pellet,
        test_standard_wave_follows_spawn_rules,
        test_boss_hp_matches_enemy_stats,
        test_difficulty_moves_wave_hp_the_right_way,
        test_standard_wave_is_deterministic_and_keeps_global_rng,
        test_outlier_rule_is_strictly_more_than_forty_percent,
        test_every_powerup_kind_is_priced_or_explained,
        test_wave1_powerup_kinds_skip_until_present,
        test_mutator_and_skin_tables_are_guarded,
        test_mutator_table_reports_score_and_difficulty_change,
        test_mirrored_inline_formulas_still_match_the_game,
        test_table_and_csv_shape,
        test_simulator_reads_weapon_damage_from_weapons_py,
        test_cli_prints_every_section_and_is_deterministic,
    )
    for test in tests:
        test()
    print("\nALL W3 BALANCESIM TESTS PASSED")


if __name__ == "__main__":
    run_all()
