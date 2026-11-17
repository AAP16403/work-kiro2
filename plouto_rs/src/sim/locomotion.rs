use std::f32::consts::TAU;

use rayon::prelude::*;

use crate::sim::ai_skill::AiSkill;
use crate::sim::config::{CROSS_ARM_RATIO, DONUT_INNER_RATIO, MAP_CROSS, MAP_DONUT, PARALLEL_MIN_ENEMIES};
use crate::sim::enemy::{Enemy, EnemyRole, EnemySubState};
use crate::sim::math::{clamp_entity_to_map, perp, Vec2};
use crate::sim::steer::safe_dir;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IntentKind {
    Committed,
    Evade,
    RoleMove,
    Hold,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct MoveIntent {
    pub dir: Vec2,
    pub speed_mult: f32,
    pub kind: IntentKind,
    pub arrive_target: Option<Vec2>,
}

impl MoveIntent {
    #[inline]
    pub const fn hold() -> Self {
        Self {
            dir: Vec2::ZERO,
            speed_mult: 0.0,
            kind: IntentKind::Hold,
            arrive_target: None,
        }
    }

    #[inline]
    pub fn role(dir: Vec2, speed_mult: f32, arrive_target: Option<Vec2>) -> Self {
        Self {
            dir,
            speed_mult,
            kind: IntentKind::RoleMove,
            arrive_target,
        }
    }

    #[inline]
    pub fn evade(dir: Vec2, speed_mult: f32) -> Self {
        Self {
            dir,
            speed_mult,
            kind: IntentKind::Evade,
            arrive_target: None,
        }
    }

    #[inline]
    pub fn committed(dir: Vec2, speed_mult: f32) -> Self {
        Self {
            dir,
            speed_mult,
            kind: IntentKind::Committed,
            arrive_target: None,
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct Kinematics {
    pub max_speed_mult: f32,
    pub accel: f32,
    pub decel: f32,
    pub turn_rate_rad_s: f32,
    pub arrive_slow_r: f32,
    pub form_weight: f32,
    pub mass: f32,
    pub weave_amp: f32,
    pub weave_freq: f32,
}

pub fn kinematics_for_role(role: EnemyRole) -> Kinematics {
    match role {
        EnemyRole::Chaser => Kinematics {
            max_speed_mult: 1.25,
            accel: 640.0,
            decel: 720.0,
            turn_rate_rad_s: 7.5,
            arrive_slow_r: 36.0,
            form_weight: 0.28,
            mass: 1.0,
            weave_amp: 0.16,
            weave_freq: 2.6,
        },
        EnemyRole::Ranged => Kinematics {
            max_speed_mult: 1.15,
            accel: 480.0,
            decel: 620.0,
            turn_rate_rad_s: 6.0,
            arrive_slow_r: 55.0,
            form_weight: 0.36,
            mass: 1.0,
            weave_amp: 0.14,
            weave_freq: 1.6,
        },
        EnemyRole::Sniper => Kinematics {
            max_speed_mult: 1.10,
            accel: 420.0,
            decel: 680.0,
            turn_rate_rad_s: 5.5,
            arrive_slow_r: 65.0,
            form_weight: 0.30,
            mass: 1.1,
            weave_amp: 0.08,
            weave_freq: 1.2,
        },
        EnemyRole::Bomber => Kinematics {
            max_speed_mult: 1.12,
            accel: 400.0,
            decel: 560.0,
            turn_rate_rad_s: 5.0,
            arrive_slow_r: 60.0,
            form_weight: 0.35,
            mass: 1.3,
            weave_amp: 0.10,
            weave_freq: 1.4,
        },
        EnemyRole::Tank => Kinematics {
            max_speed_mult: 1.05,
            accel: 300.0,
            decel: 520.0,
            turn_rate_rad_s: 3.8,
            arrive_slow_r: 48.0,
            form_weight: 0.32,
            mass: 2.4,
            weave_amp: 0.0,
            weave_freq: 0.0,
        },
        EnemyRole::Charger => Kinematics {
            max_speed_mult: 1.18,
            accel: 520.0,
            decel: 600.0,
            turn_rate_rad_s: 5.5,
            arrive_slow_r: 44.0,
            form_weight: 0.25,
            mass: 2.0,
            weave_amp: 0.0,
            weave_freq: 0.0,
        },
        EnemyRole::Spitter => Kinematics {
            max_speed_mult: 1.15,
            accel: 500.0,
            decel: 640.0,
            turn_rate_rad_s: 6.5,
            arrive_slow_r: 52.0,
            form_weight: 0.34,
            mass: 1.0,
            weave_amp: 0.16,
            weave_freq: 1.9,
        },
        EnemyRole::Flyer => Kinematics {
            max_speed_mult: 1.22,
            accel: 680.0,
            decel: 720.0,
            turn_rate_rad_s: 8.5,
            arrive_slow_r: 45.0,
            form_weight: 0.38,
            mass: 0.9,
            weave_amp: 0.18,
            weave_freq: 2.8,
        },
        EnemyRole::Engineer => Kinematics {
            max_speed_mult: 1.12,
            accel: 440.0,
            decel: 600.0,
            turn_rate_rad_s: 5.8,
            arrive_slow_r: 58.0,
            form_weight: 0.35,
            mass: 1.2,
            weave_amp: 0.10,
            weave_freq: 1.5,
        },
        EnemyRole::Swarm => Kinematics {
            max_speed_mult: 1.28,
            accel: 780.0,
            decel: 820.0,
            turn_rate_rad_s: 9.5,
            arrive_slow_r: 32.0,
            form_weight: 0.0,
            mass: 0.75,
            weave_amp: 0.14,
            weave_freq: 4.2,
        },
        EnemyRole::EggSac => Kinematics {
            max_speed_mult: 0.0,
            accel: 0.0,
            decel: 999.0,
            turn_rate_rad_s: 0.0,
            arrive_slow_r: 0.0,
            form_weight: 0.0,
            mass: 4.0,
            weave_amp: 0.0,
            weave_freq: 0.0,
        },
        EnemyRole::Boss => Kinematics {
            max_speed_mult: 1.0,
            accel: 400.0,
            decel: 400.0,
            turn_rate_rad_s: 4.0,
            arrive_slow_r: 60.0,
            form_weight: 0.0,
            mass: 10.0,
            weave_amp: 0.0,
            weave_freq: 0.0,
        },
    }
}

/// Arena-aware waypoint routing for Donut (pit tangent) and Cross (arm hub).
pub fn route_point(
    from: Vec2,
    to: Vec2,
    map_type: &str,
    room_radius: f32,
    pad: f32,
    spawn_index: i64,
) -> Vec2 {
    match map_type {
        MAP_DONUT => {
            let pit_r = room_radius * DONUT_INNER_RATIO + pad + 8.0;
            let seg = to - from;
            let seg_len2 = seg.length_squared();
            if seg_len2 <= 1e-6 {
                return to;
            }
            let t = ((-from).dot(seg) / seg_len2).clamp(0.0, 1.0);
            let closest = from + seg * t;
            if closest.length_squared() >= pit_r * pit_r {
                return to;
            }
            // Choose tangent side around origin via cross product, tie-broken by spawn_index.
            let cross = from.x * to.y - from.y * to.x;
            let sign = if cross.abs() > 1e-3 {
                if cross > 0.0 { 1.0 } else { -1.0 }
            } else if spawn_index.rem_euclid(2) == 0 {
                1.0
            } else {
                -1.0
            };
            let from_dir = safe_dir(from, Vec2::new(1.0, 0.0));
            let tangent = perp(from_dir) * sign;
            let mid_dir = safe_dir(from_dir + tangent * 0.9, tangent);
            clamp_entity_to_map(mid_dir * (pit_r + 22.0), room_radius, pad, map_type)
        }
        MAP_CROSS => {
            let w = (room_radius * CROSS_ARM_RATIO - pad).max(room_radius * 0.25);
            let in_vert_arm = from.y.abs() > w;
            let in_horiz_arm = from.x.abs() > w;
            let to_vert_arm = to.y.abs() > w;
            let to_horiz_arm = to.x.abs() > w;
            if (in_vert_arm && to_horiz_arm) || (in_horiz_arm && to_vert_arm) {
                let hub_r = (w * 0.6).max(16.0);
                Vec2::new(to.x.clamp(-hub_r, hub_r), to.y.clamp(-hub_r, hub_r))
            } else {
                to
            }
        }
        _ => to,
    }
}

const GRID_CELL_SIZE: f32 = 64.0;
const GRID_BUCKETS: usize = 512;

/// Deterministic intrusive spatial hash grid with zero `HashMap`.
pub struct SpatialGrid {
    heads: [i32; GRID_BUCKETS],
    next: Vec<i32>,
    cells: Vec<(i32, i32)>,
}

impl SpatialGrid {
    #[inline]
    fn cell_coord(pos: Vec2) -> (i32, i32) {
        (
            (pos.x / GRID_CELL_SIZE).floor() as i32,
            (pos.y / GRID_CELL_SIZE).floor() as i32,
        )
    }

    #[inline]
    fn bucket(cx: i32, cy: i32) -> usize {
        let h = (cx.wrapping_mul(73_856_093) ^ cy.wrapping_mul(19_349_663)) as u32;
        (h as usize) & (GRID_BUCKETS - 1)
    }

    pub fn build_grid(positions: &[Vec2]) -> Self {
        let mut heads = [-1_i32; GRID_BUCKETS];
        let mut next = vec![-1_i32; positions.len()];
        let mut cells = Vec::with_capacity(positions.len());
        // Insert in reverse order so bucket traversal visits smaller indices first.
        for (idx, &pos) in positions.iter().enumerate() {
            let (cx, cy) = Self::cell_coord(pos);
            cells.push((cx, cy));
            let b = Self::bucket(cx, cy);
            next[idx] = heads[b];
            heads[b] = idx as i32;
        }
        Self { heads, next, cells }
    }

    pub fn query_3x3(&self, pos: Vec2, out: &mut Vec<usize>) {
        out.clear();
        let (cx, cy) = Self::cell_coord(pos);
        for dx in -1..=1 {
            for dy in -1..=1 {
                let ncx = cx + dx;
                let ncy = cy + dy;
                let mut cur = self.heads[Self::bucket(ncx, ncy)];
                while cur >= 0 {
                    let idx = cur as usize;
                    if self.cells[idx] == (ncx, ncy) {
                        out.push(idx);
                    }
                    cur = self.next[idx];
                }
            }
        }
    }
}

#[inline]
fn rotate_dir_towards(current: Vec2, target: Vec2, max_rad: f32) -> Vec2 {
    let cur = safe_dir(current, Vec2::new(1.0, 0.0));
    let tgt = safe_dir(target, cur);
    let dot = cur.dot(tgt).clamp(-1.0, 1.0);
    let cross = cur.x * tgt.y - cur.y * tgt.x;
    let ang = cross.atan2(dot);
    if ang.abs() <= max_rad {
        tgt
    } else {
        cur.rotated_rad(ang.signum() * max_rad)
    }
}

#[derive(Debug, Clone, Copy)]
struct EnemyLocomotionSnap {
    idx: usize,
    pos: Vec2,
    vel: Vec2,
    heading: Vec2,
    speed: f32,
    radius: f32,
    t: f32,
    seed: f32,
    spawn_index: i64,
    role: EnemyRole,
    active: bool,
}

#[derive(Debug, Clone, Copy)]
struct IntegratedStep {
    idx: usize,
    heading: Vec2,
    vel: Vec2,
    accel_vec: Vec2,
    pos: Vec2,
}

/// Single-integrator locomotion pass combining `MoveIntent`, Formation v2 targets,
/// predictive neighbor avoidance (`t* < 0.5s`, up to 6 nearest), turn-rate limits, and accel/decel.
#[allow(clippy::too_many_arguments)]
pub fn integrate_batch(
    enemies: &mut [Enemy],
    intents: &[Option<MoveIntent>],
    form_targets: &[Option<(Vec2, &'static str)>],
    skill: &AiSkill,
    room_radius: f32,
    map_type: &str,
    dt: f32,
    now: f32,
) {
    if dt <= 0.0 || enemies.is_empty() {
        return;
    }

    let mut snaps = Vec::with_capacity(enemies.len());
    let mut positions = Vec::with_capacity(enemies.len());
    let mut active_count = 0usize;

    for (idx, e) in enemies.iter().enumerate() {
        let alive = !e.is_dead && e.hp > 0;
        let active = alive && !e.is_boss() && e.role != EnemyRole::EggSac && !e.is_stunned(now);
        if active {
            active_count += 1;
        }
        positions.push(e.pos);
        snaps.push(EnemyLocomotionSnap {
            idx,
            pos: e.pos,
            vel: e.vel,
            heading: safe_dir(e.ai.heading, safe_dir(e.vel, Vec2::new(1.0, 0.0))),
            speed: e.speed,
            radius: e.radius,
            t: e.t,
            seed: e.seed,
            spawn_index: e.spawn_index,
            role: e.role,
            active,
        });
    }

    if active_count == 0 {
        return;
    }

    let grid = SpatialGrid::build_grid(&positions);

    let compute_one = |i: usize| -> Option<IntegratedStep> {
        let s = snaps[i];
        if !s.active {
            return None;
        }
        let intent = intents.get(i).and_then(|v| *v)?;
        let kin = kinematics_for_role(s.role);

        if intent.kind == IntentKind::Hold || s.speed <= 0.0 {
            let decel_step = (kin.decel * 1.4).max(s.speed * 6.0) * dt;
            let vlen = s.vel.length();
            let new_vel = if vlen <= decel_step || vlen <= 1e-6 {
                Vec2::ZERO
            } else {
                s.vel * ((vlen - decel_step) / vlen)
            };
            let accel_vec = (new_vel - s.vel) / dt;
            return Some(IntegratedStep {
                idx: s.idx,
                heading: s.heading,
                vel: new_vel,
                accel_vec,
                pos: s.pos + new_vel * dt,
            });
        }

        // Predictive neighbor avoidance (t* < 0.5s, up to 6 nearest within neighborhood).
        let mut avoid_steer = Vec2::ZERO;
        if intent.kind != IntentKind::Committed {
            let mut candidates = Vec::new();
            grid.query_3x3(s.pos, &mut candidates);
            let mut nearest: [(f32, usize); 6] = [(f32::INFINITY, usize::MAX); 6];
            for &j in &candidates {
                if j == i {
                    continue;
                }
                let o = &snaps[j];
                if o.role == EnemyRole::EggSac {
                    continue;
                }
                let d2 = (o.pos - s.pos).length_squared();
                let limit = s.radius + o.radius + 54.0;
                if d2 > limit * limit {
                    continue;
                }
                if d2 < nearest[5].0 {
                    nearest[5] = (d2, j);
                    nearest.sort_by(|a, b| a.0.total_cmp(&b.0).then_with(|| a.1.cmp(&b.1)));
                }
            }

            for &(d2, j) in &nearest {
                if !d2.is_finite() || j == usize::MAX {
                    break;
                }
                let o = &snaps[j];
                let dp = o.pos - s.pos;
                let dv = o.vel - s.vel;
                let dv2 = dv.length_squared();
                if dv2 <= 1e-6 {
                    continue;
                }
                let t_star = -dp.dot(dv) / dv2;
                if t_star > 0.0 && t_star < 0.5 {
                    let future_sep = dp + dv * t_star;
                    let min_sep = s.radius + o.radius + 8.0;
                    let f_len = future_sep.length();
                    if f_len < min_sep {
                        let away = if f_len > 1e-4 {
                            -future_sep / f_len
                        } else {
                            perp(safe_dir(s.vel, s.heading))
                                * if s.spawn_index.rem_euclid(2) == 0 { 1.0 } else { -1.0 }
                        };
                        let w = (1.0 - t_star / 0.5) * (1.0 - f_len / min_sep);
                        avoid_steer += away * w;
                    }
                }
            }
        }

        let form_target = form_targets.get(i).and_then(|v| *v).map(|(p, _)| p);
        let pad = s.radius + 6.0;

        let (raw_dir, turn_mult, accel_mult, speed_scale) = match intent.kind {
            IntentKind::Committed => {
                let d = safe_dir(intent.dir, s.heading);
                // High turn & accel for dashes/lunges/charges so velocity commits cleanly.
                (d, 3.5, 4.5, 1.0)
            }
            IntentKind::Evade => {
                let idir = safe_dir(intent.dir, s.heading);
                let blended = if let Some(ft) = form_target {
                    let fdir = safe_dir(ft - s.pos, idir);
                    safe_dir(idir * 0.7 + fdir * 0.3 + avoid_steer * 0.35, idir)
                } else {
                    safe_dir(idir + avoid_steer * 0.35, idir)
                };
                (blended, 2.0, 1.5, 1.0)
            }
            IntentKind::RoleMove => {
                let routed_intent = if let Some(tgt) = intent.arrive_target {
                    let wp = route_point(s.pos, tgt, map_type, room_radius, pad, s.spawn_index);
                    safe_dir(wp - s.pos, intent.dir)
                } else {
                    let lookahead = s.pos + safe_dir(intent.dir, s.heading) * 90.0;
                    let wp = route_point(s.pos, lookahead, map_type, room_radius, pad, s.spawn_index);
                    safe_dir(wp - s.pos, intent.dir)
                };
                let mut dir = if let Some(ft) = form_target {
                    if kin.form_weight > 0.0 {
                        let wp = route_point(s.pos, ft, map_type, room_radius, pad, s.spawn_index);
                        let fdir = safe_dir(wp - s.pos, routed_intent);
                        safe_dir(
                            routed_intent * (1.0 - kin.form_weight) + fdir * kin.form_weight,
                            routed_intent,
                        )
                    } else {
                        routed_intent
                    }
                } else {
                    routed_intent
                };
                if avoid_steer.length_squared() > 1e-6 {
                    dir = safe_dir(dir + avoid_steer * 0.55, dir);
                }
                if kin.weave_amp > 0.0 {
                    let weave = (s.t * kin.weave_freq + s.seed).sin() * kin.weave_amp * skill.weave_mult;
                    dir = safe_dir(dir + perp(dir) * weave, dir);
                }
                let arrive_scale = if let Some(tgt) = intent.arrive_target {
                    if kin.arrive_slow_r > 1e-3 {
                        let d = (tgt - s.pos).length();
                        if d < kin.arrive_slow_r {
                            (d / kin.arrive_slow_r).clamp(0.18, 1.0)
                        } else {
                            1.0
                        }
                    } else {
                        1.0
                    }
                } else {
                    1.0
                };
                (dir, 1.0, 1.0, arrive_scale)
            }
            IntentKind::Hold => unreachable!(),
        };

        let max_turn = kin.turn_rate_rad_s * turn_mult * dt;
        let new_heading = rotate_dir_towards(s.heading, raw_dir, max_turn);
        let max_speed = s.speed * kin.max_speed_mult.max(intent.speed_mult);
        let desired_speed = (s.speed * intent.speed_mult * speed_scale).min(max_speed);
        let desired_vel = new_heading * desired_speed;

        let delta_v = desired_vel - s.vel;
        let dv_len = delta_v.length();
        let rate = if desired_vel.length_squared() >= s.vel.length_squared() {
            (kin.accel * accel_mult).max(if intent.kind == IntentKind::Committed {
                s.speed * 18.0
            } else {
                0.0
            })
        } else {
            kin.decel * accel_mult
        };
        let max_dv = rate * dt;
        let new_vel = if dv_len <= max_dv || dv_len <= 1e-6 {
            desired_vel
        } else {
            s.vel + delta_v * (max_dv / dv_len)
        };

        let accel_vec = (new_vel - s.vel) / dt;
        Some(IntegratedStep {
            idx: s.idx,
            heading: new_heading,
            vel: new_vel,
            accel_vec,
            pos: s.pos + new_vel * dt,
        })
    };

    let steps: Vec<Option<IntegratedStep>> = if active_count >= PARALLEL_MIN_ENEMIES {
        (0..snaps.len()).into_par_iter().map(compute_one).collect()
    } else {
        (0..snaps.len()).map(compute_one).collect()
    };

    for step in steps.into_iter().flatten() {
        let e = &mut enemies[step.idx];
        e.ai.heading = step.heading;
        e.vel = step.vel;
        e.ai.accel_vec = step.accel_vec;
        e.pos = step.pos;
    }
}

fn enemy_holds_body_anchor(enemy: &Enemy, now: f32) -> bool {
    enemy.is_boss()
        || enemy.role == EnemyRole::EggSac
        || enemy.is_stunned(now)
        || enemy.ai.telegraph_beam_id.is_some()
        || enemy.ai.lunge_windup > 0.0
        || enemy.ai.lunge_t > 0.0
        || matches!(
            enemy.ai.sub_state,
            EnemySubState::ChargerWindup
                | EnemySubState::ChargerCharging
                | EnemySubState::FlyerWindup
                | EnemySubState::FlyerDashing
                | EnemySubState::SniperWindup
                | EnemySubState::BomberWindup
                | EnemySubState::TankWindup
                | EnemySubState::RangedWindup
                | EnemySubState::SpitterWindup
                | EnemySubState::EngineerWindup
        )
}

fn move_enemy_for_clearance(
    enemy: &mut Enemy,
    desired: Vec2,
    moved_this_step: &mut f32,
    max_disp: f32,
    room_radius: f32,
    map_type: &str,
) {
    let remaining = (max_disp - *moved_this_step).max(0.0);
    let length = desired.length();
    if remaining <= 0.0 || length <= 1.0e-6 {
        return;
    }
    let limited = if length > remaining {
        desired * (remaining / length)
    } else {
        desired
    };
    let next = clamp_entity_to_map(
        enemy.pos + limited,
        room_radius,
        enemy.radius + 6.0,
        map_type,
    );
    let applied = next - enemy.pos;
    enemy.pos = next;
    *moved_this_step += applied.length();
}

/// Mass-weighted body overlap solver using the deterministic 64-unit spatial hash grid.
pub fn resolve_enemy_body_overlaps(
    enemies: &mut [Enemy],
    room_radius: f32,
    map_type: &str,
    now: f32,
    dt: f32,
) {
    if enemies.len() < 2 {
        return;
    }
    let anchors: Vec<bool> = enemies
        .iter()
        .map(|enemy| enemy_holds_body_anchor(enemy, now))
        .collect();
    let masses: Vec<f32> = enemies
        .iter()
        .map(|enemy| kinematics_for_role(enemy.role).mass)
        .collect();
    let max_disps: Vec<f32> = enemies
        .iter()
        .map(|enemy| (0.35 * enemy.speed.max(60.0) * dt.max(1.0 / 120.0) * 60.0).min(22.0))
        .collect();
    let mut moved = vec![0.0_f32; enemies.len()];
    let mut neighbors = Vec::with_capacity(16);

    for _ in 0..4 {
        let positions: Vec<Vec2> = enemies.iter().map(|e| e.pos).collect();
        let grid = SpatialGrid::build_grid(&positions);

        for first in 0..enemies.len() {
            if enemies[first].is_dead || enemies[first].hp <= 0 {
                continue;
            }
            grid.query_3x3(enemies[first].pos, &mut neighbors);
            neighbors.sort_unstable();
            for &second in &neighbors {
                if second <= first || enemies[second].is_dead || enemies[second].hp <= 0 {
                    continue;
                }
                if anchors[first] && anchors[second] {
                    continue;
                }
                let delta = enemies[second].pos - enemies[first].pos;
                let distance = delta.length();
                let clearance = enemies[first].radius + enemies[second].radius + 2.0;
                if distance >= clearance {
                    continue;
                }

                let direction = if distance > 1.0e-5 {
                    delta / distance
                } else {
                    let hash = enemies[first]
                        .id
                        .wrapping_mul(31)
                        ^ enemies[second].id.wrapping_mul(17);
                    let angle = (hash % 4096) as f32 * (TAU / 4096.0);
                    Vec2::new(angle.cos(), angle.sin())
                };
                let penetration = (clearance - distance).min(18.0);
                if anchors[first] {
                    move_enemy_for_clearance(
                        &mut enemies[second],
                        direction * penetration,
                        &mut moved[second],
                        max_disps[second],
                        room_radius,
                        map_type,
                    );
                } else if anchors[second] {
                    move_enemy_for_clearance(
                        &mut enemies[first],
                        -direction * penetration,
                        &mut moved[first],
                        max_disps[first],
                        room_radius,
                        map_type,
                    );
                } else {
                    let m_a = masses[first];
                    let m_b = masses[second];
                    let denom = (m_a + m_b).max(1e-3);
                    let push_a = penetration * (m_b / denom);
                    let push_b = penetration * (m_a / denom);
                    move_enemy_for_clearance(
                        &mut enemies[first],
                        -direction * push_a,
                        &mut moved[first],
                        max_disps[first],
                        room_radius,
                        map_type,
                    );
                    move_enemy_for_clearance(
                        &mut enemies[second],
                        direction * push_b,
                        &mut moved[second],
                        max_disps[second],
                        room_radius,
                        map_type,
                    );
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn route_point_avoids_donut_pit_and_cross_corners() {
        let wp_donut = route_point(
            Vec2::new(-400.0, 0.0),
            Vec2::new(400.0, 0.0),
            MAP_DONUT,
            760.0,
            20.0,
            0,
        );
        let pit_r = 760.0 * DONUT_INNER_RATIO + 20.0;
        assert!(wp_donut.length() >= pit_r - 1.0);
        assert!(wp_donut.y.abs() > 10.0);

        let wp_cross = route_point(
            Vec2::new(0.0, 500.0),
            Vec2::new(500.0, 0.0),
            MAP_CROSS,
            760.0,
            20.0,
            0,
        );
        let arm_w = 760.0 * CROSS_ARM_RATIO - 20.0;
        assert!(wp_cross.x.abs() <= arm_w && wp_cross.y.abs() <= arm_w);
    }

    #[test]
    fn mass_weighted_overlap_pushes_lighter_enemy_more() {
        let mut enemies = vec![
            Enemy::new(1, Vec2::new(0.0, 0.0), 100, 90.0, "tank"),
            Enemy::new(2, Vec2::new(10.0, 0.0), 50, 110.0, "swarm"),
        ];
        resolve_enemy_body_overlaps(&mut enemies, 760.0, "circle", 1.0, 1.0 / 60.0);
        let tank_disp = enemies[0].pos.x.abs();
        let swarm_disp = (enemies[1].pos.x - 10.0).abs();
        assert!(swarm_disp > tank_disp * 2.0);
    }
}
