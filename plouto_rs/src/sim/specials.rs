use std::collections::HashMap;
use std::f32::consts::TAU;

use crate::sim::config::{
    AFTERBURN_BOSS_MULT, AFTERBURN_DAMAGE, AFTERBURN_DROP_SECONDS, AFTERBURN_HIT_RADIUS,
    AFTERBURN_LIFE_SECONDS, AFTERBURN_MAX_SEGMENTS, AFTERBURN_TICK_SECONDS, CHAIN_ARC_POOL,
    CHAIN_ARC_SECONDS, CHAIN_DAMAGE_PERCENT, CHAIN_RANGE, ECHO_DAMAGE_PERCENT,
    ECHO_HOMING_RANGE, ECHO_HOMING_SECONDS, ECHO_HOMING_TURN_RATE, ECHO_SPEED,
    ECHO_TTL, HOMING_RANGE, HOMING_TURN_RATE, REPULSOR_CLEAR_SPEED, REPULSOR_COOLDOWN_SECONDS,
    REPULSOR_MAX_CHARGES, REPULSOR_PUSH_SPEED, REPULSOR_RANGE, REPULSOR_RING_SECONDS,
    REPULSOR_STUN_SECONDS, RICOCHET_BOUNCES, SHARD_CAP, SHARD_DAMAGE_PERCENT, SHARD_HIT_RADIUS,
    SHARD_SECONDS, SHARD_SPEED_FRACTION, SHARD_SPREAD_DEG,
};
use crate::sim::math::{
    arena_edge_normal, arena_inside, half_up_percent, point_segment_distance_sq, round_countdown,
    Vec2,
};
use crate::sim::projectile::Projectile;

// =========================================================================
// Chain Lightning
// =========================================================================

#[derive(Debug, Clone)]
pub struct ChainArc {
    pub a: Vec2,
    pub b: Vec2,
    pub started_at: f32,
    pub ttl: f32,
    pub seed: u32,
}

#[derive(Debug, Clone)]
pub struct ChainSystem {
    pub until: f32,
    pub arcs: Vec<ChainArc>,
    arc_seq: u32,
}

impl Default for ChainSystem {
    fn default() -> Self {
        Self::new()
    }
}

impl ChainSystem {
    pub fn new() -> Self {
        Self {
            until: 0.0,
            arcs: Vec::with_capacity(CHAIN_ARC_POOL),
            arc_seq: 0,
        }
    }

    pub fn is_active(&self, now: f32) -> bool {
        now < self.until
    }

    pub fn activate(&mut self, now: f32, duration: f32) {
        self.until = now + duration;
    }

    pub fn spawn_arc(&mut self, a: Vec2, b: Vec2, now: f32) {
        self.arc_seq = self.arc_seq.wrapping_add(1);
        let arc = ChainArc {
            a,
            b,
            started_at: now,
            ttl: CHAIN_ARC_SECONDS,
            seed: self.arc_seq,
        };
        if self.arcs.len() >= CHAIN_ARC_POOL {
            self.arcs.remove(0);
        }
        self.arcs.push(arc);
    }

    pub fn prune(&mut self, now: f32) {
        self.arcs.retain(|a| now - a.started_at < a.ttl);
    }
}

pub fn chain_arc_damage(player_damage: i32) -> i32 {
    half_up_percent(player_damage, CHAIN_DAMAGE_PERCENT).max(1)
}

pub fn find_chain_target(origin: Vec2, candidates: &[(usize, Vec2, bool)]) -> Option<(usize, Vec2)> {
    let r2 = CHAIN_RANGE * CHAIN_RANGE;
    let mut best: Option<(usize, Vec2, f32)> = None;
    for &(idx, pos, alive) in candidates {
        if !alive {
            continue;
        }
        let d2 = (pos - origin).length_squared();
        if d2 <= r2 {
            if best.map_or(true, |b| d2 < b.2) {
                best = Some((idx, pos, d2));
            }
        }
    }
    best.map(|(i, p, _)| (i, p))
}

// =========================================================================
// Repulsor Shockwave
// =========================================================================

#[derive(Debug, Clone)]
pub struct RepulsorRing {
    pub pos: Vec2,
    pub started_at: f32,
    pub ttl: f32,
}

#[derive(Debug, Clone)]
pub struct RepulsorSystem {
    pub charges: i32,
    pub cooldown_until: f32,
    pub rings: Vec<RepulsorRing>,
}

impl Default for RepulsorSystem {
    fn default() -> Self {
        Self::new()
    }
}

impl RepulsorSystem {
    pub fn new() -> Self {
        Self {
            charges: 0,
            cooldown_until: 0.0,
            rings: Vec::new(),
        }
    }

    /// Returns true if the shockwave should fire immediately.
    pub fn on_pickup(&mut self, now: f32) -> bool {
        if self.charges >= REPULSOR_MAX_CHARGES {
            // An overflow pickup becomes an immediate bonus pulse without delaying the
            // recharge already queued for the stored charges.
            return true;
        }
        if self.charges > 0 || now < self.cooldown_until {
            self.charges = (self.charges + 1).min(REPULSOR_MAX_CHARGES);
            false
        } else {
            self.cooldown_until = now + REPULSOR_COOLDOWN_SECONDS;
            true
        }
    }

    /// Call every step to fire a queued charge once cooldown finishes.
    pub fn poll_ready(&mut self, now: f32) -> bool {
        if self.charges > 0 && now >= self.cooldown_until {
            self.charges -= 1;
            self.cooldown_until = now + REPULSOR_COOLDOWN_SECONDS;
            true
        } else {
            false
        }
    }

    pub fn spawn_ring(&mut self, pos: Vec2, now: f32) {
        self.rings.push(RepulsorRing {
            pos,
            started_at: now,
            ttl: REPULSOR_RING_SECONDS,
        });
    }

    pub fn prune(&mut self, now: f32) {
        self.rings.retain(|r| now - r.started_at < r.ttl);
    }

    pub fn format_hud(&self, now: f32) -> String {
        let cd = round_countdown((self.cooldown_until - now).max(0.0));
        if self.charges > 0 {
            if cd > 0.0 {
                format!("Repulsor {} ({}s)", self.charges, cd.ceil() as i32)
            } else {
                format!("Repulsor {}", self.charges)
            }
        } else if cd > 0.0 {
            format!("Repulsor {}s", cd.ceil() as i32)
        } else {
            String::new()
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct RepulsorWaveStats {
    pub stunned_positions: Vec<Vec2>,
    pub cleared_bullets: usize,
    pub pushed_bullets: usize,
}

pub fn apply_repulsor_shockwave(
    origin: Vec2,
    projectiles: &mut Vec<Projectile>,
    enemies: &mut [(Vec2, &mut f32)], // (pos, &mut stun_left)
) -> RepulsorWaveStats {
    let mut stats = RepulsorWaveStats::default();
    let r2 = REPULSOR_RANGE * REPULSOR_RANGE;

    let mut idx = 0;
    while idx < projectiles.len() {
        let p = &mut projectiles[idx];
        if p.owner != "enemy" {
            idx += 1;
            continue;
        }
        let d = p.pos - origin;
        if d.length_squared() > r2 {
            idx += 1;
            continue;
        }
        let speed = p.vel.length();
        if speed < REPULSOR_CLEAR_SPEED {
            projectiles.swap_remove(idx);
            stats.cleared_bullets += 1;
            continue;
        }
        let out_dir = if d.length_squared() > 1e-6 {
            d.normalized()
        } else {
            Vec2::new(1.0, 0.0)
        };
        let radial_v = p.vel.dot(out_dir);
        let target_speed = speed.max(REPULSOR_PUSH_SPEED);
        if radial_v < target_speed {
            p.vel = out_dir * target_speed;
        }
        stats.pushed_bullets += 1;
        idx += 1;
    }

    for (epos, stun_left) in enemies.iter_mut() {
        if (*epos - origin).length_squared() <= r2 {
            **stun_left = (**stun_left).max(REPULSOR_STUN_SECONDS);
            stats.stunned_positions.push(*epos);
        }
    }

    stats
}

// =========================================================================
// Echo Dash Projectile & Ring
// =========================================================================

#[derive(Debug, Clone)]
pub struct EchoRing {
    pub pos: Vec2,
    pub started_at: f32,
    pub ttl: f32,
}

pub fn spawn_echo_projectile(pos: Vec2, dir: Vec2, effective_damage: i32) -> Projectile {
    let d = if dir.length_squared() > 1e-9 {
        dir.normalized()
    } else {
        Vec2::new(1.0, 0.0)
    };
    let dmg = half_up_percent(effective_damage, ECHO_DAMAGE_PERCENT).max(1);
    let mut p = Projectile::new(pos, d * ECHO_SPEED, dmg, ECHO_TTL, "player", "echo");
    p.is_echo = true;
    p.homing_left = ECHO_HOMING_SECONDS;
    p
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum RicochetStep {
    None,
    Bounced(Vec2),
    Spent(Vec2),
}

pub fn steer_homing_projectiles(
    projectiles: &mut [Projectile],
    targets: &[(u64, Vec2)],
    dt: f32,
    player_homing_active: bool,
) -> usize {
    if targets.is_empty() {
        for p in projectiles.iter_mut() {
            if p.is_echo && p.homing_left > 0.0 {
                p.homing_left = (p.homing_left - dt).max(0.0);
            }
        }
        return 0;
    }
    let mut new_locks = 0;
    for p in projectiles.iter_mut() {
        if p.owner != "player" || p.projectile_type == "mortar" {
            continue;
        }
        let (range, turn_rate) = if p.is_echo {
            if p.homing_left <= 0.0 {
                continue;
            }
            p.homing_left = (p.homing_left - dt).max(0.0);
            (ECHO_HOMING_RANGE, ECHO_HOMING_TURN_RATE)
        } else if player_homing_active {
            (HOMING_RANGE, HOMING_TURN_RATE)
        } else {
            continue;
        };

        let range_sq = range * range;
        let mut best: Option<(u64, Vec2, f32)> = None;
        for &(tid, tpos) in targets {
            if p.hit_ids.contains(&tid) {
                continue;
            }
            let d2 = (tpos - p.pos).length_squared();
            if d2 <= range_sq && best.map_or(true, |b| d2 < b.2) {
                best = Some((tid, tpos, d2));
            }
        }
        let Some((tid, tpos, _)) = best else {
            continue;
        };
        let speed = p.vel.length();
        if speed <= 1e-6 {
            continue;
        }
        let cur_ang = p.vel.y.atan2(p.vel.x);
        let desired_vec = tpos - p.pos;
        if desired_vec.length_squared() <= 1e-6 {
            continue;
        }
        let des_ang = desired_vec.y.atan2(desired_vec.x);
        let diff = (des_ang - cur_ang + std::f32::consts::PI).rem_euclid(TAU) - std::f32::consts::PI;
        let max_step = turn_rate * dt;
        let step = diff.clamp(-max_step, max_step);
        let next_ang = cur_ang + step;
        p.vel = Vec2::new(next_ang.cos(), next_ang.sin()) * speed;
        if !p.is_echo && p.homing_lock_id != Some(tid) {
            p.homing_lock_id = Some(tid);
            new_locks += 1;
        }
    }
    new_locks
}

fn edge_point_bisect(inside_pt: Vec2, outside_pt: Vec2, map_type: &str, radius: f32) -> Vec2 {
    let d = outside_pt - inside_pt;
    let mut lo = 0.0_f32;
    let mut hi = 1.0_f32;
    for _ in 0..12 {
        let mid = 0.5 * (lo + hi);
        if arena_inside(inside_pt + d * mid, radius, map_type) {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    inside_pt + d * lo
}

pub fn step_ricochet_bounce(
    p: &mut Projectile,
    ricochet_active: bool,
    radius: f32,
    map_type: &str,
) -> RicochetStep {
    if p.owner != "player" {
        return RicochetStep::None;
    }
    if arena_inside(p.pos, radius, map_type) {
        return RicochetStep::None;
    }
    let prev = p.prev_pos.unwrap_or(p.pos);
    if p.bounces_taken >= RICOCHET_BOUNCES {
        let impact = if arena_inside(prev, radius, map_type) {
            edge_point_bisect(prev, p.pos, map_type, radius)
        } else {
            p.pos
        };
        p.boundary_spent = Some(impact);
        p.pos = impact;
        return RicochetStep::Spent(impact);
    }
    if !ricochet_active {
        return RicochetStep::None;
    }
    if !arena_inside(prev, radius, map_type) {
        return RicochetStep::None;
    }

    let b = edge_point_bisect(prev, p.pos, map_type, radius);
    let normal = arena_edge_normal(b, radius, map_type);
    let vn = p.vel.dot(normal);
    if vn <= 0.0 {
        return RicochetStep::None;
    }
    p.pre_bounce_segment = Some((prev, b));
    p.vel -= normal * (2.0 * vn);
    let overshoot = p.pos - b;
    let reflected = overshoot - normal * (2.0 * overshoot.dot(normal));
    let mut new_pos = b + reflected;
    if !arena_inside(new_pos, radius, map_type) {
        new_pos = b;
    }
    p.prev_pos = Some(b);
    p.pos = new_pos;
    p.bounces_taken += 1;
    RicochetStep::Bounced(b)
}

// =========================================================================
// Afterburn Trail
// =========================================================================

#[derive(Debug, Clone)]
pub struct AfterburnSegment {
    pub pos: Vec2,
    pub born_at: f32,
    pub ttl: f32,
}

#[derive(Debug, Clone)]
pub struct AfterburnSystem {
    pub segments: Vec<AfterburnSegment>,
    pub next_drop_at: f32,
    pub last_tick_by_enemy: HashMap<u64, f32>,
}

impl Default for AfterburnSystem {
    fn default() -> Self {
        Self::new()
    }
}

impl AfterburnSystem {
    pub fn new() -> Self {
        Self {
            segments: Vec::with_capacity(AFTERBURN_MAX_SEGMENTS),
            next_drop_at: 0.0,
            last_tick_by_enemy: HashMap::new(),
        }
    }

    pub fn maybe_drop(&mut self, pos: Vec2, now: f32) {
        if now < self.next_drop_at {
            return;
        }
        self.next_drop_at = now + AFTERBURN_DROP_SECONDS;
        if self.segments.len() >= AFTERBURN_MAX_SEGMENTS {
            self.segments.remove(0);
        }
        self.segments.push(AfterburnSegment {
            pos,
            born_at: now,
            ttl: AFTERBURN_LIFE_SECONDS,
        });
    }

    pub fn prune(&mut self, now: f32) {
        self.segments.retain(|s| now - s.born_at < s.ttl);
    }

    pub fn collect_hits(&mut self, now: f32, enemies: &[(u64, Vec2, bool)]) -> Vec<(usize, i32)> {
        if self.segments.is_empty() {
            return Vec::new();
        }
        let r2 = AFTERBURN_HIT_RADIUS * AFTERBURN_HIT_RADIUS;
        let mut hits = Vec::new();
        for (idx, &(eid, epos, is_boss)) in enemies.iter().enumerate() {
            let touching = self
                .segments
                .iter()
                .any(|s| (epos - s.pos).length_squared() <= r2);
            if !touching {
                continue;
            }
            let ready = self
                .last_tick_by_enemy
                .get(&eid)
                .map_or(true, |&t| now - t >= AFTERBURN_TICK_SECONDS);
            if ready {
                self.last_tick_by_enemy.insert(eid, now);
                let dmg = if is_boss {
                    ((AFTERBURN_DAMAGE as f32) * AFTERBURN_BOSS_MULT).round().max(1.0) as i32
                } else {
                    AFTERBURN_DAMAGE
                };
                hits.push((idx, dmg));
            }
        }
        hits
    }
}

// =========================================================================
// Critical Hit Shards
// =========================================================================

#[derive(Debug, Clone)]
pub struct Shard {
    pub pos: Vec2,
    pub vel: Vec2,
    pub damage: i32,
    pub ttl: f32,
    pub max_ttl: f32,
    pub source_enemy_id: u64,
    pub color: [u8; 3],
}

/// Compute first entry point along segment `a -> b` into circle `(centre, reach)`, matching Python `shards.impact_point`.
pub fn impact_point(a: Vec2, b: Vec2, centre: Vec2, reach: f32) -> Vec2 {
    let ab = b - a;
    let a_coef = ab.length_squared();
    if a_coef <= 1e-12 {
        return b;
    }
    let f = a - centre;
    let b_coef = 2.0 * f.dot(ab);
    let c_coef = f.length_squared() - reach * reach;
    let disc = b_coef * b_coef - 4.0 * a_coef * c_coef;
    let t = if disc >= 0.0 {
        (-b_coef - disc.sqrt()) / (2.0 * a_coef)
    } else {
        -b_coef / (2.0 * a_coef)
    };
    let t = t.clamp(0.0, 1.0);
    a + ab * t
}

pub fn can_split_crit(p: &Projectile) -> bool {
    p.owner == "player" && p.is_crit && !(p.weapon_name.is_empty() && p.projectile_type == "bullet")
}

#[derive(Debug, Clone)]
pub struct ShardPool {
    pub shards: Vec<Shard>,
}

impl Default for ShardPool {
    fn default() -> Self {
        Self::new()
    }
}

impl ShardPool {
    pub fn new() -> Self {
        Self {
            shards: Vec::with_capacity(SHARD_CAP),
        }
    }

    pub fn spawn_crit_shards(
        &mut self,
        origin: Vec2,
        bullet_vel: Vec2,
        bullet_damage: i32,
        hit_enemy_id: u64,
        color: [u8; 3],
    ) {
        let dir = bullet_vel.normalized();
        if dir.length_squared() <= 1e-9 {
            return;
        }
        let speed = (bullet_vel.length() * SHARD_SPEED_FRACTION).max(40.0);
        let dmg = half_up_percent(bullet_damage, SHARD_DAMAGE_PERCENT).max(1);
        for deg in [-SHARD_SPREAD_DEG, 0.0, SHARD_SPREAD_DEG] {
            if self.shards.len() >= SHARD_CAP {
                self.shards.remove(0);
            }
            let v = dir.rotated_deg(deg) * speed;
            self.shards.push(Shard {
                pos: origin,
                vel: v,
                damage: dmg,
                ttl: SHARD_SECONDS,
                max_ttl: SHARD_SECONDS,
                source_enemy_id: hit_enemy_id,
                color,
            });
        }
    }

    pub fn step(
        &mut self,
        dt: f32,
        enemies: &[(u64, Vec2, f32)], // (id, pos, radius)
    ) -> Vec<(usize, i32, Vec2)> {
        let mut hits = Vec::new();
        let mut i = 0;
        while i < self.shards.len() {
            let s = &mut self.shards[i];
            s.ttl -= dt;
            if s.ttl <= 1e-9 {
                self.shards.swap_remove(i);
                continue;
            }
            let prev = s.pos;
            s.pos += s.vel * dt;
            let cur = s.pos;
            let min_x = prev.x.min(cur.x);
            let max_x = prev.x.max(cur.x);
            let min_y = prev.y.min(cur.y);
            let max_y = prev.y.max(cur.y);
            let mut hit_idx = None;
            for (ei, &(eid, epos, erad)) in enemies.iter().enumerate() {
                if eid == s.source_enemy_id {
                    continue;
                }
                let reach = erad + SHARD_HIT_RADIUS;
                if epos.x < min_x - reach
                    || epos.x > max_x + reach
                    || epos.y < min_y - reach
                    || epos.y > max_y + reach
                {
                    continue;
                }
                if point_segment_distance_sq(epos, prev, cur) <= reach * reach {
                    hit_idx = Some(ei);
                    break;
                }
            }
            if let Some(ei) = hit_idx {
                let s_rem = self.shards.swap_remove(i);
                hits.push((ei, s_rem.damage, s_rem.pos));
            } else {
                i += 1;
            }
        }
        hits
    }
}
