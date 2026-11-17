use std::f32::consts::{FRAC_PI_2, PI, TAU};

use crate::sim::config::{DIAMOND_EXTENT_RATIO, MAP_DIAMOND, MAP_DONUT};
use crate::sim::math::{arena_inside, dist, Vec2};
use crate::sim::rng::SimRng;

#[derive(Debug, Clone)]
pub struct Obstacle {
    pub pos: Vec2,
    pub radius: f32,
    pub kind: String,
    pub hp: i32,
    pub max_hp: i32,
}

fn difficulty_layout_mult(difficulty: &str) -> f32 {
    match difficulty.to_ascii_lowercase().as_str() {
        "easy" => 0.9,
        "hard" => 1.15,
        _ => 1.0,
    }
}

pub fn generate_obstacles(seed: u64, segment: i32, room_radius: f32, difficulty: &str, map_type: &str) -> Vec<Obstacle> {
    let derived = seed.wrapping_add((segment as i64 as u64).wrapping_mul(1337));
    let mut rng = SimRng::new(derived);
    let r = room_radius;
    let mult = difficulty_layout_mult(difficulty);

    let mut obstacles: Vec<Obstacle> = Vec::new();
    let spawn_center = if map_type == MAP_DONUT {
        Vec2::new(0.0, -(r * 0.68))
    } else {
        Vec2::ZERO
    };
    let center_keepout = (r * 0.14).max(80.0);
    let escape_lane_half_width = (r * 0.075).clamp(44.0, 68.0);
    let escape_lanes = [
        Vec2::new(1.0, 0.0),
        Vec2::new(-1.0, 0.0),
        Vec2::new(0.0, 1.0),
        Vec2::new(0.0, -1.0),
        Vec2::new(1.0, 1.0).normalized(),
        Vec2::new(-1.0, 1.0).normalized(),
        Vec2::new(1.0, -1.0).normalized(),
        Vec2::new(-1.0, -1.0).normalized(),
    ];
    let max_place_r = if map_type == MAP_DIAMOND {
        r * (DIAMOND_EXTENT_RATIO * 0.86)
    } else {
        r * 0.88
    };

    let can_place = |obs: &[Obstacle], p: Vec2, pr: f32| -> bool {
        if !arena_inside(p, r * 0.90, map_type) {
            return false;
        }
        if dist(p, spawn_center) < center_keepout || dist(p, Vec2::ZERO) > max_place_r {
            return false;
        }
        // Keep several broad routes open from the spawn pocket so randomized fills and the
        // denser late-game layouts cannot turn the arena into a ring of dead ends.
        let from_spawn = p - spawn_center;
        for lane in escape_lanes {
            let along = from_spawn.dot(lane);
            let across = from_spawn.dot(lane.perp()).abs();
            if along > center_keepout * 0.65
                && along < r * 0.86
                && across < escape_lane_half_width + pr * 0.45
            {
                return false;
            }
        }
        for o in obs {
            if dist(p, o.pos) < (pr + o.radius + 34.0) {
                return false;
            }
        }
        true
    };

    let try_place = |obs: &mut Vec<Obstacle>, p: Vec2, pr: f32, kind: &str| {
        if can_place(obs, p, pr) {
            let max_hp = if kind == "crate" { 28 } else { 0 };
            obs.push(Obstacle {
                pos: p,
                radius: pr,
                kind: kind.to_string(),
                hp: max_hp,
                max_hp,
            });
        }
    };

    let layouts = [
        "cross", "ring", "lanes", "cluster", "petals", "crescent", "maze", "spiral",
    ];
    let idx = ((seed as i128 + segment as i128).rem_euclid(layouts.len() as i128)) as usize;
    let layout = layouts[idx];

    match layout {
        "cross" => {
            let base_r = 56.0_f32.min(r * 0.12);
            let arm = r * 0.56;
            for ang in [0.0, FRAC_PI_2, PI, 3.0 * FRAC_PI_2] {
                try_place(&mut obstacles, Vec2::new(ang.cos() * arm, ang.sin() * arm), base_r, "pillar");
            }
            for _ in 0..4 {
                let ang = rng.range_f32(0.0, TAU);
                let mag = rng.range_f32(r * 0.30, max_place_r);
                try_place(&mut obstacles, Vec2::new(ang.cos(), ang.sin()) * mag, 34.0_f32.min(r * 0.08), "crystal");
            }
        }
        "ring" => {
            let n = 8;
            let ring_r = r * 0.62;
            for i in 0..n {
                let ang = (i as f32 / n as f32) * TAU + rng.range_f32(-0.18, 0.18);
                try_place(
                    &mut obstacles,
                    Vec2::new(ang.cos(), ang.sin()) * ring_r,
                    46.0_f32.min(r * 0.10),
                    "pillar",
                );
            }
            for _ in 0..3 {
                let ang = rng.range_f32(0.0, TAU);
                let mag = rng.range_f32(r * 0.25, max_place_r);
                try_place(&mut obstacles, Vec2::new(ang.cos(), ang.sin()) * mag, 28.0_f32.min(r * 0.07), "crate");
            }
        }
        "lanes" => {
            let wall_r = 70.0_f32.min(r * 0.16);
            let offset = r * 0.22;
            try_place(&mut obstacles, Vec2::new(-offset, 0.0), wall_r, "pillar");
            try_place(&mut obstacles, Vec2::new(offset, 0.0), wall_r, "pillar");
            try_place(&mut obstacles, Vec2::new(0.0, offset), wall_r, "pillar");
            for _ in 0..3 {
                let ang = rng.range_f32(0.0, TAU);
                let mag = rng.range_f32(r * 0.28, r * 0.58);
                let kind = if rng.f32() < 0.5 { "crate" } else { "crystal" };
                try_place(&mut obstacles, Vec2::new(ang.cos(), ang.sin()) * mag, 30.0_f32.min(r * 0.08), kind);
            }
        }
        "cluster" => {
            let cx = rng.range_f32(-r * 0.25, r * 0.25);
            let cy = rng.range_f32(-r * 0.25, r * 0.25);
            for _ in 0..6 {
                let p = Vec2::new(cx + rng.range_f32(-120.0, 120.0), cy + rng.range_f32(-120.0, 120.0));
                let kind = if rng.f32() < 0.5 { "pillar" } else { "crate" };
                try_place(&mut obstacles, p, 42.0_f32.min(r * 0.11), kind);
            }
            for _ in 0..3 {
                let ang = rng.range_f32(0.0, TAU);
                let mag = rng.range_f32(r * 0.35, r * 0.6);
                try_place(&mut obstacles, Vec2::new(ang.cos(), ang.sin()) * mag, 26.0_f32.min(r * 0.07), "crystal");
            }
        }
        "petals" => {
            // Three broken cover clusters make recognizable pockets without sealing the lanes
            // between them. The tangent rocks turn each pillar into a small combat feature.
            let base_ang = rng.range_f32(0.0, TAU);
            let arm = (r * 0.18).max(112.0);
            for i in 0..3 {
                let ang = base_ang + (i as f32) * (TAU / 3.0) + rng.range_f32(-0.07, 0.07);
                let radial = Vec2::new(ang.cos(), ang.sin());
                let center = radial * (r * 0.49);
                try_place(&mut obstacles, center, 44.0_f32.min(r * 0.105), "pillar");
                let tangent = radial.perp();
                for side in [-1.0_f32, 1.0] {
                    let offset = center + tangent * arm * side;
                    let kind = if rng.f32() < 0.5 { "crystal" } else { "crate" };
                    try_place(&mut obstacles, offset, 27.0_f32.min(r * 0.07), kind);
                }
            }
        }
        "crescent" => {
            // A broken half-ring gives one side of the room layered cover and leaves the
            // opposite side open for circling and long-range attacks.
            let spawn_angle = spawn_center.y.atan2(spawn_center.x);
            let base_ang = if spawn_center.length_squared() > 1e-6 {
                spawn_angle + PI
            } else {
                rng.range_f32(0.0, TAU)
            };
            for i in 0..7 {
                let frac = i as f32 / 6.0 - 0.5;
                let ang = base_ang + frac * 2.25 + rng.range_f32(-0.08, 0.08);
                let radius = r * (0.55 + rng.range_f32(-0.035, 0.035));
                let kind = if i % 3 == 0 { "pillar" } else { "crate" };
                let size = if kind == "pillar" { 44.0_f32 } else { 31.0_f32 };
                try_place(
                    &mut obstacles,
                    Vec2::new(ang.cos(), ang.sin()) * radius,
                    size.min(r * 0.1),
                    kind,
                );
            }
        }
        "maze" => {
            let grid_size = 10;
            let cell_size = r * 2.0 / grid_size as f32;
            let wall_r = cell_size * 0.3;
            for i in 0..grid_size {
                for j in 0..grid_size {
                    if rng.f32() > 0.3 {
                        let x = -r + (i as f32) * cell_size + cell_size * 0.5;
                        let y = -r + (j as f32) * cell_size + cell_size * 0.5;
                        let p = Vec2::new(x, y);
                        if dist(p, Vec2::ZERO) > center_keepout {
                            try_place(&mut obstacles, p, wall_r, "pillar");
                        }
                    }
                }
            }
        }
        _ => {
            let turns = 2.2_f32;
            let steps = 10;
            for i in 0..steps {
                let t = i as f32 / (steps - 1) as f32;
                let ang = t * TAU * turns + rng.range_f32(-0.15, 0.15);
                let rad = center_keepout + t * (r * 0.52);
                let p = Vec2::new(ang.cos(), ang.sin()) * rad;
                let kind = if i % 3 == 0 {
                    "pillar"
                } else if rng.f32() < 0.5 {
                    "crystal"
                } else {
                    "crate"
                };
                let pr = if kind == "pillar" { 44.0_f32.min(r * 0.11) } else { 28.0_f32.min(r * 0.075) };
                try_place(&mut obstacles, p, pr, kind);
            }
        }
    }

    let target = (((6.0 + (segment as f32) * 2.0) * mult + (r / 320.0)) as i32).clamp(6, 18) as usize;
    let mut tries = 0;
    while obstacles.len() < target && tries < 800 {
        tries += 1;
        let x = rng.range_f32(-max_place_r, max_place_r);
        let y = rng.range_f32(-max_place_r, max_place_r);
        let p = Vec2::new(x, y);
        let idx_k = rng.weighted_index(&[4.0, 3.0, 2.0]);
        let (kind, pr) = match idx_k {
            0 => ("crate", 28.0_f32.min(r * 0.065)),
            1 => ("crystal", 32.0_f32.min(r * 0.07)),
            _ => ("pillar", 46.0_f32.min(r * 0.095)),
        };
        try_place(&mut obstacles, p, pr, kind);
    }

    obstacles
}

pub fn resolve_circle_obstacles(pos: Vec2, radius: f32, obstacles: &[Obstacle], iterations: usize) -> Vec2 {
    let mut p = pos;
    for _ in 0..iterations.max(1) {
        let mut moved = false;
        for o in obstacles {
            let r = radius + o.radius;
            let d = p - o.pos;
            let len = d.length();
            if len >= r {
                continue;
            }
            let (nx, ny) = if len <= 1e-6 { (1.0, 0.0) } else { (d.x / len, d.y / len) };
            let push = r - len;
            p.x += nx * push;
            p.y += ny * push;
            moved = true;
        }
        if !moved {
            break;
        }
    }
    p
}
