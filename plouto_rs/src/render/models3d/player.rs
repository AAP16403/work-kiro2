//! Player pod model: mesh construction, pod orientation helpers and `draw_player_pod`.
use crate::render::sdf::{linear_rgba_f, mix_rgb, SdfBatch};
use crate::sim::config::ISO_SCALE_Y;
use crate::sim::math::Vec2;
use crate::sim::skins::Palette;

use super::geom::*;
use super::project::*;
use super::pod_mesh;

pub(crate) struct PodMesh {
    pub(crate) mesh: Mesh,
}

pub(crate) fn build_pod_mesh() -> PodMesh {
    let mut hull = Mesh::default();
    let mut visor = Mesh::default();
    let mut features = Mesh::default();
    // Rounded spherical flight pod matching `player-classic-pod.png`:
    // upright dome, dark recessed visor window with cyan rim, two cyan oval eyes,
    // pink cheek blushes, side thruster pods with cyan rings, and top gold antenna.
    let body_r = V3::new(17.2, 18.2, 14.8);
    hull.ellipsoid(V3::ZERO, body_r, 24, 14, Material::Shell);
    // Subtle lower chin & upper crown reinforcement
    hull.ellipsoid(V3::new(5.8, 0.0, -5.8), V3::new(12.6, 13.0, 9.5), 18, 10, Material::ShellLight);

    // Raised, closed 3D visor shell cleanly proud of the forward sphere to prevent Z-fighting.
    let visor_center = V3::new(10.8, 0.0, 2.8);
    let visor_radii = V3::new(8.2, 13.6, 10.0);
    append_ellipsoid_cap_x(&mut visor, visor_center, visor_radii, 24, 8, Material::Dark);
    append_elliptical_torus_x(&mut visor, visor_center + V3::new(0.8, 0.0, 0.0), 13.8, 10.2, 1.0, 24, 8, Material::Accent);
    visor.with_bias(0, -3.5);

    // Upper brow ridge & two glowing cyan oval eyes on the curved visor surface.
    features.ellipsoid(V3::new(17.4, 0.0, 11.0), V3::new(1.1, 9.0, 1.2), 12, 7, Material::ShellLight);

    for side in [-1.0_f32, 1.0] {
        let visor_ey = side * 4.2;
        let visor_ez = 4.0_f32;
        let visor_ex = visor_center.x + visor_radii.x * (1.0 - (visor_ey / visor_radii.y).powi(2) - ((visor_ez - visor_center.z) / visor_radii.z).powi(2)).max(0.05).sqrt();
        features.ellipsoid(
            V3::new(visor_ex + 0.55, visor_ey, visor_ez),
            V3::new(1.35, 1.85, 3.0),
            12,
            8,
            Material::Eye,
        );

        // Pink/coral cheek blushes on the lower outer corners of the face.
        features.ellipsoid(
            V3::new(14.8, side * 8.6, -1.8),
            V3::new(1.6, 2.3, 1.25),
            10,
            7,
            Material::Bone,
        );

        // Side thruster pods with glowing cyan ring & core (`player-classic-pod.png`).
        let engine = V3::new(-1.8, side * 16.6, -1.4);
        hull.ellipsoid(engine, V3::new(6.1, 4.5, 4.8), 14, 9, Material::ShellLight);
        hull.torus(engine + V3::new(0.0, side * 2.1, 0.0), 3.8, 0.9, 16, 7, 1, Material::Glow);
        hull.ellipsoid(engine + V3::new(0.0, side * 2.3, 0.0), V3::new(2.2, 1.4, 2.2), 10, 7, Material::Glow);
    }

    // Three recessed vent slits on the lower chin plate.
    for side in [-1.0_f32, 0.0, 1.0] {
        features.ellipsoid(V3::new(15.6, side * 2.1, -6.2), V3::new(0.65, 0.48, 1.25), 8, 6, Material::Dark);
    }
    features.with_bias(0, -6.5);

    // Top antenna stalk + glowing gold beacon orb + rear main thruster nozzle.
    hull.cylinder_z(V3::new(-2.5, 0.0, 0.0), 3.4, 13.5, 16.0, 10, Material::ShellLight);
    hull.cylinder_z(V3::new(-2.5, 0.0, 0.0), 1.35, 15.0, 21.8, 8, Material::Accent);
    hull.ellipsoid(V3::new(-2.5, 0.0, 23.2), V3::new(2.7, 2.7, 2.7), 12, 8, Material::Core);
    let rear = V3::new(-16.2, 0.0, -0.8);
    hull.ellipsoid(rear, V3::new(3.2, 4.6, 3.6), 12, 8, Material::ShellLight);
    hull.torus_x(rear + V3::new(-1.2, 0.0, 0.0), 3.4, 0.95, Material::Accent);
    hull.ellipsoid(rear + V3::new(-1.8, 0.0, 0.0), V3::new(1.5, 2.2, 2.0), 10, 7, Material::Glow);

    let mut mesh = Mesh::default();
    mesh.faces.reserve(hull.faces.len() + visor.faces.len() + features.faces.len());
    mesh.faces.extend(hull.faces);
    mesh.faces.extend(visor.faces);
    mesh.faces.extend(features.faces);
    PodMesh { mesh }
}

pub(crate) fn player_yaw(facing: Vec2) -> f32 {
    if facing.length_squared() > 1e-5 {
        facing.y.atan2(facing.x)
    } else {
        0.0
    }
}

pub(crate) fn project_player_point(
    local: V3,
    center: [f32; 2],
    scale: f32,
    pitch: f32,
    roll: f32,
    yaw: f32,
) -> [f32; 2] {
    project_world_iso(
        rotate_world_model(local, pitch, roll, yaw) * scale,
        center[0],
        center[1],
        1.0,
    )
}

#[allow(clippy::too_many_arguments)]
pub fn draw_player_pod(
    alpha: &mut SdfBatch,
    add: &mut SdfBatch,
    center: [f32; 2],
    facing: Vec2,
    gaze: Vec2,
    scale: f32,
    roll: f32,
    pitch: f32,
    time: f32,
    opacity: f32,
    blinking: bool,
    worried: bool,
    boosting: bool,
    shield: i32,
    laser_active: bool,
    reduce_motion: bool,
    palette: &Palette,
) {
    let cap_material = |rgb: [u8; 3], max: u8| {
        [rgb[0].min(max), rgb[1].min(max), rgb[2].min(max)]
    };
    let hull = mix_rgb(palette.body, [12, 24, 38], 0.12);
    let colors = [
        cap_material(hull, 232),
        cap_material(mix_rgb(palette.body, [245, 253, 255], 0.28), 232),
        [7, 15, 28],
        cap_material(mix_rgb(palette.accent, [20, 25, 38], 0.08), 232),
        cap_material(mix_rgb(palette.glow, [12, 22, 35], 0.24), 232),
        cap_material(mix_rgb(palette.eye, [240, 255, 255], 0.18), 248),
        mix_rgb(palette.accent, [255, 255, 220], 0.18),
        cap_material(palette.cheek, 236),
    ];
    let yaw = player_yaw(facing);
    let pod = pod_mesh();
    // Rotate the real mesh in world space, then project it through the fixed
    // isometric camera. The camera no longer follows the heading, so the face
    // naturally narrows at side angles and disappears when the pod turns away.
    draw_world_mesh_culled(&pod.mesh, alpha, center, facing, scale, pitch, roll, yaw, &colors, opacity);

    let view_to_camera = V3::new(-1.0, -1.0, 2.0 * ISO_SCALE_Y / 0.82).normalized();
    let face_visible = rotate_world_model(V3::new(1.0, 0.0, 0.0), pitch, roll, yaw)
        .dot(view_to_camera)
        > 0.10;
    // The eye domes and visor are part of the 3D mesh. Tiny highlights and
    // expression marks use the same 3D transform and disappear with the face.
    for side in [-1.0_f32, 1.0].into_iter().filter(|_| face_visible) {
        let eye_local = V3::new(18.2, side * 4.2, 4.0);
        if blinking {
            let mut a = project_player_point(
                eye_local + V3::new(0.0, -2.4, 0.0),
                center,
                scale,
                pitch,
                roll,
                yaw,
            );
            let mut b = project_player_point(
                eye_local + V3::new(0.0, 2.4, 0.0),
                center,
                scale,
                pitch,
                roll,
                yaw,
            );
            a[0] += gaze.x;
            a[1] += gaze.y;
            b[0] += gaze.x;
            b[1] += gaze.y;
            alpha.line(
                a[0],
                a[1],
                b[0],
                b[1],
                2.3 * scale,
                linear_rgba_f([7, 15, 28], opacity * 0.92, 1.0),
            );
        } else {
            let glint = project_player_point(
                eye_local + V3::new(0.55, -0.45, 0.85),
                center,
                scale,
                pitch,
                roll,
                yaw,
            );
            alpha.circle(
                glint[0] + gaze.x,
                glint[1] + gaze.y,
                0.72 * scale,
                linear_rgba_f([235, 252, 255], opacity * 0.82, 1.0),
            );
        }
    }
    if !blinking && worried && face_visible {
        for side in [-1.0_f32, 1.0] {
            let mut a = project_player_point(
                V3::new(18.0, side * 4.2 - 2.2, 6.6),
                center,
                scale,
                pitch,
                roll,
                yaw,
            );
            let mut b = project_player_point(
                V3::new(18.0, side * 4.2 + 2.2, 6.6),
                center,
                scale,
                pitch,
                roll,
                yaw,
            );
            a[0] += gaze.x;
            a[1] += gaze.y;
            b[0] += gaze.x;
            b[1] += gaze.y;
            alpha.line(
                a[0],
                a[1],
                b[0],
                b[1],
                1.5 * scale,
                linear_rgba_f(palette.eye, opacity * 0.95, 1.0),
            );
        }
    }

    let pulse = if reduce_motion { 1.0 } else { 0.86 + 0.14 * (time * if boosting { 17.0 } else { 10.0 }).sin() };
    let exhaust = project_player_point(V3::new(-18.2, 0.0, -0.8), center, scale, pitch, roll, yaw);
    let exhaust_color = if boosting { [255, 155, 65] } else { palette.glow };
    add.ellipse_glow(exhaust[0], exhaust[1], 4.2 * scale * pulse, 2.2 * scale * pulse, 1.6, linear_rgba_f(exhaust_color, opacity * 0.12, 1.15));
    let beacon = project_player_point(V3::new(-2.5, 0.0, 23.2), center, scale, pitch, roll, yaw);
    // Keep the amber beacon legible as a model detail without blooming over the hull.
    add.glow(beacon[0], beacon[1], 2.8 * scale * pulse, 1.2, linear_rgba_f(palette.accent, opacity * 0.12, 1.15));
    if boosting {
        let flicker = if reduce_motion { 1.0 } else { 0.88 + 0.12 * (time * 20.0).sin().abs() };
        for (side, length, width) in [(-1.0_f32, 7.0, 1.5), (0.0, 11.0, 2.4), (1.0, 7.0, 1.5)] {
            let root = project_player_point(V3::new(-17.8, side * 1.8, -0.8), center, scale, pitch, roll, yaw);
            let tip = project_player_point(V3::new(-17.8 - length * flicker, side * 0.7, -1.0), center, scale, pitch, roll, yaw);
            let edge = project_player_point(V3::new(-17.8, side * (1.8 + width), -0.8), center, scale, pitch, roll, yaw);
            alpha.triangle(root, edge, tip, linear_rgba_f([255, 159, 65], opacity * 0.82, 1.0));
        }
        add.ellipse_glow(exhaust[0], exhaust[1], 7.0 * scale * pulse, 3.2 * scale * pulse, 1.6, linear_rgba_f([255, 145, 52], opacity * 0.22, 1.25));
    }
    if laser_active {
        add.ring(center[0], center[1], 24.0 * scale, 20.0 * scale, 2.0 * scale, linear_rgba_f([255, 110, 255], opacity * pulse, 1.8));
    }
    if shield > 0 {
        let shield_pulse = if reduce_motion { 1.0 } else { 0.88 + 0.12 * (time * 4.5).sin() };
        alpha.circle(center[0], center[1], 25.0 * scale, linear_rgba_f([75, 195, 255], opacity * 0.12 * shield_pulse, 1.0));
        add.ring(center[0], center[1], 25.0 * scale, 25.0 * scale, 2.2 * scale, linear_rgba_f([125, 225, 255], opacity * 0.72 * shield_pulse, 1.8));
        add.arc(center[0], center[1], 25.0 * scale, 2.5 * scale, time * 2.2, 1.3, linear_rgba_f([230, 250, 255], opacity * 0.72, 2.0));
    }
}
