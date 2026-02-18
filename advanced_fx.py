"""Lightweight screen-space FX for Panda3D."""

from __future__ import annotations

from direct.gui.DirectGui import DirectFrame


class AdvancedFX:
    def __init__(self, width: int, height: int):
        self.enabled = True
        self._hit_flash = 0.0
        self._danger = 0.0
        self._overlay = DirectFrame(
            frameColor=(0.15, 0.2, 0.28, 0.0),
            frameSize=(-1.0, 1.0, -1.0, 1.0),
            parent=None,
        )
        self._overlay.setTransparency(True)

    def resize(self, width: int, height: int):
        return

    def trigger_hit(self, intensity: float):
        self._hit_flash = max(self._hit_flash, max(0.0, min(1.0, float(intensity))))

    def render(self, t: float, combat_int: float, hp_ratio: float, boss_active: bool):
        if not self.enabled:
            self._overlay["frameColor"] = (0.15, 0.2, 0.28, 0.0)
            return
        self._hit_flash = max(0.0, self._hit_flash - 0.045)
        low_hp = max(0.0, min(1.0, 1.0 - float(hp_ratio)))
        danger_target = max(0.0, min(1.0, low_hp * 0.8 + float(combat_int) * 0.2 + (0.1 if boss_active else 0.0)))
        self._danger += (danger_target - self._danger) * 0.16
        alpha = max(0.0, min(0.24, self._hit_flash * 0.14 + self._danger * 0.16))

        # Keep low-health readability without painting the whole scene red.
        red = 0.16 + low_hp * 0.14 + self._hit_flash * 0.25
        green = 0.2 - low_hp * 0.08 + self._hit_flash * 0.08
        blue = 0.28 - low_hp * 0.1
        self._overlay["frameColor"] = (max(0.0, min(1.0, red)), max(0.0, min(1.0, green)), max(0.0, min(1.0, blue)), alpha)
