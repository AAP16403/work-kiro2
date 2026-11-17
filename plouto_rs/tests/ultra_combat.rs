use plouto_rs::sim::config::{ULTRA_BLAST_RADIUS, ULTRA_DAMAGE_BASE, ULTRA_DAMAGE_MULT};
use plouto_rs::sim::enemy::Enemy;
use plouto_rs::sim::math::Vec2;
use plouto_rs::sim::state::{DamageTarget, RunSetup, SimEvent, SimInput, SimState};
use plouto_rs::sim::step::step;

const DT: f32 = 1.0 / 60.0;

fn fresh_state() -> SimState {
    let mut setup = RunSetup::default();
    setup.seed = 0x554c_5452_415f_5445;
    let mut state = SimState::new(setup);
    state.player.damage = 10;
    state.player.ultra_charges = 1;
    state.player.ultra_cd_until = 0.0;
    state.auto_shoot = false;
    state
}

fn add_target(state: &mut SimState, id: u64, pos: Vec2) {
    state.enemies.push(Enemy::new(id, pos, 5_000, 0.0, "chaser"));
}

fn ultra_hits(events: &[SimEvent], target_id: u64) -> Vec<i32> {
    events
        .iter()
        .filter_map(|event| match event {
            SimEvent::DamageResolved(result)
                if result.source == "ultra"
                    && result.target == DamageTarget::Enemy(target_id) =>
            {
                Some(result.raw_damage)
            }
            _ => None,
        })
        .collect()
}

fn fire_ultra(state: &mut SimState, aim: Vec2) -> Vec<SimEvent> {
    step(
        state,
        &SimInput {
            ultra_pressed: true,
            aim_world: aim,
            ..SimInput::default()
        },
        DT,
    )
}

#[test]
fn ultra_variants_apply_their_documented_damage_and_target_coverage() {
    let raw = ULTRA_DAMAGE_BASE + (10.0 * ULTRA_DAMAGE_MULT) as i32;

    // Single piercing beam: full damage to every target it intersects.
    let mut state = fresh_state();
    let player = state.player.pos;
    add_target(&mut state, 1, player + Vec2::new(240.0, 0.0));
    add_target(&mut state, 2, player + Vec2::new(240.0, 80.0));
    let events = fire_ultra(&mut state, player + Vec2::new(1_000.0, 0.0));
    assert_eq!(ultra_hits(&events, 1), vec![raw]);
    assert!(ultra_hits(&events, 2).is_empty());
    assert_eq!(state.player.ultra_charges, 0);
    assert!(state.player.ultra_cd_until > state.time);
    assert_eq!(state.run_stats.ultra_uses, 1);

    // Three-ray fan: the center and both flanks are separate, full-length lanes.
    let mut state = fresh_state();
    state.player.ultra_variant_idx = 1;
    let player = state.player.pos;
    let aim = Vec2::new(1.0, 0.0);
    for (id, angle) in [(11, -16.0), (12, 0.0), (13, 16.0)] {
        add_target(
            &mut state,
            id,
            player + aim.rotated_deg(angle) * 240.0,
        );
    }
    let events = fire_ultra(&mut state, player + aim * 1_000.0);
    let fan_damage = ((raw as f32) * 0.88) as i32;
    for id in [11, 12, 13] {
        assert_eq!(ultra_hits(&events, id), vec![fan_damage], "fan ray missed target {id}");
    }

    // Pulse plus forward strike: radial coverage, a reinforced overlap, and a
    // beam-only extension each have an explicit, inspectable damage result.
    let mut state = fresh_state();
    state.player.ultra_variant_idx = 2;
    let player = state.player.pos;
    add_target(&mut state, 21, player + Vec2::new(0.0, ULTRA_BLAST_RADIUS - 20.0));
    add_target(&mut state, 22, player + Vec2::new(180.0, 0.0));
    add_target(&mut state, 23, player + Vec2::new(320.0, 0.0));
    add_target(&mut state, 24, player + Vec2::new(0.0, ULTRA_BLAST_RADIUS + 80.0));
    let events = fire_ultra(&mut state, player + Vec2::new(1_000.0, 0.0));
    let blast_damage = ((raw as f32) * 0.70) as i32;
    let pulse_beam_damage = ((raw as f32) * 0.48) as i32;
    assert_eq!(ultra_hits(&events, 21), vec![blast_damage]);
    assert_eq!(ultra_hits(&events, 22), vec![blast_damage, pulse_beam_damage]);
    assert_eq!(ultra_hits(&events, 23), vec![pulse_beam_damage]);
    assert!(ultra_hits(&events, 24).is_empty());
}
