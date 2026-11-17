use std::f32::consts::TAU;

use plouto_rs::sim::ai_skill::ai_skill;
use plouto_rs::sim::behaviors::{dodge_player_projectiles, predict_target};
use plouto_rs::sim::config::{
    CROSS_ARM_RATIO, DONUT_INNER_RATIO, MAP_CIRCLE, MAP_CROSS, MAP_DIAMOND, MAP_DONUT,
    MAX_ACTIVE_CONSTRUCTIONS, PARALLEL_MIN_ENEMIES, REPULSOR_STUN_SECONDS,
};
use plouto_rs::sim::director::{
    AttackCategory, AttackDirector, AttackDirectorState, AttackProposal,
};
use plouto_rs::sim::enemy::{Enemy, EnemyRole, EnemySubState};
use plouto_rs::sim::hazards::Trap;
use plouto_rs::sim::locomotion::{
    integrate_batch, kinematics_for_role, resolve_enemy_body_overlaps, route_point, MoveIntent,
};
use plouto_rs::sim::math::{arena_inside, clamp_entity_to_map, Vec2};
use plouto_rs::sim::perception::{build_perception, Perception, PerceptionMemory, WorldRect};
use plouto_rs::sim::projectile::Projectile;
use plouto_rs::sim::replay::{replay_and_verify, state_hash, Recorder};
use plouto_rs::sim::rng::SimRng;
use plouto_rs::sim::state::{RunSetup, SimInput, SimState};
use plouto_rs::sim::steer::{compute_formation_targets, FormationState};
use plouto_rs::sim::step::step;

fn full_screen_perception(player_pos: Vec2) -> Perception {
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
fn dodge_survives_formation() {
    // Part 1: locomotion::integrate_batch keeps MoveIntent::evade dominant even when
    // Formation v2 slot pulls in the exact opposite direction.
    let mut e = Enemy::new(1, Vec2::new(220.0, 0.0), 100, 120.0, "ranged");
    e.ai.heading = Vec2::new(0.0, 1.0);
    let mut enemies = vec![e];
    let dodge_dir = Vec2::new(0.0, 1.0);
    let intents = vec![Some(MoveIntent::evade(dodge_dir, 1.0))];
    let form_targets = vec![Some((Vec2::new(220.0, -250.0), "back"))];
    let skill = ai_skill("hard", 10);

    for _ in 0..8 {
        integrate_batch(
            &mut enemies,
            &intents,
            &form_targets,
            &skill,
            760.0,
            MAP_CIRCLE,
            1.0 / 60.0,
            1.0,
        );
    }
    assert!(
        enemies[0].vel.y > 40.0 && enemies[0].pos.y > 0.0,
        "evade intent must survive opposing formation pull: pos={:?}, vel={:?}",
        enemies[0].pos,
        enemies[0].vel
    );

    // Part 2: Live step() where a ranged enemy's strafe_sign opposes the required dodge side.
    let mut state = SimState::new(RunSetup {
        seed: 101,
        difficulty: "hard".to_string(),
        auto_shoot: false,
        ..RunSetup::default()
    });
    state.wave = 10;
    state.wave_active = true;
    state.player.hp = 10_000;
    state.player.pos = Vec2::ZERO;
    let mut ranged = Enemy::new(501, Vec2::new(200.0, 0.0), 500, 120.0, "ranged");
    ranged.ai.strafe_sign = Some(-1.0); // would normally strafe -y
    ranged.attack_cd = 10.0;
    state.enemies.push(ranged);

    // Fire a player projectile just below y=0 heading straight toward the enemy so dodge must go +y.
    state.projectiles.push(Projectile::new(
        Vec2::new(60.0, -6.0),
        Vec2::new(600.0, 0.0),
        10,
        2.0,
        "player",
        "bullet",
    ));

    let mut dodged_upward = false;
    for _ in 0..12 {
        step(&mut state, &SimInput::default(), 1.0 / 60.0);
        if state.enemies[0].ai.dodge_active_left > 0.0 {
            assert!(
                state.enemies[0].ai.dodge_direction.y > 0.5,
                "expected +y dodge away from bullet, got {:?}",
                state.enemies[0].ai.dodge_direction
            );
            dodged_upward = true;
        }
    }
    assert!(dodged_upward, "hard ranged enemy should trigger dodge after reaction window");
    assert!(
        state.enemies[0].pos.y > 2.0,
        "strafe_sign=-1 must not cancel +y dodge: pos={:?}",
        state.enemies[0].pos
    );
}

#[test]
fn committed_lunge_ignores_slot() {
    let mut chaser = Enemy::new(10, Vec2::new(150.0, 0.0), 100, 130.0, "chaser");
    chaser.ai.heading = Vec2::new(-1.0, 0.0);
    chaser.ai.lunge_t = 0.25;
    chaser.ai.lunge_dir = Vec2::new(-1.0, 0.0); // lunging toward player at origin
    let mut enemies = vec![chaser];
    let intents = vec![Some(MoveIntent::committed(Vec2::new(-1.0, 0.0), 1.7))];
    // Formation slot placed far behind the chaser (+x)
    let form_targets = vec![Some((Vec2::new(500.0, 200.0), "strike"))];
    let skill = ai_skill("normal", 5);

    for _ in 0..10 {
        integrate_batch(
            &mut enemies,
            &intents,
            &form_targets,
            &skill,
            760.0,
            MAP_CIRCLE,
            1.0 / 60.0,
            1.0,
        );
    }
    assert!(
        enemies[0].vel.x < -150.0 && enemies[0].vel.y.abs() < 1e-3,
        "committed lunge must ignore formation slot pull: vel={:?}",
        enemies[0].vel
    );
    assert!(enemies[0].pos.x < 130.0);
}

#[test]
fn prediction_ignores_dash_spike() {
    let mut state = SimState::new(RunSetup {
        seed: 202,
        view_w: 980,
        view_h: 620,
        ..RunSetup::default()
    });
    let mut mem = PerceptionMemory::new(state.player.hp, 980, 620);
    let input = SimInput {
        move_dir: Vec2::new(1.0, 0.0),
        ..SimInput::default()
    };
    let dt = 1.0 / 60.0;

    // Steady normal movement builds smoothed_vel.
    for _ in 0..10 {
        build_perception(&state, &mut mem, &input, Vec2::new(175.0, 0.0), false, dt);
    }
    let steady_vel = mem.smoothed_vel;
    assert!(steady_vel.x > 80.0);

    // Dash spike and dash_ended frame are excluded.
    state.player.is_dashing = true;
    let p_dash = build_perception(&state, &mut mem, &input, Vec2::new(800.0, 0.0), false, dt);
    assert_eq!(p_dash.smoothed_vel, steady_vel);

    state.player.is_dashing = false;
    let p_end = build_perception(&state, &mut mem, &input, Vec2::new(800.0, 0.0), true, dt);
    assert_eq!(p_end.smoothed_vel, steady_vel);

    // Boss contact knockback frame is excluded.
    mem.player_knocked_back = true;
    let p_kb = build_perception(&state, &mut mem, &input, Vec2::new(-950.0, 400.0), false, dt);
    assert_eq!(p_kb.smoothed_vel, steady_vel);

    // predict_target edge cases: zero speed, player_speed >= proj_speed, and lead_quality.
    let mut rng = SimRng::new(7);
    let mut shooter = Enemy::new(1, Vec2::ZERO, 50, 80.0, "ranged");
    let mut skill = ai_skill("hard", 20);
    skill.aim_jitter_deg = 0.0;

    // 1) Zero target velocity -> aims directly at player_pos without NaN.
    let p_zero = full_screen_perception(Vec2::new(220.0, -40.0));
    let aim_zero = predict_target(
        Vec2::ZERO,
        200.0,
        &mut shooter,
        &p_zero,
        &skill,
        dt,
        760.0,
        MAP_CIRCLE,
        &mut rng,
        0.0,
    );
    assert!((aim_zero - p_zero.player_pos).length() < 1e-4);

    // 2) player_speed == proj_speed and player_speed > proj_speed -> finite, valid aim.
    for speed in [200.0_f32, 320.0] {
        shooter.ai.retarget_left = 0.0;
        let p_fast = Perception {
            player_pos: Vec2::new(240.0, 0.0),
            smoothed_vel: Vec2::new(0.0, speed),
            intent_vel: Vec2::new(0.0, speed),
            ..full_screen_perception(Vec2::new(240.0, 0.0))
        };
        let aim_fast = predict_target(
            Vec2::ZERO,
            200.0,
            &mut shooter,
            &p_fast,
            &skill,
            dt,
            760.0,
            MAP_CIRCLE,
            &mut rng,
            0.0,
        );
        assert!(aim_fast.x.is_finite() && aim_fast.y.is_finite());
        assert!(aim_fast.y > 0.0, "must lead +y for fast moving target, got {aim_fast:?}");
    }

    // 3) lead_quality = 0.0 aims at current pos, lead_quality = 1.0 leads ahead.
    let p_lead = Perception {
        player_pos: Vec2::new(200.0, 0.0),
        smoothed_vel: Vec2::new(0.0, 120.0),
        intent_vel: Vec2::new(0.0, 120.0),
        ..full_screen_perception(Vec2::new(200.0, 0.0))
    };
    let mut low_skill = ai_skill("easy", 1);
    low_skill.lead_quality = 0.0;
    low_skill.aim_jitter_deg = 0.0;
    shooter.ai.retarget_left = 0.0;
    let aim_no_lead = predict_target(
        Vec2::ZERO,
        240.0,
        &mut shooter,
        &p_lead,
        &low_skill,
        dt,
        760.0,
        MAP_CIRCLE,
        &mut rng,
        0.0,
    );
    assert!((aim_no_lead - p_lead.player_pos).length() < 1e-4);
}

#[test]
fn iframe_hold_delays_normal_commit() {
    // Normal wave 6 respects i-frames; Normal wave 1 / Easy wave 6 do not.
    let make_state = |difficulty: &str, wave: i32| {
        let mut state = SimState::new(RunSetup {
            seed: 303,
            difficulty: difficulty.to_string(),
            auto_shoot: false,
            ..RunSetup::default()
        });
        state.wave = wave;
        state.wave_active = true;
        state.player.pos = Vec2::ZERO;
        state.player.invincibility_timer = 0.5;
        let mut ranged = Enemy::new(1, Vec2::new(180.0, 0.0), 100, 90.0, "ranged");
        ranged.attack_cd = 0.0;
        state.enemies.push(ranged);
        state
    };

    let mut normal_w6 = make_state("normal", 6);
    for _ in 0..10 {
        step(&mut normal_w6, &SimInput::default(), 1.0 / 60.0);
        assert_eq!(
            normal_w6.enemies[0].ai.sub_state,
            EnemySubState::None,
            "normal wave 6 must hold commit while player has i-frames"
        );
    }
    // Advance until i-frames expire (~0.5s total = 30 ticks); enemy should then commit.
    let mut committed_after = false;
    for _ in 0..35 {
        step(&mut normal_w6, &SimInput::default(), 1.0 / 60.0);
        if normal_w6.enemies[0].ai.sub_state == EnemySubState::RangedWindup {
            committed_after = true;
            break;
        }
    }
    assert!(committed_after, "enemy should commit once player i-frames expire");

    let mut easy_w6 = make_state("easy", 6);
    step(&mut easy_w6, &SimInput::default(), 1.0 / 60.0);
    assert_eq!(
        easy_w6.enemies[0].ai.sub_state,
        EnemySubState::RangedWindup,
        "easy difficulty must not hold commit on player i-frames"
    );
}

#[test]
fn dodge_edge_safe() {
    let mut skill = ai_skill("hard", 20);
    skill.dodge_chance = 1.0;
    skill.dodge_reaction_s = 0.0;
    let mut rng = SimRng::new(404);
    let room_radius = 760.0;

    // 1) Circle outer wall: enemy near right wall (735, 0); bullet just to its left (730, -100)
    // going +y would push lateral escape (+1, 0) outward past the wall, so edge check must flip to (-1, 0).
    let mut edge_enemy = Enemy::new(1, Vec2::new(735.0, 0.0), 100, 100.0, "ranged");
    edge_enemy.spawn_index = 0;
    let proj_circle = Projectile::new(
        Vec2::new(730.0, -90.0),
        Vec2::new(0.0, 600.0),
        10,
        2.0,
        "player",
        "bullet",
    );
    let dir_circle = dodge_player_projectiles(
        &mut edge_enemy,
        &[proj_circle],
        90.0,
        4,
        true,
        1.0 / 60.0,
        &skill,
        room_radius,
        MAP_CIRCLE,
        &mut rng,
    );
    assert!(
        dir_circle.x < -0.5,
        "dodge near Circle wall must flip inward, got {dir_circle:?}"
    );
    assert!(arena_inside(edge_enemy.pos + dir_circle * 36.0, room_radius, MAP_CIRCLE));

    // 2) Donut inner pit: enemy just outside inner hole at (315, 0) (pit edge at 760*0.38 = 288.8).
    // Bullet at (320, -90) going +y would push lateral escape (-1, 0) INTO the pit, so edge check must flip to (+1, 0).
    let mut donut_enemy = Enemy::new(2, Vec2::new(315.0, 0.0), 100, 100.0, "ranged");
    donut_enemy.spawn_index = 0;
    let proj_donut = Projectile::new(
        Vec2::new(320.0, -90.0),
        Vec2::new(0.0, 600.0),
        10,
        2.0,
        "player",
        "bullet",
    );
    let dir_donut = dodge_player_projectiles(
        &mut donut_enemy,
        &[proj_donut],
        90.0,
        4,
        true,
        1.0 / 60.0,
        &skill,
        room_radius,
        MAP_DONUT,
        &mut rng,
    );
    assert!(
        dir_donut.x > 0.5,
        "dodge near Donut inner pit must flip outward away from pit, got {dir_donut:?}"
    );
    assert!(arena_inside(donut_enemy.pos + dir_donut * 36.0, room_radius, MAP_DONUT));
}

#[test]
fn director_is_order_independent_and_weight2_not_deadlocked() {
    // 1) Vec order independence: same spawn_index/role/pos yields identical grants regardless of Vec order.
    let make_pair = |reverse: bool| {
        let mut off = Enemy::new(10, Vec2::new(720.0, 0.0), 50, 90.0, "ranged");
        off.spawn_index = 0;
        let mut on = Enemy::new(11, Vec2::new(170.0, 0.0), 50, 90.0, "ranged");
        on.spawn_index = 1;
        let mut enemies = if reverse { vec![on, off] } else { vec![off, on] };
        let mut dir_state = AttackDirectorState::default();
        let mut director = AttackDirector::new(&enemies, 0.0, 1.0);
        for (idx, e) in enemies.iter().enumerate() {
            let on_screen = e.id == 11;
            director.propose(AttackProposal {
                enemy_idx: idx,
                enemy_id: e.id,
                spawn_index: e.spawn_index,
                role: e.role,
                category: AttackCategory::Ranged,
                weight: 1,
                range_ok: true,
                on_screen,
                sniper_visible: false,
                denied_t: 0.0,
                attack_range: 330.0,
                dist_to_player: e.pos.x,
            });
        }
        director.resolve(&mut enemies, &mut dir_state, 1.0, 1.0 / 60.0, 0.0, 1.0);
        let granted_id = enemies
            .iter()
            .find(|e| e.ai.director_granted)
            .map(|e| e.id);
        (granted_id, dir_state)
    };
    let (g_fwd, s_fwd) = make_pair(false);
    let (g_rev, s_rev) = make_pair(true);
    assert_eq!(g_fwd, Some(11));
    assert_eq!(g_fwd, g_rev);
    assert_eq!(s_fwd, s_rev);

    // 2) Weight-2 (Charger/Spitter/Sniper) commits cleanly on Easy with <5 enemies AND with boss present.
    let easy_coord = ai_skill("easy", 1).coordination; // 0.70
    for role in ["charger", "spitter", "sniper"] {
        let mut unit = Enemy::new(20, Vec2::new(150.0, 0.0), 80, 90.0, role);
        unit.spawn_index = 0;
        let boss = Enemy::new(21, Vec2::new(-250.0, 0.0), 3000, 70.0, "boss_thunder");
        let mut enemies = vec![unit, boss];
        let mut dir_state = AttackDirectorState::default();
        let mut director = AttackDirector::new(&enemies, 0.0, easy_coord);
        assert!(
            director.budget >= 2,
            "weight-2 {role} would deadlock with budget {}",
            director.budget
        );
        director.propose(AttackProposal {
            enemy_idx: 0,
            enemy_id: 20,
            spawn_index: 0,
            role: enemies[0].role,
            category: AttackCategory::Ranged,
            weight: 2,
            range_ok: true,
            on_screen: true,
            sniper_visible: true,
            denied_t: 0.0,
            attack_range: 320.0,
            dist_to_player: 150.0,
        });
        director.resolve(&mut enemies, &mut dir_state, 1.0, 1.0 / 60.0, 0.0, easy_coord);
        assert!(enemies[0].ai.director_granted, "{role} should commit with boss present on easy");
    }

    // 3) breathing_room_left reduces budget for 0.60s after hull loss.
    let mut mem = PerceptionMemory::new(100, 980, 620);
    let mut state = SimState::new(RunSetup::default());
    state.player.hp = 85;
    let p_hit = build_perception(&state, &mut mem, &SimInput::default(), Vec2::ZERO, false, 1.0 / 60.0);
    assert!((p_hit.breathing_room_left - 0.60).abs() < 1e-5);
    let crowd: Vec<Enemy> = (0..12)
        .map(|i| Enemy::new(100 + i, Vec2::new(200.0, 0.0), 50, 90.0, "ranged"))
        .collect();
    let d_normal = AttackDirector::new(&crowd, 0.0, 1.0);
    let d_breath = AttackDirector::new(&crowd, p_hit.breathing_room_left, 1.0);
    assert_eq!(d_breath.budget, d_normal.budget - 1);

    // 4) Engineer does not waste cap grants or keep attack_cd <= 0 when MAX_ACTIVE_CONSTRUCTIONS is full.
    let mut eng_state = SimState::new(RunSetup {
        seed: 505,
        auto_shoot: false,
        ..RunSetup::default()
    });
    eng_state.wave_active = true;
    eng_state.player.hp = 10_000;
    let mut eng = Enemy::new(1, Vec2::new(240.0, 0.0), 100, 90.0, "engineer");
    eng.attack_cd = 0.0;
    eng_state.enemies.push(eng);
    for k in 0..MAX_ACTIVE_CONSTRUCTIONS {
        eng_state.traps.push(Trap::new(
            Vec2::new(100.0 + k as f32 * 10.0, 100.0),
            20.0,
            10,
            10.0,
            0.5,
            "mine",
        ));
    }
    step(&mut eng_state, &SimInput::default(), 1.0 / 60.0);
    assert_eq!(eng_state.enemies[0].ai.sub_state, EnemySubState::None);
    assert!(eng_state.enemies[0].attack_cd > 0.7);
    assert_eq!(eng_state.traps.len(), MAX_ACTIVE_CONSTRUCTIONS);
}

#[test]
fn formation_front_faces_crowd_and_single_centered() {
    // 1) Single member is centered on axis with 0.0 angular offset.
    let mut single = vec![Enemy::new(1, Vec2::new(-320.0, 0.0), 50, 90.0, "tank")];
    let mut spawn_count = 0;
    let mut form = FormationState::new(Vec2::ZERO);
    form.axis = Vec2::new(-1.0, 0.0);
    let p = full_screen_perception(Vec2::ZERO);
    let skill = ai_skill("normal", 1);

    let single_slots = compute_formation_targets(
        &mut single,
        &mut spawn_count,
        &mut form,
        "normal",
        &p,
        &skill,
        760.0,
        MAP_CIRCLE,
        1.0 / 60.0,
    );
    assert_eq!(single[0].ai.formation_slot_ang, Some(0.0));
    let (target, tag) = single_slots[0].unwrap();
    assert_eq!(tag, "wall");
    assert!((target.x + 105.0).abs() < 1.5 && target.y.abs() < 1.5);

    // 2) Mixed squad: axis points from player toward crowd (+x), so Tank/Chaser/Charger
    // sit closer to player (between player & crowd) while Spitter/Ranged/Engineer/Sniper sit behind them.
    let mut squad = vec![
        Enemy::new(1, Vec2::new(300.0, 0.0), 100, 90.0, "tank"),
        Enemy::new(2, Vec2::new(320.0, 20.0), 50, 100.0, "chaser"),
        Enemy::new(3, Vec2::new(330.0, -20.0), 80, 90.0, "charger"),
        Enemy::new(4, Vec2::new(350.0, 10.0), 50, 90.0, "spitter"),
        Enemy::new(5, Vec2::new(370.0, -10.0), 50, 90.0, "ranged"),
        Enemy::new(6, Vec2::new(380.0, 30.0), 60, 90.0, "engineer"),
        Enemy::new(7, Vec2::new(420.0, 0.0), 40, 80.0, "sniper"),
    ];
    let mut squad_form = FormationState::new(Vec2::ZERO);
    let mut sc = 0;
    let slots = compute_formation_targets(
        &mut squad,
        &mut sc,
        &mut squad_form,
        "normal",
        &p,
        &skill,
        760.0,
        MAP_CIRCLE,
        1.0 / 60.0,
    );
    assert!(squad_form.axis.x > 0.95);
    let dist_for = |idx: usize| slots[idx].unwrap().0.length();
    assert!(dist_for(0) < dist_for(1)); // tank < chaser
    assert!(dist_for(1) < dist_for(3)); // chaser < spitter
    assert!(dist_for(3) < dist_for(4)); // spitter < ranged
    assert!(dist_for(4) < dist_for(5)); // ranged < engineer
    assert!(dist_for(5) < dist_for(6)); // engineer < sniper
}

#[test]
fn donut_routes_around_hole() {
    let room_radius = 760.0;
    let pad = 22.0;
    let pit_r = room_radius * DONUT_INNER_RATIO + pad;

    // Diametrically opposite points across the center hole.
    let wp = route_point(
        Vec2::new(-450.0, 0.0),
        Vec2::new(450.0, 0.0),
        MAP_DONUT,
        room_radius,
        pad,
        0,
    );
    assert!(wp.x.is_finite() && wp.y.is_finite());
    assert!(wp.length() >= pit_r - 0.5, "waypoint entered Donut pit: {wp:?}");
    assert!(wp.y.abs() > 20.0, "waypoint did not detour tangentially: {wp:?}");

    // Zero-length & origin degenerate inputs must never return NaN.
    let wp_same = route_point(
        Vec2::new(400.0, 0.0),
        Vec2::new(400.0, 0.0),
        MAP_DONUT,
        room_radius,
        pad,
        1,
    );
    assert!((wp_same - Vec2::new(400.0, 0.0)).length() < 1e-5);

    let wp_origin = route_point(
        Vec2::ZERO,
        Vec2::new(450.0, 0.0),
        MAP_DONUT,
        room_radius,
        pad,
        1,
    );
    assert!(wp_origin.x.is_finite() && wp_origin.y.is_finite());
    assert!(wp_origin.length() >= pit_r - 0.5);

    // Cross map routes via central hub when crossing between orthogonal arms.
    let wp_cross = route_point(
        Vec2::new(0.0, 520.0),
        Vec2::new(-520.0, 0.0),
        MAP_CROSS,
        room_radius,
        pad,
        0,
    );
    let arm_w = room_radius * CROSS_ARM_RATIO - pad;
    assert!(wp_cross.x.abs() <= arm_w && wp_cross.y.abs() <= arm_w);
}

#[test]
fn mass_push_ratio_tank_vs_swarm() {
    let mut enemies = vec![
        Enemy::new(1, Vec2::new(0.0, 0.0), 100, 90.0, "tank"),
        Enemy::new(2, Vec2::new(12.0, 0.0), 30, 110.0, "swarm"),
    ];
    let m_tank = kinematics_for_role(EnemyRole::Tank).mass;
    let m_swarm = kinematics_for_role(EnemyRole::Swarm).mass;
    let expected_ratio = m_tank / m_swarm; // 2.4 / 0.75 = 3.2

    resolve_enemy_body_overlaps(&mut enemies, 760.0, MAP_CIRCLE, 1.0, 1.0 / 60.0);
    let tank_disp = enemies[0].pos.x.abs();
    let swarm_disp = (enemies[1].pos.x - 12.0).abs();
    let observed_ratio = swarm_disp / tank_disp;
    assert!(
        (observed_ratio - expected_ratio).abs() < 0.05,
        "expected push ratio {expected_ratio:.2}, got {observed_ratio:.2} (tank={tank_disp:.3}, swarm={swarm_disp:.3})"
    );

    // Stunned / windup anchor must not be displaced by an overlapping neighbor.
    let mut anchored = vec![
        {
            let mut e = Enemy::new(3, Vec2::new(0.0, 0.0), 100, 90.0, "ranged");
            e.ai.sub_state = EnemySubState::RangedWindup;
            e
        },
        Enemy::new(4, Vec2::new(10.0, 0.0), 50, 100.0, "chaser"),
    ];
    resolve_enemy_body_overlaps(&mut anchored, 760.0, MAP_CIRCLE, 1.0, 1.0 / 60.0);
    assert_eq!(anchored[0].pos, Vec2::ZERO);
    assert!(anchored[1].pos.x > 10.0);
}

#[test]
fn easy_vs_hard_skill_and_determinism() {
    let e = ai_skill("easy", 5);
    let h = ai_skill("hard", 5);
    assert!(e.reaction_s > h.reaction_s);
    assert!(e.lead_quality < h.lead_quality);
    assert!(e.dodge_chance < h.dodge_chance);
    assert!(e.dodge_reaction_s > h.dodge_reaction_s);
    assert!(e.aim_jitter_deg > h.aim_jitter_deg);
    assert!(e.coordination < h.coordination);
    assert!(e.axis_turn_deg_s < h.axis_turn_deg_s);
    assert!(e.weave_mult < h.weave_mult);
    assert!(!e.respects_iframes && h.respects_iframes);

    // Bit-identical determinism across Rayon parallel threshold, Time Slow, Repulsor stun,
    // and all 4 arena shapes, verified with replay_and_verify.
    for map_type in [MAP_CIRCLE, MAP_DONUT, MAP_CROSS, MAP_DIAMOND] {
        let run_once = || {
            let mut state = SimState::new(RunSetup {
                seed: 88_888,
                difficulty: "hard".to_string(),
                map_type: map_type.to_string(),
                ..RunSetup::default()
            });
            state.wave = 7;
            state.wave_active = true;
            state.player.hp = 10_000;
            state.player.time_slow_until = 2.5;
            state.max_enemies = 40;

            let roles = ["chaser", "ranged", "sniper", "charger", "spitter", "flyer", "tank", "engineer"];
            for i in 0..(PARALLEL_MIN_ENEMIES + 12) {
                let ang = (i as f32) * TAU / ((PARALLEL_MIN_ENEMIES + 12) as f32);
                let role = roles[i % roles.len()];
                let raw = Vec2::new(ang.cos() * 340.0, ang.sin() * 340.0);
                let pos = clamp_entity_to_map(raw, state.room_radius, 26.0, map_type);
                let mut enemy = Enemy::new(10_000 + i as u64, pos, 500, 95.0, role);
                if i == 0 {
                    // Exercise stun gating in locomotion & behaviors
                    enemy.stun_until = 1.5;
                    enemy.stun_until = enemy.stun_until.max(REPULSOR_STUN_SECONDS);
                }
                state.enemies.push(enemy);
            }

            let dt = 1.0 / 60.0;
            for f in 0..180usize {
                let t = f as f32 * dt;
                let input = SimInput {
                    move_dir: Vec2::new((t * 1.5).cos(), (t * 1.1).sin()),
                    aim_world: Vec2::new((t * 2.3).cos() * 200.0, (t * 2.3).sin() * 200.0),
                    fire_held: true,
                    boost_held: f % 40 < 10,
                    dash_pressed: f == 45,
                    ultra_pressed: false,
                };
                step(&mut state, &input, dt);
            }
            for e in &state.enemies {
                assert!(e.pos.x.is_finite() && e.pos.y.is_finite());
                assert!(arena_inside(e.pos, state.room_radius, map_type));
            }
            state_hash(&state)
        };

        assert_eq!(
            run_once(),
            run_once(),
            "parallel AI simulation diverged on {map_type}"
        );
    }

    // Also verify Recorder + replay_and_verify across a full run on Donut.
    let dt = 1.0 / 60.0;
    let mut clean_state = SimState::new(RunSetup {
        seed: 99_992,
        difficulty: "hard".to_string(),
        map_type: MAP_DONUT.to_string(),
        ..RunSetup::default()
    });
    let mut clean_rec = Recorder::from_state(&clean_state, clean_state.perception_mem.view_w, clean_state.perception_mem.view_h);
    for f in 0..300usize {
        let t = f as f32 * dt;
        let input = SimInput {
            move_dir: Vec2::new((-t).sin(), t.cos()),
            aim_world: Vec2::new(t.cos() * 250.0, t.sin() * 250.0),
            fire_held: true,
            boost_held: f % 60 < 15,
            dash_pressed: f == 60 || f == 180,
            ultra_pressed: false,
        };
        clean_rec.push_frame_with_state(&input, &clean_state);
        step(&mut clean_state, &input, dt);
    }
    let recording = clean_rec.finalize(&clean_state);
    let verified = replay_and_verify(&recording);
    assert!(
        verified.matches,
        "replay verification failed: actual={} expected={}",
        verified.actual_hash, verified.expected_hash
    );
}
