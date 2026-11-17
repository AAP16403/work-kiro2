//! Forge Warden: toothed back gear, furnace chest, visor, and two cannon
//! gauntlets with hook claws. Authored pre-turn (front on -Y), then `turn`ed to +X forward.
use std::f32::consts::TAU;
use super::super::geom::*;
use crate::sim::enemy::{Enemy, EnemySubState};

const AXIS_Y: usize = 1;
const GEAR_Y: f32 = 24.0;
const GEAR_Z: f32 = 8.0;
const POD: V3 = V3::new(9.0, 8.0, 8.0);
const MUZZLE_Y: f32 = -9.0;
const MUZZLES: [(f32, f32); 4] = [(-3.0, 2.0), (-1.0, -2.0), (1.0, -2.0), (3.0, 2.0)];
const CHEST: &[(f32, f32)] = &[
    (-18.0, 27.0), (-23.0, 17.0), (-24.0, -8.0), (-17.0, -20.0), (-11.0, -25.0), (11.0, -25.0),
    (17.0, -20.0), (24.0, -8.0), (23.0, 17.0), (18.0, 27.0), (10.0, 32.0), (-10.0, 32.0),
];
const VISOR: &[(f32, f32)] = &[
    (-10.0, 39.0), (-8.0, 44.0), (-4.5, 46.0), (0.0, 42.5), (4.5, 46.0), (8.0, 44.0), (10.0, 39.0), (7.0, 34.0), (-7.0, 34.0),
];
const WAIST: &[(f32, f32)] = &[(-13.0, -14.0), (-10.0, -25.0), (-6.0, -29.0), (6.0, -29.0), (10.0, -25.0), (13.0, -14.0)];

/// Quarter turn about +Z, (x,y,z) -> (-y,x,z): a proper rotation, so winding holds.
fn turn(mesh: &mut Mesh) {
    let t = |v: V3| V3::new(-v.y, v.x, v.z);
    for f in mesh.faces.iter_mut() { (f.a, f.b, f.c) = (t(f.a), t(f.b), t(f.c)); }
}

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    // Back gear: bronze wheel in the rear plane, braced to the top of the torso.
    mesh.torus(V3::new(0.0, GEAR_Y, GEAR_Z), 39.0, 3.8, 20, 8, AXIS_Y, Material::Shell);
    mesh.torus(V3::new(0.0, GEAR_Y, GEAR_Z), 35.0, 1.7, 20, 7, AXIS_Y, Material::Accent);
    tapered_rod(&mut mesh, V3::new(0.0, 12.0, GEAR_Z), V3::new(0.0, GEAR_Y, GEAR_Z + 37.0), 3.5, 2.5, 8, Material::Dark);
    for i in 0..8 {
        let (sa, ca) = (i as f32 * (TAU / 8.0)).sin_cos();
        let root = V3::new(ca * 37.0, GEAR_Y, GEAR_Z + sa * 37.0);
        let tooth = V3::new(ca * 47.0, GEAR_Y, GEAR_Z + sa * 47.0);
        tapered_rod(&mut mesh, root, tooth, 5.0, 3.0, 8, Material::ShellLight);
        mesh.ellipsoid(tooth, V3::new(2.8, 2.8, 2.8), 6, 4, Material::Glow);
    }
    mesh.ellipsoid(V3::new(0.0, 0.0, 3.0), V3::new(22.5, 13.0, 26.0), 18, 12, Material::Shell);
    extruded_xz_plate(&mut mesh, CHEST, 10.0, -13.5, Material::ShellLight, Material::Shell, Material::Dark);

    // Visor with amber eyes on the forward face, and a short crest.
    mesh.ellipsoid(V3::new(0.0, -0.5, 38.0), V3::new(12.0, 10.0, 13.0), 16, 10, Material::ShellLight);
    extruded_xz_plate(&mut mesh, VISOR, -7.0, -11.2, Material::Dark, Material::Dark, Material::Accent);
    for side in [-1.0_f32, 1.0] { mesh.ellipsoid(V3::new(side * 4.2, -12.0, 39.5), V3::new(2.3, 1.2, 2.0), 10, 7, Material::Glow); }
    tapered_rod(&mut mesh, V3::new(0.0, -11.2, 47.0), V3::new(0.0, -8.5, 53.5), 4.5, 0.55, 8, Material::Accent);

    // Nested rings, recessed furnace core, grate bars (biased back into the ring).
    mesh.torus(V3::new(0.0, -13.8, 5.0), 12.8, 2.8, 18, 7, AXIS_Y, Material::Accent);
    mesh.torus(V3::new(0.0, -14.8, 5.0), 9.8, 1.15, 16, 6, AXIS_Y, Material::ShellLight);
    let f_start = mesh.faces.len();
    mesh.ellipsoid(V3::new(0.0, -15.0, 5.0), V3::new(8.3, 2.0, 10.0), 16, 10, Material::Core);
    for bar in [-4.0_f32, 0.0, 4.0] { tapered_rod(&mut mesh, V3::new(bar, -17.2, -2.5), V3::new(bar, -17.2, 12.5), 0.72, 0.72, 7, Material::Dark); }
    mesh.with_bias(f_start, -4.5);

    for side in [-1.0_f32, 1.0] {
        tapered_rod(&mut mesh, V3::new(side * 16.0, -14.4, 15.0), V3::new(side * 11.0, -14.4, 20.0), 1.1, 0.55, 7, Material::Glow);
        mesh.ellipsoid(V3::new(side * 21.0, -2.0, 18.0), V3::new(10.5, 11.0, 12.0), 12, 8, Material::ShellLight);
        mesh.torus(V3::new(side * 22.0, -3.0, 18.0), 7.4, 1.25, 14, 6, AXIS_Y, Material::Accent);
        // Shoulder pod: the arm hinges here and never moves, so it is static.
        let shoulder = V3::new(side * 18.0, -2.0, 17.0);
        mesh.ellipsoid(shoulder, POD, 12, 8, Material::Dark);
        mesh.torus(shoulder + V3::new(0.0, -1.0, 0.0), 6.6, 1.25, 14, 6, AXIS_Y, Material::Accent);
    }

    // Reinforced waist with two glowing coolant pipes toward the hips.
    mesh.ellipsoid(V3::new(0.0, 0.0, -19.0), V3::new(15.0, 11.0, 9.5), 14, 9, Material::Dark);
    extruded_xz_plate(&mut mesh, WAIST, 8.0, -8.0, Material::ShellLight, Material::Shell, Material::Dark);
    for side in [-1.0_f32, 1.0] { tapered_rod(&mut mesh, V3::new(side * 4.0, -10.0, -21.0), V3::new(side * 9.0, -8.0, -23.0), 1.6, 1.6, 7, Material::Glow); }
    turn(&mut mesh);
    mesh
}

/// Articulated (pose-driven) parts, in the same pre-turn frame as `build_mesh`.
pub(crate) fn animated_parts(e: &Enemy, time: f32, windup: f32, reduce_motion: bool) -> Mesh {
    let mut mesh = Mesh::default();
    let calm = |v: f32| if reduce_motion { 0.0 } else { v };
    // Load rises only inside the spike-array telegraph (smoothstep, full by 85% of the tell).
    let load = if e.ai.sub_state == EnemySubState::TrapmasterTelegraph { let w = (windup / 0.85).clamp(0.0, 1.0); w * w * (3.0 - 2.0 * w) } else { 0.0 };
    for side in [-1.0_f32, 1.0] {
        let swing = calm((time * 2.4 + e.seed).sin() * 2.0);
        let shoulder = V3::new(side * 18.0, -2.0, 17.0);
        let elbow = V3::new(side * (27.0 + swing), -5.0, 11.0 + load * 2.0);
        let wrist = V3::new(side * (40.0 + load * 9.0), -8.0, -8.0 + load * 3.0);
        tapered_rod(&mut mesh, shoulder, elbow, 5.5, 4.4, 9, Material::ShellLight);
        // Glowing hydraulic tube down the front face of the upper arm.
        let tube = V3::new(0.0, -5.0, 0.0);
        tapered_rod(&mut mesh, shoulder + (elbow - shoulder) * 0.2 + tube, shoulder + (elbow - shoulder) * 0.85 + tube, 1.4, 1.4, 7, Material::Glow);
        mesh.ellipsoid(elbow, V3::new(5.4, 5.0, 5.0), 10, 7, Material::Dark);
        tapered_rod(&mut mesh, elbow, wrist, 4.6, 3.4, 9, Material::ShellLight);
        mesh.ellipsoid(wrist, POD, 12, 8, Material::ShellLight);
        mesh.torus(wrist + V3::new(0.0, -6.0, 0.0), 6.1, 1.3, 14, 6, AXIS_Y, Material::Accent);
        // Four glowing muzzles housed in the gauntlet; they protrude under load.
        for (dx, dz) in MUZZLES {
            let m = V3::new(wrist.x + dx, MUZZLE_Y - load * 2.5, wrist.z + dz);
            tapered_rod(&mut mesh, m + V3::new(0.0, 8.0, 0.0), m + V3::new(0.0, -7.0, 0.0), 2.2 + load * 0.8, 1.8 + load * 0.5, 8, Material::Glow);
        }
        // Three curled two-segment hook claws that open outward during the windup.
        for finger in [-1.0_f32, 0.0, 1.0] {
            let start = wrist + V3::new(side * finger * 3.8, -7.0, finger * 2.8);
            let spread = finger * (4.6 + load * 1.5);
            let mid = wrist + V3::new(side * (7.0 + load * 2.0), -9.0, spread);
            let tip = wrist + V3::new(side * (9.0 + load * 4.0), -8.0, spread - 4.5);
            tapered_rod(&mut mesh, start, mid, 2.4, 1.9, 8, Material::Accent);
            tapered_rod(&mut mesh, mid, tip, 1.9, 0.5, 7, Material::Accent);
            mesh.ellipsoid(tip, V3::new(1.0, 1.0, 1.0), 6, 4, Material::Accent);
        }
        // Legs stride along pre-turn y, which becomes forward +X.
        let hip = V3::new(side * 12.0, 0.0, -19.0);
        let stride = calm((time * 5.0 + side).sin() * 2.4);
        let knee = V3::new(side * 20.0, stride * 0.4, -30.0);
        let foot = V3::new(side * 26.0, stride, -42.0);
        tapered_rod(&mut mesh, hip, knee, 6.0, 4.7, 8, Material::Dark);
        mesh.ellipsoid(knee, V3::new(5.2, 5.4, 4.6), 10, 7, Material::Accent);
        tapered_rod(&mut mesh, knee, foot, 4.7, 3.4, 8, Material::ShellLight);
        mesh.ellipsoid(foot, V3::new(9.0, 8.5, 4.0), 10, 7, Material::Dark);
    }
    turn(&mut mesh);
    mesh
}
