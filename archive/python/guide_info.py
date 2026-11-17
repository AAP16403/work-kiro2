"""Guide entries for the newer systems: Hangar and skins, achievements, mutators,
the new powerups, arena events, elite affixes, boss rage and the daily run.

Every number in these entries comes from config.py or from an owner module's
definitions (mutators.MUTATORS, skins.SKINS, achievements.ACHIEVEMENTS and
events.EVENTS). None is typed here, so the Guide text cannot drift from the game.
An owner module that is not in the build contributes no entries.

Entry shape, as used by menu.GuideMenu:
    {"key", "name", "icon", "what", "deal", "lore"}
"""

from __future__ import annotations

import importlib
from dataclasses import fields as dataclass_fields
from typing import Any

import config

# Icon colours for entries whose key is not a config.ENEMY_COLORS or POWERUP_COLORS key.
ACCENT_COLORS = {
    "splitter": config.ELITE_AURA_COLOR,
    "reflector": (170, 230, 255),
    "boss_rage": (255, 90, 90),
}

MUTATOR_ICONS = {
    "glass_cannon": "GC",
    "bullet_hell": "BH",
    "drift": "DR",
    "frenzy": "FZ",
    "iron_man": "IM",
}

# Plain wording for the arena events, matched by a word inside the event id.
# Each row: (id word, name, icon, what, deal, lore). A name or description set on the
# event definition wins over these.
EVENT_TEXT = (
    ("meteor", "Meteor Shower", "MS",
     "Rings mark where rocks land, then area damage hits.",
     "Step out of each ring before it lands.",
     "The rings are the warning. Stay outside them."),
    ("flare", "Solar Flare", "SF",
     "A beam sweeps one sector after a clear warning.",
     "Read the sweep and move against it.",
     "Damage only lands inside the beam, never outside it."),
    ("nebula", "Nebula Cloud", "NC",
     "Enemies inside the visible cloud gain a shield.",
     "Pull enemies out of the cloud to strip shields.",
     "The cloud is always drawn, so you can see where it is."),
)

_STAT_LABELS = {
    "PLAYER_DAMAGE": "damage",
    "PLAYER_HP": "max HP",
    "PLAYER_SPEED": "move speed",
    "PLAYER_FIRE_RATE": "fire interval",
}


def _owner(name: str) -> Any:
    """Import an owner module, or return None while it is missing from the build."""
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _field(obj: Any, name: str, default: Any) -> Any:
    """Read a field from a dict or an object, falling back to default."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def ordinal(n: Any) -> str:
    """5 -> '5th', 2 -> '2nd', 11 -> '11th'."""
    n = int(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _config_numbers() -> dict:
    """Every numeric UPPER_CASE config value, used as the base for mutator diffs."""
    return {k: v for k, v in vars(config).items() if k.isupper() and isinstance(v, (bool, int, float))}


def _stat_label(key: str) -> str:
    """PLAYER_DAMAGE -> damage; ENEMY_BULLET_SPEED_MULT -> enemy bullet speed."""
    if key in _STAT_LABELS:
        return _STAT_LABELS[key]
    return str(key).upper().removesuffix("_MULT").lower().replace("_", " ")


# Plain labels for the RunRules fields that mutators.py changes.
_RULE_LABELS = {
    "player_damage_mult": "damage",
    "player_max_hp_mult": "max HP",
    "player_accel": "steering ease",
    "player_decel": "slide after input",
    "enemy_projectile_speed_mult": "enemy bullet speed",
    "enemy_volley_extra": "enemy shots per volley",
    "enemy_speed_mult": "enemy speed",
    "spawn_size_mult": "wave size",
    "pickups_enabled": "pickups",
    "shield_regen_per_s": "shield regen",
}


def _mutator_what_rules(mutator: Any, rules_cls: Any) -> str:
    """Score multiplier plus the RunRules fields the mutator changes. The stock RunRules is the base."""
    stock = rules_cls()
    after_rules = mutator.apply(stock)
    parts = []
    for f in dataclass_fields(stock):
        before = getattr(stock, f.name)
        after = getattr(after_rules, f.name)
        if after == before:
            continue
        label = _RULE_LABELS.get(f.name, f.name.replace("_", " "))
        if isinstance(after, bool):
            parts.append(f"{label} {'on' if after else 'off'}")
        elif f.name.endswith("_mult"):
            parts.append(f"{label} x{float(after):g}")
        elif f.name == "enemy_volley_extra":
            parts.append(f"{label} +{int(after)}")
        else:
            parts.append(f"{label} {float(after):g}")
    text = f"Score x{float(mutator.score_mult):g}."
    if parts:
        stats = ", ".join(parts)
        text += " " + stats[0].upper() + stats[1:] + "."
    return text


def _mutator_what(mutator: Any, base: dict, rules_cls: Any = None) -> str:
    """Score multiplier plus the values the mutator changes, read from its own apply().
    With a RunRules class (mutators.py) the change is read from the RunRules fields. Otherwise apply() gets a
    config dict, and a value that is not in config is shown as a multiplier when its key ends in _MULT."""
    if rules_cls is not None:
        return _mutator_what_rules(mutator, rules_cls)
    changed = dict(mutator.apply(dict(base)) or {})
    parts = []
    for key, after in changed.items():
        if not isinstance(after, (bool, int, float)):
            continue
        before = base.get(key)
        if before == after:
            continue
        label = _stat_label(str(key))
        if isinstance(after, bool):
            parts.append(f"{label} {'on' if after else 'off'}")
        elif _is_number(before) and before != 0:
            parts.append(f"{label} x{float(after) / float(before):g}")
        elif str(key).upper().endswith("_MULT"):
            parts.append(f"{label} x{float(after):g}")
        else:
            parts.append(f"{label} {float(after):g}")
    text = f"Score x{float(mutator.score_mult):g}."
    if parts:
        stats = ", ".join(parts)
        text += " " + stats[0].upper() + stats[1:] + "."
    return text


def _skin_deal(rule: Any, skins_module: Any = None) -> str:
    """The unlock line for a skin. Numbers come from the rule itself."""
    if not rule or getattr(rule, "kind", None) == "default":
        return "Open from the start."
    return f"Unlock by {_unlock_text(rule, skins_module)}."


def _unlock_text(rule: Any, skins_module: Any = None) -> str:
    """Plain text for a non-empty skin unlock rule, e.g. 'best wave 10'.

    A skins.UnlockRule is worded by skins.unlock_rule_text, the same source the Hangar's cards use.
    """
    if isinstance(rule, str):
        return rule
    if isinstance(rule, dict):
        for field in ("text", "label", "description"):
            if rule.get(field):
                return str(rule[field])
        pieces = []
        for k, v in rule.items():
            value = f"{v:g}" if _is_number(v) else str(v)
            pieces.append(f"{str(k).replace('_', ' ')} {value}")
        return ", ".join(pieces)
    kind = getattr(rule, "kind", None)
    if kind is not None:
        worded = getattr(skins_module, "unlock_rule_text", None) if skins_module is not None else None
        text = worded(rule) if callable(worded) else f"{str(kind).replace('_', ' ')} {getattr(rule, 'value', '')}".strip()
        return text[:1].lower() + text[1:]
    return str(rule)


def enemy_entries() -> list[dict]:
    """Elite affixes splitter and reflector, and boss rage. Shown on the Enemies tab."""
    return [
        {
            "key": "splitter", "name": "Elite: Splitter", "icon": "SL",
            "what": f"On death it splits into {config.ELITE_SPLIT_COUNT:g} copies at {config.ELITE_SPLIT_HP_FRAC * 100:g}% HP each.",
            "deal": "Clear the halves fast; they never split again.",
            "lore": "Fragments of the same frame, one generation deep.",
        },
        {
            "key": "reflector", "name": "Elite: Reflector", "icon": "RF",
            "what": f"Every {config.ELITE_REFLECT_COOLDOWN:g}s it bounces back the next shot that hits it.",
            "deal": "Watch its flash, then leave the bounce line.",
            "lore": "It turns your own damage back on you.",
        },
        {
            "key": "boss_rage", "name": "Boss Rage", "icon": "RG",
            "what": (
                f"At {config.BOSS_RAGE_HP_FRAC * 100:g}% HP: cooldowns shrink "
                f"{(1.0 - config.BOSS_RAGE_COOLDOWN_MULT) * 100:g}%, +{config.BOSS_RAGE_EXTRA_PROJECTILES:g} shot per volley."
            ),
            "deal": "Burst it before the rage line, then dodge.",
            "lore": "A banner marks the rage. It starts once per boss.",
        },
    ]


def powerup_entries() -> list[dict]:
    """Ricochet, homing, time slow, magnet, chain lightning and repulsor. Shown on the Powerups tab."""
    bounce = "once" if int(config.RICOCHET_BOUNCES) == 1 else f"{int(config.RICOCHET_BOUNCES)} times"
    return [
        {
            "key": "ricochet", "name": "Ricochet (<>)", "icon": "<>",
            "what": f"Your bullets bounce off the arena edge {bounce}, for {config.RICOCHET_DURATION:g}s.",
            "deal": "Bank shots off the rim into blind spots.",
            "lore": "Edge-tuned rounds that refuse to die on first contact.",
        },
        {
            "key": "homing", "name": "Homing (H)", "icon": "H",
            "what": f"Bullets curve to the nearest enemy within {config.HOMING_RANGE:g} px for {config.HOMING_DURATION:g}s.",
            "deal": "Fire into packs; the shots find targets.",
            "lore": "Seeking rounds with a capped turn rate, so they stay readable.",
        },
        {
            "key": "time_slow", "name": "Time Slow (~)", "icon": "~",
            "what": f"Enemies and their shots move at {config.TIME_SLOW_SCALE * 100:g}% speed for {config.TIME_SLOW_DURATION:g}s.",
            "deal": "You keep full speed: reposition or line up shots.",
            "lore": "The whole field slows down, you do not.",
        },
        {
            "key": "magnet", "name": "Magnet (M)", "icon": "M",
            "what": f"Pickups are pulled from {config.MAGNET_RADIUS_MULT:g}x as far, and faster, for {config.MAGNET_DURATION:g}s.",
            "deal": "Clear the field, then sweep up distant loot.",
            "lore": "Drops pulled in like filings to a lodestone.",
        },
        {
            "key": "chain", "name": "Chain Lightning (Z)", "icon": "Z",
            "what": (
                f"Rare. Each kill throws an arc to the nearest enemy within {config.CHAIN_RANGE:g} px for "
                f"{config.CHAIN_DURATION:g}s, dealing {config.CHAIN_DAMAGE_PERCENT:g}% of your damage."
            ),
            "deal": "Kills in a pack start more kills; keep the packs close.",
            "lore": "A capacitor that discharges into the next nearest target.",
        },
        {
            "key": "repulsor", "name": "Repulsor (R)", "icon": "R",
            "what": f"Shockwave: enemy shots within {config.REPULSOR_RANGE:g} px are pushed out, slow ones vanish. Enemies stun {config.REPULSOR_STUN_SECONDS:g}s.",
            "deal": f"Cooldown {config.REPULSOR_COOLDOWN_SECONDS:g}s. Extra pickups bank up to {config.REPULSOR_MAX_CHARGES}.",
            "lore": "A reactive pulse that shoves back anything not moving fast.",
        },
    ]


def hangar_entry(skins_module: Any) -> dict:
    count = len(getattr(skins_module, "SKINS", {}) or {}) if skins_module is not None else 0
    what = (
        f"Pick a ship look from {count} skins on the title screen."
        if count else "Pick a ship look on the title screen."
    )
    return {
        "key": "hangar", "name": "Hangar", "icon": "HG",
        "what": what,
        "deal": "Locked skins list their unlock rule.",
        "lore": "Achievements are listed in the same screen.",
    }


def skin_entries(skins_module: Any) -> list[dict]:
    if skins_module is None:
        return []
    return [
        {
            "key": f"skin_{skin.id}", "name": f"Skin: {skin.name}", "icon": "SK",
            "what": str(skin.description),
            "deal": _skin_deal(skin.unlock, skins_module),
            "lore": "Recolours your ship and its bullets.",
        }
        for skin in skins_module.SKINS.values()
    ]


def daily_entry() -> dict:
    return {
        "key": "daily", "name": "Daily Run", "icon": "DY",
        "what": "One seed and one mutator per day, the same for everyone.",
        "deal": "Beat today's best score. No other mutators.",
        "lore": "Dates use your local clock.",
    }


def mutator_entries(mutators_module: Any) -> list[dict]:
    if mutators_module is None:
        return []
    base = _config_numbers()
    rules_cls = getattr(mutators_module, "RunRules", None)
    out = []
    table = getattr(mutators_module, "MUTATORS", ())
    # mutators.MUTATORS is a tuple of Mutator records in canonical order; a mapping of id to record also works.
    records = table.values() if isinstance(table, dict) else table
    for mutator in records:
        mid = str(mutator.id)
        out.append({
            "key": mid, "name": str(mutator.name),
            "icon": MUTATOR_ICONS.get(mid, str(mutator.name)[:2].upper()),
            "what": _mutator_what(mutator, base, rules_cls),
            "deal": "Opt-in: toggle it on the title screen before you start.",
            "lore": str(mutator.description),
        })
    return out


def event_entries(events_module: Any) -> list[dict]:
    if events_module is None:
        return []
    out = []
    for event in getattr(events_module, "EVENTS", []) or []:
        event_id = str(_field(event, "id", event))
        typed = next((row for row in EVENT_TEXT if row[0] in event_id.lower()), None)
        if typed is None:
            default_name = event_id.replace("_", " ").title()
            default_what = "A timed arena event that warns before it hits."
            default_deal = "Watch the warning marks and stay clear of them."
            default_lore = "Arena events always show their warning first."
            icon = "EV"
        else:
            _, default_name, icon, default_what, default_deal, default_lore = typed
        out.append({
            "key": f"event_{event_id}",
            "name": str(_field(event, "name", default_name)),
            "icon": icon,
            "what": str(_field(event, "description", default_what)),
            "deal": default_deal,
            "lore": default_lore,
        })
    return out


def achievement_entries(achievements_module: Any) -> list[dict]:
    if achievements_module is None:
        return []
    return [
        {
            "key": f"ach_{achievement.id}", "name": str(achievement.name), "icon": "AC",
            "what": str(achievement.description),
            "deal": "Earned once. Saved with your progress.",
            "lore": "Listed in the Hangar's achievement gallery.",
        }
        for achievement in achievements_module.ACHIEVEMENTS
    ]


def systems_entries(modules: dict | None = None) -> list[dict]:
    """Shown on the Systems tab. modules maps owner names to modules (tests pass fakes);
    by default each owner is imported, and a missing one contributes nothing."""
    if modules is None:
        modules = {name: _owner(name) for name in ("skins", "achievements", "mutators", "events")}
    return (
        [hangar_entry(modules.get("skins"))]
        + skin_entries(modules.get("skins"))
        + [daily_entry()]
        + mutator_entries(modules.get("mutators"))
        + event_entries(modules.get("events"))
        + achievement_entries(modules.get("achievements"))
    )
