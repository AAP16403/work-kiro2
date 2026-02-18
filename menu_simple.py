"""Minimal test menu."""

from direct.gui.DirectGui import DirectFrame, DirectButton, DirectLabel, DGG
from panda3d.core import TextNode


class TestMenu:
    """Super minimal menu for testing."""
    
    def __init__(self, game):
        self.game = game
        self.frame = None
        self.visible = False
    
    def show(self):
        """Show menu."""
        if self.frame is None:
            self.build()
        if self.frame:
            self.frame.show()
            self.visible = True
    
    def hide(self):
        """Hide menu."""
        if self.frame:
            self.frame.hide()
            self.visible = False
    
    def build(self):
        """Build the menu."""
        # Get showbase
        showbase = self.game.base
        
        # Create a simple frame - parent to render2d instead of aspect2d
        self.frame = DirectFrame(
            frameColor=(0.1, 0.1, 0.1, 0.9),
            frameSize=(-0.5, 0.5, -0.5, 0.5),
            pos=(0, 0, 0)
        )
        
        # Add a label
        label = DirectLabel(
            parent=self.frame,
            text="== KIRO 2 ==",
            text_scale=0.1,
            pos=(0, 0, 0.3),
            frameColor=(0, 0, 0, 0),
            text_fg=(0, 1, 0.8, 1)
        )
        
        # Add buttons
        btn1 = DirectButton(
            parent=self.frame,
            text="START",
            text_scale=0.08,
            frameSize=(-0.2, 0.2, -0.05, 0.05),
            pos=(0, 0, 0.1),
            command=self.on_start,
            frameColor=(0.2, 0.2, 0.5, 1),
            text_fg=(1, 1, 1, 1)
        )
        
        btn2 = DirectButton(
            parent=self.frame,
            text="EXIT",
            text_scale=0.08,
            frameSize=(-0.2, 0.2, -0.05, 0.05),
            pos=(0, 0, -0.1),
            command=self.on_exit,
            frameColor=(0.5, 0.2, 0.2, 1),
            text_fg=(1, 1, 1, 1)
        )
        
        print("DEBUG: Menu created!")
    
    def on_start(self):
        print("DEBUG: Start pressed")
        self.game._init_game()
        self.game.fsm.set_state("PlayingState")
    
    def on_exit(self):
        print("DEBUG: Exit pressed")
        import sys
        sys.exit()
