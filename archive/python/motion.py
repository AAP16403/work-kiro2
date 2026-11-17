"""Reduced motion: one switch that stills every decorative animation.

config.REDUCE_MOTION is the flag (default False). The Settings toggle sets it at runtime, the same
way the Screen Shake setting sets SHAKE_SCALE. Animation code asks this module for a factor rather
than reading the flag itself, so every effect follows one rule: scale its shake, its drift or its
oscillator time by factor(). Gameplay never reads this module, so turning the switch on changes
only what is drawn, never the simulation.
"""

import config


def reduced() -> bool:
    """True while reduced motion is on."""
    return bool(getattr(config, "REDUCE_MOTION", False))


def factor() -> float:
    """1.0 normally, 0.0 with reduced motion. Multiply shake, drift and oscillator time by it."""
    return 0.0 if reduced() else 1.0


def clock(t: float) -> float:
    """Oscillator time for a visual pulse. With reduced motion it sits at 0, the rest pose of sin(t * k)."""
    return float(t) * factor()


def anim_dt(dt: float) -> float:
    """Frame time for animation only. Zero with reduced motion. Gameplay timing never uses this."""
    return float(dt) * factor()
