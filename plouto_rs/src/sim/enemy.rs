use crate::sim::config::enemy_radius;
use crate::sim::math::Vec2;
use std::f32::consts::TAU;

/// Player-facing identity shared by boss banners, the HUD, and the field guide.
pub fn boss_title(behavior: &str) -> String {
    let name = match behavior {
        "boss_thunder" => "STORM SOVEREIGN",
        "boss_laser" => "PRISMA OVERLORD",
        "boss_trapmaster" => "FORGE WARDEN",
        "boss_swarmqueen" => "BROOD MATRIARCH",
        "boss_brute" => "GORGON JUGGERNAUT",
        "boss_abyss_gaze" => "OCULAR ABYSS",
        "boss_womb_core" => "ORIGIN NEXUS",
        "boss_eclipse_archon" => "ECLIPSE ARCHON",
        _ => {
            let stripped = behavior.strip_prefix("boss_").unwrap_or(behavior);
            return stripped.replace('_', " ").to_ascii_uppercase();
        }
    };
    name.to_string()
}

pub const RUN_KEY_STEP: i64 = 7919;
pub const SWARM_SLOTS: i64 = 127;
pub const SWARM_RANKS: i64 = 97;
pub const WOMB_PULSE_TELEGRAPH: f32 = 0.52;
pub const TRAPMASTER_TELEGRAPH: f32 = 0.72;
pub const ABYSS_GAZE_TELEGRAPH: f32 = 0.68;
pub const SWARMQUEEN_TELEGRAPH: f32 = 0.78;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BossPersona {
    Aggressive,
    Cautious,
    Trickster,
}

impl BossPersona {
    pub fn as_str(self) -> &'static str {
        match self {
            BossPersona::Aggressive => "aggressive",
            BossPersona::Cautious => "cautious",
            BossPersona::Trickster => "trickster",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum EnemyRole {
    Chaser,
    Ranged,
    Sniper,
    Bomber,
    Tank,
    Charger,
    Spitter,
    Flyer,
    Engineer,
    Swarm,
    EggSac,
    Boss,
}

impl EnemyRole {
    pub fn from_key(behavior: &str) -> Option<Self> {
        match behavior {
            "chaser" => Some(Self::Chaser),
            "ranged" => Some(Self::Ranged),
            "sniper" => Some(Self::Sniper),
            "bomber" => Some(Self::Bomber),
            "tank" => Some(Self::Tank),
            "charger" => Some(Self::Charger),
            "spitter" => Some(Self::Spitter),
            "flyer" => Some(Self::Flyer),
            "engineer" => Some(Self::Engineer),
            "swarm" => Some(Self::Swarm),
            "egg_sac" => Some(Self::EggSac),
            s if s == "boss" || s.starts_with("boss_") => Some(Self::Boss),
            _ => None,
        }
    }

    pub const fn key(self) -> &'static str {
        match self {
            Self::Chaser => "chaser",
            Self::Ranged => "ranged",
            Self::Sniper => "sniper",
            Self::Bomber => "bomber",
            Self::Tank => "tank",
            Self::Charger => "charger",
            Self::Spitter => "spitter",
            Self::Flyer => "flyer",
            Self::Engineer => "engineer",
            Self::Swarm => "swarm",
            Self::EggSac => "egg_sac",
            Self::Boss => "boss",
        }
    }

    pub const fn index(self) -> usize {
        match self {
            Self::Chaser => 0,
            Self::Ranged => 1,
            Self::Sniper => 2,
            Self::Bomber => 3,
            Self::Tank => 4,
            Self::Charger => 5,
            Self::Spitter => 6,
            Self::Flyer => 7,
            Self::Engineer => 8,
            Self::Swarm => 9,
            Self::EggSac => 10,
            Self::Boss => 11,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum AttackPhase {
    Idle,
    Windup { frac: f32 },
    Active,
    Recover,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum EnemySubState {
    #[default]
    None,
    // Charger
    ChargerRepositioning,
    ChargerWindup,
    ChargerCharging,
    ChargerCooldown,
    // Flyer
    FlyerCircling,
    FlyerWindup,
    FlyerDashing,
    // Sniper
    SniperWindup,
    SniperRecover,
    // Common ranged volleys
    RangedWindup,
    SpitterWindup,
    EngineerWindup,
    BomberWindup,
    TankWindup,
    // Boss Thunder
    ThunderStalk,
    ThunderTeleportOut,
    ThunderTeleportIn,
    ThunderWindup,
    ThunderAttack,
    // Origin Nexus
    WombPulseTelegraph,
    // Boss Laser
    LaserReposition,
    LaserMoving,
    LaserCharge,
    LaserAttack,
    LaserWingWindup,
    // Boss Brute
    BruteChase,
    BruteTelegraph,
    BruteCharge,
    BruteStun,
    BruteRecover,
    // Eclipse Archon
    EclipseOrbit,
    EclipseCharge,
    EclipseBurst,
    EclipseEscape,
    // Brood Matriarch
    QueenBroodTelegraph,
    QueenSwarmTelegraph,
    QueenVolleyTelegraph,
    // Forge Warden and Ocular Abyss
    TrapmasterTelegraph,
    AbyssTelegraph,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AttackDenialReason {
    SameTypeStagger,
    CommitmentBudget,
}

#[derive(Debug, Clone)]
pub struct EnemyAi {
    pub attack_mult: f32,
    pub forward_lock_t: f32,
    pub formation_bias: Option<f32>,
    pub formation_slot: Option<u16>,
    pub slot_bias: Option<f32>,
    pub squad_rank: Option<f32>,
    pub reflect_cd_left: f32,
    pub boost_ram_ready_at: f32,
    pub dodge_active_left: f32,
    pub dodge_cooldown_left: f32,
    pub dodge_direction: Vec2,
    pub attack_denied_t: f32,
    pub attack_denial_reason: Option<AttackDenialReason>,
    /// Attack scheduler timestamps measured against `SimState::enemy_time`.
    pub last_attack_started_at: f32,
    pub last_forced_attack_started_at: f32,
    pub mender_cd: f32,
    pub mender_pulse: f32,
    pub sniper_aim: Vec2,

    // Core AI v2 fields
    pub heading: Vec2,
    pub accel_vec: Vec2,
    pub last_seen_intent: Vec2,
    pub retarget_left: f32,
    pub aimed_at_t: f32,
    pub director_granted: bool,
    pub formation_slot_ang: Option<f32>,
    /// Fixed-size projectile threat reaction tracker: (proj_hash, seen_time), 0 = empty.
    pub threat_seen: [(u64, f32); 8],

    // Generic sub-state machine & timers
    pub sub_state: EnemySubState,
    pub state_timer: Option<f32>,
    pub sub_timer: f32,

    // Chaser lunge
    pub lunge_cd: Option<f32>,
    pub lunge_t: f32,
    pub lunge_windup: f32,
    pub lunge_dir: Vec2,
    pub orbit_sign: Option<f32>,

    // Charger / Flyer / Brute dash & charge
    pub charger_dashing: bool,
    pub charge_target: Vec2,
    pub charge_dir: Vec2,
    pub dash_target: Vec2,

    // Ranged / Spitter
    pub burst_left: i32,
    pub burst_gap: f32,
    pub relocate_t: f32,
    pub strafe_sign: Option<f32>,
    pub volley_mode: i32,

    // Tank
    pub brace_t: Option<f32>,
    pub push_t: f32,

    // Engineer support pulse
    pub support_cd: f32,
    pub support_pulse: f32,

    // Egg sac
    pub hatch_timer: f32,
    pub max_hatch_timer: f32,

    // Telegraph laser id
    pub telegraph_beam_id: Option<u64>,

    // Boss fields
    pub boss_initialized: bool,
    pub boss_max_hp: i32,
    pub boss_phase_recovery_left: f32,
    pub persona: BossPersona,
    pub phase: i32,
    pub gun_idx: usize,
    pub rage: bool,
    pub move_target: Vec2,
    pub summon_targets: [Vec2; 3],
    pub summon_target_count: u8,
    pub laser_tick: f32,
}

impl Default for EnemyAi {
    fn default() -> Self {
        Self {
            attack_mult: 1.0,
            forward_lock_t: 0.0,
            formation_bias: None,
            formation_slot: None,
            slot_bias: None,
            squad_rank: None,
            reflect_cd_left: 0.0,
            boost_ram_ready_at: 0.0,
            dodge_active_left: 0.0,
            dodge_cooldown_left: 0.0,
            dodge_direction: Vec2::ZERO,
            attack_denied_t: 0.0,
            attack_denial_reason: None,
            last_attack_started_at: -1_000.0,
            last_forced_attack_started_at: -1_000.0,
            mender_cd: 0.0,
            mender_pulse: 0.0,
            sniper_aim: Vec2::ZERO,
            heading: Vec2::new(1.0, 0.0),
            accel_vec: Vec2::ZERO,
            last_seen_intent: Vec2::ZERO,
            retarget_left: 0.0,
            aimed_at_t: 0.0,
            director_granted: false,
            formation_slot_ang: None,
            threat_seen: [(0, 0.0); 8],
            sub_state: EnemySubState::None,
            state_timer: None,
            sub_timer: 0.0,
            lunge_cd: None,
            lunge_t: 0.0,
            lunge_windup: 0.0,
            lunge_dir: Vec2::new(1.0, 0.0),
            orbit_sign: None,
            charger_dashing: false,
            charge_target: Vec2::ZERO,
            charge_dir: Vec2::new(1.0, 0.0),
            dash_target: Vec2::ZERO,
            burst_left: 0,
            burst_gap: 0.0,
            relocate_t: 0.0,
            strafe_sign: None,
            volley_mode: 0,
            brace_t: None,
            push_t: 0.0,
            support_cd: 2.2,
            support_pulse: 0.0,
            hatch_timer: 4.0,
            max_hatch_timer: 4.0,
            telegraph_beam_id: None,
            boss_initialized: false,
            boss_max_hp: 0,
            boss_phase_recovery_left: 0.0,
            persona: BossPersona::Aggressive,
            phase: 0,
            gun_idx: 0,
            rage: false,
            move_target: Vec2::ZERO,
            summon_targets: [Vec2::ZERO; 3],
            summon_target_count: 0,
            laser_tick: 0.0,
        }
    }
}

#[derive(Debug, Clone)]
pub struct Enemy {
    pub id: u64,
    pub spawn_index: i64,
    pub pos: Vec2,
    pub prev_pos: Vec2,
    pub vel: Vec2,
    pub hp: i32,
    pub max_hp: i32,
    pub speed: f32,
    pub behavior: String,
    pub role: EnemyRole,
    pub radius: f32,
    pub t: f32,
    pub attack_cd: f32,
    pub seed: f32,
    pub is_elite: bool,
    pub elite_affix: String,
    pub shield: i32,
    pub hit_flash_timer: f32,
    pub stun_until: f32,
    pub vortex_acc: f32,
    pub is_dead: bool,
    pub ai: EnemyAi,
}

impl Enemy {
    pub fn new(id: u64, pos: Vec2, hp: i32, speed: f32, behavior: &str) -> Self {
        Self {
            id,
            spawn_index: -1,
            pos,
            prev_pos: pos,
            vel: Vec2::ZERO,
            hp,
            max_hp: hp,
            speed,
            behavior: behavior.to_string(),
            role: EnemyRole::from_key(behavior).unwrap_or(EnemyRole::Chaser),
            radius: enemy_radius(behavior),
            t: 0.0,
            attack_cd: 0.0,
            seed: 0.0,
            is_elite: false,
            elite_affix: String::new(),
            shield: 0,
            hit_flash_timer: 0.0,
            stun_until: -1.0,
            vortex_acc: 0.0,
            is_dead: false,
            ai: EnemyAi::default(),
        }
    }

    pub fn is_boss(&self) -> bool {
        self.role == EnemyRole::Boss || self.behavior.starts_with("boss_")
    }

    pub fn is_stunned(&self, now: f32) -> bool {
        now < self.stun_until
    }

    pub fn attack_phase(&self) -> AttackPhase {
        match self.role {
            EnemyRole::Chaser => {
                if self.ai.lunge_windup > 0.0 {
                    AttackPhase::Windup {
                        frac: (1.0 - self.ai.lunge_windup / 0.22).clamp(0.0, 1.0),
                    }
                } else if self.ai.lunge_t > 0.0 {
                    AttackPhase::Active
                } else {
                    AttackPhase::Idle
                }
            }
            EnemyRole::Charger => match self.ai.sub_state {
                EnemySubState::ChargerWindup => AttackPhase::Windup {
                    frac: (1.0 - self.ai.state_timer.unwrap_or(0.0) / 0.5).clamp(0.0, 1.0),
                },
                EnemySubState::ChargerCharging => AttackPhase::Active,
                EnemySubState::ChargerCooldown => AttackPhase::Recover,
                _ => AttackPhase::Idle,
            },
            EnemyRole::Flyer => match self.ai.sub_state {
                EnemySubState::FlyerWindup => AttackPhase::Windup {
                    frac: (1.0 - self.ai.state_timer.unwrap_or(0.0) / 0.45).clamp(0.0, 1.0),
                },
                EnemySubState::FlyerDashing => AttackPhase::Active,
                _ => AttackPhase::Idle,
            },
            EnemyRole::Sniper => match self.ai.sub_state {
                EnemySubState::SniperWindup => AttackPhase::Windup {
                    frac: (1.0 - self.ai.sub_timer / 0.92).clamp(0.0, 1.0),
                },
                EnemySubState::SniperRecover => AttackPhase::Recover,
                _ => AttackPhase::Idle,
            },
            EnemyRole::Ranged => match self.ai.sub_state {
                EnemySubState::RangedWindup => AttackPhase::Windup {
                    frac: (1.0 - self.ai.sub_timer / 0.34).clamp(0.0, 1.0),
                },
                _ => AttackPhase::Idle,
            },
            EnemyRole::Spitter => match self.ai.sub_state {
                EnemySubState::SpitterWindup => AttackPhase::Windup {
                    frac: (1.0 - self.ai.sub_timer / 0.38).clamp(0.0, 1.0),
                },
                _ => AttackPhase::Idle,
            },
            EnemyRole::Engineer => match self.ai.sub_state {
                EnemySubState::EngineerWindup => AttackPhase::Windup {
                    frac: (1.0 - self.ai.sub_timer / 0.54).clamp(0.0, 1.0),
                },
                _ => AttackPhase::Idle,
            },
            EnemyRole::Bomber => match self.ai.sub_state {
                EnemySubState::BomberWindup => AttackPhase::Windup {
                    frac: (1.0 - self.ai.sub_timer / 0.60).clamp(0.0, 1.0),
                },
                _ => AttackPhase::Idle,
            },
            EnemyRole::Tank => match self.ai.sub_state {
                EnemySubState::TankWindup => AttackPhase::Windup {
                    frac: (1.0 - self.ai.sub_timer / 0.48).clamp(0.0, 1.0),
                },
                _ => AttackPhase::Idle,
            },
            EnemyRole::Boss => match self.ai.sub_state {
                EnemySubState::ThunderWindup
                | EnemySubState::WombPulseTelegraph
                | EnemySubState::LaserCharge
                | EnemySubState::LaserWingWindup
                | EnemySubState::BruteTelegraph
                | EnemySubState::EclipseCharge
                | EnemySubState::QueenBroodTelegraph
                | EnemySubState::QueenSwarmTelegraph
                | EnemySubState::QueenVolleyTelegraph
                | EnemySubState::TrapmasterTelegraph
                | EnemySubState::AbyssTelegraph => AttackPhase::Windup { frac: 0.5 },
                EnemySubState::ThunderAttack
                | EnemySubState::LaserAttack
                | EnemySubState::BruteCharge
                | EnemySubState::EclipseBurst => AttackPhase::Active,
                EnemySubState::BruteStun | EnemySubState::BruteRecover => AttackPhase::Recover,
                _ => AttackPhase::Idle,
            },
            EnemyRole::Swarm | EnemyRole::EggSac => AttackPhase::Idle,
        }
    }
}

/// Assign deterministic per-run spawn index and derived swarm keys without relying on memory addresses.
pub fn assign_run_keys(enemy: &mut Enemy, enemy_spawn_count: &mut i64) {
    if enemy.spawn_index < 0 {
        let idx = *enemy_spawn_count;
        *enemy_spawn_count = idx + 1;
        enemy.spawn_index = idx;
    }
    if enemy.ai.slot_bias.is_none() {
        let m = (enemy.spawn_index * RUN_KEY_STEP).rem_euclid(SWARM_SLOTS);
        enemy.ai.slot_bias = Some((m as f32 / SWARM_SLOTS as f32) * TAU);
    }
    if enemy.ai.squad_rank.is_none() {
        let m = (enemy.spawn_index * RUN_KEY_STEP).rem_euclid(SWARM_RANKS);
        enemy.ai.squad_rank = Some(m as f32 / SWARM_RANKS as f32);
    }
}

/// Stable swarm subgroup and lane derived from the run key, so casualties do
/// not cause surviving fighters to jump to newly numbered formation slots.
pub fn swarm_formation_key(enemy: &Enemy) -> (usize, usize) {
    let spawn_key = if enemy.spawn_index >= 0 {
        enemy.spawn_index
    } else {
        enemy.id as i64
    };
    let slot = (spawn_key.rem_euclid(SWARM_SLOTS) * RUN_KEY_STEP).rem_euclid(SWARM_SLOTS) as usize;
    (slot % 3, slot / 3)
}

/// Deterministic order bias in `[0, 1)` used to assign formation arcs cleanly.
pub fn unit_order_bias(enemy: &mut Enemy) -> f32 {
    if let Some(b) = enemy.ai.formation_bias {
        return b;
    }
    let m = (enemy.spawn_index.max(0) * RUN_KEY_STEP).rem_euclid(997);
    let b = (m as f32) / 997.0;
    enemy.ai.formation_bias = Some(b);
    b
}
