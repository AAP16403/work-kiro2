"""Boss rage phase and the boss-kill set piece, shared by every boss.

Rage: the first time a boss is at or below RAGE_HP_FRACTION of its max HP it enters rage, once.
While raged, each boss's attack cooldowns are RAGE_COOLDOWN_MULT of their normal length and each
volley fires RAGE_EXTRA_SHOTS more projectiles (or beams, or pulses). Bosses call cooldown() and
volley() from their own attack code, so the rule itself lives here once. Rage draws no random
numbers, so a seeded run stays reproducible.

Boss death: celebrate_boss_death() adds a camera-style flash through advanced_fx and plays the
victory fanfare from the existing SFX list.
"""

import audio_cues
from utils import enemy_behavior_name

RAGE_HP_FRACTION = 0.35
RAGE_COOLDOWN_MULT = 0.75  # attack cooldowns shrink by 25 percent
RAGE_EXTRA_SHOTS = 1  # one extra projectile, beam or pulse per volley
RAGE_BANNER_TITLE = "BOSS RAGE"
RAGE_BANNER_COLOR = (255, 110, 70)
RAGE_BANNER_DURATION = 2.4

# The rage warning and the victory fanfare are cues from audio_cues.CUE_SPECS ("rage_warn", "victory_fanfare").
# The wave-clear chirp fires on the same frame when the boss was the last enemy. states.py skips that chirp
# on a frame where celebrate_boss_death already played the fanfare, so the two never double up.
FANFARE_MIN_GAP = 0.6  # the chirp's min_gap (states.py)
DEATH_FLASH_STRENGTH = 1.0


def is_raged(enemy) -> bool:
    """True once the boss has entered rage."""
    ai = getattr(enemy, "ai", None)
    return bool(ai) and bool(ai.get("rage"))


def _boss_title(enemy) -> str:
    name = enemy_behavior_name(enemy)
    if name.startswith("boss_"):
        name = name[5:]
    return name.replace("_", " ").upper()


def _announce(enemy, game) -> None:
    hud = getattr(game, "hud", None)
    if hud is not None:
        hud.show_banner(
            RAGE_BANNER_TITLE,
            f"{_boss_title(enemy)}  -  ATTACKS QUICKEN",
            color=RAGE_BANNER_COLOR,
            duration=RAGE_BANNER_DURATION,
        )
    audio = getattr(game, "audio", None)
    if audio is not None:
        audio_cues.cue(audio, "rage_warn")


def update_rage(enemy, game=None) -> bool:
    """Enter rage the first time the boss is at or below RAGE_HP_FRACTION of max HP.

    Returns True only on the call that starts rage. The banner and warning sound are requested on
    that call, and the pending attack cooldown shrinks with it so the change lands right away.
    """
    ai = enemy.ai
    if ai.get("rage"):
        return False
    max_hp = max(1, int(ai.get("max_hp", enemy.hp)))
    if float(enemy.hp) / float(max_hp) > RAGE_HP_FRACTION:
        return False
    ai["rage"] = True
    if enemy.attack_cd > 0.0:
        enemy.attack_cd *= RAGE_COOLDOWN_MULT
    _announce(enemy, game)
    return True


def cooldown(enemy, seconds: float) -> float:
    """An attack cooldown for this boss: RAGE_COOLDOWN_MULT of it while raged, unchanged otherwise."""
    s = float(seconds)
    return s * RAGE_COOLDOWN_MULT if is_raged(enemy) else s


def volley(enemy, count: int) -> int:
    """The projectile count of one volley: RAGE_EXTRA_SHOTS more while raged."""
    n = int(count)
    return n + RAGE_EXTRA_SHOTS if is_raged(enemy) else n


def celebrate_boss_death(game) -> None:
    """Boss kill set piece: a camera-style flash through advanced_fx and the victory fanfare.

    The game remembers the state time of the fanfare, so the wave-clear chirp on the same frame is skipped.
    """
    fx = getattr(game, "advanced_fx", None)
    if fx is not None:
        fx.trigger_boss_flash(DEATH_FLASH_STRENGTH)
    audio = getattr(game, "audio", None)
    if audio is not None:
        audio_cues.cue(audio, "victory_fanfare")
    state = getattr(game, "state", None)
    game._fanfare_stamp = getattr(state, "time", None)
