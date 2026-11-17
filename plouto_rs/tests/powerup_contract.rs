use plouto_rs::sim::math::Vec2;
use plouto_rs::sim::player::Player;
use plouto_rs::sim::powerup::{
    apply_powerup, expire_weapon_pickup, powerup_duration_seconds, timed_powerup_states,
    PowerUp,
};
use plouto_rs::sim::rng::SimRng;
use plouto_rs::sim::specials::{ChainSystem, RepulsorSystem};
use plouto_rs::sim::weapons::get_weapon;

fn apply(
    player: &mut Player,
    kind: &str,
    weapon_key: Option<&str>,
    now: f32,
    chain: &mut ChainSystem,
    repulsor: &mut RepulsorSystem,
    rng: &mut SimRng,
) -> plouto_rs::sim::powerup::PickupOutcome {
    let pickup = PowerUp::new(
        Vec2::ZERO,
        kind,
        weapon_key.map(str::to_string),
    );
    apply_powerup(player, &pickup, now, 8, chain, repulsor, rng)
}

#[test]
fn timed_pickups_refresh_from_the_latest_collection_time() {
    for kind in [
        "boost",
        "drone",
        "magnet",
        "ricochet",
        "homing",
        "laser",
        "vortex",
        "time_slow",
    ] {
        let mut player = Player::default_at_origin();
        let mut chain = ChainSystem::new();
        let mut repulsor = RepulsorSystem::new();
        let mut rng = SimRng::new(41);
        let duration = powerup_duration_seconds(kind, None).unwrap();

        apply(&mut player, kind, None, 5.0, &mut chain, &mut repulsor, &mut rng);
        let first_until = timed_powerup_states(&player)
            .into_iter()
            .find(|status| status.kind == kind)
            .unwrap()
            .until;
        assert!((first_until - (5.0 + duration)).abs() < 1.0e-5, "{kind}");

        apply(&mut player, kind, None, 6.0, &mut chain, &mut repulsor, &mut rng);
        let refreshed_until = timed_powerup_states(&player)
            .into_iter()
            .find(|status| status.kind == kind)
            .unwrap()
            .until;
        assert!((refreshed_until - (6.0 + duration)).abs() < 1.0e-5, "{kind}");
        assert!(refreshed_until > first_until, "{kind} did not refresh");
    }

    let mut player = Player::default_at_origin();
    let mut chain = ChainSystem::new();
    let mut repulsor = RepulsorSystem::new();
    let mut rng = SimRng::new(42);
    let duration = powerup_duration_seconds("chain", None).unwrap();
    apply(&mut player, "chain", None, 5.0, &mut chain, &mut repulsor, &mut rng);
    apply(&mut player, "chain", None, 6.0, &mut chain, &mut repulsor, &mut rng);
    assert!((chain.until - (6.0 + duration)).abs() < 1.0e-5);
}

#[test]
fn replacing_a_temporary_weapon_keeps_the_original_and_restarts_its_timer() {
    let mut player = Player::default_at_origin();
    player.current_weapon = get_weapon("basic");
    let mut chain = ChainSystem::new();
    let mut repulsor = RepulsorSystem::new();
    let mut rng = SimRng::new(43);

    apply(
        &mut player,
        "weapon",
        Some("heavy"),
        10.0,
        &mut chain,
        &mut repulsor,
        &mut rng,
    );
    assert_eq!(player.current_weapon.key, "heavy");
    assert_eq!(player.weapon_base.as_ref().unwrap().key, "basic");
    assert!((player.weapon_until - 18.0).abs() < 1.0e-5);

    apply(
        &mut player,
        "weapon",
        Some("railgun"),
        12.0,
        &mut chain,
        &mut repulsor,
        &mut rng,
    );
    assert_eq!(player.current_weapon.key, "railgun");
    assert_eq!(player.weapon_base.as_ref().unwrap().key, "basic");
    assert!((player.weapon_until - 24.0).abs() < 1.0e-5);
    assert!(!expire_weapon_pickup(&mut player, 18.0));
    assert!(expire_weapon_pickup(&mut player, 24.0));
    assert_eq!(player.current_weapon.key, "basic");
    assert!(player.weapon_base.is_none());
}

#[test]
fn charge_pickups_queue_repulsor_pulses_and_cap_ultra_charges() {
    let mut player = Player::default_at_origin();
    let mut chain = ChainSystem::new();
    let mut repulsor = RepulsorSystem::new();
    let mut rng = SimRng::new(44);

    assert!(apply(&mut player, "repulsor", None, 1.0, &mut chain, &mut repulsor, &mut rng).repulsor_fired);
    assert!(!apply(&mut player, "repulsor", None, 2.0, &mut chain, &mut repulsor, &mut rng).repulsor_fired);
    assert!(!apply(&mut player, "repulsor", None, 3.0, &mut chain, &mut repulsor, &mut rng).repulsor_fired);
    assert_eq!(repulsor.charges, 2);
    assert!(apply(&mut player, "repulsor", None, 4.0, &mut chain, &mut repulsor, &mut rng).repulsor_fired);
    assert_eq!(repulsor.charges, 2);
    assert!(repulsor.poll_ready(repulsor.cooldown_until));
    assert_eq!(repulsor.charges, 1);

    player.ultra_charges = 0;
    for expected in 1..=player.ultra_max_charges {
        apply(&mut player, "ultra", None, 5.0 + expected as f32, &mut chain, &mut repulsor, &mut rng);
        assert_eq!(player.ultra_charges, expected);
    }
    player.shield = 0;
    apply(&mut player, "ultra", None, 9.0, &mut chain, &mut repulsor, &mut rng);
    assert_eq!(player.ultra_charges, player.ultra_max_charges);
    assert_eq!(player.shield, 25);
}
