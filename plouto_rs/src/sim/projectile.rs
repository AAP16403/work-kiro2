use crate::sim::config::PLAYER_DAMAGE;
use crate::sim::math::Vec2;
use crate::sim::rng::SimRng;
use crate::sim::weapons::Weapon;

#[derive(Debug, Clone)]
pub struct Projectile {
    pub pos: Vec2,
    pub prev_pos: Option<Vec2>,
    pub pre_bounce_segment: Option<(Vec2, Vec2)>,
    pub boundary_spent: Option<Vec2>,
    pub ttl_expired: bool,
    pub vel: Vec2,
    pub damage: i32,
    pub ttl: f32,
    /// Original travel time, used by lobbed shells to animate their height arc.
    pub flight_duration: f32,
    pub owner: String,
    pub projectile_type: String,
    pub weapon_name: String,
    pub is_crit: bool,
    pub cluster_on_death: bool,
    pub is_echo: bool,
    pub bounces_taken: i32,
    pub pierce_left: i32,
    pub hit_ids: Vec<u64>,
    pub homing_left: f32,
    pub homing_lock_id: Option<u64>,
    pub source: String,
}

impl Projectile {
    pub fn new(
        pos: Vec2,
        vel: Vec2,
        damage: i32,
        ttl: f32,
        owner: &str,
        projectile_type: &str,
    ) -> Self {
        Self {
            pos,
            prev_pos: None,
            pre_bounce_segment: None,
            boundary_spent: None,
            ttl_expired: false,
            vel,
            damage,
            ttl,
            flight_duration: ttl,
            owner: owner.to_string(),
            projectile_type: projectile_type.to_string(),
            weapon_name: String::new(),
            is_crit: false,
            cluster_on_death: false,
            is_echo: false,
            bounces_taken: 0,
            pierce_left: 0,
            hit_ids: Vec::new(),
            homing_left: 0.0,
            homing_lock_id: None,
            source: String::new(),
        }
    }

    pub fn with_source(mut self, source: &str) -> Self {
        self.source = source.to_string();
        self
    }

    /// Advance position and TTL for one simulation step; returns false when expired.
    pub fn step(&mut self, dt: f32) -> bool {
        self.prev_pos = Some(self.pos);
        self.pre_bounce_segment = None;
        self.boundary_spent = None;
        let travel_dt = dt.max(0.0).min(self.ttl.max(0.0));
        self.pos += self.vel * travel_dt;
        self.ttl -= dt;
        self.ttl_expired = self.ttl <= 0.0;
        !self.ttl_expired
    }
}

pub fn compute_player_raw_damage(weapon: &Weapon, base_player_damage: i32) -> i32 {
    let dmg = (weapon.damage as f32 + 0.5 * (PLAYER_DAMAGE as f32))
        * (base_player_damage as f32 / (PLAYER_DAMAGE as f32))
        + 0.5;
    dmg.floor() as i32
}

#[allow(clippy::too_many_arguments)]
pub fn spawn_player_projectiles(
    muzzle: Vec2,
    aim_dir: Vec2,
    weapon: &Weapon,
    base_player_damage: i32,
    damage_mult: f32,
    recoil_deg: f32,
    crit_chance_bonus: f32,
    crit_mult_bonus: f32,
    rng: &mut SimRng,
) -> Vec<Projectile> {
    let dir = aim_dir.normalized();
    if dir.length_squared() <= 1e-12 {
        return Vec::new();
    }

    let effective_crit_chance = (weapon.crit_chance + crit_chance_bonus).clamp(0.0, 0.85);
    let is_crit = rng.f32() < effective_crit_chance;
    let base_raw = compute_player_raw_damage(weapon, base_player_damage) as f32;
    let scaled_raw = base_raw * damage_mult;
    let final_damage = if is_crit {
        let mult = weapon.crit_mult + crit_mult_bonus;
        (scaled_raw * mult).round().max(1.0) as i32
    } else {
        (scaled_raw + 0.5).floor().max(1.0) as i32
    };

    let recoil = recoil_deg.max(0.0);
    let count = weapon.projectile_count.max(1);
    let mut out = Vec::with_capacity(count);

    match weapon.projectile_type.as_str() {
        "bullet" | "spread" | "plasma" => {
            let ttl = match weapon.projectile_type.as_str() {
                "bullet" => 3.0,
                "spread" => 3.0,
                _ => 3.2,
            };
            for i in 0..count {
                let angle_offset = (i as f32 - (count as f32) * 0.5 + 0.5) * weapon.spread_angle;
                let jitter = if recoil > 0.0 {
                    rng.range_f32(-recoil, recoil)
                } else {
                    0.0
                };
                let d = dir.rotated_deg(angle_offset + jitter);
                let mut p = Projectile::new(
                    muzzle,
                    d * weapon.projectile_speed,
                    final_damage,
                    ttl,
                    "player",
                    weapon.projectile_type.as_str(),
                );
                p.is_crit = is_crit;
                p.weapon_name = weapon.name.clone();
                out.push(p);
            }
        }
        "missile" => {
            let jitter = if recoil > 0.0 {
                rng.range_f32(-recoil, recoil)
            } else {
                0.0
            };
            let d = if jitter != 0.0 {
                dir.rotated_deg(jitter)
            } else {
                dir
            };
            let spawn_pos = muzzle + dir * 4.0;
            let mut p = Projectile::new(
                spawn_pos,
                d * weapon.projectile_speed,
                final_damage,
                3.8,
                "player",
                "missile",
            );
            p.is_crit = is_crit;
            p.weapon_name = weapon.name.clone();
            out.push(p);
        }
        "railgun" => {
            let jitter = if recoil > 0.0 {
                rng.range_f32(-recoil * 0.4, recoil * 0.4)
            } else {
                0.0
            };
            let d = if jitter != 0.0 {
                dir.rotated_deg(jitter)
            } else {
                dir
            };
            let mut p = Projectile::new(
                muzzle,
                d * weapon.projectile_speed,
                final_damage,
                1.8,
                "player",
                "railgun",
            );
            p.is_crit = is_crit;
            p.pierce_left = weapon.pierce.max(0);
            p.weapon_name = weapon.name.clone();
            out.push(p);
        }
        "flak" => {
            for i in 0..count {
                let angle_offset = (i as f32 - (count as f32) * 0.5 + 0.5) * weapon.spread_angle;
                let jitter = if recoil > 0.0 {
                    rng.range_f32(-recoil, recoil)
                } else {
                    0.0
                };
                let d = dir.rotated_deg(angle_offset + jitter);
                let speed = weapon.projectile_speed * rng.range_f32(0.9, 1.1);
                let ttl = rng.range_f32(0.7, 1.1);
                let mut p = Projectile::new(muzzle, d * speed, final_damage, ttl, "player", "flak");
                p.is_crit = is_crit;
                p.cluster_on_death = true;
                p.weapon_name = weapon.name.clone();
                out.push(p);
            }
        }
        "mortar" => {
            let ttl = crate::sim::config::PLAYER_MORTAR_MAX_RANGE
                / weapon.projectile_speed.max(1.0);
            let mut p = Projectile::new(
                muzzle,
                dir * weapon.projectile_speed,
                final_damage,
                ttl,
                "player",
                "mortar",
            );
            p.is_crit = is_crit;
            p.weapon_name = weapon.name.clone();
            out.push(p);
        }
        "laser" => {
            let mut p = Projectile::new(
                muzzle,
                dir * 2000.0,
                final_damage,
                0.05,
                "player",
                "laser",
            );
            p.is_crit = is_crit;
            p.weapon_name = weapon.name.clone();
            out.push(p);
        }
        _ => {}
    }

    out
}
