print("DEBUG: main_panda.py loading...")
from direct.showbase.ShowBase import ShowBase
from direct.filter.CommonFilters import CommonFilters
from panda3d.core import OrthographicLens, AmbientLight, DirectionalLight, Vec4, WindowProperties

import config


class KiroGame(ShowBase):
    def __init__(self):
        ShowBase.__init__(self)

        props = WindowProperties()
        props.setTitle("Kiro 2: Panda3D Edition")
        props.setSize(config.SCREEN_W, config.SCREEN_H)
        self.win.requestProperties(props)

        self.disableMouse()

        lens = OrthographicLens()
        lens.setFilmSize(config.SCREEN_W, config.SCREEN_H)
        lens.setNearFar(0.1, 5000.0)
        self.cam.node().setLens(lens)

        # Stable isometric camera framing centered on world origin.
        self.camera.setPos(-700, -700, 700)
        self.camera.lookAt(0, 0, 0)

        alight = AmbientLight("alight")
        alight.setColor(Vec4(0.2, 0.2, 0.35, 1)) # Darker, bluer ambient
        alnp = self.render.attachNewNode(alight)
        self.render.setLight(alnp)

        dlight = DirectionalLight("dlight")
        dlight.setColor(Vec4(0.7, 0.7, 0.8, 1)) # Slightly cooler main light
        dlnp = self.render.attachNewNode(dlight)
        dlnp.setHpr(45, -60, 0) # Angled for better rim lighting on 3D shapes
        self.render.setLight(dlnp)
        
        # Secondary rim light for extra pop
        rlight = DirectionalLight("rlight")
        rlight.setColor(Vec4(0.4, 0.2, 0.5, 1)) # Purple rim
        rlnp = self.render.attachNewNode(rlight)
        rlnp.setHpr(-135, -20, 0)
        self.render.setLight(rlnp)

        # Post-Processing (Bloom)
        # Intense bloom for neon look
        self.filters = CommonFilters(self.win, self.cam)
        self.filters.setBloom(blend=(0, 0, 0, 1), desat=-0.1, intensity=2.0, size="medium", mintrigger=0.6)

        from game import Game

        self.game = Game(self)


if __name__ == "__main__":
    app = KiroGame()
    app.run()
