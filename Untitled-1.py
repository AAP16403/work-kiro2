# Pyglet isometric room survival prototype
# Controls: WASD/Arrows move, hold Left Mouse to shoot, ESC for menu.
# Install: py -m pip install pyglet

import random

import pyglet

pyglet.options["shadow_window"] = False

import config
from config import SCREEN_W, SCREEN_H, FPS, PLAYER_SPEED, PROJECTILE_SPEED, WAVE_COOLDOWN, HUD_TEXT, ENEMY_COLORS, POWERUP_COLORS
from player import Player
from map import Room
from level import GameState, spawn_wave, maybe_spawn_powerup
from enemy import update_enemy
from powerup import apply_powerup
from projectile import Projectile
from utils import (
    Vec2,
    clamp_to_room,
    iso_to_world,
    dist,
    set_view_size,
    compute_room_radius,
    point_segment_distance,
    resolve_circle_obstacles,
)
from visuals import Visuals, GroupCache
from weapons import get_weapon_for_wave, spawn_weapon_projectiles, get_weapon_color
from particles import ParticleSystem
from menu import Menu, SettingsMenu, PauseMenu, GameOverMenu
from hazards import LaserBeam
from layout import generate_obstacles


# ============================
# Main Game Class
# ============================
class Game(pyglet.window.Window):
    """Main game window and logic."""

    def __init__(self):
        super().__init__(width=SCREEN_W, height=SCREEN_H, caption="Isometric Room Survival (pyglet)", vsync=True)
        for event_name in ("on_activate", "on_deactivate"):
            type(self).register_event_type(event_name)
        set_view_size(self.width, self.height)
        self._display_size = self._get_display_size()
        if self._display_size:
            dw, dh = self._display_size
            if self.width > dw or self.height > dh:
                self.set_size(min(self.width, dw), min(self.height, dh))
        self._update_room_radius_from_view()

        # Game state: "menu", "settings", "playing", "paused", "game_over"
        self.game_state = "menu"
        self.settings = {
            "difficulty": "normal",
            "window_size": (self.width, self.height),
            "fullscreen": False,
            "arena_margin": float(getattr(config, "ARENA_MARGIN", 0.97)),
        }
        
        # Menu system
        self.main_menu = Menu(self.width, self.height)
        self.settings_menu = SettingsMenu(self.width, self.height, self._on_settings_change, display_size=self._display_size)
        self.pause_menu = PauseMenu(self.width, self.height)
        self.game_over_menu = GameOverMenu(self.width, self.height)
        
        # Game objects (will be initialized when game starts)
        self.batch = None
        self.groups = None
        self.room = None
        self.state = None
        self.player = None
        self.visuals = None
        self.particle_system = None
        self.hud = None
        
        self.keys = pyglet.window.key.KeyStateHandler()
        self.push_handlers(self.keys)

        self.mouse_xy = (self.width / 2, self.height / 2)
        self.mouse_down = False

        pyglet.clock.schedule_interval(self.update, 1.0 / FPS)

    def _get_display_size(self):
        try:
            display = pyglet.canvas.get_display()
            screen = display.get_default_screen()
            return (int(screen.width), int(screen.height))
        except Exception:
            return None

    def _update_room_radius_from_view(self):
        margin = float(getattr(config, "ARENA_MARGIN", 0.92))
        config.ROOM_RADIUS = compute_room_radius(self.width, self.height, margin=margin)

    def _prune_dead_weak_handlers(self) -> None:
        """Remove collected WeakMethod handlers to prevent pyglet assertions on dispatch."""
        try:
            from pyglet.event import WeakMethod
        except Exception:
            return

        stack = getattr(self, "_event_stack", None)
        if not stack:
            return

        for frame in list(stack):
            if not isinstance(frame, dict):
                continue
            for event_name, handler in list(frame.items()):
                is_pyglet_weakmethod = isinstance(handler, WeakMethod)
                is_weakmethod_like = (
                    handler.__class__.__name__ == "WeakMethod"
                    and callable(getattr(handler, "__call__", None))
                )
                if (is_pyglet_weakmethod or is_weakmethod_like) and handler() is None:
                    del frame[event_name]

    def dispatch_event(self, *args):
        self._prune_dead_weak_handlers()
        try:
            return super().dispatch_event(*args)
        except AssertionError:
            if args and args[0] in ("on_activate", "on_deactivate"):
                return False
            raise
    
    def _init_game(self):
        """Initialize game objects."""
        self.batch = pyglet.graphics.Batch()
        self.groups = GroupCache()
        self.room = Room(self.batch, self.width, self.height)

        difficulty = str(self.settings.get("difficulty", "normal")).lower()
        self.state = GameState(difficulty=difficulty)
        if difficulty == "easy":
            self.state.max_enemies = 10
            self._incoming_damage_mult = 0.85
        elif difficulty == "hard":
            self.state.max_enemies = 14
            self._incoming_damage_mult = 1.15
        else:
            self.state.max_enemies = 12
            self._incoming_damage_mult = 1.0
        if config.ENABLE_OBSTACLES:
            self.state.layout_seed = random.randint(0, 1_000_000_000)
            self.state.layout_segment = 0
            self.state.obstacles = generate_obstacles(
                self.state.layout_seed, self.state.layout_segment, config.ROOM_RADIUS, difficulty=self.state.difficulty
            )
        else:
            self.state.obstacles = []
        self.player = Player(pos=Vec2(0.0, 0.0))
        self.player.current_weapon = get_weapon_for_wave(1)

        self.visuals = Visuals(self.batch, self.groups)
        self.visuals.make_player()
        
        self.particle_system = ParticleSystem(self.batch)

        self.hud = pyglet.text.Label(
            "",
            font_name="Consolas",
            font_size=14,
            x=12,
            y=self.height - 14,
            anchor_x="left",
            anchor_y="top",
            color=(HUD_TEXT[0], HUD_TEXT[1], HUD_TEXT[2], 255),
        )

    def _regen_layout(self, segment: int | None = None):
        if not config.ENABLE_OBSTACLES:
            if self.state:
                self.state.obstacles = []
            return
        if not self.state:
            return
        if segment is None:
            segment = int(getattr(self.state, "layout_segment", 0))
        # Drop visuals for old obstacles.
        if self.visuals:
            for ob in list(getattr(self.state, "obstacles", [])):
                self.visuals.drop_obstacle(ob)
        self.state.layout_segment = int(segment)
        self.state.obstacles = generate_obstacles(
            int(getattr(self.state, "layout_seed", 0)),
            self.state.layout_segment,
            config.ROOM_RADIUS,
            difficulty=getattr(self.state, "difficulty", "normal"),
        )

    def _damage_player(self, amount: int):
        if amount <= 0:
            return
        mult = getattr(self, "_incoming_damage_mult", 1.0)
        if mult != 1.0:
            amount = max(1, int(round(amount * mult)))
        if self.player.shield > 0:
            absorbed = min(self.player.shield, amount)
            self.player.shield -= absorbed
            amount -= absorbed
            if absorbed > 0 and self.particle_system:
                self.particle_system.add_shield_hit(self.player.pos, absorbed)
        if amount > 0:
            self.player.hp -= amount

    def _enemy_radius(self, enemy) -> float:
        b = getattr(enemy, "behavior", "")
        if b.startswith("boss_"):
            return 24.0
        return {
            "tank": 16.0,
            "swarm": 9.0,
            "flyer": 11.0,
            "engineer": 13.0,
            "charger": 13.0,
            "spitter": 12.0,
            "ranged": 12.0,
            "chaser": 12.0,
        }.get(b, 12.0)
    
    def _start_game(self):
        """Start the game."""
        self._init_game()
        self.game_state = "playing"
    
    def _open_settings(self):
        """Open settings menu."""
        self.game_state = "settings"
    
    def _quit_game(self):
        """Quit the game."""
        def _close(dt):
            self.close()
            pyglet.app.exit()
        pyglet.clock.schedule_once(_close, 0)
    
    def _on_settings_change(self, value):
        """Callback for settings changes."""
        if not isinstance(value, dict):
            return
        self.settings.update(value)
        fullscreen = value.get("fullscreen")
        arena_margin = value.get("arena_margin")
        if arena_margin is not None:
            try:
                config.ARENA_MARGIN = float(arena_margin)
            except Exception:
                pass
            self._update_room_radius_from_view()
            if self.room:
                self.room.rebuild()
            if self.player:
                self.player.pos = clamp_to_room(self.player.pos, config.ROOM_RADIUS)

        if fullscreen is True:
            if not self.fullscreen:
                self._windowed_size = (self.width, self.height)
            self.set_fullscreen(True)
            return

        if fullscreen is False and self.fullscreen:
            self.set_fullscreen(False)

        size = value.get("window_size")
        if size and isinstance(size, (tuple, list)) and len(size) == 2:
            w, h = int(size[0]), int(size[1])
            if self._display_size:
                dw, dh = self._display_size
                w = min(w, dw)
                h = min(h, dh)
            if w > 0 and h > 0 and (w != self.width or h != self.height):
                self.set_size(w, h)

    def on_resize(self, width, height):
        super().on_resize(width, height)
        self.settings["window_size"] = (width, height)
        self.settings["fullscreen"] = bool(getattr(self, "fullscreen", False))
        if self.game_state != "playing":
            self.mouse_xy = (width / 2, height / 2)
        set_view_size(width, height)
        self._update_room_radius_from_view()

        self.main_menu.resize(width, height)
        self.settings_menu.resize(width, height)
        self.pause_menu.resize(width, height)
        self.game_over_menu.resize(width, height)

        if self.hud:
            self.hud.y = height - 14

        if self.room:
            self.room.resize(width, height)
        if self.state:
            if config.ENABLE_OBSTACLES:
                self._regen_layout(getattr(self.state, "layout_segment", 0))
    
    def _return_to_menu(self):
        """Return to main menu."""
        self.game_state = "menu"
        # Clean up game objects
        if self.batch:
            self.batch = None
        self.groups = None
        self.room = None
        self.state = None
        self.player = None
        self.visuals = None
        self.particle_system = None

    def on_mouse_motion(self, x, y, dx, dy):
        self.mouse_xy = (x, y)
        if self.game_state == "menu":
            self.main_menu.on_mouse_motion(x, y)
        elif self.game_state == "settings":
            self.settings_menu.on_mouse_motion(x, y)
        elif self.game_state == "paused":
            self.pause_menu.on_mouse_motion(x, y)
        elif self.game_state == "game_over":
            self.game_over_menu.on_mouse_motion(x, y)

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        self.mouse_xy = (x, y)
        if self.game_state == "settings":
            self.settings_menu.on_mouse_drag(x, y, dx, dy)

    def on_mouse_press(self, x, y, button, modifiers):
        if self.game_state == "menu":
            action = self.main_menu.on_mouse_press(x, y, button)
            if action == "start_game":
                self._start_game()
            elif action == "settings":
                self._open_settings()
            elif action == "quit":
                self._quit_game()
        elif self.game_state == "settings":
            action = self.settings_menu.on_mouse_press(x, y, button)
            if action == "back":
                self.game_state = "menu"
        elif self.game_state == "paused":
            action = self.pause_menu.on_mouse_press(x, y, button)
            if action == "resume":
                self.game_state = "playing"
            elif action == "quit_to_menu":
                self._return_to_menu()
        elif self.game_state == "game_over":
            action = self.game_over_menu.on_mouse_press(x, y, button)
            if action == "retry":
                self._start_game()
            elif action == "quit_to_menu":
                self._return_to_menu()
        elif self.game_state == "playing":
            if button == pyglet.window.mouse.LEFT:
                self.mouse_down = True

    def on_mouse_release(self, x, y, button, modifiers):
        if button == pyglet.window.mouse.LEFT:
            self.mouse_down = False
        if self.game_state == "settings":
            self.settings_menu.on_mouse_release(x, y, button)
    
    def on_key_press(self, symbol, modifiers):
        """Handle key presses."""
        if symbol == pyglet.window.key.ESCAPE:
            if self.game_state == "playing":
                self.game_state = "paused"
            elif self.game_state == "paused":
                self.game_state = "playing"
            elif self.game_state == "settings":
                self.game_state = "menu"

    def on_close(self):
        """Handle window close event."""
        def _close(dt):
            self.close()
            pyglet.app.exit()
        pyglet.clock.schedule_once(_close, 0)
        return True

    def _input_dir(self) -> Vec2:
        """Get input direction from keyboard.
        
        Isometric controls:
        W: Northeast, S: Southwest, A: Northwest, D: Southeast
        """
        k = pyglet.window.key
        d = Vec2(0.0, 0.0)
        # W: Move northeast (x+, y+)
        if self.keys[k.W] or self.keys[k.UP]:
            d.x += 1
            d.y += 1
        # S: Move southwest (x-, y-)
        if self.keys[k.S] or self.keys[k.DOWN]:
            d.x -= 1
            d.y -= 1
        # A: Move northwest (x-, y+)
        if self.keys[k.A] or self.keys[k.LEFT]:
            d.x -= 1
            d.y += 1
        # D: Move southeast (x+, y-)
        if self.keys[k.D] or self.keys[k.RIGHT]:
            d.x += 1
            d.y -= 1
        return d

    def update(self, dt: float):
        """Update game logic."""
        if self.game_state == "menu":
            self.main_menu.update(dt)
        elif self.game_state == "settings":
            self.settings_menu.update(dt)

        if self.game_state != "playing":
            return
        
        if not self.state:
            return
        
        s = self.state
        s.time += dt

        # Waves
        if not s.wave_active and (s.time - s.last_wave_clear) >= WAVE_COOLDOWN:
            spawn_wave(s, Vec2(0.0, 0.0))

        # Vortex aura (rare powerup): damages nearby enemies and emits swirl particles.
        if s.time < self.player.vortex_until:
            self.particle_system.add_vortex_swirl(self.player.pos, s.time, self.player.vortex_radius)
            dps = self.player.vortex_dps
            for e in list(s.enemies):
                if dist(e.pos, self.player.pos) <= self.player.vortex_radius:
                    acc = getattr(e, "_vortex_acc", 0.0) + dps * dt
                    dmg = int(acc)
                    e._vortex_acc = acc - dmg
                    if dmg > 0:
                        e.hp -= dmg
                        s.shake = max(s.shake, 2.5)
                        if e.hp <= 0:
                            s.enemies.remove(e)
                            self.visuals.drop_enemy(e)
                            from level import spawn_powerup_on_kill
                            spawn_powerup_on_kill(s, e.pos)

        # Traps
        for tr in list(getattr(s, "traps", [])):
            tr.t += dt
            tr.ttl -= dt
            if tr.ttl <= 0:
                s.traps.remove(tr)
                self.visuals.drop_trap(tr)
                continue
            if tr.damage > 0 and tr.t >= tr.armed_delay and dist(tr.pos, self.player.pos) <= tr.radius:
                self._damage_player(tr.damage)
                s.shake = max(s.shake, 10.0)
                s.traps.remove(tr)
                self.visuals.drop_trap(tr)

        # Thunder lines (boss hazard)
        for th in list(getattr(s, "thunders", [])):
            th.t += dt
            if th.t >= th.warn and not th.hit_done:
                if point_segment_distance(self.player.pos, th.start, th.end) <= th.thickness * 0.6:
                    th.hit_done = True
                    self._damage_player(th.damage)
                    s.shake = max(s.shake, 14.0)
                    self.particle_system.add_laser_beam(th.start, th.end, color=th.color)
            if th.t >= th.warn + th.ttl:
                s.thunders.remove(th)
                self.visuals.drop_thunder(th)

        # Player movement
        old_pos = Vec2(self.player.pos.x, self.player.pos.y)
        idir = self._input_dir()
        if idir.length() > 0:
            nd = idir.normalized()
            self.player.pos = self.player.pos + nd * self.player.speed * dt
            self.particle_system.add_step_dust(self.player.pos, nd)
        self.player.pos = clamp_to_room(self.player.pos, config.ROOM_RADIUS * 0.9)
        if config.ENABLE_OBSTACLES and getattr(s, "obstacles", None):
            self.player.pos = resolve_circle_obstacles(self.player.pos, 14.0, s.obstacles)
            self.player.pos = clamp_to_room(self.player.pos, config.ROOM_RADIUS * 0.9)
        if dt > 1e-6:
            player_vel = (self.player.pos - old_pos) * (1.0 / dt)
        else:
            player_vel = Vec2(0.0, 0.0)

        # Player shooting
        if self.mouse_down and (s.time - self.player.last_shot) >= self.player.fire_rate:
            world_mouse = iso_to_world(self.mouse_xy)
            aim = (world_mouse - self.player.pos).normalized()
            muzzle = self.player.pos + aim * 14.0
            
            if s.time < self.player.laser_until:
                beam_len = config.ROOM_RADIUS * 1.6
                end = muzzle + aim * beam_len
                dmg = int(self.player.damage * 0.9) + 14
                beam = LaserBeam(start=muzzle, end=end, damage=dmg, thickness=12.0, ttl=0.08, owner="player")
                s.lasers.append(beam)
                self.particle_system.add_laser_beam(muzzle, end, color=beam.color)
                for e in list(s.enemies):
                    if point_segment_distance(e.pos, muzzle, end) <= 14:
                        e.hp -= dmg
                        s.shake = max(s.shake, 4.0)
                        if e.hp <= 0:
                            s.enemies.remove(e)
                            self.visuals.drop_enemy(e)
                            from level import spawn_powerup_on_kill
                            spawn_powerup_on_kill(s, e.pos)
            else:
                # Use current weapon to spawn projectiles
                weapon = self.player.current_weapon
                projectiles = spawn_weapon_projectiles(muzzle, aim, weapon, s.time, self.player.damage)
                s.projectiles.extend(projectiles)
            
            # Muzzle flash particle effect
            self.particle_system.add_muzzle_flash(muzzle, aim)
            
            self.player.last_shot = s.time

        # Enemies
        for e in list(s.enemies):
            update_enemy(e, self.player.pos, s, dt, player_vel=player_vel)
            e.pos = clamp_to_room(e.pos, config.ROOM_RADIUS * 0.96)
            if config.ENABLE_OBSTACLES and getattr(s, "obstacles", None):
                e.pos = resolve_circle_obstacles(e.pos, self._enemy_radius(e), s.obstacles)
                e.pos = clamp_to_room(e.pos, config.ROOM_RADIUS * 0.96)
            if dist(e.pos, self.player.pos) < 12:
                self._damage_player(10)
                s.enemies.remove(e)
                self.visuals.drop_enemy(e)
                s.shake = 9.0
                # Chance to spawn powerup on kill
                from level import spawn_powerup_on_kill
                spawn_powerup_on_kill(s, self.player.pos)

        # Projectiles
        for p in list(s.projectiles):
            p.pos = p.pos + p.vel * dt
            p.ttl -= dt
            if config.ENABLE_OBSTACLES and getattr(s, "obstacles", None):
                blocked = False
                for ob in s.obstacles:
                    if dist(p.pos, ob.pos) <= ob.radius:
                        blocked = True
                        break
                if blocked:
                    s.projectiles.remove(p)
                    self.visuals.drop_projectile(p)
                    self.particle_system.add_hit_particles(p.pos, (160, 160, 170))
                    continue
            if p.ttl <= 0:
                s.projectiles.remove(p)
                self.visuals.drop_projectile(p)
                continue

        # Collisions
        for p in list(s.projectiles):
            if p.owner == "player":
                for e in list(s.enemies):
                    if dist(p.pos, e.pos) < 11:
                        e.hp -= p.damage
                        s.shake = max(s.shake, 4.0)
                        
                        # Hit particles
                        enemy_color = ENEMY_COLORS.get(e.behavior, (200, 200, 200))
                        self.particle_system.add_hit_particles(e.pos, enemy_color)
                        
                        if e.hp <= 0:
                            s.enemies.remove(e)
                            self.visuals.drop_enemy(e)
                            
                            # Death explosion
                            self.particle_system.add_death_explosion(e.pos, enemy_color, e.behavior)
                            
                            # Explosion damage (Tank enemies explode violently)
                            if e.behavior == "tank":
                                if dist(e.pos, self.player.pos) < 70:
                                    self._damage_player(15)
                                    s.shake = 15.0
                            
                            # Chance to spawn powerup on kill
                            from level import spawn_powerup_on_kill
                            spawn_powerup_on_kill(s, e.pos)
                        if p in s.projectiles:
                            s.projectiles.remove(p)
                            self.visuals.drop_projectile(p)
                        break
            else:
                if dist(p.pos, self.player.pos) < 12:
                    self._damage_player(p.damage)
                    s.shake = max(s.shake, 6.0)
                    if p in s.projectiles:
                        s.projectiles.remove(p)
                        self.visuals.drop_projectile(p)

        # Powerups
        for pu in list(s.powerups):
            if dist(pu.pos, self.player.pos) < 16:
                # Particle effect for powerup collection
                color = POWERUP_COLORS.get(pu.kind, (200, 200, 200))
                self.particle_system.add_powerup_collection(pu.pos, color)
                
                apply_powerup(self.player, pu, s.time)
                s.powerups.remove(pu)
                self.visuals.drop_powerup(pu)

        # Wave clear
        if s.wave_active and not s.enemies:
            s.wave_active = False
            s.last_wave_clear = s.time
            s.wave += 1
            new_segment = (s.wave - 1) // 5
            if config.ENABLE_OBSTACLES and new_segment != getattr(s, "layout_segment", 0):
                self._regen_layout(new_segment)
            self.player.current_weapon = get_weapon_for_wave(s.wave)  # Update weapon for new wave
            maybe_spawn_powerup(s, Vec2(0.0, 0.0))

        # Shake decay
        if s.shake > 0:
            s.shake = max(0.0, s.shake - dt * 20)
        
        # Update particles
        self.particle_system.update(dt)
        if self.room:
            self.room.update(dt)

        # Laser beams
        for lb in list(getattr(s, "lasers", [])):
            lb.t += dt
            if lb.owner == "enemy" and lb.t >= lb.warn and not lb.hit_done:
                if point_segment_distance(self.player.pos, lb.start, lb.end) <= lb.thickness * 0.55:
                    lb.hit_done = True
                    self._damage_player(lb.damage)
                    s.shake = max(s.shake, 10.0)
                    self.particle_system.add_laser_beam(lb.start, lb.end, color=lb.color)
            if lb.t >= lb.warn + lb.ttl:
                s.lasers.remove(lb)
                self.visuals.drop_laser(lb)

        if self.player.hp <= 0:
            self.game_state = "game_over"
            self.game_over_menu.set_wave(self.state.wave)
            self.mouse_down = False

    def on_draw(self):
        """Render the game."""
        self.clear()

        if self.game_state == "menu":
            self.main_menu.draw()
        elif self.game_state == "settings":
            self.settings_menu.draw()
        elif self.game_state in ["playing", "paused", "game_over"]:
            if not self.state:
                return

            # Compute shake offset once per frame.
            s = self.state
            shake = Vec2(0.0, 0.0)
            if s.shake > 0:
                shake = Vec2(random.uniform(-1, 1), random.uniform(-1, 1)) * s.shake

            # Ensure visuals exist and update their positions.
            if config.ENABLE_OBSTACLES:
                for ob in getattr(self.state, "obstacles", []):
                    self.visuals.ensure_obstacle(ob)
                    self.visuals.sync_obstacle(ob, shake)

            aim_dir = (iso_to_world(self.mouse_xy) - self.player.pos).normalized()
            self.visuals.sync_player(self.player, shake, t=s.time, aim_dir=aim_dir)

            for e in self.state.enemies:
                self.visuals.ensure_enemy(e)
                self.visuals.sync_enemy(e, shake)

            for p in self.state.projectiles:
                self.visuals.ensure_projectile(p)
                self.visuals.sync_projectile(p, shake)

            for pu in self.state.powerups:
                self.visuals.ensure_powerup(pu)
                self.visuals.sync_powerup(pu, shake)

            for tr in getattr(self.state, "traps", []):
                self.visuals.ensure_trap(tr)
                self.visuals.sync_trap(tr, shake)

            for lb in getattr(self.state, "lasers", []):
                self.visuals.ensure_laser(lb)
                self.visuals.sync_laser(lb, shake)

            for th in getattr(self.state, "thunders", []):
                self.visuals.ensure_thunder(th)
                self.visuals.sync_thunder(th, shake)

            self.batch.draw()
            
            # Render particles on top of batch
            self.particle_system.render(shake)

            laser_left = max(0.0, self.player.laser_until - self.state.time)
            laser_txt = f"   Laser: {laser_left:.0f}s" if laser_left > 0 else ""
            vortex_left = max(0.0, self.player.vortex_until - self.state.time)
            vortex_txt = f"   Vortex: {vortex_left:.0f}s" if vortex_left > 0 else ""
            boss = next((e for e in self.state.enemies if getattr(e, "behavior", "").startswith("boss_")), None)
            boss_txt = f"   BOSS: {boss.behavior[5:].replace('_',' ').title()} HP:{boss.hp}" if boss else ""
            self.hud.text = f"HP: {self.player.hp}   Shield: {self.player.shield}   Wave: {self.state.wave}   Enemies: {len(self.state.enemies)}   Weapon: {self.player.current_weapon.name.capitalize()}{laser_txt}{vortex_txt}{boss_txt}"
            self.hud.draw()
            
            if self.game_state == "paused":
                self.pause_menu.draw()
            elif self.game_state == "game_over":
                self.game_over_menu.draw()
            else:
                # Draw pause hint
                pause_hint = pyglet.text.Label(
                    "Press ESC to pause",
                    font_name="Arial",
                    font_size=10,
                    x=self.width - 10,
                    y=self.height - 14,
                    anchor_x="right",
                    anchor_y="top",
                    color=(150, 150, 150, 200)
                )
                pause_hint.draw()


def main():
    """Start the game."""
    try:
        _ = Game()
        pyglet.app.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print("Fatal error:", e)
        raise


if __name__ == "__main__":
    main()
