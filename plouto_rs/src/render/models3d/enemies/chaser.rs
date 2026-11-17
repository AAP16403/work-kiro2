//! Chaser role: a graphite arrowhead interceptor with swept side fins, a dark
//! canopy with amber eye slashes, and one rear turbine that lengthens into a
//! thrust flame while it runs or winds up its lunge.
use super::super::geom::*;
use super::super::EnemyAnim;

// Silhouette matched to `enemy-chaser.png`: nose at X=22, wingtips at Y=±20,
// so the body spans 40 units across (art ratio about 0.94).
const BODY: [(f32, f32); 10] = [
    (22.0, 0.0), (8.0, 7.4), (-15.0, 20.0), (-11.0, 7.5), (-16.5, 4.2),
    (-14.5, 0.0), (-16.5, -4.2), (-11.0, -7.5), (-15.0, -20.0), (8.0, -7.4),
];
const SPINE: [(f32, f32); 6] = [(19.5, 0.0), (7.5, 4.8), (-12.5, 5.2), (-15.0, 0.0), (-12.5, -5.2), (7.5, -4.8)];
const BEVEL: [(f32, f32); 9] = [
    (11.0, 0.0), (7.2, 5.2), (1.0, 6.2), (-5.6, 5.0), (-9.6, 2.6),
    (-9.6, -2.6), (-5.6, -5.0), (1.0, -6.2), (7.2, -5.2),
];
const CANOPY: [(f32, f32); 8] = [
    (7.6, 0.0), (5.0, 3.7), (1.0, 4.7), (-3.2, 4.0), (-4.6, 0.0), (-3.2, -4.0), (1.0, -4.7), (5.0, -3.7),
];
const POD: [(f32, f32); 5] = [(5.0, 6.0), (2.0, 8.6), (-2.0, 9.2), (-2.8, 6.2), (-0.5, 5.2)];
const FIN: [(f32, f32); 4] = [(-5.0, 13.8), (-11.5, 17.8), (-14.0, 18.0), (-11.0, 12.5)];
const NOZZLE_X: f32 = -18.0;
const NOZZLE_Z: f32 = -0.4;

fn mirrored(points: &[(f32, f32)], side: f32) -> Vec<(f32, f32)> {
    points.iter().map(|&(x, y)| (x, side * y)).collect()
}

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    extruded_plate(&mut mesh, &BODY, -1.8, 2.2, Material::Shell, Material::Dark);
    extruded_plate(&mut mesh, &SPINE, 1.2, 4.4, Material::ShellLight, Material::Dark);

    // Faces from here on (bevel, canopy, wing trim, nozzle) are pulled forward to avoid z-fighting.
    let raised_faces_start = mesh.faces.len();
    extruded_plate(&mut mesh, &BEVEL, 3.6, 5.7, Material::ShellLight, Material::Dark);
    extruded_plate(&mut mesh, &CANOPY, 5.5, 6.1, Material::Dark, Material::Dark);
    mesh.ellipsoid(V3::new(4.5, 0.0, 6.3), V3::new(2.6, 1.9, 0.55), 8, 4, Material::Dark);

    for side in [-1.0_f32, 1.0] {
        // Cyan leading edge; three amber slashes ("III") sit on the wing surface.
        tapered_rod(&mut mesh, V3::new(7.8, side * 7.6, 3.0), V3::new(-13.8, side * 19.2, 2.5), 0.78, 0.5, 8, Material::Glow);
        for j in [-0.9_f32, 0.0, 0.9] {
            tapered_rod(&mut mesh, V3::new(-7.0, side * (12.2 + j), 2.6), V3::new(-10.8, side * (16.4 + j), 2.6), 0.42, 0.34, 6, Material::Accent);
        }
        // Amber eye slash flanking the canopy, and an armored shoulder pod.
        tapered_rod(&mut mesh, V3::new(1.7, side * 5.0, 5.9), V3::new(-3.0, side * 4.7, 5.9), 0.5, 0.42, 6, Material::Accent);
        extruded_plate(&mut mesh, &mirrored(&POD, side), 1.2, 4.0, Material::ShellLight, Material::Shell);
    }

    // Nose warning strip, three cooling slots as flat plates (thin rods flickered at this scale).
    tapered_rod(&mut mesh, V3::new(12.8, 0.0, 4.0), V3::new(19.0, 0.0, 2.1), 0.72, 0.42, 7, Material::Accent);
    for y in [-1.8_f32, 0.0, 1.8] {
        extruded_plate(&mut mesh, &[(-1.6, y - 0.8), (-4.2, y - 0.8), (-4.2, y + 0.8), (-1.6, y + 0.8)], 5.95, 6.6, Material::Shell, Material::Dark);
    }
    // Rear engine: collar, accent and bone rings, and a glowing core. Amber lip on the collar.
    mesh.ellipsoid(V3::new(-15.8, 0.0, NOZZLE_Z), V3::new(4.3, 6.4, 4.2), 10, 5, Material::Shell);
    mesh.torus(V3::new(NOZZLE_X, 0.0, NOZZLE_Z), 5.1, 1.05, 12, 5, 0, Material::Accent);
    mesh.torus(V3::new(-18.45, 0.0, NOZZLE_Z), 3.45, 0.62, 12, 4, 0, Material::Bone);
    mesh.ellipsoid(V3::new(-18.8, 0.0, NOZZLE_Z), V3::new(1.6, 3.4, 3.4), 8, 4, Material::Core);
    tapered_rod(&mut mesh, V3::new(-12.0, -2.4, 4.6), V3::new(-12.0, 2.4, 4.6), 0.45, 0.35, 6, Material::Accent);
    mesh.with_bias(raised_faces_start, -2.5);
    mesh
}

/// Articulated (pose-driven) parts for this role.
pub(crate) fn animated_parts(a: &EnemyAnim<'_>) -> Mesh {
    let EnemyAnim { time, seed, windup, reduce_motion, move_speed, .. } = *a;
    let mut mesh = Mesh::default();
    let speed = (move_speed / 180.0).clamp(0.0, 1.0);
    let lunge = windup.clamp(0.0, 1.0);
    // Smoothstep ramp: fins and thrust ease through the windup and peak at commit.
    let coil = lunge * lunge * (3.0 - 2.0 * lunge);
    // Speed-scaled flex plus a slow drift so a parked craft still breathes; both gated by reduce_motion.
    let idle_flex = if reduce_motion {
        0.0
    } else {
        (time * 9.0 + seed).sin() * speed * 0.045 + (time * 4.2 + seed * 0.6).sin() * 0.015
    };
    let sweep = idle_flex + coil * 0.22;
    for side in [-1.0_f32, 1.0] {
        append_flap_plate(&mut mesh, &FIN, side, V3::new(-7.0, side * 12.0, 2.5), sweep, 0.7, Material::ShellLight, Material::Dark);
    }

    // The turbine lengthens into a solid flame while moving or winding up. The
    // flicker matches the exhaust pulse in mod.rs; reduced motion holds it steady.
    let thrust = speed.max(coil * 0.72);
    let flicker = if reduce_motion { 1.0 } else { 0.84 + 0.16 * (time * 11.0 + seed).sin() };
    let plume_len = (2.2 + thrust * 7.0) * flicker;
    let plume_width = (2.6 + thrust * 0.9) * flicker;
    push_plume(&mut mesh, -18.6, plume_len, plume_width, 0.35, 9, Material::Accent);
    if thrust > 0.08 {
        push_plume(&mut mesh, -19.0, plume_len * 0.6, plume_width * 0.5, 0.12, 7, Material::Core);
    }

    // Nose charge: a glow that grows toward the lunge warning as the windup builds.
    if coil > 0.02 {
        tapered_rod(&mut mesh, V3::new(21.0, 0.0, 2.1), V3::new(21.0 + 1.5 * coil, 0.0, 2.1), 0.30 + 0.45 * coil, 0.10, 7, Material::Glow);
    }
    mesh
}

fn push_plume(mesh: &mut Mesh, start_x: f32, len: f32, r0: f32, r1: f32, segments: usize, material: Material) {
    tapered_rod(mesh, V3::new(start_x, 0.0, NOZZLE_Z), V3::new(start_x - len, 0.0, NOZZLE_Z), r0, r1, segments, material);
}
