//! Boss womb core (Origin Nexus): a suspended lobed heart inside three precessing
//! armored gimbal rings, with crystal mounts, crossing stars and a rib cage.
use std::f32::consts::{FRAC_PI_4, TAU};

use super::super::geom::*;
use crate::sim::enemy::{Enemy, EnemySubState};

/// Breast-plate outline in the YZ plane (y = width, z = height).
const HEART: [(f32, f32); 12] = [
    (0.0, 19.0), (5.6, 23.0), (10.3, 20.5), (13.0, 14.5), (11.7, 8.0), (7.0, 2.5),
    (0.0, -6.2), (-7.0, 2.5), (-11.7, 8.0), (-13.0, 14.5), (-10.3, 20.5), (-5.6, 23.0),
];
const HEART_WIDTH: f32 = 1.12;
/// Gimbal rings: (base normal, precession axis, base radius, orbit speed).
const RING_SPECS: [(V3, V3, f32, f32); 3] = [
    (V3::new(0.0, 0.0, 1.0), V3::new(1.0, 0.2, 0.0), 34.0, 0.72),
    (V3::new(1.0, 0.0, 0.0), V3::new(0.0, 1.0, 0.18), 37.0, -0.94),
    (V3::new(0.0, 1.0, 0.0), V3::new(0.24, 0.0, 1.0), 40.0, 0.56),
];
const PRECESSION_RATE: f32 = 0.42;
// Pulse terms: the windup kick is bounded (windup squared), never a rate times time.
const PULSE_SPEED_KICK: f32 = 1.1; const PULSE_RING_CONTRACT: f32 = 4.5;
const RING_TUBE: f32 = 4.4; // flat band; the Glow channel and ShellLight lip sit on it
/// Mounts sit between the crossing stars, which lie on the axes.
const MOUNT_OFFSET: f32 = FRAC_PI_4; const MOUNT_SOCKET_R: f32 = 7.5;
const RIB_COUNT: usize = 8; const RIB_ROOT_R: f32 = 12.0; const RIB_MIDDLE_R: f32 = 24.0; const RIB_TIP_R: f32 = 38.0;
const RIB_ARC_Z: f32 = 11.0; const RIB_FREQ: f32 = 1.45; const RIB_PHASE_STEP: f32 = 0.8; const RIB_WAVE: f32 = 0.07;
const RIB_CURL: f32 = 0.06; const PULSE_RIB_GATHER: f32 = 3.5; const PULSE_RIB_TIP_CONTRACT: f32 = 8.5;

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    // A dark open rim, not an opaque shell: the heart reads through the cage.
    mesh.ellipsoid(V3::ZERO, V3::new(17.0, 16.0, 18.5), 16, 10, Material::Dark);
    mesh.torus(V3::new(2.0, 0.0, 1.0), 16.2, 2.3, 20, 7, 0, Material::ShellLight);

    let core_start = mesh.faces.len();
    mesh.ellipsoid(V3::new(3.8, 0.0, 2.5), V3::new(12.8, 13.2, 15.5), 18, 12, Material::Core);
    for side in [-1.0_f32, 1.0] {
        mesh.ellipsoid(V3::new(9.0, side * 5.6, 8.2), V3::new(5.8, 6.0, 7.8), 14, 10, Material::Glow);
        mesh.ellipsoid(V3::new(10.1, side * 5.0, 9.3), V3::new(2.5, 2.9, 3.8), 11, 8, Material::Eye);
    }
    let heart: Vec<(f32, f32)> = HEART.iter().map(|&(y, z)| (y * HEART_WIDTH, z)).collect();
    extruded_yz_plate(&mut mesh, &heart, 15.0, 17.0, Material::Core, Material::Accent);
    crystal_yz(&mut mesh, V3::new(17.0, 0.0, 20.0), 3.5, 5.2, 2.8, 1.0, Material::Glow, Material::Eye);
    mesh.with_bias(core_start, -4.0);
    mesh
}

/// Articulated (pose-driven) parts for this boss.
pub(crate) fn animated_parts(e: &Enemy, time: f32, windup: f32, reduce_motion: bool) -> Mesh {
    let mut mesh = Mesh::default();
    let tell = if e.ai.sub_state == EnemySubState::WombPulseTelegraph { windup } else { 0.0 }; // gates all pulse terms
    let idle_phase = if reduce_motion { 0.0 } else { time };
    let (mut normals, mut radii) = ([V3::ZERO; 3], [0.0_f32; 3]);
    for (index, (base_normal, axis, base_radius, speed)) in RING_SPECS.into_iter().enumerate() {
        let phase = idle_phase * speed + index as f32 * 0.72 + tell * tell * speed.signum() * PULSE_SPEED_KICK;
        let precession = if reduce_motion { 0.0 } else { phase * PRECESSION_RATE };
        let spin = if reduce_motion { 0.0 } else { phase };
        let normal = rotate_about_axis(base_normal, axis, precession);
        let radius = base_radius - tell * PULSE_RING_CONTRACT;
        normals[index] = normal; radii[index] = radius;
        push_gyro_ring(&mut mesh, radius, normal, spin);
        push_ring_mounts(&mut mesh, radius, normal, spin, if index == 0 { 4 } else { 2 });
    }

    // Ring pairs meet on shared axes; stars use live normals and radii, so they follow the rings.
    for (a, b) in [(0, 1), (1, 2), (0, 2)] {
        let axis = normals[a].cross(normals[b]).normalized();
        let c = (radii[a] + radii[b]) * 0.5;
        for sign in [1.0_f32, -1.0] {
            crystal_oriented(&mut mesh, axis * (sign * c), normals[a], axis * sign, normals[b], 6.0, 6.0, 3.0, Material::Dark, Material::Accent);
        }
    }
    // Heart suspension struts run from the core out to the Z-axis stars.
    let (axis, c) = (normals[1].cross(normals[2]).normalized(), (radii[1] + radii[2]) * 0.5);
    for sign in [1.0_f32, -1.0] {
        tapered_rod(&mut mesh, axis * (sign * 13.0), axis * (sign * (c - 4.0)), 2.4, 1.2, 6, Material::Dark);
    }

    // Cage ribs flex at rest; the pulse gathers their middles and tips inward
    // with only a small tangential curl.
    let rib_phase = if reduce_motion { 0.0 } else { time * RIB_FREQ + e.seed };
    for i in 0..RIB_COUNT {
        let base = i as f32 * (TAU / RIB_COUNT as f32);
        let sign = if i % 2 == 0 { 1.0 } else { -1.0 };
        let wave = if reduce_motion { 0.0 } else { (rib_phase + i as f32 * RIB_PHASE_STEP).sin() * RIB_WAVE };
        let angle = base + wave + sign * tell * RIB_CURL;
        let z = (base * 2.0).sin() * RIB_ARC_Z;
        let (middle_r, tip_r) = (RIB_MIDDLE_R - tell * PULSE_RIB_GATHER, RIB_TIP_R - tell * PULSE_RIB_TIP_CONTRACT);
        let middle = V3::new(angle.cos() * middle_r, angle.sin() * middle_r, z * 0.68);
        let tip = V3::new(angle.cos() * tip_r, angle.sin() * tip_r, z);
        let root = V3::new(angle.cos() * RIB_ROOT_R, angle.sin() * RIB_ROOT_R, z * 0.38);
        tapered_rod(&mut mesh, root, middle, 4.6, 3.8, 8, Material::Dark);
        mesh.ellipsoid(middle, V3::new(4.2, 4.2, 4.2), 8, 5, Material::ShellLight);
        tapered_rod(&mut mesh, middle, tip, 3.8, 2.1, 8, Material::ShellLight);
        if i % 2 == 0 {
            tapered_rod(&mut mesh, root, middle, 1.0, 0.65, 6, Material::Accent);
            tapered_rod(&mut mesh, middle, tip, 0.8, 0.35, 6, Material::Glow);
        }
        mesh.ellipsoid(tip, V3::new(2.8, 2.8, 2.8), 8, 5, Material::Dark);
    }
    mesh
}

/// One gimbal ring: Shell band, ShellLight lip outside it, Glow channel inside.
fn push_gyro_ring(mesh: &mut Mesh, radius: f32, normal: V3, spin: f32) {
    mesh.torus_oriented(V3::ZERO, radius, RING_TUBE, 24, 8, normal, spin, Material::Shell);
    mesh.torus_oriented(V3::ZERO, radius + 4.6, 1.1, 24, 6, normal, spin, Material::ShellLight);
    mesh.torus_oriented(V3::ZERO, radius - 3.6, 1.4, 24, 6, normal, spin, Material::Glow);
}

/// Evenly spaced socket, rod, faceted crystal and two shards riding one ring.
fn push_ring_mounts(mesh: &mut Mesh, radius: f32, normal: V3, spin: f32, count: usize) {
    let (u, v) = ring_plane_basis(normal, spin);
    for node in 0..count {
        let (sa, ca) = (MOUNT_OFFSET + node as f32 * (TAU / count as f32)).sin_cos();
        let (radial, tangent) = (u * ca + v * sa, u * -sa + v * ca);
        let socket = radial * (radius + MOUNT_SOCKET_R);
        mesh.ellipsoid(socket, V3::new(5.2, 5.2, 5.2), 8, 6, Material::Dark);
        tapered_rod(mesh, socket - radial * 4.0, socket + radial * 4.2, 2.4, 1.45, 6, Material::Accent);
        let gem = socket + radial * 5.2;
        crystal_oriented(mesh, gem, tangent, radial, normal, 5.8, 10.5, 4.2, Material::Glow, Material::Eye);
        for side in [-1.0_f32, 1.0] {
            let shard = gem + tangent * (side * 5.3) + radial * 1.2;
            crystal_oriented(mesh, shard, tangent, radial, normal, 3.0, 6.6, 2.6, Material::Eye, Material::Glow);
        }
    }
}
