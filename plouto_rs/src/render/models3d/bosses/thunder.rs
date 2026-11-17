//! Boss thunder (Storm Sovereign): an upright armored cross around a recessed
//! cyan vortex, gold filigree, and four suspended lightning crystals.
use super::super::geom::*;
use crate::sim::enemy::Enemy;

/// Uniform mesh fit before the shared 1.08 presentation scale. The cross and
/// crystals may extend slightly beyond the 40-unit gameplay body radius.
const FIT: f32 = 0.66;
/// Crossbar and vortex centre along z (the art's cross sits above centre).
const CROSS_Z: f32 = 10.0;
/// Animated crystal anchors (x, z) in art order: right, top, left, bottom.
const ORBIT: [(f32, f32); 4] = [(41.0, 10.0), (0.0, 44.0), (-41.0, 10.0), (0.0, -36.0)];

const OUTER_CROSS: &[(f32, f32)] = &[
    (0.0, 48.0), (5.0, 38.0), (7.0, 22.0), (16.0, 17.0), (38.0, 15.0), (52.0, 10.0),
    (38.0, 3.0), (8.0, 1.0), (8.0, -21.0), (6.0, -45.0), (0.0, -58.0),
    (-6.0, -45.0), (-8.0, -21.0), (-8.0, 1.0), (-38.0, 3.0), (-52.0, 10.0),
    (-38.0, 15.0), (-16.0, 17.0), (-7.0, 22.0), (-5.0, 38.0),
];
const INNER_CROSS: &[(f32, f32)] = &[
    (0.0, 41.0), (4.0, 33.0), (5.0, 20.0), (12.0, 15.0), (32.0, 13.0), (42.0, 10.0),
    (32.0, 6.0), (7.0, 4.0), (6.0, -19.0), (4.4, -41.0), (0.0, -51.0),
    (-4.4, -41.0), (-6.0, -19.0), (-7.0, 4.0), (-32.0, 6.0), (-42.0, 10.0),
    (-32.0, 13.0), (-12.0, 15.0), (-5.0, 20.0), (-4.0, 33.0),
];
const CENTER_SPINE: &[(f32, f32)] = &[
    (0.0, 45.0), (3.6, 32.0), (8.0, 18.0), (9.0, 10.0), (8.0, 2.0), (3.6, -12.0),
    (0.0, -25.0), (-3.6, -12.0), (-8.0, 2.0), (-9.0, 10.0), (-8.0, 18.0), (-3.6, 32.0),
];

fn fit(mut mesh: Mesh) -> Mesh {
    for f in &mut mesh.faces {
        f.a = f.a * FIT;
        f.b = f.b * FIT;
        f.c = f.c * FIT;
    }
    mesh
}

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    mesh.torus(V3::new(0.0, 4.4, 0.0), 25.0, 1.7, 20, 7, 1, Material::Glow);
    extruded_xz_plate(&mut mesh, OUTER_CROSS, 8.5, -8.5, Material::Shell, Material::Shell, Material::ShellLight);
    for s in [-1.0_f32, 1.0] {
        extruded_xz_plate(&mut mesh, INNER_CROSS, s * 7.5, s * 9.8, Material::ShellLight, Material::ShellLight, Material::Shell);
    }

    // Matching front and back faces keep the artifact detailed as it turns.
    for face in [-1.0_f32, 1.0] {
        extruded_xz_plate(&mut mesh, CENTER_SPINE, face * 9.5, face * 10.2, Material::Shell, Material::Dark, Material::Accent);
        let vortex = |y: f32| V3::new(0.0, face * y, CROSS_Z);
        mesh.torus(vortex(9.4), 17.0, 1.55, 20, 7, 1, Material::Accent);
        mesh.torus(vortex(10.2), 12.2, 1.5, 16, 4, 1, Material::Glow);
        mesh.ellipsoid(vortex(10.6), V3::new(9.7, 2.3, 9.7), 16, 6, Material::Dark);
        mesh.ellipsoid(vortex(11.3), V3::new(7.8, 1.9, 7.8), 16, 6, Material::Core);
        // Gold rods: the vertical limbs on x=0 and the crossbar on z=CROSS_Z.
        let y = face * 10.5;
        for direction in [-1.0_f32, 1.0] {
            tapered_rod(&mut mesh, V3::new(0.0, y, direction * 18.0), V3::new(0.0, y, direction * 37.0), 2.0, 1.0, 8, Material::Accent);
            tapered_rod(&mut mesh, V3::new(direction * 18.0, y, CROSS_Z), V3::new(direction * 37.0, y, CROSS_Z), 2.0, 1.0, 8, Material::Accent);
        }
    }
    fit(mesh)
}

/// Articulated (pose-driven) parts for this boss.
pub(crate) fn animated_parts(e: &Enemy, time: f32, windup: f32, reduce_motion: bool) -> Mesh {
    let mut mesh = Mesh::default();
    let wave = |rate: f32, phase: f32, amp: f32| {
        if reduce_motion { 0.0 } else { (time * rate + phase).sin() * amp }
    };
    let speed = if reduce_motion {
        0.0
    } else {
        let cruise_speed = (e.speed * 0.4).max(1.0);
        ((e.vel.x * e.vel.x + e.vel.y * e.vel.y).sqrt() / cruise_speed).min(1.0)
    };
    // Idle breathing grows with speed; the windup damps it and coils the crystals inward.
    let pulse = wave(2.1, e.seed, 1.35 + 0.9 * speed) * (1.0 - windup);
    let coil = windup * windup * 4.5;
    let drift = wave(1.2, e.seed, 0.055 + 0.05 * speed);
    let (sd, cd) = drift.sin_cos();
    for (i, &(bx, bz)) in ORBIT.iter().enumerate() {
        let (ax, az) = (bx * cd - bz * sd, bx * sd + bz * cd);
        let len = (ax * ax + az * az).sqrt();
        let dir = V3::new(ax / len, 0.0, az / len);
        let push = pulse - coil;
        // Charge rattle ramps with windup; calm pose under reduced motion.
        let tilt = wave(1.7 + 7.0 * windup, i as f32, 0.06 + 0.14 * windup);
        let (hw, hh) = if i % 2 == 0 { (8.2, 5.8) } else { (5.8, 8.2) };
        for face in [-1.0_f32, 1.0] {
            let crystal = V3::new(ax, face * 11.2, az) + dir * push;
            let root = dir * 18.0 + V3::new(0.0, face * 9.5, 0.0);
            tapered_rod(&mut mesh, root, crystal - dir * 7.4, 2.15, 0.8, 6, Material::ShellLight);
            mesh.torus(crystal, 6.6, 1.0, 12, 4, 1, Material::Accent);
            crystal_xz(&mut mesh, crystal, hw, hh, 3.8, face, tilt, Material::Glow, Material::Core);
        }
    }
    fit(mesh)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Static body reach, in world units at the enlarged boss draw scale, stays within the 40-unit target.
    #[test]
    fn body_reach_fits_hitbox_target() {
        let reach = build_mesh()
            .faces
            .iter()
            .flat_map(|f| [f.a, f.b, f.c])
            .map(|v| (v.x * v.x + v.z * v.z).sqrt())
            .fold(0.0_f32, f32::max);
        assert!(
            reach * 35.28 / 34.0 * crate::render::models3d::boss_model_visual_scale("boss_thunder") <= 40.0,
            "static reach {reach}"
        );
    }
}
