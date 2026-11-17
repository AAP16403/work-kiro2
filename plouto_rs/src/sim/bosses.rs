use std::f32::consts::{PI, TAU};

use crate::sim::behaviors::{
    append_trap_capped, cancel_attack_for_interrupt, lead_dir, steer_clear_of_obstacles,
    BehaviorContext,
};
use crate::sim::config::{
    BOSS_RAGE_COOLDOWN_MULT, BOSS_RAGE_EXTRA_PROJECTILES, BOSS_RAGE_HP_FRAC, DIAMOND_EXTENT_RATIO,
    MAX_ACTIVE_CONSTRUCTIONS, RAGE_BANNER_COLOR, RAGE_BANNER_TITLE,
};
use crate::sim::enemy::{
    boss_title, BossPersona, Enemy, EnemySubState, ABYSS_GAZE_TELEGRAPH,
    SWARMQUEEN_TELEGRAPH, TRAPMASTER_TELEGRAPH, WOMB_PULSE_TELEGRAPH,
};
use crate::sim::hazards::{LaserBeam, ThunderLine, Trap};
use crate::sim::level::{difficulty_mods, make_summoned_enemy};
use crate::sim::math::{clamp_entity_to_map, perp, Vec2};
use crate::sim::projectile::Projectile;
use crate::sim::steer::safe_dir;

pub const BRUTE_CHARGE_TIME: f32 = 1.2;
pub const BRUTE_FOLLOWUP_CHARGE_TIME: f32 = 0.66;
pub const BRUTE_FOLLOWUP_TELEGRAPH_TIME: f32 = 0.62;
pub const TRAPMASTER_SPIKE_RADIUS: f32 = 26.0;
const TRAPMASTER_SPIKE_PADDING: f32 = 32.0;
pub const ECLIPSE_GAP_HALF_WIDTH: f32 = 0.42;

/// Signed per-volley rotation (radians) applied to Eclipse Archon's safe opening in later phases.
pub fn eclipse_safe_step_rad(enemy: &Enemy) -> f32 {
    let step = match enemy.ai.phase {
        0 => 0.0,
        1 => 0.34,
        _ => 0.38,
    };
    if enemy.ai.persona == BossPersona::Cautious {
        -step
    } else {
        step
    }
}

/// World-space angle (radians) of Eclipse Archon's safe opening for the given burst volley index.
pub fn eclipse_safe_angle(enemy: &Enemy, volley: i32) -> f32 {
    let base_dir = safe_dir(enemy.ai.charge_dir, Vec2::new(1.0, 0.0));
    base_dir.y.atan2(base_dir.x) + volley as f32 * eclipse_safe_step_rad(enemy)
}

/// Arena-safe spike position shared by the Forge Warden simulation and its warning marks.
pub fn trapmaster_spike_position(
    center: Vec2,
    base_angle: f32,
    index: usize,
    count: usize,
    ring_radius: f32,
    room_radius: f32,
    map_type: &str,
) -> Vec2 {
    let count = count.max(1);
    let angle = base_angle + (index as f32 / count as f32) * TAU;
    let raw = center + Vec2::new(angle.cos(), angle.sin()) * ring_radius;
    clamp_entity_to_map(raw, room_radius, TRAPMASTER_SPIKE_PADDING, map_type)
}

#[derive(Debug, Clone)]
pub struct BossRageBanner {
    pub title: &'static str,
    pub subtitle: String,
    pub color: [u8; 3],
}

/// The single transition result consumed by banners and encounter state.
/// A phase change cancels an unlaunched action, preserves already released
/// hazards with their existing warning, and gives the boss a short reset.
#[derive(Debug, Clone)]
pub struct BossTransition {
    pub previous_phase: i32,
    pub phase: i32,
    pub phase_changed: bool,
    pub rage_banner: Option<BossRageBanner>,
}

pub const BOSS_PHASE_RECOVERY_SECONDS: f32 = 0.35;

pub fn is_raged(enemy: &Enemy) -> bool {
    enemy.ai.rage
}

pub fn update_boss_rage(enemy: &mut Enemy) -> Option<BossRageBanner> {
    if enemy.ai.rage {
        return None;
    }
    let max_hp = enemy.ai.boss_max_hp.max(enemy.hp).max(1);
    if (enemy.hp as f32) / (max_hp as f32) > BOSS_RAGE_HP_FRAC {
        return None;
    }
    enemy.ai.rage = true;
    if enemy.attack_cd > 0.0 {
        enemy.attack_cd *= BOSS_RAGE_COOLDOWN_MULT;
    }
    Some(BossRageBanner {
        title: RAGE_BANNER_TITLE,
        subtitle: format!("{}  -  ATTACKS QUICKEN", boss_title(&enemy.behavior)),
        color: RAGE_BANNER_COLOR,
    })
}

pub fn rage_cooldown(enemy: &Enemy, seconds: f32) -> f32 {
    if is_raged(enemy) {
        seconds * BOSS_RAGE_COOLDOWN_MULT
    } else {
        seconds
    }
}

pub fn rage_volley(enemy: &Enemy, count: i32) -> i32 {
    if is_raged(enemy) {
        count + BOSS_RAGE_EXTRA_PROJECTILES
    } else {
        count
    }
}

pub fn brute_charge_speed(speed: f32, phase: i32) -> f32 {
    let mut s = speed * 2.8;
    if phase >= 1 {
        s *= 1.08;
    }
    s
}

pub fn brute_charge_time(enemy: &Enemy) -> f32 {
    if enemy.ai.phase >= 2 {
        if enemy.ai.volley_mode == 2 {
            BRUTE_FOLLOWUP_CHARGE_TIME
        } else {
            BRUTE_CHARGE_TIME * 0.72
        }
    } else {
        BRUTE_CHARGE_TIME
    }
}

pub fn brute_charge_windup_time(enemy: &Enemy) -> f32 {
    if enemy.ai.phase >= 2 && enemy.ai.volley_mode == 2 {
        BRUTE_FOLLOWUP_TELEGRAPH_TIME
    } else {
        1.0
    }
}

/// Direction and drawn length of the brute's telegraphed charge, or None outside its telegraph.
pub fn brute_charge_lane(enemy: &Enemy, room_radius: f32, map_type: &str) -> Option<(Vec2, f32)> {
    if enemy.ai.sub_state != EnemySubState::BruteTelegraph {
        return None;
    }
    let dir = enemy.ai.charge_dir.normalized();
    if dir.length_squared() <= 1e-9 {
        return None;
    }
    let reach = brute_charge_speed(enemy.speed, enemy.ai.phase) * brute_charge_time(enemy);
    let wall_pad = enemy.radius + 6.0;
    let inside_playable = |pt: Vec2| {
        let clamped = clamp_entity_to_map(pt, room_radius, wall_pad, map_type);
        (clamped - pt).length_squared() <= 1e-3
    };
    let sample_count = (reach / 20.0).ceil().clamp(1.0, 128.0) as usize;
    let mut low = 0.0;
    let mut high = reach;
    let mut found_boundary = false;
    for sample in 1..=sample_count {
        let distance = reach * sample as f32 / sample_count as f32;
        if !inside_playable(enemy.pos + dir * distance) {
            high = distance;
            low = reach * (sample - 1) as f32 / sample_count as f32;
            found_boundary = true;
            break;
        }
    }
    if !found_boundary {
        return Some((dir, reach));
    }
    for _ in 0..20 {
        let middle = (low + high) * 0.5;
        if inside_playable(enemy.pos + dir * middle) {
            low = middle;
        } else {
            high = middle;
        }
    }
    Some((dir, low.max(0.0)))
}

fn append_trap_pair_capped(traps: &mut Vec<Trap>, first: Trap, second: Trap) -> bool {
    if traps.len().saturating_add(2) > MAX_ACTIVE_CONSTRUCTIONS {
        return false;
    }
    traps.push(first);
    traps.push(second);
    true
}

fn boss_init(enemy: &mut Enemy) {
    if enemy.ai.boss_initialized {
        return;
    }
    enemy.ai.boss_initialized = true;
    enemy.ai.boss_max_hp = enemy.hp.max(enemy.max_hp);
    let personas = [
        BossPersona::Aggressive,
        BossPersona::Cautious,
        BossPersona::Trickster,
    ];
    let idx = ((enemy.seed * 1000.0) as usize) % personas.len();
    enemy.ai.persona = personas[idx];
    enemy.ai.phase = 0;
    enemy.ai.gun_idx = 0;
}

fn boss_phase(enemy: &Enemy) -> i32 {
    let max_hp = enemy.ai.boss_max_hp.max(1);
    let r = enemy.hp as f32 / max_hp as f32;
    if r > 0.66 {
        0
    } else if r > 0.33 {
        1
    } else {
        2
    }
}

fn boss_damage(difficulty: &str, wave: i32, base: f32, wave_scale: f32, cap: i32) -> i32 {
    let mult = difficulty_mods(difficulty).hp;
    let dmg = (base + (wave as f32) * wave_scale) * mult;
    (dmg.round() as i32).clamp(1, cap)
}

fn boss_cd(difficulty: &str, base: f32, phase: i32, floor: f32, persona: BossPersona) -> f32 {
    let mut cd = base;
    if phase == 1 {
        cd *= 0.96;
    } else if phase >= 2 {
        cd *= 0.90;
    }
    match persona {
        BossPersona::Aggressive => cd *= 0.94,
        BossPersona::Cautious => cd *= 1.06,
        BossPersona::Trickster => {}
    }
    match difficulty.to_ascii_lowercase().as_str() {
        "easy" => cd *= 1.12,
        "hard" => cd *= 0.96,
        _ => {}
    }
    cd.max(floor)
}

fn boss_adds_cap(max_enemies: usize, bonus: usize) -> usize {
    (max_enemies + bonus).clamp(max_enemies + 1, max_enemies + 4)
}

fn cycle_gun<'a>(enemy: &mut Enemy, guns: &[&'a str]) -> &'a str {
    let g = guns[enemy.ai.gun_idx % guns.len()];
    enemy.ai.gun_idx += 1;
    g
}

#[allow(clippy::too_many_arguments)]
fn fire_fan(
    projectiles: &mut Vec<Projectile>,
    origin: Vec2,
    aim: Vec2,
    count: i32,
    spread_deg: f32,
    speed: f32,
    damage: i32,
    ttl: f32,
    ptype: &str,
    source: &str,
) {
    let n = count.max(1);
    if n == 1 {
        projectiles.push(
            Projectile::new(origin, aim * speed, damage, ttl, "enemy", ptype).with_source(source),
        );
        return;
    }
    let step = spread_deg / (n - 1) as f32;
    let start = -spread_deg * 0.5;
    for i in 0..n {
        let d = aim.rotated_deg(start + step * i as f32);
        projectiles.push(
            Projectile::new(origin, d * speed, damage, ttl, "enemy", ptype).with_source(source),
        );
    }
}

#[allow(clippy::too_many_arguments)]
fn fire_ring(
    projectiles: &mut Vec<Projectile>,
    origin: Vec2,
    count: i32,
    speed: f32,
    damage: i32,
    ttl: f32,
    start_deg: f32,
    ptype: &str,
    source: &str,
) {
    let n = count.max(3);
    let step = 360.0 / n as f32;
    for i in 0..n {
        let a = (start_deg + (i as f32) * step).to_radians();
        let d = Vec2::new(a.cos(), a.sin());
        projectiles.push(
            Projectile::new(origin, d * speed, damage, ttl, "enemy", ptype).with_source(source),
        );
    }
}

pub fn update_boss_enemy(
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    difficulty: &str,
    max_enemies: usize,
    total_live_enemies: usize,
    non_boss_count: usize,
    egg_sac_count: usize,
    thunders: &mut Vec<ThunderLine>,
) -> BossTransition {
    boss_init(enemy);
    let previous_phase = enemy.ai.phase;
    let new_phase = boss_phase(enemy);
    let phase_changed = previous_phase != new_phase;
    if phase_changed {
        enemy.ai.phase = new_phase;
        cancel_attack_for_interrupt(enemy, ctx.lasers, BOSS_PHASE_RECOVERY_SECONDS);
    }
    let rage_banner = update_boss_rage(enemy);
    let transition = BossTransition {
        previous_phase,
        phase: enemy.ai.phase,
        phase_changed,
        rage_banner,
    };

    if phase_changed {
        enemy.ai.boss_phase_recovery_left = BOSS_PHASE_RECOVERY_SECONDS;
        // Rage cooldown scaling must not shrink the phase reset window.
        enemy.attack_cd = enemy.attack_cd.max(BOSS_PHASE_RECOVERY_SECONDS);
        return transition;
    }
    if enemy.ai.boss_phase_recovery_left > 0.0 {
        enemy.ai.boss_phase_recovery_left =
            (enemy.ai.boss_phase_recovery_left - ctx.dt.max(0.0)).max(0.0);
        enemy.vel = Vec2::ZERO;
        if enemy.ai.boss_phase_recovery_left > 0.0 {
            return transition;
        }
    }

    match enemy.behavior.as_str() {
        "boss_thunder" => update_boss_thunder(enemy, ctx, difficulty, thunders),
        "boss_laser" => update_boss_laser(enemy, ctx, difficulty),
        "boss_trapmaster" => {
            update_boss_trapmaster(enemy, ctx, difficulty, max_enemies, total_live_enemies)
        }
        "boss_swarmqueen" => update_boss_swarmqueen(
            enemy,
            ctx,
            difficulty,
            max_enemies,
            non_boss_count,
            egg_sac_count,
        ),
        "boss_brute" => update_boss_brute(enemy, ctx, difficulty),
        "boss_abyss_gaze" => {
            update_boss_abyss_gaze(enemy, ctx, difficulty, max_enemies, total_live_enemies)
        }
        "boss_womb_core" => {
            update_boss_womb_core(enemy, ctx, difficulty, max_enemies, total_live_enemies)
        }
        "boss_eclipse_archon" => update_boss_eclipse_archon(enemy, ctx, difficulty),
        _ => {}
    }
    transition
}

fn update_boss_thunder(
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    difficulty: &str,
    thunders: &mut Vec<ThunderLine>,
) {
    let phase = enemy.ai.phase;
    let persona = enemy.ai.persona;

    if enemy.ai.sub_state == EnemySubState::None {
        enemy.ai.sub_state = EnemySubState::ThunderStalk;
        enemy.ai.sub_timer = 1.5;
    }
    enemy.ai.sub_timer = (enemy.ai.sub_timer - ctx.dt).max(0.0);
    let timer = enemy.ai.sub_timer;

    match enemy.ai.sub_state {
        EnemySubState::ThunderStalk => {
            let dir_to = safe_dir(ctx.player_pos - enemy.pos, Vec2::new(1.0, 0.0));
            let drift = dir_to.rotated_deg(if enemy.seed > 3.14 { 90.0 } else { -90.0 });
            let move_dir = steer_clear_of_obstacles(enemy, drift, ctx.obstacles);
            enemy.vel = move_dir * (enemy.speed * 0.4);
            enemy.pos += enemy.vel * ctx.dt;
            if timer <= 0.0 {
                enemy.vel = Vec2::ZERO;
                enemy.ai.sub_state = EnemySubState::ThunderTeleportOut;
                enemy.ai.sub_timer = 0.4;
            }
        }
        EnemySubState::ThunderTeleportOut => {
            enemy.vel = Vec2::ZERO;
            if timer <= 0.0 {
                let ang = ctx.rng.range_f32(0.0, TAU);
                let dist = ctx.rng.range_f32(220.0, (ctx.room_radius * 0.62).max(260.0));
                let raw_target = ctx.player_pos + Vec2::new(ang.cos(), ang.sin()) * dist;
                enemy.pos = clamp_entity_to_map(
                    raw_target,
                    ctx.room_radius,
                    enemy.radius + 6.0,
                    ctx.map_type,
                );
                enemy.prev_pos = enemy.pos;
                enemy.ai.sub_state = EnemySubState::ThunderTeleportIn;
                enemy.ai.sub_timer = 0.25;
            }
        }
        EnemySubState::ThunderTeleportIn => {
            enemy.vel = Vec2::ZERO;
            if timer <= 0.0 {
                let count = rage_volley(enemy, if phase == 0 { 8 } else { 10 });
                let angle = ctx.rng.range_f32(0.0, TAU);
                enemy.ai.charge_dir = Vec2::new(angle.cos(), angle.sin());
                enemy.ai.laser_tick = count as f32;
                enemy.ai.sub_state = EnemySubState::ThunderWindup;
                enemy.ai.sub_timer = 0.62;
            }
        }
        EnemySubState::ThunderWindup => {
            enemy.vel = Vec2::ZERO;
            if timer <= 0.0 {
                enemy.ai.sub_state = EnemySubState::ThunderAttack;
                enemy.ai.sub_timer = 0.0;
            }
        }
        EnemySubState::ThunderAttack => {
            enemy.vel = Vec2::ZERO;
            let atk_roll = ctx.rng.f32();
            let proj_speed = 210.0 + (ctx.wave as f32) * 2.0;
            let dmg = boss_damage(difficulty, ctx.wave, 5.0, 0.14, 16);
            let ring_count = enemy.ai.laser_tick.round().max(3.0) as i32;
            let start_angle = enemy.ai.charge_dir.y.atan2(enemy.ai.charge_dir.x).to_degrees();

            if atk_roll < 0.38 || (phase >= 1 && atk_roll < 0.7) {
                let line_count = if phase == 0 {
                    1
                } else if phase >= 2 && persona == BossPersona::Aggressive {
                    3
                } else {
                    2
                };
                let ang = ctx.rng.range_f32(0.0, TAU);
                let dirv = Vec2::new(ang.cos(), ang.sin());
                let pv = Vec2::new(-dirv.y, dirv.x);
                let lock_center = ctx.player_pos + ctx.player_vel * 0.28;
                for lane in 0..line_count {
                    let centered_lane = lane as f32 - (line_count - 1) as f32 * 0.5;
                    let anchor = lock_center + pv * (centered_lane * 116.0);
                    let span = ctx.room_radius * 2.2;
                    let th_dmg = boss_damage(difficulty, ctx.wave, 12.0, 0.22, 26);
                    thunders.push(ThunderLine::new(
                        anchor - dirv * span,
                        anchor + dirv * span,
                        th_dmg,
                        14.0,
                        0.16,
                        1.0,
                        [255, 235, 110],
                        "enemy",
                    ).with_source(&enemy.behavior));
                }
            }

            let gun = cycle_gun(enemy, &["plasma", "bullet"]).to_string();
            let src = enemy.behavior.clone();
            fire_ring(
                ctx.projectiles,
                enemy.pos,
                ring_count,
                proj_speed * 0.9,
                dmg,
                2.8,
                start_angle,
                &gun,
                &src,
            );
            if phase >= 2 {
                let second_count = (ring_count / 2).max(3);
                let interlace = 180.0 / ring_count as f32;
                fire_ring(
                    ctx.projectiles,
                    enemy.pos,
                    second_count,
                    proj_speed * 0.75,
                    dmg,
                    2.8,
                    start_angle + interlace,
                    &gun,
                    &src,
                );
            }

            enemy.ai.sub_state = EnemySubState::ThunderStalk;
            let mut cd_base = 2.5 - (ctx.wave as f32) * 0.035 - (phase as f32) * 0.2;
            if persona == BossPersona::Aggressive {
                cd_base *= 0.8;
            }
            enemy.ai.sub_timer = rage_cooldown(enemy, cd_base.max(1.1));
        }
        _ => {}
    }
}

fn update_boss_laser(enemy: &mut Enemy, ctx: &mut BehaviorContext<'_>, difficulty: &str) {
    let phase = enemy.ai.phase;
    let persona = enemy.ai.persona;

    if enemy.ai.sub_state == EnemySubState::None {
        enemy.ai.sub_state = EnemySubState::LaserReposition;
        enemy.ai.sub_timer = 0.0;
    }
    enemy.ai.sub_timer = (enemy.ai.sub_timer - ctx.dt).max(0.0);
    let timer = enemy.ai.sub_timer;

    match enemy.ai.sub_state {
        EnemySubState::LaserReposition => {
            enemy.vel = Vec2::ZERO;
            if timer <= 0.0 {
                let c_diag = ctx.room_radius * 0.56;
                let c_card = ctx.room_radius * 0.78;
                let anchors = [
                    Vec2::new(c_diag, c_diag),
                    Vec2::new(-c_diag, c_diag),
                    Vec2::new(c_diag, -c_diag),
                    Vec2::new(-c_diag, -c_diag),
                    Vec2::new(c_card, 0.0),
                    Vec2::new(-c_card, 0.0),
                    Vec2::new(0.0, c_card),
                    Vec2::new(0.0, -c_card),
                ];
                let idx = ctx.rng.index(anchors.len());
                enemy.ai.move_target =
                    clamp_entity_to_map(anchors[idx], ctx.room_radius, 28.0, ctx.map_type);
                enemy.ai.sub_state = EnemySubState::LaserMoving;
                enemy.ai.sub_timer = 3.0;
            }
        }
        EnemySubState::LaserMoving => {
            let dvec = enemy.ai.move_target - enemy.pos;
            if dvec.length() < 20.0 || timer <= 0.0 {
                enemy.vel = Vec2::ZERO;
                // Commit to the player's direction when the charge begins so the warning
                // describes the whole upcoming sweep instead of following them invisibly.
                enemy.ai.charge_dir = safe_dir(ctx.player_pos - enemy.pos, Vec2::new(1.0, 0.0));
                enemy.ai.sub_state = EnemySubState::LaserCharge;
                enemy.ai.sub_timer = 0.75;
            } else {
                let move_dir = steer_clear_of_obstacles(
                    enemy,
                    safe_dir(dvec, Vec2::new(1.0, 0.0)),
                    ctx.obstacles,
                );
                enemy.vel = move_dir * (enemy.speed * 1.5);
                enemy.pos += enemy.vel * ctx.dt;
            }
        }
        EnemySubState::LaserCharge => {
            enemy.vel = Vec2::ZERO;
            if timer <= 0.0 {
                enemy.ai.sub_state = EnemySubState::LaserAttack;
                enemy.ai.sub_timer = 2.2;
                enemy.ai.laser_tick = 0.0;
            }
        }
        EnemySubState::LaserAttack => {
            enemy.vel = Vec2::ZERO;
            if timer <= 0.0 {
                // Sustained sweep beams belong to this action, so they must stop
                // before the wing warning or reposition recovery begins.
                ctx.lasers.retain(|beam| {
                    !(beam.owner == "enemy" && beam.source == enemy.behavior)
                });
                if phase >= 2 {
                    enemy.ai.sub_state = EnemySubState::LaserWingWindup;
                    enemy.ai.sub_timer = 0.46;
                } else {
                    enemy.ai.sub_state = EnemySubState::LaserReposition;
                    enemy.ai.sub_timer = rage_cooldown(enemy, 0.7);
                }
                return;
            }
            let base_angle = enemy.ai.charge_dir.y.atan2(enemy.ai.charge_dir.x).to_degrees();
            let sweep_extent = crate::sim::config::BOSS_LASER_SWEEP_BASE_DEG
                + phase as f32 * crate::sim::config::BOSS_LASER_SWEEP_PER_PHASE_DEG;
            let attack_progress = (1.0 - timer / 2.2).clamp(0.0, 1.0);
            let sweep_offset = (attack_progress * 2.0 - 1.0) * sweep_extent;
            let base_beams = if persona == BossPersona::Aggressive && phase >= 2 {
                2
            } else {
                1
            };
            let beams = rage_volley(enemy, base_beams).clamp(1, 3) as usize;
            let offsets = [sweep_offset, -sweep_offset, 0.0];
            let dmg = boss_damage(difficulty, ctx.wave, 9.5, 0.18, 20);

            enemy.ai.laser_tick -= ctx.dt;
            let reset_hit = enemy.ai.laser_tick <= 0.0;
            if reset_hit {
                let base_tick = match phase {
                    0 => 0.22,
                    1 => 0.18,
                    _ => 0.15,
                };
                enemy.ai.laser_tick = rage_cooldown(enemy, base_tick);
            }

            let mut slot = 0usize;
            for beam in ctx.lasers.iter_mut() {
                if beam.owner == "enemy" && beam.source == enemy.behavior && slot < beams {
                    let rad = (base_angle + offsets[slot]).to_radians();
                    let bdir = Vec2::new(rad.cos(), rad.sin());
                    beam.start = enemy.pos;
                    beam.end = enemy.pos + bdir * (ctx.room_radius * 2.2);
                    beam.damage = dmg;
                    beam.thickness = 12.0;
                    beam.ttl = 0.08;
                    beam.warn = 0.0;
                    beam.t = 0.0;
                    if reset_hit {
                        beam.hit_done = false;
                    }
                    slot += 1;
                }
            }
            for &off in &offsets[slot..beams] {
                let rad = (base_angle + off).to_radians();
                let bdir = Vec2::new(rad.cos(), rad.sin());
                let start = enemy.pos;
                let end = start + bdir * (ctx.room_radius * 2.2);
                ctx.lasers.push(
                    LaserBeam::new(start, end, dmg, 12.0, 0.08, 0.0, [255, 100, 255], "enemy")
                        .with_source(&enemy.behavior),
                );
            }

        }
        EnemySubState::LaserWingWindup => {
            enemy.vel = Vec2::ZERO;
            if timer <= 0.0 {
                let aim = safe_dir(enemy.ai.charge_dir, Vec2::new(1.0, 0.0));
                let damage = boss_damage(difficulty, ctx.wave, 5.5, 0.12, 15);
                fire_fan(
                    ctx.projectiles,
                    enemy.pos,
                    aim,
                    rage_volley(enemy, 5),
                    48.0,
                    178.0 + ctx.wave as f32,
                    damage,
                    2.4,
                    "plasma",
                    &enemy.behavior,
                );
                enemy.ai.sub_state = EnemySubState::LaserReposition;
                enemy.ai.sub_timer = rage_cooldown(enemy, 0.7);
            }
        }
        _ => {}
    }
}

fn prune_traps_for_spikes(traps: &mut Vec<Trap>, incoming: usize) {
    while traps.len().saturating_add(incoming) > MAX_ACTIVE_CONSTRUCTIONS {
        let oldest_of_kind = |kind: &str| -> Option<usize> {
            traps
                .iter()
                .enumerate()
                .filter(|(_, tr)| tr.kind == kind)
                .max_by(|(ia, a), (ib, b)| a.t.total_cmp(&b.t).then_with(|| ib.cmp(ia)))
                .map(|(idx, _)| idx)
        };
        if let Some(idx) = oldest_of_kind("spike").or_else(|| oldest_of_kind("mine")) {
            traps.swap_remove(idx);
        } else {
            break;
        }
    }
}

fn update_boss_trapmaster(
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    difficulty: &str,
    max_enemies: usize,
    total_live_enemies: usize,
) {
    let dvec = ctx.player_pos - enemy.pos;
    let d = dvec.length();
    let dir_to = safe_dir(dvec, Vec2::new(1.0, 0.0));
    let phase = enemy.ai.phase;
    let persona = enemy.ai.persona;

    let winding = enemy.ai.sub_state == EnemySubState::TrapmasterTelegraph;
    let move_scale = if winding { 0.42 } else { 1.0 };
    if d > 320.0 {
        let move_dir = steer_clear_of_obstacles(enemy, dir_to, ctx.obstacles);
        enemy.vel = move_dir * (enemy.speed * 0.85 * move_scale);
        enemy.pos += enemy.vel * ctx.dt;
    } else if d < 200.0 {
        let move_dir = steer_clear_of_obstacles(enemy, -dir_to, ctx.obstacles);
        enemy.vel = move_dir * (enemy.speed * 0.95 * move_scale);
        enemy.pos += enemy.vel * ctx.dt;
    } else {
        let strafe = Vec2::new(-dir_to.y, dir_to.x);
        let move_dir = steer_clear_of_obstacles(enemy, strafe, ctx.obstacles);
        enemy.vel = move_dir * (enemy.speed * move_scale);
        enemy.pos += enemy.vel * ctx.dt;
    }

    if !winding {
        enemy.attack_cd -= ctx.dt;
        if enemy.attack_cd > 0.0 {
            return;
        }
        let proj_speed = 195.0 + (ctx.wave as f32) * 1.7;
        let non_prunable = ctx
            .traps
            .iter()
            .filter(|tr| tr.kind != "spike" && tr.kind != "mine" && tr.ttl > TRAPMASTER_TELEGRAPH)
            .count();
        let deployable_cap = MAX_ACTIVE_CONSTRUCTIONS.saturating_sub(non_prunable);
        enemy.ai.sub_state = EnemySubState::TrapmasterTelegraph;
        enemy.ai.sub_timer = TRAPMASTER_TELEGRAPH;
        enemy.ai.summon_target_count = (if phase == 0 { 3 } else { 4 }).min(deployable_cap) as u8;
        enemy.ai.move_target = clamp_entity_to_map(
            ctx.player_pos + ctx.player_vel * 0.55,
            ctx.room_radius,
            32.0,
            ctx.map_type,
        );
        let base_ang = ctx.rng.range_f32(0.0, TAU);
        enemy.ai.sniper_aim = Vec2::new(base_ang.cos(), base_ang.sin());
        enemy.ai.charge_dir = lead_dir(enemy.pos, ctx.player_pos, ctx.player_vel, proj_speed, 0.85);
        return;
    }

    enemy.ai.sub_timer = (enemy.ai.sub_timer - ctx.dt).max(0.0);
    if enemy.ai.sub_timer > 0.0 {
        return;
    }

    {
        let n = enemy.ai.summon_target_count as usize;
        prune_traps_for_spikes(ctx.traps, n);
        let r = if phase < 2 { 82.0 } else { 92.0 };
        let base_ang = enemy.ai.sniper_aim.y.atan2(enemy.ai.sniper_aim.x);
        let trap_dmg = boss_damage(difficulty, ctx.wave, 12.5, 0.2, 25);
        let predicted_player_pos = enemy.ai.move_target;
        for i in 0..n {
            let pos = trapmaster_spike_position(
                predicted_player_pos,
                base_ang,
                i,
                n,
                r,
                ctx.room_radius,
                ctx.map_type,
            );
            append_trap_capped(
                ctx.traps,
                Trap::new(pos, TRAPMASTER_SPIKE_RADIUS, trap_dmg, 7.6, 0.8, "spike")
                    .with_source(&enemy.behavior),
            );
        }

        let proj_speed = 195.0 + (ctx.wave as f32) * 1.7;
        let dmg = boss_damage(difficulty, ctx.wave, 5.0, 0.14, 16);
        let aim = safe_dir(enemy.ai.charge_dir, dir_to);
        let src = enemy.behavior.clone();

        if phase == 0 {
            if persona != BossPersona::Cautious {
                fire_fan(
                    ctx.projectiles,
                    enemy.pos,
                    aim,
                    rage_volley(enemy, 4),
                    56.0,
                    proj_speed,
                    dmg,
                    2.55,
                    "spread",
                    &src,
                );
            }
        } else if phase == 1 {
            fire_fan(
                ctx.projectiles,
                enemy.pos,
                aim,
                rage_volley(enemy, 6),
                76.0,
                proj_speed,
                dmg + 1,
                2.65,
                "spread",
                &src,
            );
        } else {
            fire_fan(
                ctx.projectiles,
                enemy.pos,
                aim,
                rage_volley(enemy, 7),
                88.0,
                proj_speed,
                dmg + 2,
                2.55,
                "spread",
                &src,
            );
            if matches!(persona, BossPersona::Aggressive | BossPersona::Trickster) {
                fire_fan(
                    ctx.projectiles,
                    enemy.pos,
                    perp(aim),
                    3,
                    38.0,
                    proj_speed * 0.9,
                    dmg.max(1),
                    2.3,
                    "spread",
                    &src,
                );
            }
        }

        let adds_cap = boss_adds_cap(max_enemies, 2);
        if total_live_enemies + ctx.queued_spawns.len() < adds_cap && ctx.rng.f32() < 0.14 {
            let pos = enemy.pos
                + Vec2::new(
                    ctx.rng.range_f32(-70.0, 70.0),
                    ctx.rng.range_f32(-70.0, 70.0),
                );
            let id = *ctx.next_id;
            *ctx.next_id += 1;
            ctx.queued_spawns.push(make_summoned_enemy(
                id,
                pos,
                "engineer",
                ctx.wave,
                difficulty,
                ctx.rng,
            ));
        }

        let base_cd = 2.35 - (ctx.wave as f32) * 0.012;
        enemy.ai.summon_target_count = 0;
        enemy.ai.sub_state = EnemySubState::None;
        enemy.ai.sub_timer = 0.0;
        enemy.attack_cd = (rage_cooldown(
            enemy,
            boss_cd(difficulty, base_cd, phase, 1.05, persona),
        ) - TRAPMASTER_TELEGRAPH)
            .max(0.12);
    }
}

fn boss_summon_points(
    enemy: &Enemy,
    ctx: &BehaviorContext<'_>,
    count: usize,
    child_behavior: &str,
) -> [Vec2; 3] {
    let mut points = [Vec2::ZERO; 3];
    let child_radius = crate::sim::config::enemy_radius(child_behavior);
    let base_radius = enemy.radius + child_radius + 18.0;
    for slot in 0..count.min(points.len()) {
        let mut chosen = None;
        for attempt in 0..24 {
            let ring = base_radius + (attempt / 8) as f32 * 24.0;
            let angle = enemy.seed + slot as f32 * TAU / count.max(1) as f32
                + attempt as f32 * (TAU / 24.0);
            let raw = enemy.pos + Vec2::new(angle.cos(), angle.sin()) * ring;
            let candidate = clamp_entity_to_map(
                raw,
                ctx.room_radius,
                child_radius + 8.0,
                ctx.map_type,
            );
            let overlaps_live = ctx.spawn_snaps.iter().any(|&(other_id, other_pos, other_radius)| {
                other_id != enemy.id
                    && (candidate - other_pos).length_squared()
                        < (child_radius + other_radius + 8.0).powi(2)
            });
            let overlaps_queued = ctx.queued_spawns.iter().any(|other| {
                (candidate - other.pos).length_squared()
                    < (child_radius + other.radius + 8.0).powi(2)
            });
            let overlaps_planned = points[..slot].iter().any(|other_pos| {
                (candidate - *other_pos).length_squared() < (child_radius * 2.0 + 8.0).powi(2)
            });
            if !overlaps_live && !overlaps_queued && !overlaps_planned {
                chosen = Some(candidate);
                break;
            }
        }
        let angle = enemy.seed + slot as f32 * TAU / count.max(1) as f32;
        let fallback = enemy.pos + Vec2::new(angle.cos(), angle.sin()) * base_radius;
        points[slot] = chosen.unwrap_or_else(|| {
            clamp_entity_to_map(
                fallback,
                ctx.room_radius,
                child_radius + 8.0,
                ctx.map_type,
            )
        });
    }
    points
}

fn update_boss_swarmqueen(
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    difficulty: &str,
    max_enemies: usize,
    non_boss_count: usize,
    egg_sac_count: usize,
) {
    let phase = enemy.ai.phase;
    let persona = enemy.ai.persona;

    let dvec = ctx.player_pos - enemy.pos;
    if dvec.length() < 300.0 {
        let move_dir = steer_clear_of_obstacles(
            enemy,
            -safe_dir(dvec, Vec2::new(1.0, 0.0)),
            ctx.obstacles,
        );
        enemy.vel = move_dir * (enemy.speed * 0.8);
        enemy.pos += enemy.vel * ctx.dt;
    } else {
        let drift = safe_dir(dvec, Vec2::new(1.0, 0.0)).rotated_deg(90.0);
        let move_dir = steer_clear_of_obstacles(enemy, drift, ctx.obstacles);
        enemy.vel = move_dir * (enemy.speed * 0.3);
        enemy.pos += enemy.vel * ctx.dt;
    }

    if enemy.ai.sub_state == EnemySubState::None {
        enemy.attack_cd -= ctx.dt;
        if enemy.attack_cd > 0.0 {
            return;
        }

        let adds_cap = boss_adds_cap(max_enemies, 4);
        let cur_adds = non_boss_count.saturating_add(ctx.queued_spawns.len());
        let add_slots = adds_cap.saturating_sub(cur_adds);
        let max_sacs: usize = if phase < 2 { 2 } else { 3 };
        let queued_sacs = ctx
            .queued_spawns
            .iter()
            .filter(|spawn| spawn.behavior == "egg_sac")
            .count();
        let sac_slots = max_sacs.saturating_sub(egg_sac_count.saturating_add(queued_sacs));
        let roll = ctx.rng.f32();

        enemy.ai.sub_state = if roll < 0.5 && add_slots > 0 && sac_slots > 0 {
            EnemySubState::QueenBroodTelegraph
        } else if roll < 0.85 || add_slots < 2 {
            EnemySubState::QueenVolleyTelegraph
        } else {
            EnemySubState::QueenSwarmTelegraph
        };
        enemy.ai.sub_timer = SWARMQUEEN_TELEGRAPH;
        enemy.ai.summon_target_count = 0;
        match enemy.ai.sub_state {
            EnemySubState::QueenBroodTelegraph => {
                let planned = (if phase >= 1 { 2 } else { 1 })
                    .min(add_slots)
                    .min(sac_slots);
                enemy.ai.summon_targets = boss_summon_points(enemy, ctx, planned, "egg_sac");
                enemy.ai.summon_target_count = planned as u8;
            }
            EnemySubState::QueenSwarmTelegraph => {
                let planned = 2.min(add_slots);
                enemy.ai.summon_targets = boss_summon_points(enemy, ctx, planned, "swarm");
                enemy.ai.summon_target_count = planned as u8;
            }
            EnemySubState::QueenVolleyTelegraph => {
                enemy.ai.charge_dir = safe_dir(ctx.player_pos - enemy.pos, Vec2::new(1.0, 0.0));
            }
            _ => {}
        }
        return;
    }

    enemy.ai.sub_timer = (enemy.ai.sub_timer - ctx.dt).max(0.0);
    if enemy.ai.sub_timer > 0.0 {
        return;
    }

    match enemy.ai.sub_state {
        EnemySubState::QueenBroodTelegraph => {
            let adds_cap = boss_adds_cap(max_enemies, 4);
            let cur_adds = non_boss_count.saturating_add(ctx.queued_spawns.len());
            let add_slots = adds_cap.saturating_sub(cur_adds);
            let max_sacs: usize = if phase < 2 { 2 } else { 3 };
            let queued_sacs = ctx
                .queued_spawns
                .iter()
                .filter(|spawn| spawn.behavior == "egg_sac")
                .count();
            let sac_slots = max_sacs.saturating_sub(egg_sac_count.saturating_add(queued_sacs));
            let count = (if phase >= 1 { 2 } else { 1 })
                .min(add_slots)
                .min(sac_slots)
                .min(enemy.ai.summon_target_count as usize);
            if count == 0 {
                enemy.ai.sub_state = EnemySubState::QueenVolleyTelegraph;
                enemy.ai.sub_timer = SWARMQUEEN_TELEGRAPH;
                enemy.ai.summon_target_count = 0;
                enemy.ai.charge_dir = safe_dir(ctx.player_pos - enemy.pos, Vec2::new(1.0, 0.0));
                return;
            }
            for pos in enemy.ai.summon_targets.iter().take(count).copied() {
                let id = *ctx.next_id;
                *ctx.next_id += 1;
                let mut sac = make_summoned_enemy(id, pos, "egg_sac", ctx.wave, difficulty, ctx.rng);
                sac.ai.hatch_timer = if phase == 0 { 4.0 } else { 3.0 };
                sac.ai.max_hatch_timer = sac.ai.hatch_timer;
                ctx.queued_spawns.push(sac);
            }
        }
        EnemySubState::QueenSwarmTelegraph => {
            let adds_cap = boss_adds_cap(max_enemies, 4);
            let cur_adds = non_boss_count.saturating_add(ctx.queued_spawns.len());
            let count = 2
                .min(adds_cap.saturating_sub(cur_adds))
                .min(enemy.ai.summon_target_count as usize);
            if count == 0 {
                enemy.ai.sub_state = EnemySubState::QueenVolleyTelegraph;
                enemy.ai.sub_timer = SWARMQUEEN_TELEGRAPH;
                enemy.ai.summon_target_count = 0;
                enemy.ai.charge_dir = safe_dir(ctx.player_pos - enemy.pos, Vec2::new(1.0, 0.0));
                return;
            }
            for pos in enemy.ai.summon_targets.iter().take(count).copied() {
                let id = *ctx.next_id;
                *ctx.next_id += 1;
                ctx.queued_spawns.push(make_summoned_enemy(
                    id,
                    pos,
                    "swarm",
                    ctx.wave,
                    difficulty,
                    ctx.rng,
                ));
            }
        }
        EnemySubState::QueenVolleyTelegraph => {
            fire_swarmqueen_volley(enemy, ctx, difficulty, phase);
        }
        _ => return,
    }

    enemy.ai.summon_target_count = 0;
    enemy.ai.sub_state = EnemySubState::None;
    let cycle = rage_cooldown(enemy, boss_cd(difficulty, 2.5, phase, 1.2, persona));
    enemy.attack_cd = (cycle - SWARMQUEEN_TELEGRAPH).max(0.12);
}

fn fire_swarmqueen_volley(
    enemy: &Enemy,
    ctx: &mut BehaviorContext<'_>,
    difficulty: &str,
    phase: i32,
) {
    let dmg = boss_damage(difficulty, ctx.wave, 6.0, 0.15, 18);
    let aim = safe_dir(enemy.ai.charge_dir, safe_dir(ctx.player_pos - enemy.pos, Vec2::new(1.0, 0.0)));
    fire_fan(
        ctx.projectiles,
        enemy.pos,
        aim,
        rage_volley(enemy, 5 + phase.min(1)),
        56.0,
        190.0,
        dmg,
        2.6,
        "plasma",
        &enemy.behavior,
    );
}

fn update_boss_brute(enemy: &mut Enemy, ctx: &mut BehaviorContext<'_>, difficulty: &str) {
    let phase = enemy.ai.phase;
    let persona = enemy.ai.persona;

    if enemy.ai.sub_state == EnemySubState::None {
        enemy.ai.sub_state = EnemySubState::BruteChase;
        enemy.ai.sub_timer = 0.0;
    }
    enemy.ai.sub_timer = (enemy.ai.sub_timer - ctx.dt).max(0.0);
    let timer = enemy.ai.sub_timer;

    match enemy.ai.sub_state {
        EnemySubState::BruteChase => {
            let dir_to = safe_dir(ctx.player_pos - enemy.pos, Vec2::new(1.0, 0.0));
            let speed_mod = if persona == BossPersona::Aggressive {
                0.85
            } else {
                0.75
            };
            let move_dir = steer_clear_of_obstacles(enemy, dir_to, ctx.obstacles);
            enemy.vel = move_dir * (enemy.speed * speed_mod);
            enemy.pos += enemy.vel * ctx.dt;
            if timer <= 0.0 {
                enemy.vel = Vec2::ZERO;
                enemy.ai.sub_state = EnemySubState::BruteTelegraph;
                enemy.ai.volley_mode = 0;
                enemy.ai.sub_timer = 1.0;
                enemy.ai.charge_dir = dir_to;
            }
        }
        EnemySubState::BruteTelegraph => {
            enemy.vel = Vec2::ZERO;
            if timer <= 0.0 {
                enemy.ai.sub_state = EnemySubState::BruteCharge;
                enemy.ai.sub_timer = brute_charge_time(enemy);
            }
        }
        EnemySubState::BruteCharge => {
            let charge_dir = enemy.ai.charge_dir;
            let charge_speed = brute_charge_speed(enemy.speed, phase);
            enemy.vel = charge_dir * charge_speed;
            enemy.pos += enemy.vel * ctx.dt;
            let clamped = clamp_entity_to_map(
                enemy.pos,
                ctx.room_radius,
                enemy.radius + 6.0,
                ctx.map_type,
            );
            if (clamped - enemy.pos).length_squared() > 1e-4 {
                enemy.pos = clamped;
                enemy.vel = Vec2::ZERO;
                enemy.ai.sub_state = EnemySubState::BruteStun;
                enemy.ai.sub_timer = if phase >= 2 && enemy.ai.volley_mode == 0 {
                    enemy.ai.volley_mode = 1;
                    0.68
                } else {
                    2.0
                };
                let sw_dmg = boss_damage(difficulty, ctx.wave, 7.0, 0.13, 18);
                fire_ring(
                    ctx.projectiles,
                    enemy.pos,
                    rage_volley(enemy, 12 + phase * 3),
                    240.0,
                    sw_dmg,
                    1.8,
                    0.0,
                    "plasma",
                    &enemy.behavior,
                );
                if phase >= 2 && enemy.ai.volley_mode == 2 {
                    // The final-phase impact adds two delayed cross-lanes. Their inner offsets
                    // leave a clear band to read and cross while the warning beams are active.
                    let cross_dir = charge_dir.perp();
                    let span = ctx.room_radius * 1.15;
                    let shock_dmg = boss_damage(difficulty, ctx.wave, 8.0, 0.15, 18);
                    for offset in [105.0_f32, 245.0] {
                        let anchor = clamp_entity_to_map(
                            enemy.pos - charge_dir * offset,
                            ctx.room_radius,
                            12.0,
                            ctx.map_type,
                        );
                        ctx.lasers.push(LaserBeam::new(
                            anchor - cross_dir * span,
                            anchor + cross_dir * span,
                            shock_dmg,
                            10.0,
                            0.14,
                            0.72,
                            [105, 190, 255],
                            "enemy",
                        ).with_source(&enemy.behavior));
                    }
                } else if phase == 1 && enemy.ai.volley_mode == 0 {
                    let pulse_damage = boss_damage(difficulty, ctx.wave, 10.0, 0.18, 22);
                    append_trap_pair_capped(
                        ctx.traps,
                        Trap::new(enemy.pos, 78.0, 0, 0.62, 0.62, "slam_warn")
                            .with_source(&enemy.behavior),
                        Trap::new(enemy.pos, 78.0, pulse_damage, 1.1, 0.62, "slam")
                            .with_source(&enemy.behavior),
                    );
                }
            } else if timer <= 0.0 {
                enemy.vel = Vec2::ZERO;
                enemy.ai.sub_state = EnemySubState::BruteRecover;
                enemy.ai.sub_timer = 0.8;
                enemy.ai.volley_mode = 0;
            }
        }
        EnemySubState::BruteStun => {
            enemy.vel = Vec2::ZERO;
            if timer <= 0.0 {
                if phase >= 2 && enemy.ai.volley_mode == 1 {
                    enemy.ai.volley_mode = 2;
                    enemy.ai.sub_state = EnemySubState::BruteTelegraph;
                    enemy.ai.sub_timer = BRUTE_FOLLOWUP_TELEGRAPH_TIME;
                    enemy.ai.charge_dir = safe_dir(
                        ctx.player_pos - enemy.pos,
                        enemy.ai.charge_dir,
                    );
                } else {
                    enemy.ai.volley_mode = 0;
                    enemy.ai.sub_state = EnemySubState::BruteChase;
                    enemy.ai.sub_timer = rage_cooldown(enemy, if phase == 0 { 3.0 } else { 2.2 });
                }
            }
        }
        EnemySubState::BruteRecover => {
            enemy.vel = Vec2::ZERO;
            if timer <= 0.0 {
                enemy.ai.volley_mode = 0;
                enemy.ai.sub_state = EnemySubState::BruteChase;
                enemy.ai.sub_timer = rage_cooldown(enemy, 2.5);
            }
        }
        _ => {}
    }
}

fn update_boss_abyss_gaze(
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    difficulty: &str,
    max_enemies: usize,
    total_live_enemies: usize,
) {
    let dvec = ctx.player_pos - enemy.pos;
    let d = dvec.length();
    let dir_to = safe_dir(dvec, Vec2::new(1.0, 0.0));
    let phase = enemy.ai.phase;
    let persona = enemy.ai.persona;
    let strafe = Vec2::new(-dir_to.y, dir_to.x);

    let base_desired = match phase {
        0 => 240.0,
        1 => 220.0,
        _ => 205.0,
    };
    let desired = base_desired
        + match persona {
            BossPersona::Aggressive => -28.0,
            BossPersona::Cautious => 38.0,
            BossPersona::Trickster => 0.0,
        };
    let orbit_sign = match persona {
        BossPersona::Aggressive => 1.0,
        BossPersona::Cautious => -1.0,
        BossPersona::Trickster => {
            if (enemy.t / 3.8).floor() as i32 % 2 == 0 { 1.0 } else { -1.0 }
        }
    };
    let strafe = strafe * orbit_sign;
    let mv = if d > desired + 20.0 {
        (dir_to * 0.88 + strafe * 0.36).normalized()
    } else if d < desired - 20.0 {
        ((-dir_to) * 0.7 + strafe * 0.62).normalized()
    } else {
        (strafe * 0.92 + dir_to * 0.2).normalized()
    };
    let move_dir = steer_clear_of_obstacles(enemy, mv, ctx.obstacles);
    let move_scale = if enemy.ai.sub_state == EnemySubState::AbyssTelegraph {
        0.55
    } else {
        1.0
    };
    let speed_val = enemy.speed * (0.9 + 0.12 * (enemy.t * 2.2).sin()) * move_scale;
    enemy.vel = move_dir * speed_val;
    enemy.pos += enemy.vel * ctx.dt;

    if enemy.ai.sub_state != EnemySubState::AbyssTelegraph {
        enemy.attack_cd -= ctx.dt;
        if enemy.attack_cd > 0.0 {
            return;
        }
        let proj_speed = 218.0 + (ctx.wave as f32) * 1.6;
        enemy.ai.charge_dir = lead_dir(enemy.pos, ctx.player_pos, ctx.player_vel, proj_speed, 0.72);
        let ring_rate = if phase >= 2 { 34.0 } else { 30.0 };
        let start_rad = ((enemy.t + ABYSS_GAZE_TELEGRAPH) * ring_rate).to_radians();
        enemy.ai.sniper_aim = Vec2::new(start_rad.cos(), start_rad.sin());
        enemy.ai.sub_state = EnemySubState::AbyssTelegraph;
        enemy.ai.sub_timer = ABYSS_GAZE_TELEGRAPH;
        return;
    }
    enemy.ai.sub_timer = (enemy.ai.sub_timer - ctx.dt).max(0.0);
    if enemy.ai.sub_timer > 0.0 {
        return;
    }

    {
        let proj_speed = 218.0 + (ctx.wave as f32) * 1.6;
        let dmg = boss_damage(difficulty, ctx.wave, 6.0, 0.13, 16);
        let aim = safe_dir(enemy.ai.charge_dir, dir_to);
        let ring_start_deg = enemy.ai.sniper_aim.y.atan2(enemy.ai.sniper_aim.x).to_degrees();
        let src = enemy.behavior.clone();

        if phase == 0 {
            fire_fan(
                ctx.projectiles,
                enemy.pos,
                aim,
                rage_volley(enemy, 6),
                72.0,
                proj_speed,
                dmg,
                2.6,
                "plasma",
                &src,
            );
        } else if phase == 1 {
            fire_fan(
                ctx.projectiles,
                enemy.pos,
                aim,
                rage_volley(enemy, 7),
                82.0,
                proj_speed,
                dmg + 1,
                2.65,
                "plasma",
                &src,
            );
            fire_ring(
                ctx.projectiles,
                enemy.pos,
                8,
                proj_speed * 0.8,
                (dmg - 1).max(1),
                2.45,
                ring_start_deg,
                "bullet",
                &src,
            );
        } else {
            for off in [-14.0_f32, 0.0, 14.0] {
                let a = aim.rotated_deg(off);
                let n_fan = if off == 0.0 {
                    rage_volley(enemy, 3)
                } else {
                    3
                };
                fire_fan(
                    ctx.projectiles,
                    enemy.pos,
                    a,
                    n_fan,
                    24.0,
                    proj_speed,
                    dmg + 1,
                    2.35,
                    "plasma",
                    &src,
                );
            }
            fire_ring(
                ctx.projectiles,
                enemy.pos,
                8,
                proj_speed * 0.78,
                (dmg - 1).max(1),
                2.4,
                ring_start_deg,
                "bullet",
                &src,
            );
        }

        let beam_len = ctx.room_radius * (DIAMOND_EXTENT_RATIO * 1.5);
        if phase >= 1 {
            let lane_half_angle = match (phase, persona) {
                (1, BossPersona::Aggressive) => 16.0,
                (1, BossPersona::Cautious) => 24.0,
                (1, BossPersona::Trickster) => 20.0,
                (_, BossPersona::Aggressive) => 20.0,
                (_, BossPersona::Cautious) => 29.0,
                (_, BossPersona::Trickster) => 24.0,
            };
            let lane_shift = if persona == BossPersona::Trickster {
                if (enemy.t / 3.0).floor() as i32 % 2 == 0 { -7.0 } else { 7.0 }
            } else {
                0.0
            };
            let offsets = [-lane_half_angle + lane_shift, lane_half_angle + lane_shift];
            let ldmg = boss_damage(difficulty, ctx.wave, 10.0, 0.2, 24);
            let thick = if phase == 1 { 7.2 } else { 7.8 };
            let warn = if phase == 1 { 0.62 } else { 0.58 };
            for off in offsets {
                let d2 = aim.rotated_deg(off);
                ctx.lasers.push(LaserBeam::new(
                    enemy.pos,
                    enemy.pos + d2 * beam_len,
                    ldmg,
                    thick,
                    0.12,
                    warn,
                    [190, 210, 255],
                    "enemy",
                ).with_source(&enemy.behavior));
            }
        }

        let adds_cap = boss_adds_cap(max_enemies, 4);
        let spawn_chance = if phase == 2 { 0.09 } else { 0.06 };
        if total_live_enemies + ctx.queued_spawns.len() < adds_cap && ctx.rng.f32() < spawn_chance {
            let pos = enemy.pos
                + Vec2::new(
                    ctx.rng.range_f32(-85.0, 85.0),
                    ctx.rng.range_f32(-85.0, 85.0),
                );
            let add_behavior = if ctx.rng.f32() < 0.6 { "flyer" } else { "ranged" };
            let id = *ctx.next_id;
            *ctx.next_id += 1;
            ctx.queued_spawns.push(make_summoned_enemy(
                id,
                pos,
                add_behavior,
                ctx.wave,
                difficulty,
                ctx.rng,
            ));
        }

        let base_cd = 1.8 - (ctx.wave as f32) * 0.006;
        enemy.ai.sub_state = EnemySubState::None;
        enemy.ai.sub_timer = 0.0;
        enemy.attack_cd = (rage_cooldown(
            enemy,
            boss_cd(difficulty, base_cd, phase, 1.0, persona),
        ) - ABYSS_GAZE_TELEGRAPH)
            .max(0.12);
    }
}

fn update_boss_womb_core(
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    difficulty: &str,
    max_enemies: usize,
    total_live_enemies: usize,
) {
    let dvec = ctx.player_pos - enemy.pos;
    let d = dvec.length();
    let dir_to = safe_dir(dvec, Vec2::new(1.0, 0.0));
    let phase = enemy.ai.phase;
    let persona = enemy.ai.persona;

    let base_desired = match phase {
        0 => 235.0,
        1 => 218.0,
        _ => 200.0,
    };
    let desired = base_desired
        + match persona {
            BossPersona::Aggressive => -32.0,
            BossPersona::Cautious => 42.0,
            BossPersona::Trickster => 0.0,
        };
    let wobble = Vec2::new((enemy.t * 1.5).sin(), (enemy.t * 1.9).cos()) * 0.3;
    let mv = if d > desired + 15.0 {
        (dir_to * 0.82 + wobble).normalized()
    } else if d < desired - 15.0 {
        ((-dir_to) * 0.72 + wobble).normalized()
    } else {
        (Vec2::new(-dir_to.y, dir_to.x) * 0.82 + wobble).normalized()
    };
    let move_dir = steer_clear_of_obstacles(enemy, mv, ctx.obstacles);
    enemy.vel = move_dir * (enemy.speed * 0.88);
    enemy.pos += enemy.vel * ctx.dt;

    if enemy.ai.sub_state != EnemySubState::WombPulseTelegraph {
        enemy.attack_cd -= ctx.dt;
        if enemy.attack_cd > 0.0 {
            return;
        }
        let pulse_r = if phase < 2 { 86.0 } else { 94.0 };
        let pulse_dmg = boss_damage(difficulty, ctx.wave, 11.5, 0.2, 24);
        let pulse_pos = match persona {
            BossPersona::Aggressive => ctx.player_pos,
            BossPersona::Cautious => enemy.pos + dir_to * 150.0,
            BossPersona::Trickster => ctx.player_pos + ctx.player_vel * 0.48,
        };
        let pulse_pos = clamp_entity_to_map(
            pulse_pos,
            ctx.room_radius,
            pulse_r + 32.0,
            ctx.map_type,
        );
        append_trap_pair_capped(
            ctx.traps,
            Trap::new(
                pulse_pos,
                pulse_r + 16.0,
                0,
                WOMB_PULSE_TELEGRAPH,
                WOMB_PULSE_TELEGRAPH,
                "womb_warn",
            )
            .with_source(&enemy.behavior),
            Trap::new(
                pulse_pos,
                pulse_r,
                pulse_dmg,
                0.9,
                WOMB_PULSE_TELEGRAPH,
                "womb_pulse",
            )
            .with_source(&enemy.behavior),
        );
        let proj_speed = 212.0 + (ctx.wave as f32) * 1.9;
        enemy.ai.charge_dir = lead_dir(enemy.pos, ctx.player_pos, ctx.player_vel, proj_speed, 0.78);
        let ring_rate = if phase >= 2 { 30.0 } else { 24.0 };
        let ring_rad = ((enemy.t + WOMB_PULSE_TELEGRAPH) * ring_rate).to_radians();
        enemy.ai.sniper_aim = Vec2::new(ring_rad.cos(), ring_rad.sin());
        enemy.ai.sub_state = EnemySubState::WombPulseTelegraph;
        enemy.ai.sub_timer = WOMB_PULSE_TELEGRAPH;
        return;
    }

    enemy.ai.sub_timer = (enemy.ai.sub_timer - ctx.dt).max(0.0);
    if enemy.ai.sub_timer > 0.0 {
        return;
    }

    {
        let proj_speed = 212.0 + (ctx.wave as f32) * 1.9;
        let dmg = boss_damage(difficulty, ctx.wave, 6.0, 0.15, 18);
        let aim = safe_dir(enemy.ai.charge_dir, dir_to);
        let ring_start_deg = enemy.ai.sniper_aim.y.atan2(enemy.ai.sniper_aim.x).to_degrees();
        let gun = cycle_gun(enemy, &["spread", "bullet", "plasma"]).to_string();
        let src = enemy.behavior.clone();

        if phase == 0 {
            fire_fan(
                ctx.projectiles,
                enemy.pos,
                aim,
                rage_volley(enemy, 5),
                68.0,
                proj_speed,
                dmg,
                2.6,
                &gun,
                &src,
            );
        } else if phase == 1 {
            fire_fan(
                ctx.projectiles,
                enemy.pos,
                aim,
                rage_volley(enemy, 7),
                82.0,
                proj_speed,
                dmg + 1,
                2.65,
                &gun,
                &src,
            );
            fire_ring(
                ctx.projectiles,
                enemy.pos,
                7,
                proj_speed * 0.8,
                (dmg - 1).max(1),
                2.5,
                ring_start_deg,
                "bullet",
                &src,
            );
        } else {
            fire_fan(
                ctx.projectiles,
                enemy.pos,
                aim,
                rage_volley(enemy, 7),
                86.0,
                proj_speed,
                dmg + 1,
                2.5,
                &gun,
                &src,
            );
            fire_fan(
                ctx.projectiles,
                enemy.pos,
                perp(aim),
                4,
                34.0,
                proj_speed * 0.9,
                dmg,
                2.35,
                "spread",
                &src,
            );
            fire_ring(
                ctx.projectiles,
                enemy.pos,
                6,
                proj_speed * 0.78,
                (dmg - 1).max(1),
                2.35,
                ring_start_deg,
                "plasma",
                &src,
            );
        }

        let adds_cap = boss_adds_cap(max_enemies, 3);
        let cur_len = total_live_enemies + ctx.queued_spawns.len();
        if cur_len < adds_cap {
            let summon_n = if phase <= 1 {
                1
            } else if ctx.rng.f32() < 0.5 {
                2
            } else {
                1
            };
            for _ in 0..summon_n {
                if total_live_enemies + ctx.queued_spawns.len() >= adds_cap {
                    break;
                }
                let pos = enemy.pos
                    + Vec2::new(
                        ctx.rng.range_f32(-70.0, 70.0),
                        ctx.rng.range_f32(-70.0, 70.0),
                    );
                let add_b = if ctx.rng.f32() < 0.7 { "swarm" } else { "charger" };
                let id = *ctx.next_id;
                *ctx.next_id += 1;
                ctx.queued_spawns.push(make_summoned_enemy(
                    id,
                    pos,
                    add_b,
                    ctx.wave,
                    difficulty,
                    ctx.rng,
                ));
            }
        }

        enemy.ai.sub_state = EnemySubState::None;
        enemy.ai.sub_timer = 0.0;
        let base_cd = 2.25 - (ctx.wave as f32) * 0.007;
        enemy.attack_cd = (rage_cooldown(
            enemy,
            boss_cd(difficulty, base_cd, phase, 1.15, persona),
        ) - WOMB_PULSE_TELEGRAPH)
            .max(0.12);
    }
}

/// The Eclipse Archon changes its orbit before every cast, then fires radial volleys with a
/// deliberate opening aimed at the player. The opening is wide enough to read and use, while
/// later phases shift it between volleys so staying still is never the answer.
fn update_boss_eclipse_archon(
    enemy: &mut Enemy,
    ctx: &mut BehaviorContext<'_>,
    difficulty: &str,
) {
    let phase = enemy.ai.phase;
    let persona = enemy.ai.persona;
    if enemy.ai.sub_state == EnemySubState::None {
        enemy.ai.sub_state = EnemySubState::EclipseOrbit;
    }

    match enemy.ai.sub_state {
        EnemySubState::EclipseOrbit => {
            let to_player = ctx.player_pos - enemy.pos;
            let distance = to_player.length();
            let toward = safe_dir(to_player, Vec2::new(1.0, 0.0));
            let desired = match phase {
                0 => 315.0,
                1 => 280.0,
                _ => 245.0,
            };
            let radial = if distance > desired + 28.0 {
                toward * 0.85
            } else if distance < desired - 28.0 {
                toward * -0.75
            } else {
                Vec2::ZERO
            };
            let side = match persona {
                BossPersona::Aggressive => 1.0,
                BossPersona::Cautious => -1.0,
                BossPersona::Trickster => {
                    if (enemy.t / 4.0).floor() as i32 % 2 == 0 { 1.0 } else { -1.0 }
                }
            };
            let orbit = toward.perp() * side;
            let move_dir = steer_clear_of_obstacles(
                enemy,
                safe_dir(radial + orbit * 0.72, orbit),
                ctx.obstacles,
            );
            enemy.vel = move_dir * (enemy.speed * 0.95);
            enemy.pos += enemy.vel * ctx.dt;
            enemy.pos = clamp_entity_to_map(enemy.pos, ctx.room_radius, 34.0, ctx.map_type);

            enemy.attack_cd -= ctx.dt;
            if enemy.attack_cd <= 0.0 {
                enemy.vel = Vec2::ZERO;
                enemy.ai.sub_state = EnemySubState::EclipseCharge;
                enemy.ai.sub_timer = if enemy.ai.rage { 0.68 } else { 0.92 };
                enemy.ai.charge_dir = toward;
                enemy.ai.gun_idx = 0;
            }
        }
        EnemySubState::EclipseCharge => {
            let to_player = ctx.player_pos - enemy.pos;
            // The charge heading is frozen on entry; only the model and its
            // floor cue move during preparation, so walking away can escape it.
            let toward = safe_dir(enemy.ai.charge_dir, safe_dir(to_player, Vec2::new(1.0, 0.0)));
            let drift = toward.perp() * if enemy.ai.persona == BossPersona::Cautious { -1.0 } else { 1.0 };
            let move_dir = steer_clear_of_obstacles(enemy, drift, ctx.obstacles);
            enemy.vel = move_dir * (enemy.speed * 0.2);
            enemy.pos += enemy.vel * ctx.dt;
            enemy.pos = clamp_entity_to_map(enemy.pos, ctx.room_radius, 34.0, ctx.map_type);
            enemy.ai.sub_timer = (enemy.ai.sub_timer - ctx.dt).max(0.0);
            if enemy.ai.sub_timer <= 0.0 {
                enemy.vel = Vec2::ZERO;
                enemy.ai.sub_state = EnemySubState::EclipseBurst;
                enemy.ai.sub_timer = 0.0;
                enemy.ai.gun_idx = 0;
            }
        }
        EnemySubState::EclipseBurst => {
            enemy.vel = Vec2::ZERO;
            enemy.ai.sub_timer = (enemy.ai.sub_timer - ctx.dt).max(0.0);
            let volley_count = 1 + phase;
            if enemy.ai.gun_idx < volley_count as usize && enemy.ai.sub_timer <= 0.0 {
                let volley = enemy.ai.gun_idx as i32;
                let count = rage_volley(enemy, 10 + phase * 2).max(3);
                let speed = 164.0 + (ctx.wave as f32) * 1.15 + (phase as f32) * 16.0;
                let damage = boss_damage(difficulty, ctx.wave, 5.0, 0.11, 15);
                let safe_angle = eclipse_safe_angle(enemy, volley);
                let gap_half_width = ECLIPSE_GAP_HALF_WIDTH;
                let start_angle = enemy.seed + volley as f32 * (TAU / (count as f32 * 2.0));

                for i in 0..count {
                    let angle = start_angle + (i as f32 / count as f32) * TAU;
                    let delta = (angle - safe_angle + PI).rem_euclid(TAU) - PI;
                    if delta.abs() < gap_half_width {
                        continue;
                    }
                    let direction = Vec2::new(angle.cos(), angle.sin());
                    ctx.projectiles.push(
                        Projectile::new(
                            enemy.pos,
                            direction * speed,
                            damage,
                            2.7,
                            "enemy",
                            if volley % 2 == 0 { "plasma" } else { "bullet" },
                        )
                        .with_source(&enemy.behavior),
                    );
                }

                enemy.ai.gun_idx += 1;
                enemy.ai.sub_timer = if enemy.ai.rage { 0.27 } else { 0.36 };
            } else if enemy.ai.gun_idx >= volley_count as usize && enemy.ai.sub_timer <= 0.0 {
                let to_player = safe_dir(ctx.player_pos - enemy.pos, enemy.ai.charge_dir);
                let side = to_player.perp()
                    * if enemy.ai.persona == BossPersona::Cautious { -1.0 } else { 1.0 };
                let escape = enemy.pos - to_player * 150.0 + side * 120.0;
                enemy.ai.move_target = clamp_entity_to_map(escape, ctx.room_radius, 36.0, ctx.map_type);
                enemy.ai.sub_state = EnemySubState::EclipseEscape;
                enemy.ai.sub_timer = 0.58;
            }
        }
        EnemySubState::EclipseEscape => {
            let toward = safe_dir(enemy.ai.move_target - enemy.pos, enemy.ai.charge_dir * -1.0);
            let move_dir = steer_clear_of_obstacles(enemy, toward, ctx.obstacles);
            enemy.vel = move_dir * (enemy.speed * 1.75);
            enemy.pos += enemy.vel * ctx.dt;
            enemy.pos = clamp_entity_to_map(enemy.pos, ctx.room_radius, 34.0, ctx.map_type);
            enemy.ai.sub_timer = (enemy.ai.sub_timer - ctx.dt).max(0.0);
            if (enemy.ai.move_target - enemy.pos).length() < 22.0 || enemy.ai.sub_timer <= 0.0 {
                enemy.vel = Vec2::ZERO;
                enemy.ai.sub_state = EnemySubState::EclipseOrbit;
                let base_cd = match phase {
                    0 => 2.85,
                    1 => 2.5,
                    _ => 2.2,
                };
                enemy.attack_cd = rage_cooldown(enemy, boss_cd(difficulty, base_cd, phase, 1.45, persona));
            }
        }
        _ => {}
    }
}
