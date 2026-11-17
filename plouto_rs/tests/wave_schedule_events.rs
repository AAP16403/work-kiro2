use plouto_rs::sim::config::{
    BOSS_WAVE_EVERY, DIAMOND_EXTENT_RATIO, EVENT_FLARE_SECTOR_DEG, EVENT_FLARE_WARN,
    EVENT_MIN_WAVE, EVENT_NEBULA_RADIUS, EVENT_NEBULA_SHIELD, EVENT_NEBULA_WARN,
    EVENT_WAVE_CHANCE,
};
use plouto_rs::sim::enemy::Enemy;
use plouto_rs::sim::events::{
    begin_wave_event, end_wave_event, update_arena_event, ArenaEvent, MeteorShower, MeteorZone,
    NebulaCloud, SolarFlare,
};
use plouto_rs::sim::level::{difficulty_mods, spawn_wave_enemies, wave_cap};
use plouto_rs::sim::math::Vec2;
use plouto_rs::sim::mutators::RunRules;
use plouto_rs::sim::rng::SimRng;
use plouto_rs::sim::state::{DamageTarget, RunSetup, SimEvent, SimInput, SimState};
use plouto_rs::sim::step::step;

const DT: f32 = 1.0 / 60.0;
const DIFFICULTIES: [&str; 3] = ["easy", "normal", "hard"];
const REPRESENTATIVE_WAVES: [i32; 17] = [
    1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 19, 20, 21, 30, 31, 39, 40,
];

fn role_unlock_wave(behavior: &str) -> i32 {
    match behavior {
        "chaser" | "charger" => 1,
        "ranged" => 2,
        "bomber" => 3,
        "swarm" => 4,
        "engineer" => 6,
        "tank" => 7,
        "sniper" => 8,
        "spitter" | "flyer" => 9,
        _ => 1,
    }
}

fn spawn_wave(wave: i32, difficulty: &str, seed: u64) -> Vec<Enemy> {
    let mods = difficulty_mods(difficulty);
    let mut next_id = 1;
    let mut rng = SimRng::new(seed);
    spawn_wave_enemies(
        wave,
        difficulty,
        "circle",
        760.0,
        mods.max_enemies,
        &RunRules::default(),
        Vec2::ZERO,
        &mut next_id,
        &mut rng,
    )
    .enemies
}

#[test]
fn representative_early_mid_and_late_waves_keep_composition_caps_and_five_wave_boss_cadence() {
    for wave in REPRESENTATIVE_WAVES {
        let mut difficulty_counts = Vec::new();
        for (difficulty_index, difficulty) in DIFFICULTIES.iter().enumerate() {
            let mods = difficulty_mods(difficulty);
            let enemies = spawn_wave(
                wave,
                difficulty,
                900_000 + wave as u64 * 10 + difficulty_index as u64,
            );
            let bosses: Vec<&Enemy> = enemies.iter().filter(|enemy| enemy.is_boss()).collect();

            if wave % BOSS_WAVE_EVERY == 0 {
                assert_eq!(bosses.len(), 1, "wave {wave}/{difficulty} should have one boss");
                assert_eq!(enemies.len(), 1, "wave {wave}/{difficulty} should contain only its boss");
                assert!(bosses[0].behavior.starts_with("boss_"));
                difficulty_counts.push(1);
                continue;
            }

            assert!(bosses.is_empty(), "wave {wave}/{difficulty} spawned a boss off schedule");
            let base_count = 4 + ((wave as f32) * 1.4) as usize;
            let expected_count = ((base_count as f32 * mods.spawn) as usize)
                .max(1)
                .min(wave_cap(wave, mods.max_enemies));
            assert_eq!(enemies.len(), expected_count, "wrong body count at wave {wave}/{difficulty}");
            assert!(
                enemies.len() <= wave_cap(wave, mods.max_enemies),
                "wave {wave}/{difficulty} exceeded its rising wave cap"
            );
            for enemy in &enemies {
                assert!(
                    wave >= role_unlock_wave(&enemy.behavior),
                    "{} appeared before its wave unlock at wave {wave}",
                    enemy.behavior
                );
            }
            difficulty_counts.push(enemies.len());
        }

        if wave % BOSS_WAVE_EVERY != 0 {
            assert!(
                difficulty_counts.windows(2).all(|pair| pair[0] <= pair[1]),
                "spawn count should not fall as difficulty rises at wave {wave}: {difficulty_counts:?}"
            );
        }
    }

    for difficulty in DIFFICULTIES {
        for wave in (BOSS_WAVE_EVERY..=40).step_by(BOSS_WAVE_EVERY as usize) {
            let enemies = spawn_wave(wave, difficulty, 44_000 + wave as u64);
            assert_eq!(enemies.len(), 1, "boss cadence broke at wave {wave}/{difficulty}");
            assert!(enemies[0].is_boss());
        }
    }

    // The authored onboarding waves introduce their intended threat classes.
    let introductions = [
        (2, "ranged"),
        (3, "bomber"),
        (4, "swarm"),
        (6, "engineer"),
        (7, "tank"),
        (8, "sniper"),
    ];
    for difficulty in DIFFICULTIES {
        for (wave, role) in introductions {
            let enemies = spawn_wave(wave, difficulty, 123_000 + wave as u64);
            assert!(
                enemies.iter().any(|enemy| enemy.behavior == role),
                "the authored wave {wave} introduction omitted {role} on {difficulty}"
            );
        }
        let pressure = spawn_wave(9, difficulty, 123_009);
        assert!(
            pressure
                .iter()
                .any(|enemy| matches!(enemy.behavior.as_str(), "spitter" | "flyer")),
            "wave 9 must introduce a pressure role on {difficulty}"
        );
    }
}

#[test]
fn arena_events_are_gated_to_regular_waves_and_scale_player_damage_by_difficulty() {
    for wave in 1..=40 {
        for seed in 0..64_u64 {
            let boss_wave = wave % BOSS_WAVE_EVERY == 0;
            let eligible = !boss_wave && wave >= EVENT_MIN_WAVE;
            let mut expected_roll = SimRng::new(seed);
            let expected_event = expected_roll.f32() < EVENT_WAVE_CHANCE;
            let mut rng = SimRng::new(seed);
            let event = begin_wave_event(wave, boss_wave, 760.0, "circle", &mut rng);
            assert_eq!(
                event.is_some(),
                eligible && expected_event,
                "event gate/one-third roll mismatch at wave {wave}, seed {seed}"
            );
        }
    }

    for difficulty in DIFFICULTIES {
        let expected_mult = match difficulty {
            "easy" => 0.85,
            "hard" => 1.15,
            _ => 1.0,
        };
        let meteor = resolved_player_event_damage(
            difficulty,
            ArenaEvent::MeteorShower(MeteorShower {
                wave: 4,
                elapsed: plouto_rs::sim::config::EVENT_METEOR_WARN - DT,
                zones: vec![MeteorZone {
                    pos: Vec2::ZERO,
                    delay: 0.0,
                    elapsed: 0.0,
                    hit_done: false,
                    live_left: 0.0,
                }],
            }),
        );
        assert_eq!(meteor.0, 16);
        assert_eq!(meteor.1, (16.0_f32 * expected_mult).round() as i32);

        let flare = resolved_player_event_damage(
            difficulty,
            ArenaEvent::SolarFlare(SolarFlare {
                wave: 4,
                elapsed: EVENT_FLARE_WARN - DT,
                start_angle: 0.0,
                sweep_dir: 1.0,
                sector_rad: EVENT_FLARE_SECTOR_DEG.to_radians(),
                beam_length: 760.0 * DIAMOND_EXTENT_RATIO,
                last_hit_elapsed: -999.0,
                enemy_hit_elapsed: Vec::new(),
                sweep_sfx_played: false,
            }),
        );
        assert_eq!(flare.0, 18);
        assert_eq!(flare.1, (18.0_f32 * expected_mult).round() as i32);
    }
}

#[test]
fn nebula_warns_before_buffing_enemies_and_wave_clear_removes_its_shield() {
    let mut event = ArenaEvent::NebulaCloud(NebulaCloud {
        wave: 6,
        elapsed: 0.0,
        pos: Vec2::ZERO,
        radius: EVENT_NEBULA_RADIUS,
        active: false,
        shielded_ids: Vec::new(),
    });
    let mut shield = 0;

    let mut enemies = [(9001, Vec2::ZERO, &mut shield)];
    let warning = update_arena_event(
        &mut event,
        EVENT_NEBULA_WARN - DT,
        Vec2::ZERO,
        &mut enemies,
    );
    assert_eq!(warning.damage_player_amount, 0);
    drop(enemies);
    assert_eq!(shield, 0, "nebula applied its shield during the warning");

    let mut enemies = [(9001, Vec2::ZERO, &mut shield)];
    let active = update_arena_event(&mut event, DT, Vec2::ZERO, &mut enemies);
    assert_eq!(active.damage_player_amount, 0, "nebula should not damage the player");
    assert_eq!(active.enemy_hits.len(), 0);
    assert!(event.active());
    drop(enemies);
    assert_eq!(shield, EVENT_NEBULA_SHIELD);

    let mut cleanup = [(9001, &mut shield)];
    end_wave_event(&mut event, &mut cleanup);
    assert_eq!(shield, 0, "nebula shield persisted after its wave ended");
}

fn resolved_player_event_damage(difficulty: &str, event: ArenaEvent) -> (i32, i32) {
    let mut state = SimState::new(RunSetup {
        difficulty: difficulty.to_string(),
        auto_shoot: false,
        ..RunSetup::default()
    });
    state.wave = 4;
    state.wave_active = true;
    state.player.max_hp = 1_000;
    state.player.hp = 1_000;
    state.player.shield = 0;
    state.player.invincibility_timer = 0.0;
    let mut distant_enemy = Enemy::new(
        8001,
        Vec2::new(state.room_radius * 0.6, 0.0),
        10_000,
        0.0,
        "egg_sac",
    );
    distant_enemy.ai.hatch_timer = 100.0;
    state.enemies.push(distant_enemy);
    state.arena_event = Some(event);

    step(&mut state, &SimInput::default(), DT)
        .into_iter()
        .find_map(|event| match event {
            SimEvent::DamageResolved(result)
                if result.source == "arena event" && result.target == DamageTarget::Player =>
            {
                Some((result.raw_damage, result.adjusted_damage))
            }
            _ => None,
        })
        .expect("active arena event did not damage the player")
}

#[test]
fn legacy_obstacle_settings_cannot_restore_cover_in_any_arena() {
    for map_type in ["circle", "donut", "cross", "diamond"] {
        let mut runtime = plouto_rs::sim::config::RuntimeConfig::default();
        runtime.enable_obstacles = true;
        let state = SimState::new(RunSetup {
            map_type: map_type.to_string(),
            runtime,
            ..RunSetup::default()
        });

        assert!(
            !state.runtime.enable_obstacles,
            "legacy obstacle flag survived run setup on {map_type}"
        );
        assert!(state.obstacles.is_empty(), "{map_type} opened with obstacle geometry");
    }
}
