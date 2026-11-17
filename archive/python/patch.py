import re
import os

with open("vercel_site/py/browser_game.py", "r", encoding="utf-8") as f:
    content = f.read()

particles_import = "from powerup import apply_powerup\nfrom particles import ParticleSystem\n"
content = content.replace("from powerup import apply_powerup\n", particles_import)

init_insert = """
        self.score = ScoreTracker()
        self.particles = ParticleSystem()
"""
content = content.replace("\n        self.score = ScoreTracker()", init_insert)

update_insert = """
        if self.state_name == STATE_PLAYING and self.state and self.player:
            self.particles.update(dt)
            self._update_playing(dt)
"""
content = content.replace("\n        if self.state_name == STATE_PLAYING and self.state and self.player:\n            self._update_playing(dt)", update_insert)

render_insert = """
            self._draw_player(shake)
            self.particles.render(self.ctx, shake, to_iso)
"""
content = content.replace("\n            self._draw_player(shake)", render_insert)

new_draw_enemy = '''
    def _draw_enemy(self, enemy_obj, shake: Vec2) -> None:
        sx, sy = to_iso(enemy_obj.pos, shake)
        name = getattr(enemy_obj, "_behavior_name", enemy_behavior_name(enemy_obj))
        color = ENEMY_COLORS.get(name, (220, 220, 220))
        radius = getattr(enemy_obj, "_radius", self._enemy_radius(enemy_obj))
        boss = name.startswith("boss_")
        rx = max(10.0, radius * 0.95)
        ry = max(8.0, radius * 0.58)
        ctx = self.ctx
        bob = math.sin(enemy_obj.t * 6.0) * 1.5

        if boss:
            sy -= 26
        
        ctx.fillStyle = "rgba(10, 12, 18, 0.5)"
        ctx.beginPath()
        ctx.ellipse(sx, sy + 10 + (26 if boss else 0), rx * 0.95, ry * 0.74, 0, 0, TAU)
        ctx.fill()

        self._draw_glow_circle(sx, sy - 16 + bob, rx * 0.8, color, 0.18 if not boss else 0.28)
        
        ctx.fillStyle = f"rgb({color[0]}, {color[1]}, {color[2]})"
        ctx.beginPath()
        ctx.ellipse(sx, sy - 14 + bob, rx, ry, 0, 0, TAU)
        ctx.fill()
        
        ctx.lineWidth = 1.6
        if name == "bomber":
            exploding = bool(getattr(enemy_obj, "ai", {}).get("bomber_exploding", False))
            pulse = 0.5 + 0.5 * math.sin(enemy_obj.t * 30) if exploding else 0
            fuse_speed = 18.0 if exploding else 4.0
            
            ctx.fillStyle = "rgba(255, 100, 50, 0.9)" if exploding else "rgba(255, 160, 50, 0.8)"
            ctx.beginPath()
            ctx.arc(sx, sy + bob - 14, 8 + 4 * pulse, 0, TAU)
            ctx.fill()
            
            fr = 16
            fx = sx + math.cos(enemy_obj.t * fuse_speed) * fr
            fy = sy + bob - 14 + math.sin(enemy_obj.t * fuse_speed) * fr
            self._draw_glow_circle(fx, fy, 6, (255, 200, 50), 0.6 + 0.4 * math.sin(enemy_obj.t * 12.0))
            
        elif name == "engineer":
            gear_r = 17 + 1.5 * math.sin(enemy_obj.t * 5.0)
            ctx.strokeStyle = f"rgba(180, 200, 220, {0.2 + 0.2 * math.sin(enemy_obj.t * 3.0)})"
            ctx.beginPath()
            ctx.arc(sx - 12, sy + 2 + bob - 14, gear_r, 0, TAU)
            ctx.stroke()
            
            ctx.fillStyle = "rgba(100, 150, 180, 0.8)"
            ctx.fillRect(sx - 16, sy + bob - 16, 8, 12)
            ctx.fillStyle = "rgba(200, 200, 200, 0.9)"
            ctx.fillRect(sx + 10, sy + bob - 12, 6, 2)
            
        elif name == "egg_sac":
            pulse = 0.8 + 0.2 * math.sin(enemy_obj.t * 8.0)
            if getattr(enemy_obj, "ai", {}).get("hatch_timer", 0) < 1.0:
                pulse = 0.8 + 0.3 * math.sin(enemy_obj.t * 18.0)
            
            ctx.fillStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, 0.8)"
            ctx.beginPath()
            ctx.arc(sx, sy + bob - 14, 15 * pulse, 0, TAU)
            ctx.fill()
            
            ctx.fillStyle = "rgba(255, 50, 50, 0.9)"
            ctx.beginPath()
            ctx.arc(sx, sy + bob - 14, 6 * pulse + 2 * math.sin(enemy_obj.t * 12.0), 0, TAU)
            ctx.fill()

        elif name == "tank":
            ctx.fillStyle = "rgba(80, 120, 80, 0.9)"
            ctx.fillRect(sx - 8, sy + bob - 18, 16, 8)
            
            shield_r = 22 + 1.0 * math.sin(enemy_obj.t * 2.0)
            ctx.strokeStyle = f"rgba(100, 220, 100, {0.2 + 0.15 * math.sin(enemy_obj.t * 1.5)})"
            ctx.lineWidth = 2.5
            ctx.beginPath()
            ctx.ellipse(sx, sy + bob * 0.4 - 14, shield_r, shield_r * 0.6, 0, 0, TAU)
            ctx.stroke()
            
        elif name == "ranged":
            sr = 20
            sa = enemy_obj.t * 1.2
            ctx.strokeStyle = f"rgba(255, 50, 50, {0.25 + 0.15 * math.sin(enemy_obj.t * 3.0)})"
            ctx.lineWidth = 1.5
            cx = sx + 18
            cy = sy + 2 + bob - 14
            ctx.beginPath()
            ctx.moveTo(cx - math.cos(sa) * sr, cy)
            ctx.lineTo(cx + math.cos(sa) * sr, cy)
            ctx.moveTo(cx, cy - math.sin(sa) * sr)
            ctx.lineTo(cx, cy + math.sin(sa) * sr)
            ctx.stroke()
            
            ctx.fillStyle = "rgba(100, 100, 100, 0.9)"
            ctx.fillRect(sx + 6, sy + bob - 16, 12, 4)

        elif name == "charger":
            ctx.fillStyle = "rgba(200, 200, 200, 0.9)"
            ctx.beginPath()
            ctx.moveTo(sx + 2, sy + 16 + bob - 14)
            ctx.lineTo(sx + 12, sy + 10 + bob - 14)
            ctx.lineTo(sx + 6, sy + 4 + bob - 14)
            ctx.fill()
            ctx.beginPath()
            ctx.moveTo(sx - 2, sy + 16 + bob - 14)
            ctx.lineTo(sx - 12, sy + 10 + bob - 14)
            ctx.lineTo(sx - 6, sy + 4 + bob - 14)
            ctx.fill()
            
            if getattr(enemy_obj, "ai", {}).get("charger_dashing", False):
                ctx.strokeStyle = "rgba(255, 200, 100, 0.5)"
                ctx.lineWidth = 2
                ctx.beginPath()
                ctx.moveTo(sx - 12, sy + 6 + bob - 14)
                ctx.lineTo(sx - 32, sy + 10 + bob - 14)
                ctx.stroke()
                ctx.beginPath()
                ctx.moveTo(sx - 12, sy - 2 + bob - 14)
                ctx.lineTo(sx - 32, sy + 2 + bob - 14)
                ctx.stroke()

        elif name == "flyer":
            flap = 6 + 4 * math.sin(enemy_obj.t * 10.0)
            ctx.fillStyle = f"rgba({color[0]}, {color[1]}, {color[2]}, 0.8)"
            ctx.beginPath()
            ctx.moveTo(sx, sy + bob + 6 - 14)
            ctx.lineTo(sx + 22, sy + bob + flap - 14)
            ctx.lineTo(sx + 10, sy + bob - 2 - 14)
            ctx.fill()
            ctx.beginPath()
            ctx.moveTo(sx, sy + bob + 6 - 14)
            ctx.lineTo(sx - 22, sy + bob + flap - 14)
            ctx.lineTo(sx - 10, sy + bob - 2 - 14)
            ctx.fill()
            
            ctx.strokeStyle = f"rgba(100, 200, 255, {0.2 + 0.15 * math.sin(enemy_obj.t * 8.0)})"
            ctx.lineWidth = 2
            ctx.beginPath()
            ctx.moveTo(sx - 4, sy + bob - 4 - 14)
            ctx.lineTo(sx - 18, sy + bob - 16 - 14)
            ctx.stroke()
            
        elif name == "spitter":
            ctx.fillStyle = "rgba(100, 200, 100, 0.8)"
            ctx.beginPath()
            ctx.arc(sx - 9, sy + 2 + bob - 14, 5, 0, TAU)
            ctx.fill()
            ctx.beginPath()
            ctx.arc(sx + 8, sy + 4 + bob - 14, 5, 0, TAU)
            ctx.fill()
            
            acid_r = 14 + 3 * math.sin(enemy_obj.t * 4.0)
            self._draw_glow_circle(sx, sy + bob - 14, acid_r, (100, 255, 100), 0.1 + 0.1 * math.sin(enemy_obj.t * 5.0))

        elif name == "swarm":
            r = 8
            dot_color = (255, 100, 255)
            for offset in (0, 2.1, 4.2):
                dx = sx + math.cos(enemy_obj.t * 6.0 + offset) * r
                dy = sy + bob - 14 + math.sin(enemy_obj.t * 6.0 + offset) * r
                ctx.fillStyle = f"rgb({dot_color[0]}, {dot_color[1]}, {dot_color[2]})"
                ctx.beginPath()
                ctx.arc(dx, dy, 3, 0, TAU)
                ctx.fill()
            
            jitter = math.sin(enemy_obj.t * 20.0) * 3.0
            ctx.strokeStyle = f"rgba(255, 150, 255, {0.3 + 0.2 * math.sin(enemy_obj.t * 14.0)})"
            ctx.lineWidth = 1.5
            ctx.beginPath()
            ctx.moveTo(sx - 3, sy + bob + 8 - 14)
            ctx.lineTo(sx - 5 + jitter, sy + bob + 15 - 14)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(sx + 3, sy + bob + 8 - 14)
            ctx.lineTo(sx + 5 - jitter, sy + bob + 15 - 14)
            ctx.stroke()

        elif name == "chaser":
            aura_r = 16 + 4 * math.sin(enemy_obj.t * 3.5)
            ctx.strokeStyle = f"rgba(255, 50, 50, {0.15 + 0.15 * math.sin(enemy_obj.t * 2.5)})"
            ctx.lineWidth = 2
            ctx.beginPath()
            ctx.arc(sx, sy + bob - 14, aura_r, 0, TAU)
            ctx.stroke()
            
            t_rot = enemy_obj.t * 1.8
            ctx.fillStyle = "rgba(200, 50, 50, 0.9)"
            for i in range(3):
                a = t_rot + i * (math.tau / 3)
                tip_x = sx + math.cos(a) * 18
                tip_y = sy + bob - 14 + math.sin(a) * 18
                b1 = a + 0.35
                b2 = a - 0.35
                ctx.beginPath()
                ctx.moveTo(tip_x, tip_y)
                ctx.lineTo(sx + math.cos(b1) * 10, sy + bob - 14 + math.sin(b1) * 10)
                ctx.lineTo(sx + math.cos(b2) * 10, sy + bob - 14 + math.sin(b2) * 10)
                ctx.fill()
        
        elif boss:
            ctx.strokeStyle = f"rgba(255, 200, 50, {0.5 + 0.3 * math.sin(enemy_obj.t * 4.0)})"
            ctx.lineWidth = 3
            crown_r = 24 + 2.0 * (0.5 + 0.5 * math.sin(enemy_obj.t * 4.0))
            ctx.beginPath()
            ctx.ellipse(sx, sy + bob - 14, crown_r, crown_r * 0.5, 0, 0, TAU)
            ctx.stroke()

        ctx.strokeStyle = "rgba(255,255,255,0.16)"
        ctx.lineWidth = 1.6
        ctx.beginPath()
        ctx.ellipse(sx, sy - 14 + bob, rx, ry, 0, 0, TAU)
        ctx.stroke()

        if boss:
            max_hp = max(1, int(enemy_obj.ai.get("max_hp", enemy_obj.hp)))
            self._draw_entity_bar(sx - 28, sy - 44 + 26, 56, max(0.0, min(1.0, enemy_obj.hp / max_hp)), color)
'''

content = re.sub(
    r'    def _draw_enemy\(self, enemy_obj, shake: Vec2\) -> None:.*?def _draw_player',
    new_draw_enemy + '\n\n    def _draw_player',
    content,
    flags=re.DOTALL
)

# Also need to add particle hits into browser_game logic:
# 1. _damage_player -> self.particles.add_hit_particles
# 2. _kill_enemy -> self.particles.add_death_explosion
# 3. _use_ultra -> self.particles.add_laser_beam etc.
# 4. auto_shoot -> self.particles.add_muzzle_flash
# Let's insert a few calls

content = content.replace("self.score.on_player_hit()", "self.score.on_player_hit()\n            self.particles.add_hit_particles(self.player.pos, (255, 100, 100))")
content = content.replace("spawn_loot_on_enemy_death(self.state, behavior, enemy_obj.pos)", "spawn_loot_on_enemy_death(self.state, behavior, enemy_obj.pos)\n        self.particles.add_death_explosion(enemy_obj.pos, ENEMY_COLORS.get(behavior, (220, 220, 220)), behavior)")
content = content.replace("apply_powerup(self.player, powerup, s.time)", "apply_powerup(self.player, powerup, s.time)\n                self.particles.add_powerup_collection(powerup.pos, POWERUP_COLORS.get(getattr(powerup, 'kind', ''), (220, 220, 220)))")
content = content.replace("s.projectiles.extend(\n                    spawn_projectiles(", "self.particles.add_muzzle_flash(muzzle, aim)\n                s.projectiles.extend(\n                    spawn_projectiles(")
content = content.replace("self._dash_cd_mult)", "self._dash_cd_mult)\n        if self.player.is_dashing:\n            self.particles.add_dash_effect(self.player.pos, self.player.dash_direction)")

with open("vercel_site/py/browser_game.py", "w", encoding="utf-8") as f:
    f.write(content)
