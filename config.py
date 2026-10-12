 # Game Configuration Constants

# Screen dimensions
SCREEN_W = 980
SCREEN_H = 620
FPS = 60

# Feature flags
ENABLE_OBSTACLES = False
ENABLE_ADVANCED_FX = True
ADVANCED_FX_STRENGTH = 0.55
REDUCE_MOTION = False  # True stops ambient UI motion: title shimmer, bobbing, starfield and orb drift
USE_PLAYER_ART = True  # Pod-robot player character (player_art.py). False draws the legacy ship.

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
SHIELD_MAX = 120  # Shield cap shared by pickups, the HUD shield bar and its label
PLAYER_DAMAGE = 10
PLAYER_FIRE_RATE = 0.28
FIRE_RATE_MIN = 0.08
FIRE_RATE_RATIO_MIN = 0.65
FIRE_RATE_RATIO_MAX = 1.65
FIRE_RATE_CURVE = 0.85

# Gameplay tuning
WAVE_COOLDOWN = 2.0
MAX_ACTIVE_CONSTRUCTIONS = 14  # Cap for enemy-built traps/hazards to avoid map clutter
WEAPON_WAVE_UPGRADE_CHANCE = 0.5  # Chance per wave clear to roll a weapon; it is equipped only if it outranks the current one

# Game Over: the staged reveal runs this long, and input (click or key) unlocks when it ends.
GAME_OVER_REVEAL_S = 1.0

# Ultra ability (special powerup -> right click)
ULTRA_MAX_CHARGES = 2  # Starting charge capacity; permanent Ultra rewards raise it per run
ULTRA_MAX_CHARGES_HARD_CAP = 4  # Upper bound for run-scaled Ultra charge capacity
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
ISO_SCALE_X = 0.7
ISO_SCALE_Y = 0.35

# Colors
BG_TOP = (10, 15, 30)
BG_BOTTOM = (5, 8, 20)
FLOOR_MAIN = (30, 35, 42)       # Cool slate-grey
FLOOR_EDGE = (50, 60, 75)       # Blue-grey edge
FLOOR_GRID = (60, 80, 100)      # Muted steel-blue grid
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
    "boost": (255, 145, 45),
    "drone": (90, 255, 225),
}

# Boost / Overdrive mechanic (LSHIFT key)
BOOST_SPEED_MULT = 1.65
BOOST_MAX_ENERGY = 100.0
BOOST_DRAIN_RATE = 28.0
BOOST_RECHARGE_RATE = 22.0
BOOST_DAMAGE_REDUCTION = 0.35
BOOST_RAM_DAMAGE = 28
BOOST_COLOR = (255, 145, 45)

# Critical hits
CRIT_CHANCE_BASE = 0.10
CRIT_MULT_BASE = 2.0
CRIT_SPARK_COLOR = (255, 225, 75)

# Elite enemy settings
ELITE_SPAWN_BASE_WAVE = 3
ELITE_SPAWN_CHANCE = 0.14
ELITE_HP_MULT = 2.2
ELITE_REFLECT_COOLDOWN_S = 3.0   # Reflector affix: one player shot is sent back at the player per this many seconds
ELITE_REFLECT_SPEED = 260.0      # speed of a reflected shot, world units per second
ELITE_SCORE_MULT = 2.5
ELITE_AURA_COLOR = (255, 215, 60)

# Particle & Rendering budget (prevents frame drops under heavy load)
PARTICLE_SOFT_CAP = 450
PARTICLE_HARD_CAP = 650
DEPTH_BUCKET = 16

# Screen shake. Impulses stack, the total is capped, and every impulse is scaled by
# SHAKE_SCALE. The Screen Shake setting (Full / Reduced / Off) sets SHAKE_SCALE at runtime:
# Full = 1.0, Reduced = SHAKE_REDUCED_SCALE, Off = SHAKE_OFF_SCALE. Default is Full.
SHAKE_CAP = 14.0            # hard ceiling on the shake amplitude in px
SHAKE_DECAY = 20.0          # px of shake lost per second
SHAKE_SCALE = 1.0           # runtime multiplier, one of SHAKE_FULL_SCALE / SHAKE_REDUCED_SCALE / SHAKE_OFF_SCALE
SHAKE_FULL_SCALE = 1.0
SHAKE_REDUCED_SCALE = 0.5
SHAKE_OFF_SCALE = 0.0
SHAKE_LEVELS = ("full", "reduced", "off")  # Screen Shake setting, in the order the menu cycles through them
SHAKE_LEVEL_LABELS = {"full": "Full", "reduced": "Reduced", "off": "Off"}
SHAKE_HIT_IMPULSE = 2.0     # per player bullet hit at PLAYER_DAMAGE; beam and vortex ticks use it flat
SHAKE_HIT_DAMAGE_MAX_SCALE = 1.5  # bullet hits scale with damage / PLAYER_DAMAGE, clamped to [1.0, this]
SHAKE_CRIT_IMPULSE = 3.0    # per critical bullet hit, added on top of the damage-scaled hit impulse
SHAKE_HIT_FRAME_MAX = 3.0   # weapon hits in one frame sum to at most this, so multi-pellet fire cannot saturate
SHAKE_HIT_CEILING = 4.0     # sustained weapon fire holds at or below this; bigger impacts still stack past it
SHAKE_PLAYER_HIT_BASE = 2.0  # player damage shake: base + SHAKE_PLAYER_HIT_PER_HP * HP lost after shields
SHAKE_PLAYER_HIT_PER_HP = 0.25
SHAKE_PLAYER_HIT_MAX = 8.0

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

# Arena events (events.py). Set pieces on non-boss waves. Each one is telegraphed before it deals damage.
EVENT_MIN_WAVE = 4                  # no events before this wave
EVENT_WAVE_CHANCE = 1.0 / 3.0       # chance that an eligible (non-boss, wave >= EVENT_MIN_WAVE) wave gets one event
EVENT_METEOR_IMPACTS = 3            # impact zones per Meteor Shower
EVENT_METEOR_WARN = 1.5             # a zone is marked this long before it hits
EVENT_METEOR_STAGGER = 0.7          # gap between zone marks, so the impacts ripple across the arena
EVENT_METEOR_RADIUS = 38.0          # impact radius (same units as Trap.radius)
EVENT_METEOR_DAMAGE = 16
EVENT_METEOR_LIVE = 0.25            # a zone stays live for this long after it hits
EVENT_FLARE_WARN = 2.0              # the sector shows this long before the beam starts to move
EVENT_FLARE_SWEEP = 2.6             # seconds for the beam to cross the sector
EVENT_FLARE_SECTOR_DEG = 110.0      # width of the sector the beam sweeps
EVENT_FLARE_THICKNESS = 14.0
EVENT_FLARE_DAMAGE = 18
EVENT_FLARE_TICK = 0.5              # minimum gap between beam hits on the player
EVENT_NEBULA_WARN = 1.0             # the cloud shows this long before it becomes active
EVENT_NEBULA_TTL = 8.0              # seconds the cloud is active; enemies inside gain shield
EVENT_NEBULA_RADIUS = 110.0
EVENT_NEBULA_SHIELD = 24            # shield an enemy gains on entering the cloud; the leftover is removed on exit or at the end
# Multi-core job layer (parallel.py). Pool work is opt-in. tools/bench_steer.py measures it: the pool
# steers slower than the serial loop below ~20 live enemies and faster from ~24 up (1.6x to 2.9x at 32,
# over two runs).
# It stays off by default because the game's wave caps keep most fights below that, and because a
# spawned worker costs seconds of start-up on Windows (warmed on the first playing frame).
PARALLEL_STEER_ENABLED = False      # True: batch enemy steering may run in a process pool
PARALLEL_STEER_MIN_ENEMIES = 32     # live enemy count at which the batch path is used
# Named threshold for the multicore wiring tests and bench: the batch path runs at or above this live enemy count.
PARALLEL_MIN_ENEMIES = PARALLEL_STEER_MIN_ENEMIES
PARALLEL_STEER_WORKERS = 3          # process-pool size when enabled
PARALLEL_LOADER_WORKERS = 4         # threads for I/O-bound asset reads
