use crate::sim::math::Vec2;
use crate::sim::projectile::{spawn_player_projectiles, Projectile};
use crate::sim::rng::SimRng;
use crate::sim::weapons::get_weapon;

pub const DRONE_DURATION: f32 = 8.0;
pub const DRONE_ORBIT_RADIUS: f32 = 40.0;
pub const DRONE_ORBIT_SPEED: f32 = 2.4;
pub const DRONE_FIRE_INTERVAL: f32 = 0.6;
pub const DRONE_RANGE: f32 = 300.0;
pub const DRONE_TURN_RATE: f32 = 10.0;
pub const DRONE_MUZZLE_OFFSET: f32 = 12.0;
pub const DRONE_FLASH_TIME: f32 = 0.08;
pub const DRONE_DROP_SHARE: f32 = 0.03;

#[derive(Debug, Clone)]
pub struct DroneState {
    pub active: bool,
    pub pos: Vec2,
    pub angle: f32,
    pub heading: Vec2,
    pub has_target: bool,
    pub fire_cd: f32,
    pub flash: f32,
}

impl Default for DroneState {
    fn default() -> Self {
        Self::new()
    }
}

impl DroneState {
    pub fn new() -> Self {
        Self {
            active: false,
            pos: Vec2::ZERO,
            angle: 0.0,
            heading: Vec2::new(1.0, 0.0),
            has_target: false,
            fire_cd: 0.0,
            flash: 0.0,
        }
    }

    pub fn reset(&mut self) {
        self.active = false;
        self.angle = 0.0;
        self.pos = Vec2::ZERO;
        self.heading = Vec2::new(1.0, 0.0);
        self.has_target = false;
        self.fire_cd = 0.0;
        self.flash = 0.0;
    }
}

pub struct DroneShot {
    pub muzzle: Vec2,
    pub aim: Vec2,
    pub projectiles: Vec<Projectile>,
}

/// Closest live enemy within `max_range` of `origin` (ties preserve slice order).
pub fn nearest_live_enemy(origin: Vec2, enemies: &[(Vec2, bool)], max_range: f32) -> Option<Vec2> {
    let limit2 = max_range * max_range;
    let mut best: Option<Vec2> = None;
    let mut best_d2 = limit2;
    for &(epos, alive) in enemies {
        if !alive {
            continue;
        }
        let d2 = (epos - origin).length_squared();
        if d2 <= limit2 && (best.is_none() || d2 < best_d2) {
            best = Some(epos);
            best_d2 = d2;
        }
    }
    best
}

#[allow(clippy::too_many_arguments)]
pub fn update_drone(
    drone: &mut DroneState,
    player_pos: Vec2,
    base_damage: i32,
    damage_mult: f32,
    crit_chance_bonus: f32,
    crit_mult_bonus: f32,
    drone_until: f32,
    time: f32,
    dt: f32,
    enemies: &[(Vec2, bool)],
    rng: &mut SimRng,
) -> Option<DroneShot> {
    if time >= drone_until {
        drone.reset();
        return None;
    }

    if !drone.active {
        drone.active = true;
        drone.fire_cd = 0.0;
    }

    let step_dt = dt.max(0.0);
    drone.angle += DRONE_ORBIT_SPEED * step_dt;
    drone.pos = Vec2::new(
        player_pos.x + drone.angle.cos() * DRONE_ORBIT_RADIUS,
        player_pos.y + drone.angle.sin() * DRONE_ORBIT_RADIUS,
    );

    let target = nearest_live_enemy(drone.pos, enemies, DRONE_RANGE);
    drone.has_target = target.is_some();
    if let Some(tpos) = target {
        let want = (tpos - drone.pos).normalized();
        let k = (DRONE_TURN_RATE * step_dt).min(1.0);
        let turned = drone.heading + (want - drone.heading) * k;
        if turned.length_squared() > 1e-12 {
            drone.heading = turned.normalized();
        }
    }

    drone.flash = (drone.flash - step_dt).max(0.0);
    drone.fire_cd = (drone.fire_cd - step_dt).max(0.0);

    let target_pos = target?;
    if drone.fire_cd > 0.0 {
        return None;
    }

    let mut aim = (target_pos - drone.pos).normalized();
    if aim.length_squared() <= 1e-12 {
        aim = drone.heading;
    }
    drone.fire_cd = DRONE_FIRE_INTERVAL;
    drone.flash = DRONE_FLASH_TIME;
    let muzzle = drone.pos + aim * DRONE_MUZZLE_OFFSET;

    let drone_weapon = get_weapon("basic");
    let projectiles = spawn_player_projectiles(
        muzzle,
        aim,
        &drone_weapon,
        base_damage,
        damage_mult,
        0.0,
        crit_chance_bonus,
        crit_mult_bonus,
        rng,
    );

    Some(DroneShot {
        muzzle,
        aim,
        projectiles,
    })
}
