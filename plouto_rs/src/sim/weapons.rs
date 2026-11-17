use serde::{Deserialize, Serialize};

use crate::sim::config::{
    FIRE_RATE_CURVE, FIRE_RATE_MIN, FIRE_RATE_RATIO_MAX, FIRE_RATE_RATIO_MIN, PLAYER_FIRE_RATE,
    WEAPON_WAVE_UPGRADE_CHANCE,
};
use crate::sim::rng::SimRng;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WeaponDef {
    pub key: &'static str,
    pub name: &'static str,
    pub damage: i32,
    pub fire_rate: f32,
    pub projectile_count: usize,
    pub spread_angle: f32,
    pub projectile_speed: f32,
    pub projectile_type: &'static str,
    pub recoil_kick: f32,
    pub recoil_recover: f32,
    pub recoil_max: f32,
    pub cadence_jitter: f32,
    pub pierce: i32,
    pub crit_chance: f32,
    pub crit_mult: f32,
    pub rank: i32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Weapon {
    pub key: String,
    pub name: String,
    pub damage: i32,
    pub fire_rate: f32,
    pub projectile_count: usize,
    pub spread_angle: f32,
    pub projectile_speed: f32,
    pub projectile_type: String,
    pub recoil_kick: f32,
    pub recoil_recover: f32,
    pub recoil_max: f32,
    pub cadence_jitter: f32,
    pub pierce: i32,
    pub crit_chance: f32,
    pub crit_mult: f32,
    pub rank: i32,
}

impl From<&WeaponDef> for Weapon {
    fn from(d: &WeaponDef) -> Self {
        Self {
            key: d.key.to_string(),
            name: d.name.to_string(),
            damage: d.damage,
            fire_rate: d.fire_rate,
            projectile_count: d.projectile_count,
            spread_angle: d.spread_angle,
            projectile_speed: d.projectile_speed,
            projectile_type: d.projectile_type.to_string(),
            recoil_kick: d.recoil_kick,
            recoil_recover: d.recoil_recover,
            recoil_max: d.recoil_max,
            cadence_jitter: d.cadence_jitter,
            pierce: d.pierce,
            crit_chance: d.crit_chance,
            crit_mult: d.crit_mult,
            rank: d.rank,
        }
    }
}

pub const WEAPONS: &[WeaponDef] = &[
    WeaponDef {
        key: "basic",
        name: "Basic Gun",
        rank: 1,
        damage: 10,
        fire_rate: 0.28,
        projectile_count: 1,
        spread_angle: 0.0,
        projectile_speed: 360.0,
        projectile_type: "bullet",
        recoil_kick: 0.9,
        recoil_recover: 10.0,
        recoil_max: 4.0,
        cadence_jitter: 0.05,
        pierce: 0,
        crit_chance: 0.10,
        crit_mult: 2.0,
    },
    WeaponDef {
        key: "heavy",
        name: "Heavy Cannon",
        rank: 2,
        damage: 20,
        fire_rate: 0.95,
        projectile_count: 1,
        spread_angle: 0.0,
        projectile_speed: 280.0,
        projectile_type: "missile",
        recoil_kick: 1.8,
        recoil_recover: 6.5,
        recoil_max: 7.0,
        cadence_jitter: 0.03,
        pierce: 0,
        crit_chance: 0.10,
        crit_mult: 2.0,
    },
    WeaponDef {
        key: "rapid",
        name: "Rapid Fire",
        rank: 3,
        damage: 6,
        fire_rate: 0.12,
        projectile_count: 1,
        spread_angle: 5.0,
        projectile_speed: 340.0,
        projectile_type: "bullet",
        recoil_kick: 0.45,
        recoil_recover: 14.0,
        recoil_max: 2.5,
        cadence_jitter: 0.12,
        pierce: 0,
        crit_chance: 0.10,
        crit_mult: 2.0,
    },
    WeaponDef {
        key: "railgun",
        name: "Hyper Railgun",
        rank: 4,
        damage: 40,
        fire_rate: 0.50,
        projectile_count: 1,
        spread_angle: 0.0,
        projectile_speed: 780.0,
        projectile_type: "railgun",
        recoil_kick: 2.4,
        recoil_recover: 6.0,
        recoil_max: 8.0,
        cadence_jitter: 0.02,
        pierce: 3,
        crit_chance: 0.22,
        crit_mult: 2.6,
    },
    WeaponDef {
        key: "spread",
        name: "Spread Shot",
        rank: 5,
        damage: 8,
        fire_rate: 0.35,
        projectile_count: 3,
        spread_angle: 30.0,
        projectile_speed: 320.0,
        projectile_type: "spread",
        recoil_kick: 1.3,
        recoil_recover: 8.0,
        recoil_max: 6.0,
        cadence_jitter: 0.07,
        pierce: 0,
        crit_chance: 0.10,
        crit_mult: 2.0,
    },
    WeaponDef {
        key: "plasma",
        name: "Plasma Rifle",
        rank: 6,
        damage: 9,
        fire_rate: 0.26,
        projectile_count: 3,
        spread_angle: 20.0,
        projectile_speed: 300.0,
        projectile_type: "plasma",
        recoil_kick: 1.1,
        recoil_recover: 9.0,
        recoil_max: 5.0,
        cadence_jitter: 0.08,
        pierce: 0,
        crit_chance: 0.15,
        crit_mult: 2.1,
    },
    WeaponDef {
        key: "flak",
        name: "Flak Battery",
        rank: 7,
        damage: 11,
        fire_rate: 1.10,
        projectile_count: 3,
        spread_angle: 22.0,
        projectile_speed: 340.0,
        projectile_type: "flak",
        recoil_kick: 1.5,
        recoil_recover: 8.5,
        recoil_max: 6.5,
        cadence_jitter: 0.06,
        pierce: 0,
        crit_chance: 0.14,
        crit_mult: 1.85,
    },
    WeaponDef {
        key: "mortar",
        name: "Siege Mortar",
        rank: 8,
        damage: 32,
        fire_rate: 1.45,
        projectile_count: 1,
        spread_angle: 0.0,
        projectile_speed: 260.0,
        projectile_type: "mortar",
        recoil_kick: 2.0,
        recoil_recover: 7.0,
        recoil_max: 8.0,
        cadence_jitter: 0.025,
        pierce: 0,
        crit_chance: 0.12,
        crit_mult: 2.0,
    },
];

pub fn get_weapon(key: &str) -> Weapon {
    try_get_weapon(key).unwrap_or_else(|| (&WEAPONS[0]).into())
}

pub fn try_get_weapon(key: &str) -> Option<Weapon> {
    WEAPONS.iter().find(|weapon| weapon.key == key).map(Into::into)
}

pub fn get_weapon_pool_for_wave(wave: i32) -> &'static [&'static str] {
    if wave <= 2 {
        &["basic"]
    } else if wave <= 4 {
        &["basic", "rapid", "spread"]
    } else if wave <= 6 {
        &["rapid", "spread", "plasma"]
    } else if wave <= 15 {
        &["spread", "plasma", "heavy", "railgun", "flak"]
    } else {
        &["spread", "plasma", "heavy", "railgun", "flak", "mortar"]
    }
}

fn pool_weights_for_wave(wave: i32) -> &'static [f32] {
    if wave <= 2 {
        &[1.0]
    } else if wave <= 4 {
        &[0.5, 0.25, 0.25]
    } else if wave <= 6 {
        &[0.3, 0.25, 0.25]
    } else if wave <= 15 {
        &[0.22, 0.22, 0.18, 0.18, 0.20]
    } else {
        &[0.20, 0.20, 0.16, 0.16, 0.19, 0.09]
    }
}

pub fn get_weapon_key_for_wave(wave: i32, rng: &mut SimRng) -> &'static str {
    let pool = get_weapon_pool_for_wave(wave);
    let weights = pool_weights_for_wave(wave);
    let idx = rng.weighted_index(weights);
    pool[idx]
}

pub fn get_weapon_for_wave(wave: i32, rng: &mut SimRng) -> Weapon {
    get_weapon(get_weapon_key_for_wave(wave, rng))
}

pub fn is_weapon_upgrade(current: Option<&Weapon>, candidate: &Weapon) -> bool {
    match current {
        None => true,
        Some(cur) => candidate.rank > cur.rank,
    }
}

pub fn get_upgrade_key_for_wave(
    wave: i32,
    current: Option<&Weapon>,
    rng: &mut SimRng,
) -> &'static str {
    let pool = get_weapon_pool_for_wave(wave);
    let weights = pool_weights_for_wave(wave);
    let cur_rank = current.map(|w| w.rank).unwrap_or(0);
    let mut above_keys = Vec::new();
    let mut above_weights = Vec::new();
    for (&k, &wt) in pool.iter().zip(weights.iter()) {
        if get_weapon(k).rank > cur_rank {
            above_keys.push(k);
            above_weights.push(wt);
        }
    }
    if above_keys.is_empty() {
        return pool
            .iter()
            .copied()
            .max_by_key(|&k| get_weapon(k).rank)
            .unwrap_or("basic");
    }
    let idx = rng.weighted_index(&above_weights);
    above_keys[idx]
}

pub fn roll_wave_clear_upgrade(
    current: Option<&Weapon>,
    wave: i32,
    rng: &mut SimRng,
    chance: f32,
) -> Option<Weapon> {
    if rng.f32() >= chance {
        return None;
    }
    let candidate = get_weapon_for_wave(wave, rng);
    if is_weapon_upgrade(current, &candidate) {
        Some(candidate)
    } else {
        None
    }
}

pub fn roll_wave_clear_upgrade_default(
    current: Option<&Weapon>,
    wave: i32,
    rng: &mut SimRng,
) -> Option<Weapon> {
    roll_wave_clear_upgrade(current, wave, rng, WEAPON_WAVE_UPGRADE_CHANCE)
}

pub fn get_effective_fire_rate(weapon: &Weapon, player_fire_rate: f32) -> f32 {
    let base = weapon.fire_rate.max(FIRE_RATE_MIN);
    let ratio = (player_fire_rate / PLAYER_FIRE_RATE.max(FIRE_RATE_MIN))
        .clamp(FIRE_RATE_RATIO_MIN, FIRE_RATE_RATIO_MAX);
    let scaled = ratio.powf(FIRE_RATE_CURVE);
    (base * scaled).max(weapon_min_cooldown(weapon))
}

/// Heavy explosives retain a reload window even with stacked fire-rate rewards.
pub fn weapon_min_cooldown(weapon: &Weapon) -> f32 {
    match weapon.projectile_type.as_str() {
        "missile" => 0.70,
        "flak" => 0.85,
        "mortar" => 1.30,
        _ => FIRE_RATE_MIN,
    }
}

pub fn weapon_pickup_seconds(weapon: &Weapon) -> f32 {
    match weapon.projectile_type.as_str() {
        "missile" => 8.0,
        "flak" => 6.0,
        "mortar" => 5.0,
        "railgun" | "plasma" => 12.0,
        _ => crate::sim::config::WEAPON_PICKUP_SECONDS,
    }
}

pub fn get_weapon_color(weapon_type: &str) -> [u8; 3] {
    match weapon_type {
        "bullet" => [255, 245, 190],
        "spread" => [255, 200, 100],
        "missile" => [200, 100, 100],
        "plasma" => [150, 100, 255],
        "railgun" => [120, 245, 255],
        "flak" => [255, 140, 50],
        "mortar" => [255, 112, 52],
        _ => [255, 255, 255],
    }
}

pub fn shot_sfx_for_weapon(weapon_name: &str) -> &'static str {
    match weapon_name {
        "Basic Gun" => "shot_basic",
        "Spread Shot" => "shot_spread",
        "Rapid Fire" => "shot_rapid",
        "Heavy Cannon" => "shot_heavy",
        "Plasma Rifle" => "shot_plasma",
        "Hyper Railgun" => "shot_railgun",
        "Flak Battery" => "shot_flak",
        _ => "shot_basic",
    }
}
