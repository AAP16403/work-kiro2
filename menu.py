"""Simple, clean menu system for KIRO 2."""

from direct.gui.DirectGui import DirectFrame, DirectButton, DirectLabel, DGG
from panda3d.core import TextNode, Vec4


# ============================================================================
# UI CONSTANTS
# ============================================================================

UI_COLOR_BG = Vec4(0.02, 0.02, 0.08, 0.95)
UI_COLOR_TITLE = Vec4(0.0, 1.0, 0.8, 1.0)
UI_COLOR_TEXT = Vec4(0.9, 0.9, 1.0, 1.0)
UI_COLOR_BTN = Vec4(0.0, 0.2, 0.5, 1.0)
UI_COLOR_BTN_HOVER = Vec4(0.0, 0.4, 0.7, 1.0)

BUTTON_SCALE = 0.09
TITLE_SCALE = 0.20
TEXT_SCALE = 0.06

# Fonts (loaded at runtime)
UI_FONT_TITLE = None
UI_FONT_BODY = None


# ============================================================================
# FONT LOADING
# ============================================================================

def load_fonts(loader):
    """Load UI fonts from assets folder."""
    global UI_FONT_TITLE, UI_FONT_BODY
    
    try:
        UI_FONT_TITLE = loader.loadFont("assets/fonts/Orbitron-Variable.ttf")
        if UI_FONT_TITLE:
            UI_FONT_TITLE.setPixelsPerUnit(100)
    except:
        UI_FONT_TITLE = None
    
    try:
        UI_FONT_BODY = loader.loadFont("assets/fonts/Rajdhani-Regular.ttf")
        if UI_FONT_BODY:
            UI_FONT_BODY.setPixelsPerUnit(100)
    except:
        UI_FONT_BODY = None


# ============================================================================
# MENU BASE CLASS
# ============================================================================

class Menu:
    """Base menu class."""
    
    def __init__(self, game):
        self.game = game
        self.base = game.base  # Get the ShowBase instance
        self.frame = None
        self.buttons = []
        self.labels = []
    
    def show(self):
        """Show menu."""
        if not self.frame:
            self.build()
        if self.frame:
            self.frame.show()
    
    def hide(self):
        """Hide menu."""
        if self.frame:
            self.frame.hide()
    
    def build(self):
        """Build menu. Override in subclasses."""
        pass
    
    def destroy(self):
        """Cleanup menu."""
        if self.frame:
            self.frame.destroy()
            self.frame = None
        self.buttons.clear()
        self.labels.clear()


# ============================================================================
# MAIN MENU
# ============================================================================

class MainMenu(Menu):
    """Main menu screen."""
    
    def build(self):
        # Background frame
        self.frame = DirectFrame(
            frameColor=UI_COLOR_BG,
            frameSize=(-1.0, 1.0, -1.0, 1.0),
            parent=self.base.aspect2d,
            sortOrder=100
        )
        
        # Title
        title = DirectLabel(
            parent=self.frame,
            text="KIRO 2",
            text_font=UI_FONT_TITLE,
            text_fg=UI_COLOR_TITLE,
            text_scale=TITLE_SCALE,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.7)
        )
        self.labels.append(title)
        
        # Subtitle
        subtitle = DirectLabel(
            parent=self.frame,
            text="NEON SURVIVAL",
            text_font=UI_FONT_BODY,
            text_fg=UI_COLOR_TEXT,
            text_scale=TEXT_SCALE * 1.2,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.6)
        )
        self.labels.append(subtitle)
        
        # Buttons
        btn_y_start = 0.3
        btn_spacing = 0.2
        
        # Start button
        self.btn_play = DirectButton(
            parent=self.frame,
            text="INITIATE",
            command=self.on_play,
            text_font=UI_FONT_BODY,
            text_scale=BUTTON_SCALE,
            text_fg=(0, 0, 0, 1),
            frameColor=UI_COLOR_BTN,
            frameSize=(-0.3, 0.3, -0.08, 0.08),
            relief=DGG.RAISED,
            pos=(0, 0, btn_y_start)
        )
        self.buttons.append(self.btn_play)
        
        # Settings button
        self.btn_settings = DirectButton(
            parent=self.frame,
            text="SYSTEMS",
            command=self.on_settings,
            text_font=UI_FONT_BODY,
            text_scale=BUTTON_SCALE,
            text_fg=(0, 0, 0, 1),
            frameColor=UI_COLOR_BTN,
            frameSize=(-0.3, 0.3, -0.08, 0.08),
            relief=DGG.RAISED,
            pos=(0, 0, btn_y_start - btn_spacing)
        )
        self.buttons.append(self.btn_settings)
        
        # Guide button
        self.btn_guide = DirectButton(
            parent=self.frame,
            text="DATABASE",
            command=self.on_guide,
            text_font=UI_FONT_BODY,
            text_scale=BUTTON_SCALE,
            text_fg=(0, 0, 0, 1),
            frameColor=UI_COLOR_BTN,
            frameSize=(-0.3, 0.3, -0.08, 0.08),
            relief=DGG.RAISED,
            pos=(0, 0, btn_y_start - btn_spacing * 2)
        )
        self.buttons.append(self.btn_guide)
        
        # Exit button
        self.btn_exit = DirectButton(
            parent=self.frame,
            text="TERMINATE",
            command=self.on_exit,
            text_font=UI_FONT_BODY,
            text_scale=BUTTON_SCALE,
            text_fg=(0, 0, 0, 1),
            frameColor=UI_COLOR_BTN,
            frameSize=(-0.3, 0.3, -0.08, 0.08),
            relief=DGG.RAISED,
            pos=(0, 0, btn_y_start - btn_spacing * 3)
        )
        self.buttons.append(self.btn_exit)
        
        # Version label
        version = DirectLabel(
            parent=self.frame,
            text="v2.0 // SYSTEM READY",
            text_font=UI_FONT_BODY,
            text_fg=(0.5, 0.5, 0.6, 1),
            text_scale=TEXT_SCALE * 0.6,
            frameColor=(0, 0, 0, 0),
            pos=(0.8, 0, -0.9)
        )
        self.labels.append(version)
        
        self.hide()
    
    def on_play(self):
        self.game._init_game()
        self.game.fsm.set_state("PlayingState")
    
    def on_settings(self):
        self.game.fsm.set_state("SettingsState")
    
    def on_guide(self):
        self.game.fsm.set_state("GuideState")
    
    def on_exit(self):
        import sys
        sys.exit()


# ============================================================================
# SETTINGS MENU
# ============================================================================

class SettingsMenu(Menu):
    """Settings menu."""
    
    def build(self):
        self.frame = DirectFrame(
            frameColor=UI_COLOR_BG,
            frameSize=(-1.0, 1.0, -1.0, 1.0),
            parent=self.base.aspect2d,
            sortOrder=100
        )
        
        # Title
        title = DirectLabel(
            parent=self.frame,
            text="SYSTEM CONFIG",
            text_font=UI_FONT_TITLE,
            text_fg=UI_COLOR_TITLE,
            text_scale=TITLE_SCALE,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.7)
        )
        self.labels.append(title)
        
        # Status labels
        self.difficulty_label = DirectLabel(
            parent=self.frame,
            text="DIFFICULTY: NORMAL",
            text_font=UI_FONT_BODY,
            text_fg=UI_COLOR_TEXT,
            text_scale=TEXT_SCALE,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.45)
        )
        self.labels.append(self.difficulty_label)
        
        self.map_label = DirectLabel(
            parent=self.frame,
            text="MAP: CIRCLE",
            text_font=UI_FONT_BODY,
            text_fg=UI_COLOR_TEXT,
            text_scale=TEXT_SCALE,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.35)
        )
        self.labels.append(self.map_label)
        
        self.fx_label = DirectLabel(
            parent=self.frame,
            text="EFFECTS: ON",
            text_font=UI_FONT_BODY,
            text_fg=UI_COLOR_TEXT,
            text_scale=TEXT_SCALE,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.25)
        )
        self.labels.append(self.fx_label)
        
        # Buttons
        btn_y_start = 0.05
        btn_spacing = 0.2
        
        self.btn_difficulty = DirectButton(
            parent=self.frame,
            text="TOGGLE DIFFICULTY",
            command=self.on_difficulty,
            text_font=UI_FONT_BODY,
            text_scale=BUTTON_SCALE * 0.8,
            text_fg=(0, 0, 0, 1),
            frameColor=UI_COLOR_BTN,
            frameSize=(-0.35, 0.35, -0.08, 0.08),
            relief=DGG.RAISED,
            pos=(0, 0, btn_y_start)
        )
        self.buttons.append(self.btn_difficulty)
        
        self.btn_map = DirectButton(
            parent=self.frame,
            text="NEXT MAP",
            command=self.on_map,
            text_font=UI_FONT_BODY,
            text_scale=BUTTON_SCALE * 0.8,
            text_fg=(0, 0, 0, 1),
            frameColor=UI_COLOR_BTN,
            frameSize=(-0.35, 0.35, -0.08, 0.08),
            relief=DGG.RAISED,
            pos=(0, 0, btn_y_start - btn_spacing)
        )
        self.buttons.append(self.btn_map)
        
        self.btn_fx = DirectButton(
            parent=self.frame,
            text="TOGGLE EFFECTS",
            command=self.on_fx,
            text_font=UI_FONT_BODY,
            text_scale=BUTTON_SCALE * 0.8,
            text_fg=(0, 0, 0, 1),
            frameColor=UI_COLOR_BTN,
            frameSize=(-0.35, 0.35, -0.08, 0.08),
            relief=DGG.RAISED,
            pos=(0, 0, btn_y_start - btn_spacing * 2)
        )
        self.buttons.append(self.btn_fx)
        
        self.btn_back = DirectButton(
            parent=self.frame,
            text="<< BACK",
            command=self.on_back,
            text_font=UI_FONT_BODY,
            text_scale=BUTTON_SCALE,
            text_fg=(0, 0, 0, 1),
            frameColor=UI_COLOR_BTN,
            frameSize=(-0.3, 0.3, -0.08, 0.08),
            relief=DGG.RAISED,
            pos=(0, 0, btn_y_start - btn_spacing * 3.5)
        )
        self.buttons.append(self.btn_back)
        
        self._update_labels()
        self.hide()
    
    def _update_labels(self):
        d = self.game.settings.get("difficulty", "normal").upper()
        m = self.game.settings.get("map_type", "circle").upper()
        fx = "ON" if self.game.settings.get("advanced_fx", True) else "OFF"
        self.difficulty_label["text"] = f"DIFFICULTY: {d}"
        self.map_label["text"] = f"MAP: {m}"
        self.fx_label["text"] = f"EFFECTS: {fx}"
    
    def on_difficulty(self):
        d = self.game.settings.get("difficulty", "normal")
        new_d = "hard" if d == "normal" else "normal"
        self.game._on_settings_change({"difficulty": new_d})
        self._update_labels()
    
    def on_map(self):
        m = self.game.settings.get("map_type", "circle")
        types = ["circle", "donut", "cross", "diamond"]
        try:
            idx = types.index(m)
        except:
            idx = 0
        new_m = types[(idx + 1) % len(types)]
        self.game._on_settings_change({"map_type": new_m})
        self._update_labels()
    
    def on_fx(self):
        fx = self.game.settings.get("advanced_fx", True)
        self.game._on_settings_change({"advanced_fx": not fx})
        self._update_labels()
    
    def on_back(self):
        if self.game.state:
            self.game.fsm.set_state("PausedState")
        else:
            self.game.fsm.set_state("MenuState")


# ============================================================================
# PAUSE MENU
# ============================================================================

class PauseMenu(Menu):
    """Pause menu during gameplay."""
    
    def build(self):
        self.frame = DirectFrame(
            frameColor=UI_COLOR_BG,
            frameSize=(-1.0, 1.0, -1.0, 1.0),
            parent=self.base.aspect2d,
            sortOrder=100
        )
        
        title = DirectLabel(
            parent=self.frame,
            text="// PAUSED //",
            text_font=UI_FONT_TITLE,
            text_fg=UI_COLOR_TITLE,
            text_scale=TITLE_SCALE,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.5)
        )
        self.labels.append(title)
        
        btn_y_start = 0.2
        btn_spacing = 0.2
        
        self.btn_resume = DirectButton(
            parent=self.frame,
            text="RESUME MISSION",
            command=self.on_resume,
            text_font=UI_FONT_BODY,
            text_scale=BUTTON_SCALE,
            text_fg=(0, 0, 0, 1),
            frameColor=UI_COLOR_BTN,
            frameSize=(-0.3, 0.3, -0.08, 0.08),
            relief=DGG.RAISED,
            pos=(0, 0, btn_y_start)
        )
        self.buttons.append(self.btn_resume)
        
        self.btn_settings = DirectButton(
            parent=self.frame,
            text="SYSTEMS",
            command=self.on_settings,
            text_font=UI_FONT_BODY,
            text_scale=BUTTON_SCALE,
            text_fg=(0, 0, 0, 1),
            frameColor=UI_COLOR_BTN,
            frameSize=(-0.3, 0.3, -0.08, 0.08),
            relief=DGG.RAISED,
            pos=(0, 0, btn_y_start - btn_spacing)
        )
        self.buttons.append(self.btn_settings)
        
        self.btn_menu = DirectButton(
            parent=self.frame,
            text="ABORT TO MENU",
            command=self.on_menu,
            text_font=UI_FONT_BODY,
            text_scale=BUTTON_SCALE,
            text_fg=(0, 0, 0, 1),
            frameColor=UI_COLOR_BTN,
            frameSize=(-0.3, 0.3, -0.08, 0.08),
            relief=DGG.RAISED,
            pos=(0, 0, btn_y_start - btn_spacing * 2)
        )
        self.buttons.append(self.btn_menu)
        
        self.hide()
    
    def on_resume(self):
        self.game.fsm.set_state("PlayingState")
    
    def on_settings(self):
        self.game.fsm.set_state("SettingsState")
    
    def on_menu(self):
        self.game.state = None
        self.game.fsm.set_state("MenuState")


# ============================================================================
# GAME OVER MENU
# ============================================================================

class GameOverMenu(Menu):
    """Game over screen."""
    
    def build(self):
        self.frame = DirectFrame(
            frameColor=(0.15, 0.02, 0.02, 0.95),
            frameSize=(-1.0, 1.0, -1.0, 1.0),
            parent=self.base.aspect2d,
            sortOrder=100
        )
        
        title = DirectLabel(
            parent=self.frame,
            text="CRITICAL FAILURE",
            text_font=UI_FONT_TITLE,
            text_fg=(1, 0.2, 0.2, 1),
            text_scale=TITLE_SCALE * 1.2,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.6)
        )
        self.labels.append(title)
        
        self.score_label = DirectLabel(
            parent=self.frame,
            text="ANALYZING...",
            text_font=UI_FONT_BODY,
            text_fg=UI_COLOR_TEXT,
            text_scale=TEXT_SCALE,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.3)
        )
        self.labels.append(self.score_label)
        
        self.new_record_label = DirectLabel(
            parent=self.frame,
            text="",
            text_font=UI_FONT_TITLE,
            text_fg=(1, 1, 0, 1),
            text_scale=TEXT_SCALE * 1.5,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.1)
        )
        self.labels.append(self.new_record_label)
        
        btn_y_start = -0.2
        btn_spacing = 0.2
        
        self.btn_retry = DirectButton(
            parent=self.frame,
            text="REBOOT SYSTEM",
            command=self.on_retry,
            text_font=UI_FONT_BODY,
            text_scale=BUTTON_SCALE,
            text_fg=(0, 0, 0, 1),
            frameColor=UI_COLOR_BTN,
            frameSize=(-0.3, 0.3, -0.08, 0.08),
            relief=DGG.RAISED,
            pos=(0, 0, btn_y_start)
        )
        self.buttons.append(self.btn_retry)
        
        self.btn_menu = DirectButton(
            parent=self.frame,
            text="RETURN TO BASE",
            command=self.on_menu,
            text_font=UI_FONT_BODY,
            text_scale=BUTTON_SCALE,
            text_fg=(0, 0, 0, 1),
            frameColor=UI_COLOR_BTN,
            frameSize=(-0.3, 0.3, -0.08, 0.08),
            relief=DGG.RAISED,
            pos=(0, 0, btn_y_start - btn_spacing)
        )
        self.buttons.append(self.btn_menu)
        
        self.hide()
    
    def set_results(self, wave, score, high_score, is_new_high):
        if self.frame:
            self.score_label["text"] = f"WAVES: {wave} | SCORE: {score:,}"
            self.new_record_label["text"] = "!! NEW RECORD !!" if is_new_high else ""
    
    def on_retry(self):
        self.game._init_game()
        self.game.fsm.set_state("PlayingState")
    
    def on_menu(self):
        self.game.state = None
        self.game.fsm.set_state("MenuState")


# ============================================================================
# GUIDE MENU
# ============================================================================

class GuideMenu(Menu):
    """Combat manual."""
    
    def build(self):
        self.frame = DirectFrame(
            frameColor=UI_COLOR_BG,
            frameSize=(-1.0, 1.0, -1.0, 1.0),
            parent=self.base.aspect2d,
            sortOrder=100
        )
        
        title = DirectLabel(
            parent=self.frame,
            text="COMBAT MANUAL",
            text_font=UI_FONT_TITLE,
            text_fg=UI_COLOR_TITLE,
            text_scale=TITLE_SCALE,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.75)
        )
        self.labels.append(title)
        
        instructions = "W/A/S/D - MOVE\nMOUSE - AIM\nLEFT CLICK - FIRE\nRIGHT CLICK - ULTRA\nSPACE - DASH\nESC - PAUSE"
        
        instr_label = DirectLabel(
            parent=self.frame,
            text=instructions,
            text_font=UI_FONT_BODY,
            text_fg=UI_COLOR_TEXT,
            text_scale=TEXT_SCALE * 0.9,
            text_align=TextNode.ACenter,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.2)
        )
        self.labels.append(instr_label)
        
        self.btn_back = DirectButton(
            parent=self.frame,
            text="<< ACKNOWLEDGE",
            command=self.on_back,
            text_font=UI_FONT_BODY,
            text_scale=BUTTON_SCALE,
            text_fg=(0, 0, 0, 1),
            frameColor=UI_COLOR_BTN,
            frameSize=(-0.35, 0.35, -0.08, 0.08),
            relief=DGG.RAISED,
            pos=(0, 0, -0.6)
        )
        self.buttons.append(self.btn_back)
        
        self.hide()
    
    def on_back(self):
        self.game.fsm.set_state("MenuState")
