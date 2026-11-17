use std::f32::consts::{PI, TAU};

use plouto_rs::render::models3d::draw_boss_model;
use plouto_rs::render::sdf::{linear_rgba_f, SdfBatch};
use plouto_rs::render::text::TextBatch;
use plouto_rs::render::world::WorldRenderer;
use plouto_rs::sim::bosses::{
    eclipse_safe_angle, eclipse_safe_step_rad, ECLIPSE_GAP_HALF_WIDTH, TRAPMASTER_SPIKE_RADIUS,
};
use plouto_rs::sim::config::{
    BOSS_RAGE_EXTRA_PROJECTILES, MAX_ACTIVE_CONSTRUCTIONS, REPULSOR_RANGE,
};
use plouto_rs::sim::enemy::{
    BossPersona, Enemy, EnemySubState, ABYSS_GAZE_TELEGRAPH, SWARMQUEEN_TELEGRAPH,
    WOMB_PULSE_TELEGRAPH,
};
use plouto_rs::sim::hazards::Trap;
use plouto_rs::sim::level::enemy_stats;
use plouto_rs::sim::math::{to_iso_cam, Vec2};
use plouto_rs::sim::replay::{
    replay_and_verify, state_hash, Recorder, SIMULATION_RULES_VERSION,
};
use plouto_rs::sim::state::{RunSetup, SimEvent, SimInput, SimState};
use plouto_rs::sim::step::step;

const DT: f32 = 1.0 / 60.0;

const ALL_BOSSES: [&str; 8] = [
    "boss_thunder",
    "boss_laser",
    "boss_trapmaster",
    "boss_swarmqueen",
    "boss_brute",
    "boss_abyss_gaze",
    "boss_womb_core",
    "boss_eclipse_archon",
];

#[test]
fn chain_lightning_renders_during_a_boss_attack_without_overflow() {
    let mut state = new_boss_arena("circle", "normal", vec![], 1201);
    spawn_boss(&mut state, "boss_laser", Vec2::new(180.0, 0.0), 3_000, 75.0);
    state.enemies[0].ai.sub_state = EnemySubState::LaserAttack;
    state.chain.spawn_arc(Vec2::ZERO, Vec2::new(180.0, 0.0), state.time);
    let (alpha, add) = render_world(&state);
    assert!(!alpha.instances.is_empty());
    assert!(!add.instances.is_empty());
}

#[test]
fn prisma_overlord_stops_its_beams_when_the_sweep_finishes() {
    for time_slow in [false, true] {
        let mut state = new_boss_arena("circle", "normal", vec![], 1202);
        spawn_boss(&mut state, "boss_laser", Vec2::new(180.0, 0.0), 800, 75.0);
        let boss = &mut state.enemies[0];
        boss.ai.boss_initialized = true;
        boss.ai.boss_max_hp = 3000;
        boss.ai.phase = 2;
        boss.ai.sub_state = EnemySubState::LaserAttack;
        boss.ai.sub_timer = DT * 1.2;
        boss.ai.charge_dir = Vec2::new(-1.0, 0.0);
        if time_slow { state.player.time_slow_until = 10.0; }
        let mut saw_beam = false;
        for _ in 0..20 {
            step(&mut state, &SimInput::default(), DT);
            if state.enemies[0].ai.sub_state == EnemySubState::LaserWingWindup {
                assert!(saw_beam, "must exercise the live beam before it ends");
                assert!(!state.lasers.iter().any(|b| b.source == "boss_laser"),
                    "the sweep must not keep damaging the player during the fan warning");
                break;
            }
            saw_beam |= state.lasers.iter().any(|b| b.source == "boss_laser");
        }
        assert_eq!(state.enemies[0].ai.sub_state, EnemySubState::LaserWingWindup);
    }
}

fn new_boss_arena(map_type: &str, difficulty: &str, mutator_ids: Vec<String>, seed: u64) -> SimState {
    let setup = RunSetup {
        seed,
        difficulty: difficulty.to_string(),
        map_type: map_type.to_string(),
        mutator_ids,
        auto_shoot: false,
        ..RunSetup::default()
    };
    let mut state = SimState::new(setup);
    state.wave = 10;
    state.wave_active = true;
    state.player.hp = 1_000_000;
    state.player.max_hp = 1_000_000;
    state.player.pos = Vec2::new(-220.0, 90.0);
    state
}

fn spawn_boss(state: &mut SimState, behavior: &str, pos: Vec2, hp: i32, speed: f32) -> u64 {
    let id = state.next_entity_id;
    state.next_entity_id += 1;
    let mut boss = Enemy::new(id, pos, hp, speed, behavior);
    boss.max_hp = hp;
    boss.attack_cd = 0.0;
    state.enemies.push(boss);
    id
}

fn color_matches(actual: [f32; 4], expected: [f32; 4], tol: f32) -> bool {
    (actual[0] - expected[0]).abs() <= tol
        && (actual[1] - expected[1]).abs() <= tol
        && (actual[2] - expected[2]).abs() <= tol
}

fn render_world(state: &SimState) -> (SdfBatch, SdfBatch) {
    let mut renderer = WorldRenderer::new();
    let mut wa = SdfBatch::with_capacity(512);
    let mut wadd = SdfBatch::with_capacity(512);
    let mut uia = SdfBatch::with_capacity(128);
    let mut uit = TextBatch::default();
    renderer.draw_world(
        state,
        1.0,
        980.0,
        620.0,
        Vec2::new(1.0, 0.0),
        None,
        false,
        &mut wa,
        &mut wadd,
        &mut uia,
        &mut uit,
        1.0,
    );
    (wa, wadd)
}

#[test]
fn all_bosses_set_velocity_when_moving() {
    for (idx, behavior) in ALL_BOSSES.iter().enumerate() {
        let mut state = new_boss_arena("circle", "normal", vec![], 100 + idx as u64);
        // Place player far enough to trigger stalk/chase/orbit/approach movement.
        state.player.pos = Vec2::new(-320.0, 140.0);
        let id = spawn_boss(&mut state, behavior, Vec2::new(280.0, -110.0), 4_000, 85.0);

        let mut saw_motion = false;
        let mut saw_stationary_zero_vel = false;
        for _ in 0..360 {
            let prev_sub = state
                .enemies
                .iter()
                .find(|e| e.id == id)
                .unwrap()
                .ai
                .sub_state;
            step(&mut state, &SimInput::default(), DT);
            let boss = state.enemies.iter().find(|e| e.id == id).expect("boss alive");
            let delta = boss.pos - boss.prev_pos;
            let disp = delta.length();
            if disp > 0.05 {
                saw_motion = true;
                // On a state transition step (e.g. ThunderStalk -> ThunderTeleportOut,
                // LaserMoving -> LaserCharge, BruteCharge -> BruteStun), the boss
                // moves and then zeroes `vel` for the new stationary state.
                if boss.ai.sub_state == prev_sub {
                    assert!(
                        boss.vel.length() > 1e-3,
                        "{behavior} moved by {disp:.4} in {:?} without setting non-zero vel",
                        boss.ai.sub_state
                    );
                    let dot = delta.normalized().dot(boss.vel.normalized());
                    assert!(
                        dot > 0.90,
                        "{behavior} vel direction {:?} disagreed with displacement {:?} (dot={dot:.3})",
                        boss.vel,
                        delta
                    );
                }
            } else if boss.vel.length_squared() <= 1e-6 {
                saw_stationary_zero_vel = true;
            }
        }
        assert!(saw_motion, "{behavior} never moved during 6s simulation");
        if matches!(
            *behavior,
            "boss_thunder" | "boss_laser" | "boss_brute" | "boss_eclipse_archon"
        ) {
            assert!(
                saw_stationary_zero_vel,
                "{behavior} should explicitly zero velocity during stationary attack/telegraph states"
            );
        }
    }
}

#[test]
fn boss_summoned_adds_inherit_difficulty_frenzy_and_spawn_cooldown() {
    let mut easy = new_boss_arena("circle", "easy", vec![], 201);
    let mut hard_frenzy = new_boss_arena("circle", "hard", vec!["frenzy".to_string()], 201);
    hard_frenzy.wave = 10;
    easy.wave = 10;

    let run_summons = |state: &mut SimState, behavior: &str, hp: i32| -> Vec<Enemy> {
        let boss_id = spawn_boss(state, behavior, Vec2::new(160.0, 0.0), hp, 80.0);
        state.enemies[0].ai.boss_initialized = true;
        state.enemies[0].ai.boss_max_hp = 4_000;
        let mut collected = Vec::new();
        for _ in 0..720 {
            step(state, &SimInput::default(), DT);
            for e in &state.enemies {
                if e.id != boss_id
                    && !e.is_boss()
                    && !collected.iter().any(|c: &Enemy| c.id == e.id)
                {
                    collected.push(e.clone());
                }
            }
            if collected.len() >= 2 {
                break;
            }
        }
        collected
    };

    // Brood Matriarch summons egg_sac / swarm via make_summoned_enemy
    let easy_queen_adds = run_summons(&mut easy, "boss_swarmqueen", 4_000);
    let hard_queen_adds = run_summons(&mut hard_frenzy, "boss_swarmqueen", 4_000);
    assert!(!easy_queen_adds.is_empty(), "easy queen should summon adds");
    assert!(!hard_queen_adds.is_empty(), "hard+frenzy queen should summon adds");

    for add in &hard_queen_adds {
        let (exp_hp, exp_speed, exp_atk) = enemy_stats(&add.behavior, 10, "hard");
        let expected_speed = exp_speed * hard_frenzy.rules.enemy_speed_mult;
        assert_eq!(add.hp, exp_hp, "add {} hp mismatch", add.behavior);
        assert!(
            (add.speed - expected_speed).abs() <= 1e-3,
            "add {} speed {} != expected single-applied frenzy*hard speed {}",
            add.behavior,
            add.speed,
            expected_speed
        );
        assert!((add.ai.attack_mult - exp_atk).abs() <= 1e-4);
        assert!(
            add.attack_cd > 0.0,
            "summoned add {} must receive initial spawn attack_cd",
            add.behavior
        );
    }

    // Origin Nexus summons swarm/charger via make_summoned_enemy too
    let mut nexus_hard = new_boss_arena("donut", "hard", vec!["frenzy".to_string()], 303);
    let nexus_adds = run_summons(&mut nexus_hard, "boss_womb_core", 4_000);
    assert!(!nexus_adds.is_empty(), "Origin Nexus should summon adds");
    for add in &nexus_adds {
        let (exp_hp, exp_speed, _) = enemy_stats(&add.behavior, 10, "hard");
        let expected_speed = exp_speed * nexus_hard.rules.enemy_speed_mult;
        assert_eq!(add.hp, exp_hp);
        assert!(
            (add.speed - expected_speed).abs() <= 1e-3,
            "nexus add {} speed {} != expected {}",
            add.behavior,
            add.speed,
            expected_speed
        );
        assert!(
            add.attack_cd > 0.0,
            "nexus add {} must have positive initial attack_cd",
            add.behavior
        );
    }

    // Also verify hard+frenzy speed exceeds easy speed by difficulty*frenzy (not frenzy^2)
    if let (Some(e_add), Some(h_add)) = (
        easy_queen_adds.iter().find(|e| e.behavior == "swarm"),
        hard_queen_adds.iter().find(|e| e.behavior == "swarm"),
    ) {
        let (_, easy_s, _) = enemy_stats("swarm", 10, "easy");
        let (_, hard_s, _) = enemy_stats("swarm", 10, "hard");
        let expected_ratio = (hard_s * 1.20) / easy_s;
        let actual_ratio = h_add.speed / e_add.speed;
        assert!(
            (actual_ratio - expected_ratio).abs() < 1e-3,
            "speed ratio {actual_ratio:.4} != expected {expected_ratio:.4}"
        );
    }
}

#[test]
fn storm_sovereign_teleport_resets_prev_pos_and_emits_event() {
    for (idx, map_type) in ["circle", "donut", "cross", "diamond"].iter().enumerate() {
        let mut state = new_boss_arena(map_type, "normal", vec![], 400 + idx as u64);
        // Put player near arena boundary to exercise wall-clamped teleport targets too.
        state.player.pos = Vec2::new(state.room_radius * 0.72, 0.0);
        let id = spawn_boss(&mut state, "boss_thunder", Vec2::new(0.0, 0.0), 3_000, 80.0);
        state.enemies[0].ai.sub_state = EnemySubState::ThunderTeleportOut;
        state.enemies[0].ai.sub_timer = 0.05;

        let mut teleport_event = None;
        for _ in 0..20 {
            let events = step(&mut state, &SimInput::default(), DT);
            for ev in events {
                if let SimEvent::BossTeleport { from, to, .. } = ev {
                    teleport_event = Some((from, to));
                }
            }
            if teleport_event.is_some() {
                let boss = state.enemies.iter().find(|e| e.id == id).unwrap();
                assert_eq!(boss.ai.sub_state, EnemySubState::ThunderTeleportIn);
                assert_eq!(
                    boss.prev_pos, boss.pos,
                    "on {map_type}, prev_pos {:?} must equal pos {:?} after teleport",
                    boss.prev_pos, boss.pos
                );
                let (from, to) = teleport_event.unwrap();
                assert!((to - boss.pos).length() < 1e-4);
                assert!((to - from).length() > 10.0, "teleport should jump across arena");
                break;
            }
        }
        assert!(teleport_event.is_some(), "missing BossTeleport event on {map_type}");
    }
}

#[test]
fn prisma_overlord_sweep_is_continuous_and_clears_on_interrupt() {
    // 1. Continuous sweep + rage mid-attack + accurate LaserWingWindup duration (0.46s, not 0.23s)
    let mut state = new_boss_arena("circle", "normal", vec![], 501);
    // Start in Phase II (non-raged, 1 beam) then trigger rage mid-attack without changing phase,
    // and also verify Phase III LaserWingWindup lasts 0.46s.
    let id = spawn_boss(&mut state, "boss_laser", Vec2::new(180.0, 0.0), 1_500, 75.0);
    state.enemies[0].ai.boss_initialized = true;
    state.enemies[0].ai.boss_max_hp = 3_000;
    state.enemies[0].ai.phase = 1;
    state.enemies[0].ai.persona = BossPersona::Aggressive;
    state.enemies[0].ai.charge_dir = Vec2::new(-1.0, 0.0);
    state.enemies[0].ai.sub_state = EnemySubState::LaserCharge;
    state.enemies[0].ai.sub_timer = 0.02;

    let mut attack_steps = 0;
    let mut saw_rage_beam_growth = false;
    for _ in 0..220 {
        let prev_sub = state.enemies[0].ai.sub_state;
        step(&mut state, &SimInput::default(), DT);
        let boss = state.enemies.iter().find(|e| e.id == id).unwrap();
        if prev_sub == EnemySubState::LaserAttack && boss.ai.sub_state == EnemySubState::LaserAttack
        {
            attack_steps += 1;
            let active_beams: Vec<_> = state
                .lasers
                .iter()
                .filter(|b| b.owner == "enemy" && b.source == "boss_laser")
                .collect();
            let expected = if boss.ai.rage {
                (1 + BOSS_RAGE_EXTRA_PROJECTILES).min(3) as usize
            } else {
                1
            };
            assert_eq!(
                active_beams.len(),
                expected,
                "LaserAttack should maintain exact beam count ({expected}) without stray duplicates"
            );
            for b in &active_beams {
                assert_eq!(b.warn, 0.0);
                assert!((b.ttl - 0.08).abs() < 1e-5);
            }
            if attack_steps == 10 {
                // Trigger rage (<= 35%) mid-attack while remaining in Phase II (> 33%)
                state.enemies[0].hp = 1_020;
            }
            if state.enemies[0].ai.rage && active_beams.len() == 2 {
                saw_rage_beam_growth = true;
            }
        } else if attack_steps > 0 && boss.ai.sub_state == EnemySubState::LaserReposition {
            break;
        }
    }
    assert!(attack_steps > 100, "LaserAttack should run for ~2.2s, got {attack_steps} steps");
    assert!(saw_rage_beam_growth, "rage mid-attack should cleanly expand 1 -> 2 beams");

    // 1b. Verify Phase III LaserWingWindup lasts ~0.46s (not halved to 0.23s by double decrement)
    let mut wing_state = new_boss_arena("circle", "normal", vec![], 511);
    spawn_boss(&mut wing_state, "boss_laser", Vec2::new(180.0, 0.0), 800, 75.0);
    wing_state.enemies[0].ai.boss_initialized = true;
    wing_state.enemies[0].ai.boss_max_hp = 3_000;
    wing_state.enemies[0].ai.phase = 2;
    wing_state.enemies[0].ai.charge_dir = Vec2::new(-1.0, 0.0);
    wing_state.enemies[0].ai.sub_state = EnemySubState::LaserAttack;
    wing_state.enemies[0].ai.sub_timer = 0.02;
    let mut windup_steps = 0;
    for _ in 0..80 {
        step(&mut wing_state, &SimInput::default(), DT);
        if wing_state.enemies[0].ai.sub_state == EnemySubState::LaserWingWindup {
            windup_steps += 1;
        } else if windup_steps > 0 {
            break;
        }
    }
    // 0.46s at 60Hz is 28 steps (vs ~14 steps if double-decremented)
    assert!(
        windup_steps >= 26,
        "LaserWingWindup should last ~0.46s (>=26 steps), got {windup_steps} steps"
    );

    // 2. Repulsor stun mid-LaserAttack clears sweeping beams immediately
    let mut rep_state = new_boss_arena("circle", "normal", vec![], 502);
    rep_state.player.pos = Vec2::ZERO;
    let rep_id = spawn_boss(&mut rep_state, "boss_laser", Vec2::new(REPULSOR_RANGE - 30.0, 0.0), 3_000, 75.0);
    rep_state.enemies[0].ai.boss_initialized = true;
    rep_state.enemies[0].ai.boss_max_hp = 3_000;
    rep_state.enemies[0].ai.charge_dir = Vec2::new(-1.0, 0.0);
    rep_state.enemies[0].ai.sub_state = EnemySubState::LaserAttack;
    rep_state.enemies[0].ai.sub_timer = 1.5;
    step(&mut rep_state, &SimInput::default(), DT);
    assert!(rep_state.lasers.iter().any(|b| b.source == "boss_laser"));

    rep_state.repulsor.charges = 1;
    rep_state.repulsor.cooldown_until = rep_state.time;
    let events = step(
        &mut rep_state,
        &SimInput {
            ultra_pressed: true,
            ..SimInput::default()
        },
        DT,
    );
    assert!(events.iter().any(|e| matches!(e, SimEvent::RepulsorBlast { .. })));
    let boss = rep_state.enemies.iter().find(|e| e.id == rep_id).unwrap();
    assert!(boss.is_stunned(rep_state.time));
    assert_eq!(boss.ai.sub_state, EnemySubState::None);
    assert!(
        !rep_state.lasers.iter().any(|b| b.source == "boss_laser"),
        "Repulsor stun must clear boss_laser sweeping beams"
    );

    // 3. Phase transition mid-LaserAttack clears sweeping beams immediately
    let mut ph_state = new_boss_arena("circle", "normal", vec![], 503);
    spawn_boss(&mut ph_state, "boss_laser", Vec2::new(150.0, 0.0), 3_000, 75.0);
    ph_state.enemies[0].ai.boss_initialized = true;
    ph_state.enemies[0].ai.boss_max_hp = 3_000;
    ph_state.enemies[0].ai.phase = 0;
    ph_state.enemies[0].ai.charge_dir = Vec2::new(-1.0, 0.0);
    ph_state.enemies[0].ai.sub_state = EnemySubState::LaserAttack;
    ph_state.enemies[0].ai.sub_timer = 1.5;
    step(&mut ph_state, &SimInput::default(), DT);
    assert!(!ph_state.lasers.is_empty());

    ph_state.enemies[0].hp = 1_800; // Crosses into Phase II (<= 66%)
    step(&mut ph_state, &SimInput::default(), DT);
    assert_eq!(ph_state.enemies[0].ai.phase, 1);
    assert_eq!(ph_state.enemies[0].ai.sub_state, EnemySubState::None);
    assert!(
        !ph_state.lasers.iter().any(|b| b.source == "boss_laser"),
        "Phase transition must clear boss_laser sweeping beams"
    );
}

#[test]
fn forge_warden_prunes_old_traps_so_telegraphed_spikes_deploy() {
    // Case A: 14 traps (10 slam/meteor + 4 old spikes/mines) -> prunes 4 old spikes/mines, keeps slam/meteor, deploys all 4 spikes
    let mut state = new_boss_arena("circle", "normal", vec![], 601);
    let _id = spawn_boss(&mut state, "boss_trapmaster", Vec2::new(180.0, 0.0), 1_500, 75.0);
    state.enemies[0].ai.boss_initialized = true;
    state.enemies[0].ai.boss_max_hp = 3_000;
    state.enemies[0].ai.phase = 1; // deploys 4 spikes

    for i in 0..6 {
        let mut tr = Trap::new(Vec2::new(i as f32 * 20.0, 120.0), 40.0, 10, 5.0, 0.5, "slam");
        tr.t = 0.2;
        state.traps.push(tr);
    }
    for i in 0..4 {
        let mut tr = Trap::new(Vec2::new(i as f32 * 20.0, -120.0), 40.0, 10, 5.0, 0.5, "meteor");
        tr.t = 0.2;
        state.traps.push(tr);
    }
    for i in 0..2 {
        let mut tr = Trap::new(Vec2::new(-100.0, i as f32 * 20.0), TRAPMASTER_SPIKE_RADIUS, 10, 6.0, 0.8, "spike");
        tr.t = 2.0 + i as f32;
        state.traps.push(tr);
    }
    for i in 0..2 {
        let mut tr = Trap::new(Vec2::new(-140.0, i as f32 * 20.0), 28.0, 10, 6.0, 0.7, "mine");
        tr.t = 1.0 + i as f32;
        state.traps.push(tr);
    }
    assert_eq!(state.traps.len(), MAX_ACTIVE_CONSTRUCTIONS);

    // Step once to enter TrapmasterTelegraph
    step(&mut state, &SimInput::default(), DT);
    assert_eq!(state.enemies[0].ai.sub_state, EnemySubState::TrapmasterTelegraph);
    assert_eq!(state.enemies[0].ai.summon_target_count, 4);

    // Step until TrapmasterTelegraph completes
    for _ in 0..60 {
        step(&mut state, &SimInput::default(), DT);
        if state.enemies[0].ai.sub_state == EnemySubState::None {
            break;
        }
    }
    assert_eq!(state.traps.len(), MAX_ACTIVE_CONSTRUCTIONS);
    assert_eq!(
        state.traps.iter().filter(|tr| tr.kind == "slam").count(),
        6,
        "slam traps must not be pruned"
    );
    assert_eq!(
        state.traps.iter().filter(|tr| tr.kind == "meteor").count(),
        4,
        "meteor traps must not be pruned"
    );
    let new_spikes: Vec<_> = state
        .traps
        .iter()
        .filter(|tr| tr.kind == "spike" && tr.source == "boss_trapmaster")
        .collect();
    assert_eq!(new_spikes.len(), 4, "all 4 telegraphed spikes must deploy");

    // Case B: 14 traps (12 long-lived slam/meteor + 2 old spikes) -> summon_target_count matches actual deployed (2)
    let mut tight = new_boss_arena("circle", "normal", vec![], 602);
    spawn_boss(&mut tight, "boss_trapmaster", Vec2::new(180.0, 0.0), 1_500, 75.0);
    tight.enemies[0].ai.boss_initialized = true;
    tight.enemies[0].ai.boss_max_hp = 3_000;
    tight.enemies[0].ai.phase = 1;
    for i in 0..12 {
        tight.traps.push(Trap::new(Vec2::new(i as f32 * 15.0, 150.0), 40.0, 10, 5.0, 0.5, "slam"));
    }
    for i in 0..2 {
        tight.traps.push(Trap::new(Vec2::new(-100.0, i as f32 * 25.0), 26.0, 10, 6.0, 0.8, "spike"));
    }
    step(&mut tight, &SimInput::default(), DT);
    assert_eq!(tight.enemies[0].ai.sub_state, EnemySubState::TrapmasterTelegraph);
    assert_eq!(
        tight.enemies[0].ai.summon_target_count, 2,
        "summon_target_count must match deployable cap when non-prunable traps fill 12 slots"
    );
    for _ in 0..60 {
        step(&mut tight, &SimInput::default(), DT);
        if tight.enemies[0].ai.sub_state == EnemySubState::None {
            break;
        }
    }
    let deployed = tight
        .traps
        .iter()
        .filter(|tr| tr.kind == "spike" && tr.source == "boss_trapmaster")
        .count();
    assert_eq!(deployed, 2);
    assert_eq!(tight.traps.len(), MAX_ACTIVE_CONSTRUCTIONS);
}

#[test]
fn brood_matriarch_falls_back_to_telegraphed_volley_when_cap_fills() {
    let mut state = new_boss_arena("circle", "normal", vec![], 701);
    state.max_enemies = 4; // boss_adds_cap = 4 + 4 = 8 non-boss enemies
    let id = spawn_boss(&mut state, "boss_swarmqueen", Vec2::new(240.0, 0.0), 3_000, 70.0);

    // Run until she enters QueenBroodTelegraph or QueenSwarmTelegraph
    let mut entered_summon_telegraph = false;
    for _ in 0..600 {
        // Keep attack_cd ready quickly
        if state.enemies[0].ai.sub_state == EnemySubState::None {
            state.enemies[0].attack_cd = 0.0;
        }
        step(&mut state, &SimInput::default(), DT);
        let sub = state.enemies[0].ai.sub_state;
        if matches!(
            sub,
            EnemySubState::QueenBroodTelegraph | EnemySubState::QueenSwarmTelegraph
        ) {
            entered_summon_telegraph = true;
            break;
        }
        // Reset seed/rng gently if she picked QueenVolleyTelegraph
        if sub == EnemySubState::QueenVolleyTelegraph {
            state.enemies[0].ai.sub_state = EnemySubState::None;
            state.enemies[0].ai.sub_timer = 0.0;
            state.enemies[0].attack_cd = 0.0;
        }
    }
    assert!(entered_summon_telegraph, "queen should enter summon telegraph");
    assert!(state.projectiles.is_empty());

    // Now fill the non-boss cap (8 non-boss enemies) mid-telegraph!
    let cap = state.max_enemies + 4;
    while state.enemies.iter().filter(|e| !e.is_boss()).count() < cap {
        let eid = state.next_entity_id;
        state.next_entity_id += 1;
        state.enemies.push(Enemy::new(eid, Vec2::new(-300.0, -300.0), 200, 0.0, "chaser"));
    }

    // Advance until original summon telegraph expires: must transition to QueenVolleyTelegraph WITHOUT firing projectiles!
    let mut saw_fallback_telegraph = false;
    for _ in 0..90 {
        step(&mut state, &SimInput::default(), DT);
        let queen = state.enemies.iter().find(|e| e.id == id).unwrap();
        if queen.ai.sub_state == EnemySubState::QueenVolleyTelegraph {
            saw_fallback_telegraph = true;
            assert!(
                state.projectiles.is_empty(),
                "fallback to QueenVolleyTelegraph must NOT fire an untelegraphed volley"
            );
            assert!(
                (queen.ai.sub_timer - SWARMQUEEN_TELEGRAPH).abs() <= DT * 2.0,
                "fallback telegraph should reset sub_timer to SWARMQUEEN_TELEGRAPH ({SWARMQUEEN_TELEGRAPH}), got {}",
                queen.ai.sub_timer
            );
            break;
        }
    }
    assert!(saw_fallback_telegraph, "queen did not fall back to QueenVolleyTelegraph");

    // Hold projectiles while QueenVolleyTelegraph runs, then fire after ~SWARMQUEEN_TELEGRAPH
    let mut fired_after_telegraph = false;
    for _ in 0..60 {
        step(&mut state, &SimInput::default(), DT);
        let queen = state.enemies.iter().find(|e| e.id == id).unwrap();
        if queen.ai.sub_state == EnemySubState::QueenVolleyTelegraph {
            assert!(state.projectiles.is_empty(), "must hold volley during fallback telegraph");
        } else if !state.projectiles.is_empty() {
            fired_after_telegraph = true;
            break;
        }
    }
    assert!(fired_after_telegraph, "queen did not fire volley after fallback telegraph completed");
}

#[test]
fn gorgon_juggernaut_slam_warn_expires_when_slam_arms() {
    for &time_slow in &[false, true] {
        let mut state = new_boss_arena("circle", "normal", vec![], 801);
        let start_x = state.room_radius * 0.80;
        let id = spawn_boss(&mut state, "boss_brute", Vec2::new(start_x, 0.0), 1_500, 95.0);
        state.enemies[0].ai.boss_initialized = true;
        state.enemies[0].ai.boss_max_hp = 3_000;
        state.enemies[0].ai.phase = 1; // phase II spawns slam_warn + slam on wall impact
        state.enemies[0].ai.volley_mode = 0;
        state.enemies[0].ai.sub_state = EnemySubState::BruteCharge;
        state.enemies[0].ai.sub_timer = 1.0;
        state.enemies[0].ai.charge_dir = Vec2::new(1.0, 0.0);
        if time_slow {
            state.player.time_slow_until = 10.0;
        }

        // Step until Brute impacts wall and spawns slam_warn + slam
        let mut spawned = false;
        for _ in 0..90 {
            step(&mut state, &SimInput::default(), DT);
            if state.traps.iter().any(|t| t.kind == "slam_warn") {
                spawned = true;
                break;
            }
        }
        assert!(spawned, "Brute wall impact in phase II must spawn slam_warn");

        let warn = state.traps.iter().find(|t| t.kind == "slam_warn").unwrap();
        let slam = state.traps.iter().find(|t| t.kind == "slam").unwrap();
        assert!((warn.armed_delay - 0.62).abs() < 1e-4);
        assert!((warn.ttl + warn.t - 0.62).abs() < 1e-4, "slam_warn initial ttl must be 0.62");
        assert!((slam.armed_delay - 0.62).abs() < 1e-4);
        assert!(slam.damage > 0);
        assert_eq!(warn.damage, 0);

        // Clear shockwave projectiles and position player inside slam radius (78.0)
        // but outside boss body contact radius (30 + player_radius) so only slam can hit.
        state.projectiles.clear();
        let slam_pos = slam.pos;
        state.player.pos = slam_pos + Vec2::new(-62.0, 0.0);
        let hp_before = state.player.hp;

        let mut expired_and_armed_together = false;
        for _ in 0..120 {
            step(&mut state, &SimInput::default(), DT);
            let has_warn = state.traps.iter().any(|t| t.kind == "slam_warn");
            let slam_opt = state.traps.iter().find(|t| t.kind == "slam");
            if has_warn {
                assert_eq!(
                    state.player.hp, hp_before,
                    "slam must NOT damage player while slam_warn is still active"
                );
                if let Some(s) = slam_opt {
                    assert!(s.t < s.armed_delay);
                }
            } else {
                // On the step slam_warn expires, either slam armed and hit player (consumed) or slam.t >= armed_delay
                assert!(
                    state.player.hp < hp_before || slam_opt.is_some_and(|s| s.t >= s.armed_delay),
                    "slam must arm on the exact step slam_warn expires"
                );
                expired_and_armed_together = true;
                break;
            }
        }
        assert!(expired_and_armed_together, "slam_warn/slam lifecycle failed (time_slow={time_slow})");
        assert!(state.enemies.iter().any(|e| e.id == id));
    }
}

#[test]
fn ocular_abyss_telegraphs_phase_two_ring_and_fan() {
    let mut state = new_boss_arena("circle", "normal", vec![], 901);
    state.player.pos = Vec2::new(-200.0, 40.0);
    let id = spawn_boss(&mut state, "boss_abyss_gaze", Vec2::new(160.0, -20.0), 1_500, 80.0);
    state.enemies[0].ai.boss_initialized = true;
    state.enemies[0].ai.boss_max_hp = 3_000;
    state.enemies[0].ai.phase = 1; // phase II

    // Enter AbyssTelegraph
    step(&mut state, &SimInput::default(), DT);
    let boss = state.enemies.iter().find(|e| e.id == id).unwrap();
    assert_eq!(boss.ai.sub_state, EnemySubState::AbyssTelegraph);
    assert!(boss.ai.sniper_aim.length() > 0.99);
    let locked_ring_start = boss.ai.sniper_aim.y.atan2(boss.ai.sniper_aim.x);
    let locked_fan_aim = boss.ai.charge_dir.normalized();

    // Verify render parity during AbyssTelegraph: 8 spoke lines + 3 fan rails drawn
    let (_wa, wadd) = render_world(&state);
    let ring_spoke_col = linear_rgba_f([165, 195, 255], 0.15, 1.45);
    let spoke_lines = wadd
        .instances
        .iter()
        .filter(|inst| inst.kind == 1 && color_matches(inst.color, ring_spoke_col, 0.35))
        .count();
    assert!(
        spoke_lines >= 8,
        "world renderer should draw 8 ring spoke rails during phase II AbyssTelegraph, found {spoke_lines}"
    );

    // While AbyssTelegraph runs (~0.68s), projectiles & lasers must stay empty
    let mut fired = false;
    for _ in 0..60 {
        step(&mut state, &SimInput::default(), DT);
        let boss = state.enemies.iter().find(|e| e.id == id).unwrap();
        if boss.ai.sub_state == EnemySubState::AbyssTelegraph {
            assert!(state.projectiles.is_empty(), "must hold fan/ring during AbyssTelegraph");
            assert!(state.lasers.is_empty(), "must hold paired lasers during AbyssTelegraph");
        } else {
            fired = true;
            break;
        }
    }
    assert!(fired, "AbyssTelegraph did not complete within 60 steps");

    // Verify 8 ring "bullet" projectiles match locked sniper_aim angle, and fan "plasma" matches charge_dir
    let bullets: Vec<_> = state
        .projectiles
        .iter()
        .filter(|p| p.source == "boss_abyss_gaze" && p.projectile_type == "bullet")
        .collect();
    assert_eq!(bullets.len(), 8, "phase II Abyss Gaze must fire 8-bullet ring");
    for i in 0..8 {
        let expected_ang = locked_ring_start + (i as f32) * (TAU / 8.0);
        let expected_dir = Vec2::new(expected_ang.cos(), expected_ang.sin());
        let matched = bullets
            .iter()
            .any(|p| p.vel.normalized().dot(expected_dir) > 0.999);
        assert!(matched, "missing ring bullet at spoke {i} ({expected_ang:.3} rad)");
    }

    let plasmas: Vec<_> = state
        .projectiles
        .iter()
        .filter(|p| p.source == "boss_abyss_gaze" && p.projectile_type == "plasma")
        .collect();
    assert_eq!(plasmas.len(), 7, "phase II Abyss Gaze must fire 7-shot plasma fan");
    let center_plasma = plasmas
        .iter()
        .any(|p| p.vel.normalized().dot(locked_fan_aim) > 0.999);
    assert!(center_plasma, "center fan projectile must match locked charge_dir");

    let abyss_lasers: Vec<_> = state
        .lasers
        .iter()
        .filter(|l| l.source == "boss_abyss_gaze")
        .collect();
    assert_eq!(abyss_lasers.len(), 2, "phase II Abyss Gaze must spawn 2 warned laser lanes");
    assert!(abyss_lasers.iter().all(|l| l.warn > 0.5));
    let _ = ABYSS_GAZE_TELEGRAPH;
}

#[test]
fn origin_nexus_delays_projectiles_until_telegraph_completes() {
    let mut state = new_boss_arena("circle", "normal", vec![], 1001);
    let id = spawn_boss(&mut state, "boss_womb_core", Vec2::new(170.0, 0.0), 1_500, 80.0);
    state.enemies[0].ai.boss_initialized = true;
    state.enemies[0].ai.boss_max_hp = 3_000;
    state.enemies[0].ai.phase = 1;
    // Cautious places womb_pulse between boss and player (away from player_pos)
    // so it doesn't immediately detonate on the player before render inspection.
    state.enemies[0].ai.persona = BossPersona::Cautious;

    step(&mut state, &SimInput::default(), DT);
    assert_eq!(state.enemies[0].ai.sub_state, EnemySubState::WombPulseTelegraph);
    assert!(state.traps.iter().any(|t| t.kind == "womb_warn"));
    assert!(state.traps.iter().any(|t| t.kind == "womb_pulse"));
    assert!(state.projectiles.is_empty());

    // Render while womb_warn is active and womb_pulse is unarmed
    let (wa_warn, _) = render_world(&state);
    let warn_fill = linear_rgba_f([150, 110, 255], 0.25, 1.05);
    assert!(
        wa_warn
            .instances
            .iter()
            .any(|inst| inst.kind == 0 && color_matches(inst.color, warn_fill, 0.15)),
        "WorldRenderer must draw womb_warn ellipse while telegraphing"
    );

    // Step until WombPulseTelegraph completes (~0.52s = 32 steps)
    let mut steps = 0;
    for _ in 0..50 {
        steps += 1;
        step(&mut state, &SimInput::default(), DT);
        let boss = state.enemies.iter().find(|e| e.id == id).unwrap();
        if boss.ai.sub_state == EnemySubState::WombPulseTelegraph {
            assert!(
                state.projectiles.is_empty(),
                "WombPulseTelegraph must delay projectiles until sub_timer <= 0.0"
            );
            assert!(state.traps.iter().any(|t| t.kind == "womb_warn"));
        } else {
            break;
        }
    }
    let elapsed = steps as f32 * DT;
    assert!(
        (elapsed - WOMB_PULSE_TELEGRAPH).abs() <= DT * 2.0,
        "WombPulseTelegraph duration {elapsed:.3}s != {WOMB_PULSE_TELEGRAPH}"
    );
    assert!(!state.projectiles.is_empty(), "projectiles must fire once telegraph finishes");
    assert!(
        !state.traps.iter().any(|t| t.kind == "womb_warn"),
        "womb_warn must expire when pulse arms"
    );
    let pulse = state
        .traps
        .iter()
        .find(|t| t.kind == "womb_pulse")
        .expect("womb_pulse must arm when telegraph finishes");
    assert!(pulse.t >= pulse.armed_delay);

    // Verify WorldRenderer draws armed "womb_pulse" using its magenta pulse tint (not fallback red `_ =>`)
    let (wa_armed, _) = render_world(&state);
    let pulse_fill = linear_rgba_f([220, 85, 225], 0.26, 1.05);
    let fallback_red = linear_rgba_f([255, 80, 80], 0.26, 1.05);
    assert!(
        wa_armed
            .instances
            .iter()
            .any(|inst| inst.kind == 0 && color_matches(inst.color, pulse_fill, 0.05)),
        "WorldRenderer must draw armed womb_pulse with magenta pulse tint"
    );
    assert!(
        !wa_armed
            .instances
            .iter()
            .any(|inst| inst.kind == 0 && color_matches(inst.color, fallback_red, 0.02)),
        "womb_pulse must not fall into fallback red trap rendering"
    );
}

#[test]
fn eclipse_archon_rotates_safe_sector_in_phase_two_and_three() {
    for &(phase, expected_abs_step) in &[(1_i32, 0.34_f32), (2_i32, 0.38_f32)] {
        let mut state = new_boss_arena("circle", "normal", vec![], 1100 + phase as u64);
        let id = spawn_boss(
            &mut state,
            "boss_eclipse_archon",
            Vec2::new(200.0, 0.0),
            if phase == 1 { 1_500 } else { 800 },
            75.0,
        );
        state.enemies[0].ai.boss_initialized = true;
        state.enemies[0].ai.boss_max_hp = 3_000;
        state.enemies[0].ai.phase = phase;
        state.enemies[0].ai.persona = BossPersona::Aggressive;
        state.enemies[0].ai.charge_dir = Vec2::new(-1.0, 0.0);
        state.enemies[0].ai.sub_state = EnemySubState::EclipseCharge;
        state.enemies[0].ai.sub_timer = 0.05;

        let step_rad = eclipse_safe_step_rad(&state.enemies[0]);
        assert!((step_rad.abs() - expected_abs_step).abs() < 1e-5);
        assert!(
            (eclipse_safe_angle(&state.enemies[0], 1) - eclipse_safe_angle(&state.enemies[0], 0) - step_rad).abs()
                < 1e-5
        );

        let mut volley_gaps = Vec::new();
        let mut prev_proj_len = 0usize;
        for _ in 0..180 {
            step(&mut state, &SimInput::default(), DT);
            let boss = state.enemies.iter().find(|e| e.id == id).unwrap();
            if boss.ai.sub_state == EnemySubState::EclipseBurst && state.projectiles.len() > prev_proj_len {
                let volley = (boss.ai.gun_idx as i32) - 1;
                let safe_ang = eclipse_safe_angle(boss, volley);
                let new_shots = &state.projectiles[prev_proj_len..];
                assert!(!new_shots.is_empty());
                for p in new_shots {
                    let ang = p.vel.y.atan2(p.vel.x);
                    let delta = (ang - safe_ang + PI).rem_euclid(TAU) - PI;
                    assert!(
                        delta.abs() >= ECLIPSE_GAP_HALF_WIDTH - 1e-4,
                        "phase {phase} volley {volley} fired inside safe sector! delta={delta:.3}"
                    );
                }
                volley_gaps.push((volley, safe_ang));
                prev_proj_len = state.projectiles.len();

                // Verify world & 3D model render cleanly during EclipseBurst without panics/NaNs
                let (wa, wadd) = render_world(&state);
                assert!(!wa.instances.is_empty() && !wadd.instances.is_empty());
                let mut m_alpha = SdfBatch::with_capacity(256);
                let mut m_add = SdfBatch::with_capacity(64);
                let (cx, cy) = to_iso_cam(boss.pos, state.player.pos, 980.0, 620.0, Vec2::ZERO);
                assert!(draw_boss_model(
                    boss,
                    &mut m_alpha,
                    &mut m_add,
                    [cx, cy],
                    Vec2::new(safe_ang.cos(), safe_ang.sin()),
                    1.0,
                    state.time,
                    0.5,
                    [60, 255, 204],
                    false,
                ));
            }
            if boss.ai.sub_state == EnemySubState::EclipseEscape {
                break;
            }
        }
        let expected_volleys = (1 + phase) as usize;
        assert_eq!(
            volley_gaps.len(),
            expected_volleys,
            "phase {phase} should fire {expected_volleys} rotated volleys"
        );
        let diff_0_1 = volley_gaps[1].1 - volley_gaps[0].1;
        assert!(
            (diff_0_1 - step_rad).abs() < 1e-4,
            "safe angle did not rotate by {step_rad:.3} between volley 0 and 1 (got {diff_0_1:.3})"
        );
    }
}

#[test]
fn replay_verification_roundtrip_passes_under_current_rules() {

    let setup = RunSetup {
        seed: 42_010,
        difficulty: "hard".to_string(),
        map_type: "diamond".to_string(),
        mutator_ids: vec!["frenzy".to_string()],
        auto_shoot: true,
        ..RunSetup::default()
    };
    let mut state = SimState::new(setup.clone());
    let mut recorder = Recorder::from_state(&state, setup.view_w, setup.view_h);

    for frame in 0..360 {
        let ang = frame as f32 * 0.04;
        let input = SimInput {
            move_dir: Vec2::new(ang.cos(), ang.sin()),
            aim_world: Vec2::new(-ang.sin() * 200.0, ang.cos() * 200.0),
            fire_held: true,
            boost_held: frame % 90 < 15,
            dash_pressed: frame % 120 == 30,
            ultra_pressed: frame == 180,
        };
        step(&mut state, &input, DT);
        recorder.push_frame_with_state(&input, &state);
    }
    let rec = recorder.finalize(&state);
    assert_eq!(rec.rules_version, SIMULATION_RULES_VERSION);
    assert_eq!(rec.final_hash, state_hash(&state));

    let verified = replay_and_verify(&rec);
    assert!(verified.matches, "replay failed: {:?}", verified.error);
    assert_eq!(verified.frames_run, 360);
    assert_eq!(verified.actual_hash, rec.final_hash);

    // Mismatched rules_version must be rejected explicitly.
    let mut bad_rec = rec;
    bad_rec.rules_version = 10;
    let rejected = replay_and_verify(&bad_rec);
    assert!(!rejected.matches);
    assert!(rejected.error.is_some());
}
