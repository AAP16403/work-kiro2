//! Engineer role: a round repair mech with a plated brow, an amber beacon, a cyan
//! chest reactor, and two articulated pincer arms with glowing claws.
use super::super::geom::*;
use super::super::EnemyAnim;

/// Idle arm sway (rad/s, amplitude in mesh units) before speed and windup scaling.
const SWAY_RATE: f32 = 5.2;
const SWAY_AMP: f32 = 1.1;
/// Claw pose at full windup: lift, pinch closing, and forward reach (mesh units).
const CLAW_LIFT: f32 = 3.8;
const CLAW_PINCH: f32 = 2.4;
const CLAW_REACH: f32 = 2.6;
/// Travel speed that counts as full motion for sway and hover (approx. engineer top speed).
const MOVE_SPEED_REF: f32 = 150.0;
const HOVER_RATE: f32 = 2.4;
const HOVER_BOB: f32 = 0.7;

fn build_shoulder(mesh: &mut Mesh, side: f32) {
    mesh.ellipsoid(V3::new(-1.0, side * 10.8, 3.4), V3::new(5.8, 3.1, 5.3), 12, 7, Material::ShellLight);
    extruded_plate(mesh, &[
        (-5.5, side * 10.0), (-3.0, side * 14.0), (3.0, side * 14.5),
        (6.5, side * 10.2), (2.0, side * 8.2),
    ], 4.2, 7.0, Material::Shell, Material::Dark);
    for vent in 0..3 {
        let x = -1.0 + vent as f32 * 2.1;
        tapered_rod(mesh, V3::new(x, side * 13.9, 5.5), V3::new(x, side * 14.1, 7.2), 0.62, 0.48, 6, Material::Accent);
    }
    // Raised dome facets keep the spherical body readable.
    extruded_plate(mesh, &[
        (-1.0, side * 5.8), (-4.5, side * 9.4), (-10.0, side * 8.0),
        (-12.2, side * 3.6), (-7.0, side * 2.7),
    ], 9.0, 11.6, Material::ShellLight, Material::Dark);
    tapered_rod(mesh, V3::new(-5.0, side * 9.0, 10.8), V3::new(-10.5, side * 7.1, 10.1), 0.62, 0.32, 7, Material::Glow);
}

fn build_optic(mesh: &mut Mesh, side: f32) {
    mesh.ellipsoid(V3::new(14.0, side * 2.8, 5.8), V3::new(1.15, 1.7, 1.35), 8, 5, Material::Core);
    tapered_rod(mesh, V3::new(13.4, side * 5.1, 8.2), V3::new(14.4, side * 1.3, 7.4), 0.92, 0.55, 7, Material::Accent);
}

fn build_bracket(mesh: &mut Mesh, side: f32) {
    extruded_plate(mesh, &[
        (9.4, side * 2.4), (7.6, side * 3.5), (3.5, side * 3.3), (4.5, side * 2.0),
    ], 0.3, 3.3, Material::Accent, Material::Dark);
}

/// One pincer arm: shoulder, elbow (with amber ring), forearm, wrist, outer and inner jaws.
fn build_claw_arm(mesh: &mut Mesh, side: f32, sway: f32, lift: f32, pinch: f32, reach: f32) {
    let shoulder = V3::new(1.5, side * 10.4, 0.5);
    let elbow = V3::new(6.0 + reach * 0.5, side * (15.0 + sway * 0.6), -1.5 + lift * 0.6);
    let wrist = V3::new(10.0 + reach, side * (17.5 + sway * 0.4), -5.0 + lift);
    let outer_tip = V3::new(13.5 + reach, side * (19.0 - pinch), -8.0 + lift);
    let inner_tip = V3::new(12.8 + reach, side * (16.0 + pinch * 0.7), -8.4 + lift);
    tapered_rod(mesh, shoulder, elbow, 2.2, 1.7, 6, Material::ShellLight);
    mesh.ellipsoid(elbow, V3::new(2.3, 2.3, 2.0), 6, 4, Material::Dark);
    mesh.torus(elbow, 2.0, 0.42, 12, 6, 1, Material::Accent);
    tapered_rod(mesh, elbow, wrist, 1.7, 1.4, 6, Material::Dark);
    mesh.ellipsoid(wrist, V3::new(2.0, 2.0, 1.8), 6, 4, Material::ShellLight);
    tapered_rod(mesh, wrist + V3::new(0.0, side * 1.2, 0.2), outer_tip, 1.5, 0.6, 6, Material::ShellLight);
    mesh.ellipsoid(outer_tip, V3::new(0.7, 0.7, 0.7), 6, 4, Material::Accent);
    // Amber inner claw, matching the artwork's glowing orange jaws.
    tapered_rod(mesh, wrist - V3::new(0.0, side * 0.8, 0.1), inner_tip, 1.25, 0.5, 6, Material::Core);
}

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    // Round repair mech (`enemy-engineer.png`): plated brow, amber optic and beacon, cyan reactor.
    mesh.ellipsoid(V3::new(0.0, 0.0, 3.0), V3::new(13.1, 12.5, 11.4), 20, 13, Material::Shell);
    // Small cyan emitter flush with the lowest point of the body.
    mesh.torus(V3::new(0.0, 0.0, -8.0), 3.2, 0.55, 14, 6, 2, Material::Glow);
    for side in [-1.0_f32, 1.0] { build_shoulder(&mut mesh, side); }
    // Beacon stalk, amber collar and globe, all on the body's vertical axis.
    tapered_rod(&mut mesh, V3::new(0.0, 0.0, 12.0), V3::new(0.0, 0.0, 17.5), 2.6, 1.2, 10, Material::Dark);
    mesh.torus(V3::new(0.0, 0.0, 16.5), 2.2, 0.62, 12, 6, 2, Material::Accent);
    mesh.ellipsoid(V3::new(0.0, 0.0, 19.8), V3::new(2.6, 2.6, 2.7), 12, 8, Material::Core);
    mesh.ellipsoid(V3::new(0.1, -0.8, 21.4), V3::new(0.72, 0.82, 0.72), 6, 4, Material::Eye);

    // Everything from here is front-facing detail and shares one depth bias.
    let f_start = mesh.faces.len();
    mesh.ellipsoid(V3::new(9.6, 0.0, 5.2), V3::new(4.1, 7.7, 4.7), 12, 7, Material::ShellLight);
    mesh.ellipsoid(V3::new(12.2, 0.0, 5.2), V3::new(2.8, 6.4, 3.4), 10, 6, Material::Dark);
    for side in [-1.0_f32, 1.0] { build_optic(&mut mesh, side); }
    // Cyan reactor clamped into the chest by amber rings and brackets.
    mesh.cylinder_z(V3::new(10.8, 0.0, 0.0), 2.55, -1.0, 5.3, 14, Material::Glow);
    for z in [-0.55_f32, 4.9] {
        mesh.torus(V3::new(10.8, 0.0, z), 2.65, 0.62, 14, 7, 2, Material::Accent);
    }
    for side in [-1.0_f32, 1.0] { build_bracket(&mut mesh, side); }
    mesh.with_bias(f_start, -2.5);
    mesh
}

/// Articulated (pose-driven) parts: arms, windup emitter and the hover ring.
/// Reduced motion zeroes every time-based term, so the attack pose stays calm and fixed.
pub(crate) fn animated_parts(a: &EnemyAnim<'_>) -> Mesh {
    let EnemyAnim { time, seed, windup, reduce_motion, move_speed, .. } = *a;
    let mut mesh = Mesh::default();
    mesh.faces.reserve(512);
    let w = windup.clamp(0.0, 1.0);
    let lift = CLAW_LIFT * w;
    let pinch = CLAW_PINCH * w;
    let reach = CLAW_REACH * w;
    // Sway grows with travel speed and is damped as the claws lock onto the drop point.
    let move_n = (move_speed / MOVE_SPEED_REF).clamp(0.0, 1.0);
    let sway_amp = SWAY_AMP * (1.0 + 0.6 * move_n) * (1.0 - 0.8 * w);
    for side in [-1.0_f32, 1.0] {
        let sway = if reduce_motion { 0.0 } else { (time * SWAY_RATE + seed + side).sin() * sway_amp };
        build_claw_arm(&mut mesh, side, sway, lift, pinch, reach);
    }
    let hover = if reduce_motion { 0.0 } else { (time * HOVER_RATE + seed).sin() * HOVER_BOB };
    mesh.torus(V3::new(0.0, 0.0, -3.6 + hover), 12.4, 0.9, 20, 8, 2, Material::Glow);
    // Emitter in front of the claws grows through windup and is absent at rest.
    if w > 0.0 {
        let r = 0.5 + 1.2 * w;
        mesh.ellipsoid(V3::new(16.0 + reach, 0.0, -4.0 + lift), V3::new(r, r, r), 8, 6, Material::Core);
    }
    mesh
}
