//! Swarm role: delta fighter with a forward optic, beating wing pair and cyan lift engine.
use super::super::geom::*;
use super::super::EnemyAnim;

const SIDES: [f32; 2] = [-1.0, 1.0];

/// Delta hull outline in the mesh frame (nose at +X). Wing tips sit near x = -11.5, lateral +/-24.
const HULL: [(f32, f32); 12] = [
    (28.0, 0.0), (17.0, 6.2), (8.0, 11.5), (-4.0, 18.8), (-11.5, 24.0), (-15.0, 13.0),
    (-18.5, 0.0), (-15.0, -13.0), (-11.5, -24.0), (-4.0, -18.8), (8.0, -11.5), (17.0, -6.2),
];
/// Shoulder plate outline on the +Y side; mirrored for the other side.
const SHOULDER: [(f32, f32); 6] = [(10.0, 7.0), (2.5, 12.5), (-7.0, 19.5), (-11.5, 22.0), (-10.5, 15.0), (-7.5, 9.0)];

const WING_OUTLINE: [(f32, f32); 7] = [
    (8.0, 8.0), (4.0, 12.0), (-3.0, 20.0), (-11.5, 24.0), (-10.5, 17.0), (-8.0, 12.0), (-2.0, 7.0),
];
const WING_HINGE_X: f32 = 5.0;
const WING_HINGE_SPAN: f32 = 3.0;
const WING_HINGE_Z: f32 = 5.8;
const WING_THICKNESS: f32 = 1.0;

const FLAP_RATE: f32 = 17.0;
const FLAP_BASE_AMPLITUDE: f32 = 0.16;
const FLAP_SPEED_AMPLITUDE: f32 = 0.14;
const FLAP_FULL_SPEED: f32 = 170.0;
/// Wings fold down by this much at the peak of the surge telegraph.
const SURGE_TUCK: f32 = 0.20;

/// Dorsal dome: a rounded shell whose top follows z = 4.3 + 5.2 * sqrt(1 - (x / 17.2)^2).
const DOME_CENTER: V3 = V3 { x: 0.0, y: 0.0, z: 4.3 };
const DOME_RADII: V3 = V3 { x: 17.2, y: 12.2, z: 5.2 };

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    extruded_plate(&mut mesh, &HULL, -1.8, 4.8, Material::Shell, Material::Dark);
    mesh.ellipsoid(DOME_CENTER, DOME_RADII, 16, 10, Material::ShellLight);

    for side in SIDES {
        let shoulder: Vec<(f32, f32)> = SHOULDER.iter().map(|&(x, y)| (x, side * y)).collect();
        extruded_plate(&mut mesh, &shoulder, 3.8, 7.0, Material::ShellLight, Material::Dark);
        tapered_rod(
            &mut mesh,
            V3::new(14.0, side * 5.5, 6.5),
            V3::new(-14.0, side * 21.0, 6.1),
            1.05,
            0.52,
            8,
            Material::Glow,
        );
        for mark in 0..2 {
            add_wing_slash(&mut mesh, side, mark);
        }
    }

    // Orange dorsal stripe running from the nose back along the dome crest (two segments
    // so the chord stays on the dome surface).
    tapered_rod(&mut mesh, V3::new(24.0, 0.0, 5.0), V3::new(16.5, 0.0, 6.1), 0.6, 0.6, 6, Material::Accent);
    tapered_rod(&mut mesh, V3::new(16.5, 0.0, 6.1), V3::new(11.0, 0.0, 8.65), 0.6, 0.65, 6, Material::Accent);

    // Forward optic on a dorsal hood, centred about 25 units behind the nose as in the art.
    mesh.ellipsoid(V3::new(1.2, 0.0, 8.0), V3::new(3.0, 8.2, 7.2), 14, 9, Material::Dark);
    mesh.torus_x(V3::new(2.2, 0.0, 8.0), 7.0, 1.5, Material::ShellLight);
    mesh.torus_x(V3::new(3.05, 0.0, 8.0), 5.5, 0.48, Material::Accent);
    mesh.ellipsoid(V3::new(3.4, 0.0, 8.0), V3::new(2.2, 5.0, 4.8), 14, 9, Material::Core);
    mesh.ellipsoid(V3::new(5.45, -1.7, 9.4), V3::new(0.65, 1.25, 1.25), 10, 7, Material::Eye);

    // Three dark vent slots on the rear dome, running fore and aft as in the art.
    for i in 0..3 {
        let y = (i as f32 - 1.0) * 3.4;
        tapered_rod(&mut mesh, V3::new(-7.8, y, 9.1), V3::new(-10.6, y, 8.6), 0.42, 0.42, 5, Material::Dark);
    }

    // Cyan lift engine: a dark collar that runs past the rear notch, ending in a glowing nozzle ring.
    tapered_rod(&mut mesh, V3::new(-15.5, 0.0, 0.8), V3::new(-19.5, 0.0, 0.8), 2.4, 2.1, 10, Material::Dark);
    mesh.torus(V3::new(-19.5, 0.0, 0.8), 2.1, 0.5, 12, 5, 0, Material::Glow);
    mesh
}

/// One orange slash on a wing; `mark` 0 is the inner slash, 1 the outer one.
fn add_wing_slash(mesh: &mut Mesh, side: f32, mark: usize) {
    let x = -6.0 - mark as f32 * 3.4;
    let y = side * (18.0 + mark as f32 * 2.4);
    tapered_rod(
        mesh,
        V3::new(x + 1.0, y - side * 0.8, 7.2),
        V3::new(x - 1.6, y + side * 0.8, 7.2),
        0.9,
        0.65,
        8,
        Material::Accent,
    );
}

/// Articulated parts: the beating wing pair. Flap amplitude grows with speed; a surge
/// telegraph (`windup`) folds the wings down before the dive. Reduced motion holds the beat at zero.
pub(crate) fn animated_parts(a: &EnemyAnim<'_>) -> Mesh {
    let EnemyAnim { time, seed, windup, reduce_motion, move_speed, .. } = *a;
    let beat = if reduce_motion {
        0.0
    } else {
        let speed01 = (move_speed / FLAP_FULL_SPEED).clamp(0.0, 1.0);
        (time * FLAP_RATE + seed).sin() * (FLAP_BASE_AMPLITUDE + speed01 * FLAP_SPEED_AMPLITUDE)
    };
    let flap = beat - windup.clamp(0.0, 1.0) * SURGE_TUCK;

    let mut mesh = Mesh::default();
    append_insect_wing_pair(
        &mut mesh,
        &WING_OUTLINE,
        WING_HINGE_X,
        WING_HINGE_SPAN,
        WING_HINGE_Z,
        flap,
        WING_THICKNESS,
        Material::Accent,
        |mesh: &mut Mesh, _side: f32, wing_point: &dyn Fn(f32, f32, f32) -> V3| {
            tapered_rod(
                mesh,
                wing_point(8.0, 8.5, 7.1),
                wing_point(-10.5, 22.5, 6.7),
                0.82,
                0.38,
                7,
                Material::Glow,
            );
        },
    );
    mesh
}
