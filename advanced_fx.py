"""Lightweight screen-space FX for Panda3D."""

from __future__ import annotations

from direct.gui.DirectGui import DirectFrame


class AdvancedFX:
    def __init__(self, width: int, height: int):
        self.enabled = True
        self._hit_flash = 0.0
        self._danger = 0.0
        self._overlay = DirectFrame(
            frameColor=(1.0, 0.15, 0.15, 0.0),
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
            self._overlay["frameColor"] = (1.0, 0.15, 0.15, 0.0)
            return
        self._hit_flash = max(0.0, self._hit_flash - 0.05)
        low_hp = max(0.0, min(1.0, 1.0 - float(hp_ratio)))
        danger_target = max(0.0, min(1.0, low_hp * 0.75 + float(combat_int) * 0.25 + (0.18 if boss_active else 0.0)))
        self._danger += (danger_target - self._danger) * 0.2
        alpha = max(0.0, min(0.42, self._hit_flash * 0.5 + self._danger * 0.2))
        self._overlay["frameColor"] = (1.0, 0.15, 0.15, alpha)
