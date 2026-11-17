use std::f32::consts::{PI, TAU};

use crate::sim::math::Vec2;
use crate::sim::projectile::Projectile;

pub const GLASS_CANNON_DAMAGE_MULT: f32 = 1.5;
pub const GLASS_CANNON_MAX_HP_MULT: f32 = 0.6;
pub const BULLET_HELL_PROJECTILE_MULT: f32 = 1.25;
pub const BULLET_HELL_EXTRA_PER_VOLLEY: usize = 1;
pub const BULLET_HELL_LONE_SHOT_SPREAD_DEG: f32 = 12.0;
pub const DRIFT_ACCEL: f32 = 5.0;
pub const DRIFT_DECEL: f32 = 2.4;
pub const FRENZY_ENEMY_SPEED_MULT: f32 = 1.2;
pub const FRENZY_SPAWN_SIZE_MULT: f32 = 1.25;
pub const IRON_MAN_SHIELD_REGEN: f32 = 2.0;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RunRules {
    pub player_damage_mult: f32,
    pub player_max_hp_mult: f32,
    pub player_accel: f32,
    pub player_decel: f32,
    pub enemy_projectile_speed_mult: f32,
    pub enemy_volley_extra: usize,
    pub enemy_speed_mult: f32,
    pub spawn_size_mult: f32,
    pub pickups_enabled: bool,
    pub shield_regen_per_s: f32,
}

impl Default for RunRules {
    fn default() -> Self {
        Self {
            player_damage_mult: 1.0,
            player_max_hp_mult: 1.0,
            player_accel: 0.0,
            player_decel: 0.0,
            enemy_projectile_speed_mult: 1.0,
            enemy_volley_extra: 0,
            enemy_speed_mult: 1.0,
            spawn_size_mult: 1.0,
            pickups_enabled: true,
            shield_regen_per_s: 0.0,
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct MutatorDef {
    pub id: &'static str,
    pub name: &'static str,
    pub description: &'static str,
    pub score_mult: f32,
}

pub const MUTATORS: &[MutatorDef] = &[
    MutatorDef {
        id: "glass_cannon",
        name: "Glass Cannon",
        description: "Deal 1.5x damage, but your max HP drops to 60 percent.",
        score_mult: 1.25,
    },
    MutatorDef {
        id: "bullet_hell",
        name: "Bullet Hell",
        description: "Enemy shots fly 25 percent faster and every volley gains one extra shot.",
        score_mult: 1.20,
    },
    MutatorDef {
        id: "drift",
        name: "Drift",
        description: "Steering is sluggish and the ship slides for a while after you let go.",
        score_mult: 1.10,
    },
    MutatorDef {
        id: "frenzy",
        name: "Frenzy",
        description: "Enemies move 20 percent faster and early waves field more bodies, still within the wave cap.",
        score_mult: 1.30,
    },
    MutatorDef {
        id: "iron_man",
        name: "Iron Man",
        description: "No pickups spawn, but your shields slowly recharge over time.",
        score_mult: 1.15,
    },
];

pub fn mutator_by_id(id: &str) -> Option<&'static MutatorDef> {
    MUTATORS.iter().find(|m| m.id == id)
}

pub fn normalize_selection<'a, I: IntoIterator<Item = &'a str>>(ids: I) -> Vec<String> {
    let wanted: Vec<&str> = ids.into_iter().collect();
    MUTATORS
        .iter()
        .filter(|m| wanted.iter().any(|&w| w == m.id))
        .map(|m| m.id.to_string())
        .collect()
}

pub fn toggle_selection(current: &[String], mutator_id: &str) -> Vec<String> {
    if mutator_by_id(mutator_id).is_none() {
        return current.iter().map(|s| s.as_str()).collect::<Vec<_>>().into_iter().map(str::to_string).collect();
    }
    if current.iter().any(|id| id == mutator_id) {
        current
            .iter()
            .filter(|id| id.as_str() != mutator_id)
            .cloned()
            .collect()
    } else {
        let mut refs: Vec<&str> = current.iter().map(|s| s.as_str()).collect();
        refs.push(mutator_id);
        normalize_selection(refs)
    }
}

pub fn mutator_names(ids: &[String]) -> Vec<&'static str> {
    MUTATORS
        .iter()
        .filter(|m| ids.iter().any(|id| id == m.id))
        .map(|m| m.name)
        .collect()
}

pub fn apply_mutators(ids: &[String]) -> RunRules {
    let mut r = RunRules::default();
    for m in MUTATORS {
        if !ids.iter().any(|id| id == m.id) {
            continue;
        }
        match m.id {
            "glass_cannon" => {
                r.player_damage_mult *= GLASS_CANNON_DAMAGE_MULT;
                r.player_max_hp_mult *= GLASS_CANNON_MAX_HP_MULT;
            }
            "bullet_hell" => {
                r.enemy_projectile_speed_mult *= BULLET_HELL_PROJECTILE_MULT;
                r.enemy_volley_extra += BULLET_HELL_EXTRA_PER_VOLLEY;
            }
            "drift" => {
                r.player_accel = DRIFT_ACCEL;
                r.player_decel = DRIFT_DECEL;
            }
            "frenzy" => {
                r.enemy_speed_mult *= FRENZY_ENEMY_SPEED_MULT;
                r.spawn_size_mult *= FRENZY_SPAWN_SIZE_MULT;
            }
            "iron_man" => {
                r.pickups_enabled = false;
                r.shield_regen_per_s += IRON_MAN_SHIELD_REGEN;
            }
            _ => {}
        }
    }
    r
}

pub fn combined_score_multiplier(ids: &[String]) -> f32 {
    let mut mult = 1.0_f32;
    for m in MUTATORS {
        if ids.iter().any(|id| id == m.id) {
            mult *= m.score_mult;
        }
    }
    mult
}

pub fn format_score_mult(mult: f32) -> String {
    let cents = ((mult as f64) * 100.0 + 0.5 + 1e-9).floor();
    format!("x{:.2}", cents / 100.0)
}

pub fn scaled_max_hp(base_hp: i32, rules: &RunRules) -> i32 {
    ((base_hp as f32) * rules.player_max_hp_mult).round().max(1.0) as i32
}

pub fn steer_velocity(vel: Vec2, desired: Vec2, dt: f32, rules: &RunRules) -> Vec2 {
    if rules.player_accel <= 0.0 {
        return desired;
    }
    let rate = if desired.length() > 0.0 {
        rules.player_accel
    } else {
        rules.player_decel
    };
    let k = 1.0 - (-rate.max(0.0) * dt.max(0.0)).exp();
    vel + (desired - vel) * k
}

pub fn tick_shield_regen(shield: &mut i32, mut carry: f32, dt: f32, rules: &RunRules, cap: i32) -> f32 {
    let rate = rules.shield_regen_per_s;
    if rate <= 0.0 || *shield >= cap {
        return 0.0;
    }
    carry += rate * dt.max(0.0);
    let whole = carry.floor() as i32;
    if whole > 0 {
        *shield = (*shield + whole).min(cap);
        carry -= whole as f32;
    }
    if *shield < cap {
        carry
    } else {
        0.0
    }
}

#[inline]
fn wrap_angle(a: f32) -> f32 {
    (a + PI).rem_euclid(TAU) - PI
}

pub fn shape_enemy_volley(projectiles: &mut Vec<Projectile>, start: usize, rules: &RunRules) -> usize {
    let speed_mult = rules.enemy_projectile_speed_mult;
    let extra = rules.enemy_volley_extra;
    if (speed_mult - 1.0).abs() <= f32::EPSILON && extra == 0 {
        return 0;
    }
    let indices: Vec<usize> = (start..projectiles.len())
        .filter(|&i| projectiles[i].owner == "enemy" && projectiles[i].projectile_type != "bomb")
        .collect();
    if indices.is_empty() {
        return 0;
    }
    if (speed_mult - 1.0).abs() > f32::EPSILON {
        for &i in &indices {
            projectiles[i].vel = projectiles[i].vel * speed_mult;
        }
    }
    if extra == 0 {
        return 0;
    }

    let template = projectiles[indices[0]].clone();
    let speed = template.vel.length();
    if speed <= 1e-9 {
        return 0;
    }
    let angles: Vec<f32> = indices
        .iter()
        .map(|&i| projectiles[i].vel.y.atan2(projectiles[i].vel.x))
        .collect();
    let sum_x: f32 = angles.iter().map(|a| a.cos()).sum();
    let sum_y: f32 = angles.iter().map(|a| a.sin()).sum();
    let ref_ang = if sum_x.hypot(sum_y) > 1e-9 {
        sum_y.atan2(sum_x)
    } else {
        angles[0]
    };

    let mut new_angles = Vec::with_capacity(extra);
    if indices.len() == 1 {
        let spread = BULLET_HELL_LONE_SHOT_SPREAD_DEG.to_radians();
        for k in 0..extra {
            let side = if k % 2 == 0 { 1.0 } else { -1.0 };
            new_angles.push(ref_ang + side * spread * ((k / 2 + 1) as f32));
        }
    } else {
        let mut rel: Vec<f32> = angles.iter().map(|&a| wrap_angle(a - ref_ang)).collect();
        rel.sort_by(|a, b| a.total_cmp(b));
        for _ in 0..extra {
            let mut best_gap = -1.0_f32;
            let mut best_j = 0;
            for j in 0..rel.len() - 1 {
                let g = rel[j + 1] - rel[j];
                if g >= best_gap {
                    best_gap = g;
                    best_j = j;
                }
            }
            let mid = rel[best_j] + best_gap * 0.5;
            rel.insert(best_j + 1, mid);
            new_angles.push(ref_ang + mid);
        }
    }

    for a in &new_angles {
        let dir = Vec2::new(a.cos(), a.sin());
        let mut p = Projectile::new(
            template.pos,
            dir * speed,
            template.damage,
            template.ttl,
            &template.owner,
            &template.projectile_type,
        );
        p.is_crit = template.is_crit;
        p.source = template.source.clone();
        projectiles.push(p);
    }
    new_angles.len()
}
