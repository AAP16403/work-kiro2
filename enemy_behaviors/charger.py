"""Charger behavior for enemies."""
from enemy_behaviors.base import Behavior
from utils import Vec2

class Charger(Behavior):
    """
    A charger behavior that telegraphs its attack.
    It uses a state machine: REPOSITIONING -> WINDUP -> CHARGING -> COOLDOWN.
    """

    def __init__(self, charge_speed_mult=3.0, windup_time=0.5, cooldown_time=1.0, reposition_dist=200.0):
        self.charge_speed_mult = charge_speed_mult
        self.windup_time = windup_time
        self.cooldown_time = cooldown_time
        self.reposition_dist = reposition_dist

    def update(self, enemy, player_pos, state, dt, player_vel):
        """Update the enemy's state based on its behavior."""

        # -- Initialize AI state --
        if "state" not in enemy.ai or "state_timer" not in enemy.ai:
            enemy.ai["state"] = "REPOSITIONING"
            enemy.ai["state_timer"] = 0

        # -- Common calculations --
        dvec = player_pos - enemy.pos
        dist_to_player = dvec.length()
        dir_to_player = dvec.normalized() if dist_to_player > 1e-6 else Vec2(1.0, 0.0)

        # -- State Machine --
        current_state = enemy.ai.get("state")
        enemy.ai["state_timer"] -= dt

        if current_state == "REPOSITIONING":
            # --- Move to a good charging distance ---
            # If we are at a good distance, start winding up
            if dist_to_player < self.reposition_dist:
                enemy.ai["state"] = "WINDUP"
                enemy.ai["state_timer"] = self.windup_time
                enemy.vel = Vec2(0, 0) # Stop to telegraph
                return

            # Move towards the player
            sep = self._separation(enemy, state.enemies, radius=60.0, weight=1.5)
            move_dir = (dir_to_player + sep * 0.5).normalized()
            enemy.vel = move_dir * enemy.speed
            enemy.pos += enemy.vel * dt

        elif current_state == "WINDUP":
            # --- Telegraph the charge ---
            enemy.vel = Vec2(0, 0) # Stay still
            if enemy.ai["state_timer"] <= 0:
                enemy.ai["state"] = "CHARGING"
                # Lock on to a predicted position
                prediction_time = dist_to_player / (enemy.speed * self.charge_speed_mult) * 0.5 # Simple prediction
                enemy.ai["charge_target"] = player_pos + player_vel * prediction_time
                enemy.ai["charge_dir"] = (enemy.ai["charge_target"] - enemy.pos).normalized()

        elif current_state == "CHARGING":
            # --- Dash in a straight line ---
            # Use the locked-on direction
            charge_dir = enemy.ai["charge_dir"]
            enemy.vel = charge_dir * enemy.speed * self.charge_speed_mult
            enemy.pos += enemy.vel * dt

            # Stop charging if we've gone far enough or are close to the target
            # This prevents infinite charging across the map
            dist_to_target = (enemy.ai["charge_target"] - enemy.pos).length()
            if dist_to_target < 30 or (charge_dir.dot( (enemy.ai["charge_target"] - enemy.pos).normalized() ) < 0): # Overshot
                enemy.ai["state"] = "COOLDOWN"
                enemy.ai["state_timer"] = self.cooldown_time

        elif current_state == "COOLDOWN":
            # --- Brief pause after charging ---
            # Slow down significantly
            enemy.vel *= 0.9 * (1.0 - dt)
            enemy.pos += enemy.vel * dt
            if enemy.ai["state_timer"] <= 0:
                enemy.ai["state"] = "REPOSITIONING"


    def _separation(self, enemy, others, radius: float = 50.0, weight: float = 1.5) -> Vec2:
        """Repel from nearby enemies to reduce stacking."""
        steer = Vec2(0.0, 0.0)
        count = 0
        for o in others:
            if o is enemy:
                continue
            dvec = enemy.pos - o.pos
            d = dvec.length()
            if d > 0 and d < radius:
                # Force is inversely proportional to distance
                steer += (dvec.normalized() / d)
                count += 1
        if count > 0:
            steer /= count
        return steer
