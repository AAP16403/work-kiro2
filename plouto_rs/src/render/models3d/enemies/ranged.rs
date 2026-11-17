//! Ranged role: a graphite gunship with twin shoulder cannons that load and recoil.
use super::super::geom::*;
use super::super::EnemyAnim;

const SIDES: [f32; 2] = [-1.0, 1.0];
/// Fit the authored 28-unit reference span before world.rs applies the role radius
/// and shared presentation scale. Outer wings and cannon details can sit outside
/// the central gameplay hit circle.
const FIT: f32 = 20.0 / 28.0;
const GUN_X: f32 = 1.5;
const GUN_Y: f32 = 15.0;
const BARREL_Z: f32 = 11.6;
const RECOIL: f32 = 4.0; // full-windup barrel pull-back, art-scale units
const LIFT: f32 = 2.4; // full-windup barrel lift

/// Closed outline from one half (nose to tail, y >= 0), mirrored across the centreline.
fn mirrored(upper: &[(f32, f32)]) -> Vec<(f32, f32)> {
    let mut out = upper.to_vec();
    out.extend(upper.iter().rev().filter(|p| p.1 != 0.0).map(|p| (p.0, -p.1)));
    out
}

fn cannon_muzzle(side: f32, charge: f32) -> V3 { V3::new(15.0 - charge * RECOIL, side * GUN_Y, BARREL_Z + charge * LIFT) }

/// Barrel mouth for `windup` in mesh space (fitted). `mod.rs` anchors the firing glow here.
pub(crate) fn muzzle_point(side: f32, windup: f32) -> V3 {
    cannon_muzzle(side, windup.clamp(0.0, 1.0)) * FIT
}

fn fit(mut mesh: Mesh) -> Mesh {
    for f in &mut mesh.faces {
        f.a = f.a * FIT; f.b = f.b * FIT; f.c = f.c * FIT;
    }
    mesh
}

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    // Pointed graphite gunship (`enemy-ranged.png`): swept wings, twin raised cannon
    // wells, a cyan reactor and one warm rear engine.
    extruded_plate(&mut mesh, &mirrored(&[
        (31.0, 0.0), (21.0, 4.5), (15.0, 7.0), (8.0, 10.0), (2.0, 16.0),
        (-4.0, 21.0), (-12.0, 20.0), (-20.0, 13.0), (-25.0, 7.0), (-27.0, 5.5),
    ]), -4.2, 4.4, Material::Shell, Material::Dark);
    extruded_plate(&mut mesh, &mirrored(&[
        (28.0, 0.0), (20.0, 4.2), (12.0, 6.6), (5.0, 12.5), (-8.0, 17.6), (-18.0, 12.5), (-24.0, 5.5),
    ]), 4.0, 7.3, Material::ShellLight, Material::Dark);
    extruded_plate(&mut mesh, &mirrored(&[
        (29.0, 0.0), (20.0, 4.8), (7.0, 5.5), (-10.0, 4.6), (-17.0, 0.0),
    ]), 6.8, 9.0, Material::Shell, Material::Dark);

    for side in SIDES {
        let wing: Vec<(f32, f32)> = [
            (12.0, 8.0), (4.0, 14.5), (-8.0, 27.0), (-17.0, 17.0), (-21.0, 10.0), (-14.0, 7.0), (3.0, 8.0),
        ].iter().map(|&(x, y)| (x, side * y)).collect();
        extruded_plate(&mut mesh, &wing, 7.1, 8.4, Material::Shell, Material::Dark);
        // Cyan leading edge rides the wing top, following its sweep to the tip.
        let rim = [
            V3::new(12.0, side * 8.0, 8.5), V3::new(4.0, side * 14.5, 8.5),
            V3::new(-8.0, side * 27.0, 8.5), V3::new(-17.0, side * 17.0, 8.5),
        ];
        for w in rim.windows(2) {
            tapered_rod(&mut mesh, w[0], w[1], 0.42, 0.42, 6, Material::Glow);
        }
        for vent in 0..3 {
            let x = -5.5 - vent as f32 * 3.0;
            let y = side * (12.7 + vent as f32);
            tapered_rod(&mut mesh, V3::new(x + 1.4, y - side * 0.55, 8.8), V3::new(x - 1.2, y + side * 0.55, 8.9), 0.72, 0.48, 6, Material::Accent);
        }
        // Amber flank strip on the canopy shoulder.
        tapered_rod(&mut mesh, V3::new(9.0, side * 4.9, 9.15), V3::new(3.0, side * 5.4, 9.15),
            0.3, 0.3, 5, Material::Accent);

        // Raised cannon well; the barrel is articulated in `animated_parts`.
        let (gx, gy) = (GUN_X, side * GUN_Y);
        extruded_plate(&mut mesh, &[
            (gx + 4.5, gy), (gx + 3.0, gy + side * 3.8), (gx - 2.5, gy + side * 3.8),
            (gx - 4.5, gy), (gx - 2.5, gy - side * 3.8), (gx + 3.0, gy - side * 3.8),
        ], 6.4, 9.0, Material::Shell, Material::Dark);
        mesh.cylinder_z(V3::new(gx, gy, 0.0), 3.2, 8.5, 12.0, 10, Material::ShellLight);
        mesh.torus(V3::new(gx, gy, 12.0), 2.9, 0.6, 12, 5, 2, Material::Accent);
        mesh.ellipsoid(V3::new(gx, gy, 12.0), V3::new(2.0, 2.0, 0.5), 8, 4, Material::Dark);
        mesh.ellipsoid(V3::new(gx, gy, 12.2), V3::new(1.2, 1.2, 0.4), 8, 4, Material::Bone);
    }

    let f_start = mesh.faces.len();
    // Dark canopy with an amber nose spine, dark chin grille, cyan reactor.
    extruded_plate(&mut mesh, &mirrored(&[(18.5, 0.0), (12.0, 4.2), (3.0, 4.6), (-3.0, 2.4)]),
        8.6, 9.4, Material::Dark, Material::ShellLight);
    tapered_rod(&mut mesh, V3::new(14.0, 0.0, 9.0), V3::new(26.0, 0.0, 7.6), 0.7, 0.4, 6, Material::Accent);
    for j in -1..=1 {
        let y = j as f32 * 1.3;
        tapered_rod(&mut mesh, V3::new(-7.6, y, 9.15), V3::new(-10.4, y, 9.15), 0.3, 0.3, 5, Material::Dark);
    }
    extruded_plate(&mut mesh, &mirrored(&[(5.0, 0.0), (2.8, 4.1), (-2.7, 4.1), (-5.0, 0.0)]),
        8.0, 10.0, Material::Dark, Material::ShellLight);
    mesh.torus(V3::new(-0.4, 0.0, 10.1), 3.9, 0.8, 10, 4, 2, Material::Glow);
    extruded_plate(&mut mesh, &mirrored(&[(2.9, 0.0), (1.6, 2.5), (-1.6, 2.5), (-3.0, 0.0)]),
        9.8, 12.2, Material::Core, Material::Glow);

    // Single centred rear nozzle: dark housing, amber collar, warm inner glass.
    mesh.ellipsoid(V3::new(-23.0, 0.0, 1.6), V3::new(4.0, 6.0, 4.0), 10, 5, Material::Shell);
    mesh.torus(V3::new(-25.2, 0.0, 1.6), 4.0, 0.9, 12, 4, 0, Material::Accent);
    mesh.torus(V3::new(-25.7, 0.0, 1.6), 2.75, 0.55, 12, 4, 0, Material::Bone);
    mesh.ellipsoid(V3::new(-26.0, 0.0, 1.6), V3::new(1.4, 3.0, 3.0), 8, 4, Material::Bone);
    mesh.with_bias(f_start, -2.5);
    fit(mesh)
}

/// Cannons follow `windup`; the reactor breathes with time but is fixed under `reduce_motion`.
pub(crate) fn animated_parts(a: &EnemyAnim<'_>) -> Mesh {
    let EnemyAnim { windup, time, seed, reduce_motion, .. } = *a;
    let charge = windup.clamp(0.0, 1.0);
    let mut mesh = Mesh::default();
    for side in SIDES {
        let root = V3::new(2.5, side * GUN_Y, BARREL_Z);
        let muzzle = cannon_muzzle(side, charge);
        tapered_rod(&mut mesh, root, muzzle, 1.45, 1.05, 6, Material::ShellLight);
        tapered_rod(&mut mesh, root + V3::new(1.0, 0.0, 1.0), muzzle + V3::new(-0.4, 0.0, 0.8),
            0.4, 0.28, 5, Material::Accent);
        mesh.torus(muzzle, 1.35, 0.42, 8, 4, 0, Material::Accent);
        mesh.ellipsoid(muzzle + V3::new(0.35, 0.0, 0.0), V3::new(0.4, 0.9, 0.9), 6, 4, Material::Dark);
        if charge > 0.0 {
            // Cyan charge band slides out the barrel as the shot loads.
            let band = root + (muzzle - root) * (0.25 + 0.6 * charge);
            mesh.torus(band, 1.3, 0.3, 8, 4, 0, Material::Glow);
        }
    }
    let breath = if reduce_motion { 0.5 } else { 0.5 + 0.5 * (time * 2.4 + seed).sin() };
    let r = 1.0 + 0.08 * breath;
    mesh.ellipsoid(V3::new(-0.4, 0.0, 12.5), V3::new(1.9 * r, 1.9 * r, 0.85 + 0.05 * breath), 8, 4, Material::Eye);
    fit(mesh)
}
