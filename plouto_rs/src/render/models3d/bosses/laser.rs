//! Boss laser (Prisma Overlord): a tall faceted crystal monolith with a slit eye,
//! twin dart wings, an elliptical halo and orbiting collimator pylons.
use std::f32::consts::TAU;

use super::super::geom::*;
use crate::sim::enemy::{Enemy, EnemySubState};

// The slit eye, halo and pylon orbit centre on EYE_Z; draw_boss_model pins the core glow to the same eye.
const EYE_Z: f32 = 3.5;
const EYE_X: f32 = 15.9;
const HALO_X: f32 = 7.4;
// Hex column (vertex-forward, radius 17) with pointed caps top and bottom.
const BODY_R: f32 = 17.0;
const BODY_Z0: f32 = -4.0;
const BODY_Z1: f32 = 26.0;
const CAP_TOP_Z: f32 = 36.0;
const SPIKE_TIP_Z: f32 = -34.0;
const WING_X_BACK: f32 = 12.0;
const WING_X_FRONT: f32 = 17.2;
const SPAN_FOLDED: f32 = 31.0;
const SPAN_FOLD: f32 = 9.0;
const SPAN_SPREAD: f32 = 7.0;
const SPAN_MIN: f32 = 21.0;
const SPAN_MAX: f32 = 33.0;
// Placeholder move speed for the hover flutter; replace with the Prisma's LaserMoving speed.
const HOVER_SPEED_REF: f32 = 120.0;
const PYLON_TIP_R: f32 = 25.0;
const PYLON_ROOT_R: f32 = 17.0;
const PYLON_CHARGE_SQUEEZE: f32 = 6.0;

pub(crate) fn build_mesh() -> Mesh {
    let mut mesh = Mesh::default();
    mesh.cylinder_z(V3::ZERO, BODY_R, BODY_Z0, BODY_Z1, 6, Material::Shell);
    tapered_rod(&mut mesh, V3::new(0.0, 0.0, BODY_Z1), V3::new(0.0, 0.0, CAP_TOP_Z), BODY_R, 0.7, 6, Material::ShellLight);
    tapered_rod(&mut mesh, V3::new(0.0, 0.0, BODY_Z0), V3::new(0.0, 0.0, -14.0), BODY_R, 4.0, 6, Material::Dark);
    tapered_rod(&mut mesh, V3::new(0.0, 0.0, -14.0), V3::new(0.0, 0.0, SPIKE_TIP_Z), 4.0, 1.0, 6, Material::Dark);
    // Front face plate, kept within the hex flats (|y| <= 14.2) so it does not overhang the body.
    extruded_yz_plate(
        &mut mesh,
        &[(-11.0, -4.0), (-14.2, 0.0), (-14.2, 24.0), (-11.0, 26.0), (11.0, 26.0), (14.2, 24.0), (14.2, 0.0), (11.0, -4.0)],
        10.8,
        15.6,
        Material::ShellLight,
        Material::Dark,
    );
    // Lower V crystal: flank tips at z -9.9 and the tail tip at z -35.3, as in the artwork.
    extruded_yz_plate(
        &mut mesh,
        &[(-6.5, -2.0), (-15.4, -9.9), (0.0, -35.3), (15.4, -9.9), (6.5, -2.0)],
        7.5,
        14.0,
        Material::ShellLight,
        Material::Dark,
    );
    // Elliptical halo, wider than tall, centred on the eye axis.
    append_elliptical_torus_x(&mut mesh, V3::new(HALO_X, 0.0, EYE_Z), 28.0, 20.0, 1.2, 30, 6, Material::Accent);
    append_elliptical_torus_x(&mut mesh, V3::new(HALO_X + 0.7, 0.0, EYE_Z), 24.5, 17.0, 0.72, 30, 5, Material::Glow);

    let f_start = mesh.faces.len();
    // Wide, short almond socket with an iris ring, magenta glow and a slit pupil.
    mesh.ellipsoid(V3::new(EYE_X, 0.0, EYE_Z), V3::new(2.8, 10.0, 4.8), 14, 9, Material::Dark);
    append_elliptical_torus_x(&mut mesh, V3::new(17.2, 0.0, EYE_Z), 6.2, 4.4, 1.0, 24, 8, Material::ShellLight);
    append_elliptical_torus_x(&mut mesh, V3::new(18.0, 0.0, EYE_Z), 4.6, 3.2, 0.6, 24, 6, Material::Accent);
    mesh.ellipsoid(V3::new(18.5, 0.0, EYE_Z), V3::new(2.0, 4.0, 3.2), 10, 6, Material::Glow);
    mesh.ellipsoid(V3::new(20.1, 0.0, EYE_Z), V3::new(0.9, 0.7, 2.6), 8, 6, Material::Core);
    mesh.ellipsoid(V3::new(20.8, -1.35, 5.2), V3::new(0.38, 0.62, 0.7), 8, 6, Material::Eye);
    // Crown ridges run from the cap shoulder to the apex, so they sit on the column surface.
    for (side, material) in [(-1.0_f32, Material::Glow), (1.0_f32, Material::Accent)] {
        tapered_rod(&mut mesh, V3::new(8.5, side * 14.7, BODY_Z1), V3::new(0.0, 0.0, CAP_TOP_Z), 0.9, 0.2, 6, material);
    }
    mesh.with_bias(f_start, -3.5);
    mesh
}

/// One dart wing (y/z outline) with its glow spine and accent edge.
fn push_wing(mesh: &mut Mesh, side: f32, span: f32) {
    let wing = [
        (side * 14.5, 22.0),
        (side * (span - 8.0), 14.2),
        (side * (span + 4.8), 3.7),
        (side * (span - 6.0), 7.7),
        (side * 14.5, 12.6),
    ];
    extruded_yz_plate(mesh, &wing, WING_X_BACK, WING_X_FRONT, Material::ShellLight, Material::Dark);
    tapered_rod(mesh, V3::new(17.6, side * 16.0, 14.0), V3::new(17.6, side * (span + 1.5), 4.5), 0.92, 0.42, 7, Material::Glow);
    tapered_rod(mesh, V3::new(17.5, side * 21.0, 9.0), V3::new(17.5, side * (span - 2.0), 2.0), 0.72, 0.28, 6, Material::Accent);
}

/// One collimator pylon orbiting the eye axis at `radius`.
fn push_pylon(mesh: &mut Mesh, angle: f32, radius: f32, pulse: f32) {
    let (sa, ca) = angle.sin_cos();
    let pylon = V3::new(15.0, ca * radius, EYE_Z + sa * radius);
    let root = V3::new(14.0, ca * PYLON_ROOT_R, EYE_Z + sa * PYLON_ROOT_R);
    tapered_rod(mesh, root, pylon, 2.4, 1.4, 7, Material::Accent);
    mesh.ellipsoid(pylon, V3::new(2.6, 3.2, 4.6), 8, 5, Material::ShellLight);
    mesh.ellipsoid(pylon + V3::new(1.6, 0.0, 0.0), V3::new(1.2, 1.5, 2.3) * pulse, 6, 4, Material::Glow);
}

/// Articulated (pose-driven) parts for this boss. Every term is zero under
/// reduce_motion except the windup-driven fold, which keeps the pose calm.
pub(crate) fn animated_parts(e: &Enemy, time: f32, windup: f32, reduce_motion: bool) -> Mesh {
    let mut mesh = Mesh::default();
    let sub = e.ai.sub_state;
    let w = windup.clamp(0.0, 1.0);
    let attacking = matches!(sub, EnemySubState::LaserAttack | EnemySubState::LaserWingWindup);
    let orbit = if reduce_motion { 0.0 } else { time * if attacking { 2.2 } else { 0.58 } };
    let attack_flex = if !reduce_motion && attacking { (time * 7.5 + e.seed).sin() * 1.5 } else { 0.0 };
    // Wings flutter faster the faster the boss moves; idle flutter is small.
    let hover = if reduce_motion || attacking {
        0.0
    } else {
        let speed01 = (e.vel.length() / HOVER_SPEED_REF).clamp(0.0, 1.0);
        (time * 2.6 + e.seed).sin() * (0.35 + 0.9 * speed01)
    };
    // Wings open to the fan width as the commit windup charges, then the span settles.
    let span = if sub == EnemySubState::LaserWingWindup {
        SPAN_FOLDED + SPAN_SPREAD * w
    } else {
        (SPAN_FOLDED - SPAN_FOLD * w + attack_flex + hover).clamp(SPAN_MIN, SPAN_MAX)
    };
    for side in [-1.0_f32, 1.0] {
        push_wing(&mut mesh, side, span);
    }
    // The pylons squeeze inward during the charge telegraph.
    let pylon_r = if sub == EnemySubState::LaserCharge { PYLON_TIP_R - PYLON_CHARGE_SQUEEZE * w } else { PYLON_TIP_R };
    let count = if e.ai.phase >= 2 { 4 } else { 2 };
    for i in 0..count {
        let angle = orbit + i as f32 * (TAU / count as f32);
        let pulse = if reduce_motion { 1.0 } else { 1.0 + 0.12 * (time * 5.0 + e.seed + i as f32 * 1.7).sin() };
        push_pylon(&mut mesh, angle, pylon_r, pulse);
    }
    mesh
}

#[cfg(test)]
mod tests {
    use super::build_mesh;
    use crate::render::models3d::geom::Material;

    #[test]
    fn solid_body_stays_inside_the_collision_envelope() {
        let mesh = build_mesh();
        let reach = mesh
            .faces
            .iter()
            .filter(|f| !matches!(f.material, Material::Accent | Material::Glow))
            .flat_map(|f| [f.a, f.b, f.c])
            .map(|v| (v.x * v.x + v.y * v.y).sqrt())
            .fold(0.0_f32, f32::max);
        assert!(reach <= 30.0, "solid body reach {reach} exceeds the boss collision radius");
    }
}
