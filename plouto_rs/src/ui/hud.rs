use std::collections::VecDeque;
use std::f32::consts::{FRAC_PI_2, TAU};

use crate::render::particles::BannerNotice;
use crate::render::sdf::{linear_rgba, mix_rgb, SdfBatch};
use crate::render::text::{AlignX, AlignY, FontId, FontPack, TextBatch};
use crate::sim::enemy::{boss_title, BossPersona, EnemySubState};
use crate::sim::config::ULTRA_BEAM_COLOR;
use crate::sim::daily::is_daily_run;
use crate::sim::powerup::{powerup_duration_seconds, timed_active, timed_powerup_states};
use crate::sim::mutators::{combined_score_multiplier, format_score_mult, mutator_names};
use crate::sim::rpg::{format_perm_hud, format_temp_hud, has_relic};
use crate::sim::score::{combo_window_fraction, COMBO_DECAY_DELAY};
use crate::sim::state::SimState;
use crate::sim::weapons::get_weapon_color;
use crate::ui::theme::{
    draw_panel, pt_px, ui_scale, UiRect, ACCENT, DANGER, GOLD, MUTED, PANEL, TEXT,
};

pub const TOAST_SECONDS: f32 = 3.2;
pub const TOAST_FADE_IN_S: f32 = 0.25;
pub const TOAST_FADE_OUT_S: f32 = 0.45;
/// Toasts waiting behind the one on screen. Anything past this is folded into a single
/// "+N more" summary toast, shown after the queue drains, so no unlock goes unannounced.
pub const TOAST_MAX_PENDING: usize = 6;

/// Cooldown ring fills from empty to ready while the Ultra lockout runs.
pub fn ultra_cooldown_fraction(
    charges: i32,
    cd_left: f32,
    cooldown: f32,
    cooldown_started: bool,
) -> f32 {
    if cd_left > 0.0 {
        if cooldown <= 0.0 {
            0.0
        } else {
            (1.0 - cd_left / cooldown).clamp(0.0, 1.0)
        }
    } else if charges > 0 || cooldown_started {
        1.0
    } else {
        0.0
    }
}

pub fn ultra_ready_alpha(ready: bool, pulse_t: f32, reduce_motion: bool) -> u8 {
    if !ready {
        return if reduce_motion { 190 } else { 175 };
    }
    if reduce_motion {
        return 255;
    }
    (210.0 + 45.0 * (0.5 + 0.5 * (pulse_t * 5.0).sin())).round() as u8
}

#[cfg(test)]
mod ultra_gauge_tests {
    use super::ultra_cooldown_fraction;

    #[test]
    fn cooldown_ring_tracks_time_to_use_not_the_charge_count() {
        assert_eq!(ultra_cooldown_fraction(0, 0.0, 10.0, false), 0.0);
        assert!((ultra_cooldown_fraction(1, 5.0, 10.0, true) - 0.5).abs() < 1e-6);
        assert!((ultra_cooldown_fraction(0, 5.0, 10.0, true) - 0.5).abs() < 1e-6);
        assert_eq!(ultra_cooldown_fraction(0, 0.0, 10.0, true), 1.0);
        assert_eq!(ultra_cooldown_fraction(2, 0.0, 10.0, false), 1.0);
        assert_eq!(ultra_cooldown_fraction(1, 5.0, 0.0, true), 0.0);
    }
}

#[cfg(test)]
mod comms_tests {
    use super::AnimatedComms;
    use crate::render::sdf::SdfBatch;
    use crate::render::text::{FontPack, TextBatch};
    use crate::sim::state::{RunSetup, SimState};

    #[test]
    fn type_on_cursor_uses_rendered_geometry_not_a_missing_font_glyph() {
        let state = SimState::new(RunSetup::default());
        let mut comms = AnimatedComms::new();
        comms.update(&state, 0.36);
        let fonts = FontPack::load().expect("HUD fonts should load");

        let mut animated_sdf = SdfBatch::default();
        let mut animated_add = SdfBatch::default();
        let mut animated_text = TextBatch::default();
        comms.draw(
            false,
            1.0,
            1280,
            720,
            &mut animated_sdf,
            &mut animated_add,
            &mut animated_text,
            &fonts,
        );

        assert!(animated_text.items.iter().all(|item| !item.text.contains('▌')));
        assert!(animated_sdf.instances.len() > 3, "the animated cursor should add a visible line primitive");

        let mut reduced_sdf = SdfBatch::default();
        let mut reduced_add = SdfBatch::default();
        let mut reduced_text = TextBatch::default();
        comms.draw(
            true,
            1.0,
            1280,
            720,
            &mut reduced_sdf,
            &mut reduced_add,
            &mut reduced_text,
            &fonts,
        );
        assert_eq!(
            animated_sdf.instances.len(),
            reduced_sdf.instances.len() + 1,
            "reduced-motion mode should omit the blinking cursor"
        );
    }
}

#[derive(Debug, Clone)]
pub struct ToastItem {
    pub title: String,
    pub subtitle: String,
}

pub struct ToastQueue {
    pending: VecDeque<ToastItem>,
    /// Toasts folded into the summary because `pending` was full.
    overflow: u32,
    pub current: Option<ToastItem>,
    pub age: f32,
}

impl Default for ToastQueue {
    fn default() -> Self {
        Self::new()
    }
}

impl ToastQueue {
    pub fn new() -> Self {
        Self {
            pending: VecDeque::with_capacity(TOAST_MAX_PENDING),
            overflow: 0,
            current: None,
            age: 0.0,
        }
    }

    /// Queue a toast. Returns true when it is shown or queued on its own, false when it was
    /// folded into the "+N more" summary.
    pub fn push(&mut self, title: impl Into<String>, subtitle: impl Into<String>) -> bool {
        let item = ToastItem {
            title: title.into(),
            subtitle: subtitle.into(),
        };
        if self.current.is_none() {
            self.current = Some(item);
            self.age = 0.0;
            return true;
        }
        if self.pending.len() < TOAST_MAX_PENDING {
            self.pending.push_back(item);
            return true;
        }
        self.overflow = self.overflow.saturating_add(1);
        false
    }

    /// Next toast after the current one: queued items first, then the overflow summary.
    fn next_item(&mut self) -> Option<ToastItem> {
        if let Some(item) = self.pending.pop_front() {
            return Some(item);
        }
        if self.overflow > 0 {
            let n = self.overflow;
            self.overflow = 0;
            return Some(ToastItem {
                title: "More Unlocked".to_string(),
                subtitle: format!("+{n} more, see Hangar"),
            });
        }
        None
    }

    pub fn tick(&mut self, dt: f32) {
        if self.current.is_none() {
            return;
        }
        self.age += dt.max(0.0);
        while self.current.is_some() && self.age >= TOAST_SECONDS {
            self.age -= TOAST_SECONDS;
            self.current = self.next_item();
            if self.current.is_none() {
                self.age = 0.0;
            }
        }
    }

    pub fn alpha(&self, reduce_motion: bool) -> f32 {
        if self.current.is_none() {
            return 0.0;
        }
        if reduce_motion {
            return 1.0;
        }
        if self.age < TOAST_FADE_IN_S {
            (self.age / TOAST_FADE_IN_S).clamp(0.0, 1.0)
        } else {
            let left = TOAST_SECONDS - self.age;
            if left < TOAST_FADE_OUT_S {
                (left / TOAST_FADE_OUT_S).clamp(0.0, 1.0)
            } else {
                1.0
            }
        }
    }

    pub fn clear(&mut self) {
        self.pending.clear();
        self.overflow = 0;
        self.current = None;
        self.age = 0.0;
    }

    /// Toasts still waiting to be shown, including the overflow summary when pending.
    pub fn queued_len(&self) -> usize {
        self.pending.len() + usize::from(self.overflow > 0)
    }
}

const COMMS_MAX_PENDING: usize = 4;
const RUN_RELIC_KEYS: [&str; 4] = [
    "relic_graviton",
    "relic_soul_rivet",
    "relic_phase_shard",
    "relic_aegis_relay",
];
const RUN_RELIC_NAMES: [&str; 4] = ["Graviton", "Soul Rivet", "Phase Shard", "Aegis Relay"];

#[derive(Debug, Clone)]
struct CommsLine {
    speaker: &'static str,
    message: String,
    color: [u8; 3],
    duration: f32,
    priority: u8,
    instant: bool,
}

/// Contextual flight chatter with a short, motion-aware type-on animation.
pub struct AnimatedComms {
    current: Option<CommsLine>,
    pending: VecDeque<CommsLine>,
    age: f32,
    last_wave: i32,
    last_boss: Option<(u64, i32)>,
    last_relic_mask: Option<u8>,
    last_hp_fraction: Option<f32>,
    last_buff_mask: Option<u16>,
    ultra_was_ready: Option<bool>,
    last_event: Option<&'static str>,
}

impl Default for AnimatedComms {
    fn default() -> Self {
        Self::new()
    }
}

impl AnimatedComms {
    pub fn new() -> Self {
        Self {
            current: None,
            pending: VecDeque::with_capacity(COMMS_MAX_PENDING),
            age: 0.0,
            last_wave: 0,
            last_boss: None,
            last_relic_mask: None,
            last_hp_fraction: None,
            last_buff_mask: None,
            ultra_was_ready: None,
            last_event: None,
        }
    }

    fn queue(&mut self, speaker: &'static str, message: impl Into<String>, color: [u8; 3], urgent: bool) {
        let message = message.into();
        if self.current.as_ref().is_some_and(|line| line.speaker == speaker && line.message == message)
            || self.pending.iter().any(|line| line.speaker == speaker && line.message == message)
        {
            return;
        }
        let duration = (message.chars().count() as f32 / 34.0 + 2.4).clamp(3.0, 4.8);
        let priority = match speaker {
            "HULL ALERT" => 4,
            "ARENA CONTROL" => 3,
            "THREAT SCAN" => 2,
            "RELIC CACHE" | "SYSTEMS" => 1,
            _ => 0,
        };
        let line = CommsLine { speaker, message, color, duration, priority, instant: urgent };
        if self.current.is_none() {
            self.current = Some(line);
            self.age = 0.0;
        } else if urgent && self.current.as_ref().is_some_and(|current| priority > current.priority) {
            let previous = self.current.replace(line).expect("checked current comms line");
            if previous.duration - self.age > 0.65 {
                self.enqueue_ordered(previous);
            }
            self.age = 0.0;
        } else if self.pending.len() < COMMS_MAX_PENDING {
            self.enqueue_ordered(line);
        } else {
            self.enqueue_ordered(line);
        }
    }

    fn enqueue_ordered(&mut self, line: CommsLine) {
        if self.pending.len() >= COMMS_MAX_PENDING {
            let lowest = self
                .pending
                .iter()
                .enumerate()
                .min_by_key(|(_, queued)| queued.priority)
                .map(|(idx, queued)| (idx, queued.priority));
            if let Some((idx, rank)) = lowest {
                if rank >= line.priority {
                    return;
                }
                self.pending.remove(idx);
            } else {
                return;
            }
        }
        let insert_at = self
            .pending
            .iter()
            .position(|queued| queued.priority < line.priority)
            .unwrap_or(self.pending.len());
        self.pending.insert(insert_at, line);
    }

    fn advance(&mut self, dt: f32) {
        if self.current.is_none() {
            self.current = self.pending.pop_front();
            self.age = 0.0;
        }
        if self.current.is_none() {
            return;
        }
        self.age += dt.max(0.0);
        while self.current.as_ref().is_some_and(|line| self.age >= line.duration) {
            let duration = self.current.as_ref().map_or(0.0, |line| line.duration);
            self.age -= duration;
            self.current = self.pending.pop_front();
            if self.current.is_none() {
                self.age = 0.0;
            }
        }
    }

    pub fn reset(&mut self) {
        *self = Self::new();
    }

    pub fn update(&mut self, state: &SimState, dt: f32) {
        let hp_fraction = state.player.hp as f32 / state.player.max_hp.max(1) as f32;
        if self.last_wave == 0 && state.wave > 0 {
            self.queue("FLIGHT LINK", "We're live. Keep moving and leave yourself a clear lane.", ACCENT, false);
        } else if state.wave > self.last_wave {
            self.queue(
                "FLIGHT LINK",
                format!("Wave {}: contacts closing. Keep a lane open and watch their attack tells.", state.wave),
                ACCENT,
                false,
            );
        }
        self.last_wave = state.wave;

        let boss = state.enemies.iter().find(|enemy| enemy.behavior.starts_with("boss_") && !enemy.is_dead);
        if let Some(boss) = boss {
            if self.last_boss.map(|(id, _)| id) != Some(boss.id) {
                let title = boss_title(&boss.behavior);
                self.queue(
                    "THREAT SCAN",
                    format!("{title} confirmed. {}", boss_comms_intro(&boss.behavior)),
                    [255, 185, 220],
                    true,
                );
            } else if self.last_boss.is_some_and(|(id, phase)| id == boss.id && boss.ai.phase > phase) {
                self.queue(
                    "THREAT SCAN",
                    format!("Phase {}. {}", boss.ai.phase + 1, boss_comms_phase(&boss.behavior, boss.ai.phase)),
                    [255, 165, 135],
                    true,
                );
            }
            self.last_boss = Some((boss.id, boss.ai.phase));
        } else {
            self.last_boss = None;
        }

        if let Some(previous) = self.last_hp_fraction {
            if previous > 0.30 && hp_fraction <= 0.30 {
                self.queue(
                    "HULL ALERT",
                    "Critical hull. Break away and use an opening before the next hit lands.",
                    DANGER,
                    true,
                );
            }
        }
        self.last_hp_fraction = Some(hp_fraction);

        let buffs = active_comms_buffs(state);
        if let Some(previous) = self.last_buff_mask {
            let acquired = buffs & !previous;
            if acquired != 0 {
                let bit = acquired.trailing_zeros() as usize;
                let (_, label, advice) = COMMS_BUFFS[bit];
                self.queue(
                    "SYSTEMS",
                    format!("{label} online. {advice}"),
                    crate::sim::config::powerup_color(COMMS_BUFFS[bit].0),
                    false,
                );
            }
        }
        self.last_buff_mask = Some(buffs);

        let mut relic_mask = 0u8;
        for (idx, key) in RUN_RELIC_KEYS.iter().enumerate() {
            if has_relic(&state.run_permanent_rewards, key) {
                relic_mask |= 1 << idx;
            }
        }
        if let Some(previous) = self.last_relic_mask {
            let acquired = relic_mask & !previous;
            if acquired != 0 {
                let idx = acquired.trailing_zeros() as usize;
                let message = if idx == 3 {
                    "Aegis Relay attuned. Ultra strikes now restore shield.".to_string()
                } else {
                    format!("{} attuned. Its run bonus is now active.", RUN_RELIC_NAMES[idx])
                };
                self.queue("RELIC CACHE", message, [115, 220, 250], true);
            }
        }
        self.last_relic_mask = Some(relic_mask);

        let ultra_ready = state.player.ultra_charges > 0
            && state.player.ultra_cd_until <= state.time;
        if self.ultra_was_ready == Some(false) && ultra_ready {
            self.queue(
                "SYSTEMS",
                "Ultra is charged. Its side gauge is full; unleash it when the pack closes.",
                GOLD,
                false,
            );
        }
        self.ultra_was_ready = Some(ultra_ready);

        let event = state
            .arena_event
            .as_ref()
            .filter(|event| event.active())
            .map(|event| event.kind_name());
        if event.is_some() && event != self.last_event {
            let line = match event.unwrap_or_default() {
                "meteor_shower" => "Meteor shower detected. Move off the marked impact zones.",
                "solar_flare" => "Solar flare incoming. Watch the sweep and cross behind it.",
                "nebula_cloud" => "Nebula cloud ahead. Its field can turn enemy shots aside.",
                _ => "Arena event detected. Keep an eye on the warning markers.",
            };
            self.queue("ARENA CONTROL", line, [255, 205, 125], true);
        }
        self.last_event = event;

        self.advance(dt);
    }

    fn draw(
        &self,
        reduce_motion: bool,
        pulse_t: f32,
        view_w: u32,
        view_h: u32,
        sdf: &mut SdfBatch,
        add: &mut SdfBatch,
        text: &mut TextBatch,
        fonts: &FontPack,
    ) {
        let Some(line) = self.current.as_ref() else { return; };
        let fade_in = if reduce_motion || line.instant { 1.0 } else { (self.age / 0.2).clamp(0.0, 1.0) };
        let fade_out = if reduce_motion { 1.0 } else { ((line.duration - self.age) / 0.35).clamp(0.0, 1.0) };
        let alpha = fade_in.min(fade_out);
        if alpha <= 0.01 { return; }

        let s = ui_scale(view_w, view_h);
        let w = view_w as f32;
        let margin = 12.0 * s;
        let panel_w = (430.0 * s).min((w - margin * 2.0).max(140.0 * s));
        let message_px = pt_px(9.6, s, 8.0);
        let message_width = panel_w - 48.0 * s;
        let full_text_mode = reduce_motion || line.instant;
        let wrapped_lines = if full_text_mode {
            fonts.wrap_lines(FontId::Regular, message_px, &line.message, message_width)
        } else {
            Vec::new()
        };
        let panel_h = (46.0 + wrapped_lines.len().saturating_sub(1) as f32 * 12.0) * s;
        let slide = if reduce_motion || line.instant { 0.0 } else { (1.0 - alpha) * 9.0 * s };
        let x = (w - panel_w) * 0.5;
        // Keep chatter below the boss health strip and away from the wave chip,
        // which occupies the lower-center edge of the HUD.
        let y = margin + 78.0 * s + slide;
        draw_panel(
            sdf,
            UiRect::new(x, y, panel_w, panel_h),
            7.0 * s,
            1.4,
            [8, 20, 32],
            (232.0 * alpha) as u8,
            line.color,
            (185.0 * alpha) as u8,
            2.2 * s,
        );

        let icon_x = x + 17.0 * s;
        let icon_y = y + panel_h * 0.5;
        sdf.ring(icon_x, icon_y, 8.5 * s, 8.5 * s, 1.2 * s, linear_rgba(line.color, (220.0 * alpha) as u8, 1.0));
        let pulse = if reduce_motion { 0.0 } else { (pulse_t * 6.5).sin().abs() };
        sdf.circle(icon_x, icon_y, (2.7 + pulse * 1.2) * s, linear_rgba([235, 255, 255], (245.0 * alpha) as u8, 1.0));
        if !reduce_motion {
            add.glow(icon_x, icon_y, (8.0 + pulse * 2.0) * s, 1.8, linear_rgba(line.color, (95.0 * alpha) as u8, 1.25));
        }
        let meter_x = x + panel_w - 16.0 * s;
        for i in 0..3 {
            let phase = if reduce_motion { 0.65 } else { (pulse_t * 8.0 + i as f32 * 1.5).sin().abs() };
            let bar_h = (4.0 + phase * 9.0) * s;
            let bx = meter_x - (2 - i) as f32 * 4.2 * s;
            sdf.line(bx, icon_y - bar_h * 0.5, bx, icon_y + bar_h * 0.5, 1.7 * s, linear_rgba(line.color, (210.0 * alpha) as u8, 1.0));
        }

        let speaker_px = pt_px(7.4, s, 6.2);
        text.draw(
            line.speaker,
            FontId::Bold,
            speaker_px,
            x + 32.0 * s,
            y + 12.5 * s,
            AlignX::Left,
            AlignY::Center,
            line.color,
            (235.0 * alpha) as u8,
            true,
        );
        let count = line.message.chars().count();
        let visible = if full_text_mode { count } else { ((self.age * 34.0).floor() as usize).min(count) };
        if full_text_mode {
            for (index, row) in wrapped_lines.iter().enumerate() {
                text.draw(
                    row,
                    FontId::Regular,
                    message_px,
                    x + 32.0 * s,
                    y + (30.0 + index as f32 * 12.0) * s,
                    AlignX::Left,
                    AlignY::Center,
                    TEXT,
                    (245.0 * alpha) as u8,
                    false,
                );
            }
        } else {
            let shown: String = line.message.chars().take(visible).collect();
            let shown = fonts.fit_text(FontId::Regular, message_px, &shown, message_width);
            let shown_width = fonts.measure(FontId::Regular, message_px, &shown).0;
            text.draw(
                shown,
                FontId::Regular,
                message_px,
                x + 32.0 * s,
                y + 30.0 * s,
                AlignX::Left,
                AlignY::Center,
                TEXT,
                (245.0 * alpha) as u8,
                false,
            );
            if visible < count {
                // Draw the type-on cursor as geometry; the font has no block-cursor
                // glyph, which rendered as a missing-character placeholder.
                let cursor_x = x + 32.0 * s + shown_width + 1.5 * s;
                let cursor_y = y + 30.0 * s;
                let blink = if (pulse_t * 3.0).fract() < 0.52 { 1.0 } else { 0.38 };
                sdf.line(
                    cursor_x,
                    cursor_y - 4.5 * s,
                    cursor_x,
                    cursor_y + 4.5 * s,
                    1.15 * s,
                    linear_rgba(line.color, (220.0 * alpha * blink) as u8, 1.0),
                );
            }
        }
    }
}

const COMMS_BUFFS: [(&str, &str, &str); 11] = [
    ("laser", "Laser Array", "Line up a clear lane to sweep clustered contacts."),
    ("vortex", "Vortex Field", "Let nearby shots bend wide, then cut through the opening."),
    ("drone", "Support Drone", "Keep threats in range while it adds steady pressure."),
    ("ricochet", "Ricochet Rounds", "Angle shots off the arena edge to reach the pack."),
    ("homing", "Homing Rounds", "Keep moving and let the rounds track dense groups."),
    ("time_slow", "Time Dilation", "Use the slowed window to cross a crowded lane."),
    ("magnet", "Salvage Magnet", "Sweep up nearby drops as you pass; keep moving under fire."),
    ("boost", "Boost Overdrive", "Save a burst to slip through a closing gap."),
    ("weapon", "Weapon Surge", "Press the attack while the damage surge is active."),
    ("repulsor", "Repulsor", "Save its pulse to clear a close threat."),
    ("chain", "Chain Surge", "Aim into a cluster and let the arcs jump between targets."),
];

fn boss_comms_intro(behavior: &str) -> &'static str {
    match behavior {
        "boss_thunder" => "Move during its vanish, then cross the marked spokes before the delayed ring.",
        "boss_laser" => "Change direction during the marked charge; cross the beam sweep, not its length.",
        "boss_trapmaster" => "Shift your heading when spikes are marked; keep one escape lane open.",
        "boss_swarmqueen" => "Break egg sacs before they hatch, then strafe across the plasma fan.",
        "boss_brute" => "Bait its charge into open space and turn on the stun after impact.",
        "boss_abyss_gaze" => "Watch its orbit and range; cross each marked laser lane after its warning.",
        "boss_womb_core" => "Leave the marked pulse zone; change heading if it leads your path.",
        "boss_eclipse_archon" => "Follow the gap in each radial burst; it shifts after the escape dash.",
        _ => "Read the windup, then move through an open lane.",
    }
}

fn boss_comms_phase(behavior: &str, phase: i32) -> &'static str {
    match (behavior, phase) {
        ("boss_thunder", 1..) => "A delayed second spoke ring joins the volley; keep moving between releases.",
        ("boss_laser", 1..) => "The marked sweep covers more lanes; cross the warning arc before it fires.",
        ("boss_trapmaster", 1..) => "A wider four-spike ring leads your path; turn early and keep a lane open.",
        ("boss_swarmqueen", 1..) => "Eggs hatch faster and arrive in pairs; clear a sac before the next volley.",
        ("boss_brute", 2..) => "Delayed blue cross-lanes follow the charge; cross between their marks.",
        ("boss_brute", 1..) => "Wall impacts now seed extra shots; leave room to turn after the charge.",
        ("boss_abyss_gaze", 1..) => "Its lane spacing is changing; wait for the marks, then cross decisively.",
        ("boss_womb_core", 1..) => "More shots and adds join the cycle; leave the pulse mark, then move through a gap.",
        ("boss_eclipse_archon", 1..) => "The safe gap rotates between bursts; track it and move with the opening.",
        _ => "The pattern is changing; follow the new floor and beam tells.",
    }
}

fn active_comms_buffs(state: &SimState) -> u16 {
    let mut mask = 0u16;
    for (i, (kind, _, _)) in COMMS_BUFFS[..9].iter().enumerate() {
        let active = match *kind {
            "laser" => timed_active(state.player.laser_until, state.time),
            "vortex" => timed_active(state.player.vortex_until, state.time),
            "drone" => timed_active(state.player.drone_until, state.time),
            "ricochet" => timed_active(state.player.ricochet_until, state.time),
            "homing" => timed_active(state.player.homing_until, state.time),
            "time_slow" => timed_active(state.player.time_slow_until, state.time),
            "magnet" => timed_active(state.player.magnet_until, state.time),
            "boost" => timed_active(state.player.infinite_boost_until, state.time),
            "weapon" => timed_active(state.player.weapon_until, state.time),
            _ => false,
        };
        if active { mask |= 1 << i; }
    }
    if state.repulsor.charges > 0 || state.time < state.repulsor.cooldown_until { mask |= 1 << 9; }
    if state.chain.is_active(state.time) { mask |= 1 << 10; }
    mask
}

#[derive(Default)]
pub struct ComboRingAnim {
    pub frac: f32,
    pub pulse: f32,
    last_combo: f32,
    last_time: f32,
}

impl ComboRingAnim {
    pub fn update(&mut self, combo: f32, combo_timer: f32, sim_time: f32, dt: f32, reduce_motion: bool) {
        if combo <= 1.001 {
            self.frac = 0.0;
            self.last_combo = combo;
        } else {
            if combo > self.last_combo + 0.01 && !reduce_motion {
                self.pulse = 1.0;
            }
            self.last_combo = combo;
            let elapsed = (sim_time - combo_timer).max(0.0);
            self.frac = combo_window_fraction(elapsed, COMBO_DECAY_DELAY);
        }
        if reduce_motion {
            self.pulse = 0.0;
        } else {
            self.pulse = (self.pulse - dt * 3.8).max(0.0);
        }
        self.last_time = sim_time;
    }
}

pub struct HudState {
    pub hp_anim: f32,
    pub shield_anim: f32,
    pub boost_anim: f32,
    pub boss_lag_hp: f32,
    pub last_boss_id: Option<u64>,
    pub boss_phase: i32,
    pub boss_phase_flash: f32,
    pub hp_hit_flash: f32,
    pub combo_ring: ComboRingAnim,
    pub toasts: ToastQueue,
    pub comms: AnimatedComms,
    relic_flash: [f32; 4],
    last_relic_mask: Option<u8>,
    last_player_hp: Option<i32>,
    pulse_t: f32,
}

impl Default for HudState {
    fn default() -> Self {
        Self::new()
    }
}

impl HudState {
    pub fn new() -> Self {
        Self {
            hp_anim: 1.0,
            shield_anim: 0.0,
            boost_anim: 1.0,
            boss_lag_hp: 1.0,
            last_boss_id: None,
            boss_phase: 0,
            boss_phase_flash: 0.0,
            hp_hit_flash: 0.0,
            combo_ring: ComboRingAnim::default(),
            toasts: ToastQueue::new(),
            comms: AnimatedComms::new(),
            relic_flash: [0.0; 4],
            last_relic_mask: None,
            last_player_hp: None,
            pulse_t: 0.0,
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn draw_active_buff_badges(
        &self,
        state: &SimState,
        start_x: f32,
        start_y: f32,
        s: f32,
        sdf: &mut SdfBatch,
        add: &mut SdfBatch,
        text: &mut TextBatch,
    ) -> usize {
        let mut items: Vec<(&'static str, String, f32, bool)> = Vec::new();
        for status in timed_powerup_states(&state.player) {
            if timed_active(status.until, state.time) {
                let remaining = (status.until - state.time).max(0.0);
                let rem = remaining.ceil().max(1.0) as i32;
                items.push((
                    status.kind,
                    format!("{rem}s"),
                    remaining / status.duration.max(0.1),
                    remaining <= 3.0,
                ));
            }
        }
        if state.repulsor.charges > 0 || state.time < state.repulsor.cooldown_until {
            let txt = if state.repulsor.charges > 0 {
                format!("x{}", state.repulsor.charges)
            } else {
                let cd = (state.repulsor.cooldown_until - state.time).ceil().max(1.0) as i32;
                format!("{cd}s")
            };
            let cooldown = crate::sim::config::REPULSOR_COOLDOWN_SECONDS.max(0.1);
            let cd_left = (state.repulsor.cooldown_until - state.time).max(0.0);
            let progress = if cd_left > 0.0 {
                (1.0 - cd_left / cooldown).clamp(0.0, 1.0)
            } else if state.repulsor.charges > 0 {
                1.0
            } else {
                0.0
            };
            let urgent = cd_left > 0.0 && cd_left <= 3.0;
            items.push(("repulsor", txt, progress, urgent));
        }
        if state.chain.is_active(state.time) {
            let remaining = (state.chain.until - state.time).max(0.0);
            let rem = remaining.ceil().max(1.0) as i32;
            items.push((
                "chain",
                format!("{rem}s"),
                remaining / powerup_duration_seconds("chain", None).unwrap_or(1.0).max(0.1),
                remaining <= 3.0,
            ));
        }

        let badge_w = 56.0 * s;
        let badge_h = 24.0 * s;
        let gap = 6.0 * s;
        let rows = (items.len() + 3) / 4;
        for (idx, (kind, label, progress, urgent)) in items.into_iter().enumerate() {
            let col_idx = idx % 4;
            let row_idx = idx / 4;
            let bx = start_x + col_idx as f32 * (badge_w + gap);
            let by = start_y + row_idx as f32 * (badge_h + gap);
            let col = crate::sim::config::powerup_color(kind);
            let rect = UiRect::new(bx, by, badge_w, badge_h);
            draw_panel(sdf, rect, 5.0 * s, 1.2, [12, 20, 34], 222, col, 175, 0.0);
            let icon_x = bx + 12.5 * s;
            let icon_y = by + badge_h * 0.5;
            let ring_r = 9.3 * s;
            sdf.ring(icon_x, icon_y, ring_r, ring_r, 1.0 * s, linear_rgba([30, 42, 58], 230, 1.0));
            if progress > 0.002 {
                let warning = urgent && !state.runtime.reduce_motion;
                let warning_mix = if warning { 0.45 + 0.25 * (self.pulse_t * 7.0 + idx as f32).sin().abs() } else { 0.0 };
                let ring_col = mix_rgb(col, GOLD, warning_mix);
                sdf.arc(
                    icon_x,
                    icon_y,
                    ring_r,
                    1.6 * s,
                    FRAC_PI_2 - progress.clamp(0.0, 1.0) * TAU,
                    progress.clamp(0.0, 1.0) * TAU,
                    linear_rgba(ring_col, 248, 1.0),
                );
                if warning {
                    add.ellipse_glow(icon_x, icon_y, ring_r * 1.35, ring_r * 1.35, 2.2, linear_rgba(col, 42, 1.3));
                }
            }
            crate::render::powerup_art::draw_powerup_emblem(
                kind,
                icon_x,
                icon_y,
                7.6 * s,
                col,
                1.0,
                self.pulse_t,
                sdf,
                add,
            );
            if !state.runtime.reduce_motion && progress > 0.12 {
                let sparkle_t = self.pulse_t * 1.7 + idx as f32 * 1.91;
                let sparkle_x = icon_x + sparkle_t.cos() * ring_r;
                let sparkle_y = icon_y + sparkle_t.sin() * ring_r;
                sdf.circle(sparkle_x, sparkle_y, 1.0 * s, linear_rgba([235, 250, 255], 230, 1.0));
                add.glow(sparkle_x, sparkle_y, 3.2 * s, 2.2, linear_rgba(col, 95, 1.35));
            }
            text.draw(
                label,
                FontId::Bold,
                pt_px(10.0, s, 8.5),
                bx + 25.0 * s,
                by + badge_h * 0.5,
                AlignX::Left,
                AlignY::Center,
                TEXT,
                245,
                true,
            );
        }
        rows
    }

    fn draw_run_relic_badges(
        &self,
        state: &SimState,
        start_x: f32,
        start_y: f32,
        s: f32,
        sdf: &mut SdfBatch,
        add: &mut SdfBatch,
        text: &mut TextBatch,
        fonts: &FontPack,
    ) {
        const RELICS: [(&str, &str, &str, [u8; 3]); 4] = [
            ("relic_graviton", "GRAVITON", "SALVAGE PULL", [165, 133, 255]),
            ("relic_soul_rivet", "SOUL RIVET", "+4 HULL / WAVE", [255, 112, 154]),
            ("relic_phase_shard", "PHASE SHARD", "DASH PULSE", [101, 224, 255]),
            ("relic_aegis_relay", "AEGIS RELAY", "+14 SHIELD / ULTRA", [105, 225, 245]),
        ];
        let badge_w = 122.0 * s;
        let badge_h = 32.0 * s;
        let gap = 7.0 * s;
        let mut shown = 0usize;
        for (idx, (key, label, effect, base_col)) in RELICS.iter().enumerate() {
            if !has_relic(&state.run_permanent_rewards, key) {
                continue;
            }
            let pulse = if state.runtime.reduce_motion {
                0.0
            } else {
                (self.pulse_t * 2.1 + idx as f32 * 1.7).sin() * 0.5 + 0.5
            };
            let flash = self.relic_flash[idx].clamp(0.0, 1.0);
            let edge_alpha = (145.0 + pulse * 45.0 + flash * 65.0).clamp(0.0, 255.0) as u8;
            let col = mix_rgb(*base_col, [255, 255, 255], (flash * 0.58 + pulse * 0.10).clamp(0.0, 0.7));
            let bx = start_x + shown as f32 * (badge_w + gap);
            shown += 1;
            let rect = UiRect::new(bx, start_y, badge_w, badge_h);
            draw_panel(sdf, rect, 6.0 * s, 1.35, [12, 18, 31], 225, col, edge_alpha, 1.0 * s);

            let icon_x = bx + 17.0 * s;
            let icon_y = start_y + badge_h * 0.5;
            let core = mix_rgb(col, [255, 255, 255], 0.62);
            match *key {
                "relic_graviton" => {
                    sdf.ring(icon_x, icon_y, 7.0 * s, 3.0 * s, 1.0 * s, linear_rgba(col, 235, 1.0));
                    sdf.ring(icon_x, icon_y, 3.0 * s, 7.0 * s, 0.8 * s, linear_rgba(col, 175, 1.0));
                    let orbit_t = if state.runtime.reduce_motion { 0.0 } else { self.pulse_t * 1.5 };
                    let ox = icon_x + orbit_t.cos() * 6.2 * s;
                    let oy = icon_y + orbit_t.sin() * 2.6 * s;
                    sdf.circle(icon_x, icon_y, 2.0 * s, linear_rgba(core, 250, 1.0));
                    sdf.circle(ox, oy, 1.55 * s, linear_rgba([255, 255, 255], 255, 1.0));
                    if !state.runtime.reduce_motion {
                        add.glow(ox, oy, 5.0 * s, 1.8, linear_rgba(col, 120, 1.25));
                    }
                }
                "relic_soul_rivet" => {
                    let beat = if state.runtime.reduce_motion { 1.0 } else { 1.0 + 0.10 * (self.pulse_t * 4.0).sin().max(0.0) };
                    let r = 6.2 * s * beat;
                    let shield = [
                        [icon_x, icon_y - r],
                        [icon_x + r * 0.84, icon_y - r * 0.45],
                        [icon_x + r * 0.72, icon_y + r * 0.48],
                        [icon_x, icon_y + r],
                        [icon_x - r * 0.72, icon_y + r * 0.48],
                        [icon_x - r * 0.84, icon_y - r * 0.45],
                    ];
                    sdf.polyline_closed(&shield, 1.15 * s, linear_rgba(col, 245, 1.0));
                    sdf.line(icon_x, icon_y - 3.6 * s, icon_x, icon_y + 3.6 * s, 1.0 * s, linear_rgba(core, 245, 1.0));
                    sdf.line(icon_x - 3.0 * s, icon_y, icon_x + 3.0 * s, icon_y, 1.0 * s, linear_rgba(core, 245, 1.0));
                    if flash > 0.0 && !state.runtime.reduce_motion {
                        add.glow(icon_x, icon_y, (10.0 + flash * 7.0) * s, 2.0, linear_rgba(col, (70.0 + flash * 110.0) as u8, 1.3));
                    }
                }
                "relic_aegis_relay" => {
                    let r = 7.0 * s;
                    let shield = [
                        [icon_x, icon_y - r],
                        [icon_x + r * 0.82, icon_y - r * 0.42],
                        [icon_x + r * 0.7, icon_y + r * 0.48],
                        [icon_x, icon_y + r],
                        [icon_x - r * 0.7, icon_y + r * 0.48],
                        [icon_x - r * 0.82, icon_y - r * 0.42],
                    ];
                    sdf.polyline_closed(&shield, 1.1 * s, linear_rgba(col, 245, 1.0));
                    sdf.ring(icon_x, icon_y, 3.0 * s, 3.0 * s, 1.0 * s, linear_rgba(core, 235, 1.0));
                    let orbit = if state.runtime.reduce_motion { 0.0 } else { self.pulse_t * 3.0 };
                    let spark_x = icon_x + orbit.cos() * 3.0 * s;
                    let spark_y = icon_y + orbit.sin() * 2.0 * s;
                    sdf.circle(spark_x, spark_y, 1.2 * s, linear_rgba([255, 255, 255], 255, 1.0));
                    if !state.runtime.reduce_motion {
                        add.glow(spark_x, spark_y, 4.8 * s, 1.9, linear_rgba(col, 115, 1.3));
                    }
                }
                _ => {
                    let shard = [
                        [icon_x, icon_y - 7.0 * s],
                        [icon_x + 5.4 * s, icon_y - 1.0 * s],
                        [icon_x + 2.8 * s, icon_y + 6.6 * s],
                        [icon_x - 3.7 * s, icon_y + 5.2 * s],
                        [icon_x - 6.0 * s, icon_y - 2.5 * s],
                    ];
                    sdf.polygon(&shard, linear_rgba(col, 165, 1.0));
                    sdf.polyline_closed(&shard, 1.05 * s, linear_rgba(core, 250, 1.0));
                    sdf.line(icon_x - 3.5 * s, icon_y - 2.4 * s, icon_x + 3.2 * s, icon_y + 3.7 * s, 0.9 * s, linear_rgba([255, 255, 255], 230, 1.0));
                    if !state.runtime.reduce_motion {
                        let glint = self.pulse_t * 2.0 + idx as f32;
                        let gx = icon_x + glint.sin() * 3.0 * s;
                        sdf.circle(gx, icon_y - 3.0 * s, 1.1 * s, linear_rgba([255, 255, 255], 255, 1.0));
                        add.glow(gx, icon_y - 3.0 * s, 4.4 * s, 1.8, linear_rgba(col, 110, 1.3));
                    }
                }
            }

            let title_px = pt_px(8.8, s, 7.5);
            let title = fonts.fit_text(FontId::Bold, title_px, label, 91.0 * s);
            text.draw(
                title,
                FontId::Bold,
                title_px,
                bx + 31.0 * s,
                start_y + 11.0 * s,
                AlignX::Left,
                AlignY::Center,
                TEXT,
                250,
                true,
            );
            let effect_px = pt_px(7.2, s, 6.0);
            let effect_label = fonts.fit_text(FontId::Regular, effect_px, effect, 91.0 * s);
            text.draw(
                effect_label,
                FontId::Regular,
                effect_px,
                bx + 31.0 * s,
                start_y + 22.0 * s,
                AlignX::Left,
                AlignY::Center,
                col,
                230,
                false,
            );
        }
    }

    pub fn reset(&mut self) {
        self.hp_anim = 1.0;
        self.shield_anim = 0.0;
        self.boost_anim = 1.0;
        self.boss_lag_hp = 1.0;
        self.last_boss_id = None;
        self.boss_phase = 0;
        self.boss_phase_flash = 0.0;
        self.hp_hit_flash = 0.0;
        self.combo_ring = ComboRingAnim::default();
        self.toasts.clear();
        self.comms.reset();
        self.relic_flash = [0.0; 4];
        self.last_relic_mask = None;
        self.last_player_hp = None;
        self.pulse_t = 0.0;
    }

    pub fn update(&mut self, state: &SimState, dt: f32) {
        let dt = dt.max(0.0);
        let rm = state.runtime.reduce_motion;
        if rm {
            self.pulse_t = 0.0;
        } else {
            self.pulse_t += dt;
        }
        self.toasts.tick(dt);
        self.comms.update(state, dt);

        let mut relic_mask = 0u8;
        for (idx, key) in RUN_RELIC_KEYS.iter().enumerate() {
            if has_relic(&state.run_permanent_rewards, key) {
                relic_mask |= 1 << idx;
            }
            if rm {
                self.relic_flash[idx] = 0.0;
            } else {
                self.relic_flash[idx] = (self.relic_flash[idx] - dt * 1.8).max(0.0);
            }
        }
        if let Some(previous_mask) = self.last_relic_mask {
            if !rm {
                for idx in 0..RUN_RELIC_KEYS.len() {
                    let bit = 1 << idx;
                    if relic_mask & bit != 0 && previous_mask & bit == 0 {
                        self.relic_flash[idx] = 1.0;
                    }
                }
            }
        }
        self.last_relic_mask = Some(relic_mask);

        if let Some(last_hp) = self.last_player_hp {
            if state.player.hp < last_hp && !rm {
                self.hp_hit_flash = 1.0;
            }
        }
        self.last_player_hp = Some(state.player.hp);
        self.hp_hit_flash = if rm {
            0.0
        } else {
            (self.hp_hit_flash - dt * 3.5).max(0.0)
        };

        let hp_target = (state.player.hp as f32 / state.player.max_hp.max(1) as f32).clamp(0.0, 1.0);
        let sh_target = (state.player.shield as f32 / crate::sim::config::SHIELD_MAX as f32).clamp(0.0, 1.0);
        let bs_target = (state.player.boost_energy / state.player.boost_max_energy.max(1.0)).clamp(0.0, 1.0);

        let k = if rm { 1.0 } else { (dt * 14.0).clamp(0.0, 1.0) };
        self.hp_anim += (hp_target - self.hp_anim) * k;
        self.shield_anim += (sh_target - self.shield_anim) * k;
        self.boost_anim += (bs_target - self.boost_anim) * k;

        self.combo_ring.update(
            state.score.combo,
            state.score.combo_timer,
            state.time,
            dt,
            rm,
        );

        // Track boss HP lag bar
        if let Some(boss) = state.enemies.iter().find(|e| e.behavior.starts_with("boss_") && !e.is_dead) {
            let max_hp = boss.ai.boss_max_hp.max(boss.max_hp).max(1) as f32;
            let cur_frac = (boss.hp as f32 / max_hp).clamp(0.0, 1.0);
            if self.last_boss_id != Some(boss.id) {
                self.last_boss_id = Some(boss.id);
                self.boss_lag_hp = cur_frac;
                self.boss_phase = boss.ai.phase.clamp(0, 2);
                self.boss_phase_flash = 0.0;
            } else if rm {
                self.boss_lag_hp = cur_frac;
            } else if self.boss_lag_hp > cur_frac {
                self.boss_lag_hp = (self.boss_lag_hp - dt * 0.35).max(cur_frac);
            } else {
                self.boss_lag_hp = cur_frac;
            }
            let phase = boss.ai.phase.clamp(0, 2);
            if phase > self.boss_phase && !rm {
                self.boss_phase_flash = 1.0;
            }
            self.boss_phase = phase;
        } else {
            self.last_boss_id = None;
            self.boss_phase = 0;
            self.boss_phase_flash = 0.0;
        }
        self.boss_phase_flash = (self.boss_phase_flash - dt * 1.2).max(0.0);
    }

    #[allow(clippy::too_many_arguments)]
    pub fn draw(
        &self,
        state: &SimState,
        banner: Option<&BannerNotice>,
        view_w: u32,
        view_h: u32,
        sdf: &mut SdfBatch,
        text: &mut TextBatch,
        fonts: &FontPack,
    ) {
        self.draw_with_badges(state, banner, view_w, view_h, sdf, None, text, fonts);
    }

    #[allow(clippy::too_many_arguments)]
    pub fn draw_with_badges(
        &self,
        state: &SimState,
        banner: Option<&BannerNotice>,
        view_w: u32,
        view_h: u32,
        sdf: &mut SdfBatch,
        ui_add: Option<&mut SdfBatch>,
        text: &mut TextBatch,
        fonts: &FontPack,
    ) {
        let mut scratch_add = SdfBatch::default();
        let add_batch = ui_add.unwrap_or(&mut scratch_add);
        let s = ui_scale(view_w, view_h);
        let w = view_w as f32;
        let h = view_h as f32;
        let margin = 14.0 * s;
        let contrast = state.runtime.high_contrast_hud;
        let rm = state.runtime.reduce_motion;

        // ── 1. Bottom-Left Hull / Shield / Boost Panel ──────────────────
        let panel_w = 248.0 * s;
        let panel_h = 112.0 * s;
        let panel = UiRect::new(margin, margin, panel_w, panel_h);
        draw_panel(sdf, panel, 7.0 * s, 1.6, PANEL, 206, ACCENT, 110, 3.0 * s);
        if self.hp_hit_flash > 0.01 {
            let alpha = (self.hp_hit_flash * 150.0).clamp(0.0, 150.0) as u8;
            sdf.panel_outline(
                panel.x - 1.0 * s,
                panel.y - 1.0 * s,
                panel.w + 2.0 * s,
                panel.h + 2.0 * s,
                8.0 * s,
                1.8 * s,
                linear_rgba(DANGER, alpha, 1.0),
            );
            if !rm {
                add_batch.ellipse_glow(
                    panel.x + panel.w * 0.5,
                    panel.y + panel.h * 0.5,
                    panel.w * 0.6,
                    panel.h * 0.65,
                    2.4,
                    linear_rgba(DANGER, (self.hp_hit_flash * 24.0) as u8, 1.15),
                );
            }
        }

        // ── 1b. Active Buff Vector Badges directly above Hull panel ────
        let badge_y = margin + panel_h + 10.0 * s;
        let badge_rows = self.draw_active_buff_badges(state, margin, badge_y, s, sdf, add_batch, text);
        self.draw_run_relic_badges(
            state,
            margin,
            badge_y + badge_rows as f32 * 30.0 * s,
            s,
            sdf,
            add_batch,
            text,
            fonts,
        );

        let bar_x = panel.x + 62.0 * s;
        let bar_w = panel_w - 116.0 * s;
        let bar_h = 11.0 * s;

        let draw_bar = |sdf: &mut SdfBatch,
                        text: &mut TextBatch,
                        y: f32,
                        label: &str,
                        val_text: String,
                        frac: f32,
                        fill_col: [u8; 3],
                        bg_col: [u8; 3],
                        label_col: [u8; 3]| {
            text.draw(
                label,
                FontId::Regular,
                pt_px(9.5, s, 8.0),
                panel.x + 11.0 * s,
                y + bar_h * 0.5,
                AlignX::Left,
                AlignY::Center,
                label_col,
                225,
                false,
            );
            sdf.panel(bar_x, y, bar_w, bar_h, 3.0 * s, linear_rgba(bg_col, 235, 1.0));
            if frac > 0.005 {
                sdf.panel(
                    bar_x,
                    y,
                    (bar_w * frac).max(4.0 * s),
                    bar_h,
                    3.0 * s,
                    linear_rgba(fill_col, 245, 1.0),
                );
            }
            let vx = panel.x + panel.w - 10.0 * s;
            let vy = y + bar_h * 0.5;
            if contrast {
                draw_contrast_plate(sdf, fonts, &val_text, FontId::Bold, pt_px(10.0, s, 9.0), vx, vy, AlignX::Right, s);
            }
            text.draw(
                val_text,
                FontId::Bold,
                pt_px(10.0, s, 9.0),
                vx,
                vy,
                AlignX::Right,
                AlignY::Center,
                TEXT,
                255,
                true,
            );
        };

        let hp_col = if self.hp_anim < 0.30 {
            DANGER
        } else if self.hp_anim < 0.55 {
            [235, 190, 75]
        } else {
            [110, 215, 125]
        };
        draw_bar(
            sdf,
            text,
            panel.y + panel_h - 24.0 * s,
            "HULL",
            format!("{}/{}", state.player.hp.max(0), state.player.max_hp),
            self.hp_anim,
            hp_col,
            [38, 42, 54],
            MUTED,
        );
        draw_bar(
            sdf,
            text,
            panel.y + panel_h - 46.0 * s,
            "SHIELD",
            format!("{}", state.player.shield),
            self.shield_anim,
            [84, 176, 232],
            [32, 42, 58],
            MUTED,
        );
        draw_bar(
            sdf,
            text,
            panel.y + panel_h - 68.0 * s,
            "BOOST",
            if state.has_infinite_boost() {
                "INF".to_string()
            } else {
                format!("{}%", state.player.boost_energy.round() as i32)
            },
            if state.has_infinite_boost() { 1.0 } else { self.boost_anim },
            [255, 145, 45],
            [44, 32, 18],
            [255, 185, 95],
        );

        // Weapon & Skin chips on bottom of health panel
        let wpn_name = state.player.current_weapon.name.to_ascii_uppercase();
        let wpn_col = get_weapon_color(&state.player.current_weapon.projectile_type);
        let mut wpn_label = wpn_name;
        if timed_active(state.player.weapon_until, state.time) {
            let rem = (state.player.weapon_until - state.time).ceil() as i32;
            wpn_label.push_str(&format!(" {}s", rem));
        }
        let crit_pct = ((state.total_weapon_crit_chance(state.player.current_weapon.crit_chance)) * 100.0).round() as i32;
        if crit_pct > 0 {
            wpn_label.push_str(&format!("  {}%C", crit_pct));
        }
        let chip_y = panel.y + 8.0 * s;
        let chip_h = 22.0 * s;
        let wpn_chip = UiRect::new(panel.x + 9.0 * s, chip_y, 142.0 * s, chip_h);
        draw_panel(sdf, wpn_chip, 4.0 * s, 1.2, [14, 24, 38], 220, wpn_col, 150, 0.0);
        let shot_interval = (state.player.next_shot_time - state.player.last_shot).max(0.001);
        let reload = (1.0 - (state.player.next_shot_time - state.time).max(0.0) / shot_interval)
            .clamp(0.0, 1.0);
        let reload_x = wpn_chip.x + 6.0 * s;
        let reload_y = chip_y + 2.5 * s;
        let reload_w = wpn_chip.w - 12.0 * s;
        sdf.line(reload_x, reload_y, reload_x + reload_w, reload_y,
            1.8 * s, linear_rgba([45, 62, 80], 230, 1.0));
        if reload > 0.005 {
            sdf.line(reload_x, reload_y, reload_x + reload_w * reload, reload_y,
                1.8 * s, linear_rgba(wpn_col, 245, 1.0));
        }
        sdf.circle(wpn_chip.x + 9.0 * s, chip_y + chip_h * 0.5, 3.5 * s, linear_rgba(wpn_col, 245, 1.0));
        let fitted_wpn = fonts.fit_text(FontId::Bold, pt_px(9.5, s, 8.0), &wpn_label, wpn_chip.w - 20.0 * s);
        text.draw(
            fitted_wpn,
            FontId::Bold,
            pt_px(9.5, s, 8.0),
            wpn_chip.x + 17.0 * s,
            chip_y + chip_h * 0.5,
            AlignX::Left,
            AlignY::Center,
            TEXT,
            245,
            false,
        );

        let skin_chip = UiRect::new(wpn_chip.x + wpn_chip.w + 6.0 * s, chip_y, panel.x + panel.w - (wpn_chip.x + wpn_chip.w + 15.0 * s), chip_h);
        draw_panel(sdf, skin_chip, 4.0 * s, 1.2, [14, 24, 38], 215, ACCENT, 110, 0.0);
        let skin_name = crate::sim::skins::get_skin(&state.run_skin.skin_id)
            .map(|sk| sk.name)
            .unwrap_or("Standard Pod");
        let fitted_skin = fonts.fit_text(FontId::Regular, pt_px(9.0, s, 8.0), skin_name, skin_chip.w - 10.0 * s);
        text.draw(
            fitted_skin,
            FontId::Regular,
            pt_px(9.0, s, 8.0),
            skin_chip.x + skin_chip.w * 0.5,
            chip_y + chip_h * 0.5,
            AlignX::Center,
            AlignY::Center,
            ACCENT,
            235,
            false,
        );

        // ── 2. Radial Ultra Gauge (next to Hull panel) ──────────────────
        let ultra_r = 28.0 * s;
        let ultra_cx = panel.x + panel.w + 14.0 * s + ultra_r;
        let ultra_cy = panel.y + panel_h * 0.5;
        let cd_left = (state.player.ultra_cd_until - state.time).max(0.0);
        let u_frac = ultra_cooldown_fraction(
            state.player.ultra_charges,
            cd_left,
            state.player.ultra_cd_duration,
            state.player.ultra_cd_until > 0.0,
        );
        let ultra_ready = state.player.ultra_charges > 0 && cd_left <= 0.0;
        let u_alpha = ultra_ready_alpha(ultra_ready, self.pulse_t, rm);

        sdf.circle(ultra_cx, ultra_cy, ultra_r + 4.0 * s, linear_rgba(PANEL, 210, 1.0));
        sdf.ring(ultra_cx, ultra_cy, ultra_r, ultra_r, 5.0 * s, linear_rgba([32, 42, 58], 210, 1.0));
        if u_frac > 0.005 {
            sdf.arc(
                ultra_cx,
                ultra_cy,
                ultra_r,
                5.5 * s,
                FRAC_PI_2 - u_frac * TAU,
                u_frac * TAU,
                linear_rgba(ULTRA_BEAM_COLOR, u_alpha, 1.0),
            );
            if !rm && u_frac < 0.995 {
                let head_angle = FRAC_PI_2 - u_frac * TAU;
                let hx = ultra_cx + head_angle.cos() * ultra_r;
                let hy = ultra_cy + head_angle.sin() * ultra_r;
                add_batch.circle(hx, hy, 2.4 * s, linear_rgba([255, 252, 228], 245, 1.7));
                add_batch.glow(hx, hy, 6.0 * s, 1.8, linear_rgba(ULTRA_BEAM_COLOR, 130, 1.5));
            }
        }
        crate::render::powerup_art::draw_powerup_emblem(
            "ultra",
            ultra_cx,
            ultra_cy + 1.0 * s,
            8.0 * s,
            ULTRA_BEAM_COLOR,
            if ultra_ready { 1.0 } else { 0.72 },
            self.pulse_t,
            sdf,
            add_batch,
        );
        let charge_pips = state.player.ultra_max_charges.clamp(0, 4) as usize;
        let pip_spacing = 6.2 * s;
        let pip_start_x = ultra_cx - (charge_pips.saturating_sub(1) as f32) * pip_spacing * 0.5;
        let pip_y = ultra_cy + 15.0 * s;
        for i in 0..charge_pips {
            let x = pip_start_x + i as f32 * pip_spacing;
            let filled = i < state.player.ultra_charges.max(0) as usize;
            if filled {
                sdf.circle(x, pip_y, 2.0 * s, linear_rgba(ULTRA_BEAM_COLOR, 245, 1.0));
                add_batch.circle(x, pip_y, 1.05 * s, linear_rgba([255, 255, 245], 255, 1.65));
            } else {
                sdf.ring(x, pip_y, 2.1 * s, 2.1 * s, 0.85 * s, linear_rgba(MUTED, 175, 1.0));
            }
        }
        text.draw(
            "ULTRA",
            FontId::Regular,
            pt_px(8.0, s, 7.0),
            ultra_cx,
            ultra_cy - 17.0 * s,
            AlignX::Center,
            AlignY::Center,
            ULTRA_BEAM_COLOR,
            220,
            false,
        );

        // ── 3. Top-Center Wave Chip + Status Line ───────────────────────
        let wave_w = 196.0 * s;
        let wave_h = 66.0 * s;
        let wave_rect = UiRect::new(w * 0.5 - wave_w * 0.5, h - margin - wave_h, wave_w, wave_h);
        draw_panel(sdf, wave_rect, 7.0 * s, 1.6, PANEL, 212, ACCENT, 120, 3.0 * s);

        let wave_title = format!("WAVE {}", state.wave);
        let alive_enemies = state.enemies.iter().filter(|e| !e.is_dead).count();
        let meta_txt = if is_daily_run(state.daily_date.as_deref()) {
            format!("{} LEFT  ·  DAILY", alive_enemies)
        } else {
            format!("{} LEFT  ·  {}", alive_enemies, state.difficulty.to_ascii_uppercase())
        };
        let title_y = wave_rect.y + wave_h - 16.0 * s;
        if contrast {
            draw_contrast_plate(sdf, fonts, &wave_title, FontId::Head, pt_px(18.0, s, 12.0), w * 0.5, title_y, AlignX::Center, s);
        }
        text.draw(
            wave_title,
            FontId::Head,
            pt_px(18.0, s, 12.0),
            w * 0.5,
            title_y,
            AlignX::Center,
            AlignY::Center,
            TEXT,
            255,
            true,
        );
        let fitted_meta = fonts.fit_text(FontId::Regular, pt_px(10.0, s, 8.0), &meta_txt, wave_w - 16.0 * s);
        text.draw(
            fitted_meta,
            FontId::Regular,
            pt_px(10.0, s, 8.0),
            w * 0.5,
            wave_rect.y + 8.0 * s,
            AlignX::Center,
            AlignY::Center,
            MUTED,
            235,
            false,
        );
        if state.wave_active && !state.enemy_combo_text.is_empty() {
            let mix_rows: Vec<&str> = state.enemy_combo_text.lines().take(2).collect();
            for (index, row) in mix_rows.iter().enumerate() {
                let row_y = match mix_rows.len() {
                    1 => wave_rect.y + 27.0 * s,
                    _ if index == 0 => wave_rect.y + 34.0 * s,
                    _ => wave_rect.y + 22.0 * s,
                };
                let mix_px = pt_px(8.5, s, 7.0);
                let mix_label = fonts.fit_text(FontId::Bold, mix_px, row, wave_w - 16.0 * s);
                if contrast {
                    draw_contrast_plate(sdf, fonts, &mix_label, FontId::Bold, mix_px, w * 0.5, row_y, AlignX::Center, s);
                }
                text.draw(
                    mix_label,
                    FontId::Bold,
                    mix_px,
                    w * 0.5,
                    row_y,
                    AlignX::Center,
                    AlignY::Center,
                    [145, 210, 245],
                    245,
                    true,
                );
            }
        }

        // Priority status segments directly under Wave Chip
        let max_sw = (w * 0.52).max(240.0);
        let status_slots = ((max_sw / (82.0 * s)).floor() as usize).clamp(2, 5);
        let status_txt = build_status_line(state, status_slots);
        if !status_txt.is_empty() {
            let fitted_st = fonts.fit_text(FontId::Bold, pt_px(11.0, s, 9.0), &status_txt, max_sw);
            let st_y = wave_rect.y - 16.0 * s;
            if contrast {
                draw_contrast_plate(sdf, fonts, &fitted_st, FontId::Bold, pt_px(11.0, s, 9.0), w * 0.5, st_y, AlignX::Center, s);
            }
            text.draw(
                fitted_st,
                FontId::Bold,
                pt_px(11.0, s, 9.0),
                w * 0.5,
                st_y,
                AlignX::Center,
                AlignY::Center,
                [190, 226, 255],
                245,
                true,
            );
        }

        // ── 4. Top-Right Score Panel + Combo Ring + Toasts ──────────────
        let score_w = 196.0 * s;
        let score_h = 60.0 * s;
        let score_rect = UiRect::new(w - margin - score_w, h - margin - score_h, score_w, score_h);
        draw_panel(sdf, score_rect, 7.0 * s, 1.6, PANEL, 212, GOLD, 120, 3.0 * s);

        let rx = score_rect.x + score_rect.w - 12.0 * s;
        let score_str = format_score_commas(state.score.score);
        text.draw(
            "SCORE",
            FontId::Regular,
            pt_px(9.5, s, 8.0),
            score_rect.x + 12.0 * s,
            score_rect.y + score_h - 14.0 * s,
            AlignX::Left,
            AlignY::Center,
            [214, 200, 160],
            220,
            false,
        );
        if contrast {
            draw_contrast_plate(sdf, fonts, &score_str, FontId::Head, pt_px(18.0, s, 12.0), rx, score_rect.y + score_h - 22.0 * s, AlignX::Right, s);
        }
        text.draw(
            score_str,
            FontId::Head,
            pt_px(18.0, s, 12.0),
            rx,
            score_rect.y + score_h - 22.0 * s,
            AlignX::Right,
            AlignY::Center,
            [255, 240, 180],
            255,
            true,
        );
        if state.score.combo > 1.001 {
            let combo_str = format!("x{:.2} COMBO", state.score.combo);
            text.draw(
                combo_str,
                FontId::Bold,
                pt_px(10.0, s, 8.5),
                rx,
                score_rect.y + 13.0 * s,
                AlignX::Right,
                AlignY::Center,
                [255, 200, 100],
                245,
                true,
            );
        }

        // Combo Timer Ring beside Score Panel (shrinks or hides smoothly if room < min_reach)
        if state.runtime.enable_combo_ring && state.score.combo > 1.001 && self.combo_ring.frac > 0.005 {
            let gap = 10.0 * s;
            let base_r = 17.0 * s;
            let thick = (4.0 * s).max(2.0);
            let scale_pulse = 1.0 + 0.16 * self.combo_ring.pulse;
            let reach = (base_r + thick) * scale_pulse;
            let room = ((score_rect.x - gap) - (wave_rect.x + wave_rect.w + gap)) * 0.5;
            if room >= 10.0 * s {
                let r_draw = base_r.min(room - thick).max(6.0);
                let cx = score_rect.x - gap - reach.min(room);
                let cy = score_rect.y + score_h * 0.5;
                sdf.ring(cx, cy, r_draw, r_draw, thick, linear_rgba([36, 44, 58], 185, 1.0));
                sdf.arc(
                    cx,
                    cy,
                    r_draw * scale_pulse,
                    thick,
                    FRAC_PI_2 - self.combo_ring.frac * TAU,
                    self.combo_ring.frac * TAU,
                    linear_rgba([255, 200, 90], 245, 1.0),
                );
            }
        }

        // Achievement / Daily Toast under Score panel
        if let Some(toast) = &self.toasts.current {
            let ta = self.toasts.alpha(rm);
            if ta > 0.02 {
                let tw = score_w.max(220.0 * s);
                let th = 48.0 * s;
                let tx = w - margin - tw;
                let ty = score_rect.y - 10.0 * s - th;
                let trect = UiRect::new(tx, ty, tw, th);
                draw_panel(
                    sdf,
                    trect,
                    6.0 * s,
                    1.6,
                    [12, 22, 36],
                    (230.0 * ta) as u8,
                    GOLD,
                    (210.0 * ta) as u8,
                    2.5 * s,
                );
                text.draw_hdr(
                    fonts.fit_text(FontId::Head, pt_px(10.5, s, 8.5), &toast.title, tw - 18.0 * s),
                    FontId::Head,
                    pt_px(10.5, s, 8.5),
                    tx + 10.0 * s,
                    ty + th - 15.0 * s,
                    AlignX::Left,
                    AlignY::Center,
                    GOLD,
                    ta,
                    true,
                );
                text.draw_hdr(
                    fonts.fit_text(FontId::Regular, pt_px(9.5, s, 8.0), &toast.subtitle, tw - 18.0 * s),
                    FontId::Regular,
                    pt_px(9.5, s, 8.0),
                    tx + 10.0 * s,
                    ty + 14.0 * s,
                    AlignX::Left,
                    AlignY::Center,
                    TEXT,
                    ta * 0.9,
                    false,
                );
            }
        }

        // ── 5. Boss Health Bar (Bottom-Center above Player/Lower Arena) ──
        if let Some(boss) = state.enemies.iter().find(|e| e.behavior.starts_with("boss_") && !e.is_dead) {
            let frame_right_limit = w - margin - 10.0 * s;
            let frame_left_min = ultra_cx + ultra_r + 14.0 * s;
            let max_boss_w = (frame_right_limit - frame_left_min - 10.0 * s).max(96.0 * s);
            let bw = (380.0 * s).min(w * 0.48).min(max_boss_w);
            let bh = 16.0 * s;
            let max_bx = frame_right_limit - bw - 10.0 * s;
            let bx = (w * 0.5 - bw * 0.5)
                .max(frame_left_min)
                .min(max_bx.max(frame_left_min));
            let by = margin + 12.0 * s;
            let max_hp = boss.ai.boss_max_hp.max(boss.max_hp).max(1);
            let hp_frac = (boss.hp as f32 / max_hp as f32).clamp(0.0, 1.0);

            let frame_rect = UiRect::new(bx - 10.0 * s, by - 8.0 * s, bw + 20.0 * s, bh + 32.0 * s);
            let b_edge = if boss.ai.rage { [255, 85, 70] } else { [215, 110, 165] };
            draw_panel(sdf, frame_rect, 6.0 * s, 1.6, PANEL, 210, b_edge, 175, 3.0 * s);

            let compact = bw < 270.0 * s;
            let mut title = boss_title(&boss.behavior);
            if boss.ai.rage && !compact {
                title.push_str("  [ENRAGED]");
            }
            let title_px = pt_px(10.5, s, 8.5);
            let title_width = if compact { bw - 90.0 * s } else { bw - 144.0 * s };
            text.draw(
                fonts.fit_text(FontId::Head, title_px, &title, title_width.max(48.0 * s)),
                FontId::Head,
                title_px,
                bx + bw * 0.5,
                by + bh + 12.0 * s,
                AlignX::Center,
                AlignY::Center,
                if boss.ai.rage { [255, 130, 100] } else { [255, 215, 235] },
                250,
                true,
            );
            let phase_label = match (compact, self.boss_phase) {
                (true, 0) => "PHASE I",
                (true, 1) => "PHASE II",
                (true, _) => "PHASE III",
                (false, 0) => "PHASE I / III",
                (false, 1) => "PHASE II / III",
                (false, _) => "PHASE III / III",
            };
            text.draw(
                phase_label,
                FontId::Bold,
                pt_px(8.0, s, 7.0),
                frame_rect.x + 8.0 * s,
                by + bh + 12.0 * s,
                AlignX::Left,
                AlignY::Center,
                if self.boss_phase >= 2 { [255, 160, 125] } else { [208, 176, 202] },
                225,
                false,
            );
            if !compact {
                let (persona_label, persona_color) = match boss.ai.persona {
                    BossPersona::Aggressive => ("AGGRESSIVE", [255, 150, 125]),
                    BossPersona::Cautious => ("CAUTIOUS", [135, 205, 255]),
                    BossPersona::Trickster => ("TRICKSTER", [210, 155, 255]),
                };
                text.draw(
                    persona_label,
                    FontId::Bold,
                    pt_px(7.5, s, 6.5),
                    frame_rect.x + frame_rect.w - 8.0 * s,
                    by + bh + 12.0 * s,
                    AlignX::Right,
                    AlignY::Center,
                    persona_color,
                    225,
                    false,
                );
            }
            if bw >= 170.0 * s {
                if let Some(action_label) = boss_action_label(boss) {
                    let row_y = by + bh + 12.0 * s;
                    let cue_w = if compact { 78.0 * s } else { 102.0 * s };
                    let cue_h = 14.0 * s;
                    let cue_x = if compact {
                        frame_rect.x + frame_rect.w - cue_w - 7.0 * s
                    } else {
                        frame_rect.x + (frame_rect.w - cue_w) * 0.52
                    };
                    let cue_col = if boss.ai.rage { [255, 105, 85] } else { [255, 190, 118] };
                    let pulse = if rm {
                        1.0
                    } else {
                        0.78 + 0.22 * (self.pulse_t * 5.0).sin().abs()
                    };
                    let cue_rect = UiRect::new(cue_x, row_y - cue_h * 0.5, cue_w, cue_h);
                    draw_panel(
                        sdf,
                        cue_rect,
                        4.0 * s,
                        1.1,
                        [27, 18, 22],
                        (184.0 * pulse) as u8,
                        cue_col,
                        (145.0 * pulse) as u8,
                        0.8 * s,
                    );
                    let cue_px = pt_px(7.8, s, 6.5);
                    text.draw(
                        fonts.fit_text(FontId::Bold, cue_px, action_label, cue_w - 8.0 * s),
                        FontId::Bold,
                        cue_px,
                        cue_x + cue_w * 0.5,
                        row_y,
                        AlignX::Center,
                        AlignY::Center,
                        cue_col,
                        (240.0 * pulse) as u8,
                        true,
                    );
                }
            }
            sdf.panel(bx, by, bw, bh, 4.0 * s, linear_rgba([32, 18, 28], 240, 1.0));
            if self.boss_lag_hp > hp_frac {
                sdf.panel(bx, by, bw * self.boss_lag_hp, bh, 4.0 * s, linear_rgba([255, 225, 210], 170, 1.0));
            }
            if hp_frac > 0.002 {
                let fill_col = if boss.ai.rage { [255, 70, 60] } else { [230, 75, 135] };
                sdf.panel(bx, by, (bw * hp_frac).max(4.0 * s), bh, 4.0 * s, linear_rgba(fill_col, 250, 1.0));
                sdf.line(bx + 2.0 * s, by + bh - 2.0 * s, bx + (bw * hp_frac).max(4.0 * s) - 2.0 * s, by + bh - 2.0 * s, 1.0 * s, linear_rgba([255, 220, 232], 150, 1.0));
                if !rm && hp_frac > 0.02 {
                    let edge_x = bx + bw * hp_frac;
                    let glint = 0.45 + 0.55 * (self.pulse_t * 3.2).sin().abs();
                    add_batch.ellipse_glow(edge_x, by + bh * 0.5, 10.0 * s, 10.0 * s, 2.0, linear_rgba(fill_col, (100.0 * glint) as u8, 1.35));
                }
            }
            // Tick marks divide the health bar into the three combat phases.
            for phase_mark in 1..3 {
                let x = bx + bw * (phase_mark as f32 / 3.0);
                sdf.line(x, by + 1.5 * s, x, by + bh - 1.5 * s, 1.6 * s, linear_rgba([18, 16, 27], 235, 1.0));
            }
            let phase_flash = if rm { 0.0 } else { self.boss_phase_flash };
            if phase_flash > 0.01 {
                let pulse = 0.55 + 0.45 * (self.pulse_t * 8.0).sin().abs();
                let alpha = (phase_flash * pulse * 180.0).clamp(0.0, 180.0) as u8;
                sdf.panel_outline(
                    frame_rect.x - 1.5 * s,
                    frame_rect.y - 1.5 * s,
                    frame_rect.w + 3.0 * s,
                    frame_rect.h + 3.0 * s,
                    7.0 * s,
                    2.0 * s,
                    linear_rgba([255, 228, 165], alpha, 1.15),
                );
                add_batch.ellipse_glow(w * 0.5, by + bh * 0.5, bw * 0.45, 20.0 * s, 2.6, linear_rgba([255, 182, 125], (phase_flash * 34.0) as u8, 1.25));
            }
        }

        // ── 6. Center-Screen Animated Wave / Event / Boss Banner ────────
        if let Some(ban) = banner {
            let p = (ban.elapsed / ban.duration.max(0.1)).clamp(0.0, 1.0);
            let alpha = if p < 0.16 {
                p / 0.16
            } else if p > 0.80 {
                (1.0 - p) / 0.20
            } else {
                1.0
            }
            .clamp(0.0, 1.0);
            if alpha > 0.02 {
                let bw = (420.0 * s).min(w - 40.0);
                let bh = if ban.subtitle.is_empty() { 58.0 * s } else { 78.0 * s };
                let bx = w * 0.5 - bw * 0.5;
                let by = h * 0.72 - bh * 0.5;
                let brect = UiRect::new(bx, by, bw, bh);
                draw_panel(
                    sdf,
                    brect,
                    8.0 * s,
                    2.0,
                    mix_rgb(PANEL, ban.color, 0.12),
                    (222.0 * alpha) as u8,
                    ban.color,
                    (210.0 * alpha) as u8,
                    3.0 * s,
                );
                let title_y = if ban.subtitle.is_empty() {
                    by + bh * 0.5
                } else {
                    by + bh * 0.63
                };
                text.draw_hdr(
                    ban.title.as_str(),
                    FontId::Head,
                    pt_px(22.0, s, 14.0),
                    w * 0.5,
                    title_y,
                    AlignX::Center,
                    AlignY::Center,
                    mix_rgb(ban.color, [255, 255, 255], 0.35),
                    alpha,
                    true,
                );
                if !ban.subtitle.is_empty() {
                    text.draw_hdr(
                        ban.subtitle.as_str(),
                        FontId::Bold,
                        pt_px(12.0, s, 9.5),
                        w * 0.5,
                        by + bh * 0.28,
                        AlignX::Center,
                        AlignY::Center,
                        TEXT,
                        alpha * 0.92,
                        true,
                    );
                }
            }
        }
        self.comms.draw(
            rm,
            self.pulse_t,
            view_w,
            view_h,
            sdf,
            add_batch,
            text,
            fonts,
        );
    }
}

fn boss_action_label(boss: &crate::sim::enemy::Enemy) -> Option<&'static str> {
    match (boss.behavior.as_str(), boss.ai.sub_state) {
        ("boss_womb_core", EnemySubState::WombPulseTelegraph) => Some("PULSE WARNING"),
        ("boss_thunder", EnemySubState::ThunderTeleportOut) => Some("PHASING OUT"),
        ("boss_thunder", EnemySubState::ThunderTeleportIn) => Some("STORM ARRIVAL"),
        ("boss_thunder", EnemySubState::ThunderWindup) => Some("RING CHARGE"),
        ("boss_thunder", EnemySubState::ThunderAttack) => Some("LIGHTNING STRIKE"),
        ("boss_laser", EnemySubState::LaserCharge) => Some("BEAM LOCK"),
        ("boss_laser", EnemySubState::LaserAttack) => Some("BEAM SWEEP"),
        ("boss_brute", EnemySubState::BruteTelegraph) => Some("CHARGE WINDUP"),
        ("boss_brute", EnemySubState::BruteCharge) => Some("CHARGING"),
        ("boss_brute", EnemySubState::BruteStun) => Some("STUNNED"),
        ("boss_eclipse_archon", EnemySubState::EclipseCharge) => Some("ORBIT CHARGE"),
        ("boss_eclipse_archon", EnemySubState::EclipseBurst) => Some("NOVA BURST"),
        ("boss_eclipse_archon", EnemySubState::EclipseEscape) => Some("PHASE SHIFT"),
        ("boss_swarmqueen", EnemySubState::QueenBroodTelegraph) => Some("BROOD PODS"),
        ("boss_swarmqueen", EnemySubState::QueenSwarmTelegraph) => Some("SWARM BURST"),
        ("boss_swarmqueen", EnemySubState::QueenVolleyTelegraph) => Some("PLASMA FAN"),
        ("boss_trapmaster", EnemySubState::TrapmasterTelegraph) => Some("SPIKE ARRAY"),
        ("boss_abyss_gaze", EnemySubState::AbyssTelegraph) => Some("VOID SALVO"),
        _ if boss.attack_cd > 0.0 && boss.attack_cd <= 0.5 => match boss.behavior.as_str() {
            "boss_trapmaster" => Some("TRAP ARRAY"),
            "boss_abyss_gaze" => Some("VOID SALVO"),
            "boss_womb_core" => Some("PULSE WARNING"),
            _ => None,
        },
        _ => None,
    }
}

#[allow(clippy::too_many_arguments)]
fn draw_contrast_plate(
    sdf: &mut SdfBatch,
    fonts: &FontPack,
    txt: &str,
    font: FontId,
    px: f32,
    x: f32,
    y: f32,
    align_x: AlignX,
    s: f32,
) {
    if txt.trim().is_empty() {
        return;
    }
    let (tw, th) = fonts.measure(font, px, txt);
    let pad_x = 5.0 * s;
    let pad_y = 2.0 * s;
    let left = match align_x {
        AlignX::Left => x,
        AlignX::Center => x - tw * 0.5,
        AlignX::Right => x - tw,
    };
    sdf.panel(
        left - pad_x,
        y - th * 0.45 - pad_y,
        tw + pad_x * 2.0,
        th * 0.85 + pad_y * 2.0,
        3.0 * s,
        linear_rgba([6, 10, 18], 210, 1.0),
    );
}

fn build_status_line(state: &SimState, max_segments: usize) -> String {
    let mut segs: Vec<String> = Vec::new();
    if is_daily_run(state.daily_date.as_deref()) {
        let names = mutator_names(&state.mutators).join("/");
        segs.push(format!(
            "DAILY {names} {}",
            format_score_mult(combined_score_multiplier(&state.mutators))
        ));
    } else if !state.mutators.is_empty() {
        let names = mutator_names(&state.mutators).join("/");
        segs.push(format!(
            "MOD {names} {}",
            format_score_mult(combined_score_multiplier(&state.mutators))
        ));
    }
    let build = format_perm_hud(&state.run_permanent_rewards);
    if !build.is_empty() {
        segs.push(build);
    }

    let mut transient: Vec<String> = Vec::new();
    if let Some(ev) = &state.arena_event {
        let st = ev.status_text();
        if !st.is_empty() {
            transient.push(st);
        }
    }
    if timed_active(state.player.time_slow_until, state.time) {
        transient.push(format!("Slow {}s", (state.player.time_slow_until - state.time).ceil() as i32));
    }
    if timed_active(state.player.magnet_until, state.time) {
        transient.push(format!("Magnet {}s", (state.player.magnet_until - state.time).ceil() as i32));
    }
    if state.chain.is_active(state.time) {
        transient.push(format!("Chain {}s", (state.chain.until - state.time).ceil() as i32));
    }
    if timed_active(state.player.ricochet_until, state.time) {
        transient.push(format!("Ricochet {}s", (state.player.ricochet_until - state.time).ceil() as i32));
    }
    if timed_active(state.player.homing_until, state.time) {
        transient.push(format!("Homing {}s", (state.player.homing_until - state.time).ceil() as i32));
    }
    let rep = state.repulsor.format_hud(state.time);
    if !rep.is_empty() {
        transient.push(rep);
    }
    if timed_active(state.player.laser_until, state.time) {
        transient.push(format!("Laser {}s", (state.player.laser_until - state.time).ceil() as i32));
    }
    if timed_active(state.player.vortex_until, state.time) {
        transient.push(format!("Vortex {}s", (state.player.vortex_until - state.time).ceil() as i32));
    }
    if state.drone.active && timed_active(state.player.drone_until, state.time) {
        transient.push(format!("Drone {}s", (state.player.drone_until - state.time).ceil() as i32));
    }
    if !state.active_temp_rewards.is_empty() {
        let boons = format_temp_hud(&state.active_temp_rewards);
        if !boons.is_empty() {
            transient.push(boons);
        }
    }
    if !state.auto_shoot {
        transient.push("AUTO-FIRE OFF".to_string());
    }

    let slots = max_segments.max(1).saturating_sub(segs.len());
    let has_overflow = transient.len() > slots;
    let visible_transient = if has_overflow {
        slots.saturating_sub(1)
    } else {
        slots
    };
    segs.extend(transient.iter().take(visible_transient).cloned());
    let hidden = transient.len().saturating_sub(visible_transient);
    if hidden > 0 {
        let summary = format!("+{hidden} ACTIVE");
        if segs.len() < max_segments.max(1) {
            segs.push(summary);
        } else if let Some(last) = segs.last_mut() {
            last.push_str(" · ");
            last.push_str(&summary);
        }
    }
    segs.join("  ·  ")
}

pub fn format_score_commas(val: i32) -> String {
    let s = val.abs().to_string();
    let mut out = String::new();
    for (idx, ch) in s.chars().rev().enumerate() {
        if idx > 0 && idx % 3 == 0 {
            out.push(',');
        }
        out.push(ch);
    }
    if val < 0 {
        out.push('-');
    }
    out.chars().rev().collect()
}
