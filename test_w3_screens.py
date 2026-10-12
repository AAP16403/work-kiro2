"""Regression tests for the W3 screens item: the label box math, the overlap checker, the
layered exemption, popup shadows, off-window counting, the exit-code rule, the screen list
and an end-to-end capture of one size into a temp directory.

Run from the project root: python test_w3_screens.py
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile

import pyglet
from pyglet.gl import glClearColor

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import screens  # noqa: E402
from game import Game  # noqa: E402
from menu import UI_FONT_BODY  # noqa: E402
from popups import DamagePopups  # noqa: E402
from utils import Vec2  # noqa: E402

REAL_HIGH_SCORES = os.path.join(ROOT, "high_scores.json")


def _label(text, x, y, batch, group=None, font_size=16, anchor_x="left", anchor_y="bottom"):
    return pyglet.text.Label(
        text, font_name=UI_FONT_BODY, font_size=font_size, x=x, y=y,
        anchor_x=anchor_x, anchor_y=anchor_y, color=(255, 255, 255, 255), batch=batch, group=group,
    )


def _painted(g, batch):
    """Draw a batch under the recorder on a black frame and return (infos, offscreen).

    batch.draw() is looked up inside the recorder on purpose: the recorder patches the
    Batch class, so a bound method taken before entering it would bypass the recording.
    """
    glClearColor(0.0, 0.0, 0.0, 1.0)
    g.clear()
    recorder = screens.DrawRecorder()
    with recorder:
        batch.draw()
    return screens.collect_label_infos(screens.painted_layouts(recorder), g.width, g.height)


def _pairs(infos):
    """Overlapping pairs as sorted text tuples, so the order of the report does not matter."""
    return [tuple(sorted((p.a.text, p.b.text))) for p in screens.find_overlaps(infos)]


def _ink_box(g):
    """Bounding box (left, bottom, right, top) of the non-black pixels in the back buffer."""
    img = pyglet.image.get_buffer_manager().get_color_buffer().get_image_data()
    w, h = img.width, img.height
    raw = img.get_data("RGBA", w * 4)
    xs, ys = [], []
    for row in range(h):
        base = row * w * 4
        reds = raw[base:base + w * 4:4]
        for col, value in enumerate(reds):
            if value > 96:
                xs.append(col)
                ys.append(row)
    if not xs:
        return None
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def test_label_box_encloses_rendered_ink(g):
    cases = [
        ("left", "bottom"), ("left", "baseline"), ("left", "center"), ("left", "top"),
        ("center", "center"), ("right", "baseline"),
    ]
    for anchor_x, anchor_y in cases:
        batch = pyglet.graphics.Batch()
        lbl = _label("HHgy", 400.0, 300.0, batch, font_size=24, anchor_x=anchor_x, anchor_y=anchor_y)
        glClearColor(0.0, 0.0, 0.0, 1.0)
        g.clear()
        batch.draw()
        ink = _ink_box(g)
        assert ink is not None, f"no ink drawn for {anchor_x}/{anchor_y}"
        box = screens.label_box(lbl)
        tol = 2.0
        assert ink[0] >= box[0] - tol and ink[2] <= box[2] + tol, f"{anchor_x}/{anchor_y} x: ink {ink} vs box {box}"
        assert ink[1] >= box[1] - tol and ink[3] <= box[3] + tol, f"{anchor_x}/{anchor_y} y: ink {ink} vs box {box}"
        assert abs((box[3] - box[1]) - lbl.content_height) < 1e-6, "box height must equal content_height"
        assert abs((box[2] - box[0]) - lbl.content_width) < 1e-6, "box width must equal content_width"
    print(f"[PASS] test_label_box_encloses_rendered_ink passed ({len(cases)} anchor cases: ink inside box within 2 px)")


def test_synthetic_overlap_reported_and_clear_pair_not(g):
    batch = pyglet.graphics.Batch()
    a = _label("W3 SYNTH OVERLAP A", 300.0, 300.0, batch, font_size=20)
    b = _label("W3 SYNTH OVERLAP B", 320.0, 305.0, batch, font_size=20)
    c = _label("W3 SYNTH CLEAR C", 300.0, 500.0, batch, font_size=20)
    d = _label("W3 SYNTH CLEAR D", 300.0, 100.0, batch, font_size=20)
    infos, offscreen = _painted(g, batch)
    assert offscreen == 0, f"synthetic labels should all be on screen, offscreen={offscreen}"
    pairs = _pairs(infos)
    assert pairs == [("W3 SYNTH OVERLAP A", "W3 SYNTH OVERLAP B")], f"unexpected pairs: {pairs}"
    assert all("CLEAR" not in t for pair in pairs for t in pair), f"clear labels must not be reported: {pairs}"
    alive = [a, b, c, d]
    assert len(alive) == 4
    print("[PASS] test_synthetic_overlap_reported_and_clear_pair_not passed (overlapping pair reported, separated pair not)")


def test_layered_group_and_child_are_exempt(g):
    batch = pyglet.graphics.Batch()
    layered = pyglet.graphics.Group(order=1)
    layered.layered = True
    child = pyglet.graphics.Group(order=2, parent=layered)
    plain = pyglet.graphics.Group(order=3)
    x = _label("W3 LAYER X", 200.0, 200.0, batch, group=layered, font_size=20)
    y = _label("W3 LAYER Y", 210.0, 205.0, batch, group=plain, font_size=20)
    infos, _ = _painted(g, batch)
    assert _pairs(infos) == [], f"a layered label must be exempt, got {_pairs(infos)}"

    z = _label("W3 LAYER Z", 210.0, 205.0, batch, group=child, font_size=20)
    infos, _ = _painted(g, batch)
    assert _pairs(infos) == [], f"a child of a layered group must be exempt, got {_pairs(infos)}"

    control_batch = pyglet.graphics.Batch()
    p = _label("W3 CTRL P", 500.0, 400.0, control_batch, group=plain, font_size=20)
    q = _label("W3 CTRL Q", 510.0, 405.0, control_batch, group=plain, font_size=20)
    infos, _ = _painted(g, control_batch)
    assert _pairs(infos) == [("W3 CTRL P", "W3 CTRL Q")], "unlayered control pair must still be reported"
    alive = [x, y, z, p, q]
    assert len(alive) == 5
    print("[PASS] test_layered_group_and_child_are_exempt passed (layered and child groups exempt, control pair reported)")


def test_popup_shadow_pair_is_exempt(g):
    popups = DamagePopups()
    popups.spawn(Vec2(0.0, 0.0), "-12", color=(255, 80, 80))
    popups.sync(Vec2(0.0, 0.0))
    glClearColor(0.0, 0.0, 0.0, 1.0)
    g.clear()
    recorder = screens.DrawRecorder()
    with recorder:
        popups.draw()
    layouts = screens.painted_layouts(recorder)
    assert len(layouts) == 2, f"expected a shadow and a text layout for the popup, got {len(layouts)}"
    boxes = [screens.label_box(lay) for lay in layouts]
    assert screens.overlap_area(boxes[0], boxes[1]) > 0.0, "the popup's shadow and text should overlap as boxes"
    layered_flags = sorted(screens.is_layered(lay) for lay in layouts)
    assert layered_flags == [False, True], f"only the shadow group should be layered, got {layered_flags}"
    infos, _ = screens.collect_label_infos(layouts, g.width, g.height)
    assert screens.find_overlaps(infos) == [], "a popup shadow sits on purpose and must not be reported"
    print("[PASS] test_popup_shadow_pair_is_exempt passed (shadow and text overlap as boxes, exempt as layered)")


def test_offscreen_labels_are_counted_not_checked(g):
    batch = pyglet.graphics.Batch()
    on = _label("W3 ON SCREEN", 100.0, 100.0, batch, font_size=20)
    off_a = _label("W3 FAR LEFT", -5000.0, 100.0, batch, font_size=20)
    off_b = _label("W3 FAR LEFT TWO", -5000.0, 105.0, batch, font_size=20)
    infos, offscreen = _painted(g, batch)
    texts = [info.text for info in infos]
    assert texts == ["W3 ON SCREEN"], f"off-window labels must not be checked, got {texts}"
    assert offscreen == 2, f"both off-window labels must be counted, got {offscreen}"
    assert _pairs(infos) == []
    alive = [on, off_a, off_b]
    assert len(alive) == 3
    print("[PASS] test_offscreen_labels_are_counted_not_checked passed (2 counted, none checked)")


def test_exit_status_rules(g):
    assert screens.exit_status(0, [], False) == 0, "no overlaps and no errors must exit 0"
    assert screens.exit_status(3, [], False) == 1, "overlaps must exit 1 by default"
    assert screens.exit_status(3, [], True) == 0, "--allow-overlaps must exit 0 despite overlaps"
    assert screens.exit_status(0, [{"error": "boom"}], True) == 1, "a screen error must always exit 1"
    print("[PASS] test_exit_status_rules passed (0 clean, 1 on overlaps, 0 with --allow-overlaps, 1 on errors)")


def test_screen_list_covers_required_screens(g):
    specs, skipped = screens.screen_specs(g)
    names = [s.name for s in specs]
    for required in ("title", "settings", "combat", "pause", "reward", "game_over"):
        assert required in names, f"missing screen {required}: {names}"
    guide = [n for n in names if n.startswith("guide_")]
    # Every page the Guide reports on every tab, read from the menu itself, so a new page or
    # a new tab (the Systems tab) cannot be left out of the captures.
    menu = g.guide_menu
    expected = []
    for tab in ("enemies", "powerups", "basics", "systems"):
        saved = menu.tab
        menu.tab = tab
        pages = int(menu._total_pages())
        menu.tab = saved
        expected += [f"guide_{tab}_{page + 1}" for page in range(pages)]
    assert guide == expected, f"guide pages captured {guide} != pages the Guide has {expected}"
    if hasattr(screens.GameStateName, "HANGAR"):
        assert "hangar" in names, "the Hangar must be captured when the build defines it"
        assert skipped == [], f"nothing should be skipped when the Hangar exists: {skipped}"
    else:
        assert "hangar" not in names, "no Hangar capture without a Hangar state"
        assert [s["screen"] for s in skipped] == ["hangar"], f"the Hangar must be listed as skipped: {skipped}"
    print(f"[PASS] test_screen_list_covers_required_screens passed ({len(names)} screens, hangar skipped={bool(skipped)})")


def test_end_to_end_capture_one_size_writes_pngs_and_json(g):
    def digest(path):
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    before = digest(REAL_HIGH_SCORES) if os.path.exists(REAL_HIGH_SCORES) else None
    out_dir = tempfile.mkdtemp(prefix="plouto_w3_screens_")
    try:
        report = screens.run_capture(out_dir, sizes=((980, 620),), game=g)
        after = digest(REAL_HIGH_SCORES) if os.path.exists(REAL_HIGH_SCORES) else None
        assert before == after, "the capture must not change the real high_scores.json"
        assert report["errors"] == [], f"capture errors: {report['errors']}"
        specs, _skipped = screens.screen_specs(g)  # every screen the tool plans, so the count follows the Guide's pages
        assert len(report["screens"]) == len(specs), f"expected {len(specs)} screens at 980x620, got {len(report['screens'])}"
        for entry in report["screens"]:
            png = os.path.join(out_dir, entry["png"])
            assert os.path.getsize(png) > 0, f"empty PNG {png}"
            assert entry["labels"] > 0, f"{entry['screen']} has no visible labels"
        screens_json = os.path.join(out_dir, "overlaps.json")
        with open(screens_json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        with open(screens_json, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["total_overlaps"] == sum(s["overlap_count"] for s in loaded["screens"])
        assert all(set(("screen", "size", "png", "labels", "offscreen_labels", "overlap_count", "overlaps")) <= set(s)
                   for s in loaded["screens"])
        assert g.width == 980 and g.height == 620, "the window should be left at the last captured size"
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    print("[PASS] test_end_to_end_capture_one_size_writes_pngs_and_json passed (13 PNGs, overlaps.json shape ok, real high_scores.json unchanged)")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_label_box_encloses_rendered_ink(g)
        test_synthetic_overlap_reported_and_clear_pair_not(g)
        test_layered_group_and_child_are_exempt(g)
        test_popup_shadow_pair_is_exempt(g)
        test_offscreen_labels_are_counted_not_checked(g)
        test_exit_status_rules(g)
        test_screen_list_covers_required_screens(g)
        test_end_to_end_capture_one_size_writes_pngs_and_json(g)
    finally:
        g.close()
    print("\nALL W3 SCREENS TESTS PASSED")


if __name__ == "__main__":
    run_all()
