 # Game Configuration Constants

# Screen dimensions
SCREEN_W = 980
SCREEN_H = 620
FPS = 60

# Feature flags
ENABLE_OBSTACLES = False
ENABLE_ADVANCED_FX = True
ADVANCED_FX_STRENGTH = 0.55
# pyglet's debug_gl checks every GL call with a glGetError round trip. Off by default: frozen builds
# already run with it off, and the source run draws about 3x slower with it on. Set True to debug GL.
PYGLET_DEBUG_GL = False
USE_PLAYER_ART = True  # Pod-robot player character (player_art.py). False draws the legacy ship.
REDUCE_MOTION = False  # True stops ambient UI motion: title shimmer, bobbing, starfield and orb drift

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
WEAPON_PICKUP_SECONDS = 20.0  # A weapon pickup equips for this long, then the player reverts to the weapon held before it

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
    "ricochet": (60, 255, 200),
    "homing": (255, 80, 170),
    "time_slow": (110, 130, 255),
    "magnet": (170, 255, 70),
}

# Timed powerups (see powerup.py). Each one refreshes its expiry; picking it up again does not stack.
RICOCHET_DURATION = 8.0       # player bullets bounce once off the arena edge
HOMING_DURATION = 6.0         # player bullets steer toward the nearest live enemy
HOMING_RANGE = 260.0          # world units, measured from the bullet
HOMING_TURN_RATE = 2.4        # max steering in radians per second, so the curve stays readable
TIME_SLOW_DURATION = 4.0      # enemies and enemy projectiles run at TIME_SLOW_SCALE; the player does not
TIME_SLOW_SCALE = 0.5         # the one scalar for enemy time: enemy dt = frame dt * this
MAGNET_DURATION = 10.0        # pickups are pulled from a wider radius and faster
MAGNET_RADIUS_MULT = 3.0      # multiplies the pickup magnet radius
MAGNET_PULL_MULT = 1.5        # multiplies the pickup pull speed
RICOCHET_BOUNCES = 1          # bounces per bullet while Ricochet runs (shot_mods reads it; the Guide too)

# Chain Lightning (chain.py). A rare timed powerup; picking it up again refreshes the timer.
CHAIN_DURATION = 8.0          # seconds of chain per pickup
CHAIN_RANGE = 160.0           # world units: an arc reaches the nearest other live enemy within this of the kill
CHAIN_DAMAGE_PERCENT = 30     # arc damage = this percent of the player's damage, rounded half up
CHAIN_COLOR = (200, 245, 255) # pickup decoration and the arc glow; POWERUP_COLORS["chain"] should point here
CHAIN_ARC_COLOR = (235, 252, 255)  # bright core of each arc
CHAIN_ARC_CORE_WIDTH = 3.0    # core line thickness, screen px
CHAIN_ARC_GLOW_WIDTH = 9.0    # soft glow line under the core, screen px
CHAIN_ARC_GLOW_OPACITY = 150  # glow opacity at the start of the fade (0-255)
CHAIN_ARC_SECONDS = 0.22      # each arc fades out over this long
CHAIN_ARC_POOL = 12           # arcs drawn at once; a new arc reuses the oldest slot when all are busy
CHAIN_ARC_SEGMENTS = 5        # straight pieces per arc, so it reads as a jagged bolt
CHAIN_ARC_JITTER = 7.0        # max sideways offset of each interior point, world units
CHAIN_FLICKER_SECONDS = 0.05  # normal motion re-rolls the jagged shape this often; REDUCE_MOTION never re-rolls
CHAIN_PICKUP_DOT = 2.6        # pickup decoration: radius of each dot in the zigzag ring
CHAIN_PICKUP_RING_NEAR = 7.0  # dot distance beyond the orb edge on the even dots
CHAIN_PICKUP_RING_FAR = 12.0  # dot distance beyond the orb edge on the odd dots
CHAIN_LAYER_ORDER = 14600     # arc draw order: above the glow pool (14500), below the particle rings (15000)

# Boost / Overdrive mechanic (LSHIFT key)
BOOST_SPEED_MULT = 1.65
BOOST_MAX_ENERGY = 100.0
BOOST_DRAIN_RATE = 28.0
BOOST_RECHARGE_RATE = 22.0
BOOST_DAMAGE_REDUCTION = 0.35
BOOST_RAM_DAMAGE = 28
BOOST_COLOR = (255, 145, 45)
BOOST_OVERDRIVE_SECONDS = 6.0  # Overdrive powerup: infinite boost and shield top-up duration

# Repulsor (repulsor.py). A pickup fires an instant shockwave from the player: enemy bullets inside
# REPULSOR_RANGE are pushed outward (slow ones are removed) and enemies inside it are stunned.
REPULSOR_RANGE = 220.0            # world units from the player centre, for bullets and enemies alike
REPULSOR_STUN_SECONDS = 1.5       # an enemy in range stops moving and acting for this long
REPULSOR_CLEAR_SPEED = 150.0      # enemy bullets slower than this (px per second) are removed, not pushed
REPULSOR_PUSH_SPEED = 260.0       # a kept bullet is given at least this much outward radial speed
REPULSOR_COOLDOWN_SECONDS = 12.0  # after a shockwave fires, the next one waits this long
REPULSOR_MAX_CHARGES = 2          # each pickup during a cooldown stores one charge, up to this many
REPULSOR_COLOR = (190, 240, 255)  # ring and dust colour
REPULSOR_RING_SECONDS = 0.45      # ring lifetime; with reduced motion the ring holds its full size for this long
REPULSOR_DUST_COUNT = 5           # dust particles per stunned enemy (none with reduced motion)
REPULSOR_DUST_SPEED = 45.0        # px per second
REPULSOR_DUST_SECONDS = 0.4       # dust lifetime

# Pickup colours for the two powerups above. POWERUP_COLORS sits at the top of this file, before these exist.
POWERUP_COLORS["chain"] = CHAIN_COLOR
POWERUP_COLORS["repulsor"] = REPULSOR_COLOR


# Critical hits
CRIT_CHANCE_BASE = 0.10
CRIT_MULT_BASE = 2.0
CRIT_SPARK_COLOR = (255, 225, 75)

# Elite enemy settings
ELITE_SPAWN_BASE_WAVE = 3
ELITE_SPAWN_CHANCE = 0.14
ELITE_HP_MULT = 2.2
ELITE_SCORE_MULT = 2.5
ELITE_AURA_COLOR = (255, 215, 60)
ELITE_SWIFT_SPEED_MULT = 1.30        # Swift affix: enemy speed multiplier
ELITE_VOLATILE_BLAST_RADIUS = 130.0  # Volatile affix: death blast radius in px
ELITE_VOLATILE_BLAST_DAMAGE = 45     # Volatile affix: damage to enemies inside the blast
ELITE_SPLIT_COUNT = 2                # Splitter affix: copies left behind on death
ELITE_SPLIT_HP_FRAC = 0.5            # Splitter affix: each copy's max HP as a fraction of the elite's max HP
ELITE_REFLECT_COOLDOWN = 3.0         # Reflector affix: seconds between reflected shots
ELITE_REFLECT_SPEED = 260.0          # Reflector affix: speed of a reflected shot, px per second

# Boss waves. Boss rage starts once per boss, at or below BOSS_RAGE_HP_FRAC of its max HP.
BOSS_WAVE_EVERY = 5                  # A boss arrives every Nth wave
BOSS_RAGE_HP_FRAC = 0.35
BOSS_RAGE_COOLDOWN_MULT = 0.75       # Attack cooldowns are multiplied by this during rage (25 percent shorter)
BOSS_RAGE_EXTRA_PROJECTILES = 1      # Extra projectiles or pulses per volley during rage

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

# Graphics polish (wave 1). Each effect has its own switch, and all of them default on.
ENABLE_GLOW = True               # additive glow sprites: projectile heads, pickups, enemy eyes, player thruster
GLOW_POOL_CAP = 96               # hard cap on live glow quads; once full, the lowest-priority glows (eyes) are skipped
ENABLE_PARALLAX_STARS = True     # three screen-space star layers drifting at different speeds behind the arena
ENABLE_DASH_AFTERIMAGE = True    # glow streak left behind a dash, fading out over about 0.3 s
ENABLE_RIM_PULSE = True          # arena rim brightens with combat intensity
# Draw-order groups (lower values draw first): room backdrop, then the starfield, then the floor (order 0).
ROOM_BG_LAYER_ORDER = -19990
STARFIELD_LAYER_ORDER = -19980
GLOW_LAYER_ORDER = 14500         # above projectiles (14000), below the overlay (22000)

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

# Multi-core job layer (parallel.py). Pool work is opt-in and changes nothing unless a flag below is on.
# The steering pool keeps its worker processes alive and passes each frame through shared float64
# arrays, so no snapshot is pickled per frame.
#
# Measured on this machine (12 logical cores, Python 3.12, spawn, 3 workers). Method: the steering
# stage only, as in tools/bench_steer.py, median ms per frame over 300 to 600 timed frames, medians
# across 2 or 3 repeated sweeps. The serial path moved by up to about 70% between sweeps (30 enemies:
# 3.9 to 6.6 ms), so read the speedups as approximate.
#   enemies   serial   pool (3 workers)   speedup   pool faster in
#        12     0.83        0.90            0.92x       1 of 3 runs
#        16     1.28        1.10            1.16x       3 of 3
#        20     1.87        1.32            1.41x       3 of 3
#        30     5.20        1.73            3.00x       2 of 2
#        60    13.47        4.72            2.85x       2 of 2
# The pickled pool it replaced (commit ef93c82, one run) was 0.52x at 20 and 0.92x at 30, and won only
# at 60 (1.79x). Three and four workers were within run-to-run noise at 16 to 60 enemies, and two
# workers were slower at 60 (7.56 ms), so the size stays at 3.
# PARALLEL_MIN_ENEMIES = 16 is the smallest count at which the pool was faster in every run.
# A spawned worker takes about 0.45 s to start on Windows. warm() starts the workers during the first
# small frames, and the first big fight does not wait for them.
# PARALLEL_STEER_ENABLED is ON. The user enabled it ("enable multi core more better, do not worry about
# the performance gain, it will pay later"). The gain is not proven. The quiet-bench numbers below are the
# evidence on file: 15 enemies pool slower, 22 about 6% faster, 29 within noise. Quiet bench,
# tools/bench.py --wave 15 22 29 --frames 300 --repeats 5, median ms per frame, serial / inline batch /
# pool of 3 workers:
#   15 enemies: 1.93 / 2.01 / 2.39   (pool slower)
#   22 enemies: 3.45 / 3.46 / 3.25   (pool about 6% faster)
#   29 enemies: 4.68 / 4.72 / 4.62   (within noise)
# The threshold stays at 16, the smallest count the pool won in every measured run above.
# Batched steering changes enemy movement, not only speed: phase 1 moves every enemy before coordination is
# applied, so enemy movement at 16 or more live enemies differs from the interleaved serial loop. Measured on
# one seeded 587-step run (20 enemies, swarm included): enemy positions differ on 522 of 587 frames, by up to
# 43 px. Units are ordered by their per-run spawn index, not their address, so a batched run repeats for a seed.
PARALLEL_MIN_ENEMIES = 16           # live enemy count at which the batch path runs (measured above)
PARALLEL_STEER_ENABLED = True       # True: batch enemy steering may run in a process pool (see above; user-enabled)
PARALLEL_STEER_MIN_ENEMIES = PARALLEL_MIN_ENEMIES
PARALLEL_STEER_WORKERS = 3          # process-pool size when enabled
PARALLEL_LOADER_WORKERS = 4         # threads for I/O-bound asset reads

# Arena floor geometry in a worker process (map.prefetch_next_arena). The user enabled it with the rest of
# the multicore work. The menu queues the default arena, and the run's Room takes the worker's result when it
# is ready. Otherwise the Room builds the same floor in-process from the same seed (test_w4_geometry.py).
ARENA_GEOMETRY_WORKER = True

# Accessibility (Settings > Accessibility). Every option defaults to off. The saved user settings
# (access_prefs.py) set these flags at runtime, so the values here are the defaults. REDUCE_MOTION is
# defined above with the other display flags (uitheme); access_prefs.py and motion.py read it.
COLORBLIND_PALETTE = False      # swaps ENEMY_COLORS for COLORBLIND_ENEMY_COLORS (access_prefs.py)
HIGH_CONTRAST_HUD = False       # a dark plate behind every HUD number, and brighter HUD text
# Colour-blind enemy palette. Each pair stays at least CIE76 dE 14 apart under deuteranopia and
# protanopia (Machado 2009, severity 1.0), checked by test_w3_access.py.
COLORBLIND_ENEMY_COLORS = {
    "bomber": (62, 230, 235),
    "chaser": (239, 112, 217),
    "ranged": (168, 255, 48),
    "charger": (56, 219, 47),
    "swarm": (212, 173, 97),
    "tank": (64, 135, 172),
    "spitter": (247, 161, 12),
    "flyer": (30, 234, 175),
    "engineer": (255, 23, 166),
    "boss_thunder": (191, 107, 35),
    "boss_laser": (225, 237, 120),
    "boss_trapmaster": (84, 163, 128),
    "boss_swarmqueen": (145, 230, 142),
    "boss_brute": (104, 193, 255),
    "boss_abyss_gaze": (123, 137, 249),
    "boss_womb_core": (238, 42, 104),
}
