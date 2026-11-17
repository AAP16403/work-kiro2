"""Wave-8 neon-obsidian tests: two pod skins that unlock by play.

Neon Surge Pod unlocks at a best wave of 15 (UnlockRule "wave"). Obsidian Pod unlocks at a best score of
20,000 in one run (UnlockRule "score"). The tests cover:

- palette completeness: every skin palette holds exactly the PALETTE_KEYS, as RGB bytes;
- palette readability: the body and the glow hold at least 3:1 contrast against the arena floor and the
  Hangar card plate, and the eye (the outline and pupils) holds 3:1 against the body;
- the unlock rules, the hints, and the unlock through a finished run (progress.end_run);
- selection driving the next run's look (hull, shots and dash), and locked choices being refused;
- each palette rendering in the Hangar preview (pixels drawn with the skin's body colour);
- the locked, unlocked and selected card states, with a temp progress file;
- config.ENABLE_NEON_OBSIDIAN = False hiding both skins from the Hangar, the Guide and selection.

Every test points progress.PROGRESS_FILE at a temp file, so the real progress.json is never read or written.
Run with the venv python from the project root: python test_w8_neon-obsidian.py
"""

import importlib
import math
import os
import shutil
import tempfile

import pyglet
from pyglet import gl

import achievements
import config
import guide_info
import hangar
import progress
import skins
import skin_preview
import ui_theme
from game import Game
from player_art import DEFAULT_PALETTE
from skin_apply import PALETTE_KEYS, complete_palette, read_run_skin
from states import GameStateName
from utils import Vec2

NEW_IDS = ("neon_surge", "obsidian")
ORIGINAL_IDS = ("classic", "ember", "frost", "verdant", "solar", "storm", "void", "neon", "crimson", "ghost")
CONTRAST_MIN = 3.0   # WCAG 1.4.11 non-text contrast: the parts a player must see against the floor and the card
DISTINCT_MIN = 30.0  # RGB distance: a skin's body must not read as another skin's body
PIXEL_TOL = 6        # per-channel tolerance when counting pixels of one colour in a rendered card
# The arena floor as the player sees it. map.py draws config.FLOOR_MAIN, and the lit frame reads (42, 50, 61):
# this was sampled from an in-run capture at 980x620 (wave 1, calm frame, the pod at the centre). The lit value is
# the stricter floor, because lighting only ever brightens it. config.FLOOR_MAIN is checked too.
ARENA_FLOOR_LIT = (42, 50, 61)
DASH_LEGACY = (160, 220, 255)

_ORIGINAL_PROGRESS_FILE = progress.PROGRESS_FILE
_TEMP_DIRS: list[str] = []


# ---------------------------------------------------------------- helpers

def _lum(color) -> float:
    """WCAG relative luminance of an (r, g, b) colour."""
    def channel(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(float(c)) for c in color[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b) -> float:
    """WCAG contrast ratio between two colours, 1.0 to 21.0."""
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _distance(a, b) -> float:
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a[:3], b[:3])))


def _rgb(shape):
    return tuple(int(c) for c in shape.color[:3])


def _temp_progress(**fields) -> str:
    """Write a progress record made from the defaults plus ``fields`` to a temp file, and point the game at it."""
    folder = tempfile.mkdtemp(prefix="w8_neon_obsidian_")
    _TEMP_DIRS.append(folder)
    path = os.path.join(folder, "progress.json")
    data = progress.default_progress()
    data.update(fields)
    skins.refresh_unlocks(data)
    assert progress.save(data, path), "the temp progress file must be writable"
    progress.PROGRESS_FILE = path
    return path


def _menu(path):
    menu = hangar.HangarMenu(980, 620, progress_path=path)
    menu.open()
    return menu


def _start(g):
    """Start a run the way the title screen does: build the run, then enter play."""
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)


def _hull(g):
    g.visuals.sync_player(g.player, Vec2(0.0, 0.0), t=0.0)
    return _rgb(g.visuals._player_art.body)


def _bullet_colours(g):
    """(head colour, first trail colour) for a plain player shot, as the run's visuals draw it."""
    from projectile import Projectile
    shot = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(400.0, 0.0), damage=10, owner="player", projectile_type="bullet")
    g.visuals.ensure_projectile(shot)
    pv = g.visuals._proj_handles[id(shot)]
    body = _rgb(pv._body)
    trail = _rgb(pv._trail[0]) if pv._trail else None
    g.visuals.drop_projectile(shot)
    return body, trail


def _dash_colours(g):
    before = len(g.particle_system.particles)
    g._dash()
    return [tuple(int(c) for c in p.color[:3]) for p in g.particle_system.particles[before:]]


def _check_run_look(g, sid):
    """A run must draw this skin's hull, plain shot head and trail, and dash colour."""
    skin = skins.get(sid)
    pal = complete_palette(skin.palette)
    assert g.run_skin.skin_id == sid, f"the run should use '{sid}', got '{g.run_skin.skin_id}'"
    assert g.visuals.player_palette == pal, f"{sid}: visuals palette is not the skin's"
    hull = _hull(g)
    assert hull == pal["body"], f"{sid}: hull {hull} should be {pal['body']}"
    head, trail = _bullet_colours(g)
    assert head == pal["bullet"], f"{sid}: shot head {head} should be {pal['bullet']}"
    assert trail == pal["trail"], f"{sid}: shot trail {trail} should be {pal['trail']}"
    dash = _dash_colours(g)
    assert dash and all(c == pal["trail"] for c in dash), f"{sid}: dash colours {dash} should be {pal['trail']}"


def _texts(menu):
    return [getattr(c, "text", None) for c in menu._content]


# ---------------------------------------------------------------- catalogue

def test_catalogue_lists_both_new_skins_after_the_originals():
    assert config.ENABLE_NEON_OBSIDIAN is True, "the switch ships on"
    ids = list(skins.SKINS)
    assert len(ids) == len(set(ids)), f"skin ids must be unique: {ids}"
    assert tuple(ids) == ORIGINAL_IDS + NEW_IDS, f"catalogue order is {ids}"
    assert skins.get("neon_surge").name == "Neon Surge Pod"
    assert skins.get("obsidian").name == "Obsidian Pod"
    print(f"[PASS] test_catalogue_lists_both_new_skins_after_the_originals passed ({len(ids)} skins, new ids last)")


def test_palettes_are_complete():
    for sid in NEW_IDS:
        skin = skins.get(sid)
        assert set(skin.palette) == set(PALETTE_KEYS), f"{sid}: palette keys {sorted(skin.palette)} != {sorted(PALETTE_KEYS)}"
        for key, value in skin.palette.items():
            assert isinstance(value, tuple) and len(value) == 3, f"{sid}.{key} must be an (r, g, b) tuple, got {value!r}"
            assert all(isinstance(c, int) and 0 <= c <= 255 for c in value), f"{sid}.{key} has a value outside 0..255: {value!r}"
        assert complete_palette(skin.palette) == dict(skin.palette), f"{sid}: complete_palette must add nothing"
    assert set(PALETTE_KEYS) == set(DEFAULT_PALETTE), "the palette keys are the default palette's keys"
    print(f"[PASS] test_palettes_are_complete passed ({', '.join(NEW_IDS)}: all {len(PALETTE_KEYS)} keys, RGB bytes)")


def test_palettes_read_against_the_floor():
    report = []
    for sid in NEW_IDS:
        pal = skins.get(sid).palette
        body_floor = _contrast(pal["body"], ARENA_FLOOR_LIT)
        body_base = _contrast(pal["body"], config.FLOOR_MAIN)
        body_card = _contrast(pal["body"], ui_theme.BG)
        glow_floor = _contrast(pal["glow"], ARENA_FLOOR_LIT)
        eye_body = _contrast(pal["eye"], pal["body"])
        assert body_floor >= CONTRAST_MIN, f"{sid}: body on the lit arena floor is {body_floor:.2f}:1, need {CONTRAST_MIN}:1"
        assert body_base >= CONTRAST_MIN, f"{sid}: body on config.FLOOR_MAIN is {body_base:.2f}:1, need {CONTRAST_MIN}:1"
        assert body_card >= CONTRAST_MIN, f"{sid}: body on the Hangar card plate is {body_card:.2f}:1, need {CONTRAST_MIN}:1"
        assert glow_floor >= CONTRAST_MIN, f"{sid}: halo on the lit arena floor is {glow_floor:.2f}:1, need {CONTRAST_MIN}:1"
        assert eye_body >= CONTRAST_MIN, f"{sid}: eye and outline on the body are {eye_body:.2f}:1, need {CONTRAST_MIN}:1"
        report.append(f"{sid} body {body_floor:.1f}:1 lit floor, halo {glow_floor:.1f}:1, eye {eye_body:.1f}:1 on body")
    print(f"[PASS] test_palettes_read_against_the_floor passed ({'; '.join(report)})")


def test_bodies_are_distinct_from_every_skin():
    for sid in NEW_IDS:
        body = skins.get(sid).palette["body"]
        for other in skins.SKINS.values():
            if other.id == sid:
                continue
            gap = _distance(body, other.palette["body"])
            assert gap >= DISTINCT_MIN, f"{sid} body is {gap:.0f} from {other.id}'s body, need {DISTINCT_MIN:.0f}"
    print(f"[PASS] test_bodies_are_distinct_from_every_skin passed (body distance >= {DISTINCT_MIN:.0f} from every other skin)")


# ---------------------------------------------------------------- unlock rules

def test_neon_surge_unlock_rule_is_best_wave_15():
    skin = skins.get("neon_surge")
    assert skin.unlock.kind == "wave" and skin.unlock.value == 15, f"rule is {skin.unlock}"
    assert config.NEON_SURGE_UNLOCK_WAVE == 15, "the threshold lives in config and reads 15"
    p = progress.default_progress()
    p["best_score"] = 999999  # a huge score does not unlock a wave skin
    assert skins.unlock_rule_met(skin, p) is False and skins.unlocked(p, "neon_surge") is False
    p["best_wave"] = 14
    assert skins.unlocked(p, "neon_surge") is False, "wave 14 is one short"
    p["best_wave"] = 15
    assert skins.unlocked(p, "neon_surge") is True, "reaching wave 15 unlocks it"
    assert skins.unlock_hint(skin) == "Reach wave 15", skins.unlock_hint(skin)
    print("[PASS] test_neon_surge_unlock_rule_is_best_wave_15 passed (wave 14 locked, wave 15 unlocked, hint 'Reach wave 15')")


def test_obsidian_unlock_rule_is_score_20000():
    skin = skins.get("obsidian")
    assert skin.unlock.kind == "score" and skin.unlock.value == 20000, f"rule is {skin.unlock}"
    assert config.OBSIDIAN_UNLOCK_SCORE == 20000, "the threshold lives in config and reads 20,000"
    p = progress.default_progress()
    p["best_wave"] = 99  # a long run without the score does not unlock a score skin
    assert skins.unlocked(p, "obsidian") is False
    p["best_score"] = 19999
    assert skins.unlocked(p, "obsidian") is False, "19,999 is one short"
    p["best_score"] = 20000
    assert skins.unlocked(p, "obsidian") is True, "a best score of 20,000 unlocks it"
    assert skins.unlock_hint(skin) == "Score 20,000 in one run", skins.unlock_hint(skin)
    print("[PASS] test_obsidian_unlock_rule_is_score_20000 passed (19,999 locked, 20,000 unlocked, hint 'Score 20,000 in one run')")


def test_unlock_happens_when_a_run_ends():
    folder = tempfile.mkdtemp(prefix="w8_neon_obsidian_")
    _TEMP_DIRS.append(folder)
    path = os.path.join(folder, "progress.json")
    progress.save(progress.default_progress(), path)

    short_run = achievements.RunStats()
    short_run.finish(score=4000, wave=14, survived=60.0)
    result = progress.end_run(short_run, path)
    assert "neon_surge" not in result["new_skins"] and "obsidian" not in result["new_skins"], result["new_skins"]

    wave_run = achievements.RunStats()
    wave_run.finish(score=4000, wave=15, survived=90.0)
    result = progress.end_run(wave_run, path)
    assert "neon_surge" in result["new_skins"], f"a wave 15 run must unlock Neon Surge Pod, got {result['new_skins']}"
    assert "obsidian" not in result["new_skins"], "4,000 points must not unlock Obsidian Pod"

    score_run = achievements.RunStats()
    score_run.finish(score=20000, wave=3, survived=40.0)
    result = progress.end_run(score_run, path)
    assert result["new_skins"].count("obsidian") == 1, f"a 20,000 point run must unlock Obsidian Pod, got {result['new_skins']}"

    again = progress.end_run(score_run, path)
    assert "obsidian" not in again["new_skins"], "an unlock is recorded once and never repeated"

    saved = progress.load(path)
    assert "neon_surge" in saved["unlocked_skins"] and "obsidian" in saved["unlocked_skins"], "unlocks are saved"
    print("[PASS] test_unlock_happens_when_a_run_ends passed (wave 14 and 4,000 points unlock nothing, wave 15 and 20,000 each unlock once and save)")


# ---------------------------------------------------------------- selection and the run

def test_selection_drives_the_next_run(g):
    path = _temp_progress(best_wave=15, best_score=20000)
    menu = _menu(path)
    for sid in NEW_IDS:
        assert menu.choose(sid), f"'{sid}' is unlocked and must be selectable"
        _start(g)
        _check_run_look(g, sid)
    assert menu.choose("classic"), "the default is always selectable"
    _start(g)
    assert g.run_skin.skin_id == "classic", "switching back to the default must reach the next run"
    print("[PASS] test_selection_drives_the_next_run passed (neon_surge and obsidian: hull, shots and dash follow the selection)")


def test_locked_new_skins_are_refused_and_the_run_stays_default(g):
    path = _temp_progress(best_wave=14, best_score=19999)  # both new skins stay locked
    menu = _menu(path)
    before = open(path, "rb").read()
    for sid in NEW_IDS:
        assert menu.choose(sid) is False, f"locked '{sid}' must be refused"
        assert "is locked" in menu._message, "the refusal must say why"
    assert open(path, "rb").read() == before, "refused choices must not write progress"
    _start(g)
    assert g.run_skin.skin_id == "classic", "a locked skin must not reach the run"

    tampered = progress.load(path)
    tampered["selected_skin"] = "neon_surge"  # a hand-edited save naming a locked skin
    progress.save(tampered, path)
    assert read_run_skin().is_default, "a locked new skin named in the save must not reach the run"
    print("[PASS] test_locked_new_skins_are_refused_and_the_run_stays_default passed (click refused, no write, tampered save -> default run)")


def test_run_picks_up_each_skin_palette_as_a_run_skin():
    for sid in NEW_IDS:
        path = _temp_progress(best_wave=15, best_score=20000)
        progress.PROGRESS_FILE = path
        loaded = progress.load(path)
        loaded["selected_skin"] = sid
        progress.save(loaded, path)
        run_skin = read_run_skin()
        assert run_skin.skin_id == sid and run_skin.palette == complete_palette(skins.get(sid).palette)
        assert run_skin.shot_palette == run_skin.palette and run_skin.dash_color == skins.get(sid).palette["trail"]
    print("[PASS] test_run_picks_up_each_skin_palette_as_a_run_skin passed (read_run_skin gives each skin's palette)")


# ---------------------------------------------------------------- the preview

def _read_hits(g, card, batch, pal_key_color, half=80):
    """Draw one character card on the BG colour and count pixels near ``pal_key_color`` in its region."""
    gl.glClearColor(ui_theme.BG[0] / 255.0, ui_theme.BG[1] / 255.0, ui_theme.BG[2] / 255.0, 1.0)
    g.clear()
    cx, cy = g.width // 2, g.height // 2
    card.place(cx, cy)
    card.update(0.5)
    batch.draw()
    buf = pyglet.image.get_buffer_manager().get_color_buffer().get_image_data()
    region = buf.get_region(cx - half, cy - half, 2 * half, 2 * half)
    data = region.get_data("RGBA", region.width * 4)
    r, gg, b = pal_key_color[:3]
    hits = 0
    for i in range(0, len(data), 4):
        if abs(data[i] - r) <= PIXEL_TOL and abs(data[i + 1] - gg) <= PIXEL_TOL and abs(data[i + 2] - b) <= PIXEL_TOL:
            hits += 1
    return hits


def test_each_palette_renders_in_the_preview(g):
    counts = []
    prev = bool(config.USE_PLAYER_ART)
    try:
        config.USE_PLAYER_ART = True
        for sid in NEW_IDS:
            skin = skins.get(sid)
            pal = complete_palette(skin.palette)
            batch = pyglet.graphics.Batch()
            card = skin_preview.CharacterPreview(batch, None, palette=skin.palette)
            assert card.uses_player_art, "with the switch on, the card draws the pod robot"
            assert card.palette == pal, f"{sid}: the card must hold the skin's palette"
            card.place(0.0, 0.0)
            card.update(0.5)  # the art takes its colours on the first pose, as the Hangar does each frame
            assert _rgb(card.art.body) == pal["body"], f"{sid}: the pod hull must take the body colour"
            hits = _read_hits(g, card, batch, pal["body"])
            assert hits >= 40, f"{sid}: only {hits} pixels in the hull colour were drawn on the card"
            counts.append(f"{sid} {hits} body px")
            card.delete()

        config.USE_PLAYER_ART = False
        for sid in NEW_IDS:
            skin = skins.get(sid)
            legacy = skin_preview.CharacterPreview(pyglet.graphics.Batch(), None, palette=skin.palette)
            assert not legacy.uses_player_art and legacy.legacy is not None, "with the switch off, the card draws the legacy ship"
            assert _rgb(legacy.legacy._shapes[4]) == complete_palette(skin.palette)["body"], f"{sid}: legacy hull must be the skin body"
            legacy.delete()
    finally:
        config.USE_PLAYER_ART = prev
    print(f"[PASS] test_each_palette_renders_in_the_preview passed (pod card pixels in the hull colour: {', '.join(counts)}; legacy hulls match)")


def test_card_states_locked_unlocked_selected(g):
    progress_fields = {
        "neon_surge": dict(best_wave=14),
        "obsidian": dict(best_score=19999),
    }
    for sid in NEW_IDS:
        unlock_fields = {"best_wave": 15} if sid == "neon_surge" else {"best_score": 20000}
        path = _temp_progress(**progress_fields[sid])
        menu = _menu(path)
        hint = menu._unlock_text[sid]
        assert menu._card_state(sid) == "locked", f"{sid} should show LOCKED before its rule is met"
        texts = _texts(menu)
        assert "LOCKED" in texts and hint in texts, f"{sid}: the locked card must show its LOCKED chip and '{hint}'"

        path = _temp_progress(**unlock_fields)
        menu = _menu(path)
        assert menu._card_state(sid) == "unlocked", f"{sid} should show UNLOCKED once its rule is met"
        assert "UNLOCKED" in _texts(menu), f"{sid}: the unlocked card must show the UNLOCKED chip"

        assert menu.choose(sid), f"'{sid}' is unlocked and must be selectable"
        menu._rebuild()  # the Hangar's click and ENTER paths rebuild after a successful choice
        assert menu._card_state(sid) == "selected", f"{sid} should show SELECTED after choosing it"
        assert "SELECTED" in _texts(menu), f"{sid}: the chosen card must show the SELECTED chip"
        _start(g)
        _check_run_look(g, sid)
    print("[PASS] test_card_states_locked_unlocked_selected passed (each new card: LOCKED with its hint, UNLOCKED once met, SELECTED after a choice)")


def test_card_palettes_match_their_skin(g):
    path = _temp_progress(best_wave=15, best_score=20000)
    menu = _menu(path)
    menu.update(0.1)
    for sid in NEW_IDS:
        card = menu._previews[sid]
        assert card.uses_player_art, "with config.USE_PLAYER_ART on, the card draws the pod robot"
        assert card.palette == complete_palette(skins.get(sid).palette), f"card '{sid}' palette differs from its skin"
        assert _rgb(card.art.body) == skins.get(sid).palette["body"], f"card '{sid}' hull is not the skin's body colour"
    print("[PASS] test_card_palettes_match_their_skin passed (both new cards draw their own palette)")


def test_switch_off_hides_both_skins():
    path = _temp_progress(best_wave=30, best_score=30000, selected_skin="obsidian", unlocked_skins=["obsidian"])
    saved = config.ENABLE_NEON_OBSIDIAN
    config.ENABLE_NEON_OBSIDIAN = False
    try:
        importlib.reload(skins)
        assert tuple(skins.SKINS) == ORIGINAL_IDS, f"with the switch off the catalogue is {tuple(skins.SKINS)}"
        assert skins.get("neon_surge") is None and skins.get("obsidian") is None, "both new skins must be hidden"

        data = progress.load(path)
        assert skins.refresh_unlocks(data) == [], "no hidden skin is recorded as unlocked"
        assert skins.selected(data).id == skins.DEFAULT_SKIN_ID, "a saved hidden selection falls back to the default"
        assert skins.select(data, "obsidian") is False, "a hidden skin cannot be selected"
        assert read_run_skin(data).is_default, "a saved hidden selection gives the default run look"

        menu = hangar.HangarMenu(980, 620, progress_path=path)
        menu.open()
        assert not set(NEW_IDS) & set(menu.skin_ids), f"the Hangar lists {menu.skin_ids}"
        assert len(menu.skin_ids) == len(ORIGINAL_IDS), f"the Hangar shows {len(menu.skin_ids)} cards"

        guide_keys = {e["key"] for e in guide_info.skin_entries(skins)}
        assert not {f"skin_{sid}" for sid in NEW_IDS} & guide_keys, "the Guide must not list hidden skins"
    finally:
        config.ENABLE_NEON_OBSIDIAN = saved
        importlib.reload(skins)
    assert set(NEW_IDS) <= set(skins.SKINS), "the skins return when the switch is back on"
    print("[PASS] test_switch_off_hides_both_skins passed (catalogue, Hangar, Guide and selection drop both; switch back on restores them)")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_catalogue_lists_both_new_skins_after_the_originals()
        test_palettes_are_complete()
        test_palettes_read_against_the_floor()
        test_bodies_are_distinct_from_every_skin()
        test_neon_surge_unlock_rule_is_best_wave_15()
        test_obsidian_unlock_rule_is_score_20000()
        test_unlock_happens_when_a_run_ends()
        test_selection_drives_the_next_run(g)
        test_locked_new_skins_are_refused_and_the_run_stays_default(g)
        test_run_picks_up_each_skin_palette_as_a_run_skin()
        test_each_palette_renders_in_the_preview(g)
        test_card_states_locked_unlocked_selected(g)
        test_card_palettes_match_their_skin(g)
        test_switch_off_hides_both_skins()  # last: it reloads skins.py
    finally:
        g.close()
        progress.PROGRESS_FILE = _ORIGINAL_PROGRESS_FILE
        for folder in _TEMP_DIRS:
            shutil.rmtree(folder, ignore_errors=True)
    print("\nALL WAVE 8 NEON-OBSIDIAN TESTS PASSED")


if __name__ == "__main__":
    run_all()
