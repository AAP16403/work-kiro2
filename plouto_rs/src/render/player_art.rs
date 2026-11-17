use std::collections::VecDeque;
use std::f32::consts::TAU;

use crate::render::models3d::draw_player_pod;
use crate::render::sdf::{linear_rgba, linear_rgba_f, mix_rgb, SdfBatch};
use crate::sim::math::Vec2;
use crate::sim::skins::{LEGACY_GLOW2, Palette};

pub const DISSOLVE_S: f32 = 0.9;
const PLAYER_ART_SCALE: f32 = 1.34;
const BODY_A: f32 = 16.8;
const BODY_B: f32 = 14.6;
const BOB_AMP: f32 = 1.5;
const BREATH_RATE: f32 = 2.6;
const BREATH_AMP: f32 = 0.03;
const BANK_PX: f32 = 2.2;
const BANK_STIFF: f32 = 60.0;
const GAZE_X: f32 = 1.9;
const GAZE_Y: f32 = 1.5;
const GAZE_STIFF: f32 = 220.0;
const STAGGER_PX: f32 = 3.0;
const STAGGER_STIFF: f32 = 700.0;
const BLINK_PERIOD: f32 = 3.0;
const BLINK_CLOSED_S: f32 = 0.12;
const WORRY_HP_FRAC: f32 = 0.30;
const GHOST_N: usize = 4;
const GHOST_STEP_S: f32 = 0.07;
const GHOST_LIFE_S: f32 = 0.28;
const GHOST_ALPHA: f32 = 0.42;

#[derive(Debug, Clone, Default)]
struct Spring2D {
    pos: Vec2,
    vel: Vec2,
}

impl Spring2D {
    fn step(&mut self, target: Vec2, stiffness: f32, dt: f32) -> Vec2 {
        let dt = dt.clamp(0.0, 0.05);
        if dt <= 0.0 {
            return self.pos;
        }
        let damping = 2.0 * stiffness.sqrt(); // critical damping
        let accel = (target - self.pos) * stiffness - self.vel * damping;
        self.vel += accel * dt;
        self.pos += self.vel * dt;
        self.pos
    }

    fn reset(&mut self) {
        self.pos = Vec2::ZERO;
        self.vel = Vec2::ZERO;
    }
}

#[derive(Debug, Clone)]
struct GhostSnapshot {
    sx: f32,
    sy: f32,
    scale_x: f32,
    scale_y: f32,
    color: [u8; 3],
    born: f32,
}

pub struct PlayerVisualState {
    bank: Spring2D,
    gaze: Spring2D,
    stagger: Spring2D,
    ghosts: VecDeque<GhostSnapshot>,
    last_ghost_t: f32,
    was_dashing: bool,
    was_hit: bool,
    pub dead_elapsed: f32,
    was_dead: bool,
    last_t: Option<f32>,
    hold_aim: Vec2,
    hold_boosting: bool,
    model_yaw: f32,
    model_yaw_velocity: f32,
}

impl Default for PlayerVisualState {
    fn default() -> Self {
        Self::new()
    }
}

impl PlayerVisualState {
    pub fn new() -> Self {
        Self {
            bank: Spring2D::default(),
            gaze: Spring2D::default(),
            stagger: Spring2D::default(),
            ghosts: VecDeque::with_capacity(GHOST_N),
            last_ghost_t: -10.0,
            was_dashing: false,
            was_hit: false,
            dead_elapsed: 0.0,
            was_dead: false,
            last_t: None,
            hold_aim: Vec2::new(1.0, 0.0),
            hold_boosting: false,
            model_yaw: 0.0,
            model_yaw_velocity: 0.0,
        }
    }

    pub fn reset(&mut self) {
        self.bank.reset();
        self.gaze.reset();
        self.stagger.reset();
        self.ghosts.clear();
        self.last_ghost_t = -10.0;
        self.was_dashing = false;
        self.was_hit = false;
        self.dead_elapsed = 0.0;
        self.was_dead = false;
        self.last_t = None;
        self.hold_aim = Vec2::new(1.0, 0.0);
        self.hold_boosting = false;
        self.model_yaw = 0.0;
        self.model_yaw_velocity = 0.0;
    }

    #[inline]
    pub fn death_fade(&self, alive: bool, enable_death_fade: bool) -> f32 {
        if alive {
            1.0
        } else if !enable_death_fade {
            0.0
        } else {
            (1.0 - self.dead_elapsed / DISSOLVE_S).clamp(0.0, 1.0)
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub fn draw(
        &mut self,
        alpha_batch: &mut SdfBatch,
        add_batch: &mut SdfBatch,
        sx: f32,
        sy: f32,
        real_t: f32,
        motion_t: f32,
        move_vel: Vec2,
        aim_dir: Vec2,
        hp_frac: f32,
        alive: bool,
        shield: i32,
        is_dashing: bool,
        dash_dir: Vec2,
        is_boosting: bool,
        laser_active: bool,
        damage_flash: f32,
        invinc_timer: f32,
        use_pod_art: bool,
        enable_death_fade: bool,
        reduce_motion: bool,
        pal: &Palette,
        ship_pal: &Palette,
    ) {
        let dt = match self.last_t {
            Some(prev) => (real_t - prev).clamp(0.0, 0.05),
            None => 0.016,
        };
        self.last_t = Some(real_t);

        let aim = if aim_dir.length_squared() > 1e-6 {
            aim_dir.normalized()
        } else {
            Vec2::new(1.0, 0.0)
        };

        if alive {
            self.dead_elapsed = 0.0;
            self.was_dead = false;
            self.hold_aim = aim;
            self.hold_boosting = is_boosting;
            let target_yaw = aim.y.atan2(aim.x);
            if reduce_motion {
                self.model_yaw = target_yaw;
                self.model_yaw_velocity = 0.0;
            } else {
                let error = (target_yaw - self.model_yaw + std::f32::consts::PI)
                    .rem_euclid(TAU)
                    - std::f32::consts::PI;
                let acceleration = error * 78.0 - self.model_yaw_velocity * 17.6;
                self.model_yaw_velocity += acceleration * dt;
                self.model_yaw = (self.model_yaw + self.model_yaw_velocity * dt).rem_euclid(TAU);
            }
        } else {
            if !self.was_dead {
                self.was_dead = true;
            }
            self.dead_elapsed += dt;
        }

        let fade = self.death_fade(alive, enable_death_fade);
        if fade <= 0.005 {
            return;
        }

        // Legacy retro triangle ship fallback
        if !use_pod_art {
            draw_legacy_ship(
                alpha_batch,
                add_batch,
                sx,
                sy,
                if alive { aim } else { self.hold_aim },
                if alive { is_boosting } else { self.hold_boosting },
                shield,
                laser_active,
                damage_flash,
                invinc_timer,
                motion_t,
                fade,
                ship_pal,
            );
            return;
        }

        // Invincibility flicker
        let flicker_alpha = if alive && invinc_timer > 0.0 && ((real_t * 22.0) as i32) % 2 == 0 {
            0.52
        } else {
            1.0
        };

        // Ground drop shadow
        let body_a = BODY_A * PLAYER_ART_SCALE;
        let body_b = BODY_B * PLAYER_ART_SCALE;
        alpha_batch.ellipse(
            sx,
            sy - 17.5,
            body_a * 1.15 * fade,
            6.5 * fade,
            0.0,
            linear_rgba_f([4, 6, 12], 0.45 * fade, 1.0),
        );

        // Death radial 4-piece dissolve animation matching `player_art.py`
        if !alive {
            let p = (self.dead_elapsed / DISSOLVE_S).clamp(0.0, 1.0);
            if p >= 1.0 {
                return;
            }
            let alpha = (1.0 - p) * (1.0 - p);
            let reach = 26.0 * p;
            let lift = 14.0 * p;
            let shard_r = (3.0 + (1.0 - p) * 2.5).max(1.2);
            let dirs = [(1.0, 0.8), (-1.0, 0.8), (0.85, -0.7), (-0.85, -0.7)];
            for (dx, dy) in dirs {
                let mx = sx + dx * reach;
                let my = sy + dy * reach * 0.7 + lift;
                let c = mix_rgb(pal.body, pal.glow, p * 0.6);
                add_batch.circle(mx, my, shard_r, linear_rgba_f(c, alpha * 0.9, 1.8));
                add_batch.glow(mx, my, shard_r * 3.0, 1.8, linear_rgba_f(pal.glow, alpha * 0.35, 1.4));
            }
            // Fading thruster ember on last living aim
            draw_pod_thruster_glow(add_batch, sx, sy, self.hold_aim, self.hold_boosting, fade, motion_t, pal);
            return;
        }

        // Update spring physics (suppressed cleanly if reduce_motion)
        let speed_mag = move_vel.length().max(1.0);
        let bank_target = if !reduce_motion && move_vel.length() > 10.0 {
            let norm_v = Vec2::new(move_vel.x / speed_mag, move_vel.y / speed_mag);
            let iso_v = crate::sim::math::to_iso_vec(norm_v);
            Vec2::new(iso_v.x * BANK_PX, iso_v.y * BANK_PX * 0.65)
        } else {
            Vec2::ZERO
        };
        let bank_off = if reduce_motion {
            Vec2::ZERO
        } else {
            self.bank.step(bank_target, BANK_STIFF, dt)
        };

        let gaze_target = if reduce_motion {
            Vec2::ZERO
        } else {
            let iso_aim = crate::sim::math::to_iso_vec(aim);
            Vec2::new(iso_aim.x * GAZE_X, iso_aim.y * GAZE_Y)
        };
        let gaze_off = self.gaze.step(gaze_target, GAZE_STIFF, dt);

        let is_hit = damage_flash > 0.0;
        if is_hit && !self.was_hit && !reduce_motion {
            let push_world = if dash_dir.length_squared() > 0.1 {
                -dash_dir.normalized()
            } else {
                Vec2::new(-aim.x, -aim.y)
            };
            let push = crate::sim::math::to_iso_vec(push_world);
            self.stagger.vel += push * (STAGGER_PX * 16.0);
        }
        self.was_hit = is_hit;
        let stagger_off = if reduce_motion {
            Vec2::ZERO
        } else {
            self.stagger.step(Vec2::ZERO, STAGGER_STIFF, dt)
        };

        // Dash ghost trail tracking
        if !reduce_motion && is_dashing && (!self.was_dashing || real_t - self.last_ghost_t >= GHOST_STEP_S) {
            if self.ghosts.len() >= GHOST_N {
                self.ghosts.pop_front();
            }
            self.ghosts.push_back(GhostSnapshot {
                sx: sx + bank_off.x,
                sy: sy + bank_off.y,
                scale_x: 1.18,
                scale_y: 0.85,
                color: pal.trail,
                born: real_t,
            });
            self.last_ghost_t = real_t;
        }
        self.was_dashing = is_dashing;
        while let Some(front) = self.ghosts.front() {
            if real_t - front.born >= GHOST_LIFE_S {
                self.ghosts.pop_front();
            } else {
                break;
            }
        }

        // Draw dash ghosts behind pod
        for g in &self.ghosts {
            let frac = (1.0 - (real_t - g.born) / GHOST_LIFE_S).clamp(0.0, 1.0);
            add_batch.ellipse(
                g.sx,
                g.sy,
                body_a * g.scale_x,
                body_b * g.scale_y,
                0.0,
                linear_rgba_f(g.color, frac * GHOST_ALPHA, 1.5),
            );
        }

        // Hover bob and a restrained breathing scale keep the pod alive between inputs.
        let bob = if reduce_motion {
            0.0
        } else {
            (motion_t * 3.8).sin() * BOB_AMP
        };
        let breath = if reduce_motion {
            0.0
        } else {
            (motion_t * BREATH_RATE).sin() * BREATH_AMP
        };

        let px = sx + bank_off.x + stagger_off.x;
        let py = sy + bob + bank_off.y + stagger_off.y;

        // Render the pod artwork as a real faceted 3D mesh. Its heading follows aim through
        // a damped angular spring, while banking and pitch respond to movement and boost.
        let model_facing = Vec2::new(self.model_yaw.cos(), self.model_yaw.sin());
        let lateral_speed = move_vel.dot(model_facing.perp());
        let roll = if reduce_motion {
            0.0
        } else {
            (-lateral_speed / move_vel.length().max(1.0) * 0.24).clamp(-0.22, 0.22)
        };
        // Keep the face aligned to the model's +X front. Only movement adds pitch,
        // so aim direction controls when the real 3D face turns out of view.
        let pitch_motion = if reduce_motion {
            0.0
        } else if is_dashing {
            0.18
        } else if is_boosting {
            0.12
        } else {
            (move_vel.length() / 320.0 * 0.09).clamp(0.0, 0.09)
        };
        let pitch = pitch_motion;
        let model_body = if is_hit {
            mix_rgb(pal.body, [255, 255, 255], 0.75)
        } else {
            pal.body
        };
        let mut model_palette = *pal;
        model_palette.body = model_body;
        let blink_phase = motion_t.rem_euclid(BLINK_PERIOD);
        let model_scale = PLAYER_ART_SCALE * if is_dashing { 1.06 } else { 1.0 + breath };
        draw_player_pod(
            alpha_batch,
            add_batch,
            [px, py],
            model_facing,
            gaze_off,
            model_scale,
            roll,
            pitch,
            motion_t,
            flicker_alpha,
            !reduce_motion && blink_phase > BLINK_PERIOD - BLINK_CLOSED_S,
            hp_frac <= WORRY_HP_FRAC,
            is_boosting,
            shield,
            laser_active,
            reduce_motion,
            &model_palette,
        );
    }
}

fn draw_pod_thruster_glow(
    add_batch: &mut SdfBatch,
    px: f32,
    py: f32,
    aim: Vec2,
    is_boosting: bool,
    alpha: f32,
    t: f32,
    pal: &Palette,
) {
    let iso_aim = crate::sim::math::to_iso_vec(aim);
    let rear_x = px - iso_aim.x * 13.0;
    let rear_y = py - iso_aim.y * 9.0;
    let col = if is_boosting { [255, 165, 60] } else { pal.glow };
    let pulse = 0.88 + 0.12 * (t * 14.0).sin();
    let r = (if is_boosting { 22.0 } else { 15.0 }) * pulse;
    add_batch.glow(rear_x, rear_y, r, 1.8, linear_rgba_f(col, 0.55 * alpha, 1.8));
}

#[allow(clippy::too_many_arguments)]
fn draw_legacy_ship(
    alpha_batch: &mut SdfBatch,
    add_batch: &mut SdfBatch,
    sx: f32,
    sy: f32,
    aim: Vec2,
    is_boosting: bool,
    shield: i32,
    laser_active: bool,
    damage_flash: f32,
    invinc_timer: f32,
    t: f32,
    fade: f32,
    pal: &Palette,
) {
    let f = if invinc_timer > 0.0 && ((t * 22.0) as i32) % 2 == 0 {
        0.52 * fade
    } else {
        fade
    };
    let fwd = crate::sim::math::to_iso_vec(aim);
    let perp = Vec2::new(-fwd.y, fwd.x);
    let hover = (t * 4.0).sin() * 1.5;
    let cx = sx;
    let cy = sy + hover;

    alpha_batch.ellipse(
        sx,
        sy - 17.0,
        17.0 * fade,
        6.0 * fade,
        0.0,
        linear_rgba_f([4, 6, 12], 0.45 * fade, 1.0),
    );
    alpha_batch.glow(
        cx - fwd.x * 14.0,
        cy - fwd.y * 14.0,
        if is_boosting { 24.0 } else { 16.0 },
        1.8,
        linear_rgba_f(if is_boosting { [255, 165, 65] } else { LEGACY_GLOW2 }, 0.65 * f, 1.8),
    );

    let hull_col = if damage_flash > 0.0 {
        mix_rgb(pal.body, [255, 255, 255], 0.75)
    } else {
        pal.body
    };
    let nose = [cx + fwd.x * 17.0, cy + fwd.y * 17.0];
    let left_w = [cx - fwd.x * 12.0 + perp.x * 12.5, cy - fwd.y * 12.0 + perp.y * 12.5];
    let right_w = [cx - fwd.x * 12.0 - perp.x * 12.5, cy - fwd.y * 12.0 - perp.y * 12.5];
    let tail = [cx - fwd.x * 7.5, cy - fwd.y * 7.5];

    alpha_batch.triangle(nose, left_w, tail, linear_rgba_f(hull_col, f, 1.05));
    alpha_batch.triangle(nose, tail, right_w, linear_rgba_f(mix_rgb(hull_col, pal.accent, 0.25), f, 1.05));
    add_batch.circle(
        cx + fwd.x * 3.0,
        cy + fwd.y * 3.0,
        3.6,
        linear_rgba_f(pal.eye, f, 1.5),
    );

    if laser_active {
        add_batch.ring(cx, cy, 19.0, 19.0, 2.0, linear_rgba_f([255, 110, 255], 0.7 * f, 1.9));
    }
    if shield > 0 {
        alpha_batch.circle(cx, cy, 24.0, linear_rgba_f([80, 200, 255], 0.15 * f, 1.1));
        add_batch.ring(cx, cy, 24.0, 24.0, 2.2, linear_rgba_f([130, 230, 255], 0.8 * f, 1.8));
    }
}

/// Live animated pod-robot preview rendered directly inside Hangar skin cards & menus.
pub fn draw_character_preview(
    alpha_batch: &mut SdfBatch,
    add_batch: &mut SdfBatch,
    cx: f32,
    cy: f32,
    scale: f32,
    t: f32,
    selected: bool,
    locked: bool,
    pal: &Palette,
) {
    let bob = (t * 2.8).sin() * 2.2 * scale;
    let py = cy + bob;
    let tint = |c: [u8; 3]| -> [u8; 3] {
        if locked {
            mix_rgb(c, [24, 30, 44], 0.62)
        } else {
            c
        }
    };

    // Halo under-glow
    let halo_a = if locked {
        18
    } else if selected {
        78
    } else {
        44
    };
    add_batch.glow(
        cx,
        py,
        24.0 * scale,
        1.8,
        linear_rgba(tint(pal.glow), halo_a, if selected { 1.15 } else { 0.95 }),
    );
    alpha_batch.ellipse(
        cx,
        cy - 17.5 * scale,
        15.0 * scale,
        5.0 * scale,
        0.0,
        linear_rgba([4, 8, 16], if locked { 65 } else { 110 }, 1.0),
    );

    let mut preview_palette = *pal;
    if locked {
        preview_palette.body = tint(pal.body);
        preview_palette.accent = tint(pal.accent);
        preview_palette.eye = tint(pal.eye);
        preview_palette.glow = tint(pal.glow);
        preview_palette.trail = tint(pal.trail);
        preview_palette.bullet = tint(pal.bullet);
        preview_palette.cheek = tint(pal.cheek);
    }
    let spin = if locked { 0.0 } else { (t * 0.42).sin() * 0.14 };
    let heading = -std::f32::consts::FRAC_PI_4 + spin;
    let blink = !locked && (t + cx * 0.01).rem_euclid(BLINK_PERIOD) > BLINK_PERIOD - BLINK_CLOSED_S;
    draw_player_pod(
        alpha_batch,
        add_batch,
        [cx, py],
        Vec2::new(heading.cos(), heading.sin()),
        Vec2::ZERO,
        scale,
        if locked { 0.0 } else { (t * 1.6).sin() * 0.035 },
        -0.12,
        t,
        if locked { 0.52 } else { 1.0 },
        blink,
        false,
        false,
        0,
        false,
        locked,
        &preview_palette,
    );
}
