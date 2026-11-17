//! Shared mesh primitives for the models: vectors, materials, faces, the `Mesh`
//! builder, and the geometry helpers every role mesh and pose is built from.
use std::f32::consts::{FRAC_PI_2, PI, TAU};

#[derive(Debug, Clone, Copy, Default)]
pub(crate) struct V3 {
    pub(crate) x: f32,
    pub(crate) y: f32,
    pub(crate) z: f32,
}

impl V3 {
    pub(crate) const ZERO: Self = Self { x: 0.0, y: 0.0, z: 0.0 };

    pub(crate) const fn new(x: f32, y: f32, z: f32) -> Self {
        Self { x, y, z }
    }

    pub(crate) fn dot(self, rhs: Self) -> f32 {
        self.x * rhs.x + self.y * rhs.y + self.z * rhs.z
    }

    pub(crate) fn cross(self, rhs: Self) -> Self {
        Self::new(
            self.y * rhs.z - self.z * rhs.y,
            self.z * rhs.x - self.x * rhs.z,
            self.x * rhs.y - self.y * rhs.x,
        )
    }

    pub(crate) fn normalized(self) -> Self {
        let len = self.dot(self).sqrt();
        if len > 1e-6 { self * (1.0 / len) } else { Self::new(0.0, 0.0, 1.0) }
    }
}

impl std::ops::Add for V3 {
    type Output = Self;
    fn add(self, rhs: Self) -> Self { Self::new(self.x + rhs.x, self.y + rhs.y, self.z + rhs.z) }
}

impl std::ops::Sub for V3 {
    type Output = Self;
    fn sub(self, rhs: Self) -> Self { Self::new(self.x - rhs.x, self.y - rhs.y, self.z - rhs.z) }
}

impl std::ops::Mul<f32> for V3 {
    type Output = Self;
    fn mul(self, rhs: f32) -> Self { Self::new(self.x * rhs, self.y * rhs, self.z * rhs) }
}

pub(crate) fn rotate_about_axis(value: V3, axis: V3, angle: f32) -> V3 {
    let axis = axis.normalized();
    let (sin, cos) = angle.sin_cos();
    value * cos + axis.cross(value) * sin + axis * (axis.dot(value) * (1.0 - cos))
}

pub(crate) fn ring_plane_basis(normal: V3, spin: f32) -> (V3, V3) {
    let normal = normal.normalized();
    let guide = if normal.z.abs() > 0.86 { V3::new(0.0, 1.0, 0.0) } else { V3::new(0.0, 0.0, 1.0) };
    let u = rotate_about_axis(normal.cross(guide).normalized(), normal, spin);
    let v = rotate_about_axis(normal.cross(u).normalized(), normal, spin);
    (u, v)
}

#[derive(Debug, Clone, Copy)]
#[repr(usize)]
pub(crate) enum Material {
    Shell,
    ShellLight,
    Dark,
    Accent,
    Glow,
    Eye,
    Core,
    Bone,
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct Face {
    pub(crate) a: V3,
    pub(crate) b: V3,
    pub(crate) c: V3,
    pub(crate) material: Material,
    pub(crate) bias: f32,
}

#[derive(Default)]
pub(crate) struct Mesh {
    pub(crate) faces: Vec<Face>,
}

impl Mesh {
    pub(crate) fn tri(&mut self, a: V3, b: V3, c: V3, material: Material) {
        let normal = (b - a).cross(c - a);
        if normal.dot(normal) <= 1e-12 {
            return;
        }
        self.faces.push(Face { a, b, c, material, bias: 0.0 });
    }

    pub(crate) fn with_bias(&mut self, start_idx: usize, bias: f32) {
        for f in &mut self.faces[start_idx..] {
            f.bias = bias;
        }
    }

    pub(crate) fn outward_tri(&mut self, a: V3, mut b: V3, mut c: V3, center: V3, material: Material) {
        let mid = (a + b + c) * (1.0 / 3.0);
        if (b - a).cross(c - a).dot(mid - center) < 0.0 {
            std::mem::swap(&mut b, &mut c);
        }
        self.tri(a, b, c, material);
    }

    pub(crate) fn ellipsoid(&mut self, center: V3, radii: V3, longitude: usize, latitude: usize, material: Material) {
        let mut rings = Vec::with_capacity(latitude + 1);
        for lat in 0..=latitude {
            let phi = -PI * 0.5 + PI * lat as f32 / latitude as f32;
            let cp = phi.cos();
            let sp = phi.sin();
            let mut ring = Vec::with_capacity(longitude + 1);
            for lon in 0..=longitude {
                let theta = TAU * lon as f32 / longitude as f32;
                ring.push(center + V3::new(
                    radii.x * cp * theta.cos(),
                    radii.y * cp * theta.sin(),
                    radii.z * sp,
                ));
            }
            rings.push(ring);
        }
        for lat in 0..latitude {
            for lon in 0..longitude {
                let a = rings[lat][lon];
                let b = rings[lat][lon + 1];
                let c = rings[lat + 1][lon + 1];
                let d = rings[lat + 1][lon];
                self.outward_tri(a, b, c, center, material);
                self.outward_tri(a, c, d, center, material);
            }
        }
    }

    pub(crate) fn torus_x(&mut self, center: V3, radius: f32, tube: f32, material: Material) {
        self.torus(center, radius, tube, 18, 7, 0, material);
    }

    pub(crate) fn torus(&mut self, center: V3, radius: f32, tube: f32, major_n: usize, minor_n: usize, axis: usize, material: Material) {
        let mut rings = Vec::with_capacity(major_n + 1);
        for major in 0..=major_n {
            let a = TAU * major as f32 / major_n as f32;
            let (sa, ca) = a.sin_cos();
            let mut ring = Vec::with_capacity(minor_n + 1);
            for minor in 0..=minor_n {
                let b = TAU * minor as f32 / minor_n as f32;
                let (sb, cb) = b.sin_cos();
                let p = if axis == 0 {
                    V3::new(tube * sb, (radius + tube * cb) * ca, (radius + tube * cb) * sa)
                } else if axis == 1 {
                    V3::new((radius + tube * cb) * ca, tube * sb, (radius + tube * cb) * sa)
                } else {
                    V3::new((radius + tube * cb) * ca, (radius + tube * cb) * sa, tube * sb)
                };
                ring.push(center + p);
            }
            rings.push(ring);
        }
        for major in 0..major_n {
            for minor in 0..minor_n {
                let a = rings[major][minor];
                let b = rings[major][minor + 1];
                let c = rings[major + 1][minor + 1];
                let d = rings[major + 1][minor];
                self.outward_tri(a, b, c, center, material);
                self.outward_tri(a, c, d, center, material);
            }
        }
    }

    pub(crate) fn torus_oriented(
        &mut self,
        center: V3,
        radius: f32,
        tube: f32,
        major_n: usize,
        minor_n: usize,
        normal: V3,
        spin: f32,
        material: Material,
    ) {
        let normal = normal.normalized();
        let (u, v) = ring_plane_basis(normal, spin);
        let mut rings = Vec::with_capacity(major_n + 1);
        for major in 0..=major_n {
            let a = TAU * major as f32 / major_n as f32;
            let (sa, ca) = a.sin_cos();
            let radial = u * ca + v * sa;
            let mut ring = Vec::with_capacity(minor_n + 1);
            for minor in 0..=minor_n {
                let b = TAU * minor as f32 / minor_n as f32;
                let (sb, cb) = b.sin_cos();
                let around_tube = radial * cb + normal * sb;
                ring.push(center + radial * radius + around_tube * tube);
            }
            rings.push(ring);
        }
        for major in 0..major_n {
            for minor in 0..minor_n {
                let a = rings[major][minor];
                let b = rings[major][minor + 1];
                let c = rings[major + 1][minor + 1];
                let d = rings[major + 1][minor];
                self.outward_tri(a, b, c, center, material);
                self.outward_tri(a, c, d, center, material);
            }
        }
    }

    pub(crate) fn cylinder_z(&mut self, center: V3, radius: f32, z0: f32, z1: f32, segments: usize, material: Material) {
        let vol_center = V3::new(center.x, center.y, (z0 + z1) * 0.5);
        for i in 0..segments {
            let a0 = TAU * i as f32 / segments as f32;
            let a1 = TAU * (i + 1) as f32 / segments as f32;
            let p0 = V3::new(center.x + radius * a0.cos(), center.y + radius * a0.sin(), z0);
            let p1 = V3::new(center.x + radius * a1.cos(), center.y + radius * a1.sin(), z0);
            let p2 = V3::new(center.x + radius * a1.cos(), center.y + radius * a1.sin(), z1);
            let p3 = V3::new(center.x + radius * a0.cos(), center.y + radius * a0.sin(), z1);
            self.outward_tri(p0, p1, p2, vol_center, material);
            self.outward_tri(p0, p2, p3, vol_center, material);
            self.outward_tri(V3::new(center.x, center.y, z0), p1, p0, vol_center, material);
            self.outward_tri(V3::new(center.x, center.y, z1), p3, p2, vol_center, material);
        }
    }
}

pub(crate) fn extruded_plate(
    mesh: &mut Mesh,
    outline: &[(f32, f32)],
    z_bottom: f32,
    z_top: f32,
    top: Material,
    sides: Material,
) {
    if outline.len() < 3 { return; }
    let center_xy = outline.iter().fold((0.0_f32, 0.0_f32), |sum, p| (sum.0 + p.0, sum.1 + p.1));
    let center_xy = (center_xy.0 / outline.len() as f32, center_xy.1 / outline.len() as f32);
    let top_center = V3::new(center_xy.0, center_xy.1, z_top);
    let bottom_center = V3::new(center_xy.0, center_xy.1, z_bottom);
    let volume_center = V3::new(center_xy.0, center_xy.1, (z_bottom + z_top) * 0.5);
    for i in 0..outline.len() {
        let j = (i + 1) % outline.len();
        let a = V3::new(outline[i].0, outline[i].1, z_top);
        let b = V3::new(outline[j].0, outline[j].1, z_top);
        let a_bottom = V3::new(outline[i].0, outline[i].1, z_bottom);
        let b_bottom = V3::new(outline[j].0, outline[j].1, z_bottom);
        mesh.outward_tri(top_center, a, b, volume_center, top);
        mesh.outward_tri(bottom_center, b_bottom, a_bottom, volume_center, sides);
        mesh.outward_tri(a, a_bottom, b_bottom, volume_center, sides);
        mesh.outward_tri(a, b_bottom, b, volume_center, sides);
    }
}

pub(crate) fn extruded_yz_plate(
    mesh: &mut Mesh,
    outline: &[(f32, f32)],
    x_back: f32,
    x_front: f32,
    front: Material,
    sides: Material,
) {
    if outline.len() < 3 { return; }
    let center_yz = outline.iter().fold((0.0_f32, 0.0_f32), |sum, p| {
        (sum.0 + p.0, sum.1 + p.1)
    });
    let center_yz = (center_yz.0 / outline.len() as f32, center_yz.1 / outline.len() as f32);
    let front_center = V3::new(x_front, center_yz.0, center_yz.1);
    let back_center = V3::new(x_back, center_yz.0, center_yz.1);
    let volume_center = V3::new((x_back + x_front) * 0.5, center_yz.0, center_yz.1);
    for i in 0..outline.len() {
        let j = (i + 1) % outline.len();
        let a = V3::new(x_front, outline[i].0, outline[i].1);
        let b = V3::new(x_front, outline[j].0, outline[j].1);
        let a_back = V3::new(x_back, outline[i].0, outline[i].1);
        let b_back = V3::new(x_back, outline[j].0, outline[j].1);
        mesh.outward_tri(front_center, a, b, volume_center, front);
        mesh.outward_tri(back_center, b_back, a_back, volume_center, sides);
        mesh.outward_tri(a, a_back, b_back, volume_center, sides);
        mesh.outward_tri(a, b_back, b, volume_center, sides);
    }
}

pub(crate) fn extruded_xz_plate(
    mesh: &mut Mesh,
    outline: &[(f32, f32)],
    y_back: f32,
    y_front: f32,
    front: Material,
    back: Material,
    sides: Material,
) {
    if outline.len() < 3 { return; }
    let center_xz = outline.iter().fold((0.0_f32, 0.0_f32), |sum, p| {
        (sum.0 + p.0, sum.1 + p.1)
    });
    let center_xz = (center_xz.0 / outline.len() as f32, center_xz.1 / outline.len() as f32);
    let front_center = V3::new(center_xz.0, y_front, center_xz.1);
    let back_center = V3::new(center_xz.0, y_back, center_xz.1);
    let volume_center = V3::new(center_xz.0, (y_back + y_front) * 0.5, center_xz.1);
    for i in 0..outline.len() {
        let j = (i + 1) % outline.len();
        let a = V3::new(outline[i].0, y_front, outline[i].1);
        let b = V3::new(outline[j].0, y_front, outline[j].1);
        let a_back = V3::new(outline[i].0, y_back, outline[i].1);
        let b_back = V3::new(outline[j].0, y_back, outline[j].1);
        mesh.outward_tri(front_center, a, b, volume_center, front);
        mesh.outward_tri(back_center, b_back, a_back, volume_center, back);
        mesh.outward_tri(a, a_back, b_back, volume_center, sides);
        mesh.outward_tri(a, b_back, b, volume_center, sides);
    }
}

pub(crate) fn crystal_xz(
    mesh: &mut Mesh,
    center: V3,
    half_width: f32,
    half_height: f32,
    half_depth: f32,
    front_dir_y: f32,
    twist: f32,
    front: Material,
    facets: Material,
) {
    let (s, c) = twist.sin_cos();
    let point = |x: f32, z: f32| {
        center + V3::new(x * c + z * s, 0.0, -x * s + z * c)
    };
    let rim = [
        point(0.0, half_height),
        point(half_width, 0.0),
        point(0.0, -half_height),
        point(-half_width, 0.0),
    ];
    let front_tip = center + V3::new(0.0, front_dir_y * half_depth, 0.0);
    let back_tip = center - V3::new(0.0, front_dir_y * half_depth, 0.0);
    for i in 0..rim.len() {
        let next = (i + 1) % rim.len();
        mesh.outward_tri(front_tip, rim[i], rim[next], center, if i % 2 == 0 { front } else { facets });
        mesh.outward_tri(back_tip, rim[next], rim[i], center, facets);
    }
}

pub(crate) fn crystal_yz(
    mesh: &mut Mesh,
    center: V3,
    half_width: f32,
    half_height: f32,
    half_depth: f32,
    front_dir_x: f32,
    front: Material,
    facets: Material,
) {
    let rim = [
        center + V3::new(0.0, 0.0, half_height),
        center + V3::new(0.0, half_width, 0.0),
        center + V3::new(0.0, 0.0, -half_height),
        center + V3::new(0.0, -half_width, 0.0),
    ];
    let front_tip = center + V3::new(front_dir_x * half_depth, 0.0, 0.0);
    let back_tip = center - V3::new(front_dir_x * half_depth, 0.0, 0.0);
    for i in 0..rim.len() {
        let next = (i + 1) % rim.len();
        mesh.outward_tri(front_tip, rim[i], rim[next], center, if i % 2 == 0 { front } else { facets });
        mesh.outward_tri(back_tip, rim[next], rim[i], center, facets);
    }
}

pub(crate) fn crystal_oriented(
    mesh: &mut Mesh,
    center: V3,
    tangent: V3,
    radial: V3,
    normal: V3,
    half_width: f32,
    half_height: f32,
    half_depth: f32,
    front: Material,
    facets: Material,
) {
    let tangent = tangent.normalized();
    let radial = radial.normalized();
    let normal = normal.normalized();
    let rim = [
        center + radial * half_height,
        center + tangent * half_width,
        center - radial * half_height,
        center - tangent * half_width,
    ];
    let front_tip = center + normal * half_depth;
    let back_tip = center - normal * half_depth;
    for i in 0..rim.len() {
        let next = (i + 1) % rim.len();
        mesh.outward_tri(front_tip, rim[i], rim[next], center, if i % 2 == 0 { front } else { facets });
        mesh.outward_tri(back_tip, rim[next], rim[i], center, facets);
    }
}

pub(crate) fn tapered_rod(mesh: &mut Mesh, start: V3, end: V3, r0: f32, r1: f32, segments: usize, material: Material) {
    let axis = (end - start).normalized();
    let guide = if axis.z.abs() > 0.88 { V3::new(0.0, 1.0, 0.0) } else { V3::new(0.0, 0.0, 1.0) };
    let u = axis.cross(guide).normalized();
    let v = axis.cross(u).normalized();
    let center = (start + end) * 0.5;
    for i in 0..segments {
        let a0 = TAU * i as f32 / segments as f32;
        let a1 = TAU * (i + 1) as f32 / segments as f32;
        let radial = |a: f32| u * a.cos() + v * a.sin();
        let p0 = start + radial(a0) * r0;
        let p1 = start + radial(a1) * r0;
        let p2 = end + radial(a1) * r1;
        let p3 = end + radial(a0) * r1;
        mesh.outward_tri(p0, p1, p2, center, material);
        mesh.outward_tri(p0, p2, p3, center, material);
        mesh.outward_tri(start, p1, p0, center, material);
        mesh.outward_tri(end, p3, p2, center, material);
    }
}

pub(crate) fn append_flap_plate(
    mesh: &mut Mesh,
    outline: &[(f32, f32)],
    side: f32,
    hinge: V3,
    angle: f32,
    half_depth: f32,
    top: Material,
    sides: Material,
) {
    if outline.len() < 3 { return; }
    let (sa, ca) = (angle * side).sin_cos();
    let flap = |x: f32, y: f32, z: f32| {
        let p = V3::new(x, side * y, z) - hinge;
        V3::new(hinge.x + p.x, hinge.y + p.y * ca - p.z * sa, hinge.z + p.y * sa + p.z * ca)
    };
    let top_points: Vec<V3> = outline.iter().map(|p| flap(p.0, p.1, half_depth)).collect();
    let bottom_points: Vec<V3> = outline.iter().map(|p| flap(p.0, p.1, -half_depth)).collect();
    let center = (top_points.iter().chain(bottom_points.iter()).copied().fold(V3::ZERO, |sum, p| sum + p))
        * (1.0 / (top_points.len() + bottom_points.len()) as f32);
    let top_center = top_points.iter().copied().fold(V3::ZERO, |sum, p| sum + p) * (1.0 / top_points.len() as f32);
    let bottom_center = bottom_points.iter().copied().fold(V3::ZERO, |sum, p| sum + p) * (1.0 / bottom_points.len() as f32);
    for i in 0..outline.len() {
        let j = (i + 1) % outline.len();
        mesh.outward_tri(top_center, top_points[i], top_points[j], center, top);
        mesh.outward_tri(bottom_center, bottom_points[j], bottom_points[i], center, sides);
        mesh.outward_tri(top_points[i], bottom_points[i], bottom_points[j], center, sides);
        mesh.outward_tri(top_points[i], bottom_points[j], top_points[j], center, sides);
    }
}

pub(crate) fn append_flap_yz_plate(
    mesh: &mut Mesh,
    outline: &[(f32, f32)],
    side: f32,
    hinge: V3,
    angle: f32,
    half_depth: f32,
    front: Material,
    sides: Material,
) {
    if outline.len() < 3 { return; }
    let (sa, ca) = (angle * side).sin_cos();
    let flap = |y: f32, z: f32, face: f32| {
        let p = V3::new(0.0, side * y, z) - hinge;
        V3::new(hinge.x + face * half_depth, hinge.y + p.y * ca - p.z * sa, hinge.z + p.y * sa + p.z * ca)
    };
    let front_points: Vec<V3> = outline.iter().map(|p| flap(p.0, p.1, 1.0)).collect();
    let back_points: Vec<V3> = outline.iter().map(|p| flap(p.0, p.1, -1.0)).collect();
    let center = front_points.iter().chain(&back_points).copied().fold(V3::ZERO, |sum, p| sum + p)
        * (1.0 / (front_points.len() + back_points.len()) as f32);
    let front_center = front_points.iter().copied().fold(V3::ZERO, |sum, p| sum + p)
        * (1.0 / front_points.len() as f32);
    let back_center = back_points.iter().copied().fold(V3::ZERO, |sum, p| sum + p)
        * (1.0 / back_points.len() as f32);
    for i in 0..outline.len() {
        let j = (i + 1) % outline.len();
        mesh.outward_tri(front_center, front_points[i], front_points[j], center, front);
        mesh.outward_tri(back_center, back_points[j], back_points[i], center, sides);
        mesh.outward_tri(front_points[i], back_points[i], back_points[j], center, sides);
        mesh.outward_tri(front_points[i], back_points[j], front_points[j], center, sides);
    }
    // A pair of raised veins follows the membrane as it folds, so the wings
    // keep their sculpted, armored look at every attack pose.
    let outer_tip_y = outline.iter().map(|point| point.0).fold(0.0_f32, f32::max);
    for (y, tip_y, tip_z) in [(0.42_f32, outer_tip_y, 44.0_f32), (0.64, 36.0, -48.0)] {
        let start_y = 12.0 + (tip_y - 12.0) * y;
        let start_z = 20.0 + (tip_z - 20.0) * y;
        tapered_rod(
            mesh,
            flap(start_y, start_z, 1.15),
            flap(tip_y, tip_z, 1.15),
            1.05 - y * 0.42,
            0.42,
            7,
            Material::Accent,
        );
    }
}

pub(crate) fn append_elliptical_torus_x(
    mesh: &mut Mesh,
    center: V3,
    radius_y: f32,
    radius_z: f32,
    tube: f32,
    major_segments: usize,
    minor_segments: usize,
    material: Material,
) {
    let mut rings = Vec::with_capacity(major_segments + 1);
    for major in 0..=major_segments {
        let a = TAU * major as f32 / major_segments as f32;
        let (sa, ca) = a.sin_cos();
        let mut ring = Vec::with_capacity(minor_segments + 1);
        for minor in 0..=minor_segments {
            let b = TAU * minor as f32 / minor_segments as f32;
            let (sb, cb) = b.sin_cos();
            ring.push(center + V3::new(tube * sb, (radius_y + tube * cb) * ca, (radius_z + tube * cb) * sa));
        }
        rings.push(ring);
    }
    for major in 0..major_segments {
        for minor in 0..minor_segments {
            let a = rings[major][minor];
            let b = rings[major][minor + 1];
            let c = rings[major + 1][minor + 1];
            let d = rings[major + 1][minor];
            mesh.outward_tri(a, b, c, center, material);
            mesh.outward_tri(a, c, d, center, material);
        }
    }
}

pub(crate) fn append_ellipsoid_cap_x(
    mesh: &mut Mesh,
    center: V3,
    radii: V3,
    radial_segments: usize,
    half_steps: usize,
    material: Material,
) {
    let tip = center + V3::new(radii.x, 0.0, 0.0);
    let mut rings = Vec::with_capacity(half_steps);
    for step in 1..=half_steps {
        let theta = FRAC_PI_2 * step as f32 / half_steps as f32;
        let (st, ct) = theta.sin_cos();
        let mut ring = Vec::with_capacity(radial_segments + 1);
        for segment in 0..=radial_segments {
            let phi = TAU * segment as f32 / radial_segments as f32;
            let (sp, cp) = phi.sin_cos();
            ring.push(center + V3::new(radii.x * ct, radii.y * st * cp, radii.z * st * sp));
        }
        rings.push(ring);
    }
    for segment in 0..radial_segments {
        mesh.outward_tri(tip, rings[0][segment], rings[0][segment + 1], center, material);
    }
    for step in 0..rings.len().saturating_sub(1) {
        for segment in 0..radial_segments {
            let a = rings[step][segment];
            let b = rings[step][segment + 1];
            let c = rings[step + 1][segment + 1];
            let d = rings[step + 1][segment];
            mesh.outward_tri(a, b, c, center, material);
            mesh.outward_tri(a, c, d, center, material);
        }
    }
}

/// Rotates a wing-local point about the hinge by the flap angle (`sa`, `ca` are the
/// sine and cosine of the side-signed flap). Shared by the flyer and swarm wings.
pub(crate) fn flap_wing_point(hinge_point: V3, side: f32, sa: f32, ca: f32, x: f32, y: f32, z: f32) -> V3 {
    let p = V3::new(x, side * y, z) - hinge_point;
    V3::new(
        hinge_point.x + p.x,
        hinge_point.y + p.y * ca - p.z * sa,
        hinge_point.z + p.y * sa + p.z * ca,
    )
}

/// Appends both flap plates of an insect-style wing pair (one per side), then hands
/// each side's wing-point mapper to `detail` for the role's own ornaments.
#[allow(clippy::too_many_arguments)]
pub(crate) fn append_insect_wing_pair(
    mesh: &mut Mesh,
    outline: &[(f32, f32)],
    hinge: f32,
    hinge_span: f32,
    z: f32,
    flap: f32,
    thick: f32,
    edge_material: Material,
    mut detail: impl FnMut(&mut Mesh, f32, &dyn Fn(f32, f32, f32) -> V3),
) {
    for side in [-1.0_f32, 1.0] {
        let hinge_point = V3::new(hinge, side * hinge_span, z);
        append_flap_plate(mesh, outline, side, hinge_point, flap, thick, Material::ShellLight, edge_material);
        let (sa, ca) = (flap * side).sin_cos();
        let wing_point = |x: f32, y: f32, z: f32| flap_wing_point(hinge_point, side, sa, ca, x, y, z);
        detail(mesh, side, &wing_point);
    }
}
