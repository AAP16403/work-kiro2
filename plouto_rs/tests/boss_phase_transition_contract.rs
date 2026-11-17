use plouto_rs::sim::enemy::{Enemy, EnemySubState};
use plouto_rs::sim::hazards::{LaserBeam, Trap};
use plouto_rs::sim::math::Vec2;
use plouto_rs::sim::state::{RunSetup, SimInput, SimState};
use plouto_rs::sim::step::step;

const DT: f32 = 1.0 / 60.0;

#[test]
fn phase_transition_cancels_unlaunched_tells_for_all_eight_bosses() {
    let encounters = [
        ("boss_thunder", EnemySubState::ThunderWindup),
        ("boss_laser", EnemySubState::LaserAttack),
        ("boss_trapmaster", EnemySubState::TrapmasterTelegraph),
        ("boss_swarmqueen", EnemySubState::QueenVolleyTelegraph),
        ("boss_brute", EnemySubState::BruteTelegraph),
        ("boss_abyss_gaze", EnemySubState::AbyssTelegraph),
        ("boss_womb_core", EnemySubState::WombPulseTelegraph),
        ("boss_eclipse_archon", EnemySubState::EclipseCharge),
    ];

    for (seed, (behavior, telegraph_state)) in encounters.into_iter().enumerate() {
        let setup = RunSetup {
            seed: 700 + seed as u64,
            difficulty: "normal".to_string(),
            map_type: "circle".to_string(),
            auto_shoot: false,
            ..RunSetup::default()
        };
        let mut state = SimState::new(setup);
        state.wave = 10;
        state.wave_active = true;
        state.player.hp = 1_000_000;
        state.player.max_hp = 1_000_000;
        state.player.pos = Vec2::new(-220.0, 90.0);

        let mut boss = Enemy::new(9000 + seed as u64, Vec2::new(180.0, 0.0), 3_000, 75.0, behavior);
        boss.hp = 1_800; // Cross from phase I to phase II on the next boss update.
        boss.ai.boss_initialized = true;
        boss.ai.boss_max_hp = 3_000;
        boss.ai.phase = 0;
        boss.ai.sub_state = telegraph_state;
        boss.ai.sub_timer = 0.5;
        boss.ai.summon_target_count = 2;
        state.enemies.push(boss);

        if behavior == "boss_laser" {
            state.lasers.push(
                LaserBeam::new(
                    Vec2::new(180.0, 0.0),
                    Vec2::new(-500.0, 0.0),
                    10,
                    12.0,
                    2.0,
                    0.0,
                    [255, 100, 255],
                    "enemy",
                )
                .with_source(behavior),
            );
        }
        if behavior == "boss_womb_core" {
            state.traps.push(
                Trap::new(Vec2::new(300.0, 250.0), 102.0, 0, 0.52, 0.52, "womb_warn")
                    .with_source(behavior),
            );
            state.traps.push(
                Trap::new(Vec2::new(300.0, 250.0), 86.0, 20, 0.9, 0.52, "womb_pulse")
                    .with_source(behavior),
            );
        }

        step(&mut state, &SimInput::default(), DT);

        let boss = state
            .enemies
            .iter()
            .find(|enemy| enemy.behavior == behavior)
            .expect("boss remains alive through the phase transition");
        assert_eq!(boss.ai.phase, 1, "{behavior} did not enter phase II");
        assert_eq!(boss.ai.sub_state, EnemySubState::None, "{behavior} kept its stale tell");
        assert!(boss.ai.boss_phase_recovery_left > 0.0, "{behavior} skipped phase recovery");
        assert!(
            !state.projectiles.iter().any(|p| p.source == behavior),
            "{behavior} launched a projectile while its unlaunched tell was canceled"
        );

        if behavior == "boss_laser" {
            assert!(
                !state.lasers.iter().any(|beam| beam.source == behavior),
                "{behavior} retained a sweep beam after phase interruption"
            );
        }
        if behavior == "boss_womb_core" {
            assert!(
                state.traps.iter().any(|trap| trap.kind == "womb_warn" && trap.source == behavior),
                "{behavior} must retain the tell for its already-committed pulse"
            );
            assert!(
                state.traps.iter().any(|trap| trap.kind == "womb_pulse" && trap.source == behavior),
                "{behavior} must retain the matching already-committed pulse"
            );
        } else {
            assert!(
                !state.traps.iter().any(|trap| trap.source == behavior),
                "{behavior} left a floor tell/hazard after canceling before launch"
            );
        }
    }
}
