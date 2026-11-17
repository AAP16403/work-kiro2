//! Bomber role: quad-X mine layer. Static body, so there are no articulated parts.
use super::super::geom::*;
use super::super::EnemyAnim;

// The hull plate intentionally extends beyond the gameplay radius at presentation scale.
// Keep that fringe narrow so bomb arms read clearly while the simulation circle remains
// the authoritative damage/contact boundary.
const PLATE_R: f32 = 13.1;
const PLATE_D: f32 = 9.3;
const HULL_R: f32 = 11.3;
const EQUATOR_Z: f32 = -1.4;
const ARM_IN_XY: f32 = 5.2;
const ARM_OUT_XY: f32 = 13.5;
const ARM_IN_Z: f32 = -0.8;
const ARM_OUT_Z: f32 = -1.0;

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    // Quad-X heavy mine-layer (`enemy-bomber.png`): tall graphite pod, four slim
    // amber-capped bomb arms, cyan edge lights and a recessed furnace port.
    mesh.cylinder_z(V3::ZERO, HULL_R, -7.2, 4.4, 12, Material::Shell);
    mesh.torus(V3::new(0.0, 0.0, EQUATOR_Z), HULL_R + 0.3, 0.9, 16, 5, 2, Material::ShellLight);
    extruded_plate(&mut mesh, &[
        (PLATE_R, 0.0), (PLATE_D, PLATE_D), (0.0, PLATE_R), (-PLATE_D, PLATE_D),
        (-PLATE_R, 0.0), (-PLATE_D, -PLATE_D), (0.0, -PLATE_R), (PLATE_D, -PLATE_D),
    ], 3.8, 5.8, Material::Shell, Material::Dark);
    for side in [-1.0_f32, 1.0] {
        for forward in [-1.0_f32, 1.0] {
            let inner = V3::new(forward * ARM_IN_XY, side * ARM_IN_XY, ARM_IN_Z);
            let outer = V3::new(forward * ARM_OUT_XY, side * ARM_OUT_XY, ARM_OUT_Z);
            tapered_rod(&mut mesh, inner, outer, 2.6, 1.9, 8, Material::ShellLight);
            mesh.cylinder_z(outer, 3.4, ARM_OUT_Z - 2.4, ARM_OUT_Z + 2.4, 10, Material::Dark);
            mesh.torus(outer + V3::new(0.0, 0.0, 2.6), 2.8, 0.6, 12, 5, 2, Material::Accent);
            mesh.ellipsoid(outer + V3::new(0.0, 0.0, 3.1), V3::new(1.9, 1.9, 1.1), 9, 5, Material::Glow);
            // Cyan edge light running along the top of the arm.
            tapered_rod(
                &mut mesh,
                V3::new(forward * 7.6, side * 7.6, 2.0),
                V3::new(forward * 13.0, side * 13.0, 1.2),
                0.6,
                0.45,
                6,
                Material::Bone,
            );
        }
    }
    // Furnace: a flush glow lens in a dark bezel, with three armored clamps on the ring.
    let f_start = mesh.faces.len();
    mesh.torus(V3::new(0.0, 0.0, 6.0), 9.0, 1.45, 18, 7, 2, Material::Accent);
    mesh.torus(V3::new(0.0, 0.0, 6.4), 6.9, 0.85, 16, 6, 2, Material::Dark);
    mesh.ellipsoid(V3::new(0.0, 0.0, 5.9), V3::new(6.0, 6.0, 1.1), 16, 8, Material::Glow);
    mesh.ellipsoid(V3::new(0.0, 0.0, 6.9), V3::new(3.8, 3.8, 1.4), 12, 6, Material::Core);
    for ang in [90.0_f32, 210.0, 330.0] {
        let (s, c) = ang.to_radians().sin_cos();
        mesh.ellipsoid(V3::new(8.3 * c, 8.3 * s, 7.0), V3::new(2.2, 2.2, 1.8), 10, 6, Material::ShellLight);
    }
    mesh.with_bias(f_start, -2.5);
    mesh
}

/// No articulated parts.
pub(crate) fn animated_parts(_a: &EnemyAnim<'_>) -> Mesh {
    Mesh::default()
}
