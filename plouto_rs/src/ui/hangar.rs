use std::path::Path;

use crate::render::player_art::draw_character_preview;
use crate::render::sdf::{linear_rgba, mix_rgb, SdfBatch};
use crate::render::text::{AlignX, AlignY, FontId, FontPack, TextBatch};
use crate::save::progress::{load_progress, save_progress, skin_is_unlocked, ProgressData};
use crate::sim::achievements::{
    progress_of, shown_description, shown_name, AchCategory, AchCondition, AchTotals,
    AchievementDef, RunStats, ACHIEVEMENTS,
};
use crate::sim::skins::{get_skin, unlock_hint, DEFAULT_SKIN_ID, SKINS};
use crate::ui::theme::{
    draw_button, draw_chip, draw_panel, pt_px, ui_scale, ButtonStyle, UiRect, ACCENT, BACKGROUND,
    DANGER, MUTED, PANEL, SUCCESS, TEXT,
};

const MESSAGE_SECONDS: f32 = 3.0;
const MIN_CARD_W: f32 = 240.0;
const CARD_MAX_H: f32 = 160.0;
const CARD_GAP: f32 = 14.0;
const ROW_H: f32 = 82.0;
const ROW_GAP: f32 = 10.0;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HangarTab {
    Skins,
    Achievements,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NavDir {
    Left,
    Right,
    Up,
    Down,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HangarAction {
    None,
    Back,
    Moved,
    SkinEquipped(String),
    LockedRefused,
}

pub fn grid_step(cursor: usize, dir: NavDir, count: usize, cols: usize) -> usize {
    if count == 0 || cols == 0 {
        return 0;
    }
    let c = cursor.min(count - 1);
    match dir {
        NavDir::Left => {
            if c % cols > 0 {
                c - 1
            } else {
                c
            }
        }
        NavDir::Right => {
            if c + 1 < count && (c % cols) + 1 < cols {
                c + 1
            } else {
                c
            }
        }
        NavDir::Up => {
            if c >= cols {
                c - cols
            } else {
                c
            }
        }
        NavDir::Down => {
            if c + cols < count {
                c + cols
            } else {
                c
            }
        }
    }
}

pub fn page_step(page: usize, delta: isize, total_pages: usize) -> usize {
    if total_pages == 0 {
        return 0;
    }
    ((page as isize) + delta).rem_euclid(total_pages as isize) as usize
}

struct HangarLayout {
    s: f32,
    panel: UiRect,
    area: UiRect,
    btn_skins: UiRect,
    btn_ach: UiRect,
    btn_back: UiRect,
    btn_prev: UiRect,
    btn_next: UiRect,
    cols: usize,
    cards: Vec<(UiRect, &'static str)>,
    ach_per_page: usize,
    ach_page_count: usize,
}

pub struct HangarScreen {
    pub tab: HangarTab,
    pub cursor: usize,
    pub ach_page: usize,
    pub progress: ProgressData,
    t: f32,
    message: String,
    message_color: [u8; 3],
    message_left: f32,

    btn_skins: ButtonStyle,
    btn_ach: ButtonStyle,
    btn_back: ButtonStyle,
    btn_prev: ButtonStyle,
    btn_next: ButtonStyle,

    hovered_pos: [f32; 2],
    has_pointer: bool,
}

impl Default for HangarScreen {
    fn default() -> Self {
        Self::new()
    }
}

impl HangarScreen {
    pub fn new() -> Self {
        Self {
            tab: HangarTab::Skins,
            cursor: 0,
            ach_page: 0,
            progress: ProgressData::default(),
            t: 0.0,
            message: String::new(),
            message_color: MUTED,
            message_left: 0.0,
            btn_skins: ButtonStyle::new("Skins", ACCENT, [185, 225, 255]),
            btn_ach: ButtonStyle::new("Achievements", PANEL, ACCENT),
            btn_back: ButtonStyle::new("Back", [90, 110, 145], ACCENT),
            btn_prev: ButtonStyle::new("Prev", PANEL, ACCENT),
            btn_next: ButtonStyle::new("Next", PANEL, ACCENT),
            hovered_pos: [0.0, 0.0],
            has_pointer: false,
        }
    }

    pub fn open(&mut self, progress_path: &Path) {
        self.progress = load_progress(progress_path);
        self.reset_on_open();
    }

    pub fn open_with_progress(&mut self, progress: ProgressData) {
        self.progress = progress;
        self.reset_on_open();
    }

    fn reset_on_open(&mut self) {
        self.message.clear();
        self.message_left = 0.0;
        self.ach_page = 0;
        let sel = self.selected_id().to_string();
        self.cursor = SKINS.iter().position(|s| s.id == sel).unwrap_or(0);
    }

    pub fn selected_id(&self) -> &str {
        if self.progress.selected_skin.is_empty() {
            DEFAULT_SKIN_ID
        } else {
            &self.progress.selected_skin
        }
    }

    pub fn set_tab(&mut self, tab: HangarTab) {
        if self.tab != tab {
            self.tab = tab;
        }
    }

    fn flash(&mut self, msg: impl Into<String>, color: [u8; 3]) {
        self.message = msg.into();
        self.message_color = color;
        self.message_left = MESSAGE_SECONDS;
    }

    pub fn choose(&mut self, skin_id: &str, progress_path: Option<&Path>) -> HangarAction {
        let Some(skin) = get_skin(skin_id) else {
            return HangarAction::None;
        };
        if !skin_is_unlocked(&self.progress, skin_id) {
            self.flash(format!("{} is locked. {}", skin.name, unlock_hint(skin)), DANGER);
            return HangarAction::LockedRefused;
        }
        self.progress.selected_skin = skin.id.to_string();
        if let Some(p) = progress_path {
            save_progress(p, &self.progress);
        }
        self.flash(format!("{} selected", skin.name), SUCCESS);
        HangarAction::SkinEquipped(skin.id.to_string())
    }

    pub fn update(&mut self, dt: f32, view_w: u32, view_h: u32, reduce_motion: bool) {
        if !reduce_motion {
            self.t += dt;
        }
        if self.message_left > 0.0 {
            self.message_left = (self.message_left - dt).max(0.0);
            if self.message_left <= 0.0 {
                self.message.clear();
            }
        }
        let layout = self.compute_layout(view_w, view_h);
        // A resize can shrink the page count; keep the stored page inside it so Prev/Next
        // step from the page the player actually sees.
        self.ach_page = self.clamped_ach_page(&layout);
        let [mx, my] = self.hovered_pos;
        let on_ach = self.tab == HangarTab::Achievements;
        self.btn_skins.selected = !on_ach;
        self.btn_ach.selected = on_ach;
        self.btn_skins
            .update_hover(self.has_pointer && layout.btn_skins.contains(mx, my), dt, reduce_motion);
        self.btn_ach
            .update_hover(self.has_pointer && layout.btn_ach.contains(mx, my), dt, reduce_motion);
        self.btn_back
            .update_hover(self.has_pointer && layout.btn_back.contains(mx, my), dt, reduce_motion);
        self.btn_prev.alpha = if on_ach { 1.0 } else { 0.0 };
        self.btn_next.alpha = if on_ach { 1.0 } else { 0.0 };
        self.btn_prev.update_hover(
            on_ach && self.has_pointer && layout.btn_prev.contains(mx, my),
            dt,
            reduce_motion,
        );
        self.btn_next.update_hover(
            on_ach && self.has_pointer && layout.btn_next.contains(mx, my),
            dt,
            reduce_motion,
        );
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
        progress_path: Option<&Path>,
    ) -> HangarAction {
        self.hovered_pos = [x, y];
        self.has_pointer = true;
        let layout = self.compute_layout(view_w, view_h);
        if layout.btn_back.contains(x, y) {
            return HangarAction::Back;
        }
        if layout.btn_skins.contains(x, y) {
            self.set_tab(HangarTab::Skins);
            return HangarAction::None;
        }
        if layout.btn_ach.contains(x, y) {
            self.set_tab(HangarTab::Achievements);
            return HangarAction::None;
        }
        if self.tab == HangarTab::Skins {
            for (i, (rect, sid)) in layout.cards.iter().enumerate() {
                if rect.contains(x, y) {
                    let moved = i != self.cursor;
                    self.cursor = i;
                    let act = self.choose(sid, progress_path);
                    if act == HangarAction::None && moved {
                        return HangarAction::Moved;
                    }
                    return act;
                }
            }
        } else {
            if layout.btn_prev.contains(x, y) {
                let page = self.clamped_ach_page(&layout);
                self.ach_page = page_step(page, -1, layout.ach_page_count);
                return HangarAction::Moved;
            }
            if layout.btn_next.contains(x, y) {
                let page = self.clamped_ach_page(&layout);
                self.ach_page = page_step(page, 1, layout.ach_page_count);
                return HangarAction::Moved;
            }
        }
        HangarAction::None
    }

    pub fn on_nav(
        &mut self,
        dir: Option<NavDir>,
        activate: bool,
        toggle_tab: bool,
        back: bool,
        view_w: u32,
        view_h: u32,
        progress_path: Option<&Path>,
    ) -> HangarAction {
        if back {
            return HangarAction::Back;
        }
        if toggle_tab {
            self.set_tab(match self.tab {
                HangarTab::Skins => HangarTab::Achievements,
                HangarTab::Achievements => HangarTab::Skins,
            });
            return HangarAction::Moved;
        }
        let layout = self.compute_layout(view_w, view_h);
        if self.tab == HangarTab::Skins {
            if let Some(d) = dir {
                let before = self.cursor;
                self.cursor = grid_step(self.cursor, d, SKINS.len(), layout.cols);
                return if self.cursor != before {
                    HangarAction::Moved
                } else {
                    HangarAction::None
                };
            }
            if activate && !SKINS.is_empty() {
                let sid = SKINS[self.cursor.min(SKINS.len() - 1)].id;
                return self.choose(sid, progress_path);
            }
        } else if let Some(d) = dir {
            let step = match d {
                NavDir::Left | NavDir::Up => -1,
                NavDir::Right | NavDir::Down => 1,
            };
            let page = self.clamped_ach_page(&layout);
            self.ach_page = page_step(page, step, layout.ach_page_count);
            return HangarAction::Moved;
        }
        HangarAction::None
    }

    fn clamped_ach_page(&self, layout: &HangarLayout) -> usize {
        self.ach_page.min(layout.ach_page_count.saturating_sub(1))
    }

    fn compute_layout(&self, view_w: u32, view_h: u32) -> HangarLayout {
        let w = view_w as f32;
        let h = view_h as f32;
        let s = ui_scale(view_w, view_h).min(1.35);
        let cx = w * 0.5;
        let title_y = h - 46.0 * s;
        let sub_y = title_y - 38.0 * s;

        let pad = 18.0 * s;
        let panel_w = (w * 0.94).min(1220.0 * s);
        let panel_top = sub_y - 18.0 * s;
        let panel_h = (panel_top - 40.0 * s).min(760.0 * s).max(260.0);
        let panel_x = cx - panel_w * 0.5;
        let panel_y = (panel_top - panel_h).max(40.0 * s);
        let panel = UiRect::new(panel_x, panel_y, panel_w, panel_h);

        let btn_h = 44.0 * s;
        let top_row_y = panel_y + panel_h - pad - btn_h;
        let gap = 10.0 * s;
        let btn_skins = UiRect::new(panel_x + pad, top_row_y, 150.0 * s, btn_h);
        let btn_ach = UiRect::new(btn_skins.x + btn_skins.w + gap, top_row_y, 190.0 * s, btn_h);
        let back_w = 170.0 * s;
        let btn_back = UiRect::new(panel_x + panel_w - pad - back_w, top_row_y, back_w, btn_h);

        let band_h = 50.0 * s;
        let pg_h = 34.0 * s;
        let pg_w = 120.0 * s;
        let pg_y = panel_y + (band_h - pg_h) * 0.5;
        let btn_prev = UiRect::new(panel_x + pad, pg_y, pg_w, pg_h);
        let btn_next = UiRect::new(panel_x + panel_w - pad - pg_w, pg_y, pg_w, pg_h);

        let area_x = panel_x + pad;
        let area_y = panel_y + band_h;
        let area_w = panel_w - 2.0 * pad;
        let area_h = (top_row_y - 14.0 * s - area_y).max(120.0);
        let area = UiRect::new(area_x, area_y, area_w, area_h);

        // Compute skin grid
        let n = SKINS.len();
        let cgap = CARD_GAP * s;
        let min_w = MIN_CARD_W * s;
        let cols = (((area_w + cgap) / (min_w + cgap)).floor() as usize).clamp(1, n.max(1));
        let rows = (n + cols - 1) / cols;
        let card_w = (area_w - cgap * ((cols.saturating_sub(1)) as f32)) / cols as f32;
        let card_h = (CARD_MAX_H * s)
            .min((area_h - cgap * ((rows.saturating_sub(1)) as f32)) / rows.max(1) as f32)
            .max(70.0);
        let grid_h = card_h * (rows as f32) + cgap * (rows.saturating_sub(1) as f32);
        let grid_top = area_y + area_h - ((area_h - grid_h).max(0.0)) * 0.5;

        let mut cards = Vec::with_capacity(n);
        for (i, skin) in SKINS.iter().enumerate() {
            let r = i / cols;
            let c = i % cols;
            let x = area_x + (c as f32) * (card_w + cgap);
            let y = grid_top - ((r + 1) as f32) * card_h - (r as f32) * cgap;
            cards.push((UiRect::new(x, y, card_w, card_h), skin.id));
        }

        // Compute achievements pagination
        let rgap = ROW_GAP * s;
        let rh = ROW_H * s;
        let ach_per_page = (((area_h + rgap) / (rh + rgap)).floor() as usize).max(1);
        let ach_page_count = ((ACHIEVEMENTS.len() + ach_per_page - 1) / ach_per_page).max(1);

        HangarLayout {
            s,
            panel,
            area,
            btn_skins,
            btn_ach,
            btn_back,
            btn_prev,
            btn_next,
            cols,
            cards,
            ach_per_page,
            ach_page_count,
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
    ) {
        let l = self.compute_layout(view_w, view_h);
        let s = l.s;
        let w = view_w as f32;
        let h = view_h as f32;
        let cx = w * 0.5;

        // Veil over menu starfield
        ui_alpha.panel(0.0, 0.0, w, h, 0.0, linear_rgba(BACKGROUND, 195, 1.0));

        let title_y = h - 46.0 * s;
        ui_text.draw_hdr(
            "HANGAR",
            FontId::Head,
            pt_px(28.0, s, 18.0),
            cx,
            title_y,
            AlignX::Center,
            AlignY::Center,
            TEXT,
            1.0,
            true,
        );
        let sub = match self.tab {
            HangarTab::Skins => "Pick a paint for your ship. Locked skins show how to earn them.",
            HangarTab::Achievements => "Every achievement, and earned status across all runs.",
        };
        ui_text.draw(
            sub,
            FontId::Regular,
            pt_px(13.0, s, 10.0),
            cx,
            title_y - 38.0 * s,
            AlignX::Center,
            AlignY::Center,
            MUTED,
            235,
            true,
        );

        // Main panel
        draw_panel(
            ui_alpha,
            l.panel,
            10.0 * s,
            1.8,
            PANEL,
            215,
            ACCENT,
            75,
            6.0 * s,
        );

        let tab_px = pt_px(15.0, s, 11.0);
        draw_button(ui_alpha, ui_text, l.btn_skins, &self.btn_skins, tab_px, s);
        draw_button(ui_alpha, ui_text, l.btn_ach, &self.btn_ach, tab_px, s);
        draw_button(ui_alpha, ui_text, l.btn_back, &self.btn_back, tab_px, s);

        if self.tab == HangarTab::Skins {
            self.draw_skins_tab(&l, ui_alpha, ui_add, ui_text, fonts);
        } else {
            self.draw_achievements_tab(&l, ui_alpha, ui_text, fonts);
            let pg_px = pt_px(13.5, s, 10.0);
            draw_button(ui_alpha, ui_text, l.btn_prev, &self.btn_prev, pg_px, s);
            draw_button(ui_alpha, ui_text, l.btn_next, &self.btn_next, pg_px, s);
        }

        // Footer bar / status flash
        let (footer_txt, footer_col) = if self.message_left > 0.0 && !self.message.is_empty() {
            (self.message.as_str(), self.message_color)
        } else if self.tab == HangarTab::Skins {
            ("ARROWS move  |  ENTER select  |  TAB achievements  |  ESC back", MUTED)
        } else {
            ("ARROWS page  |  TAB skins  |  ESC back", MUTED)
        };
        let footer_pt = pt_px(11.5, s, 9.5);
        let footer_fit = fonts.fit_text(FontId::Regular, footer_pt, footer_txt, w - 40.0 * s);
        ui_text.draw(
            footer_fit,
            FontId::Regular,
            footer_pt,
            cx,
            18.0 * s,
            AlignX::Center,
            AlignY::Center,
            footer_col,
            245,
            true,
        );
    }

    fn draw_skins_tab(
        &self,
        l: &HangarLayout,
        ui_alpha: &mut SdfBatch,
        ui_add: &mut SdfBatch,
        ui_text: &mut TextBatch,
        fonts: &FontPack,
    ) {
        let s = l.s;
        let selected_id = self.selected_id();
        let mut unlocked_n = 0usize;

        for (idx, (rect, sid)) in l.cards.iter().enumerate() {
            let Some(skin) = get_skin(sid) else {
                continue;
            };
            let unlocked = skin_is_unlocked(&self.progress, sid);
            if unlocked {
                unlocked_n += 1;
            }
            let is_selected = *sid == selected_id;
            let is_cursor = idx == self.cursor;
            let is_hovered = self.has_pointer && rect.contains(self.hovered_pos[0], self.hovered_pos[1]);

            if is_cursor {
                let pad = 3.0 * s;
                ui_alpha.panel_outline(
                    rect.x - pad,
                    rect.y - pad,
                    rect.w + 2.0 * pad,
                    rect.h + 2.0 * pad,
                    10.0 * s,
                    2.6,
                    linear_rgba(ACCENT, 240, 1.0),
                );
            }

            let card_bg = if is_selected {
                mix_rgb(PANEL, skin.palette.accent, 0.22)
            } else if is_hovered {
                mix_rgb(PANEL, ACCENT, 0.14)
            } else {
                mix_rgb(PANEL, [24, 38, 60], 0.35)
            };
            let border = if is_selected {
                skin.palette.accent
            } else if unlocked {
                mix_rgb(ACCENT, [255, 255, 255], 0.15)
            } else {
                [80, 92, 112]
            };
            draw_panel(
                ui_alpha,
                *rect,
                8.0 * s,
                if is_selected { 2.0 } else { 1.4 },
                card_bg,
                225,
                border,
                if is_selected { 230 } else { 105 },
                3.0 * s,
            );

            let pad = 12.0 * s;
            let plate_w = rect.w * 0.27;
            let plate_x = rect.x + rect.w - pad - plate_w;
            let left_w = (plate_x - 8.0 * s - (rect.x + pad)).max(40.0);
            let plate_bottom = rect.y + 44.0 * s;
            let plate_top = rect.y + rect.h - pad;
            let plate_h = (plate_top - plate_bottom).max(36.0);

            // Title + fit
            let name_px = pt_px(15.5, s, 11.0);
            let fit_name = fonts.fit_text(FontId::Head, name_px, skin.name, left_w);
            ui_text.draw(
                fit_name,
                FontId::Head,
                name_px,
                rect.x + pad,
                rect.y + rect.h - pad - 2.0 * s,
                AlignX::Left,
                AlignY::Top,
                if unlocked { TEXT } else { MUTED },
                255,
                true,
            );

            let (chip_txt, chip_col) = if is_selected {
                ("SELECTED", ACCENT)
            } else if unlocked {
                ("UNLOCKED", SUCCESS)
            } else {
                ("LOCKED", DANGER)
            };
            let chip_rect = UiRect::new(
                rect.x + pad,
                rect.y + rect.h - pad - 44.0 * s,
                (94.0 * s).min(left_w),
                19.0 * s,
            );
            draw_chip(
                ui_alpha,
                ui_text,
                chip_rect,
                chip_txt,
                is_selected,
                false,
                chip_col,
                pt_px(9.5, s, 8.0),
                s,
                1.0,
            );

            // Preview plate
            let plate = UiRect::new(plate_x, plate_bottom, plate_w, plate_h);
            draw_panel(
                ui_alpha,
                plate,
                6.0 * s,
                1.2,
                BACKGROUND,
                235,
                if unlocked { skin.palette.glow } else { [70, 82, 100] },
                if is_selected { 170 } else { 70 },
                0.0,
            );
            let (pcx, pcy) = plate.center();
            let pscale = (plate_w.min(plate_h) / 46.0).clamp(0.75, 1.35);
            if unlocked {
                ui_add.glow(
                    pcx,
                    pcy,
                    18.0 * pscale,
                    1.6,
                    linear_rgba(skin.palette.glow, if is_selected { 130 } else { 75 }, 1.2),
                );
            }
            draw_character_preview(
                ui_alpha,
                ui_add,
                pcx,
                pcy,
                pscale,
                self.t,
                is_selected,
                !unlocked,
                &skin.palette,
            );

            // Unlock rule (wrapped at bottom of card)
            let hint = unlock_hint(skin);
            let hint_px = pt_px(10.5, s, 8.5);
            let hint_w = rect.w - 2.0 * pad;
            let lines = fonts.wrap_lines(FontId::Regular, hint_px, &hint, hint_w);
            // Two lines at most. Anything beyond the second is folded into it with an ellipsis.
            let shown: Vec<String> = if lines.len() <= 2 {
                lines
            } else {
                let rest = lines[1..].join(" ");
                vec![
                    lines[0].clone(),
                    fonts.fit_text(FontId::Regular, hint_px, &rest, hint_w),
                ]
            };
            let line_step = hint_px * 1.15;
            for (li, line) in shown.iter().enumerate() {
                ui_text.draw(
                    line.as_str(),
                    FontId::Regular,
                    hint_px,
                    rect.x + pad,
                    rect.y + 8.0 * s + ((shown.len() - 1 - li) as f32) * line_step,
                    AlignX::Left,
                    AlignY::Bottom,
                    if unlocked { [180, 200, 224] } else { MUTED },
                    230,
                    false,
                );
            }
        }

        let sel_name = get_skin(selected_id).map(|s| s.name).unwrap_or("Standard Pod");
        let band = format!("Selected: {sel_name}   |   {unlocked_n} of {} unlocked", SKINS.len());
        ui_text.draw(
            band,
            FontId::Regular,
            pt_px(12.5, s, 10.0),
            l.panel.x + l.panel.w * 0.5,
            l.panel.y + 24.0 * s,
            AlignX::Center,
            AlignY::Center,
            MUTED,
            245,
            true,
        );
    }

    fn draw_achievements_tab(
        &self,
        l: &HangarLayout,
        ui_alpha: &mut SdfBatch,
        ui_text: &mut TextBatch,
        fonts: &FontPack,
    ) {
        let s = l.s;
        let pad = 16.0 * s;
        let order = ach_display_order();
        let totals = lifetime_totals(&self.progress);
        let best = best_known_run(&self.progress);
        let page = self.clamped_ach_page(l);
        let start = (page * l.ach_per_page).min(order.len());
        let end = (start + l.ach_per_page).min(order.len());

        let row_h = ROW_H * s;
        let gap = ROW_GAP * s;
        let chip_w = 92.0 * s;
        let chip_h = 20.0 * s;
        let right_w = 150.0 * s;
        let text_x = l.area.x + 18.0 * s;
        let text_w = (l.area.w - 18.0 * s - right_w - pad).max(120.0);
        // Right-hand column (chip, category, progress numbers) hangs off this edge.
        let right_edge = l.area.x + l.area.w - pad;

        for (i, &ach) in order[start..end].iter().enumerate() {
            let earned = self.progress.achievements.iter().any(|id| id == ach.id);
            let row_y = l.area.y + l.area.h - ((i + 1) as f32) * row_h - (i as f32) * gap;
            let r = UiRect::new(l.area.x, row_y, l.area.w, row_h);
            draw_panel(
                ui_alpha,
                r,
                7.0 * s,
                1.4,
                mix_rgb(PANEL, if earned { SUCCESS } else { MUTED }, if earned { 0.14 } else { 0.04 }),
                215,
                if earned { SUCCESS } else { [82, 96, 118] },
                if earned { 180 } else { 90 },
                2.0 * s,
            );
            // Left status stripe
            ui_alpha.panel(
                r.x,
                r.y,
                (5.0 * s).max(3.0),
                r.h,
                2.0,
                linear_rgba(if earned { SUCCESS } else { MUTED }, 240, 1.0),
            );

            let top = row_y + row_h - 10.0 * s;
            let name_px = pt_px(15.5, s, 11.0);
            let name_fit = fonts.fit_text(FontId::Bold, name_px, shown_name(ach, earned), text_w);
            ui_text.draw(
                name_fit,
                FontId::Bold,
                name_px,
                text_x,
                top,
                AlignX::Left,
                AlignY::Top,
                if earned { TEXT } else { MUTED },
                255,
                true,
            );
            let desc_px = pt_px(11.5, s, 9.5);
            let desc_fit =
                fonts.fit_text(FontId::Regular, desc_px, shown_description(ach, earned), text_w);
            ui_text.draw(
                desc_fit,
                FontId::Regular,
                desc_px,
                text_x,
                top - 26.0 * s,
                AlignX::Left,
                AlignY::Top,
                MUTED,
                235,
                false,
            );

            let chip_r = UiRect::new(right_edge - chip_w, row_y + row_h - 10.0 * s - chip_h, chip_w, chip_h);
            draw_chip(
                ui_alpha,
                ui_text,
                chip_r,
                if earned { "EARNED" } else { "LOCKED" },
                earned,
                false,
                if earned { SUCCESS } else { MUTED },
                pt_px(9.5, s, 8.0),
                s,
                1.0,
            );
            ui_text.draw(
                ach.category.label(),
                FontId::Regular,
                pt_px(9.5, s, 8.0),
                right_edge,
                row_y + row_h - 41.0 * s,
                AlignX::Right,
                AlignY::Center,
                MUTED,
                220,
                false,
            );

            // Bottom line: progress bar with numbers, a plain goal, or nothing when earned/secret.
            let bottom_y = row_y + 16.0 * s;
            match ach_progress(ach, earned, &best, &totals) {
                AchProgress::Bar { current, target } => {
                    let shown = current.min(target);
                    let frac = (shown as f32 / target.max(1) as f32).clamp(0.0, 1.0);
                    let bar_h = 6.0 * s;
                    let bar_y = bottom_y - bar_h * 0.5;
                    ui_alpha.panel(
                        text_x,
                        bar_y,
                        text_w,
                        bar_h,
                        bar_h * 0.5,
                        linear_rgba([30, 44, 66], 230, 1.0),
                    );
                    if frac > 0.0 {
                        ui_alpha.panel(
                            text_x,
                            bar_y,
                            (text_w * frac).max(bar_h),
                            bar_h,
                            bar_h * 0.5,
                            linear_rgba(ACCENT, 235, 1.0),
                        );
                    }
                    ui_text.draw(
                        format!("{} / {}", fmt_value(ach.cond, shown), fmt_value(ach.cond, target)),
                        FontId::Regular,
                        pt_px(10.5, s, 8.5),
                        right_edge,
                        bottom_y,
                        AlignX::Right,
                        AlignY::Center,
                        TEXT,
                        235,
                        false,
                    );
                }
                AchProgress::Goal(target) => {
                    ui_text.draw(
                        format!("Goal {}", fmt_value(ach.cond, target)),
                        FontId::Regular,
                        pt_px(10.0, s, 8.0),
                        text_x,
                        bottom_y,
                        AlignX::Left,
                        AlignY::Center,
                        MUTED,
                        210,
                        false,
                    );
                }
                AchProgress::Nothing => {}
            }
        }

        let total = ACHIEVEMENTS.len();
        let earned_n = ACHIEVEMENTS
            .iter()
            .filter(|a| self.progress.achievements.iter().any(|id| id == a.id))
            .count();
        let pct = if total > 0 { earned_n * 100 / total } else { 0 };
        let info = format!(
            "Page {}/{}   |   {earned_n} / {total} earned ({pct}%)",
            page + 1,
            l.ach_page_count,
        );
        ui_text.draw(
            info,
            FontId::Regular,
            pt_px(12.5, s, 10.0),
            l.panel.x + l.panel.w * 0.5,
            l.panel.y + 24.0 * s,
            AlignX::Center,
            AlignY::Center,
            MUTED,
            245,
            true,
        );
    }
}

/// What the bottom line of an achievement row shows.
enum AchProgress {
    /// Numbers the player can see moving: lifetime totals, or the best known wave and score.
    Bar { current: i64, target: i64 },
    /// Run-only stat with no saved best. Only the target is shown.
    Goal(i64),
    /// Nothing to show: already earned, or a secret achievement.
    Nothing,
}

/// Achievements in display order: grouped by category, definition order within each group.
fn ach_display_order() -> Vec<&'static AchievementDef> {
    let mut order: Vec<&'static AchievementDef> = ACHIEVEMENTS.iter().collect();
    order.sort_by_key(|a| {
        AchCategory::ALL
            .iter()
            .position(|c| *c == a.category)
            .unwrap_or(usize::MAX)
    });
    order
}

/// Lifetime totals as the achievement engine reads them, from the saved progress.
fn lifetime_totals(p: &ProgressData) -> AchTotals {
    AchTotals {
        best_wave: p.best_wave,
        best_score: p.best_score,
        total_kills: p.total_kills,
        bosses_defeated: p.bosses_defeated,
        runs_played: p.runs_played,
        daily_runs: p.daily_runs,
        bosses_seen: p.bosses_seen.clone(),
        arenas_cleared: p.arenas_cleared.clone(),
    }
}

/// Stand-in run for progress bars. Only the lifetime best wave and score are saved per run,
/// so they are the only per-run values shown as progress.
fn best_known_run(p: &ProgressData) -> RunStats {
    let mut run = RunStats::new();
    run.wave = p.best_wave;
    run.score = p.best_score;
    run
}

fn ach_progress(ach: &AchievementDef, earned: bool, best: &RunStats, totals: &AchTotals) -> AchProgress {
    if earned || ach.secret {
        return AchProgress::Nothing;
    }
    let (current, target) = progress_of(ach, best, totals);
    match ach.cond {
        AchCondition::TotalAtLeast(..) => AchProgress::Bar { current, target },
        AchCondition::RunAtLeast("wave", _) | AchCondition::RunAtLeast("score", _) => {
            AchProgress::Bar { current, target }
        }
        _ => AchProgress::Goal(target),
    }
}

/// Format a condition value for display. Float conditions are stored in thousandths.
fn fmt_value(cond: AchCondition, v: i64) -> String {
    match cond {
        AchCondition::RunFloatAtLeast("survived_s", _) => {
            let secs = (v / 1000).max(0);
            format!("{}:{:02}", secs / 60, secs % 60)
        }
        AchCondition::RunFloatAtLeast(_, _) => format!("{:.1}x", v as f32 / 1000.0),
        _ => group_digits(v),
    }
}

fn group_digits(v: i64) -> String {
    let digits = v.unsigned_abs().to_string();
    let mut out = String::with_capacity(digits.len() + digits.len() / 3 + 1);
    if v < 0 {
        out.push('-');
    }
    let len = digits.len();
    for (i, ch) in digits.chars().enumerate() {
        if i > 0 && (len - i) % 3 == 0 {
            out.push(',');
        }
        out.push(ch);
    }
    out
}
