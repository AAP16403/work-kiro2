//! Projection, shading and culled drawing for model meshes. Models rotate in
//! world space and are projected through the isometric arena camera.
use std::cell::RefCell;

use crate::render::sdf::{linear_rgba_f, SdfBatch};
use crate::sim::config::{ISO_SCALE_X, ISO_SCALE_Y};
use crate::sim::math::Vec2;

use super::geom::*;

#[derive(Clone, Copy)]
pub(crate) struct ProjectedFace {
    pub(crate) points: [[f32; 2]; 3],
    pub(crate) depth: f32,
    pub(crate) color: [u8; 3],
}

thread_local! {
    static FACE_SCRATCH: RefCell<Vec<ProjectedFace>> = RefCell::new(Vec::with_capacity(768));
}

pub(crate) fn rotate_model(mut v: V3, pitch: f32, roll: f32, yaw: f32) -> V3 {
    let (sy, cy) = yaw.sin_cos();
    v = V3::new(v.x * cy - v.y * sy, v.x * sy + v.y * cy, v.z);
    let (sp, cp) = pitch.sin_cos();
    let (sr, cr) = roll.sin_cos();
    v = V3::new(v.x * cp + v.z * sp, v.y, -v.x * sp + v.z * cp);
    V3::new(v.x, v.y * cr - v.z * sr, v.y * sr + v.z * cr)
}

pub(crate) fn rotate_world_model(mut v: V3, pitch: f32, roll: f32, yaw: f32) -> V3 {
    let (sr, cr) = roll.sin_cos();
    v = V3::new(v.x, v.y * cr - v.z * sr, v.y * sr + v.z * cr);
    let (sp, cp) = pitch.sin_cos();
    v = V3::new(v.x * cp + v.z * sp, v.y, -v.x * sp + v.z * cp);
    let (sy, cy) = yaw.sin_cos();
    V3::new(v.x * cy - v.y * sy, v.x * sy + v.y * cy, v.z)
}

pub(crate) fn screen_basis(facing: Vec2) -> ([f32; 2], [f32; 2]) {
    let f = if facing.length_squared() > 1e-5 { facing.normalized() } else { Vec2::new(1.0, 0.0) };
    let sx = (f.x - f.y) * ISO_SCALE_X;
    let sy = (f.x + f.y) * ISO_SCALE_Y;
    let len = sx.hypot(sy).max(1e-5);
    let forward = [sx / len, sy / len];
    (forward, [forward[1], -forward[0]])
}

pub(crate) fn project(v: V3, cx: f32, cy: f32, forward: [f32; 2], right: [f32; 2], scale: f32) -> [f32; 2] {
    [
        cx + (forward[0] * v.x + right[0] * v.y) * scale,
        cy + (forward[1] * v.x + right[1] * v.y) * scale + v.z * scale * 0.82,
    ]
}

pub(crate) fn project_world_iso(v: V3, cx: f32, cy: f32, scale: f32) -> [f32; 2] {
    [
        cx + (v.x - v.y) * ISO_SCALE_X * scale,
        cy + (v.x + v.y) * ISO_SCALE_Y * scale + v.z * scale * 0.82,
    ]
}

pub(crate) fn shade(base: [u8; 3], normal: V3, pitch: f32, roll: f32, yaw: f32, world_iso: bool) -> [u8; 3] {
    let transformed = if world_iso {
        rotate_world_model(normal, pitch, roll, yaw)
    } else {
        rotate_model(normal, pitch, roll, yaw)
    };
    let n = transformed.normalized();
    // Overhead isometric key light from top-front-left + warm rim fill
    let light = V3::new(0.28, -0.58, 0.76).normalized();
    let diffuse = n.dot(light).max(0.0);
    let rim = n.dot(V3::new(-0.45, -0.45, 0.77).normalized()).max(0.0).powi(3) * 0.14;
    let lower_face = if n.z < -0.25 { 0.82 } else { 1.0 };
    // Keep hull plating below the global bloom threshold; let the small eyes,
    // antenna tip, and engine parts carry the highlights instead of the whole pod.
    let factor = (0.44 + diffuse * 0.48 + rim) * lower_face;
    [
        (base[0] as f32 * factor).clamp(0.0, 255.0) as u8,
        (base[1] as f32 * factor).clamp(0.0, 255.0) as u8,
        (base[2] as f32 * factor).clamp(0.0, 255.0) as u8,
    ]
}

pub(crate) fn projected_triangle_is_stable(points: [[f32; 2]; 3]) -> bool {
    let edge_len = |a: [f32; 2], b: [f32; 2]| (b[0] - a[0]).hypot(b[1] - a[1]);
    let longest_edge = edge_len(points[0], points[1])
        .max(edge_len(points[1], points[2]))
        .max(edge_len(points[2], points[0]));
    if !longest_edge.is_finite() || longest_edge < 0.5 {
        return false;
    }
    let ab = [points[1][0] - points[0][0], points[1][1] - points[0][1]];
    let ac = [points[2][0] - points[0][0], points[2][1] - points[0][1]];
    let twice_area = ab[0] * ac[1] - ab[1] * ac[0];
    // Edge-on mesh facets can be many pixels long while being less than a
    // pixel tall. The triangle shader already antialiases the true edge, so
    // discard faces whose projected altitude is below a quarter pixel.
    twice_area.is_finite() && twice_area.abs() / longest_edge >= 0.25
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn draw_world_mesh_culled(
    mesh: &Mesh,
    alpha: &mut SdfBatch,
    center: [f32; 2],
    facing: Vec2,
    scale: f32,
    pitch: f32,
    roll: f32,
    yaw: f32,
    colors: &[[u8; 3]; 8],
    opacity: f32,
) {
    draw_meshes_combined(&[mesh], alpha, center, facing, scale, pitch, roll, yaw, colors, opacity, true, true);
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn draw_meshes_combined(
    meshes: &[&Mesh],
    alpha: &mut SdfBatch,
    center: [f32; 2],
    facing: Vec2,
    scale: f32,
    pitch: f32,
    roll: f32,
    yaw: f32,
    colors: &[[u8; 3]; 8],
    opacity: f32,
    cull_backfaces: bool,
    world_iso: bool,
) {
    if opacity <= 0.005 || scale <= 0.005 {
        return;
    }
    let (forward, right) = screen_basis(facing);
    // In our isometric projection:
    // screen_x = (x - y) * ISO_SCALE_X
    // screen_y = (x + y) * ISO_SCALE_Y + z * 0.82
    // Objects at smaller (x + y) and larger +z are closer to the elevated viewer!
    // Therefore the ray FROM the camera INTO the scene is (+1, +1, -2*ISO_SCALE_Y/0.82).
    // Larger `dot(camera_ray)` = deeper/farther away (drawn first); smaller `dot` = closer (drawn on top).
    let camera_ray = if world_iso {
        V3::new(1.0, 1.0, -(2.0 * ISO_SCALE_Y / 0.82)).normalized()
    } else {
        V3::new(
            0.82 * right[0],
            -0.82 * forward[0],
            forward[0] * right[1] - right[0] * forward[1],
        ).normalized()
    };
    FACE_SCRATCH.with(|scratch| {
        let mut projected = scratch.borrow_mut();
        projected.clear();
        for mesh in meshes {
            for face in &mesh.faces {
                let normal = (face.b - face.a).cross(face.c - face.a);
                let transform = |v| {
                    if world_iso {
                        rotate_world_model(v, pitch, roll, yaw)
                    } else {
                        rotate_model(v, pitch, roll, yaw)
                    }
                };
                if cull_backfaces && transform(normal).dot(camera_ray * -1.0) <= 0.0 {
                    continue;
                }
                let a = transform(face.a) * scale;
                let b = transform(face.b) * scale;
                let c = transform(face.c) * scale;
                let project_point = |v| {
                    if world_iso {
                        project_world_iso(v, center[0], center[1], 1.0)
                    } else {
                        project(v, center[0], center[1], forward, right, 1.0)
                    }
                };
                let pa = project_point(a);
                let pb = project_point(b);
                let pc = project_point(c);
                if !projected_triangle_is_stable([pa, pb, pc]) {
                    continue;
                }
                let color = shade(colors[face.material as usize], normal, pitch, roll, yaw, world_iso);
                projected.push(ProjectedFace {
                    points: [pa, pb, pc],
                    depth: ((a.dot(camera_ray) + b.dot(camera_ray) + c.dot(camera_ray)) / 3.0) + face.bias * scale,
                    color,
                });
            }
        }
        // Sort along the projection camera ray so front plates sit over the hull correctly.
        projected.sort_by(|a, b| b.depth.total_cmp(&a.depth));
        for face in projected.iter() {
            // Keep the actual projected triangle boundaries. SDF coverage
            // already antialiases edges; do not expand narrow facets.
            alpha.triangle(
                face.points[0], face.points[1], face.points[2],
                linear_rgba_f(face.color, opacity, 1.0),
            );
        }
    });
}
