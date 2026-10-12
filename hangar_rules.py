"""Pure rules for the Hangar: cursor movement, paging and unlock wording.

No pyglet and no wave-1 imports, so these can be tested on their own. hangar.py builds the screen on top.
"""

from __future__ import annotations

from typing import Optional

TAB_SKINS = "skins"
TAB_ACHIEVEMENTS = "achievements"


def grid_step(index: int, direction: str, count: int, cols: int) -> int:
    """Return the cursor cell after one arrow key on a grid of ``count`` cells in ``cols`` columns.

    Left and right walk the flat order and wrap from the last cell to the first and back. Up and
    down stay in the same column and wrap to the opposite edge of that column.
    """
    if count <= 0:
        return 0
    cols = max(1, min(int(cols), count))
    i = int(index) % count
    col = i % cols
    if direction == "left":
        return (i - 1) % count
    if direction == "right":
        return (i + 1) % count
    if direction == "up":
        j = i - cols
        if j >= 0:
            return j
        # Wrap to the bottom-most cell in this column.
        return col + cols * ((count - 1 - col) // cols)
    if direction == "down":
        j = i + cols
        if j < count:
            return j
        return col
    return i


def page_step(page: int, delta: int, total: int) -> int:
    """Move a page index by ``delta`` pages, wrapping at both ends."""
    if total <= 0:
        return 0
    return (int(page) + int(delta)) % int(total)


def describe_unlock(skin, achievement_names: Optional[dict] = None) -> str:
    """Plain-language unlock line for a skin card, such as "Unlock: reach 150 total kills".

    Understands an explicit ``text``/``label``/``description``, an achievement rule and a stat
    threshold. A default rule reads "Open from the start". Any other rule shape is spelled out
    as key/value pairs.
    """
    rule = getattr(skin, "unlock", None)
    if not rule:
        return "Open from the start"
    if not isinstance(rule, dict):
        return f"Unlock: {rule}"
    text = rule.get("text") or rule.get("label") or rule.get("description")
    if text:
        return f"Unlock: {text}"
    kind = str(rule.get("kind", rule.get("type", ""))).strip().lower()
    if kind in ("", "default", "none", "always"):
        return "Open from the start"
    if kind in ("achievement", "achievements"):
        ach_id = rule.get("id", rule.get("achievement", "?"))
        name = (achievement_names or {}).get(ach_id, str(ach_id))
        return f"Unlock: earn the {name} achievement"
    if kind in ("stat", "stats"):
        stat = str(rule.get("stat", "")).replace("_", " ")
        threshold = rule.get("at_least", rule.get("min", rule.get("value")))
        if stat and threshold is not None:
            return f"Unlock: reach {threshold} {stat}"
    parts = [f"{str(k).replace('_', ' ')} {v}" for k, v in rule.items() if k not in ("kind", "type")]
    return "Unlock: " + (", ".join(parts) if parts else kind.replace("_", " "))
