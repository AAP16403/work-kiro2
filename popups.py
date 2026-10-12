"""Floating combat text (damage numbers) drawn from a pooled pyglet label batch.

Typical per-frame use from the game loop:
    popups.spawn(world_pos, "-12", color=(255, 200, 80))
    popups.update(dt)
    popups.sync(shake)
    popups.draw()

Labels are created lazily (a shadow label and a text label per slot, at most
max_items slots) and then reused for every later popup.
"""

import pyglet

from utils import Vec2, to_iso

POPUP_FONT = "Rajdhani"
POPUP_WEIGHT = "bold"
SIZE_NORMAL = 13
SIZE_BIG = 20
LIFE_NORMAL = 0.8           # seconds
LIFE_BIG = 1.1              # seconds
RISE_SPEED = 40.0           # screen pixels per second
FADE_FRACTION = 0.35        # the last 35% of a popup's life fades out
POP_TIME = 0.12             # seconds for the spawn scale pop to settle
POP_BOOST_NORMAL = 0.5      # spawn scale is (1 + boost), easing back to 1.0
POP_BOOST_BIG = 0.8
SHADOW_DX = 1.0             # shadow offset in screen pixels (right and down)
SHADOW_DY = 1.0
_SHADOW_COLOR = (0, 0, 0, 255)
_ORDER_SHADOW = 0           # shadows draw first so every text sits above all outlines
_ORDER_TEXT = 1


def _size_at(base_size: float, pop_boost: float, age: float) -> int:
    """Font size for a popup of the given age: eases from the pop peak down to base."""
    if age >= POP_TIME:
        return int(base_size)
    k = 1.0 - age / POP_TIME
    return int(round(base_size * (1.0 + pop_boost * k * k)))


class _Slot:
    """One pooled popup: a shadow label, a text label and their animation state."""

    __slots__ = (
        "label", "shadow", "world", "active", "order", "age", "life",
        "base_size", "pop_boost", "rise", "size", "alpha",
    )

    def __init__(self, batch, shadow_group, text_group) -> None:
        self.shadow = pyglet.text.Label(
            "", font_name=POPUP_FONT, font_size=SIZE_NORMAL, weight=POPUP_WEIGHT,
            anchor_x="center", anchor_y="center", color=_SHADOW_COLOR,
            batch=batch, group=shadow_group,
        )
        self.label = pyglet.text.Label(
            "", font_name=POPUP_FONT, font_size=SIZE_NORMAL, weight=POPUP_WEIGHT,
            anchor_x="center", anchor_y="center", color=(255, 255, 255, 255),
            batch=batch, group=text_group,
        )
        self.shadow.visible = False
        self.label.visible = False
        self.world = Vec2(0.0, 0.0)  # owned by the slot; written in place on spawn
        self.active = False
        self.order = 0
        self.age = 0.0
        self.life = LIFE_NORMAL
        self.base_size = float(SIZE_NORMAL)
        self.pop_boost = POP_BOOST_NORMAL
        self.rise = 0.0
        self.size = -1
        self.alpha = -1


class DamagePopups:
    """Pool of floating damage numbers that pop in, rise and fade out."""

    def __init__(self, max_items: int = 48) -> None:
        self._max_items = max(1, int(max_items))
        self._batch = pyglet.graphics.Batch()
        self._shadow_group = pyglet.graphics.Group(order=_ORDER_SHADOW)
        self._text_group = pyglet.graphics.Group(order=_ORDER_TEXT)
        self._slots: list[_Slot] = []
        self._live = 0
        self._seq = 0

    def spawn(self, world_pos: Vec2, text: str, color: tuple = (255, 255, 255), big: bool = False) -> None:
        slot = self._acquire()
        if not slot.active:
            slot.active = True
            self._live += 1
        slot.order = self._seq
        self._seq += 1

        slot.world.x = float(world_pos.x)
        slot.world.y = float(world_pos.y)
        slot.life = LIFE_BIG if big else LIFE_NORMAL
        slot.base_size = float(SIZE_BIG if big else SIZE_NORMAL)
        slot.pop_boost = POP_BOOST_BIG if big else POP_BOOST_NORMAL
        slot.age = 0.0
        slot.rise = 0.0

        if not isinstance(text, str):
            text = str(text)
        label = slot.label
        shadow = slot.shadow
        if label.text != text:
            label.text = text
            shadow.text = text
        label.color = (int(color[0]), int(color[1]), int(color[2]), 255)

        size = _size_at(slot.base_size, slot.pop_boost, 0.0)
        if size != slot.size:
            slot.size = size
            label.font_size = size
            shadow.font_size = size
        slot.alpha = 255
        label.opacity = 255
        shadow.opacity = 255

        label.visible = True
        shadow.visible = True

    def update(self, dt: float) -> None:
        if self._live <= 0:
            return
        dt = max(0.0, float(dt))
        for slot in self._slots:
            if not slot.active:
                continue
            slot.age += dt
            if slot.age >= slot.life:
                self._retire(slot)
                continue
            slot.rise += RISE_SPEED * dt

            size = _size_at(slot.base_size, slot.pop_boost, slot.age)
            if size != slot.size:
                slot.size = size
                slot.label.font_size = size
                slot.shadow.font_size = size

            fade_window = slot.life * FADE_FRACTION
            remaining = slot.life - slot.age
            alpha = int(255.0 * remaining / fade_window) if remaining < fade_window else 255
            if alpha != slot.alpha:
                slot.alpha = alpha
                slot.label.opacity = alpha
                slot.shadow.opacity = alpha

    def sync(self, shake: Vec2 = Vec2(0.0, 0.0)) -> None:
        if self._live <= 0:
            return
        for slot in self._slots:
            if not slot.active:
                continue
            sx, sy = to_iso(slot.world, shake)
            x = round(sx)
            y = round(sy + slot.rise)
            slot.label.x = x
            slot.label.y = y
            slot.shadow.x = x + SHADOW_DX
            slot.shadow.y = y - SHADOW_DY

    def draw(self) -> None:
        if self._live > 0:
            self._batch.draw()

    def clear(self) -> None:
        for slot in self._slots:
            if slot.active:
                self._retire(slot)
        self._live = 0

    def _retire(self, slot: _Slot) -> None:
        slot.active = False
        slot.label.visible = False
        slot.shadow.visible = False
        self._live = max(0, self._live - 1)

    def _acquire(self) -> _Slot:
        """Return a free slot, creating one lazily while under max_items, else recycle the oldest."""
        for slot in self._slots:
            if not slot.active:
                return slot
        if len(self._slots) < self._max_items:
            slot = _Slot(self._batch, self._shadow_group, self._text_group)
            self._slots.append(slot)
            return slot
        oldest = self._slots[0]
        for slot in self._slots:
            if slot.order < oldest.order:
                oldest = slot
        return oldest
