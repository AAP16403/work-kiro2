use crate::sim::config::{
    DASH_COOLDOWN, PLAYER_DAMAGE, PLAYER_FIRE_RATE, PLAYER_HP, PLAYER_SPEED, ULTRA_COOLDOWN,
    ULTRA_MAX_CHARGES,
};
use crate::sim::math::Vec2;
use crate::sim::weapons::{get_weapon, Weapon};

#[derive(Debug, Clone)]
pub struct Player {
    pub pos: Vec2,
    pub max_hp: i32,
    pub hp: i32,
    pub shield: i32,
    pub speed: f32,
    pub damage: i32,
    pub fire_rate: f32,
    pub last_shot: f32,
    pub next_shot_time: f32,
    pub recoil: f32,
    pub laser_until: f32,
    pub vortex_until: f32,
    pub vortex_radius: f32,
    pub vortex_dps: f32,
    pub drone_until: f32,
    pub ricochet_until: f32,
    pub homing_until: f32,
    pub time_slow_until: f32,
    pub magnet_until: f32,
    pub weapon_until: f32,
    pub weapon_base: Option<Weapon>,
    pub ultra_charges: i32,
    pub ultra_max_charges: i32,
    pub ultra_cd_until: f32,
    pub ultra_cd_duration: f32,
    pub ultra_variant_idx: usize,
    pub current_weapon: Weapon,
    pub is_dashing: bool,
    pub dash_timer: f32,
    pub dash_cooldown: f32,
    pub dash_direction: Vec2,
    pub dash_speed: f32,
    pub dash_charges: i32,
    pub dash_max_charges: i32,
    pub invincibility_timer: f32,
    pub boost_energy: f32,
    pub boost_max_energy: f32,
    pub is_boosting: bool,
    pub infinite_boost_until: f32,
    pub boost_recharge_rate: f32,
    pub boost_drain_rate: f32,
    pub crit_chance_bonus: f32,
    pub crit_mult_bonus: f32,
    pub damage_flash_timer: f32,
    pub move_vel: Vec2,
}

impl Player {
    pub fn new(pos: Vec2, max_hp: i32) -> Self {
        Self {
            pos,
            max_hp,
            hp: max_hp.max(1).min(max_hp),
            shield: 0,
            speed: PLAYER_SPEED,
            damage: PLAYER_DAMAGE,
            fire_rate: PLAYER_FIRE_RATE,
            last_shot: 0.0,
            next_shot_time: 0.0,
            recoil: 0.0,
            laser_until: 0.0,
            vortex_until: 0.0,
            vortex_radius: 110.0,
            vortex_dps: 38.0,
            drone_until: 0.0,
            ricochet_until: 0.0,
            homing_until: 0.0,
            time_slow_until: 0.0,
            magnet_until: 0.0,
            weapon_until: 0.0,
            weapon_base: None,
            ultra_charges: 0,
            ultra_max_charges: ULTRA_MAX_CHARGES,
            ultra_cd_until: 0.0,
            ultra_cd_duration: ULTRA_COOLDOWN,
            ultra_variant_idx: 0,
            current_weapon: get_weapon("basic"),
            is_dashing: false,
            dash_timer: 0.0,
            dash_cooldown: 0.0,
            dash_direction: Vec2::ZERO,
            dash_speed: 800.0,
            dash_charges: 1,
            dash_max_charges: 1,
            invincibility_timer: 0.0,
            boost_energy: 100.0,
            boost_max_energy: 100.0,
            is_boosting: false,
            infinite_boost_until: 0.0,
            boost_recharge_rate: 22.0,
            boost_drain_rate: 28.0,
            crit_chance_bonus: 0.0,
            crit_mult_bonus: 0.0,
            damage_flash_timer: 0.0,
            move_vel: Vec2::ZERO,
        }
    }

    pub fn default_at_origin() -> Self {
        Self::new(Vec2::ZERO, PLAYER_HP)
    }
}

pub fn compute_dash_cd(diff_mod: f32, perm_mod: f32) -> f32 {
    DASH_COOLDOWN * diff_mod * perm_mod
}

pub fn perform_dash(
    player: &mut Player,
    time: f32,
    diff_mod: f32,
    perm_mod: f32,
    input_dir: Vec2,
    mouse_world: Vec2,
) -> bool {
    if player.dash_charges <= 0 || player.is_dashing {
        return false;
    }

    player.is_dashing = true;
    player.dash_timer = 0.15;
    player.dash_charges = (player.dash_charges - 1).max(0);

    if player.dash_charges == player.dash_max_charges - 1 {
        player.dash_cooldown = time + compute_dash_cd(diff_mod, perm_mod);
    }

    player.invincibility_timer = 0.15;
    if input_dir.length_squared() > 1e-12 {
        player.dash_direction = input_dir.normalized();
    } else {
        let aim = mouse_world - player.pos;
        player.dash_direction = if aim.length_squared() > 1e-12 {
            aim.normalized()
        } else if player.move_vel.length_squared() > 1e-12 {
            player.move_vel.normalized()
        } else {
            Vec2::new(1.0, 0.0)
        };
    }
    true
}

pub fn recharge_dash(player: &mut Player, time: f32, diff_mod: f32, perm_mod: f32) {
    if player.dash_charges >= player.dash_max_charges {
        return;
    }
    if time < player.dash_cooldown {
        return;
    }
    player.dash_charges = (player.dash_charges + 1).min(player.dash_max_charges);
    if player.dash_charges < player.dash_max_charges {
        player.dash_cooldown = time + compute_dash_cd(diff_mod, perm_mod);
    }
}

pub fn format_dash_hud(player: &Player, current_time: f32) -> String {
    let charges = player.dash_charges;
    let max_ch = player.dash_max_charges;
    let cd_left = (player.dash_cooldown - current_time).max(0.0);
    if charges < max_ch && cd_left > 0.0 {
        format!("Dash {charges}/{max_ch} {cd_left:.1}s")
    } else if max_ch > 1 {
        format!("Dash {charges}/{max_ch}")
    } else {
        String::new()
    }
}

pub fn update_boost(
    player: &mut Player,
    dt: f32,
    boost_requested: bool,
    current_time: f32,
    has_infinite: bool,
) -> bool {
    let is_inf = has_infinite || (current_time < player.infinite_boost_until);
    let can_start = is_inf || (player.boost_energy >= 12.0);
    let can_sustain = is_inf || (player.boost_energy > 0.0);

    if boost_requested && ((player.is_boosting && can_sustain) || (!player.is_boosting && can_start)) {
        player.is_boosting = true;
        if !is_inf {
            player.boost_energy = (player.boost_energy - player.boost_drain_rate * dt).max(0.0);
            if player.boost_energy <= 0.0 {
                player.is_boosting = false;
            }
        }
    } else {
        player.is_boosting = false;
        if player.boost_energy < player.boost_max_energy {
            player.boost_energy = (player.boost_energy + player.boost_recharge_rate * dt).min(player.boost_max_energy);
        }
    }
    player.is_boosting
}

pub fn format_boost_hud(player: &Player, current_time: f32, has_infinite: bool) -> String {
    let is_inf = has_infinite || (current_time < player.infinite_boost_until);
    if is_inf {
        let left = (player.infinite_boost_until - current_time).max(0.0);
        if left > 0.0 {
            format!("BOOST [INF {left:.0}s]")
        } else {
            "BOOST [INF]".to_string()
        }
    } else if player.is_boosting {
        format!("BOOSTING {}%", player.boost_energy as i32)
    } else {
        format!("Boost {}%", player.boost_energy as i32)
    }
}
