//! Boss swarm queen (Brood Matriarch, `boss-brood-matriarch.png`): armored insect body,
//! heart cuirass, crown, flapping wings, forearms and a long-legged gait.
//! `build_mesh` is the static sculpt; `animated_parts` holds the pose-driven limbs.
//! Head and chest face +X; the sculpt rotates with her world-space body.

use super::super::geom::*;
use crate::sim::enemy::{Enemy, EnemySubState};

// Telegraph gains (wing flap in radians, forearm/guard in units); windup fraction at full pose.
const BROOD_FLAP: (f32, f32) = (0.08, 0.5);
const SWARM_FLAP: (f32, f32) = (-0.12, 0.52);
const VOLLEY_FLAP_GAIN: f32 = 0.38;
const BROOD_RAISE: f32 = 7.0;
const SWARM_SPREAD: f32 = 6.0;
const VOLLEY_GUARD: f32 = 4.5;
const TELL_HOLD: f32 = 0.85;

// Idle, beat, gait and tremor rates/amplitudes.
const WAVE: (f32, f32) = (2.4, 0.12);
const FLUTTER: (f32, f32) = (5.8, 0.08);
const BEAT: (f32, f32) = (9.0, 0.10);
const GAIT: (f32, f32) = (5.6, 2.6);
const TREMOR: (f32, f32) = (38.0, 0.35);

// Wing outline in (spread, height) wing-local coordinates; hinge on the shoulder line.
const WING_HALF_DEPTH: f32 = 3.6;
const WING_HINGE: (f32, f32, f32) = (-1.5, 12.0, 20.0);
const WING_SPREAD_SCALE: f32 = 1.20;
const WING_OUTLINE: [(f32, f32); 17] = [
    (12.0, 20.0), (20.0, 37.0), (39.0, 50.0), (56.0, 52.0), (67.0, 44.0), (56.0, 38.0), (63.0, 30.0),
    (57.0, 19.0), (56.0, 7.0), (50.0, -8.0), (44.0, -23.0), (39.0, -38.0), (36.0, -53.0), (32.0, -40.0),
    (30.0, -18.0), (24.0, -2.0), (17.0, 10.0),
];

// Legs: (root x, root z, foot span). Feet reach ~0.65 of the wing-tip half-span.
const LEG_PAIRS: [(f32, f32, f32); 3] = [(-2.0, 5.0, 36.0), (-7.0, -9.0, 46.0), (-13.0, -22.0, 40.0)];

// Heart core, eyes and socket scale, shared by the static sculpt and the telegraph swell.
const CORE_CENTER: V3 = V3::new(18.4, 0.0, 12.3);
const CORE_RADII: V3 = V3::new(2.6, 5.5, 7.0);
const EYE_X: f32 = 21.1;
const EYE_Y: f32 = 3.4;
const EYE_Z: f32 = 31.0;
const EYE_RADII: V3 = V3::new(1.1, 1.5, 1.7);

const HEART: [(f32, f32); 12] = [
    (0.0, 18.0), (5.5, 22.0), (10.0, 20.0), (13.0, 15.0), (12.0, 10.0), (8.0, 5.0),
    (0.0, -3.5), (-8.0, 5.0), (-12.0, 10.0), (-13.0, 15.0), (-10.0, 20.0), (-5.5, 22.0),
];
const MASK: [(f32, f32); 8] = [
    (0.0, 38.5), (5.6, 35.5), (7.0, 30.0), (4.4, 25.0), (0.0, 21.8), (-4.4, 25.0), (-7.0, 30.0), (-5.6, 35.5),
];
const JAW: [(f32, f32); 6] = [(0.0, 28.0), (4.3, 26.0), (4.0, 22.0), (0.0, 17.5), (-4.0, 22.0), (-4.3, 26.0)];

/// Belly plates as forward domes: (z, half width, half height, rim x, tip x, rib x).
const BELLY: [(f32, f32, f32, f32, f32, f32); 4] = [
    (-1.0, 14.0, 8.6, 3.0, 16.9, 13.0),
    (-13.0, 13.2, 8.4, 3.0, 17.9, 13.7),
    (-25.0, 11.0, 7.4, 3.0, 14.9, 11.7),
    (-35.0, 8.0, 6.2, 0.0, 7.5, 5.6),
];

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    mesh.ellipsoid(V3::new(-2.0, 0.0, -10.0), V3::new(18.5, 15.0, 27.0), 20, 14, Material::Shell);
    mesh.ellipsoid(V3::new(-4.5, 0.0, -25.0), V3::new(13.5, 14.5, 16.0), 18, 12, Material::Dark);
    mesh.ellipsoid(V3::new(1.5, 0.0, 11.0), V3::new(12.5, 11.0, 17.0), 18, 12, Material::ShellLight);
    mesh.ellipsoid(V3::new(2.0, 0.0, 19.5), V3::new(12.5, 10.5, 6.2), 16, 10, Material::Shell);
    mesh.ellipsoid(V3::new(7.0, 0.0, 29.0), V3::new(9.5, 7.4, 10.0), 16, 11, Material::Dark);

    // Belly plates: domes that stand proud of the abdomen, each with a gold rib.
    for (i, &(z, hw, hh, rim_x, tip_x, rib_x)) in BELLY.iter().enumerate() {
        let material = if i % 2 == 0 { Material::ShellLight } else { Material::Shell };
        append_ellipsoid_cap_x(&mut mesh, V3::new(rim_x, 0.0, z), V3::new(tip_x - rim_x, hw, hh), 14, 6, material);
        for side in [-1.0_f32, 1.0] {
            let rib_top = V3::new(rib_x, side * hw * 0.72, z + hh * 0.35);
            tapered_rod(&mut mesh, rib_top, V3::new(rib_x, 0.0, z - hh * 0.62), 1.15, 0.35, 7, Material::Accent);
        }
    }

    // Heart cuirass and glowing core.
    mesh.torus(V3::new(13.0, 0.0, 10.0), 8.6, 1.4, 16, 6, 0, Material::Accent);
    let heart_start = mesh.faces.len();
    extruded_yz_plate(&mut mesh, &HEART, 14.0, 17.6, Material::Glow, Material::Accent);
    mesh.ellipsoid(CORE_CENTER, CORE_RADII, 12, 8, Material::Core);
    mesh.with_bias(heart_start, -3.5);

    // Crystal nodes hang from armored shoulder rails; fixed limb roots go here too.
    for side in [-1.0_f32, 1.0] {
        for (y, z, root_z) in [(side * 15.5, 18.0, 15.0), (side * 19.0, 1.0, 8.0)] {
            let socket = V3::new(7.0, y * 0.82, z);
            tapered_rod(&mut mesh, V3::new(5.0, side * 10.5, root_z), socket, 2.4, 1.4, 8, Material::ShellLight);
            mesh.ellipsoid(socket, V3::new(3.4, 3.4, 4.3), 8, 5, Material::Dark);
            mesh.ellipsoid(socket + V3::new(1.2, 0.0, 0.0), V3::new(2.6, 2.6, 3.5), 8, 5, Material::Glow);
        }
        let shoulder = V3::new(1.0, side * 11.0, 19.0);
        mesh.ellipsoid(shoulder, V3::new(8.0, 7.3, 7.2), 12, 8, Material::Dark);
        mesh.torus_x(shoulder + V3::new(0.0, side, 0.0), 5.5, 1.15, Material::Accent);
        mesh.ellipsoid(arm_root(side), V3::new(5.0, 4.6, 4.8), 10, 7, Material::Dark);
        for (x, z, _) in LEG_PAIRS {
            mesh.ellipsoid(leg_root(x, z, side), V3::new(4.0, 4.0, 3.5), 10, 7, Material::Dark);
        }
    }

    // Neck, narrow face, paired eyes, jaw, and the crown.
    mesh.ellipsoid(V3::new(8.0, 0.0, 28.0), V3::new(7.5, 6.0, 11.0), 14, 10, Material::Shell);
    let face_start = mesh.faces.len();
    extruded_yz_plate(&mut mesh, &MASK, 15.0, 18.8, Material::ShellLight, Material::Dark);
    for side in [-1.0_f32, 1.0] {
        mesh.ellipsoid(V3::new(19.8, side * EYE_Y, EYE_Z), V3::new(2.0, 2.6, 2.8), 8, 6, Material::Glow);
        mesh.ellipsoid(V3::new(EYE_X, side * EYE_Y, EYE_Z), EYE_RADII, 6, 4, Material::Eye);
        tapered_rod(&mut mesh, V3::new(18.5, side * 6.5, 34.0), V3::new(20.8, side * 3.0, 32.7), 2.2, 1.0, 8, Material::Accent);
    }
    extruded_yz_plate(&mut mesh, &JAW, 13.5, 20.6, Material::Dark, Material::Accent);
    mesh.with_bias(face_start, -4.0);
    tapered_rod(&mut mesh, V3::new(13.4, 0.0, 34.5), V3::new(15.2, 0.0, 54.0), 2.6, 0.42, 9, Material::Accent);
    tapered_rod(&mut mesh, V3::new(14.4, 0.0, 45.0), V3::new(20.0, 0.0, 49.0), 2.5, 0.35, 8, Material::ShellLight);
    for side in [-1.0_f32, 1.0] {
        tapered_rod(&mut mesh, V3::new(12.4, side * 3.0, 35.0), V3::new(14.0, side * 8.0, 48.0), 2.8, 0.38, 8, Material::ShellLight);
        tapered_rod(&mut mesh, V3::new(14.0, side * 8.0, 48.0), V3::new(17.0, side * 12.5, 57.0), 1.4, 0.25, 8, Material::Accent);
    }
    crystal_yz(&mut mesh, V3::new(17.3, 0.0, 43.0), 4.4, 7.0, 3.2, 1.0, Material::Glow, Material::Eye);
    mesh
}

fn arm_root(side: f32) -> V3 {
    V3::new(7.0, side * 9.0, 14.0)
}

fn leg_root(x: f32, z: f32, side: f32) -> V3 {
    V3::new(x, side * 7.0, z)
}

/// Articulated (pose-driven) parts: wings, forearms, legs, and the telegraph swell.
pub(crate) fn animated_parts(e: &Enemy, time: f32, windup: f32, reduce_motion: bool) -> Mesh {
    let mut mesh = Mesh::default();
    let calm = |amp: f32| if reduce_motion { 0.0 } else { amp };
    let wave = calm((time * WAVE.0 + e.seed).sin() * WAVE.1);
    let flutter = calm((time * FLUTTER.0 + e.seed).cos() * FLUTTER.1);
    // The telegraph eases in and holds at full strength for the last part of the windup.
    let tell = {
        let x = (windup / TELL_HOLD).clamp(0.0, 1.0);
        1.0 - (1.0 - x) * (1.0 - x)
    };
    let (flap_tell, raise, spread, guard) = match e.ai.sub_state {
        EnemySubState::QueenBroodTelegraph => (BROOD_FLAP.0 + tell * BROOD_FLAP.1, tell * BROOD_RAISE, 0.0, 0.0),
        EnemySubState::QueenSwarmTelegraph => (SWARM_FLAP.0 - tell * SWARM_FLAP.1, 0.0, tell * SWARM_SPREAD, 0.0),
        EnemySubState::QueenVolleyTelegraph => (tell * VOLLEY_FLAP_GAIN, 0.0, 0.0, tell * VOLLEY_GUARD),
        _ => (0.0, 0.0, 0.0, 0.0),
    };
    // Movement (sim velocity) drives the wing beat and the stride; both are zero when still.
    let move_frac = calm((e.vel.length() / e.speed.max(1.0)).clamp(0.0, 1.0));
    let beat = calm((time * BEAT.0 + e.seed).sin() * BEAT.1 * move_frac);
    let shake = calm((time * TREMOR.0 + e.seed).sin() * TREMOR.1 * tell * tell);
    let flap = wave + flutter + flap_tell + beat;

    for side in [-1.0_f32, 1.0] {
        let hinge = V3::new(WING_HINGE.0, side * WING_HINGE.1, WING_HINGE.2);
        let wing_outline: Vec<(f32, f32)> = WING_OUTLINE
            .iter()
            .map(|&(spread, height)| {
                (
                    WING_HINGE.1 + (spread - WING_HINGE.1) * WING_SPREAD_SCALE,
                    height,
                )
            })
            .collect();
        append_flap_yz_plate(&mut mesh, &wing_outline, side, hinge, flap, WING_HALF_DEPTH, Material::Core, Material::Shell);
        let (sa, ca) = (flap * side).sin_cos();
        for (y, z) in [(40.0_f32, 36.0_f32), (46.0, -4.0)] {
            let spot = flap_wing_point(hinge, side, sa, ca, 1.8, y, z);
            mesh.ellipsoid(spot, V3::new(0.6, 2.6, 1.8), 8, 6, Material::Glow);
        }

        // Plated forearms reach out to the attack lane, then draw back to guard the heart.
        let shoulder = arm_root(side);
        let elbow = V3::new(10.0 + spread + guard * 0.35, side * (17.0 + spread + guard * 0.45), 8.0 + raise + guard + shake);
        let claw = V3::new(16.0 + spread * 0.5 + guard, side * (22.0 + spread + guard), 6.0 + raise + guard + shake);
        tapered_rod(&mut mesh, shoulder, elbow, 3.6, 2.6, 8, Material::ShellLight);
        mesh.ellipsoid(elbow, V3::new(3.4, 3.3, 3.0), 7, 5, Material::Accent);
        tapered_rod(&mut mesh, elbow, claw, 2.8, 1.6, 8, Material::ShellLight);
        // Hooked blades; they open wider at the peak of the telegraph.
        for pincer in [-1.0_f32, 1.0] {
            let tip = claw + V3::new(6.0, side * pincer * (3.6 + 1.6 * tell), -2.0 + raise * 0.18);
            tapered_rod(&mut mesh, claw, tip, 1.9, 0.3, 7, Material::Accent);
        }
    }

    let gait_amp = GAIT.1 * (0.2 + 0.8 * move_frac);
    let gait = calm((time * (GAIT.0 + 2.0 * move_frac) + e.seed).sin() * gait_amp);
    for (pair, (x, z, span)) in LEG_PAIRS.into_iter().enumerate() {
        for side in [-1.0_f32, 1.0] {
            let phase = if pair % 2 == 0 { gait } else { -gait };
            let stride = phase * side;
            let root = leg_root(x, z, side);
            let knee = V3::new(x - 3.5 + stride * 0.35, side * (span * 0.62), z - 7.0 + stride * 0.22);
            let foot = V3::new(x - 8.0 + stride, side * span, z - 21.0 + stride * 0.2);
            tapered_rod(&mut mesh, root, knee, 4.3, 3.0, 8, Material::ShellLight);
            mesh.ellipsoid(knee, V3::new(3.4, 3.2, 3.2), 7, 5, Material::Accent);
            tapered_rod(&mut mesh, knee, foot, 3.0, 0.34, 8, Material::ShellLight);
        }
    }

    // At the telegraph the heart swells and the eyes flare; the charge reads from the head.
    if tell > 0.0 {
        mesh.ellipsoid(CORE_CENTER, CORE_RADII * (1.0 + 0.3 * tell), 6, 4, Material::Glow);
        for side in [-1.0_f32, 1.0] {
            mesh.ellipsoid(V3::new(EYE_X, side * EYE_Y, EYE_Z), EYE_RADII * (1.0 + 0.6 * tell), 6, 4, Material::Eye);
        }
    }
    mesh
}
