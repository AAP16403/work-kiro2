use crate::sim::config::{BOOST_SPEED_MULT, ISO_SCALE_X, ISO_SCALE_Y};
use crate::sim::math::Vec2;
use crate::sim::state::{SimInput, SimState};

/// Axis-aligned world-space rectangle used for deterministic visibility checks.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct WorldRect {
    pub min: Vec2,
    pub max: Vec2,
}

impl WorldRect {
    #[inline]
    pub fn contains(self, pos: Vec2, margin: f32) -> bool {
        pos.x >= self.min.x - margin
            && pos.x <= self.max.x + margin
            && pos.y >= self.min.y - margin
            && pos.y <= self.max.y + margin
    }
}

/// Cross-tick player perception state persisted on `SimState` and hashed in replays.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PerceptionMemory {
    pub smoothed_vel: Vec2,
    pub prev_hp: i32,
    pub breathing_room_left: f32,
    pub player_knocked_back: bool,
    pub view_w: u32,
    pub view_h: u32,
}

impl PerceptionMemory {
    pub fn new(initial_hp: i32, view_w: u32, view_h: u32) -> Self {
        Self {
            smoothed_vel: Vec2::ZERO,
            prev_hp: initial_hp,
            breathing_room_left: 0.0,
            player_knocked_back: false,
            view_w,
            view_h,
        }
    }
}

/// Immutable per-tick snapshot of the player and viewport derived solely from sim state.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Perception {
    pub player_pos: Vec2,
    pub smoothed_vel: Vec2,
    pub intent_vel: Vec2,
    pub aim_dir: Vec2,
    pub is_dashing: bool,
    pub invulnerable_left: f32,
    pub boosting: bool,
    pub hull_frac: f32,
    pub ultra_ready: bool,
    pub on_screen_rect: WorldRect,
    pub breathing_room_left: f32,
}

#[inline]
fn clamp_len(v: Vec2, max_len: f32) -> Vec2 {
    if max_len <= 0.0 {
        return Vec2::ZERO;
    }
    let len = v.length();
    if len > max_len && len > 1e-6 {
        v * (max_len / len)
    } else {
        v
    }
}

/// Build the tick's deterministic `Perception` snapshot and advance `PerceptionMemory`.
pub fn build_perception(
    state: &SimState,
    mem: &mut PerceptionMemory,
    input: &SimInput,
    raw_vel: Vec2,
    dash_ended: bool,
    enemy_dt: f32,
) -> Perception {
    let dt = enemy_dt.max(0.0);
    let alpha = 1.0 - (-dt / 0.12).exp();
    let max_smooth_speed = state.effective_player_speed() * BOOST_SPEED_MULT * 1.25;

    // Exclude dash spikes and boss-contact teleports from the smoothed velocity
    // estimate so ranged predictors don't lead the player into the arena wall.
    if !state.player.is_dashing
        && !dash_ended
        && !mem.player_knocked_back
        && raw_vel.length() <= max_smooth_speed
    {
        mem.smoothed_vel = mem.smoothed_vel + (raw_vel - mem.smoothed_vel) * alpha;
    }
    mem.player_knocked_back = false;

    let intent_vel = if input.move_dir.length_squared() > 1e-12 {
        let mult = if state.player.is_boosting {
            BOOST_SPEED_MULT
        } else {
            1.0
        };
        input.move_dir.normalized() * (state.effective_player_speed() * mult)
    } else {
        Vec2::ZERO
    };

    let aim_delta = input.aim_world - state.player.pos;
    let aim_dir = if aim_delta.length_squared() > 1e-12 {
        aim_delta.normalized()
    } else {
        Vec2::new(1.0, 0.0)
    };

    if state.player.hp < mem.prev_hp {
        mem.breathing_room_left = 0.60;
    } else {
        mem.breathing_room_left = (mem.breathing_room_left - dt).max(0.0);
    }
    mem.prev_hp = state.player.hp;

    let hull_frac = (state.player.hp as f32 / state.player.max_hp.max(1) as f32).clamp(0.0, 1.0);
    let ultra_ready = state.player.ultra_charges > 0 && state.time >= state.player.ultra_cd_until;

    let on_screen_rect = if mem.view_w > 0 && mem.view_h > 0 {
        let cam_center = clamp_len(
            state.player.pos * 0.62,
            (state.room_radius * 0.56).max(80.0),
        );
        let h = 0.25 * (mem.view_w as f32 / ISO_SCALE_X + mem.view_h as f32 / ISO_SCALE_Y);
        WorldRect {
            min: cam_center - Vec2::new(h, h),
            max: cam_center + Vec2::new(h, h),
        }
    } else {
        let r = state.room_radius;
        WorldRect {
            min: Vec2::new(-r, -r),
            max: Vec2::new(r, r),
        }
    };

    Perception {
        player_pos: state.player.pos,
        smoothed_vel: mem.smoothed_vel,
        intent_vel,
        aim_dir,
        is_dashing: state.player.is_dashing,
        invulnerable_left: state.player.invincibility_timer.max(0.0),
        boosting: state.player.is_boosting,
        hull_frac,
        ultra_ready,
        on_screen_rect,
        breathing_room_left: mem.breathing_room_left,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sim::state::RunSetup;

    #[test]
    fn smoothed_vel_ignores_dash_and_knockback_spikes() {
        let mut setup = RunSetup::default();
        setup.view_w = 980;
        setup.view_h = 620;
        let mut state = SimState::new(setup);
        let mut mem = PerceptionMemory::new(state.player.hp, 980, 620);
        let input = SimInput {
            move_dir: Vec2::new(1.0, 0.0),
            ..SimInput::default()
        };

        let p1 = build_perception(&state, &mut mem, &input, Vec2::new(175.0, 0.0), false, 1.0 / 60.0);
        assert!(p1.smoothed_vel.x > 0.0);
        let before_spike = p1.smoothed_vel;

        state.player.is_dashing = true;
        let p2 = build_perception(&state, &mut mem, &input, Vec2::new(800.0, 0.0), false, 1.0 / 60.0);
        assert_eq!(p2.smoothed_vel, before_spike);

        state.player.is_dashing = false;
        mem.player_knocked_back = true;
        let p3 = build_perception(&state, &mut mem, &input, Vec2::new(-900.0, 0.0), false, 1.0 / 60.0);
        assert_eq!(p3.smoothed_vel, before_spike);
        assert!(!mem.player_knocked_back);
    }

    #[test]
    fn breathing_room_triggers_on_hp_drop_and_decays() {
        let state_setup = RunSetup::default();
        let mut state = SimState::new(state_setup);
        let mut mem = PerceptionMemory::new(state.player.hp, 980, 620);
        let input = SimInput::default();

        state.player.hp -= 10;
        let p1 = build_perception(&state, &mut mem, &input, Vec2::ZERO, false, 1.0 / 60.0);
        assert!((p1.breathing_room_left - 0.60).abs() < 1e-5);

        let p2 = build_perception(&state, &mut mem, &input, Vec2::ZERO, false, 0.25);
        assert!((p2.breathing_room_left - 0.35).abs() < 1e-5);
    }
}
