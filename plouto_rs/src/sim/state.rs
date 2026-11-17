use crate::sim::achievements::RunStats;
use crate::sim::behaviors::SwarmBrain;
use crate::sim::config::{
    enemy_radius, projectile_radius, ARENA_MARGIN_DEFAULT, CRIT_CHANCE_BASE, CRIT_MULT_BASE,
    MAP_DONUT, PLAYER_HP, PLAYER_RADIUS, ROOM_RADIUS_DEFAULT, RuntimeConfig, SCREEN_H, SCREEN_W,
    SHAKE_CAP,
};
use crate::sim::director::AttackDirectorState;
use crate::sim::drone::DroneState;
use crate::sim::enemy::Enemy;
use crate::sim::events::ArenaEvent;
use crate::sim::hazards::{LaserBeam, ThunderLine, Trap};
use crate::sim::layout::Obstacle;
use crate::sim::level::{difficulty_mods, UltraPityTracker};
use crate::sim::math::{clamp_entity_to_map, compute_room_radius, Vec2};
use crate::sim::mutators::{
    apply_mutators, combined_score_multiplier, normalize_selection, scaled_max_hp, RunRules,
};
use crate::sim::perception::PerceptionMemory;
use crate::sim::player::Player;
use crate::sim::projectile::Projectile;
use crate::sim::powerup::PowerUp;
use crate::sim::rng::SimRng;
use crate::sim::rpg::{
    recompute_temp_mods, ActiveTempReward, PermRewardDef, TempMods, TempRewardDef,
};
use crate::sim::score::ScoreTracker;
use crate::sim::skins::{get_skin, RunSkin, DEFAULT_SKIN_ID};
use crate::sim::specials::{AfterburnSystem, ChainSystem, EchoRing, RepulsorSystem, ShardPool};
use crate::sim::steer::FormationState;
use crate::sim::weapons::get_weapon_for_wave;

#[derive(Debug, Clone, Default)]
pub struct SimInput {
    pub move_dir: Vec2,
    pub aim_world: Vec2,
    pub fire_held: bool,
    pub boost_held: bool,
    pub dash_pressed: bool,
    pub ultra_pressed: bool,
}

#[derive(Debug, Clone)]
pub struct BossRewardOffer {
    pub temp_options: Vec<&'static TempRewardDef>,
    pub perm_options: Vec<&'static PermRewardDef>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DamageTarget {
    Player,
    Enemy(u64),
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DamageRejection {
    NonPositive,
    Invulnerable,
    MissingTarget,
    SupersededByStrongerSameStepHit,
}

/// A single, resolved damage application. The adjusted amount is pre-shield;
/// shield and health amounts describe where it actually landed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DamageResult {
    pub source: &'static str,
    pub target: DamageTarget,
    pub raw_damage: i32,
    pub adjusted_damage: i32,
    pub shield_damage: i32,
    pub health_damage: i32,
    pub rejected: Option<DamageRejection>,
    pub killed: bool,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PendingPlayerDamage {
    pub source: &'static str,
    pub raw_damage: i32,
    pub grace_seconds: f32,
}

#[derive(Debug, Clone)]
pub struct PendingReflect {
    pub pos: Vec2,
    pub dir: Vec2,
    pub damage: i32,
    pub delay_left: f32,
}

/// Event stream emitted deterministically by `sim::step()` so audio, particles, popups, HUD, and
/// advanced shader FX react without coupling simulation math to rendering state.
#[derive(Debug, Clone)]
pub enum SimEvent {
    DamageResolved(DamageResult),
    Audio {
        clip: &'static str,
        volume: f32,
        pitch_jitter: f32,
        min_gap: f32,
    },
    AudioCue(&'static str),
    Banner {
        title: String,
        subtitle: String,
        color: [u8; 3],
        duration: f32,
    },
    Popup {
        pos: Vec2,
        text: String,
        color: [u8; 3],
        big: bool,
    },
    HitParticles {
        pos: Vec2,
        color: [u8; 3],
    },
    CritSpark(Vec2),
    ShieldHit {
        pos: Vec2,
        absorbed: i32,
    },
    WardAbsorb {
        pos: Vec2,
    },
    TetherBeam {
        from: Vec2,
        to: Vec2,
        color: [u8; 3],
    },
    DeathExplosion {
        pos: Vec2,
        color: [u8; 3],
        behavior: String,
    },
    KillBurst {
        pos: Vec2,
        color: [u8; 3],
        big: bool,
    },
    BossDeath(Vec2, [u8; 3]),
    BossDeathFlash,
    BossTeleport {
        from: Vec2,
        to: Vec2,
        color: [u8; 3],
    },
    FlakDetonation(Vec2),
    Shockwave {
        pos: Vec2,
        color: [u8; 3],
        max_radius: f32,
        ttl: f32,
    },
    PickupCollection {
        pos: Vec2,
        color: [u8; 3],
    },
    PickupRing {
        pos: Vec2,
        color: [u8; 3],
    },
    DashEffect {
        pos: Vec2,
        dir: Vec2,
        color: [u8; 3],
    },
    MuzzleFlash {
        pos: Vec2,
        dir: Vec2,
    },
    LaserBeamFx {
        start: Vec2,
        end: Vec2,
        color: [u8; 3],
    },
    VortexSwirl {
        pos: Vec2,
        time: f32,
        radius: f32,
    },
    BoostFlame {
        pos: Vec2,
        dir: Vec2,
    },
    StepDust {
        pos: Vec2,
        dir: Vec2,
    },
    EliteAura {
        pos: Vec2,
        color: [u8; 3],
    },
    RepulsorBlast {
        pos: Vec2,
        stunned_positions: Vec<Vec2>,
    },
    UltraFlash {
        pos: Vec2,
        color: [u8; 3],
        radius: f32,
    },
    ScreenFlashHit(f32),
    ScreenFlashUltra(f32),
    ScreenFlashBoost(f32),
    ScreenFlashDash(f32),
    WaveCleared(i32),
    BossRewardOpened,
    GameOver,
}

#[derive(Debug, Clone)]
pub struct RunSetup {
    pub seed: u64,
    pub difficulty: String,
    pub map_type: String,
    pub skin_id: String,
    pub mutator_ids: Vec<String>,
    pub daily_date: Option<String>,
    pub view_w: u32,
    pub view_h: u32,
    pub arena_margin: f32,
    pub auto_shoot: bool,
    pub runtime: RuntimeConfig,
}

impl Default for RunSetup {
    fn default() -> Self {
        Self {
            seed: 1,
            difficulty: "normal".to_string(),
            map_type: "circle".to_string(),
            skin_id: DEFAULT_SKIN_ID.to_string(),
            mutator_ids: Vec::new(),
            daily_date: None,
            view_w: SCREEN_W,
            view_h: SCREEN_H,
            arena_margin: ARENA_MARGIN_DEFAULT,
            auto_shoot: true,
            runtime: RuntimeConfig::default(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct SimState {
    pub time: f32,
    /// Accumulated enemy-local clock. Time Slow scales this while player time continues.
    pub enemy_time: f32,
    pub wave: i32,
    pub difficulty: String,
    pub map_type: String,
    pub seed: u64,
    pub daily_date: Option<String>,
    pub mutators: Vec<String>,
    pub rules: RunRules,
    pub run_skin: RunSkin,
    pub runtime: RuntimeConfig,
    pub auto_shoot: bool,

    pub rng: SimRng,
    pub next_entity_id: u64,
    pub enemy_spawn_count: i64,

    pub room_radius: f32,
    pub arena_margin: f32,
    pub layout_seed: u64,
    pub layout_segment: i32,
    pub obstacles: Vec<Obstacle>,

    pub player: Player,
    pub max_enemies: usize,
    pub enemies: Vec<Enemy>,
    pub projectiles: Vec<Projectile>,
    pub powerups: Vec<PowerUp>,
    pub traps: Vec<Trap>,
    pub lasers: Vec<LaserBeam>,
    pub thunders: Vec<ThunderLine>,

    pub drone: DroneState,
    pub chain: ChainSystem,
    pub repulsor: RepulsorSystem,
    pub afterburn: AfterburnSystem,
    pub shards: ShardPool,
    pub echo_rings: Vec<EchoRing>,
    pub swarm_brain: Option<SwarmBrain>,
    pub perception_mem: PerceptionMemory,
    pub formation: FormationState,
    pub director: AttackDirectorState,
    pub arena_event: Option<ArenaEvent>,
    pub pity: UltraPityTracker,

    pub wave_active: bool,
    pub last_wave_clear: f32,
    pub enemy_combo_value: i32,
    pub enemy_combo_text: String,

    pub hitstop: f32,
    pub shake: f32,
    pub time_slow_was_on: bool,
    pub fanfare_stamp: Option<f32>,

    pub shield_regen_carry: f32,
    pub active_temp_rewards: Vec<ActiveTempReward>,
    pub temp_mods: TempMods,
    pub run_permanent_rewards: Vec<String>,
    pub last_reward_temp_key: String,
    pub last_reward_perm_key: String,
    pub dash_cd_mult: f32,
    pub dash_cd_difficulty: f32,
    pub incoming_damage_mult: f32,
    pub pending_boss_reward: Option<BossRewardOffer>,

    pub score: ScoreTracker,
    pub run_stats: RunStats,
    pub pending_reflects: Vec<PendingReflect>,
    pub(crate) pending_player_damage: Vec<PendingPlayerDamage>,
    pub(crate) chain_hops_this_step: u8,
    pub game_over: bool,
}

impl SimState {
    pub fn new(mut setup: RunSetup) -> Self {
        // Interior cover has been removed from the Rust game. Force this off here
        // as well as in defaults so legacy settings and replay files cannot restore it.
        setup.runtime.enable_obstacles = false;
        let mut rng = SimRng::new(setup.seed);
        let difficulty = setup.difficulty.to_ascii_lowercase();
        let mutators = normalize_selection(setup.mutator_ids.iter().map(String::as_str));
        let rules = apply_mutators(&mutators);
        let mods = difficulty_mods(&difficulty);

        let skin_def = get_skin(&setup.skin_id).unwrap_or_else(|| get_skin(DEFAULT_SKIN_ID).unwrap());
        let run_skin = RunSkin::from_skin_id(skin_def.id);

        let room_radius = if setup.view_w > 0 && setup.view_h > 0 {
            compute_room_radius(setup.view_w, setup.view_h, setup.arena_margin)
        } else {
            ROOM_RADIUS_DEFAULT
        };

        let layout_seed = rng.range_i32(0, 1_000_000_000) as u64;
        let obstacles = Vec::new();

        let max_hp = scaled_max_hp(PLAYER_HP, &rules);
        let spawn_pos = if setup.map_type == MAP_DONUT {
            Vec2::new(0.0, -(room_radius * 0.68))
        } else {
            Vec2::ZERO
        };
        let mut player = Player::new(spawn_pos, max_hp);
        player.current_weapon = get_weapon_for_wave(1, &mut rng);

        let incoming_damage_mult = match difficulty.as_str() {
            "easy" => 0.85,
            "hard" => 1.15,
            _ => 1.0,
        };

        let score_mult = combined_score_multiplier(&mutators);

        Self {
            time: 0.0,
            enemy_time: 0.0,
            wave: 1,
            difficulty: difficulty.clone(),
            map_type: setup.map_type,
            seed: setup.seed,
            daily_date: setup.daily_date,
            mutators,
            rules,
            run_skin,
            runtime: setup.runtime,
            auto_shoot: setup.auto_shoot,
            rng,
            next_entity_id: 1,
            enemy_spawn_count: 0,
            room_radius,
            arena_margin: setup.arena_margin,
            layout_seed,
            layout_segment: 0,
            obstacles,
            player,
            max_enemies: mods.max_enemies,
            enemies: Vec::with_capacity(32),
            projectiles: Vec::with_capacity(128),
            powerups: Vec::with_capacity(16),
            traps: Vec::with_capacity(16),
            lasers: Vec::with_capacity(16),
            thunders: Vec::with_capacity(8),
            drone: DroneState::new(),
            chain: ChainSystem::new(),
            repulsor: RepulsorSystem::new(),
            afterburn: AfterburnSystem::new(),
            shards: ShardPool::new(),
            echo_rings: Vec::with_capacity(8),
            swarm_brain: None,
            perception_mem: PerceptionMemory::new(max_hp, setup.view_w, setup.view_h),
            formation: FormationState::new(spawn_pos),
            director: AttackDirectorState::default(),
            arena_event: None,
            pity: UltraPityTracker::default(),
            wave_active: false,
            last_wave_clear: 0.0,
            enemy_combo_value: 0,
            enemy_combo_text: String::new(),
            hitstop: 0.0,
            shake: 0.0,
            time_slow_was_on: false,
            fanfare_stamp: None,
            shield_regen_carry: 0.0,
            active_temp_rewards: Vec::new(),
            temp_mods: recompute_temp_mods(&[]),
            run_permanent_rewards: Vec::new(),
            last_reward_temp_key: String::new(),
            last_reward_perm_key: String::new(),
            dash_cd_mult: 1.0,
            dash_cd_difficulty: mods.dash_cd,
            incoming_damage_mult,
            pending_boss_reward: None,
            score: ScoreTracker::new(&difficulty, score_mult),
            run_stats: RunStats::default(),
            pending_reflects: Vec::with_capacity(4),
            pending_player_damage: Vec::with_capacity(4),
            chain_hops_this_step: 0,
            game_over: false,
        }
    }

    pub fn alloc_id(&mut self) -> u64 {
        let id = self.next_entity_id;
        self.next_entity_id += 1;
        id
    }

    pub fn effective_player_damage(&self) -> i32 {
        let dmg = (self.player.damage as f32)
            * self.temp_mods.damage
            * self.rules.player_damage_mult;
        (dmg + 0.5).floor().max(1.0) as i32
    }

    pub fn effective_player_speed(&self) -> f32 {
        self.player.speed * self.temp_mods.speed
    }

    pub fn effective_player_fire_rate(&self) -> f32 {
        (self.player.fire_rate * self.temp_mods.fire_rate).max(crate::sim::config::FIRE_RATE_MIN)
    }

    pub fn effective_crit_chance(&self) -> f32 {
        self.player.crit_chance_bonus + self.temp_mods.crit_chance
    }

    pub fn effective_crit_mult(&self) -> f32 {
        self.player.crit_mult_bonus + self.temp_mods.crit_mult
    }

    /// Weapon crit chance + player/reward bonuses (does not include base weapon crit twice).
    pub fn total_weapon_crit_chance(&self, weapon_crit: f32) -> f32 {
        let _ = CRIT_CHANCE_BASE;
        let _ = CRIT_MULT_BASE;
        (weapon_crit + self.effective_crit_chance()).clamp(0.0, 0.85)
    }

    pub fn has_infinite_boost(&self) -> bool {
        self.temp_mods.boost_inf || self.time < self.player.infinite_boost_until
    }

    pub fn add_shake(&mut self, amount: f32, limit: Option<f32>) {
        if amount <= 0.0 {
            return;
        }
        let cap = limit.unwrap_or(SHAKE_CAP).min(SHAKE_CAP);
        // Many same-frame pellets, fragments, and nearby deaths represent one
        // impact cluster. Keep the strongest impulse so small effects cannot
        // stack over a more important hit; `limit` still bounds that source.
        let impulse = amount.min(cap);
        self.shake = self.shake.max(impulse).min(SHAKE_CAP);
    }

    #[inline]
    pub fn player_radius(&self) -> f32 {
        PLAYER_RADIUS
    }

    #[inline]
    pub fn enemy_radius_of(behavior: &str) -> f32 {
        enemy_radius(behavior)
    }

    #[inline]
    pub fn projectile_radius_of(ptype: &str) -> f32 {
        projectile_radius(ptype)
    }

    pub fn ultra_variant_name(&self) -> &'static str {
        match self.player.ultra_variant_idx % 3 {
            0 => "Beam",
            1 => "Tri-Beam",
            _ => "Shockwave",
        }
    }

    /// Update room radius on resize or arena margin change and immediately clamp active entities inside.
    pub fn on_view_resized(&mut self, view_w: u32, view_h: u32, arena_margin: f32) {
        self.arena_margin = arena_margin;
        self.room_radius = compute_room_radius(view_w, view_h, arena_margin);
        self.perception_mem.view_w = view_w;
        self.perception_mem.view_h = view_h;
        let p_pad = PLAYER_RADIUS * 2.0 + 4.0;
        self.player.pos = clamp_entity_to_map(
            self.player.pos,
            self.room_radius,
            p_pad,
            &self.map_type,
        );
        for e in &mut self.enemies {
            e.pos = clamp_entity_to_map(
                e.pos,
                self.room_radius,
                e.radius + 6.0,
                &self.map_type,
            );
            e.prev_pos = e.pos;
        }
        for pu in &mut self.powerups {
            pu.pos = clamp_entity_to_map(pu.pos, self.room_radius, 12.0, &self.map_type);
        }
        for tr in &mut self.traps {
            tr.pos = clamp_entity_to_map(tr.pos, self.room_radius, 10.0, &self.map_type);
        }
    }
}
