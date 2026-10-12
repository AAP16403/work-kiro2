"""Documentation checks for the wave 3 docs item (CHANGELOG.md and README.md).

These tests read the two documents and the source files they describe. They check that:

- CHANGELOG.md has the release groups and names every new system in the wave plans;
- the numbers the docs quote match config.py and the code that owns them;
- every control the README documents is a key the code reads;
- every tool, test file and build file the README names exists, and the flags it documents
  are present in the tools.

A check that needs a module owned by another wave is skipped with a "[SKIP requires-waveN]" line
when that module is missing from this worktree. The final integration pass runs every check.

Reads text files and config constants only. It never reads the clock, never writes files, and
never touches progress.json, user_settings.json or high_scores.json.
"""

import importlib
import os
import re
import sys


ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SKIPS = []


def _path(rel):
    return os.path.join(ROOT, *rel.split("/"))


def _read(rel):
    with open(_path(rel), "r", encoding="utf-8") as fh:
        return fh.read()


def _exists(rel):
    return os.path.exists(_path(rel))


def _source(*rels):
    return "\n".join(_read(r) for r in rels if _exists(r))


def _flat(text):
    """Collapse all whitespace so a phrase that wraps across lines still matches."""
    return " ".join(text.split())


def _has(text, needle):
    return needle.lower() in _flat(text).lower()


# The integration pass (run_all) sets STRICT. Then a check that needs an owned file or item and cannot find it
# fails the run; it is never counted as a pass. Outside the integration pass a missing item is a printed skip.
STRICT = False


def _skip(owner, what):
    if STRICT:
        raise AssertionError(f"[MISSING requires-{owner}] {what}")
    SKIPS.append(what)
    print(f"[SKIP requires-{owner}] {what}")


def _number(src, pattern):
    match = re.search(pattern, src)
    assert match, f"pattern not found in source: {pattern}"
    return float(match.group(1))


CHANGELOG = _read("CHANGELOG.md")
README = _read("README.md")
CL = _flat(CHANGELOG)
RM = _flat(README)

# Names from the wave plans. Each must be named in the CHANGELOG.
PLAN_MUTATORS = ["Glass Cannon", "Bullet Hell", "Drift", "Frenzy", "Iron Man"]
PLAN_POWER_UPS = ["Ricochet", "Homing", "Time Slow", "Magnet", "Drone"]
PLAN_AFFIXES = ["Volatile", "Swift", "Shielded", "Splitter", "Reflector"]
PLAN_EVENTS = ["Meteor Shower", "Solar Flare", "Nebula Cloud"]
PLAN_SYSTEMS = [
    "Hangar", "achievement", "skin", "mutator", "Daily", "arena event", "boss rage",
    "Screen Shake", "Reduced motion", "Colour-blind", "High-contrast", "Game Over",
    "replay.py", "parallel.py", "requirements.txt", "--jobs",
    "tools/bench.py", "tools/playtest.py", "tools/screens.py",
    "tools/smoke_exe.ps1", "tools/balance_sim.py",
]
NEW_SFX = [
    "ricochet", "homing_lock", "time_slow_on", "time_slow_off", "magnet", "drone_spawn",
    "drone_fire", "event_warn", "meteor_impact", "flare_sweep", "nebula_hum", "toast",
    "achievement", "daily_record", "reflect", "split", "rage_warn", "victory_fanfare",
    "skin_select", "mutator_toggle", "hangar_move",
]


def test_changelog_has_release_groups():
    assert "## Unreleased" in CL, "CHANGELOG.md needs an Unreleased release section"
    last = -1
    for group in ("Gameplay", "Visuals", "Audio", "Tools", "Fixes"):
        heading = f"### {group}"
        pos = CHANGELOG.find(heading)
        assert pos > last, f"missing or out of order: {heading}"
        last = pos
    print("[PASS] test_changelog_has_release_groups passed (Gameplay, Visuals, Audio, Tools, Fixes in order)")


def test_docs_are_plain_ascii_and_placeholder_free():
    for name, text in (("CHANGELOG.md", CHANGELOG), ("README.md", README)):
        bad = sorted({c for c in text if ord(c) > 127})
        assert not bad, f"{name} has non-ASCII characters: {bad!r}"
        for word in ("TODO", "TBD", "FIXME", "lorem ipsum"):
            assert not _has(text, word), f"{name} contains '{word}'"
    print("[PASS] test_docs_are_plain_ascii_and_placeholder_free passed")


def test_changelog_names_every_new_system_and_plan_item():
    wanted = PLAN_MUTATORS + PLAN_POWER_UPS + PLAN_AFFIXES + PLAN_EVENTS + PLAN_SYSTEMS
    missing = [name for name in wanted if not _has(CHANGELOG, name)]
    assert not missing, f"CHANGELOG.md does not name: {missing}"
    print(f"[PASS] test_changelog_names_every_new_system_and_plan_item passed ({len(wanted)} names)")


def test_changelog_names_every_new_sound_effect():
    missing = [sfx for sfx in NEW_SFX if f"`{sfx}`" not in CL]
    assert not missing, f"CHANGELOG.md does not list sound effects: {missing}"
    assert len(NEW_SFX) == 21, "the wave 3 audio item asks for 21 new sound effects"
    if not _exists("tools/synth_sfx.py"):
        _skip("wave3", "tools/synth_sfx.py missing: sound recipes not cross-checked")
    else:
        src = _read("tools/synth_sfx.py")
        absent = [sfx for sfx in NEW_SFX if f'"{sfx}"' not in src]
        if absent:
            _skip("wave3", f"synth recipes not in tools/synth_sfx.py yet: {absent}")
    print("[PASS] test_changelog_names_every_new_sound_effect passed (21 names listed)")


def test_mutator_catalogue_matches_docs():
    if not _exists("mutators.py"):
        _skip("wave1", "mutators.py not in this worktree: mutator ids and names not cross-checked")
        return
    mod = importlib.import_module("mutators")
    ids = {m.id for m in mod.MUTATORS}
    expected = {"glass_cannon", "bullet_hell", "drift", "frenzy", "iron_man"}
    assert ids == expected, f"mutator ids differ from the contract: {sorted(ids)}"
    for mut in mod.MUTATORS:
        assert _has(CHANGELOG, mut.name), f"CHANGELOG does not name mutator {mut.name!r}"
    print(f"[PASS] test_mutator_catalogue_matches_docs passed ({len(ids)} mutators, names documented)")


def test_power_up_kinds_exist_in_code():
    # Kinds are defined in powerup.py and spawned from level.py. game.py reads mods["magnet"]
    # for an unrelated existing modifier, so it is deliberately not searched.
    src = _source("powerup.py", "level.py")
    owners = {"ricochet": "wave1", "homing": "wave1", "time_slow": "wave1", "magnet": "wave1", "drone": "wave2"}
    found = 0
    for kind, owner in owners.items():
        if f'"{kind}"' in src:
            found += 1
        else:
            _skip(owner, f'power-up kind "{kind}" not in code yet')
    if found == len(owners):
        print(f"[PASS] test_power_up_kinds_exist_in_code passed ({found} kinds in code)")
    else:
        print(f"[PASS] test_power_up_kinds_exist_in_code passed ({found} of {len(owners)} kinds in code)")


def test_elite_affixes_exist_in_code():
    src = _read("level.py")
    for affix in ("volatile", "swift", "shielded"):
        assert f'"{affix}"' in src, f"existing elite affix {affix} is missing from level.py"
    for affix in ("splitter", "reflector"):
        if f'"{affix}"' in src:
            print(f"[PASS] elite affix {affix} present in level.py")
        else:
            _skip("wave2", f'elite affix "{affix}" not in level.py yet')
    print("[PASS] test_elite_affixes_exist_in_code passed (volatile, swift, shielded)")


def test_arena_events_exist_in_code():
    if not _exists("events.py"):
        _skip("wave2", "events.py not in this worktree: arena event names not cross-checked")
        return
    src = _read("events.py").lower()
    for word in ("meteor", "flare", "nebula"):
        assert word in src, f"events.py does not mention {word}"
    print("[PASS] test_arena_events_exist_in_code passed (Meteor, Flare, Nebula)")


def test_changelog_numbers_match_config():
    import config

    assert f"base damage of {config.PLAYER_DAMAGE}" in CL, "base damage in the CHANGELOG"
    assert f"{config.SHIELD_MAX}" in CL and "SHIELD_MAX" in CL, "shield cap"
    assert f"start with {config.ULTRA_MAX_CHARGES}" in CL, "starting Ultra charges"
    assert f"at most {config.ULTRA_MAX_CHARGES_HARD_CAP}" in CL, "Ultra hard cap"
    assert f"{config.GAME_OVER_REVEAL_S:.1f} s" in CL, "Game Over reveal lock"
    assert f"{round(config.WEAPON_WAVE_UPGRADE_CHANCE * 100)}%" in CL, "weapon roll chance"
    assert f"{config.ELITE_SCORE_MULT:g}x" in CL, "elite score multiplier"
    assert f"to {config.SHAKE_PLAYER_HIT_MAX:g} px" in CL, "player hit shake maximum"
    assert f"{config.SHAKE_PLAYER_HIT_BASE:g} to" in CL, "player hit shake base"
    labels = [config.SHAKE_LEVEL_LABELS[lvl] for lvl in config.SHAKE_LEVELS]
    for label in labels:
        assert label in CL, f"shake level label {label} missing from CHANGELOG"
    assert f"{config.BOOST_DAMAGE_REDUCTION * 100:.0f}%" in RM, "boost damage reduction in RM"
    assert config.SHAKE_LEVELS == ("full", "reduced", "off"), "shake levels changed; update the docs"

    logic_src = _read("logic.py")
    every = int(_number(logic_src, r"wave_cap_ramp_every: int = (\d+)"))
    start = int(_number(logic_src, r"wave_cap_ramp_start: int = (\d+)"))
    cap = int(_number(logic_src, r"wave_cap_ramp_max: int = (\d+)"))
    assert f"every {every} waves" in CL, "wave head-count ramp interval"
    assert f"first at wave {start + every}" in CL, "wave head-count ramp start"
    assert f"up to +{cap}" in CL, "wave head-count ramp cap"

    flyer_windup = _number(_read("enemy_behaviors/flyer.py"), r"windup_time=([0-9.]+)")
    lunge = _number(_read("enemy_behaviors/chase.py"), r"LUNGE_WINDUP_S = ([0-9.]+)")
    assert f"{flyer_windup:.2f} s" in CL, "flyer windup seconds"
    assert f"{lunge:.2f} s" in CL, "chaser windup seconds"
    assert "warn=0.30" in _read("enemy.py"), "boss laser warning is no longer 0.30 s"
    assert "0.30 s" in CL, "boss laser warning seconds"
    print("[PASS] test_changelog_numbers_match_config passed (damage, shield, Ultra, shake, waves, telegraphs)")


def test_settings_defaults_match_docs():
    shake_src = _read("shake_prefs.py")
    assert 'def load_shake_level(default: str = "full")' in shake_src, "shake default is no longer Full"
    assert "The default is Full" in CL, "CHANGELOG must state Screen Shake defaults to Full"
    print("[PASS] test_settings_defaults_match_docs passed (Screen Shake default Full)")


KEY_CODE_TOKENS = {
    "SPACE": "SPACE", "LSHIFT": "LSHIFT", "RSHIFT": "RSHIFT", "ESCAPE": "ESC",
    "ENTER": "ENTER", "R": "R", "M": "M", "Q": "Q",
}


def test_readme_controls_match_code():
    code = _source("states.py", "game.py", "menu.py", "rpg.py")
    for pyglet_name, token in KEY_CODE_TOKENS.items():
        assert re.search(rf"\b(?:key|k)\.{pyglet_name}\b", code), f"code never reads key.{pyglet_name}"
        assert f"`{token}`" in RM, f"README controls do not list `{token}`"
    assert "`RMB` or `Q`" in RM, "Ultra row must name RMB and Q"
    assert "Ultra (U)" not in RM and "U key" not in RM, "README repeats the wrong Ultra key"
    game_src = _read("game.py")
    assert "self.auto_shoot = True" in game_src, "auto-fire default changed; update the controls table"
    assert "starts ON" in RM, "README must say auto-fire starts ON"
    print(f"[PASS] test_readme_controls_match_code passed ({len(KEY_CODE_TOKENS)} keys read by the code)")


def test_readme_hangar_and_daily_buttons():
    menu_src = _source("menu.py")
    # The title buttons are labelled exactly as menu.py draws them: "Daily Run", not "Daily".
    for label, owner in (("Hangar", "wave2"), ("Daily Run", "wave2")):
        if f'"{label}"' in menu_src or f"'{label}'" in menu_src:
            print(f"[PASS] title-screen label {label} present in menu.py")
        else:
            _skip(owner, f'title-screen label "{label}" not in menu.py yet')
    print("[PASS] test_readme_hangar_and_daily_buttons passed (labels checked where present)")


def test_settings_keyboard_navigation_matches_readme():
    src = _read("menu.py")
    block = re.search(r"class SettingsMenu.*?(?=\nclass )", src, re.S)
    assert block, "SettingsMenu class not found"
    if "def on_key_press" in block.group(0):
        print("[PASS] test_settings_keyboard_navigation_matches_readme passed (SettingsMenu handles keys)")
    else:
        _skip("wave3", "SettingsMenu has no keyboard navigation yet (access item); README row is unverified")


def test_readme_tools_and_tests_exist():
    for name in sorted(set(re.findall(r"\btest_[a-z0-9_]+\.py\b", README))):
        assert _exists(name), f"README names {name} but it is missing"
    for rel in ("tools/synth_sfx.py", "tools/synth_music.py"):
        assert _exists(rel), f"README names {rel} but it is missing"
    owners = {
        "tools/bench.py": "wave1",
        "parallel.py": "wave1",
        "tools/playtest.py": "wave3",
        "tools/screens.py": "wave3",
        "tools/smoke_exe.ps1": "wave3",
        "tools/balance_sim.py": "wave3",
        "replay.py": "wave3",
        "requirements.txt": "wave3",
    }
    present = []
    for rel, owner in owners.items():
        if _exists(rel):
            present.append(rel)
        else:
            _skip(owner, f"{rel} is named in the README but not in this worktree")
    print(f"[PASS] test_readme_tools_and_tests_exist passed ({len(present)} of {len(owners)} owned files present)")


def test_documented_tool_flags_exist():
    flags = {
        "tools/bench.py": ["--out"],
        "tools/playtest.py": ["--runs", "--out"],
        "tools/screens.py": ["--out", "--allow-overlaps"],
        "tools/balance_sim.py": ["--csv"],
        "tools/synth_sfx.py": ["--jobs"],
        "tools/synth_music.py": ["--jobs"],
    }
    owners = {"tools/bench.py": "wave1", "tools/synth_sfx.py": "wave1", "tools/synth_music.py": "wave1"}
    for rel, wanted in flags.items():
        owner = owners.get(rel, "wave3")
        if not _exists(rel):
            _skip(owner, f"{rel} missing: flags {wanted} not checked")
            continue
        src = _read(rel)
        for flag in wanted:
            if flag in src:
                continue
            _skip(owner, f"{rel} does not accept {flag} yet")
    print("[PASS] test_documented_tool_flags_exist passed (flags checked where the tool exists)")


def test_readme_build_steps_match_build_files():
    bat = _read("build_all.bat")
    assert "APP_NAME=Plouto" in bat, "build_all.bat no longer builds Plouto"
    for needle in ("build_all.bat", "requirements.txt", "dist\\Plouto\\Plouto.exe", "dist\\Plouto.zip",
                   "kiro2_game.spec", "tools\\smoke_exe.ps1"):
        assert needle in RM, f"README build steps do not mention {needle}"
    spec = _read("kiro2_game.spec")
    assert "assets/audio" in spec and "assets/fonts" in spec, "spec no longer bundles audio and fonts"
    if "requirements.txt" in bat:
        if "pip install -U pip pyglet" in bat:
            _skip("wave3", "build_all.bat still upgrades pyglet on each build")
        else:
            print("[PASS] build_all.bat installs from requirements.txt without upgrading pyglet")
    else:
        _skip("wave3", "build_all.bat does not install from requirements.txt yet (smoke/exe item)")
    print("[PASS] test_readme_build_steps_match_build_files passed (EXE path, zip, spec, smoke step)")


def test_readme_test_command_runs_every_file():
    assert "Get-ChildItem test_*.py" in RM, "README must show the run-all test command"
    print("[PASS] test_readme_test_command_runs_every_file passed")


def run_all():
    global STRICT
    STRICT = True
    test_changelog_has_release_groups()
    test_docs_are_plain_ascii_and_placeholder_free()
    test_changelog_names_every_new_system_and_plan_item()
    test_changelog_names_every_new_sound_effect()
    test_mutator_catalogue_matches_docs()
    test_power_up_kinds_exist_in_code()
    test_elite_affixes_exist_in_code()
    test_arena_events_exist_in_code()
    test_changelog_numbers_match_config()
    test_settings_defaults_match_docs()
    test_readme_controls_match_code()
    test_readme_hangar_and_daily_buttons()
    test_settings_keyboard_navigation_matches_readme()
    test_readme_tools_and_tests_exist()
    test_documented_tool_flags_exist()
    test_readme_build_steps_match_build_files()
    test_readme_test_command_runs_every_file()
    if SKIPS:
        print(f"\n{len(SKIPS)} check(s) skipped because another wave owns the module; the integration pass must run them")
    print("\nALL W3 DOCS TESTS PASSED")


if __name__ == "__main__":
    run_all()
