use plouto_rs::render::particles::{ParticleKind, ParticleSystem};
use plouto_rs::sim::config::{PLAYER_MORTAR_BLAST_RADIUS, PLAYER_MORTAR_BLAST_SECONDS};
use plouto_rs::sim::enemy::Enemy;
use plouto_rs::sim::math::Vec2;
use plouto_rs::sim::player::Player;
use plouto_rs::sim::powerup::{apply_powerup, expire_weapon_pickup, PowerUp};
use plouto_rs::sim::projectile::Projectile;
use plouto_rs::sim::rng::SimRng;
use plouto_rs::sim::specials::{ChainSystem, RepulsorSystem};
use plouto_rs::sim::state::{RunSetup, SimEvent, SimInput, SimState};
use plouto_rs::sim::step::step;
use plouto_rs::sim::weapons::{
    get_effective_fire_rate, get_weapon, weapon_min_cooldown, weapon_pickup_seconds,
};

const DT: f32 = 1.0 / 60.0;

#[test]
fn mortar_reload_is_enforced_by_live_auto_fire_even_with_stacked_fire_rate() {
    let mortar = get_weapon("mortar");
    let min_cooldown = weapon_min_cooldown(&mortar);
    assert!((min_cooldown - 1.30).abs() < 1.0e-6);
    assert!(get_effective_fire_rate(&mortar, 0.01) >= min_cooldown);

    let mut state = SimState::new(RunSetup {
        auto_shoot: true,
        ..RunSetup::default()
    });
    state.wave_active = true;
    state.player.current_weapon = mortar;
    state.player.fire_rate = 0.01;
    state.player.last_shot = -10.0;
    state.player.next_shot_time = 0.0;

    // Keep the wave active without putting a target in the mortar's flight path.
    let mut blocker = Enemy::new(7001, Vec2::new(-400.0, 400.0), 10_000, 0.0, "egg_sac");
    blocker.ai.hatch_timer = 100.0;
    state.enemies.push(blocker);

    let mut shot_times = Vec::new();
    for _ in 0..360 {
        let events = step(
            &mut state,
            &SimInput {
                aim_world: Vec2::new(420.0, 0.0),
                ..SimInput::default()
            },
            DT,
        );
        if events
            .iter()
            .any(|event| matches!(event, SimEvent::MuzzleFlash { .. }))
        {
            shot_times.push(state.time);
        }
    }

    assert!(shot_times.len() >= 4, "mortar stopped firing: {shot_times:?}");
    for pair in shot_times.windows(2) {
        let interval = pair[1] - pair[0];
        assert!(
            interval >= min_cooldown - 0.001,
            "mortar fired after only {interval:.3}s; minimum is {min_cooldown:.2}s"
        );
    }
}

#[test]
fn temporary_mortar_pickup_expires_after_five_seconds_and_restores_primary() {
    let mortar = get_weapon("mortar");
    assert_eq!(weapon_pickup_seconds(&mortar), 5.0);

    let mut player = Player::default_at_origin();
    let mut chain = ChainSystem::new();
    let mut repulsor = RepulsorSystem::new();
    let mut rng = SimRng::new(73);
    let pickup = PowerUp::new(Vec2::ZERO, "weapon", Some("mortar".to_string()));
    apply_powerup(
        &mut player,
        &pickup,
        10.0,
        20,
        &mut chain,
        &mut repulsor,
        &mut rng,
    );

    assert_eq!(player.current_weapon.key, "mortar");
    assert_eq!(player.weapon_until, 15.0);
    assert!(!expire_weapon_pickup(&mut player, 14.999));
    assert!(expire_weapon_pickup(&mut player, 15.0));
    assert_eq!(player.current_weapon.key, "basic");
    assert!(player.weapon_base.is_none());
}

#[test]
fn mortar_splash_reaches_168_units_and_keeps_a_240ms_rendered_blast() {
    let mut state = SimState::new(RunSetup {
        auto_shoot: false,
        ..RunSetup::default()
    });
    state.wave_active = true;

    let mut inside = Enemy::new(7101, Vec2::ZERO, 1_000, 0.0, "egg_sac");
    inside.ai.hatch_timer = 100.0;
    let target_radius = inside.radius;
    inside.pos = Vec2::new(PLAYER_MORTAR_BLAST_RADIUS + target_radius - 1.0, 0.0);
    state.enemies.push(inside);

    let mut outside = Enemy::new(7102, Vec2::ZERO, 1_000, 0.0, "egg_sac");
    outside.ai.hatch_timer = 100.0;
    outside.pos = Vec2::new(PLAYER_MORTAR_BLAST_RADIUS + outside.radius + 1.0, 0.0);
    state.enemies.push(outside);

    let mut shell = Projectile::new(Vec2::ZERO, Vec2::ZERO, 100, 0.0, "player", "mortar");
    shell.weapon_name = "Siege Mortar".to_string();
    state.projectiles.push(shell);
    let events = step(&mut state, &SimInput::default(), DT);

    let hp = |id| state.enemies.iter().find(|enemy| enemy.id == id).unwrap().hp;
    assert!(hp(7101) < 1_000, "target inside the 168-unit blast was missed");
    assert_eq!(hp(7102), 1_000, "target beyond the 168-unit blast was hit");

    let (blast_radius, blast_ttl) = events
        .iter()
        .find_map(|event| match event {
            SimEvent::Shockwave {
                max_radius, ttl, ..
            } if (*max_radius - PLAYER_MORTAR_BLAST_RADIUS).abs() < 1.0e-6 => {
                Some((*max_radius, *ttl))
            }
            _ => None,
        })
        .expect("mortar detonation did not emit its blast ring");
    assert_eq!(blast_radius, 168.0);
    assert!((blast_ttl - PLAYER_MORTAR_BLAST_SECONDS).abs() < 1.0e-6);
    assert_eq!(blast_ttl, 0.24);

    let mut particles = ParticleSystem::new();
    particles.handle_sim_events(&events, false);
    let ring = particles
        .particles
        .iter()
        .find(|particle| particle.kind == ParticleKind::Ring)
        .expect("mortar blast ring was not rendered");
    assert!((ring.max_life - 0.24).abs() < 1.0e-6);
}
