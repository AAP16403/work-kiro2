use crate::sim::config::{
    BOOST_OVERDRIVE_SECONDS, CHAIN_DURATION, HOMING_DURATION, MAGNET_DURATION, MAGNET_PULL_MULT,
    MAGNET_RADIUS_MULT, RICOCHET_DURATION, SHIELD_MAX, TIME_SLOW_DURATION, TIME_SLOW_SCALE,
    LASER_PICKUP_SECONDS, VORTEX_PICKUP_SECONDS,
};
use crate::sim::drone::DRONE_DURATION;
use crate::sim::math::{round_countdown, Vec2};
use crate::sim::player::Player;
use crate::sim::rng::SimRng;
use crate::sim::specials::{ChainSystem, RepulsorSystem};
use crate::sim::weapons::{
    get_weapon_for_wave, is_weapon_upgrade, try_get_weapon, weapon_min_cooldown,
    weapon_pickup_seconds, Weapon,
};

#[derive(Debug, Clone)]
pub struct PowerUp {
    pub pos: Vec2,
    pub kind: String,
    pub ttl: f32,
    pub weapon_key: Option<String>,
}

impl PowerUp {
    pub fn new(pos: Vec2, kind: &str, weapon_key: Option<String>) -> Self {
        Self {
            pos,
            kind: kind.to_string(),
            ttl: 18.0,
            weapon_key,
        }
    }
}

pub fn tick_powerups(powerups: &mut Vec<PowerUp>, dt: f32) {
    let dt = dt.max(0.0);
    powerups.retain_mut(|powerup| {
        powerup.ttl -= dt;
        powerup.ttl > 0.0
    });
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PickupSound {
    Normal,
    Rare,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum PickupDuration {
    None,
    Fixed(f32),
    WeaponClass,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PickupStackPolicy {
    ImmediateOrConvert,
    RefreshDuration,
    ReplaceTemporary,
    AddCharge,
}

#[derive(Debug, Clone, Copy)]
pub struct PowerupDefinition {
    pub key: &'static str,
    pub rare: bool,
    pub duration: PickupDuration,
    pub stack_policy: PickupStackPolicy,
}

/// Gameplay-facing power-up rules. The UI uses this table for rarity and all
/// timed-effect denominators so displayed timers cannot silently drift.
/// Keep `rare` aligned with the preserved Python-era rare pickup set; art tier
/// is a separate classification used by the guide's emblem frame.
pub const POWERUP_DEFINITIONS: &[PowerupDefinition] = &[
    PowerupDefinition { key: "heal", rare: false, duration: PickupDuration::None, stack_policy: PickupStackPolicy::ImmediateOrConvert },
    PowerupDefinition { key: "shield", rare: false, duration: PickupDuration::None, stack_policy: PickupStackPolicy::ImmediateOrConvert },
    PowerupDefinition { key: "damage", rare: false, duration: PickupDuration::None, stack_policy: PickupStackPolicy::ImmediateOrConvert },
    PowerupDefinition { key: "speed", rare: false, duration: PickupDuration::None, stack_policy: PickupStackPolicy::ImmediateOrConvert },
    PowerupDefinition { key: "firerate", rare: false, duration: PickupDuration::None, stack_policy: PickupStackPolicy::ImmediateOrConvert },
    PowerupDefinition { key: "boost", rare: false, duration: PickupDuration::Fixed(BOOST_OVERDRIVE_SECONDS), stack_policy: PickupStackPolicy::RefreshDuration },
    PowerupDefinition { key: "weapon", rare: true, duration: PickupDuration::WeaponClass, stack_policy: PickupStackPolicy::ReplaceTemporary },
    PowerupDefinition { key: "drone", rare: true, duration: PickupDuration::Fixed(DRONE_DURATION), stack_policy: PickupStackPolicy::RefreshDuration },
    PowerupDefinition { key: "magnet", rare: false, duration: PickupDuration::Fixed(MAGNET_DURATION), stack_policy: PickupStackPolicy::RefreshDuration },
    PowerupDefinition { key: "ricochet", rare: false, duration: PickupDuration::Fixed(RICOCHET_DURATION), stack_policy: PickupStackPolicy::RefreshDuration },
    PowerupDefinition { key: "homing", rare: true, duration: PickupDuration::Fixed(HOMING_DURATION), stack_policy: PickupStackPolicy::RefreshDuration },
    PowerupDefinition { key: "chain", rare: true, duration: PickupDuration::Fixed(CHAIN_DURATION), stack_policy: PickupStackPolicy::RefreshDuration },
    PowerupDefinition { key: "repulsor", rare: false, duration: PickupDuration::None, stack_policy: PickupStackPolicy::AddCharge },
    PowerupDefinition { key: "laser", rare: true, duration: PickupDuration::Fixed(LASER_PICKUP_SECONDS), stack_policy: PickupStackPolicy::RefreshDuration },
    PowerupDefinition { key: "vortex", rare: true, duration: PickupDuration::Fixed(VORTEX_PICKUP_SECONDS), stack_policy: PickupStackPolicy::RefreshDuration },
    PowerupDefinition { key: "time_slow", rare: true, duration: PickupDuration::Fixed(TIME_SLOW_DURATION), stack_policy: PickupStackPolicy::RefreshDuration },
    PowerupDefinition { key: "ultra", rare: true, duration: PickupDuration::None, stack_policy: PickupStackPolicy::AddCharge },
];

pub fn powerup_definition(kind: &str) -> Option<&'static PowerupDefinition> {
    POWERUP_DEFINITIONS.iter().find(|definition| definition.key == kind)
}

pub fn powerup_duration_seconds(kind: &str, weapon: Option<&Weapon>) -> Option<f32> {
    match powerup_definition(kind)?.duration {
        PickupDuration::None => None,
        PickupDuration::Fixed(seconds) => Some(seconds),
        PickupDuration::WeaponClass => weapon.map(weapon_pickup_seconds),
    }
}

#[derive(Debug, Clone, Copy)]
pub struct TimedPowerupState {
    pub kind: &'static str,
    pub until: f32,
    pub duration: f32,
}

pub fn timed_powerup_states(player: &Player) -> Vec<TimedPowerupState> {
    let mut states = Vec::with_capacity(9);
    for (kind, until) in [
        ("laser", player.laser_until),
        ("vortex", player.vortex_until),
        ("drone", player.drone_until),
        ("ricochet", player.ricochet_until),
        ("homing", player.homing_until),
        ("time_slow", player.time_slow_until),
        ("magnet", player.magnet_until),
        ("boost", player.infinite_boost_until),
    ] {
        if let Some(duration) = powerup_duration_seconds(kind, None) {
            states.push(TimedPowerupState { kind, until, duration });
        }
    }
    if player.weapon_base.is_some() {
        if let Some(duration) = powerup_duration_seconds("weapon", Some(&player.current_weapon)) {
            states.push(TimedPowerupState { kind: "weapon", until: player.weapon_until, duration });
        }
    }
    states
}

#[derive(Debug, Clone)]
pub struct PickupOutcome {
    pub sound: PickupSound,
    pub extra_cue: Option<&'static str>,
    pub repulsor_fired: bool,
    pub popup_text: Option<String>,
}

pub fn is_rare_powerup(kind: &str) -> bool {
    powerup_definition(kind).is_some_and(|definition| definition.rare)
}

pub fn timed_active(until: f32, now: f32) -> bool {
    until > now
}

pub fn enemy_time_scale(player: &Player, now: f32) -> f32 {
    if timed_active(player.time_slow_until, now) {
        TIME_SLOW_SCALE
    } else {
        1.0
    }
}

pub fn pickup_magnet_mods(player: &Player, now: f32) -> (f32, f32) {
    if timed_active(player.magnet_until, now) {
        (MAGNET_RADIUS_MULT, MAGNET_PULL_MULT)
    } else {
        (1.0, 1.0)
    }
}

pub fn expire_timed_effects(player: &mut Player, now: f32) -> Vec<&'static str> {
    let mut expired = Vec::new();
    let pairs: &[(fn(&mut Player) -> &mut f32, &'static str)] = &[
        (|p| &mut p.ricochet_until, "ricochet"),
        (|p| &mut p.homing_until, "homing"),
        (|p| &mut p.time_slow_until, "time_slow"),
        (|p| &mut p.magnet_until, "magnet"),
    ];
    for &(field, name) in pairs {
        let u = field(player);
        if *u > 0.0 && now >= *u {
            *u = 0.0;
            expired.push(name);
        }
    }
    expired
}

pub fn equip_permanent_weapon(player: &mut Player, weapon: Weapon) {
    if player.weapon_base.is_some() {
        player.weapon_base = Some(weapon);
    } else {
        player.current_weapon = weapon;
    }
}

pub fn expire_weapon_pickup(player: &mut Player, now: f32) -> bool {
    if player.weapon_until <= 0.0 || now < player.weapon_until {
        return false;
    }
    if let Some(base) = player.weapon_base.take() {
        preserve_weapon_reload(player, &base);
        player.current_weapon = base;
    }
    player.weapon_until = 0.0;
    true
}

/// Keep already-earned cadence debt and ensure switching to a slower weapon
/// cannot grant an early shot from the faster weapon's shorter interval.
fn preserve_weapon_reload(player: &mut Player, weapon: &Weapon) {
    if player.next_shot_time > player.last_shot {
        player.next_shot_time = player
            .next_shot_time
            .max(player.last_shot + weapon_min_cooldown(weapon));
    }
}

pub fn powerup_popup_name(kind: &str, weapon_name: Option<&str>) -> String {
    match kind {
        "heal" => "HEAL".to_string(),
        "damage" => "DAMAGE UP".to_string(),
        "speed" => "SPEED UP".to_string(),
        "firerate" => "FIRE RATE UP".to_string(),
        "shield" => "SHIELD".to_string(),
        "laser" => "LASER".to_string(),
        "vortex" => "VORTEX".to_string(),
        "ultra" => "ULTRA +1".to_string(),
        "boost" => "OVERDRIVE".to_string(),
        "drone" => "DRONE".to_string(),
        "ricochet" => "RICOCHET".to_string(),
        "homing" => "HOMING".to_string(),
        "time_slow" => "TIME SLOW".to_string(),
        "magnet" => "MAGNET".to_string(),
        "chain" => "CHAIN".to_string(),
        "repulsor" => "REPULSOR".to_string(),
        "weapon" => weapon_name
            .map(|n| n.to_ascii_uppercase())
            .unwrap_or_else(|| "WEAPON".to_string()),
        other => other.to_ascii_uppercase(),
    }
}

pub fn apply_powerup(
    player: &mut Player,
    pu: &PowerUp,
    time: f32,
    wave: i32,
    chain: &mut ChainSystem,
    repulsor: &mut RepulsorSystem,
    rng: &mut SimRng,
) -> PickupOutcome {
    let mut sound = if is_rare_powerup(&pu.kind) {
        PickupSound::Rare
    } else {
        PickupSound::Normal
    };
    let mut extra_cue = None;
    let mut repulsor_fired = false;
    let mut weapon_label: Option<String> = None;
    let mut popup_override: Option<String> = None;

    match pu.kind.as_str() {
        "heal" => {
            let hp = (player.hp + 25).min(player.max_hp);
            if hp > player.hp {
                player.hp = hp;
            } else if player.shield < SHIELD_MAX {
                player.shield = (player.shield + 15).min(SHIELD_MAX);
                popup_override = Some("SHIELD UP".to_string());
            } else {
                player.damage += 1;
                popup_override = Some("DAMAGE UP".to_string());
            }
        }
        "damage" => {
            player.damage += 3;
        }
        "speed" => {
            player.speed += 15.0;
        }
        "firerate" => {
            let next_rate = (player.fire_rate - 0.04).max(0.16).min(player.fire_rate);
            if next_rate < player.fire_rate {
                player.fire_rate = next_rate;
            } else {
                player.damage += 1;
                popup_override = Some("DAMAGE UP".to_string());
            }
        }
        "shield" => {
            if player.shield < SHIELD_MAX {
                player.shield = (player.shield + 35).min(SHIELD_MAX);
            } else if player.hp < player.max_hp {
                player.hp = (player.hp + 10).min(player.max_hp);
                popup_override = Some("HULL RESTORED".to_string());
            } else {
                player.damage += 1;
                popup_override = Some("DAMAGE UP".to_string());
            }
        }
        "laser" => {
            player.laser_until = time + powerup_duration_seconds("laser", None).unwrap_or(0.0);
        }
        "vortex" => {
            player.vortex_until = time + powerup_duration_seconds("vortex", None).unwrap_or(0.0);
        }
        "drone" => {
            player.drone_until = time + powerup_duration_seconds("drone", None).unwrap_or(0.0);
        }
        "ultra" => {
            if player.ultra_charges < player.ultra_max_charges {
                player.ultra_charges += 1;
            } else if player.shield < SHIELD_MAX {
                player.shield = (player.shield + 25).min(SHIELD_MAX);
                popup_override = Some("OVERCHARGE SHIELD".to_string());
            } else {
                player.damage += 1;
                popup_override = Some("DAMAGE UP".to_string());
            }
        }
        "boost" => {
            player.boost_energy = player.boost_max_energy;
            player.infinite_boost_until = time + powerup_duration_seconds("boost", None).unwrap_or(0.0);
            player.shield = (player.shield + 20).min(SHIELD_MAX);
        }
        "ricochet" => {
            player.ricochet_until = time + powerup_duration_seconds("ricochet", None).unwrap_or(0.0);
        }
        "homing" => {
            player.homing_until = time + powerup_duration_seconds("homing", None).unwrap_or(0.0);
        }
        "time_slow" => {
            player.time_slow_until = time + powerup_duration_seconds("time_slow", None).unwrap_or(0.0);
            extra_cue = Some("time_slow_on");
        }
        "magnet" => {
            player.magnet_until = time + powerup_duration_seconds("magnet", None).unwrap_or(0.0);
            extra_cue = Some("magnet");
        }
        "chain" => {
            chain.activate(time, powerup_duration_seconds("chain", None).unwrap_or(0.0));
        }
        "repulsor" => {
            repulsor_fired = repulsor.on_pickup(time);
        }
        "weapon" => {
            let candidate = pu
                .weapon_key
                .as_deref()
                .and_then(try_get_weapon)
                .unwrap_or_else(|| get_weapon_for_wave(wave, rng));
            if !is_weapon_upgrade(Some(&player.current_weapon), &candidate) {
                sound = PickupSound::Normal;
                if player.shield < SHIELD_MAX {
                    player.shield = (player.shield + 20).min(SHIELD_MAX);
                    popup_override = Some("SHIELD UP".to_string());
                } else if player.hp < player.max_hp {
                    player.hp = (player.hp + 10).min(player.max_hp);
                    popup_override = Some("HULL RESTORED".to_string());
                } else {
                    player.damage += 1;
                    popup_override = Some("DAMAGE UP".to_string());
                }
            } else {
                if player.weapon_base.is_none() {
                    player.weapon_base = Some(player.current_weapon.clone());
                }
                preserve_weapon_reload(player, &candidate);
                weapon_label = Some(candidate.name.clone());
                player.current_weapon = candidate;
                player.weapon_until = time
                    + powerup_duration_seconds("weapon", Some(&player.current_weapon)).unwrap_or(0.0);
            }
        }
        _ => {}
    }

    PickupOutcome {
        sound,
        extra_cue,
        repulsor_fired,
        popup_text: Some(
            popup_override
                .unwrap_or_else(|| powerup_popup_name(&pu.kind, weapon_label.as_deref())),
        ),
    }
}

pub fn format_timed_powerups_hud(
    player: &Player,
    now: f32,
    chain: &ChainSystem,
    repulsor: &RepulsorSystem,
) -> String {
    let mut parts = Vec::new();
    if player.weapon_until > now && player.weapon_base.is_some() {
        let left = round_countdown(player.weapon_until - now).ceil().max(1.0) as i32;
        parts.push(format!("{} {left}s", player.current_weapon.name));
    }
    for status in timed_powerup_states(player) {
        if status.kind == "weapon" {
            continue;
        }
        if timed_active(status.until, now) {
            let left = round_countdown(status.until - now).ceil().max(1.0) as i32;
            parts.push(format!("{} {left}s", status.kind));
        }
    }
    if chain.is_active(now) {
        let left = round_countdown(chain.until - now).ceil().max(1.0) as i32;
        parts.push(format!("Chain {left}s"));
    }
    let rep_hud = repulsor.format_hud(now);
    if !rep_hud.is_empty() {
        parts.push(rep_hud);
    }
    parts.join(" | ")
}

pub fn powerup_timing_description(kind: &str) -> Option<String> {
    if kind == "weapon" {
        let entries = crate::sim::weapons::WEAPONS
            .iter()
            .map(|definition| {
                let weapon = Weapon::from(definition);
                format!("{} {}s", weapon.name, weapon_pickup_seconds(&weapon).round() as i32)
            })
            .collect::<Vec<_>>()
            .join(", ");
        return Some(format!("Temporary pod: {entries}."));
    }
    powerup_duration_seconds(kind, None)
        .map(|seconds| format!("Active for {}s.", seconds.round() as i32))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sim::config::{REPULSOR_MAX_CHARGES, SHIELD_MAX};

    #[test]
    fn every_catalog_powerup_dispatches_to_an_effect() {
        for meta in crate::render::powerup_art::POWERUP_CATALOG {
            let kind = meta.key;
            let mut player = Player::default_at_origin();
            player.hp = 50;
            player.boost_energy = 0.0;
            let old_damage = player.damage;
            let old_speed = player.speed;
            let old_fire_rate = player.fire_rate;
            let mut chain = ChainSystem::new();
            let mut repulsor = RepulsorSystem::new();
            let mut rng = SimRng::new(7);
            let key = if kind == "weapon" {
                Some("railgun".to_string())
            } else {
                None
            };
            let pickup = PowerUp::new(Vec2::ZERO, kind, key);
            let outcome = apply_powerup(
                &mut player,
                &pickup,
                10.0,
                8,
                &mut chain,
                &mut repulsor,
                &mut rng,
            );

            let changed = match kind {
                "heal" => player.hp > 50,
                "damage" => player.damage > old_damage,
                "speed" => player.speed > old_speed,
                "firerate" => player.fire_rate < old_fire_rate,
                "shield" => player.shield > 0,
                "laser" => player.laser_until > 10.0,
                "vortex" => player.vortex_until > 10.0,
                "drone" => player.drone_until > 10.0,
                "ultra" => player.ultra_charges > 0,
                "boost" => {
                    player.boost_energy == player.boost_max_energy
                        && player.infinite_boost_until > 10.0
                }
                "ricochet" => player.ricochet_until > 10.0,
                "homing" => player.homing_until > 10.0,
                "time_slow" => player.time_slow_until > 10.0,
                "magnet" => player.magnet_until > 10.0,
                "chain" => chain.until > 10.0,
                "repulsor" => outcome.repulsor_fired,
                "weapon" => player.current_weapon.key == "railgun" && player.weapon_until > 10.0,
                _ => false,
            };
            assert!(changed, "{kind} pickup produced no effect");
            assert!(outcome.popup_text.is_some(), "{kind} pickup has no feedback");
        }
    }

    #[test]
    fn capped_pickups_convert_into_a_different_benefit() {
        let mut player = Player::default_at_origin();
        player.shield = SHIELD_MAX;
        let old_damage = player.damage;
        let mut chain = ChainSystem::new();
        let mut repulsor = RepulsorSystem::new();
        let mut rng = SimRng::new(9);

        let full_heal = PowerUp::new(Vec2::ZERO, "heal", None);
        let outcome = apply_powerup(
            &mut player,
            &full_heal,
            1.0,
            1,
            &mut chain,
            &mut repulsor,
            &mut rng,
        );
        assert_eq!(player.damage, old_damage + 1);
        assert_eq!(outcome.popup_text.as_deref(), Some("DAMAGE UP"));

        player.fire_rate = 0.16;
        let capped_rate = PowerUp::new(Vec2::ZERO, "firerate", None);
        apply_powerup(
            &mut player,
            &capped_rate,
            2.0,
            1,
            &mut chain,
            &mut repulsor,
            &mut rng,
        );
        assert_eq!(player.damage, old_damage + 2);

        player.hp = player.max_hp - 10;
        let capped_shield = PowerUp::new(Vec2::ZERO, "shield", None);
        let hull_before = player.hp;
        let outcome = apply_powerup(
            &mut player,
            &capped_shield,
            2.5,
            1,
            &mut chain,
            &mut repulsor,
            &mut rng,
        );
        assert_eq!(player.hp, hull_before + 10);
        assert_eq!(outcome.popup_text.as_deref(), Some("HULL RESTORED"));

        player.shield = 0;
        let capped_weapon = PowerUp::new(Vec2::ZERO, "weapon", Some("basic".to_string()));
        let outcome = apply_powerup(
            &mut player,
            &capped_weapon,
            2.75,
            1,
            &mut chain,
            &mut repulsor,
            &mut rng,
        );
        assert_eq!(outcome.popup_text.as_deref(), Some("SHIELD UP"));
        assert!(player.shield > 0);

        player.ultra_charges = player.ultra_max_charges;
        player.shield = 0;
        let overflow_ultra = PowerUp::new(Vec2::ZERO, "ultra", None);
        let charges_before = player.ultra_charges;
        apply_powerup(
            &mut player,
            &overflow_ultra,
            3.0,
            1,
            &mut chain,
            &mut repulsor,
            &mut rng,
        );
        assert_eq!(player.ultra_charges, charges_before);
        assert_eq!(player.shield, 25);
    }

    #[test]
    fn expired_pickups_are_removed_from_the_run() {
        let mut powerups = vec![PowerUp::new(Vec2::ZERO, "heal", None)];
        tick_powerups(&mut powerups, 0.0);
        assert_eq!(powerups.len(), 1);
        tick_powerups(&mut powerups, 17.5);
        assert_eq!(powerups.len(), 1);
        assert!((powerups[0].ttl - 0.5).abs() < 1e-6);
        tick_powerups(&mut powerups, 0.5);
        assert!(powerups.is_empty());
    }

    #[test]
    fn repulsor_overflow_fires_without_discarding_queued_charges() {
        let mut repulsor = RepulsorSystem::new();
        repulsor.charges = REPULSOR_MAX_CHARGES;
        repulsor.cooldown_until = 6.0;
        assert!(repulsor.on_pickup(2.0));
        assert_eq!(repulsor.charges, REPULSOR_MAX_CHARGES);
        assert_eq!(repulsor.cooldown_until, 6.0);
    }
}
