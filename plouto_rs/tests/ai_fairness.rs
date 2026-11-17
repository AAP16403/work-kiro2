//! Headless fairness measurements for the regular-enemy AI.
//!
//! These tests intentionally stay outside `SimState`: they infer commits from
//! the public attack phase, count fired regular projectiles from the live
//! projectile pool, and count projectile collision events from `step` events.
//! Accepted damage is reported separately; this keeps measurement-only state
//! out of replay hashes.

use std::collections::BTreeMap;

use plouto_rs::sim::ai_skill::ai_skill;
use plouto_rs::sim::config::{SCREEN_H, SCREEN_W};
use plouto_rs::sim::director::{active_attack_weight, AttackDirector};
use plouto_rs::sim::enemy::{AttackPhase, Enemy};
use plouto_rs::sim::level::enemy_stats;
use plouto_rs::sim::math::{clamp_entity_to_map, Vec2};
use plouto_rs::sim::projectile::Projectile;
use plouto_rs::sim::state::{
    DamageRejection, DamageTarget, RunSetup, SimEvent, SimInput, SimState,
};
use plouto_rs::sim::step::step;

const DT: f32 = 1.0 / 60.0;
const RANGED_WARNING_SECONDS: f32 = 0.34;
const MATCHED_SEEDS: [u64; 5] = [71_009, 71_771, 90_001, 90_019, 91_771];
const MATCHED_RUN_FRAMES: usize = 10_800; // 180 simulated seconds per seed and difficulty.
const ROLE_WARNING_FRAMES: usize = 3_600; // 60 simulated seconds per isolated role and seed.
const REGULAR_ROSTER: [&str; 11] = [
    "chaser", "ranged", "sniper", "bomber", "tank", "charger", "spitter", "flyer",
    "engineer", "swarm", "egg_sac",
];

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct ProjectileKey {
    source: String,
    projectile_type: String,
    damage: i32,
    vx: u32,
    vy: u32,
    flight_duration: u32,
}

#[derive(Debug, Default, Clone)]
struct Metrics {
    fired: usize,
    landed: usize,
    accepted_damage_events: usize,
    commits: usize,
    commits_during_iframes: usize,
    max_committed_weight: u8,
    fired_by_source: [usize; 4],
    commits_by_role: [usize; 11],
}

#[derive(Debug, Default)]
struct RoleWarningMetrics {
    commits: usize,
    physical_hits: usize,
    warning_to_damage: Vec<f32>,
}

fn new_state(map: &str, difficulty: &str, seed: u64) -> SimState {
    let mut state = SimState::new(RunSetup {
        seed,
        difficulty: difficulty.to_string(),
        map_type: map.to_string(),
        auto_shoot: false,
        view_w: SCREEN_W,
        view_h: SCREEN_H,
        ..RunSetup::default()
    });
    state.wave = 5;
    state.wave_active = true;
    state.auto_shoot = false;
    state.player.hp = 100_000;
    state.player.max_hp = 100_000;
    state.player.shield = 0;
    state.player.invincibility_timer = 0.0;
    state.perception_mem.prev_hp = state.player.hp;
    state
}

fn add_roster(state: &mut SimState) {
    let origin = state.player.pos;
    for (index, role) in REGULAR_ROSTER.iter().enumerate() {
        let angle = index as f32 * (std::f32::consts::TAU / REGULAR_ROSTER.len() as f32);
        let desired = origin + Vec2::new(angle.cos(), angle.sin()) * 300.0;
        let (hp, speed, attack_mult) = enemy_stats(role, state.wave, &state.difficulty);
        let pos = clamp_entity_to_map(desired, state.room_radius, 70.0, &state.map_type);
        let mut enemy = Enemy::new(80_000 + index as u64, pos, hp, speed, role);
        enemy.max_hp = hp;
        enemy.spawn_index = index as i64;
        enemy.seed = 0.37 + index as f32 * 0.61;
        enemy.attack_cd = 0.18 + index as f32 * 0.035;
        enemy.ai.attack_mult = attack_mult;
        state.enemies.push(enemy);
    }
    state.enemy_spawn_count = REGULAR_ROSTER.len() as i64;
}

fn bot_input(state: &SimState, frame: usize) -> SimInput {
    let radial = state.player.pos.normalized();
    let orbit = if radial.length_squared() > 1.0e-6 {
        radial.perp()
    } else {
        Vec2::new((state.time * 0.7).cos(), (state.time * 0.7).sin())
    };
    let edge_steer = if state.player.pos.length() > state.room_radius * 0.72 {
        -radial
    } else {
        Vec2::ZERO
    };
    let nearest = state
        .enemies
        .iter()
        .filter(|enemy| !enemy.is_dead && enemy.hp > 0)
        .min_by(|a, b| {
            (a.pos - state.player.pos)
                .length_squared()
                .total_cmp(&(b.pos - state.player.pos).length_squared())
        });
    let (aim_world, dodge, approach) = if let Some(enemy) = nearest {
        let to_enemy = enemy.pos - state.player.pos;
        let away = -to_enemy.normalized();
        (
            enemy.pos + enemy.vel * (to_enemy.length() / 260.0).min(0.6),
            if to_enemy.length() < 118.0 {
                away * 0.8
            } else {
                Vec2::ZERO
            },
            if to_enemy.length() > 280.0 {
                to_enemy.normalized() * 0.85
            } else {
                Vec2::ZERO
            },
        )
    } else {
        (state.player.pos + Vec2::new(180.0, 0.0), Vec2::ZERO, Vec2::ZERO)
    };
    SimInput {
        move_dir: (orbit * 0.78 + edge_steer + dodge + approach).normalized(),
        aim_world,
        fire_held: false,
        dash_pressed: frame % 100 == 0 && frame > 0,
        ..SimInput::default()
    }
}

fn is_regular_shot(projectile: &Projectile) -> bool {
    projectile.owner == "enemy"
        && projectile.projectile_type != "bomb"
        && matches!(
            projectile.source.as_str(),
            "ranged" | "sniper" | "spitter" | "tank"
        )
}

fn shot_key(projectile: &Projectile) -> Option<ProjectileKey> {
    is_regular_shot(projectile).then(|| ProjectileKey {
        source: projectile.source.clone(),
        projectile_type: projectile.projectile_type.clone(),
        damage: projectile.damage,
        vx: projectile.vel.x.to_bits(),
        vy: projectile.vel.y.to_bits(),
        flight_duration: projectile.flight_duration.to_bits(),
    })
}

fn shot_counts(state: &SimState) -> BTreeMap<ProjectileKey, usize> {
    let mut counts = BTreeMap::new();
    for projectile in &state.projectiles {
        if let Some(key) = shot_key(projectile) {
            *counts.entry(key).or_insert(0) += 1;
        }
    }
    counts
}

fn count_new_shots_by_source(
    before: &BTreeMap<ProjectileKey, usize>,
    after: &BTreeMap<ProjectileKey, usize>,
) -> [usize; 4] {
    let mut counts = [0; 4];
    for (key, count) in after {
        let Some(slot) = source_slot(&key.source) else { continue; };
        counts[slot] += count.saturating_sub(*before.get(key).unwrap_or(&0));
    }
    counts
}

fn source_slot(source: &str) -> Option<usize> {
    match source {
        "ranged" => Some(0),
        "sniper" => Some(1),
        "spitter" => Some(2),
        "tank" => Some(3),
        _ => None,
    }
}

fn is_landed_enemy_projectile_hit(event: &SimEvent) -> bool {
    matches!(
        event,
        SimEvent::DamageResolved(result)
            if result.target == DamageTarget::Player
                && result.source == "enemy projectile"
                && result.raw_damage > 0
                && !matches!(result.rejected,
                    Some(DamageRejection::NonPositive | DamageRejection::MissingTarget))
    )
}

fn is_accepted_enemy_projectile_damage(event: &SimEvent) -> bool {
    matches!(
        event,
        SimEvent::DamageResolved(result)
            if result.target == DamageTarget::Player
                && result.source == "enemy projectile"
                && result.rejected.is_none()
                && result.health_damage + result.shield_damage > 0
    )
}

fn attack_weight(state: &SimState) -> u8 {
    state
        .enemies
        .iter()
        .filter(|enemy| !enemy.is_dead && enemy.hp > 0)
        .map(active_attack_weight)
        .fold(0_u8, u8::saturating_add)
}

fn simulate_metrics(
    map: &str,
    difficulty: &str,
    seed: u64,
    frames: usize,
    stationary_target: bool,
) -> Metrics {
    let mut state = new_state(map, difficulty, seed);
    add_roster(&mut state);
    let mut metrics = Metrics::default();

    for frame in 0..frames {
        if state.game_over {
            break;
        }
        let skill = ai_skill(&state.difficulty, state.wave);
        let breathing_for_tick = if state.player.hp < state.perception_mem.prev_hp {
            0.60
        } else {
            (state.perception_mem.breathing_room_left - DT).max(0.0)
        };
        let budget_for_tick = AttackDirector::new(
            &state.enemies,
            breathing_for_tick,
            skill.coordination,
        )
        .budget;
        let before_active_ids: std::collections::BTreeSet<_> = state
            .enemies
            .iter()
            .filter(|enemy| active_attack_weight(enemy) > 0)
            .map(|enemy| enemy.id)
            .collect();
        let before_weight = attack_weight(&state);
        let before_shots = shot_counts(&state);
        let input = if stationary_target {
            SimInput {
                aim_world: state.player.pos + Vec2::new(180.0, 0.0),
                ..SimInput::default()
            }
        } else {
            bot_input(&state, frame)
        };
        let events = step(&mut state, &input, DT);
        let after_weight = attack_weight(&state);
        let newly_committed: Vec<_> = state
            .enemies
            .iter()
            .filter(|enemy| {
                active_attack_weight(enemy) > 0 && !before_active_ids.contains(&enemy.id)
            })
            .collect();
        for enemy in &newly_committed {
            metrics.commits += 1;
            if let Some(slot) = REGULAR_ROSTER
                .iter()
                .position(|role| *role == enemy.behavior)
            {
                metrics.commits_by_role[slot] += 1;
            }
            if state.player.is_dashing || state.player.invincibility_timer > 0.0 {
                metrics.commits_during_iframes += 1;
            }
        }
        let by_source = count_new_shots_by_source(&before_shots, &shot_counts(&state));
        metrics.fired_by_source = std::array::from_fn(|slot| {
            metrics.fired_by_source[slot] + by_source[slot]
        });
        metrics.fired += by_source.iter().sum::<usize>();
        metrics.landed += events.iter().filter(|event| is_landed_enemy_projectile_hit(event)).count();
        metrics.accepted_damage_events += events
            .iter()
            .filter(|event| is_accepted_enemy_projectile_damage(event))
            .count();
        metrics.max_committed_weight = metrics.max_committed_weight.max(after_weight);

        let new_weight = newly_committed
            .iter()
            .map(|enemy| active_attack_weight(enemy))
            .fold(0_u8, u8::saturating_add);
        if !newly_committed.is_empty() && before_weight.saturating_add(new_weight) > budget_for_tick {
            let forced_active: Vec<_> = newly_committed
                .iter()
                .filter(|enemy| {
                    (enemy.ai.last_forced_attack_started_at - enemy.ai.last_attack_started_at)
                        .abs()
                        < DT * 0.5
                })
                .collect();
            assert_eq!(
                forced_active.len(),
                1,
                "new committed weight {} over prior weight {before_weight} exceeds director budget {budget_for_tick} without one forced grant on {map}/{difficulty} at t={:.2}; live={}, breathing={:.2}, active={:?}",
                new_weight,
                state.time,
                state.enemies.iter().filter(|enemy| !enemy.is_dead && enemy.hp > 0).count(),
                breathing_for_tick,
                state.enemies.iter().filter(|enemy| active_attack_weight(enemy) > 0).map(|enemy| (&enemy.behavior, active_attack_weight(enemy), enemy.ai.last_attack_started_at, enemy.ai.last_forced_attack_started_at, enemy.attack_phase())).collect::<Vec<_>>(),
            );
            let forced_weight = active_attack_weight(forced_active[0]);
            assert!(
                before_weight.saturating_add(new_weight)
                    <= budget_for_tick.saturating_add(forced_weight),
                "one forced grant must account for the excess committed weight on {map}/{difficulty} at t={:.2}",
                state.time
            );
        }
    }
    metrics
}

fn merge_metrics(total: &mut Metrics, next: Metrics) {
    total.fired += next.fired;
    total.landed += next.landed;
    total.accepted_damage_events += next.accepted_damage_events;
    total.commits += next.commits;
    total.commits_during_iframes += next.commits_during_iframes;
    total.max_committed_weight = total.max_committed_weight.max(next.max_committed_weight);
    for slot in 0..total.fired_by_source.len() {
        total.fired_by_source[slot] += next.fired_by_source[slot];
    }
    for slot in 0..total.commits_by_role.len() {
        total.commits_by_role[slot] += next.commits_by_role[slot];
    }
}

fn is_physical_damage_hit_from_role(event: &SimEvent, role: &str) -> bool {
    let expected_source = match role {
        "ranged" | "spitter" | "tank" => "enemy projectile",
        "sniper" => "enemy laser",
        "bomber" => "enemy bomb",
        "engineer" => "floor trap",
        "chaser" | "charger" | "flyer" | "swarm" => "enemy contact",
        _ => return false,
    };
    matches!(
        event,
        SimEvent::DamageResolved(result)
            if result.target == DamageTarget::Player
                && result.raw_damage > 0
                && !matches!(result.rejected,
                    Some(DamageRejection::NonPositive | DamageRejection::MissingTarget))
                && result.source == expected_source
    )
}

fn simulate_role_warnings(role: &str, seed: u64, difficulty: &str, frames: usize) -> RoleWarningMetrics {
    let mut state = new_state("circle", difficulty, seed);
    let (hp, speed, attack_mult) = enemy_stats(role, state.wave, &state.difficulty);
    let tracked_enemy_id = 12_000 + seed;
    let mut enemy = Enemy::new(tracked_enemy_id, state.player.pos + Vec2::new(250.0, 0.0), hp, speed, role);
    enemy.spawn_index = 0;
    enemy.seed = (seed % 10_000) as f32 * 0.000_071 + 0.23;
    enemy.attack_cd = 0.05;
    enemy.ai.attack_mult = attack_mult;
    state.enemies.push(enemy);
    state.enemy_spawn_count = 1;

    let mut metrics = RoleWarningMetrics::default();
    let mut first_commit_at = None;
    'frames: for _ in 0..frames {
        let Some(tracked_before) = state.enemies.iter().find(|enemy| enemy.id == tracked_enemy_id) else {
            break;
        };
        if state.game_over || tracked_before.is_dead || tracked_before.hp <= 0 {
            break;
        }
        let before_phase = tracked_before.attack_phase();
        let input = SimInput {
            aim_world: state.player.pos + Vec2::new(250.0, 0.0),
            ..SimInput::default()
        };
        let events = step(&mut state, &input, DT);
        let after_phase = state
            .enemies
            .iter()
            .find(|enemy| enemy.id == tracked_enemy_id)
            .map(Enemy::attack_phase);
        if let Some(after_phase) = after_phase {
            if !matches!(before_phase, AttackPhase::Windup { .. })
                && matches!(after_phase, AttackPhase::Windup { .. })
            {
                if first_commit_at.is_some() {
                    // Do not pair a previous projectile with a later attack's warning.
                    break;
                }
                metrics.commits = 1;
                first_commit_at = Some(state.time);
            }
        }
        for _event in events
            .iter()
            .filter(|event| is_physical_damage_hit_from_role(event, role))
        {
            metrics.physical_hits += 1;
            if let Some(started_at) = first_commit_at {
                metrics.warning_to_damage.push((state.time - started_at).max(0.0));
                break 'frames;
            }
        }
        if after_phase.is_none() {
            break;
        }
    }
    metrics
}

#[test]
fn ranged_damage_arrives_after_its_commit_warning() {
    let mut state = new_state("circle", "hard", 71_009);
    let (hp, speed, attack_mult) = enemy_stats("ranged", state.wave, &state.difficulty);
    let mut enemy = Enemy::new(9_100, state.player.pos + Vec2::new(250.0, 0.0), hp, speed, "ranged");
    enemy.spawn_index = 0;
    enemy.seed = 0.41;
    enemy.attack_cd = 0.05;
    enemy.ai.attack_mult = attack_mult;
    state.enemies.push(enemy);
    state.enemy_spawn_count = 1;

    let mut first_commit_at = None;
    let mut first_hit_after_commit = None;
    for _ in 0..1_200 {
        let before = state.enemies[0].attack_phase();
        let input = SimInput {
            aim_world: state.player.pos + Vec2::new(1.0, 0.0),
            ..SimInput::default()
        };
        let events = step(&mut state, &input, DT);
        let after = state.enemies[0].attack_phase();
        if !matches!(before, AttackPhase::Windup { .. })
            && matches!(after, AttackPhase::Windup { .. })
            && first_commit_at.is_none()
        {
            first_commit_at = Some(state.time);
        }
        if events.iter().any(is_landed_enemy_projectile_hit) {
            first_hit_after_commit = Some(
                state.time
                    - first_commit_at.expect("ranged projectile hit must follow a recorded commit"),
            );
            break;
        }
    }

    let elapsed = first_hit_after_commit.expect("stationary headless player should be hit by ranged fire");
    assert!(
        elapsed + DT >= RANGED_WARNING_SECONDS,
        "ranged hit arrived after only {elapsed:.3}s; authored warning is {RANGED_WARNING_SECONDS:.2}s"
    );
}

#[test]
fn fairness_measurements_cover_all_difficulties_and_arena_shapes() {
    let maps = ["circle", "donut", "cross", "diamond"];
    let difficulties = ["easy", "normal", "hard"];
    let mut normal_commits = 0usize;
    let mut normal_iframe_commits = 0usize;

    for map in maps {
        for difficulty in difficulties {
            let mut metrics = Metrics::default();
            for seed in MATCHED_SEEDS {
                merge_metrics(
                    &mut metrics,
                    simulate_metrics(map, difficulty, seed, 1_800, false),
                );
            }
            assert!(metrics.commits > 0, "no attack commits observed on {map}/{difficulty}");
            assert!(metrics.fired > 0, "no regular projectiles fired on {map}/{difficulty}");
            if difficulty == "normal" {
                normal_commits += metrics.commits;
                normal_iframe_commits += metrics.commits_during_iframes;
            }
        }
    }

    assert!(normal_commits > 0, "normal-difficulty commit sample must be nonempty");
    let iframe_share = normal_iframe_commits as f32 / normal_commits as f32;
    assert!(
        iframe_share < 0.10,
        "{normal_iframe_commits}/{normal_commits} normal-difficulty attack commits happened during player invulnerability ({iframe_share:.1}%)"
    );

    let mut easy = Metrics::default();
    let mut hard = Metrics::default();
    let mut easy_orbit = Metrics::default();
    let mut hard_orbit = Metrics::default();
    for seed in MATCHED_SEEDS {
        let easy_orbit_seed = simulate_metrics("circle", "easy", seed, MATCHED_RUN_FRAMES, false);
        let hard_orbit_seed = simulate_metrics("circle", "hard", seed, MATCHED_RUN_FRAMES, false);
        eprintln!(
            "WP-G moving-orbit diagnostic seed {seed}: Easy projectile collisions {}/{}, accepted damage events={}, commits {:?}; Hard {}/{}, accepted damage events={}, commits {:?}",
            easy_orbit_seed.landed,
            easy_orbit_seed.fired,
            easy_orbit_seed.accepted_damage_events,
            easy_orbit_seed.commits_by_role,
            hard_orbit_seed.landed,
            hard_orbit_seed.fired,
            hard_orbit_seed.accepted_damage_events,
            hard_orbit_seed.commits_by_role,
        );
        merge_metrics(&mut easy_orbit, easy_orbit_seed);
        merge_metrics(&mut hard_orbit, hard_orbit_seed);

        let easy_seed = simulate_metrics("circle", "easy", seed, MATCHED_RUN_FRAMES, true);
        let hard_seed = simulate_metrics("circle", "hard", seed, MATCHED_RUN_FRAMES, true);
        eprintln!(
            "WP-G stationary-target matched seed {seed}: Easy projectile collisions {}/{}, accepted damage events={}, source fire {:?}, commits {:?}; Hard projectile collisions {}/{}, accepted damage events={}, source fire {:?}, commits {:?}",
            easy_seed.landed,
            easy_seed.fired,
            easy_seed.accepted_damage_events,
            easy_seed.fired_by_source,
            easy_seed.commits_by_role,
            hard_seed.landed,
            hard_seed.fired,
            hard_seed.accepted_damage_events,
            hard_seed.fired_by_source,
            hard_seed.commits_by_role,
        );
        merge_metrics(&mut easy, easy_seed);
        merge_metrics(&mut hard, hard_seed);
    }
    assert!(easy.fired > 0 && hard.fired > 0, "both matched samples must fire shots");
    let easy_rate = easy.landed as f32 / easy.fired as f32;
    let hard_rate = hard.landed as f32 / hard.fired as f32;

    eprintln!(
        "WP-G diagnostic only (neither bot is a gameplay-fairness verdict): Normal commits during player invulnerability {normal_iframe_commits}/{normal_commits}; moving-orbit accepted projectile hits Easy={}/{} ({} accepted damage), Hard={}/{} ({}); stationary-target collision accuracy Easy={:.4} ({}/{}; accepted damage events={}), Hard={:.4} ({}/{}; accepted damage events={}), ratio={:.3}x; max committed weight Easy={}, Hard={}",
        easy_orbit.landed,
        easy_orbit.fired,
        easy_orbit.accepted_damage_events,
        hard_orbit.landed,
        hard_orbit.fired,
        hard_orbit.accepted_damage_events,
        easy_rate,
        easy.landed,
        easy.fired,
        easy.accepted_damage_events,
        hard_rate,
        hard.landed,
        hard.fired,
        hard.accepted_damage_events,
        hard_rate / easy_rate.max(f32::EPSILON),
        easy.max_committed_weight,
        hard.max_committed_weight,
    );

    for (index, role) in REGULAR_ROSTER.iter().enumerate() {
        eprintln!(
            "WP-G moving-orbit commits across {} matched 180s seeds: {role} Easy={}, Hard={}",
            MATCHED_SEEDS.len(),
            easy_orbit.commits_by_role[index],
            hard_orbit.commits_by_role[index],
        );
    }

    // Isolated single-role runs pair the first physical hit with the first
    // windup. These are warning-time samples, not a complete fairness verdict.
    for (role_index, role) in REGULAR_ROSTER.iter().enumerate() {
        if *role == "egg_sac" {
            eprintln!("WP-G warning-to-damage: egg_sac has no committed attack phase; it summons other roles, so it is reported by mixed-roster commits only");
            continue;
        }
        let mut aggregate = RoleWarningMetrics::default();
        for seed in MATCHED_SEEDS {
            let sample = simulate_role_warnings(role, seed, "normal", ROLE_WARNING_FRAMES);
            aggregate.commits += sample.commits;
            aggregate.physical_hits += sample.physical_hits;
            aggregate.warning_to_damage.extend(sample.warning_to_damage);
        }
        aggregate.warning_to_damage.sort_by(f32::total_cmp);
        if aggregate.warning_to_damage.is_empty() {
            eprintln!(
                "WP-G warning-to-damage: {role} commits={}, physical hits={}, matched warning samples=0/{}",
                aggregate.commits,
                aggregate.physical_hits,
                MATCHED_SEEDS.len(),
            );
            continue;
        }
        let times = &aggregate.warning_to_damage;
        let mean = times.iter().sum::<f32>() / times.len() as f32;
        let percentile = |p: f32| -> f32 {
            let index = ((times.len() - 1) as f32 * p).round() as usize;
            times[index]
        };
        eprintln!(
            "WP-G warning-to-damage: {} commits={}, physical hits={}, warning-hit samples={}; min={:.3}s p10={:.3}s median={:.3}s mean={:.3}s p90={:.3}s max={:.3}s",
            REGULAR_ROSTER[role_index],
            aggregate.commits,
            aggregate.physical_hits,
            times.len(),
            times[0],
            percentile(0.10),
            percentile(0.50),
            mean,
            percentile(0.90),
            times[times.len() - 1],
        );
    }
}
