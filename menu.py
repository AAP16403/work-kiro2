from direct.gui.DirectGui import DirectFrame, DirectButton, DirectLabel, DirectSlider, DGG
from panda3d.core import TextNode

# Style constants
BUTTON_SCALE = 0.08
TEXT_SCALE = 0.08
TITLE_SCALE = 0.15
FONT_PATH = "cmss12" # Built-in font
UI_FONT_META = FONT_PATH

class Menu:
    def __init__(self, game):
        self.game = game
        self.frame = None

    def show(self):
        if not self.frame:
            self.build()
        self.frame.show()

    def hide(self):
        if self.frame:
            self.frame.hide()

    def build(self):
        # Override to build UI
        pass
    
    def destroy(self):
        if self.frame:
            self.frame.destroy()
            self.frame = None

class MainMenu(Menu):
    def build(self):
        self.frame = DirectFrame(frameColor=(0, 0, 0, 0.8), frameSize=(-1, 1, -1, 1))
        
        DirectLabel(parent=self.frame, text="PLOUTO // STELLAR SURVIVAL", scale=TITLE_SCALE, pos=(0, 0, 0.6), text_fg=(1, 1, 1, 1))
        
        DirectButton(parent=self.frame, text="PLAY", scale=BUTTON_SCALE, pos=(0, 0, 0.2), command=self.on_play)
        DirectButton(parent=self.frame, text="SETTINGS", scale=BUTTON_SCALE, pos=(0, 0, 0.0), command=self.on_settings)
        DirectButton(parent=self.frame, text="GUIDE", scale=BUTTON_SCALE, pos=(0, 0, -0.2), command=self.on_guide)
        DirectButton(parent=self.frame, text="EXIT", scale=BUTTON_SCALE, pos=(0, 0, -0.4), command=self.on_exit)

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

class SettingsMenu(Menu):
    def __init__(self, game):
        super().__init__(game)
        self.window_sizes = [(960, 540), (1280, 720), (1920, 1080)]

    def build(self):
        self.frame = DirectFrame(frameColor=(0.1, 0.1, 0.1, 0.9), frameSize=(-1, 1, -1, 1))
        DirectLabel(parent=self.frame, text="SETTINGS", scale=TITLE_SCALE, pos=(0, 0, 0.7), text_fg=(1, 1, 1, 1))
        
        # Difficulty
        DirectButton(parent=self.frame, text="Toggle Difficulty", scale=BUTTON_SCALE*0.8, pos=(0, 0, 0.4), command=self.on_difficulty)
        
        # Map Type
        DirectButton(parent=self.frame, text="Cycle Map", scale=BUTTON_SCALE*0.8, pos=(0, 0, 0.2), command=self.on_map_type)
        
        # FX
        DirectButton(parent=self.frame, text="Toggle FX", scale=BUTTON_SCALE*0.8, pos=(0, 0, 0.0), command=self.on_fx)
        
        DirectButton(parent=self.frame, text="BACK", scale=BUTTON_SCALE, pos=(0, 0, -0.6), command=self.on_back)

    def on_difficulty(self):
        # Stub logic to toggle difficulty
        d = self.game.settings.get("difficulty", "normal")
        new_d = "hard" if d == "normal" else "normal"
        self.game._on_settings_change({"difficulty": new_d})
        print(f"Difficulty set to {new_d}")

    def on_map_type(self):
        m = self.game.settings.get("map_type", "circle")
        types = ["circle", "donut", "cross", "diamond"]
        try:
            curr_idx = types.index(m)
        except Exception:
            curr_idx = 0
        new_m = types[(curr_idx + 1) % len(types)]
        self.game._on_settings_change({"map_type": new_m})
        print(f"Map set to {new_m}")

    def on_fx(self):
        fx = self.game.settings.get("advanced_fx", True)
        self.game._on_settings_change({"advanced_fx": not fx})
        print(f"FX set to {not fx}")

    def on_back(self):
        if self.game.state: # If game running/paused
             self.game.fsm.set_state("PausedState")
        else:
             self.game.fsm.set_state("MenuState")

class PauseMenu(Menu):
    def build(self):
        self.frame = DirectFrame(frameColor=(0, 0, 0, 0.5), frameSize=(-1, 1, -1, 1))
        DirectLabel(parent=self.frame, text="PAUSED", scale=TITLE_SCALE, pos=(0, 0, 0.4), text_fg=(1, 1, 1, 1))
        
        DirectButton(parent=self.frame, text="RESUME", scale=BUTTON_SCALE, pos=(0, 0, 0.0), command=self.on_resume)
        DirectButton(parent=self.frame, text="SETTINGS", scale=BUTTON_SCALE, pos=(0, 0, -0.2), command=self.on_settings)
        DirectButton(parent=self.frame, text="MAIN MENU", scale=BUTTON_SCALE, pos=(0, 0, -0.4), command=self.on_main_menu)

    def on_resume(self):
        self.game.fsm.set_state("PlayingState")

    def on_settings(self):
        self.game.fsm.set_state("SettingsState")

    def on_main_menu(self):
        self.game.state = None
        self.game.fsm.set_state("MenuState")

class GameOverMenu(Menu):
    def build(self):
        self.frame = DirectFrame(frameColor=(0.3, 0, 0, 0.8), frameSize=(-1, 1, -1, 1))
        DirectLabel(parent=self.frame, text="GAME OVER", scale=TITLE_SCALE, pos=(0, 0, 0.4), text_fg=(1, 0, 0, 1))
        
        self.score_lbl = DirectLabel(parent=self.frame, text="Score: 0", scale=TEXT_SCALE, pos=(0, 0, 0.2), text_fg=(1, 1, 1, 1))
        
        DirectButton(parent=self.frame, text="RETRY", scale=BUTTON_SCALE, pos=(0, 0, -0.2), command=self.on_retry)
        DirectButton(parent=self.frame, text="MAIN MENU", scale=BUTTON_SCALE, pos=(0, 0, -0.4), command=self.on_main_menu)

    def set_results(self, wave, score, high_score, is_new_high):
        if self.frame:
            self.score_lbl["text"] = f"Wave: {wave} | Score: {score}"

    def on_retry(self):
        self.game._init_game()
        self.game.fsm.set_state("PlayingState")

    def on_main_menu(self):
        self.game.state = None
        self.game.fsm.set_state("MenuState")

class GuideMenu(Menu):
    def build(self):
        self.frame = DirectFrame(frameColor=(0, 0, 0, 0.9), frameSize=(-1, 1, -1, 1))
        DirectLabel(parent=self.frame, text="GUIDE", scale=TITLE_SCALE, pos=(0, 0, 0.7), text_fg=(1, 1, 1, 1))
        
        instr = "WASD to Move\nMouse to Aim\nLeft Click to Toggle Auto-Shoot\nRight Click to Use Ultra\nSpace to Dash"
        DirectLabel(parent=self.frame, text=instr, scale=TEXT_SCALE*0.8, pos=(0, 0, 0.2), text_fg=(0.9, 0.9, 0.9, 1))
        
        DirectButton(parent=self.frame, text="BACK", scale=BUTTON_SCALE, pos=(0, 0, -0.6), command=self.on_back)

    def on_back(self):
        self.game.fsm.set_state("MenuState")
