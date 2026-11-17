use std::env;
use std::fs;
use std::time::Instant;

use plouto_rs::sim::config::RuntimeConfig;
use plouto_rs::sim::enemy::Enemy;
use plouto_rs::sim::math::Vec2;
use plouto_rs::sim::replay::{state_hash, SIMULATION_RULES_VERSION};
use plouto_rs::sim::state::{RunSetup, SimInput, SimState};
use plouto_rs::sim::step::step;
use serde::Serialize;

const FIXED_DT: f32 = 1.0 / 60.0;
const WARMUP_STEPS: usize = 240;
const MEASURED_STEPS: usize = 1800;
const CHECKPOINT_INTERVAL: usize = 300;
const GOLDEN_ANGLE: f32 = 2.399_963_1;

const ENEMY_ROLES: [&str; 11] = [
    "chaser", "bomber", "ranged", "sniper", "tank", "charger", "spitter", "flyer",
    "engineer", "swarm", "egg_sac",
];

#[derive(Serialize)]
struct Environment {
    os: &'static str,
    arch: &'static str,
    logical_cpus: usize,
    rust_profile: &'static str,
}

#[derive(Serialize)]
struct ScenarioResult {
    name: String,
    initial_enemies: usize,
    warmup_steps: usize,
    measured_steps: usize,
    fixed_dt_seconds: f32,
    median_step_us: f64,
    p95_step_us: f64,
    p99_step_us: f64,
    max_step_us: f64,
    final_enemies: usize,
    max_enemies: usize,
    max_projectiles: usize,
    max_step_events: usize,
    checkpoints: Vec<String>,
}

#[derive(Serialize)]
struct ProfileReport {
    kind: &'static str,
    rules_version: u32,
    environment: Environment,
    scenarios: Vec<ScenarioResult>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let output_path = env::args().nth(1);
    let logical_cpus = std::thread::available_parallelism().map_or(1, |count| count.get());
    let mut scenarios = Vec::new();

    for enemy_count in [24, 64, 112] {
        scenarios.push(profile_scenario(
            synthetic_crowd(enemy_count),
            format!("synthetic-mixed-roles-{enemy_count}-actors"),
        ));
    }
    scenarios.push(profile_scenario(authored_wave(14), "authored-wave-14-normal".to_string()));
    scenarios.push(profile_scenario(authored_wave(15), "authored-wave-15-boss".to_string()));

    let report = ProfileReport {
        kind: "headless-rust-simulation-profile",
        rules_version: SIMULATION_RULES_VERSION,
        environment: Environment {
            os: env::consts::OS,
            arch: env::consts::ARCH,
            logical_cpus,
            rust_profile: "release-opt-level-3-thin-lto",
        },
        scenarios,
    };
    let json = serde_json::to_string_pretty(&report)?;
    if let Some(path) = output_path {
        fs::write(path, &json)?;
    }
    println!("{json}");
    Ok(())
}

fn profile_state(seed: u64) -> SimState {
    let setup = RunSetup {
        seed,
        auto_shoot: false,
        runtime: RuntimeConfig {
            enable_obstacles: false,
            ..RuntimeConfig::default()
        },
        ..RunSetup::default()
    };
    let mut state = SimState::new(setup);
    state.player.hp = 1_000_000;
    state.player.max_hp = 1_000_000;
    state.player.ultra_charges = state.player.ultra_max_charges;
    state.player.homing_until = 120.0;
    state.player.ricochet_until = 120.0;
    state.player.magnet_until = 120.0;
    state.player.vortex_until = 120.0;
    state.player.drone_until = 120.0;
    state.player.laser_until = 120.0;
    state
}

fn synthetic_crowd(enemy_count: usize) -> SimState {
    let seed = 0x504C_4F55_544F_u64 ^ enemy_count as u64;
    let mut state = profile_state(seed);
    state.wave = 14;
    state.wave_active = true;
    state.max_enemies = enemy_count;
    for i in 0..enemy_count {
        let angle = i as f32 * GOLDEN_ANGLE;
        let ring = (i % 5) as f32;
        let radius = 190.0 + ring * 46.0;
        let position = Vec2::new(angle.cos() * radius, angle.sin() * radius);
        let role = ENEMY_ROLES[i % ENEMY_ROLES.len()];
        let id = state.alloc_id();
        let mut enemy = Enemy::new(id, position, 100_000, 70.0 + ring * 4.0, role);
        enemy.max_hp = 100_000;
        enemy.attack_cd = 0.2 + (i % 7) as f32 * 0.11;
        enemy.ai.attack_mult = 1.0;
        state.enemies.push(enemy);
    }
    state
}

fn authored_wave(wave: i32) -> SimState {
    let mut state = profile_state(0x4155_5448_4F52_0000_u64 ^ wave as u64);
    state.wave = wave;
    state.wave_active = false;
    state.last_wave_clear = -100.0;
    let _spawn_events = step(&mut state, &SimInput::default(), FIXED_DT);
    state
}

fn profile_scenario(mut state: SimState, name: String) -> ScenarioResult {
    let initial_enemies = state.enemies.len();

    for warmup_frame in 0..WARMUP_STEPS {
        let input = profile_input(warmup_frame);
        let _events = step(&mut state, &input, FIXED_DT);
    }

    let mut samples_ns = Vec::with_capacity(MEASURED_STEPS);
    let mut checkpoints = Vec::with_capacity(MEASURED_STEPS / CHECKPOINT_INTERVAL);
    let mut max_enemies = initial_enemies;
    let mut max_projectiles = state.projectiles.len();
    let mut max_step_events = 0;

    for frame in 0..MEASURED_STEPS {
        let input = profile_input(WARMUP_STEPS + frame);
        let start = Instant::now();
        let events = step(&mut state, &input, FIXED_DT);
        let elapsed = start.elapsed();
        samples_ns.push(elapsed.as_nanos() as u64);
        max_step_events = max_step_events.max(events.len());
        drop(events);
        max_enemies = max_enemies.max(state.enemies.len());
        max_projectiles = max_projectiles.max(state.projectiles.len());

        if (frame + 1) % CHECKPOINT_INTERVAL == 0 {
            checkpoints.push(state_hash(&state));
        }
    }

    samples_ns.sort_unstable();
    let percentile_us = |percentile: usize| -> f64 {
        let index = ((samples_ns.len() - 1) * percentile / 100).min(samples_ns.len() - 1);
        samples_ns[index] as f64 / 1_000.0
    };
    let max_step_us = samples_ns.last().copied().unwrap_or_default() as f64 / 1_000.0;

    ScenarioResult {
        name,
        initial_enemies,
        warmup_steps: WARMUP_STEPS,
        measured_steps: MEASURED_STEPS,
        fixed_dt_seconds: FIXED_DT,
        median_step_us: percentile_us(50),
        p95_step_us: percentile_us(95),
        p99_step_us: percentile_us(99),
        max_step_us,
        final_enemies: state.enemies.len(),
        max_enemies,
        max_projectiles,
        max_step_events,
        checkpoints,
    }
}

fn profile_input(frame: usize) -> SimInput {
    let t = frame as f32 * FIXED_DT;
    let move_dir = Vec2::new((t * 0.41).sin(), (t * 0.29).cos());
    SimInput {
        move_dir,
        aim_world: Vec2::new((t * 0.17).cos() * 260.0, (t * 0.17).sin() * 260.0),
        fire_held: frame % 2 == 0,
        boost_held: frame % 240 < 42,
        dash_pressed: frame % 180 == 0,
        ultra_pressed: frame % 600 == 0,
    }
}
