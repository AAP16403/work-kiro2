"""The Hangar: browse and select skins with live previews, and review achievements.

Built on the wave-1 progress, skins, achievements, player_art and ui_theme modules. All colours,
panels and chips come from ui_theme. The cursor, paging and unlock wording live in hangar_rules.
states.HangarState builds this menu on the first visit, so the rest of the game does not import it.

Drawing layers, back to front: background, tab panel, cursor ring, tab content, chrome. Moving the
cursor only rebuilds the ring; text labels are rebuilt when the layout, tab, page or selection changes.
"""

from __future__ import annotations

from typing import Optional

import pyglet
from pyglet import shapes
from pyglet.graphics import Group

import achievements
import audio_cues
import skins
from hangar_rules import TAB_ACHIEVEMENTS, TAB_SKINS, describe_unlock, grid_step, page_step
from menu import MenuButton, UI_FONT_BODY, UI_FONT_HEAD, UI_FONT_META, _sync_label_style_if_ready, _ui_scale
from player import Player
from player_art import PlayerArt
import progress as meta_progress
from ui_theme import ACCENT, BG, DANGER, MUTED, PANEL, SUCCESS, TEXT, draw_panel, draw_tag, font_size
from utils import Vec2, to_iso


MESSAGE_SECONDS = 2.5
MIN_CARD_W = 200     # skin card width before UI scale; the grid uses as many columns as fit
CARD_MAX_H = 220     # cards stop growing taller than this, before UI scale
CARD_GAP = 14
ROW_H = 66           # achievement row height, before UI scale
ROW_GAP = 8
RIGHT_COL_W = 150    # achievement rows reserve this much width on the right for the chip and date
UI_MAX_SCALE = 1.25  # the panel stops growing here, like the field guide


def _rgba(color, alpha: int = 255) -> tuple:
    return (int(color[0]), int(color[1]), int(color[2]), int(alpha))


def _drop(objs) -> None:
    for obj in objs:
        if hasattr(obj, "delete"):
            obj.delete()


def _px(base: int, s: float) -> int:
    """Pixel size for a base size at the UI scale. The layout numbers below were tuned in these units."""
    return max(8, int(base * s))


def _name_size(name: str, font: str, base_px: int, max_w: float) -> int:
    """The largest size at or below base_px at which ``name`` fits max_w, never below 9 px."""
    size = base_px
    while size > 9:
        probe = pyglet.text.Label(name, font_name=font, font_size=size)
        width = float(probe.content_width)
        probe.delete()
        if width <= max_w:
            break
        size -= 1
    return size


def _ordered_skin_ids() -> list[str]:
    return list(skins.SKINS)  # catalogue order (dict insertion order): the default skin comes first


class HangarMenu:
    """Skins grid with live previews, plus the achievements gallery."""

    def __init__(self, width: int, height: int, progress_path: Optional[str] = None):
        self.screen_width = width
        self.screen_height = height
        self.progress_path = progress_path
        self.progress = meta_progress.load(progress_path)
        self.audio = None  # the game's audio manager, set by the Hangar state; cues are silent without it
        self.tab = TAB_SKINS
        self.cursor = 0
        self.ach_page = 0
        self._t = 0.0
        self._s = 1.0
        self._cols = 1
        self._page_count = 1
        self._message = ""
        self._message_color = MUTED
        self._message_left = 0.0

        self.skin_ids = _ordered_skin_ids()
        self._achievement_names = {a.id: a.name for a in achievements.ACHIEVEMENTS}
        self._unlock_text = {sid: describe_unlock(skins.get(sid), self._achievement_names) for sid in self.skin_ids}
        self._palettes = {sid: skins.get(sid).palette for sid in self.skin_ids}
        self._player = Player(pos=Vec2(0.0, 0.0))  # fixed character for every preview
        self._aim = Vec2(1.0, 0.0)

        self._bg_batch = pyglet.graphics.Batch()
        self._panel_batch = pyglet.graphics.Batch()
        self._ring_batch = pyglet.graphics.Batch()
        self._skin_batch = pyglet.graphics.Batch()
        self._ach_batch = pyglet.graphics.Batch()
        self._ui_batch = pyglet.graphics.Batch()
        self._art_group = Group(order=1)  # previews draw above the card plates
        self._panel_shapes: list = []     # tab panel, rebuilt with the tab
        self._ring_shapes: list = []      # cursor ring, rebuilt on cursor moves
        self._content: list = []          # cards or rows and their labels, rebuilt with the tab
        self._cards: list[tuple[float, float, float, float, str]] = []
        self._arts: dict[str, PlayerArt] = {}
        self._art_shakes: dict[str, Vec2] = {}
        self._area = (0.0, 0.0, 0.0, 0.0)
        self._panel_rect = (0.0, 0.0, 0.0, 0.0)

        self._bg = shapes.Rectangle(0, 0, width, height, color=BG, batch=self._bg_batch)

        self.title = self._label(self._ui_batch, "P L O U T O // HANGAR", 0, 0, 30, TEXT, font=UI_FONT_HEAD, anchor_x="center", anchor_y="center")
        self.subtitle = self._label(self._ui_batch, "", 0, 0, 13, MUTED, anchor_x="center", anchor_y="center")
        self.footer = self._label(self._ui_batch, "", 0, 0, 12, MUTED, anchor_x="center", anchor_y="center")

        self.btn_skins = MenuButton(0, 0, 150, 44, "Skins", lambda: None, color=PANEL, hover_color=ACCENT, text_color=_rgba(TEXT))
        self.btn_ach = MenuButton(0, 0, 190, 44, "Achievements", lambda: None, color=PANEL, hover_color=ACCENT, text_color=_rgba(TEXT))
        self.btn_prev = MenuButton(0, 0, 120, 34, "Prev", lambda: None, color=PANEL, hover_color=ACCENT, text_color=_rgba(TEXT))
        self.btn_next = MenuButton(0, 0, 120, 34, "Next", lambda: None, color=PANEL, hover_color=ACCENT, text_color=_rgba(TEXT))
        self.btn_back = MenuButton(0, 0, 170, 44, "Back to Menu", lambda: None, color=PANEL, hover_color=ACCENT, text_color=_rgba(TEXT))
        self._buttons = [self.btn_skins, self.btn_ach, self.btn_prev, self.btn_next, self.btn_back]
        for b in self._buttons:
            b.ensure(self._ui_batch)

        for sid in self.skin_ids:
            self._arts[sid] = PlayerArt(self._skin_batch, self._art_group)

        self._layout(width, height)  # geometry only; open() or resize() fills the panel

    # ------------------------------------------------------------------ helpers

    def _label(self, batch, text, x, y, size, color, *, font=UI_FONT_META, anchor_x="left", anchor_y="center",
               width=None, multiline=False):
        kwargs = {}
        if width is not None:
            kwargs["width"] = max(1, int(width))
            kwargs["multiline"] = bool(multiline)
        return pyglet.text.Label(
            text,
            font_name=font,
            font_size=int(size),
            x=x,
            y=y,
            anchor_x=anchor_x,
            anchor_y=anchor_y,
            color=_rgba(color),
            batch=batch,
            **kwargs,
        )

    def _selected_id(self) -> str:
        return skins.selected(self.progress).id

    def _card_state(self, sid: str) -> str:
        if sid == self._selected_id():
            return "selected"
        return "unlocked" if skins.unlocked(self.progress, sid) else "locked"

    def _earned(self) -> dict:
        data = self.progress.get("achievements") if isinstance(self.progress, dict) else None
        return data if isinstance(data, dict) else {}

    def _sync_art(self, sid: str) -> None:
        self._arts[sid].sync(self._player, self._art_shakes[sid], self._t, self._aim, palette=self._palettes[sid])

    def _flash(self, text: str, color) -> None:
        self._message = text
        self._message_color = color
        self._message_left = MESSAGE_SECONDS
        self._sync_footer()

    def _sync_footer(self) -> None:
        if self._message_left > 0.0 and self._message:
            self.footer.text = self._message
            self.footer.color = _rgba(self._message_color)
            return
        if self.tab == TAB_SKINS:
            self.footer.text = "ARROWS move  |  ENTER select  |  TAB achievements  |  ESC back"
        else:
            self.footer.text = "ARROWS page  |  TAB skins  |  ESC back"
        self.footer.color = _rgba(MUTED)

    # ------------------------------------------------------------------ state

    def open(self) -> None:
        """Reload progress and put the cursor on the selected skin. Called on every visit."""
        self.progress = meta_progress.load(self.progress_path)
        self._message_left = 0.0
        self._message = ""
        selected = self._selected_id()
        self.cursor = self.skin_ids.index(selected) if selected in self.skin_ids else 0
        self._rebuild()

    def set_tab(self, tab: str) -> None:
        if tab not in (TAB_SKINS, TAB_ACHIEVEMENTS) or tab == self.tab:
            return
        self.tab = tab
        self._rebuild()

    def choose(self, skin_id: str) -> bool:
        """Select an unlocked skin and save progress. Locked skins are refused and nothing is saved.

        Callers rebuild the panel after a successful choice so the chips reflect it, or only the ring after a refusal.
        """
        if skins.get(skin_id) is None:
            return False
        skin = skins.get(skin_id)
        if not skins.unlocked(self.progress, skin_id):
            self._flash(f"{skin.name} is locked. {self._unlock_text[skin_id]}", DANGER)
            return False
        if not skins.select(self.progress, skin_id):
            self._flash(f"{skin.name} could not be selected", DANGER)
            return False
        meta_progress.save(self.progress, self.progress_path)
        self._flash(f"{skin.name} selected", SUCCESS)
        audio_cues.cue(self.audio, "skin_select")
        return True

    # ------------------------------------------------------------------ layout

    def resize(self, width: int, height: int) -> None:
        self._layout(width, height)
        self._rebuild()

    def _layout(self, width: int, height: int) -> None:
        self.screen_width = width
        self.screen_height = height
        s = min(_ui_scale(width, height), UI_MAX_SCALE)
        self._s = s
        cx = width // 2
        self._bg.width = width
        self._bg.height = height

        self.title.x = cx
        self.title.y = height - int(46 * s)
        _sync_label_style_if_ready(self.title, UI_FONT_HEAD, _px(30, s))
        self.subtitle.x = cx
        self.subtitle.y = self.title.y - int(40 * s)  # clears the title at both sizes
        _sync_label_style_if_ready(self.subtitle, UI_FONT_META, _px(13, s))
        self.footer.x = cx
        self.footer.y = int(14 * s)
        _sync_label_style_if_ready(self.footer, UI_FONT_META, _px(12, s))

        pad = int(18 * s)
        panel_w = min(int(width * 0.94), int(1220 * s))
        panel_top = self.subtitle.y - int(18 * s)
        panel_h = min(panel_top - int(40 * s), int(760 * s))
        panel_x = cx - panel_w // 2
        panel_y = max(int(40 * s), panel_top - panel_h)
        self._panel_rect = (panel_x, panel_y, panel_w, panel_h)

        btn_h = int(44 * s)
        top_row_y = panel_y + panel_h - pad - btn_h
        gap = int(10 * s)
        self.btn_skins.width = int(150 * s)
        self.btn_ach.width = int(190 * s)
        for b in (self.btn_skins, self.btn_ach, self.btn_back):
            b.height = btn_h
            b.font_size = max(11, _px(16, s))
        self.btn_skins.x = panel_x + pad
        self.btn_skins.y = top_row_y
        self.btn_ach.x = self.btn_skins.x + self.btn_skins.width + gap
        self.btn_ach.y = top_row_y
        self.btn_back.width = int(170 * s)
        self.btn_back.x = panel_x + panel_w - pad - self.btn_back.width
        self.btn_back.y = top_row_y

        band_h = int(50 * s)
        for b in (self.btn_prev, self.btn_next):
            b.width = int(120 * s)
            b.height = int(34 * s)
            b.font_size = max(10, _px(14, s))
            b.y = panel_y + (band_h - b.height) // 2
        self.btn_prev.x = panel_x + pad
        self.btn_next.x = panel_x + panel_w - pad - self.btn_next.width

        area_x = panel_x + pad
        area_y = panel_y + band_h
        area_w = panel_w - 2 * pad
        area_h = top_row_y - int(16 * s) - area_y
        self._area = (area_x, area_y, area_w, area_h)

    def _rebuild(self) -> None:
        """Rebuild the active tab's panel and items. Runs on layout, tab, page and selection changes."""
        _drop(self._panel_shapes)
        _drop(self._content)
        self._panel_shapes = []
        self._content = []
        self._cards = []
        on_ach = self.tab == TAB_ACHIEVEMENTS
        self.btn_skins.color = PANEL if on_ach else ACCENT
        self.btn_ach.color = ACCENT if on_ach else PANEL
        self.btn_prev.alpha = 1.0 if on_ach else 0.0
        self.btn_next.alpha = 1.0 if on_ach else 0.0
        for b in self._buttons:
            b.sync()
        self._sync_footer()
        if on_ach:
            self.subtitle.text = "Every achievement, and when you earned it."
            self._build_achievements()
        else:
            self.subtitle.text = "Pick a paint for your ship. Locked skins show how to earn them."
            self._build_skins()
        self._build_ring()

    def _build_ring(self) -> None:
        """Draw the cursor ring behind the cursor card. Cheap enough to run on every arrow key."""
        _drop(self._ring_shapes)
        self._ring_shapes = []
        if self.tab != TAB_SKINS or not self._cards:
            return
        self.cursor = max(0, min(self.cursor, len(self._cards) - 1))
        x, y, w, h, _sid = self._cards[self.cursor]
        ring = max(2, int(3 * self._s))
        self._ring_shapes = draw_panel(self._ring_batch, x - ring, y - ring, w + 2 * ring, h + 2 * ring, fill=ACCENT)

    def _build_skins(self) -> None:
        batch = self._skin_batch
        s = self._s
        px, py, pw, ph = self._panel_rect
        ax, ay, aw, ah = self._area
        self._panel_shapes.extend(draw_panel(self._panel_batch, px, py, pw, ph))

        n = len(self.skin_ids)
        gap = int(CARD_GAP * s)
        min_w = int(MIN_CARD_W * s)
        cols = max(1, min(n, (aw + gap) // (min_w + gap)))
        rows = (n + cols - 1) // cols
        self._cols = cols
        card_w = (aw - gap * (cols - 1)) // cols
        card_h = min(int(CARD_MAX_H * s), (ah - gap * (rows - 1)) // rows)
        grid_h = card_h * rows + gap * (rows - 1)
        grid_top = ay + ah - max(0, ah - grid_h) // 2
        self.cursor = max(0, min(self.cursor, n - 1))
        for i, sid in enumerate(self.skin_ids):
            r, c = divmod(i, cols)
            x = ax + c * (card_w + gap)
            y = grid_top - (r + 1) * card_h - r * gap
            self._cards.append((x, y, card_w, card_h, sid))
            self._build_card(sid, x, y, card_w, card_h, s)

        selected = self._selected_id()
        unlocked_n = sum(1 for sid in self.skin_ids if skins.unlocked(self.progress, sid))
        band = f"Selected: {skins.get(selected).name}   |   {unlocked_n} of {n} unlocked"
        self._content.append(self._label(batch, band, px + pw // 2, py + int(25 * s), _px(13, s), MUTED,
                                         anchor_x="center", anchor_y="center"))

    def _build_card(self, sid: str, x: float, y: float, w: float, h: float, s: float) -> None:
        batch = self._skin_batch
        pad = int(12 * s)
        skin = skins.get(sid)
        state = self._card_state(sid)

        self._content.extend(draw_panel(batch, x, y, w, h, fill=PANEL))

        # Two columns. The name and status chip stack on the left. The character plate takes the right
        # column from just above the unlock line to the card top. The unlock line runs full width
        # underneath, so the plate, the labels and the text never share a box at any card size.
        plate_w = int(w * 0.25)
        plate_x = x + w - pad - plate_w
        gap = int(8 * s)
        left_w = plate_x - gap - (x + pad)
        plate_bottom = y + int(54 * s)  # clears the two-line unlock text, which is bottom-anchored at y + 10 * s
        plate_top = y + h - pad
        plate_h = plate_top - plate_bottom

        name_color = MUTED if state == "locked" else TEXT
        name_top = y + h - pad
        name_px = _name_size(skin.name, UI_FONT_HEAD, _px(16, s), left_w)
        self._content.append(self._label(batch, skin.name, x + pad, name_top, name_px, name_color,
                                         font=UI_FONT_HEAD, anchor_x="left", anchor_y="top", width=left_w))

        chip_text, chip_color = {
            "selected": ("SELECTED", ACCENT),
            "unlocked": ("UNLOCKED", SUCCESS),
            "locked": ("LOCKED", DANGER),
        }[state]
        chip_w = min(int(96 * s), left_w)
        chip_h = int(20 * s)
        chip_y = name_top - int(26 * s) - chip_h
        self._content.extend(draw_tag(batch, x + pad, chip_y, chip_w, chip_h, chip_text, chip_color))

        self._content.extend(draw_panel(batch, plate_x, plate_bottom, plate_w, plate_h, fill=BG))

        # Preview: the dummy player sits at world origin, so shake carries it to the plate centre.
        ox, oy = to_iso(Vec2(0.0, 0.0), Vec2(0.0, 0.0))
        centre_x = plate_x + plate_w / 2.0
        centre_y = plate_bottom + plate_h / 2.0
        self._art_shakes[sid] = Vec2(centre_x - ox, centre_y - oy)
        self._sync_art(sid)

        self._content.append(self._label(batch, self._unlock_text[sid], x + pad, y + int(10 * s),
                                         _px(11, s), MUTED, anchor_x="left", anchor_y="bottom",
                                         width=w - 2 * pad, multiline=True))

    def _build_achievements(self) -> None:
        batch = self._ach_batch
        s = self._s
        pad = int(18 * s)
        px, py, pw, ph = self._panel_rect
        ax, ay, aw, ah = self._area
        self._panel_shapes.extend(draw_panel(self._panel_batch, px, py, pw, ph))

        items = list(achievements.ACHIEVEMENTS)
        earned = self._earned()
        gap = int(ROW_GAP * s)
        row_h = int(ROW_H * s)
        per_page = max(1, (ah + gap) // (row_h + gap))
        self._page_count = max(1, (len(items) + per_page - 1) // per_page)
        self.ach_page = max(0, min(int(self.ach_page), self._page_count - 1))
        start = self.ach_page * per_page

        chip_w = int(92 * s)
        chip_h = int(20 * s)
        right_w = int(RIGHT_COL_W * s)
        text_x = ax + int(18 * s)
        text_w = aw - int(18 * s) - right_w - pad

        for i, ach in enumerate(items[start:start + per_page]):
            is_earned = ach.id in earned
            row_y = ay + ah - (i + 1) * row_h - i * gap
            self._content.extend(draw_panel(batch, ax, row_y, aw, row_h, fill=PANEL))
            self._content.extend(draw_panel(batch, ax, row_y, max(3, int(5 * s)), row_h, fill=SUCCESS if is_earned else MUTED))
            top = row_y + row_h - int(10 * s)
            self._content.append(self._label(batch, str(ach.name), text_x, top, _px(16, s),
                                             TEXT if is_earned else MUTED, font=UI_FONT_BODY, anchor_x="left",
                                             anchor_y="top", width=text_w))
            self._content.append(self._label(batch, str(ach.description), text_x, top - int(24 * s), _px(12, s), MUTED,
                                             anchor_x="left", anchor_y="top", width=text_w, multiline=True))
            right_edge = ax + aw - pad
            chip_text, chip_color = ("EARNED", SUCCESS) if is_earned else ("LOCKED", MUTED)
            self._content.extend(draw_tag(batch, right_edge - chip_w, row_y + row_h - int(10 * s) - chip_h,
                                           chip_w, chip_h, chip_text, chip_color))
            if is_earned:
                when = earned.get(ach.id)
                date_text = f"Earned {when}" if when else "Earned"
                self._content.append(self._label(batch, date_text, right_edge, row_y + int(9 * s), _px(11, s), MUTED,
                                                 anchor_x="right", anchor_y="bottom"))

        earned_n = sum(1 for a in items if a.id in earned)
        info = f"Page {self.ach_page + 1}/{self._page_count}   |   {earned_n} of {len(items)} earned"
        self._content.append(self._label(batch, info, px + pw // 2, py + int(25 * s), _px(13, s), MUTED,
                                         anchor_x="center", anchor_y="center"))

    # ------------------------------------------------------------------ input

    def _hit_card(self, x: float, y: float) -> Optional[int]:
        for i, (cx, cy, w, h, _sid) in enumerate(self._cards):
            if cx <= x <= cx + w and cy <= y <= cy + h:
                return i
        return None

    def on_mouse_motion(self, x: float, y: float) -> None:
        for b in self._buttons:
            b.is_hovered = b.contains_point(x, y)
            b.sync()

    def on_mouse_press(self, x: float, y: float, button: int) -> Optional[str]:
        if button != pyglet.window.mouse.LEFT:
            return None
        if self.btn_back.contains_point(x, y):
            return "back"
        if self.btn_skins.contains_point(x, y):
            self.set_tab(TAB_SKINS)
            return None
        if self.btn_ach.contains_point(x, y):
            self.set_tab(TAB_ACHIEVEMENTS)
            return None
        if self.tab == TAB_SKINS:
            hit = self._hit_card(x, y)
            if hit is not None:
                if hit != self.cursor:
                    audio_cues.cue(self.audio, "hangar_move")
                self.cursor = hit
                if self.choose(self._cards[hit][4]):
                    self._rebuild()
                else:
                    self._build_ring()
            return None
        if self.btn_prev.contains_point(x, y):
            self.ach_page = page_step(self.ach_page, -1, self._page_count)
            self._rebuild()
        elif self.btn_next.contains_point(x, y):
            self.ach_page = page_step(self.ach_page, 1, self._page_count)
            self._rebuild()
        return None

    def on_key_press(self, symbol: int) -> Optional[str]:
        key = pyglet.window.key
        if symbol == key.ESCAPE:
            return "back"
        if symbol == key.TAB:
            self.set_tab(TAB_ACHIEVEMENTS if self.tab == TAB_SKINS else TAB_SKINS)
            return None
        direction = {key.LEFT: "left", key.RIGHT: "right", key.UP: "up", key.DOWN: "down"}.get(symbol)
        if self.tab == TAB_SKINS:
            if direction is not None:
                before = self.cursor
                self.cursor = grid_step(self.cursor, direction, len(self.skin_ids), self._cols)
                if self.cursor != before:
                    audio_cues.cue(self.audio, "hangar_move")
                self._build_ring()
            elif symbol in (key.ENTER, key.NUM_ENTER):
                if self.choose(self.skin_ids[self.cursor]):
                    self._rebuild()
                else:
                    self._build_ring()
        elif direction is not None:
            step = -1 if direction in ("left", "up") else 1
            self.ach_page = page_step(self.ach_page, step, self._page_count)
            self._rebuild()
        return None

    # ------------------------------------------------------------------ frame

    def update(self, dt: float) -> None:
        self._t += dt
        if self._message_left > 0.0:
            self._message_left -= dt
            if self._message_left <= 0.0:
                self._message_left = 0.0
                self._message = ""
                self._sync_footer()
        if self.tab == TAB_SKINS:
            for sid in self.skin_ids:
                self._sync_art(sid)

    def draw(self) -> None:
        self._bg_batch.draw()
        self._panel_batch.draw()
        if self.tab == TAB_SKINS:
            self._ring_batch.draw()
            self._skin_batch.draw()
        else:
            self._ach_batch.draw()
        self._ui_batch.draw()
