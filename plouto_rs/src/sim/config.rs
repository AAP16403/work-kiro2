#![allow(dead_code)]

use std::collections::HashMap;

pub const SCREEN_W: u32 = 980;
pub const SCREEN_H: u32 = 620;
pub const FPS: f64 = 60.0;

pub const ROOM_RADIUS_DEFAULT: f32 = 760.0;
pub const ARENA_MARGIN_DEFAULT: f32 = 0.97;
pub const ARENA_MARGIN_MIN: f32 = 0.50;
pub const ARENA_MARGIN_MAX: f32 = 0.98;
pub const WORLD_ARENA_SCALE: f32 = 1.25;
pub const DONUT_INNER_RATIO: f32 = 0.40;
pub const CROSS_ARM_RATIO: f32 = 0.46;
pub const DIAMOND_EXTENT_RATIO: f32 = std::f32::consts::SQRT_2;

pub const MAP_CIRCLE: &str = "circle";
pub const MAP_DONUT: &str = "donut";
pub const MAP_CROSS: &str = "cross";
pub const MAP_DIAMOND: &str = "diamond";

// Player stats
pub const PLAYER_SPEED: f32 = 175.0;
pub const PLAYER_HP: i32 = 100;
pub const SHIELD_MAX: i32 = 120;
pub const PLAYER_DAMAGE: i32 = 10;
pub const PLAYER_FIRE_RATE: f32 = 0.28;
pub const PLAYER_HIT_GRACE_SECONDS: f32 = 0.08;
pub const FIRE_RATE_MIN: f32 = 0.08;
pub const FIRE_RATE_RATIO_MIN: f32 = 0.65;
pub const FIRE_RATE_RATIO_MAX: f32 = 1.65;
pub const FIRE_RATE_CURVE: f32 = 0.85;

// Gameplay tuning
pub const WAVE_COOLDOWN: f32 = 2.0;
pub const MAX_ACTIVE_CONSTRUCTIONS: usize = 14;
pub const WEAPON_WAVE_UPGRADE_CHANCE: f32 = 0.5;
pub const WEAPON_PICKUP_SECONDS: f32 = 20.0;
pub const LASER_PICKUP_SECONDS: f32 = 5.0;
pub const LASER_FIRE_INTERVAL: f32 = 0.32;
pub const VORTEX_PICKUP_SECONDS: f32 = 6.0;
pub const PLAYER_MISSILE_BLAST_RADIUS: f32 = 112.0;
pub const PLAYER_FLAK_BLAST_RADIUS: f32 = 76.0;
pub const PLAYER_MORTAR_BLAST_RADIUS: f32 = 168.0;
pub const PLAYER_MORTAR_MIN_RANGE: f32 = 200.0;
pub const PLAYER_MORTAR_MAX_RANGE: f32 = 520.0;
pub const PLAYER_MORTAR_BLAST_SECONDS: f32 = 0.24;
pub const PLAYER_MORTAR_SHAKE: f32 = 4.0;
pub const PLAYER_MORTAR_ARC_HEIGHT_PX: f32 = 72.0;
pub const GAME_OVER_REVEAL_S: f32 = 1.0;

// Ultra ability
pub const ULTRA_MAX_CHARGES: i32 = 2;
pub const ULTRA_MAX_CHARGES_HARD_CAP: i32 = 4;
pub const ULTRA_COOLDOWN: f32 = 10.0;
pub const ULTRA_DAMAGE_BASE: i32 = 90;
pub const ULTRA_DAMAGE_MULT: f32 = 8.0;
pub const ULTRA_BLAST_RADIUS: f32 = 220.0;
pub const ULTRA_BEAM_THICKNESS: f32 = 16.0;
pub const ULTRA_BEAM_TTL: f32 = 0.12;
pub const ULTRA_BEAM_COLOR: [u8; 3] = [255, 230, 170];
pub const ULTRA_SPAWN_MIN_WAVE: i32 = 4;
pub const ULTRA_GUARANTEE_WAVE_GAP: i32 = 4;
pub const ULTRA_WAVE_SPAWN_BASE: f32 = 0.03;
pub const ULTRA_WAVE_SPAWN_PER_WAVE: f32 = 0.004;
pub const ULTRA_WAVE_SPAWN_MAX: f32 = 0.2;
pub const ULTRA_KILL_BASE_CHANCE: f32 = 0.015;
pub const ULTRA_KILL_PITY_THRESHOLD: i32 = 30;

// Isometric projection
pub const ISO_SCALE_X: f32 = 0.7;
pub const ISO_SCALE_Y: f32 = 0.35;

// Colors
pub const BG_TOP: [u8; 3] = [10, 15, 30];
pub const BG_BOTTOM: [u8; 3] = [5, 8, 20];
pub const FLOOR_MAIN: [u8; 3] = [30, 35, 42];
pub const FLOOR_EDGE: [u8; 3] = [50, 60, 75];
pub const FLOOR_GRID: [u8; 3] = [60, 80, 100];
pub const HUD_TEXT: [u8; 3] = [240, 240, 240];

// Timed powerups
pub const RICOCHET_DURATION: f32 = 6.0;
pub const HOMING_DURATION: f32 = 5.0;
pub const HOMING_RANGE: f32 = 260.0;
pub const HOMING_TURN_RATE: f32 = 2.4;
pub const TIME_SLOW_DURATION: f32 = 4.0;
pub const TIME_SLOW_SCALE: f32 = 0.5;
pub const MAGNET_DURATION: f32 = 10.0;
pub const MAGNET_RADIUS_MULT: f32 = 3.0;
pub const MAGNET_PULL_MULT: f32 = 1.5;
pub const RICOCHET_BOUNCES: i32 = 1;

// Chain Lightning
pub const CHAIN_DURATION: f32 = 5.0;
pub const CHAIN_RANGE: f32 = 160.0;
pub const CHAIN_DAMAGE_PERCENT: i32 = 30;
pub const CHAIN_COLOR: [u8; 3] = [200, 245, 255];
pub const CHAIN_ARC_COLOR: [u8; 3] = [235, 252, 255];
pub const CHAIN_ARC_CORE_WIDTH: f32 = 3.0;
pub const CHAIN_ARC_GLOW_WIDTH: f32 = 9.0;
pub const CHAIN_ARC_GLOW_OPACITY: u8 = 150;
pub const CHAIN_ARC_SECONDS: f32 = 0.22;
pub const CHAIN_ARC_POOL: usize = 12;
pub const CHAIN_ARC_SEGMENTS: usize = 5;
pub const CHAIN_ARC_JITTER: f32 = 7.0;
pub const CHAIN_FLICKER_SECONDS: f32 = 0.05;

// Boost / Overdrive
pub const BOOST_SPEED_MULT: f32 = 1.65;
pub const BOOST_MAX_ENERGY: f32 = 100.0;
pub const BOOST_DRAIN_RATE: f32 = 28.0;
pub const BOOST_RECHARGE_RATE: f32 = 22.0;
pub const BOOST_DAMAGE_REDUCTION: f32 = 0.35;
pub const BOOST_RAM_DAMAGE: i32 = 28;
pub const BOOST_RAM_COOLDOWN_SECONDS: f32 = 0.45;
pub const CHAIN_HOPS_PER_STEP_MAX: u8 = 8;
pub const BOOST_COLOR: [u8; 3] = [255, 145, 45];
pub const BOOST_OVERDRIVE_SECONDS: f32 = 6.0;

// Repulsor
pub const REPULSOR_RANGE: f32 = 220.0;
pub const REPULSOR_STUN_SECONDS: f32 = 1.5;
pub const REPULSOR_CLEAR_SPEED: f32 = 150.0;
pub const REPULSOR_PUSH_SPEED: f32 = 260.0;
pub const REPULSOR_COOLDOWN_SECONDS: f32 = 12.0;
pub const REPULSOR_MAX_CHARGES: i32 = 2;
pub const REPULSOR_COLOR: [u8; 3] = [190, 240, 255];
pub const REPULSOR_RING_SECONDS: f32 = 0.45;
pub const REPULSOR_DUST_COUNT: usize = 5;
pub const REPULSOR_DUST_SPEED: f32 = 45.0;
pub const REPULSOR_DUST_SECONDS: f32 = 0.4;

// Critical hits
pub const CRIT_CHANCE_BASE: f32 = 0.10;
pub const CRIT_MULT_BASE: f32 = 2.0;
pub const CRIT_SPARK_COLOR: [u8; 3] = [255, 225, 75];

// Elite enemy settings
pub const ELITE_SPAWN_BASE_WAVE: i32 = 3;
pub const ELITE_SPAWN_CHANCE: f32 = 0.14;
pub const ELITE_HP_MULT: f32 = 2.2;
pub const ELITE_SCORE_MULT: f32 = 2.5;
pub const ELITE_AURA_COLOR: [u8; 3] = [255, 215, 60];
pub const ELITE_VOLATILE_COLOR: [u8; 3] = [255, 105, 65];
pub const ELITE_SWIFT_COLOR: [u8; 3] = [80, 225, 255];
pub const ELITE_SHIELDED_COLOR: [u8; 3] = [120, 180, 255];
pub const ELITE_SPLITTER_COLOR: [u8; 3] = [255, 205, 70];
pub const ELITE_REFLECTOR_COLOR: [u8; 3] = [150, 245, 255];
pub const ELITE_MENDER_COLOR: [u8; 3] = [105, 255, 172];
pub const ELITE_WARDEN_COLOR: [u8; 3] = [115, 190, 255];
pub const ELITE_SWIFT_SPEED_MULT: f32 = 1.30;
pub const ELITE_SHIELDED_HP_FRAC: f32 = 0.40;
pub const ELITE_VOLATILE_BLAST_RADIUS: f32 = 130.0;
pub const ELITE_VOLATILE_BLAST_DAMAGE: i32 = 45;
pub const ELITE_SPLIT_COUNT: usize = 2;
pub const ELITE_SPLIT_HP_FRAC: f32 = 0.5;
pub const ELITE_REFLECT_COOLDOWN: f32 = 3.0;
pub const ELITE_REFLECT_SPEED: f32 = 260.0;
pub const ELITE_MENDER_RADIUS: f32 = 165.0;
pub const ELITE_MENDER_INTERVAL: f32 = 2.0;
pub const ELITE_MENDER_HEAL: i32 = 8;
pub const ELITE_WARD_RADIUS: f32 = 170.0;
pub const ELITE_WARD_DAMAGE_MULT: f32 = 0.75;

pub fn elite_affix_color(affix: &str) -> [u8; 3] {
    match affix {
        "volatile" => ELITE_VOLATILE_COLOR,
        "swift" => ELITE_SWIFT_COLOR,
        "shielded" => ELITE_SHIELDED_COLOR,
        "splitter" => ELITE_SPLITTER_COLOR,
        "reflector" => ELITE_REFLECTOR_COLOR,
        "mender" => ELITE_MENDER_COLOR,
        "warden" => ELITE_WARDEN_COLOR,
        _ => ELITE_AURA_COLOR,
    }
}
pub const SNIPER_AIM_SECONDS: f32 = 0.92;
pub const SNIPER_LOCK_SECONDS: f32 = 0.26;
pub const SNIPER_RECOVER_SECONDS: f32 = 0.58;

// Boss waves
pub const BOSS_WAVE_EVERY: i32 = 5;
pub const BOSS_RAGE_HP_FRAC: f32 = 0.35;
pub const BOSS_RAGE_COOLDOWN_MULT: f32 = 0.75;
pub const BOSS_RAGE_EXTRA_PROJECTILES: i32 = 1;
pub const BOSS_LASER_SWEEP_BASE_DEG: f32 = 28.0;
pub const BOSS_LASER_SWEEP_PER_PHASE_DEG: f32 = 8.0;
pub const RAGE_BANNER_TITLE: &str = "BOSS RAGE";
pub const RAGE_BANNER_COLOR: [u8; 3] = [255, 110, 70];
pub const RAGE_BANNER_DURATION: f32 = 2.4;
pub const FANFARE_MIN_GAP: f32 = 0.6;
pub const DEATH_FLASH_STRENGTH: f32 = 1.0;

// Particle & Rendering budgets
pub const PARTICLE_SOFT_CAP: usize = 450;
pub const PARTICLE_HARD_CAP: usize = 650;
pub const GLOW_POOL_CAP: usize = 96;

// Screen shake
pub const SHAKE_CAP: f32 = 14.0;
pub const SHAKE_DECAY: f32 = 20.0;
pub const SHAKE_FULL_SCALE: f32 = 1.0;
pub const SHAKE_REDUCED_SCALE: f32 = 0.5;
pub const SHAKE_OFF_SCALE: f32 = 0.0;
pub const SHAKE_HIT_IMPULSE: f32 = 2.0;
pub const SHAKE_HIT_DAMAGE_MAX_SCALE: f32 = 1.5;
pub const SHAKE_CRIT_IMPULSE: f32 = 3.0;
pub const SHAKE_HIT_FRAME_MAX: f32 = 3.0;
pub const SHAKE_HIT_CEILING: f32 = 4.0;
pub const SHAKE_PLAYER_HIT_BASE: f32 = 2.0;
pub const SHAKE_PLAYER_HIT_PER_HP: f32 = 0.25;
pub const SHAKE_PLAYER_HIT_MAX: f32 = 8.0;

// Arena events
pub const EVENT_MIN_WAVE: i32 = 4;
pub const EVENT_WAVE_CHANCE: f32 = 1.0 / 3.0;
pub const EVENT_METEOR_IMPACTS: usize = 3;
pub const EVENT_METEOR_WARN: f32 = 1.5;
pub const EVENT_METEOR_STAGGER: f32 = 0.7;
pub const EVENT_METEOR_RADIUS: f32 = 38.0;
pub const EVENT_METEOR_MIN_GAP: f32 = 90.0;
pub const EVENT_METEOR_DODGE_WINDOW: f32 = 0.8;
pub const EVENT_METEOR_DAMAGE: i32 = 16;
pub const EVENT_METEOR_LIVE: f32 = 0.25;
pub const EVENT_FLARE_WARN: f32 = 2.0;
pub const EVENT_FLARE_SWEEP: f32 = 2.6;
pub const EVENT_FLARE_SECTOR_DEG: f32 = 110.0;
pub const EVENT_FLARE_THICKNESS: f32 = 14.0;
pub const EVENT_FLARE_DAMAGE: i32 = 18;
pub const EVENT_FLARE_TICK: f32 = 0.5;
pub const EVENT_NEBULA_WARN: f32 = 1.0;
pub const EVENT_NEBULA_TTL: f32 = 8.0;
pub const EVENT_NEBULA_RADIUS: f32 = 110.0;
pub const EVENT_NEBULA_SHIELD: i32 = 24;

// Parallel steering threshold (always deterministic via spawn_index)
pub const PARALLEL_MIN_ENEMIES: usize = 16;

// Bullet signatures
pub const SIG_SPITTER_COLOR: [u8; 3] = [120, 255, 110];
pub const SIG_SPITTER_CORE: [u8; 3] = [200, 255, 170];
pub const SIG_SPITTER_RADIUS: f32 = 4.6;
pub const SIG_SPITTER_TRAIL: f32 = 12.0;
pub const SIG_RANGED_COLOR: [u8; 3] = [255, 110, 120];
pub const SIG_RANGED_CORE: [u8; 3] = [255, 236, 232];
pub const SIG_RANGED_LENGTH: f32 = 30.0;
pub const SIG_BOMBER_COLOR: [u8; 3] = [255, 150, 40];
pub const SIG_BOMBER_CORE: [u8; 3] = [255, 228, 170];
pub const SIG_BOMBER_RING: f32 = 10.0;
pub const SIG_BOSS_COLOR: [u8; 3] = [255, 70, 225];
pub const SIG_BOSS_CORE: [u8; 3] = [255, 205, 250];
pub const SIG_BOSS_RING: f32 = 15.0;
pub const SIG_RING_PULSE: f32 = 0.18;
pub const SIG_PULSE_RATE: f32 = 9.0;
pub const SIG_GLOW_OPACITY: u8 = 110;

// Unlock thresholds
pub const NEON_SURGE_UNLOCK_WAVE: i32 = 15;
pub const OBSIDIAN_UNLOCK_SCORE: i32 = 20000;

// Echo dash
pub const ECHO_DAMAGE_PERCENT: i32 = 60;
pub const ECHO_SPEED: f32 = 520.0;
pub const ECHO_TTL: f32 = 1.6;
pub const ECHO_HOMING_SECONDS: f32 = 1.2;
pub const ECHO_HOMING_RANGE: f32 = 300.0;
pub const ECHO_HOMING_TURN_RATE: f32 = 3.6;
pub const ECHO_RING_RADIUS: f32 = 34.0;
pub const ECHO_RING_SECONDS: f32 = 0.3;
pub const ECHO_COLOR: [u8; 3] = [150, 240, 255];

// Afterburn
pub const AFTERBURN_DROP_SECONDS: f32 = 0.05;
pub const AFTERBURN_LIFE_SECONDS: f32 = 2.5;
pub const AFTERBURN_MAX_SEGMENTS: usize = 12;
pub const AFTERBURN_HIT_RADIUS: f32 = 26.0;
pub const AFTERBURN_TICK_SECONDS: f32 = 0.5;
pub const AFTERBURN_DAMAGE: i32 = 4;
pub const AFTERBURN_BOSS_MULT: f32 = 0.5;
pub const AFTERBURN_CORE_RADIUS: f32 = 14.0;
pub const AFTERBURN_GLOW_OPACITY: u8 = 150;
pub const AFTERBURN_CORE_OPACITY: u8 = 215;
pub const AFTERBURN_CORE_SHADE: f32 = 0.22;
pub const AFTERBURN_FLICKER_HZ: f32 = 9.0;
pub const AFTERBURN_FLICKER_DEPTH: f32 = 0.25;
pub const AFTERBURN_COLOR: [u8; 3] = [255, 140, 40];

pub const COUNTDOWN_ROUND_DIGITS: i32 = 6;

// Shards
pub const SHARD_SPREAD_DEG: f32 = 35.0;
pub const SHARD_SPEED_FRACTION: f32 = 0.6;
pub const SHARD_SECONDS: f32 = 0.35;
pub const SHARD_DAMAGE_PERCENT: i32 = 35;
pub const SHARD_CAP: usize = 24;
pub const SHARD_HIT_RADIUS: f32 = 2.5;
pub const SHARD_STREAK_PX: f32 = 16.0;
pub const SHARD_WIDTH_PX: f32 = 7.0;
pub const SHARD_SHIMMER_DEPTH: f32 = 0.3;
pub const SHARD_SHIMMER_RATE: f32 = 18.0;

// BalanceLogic constants
pub const PLAYER_RADIUS: f32 = 4.8;
/// Reference boss radius. Still the draw-scale reference in render/world.rs; the
/// collision radius per boss comes from `enemy_radius`.
pub const BOSS_RADIUS: f32 = 33.6;
pub const DEFAULT_ENEMY_RADIUS: f32 = 13.0;
pub const ENEMY_CONTACT_DAMAGE: i32 = 10;
pub const TANK_PROJ_SPEED: f32 = 185.0;
pub const TANK_PROJ_TTL: f32 = 2.8;
pub const TANK_RANGE: f32 = 518.0;
pub const TANK_DEATH_BLAST_RADIUS: f32 = 70.0;
pub const TANK_DEATH_BLAST_DAMAGE: i32 = 15;
pub const BOMB_BLAST_RADIUS: f32 = 72.0;
pub const BOMB_BLAST_MIN_DAMAGE: i32 = 10;
pub const MAGNET_RADIUS_NORMAL: f32 = 150.0;
pub const MAGNET_RADIUS_SPECIAL: f32 = 190.0;
pub const PICKUP_RADIUS_NORMAL: f32 = 16.0;
pub const PICKUP_RADIUS_SPECIAL: f32 = 20.0;
pub const PICKUP_PULL_BASE_SPEED: f32 = 220.0;
pub const PICKUP_PULL_NEARBY_GAIN: f32 = 2.0;
pub const DASH_COOLDOWN: f32 = 1.5;

pub fn powerup_color(kind: &str) -> [u8; 3] {
    match kind {
        "heal" => [120, 255, 120],
        "damage" => [255, 120, 120],
        "speed" => [120, 180, 255],
        "firerate" => [255, 255, 120],
        "shield" => [100, 220, 255],
        "laser" => [255, 120, 255],
        "vortex" => [200, 160, 255],
        "weapon" => [230, 230, 255],
        "ultra" => [255, 240, 180],
        "boost" => [255, 145, 45],
        "drone" => [90, 255, 225],
        "ricochet" => [60, 255, 200],
        "homing" => [255, 80, 170],
        "time_slow" => [110, 130, 255],
        "magnet" => [170, 255, 70],
        "chain" => CHAIN_COLOR,
        "repulsor" => REPULSOR_COLOR,
        _ => [255, 255, 255],
    }
}

pub fn enemy_color(behavior: &str, colorblind: bool) -> [u8; 3] {
    if colorblind {
        match behavior {
            "bomber" => [62, 230, 235],
            "chaser" => [239, 112, 217],
            "ranged" => [168, 255, 48],
            "charger" => [56, 219, 47],
            "swarm" => [212, 173, 97],
            "tank" => [64, 135, 172],
            "spitter" => [247, 161, 12],
            "flyer" => [30, 234, 175],
            "engineer" => [255, 23, 166],
            "sniper" => [90, 225, 255],
            "boss_thunder" => [191, 107, 35],
            "boss_laser" => [225, 237, 120],
            "boss_trapmaster" => [84, 163, 128],
            "boss_swarmqueen" => [145, 230, 142],
            "boss_brute" => [104, 193, 255],
            "boss_abyss_gaze" => [123, 137, 249],
            "boss_womb_core" => [238, 42, 104],
            "boss_eclipse_archon" => [80, 172, 186],
            _ => [200, 200, 220],
        }
    } else {
        match behavior {
            "bomber" => [255, 160, 50],
            "chaser" => [255, 80, 80],
            "ranged" => [80, 150, 255],
            "charger" => [255, 180, 80],
            "swarm" => [220, 100, 220],
            "tank" => [100, 220, 100],
            "spitter" => [255, 220, 80],
            "flyer" => [150, 180, 255],
            "engineer" => [80, 240, 180],
            "sniper" => [190, 120, 255],
            "boss_thunder" => [180, 210, 255],
            "boss_laser" => [255, 140, 255],
            "boss_trapmaster" => [255, 180, 100],
            "boss_swarmqueen" => [230, 140, 255],
            "boss_brute" => [255, 100, 100],
            "boss_abyss_gaze" => [185, 220, 255],
            "boss_womb_core" => [255, 105, 135],
            "boss_eclipse_archon" => [110, 235, 220],
            _ => [200, 200, 220],
        }
    }
}

/// Collision radius in sim units. Values are final (the former `base * 1.05`
/// factor is folded in), fitted to each role's improved model body.
pub fn enemy_radius(behavior: &str) -> f32 {
    match behavior {
        "boss_brute" | "boss_trapmaster" | "boss_womb_core" | "boss_eclipse_archon" => BOSS_RADIUS,
        "boss_laser" => 30.0,
        "boss_swarmqueen" | "boss_abyss_gaze" => 27.0,
        "boss_thunder" => 40.0,
        _ if behavior.starts_with("boss_") => BOSS_RADIUS,
        "tank" => 17.5,
        "charger" => 17.0,
        "egg_sac" => 16.0,
        "engineer" => 14.7,
        "swarm" => 12.3,
        "flyer" => 13.86,
        "sniper" | "spitter" | "ranged" | "chaser" | "bomber" => 13.65,
        _ => DEFAULT_ENEMY_RADIUS * 1.05,
    }
}

pub fn projectile_radius(ptype: &str) -> f32 {
    let base = match ptype {
        "bomb" => 11.0,
        "mortar" => 9.2,
        "missile" => 7.7,
        "plasma" => 6.1,
        "spread" => 5.3,
        _ => 5.0,
    };
    base * 1.05
}

pub fn shake_scale_for_level(level: &str) -> f32 {
    match level {
        "reduced" => SHAKE_REDUCED_SCALE,
        "off" => SHAKE_OFF_SCALE,
        _ => SHAKE_FULL_SCALE,
    }
}

pub fn normalize_shake_level(level: &str) -> &'static str {
    match level.trim().to_ascii_lowercase().as_str() {
        "reduced" => "reduced",
        "off" => "off",
        _ => "full",
    }
}

#[derive(Debug, Clone)]
pub struct RuntimeConfig {
    pub room_radius: f32,
    pub arena_margin: f32,
    pub enable_obstacles: bool,
    pub enable_destructible_crates: bool,
    pub enable_advanced_fx: bool,
    pub advanced_fx_strength: f32,
    pub use_player_art: bool,
    pub reduce_motion: bool,
    pub colorblind_palette: bool,
    pub high_contrast_hud: bool,
    pub shake_scale: f32,
    pub enable_glow: bool,
    pub enable_parallax_stars: bool,
    pub enable_dash_afterimage: bool,
    pub enable_rim_pulse: bool,
    pub enable_bullet_signatures: bool,
    pub enable_echo: bool,
    pub enable_combo_ring: bool,
    pub enable_death_fade: bool,
    pub enable_afterburn: bool,
    pub enable_shards: bool,
    pub enable_powerup_edges: bool,
}

impl Default for RuntimeConfig {
    fn default() -> Self {
        Self::from_defaults()
    }
}

impl RuntimeConfig {
    pub fn from_defaults() -> Self {
        Self {
            room_radius: ROOM_RADIUS_DEFAULT,
            arena_margin: ARENA_MARGIN_DEFAULT,
            enable_obstacles: false,
            enable_destructible_crates: false,
            enable_advanced_fx: true,
            advanced_fx_strength: 0.55,
            use_player_art: true,
            reduce_motion: false,
            colorblind_palette: false,
            high_contrast_hud: false,
            shake_scale: SHAKE_FULL_SCALE,
            enable_glow: true,
            enable_parallax_stars: true,
            enable_dash_afterimage: true,
            enable_rim_pulse: true,
            enable_bullet_signatures: true,
            enable_echo: true,
            enable_combo_ring: true,
            enable_death_fade: true,
            enable_afterburn: true,
            enable_shards: true,
            enable_powerup_edges: true,
        }
    }

    #[inline]
    pub fn motion_factor(&self) -> f32 {
        if self.reduce_motion { 0.0 } else { 1.0 }
    }
}

#[allow(dead_code)]
fn _keep_hashmap(_: HashMap<String, i32>) {}
