use std::f32::consts::PI;

use crate::sim::ai_skill::AiSkill;
use crate::sim::config::{
    DONUT_INNER_RATIO, MAP_DONUT, PLAYER_SPEED, ROOM_RADIUS_DEFAULT,
};
use crate::sim::enemy::{assign_run_keys, unit_order_bias, Enemy, EnemyRole, EnemySubState};
use crate::sim::math::{
    arena_edge_normal, arena_inside, clamp_entity_to_map, perp, Vec2,
};
use crate::sim::perception::Perception;

/// Persistent Formation v2 state stored on `SimState` and hashed in replays.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FormationState {
    pub axis: Vec2,
    pub anchor: Vec2,
}

impl FormationState {
    pub fn new(anchor: Vec2) -> Self {
        Self {
            axis: Vec2::new(1.0, 0.0),
            anchor,
        }
    }
}

impl Default for FormationState {
    fn default() -> Self {
        Self::new(Vec2::ZERO)
    }
}

#[derive(Debug, Clone, Copy)]
pub struct FormationProfile {
    pub lead_time: f32,
    pub front_arc_deg: f32,
    pub back_arc_deg: f32,
    pub steer_mult: f32,
    pub pressure_mult: f32,
    pub flank_offset_deg: f32,
}

pub fn formation_profile(difficulty: &str) -> FormationProfile {
    match difficulty.to_ascii_lowercase().as_str() {
        "easy" => FormationProfile {
            lead_time: 0.09,
            front_arc_deg: 104.0,
            back_arc_deg: 120.0,
            steer_mult: 0.78,
            pressure_mult: 0.86,
            flank_offset_deg: 80.0,
        },
        "hard" => FormationProfile {
            lead_time: 0.18,
            front_arc_deg: 84.0,
            back_arc_deg: 98.0,
            steer_mult: 1.08,
            pressure_mult: 1.16,
            flank_offset_deg: 80.0,
        },
        _ => FormationProfile {
            lead_time: 0.13,
            front_arc_deg: 94.0,
            back_arc_deg: 108.0,
            steer_mult: 0.95,
            pressure_mult: 1.0,
            flank_offset_deg: 80.0,
        },
    }
}

pub fn role_for_behavior(key: &str) -> &'static str {
    match key {
        "tank" => "wall",
        "charger" | "chaser" => "strike",
        "flyer" => "flank",
        "bomber" => "mid",
        "ranged" | "spitter" | "sniper" => "back",
        "engineer" => "support",
        "swarm" => "swarm",
        _ => "strike",
    }
}

pub fn slot_radius(key: &str) -> f32 {
    match key {
        "tank" => 105.0,
        "charger" | "chaser" => 130.0,
        "flyer" => 140.0,
        "bomber" => 160.0,
        "spitter" => 175.0,
        "ranged" => 190.0,
        "engineer" => 215.0,
        "sniper" => 260.0,
        _ => 130.0,
    }
}

#[inline]
pub fn safe_dir(v: Vec2, fallback: Vec2) -> Vec2 {
    let n = v.normalized();
    if n.length_squared() > 1e-9 {
        return n;
    }
    let fb = fallback.normalized();
    if fb.length_squared() > 1e-9 {
        return fb;
    }
    Vec2::new(1.0, 0.0)
}

#[inline]
fn wrap_pi(mut a: f32) -> f32 {
    while a > PI {
        a -= 2.0 * PI;
    }
    while a < -PI {
        a += 2.0 * PI;
    }
    a
}

pub fn holding_telegraph(enemy: &Enemy) -> bool {
    match enemy.role {
        EnemyRole::Charger => matches!(
            enemy.ai.sub_state,
            EnemySubState::ChargerWindup
                | EnemySubState::ChargerCharging
                | EnemySubState::ChargerCooldown
        ),
        EnemyRole::Flyer => matches!(
            enemy.ai.sub_state,
            EnemySubState::FlyerWindup | EnemySubState::FlyerDashing
        ),
        EnemyRole::Sniper => matches!(
            enemy.ai.sub_state,
            EnemySubState::SniperWindup | EnemySubState::SniperRecover
        ),
        EnemyRole::Ranged => enemy.ai.sub_state == EnemySubState::RangedWindup,
        EnemyRole::Spitter => enemy.ai.sub_state == EnemySubState::SpitterWindup,
        EnemyRole::Engineer => enemy.ai.sub_state == EnemySubState::EngineerWindup,
        EnemyRole::Bomber => enemy.ai.sub_state == EnemySubState::BomberWindup,
        EnemyRole::Tank => enemy.ai.sub_state == EnemySubState::TankWindup,
        EnemyRole::Chaser => enemy.ai.lunge_windup > 0.0 || enemy.ai.lunge_t > 0.0,
        _ => false,
    }
}

pub fn is_coordinated_role(role: EnemyRole) -> bool {
    matches!(
        role,
        EnemyRole::Chaser
            | EnemyRole::Ranged
            | EnemyRole::Sniper
            | EnemyRole::Bomber
            | EnemyRole::Tank
            | EnemyRole::Charger
            | EnemyRole::Spitter
            | EnemyRole::Flyer
            | EnemyRole::Engineer
    )
}

pub fn is_coordinated_behavior(key: &str) -> bool {
    EnemyRole::from_key(key).is_some_and(|r| is_coordinated_role(r) || r == EnemyRole::Swarm)
}

#[inline]
fn donut_segment_clears_pit(from: Vec2, to: Vec2, room_radius: f32, pad: f32) -> bool {
    let pit_r = room_radius * DONUT_INNER_RATIO + pad * 0.5;
    let seg = to - from;
    let seg_len2 = seg.length_squared();
    if seg_len2 <= 1e-6 {
        return to.length_squared() >= pit_r * pit_r;
    }
    let t = ((-from).dot(seg) / seg_len2).clamp(0.0, 1.0);
    let closest = from + seg * t;
    closest.length_squared() >= pit_r * pit_r
}

fn slot_candidate_valid(
    enemy_pos: Vec2,
    cand: Vec2,
    room_radius: f32,
    pad: f32,
    map_type: &str,
) -> bool {
    if !arena_inside(cand, room_radius, map_type) {
        return false;
    }
    let clamped = clamp_entity_to_map(cand, room_radius, pad, map_type);
    if (clamped - cand).length_squared() > 1.5 {
        return false;
    }
    if map_type == MAP_DONUT && !donut_segment_clears_pit(enemy_pos, cand, room_radius, pad) {
        return false;
    }
    true
}

#[allow(clippy::too_many_arguments)]
fn resolve_arena_slot(
    enemy_pos: Vec2,
    anchor: Vec2,
    slot_ang: f32,
    radius: f32,
    pad: f32,
    room_radius: f32,
    map_type: &str,
    spawn_index: i64,
) -> Vec2 {
    let slide_step = 6.0_f32.to_radians();
    // Try 6-degree angle sliding up to +-60 degrees on the target ring.
    for step in 0..=10 {
        let signs: &[f32] = if step == 0 { &[0.0] } else { &[1.0, -1.0] };
        for &sign in signs {
            let ang = slot_ang + sign * (step as f32) * slide_step;
            let cand = anchor + Vec2::new(ang.cos(), ang.sin()) * radius;
            if slot_candidate_valid(enemy_pos, cand, room_radius, pad, map_type) {
                return cand;
            }
        }
    }

    // Inward ring fallback when outer arcs hit an arena wall or corner.
    for r_scale in [0.75_f32, 0.55] {
        let r = radius * r_scale;
        for step in 0..=5 {
            let signs: &[f32] = if step == 0 { &[0.0] } else { &[1.0, -1.0] };
            for &sign in signs {
                let ang = slot_ang + sign * (step as f32) * slide_step;
                let cand = anchor + Vec2::new(ang.cos(), ang.sin()) * r;
                if slot_candidate_valid(enemy_pos, cand, room_radius, pad, map_type) {
                    return cand;
                }
            }
        }
    }

    let raw = anchor + Vec2::new(slot_ang.cos(), slot_ang.sin()) * radius;
    let clamped = clamp_entity_to_map(raw, room_radius, pad, map_type);
    if (clamped - raw).length_squared() > 4.0 {
        let edge_n = arena_edge_normal(clamped, room_radius, map_type);
        let tangent = perp(edge_n);
        let stagger = ((spawn_index.rem_euclid(3) - 1) as f32) * 14.0;
        return clamp_entity_to_map(clamped + tangent * stagger, room_radius, pad, map_type);
    }
    clamped
}

/// Compute Formation v2 targets aligned by `enemies` index without mutating enemy velocities.
/// Swarmers, egg sacs, and bosses receive `None` so their dedicated controllers stay intact.
#[allow(clippy::too_many_arguments)]
pub fn compute_formation_targets(
    enemies: &mut [Enemy],
    enemy_spawn_count: &mut i64,
    formation: &mut FormationState,
    difficulty: &str,
    perception: &Perception,
    skill: &AiSkill,
    room_radius: f32,
    map_type: &str,
    enemy_dt: f32,
) -> Vec<Option<(Vec2, &'static str)>> {
    let mut out = vec![None; enemies.len()];
    if enemies.is_empty() {
        return out;
    }

    for e in enemies.iter_mut() {
        assign_run_keys(e, enemy_spawn_count);
    }

    let prof = formation_profile(difficulty);

    // F1 fix: weighted centroid of coordinated non-boss, non-swarm, non-egg_sac enemies,
    // and axis pointing FROM player TOWARD the crowd.
    let mut weighted_sum = Vec2::ZERO;
    let mut weight_total = 0.0_f32;
    for e in enemies.iter() {
        if e.is_dead || e.hp <= 0 || !is_coordinated_role(e.role) {
            continue;
        }
        let w = match e.role {
            EnemyRole::Tank => 1.4,
            EnemyRole::Chaser | EnemyRole::Charger => 1.2,
            _ => 1.0,
        };
        weighted_sum += e.pos * w;
        weight_total += w;
    }
    if weight_total <= 0.0 {
        return out;
    }

    let weighted_centroid = weighted_sum / weight_total;
    let target_axis = safe_dir(weighted_centroid - perception.player_pos, formation.axis);

    // Rate-limit formation axis rotation with 15-degree hysteresis.
    let cur_axis = safe_dir(formation.axis, target_axis);
    let dot = cur_axis.dot(target_axis).clamp(-1.0, 1.0);
    let cross = cur_axis.x * target_axis.y - cur_axis.y * target_axis.x;
    let ang_diff = cross.atan2(dot);
    if ang_diff.abs() > 15.0_f32.to_radians() {
        let max_turn = skill.axis_turn_deg_s.to_radians() * enemy_dt.max(0.0);
        if max_turn > 0.0 {
            let step = ang_diff.clamp(-max_turn, max_turn);
            formation.axis = cur_axis.rotated_rad(step).normalized();
        }
    } else {
        formation.axis = cur_axis;
    }

    // Rate-limit anchor movement toward player_pos + intent_vel * lead_time.
    let desired_anchor = clamp_entity_to_map(
        perception.player_pos + perception.intent_vel * prof.lead_time,
        room_radius,
        8.0,
        map_type,
    );
    let anchor_delta = desired_anchor - formation.anchor;
    let anchor_dist = anchor_delta.length();
    let max_anchor_step = 2.0 * PLAYER_SPEED * enemy_dt.max(0.0);
    if max_anchor_step > 0.0 && anchor_dist > max_anchor_step && anchor_dist > 1e-6 {
        formation.anchor += anchor_delta * (max_anchor_step / anchor_dist);
    } else if enemy_dt > 0.0 || formation.anchor == Vec2::ZERO {
        formation.anchor = desired_anchor;
    }

    let base_ang = formation.axis.y.atan2(formation.axis.x);
    let k = (room_radius / ROOM_RADIUS_DEFAULT).clamp(0.75, 1.25);

    // Partition coordinated enemies into ring groups.
    let mut g_wall: Vec<usize> = Vec::new();
    let mut g_strike: Vec<usize> = Vec::new();
    let mut g_flank_left: Vec<usize> = Vec::new();
    let mut g_flank_right: Vec<usize> = Vec::new();
    let mut g_mid: Vec<usize> = Vec::new();
    let mut g_spitter: Vec<usize> = Vec::new();
    let mut g_ranged: Vec<usize> = Vec::new();
    let mut g_sniper: Vec<usize> = Vec::new();
    let mut g_support: Vec<usize> = Vec::new();

    for (idx, e) in enemies.iter_mut().enumerate() {
        if e.is_dead || e.hp <= 0 || !is_coordinated_role(e.role) {
            continue;
        }
        match e.role {
            EnemyRole::Tank => g_wall.push(idx),
            EnemyRole::Chaser | EnemyRole::Charger => g_strike.push(idx),
            EnemyRole::Flyer => {
                if unit_order_bias(e) < 0.5 {
                    g_flank_left.push(idx);
                } else {
                    g_flank_right.push(idx);
                }
            }
            EnemyRole::Bomber => g_mid.push(idx),
            EnemyRole::Spitter => g_spitter.push(idx),
            EnemyRole::Ranged => g_ranged.push(idx),
            EnemyRole::Sniper => g_sniper.push(idx),
            EnemyRole::Engineer => g_support.push(idx),
            EnemyRole::Swarm | EnemyRole::EggSac | EnemyRole::Boss => {}
        }
    }

    let anchor = formation.anchor;
    let hysteresis = 10.0_f32.to_radians();

    let mut assign_group = |group: Vec<usize>,
                            role_tag: &'static str,
                            center_ang: f32,
                            base_arc_deg: f32,
                            ring_radius: f32,
                            compact_c: f32| {
        let n = group.len();
        if n == 0 {
            return;
        }

        // Angle-matched crossing-free ordering with 10-degree angular hysteresis.
        let mut keyed: Vec<(f32, i64, u64, usize)> = group
            .into_iter()
            .map(|idx| {
                let e = &enemies[idx];
                let delta = e.pos - anchor;
                let cur_rel = wrap_pi(delta.y.atan2(delta.x) - center_ang);
                let sort_ang = match e.ai.formation_slot_ang {
                    Some(prev) if (cur_rel - prev).abs() < hysteresis => prev,
                    _ => cur_rel,
                };
                (sort_ang, e.spawn_index, e.id, idx)
            })
            .collect();

        keyed.sort_by(|a, b| {
            a.0.total_cmp(&b.0)
                .then_with(|| a.1.cmp(&b.1))
                .then_with(|| a.2.cmp(&b.2))
        });

        let effective_arc = base_arc_deg.to_radians() * ((n as f32) / compact_c.max(1.0)).min(1.0);
        for (slot_i, (_, _, _, idx)) in keyed.into_iter().enumerate() {
            let frac = (slot_i as f32 + 0.5) / (n as f32) - 0.5;
            let rel_ang = frac * effective_arc;
            let slot_ang = center_ang + rel_ang;
            let e = &mut enemies[idx];
            e.ai.formation_slot_ang = Some(rel_ang);
            let target = resolve_arena_slot(
                e.pos,
                anchor,
                slot_ang,
                ring_radius,
                e.radius + 6.0,
                room_radius,
                map_type,
                e.spawn_index,
            );
            out[idx] = Some((target, role_tag));
        }
    };

    let flank_offset = prof.flank_offset_deg.to_radians();
    assign_group(g_wall, "wall", base_ang, 48.0, 105.0 * k, 3.0);
    assign_group(g_strike, "strike", base_ang, prof.front_arc_deg, 130.0 * k, 5.0);
    assign_group(g_flank_left, "flank", base_ang + flank_offset, 58.0, 140.0 * k, 3.0);
    assign_group(g_flank_right, "flank", base_ang - flank_offset, 58.0, 140.0 * k, 3.0);
    assign_group(g_mid, "mid", base_ang + 25.0_f32.to_radians(), 72.0, 160.0 * k, 3.0);
    assign_group(g_spitter, "back", base_ang, 92.0, 175.0 * k, 4.0);
    assign_group(g_ranged, "back", base_ang, prof.back_arc_deg, 190.0 * k, 4.0);
    assign_group(g_support, "support", base_ang - 25.0_f32.to_radians(), 68.0, 215.0 * k, 3.0);
    assign_group(g_sniper, "back", base_ang, 100.0, 260.0 * k, 3.0);

    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sim::ai_skill::ai_skill;
    use crate::sim::perception::WorldRect;

    fn test_perception(player_pos: Vec2) -> Perception {
        Perception {
            player_pos,
            smoothed_vel: Vec2::ZERO,
            intent_vel: Vec2::ZERO,
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
        }
    }

    #[test]
    fn formation_axis_points_from_player_toward_crowd_and_single_slot_is_centered() {
        let mut enemies = vec![Enemy::new(1, Vec2::new(300.0, 0.0), 50, 90.0, "ranged")];
        let mut spawn_count = 0;
        let mut form = FormationState::new(Vec2::ZERO);
        let p = test_perception(Vec2::ZERO);
        let skill = ai_skill("normal", 1);

        let targets = compute_formation_targets(
            &mut enemies,
            &mut spawn_count,
            &mut form,
            "normal",
            &p,
            &skill,
            760.0,
            "circle",
            1.0 / 60.0,
        );
        let (target, role) = targets[0].expect("ranged should get formation slot");
        assert_eq!(role, "back");
        assert!(form.axis.x > 0.9, "axis must point from player toward crowd");
        assert!((target.x - 190.0).abs() < 2.0 && target.y.abs() < 2.0);
    }

    #[test]
    fn dedicated_swarm_and_static_adds_do_not_tilt_regular_squad_formation() {
        let mut regular = vec![
            Enemy::new(1, Vec2::new(380.0, 40.0), 50, 90.0, "chaser"),
            Enemy::new(2, Vec2::new(410.0, -40.0), 50, 90.0, "ranged"),
            Enemy::new(3, Vec2::new(420.0, 0.0), 50, 90.0, "engineer"),
        ];
        let mut with_specials = regular.clone();
        for index in 0..6 {
            with_specials.push(Enemy::new(
                10 + index,
                Vec2::new(-300.0 + index as f32 * 12.0, 400.0),
                30,
                110.0,
                "swarm",
            ));
        }
        with_specials.push(Enemy::new(
            30,
            Vec2::new(-450.0, -350.0),
            500,
            0.0,
            "egg_sac",
        ));

        let mut base_count = 0;
        let mut expanded_count = 0;
        let mut form_a = FormationState::new(Vec2::ZERO);
        let mut form_b = FormationState::new(Vec2::ZERO);
        let p = test_perception(Vec2::ZERO);
        let skill = ai_skill("normal", 1);

        let regular_slots = compute_formation_targets(
            &mut regular,
            &mut base_count,
            &mut form_a,
            "normal",
            &p,
            &skill,
            760.0,
            "circle",
            1.0 / 60.0,
        );
        let expanded_slots = compute_formation_targets(
            &mut with_specials,
            &mut expanded_count,
            &mut form_b,
            "normal",
            &p,
            &skill,
            760.0,
            "circle",
            1.0 / 60.0,
        );

        for i in 0..3 {
            let base = regular_slots[i].unwrap().0;
            let expanded = expanded_slots[i].unwrap().0;
            assert!(
                (base - expanded).length() < 1e-4,
                "special unit changed squad {i}'s formation target: {base:?} -> {expanded:?}"
            );
        }
        for i in 3..with_specials.len() {
            assert!(expanded_slots[i].is_none(), "swarm and egg_sac must not receive regular formation slots");
        }
    }

    #[test]
    fn angle_matched_assignment_avoids_crossing_lines() {
        let mut enemies = vec![
            Enemy::new(1, Vec2::new(200.0, -100.0), 50, 90.0, "chaser"),
            Enemy::new(2, Vec2::new(200.0, 100.0), 50, 90.0, "chaser"),
        ];
        let mut spawn_count = 0;
        let mut form = FormationState::new(Vec2::ZERO);
        let p = test_perception(Vec2::ZERO);
        let skill = ai_skill("normal", 1);

        let targets = compute_formation_targets(
            &mut enemies,
            &mut spawn_count,
            &mut form,
            "normal",
            &p,
            &skill,
            760.0,
            "circle",
            1.0 / 60.0,
        );
        let t0 = targets[0].unwrap().0;
        let t1 = targets[1].unwrap().0;
        assert!(t0.y < t1.y, "slot assignment must preserve angular order to prevent crossing");
    }
}
