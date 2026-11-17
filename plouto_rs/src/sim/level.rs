use std::collections::BTreeMap;

use crate::sim::config::{
    enemy_radius, ELITE_HP_MULT, ELITE_SHIELDED_HP_FRAC, ELITE_SPAWN_BASE_WAVE, ELITE_SPAWN_CHANCE,
    ELITE_SWIFT_SPEED_MULT,
    ULTRA_GUARANTEE_WAVE_GAP, ULTRA_KILL_BASE_CHANCE, ULTRA_KILL_PITY_THRESHOLD,
    ULTRA_SPAWN_MIN_WAVE, ULTRA_WAVE_SPAWN_BASE, ULTRA_WAVE_SPAWN_MAX, ULTRA_WAVE_SPAWN_PER_WAVE,
};
use crate::sim::drone::DRONE_DROP_SHARE;
use crate::sim::enemy::{boss_title, Enemy};
use crate::sim::math::{clamp_entity_to_map, random_spawn_map_edge, Vec2};
use crate::sim::mutators::RunRules;
use crate::sim::powerup::PowerUp;
use crate::sim::rng::SimRng;
use crate::sim::weapons::{get_upgrade_key_for_wave, get_weapon_key_for_wave, Weapon};

#[derive(Debug, Clone, Copy)]
pub struct DifficultyMods {
    pub spawn: f32,
    pub hp: f32,
    pub speed: f32,
    pub powerup: f32,
    pub boss_hp: f32,
    pub dash_cd: f32,
    pub max_enemies: usize,
}

pub fn difficulty_mods(difficulty: &str) -> DifficultyMods {
    match difficulty.to_ascii_lowercase().as_str() {
        "easy" => DifficultyMods {
            spawn: 0.85,
            hp: 0.88,
            speed: 0.92,
            powerup: 1.15,
            boss_hp: 0.92,
            dash_cd: 0.90,
            max_enemies: 10,
        },
        "hard" => DifficultyMods {
            spawn: 1.12,
            hp: 1.16,
            speed: 1.08,
            powerup: 0.90,
            boss_hp: 1.08,
            dash_cd: 1.12,
            max_enemies: 14,
        },
        _ => DifficultyMods {
            spawn: 1.0,
            hp: 1.0,
            speed: 1.0,
            powerup: 1.0,
            boss_hp: 1.0,
            dash_cd: 1.0,
            max_enemies: 12,
        },
    }
}

#[derive(Debug, Clone, Copy)]
struct EnemyStatProfile {
    hp_offset: f32,
    hp_mult: f32,
    speed_mult: f32,
    attack_mult: f32,
    boss_base_hp: Option<f32>,
    boss_wave_hp_gain: Option<f32>,
}

const DEFAULT_PROFILE: EnemyStatProfile = EnemyStatProfile {
    hp_offset: 0.0,
    hp_mult: 1.0,
    speed_mult: 1.0,
    attack_mult: 1.0,
    boss_base_hp: None,
    boss_wave_hp_gain: None,
};

fn profile_for(behavior: &str) -> EnemyStatProfile {
    match behavior {
        "chaser" => EnemyStatProfile { speed_mult: 1.32, ..DEFAULT_PROFILE },
        "bomber" => EnemyStatProfile { hp_offset: -8.0, speed_mult: 1.2, ..DEFAULT_PROFILE },
        "ranged" => EnemyStatProfile { hp_offset: -5.0, speed_mult: 0.85, attack_mult: 1.2, ..DEFAULT_PROFILE },
        "charger" => EnemyStatProfile { hp_offset: 10.0, speed_mult: 1.05, attack_mult: 0.8, ..DEFAULT_PROFILE },
        "swarm" => EnemyStatProfile { hp_mult: 0.5, speed_mult: 1.45, attack_mult: 0.5, ..DEFAULT_PROFILE },
        "tank" => EnemyStatProfile { hp_mult: 2.0, speed_mult: 0.55, attack_mult: 0.9, ..DEFAULT_PROFILE },
        "spitter" => EnemyStatProfile { hp_offset: -3.0, speed_mult: 0.9, attack_mult: 1.5, ..DEFAULT_PROFILE },
        "flyer" => EnemyStatProfile { hp_offset: -7.0, speed_mult: 1.55, attack_mult: 0.7, ..DEFAULT_PROFILE },
        "engineer" => EnemyStatProfile { hp_offset: 6.0, speed_mult: 0.75, attack_mult: 1.1, ..DEFAULT_PROFILE },
        "sniper" => EnemyStatProfile { hp_offset: -10.0, speed_mult: 0.78, attack_mult: 1.15, ..DEFAULT_PROFILE },
        "egg_sac" => EnemyStatProfile { hp_offset: 3.0, speed_mult: 0.0, ..DEFAULT_PROFILE },
        "boss_thunder" => EnemyStatProfile { speed_mult: 0.9, attack_mult: 1.8, boss_base_hp: Some(150.0), boss_wave_hp_gain: Some(32.0), ..DEFAULT_PROFILE },
        "boss_laser" => EnemyStatProfile { speed_mult: 1.1, attack_mult: 1.8, boss_base_hp: Some(135.0), boss_wave_hp_gain: Some(28.0), ..DEFAULT_PROFILE },
        "boss_trapmaster" => EnemyStatProfile { speed_mult: 0.85, attack_mult: 1.7, boss_base_hp: Some(170.0), boss_wave_hp_gain: Some(30.0), ..DEFAULT_PROFILE },
        "boss_swarmqueen" => EnemyStatProfile { speed_mult: 0.95, attack_mult: 1.7, boss_base_hp: Some(155.0), boss_wave_hp_gain: Some(26.0), ..DEFAULT_PROFILE },
        "boss_brute" => EnemyStatProfile { speed_mult: 1.05, attack_mult: 1.9, boss_base_hp: Some(190.0), boss_wave_hp_gain: Some(34.0), ..DEFAULT_PROFILE },
        "boss_abyss_gaze" => EnemyStatProfile { speed_mult: 1.0, attack_mult: 2.05, boss_base_hp: Some(210.0), boss_wave_hp_gain: Some(32.0), ..DEFAULT_PROFILE },
        "boss_womb_core" => EnemyStatProfile { speed_mult: 0.9, attack_mult: 2.15, boss_base_hp: Some(240.0), boss_wave_hp_gain: Some(36.0), ..DEFAULT_PROFILE },
        "boss_eclipse_archon" => EnemyStatProfile { speed_mult: 1.08, attack_mult: 2.0, boss_base_hp: Some(225.0), boss_wave_hp_gain: Some(34.0), ..DEFAULT_PROFILE },
        _ => DEFAULT_PROFILE,
    }
}

pub fn enemy_stats(behavior: &str, wave: i32, difficulty: &str) -> (i32, f32, f32) {
    let mods = difficulty_mods(difficulty);
    let w = wave.max(1) as f32;
    let prof = profile_for(behavior);
    let base_hp = 22.0 + w * 5.0;
    let base_speed = 55.0 + w * 2.0;
    let is_boss = behavior.starts_with("boss_");

    let mut hp = if let (true, Some(b_hp), Some(w_gain)) = (is_boss, prof.boss_base_hp, prof.boss_wave_hp_gain) {
        b_hp + w * w_gain
    } else if behavior == "swarm" {
        (base_hp * prof.hp_mult + prof.hp_offset).max(8.0)
    } else {
        (base_hp + prof.hp_offset) * prof.hp_mult
    };

    let speed = base_speed * prof.speed_mult * mods.speed;
    let atk_mult = prof.attack_mult.clamp(0.5, 2.5);
    hp *= if is_boss { mods.boss_hp } else { mods.hp };
    if is_boss {
        let growth = (1.14 + 0.007 * w).min(1.75);
        hp *= growth;
        // The first two authored bosses must survive long enough for their three
        // phase routines to read clearly. Later bosses already have healthy
        // encounter times, so leave their wave-scaled durability alone.
        if wave <= 10 {
            hp *= 2.0;
        }
    }
    ((hp as i32).max(1), speed, atk_mult)
}

pub fn spawn_attack_cd_range(behavior: &str) -> (f32, f32) {
    if behavior.starts_with("boss_") {
        (0.6, 1.6)
    } else if behavior == "engineer" {
        (0.6, 1.4)
    } else if behavior == "sniper" {
        (1.0, 1.8)
    } else {
        (0.2, 1.0)
    }
}

/// Constructs a boss-summoned add with wave/difficulty stats, attack scaling, and initial cooldown.
pub fn make_summoned_enemy(
    id: u64,
    pos: Vec2,
    behavior: &str,
    wave: i32,
    difficulty: &str,
    rng: &mut SimRng,
) -> Enemy {
    let (hp, speed, attack_mult) = enemy_stats(behavior, wave, difficulty);
    let mut enemy = Enemy::new(id, pos, hp, speed, behavior);
    enemy.max_hp = hp;
    let (lo, hi) = spawn_attack_cd_range(behavior);
    enemy.attack_cd = rng.range_f32(lo, hi) / attack_mult.clamp(0.6, 1.6);
    enemy.ai.attack_mult = attack_mult;
    enemy
}

pub fn get_boss_for_wave(wave: i32, rng: &mut SimRng) -> &'static str {
    const INTRO: [&str; 5] = [
        "boss_thunder",
        "boss_laser",
        "boss_trapmaster",
        "boss_swarmqueen",
        "boss_brute",
    ];
    const LATE: [&str; 3] = ["boss_abyss_gaze", "boss_womb_core", "boss_eclipse_archon"];

    let idx = (wave / 5 - 1).max(0) as usize;
    if idx < INTRO.len() {
        return INTRO[idx];
    }
    // Give the newest encounter a clean first appearance before it joins the late-game pool.
    if idx == INTRO.len() + 2 {
        return LATE[2];
    }
    if rng.f32() < 0.28 {
        let legacy_pool = &INTRO[2..];
        let pick = rng.index(legacy_pool.len());
        return legacy_pool[pick];
    }
    LATE[(idx - INTRO.len()) % LATE.len()]
}

#[derive(Debug, Clone, Copy)]
struct EnemyClass {
    key: &'static str,
    members: &'static [(&'static str, f32)],
    unlock_wave: i32,
    weight: f32,
}

const ENEMY_CLASSES: &[EnemyClass] = &[
    EnemyClass { key: "frontline", members: &[("chaser", 1.0), ("charger", 0.9)], unlock_wave: 1, weight: 3.0 },
    EnemyClass { key: "gunline", members: &[("ranged", 1.0)], unlock_wave: 2, weight: 2.2 },
    EnemyClass { key: "explosive", members: &[("bomber", 1.0)], unlock_wave: 3, weight: 1.6 },
    EnemyClass { key: "swarmers", members: &[("swarm", 1.0)], unlock_wave: 4, weight: 1.7 },
    EnemyClass { key: "control", members: &[("engineer", 1.0)], unlock_wave: 6, weight: 1.2 },
    EnemyClass { key: "bruisers", members: &[("tank", 1.0)], unlock_wave: 7, weight: 1.0 },
    EnemyClass { key: "pressure", members: &[("spitter", 1.0), ("flyer", 0.8)], unlock_wave: 9, weight: 1.3 },
    EnemyClass { key: "marksmen", members: &[("sniper", 1.0)], unlock_wave: 8, weight: 0.9 },
];

// Authored class combinations give the first twenty waves an intentional cadence.
// Boss waves are resolved before plan_wave, so their slots are deliberately empty.
// The same unlocked classes are recombined after their introductions; later waves
// return to weighted composition once the player knows the complete roster.
const EARLY_WAVE_TEMPLATES: [&[&str]; 20] = [
    &["frontline"],
    &["frontline", "gunline"],
    &["frontline", "explosive"],
    &["frontline", "swarmers"],
    &[], // Wave 5 is a boss encounter.
    &["frontline", "control", "gunline"],
    &["frontline", "bruisers", "gunline"],
    &["frontline", "marksmen", "explosive"],
    &["frontline", "pressure", "swarmers"],
    &[], // Wave 10 is a boss encounter.
    &["frontline", "control", "pressure"],
    &["frontline", "bruisers", "gunline"],
    &["frontline", "marksmen", "swarmers"],
    &["frontline", "control", "explosive"],
    &[], // Wave 15 is a boss encounter.
    &["frontline", "bruisers", "swarmers"],
    &["frontline", "marksmen", "pressure"],
    &["frontline", "control", "explosive"],
    &["frontline", "gunline", "pressure"],
    &[], // Wave 20 is a boss encounter.
];

pub fn threat_value(behavior: &str) -> i32 {
    match behavior {
        "chaser" | "swarm" => 1,
        "ranged" | "charger" | "bomber" => 2,
        "engineer" | "spitter" | "flyer" => 3,
        "tank" | "sniper" => 4,
        "boss_thunder" | "boss_laser" => 20,
        "boss_trapmaster" | "boss_swarmqueen" => 22,
        "boss_brute" => 24,
        "boss_abyss_gaze" => 28,
        "boss_womb_core" => 30,
        "boss_eclipse_archon" => 32,
        _ => 1,
    }
}

pub fn wave_cap(wave: i32, base_cap: usize) -> usize {
    let steps = ((wave - 5).max(0) / 3) as usize;
    base_cap + steps.min(8)
}

#[derive(Debug, Clone)]
pub struct EnemySpawnPlan {
    pub behavior_counts: BTreeMap<String, usize>,
    pub combo_value: i32,
    pub combo_text: String,
    pub intro_hint: Option<&'static str>,
}

fn wave_intro_hint(wave: i32, counts: &BTreeMap<String, usize>) -> Option<&'static str> {
    let has = |behavior: &str| counts.get(behavior).copied().unwrap_or(0) > 0;
    match wave {
        2 if has("ranged") => Some("RANGED FIRE"),
        3 if has("bomber") => Some("BOMBERS"),
        4 if has("swarm") => Some("SWARMERS"),
        6 if has("engineer") => Some("ENGINEER SUPPORT"),
        7 if has("tank") => Some("HEAVY TANKS"),
        8 if has("sniper") => Some("SNIPER FIRE"),
        9 if has("tank") && (has("spitter") || has("flyer")) => Some("TANKS + FLANKERS"),
        9 if has("spitter") || has("flyer") => Some("FLANKERS"),
        _ => None,
    }
}

fn spaced_wave_spawn(
    behavior: &str,
    spawned: &[Enemy],
    player_pos: Vec2,
    room_radius: f32,
    map_type: &str,
    rng: &mut SimRng,
) -> Vec2 {
    let spawn_radius = room_radius * 0.94;
    let new_radius = enemy_radius(behavior);
    let min_player_gap = (room_radius * 0.34)
        .max(new_radius + 36.0)
        .min(room_radius * 0.72);
    let mut best = Vec2::ZERO;
    let mut best_quality = f32::NEG_INFINITY;

    for _ in 0..36 {
        let candidate = random_spawn_map_edge(Vec2::ZERO, spawn_radius, map_type, rng);
        let clearance = spawned
            .iter()
            .map(|enemy| {
                (candidate - enemy.pos).length() - (new_radius + enemy.radius + 10.0)
            })
            .fold(f32::INFINITY, f32::min);
        let player_clearance = (candidate - player_pos).length() - min_player_gap;
        let quality = clearance.min(player_clearance);
        if quality >= 0.0 {
            return candidate;
        }
        if quality > best_quality {
            best = candidate;
            best_quality = quality;
        }
    }

    best
}

pub fn plan_wave(
    wave: i32,
    difficulty: &str,
    cap: usize,
    size_mult: f32,
    rng: &mut SimRng,
) -> EnemySpawnPlan {
    let w = wave.max(1);
    let cap_i = cap.max(1);
    let base = 4 + ((w as f32) * 1.4) as usize;
    let spawn_mult = difficulty_mods(difficulty).spawn;
    let total = (((base as f32) * spawn_mult * size_mult) as usize)
        .max(1)
        .min(cap_i);

    let active: Vec<EnemyClass> = ENEMY_CLASSES
        .iter()
        .copied()
        .filter(|c| w >= c.unlock_wave)
        .collect();

    let uniq_target = match w {
        1 => 1,
        2..=6 => 2,
        _ => 3,
    }
    .min(active.len())
    .min(total);
    let mut pool = active;
    let mut selected: Vec<EnemyClass> = Vec::with_capacity(uniq_target);

    // Teach one new pressure role at a time, then keep a close-range threat, a ranged angle,
    // and a rotating wildcard in later waves. This gives new attacks room to read before they
    // are combined into denser encounters.
    if (1..=20).contains(&w) {
        for key in EARLY_WAVE_TEMPLATES[(w - 1) as usize].iter().take(uniq_target) {
            if let Some(index) = pool.iter().position(|class| class.key == *key) {
                selected.push(pool.remove(index));
            }
        }
        // Keep the director stable if a future roster edit removes or relocks
        // one of the authored entries. The fallback order is fixed and only
        // draws from classes that are already unlocked for this wave.
        for key in ["frontline", "gunline", "swarmers", "explosive", "control", "bruisers", "pressure", "marksmen"] {
            if selected.len() >= uniq_target {
                break;
            }
            if let Some(index) = pool.iter().position(|class| class.key == key) {
                selected.push(pool.remove(index));
            }
        }
    } else {
        if let Some(frontline) = pool.iter().position(|class| class.key == "frontline") {
            selected.push(pool.remove(frontline));
        }
        if w >= 7 && selected.len() < uniq_target {
            let pressure_choices: Vec<usize> = pool
                .iter()
                .enumerate()
                .filter(|(_, class)| class.key == "gunline" || class.key == "pressure")
                .map(|(i, _)| i)
                .collect();
            if !pressure_choices.is_empty() {
                let index = pressure_choices[rng.index(pressure_choices.len())];
                selected.push(pool.remove(index));
            }
        }
        let scheduled_class = match w {
            2 => "gunline",
            3 => "explosive",
            4 => "swarmers",
            6 => "control",
            7 => "bruisers",
            8 => "marksmen",
            9 => "pressure",
            _ => "",
        };
        if !scheduled_class.is_empty() && selected.len() < uniq_target {
            if let Some(index) = pool.iter().position(|class| class.key == scheduled_class) {
                selected.push(pool.remove(index));
            }
        }
        while !pool.is_empty() && selected.len() < uniq_target {
            let weights: Vec<f32> = pool.iter().map(|c| c.weight.max(0.1)).collect();
            let idx = rng.weighted_index(&weights);
            selected.push(pool.remove(idx));
        }
    }

    let mut counts_by_idx = vec![1usize; selected.len()];
    let remaining = total.saturating_sub(selected.len());
    let max_per_class = ((total as f32) * 0.6).round().max(1.0) as usize;

    for _ in 0..remaining {
        let selectable: Vec<usize> = (0..selected.len())
            .filter(|&i| counts_by_idx[i] < max_per_class)
            .collect();
        let choices = if selectable.is_empty() {
            (0..selected.len()).collect::<Vec<_>>()
        } else {
            selectable
        };
        let weights: Vec<f32> = choices.iter().map(|&i| selected[i].weight.max(0.1)).collect();
        let picked = choices[rng.weighted_index(&weights)];
        counts_by_idx[picked] += 1;
    }

    let mut behavior_counts: BTreeMap<String, usize> = BTreeMap::new();
    for (cls, count) in selected.iter().zip(counts_by_idx) {
        let weights: Vec<f32> = cls.members.iter().map(|m| m.1.max(0.05)).collect();
        for _ in 0..count {
            let m_idx = rng.weighted_index(&weights);
            let name = cls.members[m_idx].0.to_string();
            *behavior_counts.entry(name).or_insert(0) += 1;
        }
    }

    let combo_value: i32 = behavior_counts
        .iter()
        .map(|(b, &n)| threat_value(b) * (n as i32))
        .sum();
    let mut sorted: Vec<(&String, &usize)> = behavior_counts.iter().collect();
    sorted.sort_by(|a, b| b.1.cmp(a.1).then_with(|| a.0.cmp(b.0)));
    let parts: Vec<String> = sorted
        .into_iter()
        .take(4)
        .map(|(b, &n)| {
            let name = match b.as_str() {
                "chaser" => "CHASER",
                "charger" => "CHARGER",
                "ranged" => "RANGED",
                "bomber" => "BOMBER",
                "engineer" => "ENGINEER",
                "spitter" => "SPITTER",
                "flyer" => "FLYER",
                "tank" => "TANK",
                "swarm" => "SWARM",
                "egg_sac" => "EGG SAC",
                "sniper" => "SNIPER",
                _ => "ENEMY",
            };
            format!("{}x{}", name, n)
        })
        .collect();
    let combo_lines = parts
        .chunks(2)
        .map(|row| row.join("  ·  "))
        .collect::<Vec<_>>()
        .join("\n");

    EnemySpawnPlan {
        intro_hint: wave_intro_hint(w, &behavior_counts),
        behavior_counts,
        combo_value,
        combo_text: combo_lines,
    }
}

pub fn choose_elite_affix(rng: &mut SimRng) -> &'static str {
    const AFFIXES: &[(&str, f32)] = &[
        ("volatile", 3.0),
        ("swift", 3.0),
        ("shielded", 3.0),
        ("splitter", 2.0),
        ("reflector", 2.0),
        ("mender", 2.0),
        ("warden", 2.0),
    ];
    let weights: Vec<f32> = AFFIXES.iter().map(|a| a.1).collect();
    AFFIXES[rng.weighted_index(&weights)].0
}

#[derive(Debug, Clone)]
pub struct UltraPityTracker {
    pub last_ultra_wave: i32,
    pub kills_since_ultra: i32,
}

impl Default for UltraPityTracker {
    fn default() -> Self {
        Self {
            last_ultra_wave: 0,
            kills_since_ultra: 0,
        }
    }
}

pub const POWERUP_POOL_WEIGHTS: &[(&str, f32)] = &[
    ("heal", 1.0),
    ("damage", 1.0),
    ("speed", 1.0),
    ("firerate", 1.0),
    ("shield", 1.0),
    ("repulsor", 0.7),
    ("laser", 1.0),
    ("boost", 1.0),
    ("ricochet", 0.5),
    ("homing", 0.3),
    ("time_slow", 0.2),
    ("magnet", 0.5),
    ("chain", 0.3),
];

fn pick_powerup_kind_for_wave(
    wave: i32,
    source: &str,
    pity: &mut UltraPityTracker,
    rng: &mut SimRng,
) -> String {
    let weights: Vec<f32> = POWERUP_POOL_WEIGHTS.iter().map(|w| w.1).collect();
    let idx = rng.weighted_index(&weights);
    let mut kind = POWERUP_POOL_WEIGHTS[idx].0.to_string();

    let r = rng.f32();
    if r < 0.07 {
        kind = "boost".to_string();
    } else if r < 0.13 {
        kind = "vortex".to_string();
    } else if wave >= 3 && r < 0.20 {
        kind = "weapon".to_string();
    } else if wave >= 3 && r < 0.20 + DRONE_DROP_SHARE {
        kind = "drone".to_string();
    }

    if wave < ULTRA_SPAWN_MIN_WAVE {
        return kind;
    }

    let gap = ULTRA_GUARANTEE_WAVE_GAP.max(1);
    if source == "wave" && (wave - pity.last_ultra_wave) >= gap {
        pity.last_ultra_wave = wave;
        pity.kills_since_ultra = 0;
        return "ultra".to_string();
    }
    if source == "kill" && pity.kills_since_ultra >= ULTRA_KILL_PITY_THRESHOLD.max(8) {
        pity.last_ultra_wave = wave;
        pity.kills_since_ultra = 0;
        return "ultra".to_string();
    }

    let ultra_chance = if source == "wave" {
        (ULTRA_WAVE_SPAWN_BASE + ((wave - ULTRA_SPAWN_MIN_WAVE).max(0) as f32) * ULTRA_WAVE_SPAWN_PER_WAVE)
            .min(ULTRA_WAVE_SPAWN_MAX)
    } else {
        ULTRA_KILL_BASE_CHANCE
    };
    if rng.f32() < ultra_chance {
        pity.last_ultra_wave = wave;
        pity.kills_since_ultra = 0;
        return "ultra".to_string();
    }
    kind
}

fn make_powerup(pos: Vec2, kind: &str, wave: i32, rng: &mut SimRng) -> PowerUp {
    if kind == "weapon" {
        let wkey = get_weapon_key_for_wave(wave, rng);
        PowerUp::new(pos, "weapon", Some(wkey.to_string()))
    } else {
        PowerUp::new(pos, kind, None)
    }
}

pub fn maybe_spawn_wave_powerup(
    wave: i32,
    difficulty: &str,
    room_radius: f32,
    map_type: &str,
    rules: &RunRules,
    pity: &mut UltraPityTracker,
    rng: &mut SimRng,
    powerups: &mut Vec<PowerUp>,
) {
    if !rules.pickups_enabled {
        return;
    }
    let gap = ULTRA_GUARANTEE_WAVE_GAP.max(1);
    let force_ultra = wave >= ULTRA_SPAWN_MIN_WAVE && (wave - pity.last_ultra_wave) >= gap;
    let chance = 0.33 * difficulty_mods(difficulty).powerup;
    if force_ultra || rng.f32() < chance {
        let kind = if force_ultra {
            "ultra".to_string()
        } else {
            pick_powerup_kind_for_wave(wave, "wave", pity, rng)
        };
        let frac = rng.range_f32(0.38, 0.88);
        let pos = clamp_entity_to_map(
            random_spawn_map_edge(Vec2::ZERO, room_radius * frac, map_type, rng),
            room_radius,
            18.0,
            map_type,
        );
        powerups.push(make_powerup(pos, &kind, wave, rng));
        if kind == "ultra" {
            pity.last_ultra_wave = wave;
            pity.kills_since_ultra = 0;
        }
    }
}

pub fn spawn_loot_on_enemy_death(
    behavior: &str,
    pos: Vec2,
    wave: i32,
    difficulty: &str,
    rules: &RunRules,
    current_weapon: Option<&Weapon>,
    pity: &mut UltraPityTracker,
    rng: &mut SimRng,
    powerups: &mut Vec<PowerUp>,
) {
    if !rules.pickups_enabled {
        return;
    }
    if behavior.starts_with("boss_") {
        let boss_weapon_key = get_upgrade_key_for_wave(wave + 1, current_weapon, rng);
        let wpos = pos + Vec2::new(rng.range_f32(-20.0, 20.0), rng.range_f32(-20.0, 20.0));
        powerups.push(PowerUp::new(wpos, "weapon", Some(boss_weapon_key.to_string())));

        let sustain = ["heal", "shield", "laser"][rng.index(3)];
        let spos = pos + Vec2::new(rng.range_f32(-35.0, 35.0), rng.range_f32(-35.0, 35.0));
        powerups.push(PowerUp::new(spos, sustain, None));

        if wave >= ULTRA_SPAWN_MIN_WAVE && (wave - pity.last_ultra_wave) >= ULTRA_GUARANTEE_WAVE_GAP.max(2) {
            let upos = pos + Vec2::new(rng.range_f32(-30.0, 30.0), rng.range_f32(-30.0, 30.0));
            powerups.push(PowerUp::new(upos, "ultra", None));
            pity.last_ultra_wave = wave;
            pity.kills_since_ultra = 0;
        }

        if rng.f32() < 0.35 {
            let mut kind2 = ["damage", "speed", "firerate"][rng.index(3)];
            let r = rng.f32();
            if r < 0.08 {
                kind2 = "vortex";
            } else if wave >= 5 && r < 0.30 {
                kind2 = "ultra";
            }
            let bpos = pos + Vec2::new(rng.range_f32(-45.0, 45.0), rng.range_f32(-45.0, 45.0));
            powerups.push(PowerUp::new(bpos, kind2, None));
        }
        return;
    }

    pity.kills_since_ultra += 1;
    let force_ultra =
        wave >= ULTRA_SPAWN_MIN_WAVE && pity.kills_since_ultra >= ULTRA_KILL_PITY_THRESHOLD.max(8);
    let chance = 0.15 * difficulty_mods(difficulty).powerup;
    if force_ultra || rng.f32() < chance {
        let kind = if force_ultra {
            "ultra".to_string()
        } else {
            pick_powerup_kind_for_wave(wave, "kill", pity, rng)
        };
        let ppos = pos + Vec2::new(rng.range_f32(-50.0, 50.0), rng.range_f32(-50.0, 50.0));
        powerups.push(make_powerup(ppos, &kind, wave, rng));
        if kind == "ultra" {
            pity.last_ultra_wave = wave;
            pity.kills_since_ultra = 0;
        }
    }
}

pub struct WaveSpawnResult {
    pub enemies: Vec<Enemy>,
    pub combo_value: i32,
    pub combo_text: String,
    pub intro_hint: Option<&'static str>,
}

#[allow(clippy::too_many_arguments)]
pub fn spawn_wave_enemies(
    wave: i32,
    difficulty: &str,
    map_type: &str,
    room_radius: f32,
    max_enemies: usize,
    rules: &RunRules,
    player_pos: Vec2,
    next_id: &mut u64,
    rng: &mut SimRng,
) -> WaveSpawnResult {
    let mut enemies = Vec::new();
    if wave % crate::sim::config::BOSS_WAVE_EVERY == 0 {
        let behavior_name = get_boss_for_wave(wave, rng);
        let (hp, mut speed, attack_mult) = enemy_stats(behavior_name, wave, difficulty);
        speed *= rules.enemy_speed_mult;
        let pos = spaced_wave_spawn(
            behavior_name,
            &enemies,
            player_pos,
            room_radius,
            map_type,
            rng,
        );
        let id = *next_id;
        *next_id += 1;
        let mut e = Enemy::new(id, pos, hp, speed, behavior_name);
        let (lo, hi) = spawn_attack_cd_range(behavior_name);
        e.attack_cd = rng.range_f32(lo, hi) / attack_mult.clamp(0.6, 1.6);
        e.ai.attack_mult = attack_mult;
        enemies.push(e);
        return WaveSpawnResult {
            enemies,
            combo_value: threat_value(behavior_name),
            combo_text: format!("BOSS {}", boss_title(behavior_name)),
            intro_hint: None,
        };
    }

    let w_cap = wave_cap(wave, max_enemies);
    let plan = plan_wave(wave, difficulty, w_cap, rules.spawn_size_mult, rng);

    for (behavior_name, count) in &plan.behavior_counts {
        for _ in 0..*count {
            let (mut hp, mut speed, attack_mult) = enemy_stats(behavior_name, wave, difficulty);
            speed *= rules.enemy_speed_mult;
            let pos = spaced_wave_spawn(
                behavior_name,
                &enemies,
                player_pos,
                room_radius,
                map_type,
                rng,
            );

            let mut is_elite = false;
            let mut affix = "";
            let mut shield_val = 0;
            if wave >= ELITE_SPAWN_BASE_WAVE {
                let chance = (ELITE_SPAWN_CHANCE + ((wave - ELITE_SPAWN_BASE_WAVE) as f32) * 0.015)
                    .min(0.35);
                if rng.f32() < chance {
                    is_elite = true;
                    affix = choose_elite_affix(rng);
                    hp = ((hp as f32) * ELITE_HP_MULT).round() as i32;
                    if affix == "swift" {
                        speed *= ELITE_SWIFT_SPEED_MULT;
                    } else if affix == "shielded" {
                        shield_val = ((hp as f32) * ELITE_SHIELDED_HP_FRAC).round() as i32;
                    }
                }
            }

            let id = *next_id;
            *next_id += 1;
            let mut e = Enemy::new(id, pos, hp, speed, behavior_name);
            e.max_hp = hp;
            e.is_elite = is_elite;
            e.elite_affix = affix.to_string();
            e.shield = shield_val;
            if affix == "mender" {
                e.ai.mender_cd = 1.2 + ((id.wrapping_mul(37) % 120) as f32 / 100.0);
            }
            let (lo, hi) = spawn_attack_cd_range(behavior_name);
            e.attack_cd = rng.range_f32(lo, hi) / attack_mult.clamp(0.6, 1.6);
            e.ai.attack_mult = attack_mult;
            enemies.push(e);
        }
    }

    WaveSpawnResult {
        enemies,
        combo_value: plan.combo_value,
        combo_text: plan.combo_text,
        intro_hint: plan.intro_hint,
    }
}
