//! Charger role: forked pincer horns that coil in for the windup and stretch out
//! on the dash, over a broad graphite delta hull with twin rear engines.
//! Units: +x forward (nose), +y lateral, +z up. The hull body is about 23.5 units
//! area-equivalent radius; wing plates and horns are visual-only.
use super::super::geom::*;
use super::super::EnemyAnim;

const HORN_ROOT: (f32, f32, f32) = (9.0, 9.5, 6.8);
const ENGINE: (f32, f32, f32) = (-18.5, 8.2, 1.0);
/// Swept wing outline for the +y side; mirrored for -y.
const WING: [(f32, f32); 7] = [
    (10.0, 14.5), (0.0, 19.5), (-10.0, 25.0), (-16.5, 29.0), (-18.5, 14.0), (-12.0, 9.0), (4.0, 8.0),
];

/// Closed outline: nose point, one side's run, optional tail, then the mirrored run.
fn sym(head: (f32, f32), upper: &[(f32, f32)], tail: Option<(f32, f32)>) -> Vec<(f32, f32)> {
    let mut pts = vec![head];
    pts.extend_from_slice(upper);
    pts.extend(tail);
    pts.extend(upper.iter().rev().map(|&(x, y)| (x, -y)));
    pts
}

/// Point with `y` scaled by the side sign.
fn at(side: f32, (x, y, z): (f32, f32, f32)) -> V3 {
    V3::new(x, side * y, z)
}

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    extruded_plate(&mut mesh, &sym(
        (22.0, 0.0),
        &[(18.0, 8.0), (7.0, 15.5), (-10.0, 20.0), (-16.5, 29.0), (-18.5, 14.0), (-19.0, 6.0)],
        Some((-18.0, 0.0)),
    ), -4.5, 4.8, Material::Shell, Material::Shell);
    extruded_plate(&mut mesh, &sym(
        (20.0, 0.0), &[(14.0, 7.0), (5.0, 12.0), (-8.0, 15.5), (-15.0, 14.0), (-16.0, 6.0)], Some((-17.0, 0.0)),
    ), 4.2, 8.3, Material::ShellLight, Material::Shell);

    for side in [-1.0_f32, 1.0] {
        let wing: Vec<(f32, f32)> = WING.iter().map(|&(x, y)| (x, side * y)).collect();
        extruded_plate(&mut mesh, &wing, 4.5, 7.4, Material::Shell, Material::ShellLight);
        // Cyan rim along the outer leading edge.
        tapered_rod(&mut mesh, V3::new(10.0, side * 14.5, 7.6), V3::new(-10.0, side * 25.0, 7.4), 0.55, 0.5, 7, Material::Glow);
        tapered_rod(&mut mesh, V3::new(-10.0, side * 25.0, 7.4), V3::new(-16.5, side * 29.0, 7.0), 0.5, 0.42, 7, Material::Glow);

        // Horn socket with an amber locking collar.
        let root = at(side, HORN_ROOT);
        mesh.ellipsoid(root, V3::new(4.6, 3.6, 2.4), 10, 6, Material::ShellLight);
        mesh.torus(root + V3::new(1.5, side * 1.8, 1.7), 2.8, 0.72, 10, 4, 2, Material::Accent);

        // Three amber heat slashes on the wing armor.
        for vent in 0..3 {
            let k = vent as f32;
            let (x, y) = (-7.0 - k * 2.4, side * (16.0 + k * 1.4));
            tapered_rod(&mut mesh, V3::new(x + 1.4, y - side * 0.8, 8.1), V3::new(x - 1.3, y + side * 0.8, 8.2), 1.1, 0.8, 5, Material::Accent);
        }

        // Twin nozzle housings with amber lip ring, bone ring and dark eye.
        let engine = at(side, ENGINE);
        mesh.ellipsoid(engine, V3::new(7.0, 6.4, 5.0), 14, 8, Material::Shell);
        mesh.torus(engine + V3::new(-6.5, 0.0, 0.0), 5.0, 0.95, 12, 5, 0, Material::Accent);
        mesh.torus(engine + V3::new(-6.8, 0.0, 0.0), 3.3, 0.62, 12, 5, 0, Material::Bone);
        mesh.ellipsoid(engine + V3::new(-7.0, 0.0, 0.0), V3::new(1.2, 3.0, 3.0), 10, 6, Material::Eye);
    }

    let canopy_first_face = mesh.faces.len();
    // Recessed black canopy with amber nose stripe and luminous core.
    extruded_plate(&mut mesh, &sym((11.0, 0.0), &[(7.5, 4.2), (0.0, 4.8), (-3.0, 3.0)], None), 7.8, 9.0, Material::Dark, Material::ShellLight);
    mesh.ellipsoid(V3::new(2.0, 0.0, 9.2), V3::new(4.4, 3.2, 1.5), 12, 7, Material::Core);
    mesh.ellipsoid(V3::new(1.5, 0.0, 9.6), V3::new(2.0, 2.0, 0.85), 10, 6, Material::Eye);
    tapered_rod(&mut mesh, V3::new(12.5, 0.0, 9.2), V3::new(17.5, 0.0, 7.2), 0.95, 0.48, 7, Material::Accent);
    // Chin block with three dark slits, just aft of the canopy.
    extruded_plate(&mut mesh, &sym((-7.5, 0.0), &[(-9.5, 3.0), (-12.5, 3.0)], Some((-14.0, 0.0))), 7.4, 8.6, Material::ShellLight, Material::Shell);
    for y in [-2.0_f32, 0.0, 2.0] {
        tapered_rod(&mut mesh, V3::new(-9.8, y, 8.7), V3::new(-12.8, y, 8.7), 0.42, 0.42, 6, Material::Dark);
    }
    // Amber centreline bar between the engines.
    tapered_rod(&mut mesh, V3::new(-15.0, 0.0, 8.6), V3::new(-19.5, 0.0, 8.6), 0.75, 0.6, 7, Material::Accent);
    mesh.with_bias(canopy_first_face, -2.5);
    mesh
}

/// Articulated parts: horns fold in on windup and extend on dash. Idle sway,
/// speed splay and flame flicker are gated by `reduce_motion`.
pub(crate) fn animated_parts(a: &EnemyAnim<'_>) -> Mesh {
    let EnemyAnim { time, seed, windup, reduce_motion, move_speed, charger_dashing, .. } = *a;
    let mut mesh = Mesh::default();
    let w = windup.clamp(0.0, 1.0);
    let charge = w * w * (3.0 - 2.0 * w);
    let dash = if charger_dashing { 1.0 } else { 0.0 };
    let calm = if reduce_motion { 0.0 } else { 1.0 };
    let speed = (move_speed / 170.0).clamp(0.0, 1.0);
    let idle = (1.0 - charge) * (1.0 - dash) * calm;
    let sway = (time * 2.2 + seed).sin() * (0.45 + 0.9 * speed) * idle;
    let splay = speed * 1.2 * idle;
    let flick = if reduce_motion { 0.0 } else { (time * 23.0 + seed).sin() * 0.5 + (time * 37.0 + seed * 1.3).sin() * 0.5 };
    for side in [-1.0_f32, 1.0] {
        let root = at(side, HORN_ROOT);
        let elbow = at(side, (17.0 - charge, 6.5 - charge * 1.5 + splay, 9.0 + charge * 2.0 + sway * 0.5));
        let arc = at(side, (23.5 + dash * 4.0 - charge * 0.5, 4.2 - charge * 1.2 - dash * 0.4 + splay * 1.4, 12.0 + charge * 3.0 + sway * 0.6));
        let tip = at(side, (
            29.0 + dash * 7.5 - charge * 0.8,
            (2.2 - charge - dash * 0.4 + splay * 1.6).max(1.4),
            15.0 + charge * 3.5 + dash * 2.5 + sway,
        ));
        tapered_rod(&mut mesh, root, elbow, 2.0, 1.6, 8, Material::ShellLight);
        mesh.ellipsoid(elbow, V3::new(2.0, 2.0, 1.8), 8, 5, Material::Dark);
        tapered_rod(&mut mesh, elbow, arc, 1.6, 1.2, 8, Material::ShellLight);
        tapered_rod(&mut mesh, arc, tip, 1.3, 0.3, 8, Material::ShellLight);

        // Hot inner edge along each claw.
        let stripe_start = root + V3::new(0.8, -side, 2.1);
        let stripe_mid = arc + V3::new(-0.6, -side * 0.9, 1.4);
        let stripe_tip = tip + V3::new(-1.0, -side * 0.4, 0.8);
        tapered_rod(&mut mesh, stripe_start, stripe_mid, 0.9, 0.62, 6, Material::Accent);
        tapered_rod(&mut mesh, stripe_mid, stripe_tip, 0.66, 0.3, 6, Material::Accent);
        mesh.ellipsoid(stripe_tip, V3::new(0.9, 1.0, 1.0), 6, 4, Material::Bone);

        // Saw teeth along the inner edge.
        for t in [0.35_f32, 0.6, 0.85] {
            let p = elbow + (arc - elbow) * t + V3::new(0.0, -side * 2.6, 0.6);
            tapered_rod(&mut mesh, p, p + V3::new(2.4, -side * 1.2, -0.5), 0.85, 0.12, 6, Material::Accent);
        }

        // Rear turbine flame: longer on dash, flickering while moving.
        let engine = at(side, (ENGINE.0 - 7.0, ENGINE.1, ENGINE.2));
        tapered_rod(&mut mesh, engine, engine + V3::new(-3.5 - dash * 8.0 - flick * 0.6, 0.0, -0.4), 2.8 + dash * 1.2, 0.18, 7, Material::Accent);
    }
    mesh
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Hull silhouette (no horn pose) keeps the art's proportions: body length
    /// about 0.83 of width, nose near x=22, wing tips near y=+/-29.
    #[test]
    fn charger_hull_keeps_artwork_proportions() {
        let (mut x0, mut x1, mut y0, mut y1) = (f32::MAX, f32::MIN, f32::MAX, f32::MIN);
        for p in build_mesh().faces.iter().flat_map(|f| [f.a, f.b, f.c]) {
            x0 = x0.min(p.x);
            x1 = x1.max(p.x);
            y0 = y0.min(p.y);
            y1 = y1.max(p.y);
        }
        let ratio = (x1 - x0) / (y1 - y0);
        assert!((0.75..=0.95).contains(&ratio), "hull length/width {ratio} drifted from the art");
        assert!((20.0..=24.0).contains(&x1), "nose at x={x1} is off the art's apex");
        assert!(((y1 - y0) * 0.5 - 29.0).abs() < 2.0, "wing tips drifted from lateral 29");
    }
}
