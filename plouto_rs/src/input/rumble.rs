//! Rumble request selection. Pure logic, no gilrs dependency.
//!
//! `rumble_for_events` looks at one frame's `SimEvent`s and returns the single
//! strongest vibration request worth playing, if any.

use crate::sim::config::PLAYER_HP;
use crate::sim::state::{DamageResult, DamageTarget, SimEvent};

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RumbleRequest {
    pub strong: f32,
    pub weak: f32,
    pub duration_ms: u32,
}

impl RumbleRequest {
    /// Overall strength used to pick the winner among this frame's candidates.
    fn strength(&self) -> f32 {
        self.strong.max(self.weak)
    }
}

fn clamp01(v: f32) -> f32 {
    if v.is_nan() {
        0.0
    } else {
        v.clamp(0.0, 1.0)
    }
}

fn request(strong: f32, weak: f32, duration_ms: u32) -> RumbleRequest {
    RumbleRequest {
        strong: clamp01(strong),
        weak: clamp01(weak),
        duration_ms,
    }
}

/// Request for a player hit. Scaled by the fraction of max HP lost (shield
/// damage counts for half). Small hits give a short weak-motor pulse; heavy
/// hits add a strong-motor rumble.
fn player_hit_request(result: &DamageResult) -> Option<RumbleRequest> {
    if result.target != DamageTarget::Player || result.rejected.is_some() {
        return None;
    }
    if result.health_damage <= 0 && result.shield_damage <= 0 {
        return None;
    }

    let hp_max = PLAYER_HP.max(1) as f32;
    let health = result.health_damage.max(0) as f32;
    let shield = result.shield_damage.max(0) as f32;
    let frac = clamp01((health + shield * 0.5) / hp_max);

    if result.health_damage <= 0 {
        // Shield-only absorb: a light tick.
        return Some(request(0.0, 0.25 + frac * 1.5, 80));
    }

    if frac >= 0.2 {
        // Heavy hit: strong motor plus weak motor, around 200-350ms.
        let duration = 200 + (frac.min(1.0) * 150.0) as u32;
        Some(request(0.45 + frac * 0.55, 0.6 + frac * 0.4, duration))
    } else {
        // Small hit: light weak-motor pulse of about 80ms.
        Some(request(0.0, 0.3 + frac * 2.0, 80))
    }
}

/// Returns the single strongest rumble request for this frame's events.
pub fn rumble_for_events(events: &[SimEvent]) -> Option<RumbleRequest> {
    let mut best: Option<RumbleRequest> = None;

    let mut consider = |candidate: Option<RumbleRequest>| {
        if let Some(c) = candidate {
            match best {
                Some(b) if b.strength() >= c.strength() => {}
                _ => best = Some(c),
            }
        }
    };

    for event in events {
        let candidate = match event {
            SimEvent::DamageResolved(result) => {
                let mut r = player_hit_request(result);
                // A killing blow on the player is the heaviest hit.
                if result.target == DamageTarget::Player
                    && result.killed
                    && result.rejected.is_none()
                {
                    r = Some(request(1.0, 0.85, 450));
                }
                r
            }
            // Player death / game over: the strongest rumble we give.
            SimEvent::GameOver => Some(request(1.0, 1.0, 500)),
            // Boss defeated.
            SimEvent::BossDeath(_, _) => Some(request(1.0, 0.9, 600)),
            // Boss phase change: announced via a "PHASE II" / "PHASE III" banner.
            SimEvent::Banner { title, .. } if title.starts_with("PHASE") => {
                Some(request(0.8, 0.6, 450))
            }
            // Big explosions: large shockwaves and elite kill bursts.
            SimEvent::Shockwave { max_radius, .. } if *max_radius >= 150.0 => {
                let t = clamp01((*max_radius - 150.0) / 250.0);
                Some(request(0.4 + t * 0.4, 0.4 + t * 0.3, 250))
            }
            SimEvent::KillBurst { big: true, .. } => Some(request(0.2, 0.35, 120)),
            _ => None,
        };
        consider(candidate);
    }

    best
}
