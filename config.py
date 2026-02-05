# Game Configuration Constants

# Screen dimensions
SCREEN_W = 980
SCREEN_H = 620
FPS = 60

# Room settings
ROOM_RADIUS = 400.0  # Larger play area for more movement

# Player stats
PLAYER_SPEED = 175.0
PLAYER_HP = 100
PLAYER_DAMAGE = 10
PLAYER_FIRE_RATE = 0.28
PROJECTILE_SPEED = 360.0

# Wave settings
WAVE_COOLDOWN = 2.0
MAX_ENEMIES = 12  # Maximum concurrent enemies in a wave

# Isometric projection
ISO_SCALE_X = 1.0
ISO_SCALE_Y = 0.5

# Colors
BG_TOP = (14, 18, 26)
BG_BOTTOM = (9, 10, 16)
FLOOR_MAIN = (45, 52, 70)
FLOOR_EDGE = (95, 104, 128)
FLOOR_GRID = (64, 72, 96)
HUD_TEXT = (235, 235, 235)

# Powerup Colors
POWERUP_COLORS = {
    "heal": (100, 255, 150),
    "damage": (255, 100, 100),
    "speed": (100, 200, 255),
    "firerate": (255, 220, 100),
}

# Enemy Colors
ENEMY_COLORS = {
    "chaser": (210, 80, 80),        # Red
    "ranged": (90, 170, 240),       # Blue
    "charger": (235, 150, 70),      # Orange
    "swarm": (200, 100, 200),       # Purple
    "tank": (100, 200, 100),        # Green
    "spitter": (240, 200, 80),      # Yellow
    "flyer": (150, 150, 240),       # Light blue
}
