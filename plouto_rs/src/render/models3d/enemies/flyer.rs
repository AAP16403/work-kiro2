//! Flyer role: narrow crescent fuselage, broad articulated delta wings, twin cyan thruster glow.
//! The static body (mean outline radius about 17.8 mesh units) matches the sim hit circle at the
//! drawn scale; the wings overhang it on purpose, matching the artwork's span (about 46 units a side).
use super::super::geom::*;
use super::super::EnemyAnim;

const ENGINE_Y: f32 = 11.0;
const ENGINE_HOUSING_X: f32 = -12.0;
const ENGINE_NOZZLE_X: f32 = -16.0;
const WING_HINGE: (f32, f32, f32) = (9.0, 5.0, 2.0); // x, lateral span, z
const WING_HALF_DEPTH: f32 = 1.6;
const WING_OUTLINE: [(f32, f32); 9] = [
    (11.0, 4.0), (10.0, 11.0), (2.0, 28.0), (-8.0, 39.0), (-22.0, 46.0),
    (-17.0, 38.0), (-12.0, 30.0), (-9.0, 20.0), (-5.0, 7.0),
];
const VENT_COUNT: usize = 3;
const FULL_SPEED: f32 = 145.0;
const FLAP_RATE: f32 = 10.5;
const FLAP_BEAT: (f32, f32) = (0.22, 0.12); // idle amplitude, extra amplitude at full thrust
const FLAP_LOCK_DAMP: f32 = 0.8;
const FLAP_LAUNCH: (f32, f32) = (0.40, 0.24); // windup launch pose, normal and reduced motion
const GLOW_LOCK: f32 = 0.85;

/// Closed polygon from an on-axis half outline (nose to tail, upper edge only).
fn mirror_outline(upper: &[(f32, f32)]) -> Vec<(f32, f32)> {
    let mut out = upper.to_vec();
    out.extend(upper[1..upper.len() - 1].iter().rev().map(|&(x, y)| (x, -y)));
    out
}

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    extruded_plate(&mut mesh, &mirror_outline(&[
        (30.0, 0.0), (23.0, 5.2), (11.0, 8.4), (-2.0, 9.0), (-14.0, 6.8), (-24.0, 0.0),
    ]), -4.4, 4.4, Material::Shell, Material::Dark);
    extruded_plate(&mut mesh, &mirror_outline(&[
        (27.0, 0.0), (20.0, 4.0), (9.0, 5.5), (-5.0, 6.0), (-18.0, 3.8), (-22.0, 0.0),
    ]), 4.0, 7.2, Material::ShellLight, Material::Dark);
    for side in [-1.0_f32, 1.0] {
        // Engine shoulder, nozzle shell, glow ring and eye, per side.
        extruded_plate(&mut mesh, &[
            (-4.0, side * 5.5), (-10.0, side * 12.8), (-19.0, side * 13.0),
            (-17.0, side * 7.0), (-9.0, side * 4.4),
        ], 3.2, 6.7, Material::Shell, Material::Dark);
        let engine = V3::new(ENGINE_HOUSING_X, side * ENGINE_Y, 1.5);
        mesh.ellipsoid(engine, V3::new(5.2, 5.2, 4.0), 12, 6, Material::Shell);
        mesh.torus(engine + V3::new(-3.4, 0.0, 0.0), 3.7, 0.78, 12, 6, 0, Material::Glow);
        mesh.torus(engine + V3::new(-3.8, 0.0, 0.0), 2.4, 0.48, 10, 5, 0, Material::Dark);
        mesh.ellipsoid(engine + V3::new(-4.3, 0.0, 0.0), V3::new(1.2, 2.3, 2.3), 8, 4, Material::Eye);
    }
    // Dark canopy with its core dome and amber nose stripe.
    let f_start = mesh.faces.len();
    extruded_plate(&mut mesh, &mirror_outline(&[(19.0, 0.0), (13.0, 4.6), (4.0, 6.4), (-3.0, 4.6), (-5.0, 0.0)]),
        6.8, 9.4, Material::Dark, Material::ShellLight);
    mesh.ellipsoid(V3::new(8.0, 0.0, 9.4), V3::new(4.2, 3.4, 1.5), 12, 7, Material::Core);
    tapered_rod(&mut mesh, V3::new(18.0, 0.0, 9.5), V3::new(27.0, 0.0, 6.8), 1.2, 0.6, 7, Material::Accent);
    extruded_plate(&mut mesh, &mirror_outline(&[(8.0, 0.0), (4.0, 3.0), (-3.0, 3.0), (-6.0, 0.0)]),
        8.2, 9.0, Material::ShellLight, Material::Dark);
    mesh.with_bias(f_start, -2.5);
    mesh
}

/// Articulated parts: the flapping wing pair and the twin thruster glow.
pub(crate) fn animated_parts(a: &EnemyAnim<'_>) -> Mesh {
    let EnemyAnim { time, seed, windup, reduce_motion, move_speed, .. } = *a;
    let mut mesh = Mesh::default();
    let thrust = (move_speed / FULL_SPEED).clamp(0.0, 1.0);
    let w = windup.clamp(0.0, 1.0);
    let lock = w * w * (3.0 - 2.0 * w);
    // Windup charges the engines too, since the flyer is still during the telegraph.
    let glow = thrust.max(lock * GLOW_LOCK);
    let flicker = if reduce_motion { 1.0 } else {
        1.0 + 0.07 * (time * 23.0 + seed).sin() + 0.04 * (time * 37.0 + seed * 1.3).sin()
    };
    // Reduced motion keeps only the calm launch pose, with no beat.
    let flap = if reduce_motion {
        FLAP_LAUNCH.1 * lock
    } else {
        let beat = (time * FLAP_RATE + seed).sin() * (FLAP_BEAT.0 + FLAP_BEAT.1 * thrust);
        beat * (1.0 - FLAP_LOCK_DAMP * lock) + FLAP_LAUNCH.0 * lock
    };
    let (hinge, span, z) = WING_HINGE;
    append_insect_wing_pair(
        &mut mesh, &WING_OUTLINE, hinge, span, z, flap, WING_HALF_DEPTH, Material::Dark,
        |mesh: &mut Mesh, side: f32, wing_point: &dyn Fn(f32, f32, f32) -> V3| {
            // Leading-edge rim riding the top face (3.6 - 0.2), amber vents, thruster glow.
            tapered_rod(mesh, wing_point(8.0, 12.0, 3.4), wing_point(-15.0, 41.0, 3.4), 0.92, 0.35, 6, Material::Glow);
            for vent in 0..VENT_COUNT {
                let x = -4.0 - vent as f32 * 3.2;
                let y = 27.0 + vent as f32 * 2.0;
                tapered_rod(mesh, wing_point(x + 1.3, y - 0.5, 3.8), wing_point(x - 1.1, y + 0.5, 3.8), 0.76, 0.48, 4, Material::Accent);
            }
            let engine = V3::new(ENGINE_NOZZLE_X, side * ENGINE_Y, 1.5);
            tapered_rod(mesh, engine, engine + V3::new(-2.0 - glow * 7.0 * flicker, 0.0, -0.25), 1.9 + glow * 0.7, 0.12, 6, Material::Glow);
            if glow > 0.08 {
                tapered_rod(mesh, engine + V3::new(-0.4, 0.0, 0.0), engine + V3::new(-1.3 - glow * 4.0 * flicker, 0.0, -0.1),
                    0.82 + glow * 0.18, 0.04, 5, Material::Bone);
            }
        },
    );
    mesh
}
