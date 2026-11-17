//! Tank role: squat armored hull, track guards, road wheels and twin recoiling cannons.
//! Body extent is about 27 model units radially (cannon muzzle corner); the
//! broad tracks and cannons deliberately project beyond the 17.5 gameplay radius.
use super::super::geom::*;
use super::super::EnemyAnim;
use std::f32::consts::FRAC_PI_2;

const SIDES: [f32; 2] = [-1.0, 1.0];

// Outlines are authored for the +Y side and mirrored for the other side.
const HULL: [(f32, f32); 17] = [
    (25.6, 0.0), (22.4, 6.5), (17.6, 10.0), (15.2, 17.0), (6.4, 23.0), (-6.4, 25.0), (-17.0, 20.0),
    (-21.0, 16.0), (-23.5, 11.0), (-23.5, -11.0), (-21.0, -16.0), (-17.0, -20.0), (-6.4, -25.0),
    (6.4, -23.0), (15.2, -17.0), (17.6, -10.0), (22.4, -6.5),
];
const DECK: [(f32, f32); 14] = [
    (22.4, 0.0), (18.4, 7.5), (13.6, 12.5), (9.6, 19.0), (-5.6, 21.5), (-15.5, 18.0),
    (-20.0, 11.0), (-21.0, 0.0), (-20.0, -11.0), (-15.5, -18.0), (-5.6, -21.5),
    (9.6, -19.0), (13.6, -12.5), (18.4, -7.5),
];
const CENTER_PLATE: [(f32, f32); 10] = [
    (24.0, 0.0), (17.6, 5.8), (10.4, 7.2), (-2.4, 6.0), (-10.4, 3.0),
    (-15.2, 0.0), (-10.4, -3.0), (-2.4, -6.0), (10.4, -7.2), (17.6, -5.8),
];
const SHOULDER_TOP: [(f32, f32); 8] = [
    (11.2, 7.0), (7.2, 15.0), (0.0, 20.0), (-11.2, 18.0),
    (-18.4, 11.0), (-16.8, 7.0), (-5.6, 10.0), (3.2, 7.0),
];
const SHOULDER_LOW: [(f32, f32); 6] = [
    (3.2, 13.8), (0.0, 18.4), (-10.4, 18.1), (-15.2, 14.2), (-9.6, 11.4), (-2.4, 12.0),
];
const TRACK_GUARD: [(f32, f32); 7] = [
    (12.0, 19.0), (7.0, 25.0), (-14.0, 23.5), (-21.0, 18.0), (-15.0, 17.0), (-8.0, 20.0), (6.0, 20.0),
];
const REACTOR_SOCKET: [(f32, f32); 6] = [
    (6.0, 0.0), (3.36, 7.2), (-3.36, 7.2), (-6.8, 0.0), (-3.36, -7.2), (3.36, -7.2),
];
const REACTOR_CRYSTAL: [(f32, f32); 6] = [
    (4.16, 0.0), (2.16, 4.7), (-2.08, 4.7), (-4.16, 0.0), (-2.08, -4.7), (2.16, -4.7),
];
const GUN_OUTLINE: [(f32, f32); 7] = [
    (6.4, 0.0), (4.56, 6.8), (-0.8, 8.0), (-6.4, 4.3), (-6.4, -4.3), (-0.8, -8.0), (4.56, -6.8),
];

const GUN_X: f32 = 5.6;
const GUN_Y: f32 = 11.3;
const WHEEL_COUNT: usize = 4;
const WHEEL_X0: f32 = -8.5;
const WHEEL_PITCH: f32 = 5.4;
const WHEEL_Y: f32 = 22.0;
const WHEEL_Z: f32 = -2.8;
const COOLING_SLOT_Y: [f32; 3] = [-2.4, 0.0, 2.4];
const CANNON_ROOT_X: f32 = 7.5;
const CANNON_REST_X: f32 = 23.5;
const CANNON_Z: f32 = 15.6;
const RECOIL_DISTANCE: f32 = 4.2;
const MUZZLE_LIFT: f32 = 1.2;
const ROOT_LIFT: f32 = 0.4;
const SUSPENSION_RATE: f32 = 16.0;
const SUSPENSION_PUSH_CAP: f32 = 0.67;
const SUSPENSION_AMPLITUDE: f32 = 0.48;

/// Mirrors a +Y outline to the given side (`side` is -1 or 1).
fn mirror(points: &[(f32, f32)], side: f32) -> Vec<(f32, f32)> {
    points.iter().map(|&(x, y)| (x, y * side)).collect()
}

fn add_hull(mesh: &mut Mesh) {
    extruded_plate(mesh, &HULL, -5.8, 4.4, Material::Shell, Material::Dark);
    // Cyan rim along the exposed base outline on the nose and flanks.
    for i in 0..HULL.len() {
        let (ax, ay) = HULL[i];
        let (bx, by) = HULL[(i + 1) % HULL.len()];
        if (ax + bx) * 0.5 > -17.0 {
            tapered_rod(mesh, V3::new(ax, ay, 4.6), V3::new(bx, by, 4.6), 0.3, 0.3, 5, Material::Glow);
        }
    }
    extruded_plate(mesh, &DECK, 4.2, 8.2, Material::ShellLight, Material::Dark);
    extruded_plate(mesh, &CENTER_PLATE, 7.6, 10.0, Material::Shell, Material::Dark);
    // Three amber bars across the rear center plate.
    for k in [-1.0_f32, 0.0, 1.0] {
        tapered_rod(mesh, V3::new(-15.5, k * 3.6, 8.6), V3::new(-19.5, k * 3.6, 8.4), 0.8, 0.6, 7, Material::Accent);
    }
}

fn add_side_hardware(mesh: &mut Mesh, side: f32) {
    // Segmented shoulder armor with a darker inner panel.
    extruded_plate(mesh, &mirror(&SHOULDER_TOP, side), 7.9, 10.2, Material::ShellLight, Material::Dark);
    extruded_plate(mesh, &mirror(&SHOULDER_LOW, side), 9.8, 11.0, Material::Shell, Material::Dark);

    // Low track guard with a cyan edge strip along its top.
    extruded_plate(mesh, &mirror(&TRACK_GUARD, side), -1.6, 4.8, Material::Shell, Material::Dark);
    tapered_rod(
        mesh,
        V3::new(9.0, side * 21.0, 5.6),
        V3::new(-18.0, side * 20.0, 5.2),
        0.6,
        0.4,
        8,
        Material::Glow,
    );
    // Amber drive bars on the outer track pod.
    tapered_rod(mesh, V3::new(-5.0, side * 22.5, 5.3), V3::new(-12.0, side * 22.5, 5.3), 0.9, 0.7, 7, Material::Accent);

    // Three heat slashes on each shoulder panel.
    for vent in 0..3 {
        let x = -6.8 - vent as f32 * 3.04;
        let y = side * (14.1 + vent as f32 * 1.15);
        tapered_rod(
            mesh,
            V3::new(x + 2.6, y - side * 0.7, 11.1),
            V3::new(x - 2.6, y + side * 0.7, 11.2),
            1.5,
            1.2,
            7,
            Material::Accent,
        );
    }

    // Raised weapon well: graphite collar, amber lip and a recessed bore.
    let (gx, gy) = (GUN_X, side * GUN_Y);
    let gun_outline: Vec<(f32, f32)> = GUN_OUTLINE.iter().map(|&(dx, dy)| (GUN_X + dx, (GUN_Y + dy) * side)).collect();
    extruded_plate(mesh, &gun_outline, 8.0, 12.0, Material::Shell, Material::Dark);
    mesh.ellipsoid(V3::new(gx, gy, 13.2), V3::new(5.9, 7.0, 3.0), 12, 6, Material::ShellLight);
    mesh.cylinder_z(V3::new(gx, gy, 0.0), 5.1, 12.8, 17.1, 14, Material::Dark);
    mesh.torus(V3::new(gx, gy, 17.0), 4.6, 0.88, 12, 5, 2, Material::Accent);
    mesh.ellipsoid(V3::new(gx, gy, 17.0), V3::new(3.45, 3.45, 0.72), 12, 4, Material::Dark);
    mesh.ellipsoid(V3::new(gx + 0.2, gy, 17.25), V3::new(2.35, 2.35, 0.62), 10, 4, Material::Bone);
}

fn add_reactor(mesh: &mut Mesh) {
    // Dark hex socket, cyan bevelled frame and a brighter faceted crystal.
    extruded_plate(mesh, &REACTOR_SOCKET, 8.2, 11.0, Material::Dark, Material::ShellLight);
    mesh.torus(V3::new(-0.24, 0.0, 11.2), 6.5, 1.0, 16, 6, 2, Material::Glow);
    extruded_plate(mesh, &REACTOR_CRYSTAL, 10.8, 14.2, Material::Core, Material::Glow);
    mesh.ellipsoid(V3::new(-0.24, 0.0, 14.5), V3::new(2.3, 2.8, 1.2), 10, 5, Material::Eye);
}

fn add_nose(mesh: &mut Mesh) {
    // Amber spine lamp on the pointed nose, sitting on the center plate.
    tapered_rod(mesh, V3::new(16.5, 0.0, 10.2), V3::new(23.5, 0.0, 9.4), 0.75, 0.5, 8, Material::Accent);
    for y in COOLING_SLOT_Y {
        tapered_rod(mesh, V3::new(13.5, y, 10.3), V3::new(10.5, y, 10.3), 0.85, 0.7, 6, Material::Dark);
    }
}

/// Static hull, guards, weapon wells and reactor.
pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    add_hull(&mut mesh);
    for side in SIDES {
        add_side_hardware(&mut mesh, side);
    }
    add_reactor(&mut mesh);
    add_nose(&mut mesh);
    mesh
}

fn add_road_wheels(mesh: &mut Mesh, side: f32, suspension: f32, track_phase: f32) {
    // Four exposed road wheels rotate with travel while the track pod stays fixed.
    for index in 0..WHEEL_COUNT {
        let wheel = V3::new(WHEEL_X0 + index as f32 * WHEEL_PITCH, side * WHEEL_Y, WHEEL_Z + suspension);
        mesh.ellipsoid(wheel, V3::new(3.2, 2.25, 3.35), 10, 5, Material::Dark);
        mesh.torus(wheel + V3::new(0.0, side * 1.45, 0.0), 2.35, 0.42, 12, 4, 1, Material::ShellLight);
        for spoke in 0..4 {
            let angle = track_phase + spoke as f32 * FRAC_PI_2 + index as f32 * 0.32;
            let inner = wheel + V3::new(angle.cos() * 0.55, side * 2.1, angle.sin() * 0.55);
            let outer = wheel + V3::new(angle.cos() * 2.05, side * 2.1, angle.sin() * 2.05);
            tapered_rod(mesh, inner, outer, 0.36, 0.24, 4, Material::ShellLight);
        }
    }
}

fn add_cannon(mesh: &mut Mesh, side: f32, attack: f32, recoil: f32, suspension: f32) {
    // Twin cannons recoil as the windup builds and brace upward slightly.
    let root = V3::new(CANNON_ROOT_X, side * GUN_Y, CANNON_Z + suspension + attack * ROOT_LIFT);
    let muzzle = V3::new(CANNON_REST_X - recoil, side * GUN_Y, CANNON_Z + suspension + attack * MUZZLE_LIFT);
    tapered_rod(mesh, root, muzzle, 3.0, 2.15, 10, Material::ShellLight);
    tapered_rod(
        mesh,
        root + V3::new(1.8, 0.0, 0.2),
        muzzle - V3::new(1.3, 0.0, 0.0),
        1.25,
        0.92,
        8,
        Material::Dark,
    );
    mesh.torus_x(muzzle, 2.15, 0.55, Material::Accent);
    mesh.ellipsoid(muzzle + V3::new(0.16, 0.0, 0.0), V3::new(0.9, 1.5, 1.5), 9, 6, Material::Bone);
}

/// Articulated (pose-driven) parts for this role.
pub(crate) fn animated_parts(a: &EnemyAnim<'_>) -> Mesh {
    let EnemyAnim { time, seed, tank_push, tank_attack, move_speed, reduce_motion, .. } = *a;
    let mut mesh = Mesh::default();
    // Ease-out windup: most of the telegraph happens early and settles at the peak.
    let t = tank_attack.clamp(0.0, 1.0);
    let attack = 1.0 - (1.0 - t) * (1.0 - t);
    let recoil = attack * RECOIL_DISTANCE;
    let suspension = if reduce_motion || tank_push <= 0.0 {
        0.0
    } else {
        (time * SUSPENSION_RATE + seed).sin() * tank_push.clamp(0.0, SUSPENSION_PUSH_CAP) * SUSPENSION_AMPLITUDE
    };
    let track_phase = if reduce_motion || move_speed <= 1.0 {
        0.0
    } else {
        time * (move_speed / 3.2) + seed * 0.13
    };
    for side in SIDES {
        add_road_wheels(&mut mesh, side, suspension, track_phase);
        add_cannon(&mut mesh, side, attack, recoil, suspension);
    }
    mesh
}
