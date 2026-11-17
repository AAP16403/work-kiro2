use tempfile::tempdir;

use plouto_rs::assets::resolve_asset;
use plouto_rs::render::floor::FloorGeometryCache;
use plouto_rs::render::particles::ParticleSystem;
use plouto_rs::render::player_art::{draw_character_preview, PlayerVisualState};
use plouto_rs::render::sdf::{linear_rgba, SdfBatch};
use plouto_rs::render::text::{FontId, FontPack};
use plouto_rs::render::world::WorldRenderer;
use plouto_rs::save::progress::{save_progress, ProgressData};
use plouto_rs::save::scores::SubmitOutcome;
use plouto_rs::sim::config::{
    MAP_CIRCLE, MAP_CROSS, MAP_DIAMOND, MAP_DONUT, RuntimeConfig,
};
use plouto_rs::sim::math::Vec2;
use plouto_rs::sim::replay::{load_recording, replay_and_verify, Recorder};
use plouto_rs::sim::rpg::{ActiveTempReward, PERM_REWARD_POOL, TEMP_REWARD_POOL};
use plouto_rs::sim::skins::{DEFAULT_PALETTE, DEFAULT_SKIN_ID};
use plouto_rs::sim::state::{RunSetup, SimInput, SimState};
use plouto_rs::sim::step::step;
use plouto_rs::ui::hangar::{grid_step, page_step, HangarAction, HangarScreen, NavDir};
use plouto_rs::ui::hud::{
    ultra_cooldown_fraction, ultra_ready_alpha, ComboRingAnim, ToastQueue, TOAST_FADE_IN_S,
    TOAST_FADE_OUT_S, TOAST_MAX_PENDING, TOAST_SECONDS,
};
use plouto_rs::ui::screens::{
    AppScreen, BossRewardAction, BossRewardScreen, BossRewardStep, GameOverAction, GameOverScreen,
    ScreenFade,
};

#[test]
fn ultra_gauge_fraction_and_alpha() {
    assert!((ultra_cooldown_fraction(0, 5.0, 10.0, true) - 0.5).abs() < 1e-5);
    assert!((ultra_cooldown_fraction(2, 0.0, 10.0, false) - 1.0).abs() < 1e-5);
    assert!((ultra_cooldown_fraction(0, 7.5, 10.0, true) - 0.25).abs() < 1e-5);
    assert_eq!(ultra_cooldown_fraction(0, 0.0, 10.0, false), 0.0);

    assert_eq!(ultra_ready_alpha(false, 1.0, false), 175);
    assert_eq!(ultra_ready_alpha(true, 1.0, true), 255);
    let pulsing = ultra_ready_alpha(true, 0.3, false);
    assert!((210..=255).contains(&pulsing));
}

#[test]
fn toast_queue_cap_and_fade_curve() {
    let mut tq = ToastQueue::new();
    assert!(tq.push("Title 0", "Current"));
    for i in 1..=TOAST_MAX_PENDING {
        assert!(tq.push(format!("T{i}"), "Sub"));
    }
    // Queue full: next push drops cleanly without panicking
    assert!(!tq.push("Overflow", "Dropped"));
    // Queued toasts plus the overflow summary (which counts as one entry)
    assert_eq!(tq.queued_len(), TOAST_MAX_PENDING + 1);

    // Fade-in -> plateau -> fade-out
    assert_eq!(tq.alpha(false), 0.0);
    tq.tick(TOAST_FADE_IN_S * 0.5);
    assert!((tq.alpha(false) - 0.5).abs() < 0.05);
    tq.tick(TOAST_FADE_IN_S);
    assert!((tq.alpha(false) - 1.0).abs() < 1e-5);
    tq.tick(TOAST_SECONDS - TOAST_FADE_IN_S * 1.5 - TOAST_FADE_OUT_S * 0.5);
    assert!(tq.alpha(false) < 0.99);
    // Reduce motion forces full solid visibility until expiry
    assert_eq!(tq.alpha(true), 1.0);

    // Advancing past full lifetime promotes the next queued toast
    tq.tick(TOAST_SECONDS);
    assert_eq!(tq.current.as_ref().map(|c| c.title.as_str()), Some("T1"));
    assert_eq!(tq.queued_len(), TOAST_MAX_PENDING);

    // Overflowed toasts are folded into one summary toast once the queue drains
    let mut overflow_q = ToastQueue::new();
    assert!(overflow_q.push("Head", "Sub"));
    for i in 0..TOAST_MAX_PENDING {
        assert!(overflow_q.push(format!("Q{i}"), "Sub"));
    }
    assert!(!overflow_q.push("Lost", "Sub"));
    for _ in 0..=TOAST_MAX_PENDING {
        overflow_q.tick(TOAST_SECONDS);
    }
    let last = overflow_q.current.as_ref().map(|c| c.subtitle.clone());
    assert_eq!(last.as_deref(), Some("+1 more, see Hangar"));
}

#[test]
fn combo_ring_and_screen_fade_transitions() {
    let mut ring = ComboRingAnim::default();
    ring.update(3.0, 10.0, 10.0, 0.1, false);
    assert!(ring.frac > 0.95);
    assert!(ring.pulse > 0.5);

    ring.update(1.0, 0.0, 14.0, 0.2, false);
    assert_eq!(ring.frac, 0.0);

    let mut fade = ScreenFade::new();
    // Reduce motion triggers instantly
    let instant = fade.trigger(AppScreen::Playing, true, true);
    assert_eq!(instant, Some((AppScreen::Playing, true)));
    assert!(!fade.active);

    // Standard fade emits target at peak darkness, then fades out cleanly
    assert_eq!(fade.trigger(AppScreen::Playing, false, false), None);
    assert!(fade.active);
    let mut landed = None;
    for _ in 0..40 {
        if let Some(res) = fade.update(0.016) {
            landed = Some(res);
        }
    }
    assert_eq!(landed, Some((AppScreen::Playing, false)));
    assert!(!fade.active);
    assert_eq!(fade.alpha, 0.0);
}

#[test]
fn floor_cache_and_sdf_geometry_generation() {
    let mut cache = FloorGeometryCache::new();
    let mut alpha = SdfBatch::with_capacity(256);
    let mut add = SdfBatch::with_capacity(256);

    for map in [MAP_CIRCLE, MAP_DONUT, MAP_CROSS, MAP_DIAMOND] {
        alpha.clear();
        add.clear();
        cache.draw(
            &mut alpha,
            &mut add,
            map,
            420.0,
            777,
            1280.0,
            720.0,
            Vec2::ZERO,
            1.25,
            0.35,
        );
        assert!(
            !alpha.instances.is_empty(),
            "floor alpha instances empty for map {map}"
        );
        assert!(
            !add.instances.is_empty(),
            "floor add rim/beacons empty for map {map}"
        );
        for inst in alpha.instances.iter().chain(add.instances.iter()) {
            assert!(inst.p0[0].is_finite() && inst.p0[1].is_finite());
            assert!(inst.p1[0].is_finite() && inst.p1[1].is_finite());
            assert!(inst.kind <= 4);
        }
    }
}

#[test]
fn sdf_triangle_batches_reject_degenerate_faces_and_keep_valid_faces() {
    let mut batch = SdfBatch::default();
    let color = [1.0, 1.0, 1.0, 1.0];
    batch.triangle([12.0, 12.0], [12.0, 12.0], [12.0, 12.0], color);
    batch.triangle([0.0, 0.0], [10.0, 0.0], [5.0, 0.00001], color);
    assert!(batch.instances.is_empty(), "zero-area mesh tips must be rejected");

    batch.triangle([0.0, 0.0], [10.0, 0.0], [0.0, 10.0], color);
    assert_eq!(batch.instances.len(), 1, "regular 3D model faces must remain in the render batch");
    assert_eq!(batch.instances[0].kind, 4);
}

#[test]
fn player_art_and_world_renderer_emit_clean_batches() {
    let state = SimState::new(RunSetup {
        seed: 42,
        view_w: 1280,
        view_h: 720,
        ..RunSetup::default()
    });
    let mut world = WorldRenderer::new();
    world.reset(&state);

    let mut wa = SdfBatch::with_capacity(512);
    let mut wadd = SdfBatch::with_capacity(512);
    let mut ua = SdfBatch::with_capacity(256);
    let mut ut = plouto_rs::render::text::TextBatch::default();

    let post = world.draw_world(
        &state,
        0.5,
        1280.0,
        720.0,
        Vec2::new(1.0, 0.0),
        Some([700.0, 400.0]),
        true,
        &mut wa,
        &mut wadd,
        &mut ua,
        &mut ut,
        1.0,
    );
    assert!(!wa.instances.is_empty());
    assert!(!wadd.instances.is_empty());
    assert_eq!(post.low_hp_danger, 0.0);

    // Character preview and particle burst smoke check
    let mut uadd = SdfBatch::default();
    draw_character_preview(&mut ua, &mut uadd, 120.0, 120.0, 1.0, 0.5, true, false, &DEFAULT_PALETTE);
    assert!(!ua.instances.is_empty());
    assert!(!uadd.instances.is_empty());

    let mut pv = PlayerVisualState::new();
    pv.draw(
        &mut wa,
        &mut wadd,
        640.0,
        360.0,
        1.0,
        1.0,
        Vec2::new(120.0, 40.0),
        Vec2::new(1.0, 0.0),
        0.2,
        true,
        10,
        false,
        Vec2::ZERO,
        true,
        true,
        0.0,
        0.0,
        true,
        true,
        false,
        &DEFAULT_PALETTE,
        &DEFAULT_PALETTE,
    );
    let mut ps = ParticleSystem::new();
    ps.emit(Vec2::ZERO, [255, 200, 100], 10, 80.0, 0.3, 3.0, None, 0.5, true);
    ps.push_banner(
        "Wave 2".to_string(),
        "Incoming".to_string(),
        [180, 220, 255],
        1.5,
    );
    ps.tick(0.05);
    assert!(!ps.particles.is_empty());
}

#[test]
fn player_3d_pod_rotates_against_fixed_iso_camera() {
    use plouto_rs::render::models3d::draw_player_pod;
    use plouto_rs::sim::config::{ISO_SCALE_X, ISO_SCALE_Y};

    // Test screen-space aim directions after the same inverse isometric
    // mapping the game uses to turn the mouse position into a world vector.
    let screen_headings = [
        Vec2::new(1.0, 0.0),
        Vec2::new(1.0, 1.0),
        Vec2::new(0.0, 1.0),
        Vec2::new(-1.0, 1.0),
        Vec2::new(-1.0, 0.0),
        Vec2::new(-1.0, -1.0),
        Vec2::new(0.0, -1.0),
        Vec2::new(1.0, -1.0),
    ];
    let mut eye_glints_by_heading = Vec::new();
    let mut areas = Vec::new();
    for screen_heading in screen_headings {
        let screen_x = screen_heading.x / ISO_SCALE_X;
        let screen_y = screen_heading.y / ISO_SCALE_Y;
        let heading = Vec2::new(screen_x + screen_y, screen_y - screen_x);
        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        draw_player_pod(
            &mut alpha,
            &mut add,
            [400.0, 300.0],
            heading,
            Vec2::ZERO,
            1.27,
            0.0,
            0.0,
            0.0,
            1.0,
            false,
            false,
            false,
            0,
            false,
            true,
            &DEFAULT_PALETTE,
        );
        let triangles: Vec<_> = alpha.instances.iter().filter(|instance| instance.kind == 4).collect();
        assert!(!triangles.is_empty(), "pod mesh vanished at heading {heading:?}");
        let min_x = triangles.iter().flat_map(|i| [i.p0[0], i.p1[0], i.params[0]]).fold(f32::INFINITY, f32::min);
        let max_x = triangles.iter().flat_map(|i| [i.p0[0], i.p1[0], i.params[0]]).fold(f32::NEG_INFINITY, f32::max);
        let min_y = triangles.iter().flat_map(|i| [i.p0[1], i.p1[1], i.params[1]]).fold(f32::INFINITY, f32::min);
        let max_y = triangles.iter().flat_map(|i| [i.p0[1], i.p1[1], i.params[1]]).fold(f32::NEG_INFINITY, f32::max);
        let aspect = (max_y - min_y) / (max_x - min_x);
        assert!((0.65..=1.75).contains(&aspect), "pod proportions collapsed at screen heading {screen_heading:?}: {aspect:.2}");
        areas.push((max_x - min_x) * (max_y - min_y));
        eye_glints_by_heading.push(alpha.instances.iter().filter(|instance| instance.kind == 0).count());
    }
    assert!(eye_glints_by_heading[6] > 0, "the camera-facing screen-down (0, -1) heading should show the 3D face");
    assert_eq!(eye_glints_by_heading[2], 0, "the screen-up (0, 1) rear heading must turn the face fully out of view");
    let min_area = areas.iter().copied().fold(f32::INFINITY, f32::min);
    let max_area = areas.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    assert!(min_area / max_area > 0.42, "the pod silhouette collapses during a turn: {areas:?}");
}

#[test]
fn boss_reward_two_step_and_game_over_key_guard() {
    let mut screen = BossRewardScreen::new();
    let temps: Vec<_> = TEMP_REWARD_POOL.iter().take(3).collect();
    let perms: Vec<_> = PERM_REWARD_POOL.iter().take(3).collect();
    screen.open(&temps, &perms);
    assert_eq!(screen.step, BossRewardStep::TempBoon);

    screen.update(0.2, 1280, 720, true);
    let act1 = screen.on_key(Some(1), 0, false);
    assert!(matches!(act1, BossRewardAction::TempPicked { .. }));
    assert_eq!(screen.step, BossRewardStep::PermUpgrade);

    let act2 = screen.on_key(Some(0), 0, false);
    assert!(matches!(act2, BossRewardAction::PermPicked { .. }));

    // Empty temp fallback starts straight at PermUpgrade
    screen.open(&[], &perms);
    assert_eq!(screen.step, BossRewardStep::PermUpgrade);

    // GameOver held-key guard
    let mut go = GameOverScreen::new();
    let outcome = SubmitOutcome {
        is_new_best: true,
        rank: 1,
        points_to_next: None,
        saved: true,
    };
    go.open(
        12500,
        7,
        95.0,
        142,
        4.5,
        &outcome,
        &["frenzy".to_string()],
        None,
        &[],
        &[],
        true, // Confirm held at instant of death
    );
    go.update(2.0, 1280, 720, true, false);
    assert_eq!(go.on_confirm_key(), GameOverAction::None);
    // Release key -> Retry allowed
    go.update(0.05, 1280, 720, false, false);
    assert_eq!(go.on_confirm_key(), GameOverAction::Retry);
}

#[test]
fn boss_reward_cards_show_active_duration_and_upgrade_stack_count() {
    let temp = TEMP_REWARD_POOL
        .iter()
        .find(|reward| reward.key == "temp_overdrive")
        .unwrap();
    let perm = PERM_REWARD_POOL
        .iter()
        .find(|reward| reward.key == "perm_damage")
        .unwrap();
    let active = vec![ActiveTempReward {
        key: "temp_overdrive".to_string(),
        waves_left: 1,
        duration: 1,
    }];
    let run_perms = vec!["perm_damage".to_string(), "perm_damage".to_string()];

    let mut screen = BossRewardScreen::new();
    screen.open_with_context(&[temp], &[perm], &active, &run_perms);

    assert_eq!(screen.temp_cards[0].tag, "ACTIVE 1 → PICK 2");
    assert_eq!(screen.perm_cards[0].tag, "STACK 2 → 3");
}

#[test]
fn hangar_navigation_and_skin_selection_in_tempdir() {
    let dir = tempdir().expect("tempdir");
    let prog_path = dir.path().join("progress.json");
    let mut data = ProgressData::default();
    data.unlocked_skins.push("crimson".to_string());
    save_progress(&prog_path, &data);

    let mut hangar = HangarScreen::new();
    hangar.open(&prog_path);
    assert_eq!(hangar.selected_id(), DEFAULT_SKIN_ID);

    assert_eq!(grid_step(0, NavDir::Right, 12, 4), 1);
    assert_eq!(grid_step(0, NavDir::Down, 12, 4), 4);
    assert_eq!(page_step(0, -1, 4), 3);

    // Unlocked skin equips and persists
    assert_eq!(
        hangar.choose("crimson", Some(&prog_path)),
        HangarAction::SkinEquipped("crimson".to_string())
    );
    // Locked skin refuses without mutating saved selection
    assert_eq!(
        hangar.choose("obsidian", Some(&prog_path)),
        HangarAction::LockedRefused
    );
    assert_eq!(hangar.selected_id(), "crimson");
}

#[test]
fn assets_fonts_icon_and_replay_cli_roundtrip() {
    assert!(resolve_asset("laser-gun_38685.ico").is_some());
    let fonts = FontPack::load().expect("FontPack should load Orbitron and Rajdhani fonts");
    let (w, h) = fonts.measure(FontId::Head, 24.0, "PLOUTO");
    assert!(w > 10.0 && h > 10.0);
    let wrapped = fonts.wrap_lines(FontId::Regular, 14.0, "Alpha Beta Gamma Delta Epsilon", 90.0);
    assert!(wrapped.len() >= 2);

    // Record 90 deterministic frames and verify identical replay
    let dir = tempdir().expect("tempdir");
    let rec_path = dir.path().join("test_replay.json");
    let mut state = SimState::new(RunSetup {
        seed: 20261115,
        view_w: 1280,
        view_h: 720,
        runtime: RuntimeConfig::from_defaults(),
        ..RunSetup::default()
    });
    let mut rec = Recorder::from_state(&state, 1280, 720);
    for frame in 0..90 {
        let input = SimInput {
            move_dir: if frame % 2 == 0 {
                Vec2::new(1.0, 0.25).normalized()
            } else {
                Vec2::new(0.0, -1.0)
            },
            aim_world: Vec2::new(150.0, 40.0),
            fire_held: true,
            boost_held: frame < 20,
            dash_pressed: frame == 30,
            ultra_pressed: false,
        };
        let _ = step(&mut state, &input, 1.0 / 60.0);
        rec.push_frame(&input);
    }
    rec.save_to_file(&state, &rec_path).expect("save replay");
    let loaded = load_recording(&rec_path).expect("load replay");
    let ver = replay_and_verify(&loaded);
    assert!(ver.matches);
    assert_eq!(ver.frames_run, 90);
    assert_eq!(ver.actual_hash, ver.expected_hash);
    let _ = linear_rgba([255, 255, 255], 255, 1.0);
}

#[test]
fn arena_camera_roundtrip_and_expanded_bounds() {
    use plouto_rs::sim::config::{ARENA_MARGIN_DEFAULT, DIAMOND_EXTENT_RATIO};
    use plouto_rs::sim::math::{compute_room_radius, iso_to_world_cam, to_iso_cam, Vec2};

    let r = compute_room_radius(1280, 720, ARENA_MARGIN_DEFAULT);
    assert!(r > 650.0 && r < 1500.0, "unexpected room radius {r}");
    let cam = Vec2::new(280.0, -190.0);
    for pt in [
        Vec2::ZERO,
        Vec2::new(r * 0.85, -r * 0.4),
        Vec2::new(-r * DIAMOND_EXTENT_RATIO * 0.9, 12.0),
    ] {
        let (sx, sy) = to_iso_cam(pt, cam, 1280.0, 720.0, Vec2::ZERO);
        let back = iso_to_world_cam(sx, sy, cam, 1280.0, 720.0);
        assert!(
            (back - pt).length() < 0.05,
            "camera roundtrip mismatch: {pt:?} -> ({sx}, {sy}) -> {back:?}"
        );
    }
}

#[test]
fn all_17_powerups_catalog_and_emblems_consistent() {
    use std::collections::HashSet;
    use plouto_rs::render::powerup_art::{draw_powerup_emblem, powerup_meta, POWERUP_CATALOG};
    use plouto_rs::render::sdf::SdfBatch;
    use plouto_rs::sim::config::powerup_color;

    assert_eq!(POWERUP_CATALOG.len(), 17);
    let mut keys = HashSet::new();
    let mut codes = HashSet::new();
    for m in POWERUP_CATALOG {
        assert!(keys.insert(m.key), "duplicate key {}", m.key);
        assert!(codes.insert(m.short_code), "duplicate short code {}", m.short_code);
        assert_eq!(powerup_meta(m.key).key, m.key);

        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        draw_powerup_emblem(m.key, 100.0, 100.0, 14.0, powerup_color(m.key), 1.0, 1.25, &mut alpha, &mut add);
        assert!(!alpha.instances.is_empty(), "emblem {} drew no alpha geometry", m.key);
        assert!(!add.instances.is_empty(), "emblem {} drew no add geometry", m.key);
    }
}

#[test]
fn all_11_enemies_and_8_bosses_render_in_all_headings() {
    use plouto_rs::render::models3d::{draw_boss_model, draw_enemy_model};
    use plouto_rs::render::sdf::SdfBatch;
    use plouto_rs::render::text::TextBatch;
    use plouto_rs::render::world::WorldRenderer;
    use plouto_rs::sim::enemy::Enemy;
    use plouto_rs::sim::math::Vec2;
    use plouto_rs::sim::powerup::PowerUp;
    use plouto_rs::sim::state::{RunSetup, SimState};

    let all_behaviors = [
        "chaser",
        "ranged",
        "sniper",
        "bomber",
        "tank",
        "charger",
        "spitter",
        "flyer",
        "engineer",
        "swarm",
        "egg_sac",
        "boss_thunder",
        "boss_laser",
        "boss_trapmaster",
        "boss_swarmqueen",
        "boss_brute",
        "boss_abyss_gaze",
        "boss_womb_core",
        "boss_eclipse_archon",
    ];
    assert_eq!(all_behaviors.len(), 19);

    let headings = [
        Vec2::new(1.0, 0.0),
        Vec2::new(0.0, 1.0),
        Vec2::new(-1.0, 0.0),
        Vec2::new(0.0, -1.0),
    ];
    for (i, &behavior) in all_behaviors.iter().enumerate() {
        let mut enemy = Enemy::new(9000 + i as u64, Vec2::ZERO, 100, 90.0, behavior);
        enemy.ai.rage = i % 2 == 0;
        enemy.ai.phase = (i % 3) as i32;
        if behavior == "tank" {
            enemy.ai.push_t = 0.52;
            enemy.vel = Vec2::new(76.0, 0.0);
            enemy.attack_cd = 0.16;
        }
        for (heading_index, heading) in headings.iter().copied().enumerate() {
            let mut alpha = SdfBatch::default();
            let mut add = SdfBatch::default();
            let time = heading_index as f32 * 0.7;
            let modeled = if behavior.starts_with("boss_") {
                draw_boss_model(
                    &enemy,
                    &mut alpha,
                    &mut add,
                    [320.0, 240.0],
                    heading,
                    1.25,
                    time,
                    0.65,
                    [132, 204, 232],
                    false,
                )
            } else {
                draw_enemy_model(
                    &enemy,
                    &mut alpha,
                    &mut add,
                    [320.0, 240.0],
                    heading,
                    1.25,
                    0.08,
                    -0.1,
                    time,
                    0.65,
                    1.0,
                    [132, 204, 232],
                    false,
                )
            };
            assert!(modeled, "{behavior} did not dispatch to a 3D model");
            assert!(!alpha.instances.is_empty(), "{behavior} drew no solid geometry");
            assert!(
                !add.instances.is_empty() || matches!(behavior, "boss_abyss_gaze" | "boss_eclipse_archon"),
                "{behavior} drew no model effects"
            );
            for instance in alpha.instances.iter().chain(add.instances.iter()) {
                assert!(instance.p0[0].is_finite() && instance.p0[1].is_finite());
                assert!(instance.p1[0].is_finite() && instance.p1[1].is_finite());
                if instance.kind == 4 {
                    let ab = [instance.p1[0] - instance.p0[0], instance.p1[1] - instance.p0[1]];
                    let ac = [instance.params[0] - instance.p0[0], instance.params[1] - instance.p0[1]];
                    let area_twice = ab[0] * ac[1] - ab[1] * ac[0];
                    assert!(area_twice.abs() > 1e-3, "{behavior} emitted a collapsed triangle");
                    let bc = [instance.params[0] - instance.p1[0], instance.params[1] - instance.p1[1]];
                    let longest_edge = ab[0].hypot(ab[1]).max(ac[0].hypot(ac[1])).max(bc[0].hypot(bc[1]));
                    assert!(
                        area_twice.abs() / longest_edge.max(1e-6) >= 0.25,
                        "{behavior} emitted a nearly edge-on face"
                    );
                }
            }
        }
    }

    let mut state = SimState::new(RunSetup::default());
    state.player.laser_until = state.time + 8.0;
    state.player.vortex_until = state.time + 8.0;
    state.player.shield = 50;
    state.repulsor.charges = 2;

    let mut id = 500u64;
    for (i, &beh) in all_behaviors.iter().enumerate() {
        let ang = (i as f32 / all_behaviors.len() as f32) * std::f32::consts::TAU;
        let mut e = Enemy::new(id, Vec2::new(ang.cos() * 240.0, ang.sin() * 240.0), 100, 90.0, beh);
        e.hp = 60;
        e.shield = if i % 2 == 0 { 25 } else { 0 };
        e.is_elite = i % 3 == 0;
        if beh.starts_with("boss_") {
            e.ai.rage = i % 2 == 1;
        }
        state.enemies.push(e);
        id += 1;
    }
    state.powerups.push(PowerUp::new(Vec2::new(1500.0, 0.0), "ultra", None));

    let mut wr = WorldRenderer::new();
    wr.reset(&state);
    wr.update_camera(&state, 1280.0, 720.0, Some([700.0, 360.0]), 0.016);

    let mut w_alpha = SdfBatch::default();
    let mut w_add = SdfBatch::default();
    let mut ui_alpha = SdfBatch::default();
    let mut ui_text = TextBatch::default();
    wr.draw_world(
        &state,
        1.0,
        1280.0,
        720.0,
        Vec2::new(1.0, 0.0),
        Some([700.0, 360.0]),
        true,
        &mut w_alpha,
        &mut w_add,
        &mut ui_alpha,
        &mut ui_text,
        1.0,
    );
    assert!(w_alpha.instances.len() > 150, "expected rich enemy+boss SDF geometry");
    assert!(w_add.instances.len() > 80, "expected HDR glow/FX geometry");
    for inst in w_alpha.instances.iter().chain(w_add.instances.iter()).chain(ui_alpha.instances.iter()) {
        assert!(inst.p0[0].is_finite() && inst.p0[1].is_finite());
        assert!(inst.p1[0].is_finite() && inst.p1[1].is_finite());
    }
}

#[test]
fn storm_sovereign_rotates_as_a_deep_artifact_with_a_readable_front() {
    use plouto_rs::render::models3d::draw_boss_model;
    use plouto_rs::render::sdf::SdfBatch;
    use plouto_rs::sim::enemy::Enemy;
    use plouto_rs::sim::math::Vec2;
    use std::f32::consts::FRAC_1_SQRT_2;

    let enemy = Enemy::new(9400, Vec2::ZERO, 100, 80.0, "boss_thunder");
    let projected_width = |facing: Vec2| {
        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        assert!(draw_boss_model(
            &enemy,
            &mut alpha,
            &mut add,
            [320.0, 240.0],
            facing,
            1.25,
            0.0,
            0.0,
            [132, 204, 232],
            true,
        ));
        let mut min_x = f32::INFINITY;
        let mut max_x = f32::NEG_INFINITY;
        for instance in alpha.instances.iter().filter(|instance| instance.kind == 4) {
            for x in [instance.p0[0], instance.p1[0], instance.params[0]] {
                min_x = min_x.min(x);
                max_x = max_x.max(x);
            }
        }
        max_x - min_x
    };

    let face_on_width = projected_width(Vec2::new(FRAC_1_SQRT_2, -FRAC_1_SQRT_2));
    let edge_width = projected_width(Vec2::new(FRAC_1_SQRT_2, FRAC_1_SQRT_2));
    assert!(face_on_width > edge_width * 1.5, "Storm Sovereign should rotate with its heading: {face_on_width} vs {edge_width}");
}

#[test]
fn ocular_abyss_eye_glow_disappears_when_its_face_turns_away() {
    use plouto_rs::render::models3d::draw_boss_model;
    use plouto_rs::render::sdf::SdfBatch;
    use plouto_rs::sim::enemy::Enemy;
    use plouto_rs::sim::math::Vec2;
    use std::f32::consts::FRAC_1_SQRT_2;

    let enemy = Enemy::new(9401, Vec2::ZERO, 100, 80.0, "boss_abyss_gaze");
    let effects_for = |facing: Vec2| {
        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        assert!(draw_boss_model(
            &enemy,
            &mut alpha,
            &mut add,
            [320.0, 240.0],
            facing,
            1.25,
            0.0,
            0.0,
            [132, 204, 232],
            true,
        ));
        add.instances.len()
    };

    let face_on = effects_for(Vec2::new(FRAC_1_SQRT_2, -FRAC_1_SQRT_2));
    let edge_on = effects_for(Vec2::new(FRAC_1_SQRT_2, FRAC_1_SQRT_2));
    assert!(face_on > 0, "the forward eye should glow when it faces the camera");
    assert_eq!(edge_on, 0, "screen-space eye glow should not remain visible edge-on");
}

#[test]
fn boss_articulation_and_charge_poses_follow_attack_states() {
    use plouto_rs::render::models3d::draw_boss_model;
    use plouto_rs::sim::enemy::{Enemy, EnemySubState};

    let render_at = |enemy: &Enemy, windup: f32, time: f32, reduce_motion: bool| {
        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        draw_boss_model(
            enemy,
            &mut alpha,
            &mut add,
            [400.0, 300.0],
            Vec2::new(1.0, 0.0),
            1.0,
            time,
            windup,
            [132, 204, 232],
            reduce_motion,
        );
        let min_x = alpha.instances.iter().filter(|i| i.kind == 4)
            .flat_map(|i| [i.p0[0], i.p1[0], i.params[0]])
            .fold(f32::INFINITY, f32::min);
        let max_x = alpha.instances.iter().filter(|i| i.kind == 4)
            .flat_map(|i| [i.p0[0], i.p1[0], i.params[0]])
            .fold(f32::NEG_INFINITY, f32::max);
        let width = max_x - min_x;
        let mesh_instances: Vec<_> = alpha.instances.iter().filter(|i| i.kind == 4).collect();
        let min_y = mesh_instances.iter()
            .flat_map(|i| [i.p0[1], i.p1[1], i.params[1]])
            .fold(f32::INFINITY, f32::min);
        let max_y = mesh_instances.iter()
            .flat_map(|i| [i.p0[1], i.p1[1], i.params[1]])
            .fold(f32::NEG_INFINITY, f32::max);
        let coords: Vec<_> = mesh_instances.iter()
            .flat_map(|i| [i.p0[0], i.p0[1], i.p1[0], i.p1[1], i.params[0], i.params[1]])
            .collect();
        (width, coords, max_y - min_y)
    };
    let render = |enemy: &Enemy, windup: f32, reduce_motion: bool| {
        render_at(enemy, windup, 0.0, reduce_motion)
    };

    let mut womb = Enemy::new(8101, Vec2::ZERO, 100, 80.0, "boss_womb_core");
    let womb_idle = render(&womb, 0.0, true);
    let womb_reduced_late = render_at(&womb, 0.0, 0.9, true);
    assert!(womb_idle.1.iter().zip(&womb_reduced_late.1).map(|(a, b)| (a - b).abs()).sum::<f32>() < 1e-4,
        "Origin Nexus rings and cage ribs should stop ambient motion with reduced motion enabled");
    let womb_motion = render_at(&womb, 0.0, 0.9, false);
    assert!(womb_idle.1.iter().zip(&womb_motion.1).map(|(a, b)| (a - b).abs()).sum::<f32>() > 50.0,
        "Origin Nexus gyroscopes should precess visibly in normal motion mode");
    womb.ai.sub_state = EnemySubState::WombPulseTelegraph;
    let womb_warning = render(&womb, 1.0, true);
    assert!(womb_idle.0 > womb_warning.0 + 4.0, "Origin Nexus gyroscopes and cage ribs should contract for the pulse tell");
    let retained_faces = womb_idle.1.len().min(womb_warning.1.len()) as f32
        / womb_idle.1.len().max(womb_warning.1.len()).max(1) as f32;
    assert!(retained_faces > 0.97, "the boss should keep its existing 3D parts while articulating, with edge-on degenerate faces filtered");
    assert!(womb_idle.1.iter().zip(&womb_warning.1).map(|(a, b)| (a - b).abs()).sum::<f32>() > 10.0);

    let mut eclipse = Enemy::new(8102, Vec2::ZERO, 100, 80.0, "boss_eclipse_archon");
    eclipse.ai.sub_state = EnemySubState::EclipseOrbit;
    let eclipse_orbit = render(&eclipse, 0.0, true);
    let eclipse_reduced_late = render_at(&eclipse, 0.0, 0.9, true);
    assert!(eclipse_orbit.1.iter().zip(&eclipse_reduced_late.1).map(|(a, b)| (a - b).abs()).sum::<f32>() < 1e-4,
        "Eclipse Archon rings and crown should hold still with reduced motion enabled");
    let eclipse_motion = render_at(&eclipse, 0.0, 0.9, false);
    assert!(eclipse_orbit.1.iter().zip(&eclipse_motion.1).map(|(a, b)| (a - b).abs()).sum::<f32>() > 50.0,
        "Eclipse Archon rings should precess visibly in normal motion mode");
    eclipse.ai.sub_state = EnemySubState::EclipseCharge;
    let eclipse_charge = render(&eclipse, 1.0, true);
    eclipse.ai.sub_state = EnemySubState::EclipseBurst;
    let eclipse_burst = render(&eclipse, 0.0, true);
    assert!(eclipse_charge.0 > eclipse_orbit.0 + 2.0, "Eclipse Archon arms should extend during charge: orbit {:.2}, charge {:.2}", eclipse_orbit.0, eclipse_charge.0);
    assert!(eclipse_burst.0 > eclipse_orbit.0 + 2.0, "Eclipse Archon pylons should push outward during burst: orbit {:.2}, burst {:.2}", eclipse_orbit.0, eclipse_burst.0);
    assert!(eclipse_orbit.1.iter().zip(&eclipse_charge.1).map(|(a, b)| (a - b).abs()).sum::<f32>() > 10.0);

    let mut queen = Enemy::new(8105, Vec2::ZERO, 100, 80.0, "boss_swarmqueen");
    let queen_idle = render(&queen, 0.0, true);
    assert!(queen_idle.2 > queen_idle.0 * 0.55, "Brood Matriarch should keep a tall, upright silhouette: width {:.2}, height {:.2}", queen_idle.0, queen_idle.2);
    queen.ai.sub_state = EnemySubState::QueenBroodTelegraph;
    let queen_brood = render(&queen, 1.0, true);
    queen.ai.sub_state = EnemySubState::QueenSwarmTelegraph;
    let queen_swarm = render(&queen, 1.0, true);
    queen.ai.sub_state = EnemySubState::QueenVolleyTelegraph;
    let queen_volley = render(&queen, 1.0, true);
    for (name, pose) in [("brood", &queen_brood), ("swarm", &queen_swarm), ("volley", &queen_volley)] {
        let retained_parts = queen_idle.1.len().min(pose.1.len()) as f32
            / queen_idle.1.len().max(pose.1.len()).max(1) as f32;
        assert!(retained_parts > 0.85, "Brood Matriarch should retain the connected body, wings, and legs during the {name} tell");
        assert!(queen_idle.1.iter().zip(&pose.1).map(|(a, b)| (a - b).abs()).sum::<f32>() > 40.0,
            "Brood Matriarch wings and claws should visibly articulate for the {name} tell");
    }
    assert!(queen_brood.1.iter().zip(&queen_swarm.1).map(|(a, b)| (a - b).abs()).sum::<f32>() > 40.0,
        "Brood and swarm tells should use different wing poses");

    let mut brute = Enemy::new(8103, Vec2::ZERO, 100, 80.0, "boss_brute");
    brute.ai.sub_state = EnemySubState::BruteTelegraph;
    let brute_windup = render(&brute, 0.9, false);
    let brute_windup_reduced_motion = render(&brute, 0.9, true);
    brute.ai.sub_state = EnemySubState::BruteCharge;
    let brute_charge = render(&brute, 0.0, false);
    let retained_faces = brute_windup.1.len().min(brute_charge.1.len()) as f32
        / brute_windup.1.len().max(brute_charge.1.len()).max(1) as f32;
    assert!(retained_faces > 0.97, "the Juggernaut should keep its existing limbs while charging, with edge-on degenerate faces filtered");
    assert!(brute_windup.1.iter().zip(&brute_charge.1).map(|(a, b)| (a - b).abs()).sum::<f32>() > 30.0,
        "the Juggernaut should lower into its warning pose and lean into the charge");
    assert!(brute_windup.1.iter().zip(&brute_windup_reduced_motion.1).map(|(a, b)| (a - b).abs()).sum::<f32>() < 1e-4,
        "reduced motion should keep the Juggernaut's static brace pose while removing ambient motion");

    let mut forge = Enemy::new(8104, Vec2::ZERO, 120, 80.0, "boss_trapmaster");
    let forge_idle = render(&forge, 0.0, true);
    forge.ai.sub_state = EnemySubState::TrapmasterTelegraph;
    let forge_warning = render(&forge, 1.0, true);
    let retained_faces = forge_idle.1.len().min(forge_warning.1.len()) as f32
        / forge_idle.1.len().max(forge_warning.1.len()).max(1) as f32;
    assert!(retained_faces > 0.97, "Forge Warden should retain its upright armor as the cannons articulate");
    assert!(forge_warning.0 > forge_idle.0 + 6.0, "Forge Warden gauntlets should drive outward during the spike-array tell");
    assert!(forge_idle.1.iter().zip(&forge_warning.1).map(|(a, b)| (a - b).abs()).sum::<f32>() > 35.0,
        "Forge Warden cannon arms and claw pose should visibly change during its attack tell");
}

#[test]
fn prisma_overlord_keeps_its_slit_eye_and_folds_wings_for_laser_lock() {
    use plouto_rs::render::models3d::draw_boss_model;
    use plouto_rs::sim::enemy::{Enemy, EnemySubState};

    let render = |enemy: &Enemy, windup: f32, time: f32, reduce_motion: bool| {
        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        assert!(draw_boss_model(
            enemy,
            &mut alpha,
            &mut add,
            [320.0, 240.0],
            Vec2::new(0.0, -1.0),
            1.0,
            time,
            windup,
            [132, 204, 232],
            reduce_motion,
        ));
        let mesh: Vec<_> = alpha.instances.iter().filter(|instance| instance.kind == 4).collect();
        let coordinates: Vec<_> = mesh
            .iter()
            .flat_map(|instance| {
                [
                    instance.p0[0],
                    instance.p0[1],
                    instance.p1[0],
                    instance.p1[1],
                    instance.params[0],
                    instance.params[1],
                ]
            })
            .collect();
        let min_y = coordinates.iter().skip(1).step_by(2).copied().fold(f32::INFINITY, f32::min);
        let max_y = coordinates.iter().skip(1).step_by(2).copied().fold(f32::NEG_INFINITY, f32::max);
        let varied_materials = mesh
            .iter()
            .map(|instance| {
                [instance.color[0], instance.color[1], instance.color[2]]
                    .map(|channel| (channel * 100.0).round() as i32)
            })
            .collect::<std::collections::HashSet<_>>()
            .len();
        (coordinates, max_y - min_y, varied_materials)
    };

    let mut prisma = Enemy::new(8110, Vec2::ZERO, 135, 80.0, "boss_laser");
    prisma.ai.phase = 2;
    let idle = render(&prisma, 0.0, 0.4, false);
    assert!(idle.1 > 45.0, "Prisma should retain its tall crystal silhouette");
    assert!(idle.2 >= 8, "the crystal hull, halo, wings, and eye should retain distinct materials");

    prisma.ai.sub_state = EnemySubState::LaserCharge;
    let lock = render(&prisma, 0.9, 0.4, false);
    assert!(
        (idle.0.len() as f32 - lock.0.len() as f32).abs() / (idle.0.len().max(1) as f32) < 0.02,
        "the wings should fold continuously while nearly all stable facets remain"
    );
    assert!(idle.0.iter().zip(&lock.0).map(|(a, b)| (a - b).abs()).sum::<f32>() > 20.0,
        "the twin crystal wings should fold inward during the laser lock");

    let reduced_a = render(&prisma, 0.9, 0.2, true);
    let reduced_b = render(&prisma, 0.9, 1.4, true);
    assert!(reduced_a.0.iter().zip(&reduced_b.0).all(|(a, b)| (a - b).abs() < 1e-5),
        "Prisma should hold a stable pose with reduced motion");
}

#[test]
fn tank_3d_model_matches_artwork_and_animates_drive_and_fire() {
    use plouto_rs::render::models3d::draw_enemy_model;
    use plouto_rs::render::sdf::SdfBatch;
    use plouto_rs::sim::enemy::Enemy;
    use plouto_rs::sim::math::Vec2;

    fn render(enemy: &Enemy, facing: Vec2, time: f32, reduce_motion: bool) -> (Vec<f32>, Vec<[f32; 4]>, usize) {
        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        assert!(draw_enemy_model(
            enemy,
            &mut alpha,
            &mut add,
            [320.0, 240.0],
            facing,
            1.25,
            0.0,
            0.0,
            time,
            0.0,
            1.0,
            [72, 245, 50], // tank keeps its own graphite/cyan/amber palette
            reduce_motion,
        ));
        let coords = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .flat_map(|instance| {
                [
                    instance.p0[0],
                    instance.p0[1],
                    instance.p1[0],
                    instance.p1[1],
                    instance.params[0],
                    instance.params[1],
                ]
            })
            .collect();
        let colors = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .map(|instance| instance.color)
            .collect();
        (coords, colors, add.instances.len())
    }

    let mut idle = Enemy::new(8201, Vec2::ZERO, 100, 80.0, "tank");
    idle.attack_cd = 2.05;
    let idle_pose = render(&idle, Vec2::new(1.0, 0.0), 0.0, false);

    let mut charging = Enemy::new(8202, Vec2::ZERO, 100, 80.0, "tank");
    charging.ai.push_t = 0.52;
    charging.vel = Vec2::new(76.0, 0.0);
    charging.attack_cd = 0.16;
    let drive_pose = render(&charging, Vec2::new(1.0, 0.0), 0.8, false);
    let retained_faces = idle_pose.0.len().min(drive_pose.0.len()) as f32
        / idle_pose.0.len().max(drive_pose.0.len()).max(1) as f32;
    assert!(retained_faces > 0.99, "the tank should keep its wheels and cannons while animating, with edge-on degenerate faces filtered");
    let pose_delta = idle_pose
        .0
        .iter()
        .zip(&drive_pose.0)
        .map(|(a, b)| (a - b).abs())
        .sum::<f32>();
    assert!(pose_delta > 40.0, "drive and firing state should visibly rotate the treads and recoil the cannons");
    assert!(drive_pose.2 > idle_pose.2, "the active ram should add its charge and rear-thrust cues");

    let has_cyan = drive_pose.1.iter().any(|c| c[1] > c[0] * 1.3 && c[2] > c[0] * 1.3);
    let has_amber = drive_pose.1.iter().any(|c| c[0] > c[1] * 1.3 && c[1] > c[2] * 1.3);
    assert!(has_cyan && has_amber, "the armored tank needs both cyan reactor and amber hardware in its own palette");

    for heading in [
        Vec2::new(1.0, 0.0),
        Vec2::new(1.0, 1.0),
        Vec2::new(0.0, 1.0),
        Vec2::new(-1.0, 1.0),
        Vec2::new(-1.0, 0.0),
        Vec2::new(-1.0, -1.0),
        Vec2::new(0.0, -1.0),
        Vec2::new(1.0, -1.0),
    ] {
        let pose = render(&charging, heading, 0.8, false);
        assert!(!pose.0.is_empty(), "tank mesh vanished at {heading:?}");
        assert!(pose.0.iter().all(|value| value.is_finite()), "tank mesh produced invalid geometry at {heading:?}");
    }

    let reduced_a = render(&charging, Vec2::new(1.0, 0.0), 0.0, true);
    let reduced_b = render(&charging, Vec2::new(1.0, 0.0), 2.0, true);
    let reduced_delta = reduced_a
        .0
        .iter()
        .zip(&reduced_b.0)
        .map(|(a, b)| (a - b).abs())
        .sum::<f32>();
    assert!(reduced_delta < 1e-4, "reduced motion should freeze ambient tread and suspension movement");
}

#[test]
fn chaser_3d_model_matches_interceptor_art_and_animates_lunge() {
    use plouto_rs::render::models3d::draw_enemy_model;
    use plouto_rs::render::sdf::SdfBatch;
    use plouto_rs::sim::enemy::Enemy;
    use plouto_rs::sim::math::Vec2;

    fn render(enemy: &Enemy, facing: Vec2, windup: f32, time: f32, reduce_motion: bool) -> (Vec<f32>, Vec<[f32; 4]>, usize) {
        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        assert!(draw_enemy_model(
            enemy,
            &mut alpha,
            &mut add,
            [320.0, 240.0],
            facing,
            1.25,
            0.0,
            0.0,
            time,
            windup,
            1.0,
            [255, 80, 80], // the interceptor keeps its artwork palette
            reduce_motion,
        ));
        let coords = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .flat_map(|instance| [
                instance.p0[0], instance.p0[1],
                instance.p1[0], instance.p1[1],
                instance.params[0], instance.params[1],
            ])
            .collect();
        let colors = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .map(|instance| instance.color)
            .collect();
        (coords, colors, add.instances.len())
    }

    let idle = Enemy::new(8251, Vec2::ZERO, 100, 170.0, "chaser");
    let idle_pose = render(&idle, Vec2::new(1.0, 0.0), 0.0, 0.0, false);
    let mut lunging = Enemy::new(8252, Vec2::ZERO, 100, 170.0, "chaser");
    lunging.vel = Vec2::new(170.0, 0.0);
    lunging.ai.lunge_windup = 0.18;
    let lunge_pose = render(&lunging, Vec2::new(1.0, 0.0), 0.82, 0.8, false);
    assert!(lunge_pose.0.len() > idle_pose.0.len(), "the chaser should add a 3D core to its lunge thrust plume");
    assert!(lunge_pose.2 > idle_pose.2, "the lunge warning should visibly telegraph at the nose");

    let has_cyan = lunge_pose.1.iter().any(|c| c[1] > c[0] * 1.3 && c[2] > c[0] * 1.3);
    let has_amber = lunge_pose.1.iter().any(|c| c[0] > c[1] * 1.3 && c[1] > c[2] * 1.3);
    let has_graphite = lunge_pose.1.iter().any(|c| c[0] < 0.06 && c[1] < 0.08 && c[2] < 0.12);
    assert!(has_cyan && has_amber && has_graphite, "the interceptor needs graphite armor, cyan trim, and amber warning details");

    for heading in [
        Vec2::new(1.0, 0.0), Vec2::new(1.0, 1.0),
        Vec2::new(0.0, 1.0), Vec2::new(-1.0, 1.0),
        Vec2::new(-1.0, 0.0), Vec2::new(-1.0, -1.0),
        Vec2::new(0.0, -1.0), Vec2::new(1.0, -1.0),
    ] {
        let pose = render(&lunging, heading, 0.82, 0.8, false);
        assert!(!pose.0.is_empty(), "chaser mesh vanished at {heading:?}");
        assert!(pose.0.iter().all(|value| value.is_finite()), "chaser mesh produced invalid geometry at {heading:?}");
    }

    let reduced_a = render(&lunging, Vec2::new(1.0, 0.0), 0.82, 0.0, true);
    let reduced_b = render(&lunging, Vec2::new(1.0, 0.0), 0.82, 2.0, true);
    assert_eq!(reduced_a.0, reduced_b.0, "reduced motion should pause the interceptor's ambient fin flex");
}

#[test]
fn bomber_3d_model_matches_mine_layer_art_and_fuse_pulse() {
    use plouto_rs::render::models3d::draw_enemy_model;
    use plouto_rs::render::sdf::SdfBatch;
    use plouto_rs::sim::enemy::Enemy;
    use plouto_rs::sim::math::Vec2;

    fn render(enemy: &Enemy, facing: Vec2, time: f32, reduce_motion: bool) -> (Vec<f32>, Vec<[f32; 4]>, Vec<[f32; 4]>) {
        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        assert!(draw_enemy_model(
            enemy,
            &mut alpha,
            &mut add,
            [320.0, 240.0],
            facing,
            1.25,
            0.0,
            0.0,
            time,
            0.0,
            1.0,
            [255, 160, 50], // the mine-layer uses its artwork palette
            reduce_motion,
        ));
        let coords = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .flat_map(|instance| [
                instance.p0[0], instance.p0[1],
                instance.p1[0], instance.p1[1],
                instance.params[0], instance.params[1],
            ])
            .collect();
        let colors = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .map(|instance| instance.color)
            .collect();
        let effects = add.instances.iter().map(|instance| instance.color).collect();
        (coords, colors, effects)
    }

    let mut bomber = Enemy::new(8261, Vec2::ZERO, 100, 80.0, "bomber");
    bomber.attack_cd = 0.3;
    let idle = render(&bomber, Vec2::new(1.0, 0.0), 0.0, false);
    let bright_fuse = render(&bomber, Vec2::new(1.0, 0.0), std::f32::consts::PI / 44.0, false);
    assert!(bright_fuse.2.last().unwrap()[3] > idle.2.last().unwrap()[3], "the volatile core should brighten as its fuse pulse peaks");

    let has_cyan = bright_fuse.1.iter().any(|c| c[1] > c[0] * 1.3 && c[2] > c[0] * 1.3);
    let has_amber = bright_fuse.1.iter().any(|c| c[0] > c[1] * 1.3 && c[1] > c[2] * 1.3);
    let has_graphite = bright_fuse.1.iter().any(|c| c[0] < 0.06 && c[1] < 0.08 && c[2] < 0.12);
    assert!(has_cyan && has_amber && has_graphite, "the mine-layer needs graphite armor, cyan trim, and amber charges");

    for heading in [
        Vec2::new(1.0, 0.0), Vec2::new(1.0, 1.0),
        Vec2::new(0.0, 1.0), Vec2::new(-1.0, 1.0),
        Vec2::new(-1.0, 0.0), Vec2::new(-1.0, -1.0),
        Vec2::new(0.0, -1.0), Vec2::new(1.0, -1.0),
    ] {
        let pose = render(&bomber, heading, 0.0, false);
        assert!(!pose.0.is_empty(), "bomber mesh vanished at {heading:?}");
        assert!(pose.0.iter().all(|value| value.is_finite()), "bomber mesh produced invalid geometry at {heading:?}");
    }

    let reduced_a = render(&bomber, Vec2::new(1.0, 0.0), 0.0, true);
    let reduced_b = render(&bomber, Vec2::new(1.0, 0.0), 2.0, true);
    assert_eq!(reduced_a.0, reduced_b.0, "reduced motion should stop the bomber's idle rotation");
    assert_eq!(reduced_a.2.last().unwrap()[3], reduced_b.2.last().unwrap()[3], "reduced motion should use a steady reactor pulse");
}

#[test]
fn ranged_3d_model_matches_gunship_art_and_articulates_its_cannons() {
    use plouto_rs::render::models3d::draw_enemy_model;
    use plouto_rs::render::sdf::SdfBatch;
    use plouto_rs::sim::enemy::Enemy;
    use plouto_rs::sim::math::Vec2;

    fn render(enemy: &Enemy, facing: Vec2, windup: f32, time: f32, reduce_motion: bool) -> (Vec<f32>, Vec<[f32; 4]>, Vec<[f32; 4]>) {
        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        assert!(draw_enemy_model(
            enemy,
            &mut alpha,
            &mut add,
            [320.0, 240.0],
            facing,
            1.25,
            0.0,
            0.0,
            time,
            windup,
            1.0,
            [255, 142, 51],
            reduce_motion,
        ));
        let coords = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .flat_map(|instance| [
                instance.p0[0], instance.p0[1],
                instance.p1[0], instance.p1[1],
                instance.params[0], instance.params[1],
            ])
            .collect();
        let colors = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .map(|instance| instance.color)
            .collect();
        let effects = add.instances.iter().map(|instance| instance.color).collect();
        (coords, colors, effects)
    }

    let mut ranged = Enemy::new(8271, Vec2::ZERO, 100, 80.0, "ranged");
    ranged.attack_cd = 0.3;
    let idle = render(&ranged, Vec2::new(1.0, 0.0), 0.0, 0.0, false);
    let loaded = render(&ranged, Vec2::new(1.0, 0.0), 0.9, 0.8, false);
    let has_cyan = loaded.1.iter().any(|c| c[1] > c[0] * 1.3 && c[2] > c[0] * 1.3);
    let has_amber = loaded.1.iter().any(|c| c[0] > c[1] * 1.3 && c[1] > c[2] * 1.3);
    let has_graphite = loaded.1.iter().any(|c| c[0] < 0.06 && c[1] < 0.08 && c[2] < 0.12);
    assert!(has_cyan && has_amber && has_graphite, "the ranged gunship should preserve its graphite, cyan, and amber art palette");

    let animation_delta = idle.0.iter().zip(&loaded.0).map(|(a, b)| (a - b).abs()).sum::<f32>();
    assert!(animation_delta > 50.0, "the paired 3D cannons should lift and recoil through the firing windup");
    let muzzle_signal = loaded.2.iter().zip(&idle.2).map(|(hot, cool)| hot[3] - cool[3]).sum::<f32>();
    assert!(muzzle_signal > 0.0, "both loaded muzzles should brighten with the firing tell");

    for heading in [
        Vec2::new(1.0, 0.0), Vec2::new(1.0, 1.0),
        Vec2::new(0.0, 1.0), Vec2::new(-1.0, 1.0),
        Vec2::new(-1.0, 0.0), Vec2::new(-1.0, -1.0),
        Vec2::new(0.0, -1.0), Vec2::new(1.0, -1.0),
    ] {
        let pose = render(&ranged, heading, 0.45, 0.0, false);
        assert!(!pose.0.is_empty(), "ranged gunship mesh vanished at {heading:?}");
        assert!(pose.0.iter().all(|value| value.is_finite()), "ranged gunship produced invalid geometry at {heading:?}");
    }

    let reduced_a = render(&ranged, Vec2::new(1.0, 0.0), 0.45, 0.0, true);
    let reduced_b = render(&ranged, Vec2::new(1.0, 0.0), 0.45, 2.0, true);
    assert_eq!(reduced_a.0, reduced_b.0, "reduced motion should hold the ranged ship's idle geometry steady");
}

#[test]
fn sniper_3d_model_matches_railgun_art_and_charges_its_channel() {
    use plouto_rs::render::models3d::draw_enemy_model;
    use plouto_rs::render::sdf::SdfBatch;
    use plouto_rs::sim::enemy::Enemy;
    use plouto_rs::sim::math::Vec2;

    fn render(enemy: &Enemy, facing: Vec2, windup: f32, time: f32, reduce_motion: bool) -> (Vec<f32>, Vec<[f32; 4]>, Vec<[f32; 4]>) {
        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        assert!(draw_enemy_model(
            enemy,
            &mut alpha,
            &mut add,
            [320.0, 240.0],
            facing,
            1.25,
            0.0,
            0.0,
            time,
            windup,
            1.0,
            [236, 95, 255],
            reduce_motion,
        ));
        let coords = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .flat_map(|instance| [
                instance.p0[0], instance.p0[1],
                instance.p1[0], instance.p1[1],
                instance.params[0], instance.params[1],
            ])
            .collect();
        let colors = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .map(|instance| instance.color)
            .collect();
        let effects = add.instances.iter().map(|instance| instance.color).collect();
        (coords, colors, effects)
    }

    let mut sniper = Enemy::new(8281, Vec2::ZERO, 100, 90.0, "sniper");
    sniper.attack_cd = 0.3;
    let idle = render(&sniper, Vec2::new(1.0, 0.0), 0.0, 0.0, false);
    let charged = render(&sniper, Vec2::new(1.0, 0.0), 0.9, 0.8, false);
    let has_magenta = charged.1.iter().any(|c| c[0] > c[1] * 1.5 && c[2] > c[1] * 1.5);
    let has_cyan = charged.1.iter().any(|c| c[1] > c[0] * 1.3 && c[2] > c[0] * 1.3);
    let has_graphite = charged.1.iter().any(|c| c[0] < 0.06 && c[1] < 0.08 && c[2] < 0.12);
    assert!(has_magenta && has_cyan && has_graphite, "the railgun should preserve graphite armor, cyan edges, and a violet energy channel");

    let animation_delta = idle.0.iter().zip(&charged.0).map(|(a, b)| (a - b).abs()).sum::<f32>();
    assert!(animation_delta > 50.0, "the 3D rail channel should extend and brighten during the lock-on");
    let charge_signal = charged.2.iter().zip(&idle.2).map(|(hot, cool)| hot[3] - cool[3]).sum::<f32>();
    assert!(charge_signal > 0.0, "the muzzle tell should brighten as the railgun locks its shot");

    for heading in [
        Vec2::new(1.0, 0.0), Vec2::new(1.0, 1.0),
        Vec2::new(0.0, 1.0), Vec2::new(-1.0, 1.0),
        Vec2::new(-1.0, 0.0), Vec2::new(-1.0, -1.0),
        Vec2::new(0.0, -1.0), Vec2::new(1.0, -1.0),
    ] {
        let pose = render(&sniper, heading, 0.5, 0.0, false);
        assert!(!pose.0.is_empty(), "sniper mesh vanished at {heading:?}");
        assert!(pose.0.iter().all(|value| value.is_finite()), "sniper produced invalid geometry at {heading:?}");
    }

    let reduced_a = render(&sniper, Vec2::new(1.0, 0.0), 0.5, 0.0, true);
    let reduced_b = render(&sniper, Vec2::new(1.0, 0.0), 0.5, 2.0, true);
    assert_eq!(reduced_a.0, reduced_b.0, "reduced motion should hold the sniper's model geometry steady");
}

#[test]
fn charger_3d_model_matches_forked_art_and_changes_pose_for_windup_and_dash() {
    use plouto_rs::render::models3d::draw_enemy_model;
    use plouto_rs::render::sdf::SdfBatch;
    use plouto_rs::sim::enemy::Enemy;
    use plouto_rs::sim::math::Vec2;

    fn render(enemy: &Enemy, facing: Vec2, windup: f32, time: f32, reduce_motion: bool) -> (Vec<f32>, Vec<[f32; 4]>, usize) {
        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        assert!(draw_enemy_model(
            enemy,
            &mut alpha,
            &mut add,
            [320.0, 240.0],
            facing,
            1.25,
            0.0,
            0.0,
            time,
            windup,
            1.0,
            [255, 137, 48],
            reduce_motion,
        ));
        let coords = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .flat_map(|instance| [
                instance.p0[0], instance.p0[1],
                instance.p1[0], instance.p1[1],
                instance.params[0], instance.params[1],
            ])
            .collect();
        let colors = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .map(|instance| instance.color)
            .collect();
        (coords, colors, add.instances.len())
    }

    let mut charger = Enemy::new(8291, Vec2::ZERO, 100, 90.0, "charger");
    let idle = render(&charger, Vec2::new(1.0, 0.0), 0.0, 0.0, false);
    let windup = render(&charger, Vec2::new(1.0, 0.0), 0.9, 0.5, false);
    let has_amber = windup.1.iter().any(|c| c[0] > c[1] * 1.3 && c[1] > c[2] * 1.3);
    let has_cyan = windup.1.iter().any(|c| c[1] > c[0] * 1.3 && c[2] > c[0] * 1.3);
    let has_graphite = windup.1.iter().any(|c| c[0] < 0.06 && c[1] < 0.08 && c[2] < 0.12);
    assert!(has_amber && has_cyan && has_graphite, "the charger should retain graphite armor with cyan edges and hot amber prongs");
    let windup_delta = idle.0.iter().zip(&windup.0).map(|(a, b)| (a - b).abs()).sum::<f32>();
    assert!(windup_delta > 50.0, "the paired 3D horns should curl into the launch pose");

    charger.ai.charger_dashing = true;
    charger.vel = Vec2::new(210.0, 0.0);
    let dash = render(&charger, Vec2::new(1.0, 0.0), 0.0, 0.8, false);
    let dash_delta = idle.0.iter().zip(&dash.0).map(|(a, b)| (a - b).abs()).sum::<f32>();
    assert!(dash_delta > windup_delta, "the committed dash should extend both 3D prongs and twin engine flames");
    assert!(dash.2 > idle.2, "the dash should add its twin engine and nose cues");

    for heading in [
        Vec2::new(1.0, 0.0), Vec2::new(1.0, 1.0),
        Vec2::new(0.0, 1.0), Vec2::new(-1.0, 1.0),
        Vec2::new(-1.0, 0.0), Vec2::new(-1.0, -1.0),
        Vec2::new(0.0, -1.0), Vec2::new(1.0, -1.0),
    ] {
        let pose = render(&charger, heading, 0.5, 0.0, false);
        assert!(!pose.0.is_empty(), "charger mesh vanished at {heading:?}");
        assert!(pose.0.iter().all(|value| value.is_finite()), "charger produced invalid geometry at {heading:?}");
    }

    let reduced_a = render(&charger, Vec2::new(1.0, 0.0), 0.0, 0.0, true);
    let reduced_b = render(&charger, Vec2::new(1.0, 0.0), 0.0, 2.0, true);
    assert_eq!(reduced_a.0, reduced_b.0, "reduced motion should hold the active charger pose steady");
}

#[test]
fn spitter_3d_model_matches_acid_gunship_art_and_animates_its_reservoirs() {
    use plouto_rs::render::models3d::draw_enemy_model;
    use plouto_rs::render::sdf::SdfBatch;
    use plouto_rs::sim::enemy::Enemy;
    use plouto_rs::sim::math::Vec2;

    fn render(enemy: &Enemy, facing: Vec2, windup: f32, time: f32, reduce_motion: bool) -> (Vec<f32>, Vec<[f32; 4]>, Vec<[f32; 4]>) {
        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        assert!(draw_enemy_model(
            enemy,
            &mut alpha,
            &mut add,
            [320.0, 240.0],
            facing,
            1.25,
            0.0,
            0.0,
            time,
            windup,
            1.0,
            [181, 255, 76],
            reduce_motion,
        ));
        let coords = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .flat_map(|instance| [
                instance.p0[0], instance.p0[1],
                instance.p1[0], instance.p1[1],
                instance.params[0], instance.params[1],
            ])
            .collect();
        let colors = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .map(|instance| instance.color)
            .collect();
        let effects = add.instances.iter().map(|instance| instance.color).collect();
        (coords, colors, effects)
    }

    let spitter = Enemy::new(8301, Vec2::ZERO, 100, 80.0, "spitter");
    let idle = render(&spitter, Vec2::new(1.0, 0.0), 0.0, 0.0, false);
    let charged = render(&spitter, Vec2::new(1.0, 0.0), 0.9, 0.0, false);
    let has_acid = charged.1.iter().any(|c| c[1] > c[0] * 1.2 && c[1] > c[2] * 1.2);
    let has_cyan = charged.1.iter().any(|c| c[1] > c[0] * 1.3 && c[2] > c[0] * 1.3);
    let has_graphite = charged.1.iter().any(|c| c[0] < 0.06 && c[1] < 0.08 && c[2] < 0.12);
    assert!(has_acid && has_cyan && has_graphite, "the spitter should use lime reservoirs, cyan trim, and graphite ship armor");
    let charge_delta = idle.0.iter().zip(&charged.0).map(|(a, b)| (a - b).abs()).sum::<f32>();
    assert!(charge_delta > 50.0, "the reservoirs and paired spray ports should react in 3D to the volley windup");
    let tell_delta = charged.2.iter().zip(&idle.2).map(|(hot, cool)| hot[3] - cool[3]).sum::<f32>();
    assert!(tell_delta > 0.0, "the acid reservoirs should brighten during the spread warning");

    let bubble_a = render(&spitter, Vec2::new(1.0, 0.0), 0.35, 0.0, false);
    let bubble_b = render(&spitter, Vec2::new(1.0, 0.0), 0.35, 1.0, false);
    let bubble_motion = bubble_a.0.iter().zip(&bubble_b.0).map(|(a, b)| (a - b).abs()).sum::<f32>();
    assert!(bubble_motion > 1.0, "acid bubbles should drift within both reservoirs during play");

    for heading in [
        Vec2::new(1.0, 0.0), Vec2::new(1.0, 1.0),
        Vec2::new(0.0, 1.0), Vec2::new(-1.0, 1.0),
        Vec2::new(-1.0, 0.0), Vec2::new(-1.0, -1.0),
        Vec2::new(0.0, -1.0), Vec2::new(1.0, -1.0),
    ] {
        let pose = render(&spitter, heading, 0.4, 0.2, false);
        assert!(!pose.0.is_empty(), "spitter ship mesh vanished at {heading:?}");
        assert!(pose.0.iter().all(|value| value.is_finite()), "spitter produced invalid geometry at {heading:?}");
    }

    let reduced_a = render(&spitter, Vec2::new(1.0, 0.0), 0.4, 0.0, true);
    let reduced_b = render(&spitter, Vec2::new(1.0, 0.0), 0.4, 2.0, true);
    assert_eq!(reduced_a.0, reduced_b.0, "reduced motion should hold the acid reservoirs steady");
}

#[test]
fn flyer_3d_model_matches_crescent_art_and_flaps_its_wings() {
    use plouto_rs::render::models3d::draw_enemy_model;
    use plouto_rs::render::sdf::SdfBatch;
    use plouto_rs::sim::enemy::Enemy;
    use plouto_rs::sim::math::Vec2;

    fn render(enemy: &Enemy, facing: Vec2, windup: f32, time: f32, reduce_motion: bool) -> (Vec<f32>, Vec<[f32; 4]>) {
        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        assert!(draw_enemy_model(
            enemy,
            &mut alpha,
            &mut add,
            [320.0, 240.0],
            facing,
            1.25,
            0.0,
            0.0,
            time,
            windup,
            1.0,
            [110, 220, 255],
            reduce_motion,
        ));
        let coords = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .flat_map(|instance| [
                instance.p0[0], instance.p0[1],
                instance.p1[0], instance.p1[1],
                instance.params[0], instance.params[1],
            ])
            .collect();
        let colors = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .map(|instance| instance.color)
            .collect();
        (coords, colors)
    }

    let mut flyer = Enemy::new(8311, Vec2::ZERO, 100, 90.0, "flyer");
    flyer.vel = Vec2::new(120.0, 0.0);
    let idle = render(&flyer, Vec2::new(1.0, 0.0), 0.0, 0.0, false);
    let downstroke = render(&flyer, Vec2::new(1.0, 0.0), 0.0, 0.35, false);
    let charging = render(&flyer, Vec2::new(1.0, 0.0), 0.9, 0.35, false);

    let has_cyan = charging.1.iter().any(|c| c[1] > c[0] * 1.3 && c[2] > c[0] * 1.3);
    let has_amber = charging.1.iter().any(|c| c[0] > c[1] * 1.3 && c[1] > c[2] * 1.3);
    let has_graphite = charging.1.iter().any(|c| c[0] < 0.06 && c[1] < 0.08 && c[2] < 0.12);
    assert!(has_cyan && has_amber && has_graphite, "the interceptor should match its graphite, cyan, and amber reference palette");

    let flap_delta = idle.0.iter().zip(&downstroke.0).map(|(a, b)| (a - b).abs()).sum::<f32>();
    let windup_delta = downstroke.0.iter().zip(&charging.0).map(|(a, b)| (a - b).abs()).sum::<f32>();
    assert!(flap_delta > 20.0, "the broad 3D delta wings should move through their flap cycle");
    assert!(windup_delta > 20.0, "the attack warning should pull the wings into a swept launch pose");

    for heading in [
        Vec2::new(1.0, 0.0), Vec2::new(1.0, 1.0),
        Vec2::new(0.0, 1.0), Vec2::new(-1.0, 1.0),
        Vec2::new(-1.0, 0.0), Vec2::new(-1.0, -1.0),
        Vec2::new(0.0, -1.0), Vec2::new(1.0, -1.0),
    ] {
        let pose = render(&flyer, heading, 0.45, 0.0, false);
        assert!(!pose.0.is_empty(), "flyer mesh vanished at {heading:?}");
        assert!(pose.0.iter().all(|value| value.is_finite()), "flyer produced invalid geometry at {heading:?}");
    }

    let reduced_a = render(&flyer, Vec2::new(1.0, 0.0), 0.4, 0.0, true);
    let reduced_b = render(&flyer, Vec2::new(1.0, 0.0), 0.4, 2.0, true);
    assert_eq!(reduced_a.0, reduced_b.0, "reduced motion should keep a steady wing attack pose");
}

#[test]
fn engineer_3d_model_matches_art_and_keeps_its_claw_pose_in_reduced_motion() {
    use plouto_rs::render::models3d::draw_enemy_model;
    use plouto_rs::render::sdf::SdfBatch;
    use plouto_rs::sim::enemy::{Enemy, EnemySubState};
    use plouto_rs::sim::math::Vec2;

    fn render(enemy: &Enemy, facing: Vec2, windup: f32, time: f32, reduce_motion: bool) -> (Vec<f32>, Vec<[f32; 4]>, usize) {
        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        assert!(draw_enemy_model(
            enemy,
            &mut alpha,
            &mut add,
            [320.0, 240.0],
            facing,
            1.25,
            0.0,
            0.0,
            time,
            windup,
            1.0,
            [91, 255, 191],
            reduce_motion,
        ));
        let coords = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .flat_map(|instance| [
                instance.p0[0], instance.p0[1],
                instance.p1[0], instance.p1[1],
                instance.params[0], instance.params[1],
            ])
            .collect();
        let colors = alpha
            .instances
            .iter()
            .filter(|instance| instance.kind == 4)
            .map(|instance| instance.color)
            .collect();
        (coords, colors, add.instances.len())
    }

    let idle_enemy = Enemy::new(8321, Vec2::ZERO, 100, 70.0, "engineer");
    let mut winding_enemy = Enemy::new(8322, Vec2::ZERO, 100, 70.0, "engineer");
    winding_enemy.ai.sub_state = EnemySubState::EngineerWindup;
    winding_enemy.ai.sub_timer = 0.08;
    let idle = render(&idle_enemy, Vec2::new(1.0, 0.0), 0.0, 0.0, false);
    let winding = render(&winding_enemy, Vec2::new(1.0, 0.0), 0.88, 0.5, false);

    let has_cyan = winding.1.iter().any(|c| c[1] > c[0] * 1.3 && c[2] > c[0] * 1.3);
    let has_amber = winding.1.iter().any(|c| c[0] > c[1] * 1.3 && c[1] > c[2] * 1.3);
    let has_graphite = winding.1.iter().any(|c| c[0] < 0.06 && c[1] < 0.08 && c[2] < 0.12);
    assert!(has_cyan && has_amber && has_graphite, "the utility mech should match its graphite, cyan, and amber palette");
    let claw_delta = idle.0.iter().zip(&winding.0).map(|(a, b)| (a - b).abs()).sum::<f32>();
    assert!(claw_delta > 60.0, "both articulated claws should lift and close into the mine placement pose");
    assert!(winding.2 > idle.2, "the mine windup should brighten its chest reactor");

    for heading in [
        Vec2::new(1.0, 0.0), Vec2::new(1.0, 1.0),
        Vec2::new(0.0, 1.0), Vec2::new(-1.0, 1.0),
        Vec2::new(-1.0, 0.0), Vec2::new(-1.0, -1.0),
        Vec2::new(0.0, -1.0), Vec2::new(1.0, -1.0),
    ] {
        let pose = render(&winding_enemy, heading, 0.55, 0.0, false);
        assert!(!pose.0.is_empty(), "engineer mech vanished at {heading:?}");
        assert!(pose.0.iter().all(|value| value.is_finite()), "engineer produced invalid geometry at {heading:?}");
    }

    let reduced_a = render(&winding_enemy, Vec2::new(1.0, 0.0), 0.55, 0.0, true);
    let reduced_b = render(&winding_enemy, Vec2::new(1.0, 0.0), 0.55, 2.0, true);
    assert_eq!(reduced_a.0, reduced_b.0, "reduced motion should keep the engineer's active claw pose instead of canceling it");
}

#[test]
fn swarm_3d_model_matches_delta_fighter_art_and_flaps_in_flight() {
    use plouto_rs::render::models3d::draw_enemy_model;
    use plouto_rs::render::sdf::SdfBatch;
    use plouto_rs::sim::enemy::Enemy;
    use plouto_rs::sim::math::Vec2;

    fn render(enemy: &Enemy, facing: Vec2, time: f32, reduce_motion: bool) -> (Vec<f32>, Vec<[f32; 4]>, usize) {
        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        assert!(draw_enemy_model(
            enemy,
            &mut alpha,
            &mut add,
            [320.0, 240.0],
            facing,
            1.25,
            0.0,
            0.0,
            time,
            0.0,
            1.0,
            [255, 105, 76],
            reduce_motion,
        ));
        let mesh = alpha.instances.iter().filter(|instance| instance.kind == 4);
        let coords = mesh.clone().flat_map(|instance| [
            instance.p0[0], instance.p0[1],
            instance.p1[0], instance.p1[1],
            instance.params[0], instance.params[1],
        ]).collect();
        let colors = mesh.map(|instance| instance.color).collect();
        (coords, colors, add.instances.len())
    }

    let mut swarm = Enemy::new(8331, Vec2::ZERO, 100, 70.0, "swarm");
    swarm.vel = Vec2::new(132.0, 0.0);
    let idle = render(&swarm, Vec2::new(0.0, -1.0), 0.08, false);
    let flapping = render(&swarm, Vec2::new(0.0, -1.0), 0.31, false);

    let has_cyan = idle.1.iter().any(|c| c[1] > c[0] * 1.3 && c[2] > c[0] * 1.3);
    let has_warm_eye = idle.1.iter().any(|c| c[0] > c[1] * 1.35 && c[1] > c[2] * 1.18);
    let has_graphite = idle.1.iter().any(|c| c[0] < 0.06 && c[1] < 0.08 && c[2] < 0.12);
    assert!(has_cyan && has_warm_eye && has_graphite, "swarm fighter should match the graphite, cyan, and orange-red artwork palette");
    let flap_delta = idle.0.iter().zip(&flapping.0).map(|(a, b)| (a - b).abs()).sum::<f32>();
    assert!(flap_delta > 8.0, "swept wing panels and engine plume should animate in flight");
    assert!(idle.2 > 0, "the optic and lift ring should keep their restrained feedback glows");

    let front = render(&swarm, Vec2::new(0.0, -1.0), 0.31, false);
    let turned_away = render(&swarm, Vec2::new(0.0, 1.0), 0.31, false);
    assert_ne!(front.0, turned_away.0, "the optic and hull details should turn with the 3D model");
    for heading in [
        Vec2::new(1.0, 0.0), Vec2::new(1.0, 1.0),
        Vec2::new(0.0, 1.0), Vec2::new(-1.0, 1.0),
        Vec2::new(-1.0, 0.0), Vec2::new(-1.0, -1.0),
        Vec2::new(0.0, -1.0), Vec2::new(1.0, -1.0),
    ] {
        let pose = render(&swarm, heading, 0.31, false);
        assert!(!pose.0.is_empty(), "swarm fighter vanished at {heading:?}");
        assert!(pose.0.iter().all(|value| value.is_finite()), "swarm produced invalid geometry at {heading:?}");
    }

    let reduced_a = render(&swarm, Vec2::new(0.0, -1.0), 0.08, true);
    let reduced_b = render(&swarm, Vec2::new(0.0, -1.0), 2.0, true);
    assert_eq!(reduced_a.0, reduced_b.0, "reduced motion should keep a stable wing and engine pose");
}

#[test]
fn egg_sac_3d_model_splits_its_shell_as_hatching_approaches() {
    use plouto_rs::render::models3d::draw_enemy_model;
    use plouto_rs::render::sdf::SdfBatch;
    use plouto_rs::sim::enemy::Enemy;
    use plouto_rs::sim::math::Vec2;

    fn render(enemy: &Enemy, facing: Vec2, time: f32, reduce_motion: bool) -> (Vec<f32>, Vec<[f32; 4]>, Vec<[f32; 4]>) {
        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        assert!(draw_enemy_model(
            enemy,
            &mut alpha,
            &mut add,
            [320.0, 240.0],
            facing,
            1.25,
            0.0,
            0.0,
            time,
            0.0,
            1.0,
            [255, 113, 131],
            reduce_motion,
        ));
        let mesh = alpha.instances.iter().filter(|instance| instance.kind == 4);
        let coords = mesh.clone().flat_map(|instance| [
            instance.p0[0], instance.p0[1],
            instance.p1[0], instance.p1[1],
            instance.params[0], instance.params[1],
        ]).collect();
        let colors = mesh.map(|instance| instance.color).collect();
        let effects = add.instances.iter().map(|instance| [
            instance.p1[0], instance.p1[1], instance.color[3], instance.params[0],
        ]).collect();
        (coords, colors, effects)
    }

    let closed = Enemy::new(8341, Vec2::ZERO, 100, 70.0, "egg_sac");
    let mut hatching = Enemy::new(8342, Vec2::ZERO, 100, 70.0, "egg_sac");
    hatching.ai.hatch_timer = 0.48;
    let sealed = render(&closed, Vec2::new(0.0, -1.0), 0.0, false);
    let open = render(&hatching, Vec2::new(0.0, -1.0), 0.7, false);

    let has_coral = open.1.iter().any(|c| c[0] > c[1] * 1.18 && c[2] > c[1] * 1.05);
    let has_shell = open.1.iter().any(|c| c[0] > 0.16 && c[0] < c[1] * 1.5 && c[2] > c[1] * 0.8);
    let has_dark_seams = open.1.iter().any(|c| c[0] < 0.05 && c[1] < 0.05 && c[2] < 0.08);
    assert!(has_coral && has_shell && has_dark_seams, "the cocoon should retain its charcoal shell, pale ribs, and coral hatch core");
    let opening_delta = sealed.0.iter().zip(&open.0).map(|(a, b)| (a - b).abs()).sum::<f32>();
    assert!(opening_delta > 80.0, "paired shell plates should separate and expose the hatch core as the timer falls");
    assert_ne!(sealed.2, open.2, "the close-range hatch flare should strengthen with urgency");

    for heading in [
        Vec2::new(1.0, 0.0), Vec2::new(1.0, 1.0),
        Vec2::new(0.0, 1.0), Vec2::new(-1.0, 1.0),
        Vec2::new(-1.0, 0.0), Vec2::new(-1.0, -1.0),
        Vec2::new(0.0, -1.0), Vec2::new(1.0, -1.0),
    ] {
        let pose = render(&hatching, heading, 0.7, false);
        assert!(!pose.0.is_empty(), "egg sac vanished at {heading:?}");
        assert!(pose.0.iter().all(|value| value.is_finite()), "egg sac produced invalid geometry at {heading:?}");
    }

    let front = render(&hatching, Vec2::new(0.0, -1.0), 0.7, false);
    let turned_away = render(&hatching, Vec2::new(0.0, 1.0), 0.7, false);
    assert_ne!(front.0, turned_away.0, "the hatch slit should turn naturally with the 3D cocoon");
    let reduced_a = render(&hatching, Vec2::new(0.0, -1.0), 0.0, true);
    let reduced_b = render(&hatching, Vec2::new(0.0, -1.0), 2.0, true);
    assert_eq!(reduced_a.0, reduced_b.0, "the hatch opening pose should be preserved and stable in reduced-motion mode");
}
