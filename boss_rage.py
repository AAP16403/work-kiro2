"""Boss rage phase and the boss-kill set piece, shared by every boss.

Rage: the first time a boss is at or below RAGE_HP_FRACTION of its max HP it enters rage, once.
While raged, each boss's attack cooldowns are RAGE_COOLDOWN_MULT of their normal length and each
volley fires RAGE_EXTRA_SHOTS more projectiles (or beams, or pulses). Bosses call cooldown() and
volley() from their own attack code, so the rule itself lives here once. Rage draws no random
numbers, so a seeded run stays reproducible.

Boss death: celebrate_boss_death() adds a camera-style flash through advanced_fx and plays the
victory fanfare from the existing SFX list.
"""

from utils import enemy_behavior_name

RAGE_HP_FRACTION = 0.35
RAGE_COOLDOWN_MULT = 0.75  # attack cooldowns shrink by 25 percent
RAGE_EXTRA_SHOTS = 1  # one extra projectile, beam or pulse per volley
RAGE_BANNER_TITLE = "BOSS RAGE"
RAGE_BANNER_COLOR = (255, 110, 70)
RAGE_BANNER_DURATION = 2.4
RAGE_SFX = "boss_warn"
RAGE_SFX_VOLUME = 0.9

FANFARE_SFX = "wave_clear"  # ascending A major arpeggio, the existing victory-style sound
FANFARE_VOLUME = 0.9
# The wave-clear chirp fires on the same frame when the boss was the last enemy. Both calls use this
# gap, so the chirp is dropped and the fanfare is not doubled.
FANFARE_MIN_GAP = 0.6
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
        audio.play(RAGE_SFX, volume=RAGE_SFX_VOLUME)


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
    """Boss kill set piece: a camera-style flash through advanced_fx and the victory fanfare."""
    fx = getattr(game, "advanced_fx", None)
    if fx is not None:
        fx.trigger_boss_flash(DEATH_FLASH_STRENGTH)
    audio = getattr(game, "audio", None)
    if audio is not None:
        audio.play(FANFARE_SFX, volume=FANFARE_VOLUME, min_gap=FANFARE_MIN_GAP)
