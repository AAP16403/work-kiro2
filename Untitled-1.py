# Pyglet isometric room survival prototype
# Controls: WASD/Arrows move, hold Left Mouse to shoot.
# Install: py -m pip install pyglet

import random

import pyglet

from config import SCREEN_W, SCREEN_H, FPS, ROOM_RADIUS, PLAYER_SPEED, PROJECTILE_SPEED, WAVE_COOLDOWN, HUD_TEXT, ENEMY_COLORS
from player import Player
from map import Room
from level import GameState, spawn_wave, maybe_spawn_powerup
from enemy import update_enemy
from powerup import apply_powerup
from projectile import Projectile
from utils import Vec2, clamp_to_room, iso_to_world, dist
from visuals import Visuals, GroupCache
from weapons import get_weapon_for_wave, spawn_weapon_projectiles, get_weapon_color
from particles import ParticleSystem


# ============================
# Main Game Class
# ============================
class Game(pyglet.window.Window):
    """Main game window and logic."""

    def __init__(self):
        super().__init__(width=SCREEN_W, height=SCREEN_H, caption="Isometric Room Survival (pyglet)", vsync=True)

        self.batch = pyglet.graphics.Batch()
        self.groups = GroupCache()
        self.room = Room(self.batch)

        self.state = GameState()
        self.player = Player(pos=Vec2(0.0, 0.0))
        self.player.current_weapon = get_weapon_for_wave(1)  # Start with basic weapon

        self.visuals = Visuals(self.batch, self.groups)
        self.visuals.make_player()
        
        self.particle_system = ParticleSystem(self.batch)

        self.keys = pyglet.window.key.KeyStateHandler()
        self.push_handlers(self.keys)

        self.mouse_xy = (SCREEN_W / 2, SCREEN_H / 2)
        self.mouse_down = False

        self.hud = pyglet.text.Label(
            "",
            font_name="Consolas",
            font_size=14,
            x=12,
            y=SCREEN_H - 14,
            anchor_x="left",
            anchor_y="top",
            color=(HUD_TEXT[0], HUD_TEXT[1], HUD_TEXT[2], 255),
        )

        pyglet.clock.schedule_interval(self.update, 1.0 / FPS)

    def on_mouse_motion(self, x, y, dx, dy):
        self.mouse_xy = (x, y)

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        self.mouse_xy = (x, y)

    def on_mouse_press(self, x, y, button, modifiers):
        if button == pyglet.window.mouse.LEFT:
            self.mouse_down = True

    def on_mouse_release(self, x, y, button, modifiers):
        if button == pyglet.window.mouse.LEFT:
            self.mouse_down = False

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
        s = self.state
        s.time += dt

        # Waves
        if not s.wave_active and (s.time - s.last_wave_clear) >= WAVE_COOLDOWN:
            spawn_wave(s, Vec2(0.0, 0.0))

        # Player movement
        idir = self._input_dir()
        if idir.length() > 0:
            self.player.pos = self.player.pos + idir.normalized() * self.player.speed * dt
        self.player.pos = clamp_to_room(self.player.pos, ROOM_RADIUS * 0.9)

        # Player shooting
        if self.mouse_down and (s.time - self.player.last_shot) >= self.player.fire_rate:
            world_mouse = iso_to_world(self.mouse_xy)
            aim = (world_mouse - self.player.pos).normalized()
            muzzle = self.player.pos + aim * 14.0
            
            # Use current weapon to spawn projectiles
            weapon = self.player.current_weapon
            projectiles = spawn_weapon_projectiles(muzzle, aim, weapon, s.time, self.player.damage)
            s.projectiles.extend(projectiles)
            
            # Muzzle flash particle effect
            weapon_color = get_weapon_color(weapon.projectile_type)
            self.particle_system.add_muzzle_flash(muzzle, aim, weapon_color)
            
            self.player.last_shot = s.time

        # Enemies
        for e in list(s.enemies):
            update_enemy(e, self.player.pos, s, dt)
            if dist(e.pos, self.player.pos) < 12:
                self.player.hp -= 10
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
                                    self.player.hp -= 15
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
                    self.player.hp -= p.damage
                    s.shake = max(s.shake, 6.0)
                    if p in s.projectiles:
                        s.projectiles.remove(p)
                        self.visuals.drop_projectile(p)

        # Powerups
        for pu in list(s.powerups):
            if dist(pu.pos, self.player.pos) < 16:
                # Particle effect for powerup collection
                from config import POWERUP_COLORS
                color = POWERUP_COLORS.get(pu.kind, (200, 200, 200))
                self.particle_system.add_powerup_collection(pu.pos, color)
                
                apply_powerup(self.player, pu)
                s.powerups.remove(pu)
                self.visuals.drop_powerup(pu)

        # Wave clear
        if s.wave_active and not s.enemies:
            s.wave_active = False
            s.last_wave_clear = s.time
            s.wave += 1
            self.player.current_weapon = get_weapon_for_wave(s.wave)  # Update weapon for new wave
            maybe_spawn_powerup(s, Vec2(0.0, 0.0))

        # Shake decay
        if s.shake > 0:
            s.shake = max(0.0, s.shake - dt * 20)
        
        # Update particles
        self.particle_system.update(dt)

        if self.player.hp <= 0:
            pyglet.app.exit()

    def on_draw(self):
        """Render the game."""
        self.clear()

        # Compute shake offset once per frame.
        s = self.state
        shake = Vec2(0.0, 0.0)
        if s.shake > 0:
            shake = Vec2(random.uniform(-1, 1), random.uniform(-1, 1)) * s.shake

        # Ensure visuals exist and update their positions.
        self.visuals.sync_player(self.player, shake)

        for e in self.state.enemies:
            self.visuals.ensure_enemy(e)
            self.visuals.sync_enemy(e, shake)

        for p in self.state.projectiles:
            self.visuals.ensure_projectile(p)
            self.visuals.sync_projectile(p, shake)

        for pu in self.state.powerups:
            self.visuals.ensure_powerup(pu)
            self.visuals.sync_powerup(pu, shake)

        self.batch.draw()
        
        # Render particles on top of batch
        self.particle_system.render(shake)

        self.hud.text = f"HP: {self.player.hp}   Wave: {self.state.wave}   Enemies: {len(self.state.enemies)}   Weapon: {self.player.current_weapon.name.capitalize()}"
        self.hud.draw()


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
