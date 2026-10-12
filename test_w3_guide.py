"""Wave 3 Guide tests: every new system has a Guide entry, the numbers in the entries come
from config or from the owner definitions, the tabs still page, and no text overflows
a row at 980x620 or 1920x1080.

Owner modules from waves 1 and 2 (mutators, skins, achievements, events, progress) may be
absent from a worktree. Tests that need the real module print a [SKIP requires-wave1] or
[SKIP requires-wave2] line instead of failing. Builder tests use fake definitions, so they
run in every worktree.
"""

import importlib
import math
import os
import re
import types

import pyglet

import config
import guide_info
from game import Game
from menu import GuideMenu

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
TABS =("enemies", "powerups", "basics", "systems")

# Names the wave 1 and 2 contract makes public. Every one needs a Guide entry.
CONTRACT_POWERUP_KINDS = [
    "heal", "damage", "speed", "firerate", "shield", "laser", "vortex", "weapon", "ultra", "boost",
    "ricochet", "homing", "time_slow", "magnet",
]
CONTRACT_MUTATOR_IDS = ["glass_cannon", "bullet_hell", "drift", "frenzy", "iron_man"]
CONTRACT_ELITE_AFFIXES = ["splitter", "reflector"]
NEW_POWERUP_KINDS = ["ricochet", "homing", "time_slow", "magnet"]


def _tab_entries(menu, tab):
    return {"enemies": menu.ENEMY_INFO, "powerups": menu.POWERUP_INFO,
            "basics": menu.BASICS_INFO, "systems": menu.SYSTEMS_INFO}[tab]


def _owner(name):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


class _FakeMutator:
    """Stands in for a wave 1 Mutator: apply() scales config values, score_mult is its multiplier."""

    def __init__(self, mid, name, score_mult, scale=None, extra=None, description="A test mutator."):
        self.id = mid
        self.name = name
        self.score_mult = score_mult
        self.description = description
        self._scale = dict(scale or {})
        self._extra = dict(extra or {})

    def apply(self, values):
        out = dict(values)
        for key, factor in self._scale.items():
            out[key] = out[key] * factor
        out.update(self._extra)
        return out


def _fake_modules():
    skin_default = types.SimpleNamespace(id="default", name="Default", description="The wave one look.", unlock=None)
    skin_locked = types.SimpleNamespace(id="ember", name="Ember", description="Warm plating.", unlock={"best_wave": 10})
    skins = types.SimpleNamespace(SKINS={"default": skin_default, "ember": skin_locked})
    achievement = types.SimpleNamespace(id="first_blood", name="First Blood", description="Score your first kill.")
    achievements = types.SimpleNamespace(ACHIEVEMENTS=[achievement])
    mutators = types.SimpleNamespace(MUTATORS={
        "glass_cannon": _FakeMutator("glass_cannon", "Glass Cannon", 1.5,
                                     scale={"PLAYER_DAMAGE": 1.5, "PLAYER_HP": 0.6}),
        "bullet_hell": _FakeMutator("bullet_hell", "Bullet Hell", 1.25,
                                    extra={"ENEMY_BULLET_SPEED_MULT": 1.25}),
    })
    events = types.SimpleNamespace(EVENTS=["meteor_shower", "solar_flare", "nebula_cloud", "custom_event"])
    return {"skins": skins, "achievements": achievements, "mutators": mutators, "events": events}


def _check_fields(entries, label):
    keys = [e["key"] for e in entries]
    assert len(set(keys)) == len(keys), f"{label} keys must be unique: {keys}"
    for e in entries:
        for field in ("key", "name", "icon", "what", "deal", "lore"):
            assert str(e.get(field, "")).strip(), f"{label} entry {e.get('key')} is missing {field}"


def test_powerup_kinds_have_entries():
    menu_keys = {e["key"] for e in GuideMenu.POWERUP_INFO}
    missing = [k for k in CONTRACT_POWERUP_KINDS if k not in menu_keys]
    assert not missing, f"Powerups tab has no entry for: {missing}"
    for kind in NEW_POWERUP_KINDS:
        assert kind in config.POWERUP_COLORS, f"{kind} needs an icon colour in config.POWERUP_COLORS"
    _check_fields(GuideMenu.POWERUP_INFO, "Powerups")
    print(f"[PASS] test_powerup_kinds_have_entries passed ({len(CONTRACT_POWERUP_KINDS)} contract kinds, {len(GuideMenu.POWERUP_INFO)} entries)")


def test_powerup_kinds_known_to_game():
    src = open(os.path.join(PROJECT_ROOT, "powerup.py"), encoding="utf-8").read()
    if not all(f'"{k}"' in src for k in NEW_POWERUP_KINDS):
        print("[SKIP requires-wave1] new powerup kinds are not in powerup.py yet")
        return
    print("[PASS] test_powerup_kinds_known_to_game passed (powerup.py names all four new kinds)")


def test_elite_affixes_have_entries():
    keys = {e["key"] for e in GuideMenu.ENEMY_INFO}
    missing = [a for a in CONTRACT_ELITE_AFFIXES if a not in keys]
    assert not missing, f"Enemies tab has no entry for elite affixes: {missing}"
    basics = next(e for e in GuideMenu.BASICS_INFO if e["key"] == "elites")
    for name in ("Volatile", "Swift", "Shielded", "Splitter", "Reflector"):
        assert name in basics["lore"] or name in basics["deal"], f"Elites entry must list {name}"
    _check_fields(GuideMenu.ENEMY_INFO, "Enemies")
    print(f"[PASS] test_elite_affixes_have_entries passed ({', '.join(CONTRACT_ELITE_AFFIXES)} on the Enemies tab, all five affixes in Elites)")


def test_enemy_entry_numbers_come_from_config():
    saved = config.ELITE_SPLIT_COUNT, config.ELITE_REFLECT_COOLDOWN, config.BOSS_RAGE_EXTRA_PROJECTILES
    try:
        config.ELITE_SPLIT_COUNT = 3
        config.ELITE_REFLECT_COOLDOWN = 4.5
        config.BOSS_RAGE_EXTRA_PROJECTILES = 2
        entries = {e["key"]: e for e in guide_info.enemy_entries()}
    finally:
        config.ELITE_SPLIT_COUNT, config.ELITE_REFLECT_COOLDOWN, config.BOSS_RAGE_EXTRA_PROJECTILES = saved
    assert "splits into 3 copies" in entries["splitter"]["what"], entries["splitter"]["what"]
    assert "Every 4.5s" in entries["reflector"]["what"], entries["reflector"]["what"]
    assert "+2 shot per volley" in entries["boss_rage"]["what"], entries["boss_rage"]["what"]
    base = {e["key"]: e for e in guide_info.enemy_entries()}
    assert "splits into 2 copies" in base["splitter"]["what"], base["splitter"]["what"]
    print("[PASS] test_enemy_entry_numbers_come_from_config passed (changing config changes the splitter, reflector and rage text)")


def test_powerup_entry_numbers_come_from_config():
    saved = config.RICOCHET_BOUNCES, config.HOMING_RANGE, config.TIME_SLOW_SCALE, config.MAGNET_RADIUS_MULT
    try:
        config.RICOCHET_BOUNCES = 2
        config.HOMING_RANGE = 300.0
        config.TIME_SLOW_SCALE = 0.25
        config.MAGNET_RADIUS_MULT = 2.0
        entries = {e["key"]: e for e in guide_info.powerup_entries()}
    finally:
        config.RICOCHET_BOUNCES, config.HOMING_RANGE, config.TIME_SLOW_SCALE, config.MAGNET_RADIUS_MULT = saved
    assert "edge 2 times" in entries["ricochet"]["what"], entries["ricochet"]["what"]
    assert "within 300 px" in entries["homing"]["what"], entries["homing"]["what"]
    assert "25% speed" in entries["time_slow"]["what"], entries["time_slow"]["what"]
    assert "2x as far" in entries["magnet"]["what"], entries["magnet"]["what"]
    default = {e["key"]: e for e in guide_info.powerup_entries()}
    assert "once" in default["ricochet"]["what"] and "within 260 px" in default["homing"]["what"], default
    assert "50% speed for 4s" in default["time_slow"]["what"] and "for 10s" in default["magnet"]["what"], default
    print("[PASS] test_powerup_entry_numbers_come_from_config passed (ricochet, homing, time slow and magnet read config)")


def test_ordinal_and_wave_schedule_text():
    expect = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", 11: "11th", 12: "12th", 13: "13th",
              21: "21st", 22: "22nd", 101: "101st", 111: "111th"}
    for n, text in expect.items():
        assert guide_info.ordinal(n) == text, f"ordinal({n}) = {guide_info.ordinal(n)}, want {text}"
    basics = next(e for e in GuideMenu.BASICS_INFO if e["key"] == "boss_schedule")
    assert basics["what"] == f"A boss arrives every {guide_info.ordinal(config.BOSS_WAVE_EVERY)} wave ({config.BOSS_WAVE_EVERY}, {2 * config.BOSS_WAVE_EVERY}, {3 * config.BOSS_WAVE_EVERY}...).", basics["what"]
    print("[PASS] test_ordinal_and_wave_schedule_text passed (ordinal suffixes and the boss schedule line)")


def test_game_code_reads_the_guide_constants():
    # The Guide quotes these values, so the game must read the same names, not literals.
    checks = {
        "level.py": ["config.BOSS_WAVE_EVERY", "config.ELITE_SWIFT_SPEED_MULT"],
        "score.py": ["config.BOSS_WAVE_EVERY"],
        "states.py": ["config.BOSS_WAVE_EVERY", "config.ELITE_VOLATILE_BLAST_RADIUS", "config.ELITE_VOLATILE_BLAST_DAMAGE"],
        "powerup.py": ["BOOST_OVERDRIVE_SECONDS"],
    }
    literal = re.compile(r"(wave|cleared_wave)\s*%\s*5\s*[!=]=\s*0|speed \*= 1\.30|v_r = 130\.0|v_dmg = 45\b|now \+ 6\.0")
    for name, needles in checks.items():
        src = open(os.path.join(PROJECT_ROOT, name), encoding="utf-8").read()
        for needle in needles:
            assert needle in src, f"{name} must read {needle}"
        assert not literal.search(src), f"{name} still has a typed value the Guide quotes"
    print("[PASS] test_game_code_reads_the_guide_constants passed (boss wave, swift, volatile blast and overdrive read config)")


def test_mutator_entries_from_definitions():
    fakes = _fake_modules()
    entries = {e["key"]: e for e in guide_info.mutator_entries(fakes["mutators"])}
    assert set(entries) == {"glass_cannon", "bullet_hell"}, entries.keys()
    gc = entries["glass_cannon"]
    assert gc["name"] == "Glass Cannon" and gc["icon"] == "GC", gc
    assert gc["what"].startswith("Score x1.5."), gc["what"]
    assert "Max HP x0.6" in gc["what"] and "damage x1.5" in gc["what"], gc["what"]
    assert gc["lore"] == "A test mutator.", gc["lore"]
    bh = entries["bullet_hell"]
    assert bh["what"] == "Score x1.25. Enemy bullet speed x1.25.", bh["what"]
    assert guide_info.mutator_entries(None) == []
    print("[PASS] test_mutator_entries_from_definitions passed (score and stat changes come from apply() and score_mult)")


def test_skin_achievement_and_event_entries_from_definitions():
    fakes = _fake_modules()
    entries = guide_info.systems_entries(fakes)
    keys = [e["key"] for e in entries]
    assert keys[0] == "hangar" and "Pick a ship look from 2 skins" in entries[0]["what"], entries[0]
    skin = {e["key"]: e for e in entries}
    assert skin["skin_ember"]["deal"] == "Unlock by best wave 10.", skin["skin_ember"]["deal"]
    assert skin["skin_default"]["deal"] == "Open from the start.", skin["skin_default"]["deal"]
    assert skin["ach_first_blood"]["what"] == "Score your first kill.", skin["ach_first_blood"]
    assert skin["event_meteor_shower"]["name"] == "Meteor Shower" and skin["event_nebula_cloud"]["name"] == "Nebula Cloud"
    assert skin["event_custom_event"]["name"] == "Custom Event", skin["event_custom_event"]
    assert skin["daily"]["name"] == "Daily Run"
    assert len(keys) == len(set(keys)), keys
    # Without owner modules only the static entries remain.
    bare = [e["key"] for e in guide_info.systems_entries({"skins": None, "achievements": None, "mutators": None, "events": None})]
    assert bare == ["hangar", "daily"], bare
    print(f"[PASS] test_skin_achievement_and_event_entries_from_definitions passed ({len(entries)} Systems entries from fake definitions)")


def test_contract_mutator_ids_have_entries():
    if _owner("mutators") is None:
        print("[SKIP requires-wave1] mutator ids need mutators.py in the build")
        return
    import mutators
    ids = {m.id for m in mutators.MUTATORS}
    assert ids == set(CONTRACT_MUTATOR_IDS), sorted(ids)
    keys = {e["key"] for e in guide_info.systems_entries()}
    missing = [m for m in CONTRACT_MUTATOR_IDS if m not in keys]
    assert not missing, f"Systems tab has no entry for mutators: {missing}"
    print(f"[PASS] test_contract_mutator_ids_have_entries passed ({len(CONTRACT_MUTATOR_IDS)} mutators, all on the Systems tab)")


def test_real_skins_and_achievements_have_entries():
    skins = _owner("skins")
    achievements = _owner("achievements")
    if skins is None or achievements is None:
        print("[SKIP requires-wave1] skins.py and achievements.py are not in the build")
        return
    keys = {e["key"] for e in guide_info.systems_entries()}
    missing = [f"skin_{s}" for s in skins.SKINS if f"skin_{s}" not in keys]
    missing += [f"ach_{a.id}" for a in achievements.ACHIEVEMENTS if f"ach_{a.id}" not in keys]
    assert not missing, f"Systems tab misses: {missing}"
    print(f"[PASS] test_real_skins_and_achievements_have_entries passed ({len(skins.SKINS)} skins, {len(achievements.ACHIEVEMENTS)} achievements)")


def test_real_events_have_entries():
    events = _owner("events")
    if events is None:
        print("[SKIP requires-wave2] events.py is not in the build")
        return
    keys = {e["key"] for e in guide_info.systems_entries()}
    missing = [e for e in events.EVENTS if f"event_{_event_id(e)}" not in keys]
    assert not missing, f"Systems tab misses arena events: {missing}"
    print(f"[PASS] test_real_events_have_entries passed ({len(events.EVENTS)} arena events)")


def _event_id(event):
    return event if isinstance(event, str) else getattr(event, "id", event)


def test_real_elite_affixes_in_level():
    src = open(os.path.join(PROJECT_ROOT, "level.py"), encoding="utf-8").read()
    if not all(f'"{a}"' in src for a in CONTRACT_ELITE_AFFIXES):
        print("[SKIP requires-wave2] splitter and reflector are not in level.py yet")
        return
    print("[PASS] test_real_elite_affixes_in_level passed (level.py names both new affixes)")


def test_systems_entries_have_all_fields():
    _check_fields(guide_info.systems_entries(_fake_modules()), "Systems")
    _check_fields(GuideMenu.SYSTEMS_INFO, "Systems (real build)")
    print("[PASS] test_systems_entries_have_all_fields passed")


def test_tabs_page_with_the_page_controls(g):
    menu = GuideMenu(980, 620)
    for tab in TABS:
        menu.tab = tab
        menu.page = 0
        entries = _tab_entries(menu, tab)
        total = menu._total_pages()
        assert total == max(1, math.ceil(len(entries) / menu.rows_per_page)), (tab, total, len(entries), menu.rows_per_page)
        seen = []
        for _ in range(total):
            seen.extend(e["key"] for e in menu._page_entries())
            menu.on_key_press(pyglet.window.key.RIGHT)
        assert menu.page == 0, f"{tab}: RIGHT past the last page must wrap to page 1"
        assert seen == [e["key"] for e in entries], f"{tab}: pages must show every entry once, in order"
        btn_prev, btn_next = menu.btn_prev, menu.btn_next
        menu.on_mouse_press(btn_prev.x + btn_prev.width / 2, btn_prev.y + btn_prev.height / 2, pyglet.window.mouse.LEFT)
        assert menu.page == total - 1, f"{tab}: Prev from page 1 must wrap to the last page"
        menu.on_mouse_press(btn_next.x + btn_next.width / 2, btn_next.y + btn_next.height / 2, pyglet.window.mouse.LEFT)
        assert menu.page == 0, f"{tab}: Next must wrap back to page 1"
    print("[PASS] test_tabs_page_with_the_page_controls passed (all four tabs page with keys and buttons)")


def test_systems_tab_button_switches_tab(g):
    menu = GuideMenu(980, 620)
    btn = menu.btn_systems
    menu.on_mouse_press(btn.x + btn.width / 2, btn.y + btn.height / 2, pyglet.window.mouse.LEFT)
    assert menu.tab == "systems" and menu.page == 0, (menu.tab, menu.page)
    menu.draw()
    assert menu.subtitle.text.startswith("Hangar, achievements"), menu.subtitle.text
    print("[PASS] test_systems_tab_button_switches_tab passed (Systems button opens the tab)")


def test_tab_row_fits_panel_and_back_button():
    for width, height in ((980, 620), (1920, 1080)):
        menu = GuideMenu(width, height)
        tabs = [menu.btn_enemies, menu.btn_powerups, menu.btn_basics, menu.btn_systems]
        left = menu._panel.x
        right = menu._panel.x + menu._panel.width
        for b in tabs:
            assert b.x >= left and b.x + b.width <= right, f"tab {b.text} leaves the panel at {width}x{height}"
        for a, b in zip(tabs, tabs[1:]):
            assert a.x + a.width <= b.x, f"tabs {a.text} and {b.text} overlap at {width}x{height}"
        assert tabs[-1].x + tabs[-1].width < menu.btn_back.x, f"Systems tab overlaps Back at {width}x{height}"
    print("[PASS] test_tab_row_fits_panel_and_back_button passed (980x620 and 1920x1080)")


def test_rows_clear_tabs_controls_and_title(g):
    for width, height in ((980, 620), (1920, 1080)):
        menu = GuideMenu(width, height)
        tab_bottom = menu.btn_enemies.y
        controls_top = max(b.y + b.height for b in (menu.btn_prev, menu.btn_next))
        # Only the rows a page shows: rows past rows_per_page are hidden and sit below the nav strip on purpose.
        shown = menu._rows[: menu.rows_per_page]
        row_top = max(bg.y + bg.height for bg, *_ in shown)
        row_bottom = min(bg.y for bg, *_ in shown)
        assert row_top <= tab_bottom - 4, f"rows start above the tab row at {width}x{height}: {row_top} > {tab_bottom}"
        assert row_bottom >= controls_top + 6, f"visible rows run into Prev/Next at {width}x{height}: {row_bottom} < {controls_top}"
        panel_top = menu._panel.y + menu._panel.height
        title_bottom = menu.title.y - menu.title.content_height / 2
        assert title_bottom >= panel_top + 2, f"title crosses the panel border at {width}x{height}: {title_bottom} < {panel_top}"
    print("[PASS] test_rows_clear_tabs_controls_and_title passed (the visible rows fit between tabs and Prev/Next; title clears the border)")


def _row_overflows(menu):
    problems = []
    for row_index, entry in enumerate(menu._page_entries()):
        bg, _, _, _, _, _, name, desc, lore, _ = menu._rows[row_index]
        right = bg.x + bg.width - 14
        for label, field in ((name, "name"), (desc, "desc"), (lore, "lore")):
            if label.x + label.content_width > right:
                problems.append(f"{entry['key']}:{field} ({label.x + label.content_width:.0f} > {right:.0f})")
    return problems


def test_text_fits_rows(g):
    g.switch_to()
    fakes = _fake_modules()
    for width, height in ((980, 620), (1920, 1080)):
        menu = GuideMenu(width, height)
        menu.SYSTEMS_INFO = guide_info.systems_entries(fakes)
        problems = []
        for tab in TABS:
            menu.tab = tab
            for page in range(menu._total_pages()):
                menu.page = page
                menu.draw()
                problems += [f"{tab} p{page + 1} {p}" for p in _row_overflows(menu)]
        assert not problems, f"text overflows a row at {width}x{height}: {problems[:12]}"
    print("[PASS] test_text_fits_rows passed (every entry on every page fits its row at 980x620 and 1920x1080)")


def test_every_entry_has_all_fields_on_all_tabs():
    for tab in TABS:
        entries = _tab_entries(GuideMenu(980, 620), tab)
        _check_fields(entries, tab)
    print("[PASS] test_every_entry_has_all_fields_on_all_tabs passed")


def run_all():
    test_powerup_kinds_have_entries()
    test_powerup_kinds_known_to_game()
    test_elite_affixes_have_entries()
    test_enemy_entry_numbers_come_from_config()
    test_powerup_entry_numbers_come_from_config()
    test_ordinal_and_wave_schedule_text()
    test_game_code_reads_the_guide_constants()
    test_mutator_entries_from_definitions()
    test_skin_achievement_and_event_entries_from_definitions()
    test_systems_entries_have_all_fields()
    test_contract_mutator_ids_have_entries()
    test_real_skins_and_achievements_have_entries()
    test_real_events_have_entries()
    test_real_elite_affixes_in_level()
    # GuideMenu draws shapes and labels, so it needs a live GL context: run those inside a hidden window.
    g = Game()
    g.set_visible(False)
    try:
        test_every_entry_has_all_fields_on_all_tabs()
        test_tab_row_fits_panel_and_back_button()
        test_rows_clear_tabs_controls_and_title(g)
        test_tabs_page_with_the_page_controls(g)
        test_systems_tab_button_switches_tab(g)
        test_text_fits_rows(g)
    finally:
        g.close()
    print("\nALL WAVE 3 GUIDE TESTS PASSED")


if __name__ == "__main__":
    run_all()
