# Game Configuration Constants

# Screen dimensions
SCREEN_W = 980
SCREEN_H = 620
FPS = 60

# Feature flags
ENABLE_OBSTACLES = False

# Room settings
ROOM_RADIUS = 400.0  # Larger play area for more movement
ARENA_MARGIN = 0.97  # Portion of the window used to fit the arena (higher = bigger arena)

# Player stats
PLAYER_SPEED = 175.0
PLAYER_HP = 100
PLAYER_DAMAGE = 10
PLAYER_FIRE_RATE = 0.28
PROJECTILE_SPEED = 360.0

# Wave settings
WAVE_COOLDOWN = 2.0
MAX_ENEMIES = 12  # Maximum concurrent enemies in a wave
MAX_ACTIVE_CONSTRUCTIONS = 14  # Cap for enemy-built traps/hazards to avoid map clutter

# Ultra ability (special powerup -> right click)
ULTRA_MAX_CHARGES = 2
ULTRA_COOLDOWN = 10.0
ULTRA_DAMAGE_BASE = 55
ULTRA_DAMAGE_MULT = 2.7
ULTRA_BEAM_THICKNESS = 16.0
ULTRA_BEAM_TTL = 0.12
ULTRA_BEAM_COLOR = (255, 230, 170)

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
    "shield": (120, 220, 255),
    "laser": (255, 120, 255),
    "vortex": (180, 140, 255),
    "weapon": (220, 230, 255),
    "ultra": (255, 230, 170),
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
    "engineer": (80, 220, 170),     # Teal
    "boss_thunder": (170, 200, 255),
    "boss_laser": (255, 120, 255),
    "boss_trapmaster": (255, 170, 80),
    "boss_swarmqueen": (220, 120, 255),
    "boss_brute": (255, 80, 80),
}
