use std::f32::consts::{SQRT_2, TAU};

use rand::{Rng, SeedableRng};
use rand_chacha::ChaCha8Rng;

use crate::render::sdf::{linear_rgba, linear_rgba_f, mix_rgb, SdfBatch};
use crate::sim::config::{
    CROSS_ARM_RATIO, DIAMOND_EXTENT_RATIO, DONUT_INNER_RATIO, FLOOR_EDGE, FLOOR_GRID, FLOOR_MAIN,
    ISO_SCALE_X, ISO_SCALE_Y, MAP_CROSS, MAP_DIAMOND, MAP_DONUT,
};
use crate::sim::math::{arena_inside, to_iso_cam, Vec2};

const BG_TOP: [u8; 3] = [10, 15, 30];
const BG_BOT: [u8; 3] = [5, 8, 20];
const STAR_COLOR: [u8; 3] = [205, 228, 255];

#[derive(Clone, Copy)]
struct ArenaPalette {
    edge: [u8; 3],
    rim: [u8; 3],
    grid_fine: [u8; 3],
    grid_bold: [u8; 3],
    circuit: [u8; 3],
    node: [u8; 3],
    beacon: [u8; 3],
    beacon_glow: [u8; 3],
    core: [u8; 3],
}

fn arena_palette(map_type: &str) -> ArenaPalette {
    match map_type {
        MAP_DONUT => ArenaPalette {
            edge: [54, 43, 78],
            rim: [190, 145, 255],
            grid_fine: [102, 82, 137],
            grid_bold: [138, 104, 178],
            circuit: [160, 112, 230],
            node: [205, 170, 255],
            beacon: [220, 185, 255],
            beacon_glow: [145, 100, 255],
            core: [165, 112, 235],
        },
        MAP_CROSS => ArenaPalette {
            edge: [74, 57, 39],
            rim: [255, 195, 105],
            grid_fine: [126, 97, 63],
            grid_bold: [160, 122, 74],
            circuit: [235, 154, 58],
            node: [255, 203, 120],
            beacon: [255, 218, 150],
            beacon_glow: [255, 150, 55],
            core: [235, 154, 58],
        },
        MAP_DIAMOND => ArenaPalette {
            edge: [37, 70, 69],
            rim: [125, 245, 220],
            grid_fine: [68, 121, 115],
            grid_bold: [83, 151, 139],
            circuit: [74, 203, 177],
            node: [150, 255, 224],
            beacon: [183, 255, 238],
            beacon_glow: [60, 220, 193],
            core: [78, 204, 178],
        },
        _ => ArenaPalette {
            edge: FLOOR_EDGE,
            rim: [120, 215, 255],
            grid_fine: FLOOR_GRID,
            grid_bold: [82, 110, 140],
            circuit: [75, 150, 210],
            node: [120, 210, 255],
            beacon: [135, 215, 255],
            beacon_glow: [90, 185, 255],
            core: [80, 165, 240],
        },
    }
}

fn sector_palette(map_type: &str, sector: i32) -> ArenaPalette {
    let mut palette = arena_palette(map_type);
    let accent = match sector.rem_euclid(5) {
        0 => return palette,
        1 => [170, 112, 255],
        2 => [255, 160, 82],
        3 => [76, 226, 185],
        _ => [255, 108, 150],
    };
    palette.edge = mix_rgb(palette.edge, accent, 0.20);
    palette.rim = mix_rgb(palette.rim, accent, 0.36);
    palette.grid_fine = mix_rgb(palette.grid_fine, accent, 0.22);
    palette.grid_bold = mix_rgb(palette.grid_bold, accent, 0.26);
    palette.circuit = mix_rgb(palette.circuit, accent, 0.38);
    palette.node = mix_rgb(palette.node, accent, 0.28);
    palette.beacon = mix_rgb(palette.beacon, accent, 0.24);
    palette.beacon_glow = mix_rgb(palette.beacon_glow, accent, 0.36);
    palette.core = mix_rgb(palette.core, accent, 0.30);
    palette
}

struct Star {
    x: f32,
    y: f32,
    radius: f32,
    alpha: f32,
    phase: f32,
    layer: usize,
}

pub struct ParallaxStarfield {
    stars: Vec<Star>,
}

impl Default for ParallaxStarfield {
    fn default() -> Self {
        Self::new()
    }
}

impl ParallaxStarfield {
    pub fn new() -> Self {
        let mut rng = ChaCha8Rng::seed_from_u64(0x57A2_F1E1);
        // Matches `starfield.py` exact 3 layers: (28, 5, 0.03, 2, 60..120), (16, 12, 0.09, 3, 90..160), (8, 26, 0.18, 4.5, 150..225)
        let layers = [
            (28usize, 2.0_f32, 60_u8, 120_u8),
            (16usize, 3.0_f32, 90_u8, 160_u8),
            (8usize, 4.5_f32, 150_u8, 225_u8),
        ];
        let mut stars = Vec::with_capacity(52);
        for (li, &(cnt, base_r, a0, a1)) in layers.iter().enumerate() {
            for _ in 0..cnt {
                stars.push(Star {
                    x: rng.gen_range(0.0..1.0),
                    y: rng.gen_range(0.0..1.0),
                    radius: base_r * rng.gen_range(0.75..1.15),
                    alpha: (rng.gen_range(a0..=a1) as f32) / 255.0,
                    phase: rng.gen_range(0.0..TAU),
                    layer: li,
                });
            }
        }
        Self { stars }
    }

    pub fn draw(
        &self,
        alpha_batch: &mut SdfBatch,
        add_batch: &mut SdfBatch,
        view_w: f32,
        view_h: f32,
        motion_t: f32,
        camera_world: Option<Vec2>,
        combat_intensity: f32,
        enabled: bool,
    ) {
        // Deep space two-tone background gradient
        alpha_batch.rect(0.0, view_h * 0.45, view_w, view_h * 0.55, linear_rgba(BG_TOP, 255, 1.0));
        alpha_batch.rect(0.0, 0.0, view_w, view_h * 0.50, linear_rgba(BG_BOT, 255, 1.0));
        // Soft atmospheric horizon nebula glow behind arena center
        let ci = combat_intensity.clamp(0.0, 1.0);
        add_batch.ellipse_glow(
            view_w * 0.5 - 180.0,
            view_h * 0.5 + 90.0,
            340.0,
            220.0,
            1.8,
            linear_rgba_f([30, 75, 135], 0.14 + 0.08 * ci, 1.1),
        );
        add_batch.ellipse_glow(
            view_w * 0.5 + 210.0,
            view_h * 0.5 - 50.0,
            280.0,
            180.0,
            1.8,
            linear_rgba_f([150, 65, 125], 0.10 + 0.06 * ci, 1.1),
        );
        add_batch.ellipse_glow(
            view_w * 0.5 + 20.0,
            view_h * 0.5 + 160.0,
            210.0,
            140.0,
            1.8,
            linear_rgba_f([65, 175, 160], 0.09, 1.1),
        );

        if !enabled {
            return;
        }

        let speeds = [5.0_f32, 12.0_f32, 26.0_f32];
        let cam_scales = [0.03_f32, 0.09_f32, 0.18_f32];
        let drift = Vec2::new(-0.94, -0.33).normalized();
        let cam_iso = camera_world
            .map(|c| Vec2::new((c.x - c.y) * ISO_SCALE_X, (c.x + c.y) * ISO_SCALE_Y))
            .unwrap_or(Vec2::ZERO);

        for s in &self.stars {
            let spd = speeds[s.layer];
            let cs = cam_scales[s.layer];
            let raw_x = s.x * view_w + drift.x * spd * motion_t - cam_iso.x * cs;
            let raw_y = s.y * view_h + drift.y * spd * motion_t - cam_iso.y * cs;
            let sx = raw_x.rem_euclid(view_w);
            let sy = raw_y.rem_euclid(view_h);
            let twinkle = if s.layer == 2 {
                0.68 + 0.32 * (motion_t * 2.2 + s.phase).sin()
            } else {
                0.85 + 0.15 * (motion_t * 1.1 + s.phase).sin()
            };
            add_batch.circle(
                sx,
                sy,
                s.radius * 0.55,
                linear_rgba_f(STAR_COLOR, s.alpha * twinkle, 1.15),
            );
            if s.layer == 2 {
                add_batch.glow(
                    sx,
                    sy,
                    s.radius * 2.2,
                    1.8,
                    linear_rgba_f(STAR_COLOR, s.alpha * 0.3 * twinkle, 1.1),
                );
            }
        }
    }
}

#[derive(Clone)]
struct CachedSeg {
    a: Vec2,
    b: Vec2,
    alpha: u8,
    thickness: f32,
    color: [u8; 3],
}

#[derive(Clone)]
struct CircuitNode {
    pos: Vec2,
    phase: f32,
}

pub struct FloorGeometryCache {
    cached_key: (String, i32, i32, u64),
    grid_lines: Vec<CachedSeg>,
    cracks: Vec<CachedSeg>,
    circuits: Vec<CachedSeg>,
    nodes: Vec<CircuitNode>,
    beacons: Vec<Vec2>,
    panel_pts: Vec<[Vec2; 4]>,
}

impl Default for FloorGeometryCache {
    fn default() -> Self {
        Self::new()
    }
}

impl FloorGeometryCache {
    pub fn new() -> Self {
        Self {
            cached_key: (String::new(), -1, -1, 0),
            grid_lines: Vec::new(),
            cracks: Vec::new(),
            circuits: Vec::new(),
            nodes: Vec::new(),
            beacons: Vec::new(),
            panel_pts: Vec::new(),
        }
    }

    fn rebuild(&mut self, map_type: &str, sector: i32, room_radius: f32, seed: u64) {
        let key = (map_type.to_string(), sector, room_radius.round() as i32, seed);
        if self.cached_key == key {
            return;
        }
        self.cached_key = key;
        self.grid_lines.clear();
        self.cracks.clear();
        self.circuits.clear();
        self.nodes.clear();
        self.beacons.clear();
        self.panel_pts.clear();

        let r = room_radius.max(100.0);
        let palette = sector_palette(map_type, sector);
        let mut rng = ChaCha8Rng::seed_from_u64(seed ^ 0xF100_4C0D);

        // Helper to push clipped world segment pieces inside arena bounds
        let push_clipped = |a: Vec2, b: Vec2, color: [u8; 3], alpha: u8, thickness: f32, dst: &mut Vec<CachedSeg>| {
            let steps = 28usize;
            let mut seg_start: Option<Vec2> = None;
            for i in 0..=steps {
                let t = i as f32 / steps as f32;
                let p = a + (b - a) * t;
                let inside = arena_inside(p, r * 0.985, map_type);
                match (inside, seg_start) {
                    (true, None) => seg_start = Some(p),
                    (false, Some(s)) => {
                        let prev_t = (i - 1) as f32 / steps as f32;
                        let e = a + (b - a) * prev_t;
                        if (e - s).length_squared() > 9.0 {
                            dst.push(CachedSeg { a: s, b: e, alpha, thickness, color });
                        }
                        seg_start = None;
                    }
                    _ => {}
                }
            }
            if let Some(s) = seg_start {
                if (b - s).length_squared() > 9.0 {
                    dst.push(CachedSeg { a: s, b, alpha, thickness, color });
                }
            }
        };

        // 1. Primary grid & fine grid lines
        let span = if map_type == MAP_DIAMOND {
            r * DIAMOND_EXTENT_RATIO
        } else {
            r
        };
        let step = (r / 8.0).clamp(52.0, 96.0);
        let mut v = -span;
        let mut idx = 0i32;
        while v <= span + 1.0 {
            let fine = idx % 2 != 0;
            let al = if fine { 18 } else { 42 };
            let th = if fine { 1.0 } else { 1.5 };
            let col = if fine { palette.grid_fine } else { palette.grid_bold };
            push_clipped(Vec2::new(v, -span), Vec2::new(v, span), col, al, th, &mut self.grid_lines);
            push_clipped(Vec2::new(-span, v), Vec2::new(span, v), col, al, th, &mut self.grid_lines);
            v += step * 0.5;
            idx += 1;
        }

        // 2. Concentric subtle structural panels
        let panel_count = if map_type == MAP_CROSS { 6 } else { 8 };
        for i in 0..panel_count {
            let ang = (i as f32 / panel_count as f32) * TAU + 0.12;
            let dist_r = r * rng.gen_range(0.50..0.76);
            let pw = rng.gen_range(26.0..58.0);
            let ph = rng.gen_range(26.0..58.0);
            let c = Vec2::new(ang.cos() * dist_r, ang.sin() * dist_r);
            let pts = [
                c + Vec2::new(-pw * 0.5, -ph * 0.5),
                c + Vec2::new(pw * 0.5, -ph * 0.5),
                c + Vec2::new(pw * 0.5, ph * 0.5),
                c + Vec2::new(-pw * 0.5, ph * 0.5),
            ];
            if pts.iter().all(|&p| arena_inside(p, r * 0.94, map_type)) {
                self.panel_pts.push(pts);
            }
        }

        // 3. Battle-scar surface cracks
        for _ in 0..10 {
            let ang = rng.gen_range(0.0..TAU);
            let d = rng.gen_range(r * 0.18..r * 0.85);
            let p0 = Vec2::new(ang.cos() * d, ang.sin() * d);
            if !arena_inside(p0, r * 0.93, map_type) {
                continue;
            }
            let mut cur = p0;
            let mut dir = ang + rng.gen_range(-0.8..0.8);
            for _ in 0..3 {
                dir += rng.gen_range(-0.55..0.55);
                let nxt = cur + Vec2::new(dir.cos(), dir.sin()) * rng.gen_range(16.0..34.0);
                if arena_inside(nxt, r * 0.94, map_type) {
                    self.cracks.push(CachedSeg {
                        a: cur,
                        b: nxt,
                        alpha: 62,
                        thickness: 1.4,
                        color: [16, 22, 34],
                    });
                    cur = nxt;
                }
            }
        }

        // 4. Circuit traces & pulse nodes
        for i in 0..12 {
            let ang = (i as f32 / 12.0) * TAU;
            let d0 = if map_type == MAP_DONUT { r * (DONUT_INNER_RATIO + 0.05) } else { r * 0.36 };
            let d1 = r * rng.gen_range(0.62..0.88);
            let p0 = Vec2::new(ang.cos() * d0, ang.sin() * d0);
            let p1 = Vec2::new(ang.cos() * d1, ang.sin() * d1);
            push_clipped(p0, p1, palette.circuit, 42, 1.5, &mut self.circuits);
            if arena_inside(p1, r * 0.94, map_type) {
                self.nodes.push(CircuitNode {
                    pos: p1,
                    phase: i as f32 * 0.65,
                });
            }
        }

        // 5. 16 perimeter beacons (+ 8 inner rim beacons for Donut)
        let cross_pts = if map_type == MAP_CROSS {
            let w = r * CROSS_ARM_RATIO;
            vec![
                Vec2::new(-w, r),
                Vec2::new(0.0, r),
                Vec2::new(w, r),
                Vec2::new(w, w),
                Vec2::new(r, w),
                Vec2::new(r, 0.0),
                Vec2::new(r, -w),
                Vec2::new(w, -w),
                Vec2::new(w, -r),
                Vec2::new(0.0, -r),
                Vec2::new(-w, -r),
                Vec2::new(-w, -w),
                Vec2::new(-r, -w),
                Vec2::new(-r, 0.0),
                Vec2::new(-r, w),
                Vec2::new(-w, w),
            ]
        } else {
            Vec::new()
        };
        if !cross_pts.is_empty() {
            self.beacons.extend(cross_pts);
        } else {
            for i in 0..16 {
                let ang = (i as f32 / 16.0) * TAU;
                let bp = if map_type == MAP_DIAMOND {
                    let s = r * DIAMOND_EXTENT_RATIO;
                    let dx = ang.cos();
                    let dy = ang.sin();
                    let scale = s / (dx.abs() + dy.abs()).max(1e-4);
                    Vec2::new(dx * scale, dy * scale)
                } else {
                    Vec2::new(ang.cos() * r, ang.sin() * r)
                };
                self.beacons.push(bp);
            }
            if map_type == MAP_DONUT {
                let inner_r = r * DONUT_INNER_RATIO;
                for i in 0..8 {
                    let ang = (i as f32 / 8.0) * TAU;
                    self.beacons.push(Vec2::new(ang.cos() * inner_r, ang.sin() * inner_r));
                }
            }
        }
        let _ = rng;
    }

    #[allow(clippy::too_many_arguments)]
    pub fn draw(
        &mut self,
        alpha_batch: &mut SdfBatch,
        add_batch: &mut SdfBatch,
        map_type: &str,
        room_radius: f32,
        seed: u64,
        view_w: f32,
        view_h: f32,
        shake: Vec2,
        motion_t: f32,
        rim_pulse: f32,
    ) {
        self.draw_cam(
            alpha_batch,
            add_batch,
            map_type,
            0,
            room_radius,
            seed,
            Vec2::ZERO,
            view_w,
            view_h,
            shake,
            motion_t,
            rim_pulse,
        );
    }

    #[allow(clippy::too_many_arguments)]
    pub fn draw_cam(
        &mut self,
        alpha_batch: &mut SdfBatch,
        add_batch: &mut SdfBatch,
        map_type: &str,
        sector: i32,
        room_radius: f32,
        seed: u64,
        cam_world: Vec2,
        view_w: f32,
        view_h: f32,
        shake: Vec2,
        motion_t: f32,
        rim_pulse: f32,
    ) {
        self.rebuild(map_type, sector, room_radius, seed);
        let palette = sector_palette(map_type, sector);

        let r = room_radius;
        let (cx, cy) = to_iso_cam(Vec2::ZERO, cam_world, view_w, view_h, shake);
        let iso_rx = r * SQRT_2 * ISO_SCALE_X;
        let iso_ry = r * SQRT_2 * ISO_SCALE_Y;

        let to_scr = |w: Vec2| -> [f32; 2] {
            let (sx, sy) = to_iso_cam(w, cam_world, view_w, view_h, shake);
            [sx, sy]
        };

        // 1. Arena Base Floor Silhouette
        let floor_col = linear_rgba(mix_rgb(FLOOR_MAIN, palette.core, 0.09), 240, 1.0);
        let rim_color = mix_rgb(palette.edge, palette.rim, 0.35 + rim_pulse * 0.55);
        let rim_alpha = (140.0 + rim_pulse * 95.0).clamp(0.0, 255.0) as u8;
        let rim_rgba = linear_rgba(rim_color, rim_alpha, 1.15 + rim_pulse * 0.9);

        match map_type {
            MAP_DIAMOND => {
                let d = r * DIAMOND_EXTENT_RATIO;
                let pts = [
                    to_scr(Vec2::new(0.0, d)),
                    to_scr(Vec2::new(d, 0.0)),
                    to_scr(Vec2::new(0.0, -d)),
                    to_scr(Vec2::new(-d, 0.0)),
                ];
                alpha_batch.polygon(&pts, floor_col);
                // Outer halo border + bright inner rim
                let d_out = d * 1.03;
                let out_pts = [
                    to_scr(Vec2::new(0.0, d_out)),
                    to_scr(Vec2::new(d_out, 0.0)),
                    to_scr(Vec2::new(0.0, -d_out)),
                    to_scr(Vec2::new(-d_out, 0.0)),
                ];
                alpha_batch.polyline_closed(&out_pts, 5.5, linear_rgba(palette.edge, 90, 1.0));
                add_batch.polyline_closed(&pts, 3.0, rim_rgba);
            }
            MAP_CROSS => {
                let w = r * CROSS_ARM_RATIO;
                let vert = [
                    to_scr(Vec2::new(-w, r)),
                    to_scr(Vec2::new(w, r)),
                    to_scr(Vec2::new(w, -r)),
                    to_scr(Vec2::new(-w, -r)),
                ];
                let horiz = [
                    to_scr(Vec2::new(-r, w)),
                    to_scr(Vec2::new(r, w)),
                    to_scr(Vec2::new(r, -w)),
                    to_scr(Vec2::new(-r, -w)),
                ];
                alpha_batch.polygon(&vert, floor_col);
                alpha_batch.polygon(&horiz, floor_col);
                let cross_outline = [
                    to_scr(Vec2::new(-w, r)),
                    to_scr(Vec2::new(w, r)),
                    to_scr(Vec2::new(w, w)),
                    to_scr(Vec2::new(r, w)),
                    to_scr(Vec2::new(r, -w)),
                    to_scr(Vec2::new(w, -w)),
                    to_scr(Vec2::new(w, -r)),
                    to_scr(Vec2::new(-w, -r)),
                    to_scr(Vec2::new(-w, -w)),
                    to_scr(Vec2::new(-r, -w)),
                    to_scr(Vec2::new(-r, w)),
                    to_scr(Vec2::new(-w, w)),
                ];
                alpha_batch.polyline_closed(&cross_outline, 6.0, linear_rgba(palette.edge, 85, 1.0));
                add_batch.polyline_closed(&cross_outline, 2.8, rim_rgba);
            }
            MAP_DONUT => {
                alpha_batch.ellipse(cx, cy, iso_rx * 1.02, iso_ry * 1.02, 0.0, linear_rgba(palette.edge, 70, 1.0));
                alpha_batch.ellipse(cx, cy, iso_rx, iso_ry, 0.0, floor_col);
                add_batch.ring(cx, cy, iso_rx, iso_ry, 3.0, rim_rgba);
            }
            _ => {
                alpha_batch.ellipse(cx, cy, iso_rx * 1.02, iso_ry * 1.02, 0.0, linear_rgba(palette.edge, 70, 1.0));
                alpha_batch.ellipse(cx, cy, iso_rx, iso_ry, 0.0, floor_col);
                add_batch.ring(cx, cy, iso_rx, iso_ry, 3.0, rim_rgba);
            }
        }

        // 2. Subtle structural floor panels
        for pts in &self.panel_pts {
            let q = [to_scr(pts[0]), to_scr(pts[1]), to_scr(pts[2]), to_scr(pts[3])];
            alpha_batch.polygon(&q, linear_rgba(mix_rgb([38, 46, 58], palette.edge, 0.18), 115, 1.0));
            alpha_batch.polyline_closed(
                &q,
                1.2,
                linear_rgba(mix_rgb([70, 92, 118], palette.grid_fine, 0.22), 52, 1.0),
            );
        }

        // 3. Grid lines
        for seg in &self.grid_lines {
            let a = to_scr(seg.a);
            let b = to_scr(seg.b);
            alpha_batch.line(a[0], a[1], b[0], b[1], seg.thickness, linear_rgba(seg.color, seg.alpha, 1.0));
        }

        // 4. Cracks
        for seg in &self.cracks {
            let a = to_scr(seg.a);
            let b = to_scr(seg.b);
            alpha_batch.line(a[0], a[1], b[0], b[1], seg.thickness, linear_rgba(seg.color, seg.alpha, 1.0));
        }

        // 5. Circuit lines & pulsing nodes
        for seg in &self.circuits {
            let a = to_scr(seg.a);
            let b = to_scr(seg.b);
            add_batch.line(a[0], a[1], b[0], b[1], seg.thickness, linear_rgba(seg.color, seg.alpha, 1.15));
        }
        for node in &self.nodes {
            let p = to_scr(node.pos);
            let pval = 0.5 + 0.5 * (motion_t * 2.2 + node.phase).sin();
            add_batch.circle(
                p[0],
                p[1],
                2.5 + pval * 1.4,
                linear_rgba(palette.node, (50.0 + 75.0 * pval) as u8, 1.4),
            );
        }

        // 6. Center Reactor Seal (or Donut Inner Abyss Void)
        let seal_r = if map_type == MAP_DONUT {
            r * DONUT_INNER_RATIO
        } else {
            r * CROSS_ARM_RATIO
        };
        let seal_rx = seal_r * SQRT_2 * ISO_SCALE_X;
        let seal_ry = seal_r * SQRT_2 * ISO_SCALE_Y;
        if map_type == MAP_DONUT {
            // Abyss void hole inside Donut arena + glowing rim wall
            alpha_batch.ellipse(cx, cy, seal_rx, seal_ry, 0.0, linear_rgba(BG_BOT, 255, 1.0));
            add_batch.ring(cx, cy, seal_rx, seal_ry, 3.0, rim_rgba);
            add_batch.ring(
                cx,
                cy,
                seal_rx * 0.90,
                seal_ry * 0.90,
                1.5,
                linear_rgba(palette.core, 65, 1.2),
            );
        } else {
            // Subtle center reactor ring & harmonic scalloped trim
            alpha_batch.ellipse(cx, cy, seal_rx * 0.85, seal_ry * 0.85, 0.0, linear_rgba([24, 30, 40], 110, 1.0));
            alpha_batch.ring(cx, cy, seal_rx, seal_ry, 2.0, linear_rgba(palette.core, 55, 1.0));
            let wave_segs = 64;
            let mut prev_pt: Option<[f32; 2]> = None;
            let mut first_pt = [0.0; 2];
            for i in 0..wave_segs {
                let a = (i as f32 / wave_segs as f32) * TAU;
                let mod_r = seal_r * 0.86 + 4.0 * (a * 4.0).cos();
                let wp = to_scr(Vec2::new(a.cos() * mod_r, a.sin() * mod_r));
                if i == 0 {
                    first_pt = wp;
                }
                if let Some(pp) = prev_pt {
                    add_batch.line(pp[0], pp[1], wp[0], wp[1], 1.4, linear_rgba(palette.core, 48, 1.1));
                }
                prev_pt = Some(wp);
            }
            if let Some(pp) = prev_pt {
                add_batch.line(pp[0], pp[1], first_pt[0], first_pt[1], 1.4, linear_rgba(palette.core, 48, 1.1));
            }
            // Inner reactor glow node
            let core_pulse = 0.5 + 0.5 * (motion_t * 1.6).sin();
            add_batch.ellipse_glow(
                cx,
                cy,
                seal_rx * 0.42,
                seal_ry * 0.42,
                1.8,
                linear_rgba_f(palette.core, 0.14 + 0.08 * core_pulse, 1.2),
            );
        }

        // 7. 10 Perimeter Beacons
        for (i, &bp) in self.beacons.iter().enumerate() {
            let p = to_scr(bp);
            let blink = 0.5 + 0.5 * (motion_t * 2.8 + i as f32 * 0.63).sin();
            add_batch.circle(
                p[0],
                p[1],
                3.2,
                linear_rgba(palette.beacon, (110.0 + 110.0 * blink) as u8, 1.6),
            );
            add_batch.glow(
                p[0],
                p[1],
                11.0,
                1.8,
                linear_rgba(palette.beacon_glow, (45.0 + 60.0 * blink) as u8, 1.3),
            );
        }

    }
}
