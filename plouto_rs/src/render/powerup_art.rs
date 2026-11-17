use std::f32::consts::{FRAC_PI_2, PI, TAU};

use crate::render::sdf::{linear_rgba_f, mix_rgb, SdfBatch};
use crate::render::text::{AlignX, AlignY, FontId, TextBatch};
use crate::sim::config::{ISO_SCALE_X, ISO_SCALE_Y};
use crate::sim::math::{to_iso_cam, Vec2};
use crate::sim::powerup::is_rare_powerup;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PowerupTier {
    Core,
    Tactical,
    Rare,
}

#[derive(Debug, Clone, Copy)]
pub struct PowerupMeta {
    pub key: &'static str,
    pub name: &'static str,
    pub short_code: &'static str,
    pub category: &'static str,
    pub tier: PowerupTier,
    pub what: &'static str,
    pub deal: &'static str,
    pub lore: &'static str,
}

pub const POWERUP_CATALOG: &[PowerupMeta] = &[
    PowerupMeta {
        key: "heal",
        name: "Repair Core",
        short_code: "HP+",
        category: "Vital",
        tier: PowerupTier::Core,
        what: "Restores missing hull integrity immediately on pickup.",
        deal: "Keep scanning waves whenever hull drops below half.",
        lore: "Nanite solder capsule jettisoned from foundry drones.",
    },
    PowerupMeta {
        key: "shield",
        name: "Aegis Shell",
        short_code: "SHD",
        category: "Defense",
        tier: PowerupTier::Core,
        what: "Adds absorptive barrier layers over your hull.",
        deal: "Absorbs incoming hits cleanly before hull damage starts.",
        lore: "Layered hard-light plating tuned to ship capacitance.",
    },
    PowerupMeta {
        key: "damage",
        name: "Overcharge",
        short_code: "DMG",
        category: "Offense",
        tier: PowerupTier::Core,
        what: "Permanently increases weapon damage multiplier this run.",
        deal: "Stacks multiplicatively with crits and heavy cannons.",
        lore: "Unshielded accelerator coils swapped into the breech.",
    },
    PowerupMeta {
        key: "speed",
        name: "Thruster Tune",
        short_code: "SPD",
        category: "Mobility",
        tier: PowerupTier::Core,
        what: "Permanently boosts base cruise and strafe speed.",
        deal: "Helps kite fast chargers and weave out of laser sweeps.",
        lore: "Vectored ion vernier nozzles calibrated for tight arcs.",
    },
    PowerupMeta {
        key: "firerate",
        name: "Rapid Cycle",
        short_code: "ROF",
        category: "Offense",
        tier: PowerupTier::Core,
        what: "Shortens weapon cyclic reload delay for faster bursts.",
        deal: "Raises sustained DPS and proc chances across all guns.",
        lore: "Magnetic autoloader rails overclocked past spec.",
    },
    PowerupMeta {
        key: "boost",
        name: "Infinite Fuel",
        short_code: "BST",
        category: "Mobility",
        tier: PowerupTier::Tactical,
        what: "Refills thruster reserve and grants free boosting briefly.",
        deal: "Chain high-speed flanks without stalling your capacitor.",
        lore: "Zero-point deuterium cell burning cold white-amber.",
    },
    PowerupMeta {
        key: "weapon",
        name: "Weapon Pod",
        short_code: "WPN",
        category: "Arsenal",
        tier: PowerupTier::Tactical,
        what: "Equips a specialized temporary primary weapon system.",
        deal: "Temporarily replaces your primary weapon. Explosives reload between blasts.",
        lore: "Drop-rigged ordnance crate unlocked at proximity.",
    },
    PowerupMeta {
        key: "drone",
        name: "Wingman Drone",
        short_code: "DRN",
        category: "Companion",
        tier: PowerupTier::Tactical,
        what: "Deploys an autonomous orbiting escort that auto-fires.",
        deal: "Doubles pressure on flankers while you focus dodging.",
        lore: "Semi-sentient patrol micro-craft slaved to your transponder.",
    },
    PowerupMeta {
        key: "magnet",
        name: "Gravity Magnet",
        short_code: "MAG",
        category: "Utility",
        tier: PowerupTier::Tactical,
        what: "Expands pickup pull radius and acceleration cleanly.",
        deal: "Vacuum drops across wide arenas without detouring.",
        lore: "Attractive graviton loop focusing stray salvage.",
    },
    PowerupMeta {
        key: "ricochet",
        name: "Ricochet Lens",
        short_code: "RIC",
        category: "Projectile",
        tier: PowerupTier::Tactical,
        what: "Shots bounce off arena bounds and strike fresh targets.",
        deal: "Deadly inside tight corridors, Diamond apexes, and swarms.",
        lore: "Phase-reflective muzzle prism bending kinetic slugs.",
    },
    PowerupMeta {
        key: "homing",
        name: "Seeker Lock",
        short_code: "HOM",
        category: "Projectile",
        tier: PowerupTier::Tactical,
        what: "Bends outgoing projectiles smoothly toward nearby foes.",
        deal: "Converts spray weapons into relentless pursuit swarms.",
        lore: "Micro-gyroscopic guidance firmware flashed live.",
    },
    PowerupMeta {
        key: "chain",
        name: "Arc Coil",
        short_code: "ARC",
        category: "Elemental",
        tier: PowerupTier::Tactical,
        what: "Discharges high-voltage lightning between clustered foes.",
        deal: "Melts egg sacs and swarm packs in chain reactions.",
        lore: "Capacitor totem salvaged from Thunder-class cruisers.",
    },
    PowerupMeta {
        key: "repulsor",
        name: "Pulse Repulsor",
        short_code: "REP",
        category: "Defense",
        tier: PowerupTier::Tactical,
        what: "Stores periodic radial shockwaves that blast enemies back.",
        deal: "Breaks surround traps and buys breathing room on cooldown.",
        lore: "Omnidirectional grav-thumper originally fitted on tugs.",
    },
    PowerupMeta {
        key: "laser",
        name: "Ion Beam",
        short_code: "LSR",
        category: "Rare Tech",
        tier: PowerupTier::Rare,
        what: "Fires broad piercing beam pulses on a dedicated quick cooldown for a short pickup window.",
        deal: "Cuts cleanly through lined-up mobs and shields alike.",
        lore: "Focusing crystal borrowed from orbital cutters.",
    },
    PowerupMeta {
        key: "vortex",
        name: "Singularity",
        short_code: "VTX",
        category: "Rare Tech",
        tier: PowerupTier::Rare,
        what: "Surrounds your craft with a wide damaging gravity well for a short pickup window.",
        deal: "Shreds swarms that try to hug your hull mid-kite.",
        lore: "Contained micro-singularity stabilized by magnetic rings.",
    },
    PowerupMeta {
        key: "time_slow",
        name: "Chrono Field",
        short_code: "CHR",
        category: "Rare Tech",
        tier: PowerupTier::Rare,
        what: "Dilates enemy movement and projectile speeds temporarily.",
        deal: "Turn bullet-hell boss barrages into crisp dodging lanes.",
        lore: "Tachyon brake core warping local reference frames.",
    },
    PowerupMeta {
        key: "ultra",
        name: "Nova Charge",
        short_code: "ULT",
        category: "Ultimate",
        tier: PowerupTier::Rare,
        what: "Grants an Ultra charge ready for devastating bursts.",
        deal: "Hold or tap Ultra at boss phases and panic swarms.",
        lore: "Prismatic singularity core humming at super-critical load.",
    },
];

pub fn powerup_meta(kind: &str) -> &'static PowerupMeta {
    POWERUP_CATALOG
        .iter()
        .find(|m| m.key == kind)
        .unwrap_or(&POWERUP_CATALOG[0])
}

#[inline]
pub fn tier_label(tier: PowerupTier) -> &'static str {
    match tier {
        PowerupTier::Core => "CORE",
        PowerupTier::Tactical => "TACTICAL",
        PowerupTier::Rare => "RARE",
    }
}

/// Shared crisp SDF vector emblem used uniformly across world drops, HUD badges, and Guide rows.
#[allow(clippy::too_many_arguments)]
pub fn draw_powerup_emblem(
    kind: &str,
    cx: f32,
    cy: f32,
    r: f32,
    col: [u8; 3],
    fade: f32,
    motion_t: f32,
    alpha_batch: &mut SdfBatch,
    add_batch: &mut SdfBatch,
) {
    let f = fade.clamp(0.0, 1.0);
    if f <= 0.005 || r <= 1.0 {
        return;
    }
    let meta = powerup_meta(kind);
    let bright = mix_rgb(col, [255, 255, 255], 0.45);
    let core_white = mix_rgb(col, [255, 255, 255], 0.85);
    let bg_col = [10, 18, 30];

    // 1. Unified Tier Frame + Backing Disc
    match meta.tier {
        PowerupTier::Core => {
            alpha_batch.circle(cx, cy, r * 1.04, linear_rgba_f(bg_col, 0.92 * f, 1.0));
            alpha_batch.ring(cx, cy, r, r, (r * 0.14).max(1.2), linear_rgba_f(col, 0.95 * f, 1.15));
        }
        PowerupTier::Tactical => {
            let oct = regular_poly(cx, cy, r * 1.08, 8, PI / 8.0);
            alpha_batch.polygon(&oct, linear_rgba_f(bg_col, 0.94 * f, 1.0));
            alpha_batch.polyline_closed(&oct, (r * 0.13).max(1.2), linear_rgba_f(col, 0.95 * f, 1.2));
            let inner = regular_poly(cx, cy, r * 0.88, 8, PI / 8.0);
            add_batch.polyline_closed(&inner, (r * 0.06).max(0.7), linear_rgba_f(bright, 0.45 * f, 1.5));
        }
        PowerupTier::Rare => {
            let spin = motion_t * 1.4;
            let hex_bg = regular_poly(cx, cy, r * 1.12, 6, spin * 0.35);
            alpha_batch.polygon(&hex_bg, linear_rgba_f(bg_col, 0.95 * f, 1.0));
            alpha_batch.polyline_closed(&hex_bg, (r * 0.14).max(1.3), linear_rgba_f(bright, 0.96 * f, 1.35));
            add_batch.arc(cx, cy, r * 1.26, (r * 0.10).max(1.0), spin, 1.85, linear_rgba_f(bright, 0.72 * f, 1.7));
            add_batch.arc(cx, cy, r * 1.26, (r * 0.10).max(1.0), spin + PI, 1.85, linear_rgba_f(bright, 0.72 * f, 1.7));
        }
    }

    // 2. Crisp Vector Glyph Symbol inside radius `r * 0.72`
    let g = r * 0.68;
    let stroke = (r * 0.14).max(1.25);
    match kind {
        "heal" => {
            alpha_batch.rrect(cx, cy, g * 0.72, g * 0.23, 0.0, g * 0.08, linear_rgba_f(col, f, 1.2));
            alpha_batch.rrect(cx, cy, g * 0.23, g * 0.72, 0.0, g * 0.08, linear_rgba_f(col, f, 1.2));
            add_batch.rrect(cx, cy, g * 0.56, g * 0.11, 0.0, g * 0.04, linear_rgba_f(core_white, 0.9 * f, 1.7));
            add_batch.rrect(cx, cy, g * 0.11, g * 0.56, 0.0, g * 0.04, linear_rgba_f(core_white, 0.9 * f, 1.7));
        }
        "shield" => {
            let crest = [
                [cx, cy + g * 0.78],
                [cx + g * 0.68, cy + g * 0.42],
                [cx + g * 0.54, cy - g * 0.32],
                [cx, cy - g * 0.80],
                [cx - g * 0.54, cy - g * 0.32],
                [cx - g * 0.68, cy + g * 0.42],
            ];
            alpha_batch.polygon(&crest, linear_rgba_f(col, 0.85 * f, 1.15));
            alpha_batch.polyline_closed(&crest, stroke * 0.85, linear_rgba_f(core_white, f, 1.45));
            add_batch.line(cx, cy + g * 0.48, cx, cy - g * 0.48, stroke * 0.65, linear_rgba_f(core_white, 0.8 * f, 1.8));
        }
        "damage" => {
            // Spear / Power Sword
            alpha_batch.triangle(
                [cx, cy + g * 0.86],
                [cx - g * 0.28, cy + g * 0.08],
                [cx + g * 0.28, cy + g * 0.08],
                linear_rgba_f(core_white, f, 1.5),
            );
            alpha_batch.line(cx, cy + g * 0.62, cx, cy - g * 0.72, stroke * 1.15, linear_rgba_f(col, f, 1.25));
            alpha_batch.line(cx - g * 0.46, cy - g * 0.24, cx + g * 0.46, cy - g * 0.24, stroke * 1.0, linear_rgba_f(bright, f, 1.35));
            add_batch.circle(cx, cy + g * 0.58, r * 0.13, linear_rgba_f(core_white, 0.95 * f, 1.9));
        }
        "speed" => {
            for idx in 0..2 {
                let off = if idx == 0 { -g * 0.26 } else { g * 0.22 };
                let c = if idx == 1 { core_white } else { col };
                alpha_batch.line(cx + off - g * 0.28, cy + g * 0.52, cx + off + g * 0.34, cy, stroke * 1.05, linear_rgba_f(c, f, 1.35));
                alpha_batch.line(cx + off + g * 0.34, cy, cx + off - g * 0.28, cy - g * 0.52, stroke * 1.05, linear_rgba_f(c, f, 1.35));
            }
            add_batch.line(cx + g * 0.22 - g * 0.22, cy + g * 0.44, cx + g * 0.56, cy, stroke * 0.7, linear_rgba_f(core_white, 0.85 * f, 1.85));
            add_batch.line(cx + g * 0.56, cy, cx + g * 0.22 - g * 0.22, cy - g * 0.44, stroke * 0.7, linear_rgba_f(core_white, 0.85 * f, 1.85));
        }
        "firerate" => {
            for (ox, oy) in [(-g * 0.36, -g * 0.14), (0.0, g * 0.12), (g * 0.36, -g * 0.14)] {
                add_batch.line(cx + ox - g * 0.14, cy + oy - g * 0.38, cx + ox + g * 0.14, cy + oy + g * 0.38, stroke * 0.9, linear_rgba_f(col, f, 1.45));
                add_batch.circle(cx + ox + g * 0.14, cy + oy + g * 0.38, r * 0.11, linear_rgba_f(core_white, f, 1.9));
            }
        }
        "boost" => {
            // Afterburner jet flame
            alpha_batch.triangle(
                [cx, cy + g * 0.85],
                [cx - g * 0.52, cy - g * 0.42],
                [cx + g * 0.52, cy - g * 0.42],
                linear_rgba_f(col, f, 1.3),
            );
            add_batch.triangle(
                [cx, cy + g * 0.55],
                [cx - g * 0.26, cy - g * 0.32],
                [cx + g * 0.26, cy - g * 0.32],
                linear_rgba_f(core_white, 0.95 * f, 1.9),
            );
            alpha_batch.line(cx - g * 0.44, cy - g * 0.58, cx + g * 0.44, cy - g * 0.58, stroke, linear_rgba_f(bright, f, 1.4));
        }
        "weapon" => {
            // Precision cannon pod
            alpha_batch.rrect(cx + g * 0.04, cy + g * 0.14, g * 0.64, g * 0.22, 0.0, g * 0.06, linear_rgba_f(bright, f, 1.3));
            alpha_batch.rrect(cx - g * 0.24, cy - g * 0.24, g * 0.18, g * 0.32, 0.18, g * 0.04, linear_rgba_f(col, f, 1.2));
            add_batch.circle(cx + g * 0.68, cy + g * 0.14, r * 0.13, linear_rgba_f(core_white, f, 1.8));
        }
        "drone" => {
            alpha_batch.triangle([cx - g * 0.78, cy - g * 0.10], [cx - g * 0.16, cy + g * 0.36], [cx - g * 0.16, cy - g * 0.40], linear_rgba_f(col, f, 1.25));
            alpha_batch.triangle([cx + g * 0.78, cy - g * 0.10], [cx + g * 0.16, cy + g * 0.36], [cx + g * 0.16, cy - g * 0.40], linear_rgba_f(col, f, 1.25));
            alpha_batch.circle(cx, cy, g * 0.38, linear_rgba_f(bright, f, 1.35));
            add_batch.circle(cx, cy, g * 0.16, linear_rgba_f(core_white, f, 2.0));
        }
        "magnet" => {
            // Horseshoe U-magnet opening downward
            alpha_batch.arc(cx, cy + g * 0.10, g * 0.52, stroke * 1.25, 0.0, PI, linear_rgba_f(col, f, 1.25));
            alpha_batch.line(cx - g * 0.52, cy + g * 0.10, cx - g * 0.52, cy - g * 0.50, stroke * 1.25, linear_rgba_f(col, f, 1.25));
            alpha_batch.line(cx + g * 0.52, cy + g * 0.10, cx + g * 0.52, cy - g * 0.50, stroke * 1.25, linear_rgba_f(col, f, 1.25));
            add_batch.circle(cx - g * 0.52, cy - g * 0.52, r * 0.14, linear_rgba_f(core_white, f, 1.8));
            add_batch.circle(cx + g * 0.52, cy - g * 0.52, r * 0.14, linear_rgba_f(core_white, f, 1.8));
        }
        "ricochet" => {
            // Reflector bar + zig-zag bounce trajectory
            alpha_batch.line(cx + g * 0.56, cy - g * 0.56, cx + g * 0.56, cy + g * 0.56, stroke * 0.9, linear_rgba_f(bright, f, 1.3));
            add_batch.line(cx - g * 0.58, cy - g * 0.46, cx + g * 0.46, cy + g * 0.06, stroke * 0.9, linear_rgba_f(col, f, 1.5));
            add_batch.line(cx + g * 0.46, cy + g * 0.06, cx - g * 0.48, cy + g * 0.56, stroke * 0.9, linear_rgba_f(core_white, f, 1.8));
            add_batch.circle(cx + g * 0.46, cy + g * 0.06, r * 0.13, linear_rgba_f(core_white, f, 2.0));
        }
        "homing" => {
            alpha_batch.ring(cx, cy, g * 0.62, g * 0.62, stroke * 0.78, linear_rgba_f(col, f, 1.3));
            for a in [0.0, FRAC_PI_2, PI, 3.0 * FRAC_PI_2] {
                let (ca, sa) = (a.cos(), a.sin());
                alpha_batch.line(cx + ca * g * 0.42, cy + sa * g * 0.42, cx + ca * g * 0.80, cy + sa * g * 0.80, stroke * 0.78, linear_rgba_f(bright, f, 1.4));
            }
            add_batch.circle(cx, cy, g * 0.20, linear_rgba_f(core_white, f, 1.95));
        }
        "chain" => {
            let p0 = [cx + g * 0.16, cy + g * 0.78];
            let p1 = [cx - g * 0.34, cy + g * 0.08];
            let p2 = [cx + g * 0.18, cy - g * 0.02];
            let p3 = [cx - g * 0.16, cy - g * 0.78];
            add_batch.line(p0[0], p0[1], p1[0], p1[1], stroke * 1.15, linear_rgba_f(col, f, 1.6));
            add_batch.line(p1[0], p1[1], p2[0], p2[1], stroke * 1.15, linear_rgba_f(core_white, f, 2.0));
            add_batch.line(p2[0], p2[1], p3[0], p3[1], stroke * 1.15, linear_rgba_f(col, f, 1.6));
        }
        "repulsor" => {
            let phase = motion_t * 2.2;
            add_batch.circle(cx, cy, g * 0.24, linear_rgba_f(core_white, f, 2.0));
            add_batch.arc(cx, cy, g * 0.48, stroke * 0.8, phase, 2.1, linear_rgba_f(bright, f, 1.6));
            add_batch.arc(cx, cy, g * 0.48, stroke * 0.8, phase + PI, 2.1, linear_rgba_f(bright, f, 1.6));
            alpha_batch.arc(cx, cy, g * 0.76, stroke * 0.75, -phase, 1.8, linear_rgba_f(col, f, 1.4));
            alpha_batch.arc(cx, cy, g * 0.76, stroke * 0.75, -phase + PI, 1.8, linear_rgba_f(col, f, 1.4));
        }
        "laser" => {
            add_batch.line(cx - g * 0.76, cy - g * 0.48, cx + g * 0.76, cy + g * 0.48, stroke * 1.35, linear_rgba_f(col, f, 1.65));
            add_batch.line(cx - g * 0.76, cy - g * 0.48, cx + g * 0.76, cy + g * 0.48, stroke * 0.55, linear_rgba_f(core_white, f, 2.2));
            add_batch.circle(cx, cy, g * 0.22, linear_rgba_f(core_white, f, 2.0));
        }
        "vortex" => {
            let spin = motion_t * 3.0;
            for arm in 0..3 {
                let a = spin + arm as f32 * (TAU / 3.0);
                add_batch.arc(cx + a.cos() * g * 0.18, cy + a.sin() * g * 0.18, g * 0.52, stroke * 0.85, a, 2.25, linear_rgba_f(bright, f, 1.65));
            }
            alpha_batch.circle(cx, cy, g * 0.24, linear_rgba_f([8, 4, 18], f, 1.0));
            add_batch.ring(cx, cy, g * 0.26, g * 0.26, stroke * 0.65, linear_rgba_f(core_white, f, 2.0));
        }
        "time_slow" => {
            // Chrono hourglass
            alpha_batch.triangle([cx - g * 0.52, cy + g * 0.66], [cx + g * 0.52, cy + g * 0.66], [cx, cy], linear_rgba_f(col, 0.88 * f, 1.3));
            alpha_batch.triangle([cx - g * 0.52, cy - g * 0.66], [cx + g * 0.52, cy - g * 0.66], [cx, cy], linear_rgba_f(bright, 0.92 * f, 1.45));
            alpha_batch.line(cx - g * 0.58, cy + g * 0.68, cx + g * 0.58, cy + g * 0.68, stroke * 0.9, linear_rgba_f(core_white, f, 1.6));
            alpha_batch.line(cx - g * 0.58, cy - g * 0.68, cx + g * 0.58, cy - g * 0.68, stroke * 0.9, linear_rgba_f(core_white, f, 1.6));
            add_batch.circle(cx, cy, r * 0.11, linear_rgba_f(core_white, f, 2.0));
        }
        "ultra" => {
            // 4-point supernova burst
            for rot in [0.0, FRAC_PI_2] {
                let d1 = rot;
                let d2 = rot + FRAC_PI_2;
                alpha_batch.quad(
                    [cx + d1.cos() * g * 0.92, cy + d1.sin() * g * 0.92],
                    [cx + d2.cos() * g * 0.24, cy + d2.sin() * g * 0.24],
                    [cx - d1.cos() * g * 0.92, cy - d1.sin() * g * 0.92],
                    [cx - d2.cos() * g * 0.24, cy - d2.sin() * g * 0.24],
                    linear_rgba_f(bright, f, 1.6),
                );
            }
            add_batch.circle(cx, cy, g * 0.28, linear_rgba_f(core_white, f, 2.3));
        }
        _ => {
            alpha_batch.circle(cx, cy, g * 0.45, linear_rgba_f(col, f, 1.25));
            add_batch.circle(cx, cy, g * 0.20, linear_rgba_f(core_white, f, 1.8));
        }
    }
}

/// Renders a hovering world powerup pod with grounded shadow, tier beacon halo, magnet streak,
/// shared vector emblem, and crisp hover tag.
#[allow(clippy::too_many_arguments)]
pub fn draw_powerup_pickup(
    pos: Vec2,
    kind: &str,
    ttl: f32,
    col: [u8; 3],
    player_pos: Vec2,
    cam_world: Vec2,
    view_w: f32,
    view_h: f32,
    shake: Vec2,
    motion_t: f32,
    enable_edges: bool,
    enable_glow: bool,
    alpha_batch: &mut SdfBatch,
    add_batch: &mut SdfBatch,
    ui_text: &mut TextBatch,
    ui_scale: f32,
) {
    let meta = powerup_meta(kind);
    let rare = is_rare_powerup(kind);
    let fade = if ttl < 3.0 {
        0.48 + 0.52 * (motion_t * 14.0).sin()
    } else {
        1.0
    };
    let phase = pos.x * 0.04 + pos.y * 0.03;
    let bob = (motion_t * 3.8 + phase).sin() * 3.5;
    let (sx, sy_floor) = to_iso_cam(pos, cam_world, view_w, view_h, shake);
    let sy = sy_floor + 11.0 + bob;

    // Grounded elliptical shadow + iso floor beacon
    let ground_rx = if rare { 21.0 } else { 15.0 };
    let ground_ry = ground_rx * (ISO_SCALE_Y / ISO_SCALE_X);
    alpha_batch.ellipse(sx, sy_floor - 1.0, ground_rx * 0.85, ground_ry * 0.72, 0.0, linear_rgba_f([0, 0, 0], 0.45 * fade, 1.0));
    if enable_edges {
        let pulse = 0.55 + 0.45 * (motion_t * 4.5 + phase).sin();
        add_batch.ring(sx, sy_floor, ground_rx * (1.0 + 0.14 * pulse), ground_ry * (1.0 + 0.14 * pulse), if rare { 2.4 } else { 1.6 }, linear_rgba_f(col, (0.42 + 0.25 * pulse) * fade, 1.55));
        add_batch.line(sx, sy_floor, sx, sy, 1.6, linear_rgba_f(col, 0.45 * fade, 1.5));
    }

    // Magnet pull energy thread toward player when close
    let dist_player = (player_pos - pos).length();
    if dist_player < 210.0 && dist_player > 18.0 {
        let (px, py) = to_iso_cam(player_pos, cam_world, view_w, view_h, shake);
        let intensity = ((210.0 - dist_player) / 192.0).clamp(0.0, 1.0);
        add_batch.line(sx, sy, px, py + 6.0, 1.6 * intensity + 0.8, linear_rgba_f(col, 0.35 * intensity * fade, 1.55));
    }

    let pod_r = match meta.tier {
        PowerupTier::Rare => 14.5,
        PowerupTier::Tactical => 13.0,
        PowerupTier::Core => 12.0,
    };
    if enable_glow {
        add_batch.glow(sx, sy, pod_r * 2.1, 1.85, linear_rgba_f(col, if rare { 0.46 * fade } else { 0.30 * fade }, 1.65));
    }

    draw_powerup_emblem(kind, sx, sy, pod_r, col, fade, motion_t, alpha_batch, add_batch);

    if enable_edges && (rare || dist_player < 160.0) {
        ui_text.draw(
            meta.short_code,
            FontId::Bold,
            (9.5 * ui_scale).clamp(8.5, 12.5),
            sx,
            sy + pod_r + 9.0,
            AlignX::Center,
            AlignY::Bottom,
            mix_rgb(col, [255, 255, 255], 0.55),
            ((if rare { 235.0 } else { 195.0 }) * fade) as u8,
            true,
        );
    }
}

fn regular_poly(cx: f32, cy: f32, r: f32, sides: usize, rot: f32) -> Vec<[f32; 2]> {
    let mut pts = Vec::with_capacity(sides);
    for i in 0..sides {
        let a = rot + (i as f32 / sides as f32) * TAU;
        pts.push([cx + a.cos() * r, cy + a.sin() * r]);
    }
    pts
}
