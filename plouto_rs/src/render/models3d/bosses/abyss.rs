//! Boss abyss gaze: six curling tentacles flaring from the eye frame.
use std::f32::consts::TAU;

use super::super::geom::*;
use crate::sim::enemy::{Enemy, EnemySubState};

/// Per tendril: root angle in the mesh XZ plane, and tip reach.
const TENDRILS: [(f32, f32); 6] = [(-0.157, 49.0), (0.576, 44.0), (2.566, 44.0), (3.299, 49.0), (4.102, 54.0), (5.428, 54.0)];
const SEGMENTS: usize = 5;
const WINDUP_REACH_LOSS: f32 = 0.2;
const TWIST: f32 = 0.36;
const HOOK: f32 = 0.45;
const TIP_LIFT: f32 = 4.5;

fn joint_radius(j: usize) -> f32 {
    5.0 - 4.15 * j as f32 / SEGMENTS as f32
}

/// Y-axis torus whose faces orient about each tube's own core, not the torus centre.
fn tube_ring(mesh: &mut Mesh, center: V3, radius: f32, tube: f32, major_n: usize, minor_n: usize, material: Material) {
    let at = |major: usize, minor: usize| {
        let (sa, ca) = (TAU * major as f32 / major_n as f32).sin_cos();
        let (sb, cb) = (TAU * minor as f32 / minor_n as f32).sin_cos();
        center + V3::new(ca * (radius + tube * cb), tube * sb, sa * (radius + tube * cb))
    };
    for major in 0..major_n {
        let (sa, ca) = (TAU * (major as f32 + 0.5) / major_n as f32).sin_cos();
        let core = center + V3::new(ca * radius, 0.0, sa * radius);
        for minor in 0..minor_n {
            let (a, b) = (at(major, minor), at(major, minor + 1));
            let (c, d) = (at(major + 1, minor + 1), at(major + 1, minor));
            mesh.outward_tri(a, b, c, core, material);
            mesh.outward_tri(a, c, d, core, material);
        }
    }
}

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    // Ocular Abyss (`boss-ocular-abyss.png`): purple eye mask, cyan iris slit, six tendril sockets.
    mesh.ellipsoid(V3::new(0.0, 0.0, 0.0), V3::new(23.0, 10.5, 17.0), 20, 13, Material::Shell);
    tube_ring(&mut mesh, V3::new(0.0, -7.8, 0.0), 20.0, 2.8, 20, 8, Material::Dark);
    tube_ring(&mut mesh, V3::new(0.0, -8.6, 0.0), 17.6, 1.65, 18, 7, Material::Accent);

    // Brow outline in (x, z); the jaw is its mirror in z.
    let brow: [(f32, f32); 12] = [
        (-23.0, 9.0), (-18.0, 13.5), (-10.0, 16.0), (0.0, 28.0), (10.0, 16.0), (18.0, 13.5),
        (23.0, 9.0), (17.0, 8.0), (9.0, 11.0), (0.0, 12.5), (-9.0, 11.0), (-17.0, 8.0),
    ];
    let jaw = brow.map(|(x, z)| (x, -z));
    for side in [-1.0_f32, 1.0] {
        for outline in [&brow[..], &jaw[..]] {
            extruded_xz_plate(&mut mesh, outline, side * 6.2, side * 10.1, Material::ShellLight, Material::Shell, Material::Dark);
        }
    }

    // Raised eye layers sit on the forward (-Y) face so the iris turns with the mask.
    let f_start = mesh.faces.len();
    mesh.ellipsoid(V3::new(0.0, -9.4, 0.0), V3::new(15.3, 2.8, 10.8), 14, 8, Material::Bone);
    tube_ring(&mut mesh, V3::new(0.0, -11.4, 0.0), 9.4, 1.0, 14, 6, Material::Accent);
    mesh.ellipsoid(V3::new(0.0, -11.8, 0.0), V3::new(9.6, 1.9, 10.0), 14, 8, Material::Core);
    mesh.ellipsoid(V3::new(0.0, -13.5, 0.0), V3::new(1.5, 1.0, 6.9), 8, 6, Material::Dark);
    mesh.ellipsoid(V3::new(-3.2, -13.2, 3.4), V3::new(1.35, 0.8, 1.7), 8, 5, Material::Eye);
    for (sx, sz) in [(-1.0_f32, -1.0_f32), (-1.0, 1.0), (1.0, -1.0), (1.0, 1.0)] {
        mesh.ellipsoid(V3::new(sx * 11.2, -10.2, sz * 6.6), V3::new(0.7, 0.45, 1.8), 8, 6, Material::Glow);
    }
    mesh.with_bias(f_start, -6.0);

    // Crown gems and the four swept mask horns, each with a cyan tip.
    for z in [25.0_f32, -25.0] {
        crystal_xz(&mut mesh, V3::new(0.0, -10.5, z), 4.8, 7.0, 2.6, -1.0, 0.0, Material::Glow, Material::Eye);
    }
    for (side, sz) in [(-1.0_f32, -1.0_f32), (-1.0, 1.0), (1.0, -1.0), (1.0, 1.0)] {
        let start = V3::new(side * 13.0, -6.0, sz * 12.0);
        let end = V3::new(side * 25.0, -3.0, sz * 21.0);
        tapered_rod(&mut mesh, start, end, 4.1, 0.38, 7, Material::ShellLight);
        tapered_rod(&mut mesh, start + (end - start) * 0.72, end, 1.5, 0.38, 6, Material::Accent);
    }
    mesh
}

/// Articulated (pose-driven) parts for this boss.
pub(crate) fn animated_parts(e: &Enemy, time: f32, windup: f32, reduce_motion: bool) -> Mesh {
    let mut mesh = Mesh::default();
    // `coil` is the telegraph charge, zero outside AbyssTelegraph (no false pre-tell coil).
    let coil = if e.ai.sub_state == EnemySubState::AbyssTelegraph { windup.clamp(0.0, 1.0) } else { 0.0 };
    for (i, &(base, reach)) in TENDRILS.iter().enumerate() {
        // Static hook (kept under reduce_motion): tips roll toward the nearest horizontal axis.
        let hook_sign = -(base.sin() * base.cos()).signum();
        let twist_sign = if i % 2 == 0 { 1.0 } else { -1.0 };
        let mut prev = V3::new(base.cos() * 18.0, -8.0, base.sin() * 16.0);
        for seg in 1..=SEGMENTS {
            let t = seg as f32 / SEGMENTS as f32;
            let (curl, bob) = if reduce_motion {
                (0.0, 0.0)
            } else {
                (
                    (time * 1.3 + e.seed + i as f32 * 1.07 + seg as f32 * 0.74).sin() * (0.16 + 0.48 * t),
                    (time * 1.55 + e.seed + i as f32).sin() * (3.0 + 7.0 * t),
                )
            };
            let angle = base + curl + hook_sign * HOOK * t * t * t + twist_sign * coil * TWIST * t;
            let radius = 19.0 + t * (reach - 19.0) * (1.0 - WINDUP_REACH_LOSS * coil);
            let next = V3::new(angle.cos() * radius, -8.0 - coil * TIP_LIFT * t * t + bob, angle.sin() * radius);
            let (r0, r1) = (joint_radius(seg - 1), joint_radius(seg));
            tapered_rod(&mut mesh, prev, next, r0, r1, 7, Material::ShellLight);
            // Magenta filament on the forward (-Y) side, so it protrudes from the shell.
            if seg >= 2 {
                let k = 0.4 + 0.15 * coil;
                let (p0, p1) = (prev + V3::new(0.0, -r0, 0.0), next + V3::new(0.0, -r1, 0.0));
                tapered_rod(&mut mesh, p0, p1, r0 * k, r1 * k, 5, Material::Accent);
            }
            prev = next;
        }
    }
    mesh
}
