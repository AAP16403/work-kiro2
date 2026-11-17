use std::collections::HashMap;
use std::fs;

use ab_glyph::{Font, FontArc, GlyphId, ScaleFont};
use bytemuck::{Pod, Zeroable};

use crate::assets::resolve_asset;
use crate::render::sdf::{linear_rgba, srgb_ch_to_linear, ScreenUniform};

const ATLAS_SIZE: u32 = 2048;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum FontId {
    Head,
    Bold,
    Regular,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AlignX {
    Left,
    Center,
    Right,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AlignY {
    Top,
    Center,
    Bottom,
    Baseline,
}

#[derive(Debug, Clone)]
pub struct TextDraw {
    pub text: String,
    pub font: FontId,
    pub size_px: f32,
    pub x: f32,
    pub y: f32,
    pub align_x: AlignX,
    pub align_y: AlignY,
    pub color: [f32; 4],
    pub shadow: bool,
}

#[derive(Default)]
pub struct TextBatch {
    pub items: Vec<TextDraw>,
}

impl TextBatch {
    pub fn clear(&mut self) {
        self.items.clear();
    }

    pub fn push(&mut self, item: TextDraw) {
        if !item.text.is_empty() && item.color[3] > 0.002 && item.size_px > 1.0 {
            self.items.push(item);
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub fn draw(
        &mut self,
        text: impl Into<String>,
        font: FontId,
        size_px: f32,
        x: f32,
        y: f32,
        align_x: AlignX,
        align_y: AlignY,
        rgb: [u8; 3],
        alpha_u8: u8,
        shadow: bool,
    ) {
        self.push(TextDraw {
            text: text.into(),
            font,
            size_px,
            x,
            y,
            align_x,
            align_y,
            color: linear_rgba(rgb, alpha_u8, 1.0),
            shadow,
        });
    }

    #[allow(clippy::too_many_arguments)]
    pub fn draw_hdr(
        &mut self,
        text: impl Into<String>,
        font: FontId,
        size_px: f32,
        x: f32,
        y: f32,
        align_x: AlignX,
        align_y: AlignY,
        rgb: [u8; 3],
        alpha01: f32,
        shadow: bool,
    ) {
        self.push(TextDraw {
            text: text.into(),
            font,
            size_px,
            x,
            y,
            align_x,
            align_y,
            color: [
                srgb_ch_to_linear(rgb[0]),
                srgb_ch_to_linear(rgb[1]),
                srgb_ch_to_linear(rgb[2]),
                alpha01.clamp(0.0, 1.0),
            ],
            shadow,
        });
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
struct GlyphKey {
    font: FontId,
    px_tenths: u32,
    glyph_id: u16,
}

#[derive(Debug, Clone, Copy)]
struct CachedGlyph {
    uv: [f32; 4], // u0, v0 (top), u1, v1 (bot)
    offset_x: f32,
    top_from_baseline: f32, // positive up from baseline
    bot_from_baseline: f32, // offset up/down from baseline
    width: f32,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Pod, Zeroable)]
struct GlyphInstance {
    rect: [f32; 4],
    uv: [f32; 4],
    color: [f32; 4],
}

pub struct FontPack {
    pub head: FontArc,
    pub bold: FontArc,
    pub regular: FontArc,
}

impl FontPack {
    pub fn load() -> Result<Self, String> {
        let load_one = |candidates: &[&str]| -> Result<FontArc, String> {
            for rel in candidates {
                if let Some(path) = resolve_asset(rel) {
                    let bytes = fs::read(&path)
                        .map_err(|e| format!("failed reading font {}: {e}", path.display()))?;
                    return FontArc::try_from_vec(bytes)
                        .map_err(|e| format!("invalid font {}: {e}", path.display()));
                }
            }
            Err(format!("could not locate font among {:?}", candidates))
        };

        let head = load_one(&[
            "assets/fonts/Orbitron-Variable.ttf",
            "assets/fonts/Orbitron-Bold.ttf",
        ])?;
        let bold = load_one(&[
            "assets/fonts/Rajdhani-SemiBold.ttf",
            "assets/fonts/Rajdhani-Bold.ttf",
        ])?;
        let regular = load_one(&["assets/fonts/Rajdhani-Regular.ttf"])?;
        Ok(Self {
            head,
            bold,
            regular,
        })
    }

    #[inline]
    pub fn get(&self, id: FontId) -> &FontArc {
        match id {
            FontId::Head => &self.head,
            FontId::Bold => &self.bold,
            FontId::Regular => &self.regular,
        }
    }

    /// Measure `(width, height)` in pixels matching Pyglet's 96-dpi scale (`px = pt * 1.333`).
    pub fn measure(&self, id: FontId, px_size: f32, text: &str) -> (f32, f32) {
        let scaled = self.get(id).as_scaled(px_size);
        let mut w = 0.0_f32;
        let mut prev: Option<GlyphId> = None;
        for ch in text.chars() {
            if ch == '\n' {
                continue;
            }
            let gid = scaled.glyph_id(ch);
            if let Some(p) = prev {
                w += scaled.kern(p, gid);
            }
            w += scaled.h_advance(gid);
            prev = Some(gid);
        }
        let h = (scaled.ascent() - scaled.descent()).max(px_size);
        (w, h)
    }

    /// Truncate with ellipsis or wrap cleanly into `max_width` lines.
    pub fn wrap_lines(&self, id: FontId, px_size: f32, text: &str, max_width: f32) -> Vec<String> {
        if max_width <= 8.0 {
            return vec![text.to_string()];
        }
        let mut lines = Vec::new();
        for raw_line in text.lines() {
            let mut current = String::new();
            for word in raw_line.split_whitespace() {
                let candidate = if current.is_empty() {
                    word.to_string()
                } else {
                    format!("{current} {word}")
                };
                if self.measure(id, px_size, &candidate).0 <= max_width || current.is_empty() {
                    current = candidate;
                } else {
                    lines.push(current);
                    current = word.to_string();
                }
            }
            if !current.is_empty() {
                lines.push(current);
            }
        }
        if lines.is_empty() && !text.is_empty() {
            lines.push(text.to_string());
        }
        lines
    }

    pub fn fit_text(&self, id: FontId, px_size: f32, text: &str, max_width: f32) -> String {
        if self.measure(id, px_size, text).0 <= max_width {
            return text.to_string();
        }
        let mut chars: Vec<char> = text.chars().collect();
        while chars.len() > 1 {
            chars.pop();
            let candidate: String = chars.iter().collect::<String>() + "...";
            if self.measure(id, px_size, &candidate).0 <= max_width {
                return candidate;
            }
        }
        "...".to_string()
    }
}

pub struct TextRenderer {
    pub fonts: FontPack,
    atlas_cpu: Vec<u8>,
    cursor_x: u32,
    cursor_y: u32,
    row_h: u32,
    cache: HashMap<GlyphKey, Option<CachedGlyph>>,
    dirty: bool,

    atlas_tex: wgpu::Texture,
    uniform_buf: wgpu::Buffer,
    bind_group: wgpu::BindGroup,
    pipeline: wgpu::RenderPipeline,
    instance_buf: wgpu::Buffer,
    instance_cap: usize,
    staging: Vec<GlyphInstance>,
}

impl TextRenderer {
    pub fn new(device: &wgpu::Device, ui_format: wgpu::TextureFormat) -> Result<Self, String> {
        let fonts = FontPack::load()?;
        let atlas_tex = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("glyph_atlas"),
            size: wgpu::Extent3d {
                width: ATLAS_SIZE,
                height: ATLAS_SIZE,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::R8Unorm,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        let atlas_view = atlas_tex.create_view(&wgpu::TextureViewDescriptor::default());
        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("glyph_sampler"),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            address_mode_u: wgpu::AddressMode::ClampToEdge,
            address_mode_v: wgpu::AddressMode::ClampToEdge,
            ..Default::default()
        });

        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("text_shader"),
            source: wgpu::ShaderSource::Wgsl(include_str!("text_shader.wgsl").into()),
        });

        let uniform_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("text_screen_uniform"),
            size: std::mem::size_of::<ScreenUniform>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });

        let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("text_bgl"),
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::VERTEX,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 2,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                    count: None,
                },
            ],
        });

        let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("text_bg"),
            layout: &bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: uniform_buf.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(&atlas_view),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::Sampler(&sampler),
                },
            ],
        });

        let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("text_layout"),
            bind_group_layouts: &[&bgl],
            push_constant_ranges: &[],
        });

        let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("text_pipeline"),
            layout: Some(&layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs_main"),
                buffers: &[wgpu::VertexBufferLayout {
                    array_stride: std::mem::size_of::<GlyphInstance>() as u64,
                    step_mode: wgpu::VertexStepMode::Instance,
                    attributes: &[
                        wgpu::VertexAttribute {
                            offset: 0,
                            shader_location: 0,
                            format: wgpu::VertexFormat::Float32x4,
                        },
                        wgpu::VertexAttribute {
                            offset: 16,
                            shader_location: 1,
                            format: wgpu::VertexFormat::Float32x4,
                        },
                        wgpu::VertexAttribute {
                            offset: 32,
                            shader_location: 2,
                            format: wgpu::VertexFormat::Float32x4,
                        },
                    ],
                }],
                compilation_options: Default::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs_main"),
                targets: &[Some(wgpu::ColorTargetState {
                    format: ui_format,
                    blend: Some(wgpu::BlendState::ALPHA_BLENDING),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
                compilation_options: Default::default(),
            }),
            primitive: wgpu::PrimitiveState::default(),
            depth_stencil: None,
            multisample: wgpu::MultisampleState::default(),
            multiview: None,
            cache: None,
        });

        let initial_cap = 4096;
        let instance_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("text_instances"),
            size: (initial_cap * std::mem::size_of::<GlyphInstance>()) as u64,
            usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });

        Ok(Self {
            fonts,
            atlas_cpu: vec![0u8; (ATLAS_SIZE * ATLAS_SIZE) as usize],
            cursor_x: 1,
            cursor_y: 1,
            row_h: 0,
            cache: HashMap::new(),
            dirty: true,
            atlas_tex,
            uniform_buf,
            bind_group,
            pipeline,
            instance_buf,
            instance_cap: initial_cap,
            staging: Vec::with_capacity(2048),
        })
    }

    fn get_or_rasterize(&mut self, font_id: FontId, px_size: f32, ch: char) -> (GlyphId, Option<CachedGlyph>) {
        let font = self.fonts.get(font_id);
        let gid = font.glyph_id(ch);
        let px_tenths = (px_size.clamp(4.0, 200.0) * 10.0).round() as u32;
        let key = GlyphKey {
            font: font_id,
            px_tenths,
            glyph_id: gid.0,
        };
        if let Some(cached) = self.cache.get(&key) {
            return (gid, *cached);
        }

        let scale = px_tenths as f32 / 10.0;
        let glyph = gid.with_scale_and_position(scale, ab_glyph::point(0.0, 0.0));
        let Some(outlined) = font.outline_glyph(glyph) else {
            self.cache.insert(key, None);
            return (gid, None);
        };

        let bounds = outlined.px_bounds();
        let gw = bounds.width().ceil().max(1.0) as u32;
        let gh = bounds.height().ceil().max(1.0) as u32;
        if gw > ATLAS_SIZE - 4 || gh > ATLAS_SIZE - 4 {
            self.cache.insert(key, None);
            return (gid, None);
        }

        if self.cursor_x + gw + 2 >= ATLAS_SIZE {
            self.cursor_x = 1;
            self.cursor_y += self.row_h + 2;
            self.row_h = 0;
        }
        if self.cursor_y + gh + 2 >= ATLAS_SIZE {
            // Flush and reset atlas cleanly if ever full
            self.atlas_cpu.fill(0);
            self.cache.clear();
            self.cursor_x = 1;
            self.cursor_y = 1;
            self.row_h = 0;
        }

        let ax = self.cursor_x;
        let ay = self.cursor_y;
        self.cursor_x += gw + 2;
        self.row_h = self.row_h.max(gh);

        outlined.draw(|lx, ly, c| {
            let x = ax + lx;
            let y = ay + ly;
            if x < ATLAS_SIZE && y < ATLAS_SIZE {
                let idx = (y * ATLAS_SIZE + x) as usize;
                self.atlas_cpu[idx] = (c.clamp(0.0, 1.0) * 255.0).round() as u8;
            }
        });
        self.dirty = true;

        let cached = CachedGlyph {
            uv: [
                ax as f32 / ATLAS_SIZE as f32,
                ay as f32 / ATLAS_SIZE as f32,
                (ax + gw) as f32 / ATLAS_SIZE as f32,
                (ay + gh) as f32 / ATLAS_SIZE as f32,
            ],
            offset_x: bounds.min.x,
            top_from_baseline: -bounds.min.y,
            bot_from_baseline: -(bounds.min.y + gh as f32),
            width: gw as f32,
        };
        self.cache.insert(key, Some(cached));
        (gid, Some(cached))
    }

    pub fn prepare_and_record(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        width: u32,
        height: u32,
        batch: &TextBatch,
        ui_view: &wgpu::TextureView,
        encoder: &mut wgpu::CommandEncoder,
    ) {
        self.staging.clear();
        for item in &batch.items {
            let scaled = self.fonts.get(item.font).as_scaled(item.size_px);
            let ascent = scaled.ascent();
            let descent = scaled.descent();
            let line_h = (ascent - descent).max(item.size_px * 1.15);

            let lines: Vec<&str> = item.text.split('\n').collect();
            let total_h = lines.len() as f32 * line_h;

            let mut base_y = match item.align_y {
                AlignY::Baseline => item.y,
                AlignY::Bottom => item.y + total_h - line_h - descent,
                AlignY::Top => item.y - ascent,
                AlignY::Center => item.y + (total_h * 0.5) - ascent * 0.65 - (ascent + descent) * 0.25,
            };

            for line in lines {
                let (lw, _) = self.fonts.measure(item.font, item.size_px, line);
                let start_x = match item.align_x {
                    AlignX::Left => item.x,
                    AlignX::Center => item.x - lw * 0.5,
                    AlignX::Right => item.x - lw,
                };

                // Shadow pass (if requested) before crisp main glyphs
                let passes: &[(f32, f32, [f32; 4])] = if item.shadow {
                    &[
                        (
                            1.3,
                            -1.5,
                            [0.01, 0.015, 0.03, (item.color[3] * 0.72).clamp(0.0, 1.0)],
                        ),
                        (0.0, 0.0, item.color),
                    ]
                } else {
                    &[(0.0, 0.0, item.color)]
                };

                for &(dx_sh, dy_sh, col) in passes {
                    let mut pen_x = start_x + dx_sh;
                    let pen_y = base_y + dy_sh;
                    let mut prev: Option<GlyphId> = None;
                    for ch in line.chars() {
                        let (gid, cached_opt) = self.get_or_rasterize(item.font, item.size_px, ch);
                        let sc = self.fonts.get(item.font).as_scaled(item.size_px);
                        if let Some(p) = prev {
                            pen_x += sc.kern(p, gid);
                        }
                        if let Some(g) = cached_opt {
                            let x0 = (pen_x + g.offset_x).round();
                            let x1 = x0 + g.width;
                            let y1 = (pen_y + g.top_from_baseline).round();
                            let y0 = (pen_y + g.bot_from_baseline).round();
                            self.staging.push(GlyphInstance {
                                rect: [x0, y0, x1, y1],
                                uv: g.uv,
                                color: col,
                            });
                        }
                        pen_x += sc.h_advance(gid);
                        prev = Some(gid);
                    }
                }
                base_y -= line_h;
            }
        }

        if self.staging.is_empty() {
            return;
        }

        if self.dirty {
            queue.write_texture(
                wgpu::TexelCopyTextureInfo {
                    texture: &self.atlas_tex,
                    mip_level: 0,
                    origin: wgpu::Origin3d::ZERO,
                    aspect: wgpu::TextureAspect::All,
                },
                &self.atlas_cpu,
                wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(ATLAS_SIZE),
                    rows_per_image: Some(ATLAS_SIZE),
                },
                wgpu::Extent3d {
                    width: ATLAS_SIZE,
                    height: ATLAS_SIZE,
                    depth_or_array_layers: 1,
                },
            );
            self.dirty = false;
        }

        let uniform = ScreenUniform {
            resolution: [width.max(1) as f32, height.max(1) as f32],
            _pad: [0.0; 2],
        };
        queue.write_buffer(&self.uniform_buf, 0, bytemuck::bytes_of(&uniform));

        if self.staging.len() > self.instance_cap {
            self.instance_cap = self.staging.len().next_power_of_two();
            self.instance_buf = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("text_instances"),
                size: (self.instance_cap * std::mem::size_of::<GlyphInstance>()) as u64,
                usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
        }
        queue.write_buffer(&self.instance_buf, 0, bytemuck::cast_slice(&self.staging));

        let mut rp = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("text_pass"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: ui_view,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Load,
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: None,
            occlusion_query_set: None,
            timestamp_writes: None,
        });
        rp.set_pipeline(&self.pipeline);
        rp.set_bind_group(0, &self.bind_group, &[]);
        rp.set_vertex_buffer(0, self.instance_buf.slice(..));
        rp.draw(0..6, 0..self.staging.len() as u32);
    }
}
