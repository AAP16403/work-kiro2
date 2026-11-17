//! Pure stick/trigger mapping helpers for gamepad input.
//!
//! Nothing in this module touches gilrs or the game state. Inputs are raw
//! stick values in the range -1..1 with the Y axis pointing UP (positive y),
//! which matches the gilrs convention used by `PadSnapshot`.
//!
//! World axis convention: stick up is world +y (the same as keyboard W in
//! `App::build_sim_input`), and stick right is world +x (the same as D).

use crate::sim::math::Vec2;

/// Default radial deadzone applied to both sticks.
pub const DEFAULT_DEADZONE: f32 = 0.18;

/// Trigger value (0..1) above which a trigger counts as pressed.
pub const TRIGGER_THRESHOLD: f32 = 0.35;

/// Right-stick magnitude (after deadzone) above which the stick also counts as
/// holding fire, so pushing the aim stick fires without a trigger or bumper.
pub const AIM_FIRE_THRESHOLD: f32 = 0.5;

/// World units in front of the player where the virtual aim point is placed.
pub const AIM_DISTANCE: f32 = 260.0;

/// Left-stick magnitude (after deadzone) above which a menu navigation
/// direction is produced.
const NAV_THRESHOLD: f32 = 0.6;

/// Delay before a held menu direction starts repeating, in seconds.
const NAV_INITIAL_DELAY: f32 = 0.35;

/// Interval between repeats while a menu direction stays held, in seconds.
const NAV_REPEAT_INTERVAL: f32 = 0.12;

/// Radial deadzone. Magnitudes at or below `deadzone` map to zero. Above it the
/// magnitude is rescaled so the output runs from 0 at the deadzone edge to 1 at
/// full deflection, clamped to 1. Direction is preserved.
///
/// `deadzone` is clamped to 0..0.99 so the rescale never divides by zero.
/// Non-finite input yields zero.
pub fn apply_radial_deadzone(v: [f32; 2], deadzone: f32) -> [f32; 2] {
    let mag = (v[0] * v[0] + v[1] * v[1]).sqrt();
    if !mag.is_finite() {
        return [0.0, 0.0];
    }
    let dz = if deadzone.is_finite() {
        deadzone.clamp(0.0, 0.99)
    } else {
        DEFAULT_DEADZONE
    };
    if mag <= dz {
        return [0.0, 0.0];
    }
    let out_mag = ((mag - dz) / (1.0 - dz)).min(1.0);
    let scale = out_mag / mag;
    [v[0] * scale, v[1] * scale]
}

/// World-space movement vector. Magnitude is 0..1 after the deadzone, and the
/// direction follows the stick (up is +y, right is +x).
pub fn stick_to_move(v: [f32; 2], deadzone: f32) -> Vec2 {
    let d = apply_radial_deadzone(v, deadzone);
    Vec2::new(d[0], d[1])
}

/// Normalized world-space aim direction, or `None` while the stick is inside
/// the deadzone. The caller keeps its last aim direction when this returns
/// `None`, so the aim point holds still once the stick is released.
pub fn stick_to_aim_dir(v: [f32; 2], deadzone: f32) -> Option<Vec2> {
    let d = apply_radial_deadzone(v, deadzone);
    let dir = Vec2::new(d[0], d[1]);
    if dir.length_squared() <= 1e-12 {
        None
    } else {
        Some(dir.normalized())
    }
}

/// Four-way menu direction. Screen-style: up is y > 0 on the stick.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NavDir4 {
    Up,
    Down,
    Left,
    Right,
}

/// Converts a stick deflection to a four-way menu direction. The dominant axis
/// wins, and the result is `None` unless the magnitude exceeds 0.6. Ties go to
/// the vertical axis.
pub fn stick_to_nav(v: [f32; 2]) -> Option<NavDir4> {
    if !v[0].is_finite() || !v[1].is_finite() {
        return None;
    }
    let mag = (v[0] * v[0] + v[1] * v[1]).sqrt();
    if mag <= NAV_THRESHOLD {
        return None;
    }
    if v[0].abs() > v[1].abs() {
        if v[0] > 0.0 {
            Some(NavDir4::Right)
        } else {
            Some(NavDir4::Left)
        }
    } else if v[1] > 0.0 {
        Some(NavDir4::Up)
    } else {
        Some(NavDir4::Down)
    }
}

/// Key-repeat state for menu navigation.
///
/// A new direction fires immediately. A direction held past 0.35s then repeats
/// every 0.12s. Releasing the stick (`None`) resets the state.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct NavRepeat {
    held: Option<NavDir4>,
    timer: f32,
    repeating: bool,
}

impl NavRepeat {
    pub fn new() -> Self {
        Self {
            held: None,
            timer: 0.0,
            repeating: false,
        }
    }

    /// Feed the current direction and the frame time in seconds. Returns the
    /// direction to act on this frame, or `None`.
    pub fn update(&mut self, dir: Option<NavDir4>, dt: f32) -> Option<NavDir4> {
        let Some(d) = dir else {
            self.held = None;
            self.timer = 0.0;
            self.repeating = false;
            return None;
        };

        if self.held != Some(d) {
            self.held = Some(d);
            self.timer = 0.0;
            self.repeating = false;
            return Some(d);
        }

        let dt = if dt.is_finite() { dt.max(0.0) } else { 0.0 };
        self.timer += dt;
        let threshold = if self.repeating {
            NAV_REPEAT_INTERVAL
        } else {
            NAV_INITIAL_DELAY
        };
        if self.timer >= threshold {
            self.timer -= threshold;
            self.repeating = true;
            return Some(d);
        }
        None
    }
}

impl Default for NavRepeat {
    fn default() -> Self {
        Self::new()
    }
}
