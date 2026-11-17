use serde::{Deserialize, Serialize};

use crate::sim::config::{SHIELD_MAX, ULTRA_MAX_CHARGES_HARD_CAP};
use crate::sim::player::Player;
use crate::sim::rng::SimRng;

#[derive(Debug, Clone, Copy)]
pub struct TempRewardDef {
    pub key: &'static str,
    pub title: &'static str,
    pub desc: &'static str,
    pub duration: i32,
}

#[derive(Debug, Clone, Copy)]
pub struct PermRewardDef {
    pub key: &'static str,
    pub title: &'static str,
    pub desc: &'static str,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActiveTempReward {
    pub key: String,
    pub waves_left: i32,
    pub duration: i32,
}

#[derive(Debug, Clone, Copy)]
pub struct TempMods {
    pub damage: f32,
    pub speed: f32,
    pub fire_rate: f32,
    pub magnet: f32,
    pub incoming_damage: f32,
    pub ultra_cd: f32,
    pub crit_chance: f32,
    pub crit_mult: f32,
    pub boost_inf: bool,
}

impl Default for TempMods {
    fn default() -> Self {
        Self {
            damage: 1.0,
            speed: 1.0,
            fire_rate: 1.0,
            magnet: 0.0,
            incoming_damage: 1.0,
            ultra_cd: 1.0,
            crit_chance: 0.0,
            crit_mult: 0.0,
            boost_inf: false,
        }
    }
}

pub const TEMP_REWARD_POOL: &[TempRewardDef] = &[
    TempRewardDef { key: "temp_overdrive", title: "Overdrive", desc: "+28% damage for 2 waves", duration: 2 },
    TempRewardDef { key: "temp_haste", title: "Haste Drive", desc: "+22% move speed for 3 waves", duration: 3 },
    TempRewardDef { key: "temp_rapidfire", title: "Hot Trigger", desc: "22% faster fire-rate for 2 waves", duration: 2 },
    TempRewardDef { key: "temp_magnet", title: "Magnet Core", desc: "Wider pickup magnet for 3 waves", duration: 3 },
    TempRewardDef { key: "temp_guard", title: "Aegis Skin", desc: "-18% incoming damage for 2 waves", duration: 2 },
    TempRewardDef { key: "temp_ultra_flux", title: "Ultra Flux", desc: "+1 Ultra charge now; 30% shorter Ultra cooldown for 3 waves", duration: 3 },
    TempRewardDef { key: "temp_boost_overdrive", title: "Hyper Overdrive", desc: "Infinite Boost + 25% speed for 2 waves", duration: 2 },
    TempRewardDef { key: "temp_crit_lens", title: "Targeting Optics", desc: "+25% Crit Chance & +0.5 Crit Mult for 2 waves", duration: 2 },
];

pub const PERM_REWARD_POOL: &[PermRewardDef] = &[
    PermRewardDef { key: "perm_damage", title: "Core Damage", desc: "+1 damage this run" },
    PermRewardDef { key: "perm_speed", title: "Servo Boost", desc: "+6 move speed this run" },
    PermRewardDef { key: "perm_hp", title: "Hull Plating", desc: "+6 max hull and restore up to 6 hull now" },
    PermRewardDef { key: "perm_fire", title: "Trigger Tuning", desc: "Shorter firing interval this run (down to 0.12s)" },
    PermRewardDef { key: "perm_shield", title: "Shield Layer", desc: "+18 shield now" },
    PermRewardDef { key: "perm_ultra", title: "Ultra Charge", desc: "+1 Ultra charge now and +1 max (up to 4)" },
    PermRewardDef { key: "perm_dash", title: "Quick Dash", desc: "Dash cooldown reduced this run" },
    PermRewardDef { key: "perm_double_dash", title: "Double Dash", desc: "+1 dash charge this run" },
    PermRewardDef { key: "perm_boost_cap", title: "Boost Battery", desc: "+30 Max Boost energy this run" },
    PermRewardDef { key: "perm_crit", title: "Precision Calibration", desc: "+10% Crit Chance & +0.4x Crit Mult this run" },
    PermRewardDef { key: "relic_graviton", title: "Graviton Charm", desc: "Power-ups are pulled from much farther away" },
    PermRewardDef { key: "relic_soul_rivet", title: "Soul Rivet", desc: "Recover 4 hull after every wave clear" },
    PermRewardDef { key: "relic_phase_shard", title: "Phase Shard", desc: "Dash endings pulse nearby enemies for bonus damage" },
    PermRewardDef { key: "relic_aegis_relay", title: "Aegis Relay", desc: "Ultra strikes restore up to 14 shield" },
];

pub const DASH_CD_FLOOR: f32 = 0.6;
pub const FIRE_RATE_FLOOR: f32 = 0.12;

pub fn temp_reward_short_name(key: &str) -> Option<&'static str> {
    match key {
        "temp_overdrive" => Some("Overdrive"),
        "temp_haste" => Some("Haste"),
        "temp_rapidfire" => Some("Rapidfire"),
        "temp_magnet" => Some("Magnet"),
        "temp_guard" => Some("Guard"),
        "temp_ultra_flux" => Some("Ultra Flux"),
        "temp_boost_overdrive" => Some("Hyper Boost"),
        "temp_crit_lens" => Some("Optics"),
        _ => None,
    }
}

pub fn perm_reward_short_name(key: &str) -> Option<&'static str> {
    match key {
        "perm_damage" => Some("Core Damage"),
        "perm_speed" => Some("Servo"),
        "perm_hp" => Some("Hull"),
        "perm_fire" => Some("Trigger"),
        "perm_shield" => Some("Shield"),
        "perm_ultra" => Some("Ultra+"),
        "perm_dash" => Some("Dash+"),
        "perm_double_dash" => Some("Dash^2"),
        "perm_boost_cap" => Some("Boost+"),
        "perm_crit" => Some("Crit+"),
        "relic_graviton" => Some("Graviton"),
        "relic_soul_rivet" => Some("Soul Rivet"),
        "relic_phase_shard" => Some("Phase Shard"),
        "relic_aegis_relay" => Some("Aegis Relay"),
        _ => None,
    }
}

pub fn reward_category(key: &str) -> &'static str {
    match key {
        "temp_overdrive" | "temp_rapidfire" | "temp_crit_lens" | "perm_damage" | "perm_fire" | "perm_crit" => "OFFENSE",
        "temp_haste" | "temp_boost_overdrive" | "perm_speed" | "perm_dash" | "perm_double_dash" | "perm_boost_cap" => "MOBILITY",
        "temp_guard" | "perm_hp" | "perm_shield" => "DEFENSE",
        "temp_magnet" => "UTILITY",
        "temp_ultra_flux" | "perm_ultra" => "ULTRA",
        "relic_graviton" | "relic_soul_rivet" | "relic_phase_shard" | "relic_aegis_relay" => "RELIC",
        _ => "BOON",
    }
}

pub fn category_color(cat: &str) -> [u8; 3] {
    match cat {
        "OFFENSE" => [255, 116, 98],
        "MOBILITY" => [98, 196, 255],
        "DEFENSE" => [122, 228, 152],
        "UTILITY" => [255, 214, 110],
        "ULTRA" => [200, 142, 255],
        "RELIC" => [194, 132, 255],
        _ => [160, 176, 204],
    }
}

pub fn recompute_temp_mods(active: &[ActiveTempReward]) -> TempMods {
    let mut m = TempMods::default();
    for fx in active {
        match fx.key.as_str() {
            "temp_overdrive" => m.damage *= 1.28,
            "temp_haste" => m.speed *= 1.22,
            "temp_rapidfire" => m.fire_rate *= 0.78,
            "temp_magnet" => m.magnet += 80.0,
            "temp_guard" => m.incoming_damage *= 0.82,
            "temp_ultra_flux" => m.ultra_cd *= 0.7,
            "temp_boost_overdrive" => {
                m.speed *= 1.25;
                m.boost_inf = true;
            }
            "temp_crit_lens" => {
                m.crit_chance += 0.25;
                m.crit_mult += 0.50;
            }
            _ => {}
        }
    }
    m
}

pub fn advance_temp_rewards(active: &mut Vec<ActiveTempReward>) {
    active.retain_mut(|fx| {
        fx.waves_left -= 1;
        fx.duration = fx.waves_left;
        fx.waves_left > 0
    });
}

pub fn apply_temp_reward(active: &mut Vec<ActiveTempReward>, key: &str, duration: i32) -> bool {
    let k = key.trim().to_ascii_lowercase();
    let Some(def) = TEMP_REWARD_POOL.iter().find(|reward| reward.key == k) else {
        return false;
    };
    let dur = duration.clamp(1, def.duration).min(def.duration);
    if let Some(existing) = active.iter_mut().find(|fx| fx.key == k) {
        existing.waves_left = existing.waves_left.max(dur);
        existing.duration = existing.waves_left;
        return true;
    }
    active.push(ActiveTempReward {
        key: k,
        waves_left: dur,
        duration: dur,
    });
    true
}

pub fn apply_perm_reward(
    player: &mut Player,
    run_perms: &mut Vec<String>,
    key: &str,
    dash_cd_mult: &mut f32,
) -> bool {
    let k = key.trim().to_ascii_lowercase();
    let applied = match k.as_str() {
        "perm_damage" => {
            player.damage += 1;
            true
        }
        "perm_speed" => {
            player.speed += 6.0;
            true
        }
        "perm_hp" => {
            player.max_hp += 6;
            player.hp = (player.hp + 6).min(player.max_hp);
            true
        }
        "perm_fire" => {
            player.fire_rate = (player.fire_rate - 0.006).max(FIRE_RATE_FLOOR);
            true
        }
        "perm_shield" => {
            player.shield = (player.shield + 18).min(SHIELD_MAX);
            true
        }
        "perm_ultra" => {
            player.ultra_max_charges = (player.ultra_max_charges + 1).min(ULTRA_MAX_CHARGES_HARD_CAP);
            player.ultra_charges = (player.ultra_charges + 1).min(player.ultra_max_charges);
            true
        }
        "perm_dash" => {
            *dash_cd_mult = (*dash_cd_mult * 0.90).max(DASH_CD_FLOOR);
            true
        }
        "perm_double_dash" => {
            player.dash_max_charges = (player.dash_max_charges + 1).min(2);
            player.dash_charges = player.dash_max_charges;
            true
        }
        "perm_boost_cap" => {
            player.boost_max_energy += 30.0;
            player.boost_energy = (player.boost_energy + 30.0).min(player.boost_max_energy);
            true
        }
        "perm_crit" => {
            player.crit_chance_bonus += 0.10;
            player.crit_mult_bonus += 0.40;
            true
        }
        "relic_graviton" | "relic_soul_rivet" | "relic_phase_shard" | "relic_aegis_relay" => {
            !run_perms.iter().any(|owned| owned == &k)
        }
        _ => false,
    };

    let is_relic = reward_category(&k) == "RELIC";
    if applied && (!is_relic || !run_perms.iter().any(|p| p == &k)) {
        run_perms.push(k);
    }
    applied
}

fn perm_is_noop(key: &str, player: &Player, dash_cd_mult: f32, run_perms: &[String]) -> bool {
    match key {
        "perm_dash" => dash_cd_mult <= DASH_CD_FLOOR,
        "perm_shield" => player.shield >= SHIELD_MAX,
        "perm_ultra" => player.ultra_max_charges >= ULTRA_MAX_CHARGES_HARD_CAP,
        "perm_double_dash" => player.dash_max_charges >= 2,
        "perm_fire" => player.fire_rate <= FIRE_RATE_FLOOR,
        "relic_graviton" | "relic_soul_rivet" | "relic_phase_shard" | "relic_aegis_relay" => {
            run_perms.iter().any(|owned| owned == key)
        }
        _ => false,
    }
}

pub fn roll_boss_rewards(
    active_temp: &[ActiveTempReward],
    last_temp_key: &str,
    last_perm_key: &str,
    player: &Player,
    dash_cd_mult: f32,
    run_perms: &[String],
    rng: &mut SimRng,
) -> (Vec<&'static TempRewardDef>, Vec<&'static PermRewardDef>) {
    let mut temp_candidates: Vec<&'static TempRewardDef> = TEMP_REWARD_POOL
        .iter()
        .filter(|x| !active_temp.iter().any(|a| a.key == x.key) && x.key != last_temp_key)
        .collect();
    if temp_candidates.len() < 3 {
        temp_candidates = TEMP_REWARD_POOL
            .iter()
            .filter(|x| !active_temp.iter().any(|a| a.key == x.key))
            .collect();
        if temp_candidates.is_empty() {
            temp_candidates = TEMP_REWARD_POOL.iter().collect();
        }
    }

    let perm_candidates: Vec<&'static PermRewardDef> = PERM_REWARD_POOL
        .iter()
        .filter(|x| {
            x.key != last_perm_key && !perm_is_noop(x.key, player, dash_cd_mult, run_perms)
        })
        .collect();

    let temp_offer = category_balanced_draw(
        temp_candidates,
        3,
        rng,
        |reward| reward_category(reward.key),
        |reward| reward.key,
    );
    let perm_offer = category_balanced_draw(
        perm_candidates,
        3,
        rng,
        |reward| reward_category(reward.key),
        |reward| reward.key,
    );
    (temp_offer, perm_offer)
}

fn category_balanced_draw<T: Copy>(
    mut candidates: Vec<T>,
    count: usize,
    rng: &mut SimRng,
    category_of: impl Fn(T) -> &'static str,
    key_of: impl Fn(T) -> &'static str,
) -> Vec<T> {
    let mut categories: Vec<&'static str> = candidates
        .iter()
        .copied()
        .map(&category_of)
        .collect();
    categories.sort_unstable();
    categories.dedup();
    rng.shuffle(&mut categories);

    let mut selected = Vec::with_capacity(count.min(candidates.len()));
    let mut selected_keys = Vec::with_capacity(count.min(candidates.len()));
    for category in categories.into_iter().take(count) {
        let mut group: Vec<T> = candidates
            .iter()
            .copied()
            .filter(|reward| category_of(*reward) == category)
            .collect();
        rng.shuffle(&mut group);
        if let Some(reward) = group.first().copied() {
            selected.push(reward);
            selected_keys.push(key_of(reward));
        }
    }

    if selected.len() < count {
        rng.shuffle(&mut candidates);
        for reward in candidates {
            if selected_keys.contains(&key_of(reward)) {
                continue;
            }
            selected.push(reward);
            selected_keys.push(key_of(reward));
            if selected.len() == count {
                break;
            }
        }
    }
    selected
}

pub fn format_temp_hud(active: &[ActiveTempReward]) -> String {
    let mut parts = Vec::new();
    for fx in active.iter().take(2) {
        if let Some(name) = temp_reward_short_name(&fx.key) {
            if fx.waves_left > 0 {
                parts.push(format!("{name}:{}", fx.waves_left));
            }
        }
    }
    if parts.is_empty() {
        String::new()
    } else {
        format!("Temp {}", parts.join(", "))
    }
}

pub fn format_perm_hud(run_perms: &[String]) -> String {
    let mut stacks: Vec<(&'static str, usize)> = Vec::new();
    for key in run_perms {
        if reward_category(key) == "RELIC" {
            continue;
        }
        let Some(name) = perm_reward_short_name(key) else {
            continue;
        };
        if let Some((_, count)) = stacks.iter_mut().find(|(existing, _)| *existing == name) {
            *count += 1;
        } else {
            stacks.push((name, 1));
        }
    }
    if stacks.is_empty() {
        String::new()
    } else {
        let shown = stacks
            .into_iter()
            .map(|(name, count)| {
                if count > 1 {
                    format!("{name} x{count}")
                } else {
                    name.to_string()
                }
            })
            .collect::<Vec<_>>();
        format!("Build {}", shown.join(" · "))
    }
}

pub fn has_relic(run_perms: &[String], key: &str) -> bool {
    run_perms.iter().any(|owned| owned == key)
}

pub fn format_relic_hud(run_perms: &[String]) -> String {
    let names: Vec<&str> = [
        ("relic_graviton", "Graviton"),
        ("relic_soul_rivet", "Soul Rivet"),
        ("relic_phase_shard", "Phase Shard"),
        ("relic_aegis_relay", "Aegis Relay"),
    ]
    .iter()
    .filter_map(|(key, name)| has_relic(run_perms, key).then_some(*name))
    .collect();
    if names.is_empty() {
        String::new()
    } else {
        format!("Relics {}", names.join(", "))
    }
}
