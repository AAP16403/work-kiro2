//! Achievement system tests: definitions, thresholds, lifetime totals, live previews,
//! settlement through `end_run`, and progress.json compatibility.

use serde_json::{json, Value};
use std::fs;
use tempfile::tempdir;

use plouto_rs::save::progress::{
    best_for_date, default_progress, end_run, evaluate_live, load_progress, save_progress,
    RunContext,
};
use plouto_rs::sim::achievements::{
    check_condition, get_achievement, name_of, progress_of, shown_description, shown_name,
    AchCategory, AchCondition, AchTotals, AchievementDef, RunStats, ACHIEVEMENTS, ARENA_SHAPES,
    BOSS_KINDS, LEGACY_ACHIEVEMENT_IDS,
};
use plouto_rs::sim::config::MAP_DONUT;
use plouto_rs::sim::math::Vec2;
use plouto_rs::sim::projectile::Projectile;
use plouto_rs::sim::state::{RunSetup, SimInput, SimState};
use plouto_rs::sim::step::step;

/// Threshold table: (id, target in the condition's units). Float conditions use thousandths.
const CASES: &[(&str, i64)] = &[
    ("first_blood", 1),
    ("massacre", 50),
    ("giant_slayer", 1),
    ("boss_hunter", 3),
    ("bossbreaker", 15),
    ("no_damage_wave", 1),
    ("flawless_five", 5),
    ("elite_slayer", 5),
    ("combo_6x", 6000),
    ("combo_max", 8000),
    ("survive_ten_waves", 10),
    ("into_the_deep", 10),
    ("deep_space", 20),
    ("edge_of_stars", 30),
    ("marathon", 300_000),
    ("five_digits", 10_000),
    ("stellar_score", 50_000),
    ("centurion", 100),
    ("exterminator", 1000),
    ("veteran", 10),
    ("dash_master", 100),
    ("overdrive", 5),
    ("overkill", 25),
    ("scavenger", 25),
    ("shield_wall", 10),
    ("triple_threat", 3),
    ("every_boss", 8),
    ("world_tour", 4),
    ("daily_driver", 1),
    ("mutant", 10),
    ("purist", 15),
    ("endurance", 600_000),
    ("five_thousand", 5000),
    ("old_hand", 50),
    ("clean_sweep", 10),
];

/// Builds a state where the achievement's stat equals `n` (thousandths for float conditions).
/// Returns the current run and the lifetime totals, with the run already absorbed.
fn case(id: &str, n: u32) -> (RunStats, AchTotals) {
    let k = n as usize;
    let mut history: Vec<RunStats> = Vec::new();
    let mut run = RunStats::new();
    match id {
        "first_blood" | "massacre" | "centurion" | "exterminator" | "five_thousand" => {
            for _ in 0..n {
                run.on_kill(false, false, 1.0);
            }
        }
        "giant_slayer" | "triple_threat" => {
            for _ in 0..n {
                run.on_kill(false, true, 1.0);
                run.on_boss_kind("boss_brute");
            }
        }
        "boss_hunter" | "bossbreaker" => {
            for _ in 0..n {
                let mut r = RunStats::new();
                r.on_kill(false, true, 1.0);
                r.on_boss_kind("boss_laser");
                r.finish(0, 0, 0.0, None);
                history.push(r);
            }
        }
        "no_damage_wave" | "flawless_five" | "clean_sweep" | "survive_ten_waves" => {
            for _ in 0..n {
                run.on_wave_clear();
            }
        }
        "elite_slayer" => {
            for _ in 0..n {
                run.on_kill(true, false, 1.0);
            }
        }
        "combo_6x" | "combo_max" => run.on_kill(false, false, n as f32 / 1000.0),
        "into_the_deep" | "deep_space" | "edge_of_stars" | "purist" => {
            run.finish(0, n as i32, 0.0, None)
        }
        "mutant" => {
            run.set_run_context(1, false);
            run.finish(0, n as i32, 0.0, None);
        }
        "marathon" | "endurance" => run.finish(0, 0, n as f32 / 1000.0, None),
        "five_digits" | "stellar_score" => run.finish(n as i32, 0, 0.0, None),
        "veteran" | "old_hand" => {
            for _ in 0..n {
                let mut r = RunStats::new();
                r.finish(0, 0, 0.0, None);
                history.push(r);
            }
        }
        "daily_driver" => {
            for _ in 0..n {
                let mut r = RunStats::new();
                r.set_run_context(0, true);
                r.finish(0, 0, 0.0, None);
                history.push(r);
            }
        }
        "dash_master" => {
            for _ in 0..n {
                run.on_dash();
            }
        }
        "overdrive" => {
            for _ in 0..n {
                run.on_ultra_use();
            }
        }
        "overkill" => {
            for _ in 0..n {
                run.on_ultra_kill();
            }
        }
        "scavenger" => {
            for _ in 0..n {
                run.on_pickup();
            }
        }
        "shield_wall" => {
            for _ in 0..n {
                run.on_shield_block();
            }
        }
        "every_boss" => {
            for kind in BOSS_KINDS.iter().take(k) {
                run.on_boss_kind(kind);
            }
        }
        "world_tour" => {
            for shape in ARENA_SHAPES.iter().take(k) {
                run.on_arena_clear(shape);
            }
        }
        other => panic!("no threshold case for achievement {other}"),
    }
    run.finish(0, 0, 0.0, None);
    if history.is_empty() {
        history.push(run.clone());
    }
    let mut totals = AchTotals::default();
    for r in &history {
        totals.absorb(r);
    }
    (run, totals)
}

fn settled(f: impl FnOnce(&mut RunStats)) -> RunStats {
    let mut r = RunStats::new();
    f(&mut r);
    r.finish(0, 0, 0.0, None);
    r
}

// ---------------------------------------------------------------------------
// Definitions
// ---------------------------------------------------------------------------

#[test]
fn ids_are_unique_complete_and_named() {
    assert_eq!(ACHIEVEMENTS.len(), 35, "20 legacy + 15 new achievements");
    for (i, a) in ACHIEVEMENTS.iter().enumerate() {
        assert!(!a.id.is_empty() && !a.name.is_empty() && !a.description.is_empty());
        for b in ACHIEVEMENTS.iter().skip(i + 1) {
            assert_ne!(a.id, b.id, "duplicate achievement id {}", a.id);
        }
    }
    assert_eq!(LEGACY_ACHIEVEMENT_IDS.len(), 20);
    for id in LEGACY_ACHIEVEMENT_IDS {
        assert!(get_achievement(id).is_some(), "legacy id removed: {id}");
    }
}

#[test]
fn legacy_ids_and_names_are_unchanged() {
    // Saved progress.json files store ids; names are what players learned. Neither may drift.
    let legacy = [
        ("first_blood", "First Blood"),
        ("massacre", "Massacre"),
        ("giant_slayer", "Giant Slayer"),
        ("boss_hunter", "Boss Hunter"),
        ("bossbreaker", "Bossbreaker"),
        ("no_damage_wave", "Untouchable"),
        ("flawless_five", "Flawless Five"),
        ("elite_slayer", "Elite Slayer"),
        ("combo_6x", "Combo x6"),
        ("combo_max", "Maxed Out"),
        ("survive_ten_waves", "Survivor"),
        ("into_the_deep", "Into the Deep"),
        ("deep_space", "Deep Space"),
        ("edge_of_stars", "Edge of the Stars"),
        ("marathon", "Marathon"),
        ("five_digits", "Five Digits"),
        ("stellar_score", "Stellar Score"),
        ("centurion", "Centurion"),
        ("exterminator", "Exterminator"),
        ("veteran", "Veteran"),
    ];
    for (id, name) in legacy {
        assert_eq!(name_of(id), name, "legacy name changed for {id}");
        assert!(LEGACY_ACHIEVEMENT_IDS.contains(&id));
    }
    assert_eq!(name_of("not_an_achievement"), "not_an_achievement");
}

#[test]
fn every_category_has_achievements() {
    for cat in AchCategory::ALL {
        assert!(
            ACHIEVEMENTS.iter().any(|a| a.category == cat),
            "no achievement in category {}",
            cat.label()
        );
    }
}

#[test]
fn threshold_table_covers_every_achievement_with_matching_targets() {
    assert_eq!(CASES.len(), ACHIEVEMENTS.len(), "a threshold case is missing or duplicated");
    let empty_run = RunStats::new();
    let empty_totals = AchTotals::default();
    for (id, target) in CASES {
        let def = get_achievement(id).unwrap_or_else(|| panic!("missing achievement {id}"));
        let (_, t) = progress_of(def, &empty_run, &empty_totals);
        assert_eq!(t, *target, "target for {id} differs from the table");
    }
}

#[test]
fn each_condition_unlocks_at_threshold_and_not_below() {
    for (id, target) in CASES {
        let def = get_achievement(id).expect("known id");
        let t = *target as u32;

        let (run, totals) = case(id, t - 1);
        assert!(
            !check_condition(def.cond, &run, &totals),
            "{id} unlocked below its threshold"
        );
        assert_eq!(progress_of(def, &run, &totals), (*target - 1, *target), "{id} progress below");

        let (run, totals) = case(id, t);
        assert!(
            check_condition(def.cond, &run, &totals),
            "{id} did not unlock at its threshold"
        );
        assert_eq!(progress_of(def, &run, &totals).0, *target, "{id} progress at threshold");
    }
}

#[test]
fn unknown_stat_key_never_unlocks_and_reports_zero_progress() {
    let def = AchievementDef {
        id: "typo_test",
        name: "Typo",
        description: "Unknown key.",
        cond: AchCondition::RunAtLeast("kils", 5),
        category: AchCategory::Combat,
        secret: false,
    };
    let mut run = RunStats::new();
    for _ in 0..10 {
        run.on_kill(false, false, 1.0);
    }
    run.finish(0, 0, 0.0, None);
    let totals = AchTotals::default();
    assert!(!check_condition(def.cond, &run, &totals));
    assert_eq!(progress_of(&def, &run, &totals), (0, 5));

    let total_def = AchievementDef {
        cond: AchCondition::TotalAtLeast("total_kils", 1),
        ..def
    };
    assert!(!check_condition(total_def.cond, &run, &totals));
}

#[test]
fn secret_achievement_hides_text_until_earned() {
    let clean = get_achievement("clean_sweep").expect("clean_sweep exists");
    assert!(clean.secret);
    assert_eq!(shown_name(clean, false), "???");
    assert_ne!(shown_description(clean, false), clean.description);
    assert_eq!(shown_name(clean, true), clean.name);
    assert_eq!(shown_description(clean, true), clean.description);

    let open = get_achievement("first_blood").expect("first_blood exists");
    assert_eq!(shown_name(open, false), open.name);
    assert_eq!(shown_description(open, false), open.description);
}

// ---------------------------------------------------------------------------
// Combat rules and sim wiring
// ---------------------------------------------------------------------------

#[test]
fn health_hit_breaks_untouchable_streak_in_sim() {
    let setup = RunSetup {
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
    step(&mut state, &SimInput::default(), 1.0 / 60.0);
    assert_eq!(state.run_stats.hits_taken, 1, "a health hit must be recorded");
    assert_eq!(state.run_stats.shield_blocks, 0);
}

#[test]
fn shield_only_block_keeps_untouchable_streak_in_sim() {
    let setup = RunSetup {
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

    assert_eq!(state.player.hp, 100, "shield absorbed the whole hit");
    assert_eq!(state.run_stats.shield_blocks, 1);
    assert_eq!(state.run_stats.hits_taken, 0, "shield-only block is not a health hit");
    assert_eq!(state.run_stats.damage_taken, 0);

    // With no health hit, a cleared wave is still perfect.
    let mut probe = state.run_stats.clone();
    let before = probe.perfect_waves;
    probe.on_wave_clear();
    assert_eq!(probe.perfect_waves, before + 1);
}

#[test]
fn zero_or_negative_health_damage_is_ignored() {
    let mut r = RunStats::new();
    r.on_player_hit(0);
    r.on_player_hit(-4);
    assert_eq!(r.hits_taken, 0);
    assert_eq!(r.damage_taken, 0);
}

#[test]
fn tracking_fields_follow_their_hooks() {
    let mut r = RunStats::new();
    r.on_kill(true, true, 2.0);
    r.on_boss_kind("boss_thunder");
    r.on_ultra_kill();
    r.on_ultra_use();
    r.on_dash();
    r.on_pickup();
    r.on_arena_clear(MAP_DONUT);
    r.on_arena_clear(MAP_DONUT);
    assert_eq!((r.kills, r.elite_kills, r.boss_kills), (1, 1, 1));
    assert_eq!(r.ultra_kills, 1);
    assert_eq!(r.ultra_uses, 1);
    assert_eq!(r.dashes, 1);
    assert_eq!(r.pickups, 1);
    assert_eq!(r.boss_kind_names(), vec!["boss_thunder"]);
    assert_eq!(r.arena_names(), vec![MAP_DONUT]);
    assert_eq!(r.best_combo, 2.0);
}

#[test]
fn unknown_boss_and_arena_names_are_ignored() {
    let mut r = RunStats::new();
    r.on_boss_kind("boss_nobody");
    r.on_arena_clear("moon");
    assert_eq!(r.boss_kinds, 0);
    assert_eq!(r.arenas_cleared, 0);
}

// ---------------------------------------------------------------------------
// Live previews
// ---------------------------------------------------------------------------

#[test]
fn evaluate_live_is_read_only_and_skips_earned() {
    let dir = tempdir().expect("tempdir");
    let path = dir.path().join("progress.json");
    let mut data = default_progress();
    let snapshot = format!("{data:?}");

    let mut stats = RunStats::new();
    stats.on_kill(false, false, 1.0);
    stats.wave = 10; // live value, normally set by finish
    let ctx = RunContext::default();

    let live = evaluate_live(&stats, &ctx, &data);
    assert!(live.contains(&"first_blood"));
    assert!(live.contains(&"into_the_deep"));
    assert_eq!(format!("{data:?}"), snapshot, "evaluate_live changed the data");
    assert!(!path.exists(), "evaluate_live must not write");

    data.achievements.push("first_blood".to_string());
    let live = evaluate_live(&stats, &ctx, &data);
    assert!(!live.contains(&"first_blood"), "earned achievements are not announced again");
}

#[test]
fn evaluate_live_uses_mutator_and_daily_context_without_touching_stats() {
    let data = default_progress();
    let mut stats = RunStats::new();
    stats.wave = 10;
    let before = format!("{stats:?}");
    let ctx = RunContext {
        daily_date: Some("2026-05-01".to_string()),
        mutators: vec!["frenzy".to_string()],
    };
    let live = evaluate_live(&stats, &ctx, &data);
    assert!(live.contains(&"mutant"));
    assert!(live.contains(&"daily_driver"));
    assert_eq!(format!("{stats:?}"), before);
}

// ---------------------------------------------------------------------------
// Settlement and progress.json
// ---------------------------------------------------------------------------

#[test]
fn legacy_progress_json_loads_and_round_trips() {
    let dir = tempdir().expect("tempdir");
    let path = dir.path().join("progress.json");
    let legacy = r#"{
        "version": 1,
        "best_wave": 12,
        "best_score": 4200,
        "total_kills": 300,
        "bosses_defeated": 2,
        "runs_played": 7,
        "unlocked_skins": ["crimson"],
        "achievements": ["first_blood", "massacre"],
        "selected_skin": "crimson",
        "daily": {"2026-04-14": {"score": 10, "wave": 2}},
        "future_key": "keep-me"
    }"#;
    fs::write(&path, legacy).unwrap();

    let data = load_progress(&path);
    assert_eq!(data.best_wave, 12);
    assert_eq!(data.total_kills, 300);
    assert_eq!(data.runs_played, 7);
    assert_eq!(data.daily_runs, 0, "new field defaults to zero");
    assert!(data.bosses_seen.is_empty());
    assert!(data.arenas_cleared.is_empty());
    assert_eq!(data.achievements, vec!["first_blood", "massacre"]);
    assert_eq!(data.extra.get("future_key"), Some(&json!("keep-me")));

    assert!(save_progress(&path, &data));
    let raw: Value = serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
    assert_eq!(raw["daily_runs"], json!(0));
    assert_eq!(raw["bosses_seen"], json!([]));
    assert_eq!(raw["arenas_cleared"], json!([]));
    assert_eq!(raw["future_key"], json!("keep-me"));

    let again = load_progress(&path);
    assert_eq!(again.total_kills, 300);
    assert_eq!(again.achievements, vec!["first_blood", "massacre"]);
    assert_eq!(best_for_date(&again, "2026-04-14"), Some((10, 2)));
}

#[test]
fn unknown_boss_and_arena_names_are_dropped_on_load() {
    let dir = tempdir().expect("tempdir");
    let path = dir.path().join("progress.json");
    let body = json!({
        "bosses_seen": ["boss_brute", "boss_fake", "boss_brute"],
        "arenas_cleared": [ARENA_SHAPES[0], "moon"],
        "daily_runs": 3,
    });
    fs::write(&path, body.to_string()).unwrap();
    let data = load_progress(&path);
    assert_eq!(data.bosses_seen, vec!["boss_brute".to_string()]);
    assert_eq!(data.arenas_cleared, vec![ARENA_SHAPES[0].to_string()]);
    assert_eq!(data.daily_runs, 3);
}

#[test]
fn settlement_writes_once_and_leaves_run_stats_unchanged() {
    let dir = tempdir().expect("tempdir");
    let path = dir.path().join("progress.json");

    let mut run = RunStats::new();
    for _ in 0..3 {
        run.on_kill(false, false, 1.5);
    }
    run.on_boss_kind("boss_brute");
    run.on_kill(false, true, 1.5);
    run.on_arena_clear(MAP_DONUT);
    run.on_wave_clear();
    run.on_dash();
    run.finish(1200, 4, 61.0, Some(2.5));
    let before = format!("{run:?}");

    let ctx = RunContext {
        daily_date: Some("2026-05-01".to_string()),
        mutators: vec!["frenzy".to_string()],
    };
    let summary = end_run(&run, &ctx, &path);
    assert!(summary.saved);
    assert_eq!(format!("{run:?}"), before, "settlement must not change the replayed RunStats");

    let on_disk = load_progress(&path);
    assert_eq!(on_disk.runs_played, 1, "one settled run counts once");
    assert_eq!(on_disk.total_kills, 4);
    assert_eq!(on_disk.bosses_defeated, 1);
    assert_eq!(on_disk.best_score, 1200);
    assert_eq!(on_disk.daily_runs, 1);
    assert_eq!(on_disk.bosses_seen, vec!["boss_brute".to_string()]);
    assert_eq!(on_disk.arenas_cleared, vec![MAP_DONUT.to_string()]);
    assert_eq!(summary.progress.runs_played, on_disk.runs_played);
    assert!(summary.new_achievements.contains(&"first_blood"));
    assert!(summary.new_achievements.contains(&"giant_slayer"));
}

#[test]
fn repeated_settlement_does_not_announce_earned_achievements_again() {
    let dir = tempdir().expect("tempdir");
    let path = dir.path().join("progress.json");
    let run = settled(|r| r.on_kill(false, false, 1.0));
    let ctx = RunContext::default();

    let first = end_run(&run, &ctx, &path);
    assert!(first.new_achievements.contains(&"first_blood"));
    let second = end_run(&run, &ctx, &path);
    assert!(!second.new_achievements.contains(&"first_blood"));
}

#[test]
fn daily_result_is_saved_in_the_same_write() {
    let dir = tempdir().expect("tempdir");
    let path = dir.path().join("progress.json");

    let mut run = RunStats::new();
    run.on_kill(false, false, 1.0);
    run.finish(1000, 3, 30.0, None);
    let ctx = RunContext {
        daily_date: Some("2026-05-01".to_string()),
        mutators: Vec::new(),
    };
    let summary = end_run(&run, &ctx, &path);
    let daily = summary.daily.clone().expect("valid date gives a daily result");
    assert!(daily.changed && daily.new_best);
    assert_eq!(daily.best_score, 1000);
    assert_eq!(best_for_date(&load_progress(&path), "2026-05-01"), Some((1000, 3)));
    assert_eq!(load_progress(&path).daily_runs, 1);

    // A lower score on the same date does not replace the record but still counts as a daily run.
    let mut worse = RunStats::new();
    worse.finish(400, 1, 5.0, None);
    let again = end_run(&worse, &ctx, &path).daily.expect("daily result");
    assert!(!again.changed);
    assert_eq!(best_for_date(&load_progress(&path), "2026-05-01"), Some((1000, 3)));
}

#[test]
fn invalid_daily_date_counts_as_a_normal_run() {
    let dir = tempdir().expect("tempdir");
    let path = dir.path().join("progress.json");
    let mut run = RunStats::new();
    run.finish(500, 2, 20.0, None);
    let ctx = RunContext {
        daily_date: Some("not-a-date".to_string()),
        mutators: Vec::new(),
    };
    let summary = end_run(&run, &ctx, &path);
    assert!(summary.daily.is_none());
    let on_disk = load_progress(&path);
    assert_eq!(on_disk.runs_played, 1);
    assert_eq!(on_disk.daily_runs, 0);
    assert!(on_disk.daily.is_empty());
}

#[test]
fn mutator_context_grants_mutant_without_touching_run_stats() {
    let dir = tempdir().expect("tempdir");
    let path = dir.path().join("progress.json");
    let mut run = RunStats::new();
    run.finish(0, 10, 0.0, None);
    assert_eq!(run.mutator_count, 0);

    let ctx = RunContext {
        daily_date: None,
        mutators: vec!["frenzy".to_string(), "glass_cannon".to_string()],
    };
    let summary = end_run(&run, &ctx, &path);
    assert!(summary.new_achievements.contains(&"mutant"));
    assert_eq!(run.mutator_count, 0, "context applies to a copy only");
}

#[test]
fn totals_match_apply_run_and_absorb() {
    let mut data = default_progress();
    let mut run = RunStats::new();
    run.on_boss_kind("boss_swarmqueen");
    run.on_kill(false, true, 1.0);
    run.finish(77, 5, 12.0, None);
    plouto_rs::save::progress::apply_run(&mut data, &run);
    let totals = plouto_rs::save::progress::totals_of(&data);
    let mut manual = AchTotals::default();
    manual.absorb(&run);
    assert_eq!(totals, manual);
    assert_eq!(data.best_score, 77);
    assert_eq!(data.bosses_defeated, 1);
}

#[test]
fn boss_kind_list_covers_every_boss_name() {
    // Every boss kind must be representable, or "Boss Collector" can never unlock.
    assert!(BOSS_KINDS.len() <= 32, "bitmask holds 32 kinds");
    let mut r = RunStats::new();
    for kind in BOSS_KINDS {
        r.on_boss_kind(kind);
    }
    assert_eq!(r.boss_kind_names().len(), BOSS_KINDS.len());
}
