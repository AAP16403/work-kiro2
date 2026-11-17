use serde_json::{json, Value};
use std::fs;
use tempfile::tempdir;

use plouto_rs::assets::resolve_asset;
use plouto_rs::audio::{AudioManager, CUE_SPECS};

use plouto_rs::save::atomic::{atomic_write_json, quarantine, PROGRESS_VERSION};
use plouto_rs::save::progress::{
    best_for_date, end_run, ensure_progress_file, load_progress, save_progress,
    skin_is_unlocked, RunContext,
};
use plouto_rs::save::scores::{load_high_scores, submit_score, top_score};
use plouto_rs::save::settings::{load_settings, save_settings, update_settings_keys};
use plouto_rs::sim::achievements::RunStats;
use plouto_rs::sim::config::{
    ARENA_MARGIN_DEFAULT, ARENA_MARGIN_MAX, ARENA_MARGIN_MIN, CROSS_ARM_RATIO,
    DIAMOND_EXTENT_RATIO, DONUT_INNER_RATIO, PARALLEL_MIN_ENEMIES, REPULSOR_RANGE, SCREEN_H,
    SCREEN_W, SHIELD_MAX, ULTRA_MAX_CHARGES_HARD_CAP,
};
use plouto_rs::sim::daily::{
    challenge_for_date, daily_mutator, daily_seed, is_daily_run, normalise_date,
    DAILY_ARENA_MARGIN, DAILY_DIFFICULTY, DAILY_MAP_TYPE,
};
use plouto_rs::sim::enemy::Enemy;
use plouto_rs::sim::level::spawn_wave_enemies;
use plouto_rs::sim::math::{
    arena_inside, clamp_entity_to_map, clamp_to_map, random_spawn_map_edge, Vec2,
};
use plouto_rs::sim::mutators::{
    apply_mutators, combined_score_multiplier, format_score_mult, normalize_selection, MUTATORS,
};
use plouto_rs::sim::powerup::PowerUp;
use plouto_rs::sim::replay::{load_recording, replay_and_verify, state_hash, Recorder};
use plouto_rs::sim::player::Player;
use plouto_rs::sim::rpg::{
    apply_perm_reward, apply_temp_reward, format_perm_hud, recompute_temp_mods, reward_category,
    roll_boss_rewards, ActiveTempReward, TEMP_REWARD_POOL, PERM_REWARD_POOL,
};
use plouto_rs::sim::rng::SimRng;
use plouto_rs::sim::score::ScoreTracker;
use plouto_rs::sim::specials::AfterburnSystem;
use plouto_rs::sim::state::{RunSetup, SimEvent, SimInput, SimState};
use plouto_rs::sim::step::{apply_boss_perm_reward, apply_boss_temp_reward, step};
use plouto_rs::sim::weapons::get_weapon;

fn assert_near(a: f32, b: f32, tol: f32) {
    assert!((a - b).abs() <= tol, "expected {a} ~ {b} (tol {tol})");
}

#[test]
fn test_map_geometries_and_resize_clamping() {
    let radius = 300.0;
    // Diamond uses exact SQRT_2 * radius L1 half-extent
    let d_max = radius * DIAMOND_EXTENT_RATIO;
    assert!(arena_inside(Vec2::new(d_max - 10.0, 0.0), radius, "diamond"));
    assert!(!arena_inside(Vec2::new(d_max + 12.0, 0.0), radius, "diamond"));
    let d_clamped = clamp_to_map(Vec2::new(400.0, 400.0), radius, "diamond");
    assert!(arena_inside(d_clamped, radius, "diamond"));

    // Cross arm clamping prevents corner snagging (w = CROSS_ARM_RATIO * radius)
    let c_corner = clamp_to_map(Vec2::new(260.0, 260.0), radius, "cross");
    assert!(arena_inside(c_corner, radius, "cross"));
    assert!(
        c_corner.x.abs() <= radius * CROSS_ARM_RATIO + 0.01
            || c_corner.y.abs() <= radius * CROSS_ARM_RATIO + 0.01
    );

    // Donut keeps outer disc and excludes inner hole (< DONUT_INNER_RATIO * r)
    let donut_inner = clamp_to_map(Vec2::new(10.0, 0.0), radius, "donut");
    assert!(donut_inner.length() >= radius * DONUT_INNER_RATIO - 0.1);
    assert!(arena_inside(donut_inner, radius, "donut"));

    // Donut player spawn begins safely on solid ring, not inside center void
    let mut donut_setup = RunSetup::default();
    donut_setup.map_type = "donut".to_string();
    let donut_state = SimState::new(donut_setup);
    assert!(arena_inside(donut_state.player.pos, donut_state.room_radius, "donut"));

    // Random spawn edge stays strictly inside map boundaries across all 4 maps
    let mut state = SimState::new(RunSetup::default());
    let initial_radius = state.room_radius;
    assert!(initial_radius > 550.0, "expected expanded default arena radius, got {initial_radius}");
    let hd_radius = plouto_rs::sim::math::compute_room_radius(1280, 720, ARENA_MARGIN_DEFAULT);
    assert!(hd_radius > 750.0, "expected expanded 1280x720 arena radius, got {hd_radius}");
    for map in ["circle", "donut", "cross", "diamond"] {
        for _ in 0..80 {
            let p = random_spawn_map_edge(Vec2::ZERO, radius, map, &mut state.rng);
            assert!(
                arena_inside(p, radius + 1.0, map),
                "spawn {p:?} outside {map}"
            );
        }
    }

    // Live resize shrinks arena and clamps player, enemies, and powerups inside
    state.map_type = "diamond".to_string();
    state.player.pos = Vec2::new(initial_radius * 0.9, 0.0);
    state.enemies.push(Enemy::new(9001, Vec2::new(0.0, initial_radius * 0.92), 10, 50.0, "chaser"));
    state.powerups.push(PowerUp::new(Vec2::new(-initial_radius * 0.92, 0.0), "heal", None));
    state.on_view_resized(640, 480, ARENA_MARGIN_MAX);
    assert!(state.room_radius < initial_radius);
    assert!(arena_inside(state.player.pos, state.room_radius, &state.map_type));
    assert!(arena_inside(
        state.enemies.last().unwrap().pos,
        state.room_radius,
        &state.map_type
    ));
    assert!(arena_inside(
        state.powerups.last().unwrap().pos,
        state.room_radius,
        &state.map_type
    ));
    let _ = ARENA_MARGIN_MIN;
}

#[test]
fn test_determinism_rayon_steering_and_replay_verification() {
    let tmp = tempdir().unwrap();
    let rec_path = tmp.path().join("test_run.json");

    let run_with_swarm = |seed: u64| -> (String, i32) {
        let setup = RunSetup {
            seed,
            difficulty: "normal".to_string(),
            map_type: "cross".to_string(),
            mutator_ids: vec!["glass_cannon".to_string(), "frenzy".to_string()],
            view_w: SCREEN_W,
            view_h: SCREEN_H,
            ..RunSetup::default()
        };
        let mut state = SimState::new(setup);
        // Inject > PARALLEL_MIN_ENEMIES enemies to force Rayon parallel formation steering path!
        for i in 0..(PARALLEL_MIN_ENEMIES + 8) {
            let angle = (i as f32) * 0.25;
            let pos = Vec2::new(angle.cos() * 200.0, angle.sin() * 200.0);
            let mut e = Enemy::new(50_000 + i as u64, pos, 15, 110.0, "swarm");
            e.seed = (i as f32) * 0.5;
            state.enemies.push(e);
        }

        let dt = 1.0 / 60.0;
        for f in 0..360usize {
            let t = f as f32 * dt;
            let input = SimInput {
                move_dir: Vec2::new((t * 1.7).cos(), (t * 1.3).sin()),
                aim_world: Vec2::new((t * 3.1).cos() * 180.0, (t * 3.1).sin() * 180.0),
                fire_held: true,
                boost_held: f % 90 < 20,
                dash_pressed: f == 30 || f == 150 || f == 270,
                ultra_pressed: f == 60,
            };
            step(&mut state, &input, dt);
        }
        (state_hash(&state), state.score.score)
    };

    let (hash_a, score_a) = run_with_swarm(424242);
    let (hash_b, score_b) = run_with_swarm(424242);
    assert_eq!(hash_a, hash_b, "identical seed + input must match bit-for-bit across Rayon steering");
    assert_eq!(score_a, score_b);

    // Pure recorded run from SimState::new must verify bit-for-bit on replay
    let setup = RunSetup {
        seed: 424242,
        difficulty: "normal".to_string(),
        map_type: "cross".to_string(),
        mutator_ids: vec!["glass_cannon".to_string(), "frenzy".to_string()],
        view_w: SCREEN_W,
        view_h: SCREEN_H,
        ..RunSetup::default()
    };
    let mut rec_state = SimState::new(setup);
    let mut recorder = Recorder::from_state(&rec_state, SCREEN_W, SCREEN_H);
    let dt = 1.0 / 60.0;
    for f in 0..360usize {
        let t = f as f32 * dt;
        let input = SimInput {
            move_dir: Vec2::new((t * 1.7).cos(), (t * 1.3).sin()),
            aim_world: Vec2::new((t * 3.1).cos() * 180.0, (t * 3.1).sin() * 180.0),
            fire_held: true,
            boost_held: f % 90 < 20,
            dash_pressed: f == 30 || f == 150 || f == 270,
            ultra_pressed: f == 60,
        };
        recorder.push_frame(&input);
        step(&mut rec_state, &input, dt);
    }
    recorder.save_to_file(&rec_state, &rec_path).unwrap();

    let loaded = load_recording(&rec_path).unwrap();
    let verify = replay_and_verify(&loaded);
    assert!(verify.matches, "replay hash mismatch: actual={} expected={}", verify.actual_hash, verify.expected_hash);
}

#[test]
fn swarm_mode_clock_obeys_enemy_time_scale() {
    let run_swarm_clock = |slow: bool| {
        let setup = RunSetup {
            seed: 42,
            auto_shoot: false,
            ..RunSetup::default()
        };
        let mut state = SimState::new(setup);
        state.wave_active = true;
        if slow {
            state.player.time_slow_until = 10.0;
        }
        state
            .enemies
            .push(Enemy::new(42_001, Vec2::new(350.0, 0.0), 1_000, 110.0, "swarm"));

        for _ in 0..60 {
            step(&mut state, &SimInput::default(), 1.0 / 60.0);
        }
        state.swarm_brain.expect("swarm brain should initialize").mode_t
    };

    let normal_timer = run_swarm_clock(false);
    let slowed_timer = run_swarm_clock(true);
    assert!(
        slowed_timer > normal_timer + 0.35,
        "time-slow should delay the flock's shared mode transition (normal={normal_timer:.2}, slow={slowed_timer:.2})"
    );
}

#[test]
fn simultaneous_enemy_projectiles_resolve_as_one_hit() {
    use plouto_rs::sim::projectile::Projectile;

    let setup = RunSetup {
        seed: 43,
        auto_shoot: false,
        ..RunSetup::default()
    };
    let mut state = SimState::new(setup);
    state.wave_active = true;
    state.player.shield = 0;
    state.projectiles.push(Projectile::new(
        state.player.pos,
        Vec2::ZERO,
        12,
        1.0,
        "enemy",
        "bullet",
    ));
    state.projectiles.push(Projectile::new(
        state.player.pos,
        Vec2::ZERO,
        12,
        1.0,
        "enemy",
        "bullet",
    ));

    step(&mut state, &SimInput::default(), 1.0 / 60.0);

    assert_eq!(state.player.hp, 88, "same-frame pellets should not stack hull damage");
    assert_eq!(state.run_stats.hits_taken, 1);
    assert_eq!(state.run_stats.damage_taken, 12);
    assert!(state.player.invincibility_timer > 0.0);
}

#[test]
fn difficulty_scales_incoming_damage_before_shield_absorption() {
    use plouto_rs::sim::projectile::Projectile;

    for (difficulty, _incoming, expected_shield) in
        [("easy", 10, 10), ("normal", 12, 8), ("hard", 14, 6)]
    {
        let setup = RunSetup {
            difficulty: difficulty.to_string(),
            auto_shoot: false,
            ..RunSetup::default()
        };
        let mut state = SimState::new(setup);
        state.wave_active = true;
        state.player.shield = 20;
        state.projectiles.push(Projectile::new(
            state.player.pos,
            Vec2::ZERO,
            12,
            1.0,
            "enemy",
            "bullet",
        ));

        step(&mut state, &SimInput::default(), 1.0 / 60.0);

        assert_eq!(state.player.hp, 100, "{difficulty} shield should absorb the hit");
        assert_eq!(state.player.shield, expected_shield, "{difficulty} shield remainder");
        // A shield-only block loses no health: no hit is recorded and the Untouchable streak holds.
        assert_eq!(state.run_stats.damage_taken, 0);
        assert_eq!(state.run_stats.hits_taken, 0);
        assert_eq!(state.run_stats.shield_blocks, 1);
    }
}

#[test]
fn swarm_squad_avoids_body_pileups_through_its_mode_cycle() {
    use std::f32::consts::TAU;

    let setup = RunSetup {
        seed: 44,
        auto_shoot: false,
        ..RunSetup::default()
    };
    let mut state = SimState::new(setup);
    state.wave_active = true;
    state.player.hp = 1_000_000;
    for index in 0..20 {
        let angle = index as f32 * TAU / 20.0;
        let radius = 280.0 + (index as f32 * 1.7).sin() * 22.0;
        let mut enemy = Enemy::new(
            44_100 + index as u64,
            Vec2::new(angle.cos() * radius, angle.sin() * radius),
            1_000,
            110.0,
            "swarm",
        );
        enemy.seed = angle;
        state.enemies.push(enemy);
    }

    for _ in 0..150 {
        step(&mut state, &SimInput::default(), 1.0 / 60.0);
    }

    let mut closest = f32::INFINITY;
    let mut closest_pair = (0usize, 1usize);
    for first in 0..state.enemies.len() {
        for second in first + 1..state.enemies.len() {
            let distance = (state.enemies[first].pos - state.enemies[second].pos).length();
            if distance < closest {
                closest = distance;
                closest_pair = (first, second);
            }
        }
    }
    let minimum_clearance = state.enemies[0].radius + state.enemies[1].radius;
    assert!(
        closest > minimum_clearance * 0.72,
        "swarm formation collapsed to {closest:.1} units (body clearance {minimum_clearance:.1}); pair {:?}/{:?}, mode {:?}, ring {:.1}",
        state.enemies[closest_pair.0].pos,
        state.enemies[closest_pair.1].pos,
        state.swarm_brain.as_ref().map(|brain| brain.mode.as_str()),
        state.swarm_brain.as_ref().map(|brain| brain.ring_r).unwrap_or_default()
    );
}

#[test]
fn powerful_weapon_pickups_expire_and_restore_the_primary() {
    use plouto_rs::sim::powerup::{apply_powerup, expire_weapon_pickup};
    use plouto_rs::sim::player::Player;
    use plouto_rs::sim::specials::{ChainSystem, RepulsorSystem};
    for (key, duration) in [("heavy", 8.0), ("flak", 6.0), ("railgun", 12.0), ("plasma", 12.0)] {
        let mut player = Player::default_at_origin();
        let mut chain = ChainSystem::new();
        let mut repulsor = RepulsorSystem::new();
        let mut rng = SimRng::new(123);
        let pickup = PowerUp::new(Vec2::ZERO, "weapon", Some(key.to_string()));
        apply_powerup(&mut player, &pickup, 10.0, 8, &mut chain, &mut repulsor, &mut rng);
        assert_eq!(player.current_weapon.key, key);
        assert_eq!(player.weapon_until, 10.0 + duration);
        assert!(!expire_weapon_pickup(&mut player, 10.0 + duration - 0.01));
        assert!(expire_weapon_pickup(&mut player, 10.0 + duration));
        assert_eq!(player.current_weapon.key, "basic");
        assert!(player.weapon_base.is_none());
    }
}

#[test]
fn charger_recovers_when_a_charge_cannot_reach_its_target() {
    use plouto_rs::sim::enemy::EnemySubState;
    let mut state = SimState::new(RunSetup { auto_shoot: false, ..RunSetup::default() });
    state.wave_active = true;
    let mut enemy = Enemy::new(123, Vec2::new(state.room_radius - 30.0, 0.0), 1000, 100.0, "charger");
    enemy.ai.sub_state = EnemySubState::ChargerCharging;
    enemy.ai.charge_dir = Vec2::new(1.0, 0.0);
    enemy.ai.charge_target = Vec2::new(state.room_radius + 1000.0, 0.0);
    enemy.ai.state_timer = Some(0.1);
    state.enemies.push(enemy);
    for _ in 0..12 { step(&mut state, &SimInput::default(), 1.0 / 60.0); }
    assert_eq!(state.enemies[0].ai.sub_state, EnemySubState::ChargerCooldown);
    assert!(!state.enemies[0].ai.charger_dashing);
}

#[test]
fn explosive_weapons_keep_reload_windows_and_damage_nearby_targets() {
    use plouto_rs::sim::projectile::Projectile;
    use plouto_rs::sim::weapons::{get_effective_fire_rate, get_weapon};
    for (key, minimum, kind) in [("heavy", 0.70, "missile"), ("flak", 0.85, "flak")] {
        assert!(get_effective_fire_rate(&get_weapon(key), 0.01) >= minimum);
        let mut state = SimState::new(RunSetup { auto_shoot: false, ..RunSetup::default() });
        state.wave_active = true;
        for (id, x) in [(901, 120.0), (902, 175.0), (903, 310.0)] {
            let mut enemy = Enemy::new(id, Vec2::new(x, 0.0), 1000, 0.0, "egg_sac");
            enemy.ai.hatch_timer = 100.0;
            state.enemies.push(enemy);
        }
        let mut shell = Projectile::new(Vec2::new(100.0, 0.0), Vec2::new(600.0, 0.0), 100, 1.0, "player", kind);
        shell.cluster_on_death = kind == "flak";
        state.projectiles.push(shell);
        step(&mut state, &SimInput::default(), 1.0 / 60.0);
        let hp = |id| state.enemies.iter().find(|e| e.id == id).unwrap().hp;
        assert_eq!(hp(901), 900, "direct target must not receive splash twice: {kind}");
        assert!(hp(902) < 1000, "nearby target missed blast: {kind}");
        assert_eq!(hp(903), 1000, "blast escaped its radius: {kind}");
        assert!(state.shake <= 4.0, "shell shake stacked excessively: {kind}");
    }
}

#[test]
fn heavy_and_laser_firing_cadence_survives_stacked_fire_rate() {
    use plouto_rs::sim::state::SimEvent;
    use plouto_rs::sim::weapons::get_weapon;
    for (weapon, laser, minimum) in [("heavy", false, 0.70), ("flak", false, 0.85), ("rapid", true, 0.32)] {
        let mut state = SimState::new(RunSetup { auto_shoot: true, ..RunSetup::default() });
        state.wave_active = true;
        state.player.current_weapon = get_weapon(weapon);
        state.player.fire_rate = 0.01;
        if laser { state.player.laser_until = 100.0; }
        let mut last_shot = None;
        let mut count = 0;
        for _ in 0..180 {
            let events = step(&mut state, &SimInput { aim_world: Vec2::new(500.0, 0.0), ..SimInput::default() }, 1.0 / 60.0);
            if events.iter().any(|e| matches!(e, SimEvent::MuzzleFlash { .. })) {
                if let Some(previous) = last_shot {
                    assert!(state.time - previous >= minimum - 0.001, "{weapon}/laser={laser} fired before reload");
                }
                last_shot = Some(state.time);
                count += 1;
            }
        }
        assert!(count >= 2, "weapon stopped firing: {weapon}");
    }
}

#[test]
fn bomber_and_tank_require_windup_then_recovery() {
    use plouto_rs::sim::enemy::EnemySubState;
    for (behavior, x, windup, reload) in [
        ("bomber", 250.0, EnemySubState::BomberWindup, 2.7),
        ("tank", 110.0, EnemySubState::TankWindup, 1.8),
    ] {
        let mut state = SimState::new(RunSetup { auto_shoot: false, ..RunSetup::default() });
        state.wave_active = true;
        state.player.hp = 10000;
        state.enemies.push(Enemy::new(123, Vec2::new(x, 0.0), 10000, 0.0, behavior));
        step(&mut state, &SimInput::default(), 1.0 / 60.0);
        assert_eq!(state.enemies[0].ai.sub_state, windup);
        assert!(!state.projectiles.iter().any(|p| p.source == behavior));
        let mut fired = false;
        for _ in 0..60 {
            step(&mut state, &SimInput::default(), 1.0 / 60.0);
            if let Some(projectile) = state.projectiles.iter().find(|p| p.source == behavior) {
                if behavior == "bomber" {
                    let landing = projectile.pos + projectile.vel * projectile.ttl;
                    assert!(landing.length() < 1.0, "bomb fuse does not reach locked target: {landing:?}");
                }
                assert!(state.enemies[0].attack_cd >= reload);
                fired = true;
                break;
            }
        }
        assert!(fired, "{behavior} never completed its windup");
        state.projectiles.clear();
        for _ in 0..60 { step(&mut state, &SimInput::default(), 1.0 / 60.0); }
        assert!(!state.projectiles.iter().any(|p| p.source == behavior), "{behavior} skipped its recovery");
    }
}

#[test]
fn regular_enemy_roster_survives_a_live_ai_simulation() {
    use std::f32::consts::TAU;

    let behaviors = [
        "chaser",
        "ranged",
        "charger",
        "tank",
        "spitter",
        "flyer",
        "sniper",
        "engineer",
        "bomber",
        "swarm",
        "egg_sac",
    ];
    for map_type in ["circle", "donut", "cross", "diamond"] {
        for difficulty in ["easy", "normal", "hard"] {
            let mut setup = RunSetup {
                seed: 45,
                difficulty: difficulty.to_string(),
                map_type: map_type.to_string(),
                auto_shoot: false,
                ..RunSetup::default()
            };
            setup.runtime.enable_obstacles = false;
            let mut state = SimState::new(setup);
            state.wave = 10;
            state.wave_active = true;
            state.player.hp = 1_000_000;
            // The 11-enemy roster must leave room for hatch children: the non-boss spawn cap
            // (max_enemies, 10 on early waves) suppresses hatching by design when it is full.
            state.max_enemies = 20;
            let spawn_radius = state.room_radius * 0.64;
            for (index, behavior) in behaviors.iter().enumerate() {
                let angle = index as f32 * TAU / behaviors.len() as f32;
                let probe = Vec2::new(angle.cos() * spawn_radius, angle.sin() * spawn_radius);
                let position = clamp_entity_to_map(
                    probe,
                    state.room_radius,
                    SimState::enemy_radius_of(behavior) + 8.0,
                    map_type,
                );
                let mut enemy = Enemy::new(
                    45_100 + index as u64,
                    position,
                    10_000,
                    95.0,
                    behavior,
                );
                enemy.seed = angle;
                enemy.attack_cd = 0.1;
                if *behavior == "egg_sac" {
                    enemy.ai.hatch_timer = 4.0;
                }
                state.enemies.push(enemy);
            }

            let mut saw_hatched_swarm = false;
            for _ in 0..(6 * 60) {
                step(&mut state, &SimInput::default(), 1.0 / 60.0);
                saw_hatched_swarm |= state.enemies.iter()
                    .any(|enemy| enemy.behavior == "swarm" && enemy.id != 45_109);
            }

            for enemy in &state.enemies {
                assert!(
                    enemy.pos.x.is_finite() && enemy.pos.y.is_finite(),
                    "{} produced a non-finite position on {map_type}/{difficulty}",
                    enemy.behavior
                );
                assert!(
                    arena_inside(enemy.pos, state.room_radius, map_type),
                    "{} escaped {map_type}/{difficulty} at {:?}",
                    enemy.behavior,
                    enemy.pos
                );
            }
            let mut closest_body_gap = f32::INFINITY;
            for first in 0..state.enemies.len() {
                if state.enemies[first].is_dead || state.enemies[first].hp <= 0 {
                    continue;
                }
                for second in first + 1..state.enemies.len() {
                    if state.enemies[second].is_dead || state.enemies[second].hp <= 0 {
                        continue;
                    }
                    let gap = (state.enemies[first].pos - state.enemies[second].pos).length()
                        - state.enemies[first].radius
                        - state.enemies[second].radius;
                    closest_body_gap = closest_body_gap.min(gap);
                }
            }
            assert!(
                closest_body_gap >= 0.0,
                "mixed AI roster overlapped by {:.2} units on {map_type}/{difficulty}",
                -closest_body_gap
            );
            assert!(
                saw_hatched_swarm,
                "egg sac failed to hatch on {map_type}/{difficulty}; enemies={}, game_over={}, sac={:?}, roster={:?}",
                state.enemies.len(),
                state.game_over,
                state.enemies.iter().find(|enemy| enemy.behavior == "egg_sac").map(|enemy| (enemy.hp, enemy.ai.hatch_timer, enemy.is_dead)),
                state.enemies.iter().map(|e| (&e.behavior, e.id, e.pos)).collect::<Vec<_>>()
            );
        }
    }
}

#[test]
fn orbiting_auto_fire_bot_sweeps_all_difficulties() {
    let difficulties = ["easy", "normal", "hard"];
    for difficulty in difficulties {
        let setup = RunSetup {
            seed: 90_000,
            difficulty: (*difficulty).to_string(),
            auto_shoot: true,
            ..RunSetup::default()
        };
        let mut state = SimState::new(setup);
        let mut max_wave = state.wave;
        let mut boss_started_at: Option<f32> = None;
        let mut boss_fight_seconds = Vec::new();
        for frame in 0..(24_000usize) {
            if state.game_over {
                break;
            }
            let reward_choice = state.pending_boss_reward.as_ref().map(|offer| {
                (
                    offer.temp_options.first().copied(),
                    offer.perm_options.first().copied(),
                )
            });
            if let Some((temp_reward, perm_reward)) = reward_choice {
                if let Some(reward) = temp_reward {
                    apply_boss_temp_reward(&mut state, reward.key, reward.duration);
                }
                if let Some(reward) = perm_reward {
                    apply_boss_perm_reward(&mut state, reward.key);
                }
            }
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
                let approach_range = if state.player.current_weapon.projectile_type == "flak" {
                    175.0
                } else { 280.0 };
                (
                    enemy.pos + enemy.vel * (to_enemy.length()
                        / state.player.current_weapon.projectile_speed.max(1.0)).min(0.6),
                    if to_enemy.length() < 118.0 {
                        away * 0.8
                    } else {
                        Vec2::ZERO
                    },
                    if to_enemy.length() > approach_range {
                        to_enemy.normalized() * 0.85
                    } else {
                        Vec2::ZERO
                    },
                )
            } else {
                (
                    state.player.pos + Vec2::new(180.0, 0.0),
                    Vec2::ZERO,
                    Vec2::ZERO,
                )
            };
            let movement = (orbit * 0.78 + edge_steer + dodge + approach).normalized();
            let input = SimInput {
                move_dir: movement,
                aim_world,
                fire_held: true,
                dash_pressed: frame % 100 == 0 && frame > 0,
                ultra_pressed: state.player.ultra_charges > 0
                    && state.player.ultra_cd_until <= state.time,
                ..SimInput::default()
            };
            step(&mut state, &input, 1.0 / 60.0);
            let boss_alive = state.enemies.iter().any(|enemy| {
                enemy.is_boss() && !enemy.is_dead && enemy.hp > 0
            });
            match (boss_started_at, boss_alive) {
                (None, true) => boss_started_at = Some(state.time),
                (Some(started_at), false) => {
                    boss_fight_seconds.push((state.time - started_at).max(0.0));
                    boss_started_at = None;
                }
                _ => {}
            }
            max_wave = max_wave.max(state.wave);
        }

        println!(
            "{difficulty}: max_wave={max_wave}, time={:.1}s, game_over={}, hull={}, shield={}, damage={}, hits={}, bosses={}, boss_fights={:?}",
            state.time,
            state.game_over,
            state.player.hp,
            state.player.shield,
            state.run_stats.damage_taken,
            state.run_stats.hits_taken,
            state.run_stats.boss_kills,
            boss_fight_seconds,
        );
        let minimum_wave = match difficulty {
            "easy" => 12,
            "normal" => 10,
            _ => 8,
        };
        // Progress and a completed boss reward are the success criteria. A bot
        // that clears the target sector then dies must not fail just because
        // it did not also idle alive until an arbitrary 300-second cutoff.
        let minimum_time = 90.0;
        assert!(
            state.time > minimum_time,
            "{difficulty} simulation ended before the long-run balance check ({:.1}s < {minimum_time}s)",
            state.time
        );
        assert!(
            max_wave >= minimum_wave,
            "{difficulty} did not reach its late-wave simulation target (wave {max_wave}, expected {minimum_wave}); player={:?}, weapon={}, enemies={:?}",
            state.player.pos, state.player.current_weapon.name,
            state.enemies.iter().map(|e| (&e.behavior, e.hp, e.pos)).collect::<Vec<_>>()
        );
        assert!(state.run_stats.boss_kills >= 1, "{difficulty} did not finish and resume after a boss reward");
        assert!(state.player.hp > -10_000, "{difficulty} damage accounting overflowed");
    }
}

#[test]
fn every_boss_reaches_phase_three_and_uses_its_moveset() {
    use plouto_rs::sim::enemy::EnemySubState;

    let bosses = [
        "boss_thunder",
        "boss_laser",
        "boss_trapmaster",
        "boss_swarmqueen",
        "boss_brute",
        "boss_abyss_gaze",
        "boss_womb_core",
        "boss_eclipse_archon",
    ];

    for (index, behavior) in bosses.iter().enumerate() {
        let setup = RunSetup {
            seed: 10_000 + index as u64,
            difficulty: "normal".to_string(),
            auto_shoot: false,
            ..RunSetup::default()
        };
        let mut state = SimState::new(setup);
        state.wave = 10;
        state.wave_active = true;
        state.player.hp = 1_000_000;
        state.player.pos = Vec2::new(-210.0, 110.0);
        let mut boss = Enemy::new(70_000 + index as u64, Vec2::new(280.0, -40.0), 3_000, 70.0, behavior);
        boss.max_hp = 3_000;
        boss.attack_cd = 0.0;
        state.enemies.push(boss);

        let mut saw_attack = false;
        let mut phase_two_attack = false;
        let mut phase_three_attack = false;
        let mut phase_banners = 0;
        for frame in 0..(45 * 60) {
            if frame == 15 * 60 {
                state.enemies[0].hp = 1_920;
            } else if frame == 30 * 60 {
                state.enemies[0].hp = 900;
            }
            if frame == 15 * 60 || frame == 30 * 60 {
                // Remove the previous phase's lingering hazards and summons so
                // the next assertion proves that the new phase attacks too.
                state.projectiles.clear();
                state.traps.clear();
                state.lasers.clear();
                state.thunders.clear();
                state.enemies.retain(|enemy| enemy.is_boss());
            }
            let events = step(&mut state, &SimInput::default(), 1.0 / 60.0);
            let active_attack = !state.projectiles.is_empty()
                || !state.traps.is_empty()
                || !state.lasers.is_empty()
                || !state.thunders.is_empty()
                || state.enemies.len() > 1
                // The Juggernaut's core attack is a telegraphed charge. It may
                // not hit a wall in this fixture, so its committed attack state
                // is also evidence of an active move.
                || matches!(
                    state.enemies[0].ai.sub_state,
                    EnemySubState::BruteTelegraph | EnemySubState::BruteCharge
                );
            saw_attack |= active_attack;
            phase_two_attack |= state.enemies[0].ai.phase >= 1 && active_attack;
            phase_three_attack |= state.enemies[0].ai.phase >= 2 && active_attack;
            phase_banners += events
                .iter()
                .filter(|event| matches!(event, SimEvent::Banner { title, subtitle, .. } if title == "PHASE II" || title == "PHASE III" || subtitle.contains("PHASE II PATTERN") || subtitle.contains("PHASE III PATTERN")))
                .count();
        }

        assert!(saw_attack, "{behavior} did not produce a visible attack or summon");
        assert!(phase_two_attack, "{behavior} did not attack during phase II");
        assert!(phase_three_attack, "{behavior} did not attack during phase III");
        assert_eq!(state.enemies[0].ai.phase, 2, "{behavior} did not reach phase III");
        assert_eq!(phase_banners, 2, "{behavior} should announce both pattern shifts");
        assert!(
            state.enemies[0].pos.x.is_finite() && state.enemies[0].pos.y.is_finite(),
            "{behavior} movement produced a non-finite position"
        );
    }
}

#[test]
fn test_boss_wave_rewards_weapons_and_specials() {
    let mut setup = RunSetup {
        seed: 777,
        difficulty: "hard".to_string(),
        map_type: "diamond".to_string(),
        skin_id: "obsidian".to_string(),
        ..RunSetup::default()
    };
    setup.runtime.enable_obstacles = true;
    let mut state = SimState::new(setup);

    // Jump to wave 5 boss clear and verify reward rolling & application
    state.wave = 5;
    state.enemies.clear();
    let spawned = spawn_wave_enemies(
        state.wave,
        &state.difficulty,
        &state.map_type,
        state.room_radius,
        state.max_enemies,
        &state.rules,
        state.player.pos,
        &mut state.next_entity_id,
        &mut state.rng,
    );
    assert!(spawned.enemies.iter().any(|e| e.is_boss()), "wave 5 must spawn a boss");

    // Simulate wave 5 cleared cleanly
    state.wave_active = true;
    state.enemies.clear();
    let events = step(&mut state, &SimInput::default(), 1.0 / 60.0);
    assert!(events.iter().any(|e| matches!(e, SimEvent::BossRewardOpened)));
    let offer = state.pending_boss_reward.clone().expect("boss reward offer missing");
    assert!(!offer.temp_options.is_empty());
    assert!(!offer.perm_options.is_empty());

    let temp_key = offer.temp_options[0].key;
    let temp_dur = offer.temp_options[0].duration;
    let perm_key = offer.perm_options[0].key;
    apply_boss_temp_reward(&mut state, temp_key, temp_dur);
    apply_boss_perm_reward(&mut state, perm_key);
    assert!(state.pending_boss_reward.is_none());
    assert!(state.active_temp_rewards.iter().any(|r| r.key == temp_key));
    assert!(state.run_permanent_rewards.iter().any(|p| p == perm_key));
    let _ = (TEMP_REWARD_POOL.len(), PERM_REWARD_POOL.len());

    // Test all 7 weapons fire cleanly without panic
    let all_weapons = ["basic", "spread", "plasma", "missile", "railgun", "flak", "laser"];
    for wkey in all_weapons {
        let w = get_weapon(wkey);
        state.player.current_weapon = w;
        state.player.last_shot = -10.0;
        state.player.next_shot_time = 0.0;
        let aim = SimInput {
            aim_world: Vec2::new(200.0, 0.0),
            fire_held: true,
            ..SimInput::default()
        };
        step(&mut state, &aim, 1.0 / 60.0);
    }

    // Test Repulsor, Chain, Echo, Vortex, Afterburn, Shards
    state.enemies.clear();
    let target = Enemy::new(8801, Vec2::new(REPULSOR_RANGE * 0.5, 0.0), 10, 0.0, "chaser");
    state.enemies.push(target);
    let chain_target = Enemy::new(8802, Vec2::new(REPULSOR_RANGE * 0.6, 25.0), 10, 0.0, "chaser");
    state.enemies.push(chain_target);

    state.powerups.push(PowerUp::new(state.player.pos, "repulsor", None));
    state.powerups.push(PowerUp::new(state.player.pos, "chain", None));
    state.powerups.push(PowerUp::new(state.player.pos, "vortex", None));
    let step_events = step(&mut state, &SimInput::default(), 1.0 / 60.0);
    assert!(step_events.iter().any(|e| matches!(e, SimEvent::RepulsorBlast { .. })));

    let mut ab = AfterburnSystem::new();
    ab.maybe_drop(Vec2::new(10.0, 0.0), 1.0);
    assert!(!ab.segments.is_empty());

    // Ultra variants
    for variant_idx in 0..3usize {
        state.hitstop = 0.0;
        state.player.ultra_variant_idx = variant_idx;
        state.player.ultra_charges = 1;
        state.player.ultra_cd_until = 0.0;
        let evs = step(
            &mut state,
            &SimInput {
                ultra_pressed: true,
                aim_world: Vec2::new(100.0, 0.0),
                ..SimInput::default()
            },
            1.0 / 60.0,
        );
        assert!(evs.iter().any(|e| matches!(e, SimEvent::UltraFlash { .. })));
    }
}

#[test]
fn origin_nexus_pulse_state_matches_floor_warning_duration() {
    use plouto_rs::sim::behaviors::{AttackScheduler, BehaviorContext};
    use plouto_rs::sim::bosses::update_boss_enemy;
    use plouto_rs::sim::enemy::{EnemySubState, WOMB_PULSE_TELEGRAPH};
    use plouto_rs::sim::rng::SimRng;

    let mut boss = Enemy::new(9901, Vec2::ZERO, 100, 80.0, "boss_womb_core");
    boss.ai.boss_initialized = true;
    boss.ai.boss_max_hp = 100;
    boss.attack_cd = 0.01;
    let mut rng = SimRng::new(9901);
    let mut next_id = 10000;
    let mut projectiles = Vec::new();
    let mut traps = Vec::new();
    let mut lasers = Vec::new();
    let mut swarm_brain = None;
    let mut queued_spawns = Vec::new();
    let mut attack_scheduler = AttackScheduler::for_enemies(std::slice::from_ref(&boss));
    let mut context = BehaviorContext {
        player_pos: Vec2::new(100.0, 0.0),
        player_vel: Vec2::ZERO,
        dt: 1.0 / 60.0,
        enemy_time: 0.0,
        wave: 5,
        room_radius: 600.0,
        map_type: "circle",
        next_id: &mut next_id,
        rng: &mut rng,
        enemy_snaps: &[],
        swarm_snaps: &[],
        spawn_snaps: &[],
        live_non_boss_count: 0,
        non_boss_spawn_cap: 60,
        obstacles: &[],
        projectiles: &mut projectiles,
        traps: &mut traps,
        lasers: &mut lasers,
        swarm_brain: &mut swarm_brain,
        queued_spawns: &mut queued_spawns,
        attack_scheduler: &mut attack_scheduler,
    };
    let mut thunders = Vec::new();
    update_boss_enemy(&mut boss, &mut context, "normal", 60, 1, 0, 0, &mut thunders);
    assert_eq!(boss.ai.sub_state, EnemySubState::WombPulseTelegraph);
    assert!((boss.ai.sub_timer - WOMB_PULSE_TELEGRAPH).abs() < 1e-5);
    assert!(context.traps.iter().any(|trap| trap.kind == "womb_warn" && (trap.armed_delay - WOMB_PULSE_TELEGRAPH).abs() < 1e-5));

    context.dt = 0.5;
    update_boss_enemy(&mut boss, &mut context, "normal", 60, 1, 0, 0, &mut thunders);
    assert_eq!(boss.ai.sub_state, EnemySubState::WombPulseTelegraph);
    assert!((boss.ai.sub_timer - (WOMB_PULSE_TELEGRAPH - 0.5)).abs() < 1e-5);

    context.dt = 0.03;
    update_boss_enemy(&mut boss, &mut context, "normal", 60, 1, 0, 0, &mut thunders);
    assert_eq!(boss.ai.sub_state, EnemySubState::None);
}

#[test]
fn test_daily_and_mutators() {
    let date = normalise_date("2026-04-14").unwrap();
    let s1 = daily_seed(&date);
    let s2 = daily_seed("2026-04-14");
    assert_eq!(s1, s2);
    assert_ne!(daily_seed("2026-04-15"), s1);
    let mut_id = daily_mutator(&date).unwrap();
    assert!(MUTATORS.iter().any(|m| m.id == mut_id));
    let challenge_a = challenge_for_date(&date).unwrap();
    let challenge_b = challenge_for_date("2026-04-14").unwrap();
    assert_eq!(challenge_a, challenge_b);
    assert_eq!(challenge_a.seed, s1.unwrap());
    assert_eq!(challenge_a.mutator_id, mut_id);
    assert_eq!(challenge_a.difficulty, DAILY_DIFFICULTY);
    assert_eq!(challenge_a.map_type, DAILY_MAP_TYPE);
    assert_eq!(DAILY_DIFFICULTY, "normal");
    assert_eq!(DAILY_MAP_TYPE, "circle");
    assert!(DAILY_ARENA_MARGIN.is_finite());
    assert!(is_daily_run(Some("2026-04-14")));
    assert!(!is_daily_run(Some("not-a-date")));

    let sel = normalize_selection(["frenzy", "glass_cannon", "frenzy"]);
    assert_eq!(sel.len(), 2);
    let rules = apply_mutators(&sel);
    assert!(rules.player_damage_mult > 1.0);
    assert!(rules.enemy_speed_mult > 1.0);
    let mult = combined_score_multiplier(&sel);
    assert!(mult > 1.0);
    assert!(!format_score_mult(mult).is_empty());
}

#[test]
fn boss_reward_offers_always_show_three_reward_categories() {
    let player = Player::new(Vec2::ZERO, 100);
    for seed in 0..128 {
        let mut rng = SimRng::new(seed);
        let (temps, perms) = roll_boss_rewards(
            &[],
            "",
            "",
            &player,
            1.0,
            &[],
            &mut rng,
        );
        assert_eq!(temps.len(), 3, "seed {seed} returned fewer than 3 temp boons");
        assert_eq!(perms.len(), 3, "seed {seed} returned fewer than 3 run upgrades");
        assert_eq!(
            temps.iter().map(|reward| reward_category(reward.key)).collect::<std::collections::BTreeSet<_>>().len(),
            3,
            "seed {seed} offered duplicate temporary-boon categories"
        );
        assert_eq!(
            perms.iter().map(|reward| reward_category(reward.key)).collect::<std::collections::BTreeSet<_>>().len(),
            3,
            "seed {seed} offered duplicate run-upgrade categories"
        );
    }
}

#[test]
fn repeatable_run_upgrades_track_their_stacks_and_temp_rewards_validate_keys() {
    let mut player = Player::new(Vec2::ZERO, 100);
    let base_damage = player.damage;
    let mut run_rewards = Vec::new();
    let mut dash_cd_mult = 1.0;
    assert!(apply_perm_reward(
        &mut player,
        &mut run_rewards,
        "perm_damage",
        &mut dash_cd_mult,
    ));
    assert!(apply_perm_reward(
        &mut player,
        &mut run_rewards,
        "perm_damage",
        &mut dash_cd_mult,
    ));
    assert_eq!(player.damage, base_damage + 2);
    assert_eq!(
        run_rewards,
        vec!["perm_damage".to_string(), "perm_damage".to_string()]
    );
    assert_eq!(format_perm_hud(&run_rewards), "Build Core Damage x2");

    let mut active = Vec::new();
    assert!(!apply_temp_reward(&mut active, "not_a_reward", 3));
    assert!(active.is_empty());
    assert!(apply_temp_reward(&mut active, "temp_overdrive", 99));
    assert_eq!(active[0].waves_left, 2, "reward duration must not exceed its definition");
    assert!(apply_temp_reward(&mut active, "TEMP_OVERDRIVE", 1));
    assert_eq!(active[0].waves_left, 2, "reapplying a shorter boon must preserve its remaining duration");
}

#[test]
fn every_temporary_and_permanent_boss_reward_changes_the_expected_run_state() {
    let all_temp_rewards: Vec<_> = TEMP_REWARD_POOL
        .iter()
        .map(|reward| ActiveTempReward {
            key: reward.key.to_string(),
            waves_left: reward.duration,
            duration: reward.duration,
        })
        .collect();
    let mods = recompute_temp_mods(&all_temp_rewards);
    assert_near(mods.damage, 1.28, 1e-5);
    assert_near(mods.speed, 1.22 * 1.25, 1e-5);
    assert_near(mods.fire_rate, 0.78, 1e-5);
    assert_near(mods.magnet, 80.0, 1e-5);
    assert_near(mods.incoming_damage, 0.82, 1e-5);
    assert_near(mods.ultra_cd, 0.70, 1e-5);
    assert_near(mods.crit_chance, 0.25, 1e-5);
    assert_near(mods.crit_mult, 0.50, 1e-5);
    assert!(mods.boost_inf);

    let mut player = Player::new(Vec2::ZERO, 100);
    player.hp = 90;
    player.boost_energy = 75.0;
    let (base_damage, base_speed, base_fire) = (player.damage, player.speed, player.fire_rate);
    let (base_ultra_max, base_ultra) = (player.ultra_max_charges, player.ultra_charges);
    let mut run_rewards = Vec::new();
    let mut dash_cd_mult = 1.0;
    for key in [
        "perm_damage",
        "perm_speed",
        "perm_hp",
        "perm_fire",
        "perm_shield",
        "perm_ultra",
        "perm_dash",
        "perm_double_dash",
        "perm_boost_cap",
        "perm_crit",
    ] {
        assert!(apply_perm_reward(
            &mut player,
            &mut run_rewards,
            key,
            &mut dash_cd_mult,
        ), "{key} should apply");
    }
    for key in [
        "relic_graviton",
        "relic_soul_rivet",
        "relic_phase_shard",
        "relic_aegis_relay",
    ] {
        assert!(apply_perm_reward(
            &mut player,
            &mut run_rewards,
            key,
            &mut dash_cd_mult,
        ), "{key} should apply");
    }
    assert_eq!(player.damage, base_damage + 1);
    assert_near(player.speed, base_speed + 6.0, 1e-5);
    assert_eq!((player.max_hp, player.hp), (106, 96));
    assert_near(player.fire_rate, base_fire - 0.006, 1e-5);
    assert_eq!(player.shield, 18);
    assert_eq!(player.ultra_max_charges, (base_ultra_max + 1).min(ULTRA_MAX_CHARGES_HARD_CAP));
    assert_eq!(player.ultra_charges, (base_ultra + 1).min(player.ultra_max_charges));
    assert_near(dash_cd_mult, 0.90, 1e-5);
    assert_eq!((player.dash_max_charges, player.dash_charges), (2, 2));
    assert_near(player.boost_max_energy, 130.0, 1e-5);
    assert_near(player.boost_energy, 105.0, 1e-5);
    assert_near(player.crit_chance_bonus, 0.10, 1e-5);
    assert_near(player.crit_mult_bonus, 0.40, 1e-5);
    assert_eq!(run_rewards.iter().filter(|key| key.starts_with("relic_")).count(), 4);
}

#[test]
fn boss_reward_pool_omits_owned_relics_and_capped_upgrades() {
    let mut player = Player::new(Vec2::ZERO, 100);
    player.shield = SHIELD_MAX;
    player.ultra_max_charges = ULTRA_MAX_CHARGES_HARD_CAP;
    player.dash_max_charges = 2;
    player.fire_rate = plouto_rs::sim::rpg::FIRE_RATE_FLOOR;
    let run_rewards = vec![
        "relic_graviton".to_string(),
        "relic_soul_rivet".to_string(),
        "relic_phase_shard".to_string(),
        "relic_aegis_relay".to_string(),
    ];
    let mut rng = SimRng::new(991);
    let (_, offer) = roll_boss_rewards(
        &[],
        "",
        "",
        &player,
        plouto_rs::sim::rpg::DASH_CD_FLOOR,
        &run_rewards,
        &mut rng,
    );
    for unavailable in [
        "perm_fire",
        "perm_shield",
        "perm_ultra",
        "perm_dash",
        "perm_double_dash",
        "relic_graviton",
        "relic_soul_rivet",
        "relic_phase_shard",
        "relic_aegis_relay",
    ] {
        assert!(
            offer.iter().all(|reward| reward.key != unavailable),
            "capped or owned reward {unavailable} was offered"
        );
    }
}

/// One settled daily run through the single-write `end_run` path.
fn settle_day(path: &std::path::Path, date: &str, score: i32, wave: i32) -> plouto_rs::sim::daily::DailyResult {
    let mut run = RunStats::new();
    run.finish(score, wave, 0.0, None);
    let ctx = RunContext {
        daily_date: Some(date.to_string()),
        mutators: Vec::new(),
    };
    end_run(&run, &ctx, path)
        .daily
        .expect("daily result for a valid date")
}

#[test]
fn test_save_persistence_quarantine_migration_and_progression() {
    let dir = tempdir().unwrap();

    // 1) Corrupt JSON quarantine
    let bad_path = dir.path().join("progress.json");
    fs::write(&bad_path, b"{ not valid json !!!").unwrap();
    let loaded = load_progress(&bad_path);
    assert_eq!(loaded.runs_played, 0);
    assert!(!bad_path.exists(), "corrupt file should be moved aside");
    assert!(dir.path().join("progress.json.corrupt-1").exists());

    // 2) Unknown keys + forward version + UTF-8 BOM + progress end_run + daily
    let bom_json = "\u{FEFF}{\"version\":99,\"best_wave\":2,\"unknown_future\":\"keep-me\"}";
    fs::write(&bad_path, bom_json.as_bytes()).unwrap();
    let mut run = RunStats::new();
    for _ in 0..55 {
        run.on_kill(false, false, 3.0);
    }
    run.on_kill(true, true, 3.5);
    run.on_wave_clear();
    run.finish(125_000, 12, 420.0, Some(5.2));
    let summary = end_run(&run, &RunContext::default(), &bad_path);
    assert!(summary.saved);
    assert!(summary.progress.version >= 99);
    assert_eq!(summary.progress.extra.get("unknown_future"), Some(&json!("keep-me")));
    assert_eq!(summary.progress.best_score, 125_000);
    assert!(skin_is_unlocked(&summary.progress, "obsidian"));
    assert!(summary.progress.achievements.iter().any(|a| a == "giant_slayer"));

    // Daily settle tie vs strictly higher
    let r1 = settle_day(&bad_path, "2026-04-14", 0, 1);
    assert!(r1.changed && r1.new_best);
    let r2 = settle_day(&bad_path, "2026-04-14", 0, 2);
    assert!(r2.changed && r2.new_best, "equal score with a farther wave should replace the daily record");
    assert_eq!(best_for_date(&load_progress(&bad_path), "2026-04-14"), Some((0, 2)));
    let r3 = settle_day(&bad_path, "2026-04-14", 5000, 5);
    assert!(r3.changed && r3.new_best);
    assert_eq!(best_for_date(&load_progress(&bad_path), "2026-04-14"), Some((5000, 5)));

    // ensure_progress_file does not overwrite existing file
    assert!(!ensure_progress_file(&bad_path));
    let p2 = dir.path().join("fresh_progress.json");
    assert!(ensure_progress_file(&p2));
    let mut mod_p = load_progress(&p2);
    mod_p.selected_skin = "frost".to_string();
    assert!(save_progress(&p2, &mod_p));
    assert_eq!(load_progress(&p2).selected_skin, "frost");

    // 3) Settings v0 -> v1 migration (reduced_shake -> shake_level) & unknown key preservation
    let settings_path = dir.path().join("user_settings.json");
    fs::write(
        &settings_path,
        r#"{"music_volume":0.35,"sfx_volume":0.95,"reduced_shake":true,"custom_flag":42}"#,
    )
    .unwrap();
    let mut cfg = load_settings(&settings_path);
    assert_near(cfg.music_volume, 0.35, 1e-4);
    assert_near(cfg.sfx_volume, 0.95, 1e-4);
    assert_eq!(cfg.shake_level, "reduced");
    assert_eq!(cfg.extra.get("custom_flag"), Some(&json!(42)));

    cfg.shake_level = "off".to_string();
    cfg.reduced_motion = true;
    assert!(save_settings(&settings_path, &cfg));
    let raw_saved: Value =
        serde_json::from_str(&fs::read_to_string(&settings_path).unwrap()).unwrap();
    assert_eq!(raw_saved["version"], json!(PROGRESS_VERSION));
    assert_eq!(raw_saved["shake_level"], json!("off"));
    assert_eq!(raw_saved["reduced_shake"], json!(true));
    assert_eq!(raw_saved["custom_flag"], json!(42));

    assert!(update_settings_keys(
        &settings_path,
        &[("sfx_volume".to_string(), json!(0.6))]
    ));
    let reloaded = load_settings(&settings_path);
    assert_near(reloaded.sfx_volume, 0.6, 1e-4);
    assert!(reloaded.reduced_motion);

    // 4) High scores sorting, top 5 truncation, tie ranking
    let scores_path = dir.path().join("high_scores.json");
    for s in [100, 500, 300, 200, 400, 50] {
        let mut t = ScoreTracker::new("normal", 1.0);
        t.score = s;
        let out = submit_score(&scores_path, &mut t, 5, Some("2026-04-14 10:00"));
        assert!(out.saved);
    }
    assert_eq!(top_score(&scores_path, "normal"), 500);
    let board = load_high_scores(&scores_path);
    assert_eq!(board.boards["normal"].len(), 5);
    let mut tie = ScoreTracker::new("normal", 1.0);
    tie.score = 500;
    let tie_out = submit_score(&scores_path, &mut tie, 6, Some("2026-04-14 10:01"));
    assert!(!tie_out.is_new_best);
    assert_eq!(tie_out.rank, 2, "tie must rank behind existing #1");
    assert_eq!(tie_out.points_to_next, Some(1));

    // atomic_write_json + explicit quarantine helper sanity
    let q_target = dir.path().join("explicit.json");
    fs::write(&q_target, b"bad").unwrap();
    let q_res = quarantine(&q_target).expect("quarantine path");
    assert!(q_res.exists());
    let mut m = serde_json::Map::new();
    m.insert("ok".to_string(), json!(true));
    assert!(atomic_write_json(&dir.path().join("atomic.json"), &m));
}

#[test]
fn test_audio_cues_and_asset_paths() {
    let audio_dir = resolve_asset("assets/audio").expect("assets/audio should resolve");
    assert!(audio_dir.join("music_menu.wav").is_file());
    assert!(audio_dir.join("music_battle.wav").is_file());
    for &(cue_name, _, _, _) in CUE_SPECS {
        assert!(
            audio_dir.join(format!("sfx_{cue_name}.wav")).is_file(),
            "missing wav for cue {cue_name}"
        );
    }

    assert!(resolve_asset("assets/fonts/Orbitron-Variable.ttf").is_some());
    assert!(resolve_asset("assets/fonts/Rajdhani-Regular.ttf").is_some());
    assert!(resolve_asset("assets/fonts/Rajdhani-SemiBold.ttf").is_some());
    assert!(resolve_asset("laser-gun_38685.ico").is_some());

    let mut mgr = AudioManager::new_silent(0.8, 0.5);
    mgr.set_volumes(Some(1.5), Some(-0.2));
    assert_near(mgr.music_volume, 1.0, 1e-6);
    assert_near(mgr.sfx_volume, 0.0, 1e-6);
    mgr.cue("ricochet", 1.0);
    mgr.play_pickup("magnet", true);
    mgr.play_elite_death("splitter");
    mgr.play_music(Some("menu"), 0.5);
    mgr.duck(0.35, 0.25);
    mgr.update(1.0 / 60.0);
}

#[test]
fn wave_spawns_keep_clearance_across_all_arena_shapes() {
    const MAPS: [&str; 4] = ["circle", "donut", "cross", "diamond"];

    for map_type in MAPS {
        let mut setup = RunSetup {
            map_type: map_type.to_string(),
            ..RunSetup::default()
        };
        setup.runtime.enable_obstacles = false;
        let arena = SimState::new(setup);
        let edge_positions = [
            Vec2::new(0.0, -arena.room_radius * 2.0),
            Vec2::new(arena.room_radius * 2.0, 0.0),
            Vec2::new(0.0, arena.room_radius * 2.0),
            Vec2::new(-arena.room_radius * 2.0, 0.0),
        ]
        .map(|pos| clamp_entity_to_map(pos, arena.room_radius, 48.0, map_type));
        let mut player_positions = vec![arena.player.pos];
        player_positions.extend(edge_positions);

        for wave in 1..=20 {
            for seed in 0..8_u64 {
                for (player_index, player_pos) in player_positions.iter().copied().enumerate() {
                    let mut rng = SimRng::new(
                        seed + (wave as u64 * 100) + (player_index as u64 * 10_000),
                    );
                    let mut next_id = 1;
                    let spawned = spawn_wave_enemies(
                        wave,
                        "normal",
                        map_type,
                        arena.room_radius,
                        arena.max_enemies,
                        &arena.rules,
                        player_pos,
                        &mut next_id,
                        &mut rng,
                    );

                    for (index, enemy) in spawned.enemies.iter().enumerate() {
                        assert!(
                            arena_inside(enemy.pos, arena.room_radius, map_type),
                            "wave {wave} spawned {} outside {map_type}: {:?}",
                            enemy.behavior,
                            enemy.pos
                        );
                        let player_gap = (arena.room_radius * 0.34)
                            .max(enemy.radius + 36.0)
                            .min(arena.room_radius * 0.72);
                        assert!(
                            (enemy.pos - player_pos).length() >= player_gap - 0.01,
                            "wave {wave} spawned {} too close to the player on {map_type}",
                            enemy.behavior
                        );
                        for other in &spawned.enemies[..index] {
                            let required_gap = enemy.radius + other.radius + 10.0;
                            assert!(
                                (enemy.pos - other.pos).length() >= required_gap - 0.01,
                                "wave {wave} spawned overlapping {} and {} on {map_type}",
                                enemy.behavior,
                                other.behavior
                            );
                        }
                    }
                }
            }
        }
    }
}
