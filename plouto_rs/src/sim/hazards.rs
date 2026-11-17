use crate::sim::math::Vec2;

#[derive(Debug, Clone)]
pub struct Trap {
    pub pos: Vec2,
    pub radius: f32,
    pub damage: i32,
    pub ttl: f32,
    pub armed_delay: f32,
    pub kind: String,
    pub t: f32,
    pub landed: bool,
    pub source: String,
}

impl Trap {
    pub fn new(pos: Vec2, radius: f32, damage: i32, ttl: f32, armed_delay: f32, kind: &str) -> Self {
        Self {
            pos,
            radius,
            damage,
            ttl,
            armed_delay,
            kind: kind.to_string(),
            t: 0.0,
            landed: false,
            source: String::new(),
        }
    }

    pub fn with_source(mut self, source: &str) -> Self {
        self.source = source.to_string();
        self
    }
}

#[derive(Debug, Clone)]
pub struct LaserBeam {
    pub id: u64,
    pub start: Vec2,
    pub end: Vec2,
    pub damage: i32,
    pub thickness: f32,
    pub ttl: f32,
    pub warn: f32,
    pub t: f32,
    pub color: [u8; 3],
    pub owner: String,
    pub hit_done: bool,
    pub source: String,
}

impl LaserBeam {
    pub fn new(start: Vec2, end: Vec2, damage: i32, thickness: f32, ttl: f32, warn: f32, color: [u8; 3], owner: &str) -> Self {
        Self {
            id: 0,
            start,
            end,
            damage,
            thickness,
            ttl,
            warn,
            t: 0.0,
            color,
            owner: owner.to_string(),
            hit_done: false,
            source: String::new(),
        }
    }

    pub fn with_id(mut self, id: u64) -> Self {
        self.id = id;
        self
    }

    pub fn with_source(mut self, source: &str) -> Self {
        self.source = source.to_string();
        self
    }
}

#[derive(Debug, Clone)]
pub struct ThunderLine {
    pub start: Vec2,
    pub end: Vec2,
    pub damage: i32,
    pub thickness: f32,
    pub ttl: f32,
    pub warn: f32,
    pub t: f32,
    pub color: [u8; 3],
    pub owner: String,
    pub hit_done: bool,
    pub source: String,
}

impl ThunderLine {
    pub fn new(start: Vec2, end: Vec2, damage: i32, thickness: f32, ttl: f32, warn: f32, color: [u8; 3], owner: &str) -> Self {
        Self {
            start,
            end,
            damage,
            thickness,
            ttl,
            warn,
            t: 0.0,
            color,
            owner: owner.to_string(),
            hit_done: false,
            source: String::new(),
        }
    }

    pub fn with_source(mut self, source: &str) -> Self {
        self.source = source.to_string();
        self
    }
}
