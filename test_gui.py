"""Quick test of Panda3D GUI rendering."""

from direct.showbase.ShowBase import ShowBase
from direct.gui.DirectGui import DirectFrame, DirectLabel, DirectButton
from panda3d.core import WindowProperties

class TestApp(ShowBase):
    def __init__(self):
        ShowBase.__init__(self)
        
        # Window setup
        props = WindowProperties()
        props.setSize(1280, 720)
        props.setTitle("Menu Test")
        self.win.requestProperties(props)
        
        print("Creating test frame...")
        
        # Create a simple frame
        frame = DirectFrame(
            frameColor=(0, 0, 0, 0.8),
            frameSize=(-0.3, 0.3, -0.3, 0.3)
        )
        
        # Add label
        label = DirectLabel(
            parent=frame,
            text="HELLO",
            text_scale=0.1,
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
            pos=(0, 0, 0.15)
        )
        
        # Add button
        btn = DirectButton(
            parent=frame,
            text="CLICK ME",
            text_scale=0.08,
            frameSize=(-0.15, 0.15, -0.04, 0.04),
            frameColor=(0.2, 0.5, 0.8, 1),
            pos=(0, 0, -0.15),
            command=lambda: print("Button clicked!")
        )
        
        print("GUI created! Frame visible: " + str(not frame.isHidden()))

if __name__ == "__main__":
    app = TestApp()
    print("Starting main loop...")
    app.run()
