# Game Configuration Constants

# Screen dimensions
SCREEN_W = 980
SCREEN_H = 620
FPS = 60

# Feature flags
ENABLE_OBSTACLES = False
ENABLE_ADVANCED_FX = True
ADVANCED_FX_STRENGTH = 0.55

# Room settings
ROOM_RADIUS = 400.0
ARENA_MARGIN = 0.97

# Map Types
MAP_CIRCLE = "circle"
MAP_DONUT = "donut"
MAP_CROSS = "cross"
MAP_DIAMOND = "diamond"

# Player stats
PLAYER_SPEED = 175.0
PLAYER_HP = 100
PLAYER_DAMAGE = 10
PLAYER_FIRE_RATE = 0.28

# Projectile tuning
# Global multiplier for projectile movement (player + enemy).
PROJECTILE_TRAVEL_SCALE = 0.72

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

# Colors (Neon/Cyberpunk Palette)
PALETTE = {
    "background_top": (10, 10, 20),      # Deep void blue
    "background_bottom": (5, 5, 12),    # Nearly black
    "floor_main": (15, 18, 30),         # Dark sleek floor
    "floor_edge": (40, 50, 80),         # Tech blue rim
    "floor_grid": (40, 100, 200),       # Glowing grid lines
    "player": (0, 255, 200),            # Cyan Neon
    "player_projectile": (200, 255, 100), # Lime Yellow
    "enemy_projectile": (255, 50, 100),   # Hot Pink
    "hud_text": (255, 255, 255),
    "vibrant_blue": (0, 190, 255),      # Electric Blue
    "vibrant_orange": (255, 140, 20),   # Neon Orange
    "vibrant_pink": (255, 20, 180),     # Cyber Pink
    "vibrant_green": (50, 255, 80),     # Acid Green
    "vibrant_purple": (180, 50, 255),   # Deep Neon Purple
    "white_glow": (220, 235, 255),      # Bright White-Blue
}

BG_TOP = PALETTE["background_top"]
BG_BOTTOM = PALETTE["background_bottom"]
FLOOR_MAIN = PALETTE["floor_main"]
FLOOR_EDGE = PALETTE["floor_edge"]
FLOOR_GRID = PALETTE["floor_grid"]
HUD_TEXT = PALETTE["hud_text"]

# Powerup Colors
POWERUP_COLORS = {
    "heal": (50, 255, 150),
    "damage": (255, 60, 60),
    "speed": PALETTE["vibrant_blue"],
    "firerate": (255, 220, 50),
    "shield": (100, 200, 255),
    "laser": PALETTE["vibrant_pink"],
    "vortex": PALETTE["vibrant_purple"],
    "weapon": (255, 255, 220),
    "ultra": (255, 200, 100),
}

# Enemy Colors
ENEMY_COLORS = {
    "bomber": PALETTE["vibrant_orange"],
    "chaser": (255, 40, 40),        # Red
    "ranged": PALETTE["vibrant_blue"],
    "charger": (255, 100, 0),       # Orange-Red
    "swarm": PALETTE["vibrant_purple"],
    "tank": PALETTE["vibrant_green"],
    "spitter": (255, 220, 0),       # Yellow
    "flyer": (120, 200, 255),       # Sky Blue
    "engineer": (0, 255, 180),      # Teal
    "boss_thunder": (150, 200, 255),
    "boss_laser": PALETTE["vibrant_pink"],
    "boss_trapmaster": PALETTE["vibrant_orange"],
    "boss_swarmqueen": (200, 80, 255),
    "boss_brute": (255, 50, 50),
    "boss_abyss_gaze": (100, 150, 255),
    "boss_womb_core": (255, 80, 120),
}
