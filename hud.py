"""HUD system for KIRO 2."""

from direct.gui.OnscreenText import OnscreenText
from panda3d.core import TextNode
from menu import UI_FONT_BODY, UI_FONT_TITLE


class HUD:
    """Game HUD displaying score, wave, health, etc."""
    
    def __init__(self, game):
        self.game = game
        self.elements = {}
        self.visible = False
    
    def build(self):
        """Build HUD elements."""
        if self.elements:
            return
        
        base_instance = self.game.base
        
        # Helper to create text
        def make_text(pos, scale=0.06, align=TextNode.ALeft, font=None, fg=(1, 1, 1, 1)):
            return OnscreenText(
                text="",
                pos=pos,
                scale=scale,
                fg=fg,
                align=align,
                mayChange=True,
                font=font,
                parent=base_instance.aspect2d
            )
        
        # TOP LEFT - Score and Info
        self.elements["score"] = make_text(
            (-1.75, 0.92),
            align=TextNode.ALeft,
            scale=0.075,
            font=UI_FONT_BODY,
            fg=(0, 1, 0.8, 1)
        )
        
        self.elements["kills"] = make_text(
            (-1.75, 0.82),
            align=TextNode.ALeft,
            scale=0.065,
            font=UI_FONT_BODY
        )
        
        # TOP CENTER - Wave
        self.elements["wave"] = make_text(
            (0, 0.92),
            align=TextNode.ACenter,
            scale=0.12,
            font=UI_FONT_TITLE,
            fg=(1, 1, 0.3, 1)
        )
        
        # BOTTOM LEFT - Critical Info
        self.elements["enemies_alive"] = make_text(
            (-1.75, -0.88),
            align=TextNode.ALeft,
            scale=0.07,
            font=UI_FONT_BODY,
            fg=(1, 0.5, 0.5, 1)
        )
        
        self.elements["wave_timer"] = make_text(
            (-1.75, -0.96),
            align=TextNode.ALeft,
            scale=0.065,
            font=UI_FONT_BODY
        )
        
        # PLAYER STATS - Health and Shield
        self.elements["health"] = make_text(
            (-0.85, -0.88),
            align=TextNode.ACenter,
            scale=0.075,
            font=UI_FONT_BODY,
            fg=(0.0, 1.0, 0.4, 1)
        )
        
        self.elements["shield"] = make_text(
            (-0.85, -0.96),
            align=TextNode.ACenter,
            scale=0.065,
            font=UI_FONT_BODY,
            fg=(0.5, 0.8, 1.0, 1)
        )
        
        # CENTER BOTTOM - Combo
        self.elements["combo"] = make_text(
            (0, -0.85),
            align=TextNode.ACenter,
            scale=0.14,
            font=UI_FONT_TITLE,
            fg=(1, 0.8, 0.2, 1)
        )
        
        # Weapon (bottom-right)
        self.elements["weapon"] = make_text(
            (1.75, -0.88),
            align=TextNode.ARight,
            scale=0.08,
            font=UI_FONT_BODY,
            fg=(1, 0.8, 0.2, 1)
        )
        
        # Ultra charges (bottom-right)
        self.elements["ultra"] = make_text(
            (1.75, -0.96),
            align=TextNode.ARight,
            scale=0.065,
            font=UI_FONT_BODY,
            fg=(1, 0.4, 1, 1)
        )
        
        # TOP RIGHT - FPS & Status
        self.elements["fps"] = make_text(
            (1.75, 0.92),
            scale=0.06,
            align=TextNode.ARight,
            font=UI_FONT_BODY,
            fg=(0.7, 0.7, 0.7, 1)
        )
        
        self.elements["status"] = make_text(
            (1.75, 0.82),
            scale=0.065,
            align=TextNode.ARight,
            font=UI_FONT_BODY,
            fg=(0.8, 1.0, 0.5, 1)
        )
        
        self.hide()
    
    def show(self):
        """Show HUD."""
        self.build()
        self.visible = True
        for elem in self.elements.values():
            elem.show()
    
    def hide(self):
        """Hide HUD."""
        self.visible = False
        if not self.elements:
            return
        for elem in self.elements.values():
            elem.hide()
    
    def update(self, player, state):
        """Update HUD display."""
        if not self.visible or not self.elements:
            return
        
        # Score
        if self.game.score:
            score_val = self.game.score.score
            self.elements["score"]["text"] = f"SCORE: {score_val:,}"
        
        # Wave counter
        if state and hasattr(state, 'current_wave'):
            self.elements["wave"]["text"] = f"WAVE {state.current_wave}"
        
        # Combo multiplier
        if self.game.score and hasattr(self.game.score, 'combo'):
            combo = self.game.score.combo
            if combo > 1.0:
                self.elements["combo"]["text"] = f"x{combo:.2f}"
            else:
                self.elements["combo"]["text"] = ""
        
        # Enemies alive count
        if state and hasattr(state, 'enemies'):
            enemy_count = len(state.enemies)
            self.elements["enemies_alive"]["text"] = f"ENEMIES: {enemy_count}"
        
        # Wave timer
        if state and hasattr(state, 'wave_timer'):
            timer = state.wave_timer
            self.elements["wave_timer"]["text"] = f"NEXT: {timer:.1f}s"
        
        # Player Health and Shield
        if player:
            hp = getattr(player, 'hp', 0)
            max_hp = getattr(player, 'max_hp', 100)
            shield = getattr(player, 'shield', 0)
            
            # Health bar representation
            hp_pct = max(0, min(100, int(hp * 100 / max_hp))) if max_hp > 0 else 0
            health_bar = "[" + "=" * (hp_pct // 10) + " " * (10 - hp_pct // 10) + "]"
            self.elements["health"]["text"] = f"HP: {hp:3d}/{max_hp} {health_bar}"
            
            # Shield display
            if shield > 0:
                shield_bar = "[" + "#" * min(5, shield // 25) + " " * (5 - min(5, shield // 25)) + "]"
                self.elements["shield"]["text"] = f"SHIELD: {shield:3d} {shield_bar}"
            else:
                self.elements["shield"]["text"] = "SHIELD: --- "
            
            # Current weapon
            weapon = getattr(player, 'current_weapon', None)
            if weapon:
                weapon_name = getattr(weapon, 'name', 'UNKNOWN').upper()
                self.elements["weapon"]["text"] = f"WPN: {weapon_name}"
            
            # Ultra charges
            ultra = getattr(player, 'ultra_charges', 0)
            if ultra > 0:
                ultra_bar = "*" * ultra
                self.elements["ultra"]["text"] = f"ULTRA: {ultra} {ultra_bar}"
            else:
                self.elements["ultra"]["text"] = "ULTRA: --"
        
        # Status effects
        if player:
            status = []
            current_time = self.game.base.globalClock.getFrameTime() if hasattr(self.game, 'base') and hasattr(self.game.base, 'globalClock') else 0
            if getattr(player, 'laser_until', 0) > current_time:
                status.append("LASER")
            if getattr(player, 'vortex_until', 0) > current_time:
                status.append("VORTEX")
            if getattr(player, 'invincibility_timer', 0) > 0:
                status.append("INVUL")
            
            if status:
                self.elements["status"]["text"] = " | ".join(status)
            else:
                self.elements["status"]["text"] = ""
    
    def set_fps(self, fps):
        """Update FPS display."""
        if self.visible and "fps" in self.elements:
            self.elements["fps"]["text"] = f"FPS: {fps:.0f}"
