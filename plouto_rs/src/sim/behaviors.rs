use std::collections::HashMap;
use std::f32::consts::TAU;

use crate::sim::ai_skill::AiSkill;
use crate::sim::config::{MAX_ACTIVE_CONSTRUCTIONS, TANK_PROJ_SPEED, TANK_PROJ_TTL, TANK_RANGE};
use crate::sim::director::{
    attack_category_for_role, AttackDirector, AttackProposal,
};
use crate::sim::enemy::{swarm_formation_key, AttackDenialReason, Enemy, EnemyRole, EnemySubState};
use crate::sim::hazards::{LaserBeam, Trap};
use crate::sim::layout::Obstacle;
use crate::sim::locomotion::MoveIntent;
use crate::sim::math::{arena_inside, clamp_entity_to_map, perp, point_segment_distance_sq, Vec2};
use crate::sim::perception::Perception;
use crate::sim::projectile::Projectile;
use crate::sim::rng::SimRng;
use crate::sim::steer::safe_dir;

pub const TELEGRAPH_OWNER: &str = "telegraph";
pub const TELEGRAPH_COLOR: [u8; 3] = [235, 235, 230];
pub const TELEGRAPH_THICKNESS: f32 = 5.0;

const LUNGE_WINDUP_S: f32 = 0.22;
const PROJECTILE_DODGE_HORIZON_S: f32 = 0.42;
const MAX_DODGE_CANDIDATES: usize = 8;
const MAX_ATTACK_WAIT_SECONDS: f32 = 1.6;
const FORCED_ATTACK_STAGGER_SECONDS: f32 = 0.35;
const REGULAR_SAME_TYPE_STAGGER: f32 = 0.20;
pub const BOMBER_WINDUP_SECONDS: f32 = 0.60;
pub const BOMBER_FUSE_SECONDS: f32 = 1.25;
pub const TANK_WINDUP_SECONDS: f32 = 0.48;
pub const FLYER_WINDUP_SECONDS: f32 = 0.45;
pub const FLYER_DASH_TIMEOUT_SECONDS: f32 = 1.35;
pub const SWARM_SURGE_TELEGRAPH_SECONDS: f32 = 0.30;

#[derive(Debug, Clone)]
pub struct SwarmBrain {
    pub mode: String, // "encircle", "surge", "regroup"
    pub mode_t: f32,
    pub focus: Vec2,
    pub ring_r: f32,
    pub flank_sign: f32,
    pub orbit_phase: f32,
    pub last_t: f32,
    pub subgroup_modes: [SwarmMode; 3],
    pub subgroup_timers: [f32; 3],
    pub subgroup_flank_signs: [f32; 3],
    pub subgroup_orbit_phases: [f32; 3],
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SwarmMode {
    Encircle,
    SurgeTelegraph,
    Surge,
    Regroup,
}

impl SwarmMode {
    fn as_str(self) -> &'static str {
        match self {
            Self::Encircle => "encircle",
            Self::SurgeTelegraph => "surge_telegraph",
            Self::Surge => "surge",
            Self::Regroup => "regroup",
        }
    }
}

impl SwarmBrain {
    pub fn new(now: f32, rng: &mut SimRng) -> Self {
        let orbit_phase = rng.range_f32(0.0, TAU);
        let flank_sign = if rng.f32() < 0.5 { 1.0 } else { -1.0 };
        Self {
            mode: "encircle".to_string(),
            mode_t: 1.8,
            focus: Vec2::ZERO,
            ring_r: 120.0,
            flank_sign,
            orbit_phase,
            last_t: now,
            subgroup_modes: [SwarmMode::Encircle; 3],
            subgroup_timers: [1.8, 2.35, 2.9],
            subgroup_flank_signs: [flank_sign, -flank_sign, flank_sign],
            subgroup_orbit_phases: [
                orbit_phase,
                orbit_phase + TAU / 3.0,
                orbit_phase + 2.0 * TAU / 3.0,
            ],
        }
    }
}

pub struct BehaviorContext<'a> {
    pub player_pos: Vec2,
    pub player_vel: Vec2,
    pub dt: f32,
    /// Accumulated enemy-time clock, already scaled by Time Slow.
    pub enemy_time: f32,
    pub wave: i32,
    pub room_radius: f32,
    pub map_type: &'a str,
    pub next_id: &'a mut u64,
    pub rng: &'a mut SimRng,
    pub enemy_snaps: &'a [(u64, Vec2, Vec2, bool)], // (id, pos, vel, is_swarm)
    pub swarm_snaps: &'a [(u64, Vec2, Vec2, usize)], // (id, pos, vel, stable subgroup)
    pub spawn_snaps: &'a [(u64, Vec2, f32)],        // (id, position, radius)
    pub live_non_boss_count: usize,
    pub non_boss_spawn_cap: usize,
    pub obstacles: &'a [Obstacle],
    pub projectiles: &'a mut Vec<Projectile>,
    pub traps: &'a mut Vec<Trap>,
    pub lasers: &'a mut Vec<LaserBeam>,
    pub swarm_brain: &'a mut Option<SwarmBrain>,
    pub queued_spawns: &'a mut Vec<Enemy>,
    pub attack_scheduler: &'a mut AttackScheduler,
}

/// Legacy single-pass attack scheduler retained for `BehaviorContext` / boss compatibility.
/// Regular enemies are scheduled by the two-pass `AttackDirector` in `sim/director.rs`.
#[derive(Debug, Clone)]
pub struct AttackScheduler {
    pub active_weight: u8,
    pub capacity: u8,
    granted_weight: u8,
    forced_grants: u8,
    boss_present: bool,
    last_start_by_role: HashMap<String, f32>,
    last_forced_start: f32,
}

impl AttackScheduler {
    pub fn for_enemies(enemies: &[Enemy]) -> Self {
        let live_non_boss = enemies
            .iter()
            .filter(|e| !e.is_dead && e.hp > 0 && !e.is_boss())
            .count();
        let boss_present = enemies.iter().any(|e| !e.is_dead && e.hp > 0 && e.is_boss());
        let capacity = if boss_present {
            1
        } else if live_non_boss >= 12 {
            3
        } else if live_non_boss >= 5 {
            2
        } else {
            1
        };
        let mut scheduler = Self {
            active_weight: 0,
            capacity,
            granted_weight: 0,
            forced_grants: 0,
            boss_present,
            last_start_by_role: HashMap::new(),
            last_forced_start: -1_000.0,
        };
        for enemy in enemies.iter().filter(|e| !e.is_dead && e.hp > 0) {
            scheduler.active_weight = scheduler
                .active_weight
                .saturating_add(crate::sim::director::active_attack_weight(enemy));
            if enemy.ai.last_attack_started_at > -999.0 {
                scheduler
                    .last_start_by_role
                    .entry(enemy.behavior.clone())
                    .and_modify(|last| *last = last.max(enemy.ai.last_attack_started_at))
                    .or_insert(enemy.ai.last_attack_started_at);
            }
            scheduler.last_forced_start = scheduler
                .last_forced_start
                .max(enemy.ai.last_forced_attack_started_at);
        }
        scheduler
    }

    pub fn request(&mut self, enemy: &mut Enemy, weight: u8, enemy_time: f32, dt: f32) -> bool {
        let same_type_stagger = if self.boss_present {
            0.28
        } else {
            REGULAR_SAME_TYPE_STAGGER
        };
        let staggered = self
            .last_start_by_role
            .get(&enemy.behavior)
            .is_some_and(|last| enemy_time - *last < same_type_stagger);
        let within_budget = self
            .active_weight
            .saturating_add(self.granted_weight)
            .saturating_add(weight)
            <= self.capacity;
        let forced = enemy.ai.attack_denied_t >= MAX_ATTACK_WAIT_SECONDS
            && self.forced_grants == 0
            && enemy_time - self.last_forced_start >= FORCED_ATTACK_STAGGER_SECONDS;
        if (within_budget && !staggered) || forced {
            self.granted_weight = self.granted_weight.saturating_add(weight);
            if forced && (!within_budget || staggered) {
                self.forced_grants = self.forced_grants.saturating_add(1);
                self.last_forced_start = enemy_time;
                enemy.ai.last_forced_attack_started_at = enemy_time;
            }
            enemy.ai.attack_denied_t = 0.0;
            enemy.ai.attack_denial_reason = None;
            enemy.ai.last_attack_started_at = enemy_time;
            self.last_start_by_role
                .insert(enemy.behavior.clone(), enemy_time);
            true
        } else {
            enemy.ai.attack_denied_t += dt.max(0.0);
            enemy.ai.attack_denial_reason = Some(if staggered {
                AttackDenialReason::SameTypeStagger
            } else {
                AttackDenialReason::CommitmentBudget
            });
            false
        }
    }
}

pub fn sustained_cd_scale(enemy: &Enemy) -> f32 {
    let m = enemy.ai.attack_mult.clamp(0.6, 1.6);
    1.0 + (m - 1.0) * 0.5
}

/// Legacy linear lead direction retained for `bosses.rs` until Task 3.
pub fn lead_dir(
    shooter_pos: Vec2,
    target_pos: Vec2,
    target_vel: Vec2,
    proj_speed: f32,
    mult: f32,
) -> Vec2 {
    let d = (target_pos - shooter_pos).length();
    let t = (d / proj_speed.max(1.0)) * mult;
    let aim_pos = target_pos + target_vel * t;
    safe_dir(aim_pos - shooter_pos, Vec2::new(1.0, 0.0))
}

/// Exact quadratic projectile intercept predictor with reaction delay, skill-scaled lead,
/// arena clamping, and aim jitter.
#[allow(clippy::too_many_arguments)]
pub fn predict_target(
    shooter_pos: Vec2,
    proj_speed: f32,
    enemy: &mut Enemy,
    perception: &Perception,
    skill: &AiSkill,
    dt: f32,
    room_radius: f32,
    map_type: &str,
    rng: &mut SimRng,
    jitter_scale: f32,
) -> Vec2 {
    enemy.ai.retarget_left = (enemy.ai.retarget_left - dt.max(0.0)).max(0.0);
    if enemy.ai.retarget_left <= 0.0 {
        enemy.ai.last_seen_intent = perception.smoothed_vel * 0.72 + perception.intent_vel * 0.28;
        enemy.ai.retarget_left = skill.reaction_s;
    }

    let d = perception.player_pos - shooter_pos;
    let v = enemy.ai.last_seen_intent;
    let s = proj_speed.max(1.0);

    let a = v.length_squared() - s * s;
    let b = 2.0 * d.dot(v);
    let c = d.length_squared();

    let mut t_hit = d.length() / s;
    if a.abs() < 1e-4 {
        if b < -1e-4 {
            t_hit = -c / b;
        }
    } else {
        let disc = b * b - 4.0 * a * c;
        if disc >= 0.0 {
            let sqrt_disc = disc.sqrt();
            let t1 = (-b - sqrt_disc) / (2.0 * a);
            let t2 = (-b + sqrt_disc) / (2.0 * a);
            let best = match (t1 > 0.0, t2 > 0.0) {
                (true, true) => Some(t1.min(t2)),
                (true, false) => Some(t1),
                (false, true) => Some(t2),
                (false, false) => None,
            };
            if let Some(t) = best {
                t_hit = t;
            }
        }
    }
    t_hit = t_hit.clamp(0.0, 1.5);

    let raw_aim = perception.player_pos + v * (t_hit * skill.lead_quality);
    let mut target = clamp_entity_to_map(raw_aim, room_radius, 8.0, map_type);

    if skill.aim_jitter_deg > 0.0 && jitter_scale > 0.0 {
        let offset = target - shooter_pos;
        if offset.length_squared() > 1e-6 {
            let max_jit = skill.aim_jitter_deg * jitter_scale;
            let deg = rng.range_f32(-max_jit, max_jit);
            target = clamp_entity_to_map(
                shooter_pos + offset.rotated_deg(deg),
                room_radius,
                8.0,
                map_type,
            );
        }
    }

    target
}

/// Inverse-square separation from other enemies within `radius`.
pub fn separation_inv_sq(
    pos: Vec2,
    self_id: u64,
    snaps: &[(u64, Vec2, Vec2, bool)],
    radius: f32,
    weight: f32,
) -> Vec2 {
    let mut acc = Vec2::ZERO;
    let mut count = 0usize;
    for &(oid, opos, _, _) in snaps {
        if oid == self_id {
            continue;
        }
        let dvec = pos - opos;
        let d = dvec.length();
        if d <= 1e-6 || d > radius {
            continue;
        }
        acc += dvec / (d * d);
        count += 1;
    }
    if count == 0 {
        return Vec2::ZERO;
    }
    acc.normalized() * weight
}

#[inline]
fn projectile_threat_key(p: &Projectile) -> u64 {
    let vx = p.vel.x.to_bits() as u64;
    let vy = p.vel.y.to_bits() as u64;
    let dmg = (p.damage as u64).wrapping_mul(0x9e37_79b9_7f4a_7c15);
    let mut h = vx.wrapping_mul(0xbf58_476d_1ce4_e5b9)
        ^ vy.wrapping_mul(0x94d0_49bb_1331_11eb)
        ^ dmg;
    h ^= h >> 30;
    h.max(1)
}

/// Evade player projectiles whose projected path comes close within the reaction window.
/// Enforces per-threat `dodge_reaction_s`, `dodge_chance`, and arena-edge safety.
#[allow(clippy::too_many_arguments)]
pub fn dodge_player_projectiles(
    enemy: &mut Enemy,
    projectiles: &[Projectile],
    danger_radius: f32,
    max_count: usize,
    lateral: bool,
    dt: f32,
    skill: &AiSkill,
    room_radius: f32,
    map_type: &str,
    rng: &mut SimRng,
) -> Vec2 {
    if enemy.ai.dodge_active_left > 0.0 {
        return enemy.ai.dodge_direction;
    }
    if enemy.ai.dodge_cooldown_left > 0.0 {
        return Vec2::ZERO;
    }
    let reaction_radius = (enemy.radius + danger_radius * 0.28)
        .max(18.0)
        .min(danger_radius * 0.75);
    let reaction_radius_sq = reaction_radius * reaction_radius;
    let fallback_side = det_sign(enemy, false);
    let threat_limit = max_count.min(MAX_DODGE_CANDIDATES);
    if threat_limit == 0 {
        return Vec2::ZERO;
    }

    let mut raw_candidates = [(0_u64, 0.0_f32, Vec2::ZERO); MAX_DODGE_CANDIDATES];
    let mut raw_count = 0usize;

    for p in projectiles {
        if p.owner != "player" {
            continue;
        }
        let projectile_speed_sq = p.vel.length_squared();
        if projectile_speed_sq <= 1e-6 {
            continue;
        }
        let relative_pos = enemy.pos - p.pos;
        let relative_vel = enemy.vel - p.vel;
        let relative_speed_sq = relative_vel.length_squared();
        if relative_speed_sq <= 1e-6 {
            continue;
        }
        let closest_t = -relative_pos.dot(relative_vel) / relative_speed_sq;
        if closest_t <= 0.0 || closest_t > PROJECTILE_DODGE_HORIZON_S {
            continue;
        }
        let closest_offset = relative_pos + relative_vel * closest_t;
        let miss_sq = closest_offset.length_squared();
        if miss_sq >= reaction_radius_sq {
            continue;
        }
        let vnorm = p.vel.normalized();
        let side_axis = perp(vnorm);
        let miss_side = closest_offset.dot(side_axis);
        let side = if miss_side.abs() > 1e-4 {
            if miss_side > 0.0 {
                1.0
            } else {
                -1.0
            }
        } else {
            fallback_side
        };
        let proximity = (1.0 - miss_sq.sqrt() / reaction_radius).clamp(0.0, 1.0);
        let urgency = (1.0 - closest_t / PROJECTILE_DODGE_HORIZON_S).clamp(0.0, 1.0);
        let threat_score = proximity * proximity * (0.55 + 0.45 * urgency);
        let escape = if lateral {
            side_axis * side
        } else {
            safe_dir(closest_offset, side_axis * fallback_side)
        };
        let key = projectile_threat_key(p);

        let insert_at = raw_candidates[..raw_count]
            .iter()
            .position(|(_, score, _)| threat_score > *score)
            .unwrap_or(raw_count);
        if insert_at >= threat_limit {
            continue;
        }
        let new_count = (raw_count + 1).min(threat_limit);
        for idx in (insert_at..new_count.saturating_sub(1)).rev() {
            raw_candidates[idx + 1] = raw_candidates[idx];
        }
        raw_candidates[insert_at] = (key, threat_score, escape);
        raw_count = new_count;
    }

    // Prune stale threat_seen slots not present this tick.
    for slot in &mut enemy.ai.threat_seen {
        if slot.0 != 0 && !raw_candidates[..raw_count].iter().any(|&(k, _, _)| k == slot.0) {
            *slot = (0, 0.0);
        }
    }

    if raw_count == 0 {
        return Vec2::ZERO;
    }

    // Advance seen_time for active threats and filter to threats that passed dodge_reaction_s.
    let mut threats = [(0.0_f32, Vec2::ZERO); MAX_DODGE_CANDIDATES];
    let mut threat_count = 0usize;
    let step_dt = dt.max(1.0 / 120.0);
    for &(key, score, escape) in &raw_candidates[..raw_count] {
        let seen_t = if let Some(slot) = enemy.ai.threat_seen.iter_mut().find(|s| s.0 == key) {
            slot.1 += step_dt;
            slot.1
        } else {
            let target_slot = if let Some(empty) = enemy.ai.threat_seen.iter_mut().find(|s| s.0 == 0) {
                empty
            } else {
                // Fixed-size array fallback: overwrite oldest/smallest seen_time.
                let mut min_idx = 0;
                for i in 1..enemy.ai.threat_seen.len() {
                    if enemy.ai.threat_seen[i].1 < enemy.ai.threat_seen[min_idx].1 {
                        min_idx = i;
                    }
                }
                &mut enemy.ai.threat_seen[min_idx]
            };
            *target_slot = (key, step_dt);
            step_dt
        };

        if seen_t >= skill.dodge_reaction_s {
            threats[threat_count] = (score, escape);
            threat_count += 1;
        }
    }

    if threat_count == 0 {
        return Vec2::ZERO;
    }

    // Skill-gated dodge probability roll with brief backoff on miss so we don't re-roll 60x/s.
    if rng.f32() >= skill.dodge_chance {
        enemy.ai.dodge_cooldown_left = 0.25;
        return Vec2::ZERO;
    }

    let steer = threats[..threat_count]
        .iter()
        .fold(Vec2::ZERO, |sum, (score, escape)| sum + *escape * *score);
    let mut direction = if steer.length_squared() <= 1e-8 {
        threats[0].1
    } else {
        steer.normalized()
    };

    // Arena-edge safety check: if dodging across an outer wall or Donut pit, flip once.
    let edge_pad = enemy.radius + 8.0;
    let is_edge_safe = |pt: Vec2| {
        (clamp_entity_to_map(pt, room_radius, edge_pad, map_type) - pt).length_squared() <= 0.25
    };
    let probe = enemy.pos + direction * 36.0;
    if !is_edge_safe(probe) {
        let flipped = -direction;
        let flip_probe = enemy.pos + flipped * 36.0;
        if is_edge_safe(flip_probe) {
            direction = flipped;
        }
    }

    if direction.length_squared() > 1e-8 {
        let cooldown = match enemy.role {
            EnemyRole::Chaser => 0.58,
            EnemyRole::Flyer => 0.52,
            EnemyRole::Ranged => 0.72,
            EnemyRole::Spitter => 0.76,
            EnemyRole::Sniper => 0.92,
            EnemyRole::Tank => 1.15,
            _ => 0.82,
        };
        enemy.ai.dodge_direction = direction;
        enemy.ai.dodge_active_left = 0.16;
        enemy.ai.dodge_cooldown_left = cooldown;
    }
    direction
}

pub fn add_windup_telegraph(
    lasers: &mut Vec<LaserBeam>,
    next_id: &mut u64,
    start: Vec2,
    end: Vec2,
    duration: f32,
) -> u64 {
    let id = *next_id;
    *next_id += 1;
    let beam = LaserBeam::new(
        start,
        end,
        0,
        TELEGRAPH_THICKNESS,
        0.0,
        duration.max(0.01),
        TELEGRAPH_COLOR,
        TELEGRAPH_OWNER,
    )
    .with_id(id);
    lasers.push(beam);
    id
}

pub fn set_windup_telegraph(lasers: &mut [LaserBeam], beam_id: Option<u64>, start: Vec2, end: Vec2) {
    let Some(id) = beam_id else {
        return;
    };
    if let Some(beam) = lasers
        .iter_mut()
        .find(|b| b.id == id && b.owner == TELEGRAPH_OWNER)
    {
        beam.start = start;
        beam.end = end;
    }
}

fn refresh_windup_telegraph(
    lasers: &mut Vec<LaserBeam>,
    next_id: &mut u64,
    beam_id: &mut Option<u64>,
    start: Vec2,
    end: Vec2,
    remaining: f32,
) {
    let exists = beam_id.is_some_and(|id| {
        lasers
            .iter()
            .any(|beam| beam.id == id && beam.owner == TELEGRAPH_OWNER)
    });
    if exists {
        set_windup_telegraph(lasers, *beam_id, start, end);
    } else {
        *beam_id = Some(add_windup_telegraph(
            lasers,
            next_id,
            start,
            end,
            remaining.max(0.06),
        ));
    }
}

pub fn remove_telegraph(lasers: &mut Vec<LaserBeam>, beam_id: Option<u64>) {
    if let Some(id) = beam_id {
        lasers.retain(|b| b.id != id);
    }
}

/// Cancel a committed enemy action when a stun or boss phase transition makes
/// its target/cue stale. Launched projectiles and deployed floor hazards remain
/// committed; the next attack waits through an explicit recovery interval.
pub fn cancel_attack_for_interrupt(
    enemy: &mut Enemy,
    lasers: &mut Vec<LaserBeam>,
    recovery_seconds: f32,
) {
    remove_telegraph(lasers, enemy.ai.telegraph_beam_id);
    lasers.retain(|b| {
        !(b.owner == "enemy"
            && b.source == enemy.behavior
            && (enemy.behavior == "boss_laser" || b.warn <= 0.0))
    });
    enemy.ai.telegraph_beam_id = None;
    enemy.ai.director_granted = false;
    enemy.ai.sub_state = EnemySubState::None;
    enemy.ai.state_timer = None;
    enemy.ai.sub_timer = 0.0;
    enemy.ai.forward_lock_t = 0.0;
    enemy.ai.lunge_t = 0.0;
    enemy.ai.lunge_windup = 0.0;
    enemy.ai.charger_dashing = false;
    enemy.ai.burst_left = 0;
    enemy.ai.burst_gap = 0.0;
    enemy.ai.brace_t = None;
    enemy.ai.push_t = 0.0;
    enemy.ai.summon_target_count = 0;
    enemy.vel = Vec2::ZERO;
    enemy.attack_cd = enemy.attack_cd.max(recovery_seconds.max(0.0));
}

pub fn append_trap_capped(traps: &mut Vec<Trap>, trap: Trap) -> bool {
    if traps.len() >= MAX_ACTIVE_CONSTRUCTIONS {
        return false;
    }
    traps.push(trap);
    true
}

fn det_sign(enemy: &Enemy, mix_seed: bool) -> f32 {
    let val = if mix_seed {
        ((enemy.seed * 1000.0) as i64) + enemy.spawn_index
    } else {
        enemy.spawn_index
    };
    if val.rem_euclid(2) != 0 {
        1.0
    } else {
        -1.0
    }
}

pub fn steer_clear_of_obstacles(enemy: &Enemy, direction: Vec2, obstacles: &[Obstacle]) -> Vec2 {
    if direction.length_squared() <= 1e-6 {
        return Vec2::ZERO;
    }
    let desired = safe_dir(direction, Vec2::new(1.0, 0.0));
    if obstacles.is_empty() {
        return desired;
    }

    let lateral_axis = perp(desired);
    let look_ahead = (enemy.radius + 54.0).clamp(46.0, 82.0);
    let mut left_pressure = 0.0;
    let mut right_pressure = 0.0;
    for obstacle in obstacles {
        let offset = obstacle.pos - enemy.pos;
        let along = offset.dot(desired);
        let reach = look_ahead + obstacle.radius;
        if along < -enemy.radius * 0.25 || along > reach {
            continue;
        }
        let lateral = offset.dot(lateral_axis);
        let clearance = obstacle.radius + enemy.radius + 14.0;
        if lateral.abs() >= clearance {
            continue;
        }
        let urgency = (1.0 - along.max(0.0) / reach).clamp(0.0, 1.0)
            * (1.0 - lateral.abs() / clearance).clamp(0.0, 1.0);
        if lateral >= 0.0 {
            left_pressure += urgency;
        } else {
            right_pressure += urgency;
        }
    }

    let pressure = left_pressure + right_pressure;
    if pressure <= 0.01 {
        return desired;
    }
    let side = if (left_pressure - right_pressure).abs() < 0.02 {
        det_sign(enemy, false)
    } else if left_pressure < right_pressure {
        1.0
    } else {
        -1.0
    };
    safe_dir(
        desired + lateral_axis * side * (0.62 + pressure.min(1.0) * 0.42),
        desired,
    )
}

#[inline]
fn make_proposal(
    enemy_idx: usize,
    enemy: &Enemy,
    weight: u8,
    attack_range: f32,
    dist_to_player: f32,
    perception: &Perception,
) -> AttackProposal {
    AttackProposal {
        enemy_idx,
        enemy_id: enemy.id,
        spawn_index: enemy.spawn_index,
        role: enemy.role,
        category: attack_category_for_role(enemy.role),
        weight,
        range_ok: dist_to_player <= attack_range,
        on_screen: perception
            .on_screen_rect
            .contains(enemy.pos, enemy.radius + 16.0),
        sniper_visible: enemy.role == EnemyRole::Sniper
            && perception.on_screen_rect.contains(enemy.pos, 180.0),
        denied_t: enemy.ai.attack_denied_t,
        attack_range,
        dist_to_player,
    }
}

#[inline]
fn can_propose_attack(skill: &AiSkill, perception: &Perception) -> bool {
    !skill.respects_iframes || perception.invulnerable_left <= 0.0
}

#[allow(clippy::too_many_arguments)]
pub fn update_regular_behavior(
    enemy_idx: usize,
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    perception: &Perception,
    skill: &AiSkill,
    director: &mut AttackDirector,
) -> MoveIntent {
    enemy.ai.dodge_active_left = (enemy.ai.dodge_active_left - ctx.dt).max(0.0);
    enemy.ai.dodge_cooldown_left = (enemy.ai.dodge_cooldown_left - ctx.dt).max(0.0);
    match enemy.role {
        EnemyRole::Chaser => update_chase(enemy_idx, enemy, ctx, perception, skill, director),
        EnemyRole::Ranged => update_ranged(enemy_idx, enemy, ctx, perception, skill, director),
        EnemyRole::Swarm => update_swarm(enemy, ctx, perception, skill),
        EnemyRole::Charger => update_charger(enemy_idx, enemy, ctx, perception, skill, director),
        EnemyRole::Tank => update_tank(enemy_idx, enemy, ctx, perception, skill, director),
        EnemyRole::Spitter => update_spitter(enemy_idx, enemy, ctx, perception, skill, director),
        EnemyRole::Flyer => update_flyer(enemy_idx, enemy, ctx, perception, skill, director),
        EnemyRole::Sniper => update_sniper(enemy_idx, enemy, ctx, perception, skill, director),
        EnemyRole::Engineer => update_engineer(enemy_idx, enemy, ctx, perception, skill, director),
        EnemyRole::Bomber => update_bomber(enemy_idx, enemy, ctx, perception, skill, director),
        EnemyRole::EggSac => {
            update_egg_sac(enemy, ctx);
            MoveIntent::hold()
        }
        EnemyRole::Boss => MoveIntent::hold(),
    }
}

/// Same-tick commit pass for proposals granted by `AttackDirector::resolve`.
/// Eliminates 1-tick commit latency while preserving vector-order independence.
#[allow(clippy::too_many_arguments)]
pub fn commit_granted_attacks(
    enemies: &mut [Enemy],
    intents: &mut [Option<MoveIntent>],
    lasers: &mut Vec<LaserBeam>,
    next_id: &mut u64,
    rng: &mut SimRng,
    perception: &Perception,
    skill: &AiSkill,
    wave: i32,
    room_radius: f32,
    map_type: &str,
) {
    for (idx, enemy) in enemies.iter_mut().enumerate() {
        if !enemy.ai.director_granted {
            continue;
        }
        enemy.ai.director_granted = false;
        if enemy.is_dead || enemy.hp <= 0 {
            continue;
        }

        let dir = safe_dir(perception.player_pos - enemy.pos, Vec2::new(1.0, 0.0));
        match enemy.role {
            EnemyRole::Sniper => {
                let aim_time = crate::sim::config::SNIPER_AIM_SECONDS;
                enemy.ai.sniper_aim = predict_target(
                    enemy.pos,
                    2000.0,
                    enemy,
                    perception,
                    skill,
                    0.0,
                    room_radius,
                    map_type,
                    rng,
                    0.35,
                );
                enemy.ai.sub_state = EnemySubState::SniperWindup;
                enemy.ai.sub_timer = aim_time;
                let aim_dir = safe_dir(enemy.ai.sniper_aim - enemy.pos, dir);
                let end = enemy.pos + aim_dir * (room_radius * 2.2);
                let beam_id = add_windup_telegraph(lasers, next_id, enemy.pos, end, aim_time);
                enemy.ai.telegraph_beam_id = Some(beam_id);
                if let Some(slot) = intents.get_mut(idx) {
                    *slot = Some(MoveIntent::hold());
                }
            }
            EnemyRole::Chaser => {
                let aim_pt = predict_target(
                    enemy.pos,
                    (enemy.speed * 1.7).max(120.0),
                    enemy,
                    perception,
                    skill,
                    0.0,
                    room_radius,
                    map_type,
                    rng,
                    0.25,
                );
                let lunge_dir = safe_dir(aim_pt - enemy.pos, dir);
                let planned_t = 0.28 + rng.range_f32(0.0, 0.1);
                enemy.ai.sub_timer = planned_t;
                enemy.ai.lunge_windup = LUNGE_WINDUP_S;
                enemy.ai.lunge_cd = Some(1.4 + rng.range_f32(0.0, 0.6));
                enemy.ai.lunge_dir = lunge_dir;
                let reach = enemy.speed * 1.7 * planned_t;
                let bid = add_windup_telegraph(
                    lasers,
                    next_id,
                    enemy.pos,
                    enemy.pos + lunge_dir * reach,
                    LUNGE_WINDUP_S,
                );
                enemy.ai.telegraph_beam_id = Some(bid);
                if let Some(slot) = intents.get_mut(idx) {
                    *slot = Some(MoveIntent::hold());
                }
            }
            EnemyRole::Charger => {
                const WINDUP_TIME: f32 = 0.5;
                let raw_aim = predict_target(
                    enemy.pos,
                    (enemy.speed * 3.0).max(120.0),
                    enemy,
                    perception,
                    skill,
                    0.0,
                    room_radius,
                    map_type,
                    rng,
                    0.25,
                );
                let aim = clamp_entity_to_map(raw_aim, room_radius, enemy.radius + 6.0, map_type);
                enemy.ai.sub_state = EnemySubState::ChargerWindup;
                enemy.ai.state_timer = Some(WINDUP_TIME);
                enemy.ai.charge_target = aim;
                enemy.ai.charge_dir = safe_dir(aim - enemy.pos, dir);
                let bid = add_windup_telegraph(lasers, next_id, enemy.pos, aim, WINDUP_TIME);
                enemy.ai.telegraph_beam_id = Some(bid);
                if let Some(slot) = intents.get_mut(idx) {
                    *slot = Some(MoveIntent::hold());
                }
            }
            EnemyRole::Flyer => {
                let orbit_sign = *enemy.ai.orbit_sign.get_or_insert(det_sign(enemy, true));
                let dash_speed = (enemy.speed * 4.0).max(120.0);
                let est_t = (perception.player_pos - enemy.pos).length() / dash_speed;
                let lead_vel = perception.smoothed_vel * 0.72 + perception.intent_vel * 0.28;
                let intercept = perception.player_pos
                    + lead_vel * ((FLYER_WINDUP_SECONDS + est_t * 0.60) * skill.lead_quality);
                let to_intercept = safe_dir(intercept - enemy.pos, dir);
                let lateral = perp(to_intercept) * orbit_sign;
                let raw_target = intercept + to_intercept * 55.0 + lateral * 22.0;
                let dash_target =
                    clamp_entity_to_map(raw_target, room_radius, enemy.radius + 6.0, map_type);
                enemy.ai.sub_state = EnemySubState::FlyerWindup;
                enemy.ai.state_timer = Some(FLYER_WINDUP_SECONDS);
                enemy.ai.dash_target = dash_target;
                let bid = add_windup_telegraph(
                    lasers,
                    next_id,
                    enemy.pos,
                    dash_target,
                    FLYER_WINDUP_SECONDS,
                );
                enemy.ai.telegraph_beam_id = Some(bid);
                if let Some(slot) = intents.get_mut(idx) {
                    *slot = Some(MoveIntent::hold());
                }
            }
            EnemyRole::Bomber => {
                let d = (perception.player_pos - enemy.pos).length();
                enemy.ai.move_target = predict_target(
                    enemy.pos,
                    (d / BOMBER_FUSE_SECONDS).max(120.0),
                    enemy,
                    perception,
                    skill,
                    0.0,
                    room_radius,
                    map_type,
                    rng,
                    0.0,
                );
                enemy.ai.sub_state = EnemySubState::BomberWindup;
                enemy.ai.sub_timer = BOMBER_WINDUP_SECONDS;
                refresh_windup_telegraph(
                    lasers,
                    next_id,
                    &mut enemy.ai.telegraph_beam_id,
                    enemy.pos,
                    enemy.ai.move_target,
                    BOMBER_WINDUP_SECONDS,
                );
                if let Some(slot) = intents.get_mut(idx) {
                    *slot = Some(MoveIntent::hold());
                }
            }
            EnemyRole::Engineer => {
                enemy.ai.move_target =
                    clamp_entity_to_map(enemy.ai.move_target, room_radius, 34.0, map_type);
                enemy.ai.sub_state = EnemySubState::EngineerWindup;
                enemy.ai.sub_timer = 0.54;
                if let Some(slot) = intents.get_mut(idx) {
                    *slot = Some(MoveIntent::hold());
                }
            }
            EnemyRole::Ranged => {
                const WINDUP: f32 = 0.34;
                enemy.ai.burst_left = rng.range_i32(1, 2);
                enemy.ai.burst_gap = 0.0;
                let proj_speed = 205.0 + (wave as f32) * 2.2;
                let telegraph_range = proj_speed * 2.4;
                let aim_pt = predict_target(
                    enemy.pos,
                    proj_speed,
                    enemy,
                    perception,
                    skill,
                    0.0,
                    room_radius,
                    map_type,
                    rng,
                    0.75,
                );
                let aim = safe_dir(aim_pt - enemy.pos, dir);
                enemy.ai.sniper_aim = enemy.pos + aim * telegraph_range;
                enemy.ai.sub_state = EnemySubState::RangedWindup;
                enemy.ai.sub_timer = WINDUP;
                refresh_windup_telegraph(
                    lasers,
                    next_id,
                    &mut enemy.ai.telegraph_beam_id,
                    enemy.pos,
                    enemy.ai.sniper_aim,
                    WINDUP,
                );
                if let Some(slot) = intents.get_mut(idx) {
                    *slot = Some(MoveIntent::hold());
                }
            }
            EnemyRole::Spitter => {
                const WINDUP: f32 = 0.38;
                let telegraph_range = if enemy.ai.volley_mode == 0 { 525.0 } else { 487.5 };
                let proj_speed = if enemy.ai.volley_mode == 0 { 210.0 } else { 195.0 };
                let aim_pt = predict_target(
                    enemy.pos,
                    proj_speed,
                    enemy,
                    perception,
                    skill,
                    0.0,
                    room_radius,
                    map_type,
                    rng,
                    0.65,
                );
                let aim = safe_dir(aim_pt - enemy.pos, dir);
                enemy.ai.sniper_aim = enemy.pos + aim * telegraph_range;
                enemy.ai.sub_state = EnemySubState::SpitterWindup;
                enemy.ai.sub_timer = WINDUP;
                refresh_windup_telegraph(
                    lasers,
                    next_id,
                    &mut enemy.ai.telegraph_beam_id,
                    enemy.pos,
                    enemy.ai.sniper_aim,
                    WINDUP,
                );
                if let Some(slot) = intents.get_mut(idx) {
                    *slot = Some(MoveIntent::hold());
                }
            }
            EnemyRole::Tank => {
                let aim_pt = predict_target(
                    enemy.pos,
                    TANK_PROJ_SPEED,
                    enemy,
                    perception,
                    skill,
                    0.0,
                    room_radius,
                    map_type,
                    rng,
                    0.5,
                );
                let aim = safe_dir(aim_pt - enemy.pos, dir);
                enemy.ai.sniper_aim = enemy.pos + aim * TANK_RANGE;
                enemy.ai.sub_state = EnemySubState::TankWindup;
                enemy.ai.sub_timer = TANK_WINDUP_SECONDS;
                refresh_windup_telegraph(
                    lasers,
                    next_id,
                    &mut enemy.ai.telegraph_beam_id,
                    enemy.pos,
                    enemy.ai.sniper_aim,
                    TANK_WINDUP_SECONDS,
                );
                if let Some(slot) = intents.get_mut(idx) {
                    *slot = Some(MoveIntent::hold());
                }
            }
            EnemyRole::Swarm | EnemyRole::EggSac | EnemyRole::Boss => {}
        }
    }
}

fn update_sniper(
    enemy_idx: usize,
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    perception: &Perception,
    skill: &AiSkill,
    director: &mut AttackDirector,
) -> MoveIntent {
    const COMFORT_NEAR: f32 = 240.0;
    const COMFORT_FAR: f32 = 385.0;
    const SNIPER_FIRE_RANGE: f32 = 450.0;
    const MAX_RANGE_MULT: f32 = 2.2;
    let lock_time = crate::sim::config::SNIPER_LOCK_SECONDS;
    let recover_time = crate::sim::config::SNIPER_RECOVER_SECONDS;

    let to_player = perception.player_pos - enemy.pos;
    let distance = to_player.length();
    let dir = safe_dir(to_player, Vec2::new(1.0, 0.0));
    let sign = *enemy.ai.strafe_sign.get_or_insert(det_sign(enemy, false));
    let separation = separation_inv_sq(enemy.pos, enemy.id, ctx.enemy_snaps, 52.0, 1.0);
    let dodge = if matches!(
        enemy.ai.sub_state,
        EnemySubState::None | EnemySubState::SniperRecover
    ) {
        dodge_player_projectiles(
            enemy,
            ctx.projectiles,
            110.0,
            5,
            true,
            ctx.dt,
            skill,
            ctx.room_radius,
            ctx.map_type,
            ctx.rng,
        )
    } else {
        Vec2::ZERO
    };

    match enemy.ai.sub_state {
        EnemySubState::None => {
            let dodging = dodge.length_squared() > 1e-6;
            let (steer, speed_mult) = if dodging {
                let radial = if distance > COMFORT_FAR {
                    dir * 0.45
                } else if distance < COMFORT_NEAR {
                    -dir * 0.45
                } else {
                    Vec2::ZERO
                };
                (radial + separation * 0.5 + dodge * 1.4, 0.95)
            } else if distance > COMFORT_FAR {
                (dir * 0.9 + separation * 0.6, 0.9)
            } else if distance < COMFORT_NEAR {
                (-dir * 0.95 + separation * 0.8, 0.95)
            } else {
                (perp(dir) * sign + separation * 0.75, 0.72)
            };
            let move_dir = steer_clear_of_obstacles(enemy, steer, ctx.obstacles);

            enemy.attack_cd -= ctx.dt;
            let on_screen_inset = perception.on_screen_rect.contains(enemy.pos, -20.0);
            let forced_ready = enemy.ai.attack_denied_t >= MAX_ATTACK_WAIT_SECONDS;
            if enemy.attack_cd <= 0.0
                && distance < SNIPER_FIRE_RANGE
                && distance > 90.0
                && can_propose_attack(skill, perception)
            {
                if on_screen_inset || forced_ready {
                    director.propose(make_proposal(
                        enemy_idx,
                        enemy,
                        2,
                        SNIPER_FIRE_RANGE,
                        distance,
                        perception,
                    ));
                } else {
                    enemy.ai.attack_denied_t += ctx.dt.max(0.0);
                }
            }

            if dodge.length_squared() > 1e-6 {
                MoveIntent::evade(move_dir, speed_mult)
            } else {
                MoveIntent::role(move_dir, speed_mult, None)
            }
        }
        EnemySubState::SniperWindup => {
            enemy.ai.sub_timer = (enemy.ai.sub_timer - ctx.dt).max(0.0);
            if enemy.ai.sub_timer > lock_time && !perception.is_dashing {
                enemy.ai.sniper_aim = predict_target(
                    enemy.pos,
                    2000.0,
                    enemy,
                    perception,
                    skill,
                    ctx.dt,
                    ctx.room_radius,
                    ctx.map_type,
                    ctx.rng,
                    0.0,
                );
            }
            let aim_dir = safe_dir(enemy.ai.sniper_aim - enemy.pos, dir);
            let end = enemy.pos + aim_dir * (ctx.room_radius * MAX_RANGE_MULT);
            refresh_windup_telegraph(
                ctx.lasers,
                ctx.next_id,
                &mut enemy.ai.telegraph_beam_id,
                enemy.pos,
                end,
                enemy.ai.sub_timer,
            );
            if enemy.ai.sub_timer <= lock_time {
                if let Some(id) = enemy.ai.telegraph_beam_id {
                    if let Some(beam) = ctx
                        .lasers
                        .iter_mut()
                        .find(|b| b.id == id && b.owner == TELEGRAPH_OWNER)
                    {
                        beam.color = [255, 112, 165];
                    }
                }
            }

            if enemy.ai.sub_timer <= 0.0 {
                remove_telegraph(ctx.lasers, enemy.ai.telegraph_beam_id);
                enemy.ai.telegraph_beam_id = None;
                let damage = 12 + ctx.wave / 3;
                ctx.lasers.push(LaserBeam::new(
                    enemy.pos,
                    end,
                    damage,
                    11.0,
                    0.12,
                    0.0,
                    [255, 92, 170],
                    "enemy",
                ));
                enemy.attack_cd =
                    (2.55 + ctx.rng.range_f32(0.25, 0.7)) / sustained_cd_scale(enemy);
                enemy.ai.sub_state = EnemySubState::SniperRecover;
                enemy.ai.sub_timer = recover_time;
                enemy.ai.strafe_sign = Some(-sign);
            }
            MoveIntent::hold()
        }
        EnemySubState::SniperRecover => {
            enemy.ai.sub_timer = (enemy.ai.sub_timer - ctx.dt).max(0.0);
            let retreat = if distance < COMFORT_NEAR {
                -dir * 0.45
            } else {
                Vec2::ZERO
            };
            let lateral = if dodge.length_squared() > 1e-6 {
                dodge * 1.4
            } else {
                perp(dir) * sign * 0.78
            };
            let move_dir = steer_clear_of_obstacles(
                enemy,
                lateral + retreat + separation * 0.65,
                ctx.obstacles,
            );
            if enemy.ai.sub_timer <= 0.0 {
                enemy.ai.sub_state = EnemySubState::None;
            }
            if dodge.length_squared() > 1e-6 {
                MoveIntent::evade(move_dir, 0.78)
            } else {
                MoveIntent::role(move_dir, 0.78, None)
            }
        }
        _ => {
            enemy.ai.sub_state = EnemySubState::None;
            MoveIntent::hold()
        }
    }
}

fn update_chase(
    enemy_idx: usize,
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    perception: &Perception,
    skill: &AiSkill,
    director: &mut AttackDirector,
) -> MoveIntent {
    if enemy.ai.lunge_cd.is_none() {
        enemy.ai.lunge_cd = Some(ctx.rng.range_f32(0.4, 1.2));
    }
    let det_o = det_sign(enemy, true);
    let mut orbit_sign = *enemy.ai.orbit_sign.get_or_insert(det_o);

    let dist_to_player = (perception.player_pos - enemy.pos).length();
    enemy.ai.relocate_t = (enemy.ai.relocate_t - ctx.dt).max(0.0);
    if enemy.ai.lunge_windup <= 0.0
        && enemy.ai.lunge_t <= 0.0
        && enemy.ai.relocate_t <= 0.0
        && dist_to_player < 240.0
        && dist_to_player > 1e-3
    {
        let from_player = (enemy.pos - perception.player_pos) / dist_to_player;
        let aim_norm = safe_dir(perception.aim_dir, Vec2::ZERO);
        if aim_norm.length_squared() > 0.5
            && aim_norm.dot(from_player) >= 18.0_f32.to_radians().cos()
        {
            orbit_sign = -orbit_sign;
            enemy.ai.orbit_sign = Some(orbit_sign);
            enemy.ai.relocate_t = 0.65;
        }
    }
    let predicted = predict_target(
        enemy.pos,
        enemy.speed.max(90.0),
        enemy,
        perception,
        skill,
        ctx.dt,
        ctx.room_radius,
        ctx.map_type,
        ctx.rng,
        0.0,
    );
    let dir_to = safe_dir(predicted - enemy.pos, Vec2::new(1.0, 0.0));
    let orbit = perp(dir_to) * orbit_sign;
    let dodge = if enemy.ai.lunge_windup <= 0.0 && enemy.ai.lunge_t <= 0.0 {
        dodge_player_projectiles(
            enemy,
            ctx.projectiles,
            70.0,
            4,
            true,
            ctx.dt,
            skill,
            ctx.room_radius,
            ctx.map_type,
            ctx.rng,
        )
    } else {
        Vec2::ZERO
    };
    let sep = separation_inv_sq(enemy.pos, enemy.id, ctx.enemy_snaps, 44.0, 1.1);

    let pressure = if dist_to_player < 160.0 {
        (160.0 - dist_to_player) / 160.0
    } else {
        0.0
    };

    let lcd = enemy.ai.lunge_cd.unwrap_or(0.0) - ctx.dt;
    enemy.ai.lunge_cd = Some(lcd);
    enemy.ai.lunge_t = (enemy.ai.lunge_t - ctx.dt).max(0.0);

    if enemy.ai.lunge_windup > 0.0 {
        enemy.ai.lunge_windup = (enemy.ai.lunge_windup - ctx.dt).max(0.0);
        if enemy.ai.lunge_windup > 0.0 {
            return MoveIntent::hold();
        }
        remove_telegraph(ctx.lasers, enemy.ai.telegraph_beam_id);
        enemy.ai.telegraph_beam_id = None;
        enemy.ai.lunge_t = if enemy.ai.sub_timer > 0.0 {
            enemy.ai.sub_timer
        } else {
            0.33
        };
        enemy.ai.sub_timer = 0.0;
    } else if enemy.ai.lunge_t <= 0.0
        && lcd <= 0.0
        && dist_to_player > 80.0
        && dist_to_player < 240.0
        && can_propose_attack(skill, perception)
    {
        director.propose(make_proposal(
            enemy_idx,
            enemy,
            1,
            240.0,
            dist_to_player,
            perception,
        ));
    }

    if enemy.ai.lunge_t > 0.0 {
        let ld = if enemy.ai.lunge_dir.length_squared() > 1e-6 {
            enemy.ai.lunge_dir
        } else {
            dir_to
        };
        return MoveIntent::committed(ld, 1.7);
    }

    let mv = (dir_to * (1.0 + pressure * 0.25)
        + orbit * (0.28 + pressure * 0.35)
        + sep
        + dodge * 1.05)
        .normalized();
    let speed_mult = 1.0 + pressure * 0.22;
    let move_dir = steer_clear_of_obstacles(enemy, mv, ctx.obstacles);
    if dodge.length_squared() > 1e-6 {
        MoveIntent::evade(move_dir, speed_mult)
    } else {
        MoveIntent::role(move_dir, speed_mult, None)
    }
}

fn charger_clear_path(
    start: Vec2,
    dir: Vec2,
    reach: f32,
    enemy_radius: f32,
    room_radius: f32,
    map_type: &str,
    obstacles: &[Obstacle],
) -> bool {
    let end = start + dir * reach;
    for step in 1..=4 {
        let sample = start + dir * (reach * (step as f32 * 0.25));
        if !arena_inside(sample, room_radius, map_type) {
            return false;
        }
        let clamped = clamp_entity_to_map(sample, room_radius, enemy_radius + 6.0, map_type);
        if (clamped - sample).length_squared() > 4.0 {
            return false;
        }
    }
    !obstacles.iter().any(|ob| {
        point_segment_distance_sq(ob.pos, start, end) <= (ob.radius + enemy_radius + 4.0).powi(2)
    })
}

fn update_charger(
    enemy_idx: usize,
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    perception: &Perception,
    skill: &AiSkill,
    director: &mut AttackDirector,
) -> MoveIntent {
    const CHARGE_SPEED_MULT: f32 = 3.0;
    const COOLDOWN_TIME: f32 = 1.0;
    const REPOSITION_DIST: f32 = 200.0;

    if enemy.ai.sub_state == EnemySubState::None {
        enemy.ai.sub_state = EnemySubState::ChargerRepositioning;
        enemy.ai.state_timer = Some(0.0);
    }

    let dvec = perception.player_pos - enemy.pos;
    let dist_to_player = dvec.length();
    let dir_to_player = safe_dir(dvec, Vec2::new(1.0, 0.0));

    let timer = enemy.ai.state_timer.unwrap_or(0.0) - ctx.dt;
    enemy.ai.state_timer = Some(timer);

    match enemy.ai.sub_state {
        EnemySubState::ChargerRepositioning => {
            enemy.ai.charger_dashing = false;
            if dist_to_player < REPOSITION_DIST
                && can_propose_attack(skill, perception)
                && charger_clear_path(
                    enemy.pos,
                    dir_to_player,
                    120.0,
                    enemy.radius,
                    ctx.room_radius,
                    ctx.map_type,
                    ctx.obstacles,
                )
            {
                director.propose(make_proposal(
                    enemy_idx,
                    enemy,
                    2,
                    REPOSITION_DIST,
                    dist_to_player,
                    perception,
                ));
            }
            let mut steer = Vec2::ZERO;
            let mut count = 0usize;
            for &(oid, opos, _, _) in ctx.enemy_snaps {
                if oid == enemy.id {
                    continue;
                }
                let dv = enemy.pos - opos;
                let d = dv.length();
                if d > 0.0 && d < 60.0 {
                    steer += dv / (d * d);
                    count += 1;
                }
            }
            if count > 0 {
                steer /= count as f32;
            }
            let move_dir = steer_clear_of_obstacles(
                enemy,
                dir_to_player + steer * 0.5,
                ctx.obstacles,
            );
            MoveIntent::role(move_dir, 1.0, None)
        }
        EnemySubState::ChargerWindup => {
            if timer > 0.15 {
                let raw_aim = predict_target(
                    enemy.pos,
                    (enemy.speed * CHARGE_SPEED_MULT).max(120.0),
                    enemy,
                    perception,
                    skill,
                    ctx.dt,
                    ctx.room_radius,
                    ctx.map_type,
                    ctx.rng,
                    0.0,
                );
                let aim = clamp_entity_to_map(
                    raw_aim,
                    ctx.room_radius,
                    enemy.radius + 6.0,
                    ctx.map_type,
                );
                enemy.ai.charge_target = aim;
                enemy.ai.charge_dir = safe_dir(aim - enemy.pos, dir_to_player);
                set_windup_telegraph(ctx.lasers, enemy.ai.telegraph_beam_id, enemy.pos, aim);
            }
            if timer <= 0.0 {
                remove_telegraph(ctx.lasers, enemy.ai.telegraph_beam_id);
                enemy.ai.telegraph_beam_id = None;
                enemy.ai.sub_state = EnemySubState::ChargerCharging;
                enemy.ai.charger_dashing = true;
                if enemy.ai.charge_dir.length_squared() <= 1e-6 {
                    enemy.ai.charge_dir =
                        safe_dir(enemy.ai.charge_target - enemy.pos, dir_to_player);
                }
                enemy.ai.state_timer = Some(1.15);
            }
            MoveIntent::hold()
        }
        EnemySubState::ChargerCharging => {
            enemy.ai.charger_dashing = true;
            let cd = safe_dir(enemy.ai.charge_dir, dir_to_player);
            let rem = enemy.ai.charge_target - enemy.pos;
            if timer <= 0.0 || rem.length() < 30.0 || cd.dot(rem.normalized()) < 0.0 {
                enemy.ai.sub_state = EnemySubState::ChargerCooldown;
                enemy.ai.state_timer = Some(COOLDOWN_TIME);
                enemy.ai.charger_dashing = false;
                return MoveIntent::hold();
            }
            MoveIntent::committed(cd, CHARGE_SPEED_MULT)
        }
        EnemySubState::ChargerCooldown => {
            enemy.ai.charger_dashing = false;
            if timer <= 0.0 {
                enemy.ai.sub_state = EnemySubState::ChargerRepositioning;
            }
            MoveIntent::hold()
        }
        _ => MoveIntent::hold(),
    }
}

fn update_flyer(
    enemy_idx: usize,
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    perception: &Perception,
    skill: &AiSkill,
    director: &mut AttackDirector,
) -> MoveIntent {
    const CIRCLING_DUR: f32 = 2.05;
    const DASH_SPEED_MULT: f32 = 4.0;
    const CIRCLING_DIST: f32 = 150.0;

    if enemy.ai.sub_state == EnemySubState::None {
        enemy.ai.sub_state = EnemySubState::FlyerCircling;
        enemy.ai.state_timer = Some(CIRCLING_DUR + ctx.rng.range_f32(-0.5, 0.5));
    }

    let dvec = perception.player_pos - enemy.pos;
    let d = dvec.length();
    let dir_to = safe_dir(dvec, Vec2::new(1.0, 0.0));

    match enemy.ai.sub_state {
        EnemySubState::FlyerCircling => {
            let timer = enemy.ai.state_timer.unwrap_or(0.0) - ctx.dt;
            enemy.ai.state_timer = Some(timer.max(0.0));
            if timer <= 0.0 && can_propose_attack(skill, perception) {
                director.propose(make_proposal(
                    enemy_idx,
                    enemy,
                    1,
                    320.0,
                    d,
                    perception,
                ));
            }
            let dodge = dodge_player_projectiles(
                enemy,
                ctx.projectiles,
                95.0,
                4,
                true,
                ctx.dt,
                skill,
                ctx.room_radius,
                ctx.map_type,
                ctx.rng,
            );
            let mut acc = Vec2::ZERO;
            let mut count = 0usize;
            for &(oid, opos, _, _) in ctx.enemy_snaps {
                if oid == enemy.id {
                    continue;
                }
                let dv = enemy.pos - opos;
                let dist = dv.length();
                if dist <= 1e-6 || dist > 50.0 {
                    continue;
                }
                acc += (dv / dist) * (1.0 - dist / 50.0);
                count += 1;
            }
            let sep = if count == 0 {
                Vec2::ZERO
            } else {
                (acc / count as f32).normalized() * 1.2
            };
            let radial = if d > CIRCLING_DIST + 20.0 {
                dir_to
            } else if d < CIRCLING_DIST - 20.0 {
                -dir_to
            } else {
                Vec2::ZERO
            };
            let orbit_sign = *enemy.ai.orbit_sign.get_or_insert(det_sign(enemy, true));
            let strafe = perp(dir_to) * orbit_sign;
            let move_dir = steer_clear_of_obstacles(
                enemy,
                radial * 0.6 + strafe * 0.4 + sep * 0.5 + dodge * 0.85,
                ctx.obstacles,
            );
            if dodge.length_squared() > 1e-6 {
                MoveIntent::evade(move_dir, 1.0)
            } else {
                MoveIntent::role(move_dir, 1.0, None)
            }
        }
        EnemySubState::FlyerWindup => {
            let timer = enemy.ai.state_timer.unwrap_or(0.0) - ctx.dt;
            enemy.ai.state_timer = Some(timer);
            if timer <= 0.0 {
                remove_telegraph(ctx.lasers, enemy.ai.telegraph_beam_id);
                enemy.ai.telegraph_beam_id = None;
                enemy.ai.sub_state = EnemySubState::FlyerDashing;
                let dash_speed = (enemy.speed * DASH_SPEED_MULT).max(1.0);
                enemy.ai.state_timer = Some(
                    ((enemy.ai.dash_target - enemy.pos).length() / dash_speed)
                        .clamp(0.18, FLYER_DASH_TIMEOUT_SECONDS),
                );
            }
            MoveIntent::hold()
        }
        EnemySubState::FlyerDashing => {
            let dash_left = enemy.ai.state_timer.unwrap_or(0.0) - ctx.dt;
            enemy.ai.state_timer = Some(dash_left);
            let dvec = enemy.ai.dash_target - enemy.pos;
            if dvec.length() < 20.0 || dash_left <= 0.0 {
                let orbit_sign = *enemy.ai.orbit_sign.get_or_insert(det_sign(enemy, true));
                enemy.ai.orbit_sign = Some(-orbit_sign);
                enemy.ai.sub_state = EnemySubState::FlyerCircling;
                enemy.ai.state_timer = Some(CIRCLING_DUR + ctx.rng.range_f32(-0.5, 0.5));
                return MoveIntent::hold();
            }
            MoveIntent::committed(dvec.normalized(), DASH_SPEED_MULT)
        }
        _ => MoveIntent::hold(),
    }
}

fn update_bomber(
    enemy_idx: usize,
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    perception: &Perception,
    skill: &AiSkill,
    director: &mut AttackDirector,
) -> MoveIntent {
    if enemy.ai.sub_state == EnemySubState::BomberWindup {
        enemy.ai.sub_timer = (enemy.ai.sub_timer - ctx.dt).max(0.0);
        refresh_windup_telegraph(
            ctx.lasers,
            ctx.next_id,
            &mut enemy.ai.telegraph_beam_id,
            enemy.pos,
            enemy.ai.move_target,
            enemy.ai.sub_timer,
        );
        if enemy.ai.sub_timer > 0.0 {
            return MoveIntent::hold();
        }
        remove_telegraph(ctx.lasers, enemy.ai.telegraph_beam_id);
        enemy.ai.telegraph_beam_id = None;
        let fuse = BOMBER_FUSE_SECONDS;
        let velocity = (enemy.ai.move_target - enemy.pos) / fuse;
        ctx.projectiles.push(
            Projectile::new(
                enemy.pos,
                velocity,
                14 + ctx.wave / 3,
                fuse,
                "enemy",
                "bomb",
            )
            .with_source("bomber"),
        );
        enemy.attack_cd = (2.8 + ctx.rng.range_f32(0.0, 0.5)) / sustained_cd_scale(enemy);
        enemy.ai.sub_state = EnemySubState::None;
        return MoveIntent::hold();
    }

    let dvec = perception.player_pos - enemy.pos;
    let dist_to_player = dvec.length();
    let dir_to = safe_dir(dvec, Vec2::new(1.0, 0.0));
    let sep = separation_inv_sq(enemy.pos, enemy.id, ctx.enemy_snaps, 44.0, 1.2);
    let dodge = dodge_player_projectiles(
        enemy,
        ctx.projectiles,
        85.0,
        3,
        true,
        ctx.dt,
        skill,
        ctx.room_radius,
        ctx.map_type,
        ctx.rng,
    );
    let sign = det_sign(enemy, false);
    let dodging = dodge.length_squared() > 1e-6;
    let (mv, speed_mult) = if dodging {
        let radial = if dist_to_player < 130.0 {
            -dir_to * 0.45
        } else if dist_to_player > 250.0 {
            dir_to * 0.45
        } else {
            Vec2::ZERO
        };
        ((radial + sep * 0.6 + dodge * 1.25).normalized(), 1.0)
    } else if dist_to_player < 130.0 {
        (((-dir_to) + sep).normalized(), 1.05)
    } else if dist_to_player > 250.0 {
        ((dir_to + sep * 0.8).normalized(), 0.9)
    } else {
        (
            (sep + Vec2::new(-dir_to.y, dir_to.x) * sign * 0.65).normalized(),
            0.75,
        )
    };
    let move_dir = steer_clear_of_obstacles(enemy, mv, ctx.obstacles);

    enemy.attack_cd -= ctx.dt;
    if enemy.attack_cd <= 0.0
        && dist_to_player < 360.0
        && can_propose_attack(skill, perception)
    {
        director.propose(make_proposal(
            enemy_idx,
            enemy,
            1,
            360.0,
            dist_to_player,
            perception,
        ));
    }
    if dodging {
        MoveIntent::evade(move_dir, speed_mult)
    } else {
        MoveIntent::role(move_dir, speed_mult, None)
    }
}

fn update_engineer(
    enemy_idx: usize,
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    perception: &Perception,
    skill: &AiSkill,
    director: &mut AttackDirector,
) -> MoveIntent {
    if enemy.ai.sub_state == EnemySubState::EngineerWindup {
        enemy.ai.sub_timer = (enemy.ai.sub_timer - ctx.dt).max(0.0);
        if enemy.ai.sub_timer > 0.0 {
            return MoveIntent::hold();
        }

        let deployed = append_trap_capped(
            ctx.traps,
            Trap::new(enemy.ai.move_target, 28.0, 16, 10.0, 0.7, "mine"),
        );
        enemy.attack_cd = if deployed {
            (2.9 + ctx.rng.range_f32(0.0, 0.6)) / sustained_cd_scale(enemy)
        } else {
            0.85
        };
        enemy.ai.sub_state = EnemySubState::None;
        return MoveIntent::hold();
    }

    let dvec = perception.player_pos - enemy.pos;
    let d = dvec.length();
    let dir_to = if d > 1e-6 { dvec / d } else { Vec2::ZERO };
    let sep = separation_inv_sq(enemy.pos, enemy.id, ctx.enemy_snaps, 44.0, 1.1);
    let sign = det_sign(enemy, false);

    let intent = if d > 260.0 {
        let move_dir = steer_clear_of_obstacles(enemy, dir_to, ctx.obstacles);
        MoveIntent::role(move_dir, 0.85, None)
    } else if d < 180.0 {
        let move_dir = steer_clear_of_obstacles(enemy, -dir_to, ctx.obstacles);
        MoveIntent::role(move_dir, 0.95, None)
    } else {
        let strafe = perp(dir_to) * sign;
        let mv = steer_clear_of_obstacles(enemy, strafe * 0.8 + sep + dir_to * 0.1, ctx.obstacles);
        MoveIntent::role(mv, 0.85, None)
    };

    enemy.attack_cd -= ctx.dt;
    if enemy.attack_cd <= 0.0 && d < 420.0 && can_propose_attack(skill, perception) {
        if ctx.traps.len() >= MAX_ACTIVE_CONSTRUCTIONS {
            enemy.attack_cd = 0.85;
        } else {
            let mut base = predict_target(
                enemy.pos,
                180.0,
                enemy,
                perception,
                skill,
                0.0,
                ctx.room_radius,
                ctx.map_type,
                ctx.rng,
                0.6,
            );
            let max_r = ctx.room_radius * 0.86;
            if base.length() > max_r {
                base = base.normalized() * max_r;
            }
            let is_valid_mine_spot = |cand: Vec2| -> bool {
                let mines_clear = ctx
                    .traps
                    .iter()
                    .filter(|t| t.kind == "mine")
                    .all(|t| (t.pos - cand).length_squared() >= 70.0 * 70.0);
                let obstacles_clear = !ctx.obstacles.iter().any(|ob| {
                    (ob.pos - cand).length_squared() < (ob.radius + 28.0).powi(2)
                });
                mines_clear && obstacles_clear
            };
            let mut chosen = None;
            let base_clamped = clamp_entity_to_map(base, ctx.room_radius, 34.0, ctx.map_type);
            if is_valid_mine_spot(base_clamped) {
                chosen = Some(base_clamped);
            } else {
                for step in 0..8 {
                    let ang = enemy.seed + (step as f32) * (TAU / 8.0);
                    let cand = clamp_entity_to_map(
                        base + Vec2::new(ang.cos(), ang.sin()) * 74.0,
                        ctx.room_radius,
                        34.0,
                        ctx.map_type,
                    );
                    if is_valid_mine_spot(cand) {
                        chosen = Some(cand);
                        break;
                    }
                }
            }
            if let Some(target) = chosen {
                enemy.ai.move_target = target;
                director.propose(make_proposal(enemy_idx, enemy, 1, 420.0, d, perception));
            } else {
                enemy.attack_cd = 0.65;
            }
        }
    }
    intent
}

fn update_ranged(
    enemy_idx: usize,
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    perception: &Perception,
    skill: &AiSkill,
    director: &mut AttackDirector,
) -> MoveIntent {
    let proj_speed = 205.0 + (ctx.wave as f32) * 2.2;
    let telegraph_range = proj_speed * 2.4;

    if enemy.ai.sub_state == EnemySubState::RangedWindup {
        enemy.ai.sub_timer = (enemy.ai.sub_timer - ctx.dt).max(0.0);
        let aim = safe_dir(enemy.ai.sniper_aim - enemy.pos, Vec2::new(1.0, 0.0));
        refresh_windup_telegraph(
            ctx.lasers,
            ctx.next_id,
            &mut enemy.ai.telegraph_beam_id,
            enemy.pos,
            enemy.pos + aim * telegraph_range,
            enemy.ai.sub_timer,
        );
        if enemy.ai.sub_timer > 0.0 {
            return MoveIntent::hold();
        }

        remove_telegraph(ctx.lasers, enemy.ai.telegraph_beam_id);
        enemy.ai.telegraph_beam_id = None;
        ctx.projectiles.push(
            Projectile::new(
                enemy.pos,
                aim * proj_speed,
                6 + ctx.wave / 3,
                2.4,
                "enemy",
                "bullet",
            )
            .with_source("ranged"),
        );
        enemy.ai.burst_left -= 1;
        if enemy.ai.burst_left > 0 {
            let dir_to = safe_dir(perception.player_pos - enemy.pos, Vec2::new(1.0, 0.0));
            let aim_pt = predict_target(
                enemy.pos,
                proj_speed,
                enemy,
                perception,
                skill,
                ctx.dt,
                ctx.room_radius,
                ctx.map_type,
                ctx.rng,
                0.9,
            );
            let next_aim = safe_dir(aim_pt - enemy.pos, dir_to);
            enemy.ai.sniper_aim = enemy.pos + next_aim * telegraph_range;
            enemy.ai.sub_state = EnemySubState::RangedWindup;
            enemy.ai.sub_timer = 0.20;
            refresh_windup_telegraph(
                ctx.lasers,
                ctx.next_id,
                &mut enemy.ai.telegraph_beam_id,
                enemy.pos,
                enemy.ai.sniper_aim,
                0.20,
            );
        } else {
            enemy.attack_cd =
                (1.45 + ctx.rng.range_f32(0.2, 0.55)) / sustained_cd_scale(enemy);
            enemy.ai.relocate_t = 0.5 + ctx.rng.range_f32(0.0, 0.6);
            let dir_to = safe_dir(perception.player_pos - enemy.pos, Vec2::new(1.0, 0.0));
            let perp_dot = perception.intent_vel.dot(perp(dir_to));
            if perp_dot.abs() > 12.0 {
                enemy.ai.strafe_sign = Some(if perp_dot > 0.0 { 1.0 } else { -1.0 });
            } else if let Some(sign) = enemy.ai.strafe_sign {
                enemy.ai.strafe_sign = Some(-sign);
            }
            enemy.ai.sub_state = EnemySubState::None;
        }
        return MoveIntent::hold();
    }

    let det_s = det_sign(enemy, false);
    let strafe_sign = *enemy.ai.strafe_sign.get_or_insert(det_s);
    let dvec = perception.player_pos - enemy.pos;
    let d = dvec.length();
    let dir_to = safe_dir(dvec, Vec2::new(1.0, 0.0));
    let strafe = perp(dir_to) * strafe_sign;
    let dodge = dodge_player_projectiles(
        enemy,
        ctx.projectiles,
        90.0,
        4,
        true,
        ctx.dt,
        skill,
        ctx.room_radius,
        ctx.map_type,
        ctx.rng,
    );
    let sep = separation_inv_sq(enemy.pos, enemy.id, ctx.enemy_snaps, 44.0, 1.1);
    enemy.ai.relocate_t = (enemy.ai.relocate_t - ctx.dt).max(0.0);

    let dodging = dodge.length_squared() > 1e-6;
    let (mv, speed_mult) = if dodging {
        let radial = if d > 220.0 {
            dir_to * 0.45
        } else if d < 140.0 {
            -dir_to * 0.45
        } else {
            Vec2::ZERO
        };
        ((radial + sep * 0.55 + dodge * 1.4).normalized(), 0.95)
    } else if d > 220.0 {
        ((dir_to * 0.95 + sep * 0.8).normalized(), 0.95)
    } else if d < 140.0 {
        (((-dir_to) * 0.95 + sep).normalized(), 0.95)
    } else {
        let lateral = strafe * if enemy.ai.relocate_t > 0.0 { 1.0 } else { 0.72 };
        ((lateral + dir_to * 0.1 + sep * 0.9).normalized(), 0.75)
    };
    let move_dir = steer_clear_of_obstacles(enemy, mv, ctx.obstacles);

    enemy.attack_cd -= ctx.dt;
    enemy.ai.burst_gap = (enemy.ai.burst_gap - ctx.dt).max(0.0);

    if d < 330.0 && enemy.attack_cd <= 0.0 && can_propose_attack(skill, perception) {
        director.propose(make_proposal(enemy_idx, enemy, 1, 330.0, d, perception));
    }

    if dodge.length_squared() > 1e-6 {
        MoveIntent::evade(move_dir, speed_mult)
    } else {
        MoveIntent::role(move_dir, speed_mult, None)
    }
}

fn update_spitter(
    enemy_idx: usize,
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    perception: &Perception,
    skill: &AiSkill,
    director: &mut AttackDirector,
) -> MoveIntent {
    let telegraph_range = if enemy.ai.volley_mode == 0 { 525.0 } else { 487.5 };

    if enemy.ai.sub_state == EnemySubState::SpitterWindup {
        enemy.ai.sub_timer = (enemy.ai.sub_timer - ctx.dt).max(0.0);
        let aim = safe_dir(enemy.ai.sniper_aim - enemy.pos, Vec2::new(1.0, 0.0));
        refresh_windup_telegraph(
            ctx.lasers,
            ctx.next_id,
            &mut enemy.ai.telegraph_beam_id,
            enemy.pos,
            enemy.pos + aim * telegraph_range,
            enemy.ai.sub_timer,
        );
        if enemy.ai.sub_timer > 0.0 {
            return MoveIntent::hold();
        }

        remove_telegraph(ctx.lasers, enemy.ai.telegraph_beam_id);
        enemy.ai.telegraph_beam_id = None;
        let cd_scale = sustained_cd_scale(enemy);
        let (angles, speed, damage): (&[f32], f32, i32) = if enemy.ai.volley_mode == 0 {
            enemy.attack_cd = (1.4 + ctx.rng.range_f32(0.0, 0.3)) / cd_scale;
            (&[-22.0, 0.0, 22.0], 210.0, (6 + ctx.wave / 4).min(14))
        } else {
            enemy.attack_cd = (1.75 + ctx.rng.range_f32(0.0, 0.35)) / cd_scale;
            if let Some(sign) = enemy.ai.strafe_sign {
                enemy.ai.strafe_sign = Some(-sign);
            }
            (&[-40.0, -14.0, 14.0, 40.0], 195.0, (5 + ctx.wave / 4).min(12))
        };
        for &angle in angles {
            let shot_dir = aim.rotated_deg(angle);
            ctx.projectiles.push(
                Projectile::new(
                    enemy.pos,
                    shot_dir * speed,
                    damage,
                    2.5,
                    "enemy",
                    "spread",
                )
                .with_source("spitter"),
            );
        }
        enemy.ai.volley_mode = 1 - enemy.ai.volley_mode;
        enemy.ai.sub_state = EnemySubState::None;
        return MoveIntent::hold();
    }

    let det_s = det_sign(enemy, false);
    let sign = *enemy.ai.strafe_sign.get_or_insert(det_s);
    let dvec = perception.player_pos - enemy.pos;
    let d = dvec.length();
    let dir_to = safe_dir(dvec, Vec2::new(1.0, 0.0));
    let sep = separation_inv_sq(enemy.pos, enemy.id, ctx.enemy_snaps, 44.0, 1.1);
    let dodge = dodge_player_projectiles(
        enemy,
        ctx.projectiles,
        95.0,
        4,
        true,
        ctx.dt,
        skill,
        ctx.room_radius,
        ctx.map_type,
        ctx.rng,
    );

    let dodging = dodge.length_squared() > 1e-6;
    let (mv, speed_mult) = if dodging {
        let radial = if d > 200.0 {
            dir_to * 0.4
        } else if d < 120.0 {
            -dir_to * 0.4
        } else {
            Vec2::ZERO
        };
        ((radial + sep * 0.55 + dodge * 1.4).normalized(), 0.95)
    } else if d > 200.0 {
        ((dir_to * 0.75 + sep * 0.8).normalized(), 0.8)
    } else if d < 120.0 {
        (((-dir_to) * 0.75 + sep).normalized(), 0.95)
    } else {
        let strafe = perp(dir_to) * sign;
        ((strafe * 0.9 + sep * 0.8 + dir_to * 0.1).normalized(), 0.95)
    };
    let move_dir = steer_clear_of_obstacles(enemy, mv, ctx.obstacles);

    enemy.attack_cd -= ctx.dt;
    if enemy.attack_cd <= 0.0 && d < 320.0 && can_propose_attack(skill, perception) {
        director.propose(make_proposal(enemy_idx, enemy, 2, 320.0, d, perception));
    }

    if dodge.length_squared() > 1e-6 {
        MoveIntent::evade(move_dir, speed_mult)
    } else {
        MoveIntent::role(move_dir, speed_mult, None)
    }
}

fn update_swarm(
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    perception: &Perception,
    skill: &AiSkill,
) -> MoveIntent {
    const PERCEPTION_R2: f32 = 95.0 * 95.0;
    const SEP_W: f32 = 1.7;
    const ALIGN_W: f32 = 0.9;
    const COH_W: f32 = 0.9;

    let (group, lane) = swarm_formation_key(enemy);
    let mut group_counts = [0usize; 3];
    let mut group_centers = [Vec2::ZERO; 3];
    for &(_, pos, _, snapshot_group) in ctx.swarm_snaps {
        if snapshot_group < 3 {
            group_counts[snapshot_group] += 1;
            group_centers[snapshot_group] += pos;
        }
    }
    let ally_count = group_counts.iter().sum::<usize>();
    if ally_count == 0 {
        return MoveIntent::hold();
    }
    for group_idx in 0..3 {
        if group_counts[group_idx] > 0 {
            group_centers[group_idx] /= group_counts[group_idx] as f32;
        }
    }

    let brain = ctx
        .swarm_brain
        .get_or_insert_with(|| SwarmBrain::new(ctx.enemy_time, ctx.rng));

    // Each stable subgroup advances on the enemy clock, but at a different
    // phase so the whole swarm never commits to the same move at once.
    let tick_advanced = ctx.enemy_time > brain.last_t;
    let bdt = if tick_advanced { ctx.dt.max(0.0) } else { 0.0 };
    brain.last_t = ctx.enemy_time;
    if bdt > 0.0 {
        for group_idx in 0..3 {
            brain.subgroup_timers[group_idx] -= bdt;
            if brain.subgroup_timers[group_idx] <= 0.0 {
                brain.subgroup_modes[group_idx] = match brain.subgroup_modes[group_idx] {
                    SwarmMode::Encircle => {
                        brain.subgroup_timers[group_idx] = SWARM_SURGE_TELEGRAPH_SECONDS;
                        SwarmMode::SurgeTelegraph
                    }
                    SwarmMode::SurgeTelegraph => {
                        brain.subgroup_timers[group_idx] = 1.05 + ctx.rng.range_f32(0.0, 0.35);
                        SwarmMode::Surge
                    }
                    SwarmMode::Surge => {
                        brain.subgroup_timers[group_idx] = 1.15 + ctx.rng.range_f32(0.0, 0.45);
                        brain.subgroup_flank_signs[group_idx] *= -1.0;
                        SwarmMode::Regroup
                    }
                    SwarmMode::Regroup => {
                        brain.subgroup_timers[group_idx] = 1.8 + ctx.rng.range_f32(0.0, 0.7);
                        SwarmMode::Encircle
                    }
                };
            }
            let orbit_speed = match brain.subgroup_modes[group_idx] {
                SwarmMode::Encircle => 0.62,
                SwarmMode::SurgeTelegraph => 0.38,
                SwarmMode::Surge => 0.22,
                SwarmMode::Regroup => 0.35,
            };
            brain.subgroup_orbit_phases[group_idx] =
                (brain.subgroup_orbit_phases[group_idx] + bdt * orbit_speed).rem_euclid(TAU);
        }
        brain.orbit_phase = brain.subgroup_orbit_phases[0];
    }

    brain.mode = brain.subgroup_modes[0].as_str().to_string();
    brain.mode_t = brain.subgroup_timers[0];
    brain.flank_sign = brain.subgroup_flank_signs[0];

    let group_count = group_counts[group].max(1);
    let group_center = if group_counts[group] > 0 {
        group_centers[group]
    } else {
        enemy.pos
    };
    let center_to_player = perception.player_pos - group_center;
    let dir_to_group = safe_dir(center_to_player, Vec2::new(1.0, 0.0));
    let mode = brain.subgroup_modes[group];
    let flank = perp(dir_to_group) * brain.subgroup_flank_signs[group];
    let lead_t = match mode {
        SwarmMode::Encircle => 0.16,
        SwarmMode::SurgeTelegraph => 0.16,
        SwarmMode::Surge => 0.08,
        SwarmMode::Regroup => 0.12,
    };
    let predicted = perception.player_pos + perception.smoothed_vel * lead_t;
    let focus = match mode {
        SwarmMode::Encircle => predicted + flank * (22.0 + group_count as f32 * 1.2),
        SwarmMode::SurgeTelegraph => predicted + flank * (22.0 + group_count as f32 * 1.2),
        SwarmMode::Surge => predicted,
        SwarmMode::Regroup => {
            predicted - dir_to_group * (16.0 + group_count as f32 * 2.0).min(45.0)
        }
    };
    let base_r = (150.0 - group_count as f32 * 3.4).clamp(82.0, 132.0);
    let ring_r = match mode {
        SwarmMode::SurgeTelegraph => base_r,
        SwarmMode::Surge => 14.0,
        SwarmMode::Regroup => base_r * 1.18,
        SwarmMode::Encircle => base_r,
    };
    if group == 0 {
        brain.focus = focus;
        brain.ring_r = ring_r;
    }

    let mut sep_acc = Vec2::ZERO;
    let mut sep_n = 0usize;
    let mut align_acc = Vec2::ZERO;
    let mut align_n = 0usize;
    let mut coh_acc = Vec2::ZERO;
    let mut coh_n = 0usize;
    const OTHER_GROUP_SEP_R2: f32 = 52.0 * 52.0;
    for &(oid, opos, ovel, other_group) in ctx.swarm_snaps {
        if oid == enemy.id {
            continue;
        }
        let dvec = enemy.pos - opos;
        let d2 = dvec.length_squared();
        if other_group == group {
            if d2 >= PERCEPTION_R2 {
                continue;
            }
            let d = d2.sqrt();
            if d > 1e-6 {
                sep_acc += (dvec / d) / d.max(0.2);
                sep_n += 1;
            }
            if ovel.length_squared() > 1e-6 {
                align_acc += ovel.normalized();
                align_n += 1;
            }
            coh_acc += opos;
            coh_n += 1;
        } else if d2 < OTHER_GROUP_SEP_R2 {
            let d = d2.sqrt();
            if d > 1e-6 {
                sep_acc += ((dvec / d) / d.max(0.2)) * 0.75;
                sep_n += 1;
            }
        }
    }

    let sep = if sep_n > 0 {
        sep_acc / sep_n as f32
    } else {
        Vec2::ZERO
    };
    let align = if align_n > 0 {
        let avg = align_acc / align_n as f32;
        if avg.length_squared() > 1e-6 {
            (avg - enemy.vel.normalized()).normalized()
        } else {
            Vec2::ZERO
        }
    } else {
        Vec2::ZERO
    };
    let coh = if coh_n > 0 {
        ((coh_acc / coh_n as f32) - enemy.pos).normalized()
    } else {
        Vec2::ZERO
    };
    let dodge = dodge_player_projectiles(
        enemy,
        ctx.projectiles,
        90.0,
        4,
        true,
        ctx.dt,
        skill,
        ctx.room_radius,
        ctx.map_type,
        ctx.rng,
    );

    let dvec = perception.player_pos - enemy.pos;
    let to_player = safe_dir(dvec, Vec2::new(1.0, 0.0));
    let slot_ang = brain.subgroup_orbit_phases[group] + (lane % 8) as f32 * (TAU / 8.0);
    let slot_r = if mode == SwarmMode::Surge {
        14.0 + (lane / 8) as f32 * 14.0
    } else {
        ring_r + (lane / 8) as f32 * 22.0
    };
    let slot_target = focus + Vec2::new(slot_ang.cos(), slot_ang.sin()) * slot_r;

    let to_slot = (slot_target - enemy.pos).normalized();
    let to_focus = (focus - enemy.pos).normalized();

    let (move_dir, speed_mult) = match mode {
        SwarmMode::SurgeTelegraph => (
            (to_slot * 1.1
                + flank * 0.35
                + to_player * 0.30
                + sep * SEP_W
                + align * (ALIGN_W * 0.8)
                + coh * (COH_W * 0.45)
                + dodge * 0.9)
                .normalized(),
            0.82,
        ),
        SwarmMode::Surge => (
            (to_slot * 0.35
                + to_focus * 1.25
                + to_player * 0.85
                + sep * SEP_W
                + align * (ALIGN_W * 0.7)
                + coh * (COH_W * 0.4)
                + dodge * 0.95
                + flank * 0.22)
                .normalized(),
            1.38,
        ),
        SwarmMode::Regroup => (
            (to_slot * 1.2
                + to_player * 0.4
                + coh * (COH_W * 0.55)
                + align * (ALIGN_W * 0.8)
                + sep * (SEP_W * 1.05)
                + dodge * 0.7)
                .normalized(),
            0.95,
        ),
        _ => (
            (to_slot * 1.1
                + flank * 0.35
                + to_player * 0.45
                + sep * SEP_W
                + align * (ALIGN_W * 0.8)
                + coh * (COH_W * 0.45)
                + dodge * 0.9)
                .normalized(),
            1.05,
        ),
    };

    let move_dir = steer_clear_of_obstacles(enemy, move_dir, ctx.obstacles);
    if dodge.length_squared() > 1e-6 {
        MoveIntent::evade(move_dir, speed_mult)
    } else {
        MoveIntent::role(move_dir, speed_mult, None)
    }
}

fn update_tank(
    enemy_idx: usize,
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    perception: &Perception,
    skill: &AiSkill,
    director: &mut AttackDirector,
) -> MoveIntent {
    if enemy.ai.sub_state == EnemySubState::TankWindup {
        enemy.ai.sub_timer = (enemy.ai.sub_timer - ctx.dt).max(0.0);
        refresh_windup_telegraph(
            ctx.lasers,
            ctx.next_id,
            &mut enemy.ai.telegraph_beam_id,
            enemy.pos,
            enemy.ai.sniper_aim,
            enemy.ai.sub_timer,
        );
        if enemy.ai.sub_timer > 0.0 {
            return MoveIntent::hold();
        }
        remove_telegraph(ctx.lasers, enemy.ai.telegraph_beam_id);
        enemy.ai.telegraph_beam_id = None;
        let aim = safe_dir(enemy.ai.sniper_aim - enemy.pos, Vec2::new(1.0, 0.0));
        let dmg = (12 + ctx.wave / 3).min(24);
        ctx.projectiles.push(
            Projectile::new(
                enemy.pos,
                aim * TANK_PROJ_SPEED,
                dmg,
                TANK_PROJ_TTL,
                "enemy",
                "bullet",
            )
            .with_source("tank"),
        );
        enemy.attack_cd = (1.9 + ctx.rng.range_f32(0.0, 0.3)) / sustained_cd_scale(enemy);
        enemy.ai.sub_state = EnemySubState::None;
        return MoveIntent::hold();
    }
    if enemy.ai.brace_t.is_none() {
        enemy.ai.brace_t = Some(ctx.rng.range_f32(0.0, 0.9));
    }

    let dvec = perception.player_pos - enemy.pos;
    let d = dvec.length();
    let dir_to = safe_dir(dvec, Vec2::new(1.0, 0.0));
    let sep = separation_inv_sq(enemy.pos, enemy.id, ctx.enemy_snaps, 44.0, 1.1);
    let dodge = dodge_player_projectiles(
        enemy,
        ctx.projectiles,
        75.0,
        2,
        false,
        ctx.dt,
        skill,
        ctx.room_radius,
        ctx.map_type,
        ctx.rng,
    );

    let mut brace_t = (enemy.ai.brace_t.unwrap_or(0.0) - ctx.dt).max(0.0);
    enemy.ai.push_t = (enemy.ai.push_t - ctx.dt).max(0.0);
    if brace_t <= 0.0 && d < 220.0 {
        enemy.ai.push_t = 0.65;
        enemy.attack_cd = (enemy.attack_cd - 0.35).max(0.0);
        brace_t = 2.0 + ctx.rng.range_f32(0.0, 0.7);
    }
    enemy.ai.brace_t = Some(brace_t);

    let intent = if d > 100.0 {
        let (mv, speed_mult) = if enemy.ai.push_t > 0.0 {
            ((dir_to * 1.15 + sep * 0.4 + dodge * 0.35).normalized(), 0.95)
        } else {
            ((dir_to * 0.7 + sep * 0.6 + dodge * 0.55).normalized(), 0.65)
        };
        let move_dir = steer_clear_of_obstacles(enemy, mv, ctx.obstacles);
        if dodge.length_squared() > 1e-6 {
            MoveIntent::evade(move_dir, speed_mult)
        } else {
            MoveIntent::role(move_dir, speed_mult, None)
        }
    } else {
        MoveIntent::hold()
    };

    enemy.attack_cd -= ctx.dt;
    if enemy.attack_cd <= 0.0 && d < 150.0 && can_propose_attack(skill, perception) {
        director.propose(make_proposal(enemy_idx, enemy, 1, 150.0, d, perception));
    }

    intent
}

fn update_egg_sac(enemy: &mut Enemy, ctx: &mut BehaviorContext<'_>) {
    enemy.ai.hatch_timer -= ctx.dt;
    if enemy.ai.hatch_timer <= 0.0 {
        enemy.hp = -1;
        let queued_non_boss = ctx
            .queued_spawns
            .iter()
            .filter(|spawn| !spawn.is_boss())
            .count();
        let hatch_count = 3.min(
            ctx.non_boss_spawn_cap
                .saturating_sub(ctx.live_non_boss_count.saturating_add(queued_non_boss)),
        );
        let child_radius = crate::sim::config::enemy_radius("swarm");
        let mut placements = Vec::with_capacity(hatch_count);
        for child_idx in 0..hatch_count {
            let base_angle = enemy.seed + child_idx as f32 * TAU / 3.0;
            let mut chosen = None;
            for attempt in 0..16 {
                let ring = enemy.radius + child_radius + 16.0 + (attempt / 4) as f32 * 22.0;
                let angle = base_angle + (attempt as f32) * (TAU / 12.0);
                let raw = enemy.pos + Vec2::new(angle.cos(), angle.sin()) * ring;
                let candidate = clamp_entity_to_map(
                    raw,
                    ctx.room_radius,
                    child_radius + 6.0,
                    ctx.map_type,
                );
                let overlaps_live = ctx.spawn_snaps.iter().any(|&(other_id, other_pos, other_radius)| {
                    other_id != enemy.id
                        && (candidate - other_pos).length_squared()
                            < (child_radius + other_radius + 6.0).powi(2)
                });
                let overlaps_queued = ctx.queued_spawns.iter().any(|other| {
                    (candidate - other.pos).length_squared()
                        < (child_radius + other.radius + 6.0).powi(2)
                });
                let overlaps_hatch = placements.iter().any(|pos: &Vec2| {
                    (candidate - *pos).length_squared() < (child_radius * 2.0 + 6.0).powi(2)
                });
                if !overlaps_live && !overlaps_queued && !overlaps_hatch {
                    chosen = Some(candidate);
                    break;
                }
            }
            let fallback_angle = base_angle + child_idx as f32 * 0.37;
            let fallback = enemy.pos
                + Vec2::new(fallback_angle.cos(), fallback_angle.sin())
                    * (enemy.radius + child_radius + 16.0);
            placements.push(chosen.unwrap_or_else(|| {
                clamp_entity_to_map(
                    fallback,
                    ctx.room_radius,
                    child_radius + 6.0,
                    ctx.map_type,
                )
            }));
        }
        for pos in placements {
            let eid = *ctx.next_id;
            *ctx.next_id += 1;
            ctx.queued_spawns
                .push(Enemy::new(eid, pos, 12 + ctx.wave, 110.0, "swarm"));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sim::ai_skill::ai_skill;
    use crate::sim::perception::WorldRect;

    #[test]
    fn predict_target_solves_quadratic_intercept_for_moving_target() {
        let mut enemy = Enemy::new(1, Vec2::ZERO, 50, 80.0, "ranged");
        let perception = Perception {
            player_pos: Vec2::new(200.0, 0.0),
            smoothed_vel: Vec2::new(0.0, 100.0),
            intent_vel: Vec2::new(0.0, 100.0),
            aim_dir: Vec2::new(1.0, 0.0),
            is_dashing: false,
            invulnerable_left: 0.0,
            boosting: false,
            hull_frac: 1.0,
            ultra_ready: false,
            on_screen_rect: WorldRect {
                min: Vec2::new(-800.0, -800.0),
                max: Vec2::new(800.0, 800.0),
            },
            breathing_room_left: 0.0,
        };
        let mut skill = ai_skill("hard", 20);
        skill.lead_quality = 1.0;
        skill.aim_jitter_deg = 0.0;
        let mut rng = SimRng::new(1);

        let pred = predict_target(
            Vec2::ZERO,
            200.0,
            &mut enemy,
            &perception,
            &skill,
            1.0 / 60.0,
            760.0,
            "circle",
            &mut rng,
            0.0,
        );
        // Moving perpendicular (+y at 100), intercept must lead +y accurately.
        assert!(pred.y > 90.0 && pred.y < 140.0);
        assert!((pred.x - 200.0).abs() < 1.0);
    }
}
