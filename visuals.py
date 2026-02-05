"""Visual rendering system."""

from typing import Dict, Optional

import pyglet
from pyglet import shapes
from pyglet.graphics import Group

from config import ENEMY_COLORS
from utils import to_iso, Vec2


class GroupCache:
    """Cache for rendering groups for depth sorting."""

    def __init__(self):
        self._cache: Dict[int, object] = {}

    def get(self, order: int):
        if Group is None:
            return None
        g = self._cache.get(order)
        if g is None:
            g = Group(order=order)
            self._cache[order] = g
        return g


class RenderHandle:
    """Handle for managing render objects."""

    def __init__(self, *objs):
        self.objs = list(objs)

    def set_group(self, group):
        if group is None:
            return
        for o in self.objs:
            o.group = group

    def delete(self):
        for o in self.objs:
            if hasattr(o, "delete"):
                o.delete()


class Visuals:
    """Visual rendering system."""

    def __init__(self, batch, group_cache: GroupCache):
        self.batch = batch
        self.groups = group_cache

        self._enemy_handles: Dict[int, RenderHandle] = {}
        self._proj_handles: Dict[int, RenderHandle] = {}
        self._power_handles: Dict[int, RenderHandle] = {}
        self._trap_handles: Dict[int, RenderHandle] = {}
        self._laser_handles: Dict[int, RenderHandle] = {}
        self._player_handle: Optional[RenderHandle] = None

    def make_player(self):
        """Create player visual."""
        sh = shapes.Ellipse(0, 0, 22, 8, color=(0, 0, 0), batch=self.batch)
        sh.opacity = 120
        body = shapes.Circle(0, 0, 14, color=(70, 160, 220), batch=self.batch)
        core = shapes.Circle(0, 0, 9, color=(100, 200, 255), batch=self.batch)
        visor = shapes.Rectangle(0, 0, 12, 4, color=(240, 245, 255), batch=self.batch)
        visor.anchor_x = 6
        visor.anchor_y = 2
        self._player_handle = RenderHandle(sh, body, core, visor)

    def sync_player(self, player, shake: Vec2):
        """Update player visual position."""
        assert self._player_handle is not None
        sh, body, core, visor = self._player_handle.objs
        sx, sy = to_iso(player.pos, shake)
        sh.x, sh.y = sx, sy - 18
        body.x, body.y = sx, sy
        core.x, core.y = sx, sy
        visor.x, visor.y = sx + 2, sy + 2
        self._player_handle.set_group(self.groups.get(int(sy)))

    def ensure_enemy(self, enemy):
        """Ensure enemy visual exists."""
        if id(enemy) in self._enemy_handles:
            return
        base = ENEMY_COLORS.get(enemy.behavior, (200, 120, 120))

        sh = shapes.Ellipse(0, 0, 20, 7, color=(0, 0, 0), batch=self.batch)
        sh.opacity = 110

        if enemy.behavior == "engineer":
            body = shapes.Circle(0, 0, 13, color=base, batch=self.batch)
            backpack = shapes.Rectangle(0, 0, 12, 10, color=(40, 60, 70), batch=self.batch)
            backpack.anchor_x = 6
            backpack.anchor_y = 5
            backpack.opacity = 220
            visor = shapes.Rectangle(0, 0, 10, 4, color=(230, 255, 245), batch=self.batch)
            visor.anchor_x = 5
            visor.anchor_y = 2
            visor.opacity = 210
            tool = shapes.Line(0, 0, 10, 10, thickness=2, color=(240, 240, 240), batch=self.batch)
            tool2 = shapes.Line(0, 0, 10, -10, thickness=2, color=(240, 240, 240), batch=self.batch)
            self._enemy_handles[id(enemy)] = RenderHandle(sh, body, backpack, visor, tool, tool2)
            return

        body = shapes.Circle(0, 0, 12, color=base, batch=self.batch)
        shine = shapes.Circle(0, 0, 7, color=(255, 255, 255), batch=self.batch)
        shine.opacity = 60
        eye1 = shapes.Circle(0, 0, 2, color=(20, 20, 20), batch=self.batch)
        eye2 = shapes.Circle(0, 0, 2, color=(20, 20, 20), batch=self.batch)
        self._enemy_handles[id(enemy)] = RenderHandle(sh, body, shine, eye1, eye2)

    def sync_enemy(self, enemy, shake: Vec2):
        """Update enemy visual position."""
        h = self._enemy_handles[id(enemy)]
        sx, sy = to_iso(enemy.pos, shake)
        if enemy.behavior == "engineer":
            sh, body, backpack, visor, tool, tool2 = h.objs
            sh.x, sh.y = sx, sy - 18
            body.x, body.y = sx, sy
            backpack.x, backpack.y = sx - 12, sy + 2
            visor.x, visor.y = sx + 1, sy + 2
            tool.x, tool.y, tool.x2, tool.y2 = sx + 10, sy + 6, sx + 16, sy + 0
            tool2.x, tool2.y, tool2.x2, tool2.y2 = sx + 10, sy + 6, sx + 16, sy + 12
            h.set_group(self.groups.get(int(sy)))
            return

        sh, body, shine, eye1, eye2 = h.objs
        sh.x, sh.y = sx, sy - 18
        body.x, body.y = sx, sy
        shine.x, shine.y = sx - 3, sy + 3
        eye1.x, eye1.y = sx - 4, sy + 1
        eye2.x, eye2.y = sx + 2, sy + 1
        h.set_group(self.groups.get(int(sy)))

    def drop_enemy(self, enemy):
        """Remove enemy visual."""
        h = self._enemy_handles.pop(id(enemy), None)
        if h:
            h.delete()

    def ensure_projectile(self, proj):
        """Ensure projectile visual exists."""
        if id(proj) in self._proj_handles:
            return
        
        # Different visuals for different projectile types
        projectile_type = getattr(proj, 'projectile_type', 'bullet')
        
        if projectile_type == "missile":
            # Larger red/orange missile
            sh = shapes.Circle(0, 0, 6, color=(200, 100, 50), batch=self.batch)
            core = shapes.Circle(0, 0, 3, color=(255, 150, 100), batch=self.batch)
        elif projectile_type == "plasma":
            # Purple plasma projectile
            sh = shapes.Circle(0, 0, 4, color=(150, 100, 255), batch=self.batch)
            core = shapes.Circle(0, 0, 2, color=(200, 150, 255), batch=self.batch)
        else:  # bullet or default
            # Standard yellow bullet
            sh = shapes.Circle(0, 0, 4, color=(255, 245, 190), batch=self.batch)
            core = shapes.Circle(0, 0, 2, color=(255, 255, 255), batch=self.batch)
        
        self._proj_handles[id(proj)] = RenderHandle(sh, core)

    def sync_projectile(self, proj, shake: Vec2):
        """Update projectile visual position."""
        h = self._proj_handles[id(proj)]
        sh, core = h.objs
        sx, sy = to_iso(proj.pos, shake)
        sh.x, sh.y = sx, sy
        core.x, core.y = sx, sy
        h.set_group(self.groups.get(int(sy)))

    def drop_projectile(self, proj):
        """Remove projectile visual."""
        h = self._proj_handles.pop(id(proj), None)
        if h:
            h.delete()

    def ensure_powerup(self, p):
        """Ensure powerup visual exists."""
        if id(p) in self._power_handles:
            return
        
        # Powerup type - distinct bright colors
        color, glyph, size = {
            "heal": ((100, 255, 150), "+", 14),      # Bright green
            "damage": ((255, 100, 100), "!", 14),    # Bright red  
            "speed": ((100, 200, 255), ">", 14),     # Bright blue
            "firerate": ((255, 220, 100), "*", 14),  # Bright yellow/gold
            "shield": ((120, 220, 255), "O", 14),    # Cyan shield
            "laser": ((255, 120, 255), "=", 14),     # Magenta beam
        }.get(p.kind, ((200, 200, 200), "?", 12))

        # Large, glowing center orb
        orb = shapes.Circle(0, 0, size, color=color, batch=self.batch)
        
        # Inner bright core
        core = shapes.Circle(0, 0, size // 2, color=(255, 255, 255), batch=self.batch)
        core.opacity = 200
        
        # Outer pulsing rings for visibility
        ring1 = shapes.Circle(0, 0, size + 4, color=(255, 255, 255), batch=self.batch)
        ring1.opacity = 200
        
        ring2 = shapes.Circle(0, 0, size + 10, color=color, batch=self.batch)
        ring2.opacity = 80
        
        # Symbol label - larger and more visible
        label = pyglet.text.Label(
            glyph,
            font_name="Consolas",
            font_size=16,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            batch=self.batch,
            color=(255, 255, 255, 255),
        )
        self._power_handles[id(p)] = RenderHandle(ring2, ring1, orb, core, label)

    def sync_powerup(self, p, shake: Vec2):
        """Update powerup visual position."""
        h = self._power_handles[id(p)]
        ring2, ring1, orb, core, label = h.objs
        sx, sy = to_iso(p.pos, shake)
        ring2.x, ring2.y = sx, sy
        ring1.x, ring1.y = sx, sy
        orb.x, orb.y = sx, sy
        core.x, core.y = sx, sy
        label.x, label.y = sx, sy
        h.set_group(self.groups.get(int(sy)))

    def drop_powerup(self, p):
        """Remove powerup visual."""
        h = self._power_handles.pop(id(p), None)
        if h:
            h.delete()

    def ensure_trap(self, tr):
        if id(tr) in self._trap_handles:
            return
        base = shapes.Circle(0, 0, tr.radius, color=(220, 120, 60), batch=self.batch)
        base.opacity = 80
        core = shapes.Circle(0, 0, max(6, tr.radius * 0.25), color=(255, 220, 180), batch=self.batch)
        core.opacity = 200
        spike = shapes.Line(0, 0, 0, 0, thickness=3, color=(255, 210, 170), batch=self.batch)
        spike2 = shapes.Line(0, 0, 0, 0, thickness=3, color=(255, 210, 170), batch=self.batch)
        self._trap_handles[id(tr)] = RenderHandle(base, core, spike, spike2)

    def sync_trap(self, tr, shake: Vec2):
        h = self._trap_handles[id(tr)]
        base, core, spike, spike2 = h.objs
        sx, sy = to_iso(tr.pos, shake)
        base.x, base.y = sx, sy
        core.x, core.y = sx, sy
        arm = tr.radius * 0.75
        spike.x, spike.y, spike.x2, spike.y2 = sx - arm, sy - 2, sx + arm, sy + 2
        spike2.x, spike2.y, spike2.x2, spike2.y2 = sx - 2, sy - arm, sx + 2, sy + arm
        h.set_group(self.groups.get(int(sy)))

    def drop_trap(self, tr):
        h = self._trap_handles.pop(id(tr), None)
        if h:
            h.delete()

    def ensure_laser(self, lb):
        if id(lb) in self._laser_handles:
            return
        line = shapes.Line(0, 0, 0, 0, thickness=lb.thickness, color=(255, 120, 255), batch=self.batch)
        line.opacity = 200
        core = shapes.Line(0, 0, 0, 0, thickness=max(2, lb.thickness * 0.35), color=(255, 255, 255), batch=self.batch)
        core.opacity = 180
        self._laser_handles[id(lb)] = RenderHandle(line, core)

    def sync_laser(self, lb, shake: Vec2):
        h = self._laser_handles[id(lb)]
        line, core = h.objs
        x1, y1 = to_iso(lb.start, shake)
        x2, y2 = to_iso(lb.end, shake)
        line.x, line.y, line.x2, line.y2 = x1, y1, x2, y2
        core.x, core.y, core.x2, core.y2 = x1, y1, x2, y2
        h.set_group(self.groups.get(int(max(y1, y2))))

    def drop_laser(self, lb):
        h = self._laser_handles.pop(id(lb), None)
        if h:
            h.delete()
