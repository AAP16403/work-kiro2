"""Afterburn: a dash leaves a short burning strip on the ground.

While the player dashes, a segment drops at the pod every AFTERBURN_DROP_SECONDS. A segment burns for
AFTERBURN_LIFE_SECONDS and then fades out. At most AFTERBURN_MAX_SEGMENTS are alive: a drop with the pool full
reuses the oldest live segment.

An enemy whose body centre is within AFTERBURN_HIT_RADIUS of a live segment burns: it takes AFTERBURN_DAMAGE
every AFTERBURN_TICK_SECONDS. Each enemy has its own timer, kept on the enemy as ``_afterburn_next`` (run clock),
so one enemy's tick never resets another's. Bosses take AFTERBURN_BOSS_MULT of each tick. The damage and the kill
go through the caller's ``deal`` callable (PlayingState._afterburn_hit), which uses the normal damage and kill path.

This module has no pyglet import. The drawing is afterburn_art.AfterburnPool, which reads the segments of an
AfterburnTrail. Nothing here uses a random source, so a seeded run and its replay stay the same.

Every number comes from config.py, read when it is used. With ENABLE_AFTERBURN False nothing spawns, nothing
burns and nothing is drawn.
"""

from __future__ import annotations

from typing import Callable

import config
from utils import enemy_behavior_name

# Float slack for the drop and tick clocks. Fixed steps are 1/60 s, so a drop 0.05 s after the last one lands
# on the step it should, not one step late, when the float sum falls a hair short.
_EPS = 1e-9


class Segment:
    """One burning segment: its ground position (world units), its drop time, and whether it is alive.

    The fixed set of these is built once per run and reused. A dead segment keeps its last values.
    """

    __slots__ = ("x", "y", "t0", "live")

    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.t0 = 0.0
        self.live = False


def damage_for(enemy) -> int:
    """Damage of one tick on ``enemy``: AFTERBURN_DAMAGE, or AFTERBURN_BOSS_MULT of it for a boss (at least 1)."""
    base = int(config.AFTERBURN_DAMAGE)
    if enemy_behavior_name(enemy).startswith("boss_"):
        return max(1, int(base * float(config.AFTERBURN_BOSS_MULT) + 0.5))
    return base


class AfterburnTrail:
    """The run's burning strip: a fixed pool of segments, the drop clock, and two counters for the report.

    ``hits`` counts ticks dealt and ``kills`` counts the ticks that killed. Both only grow during a run.
    """

    def __init__(self, size: int | None = None):
        n = int(config.AFTERBURN_MAX_SEGMENTS if size is None else size)
        self.segments: list[Segment] = [Segment() for _ in range(max(1, n))]
        self._next_drop = 0.0
        self.drops = 0
        self.hits = 0
        self.kills = 0

    @property
    def size(self) -> int:
        return len(self.segments)

    @property
    def live_count(self) -> int:
        """Segments alive right now. Call expire() first to read the count at a run time."""
        n = 0
        for seg in self.segments:
            if seg.live:
                n += 1
        return n

    def spawn(self, x: float, y: float, now: float) -> Segment | None:
        """Drop a segment at world (x, y) at run time ``now``. Takes a free slot, else reuses the oldest live one.

        Returns the segment, or None when ENABLE_AFTERBURN is off.
        """
        if not config.ENABLE_AFTERBURN:
            return None
        slot = None
        oldest = None
        for seg in self.segments:
            if not seg.live:
                slot = seg
                break
            if oldest is None or seg.t0 < oldest.t0:
                oldest = seg
        if slot is None:
            slot = oldest
        slot.x = float(x)
        slot.y = float(y)
        slot.t0 = float(now)
        slot.live = True
        self.drops += 1
        return slot

    def update_dash(self, dashing: bool, x: float, y: float, now: float) -> bool:
        """Once per frame, with the dash state. While dashing, drops a segment at (x, y) whenever the drop clock is due.

        The first frame of a dash drops at once: a frame that is not dashing resets the clock. Returns True when a
        segment dropped this frame.
        """
        if not config.ENABLE_AFTERBURN:
            return False
        now = float(now)
        if not dashing:
            self._next_drop = now
            return False
        if now + _EPS < self._next_drop:
            return False
        if self.spawn(x, y, now) is None:
            return False
        self._next_drop = now + float(config.AFTERBURN_DROP_SECONDS)
        return True

    def expire(self, now: float) -> None:
        """Retire every segment whose age has reached AFTERBURN_LIFE_SECONDS at run time ``now``."""
        life = float(config.AFTERBURN_LIFE_SECONDS)
        now = float(now)
        for seg in self.segments:
            if seg.live and now - seg.t0 >= life:
                seg.live = False

    def tick(self, enemies, now: float, deal: Callable) -> int:
        """Burn every enemy in reach of a live segment whose own timer is due. Returns the ticks dealt.

        ``enemies`` is the run's enemy list. ``deal(enemy, amount) -> bool`` applies the damage and returns True
        when the tick killed the enemy. The caller's kill path removes the enemy from ``enemies``, so the loop runs
        backwards and reads the list by index. Nothing is allocated per call.
        """
        if not config.ENABLE_AFTERBURN:
            return 0
        now = float(now)
        self.expire(now)
        if self.live_count == 0:
            return 0
        reach = float(config.AFTERBURN_HIT_RADIUS)
        reach_sq = reach * reach
        interval = float(config.AFTERBURN_TICK_SECONDS)
        segments = self.segments
        dealt = 0
        i = len(enemies) - 1
        while i >= 0:
            # A kill can remove enemies behind the cursor (an elite's blast), so the cursor is clamped to the list.
            if i >= len(enemies):
                i = len(enemies) - 1
                continue
            e = enemies[i]
            i -= 1
            if e.hp <= 0 or getattr(e, "_is_dead", False):
                continue
            ex = e.pos.x
            ey = e.pos.y
            in_reach = False
            for seg in segments:
                if seg.live:
                    dx = seg.x - ex
                    dy = seg.y - ey
                    if dx * dx + dy * dy <= reach_sq:
                        in_reach = True
                        break
            if not in_reach:
                continue
            due = getattr(e, "_afterburn_next", None)
            if due is None:
                nxt = now + interval  # first contact: the enemy's own timer starts now
            else:
                if now + _EPS < due:
                    continue
                # Keep the cadence on a fixed grid while ticks land on time. After a long gap, restart from now.
                nxt = due + interval
                if nxt <= now + _EPS:
                    nxt = now + interval
            e._afterburn_next = nxt
            dealt += 1
            self.hits += 1
            if deal(e, damage_for(e)):
                self.kills += 1
        return dealt

    def reset(self) -> None:
        """Clear every segment and the drop clock, e.g. when a run ends. The counters are kept."""
        for seg in self.segments:
            seg.live = False
        self._next_drop = 0.0
