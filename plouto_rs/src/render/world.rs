use std::collections::HashMap;
use std::f32::consts::{FRAC_PI_2, FRAC_PI_4, PI, SQRT_2, TAU};

use crate::render::floor::{FloorGeometryCache, ParallaxStarfield};
use crate::render::models3d::{boss_model_scale, boss_model_visual_scale, enemy_model_scale, ENEMY_MODEL_VISUAL_SCALE};
use crate::render::particles::ParticleSystem;
use crate::render::player_art::PlayerVisualState;
use crate::render::powerup_art::{draw_powerup_pickup, powerup_meta};
use crate::render::sdf::{linear_rgba, linear_rgba_f, mix_rgb, SdfBatch};
use crate::render::text::{AlignX, AlignY, FontId, TextBatch};
use crate::sim::behaviors::{
    SwarmMode, BOMBER_WINDUP_SECONDS, SWARM_SURGE_TELEGRAPH_SECONDS,
    TANK_WINDUP_SECONDS,
};
use crate::sim::bosses::{
    brute_charge_lane, brute_charge_windup_time, eclipse_safe_angle, is_raged,
    trapmaster_spike_position, ECLIPSE_GAP_HALF_WIDTH, TRAPMASTER_SPIKE_RADIUS,
};
use crate::sim::config::{
    enemy_color, elite_affix_color, powerup_color, AFTERBURN_COLOR, AFTERBURN_CORE_OPACITY, AFTERBURN_CORE_RADIUS,
    AFTERBURN_CORE_SHADE, AFTERBURN_FLICKER_DEPTH, AFTERBURN_FLICKER_HZ, AFTERBURN_GLOW_OPACITY,
    BOSS_RADIUS, CHAIN_ARC_COLOR, CHAIN_ARC_CORE_WIDTH, CHAIN_ARC_GLOW_OPACITY,
    CHAIN_ARC_GLOW_WIDTH, CHAIN_ARC_JITTER, CHAIN_ARC_SEGMENTS, CHAIN_COLOR, ECHO_COLOR,
    BOSS_LASER_SWEEP_BASE_DEG, BOSS_LASER_SWEEP_PER_PHASE_DEG,
    EVENT_FLARE_SECTOR_DEG, EVENT_FLARE_SWEEP, EVENT_FLARE_THICKNESS, EVENT_FLARE_WARN,
    EVENT_METEOR_RADIUS, ISO_SCALE_X, ISO_SCALE_Y, REPULSOR_COLOR, SHARD_SHIMMER_DEPTH,
    SHARD_SHIMMER_RATE, SHARD_STREAK_PX, SHARD_WIDTH_PX, SIG_BOMBER_COLOR, SIG_BOMBER_CORE,
    SIG_BOMBER_RING, SIG_BOSS_COLOR, SIG_BOSS_CORE, SIG_BOSS_RING, SIG_GLOW_OPACITY,
    SIG_PULSE_RATE, SIG_RANGED_COLOR, SIG_RANGED_CORE, SIG_RANGED_LENGTH, SIG_RING_PULSE,
    SIG_SPITTER_COLOR, SIG_SPITTER_CORE, SIG_SPITTER_RADIUS, SIG_SPITTER_TRAIL,
    ELITE_MENDER_RADIUS, ELITE_REFLECTOR_COLOR, ELITE_REFLECT_COOLDOWN,
    ELITE_VOLATILE_BLAST_RADIUS, ELITE_WARD_RADIUS,
    SNIPER_AIM_SECONDS, SNIPER_LOCK_SECONDS, TANK_DEATH_BLAST_RADIUS,
};
use crate::sim::drone::{DroneState, DRONE_RANGE};
use crate::sim::enemy::{
    swarm_formation_key, Enemy, EnemySubState, ABYSS_GAZE_TELEGRAPH, SWARMQUEEN_TELEGRAPH,
    TRAPMASTER_TELEGRAPH, WOMB_PULSE_TELEGRAPH,
};
use crate::sim::events::ArenaEvent;
use crate::sim::math::{iso_to_world_cam, mortar_landing_target, to_iso_cam, Vec2};
use crate::sim::powerup::{is_rare_powerup, timed_active};
use crate::sim::projectile::Projectile;
use crate::sim::skins::Palette;
use crate::sim::state::SimState;
use crate::sim::steer::safe_dir;
use crate::sim::weapons::get_weapon_color;

const FLAK_LIFT_PX: f32 = 16.0;
const ENEMY_HEAD: [u8; 3] = [255, 85, 45];
const GOLD_TRAIL: [u8; 3] = [255, 212, 64];
#[derive(Clone)]
struct TrackedEnemy {
    pos: Vec2,
    color: [u8; 3],
    radius: f32,
    is_boss: bool,
}

pub struct WorldRenderer {
    pub stars: ParallaxStarfield,
    pub floor: FloorGeometryCache,
    pub player_art: PlayerVisualState,
    pub particles: ParticleSystem,
    pub cam_world: Vec2,
    prev_player_pos: Vec2,
    prev_drone_pos: Vec2,
    prev_enemy_map: HashMap<u64, TrackedEnemy>,
    last_model_trail_at: HashMap<u64, f32>,
    model_facing: HashMap<u64, Vec2>,
    last_model_turn_at: f32,
    last_player_engine_trail_at: f32,
    rim_pulse: f32,
    last_layout_segment: Option<i32>,
    real_time: f32,
}

impl Default for WorldRenderer {
    fn default() -> Self {
        Self::new()
    }
}

impl WorldRenderer {
    pub fn new() -> Self {
        Self {
            stars: ParallaxStarfield::new(),
            floor: FloorGeometryCache::new(),
            player_art: PlayerVisualState::new(),
            particles: ParticleSystem::new(),
            cam_world: Vec2::ZERO,
            prev_player_pos: Vec2::ZERO,
            prev_drone_pos: Vec2::ZERO,
            prev_enemy_map: HashMap::new(),
            last_model_trail_at: HashMap::new(),
            model_facing: HashMap::new(),
            last_model_turn_at: 0.0,
            last_player_engine_trail_at: -1.0,
            rim_pulse: 0.0,
            last_layout_segment: None,
            real_time: 0.0,
        }
    }

    pub fn reset(&mut self, state: &SimState) {
        self.particles.clear();
        self.player_art.reset();
        self.cam_world = state.player.pos * 0.62;
        self.prev_player_pos = state.player.pos;
        self.prev_drone_pos = state.drone.pos;
        self.prev_enemy_map.clear();
        self.last_model_trail_at.clear();
        self.model_facing.clear();
        self.last_model_turn_at = self.real_time;
        self.last_player_engine_trail_at = -1.0;
        self.rim_pulse = 0.0;
        self.last_layout_segment = Some(state.layout_segment);
    }

    pub fn update_camera(
        &mut self,
        state: &SimState,
        view_w: f32,
        view_h: f32,
        cursor_screen: Option<[f32; 2]>,
        dt: f32,
    ) {
        let look = cursor_screen
            .map(|[mx, my]| {
                let w = iso_to_world_cam(mx, my, self.cam_world, view_w, view_h);
                let d = w - state.player.pos;
                if d.length_squared() > 1e-4 {
                    d.normalized()
                } else {
                    Vec2::ZERO
                }
            })
            .unwrap_or(Vec2::ZERO);

        let (move_dir, move_speed) = if state.player.is_dashing {
            (state.player.dash_direction, state.player.dash_speed)
        } else {
            (state.player.move_vel.normalized(), state.player.move_vel.length())
        };
        let movement_gain = if cursor_screen.is_some() { 0.55 } else { 1.0 };
        let movement_look = if state.runtime.reduce_motion {
            Vec2::ZERO
        } else {
            move_dir * (move_speed * 0.22).clamp(0.0, 58.0) * movement_gain
        };
        let mut target = state.player.pos * 0.62 + look * 48.0 + movement_look;
        let max_cam = (state.room_radius * 0.56).max(80.0);
        let len_sq = target.length_squared();
        if len_sq > max_cam * max_cam {
            target = target * (max_cam / len_sq.sqrt());
        }

        let k = if state.runtime.reduce_motion {
            1.0
        } else {
            1.0 - (-8.5 * dt.clamp(0.0, 0.05)).exp()
        };
        self.cam_world += (target - self.cam_world) * k;
    }

    pub fn capture_prev(&mut self, state: &SimState) {
        self.prev_player_pos = state.player.pos;
        self.prev_drone_pos = state.drone.pos;
    }

    pub fn on_step_post(&mut self, state: &SimState, events: &[crate::sim::state::SimEvent], _view_w: f32, _view_h: f32) {
        let rm = state.runtime.reduce_motion;
        self.particles.handle_sim_events(events, rm);

        // Add restrained engine motes to the newly modeled fighters and pod. They carry no
        // combat effect, and reduced-motion mode uses a sparse, slower plume.
        for enemy in state.enemies.iter().filter(|enemy| {
            matches!(enemy.behavior.as_str(), "chaser" | "bomber") && enemy.vel.length_squared() > 25.0
        }) {
            let cadence = if rm { 0.24 } else { 0.085 };
            if state.time - self.last_model_trail_at.get(&enemy.id).copied().unwrap_or(-1.0) < cadence {
                continue;
            }
            self.last_model_trail_at.insert(enemy.id, state.time);
            let direction = enemy.vel.normalized();
            let rear = enemy.pos - direction * if enemy.behavior == "chaser" { 16.0 } else { 13.0 };
            let color = if enemy.behavior == "chaser" { [80, 210, 255] } else { [255, 142, 58] };
            self.particles.emit(
                rear,
                color,
                if rm { 1 } else { 2 },
                if rm { 14.0 } else { 34.0 },
                if rm { 0.16 } else { 0.24 },
                if rm { 1.4 } else { 2.0 },
                Some(-direction),
                if rm { 0.12 } else { 0.32 },
                true,
            );
        }
        let player_speed = state.player.move_vel.length();
        let player_trail_cadence = if rm { 0.24 } else if state.player.is_boosting { 0.045 } else { 0.12 };
        if !state.player.is_dashing
            && (state.player.is_boosting || player_speed > 70.0)
            && state.time - self.last_player_engine_trail_at >= player_trail_cadence
        {
            self.last_player_engine_trail_at = state.time;
            let aim = state.player.move_vel.normalized();
            let rear = state.player.pos - aim * 15.0;
            let palette = state.run_skin.ship_palette();
            self.particles.emit(
                rear,
                if state.player.is_boosting { [255, 150, 58] } else { palette.trail },
                if rm { 1 } else { 2 },
                if rm { 16.0 } else if state.player.is_boosting { 52.0 } else { 30.0 },
                if rm { 0.18 } else { 0.28 },
                if rm { 1.6 } else { 2.2 },
                Some(-aim),
                if rm { 0.14 } else { 0.42 },
                true,
            );
        }

        if let Some(previous) = self.last_layout_segment {
            if previous != state.layout_segment && state.runtime.enable_rim_pulse && !rm {
                self.rim_pulse = self.rim_pulse.max(0.9);
            }
        }
        self.last_layout_segment = Some(state.layout_segment);

        // Emit enemy dissolve bursts for any tracked enemy missing in the new frame
        let live_ids: std::collections::HashSet<u64> = state.enemies.iter().map(|e| e.id).collect();
        self.last_model_trail_at.retain(|id, _| live_ids.contains(id));
        self.model_facing.retain(|id, _| live_ids.contains(id));
        let mut dropped = Vec::new();
        for (&id, tr) in &self.prev_enemy_map {
            if !live_ids.contains(&id) {
                dropped.push((id, tr.clone()));
            }
        }
        for (id, tr) in dropped {
            self.prev_enemy_map.remove(&id);
            if !rm {
                self.particles.burst_dissolve(
                    tr.pos,
                    tr.color,
                    if tr.is_boss { 16 } else { 9 },
                    tr.radius,
                    if tr.is_boss { 1.35 } else { 1.0 },
                );
            }
        }

        // Update tracked enemy positions for dissolve bursts next frame
        for e in &state.enemies {
            let col = enemy_color(&e.behavior, state.runtime.colorblind_palette);
            self.prev_enemy_map.insert(
                e.id,
                TrackedEnemy {
                    pos: e.pos,
                    color: col,
                    radius: e.radius,
                    is_boss: e.behavior.starts_with("boss_"),
                },
            );
        }

        // Trigger rim pulse when arena shake impulses occur
        if state.runtime.enable_rim_pulse && state.shake > 2.0 {
            self.rim_pulse = self.rim_pulse.max((state.shake / 10.0).clamp(0.25, 1.0));
        }

        // Track player dash afterimages
        let trail_col = state
            .run_skin
            .dash_color()
            .unwrap_or_else(|| state.run_skin.ship_palette().trail);
        self.player_art.reset_hold_check(state);
        self.particles.track_dash(
            state.time,
            state.player.is_dashing,
            state.player.pos,
            state.player.dash_direction,
            trail_col,
            state.runtime.enable_dash_afterimage,
            rm,
        );
    }

    pub fn tick_visual_dt(&mut self, dt: f32) {
        self.real_time += dt;
        self.particles.tick(dt);
        self.rim_pulse = (self.rim_pulse - dt * 2.4).max(0.0);
    }

    #[allow(clippy::too_many_arguments)]
    pub fn draw_menu_backdrop(
        &mut self,
        alpha_batch: &mut SdfBatch,
        add_batch: &mut SdfBatch,
        view_w: f32,
        view_h: f32,
        dt: f32,
        reduce_motion: bool,
    ) {
        self.real_time += dt;
        let t = if reduce_motion { 0.0 } else { self.real_time };
        self.stars.draw(
            alpha_batch,
            add_batch,
            view_w,
            view_h,
            t,
            None,
            0.25,
            true,
        );
    }

    #[allow(clippy::too_many_arguments)]
    pub fn draw_world(
        &mut self,
        state: &SimState,
        alpha: f32,
        view_w: f32,
        view_h: f32,
        aim_dir: Vec2,
        cursor_screen: Option<[f32; 2]>,
        show_reticle: bool,
        world_alpha: &mut SdfBatch,
        world_add: &mut SdfBatch,
        ui_alpha: &mut SdfBatch,
        ui_text: &mut TextBatch,
        ui_scale: f32,
    ) -> WorldPostState {
        let rm = state.runtime.reduce_motion;
        let motion_t = if rm { 0.0 } else { state.time };
        let interp = alpha.clamp(0.0, 1.0);
        let model_turn_dt = (self.real_time - self.last_model_turn_at).clamp(0.0, 0.05);
        self.last_model_turn_at = self.real_time;

        // Compute deterministic shake offset for this render instant
        let shake_amp = state.shake * state.runtime.shake_scale;
        let shake = if shake_amp > 0.05 && !rm {
            let sx = (self.real_time * 47.0).sin() * shake_amp;
            let sy = (self.real_time * 59.0 + 1.3).cos() * shake_amp * 0.7;
            Vec2::new(sx, sy)
        } else {
            Vec2::ZERO
        };

        let player_pos = lerp_v2(self.prev_player_pos, state.player.pos, interp);
        let boss_alive = state.enemies.iter().any(|e| e.behavior.starts_with("boss_") && !e.is_dead);
        let combat_intensity = ((state.enemies.len() as f32 / 14.0) + if boss_alive { 0.35 } else { 0.0 }).clamp(0.0, 1.0);

        let cam = self.cam_world;
        // 1. Background & Starfield
        self.stars.draw(
            world_alpha,
            world_add,
            view_w,
            view_h,
            motion_t,
            Some(cam),
            combat_intensity,
            state.runtime.enable_parallax_stars,
        );

        // 2. Arena Floor
        let floor_segment_seed = state.layout_seed
            ^ (state.layout_segment.max(0) as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15);
        self.floor.draw_cam(
            world_alpha,
            world_add,
            &state.map_type,
            state.layout_segment,
            state.room_radius,
            floor_segment_seed,
            cam,
            view_w,
            view_h,
            shake,
            motion_t,
            self.rim_pulse,
        );

        // 3. Arena Event Visuals (`NebulaCloud` / `MeteorShower` / `SolarFlare`)
        if let Some(ev) = &state.arena_event {
            draw_arena_event(
                ev,
                state.room_radius,
                cam,
                view_w,
                view_h,
                shake,
                motion_t,
                world_alpha,
                world_add,
            );
        }

        // Show the exact locked Mortar landing point and blast radius while
        // aiming. The simulation uses the same target resolver on fire.
        if show_reticle && state.player.current_weapon.projectile_type == "mortar" {
            let aim_target = cursor_screen
                .map(|[mx, my]| iso_to_world_cam(mx, my, cam, view_w, view_h))
                .unwrap_or_else(|| player_pos + aim_dir.normalized() * 360.0);
            let landing = mortar_landing_target(
                player_pos,
                aim_target,
                aim_dir,
                state.room_radius,
                &state.map_type,
            );
            let (lx, ly) = to_iso_cam(landing, cam, view_w, view_h, shake);
            let radius = crate::sim::config::PLAYER_MORTAR_BLAST_RADIUS
                * SQRT_2
                * ISO_SCALE_X;
            let aspect = ISO_SCALE_Y / ISO_SCALE_X;
            world_alpha.ellipse(
                lx,
                ly,
                radius,
                radius * aspect,
                0.0,
                linear_rgba_f([255, 116, 52], 0.018, 1.0),
            );
            world_add.ring(
                lx,
                ly,
                radius,
                radius * aspect,
                1.35,
                linear_rgba_f([255, 132, 62], 0.28, 1.15),
            );
            world_add.circle(lx, ly, 3.4, linear_rgba_f([255, 226, 175], 0.76, 1.25));
            world_add.line(lx - 8.0, ly, lx + 8.0, ly, 1.2, linear_rgba_f([255, 226, 175], 0.62, 1.1));
            world_add.line(lx, ly - 4.5, lx, ly + 4.5, 1.2, linear_rgba_f([255, 226, 175], 0.62, 1.1));
        }

        // 4. Afterburn Fire Trail
        if state.runtime.enable_afterburn && !state.afterburn.segments.is_empty() {
            let trail_col = state
                .run_skin
                .dash_color()
                .unwrap_or(AFTERBURN_COLOR);
            let core_col = mix_rgb(trail_col, [255, 255, 255], AFTERBURN_CORE_SHADE);
            let flicker = if rm {
                1.0
            } else {
                1.0 - AFTERBURN_FLICKER_DEPTH * (0.5 + 0.5 * (motion_t * TAU * AFTERBURN_FLICKER_HZ).sin())
            };
            for (idx, seg) in state.afterburn.segments.iter().enumerate() {
                let life_left = (1.0 - (state.time - seg.born_at) / seg.ttl.max(0.01)).clamp(0.0, 1.0);
                if life_left <= 0.01 {
                    continue;
                }
                let (sx, sy) = to_iso_cam(seg.pos, cam, view_w, view_h, shake);
                let phase_f = 0.88 + 0.12 * (idx as f32 * 0.9 + motion_t * 10.0).sin();
                let r = AFTERBURN_CORE_RADIUS * (0.55 + 0.45 * life_left) * phase_f;
                world_add.glow(
                    sx,
                    sy,
                    r * 2.2,
                    1.8,
                    linear_rgba_f(trail_col, (AFTERBURN_GLOW_OPACITY as f32 / 255.0) * life_left * flicker, 1.45),
                );
                world_add.ellipse(
                    sx,
                    sy,
                    r,
                    r * 0.62,
                    0.0,
                    linear_rgba_f(core_col, (AFTERBURN_CORE_OPACITY as f32 / 255.0) * life_left * flicker, 1.8),
                );
            }
        }

        // 5. Repulsor & Echo Expanding Shockwave Rings
        for rr in &state.repulsor.rings {
            let p = ((state.time - rr.started_at) / rr.ttl.max(0.01)).clamp(0.0, 1.0);
            let (sx, sy) = to_iso_cam(rr.pos, cam, view_w, view_h, shake);
            let rx = (220.0 * (0.15 + 0.85 * p)) * SQRT_2 * ISO_SCALE_X;
            let ry = rx * (ISO_SCALE_Y / ISO_SCALE_X);
            world_add.ring(sx, sy, rx, ry, 4.0 * (1.0 - p) + 1.2, linear_rgba_f(REPULSOR_COLOR, 1.0 - p, 1.9));
        }
        for er in &state.echo_rings {
            let p = ((state.time - er.started_at) / er.ttl.max(0.01)).clamp(0.0, 1.0);
            let (sx, sy) = to_iso_cam(er.pos, cam, view_w, view_h, shake);
            let rx = (34.0 * (0.25 + 0.75 * p)) * SQRT_2 * ISO_SCALE_X;
            let ry = rx * (ISO_SCALE_Y / ISO_SCALE_X);
            world_add.ring(sx, sy, rx, ry, 2.5 * (1.0 - p) + 0.8, linear_rgba_f(ECHO_COLOR, (1.0 - p) * 0.9, 1.8));
        }

        // 6. Traps
        for tr in &state.traps {
            let (sx, sy) = to_iso_cam(tr.pos, cam, view_w, view_h, shake);
            let tr_clock = if rm { 0.0 } else { tr.t };
            let pulse = 0.6 + 0.4 * (tr_clock * 16.0).sin();
            match tr.kind.as_str() {
                "slam" | "slam_warn" | "womb_pulse" | "womb_warn" | "meteor" => {
                    if matches!(tr.kind.as_str(), "slam" | "womb_pulse") && tr.t < tr.armed_delay {
                        continue;
                    }
                    if matches!(tr.kind.as_str(), "slam_warn" | "womb_warn") && tr.t >= tr.armed_delay {
                        continue;
                    }
                    let (tint, core_tint) = match tr.kind.as_str() {
                        "womb_warn" => ([150, 110, 255], [235, 215, 255]),
                        "womb_pulse" => ([220, 85, 225], [255, 215, 250]),
                        "meteor" => ([255, 150, 60], [255, 240, 200]),
                        _ => ([255, 80, 80], [255, 220, 200]),
                    };
                    let rx = tr.radius * SQRT_2 * ISO_SCALE_X;
                    let ry = rx * (ISO_SCALE_Y / ISO_SCALE_X);
                    let live = tr.t >= tr.armed_delay;
                    let base_alpha = if tr.kind == "meteor" && live {
                        190.0 / 255.0
                    } else if matches!(tr.kind.as_str(), "slam" | "womb_pulse") {
                        0.26
                    } else {
                        (40.0 + 55.0 * pulse) / 255.0
                    };
                    world_alpha.ellipse(sx, sy, rx, ry, 0.0, linear_rgba_f(tint, base_alpha, 1.05));
                    world_add.ring(
                        sx,
                        sy,
                        rx * 1.03,
                        ry * 1.03,
                        3.2,
                        linear_rgba_f([255, 255, 255], 0.45 + 0.45 * pulse, 1.7),
                    );
                    world_add.circle(sx, sy, (tr.radius * 0.22).max(8.0), linear_rgba_f(core_tint, 0.78, 1.6));
                }
                "mine" => {
                    let armed = tr.t >= tr.armed_delay;
                    let col = if armed { [255, 78, 92] } else { [255, 151, 78] };
                    let pulse_amt = if rm { 0.0 } else { pulse };
                    let rx = tr.radius * SQRT_2 * ISO_SCALE_X;
                    let ry = rx * (ISO_SCALE_Y / ISO_SCALE_X);
                    let expand = 1.0 + pulse_amt * if armed { 0.07 } else { 0.035 };
                    world_alpha.ellipse(
                        sx,
                        sy,
                        rx * expand,
                        ry * expand,
                        0.0,
                        linear_rgba_f(col, if armed { 0.2 } else { 0.1 }, 1.0),
                    );
                    world_add.ring(
                        sx,
                        sy,
                        rx * expand,
                        ry * expand,
                        if armed { 3.0 } else { 2.2 },
                        linear_rgba_f(col, if armed { 0.74 + pulse_amt * 0.18 } else { 0.48 }, 1.6),
                    );
                    world_add.ellipse(
                        sx,
                        sy,
                        rx * 0.28,
                        ry * 0.28,
                        0.0,
                        linear_rgba_f(if armed { [255, 228, 194] } else { [255, 210, 170] }, if armed { 0.92 } else { 0.7 }, 1.8),
                    );
                    for side in [-1.0_f32, 1.0] {
                        for cross in [-1.0_f32, 1.0] {
                            world_add.circle(
                                sx + side * rx * 0.56,
                                sy + cross * ry * 0.56,
                                2.4,
                                linear_rgba_f(col, if armed { 0.9 } else { 0.65 }, 1.5),
                            );
                        }
                    }
                    if armed {
                        world_add.ring(sx, sy, rx * 0.72, ry * 0.72, 1.5, linear_rgba_f([255, 224, 194], 0.42 + pulse_amt * 0.25, 1.4));
                    }
                }
                _ => {
                    let armed = tr.t >= tr.armed_delay;
                    let base_op = if armed { 95 } else { 42 };
                    let core_op = if armed { 210 } else { 125 };
                    world_alpha.circle(sx, sy, tr.radius, linear_rgba([220, 120, 60], base_op, 1.0));
                    world_add.circle(sx, sy, (tr.radius * 0.28).max(6.0), linear_rgba([255, 220, 180], core_op, 1.4));
                    if armed {
                        let arm = tr.radius * 0.75;
                        world_alpha.line(sx - arm, sy - 2.0, sx + arm, sy + 2.0, 2.8, linear_rgba([255, 210, 170], 220, 1.2));
                        world_alpha.line(sx - 2.0, sy - arm, sx + 2.0, sy + arm, 2.8, linear_rgba([255, 210, 170], 220, 1.2));
                    }
                }
            }
        }

        // 7. Player Vortex Swirl ring
        if timed_active(state.player.vortex_until, state.time) {
            let (px, py) = to_iso_cam(player_pos, cam, view_w, view_h, shake);
            let rx = state.player.vortex_radius * SQRT_2 * ISO_SCALE_X;
            let ry = rx * (ISO_SCALE_Y / ISO_SCALE_X);
            world_add.ring(px, py, rx, ry, 2.4, linear_rgba_f([180, 130, 255], 0.45, 1.55));
            world_add.arc_aspect(
                px,
                py,
                rx * 0.82,
                2.5,
                motion_t * 3.8,
                2.2,
                ISO_SCALE_Y / ISO_SCALE_X,
                linear_rgba_f([210, 175, 255], 0.65, 1.8),
            );
        }

        // 8. Depth-sorted Actors: Enemies + Player + Drone
        let warden_positions: Vec<(u64, Vec2)> = state
            .enemies
            .iter()
            .filter(|e| {
                !e.is_dead && e.hp > 0 && e.is_elite && e.elite_affix == "warden"
            })
            .map(|e| (e.id, lerp_v2(e.prev_pos, e.pos, interp)))
            .collect();
        let mut draw_order: Vec<(f32, usize)> = state
            .enemies
            .iter()
            .enumerate()
            .filter(|(_, e)| !e.is_dead)
            .map(|(i, e)| {
                let p = lerp_v2(e.prev_pos, e.pos, interp);
                let (_, sy) = to_iso_cam(p, cam, view_w, view_h, Vec2::ZERO);
                (sy, i)
            })
            .collect();
        // Top of screen (larger sy) draws first -> bottom (smaller sy) draws on top!
        draw_order.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));

        let (_, player_raw_sy) = to_iso_cam(player_pos, cam, view_w, view_h, Vec2::ZERO);
        let mut player_drawn = false;

        let pal = state.run_skin.palette;
        let ship_pal = state.run_skin.ship_palette();
        let hp_frac = state.player.hp as f32 / state.player.max_hp.max(1) as f32;
        let player_alive = state.player.hp > 0 && !state.game_over;

        for (esy, idx) in draw_order {
            if !player_drawn && player_raw_sy >= esy {
                let (psx, psy) = to_iso_cam(player_pos, cam, view_w, view_h, shake);
                self.player_art.draw(
                    world_alpha,
                    world_add,
                    psx,
                    psy,
                    self.real_time,
                    motion_t,
                    state.player.move_vel,
                    aim_dir,
                    hp_frac,
                    player_alive,
                    state.player.shield,
                    state.player.is_dashing,
                    state.player.dash_direction,
                    state.player.is_boosting,
                    timed_active(state.player.laser_until, state.time),
                    state.player.damage_flash_timer,
                    state.player.invincibility_timer,
                    state.runtime.use_player_art,
                    state.runtime.enable_death_fade,
                    rm,
                    &pal,
                    &ship_pal,
                );
                if state.drone.active {
                    draw_drone(&state.drone, self.prev_drone_pos, interp, motion_t, cam, view_w, view_h, shake, world_alpha, world_add);
                }
                player_drawn = true;
            }
            let e = &state.enemies[idx];
            draw_enemy(
                e,
                state,
                &warden_positions,
                interp,
                player_pos,
                cam,
                view_w,
                view_h,
                shake,
                rm,
                &mut self.model_facing,
                model_turn_dt,
                world_alpha,
                world_add,
            );
        }

        if !player_drawn {
            let (psx, psy) = to_iso_cam(player_pos, cam, view_w, view_h, shake);
            self.player_art.draw(
                world_alpha,
                world_add,
                psx,
                psy,
                self.real_time,
                motion_t,
                state.player.move_vel,
                aim_dir,
                hp_frac,
                player_alive,
                state.player.shield,
                state.player.is_dashing,
                state.player.dash_direction,
                state.player.is_boosting,
                timed_active(state.player.laser_until, state.time),
                state.player.damage_flash_timer,
                state.player.invincibility_timer,
                state.runtime.use_player_art,
                state.runtime.enable_death_fade,
                rm,
                &pal,
                &ship_pal,
            );
            if state.drone.active {
                draw_drone(&state.drone, self.prev_drone_pos, interp, motion_t, cam, view_w, view_h, shake, world_alpha, world_add);
            }
        }

        // 9. PowerUps (17 kinds + bespoke geometric art)
        for pu in &state.powerups {
            draw_powerup(
                pu,
                player_pos,
                cam,
                state.runtime.enable_powerup_edges,
                state.runtime.enable_glow,
                motion_t,
                view_w,
                view_h,
                shake,
                world_alpha,
                world_add,
                ui_text,
                ui_scale,
            );
        }

        // 10. Projectiles & Shards
        let shot_pal = state.run_skin.shot_palette();
        for proj in &state.projectiles {
            draw_projectile(
                proj,
                interp,
                motion_t,
                state.runtime.enable_bullet_signatures,
                state.runtime.enable_glow,
                shot_pal.as_ref(),
                player_pos,
                cam,
                view_w,
                view_h,
                shake,
                world_alpha,
                world_add,
            );
        }

        for sh in &state.shards.shards {
            let frac = (sh.ttl / sh.max_ttl.max(0.01)).clamp(0.0, 1.0);
            let shim = if rm {
                1.0
            } else {
                1.0 - SHARD_SHIMMER_DEPTH * (0.5 + 0.5 * (motion_t * SHARD_SHIMMER_RATE + sh.pos.x * 0.1).sin())
            };
            let (sx, sy) = to_iso_cam(sh.pos, cam, view_w, view_h, shake);
            let dir = if sh.vel.length_squared() > 1e-6 {
                sh.vel.normalized()
            } else {
                Vec2::new(1.0, 0.0)
            };
            let tail = Vec2::new(sx - dir.x * SHARD_STREAK_PX * frac, sy - dir.y * SHARD_STREAK_PX * 0.5 * frac);
            world_add.line(
                tail.x,
                tail.y,
                sx,
                sy,
                SHARD_WIDTH_PX * 0.5 * frac.max(0.35),
                linear_rgba_f(sh.color, frac * shim, 2.0),
            );
            world_add.circle(sx, sy, 2.2, linear_rgba_f([255, 255, 255], frac, 2.2));
        }

        // 11. Chain Lightning Arcs, Lasers & Thunder
        for arc in &state.chain.arcs {
            let age = state.time - arc.started_at;
            let frac = (1.0 - age / arc.ttl.max(0.01)).clamp(0.0, 1.0);
            if frac <= 0.0 {
                continue;
            }
            let (x0, y0) = to_iso_cam(arc.a, cam, view_w, view_h, shake);
            let (x1, y1) = to_iso_cam(arc.b, cam, view_w, view_h, shake);
            let dx = x1 - x0;
            let dy = y1 - y0;
            let len = dx.hypot(dy).max(1.0);
            let nx = -dy / len;
            let ny = dx / len;
            let mut prev = [x0, y0];
            let flicker_slot = (state.time / 0.05) as u32;
            for seg_i in 1..=CHAIN_ARC_SEGMENTS {
                let t_seg = seg_i as f32 / CHAIN_ARC_SEGMENTS as f32;
                let bx = x0 + dx * t_seg;
                let by = y0 + dy * t_seg;
                let jitter = if seg_i == CHAIN_ARC_SEGMENTS {
                    0.0
                } else {
                    let h = hash_u32(arc.seed ^ (seg_i as u32).wrapping_mul(0x9E37_79B9) ^ flicker_slot);
                    (h * 2.0 - 1.0) * CHAIN_ARC_JITTER
                };
                let cur = [bx + nx * jitter, by + ny * jitter];
                world_add.line(
                    prev[0],
                    prev[1],
                    cur[0],
                    cur[1],
                    CHAIN_ARC_GLOW_WIDTH,
                    linear_rgba_f(CHAIN_COLOR, (CHAIN_ARC_GLOW_OPACITY as f32 / 255.0) * frac, 1.8),
                );
                world_add.line(
                    prev[0],
                    prev[1],
                    cur[0],
                    cur[1],
                    CHAIN_ARC_CORE_WIDTH,
                    linear_rgba_f(CHAIN_ARC_COLOR, frac, 2.5),
                );
                prev = cur;
            }
        }

        for lb in &state.lasers {
            if lb.owner == "telegraph"
                && state.enemies.iter().any(|e| {
                    !e.is_dead
                        && e.hp > 0
                        && e.behavior == "spitter"
                        && e.ai.sub_state == EnemySubState::SpitterWindup
                        && e.ai.telegraph_beam_id == Some(lb.id)
                })
            {
                continue;
            }
            let (x1, y1) = to_iso_cam(lb.start, cam, view_w, view_h, shake);
            let (x2, y2) = to_iso_cam(lb.end, cam, view_w, view_h, shake);
            if lb.t < lb.warn {
                let prog = (lb.t / lb.warn.max(0.01)).clamp(0.0, 1.0);
                let (alpha_l, alpha_c) = if lb.owner == "telegraph" {
                    if lb.color == [255, 112, 165] {
                        (0.64 + 0.24 * prog, 0.44 + 0.24 * prog)
                    } else {
                        (0.35 + 0.20 * prog, 0.20 + 0.12 * prog)
                    }
                } else {
                    (0.48, 0.32)
                };
                world_add.line(x1, y1, x2, y2, lb.thickness * 0.65, linear_rgba_f(lb.color, alpha_l, 1.4));
                world_add.line(x1, y1, x2, y2, (lb.thickness * 0.25).max(1.5), linear_rgba_f([255, 255, 255], alpha_c, 1.6));
            } else {
                world_add.line(x1, y1, x2, y2, lb.thickness * 1.55, linear_rgba_f(lb.color, 0.42, 2.0));
                world_add.line(x1, y1, x2, y2, lb.thickness, linear_rgba_f(lb.color, 0.85, 2.4));
                world_add.line(x1, y1, x2, y2, (lb.thickness * 0.36).max(2.2), linear_rgba_f([255, 255, 255], 0.92, 2.8));
            }
        }

        for th in &state.thunders {
            let (x1, y1) = to_iso_cam(th.start, cam, view_w, view_h, shake);
            let (x2, y2) = to_iso_cam(th.end, cam, view_w, view_h, shake);
            if th.t < th.warn {
                world_add.line(x1, y1, x2, y2, th.thickness * 0.75, linear_rgba_f(th.color, 0.44, 1.4));
                world_add.line(x1, y1, x2, y2, (th.thickness * 0.25).max(1.5), linear_rgba_f([255, 255, 255], 0.24, 1.5));
            } else {
                let flk = 0.6 + 0.4 * (motion_t * 42.0).sin().abs();
                world_add.line(x1, y1, x2, y2, th.thickness * 1.4, linear_rgba_f(th.color, 0.65 * flk, 2.3));
                world_add.line(x1, y1, x2, y2, (th.thickness * 0.42).max(2.5), linear_rgba_f([255, 255, 255], 0.92 * flk, 2.9));
            }
        }

        // 12. Particles, Motes, Dash Afterimages
        self.particles.draw_world(world_add, state.time, cam, view_w, view_h, shake);

        // 13. Damage Popups (on crisp non-bloomed overlay pass!)
        self.particles.draw_popups(ui_text, ui_scale, cam, view_w, view_h, shake);

        // 13b. Offscreen Threat & Rare Pickup Chevrons
        draw_offscreen_indicators(state, interp, cam, view_w, view_h, shake, motion_t, ui_alpha, ui_text, ui_scale);

        // 14. Custom Aim Reticle (only during live gameplay!)
        if show_reticle {
            if let Some([mx, my]) = cursor_screen {
                let r_col = get_weapon_color(&state.player.current_weapon.projectile_type);
                let bloom_pad = state.player.recoil * 0.45 + if state.auto_shoot { 0.0 } else { 2.5 };
                let r = 10.5 + bloom_pad;
                let tick = 5.5;
                ui_alpha.ring(mx, my, r, r, 1.7, linear_rgba_f(r_col, 0.85, 1.0));
                ui_alpha.line(mx - r - tick, my, mx - r + 2.0, my, 1.8, linear_rgba_f([235, 245, 255], 0.9, 1.0));
                ui_alpha.line(mx + r - 2.0, my, mx + r + tick, my, 1.8, linear_rgba_f([235, 245, 255], 0.9, 1.0));
                ui_alpha.line(mx, my - r - tick, mx, my - r + 2.0, 1.8, linear_rgba_f([235, 245, 255], 0.9, 1.0));
                ui_alpha.line(mx, my + r - 2.0, mx, my + r + tick, 1.8, linear_rgba_f([235, 245, 255], 0.9, 1.0));
                ui_alpha.circle(mx, my, 2.2, linear_rgba([255, 255, 255], 235, 1.0));
            }
        }

        // Low-HP danger metric
        let danger = if hp_frac < 0.35 && player_alive {
            let pulse = 0.65 + 0.35 * (motion_t * 6.0).sin();
            ((0.35 - hp_frac) / 0.35).clamp(0.0, 1.0) * pulse
        } else {
            0.0
        };

        WorldPostState {
            combat_intensity,
            low_hp_danger: danger,
            boss_active: if boss_alive { 1.0 } else { 0.0 },
        }
    }
}

pub struct WorldPostState {
    pub combat_intensity: f32,
    pub low_hp_danger: f32,
    pub boss_active: f32,
}

impl PlayerVisualState {
    fn reset_hold_check(&mut self, _state: &SimState) {
        // Nothing needed; dead clock resets when alive in draw()
    }
}

#[inline]
fn lerp_v2(a: Vec2, b: Vec2, t: f32) -> Vec2 {
    Vec2::new(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t)
}

#[inline]
fn hash_u32(mut x: u32) -> f32 {
    x ^= x >> 16;
    x = x.wrapping_mul(0x7feb_352d);
    x ^= x >> 15;
    x = x.wrapping_mul(0x846c_a68b);
    x ^= x >> 16;
    (x & 0xFFFF) as f32 / 65535.0
}

#[allow(clippy::too_many_arguments)]
fn draw_arena_event(
    ev: &ArenaEvent,
    room_radius: f32,
    cam_world: Vec2,
    view_w: f32,
    view_h: f32,
    shake: Vec2,
    t: f32,
    alpha_batch: &mut SdfBatch,
    add_batch: &mut SdfBatch,
) {
    match ev {
        ArenaEvent::MeteorShower(ms) => {
            for z in &ms.zones {
                if z.hit_done && z.live_left <= 0.0 {
                    continue;
                }
                if ms.elapsed < z.delay {
                    continue;
                }
                let (sx, sy) = to_iso_cam(z.pos, cam_world, view_w, view_h, shake);
                let rx = EVENT_METEOR_RADIUS * SQRT_2 * ISO_SCALE_X;
                let ry = rx * (ISO_SCALE_Y / ISO_SCALE_X);
                let pulse = 0.6 + 0.4 * (t * 16.0).sin();
                let live = z.hit_done && z.live_left > 0.0;
                if live {
                    alpha_batch.ellipse(sx, sy, rx, ry, 0.0, linear_rgba([255, 150, 60], 195, 1.3));
                    add_batch.ring(sx, sy, rx, ry, 4.0, linear_rgba([255, 240, 195], 235, 2.1));
                } else {
                    let frac = (z.elapsed / 1.5_f32).clamp(0.0, 1.0);
                    alpha_batch.ellipse(sx, sy, rx, ry, 0.0, linear_rgba([255, 145, 55], (42.0 + 44.0 * pulse) as u8, 1.05));
                    alpha_batch.ellipse(sx, sy, rx * frac, ry * frac, 0.0, linear_rgba([255, 190, 95], 70, 1.2));
                    add_batch.ring(sx, sy, rx, ry, 3.0, linear_rgba([255, 210, 130], (100.0 + 80.0 * pulse) as u8, 1.5));
                }
            }
        }
        ArenaEvent::SolarFlare(sf) => {
            let (cx, cy) = to_iso_cam(Vec2::ZERO, cam_world, view_w, view_h, shake);
            let r_scr = room_radius.min(sf.beam_length) * SQRT_2 * ISO_SCALE_X;
            let iso_aspect = ISO_SCALE_Y / ISO_SCALE_X;
            let sweep_rad = (sf.sector_rad).max(EVENT_FLARE_SECTOR_DEG.to_radians());

            if sf.elapsed < EVENT_FLARE_WARN {
                let pulse = 0.55 + 0.45 * (t * 10.0).sin();
                let start = if sf.sweep_dir >= 0.0 {
                    sf.start_angle
                } else {
                    sf.start_angle - sweep_rad
                };
                alpha_batch.sector(
                    cx,
                    cy,
                    r_scr,
                    start,
                    sweep_rad,
                    iso_aspect,
                    linear_rgba_f([255, 175, 55], 0.14 + 0.10 * pulse, 1.1),
                );
                add_batch.arc_aspect(
                    cx,
                    cy,
                    r_scr,
                    3.0,
                    start,
                    sweep_rad,
                    iso_aspect,
                    linear_rgba_f([255, 215, 120], 0.45 + 0.35 * pulse, 1.6),
                );
            } else if sf.elapsed < EVENT_FLARE_WARN + EVENT_FLARE_SWEEP {
                let u = ((sf.elapsed - EVENT_FLARE_WARN) / EVENT_FLARE_SWEEP).clamp(0.0, 1.0);
                let ang = sf.start_angle + sf.sweep_dir * sweep_rad * u;
                let end_world = Vec2::new(ang.cos(), ang.sin()) * sf.beam_length;
                let (ex, ey) = to_iso_cam(end_world, cam_world, view_w, view_h, shake);
                add_batch.line(cx, cy, ex, ey, EVENT_FLARE_THICKNESS * 2.2, linear_rgba_f([255, 145, 40], 0.55, 2.0));
                add_batch.line(cx, cy, ex, ey, EVENT_FLARE_THICKNESS * 1.1, linear_rgba_f([255, 235, 175], 0.95, 2.7));
            }
        }
        ArenaEvent::NebulaCloud(nc) => {
            let (sx, sy) = to_iso_cam(nc.pos, cam_world, view_w, view_h, shake);
            let rx = nc.radius * SQRT_2 * ISO_SCALE_X;
            let ry = rx * (ISO_SCALE_Y / ISO_SCALE_X);
            let aspect = ISO_SCALE_Y / ISO_SCALE_X;
            let pulse = 0.75 + 0.25 * (t * 2.4).sin();
            if nc.active {
                alpha_batch.ellipse(sx, sy, rx, ry, 0.0, linear_rgba_f([90, 65, 185], 0.22 * pulse, 1.1));
                add_batch.ellipse_glow(sx, sy, rx * 0.95, ry * 0.95, 1.6, linear_rgba_f([135, 105, 255], 0.25 * pulse, 1.4));
                add_batch.ring(sx, sy, rx, ry, 2.6, linear_rgba_f([165, 140, 255], 0.65, 1.7));
                add_batch.arc_aspect(sx, sy, rx * 0.72, 2.5, t * 1.4, 2.3, aspect, linear_rgba_f([195, 170, 255], 0.55, 1.7));
            } else {
                alpha_batch.ellipse(sx, sy, rx, ry, 0.0, linear_rgba_f([95, 75, 195], 0.11 * pulse, 1.0));
                add_batch.ring(sx, sy, rx, ry, 2.0, linear_rgba_f([160, 140, 255], 0.42 * pulse, 1.3));
            }
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn draw_drone(
    drone: &DroneState,
    prev_pos: Vec2,
    interp: f32,
    motion_t: f32,
    cam_world: Vec2,
    view_w: f32,
    view_h: f32,
    shake: Vec2,
    alpha_batch: &mut SdfBatch,
    add_batch: &mut SdfBatch,
) {
    let pos = lerp_v2(prev_pos, drone.pos, interp);
    let (sx, sy) = to_iso_cam(pos, cam_world, view_w, view_h, shake);
    let alt = 16.0 + 2.5 * (motion_t * 5.0).sin();
    let dx = sx;
    let dy = sy + alt;

    // Ground shadow
    alpha_batch.ellipse(sx, sy - 6.0, 11.0, 4.0, 0.0, linear_rgba([4, 8, 16], 110, 1.0));
    add_batch.glow(dx, dy, 18.0, 1.8, linear_rgba_f([90, 255, 225], 0.34, 1.6));

    // Rotating stabilizer rotor behind/around hull
    let r_ang = motion_t * 11.0;
    let rx = r_ang.cos() * 11.5;
    let ry = r_ang.sin() * 5.0;
    alpha_batch.line(dx - rx, dy - ry, dx + rx, dy + ry, 2.0, linear_rgba([160, 250, 240], 170, 1.2));
    alpha_batch.line(dx - ry, dy + rx * 0.4, dx + ry, dy - rx * 0.4, 2.0, linear_rgba([160, 250, 240], 170, 1.2));

    // Pentagon-like diamond scout hull
    let fwd = if drone.heading.length_squared() > 1e-6 {
        drone.heading.normalized()
    } else {
        Vec2::new(1.0, 0.0)
    };
    let perp = fwd.perp();
    let p_front = [dx + fwd.x * 10.5, dy + fwd.y * 6.5];
    let p_l = [dx - fwd.x * 4.0 + perp.x * 8.5, dy - fwd.y * 2.5 + perp.y * 5.5];
    let p_r = [dx - fwd.x * 4.0 - perp.x * 8.5, dy - fwd.y * 2.5 - perp.y * 5.5];
    let p_back = [dx - fwd.x * 9.0, dy - fwd.y * 5.5];
    alpha_batch.quad(p_front, p_l, p_back, p_r, linear_rgba([214, 248, 255], 245, 1.1));
    alpha_batch.circle(dx + fwd.x * 2.5, dy + fwd.y * 1.8, 3.0, linear_rgba([18, 32, 48], 255, 1.0));
    add_batch.circle(dx + fwd.x * 3.0, dy + fwd.y * 2.0, 1.5, linear_rgba([90, 255, 225], 255, 2.0));

    if drone.flash > 0.0 {
        add_batch.circle(p_front[0], p_front[1], 4.5, linear_rgba([255, 240, 170], 245, 2.2));
    }
    let _ = DRONE_RANGE;
}

fn swarm_surge_warning_strength(state: &SimState, e: &Enemy) -> f32 {
    let Some(brain) = state.swarm_brain.as_ref() else {
        return 0.0;
    };
    let (subgroup, _) = swarm_formation_key(e);
    if brain.subgroup_modes[subgroup] != SwarmMode::SurgeTelegraph {
        return 0.0;
    }
    (1.0 - brain.subgroup_timers[subgroup] / SWARM_SURGE_TELEGRAPH_SECONDS).clamp(0.0, 1.0)
}

fn enemy_windup_strength(e: &Enemy) -> f32 {
    let ramp = |rem: f32, dur: f32| -> f32 {
        if dur <= 0.0 {
            1.0
        } else {
            (1.0 - rem / dur).clamp(0.0, 1.0)
        }
    };
    match e.behavior.as_str() {
        "boss_thunder" if e.ai.sub_state == EnemySubState::ThunderWindup => {
            ramp(e.ai.sub_timer, 0.62)
        }
        "chaser" if e.ai.lunge_windup > 0.0 => ramp(e.ai.lunge_windup, 0.22),
        "charger" if e.ai.sub_state == EnemySubState::ChargerWindup => {
            ramp(e.ai.state_timer.unwrap_or(0.0), 0.5)
        }
        "flyer" if e.ai.sub_state == EnemySubState::FlyerWindup => {
            ramp(e.ai.state_timer.unwrap_or(0.0), 0.45)
        }
        "sniper" if e.ai.sub_state == EnemySubState::SniperWindup => {
            ramp(e.ai.sub_timer, 0.92)
        }
        "ranged" if e.ai.sub_state == EnemySubState::RangedWindup => {
            ramp(e.ai.sub_timer, 0.34)
        }
        "spitter" if e.ai.sub_state == EnemySubState::SpitterWindup => {
            ramp(e.ai.sub_timer, 0.38)
        }
        "engineer" if e.ai.sub_state == EnemySubState::EngineerWindup => {
            ramp(e.ai.sub_timer, 0.54)
        }
        "boss_brute" if e.ai.sub_state == EnemySubState::BruteTelegraph => {
            ramp(e.ai.sub_timer, brute_charge_windup_time(e))
        }
        "boss_laser" if e.ai.sub_state == EnemySubState::LaserCharge => {
            ramp(e.ai.sub_timer, 0.75)
        }
        "boss_laser" if e.ai.sub_state == EnemySubState::LaserWingWindup => {
            ramp(e.ai.sub_timer, 0.46)
        }
        "boss_eclipse_archon" if e.ai.sub_state == EnemySubState::EclipseCharge => {
            ramp(e.ai.sub_timer, if e.ai.rage { 0.68 } else { 0.92 })
        }
        "boss_womb_core" if e.ai.sub_state == EnemySubState::WombPulseTelegraph => {
            ramp(e.ai.sub_timer, WOMB_PULSE_TELEGRAPH)
        }
        "boss_swarmqueen"
            if matches!(
                e.ai.sub_state,
                EnemySubState::QueenBroodTelegraph
                    | EnemySubState::QueenSwarmTelegraph
                    | EnemySubState::QueenVolleyTelegraph
            ) => ramp(e.ai.sub_timer, SWARMQUEEN_TELEGRAPH),
        "boss_trapmaster" if e.ai.sub_state == EnemySubState::TrapmasterTelegraph => {
            ramp(e.ai.sub_timer, TRAPMASTER_TELEGRAPH)
        }
        "boss_abyss_gaze" if e.ai.sub_state == EnemySubState::AbyssTelegraph => {
            ramp(e.ai.sub_timer, ABYSS_GAZE_TELEGRAPH)
        }
        "bomber" if e.ai.sub_state == EnemySubState::BomberWindup => {
            ramp(e.ai.sub_timer, BOMBER_WINDUP_SECONDS)
        }
        "tank" if e.ai.sub_state == EnemySubState::TankWindup => {
            ramp(e.ai.sub_timer, TANK_WINDUP_SECONDS)
        }
        _ => {
            if e.attack_cd > 0.0 && e.attack_cd <= 0.35 {
                1.0 - e.attack_cd / 0.35
            } else {
                0.0
            }
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn draw_enemy(
    e: &Enemy,
    state: &SimState,
    warden_positions: &[(u64, Vec2)],
    interp: f32,
    player_pos: Vec2,
    cam_world: Vec2,
    view_w: f32,
    view_h: f32,
    shake: Vec2,
    rm: bool,
    model_facing: &mut HashMap<u64, Vec2>,
    model_turn_dt: f32,
    alpha_batch: &mut SdfBatch,
    add_batch: &mut SdfBatch,
) {
    let pos = lerp_v2(e.prev_pos, e.pos, interp);
    let (sx, sy) = to_iso_cam(pos, cam_world, view_w, view_h, shake);
    let et = if rm { 0.0 } else { e.t };
    let b = e.behavior.as_str();
    let is_boss = b.starts_with("boss_");
    let warded_by_other = !is_boss
        && warden_positions.iter().any(|&(warden_id, warden_pos)| {
            warden_id != e.id
                && (warden_pos - pos).length_squared()
                    <= crate::sim::config::ELITE_WARD_RADIUS.powi(2)
        });
    let base = enemy_color(b, state.runtime.colorblind_palette);

    let (freq, amp) = match b {
        "flyer" | "swarm" => (5.5, 3.0),
        "tank" => (1.8, 1.0),
        "egg_sac" => (2.4, 0.8),
        _ if is_boss => (2.3, 2.8),
        _ => (3.2, 1.8),
    };
    let lift_extra = match b {
        "flyer" => 11.0,
        _ if is_boss => 8.0,
        _ => 2.5,
    };
    let bob = lift_extra + (et * freq + e.seed).sin() * amp;

    // Spawn scale ease
    let k_spawn = if e.t < 0.28 && !rm {
        let p = (e.t / 0.28).clamp(0.0, 1.0);
        let t = p - 1.0;
        let s = 1.70158_f32;
        0.55 + 0.45 * (1.0 + t * t * ((s + 1.0) * t + s))
    } else {
        1.0
    };

    // Windup swell & tint ramp. A whole stable swarm subgroup gets a short
    // visible tell before its coordinated dive, using the same brain state as
    // the simulation transition rather than a separately timed visual guess.
    let swarm_surge_warning = if b == "swarm" {
        swarm_surge_warning_strength(state, e)
    } else {
        0.0
    };
    let windup = enemy_windup_strength(e).max(swarm_surge_warning);
    let wpulse = 0.5 + 0.5 * (et * 18.0).sin();
    let k_wind = if windup > 0.0 {
        1.0 + 0.14 * windup + 0.06 * windup * wpulse
    } else {
        1.0
    };

    let render_col = if e.hit_flash_timer > 0.0 {
        [255, 255, 255]
    } else if windup > 0.0 {
        mix_rgb(base, [255, 235, 195], windup * (0.45 + 0.25 * wpulse))
    } else if e.is_elite {
        mix_rgb(base, [255, 215, 75], 0.55)
    } else {
        base
    };

    // Hit squash curve
    let squash = if e.hit_flash_timer > 0.0 && !rm {
        1.0 + (e.hit_flash_timer / 0.12).clamp(0.0, 1.0) * 0.20
    } else {
        1.0
    };

    let nominal_r = if is_boss {
        BOSS_RADIUS * 1.05
    } else if b == "egg_sac" {
        let ep = if e.ai.hatch_timer < 1.0 {
            0.88 + 0.26 * (et * 18.0).sin()
        } else {
            0.90 + 0.15 * (et * 7.0).sin()
        };
        16.0 * ep
    } else {
        e.radius.max(11.0)
    };

    let r_vis = nominal_r * k_spawn * k_wind * (0.5 + 0.5 * squash);
    let model_r = r_vis * ENEMY_MODEL_VISUAL_SCALE;
    let cy = sy + bob;

    // Grounded elliptical shadow
    let shad_rx = if is_boss {
        r_vis * 1.15 * boss_model_visual_scale(b)
    } else if b == "tank" {
        model_r * 1.05
    } else {
        model_r * 0.85
    };
    let shad_ry = shad_rx * (ISO_SCALE_Y / ISO_SCALE_X).clamp(0.32, 0.55);
    alpha_batch.ellipse(sx, sy - 6.0, shad_rx, shad_ry, 0.0, linear_rgba([0, 0, 0], 118, 1.0));

    // Facing vectors in screen coordinates
    let to_player = if (player_pos - e.pos).length_squared() > 1e-4 {
        (player_pos - e.pos).normalized()
    } else {
        Vec2::new(1.0, 0.0)
    };
    let world_move_dir = match b {
        "chaser" if e.ai.lunge_windup > 0.0 || e.ai.lunge_t > 0.0 => {
            if e.ai.lunge_dir.length_squared() > 1e-4 { e.ai.lunge_dir.normalized() } else { to_player }
        }
        "boss_brute" if matches!(e.ai.sub_state, EnemySubState::BruteTelegraph | EnemySubState::BruteCharge) => {
            if e.ai.charge_dir.length_squared() > 1e-4 { e.ai.charge_dir.normalized() } else { to_player }
        }
        "boss_laser"
            if matches!(
                e.ai.sub_state,
                EnemySubState::LaserCharge
                    | EnemySubState::LaserAttack
                    | EnemySubState::LaserWingWindup
            ) =>
        {
            safe_dir(e.ai.charge_dir, to_player)
        }
        "boss_abyss_gaze" if e.ai.sub_state == EnemySubState::AbyssTelegraph => {
            safe_dir(e.ai.charge_dir, to_player)
        }
        "charger" if matches!(e.ai.sub_state, EnemySubState::ChargerWindup | EnemySubState::ChargerCharging) => {
            if e.ai.charge_dir.length_squared() > 1e-4 { e.ai.charge_dir.normalized() } else { to_player }
        }
        "ranged" | "spitter" | "sniper" => to_player,
        _ if e.vel.length_squared() > 9.0 => e.vel.normalized(),
        _ => to_player,
    };
    let mut model_dir = world_move_dir;
    if b != "egg_sac" {
        let turn_blend = if rm { 1.0 } else { 1.0 - (-12.0 * model_turn_dt).exp() };
        let facing = model_facing.entry(e.id).or_insert(world_move_dir);
        if rm {
            *facing = world_move_dir;
        } else if turn_blend > 0.0 {
            let cur_a = facing.y.atan2(facing.x);
            let tgt_a = world_move_dir.y.atan2(world_move_dir.x);
            let diff = (tgt_a - cur_a + PI).rem_euclid(TAU) - PI;
            let next_a = cur_a + diff * turn_blend;
            *facing = Vec2::new(next_a.cos(), next_a.sin());
        }
        model_dir = *facing;
    }
    let (fwd, right) = iso_dir(world_move_dir);
    let (aim_f, aim_r) = iso_dir(to_player);

    if b == "bomber" && e.ai.sub_state == EnemySubState::BomberWindup {
        let (tx, ty) = to_iso_cam(e.ai.move_target, cam_world, view_w, view_h, shake);
        let blast_r = crate::sim::config::BOMB_BLAST_RADIUS * SQRT_2 * ISO_SCALE_X;
        let aspect = ISO_SCALE_Y / ISO_SCALE_X;
        let progress = (1.0 - e.ai.sub_timer / BOMBER_WINDUP_SECONDS).clamp(0.0, 1.0);
        alpha_batch.ellipse(
            tx,
            ty,
            blast_r,
            blast_r * aspect,
            0.0,
            linear_rgba_f([255, 116, 52], 0.045 + progress * 0.035, 1.0),
        );
        add_batch.ring(
            tx,
            ty,
            blast_r,
            blast_r * aspect,
            1.7 + progress * 1.0,
            linear_rgba_f([255, 132, 62], 0.34 + progress * 0.28, 1.25),
        );
        add_batch.arc_aspect(
            tx,
            ty,
            blast_r * 0.84,
            2.4,
            -FRAC_PI_2,
            TAU * progress,
            aspect,
            linear_rgba_f([255, 238, 198], 0.56 + progress * 0.24, 1.45),
        );
    }

    if b == "swarm" && swarm_surge_warning > 0.0 {
        let radius = (model_r * 1.45).max(12.0);
        let aspect = ISO_SCALE_Y / ISO_SCALE_X;
        let ground_y = sy - 6.0;
        alpha_batch.ellipse(
            sx,
            ground_y,
            radius,
            radius * aspect,
            0.0,
            linear_rgba_f(base, 0.035 + swarm_surge_warning * 0.035, 1.0),
        );
        add_batch.ring(
            sx,
            ground_y,
            radius,
            radius * aspect,
            1.5,
            linear_rgba_f(base, 0.34 + swarm_surge_warning * 0.35, 1.25),
        );
        add_batch.arc_aspect(
            sx,
            ground_y,
            radius * 0.72,
            1.8,
            -FRAC_PI_2,
            TAU * swarm_surge_warning,
            aspect,
            linear_rgba_f(mix_rgb(base, [255, 248, 226], 0.55), 0.78, 1.35),
        );
    }

    if is_boss {
        draw_boss(
            e, state, sx, sy, cy, r_vis, et, windup, k_spawn, model_dir, rm, render_col, base, fwd, right, aim_f,
            aim_r, cam_world, view_w, view_h, shake, alpha_batch, add_batch,
        );
    } else {
        let turn = world_move_dir.x * to_player.y - world_move_dir.y * to_player.x;
        let model_pitch = if rm { 0.0 } else { (et * 2.7 + e.seed).sin() * 0.035 - windup * 0.08 };
        let model_roll = if rm { 0.0 } else { (turn * 0.17 + (et * 3.4 + e.seed).sin() * 0.025).clamp(-0.20, 0.20) };
        let model_scale = enemy_model_scale(b, r_vis);
        let modeled = crate::render::models3d::draw_enemy_model(
            e,
            alpha_batch,
            add_batch,
            [sx, cy],
            model_dir,
            model_scale,
            model_pitch,
            model_roll,
            et,
            windup,
            k_spawn,
            render_col,
            rm,
        );
        if !modeled {
            draw_non_boss_enemy(
                e, sx, sy, cy, r_vis, et, windup, render_col, base, fwd, right, aim_f, aim_r,
                alpha_batch, add_batch,
            );
        }
    }

    if b == "sniper" && e.ai.sub_state == EnemySubState::SniperWindup {
        let (tx, ty) = to_iso_cam(e.ai.sniper_aim, cam_world, view_w, view_h, shake);
        let locked = e.ai.sub_timer <= SNIPER_LOCK_SECONDS;
        let progress = (1.0 - e.ai.sub_timer / SNIPER_AIM_SECONDS).clamp(0.0, 1.0);
        let pulse = if rm { 0.0 } else { (et * 17.0).sin().abs() };
        let radius = 10.0 + if rm { 0.0 } else { progress * 3.0 + pulse * 1.5 };
        let reticle_col = if locked { [255, 112, 165] } else { [190, 150, 255] };
        let alpha = if locked { 235 } else { 185 };
        add_batch.ring(
            tx,
            ty,
            radius,
            radius * 0.58,
            if locked { 2.3 } else { 1.8 },
            linear_rgba(reticle_col, alpha, 1.8),
        );
        let arm = 5.0 + if locked { 2.0 } else { 0.0 };
        for side in [-1.0_f32, 1.0] {
            add_batch.line(
                tx + side * (radius + 2.0),
                ty,
                tx + side * (radius + arm),
                ty,
                1.7,
                linear_rgba(reticle_col, alpha, 1.7),
            );
            add_batch.line(
                tx,
                ty + side * (radius * 0.58 + 2.0),
                tx,
                ty + side * (radius * 0.58 + arm),
                1.7,
                linear_rgba(reticle_col, alpha, 1.7),
            );
        }
        add_batch.circle(tx, ty, if locked { 2.3 } else { 1.5 }, linear_rgba(reticle_col, 225, 2.0));
        if locked {
            add_batch.ellipse_glow(tx, ty, radius * 1.7, radius, 2.0, linear_rgba(reticle_col, 48, 1.2));
        }
    }

    if b == "tank" && e.max_hp > 0 {
        let hp_frac = e.hp as f32 / e.max_hp as f32;
        if hp_frac <= 0.40 {
            let rx = TANK_DEATH_BLAST_RADIUS * SQRT_2 * ISO_SCALE_X;
            let ry = rx * (ISO_SCALE_Y / ISO_SCALE_X);
            let freq = if hp_frac <= 0.25 { 14.0 } else { 7.0 };
            let pulse = if rm { 0.7 } else { 0.5 + 0.5 * (et * freq).sin() };
            add_batch.ring(
                sx,
                sy - 6.0,
                rx,
                ry,
                2.0 + pulse * 0.8,
                linear_rgba_f([120, 255, 155], 0.38 + pulse * 0.42, 1.55),
            );
        }
    }

    if b == "engineer" && e.ai.support_pulse > 0.0 {
        let pulse = (e.ai.support_pulse / 0.8).clamp(0.0, 1.0);
        let rx = 165.0 * SQRT_2 * ISO_SCALE_X;
        let ry = rx * (ISO_SCALE_Y / ISO_SCALE_X);
        add_batch.ring(
            sx,
            sy - 6.0,
            rx,
            ry,
            1.8 + pulse * 0.8,
            linear_rgba_f([95, 245, 195], 0.28 + 0.35 * pulse, 1.45),
        );
    }

    if b == "spitter" && e.ai.sub_state == EnemySubState::SpitterWindup {
        let aim = if (e.ai.sniper_aim - e.pos).length_squared() > 1e-6 {
            (e.ai.sniper_aim - e.pos).normalized()
        } else {
            to_player
        };
        let (angles, range): (&[f32], f32) = if e.ai.volley_mode == 0 {
            (&[-22.0, 0.0, 22.0], 525.0)
        } else {
            (&[-40.0, -14.0, 14.0, 40.0], 487.5)
        };
        let alpha_outer = 0.34 + 0.24 * windup;
        let alpha_core = 0.26 + 0.28 * windup;
        for &deg in angles {
            let end = e.pos + aim.rotated_deg(deg) * range;
            let (ex, ey) = to_iso_cam(end, cam_world, view_w, view_h, shake);
            add_batch.line(sx, sy, ex, ey, 3.2, linear_rgba_f(SIG_SPITTER_COLOR, alpha_outer, 1.45));
            add_batch.line(sx, sy, ex, ey, 1.4, linear_rgba_f(SIG_SPITTER_CORE, alpha_core, 1.7));
        }
    }

    if b == "engineer" && e.ai.sub_state == EnemySubState::EngineerWindup {
        let (tx, ty) = to_iso_cam(e.ai.move_target, cam_world, view_w, view_h, shake);
        let progress = (1.0 - e.ai.sub_timer / 0.54).clamp(0.0, 1.0);
        let pulse = if rm { 0.0 } else { (et * 13.0).sin().abs() };
        let rx = 28.0 * SQRT_2 * ISO_SCALE_X;
        let ry = rx * (ISO_SCALE_Y / ISO_SCALE_X);
        let col = [255, 142, 74];
        add_batch.line(sx, cy, tx, ty, 3.0, linear_rgba_f([255, 185, 95], 0.42 + progress * 0.25, 1.45));
        add_batch.line(sx, cy, tx, ty, 1.3, linear_rgba_f([125, 255, 210], 0.65 + progress * 0.25, 1.8));
        alpha_batch.ellipse(tx, ty, rx, ry, 0.0, linear_rgba_f(col, 0.08 + progress * 0.05, 1.0));
        add_batch.ring(tx, ty, rx, ry, 2.0 + progress * 0.8, linear_rgba_f(col, 0.48 + progress * 0.3 + pulse * 0.15, 1.6));
        add_batch.arc_aspect(
            tx,
            ty,
            rx * 0.72,
            3.0,
            -FRAC_PI_2,
            TAU * progress,
            ISO_SCALE_Y / ISO_SCALE_X,
            linear_rgba_f([255, 224, 180], 0.7 + pulse * 0.2, 1.7),
        );
        let cross = 5.0 + progress * 3.0;
        add_batch.line(tx - cross, ty, tx + cross, ty, 1.8, linear_rgba_f([255, 236, 210], 0.72 + progress * 0.2, 1.5));
        add_batch.line(tx, ty - cross * 0.55, tx, ty + cross * 0.55, 1.8, linear_rgba_f([255, 236, 210], 0.72 + progress * 0.2, 1.5));
    }

    draw_enemy_status_overlays(
        e,
        state.time,
        sx,
        sy,
        cy,
        model_r,
        et,
        state.runtime.reduce_motion,
        warded_by_other,
        alpha_batch,
        add_batch,
    );

    // Slim capsule health tell above damaged enemies.
    if !is_boss {
        draw_enemy_health_bar(e.hp, e.max_hp, sx, cy, model_r, base, alpha_batch);
    }
}

fn draw_enemy_health_bar(
    hp: i32,
    max_hp: i32,
    sx: f32,
    cy: f32,
    visual_radius: f32,
    color: [u8; 3],
    alpha_batch: &mut SdfBatch,
) {
    if hp >= max_hp || max_hp <= 0 {
        return;
    }

    let width = (visual_radius * 1.45).clamp(15.0, 28.0);
    let y = cy + visual_radius + 6.0;
    let left = sx - width * 0.5;
    let right = sx + width * 0.5;
    let fill_right = left + width * (hp as f32 / max_hp as f32).clamp(0.0, 1.0);

    alpha_batch.line(left, y, right, y, 2.7, linear_rgba([8, 13, 22], 185, 1.0));
    if fill_right > left {
        alpha_batch.line(left, y, fill_right, y, 1.5, linear_rgba(color, 230, 1.0));
    }
}

#[inline]
fn iso_dir(dir: Vec2) -> ([f32; 2], [f32; 2]) {
    let sx = (dir.x - dir.y) * ISO_SCALE_X;
    let sy = (dir.x + dir.y) * ISO_SCALE_Y;
    let len = sx.hypot(sy);
    let f = if len > 1e-4 { [sx / len, sy / len] } else { [1.0, 0.0] };
    let r = [f[1], -f[0]];
    (f, r)
}

#[inline]
fn pt_local(cx: f32, cy: f32, f: [f32; 2], r: [f32; 2], fwd: f32, side: f32) -> [f32; 2] {
    [cx + f[0] * fwd + r[0] * side, cy + f[1] * fwd + r[1] * side]
}

fn reg_poly(cx: f32, cy: f32, r: f32, sides: usize, rot: f32, aspect_y: f32) -> Vec<[f32; 2]> {
    let mut pts = Vec::with_capacity(sides);
    for i in 0..sides {
        let a = rot + (i as f32 / sides as f32) * TAU;
        pts.push([cx + a.cos() * r, cy + a.sin() * r * aspect_y]);
    }
    pts
}

fn draw_hull(
    alpha_batch: &mut SdfBatch,
    pts: &[[f32; 2]],
    fill: [f32; 4],
    rim: [f32; 4],
    rim_w: f32,
) {
    alpha_batch.polyline_closed(pts, rim_w + 2.0, linear_rgba([8, 12, 22], 235, 1.0));
    alpha_batch.polygon(pts, fill);
    alpha_batch.polyline_closed(pts, rim_w, rim);
}

#[allow(clippy::too_many_arguments)]
fn draw_thruster(
    add_batch: &mut SdfBatch,
    cx: f32,
    cy: f32,
    f: [f32; 2],
    r: [f32; 2],
    back_off: f32,
    side_off: f32,
    len: f32,
    thick: f32,
    col: [u8; 3],
    et: f32,
) {
    let flk = 0.78 + 0.22 * (et * 34.0 + side_off).sin().abs();
    let p0 = pt_local(cx, cy, f, r, -back_off, side_off);
    let p1 = pt_local(cx, cy, f, r, -(back_off + len * flk), side_off);
    add_batch.line(p0[0], p0[1], p1[0], p1[1], thick, linear_rgba_f(col, 0.80, 1.7));
    add_batch.circle(p0[0], p0[1], thick * 0.58, linear_rgba_f([255, 245, 225], 0.92, 2.0));
}

#[allow(clippy::too_many_arguments)]
fn draw_enemy_status_overlays(
    e: &Enemy,
    now: f32,
    sx: f32,
    sy: f32,
    cy: f32,
    r_vis: f32,
    et: f32,
    reduce_motion: bool,
    warded_by_other: bool,
    alpha_batch: &mut SdfBatch,
    add_batch: &mut SdfBatch,
) {
    if e.is_elite {
        let pulse = if reduce_motion { 0.0 } else { (et * 5.0).sin() };
        let er = r_vis + 6.5 + 1.2 * pulse;
        let spin = if reduce_motion { 0.0 } else { et * 1.6 };
        let affix_col = elite_affix_color(&e.elite_affix);
        match e.elite_affix.as_str() {
            "volatile" => {
                let vol_rx = ELITE_VOLATILE_BLAST_RADIUS * SQRT_2 * ISO_SCALE_X;
                let vol_ry = vol_rx * (ISO_SCALE_Y / ISO_SCALE_X);
                let hp_frac = if e.max_hp > 0 {
                    e.hp as f32 / e.max_hp as f32
                } else {
                    1.0
                };
                if hp_frac <= 0.40 {
                    let p_wave = if reduce_motion {
                        0.6
                    } else {
                        0.5 + 0.5 * (et * 10.0).sin()
                    };
                    let ring_a = (95.0 + p_wave * 110.0).round() as u8;
                    alpha_batch.ellipse(
                        sx,
                        sy - 6.0,
                        vol_rx,
                        vol_ry,
                        0.0,
                        linear_rgba_f(affix_col, 0.05 + p_wave * 0.06, 1.0),
                    );
                    add_batch.ring(
                        sx,
                        sy - 6.0,
                        vol_rx,
                        vol_ry,
                        2.2,
                        linear_rgba(affix_col, ring_a, 1.55),
                    );
                } else {
                    add_batch.ring(
                        sx,
                        sy - 6.0,
                        vol_rx,
                        vol_ry,
                        1.6,
                        linear_rgba(affix_col, 42, 1.3),
                    );
                }
                let danger_pulse = if reduce_motion { 0.0 } else { 0.5 + 0.5 * (et * 3.5).sin() };
                let radius = er + danger_pulse * 3.0;
                add_batch.ring(
                    sx,
                    cy,
                    radius,
                    radius * 0.84,
                    2.8,
                    linear_rgba(affix_col, (170.0 + danger_pulse * 65.0) as u8, 1.9),
                );
                for i in 0..3 {
                    let a = spin + i as f32 * (TAU / 3.0);
                    add_batch.circle(
                        sx + a.cos() * (radius + 2.0),
                        cy + a.sin() * (radius + 2.0) * 0.72,
                        2.8,
                        linear_rgba([255, 220, 180], 235, 1.8),
                    );
                }
            }
            "swift" => {
                let orbit_r = er + 1.5;
                for i in 0..3 {
                    let a = spin * 1.8 + i as f32 * (TAU / 3.0);
                    add_batch.arc(
                        sx,
                        cy,
                        orbit_r,
                        2.6,
                        a,
                        0.72,
                        linear_rgba(affix_col, 225, 1.9),
                    );
                    let tail_a = a - 0.34;
                    add_batch.circle(
                        sx + tail_a.cos() * orbit_r,
                        cy + tail_a.sin() * orbit_r * 0.72,
                        2.0,
                        linear_rgba([205, 250, 255], 205, 1.7),
                    );
                }
            }
            "shielded" => {
                if e.shield > 0 {
                    let pulse = if reduce_motion { 0.0 } else { 0.5 + 0.5 * (et * 2.6).sin() };
                    let radius = er + pulse * 2.0;
                    add_batch.ring(
                        sx,
                        cy,
                        radius,
                        radius * 0.82,
                        2.6,
                        linear_rgba(affix_col, (160.0 + pulse * 65.0) as u8, 1.8),
                    );
                    for i in 0..4 {
                        let a = spin + i as f32 * (TAU / 4.0);
                        add_batch.circle(
                            sx + a.cos() * radius,
                            cy + a.sin() * radius * 0.72,
                            2.5,
                            linear_rgba([210, 238, 255], 235, 1.75),
                        );
                    }
                }
            }
            "reflector" => {
                if e.ai.reflect_cd_left <= 0.0 {
                    add_batch.arc(sx, cy, er, 2.6, spin, 2.2, linear_rgba(affix_col, 225, 1.8));
                    add_batch.arc(sx, cy, er, 2.6, spin + PI, 2.2, linear_rgba([255, 225, 110], 215, 1.8));
                } else {
                    let frac = (1.0 - e.ai.reflect_cd_left / ELITE_REFLECT_COOLDOWN).clamp(0.0, 1.0);
                    if frac > 0.01 {
                        add_batch.arc(sx, cy, er, 1.4, -FRAC_PI_2, TAU * frac, linear_rgba(affix_col, 45, 1.2));
                    }
                }
            }
            "splitter" => {
                for s in 0..2 {
                    let a = spin * 1.4 + s as f32 * PI;
                    add_batch.circle(sx + a.cos() * er, cy + a.sin() * er * 0.72, 3.4, linear_rgba(affix_col, 235, 1.9));
                }
                add_batch.ring(sx, cy, er * 0.95, er * 0.72, 1.6, linear_rgba(affix_col, 145, 1.5));
            }
            "mender" => {
                let pulse = if reduce_motion { 0.0 } else { e.ai.mender_pulse.clamp(0.0, 1.0) };
                let heal_col = affix_col;
                let mender_rx = ELITE_MENDER_RADIUS * SQRT_2 * ISO_SCALE_X;
                let mender_ry = mender_rx * (ISO_SCALE_Y / ISO_SCALE_X);
                let ground_alpha = if e.ai.mender_pulse > 0.01 {
                    let p_wave = if reduce_motion { 1.0 } else { 0.65 + 0.35 * (et * 10.0).sin().abs() };
                    (40.0 + 100.0 * e.ai.mender_pulse.clamp(0.0, 1.0) * p_wave).round() as u8
                } else {
                    40
                };
                add_batch.ring(
                    sx,
                    sy - 6.0,
                    mender_rx,
                    mender_ry,
                    if e.ai.mender_pulse > 0.01 { 2.4 } else { 1.6 },
                    linear_rgba(heal_col, ground_alpha, 1.4),
                );
                add_batch.ring(
                    sx,
                    cy,
                    er + pulse * 5.0,
                    (er + pulse * 5.0) * 0.84,
                    2.4 + pulse,
                    linear_rgba(heal_col, (145.0 + pulse * 100.0) as u8, 1.75),
                );
                let mark_y = cy + r_vis + 6.0;
                let mark_alpha = (210.0 + pulse * 45.0) as u8;
                add_batch.line(sx - 4.0, mark_y, sx + 4.0, mark_y, 2.2, linear_rgba(heal_col, mark_alpha, 1.8));
                add_batch.line(sx, mark_y - 4.0, sx, mark_y + 4.0, 2.2, linear_rgba(heal_col, mark_alpha, 1.8));
                if pulse > 0.05 {
                    add_batch.glow(sx, cy, r_vis * 1.8, 2.0, linear_rgba(heal_col, (65.0 * pulse) as u8, 1.2));
                }
            }
            "warden" => {
                let pulse = if reduce_motion { 0.0 } else { 0.5 + 0.5 * (et * 2.4).sin() };
                let ward_col = affix_col;
                let aura_rx = ELITE_WARD_RADIUS * SQRT_2 * ISO_SCALE_X * (1.0 + pulse * 0.025);
                let aura_ry = aura_rx * (ISO_SCALE_Y / ISO_SCALE_X);
                add_batch.ring(
                    sx,
                    sy - 6.0,
                    aura_rx,
                    aura_ry,
                    2.2,
                    linear_rgba(ward_col, (70.0 + pulse * 35.0) as u8, 1.35),
                );
                for i in 0..3 {
                    let ang = if reduce_motion { 0.0 } else { et * 0.8 } + i as f32 * (TAU / 3.0);
                    let nx = sx + ang.cos() * (r_vis + 7.0);
                    let ny = cy + ang.sin() * (r_vis + 7.0) * 0.72;
                    add_batch.circle(nx, ny, 2.6, linear_rgba([190, 225, 255], 230, 1.65));
                }
            }
            _ => {
                add_batch.ring(sx, cy, er, er * 0.85, 2.0, linear_rgba(affix_col, 190, 1.75));
            }
        }
    }

    if e.shield > 0 {
        let shield_spin = if reduce_motion { 0.0 } else { et * 0.8 };
        let hex = reg_poly(sx, cy, r_vis + 5.0, 6, shield_spin, 0.82);
        alpha_batch.polygon(&hex, linear_rgba([80, 195, 255], 34, 1.0));
        add_batch.polyline_closed(&hex, 2.2, linear_rgba([125, 230, 255], 215, 1.75));
    }

    if warded_by_other {
        let ward_col = [145, 205, 255];
        let spin = if reduce_motion { 0.0 } else { et * 0.5 };
        for offset in [0.0_f32, PI] {
            add_batch.arc(
                sx,
                cy,
                r_vis + 4.0,
                1.6,
                spin + offset,
                PI * 0.42,
                linear_rgba(ward_col, 165, 1.55),
            );
        }
    }

    if now < e.stun_until {
        let sy_stun = cy + r_vis + 5.0;
        let a = if reduce_motion { 0.0 } else { et * 7.5 };
        add_batch.arc(sx, cy, r_vis + 3.0, 2.0, a, 1.8, linear_rgba([195, 245, 255], 220, 1.9));
        add_batch.circle(sx + a.cos() * 9.0, sy_stun, 2.2, linear_rgba([225, 250, 255], 240, 2.0));
        add_batch.circle(sx - a.cos() * 9.0, sy_stun, 2.2, linear_rgba([175, 230, 255], 240, 2.0));
    }
}

#[allow(clippy::too_many_arguments)]
fn draw_non_boss_enemy(
    e: &Enemy,
    sx: f32,
    sy: f32,
    cy: f32,
    r: f32,
    et: f32,
    windup: f32,
    col: [u8; 3],
    base: [u8; 3],
    f: [f32; 2],
    rt: [f32; 2],
    af: [f32; 2],
    ar: [f32; 2],
    alpha_batch: &mut SdfBatch,
    add_batch: &mut SdfBatch,
) {
    let rim = linear_rgba(mix_rgb(col, [255, 255, 255], 0.42), 235, 1.25);
    let fill = linear_rgba(col, 250, 1.05);
    let dark_trim = linear_rgba(mix_rgb(col, [12, 16, 28], 0.65), 245, 1.0);

    match e.behavior.as_str() {
        "chaser" => {
            // Dart Interceptor: swept delta wings, thruster flare, glowing nose fangs
            draw_thruster(add_batch, sx, cy, f, rt, r * 0.72, 0.0, r * 0.85, 3.2, col, et);
            let hull = [
                pt_local(sx, cy, f, rt, r * 1.15, 0.0),
                pt_local(sx, cy, f, rt, -r * 0.65, r * 0.92),
                pt_local(sx, cy, f, rt, -r * 0.38, 0.0),
                pt_local(sx, cy, f, rt, -r * 0.65, -r * 0.92),
            ];
            draw_hull(alpha_batch, &hull, fill, rim, 1.5);
            let visor = pt_local(sx, cy, f, rt, r * 0.35, 0.0);
            alpha_batch.circle(visor[0], visor[1], r * 0.25, linear_rgba([16, 22, 34], 245, 1.0));
            add_batch.circle(visor[0], visor[1], r * 0.14, linear_rgba([255, 120, 95], 235, 1.9));
            if e.ai.lunge_windup > 0.0 || e.ai.lunge_t > 0.0 {
                let nose = pt_local(sx, cy, f, rt, r * 1.25, 0.0);
                add_batch.circle(nose[0], nose[1], 3.8 + windup * 3.0, linear_rgba([255, 220, 140], 240, 2.0));
            }
        }
        "ranged" => {
            // Catamaran Rail-Marksman tracking player directly
            let chassis = [
                pt_local(sx, cy, af, ar, r * 0.78, r * 0.58),
                pt_local(sx, cy, af, ar, -r * 0.75, r * 0.78),
                pt_local(sx, cy, af, ar, -r * 0.52, 0.0),
                pt_local(sx, cy, af, ar, -r * 0.75, -r * 0.78),
                pt_local(sx, cy, af, ar, r * 0.78, -r * 0.58),
            ];
            draw_hull(alpha_batch, &chassis, fill, rim, 1.5);
            for side in [-r * 0.34, r * 0.34] {
                let b0 = pt_local(sx, cy, af, ar, r * 0.15, side);
                let b1 = pt_local(sx, cy, af, ar, r * 1.32, side * 0.7);
                alpha_batch.line(b0[0], b0[1], b1[0], b1[1], 3.4, linear_rgba([26, 36, 52], 245, 1.0));
                add_batch.line(b0[0], b0[1], b1[0], b1[1], 1.4, linear_rgba([255, 120, 175], 210, 1.65));
            }
            let tip = pt_local(sx, cy, af, ar, r * 1.35, 0.0);
            let charge = (1.0 - (e.attack_cd / 0.45).clamp(0.0, 1.0)).max(windup);
            add_batch.circle(tip[0], tip[1], 2.2 + charge * 3.2, linear_rgba([255, 220, 240], 210, 2.0));
            alpha_batch.circle(sx, cy, r * 0.30, linear_rgba([16, 20, 32], 245, 1.0));
            add_batch.circle(sx, cy, r * 0.16, linear_rgba(mix_rgb(base, [255, 255, 255], 0.5), 240, 1.8));
        }
        "sniper" => {
            // Longline Interceptor: narrow scope chassis and a charged, forward rail cannon.
            let chassis = [
                pt_local(sx, cy, af, ar, r * 1.02, 0.0),
                pt_local(sx, cy, af, ar, r * 0.24, r * 0.52),
                pt_local(sx, cy, af, ar, -r * 0.82, r * 0.48),
                pt_local(sx, cy, af, ar, -r * 1.08, 0.0),
                pt_local(sx, cy, af, ar, -r * 0.82, -r * 0.48),
                pt_local(sx, cy, af, ar, r * 0.24, -r * 0.52),
            ];
            draw_hull(alpha_batch, &chassis, fill, rim, 1.55);
            let barrel_a = pt_local(sx, cy, af, ar, r * 0.12, 0.0);
            let barrel_b = pt_local(sx, cy, af, ar, r * 1.62, 0.0);
            alpha_batch.line(barrel_a[0], barrel_a[1], barrel_b[0], barrel_b[1], 5.4, dark_trim);
            alpha_batch.line(barrel_a[0], barrel_a[1], barrel_b[0], barrel_b[1], 2.1, rim);
            for side in [-1.0_f32, 1.0] {
                let coil_a = pt_local(sx, cy, af, ar, -r * 0.18, side * r * 0.32);
                let coil_b = pt_local(sx, cy, af, ar, r * 0.82, side * r * 0.32);
                alpha_batch.line(coil_a[0], coil_a[1], coil_b[0], coil_b[1], 2.2, linear_rgba([36, 24, 58], 240, 1.0));
                add_batch.line(coil_a[0], coil_a[1], coil_b[0], coil_b[1], 1.1, linear_rgba([220, 170, 255], 190, 1.6));
            }
            let charge = windup.max((1.0 - (e.attack_cd / 0.6).clamp(0.0, 1.0)) * 0.35);
            let muzzle = pt_local(sx, cy, af, ar, r * 1.66, 0.0);
            add_batch.circle(muzzle[0], muzzle[1], 2.3 + charge * 4.0, linear_rgba([255, 215, 255], 230, 1.8 + charge));
            alpha_batch.circle(sx, cy, r * 0.24, linear_rgba([18, 14, 34], 248, 1.0));
            add_batch.circle(sx, cy, r * 0.12, linear_rgba([240, 205, 255], 245, 2.0));
        }
        "bomber" => {
            // Hex Ordinance Carrier with flickering exposed volatile core
            let hex = reg_poly(sx, cy, r * 1.02, 6, et * 0.5, 0.85);
            draw_hull(alpha_batch, &hex, fill, rim, 1.7);
            for s in [-1.0_f32, 1.0] {
                let p0 = pt_local(sx, cy, f, rt, -r * 0.1, s * r * 0.85);
                let p1 = pt_local(sx, cy, f, rt, -r * 0.55, s * r * 1.25);
                alpha_batch.line(p0[0], p0[1], p1[0], p1[1], 4.0, dark_trim);
            }
            let fuse_spd = if e.ai.sub_timer > 0.0 || e.attack_cd < 0.7 { 22.0 } else { 5.5 };
            let strobe = 0.5 + 0.5 * (et * fuse_spd).sin();
            add_batch.glow(sx, cy, r * 1.5, 1.8, linear_rgba_f([255, 165, 50], 0.28 + 0.35 * strobe, 1.65));
            alpha_batch.circle(sx, cy, r * 0.46, linear_rgba([28, 18, 18], 245, 1.0));
            add_batch.circle(sx, cy, r * (0.28 + 0.14 * strobe), linear_rgba([255, 225, 110], 245, 2.1));
        }
        "tank" => {
            // Siege Juggernaut with heavy shoulder armor & rotating turret toward player
            let oct = reg_poly(sx, cy, r * 1.10, 8, PI / 8.0, 0.86);
            draw_hull(alpha_batch, &oct, fill, rim, 2.1);
            alpha_batch.ring(sx, cy, r * 0.76, r * 0.65, 3.0, dark_trim);
            let m0 = [sx, cy + 2.0];
            let m1 = pt_local(sx, cy + 2.0, af, ar, r * 1.32, 0.0);
            alpha_batch.line(m0[0], m0[1], m1[0], m1[1], 6.0, linear_rgba([26, 36, 48], 245, 1.0));
            alpha_batch.line(m0[0], m0[1], m1[0], m1[1], 3.2, rim);
            alpha_batch.circle(sx, cy + 2.0, r * 0.40, dark_trim);
            add_batch.circle(sx, cy + 2.0, r * 0.18, linear_rgba([135, 255, 165], 235, 1.9));
            if e.ai.push_t > 0.0 {
                add_batch.ring(sx, cy, r * 1.34, r * 1.15, 2.6, linear_rgba([255, 175, 80], 190, 1.7));
            }
        }
        "charger" => {
            // Wedge Rammer with twin serrated horns & supersonic charge cone
            let rushing = e.ai.charger_dashing || e.ai.sub_state == EnemySubState::ChargerCharging;
            draw_thruster(add_batch, sx, cy, f, rt, r * 0.78, -r * 0.34, r * if rushing { 1.45 } else { 0.8 }, 3.4, [255, 175, 70], et);
            draw_thruster(add_batch, sx, cy, f, rt, r * 0.78, r * 0.34, r * if rushing { 1.45 } else { 0.8 }, 3.4, [255, 175, 70], et);
            let wedge = [
                pt_local(sx, cy, f, rt, r * 1.12, 0.0),
                pt_local(sx, cy, f, rt, -r * 0.72, r * 0.88),
                pt_local(sx, cy, f, rt, -r * 0.55, 0.0),
                pt_local(sx, cy, f, rt, -r * 0.72, -r * 0.88),
            ];
            draw_hull(alpha_batch, &wedge, fill, rim, 1.7);
            for side in [-1.0_f32, 1.0] {
                let h0 = pt_local(sx, cy, f, rt, r * 0.50, side * r * 0.38);
                let h1 = pt_local(sx, cy, f, rt, r * 1.46, side * r * 0.56);
                let h2 = pt_local(sx, cy, f, rt, r * 0.25, side * r * 0.68);
                alpha_batch.triangle(h0, h1, h2, linear_rgba([250, 240, 225], 240, 1.2));
            }
            if rushing {
                let cone = pt_local(sx, cy, f, rt, r * 1.50, 0.0);
                add_batch.glow(cone[0], cone[1], 18.0, 1.7, linear_rgba([255, 155, 75], 165, 1.9));
            }
        }
        "spitter" => {
            // Venom Bio-Artillery with 3 glowing acid sacs & forward mandibles
            let body = [
                pt_local(sx, cy, af, ar, r * 0.90, 0.0),
                pt_local(sx, cy, af, ar, r * 0.25, r * 0.88),
                pt_local(sx, cy, af, ar, -r * 0.85, r * 0.62),
                pt_local(sx, cy, af, ar, -r * 0.85, -r * 0.62),
                pt_local(sx, cy, af, ar, r * 0.25, -r * 0.88),
            ];
            draw_hull(alpha_batch, &body, fill, rim, 1.6);
            let sac_pulse = 0.85 + 0.15 * (et * 5.2 + e.seed).sin();
            for (fs, ss) in [(-0.28, 0.62), (-0.28, -0.62), (-0.52, 0.0)] {
                let sp = pt_local(sx, cy, af, ar, r * fs, r * ss);
                alpha_batch.circle(sp[0], sp[1], r * 0.34 * sac_pulse, linear_rgba([195, 255, 90], 235, 1.35));
                add_batch.circle(sp[0], sp[1], r * 0.16, linear_rgba([235, 255, 180], 220, 1.8));
            }
            for s in [-1.0_f32, 1.0] {
                let m0 = pt_local(sx, cy, af, ar, r * 0.72, s * r * 0.34);
                let m1 = pt_local(sx, cy, af, ar, r * 1.32, s * r * 0.16);
                alpha_batch.line(m0[0], m0[1], m1[0], m1[1], 2.6, linear_rgba([30, 38, 22], 240, 1.0));
            }
        }
        "flyer" => {
            // Swept-forward crescent wing falcon with animated bank & windup trail
            let flap = 0.85 + 0.22 * (et * 12.0 + e.seed).sin();
            let wings = [
                pt_local(sx, cy, f, rt, r * 1.15, 0.0),
                pt_local(sx, cy, f, rt, r * 0.55, r * 1.48 * flap),
                pt_local(sx, cy, f, rt, -r * 0.52, r * 0.92 * flap),
                pt_local(sx, cy, f, rt, -r * 0.88, 0.0),
                pt_local(sx, cy, f, rt, -r * 0.52, -r * 0.92 * flap),
                pt_local(sx, cy, f, rt, r * 0.55, -r * 1.48 * flap),
            ];
            draw_hull(alpha_batch, &wings, fill, rim, 1.5);
            draw_thruster(add_batch, sx, cy, f, rt, r * 0.86, 0.0, r * 0.95, 2.8, [145, 225, 255], et);
            let visor = pt_local(sx, cy, f, rt, r * 0.42, 0.0);
            add_batch.circle(visor[0], visor[1], r * 0.18, linear_rgba([210, 245, 255], 240, 1.9));
        }
        "engineer" => {
            // Fabricator Hex-Rig with welding claw & forward scanner arc
            let rig = reg_poly(sx, cy, r * 0.96, 6, 0.0, 0.88);
            draw_hull(alpha_batch, &rig, fill, rim, 1.6);
            alpha_batch.circle(sx, cy, r * 0.34, dark_trim);
            add_batch.circle(sx, cy, r * 0.15, linear_rgba([120, 255, 210], 235, 1.85));
            let c0 = pt_local(sx, cy, f, rt, r * 0.65, r * 0.42);
            let c1 = pt_local(sx, cy, f, rt, r * 1.24, r * 0.62);
            let c2 = pt_local(sx, cy, f, rt, r * 1.24, r * 0.12);
            alpha_batch.line(c0[0], c0[1], c1[0], c1[1], 2.4, linear_rgba([235, 245, 250], 235, 1.1));
            alpha_batch.line(c0[0], c0[1], c2[0], c2[1], 2.4, linear_rgba([235, 245, 250], 235, 1.1));
            if e.ai.support_pulse > 0.0 {
                add_batch.arc(sx, cy, r * 1.38, 1.8, et * 2.8, 2.3, linear_rgba([95, 245, 195], 165, 1.5));
            }
        }
        "swarm" => {
            // Razor Stinger with fluttering wings & venom barb
            let jit = (et * 24.0 + e.seed).sin() * 0.25;
            let stinger = [
                pt_local(sx, cy, f, rt, r * 1.22, 0.0),
                pt_local(sx, cy, f, rt, -r * 0.30, r * (1.05 + jit)),
                pt_local(sx, cy, f, rt, -r * 0.92, 0.0),
                pt_local(sx, cy, f, rt, -r * 0.30, -r * (1.05 + jit)),
            ];
            draw_hull(alpha_batch, &stinger, fill, rim, 1.3);
            add_batch.circle(sx, cy, r * 0.22, linear_rgba([255, 220, 255], 235, 1.9));
        }
        "egg_sac" => {
            // Rooted Chrysalis Cocoon with pulsing bio-ribs & urgent hatch glow
            for i in 0..5 {
                let a = (i as f32 / 5.0) * TAU + e.seed;
                alpha_batch.line(sx, sy - 4.0, sx + a.cos() * (r * 1.18), sy - 5.0 + a.sin() * (r * 0.56), 2.5, dark_trim);
            }
            alpha_batch.ellipse(sx, cy, r * 0.95, r * 1.08, 0.0, linear_rgba([8, 12, 22], 235, 1.0));
            alpha_batch.ellipse(sx, cy, r * 0.84, r * 0.96, 0.0, linear_rgba(mix_rgb(col, [185, 150, 175], 0.35), 245, 1.05));
            let ur = (1.0 - (e.ai.hatch_timer / e.ai.max_hatch_timer.max(0.1)).clamp(0.0, 1.0)).max(0.15);
            let h_col = mix_rgb([255, 95, 125], [255, 220, 140], ur);
            add_batch.glow(sx, cy, r * 1.4, 1.7, linear_rgba_f(h_col, 0.30 + 0.35 * ur, 1.65));
            add_batch.circle(sx, cy, r * (0.34 + 0.16 * (et * 10.0).sin().abs()), linear_rgba(h_col, 240, 2.0));
        }
        _ => {
            let hull = [
                pt_local(sx, cy, f, rt, r * 1.05, 0.0),
                pt_local(sx, cy, f, rt, -r * 0.65, r * 0.85),
                pt_local(sx, cy, f, rt, -r * 0.65, -r * 0.85),
            ];
            draw_hull(alpha_batch, &hull, fill, rim, 1.5);
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn draw_boss(
    e: &Enemy,
    state: &SimState,
    sx: f32,
    sy: f32,
    cy: f32,
    r: f32,
    et: f32,
    windup: f32,
    k_spawn: f32,
    model_facing: Vec2,
    reduce_motion: bool,
    render_col: [u8; 3],
    base: [u8; 3],
    f: [f32; 2],
    rt: [f32; 2],
    af: [f32; 2],
    _ar: [f32; 2],
    cam_world: Vec2,
    view_w: f32,
    view_h: f32,
    shake: Vec2,
    alpha_batch: &mut SdfBatch,
    add_batch: &mut SdfBatch,
) {
    let raged = is_raged(e);
    let phase = e.ai.phase.clamp(0, 2) as f32;
    let rage_col = if raged {
        [255, 75, 95]
    } else {
        mix_rgb(base, [255, 218, 170], phase * 0.14)
    };
    let hull_fill = linear_rgba(render_col, 250, 1.1);
    let hull_rim = linear_rgba(mix_rgb(render_col, [255, 255, 255], if raged { 0.62 } else { 0.42 }), 245, 1.4);
    let dark_plate = linear_rgba([16, 22, 36], 245, 1.0);

    // 1. Tactical Lock-on Floor Ring + ambient dreadnought halo
    let aspect = (ISO_SCALE_Y / ISO_SCALE_X).clamp(0.4, 0.6);
    let ring_r = r * 1.55 * k_spawn * (1.0 + phase * 0.025);
    let ring_rot = et * if raged { 1.9 + phase * 0.18 } else { 0.85 + phase * 0.18 };
    for s in 0..3 {
        let a = ring_rot + s as f32 * (TAU / 3.0);
        let ring_alpha = if raged { 0.85 } else { 0.48 + phase * 0.11 };
        add_batch.arc_aspect(sx, sy - 4.0, ring_r, 3.0 + phase * 0.35, a, 1.35, aspect, linear_rgba_f(rage_col, ring_alpha, 1.65));
    }
    add_batch.glow(sx, cy, r * (2.1 + phase * 0.08), 1.8, linear_rgba_f(rage_col, if raged { 0.52 } else { 0.30 + phase * 0.08 }, 1.7));
    if phase >= 1.0 {
        let mote_count = phase as usize + 1;
        for i in 0..mote_count {
            let angle = et * (1.35 + phase * 0.24) + i as f32 * (TAU / mote_count as f32);
            let mx = sx + angle.cos() * ring_r;
            let my = sy - 4.0 + angle.sin() * ring_r * aspect;
            add_batch.circle(mx, my, 1.8 + phase * 0.45, linear_rgba(rage_col, 220, 1.7));
            add_batch.glow(mx, my, 4.5 + phase, 2.2, linear_rgba(rage_col, 80, 1.25));
        }
    }

    // Brute telegraph lane on ground
    if e.behavior == "boss_brute" {
        if let Some((dir, len)) = brute_charge_lane(e, state.room_radius, &state.map_type) {
            let (lx, ly) = to_iso_cam(e.pos + dir * len, cam_world, view_w, view_h, shake);
            let lane_a = ((150.0 + 60.0 * (et * 12.0).sin()) / 255.0).clamp(0.0, 1.0);
            add_batch.line(sx, sy, lx, ly, 9.0, linear_rgba_f([255, 65, 65], lane_a * 0.72, 1.8));
            add_batch.line(sx, sy, lx, ly, 3.0, linear_rgba_f([255, 225, 200], lane_a, 2.2));
        }
    }

    if e.behavior == "boss_laser" && e.ai.sub_state == EnemySubState::LaserCharge {
        let locked_dir = if e.ai.charge_dir.length_squared() > 1e-6 {
            e.ai.charge_dir.normalized()
        } else {
            Vec2::new(1.0, 0.0)
        };
        let sweep = (BOSS_LASER_SWEEP_BASE_DEG
            + e.ai.phase.clamp(0, 2) as f32 * BOSS_LASER_SWEEP_PER_PHASE_DEG)
            .to_radians();
        let reach = state.room_radius * 2.2;
        let iso_aspect = ISO_SCALE_Y / ISO_SCALE_X;
        let r_scr = reach * SQRT_2 * ISO_SCALE_X;
        let center_rad = locked_dir.y.atan2(locked_dir.x);
        let sector_start = center_rad - sweep + FRAC_PI_4;
        alpha_batch.sector(
            sx,
            sy,
            r_scr,
            sector_start,
            sweep * 2.0,
            iso_aspect,
            linear_rgba_f([255, 85, 210], 0.06 + windup * 0.07, 1.1),
        );
        add_batch.arc_aspect(
            sx,
            sy,
            (r * 3.0).min(r_scr),
            2.0,
            sector_start,
            sweep * 2.0,
            iso_aspect,
            linear_rgba_f([255, 130, 235], 0.35 + windup * 0.35, 1.5),
        );
        let warning_alpha = (105.0 + windup * 100.0) as u8;
        for offset in [-sweep, 0.0, sweep] {
            let end = e.pos + locked_dir.rotated_rad(offset) * reach;
            let (ex, ey) = to_iso_cam(end, cam_world, view_w, view_h, shake);
            let center = offset == 0.0;
            add_batch.line(
                sx,
                sy,
                ex,
                ey,
                if center { 3.4 } else { 2.0 },
                linear_rgba(
                    if center { [255, 205, 250] } else { [255, 95, 190] },
                    if center { warning_alpha } else { 82 },
                    if center { 1.9 } else { 1.35 },
                ),
            );
        }
    }

    if e.behavior == "boss_laser" && e.ai.sub_state == EnemySubState::LaserWingWindup {
        let aim = if e.ai.charge_dir.length_squared() > 1e-6 {
            e.ai.charge_dir.normalized()
        } else {
            Vec2::new(1.0, 0.0)
        };
        let reach = state.room_radius * 1.8;
        let alpha = (112.0 + windup * 110.0) as u8;
        for offset in [-24.0_f32, 0.0, 24.0] {
            let end = e.pos + aim.rotated_deg(offset) * reach;
            let (ex, ey) = to_iso_cam(end, cam_world, view_w, view_h, shake);
            let core = offset == 0.0;
            add_batch.line(
                sx,
                sy,
                ex,
                ey,
                if core { 3.1 } else { 2.0 },
                linear_rgba(
                    if core { [255, 230, 255] } else { [255, 125, 230] },
                    alpha,
                    if core { 1.95 } else { 1.45 },
                ),
            );
        }
    }

    if e.behavior == "boss_swarmqueen" {
        let is_spawn_warning = matches!(
            e.ai.sub_state,
            EnemySubState::QueenBroodTelegraph | EnemySubState::QueenSwarmTelegraph
        );
        if is_spawn_warning {
            // Mark the committed arrival positions, not an approximate band.
            let color = if e.ai.sub_state == EnemySubState::QueenBroodTelegraph {
                [255, 120, 230]
            } else {
                [160, 240, 255]
            };
            for pos in e
                .ai
                .summon_targets
                .iter()
                .take(e.ai.summon_target_count as usize)
            {
                let (mx, my) = to_iso_cam(*pos, cam_world, view_w, view_h, shake);
                let radius = if e.ai.sub_state == EnemySubState::QueenBroodTelegraph {
                    25.0
                } else {
                    18.0
                };
                let mut ring = [[0.0_f32; 2]; 20];
                let ring_count = ring.len() as f32;
                for (i, point) in ring.iter_mut().enumerate() {
                    let angle = i as f32 * (TAU / ring_count);
                    *point = [mx + angle.cos() * radius * ISO_SCALE_X,
                              my + angle.sin() * radius * ISO_SCALE_Y];
                }
                add_batch.polyline_closed(
                    &ring,
                    2.1,
                    linear_rgba_f(color, 0.5 + windup * 0.45, 1.8),
                );
                add_batch.circle(mx, my, 3.0 + windup * 2.0, linear_rgba_f(color, 0.68, 1.6));
            }
        } else if e.ai.sub_state == EnemySubState::QueenVolleyTelegraph {
            // The fan has a locked aim direction. Its outer rails match the shot spread,
            // leaving a clear view of the area the player can dodge outside.
            let aim = if e.ai.charge_dir.length_squared() > 1e-6 {
                e.ai.charge_dir.normalized()
            } else {
                Vec2::new(1.0, 0.0)
            };
            let reach = state.room_radius * 1.8;
            for offset in [-28.0_f32, 0.0, 28.0] {
                let end = e.pos + aim.rotated_deg(offset) * reach;
                let (ex, ey) = to_iso_cam(end, cam_world, view_w, view_h, shake);
                let center = offset == 0.0;
                add_batch.line(
                    sx,
                    sy,
                    ex,
                    ey,
                    if center { 3.2 } else { 2.0 },
                    linear_rgba(
                        if center { [255, 230, 255] } else { [255, 105, 220] },
                        if center { (105.0 + windup * 135.0) as u8 } else { 112 },
                        if center { 2.0 } else { 1.45 },
                    ),
                );
            }
        }
    }

    if e.behavior == "boss_trapmaster"
        && e.ai.sub_state == EnemySubState::TrapmasterTelegraph
    {
        // Lock-on marks sit on the exact spike-trap positions the Warden committed to.
        let count = e.ai.summon_target_count as usize;
        let radius = if e.ai.phase < 2 { 82.0 } else { 92.0 };
        let base_ang = e.ai.sniper_aim.y.atan2(e.ai.sniper_aim.x);
        let alpha = 0.42 + windup * 0.52;
        for i in 0..count {
            let marker = trapmaster_spike_position(
                e.ai.move_target,
                base_ang,
                i,
                count,
                radius,
                state.room_radius,
                &state.map_type,
            );
            let (mx, my) = to_iso_cam(marker, cam_world, view_w, view_h, shake);
            let mut points = [[0.0_f32; 2]; 12];
            for (j, point) in points.iter_mut().enumerate() {
                let a = j as f32 * (TAU / 12.0);
                let (x, y) = to_iso_cam(
                    marker + Vec2::new(a.cos(), a.sin()) * TRAPMASTER_SPIKE_RADIUS,
                    cam_world,
                    view_w,
                    view_h,
                    shake,
                );
                *point = [x, y];
            }
            add_batch.polyline_closed(
                &points,
                2.2,
                linear_rgba_f([255, 155, 85], alpha, 1.9),
            );
            add_batch.circle(mx, my, 2.5, linear_rgba_f([255, 240, 205], alpha, 1.8));
        }

        if e.ai.phase > 0 || e.ai.persona != crate::sim::enemy::BossPersona::Cautious {
            let aim = safe_dir(e.ai.charge_dir, Vec2::new(1.0, 0.0));
            let half_spread = match e.ai.phase {
                0 => 28.0,
                1 => 38.0,
                _ => 44.0,
            };
            for offset in [-half_spread, 0.0, half_spread] {
                let end = e.pos + aim.rotated_deg(offset) * (state.room_radius * 1.6);
                let (ex, ey) = to_iso_cam(end, cam_world, view_w, view_h, shake);
                let center = offset == 0.0;
                add_batch.line(
                    sx,
                    sy,
                    ex,
                    ey,
                    if center { 2.8 } else { 1.7 },
                    linear_rgba(
                        if center { [255, 220, 170] } else { [255, 145, 95] },
                        if center { (90.0 + windup * 145.0) as u8 } else { 82 },
                        if center { 1.8 } else { 1.3 },
                    ),
                );
            }
            if e.ai.phase >= 2
                && matches!(
                    e.ai.persona,
                    crate::sim::enemy::BossPersona::Aggressive
                        | crate::sim::enemy::BossPersona::Trickster
                )
            {
                let side_aim = aim.perp();
                for offset in [-19.0_f32, 0.0, 19.0] {
                    let end = e.pos + side_aim.rotated_deg(offset) * (state.room_radius * 1.45);
                    let (ex, ey) = to_iso_cam(end, cam_world, view_w, view_h, shake);
                    let center = offset == 0.0;
                    add_batch.line(
                        sx,
                        sy,
                        ex,
                        ey,
                        if center { 2.5 } else { 1.6 },
                        linear_rgba(
                            if center { [255, 220, 170] } else { [255, 145, 95] },
                            if center { (85.0 + windup * 135.0) as u8 } else { 78 },
                            if center { 1.75 } else { 1.3 },
                        ),
                    );
                }
            }
        }
    }

    if e.behavior == "boss_abyss_gaze" && e.ai.sub_state == EnemySubState::AbyssTelegraph {
        // Show the locked fan rails before the salvo. Every line matches the released fan.
        let aim = if e.ai.charge_dir.length_squared() > 1e-6 {
            e.ai.charge_dir.normalized()
        } else {
            Vec2::new(1.0, 0.0)
        };
        let half_spread = match e.ai.phase {
            0 => 36.0,
            1 => 41.0,
            _ => 26.0,
        };
        let reach = state.room_radius * 1.8;
        for offset in [-half_spread, 0.0, half_spread] {
            let end = e.pos + aim.rotated_deg(offset) * reach;
            let (ex, ey) = to_iso_cam(end, cam_world, view_w, view_h, shake);
            let center = offset == 0.0;
            add_batch.line(
                sx,
                sy,
                ex,
                ey,
                if center { 3.2 } else { 2.0 },
                linear_rgba(
                    if center { [205, 235, 255] } else { [145, 110, 255] },
                    if center { (95.0 + windup * 145.0) as u8 } else { 88 },
                    if center { 1.9 } else { 1.35 },
                ),
            );
        }
        if e.ai.phase >= 1 {
            let start_angle = e.ai.sniper_aim.y.atan2(e.ai.sniper_aim.x);
            let ring_reach = state.room_radius * 1.18;
            for i in 0..8 {
                let angle = start_angle + i as f32 * (TAU / 8.0);
                let end = to_iso_cam(
                    e.pos + Vec2::new(angle.cos(), angle.sin()) * ring_reach,
                    cam_world,
                    view_w,
                    view_h,
                    shake,
                );
                add_batch.line(
                    sx,
                    sy,
                    end.0,
                    end.1,
                    1.1 + windup * 0.75,
                    linear_rgba_f([165, 195, 255], 0.10 + windup * 0.24, 1.45),
                );
            }
            let rx = r * (1.85 + 0.25 * windup);
            let ry = rx * aspect;
            add_batch.ring(
                sx,
                sy - 4.0,
                rx,
                ry,
                1.8 + windup * 1.1,
                linear_rgba_f([165, 200, 255], 0.28 + windup * 0.42, 1.6),
            );
        }
    }

    if e.behavior == "boss_womb_core" && e.ai.sub_state == EnemySubState::WombPulseTelegraph {
        let aim = safe_dir(e.ai.charge_dir, Vec2::new(1.0, 0.0));
        let half_spread = match e.ai.phase {
            0 => 34.0,
            1 => 41.0,
            _ => 43.0,
        };
        let reach = state.room_radius * 1.75;
        for offset in [-half_spread, 0.0, half_spread] {
            let end = e.pos + aim.rotated_deg(offset) * reach;
            let (ex, ey) = to_iso_cam(end, cam_world, view_w, view_h, shake);
            let center = offset == 0.0;
            add_batch.line(
                sx,
                sy,
                ex,
                ey,
                if center { 3.1 } else { 1.9 },
                linear_rgba(
                    if center { [255, 215, 245] } else { [215, 110, 255] },
                    if center { (95.0 + windup * 140.0) as u8 } else { 88 },
                    if center { 1.9 } else { 1.35 },
                ),
            );
        }
        if e.ai.phase >= 2 {
            let side_aim = aim.perp();
            for offset in [-17.0_f32, 0.0, 17.0] {
                let end = e.pos + side_aim.rotated_deg(offset) * (state.room_radius * 1.5);
                let (ex, ey) = to_iso_cam(end, cam_world, view_w, view_h, shake);
                let center = offset == 0.0;
                add_batch.line(
                    sx,
                    sy,
                    ex,
                    ey,
                    if center { 2.6 } else { 1.7 },
                    linear_rgba(
                        if center { [255, 215, 245] } else { [215, 110, 255] },
                        if center { (88.0 + windup * 130.0) as u8 } else { 80 },
                        if center { 1.75 } else { 1.3 },
                    ),
                );
            }
        }
        if e.ai.phase >= 1 {
            let ring_count: usize = if e.ai.phase == 1 { 7 } else { 6 };
            let start_angle = e.ai.sniper_aim.y.atan2(e.ai.sniper_aim.x);
            let ring_reach = state.room_radius * 1.18;
            for i in 0..ring_count {
                let angle = start_angle + i as f32 * (TAU / ring_count as f32);
                let end = to_iso_cam(
                    e.pos + Vec2::new(angle.cos(), angle.sin()) * ring_reach,
                    cam_world,
                    view_w,
                    view_h,
                    shake,
                );
                add_batch.line(
                    sx,
                    sy,
                    end.0,
                    end.1,
                    1.1 + windup * 0.75,
                    linear_rgba_f([235, 130, 255], 0.10 + windup * 0.25, 1.45),
                );
            }
        }
    }

    if e.behavior == "boss_thunder" && e.ai.sub_state == EnemySubState::ThunderTeleportOut {
        let prog = (1.0 - e.ai.sub_timer / 0.4).clamp(0.0, 1.0);
        let rx = r * (2.1 - 1.65 * prog) * k_spawn;
        let ry = rx * aspect;
        add_batch.ring(
            sx,
            sy - 4.0,
            rx,
            ry,
            2.8 + (1.0 - prog) * 1.4,
            linear_rgba_f([110, 235, 255], 0.45 + 0.45 * prog, 1.9),
        );
    }

    if e.behavior == "boss_thunder" && e.ai.sub_state == EnemySubState::ThunderTeleportIn {
        let prog = (1.0 - e.ai.sub_timer / 0.25).clamp(0.0, 1.0);
        let rx = r * (0.55 + 1.65 * prog) * k_spawn;
        let ry = rx * aspect;
        add_batch.ring(
            sx,
            sy - 4.0,
            rx,
            ry,
            3.6 * (1.0 - prog * 0.6),
            linear_rgba_f([150, 245, 255], (1.0 - prog) * 0.85 + 0.15, 2.1),
        );
        add_batch.glow(
            sx,
            cy,
            r * (1.4 + 0.9 * prog),
            1.8,
            linear_rgba_f([130, 235, 255], (1.0 - prog) * 0.55, 1.8),
        );
    }

    if e.behavior == "boss_eclipse_archon"
        && matches!(
            e.ai.sub_state,
            EnemySubState::EclipseCharge | EnemySubState::EclipseBurst
        )
    {
        let reach = state.room_radius * 1.85;
        let iso_aspect = ISO_SCALE_Y / ISO_SCALE_X;
        let r_scr = reach * SQRT_2 * ISO_SCALE_X;
        let volley = if e.ai.sub_state == EnemySubState::EclipseBurst {
            (e.ai.gun_idx as i32).min(e.ai.phase.max(0))
        } else {
            0
        };
        let safe_angle = eclipse_safe_angle(e, volley);
        let half_w = ECLIPSE_GAP_HALF_WIDTH;
        let wedge_alpha = if e.ai.sub_state == EnemySubState::EclipseCharge {
            0.055 + windup * 0.055
        } else {
            0.09
        };
        alpha_batch.sector(
            sx,
            sy,
            r_scr,
            safe_angle - half_w + FRAC_PI_4,
            half_w * 2.0,
            iso_aspect,
            linear_rgba_f([60, 255, 204], wedge_alpha, 1.1),
        );
        for sign in [-1.0_f32, 1.0] {
            let edge_ang = safe_angle + sign * half_w;
            let dir = Vec2::new(edge_ang.cos(), edge_ang.sin());
            let (sx0, sy0) = to_iso_cam(e.pos + dir * 24.0, cam_world, view_w, view_h, shake);
            let (ex, ey) = to_iso_cam(e.pos + dir * reach, cam_world, view_w, view_h, shake);
            add_batch.line(
                sx0,
                sy0,
                ex,
                ey,
                6.5,
                linear_rgba_f([75, 255, 224], 0.24 + windup * 0.14, 1.65),
            );
            add_batch.line(
                sx0,
                sy0,
                ex,
                ey,
                2.0,
                linear_rgba_f([198, 255, 244], 0.72 + windup * 0.2, 1.85),
            );
        }
        if e.ai.sub_state == EnemySubState::EclipseCharge && e.ai.phase >= 1 {
            for preview_volley in 1..=e.ai.phase.min(2) {
                let next_angle = eclipse_safe_angle(e, preview_volley);
                let fade = if preview_volley == 1 { 0.45 } else { 0.28 };
                for sign in [-1.0_f32, 1.0] {
                    let edge_ang = next_angle + sign * half_w;
                    let dir = Vec2::new(edge_ang.cos(), edge_ang.sin());
                    let (sx0, sy0) = to_iso_cam(e.pos + dir * 26.0, cam_world, view_w, view_h, shake);
                    let (ex, ey) = to_iso_cam(e.pos + dir * (reach * 0.7), cam_world, view_w, view_h, shake);
                    add_batch.line(
                        sx0,
                        sy0,
                        ex,
                        ey,
                        1.5,
                        linear_rgba_f([135, 230, 255], (0.22 + windup * 0.25) * fade, 1.4),
                    );
                }
                let center_dir = Vec2::new(next_angle.cos(), next_angle.sin());
                let (cx0, cy0) = to_iso_cam(e.pos + center_dir * 26.0, cam_world, view_w, view_h, shake);
                let (cx1, cy1) = to_iso_cam(e.pos + center_dir * (reach * 0.5), cam_world, view_w, view_h, shake);
                add_batch.line(
                    cx0,
                    cy0,
                    cx1,
                    cy1,
                    1.6,
                    linear_rgba_f([165, 255, 235], (0.28 + windup * 0.3) * fade, 1.5),
                );
            }
        }
    }

    if e.behavior == "boss_thunder" && e.ai.sub_state == EnemySubState::ThunderWindup {
        let ring_count = e.ai.laser_tick.round().max(3.0) as usize;
        let start_angle = e.ai.charge_dir.y.atan2(e.ai.charge_dir.x);
        let start = to_iso_cam(e.pos, cam_world, view_w, view_h, shake);
        let reach = state.room_radius * 1.22;
        let spoke_alpha = 0.09 + windup * 0.25;
        for i in 0..ring_count {
            let angle = start_angle + i as f32 * (TAU / ring_count as f32);
            let end = to_iso_cam(
                e.pos + Vec2::new(angle.cos(), angle.sin()) * reach,
                cam_world,
                view_w,
                view_h,
                shake,
            );
            add_batch.line(
                start.0,
                start.1,
                end.0,
                end.1,
                1.15 + windup * 0.9,
                linear_rgba_f([255, 224, 126], spoke_alpha, 1.45),
            );
        }
        if e.ai.phase >= 2 {
            let second_count = (ring_count / 2).max(3);
            let interlace = PI / ring_count as f32;
            for i in 0..second_count {
                let angle = start_angle + interlace + i as f32 * (TAU / second_count as f32);
                let end = to_iso_cam(
                    e.pos + Vec2::new(angle.cos(), angle.sin()) * reach,
                    cam_world,
                    view_w,
                    view_h,
                    shake,
                );
                add_batch.line(
                    start.0,
                    start.1,
                    end.0,
                    end.1,
                    1.0 + windup * 0.65,
                    linear_rgba_f([255, 154, 105], 0.07 + windup * 0.2, 1.35),
                );
            }
        }
    }

    if crate::render::models3d::draw_boss_model(
        e,
        alpha_batch,
        add_batch,
        [sx, cy],
        model_facing,
        boss_model_scale(&e.behavior, r),
        et,
        windup,
        render_col,
        reduce_motion,
    ) {
        return;
    }

    // 2. Boss-Specific Multi-Part Architecture fallback for any unmodeled boss.
    match e.behavior.as_str() {
        "boss_thunder" => {
            // Storm Sovereign: Cruciform citadel + 4 orbiting Tesla pylons + live crackling arcs
            let cruciform = [
                [sx, cy + r * 1.25],
                [sx + r * 0.48, cy + r * 0.45],
                [sx + r * 1.25, cy],
                [sx + r * 0.48, cy - r * 0.45],
                [sx, cy - r * 1.25],
                [sx - r * 0.48, cy - r * 0.45],
                [sx - r * 1.25, cy],
                [sx - r * 0.48, cy + r * 0.45],
            ];
            draw_hull(alpha_batch, &cruciform, hull_fill, hull_rim, 2.2);
            alpha_batch.circle(sx, cy, r * 0.48, dark_plate);
            let storm_core = mix_rgb([200, 240, 255], [255, 232, 142], windup * 0.8);
            add_batch.circle(
                sx,
                cy,
                r * (0.28 + windup * 0.1),
                linear_rgba(storm_core, 245, 2.3 + windup * 0.8),
            );

            let mut pylons = [[0.0_f32; 2]; 4];
            let p_rot = et * if raged { 2.2 } else { 1.15 };
            for i in 0..4 {
                let a = p_rot + i as f32 * FRAC_PI_2;
                let px = sx + a.cos() * (r * 1.48);
                let py = cy + a.sin() * (r * 1.12);
                pylons[i] = [px, py];
                let d_poly = reg_poly(px, py, r * 0.28, 4, a, 1.0);
                draw_hull(alpha_batch, &d_poly, linear_rgba([30, 50, 85], 245, 1.0), hull_rim, 1.5);
                let pylon_core = mix_rgb([215, 248, 255], [255, 230, 145], windup * 0.78);
                add_batch.circle(px, py, r * (0.14 + windup * 0.045), linear_rgba(pylon_core, 250, 2.2 + windup * 0.6));
            }
            let flick = (et * 18.0) as u32;
            for i in 0..4 {
                let a = pylons[i];
                let b = pylons[(i + 1) % 4];
                let mid = [(a[0] + b[0]) * 0.5 + (hash_u32(flick ^ (i as u32 * 97)) - 0.5) * 14.0, (a[1] + b[1]) * 0.5 + (hash_u32(flick ^ (i as u32 * 193)) - 0.5) * 14.0];
                add_batch.line(a[0], a[1], mid[0], mid[1], 2.4 + windup, linear_rgba([150, 225, 255], 210, 2.0 + windup * 0.6));
                add_batch.line(mid[0], mid[1], b[0], b[1], 2.4 + windup, linear_rgba([235, 250, 255], 235, 2.2 + windup * 0.6));
            }
            if e.ai.sub_state == EnemySubState::ThunderWindup {
                let ring_count = e.ai.laser_tick.round().max(3.0) as usize;
                let start_angle = e.ai.charge_dir.y.atan2(e.ai.charge_dir.x);
                let start = to_iso_cam(e.pos, cam_world, view_w, view_h, shake);
                let reach = state.room_radius * 1.22;
                let main_alpha = 0.09 + windup * 0.25;
                for i in 0..ring_count {
                    let angle = start_angle + i as f32 * (TAU / ring_count as f32);
                    let end = to_iso_cam(
                        e.pos + Vec2::new(angle.cos(), angle.sin()) * reach,
                        cam_world,
                        view_w,
                        view_h,
                        shake,
                    );
                    add_batch.line(
                        start.0,
                        start.1,
                        end.0,
                        end.1,
                        1.15 + windup * 0.9,
                        linear_rgba_f([255, 224, 126], main_alpha, 1.45),
                    );
                }
                if e.ai.phase >= 2 {
                    let second_count = (ring_count / 2).max(3);
                    let interlace = PI / ring_count as f32;
                    for i in 0..second_count {
                        let angle = start_angle
                            + interlace
                            + i as f32 * (TAU / second_count as f32);
                        let end = to_iso_cam(
                            e.pos + Vec2::new(angle.cos(), angle.sin()) * reach,
                            cam_world,
                            view_w,
                            view_h,
                            shake,
                        );
                        add_batch.line(
                            start.0,
                            start.1,
                            end.0,
                            end.1,
                            1.0 + windup * 0.65,
                            linear_rgba_f([255, 154, 105], 0.07 + windup * 0.2, 1.35),
                        );
                    }
                }
            }
        }
        "boss_laser" => {
            // Prisma Overlord: 3 orbiting collimator blades squeezing inward on charge + central lens
            let hex = reg_poly(sx, cy, r * 0.92, 6, et * 0.4, 0.92);
            draw_hull(alpha_batch, &hex, hull_fill, hull_rim, 2.2);
            let squeeze = 1.38 - 0.34 * windup;
            let spin = et * if e.ai.sub_state == EnemySubState::LaserAttack { 2.6 } else { 0.9 };
            for i in 0..3 {
                let a = spin + i as f32 * (TAU / 3.0);
                let cx_b = sx + a.cos() * (r * squeeze);
                let cy_b = cy + a.sin() * (r * squeeze * 0.82);
                let perp = [-a.sin(), a.cos()];
                let petal = [
                    [cx_b + a.cos() * r * 0.45, cy_b + a.sin() * r * 0.45],
                    [cx_b + perp[0] * r * 0.34, cy_b + perp[1] * r * 0.34],
                    [cx_b - perp[0] * r * 0.34, cy_b - perp[1] * r * 0.34],
                ];
                draw_hull(alpha_batch, &petal, linear_rgba([210, 85, 240], 240, 1.3), hull_rim, 1.6);
            }
            alpha_batch.circle(sx, cy, r * 0.46, dark_plate);
            add_batch.circle(sx, cy, r * (0.26 + 0.14 * windup), linear_rgba([255, 165, 255], 245, 2.2));
            add_batch.circle(sx, cy, r * 0.12, linear_rgba([255, 255, 255], 255, 2.5));
        }
        "boss_trapmaster" => {
            // Forge Warden: Notched rotating cogwheel armor + twin hydraulic launcher claws
            let oct = reg_poly(sx, cy, r * 1.12, 8, et * 0.55, 0.88);
            draw_hull(alpha_batch, &oct, hull_fill, hull_rim, 2.4);
            let gear_r = r * 1.32;
            for i in 0..8 {
                let a = et * 0.55 + i as f32 * (PI / 4.0);
                let gx = sx + a.cos() * gear_r;
                let gy = cy + a.sin() * gear_r * 0.88;
                alpha_batch.circle(gx, gy, r * 0.18, linear_rgba([255, 185, 85], 235, 1.25));
            }
            for s in [-1.0_f32, 1.0] {
                let jaw_open = 0.12 * windup;
                let jaw = [
                    pt_local(sx, cy, f, rt, r * 0.45, s * r * 0.65),
                    pt_local(sx, cy, f, rt, r * (1.35 + jaw_open), s * r * 0.42),
                    pt_local(sx, cy, f, rt, r * (1.15 + jaw_open), s * r * (0.95 + windup * 0.08)),
                    pt_local(sx, cy, f, rt, r * 0.15, s * r * 1.05),
                ];
                draw_hull(alpha_batch, &jaw, linear_rgba([55, 42, 32], 245, 1.0), linear_rgba([255, 195, 95], 235, 1.5), 1.6);
            }
            alpha_batch.circle(sx, cy, r * 0.45, dark_plate);
            add_batch.circle(sx, cy, r * (0.25 + 0.13 * windup), linear_rgba([255, 195, 70], 245, 2.1 + windup * 0.8));
        }
        "boss_brute" => {
            // Gorgon Juggernaut: Huge directional battering-ram hull + twin massive curved tusks
            draw_thruster(add_batch, sx, cy, f, rt, r * 0.92, -r * 0.52, r * 1.15, 5.2, [255, 130, 65], et);
            draw_thruster(add_batch, sx, cy, f, rt, r * 0.92, r * 0.52, r * 1.15, 5.2, [255, 130, 65], et);
            let chassis = [
                pt_local(sx, cy, f, rt, r * 1.18, r * 0.42),
                pt_local(sx, cy, f, rt, r * 1.18, -r * 0.42),
                pt_local(sx, cy, f, rt, -r * 0.65, -r * 1.15),
                pt_local(sx, cy, f, rt, -r * 0.98, 0.0),
                pt_local(sx, cy, f, rt, -r * 0.65, r * 1.15),
            ];
            draw_hull(alpha_batch, &chassis, hull_fill, hull_rim, 2.4);
            for s in [-1.0_f32, 1.0] {
                let t0 = pt_local(sx, cy, f, rt, r * 0.72, s * r * 0.55);
                let t1 = pt_local(sx, cy, f, rt, r * 1.65, s * r * 0.78);
                let t2 = pt_local(sx, cy, f, rt, r * 0.42, s * r * 0.96);
                alpha_batch.triangle(t0, t1, t2, linear_rgba([255, 245, 230], 245, 1.25));
                alpha_batch.line(t0[0], t0[1], t1[0], t1[1], 2.2, linear_rgba([255, 255, 255], 235, 1.4));
            }
            let visor = pt_local(sx, cy, f, rt, r * 0.35, 0.0);
            add_batch.circle(visor[0], visor[1], r * (0.28 + 0.14 * windup), linear_rgba([255, 145, 85], 245, 2.1));
        }
        "boss_abyss_gaze" => {
            // Ocular Abyss: 6 undulating eldritch tentacles + player-tracking pupil
            for ti in 0..6 {
                let base_a = et * 0.45 + ti as f32 * (TAU / 6.0);
                let mut prev = [sx + base_a.cos() * r * 0.72, cy + base_a.sin() * r * 0.62];
                for seg in 1..=3 {
                    let frac = seg as f32 / 3.0;
                    let sw = (et * 3.8 + ti as f32 * 1.1 + seg as f32 * 0.8).sin() * 0.28 * frac;
                    let a = base_a + sw;
                    let rad = r * (0.72 + frac * (0.95 - windup * 0.24));
                    let cur = [sx + a.cos() * rad, cy + a.sin() * rad * 0.85];
                    alpha_batch.line(prev[0], prev[1], cur[0], cur[1], (5.8 - frac * 3.2).max(2.0), linear_rgba([55, 32, 115], 235, 1.1));
                    add_batch.line(prev[0], prev[1], cur[0], cur[1], (2.2 - frac).max(1.0), linear_rgba([135, 115, 255], 175, 1.6));
                    prev = cur;
                }
            }
            let dome = reg_poly(sx, cy, r * 0.98, 12, 0.0, 0.96);
            draw_hull(alpha_batch, &dome, hull_fill, hull_rim, 2.2);
            alpha_batch.circle(sx, cy, r * 0.64, linear_rgba([10, 14, 30], 250, 1.0));
            let px = sx + af[0] * (r * 0.24);
            let py = cy + af[1] * (r * 0.24);
            add_batch.circle(px, py, r * (0.28 + 0.13 * windup), linear_rgba([165, 220, 255], 245, 2.2 + windup * 0.7));
            add_batch.line(px - af[1] * 2.0, py + af[0] * 2.0 - 6.0, px + af[1] * 2.0, py - af[0] * 2.0 + 6.0, 2.6, linear_rgba([255, 255, 255], 250, 2.4));
        }
        "boss_womb_core" => {
            // Origin Nexus: 3 nested counter-rotating gyroscopes + beating cosmic heart
            let hex = reg_poly(sx, cy, r * 0.78, 6, et * 0.5, 0.94);
            draw_hull(alpha_batch, &hex, hull_fill, hull_rim, 2.0);
            for gi in 0..3 {
                let speed = if gi % 2 == 0 { 1.4 } else { -1.8 } + gi as f32 * 0.4;
                let g_pts = reg_poly(sx, cy, r * (1.06 + gi as f32 * 0.20), 16, et * speed, if gi == 1 { 0.56 } else { 0.84 });
                let gcol = if raged { [255, 120, 155] } else { [255, 175, 215] };
                add_batch.polyline_closed(&g_pts, 2.2, linear_rgba_f(gcol, 0.78 - gi as f32 * 0.14, 1.8));
            }
            let beat = 1.0 + 0.18 * (et * 5.2).sin().abs();
            add_batch.circle(sx, cy, r * 0.36 * beat, linear_rgba([255, 135, 185], 240, 2.0));
            add_batch.circle(sx, cy, r * 0.18 * beat, linear_rgba([255, 240, 250], 255, 2.4));
        }
        "boss_eclipse_archon" => {
            // Eclipse Archon: a black sun held inside a rotating, eight-point stellar crown.
            let spin = et * if raged { 1.35 } else { 0.62 };
            for ring in 0..3 {
                let radius = r * (1.08 + ring as f32 * 0.24);
                let tilt = if ring == 1 { -spin * 0.72 } else { spin };
                let orbit = reg_poly(sx, cy, radius, 18, tilt, if ring == 1 { 0.55 } else { 0.82 });
                let color = if ring == 1 { [157, 135, 255] } else { [105, 235, 220] };
                add_batch.polyline_closed(
                    &orbit,
                    2.0,
                    linear_rgba_f(color, if ring == 2 { 0.38 } else { 0.7 }, 1.65),
                );
            }

            for i in 0..8 {
                let a = spin + i as f32 * (TAU / 8.0);
                let inner = [sx + a.cos() * r * 0.72, cy + a.sin() * r * 0.58];
                let length = if i % 2 == 0 { 1.42 } else { 1.14 };
                let tip = [sx + a.cos() * r * length, cy + a.sin() * r * length * 0.78];
                alpha_batch.line(inner[0], inner[1], tip[0], tip[1], 5.0, dark_plate);
                alpha_batch.line(inner[0], inner[1], tip[0], tip[1], 2.4, hull_rim);
                add_batch.circle(tip[0], tip[1], r * 0.075, linear_rgba(rage_col, 225, 1.7));
            }

            let hull = reg_poly(sx, cy, r * 0.82, 8, spin * -0.28, 0.9);
            draw_hull(alpha_batch, &hull, hull_fill, hull_rim, 2.4);
            alpha_batch.circle(sx, cy, r * 0.58, linear_rgba([5, 13, 24], 255, 1.0));
            add_batch.circle(sx, cy, r * (0.39 + windup * 0.12), linear_rgba(rage_col, 235, 1.9));
            add_batch.circle(sx, cy, r * 0.21, linear_rgba([225, 255, 249], 248, 2.3));

            for i in 0..4 {
                let a = -spin * 1.4 + i as f32 * FRAC_PI_2;
                let px = sx + a.cos() * r * 1.53;
                let py = cy + a.sin() * r * 1.03;
                let satellite = reg_poly(px, py, r * 0.19, 4, a + PI * 0.25, 0.9);
                draw_hull(
                    alpha_batch,
                    &satellite,
                    linear_rgba([13, 28, 44], 246, 1.0),
                    linear_rgba([170, 255, 237], 230, 1.35),
                    1.5,
                );
                add_batch.circle(px, py, r * 0.07, linear_rgba([190, 255, 242], 240, 1.8));
            }
        }
        _ => {
            let hull = reg_poly(sx, cy, r, 6, et * 0.5, 0.9);
            draw_hull(alpha_batch, &hull, hull_fill, hull_rim, 2.0);
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn draw_offscreen_indicators(
    state: &SimState,
    interp: f32,
    cam_world: Vec2,
    view_w: f32,
    view_h: f32,
    shake: Vec2,
    motion_t: f32,
    ui_alpha: &mut SdfBatch,
    ui_text: &mut TextBatch,
    ui_scale: f32,
) {
    let pad = 26.0 * ui_scale.clamp(0.85, 1.4);
    let min_x = pad;
    let max_x = (view_w - pad).max(pad + 1.0);
    let min_y = pad;
    let max_y = (view_h - pad).max(pad + 1.0);
    let cx = view_w * 0.5;
    let cy = view_h * 0.5;

    let draw_chevron = |ui_alpha: &mut SdfBatch, sx: f32, sy: f32, size: f32, col: [u8; 3], bright: bool| {
        let dx = sx - cx;
        let dy = sy - cy;
        let dist_len = dx.hypot(dy).max(1.0);
        let dir = [dx / dist_len, dy / dist_len];
        let perp = [-dir[1], dir[0]];
        let tx = if dir[0].abs() > 1e-4 {
            if dir[0] > 0.0 { (max_x - cx) / dir[0] } else { (min_x - cx) / dir[0] }
        } else { 1e9 };
        let ty = if dir[1].abs() > 1e-4 {
            if dir[1] > 0.0 { (max_y - cy) / dir[1] } else { (min_y - cy) / dir[1] }
        } else { 1e9 };
        let t_edge = tx.min(ty);
        let ex = (cx + dir[0] * t_edge).clamp(min_x, max_x);
        let ey = (cy + dir[1] * t_edge).clamp(min_y, max_y);

        let tip = [ex + dir[0] * size * 0.7, ey + dir[1] * size * 0.7];
        let b1 = [ex - dir[0] * size * 0.6 + perp[0] * size * 0.65, ey - dir[1] * size * 0.6 + perp[1] * size * 0.65];
        let b2 = [ex - dir[0] * size * 0.6 - perp[0] * size * 0.65, ey - dir[1] * size * 0.6 - perp[1] * size * 0.65];
        ui_alpha.triangle(tip, b1, b2, linear_rgba([8, 12, 22], 235, 1.0));
        let in_tip = [ex + dir[0] * size * 0.5, ey + dir[1] * size * 0.5];
        let in_b1 = [ex - dir[0] * size * 0.45 + perp[0] * size * 0.46, ey - dir[1] * size * 0.45 + perp[1] * size * 0.46];
        let in_b2 = [ex - dir[0] * size * 0.45 - perp[0] * size * 0.46, ey - dir[1] * size * 0.45 - perp[1] * size * 0.46];
        ui_alpha.triangle(in_tip, in_b1, in_b2, linear_rgba(col, if bright { 245 } else { 205 }, 1.25));
        (ex, ey, dir)
    };

    // Offscreen enemies (always show bosses + up to 8 closest offscreen threats)
    let mut normals: Vec<(f32, f32, f32, [u8; 3])> = Vec::new();
    for e in &state.enemies {
        if e.is_dead || e.hp <= 0 {
            continue;
        }
        let p = lerp_v2(e.prev_pos, e.pos, interp);
        let (sx, sy) = to_iso_cam(p, cam_world, view_w, view_h, shake);
        if sx >= 0.0 && sx <= view_w && sy >= 0.0 && sy <= view_h {
            continue;
        }
        let col = enemy_color(&e.behavior, state.runtime.colorblind_palette);
        if e.is_boss() {
            let pulse = 1.0 + 0.14 * (motion_t * 6.0).sin();
            let (ex, ey, dir) = draw_chevron(ui_alpha, sx, sy, 14.0 * ui_scale * pulse, col, true);
            ui_text.draw(
                "BOSS",
                FontId::Bold,
                (9.0 * ui_scale).clamp(8.0, 12.0),
                ex - dir[0] * 18.0 * ui_scale,
                ey - dir[1] * 18.0 * ui_scale,
                AlignX::Center,
                AlignY::Center,
                [255, 220, 230],
                235,
                true,
            );
        } else if e.behavior == "sniper" && e.ai.sub_state == EnemySubState::SniperWindup {
            let pulse = if state.runtime.reduce_motion {
                1.0
            } else {
                1.0 + 0.16 * (motion_t * 10.0).sin()
            };
            draw_chevron(
                ui_alpha,
                sx,
                sy,
                12.0 * ui_scale * pulse,
                [255, 112, 165],
                true,
            );
        } else {
            let d2 = (sx - cx).powi(2) + (sy - cy).powi(2);
            normals.push((d2, sx, sy, col));
        }
    }
    normals.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    for (_, sx, sy, col) in normals.into_iter().take(8) {
        draw_chevron(ui_alpha, sx, sy, 8.5 * ui_scale, col, false);
    }

    // Offscreen rare pickups
    for pu in &state.powerups {
        if !is_rare_powerup(&pu.kind) {
            continue;
        }
        let (sx, sy) = to_iso_cam(pu.pos, cam_world, view_w, view_h, shake);
        if sx >= 0.0 && sx <= view_w && sy >= 0.0 && sy <= view_h {
            continue;
        }
        let col = powerup_color(&pu.kind);
        let (ex, ey, dir) = draw_chevron(ui_alpha, sx, sy, 11.5 * ui_scale, col, true);
        let meta = powerup_meta(&pu.kind);
        ui_text.draw(
            meta.short_code,
            FontId::Bold,
            (8.5 * ui_scale).clamp(8.0, 11.5),
            ex - dir[0] * 16.0 * ui_scale,
            ey - dir[1] * 16.0 * ui_scale,
            AlignX::Center,
            AlignY::Center,
            mix_rgb(col, [255, 255, 255], 0.55),
            230,
            true,
        );
    }
}

#[allow(clippy::too_many_arguments)]
fn draw_powerup(
    pu: &crate::sim::powerup::PowerUp,
    player_pos: Vec2,
    cam_world: Vec2,
    enable_edges: bool,
    enable_glow: bool,
    motion_t: f32,
    view_w: f32,
    view_h: f32,
    shake: Vec2,
    alpha_batch: &mut SdfBatch,
    add_batch: &mut SdfBatch,
    ui_text: &mut TextBatch,
    ui_scale: f32,
) {
    let col = powerup_color(&pu.kind);
    let _ = powerup_meta(&pu.kind);
    draw_powerup_pickup(
        pu.pos,
        &pu.kind,
        pu.ttl,
        col,
        player_pos,
        cam_world,
        view_w,
        view_h,
        shake,
        motion_t,
        enable_edges,
        enable_glow,
        alpha_batch,
        add_batch,
        ui_text,
        ui_scale,
    );
}

#[allow(clippy::too_many_arguments)]
fn draw_projectile(
    p: &Projectile,
    interp: f32,
    motion_t: f32,
    signatures_on: bool,
    glow_on: bool,
    shot_pal: Option<&Palette>,
    player_pos: Vec2,
    cam_world: Vec2,
    view_w: f32,
    view_h: f32,
    shake: Vec2,
    alpha_batch: &mut SdfBatch,
    add_batch: &mut SdfBatch,
) {
    let prev = p.prev_pos.unwrap_or(p.pos);
    let pos = lerp_v2(prev, p.pos, interp);
    let (sx, sy) = to_iso_cam(pos, cam_world, view_w, view_h, shake);

    // Flak lobbed parabolic cluster grenade
    if p.cluster_on_death && p.owner == "player" {
        let total = 0.55_f32;
        let u = (1.0 - (p.ttl / total).clamp(0.0, 1.0)).clamp(0.0, 1.0);
        let lift = 4.0 * u * (1.0 - u) * FLAK_LIFT_PX;
        alpha_batch.ellipse(sx, sy - 6.0, 8.0, 3.0, 0.0, linear_rgba([0, 0, 0], 110, 1.0));
        if p.ttl < 0.22 {
            let warn_r = 22.0 * (1.0 - p.ttl / 0.22);
            add_batch.ring(sx, sy, warn_r.max(4.0), (warn_r * 0.5).max(2.0), 2.0, linear_rgba([255, 175, 70], 160, 1.6));
        }
        let col = if p.is_crit { [255, 225, 95] } else { [255, 155, 55] };
        add_batch.glow(sx, sy + lift, 18.0, 1.8, linear_rgba(col, 110, 1.6));
        alpha_batch.circle(sx, sy + lift, 5.5, linear_rgba(col, 255, 1.25));
        add_batch.circle(sx, sy + lift, 2.5, linear_rgba([255, 245, 210], 255, 2.0));
        return;
    }

    // Enemy projectiles & signature shapes (`spitter`, `ranged`, `bomber`, `boss`)
    if p.owner == "enemy" {
        if signatures_on && !p.source.is_empty() {
            let ring_pulse = 1.0 + SIG_RING_PULSE * (motion_t * SIG_PULSE_RATE).sin();
            match p.source.as_str() {
                "spitter" => {
                    let dir = if p.vel.length_squared() > 1e-6 { p.vel.normalized() } else { Vec2::new(1.0, 0.0) };
                    let (tx, ty) = to_iso_cam(pos - dir * (SIG_SPITTER_TRAIL * 0.5), cam_world, view_w, view_h, shake);
                    add_batch.line(tx, ty, sx, sy, 4.1, linear_rgba(SIG_SPITTER_COLOR, 175, 1.5));
                    alpha_batch.circle(sx, sy, SIG_SPITTER_RADIUS * 1.18, linear_rgba(SIG_SPITTER_COLOR, 250, 1.1));
                    add_batch.circle(sx, sy, 2.55, linear_rgba(SIG_SPITTER_CORE, 255, 1.8));
                    return;
                }
                "ranged" => {
                    let dir = if p.vel.length_squared() > 1e-6 { p.vel.normalized() } else { Vec2::new(1.0, 0.0) };
                    let (tx, ty) = to_iso_cam(pos - dir * (SIG_RANGED_LENGTH * 1.05), cam_world, view_w, view_h, shake);
                    add_batch.line(tx, ty, sx, sy, 4.85, linear_rgba(SIG_RANGED_COLOR, 205, 1.65));
                    add_batch.line(tx, ty, sx, sy, 2.0, linear_rgba(SIG_RANGED_CORE, 255, 2.1));
                    return;
                }
                "bomber" => {
                    let is_bomb = p.projectile_type == "bomb";
                    let flight_duration = p.flight_duration.max(0.001);
                    let u = (1.0 - p.ttl.max(0.0) / flight_duration).clamp(0.0, 1.0);
                    let lift = if is_bomb { 4.0 * u * (1.0 - u) * 48.0 } else { 0.0 };
                    if is_bomb {
                        let detonation_pos = pos + p.vel * p.ttl.max(0.0);
                        let (dx, dy) = to_iso_cam(detonation_pos, cam_world, view_w, view_h, shake);
                        let blast_r = crate::sim::config::BOMB_BLAST_RADIUS * SQRT_2 * ISO_SCALE_X;
                        let aspect = ISO_SCALE_Y / ISO_SCALE_X;
                        alpha_batch.ellipse(
                            dx,
                            dy,
                            blast_r,
                            blast_r * aspect,
                            0.0,
                            linear_rgba_f([255, 116, 52], 0.035 + u * 0.06, 1.0),
                        );
                        add_batch.ring(
                            dx,
                            dy,
                            blast_r,
                            blast_r * aspect,
                            1.6 + u * 1.1,
                            linear_rgba_f([255, 132, 62], 0.3 + u * 0.3, 1.4),
                        );
                        add_batch.arc_aspect(
                            dx,
                            dy,
                            blast_r * 0.84,
                            3.0,
                            -FRAC_PI_2,
                            TAU * u,
                            aspect,
                            linear_rgba_f([255, 238, 198], 0.58 + u * 0.24, 1.55),
                        );
                        alpha_batch.ellipse(
                            sx,
                            sy - 6.0,
                            8.0,
                            3.5,
                            0.0,
                            linear_rgba([0, 0, 0], 115, 1.0),
                        );
                    }
                    let by = sy + lift;
                    if glow_on {
                        add_batch.glow(sx, by, if is_bomb { 24.0 } else { 20.0 }, 1.8, linear_rgba(SIG_BOMBER_COLOR, SIG_GLOW_OPACITY, 1.6));
                    }
                    let bomb_scale = if is_bomb { 1.26 } else { 1.05 };
                    add_batch.ring(sx, by, SIG_BOMBER_RING * bomb_scale * ring_pulse, SIG_BOMBER_RING * bomb_scale * ring_pulse, 2.8, linear_rgba(SIG_BOMBER_COLOR, 225, 1.6));
                    alpha_batch.circle(sx, by, 7.2 * bomb_scale, linear_rgba(SIG_BOMBER_COLOR, 245, 1.15));
                    add_batch.circle(sx, by, 3.5 * bomb_scale, linear_rgba(SIG_BOMBER_CORE, 255, 1.9));
                    return;
                }
                "reflector" => {
                    let dir = if p.vel.length_squared() > 1e-6 { p.vel.normalized() } else { Vec2::new(1.0, 0.0) };
                    let (tx, ty) = to_iso_cam(pos - dir * 22.0, cam_world, view_w, view_h, shake);
                    add_batch.line(tx, ty, sx, sy, 4.6, linear_rgba([255, 215, 95], 215, 1.75));
                    add_batch.line(tx, ty, sx, sy, 2.1, linear_rgba(ELITE_REFLECTOR_COLOR, 255, 2.1));
                    alpha_batch.circle(sx, sy, 5.4, linear_rgba([255, 225, 120], 245, 1.25));
                    add_batch.circle(sx, sy, 2.6, linear_rgba([255, 250, 225], 255, 2.0));
                    return;
                }
                "boss" => {
                    if glow_on {
                        add_batch.glow(sx, sy, 26.0, 1.8, linear_rgba(SIG_BOSS_COLOR, SIG_GLOW_OPACITY, 1.8));
                    }
                    add_batch.ring(sx, sy, SIG_BOSS_RING * 1.15 * ring_pulse, SIG_BOSS_RING * 1.15 * ring_pulse, 3.1, linear_rgba(SIG_BOSS_COLOR, 230, 1.8));
                    alpha_batch.circle(sx, sy, 8.2, linear_rgba(SIG_BOSS_COLOR, 250, 1.25));
                    add_batch.circle(sx, sy, 4.0, linear_rgba(SIG_BOSS_CORE, 255, 2.1));
                    return;
                }
                _ => {}
            }
        }
        // Fallback enemy orb
        if glow_on {
            add_batch.glow(sx, sy, 15.0, 1.8, linear_rgba(ENEMY_HEAD, 100, 1.5));
        }
        alpha_batch.circle(sx, sy, 6.3, linear_rgba(ENEMY_HEAD, 250, 1.15));
        add_batch.circle(sx, sy, 3.0, linear_rgba([255, 215, 190], 255, 1.8));
        return;
    }

    // Echo homing bolt
    if p.is_echo {
        let dir = if p.vel.length_squared() > 1e-6 { p.vel.normalized() } else { Vec2::new(1.0, 0.0) };
        let (tx, ty) = to_iso_cam(pos - dir * 16.0, cam_world, view_w, view_h, shake);
        add_batch.line(tx, ty, sx, sy, 4.6, linear_rgba(ECHO_COLOR, 205, 1.8));
        add_batch.circle(sx, sy, 4.8, linear_rgba([255, 255, 255], 245, 2.1));
        return;
    }

    // Ground-targeted mortar: keep the landing cue on the floor while the
    // shell follows a compact ballistic arc above its moving ground shadow.
    if p.owner == "player" && p.projectile_type == "mortar" {
        let flight_duration = p.flight_duration.max(0.001);
        let flight_progress = (1.0 - p.ttl.max(0.0) / flight_duration).clamp(0.0, 1.0);
        let lift = (flight_progress * PI).sin().max(0.0)
            * crate::sim::config::PLAYER_MORTAR_ARC_HEIGHT_PX;
        let dir = if p.vel.length_squared() > 1e-6 {
            p.vel.normalized()
        } else {
            Vec2::new(1.0, 0.0)
        };
        let landing = pos + p.vel * p.ttl.max(0.0);
        let (lx, ly) = to_iso_cam(landing, cam_world, view_w, view_h, shake);
        let blast_radius = crate::sim::config::PLAYER_MORTAR_BLAST_RADIUS
            * SQRT_2
            * ISO_SCALE_X;
        let iso_aspect = ISO_SCALE_Y / ISO_SCALE_X;
        let pulse = 1.0 + 0.025 * (motion_t * 5.0).sin();

        alpha_batch.ellipse(
            lx,
            ly,
            blast_radius * pulse,
            blast_radius * iso_aspect * pulse,
            0.0,
            linear_rgba_f([255, 116, 52], 0.045, 1.0),
        );
        add_batch.ring(
            lx,
            ly,
            blast_radius * pulse,
            blast_radius * iso_aspect * pulse,
            2.2,
            linear_rgba_f([255, 132, 62], 0.52, 1.35),
        );
        add_batch.arc_aspect(
            lx,
            ly,
            blast_radius * 0.86,
            2.7,
            -FRAC_PI_2,
            TAU * flight_progress,
            iso_aspect,
            linear_rgba_f([255, 226, 175], 0.88, 1.35),
        );
        alpha_batch.ellipse(lx, ly, 7.0, 3.8, 0.0, linear_rgba([255, 204, 132], 205, 1.0));
        add_batch.line(lx - 12.0, ly, lx + 12.0, ly, 1.2, linear_rgba([255, 227, 190], 185, 1.0));
        add_batch.line(lx, ly - 6.0, lx, ly + 6.0, 1.2, linear_rgba([255, 227, 190], 185, 1.0));

        let (tail_x, tail_y) = to_iso_cam(
            pos - dir * 15.0,
            cam_world,
            view_w,
            view_h,
            shake,
        );
        let screen_dir = Vec2::new(
            (dir.x - dir.y) * ISO_SCALE_X,
            (dir.x + dir.y) * ISO_SCALE_Y,
        )
        .normalized();
        let screen_angle = screen_dir.y.atan2(screen_dir.x);
        let shell_y = sy - lift;
        alpha_batch.ellipse(sx, sy + 1.5, 8.5, 3.4, screen_angle, linear_rgba([9, 18, 28], 125, 1.0));
        add_batch.line(
            tail_x,
            tail_y - lift,
            sx,
            shell_y,
            3.4,
            linear_rgba([255, 107, 46], 170, 1.15),
        );
        alpha_batch.ellipse(sx, shell_y, 8.2, 4.6, screen_angle, linear_rgba([177, 79, 35], 255, 1.1));
        alpha_batch.ellipse(
            sx + screen_dir.x * 2.0,
            shell_y - 1.0,
            5.8,
            3.0,
            screen_angle,
            linear_rgba([255, 178, 83], 255, 1.12),
        );
        alpha_batch.ellipse(
            sx + screen_dir.x * 4.7,
            shell_y - 1.25,
            2.0,
            1.55,
            screen_angle,
            linear_rgba([255, 238, 192], 255, 1.25),
        );
        return;
    }

    // Player weapons (with skin `shot_palette` override if present, or crit gold glow!)
    let mut head_col = get_weapon_color(&p.projectile_type);
    if let Some(pal) = shot_pal {
        head_col = pal.bullet;
    }
    if p.is_crit {
        head_col = mix_rgb(head_col, GOLD_TRAIL, 0.7);
    }

    let is_frag = p.weapon_name.is_empty() && p.projectile_type == "bullet" && shot_pal.is_none();
    let streak_world: f32 = match p.projectile_type.as_str() {
        "railgun" => 44.0,
        "missile" => 26.0,
        "plasma" => 18.0,
        _ if is_frag => 14.0,
        _ => 22.0,
    };
    let thick = match p.projectile_type.as_str() {
        "railgun" => 4.2,
        "missile" => 6.4,
        "plasma" => 5.6,
        _ if is_frag => 3.3,
        _ => 4.2,
    } * 1.14;
    let dir = if p.vel.length_squared() > 1e-6 { p.vel.normalized() } else { Vec2::new(1.0, 0.0) };
    // Grow the trail from the muzzle as the shot travels, so its first frames
    // never draw backward through the player hull.
    let lifespan = match p.projectile_type.as_str() {
        "bullet" | "spread" => 3.0,
        "plasma" => 3.2,
        "missile" => 3.8,
        "railgun" => 1.8,
        "laser" => 0.05,
        _ => p.ttl.max(0.0),
    };
    let step_distance = p.prev_pos.map_or(0.0, |previous| (p.pos - previous).length());
    let step_duration = step_distance / p.vel.length().max(1.0);
    let render_age = (lifespan - p.ttl).max(0.0) - (1.0 - interp.clamp(0.0, 1.0)) * step_duration;
    let traveled = if p.prev_pos.is_some() { render_age.max(0.0) * p.vel.length() } else { 0.0 };
    let trail_clearance = if p.owner == "player" { 32.0 } else { 0.0 };
    let tail_room = ((pos - player_pos).length() - trail_clearance).max(0.0);
    let visible_streak = streak_world.min(traveled).min(tail_room);
    let (tx, ty) = to_iso_cam(pos - dir * visible_streak, cam_world, view_w, view_h, shake);

    if glow_on {
        // Keep the round and trail readable without washing out the nearby pod.
        add_batch.glow(
            sx,
            sy,
            if p.is_crit { 9.0 } else { 7.0 },
            1.8,
            linear_rgba(head_col, if p.is_crit { 65 } else { 40 }, 1.25),
        );
    }
    add_batch.line(tx, ty, sx, sy, thick, linear_rgba(head_col, 170, 1.25));
    alpha_batch.circle(sx, sy, thick * 0.58, linear_rgba(head_col, 250, 1.0));
    add_batch.circle(sx, sy, (thick * 0.22).max(0.8), linear_rgba([245, 250, 255], 175, 1.2));
}

#[cfg(test)]
mod enemy_health_bar_tests {
    use super::draw_enemy_health_bar;
    use crate::render::sdf::SdfBatch;

    #[test]
    fn damaged_enemy_health_indicator_uses_thin_capsule_lines() {
        let mut batch = SdfBatch::default();
        draw_enemy_health_bar(45, 100, 120.0, 80.0, 20.0, [72, 205, 241], &mut batch);

        assert_eq!(batch.instances.len(), 2);
        assert!(batch.instances.iter().all(|instance| instance.kind == 1));
        assert!(batch.instances.iter().all(|instance| {
            (instance.p0[1] - instance.p1[1]).abs() < f32::EPSILON
        }));
    }

    #[test]
    fn full_health_enemy_has_no_floating_indicator() {
        let mut batch = SdfBatch::default();
        draw_enemy_health_bar(100, 100, 120.0, 80.0, 20.0, [72, 205, 241], &mut batch);
        draw_enemy_health_bar(10, 0, 120.0, 80.0, 20.0, [72, 205, 241], &mut batch);

        assert!(batch.instances.is_empty());
    }

}
