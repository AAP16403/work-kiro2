//! Egg sac role: a low, anchored sac whose split shell plates open as the hatch timer runs down.
use super::super::geom::*;
use super::super::EnemyAnim;
use std::f32::consts::TAU;

/// Shell ellipsoid centred on the enemy origin: 25 wide, 23 tall.
const SHELL_RADII: V3 = V3::new(12.5, 10.8, 11.5);
/// Dark hatch socket that the core and lip sit in.
const SOCKET_CENTER: V3 = V3::new(10.0, 0.0, 4.0);
const SOCKET_RADII: V3 = V3::new(2.3, 3.4, 5.5);
const RING_SAMPLES: usize = 24;
/// Anchor spurs as (root x, root |y|, tip x, tip |y|); roots sit inside the shell, tips outside it.
const SPUR_ROOT_Z: f32 = -5.0;
const SPUR_TIP_Z: f32 = -9.8;
const SPURS: [(f32, f32, f32, f32); 2] = [(-5.4, 4.2, -9.5, 7.2), (5.5, 4.4, 9.3, 7.4)];

/// Shell point at polar `angle` and height `z`, pushed out by `scale`.
fn surface_point(angle: f32, z: f32, scale: f32) -> V3 {
    let ring = (1.0 - (z / SHELL_RADII.z).powi(2)).max(0.08).sqrt();
    V3::new(SHELL_RADII.x * ring * scale * angle.cos(), SHELL_RADII.y * ring * scale * angle.sin(), z)
}

/// Shell x-extent at (y, z), so articulated parts sit on the surface.
fn shell_x(y: f32, z: f32) -> f32 {
    let u = (z / SHELL_RADII.z).powi(2) + (y / SHELL_RADII.y).powi(2);
    SHELL_RADII.x * (1.0 - u).max(0.0).sqrt()
}

/// Front x-extent of the hatch socket at (y, z).
fn socket_x(y: f32, z: f32) -> f32 {
    let u = ((z - SOCKET_CENTER.z) / SOCKET_RADII.z).powi(2) + (y / SOCKET_RADII.y).powi(2);
    SOCKET_CENTER.x + SOCKET_RADII.x * (1.0 - u).max(0.0).sqrt()
}

/// Closed band hugging the shell at height `z`.
fn shell_band(mesh: &mut Mesh, z: f32, scale: f32, tube: f32, material: Material) {
    let pt = |i: usize| surface_point(TAU * i as f32 / RING_SAMPLES as f32, z, scale);
    for i in 0..RING_SAMPLES {
        tapered_rod(mesh, pt(i), pt((i + 1) % RING_SAMPLES), tube, tube, 4, material);
    }
}

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    mesh.ellipsoid(V3::new(0.0, 0.0, 0.0), SHELL_RADII, 18, 12, Material::Shell);
    // Swept ridges follow the surface and twist slightly instead of forming grenade bands.
    for i in 0..6 {
        let angle = TAU * (i as f32 + 0.5) / 6.0;
        let mut last = None;
        for step in 0..=10 {
            let z = -11.16 + step as f32 * 2.232;
            let p = surface_point(angle + z / SHELL_RADII.z * 0.12, z, 1.008);
            if let Some(prev) = last {
                tapered_rod(&mut mesh, prev, p, 1.05, 0.78, 6, Material::ShellLight);
            }
            last = Some(p);
        }
    }
    let f_start = mesh.faces.len();
    // Accent seam hugs the equator; a dark band sits low; the crown nub clears the top pole.
    shell_band(&mut mesh, 0.0, 1.02, 0.5, Material::Accent);
    shell_band(&mut mesh, -7.6, 1.02, 0.9, Material::Dark);
    mesh.ellipsoid(V3::new(0.0, 0.0, 11.4), V3::new(3.6, 3.2, 1.0), 12, 7, Material::ShellLight);
    // Recessed hatch: dark socket, accent lip, glowing core, cream eye.
    mesh.ellipsoid(SOCKET_CENTER, SOCKET_RADII, 14, 9, Material::Dark);
    mesh.torus_x(V3::new(11.0, 0.0, 4.0), 4.0, 0.72, Material::Accent);
    mesh.ellipsoid(V3::new(11.8, 0.0, 4.0), V3::new(1.1, 1.75, 3.35), 12, 8, Material::Core);
    mesh.ellipsoid(V3::new(12.75, -0.35, 5.0), V3::new(0.55, 0.8, 1.0), 9, 6, Material::Eye);
    for side in [-1.0_f32, 1.0] {
        for &(rx, ry, tx, ty) in SPURS.iter() {
            let (root, tip) = (V3::new(rx, side * ry, SPUR_ROOT_Z), V3::new(tx, side * ty, SPUR_TIP_Z));
            tapered_rod(&mut mesh, root, tip, 1.7, 0.42, 7, Material::ShellLight);
        }
    }
    mesh.with_bias(f_start, -2.5);
    mesh
}

/// Articulated (pose-driven) parts for this role.
pub(crate) fn animated_parts(a: &EnemyAnim<'_>) -> Mesh {
    let EnemyAnim { windup, time, seed, reduce_motion, .. } = *a;
    let opening = windup.clamp(0.0, 1.0);
    // Breath and the final-second shiver are zero under reduce motion, leaving the calm pose.
    let breath = if reduce_motion { 0.0 } else { (time * TAU * 0.5 + seed).sin() };
    let final_second = ((opening - 0.75) / 0.25).clamp(0.0, 1.0);
    let shiver = if reduce_motion { 0.0 } else { final_second.powi(2) * 0.6 * (time * 46.0 + seed).sin() };
    // Smoothstep travel: the plates accelerate into the hatch.
    let ease = opening * opening * (3.0 - 2.0 * opening);
    let mut mesh = Mesh::default();
    for side in [-1.0_f32, 1.0] {
        let plate_y = side * (3.0 + ease * 3.0 + shiver);
        let plate_x = 10.4 + opening * 0.35;
        let plate_z = 2.0 + opening * 0.25;
        mesh.ellipsoid(V3::new(plate_x, plate_y, plate_z), V3::new(2.6, 2.95, 5.2), 12, 8, Material::ShellLight);
        // Bone rib runs down the plate face, both ends seated on the shell.
        let rib = |z: f32| V3::new(shell_x(plate_y, z) + 0.3, plate_y, z);
        tapered_rod(&mut mesh, rib(-1.2), rib(5.8), 0.48, 0.34, 6, Material::Bone);
    }
    let core_scale = 1.0 + 0.045 * breath;
    let core_radii = V3::new(0.8, (0.95 + opening * 0.7) * core_scale, (3.1 + opening * 1.1) * core_scale);
    mesh.ellipsoid(V3::new(12.8 + opening * 0.25, 0.0, 4.0), core_radii, 12, 8, Material::Core);
    // Three accent rim rods centred on the core, resting on the socket lip.
    let spread = 1.15 + opening * 0.9;
    for level in 0..3 {
        let zc = SOCKET_CENTER.z + (level as f32 - 1.0) * 3.0;
        let start = V3::new(socket_x(-spread, zc - 0.55) + 0.1, -spread, zc - 0.55);
        let end = V3::new(socket_x(spread, zc + 0.55) + 0.1, spread, zc + 0.55);
        tapered_rod(&mut mesh, start, end, 0.42 + opening * 0.10, 0.30, 6, Material::Accent);
    }
    mesh
}
