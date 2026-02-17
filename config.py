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
ULTRA_SPAWN_MIN_WAVE = 4
ULTRA_GUARANTEE_WAVE_GAP = 4
ULTRA_WAVE_SPAWN_BASE = 0.03
ULTRA_WAVE_SPAWN_PER_WAVE = 0.004
ULTRA_WAVE_SPAWN_MAX = 0.2
ULTRA_KILL_BASE_CHANCE = 0.015
ULTRA_KILL_PITY_THRESHOLD = 30

# Isometric projection
ISO_SCALE_X = 1.0
ISO_SCALE_Y = 0.5

# Colors
BG_TOP = (10, 15, 30)
BG_BOTTOM = (5, 8, 20)
FLOOR_MAIN = (52, 50, 48)       # Warm concrete
FLOOR_EDGE = (90, 85, 80)       # Pavement edge
FLOOR_GRID = (95, 110, 130)     # Subtle steel-blue grid
HUD_TEXT = (240, 240, 240)

# Powerup Colors
POWERUP_COLORS = {
    "heal": (120, 255, 120),
    "damage": (255, 120, 120),
    "speed": (120, 180, 255),
    "firerate": (255, 255, 120),
    "shield": (100, 220, 255),
    "laser": (255, 120, 255),
    "vortex": (200, 160, 255),
    "weapon": (230, 230, 255),
    "ultra": (255, 240, 180),
}

# Enemy Colors
ENEMY_COLORS = {
    "bomber": (255, 160, 50),       # Vibrant Yellow-Orange
    "chaser": (255, 80, 80),        # Bright Red
    "ranged": (80, 150, 255),       # Bright Blue
    "charger": (255, 180, 80),      # Bright Orange
    "swarm": (220, 100, 220),       # Bright Purple
    "tank": (100, 220, 100),        # Bright Green
    "spitter": (255, 220, 80),      # Bright Yellow
    "flyer": (150, 180, 255),       # Light Blue
    "engineer": (80, 240, 180),     # Bright Teal
    "boss_thunder": (180, 210, 255),
    "boss_laser": (255, 140, 255),
    "boss_trapmaster": (255, 180, 100),
    "boss_swarmqueen": (230, 140, 255),
    "boss_brute": (255, 100, 100),
    "boss_abyss_gaze": (185, 220, 255),
    "boss_womb_core": (255, 105, 135),
}
