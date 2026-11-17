use std::f32::consts::TAU;

use crate::sim::config::{
    DIAMOND_EXTENT_RATIO, EVENT_FLARE_DAMAGE, EVENT_FLARE_SECTOR_DEG, EVENT_FLARE_SWEEP,
    EVENT_FLARE_THICKNESS, EVENT_FLARE_TICK, EVENT_FLARE_WARN, EVENT_METEOR_DAMAGE,
    EVENT_METEOR_IMPACTS, EVENT_METEOR_LIVE, EVENT_METEOR_MIN_GAP, EVENT_METEOR_RADIUS,
    EVENT_METEOR_STAGGER,
    EVENT_METEOR_WARN, EVENT_MIN_WAVE, EVENT_NEBULA_RADIUS, EVENT_NEBULA_SHIELD,
    EVENT_NEBULA_TTL, EVENT_NEBULA_WARN, EVENT_WAVE_CHANCE,
};
use crate::sim::math::{clamp_entity_to_map, point_segment_distance_sq, Vec2};
use crate::sim::rng::SimRng;

#[derive(Debug, Clone)]
pub struct MeteorZone {
    pub pos: Vec2,
    pub delay: f32,
    pub elapsed: f32,
    pub hit_done: bool,
    pub live_left: f32,
}

#[derive(Debug, Clone)]
pub struct MeteorShower {
    pub wave: i32,
    pub elapsed: f32,
    pub zones: Vec<MeteorZone>,
}

#[derive(Debug, Clone)]
pub struct SolarFlare {
    pub wave: i32,
    pub elapsed: f32,
    pub start_angle: f32,
    pub sweep_dir: f32,
    pub sector_rad: f32,
    pub beam_length: f32,
    pub last_hit_elapsed: f32,
    pub enemy_hit_elapsed: Vec<(u64, f32)>,
    pub sweep_sfx_played: bool,
}

#[derive(Debug, Clone)]
pub struct NebulaCloud {
    pub wave: i32,
    pub elapsed: f32,
    pub pos: Vec2,
    pub radius: f32,
    pub active: bool,
    pub shielded_ids: Vec<(u64, i32)>,
}

#[derive(Debug, Clone)]
pub enum ArenaEvent {
    MeteorShower(MeteorShower),
    SolarFlare(SolarFlare),
    NebulaCloud(NebulaCloud),
}

impl ArenaEvent {
    pub fn kind_name(&self) -> &'static str {
        match self {
            ArenaEvent::MeteorShower(_) => "meteor_shower",
            ArenaEvent::SolarFlare(_) => "solar_flare",
            ArenaEvent::NebulaCloud(_) => "nebula_cloud",
        }
    }

    pub fn display_name(&self) -> &'static str {
        match self {
            ArenaEvent::MeteorShower(_) => "METEOR SHOWER",
            ArenaEvent::SolarFlare(_) => "SOLAR FLARE",
            ArenaEvent::NebulaCloud(_) => "NEBULA CLOUD",
        }
    }

    pub fn active(&self) -> bool {
        match self {
            ArenaEvent::MeteorShower(m) => {
                m.zones.iter().any(|z| !z.hit_done || z.live_left > 0.0)
            }
            ArenaEvent::SolarFlare(s) => s.elapsed < EVENT_FLARE_WARN + EVENT_FLARE_SWEEP,
            ArenaEvent::NebulaCloud(n) => n.elapsed < EVENT_NEBULA_WARN + EVENT_NEBULA_TTL,
        }
    }

    pub fn status_text(&self) -> String {
        if !self.active() {
            return String::new();
        }
        match self {
            ArenaEvent::MeteorShower(_) => "Event METEOR".to_string(),
            ArenaEvent::SolarFlare(s) => {
                if s.elapsed < EVENT_FLARE_WARN {
                    format!("Flare {:.1}s", (EVENT_FLARE_WARN - s.elapsed).max(0.0))
                } else {
                    "Event FLARE".to_string()
                }
            }
            ArenaEvent::NebulaCloud(n) => {
                if n.elapsed < EVENT_NEBULA_WARN {
                    format!("Nebula {:.1}s", (EVENT_NEBULA_WARN - n.elapsed).max(0.0))
                } else {
                    let left = (EVENT_NEBULA_WARN + EVENT_NEBULA_TTL - n.elapsed).max(0.0);
                    format!("Nebula {:.0}s", left)
                }
            }
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct EventStepOutcome {
    pub meteor_impacts: Vec<Vec2>,
    pub enemy_hits: Vec<(u64, i32)>,
    pub damage_player_amount: i32,
    pub player_hit_pos: Option<Vec2>,
    pub flare_sweep_started: bool,
}

fn random_point_in_arena(
    rng: &mut SimRng,
    room_radius: f32,
    reach: f32,
    map_type: &str,
) -> Vec2 {
    let ang = rng.range_f32(0.0, TAU);
    let r = rng.f32().sqrt() * reach.min(room_radius * 0.92).max(0.0);
    let raw = Vec2::new(ang.cos() * r, ang.sin() * r);
    clamp_entity_to_map(raw, room_radius, 24.0, map_type)
}

pub fn begin_wave_event(
    wave: i32,
    is_boss_wave: bool,
    room_radius: f32,
    map_type: &str,
    rng: &mut SimRng,
) -> Option<ArenaEvent> {
    if is_boss_wave || wave < EVENT_MIN_WAVE {
        return None;
    }
    if rng.f32() >= EVENT_WAVE_CHANCE {
        return None;
    }
    let choice = rng.index(3);
    match choice {
        0 => {
            let mut zones = Vec::with_capacity(EVENT_METEOR_IMPACTS);
            let mut taken = Vec::with_capacity(EVENT_METEOR_IMPACTS);
            let min_gap_sq = EVENT_METEOR_MIN_GAP * EVENT_METEOR_MIN_GAP;
            for i in 0..EVENT_METEOR_IMPACTS {
                let mut pos = Vec2::ZERO;
                for _ in 0..12 {
                    pos = random_point_in_arena(rng, room_radius, room_radius * 0.7, map_type);
                    if taken
                        .iter()
                        .all(|other: &Vec2| (pos - *other).length_squared() >= min_gap_sq)
                    {
                        break;
                    }
                }
                taken.push(pos);
                zones.push(MeteorZone {
                    pos,
                    delay: (i as f32) * EVENT_METEOR_STAGGER,
                    elapsed: 0.0,
                    hit_done: false,
                    live_left: 0.0,
                });
            }
            Some(ArenaEvent::MeteorShower(MeteorShower {
                wave,
                elapsed: 0.0,
                zones,
            }))
        }
        1 => {
            let start_angle = rng.range_f32(0.0, TAU);
            let sweep_dir = if rng.index(2) == 0 { 1.0 } else { -1.0 };
            Some(ArenaEvent::SolarFlare(SolarFlare {
                wave,
                elapsed: 0.0,
                start_angle,
                sweep_dir,
                sector_rad: EVENT_FLARE_SECTOR_DEG.to_radians(),
                beam_length: room_radius * DIAMOND_EXTENT_RATIO,
                last_hit_elapsed: -999.0,
                enemy_hit_elapsed: Vec::new(),
                sweep_sfx_played: false,
            }))
        }
        _ => {
            let pos = random_point_in_arena(rng, room_radius, room_radius * 0.5, map_type);
            Some(ArenaEvent::NebulaCloud(NebulaCloud {
                wave,
                elapsed: 0.0,
                pos,
                radius: EVENT_NEBULA_RADIUS,
                active: false,
                shielded_ids: Vec::new(),
            }))
        }
    }
}

pub fn update_arena_event(
    ev: &mut ArenaEvent,
    dt: f32,
    player_pos: Vec2,
    enemies: &mut [(u64, Vec2, &mut i32)], // (id, pos, &mut shield)
) -> EventStepOutcome {
    let mut out = EventStepOutcome::default();
    match ev {
        ArenaEvent::MeteorShower(m) => {
            m.elapsed += dt;
            for z in &mut m.zones {
                if m.elapsed < z.delay {
                    continue;
                }
                z.elapsed = (m.elapsed - z.delay).min(EVENT_METEOR_WARN);
                if !z.hit_done && m.elapsed >= z.delay + EVENT_METEOR_WARN {
                    z.hit_done = true;
                    z.live_left = EVENT_METEOR_LIVE;
                    out.meteor_impacts.push(z.pos);
                    let r2 = EVENT_METEOR_RADIUS * EVENT_METEOR_RADIUS;
                    if (player_pos - z.pos).length_squared() <= r2 {
                        out.damage_player_amount += EVENT_METEOR_DAMAGE;
                        out.player_hit_pos = Some(z.pos);
                    }
                    for (eid, epos, _) in enemies.iter() {
                        if (*epos - z.pos).length_squared() <= r2 {
                            out.enemy_hits.push((*eid, EVENT_METEOR_DAMAGE));
                        }
                    }
                } else if z.hit_done && z.live_left > 0.0 {
                    z.live_left = (z.live_left - dt).max(0.0);
                }
            }
        }
        ArenaEvent::SolarFlare(s) => {
            s.elapsed += dt;
            let live_t = s.elapsed - EVENT_FLARE_WARN;
            if live_t >= 0.0 && live_t < EVENT_FLARE_SWEEP {
                if !s.sweep_sfx_played {
                    s.sweep_sfx_played = true;
                    out.flare_sweep_started = true;
                }
                let prog = (live_t / EVENT_FLARE_SWEEP).clamp(0.0, 1.0);
                let ang = s.start_angle + s.sweep_dir * s.sector_rad * (prog - 0.5);
                let dir = Vec2::new(ang.cos(), ang.sin());
                let start = -dir * s.beam_length;
                let end = dir * s.beam_length;
                let hit_r = EVENT_FLARE_THICKNESS * 0.5 + 8.0;
                if s.elapsed - s.last_hit_elapsed >= EVENT_FLARE_TICK
                    && point_segment_distance_sq(player_pos, start, end) <= hit_r * hit_r
                {
                    s.last_hit_elapsed = s.elapsed;
                    out.damage_player_amount += EVENT_FLARE_DAMAGE;
                    out.player_hit_pos = Some(Vec2::ZERO);
                }
                s.enemy_hit_elapsed
                    .retain(|(id, _)| enemies.iter().any(|(eid, _, _)| eid == id));
                let enemy_hit_r = EVENT_FLARE_THICKNESS * 0.5 + 16.0;
                for (eid, epos, _) in enemies.iter() {
                    if point_segment_distance_sq(*epos, start, end) > enemy_hit_r * enemy_hit_r {
                        continue;
                    }
                    if let Some((_, last_hit)) = s.enemy_hit_elapsed.iter_mut().find(|(id, _)| id == eid) {
                        if s.elapsed - *last_hit >= EVENT_FLARE_TICK {
                            *last_hit = s.elapsed;
                            out.enemy_hits.push((*eid, EVENT_FLARE_DAMAGE));
                        }
                    } else {
                        s.enemy_hit_elapsed.push((*eid, s.elapsed));
                        out.enemy_hits.push((*eid, EVENT_FLARE_DAMAGE));
                    }
                }
            }
        }
        ArenaEvent::NebulaCloud(n) => {
            n.elapsed += dt;
            if n.elapsed >= EVENT_NEBULA_WARN && n.elapsed < EVENT_NEBULA_WARN + EVENT_NEBULA_TTL {
                n.active = true;
                let r2 = n.radius * n.radius;
                for (eid, epos, shield) in enemies.iter_mut() {
                    let inside = (*epos - n.pos).length_squared() <= r2;
                    let idx_opt = n.shielded_ids.iter().position(|(id, _)| *id == *eid);
                    if inside && idx_opt.is_none() {
                        **shield += EVENT_NEBULA_SHIELD;
                        n.shielded_ids.push((*eid, EVENT_NEBULA_SHIELD));
                    } else if !inside {
                        if let Some(pos) = idx_opt {
                            let (_, granted) = n.shielded_ids.swap_remove(pos);
                            **shield = (**shield - granted).max(0);
                        }
                    }
                }
            } else if n.active {
                n.active = false;
                for (eid, _, shield) in enemies.iter_mut() {
                    if let Some(pos) = n.shielded_ids.iter().position(|(id, _)| *id == *eid) {
                        let (_, granted) = n.shielded_ids.swap_remove(pos);
                        **shield = (**shield - granted).max(0);
                    }
                }
                n.shielded_ids.clear();
            }
        }
    }
    out
}

pub fn end_wave_event(ev: &mut ArenaEvent, enemies: &mut [(u64, &mut i32)]) {
    if let ArenaEvent::NebulaCloud(n) = ev {
        for (eid, shield) in enemies.iter_mut() {
            if let Some(pos) = n.shielded_ids.iter().position(|(id, _)| *id == *eid) {
                let (_, granted) = n.shielded_ids.swap_remove(pos);
                **shield = (**shield - granted).max(0);
            }
        }
        n.shielded_ids.clear();
        n.active = false;
    }
}
