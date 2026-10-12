"""Pickup decorations for the timed powerups (Ricochet, Homing, Time Slow, Magnet).

visuals.ensure_powerup draws the shared orb, rings, core and glyph for every pickup. A timed pickup
also gets a few shapes around the orb that tell it apart at a glance:

    ricochet   six dots on a ring, like bounce marks
    homing     four short bars, a crosshair
    time_slow  an open clock ring with a single hand
    magnet     a thick horseshoe with white tips

make_pickup_art builds those shapes into a batch and returns each one with its offset from the orb
centre. place_pickup_art moves them with the orb every frame.
"""

import math

from pyglet import shapes

# Kinds that get a decoration. Other pickups draw the shared orb only.
PICKUP_ART_KINDS = frozenset({"ricochet", "homing", "time_slow", "magnet"})

_WHITE = (255, 255, 255)


def make_pickup_art(kind: str, batch, color, size: float, group=None):
    """Build the decoration for ``kind`` into ``batch``.

    Returns (shapes, offsets). ``offsets[i]`` is the (dx, dy) of ``shapes[i]`` from the orb centre.
    Both lists are empty for kinds without a decoration.
    """
    kind = str(kind)
    out = []
    offsets = []
    r = float(size)

    if kind == "ricochet":
        ring_r = r + 9.0
        for i in range(6):
            ang = math.tau * i / 6.0
            dot = shapes.Circle(0, 0, 2.5, color=color, batch=batch, group=group)
            dot.opacity = 230
            out.append(dot)
            offsets.append((math.cos(ang) * ring_r, math.sin(ang) * ring_r))

    elif kind == "homing":
        reach = r + 4.0
        bar = 8.0
        thick = 3.0
        # Shapes anchor at their bottom-left corner, so offsets are for that corner.
        specs = (
            (-thick / 2.0, reach, thick, bar),              # top
            (-thick / 2.0, -reach - bar, thick, bar),       # bottom
            (reach, -thick / 2.0, bar, thick),              # right
            (-reach - bar, -thick / 2.0, bar, thick),       # left
        )
        for dx, dy, w, h in specs:
            bar_shape = shapes.Rectangle(0, 0, w, h, color=color, batch=batch, group=group)
            bar_shape.opacity = 235
            out.append(bar_shape)
            offsets.append((dx, dy))

    elif kind == "time_slow":
        face = shapes.Arc(
            0, 0, r + 8.0, segments=48, angle=290.0, start_angle=-35.0,
            thickness=2.0, color=color, batch=batch, group=group,
        )
        face.opacity = 235
        out.append(face)
        offsets.append((0.0, 0.0))
        hand = shapes.Rectangle(0, 0, 2.0, r * 0.62, color=_WHITE, batch=batch, group=group)
        hand.opacity = 230
        out.append(hand)
        offsets.append((-1.0, 0.0))

    elif kind == "magnet":
        ring_r = r + 7.0
        horseshoe = shapes.Arc(
            0, 0, ring_r, segments=32, angle=180.0, start_angle=180.0,
            thickness=4.0, color=color, batch=batch, group=group,
        )
        horseshoe.opacity = 235
        out.append(horseshoe)
        offsets.append((0.0, 0.0))
        for side in (-1.0, 1.0):
            tip = shapes.Rectangle(0, 0, 4.0, 6.0, color=_WHITE, batch=batch, group=group)
            tip.opacity = 235
            out.append(tip)
            offsets.append((side * ring_r - 2.0, -2.0))

    return out, offsets


def place_pickup_art(art_shapes, offsets, sx: float, sy: float) -> None:
    """Move decoration shapes so each sits at its offset from the orb centre (sx, sy)."""
    for shape, (dx, dy) in zip(art_shapes, offsets):
        shape.x = sx + dx
        shape.y = sy + dy
