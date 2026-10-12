#!/usr/bin/env python3
"""Screen capture suite and label overlap checker for PLOUTO.

Runs the real game in a hidden window, puts it on each screen in turn, reads the
back buffer back as a PNG, and checks the text on that frame for overlaps.

Screens, each captured at 980x620 and 1920x1080:
    title, settings, guide_<tab>_<page> (every guide page), combat, pause,
    reward, game_over, and hangar when the build defines GameStateName.HANGAR.
    A screen that this build cannot show is listed under "skipped".

Overlap checker
    A label counts when it was painted during that frame (its batch or one of its
    vertex lists went through a draw call), it has visible=True and opacity > 0,
    and it has text. Each counted label gets a box from content_width and
    content_height, placed with its x, y, anchor_x and anchor_y the way pyglet
    places it. Two boxes overlap when they share more than OVERLAP_EPS (1 px) on
    both axes. A pair is exempt when either label sits in a group, or a child of
    a group, whose 'layered' attribute is truthy: such a label is drawn over
    another one on purpose. Labels wholly outside the window are not checked;
    they are counted as offscreen_labels so clipped text still shows in the report.

Usage (any working directory):
    python tools/screens.py --out <dir> [--allow-overlaps]

Output in <dir>:
    <W>x<H>/<screen>.png   one PNG per screen per size
    overlaps.json          {sizes, overlap_eps_px, allow_overlaps, total_overlaps,
                           screens, skipped, errors}
                           screens[]: {screen, size, png, labels, offscreen_labels,
                           overlap_count, overlaps: [{a: {text, box}, b: {text, box}, area}]}
                           box is [left, bottom, right, top] in window pixels.
                           errors[]: {size, screen, error, traceback}

Exit status: 0 when every screen captured and there are no overlaps (or
--allow-overlaps is given); 1 otherwise.

The Game Over screen writes a high score. This tool points the score file at a
temp directory for the whole run, so the real high_scores.json is never touched.
"""

import argparse
import gc
import json
import os
import random
import shutil
import sys
import tempfile
import traceback
from functools import partial

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pyglet  # noqa: E402

pyglet.options["shadow_window"] = False

import config  # noqa: E402
import score as score_mod  # noqa: E402
from game import Game  # noqa: E402
from pyglet.graphics import Batch  # noqa: E402
from pyglet.text.layout import TextLayout  # noqa: E402
from states import GameStateName  # noqa: E402

SIZES = ((980, 620), (1920, 1080))
OVERLAP_EPS = 1.0
GUIDE_TABS = ("enemies", "powerups", "basics")
SEED = 1729
FRAME = 1.0 / 60.0
SETTLE_FRAMES = 30
COMBAT_SECONDS = 4.0
REWARD_SETTLE_SECONDS = 2.0
TEXT_PREVIEW = 60


# ----------------------------------------------------------------------------
# Label geometry
# ----------------------------------------------------------------------------
def _horizontal_span(layout, x: float, content_w: float) -> tuple[float, float]:
    """Left and right edge of the layout, mirroring pyglet's _get_left_anchor."""
    anchor_w = content_w
    if getattr(layout, "multiline", False) and getattr(layout, "_wrap_lines", False) and layout.width:
        anchor_w = float(layout.width)
    anchor_x = layout.anchor_x
    if anchor_x == "left":
        left = x
    elif anchor_x == "center":
        left = x - int(anchor_w) // 2
    elif anchor_x == "right":
        left = x - anchor_w
    else:
        raise ValueError(f"unknown anchor_x {anchor_x!r}")
    return left, left + content_w


def _vertical_span(layout, y: float, content_h: float) -> tuple[float, float]:
    """Bottom and top edge of the layout, mirroring pyglet's _get_top/_get_bottom_anchor.

    Single-line 'center' and 'baseline' use the font ascent and descent that pyglet
    keeps on the layout. When those are missing, a 0.75 ascent ratio stands in.
    """
    ascent = getattr(layout, "_ascent", None)
    descent = getattr(layout, "_descent", None)
    anchor_y = layout.anchor_y
    single_line = getattr(layout, "_line_count", 1) == 1 and layout.height is None
    h = content_h
    if anchor_y == "bottom":
        top_rel, bottom_rel = h, 0.0
    elif anchor_y == "top":
        top_rel, bottom_rel = 0.0, -h
    elif anchor_y == "center":
        if single_line and ascent is not None and descent is not None:
            top_rel = ascent // 2 - descent // 4
            bottom_rel = top_rel - h
        else:
            top_rel = h // 2
            bottom_rel = -(h // 2)
    elif anchor_y == "baseline":
        top_rel = ascent if ascent is not None else 0.75 * h
        bottom_rel = top_rel - h
    else:
        raise ValueError(f"unknown anchor_y {anchor_y!r}")
    return y + bottom_rel, y + top_rel


def label_box(layout) -> tuple[float, float, float, float]:
    """Window-pixel box (left, bottom, right, top) of a pyglet text layout."""
    content_w = float(layout.content_width)
    content_h = float(layout.content_height)
    left, right = _horizontal_span(layout, float(layout.x), content_w)
    bottom, top = _vertical_span(layout, float(layout.y), content_h)
    return left, bottom, right, top


def is_layered(layout) -> bool:
    """True when the layout's group, or any parent group, is marked layered."""
    group = getattr(layout, "group", None)
    while group is not None:
        if getattr(group, "layered", False):
            return True
        group = getattr(group, "parent", None)
    return False


def overlap_area(a, b, eps: float = OVERLAP_EPS) -> float:
    """Shared area of two boxes, or 0.0 unless they overlap by more than eps on both axes."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= eps or height <= eps:
        return 0.0
    return width * height


class LabelInfo:
    __slots__ = ("text", "box", "layered")

    def __init__(self, text: str, box: tuple, layered: bool):
        self.text = text
        self.box = box
        self.layered = layered


class Overlap:
    __slots__ = ("a", "b", "area")

    def __init__(self, a: LabelInfo, b: LabelInfo, area: float):
        self.a = a
        self.b = b
        self.area = area


def find_overlaps(infos: list[LabelInfo], eps: float = OVERLAP_EPS) -> list[Overlap]:
    """Every pair of boxes that overlap, skipping pairs where either label is layered."""
    pairs: list[Overlap] = []
    for i, a in enumerate(infos):
        if a.layered:
            continue
        for b in infos[i + 1:]:
            if b.layered:
                continue
            area = overlap_area(a.box, b.box, eps)
            if area > 0.0:
                pairs.append(Overlap(a, b, area))
    return pairs


def collect_label_infos(layouts, window_w: int, window_h: int) -> tuple[list[LabelInfo], int]:
    """Boxes for the layouts that carry text and fall at least partly inside the window.

    Returns (infos, offscreen): offscreen counts the texts that lie wholly outside the
    window. They are not checked for overlaps, but a count above zero means text is
    clipped on that screen, which the report shows.
    """
    infos: list[LabelInfo] = []
    offscreen = 0
    for layout in layouts:
        if layout.content_width <= 0 or layout.content_height <= 0:
            continue
        left, bottom, right, top = label_box(layout)
        if right <= 0 or left >= window_w or top <= 0 or bottom >= window_h:
            offscreen += 1
            continue
        infos.append(LabelInfo(str(getattr(layout, "text", "")), (left, bottom, right, top), is_layered(layout)))
    infos.sort(key=lambda info: (-info.box[3], info.box[0], info.text))
    return infos, offscreen


# ----------------------------------------------------------------------------
# Which labels were painted
# ----------------------------------------------------------------------------
class DrawRecorder:
    """Records the batches and vertex lists drawn while the context is active."""

    def __init__(self):
        self.batch_ids: set[int] = set()
        self.vertex_ids: set[int] = set()
        self._orig_draw = None
        self._orig_subset = None

    def __enter__(self):
        recorder = self
        orig_draw = Batch.draw
        orig_subset = Batch.draw_subset
        self._orig_draw = orig_draw
        self._orig_subset = orig_subset

        def draw(batch, *args, **kwargs):
            recorder.batch_ids.add(id(batch))
            return orig_draw(batch, *args, **kwargs)

        def draw_subset(batch, vertex_lists, *args, **kwargs):
            recorder.vertex_ids.update(id(v) for v in vertex_lists)
            return orig_subset(batch, vertex_lists, *args, **kwargs)

        Batch.draw = draw
        Batch.draw_subset = draw_subset
        return self

    def __exit__(self, exc_type, exc, tb):
        Batch.draw = self._orig_draw
        Batch.draw_subset = self._orig_subset
        return False


def _is_painted(layout, recorder: DrawRecorder) -> bool:
    if not layout.visible or layout.opacity <= 0:
        return False
    vertex_lists = getattr(layout, "_vertex_lists", None) or []
    if not vertex_lists:
        return False
    if id(getattr(layout, "_batch", None)) in recorder.batch_ids:
        return True
    return any(id(v) in recorder.vertex_ids for v in vertex_lists)


def painted_layouts(recorder: DrawRecorder) -> list:
    """Every live text layout that the recorded draw calls painted this frame.

    Layouts from replaced screens can still sit in cyclic garbage, where pyglet's weak
    references to their document are already gone. Those layouts were never painted,
    so an access error on one of them means "skip".
    """
    gc.collect()
    found = []
    for obj in gc.get_objects():
        try:
            if isinstance(obj, TextLayout) and _is_painted(obj, recorder):
                found.append(obj)
        except ReferenceError:
            continue
    return found


# ----------------------------------------------------------------------------
# Screens
# ----------------------------------------------------------------------------
class ScreenSpec:
    __slots__ = ("name", "setup")

    def __init__(self, name: str, setup):
        self.name = name
        self.setup = setup


def _settle(game, seconds: float) -> None:
    """Advance the normal update loop so menu and reward animations finish."""
    for _ in range(max(1, int(round(seconds / FRAME)))):
        game.update(FRAME)


def _show_menu(game) -> None:
    game.fsm.set_state(GameStateName.MENU)
    _settle(game, SETTLE_FRAMES * FRAME)


def _show_settings(game) -> None:
    game.fsm.set_state(GameStateName.SETTINGS)
    _settle(game, SETTLE_FRAMES * FRAME)


def _show_guide(game, tab: str, page: int) -> None:
    game.fsm.set_state(GameStateName.GUIDE)
    game.guide_menu.tab = tab
    game.guide_menu.page = page
    _settle(game, SETTLE_FRAMES * FRAME)


def _start_run(game, seconds: float = COMBAT_SECONDS) -> None:
    """Start a seeded run and let it play for a few seconds, without touching gameplay values."""
    random.seed(SEED)
    game._init_game()
    game.fsm.set_state(GameStateName.PLAYING)
    _settle(game, seconds)


def _show_combat(game) -> None:
    _start_run(game)


def _show_pause(game) -> None:
    _start_run(game)
    game.fsm.set_state(GameStateName.PAUSED)
    _settle(game, SETTLE_FRAMES * FRAME)


def _show_reward(game) -> None:
    _start_run(game)
    random.seed(SEED)
    game._roll_boss_rewards()
    game.fsm.set_state(GameStateName.BOSS_REWARD)
    _settle(game, REWARD_SETTLE_SECONDS)


def _show_game_over(game) -> None:
    _start_run(game)
    game.fsm.set_state(GameStateName.GAME_OVER)
    _settle(game, float(config.GAME_OVER_REVEAL_S) + 1.0)


def _guide_page_count(guide, tab: str) -> int:
    saved = guide.tab
    guide.tab = tab
    try:
        return int(guide._total_pages())
    finally:
        guide.tab = saved


def screen_specs(game) -> tuple[list[ScreenSpec], list[dict]]:
    """The screens to capture, in order, plus the ones this build cannot show."""
    specs = [
        ScreenSpec("title", partial(_show_menu, game)),
        ScreenSpec("settings", partial(_show_settings, game)),
    ]
    for tab in GUIDE_TABS:
        for page in range(_guide_page_count(game.guide_menu, tab)):
            specs.append(ScreenSpec(f"guide_{tab}_{page + 1}", partial(_show_guide, game, tab, page)))
    specs += [
        ScreenSpec("combat", partial(_show_combat, game)),
        ScreenSpec("pause", partial(_show_pause, game)),
        ScreenSpec("reward", partial(_show_reward, game)),
        ScreenSpec("game_over", partial(_show_game_over, game)),
    ]
    skipped: list[dict] = []
    hangar = getattr(GameStateName, "HANGAR", None)
    if hangar is None:
        skipped.append({"screen": "hangar", "reason": "this build defines no GameStateName.HANGAR"})
    else:
        specs.append(ScreenSpec("hangar", partial(game.fsm.set_state, hangar)))
    return specs, skipped


# ----------------------------------------------------------------------------
# Capture
# ----------------------------------------------------------------------------
def _apply_size(game, width: int, height: int) -> None:
    """Resize the hidden window. A windowed window is clamped to the work area, so a size that
    equals the display goes fullscreen instead, which stays hidden and keeps the exact size."""
    screen = pyglet.display.get_display().get_default_screen()
    if (width, height) == (int(screen.width), int(screen.height)):
        game.set_fullscreen(True)
    else:
        game.set_fullscreen(False)
        game.set_size(width, height)
    game.dispatch_events()
    game.on_resize(width, height)
    if (game.width, game.height) != (width, height):
        raise RuntimeError(f"window is {game.width}x{game.height}, wanted {width}x{height}")


def _capture_frame(game, png_path: str) -> tuple[list[LabelInfo], list[Overlap], int]:
    recorder = DrawRecorder()
    with recorder:
        game.on_draw()
    infos, offscreen = collect_label_infos(painted_layouts(recorder), game.width, game.height)
    overlaps = find_overlaps(infos)
    pyglet.image.get_buffer_manager().get_color_buffer().get_image_data().save(png_path)
    return infos, overlaps, offscreen


def _pair_json(pair: Overlap) -> dict:
    def side(info: LabelInfo) -> dict:
        return {"text": info.text[:TEXT_PREVIEW], "box": [round(v, 1) for v in info.box]}

    return {"a": side(pair.a), "b": side(pair.b), "area": round(pair.area, 1)}


def run_capture(out_dir: str, sizes=SIZES, game=None) -> dict:
    """Capture every screen at every size into out_dir and return the report dict."""
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="plouto_screens_")
    real_score_file = score_mod.HIGH_SCORE_FILE
    own_game = game is None
    report = {
        "sizes": [f"{w}x{h}" for w, h in sizes],
        "overlap_eps_px": OVERLAP_EPS,
        "screens": [],
        "skipped": [],
        "errors": [],
        "total_overlaps": 0,
    }
    try:
        score_mod.HIGH_SCORE_FILE = os.path.join(scratch, "high_scores.json")
        if own_game:
            game = Game()
        game.set_visible(False)
        specs, skipped = screen_specs(game)
        report["skipped"] = skipped
        for width, height in sizes:
            size_tag = f"{width}x{height}"
            size_dir = os.path.join(out_dir, size_tag)
            os.makedirs(size_dir, exist_ok=True)
            try:
                _apply_size(game, width, height)
            except Exception as exc:  # the window could not reach this size
                report["errors"].append({"size": size_tag, "screen": "*", "error": f"{type(exc).__name__}: {exc}"})
                continue
            for spec in specs:
                png_rel = f"{size_tag}/{spec.name}.png"
                try:
                    spec.setup()
                    infos, overlaps, offscreen = _capture_frame(game, os.path.join(out_dir, png_rel))
                except Exception as exc:
                    report["errors"].append({
                        "size": size_tag,
                        "screen": spec.name,
                        "error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(),
                    })
                    continue
                report["screens"].append({
                    "screen": spec.name,
                    "size": size_tag,
                    "png": png_rel,
                    "labels": len(infos),
                    "offscreen_labels": offscreen,
                    "overlap_count": len(overlaps),
                    "overlaps": [_pair_json(p) for p in overlaps],
                })
                report["total_overlaps"] += len(overlaps)
    finally:
        score_mod.HIGH_SCORE_FILE = real_score_file
        if own_game and game is not None:
            game.close()
        shutil.rmtree(scratch, ignore_errors=True)
    return report


def exit_status(total_overlaps: int, errors: list, allow_overlaps: bool) -> int:
    if errors:
        return 1
    if total_overlaps and not allow_overlaps:
        return 1
    return 0


def format_table(report: dict) -> str:
    rows = [f"{'size':<10}{'screen':<22}{'labels':>8}{'overlaps':>10}{'offscreen':>11}"]
    for entry in report["screens"]:
        rows.append(
            f"{entry['size']:<10}{entry['screen']:<22}{entry['labels']:>8}"
            f"{entry['overlap_count']:>10}{entry['offscreen_labels']:>11}"
        )
    for err in report["errors"]:
        rows.append(f"{err['size']:<10}{err['screen']:<22}  ERROR {err['error']}")
    for skip in report["skipped"]:
        rows.append(f"{'-':<10}{skip['screen']:<22}  SKIPPED {skip['reason']}")
    rows.append(
        f"{len(report['screens'])} screens captured, {len(report['errors'])} errors, "
        f"{report['total_overlaps']} overlapping label pairs"
    )
    return "\n".join(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Capture every PLOUTO screen and check labels for overlaps.")
    parser.add_argument("--out", required=True, help="directory for the PNGs and overlaps.json")
    parser.add_argument("--allow-overlaps", action="store_true", help="report overlaps but exit 0")
    args = parser.parse_args(argv)

    report = run_capture(args.out)
    report["allow_overlaps"] = bool(args.allow_overlaps)
    out_dir = os.path.abspath(args.out)
    with open(os.path.join(out_dir, "overlaps.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(format_table(report))
    print(f"wrote {os.path.join(out_dir, 'overlaps.json')}")
    return exit_status(report["total_overlaps"], report["errors"], args.allow_overlaps)


if __name__ == "__main__":
    sys.exit(main())
