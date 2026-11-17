use crate::render::sdf::{linear_rgba, linear_rgba_f, mix_rgb, SdfBatch};
use crate::render::text::{AlignX, AlignY, FontId, TextBatch};

pub const BACKGROUND: [u8; 3] = [9, 16, 26];
pub const PANEL: [u8; 3] = [10, 20, 34];
pub const ACCENT: [u8; 3] = [155, 205, 255];
pub const TEXT: [u8; 3] = [224, 236, 255];
pub const MUTED: [u8; 3] = [166, 184, 202];
pub const DANGER: [u8; 3] = [200, 70, 90];
pub const SUCCESS: [u8; 3] = [45, 170, 125];
pub const GOLD: [u8; 3] = [255, 212, 95];

/// Responsive scale matching Python `ui_theme.ui_scale`.
#[inline]
pub fn ui_scale(width: u32, height: u32) -> f32 {
    let w = (width.max(1)) as f32;
    let h = (height.max(1)) as f32;
    (w / 980.0).min(h / 620.0).clamp(0.85, 1.85)
}

/// Convert Pyglet reference font size (pt at 96 dpi) into crisp pixel height.
#[inline]
pub fn pt_px(base_pt: f32, scale: f32, min_pt: f32) -> f32 {
    (base_pt * scale).max(min_pt) * (96.0 / 72.0)
}

#[derive(Debug, Clone, Copy, Default)]
pub struct UiRect {
    pub x: f32,
    pub y: f32,
    pub w: f32,
    pub h: f32,
}

impl UiRect {
    pub const fn new(x: f32, y: f32, w: f32, h: f32) -> Self {
        Self { x, y, w, h }
    }

    #[inline]
    pub fn contains(&self, px: f32, py: f32) -> bool {
        px >= self.x && px <= self.x + self.w && py >= self.y && py <= self.y + self.h
    }

    #[inline]
    pub fn center(&self) -> (f32, f32) {
        (self.x + self.w * 0.5, self.y + self.h * 0.5)
    }
}

/// Frosted indie glass panel with drop shadow, subtle glow border, and top highlight edge.
#[allow(clippy::too_many_arguments)]
pub fn draw_panel(
    batch: &mut SdfBatch,
    rect: UiRect,
    corner_r: f32,
    edge_px: f32,
    fill_rgb: [u8; 3],
    fill_alpha: u8,
    accent_rgb: [u8; 3],
    accent_alpha: u8,
    shadow_offset: f32,
) {
    if shadow_offset > 0.1 {
        batch.panel(
            rect.x + shadow_offset,
            rect.y - shadow_offset,
            rect.w,
            rect.h,
            corner_r,
            linear_rgba([2, 4, 10], 110, 1.0),
        );
    }
    batch.panel(
        rect.x,
        rect.y,
        rect.w,
        rect.h,
        corner_r,
        linear_rgba(fill_rgb, fill_alpha, 1.0),
    );
    if edge_px > 0.1 && accent_alpha > 0 {
        batch.panel_outline(
            rect.x,
            rect.y,
            rect.w,
            rect.h,
            corner_r,
            edge_px,
            linear_rgba(accent_rgb, accent_alpha, 1.0),
        );
    }
    // Subtle top specular highlight strip
    if rect.h > 14.0 && rect.w > 18.0 {
        let pad = (corner_r * 0.6).max(4.0);
        batch.line(
            rect.x + pad,
            rect.y + rect.h - 1.5,
            rect.x + rect.w - pad,
            rect.y + rect.h - 1.5,
            1.4,
            linear_rgba([255, 255, 255], 34, 1.0),
        );
    }
}

#[derive(Debug, Clone)]
pub struct ButtonStyle {
    pub label: String,
    pub base_col: [u8; 3],
    pub hover_col: [u8; 3],
    pub text_col: [u8; 3],
    pub hover_t: f32,
    pub selected: bool,
    pub focused: bool,
    pub alpha: f32,
}

impl ButtonStyle {
    pub fn new(label: impl Into<String>, base_col: [u8; 3], hover_col: [u8; 3]) -> Self {
        Self {
            label: label.into(),
            base_col,
            hover_col,
            text_col: TEXT,
            hover_t: 0.0,
            selected: false,
            focused: false,
            alpha: 1.0,
        }
    }

    pub fn update_hover(&mut self, hovered: bool, dt: f32, reduce_motion: bool) {
        let target = if hovered || self.selected || self.focused {
            1.0
        } else {
            0.0
        };
        if reduce_motion {
            self.hover_t = target;
        } else {
            let k = (dt * 14.0).clamp(0.0, 1.0);
            self.hover_t += (target - self.hover_t) * k;
        }
    }
}

pub fn draw_button(
    sdf: &mut SdfBatch,
    text: &mut TextBatch,
    rect: UiRect,
    btn: &ButtonStyle,
    font_px: f32,
    scale: f32,
) {
    if btn.alpha <= 0.01 {
        return;
    }
    let hover = btn.hover_t.clamp(0.0, 1.0);
    let hover_eased = hover * hover * (3.0 - 2.0 * hover);
    let r = rect;
    let corner = (7.0 * scale).clamp(4.0, 12.0);

    let bg = mix_rgb(btn.base_col, btn.hover_col, hover_eased * 0.85);
    let bg_dark = mix_rgb(PANEL, bg, 0.36 + 0.30 * hover_eased + if btn.selected { 0.25 } else { 0.0 });
    let edge_col = mix_rgb(btn.base_col, [255, 255, 255], 0.35 + 0.45 * hover_eased);

    if hover > 0.05 || btn.focused || btn.selected {
        sdf.panel_outline(
            r.x - 2.0,
            r.y - 2.0,
            r.w + 4.0,
            r.h + 4.0,
            corner + 2.0,
            2.2,
            linear_rgba_f(edge_col, (0.32 * hover_eased + if btn.focused { 0.45 } else { 0.0 }) * btn.alpha, 1.0),
        );
    }

    draw_panel(
        sdf,
        r,
        corner,
        1.8,
        bg_dark,
        ((208.0 + 36.0 * hover_eased) * btn.alpha) as u8,
        edge_col,
        ((120.0 + 115.0 * hover_eased) * btn.alpha) as u8,
        3.0 * scale,
    );

    // Subtle accent left/bottom micro-bar on active buttons
    let accent_bar_col = mix_rgb(btn.hover_col, [255, 255, 255], 0.25);
    sdf.panel(
        r.x + 10.0 * scale,
        r.y + 3.0 * scale,
        r.w - 20.0 * scale,
        2.0 * scale,
        1.0,
        linear_rgba_f(accent_bar_col, (0.45 + 0.45 * hover_eased) * btn.alpha, 1.0),
    );

    let (cx, cy) = r.center();
    let txt_col = if btn.selected || hover_eased > 0.5 {
        mix_rgb(btn.text_col, [255, 255, 255], 0.5)
    } else {
        btn.text_col
    };
    text.draw_hdr(
        btn.label.as_str(),
        FontId::Bold,
        font_px,
        cx,
        cy,
        AlignX::Center,
        AlignY::Center,
        txt_col,
        btn.alpha,
        true,
    );
}

#[allow(clippy::too_many_arguments)]
pub fn draw_chip(
    sdf: &mut SdfBatch,
    text: &mut TextBatch,
    rect: UiRect,
    label: &str,
    active: bool,
    hovered: bool,
    accent: [u8; 3],
    font_px: f32,
    scale: f32,
    alpha: f32,
) {
    let corner = (6.0 * scale).clamp(3.0, 10.0);
    let fill = if active {
        mix_rgb(PANEL, accent, 0.34)
    } else if hovered {
        mix_rgb(PANEL, accent, 0.16)
    } else {
        PANEL
    };
    let border = if active {
        accent
    } else if hovered {
        mix_rgb(MUTED, accent, 0.6)
    } else {
        mix_rgb(PANEL, MUTED, 0.45)
    };
    draw_panel(
        sdf,
        rect,
        corner,
        if active { 2.0 } else { 1.4 },
        fill,
        ((if active { 235.0 } else { 190.0 }) * alpha) as u8,
        border,
        ((if active { 230.0 } else if hovered { 180.0 } else { 95.0 }) * alpha) as u8,
        2.0 * scale,
    );
    let (cx, cy) = rect.center();
    let txt_col = if active {
        [248, 252, 255]
    } else if hovered {
        TEXT
    } else {
        MUTED
    };
    text.draw_hdr(
        label,
        FontId::Bold,
        font_px,
        cx,
        cy,
        AlignX::Center,
        AlignY::Center,
        txt_col,
        alpha,
        true,
    );
}

#[allow(clippy::too_many_arguments)]
pub fn draw_slider(
    sdf: &mut SdfBatch,
    track: UiRect,
    frac: f32,
    accent: [u8; 3],
    hovered: bool,
    grabbed: bool,
    focused: bool,
    scale: f32,
) {
    let f = frac.clamp(0.0, 1.0);
    let corner = (track.h * 0.5).max(2.0);
    if focused || grabbed {
        sdf.panel_outline(
            track.x - 4.0,
            track.y - 4.0,
            track.w + 8.0,
            track.h + 8.0,
            corner + 3.0,
            1.8,
            linear_rgba(accent, if grabbed { 220 } else { 150 }, 1.0),
        );
    }
    sdf.panel(
        track.x,
        track.y,
        track.w,
        track.h,
        corner,
        linear_rgba([24, 34, 52], 235, 1.0),
    );
    let fill_w = (track.w * f).max(0.0);
    if fill_w > 1.0 {
        sdf.panel(
            track.x,
            track.y,
            fill_w,
            track.h,
            corner,
            linear_rgba(accent, if hovered || grabbed { 255 } else { 225 }, 1.0),
        );
    }
    let kx = track.x + fill_w;
    let ky = track.y + track.h * 0.5;
    let kr = (track.h * 0.85 + if grabbed { 2.5 } else if hovered { 1.5 } else { 0.0 }) * scale.clamp(0.85, 1.3);
    sdf.circle(kx, ky, kr, linear_rgba([245, 250, 255], 255, 1.0));
    sdf.ring(kx, ky, kr, kr, 1.6, linear_rgba(accent, 235, 1.0));
}
