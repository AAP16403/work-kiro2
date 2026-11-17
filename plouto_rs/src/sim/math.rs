use serde::{Deserialize, Serialize};
use std::f32::consts::{FRAC_PI_2, SQRT_2, TAU};
use std::ops::{Add, AddAssign, Div, DivAssign, Mul, MulAssign, Neg, Sub, SubAssign};

use crate::sim::config::{
    ARENA_MARGIN_MAX, ARENA_MARGIN_MIN, COUNTDOWN_ROUND_DIGITS, CROSS_ARM_RATIO,
    DIAMOND_EXTENT_RATIO, DONUT_INNER_RATIO, ISO_SCALE_X, ISO_SCALE_Y, MAP_CIRCLE, MAP_CROSS,
    MAP_DIAMOND, MAP_DONUT, WORLD_ARENA_SCALE,
};
use crate::sim::rng::SimRng;

#[derive(Debug, Clone, Copy, PartialEq, Default, Serialize, Deserialize)]
pub struct Vec2 {
    pub x: f32,
    pub y: f32,
}

impl Vec2 {
    pub const ZERO: Self = Self { x: 0.0, y: 0.0 };

    #[inline]
    pub const fn new(x: f32, y: f32) -> Self {
        Self { x, y }
    }

    #[inline]
    pub fn length(self) -> f32 {
        self.x.hypot(self.y)
    }

    #[inline]
    pub fn length_squared(self) -> f32 {
        self.x * self.x + self.y * self.y
    }

    #[inline]
    pub fn dot(self, other: Self) -> f32 {
        self.x * other.x + self.y * other.y
    }

    #[inline]
    pub fn normalized(self) -> Self {
        let len = self.length();
        if len <= 1e-9 {
            Self::ZERO
        } else {
            Self::new(self.x / len, self.y / len)
        }
    }

    #[inline]
    pub fn perp(self) -> Self {
        Self::new(-self.y, self.x)
    }

    #[inline]
    pub fn rotated_deg(self, deg: f32) -> Self {
        let a = deg.to_radians();
        let (s, c) = a.sin_cos();
        Self::new(self.x * c - self.y * s, self.x * s + self.y * c)
    }

    #[inline]
    pub fn rotated_rad(self, rad: f32) -> Self {
        let (s, c) = rad.sin_cos();
        Self::new(self.x * c - self.y * s, self.x * s + self.y * c)
    }
}

impl Add for Vec2 {
    type Output = Self;
    #[inline]
    fn add(self, rhs: Self) -> Self {
        Self::new(self.x + rhs.x, self.y + rhs.y)
    }
}

impl AddAssign for Vec2 {
    #[inline]
    fn add_assign(&mut self, rhs: Self) {
        self.x += rhs.x;
        self.y += rhs.y;
    }
}

impl Sub for Vec2 {
    type Output = Self;
    #[inline]
    fn sub(self, rhs: Self) -> Self {
        Self::new(self.x - rhs.x, self.y - rhs.y)
    }
}

impl SubAssign for Vec2 {
    #[inline]
    fn sub_assign(&mut self, rhs: Self) {
        self.x -= rhs.x;
        self.y -= rhs.y;
    }
}

impl Mul<f32> for Vec2 {
    type Output = Self;
    #[inline]
    fn mul(self, rhs: f32) -> Self {
        Self::new(self.x * rhs, self.y * rhs)
    }
}

impl Mul<Vec2> for f32 {
    type Output = Vec2;
    #[inline]
    fn mul(self, rhs: Vec2) -> Vec2 {
        Vec2::new(self * rhs.x, self * rhs.y)
    }
}

impl MulAssign<f32> for Vec2 {
    #[inline]
    fn mul_assign(&mut self, rhs: f32) {
        self.x *= rhs;
        self.y *= rhs;
    }
}

impl Div<f32> for Vec2 {
    type Output = Self;
    #[inline]
    fn div(self, rhs: f32) -> Self {
        if rhs.abs() <= 1e-12 {
            Self::ZERO
        } else {
            Self::new(self.x / rhs, self.y / rhs)
        }
    }
}

impl DivAssign<f32> for Vec2 {
    #[inline]
    fn div_assign(&mut self, rhs: f32) {
        if rhs.abs() <= 1e-12 {
            *self = Self::ZERO;
        } else {
            self.x /= rhs;
            self.y /= rhs;
        }
    }
}

impl Neg for Vec2 {
    type Output = Self;
    #[inline]
    fn neg(self) -> Self {
        Self::new(-self.x, -self.y)
    }
}

#[inline]
pub fn dist(a: Vec2, b: Vec2) -> f32 {
    (a - b).length()
}

#[inline]
pub fn dist_sq(a: Vec2, b: Vec2) -> f32 {
    (a - b).length_squared()
}

#[inline]
pub fn perp(v: Vec2) -> Vec2 {
    v.perp()
}

pub fn round_countdown(seconds: f32) -> f32 {
    let factor = 10_f64.powi(COUNTDOWN_ROUND_DIGITS);
    (((seconds as f64) * factor).round() / factor) as f32
}

pub fn half_up_percent(value: i32, percent: i32) -> i32 {
    ((value as i64 * percent as i64 * 2 + 100) / 200).max(0) as i32
}

pub fn compute_room_radius(view_w: u32, view_h: u32, margin: f32) -> f32 {
    let w = (view_w.max(1)) as f32;
    let h = (view_h.max(1)) as f32;
    let m = margin.clamp(ARENA_MARGIN_MIN, ARENA_MARGIN_MAX);
    let fit_rx = (w * 0.5 * m) / (SQRT_2 * ISO_SCALE_X);
    let fit_ry = (h * 0.5 * m) / (SQRT_2 * ISO_SCALE_Y);
    (fit_rx.min(fit_ry) * WORLD_ARENA_SCALE).clamp(160.0, 2200.0)
}

#[inline]
pub fn to_iso_cam(world: Vec2, cam_world: Vec2, view_w: f32, view_h: f32, shake: Vec2) -> (f32, f32) {
    let rel = world - cam_world;
    let ix = (rel.x - rel.y) * ISO_SCALE_X;
    let iy = (rel.x + rel.y) * ISO_SCALE_Y;
    (ix + view_w * 0.5 + shake.x, iy + view_h * 0.5 + shake.y)
}

#[inline]
pub fn to_iso(world: Vec2, view_w: f32, view_h: f32, shake: Vec2) -> (f32, f32) {
    to_iso_cam(world, Vec2::ZERO, view_w, view_h, shake)
}

#[inline]
pub fn to_iso_vec(world_dir: Vec2) -> Vec2 {
    Vec2::new(
        (world_dir.x - world_dir.y) * ISO_SCALE_X,
        (world_dir.x + world_dir.y) * ISO_SCALE_Y,
    )
    .normalized()
}

#[inline]
pub fn iso_to_world_cam(screen_x: f32, screen_y: f32, cam_world: Vec2, view_w: f32, view_h: f32) -> Vec2 {
    let ix = screen_x - view_w * 0.5;
    let iy = screen_y - view_h * 0.5;
    let x = (ix / ISO_SCALE_X + iy / ISO_SCALE_Y) * 0.5;
    let y = (iy / ISO_SCALE_Y - ix / ISO_SCALE_X) * 0.5;
    Vec2::new(x + cam_world.x, y + cam_world.y)
}

#[inline]
pub fn iso_to_world(screen_x: f32, screen_y: f32, view_w: f32, view_h: f32) -> Vec2 {
    iso_to_world_cam(screen_x, screen_y, Vec2::ZERO, view_w, view_h)
}

/// Unified arena membership matching the exact drawn geometry in `FloorGeometryCache`.
pub fn arena_inside(pos: Vec2, radius: f32, map_type: &str) -> bool {
    match map_type {
        MAP_CIRCLE => pos.length_squared() <= radius * radius,
        MAP_DONUT => {
            let inner = radius * DONUT_INNER_RATIO;
            let d2 = pos.length_squared();
            d2 >= inner * inner && d2 <= radius * radius
        }
        MAP_DIAMOND => pos.x.abs() + pos.y.abs() <= radius * DIAMOND_EXTENT_RATIO,
        MAP_CROSS => {
            let w = radius * CROSS_ARM_RATIO;
            (pos.x.abs() <= w && pos.y.abs() <= radius)
                || (pos.x.abs() <= radius && pos.y.abs() <= w)
        }
        _ => pos.length_squared() <= radius * radius,
    }
}

/// Outward edge normal for ricochet reflection & smooth boundary projection.
pub fn arena_edge_normal(pos: Vec2, radius: f32, map_type: &str) -> Vec2 {
    match map_type {
        MAP_DONUT => {
            let inner = radius * DONUT_INNER_RATIO;
            let outer = radius;
            let len = pos.length();
            if len <= 1e-6 {
                return Vec2::new(1.0, 0.0);
            }
            if (len - inner).abs() < (outer - len).abs() {
                -(pos / len) // inner hole pushes outward
            } else {
                pos / len
            }
        }
        MAP_DIAMOND => {
            let sx = if pos.x >= 0.0 { 1.0 } else { -1.0 };
            let sy = if pos.y >= 0.0 { 1.0 } else { -1.0 };
            Vec2::new(sx, sy).normalized()
        }
        MAP_CROSS => {
            let ax = pos.x.abs();
            let ay = pos.y.abs();
            let w = radius * CROSS_ARM_RATIO;
            if ax > w && ay > w {
                if (ax - w) < (ay - w) {
                    Vec2::new(pos.x.signum(), 0.0)
                } else {
                    Vec2::new(0.0, pos.y.signum())
                }
            } else if ax >= ay {
                Vec2::new(pos.x.signum(), 0.0)
            } else {
                Vec2::new(0.0, pos.y.signum())
            }
        }
        _ => {
            if pos.length_squared() <= 1e-12 {
                Vec2::new(1.0, 0.0)
            } else {
                pos.normalized()
            }
        }
    }
}

fn project_l1_diamond(p: Vec2, limit: f32) -> Vec2 {
    let ax = p.x.abs();
    let ay = p.y.abs();
    if ax + ay <= limit {
        return p;
    }
    let excess = (ax + ay - limit) * 0.5;
    let nx = (ax - excess).max(0.0);
    let ny = (ay - excess).max(0.0);
    let s = nx + ny;
    let (fx, fy) = if s > limit + 1e-6 {
        (nx * limit / s, ny * limit / s)
    } else if nx == 0.0 {
        (0.0, limit.min(ay))
    } else if ny == 0.0 {
        (limit.min(ax), 0.0)
    } else {
        (nx, ny)
    };
    Vec2::new(fx.copysign(p.x), fy.copysign(p.y))
}

/// Closest point projection onto valid arena floor (inset cleanly from perimeter & Donut pit by `pad`).
pub fn clamp_entity_to_map(p: Vec2, radius: f32, pad: f32, map_type: &str) -> Vec2 {
    if radius <= 0.0 {
        return Vec2::ZERO;
    }
    let outer_r = (radius - pad).max(radius * 0.55);
    match map_type {
        MAP_CIRCLE => {
            let l = p.length();
            if l <= outer_r {
                p
            } else {
                p / l * outer_r
            }
        }
        MAP_DONUT => {
            let inner = (radius * DONUT_INNER_RATIO + pad).min(outer_r - 2.0);
            let l = p.length();
            if l <= 1e-6 {
                return Vec2::new(inner, 0.0);
            }
            if l < inner {
                p / l * inner
            } else if l > outer_r {
                p / l * outer_r
            } else {
                p
            }
        }
        MAP_DIAMOND => {
            let limit = ((radius - pad) * DIAMOND_EXTENT_RATIO).max(radius * 0.6);
            project_l1_diamond(p, limit)
        }
        MAP_CROSS => {
            let w = (radius * CROSS_ARM_RATIO - pad).max(radius * 0.25);
            let arm = outer_r;
            let cand_v = Vec2::new(p.x.clamp(-w, w), p.y.clamp(-arm, arm));
            let cand_h = Vec2::new(p.x.clamp(-arm, arm), p.y.clamp(-w, w));
            if dist_sq(p, cand_v) <= dist_sq(p, cand_h) {
                cand_v
            } else {
                cand_h
            }
        }
        _ => {
            let l = p.length();
            if l <= outer_r {
                p
            } else {
                p / l * outer_r
            }
        }
    }
}

/// Resolve the locked floor point for a player Mortar shot. Shared by combat
/// and the renderer so range clamping and aim feedback always agree.
pub fn mortar_landing_target(
    player_pos: Vec2,
    aim_target: Vec2,
    aim_dir: Vec2,
    room_radius: f32,
    map_type: &str,
) -> Vec2 {
    let aim = if aim_dir.length_squared() > 1e-8 {
        aim_dir.normalized()
    } else {
        Vec2::new(1.0, 0.0)
    };
    let muzzle = player_pos + aim * 40.0;
    let floor_target = clamp_entity_to_map(aim_target, room_radius, 30.0, map_type);
    let requested = floor_target - muzzle;
    let direction = if requested.length_squared() > 1e-8 {
        requested.normalized()
    } else {
        aim
    };
    let travel = requested.length().clamp(
        crate::sim::config::PLAYER_MORTAR_MIN_RANGE,
        crate::sim::config::PLAYER_MORTAR_MAX_RANGE,
    );
    clamp_entity_to_map(
        muzzle + direction * travel,
        room_radius,
        30.0,
        map_type,
    )
}

/// Closest point projection onto valid arena floor (exact outer boundary).
pub fn clamp_to_map(p: Vec2, radius: f32, map_type: &str) -> Vec2 {
    clamp_entity_to_map(p, radius, 0.0, map_type)
}

pub fn random_spawn_map_edge(center: Vec2, radius: f32, map_type: &str, rng: &mut SimRng) -> Vec2 {
    match map_type {
        MAP_CIRCLE | MAP_DONUT => {
            let ang = rng.range_f32(0.0, TAU);
            Vec2::new(center.x + ang.cos() * radius, center.y + ang.sin() * radius)
        }
        MAP_DIAMOND => {
            let limit = radius * DIAMOND_EXTENT_RATIO;
            let side = rng.range_i32(0, 3);
            let t = rng.f32();
            let mut x = t * limit;
            let mut y = limit - x;
            match side {
                1 => x = -x,
                2 => y = -y,
                3 => {
                    x = -x;
                    y = -y;
                }
                _ => {}
            }
            Vec2::new(center.x + x, center.y + y)
        }
        MAP_CROSS => {
            let arm = rng.range_i32(0, 3);
            let w = radius * CROSS_ARM_RATIO;
            let p = match arm {
                0 => Vec2::new(rng.range_f32(-w, w), -radius),
                1 => Vec2::new(rng.range_f32(-w, w), radius),
                2 => Vec2::new(-radius, rng.range_f32(-w, w)),
                _ => Vec2::new(radius, rng.range_f32(-w, w)),
            };
            center + p
        }
        _ => center,
    }
}

#[inline]
pub fn point_segment_distance_sq(p: Vec2, a: Vec2, b: Vec2) -> f32 {
    let ab = b - a;
    let ap = p - a;
    let ab_len2 = ab.length_squared();
    if ab_len2 <= 1e-9 {
        return ap.length_squared();
    }
    let t = (ap.dot(ab) / ab_len2).clamp(0.0, 1.0);
    let closest = a + ab * t;
    (p - closest).length_squared()
}

/// Return the first normalized segment time at which a circle is touched.
/// Starting inside the circle is a hit at the segment origin; a zero-length
/// segment outside the circle has no hit.
#[inline]
pub fn segment_circle_first_hit_t(start: Vec2, end: Vec2, center: Vec2, radius: f32) -> Option<f32> {
    let radius = radius.max(0.0);
    let offset = start - center;
    let radius_sq = radius * radius;
    if offset.length_squared() <= radius_sq {
        return Some(0.0);
    }

    let direction = end - start;
    let a = direction.length_squared();
    if a <= 1e-9 {
        return None;
    }

    let b = offset.dot(direction);
    let c = offset.length_squared() - radius_sq;
    let discriminant = b * b - a * c;
    if discriminant < 0.0 {
        return None;
    }

    let t = (-b - discriminant.sqrt()) / a;
    (0.0..=1.0).contains(&t).then_some(t)
}

#[inline]
pub fn point_segment_distance(p: Vec2, a: Vec2, b: Vec2) -> f32 {
    point_segment_distance_sq(p, a, b).sqrt()
}

#[inline]
pub fn map_type_from_index(idx: i32) -> &'static str {
    match idx.rem_euclid(4) {
        0 => MAP_CIRCLE,
        1 => MAP_DONUT,
        2 => MAP_CROSS,
        _ => MAP_DIAMOND,
    }
}

#[inline]
pub fn quadrant_angle(i: usize) -> f32 {
    (i as f32) * FRAC_PI_2
}
