import math

from panda3d.core import NodePath, CardMaker, LineSegs
import config
from utils import enemy_behavior_name

class GroupCache:
    def get(self, order): return None

class Visuals:
    def __init__(self, parent_node, group_cache, loader=None):
        self.root = parent_node
        self.loader = loader
        # Hierarchy
        self.floor_root = self.root.attachNewNode("floor")
        self.traps_root = self.root.attachNewNode("traps")
        self.obstacles_root = self.root.attachNewNode("obstacles")
        self.powerups_root = self.root.attachNewNode("powerups")
        self.enemies_root = self.root.attachNewNode("enemies")
        self.projectiles_root = self.root.attachNewNode("projectiles")
        self.player_root = self.root.attachNewNode("player")
        self.fx_root = self.root.attachNewNode("fx")

    def _load_model(self, model_name: str):
        if self.loader is not None:
            return self.loader.loadModel(model_name)
        from direct.showbase import ShowBaseGlobal
        base = getattr(ShowBaseGlobal, "base", None)
        if base is None:
            raise RuntimeError(f"model loader unavailable for {model_name}")
        return base.loader.loadModel(model_name)
        
    def _make_quad(self, name, size, color, billboard=False):
        cm = CardMaker(name)
        cm.setFrame(-size, size, -size, size)
        node = NodePath(cm.generate())
        if billboard:
            node.setBillboardPointEye()
        else:
            # For shadows, lie flat on ground (rotate 90 degrees around X axis)
            node.setR(90)
        node.setColor(color[0]/255.0, color[1]/255.0, color[2]/255.0, 1.0)
        node.setTransparency(True)
        node.setTwoSided(True)
        return node

    @staticmethod
    def _rgb(color):
        return color[0] / 255.0, color[1] / 255.0, color[2] / 255.0
    
    def _make_sphere(self, name, size, color):
        node = self._load_model("models/smiley")
        if node is None:
            raise RuntimeError("model loader returned None for sphere")
        node.setScale(max(0.75, size * 0.09))
        r, g, b = self._rgb(color)
        node.setColor(r, g, b, 1.0)
        return node

    def _make_glow_sprite(self, name, size, color, accent=None, billboard=True):
        base = NodePath(name)
        core_cm = CardMaker(f"{name}_core")
        core_cm.setFrame(-size * 0.45, size * 0.45, -size * 0.45, size * 0.45)
        core = base.attachNewNode(core_cm.generate())
        if billboard:
            core.setBillboardPointEye()
        core.setTransparency(True)
        core.setTwoSided(True)
        core.setColor(color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, 1.0)

        halo_cm = CardMaker(f"{name}_halo")
        halo_cm.setFrame(-size, size, -size, size)
        halo = base.attachNewNode(halo_cm.generate())
        if billboard:
            halo.setBillboardPointEye()
        halo.setTransparency(True)
        halo.setTwoSided(True)
        ac = accent or color
        halo.setColor(ac[0] / 255.0, ac[1] / 255.0, ac[2] / 255.0, 0.35)
        halo.setAlphaScale(0.45)
        return base
    
    def _attach_outline(self, base: NodePath, size: float, color, sides: int = 6, thickness: float = 2.4):
        sides = max(3, int(sides))
        ls = LineSegs()
        ls.setColor(color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, 1.0)
        ls.setThickness(float(thickness))
        r = float(size) * 0.55
        for i in range(sides + 1):
            a = (i % sides) * (2.0 * math.pi / float(sides))
            x = r * math.cos(a)
            y = r * math.sin(a)
            if i == 0:
                ls.moveTo(x, y, 0.0)
            else:
                ls.drawTo(x, y, 0.0)
        node = base.attachNewNode(ls.create())
        node.setTransparency(True)
        node.setBillboardPointEye()
        return node
    
    def _make_ring(self, radius: float, thickness: float, color, segments: int = 36) -> NodePath:
        segments = max(8, int(segments))
        ls = LineSegs()
        ls.setColor(color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, 1.0)
        ls.setThickness(float(thickness))
        for i in range(segments + 1):
            a = (i % segments) * (2.0 * math.pi / float(segments))
            x = float(radius) * math.cos(a)
            y = float(radius) * math.sin(a)
            if i == 0:
                ls.moveTo(x, y, 0.0)
            else:
                ls.drawTo(x, y, 0.0)
        node = NodePath(ls.create())
        node.setTransparency(True)
        return node

    def _make_polygon(self, name: str, size: float, color, sides: int = 6) -> NodePath:
        """Create a flat polygon."""
        sides = max(3, int(sides))
        cm = CardMaker(name)
        
        # We can't directly make a polygon, so we make a card and attach line segments
        # to its borders to form the desired shape.
        node = self._make_quad(name, size, (0,0,0,0)) # Transparent card
        
        ls = LineSegs()
        ls.setColor(self._rgb(color)[0], self._rgb(color)[1], self._rgb(color)[2], 1.0)
        ls.setThickness(size * 0.5)
        
        for i in range(sides + 1):
            a = (i / sides) * 2 * math.pi
            x = math.cos(a) * size
            y = math.sin(a) * size
            if i == 0:
                ls.moveTo(x, y, 0)
            else:
                ls.drawTo(x, y, 0)
        
        poly_node = ls.create(False)
        node.attachNewNode(poly_node)
        node.setBillboardPointEye()
        return node

    def _make_rectangle(self, name: str, width: float, height: float, color) -> NodePath:
        """Create a flat rectangle."""
        cm = CardMaker(name)
        cm.setFrame(-width/2, width/2, -height/2, height/2)
        node = NodePath(cm.generate())
        node.setP(-90)
        node.setColor(self._rgb(color)[0], self._rgb(color)[1], self._rgb(color)[2], 1.0)
        node.setTransparency(True)
        return node

    def _make_beam_segment(self, start, end, z: float, color, thickness: float, alpha: float) -> NodePath:
        ls = LineSegs("beam_segment")
        r, g, b = self._rgb(color)
        ls.setColor(r, g, b, max(0.0, min(1.0, float(alpha))))
        ls.setThickness(max(1.0, float(thickness)))
        ls.moveTo(start.x, start.y, float(z))
        ls.drawTo(end.x, end.y, float(z))
        node = NodePath(ls.create())
        node.setTransparency(True)
        return node

    def _make_projectile_model(self, owner: str, ptype: str, size: float, color) -> NodePath:
        base = NodePath(f"proj_{owner}_{ptype}")
        
        # Primary core
        if ptype == "missile":
            # 3D Missile Model
            body = self._make_cube(f"missile_body_{owner}", size * 0.8, size * 0.3, size * 0.3, color)
            body.setScale(2.5, 0.6, 0.6)
            body.reparentTo(base)
            
            # Fins
            fins = self._make_polygon("fins", size * 1.2, (100, 100, 100), sides=3)
            fins.reparentTo(body)
            fins.setH(90)
            fins.setP(90)
            fins.setX(-0.5)
            
            # Engine glow
            engine = self._make_glow_sprite("engine", size * 1.5, (255, 100, 50))
            engine.reparentTo(base)
            engine.setX(-1.5 * size)
            
        elif ptype == "bomb":
            # Pulsing Spike Ball
            core = self._make_sphere("proj_core", size, color)
            core.reparentTo(base)
            
            spikes = self._make_polygon("spikes", size * 1.8, (255, 50, 50), sides=4)
            spikes.reparentTo(base)
            spikes.setHpr(45, 45, 0)
            
            pulse_ring = self._make_ring(size * 1.2, 3, (255, 100, 100), segments=16)
            pulse_ring.reparentTo(base)
            pulse_ring.setBillboardPointEye()

        elif ptype == "plasma":
            # Energy Orb with Halo
            core = self._make_sphere("proj_core", size * 0.8, (255, 255, 255))
            core.reparentTo(base)
            
            halo = self._make_glow_sprite("plasma_halo", size * 2.5, color)
            halo.reparentTo(base)
            
        elif ptype == "spread":
            # Sharp crystals
            core = self._make_cube("shard", size, size * 0.4, size * 0.4, color)
            core.reparentTo(base)
            core.setHpr(45, 0, 45)
            
            glow = self._make_glow_sprite("shard_glow", size * 1.5, color)
            glow.reparentTo(base)
            
        else: # Standard bullet
            # Glowing Capsule
            core = self._make_cube("bullet_core", size * 1.2, size * 0.4, size * 0.4, (255, 255, 255))
            core.reparentTo(base)
            
            shell = self._make_glow_sprite("bullet_glow", size * 1.8, color)
            shell.reparentTo(base)

        return base

    def _make_cube(self, name: str, sx: float, sy: float, sz: float, color) -> NodePath:
        box = self._load_model("models/box")
        box.setName(name)
        box.setScale(sx, sy, sz)
        r, g, b = self._rgb(color)
        box.setColor(r, g, b, 1.0)
        return box

    @staticmethod
    def _enemy_height_profile(behavior: str):
        b = str(behavior)
        if b.startswith("boss_"):
            return 15.6, 1.15, 5.6, 28.0
        if b == "flyer":
            return 25.0, 2.5, 4.0, 15.0 # Fly high
        if b == "swarm":
            return 9.2, 0.45, 10.0, 95.0
        if b in ("tank", "engineer"):
            return 8.0, 0.1, 1.0, 5.0 # Heavy, grounded
        return 11.2, 0.58, 6.0, 54.0
    
    def _make_enemy_model(self, behavior: str, size: float, color) -> NodePath:
        base = NodePath(f"enemy_{behavior}")
        
        if behavior == "tank":
            # Heavy Tank Design
            chassis = self._make_cube("chassis", size * 1.4, size * 1.0, size * 0.5, color)
            chassis.reparentTo(base)
            
            turret = self._make_cube("turret", size * 0.6, size * 0.6, size * 0.4, (color[0]*0.8, color[1]*0.8, color[2]*0.8))
            turret.reparentTo(chassis)
            turret.setZ(size * 0.5)
            
            barrel = self._make_cube("barrel", size * 0.8, size * 0.2, size * 0.2, (50, 50, 50))
            barrel.reparentTo(turret)
            barrel.setY(size * 0.4)
            
            treads_l = self._make_cube("treads_l", size * 1.6, size * 0.3, size * 0.3, (20, 20, 20))
            treads_l.reparentTo(base)
            treads_l.setPos(0, -size*0.6, -size*0.2)
            
            treads_r = self._make_cube("treads_r", size * 1.6, size * 0.3, size * 0.3, (20, 20, 20))
            treads_r.reparentTo(base)
            treads_r.setPos(0, size*0.6, -size*0.2)
            
        elif behavior == "flyer":
            # Swept Wing Flyer
            body = self._make_cube("body", size * 0.5, size * 1.5, size * 0.3, color)
            body.reparentTo(base)
            
            wings = self._make_polygon("wings", size * 2.0, color, sides=3)
            wings.reparentTo(body)
            wings.setH(180)
            
        elif behavior == "charger":
            # Spiked Rammer
            core = self._make_polygon("core", size * 1.2, color, sides=3)
            core.reparentTo(base)
            core.setH(270) # Point forward
            
            spikes = self._make_polygon("spikes", size * 1.5, (255, 50, 50), sides=3)
            spikes.reparentTo(base)
            spikes.setH(270)
            spikes.setZ(0.5)
            spikes.setScale(0.8)

        elif behavior == "swarm":
            # Crystal Shard Swarm
            core = self._make_cube("core", size, size, size, color)
            core.reparentTo(base)
            core.setHpr(45, 45, 45)
            
        elif behavior.startswith("boss_"):
            # Boss - Giant Complex Shape
            core = self._make_cube("boss_core", size * 1.5, size * 1.5, size * 1.5, color)
            core.reparentTo(base)
            
            outer = self._make_ring(size * 2.5, 5.0, (255, 255, 255), segments=6)
            outer.reparentTo(base)
            outer.setHpr(0, 45, 0)
            
            # Boss Aura
            aura = self._make_glow_sprite("boss_aura", size * 4.0, color)
            aura.reparentTo(base)
            aura.setZ(-5)

        else:
            # Default/Standard Enemy (Orb with floating bits)
            core = self._make_sphere("core", size, color)
            core.reparentTo(base)
            
            # Floating rings
            ring = self._make_ring(size * 1.4, 2.0, color)
            ring.reparentTo(base)
            ring.setHpr(45, 10, 0)

        # Common shadow - flat on ground
        shadow = self._make_quad("shadow", float(size) * 1.2, (20, 20, 20), billboard=False)
        shadow.reparentTo(base)
        shadow.setTransparency(True)
        shadow.setAlphaScale(0.3)
        shadow.setZ(-size * 0.4)
        
        return base
    # --- Player ---
    def make_player(self):
        player_node = self._load_model("models/box")
        if player_node is None:
            raise RuntimeError("model loader returned None for player")
        player_node.setScale(12)
        player_node.setColor(0.2, 0.95, 0.7, 1)
        return player_node

    def sync_player(self, player, shake, t=0, aim_dir=None):
        if not hasattr(player, "_node"):
            player._node = self.make_player()
            player._node.reparentTo(self.player_root)
        
        node = player._node
        node.setPos(player.pos.x + shake.x, player.pos.y + shake.y, 10)
        if aim_dir:
            import math
            angle = math.degrees(math.atan2(aim_dir.y, aim_dir.x))
            node.setH(angle)

    def sync_scene(self, t, shake, combat_intensity=0.0):
        # Global effects
        pass

    # --- Enemies ---
    def ensure_enemy(self, enemy):
        if not hasattr(enemy, "_node"):
            behavior = enemy_behavior_name(enemy)
            c = config.ENEMY_COLORS.get(behavior, (200, 200, 200))
            enemy_sizes = {
                "tank": 16.0,
                "swarm": 9.0,
                "flyer": 11.0,
                "engineer": 13.0,
                "charger": 13.0,
                "spitter": 12.0,
                "ranged": 12.0,
                "chaser": 12.0,
                "bomber": 12.0,
            }
            size = 24.0 if str(behavior).startswith("boss_") else float(enemy_sizes.get(str(behavior), 12.0))
            node = self._make_enemy_model(str(behavior), size, c)
            
            # Boss specific outlines are now handled in _make_enemy_model
            
            h_base, h_bob, h_freq, h_spin = self._enemy_height_profile(str(behavior))
            enemy._base_z = h_base
            enemy._bob_amp = h_bob
            enemy._bob_freq = h_freq
            enemy._spin_mult = h_spin

            node.reparentTo(self.enemies_root)
            enemy._node = node
            print(f"DEBUG: Created visual for enemy {behavior} at {enemy.pos}")

    def sync_enemy(self, enemy, shake):
        if hasattr(enemy, "_node"):
            t = float(getattr(enemy, "t", 0.0))
            bob_amp = float(getattr(enemy, "_bob_amp", 0.6))
            bob_freq = float(getattr(enemy, "_bob_freq", 7.0))
            base_z = float(getattr(enemy, "_base_z", 11.0))
            spin_mult = float(getattr(enemy, "_spin_mult", 45.0))
            bob = bob_amp * math.sin(t * bob_freq)
            spin = t * spin_mult
            enemy._node.setPos(enemy.pos.x + shake.x, enemy.pos.y + shake.y, base_z + bob)
            enemy._node.setH(spin)
            enemy._node.setP(2.4 * math.sin(t * (bob_freq * 0.5)))

    def drop_enemy(self, enemy):
        if hasattr(enemy, "_node"):
            enemy._node.removeNode()
            del enemy._node

    # --- Projectiles ---
    def ensure_projectile(self, proj):
        if not hasattr(proj, "_node"):
            owner = getattr(proj, "owner", "enemy")
            ptype = str(getattr(proj, "projectile_type", "bullet"))
            if owner == "player":
                colors = {
                    "bullet": (255, 238, 168),
                    "spread": (255, 215, 150),
                    "plasma": (165, 225, 255),
                    "missile": (255, 188, 120),
                }
                sizes = {"bullet": 1.2, "spread": 0.8, "plasma": 1.5, "missile": 2.0}
            else:
                colors = {
                    "bullet": config.PALETTE["enemy_projectile"],
                    "spread": (255, 100, 150),
                    "plasma": (255, 50, 200),
                    "bomb": (255, 100, 50),
                }
                sizes = {"bullet": 1.4, "spread": 0.9, "plasma": 1.6, "bomb": 2.5}
            c = colors.get(ptype, config.PALETTE["player_projectile"] if owner == "player" else config.PALETTE["enemy_projectile"])
            sz = float(sizes.get(ptype, 1.0))

            node = self._make_projectile_model(owner, ptype, sz, c)
            node.reparentTo(self.projectiles_root)
            proj._node = node

    def sync_projectile(self, proj, shake):
        if hasattr(proj, "_node"):
            pulse = 0.92 + 0.11 * math.sin(float(getattr(proj, "ttl", 0.0)) * 12.5)
            proj._node.setScale(max(0.65, pulse))
            proj._node.setPos(proj.pos.x + shake.x * 0.15, proj.pos.y + shake.y * 0.15, 12.2)
            v = getattr(proj, "vel", None)
            if v and (abs(v.x) > 1e-4 or abs(v.y) > 1e-4):
                proj._node.setH(math.degrees(math.atan2(v.y, v.x)))
                proj._node.setP(0) # Ensure flat
                
                # Visual stretch based on speed
                speed = math.hypot(v.x, v.y)
                stretch = 1.0 + min(1.5, speed / 500.0)
                
                # Dynamic scaling for certain types
                ptype = getattr(proj, "projectile_type", "bullet")
                if ptype == "missile":
                    proj._node.setScale(1.0) # Missile has fixed shape
                elif ptype == "plasma":
                    proj._node.setScale(pulse) # Plasma pulses
                else: 
                    # Bullet/Standard stretch
                    proj._node.setScale(stretch, 1.0, 1.0)
                    
                # Trail effect (simple temporary trail)
                if not hasattr(proj, "_trail"):
                     # Create a container node for the trail
                    proj._trail = self.fx_root.attachNewNode(f"trail_{id(proj)}")
                    proj._trail.setTransparency(True)
                
                # Update trail to go from current pos to previous pos (approximated by velocity)
                # We simply remove the old geometrical content and add new content
                proj._trail.getChildren().detach()
                
                prev_pos = proj.pos - (v * 0.04) # Short trail
                trail_color = config.PALETTE["player_projectile"] if proj.owner == "player" else config.PALETTE["enemy_projectile"]
                
                # Get projectile size based on type
                ptype = getattr(proj, "projectile_type", "bullet")
                owner = getattr(proj, "owner", "enemy")
                if owner == "player":
                    sizes = {"bullet": 1.2, "spread": 0.8, "plasma": 1.5, "missile": 2.0}
                else:
                    sizes = {"bullet": 1.4, "spread": 0.9, "plasma": 1.6, "bomb": 2.5}
                size = float(sizes.get(ptype, 1.0))
                
                # Add a bit of variation/flicker to alpha
                alpha = 0.4 + 0.1 * math.sin(proj.ttl * 20)
                
                seg = self._make_beam_segment(prev_pos, proj.pos, 12.2, trail_color, size * 0.6, alpha)
                seg.reparentTo(proj._trail)

    def _update_beam_segment(self, node: NodePath, start, end, z: float):
         pass # Deprecated, logic moved inline for easier management of the container node
         
    def drop_projectile(self, proj):
        if hasattr(proj, "_trail"):
            proj._trail.removeNode()
            del proj._trail
        if hasattr(proj, "_node"):
            proj._node.removeNode()
            del proj._node

    # --- Powerups ---
    def ensure_powerup(self, p):
        if not hasattr(p, "_node"):
            kind = getattr(p, "kind", "heal")
            c = config.POWERUP_COLORS.get(kind, (255, 255, 255))
            
            # Create a much more visible powerup with glow
            base = NodePath(f"powerup_{kind}")
            
            # Main bright core
            core = self._make_glow_sprite(
                f"powerup_core_{kind}",
                10.0,
                c,
                accent=(255, 255, 255)
            )
            core.reparentTo(base)
            
            # Rotating ring for visual interest
            ring = self._make_ring(12.0, 3.0, c, segments=8)
            ring.reparentTo(base)
            ring.setHpr(45, 0, 0)
            
            # Optional extra glow for certain types
            powerup_types = {
                "ultra": (255, 100, 255),  # Bright magenta
                "shield": (100, 150, 255),  # Bright blue
                "laser": (255, 150, 50),   # Orange
                "heal": (100, 255, 100),   # Bright green
            }
            
            if kind in powerup_types:
                extra_color = powerup_types[kind]
                extra_ring = self._make_ring(15.0, 2.0, extra_color, segments=6)
                extra_ring.reparentTo(base)
                extra_ring.setHpr(90, 45, 0)
            
            base.reparentTo(self.powerups_root)
            p._node = base
            p._pulse_t = 0.0

    def sync_powerup(self, p, shake):
        if hasattr(p, "_node"):
             pulse = 0.95 + 0.12 * math.sin(float(getattr(p, "_pulse_t", 0.0)) * 7.0)
             p._pulse_t = float(getattr(p, "_pulse_t", 0.0)) + 0.016
             p._node.setScale(abs(pulse))
             p._node.setPos(p.pos.x + shake.x, p.pos.y + shake.y, 10.5)

    def drop_powerup(self, p):
        if hasattr(p, "_node"):
            p._node.removeNode()
            del p._node

    # --- Obstacles ---
    def ensure_obstacle(self, ob):
        if not hasattr(ob, "_node"):
            c = (100, 100, 120)
            kind = getattr(ob, "kind", "pillar")
            if kind == "crystal": c = (100, 200, 255)
            elif kind == "crate": c = (120, 100, 80)
            node = self._load_model("models/box")
            if node is None:
                raise RuntimeError("model loader returned None for obstacle")
            node.setScale(max(0.6, float(ob.radius) * 0.08))
            node.setColor(c[0] / 255.0, c[1] / 255.0, c[2] / 255.0, 1.0)
            node.reparentTo(self.obstacles_root)
            ob._node = node

    def sync_obstacle(self, ob, shake):
        if hasattr(ob, "_node"):
            ob._node.setPos(ob.pos.x + shake.x, ob.pos.y + shake.y, 5)

    def drop_obstacle(self, ob):
        if hasattr(ob, "_node"):
            ob._node.removeNode()
            del ob._node

    # --- Lasers ---
    def ensure_laser(self, lb):
        if not hasattr(lb, "_node"):
            lb._node = self.fx_root.attachNewNode("laser_fx")

    def sync_laser(self, lb, shake):
        if not hasattr(lb, "_node"):
            return
        lb._node.getChildren().detach()
        phase = float(getattr(lb, "t", 0.0))
        warn = max(0.0, float(getattr(lb, "warn", 0.0)))
        if warn > 1e-5 and phase < warn:
            ratio = max(0.0, min(1.0, phase / warn))
            pulse = 0.5 + 0.5 * math.sin(phase * 28.0)
            warn_color = (255, 198, 120) if getattr(lb, "owner", "enemy") == "enemy" else (140, 220, 255)
            outer = self._make_beam_segment(lb.start, lb.end, 14.8, warn_color, max(2.2, lb.thickness * 0.45), 0.22 + 0.18 * pulse)
            inner = self._make_beam_segment(lb.start, lb.end, 14.9, (255, 245, 220), max(1.2, lb.thickness * 0.22), 0.16 + 0.24 * ratio)
            outer.reparentTo(lb._node)
            inner.reparentTo(lb._node)
            return

        core = self._make_beam_segment(lb.start, lb.end, 15.1, lb.color, lb.thickness, 0.95)
        glow = self._make_beam_segment(lb.start, lb.end, 15.0, lb.color, max(1.0, lb.thickness * 1.9), 0.26)
        glow.reparentTo(lb._node)
        core.reparentTo(lb._node)

    def drop_laser(self, lb):
        if hasattr(lb, "_node"):
            lb._node.removeNode()
            del lb._node

    # --- Thunder ---
    def ensure_thunder(self, th):
        if not hasattr(th, "_node"):
            th._node = self.fx_root.attachNewNode("thunder_fx")

    def sync_thunder(self, th, shake):
        if not hasattr(th, "_node"):
            return
        th._node.getChildren().detach()
        phase = float(getattr(th, "t", 0.0))
        warn = max(0.0, float(getattr(th, "warn", 0.0)))
        if warn > 1e-5 and phase < warn:
            ratio = max(0.0, min(1.0, phase / warn))
            pulse = 0.5 + 0.5 * math.sin(phase * 24.0)
            warn_outer = self._make_beam_segment(th.start, th.end, 14.85, (140, 210, 255), max(2.2, th.thickness * 0.52), 0.24 + 0.14 * pulse)
            warn_inner = self._make_beam_segment(th.start, th.end, 14.9, (225, 245, 255), max(1.3, th.thickness * 0.25), 0.2 + 0.25 * ratio)
            warn_outer.reparentTo(th._node)
            warn_inner.reparentTo(th._node)
            return

        bolt = self._make_beam_segment(th.start, th.end, 15.1, (220, 245, 255), max(1.0, th.thickness * 0.72), 0.95)
        aura = self._make_beam_segment(th.start, th.end, 15.0, th.color, max(1.0, th.thickness * 1.8), 0.32)
        aura.reparentTo(th._node)
        bolt.reparentTo(th._node)

    def drop_thunder(self, th):
        if hasattr(th, "_node"):
            th._node.removeNode()
            del th._node

    # --- Traps ---
    def ensure_trap(self, tr):
        if not hasattr(tr, "_node"):
            node = NodePath("trap_fx")
            fill = self._make_quad("trap_fill", float(tr.radius), (255, 255, 255))
            fill.setAlphaScale(0.18)
            fill.reparentTo(node)
            ring = self._make_ring(float(tr.radius), 3.4, (255, 255, 255), segments=44)
            ring.setZ(0.2)
            ring.reparentTo(node)
            inner = self._make_ring(float(tr.radius) * 0.62, 2.2, (255, 255, 255), segments=32)
            inner.setZ(0.24)
            inner.reparentTo(node)
            node.reparentTo(self.traps_root)
            tr._node = node
            tr._fill = fill
            tr._ring = ring
            tr._inner = inner

    def _trap_style(self, kind: str):
        k = str(kind or "spike").lower()
        if "warn" in k:
            return (255, 196, 126), (255, 246, 215)
        if "womb" in k:
            return (255, 136, 170), (255, 210, 228)
        if "slam" in k:
            return (255, 166, 118), (255, 232, 198)
        return (255, 148, 108), (255, 226, 196)

    def sync_trap(self, tr, shake):
        if hasattr(tr, "_node"):
            warn_span = max(0.01, float(getattr(tr, "armed_delay", 0.45)))
            armed_ratio = max(0.0, min(1.0, float(getattr(tr, "t", 0.0)) / warn_span))
            pulse = 0.5 + 0.5 * math.sin(float(getattr(tr, "t", 0.0)) * (8.0 + armed_ratio * 8.0))
            base_col, core_col = self._trap_style(getattr(tr, "kind", "spike"))

            tr._node.setPos(tr.pos.x + shake.x * 0.15, tr.pos.y + shake.y * 0.15, 2.0)
            tr._ring.setColor(*self._rgb(base_col), 0.7 + 0.25 * pulse)
            tr._inner.setColor(*self._rgb(core_col), 0.25 + 0.6 * armed_ratio)
            tr._fill.setColor(*self._rgb(base_col), 0.12 + 0.2 * armed_ratio)
            tr._ring.setScale(1.0 + (1.0 - armed_ratio) * 0.08)
            tr._inner.setScale(0.92 + pulse * 0.08)

    def drop_trap(self, tr):
        if hasattr(tr, "_node"):
            tr._node.removeNode()
            del tr._node

    def destroy(self):
        for node in (
            self.floor_root,
            self.traps_root,
            self.obstacles_root,
            self.powerups_root,
            self.enemies_root,
            self.projectiles_root,
            self.player_root,
            self.fx_root,
        ):
            if node:
                node.removeNode()
