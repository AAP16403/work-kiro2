use std::f32::consts::TAU;

use crate::sim::ai_skill::ai_skill;
use crate::sim::behaviors::{
    cancel_attack_for_interrupt, commit_granted_attacks, remove_telegraph,
    steer_clear_of_obstacles, update_regular_behavior, AttackScheduler, BehaviorContext,
    TELEGRAPH_OWNER,
};
use crate::sim::bosses::update_boss_enemy;
use crate::sim::config::{
    BOOST_DAMAGE_REDUCTION, BOOST_RAM_COOLDOWN_SECONDS, BOOST_RAM_DAMAGE, BOOST_SPEED_MULT,
    BOSS_WAVE_EVERY, CHAIN_HOPS_PER_STEP_MAX,
    CHAIN_ARC_COLOR, ELITE_MENDER_COLOR, ELITE_REFLECT_COOLDOWN, ELITE_VOLATILE_COLOR,
    elite_affix_color, ELITE_REFLECT_SPEED, ELITE_SPLIT_COUNT, ELITE_SPLIT_HP_FRAC,
    ELITE_VOLATILE_BLAST_DAMAGE, ELITE_VOLATILE_BLAST_RADIUS, ENEMY_CONTACT_DAMAGE, FANFARE_MIN_GAP,
    SHAKE_DECAY, SHAKE_HIT_CEILING,
    SHAKE_HIT_FRAME_MAX, SHAKE_HIT_IMPULSE, SHAKE_CRIT_IMPULSE, SHAKE_PLAYER_HIT_BASE,
    SHAKE_PLAYER_HIT_MAX, SHAKE_PLAYER_HIT_PER_HP, TANK_DEATH_BLAST_DAMAGE,
    TANK_DEATH_BLAST_RADIUS, ULTRA_BEAM_COLOR, ULTRA_BEAM_THICKNESS, ULTRA_BEAM_TTL,
    ULTRA_BLAST_RADIUS, ULTRA_COOLDOWN, ULTRA_DAMAGE_BASE, ULTRA_DAMAGE_MULT,
    EVENT_METEOR_DODGE_WINDOW,
    EVENT_METEOR_RADIUS, EVENT_METEOR_WARN, PLAYER_HIT_GRACE_SECONDS, enemy_color, powerup_color,
};
use crate::sim::director::AttackDirector;
use crate::sim::drone::update_drone;
use crate::sim::enemy::{assign_run_keys, boss_title, swarm_formation_key, Enemy, EnemySubState};
use crate::sim::events::{begin_wave_event, end_wave_event, update_arena_event, ArenaEvent};
use crate::sim::hazards::LaserBeam;
use crate::sim::layout::resolve_circle_obstacles;
use crate::sim::level::{
    enemy_stats, maybe_spawn_wave_powerup, spawn_loot_on_enemy_death, spawn_wave_enemies,
};
use crate::sim::locomotion::{self, MoveIntent};
use crate::sim::math::{
    clamp_entity_to_map, dist, dist_sq, mortar_landing_target, point_segment_distance_sq,
    segment_circle_first_hit_t, Vec2,
};
use crate::sim::mutators::{shape_enemy_volley, steer_velocity, tick_shield_regen};
use crate::sim::perception::build_perception;
use crate::sim::player::{perform_dash, recharge_dash, update_boost};
use crate::sim::steer::compute_formation_targets;
use crate::sim::powerup::{
    apply_powerup, enemy_time_scale, equip_permanent_weapon, expire_timed_effects,
    expire_weapon_pickup, is_rare_powerup, pickup_magnet_mods, tick_powerups, timed_active,
    PickupSound,
};
use crate::sim::projectile::{spawn_player_projectiles, Projectile};
use crate::sim::rpg::{
    advance_temp_rewards, apply_perm_reward, apply_temp_reward, has_relic, recompute_temp_mods,
    roll_boss_rewards,
};
use crate::sim::specials::{
    apply_repulsor_shockwave, can_split_crit, chain_arc_damage, find_chain_target,
    spawn_echo_projectile, step_ricochet_bounce, steer_homing_projectiles, EchoRing, RicochetStep,
};
use crate::sim::state::{
    BossRewardOffer, DamageRejection, DamageResult, DamageTarget, PendingPlayerDamage,
    PendingReflect, SimEvent, SimInput, SimState,
};
use crate::sim::weapons::{get_effective_fire_rate, get_weapon_color, roll_wave_clear_upgrade, shot_sfx_for_weapon};
use crate::sim::config::{
    ECHO_COLOR, ECHO_RING_RADIUS, ECHO_RING_SECONDS, MAGNET_RADIUS_NORMAL, MAGNET_RADIUS_SPECIAL,
    PICKUP_PULL_BASE_SPEED, PICKUP_PULL_NEARBY_GAIN, PICKUP_RADIUS_NORMAL, PICKUP_RADIUS_SPECIAL,
    ELITE_MENDER_HEAL, ELITE_MENDER_INTERVAL, ELITE_MENDER_RADIUS,
};

pub const WAVE_COOLDOWN_S: f32 = crate::sim::config::WAVE_COOLDOWN;

fn trigger_dash(state: &mut SimState, input: &SimInput, events: &mut Vec<SimEvent>) {
    if perform_dash(
        &mut state.player,
        state.time,
        state.dash_cd_difficulty,
        state.dash_cd_mult,
        input.move_dir,
        input.aim_world,
    ) {
        state.run_stats.on_dash();
        events.push(SimEvent::Audio {
            clip: "dash",
            volume: 0.7,
            pitch_jitter: 0.05,
            min_gap: 0.0,
        });
        events.push(SimEvent::DashEffect {
            pos: state.player.pos,
            dir: state.player.dash_direction,
            color: state
                .run_skin
                .dash_color()
                .unwrap_or_else(|| state.run_skin.ship_palette().trail),
        });
        events.push(SimEvent::ScreenFlashDash(0.7));
    }
}

fn trigger_phase_shard(state: &mut SimState, events: &mut Vec<SimEvent>) {
    if !has_relic(&state.run_permanent_rewards, "relic_phase_shard") {
        return;
    }

    let origin = state.player.pos;
    let radius = 78.0;
    let radius_sq = radius * radius;
    let hit_ids: Vec<u64> = state
        .enemies
        .iter()
        .filter(|enemy| !enemy.is_dead && enemy.hp > 0 && dist_sq(enemy.pos, origin) <= radius_sq)
        .map(|enemy| enemy.id)
        .collect();
    let damage = (state.effective_player_damage() / 2 + 3).max(5);

    for enemy_id in hit_ids {
        let Some(idx) = state
            .enemies
            .iter()
            .position(|enemy| enemy.id == enemy_id && !enemy.is_dead && enemy.hp > 0)
        else {
            continue;
        };
        let hit_pos = state.enemies[idx].pos;
        damage_enemy_idx(state, idx, damage, false, "phase shard", events);
        events.push(SimEvent::HitParticles {
            pos: hit_pos,
            color: [196, 132, 255],
        });
        if state.enemies.get(idx).is_some_and(|enemy| enemy.hp <= 0) {
            kill_enemy_by_id(state, enemy_id, true, true, events);
        }
    }

    events.push(SimEvent::Shockwave {
        pos: origin,
        color: [184, 112, 255],
        max_radius: radius,
        ttl: 0.30,
    });
}

fn damage_player(
    state: &mut SimState,
    amount: i32,
    source: &'static str,
    grace_seconds: f32,
) {
    state.pending_player_damage.push(PendingPlayerDamage {
        source,
        raw_damage: amount,
        grace_seconds: grace_seconds.max(PLAYER_HIT_GRACE_SECONDS),
    });
}

fn resolve_player_damage(
    state: &mut SimState,
    candidate: PendingPlayerDamage,
    events: &mut Vec<SimEvent>,
) -> DamageResult {
    let mut result = DamageResult {
        source: candidate.source,
        target: DamageTarget::Player,
        raw_damage: candidate.raw_damage,
        adjusted_damage: 0,
        shield_damage: 0,
        health_damage: 0,
        rejected: None,
        killed: false,
    };
    if candidate.raw_damage <= 0 {
        result.rejected = Some(DamageRejection::NonPositive);
        events.push(SimEvent::DamageResolved(result));
        return result;
    }
    if state.player.invincibility_timer > 0.0 {
        result.rejected = Some(DamageRejection::Invulnerable);
        events.push(SimEvent::DamageResolved(result));
        return result;
    }

    let mut amount = candidate.raw_damage;
    if state.player.is_boosting {
        amount = (((amount as f32) * (1.0 - BOOST_DAMAGE_REDUCTION)).round() as i32).max(1);
    }
    let mult = state.incoming_damage_mult * state.temp_mods.incoming_damage;
    if (mult - 1.0).abs() > 1e-6 {
        amount = (((amount as f32) * mult).round() as i32).max(1);
    }
    result.adjusted_damage = amount;

    if state.player.shield > 0 {
        result.shield_damage = state.player.shield.min(amount);
        state.player.shield -= result.shield_damage;
        amount -= result.shield_damage;
        if result.shield_damage > 0 {
            events.push(SimEvent::ShieldHit {
                pos: state.player.pos,
                absorbed: result.shield_damage,
            });
            events.push(SimEvent::Audio {
                clip: "shield_hit",
                volume: 0.6,
                pitch_jitter: 0.05,
                min_gap: 0.05,
            });
        }
    }

    state.player.invincibility_timer = state
        .player
        .invincibility_timer
        .max(candidate.grace_seconds);

    result.health_damage = amount.max(0);
    // Achievement tracking: only health loss counts as a hit. A shield-only block keeps the
    // Untouchable / Flawless streak and is tracked separately.
    if result.health_damage > 0 {
        state.run_stats.on_player_hit(result.health_damage);
    } else if result.shield_damage > 0 {
        state.run_stats.on_shield_block();
    }
    if result.health_damage > 0 {
        state.player.hp -= result.health_damage;
        state.player.damage_flash_timer = 0.12;
        events.push(SimEvent::Audio {
            clip: "hurt",
            volume: 0.9,
            pitch_jitter: 0.04,
            min_gap: 0.08,
        });
        events.push(SimEvent::Popup {
            pos: state.player.pos,
            text: format!("-{}", result.health_damage),
            color: [255, 110, 110],
            big: result.health_damage >= 20,
        });
        if result.health_damage >= 25 {
            state.hitstop = state.hitstop.max(0.05);
        }
        events.push(SimEvent::ScreenFlashHit(
            (0.28 + (result.health_damage as f32) * 0.03).min(1.0),
        ));
        let hp_shake = (SHAKE_PLAYER_HIT_BASE
            + (result.health_damage as f32) * SHAKE_PLAYER_HIT_PER_HP)
            .clamp(SHAKE_PLAYER_HIT_BASE, SHAKE_PLAYER_HIT_MAX);
        state.add_shake(hp_shake, None);
        state.score.on_player_hit();
    }
    result.killed = state.player.hp <= 0;
    events.push(SimEvent::DamageResolved(result));
    result
}

fn resolve_pending_player_damage(state: &mut SimState, events: &mut Vec<SimEvent>) {
    let mut candidates = std::mem::take(&mut state.pending_player_damage);
    candidates.sort_by(|a, b| {
        a.raw_damage
            .cmp(&b.raw_damage)
            .then_with(|| a.grace_seconds.total_cmp(&b.grace_seconds))
            .then_with(|| a.source.cmp(b.source))
    });
    if state.player.invincibility_timer > 0.0 {
        for candidate in candidates {
            resolve_player_damage(state, candidate, events);
        }
    } else if let Some(candidate) = candidates.pop() {
        for superseded in candidates {
            events.push(SimEvent::DamageResolved(DamageResult {
                source: superseded.source,
                target: DamageTarget::Player,
                raw_damage: superseded.raw_damage,
                adjusted_damage: 0,
                shield_damage: 0,
                health_damage: 0,
                rejected: Some(DamageRejection::SupersededByStrongerSameStepHit),
                killed: false,
            }));
        }
        resolve_player_damage(state, candidate, events);
    }
}

fn damage_enemy_idx(
    state: &mut SimState,
    idx: usize,
    mut amount: i32,
    is_crit: bool,
    source: &'static str,
    events: &mut Vec<SimEvent>,
) -> DamageResult {
    if idx >= state.enemies.len() {
        let result = DamageResult {
            source,
            target: DamageTarget::Unknown,
            raw_damage: amount,
            adjusted_damage: 0,
            shield_damage: 0,
            health_damage: 0,
            rejected: Some(DamageRejection::MissingTarget),
            killed: false,
        };
        events.push(SimEvent::DamageResolved(result));
        return result;
    }
    let target_id = state.enemies[idx].id;
    if amount <= 0 {
        let result = DamageResult {
            source,
            target: DamageTarget::Enemy(target_id),
            raw_damage: amount,
            adjusted_damage: 0,
            shield_damage: 0,
            health_damage: 0,
            rejected: Some(DamageRejection::NonPositive),
            killed: state.enemies[idx].hp <= 0,
        };
        events.push(SimEvent::DamageResolved(result));
        return result;
    }
    let pos = state.enemies[idx].pos;
    let raw_damage = amount;
    if state.enemies[idx].behavior == "tank" && state.enemies[idx].ai.push_t > 0.0 {
        amount = ((amount as f32) * 0.65).round().max(1.0) as i32;
        events.push(SimEvent::HitParticles {
            pos,
            color: [255, 185, 90],
        });
    }
    let guarded = !state.enemies[idx].is_boss()
        && state.enemies.iter().any(|ward| {
            ward.id != target_id
                && !ward.is_dead
                && ward.hp > 0
                && ward.is_elite
                && ward.elite_affix == "warden"
                && dist_sq(ward.pos, pos)
                    <= crate::sim::config::ELITE_WARD_RADIUS.powi(2)
        });
    if guarded {
        let protected_amount = ((amount as f32)
            * crate::sim::config::ELITE_WARD_DAMAGE_MULT)
            .round()
            .max(1.0) as i32;
        let absorbed = amount - protected_amount;
        amount = protected_amount;
        if absorbed > 0 {
            events.push(SimEvent::WardAbsorb { pos });
        }
    }
    state.enemies[idx].hit_flash_timer = 0.12;
    events.push(SimEvent::Audio {
        clip: if is_crit { "hit_crit" } else { "hit" },
        volume: 0.5,
        pitch_jitter: 0.06,
        min_gap: 0.02,
    });
    if is_crit {
        events.push(SimEvent::Popup {
            pos,
            text: format!("{amount}!"),
            color: [255, 225, 75],
            big: true,
        });
        events.push(SimEvent::CritSpark(pos));
    } else {
        events.push(SimEvent::Popup {
            pos,
            text: amount.to_string(),
            color: [255, 255, 255],
            big: false,
        });
    }
    let adjusted_damage = amount;
    let shield_damage = if state.enemies[idx].shield > 0 {
        let absorbed = state.enemies[idx].shield.min(amount);
        state.enemies[idx].shield -= absorbed;
        amount -= absorbed;
        if absorbed > 0 {
            events.push(SimEvent::ShieldHit { pos, absorbed });
        }
        absorbed
    } else {
        0
    };
    if amount > 0 {
        state.enemies[idx].hp -= amount;
    }
    let result = DamageResult {
        source,
        target: DamageTarget::Enemy(target_id),
        raw_damage,
        adjusted_damage,
        shield_damage,
        health_damage: amount.max(0),
        rejected: None,
        killed: state.enemies[idx].hp <= 0,
    };
    events.push(SimEvent::DamageResolved(result));
    result
}

/// Earliest contact along this projectile's actual per-step path. A ricochet
/// path contains its incoming leg first and reflected leg second.
fn projectile_circle_impact(
    projectile: &Projectile,
    center: Vec2,
    radius: f32,
) -> Option<(usize, f32, Vec2)> {
    let end = projectile.pos;
    if let Some((start, bounce)) = projectile.pre_bounce_segment {
        if let Some(t) = segment_circle_first_hit_t(start, bounce, center, radius) {
            return Some((0, t, start + (bounce - start) * t));
        }
        let outgoing_start = projectile.prev_pos.unwrap_or(bounce);
        if let Some(t) = segment_circle_first_hit_t(outgoing_start, end, center, radius) {
            return Some((1, t, outgoing_start + (end - outgoing_start) * t));
        }
        None
    } else {
        let start = projectile.prev_pos.unwrap_or(end);
        segment_circle_first_hit_t(start, end, center, radius)
            .map(|t| (0, t, start + (end - start) * t))
    }
}

fn impact_obstacle_idx(
    state: &mut SimState,
    idx: usize,
    damage: i32,
    events: &mut Vec<SimEvent>,
) -> bool {
    if idx >= state.obstacles.len() {
        return false;
    }
    let pos = state.obstacles[idx].pos;
    let mut impact_color = [160, 160, 170];
    let mut breaks_crate = false;
    if state.runtime.enable_destructible_crates && damage > 0 && state.obstacles[idx].hp > 0 {
        let obstacle = &mut state.obstacles[idx];
        obstacle.hp = (obstacle.hp - damage).max(0);
        breaks_crate = obstacle.hp == 0;
        impact_color = if breaks_crate {
            [255, 204, 145]
        } else {
            [205, 168, 126]
        };
    }

    events.push(SimEvent::HitParticles {
        pos,
        color: impact_color,
    });
    if breaks_crate {
        state.obstacles.swap_remove(idx);
        events.push(SimEvent::DeathExplosion {
            pos,
            color: [190, 150, 105],
            behavior: "crate".to_string(),
        });
        events.push(SimEvent::Audio {
            clip: "explode",
            volume: 0.35,
            pitch_jitter: 0.08,
            min_gap: 0.08,
        });
        state.add_shake(2.5, None);
    }
    breaks_crate
}

fn dodge_imminent_meteor_zones(state: &mut SimState, dt: f32) {
    if dt <= 0.0 {
        return;
    }
    let warnings: Vec<(Vec2, f32)> = match state.arena_event.as_ref() {
        Some(ArenaEvent::MeteorShower(shower)) => shower
            .zones
            .iter()
            .filter_map(|zone| {
                let until_impact = zone.delay + EVENT_METEOR_WARN - shower.elapsed;
                (!zone.hit_done && until_impact > 0.0 && until_impact <= EVENT_METEOR_DODGE_WINDOW)
                    .then_some((zone.pos, until_impact))
            })
            .collect(),
        _ => return,
    };
    if warnings.is_empty() {
        return;
    }

    let obstacles = if state.runtime.enable_obstacles {
        state.obstacles.as_slice()
    } else {
        &[]
    };
    for enemy in &mut state.enemies {
        if enemy.is_boss()
            || enemy.is_dead
            || enemy.hp <= 0
            || enemy.is_stunned(state.time)
            || !matches!(
                enemy.behavior.as_str(),
                "ranged" | "sniper" | "spitter" | "flyer" | "engineer" | "bomber"
            )
        {
            continue;
        }

        let mut escape = Vec2::ZERO;
        let mut strongest = 0.0_f32;
        let mut strongest_dir = Vec2::ZERO;
        let mut urgency = 0.0_f32;
        let safe_radius = EVENT_METEOR_RADIUS + enemy.radius + 22.0;
        for &(zone_pos, until_impact) in &warnings {
            let delta = enemy.pos - zone_pos;
            let distance = delta.length();
            if distance >= safe_radius {
                continue;
            }
            let time_pressure =
                (1.0 - until_impact / EVENT_METEOR_DODGE_WINDOW).clamp(0.0, 1.0);
            let proximity = (1.0 - distance / safe_radius).clamp(0.0, 1.0);
            let influence = time_pressure * proximity;
            if influence <= 0.0 {
                continue;
            }
            let direction = if distance > 1.0e-5 {
                delta / distance
            } else {
                let angle = enemy.seed + enemy.id as f32 * 0.618_034;
                Vec2::new(angle.cos(), angle.sin())
            };
            escape += direction * influence;
            if influence > strongest {
                strongest = influence;
                strongest_dir = direction;
            }
            urgency = urgency.max(time_pressure);
        }

        if escape.length_squared() < 1.0e-5 {
            escape = strongest_dir;
        }
        if escape.length_squared() < 1.0e-5 {
            continue;
        }
        let move_dir = steer_clear_of_obstacles(enemy, escape.normalized(), obstacles);
        let speed_factor = 0.35 + 0.35 * urgency;
        enemy.pos += move_dir * (enemy.speed * speed_factor * dt);
        enemy.vel = move_dir * (enemy.speed * speed_factor);
    }
}

fn reflect_back(
    state: &mut SimState,
    enemy_id: u64,
    damage: i32,
    events: &mut Vec<SimEvent>,
) -> bool {
    let Some(idx) = state.enemies.iter().position(|e| e.id == enemy_id) else {
        return false;
    };
    if state.enemies[idx].elite_affix != "reflector"
        || state.enemies[idx].ai.reflect_cd_left > 0.0
    {
        return false;
    }
    state.enemies[idx].ai.reflect_cd_left = ELITE_REFLECT_COOLDOWN;
    let epos = state.enemies[idx].pos;
    let to_player = state.player.pos - epos;
    let dir = if to_player.length_squared() > 1e-12 {
        to_player.normalized()
    } else {
        Vec2::new(1.0, 0.0)
    };
    let reflected_dmg = damage.clamp(6, 18 + state.wave / 2);
    let end = epos + dir * (ELITE_REFLECT_SPEED * 2.0);
    let bid = state.alloc_id();
    state.lasers.push(
        LaserBeam::new(
            epos,
            end,
            0,
            4.5,
            0.0,
            0.16,
            [255, 220, 120],
            TELEGRAPH_OWNER,
        )
        .with_id(bid),
    );
    state.pending_reflects.push(PendingReflect {
        pos: epos,
        dir,
        damage: reflected_dmg,
        delay_left: 0.16,
    });
    events.push(SimEvent::Shockwave {
        pos: epos,
        color: [255, 220, 120],
        max_radius: 34.0,
        ttl: 0.25,
    });
    events.push(SimEvent::AudioCue("reflect"));
    true
}

fn kill_enemy_by_id(
    state: &mut SimState,
    enemy_id: u64,
    death_particles: bool,
    player_chain: bool,
    events: &mut Vec<SimEvent>,
) {
    kill_enemy_inner(state, enemy_id, death_particles, player_chain, true, events);
}

/// Removes an enemy that destroyed itself on the player (contact suicide). Scores as usual,
/// but is not credited to the player's achievement stats (`RunStats`).
fn kill_enemy_uncredited(
    state: &mut SimState,
    enemy_id: u64,
    death_particles: bool,
    player_chain: bool,
    events: &mut Vec<SimEvent>,
) {
    kill_enemy_inner(state, enemy_id, death_particles, player_chain, false, events);
}

fn kill_enemy_inner(
    state: &mut SimState,
    enemy_id: u64,
    death_particles: bool,
    player_chain: bool,
    credit: bool,
    events: &mut Vec<SimEvent>,
) {
    let Some(idx) = state.enemies.iter().position(|e| e.id == enemy_id) else {
        return;
    };
    if state.enemies[idx].is_dead {
        return;
    }
    let e = state.enemies.remove(idx);
    remove_telegraph(&mut state.lasers, e.ai.telegraph_beam_id);

    let behavior = e.behavior.clone();
    if behavior.starts_with("boss_") {
        // A defeated boss ends its own committed hazards immediately. Add and
        // support enemies remain alive and keep their own independent attacks.
        state
            .projectiles
            .retain(|p| !(p.owner == "enemy" && p.source == behavior));
        state.lasers.retain(|hazard| hazard.source != behavior);
        state.traps.retain(|hazard| hazard.source != behavior);
        state.thunders.retain(|hazard| hazard.source != behavior);
    }
    let ecolor = enemy_color(&behavior, false);
    if death_particles {
        events.push(SimEvent::DeathExplosion {
            pos: e.pos,
            color: ecolor,
            behavior: behavior.clone(),
        });
    }

    if behavior.starts_with("boss_") {
        events.push(SimEvent::Audio {
            clip: "boss_die",
            volume: 1.0,
            pitch_jitter: 0.0,
            min_gap: 0.0,
        });
        state.hitstop = state.hitstop.max(0.12);
        events.push(SimEvent::BossDeath(e.pos, ecolor));
        events.push(SimEvent::BossDeathFlash);
        events.push(SimEvent::AudioCue("victory_fanfare"));
        state.fanfare_stamp = Some(state.time);
    } else {
        if e.is_elite || matches!(behavior.as_str(), "tank" | "bomber") {
            events.push(SimEvent::Audio {
                clip: "explode",
                volume: 0.8,
                pitch_jitter: 0.05,
                min_gap: 0.0,
            });
        } else {
            events.push(SimEvent::Audio {
                clip: "kill",
                volume: 0.6,
                pitch_jitter: 0.06,
                min_gap: 0.02,
            });
        }
        if e.is_elite {
            state.hitstop = state.hitstop.max(0.04);
        }
        events.push(SimEvent::KillBurst {
            pos: e.pos,
            color: ecolor,
            big: e.is_elite,
        });
    }

    // Elite volatile blast
    if e.elite_affix == "volatile" {
        events.push(SimEvent::DeathExplosion {
            pos: e.pos,
            color: [255, 100, 30],
            behavior: "bomber".to_string(),
        });
        events.push(SimEvent::Shockwave {
            pos: e.pos,
            color: ELITE_VOLATILE_COLOR,
            max_radius: ELITE_VOLATILE_BLAST_RADIUS,
            ttl: 0.32,
        });
        state.add_shake(14.0, None);
        let neighbor_ids: Vec<u64> = state
            .enemies
            .iter()
            .filter(|o| !o.is_dead && o.hp > 0 && dist(o.pos, e.pos) <= ELITE_VOLATILE_BLAST_RADIUS)
            .map(|o| o.id)
            .collect();
        for oid in neighbor_ids {
            if let Some(oi) = state.enemies.iter().position(|o| o.id == oid) {
                damage_enemy_idx(
                    state,
                    oi,
                    ELITE_VOLATILE_BLAST_DAMAGE,
                    false,
                    "volatile elite blast",
                    events,
                );
                if state.enemies.get(oi).is_some_and(|o| o.hp <= 0) {
                    kill_enemy_by_id(state, oid, true, false, events);
                }
            }
        }
        if dist(state.player.pos, e.pos) <= ELITE_VOLATILE_BLAST_RADIUS {
            damage_player(state, 20, "volatile elite blast", PLAYER_HIT_GRACE_SECONDS);
        }
    }

    // Elite splitter spawns children with no affix
    if e.elite_affix == "splitter" {
        let count = ELITE_SPLIT_COUNT.max(1);
        let child_hp = ((e.max_hp as f32) * ELITE_SPLIT_HP_FRAC).max(1.0) as i32;
        let child_cd = e.attack_cd.max(0.5);
        let child_pad = SimState::enemy_radius_of(&behavior) + 6.0;
        for i in 0..count {
            let ang = TAU * (i as f32) / (count as f32);
            let offset = Vec2::new(ang.cos() * 26.0, ang.sin() * 26.0);
            let pos = clamp_entity_to_map(
                e.pos + offset,
                state.room_radius,
                child_pad,
                &state.map_type,
            );
            let cid = state.alloc_id();
            let mut child = Enemy::new(cid, pos, child_hp, e.speed, &behavior);
            child.max_hp = child_hp;
            child.attack_cd = child_cd;
            child.ai.attack_mult = e.ai.attack_mult;
            assign_run_keys(&mut child, &mut state.enemy_spawn_count);
            state.enemies.push(child);
        }
        events.push(SimEvent::AudioCue("split"));
    }

    if behavior == "tank" {
        tank_death_blast(state, e.pos, &behavior, events);
    }

    let cur_weapon = state.player.current_weapon.clone();
    spawn_loot_on_enemy_death(
        &behavior,
        e.pos,
        state.wave,
        &state.difficulty,
        &state.rules,
        Some(&cur_weapon),
        &mut state.pity,
        &mut state.rng,
        &mut state.powerups,
    );

    let mult = if e.is_elite {
        crate::sim::config::ELITE_SCORE_MULT
    } else {
        1.0
    };
    state.score.on_enemy_kill(&behavior, mult);
    if credit {
        let boss = behavior.starts_with("boss_");
        state.run_stats.on_kill(e.is_elite, boss, state.score.combo);
        if boss {
            state.run_stats.on_boss_kind(&behavior);
        }
    }

    if player_chain && state.chain.is_active(state.time) {
        chain_from(state, e.pos, events);
    }
}

fn chain_from(state: &mut SimState, origin: Vec2, events: &mut Vec<SimEvent>) {
    if state.chain_hops_this_step >= CHAIN_HOPS_PER_STEP_MAX {
        return;
    }
    let candidates: Vec<(usize, Vec2, bool)> = state
        .enemies
        .iter()
        .enumerate()
        .map(|(i, e)| (i, e.pos, !e.is_dead && e.hp > 0))
        .collect();
    if let Some((target_idx, target_pos)) = find_chain_target(origin, &candidates) {
        state.chain_hops_this_step += 1;
        let tid = state.enemies[target_idx].id;
        let arc_dmg = chain_arc_damage(state.effective_player_damage());
        state.chain.spawn_arc(origin, target_pos, state.time);
        events.push(SimEvent::HitParticles {
            pos: target_pos,
            color: CHAIN_ARC_COLOR,
        });
        damage_enemy_idx(state, target_idx, arc_dmg, false, "chain arc", events);
        if state
            .enemies
            .iter()
            .position(|e| e.id == tid)
            .is_some_and(|i| state.enemies[i].hp <= 0)
        {
            kill_enemy_by_id(state, tid, true, false, events);
        }
    }
}

fn tank_death_blast(
    state: &mut SimState,
    epos: Vec2,
    behavior_name: &str,
    events: &mut Vec<SimEvent>,
) {
    if behavior_name != "tank" {
        return;
    }
    events.push(SimEvent::Shockwave {
        pos: epos,
        color: [120, 255, 155],
        max_radius: TANK_DEATH_BLAST_RADIUS,
        ttl: 0.30,
    });
    if dist(epos, state.player.pos) < TANK_DEATH_BLAST_RADIUS {
        damage_player(
            state,
            TANK_DEATH_BLAST_DAMAGE,
            "tank death blast",
            PLAYER_HIT_GRACE_SECONDS,
        );
        state.add_shake(15.0, None);
    }
}

fn explode_player_shell(
    state: &mut SimState,
    p: &Projectile,
    ignore_enemy_id: Option<u64>,
    events: &mut Vec<SimEvent>,
) {
    let radius = match p.projectile_type.as_str() {
        "missile" => crate::sim::config::PLAYER_MISSILE_BLAST_RADIUS,
        "flak" => crate::sim::config::PLAYER_FLAK_BLAST_RADIUS,
        "mortar" => crate::sim::config::PLAYER_MORTAR_BLAST_RADIUS,
        _ => return,
    };
    let targets: Vec<(u64, f32)> = state.enemies.iter()
        .filter(|e| !e.is_dead && e.hp > 0 && Some(e.id) != ignore_enemy_id)
        .filter(|e| !p.hit_ids.contains(&e.id))
        .filter_map(|e| {
            let edge_distance = (dist(e.pos, p.pos) - e.radius).max(0.0);
            (edge_distance <= radius).then_some((e.id, edge_distance))
        })
        .collect();
    for (id, distance) in targets {
        let Some(idx) = state.enemies.iter().position(|e| e.id == id) else { continue };
        let falloff = 1.0 - 0.5 * (distance / radius).clamp(0.0, 1.0);
        let damage = (p.damage as f32 * 0.8 * falloff).round().max(1.0) as i32;
        let source = match p.projectile_type.as_str() {
            "missile" => "heavy cannon blast",
            "mortar" => "siege mortar blast",
            _ => "flak blast",
        };
        damage_enemy_idx(state, idx, damage, p.is_crit, source, events);
        if state.enemies[idx].hp <= 0 {
            let epos = state.enemies[idx].pos;
            if state.runtime.enable_powerup_edges {
                kill_enemy_by_id(state, id, true, true, events);
            } else {
                kill_enemy_by_id(state, id, true, false, events);
                chain_from(state, epos, events);
            }
        }
    }
    let (blast_color, blast_ttl) = if p.projectile_type == "mortar" {
        ([255, 142, 66], crate::sim::config::PLAYER_MORTAR_BLAST_SECONDS)
    } else {
        ([255, 184, 86], 0.32)
    };
    events.push(SimEvent::Shockwave {
        pos: p.pos,
        color: blast_color,
        max_radius: radius,
        ttl: blast_ttl,
    });
    // A cluster is several shells; cap their combined shake instead of adding
    // a full camera kick for each shell and every nearby casualty.
    if p.projectile_type == "mortar" {
        state.add_shake(crate::sim::config::PLAYER_MORTAR_SHAKE, Some(4.5));
    } else {
        state.add_shake(1.2, Some(3.0));
    }
}

fn spawn_cluster_shrapnel(
    state: &mut SimState,
    p: &Projectile,
    ignore_enemy_id: Option<u64>,
    events: &mut Vec<SimEvent>,
) {
    events.push(SimEvent::FlakDetonation(p.pos));
    explode_player_shell(state, p, ignore_enemy_id, events);
    let base_dmg = ((p.damage as f32) * 0.45).round().max(1.0) as i32;
    for base_deg in [0.0_f32, 90.0, 180.0, 270.0] {
        let ang = (base_deg + state.rng.range_f32(-20.0, 20.0)).to_radians();
        let sdir = Vec2::new(ang.cos(), ang.sin());
        let svel = sdir * state.rng.range_f32(340.0, 460.0);
        let spawn_pos = p.pos + sdir * 8.0;
        let ttl = state.rng.range_f32(0.24, 0.40);
        let mut shrap = Projectile::new(spawn_pos, svel, base_dmg, ttl, "player", "bullet");
        shrap.is_crit = p.is_crit;
        shrap.prev_pos = Some(p.pos);
        if let Some(id) = ignore_enemy_id {
            shrap.hit_ids.push(id);
        }
        state.projectiles.push(shrap);
    }
}

/// All player-shell retirement causes route through this single-use detonation
/// handler. Callers remove the projectile first and provide the direct target,
/// if any, so splash never reapplies that impact.
fn resolve_player_projectile_retirement(
    state: &mut SimState,
    projectile: &Projectile,
    direct_target: Option<u64>,
    events: &mut Vec<SimEvent>,
) {
    if projectile.owner != "player" {
        return;
    }
    if projectile.cluster_on_death {
        spawn_cluster_shrapnel(state, projectile, direct_target, events);
    } else if matches!(projectile.projectile_type.as_str(), "missile" | "mortar") {
        explode_player_shell(state, projectile, direct_target, events);
    }
}

fn explode_enemy_bomb(state: &mut SimState, p: &Projectile, events: &mut Vec<SimEvent>) {
    let blast_r = crate::sim::config::BOMB_BLAST_RADIUS;
    let blast_dmg = p.damage.max(crate::sim::config::BOMB_BLAST_MIN_DAMAGE);
    events.push(SimEvent::DeathExplosion {
        pos: p.pos,
        color: [255, 145, 90],
        behavior: "bomber_blast".to_string(),
    });
    if dist_sq(p.pos, state.player.pos) <= blast_r * blast_r {
        damage_player(state, blast_dmg, "enemy bomb", PLAYER_HIT_GRACE_SECONDS);
    }
}

fn trigger_ultra(state: &mut SimState, input: &SimInput, events: &mut Vec<SimEvent>) {
    if state.player.ultra_charges <= 0 || state.time < state.player.ultra_cd_until {
        return;
    }

    let mut aim = (input.aim_world - state.player.pos).normalized();
    if aim.length_squared() <= 1e-12 {
        aim = Vec2::new(1.0, 0.0);
    }
    let muzzle = state.player.pos + aim * 28.0;
    let dmg = ULTRA_DAMAGE_BASE
        + ((state.effective_player_damage() as f32) * ULTRA_DAMAGE_MULT) as i32;
    let beam_thickness = ULTRA_BEAM_THICKNESS;
    let beam_ttl = ULTRA_BEAM_TTL;

    let hit_enemy_ultra =
        |state: &mut SimState, enemy_id: u64, amount: i32, events: &mut Vec<SimEvent>| {
            let Some(idx) = state.enemies.iter().position(|e| e.id == enemy_id) else {
                return;
            };
            if state.runtime.enable_powerup_edges && state.enemies[idx].is_dead {
                return;
            }
            let epos = state.enemies[idx].pos;
            let beh = state.enemies[idx].behavior.clone();
            damage_enemy_idx(state, idx, amount, false, "ultra", events);
            events.push(SimEvent::HitParticles {
                pos: epos,
                color: enemy_color(&beh, false),
            });
            if state
                .enemies
                .iter()
                .position(|e| e.id == enemy_id)
                .is_some_and(|i| state.enemies[i].hp <= 0)
            {
                let chains = state.runtime.enable_powerup_edges;
                kill_enemy_by_id(state, enemy_id, true, chains, events);
                state.run_stats.on_ultra_kill();
            }
        };

    let spawn_player_beam = |state: &mut SimState,
                             start: Vec2,
                             dir: Vec2,
                             length: f32,
                             damage: i32,
                             thickness: f32,
                             color: [u8; 3],
                             events: &mut Vec<SimEvent>| {
        let end = start + dir * length;
        let bid = state.alloc_id();
        state.lasers.push(
            LaserBeam::new(start, end, damage, thickness, beam_ttl, 0.0, color, "player")
                .with_id(bid),
        );
        events.push(SimEvent::LaserBeamFx { start, end, color });
        let half_t = thickness * 0.5;
        let hit_ids: Vec<u64> = state
            .enemies
            .iter()
            .filter(|e| !e.is_dead && e.hp > 0)
            .filter(|e| {
                let r = half_t + SimState::enemy_radius_of(&e.behavior);
                point_segment_distance_sq(e.pos, start, end) <= r * r
            })
            .map(|e| e.id)
            .collect();
        for eid in hit_ids {
            hit_enemy_ultra(state, eid, damage, events);
        }
    };

    let variant = state.player.ultra_variant_idx % 3;
    state.player.ultra_variant_idx = (variant + 1) % 3;
    let mut flash_r = 120.0;
    let rr = state.room_radius;

    if variant == 0 {
        spawn_player_beam(
            state,
            muzzle,
            aim,
            rr * 2.05,
            dmg,
            beam_thickness,
            ULTRA_BEAM_COLOR,
            events,
        );
        state.add_shake(12.0, None);
    } else if variant == 1 {
        for deg in [-16.0_f32, 0.0, 16.0] {
            let d = aim.rotated_deg(deg);
            spawn_player_beam(
                state,
                muzzle,
                d,
                rr * 1.9,
                ((dmg as f32) * 0.88) as i32,
                beam_thickness * 0.8,
                [255, 180, 180],
                events,
            );
        }
        state.add_shake(14.0, None);
    } else {
        let blast_r = ULTRA_BLAST_RADIUS;
        flash_r = blast_r;
        let blast_dmg = ((dmg as f32) * 0.70) as i32;
        let hit_ids: Vec<u64> = state
            .enemies
            .iter()
            .filter(|e| !e.is_dead && e.hp > 0 && dist(e.pos, state.player.pos) <= blast_r)
            .map(|e| e.id)
            .collect();
        for eid in hit_ids {
            hit_enemy_ultra(state, eid, blast_dmg, events);
        }
        events.push(SimEvent::Shockwave {
            pos: state.player.pos,
            color: [255, 220, 180],
            max_radius: blast_r,
            ttl: 0.35,
        });
        events.push(SimEvent::PickupCollection {
            pos: state.player.pos,
            color: [255, 220, 180],
        });
        spawn_player_beam(
            state,
            muzzle,
            aim,
            rr * 1.55,
            ((dmg as f32) * 0.48) as i32,
            beam_thickness * 0.7,
            [255, 210, 120],
            events,
        );
        state.add_shake(16.0, None);
    }

    if has_relic(&state.run_permanent_rewards, "relic_aegis_relay") {
        let restored = (crate::sim::config::SHIELD_MAX - state.player.shield)
            .clamp(0, 14);
        if restored > 0 {
            state.player.shield += restored;
            events.push(SimEvent::Popup {
                pos: state.player.pos,
                text: format!("+{restored} SHIELD"),
                color: [115, 235, 250],
                big: false,
            });
            events.push(SimEvent::PickupCollection {
                pos: state.player.pos,
                color: [115, 235, 250],
            });
        }
    }

    let flash_color = match variant {
        0 => ULTRA_BEAM_COLOR,
        1 => [255, 180, 180],
        _ => [255, 220, 180],
    };
    events.push(SimEvent::UltraFlash {
        pos: state.player.pos,
        color: flash_color,
        radius: flash_r,
    });
    events.push(SimEvent::Audio {
        clip: "ultra_fire",
        volume: 0.9,
        pitch_jitter: 0.0,
        min_gap: 0.0,
    });
    state.hitstop = state.hitstop.max(0.06);
    state.player.ultra_charges = (state.player.ultra_charges - 1).max(0);
    state.run_stats.on_ultra_use();
    state.player.ultra_cd_duration = (ULTRA_COOLDOWN * state.temp_mods.ultra_cd).max(0.1);
    state.player.ultra_cd_until = state.time + state.player.ultra_cd_duration;
    events.push(SimEvent::ScreenFlashUltra(1.0));
}

fn trigger_repulsor_shockwave(state: &mut SimState, events: &mut Vec<SimEvent>) {
    state.repulsor.spawn_ring(state.player.pos, state.time);
    let mut enemy_stuns: Vec<(Vec2, &mut f32)> = state
        .enemies
        .iter_mut()
        .filter(|e| !e.is_dead && e.hp > 0)
        .map(|e| (e.pos, &mut e.stun_until))
        .collect();
    let rep_stats = apply_repulsor_shockwave(
        state.player.pos,
        &mut state.projectiles,
        &mut enemy_stuns,
    );
    let r2 = crate::sim::config::REPULSOR_RANGE * crate::sim::config::REPULSOR_RANGE;
    let lasers = &mut state.lasers;
    for e in &mut state.enemies {
        if !e.is_dead && e.hp > 0 && (e.pos - state.player.pos).length_squared() <= r2 {
            e.stun_until = e
                .stun_until
                .max(state.time + crate::sim::config::REPULSOR_STUN_SECONDS);
            cancel_attack_for_interrupt(e, lasers, 0.65);
        }
    }
    events.push(SimEvent::RepulsorBlast {
        pos: state.player.pos,
        stunned_positions: rep_stats.stunned_positions,
    });
}

pub fn apply_boss_temp_reward(state: &mut SimState, key: &str, duration: i32) -> Vec<SimEvent> {
    let mut events = Vec::new();
    let k = key.trim().to_ascii_lowercase();
    if !apply_temp_reward(&mut state.active_temp_rewards, &k, duration) {
        return events;
    }
    state.last_reward_temp_key = k.clone();
    if k == "temp_ultra_flux" {
        state.player.ultra_charges = (state.player.ultra_charges + 1).min(state.player.ultra_max_charges);
    }
    state.temp_mods = recompute_temp_mods(&state.active_temp_rewards);
    events.push(SimEvent::Audio {
        clip: "pickup_rare",
        volume: 0.8,
        pitch_jitter: 0.0,
        min_gap: 0.0,
    });
    events.push(SimEvent::PickupCollection {
        pos: state.player.pos,
        color: [255, 235, 170],
    });
    state.add_shake(5.0, None);
    events
}

pub fn apply_boss_perm_reward(state: &mut SimState, key: &str) -> Vec<SimEvent> {
    let mut events = Vec::new();
    let k = key.trim().to_ascii_lowercase();
    let applied = apply_perm_reward(
        &mut state.player,
        &mut state.run_permanent_rewards,
        &k,
        &mut state.dash_cd_mult,
    );
    if applied {
        state.last_reward_perm_key = k;
        state.pending_boss_reward = None;
        events.push(SimEvent::Audio {
            clip: "pickup_rare",
            volume: 0.8,
            pitch_jitter: 0.0,
            min_gap: 0.0,
        });
        events.push(SimEvent::PickupCollection {
            pos: state.player.pos,
            color: [200, 235, 255],
        });
        state.add_shake(6.0, None);
    }
    events
}

fn tick_elite_menders(
    state: &mut SimState,
    enemy_dt: f32,
    visual_dt: f32,
    events: &mut Vec<SimEvent>,
) {
    let mut pulses = Vec::new();
    for enemy in &mut state.enemies {
        enemy.ai.mender_pulse = (enemy.ai.mender_pulse - visual_dt * 2.0).max(0.0);
        if enemy.is_dead || enemy.hp <= 0 || !enemy.is_elite || enemy.elite_affix != "mender" {
            continue;
        }
        if enemy.is_stunned(state.time) {
            continue;
        }
        enemy.ai.mender_cd = (enemy.ai.mender_cd - enemy_dt).max(0.0);
        if enemy.ai.mender_cd <= 0.0 {
            enemy.ai.mender_cd = ELITE_MENDER_INTERVAL;
            pulses.push((enemy.id, enemy.pos));
        }
    }

    for (mender_id, mender_pos) in pulses {
        let mut candidates: Vec<(f32, f32, u64)> = state
            .enemies
            .iter()
            .filter(|ally| {
                ally.id != mender_id
                    && !ally.is_dead
                    && ally.hp > 0
                    && !ally.is_boss()
                    && ally.hp < ally.max_hp
                    && dist_sq(ally.pos, mender_pos) <= ELITE_MENDER_RADIUS * ELITE_MENDER_RADIUS
                    && (!state.runtime.enable_obstacles
                        || state.obstacles.iter().all(|obstacle| {
                            point_segment_distance_sq(obstacle.pos, mender_pos, ally.pos)
                                > obstacle.radius * obstacle.radius
                        }))
            })
            .map(|ally| {
                (
                    ally.hp as f32 / ally.max_hp.max(1) as f32,
                    dist_sq(ally.pos, mender_pos),
                    ally.id,
                )
            })
            .collect();
        candidates.sort_by(|a, b| {
            a.0.total_cmp(&b.0)
                .then_with(|| a.1.total_cmp(&b.1))
                .then_with(|| a.2.cmp(&b.2))
        });

        let mut healed_any = false;
        for &(_, _, target_id) in candidates.iter().take(2) {
            if let Some(target) = state.enemies.iter_mut().find(|enemy| enemy.id == target_id) {
                let heal_amt =
                    ELITE_MENDER_HEAL + (target.max_hp as f32 * 0.12).round() as i32;
                let prev_hp = target.hp;
                target.hp = (target.hp + heal_amt).min(target.max_hp);
                let healed = target.hp - prev_hp;
                if healed > 0 {
                    healed_any = true;
                    events.push(SimEvent::HitParticles {
                        pos: target.pos,
                        color: ELITE_MENDER_COLOR,
                    });
                    events.push(SimEvent::Popup {
                        pos: target.pos,
                        text: format!("+{healed}"),
                        color: ELITE_MENDER_COLOR,
                        big: false,
                    });
                    events.push(SimEvent::TetherBeam {
                        from: mender_pos,
                        to: target.pos,
                        color: ELITE_MENDER_COLOR,
                    });
                }
            }
        }
        if healed_any {
            if let Some(mender) = state.enemies.iter_mut().find(|enemy| enemy.id == mender_id) {
                mender.ai.mender_pulse = 0.8;
            }
        }
    }
}

fn tick_engineer_support(
    state: &mut SimState,
    enemy_dt: f32,
    visual_dt: f32,
    events: &mut Vec<SimEvent>,
) {
    const ENGINEER_SUPPORT_RADIUS: f32 = 165.0;
    const ENGINEER_SUPPORT_INTERVAL: f32 = 3.6;
    const ENGINEER_SUPPORT_COLOR: [u8; 3] = [95, 245, 195];

    let mut pulses = Vec::new();
    for enemy in &mut state.enemies {
        enemy.ai.support_pulse = (enemy.ai.support_pulse - visual_dt * 2.0).max(0.0);
        if enemy.is_dead || enemy.hp <= 0 || enemy.behavior != "engineer" {
            continue;
        }
        if enemy.is_stunned(state.time) {
            continue;
        }
        enemy.ai.support_cd = (enemy.ai.support_cd - enemy_dt).max(0.0);
        if enemy.ai.support_cd <= 0.0 {
            enemy.ai.support_cd = ENGINEER_SUPPORT_INTERVAL;
            pulses.push((enemy.id, enemy.pos));
        }
    }

    for (eng_id, eng_pos) in pulses {
        let target_id = state
            .enemies
            .iter()
            .filter(|ally| {
                if ally.id == eng_id || ally.is_dead || ally.hp <= 0 || ally.is_boss() {
                    return false;
                }
                if dist_sq(ally.pos, eng_pos) > ENGINEER_SUPPORT_RADIUS * ENGINEER_SUPPORT_RADIUS {
                    return false;
                }
                let cap = (ally.max_hp as f32 * 0.25).round().max(8.0) as i32;
                ally.shield < cap
            })
            .min_by(|a, b| {
                a.shield
                    .cmp(&b.shield)
                    .then_with(|| dist_sq(a.pos, eng_pos).total_cmp(&dist_sq(b.pos, eng_pos)))
                    .then_with(|| a.id.cmp(&b.id))
            })
            .map(|ally| ally.id);

        let Some(target_id) = target_id else {
            continue;
        };
        if let Some(target) = state.enemies.iter_mut().find(|enemy| enemy.id == target_id) {
            let cap = (target.max_hp as f32 * 0.25).round().max(8.0) as i32;
            let gain = (cap - target.shield).min(8);
            if gain > 0 {
                target.shield += gain;
                events.push(SimEvent::TetherBeam {
                    from: eng_pos,
                    to: target.pos,
                    color: ENGINEER_SUPPORT_COLOR,
                });
                events.push(SimEvent::Popup {
                    pos: target.pos,
                    text: format!("+{gain} SHIELD"),
                    color: ENGINEER_SUPPORT_COLOR,
                    big: false,
                });
                if let Some(eng) = state.enemies.iter_mut().find(|enemy| enemy.id == eng_id) {
                    eng.ai.support_pulse = 0.8;
                }
            }
        }
    }
}

pub fn step(state: &mut SimState, input: &SimInput, raw_dt: f32) -> Vec<SimEvent> {
    let mut events = Vec::with_capacity(16);
    if state.game_over || state.pending_boss_reward.is_some() {
        return events;
    }

    let dt = raw_dt.clamp(0.0, 1.0 / 30.0);
    if state.hitstop > 0.0 {
        state.hitstop = (state.hitstop - dt).max(0.0);
        return events;
    }
    state.pending_player_damage.clear();
    state.chain_hops_this_step = 0;

    state.time += dt;
    tick_powerups(&mut state.powerups, dt);
    if state.player.invincibility_timer > 0.0 {
        state.player.invincibility_timer = (state.player.invincibility_timer - dt).max(0.0);
    }

    expire_timed_effects(&mut state.player, state.time);
    expire_weapon_pickup(&mut state.player, state.time);

    let slow_on = timed_active(state.player.time_slow_until, state.time);
    if state.time_slow_was_on && !slow_on {
        events.push(SimEvent::AudioCue("time_slow_off"));
    }
    state.time_slow_was_on = slow_on;
    let enemy_dt = dt * enemy_time_scale(&state.player, state.time);
    state.enemy_time += enemy_dt;
    for enemy in &mut state.enemies {
        enemy.ai.reflect_cd_left = (enemy.ai.reflect_cd_left - enemy_dt).max(0.0);
    }

    if input.dash_pressed {
        trigger_dash(state, input, &mut events);
    }
    if input.ultra_pressed {
        trigger_ultra(state, input, &mut events);
    }

    let boost_requested =
        input.boost_held && (input.move_dir.length_squared() > 0.0 || state.player.is_dashing);
    let has_inf_boost = state.has_infinite_boost();
    let is_boosting = update_boost(
        &mut state.player,
        dt,
        boost_requested,
        state.time,
        has_inf_boost,
    );

    if state.player.damage_flash_timer > 0.0 {
        state.player.damage_flash_timer = (state.player.damage_flash_timer - dt).max(0.0);
    }
    for e in &mut state.enemies {
        if e.hit_flash_timer > 0.0 {
            e.hit_flash_timer = (e.hit_flash_timer - dt).max(0.0);
        }
        if e.is_elite {
            events.push(SimEvent::EliteAura {
                pos: e.pos,
                color: elite_affix_color(&e.elite_affix),
            });
        }
    }

    // Spawn next wave when cooldown elapsed
    if !state.wave_active && (state.time - state.last_wave_clear) >= WAVE_COOLDOWN_S {
        state.wave_active = true;
        let spawned = spawn_wave_enemies(
            state.wave,
            &state.difficulty,
            &state.map_type,
            state.room_radius,
            state.max_enemies,
            &state.rules,
            state.player.pos,
            &mut state.next_entity_id,
            &mut state.rng,
        );
        state.enemy_combo_value = spawned.combo_value;
        state.enemy_combo_text = spawned.combo_text;
        let intro_hint = spawned.intro_hint;
        for mut e in spawned.enemies {
            assign_run_keys(&mut e, &mut state.enemy_spawn_count);
            state.enemies.push(e);
        }

        let is_boss_wave = state.enemies.iter().any(|e| e.is_boss());
        state.arena_event = begin_wave_event(
            state.wave,
            is_boss_wave,
            state.room_radius,
            &state.map_type,
            &mut state.rng,
        );

        if let Some(ev) = &state.arena_event {
            events.push(SimEvent::AudioCue("event_warn"));
            if matches!(ev, ArenaEvent::NebulaCloud(_)) {
                events.push(SimEvent::AudioCue("nebula_hum"));
            }
        }

        if let Some(boss) = state.enemies.iter().find(|e| e.is_boss()) {
            let btitle = boss_title(&boss.behavior);
            events.push(SimEvent::Audio {
                clip: "boss_warn",
                volume: 0.9,
                pitch_jitter: 0.0,
                min_gap: 0.0,
            });
            events.push(SimEvent::Banner {
                title: "BOSS INCOMING".to_string(),
                subtitle: btitle,
                color: [255, 120, 120],
                duration: 2.6,
            });
        } else {
            let suffix = state
                .arena_event
                .as_ref()
                .map(|ev| format!("  -  {}", ev.display_name().to_ascii_uppercase()))
                .unwrap_or_default();
            let subtitle = if let Some(intro) = intro_hint {
                format!("NEW THREAT: {intro}  -  {} hostiles{suffix}", state.enemies.len())
            } else {
                format!(
                    "{}  -  {} hostiles{}",
                    state.difficulty.to_ascii_uppercase(),
                    state.enemies.len(),
                    suffix
                )
            };
            events.push(SimEvent::Banner {
                title: format!("WAVE {:02}", state.wave),
                subtitle,
                color: [200, 230, 255],
                duration: 2.0,
            });
        }
    }

    let mut hit_shake = 0.0_f32;

    // Vortex aura DPS
    if state.time < state.player.vortex_until {
        let vr = state.player.vortex_radius;
        events.push(SimEvent::VortexSwirl {
            pos: state.player.pos,
            time: state.time,
            radius: vr,
        });
        let vr2 = vr * vr;
        let dps = state.player.vortex_dps;
        let ppos = state.player.pos;
        let mut kills = Vec::new();
        for i in 0..state.enemies.len() {
            if state.enemies[i].is_dead || state.enemies[i].hp <= 0 {
                continue;
            }
            if dist_sq(state.enemies[i].pos, ppos) <= vr2 {
                state.enemies[i].vortex_acc += dps * dt;
                let dmg = state.enemies[i].vortex_acc as i32;
                state.enemies[i].vortex_acc -= dmg as f32;
                if dmg > 0 {
                    let eid = state.enemies[i].id;
                    damage_enemy_idx(state, i, dmg, false, "vortex", &mut events);
                    hit_shake += SHAKE_HIT_IMPULSE;
                    if state.enemies[i].hp <= 0 {
                        kills.push(eid);
                    }
                }
            }
        }
        let chains = state.runtime.enable_powerup_edges;
        for eid in kills {
            kill_enemy_by_id(state, eid, false, chains, &mut events);
        }
    }

    // Traps
    let player_radius = state.player_radius();
    let mut ti = 0;
    while ti < state.traps.len() {
        state.traps[ti].t += enemy_dt;
        state.traps[ti].ttl -= enemy_dt;
        if state.traps[ti].ttl <= 0.0 {
            state.traps.swap_remove(ti);
            continue;
        }
        if state.traps[ti].kind == "meteor"
            && state.traps[ti].t >= state.traps[ti].armed_delay
            && !state.traps[ti].landed
        {
            state.traps[ti].landed = true;
            events.push(SimEvent::AudioCue("meteor_impact"));
        }
        if state.traps[ti].damage > 0 && state.traps[ti].t >= state.traps[ti].armed_delay {
            let hit_r = state.traps[ti].radius + player_radius;
            if dist_sq(state.traps[ti].pos, state.player.pos) <= hit_r * hit_r {
                let dmg = state.traps[ti].damage;
                state.traps.swap_remove(ti);
                damage_player(state, dmg, "floor trap", PLAYER_HIT_GRACE_SECONDS);
                continue;
            }
        }
        ti += 1;
    }

    // Thunder lines
    let mut thi = 0;
    while thi < state.thunders.len() {
        let th = &mut state.thunders[thi];
        th.t += enemy_dt;
        if th.t >= th.warn && !th.hit_done {
            let hit_r = th.thickness * 0.6 + player_radius * 0.35;
            if point_segment_distance_sq(state.player.pos, th.start, th.end) <= hit_r * hit_r {
                th.hit_done = true;
                let dmg = th.damage;
                let start = th.start;
                let end = th.end;
                let color = th.color;
                damage_player(state, dmg, "thunder line", PLAYER_HIT_GRACE_SECONDS);
                events.push(SimEvent::LaserBeamFx { start, end, color });
            }
        }
        if state.thunders[thi].t >= state.thunders[thi].warn + state.thunders[thi].ttl {
            state.thunders.swap_remove(thi);
        } else {
            thi += 1;
        }
    }

    // Arena events
    if let Some(mut ev) = state.arena_event.take() {
        let mut enemy_shields: Vec<(u64, Vec2, &mut i32)> = state
            .enemies
            .iter_mut()
            .filter(|e| !e.is_dead && e.hp > 0)
            .map(|e| (e.id, e.pos, &mut e.shield))
            .collect();
        let outcome = update_arena_event(&mut ev, dt, state.player.pos, &mut enemy_shields);
        drop(enemy_shields);
        if outcome.flare_sweep_started {
            events.push(SimEvent::AudioCue("flare_sweep"));
        }
        for impact_pos in outcome.meteor_impacts {
            events.push(SimEvent::AudioCue("meteor_impact"));
            events.push(SimEvent::Shockwave {
                pos: impact_pos,
                color: [255, 165, 95],
                max_radius: crate::sim::config::EVENT_METEOR_RADIUS * 1.4,
                ttl: 0.3,
            });
        }
        for (enemy_id, damage) in outcome.enemy_hits {
            let Some(idx) = state.enemies.iter().position(|enemy| enemy.id == enemy_id) else {
                continue;
            };
            let pos = state.enemies[idx].pos;
            damage_enemy_idx(state, idx, damage, false, "arena event", &mut events);
            events.push(SimEvent::HitParticles {
                pos,
                color: [255, 165, 95],
            });
            if state.enemies.get(idx).is_some_and(|enemy| enemy.hp <= 0) {
                kill_enemy_by_id(state, enemy_id, true, false, &mut events);
            }
        }
        if outcome.damage_player_amount > 0 {
            damage_player(
                state,
                outcome.damage_player_amount,
                "arena event",
                PLAYER_HIT_GRACE_SECONDS,
            );
        }
        if ev.active() {
            state.arena_event = Some(ev);
        }
    }

    // Player movement (dash vs drift/direct steering)
    let old_pos = state.player.pos;
    let mut dash_ended = false;
    if state.player.is_dashing {
        state.player.pos += state.player.dash_direction * (state.player.dash_speed * dt);
        state.player.dash_timer -= dt;
        if state.player.dash_timer <= 0.0 {
            state.player.is_dashing = false;
            dash_ended = true;
        }
    } else {
        let moving = input.move_dir.length_squared() > 1e-12;
        let desired_vel = if moving {
            let nd = input.move_dir.normalized();
            let mut spd = state.effective_player_speed();
            if is_boosting {
                spd *= BOOST_SPEED_MULT;
                events.push(SimEvent::BoostFlame {
                    pos: state.player.pos,
                    dir: nd,
                });
                events.push(SimEvent::ScreenFlashBoost(0.18));
            }
            events.push(SimEvent::StepDust {
                pos: state.player.pos,
                dir: nd,
            });
            nd * spd
        } else {
            Vec2::ZERO
        };
        let next_vel = steer_velocity(state.player.move_vel, desired_vel, dt, &state.rules);
        state.player.move_vel = next_vel;
        state.player.pos += next_vel * dt;
    }

    recharge_dash(
        &mut state.player,
        state.time,
        state.dash_cd_difficulty,
        state.dash_cd_mult,
    );
    state.shield_regen_carry = tick_shield_regen(
        &mut state.player.shield,
        state.shield_regen_carry,
        dt,
        &state.rules,
        crate::sim::config::SHIELD_MAX,
    );

    let p_pad = player_radius * 2.0 + 4.0;
    state.player.pos = clamp_entity_to_map(state.player.pos, state.room_radius, p_pad, &state.map_type);
    if state.runtime.enable_obstacles && !state.obstacles.is_empty() {
        state.player.pos =
            resolve_circle_obstacles(state.player.pos, player_radius, &state.obstacles, 2);
        state.player.pos = clamp_entity_to_map(state.player.pos, state.room_radius, p_pad, &state.map_type);
    }

    if dash_ended && state.runtime.enable_echo {
        let echo_p = spawn_echo_projectile(
            state.player.pos,
            state.player.dash_direction,
            state.effective_player_damage(),
        );
        state.projectiles.push(echo_p);
        state.echo_rings.push(EchoRing {
            pos: state.player.pos,
            started_at: state.time,
            ttl: ECHO_RING_SECONDS,
        });
        events.push(SimEvent::Shockwave {
            pos: state.player.pos,
            color: ECHO_COLOR,
            max_radius: ECHO_RING_RADIUS,
            ttl: ECHO_RING_SECONDS,
        });
    }
    if dash_ended {
        trigger_phase_shard(state, &mut events);
    }
    state
        .echo_rings
        .retain(|ring| state.time - ring.started_at < ring.ttl);

    let player_vel = if dt > 1e-6 {
        (state.player.pos - old_pos) * (1.0 / dt)
    } else {
        Vec2::ZERO
    };
    let mut mem = state.perception_mem;
    let perception = build_perception(state, &mut mem, input, player_vel, dash_ended, enemy_dt);
    state.perception_mem = mem;

    if state.runtime.enable_afterburn {
        if state.player.is_dashing {
            state.afterburn.maybe_drop(state.player.pos, state.time);
        }
        state.afterburn.prune(state.time);
    }

    // Weapon shooting
    let weapon = state.player.current_weapon.clone();
    if state.player.recoil > 0.0 {
        state.player.recoil = (state.player.recoil - weapon.recoil_recover * dt).max(0.0);
    }
    if (state.auto_shoot || input.fire_held) && state.time >= state.player.next_shot_time {
        let laser_active = state.time < state.player.laser_until;
        let mut weapon_cd = if laser_active {
            crate::sim::config::LASER_FIRE_INTERVAL
        } else {
            get_effective_fire_rate(&weapon, state.effective_player_fire_rate())
        };
        if !laser_active && weapon.cadence_jitter > 0.0 {
            let j = state.rng.range_f32(
                1.0 - weapon.cadence_jitter, 1.0 + weapon.cadence_jitter,
            );
            weapon_cd *= j;
        }
        if !laser_active {
            weapon_cd = weapon_cd.max(crate::sim::weapons::weapon_min_cooldown(&weapon));
        }
        let mut aim = (input.aim_world - state.player.pos).normalized();
        if aim.length_squared() <= 1e-12 {
            aim = Vec2::new(1.0, 0.0);
        }
        let muzzle = state.player.pos + aim * 40.0;
        if laser_active {
            let beam_len = state.room_radius * 1.6;
            let end = muzzle + aim * beam_len;
            let dmg = ((state.effective_player_damage() as f32) * 0.9) as i32 + 14;
            let bid = state.alloc_id();
            let beam = LaserBeam::new(muzzle, end, dmg, 20.0, 0.08, 0.0, [255, 255, 160], "player")
                .with_id(bid);
            events.push(SimEvent::LaserBeamFx {
                start: muzzle,
                end,
                color: beam.color,
            });
            state.lasers.push(beam);
            events.push(SimEvent::Audio {
                clip: "laser_charge",
                volume: 0.4,
                pitch_jitter: 0.0,
                min_gap: 0.1,
            });
            let hit_ids: Vec<u64> = state
                .enemies
                .iter()
                .filter(|e| !e.is_dead && e.hp > 0)
                .filter(|e| {
                    let r = 10.0 + SimState::enemy_radius_of(&e.behavior);
                    point_segment_distance_sq(e.pos, muzzle, end) <= r * r
                })
                .map(|e| e.id)
                .collect();
            let chains = state.runtime.enable_powerup_edges;
            for eid in hit_ids {
                if let Some(idx) = state.enemies.iter().position(|e| e.id == eid) {
                    damage_enemy_idx(state, idx, dmg, false, "ultra beam", &mut events);
                    hit_shake += SHAKE_HIT_IMPULSE;
                    if state.enemies[idx].hp <= 0 {
                        kill_enemy_by_id(state, eid, false, chains, &mut events);
                    }
                }
            }
        } else {
            state.player.recoil = (state.player.recoil + weapon.recoil_kick).min(weapon.recoil_max);
            let crit_cb = state.effective_crit_chance();
            let crit_mb = state.effective_crit_mult();
            let eff_dmg = state.effective_player_damage();
            let mut shots = spawn_player_projectiles(
                muzzle,
                aim,
                &weapon,
                eff_dmg,
                1.0,
                state.player.recoil,
                crit_cb,
                crit_mb,
                &mut state.rng,
            );
            if weapon.projectile_type == "mortar" {
                let landing = mortar_landing_target(
                    state.player.pos,
                    input.aim_world,
                    aim,
                    state.room_radius,
                    &state.map_type,
                );
                let landing_delta = landing - muzzle;
                let flight_dir = if landing_delta.length_squared() > 1e-8 {
                    landing_delta.normalized()
                } else {
                    aim
                };
                let speed = weapon.projectile_speed.max(1.0);
                let flight_time = landing_delta.length() / speed;
                for shot in &mut shots {
                    if shot.projectile_type == "mortar" {
                        shot.vel = flight_dir * speed;
                        shot.ttl = flight_time;
                        shot.flight_duration = flight_time;
                    }
                }
            }
            state.projectiles.extend(shots);
            events.push(SimEvent::Audio {
                clip: shot_sfx_for_weapon(&weapon.name),
                volume: 0.45,
                pitch_jitter: 0.04,
                min_gap: 0.03,
            });
        }
        events.push(SimEvent::MuzzleFlash { pos: muzzle, dir: aim });
        state.player.last_shot = state.time;
        state.player.next_shot_time = state.time + weapon_cd;
    }

    // Drone companion
    let enemy_alive_snaps: Vec<(Vec2, bool)> = state
        .enemies
        .iter()
        .map(|e| (e.pos, !e.is_dead && e.hp > 0))
        .collect();
    let eff_dmg = state.effective_player_damage();
    let crit_cb = state.effective_crit_chance();
    let crit_mb = state.effective_crit_mult();
    if let Some(shot) = update_drone(
        &mut state.drone,
        state.player.pos,
        eff_dmg,
        1.0,
        crit_cb,
        crit_mb,
        state.player.drone_until,
        state.time,
        dt,
        &enemy_alive_snaps,
        &mut state.rng,
    ) {
        state.projectiles.extend(shot.projectiles);
        events.push(SimEvent::MuzzleFlash {
            pos: shot.muzzle,
            dir: shot.aim,
        });
        events.push(SimEvent::AudioCue("drone_fire"));
    }

    // Repulsor tick
    if state.repulsor.poll_ready(state.time) {
        trigger_repulsor_shockwave(state, &mut events);
    }
    state.repulsor.prune(state.time);

    // Update enemies individually, then batch-steer formation in parallel
    for enemy in state.enemies.iter_mut().filter(|e| !e.is_dead && e.hp > 0) {
        assign_run_keys(enemy, &mut state.enemy_spawn_count);
    }
    let live_snap: Vec<(u64, Vec2, Vec2, bool)> = state
        .enemies
        .iter()
        .filter(|e| !e.is_dead && e.hp > 0)
        .map(|e| (e.id, e.pos, e.vel, e.behavior == "swarm"))
        .collect();
    let swarm_snaps: Vec<(u64, Vec2, Vec2, usize)> = state
        .enemies
        .iter()
        .filter(|e| !e.is_dead && e.hp > 0 && e.behavior == "swarm")
        .map(|e| {
            (
                e.id,
                e.pos,
                e.vel,
                swarm_formation_key(e).0,
            )
        })
        .collect();
    let spawn_snaps: Vec<(u64, Vec2, f32)> = state
        .enemies
        .iter()
        .filter(|e| !e.is_dead && e.hp > 0)
        .map(|e| (e.id, e.pos, e.radius))
        .collect();
    let total_live_enemies = live_snap.len();
    let non_boss_count = state
        .enemies
        .iter()
        .filter(|e| !e.is_dead && e.hp > 0 && !e.is_boss())
        .count();
    let boss_present = state
        .enemies
        .iter()
        .any(|e| !e.is_dead && e.hp > 0 && e.is_boss());
    let non_boss_spawn_cap = state
        .max_enemies
        .saturating_add(if boss_present { 4 } else { 0 });
    let reserved_boss_spawn_slots: usize = state
        .enemies
        .iter()
        .filter(|e| {
            !e.is_dead
                && e.hp > 0
                && e.is_boss()
                && matches!(
                    e.ai.sub_state,
                    EnemySubState::QueenBroodTelegraph | EnemySubState::QueenSwarmTelegraph
                )
        })
        .map(|e| e.ai.summon_target_count as usize)
        .sum();
    let regular_non_boss_spawn_cap =
        non_boss_spawn_cap.saturating_sub(reserved_boss_spawn_slots);
    let egg_sac_count = state
        .enemies
        .iter()
        .filter(|e| !e.is_dead && e.hp > 0 && e.behavior == "egg_sac")
        .count();

    let skill = ai_skill(&state.difficulty, state.wave);
    let mut queued_spawns = Vec::new();
    let mut attack_scheduler = AttackScheduler::for_enemies(&state.enemies);
    let mut director = AttackDirector::new(
        &state.enemies,
        perception.breathing_room_left,
        skill.coordination,
    );
    let enemy_count = state.enemies.len();
    let mut intents: Vec<Option<MoveIntent>> = vec![None; enemy_count];
    for idx in 0..enemy_count {
        if state.enemies[idx].is_dead || state.enemies[idx].hp <= 0 {
            continue;
        }
        if state.enemies[idx].is_stunned(state.time) {
            continue;
        }
        state.enemies[idx].prev_pos = state.enemies[idx].pos;
        state.enemies[idx].t += enemy_dt;
        if state.enemies[idx].seed == 0.0 {
            state.enemies[idx].seed = state.rng.range_f32(0.0, TAU);
        }
        assign_run_keys(&mut state.enemies[idx], &mut state.enemy_spawn_count);

        let shots_before = state.projectiles.len();
        let is_boss = state.enemies[idx].is_boss();

        let mut bctx = BehaviorContext {
            player_pos: perception.player_pos,
            player_vel: perception.smoothed_vel,
            dt: enemy_dt,
            enemy_time: state.enemy_time,
            wave: state.wave,
            room_radius: state.room_radius,
            map_type: &state.map_type,
            next_id: &mut state.next_entity_id,
            rng: &mut state.rng,
            enemy_snaps: &live_snap,
            swarm_snaps: &swarm_snaps,
            spawn_snaps: &spawn_snaps,
            live_non_boss_count: non_boss_count,
            non_boss_spawn_cap: if is_boss {
                non_boss_spawn_cap
            } else {
                regular_non_boss_spawn_cap
            },
            obstacles: if state.runtime.enable_obstacles {
                &state.obstacles
            } else {
                &[]
            },
            projectiles: &mut state.projectiles,
            traps: &mut state.traps,
            lasers: &mut state.lasers,
            swarm_brain: &mut state.swarm_brain,
            queued_spawns: &mut queued_spawns,
            attack_scheduler: &mut attack_scheduler,
        };

        if is_boss {
            let prev_sub_state = state.enemies[idx].ai.sub_state;
            let from_pos = state.enemies[idx].pos;
            let boss_transition = update_boss_enemy(
                &mut state.enemies[idx],
                &mut bctx,
                &state.difficulty,
                state.max_enemies,
                total_live_enemies,
                non_boss_count,
                egg_sac_count,
                &mut state.thunders,
            );
            if prev_sub_state == EnemySubState::ThunderTeleportOut
                && state.enemies[idx].ai.sub_state == EnemySubState::ThunderTeleportIn
            {
                events.push(SimEvent::BossTeleport {
                    from: from_pos,
                    to: state.enemies[idx].pos,
                    color: enemy_color(
                        &state.enemies[idx].behavior,
                        state.runtime.colorblind_palette,
                    ),
                });
            }
            let phase_after = boss_transition.phase;
            if boss_transition.phase_changed && boss_transition.rage_banner.is_none() {
                let behavior = state.enemies[idx].behavior.clone();
                let phase_title = match phase_after {
                    1 => "PHASE II",
                    _ => "PHASE III",
                };
                events.push(SimEvent::Banner {
                    title: phase_title.to_string(),
                    subtitle: format!("{}  -  ATTACK PATTERN SHIFT", boss_title(&behavior)),
                    color: enemy_color(&behavior, state.runtime.colorblind_palette),
                    duration: 1.8,
                });
                events.push(SimEvent::Audio {
                    clip: "boss_warn",
                    volume: 0.62,
                    pitch_jitter: 0.02,
                    min_gap: 0.6,
                });
            }
            if let Some(banner) = boss_transition.rage_banner {
                // Rage starts at 35% HP and phase III at 33%. A hit can cross
                // both thresholds in one frame, so carry the pattern shift on
                // the rage banner instead of silently dropping that cue.
                let subtitle = if boss_transition.phase_changed {
                    let phase_label = if phase_after >= 2 { "PHASE III" } else { "PHASE II" };
                    format!(
                        "{}  -  {} PATTERN  -  ATTACKS QUICKEN",
                        boss_title(&state.enemies[idx].behavior),
                        phase_label
                    )
                } else {
                    banner.subtitle
                };
                events.push(SimEvent::Banner {
                    title: banner.title.to_string(),
                    subtitle,
                    color: banner.color,
                    duration: crate::sim::config::RAGE_BANNER_DURATION,
                });
                events.push(SimEvent::AudioCue("rage_warn"));
            }
        } else {
            let intent = update_regular_behavior(
                idx,
                &mut state.enemies[idx],
                &mut bctx,
                &perception,
                &skill,
                &mut director,
            );
            intents[idx] = Some(intent);
        }

        if state.projectiles.len() > shots_before {
            shape_enemy_volley(&mut state.projectiles, shots_before, &state.rules);
        }
    }

    director.resolve(
        &mut state.enemies,
        &mut state.director,
        state.enemy_time,
        enemy_dt,
        perception.breathing_room_left,
        skill.coordination,
    );
    commit_granted_attacks(
        &mut state.enemies,
        &mut intents,
        &mut state.lasers,
        &mut state.next_entity_id,
        &mut state.rng,
        &perception,
        &skill,
        state.wave,
        state.room_radius,
        &state.map_type,
    );

    let boss_present = state
        .enemies
        .iter()
        .any(|e| !e.is_dead && e.hp > 0 && e.is_boss());
    let spawn_cap = state
        .max_enemies
        .saturating_add(if boss_present { 4 } else { 0 });
    let mut live_non_boss = state
        .enemies
        .iter()
        .filter(|e| !e.is_dead && e.hp > 0 && !e.is_boss())
        .count();
    for mut child in queued_spawns {
        if !child.is_boss() && live_non_boss >= spawn_cap {
            continue;
        }
        if child.behavior == "swarm" && !child.is_boss() {
            let (hp, speed, atk_mult) =
                enemy_stats("swarm", state.wave, &state.difficulty);
            child.hp = hp;
            child.max_hp = hp;
            child.speed = speed * state.rules.enemy_speed_mult;
            child.ai.attack_mult = atk_mult;
        } else {
            if child.behavior == "egg_sac" {
                child.ai.max_hatch_timer = child.ai.hatch_timer.max(0.1);
            }
            child.speed *= state.rules.enemy_speed_mult;
        }
        child.pos = clamp_entity_to_map(child.pos, state.room_radius, child.radius + 6.0, &state.map_type);
        assign_run_keys(&mut child, &mut state.enemy_spawn_count);
        if !child.is_boss() {
            live_non_boss += 1;
        }
        state.enemies.push(child);
    }
    intents.resize(state.enemies.len(), None);

    // Formation v2 + unified single-integrator locomotion pass
    let form_targets = compute_formation_targets(
        &mut state.enemies,
        &mut state.enemy_spawn_count,
        &mut state.formation,
        &state.difficulty,
        &perception,
        &skill,
        state.room_radius,
        &state.map_type,
        enemy_dt,
    );
    locomotion::integrate_batch(
        &mut state.enemies,
        &intents,
        &form_targets,
        &skill,
        state.room_radius,
        &state.map_type,
        enemy_dt,
        state.time,
    );
    dodge_imminent_meteor_zones(state, enemy_dt);
    locomotion::resolve_enemy_body_overlaps(
        &mut state.enemies,
        state.room_radius,
        &state.map_type,
        state.time,
        enemy_dt,
    );

    // Clamp enemies + obstacle resolve + player-enemy contact checks
    let p_pad = player_radius * 2.0 + 4.0;
    let live_ids: Vec<u64> = state
        .enemies
        .iter()
        .filter(|e| !e.is_dead && e.hp > 0)
        .map(|e| e.id)
        .collect();
    for eid in live_ids {
        let Some(idx) = state.enemies.iter().position(|e| e.id == eid) else {
            continue;
        };
        let rad = state.enemies[idx].radius;
        let enemy_pad = rad + 6.0;
        state.enemies[idx].pos = clamp_entity_to_map(
            state.enemies[idx].pos,
            state.room_radius,
            enemy_pad,
            &state.map_type,
        );
        if state.runtime.enable_obstacles && !state.obstacles.is_empty() {
            state.enemies[idx].pos = resolve_circle_obstacles(
                state.enemies[idx].pos,
                rad,
                &state.obstacles,
                2,
            );
            state.enemies[idx].pos = clamp_entity_to_map(
                state.enemies[idx].pos,
                state.room_radius,
                enemy_pad,
                &state.map_type,
            );
        }

        let epos = state.enemies[idx].pos;
        let hit_r = rad + player_radius;
        let d2 = dist_sq(epos, state.player.pos);
        if d2 <= hit_r * hit_r {
            let is_boss = state.enemies[idx].is_boss();
            let stunned = state.enemies[idx].is_stunned(state.time);
            if state.player.is_boosting {
                let ram_ready = state.time >= state.enemies[idx].ai.boost_ram_ready_at;
                if ram_ready {
                    state.enemies[idx].ai.boost_ram_ready_at =
                        state.time + BOOST_RAM_COOLDOWN_SECONDS;
                    damage_enemy_idx(state, idx, BOOST_RAM_DAMAGE, true, "boost ram", &mut events);
                    state.add_shake(8.0, Some(8.0));
                    let diff = state.enemies[idx].pos - state.player.pos;
                    let cur_d = d2.sqrt();
                    let push_dir = if cur_d > 1e-4 {
                        diff / cur_d
                    } else if input.move_dir.length_squared() > 1e-9 {
                        input.move_dir.normalized()
                    } else {
                        Vec2::new(1.0, 0.0)
                    };
                    if is_boss {
                        state.enemies[idx].pos = clamp_entity_to_map(
                            state.enemies[idx].pos + push_dir * 20.0,
                            state.room_radius,
                            enemy_pad,
                            &state.map_type,
                        );
                        state.player.pos = clamp_entity_to_map(
                            state.player.pos - push_dir * 36.0,
                            state.room_radius,
                            p_pad,
                            &state.map_type,
                        );
                        state.perception_mem.player_knocked_back = true;
                    } else {
                        let push_dist = ((hit_r - cur_d) + 24.0).max(45.0);
                        state.enemies[idx].pos = clamp_entity_to_map(
                            state.enemies[idx].pos + push_dir * push_dist,
                            state.room_radius,
                            enemy_pad,
                            &state.map_type,
                        );
                    }
                    if state.enemies[idx].hp <= 0 {
                        let chains = state.runtime.enable_powerup_edges;
                        kill_enemy_by_id(state, eid, true, chains, &mut events);
                    }
                }
                if is_boss {
                    damage_player(state, ENEMY_CONTACT_DAMAGE, "boss contact", 0.6);
                } else if !stunned {
                    let cdmg = ((ENEMY_CONTACT_DAMAGE as f32) * 0.4).round() as i32;
                    damage_player(state, cdmg, "boost ram contact", 0.25);
                }
            } else if is_boss {
                damage_player(state, ENEMY_CONTACT_DAMAGE, "boss contact", 0.6);
                let cur_d = d2.sqrt();
                let push_dir = if cur_d > 1e-4 {
                    (state.player.pos - epos) / cur_d
                } else {
                    Vec2::new(1.0, 0.0)
                };
                state.player.pos = clamp_entity_to_map(
                    state.player.pos + push_dir * 40.0,
                    state.room_radius,
                    p_pad,
                    &state.map_type,
                );
                state.perception_mem.player_knocked_back = true;
            } else if stunned {
                // Stunned non-boss enemies do not damage on passive contact
            } else {
                damage_player(
                    state,
                    ENEMY_CONTACT_DAMAGE,
                    "enemy contact",
                    PLAYER_HIT_GRACE_SECONDS,
                );
                kill_enemy_uncredited(state, eid, false, false, &mut events);
            }
        }
    }

    // Afterburn tick
    if state.runtime.enable_afterburn && !state.afterburn.segments.is_empty() {
        let ab_enemies: Vec<(u64, Vec2, bool)> = state
            .enemies
            .iter()
            .filter(|e| !e.is_dead && e.hp > 0)
            .map(|e| (e.id, e.pos, e.is_boss()))
            .collect();
        let hits = state.afterburn.collect_hits(state.time, &ab_enemies);
        let hit_ids: Vec<(u64, i32)> = hits
            .into_iter()
            .map(|(i, dmg)| (ab_enemies[i].0, dmg))
            .collect();
        for (eid, dmg) in hit_ids {
            if let Some(idx) = state.enemies.iter().position(|e| e.id == eid) {
                damage_enemy_idx(state, idx, dmg, false, "afterburn", &mut events);
                if state.enemies[idx].hp <= 0 {
                    kill_enemy_by_id(state, eid, true, false, &mut events);
                }
            }
        }
    }

    // Pending reflector bounce releases (ticked on enemy_dt after 0.16s telegraph)
    let mut ri = 0;
    while ri < state.pending_reflects.len() {
        state.pending_reflects[ri].delay_left -= enemy_dt;
        if state.pending_reflects[ri].delay_left <= 0.0 {
            let pr = state.pending_reflects.swap_remove(ri);
            state.projectiles.push(
                Projectile::new(
                    pr.pos,
                    pr.dir * ELITE_REFLECT_SPEED,
                    pr.damage,
                    2.0,
                    "enemy",
                    "bullet",
                )
                .with_source("reflector"),
            );
        } else {
            ri += 1;
        }
    }

    // Projectiles steering, motion, ricochet, obstacle & expiry
    let homing_targets: Vec<(u64, Vec2)> = state
        .enemies
        .iter()
        .filter(|e| !e.is_dead && e.hp > 0)
        .map(|e| (e.id, e.pos))
        .collect();
    let player_homing_active = timed_active(state.player.homing_until, state.time);
    let new_locks = steer_homing_projectiles(
        &mut state.projectiles,
        &homing_targets,
        dt,
        player_homing_active,
    );
    for _ in 0..new_locks {
        events.push(SimEvent::AudioCue("homing_lock"));
    }

    let player_ricochet_active = timed_active(state.player.ricochet_until, state.time);
    let mut pi = 0;
    while pi < state.projectiles.len() {
        let is_player_p = state.projectiles[pi].owner == "player";
        let step_dt = if is_player_p { dt } else { enemy_dt };
        state.projectiles[pi].step(step_dt);

        if is_player_p {
            let can_ricochet = player_ricochet_active
                && state.projectiles[pi].projectile_type != "mortar";
            match step_ricochet_bounce(
                &mut state.projectiles[pi],
                can_ricochet,
                state.room_radius,
                &state.map_type,
            ) {
                RicochetStep::Bounced(bpos) => {
                    events.push(SimEvent::HitParticles {
                        pos: bpos,
                        color: powerup_color("ricochet"),
                    });
                    events.push(SimEvent::AudioCue("ricochet"));
                }
                RicochetStep::Spent(_) => {}
                RicochetStep::None => {}
            }
        }

        if state.runtime.enable_obstacles && !state.obstacles.is_empty() {
            let p = &state.projectiles[pi];
            let pr = SimState::projectile_radius_of(&p.projectile_type);
            let hit_obs = state
                .obstacles
                .iter()
                .enumerate()
                .filter_map(|(idx, ob)| {
                    projectile_circle_impact(p, ob.pos, ob.radius + pr)
                        .map(|(path_order, hit_t, impact)| (path_order, hit_t, idx, impact))
                })
                .min_by(|a, b| {
                    a.0.cmp(&b.0)
                        .then_with(|| a.1.total_cmp(&b.1))
                        .then_with(|| a.2.cmp(&b.2))
                });
            if let Some((_, _, obstacle_idx, impact)) = hit_obs {
                let mut removed = state.projectiles.swap_remove(pi);
                removed.pos = impact;
                let obstacle_damage = if removed.owner == "player" {
                    removed.damage.max(1)
                } else {
                    0
                };
                impact_obstacle_idx(state, obstacle_idx, obstacle_damage, &mut events);
                if removed.owner == "enemy" && removed.projectile_type == "bomb" {
                    explode_enemy_bomb(state, &removed, &mut events);
                } else {
                    resolve_player_projectile_retirement(state, &removed, None, &mut events);
                }
                continue;
            }
        }

        pi += 1;
    }

    // Critical hit shards step
    if state.runtime.enable_shards && !state.shards.shards.is_empty() {
        let shard_targets: Vec<(u64, Vec2, f32)> = state
            .enemies
            .iter()
            .filter(|e| !e.is_dead && e.hp > 0)
            .map(|e| (e.id, e.pos, e.radius))
            .collect();
        let shard_hits = state.shards.step(dt, &shard_targets);
        for (target_snap_idx, amount, _) in shard_hits {
            let tid = shard_targets[target_snap_idx].0;
            if let Some(ei) = state.enemies.iter().position(|e| e.id == tid) {
                damage_enemy_idx(state, ei, amount, false, "critical shard", &mut events);
                if state
                    .enemies
                    .iter()
                    .position(|e| e.id == tid)
                    .is_some_and(|i| state.enemies[i].hp <= 0)
                {
                    kill_enemy_by_id(state, tid, true, false, &mut events);
                }
            }
        }
    }

    // Projectile vs Enemy / Player swept-segment hits
    let mut i = 0;
    while i < state.projectiles.len() {
        let p_owner = state.projectiles[i].owner.clone();
        let pr = SimState::projectile_radius_of(&state.projectiles[i].projectile_type);

        if p_owner == "player" {
            let mut candidates: Vec<(usize, f32, u64, Vec2)> = state
                .enemies
                .iter()
                .filter(|e| !e.is_dead && e.hp > 0 && !state.projectiles[i].hit_ids.contains(&e.id))
                .filter_map(|e| {
                    projectile_circle_impact(&state.projectiles[i], e.pos, e.radius + pr)
                        .map(|(path_order, hit_t, impact)| (path_order, hit_t, e.id, impact))
                })
                .collect();
            candidates.sort_by(|a, b| {
                a.0.cmp(&b.0)
                    .then_with(|| a.1.total_cmp(&b.1))
                    .then_with(|| a.2.cmp(&b.2))
            });

            let mut candidate_idx = 0;
            let mut projectile_retired = false;
            while candidate_idx < candidates.len() {
                let (_, _, eid, impact) = candidates[candidate_idx];
                candidate_idx += 1;
                let Some(ei) = state.enemies.iter().position(|e| {
                    e.id == eid && !e.is_dead && e.hp > 0
                }) else {
                    continue;
                };
                state.projectiles[i].hit_ids.push(eid);
                let pdmg = state.projectiles[i].damage;
                let pcrit = state.projectiles[i].is_crit;
                if reflect_back(state, eid, pdmg, &mut events) {
                    let mut removed = state.projectiles.swap_remove(i);
                    removed.pos = impact;
                    resolve_player_projectile_retirement(
                        state,
                        &removed,
                        Some(eid),
                        &mut events,
                    );
                    projectile_retired = true;
                    break;
                }

                let epos = state.enemies[ei].pos;
                let beh = state.enemies[ei].behavior.clone();
                let ecolor = enemy_color(&beh, false);

                let source = if state.projectiles[i].weapon_name.is_empty() {
                    "player projectile"
                } else if state.projectiles[i].projectile_type == "missile" {
                    "heavy cannon direct hit"
                } else if state.projectiles[i].projectile_type == "mortar" {
                    "siege mortar direct hit"
                } else if state.projectiles[i].projectile_type == "flak" {
                    "flak shell direct hit"
                } else {
                    "player weapon projectile"
                };
                damage_enemy_idx(state, ei, pdmg, pcrit, source, &mut events);
                hit_shake += if pcrit {
                    SHAKE_CRIT_IMPULSE
                } else {
                    SHAKE_HIT_IMPULSE * ((pdmg as f32) / 10.0).clamp(0.5, 1.5)
                };
                events.push(SimEvent::HitParticles { pos: epos, color: ecolor });

                if state.runtime.enable_shards && can_split_crit(&state.projectiles[i]) {
                    let shard_col = state
                        .run_skin
                        .shot_palette()
                        .map(|p| p.bullet)
                        .unwrap_or_else(|| get_weapon_color(&state.projectiles[i].projectile_type));
                    state.shards.spawn_crit_shards(
                        impact,
                        state.projectiles[i].vel,
                        pdmg,
                        eid,
                        shard_col,
                    );
                }

                if state.enemies.get(ei).is_some_and(|enemy| enemy.hp <= 0) {
                    state.projectiles[i].owner = "__active_player__".to_string();
                    if state.runtime.enable_powerup_edges {
                        kill_enemy_by_id(state, eid, true, true, &mut events);
                    } else {
                        kill_enemy_by_id(state, eid, true, false, &mut events);
                        chain_from(state, epos, &mut events);
                    }
                    if let Some(new_i) = state
                        .projectiles
                        .iter()
                        .position(|p| p.owner == "__active_player__")
                    {
                        i = new_i;
                        state.projectiles[i].owner = "player".to_string();
                    } else {
                        projectile_retired = true;
                        break;
                    }
                }

                if state.projectiles[i].pierce_left > 0 {
                    state.projectiles[i].pierce_left -= 1;
                    continue;
                }

                let mut removed = state.projectiles.swap_remove(i);
                removed.pos = impact;
                resolve_player_projectile_retirement(
                    state,
                    &removed,
                    Some(eid),
                    &mut events,
                );
                projectile_retired = true;
                break;
            }
            if !projectile_retired {
                let retire_at = state.projectiles[i]
                    .boundary_spent
                    .or_else(|| state.projectiles[i].ttl_expired.then_some(state.projectiles[i].pos));
                if let Some(impact) = retire_at {
                    let mut removed = state.projectiles.swap_remove(i);
                    removed.pos = impact;
                    resolve_player_projectile_retirement(state, &removed, None, &mut events);
                    continue;
                }
                i += 1;
            }
            continue;
        } else {
            let ppos = state.player.pos;
            let hit_r = pr + player_radius;
            if state.projectiles[i].projectile_type != "bomb" {
                if let Some((_, _, impact)) =
                    projectile_circle_impact(&state.projectiles[i], ppos, hit_r)
                {
                    let mut removed = state.projectiles.swap_remove(i);
                    removed.pos = impact;
                    damage_player(
                        state,
                        removed.damage,
                        "enemy projectile",
                        PLAYER_HIT_GRACE_SECONDS,
                    );
                    continue;
                }
            }
            if state.projectiles[i].ttl_expired {
                let removed = state.projectiles.swap_remove(i);
                if removed.projectile_type == "bomb" {
                    explode_enemy_bomb(state, &removed, &mut events);
                }
                continue;
            }
        }
        i += 1;
    }

    // Damage before this point resolves before a same-tick healing pickup, as
    // it did in the original combat order. Late beam hits resolve at step end.
    resolve_pending_player_damage(state, &mut events);

    // Powerups magnet pull & collection
    let (mag_r_mult, mag_pull_mult) = pickup_magnet_mods(&state.player, state.time);
    let relic_magnet_bonus = if has_relic(&state.run_permanent_rewards, "relic_graviton") {
        72.0
    } else {
        0.0
    };
    let mag_bonus = state.temp_mods.magnet + relic_magnet_bonus;
    let mut pui = 0;
    while pui < state.powerups.len() {
        let kind = state.powerups[pui].kind.clone();
        let is_special = matches!(kind.as_str(), "weapon" | "ultra");
        let base_mag = if is_special {
            MAGNET_RADIUS_SPECIAL
        } else {
            MAGNET_RADIUS_NORMAL
        };
        let mag_r = (base_mag + mag_bonus) * mag_r_mult;
        let mut d2 = dist_sq(state.powerups[pui].pos, state.player.pos);
        if d2 > 1e-12 && d2 < mag_r * mag_r {
            let d = d2.sqrt();
            let pull = (state.player.pos - state.powerups[pui].pos) / d;
            let pull_spd = (PICKUP_PULL_BASE_SPEED
                + (mag_r - d) * PICKUP_PULL_NEARBY_GAIN)
                * mag_pull_mult;
            state.powerups[pui].pos += pull * (pull_spd * dt);
            d2 = dist_sq(state.powerups[pui].pos, state.player.pos);
        }

        let pick_r = if is_special {
            PICKUP_RADIUS_SPECIAL
        } else {
            PICKUP_RADIUS_NORMAL
        };
        if d2 < pick_r * pick_r {
            let pu = state.powerups.swap_remove(pui);
            let col = powerup_color(&pu.kind);
            events.push(SimEvent::PickupCollection {
                pos: pu.pos,
                color: col,
            });
            let rare = is_rare_powerup(&pu.kind);
            let outcome = apply_powerup(
                &mut state.player,
                &pu,
                state.time,
                state.wave,
                &mut state.chain,
                &mut state.repulsor,
                &mut state.rng,
            );
            state.run_stats.on_pickup();
            events.push(SimEvent::Audio {
                clip: match outcome.sound {
                    PickupSound::Rare => "pickup_rare",
                    PickupSound::Normal => "pickup",
                },
                volume: if rare { 0.85 } else { 0.7 },
                pitch_jitter: 0.04,
                min_gap: 0.0,
            });
            if outcome.repulsor_fired {
                trigger_repulsor_shockwave(state, &mut events);
            }
            if pu.kind == "drone" {
                events.push(SimEvent::AudioCue("drone_spawn"));
            }
            if let Some(cue) = outcome.extra_cue {
                events.push(SimEvent::AudioCue(cue));
            }
            if rare {
                events.push(SimEvent::PickupRing {
                    pos: pu.pos,
                    color: col,
                });
            }
            if let Some(text) = outcome.popup_text {
                events.push(SimEvent::Popup {
                    pos: pu.pos,
                    text,
                    color: col,
                    big: rare,
                });
            }
            continue;
        }
        pui += 1;
    }

    // Remove non-killed dead enemies (hatched egg sacs)
    let mut ei = 0;
    while ei < state.enemies.len() {
        if state.enemies[ei].hp <= 0 && !state.enemies[ei].is_dead {
            let e = state.enemies.swap_remove(ei);
            remove_telegraph(&mut state.lasers, e.ai.telegraph_beam_id);
            events.push(SimEvent::DeathExplosion {
                pos: e.pos,
                color: enemy_color(&e.behavior, false),
                behavior: e.behavior,
            });
        } else {
            ei += 1;
        }
    }

    tick_elite_menders(state, enemy_dt, dt, &mut events);
    tick_engineer_support(state, enemy_dt, dt, &mut events);

    // Wave clear check. Achievement credit (RunStats wave/arena) is deferred to the end of the
    // step, so a wave cleared on the same step the player dies does not count.
    let mut wave_cleared_this_step = false;
    if state.wave_active && state.enemies.is_empty() {
        wave_cleared_this_step = true;
        let cleared_wave = state.wave;
        state.wave_active = false;
        if let Some(mut ev) = state.arena_event.take() {
            end_wave_event(&mut ev, &mut []);
        }
        state.last_wave_clear = state.time;
        state.wave += 1;
        advance_temp_rewards(&mut state.active_temp_rewards);
        state.temp_mods = recompute_temp_mods(&state.active_temp_rewards);
        if !state.game_over && has_relic(&state.run_permanent_rewards, "relic_soul_rivet") {
            let recovered = (state.player.max_hp - state.player.hp).clamp(0, 4);
            state.player.hp += recovered;
            if recovered > 0 {
                events.push(SimEvent::Popup {
                    pos: state.player.pos,
                    text: format!("+{recovered} HULL"),
                    color: [128, 255, 188],
                    big: false,
                });
                events.push(SimEvent::HitParticles {
                    pos: state.player.pos,
                    color: [128, 255, 188],
                });
            }
        }

        if state.fanfare_stamp != Some(state.time) {
            events.push(SimEvent::Audio {
                clip: "wave_clear",
                volume: 0.8,
                pitch_jitter: 0.0,
                min_gap: FANFARE_MIN_GAP,
            });
        }
        if cleared_wave % BOSS_WAVE_EVERY != 0 {
            events.push(SimEvent::Banner {
                title: format!("WAVE {cleared_wave:02} CLEARED"),
                subtitle: "Next wave incoming".to_string(),
                color: [120, 240, 170],
                duration: 2.0,
            });
        }
        let new_segment = (state.wave - 1) / 5;
        if new_segment != state.layout_segment {
            state.layout_segment = new_segment;
        }
        if let Some(upgrade) = roll_wave_clear_upgrade(
            Some(&state.player.current_weapon),
            state.wave,
            &mut state.rng,
            0.5,
        ) {
            equip_permanent_weapon(&mut state.player, upgrade);
        }
        maybe_spawn_wave_powerup(
            state.wave,
            &state.difficulty,
            state.room_radius,
            &state.map_type,
            &state.rules,
            &mut state.pity,
            &mut state.rng,
            &mut state.powerups,
        );

        state.score.on_wave_clear(cleared_wave);
        events.push(SimEvent::WaveCleared(cleared_wave));

        if cleared_wave % BOSS_WAVE_EVERY == 0 {
            let (temp_options, perm_options) = roll_boss_rewards(
                &state.active_temp_rewards,
                &state.last_reward_temp_key,
                &state.last_reward_perm_key,
                &state.player,
                state.dash_cd_mult,
                &state.run_permanent_rewards,
                &mut state.rng,
            );
            state.pending_boss_reward = Some(BossRewardOffer {
                temp_options,
                perm_options,
            });
            events.push(SimEvent::Audio {
                clip: "reward_open",
                volume: 0.8,
                pitch_jitter: 0.0,
                min_gap: 0.0,
            });
            events.push(SimEvent::BossRewardOpened);
        }
    }

    if hit_shake > 0.0 {
        state.add_shake(hit_shake.min(SHAKE_HIT_FRAME_MAX), Some(SHAKE_HIT_CEILING));
    }
    if state.shake > 0.0 {
        state.shake = (state.shake - dt * SHAKE_DECAY).max(0.0);
    }

    state.score.update(dt);
    state.chain.prune(state.time);

    // LaserBeams tick
    let mut li = 0;
    while li < state.lasers.len() {
        let ldt = if state.lasers[li].owner == "enemy" || state.lasers[li].owner == "telegraph" {
            enemy_dt
        } else {
            dt
        };
        state.lasers[li].t += ldt;
        if state.lasers[li].owner == "enemy"
            && state.lasers[li].t >= state.lasers[li].warn
            && !state.lasers[li].hit_done
        {
            let hit_r = state.lasers[li].thickness * 0.55 + player_radius * 0.35;
            if point_segment_distance_sq(
                state.player.pos,
                state.lasers[li].start,
                state.lasers[li].end,
            ) <= hit_r * hit_r
            {
                state.lasers[li].hit_done = true;
                let dmg = state.lasers[li].damage;
                let s = state.lasers[li].start;
                let e = state.lasers[li].end;
                let c = state.lasers[li].color;
                damage_player(state, dmg, "enemy laser", PLAYER_HIT_GRACE_SECONDS);
                events.push(SimEvent::LaserBeamFx {
                    start: s,
                    end: e,
                    color: c,
                });
            }
        }
        if state.lasers[li].t >= state.lasers[li].warn + state.lasers[li].ttl {
            state.lasers.swap_remove(li);
        } else {
            li += 1;
        }
    }

    resolve_pending_player_damage(state, &mut events);

    if wave_cleared_this_step && state.player.hp > 0 {
        state.run_stats.on_wave_clear();
        state.run_stats.on_arena_clear(&state.map_type);
    }

    if state.player.hp <= 0 {
        // The run ends here: a boss reward offered on the same step is withdrawn so the
        // player is not asked to pick a reward while dead.
        state.pending_boss_reward = None;
        // Record the final run numbers inside the sim so the replay hash (which includes
        // RunStats) matches what replay_and_verify reproduces. `finish` is idempotent.
        let best_combo = state.score.best_combo;
        let (score, wave, survived_s) = (state.score.score, state.wave, state.time);
        state
            .run_stats
            .finish(score, wave, survived_s, Some(best_combo));
        state.game_over = true;
        events.push(SimEvent::GameOver);
    }

    events
}
