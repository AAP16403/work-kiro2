//! Spitter role: armored acid gunship with paired glass reservoirs and twin
//! dorsal spray launchers (`enemy-spitter.png`). Forward is +x, rear is -x.
use super::super::geom::*;
use super::super::EnemyAnim;

const SAC_X: f32 = -3.0;
const SAC_Y: f32 = 10.5;
const SAC_Z: f32 = 7.2;
const NOZZLE_X: f32 = 15.0;
const NOZZLE_Y: f32 = 6.0;
const NOZZLE_TOP_Z: f32 = 14.8;
const BUBBLE_RATE: f32 = 4.8;
const BUBBLE_SWAY: f32 = 0.65;

/// Reservoir centre for one side (`side` is -1 or 1).
fn sac_center(side: f32) -> V3 {
    V3::new(SAC_X, side * SAC_Y, SAC_Z)
}

/// Top of a dorsal launcher body for one side; shared by the static socket and the loaded spike.
fn nozzle_top(side: f32) -> V3 {
    V3::new(NOZZLE_X, side * NOZZLE_Y, NOZZLE_TOP_Z)
}

fn mirrored(points: &[(f32, f32)], side: f32) -> Vec<(f32, f32)> {
    points.iter().map(|&(x, y)| (x, y * side)).collect()
}

fn push_hull(mesh: &mut Mesh) {
    extruded_plate(mesh, &[
        (30.0, 0.0), (24.0, 3.2), (12.0, 6.0), (5.0, 12.5),
        (-10.0, 15.5), (-20.0, 22.5), (-29.0, 22.0), (-25.0, 12.0),
        (-20.0, 5.0), (-24.0, 0.0), (-20.0, -5.0), (-25.0, -12.0),
        (-29.0, -22.0), (-20.0, -22.5), (-10.0, -15.5), (5.0, -12.5),
        (12.0, -6.0), (24.0, -3.2),
    ], -4.6, 4.4, Material::Shell, Material::ShellLight);
    extruded_plate(mesh, &[
        (27.0, 0.0), (20.0, 3.0), (10.0, 4.5), (2.0, 10.2),
        (-13.0, 13.5), (-26.0, 18.5), (-28.0, 11.0), (-18.0, 5.0),
        (-20.0, 0.0), (-18.0, -5.0), (-28.0, -11.0), (-26.0, -18.5),
        (-13.0, -13.5), (2.0, -10.2), (10.0, -4.5), (20.0, -3.0),
    ], 4.0, 7.5, Material::ShellLight, Material::Dark);
}

/// Swept wing panel with a cyan leading-edge trim.
fn push_wing(mesh: &mut Mesh, side: f32) {
    extruded_plate(mesh, &mirrored(&[
        (7.0, 7.0), (-2.0, 12.0), (-17.0, 18.0), (-29.0, 22.0), (-23.0, 11.0), (-12.0, 6.0),
    ], side), 4.7, 7.0, Material::Shell, Material::ShellLight);
    tapered_rod(mesh, V3::new(-3.0, side * 11.0, 6.6), V3::new(-27.0, side * 21.0, 5.4), 0.92, 0.43, 8, Material::Glow);
}

/// Recessed reservoir: dark socket, lime glass body that breaks through the
/// shell at the top, and an accent collar. The suspended bubbles are animated.
fn push_reservoir(mesh: &mut Mesh, side: f32) {
    let sac = sac_center(side);
    extruded_plate(mesh, &mirrored(&[
        (5.0, 6.5), (2.0, 12.5), (-7.0, 15.0), (-14.0, 11.8), (-11.5, 6.7), (-2.5, 4.9),
    ], side), 5.0, 8.4, Material::Dark, Material::ShellLight);
    mesh.ellipsoid(sac + V3::new(0.0, 0.0, -0.6), V3::new(6.6, 4.6, 4.6), 12, 7, Material::ShellLight);
    mesh.ellipsoid(sac + V3::new(0.6, 0.0, 1.0), V3::new(6.2, 3.8, 5.6), 12, 7, Material::Core);
    mesh.torus(sac + V3::new(0.0, 0.0, 2.4), 4.4, 0.72, 14, 6, 2, Material::Accent);
}

/// Dorsal spray launcher on a support pylon, with a cylinder body and accent collar.
fn push_nozzle(mesh: &mut Mesh, side: f32) {
    const OUTLINE: [(f32, f32); 6] = [
        (5.5, 0.0), (2.5, 5.8), (-5.0, 6.5), (-7.0, 0.0), (-5.0, -6.5), (2.5, -5.8),
    ];
    let cy = side * NOZZLE_Y;
    let plate: Vec<(f32, f32)> = OUTLINE
        .iter()
        .map(|&(dx, dy)| (NOZZLE_X + dx, cy + side * dy))
        .collect();
    extruded_plate(mesh, &plate, 6.5, 9.5, Material::Shell, Material::Dark);
    tapered_rod(mesh, V3::new(NOZZLE_X, cy, 4.0), V3::new(NOZZLE_X, cy, 7.0), 2.8, 2.8, 10, Material::Dark);
    let base = V3::new(NOZZLE_X, cy, 0.0);
    mesh.cylinder_z(base, 2.8, 8.5, NOZZLE_TOP_Z, 13, Material::ShellLight);
    mesh.torus(base + V3::new(0.0, 0.0, 14.4), 2.4, 0.72, 14, 6, 2, Material::Accent);
    mesh.ellipsoid(base + V3::new(0.0, 0.0, 14.7), V3::new(1.7, 1.7, 0.8), 10, 6, Material::Core);
}

/// Three lime exhaust slots per rear wing.
fn push_vents(mesh: &mut Mesh, side: f32) {
    for vent in 0..3 {
        let x = -21.5 - vent as f32 * 2.2;
        let y = side * (15.0 + vent as f32);
        tapered_rod(mesh, V3::new(x + 1.2, y - side * 0.55, 7.4), V3::new(x - 1.1, y + side * 0.55, 7.5), 0.72, 0.5, 6, Material::Accent);
    }
}

/// Long recessed cockpit, pointed nose spine, center reactor, and rear engine.
fn push_cockpit(mesh: &mut Mesh) {
    extruded_plate(mesh, &[
        (23.0, 0.0), (16.0, 4.0), (5.0, 4.8), (-7.0, 3.1),
        (-7.0, -3.1), (5.0, -4.8), (16.0, -4.0),
    ], 7.1, 8.8, Material::Dark, Material::ShellLight);
    mesh.ellipsoid(V3::new(3.5, 0.0, 9.1), V3::new(5.3, 3.2, 1.4), 12, 7, Material::Core);
    tapered_rod(mesh, V3::new(14.0, 0.0, 9.4), V3::new(24.5, 0.0, 8.0), 0.7, 0.45, 8, Material::Accent);
    extruded_plate(mesh, &[
        (8.0, 0.0), (3.5, 3.5), (-4.5, 3.5), (-8.0, 0.0), (-4.5, -3.5), (3.5, -3.5),
    ], 8.0, 9.4, Material::ShellLight, Material::Dark);
    mesh.ellipsoid(V3::new(-24.5, 0.0, 1.2), V3::new(4.2, 5.2, 3.8), 10, 6, Material::Shell);
    mesh.torus_x(V3::new(-27.0, 0.0, 1.2), 3.5, 0.78, Material::Accent);
    mesh.ellipsoid(V3::new(-27.8, 0.0, 1.2), V3::new(1.4, 2.7, 2.7), 10, 6, Material::Core);
}

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    push_hull(&mut mesh);
    for side in [-1.0_f32, 1.0] {
        push_wing(&mut mesh, side);
        push_reservoir(&mut mesh, side);
        push_nozzle(&mut mesh, side);
        push_vents(&mut mesh, side);
    }
    let f_start = mesh.faces.len();
    push_cockpit(&mut mesh);
    mesh.with_bias(f_start, -2.5);
    mesh
}

/// Articulated (pose-driven) parts for this role.
pub(crate) fn animated_parts(a: &EnemyAnim<'_>) -> Mesh {
    let EnemyAnim { time, seed, windup, reduce_motion, .. } = *a;
    let mut mesh = Mesh::default();
    let charge = windup.clamp(0.0, 1.0);
    let idle = if reduce_motion { 0.0 } else { (time * BUBBLE_RATE + seed).sin() * BUBBLE_SWAY };
    for side in [-1.0_f32, 1.0] {
        let sac = sac_center(side);
        // Two suspended bubbles ride the reservoir surface; charge lifts and swells them.
        let big = 0.95 + charge * 0.4;
        mesh.ellipsoid(sac + V3::new(idle, 0.0, 4.4 + idle * 0.3 + charge * 0.8), V3::new(big, big, big), 9, 6, Material::Eye);
        let small = 0.62 + charge * 0.24;
        mesh.ellipsoid(sac + V3::new(-5.6 - idle * 0.4, 0.0, 2.6 + idle * 0.35 + charge * 0.6), V3::new(small, small, small), 8, 5, Material::Bone);

        // Loaded spike: lengthens and rises with charge, ending in a bead that marks the volley origin.
        let base = nozzle_top(side);
        let tip = V3::new(18.0 + charge * 1.8, side * (NOZZLE_Y + charge), 16.0 + charge * 2.2);
        tapered_rod(&mut mesh, base, tip, 1.15, 0.7, 8, Material::ShellLight);
        tapered_rod(&mut mesh, base + V3::new(0.6, -side * 0.6, 1.0), tip + V3::new(-0.5, -side * 0.45, 0.6), 0.42, 0.08, 6, Material::Accent);
        let bead = 0.7 + charge * 0.6;
        mesh.ellipsoid(tip, V3::new(bead, bead, bead), 8, 5, Material::Core);
        // Converging charge ring that climbs the spike as the volley loads.
        if charge > 0.02 {
            let ring = base + V3::new(0.0, 0.0, 1.0 + charge * 2.2);
            mesh.torus(ring, 3.3 - charge * 0.7, 0.5 + charge * 0.12, 14, 6, 2, Material::Accent);
        }
    }
    mesh
}
