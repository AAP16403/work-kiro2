//! Boss brute (Gorgon Juggernaut): armored quadruped with ivory tusks, nose horn,
//! amber V-visor, shoulder heat vents and twin rear exhaust stacks.

use super::super::geom::*;
use crate::sim::enemy::{Enemy, EnemySubState};

/// Leg columns as (hip x, stride phase); the rear pair strides against the front pair.
const LEG_COLUMNS: [(f32, f32); 2] = [(-19.0, 1.0), (13.0, -1.0)];
const TUSK_RADII: [f32; 5] = [6.0, 5.0, 3.8, 2.3, 0.25];
const TUSK_SEGMENTS: [usize; 4] = [12, 12, 11, 10];

/// Ivory tusk polyline for one side: root, two bends, tip.
fn tusk_points(side: f32) -> [V3; 5] {
    [
        V3::new(15.0, side * 12.5, 7.5),
        V3::new(24.5, side * 20.5, 6.5),
        V3::new(33.5, side * 22.0, 9.5),
        V3::new(37.5, side * 16.5, 14.5),
        V3::new(35.0, side * 10.5, 19.0),
    ]
}

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    // Body hull and segmented armor plate; ground footprint stays inside the 33.6 hitbox.
    mesh.ellipsoid(V3::new(-3.0, 0.0, 1.5), V3::new(28.0, 23.0, 15.0), 22, 14, Material::Shell);
    extruded_plate(&mut mesh, &[
        (25.0, 0.0), (19.0, 13.5), (7.0, 20.0), (-16.0, 20.5), (-29.0, 11.5),
        (-31.0, 0.0), (-29.0, -11.5), (-16.0, -20.5), (7.0, -20.0), (19.0, -13.5),
    ], 2.0, 11.5, Material::ShellLight, Material::Dark);
    mesh.ellipsoid(V3::new(-6.0, 0.0, 13.5), V3::new(15.0, 16.0, 5.5), 18, 10, Material::Dark);

    // Head: brow, armored snout plate under the visor, nose horn with a dark root collar.
    mesh.ellipsoid(V3::new(16.5, 0.0, 11.5), V3::new(12.5, 14.0, 9.5), 18, 12, Material::ShellLight);
    mesh.ellipsoid(V3::new(25.5, 0.0, 9.5), V3::new(4.5, 8.8, 5.8), 16, 10, Material::Dark);
    mesh.ellipsoid(V3::new(24.5, 0.0, 15.8), V3::new(5.2, 9.8, 2.6), 14, 8, Material::Shell);
    mesh.ellipsoid(V3::new(26.0, 0.0, 4.5), V3::new(7.0, 7.5, 6.0), 14, 9, Material::Shell);
    tapered_rod(&mut mesh, V3::new(23.5, 0.0, 11.0), V3::new(36.5, 0.0, 24.0), 5.0, 0.5, 12, Material::ShellLight);
    mesh.ellipsoid(V3::new(24.0, 0.0, 11.5), V3::new(5.5, 5.5, 4.0), 12, 8, Material::Dark);

    for side in [-1.0_f32, 1.0] {
        // Shoulder pauldrons, rear exhaust stacks with glowing caps.
        mesh.ellipsoid(V3::new(3.0, side * 17.0, 9.0), V3::new(12.0, 8.0, 7.5), 14, 9, Material::ShellLight);
        tapered_rod(&mut mesh, V3::new(-19.0, side * 11.0, 9.0), V3::new(-20.5, side * 12.0, 21.0), 4.4, 4.0, 10, Material::Shell);
        mesh.ellipsoid(V3::new(-20.5, side * 12.0, 21.5), V3::new(3.0, 3.0, 1.2), 8, 6, Material::Glow);
    }

    // Ivory tusks, each with a collar ring square to its root axis.
    for side in [-1.0_f32, 1.0] {
        let p = tusk_points(side);
        for i in 0..4 {
            tapered_rod(&mut mesh, p[i], p[i + 1], TUSK_RADII[i], TUSK_RADII[i + 1], TUSK_SEGMENTS[i], Material::Bone);
        }
        let axis = (p[1] - p[0]).normalized();
        mesh.torus_oriented(p[0], 6.4, 1.1, 14, 6, axis, 0.0, Material::Accent);
    }

    // Glowing V-visor with hot core, eye cores and shoulder heat-vent slats (all share the glow bias).
    let f_start = mesh.faces.len();
    for side in [-1.0_f32, 1.0] {
        tapered_rod(&mut mesh, V3::new(28.2, 0.0, 10.2), V3::new(26.8, side * 6.8, 13.4), 2.1, 1.5, 8, Material::Glow);
        tapered_rod(&mut mesh, V3::new(27.9, 0.0, 10.2), V3::new(26.5, side * 6.8, 13.4), 0.9, 0.6, 6, Material::Core);
        mesh.ellipsoid(V3::new(28.1, side * 4.1, 12.2), V3::new(1.2, 1.9, 1.4), 10, 7, Material::Core);
        for k in [-2.4_f32, 0.0, 2.4] {
            mesh.ellipsoid(V3::new(5.0, side * 24.6, 9.5 + k), V3::new(4.5, 1.0, 0.8), 8, 4, Material::Glow);
        }
    }
    mesh.with_bias(f_start, -3.5);
    mesh
}

/// Articulated (pose-driven) parts. Reads only sub_state, rage, seed, time and windup.
pub(crate) fn animated_parts(e: &Enemy, time: f32, windup: f32, reduce_motion: bool) -> Mesh {
    let mut mesh = Mesh::default();
    let state = e.ai.sub_state;
    let charge = state == EnemySubState::BruteCharge;
    let daze = state == EnemySubState::BruteStun;
    // Walking and charging stride, recovering slows, telegraph and daze plant the legs.
    let gait = match state {
        EnemySubState::BruteChase | EnemySubState::BruteCharge => 1.0,
        EnemySubState::BruteRecover => 0.35,
        _ => 0.0,
    };
    let tempo = if e.ai.rage { 1.35 } else { 1.0 };
    let wave = if reduce_motion { 0.0 } else { (time * 2.4 + e.seed).sin() };
    let stride = if reduce_motion { 0.0 } else { (time * 4.4 * tempo + e.seed).sin() * 3.2 * gait };
    let ramp = windup.clamp(0.0, 1.0);
    let droop = if daze { 1.0 } else { 0.0 };

    for side in [-1.0_f32, 1.0] {
        let shoulder = V3::new(-1.0, side * 19.0, 1.0);
        let swing = if daze {
            side * 1.5
        } else if charge {
            side * 4.0
        } else {
            wave * 2.6 * (1.0 - ramp)
        };
        // Telegraph: paws reach forward and down. Daze: arms hang slack.
        let elbow = V3::new(-7.5 + swing + ramp * 4.0, side * 28.0, -3.5 - ramp - droop * 5.0);
        let hand = V3::new(-12.0 + swing * 1.7 + ramp * 9.0, side * (31.5 + droop * 3.0), -8.5 - ramp * 4.0 - droop * 6.5);
        tapered_rod(&mut mesh, shoulder, elbow, 5.8, 4.0, 8, Material::ShellLight);
        mesh.ellipsoid(elbow, V3::new(4.8, 4.8, 3.8), 9, 6, Material::Dark);
        tapered_rod(&mut mesh, elbow, hand, 4.0, 2.6, 8, Material::Dark);
        mesh.ellipsoid(hand, V3::new(5.8, 4.8, 3.2), 9, 6, Material::ShellLight);
    }

    for (x, phase) in LEG_COLUMNS {
        for side in [-1.0_f32, 1.0] {
            let stride_x = stride * side * phase;
            let hip = V3::new(x, side * 13.5, -1.0);
            let knee = V3::new(x - 2.5 + stride_x * 0.4, side * 19.5, -10.5);
            let foot = V3::new(x - 4.0 + stride_x, side * 22.5, -17.5);
            tapered_rod(&mut mesh, hip, knee, 6.4, 4.8, 8, Material::Shell);
            tapered_rod(&mut mesh, knee, foot, 4.8, 3.6, 8, Material::ShellLight);
            mesh.ellipsoid(foot, V3::new(9.5, 9.5, 4.2), 10, 7, Material::Bone);
            for toe in [V3::new(6.0, 0.0, -2.6), V3::new(-1.5, 4.6, -2.6), V3::new(-1.5, -4.6, -2.6)] {
                mesh.ellipsoid(foot + toe, V3::new(3.0, 3.0, 2.4), 6, 4, Material::Bone);
            }
        }
    }
    mesh
}
