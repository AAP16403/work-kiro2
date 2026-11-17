//! Boss eclipse archon: a black event horizon ringed by a cyan corona, an
//! eight-lance armored crown, vertical top and bottom spikes, and three orbit rings.
use std::f32::consts::{FRAC_PI_2, PI, TAU};

use super::super::geom::*;
use crate::sim::enemy::{Enemy, EnemySubState};

const LANCES: usize = 8;
const LANCE_STEP: f32 = TAU / LANCES as f32;
const RAYS: usize = 16;
const UP: V3 = V3::new(0.0, 1.0, 0.0);
const CORONA_INNER: f32 = 16.0;
const CORONA_OUTER: f32 = 22.0;
const CORONA_SPIKE: f32 = 2.4;
/// Tangential twist applied to the alternating lance tips while charging.
const CHARGE_TWIST: f32 = 0.14;

/// Returns `value`, or zero when reduce motion is on (keeps the calm pose static).
fn live(reduce_motion: bool, value: f32) -> f32 {
    if reduce_motion { 0.0 } else { value }
}

fn bead(mesh: &mut Mesh, center: V3, radius: f32, material: Material) {
    mesh.ellipsoid(center, V3::new(radius, radius, radius), 6, 4, material);
}

/// One armor lance: a dark-shell shaft, a light rail, and an accent rail offset in Y.
fn armor_lance(mesh: &mut Mesh, root: V3, joint: V3, tip: V3, shaft: [f32; 2], rail: [f32; 2], accent_drop: f32, accent: [f32; 2]) {
    tapered_rod(mesh, root, joint, shaft[0], shaft[1], 9, Material::Shell);
    tapered_rod(mesh, joint, tip, rail[0], rail[1], 9, Material::ShellLight);
    let drop = V3::new(0.0, accent_drop, 0.0);
    tapered_rod(mesh, root + drop, tip + drop, accent[0], accent[1], 7, Material::Accent);
}

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    // Upright front-facing eclipse: the dark event horizon is the readable center,
    // so the crown and corona get the room around it. The corona lies in the
    // equatorial XZ plane, where the crown is built.
    mesh.ellipsoid(V3::ZERO, V3::new(14.5, 11.0, 14.5), 20, 14, Material::Dark);
    mesh.torus_oriented(V3::new(0.0, -14.3, 0.0), 21.5, 2.3, 24, 8, UP, 0.0, Material::Glow);
    mesh.torus_oriented(V3::new(0.0, -15.1, 0.0), 18.7, 0.9, 22, 6, UP, 0.0, Material::Eye);
    mesh.torus_oriented(V3::ZERO, 15.8, 0.9, 32, 6, UP, 0.0, Material::Glow);
    mesh.torus_oriented(V3::ZERO, 19.4, 0.4, 32, 4, UP, 0.0, Material::Eye);

    for point in 0..LANCES {
        let angle = FRAC_PI_2 + point as f32 * LANCE_STEP;
        let (sa, ca) = angle.sin_cos();
        let outline = [(12.0, -8.5), (27.0, -13.5), (42.0, -8.0), (60.0, 0.0), (42.0, 8.0), (27.0, 13.5), (12.0, 8.5)]
            .map(|(radius, tangent)| (ca * radius - sa * tangent, sa * radius + ca * tangent));
        extruded_xz_plate(&mut mesh, &outline, -8.0, -17.0, Material::ShellLight, Material::Dark, Material::Shell);
        let root = V3::new(ca * 14.0, -16.2, sa * 14.0);
        let shoulder = V3::new(ca * 31.0, -16.0, sa * 31.0);
        let tip = V3::new(ca * 60.0, -13.0, sa * 60.0);
        armor_lance(&mut mesh, root, shoulder, tip, [3.8, 3.0], [3.0, 0.5], -1.3, [1.9, 0.4]);
        // Dark collar closes the gap between the lance root and the event horizon.
        bead(&mut mesh, V3::new(ca * 12.0, -12.5, sa * 12.0), 4.5, Material::Dark);
        let jewel_radius = if point % 2 == 0 { 39.0 } else { 33.0 };
        let jewel = V3::new(ca * jewel_radius, -19.0, sa * jewel_radius);
        crystal_xz(&mut mesh, jewel, 5.4, 9.5, 3.3, -1.0, angle - FRAC_PI_2, Material::Glow, Material::Eye);
        mesh.ellipsoid(jewel + V3::new(0.0, -3.5, 0.0), V3::new(1.7, 1.1, 3.4), 6, 4, Material::Bone);
    }

    // Vertical top and bottom spikes, each capped by a magenta-white jewel.
    for sign in [1.0_f32, -1.0] {
        tapered_rod(&mut mesh, V3::new(0.0, sign * 10.0, 0.0), V3::new(0.0, sign * 46.0, 0.0), 5.0, 1.2, 9, Material::Dark);
        crystal_oriented(&mut mesh, V3::new(0.0, sign * 50.0, 0.0), V3::new(1.0, 0.0, 0.0), UP, V3::new(0.0, 0.0, 1.0), 3.2, 7.5, 3.2, Material::Glow, Material::Eye);
    }

    for ray in 0..RAYS {
        let angle = ray as f32 * (TAU / RAYS as f32);
        let (sa, ca) = angle.sin_cos();
        let spiked = ray % 2 == 0;
        let outer = CORONA_OUTER + if spiked { CORONA_SPIKE } else { 0.0 };
        let inner = V3::new(ca * CORONA_INNER, 0.0, sa * CORONA_INNER);
        let outer = V3::new(ca * outer, 0.0, sa * outer);
        tapered_rod(&mut mesh, inner, outer, 1.55, 0.25, 6, if spiked { Material::Glow } else { Material::Eye });
    }
    mesh
}

/// Articulated (pose-driven) parts for this boss.
pub(crate) fn animated_parts(e: &Enemy, time: f32, windup: f32, reduce_motion: bool) -> Mesh {
    let mut mesh = Mesh { faces: Vec::with_capacity(4_800) };
    let charging = e.ai.sub_state == EnemySubState::EclipseCharge;
    let bursting = e.ai.sub_state == EnemySubState::EclipseBurst;
    let escaping = e.ai.sub_state == EnemySubState::EclipseEscape;
    let spin_rate = if bursting { 1.35 } else if charging { 0.26 } else if escaping { 0.82 } else { 0.52 };
    let orbit = live(reduce_motion, time * spin_rate * if e.ai.rage { 1.4 } else { 1.0 });
    let extension = if charging { windup } else if bursting { 0.72 } else if escaping { 0.18 } else { 0.0 };
    let sway_phase = live(reduce_motion, time * 2.0 + e.seed);
    // Lances flare a little more while the boss is moving (sim vel, normalized).
    let move_norm = live(reduce_motion, (e.vel.length() / 120.0).clamp(0.0, 1.0));

    let ring_specs = [
        (V3::new(0.0, 1.0, 0.0), 42.0, 0.44, Material::Glow),
        (V3::new(0.22, 0.94, 0.26), 48.0, -0.58, Material::Eye),
        (V3::new(-0.31, 0.34, 0.89), 37.0, 0.77, Material::Accent),
    ];
    for (index, (base_normal, radius, speed, material)) in ring_specs.into_iter().enumerate() {
        let phase = live(reduce_motion, orbit * speed + index as f32 * 0.76);
        let precession = live(reduce_motion, phase * 0.38);
        let normal = rotate_about_axis(base_normal, V3::new(0.45, 0.2, 0.72), precession);
        let ring_radius = radius + if bursting { 5.0 } else if charging { 2.0 * windup } else if escaping { -2.0 } else { 0.0 };
        mesh.torus_oriented(V3::ZERO, ring_radius, 1.8, 26, 6, normal, phase, Material::Dark);
        mesh.torus_oriented(V3::ZERO, ring_radius + 1.1, 1.25, 26, 6, normal, phase, material);
        let (u, v) = ring_plane_basis(normal, phase);
        for node in [0.0_f32, PI] {
            let radial = u * node.cos() + v * node.sin();
            bead(&mut mesh, radial * (ring_radius + 1.2), 2.7, Material::Dark);
            // Lit orb sits proud of its dark bead instead of being buried in it.
            bead(&mut mesh, radial * (ring_radius + 1.2 + 3.7), 1.65, material);
        }
    }

    for i in 0..LANCES {
        let angle = FRAC_PI_2 + orbit * 0.34 + i as f32 * LANCE_STEP;
        let (sa, ca) = angle.sin_cos();
        let twitch = live(reduce_motion, (sway_phase + i as f32 * 0.83).sin() * (1.2 + 1.8 * move_norm));
        let root = V3::new(ca * 15.0, -16.0, sa * 15.0);
        let elbow_radius = 29.0 + extension * 3.0 + twitch + move_norm * 1.5;
        let tip_radius = 51.0 + extension * 16.0 + twitch * 1.7;
        let elbow = V3::new(ca * elbow_radius, -17.5, sa * elbow_radius);
        let side = if i % 2 == 0 { -1.0 } else { 1.0 };
        let tip_angle = angle + if charging { windup * CHARGE_TWIST * side } else { 0.0 };
        let tip = V3::new(tip_angle.cos() * tip_radius, -14.5, tip_angle.sin() * tip_radius);
        armor_lance(&mut mesh, root, elbow, tip, [6.4, 5.2], [5.1, 1.0], -2.0, [1.6, 0.4]);
        mesh.ellipsoid(elbow, V3::new(5.0, 3.2, 5.0), 8, 5, Material::ShellLight);
        bead(&mut mesh, tip, 2.4, if i % 2 == 0 { Material::Glow } else { Material::Core });
    }
    mesh
}
