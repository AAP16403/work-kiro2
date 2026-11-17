use std::f32::consts::TAU;

use crate::input::glyphs::{self, InputDevice};
use crate::render::sdf::{linear_rgba, linear_rgba_f, mix_rgb, SdfBatch};
use crate::render::text::{AlignX, AlignY, FontId, FontPack, TextBatch};
use crate::save::progress::DailyEntry;
use crate::save::scores::SubmitOutcome;
use crate::save::settings::{UserSettings, GAMEPAD_DEADZONE_MAX, GAMEPAD_DEADZONE_MIN};
use crate::sim::achievements::ACHIEVEMENTS;
use crate::sim::config::{
    enemy_color, elite_affix_color, powerup_color, ARENA_MARGIN_MAX, ARENA_MARGIN_MIN, BOSS_RAGE_COOLDOWN_MULT,
    BOSS_RAGE_EXTRA_PROJECTILES, BOSS_RAGE_HP_FRAC, ELITE_REFLECT_COOLDOWN, ELITE_SPLIT_COUNT,
    ELITE_SPLIT_HP_FRAC, GAME_OVER_REVEAL_S, ELITE_MENDER_HEAL, ELITE_MENDER_INTERVAL,
    ELITE_MENDER_RADIUS, ELITE_WARD_DAMAGE_MULT, ELITE_WARD_RADIUS, ELITE_SHIELDED_HP_FRAC,
    ELITE_SWIFT_SPEED_MULT, ELITE_VOLATILE_BLAST_DAMAGE, ELITE_VOLATILE_BLAST_RADIUS,
};
use crate::sim::daily::{daily_seed, DailyResult, DAILY_DIFFICULTY, DAILY_MAP_TYPE};
use crate::sim::mutators::{
    combined_score_multiplier, format_score_mult, mutator_by_id, mutator_names, toggle_selection,
    MUTATORS,
};
use crate::sim::rpg::{
    category_color, reward_category, ActiveTempReward, PermRewardDef, TempRewardDef,
};
use crate::sim::skins::SKINS;
use crate::ui::hud::format_score_commas;
use crate::ui::theme::{
    draw_button, draw_chip, draw_panel, draw_slider, pt_px, ui_scale, ButtonStyle, UiRect, ACCENT,
    BACKGROUND, GOLD, MUTED, PANEL, SUCCESS, TEXT,
};

// ---------------------------------------------------------------------------
// Screen Fade Transition
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AppScreen {
    Menu,
    Settings,
    Guide,
    Hangar,
    Playing,
    Paused,
    BossReward,
    GameOver,
}

#[derive(Debug, Clone)]
pub struct ScreenFade {
    pub active: bool,
    pub alpha: f32,
    phase_out: bool,
    duration: f32,
    elapsed: f32,
    pending_target: Option<AppScreen>,
    start_daily: bool,
}

impl Default for ScreenFade {
    fn default() -> Self {
        Self::new()
    }
}

impl ScreenFade {
    pub fn new() -> Self {
        Self {
            active: false,
            alpha: 0.0,
            phase_out: true,
            duration: 0.28,
            elapsed: 0.0,
            pending_target: None,
            start_daily: false,
        }
    }

    pub fn trigger(&mut self, target: AppScreen, start_daily: bool, reduce_motion: bool) -> Option<(AppScreen, bool)> {
        if reduce_motion {
            self.active = false;
            self.alpha = 0.0;
            self.pending_target = None;
            return Some((target, start_daily));
        }
        self.active = true;
        self.phase_out = true;
        self.alpha = 0.0;
        self.elapsed = 0.0;
        self.duration = 0.30;
        self.pending_target = Some(target);
        self.start_daily = start_daily;
        None
    }

    /// Returns `Some((target_screen, start_daily))` at the exact peak darkness frame.
    pub fn update(&mut self, dt: f32) -> Option<(AppScreen, bool)> {
        if !self.active {
            return None;
        }
        let half = (self.duration * 0.5).max(0.05);
        self.elapsed += dt;
        let ease = |t: f32| {
            let t = t.clamp(0.0, 1.0);
            t * t * (3.0 - 2.0 * t)
        };
        if self.phase_out {
            self.alpha = ease(self.elapsed / half);
            if self.elapsed >= half {
                self.phase_out = false;
                self.elapsed = 0.0;
                self.alpha = 1.0;
                return self.pending_target.take().map(|t| (t, self.start_daily));
            }
        } else {
            self.alpha = 1.0 - ease(self.elapsed / half);
            if self.elapsed >= half {
                self.active = false;
                self.alpha = 0.0;
            }
        }
        None
    }
}

// ---------------------------------------------------------------------------
// Main Menu Screen
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MenuAction {
    None,
    Play,
    PlayDaily,
    OpenHangar,
    OpenSettings,
    OpenGuide,
    Quit,
    MutatorsChanged(Vec<String>),
}

pub struct MenuScreen {
    pub input_device: InputDevice,
    buttons: Vec<ButtonStyle>,
    spotlight_entries: Vec<GuideEntry>,
    focus_idx: usize,
    focused_mutator: Option<usize>,
    hovered_mutator: Option<usize>,
    hovered_pos: [f32; 2],
    has_pointer: bool,
    reduce_motion: bool,
    t: f32,
    intro_t: f32,
}

impl Default for MenuScreen {
    fn default() -> Self {
        Self::new()
    }
}

impl MenuScreen {
    pub fn new() -> Self {
        Self {
            input_device: InputDevice::default(),
            spotlight_entries: GuideScreen::enemy_entries(false)
                .into_iter()
                .filter(|entry| is_guide_enemy_model(entry.key))
                .collect(),
            buttons: vec![
                ButtonStyle::new("Play", [55, 130, 195], [95, 185, 255]),
                ButtonStyle::new("Daily Challenge", [95, 95, 180], [150, 150, 255]),
                ButtonStyle::new("Hangar", [70, 125, 160], [115, 185, 235]),
                ButtonStyle::new("Settings", [70, 110, 150], [115, 165, 220]),
                ButtonStyle::new("Guide", [65, 115, 145], [110, 170, 210]),
                ButtonStyle::new("Quit", [135, 65, 80], [205, 95, 115]),
            ],
            focus_idx: 0,
            focused_mutator: None,
            hovered_mutator: None,
            hovered_pos: [0.0, 0.0],
            has_pointer: false,
            reduce_motion: false,
            t: 0.0,
            intro_t: 0.0,
        }
    }

    pub fn replay_intro(&mut self, reduce_motion: bool) {
        self.reduce_motion = reduce_motion;
        self.intro_t = if reduce_motion { 1.0 } else { 0.0 };
    }

    pub fn update(&mut self, dt: f32, view_w: u32, view_h: u32, reduce_motion: bool) {
        self.reduce_motion = reduce_motion;
        if !reduce_motion {
            self.t += dt;
            self.intro_t = (self.intro_t + dt).min(1.0);
        }
        let layout = self.layout(view_w, view_h);
        let [mx, my] = self.hovered_pos;
        for (i, b) in self.buttons.iter_mut().enumerate() {
            let rect = menu_button_entry_rect(
                layout.btn_rects[i],
                layout.s,
                self.intro_t,
                i,
                self.reduce_motion,
            );
            let hov = self.has_pointer && rect.contains(mx, my);
            b.focused = !self.has_pointer
                && self.focused_mutator.is_none()
                && i == self.focus_idx;
            b.update_hover(hov, dt, reduce_motion);
        }
        self.hovered_mutator = if self.has_pointer {
            layout.mut_rects.iter().enumerate().position(|(i, r)| {
                menu_mutator_entry_rect(
                    *r,
                    layout.s,
                    self.intro_t,
                    i,
                    self.reduce_motion,
                )
                .contains(mx, my)
            })
        } else {
            None
        };
    }

    pub fn on_mouse_move(&mut self, x: f32, y: f32) {
        self.hovered_pos = [x, y];
        self.has_pointer = true;
    }

    pub fn on_mouse_press(
        &mut self,
        x: f32,
        y: f32,
        view_w: u32,
        view_h: u32,
        selected_mutators: &[String],
    ) -> MenuAction {
        self.hovered_pos = [x, y];
        self.has_pointer = true;
        let layout = self.layout(view_w, view_h);
        for (i, rect) in layout.btn_rects.iter().enumerate() {
            let hit_rect = menu_button_entry_rect(
                *rect,
                layout.s,
                self.intro_t,
                i,
                self.reduce_motion,
            );
            if hit_rect.contains(x, y) {
                self.focused_mutator = None;
                self.focus_idx = i;
                return Self::action_for_btn(i);
            }
        }
        for (i, rect) in layout.mut_rects.iter().enumerate() {
            let hit_rect = menu_mutator_entry_rect(
                *rect,
                layout.s,
                self.intro_t,
                i,
                self.reduce_motion,
            );
            if hit_rect.contains(x, y) {
                if let Some(m) = MUTATORS.get(i) {
                    self.focused_mutator = Some(i);
                    let next = toggle_selection(selected_mutators, m.id);
                    return MenuAction::MutatorsChanged(next);
                }
            }
        }
        MenuAction::None
    }

    pub fn on_key_nav(
        &mut self,
        delta: isize,
        horizontal: isize,
        activate: bool,
        selected_mutators: &[String],
    ) -> MenuAction {
        if delta != 0 || horizontal != 0 || activate {
            self.has_pointer = false;
            self.hovered_mutator = None;
        }
        if let Some(mutator_idx) = self.focused_mutator {
            if horizontal != 0 && !MUTATORS.is_empty() {
                let n = MUTATORS.len() as isize;
                self.focused_mutator = Some((mutator_idx as isize + horizontal).rem_euclid(n) as usize);
            } else if delta < 0 {
                self.focused_mutator = None;
                self.focus_idx = self.buttons.len().saturating_sub(1);
            } else if delta > 0 {
                self.focused_mutator = None;
                self.focus_idx = 0;
            }
            if activate {
                if let Some(m) = self.focused_mutator.and_then(|idx| MUTATORS.get(idx)) {
                    return MenuAction::MutatorsChanged(toggle_selection(selected_mutators, m.id));
                }
            }
            return MenuAction::None;
        }

        if delta != 0 && !self.buttons.is_empty() {
            let n = self.buttons.len() as isize;
            if delta > 0
                && self.focus_idx + 1 == self.buttons.len()
                && !MUTATORS.is_empty()
            {
                self.focused_mutator = Some(0);
            } else {
                self.focus_idx = ((self.focus_idx as isize) + delta).rem_euclid(n) as usize;
            }
        }
        if activate && self.focused_mutator.is_none() {
            return Self::action_for_btn(self.focus_idx);
        }
        MenuAction::None
    }

    fn action_for_btn(idx: usize) -> MenuAction {
        match idx {
            0 => MenuAction::Play,
            1 => MenuAction::PlayDaily,
            2 => MenuAction::OpenHangar,
            3 => MenuAction::OpenSettings,
            4 => MenuAction::OpenGuide,
            5 => MenuAction::Quit,
            _ => MenuAction::None,
        }
    }

    fn layout(&self, view_w: u32, view_h: u32) -> MenuLayout {
        let w = view_w as f32;
        let h = view_h as f32;
        let s = ui_scale(view_w, view_h).min((h / 620.0).clamp(0.4, 1.35));
        let cx = w * 0.5;
        let title_y = (h * 0.855).min(h - 68.0 * s);
        let btn_w = (230.0 * s).min(w * 0.44);
        let btn_h = 44.0 * s;
        let gap = 10.0 * s;
        let top_btn_y = title_y - 102.0 * s;

        let mut btn_rects = Vec::with_capacity(self.buttons.len());
        for i in 0..self.buttons.len() {
            let y = top_btn_y - (i as f32) * (btn_h + gap);
            btn_rects.push(UiRect::new(cx - btn_w * 0.5, y, btn_w, btn_h));
        }

        let mut_y = top_btn_y - (self.buttons.len() as f32) * (btn_h + gap) - 34.0 * s;
        let chip_h = 28.0 * s;
        let chip_gap = 8.0 * s;
        let mutator_count = MUTATORS.len().max(1) as f32;
        let max_chip_w = ((w * 0.88 - chip_gap * (mutator_count - 1.0)) / mutator_count)
            .max(28.0 * s);
        let chip_w = (122.0 * s).min(max_chip_w);
        let total_w = chip_w * (MUTATORS.len() as f32) + chip_gap * (MUTATORS.len().saturating_sub(1) as f32);
        let start_x = cx - total_w * 0.5;
        let mut mut_rects = Vec::with_capacity(MUTATORS.len());
        for i in 0..MUTATORS.len() {
            mut_rects.push(UiRect::new(start_x + (i as f32) * (chip_w + chip_gap), mut_y, chip_w, chip_h));
        }

        MenuLayout {
            s,
            cx,
            title_y,
            btn_rects,
            mut_rects,
            mut_y,
            spotlight_rect: if w >= 820.0 && h >= 500.0 {
                Some(UiRect::new(
                    w - 304.0 * s,
                    (h - 178.0 * s) * 0.5,
                    282.0 * s,
                    178.0 * s,
                ))
            } else {
                None
            },
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub fn draw(
        &self,
        ui_alpha: &mut SdfBatch,
        ui_add: &mut SdfBatch,
        ui_text: &mut TextBatch,
        fonts: &FontPack,
        view_w: u32,
        view_h: u32,
        best_score: i32,
        difficulty: &str,
        daily_date: &str,
        daily_mut_id: &str,
        daily_entry: Option<&DailyEntry>,
        selected_mutators: &[String],
        reduce_motion: bool,
    ) {
        let l = self.layout(view_w, view_h);
        let s = l.s;
        let w = view_w as f32;
        let h = view_h as f32;

        // Give the action stack a clear home, with enough contrast to stay readable over
        // the moving starfield while leaving the daily challenge and modifier controls open.
        if let (Some(first), Some(last)) = (l.btn_rects.first(), l.btn_rects.last()) {
            let bottom = last.y - 12.0 * s;
            let top = first.y + first.h + 12.0 * s;
            draw_panel(
                ui_alpha,
                UiRect::new(l.cx - 158.0 * s, bottom, 316.0 * s, top - bottom),
                18.0 * s,
                1.2 * s,
                [8, 17, 30],
                170,
                [74, 139, 205],
                86,
                9.0 * s,
            );
            ui_add.line(
                l.cx - 157.0 * s,
                bottom + 18.0 * s,
                l.cx - 157.0 * s,
                top - 18.0 * s,
                2.0 * s,
                linear_rgba([90, 190, 255], 108, 1.35),
            );
        }

        // The main menu previews the same 3D hulls used by the field guide.
        if let Some(brief) = l.spotlight_rect {
            draw_panel(
                ui_alpha,
                brief,
                14.0 * s,
                1.1 * s,
                [8, 18, 30],
                190,
                [80, 160, 210],
                78,
                8.0 * s,
            );
            let spotlight = if self.spotlight_entries.is_empty() {
                None
            } else {
                let index = if reduce_motion {
                    0
                } else {
                    (self.t.max(0.0) / 6.0).floor() as usize % self.spotlight_entries.len()
                };
                self.spotlight_entries.get(index)
            };
            ui_text.draw(
                "ENEMY SPOTLIGHT",
                FontId::Bold,
                pt_px(11.5, s, 8.5),
                brief.x + 15.0 * s,
                brief.y + brief.h - 17.0 * s,
                AlignX::Left,
                AlignY::Center,
                ACCENT,
                245,
                true,
            );
            if let Some(entry) = spotlight {
                let model_center = [brief.x + 55.0 * s, brief.y + 91.0 * s];
                ui_alpha.circle(
                    model_center[0],
                    model_center[1],
                    38.0 * s,
                    linear_rgba([9, 20, 34], 240, 1.0),
                );
                ui_add.ring(
                    model_center[0],
                    model_center[1],
                    34.0 * s,
                    27.0 * s,
                    1.6 * s,
                    linear_rgba(entry.accent, 145, 1.25),
                );
                let heading = -std::f32::consts::FRAC_PI_4
                    + if reduce_motion { 0.0 } else { (self.t * 0.32).sin() * 0.22 };
                let facing = crate::sim::math::Vec2::new(heading.cos(), heading.sin());
                let model_scale = if is_guide_boss_model(entry.key) {
                    crate::render::models3d::boss_model_preview_fit_scale(entry.key, 32.0 * s)
                } else {
                    crate::render::models3d::enemy_model_preview_fit_scale(entry.key, 32.0 * s)
                };
                if let Some(model_scale) = model_scale {
                    let _model_drawn = draw_guide_model_preview(
                        entry,
                        ui_alpha,
                        ui_add,
                        [model_center[0], model_center[1] - 1.5 * s],
                        facing,
                        model_scale,
                        self.t,
                        reduce_motion,
                    );
                }
                let text_x = brief.x + 104.0 * s;
                let text_w = brief.w - 118.0 * s;
                let name_px = pt_px(13.0, s, 9.5);
                ui_text.draw(
                    fit_phrase_to_width(&entry.name, name_px, text_w, true),
                    FontId::Bold,
                    name_px,
                    text_x,
                    brief.y + brief.h - 51.0 * s,
                    AlignX::Left,
                    AlignY::Top,
                    TEXT,
                    250,
                    true,
                );
                let brief_px = pt_px(10.0, s, 8.0);
                ui_text.draw(
                    fit_phrase_to_width(&entry.what, brief_px, text_w, false),
                    FontId::Regular,
                    brief_px,
                    text_x,
                    brief.y + brief.h - 73.0 * s,
                    AlignX::Left,
                    AlignY::Top,
                    [198, 213, 232],
                    235,
                    true,
                );
                ui_add.line(
                    text_x,
                    brief.y + 32.0 * s,
                    brief.x + brief.w - 14.0 * s,
                    brief.y + 32.0 * s,
                    1.0,
                    linear_rgba([110, 190, 235], 82, 1.0),
                );
                ui_text.draw(
                    "Open Guide for attack tells and counters",
                    FontId::Regular,
                    pt_px(9.0, s, 7.6),
                    brief.x + 15.0 * s,
                    brief.y + 16.0 * s,
                    AlignX::Left,
                    AlignY::Center,
                    MUTED,
                    225,
                    true,
                );
            } else {
                ui_text.draw(
                    "Enemy dossiers are unavailable.",
                    FontId::Regular,
                    pt_px(10.0, s, 8.0),
                    brief.x + 15.0 * s,
                    brief.y + brief.h - 54.0 * s,
                    AlignX::Left,
                    AlignY::Center,
                    MUTED,
                    220,
                    true,
                );
            }
        }

        // Soft glowing horizon strip behind wordmark
        let horizon_y = l.title_y - 34.0 * s;
        ui_add.line(
            (l.cx - 210.0 * s).max(24.0),
            horizon_y,
            (l.cx + 210.0 * s).min(w - 24.0),
            horizon_y,
            2.2,
            linear_rgba(ACCENT, 130, 1.5),
        );
        ui_add.glow(
            l.cx,
            l.title_y,
            240.0 * s,
            2.2,
            linear_rgba([70, 145, 255], 55, 1.2),
        );

        let pulse = if reduce_motion {
            0.5
        } else {
            0.5 + 0.5 * (self.t * 2.2).sin()
        };
        let title_col = mix_rgb([210, 232, 255], [255, 255, 255], 0.35 + 0.45 * pulse);
        ui_text.draw_hdr(
            "PLOUTO",
            FontId::Head,
            pt_px(44.0, s, 26.0),
            l.cx,
            l.title_y + 10.0 * s,
            AlignX::Center,
            AlignY::Center,
            title_col,
            1.25,
            true,
        );
        ui_text.draw(
            "STELLAR SURVIVAL",
            FontId::Bold,
            pt_px(12.5, s, 9.5),
            l.cx,
            horizon_y - 16.0 * s,
            AlignX::Center,
            AlignY::Center,
            mix_rgb(ACCENT, TEXT, 0.4),
            235,
            true,
        );

        // Small animated navigation crest; the two orbital paths pause cleanly for reduced motion.
        let crest_y = l.title_y + 49.0 * s;
        let crest_spin = if reduce_motion { 0.0 } else { self.t * 0.45 };
        ui_add.ellipse(
            l.cx,
            crest_y,
            15.0 * s,
            6.0 * s,
            crest_spin,
            linear_rgba([95, 190, 255], 150, 1.25),
        );
        ui_add.ellipse(
            l.cx,
            crest_y,
            15.0 * s,
            6.0 * s,
            crest_spin + 1.05,
            linear_rgba([160, 125, 255], 115, 1.2),
        );
        ui_add.circle(
            l.cx,
            crest_y,
            3.3 * s,
            linear_rgba([225, 248, 255], 235, 1.7),
        );

        let diff_title = match difficulty {
            "easy" => "Easy",
            "hard" => "Hard",
            _ => "Normal",
        };
        if best_score > 0 {
            ui_text.draw(
                format!("Best Score ({diff_title}): {}", format_score_commas(best_score)),
                FontId::Bold,
                pt_px(12.0, s, 9.5),
                w - 22.0 * s,
                h - 20.0 * s,
                AlignX::Right,
                AlignY::Top,
                GOLD,
                235,
                true,
            );
        }

        // Buttons
        let btn_px = pt_px(16.0, s, 11.5);
        for (i, b) in self.buttons.iter().enumerate() {
            let eased = menu_button_progress(self.intro_t, i, reduce_motion);
            let mut entry_style = b.clone();
            entry_style.alpha *= eased;
            let entry_rect = menu_button_entry_rect(
                l.btn_rects[i],
                s,
                self.intro_t,
                i,
                reduce_motion,
            );
            draw_button(ui_alpha, ui_text, entry_rect, &entry_style, btn_px, s);
        }

        // Daily summary badge right below buttons / above mutators
        let daily_def = mutator_by_id(daily_mut_id);
        let daily_name = daily_def.map(|m| m.name).unwrap_or(daily_mut_id);
        let daily_mult = daily_def.map(|m| format_score_mult(m.score_mult)).unwrap_or_else(|| "x1.00".to_string());
        let current_daily_record = daily_entry.filter(|entry| {
            entry.rules_version == Some(crate::sim::replay::SIMULATION_RULES_VERSION)
                && entry.seed == daily_seed(daily_date).ok()
                && entry.mutators.len() == 1
                && entry.mutators[0] == daily_mut_id
        });
        let daily_line = match (daily_entry, current_daily_record) {
            (Some(entry), Some(_)) => format!(
                "UTC Daily {daily_date} · {} · {} · {daily_name} {daily_mult} · Best {} (W{wv})",
                DAILY_DIFFICULTY.to_ascii_uppercase(),
                DAILY_MAP_TYPE.to_ascii_uppercase(),
                format_score_commas(entry.score),
                wv = entry.wave,
            ),
            (Some(entry), None) => {
                let context = match entry.rules_version {
                    Some(version) if version != crate::sim::replay::SIMULATION_RULES_VERSION => {
                        format!("prior rules v{version}")
                    }
                    Some(_) => "prior challenge setup".to_string(),
                    None => "legacy rules unknown".to_string(),
                };
                format!(
                    "UTC Daily {daily_date} · {} · {} · {daily_name} {daily_mult} · {context} best {} (W{})",
                    DAILY_DIFFICULTY.to_ascii_uppercase(),
                    DAILY_MAP_TYPE.to_ascii_uppercase(),
                    format_score_commas(entry.score),
                    entry.wave,
                )
            }
            (None, _) => format!(
                "UTC Daily {daily_date} · {} · {} · {daily_name} {daily_mult} · No attempt today",
                DAILY_DIFFICULTY.to_ascii_uppercase(),
                DAILY_MAP_TYPE.to_ascii_uppercase(),
            ),
        };
        ui_text.draw(
            fonts.fit_text(
                FontId::Regular,
                pt_px(11.5, s, 9.5),
                &daily_line,
                (w - 36.0 * s).max(220.0),
            ),
            FontId::Regular,
            pt_px(11.5, s, 9.5),
            l.cx,
            l.mut_y + 42.0 * s,
            AlignX::Center,
            AlignY::Center,
            [185, 208, 248],
            230,
            true,
        );
        if let Some(definition) = daily_def {
            let effect_line = format!("DAILY MODIFIER · {}", definition.description);
            let effect_px = pt_px(10.0, s, 8.5);
            ui_text.draw(
                fonts.fit_text(
                    FontId::Regular,
                    effect_px,
                    &effect_line,
                    (w - 36.0 * s).max(220.0),
                ),
                FontId::Regular,
                effect_px,
                l.cx,
                l.mut_y + 58.0 * s,
                AlignX::Center,
                AlignY::Center,
                mix_rgb(GOLD, TEXT, 0.38),
                220,
                true,
            );
        }

        // Mutators chip row
        let mult = combined_score_multiplier(selected_mutators);
        let chip_px = pt_px(10.5, s, 8.5);
        for (i, m) in MUTATORS.iter().enumerate() {
            let active = selected_mutators.iter().any(|id| id == m.id);
            let hovered = self.hovered_mutator == Some(i) || self.focused_mutator == Some(i);
            let chip_eased = menu_mutator_progress(self.intro_t, i, reduce_motion);
            if chip_eased > 0.01 {
                let chip_rect = menu_mutator_entry_rect(
                    l.mut_rects[i],
                    s,
                    self.intro_t,
                    i,
                    reduce_motion,
                );
                draw_chip(
                    ui_alpha,
                    ui_text,
                    chip_rect,
                    m.name,
                    active,
                    hovered,
                    if active { GOLD } else { ACCENT },
                    chip_px,
                    s,
                    chip_eased,
                );
            }
        }

        // Mutator info / multiplier line
        let confirm = glyphs::confirm_label(self.input_device);
        let info_txt = if let Some(idx) = self.focused_mutator {
            format!("{} · ←/→ choose modifier · {confirm} toggles", MUTATORS[idx].name)
        } else if let Some(idx) = self.hovered_mutator {
            let m = &MUTATORS[idx];
            format!("{} ({}): {}", m.name, format_score_mult(m.score_mult), m.description)
        } else if !selected_mutators.is_empty() {
            let names = mutator_names(selected_mutators).join(", ");
            format!(
                "Active Mutators: {names}   |   Score Multiplier {}   |   ↓ from Quit · ←/→ move · {confirm} toggle",
                format_score_mult(mult)
            )
        } else {
            format!(
                "Mutators: None selected   |   Score Multiplier {}   |   ↓ from Quit · ←/→ move · {confirm} toggle",
                format_score_mult(mult)
            )
        };
        let info_px = pt_px(10.5, s, 8.5);
        let fit_info = fonts.fit_text(FontId::Regular, info_px, &info_txt, (w - 40.0 * s).max(200.0));
        ui_text.draw(
            fit_info,
            FontId::Regular,
            info_px,
            l.cx,
            l.mut_y - 16.0 * s,
            AlignX::Center,
            AlignY::Center,
            if self.hovered_mutator.is_some() || !selected_mutators.is_empty() {
                mix_rgb(GOLD, TEXT, 0.35)
            } else {
                MUTED
            },
            235,
            true,
        );

        // Bottom control hint strip
        ui_text.draw(
            glyphs::controls_hint(self.input_device),
            FontId::Regular,
            pt_px(10.5, s, 8.5),
            l.cx,
            16.0 * s,
            AlignX::Center,
            AlignY::Center,
            MUTED,
            210,
            true,
        );
    }
}

fn menu_button_progress(intro_t: f32, index: usize, reduce_motion: bool) -> f32 {
    if reduce_motion {
        1.0
    } else {
        ((intro_t - index as f32 * 0.055) / 0.34).clamp(0.0, 1.0)
    }
}

fn menu_mutator_progress(intro_t: f32, index: usize, reduce_motion: bool) -> f32 {
    if reduce_motion {
        1.0
    } else {
        ((intro_t - 0.22 - index as f32 * 0.035) / 0.28).clamp(0.0, 1.0)
    }
}

fn menu_button_entry_rect(
    rect: UiRect,
    scale: f32,
    intro_t: f32,
    index: usize,
    reduce_motion: bool,
) -> UiRect {
    let mut rect = rect;
    let progress = menu_button_progress(intro_t, index, reduce_motion);
    let eased = 1.0 - (1.0 - progress).powi(3);
    rect.y -= (1.0 - eased) * 14.0 * scale;
    rect
}

fn menu_mutator_entry_rect(
    rect: UiRect,
    scale: f32,
    intro_t: f32,
    index: usize,
    reduce_motion: bool,
) -> UiRect {
    let mut rect = rect;
    let progress = menu_mutator_progress(intro_t, index, reduce_motion);
    let eased = 1.0 - (1.0 - progress).powi(3);
    rect.y -= (1.0 - eased) * 6.0 * scale;
    rect
}

struct MenuLayout {
    s: f32,
    cx: f32,
    title_y: f32,
    btn_rects: Vec<UiRect>,
    mut_rects: Vec<UiRect>,
    mut_y: f32,
    spotlight_rect: Option<UiRect>,
}

// ---------------------------------------------------------------------------
// Settings Screen
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SliderId {
    ArenaMargin,
    MusicVolume,
    SfxVolume,
}

#[derive(Debug, Clone, PartialEq)]
pub enum SettingsAction {
    None,
    Back,
    Changed {
        resize_window: Option<(u32, u32)>,
        toggle_fullscreen: Option<bool>,
        arena_resized: bool,
    },
}

const DISPLAY_PRESETS: &[Option<(u32, u32)>] = &[
    Some((980, 620)),
    Some((1280, 720)),
    Some((1600, 900)),
    None, // Fullscreen
];

const DIFFICULTIES: &[(&str, &str)] = &[("easy", "Easy"), ("normal", "Normal"), ("hard", "Hard")];
const MAP_TYPES: &[(&str, &str)] = &[
    ("circle", "Circle"),
    ("donut", "Donut"),
    ("cross", "Cross"),
    ("diamond", "Diamond"),
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SettingsFocus {
    Difficulty,
    ArenaShape,
    DisplayMode,
    AutoFire,
    PlayerVisual,
    GamepadEnabled,
    GamepadVibration,
    GamepadDeadzone,
    ArenaScale,
    MusicVolume,
    SfxVolume,
    Shake,
    AdvancedFx,
    ReducedMotion,
    Colorblind,
    HudPlate,
    Back,
}

const SETTINGS_FOCUS_ORDER: [SettingsFocus; 17] = [
    SettingsFocus::Difficulty,
    SettingsFocus::ArenaShape,
    SettingsFocus::DisplayMode,
    SettingsFocus::AutoFire,
    SettingsFocus::PlayerVisual,
    SettingsFocus::GamepadEnabled,
    SettingsFocus::GamepadVibration,
    SettingsFocus::GamepadDeadzone,
    SettingsFocus::ArenaScale,
    SettingsFocus::MusicVolume,
    SettingsFocus::SfxVolume,
    SettingsFocus::Shake,
    SettingsFocus::AdvancedFx,
    SettingsFocus::ReducedMotion,
    SettingsFocus::Colorblind,
    SettingsFocus::HudPlate,
    SettingsFocus::Back,
];

const SHAKE_LEVELS: &[(&str, &str)] = &[
    ("full", "Full"),
    ("reduced", "Reduced"),
    ("off", "Off"),
];

fn cycle_setting_option(current: &str, options: &[(&str, &str)], step: isize) -> String {
    let index = options
        .iter()
        .position(|(value, _)| *value == current)
        .unwrap_or(0) as isize;
    let next = (index + step).rem_euclid(options.len() as isize) as usize;
    options[next].0.to_string()
}

const GAMEPAD_DEADZONE_STEP: f32 = 0.02;

/// Moves the stick deadzone by whole steps, clamped to the allowed range (keyboard).
fn step_gamepad_deadzone(current: f32, step: isize) -> f32 {
    let base = if current.is_finite() { current } else { GAMEPAD_DEADZONE_MIN };
    let next = base + step as f32 * GAMEPAD_DEADZONE_STEP;
    ((next * 100.0).round() / 100.0).clamp(GAMEPAD_DEADZONE_MIN, GAMEPAD_DEADZONE_MAX)
}

/// Advances the stick deadzone one step, wrapping back to the minimum past the maximum (mouse click).
fn cycle_gamepad_deadzone(current: f32) -> f32 {
    if current.is_finite() && current + GAMEPAD_DEADZONE_STEP * 0.5 < GAMEPAD_DEADZONE_MAX {
        step_gamepad_deadzone(current, 1)
    } else {
        GAMEPAD_DEADZONE_MIN
    }
}

pub struct SettingsScreen {
    pub settings: UserSettings,
    pub enable_advanced_fx: bool,
    pub use_player_art: bool,
    active_slider: Option<SliderId>,
    hovered_pos: [f32; 2],
    has_pointer: bool,
    focus_idx: Option<SettingsFocus>,
    back_btn: ButtonStyle,
}

impl Default for SettingsScreen {
    fn default() -> Self {
        Self::new(UserSettings::default(), true, true)
    }
}

impl SettingsScreen {
    pub fn new(settings: UserSettings, enable_advanced_fx: bool, use_player_art: bool) -> Self {
        Self {
            settings,
            enable_advanced_fx,
            use_player_art,
            active_slider: None,
            hovered_pos: [0.0, 0.0],
            has_pointer: false,
            focus_idx: Some(SettingsFocus::Difficulty),
            back_btn: ButtonStyle::new("Back to Menu", [85, 110, 150], ACCENT),
        }
    }

    pub fn update(&mut self, dt: f32, view_w: u32, view_h: u32) {
        let l = self.layout(view_w, view_h);
        let hov = self.has_pointer && l.back_btn.contains(self.hovered_pos[0], self.hovered_pos[1]);
        self.back_btn.update_hover(hov, dt, self.settings.reduced_motion);
    }

    pub fn on_mouse_move(&mut self, x: f32, y: f32, view_w: u32, view_h: u32) -> SettingsAction {
        self.hovered_pos = [x, y];
        self.has_pointer = true;
        if let Some(sid) = self.active_slider {
            return self.set_slider_from_x(sid, x, view_w, view_h);
        }
        SettingsAction::None
    }

    pub fn on_mouse_release(&mut self) {
        self.active_slider = None;
    }

    pub fn is_adjusting(&self) -> bool {
        self.active_slider.is_some()
    }

    fn display_preset_index(&self) -> usize {
        if self.settings.fullscreen {
            return DISPLAY_PRESETS.len() - 1;
        }
        let current = self.settings.display_size.unwrap_or((1280, 720));
        DISPLAY_PRESETS
            .iter()
            .position(|preset| *preset == Some(current))
            .unwrap_or(1)
    }

    fn select_display_preset(&mut self, index: usize) -> SettingsAction {
        match DISPLAY_PRESETS.get(index).copied().flatten() {
            None => {
                self.settings.fullscreen = true;
                SettingsAction::Changed {
                    resize_window: None,
                    toggle_fullscreen: Some(true),
                    arena_resized: true,
                }
            }
            Some((pw, ph)) => {
                self.settings.fullscreen = false;
                self.settings.display_size = Some((pw, ph));
                SettingsAction::Changed {
                    resize_window: Some((pw, ph)),
                    toggle_fullscreen: Some(false),
                    arena_resized: true,
                }
            }
        }
    }

    pub fn on_mouse_press(&mut self, x: f32, y: f32, view_w: u32, view_h: u32) -> SettingsAction {
        self.hovered_pos = [x, y];
        self.has_pointer = true;
        let l = self.layout(view_w, view_h);

        if l.back_btn.contains(x, y) {
            self.active_slider = None;
            return SettingsAction::Back;
        }

        for (i, (id, _)) in DIFFICULTIES.iter().enumerate() {
            if l.diff_btns[i].contains(x, y) {
                self.focus_idx = Some(SettingsFocus::Difficulty);
                self.settings.difficulty = (*id).to_string();
                return SettingsAction::Changed {
                    resize_window: None,
                    toggle_fullscreen: None,
                    arena_resized: false,
                };
            }
        }
        for (i, (id, _)) in MAP_TYPES.iter().enumerate() {
            if l.map_btns[i].contains(x, y) {
                self.focus_idx = Some(SettingsFocus::ArenaShape);
                self.settings.map_type = (*id).to_string();
                return SettingsAction::Changed {
                    resize_window: None,
                    toggle_fullscreen: None,
                    arena_resized: false,
                };
            }
        }
        for (i, _preset) in DISPLAY_PRESETS.iter().enumerate() {
            if l.disp_btns[i].contains(x, y) {
                self.focus_idx = Some(SettingsFocus::DisplayMode);
                return self.select_display_preset(i);
            }
        }
        for (sid, rect) in [
            (SliderId::ArenaMargin, l.arena_slider),
            (SliderId::MusicVolume, l.music_slider),
            (SliderId::SfxVolume, l.sfx_slider),
        ] {
            let hit = UiRect::new(rect.x - 10.0, rect.y - 12.0, rect.w + 20.0, rect.h + 24.0);
            if hit.contains(x, y) {
                self.active_slider = Some(sid);
                self.focus_idx = Some(match sid {
                    SliderId::ArenaMargin => SettingsFocus::ArenaScale,
                    SliderId::MusicVolume => SettingsFocus::MusicVolume,
                    SliderId::SfxVolume => SettingsFocus::SfxVolume,
                });
                return self.set_slider_from_x(sid, x, view_w, view_h);
            }
        }

        if l.btn_shake.contains(x, y) {
            self.focus_idx = Some(SettingsFocus::Shake);
            self.settings.shake_level = match self.settings.shake_level.as_str() {
                "full" => "reduced",
                "reduced" => "off",
                _ => "full",
            }
            .to_string();
            return SettingsAction::Changed {
                resize_window: None,
                toggle_fullscreen: None,
                arena_resized: false,
            };
        }
        if l.btn_fx.contains(x, y) {
            self.focus_idx = Some(SettingsFocus::AdvancedFx);
            self.enable_advanced_fx = !self.enable_advanced_fx;
            return SettingsAction::Changed {
                resize_window: None,
                toggle_fullscreen: None,
                arena_resized: false,
            };
        }
        if l.btn_auto.contains(x, y) {
            self.focus_idx = Some(SettingsFocus::AutoFire);
            self.settings.auto_shoot = !self.settings.auto_shoot;
            return SettingsAction::Changed {
                resize_window: None,
                toggle_fullscreen: None,
                arena_resized: false,
            };
        }
        if l.btn_pod.contains(x, y) {
            self.focus_idx = Some(SettingsFocus::PlayerVisual);
            self.use_player_art = !self.use_player_art;
            return SettingsAction::Changed {
                resize_window: None,
                toggle_fullscreen: None,
                arena_resized: false,
            };
        }
        if l.btn_gamepad.contains(x, y) {
            self.focus_idx = Some(SettingsFocus::GamepadEnabled);
            self.settings.gamepad_enabled = !self.settings.gamepad_enabled;
            return SettingsAction::Changed {
                resize_window: None,
                toggle_fullscreen: None,
                arena_resized: false,
            };
        }
        if l.btn_vibration.contains(x, y) {
            self.focus_idx = Some(SettingsFocus::GamepadVibration);
            self.settings.gamepad_vibration = !self.settings.gamepad_vibration;
            return SettingsAction::Changed {
                resize_window: None,
                toggle_fullscreen: None,
                arena_resized: false,
            };
        }
        if l.btn_deadzone.contains(x, y) {
            self.focus_idx = Some(SettingsFocus::GamepadDeadzone);
            self.settings.gamepad_deadzone = cycle_gamepad_deadzone(self.settings.gamepad_deadzone);
            return SettingsAction::Changed {
                resize_window: None,
                toggle_fullscreen: None,
                arena_resized: false,
            };
        }
        if l.btn_motion.contains(x, y) {
            self.focus_idx = Some(SettingsFocus::ReducedMotion);
            self.settings.reduced_motion = !self.settings.reduced_motion;
            return SettingsAction::Changed {
                resize_window: None,
                toggle_fullscreen: None,
                arena_resized: false,
            };
        }
        if l.btn_colorblind.contains(x, y) {
            self.focus_idx = Some(SettingsFocus::Colorblind);
            self.settings.colorblind_palette = !self.settings.colorblind_palette;
            return SettingsAction::Changed {
                resize_window: None,
                toggle_fullscreen: None,
                arena_resized: false,
            };
        }
        if l.btn_contrast.contains(x, y) {
            self.focus_idx = Some(SettingsFocus::HudPlate);
            self.settings.high_contrast_hud = !self.settings.high_contrast_hud;
            return SettingsAction::Changed {
                resize_window: None,
                toggle_fullscreen: None,
                arena_resized: false,
            };
        }
        SettingsAction::None
    }

    pub fn on_key_nav(
        &mut self,
        dx: isize,
        dy: isize,
        activate: bool,
        back: bool,
    ) -> SettingsAction {
        if back {
            if self.active_slider.is_some() {
                self.active_slider = None;
                return SettingsAction::None;
            }
            return SettingsAction::Back;
        }
        if let Some(sid) = self.active_slider {
            if dx != 0 {
                return self.adjust_slider_value(sid, dx);
            }
            if activate {
                self.active_slider = None;
                return SettingsAction::None;
            }
            if dy != 0 {
                self.active_slider = None;
            }
        }
        if dy != 0 {
            let cur = self
                .focus_idx
                .and_then(|focus| SETTINGS_FOCUS_ORDER.iter().position(|item| *item == focus))
                .unwrap_or(0) as isize;
            let next = (cur - dy).clamp(0, SETTINGS_FOCUS_ORDER.len() as isize - 1) as usize;
            self.focus_idx = Some(SETTINGS_FOCUS_ORDER[next]);
            return SettingsAction::None;
        }
        if dx == 0 && !activate {
            return SettingsAction::None;
        }
        let focus = self.focus_idx.unwrap_or(SettingsFocus::Difficulty);
        self.focus_idx = Some(focus);
        let step = if dx == 0 { 1 } else { dx.signum() };
        match focus {
            SettingsFocus::Difficulty => {
                self.settings.difficulty =
                    cycle_setting_option(&self.settings.difficulty, DIFFICULTIES, step);
                Self::settings_changed(false)
            }
            SettingsFocus::ArenaShape => {
                self.settings.map_type =
                    cycle_setting_option(&self.settings.map_type, MAP_TYPES, step);
                Self::settings_changed(false)
            }
            SettingsFocus::DisplayMode => {
                let index = (self.display_preset_index() as isize + step)
                    .rem_euclid(DISPLAY_PRESETS.len() as isize) as usize;
                self.select_display_preset(index)
            }
            SettingsFocus::AutoFire => {
                self.settings.auto_shoot = !self.settings.auto_shoot;
                Self::settings_changed(false)
            }
            SettingsFocus::PlayerVisual => {
                self.use_player_art = !self.use_player_art;
                Self::settings_changed(false)
            }
            SettingsFocus::GamepadEnabled => {
                self.settings.gamepad_enabled = !self.settings.gamepad_enabled;
                Self::settings_changed(false)
            }
            SettingsFocus::GamepadVibration => {
                self.settings.gamepad_vibration = !self.settings.gamepad_vibration;
                Self::settings_changed(false)
            }
            SettingsFocus::GamepadDeadzone => {
                self.settings.gamepad_deadzone =
                    step_gamepad_deadzone(self.settings.gamepad_deadzone, step);
                Self::settings_changed(false)
            }
            SettingsFocus::ArenaScale => {
                if dx != 0 {
                    self.adjust_slider_value(SliderId::ArenaMargin, dx)
                } else {
                    self.active_slider = Some(SliderId::ArenaMargin);
                    SettingsAction::None
                }
            }
            SettingsFocus::MusicVolume => {
                if dx != 0 {
                    self.adjust_slider_value(SliderId::MusicVolume, dx)
                } else {
                    self.active_slider = Some(SliderId::MusicVolume);
                    SettingsAction::None
                }
            }
            SettingsFocus::SfxVolume => {
                if dx != 0 {
                    self.adjust_slider_value(SliderId::SfxVolume, dx)
                } else {
                    self.active_slider = Some(SliderId::SfxVolume);
                    SettingsAction::None
                }
            }
            SettingsFocus::Shake => {
                self.settings.shake_level =
                    cycle_setting_option(&self.settings.shake_level, SHAKE_LEVELS, step);
                Self::settings_changed(false)
            }
            SettingsFocus::AdvancedFx => {
                self.enable_advanced_fx = !self.enable_advanced_fx;
                Self::settings_changed(false)
            }
            SettingsFocus::ReducedMotion => {
                self.settings.reduced_motion = !self.settings.reduced_motion;
                Self::settings_changed(false)
            }
            SettingsFocus::Colorblind => {
                self.settings.colorblind_palette = !self.settings.colorblind_palette;
                Self::settings_changed(false)
            }
            SettingsFocus::HudPlate => {
                self.settings.high_contrast_hud = !self.settings.high_contrast_hud;
                Self::settings_changed(false)
            }
            SettingsFocus::Back if activate => SettingsAction::Back,
            SettingsFocus::Back => SettingsAction::None,
        }
    }

    fn settings_changed(arena_resized: bool) -> SettingsAction {
        SettingsAction::Changed {
            resize_window: None,
            toggle_fullscreen: None,
            arena_resized,
        }
    }

    fn adjust_slider_value(&mut self, sid: SliderId, direction: isize) -> SettingsAction {
        let step = direction as f32;
        match sid {
            SliderId::ArenaMargin => {
                self.settings.arena_margin = (self.settings.arena_margin + step * 0.01)
                    .clamp(ARENA_MARGIN_MIN, ARENA_MARGIN_MAX);
            }
            SliderId::MusicVolume => {
                self.settings.music_volume =
                    (self.settings.music_volume + step * 0.05).clamp(0.0, 1.0);
            }
            SliderId::SfxVolume => {
                self.settings.sfx_volume =
                    (self.settings.sfx_volume + step * 0.05).clamp(0.0, 1.0);
            }
        }
        Self::settings_changed(sid == SliderId::ArenaMargin)
    }

    fn focused_rect(&self, layout: &SettingsLayout) -> Option<UiRect> {
        let focus = self.focus_idx?;
        let selected = |options: &[(&str, &str)], value: &str| {
            options.iter().position(|(id, _)| *id == value).unwrap_or(0)
        };
        Some(match focus {
            SettingsFocus::Difficulty => {
                layout.diff_btns[selected(DIFFICULTIES, &self.settings.difficulty)]
            }
            SettingsFocus::ArenaShape => {
                layout.map_btns[selected(MAP_TYPES, &self.settings.map_type)]
            }
            SettingsFocus::DisplayMode => layout.disp_btns[self.display_preset_index()],
            SettingsFocus::AutoFire => layout.btn_auto,
            SettingsFocus::PlayerVisual => layout.btn_pod,
            SettingsFocus::GamepadEnabled => layout.btn_gamepad,
            SettingsFocus::GamepadVibration => layout.btn_vibration,
            SettingsFocus::GamepadDeadzone => layout.btn_deadzone,
            SettingsFocus::ArenaScale => layout.arena_slider,
            SettingsFocus::MusicVolume => layout.music_slider,
            SettingsFocus::SfxVolume => layout.sfx_slider,
            SettingsFocus::Shake => layout.btn_shake,
            SettingsFocus::AdvancedFx => layout.btn_fx,
            SettingsFocus::ReducedMotion => layout.btn_motion,
            SettingsFocus::Colorblind => layout.btn_colorblind,
            SettingsFocus::HudPlate => layout.btn_contrast,
            SettingsFocus::Back => layout.back_btn,
        })
    }

    fn set_slider_from_x(&mut self, sid: SliderId, x: f32, view_w: u32, view_h: u32) -> SettingsAction {
        let l = self.layout(view_w, view_h);
        let rect = match sid {
            SliderId::ArenaMargin => l.arena_slider,
            SliderId::MusicVolume => l.music_slider,
            SliderId::SfxVolume => l.sfx_slider,
        };
        let t = ((x - rect.x) / rect.w.max(1.0)).clamp(0.0, 1.0);
        match sid {
            SliderId::ArenaMargin => {
                self.settings.arena_margin =
                    (ARENA_MARGIN_MIN + t * (ARENA_MARGIN_MAX - ARENA_MARGIN_MIN))
                        .clamp(ARENA_MARGIN_MIN, ARENA_MARGIN_MAX);
            }
            SliderId::MusicVolume => {
                self.settings.music_volume = t;
            }
            SliderId::SfxVolume => {
                self.settings.sfx_volume = t;
            }
        }
        SettingsAction::Changed {
            resize_window: None,
            toggle_fullscreen: None,
            arena_resized: sid == SliderId::ArenaMargin,
        }
    }

    fn layout(&self, view_w: u32, view_h: u32) -> SettingsLayout {
        let w = view_w as f32;
        let h = view_h as f32;
        let s = ui_scale(view_w, view_h).min(1.30);
        let cx = w * 0.5;
        let panel_w = (w * 0.90).min(1040.0 * s);
        let panel_h = (h * 0.80).min(640.0 * s).max(400.0);
        let panel_x = cx - panel_w * 0.5;
        let panel_y = (h - panel_h) * 0.5 - 12.0 * s;
        let panel = UiRect::new(panel_x, panel_y, panel_w, panel_h);

        let pad = 24.0 * s;
        let col_gap = 28.0 * s;
        let col_w = (panel_w - 2.0 * pad - col_gap) * 0.5;
        let left_x = panel_x + pad;
        let right_x = left_x + col_w + col_gap;
        let top_y = panel_y + panel_h - 46.0 * s;

        let chip_h = 34.0 * s;
        let chip_gap = 8.0 * s;

        // Left col rows: Difficulty (y0), Arena Shape (y1), Display Mode (y2), Gameplay (y3)
        let row_step = if h < 620.0 { 76.0 * s } else { 84.0 * s };
        let diff_w = (col_w - 2.0 * chip_gap) / 3.0;
        let diff_btns: Vec<UiRect> = (0..3)
            .map(|i| UiRect::new(left_x + (i as f32) * (diff_w + chip_gap), top_y - 36.0 * s, diff_w, chip_h))
            .collect();

        let y1 = top_y - row_step;
        let map_w = (col_w - 3.0 * chip_gap) / 4.0;
        let map_btns: Vec<UiRect> = (0..4)
            .map(|i| UiRect::new(left_x + (i as f32) * (map_w + chip_gap), y1 - 36.0 * s, map_w, chip_h))
            .collect();

        let y2 = y1 - row_step;
        let disp_w = (col_w - 3.0 * chip_gap) / 4.0;
        let disp_btns: Vec<UiRect> = (0..4)
            .map(|i| UiRect::new(left_x + (i as f32) * (disp_w + chip_gap), y2 - 36.0 * s, disp_w, chip_h))
            .collect();

        let y3 = y2 - row_step;
        let half_w = (col_w - chip_gap) * 0.5;
        let btn_auto = UiRect::new(left_x, y3 - 36.0 * s, half_w, chip_h);
        let btn_pod = UiRect::new(left_x + half_w + chip_gap, y3 - 36.0 * s, half_w, chip_h);

        // Left col, row 4: controller options (Gamepad / Vibration / Stick Deadzone)
        let y4 = y3 - row_step;
        let pad_w = (col_w - 2.0 * chip_gap) / 3.0;
        let btn_gamepad = UiRect::new(left_x, y4 - 36.0 * s, pad_w, chip_h);
        let btn_vibration = UiRect::new(left_x + pad_w + chip_gap, y4 - 36.0 * s, pad_w, chip_h);
        let btn_deadzone = UiRect::new(left_x + 2.0 * (pad_w + chip_gap), y4 - 36.0 * s, pad_w, chip_h);

        // Right col: Arena Slider, Music Slider, SFX Slider, Visual/FX row, Accessibility row
        let slider_h = 10.0 * s;
        let arena_slider = UiRect::new(right_x, top_y - 28.0 * s, col_w, slider_h);
        let music_slider = UiRect::new(right_x, top_y - 98.0 * s, col_w, slider_h);
        let sfx_slider = UiRect::new(right_x, top_y - 168.0 * s, col_w, slider_h);

        let r_fx_y = top_y - 246.0 * s;
        let btn_shake = UiRect::new(right_x, r_fx_y - 36.0 * s, half_w, chip_h);
        let btn_fx = UiRect::new(right_x + half_w + chip_gap, r_fx_y - 36.0 * s, half_w, chip_h);

        let r_acc_y = r_fx_y - 84.0 * s;
        let acc_w = (col_w - 2.0 * chip_gap) / 3.0;
        let btn_motion = UiRect::new(right_x, r_acc_y - 36.0 * s, acc_w, chip_h);
        let btn_colorblind = UiRect::new(right_x + acc_w + chip_gap, r_acc_y - 36.0 * s, acc_w, chip_h);
        let btn_contrast = UiRect::new(right_x + 2.0 * (acc_w + chip_gap), r_acc_y - 36.0 * s, acc_w, chip_h);

        let bw = 180.0 * s;
        let bh = 42.0 * s;
        let back_btn = UiRect::new(cx - bw * 0.5, panel_y + 16.0 * s, bw, bh);

        SettingsLayout {
            s,
            cx,
            panel,
            left_x,
            right_x,
            top_y,
            y1,
            y2,
            y3,
            y4,
            r_fx_y,
            r_acc_y,
            diff_btns,
            map_btns,
            disp_btns,
            btn_auto,
            btn_pod,
            btn_gamepad,
            btn_vibration,
            btn_deadzone,
            arena_slider,
            music_slider,
            sfx_slider,
            btn_shake,
            btn_fx,
            btn_motion,
            btn_colorblind,
            btn_contrast,
            back_btn,
        }
    }

    pub fn draw(
        &self,
        ui_alpha: &mut SdfBatch,
        ui_text: &mut TextBatch,
        view_w: u32,
        view_h: u32,
    ) {
        let l = self.layout(view_w, view_h);
        let s = l.s;
        let w = view_w as f32;
        let h = view_h as f32;
        let [mx, my] = self.hovered_pos;

        ui_alpha.panel(0.0, 0.0, w, h, 0.0, linear_rgba(BACKGROUND, 195, 1.0));
        ui_text.draw_hdr(
            "SETTINGS",
            FontId::Head,
            pt_px(28.0, s, 18.0),
            l.cx,
            h - 38.0 * s,
            AlignX::Center,
            AlignY::Center,
            TEXT,
            1.0,
            true,
        );
        ui_text.draw(
            "Use arrows + Enter to adjust; Esc backs out. Arena shape affects the next run.",
            FontId::Regular,
            pt_px(11.5, s, 9.5),
            l.cx,
            h - 68.0 * s,
            AlignX::Center,
            AlignY::Center,
            MUTED,
            230,
            true,
        );

        draw_panel(ui_alpha, l.panel, 10.0 * s, 1.8, PANEL, 215, ACCENT, 75, 6.0 * s);

        let sec_px = pt_px(13.5, s, 10.5);
        let chip_px = pt_px(11.0, s, 9.0);
        let draw_sec = |txt_batch: &mut TextBatch, x: f32, y: f32, title: &str, note: &str| {
            txt_batch.draw(title, FontId::Bold, sec_px, x, y, AlignX::Left, AlignY::Center, TEXT, 255, true);
            if !note.is_empty() {
                txt_batch.draw(
                    note,
                    FontId::Regular,
                    pt_px(10.0, s, 8.5),
                    x + 125.0 * s,
                    y,
                    AlignX::Left,
                    AlignY::Center,
                    MUTED,
                    210,
                    false,
                );
            }
        };

        // Left column
        draw_sec(ui_text, l.left_x, l.top_y - 6.0 * s, "Difficulty", "(next run)");
        for (i, (id, label)) in DIFFICULTIES.iter().enumerate() {
            let active = self.settings.difficulty == *id;
            let hov = self.has_pointer && l.diff_btns[i].contains(mx, my);
            draw_chip(ui_alpha, ui_text, l.diff_btns[i], label, active, hov, ACCENT, chip_px, s, 1.0);
        }

        draw_sec(ui_text, l.left_x, l.y1 - 6.0 * s, "Arena Shape", "(next run)");
        for (i, (id, label)) in MAP_TYPES.iter().enumerate() {
            let active = self.settings.map_type == *id;
            let hov = self.has_pointer && l.map_btns[i].contains(mx, my);
            draw_chip(ui_alpha, ui_text, l.map_btns[i], label, active, hov, ACCENT, chip_px, s, 1.0);
        }

        draw_sec(ui_text, l.left_x, l.y2 - 6.0 * s, "Display Mode", "");
        let disp_labels = ["980x620", "1280x720", "1600x900", "Fullscreen"];
        for (i, preset) in DISPLAY_PRESETS.iter().enumerate() {
            let active = match preset {
                None => self.settings.fullscreen,
                Some((pw, ph)) => !self.settings.fullscreen && view_w == *pw && view_h == *ph,
            };
            let hov = self.has_pointer && l.disp_btns[i].contains(mx, my);
            draw_chip(ui_alpha, ui_text, l.disp_btns[i], disp_labels[i], active, hov, ACCENT, chip_px, s, 1.0);
        }

        draw_sec(ui_text, l.left_x, l.y3 - 6.0 * s, "Gameplay & Style", "");
        draw_chip(
            ui_alpha,
            ui_text,
            l.btn_auto,
            if self.settings.auto_shoot { "Auto-Fire: ON" } else { "Auto-Fire: OFF" },
            self.settings.auto_shoot,
            self.has_pointer && l.btn_auto.contains(mx, my),
            SUCCESS,
            chip_px,
            s,
            1.0,
        );
        draw_chip(
            ui_alpha,
            ui_text,
            l.btn_pod,
            if self.use_player_art { "Visual: Pod Rig" } else { "Visual: Classic" },
            self.use_player_art,
            self.has_pointer && l.btn_pod.contains(mx, my),
            ACCENT,
            chip_px,
            s,
            1.0,
        );

        // Controller options
        draw_sec(ui_text, l.left_x, l.y4 - 6.0 * s, "Controller", "");
        draw_chip(
            ui_alpha,
            ui_text,
            l.btn_gamepad,
            if self.settings.gamepad_enabled { "Gamepad: ON" } else { "Gamepad: OFF" },
            self.settings.gamepad_enabled,
            self.has_pointer && l.btn_gamepad.contains(mx, my),
            SUCCESS,
            chip_px,
            s,
            1.0,
        );
        draw_chip(
            ui_alpha,
            ui_text,
            l.btn_vibration,
            if self.settings.gamepad_vibration { "Vibration: ON" } else { "Vibration: OFF" },
            self.settings.gamepad_vibration,
            self.has_pointer && l.btn_vibration.contains(mx, my),
            GOLD,
            chip_px,
            s,
            1.0,
        );
        let deadzone_lbl = format!("Deadzone: {:.2}", self.settings.gamepad_deadzone);
        draw_chip(
            ui_alpha,
            ui_text,
            l.btn_deadzone,
            &deadzone_lbl,
            false,
            self.has_pointer && l.btn_deadzone.contains(mx, my),
            GOLD,
            chip_px,
            s,
            1.0,
        );

        // Right column sliders
        let arena_frac = ((self.settings.arena_margin - ARENA_MARGIN_MIN) / (ARENA_MARGIN_MAX - ARENA_MARGIN_MIN)).clamp(0.0, 1.0);
        let arena_pct = (self.settings.arena_margin * 100.0).round() as i32;
        draw_sec(ui_text, l.right_x, l.top_y - 6.0 * s, &format!("Arena Scale: {arena_pct}%"), "");
        draw_slider(
            ui_alpha,
            l.arena_slider,
            arena_frac,
            ACCENT,
            self.has_pointer && l.arena_slider.contains(mx, my),
            self.active_slider == Some(SliderId::ArenaMargin),
            false,
            s,
        );

        let mus_pct = (self.settings.music_volume * 100.0).round() as i32;
        draw_sec(ui_text, l.right_x, l.top_y - 76.0 * s, &format!("Music Volume: {mus_pct}%"), "");
        draw_slider(
            ui_alpha,
            l.music_slider,
            self.settings.music_volume,
            ACCENT,
            self.has_pointer && l.music_slider.contains(mx, my),
            self.active_slider == Some(SliderId::MusicVolume),
            false,
            s,
        );

        let sfx_pct = (self.settings.sfx_volume * 100.0).round() as i32;
        draw_sec(ui_text, l.right_x, l.top_y - 146.0 * s, &format!("SFX Volume: {sfx_pct}%"), "");
        draw_slider(
            ui_alpha,
            l.sfx_slider,
            self.settings.sfx_volume,
            ACCENT,
            self.has_pointer && l.sfx_slider.contains(mx, my),
            self.active_slider == Some(SliderId::SfxVolume),
            false,
            s,
        );

        // Visual FX + Shake
        draw_sec(ui_text, l.right_x, l.r_fx_y - 6.0 * s, "Feedback & Bloom", "");
        let shake_lbl = match self.settings.shake_level.as_str() {
            "reduced" => "Shake: Reduced",
            "off" => "Shake: Off",
            _ => "Shake: Full",
        };
        draw_chip(
            ui_alpha,
            ui_text,
            l.btn_shake,
            shake_lbl,
            self.settings.shake_level == "full",
            self.has_pointer && l.btn_shake.contains(mx, my),
            ACCENT,
            chip_px,
            s,
            1.0,
        );
        draw_chip(
            ui_alpha,
            ui_text,
            l.btn_fx,
            if self.enable_advanced_fx { "Advanced FX: ON" } else { "Advanced FX: OFF" },
            self.enable_advanced_fx,
            self.has_pointer && l.btn_fx.contains(mx, my),
            SUCCESS,
            chip_px,
            s,
            1.0,
        );

        // Accessibility
        draw_sec(ui_text, l.right_x, l.r_acc_y - 6.0 * s, "Accessibility", "");
        draw_chip(
            ui_alpha,
            ui_text,
            l.btn_motion,
            if self.settings.reduced_motion { "Motion: Low" } else { "Motion: Full" },
            self.settings.reduced_motion,
            self.has_pointer && l.btn_motion.contains(mx, my),
            GOLD,
            chip_px,
            s,
            1.0,
        );
        draw_chip(
            ui_alpha,
            ui_text,
            l.btn_colorblind,
            if self.settings.colorblind_palette { "Colorblind: ON" } else { "Colorblind: OFF" },
            self.settings.colorblind_palette,
            self.has_pointer && l.btn_colorblind.contains(mx, my),
            GOLD,
            chip_px,
            s,
            1.0,
        );
        draw_chip(
            ui_alpha,
            ui_text,
            l.btn_contrast,
            if self.settings.high_contrast_hud { "HUD Plate: ON" } else { "HUD Plate: OFF" },
            self.settings.high_contrast_hud,
            self.has_pointer && l.btn_contrast.contains(mx, my),
            GOLD,
            chip_px,
            s,
            1.0,
        );

        draw_button(ui_alpha, ui_text, l.back_btn, &self.back_btn, pt_px(14.5, s, 10.5), s);
        if let Some(rect) = self.focused_rect(&l) {
            let pad_x = 3.0 * s;
            let pad_y = if rect.h <= 14.0 * s { 8.0 * s } else { 2.0 * s };
            ui_alpha.panel_outline(
                rect.x - pad_x,
                rect.y - pad_y,
                rect.w + pad_x * 2.0,
                rect.h + pad_y * 2.0,
                8.0 * s,
                2.0 * s,
                linear_rgba([205, 242, 255], 235, 1.25),
            );
        }
    }
}

struct SettingsLayout {
    s: f32,
    cx: f32,
    panel: UiRect,
    left_x: f32,
    right_x: f32,
    top_y: f32,
    y1: f32,
    y2: f32,
    y3: f32,
    y4: f32,
    r_fx_y: f32,
    r_acc_y: f32,
    diff_btns: Vec<UiRect>,
    map_btns: Vec<UiRect>,
    disp_btns: Vec<UiRect>,
    btn_auto: UiRect,
    btn_pod: UiRect,
    btn_gamepad: UiRect,
    btn_vibration: UiRect,
    btn_deadzone: UiRect,
    arena_slider: UiRect,
    music_slider: UiRect,
    sfx_slider: UiRect,
    btn_shake: UiRect,
    btn_fx: UiRect,
    btn_motion: UiRect,
    btn_colorblind: UiRect,
    btn_contrast: UiRect,
    back_btn: UiRect,
}

// ---------------------------------------------------------------------------
// Guide Screen
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GuideTab {
    Enemies,
    Powerups,
    Basics,
    Systems,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum GuideAction {
    None,
    Back,
}

#[derive(Debug, Clone)]
pub struct GuideEntry {
    pub key: &'static str,
    pub name: String,
    pub icon: &'static str,
    pub what: String,
    pub deal: String,
    pub lore: String,
    pub accent: [u8; 3],
}

const GUIDE_REGULAR_MODEL_KEYS: [&str; 11] = [
    "chaser", "bomber", "ranged", "sniper", "tank", "charger", "spitter", "flyer",
    "engineer", "swarm", "egg_sac",
];
const GUIDE_BOSS_MODEL_KEYS: [&str; 8] = [
    "boss_thunder", "boss_laser", "boss_trapmaster", "boss_swarmqueen", "boss_brute",
    "boss_abyss_gaze", "boss_womb_core", "boss_eclipse_archon",
];

fn is_guide_enemy_model(key: &str) -> bool {
    GUIDE_REGULAR_MODEL_KEYS.contains(&key) || GUIDE_BOSS_MODEL_KEYS.contains(&key)
}

fn is_guide_boss_model(key: &str) -> bool {
    GUIDE_BOSS_MODEL_KEYS.contains(&key)
}

fn draw_guide_model_preview(
    entry: &GuideEntry,
    alpha: &mut SdfBatch,
    add: &mut SdfBatch,
    center: [f32; 2],
    facing: crate::sim::math::Vec2,
    scale: f32,
    time: f32,
    reduce_motion: bool,
) -> bool {
    if !is_guide_enemy_model(entry.key) {
        return false;
    }
    let preview_enemy = crate::sim::enemy::Enemy::new(
        0,
        crate::sim::math::Vec2::ZERO,
        100,
        80.0,
        entry.key,
    );
    if is_guide_boss_model(entry.key) {
        crate::render::models3d::draw_boss_model(
            &preview_enemy,
            alpha,
            add,
            center,
            facing,
            scale,
            time,
            0.0,
            entry.accent,
            reduce_motion,
        )
    } else {
        crate::render::models3d::draw_enemy_model(
            &preview_enemy,
            alpha,
            add,
            center,
            facing,
            scale,
            -0.06,
            0.0,
            time,
            0.0,
            1.0,
            entry.accent,
            reduce_motion,
        )
    }
}

/// Draws recognizable symbols for enemy-guide concepts that do not have a unique 3D hull.
/// The 19 actual enemy and boss dossiers use their corresponding rotating 3D model instead.
fn draw_enemy_guide_symbol(
    key: &str,
    x: f32,
    y: f32,
    scale: f32,
    accent: [u8; 3],
    batch: &mut SdfBatch,
) -> bool {
    let color = linear_rgba(accent, 245, 1.25);
    let thin = (1.8 * scale).max(1.0);
    let dot = |batch: &mut SdfBatch, px: f32, py: f32| {
        batch.circle(px, py, 2.2 * scale, color);
    };
    match key {
        "volatile" => {
            let points = [
                [x, y + 11.0 * scale],
                [x + 3.4 * scale, y + 4.0 * scale],
                [x + 10.0 * scale, y + 5.5 * scale],
                [x + 5.0 * scale, y],
                [x + 10.0 * scale, y - 6.0 * scale],
                [x + 2.5 * scale, y - 4.3 * scale],
                [x, y - 11.0 * scale],
                [x - 2.5 * scale, y - 4.3 * scale],
                [x - 10.0 * scale, y - 6.0 * scale],
                [x - 5.0 * scale, y],
                [x - 10.0 * scale, y + 5.5 * scale],
                [x - 3.4 * scale, y + 4.0 * scale],
            ];
            batch.polyline_closed(&points, thin, color);
            batch.circle(x, y, 2.5 * scale, color);
        }
        "swift" => {
            for offset in [-5.0_f32, 0.0, 5.0] {
                batch.line(
                    x - 8.0 * scale,
                    y + offset * scale - 3.0 * scale,
                    x + 1.0 * scale,
                    y + offset * scale,
                    thin,
                    color,
                );
                batch.line(
                    x + 1.0 * scale,
                    y + offset * scale,
                    x - 8.0 * scale,
                    y + offset * scale + 3.0 * scale,
                    thin,
                    color,
                );
            }
            batch.line(x + 2.0 * scale, y, x + 10.0 * scale, y, thin, color);
        }
        "shielded" => {
            let points = [
                [x, y + 11.0 * scale],
                [x + 9.0 * scale, y + 7.0 * scale],
                [x + 8.0 * scale, y - 2.0 * scale],
                [x, y - 11.0 * scale],
                [x - 8.0 * scale, y - 2.0 * scale],
                [x - 9.0 * scale, y + 7.0 * scale],
            ];
            batch.polyline_closed(&points, thin, color);
            batch.line(x - 4.0 * scale, y, x + 4.0 * scale, y, thin, color);
        }
        "splitter" => {
            batch.line(x, y - 8.0 * scale, x, y - 1.0 * scale, thin, color);
            batch.line(x, y - 1.0 * scale, x - 8.0 * scale, y + 7.0 * scale, thin, color);
            batch.line(x, y - 1.0 * scale, x + 8.0 * scale, y + 7.0 * scale, thin, color);
            dot(batch, x, y - 9.0 * scale);
            dot(batch, x - 9.0 * scale, y + 8.0 * scale);
            dot(batch, x + 9.0 * scale, y + 8.0 * scale);
        }
        "reflector" => {
            batch.line(x - 10.0 * scale, y - 5.0 * scale, x - 1.0 * scale, y, thin, color);
            batch.line(x - 1.0 * scale, y, x + 8.0 * scale, y + 6.0 * scale, thin, color);
            batch.line(x + 8.0 * scale, y + 6.0 * scale, x + 2.0 * scale, y + 10.0 * scale, thin, color);
            batch.line(x + 8.0 * scale, y + 6.0 * scale, x + 8.0 * scale, y - 1.0 * scale, thin, color);
            batch.circle(x - 1.0 * scale, y, 2.4 * scale, color);
        }
        "mender" => {
            batch.ring(x, y, 9.5 * scale, 9.5 * scale, thin, color);
            batch.line(x - 5.0 * scale, y, x + 5.0 * scale, y, 2.6 * scale, color);
            batch.line(x, y - 5.0 * scale, x, y + 5.0 * scale, 2.6 * scale, color);
            dot(batch, x - 10.0 * scale, y - 8.0 * scale);
            dot(batch, x + 10.0 * scale, y + 8.0 * scale);
        }
        "warden" => {
            batch.ring(x, y, 7.0 * scale, 7.0 * scale, thin, color);
            for (angle_x, angle_y) in [(-8.0_f32, 7.0_f32), (8.0, 7.0), (0.0, -10.0)] {
                batch.line(x, y, x + angle_x * scale, y + angle_y * scale, thin, color);
                dot(batch, x + angle_x * scale, y + angle_y * scale);
            }
        }
        "boss_personas" => {
            batch.line(x - 7.0 * scale, y - 2.0 * scale, x, y + 7.0 * scale, thin, color);
            batch.line(x, y + 7.0 * scale, x + 7.0 * scale, y - 2.0 * scale, thin, color);
            batch.line(x + 7.0 * scale, y - 2.0 * scale, x - 7.0 * scale, y - 2.0 * scale, thin, color);
            for angle in [0.0_f32, 2.094, 4.189] {
                dot(batch, x + angle.cos() * 8.0 * scale, y + angle.sin() * 8.0 * scale);
            }
            batch.circle(x, y, 2.5 * scale, color);
        }
        "boss_rage" => {
            let left = [[x - 8.0 * scale, y - 6.0 * scale], [x - 5.0 * scale, y + 4.0 * scale], [x - 1.0 * scale, y - 6.0 * scale]];
            let center = [[x - 4.0 * scale, y - 7.0 * scale], [x, y + 10.0 * scale], [x + 4.0 * scale, y - 7.0 * scale]];
            let right = [[x + 1.0 * scale, y - 6.0 * scale], [x + 6.0 * scale, y + 4.0 * scale], [x + 9.0 * scale, y - 6.0 * scale]];
            batch.polyline_closed(&left, thin, color);
            batch.polyline_closed(&center, thin, color);
            batch.polyline_closed(&right, thin, color);
        }
        _ => return false,
    }
    true
}

pub struct GuideScreen {
    pub tab: GuideTab,
    pub page: usize,
    t: f32,
    reduce_motion: bool,
    hovered_pos: [f32; 2],
    has_pointer: bool,
    btn_enemies: ButtonStyle,
    btn_powerups: ButtonStyle,
    btn_basics: ButtonStyle,
    btn_systems: ButtonStyle,
    btn_prev: ButtonStyle,
    btn_next: ButtonStyle,
    btn_back: ButtonStyle,
}

impl Default for GuideScreen {
    fn default() -> Self {
        Self::new()
    }
}

impl GuideScreen {
    pub fn new() -> Self {
        Self {
            tab: GuideTab::Enemies,
            page: 0,
            t: 0.0,
            reduce_motion: false,
            hovered_pos: [0.0, 0.0],
            has_pointer: false,
            btn_enemies: ButtonStyle::new("Enemies", PANEL, ACCENT),
            btn_powerups: ButtonStyle::new("Powerups", PANEL, ACCENT),
            btn_basics: ButtonStyle::new("Basics", PANEL, ACCENT),
            btn_systems: ButtonStyle::new("Systems", PANEL, ACCENT),
            btn_prev: ButtonStyle::new("Prev", PANEL, ACCENT),
            btn_next: ButtonStyle::new("Next", PANEL, ACCENT),
            btn_back: ButtonStyle::new("Back", [85, 110, 150], ACCENT),
        }
    }

    pub fn open(&mut self) {
        self.page = 0;
    }

    pub fn update(&mut self, dt: f32, view_w: u32, view_h: u32, reduce_motion: bool) {
        self.reduce_motion = reduce_motion;
        if !reduce_motion {
            self.t += dt;
        }
        let l = self.layout(view_w, view_h);
        let [mx, my] = self.hovered_pos;
        self.btn_enemies.selected = self.tab == GuideTab::Enemies;
        self.btn_powerups.selected = self.tab == GuideTab::Powerups;
        self.btn_basics.selected = self.tab == GuideTab::Basics;
        self.btn_systems.selected = self.tab == GuideTab::Systems;

        self.btn_enemies.update_hover(self.has_pointer && l.btn_enemies.contains(mx, my), dt, reduce_motion);
        self.btn_powerups.update_hover(self.has_pointer && l.btn_powerups.contains(mx, my), dt, reduce_motion);
        self.btn_basics.update_hover(self.has_pointer && l.btn_basics.contains(mx, my), dt, reduce_motion);
        self.btn_systems.update_hover(self.has_pointer && l.btn_systems.contains(mx, my), dt, reduce_motion);
        self.btn_prev.update_hover(self.has_pointer && l.btn_prev.contains(mx, my), dt, reduce_motion);
        self.btn_next.update_hover(self.has_pointer && l.btn_next.contains(mx, my), dt, reduce_motion);
        self.btn_back.update_hover(self.has_pointer && l.btn_back.contains(mx, my), dt, reduce_motion);
    }

    pub fn on_mouse_move(&mut self, x: f32, y: f32) {
        self.hovered_pos = [x, y];
        self.has_pointer = true;
    }

    pub fn on_mouse_press(&mut self, x: f32, y: f32, view_w: u32, view_h: u32, colorblind: bool) -> GuideAction {
        let l = self.layout(view_w, view_h);
        if l.btn_back.contains(x, y) {
            return GuideAction::Back;
        }
        if l.btn_enemies.contains(x, y) {
            self.tab = GuideTab::Enemies;
            self.page = 0;
        } else if l.btn_powerups.contains(x, y) {
            self.tab = GuideTab::Powerups;
            self.page = 0;
        } else if l.btn_basics.contains(x, y) {
            self.tab = GuideTab::Basics;
            self.page = 0;
        } else if l.btn_systems.contains(x, y) {
            self.tab = GuideTab::Systems;
            self.page = 0;
        } else if l.btn_prev.contains(x, y) {
            let pages = self.total_pages(l.rows_per_page, colorblind);
            self.page = ((self.page as isize) - 1).rem_euclid(pages as isize) as usize;
        } else if l.btn_next.contains(x, y) {
            let pages = self.total_pages(l.rows_per_page, colorblind);
            self.page = ((self.page as isize) + 1).rem_euclid(pages as isize) as usize;
        }
        GuideAction::None
    }

    pub fn on_key(&mut self, page_delta: isize, tab_step: bool, back: bool, view_w: u32, view_h: u32, colorblind: bool) -> GuideAction {
        if back {
            return GuideAction::Back;
        }
        if tab_step {
            self.tab = match self.tab {
                GuideTab::Enemies => GuideTab::Powerups,
                GuideTab::Powerups => GuideTab::Basics,
                GuideTab::Basics => GuideTab::Systems,
                GuideTab::Systems => GuideTab::Enemies,
            };
            self.page = 0;
            return GuideAction::None;
        }
        if page_delta != 0 {
            let l = self.layout(view_w, view_h);
            let pages = self.total_pages(l.rows_per_page, colorblind);
            self.page = ((self.page as isize) + page_delta).rem_euclid(pages as isize) as usize;
        }
        GuideAction::None
    }

    fn entries(&self, colorblind: bool) -> Vec<GuideEntry> {
        match self.tab {
            GuideTab::Enemies => Self::enemy_entries(colorblind),
            GuideTab::Powerups => Self::powerup_entries(),
            GuideTab::Basics => Self::basics_entries(),
            GuideTab::Systems => Self::systems_entries(),
        }
    }

    fn total_pages(&self, per_page: usize, colorblind: bool) -> usize {
        let len = self.entries(colorblind).len();
        ((len + per_page - 1) / per_page.max(1)).max(1)
    }

    fn enemy_entries(cb: bool) -> Vec<GuideEntry> {
        let split_hp = (ELITE_SPLIT_HP_FRAC * 100.0).round() as i32;
        let rage_hp = (BOSS_RAGE_HP_FRAC * 100.0).round() as i32;
        let rage_cd = ((1.0 - BOSS_RAGE_COOLDOWN_MULT) * 100.0).round() as i32;
        let ward_dr = ((1.0 - ELITE_WARD_DAMAGE_MULT) * 100.0).round() as i32;
        let e = |key: &'static str, name: &str, icon: &'static str, what: &str, deal: &str, lore: &str| GuideEntry {
            key,
            name: name.to_string(),
            icon,
            what: what.to_string(),
            deal: deal.to_string(),
            lore: lore.to_string(),
            accent: enemy_color(key, cb),
        };
        vec![
            e("chaser", "Chaser", "C", "Presses close with evasive steps, then locks a heading and commits to a short lunge.", "Change direction after its lunge line locks; do not kite in a straight line.", "Always hungry for your thruster wake."),
            e("ranged", "Ranged", "R", "Holds a firing distance, marks a lane, releases a one- or two-shot burst, then relocates.", "Leave the marked lane before the first shot; cross back between burst shots.", "Locks a firing lane before slipping back."),
            e("sniper", "Sniper", "SN", "Keeps long range, dodges while repositioning, then locks and fires a high-damage laser lane.", "Break the line during the bright windup; move across the committed beam after the lock settles.", "A patient scope with a single, punishing answer."),
            e("bomber", "Bomber", "B", "Predicts a floor landing point, marks its blast area, then throws a slow-fuse bomb at that point.", "Leave the amber blast ring before detonation, then punish the Bomber while it reloads.", "Loads unstable cores and drops them in traffic."),
            e("tank", "Tank", "T", "A slow armored hull that briefly pushes faster at close range. It marks a long cannon lane before firing and bursts on death.", "Cross the marked cannon lane before the shot; keep clear when the Tank is about to be destroyed.", "Built to outlast lighter escorts."),
            e("charger", "Charger", "CH", "Repositions to charge distance, locks a heading, then commits to a fast straight-line attack before recovering.", "Wait for its lane to lock, then sidestep across it instead of running along the line.", "A coil-spring hull waiting to snap forward."),
            e("swarm", "Swarmer", "SW", "Three spawn-keyed packs cycle through encircle, a short surge tell, a committed dive, and regroup.", "Keep an exit route through the ring; use each regroup lull to thin the pack.", "One fighter is harmless; coordinated entry closes routes."),
            e("egg_sac", "Egg Sac", "EG", "Stationary nest hatches up to three Swarmers after its 4s timer, if the arena spawn cap allows.", "Destroy the sac before the timer expires; the cap can limit how many hatch.", "An unattended nest converts time into pressure."),
            e("spitter", "Spitter", "SP", "Strafes, marks the center of its aim, then alternates a narrow three-shot volley and a wider four-shot fan.", "Watch its bright center line, then move across the fan as it opens.", "Alternating scatter keeps careless pods pinned."),
            e("flyer", "Flyer", "FL", "Circles at close range, marks a destination, then commits to a fast cross-lane dash.", "Change direction after its destination locks; spread fire along its committed path.", "Wings tuned for tight arena banks."),
            e("engineer", "Engineer", "EN", "Plants delayed mines and periodically grants up to 8 shield to the lowest-shield nearby regular ally.", "Leave the mine marker before it arms and focus the Engineer before its next support pulse.", "A fabricator that turns time into mines and allied shields."),
            e("boss_thunder", "Boss: Storm Sovereign", "SS", "Teleports, charges a marked radial volley, and paints lightning lanes. Later phases interlace a second ring.", "Move during the vanish, then cross the lit spokes before the slower second ring arrives.", "A storm that turns every pause into a target."),
            e("boss_laser", "Boss: Prisma Overlord", "PO", "Locks your direction during its charge, then sweeps continuous purple beams across that arc; later phases widen the sweep, add beams, and close with a marked plasma fan.", "Change direction while the arc is marked, then move across the sweep instead of racing along it.", "Its charge shows the full danger arc before the sweep begins."),
            e("boss_trapmaster", "Boss: Forge Warden", "FW", "Marks a predicted patch with a ring of spikes, then fires an aimed spread; later phases widen the fan and can add crossfire.", "Change heading or dash before the spike marks trigger, then keep an escape lane open for the fan.", "It attacks the space you plan to occupy."),
            e("boss_swarmqueen", "Boss: Brood Matriarch", "BM", "Alternates egg-sac and Swarmer summons with broad plasma fans.", "Destroy sacs before they hatch; strafe the fan and clear summoned Swarmer packs during recovery.", "Every ignored egg becomes another problem."),
            e("boss_brute", "Boss: Gorgon Juggernaut", "GJ", "Locks a charge lane, then erupts into a radial projectile ring on wall impact.", "In its final phase, watch for the delayed blue cross-lanes and cross between them.", "Every wall strike turns the arena into a second weapon."),
            e("boss_abyss_gaze", "Boss: Ocular Abyss", "OA", "Its combat persona changes orbit direction, preferred range, and the spacing of its paired laser lanes.", "Watch its orbit and distance; cross each marked lane after the warning and clear escorts when safe.", "It predicts where your ship is already going."),
            e("boss_womb_core", "Boss: Origin Nexus", "ON", "Its combat persona marks your position, a point ahead of the boss, or predicts your movement for a delayed pulse.", "Leave the marked circle; if it leads your path, change direction before it arms, then cross the projectile fan through a gap.", "The arena itself becomes part of its attack."),
            e("boss_eclipse_archon", "Boss: Eclipse Archon", "EA", "Orbits, charges, then fires staggered radial bursts with a shifting safe gap.", "Aim for the opening in the first burst and move with it as later volleys rotate.", "The escape dash means the next volley starts from a new angle."),
            GuideEntry {
                key: "boss_personas",
                name: "Boss Combat Personas".to_string(),
                icon: "AI",
                what: "AGGRESSIVE bosses favor quick pressure; CAUTIOUS bosses may hold more range or use broader lanes; TRICKSTER bosses may shift orbit or lead your path. Each hull combines these traits differently.".to_string(),
                deal: "Read the persona above the boss health bar. Change direction against a leading pulse and watch the boss's movement before committing to a lane.".to_string(),
                lore: "The same war machine can fight with a different instinct.".to_string(),
                accent: [190, 150, 255],
            },
            GuideEntry {
                key: "volatile",
                name: "Elite: Volatile".to_string(),
                icon: "VO",
                what: format!("Detonates on death within {ELITE_VOLATILE_BLAST_RADIUS:.0} units, dealing {ELITE_VOLATILE_BLAST_DAMAGE} to nearby enemies and 20 to you."),
                deal: "Finish it from range and leave its blast circle before the final hit.".to_string(),
                lore: "A cracked reactor with a very short fuse.".to_string(),
                accent: elite_affix_color("volatile"),
            },
            GuideEntry {
                key: "swift",
                name: "Elite: Swift".to_string(),
                icon: "SW",
                what: format!("Moves {:.0}% faster than its base type.", (ELITE_SWIFT_SPEED_MULT - 1.0) * 100.0),
                deal: "Lead your shots, keep moving, and dash if it cuts off your lane.".to_string(),
                lore: "Overclocked thrusters leave a bright cyan wake.".to_string(),
                accent: elite_affix_color("swift"),
            },
            GuideEntry {
                key: "shielded",
                name: "Elite: Shielded".to_string(),
                icon: "SH",
                what: format!("Starts with a shield equal to {:.0}% of its hull.", ELITE_SHIELDED_HP_FRAC * 100.0),
                deal: "Break through the blue shield before spending your heavier attacks.".to_string(),
                lore: "A portable barrier layered over an upgraded frame.".to_string(),
                accent: elite_affix_color("shielded"),
            },
            GuideEntry {
                key: "splitter",
                name: "Elite: Splitter".to_string(),
                icon: "SL",
                what: format!("On death splits into {ELITE_SPLIT_COUNT} copies at {split_hp}% HP each."),
                deal: "Clear the halves fast; they never split again.".to_string(),
                lore: "Fragments of the same frame, one generation deep.".to_string(),
                accent: elite_affix_color("splitter"),
            },
            GuideEntry {
                key: "reflector",
                name: "Elite: Reflector".to_string(),
                icon: "RF",
                what: format!("Every {ELITE_REFLECT_COOLDOWN:.0}s intercepts a direct shot, flashes a 0.16s bounce line, and fires back a capped bolt."),
                deal: "Watch its flash, then leave the bounce line.".to_string(),
                lore: "It turns your own damage back on you.".to_string(),
                accent: elite_affix_color("reflector"),
            },
            GuideEntry {
                key: "mender",
                name: "Elite: Mender".to_string(),
                icon: "MD",
                what: format!("Heals up to 2 lowest-HP allies for {ELITE_MENDER_HEAL} + 12% max HP every {ELITE_MENDER_INTERVAL:.1}s within {ELITE_MENDER_RADIUS:.0} units and clear sight."),
                deal: "Focus it before its green tether pulse restores nearby allies.".to_string(),
                lore: "A salvage rig repurposed into a battlefield medic.".to_string(),
                accent: elite_affix_color("mender"),
            },
            GuideEntry {
                key: "warden",
                name: "Elite: Warden".to_string(),
                icon: "WD",
                what: format!("Protects nearby allies from {ward_dr}% of incoming damage within {ELITE_WARD_RADIUS:.0} units; it does not shield itself."),
                deal: "Focus the exposed Warden before spending heavy shots on guarded allies.".to_string(),
                lore: "A shield lattice that turns nearby hulls into a formation.".to_string(),
                accent: elite_affix_color("warden"),
            },
            GuideEntry {
                key: "boss_rage",
                name: "Boss Rage".to_string(),
                icon: "RG",
                what: format!("At {rage_hp}% HP: cooldowns shrink {rage_cd}%, +{BOSS_RAGE_EXTRA_PROJECTILES} shot per volley."),
                deal: "Save a dash or defensive ability for the faster final pattern; keep moving until the opening returns.".to_string(),
                lore: format!("Rage begins at {rage_hp}% health and makes every boss attack more urgent."),
                accent: [255, 95, 110],
            },
        ]
    }

    fn powerup_entries() -> Vec<GuideEntry> {
        crate::render::powerup_art::POWERUP_CATALOG
            .iter()
            .map(|m| GuideEntry {
                key: m.key,
                name: format!("{} ({})", m.name, m.short_code),
                icon: m.short_code,
                what: format!("[{}] {}", crate::render::powerup_art::tier_label(m.tier), m.what),
                deal: crate::sim::powerup::powerup_timing_description(m.key)
                    .map(|timing| format!("{} {}", m.deal, timing))
                    .unwrap_or_else(|| m.deal.to_string()),
                lore: m.lore.to_string(),
                accent: powerup_color(m.key),
            })
            .collect()
    }

    fn basics_entries() -> Vec<GuideEntry> {
        vec![
            GuideEntry {
                key: "move",
                name: "Movement & Dash (WASD / Left Stick + Space / A)".to_string(),
                icon: "MV",
                what: "WASD, Arrow keys or the left stick steer your pod; Space or the A button triggers an i-frame dash with brief invincible dodge.".to_string(),
                deal: "Dash across enemy volleys or Brute telegraph lanes cleanly.".to_string(),
                lore: "Inertia stays crisp unless Drift mutator is active.".to_string(),
                accent: ACCENT,
            },
            GuideEntry {
                key: "boost",
                name: "Afterburner Boost (Shift) & Ultra (Q / RMB)".to_string(),
                icon: "BS",
                what: "Hold Shift to blaze faster and take 35% less damage. Q or Right-Click unleashes skin-tuned Ultra.".to_string(),
                deal: "Conserve boost fuel for emergencies; Ultra clears thick screens.".to_string(),
                lore: "Three Ultra variants cycle by weapon class: Beam, Nova, and Barrage.".to_string(),
                accent: GOLD,
            },
            GuideEntry {
                key: "combo",
                name: "Combo Meter & Waves".to_string(),
                icon: "CB",
                what: "Rapid kills build Combo to 8x; the wave HUD names the enemy types in each mix. New roles arrive in stages, and bosses appear every 5th wave.".to_string(),
                deal: "Read the enemy names under the wave number to learn each threat before later combinations. Boss clears grant Temp Boon + Perm Upgrade cards.".to_string(),
                lore: "Achievements come from kills, bosses, dashes, arenas and more. Some are secret. They also unlock Hangar skins.".to_string(),
                accent: SUCCESS,
            },
        ]
    }

    fn systems_entries() -> Vec<GuideEntry> {
        let mut out = vec![
            GuideEntry {
                key: "hangar",
                name: format!("Hangar ({} Skins, {} Achievements)", SKINS.len(), ACHIEVEMENTS.len()),
                icon: "HG",
                what: format!("Unlock {} pod skins via Wave, Score, Kill, Boss, or Achievement milestones.", SKINS.len()),
                deal: "Equips recolor your pod, antenna, glow trail, and projectile palette.".to_string(),
                lore: "Unlocked milestones save automatically after every run.".to_string(),
                accent: ACCENT,
            },
            GuideEntry {
                key: "daily",
                name: "Daily Challenge".to_string(),
                icon: "DY",
                what: "One fixed UTC date, seed, Normal difficulty, Circle arena, and mutator for everyone. Regular-run difficulty, arena, and mutator choices do not change the challenge; the arena view scales to your screen shape.".to_string(),
                deal: "The daily mutator's score bonus is shown beside its name. Your personal record is saved per UTC date: higher score wins, then furthest wave breaks a tie.".to_string(),
                lore: "Press Daily Challenge on the title screen to launch the shared UTC challenge. Auto-fire and accessibility settings remain yours to choose.".to_string(),
                accent: [150, 150, 255],
            },
            GuideEntry {
                key: "arena_shapes",
                name: "Open Arena Shapes".to_string(),
                icon: "AR",
                what: "Choose Circle, Donut, Cross, or Diamond boundaries. New runs use open arenas without cover objects or projectile-blocking obstacles.".to_string(),
                deal: "Read each boundary shape to route around charges and keep moving through incoming fire.".to_string(),
                lore: "The arena outline defines the combat lanes; no interior cover blocks a clear shot.".to_string(),
                accent: [105, 205, 230],
            },
            GuideEntry {
                key: "run_relics",
                name: "Boss Relics".to_string(),
                icon: "RL",
                what: "Boss rewards can grant one-of-a-kind relics: Graviton Charm pulls salvage from farther away, Soul Rivet repairs 4 hull after a wave, Phase Shard damages nearby enemies when a dash ends, and Aegis Relay restores up to 14 shield when Ultra fires.".to_string(),
                deal: "Relics stay active for the rest of the run and appear in the HUD status line.".to_string(),
                lore: "Choose a relic to steer your build, then adapt your route and dodges around it.".to_string(),
                accent: [194, 132, 255],
            },
            GuideEntry {
                key: "events",
                name: "Arena Events (Meteor / Nebula / Solar Flare)".to_string(),
                icon: "EV",
                what: "Meteor impacts and Solar Flares damage enemies as well as your pod; Nebula shields nearby enemies.".to_string(),
                deal: "Frontliners keep pressing while ranged enemies may dodge a marked impact; leave before the flare sweep reaches you.".to_string(),
                lore: "Nebula cover favors enemy packs; meteor craters and flare lanes can break them apart.".to_string(),
                accent: [255, 175, 90],
            },
        ];
        for m in MUTATORS {
            out.push(GuideEntry {
                key: m.id,
                name: format!("Mutator: {} ({})", m.name, format_score_mult(m.score_mult)),
                icon: "MT",
                what: m.description.to_string(),
                deal: format!("Combines multiplicatively with other mutators for {} score bonus.", format_score_mult(m.score_mult)),
                lore: "Toggle any combination on the Main Menu before hitting Play.".to_string(),
                accent: GOLD,
            });
        }
        out
    }

    fn layout(&self, view_w: u32, view_h: u32) -> GuideLayout {
        let w = view_w as f32;
        let h = view_h as f32;
        let s = ui_scale(view_w, view_h).min(1.25);
        let cx = w * 0.5;
        let panel_w = (w * 0.94).min(1220.0 * s);
        let panel_h = (h * 0.84).min(760.0 * s).max(260.0);
        let panel_x = cx - panel_w * 0.5;
        let panel_y = (20.0 * s).max((h - panel_h) * 0.5 - 24.0 * s);
        let panel = UiRect::new(panel_x, panel_y, panel_w, panel_h);

        let top_y = panel_y + panel_h - 82.0 * s;
        let tab_w = 136.0 * s;
        let tab_h = 46.0 * s;
        let tab_gap = 10.0 * s;
        let tx = panel_x + 24.0 * s;
        let btn_enemies = UiRect::new(tx, top_y, tab_w, tab_h);
        let btn_powerups = UiRect::new(tx + (tab_w + tab_gap), top_y, tab_w, tab_h);
        let btn_basics = UiRect::new(tx + 2.0 * (tab_w + tab_gap), top_y, tab_w, tab_h);
        let btn_systems = UiRect::new(tx + 3.0 * (tab_w + tab_gap), top_y, tab_w, tab_h);

        let back_w = 170.0 * s;
        let btn_back = UiRect::new(panel_x + panel_w - back_w - 24.0 * s, top_y, back_w, tab_h);

        let row_top = top_y - 22.0 * s;
        let row_h = 86.0 * s;
        let row_gap = 10.0 * s;
        let nav_top = panel_y + 72.0 * s;
        let rows_per_page = (((row_top - nav_top + row_gap) / (row_h + row_gap)).floor() as usize).clamp(1, 5);

        let btn_prev = UiRect::new(panel_x + 24.0 * s, panel_y + 14.0 * s, 118.0 * s, 42.0 * s);
        let btn_next = UiRect::new(btn_prev.x + btn_prev.w + 12.0 * s, btn_prev.y, 118.0 * s, 42.0 * s);

        GuideLayout {
            s,
            cx,
            panel,
            btn_enemies,
            btn_powerups,
            btn_basics,
            btn_systems,
            btn_prev,
            btn_next,
            btn_back,
            row_top,
            row_h,
            row_gap,
            rows_per_page,
        }
    }

    pub fn draw(
        &self,
        ui_alpha: &mut SdfBatch,
        ui_add: &mut SdfBatch,
        ui_text: &mut TextBatch,
        fonts: &FontPack,
        view_w: u32,
        view_h: u32,
        colorblind: bool,
    ) {
        let l = self.layout(view_w, view_h);
        let s = l.s;
        let w = view_w as f32;
        let h = view_h as f32;

        ui_alpha.panel(0.0, 0.0, w, h, 0.0, linear_rgba(BACKGROUND, 195, 1.0));
        ui_text.draw_hdr(
            "FIELD GUIDE",
            FontId::Head,
            pt_px(28.0, s, 18.0),
            l.cx,
            h - 42.0 * s,
            AlignX::Center,
            AlignY::Center,
            TEXT,
            1.0,
            true,
        );
        let sub = match self.tab {
            GuideTab::Enemies => "Enemy dossiers, threat cues, and fast counterplay.",
            GuideTab::Powerups => "Powerup effects, timing advice, and field notes.",
            GuideTab::Basics => "Core controls, movement rules, and run-flow fundamentals.",
            GuideTab::Systems => "Hangar, achievements, mutators, daily runs, arena terrain, and events.",
        };
        ui_text.draw(
            sub,
            FontId::Regular,
            pt_px(12.0, s, 9.5),
            l.cx,
            h - 74.0 * s,
            AlignX::Center,
            AlignY::Center,
            MUTED,
            235,
            true,
        );

        draw_panel(ui_alpha, l.panel, 10.0 * s, 1.8, PANEL, 215, ACCENT, 75, 6.0 * s);

        let tab_px = pt_px(14.0, s, 10.5);
        draw_button(ui_alpha, ui_text, l.btn_enemies, &self.btn_enemies, tab_px, s);
        draw_button(ui_alpha, ui_text, l.btn_powerups, &self.btn_powerups, tab_px, s);
        draw_button(ui_alpha, ui_text, l.btn_basics, &self.btn_basics, tab_px, s);
        draw_button(ui_alpha, ui_text, l.btn_systems, &self.btn_systems, tab_px, s);
        draw_button(ui_alpha, ui_text, l.btn_back, &self.btn_back, tab_px, s);

        let entries = self.entries(colorblind);
        let total_pages = ((entries.len() + l.rows_per_page - 1) / l.rows_per_page).max(1);
        let page = self.page.min(total_pages - 1);
        let start = page * l.rows_per_page;
        let end = (start + l.rows_per_page).min(entries.len());

        let row_x = l.panel.x + 24.0 * s;
        let row_w = l.panel.w - 48.0 * s;
        for (i, entry) in entries[start..end].iter().enumerate() {
            let y = l.row_top - ((i + 1) as f32) * l.row_h - (i as f32) * l.row_gap;
            let r = UiRect::new(row_x, y, row_w, l.row_h);
            let pulse = 0.5 + 0.5 * (self.t * 2.5 + (i as f32) * 1.1).sin();

            draw_panel(
                ui_alpha,
                r,
                7.0 * s,
                1.3,
                mix_rgb(PANEL, [26, 44, 68], 0.45),
                205,
                entry.accent,
                (90.0 + 50.0 * pulse) as u8,
                2.0 * s,
            );
            ui_alpha.panel(
                row_x,
                y,
                (5.0 * s).max(4.0),
                l.row_h,
                2.0,
                linear_rgba(entry.accent, 235, 1.0),
            );

            let icon_x = row_x + 30.0 * s;
            let icon_y = y + l.row_h * 0.5;
            if self.tab == GuideTab::Powerups {
                crate::render::powerup_art::draw_powerup_emblem(
                    entry.key,
                    icon_x,
                    icon_y,
                    14.5 * s,
                    entry.accent,
                    1.0,
                    self.t,
                    ui_alpha,
                    ui_add,
                );
            } else {
                let mut drew_3d = false;
                if self.tab == GuideTab::Enemies {
                    if is_guide_enemy_model(entry.key) {
                        let heading = -std::f32::consts::FRAC_PI_4
                            + (self.t * 0.55 + i as f32 * 0.6).sin() * 0.28;
                        let facing = crate::sim::math::Vec2::new(heading.cos(), heading.sin());
                        if is_guide_boss_model(entry.key) {
                            ui_alpha.circle(
                                icon_x,
                                icon_y,
                                21.0 * s,
                                linear_rgba([12, 22, 38], 245, 1.0),
                            );
                            if let Some(model_scale) = crate::render::models3d::boss_model_preview_fit_scale(
                                entry.key,
                                17.0 * s,
                            ) {
                                drew_3d = draw_guide_model_preview(
                                    entry,
                                    ui_alpha,
                                    ui_add,
                                    [icon_x, icon_y - 2.0 * s],
                                    facing,
                                    model_scale,
                                    self.t,
                                    self.reduce_motion,
                                );
                            }
                        } else {
                            ui_alpha.circle(
                                icon_x,
                                icon_y,
                                20.0 * s,
                                linear_rgba([12, 22, 38], 245, 1.0),
                            );
                            if let Some(model_scale) = crate::render::models3d::enemy_model_preview_fit_scale(
                                entry.key,
                                17.0 * s,
                            ) {
                                drew_3d = draw_guide_model_preview(
                                    entry,
                                    ui_alpha,
                                    ui_add,
                                    [icon_x, icon_y - 1.5 * s],
                                    facing,
                                    model_scale,
                                    self.t,
                                    self.reduce_motion,
                                );
                            }
                        }
                    }
                }
                if !drew_3d {
                    ui_alpha.circle(icon_x, icon_y, 18.0 * s, linear_rgba([16, 30, 50], 245, 1.0));
                    ui_add.ring(
                        icon_x,
                        icon_y,
                        15.0 * s,
                        15.0 * s,
                        2.0,
                        linear_rgba(entry.accent, (140.0 + 70.0 * pulse) as u8, 1.3),
                    );
                    if self.tab == GuideTab::Enemies
                        && draw_enemy_guide_symbol(
                            entry.key,
                            icon_x,
                            icon_y,
                            s,
                            entry.accent,
                            ui_alpha,
                        )
                    {
                        // Extra enemy-guide entries use semantic symbols instead of letter codes.
                    } else {
                        ui_alpha.circle(icon_x, icon_y, 12.0 * s, linear_rgba(entry.accent, 225, 1.0));
                        ui_text.draw(
                            entry.icon,
                            FontId::Head,
                            pt_px(10.0, s, 8.5),
                            icon_x,
                            icon_y,
                            AlignX::Center,
                            AlignY::Center,
                            [255, 255, 255],
                            255,
                            true,
                        );
                    }
                }
            }

            let text_x = row_x + 60.0 * s;
            let max_tw = (row_w - 76.0 * s).max(120.0);
            ui_text.draw(
                &entry.name,
                FontId::Bold,
                pt_px(15.0, s, 11.0),
                text_x,
                y + l.row_h - 12.0 * s,
                AlignX::Left,
                AlignY::Top,
                TEXT,
                255,
                true,
            );
            let line1 = match self.tab {
                GuideTab::Systems => format!("About: {}  |  Tip: {}", entry.what, entry.deal),
                GuideTab::Powerups | GuideTab::Basics => {
                    format!("Effect: {}  |  Tip: {}", entry.what, entry.deal)
                }
                GuideTab::Enemies => format!("THREAT: {}", entry.what),
            };
            let p1 = pt_px(11.0, s, 9.0);
            ui_text.draw(
                fonts.fit_text(FontId::Regular, p1, &line1, max_tw),
                FontId::Regular,
                p1,
                text_x,
                y + l.row_h - 38.0 * s,
                AlignX::Left,
                AlignY::Top,
                [192, 208, 228],
                245,
                false,
            );
            let line2 = match self.tab {
                GuideTab::Enemies => format!("COUNTER: {}", entry.deal),
                _ => format!("Note: {}", entry.lore),
            };
            let p2 = pt_px(10.0, s, 8.5);
            ui_text.draw(
                fonts.fit_text(FontId::Regular, p2, &line2, max_tw),
                FontId::Regular,
                p2,
                text_x,
                y + l.row_h - 60.0 * s,
                AlignX::Left,
                AlignY::Top,
                if self.tab == GuideTab::Enemies { [204, 219, 238] } else { MUTED },
                if self.tab == GuideTab::Enemies { 245 } else { 220 },
                false,
            );
        }

        let nav_px = pt_px(13.0, s, 10.0);
        draw_button(ui_alpha, ui_text, l.btn_prev, &self.btn_prev, nav_px, s);
        draw_button(ui_alpha, ui_text, l.btn_next, &self.btn_next, nav_px, s);

        ui_text.draw(
            format!(
                "Page {}/{}   |   Left/Right to browse   |   {} entries",
                page + 1,
                total_pages,
                entries.len()
            ),
            FontId::Regular,
            pt_px(11.0, s, 9.0),
            l.cx + 70.0 * s,
            l.panel.y + 34.0 * s,
            AlignX::Center,
            AlignY::Center,
            MUTED,
            235,
            true,
        );
    }
}

struct GuideLayout {
    s: f32,
    cx: f32,
    panel: UiRect,
    btn_enemies: UiRect,
    btn_powerups: UiRect,
    btn_basics: UiRect,
    btn_systems: UiRect,
    btn_prev: UiRect,
    btn_next: UiRect,
    btn_back: UiRect,
    row_top: f32,
    row_h: f32,
    row_gap: f32,
    rows_per_page: usize,
}

// ---------------------------------------------------------------------------
// Pause Screen
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PauseAction {
    None,
    Resume,
    QuitToMenu,
}

pub struct PauseScreen {
    btn_resume: ButtonStyle,
    btn_quit: ButtonStyle,
    focus: usize,
    hovered_pos: [f32; 2],
    has_pointer: bool,
}

impl Default for PauseScreen {
    fn default() -> Self {
        Self::new()
    }
}

impl PauseScreen {
    pub fn new() -> Self {
        Self {
            btn_resume: ButtonStyle::new("Resume", [60, 145, 195], ACCENT),
            btn_quit: ButtonStyle::new("Main Menu", [145, 70, 88], [215, 100, 120]),
            focus: 0,
            hovered_pos: [0.0, 0.0],
            has_pointer: false,
        }
    }

    pub fn open(&mut self) {
        self.focus = 0;
    }

    pub fn update(&mut self, dt: f32, view_w: u32, view_h: u32, reduce_motion: bool) {
        let (r_res, r_quit, _) = Self::rects(view_w, view_h);
        let [mx, my] = self.hovered_pos;
        self.btn_resume.focused = self.focus == 0;
        self.btn_quit.focused = self.focus == 1;
        self.btn_resume.update_hover(self.has_pointer && r_res.contains(mx, my), dt, reduce_motion);
        self.btn_quit.update_hover(self.has_pointer && r_quit.contains(mx, my), dt, reduce_motion);
    }

    pub fn on_mouse_move(&mut self, x: f32, y: f32) {
        self.hovered_pos = [x, y];
        self.has_pointer = true;
    }

    pub fn on_mouse_press(&mut self, x: f32, y: f32, view_w: u32, view_h: u32) -> PauseAction {
        let (r_res, r_quit, _) = Self::rects(view_w, view_h);
        if r_res.contains(x, y) {
            return PauseAction::Resume;
        }
        if r_quit.contains(x, y) {
            return PauseAction::QuitToMenu;
        }
        PauseAction::None
    }

    pub fn on_key(&mut self, move_vert: isize, activate: bool, esc: bool) -> PauseAction {
        if esc {
            return PauseAction::Resume;
        }
        if move_vert != 0 {
            self.focus = if self.focus == 0 { 1 } else { 0 };
        }
        if activate {
            return if self.focus == 0 {
                PauseAction::Resume
            } else {
                PauseAction::QuitToMenu
            };
        }
        PauseAction::None
    }

    fn rects(view_w: u32, view_h: u32) -> (UiRect, UiRect, f32) {
        let s = ui_scale(view_w, view_h);
        let cx = (view_w as f32) * 0.5;
        let cy = (view_h as f32) * 0.48;
        let bw = 220.0 * s;
        let bh = 46.0 * s;
        let r_res = UiRect::new(cx - bw * 0.5, cy + 12.0 * s, bw, bh);
        let r_quit = UiRect::new(cx - bw * 0.5, cy - 48.0 * s, bw, bh);
        (r_res, r_quit, s)
    }

    pub fn draw(&self, ui_alpha: &mut SdfBatch, ui_text: &mut TextBatch, view_w: u32, view_h: u32) {
        let (r_res, r_quit, s) = Self::rects(view_w, view_h);
        let w = view_w as f32;
        let h = view_h as f32;
        ui_alpha.panel(0.0, 0.0, w, h, 0.0, linear_rgba([4, 8, 16], 188, 1.0));

        let panel_w = 340.0 * s;
        let panel_h = 220.0 * s;
        let p = UiRect::new(w * 0.5 - panel_w * 0.5, r_quit.y - 26.0 * s, panel_w, panel_h);
        draw_panel(ui_alpha, p, 12.0 * s, 1.8, PANEL, 230, ACCENT, 95, 8.0 * s);

        ui_text.draw_hdr(
            "PAUSED",
            FontId::Head,
            pt_px(28.0, s, 18.0),
            w * 0.5,
            r_res.y + r_res.h + 44.0 * s,
            AlignX::Center,
            AlignY::Center,
            TEXT,
            1.05,
            true,
        );

        let bpx = pt_px(15.5, s, 11.0);
        draw_button(ui_alpha, ui_text, r_res, &self.btn_resume, bpx, s);
        draw_button(ui_alpha, ui_text, r_quit, &self.btn_quit, bpx, s);

        ui_text.draw(
            "ESC resume  |  UP/DOWN + ENTER choose",
            FontId::Regular,
            pt_px(10.5, s, 8.5),
            w * 0.5,
            r_quit.y - 16.0 * s,
            AlignX::Center,
            AlignY::Center,
            MUTED,
            210,
            false,
        );
    }
}

// ---------------------------------------------------------------------------
// Boss Reward Selection Screen (2-step: Temp Boon -> Perm Upgrade)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BossRewardStep {
    TempBoon,
    PermUpgrade,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RewardCardEntry {
    pub key: &'static str,
    pub title: &'static str,
    pub desc: &'static str,
    pub duration: i32,
    pub tag: String,
    pub category: &'static str,
    pub accent: [u8; 3],
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BossRewardAction {
    None,
    TempPicked { key: &'static str, duration: i32 },
    PermPicked { key: &'static str },
}

pub struct BossRewardScreen {
    pub step: BossRewardStep,
    pub temp_cards: Vec<RewardCardEntry>,
    pub perm_cards: Vec<RewardCardEntry>,
    selected_idx: usize,
    hovered_idx: Option<usize>,
    lifts: [f32; 3],
    enters: [f32; 3],
    panel_enter: f32,
    t: f32,
    hovered_pos: [f32; 2],
    has_pointer: bool,
}

impl Default for BossRewardScreen {
    fn default() -> Self {
        Self::new()
    }
}

impl BossRewardScreen {
    pub fn new() -> Self {
        Self {
            step: BossRewardStep::TempBoon,
            temp_cards: Vec::new(),
            perm_cards: Vec::new(),
            selected_idx: 0,
            hovered_idx: None,
            lifts: [0.0; 3],
            enters: [0.0; 3],
            panel_enter: 0.0,
            t: 0.0,
            hovered_pos: [0.0, 0.0],
            has_pointer: false,
        }
    }

    pub fn open(&mut self, temps: &[&'static TempRewardDef], perms: &[&'static PermRewardDef]) {
        self.open_with_context(temps, perms, &[], &[]);
    }

    pub fn open_with_context(
        &mut self,
        temps: &[&'static TempRewardDef],
        perms: &[&'static PermRewardDef],
        active_temp: &[ActiveTempReward],
        run_perms: &[String],
    ) {
        self.step = BossRewardStep::TempBoon;
        self.temp_cards = temps
            .iter()
            .map(|r| {
                let cat = reward_category(r.key);
                let tag = active_temp
                    .iter()
                    .find(|active| active.key == r.key)
                    .map(|active| {
                        format!("ACTIVE {} → PICK {}", active.waves_left, active.waves_left.max(r.duration))
                    })
                    .unwrap_or_else(|| format!("{} WAVES", r.duration));
                RewardCardEntry {
                    key: r.key,
                    title: r.title,
                    desc: r.desc,
                    duration: r.duration,
                    tag,
                    category: cat,
                    accent: category_color(cat),
                }
            })
            .collect();
        self.perm_cards = perms
            .iter()
            .map(|r| {
                let cat = reward_category(r.key);
                let owned = run_perms.iter().filter(|key| key.as_str() == r.key).count();
                let tag = if cat == "RELIC" {
                    "NEW RELIC".to_string()
                } else if owned == 0 {
                    "NEW · STACKABLE".to_string()
                } else {
                    format!("STACK {owned} → {}", owned + 1)
                };
                RewardCardEntry {
                    key: r.key,
                    title: r.title,
                    desc: r.desc,
                    duration: 0,
                    tag,
                    category: cat,
                    accent: category_color(cat),
                }
            })
            .collect();
        self.reset_anim();
        // If no temp options exist (edge fallback), advance immediately
        if self.temp_cards.is_empty() && !self.perm_cards.is_empty() {
            self.step = BossRewardStep::PermUpgrade;
        }
    }

    fn reset_anim(&mut self) {
        self.selected_idx = 0;
        self.hovered_idx = None;
        self.lifts = [0.0; 3];
        self.enters = [0.0; 3];
        self.panel_enter = 0.0;
        self.t = 0.0;
    }

    pub fn active_cards(&self) -> &[RewardCardEntry] {
        match self.step {
            BossRewardStep::TempBoon => &self.temp_cards,
            BossRewardStep::PermUpgrade => &self.perm_cards,
        }
    }

    pub fn update(&mut self, dt: f32, view_w: u32, view_h: u32, reduce_motion: bool) {
        self.t += dt;
        if reduce_motion {
            self.panel_enter = 1.0;
            self.enters = [1.0; 3];
        } else {
            self.panel_enter = (self.t / 0.20).clamp(0.0, 1.0);
            for i in 0..3 {
                let delay = (i as f32) * 0.07;
                self.enters[i] = ((self.t - delay) / 0.22).clamp(0.0, 1.0);
            }
        }
        let rects = Self::card_rects(view_w, view_h, self.active_cards().len());
        self.hovered_idx = if self.has_pointer {
            rects.iter().position(|r| r.contains(self.hovered_pos[0], self.hovered_pos[1]))
        } else {
            None
        };
        for i in 0..3 {
            let target = if self.hovered_idx == Some(i) || self.selected_idx == i {
                1.0
            } else {
                0.0
            };
            if reduce_motion {
                self.lifts[i] = target;
            } else {
                let k = (dt * 14.0).clamp(0.0, 1.0);
                self.lifts[i] += (target - self.lifts[i]) * k;
            }
        }
    }

    pub fn on_mouse_move(&mut self, x: f32, y: f32) {
        self.hovered_pos = [x, y];
        self.has_pointer = true;
    }

    pub fn on_mouse_press(&mut self, x: f32, y: f32, view_w: u32, view_h: u32) -> BossRewardAction {
        let rects = Self::card_rects(view_w, view_h, self.active_cards().len());
        if let Some(idx) = rects.iter().position(|r| r.contains(x, y)) {
            return self.pick_index(idx);
        }
        BossRewardAction::None
    }

    pub fn on_key(&mut self, num_1_3: Option<usize>, dir_delta: isize, confirm: bool) -> BossRewardAction {
        let count = self.active_cards().len();
        if count == 0 {
            return BossRewardAction::None;
        }
        if let Some(idx) = num_1_3 {
            if idx < count {
                return self.pick_index(idx);
            }
        }
        if dir_delta != 0 {
            self.selected_idx = ((self.selected_idx as isize) + dir_delta).rem_euclid(count as isize) as usize;
        }
        if confirm {
            return self.pick_index(self.selected_idx);
        }
        BossRewardAction::None
    }

    pub fn pick_index(&mut self, idx: usize) -> BossRewardAction {
        match self.step {
            BossRewardStep::TempBoon => {
                let Some(card) = self.temp_cards.get(idx).cloned() else {
                    return BossRewardAction::None;
                };
                self.step = BossRewardStep::PermUpgrade;
                self.reset_anim();
                BossRewardAction::TempPicked {
                    key: card.key,
                    duration: card.duration,
                }
            }
            BossRewardStep::PermUpgrade => {
                let Some(card) = self.perm_cards.get(idx).cloned() else {
                    return BossRewardAction::None;
                };
                BossRewardAction::PermPicked { key: card.key }
            }
        }
    }

    fn card_rects(view_w: u32, view_h: u32, count: usize) -> Vec<UiRect> {
        let s = ui_scale(view_w, view_h).min(1.30);
        let w = view_w as f32;
        let h = view_h as f32;
        let panel_w = (w * 0.86).min(760.0 * s);
        let card_h = 96.0 * s;
        let card_gap = 12.0 * s;
        let total_cards_h = (count as f32) * card_h + (count.saturating_sub(1) as f32) * card_gap;
        let start_top = h * 0.5 + total_cards_h * 0.5 - 12.0 * s;
        let card_x = (w - (panel_w - 44.0 * s)) * 0.5;
        let card_w = panel_w - 44.0 * s;
        (0..count)
            .map(|i| {
                let y = start_top - ((i + 1) as f32) * card_h - (i as f32) * card_gap;
                UiRect::new(card_x, y, card_w, card_h)
            })
            .collect()
    }

    pub fn draw(
        &self,
        ui_alpha: &mut SdfBatch,
        ui_add: &mut SdfBatch,
        ui_text: &mut TextBatch,
        fonts: &FontPack,
        view_w: u32,
        view_h: u32,
        reduce_motion: bool,
    ) {
        let w = view_w as f32;
        let h = view_h as f32;
        let s = ui_scale(view_w, view_h).min(1.30);
        let pa = self.panel_enter;
        let panel_dy = if reduce_motion { 0.0 } else { -(1.0 - pa) * 16.0 * s };

        ui_alpha.panel(0.0, 0.0, w, h, 0.0, linear_rgba([4, 8, 16], (196.0 * pa) as u8, 1.0));

        let cards = self.active_cards();
        let rects = Self::card_rects(view_w, view_h, cards.len());
        let panel_w = (w * 0.86).min(760.0 * s);
        let top_y = rects.first().map(|r| r.y + r.h).unwrap_or(h * 0.55) + 92.0 * s;
        let bot_y = rects.last().map(|r| r.y).unwrap_or(h * 0.40) - 46.0 * s;
        let panel = UiRect::new((w - panel_w) * 0.5, bot_y + panel_dy, panel_w, (top_y - bot_y).max(200.0));

        draw_panel(
            ui_alpha,
            panel,
            12.0 * s,
            1.8,
            PANEL,
            (225.0 * pa) as u8,
            ACCENT,
            (110.0 * pa) as u8,
            10.0 * s,
        );

        let (title, sub) = match self.step {
            BossRewardStep::TempBoon => (
                "STEP 1 / 2 · CHOOSE A TEMPORARY BOON",
                "Press [1], [2], [3] or click a card — lasts multiple waves",
            ),
            BossRewardStep::PermUpgrade => (
                "STEP 2 / 2 · CHOOSE A RUN UPGRADE OR RELIC",
                "Press [1], [2], [3] or click a card — permanent for this run",
            ),
        };
        ui_text.draw_hdr(
            title,
            FontId::Head,
            pt_px(18.5, s, 13.0),
            w * 0.5,
            top_y + panel_dy - 26.0 * s,
            AlignX::Center,
            AlignY::Center,
            GOLD,
            1.05 * pa,
            true,
        );
        ui_text.draw(
            sub,
            FontId::Regular,
            pt_px(11.0, s, 9.0),
            w * 0.5,
            top_y + panel_dy - 54.0 * s,
            AlignX::Center,
            AlignY::Center,
            MUTED,
            (235.0 * pa) as u8,
            true,
        );

        for (i, (card, rect)) in cards.iter().zip(rects.iter()).enumerate() {
            let ea = (pa * self.enters[i.min(2)]).clamp(0.0, 1.0);
            if ea <= 0.01 {
                continue;
            }
            let lift = self.lifts[i.min(2)];
            let card_dy = if reduce_motion {
                0.0
            } else {
                (-(1.0 - self.enters[i.min(2)]) * 18.0 + 4.0 * lift) * s
            };
            let r = UiRect::new(rect.x, rect.y + panel_dy + card_dy, rect.w, rect.h);

            if lift > 0.05 {
                ui_add.panel_outline(
                    r.x - 3.0,
                    r.y - 3.0,
                    r.w + 6.0,
                    r.h + 6.0,
                    10.0 * s,
                    2.6,
                    linear_rgba_f(card.accent, 0.55 * lift * ea, 1.35),
                );
            }

            let fill = mix_rgb([16, 22, 34], card.accent, 0.08 + 0.14 * lift);
            let border = mix_rgb([80, 96, 128], card.accent, 0.45 + 0.55 * lift);
            draw_panel(
                ui_alpha,
                r,
                8.0 * s,
                1.8,
                fill,
                (236.0 * ea) as u8,
                border,
                ((110.0 + 135.0 * lift) * ea) as u8,
                4.0 * s,
            );
            // Category left stripe
            ui_alpha.panel(
                r.x,
                r.y,
                (6.0 * s).max(4.0),
                r.h,
                2.0,
                linear_rgba_f(card.accent, ea, 1.0),
            );

            // Key badge [1]/[2]/[3]
            let bs = 30.0 * s;
            let bx = r.x + 18.0 * s;
            let by = r.y + (r.h - bs) * 0.5;
            ui_alpha.panel(bx, by, bs, bs, 6.0 * s, linear_rgba_f(card.accent, ea * 0.9, 1.0));
            ui_text.draw(
                format!("{}", i + 1),
                FontId::Head,
                pt_px(14.0, s, 10.5),
                bx + bs * 0.5,
                by + bs * 0.5,
                AlignX::Center,
                AlignY::Center,
                [10, 14, 22],
                (255.0 * ea) as u8,
                false,
            );

            let text_x = bx + bs + 14.0 * s;
            let max_desc_w = (r.w - (text_x - r.x) - 120.0 * s).max(120.0);
            ui_text.draw(
                card.title,
                FontId::Bold,
                pt_px(16.5, s, 12.0),
                text_x,
                r.y + r.h * 0.66,
                AlignX::Left,
                AlignY::Center,
                TEXT,
                (255.0 * ea) as u8,
                true,
            );
            let d_px = pt_px(12.0, s, 9.5);
            ui_text.draw(
                fonts.fit_text(FontId::Regular, d_px, card.desc, max_desc_w),
                FontId::Regular,
                d_px,
                text_x,
                r.y + r.h * 0.30,
                AlignX::Left,
                AlignY::Center,
                [195, 212, 232],
                (245.0 * ea) as u8,
                false,
            );

            // Category + Tag right column
            ui_text.draw(
                card.category,
                FontId::Bold,
                pt_px(10.5, s, 8.5),
                r.x + r.w - 18.0 * s,
                r.y + r.h * 0.68,
                AlignX::Right,
                AlignY::Center,
                card.accent,
                (255.0 * ea) as u8,
                true,
            );
            ui_text.draw(
                card.tag.as_str(),
                FontId::Regular,
                pt_px(9.5, s, 8.0),
                r.x + r.w - 18.0 * s,
                r.y + r.h * 0.32,
                AlignX::Right,
                AlignY::Center,
                MUTED,
                (220.0 * ea) as u8,
                false,
            );
        }

        ui_text.draw(
            "LEFT/RIGHT choose · ENTER confirm · ESC skips nothing until card selected",
            FontId::Regular,
            pt_px(10.0, s, 8.5),
            w * 0.5,
            bot_y + panel_dy + 18.0 * s,
            AlignX::Center,
            AlignY::Center,
            MUTED,
            (215.0 * pa) as u8,
            false,
        );
    }
}

// ---------------------------------------------------------------------------
// Game Over Screen (Staged Cinematic Reveal + Held-Key Guard)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GameOverAction {
    None,
    Retry,
    QuitToMenu,
}

pub struct GameOverScreen {
    pub score: i32,
    pub wave: i32,
    pub survived_s: f32,
    pub kills: i32,
    pub best_combo: f32,
    pub is_new_high: bool,
    pub rank: usize,
    pub points_to_next: Option<i32>,
    pub mutator_summary: String,
    pub daily_summary: String,
    pub daily_is_best: bool,
    /// Names of achievements unlocked by this run.
    pub achievements: Vec<String>,
    /// Lines for the closest locked achievements, e.g. "Duke of Dash: 80 / 100".
    pub near: Vec<String>,

    reveal_t: f32,
    reveal_total: f32,
    key_guard_released: bool,
    btn_retry: ButtonStyle,
    btn_menu: ButtonStyle,
    hovered_pos: [f32; 2],
    has_pointer: bool,
}

impl Default for GameOverScreen {
    fn default() -> Self {
        Self::new()
    }
}

impl GameOverScreen {
    pub fn new() -> Self {
        Self {
            score: 0,
            wave: 1,
            survived_s: 0.0,
            kills: 0,
            best_combo: 1.0,
            is_new_high: false,
            rank: 0,
            points_to_next: None,
            mutator_summary: String::new(),
            daily_summary: String::new(),
            daily_is_best: false,
            achievements: Vec::new(),
            near: Vec::new(),
            reveal_t: 0.0,
            reveal_total: GAME_OVER_REVEAL_S.max(0.5),
            key_guard_released: false,
            btn_retry: ButtonStyle::new("Try Again", [65, 165, 115], [95, 225, 155]),
            btn_menu: ButtonStyle::new("Main Menu", [90, 115, 155], ACCENT),
            hovered_pos: [0.0, 0.0],
            has_pointer: false,
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub fn open(
        &mut self,
        score: i32,
        wave: i32,
        survived_s: f32,
        kills: i32,
        best_combo: f32,
        outcome: &SubmitOutcome,
        mutator_ids: &[String],
        daily_result: Option<&DailyResult>,
        unlocked: &[String],
        near: &[String],
        any_confirm_held: bool,
    ) {
        self.achievements = unlocked.to_vec();
        self.near = near.to_vec();
        self.score = score;
        self.wave = wave;
        self.survived_s = survived_s;
        self.kills = kills;
        self.best_combo = best_combo;
        self.is_new_high = outcome.is_new_best;
        self.rank = outcome.rank;
        self.points_to_next = outcome.points_to_next;
        self.reveal_t = 0.0;
        self.reveal_total = GAME_OVER_REVEAL_S.max(0.5);
        self.key_guard_released = !any_confirm_held;

        let names = mutator_names(mutator_ids);
        let mult = combined_score_multiplier(mutator_ids);
        let listed = if names.is_empty() {
            "none".to_string()
        } else {
            names.join(", ")
        };
        self.mutator_summary = format!("Mutators: {listed}   |   score {}", format_score_mult(mult));

        match daily_result {
            None => {
                self.daily_summary.clear();
                self.daily_is_best = false;
            }
            Some(dr) if dr.new_best => {
                self.daily_summary = format!(
                    "DAILY {}: NEW DAILY BEST {} (wave {})",
                    dr.date_iso,
                    format_score_commas(dr.best_score),
                    dr.best_wave
                );
                self.daily_is_best = true;
            }
            Some(dr) => {
                self.daily_summary = format!(
                    "DAILY {}: today's best {} (wave {}). This run ({}) did not beat it.",
                    dr.date_iso,
                    format_score_commas(dr.best_score),
                    dr.best_wave,
                    format_score_commas(dr.run_score)
                );
                self.daily_is_best = false;
            }
        }
    }

    pub fn update(&mut self, dt: f32, view_w: u32, view_h: u32, any_confirm_held: bool, reduce_motion: bool) {
        self.reveal_t += dt;
        if !any_confirm_held {
            self.key_guard_released = true;
        }
        let (r_retry, r_menu, s) = Self::btn_rects(view_w, view_h);
        let _ = s;
        let [mx, my] = self.hovered_pos;
        let btn_a = self.stage(0.62, 1.0);
        self.btn_retry.alpha = btn_a;
        self.btn_menu.alpha = btn_a;
        self.btn_retry.update_hover(self.has_pointer && r_retry.contains(mx, my), dt, reduce_motion);
        self.btn_menu.update_hover(self.has_pointer && r_menu.contains(mx, my), dt, reduce_motion);
    }

    pub fn on_mouse_move(&mut self, x: f32, y: f32) {
        self.hovered_pos = [x, y];
        self.has_pointer = true;
    }

    pub fn on_mouse_press(&self, x: f32, y: f32, view_w: u32, view_h: u32) -> GameOverAction {
        if self.stage(0.62, 1.0) < 0.25 {
            return GameOverAction::None;
        }
        let (r_retry, r_menu, _) = Self::btn_rects(view_w, view_h);
        if r_retry.contains(x, y) {
            return GameOverAction::Retry;
        }
        if r_menu.contains(x, y) {
            return GameOverAction::QuitToMenu;
        }
        GameOverAction::None
    }

    pub fn on_confirm_key(&self) -> GameOverAction {
        if self.key_guard_released && self.reveal_t >= self.reveal_total * 0.62 {
            GameOverAction::Retry
        } else {
            GameOverAction::None
        }
    }

    fn stage(&self, start: f32, end: f32) -> f32 {
        let p = (self.reveal_t / self.reveal_total).clamp(0.0, 1.0);
        ((p - start) / (end - start).max(1e-4)).clamp(0.0, 1.0)
    }

    fn btn_rects(view_w: u32, view_h: u32) -> (UiRect, UiRect, f32) {
        let s = ui_scale(view_w, view_h);
        let cx = (view_w as f32) * 0.5;
        let cy = (view_h as f32) * 0.5 - 125.0 * s;
        let bw = 180.0 * s;
        let bh = 46.0 * s;
        let gap = 20.0 * s;
        let r_retry = UiRect::new(cx - bw - gap * 0.5, cy, bw, bh);
        let r_menu = UiRect::new(cx + gap * 0.5, cy, bw, bh);
        (r_retry, r_menu, s)
    }

    pub fn draw(
        &self,
        ui_alpha: &mut SdfBatch,
        ui_text: &mut TextBatch,
        view_w: u32,
        view_h: u32,
        reduce_motion: bool,
    ) {
        let w = view_w as f32;
        let h = view_h as f32;
        let (r_retry, r_menu, s) = Self::btn_rects(view_w, view_h);
        let cx = w * 0.5;
        let cy = h * 0.5;
        let rise = if reduce_motion { 0.0 } else { 14.0 * s };

        let ov_a = self.stage(0.0, 0.28);
        ui_alpha.panel(0.0, 0.0, w, h, 0.0, linear_rgba([6, 8, 16], (216.0 * ov_a) as u8, 1.0));

        // 1. Title
        let a_title = self.stage(0.08, 0.35);
        ui_text.draw_hdr(
            "GAME OVER",
            FontId::Head,
            pt_px(42.0, s, 26.0),
            cx,
            cy + 150.0 * s - (1.0 - a_title) * rise,
            AlignX::Center,
            AlignY::Center,
            [255, 110, 125],
            1.15 * a_title,
            true,
        );

        // 2. Wave reached + Score countup
        let a_score = self.stage(0.18, 0.50);
        let count_t = self.stage(0.22, 0.72);
        let shown_score = ((self.score as f32) * count_t).round() as i32;
        ui_text.draw(
            format!("Wave {} Reached", self.wave),
            FontId::Bold,
            pt_px(17.0, s, 12.0),
            cx,
            cy + 102.0 * s - (1.0 - a_score) * rise,
            AlignX::Center,
            AlignY::Center,
            TEXT,
            (245.0 * a_score) as u8,
            true,
        );
        ui_text.draw_hdr(
            format!("Score: {}", format_score_commas(shown_score)),
            FontId::Head,
            pt_px(26.0, s, 17.0),
            cx,
            cy + 66.0 * s - (1.0 - a_score) * rise,
            AlignX::Center,
            AlignY::Center,
            GOLD,
            1.05 * a_score,
            true,
        );

        // 3. New High badge
        if self.is_new_high {
            let a_nh = self.stage(0.45, 0.75);
            let wob = if reduce_motion {
                0.0
            } else {
                4.0 * s * (self.reveal_t * 6.0).sin()
            };
            ui_text.draw_hdr(
                "NEW HIGH SCORE!",
                FontId::Head,
                pt_px(15.5, s, 11.5),
                cx,
                cy + 30.0 * s + wob - (1.0 - a_nh) * rise,
                AlignX::Center,
                AlignY::Center,
                [255, 224, 100],
                1.1 * a_nh,
                true,
            );
        }

        // 4. Stats row
        let a_stats = self.stage(0.38, 0.75);
        let total_sec = self.survived_s.max(0.0) as u32;
        let mins = total_sec / 60;
        let secs = total_sec % 60;
        let rank_txt = if self.rank == 0 {
            "Off board".to_string()
        } else if self.rank == 1 {
            if self.is_new_high {
                "NEW #1".to_string()
            } else {
                "#1".to_string()
            }
        } else {
            let pts = self.points_to_next.unwrap_or(1).max(1);
            format!("#{} ({} to next)", self.rank, format_score_commas(pts))
        };
        let stats_line = format!(
            "SURVIVED {mins}:{secs:02}   ·   KILLS {}   ·   BEST COMBO {:.1}x   ·   RANK {rank_txt}",
            format_score_commas(self.kills),
            self.best_combo
        );
        ui_text.draw(
            stats_line,
            FontId::Bold,
            pt_px(12.5, s, 9.5),
            cx,
            cy - 10.0 * s - (1.0 - a_stats) * rise,
            AlignX::Center,
            AlignY::Center,
            if self.rank == 1 && self.is_new_high { GOLD } else { [205, 222, 245] },
            (245.0 * a_stats) as u8,
            true,
        );

        // 5. Daily & Mutators
        let a_meta = self.stage(0.50, 0.85);
        if !self.daily_summary.is_empty() {
            ui_text.draw(
                &self.daily_summary,
                FontId::Bold,
                pt_px(11.5, s, 9.5),
                cx,
                cy - 42.0 * s - (1.0 - a_meta) * rise,
                AlignX::Center,
                AlignY::Center,
                if self.daily_is_best { GOLD } else { MUTED },
                (235.0 * a_meta) as u8,
                true,
            );
        }
        ui_text.draw(
            &self.mutator_summary,
            FontId::Regular,
            pt_px(11.0, s, 9.0),
            cx,
            cy - 68.0 * s - (1.0 - a_meta) * rise,
            AlignX::Center,
            AlignY::Center,
            MUTED,
            (220.0 * a_meta) as u8,
            true,
        );

        // 5b. Achievements: unlocked by this run, then the closest locked ones
        let a_ach = self.stage(0.56, 0.90);
        let ach_dy = (1.0 - a_ach) * rise;
        let text_max_w = (w - 40.0 * s).max(200.0);
        if !self.achievements.is_empty() {
            let ach_px = pt_px(12.0, s, 9.5);
            let line = fit_names_line(
                "ACHIEVEMENT UNLOCKED: ",
                &self.achievements,
                ach_px,
                text_max_w,
            );
            ui_text.draw(
                line,
                FontId::Bold,
                ach_px,
                cx,
                cy - 150.0 * s - ach_dy,
                AlignX::Center,
                AlignY::Center,
                GOLD,
                (245.0 * a_ach) as u8,
                true,
            );
        }
        for (i, line) in self.near.iter().take(2).enumerate() {
            let near_px = pt_px(11.0, s, 9.0);
            ui_text.draw(
                fit_line_to_width(&format!("Almost there: {line}"), near_px, text_max_w, true),
                FontId::Regular,
                near_px,
                cx,
                cy - (176.0 + 20.0 * i as f32) * s - ach_dy,
                AlignX::Center,
                AlignY::Center,
                MUTED,
                (220.0 * a_ach) as u8,
                true,
            );
        }

        // 6. Action Buttons
        let a_btn = self.stage(0.62, 1.0);
        let btn_dy = if reduce_motion { 0.0 } else { -(1.0 - a_btn) * rise };
        let rr = UiRect::new(r_retry.x, r_retry.y + btn_dy, r_retry.w, r_retry.h);
        let rm = UiRect::new(r_menu.x, r_menu.y + btn_dy, r_menu.w, r_menu.h);
        let bpx = pt_px(15.5, s, 11.5);
        draw_button(ui_alpha, ui_text, rr, &self.btn_retry, bpx, s);
        draw_button(ui_alpha, ui_text, rm, &self.btn_menu, bpx, s);

        let _ = TAU;
    }
}

/// Rough text width estimate: UI glyphs average about 0.6 em (bold a little more).
fn estimate_text_w(text: &str, px: f32, bold: bool) -> f32 {
    let em = if bold { 0.62 } else { 0.56 };
    text.chars().count() as f32 * px * em
}

/// Shortens `text` with an ellipsis so its estimated width fits `max_w`.
fn fit_line_to_width(text: &str, px: f32, max_w: f32, bold: bool) -> String {
    if estimate_text_w(text, px, bold) <= max_w {
        return text.to_string();
    }
    let per_char = (px * if bold { 0.62 } else { 0.56 }).max(1.0);
    let keep = ((max_w / per_char).floor() as usize).saturating_sub(3);
    let mut out: String = text.chars().take(keep).collect();
    out.push_str("...");
    out
}

/// Fits a single-line summary without shrinking its font or cutting through a word.
fn fit_phrase_to_width(text: &str, px: f32, max_w: f32, bold: bool) -> String {
    if estimate_text_w(text, px, bold) <= max_w {
        return text.to_string();
    }
    let suffix = "…";
    let suffix_w = estimate_text_w(suffix, px, bold);
    let mut out = String::new();
    for word in text.split_whitespace() {
        let candidate = if out.is_empty() {
            word.to_string()
        } else {
            format!("{out} {word}")
        };
        if estimate_text_w(&candidate, px, bold) + suffix_w > max_w {
            break;
        }
        out = candidate;
    }
    if out.is_empty() {
        return fit_line_to_width(text, px, max_w, bold);
    }
    out.push_str(suffix);
    out
}

/// "prefix name1, name2 (+N more)" with as many names as fit. Names are dropped from the end
/// (never cut mid-name) and the "+N more" count says how many were left out.
fn fit_names_line(prefix: &str, names: &[String], px: f32, max_w: f32) -> String {
    for k in (1..=names.len()).rev() {
        let more = names.len() - k;
        let joined = names[..k].join(", ");
        let line = if more > 0 {
            format!("{prefix}{joined} (+{more} more)")
        } else {
            format!("{prefix}{joined}")
        };
        if estimate_text_w(&line, px, true) <= max_w {
            return line;
        }
    }
    // Even one name is too wide: shorten it rather than dropping it.
    fit_line_to_width(&format!("{prefix}{}", names.first().map(String::as_str).unwrap_or("")), px, max_w, true)
}

#[cfg(test)]
mod guide_tests {
    use super::*;

    #[test]
    fn every_regular_and_boss_dossier_has_its_matching_3d_preview() {
        let entries = GuideScreen::enemy_entries(false);
        for key in GUIDE_REGULAR_MODEL_KEYS.iter().chain(GUIDE_BOSS_MODEL_KEYS.iter()) {
            let matches: Vec<_> = entries.iter().filter(|entry| entry.key == *key).collect();
            assert_eq!(matches.len(), 1, "guide roster should contain {key} once");

            let mut alpha = SdfBatch::default();
            let mut additive = SdfBatch::default();
            let drawn = draw_guide_model_preview(
                matches[0],
                &mut alpha,
                &mut additive,
                [64.0, 64.0],
                crate::sim::math::Vec2::new(1.0, 0.0),
                0.75,
                1.25,
                true,
            );
            assert!(drawn, "guide key {key} must dispatch to its real model");
            assert!(
                !alpha.instances.is_empty() || !additive.instances.is_empty(),
                "guide key {key} must produce visible model geometry"
            );
        }
    }

    #[test]
    fn every_enemy_preview_has_cached_fits_for_guide_and_spotlight_frames() {
        for key in GUIDE_REGULAR_MODEL_KEYS {
            for radius in [17.0, 32.0] {
                let scale = crate::render::models3d::enemy_model_preview_fit_scale(key, radius)
                    .unwrap_or_else(|| panic!("missing regular preview fit for {key}"));
                assert!(scale.is_finite() && scale > 0.0, "invalid fit for {key} at radius {radius}");
            }
        }
        for key in GUIDE_BOSS_MODEL_KEYS {
            for radius in [17.0, 32.0] {
                let scale = crate::render::models3d::boss_model_preview_fit_scale(key, radius)
                    .unwrap_or_else(|| panic!("missing boss preview fit for {key}"));
                assert!(scale.is_finite() && scale > 0.0, "invalid fit for {key} at radius {radius}");
            }
        }
    }

    #[test]
    fn non_hull_enemy_dossiers_use_semantic_symbols_not_letter_fallbacks() {
        let keys = [
            "boss_personas",
            "boss_rage",
            "volatile",
            "swift",
            "shielded",
            "splitter",
            "reflector",
            "mender",
            "warden",
        ];
        for key in keys {
            let mut icon = SdfBatch::default();
            assert!(draw_enemy_guide_symbol(key, 32.0, 32.0, 1.0, [140, 210, 255], &mut icon));
            assert!(!icon.instances.is_empty(), "{key} must draw a semantic badge");
        }
    }

    #[test]
    fn main_menu_spotlight_cycles_only_through_real_enemy_hulls() {
        let menu = MenuScreen::new();
        assert_eq!(menu.spotlight_entries.len(), 19);
        assert!(menu
            .spotlight_entries
            .iter()
            .all(|entry| is_guide_enemy_model(entry.key)));
    }

    #[test]
    fn main_menu_spotlight_stays_inside_view_and_clear_of_actions() {
        let menu = MenuScreen::new();
        for (width, height) in [(820, 500), (980, 620), (1280, 720), (1920, 1080)] {
            let layout = menu.layout(width, height);
            let Some(card) = layout.spotlight_rect else { panic!("expected spotlight at {width}x{height}"); };
            assert!(card.x >= 0.0 && card.y >= 0.0);
            assert!(card.x + card.w <= width as f32);
            assert!(card.y + card.h <= height as f32);
            let action_right = layout
                .btn_rects
                .iter()
                .map(|button| button.x + button.w)
                .fold(0.0_f32, f32::max);
            assert!(card.x > action_right, "spotlight overlaps actions at {width}x{height}");
        }
        assert!(menu.layout(800, 720).spotlight_rect.is_none());
    }

    #[test]
    fn guide_model_animation_respects_reduced_motion() {
        let mut guide = GuideScreen::new();
        guide.update(0.5, 1280, 720, true);
        assert!(guide.reduce_motion);
        assert_eq!(guide.t, 0.0);

        guide.update(0.5, 1280, 720, false);
        assert!(!guide.reduce_motion);
        assert!(guide.t > 0.0);
    }

    #[test]
    fn tank_egg_sac_and_origin_nexus_dossiers_match_current_source_mechanics() {
        let entries = GuideScreen::enemy_entries(false);
        let tank = entries.iter().find(|entry| entry.key == "tank").unwrap();
        assert!(!tank.what.contains("Armored Surge"));
        assert!(!tank.deal.contains("40%-HP"));
        assert!(tank.what.contains("marks a long cannon lane"));

        let egg = entries.iter().find(|entry| entry.key == "egg_sac").unwrap();
        assert!(egg.what.contains("up to three"));
        assert!(egg.what.contains("spawn cap"));

        let nexus = entries.iter().find(|entry| entry.key == "boss_womb_core").unwrap();
        assert!(nexus.what.contains("a point ahead of the boss"));
        assert!(!nexus.what.contains("zone between ships"));
    }
}
