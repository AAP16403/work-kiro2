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
        try:
            from direct.showbase import ShowBaseGlobal
            base = getattr(ShowBaseGlobal, "base", None)
            if base is not None:
                return base.loader.loadModel(model_name)
        except Exception:
            pass
        return None
        
    def _make_quad(self, name, size, color, billboard=False):
        cm = CardMaker(name)
        cm.setFrame(-size, size, -size, size)
        node = NodePath(cm.generate())
        if billboard:
            node.setBillboardPointEye()
            node.setTransparency(True)
        else:
             node.setP(-90) # Flat on ground
        
        node.setColor(color[0]/255.0, color[1]/255.0, color[2]/255.0, 1.0)
        node.setTransparency(True)
        node.setTwoSided(True)
        return node
    
    def _make_sphere(self, name, size, color):
        # Fallback to quad if model missing, but try box/sphere
        try:
            node = self._load_model("models/smiley") # Smiley is usually available
            if node is None:
                raise RuntimeError("model loader unavailable")
            node.setScale(max(0.8, size * 0.08))
            node.setColor(color[0]/255.0, color[1]/255.0, color[2]/255.0, 1.0)
            return node
        except:
            return self._make_quad(name, size, color, billboard=True)

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
        halo.setColor(ac[0] / 255.0, ac[1] / 255.0, ac[2] / 255.0, 0.65)
        halo.setAlphaScale(0.75)
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

    # --- Player ---
    def make_player(self):
        try:
            player_node = self._load_model("models/box")
            if player_node is None:
                raise RuntimeError("model loader unavailable")
            player_node.setScale(12)
        except:
             player_node = self._make_quad("player", 12, (0, 255, 0), billboard=True)
        
        player_node.setColor(0, 1, 0, 1)
        player_node.reparentTo(self.player_root) # Ensure attached for first time if returned to caller to attach? 
        # game.py attaches it? No, game.py calls make_player but expects Visuals to handle it mostly?
        # game.py usually: self.visuals.make_player() -> returns nothing or player?
        # game.py code: self.visuals.make_player(). It doesn't store return value.
        # So I must attach it here.
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
            
            node = self._make_glow_sprite(f"enemy_{behavior}", size, c, accent=(255, 255, 255), billboard=True)
            if str(behavior) in ("swarm", "ranged", "flyer"):
                node.setR(45.0)
            elif str(behavior) in ("tank", "charger", "bomber"):
                node.setScale(1.12)
            if str(behavior).startswith("boss_") or str(behavior) in ("tank", "engineer"):
                self._attach_outline(node, size, (255, 255, 255), sides=6, thickness=3.0)

            node.reparentTo(self.enemies_root)
            enemy._node = node
            print(f"DEBUG: Created visual for enemy {behavior} at {enemy.pos}")

    def sync_enemy(self, enemy, shake):
        if hasattr(enemy, "_node"):
            bob = 0.6 * math.sin(float(getattr(enemy, "t", 0.0)) * 8.0)
            enemy._node.setPos(enemy.pos.x + shake.x, enemy.pos.y + shake.y, 10 + bob)

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
                colors = {"bullet": (255, 240, 160), "spread": (255, 220, 150), "plasma": (195, 140, 255), "missile": (255, 190, 130)}
                sizes = {"bullet": 6.0, "spread": 5.5, "plasma": 6.4, "missile": 7.2}
            else:
                colors = {"bullet": (255, 125, 125), "spread": (255, 140, 100), "plasma": (255, 110, 220), "bomb": (255, 160, 100)}
                sizes = {"bullet": 6.2, "spread": 6.0, "plasma": 6.8, "bomb": 7.6}
            c = colors.get(ptype, (255, 200, 120) if owner == "player" else (255, 120, 120))
            sz = float(sizes.get(ptype, 4.6))

            node = self._make_glow_sprite("projectile", sz, c, accent=(255, 255, 255), billboard=True)
            node.reparentTo(self.projectiles_root)
            proj._node = node

    def sync_projectile(self, proj, shake):
        if hasattr(proj, "_node"):
            proj._node.setPos(proj.pos.x, proj.pos.y, 12)
            v = getattr(proj, "vel", None)
            if v and (abs(v.x) > 1e-4 or abs(v.y) > 1e-4):
                proj._node.setH(math.degrees(math.atan2(v.y, v.x)))

    def drop_projectile(self, proj):
        if hasattr(proj, "_node"):
            proj._node.removeNode()
            del proj._node

    # --- Powerups ---
    def ensure_powerup(self, p):
        if not hasattr(p, "_node"):
            kind = getattr(p, "kind", "heal")
            c = config.POWERUP_COLORS.get(kind, (255, 255, 255))
            node = self._make_sphere(f"powerup_{kind}", 8.0, c)
            node.reparentTo(self.powerups_root)
            p._node = node

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
            
            node = self._make_quad(f"obstacle_{kind}", float(ob.radius), c, billboard=True)
            # Maybe use cylinder if possible?
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
            # Use LineSegs for laser
            ls = LineSegs()
            ls.setColor(lb.color[0]/255.0, lb.color[1]/255.0, lb.color[2]/255.0, 1.0)
            ls.setThickness(lb.thickness)
            ls.moveTo(lb.start.x, lb.start.y, 15)
            ls.drawTo(lb.end.x, lb.end.y, 15)
            node = self.fx_root.attachNewNode(ls.create())
            lb._node = node
            lb._ls = ls # Keep ref to update? LineSegs create() returns a geom, difficult to update dynamic geometry efficiently without regenerating.
            # For meaningful updates (start/end moving), we might need to regenerate.
            # But lasers usually just fade or stay briefly.

    def sync_laser(self, lb, shake):
        # If laser moves or we need to update visual?
        # For now assume static for TTL
        pass

    def drop_laser(self, lb):
        if hasattr(lb, "_node"):
            lb._node.removeNode()
            del lb._node

    # --- Thunder ---
    def ensure_thunder(self, th):
        if not hasattr(th, "_node"):
            ls = LineSegs()
            ls.setColor(th.color[0]/255.0, th.color[1]/255.0, th.color[2]/255.0, 1.0)
            ls.setThickness(th.thickness)
            ls.moveTo(th.start.x, th.start.y, 15)
            ls.drawTo(th.end.x, th.end.y, 15)
            # Add jagged points?
            node = self.fx_root.attachNewNode(ls.create())
            th._node = node

    def sync_thunder(self, th, shake):
        pass

    def drop_thunder(self, th):
        if hasattr(th, "_node"):
            th._node.removeNode()
            del th._node

    # --- Traps ---
    def ensure_trap(self, tr):
        if not hasattr(tr, "_node"):
            node = self._make_quad("trap", float(tr.radius), (255, 50, 50))
            node.reparentTo(self.traps_root)
            tr._node = node

    def sync_trap(self, tr, shake):
        if hasattr(tr, "_node"):
            tr._node.setPos(tr.pos.x + shake.x, tr.pos.y + shake.y, 2)

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
