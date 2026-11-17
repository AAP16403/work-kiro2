use std::collections::VecDeque;
use std::f32::consts::{SQRT_2, TAU};

use rand::Rng;

use crate::render::sdf::{linear_rgba, linear_rgba_f, mix_rgb, SdfBatch};
use crate::render::text::{AlignX, AlignY, FontId, TextBatch};
use crate::sim::config::{
    BOMB_BLAST_RADIUS, ISO_SCALE_X, ISO_SCALE_Y, PARTICLE_HARD_CAP, PARTICLE_SOFT_CAP,
};
use crate::sim::math::{dist, to_iso_cam, Vec2};
use crate::sim::state::SimEvent;

const MOTE_DRAG: f32 = 2.5;
const DASH_SAMPLE_S: f32 = 0.03;
const DASH_FADE_S: f32 = 0.30;
const DASH_MAX_SAMPLES: usize = 10;
const DASH_STREAK_PX: f32 = 60.0;
const DASH_THICKNESS: f32 = 9.0;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ParticleKind {
    Dot,
    Spark,
    Ring,
    Glow,
}

#[derive(Debug, Clone)]
pub struct Particle {
    pub pos: Vec2,
    pub vel: Vec2,
    pub life: f32,
    pub max_life: f32,
    pub color: [u8; 3],
    pub size: f32,
    pub decay: bool,
    pub kind: ParticleKind,
    pub delay: f32,
    pub aspect: f32,
    pub grow: bool,
}

#[derive(Debug, Clone)]
pub struct DissolveMote {
    pub pos: Vec2,
    pub vel: Vec2,
    pub radius: f32,
    pub color: [u8; 3],
    pub life: f32,
    pub max_life: f32,
}

#[derive(Debug, Clone)]
pub struct PopupItem {
    pub pos: Vec2,
    pub vel: Vec2,
    pub text: String,
    pub color: [u8; 3],
    pub life: f32,
    pub max_life: f32,
    pub big: bool,
}

#[derive(Debug, Clone)]
struct DashSample {
    pos: Vec2,
    dir: Vec2,
    born: f32,
    color: [u8; 3],
}

#[derive(Debug, Clone)]
struct TetherBeamFx {
    from: Vec2,
    to: Vec2,
    color: [u8; 3],
    life: f32,
    max_life: f32,
}

#[derive(Debug, Clone)]
pub struct BannerNotice {
    pub title: String,
    pub subtitle: String,
    pub color: [u8; 3],
    pub elapsed: f32,
    pub duration: f32,
}

#[derive(Debug, Clone, Default)]
pub struct ScreenFlashState {
    pub hit_flash: f32,
    pub ultra_flash: f32,
    pub dash_pulse: f32,
    pub boost_pulse: f32,
    pub boss_flash: f32,
}

impl ScreenFlashState {
    pub fn tick(&mut self, dt: f32) {
        let f60 = (dt * 60.0).max(0.0);
        // Python decays: hit/ultra ~0.075/frame, dash 0.065/frame, boost 0.080/frame, boss 0.045/frame
        self.hit_flash = (self.hit_flash - 0.075 * f60).max(0.0);
        self.ultra_flash = (self.ultra_flash - 0.075 * f60).max(0.0);
        self.dash_pulse = (self.dash_pulse - 0.065 * f60).max(0.0);
        self.boost_pulse = (self.boost_pulse - 0.080 * f60).max(0.0);
        self.boss_flash = (self.boss_flash - 0.045 * f60).max(0.0);
    }

    pub fn clear(&mut self) {
        *self = Self::default();
    }
}

pub struct ParticleSystem {
    pub particles: Vec<Particle>,
    pub motes: Vec<DissolveMote>,
    pub popups: Vec<PopupItem>,
    afterimages: VecDeque<DashSample>,
    tether_beams: Vec<TetherBeamFx>,
    last_dash_sample: f32,
    was_dashing: bool,
    pub flashes: ScreenFlashState,
    pub banners: VecDeque<BannerNotice>,
    rng: rand::rngs::ThreadRng,
}

impl Default for ParticleSystem {
    fn default() -> Self {
        Self::new()
    }
}

impl ParticleSystem {
    pub fn new() -> Self {
        Self {
            particles: Vec::with_capacity(PARTICLE_HARD_CAP),
            motes: Vec::with_capacity(128),
            popups: Vec::with_capacity(64),
            afterimages: VecDeque::with_capacity(DASH_MAX_SAMPLES),
            tether_beams: Vec::with_capacity(16),
            last_dash_sample: -10.0,
            was_dashing: false,
            flashes: ScreenFlashState::default(),
            banners: VecDeque::with_capacity(4),
            rng: rand::thread_rng(),
        }
    }

    pub fn clear(&mut self) {
        self.particles.clear();
        self.motes.clear();
        self.popups.clear();
        self.afterimages.clear();
        self.tether_beams.clear();
        self.last_dash_sample = -10.0;
        self.was_dashing = false;
        self.flashes.clear();
        self.banners.clear();
    }

    fn capped_count(&self, count: usize) -> usize {
        let n = self.particles.len();
        if n >= PARTICLE_HARD_CAP {
            return 0;
        }
        let mut c = count;
        if n >= PARTICLE_SOFT_CAP {
            c = (count / 3).max(1);
        }
        c.min(PARTICLE_HARD_CAP - n)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn emit(
        &mut self,
        pos: Vec2,
        color: [u8; 3],
        count: usize,
        speed: f32,
        life: f32,
        size: f32,
        direction: Option<Vec2>,
        spread_angle: f32,
        decay: bool,
    ) {
        let count = self.capped_count(count);
        if count == 0 {
            return;
        }
        let base_ang = direction
            .filter(|d| d.length_squared() > 1e-8)
            .map(|d| d.y.atan2(d.x));
        for _ in 0..count {
            let ang = match base_ang {
                Some(b) => b + self.rng.gen_range(-spread_angle..=spread_angle),
                None => self.rng.gen_range(0.0..TAU),
            };
            let spd = speed * self.rng.gen_range(0.55..=1.25);
            let p_life = (life * self.rng.gen_range(0.75..=1.25)).max(0.05);
            self.particles.push(Particle {
                pos,
                vel: Vec2::new(ang.cos() * spd, ang.sin() * spd),
                life: p_life,
                max_life: p_life,
                color,
                size: (size * self.rng.gen_range(0.8..=1.2)).max(0.8),
                decay,
                kind: ParticleKind::Dot,
                delay: 0.0,
                aspect: 1.0,
                grow: true,
            });
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub fn emit_sparks(
        &mut self,
        pos: Vec2,
        color: [u8; 3],
        count: usize,
        speed: f32,
        life: f32,
        size: f32,
        direction: Option<Vec2>,
        spread_angle: f32,
    ) {
        let count = self.capped_count(count);
        if count == 0 {
            return;
        }
        let base_ang = direction
            .filter(|d| d.length_squared() > 1e-8)
            .map(|d| d.y.atan2(d.x));
        for _ in 0..count {
            let ang = match base_ang {
                Some(b) => b + self.rng.gen_range(-spread_angle..=spread_angle),
                None => self.rng.gen_range(0.0..TAU),
            };
            let spd = speed * self.rng.gen_range(0.55..=1.25);
            let p_life = (life * self.rng.gen_range(0.75..=1.25)).max(0.05);
            self.particles.push(Particle {
                pos,
                vel: Vec2::new(ang.cos() * spd, ang.sin() * spd),
                life: p_life,
                max_life: p_life,
                color,
                size: (size * self.rng.gen_range(0.8..=1.2)).max(0.8),
                decay: true,
                kind: ParticleKind::Spark,
                delay: 0.0,
                aspect: 1.0,
                grow: false,
            });
        }
    }

    pub fn add_ground_ring(
        &mut self,
        pos: Vec2,
        color: [u8; 3],
        world_radius: f32,
        ttl: f32,
        delay: f32,
        grow: bool,
    ) {
        if self.capped_count(1) == 0 {
            return;
        }
        let aspect = if ISO_SCALE_X > 0.0 {
            ISO_SCALE_Y / ISO_SCALE_X
        } else {
            1.0
        };
        let screen_r = world_radius * SQRT_2 * ISO_SCALE_X;
        let ttl = ttl.max(0.05);
        let delay = delay.max(0.0);
        let life = ttl + delay;
        self.particles.push(Particle {
            pos,
            vel: Vec2::ZERO,
            life,
            max_life: life,
            color,
            size: screen_r.max(2.0),
            decay: false,
            kind: ParticleKind::Ring,
            delay,
            aspect,
            grow,
        });
    }

    pub fn add_glow(&mut self, pos: Vec2, color: [u8; 3], radius: f32, ttl: f32) {
        if self.capped_count(1) == 0 {
            return;
        }
        let ttl = ttl.max(0.04);
        self.particles.push(Particle {
            pos,
            vel: Vec2::ZERO,
            life: ttl,
            max_life: ttl,
            color,
            size: radius.max(2.0),
            decay: false,
            kind: ParticleKind::Glow,
            delay: 0.0,
            aspect: 1.0,
            grow: false,
        });
    }

    pub fn add_laser_beam(&mut self, start: Vec2, end: Vec2, color: [u8; 3]) {
        let d = dist(start, end);
        let steps = ((d / 15.0) as usize).max(3).min(40);
        let delta = (end - start) / (steps as f32);
        let mut cur = start;
        for _ in 0..steps {
            self.emit(cur, color, 2, 40.0, 0.3, 2.0, None, TAU, true);
            cur += delta;
        }
    }

    pub fn burst_dissolve(&mut self, pos: Vec2, color: [u8; 3], count: usize, reach: f32, boost: f32) {
        let base_ang = self.rng.gen_range(0.0..TAU);
        for i in 0..count {
            let ang = base_ang + (i as f32 / count.max(1) as f32) * TAU + self.rng.gen_range(-0.22..0.22);
            let spd = (reach * 2.4 + 45.0) * boost * self.rng.gen_range(0.7..1.25);
            let life = self.rng.gen_range(0.28..0.52);
            self.motes.push(DissolveMote {
                pos,
                vel: Vec2::new(ang.cos() * spd, ang.sin() * spd),
                radius: self.rng.gen_range(2.2..4.2) * boost.min(1.4),
                color: mix_rgb(color, [255, 255, 255], 0.25),
                life,
                max_life: life,
            });
        }
    }

    pub fn add_popup(&mut self, pos: Vec2, text: impl Into<String>, color: [u8; 3], big: bool) {
        let max_life = if big { 0.95 } else { 0.72 };
        let jx = self.rng.gen_range(-24.0..24.0);
        let vy = if big { 78.0 } else { 58.0 };
        self.popups.push(PopupItem {
            pos,
            vel: Vec2::new(jx, vy),
            text: text.into(),
            color,
            life: max_life,
            max_life,
            big,
        });
    }

    pub fn push_banner(&mut self, title: String, subtitle: String, color: [u8; 3], duration: f32) {
        let dur = duration.max(1.2);
        // Replace oldest queued if > 3 to keep responsive
        if self.banners.len() >= 3 {
            self.banners.pop_front();
        }
        self.banners.push_back(BannerNotice {
            title,
            subtitle,
            color,
            elapsed: 0.0,
            duration: dur,
        });
    }

    pub fn track_dash(
        &mut self,
        t: f32,
        is_dashing: bool,
        pos: Vec2,
        dir: Vec2,
        trail_color: [u8; 3],
        enabled: bool,
        reduce_motion: bool,
    ) {
        if !enabled || reduce_motion {
            self.afterimages.clear();
            self.was_dashing = false;
            return;
        }
        if is_dashing && (!self.was_dashing || t - self.last_dash_sample >= DASH_SAMPLE_S) {
            if self.afterimages.len() >= DASH_MAX_SAMPLES {
                self.afterimages.pop_front();
            }
            self.afterimages.push_back(DashSample {
                pos,
                dir: if dir.length_squared() > 1e-6 {
                    dir.normalized()
                } else {
                    Vec2::new(1.0, 0.0)
                },
                born: t,
                color: trail_color,
            });
            self.last_dash_sample = t;
        }
        self.was_dashing = is_dashing;
        while let Some(front) = self.afterimages.front() {
            if t - front.born >= DASH_FADE_S {
                self.afterimages.pop_front();
            } else {
                break;
            }
        }
    }

    pub fn handle_sim_events(&mut self, events: &[SimEvent], reduce_motion: bool) {
        for ev in events {
            match ev {
                SimEvent::DamageResolved(_) => {}
                SimEvent::HitParticles { pos, color } => {
                    if reduce_motion {
                        self.emit(*pos, *color, 7, 135.0, 0.28, 2.4, None, TAU, true);
                    } else {
                        self.emit_sparks(*pos, *color, 5, 145.0, 0.24, 2.1, None, TAU);
                        self.emit(*pos, *color, 2, 82.0, 0.18, 1.6, None, TAU, true);
                    }
                }
                SimEvent::CritSpark(pos) => {
                    if reduce_motion {
                        self.emit(*pos, [255, 235, 90], 10, 180.0, 0.35, 3.4, None, TAU, true);
                        self.emit(*pos, [255, 255, 240], 4, 220.0, 0.20, 2.5, None, TAU, true);
                    } else {
                        self.emit_sparks(*pos, [255, 235, 90], 8, 210.0, 0.29, 3.2, None, TAU);
                        self.emit_sparks(*pos, [255, 255, 240], 4, 255.0, 0.18, 2.4, None, TAU);
                    }
                    self.add_glow(*pos, [255, 230, 110], 24.0, 0.14);
                }
                SimEvent::ShieldHit { pos, .. } => {
                    self.emit(*pos, [120, 220, 255], 8, 120.0, 0.28, 2.5, None, TAU, true);
                    self.add_ground_ring(*pos, [130, 225, 255], 26.0, 0.22, 0.0, true);
                }
                SimEvent::WardAbsorb { pos } => {
                    self.emit_sparks(*pos, [115, 190, 255], 3, 105.0, 0.22, 1.8, None, TAU);
                }
                SimEvent::TetherBeam { from, to, color } => {
                    self.tether_beams.push(TetherBeamFx {
                        from: *from,
                        to: *to,
                        color: *color,
                        life: 0.36,
                        max_life: 0.36,
                    });
                    self.emit_sparks(*to, *color, 3, 95.0, 0.22, 1.8, None, TAU);
                }
                SimEvent::DeathExplosion { pos, color, behavior } => {
                    let is_boss = behavior.starts_with("boss_");
                    let is_bomb_blast = behavior == "bomber_blast";
                    if is_bomb_blast {
                        let spark_count = if reduce_motion { 7 } else { 16 };
                        self.emit_sparks(*pos, [255, 145, 66], spark_count, 245.0, 0.30, 3.4, None, TAU);
                        self.emit_sparks(*pos, [255, 236, 192], (spark_count / 2).max(3), 300.0, 0.17, 2.0, None, TAU);
                        self.add_ground_ring(*pos, [255, 128, 54], BOMB_BLAST_RADIUS, 0.32, 0.0, true);
                        self.add_ground_ring(
                            *pos,
                            [255, 210, 145],
                            BOMB_BLAST_RADIUS * 0.76,
                            0.25,
                            0.08,
                            true,
                        );
                        self.add_ground_ring(
                            *pos,
                            [255, 244, 218],
                            BOMB_BLAST_RADIUS * 0.38,
                            0.20,
                            0.05,
                            true,
                        );
                        self.add_glow(*pos, [255, 148, 62], 62.0, 0.14);
                        self.add_glow(*pos, [255, 232, 183], 30.0, 0.09);
                    } else {
                        let cnt = if is_boss { 40 } else { 18 };
                        let spd = if is_boss { 230.0 } else { 155.0 };
                        self.emit(*pos, *color, cnt, spd, 0.45, if is_boss { 3.8 } else { 2.8 }, None, TAU, true);
                        self.emit(*pos, [255, 245, 210], cnt / 3, spd * 1.15, 0.25, 2.4, None, TAU, true);
                        self.add_ground_ring(
                            *pos,
                            *color,
                            if is_boss { 90.0 } else { 42.0 },
                            0.32,
                            0.0,
                            true,
                        );
                        self.add_glow(
                            *pos,
                            *color,
                            if is_boss { 75.0 } else { 36.0 },
                            0.22,
                        );
                    }
                }
                SimEvent::KillBurst { pos, color, big } => {
                    let cnt = if *big { 22 } else { 10 };
                    self.emit(*pos, *color, cnt, if *big { 190.0 } else { 130.0 }, 0.38, if *big { 3.3 } else { 2.4 }, None, TAU, true);
                }
                SimEvent::BossDeath(pos, color) => {
                    self.emit(*pos, *color, 45, 260.0, 0.65, 4.2, None, TAU, true);
                    self.emit(*pos, [255, 235, 180], 28, 310.0, 0.45, 3.2, None, TAU, true);
                    self.add_ground_ring(*pos, *color, 130.0, 0.55, 0.0, true);
                    self.add_ground_ring(*pos, [255, 240, 210], 85.0, 0.42, 0.08, true);
                    self.add_glow(*pos, [255, 230, 190], 110.0, 0.35);
                }
                SimEvent::BossDeathFlash => {
                    if !reduce_motion {
                        self.flashes.boss_flash = 1.0;
                    }
                }
                SimEvent::BossTeleport { from, to, color } => {
                    self.emit(*from, *color, 18, 165.0, 0.36, 3.0, None, TAU, true);
                    self.add_ground_ring(*from, *color, 52.0, 0.28, 0.0, false);
                    self.add_glow(*from, *color, 44.0, 0.22);
                    self.add_ground_ring(*to, *color, 76.0, 0.34, 0.0, true);
                    self.emit_sparks(*to, *color, 16, 230.0, 0.34, 3.0, None, TAU);
                    self.add_glow(*to, [220, 248, 255], 58.0, 0.24);
                }
                SimEvent::FlakDetonation(pos) => {
                    self.emit(*pos, [255, 160, 50], 14, 175.0, 0.45, 3.2, None, TAU, true);
                    self.emit(*pos, [255, 225, 150], 8, 125.0, 0.26, 2.4, None, TAU, true);
                    self.add_ground_ring(*pos, [255, 185, 90], 192.0 * 0.45, 0.28, 0.0, true);
                    self.add_glow(*pos, [255, 175, 70], 68.0, 0.18);
                }
                SimEvent::Shockwave { pos, color, max_radius, ttl } => {
                    self.add_ground_ring(*pos, *color, *max_radius, *ttl, 0.0, true);
                }
                SimEvent::PickupCollection { pos, color } => {
                    self.emit(*pos, *color, 10, 115.0, 0.32, 2.4, None, TAU, true);
                    self.add_glow(*pos, *color, 26.0, 0.18);
                }
                SimEvent::PickupRing { pos, color } => {
                    self.add_ground_ring(*pos, *color, 40.0, 0.30, 0.0, true);
                }
                SimEvent::DashEffect { pos, dir, color } => {
                    let back = -(*dir);
                    self.emit(*pos, *color, 8, 140.0, 0.25, 2.5, Some(back), 0.45, true);
                }
                SimEvent::MuzzleFlash { pos, dir } => {
                    self.emit(*pos, [255, 235, 175], 3, 130.0, 0.12, 1.8, Some(*dir), 0.35, true);
                }
                SimEvent::LaserBeamFx { start, end, color } => {
                    self.add_laser_beam(*start, *end, *color);
                }
                SimEvent::VortexSwirl { pos, time, radius } => {
                    if self.capped_count(1) > 0 {
                        let ang = time * 4.0;
                        let off = Vec2::new(ang.cos() * radius, ang.sin() * radius);
                        self.particles.push(Particle {
                            pos: *pos + off,
                            vel: -off.normalized() * 52.0,
                            life: 0.4,
                            max_life: 0.4,
                            color: [180, 140, 255],
                            size: 3.0,
                            decay: false,
                            kind: ParticleKind::Dot,
                            delay: 0.0,
                            aspect: 1.0,
                            grow: true,
                        });
                    }
                }
                SimEvent::BoostFlame { pos, dir } => {
                    let back = -(*dir);
                    self.emit(*pos, [130, 220, 255], 3, 160.0, 0.22, 3.0, Some(back), 0.35, true);
                    self.emit(*pos, [255, 140, 40], 4, 130.0, 0.30, 3.6, Some(back), 0.55, true);
                }
                SimEvent::StepDust { pos, dir } => {
                    let back = -(*dir);
                    self.emit(*pos, [175, 195, 215], 2, 55.0, 0.25, 1.9, Some(back), 0.5, true);
                }
                SimEvent::EliteAura { pos, color } => {
                    let ang = self.rng.gen_range(0.0..TAU);
                    let p = *pos + Vec2::new(ang.cos() * 18.0, ang.sin() * 18.0);
                    self.emit(p, *color, 1, 25.0, 0.35, 2.1, None, TAU, true);
                }
                SimEvent::RepulsorBlast { pos, stunned_positions } => {
                    self.add_ground_ring(*pos, [190, 240, 255], 220.0, 0.45, 0.0, true);
                    self.add_glow(*pos, [190, 240, 255], 70.0, 0.22);
                    for sp in stunned_positions {
                        self.emit(*sp, [190, 240, 255], 5, 45.0, 0.40, 2.2, None, TAU, true);
                    }
                }
                SimEvent::UltraFlash { pos, color, radius } => {
                    self.add_glow(*pos, *color, (*radius).max(90.0), 0.25);
                    self.add_ground_ring(*pos, *color, *radius, 0.35, 0.0, true);
                }
                SimEvent::Popup { pos, text, color, big } => {
                    self.add_popup(*pos, text.clone(), *color, *big);
                }
                SimEvent::Banner { title, subtitle, color, duration } => {
                    self.push_banner(title.clone(), subtitle.clone(), *color, *duration);
                }
                SimEvent::ScreenFlashHit(s) => {
                    if !reduce_motion {
                        self.flashes.hit_flash = self.flashes.hit_flash.max(*s);
                    }
                }
                SimEvent::ScreenFlashUltra(s) => {
                    if !reduce_motion {
                        self.flashes.ultra_flash = self.flashes.ultra_flash.max(*s);
                    }
                }
                SimEvent::ScreenFlashBoost(s) => {
                    if !reduce_motion {
                        self.flashes.boost_pulse = self.flashes.boost_pulse.max(*s);
                    }
                }
                SimEvent::ScreenFlashDash(s) => {
                    if !reduce_motion {
                        self.flashes.dash_pulse = self.flashes.dash_pulse.max(*s);
                    }
                }
                SimEvent::Audio { .. }
                | SimEvent::AudioCue(_)
                | SimEvent::WaveCleared(_)
                | SimEvent::BossRewardOpened
                | SimEvent::GameOver => {}
            }
        }
    }

    pub fn tick(&mut self, dt: f32) {
        let dt = dt.clamp(0.0, 0.1);
        self.flashes.tick(dt);

        if let Some(front) = self.banners.front_mut() {
            front.elapsed += dt;
            if front.elapsed >= front.duration {
                self.banners.pop_front();
            }
        }

        let mut i = 0;
        while i < self.particles.len() {
            let p = &mut self.particles[i];
            p.life -= dt;
            if p.life <= 0.0 {
                self.particles.swap_remove(i);
                continue;
            }
            if matches!(p.kind, ParticleKind::Dot | ParticleKind::Spark) {
                let dpos = p.vel * dt;
                p.pos += dpos;
                if p.decay {
                    p.vel *= (1.0 - 2.6 * dt).max(0.0);
                }
            }
            i += 1;
        }

        let mdt = dt.min(0.05);
        let drag = (1.0 - MOTE_DRAG * mdt).max(0.0);
        let mut mi = 0;
        while mi < self.motes.len() {
            let m = &mut self.motes[mi];
            m.life -= dt;
            if m.life <= 0.0 {
                self.motes.swap_remove(mi);
                continue;
            }
            m.pos += m.vel * mdt;
            m.vel *= drag;
            mi += 1;
        }

        let mut pi = 0;
        while pi < self.popups.len() {
            let pop = &mut self.popups[pi];
            pop.life -= dt;
            if pop.life <= 0.0 {
                self.popups.swap_remove(pi);
                continue;
            }
            pop.pos += pop.vel * dt;
            pop.vel.y -= 55.0 * dt;
            pop.vel.x *= (1.0 - 2.2 * dt).max(0.0);
            pi += 1;
        }

        let mut ti = 0;
        while ti < self.tether_beams.len() {
            self.tether_beams[ti].life -= dt;
            if self.tether_beams[ti].life <= 0.0 {
                self.tether_beams.swap_remove(ti);
            } else {
                ti += 1;
            }
        }
    }

    pub fn draw_world(
        &self,
        add_batch: &mut SdfBatch,
        t: f32,
        cam_world: Vec2,
        view_w: f32,
        view_h: f32,
        shake: Vec2,
    ) {
        // 1. Dash Afterimages (tapered neon streaks behind player)
        for s in &self.afterimages {
            let age = t - s.born;
            if age < 0.0 || age >= DASH_FADE_S {
                continue;
            }
            let frac = 1.0 - age / DASH_FADE_S;
            let (sx, sy) = to_iso_cam(s.pos, cam_world, view_w, view_h, shake);
            let tail = s.pos - s.dir * (DASH_STREAK_PX * (0.4 + 0.6 * frac));
            let (tx, ty) = to_iso_cam(tail, cam_world, view_w, view_h, shake);
            add_batch.line(
                sx,
                sy,
                tx,
                ty,
                DASH_THICKNESS * frac,
                linear_rgba_f(s.color, frac * 0.62, 1.75),
            );
            add_batch.glow(sx, sy, 14.0 * frac, 1.8, linear_rgba_f(s.color, frac * 0.4, 1.6));
        }

        // 2. Particles
        for p in &self.particles {
            if p.life > p.max_life - p.delay {
                continue;
            }
            let ttl = (p.max_life - p.delay).max(0.01);
            let frac = (p.life / ttl).clamp(0.0, 1.0);
            let prog = 1.0 - frac;
            let (sx, sy) = to_iso_cam(p.pos, cam_world, view_w, view_h, shake);
            match p.kind {
                ParticleKind::Dot => {
                    let r = p.size * (0.45 + 0.55 * frac);
                    add_batch.circle(sx, sy, r, linear_rgba_f(p.color, frac * 0.9, 1.9));
                    if p.size >= 2.8 {
                        add_batch.glow(sx, sy, r * 2.2, 1.8, linear_rgba_f(p.color, frac * 0.35, 1.4));
                    }
                }
                ParticleKind::Spark => {
                    let dir = p.vel.normalized();
                    let trail = p.size * (2.2 + 3.4 * (1.0 - frac));
                    let tail = p.pos - dir * trail;
                    let (tx, ty) = to_iso_cam(tail, cam_world, view_w, view_h, shake);
                    add_batch.line(
                        sx,
                        sy,
                        tx,
                        ty,
                        (p.size * (0.34 + frac * 0.36)).max(0.8),
                        linear_rgba_f(p.color, frac * 0.92, 1.8),
                    );
                }
                ParticleKind::Glow => {
                    let r = p.size * (0.65 + 0.45 * prog);
                    add_batch.glow(sx, sy, r, 1.8, linear_rgba_f(p.color, frac * 0.72, 2.2));
                }
                ParticleKind::Ring => {
                    let k = if p.grow { prog } else { frac };
                    let rx = (p.size * (0.15 + 0.85 * k)).max(1.0);
                    let ry = (rx * p.aspect).max(0.5);
                    let thick = (3.4 * frac).max(1.0);
                    add_batch.ring(sx, sy, rx, ry, thick, linear_rgba_f(p.color, frac * 0.85, 2.0));
                }
            }
        }

        // 3. Enemy Dissolve Motes
        for m in &self.motes {
            let frac = (m.life / m.max_life).clamp(0.0, 1.0);
            let (sx, sy) = to_iso_cam(m.pos, cam_world, view_w, view_h, shake);
            add_batch.circle(
                sx,
                sy,
                m.radius * (0.4 + 0.6 * frac),
                linear_rgba_f(m.color, frac * 0.9, 1.85),
            );
        }

        // 4. Support & Mender Tether Beams
        for beam in &self.tether_beams {
            let frac = (beam.life / beam.max_life.max(0.01)).clamp(0.0, 1.0);
            let (x0, y0) = to_iso_cam(beam.from, cam_world, view_w, view_h, shake);
            let (x1, y1) = to_iso_cam(beam.to, cam_world, view_w, view_h, shake);
            add_batch.line(
                x0,
                y0,
                x1,
                y1,
                3.8 * (0.5 + 0.5 * frac),
                linear_rgba_f(beam.color, frac * 0.45, 1.5),
            );
            add_batch.line(
                x0,
                y0,
                x1,
                y1,
                1.6,
                linear_rgba_f(mix_rgb(beam.color, [255, 255, 255], 0.45), frac * 0.9, 1.9),
            );
            add_batch.circle(x1, y1, 3.2 * frac + 1.0, linear_rgba_f(beam.color, frac * 0.85, 1.8));
        }
    }

    pub fn draw_popups(
        &self,
        text_batch: &mut TextBatch,
        scale: f32,
        cam_world: Vec2,
        view_w: f32,
        view_h: f32,
        shake: Vec2,
    ) {
        for pop in &self.popups {
            let frac = (pop.life / pop.max_life).clamp(0.0, 1.0);
            let alpha = (frac * 1.4).min(1.0);
            let (sx, sy) = to_iso_cam(pop.pos, cam_world, view_w, view_h, shake);
            let font = if pop.big { FontId::Head } else { FontId::Bold };
            let px = (if pop.big { 18.0 } else { 14.0 }) * scale.clamp(0.85, 1.5);
            text_batch.draw_hdr(
                pop.text.as_str(),
                font,
                px,
                sx,
                sy + 14.0,
                AlignX::Center,
                AlignY::Center,
                pop.color,
                alpha,
                true,
            );
        }
    }
}

/// Exponential ease-out cubic for cards/banners.
#[inline]
pub fn ease_out_cubic(x: f32) -> f32 {
    let x = x.clamp(0.0, 1.0);
    1.0 - (1.0 - x).powi(3)
}

#[allow(dead_code)]
fn _unused_rgba_keep() {
    let _ = linear_rgba([0, 0, 0], 0, 1.0);
}
