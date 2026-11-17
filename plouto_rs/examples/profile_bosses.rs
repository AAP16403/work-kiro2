use std::env;
use std::fs;

use plouto_rs::sim::math::Vec2;
use plouto_rs::sim::replay::SIMULATION_RULES_VERSION;
use plouto_rs::sim::state::{
    DamageTarget, RunSetup, SimEvent, SimInput, SimState,
};
use plouto_rs::sim::step::{apply_boss_perm_reward, apply_boss_temp_reward, step};
use serde::Serialize;

const DT: f32 = 1.0 / 60.0;
const SEEDS: [u64; 3] = [90_000, 90_001, 90_002];
const DIFFICULTIES: [&str; 3] = ["easy", "normal", "hard"];
const LAST_BOSS_WAVE: i32 = 40;
const MAX_STEPS: usize = 120_000;

#[derive(Debug, Serialize)]
struct BossEncounterResult {
    difficulty: String,
    seed: u64,
    wave: i32,
    boss: String,
    max_hp: i32,
    time_to_kill_s: f32,
    phase_dwell_s: [f32; 3],
    player_health_damage_received: i32,
    player_shield_damage_received: i32,
    player_damage_events: i32,
    player_damage: i32,
    ultra_damage: i32,
    ultra_damage_share_pct: f32,
    player_dps: f32,
    ultra_uses: i32,
    ultra_charges_available_at_start: i32,
    ultra_boss_hits: i32,
    ultra_unique_targets_hit: usize,
    ultra_unique_targets_killed: usize,
    ultra_shockwave_count: usize,
    weapon_at_spawn: String,
    weapon_damage_at_spawn: i32,
}

#[derive(Debug, Serialize)]
struct RunResult {
    difficulty: String,
    seed: u64,
    ultra_mode: String,
    reached_wave: i32,
    sim_time_s: f32,
    game_over: bool,
    timed_out: bool,
    encounters: Vec<BossEncounterResult>,
}

#[derive(Debug)]
struct ActiveBoss {
    id: u64,
    wave: i32,
    behavior: String,
    max_hp: i32,
    started_at: f32,
    phase: usize,
    phase_dwell_s: [f32; 3],
    player_health_damage_received: i32,
    player_shield_damage_received: i32,
    player_damage_events: i32,
    player_damage: i32,
    ultra_damage: i32,
    ultra_uses_at_start: i32,
    ultra_charges_at_start: i32,
    ultra_boss_hits: i32,
    ultra_targets_hit: Vec<u64>,
    ultra_targets_killed: Vec<u64>,
    ultra_shockwave_count: usize,
    weapon: String,
    weapon_damage: i32,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let output_path = env::args().nth(1);
    let mut runs = Vec::new();
    for difficulty in DIFFICULTIES {
        for seed in SEEDS {
            runs.push(profile_run(difficulty, seed, false));
            runs.push(profile_run(difficulty, seed, true));
        }
    }

    let report = serde_json::json!({
        "kind": "authored-boss-live-run-profile",
        "rules_version": SIMULATION_RULES_VERSION,
        "policy": "full run from wave 1; auto-fire on; aim nearest live enemy with linear lead; orbit and edge avoidance; Dash every 100 frames; first boss-reward choices; player hull raised only to isolate encounter timing; one comparison mode tops up exactly one ready Ultra charge at the start of each boss encounter",
        "fixed_dt_seconds": DT,
        "max_steps_per_run": MAX_STEPS,
        "seeds": SEEDS,
        "difficulties": DIFFICULTIES,
        "runs": runs,
    });
    let json = serde_json::to_string_pretty(&report)?;
    if let Some(path) = output_path {
        fs::write(path, &json)?;
    }
    println!("{json}");
    Ok(())
}

fn profile_run(difficulty: &str, seed: u64, guarantee_ultra: bool) -> RunResult {
    let setup = RunSetup {
        seed,
        difficulty: difficulty.to_string(),
        auto_shoot: true,
        ..RunSetup::default()
    };
    let mut state = SimState::new(setup);
    // Preserve the ordinary upgrade, pickup, weapon, and boss progression while
    // preventing player death from censoring late-boss duration measurements.
    state.player.max_hp = 1_000_000;
    state.player.hp = state.player.max_hp;
    let mut active_boss: Option<ActiveBoss> = None;
    let mut encounters = Vec::new();

    for frame in 0..MAX_STEPS {
        if state.wave > LAST_BOSS_WAVE && state.enemies.is_empty() {
            break;
        }
        apply_first_boss_reward(&mut state);

        let time_before = state.time;
        let boss_before = state
            .enemies
            .iter()
            .find(|enemy| enemy.is_boss() && !enemy.is_dead && enemy.hp > 0)
            .map(|boss| (boss.id, boss.ai.phase.clamp(0, 2) as usize));

        let input = bot_input(&state, frame);
        let events = step(&mut state, &input, DT);
        let elapsed = (state.time - time_before).max(0.0);
        let boss_after = state
            .enemies
            .iter()
            .find(|enemy| enemy.is_boss() && !enemy.is_dead && enemy.hp > 0)
            .map(|boss| {
                (
                    boss.id,
                    boss.behavior.clone(),
                    boss.ai.phase.clamp(0, 2) as usize,
                    boss.ai.boss_max_hp.max(boss.max_hp),
                    boss.ai.phase,
                )
            });

        if active_boss.is_none() {
            if let Some((id, behavior, phase, max_hp, _)) = boss_after.as_ref() {
                if guarantee_ultra {
                    state.player.ultra_charges = 1;
                    state.player.ultra_cd_until = state.time;
                }
                active_boss = Some(ActiveBoss {
                    id: *id,
                    wave: state.wave,
                    behavior: behavior.clone(),
                    max_hp: *max_hp,
                    started_at: time_before,
                    phase: *phase,
                    phase_dwell_s: [0.0; 3],
                    player_health_damage_received: 0,
                    player_shield_damage_received: 0,
                    player_damage_events: 0,
                    player_damage: 0,
                    ultra_damage: 0,
                    ultra_uses_at_start: state.run_stats.ultra_uses,
                    ultra_charges_at_start: state.player.ultra_charges,
                    ultra_boss_hits: 0,
                    ultra_targets_hit: Vec::new(),
                    ultra_targets_killed: Vec::new(),
                    ultra_shockwave_count: 0,
                    weapon: state.player.current_weapon.name.clone(),
                    weapon_damage: state.effective_player_damage(),
                });
            }
        }

        if let Some(encounter) = active_boss.as_mut() {
            let target = DamageTarget::Enemy(encounter.id);
            for event in &events {
                if let SimEvent::DamageResolved(result) = event {
                    if result.source == "ultra" {
                        if let DamageTarget::Enemy(hit_id) = result.target {
                            if !encounter.ultra_targets_hit.contains(&hit_id) {
                                encounter.ultra_targets_hit.push(hit_id);
                            }
                            if result.killed
                                && !encounter.ultra_targets_killed.contains(&hit_id)
                            {
                                encounter.ultra_targets_killed.push(hit_id);
                            }
                        }
                    }
                    if result.target == target && result.health_damage > 0 {
                        encounter.player_damage = encounter
                            .player_damage
                            .saturating_add(result.health_damage);
                        if result.source == "ultra" {
                            encounter.ultra_damage = encounter
                                .ultra_damage
                                .saturating_add(result.health_damage);
                            encounter.ultra_boss_hits += 1;
                        }
                    }
                    if result.target == DamageTarget::Player
                        && (result.health_damage > 0 || result.shield_damage > 0)
                    {
                        encounter.player_health_damage_received = encounter
                            .player_health_damage_received
                            .saturating_add(result.health_damage);
                        encounter.player_shield_damage_received = encounter
                            .player_shield_damage_received
                            .saturating_add(result.shield_damage);
                        encounter.player_damage_events += 1;
                    }
                }
                if let SimEvent::UltraFlash { radius, .. } = event {
                    if *radius > 120.0 {
                        encounter.ultra_shockwave_count += 1;
                    }
                }
            }
            let phase_during_step = boss_before
                .filter(|(id, _)| *id == encounter.id)
                .map(|(_, phase)| phase)
                .unwrap_or(encounter.phase);
            encounter.phase_dwell_s[phase_during_step] += elapsed;
            if let Some((id, _, phase_after, _, _)) = boss_after.as_ref() {
                if *id == encounter.id && *phase_after != encounter.phase {
                    encounter.phase = *phase_after;
                }
            }
        }

        if let Some(encounter) = active_boss.take() {
            let boss_is_alive = boss_after
                .as_ref()
                .is_some_and(|(id, _, _, _, _)| *id == encounter.id);
            if boss_is_alive {
                active_boss = Some(encounter);
            } else {
                let duration = (state.time - encounter.started_at).max(0.0);
                let dps = if duration > 0.0 {
                    encounter.player_damage as f32 / duration
                } else {
                    0.0
                };
                let ultra_damage_share_pct = if encounter.player_damage > 0 {
                    encounter.ultra_damage as f32 / encounter.player_damage as f32 * 100.0
                } else {
                    0.0
                };
                encounters.push(BossEncounterResult {
                    difficulty: difficulty.to_string(),
                    seed,
                    wave: encounter.wave,
                    boss: encounter.behavior,
                    max_hp: encounter.max_hp,
                    time_to_kill_s: duration,
                    phase_dwell_s: encounter.phase_dwell_s,
                    player_health_damage_received: encounter.player_health_damage_received,
                    player_shield_damage_received: encounter.player_shield_damage_received,
                    player_damage_events: encounter.player_damage_events,
                    player_damage: encounter.player_damage,
                    ultra_damage: encounter.ultra_damage,
                    ultra_damage_share_pct,
                    player_dps: dps,
                    ultra_uses: state
                        .run_stats
                        .ultra_uses
                        .saturating_sub(encounter.ultra_uses_at_start),
                    ultra_charges_available_at_start: encounter.ultra_charges_at_start,
                    ultra_boss_hits: encounter.ultra_boss_hits,
                    ultra_unique_targets_hit: encounter.ultra_targets_hit.len(),
                    ultra_unique_targets_killed: encounter.ultra_targets_killed.len(),
                    ultra_shockwave_count: encounter.ultra_shockwave_count,
                    weapon_at_spawn: encounter.weapon,
                    weapon_damage_at_spawn: encounter.weapon_damage,
                });
            }
        }

        drop(events);
        if state.game_over {
            break;
        }
    }

    RunResult {
        difficulty: difficulty.to_string(),
        seed,
        ultra_mode: if guarantee_ultra {
            "guaranteed-one-ready-charge-each-boss".to_string()
        } else {
            "natural-drop-progression".to_string()
        },
        reached_wave: state.wave,
        sim_time_s: state.time,
        game_over: state.game_over,
        timed_out: state.wave <= LAST_BOSS_WAVE,
        encounters,
    }
}

fn apply_first_boss_reward(state: &mut SimState) {
    let choices = state.pending_boss_reward.as_ref().map(|offer| {
        (
            offer
                .temp_options
                .first()
                .map(|reward| (reward.key, reward.duration)),
            offer.perm_options.first().map(|reward| reward.key),
        )
    });
    if let Some((temp, perm)) = choices {
        if let Some((key, duration)) = temp {
            apply_boss_temp_reward(state, key, duration);
        }
        if let Some(key) = perm {
            apply_boss_perm_reward(state, key);
        }
    }
}

fn bot_input(state: &SimState, frame: usize) -> SimInput {
    let radial = state.player.pos.normalized();
    let orbit = if radial.length_squared() > 1.0e-6 {
        radial.perp()
    } else {
        Vec2::new((state.time * 0.7).cos(), (state.time * 0.7).sin())
    };
    let edge_steer = if state.player.pos.length() > state.room_radius * 0.72 {
        -radial
    } else {
        Vec2::ZERO
    };
    let nearest = state
        .enemies
        .iter()
        .filter(|enemy| !enemy.is_dead && enemy.hp > 0)
        .min_by(|a, b| {
            (a.pos - state.player.pos)
                .length_squared()
                .total_cmp(&(b.pos - state.player.pos).length_squared())
        });
    let (aim_world, dodge, approach) = if let Some(enemy) = nearest {
        let to_enemy = enemy.pos - state.player.pos;
        let away = -to_enemy.normalized();
        let approach_range = if state.player.current_weapon.projectile_type == "flak" {
            175.0
        } else {
            280.0
        };
        (
            enemy.pos
                + enemy.vel
                    * (to_enemy.length()
                        / state.player.current_weapon.projectile_speed.max(1.0))
                    .min(0.6),
            if to_enemy.length() < 118.0 {
                away * 0.8
            } else {
                Vec2::ZERO
            },
            if to_enemy.length() > approach_range {
                to_enemy.normalized() * 0.85
            } else {
                Vec2::ZERO
            },
        )
    } else {
        (
            state.player.pos + Vec2::new(180.0, 0.0),
            Vec2::ZERO,
            Vec2::ZERO,
        )
    };
    let movement = (orbit * 0.78 + edge_steer + dodge + approach).normalized();
    SimInput {
        move_dir: movement,
        aim_world,
        fire_held: true,
        dash_pressed: frame % 100 == 0 && frame > 0,
        ultra_pressed: state.player.ultra_charges > 0
            && state.player.ultra_cd_until <= state.time,
        ..SimInput::default()
    }
}
