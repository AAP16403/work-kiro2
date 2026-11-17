use std::f32::consts::SQRT_2;

use plouto_rs::render::models3d::draw_enemy_model;
use plouto_rs::render::particles::ParticleSystem;
use plouto_rs::render::sdf::{linear_rgba, linear_rgba_f, SdfBatch};
use plouto_rs::render::text::TextBatch;
use plouto_rs::render::world::WorldRenderer;
use plouto_rs::sim::behaviors::{BOMBER_FUSE_SECONDS, SWARM_SURGE_TELEGRAPH_SECONDS, TELEGRAPH_OWNER};
use plouto_rs::sim::config::{
    BOMB_BLAST_RADIUS, DONUT_INNER_RATIO, ELITE_MENDER_HEAL, ELITE_MENDER_RADIUS,
    ELITE_REFLECT_COOLDOWN, ELITE_SHIELDED_HP_FRAC, ELITE_SPLIT_COUNT,
    ELITE_VOLATILE_BLAST_RADIUS, ELITE_WARD_DAMAGE_MULT, ELITE_WARD_RADIUS, ISO_SCALE_X,
    MAP_CROSS, MAP_DIAMOND, MAP_DONUT, MAX_ACTIVE_CONSTRUCTIONS,
    REPULSOR_RANGE, SNIPER_LOCK_SECONDS, TANK_DEATH_BLAST_DAMAGE, TANK_DEATH_BLAST_RADIUS,
    TANK_RANGE,
};
use plouto_rs::sim::enemy::{swarm_formation_key, Enemy, EnemySubState};
use plouto_rs::sim::hazards::Trap;
use plouto_rs::sim::level::enemy_stats;
use plouto_rs::sim::math::{arena_inside, dist, Vec2};
use plouto_rs::sim::projectile::Projectile;
use plouto_rs::sim::replay::state_hash;
use plouto_rs::sim::state::{RunSetup, SimEvent, SimInput, SimState};
use plouto_rs::sim::step::step;

const DT: f32 = 1.0 / 60.0;

fn new_active_state(map_type: &str, difficulty: &str, mutators: Vec<String>) -> SimState {
    let mut setup = RunSetup::default();
    setup.seed = 42;
    setup.map_type = map_type.to_string();
    setup.difficulty = difficulty.to_string();
    setup.mutator_ids = mutators;
    setup.auto_shoot = false;
    let mut state = SimState::new(setup);
    state.wave = 4;
    state.wave_active = true;
    state.last_wave_clear = -10.0;
    state
}

fn color_matches(c: [f32; 4], target: [f32; 4], tol: f32) -> bool {
    (c[0] - target[0]).abs() <= tol
        && (c[1] - target[1]).abs() <= tol
        && (c[2] - target[2]).abs() <= tol
}

#[test]
fn tank_armored_surge_reduces_damage_and_death_blast_triggers_on_ultra() {
    // Part A: Armored Surge (push_t > 0.0) reduces damage by 0.65x across damage paths (including Ultra).
    let mut state_surge = new_active_state("circle", "normal", vec![]);
    state_surge.player.pos = Vec2::ZERO;
    state_surge.player.ultra_charges = 2;
    state_surge.player.ultra_variant_idx = 0;

    let mut tank_surge = Enemy::new(state_surge.alloc_id(), Vec2::new(140.0, 0.0), 500, 50.0, "tank");
    tank_surge.ai.push_t = 0.65;
    tank_surge.ai.brace_t = Some(2.0);
    state_surge.enemies.push(tank_surge);

    let mut state_normal = state_surge.clone();
    state_normal.enemies[0].ai.push_t = 0.0;

    let mut input = SimInput::default();
    input.aim_world = Vec2::new(140.0, 0.0);
    input.ultra_pressed = true;

    let events_surge = step(&mut state_surge, &input, DT);
    let events_normal = step(&mut state_normal, &input, DT);

    let dmg_surge = 500 - state_surge.enemies[0].hp;
    let dmg_normal = 500 - state_normal.enemies[0].hp;
    let expected_surge = ((dmg_normal as f32) * 0.65).round().max(1.0) as i32;
    assert_eq!(dmg_surge, expected_surge, "push_t > 0.0 must apply 0.65x armor reduction");
    assert!(
        events_surge.iter().any(|ev| matches!(
            ev,
            SimEvent::HitParticles { color: [255, 185, 90], .. }
        )),
        "armored surge hit should emit amber armor particles"
    );
    assert!(events_normal.iter().any(|ev| matches!(ev, SimEvent::DamageResolved(_))));

    // Part B: Killing Tank via Ultra triggers tank_death_blast (Shockwave 70u + player damage within 70u).
    let mut kill_state = new_active_state("circle", "normal", vec![]);
    kill_state.player.pos = Vec2::ZERO;
    kill_state.player.hp = 100;
    kill_state.player.shield = 0;
    kill_state.player.ultra_charges = 1;
    kill_state.player.ultra_variant_idx = 0;

    let mut weak_tank = Enemy::new(
        kill_state.alloc_id(),
        Vec2::new(TANK_DEATH_BLAST_RADIUS - 12.0, 0.0),
        10,
        50.0,
        "tank",
    );
    weak_tank.ai.push_t = 0.0;
    weak_tank.ai.brace_t = Some(2.0);
    let tank_pos = weak_tank.pos;
    kill_state.enemies.push(weak_tank);

    let mut ultra_in = SimInput::default();
    ultra_in.aim_world = tank_pos;
    ultra_in.ultra_pressed = true;
    let kill_events = step(&mut kill_state, &ultra_in, DT);

    assert!(kill_state.enemies.is_empty(), "tank should be killed by Ultra");
    assert!(
        kill_events.iter().any(|ev| matches!(
            ev,
            SimEvent::Shockwave { max_radius, .. } if (*max_radius - TANK_DEATH_BLAST_RADIUS).abs() < 1e-3
        )),
        "tank_death_blast must fire on Ultra kill"
    );
    assert_eq!(
        kill_state.player.hp,
        100 - TANK_DEATH_BLAST_DAMAGE,
        "player inside 70u must take tank death blast damage"
    );

    // Part C: Tank windup telegraph beam matches TANK_RANGE (518.0).
    let mut beam_state = new_active_state("circle", "normal", vec![]);
    beam_state.player.pos = Vec2::ZERO;
    let mut t_enemy = Enemy::new(beam_state.alloc_id(), Vec2::new(110.0, 0.0), 100, 50.0, "tank");
    t_enemy.attack_cd = 0.0;
    t_enemy.ai.brace_t = Some(2.0);
    beam_state.enemies.push(t_enemy);
    for _ in 0..5 {
        step(&mut beam_state, &SimInput::default(), DT);
        if beam_state.enemies[0].ai.sub_state == EnemySubState::TankWindup {
            break;
        }
    }
    assert_eq!(beam_state.enemies[0].ai.sub_state, EnemySubState::TankWindup);
    let beam = beam_state
        .lasers
        .iter()
        .find(|l| l.owner == TELEGRAPH_OWNER)
        .expect("tank windup should emit a telegraph laser");
    let beam_len = (beam.end - beam.start).length();
    assert!(
        (beam_len - TANK_RANGE).abs() < 1.0,
        "tank telegraph length {beam_len} must match TANK_RANGE ({TANK_RANGE})"
    );
}

#[test]
fn engineer_mines_stay_outside_donut_hole_and_spaced_70_units() {
    let mut state = new_active_state(MAP_DONUT, "normal", vec![]);
    // Place player on the Donut ring near the inner pit rim.
    let inner_hole = state.room_radius * DONUT_INNER_RATIO;
    state.player.pos = Vec2::new(inner_hole + 72.0, 0.0);

    // Pre-seed one mine between the player and the Donut pit (> 33u from player so it
    // does not detonate, < 70u from player so Engineer must pick spaced offsets).
    state.traps.push(Trap::new(
        Vec2::new(inner_hole + 34.0, 0.0),
        28.0,
        16,
        30.0,
        0.7,
        "mine",
    ));

    let mut eng = Enemy::new(
        state.alloc_id(),
        Vec2::new(inner_hole + 160.0, 40.0),
        100,
        55.0,
        "engineer",
    );
    eng.attack_cd = 0.0;
    state.enemies.push(eng);

    for _ in 0..480 {
        step(&mut state, &SimInput::default(), DT);
        if state.traps.len() >= 3 {
            break;
        }
    }

    assert!(
        state.traps.len() >= 3,
        "engineer should place at least 2 spaced mines outside the pre-seeded one (got {})",
        state.traps.len()
    );

    for (i, trap) in state.traps.iter().enumerate() {
        assert!(
            arena_inside(trap.pos, state.room_radius, MAP_DONUT),
            "mine {i} at {:?} must be inside Donut arena",
            trap.pos
        );
        assert!(
            trap.pos.length() >= inner_hole + 30.0,
            "mine {i} at {:?} (r={}) must stay outside Donut inner hole ({inner_hole})",
            trap.pos,
            trap.pos.length()
        );
        for (j, other) in state.traps.iter().enumerate().skip(i + 1) {
            let d = dist(trap.pos, other.pos);
            assert!(
                d >= 70.0 - 1e-2,
                "mines {i} and {j} must be spaced >= 70.0 units apart (got {d})"
            );
        }
    }

    // Verify Cross and Diamond clamping + construction cap avoiding wasted windup.
    for map in [MAP_CROSS, MAP_DIAMOND] {
        let mut s = new_active_state(map, "normal", vec![]);
        s.player.pos = Vec2::new(s.room_radius * 0.95, 0.0);
        let mut e = Enemy::new(
            s.alloc_id(),
            Vec2::new(s.room_radius * 0.65, 0.0),
            100,
            55.0,
            "engineer",
        );
        e.attack_cd = 0.0;
        s.enemies.push(e);
        for _ in 0..90 {
            step(&mut s, &SimInput::default(), DT);
            if s.traps.len() == 1 {
                break;
            }
        }
        assert_eq!(s.traps.len(), 1, "engineer should place mine in {map}");
        assert!(
            arena_inside(s.traps[0].pos, s.room_radius, map),
            "mine must clamp inside {map}"
        );
    }

    // When traps are at MAX_ACTIVE_CONSTRUCTIONS, Engineer must not enter EngineerWindup.
    let mut capped = new_active_state("circle", "normal", vec![]);
    for k in 0..MAX_ACTIVE_CONSTRUCTIONS {
        capped.traps.push(Trap::new(
            Vec2::new(-300.0 + (k as f32) * 40.0, 200.0),
            28.0,
            16,
            30.0,
            0.7,
            "mine",
        ));
    }
    let mut e_cap = Enemy::new(capped.alloc_id(), Vec2::new(150.0, 0.0), 100, 55.0, "engineer");
    e_cap.attack_cd = 0.0;
    capped.enemies.push(e_cap);
    step(&mut capped, &SimInput::default(), DT);
    assert_ne!(
        capped.enemies[0].ai.sub_state,
        EnemySubState::EngineerWindup,
        "capped constructions must not consume a scheduler slot"
    );
}

#[test]
fn engineer_support_pulses_shield_and_hides_idle_aura() {
    let mut state = new_active_state("circle", "normal", vec![]);
    state.player.pos = Vec2::new(-500.0, 0.0);

    let mut eng = Enemy::new(state.alloc_id(), Vec2::new(0.0, 0.0), 80, 55.0, "engineer");
    eng.ai.support_cd = 0.05;
    eng.ai.support_pulse = 0.0;
    eng.attack_cd = 5.0;
    state.enemies.push(eng);

    let ally = Enemy::new(state.alloc_id(), Vec2::new(120.0, 0.0), 100, 50.0, "chaser");
    state.enemies.push(ally);

    // Check idle render first: support_pulse == 0.0 must NOT emit the green support arc.
    let mut alpha_idle = SdfBatch::with_capacity(64);
    let mut add_idle = SdfBatch::with_capacity(64);
    draw_enemy_model(
        &state.enemies[0],
        &mut alpha_idle,
        &mut add_idle,
        [200.0, 200.0],
        Vec2::new(1.0, 0.0),
        1.0,
        0.0,
        0.0,
        0.5,
        0.0,
        1.0,
        [80, 240, 180],
        false,
    );
    let green_arc_col = linear_rgba_f([95, 245, 195], 0.35, 1.35);
    assert!(
        !add_idle
            .instances
            .iter()
            .any(|inst| inst.kind == 3 && color_matches(inst.color, green_arc_col, 0.05)),
        "idle engineer (support_pulse <= 0) must hide green support arc in models3d"
    );

    // Stunned engineer must NOT tick support_cd.
    state.enemies[0].stun_until = state.time + 1.0;
    step(&mut state, &SimInput::default(), DT);
    assert_eq!(state.enemies[1].shield, 0, "stunned engineer must not pulse shield");
    state.enemies[0].stun_until = -1.0;

    // Advance until support pulse fires.
    let mut pulse_events = Vec::new();
    for _ in 0..10 {
        let evs = step(&mut state, &SimInput::default(), DT);
        if state.enemies[1].shield > 0 {
            pulse_events = evs;
            break;
        }
    }
    assert_eq!(state.enemies[1].shield, 8, "engineer support pulse must grant +8 shield");
    assert!(state.enemies[0].ai.support_pulse > 0.0, "support_pulse must activate after pulsing");
    assert!(
        pulse_events.iter().any(|ev| matches!(
            ev,
            SimEvent::TetherBeam { color: [95, 245, 195], .. }
        )),
        "engineer pulse must emit green TetherBeam"
    );
    assert!(
        pulse_events.iter().any(|ev| matches!(
            ev,
            SimEvent::Popup { text, .. } if text == "+8 SHIELD"
        )),
        "engineer pulse must emit +8 SHIELD popup"
    );

    // Active render: support_pulse > 0.0 MUST emit the green support arc in models3d AND ring in WorldRenderer.
    let mut alpha_active = SdfBatch::with_capacity(64);
    let mut add_active = SdfBatch::with_capacity(64);
    draw_enemy_model(
        &state.enemies[0],
        &mut alpha_active,
        &mut add_active,
        [200.0, 200.0],
        Vec2::new(1.0, 0.0),
        1.0,
        0.0,
        0.0,
        0.5,
        0.0,
        1.0,
        [80, 240, 180],
        false,
    );
    assert!(
        add_active
            .instances
            .iter()
            .any(|inst| inst.kind == 3 && color_matches(inst.color, green_arc_col, 0.05)),
        "active engineer (support_pulse > 0) must draw green support arc"
    );

    // Also verify EngineerWindup draws the tether beam in WorldRenderer::draw_world.
    state.enemies[0].ai.sub_state = EnemySubState::EngineerWindup;
    state.enemies[0].ai.sub_timer = 0.30;
    state.enemies[0].ai.move_target = Vec2::new(60.0, 40.0);
    let mut renderer = WorldRenderer::new();
    let mut wa = SdfBatch::with_capacity(512);
    let mut wadd = SdfBatch::with_capacity(512);
    let mut uia = SdfBatch::with_capacity(128);
    let mut uit = TextBatch::default();
    renderer.draw_world(
        &state,
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
    let tether_col = linear_rgba_f([125, 255, 210], 0.8, 1.8);
    assert!(
        wadd.instances
            .iter()
            .any(|inst| inst.kind == 1 && color_matches(inst.color, tether_col, 0.25)),
        "EngineerWindup must draw tether line in WorldRenderer"
    );
}

#[test]
fn mender_heals_scaled_amount_and_emits_tether() {
    let mut state = new_active_state("circle", "normal", vec![]);
    state.player.pos = Vec2::new(-600.0, 0.0);

    let mut mender = Enemy::new(state.alloc_id(), Vec2::ZERO, 120, 50.0, "ranged");
    mender.is_elite = true;
    mender.elite_affix = "mender".to_string();
    mender.ai.mender_cd = 0.02;
    mender.attack_cd = 5.0;
    state.enemies.push(mender);

    // Injured ally inside 165u radius with max_hp = 200 -> expected heal = 8 + round(200 * 0.12) = 32.
    let mut ally_in = Enemy::new(
        state.alloc_id(),
        Vec2::new(ELITE_MENDER_RADIUS - 10.0, 0.0),
        200,
        50.0,
        "tank",
    );
    ally_in.hp = 100;
    ally_in.attack_cd = 5.0;
    state.enemies.push(ally_in);

    // Injured ally outside 165u radius must NOT be healed.
    let mut ally_out = Enemy::new(
        state.alloc_id(),
        Vec2::new(ELITE_MENDER_RADIUS + 20.0, 0.0),
        200,
        50.0,
        "tank",
    );
    ally_out.hp = 100;
    ally_out.attack_cd = 5.0;
    state.enemies.push(ally_out);

    let mut events = Vec::new();
    for _ in 0..5 {
        let evs = step(&mut state, &SimInput::default(), DT);
        if state.enemies[1].hp > 100 {
            events = evs;
            break;
        }
    }

    let expected_heal = ELITE_MENDER_HEAL + (200.0_f32 * 0.12).round() as i32;
    assert_eq!(state.enemies[1].hp, 100 + expected_heal);
    assert_eq!(state.enemies[2].hp, 100, "ally outside 165u must not be healed");
    assert!(events.iter().any(|ev| matches!(ev, SimEvent::TetherBeam { .. })));
    assert!(events.iter().any(|ev| matches!(
        ev,
        SimEvent::Popup { text, .. } if text == &format!("+{expected_heal}")
    )));

    // ParticleSystem must spawn a tether beam & WorldRenderer must render the 165u ground ring.
    let mut ps = ParticleSystem::new();
    ps.handle_sim_events(&events, false);
    let mut batch_ps = SdfBatch::with_capacity(64);
    ps.draw_world(&mut batch_ps, state.time, Vec2::ZERO, 980.0, 620.0, Vec2::ZERO);
    assert!(
        batch_ps.instances.iter().any(|inst| inst.kind == 1),
        "ParticleSystem must draw TetherBeam line"
    );

    let mut renderer = WorldRenderer::new();
    let mut wa = SdfBatch::with_capacity(512);
    let mut wadd = SdfBatch::with_capacity(512);
    let mut uia = SdfBatch::with_capacity(128);
    let mut uit = TextBatch::default();
    renderer.draw_world(
        &state,
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
    let expected_rx = ELITE_MENDER_RADIUS * SQRT_2 * ISO_SCALE_X;
    assert!(
        wadd.instances.iter().any(|inst| {
            inst.kind == 0 && inst.params[1] > 0.0 && (inst.p1[0] - expected_rx).abs() < 2.0
        }),
        "Mender 165u ground ring must render in WorldRenderer"
    );
}

#[test]
fn reflector_ignores_shards_caps_damage_and_respects_cooldown() {
    let mut state = new_active_state("circle", "normal", vec![]);
    state.wave = 4; // cap = 18 + 4/2 = 20
    state.player.pos = Vec2::ZERO;
    state.runtime.enable_shards = true;

    let mut refl = Enemy::new(state.alloc_id(), Vec2::new(160.0, 0.0), 200, 50.0, "ranged");
    refl.is_elite = true;
    refl.elite_affix = "reflector".to_string();
    refl.attack_cd = 10.0;
    let refl_id = refl.id;
    state.enemies.push(refl);

    // 1. Critical shards must NOT trigger reflect_back and must damage the Reflector.
    state.shards.spawn_crit_shards(
        Vec2::new(148.0, 0.0),
        Vec2::new(300.0, 0.0),
        40,
        0,
        [255, 225, 75],
    );
    for _ in 0..8 {
        step(&mut state, &SimInput::default(), DT);
        if state.enemies[0].hp < 200 {
            break;
        }
    }
    assert!(state.enemies[0].hp < 200, "shards must bypass reflector");
    assert!(state.pending_reflects.is_empty(), "shards must not trigger PendingReflect");
    assert!((state.enemies[0].ai.reflect_cd_left).abs() < 1e-5);

    // Reset HP for projectile reflection check.
    state.enemies[0].hp = 200;
    let hash_before = state_hash(&state);

    // 2. High-damage player projectile gets reflected, deals 0 damage, caps reflected damage to 18 + wave/2 = 20.
    let mut big_shot = Projectile::new(
        Vec2::new(140.0, 0.0),
        Vec2::new(1200.0, 0.0),
        120,
        1.0,
        "player",
        "bullet",
    );
    big_shot.prev_pos = Some(Vec2::new(130.0, 0.0));
    state.projectiles.push(big_shot);

    step(&mut state, &SimInput::default(), DT);
    assert_eq!(state.enemies[0].hp, 200, "reflected shot must deal 0 damage to reflector");
    assert!(state.enemies[0].ai.reflect_cd_left > ELITE_REFLECT_COOLDOWN - 0.1);
    assert_eq!(state.pending_reflects.len(), 1);
    assert_eq!(state.pending_reflects[0].damage, 18 + state.wave / 2);
    assert_ne!(
        state_hash(&state),
        hash_before,
        "pending_reflects must be reflected in replay::state_hash"
    );

    // Verify 0.16s TELEGRAPH_OWNER bounce beam exists and renders in WorldRenderer while t < warn (0.16).
    let bounce_beam = state
        .lasers
        .iter()
        .find(|l| l.owner == TELEGRAPH_OWNER)
        .expect("reflector must emit a TELEGRAPH_OWNER bounce beam");
    assert!((bounce_beam.warn + bounce_beam.ttl - 0.16).abs() < 1e-4);
    assert!(bounce_beam.t < bounce_beam.warn);

    // 3. Second projectile while on cooldown must NOT reflect and MUST damage the Reflector.
    let mut follow_up = Projectile::new(
        Vec2::new(140.0, 0.0),
        Vec2::new(1200.0, 0.0),
        35,
        1.0,
        "player",
        "bullet",
    );
    follow_up.prev_pos = Some(Vec2::new(130.0, 0.0));
    state.projectiles.push(follow_up);
    step(&mut state, &SimInput::default(), DT);
    assert_eq!(state.enemies[0].hp, 165, "cooldown shot must hit reflector normally");
    assert_eq!(state.pending_reflects.len(), 1);

    // 4. Even if Reflector is killed during the 0.16s delay (and under Time Slow!),
    // the telegraph bounce beam expires cleanly at 0.16s of enemy_dt and PendingReflect releases.
    state.player.time_slow_until = state.time + 5.0; // enemy_dt = 0.5 * dt
    state.enemies.retain(|e| e.id != refl_id);

    // Step 0.10s real time (0.05s enemy_dt): beam & PendingReflect must still be active.
    for _ in 0..6 {
        step(&mut state, &SimInput::default(), DT);
    }
    assert_eq!(state.pending_reflects.len(), 1, "PendingReflect must obey enemy_dt (Time Slow)");
    assert!(
        state.lasers.iter().any(|l| l.owner == TELEGRAPH_OWNER),
        "bounce beam must remain active under Time Slow before 0.16s enemy_dt"
    );

    // Finish remaining ~0.24s real time (> 0.12s enemy_dt): bounce beam expires and projectile spawns.
    for _ in 0..16 {
        step(&mut state, &SimInput::default(), DT);
    }
    assert!(state.pending_reflects.is_empty());
    assert!(
        !state.lasers.iter().any(|l| l.owner == TELEGRAPH_OWNER),
        "bounce beam must expire cleanly even after Reflector dies"
    );
    assert!(
        state
            .projectiles
            .iter()
            .any(|p| p.owner == "enemy" && p.source == "reflector" && p.damage == 20),
        "PendingReflect must release capped reflector projectile"
    );
}

#[test]
fn shielded_elite_hides_shield_overlay_when_broken() {
    let mut state = new_active_state("circle", "normal", vec![]);
    state.player.pos = Vec2::new(-500.0, 0.0);
    let mut shielded = Enemy::new(state.alloc_id(), Vec2::ZERO, 100, 50.0, "chaser");
    shielded.is_elite = true;
    shielded.elite_affix = "shielded".to_string();
    shielded.shield = ((100.0 * ELITE_SHIELDED_HP_FRAC).round() as i32).max(1);
    state.enemies.push(shielded);

    let mut renderer = WorldRenderer::new();
    let count_shield_markers = |r: &mut WorldRenderer, s: &SimState| -> (usize, usize) {
        let mut wa = SdfBatch::with_capacity(512);
        let mut wadd = SdfBatch::with_capacity(512);
        let mut uia = SdfBatch::with_capacity(128);
        let mut uit = TextBatch::default();
        r.draw_world(
            s,
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
        let hex_fill = linear_rgba([80, 195, 255], 34, 1.0);
        let hex_count = wa
            .instances
            .iter()
            .filter(|inst| color_matches(inst.color, hex_fill, 0.02))
            .count();
        let node_col = linear_rgba([210, 238, 255], 235, 1.75);
        let node_count = wadd
            .instances
            .iter()
            .filter(|inst| inst.kind == 0 && color_matches(inst.color, node_col, 0.05))
            .count();
        (hex_count, node_count)
    };

    let (hex_with_shield, nodes_with_shield) = count_shield_markers(&mut renderer, &state);
    assert!(hex_with_shield > 0, "shielded elite with shield > 0 must render hex barrier");
    assert!(nodes_with_shield >= 4, "shielded elite with shield > 0 must render 4 orbital nodes");

    state.enemies[0].shield = 0;
    let (hex_broken, nodes_broken) = count_shield_markers(&mut renderer, &state);
    assert_eq!(hex_broken, 0, "broken shield (e.shield <= 0) must hide hex barrier");
    assert_eq!(nodes_broken, 0, "broken shield (e.shield <= 0) must hide shielded elite overlay");
}

#[test]
fn bomber_ring_renders_immediately_and_bomb_flies_over_player_to_target() {
    let mut state = new_active_state("circle", "normal", vec![]);
    let start = Vec2::new(-180.0, 0.0);
    let target = Vec2::new(180.0, 0.0);
    // Player stands directly on the flight path at (0, 0) — outside the 72u landing blast radius.
    state.player.pos = Vec2::ZERO;
    state.player.hp = 100;
    state.player.shield = 0;

    let vel = (target - start) / BOMBER_FUSE_SECONDS;
    let bomb = Projectile::new(start, vel, 18, BOMBER_FUSE_SECONDS, "enemy", "bomb").with_source("bomber");
    state.projectiles.push(bomb);
    // Keep wave active so wave-clear doesn't interrupt flight.
    let mut anchor = Enemy::new(state.alloc_id(), Vec2::new(0.0, 500.0), 500, 0.0, "egg_sac");
    anchor.ai.hatch_timer = 999.0;
    state.enemies.push(anchor);

    let mut renderer = WorldRenderer::new();
    let expected_blast_rx = BOMB_BLAST_RADIUS * SQRT_2 * ISO_SCALE_X;
    let count_blast_rings = |r: &mut WorldRenderer, s: &SimState| -> usize {
        let mut wa = SdfBatch::with_capacity(512);
        let mut wadd = SdfBatch::with_capacity(512);
        let mut uia = SdfBatch::with_capacity(128);
        let mut uit = TextBatch::default();
        r.draw_world(
            s,
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
        wadd.instances
            .iter()
            .filter(|inst| {
                inst.kind == 0 && inst.params[1] > 0.0 && (inst.p1[0] - expected_blast_rx).abs() < 1.0
            })
            .count()
    };

    // Immediately after launch (p.ttl = 1.25 > 0.52), ground blast ring must render!
    assert!(
        count_blast_rings(&mut renderer, &state) >= 1,
        "bomber 72u blast ring must render immediately at launch (p.ttl > 0.52)"
    );

    // Safety check: flight_duration = 0.0 must not produce NaN in draw_world.
    let mut zero_dur_state = state.clone();
    zero_dur_state.projectiles[0].flight_duration = 0.0;
    zero_dur_state.projectiles[0].ttl = 0.0;
    let mut wa = SdfBatch::with_capacity(512);
    let mut wadd = SdfBatch::with_capacity(512);
    let mut uia = SdfBatch::with_capacity(128);
    let mut uit = TextBatch::default();
    renderer.draw_world(
        &zero_dur_state,
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
    assert!(
        wadd.instances
            .iter()
            .all(|inst| inst.p0[0].is_finite() && inst.p0[1].is_finite()),
        "zero flight_duration bomb must not emit NaN"
    );

    // Step across the full flight: bomb must fly OVER the player at (0, 0) without mid-air contact,
    // still render its blast ring at ttl <= 0.52, and detonate at `target`.
    let mut saw_late_ring = false;
    let mut explosion_pos = None;
    for _ in 0..90 {
        let evs = step(&mut state, &SimInput::default(), DT);
        if let Some(p) = state.projectiles.first() {
            if p.ttl <= 0.52 && count_blast_rings(&mut renderer, &state) >= 1 {
                saw_late_ring = true;
            }
        }
        for ev in evs {
            if let SimEvent::DeathExplosion { pos, behavior, .. } = ev {
                if behavior == "bomber_blast" {
                    explosion_pos = Some(pos);
                }
            }
        }
        if explosion_pos.is_some() {
            break;
        }
    }

    assert!(saw_late_ring, "bomber blast ring must also render during p.ttl <= 0.52");
    let exp = explosion_pos.expect("bomb must detonate via ttl_expired");
    assert!(
        dist(exp, target) < 1.0,
        "bomb must detonate at landing target {:?}, got {:?}",
        target,
        exp
    );
    assert_eq!(state.player.hp, 100, "bomb must fly over player at (0,0) without mid-air hit");

    // Verify player inside 72u of landing spot DOES take damage on ttl_expired.
    let mut hit_state = new_active_state("circle", "normal", vec![]);
    hit_state.player.pos = target + Vec2::new(40.0, 0.0);
    hit_state.player.hp = 100;
    hit_state.player.shield = 0;
    let mut anchor2 = Enemy::new(hit_state.alloc_id(), Vec2::new(0.0, 500.0), 500, 0.0, "egg_sac");
    anchor2.ai.hatch_timer = 999.0;
    hit_state.enemies.push(anchor2);
    hit_state.projectiles.push(
        Projectile::new(start, vel, 18, BOMBER_FUSE_SECONDS, "enemy", "bomb").with_source("bomber"),
    );
    for _ in 0..90 {
        step(&mut hit_state, &SimInput::default(), DT);
        if hit_state.projectiles.is_empty() {
            break;
        }
    }
    assert_eq!(hit_state.player.hp, 82, "bomb detonation must damage player within 72u");
}

#[test]
fn charger_updates_charge_dir_during_windup_and_clamps_inside_arena() {
    // Part A: < 120 units of clear path prevents Charger from committing.
    let mut blocked = new_active_state("circle", "normal", vec![]);
    let edge_x = blocked.room_radius - 60.0;
    blocked.player.pos = Vec2::new(edge_x + 30.0, 0.0);
    let mut c_blocked = Enemy::new(blocked.alloc_id(), Vec2::new(edge_x - 30.0, 0.0), 80, 70.0, "charger");
    c_blocked.attack_cd = 0.0;
    blocked.enemies.push(c_blocked);
    for _ in 0..10 {
        step(&mut blocked, &SimInput::default(), DT);
        assert_ne!(
            blocked.enemies[0].ai.sub_state,
            EnemySubState::ChargerWindup,
            "charger with < 120u clear path must not commit to windup"
        );
    }

    // Part B: Moving player updates charge_dir during ChargerWindup (timer > 0.15)
    // and clamps charge_target inside the arena (tested on Diamond near corner).
    let mut state = new_active_state(MAP_DIAMOND, "normal", vec![]);
    let corner = state.room_radius * SQRT_2 - 35.0;
    state.player.pos = Vec2::new(corner, 0.0);
    let mut charger = Enemy::new(
        state.alloc_id(),
        Vec2::new(corner - 160.0, 0.0),
        100,
        70.0,
        "charger",
    );
    charger.attack_cd = 0.0;
    state.enemies.push(charger);

    for _ in 0..5 {
        step(&mut state, &SimInput::default(), DT);
        if state.enemies[0].ai.sub_state == EnemySubState::ChargerWindup {
            break;
        }
    }
    assert_eq!(state.enemies[0].ai.sub_state, EnemySubState::ChargerWindup);
    let initial_dir = state.enemies[0].ai.charge_dir;

    // Move player perpendicular (+Y) while timer > 0.15 so Charger tracks and updates charge_dir.
    let mut move_in = SimInput::default();
    move_in.move_dir = Vec2::new(0.0, 1.0);
    for _ in 0..12 {
        step(&mut state, &move_in, DT);
    }
    let updated_dir = state.enemies[0].ai.charge_dir;
    assert!(
        updated_dir.y > initial_dir.y + 0.05,
        "charge_dir must update during ChargerWindup (initial={initial_dir:?}, updated={updated_dir:?})"
    );
    assert!(
        arena_inside(state.enemies[0].ai.charge_target, state.room_radius, MAP_DIAMOND),
        "charge_target {:?} must be clamped inside Diamond arena",
        state.enemies[0].ai.charge_target
    );
    let beam = state
        .lasers
        .iter()
        .find(|l| l.owner == TELEGRAPH_OWNER)
        .expect("charger windup must maintain telegraph laser");
    assert!(
        dist(beam.end, state.enemies[0].ai.charge_target) < 1e-2,
        "telegraph beam end must match charge_target"
    );
}

#[test]
fn ranged_second_burst_shot_uses_windup_telegraph() {
    let mut state = new_active_state("circle", "normal", vec![]);
    state.player.pos = Vec2::new(200.0, 0.0);
    let mut ranged = Enemy::new(state.alloc_id(), Vec2::ZERO, 60, 50.0, "ranged");
    ranged.ai.sub_state = EnemySubState::RangedWindup;
    ranged.ai.sub_timer = 0.05;
    ranged.ai.burst_left = 2;
    ranged.ai.sniper_aim = Vec2::new(400.0, 0.0);
    state.enemies.push(ranged);

    // Step past first shot release.
    for _ in 0..5 {
        step(&mut state, &SimInput::default(), DT);
        if state.projectiles.len() == 1 {
            break;
        }
    }
    assert_eq!(state.projectiles.len(), 1, "shot #1 should fire");
    assert_eq!(state.enemies[0].ai.burst_left, 1, "one burst shot must remain");
    assert_eq!(
        state.enemies[0].ai.sub_state,
        EnemySubState::RangedWindup,
        "shot #2 must enter RangedWindup"
    );
    assert!(
        state.enemies[0].ai.sub_timer > 0.15 && state.enemies[0].ai.sub_timer <= 0.21,
        "shot #2 windup timer should be ~0.20s, got {}",
        state.enemies[0].ai.sub_timer
    );
    let second_beam_id = state.enemies[0]
        .ai
        .telegraph_beam_id
        .expect("shot #2 windup must attach a telegraph_beam_id");
    assert!(
        state
            .lasers
            .iter()
            .any(|l| l.id == second_beam_id && l.owner == TELEGRAPH_OWNER),
        "shot #2 telegraph beam must exist in state.lasers"
    );

    // Step through shot #2 windup -> fires shot #2 and cleans up telegraph.
    for _ in 0..16 {
        step(&mut state, &SimInput::default(), DT);
        if state.projectiles.len() == 2 {
            break;
        }
    }
    assert_eq!(state.projectiles.len(), 2, "shot #2 must fire after windup");
    assert_eq!(state.enemies[0].ai.sub_state, EnemySubState::None);
    assert!(state.enemies[0].ai.telegraph_beam_id.is_none());
    assert!(!state.lasers.iter().any(|l| l.id == second_beam_id));
}

#[test]
fn swarm_surge_dives_inward_and_separates_across_subgroups() {
    let mut state = new_active_state("circle", "normal", vec![]);
    state.player.pos = Vec2::ZERO;

    // Pick spawn indices whose swarm_formation_key maps to subgroups 0, 1, 2.
    let mut found = [None; 3];
    for idx in 0_i64..40 {
        let mut probe = Enemy::new(1, Vec2::ZERO, 10, 100.0, "swarm");
        probe.spawn_index = idx;
        let (g, _) = swarm_formation_key(&probe);
        if found[g].is_none() {
            found[g] = Some(idx);
        }
    }
    let idx0 = found[0].unwrap();
    let idx1 = found[1].unwrap();
    let idx2 = found[2].unwrap();

    // Place subgroup 0 and subgroup 1 within < 52u (and > 26.6u contact overlap) to verify
    // inter-subgroup separation pushes them apart rather than letting them merge.
    let mut s0 = Enemy::new(state.alloc_id(), Vec2::new(220.0, -15.0), 40, 120.0, "swarm");
    s0.spawn_index = idx0;
    s0.ai.heading = Vec2::new(0.0, -1.0);
    let mut s1 = Enemy::new(state.alloc_id(), Vec2::new(220.0, 15.0), 40, 120.0, "swarm");
    s1.spawn_index = idx1;
    s1.ai.heading = Vec2::new(0.0, 1.0);
    let mut s2 = Enemy::new(state.alloc_id(), Vec2::new(-220.0, 0.0), 40, 120.0, "swarm");
    s2.spawn_index = idx2;
    state.enemies.extend([s0, s1, s2]);

    let initial_gap = dist(state.enemies[0].pos, state.enemies[1].pos);
    for _ in 0..15 {
        step(&mut state, &SimInput::default(), DT);
    }
    let separated_gap = dist(state.enemies[0].pos, state.enemies[1].pos);
    assert!(
        separated_gap > initial_gap,
        "different swarm subgroups within 52u must separate ({initial_gap} -> {separated_gap})"
    );

    // Advance until subgroup 0 enters SurgeTelegraph, then Surge (ring_r = 14.0).
    let mut saw_telegraph = false;
    let mut saw_surge = false;
    let surge_start_dist;
    for _ in 0..160 {
        step(&mut state, &SimInput::default(), DT);
        if let Some(brain) = &state.swarm_brain {
            if brain.mode == "surge_telegraph" {
                saw_telegraph = true;
                assert!(brain.mode_t <= SWARM_SURGE_TELEGRAPH_SECONDS + 0.05);
            }
            if brain.mode == "surge" {
                saw_surge = true;
                assert!((brain.ring_r - 14.0).abs() < 1e-4, "Surge ring_r must be 14.0");
                break;
            }
        }
    }
    assert!(saw_telegraph, "subgroup 0 must pass through SurgeTelegraph");
    assert!(saw_surge, "subgroup 0 must enter Surge");

    // During Surge, subgroup 0 dives inward toward player.
    surge_start_dist = state.enemies[0].pos.length();
    for _ in 0..30 {
        step(&mut state, &SimInput::default(), DT);
    }
    assert!(
        state.enemies[0].pos.length() < surge_start_dist,
        "subgroup 0 must dive inward during Surge ({surge_start_dist} -> {})",
        state.enemies[0].pos.length()
    );
}

#[test]
fn egg_sac_hatched_swarmers_scale_with_difficulty_and_frenzy() {
    let run_hatch = |difficulty: &str, wave: i32, mutators: Vec<String>| -> Vec<Enemy> {
        let mut state = new_active_state("circle", difficulty, mutators);
        state.wave = wave;
        state.player.pos = Vec2::new(-500.0, 0.0);
        let mut sac = Enemy::new(state.alloc_id(), Vec2::new(200.0, 0.0), 40, 0.0, "egg_sac");
        sac.ai.hatch_timer = 0.02;
        sac.ai.max_hatch_timer = 4.0;
        state.enemies.push(sac);

        step(&mut state, &SimInput::default(), DT);
        step(&mut state, &SimInput::default(), DT);
        state
            .enemies
            .into_iter()
            .filter(|e| e.behavior == "swarm")
            .collect()
    };

    let easy_w1 = run_hatch("easy", 1, vec![]);
    let hard_w10_frenzy = run_hatch("hard", 10, vec!["frenzy".to_string()]);

    assert_eq!(easy_w1.len(), 3, "egg_sac should hatch 3 swarmers");
    assert_eq!(hard_w10_frenzy.len(), 3, "egg_sac should hatch 3 swarmers on hard+frenzy");

    let (expected_hp, expected_base_speed, expected_atk) = enemy_stats("swarm", 10, "hard");
    let expected_speed = expected_base_speed * 1.20; // frenzy enemy_speed_mult = 1.20

    for sw in &hard_w10_frenzy {
        assert_eq!(sw.hp, expected_hp);
        assert_eq!(sw.max_hp, expected_hp);
        assert!(
            (sw.speed - expected_speed).abs() < 0.1,
            "expected frenzy+hard speed {expected_speed}, got {}",
            sw.speed
        );
        assert!((sw.ai.attack_mult - expected_atk).abs() < 1e-4);
        assert!(sw.hp > easy_w1[0].hp);
        assert!(sw.speed > easy_w1[0].speed);
    }
}

#[test]
fn elites_and_remaining_regulars_edge_cases() {
    // 1. Warden reduces ally damage (0.75x) + emits WardAbsorb + ParticleSystem sparks,
    //    Splitter clamps children inside Donut/Cross, Volatile emits 130u Shockwave.
    let mut state = new_active_state(MAP_DONUT, "normal", vec![]);
    let inner = state.room_radius * DONUT_INNER_RATIO;
    state.player.pos = Vec2::new(-500.0, 0.0);

    let mut warden = Enemy::new(state.alloc_id(), Vec2::new(inner + 40.0, 0.0), 200, 50.0, "tank");
    warden.is_elite = true;
    warden.elite_affix = "warden".to_string();
    warden.attack_cd = 10.0;
    state.enemies.push(warden);

    let mut ally = Enemy::new(
        state.alloc_id(),
        Vec2::new(inner + 40.0 + ELITE_WARD_RADIUS - 20.0, 0.0),
        200,
        50.0,
        "chaser",
    );
    ally.attack_cd = 10.0;
    state.enemies.push(ally);

    let mut shot = Projectile::new(
        Vec2::new(inner + 40.0 + ELITE_WARD_RADIUS - 25.0, 0.0),
        Vec2::new(1000.0, 0.0),
        40,
        1.0,
        "player",
        "bullet",
    );
    shot.prev_pos = Some(Vec2::new(inner + 40.0 + ELITE_WARD_RADIUS - 35.0, 0.0));
    state.projectiles.push(shot);
    let evs = step(&mut state, &SimInput::default(), DT);
    let expected_warded_dmg = (40.0_f32 * ELITE_WARD_DAMAGE_MULT).round() as i32;
    assert_eq!(state.enemies[1].hp, 200 - expected_warded_dmg);
    assert!(evs.iter().any(|ev| matches!(ev, SimEvent::WardAbsorb { .. })));

    let mut ps = ParticleSystem::new();
    ps.handle_sim_events(&evs, false);
    assert!(!ps.particles.is_empty(), "WardAbsorb must emit spark particles");

    // Splitter right on the Donut inner wall spawns ELITE_SPLIT_COUNT clamped children.
    let mut splitter = Enemy::new(state.alloc_id(), Vec2::new(inner + 20.0, 0.0), 10, 50.0, "chaser");
    splitter.is_elite = true;
    splitter.elite_affix = "splitter".to_string();
    splitter.max_hp = 80;
    state.enemies.push(splitter);
    let mut kill_shot = Projectile::new(
        Vec2::new(inner + 15.0, 0.0),
        Vec2::new(1000.0, 0.0),
        50,
        1.0,
        "player",
        "bullet",
    );
    kill_shot.prev_pos = Some(Vec2::new(inner + 5.0, 0.0));
    state.projectiles.push(kill_shot);
    step(&mut state, &SimInput::default(), DT);
    let split_children: Vec<&Enemy> = state
        .enemies
        .iter()
        .filter(|e| !e.is_elite && e.behavior == "chaser" && e.max_hp == 40)
        .collect();
    assert_eq!(split_children.len(), ELITE_SPLIT_COUNT);
    for child in split_children {
        assert!(
            arena_inside(child.pos, state.room_radius, MAP_DONUT),
            "splitter child {:?} must be clamped inside Donut",
            child.pos
        );
    }

    // Clear elite hitstop from splitter kill before testing volatile kill on the next step.
    state.hitstop = 0.0;

    // Volatile death emits 130u Shockwave.
    let mut vol = Enemy::new(state.alloc_id(), Vec2::new(0.0, inner + 80.0), 10, 50.0, "chaser");
    vol.is_elite = true;
    vol.elite_affix = "volatile".to_string();
    state.enemies.push(vol);
    let mut vol_shot = Projectile::new(
        Vec2::new(-5.0, inner + 80.0),
        Vec2::new(1000.0, 0.0),
        50,
        1.0,
        "player",
        "bullet",
    );
    vol_shot.prev_pos = Some(Vec2::new(-15.0, inner + 80.0));
    state.projectiles.push(vol_shot);
    let vol_evs = step(&mut state, &SimInput::default(), DT);
    assert!(vol_evs.iter().any(|ev| matches!(
        ev,
        SimEvent::Shockwave { max_radius, .. } if (*max_radius - ELITE_VOLATILE_BLAST_RADIUS).abs() < 1e-3
    )));

    // 2. Spitter alternates 3-lane (volley_mode=0) and 4-lane (volley_mode=1).
    let mut spit_state = new_active_state("circle", "normal", vec![]);
    spit_state.player.pos = Vec2::new(200.0, 0.0);
    let mut spitter = Enemy::new(spit_state.alloc_id(), Vec2::ZERO, 60, 50.0, "spitter");
    spitter.ai.sub_state = EnemySubState::SpitterWindup;
    spitter.ai.sub_timer = 0.01;
    spitter.ai.volley_mode = 0;
    spitter.ai.sniper_aim = Vec2::new(525.0, 0.0);
    spit_state.enemies.push(spitter);
    step(&mut spit_state, &SimInput::default(), DT);
    assert_eq!(spit_state.projectiles.len(), 3);
    assert_eq!(spit_state.enemies[0].ai.volley_mode, 1);

    spit_state.projectiles.clear();
    spit_state.enemies[0].ai.sub_state = EnemySubState::SpitterWindup;
    spit_state.enemies[0].ai.sub_timer = 0.01;
    step(&mut spit_state, &SimInput::default(), DT);
    assert_eq!(spit_state.projectiles.len(), 4);
    assert_eq!(spit_state.enemies[0].ai.volley_mode, 0);

    // 3. Sniper freezes aim when player is dashing and tints beam [255, 112, 165] inside SNIPER_LOCK_SECONDS.
    let mut snp_state = new_active_state("circle", "normal", vec![]);
    snp_state.player.pos = Vec2::new(220.0, 0.0);
    snp_state.player.is_dashing = true;
    snp_state.player.dash_direction = Vec2::new(0.0, 1.0);
    snp_state.player.dash_timer = 0.20;
    let mut sniper = Enemy::new(snp_state.alloc_id(), Vec2::ZERO, 60, 50.0, "sniper");
    sniper.ai.sub_state = EnemySubState::SniperWindup;
    sniper.ai.sub_timer = 0.60;
    sniper.ai.sniper_aim = Vec2::new(220.0, 0.0);
    snp_state.enemies.push(sniper);
    step(&mut snp_state, &SimInput::default(), DT);
    assert_eq!(
        snp_state.enemies[0].ai.sniper_aim,
        Vec2::new(220.0, 0.0),
        "sniper must freeze aim while player is dashing"
    );
    snp_state.enemies[0].ai.sub_timer = SNIPER_LOCK_SECONDS * 0.5;
    step(&mut snp_state, &SimInput::default(), DT);
    let snp_beam = snp_state
        .lasers
        .iter()
        .find(|l| l.owner == TELEGRAPH_OWNER)
        .expect("sniper lock beam must exist");
    assert_eq!(snp_beam.color, [255, 112, 165]);

    // 4. Repulsor stuns enemies within REPULSOR_RANGE and cancels active windup + telegraph.
    let mut rep_state = new_active_state("circle", "normal", vec![]);
    rep_state.player.pos = Vec2::ZERO;
    rep_state.enemies.push(snp_state.enemies[0].clone());
    rep_state.enemies[0].pos = Vec2::new(REPULSOR_RANGE - 20.0, 0.0);
    let _ = rep_state.repulsor.on_pickup(rep_state.time);
    rep_state.repulsor.charges = 1;
    rep_state.repulsor.cooldown_until = rep_state.time;
    step(&mut rep_state, &SimInput::default(), DT);
    assert!(rep_state.enemies[0].is_stunned(rep_state.time));
    assert_eq!(rep_state.enemies[0].ai.sub_state, EnemySubState::None);
    assert!(rep_state.lasers.is_empty());
}
