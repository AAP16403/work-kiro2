from direct.gui.OnscreenText import OnscreenText
from panda3d.core import TextNode

class HUD:
    def __init__(self, game):
        self.game = game
        self.elements = {}
        self.visible = False
        
    def build(self):
        if self.elements: return
        
        # Helper to create text
        def make_text(pos, scale=0.07, align=TextNode.ALeft):
            return OnscreenText(text="", pos=pos, scale=scale, fg=(1,1,1,1), align=align, mayChange=True)

        self.elements["score"] = make_text((-1.3, 0.9))
        self.elements["wave"] = make_text((0.0, 0.9), align=TextNode.ACenter)
        self.elements["hp"] = make_text((-1.3, -0.9))
        self.elements["weapon"] = make_text((0.8, -0.9))
        self.elements["dash"] = make_text((0.8, -0.8))
        self.elements["combo"] = make_text((0.0, 0.8), align=TextNode.ACenter, scale=0.09)
        self.elements["fps"] = make_text((1.2, 0.9), scale=0.05)
        
        # Hide initially
        for e in self.elements.values():
            e.hide()

    def show(self):
        self.build()
        self.visible = True
        for e in self.elements.values():
            e.show()

    def hide(self):
        self.visible = False
        for e in self.elements.values():
            e.hide()

    def update(self, player, state):
        if not self.visible: return
        
        # Score
        score_val = getattr(self.game, "score", None)
        s_txt = f"Score: {int(score_val.score)}" if score_val else "Score: 0"
        self.elements["score"].setText(s_txt)
        
        # Wave
        self.elements["wave"].setText(f"Wave {state.wave}")
        
        # HP / Shield
        hp = int(player.hp)
        max_hp = int(player.max_hp)
        shield = int(getattr(player, "shield", 0))
        hp_txt = f"HP: {hp}/{max_hp}"
        if shield > 0:
            hp_txt += f" (+{shield})"
        self.elements["hp"].setText(hp_txt)
        
        # Weapon
        w = player.current_weapon
        w_name = getattr(w, "name", "Pea Shooter")
        self.elements["weapon"].setText(f"Weapon: {w_name}")
        
        # Dash
        charges = int(player.dash_charges)
        self.elements["dash"].setText(f"Dash: {charges}")
        
        # Combo
        if state.enemy_combo_value > 0:
            self.elements["combo"].setText(f"{state.enemy_combo_text} +{state.enemy_combo_value}")
        else:
            self.elements["combo"].setText("")
            
        # FPS?
        # self.elements["fps"].setText(f"FPS: ??")
