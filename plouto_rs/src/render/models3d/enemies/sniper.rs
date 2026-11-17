//! Sniper role: a needle rail hull with swept rear wings and one lit central spine.
use super::super::geom::*;
use super::super::EnemyAnim;
use crate::sim::config::{SNIPER_AIM_SECONDS, SNIPER_LOCK_SECONDS};

/// Windup level at which the sim freezes its aim (the shot is locked).
const LOCK_WINDUP: f32 = 1.0 - SNIPER_LOCK_SECONDS / SNIPER_AIM_SECONDS;
const MUZZLE_X_IDLE: f32 = 33.0;
const MUZZLE_X_GAIN: f32 = 4.0;
/// Rail sits above the inner hull plate (top z 7.1) so it stays visible.
const RAIL_Z: f32 = 7.3;

/// Upper half of the main hull outline, spine points first and last.
const HULL_A_HALF: [(f32, f32); 9] = [
    (37.0, 0.0), (27.0, 1.4), (12.0, 2.6), (2.0, 4.8), (-8.0, 9.0),
    (-21.0, 17.0), (-30.0, 12.5), (-25.0, 6.5), (-30.0, 0.0),
];
/// Upper half of the inner lighter hull plate.
const HULL_B_HALF: [(f32, f32); 9] = [
    (34.0, 0.0), (22.0, 1.2), (8.0, 1.7), (-4.0, 3.8), (-13.0, 8.0),
    (-24.0, 12.5), (-28.0, 10.0), (-21.0, 4.6), (-23.0, 0.0),
];
const VENT_COUNT: usize = 3;

/// Builds a closed symmetric outline from its upper half: the half as given,
/// then the mirrored interior points in reverse order.
fn mirror_outline(half: &[(f32, f32)]) -> Vec<(f32, f32)> {
    let mut out = half.to_vec();
    out.extend(half[1..half.len() - 1].iter().rev().map(|&(x, y)| (x, -y)));
    out
}

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    // Needle nose, swept rear delta wings, and a single lit centre channel
    // match the supplied long-range railgun art.
    extruded_plate(&mut mesh, &mirror_outline(&HULL_A_HALF), -3.8, 4.5, Material::Shell, Material::Dark);
    extruded_plate(&mut mesh, &mirror_outline(&HULL_B_HALF), 4.0, 7.1, Material::ShellLight, Material::Dark);

    for side in [-1.0_f32, 1.0] {
        // Rear stabilizers and tiny mid-body canards.
        extruded_plate(&mut mesh, &[
            (-4.0, side * 6.5), (-10.0, side * 11.0), (-22.0, side * 17.0),
            (-30.0, side * 12.5), (-24.0, side * 7.5), (-15.0, side * 5.5),
        ], 5.0, 6.8, Material::Shell, Material::Dark);
        extruded_plate(&mut mesh, &[
            (7.0, side * 3.6), (0.0, side * 9.5), (-6.0, side * 8.0), (-3.0, side * 4.2),
        ], 3.0, 5.4, Material::ShellLight, Material::Dark);
        tapered_rod(&mut mesh, V3::new(-0.5, side * 8.2, 5.7), V3::new(-3.0, side * 9.2, 5.7), 0.35, 0.35, 6, Material::Accent);
        tapered_rod(&mut mesh, V3::new(-5.0, side * 7.0, 7.3), V3::new(-29.0, side * 14.6, 5.1), 0.92, 0.42, 8, Material::Glow);
        // Magenta wing slashes.
        for vent in 0..VENT_COUNT {
            let x = -13.0 - vent as f32 * 3.3;
            let y = side * (12.0 + vent as f32 * 1.35);
            tapered_rod(
                &mut mesh,
                V3::new(x + 1.4, y - side * 0.55, 7.8),
                V3::new(x - 1.0, y + side * 0.55, 7.9),
                0.72, 0.48, 6, Material::Accent,
            );
        }
    }

    // One static cyan spine under the animated rail (no twin barrels).
    tapered_rod(&mut mesh, V3::new(7.0, 0.0, 7.2), V3::new(30.0, 0.0, 7.0), 0.34, 0.26, 7, Material::Glow);

    let f_start = mesh.faces.len();
    build_canopy(&mut mesh);
    build_engine(&mut mesh);
    mesh.with_bias(f_start, -2.5);
    mesh
}

/// Recessed violet canopy and the muzzle lens. Biased forward with the
/// rest of the upper body so it sits proud of the hull.
fn build_canopy(mesh: &mut Mesh) {
    extruded_plate(mesh, &[
        (-1.0, 0.0), (-4.0, 4.2), (-9.0, 4.8), (-14.0, 3.0),
        (-14.0, -3.0), (-9.0, -4.8), (-4.0, -4.2),
    ], 6.4, 9.0, Material::Dark, Material::ShellLight);
    mesh.torus(V3::new(-7.0, 0.0, 8.4), 4.2, 0.8, 14, 7, 2, Material::Accent);
    mesh.ellipsoid(V3::new(-7.0, 0.0, 8.7), V3::new(4.0, 3.8, 1.35), 12, 6, Material::Core);
    mesh.ellipsoid(V3::new(35.0, 0.0, 4.0), V3::new(1.35, 1.1, 1.05), 8, 5, Material::Eye);
}

/// Single centred rear engine, rimmed in violet.
fn build_engine(mesh: &mut Mesh) {
    mesh.ellipsoid(V3::new(-28.0, 0.0, 1.4), V3::new(4.0, 5.4, 4.0), 10, 6, Material::Shell);
    mesh.torus(V3::new(-29.2, 0.0, 1.4), 3.5, 0.82, 12, 6, 0, Material::Accent);
    mesh.torus(V3::new(-29.7, 0.0, 1.4), 2.3, 0.52, 10, 5, 0, Material::Eye);
    mesh.ellipsoid(V3::new(-30.0, 0.0, 1.4), V3::new(1.35, 2.6, 2.6), 10, 6, Material::Core);
}

/// Articulated (pose-driven) parts for this role.
pub(crate) fn animated_parts(a: &EnemyAnim<'_>) -> Mesh {
    let EnemyAnim { windup, time, seed, reduce_motion, .. } = *a;
    let mut mesh = Mesh::default();
    let charge = windup.clamp(0.0, 1.0);
    // Idle breath on the rail, faded out as the charge rises and held still
    // under reduced motion so the pose stays calm.
    let breathe = if reduce_motion { 0.0 } else { (time * 2.1 + seed).sin() };
    let idle_swell = (1.0 - charge) * breathe * 0.06;
    let muzzle_x = MUZZLE_X_IDLE + charge * MUZZLE_X_GAIN;
    let rail_radius = 0.42 + charge * 0.58 + idle_swell;
    tapered_rod(
        &mut mesh,
        V3::new(3.0, 0.0, RAIL_Z + 0.2),
        V3::new(muzzle_x, 0.0, RAIL_Z),
        rail_radius,
        0.24 + charge * 0.18,
        9,
        Material::Core,
    );
    if charge > 0.08 {
        tapered_rod(
            &mut mesh,
            V3::new(7.0, 0.0, RAIL_Z + 0.6),
            V3::new(muzzle_x - 1.2, 0.0, RAIL_Z + 0.3),
            0.2 + charge * 0.22,
            0.04,
            7,
            Material::Eye,
        );
    }
    // Lock collar appears at the same threshold the sim freezes its aim.
    if charge >= LOCK_WINDUP {
        mesh.torus_x(V3::new(muzzle_x - 3.0, 0.0, RAIL_Z), 1.6, 0.36, Material::Accent);
    }
    mesh
}
