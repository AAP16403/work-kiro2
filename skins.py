"""Player skin catalogue: colour palettes, unlock rules and selection.

Public API:

    SKINS                          tuple of Skin, in menu order (the default comes first)
    DEFAULT_SKIN_ID                "classic", always unlocked
    PALETTE_KEYS                   ("body", "accent", "eye", "glow", "trail", "bullet"), the keys
                                   of player_art.DEFAULT_PALETTE; every skin palette has exactly these
    get(skin_id) -> Skin | None
    unlock_rule_met(skin, progress) -> bool
        True when the skin's rule holds for this progress dict right now.
    unlocked(progress, skin_id) -> bool
        True when the skin is recorded as unlocked or its rule holds.
    refresh_unlocks(progress) -> list[str]
        Records every skin whose rule now holds in progress["unlocked_skins"]. Unlocks are
        permanent, so nothing is ever removed. Returns the ids newly recorded.
    selected(progress) -> Skin
        The chosen skin, or the default when the chosen one is unknown or locked.
    select(progress, skin_id) -> bool
        Chooses a skin and returns True. A locked or unknown skin is refused: nothing
        changes and False is returned.
    unlock_hint(skin) -> str
        One line for a locked skin, such as "Score 5,000 in one run".

Palettes are plain dicts of (r, g, b) tuples. Treat them as read-only, or copy them with
dict(skin.palette) before changing anything.

Importing this module does no I/O.
"""

from dataclasses import dataclass

import achievements


DEFAULT_SKIN_ID = "classic"
PALETTE_KEYS = ("body", "accent", "eye", "glow", "trail", "bullet", "cheek")


@dataclass(frozen=True)
class UnlockRule:
    """How a skin unlocks. ``kind`` is one of: default, score, wave, bosses, kills, achievement.

    score, wave, bosses and kills compare against the matching lifetime best or total in
    progress. ``value`` is the threshold, or an achievement id for kind "achievement".
    """

    kind: str
    value: object = 0


@dataclass(frozen=True)
class Skin:
    """One selectable player skin."""

    id: str
    name: str
    description: str
    palette: dict
    unlock: UnlockRule


SKINS: tuple[Skin, ...] = (
    Skin(
        # Equal to player_art.DEFAULT_PALETTE, the look every run shows for this skin, so the Hangar card matches the run.
        "classic", "Classic Pod", "The original cyan pod. Always unlocked.",
        {
            "body": (132, 224, 255), "accent": (255, 206, 90), "eye": (16, 24, 46),
            "glow": (100, 220, 255), "trail": (130, 210, 255), "bullet": (235, 240, 255), "cheek": (255, 140, 175),
        },
        UnlockRule("default"),
    ),
    Skin(
        "ember", "Ember Pod", "A hot orange shell that glows like a reactor core.",
        {
            "body": (255, 170, 110), "accent": (255, 110, 60), "eye": (255, 245, 220),
            "glow": (255, 120, 50), "trail": (255, 160, 80), "bullet": (255, 190, 110), "cheek": (255, 140, 175),
        },
        UnlockRule("score", 5000),
    ),
    Skin(
        "frost", "Frost Pod", "Pale ice-blue plating with cold white trails.",
        {
            "body": (210, 240, 255), "accent": (150, 220, 255), "eye": (40, 80, 140),
            "glow": (170, 230, 255), "trail": (200, 240, 255), "bullet": (220, 250, 255), "cheek": (255, 140, 175),
        },
        UnlockRule("wave", 10),
    ),
    Skin(
        "verdant", "Verdant Pod", "Leaf-green hull that leaves a soft mint haze.",
        {
            "body": (150, 240, 160), "accent": (80, 200, 120), "eye": (30, 70, 40),
            "glow": (120, 255, 150), "trail": (140, 255, 170), "bullet": (190, 255, 200), "cheek": (255, 140, 175),
        },
        UnlockRule("kills", 250),
    ),
    Skin(
        "solar", "Solar Pod", "Gold plating that blazes like a sunrise.",
        {
            "body": (255, 235, 150), "accent": (255, 200, 60), "eye": (90, 50, 10),
            "glow": (255, 220, 90), "trail": (255, 230, 120), "bullet": (255, 245, 180), "cheek": (255, 140, 175),
        },
        UnlockRule("bosses", 2),
    ),
    Skin(
        "storm", "Storm Pod", "Slate-blue hull with lightning-yellow sparks.",
        {
            "body": (120, 140, 200), "accent": (255, 235, 80), "eye": (255, 255, 255),
            "glow": (90, 170, 255), "trail": (150, 210, 255), "bullet": (255, 250, 140), "cheek": (255, 140, 175),
        },
        UnlockRule("bosses", 5),
    ),
    Skin(
        "void", "Void Pod", "Violet shell that pulls light into its trail.",
        {
            "body": (110, 70, 160), "accent": (190, 120, 255), "eye": (255, 240, 255),
            "glow": (170, 90, 255), "trail": (200, 140, 255), "bullet": (230, 190, 255), "cheek": (255, 140, 175),
        },
        UnlockRule("achievement", "combo_6x"),
    ),
    Skin(
        "neon", "Neon Pod", "Hot pink hull with aqua accents.",
        {
            "body": (255, 120, 220), "accent": (120, 255, 240), "eye": (25, 20, 40),
            "glow": (255, 80, 200), "trail": (120, 255, 240), "bullet": (255, 160, 240), "cheek": (255, 140, 175),
        },
        UnlockRule("achievement", "elite_slayer"),
    ),
    Skin(
        "crimson", "Crimson Pod", "Deep red armour for those who push the score.",
        {
            "body": (235, 70, 80), "accent": (120, 20, 30), "eye": (255, 230, 230),
            "glow": (255, 60, 70), "trail": (255, 110, 110), "bullet": (255, 150, 150), "cheek": (255, 140, 175),
        },
        UnlockRule("score", 25000),
    ),
    Skin(
        "ghost", "Ghost Pod", "Near-white shell that fades into the starfield.",
        {
            "body": (235, 240, 250), "accent": (170, 180, 200), "eye": (60, 70, 90),
            "glow": (200, 210, 235), "trail": (220, 225, 240), "bullet": (250, 250, 255), "cheek": (255, 140, 175),
        },
        UnlockRule("achievement", "no_damage_wave"),
    ),
)

_COUNTER_FOR_KIND = {
    "score": "best_score",
    "wave": "best_wave",
    "bosses": "bosses_defeated",
    "kills": "total_kills",
}


def get(skin_id) -> Skin | None:
    """Return the skin with this id, or None."""
    if not isinstance(skin_id, str):
        return None
    for skin in SKINS:
        if skin.id == skin_id:
            return skin
    return None


def unlock_rule_met(skin: Skin, progress: dict) -> bool:
    """True when the skin's unlock rule holds for ``progress`` right now."""
    rule = skin.unlock
    if rule.kind == "default":
        return True
    if rule.kind == "achievement":
        return rule.value in progress.get("achievements", [])
    key = _COUNTER_FOR_KIND.get(rule.kind)
    if key is None:
        return False
    return float(progress.get(key, 0)) >= float(rule.value)


def unlocked(progress: dict, skin_id) -> bool:
    """True when the skin is recorded as unlocked, or its rule holds now."""
    skin = get(skin_id)
    if skin is None:
        return False
    if skin.id in progress.get("unlocked_skins", []):
        return True
    return unlock_rule_met(skin, progress)


def refresh_unlocks(progress: dict) -> list[str]:
    """Record every skin whose rule now holds. Returns the ids that were newly recorded."""
    recorded = progress.setdefault("unlocked_skins", [])
    new_ids: list[str] = []
    for skin in SKINS:
        if skin.id in recorded:
            continue
        if unlock_rule_met(skin, progress):
            recorded.append(skin.id)
            new_ids.append(skin.id)
    return new_ids


def selected(progress: dict) -> Skin:
    """The chosen skin. Falls back to the default when the choice is unknown or locked."""
    skin = get(progress.get("selected_skin"))
    if skin is not None and unlocked(progress, skin.id):
        return skin
    return get(DEFAULT_SKIN_ID)


def select(progress: dict, skin_id) -> bool:
    """Choose ``skin_id``. Returns False and changes nothing when the skin is locked or unknown."""
    if not unlocked(progress, skin_id):
        return False
    recorded = progress.setdefault("unlocked_skins", [])
    if skin_id not in recorded:
        recorded.append(skin_id)
    progress["selected_skin"] = skin_id
    return True


def unlock_hint(skin: Skin) -> str:
    """One line that says how to unlock ``skin``."""
    rule = skin.unlock
    if rule.kind == "default":
        return "Always unlocked"
    if rule.kind == "score":
        return f"Score {int(rule.value):,} in one run"
    if rule.kind == "wave":
        return f"Reach wave {int(rule.value)}"
    if rule.kind == "bosses":
        return f"Defeat {int(rule.value)} bosses across all runs"
    if rule.kind == "kills":
        return f"Destroy {int(rule.value):,} enemies across all runs"
    if rule.kind == "achievement":
        return f"Earn the {achievements.name_of(rule.value)} achievement"
    return ""
