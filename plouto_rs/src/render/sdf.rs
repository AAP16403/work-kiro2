use bytemuck::{Pod, Zeroable};

#[repr(C)]
#[derive(Clone, Copy, Debug, Pod, Zeroable)]
pub struct SdfInstance {
    pub p0: [f32; 2],
    pub p1: [f32; 2],
    pub params: [f32; 4],
    pub color: [f32; 4],
    pub kind: u32,
    pub _pad: [u32; 3],
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Pod, Zeroable)]
pub struct ScreenUniform {
    pub resolution: [f32; 2],
    pub _pad: [f32; 2],
}

/// Convert sRGB channel byte `0..255` into linear optical brightness for HDR pipeline.
#[inline]
pub fn srgb_ch_to_linear(c: u8) -> f32 {
    let x = (c as f32) / 255.0;
    if x <= 0.04045 {
        x / 12.92
    } else {
        ((x + 0.055) / 1.055).powf(2.4)
    }
}

/// Pack sRGB RGB + alpha byte `0..255` into linear RGBA with optional HDR emission multiplier.
#[inline]
pub fn linear_rgba(rgb: [u8; 3], alpha_u8: u8, hdr_boost: f32) -> [f32; 4] {
    [
        srgb_ch_to_linear(rgb[0]) * hdr_boost,
        srgb_ch_to_linear(rgb[1]) * hdr_boost,
        srgb_ch_to_linear(rgb[2]) * hdr_boost,
        (alpha_u8 as f32) / 255.0,
    ]
}

#[inline]
pub fn linear_rgba_f(rgb: [u8; 3], alpha01: f32, hdr_boost: f32) -> [f32; 4] {
    [
        srgb_ch_to_linear(rgb[0]) * hdr_boost,
        srgb_ch_to_linear(rgb[1]) * hdr_boost,
        srgb_ch_to_linear(rgb[2]) * hdr_boost,
        alpha01.clamp(0.0, 1.0),
    ]
}

/// Mix two RGB colors by `t` in `0..1`.
#[inline]
pub fn mix_rgb(a: [u8; 3], b: [u8; 3], t: f32) -> [u8; 3] {
    let k = t.clamp(0.0, 1.0);
    [
        (a[0] as f32 + (b[0] as f32 - a[0] as f32) * k).round() as u8,
        (a[1] as f32 + (b[1] as f32 - a[1] as f32) * k).round() as u8,
        (a[2] as f32 + (b[2] as f32 - a[2] as f32) * k).round() as u8,
    ]
}

/// Accumulates GPU 2D SDF primitives for one render layer.
#[derive(Default, Clone)]
pub struct SdfBatch {
    pub instances: Vec<SdfInstance>,
}

impl SdfBatch {
    pub fn with_capacity(cap: usize) -> Self {
        Self {
            instances: Vec::with_capacity(cap),
        }
    }

    #[inline]
    pub fn clear(&mut self) {
        self.instances.clear();
    }

    #[inline]
    pub fn circle(&mut self, x: f32, y: f32, r: f32, color: [f32; 4]) {
        self.ellipse(x, y, r, r, 0.0, color);
    }

    #[inline]
    pub fn ellipse(&mut self, x: f32, y: f32, rx: f32, ry: f32, rot_rad: f32, color: [f32; 4]) {
        if rx <= 0.05 || ry <= 0.05 || color[3] <= 0.001 {
            return;
        }
        self.instances.push(SdfInstance {
            p0: [x, y],
            p1: [rx, ry],
            params: [rot_rad, 0.0, 0.75, 0.0],
            color,
            kind: 0,
            _pad: [0; 3],
        });
    }

    #[inline]
    pub fn ring(&mut self, x: f32, y: f32, rx: f32, ry: f32, stroke: f32, color: [f32; 4]) {
        if rx <= 0.1 || ry <= 0.1 || stroke <= 0.05 || color[3] <= 0.001 {
            return;
        }
        self.instances.push(SdfInstance {
            p0: [x, y],
            p1: [rx, ry],
            params: [0.0, stroke, 0.8, 0.0],
            color,
            kind: 0,
            _pad: [0; 3],
        });
    }

    /// Soft radial HDR glow halo matching `glow.py` falloff exponent.
    #[inline]
    pub fn glow(&mut self, x: f32, y: f32, r: f32, falloff_pow: f32, color: [f32; 4]) {
        if r <= 0.5 || color[3] <= 0.001 {
            return;
        }
        self.instances.push(SdfInstance {
            p0: [x, y],
            p1: [r, r],
            params: [0.0, 0.0, falloff_pow.max(1.1), 0.0],
            color,
            kind: 0,
            _pad: [0; 3],
        });
    }

    #[inline]
    pub fn ellipse_glow(
        &mut self,
        x: f32,
        y: f32,
        rx: f32,
        ry: f32,
        falloff_pow: f32,
        color: [f32; 4],
    ) {
        if rx <= 0.5 || ry <= 0.5 || color[3] <= 0.001 {
            return;
        }
        self.instances.push(SdfInstance {
            p0: [x, y],
            p1: [rx, ry],
            params: [0.0, 0.0, falloff_pow.max(1.1), 0.0],
            color,
            kind: 0,
            _pad: [0; 3],
        });
    }

    #[inline]
    pub fn line(&mut self, x0: f32, y0: f32, x1: f32, y1: f32, thickness: f32, color: [f32; 4]) {
        if thickness <= 0.05 || color[3] <= 0.001 {
            return;
        }
        self.instances.push(SdfInstance {
            p0: [x0, y0],
            p1: [x1, y1],
            params: [thickness * 0.5, 0.8, 0.0, 0.0],
            color,
            kind: 1,
            _pad: [0; 3],
        });
    }

    /// Filled bottom-left anchored axis-aligned rectangle.
    #[inline]
    pub fn rect(&mut self, x: f32, y: f32, w: f32, h: f32, color: [f32; 4]) {
        self.rrect(x + w * 0.5, y + h * 0.5, w * 0.5, h * 0.5, 0.0, 0.0, color);
    }

    /// Filled or stroked rounded rect centered at `(cx, cy)` with half-sizes `(hw, hh)`.
    #[inline]
    pub fn rrect(
        &mut self,
        cx: f32,
        cy: f32,
        hw: f32,
        hh: f32,
        rot_rad: f32,
        corner_r: f32,
        color: [f32; 4],
    ) {
        if hw <= 0.05 || hh <= 0.05 || color[3] <= 0.001 {
            return;
        }
        self.instances.push(SdfInstance {
            p0: [cx, cy],
            p1: [hw, hh],
            params: [rot_rad, corner_r, 0.0, 0.8],
            color,
            kind: 2,
            _pad: [0; 3],
        });
    }

    /// Bottom-left anchored rounded rectangle.
    #[inline]
    pub fn panel(&mut self, x: f32, y: f32, w: f32, h: f32, corner_r: f32, color: [f32; 4]) {
        self.rrect(x + w * 0.5, y + h * 0.5, w * 0.5, h * 0.5, 0.0, corner_r, color);
    }

    /// Bottom-left anchored stroked rounded rectangle border.
    #[inline]
    pub fn panel_outline(
        &mut self,
        x: f32,
        y: f32,
        w: f32,
        h: f32,
        corner_r: f32,
        stroke: f32,
        color: [f32; 4],
    ) {
        if w <= 0.1 || h <= 0.1 || stroke <= 0.05 || color[3] <= 0.001 {
            return;
        }
        self.instances.push(SdfInstance {
            p0: [x + w * 0.5, y + h * 0.5],
            p1: [w * 0.5, h * 0.5],
            params: [0.0, corner_r, stroke, 0.8],
            color,
            kind: 2,
            _pad: [0; 3],
        });
    }

    #[inline]
    pub fn arc(
        &mut self,
        cx: f32,
        cy: f32,
        radius: f32,
        thickness: f32,
        start_rad: f32,
        sweep_rad: f32,
        color: [f32; 4],
    ) {
        self.arc_aspect(cx, cy, radius, thickness, start_rad, sweep_rad, 1.0, color);
    }

    #[inline]
    pub fn arc_aspect(
        &mut self,
        cx: f32,
        cy: f32,
        radius: f32,
        thickness: f32,
        start_rad: f32,
        sweep_rad: f32,
        aspect_y: f32,
        color: [f32; 4],
    ) {
        if radius <= 0.2 || thickness <= 0.05 || sweep_rad.abs() <= 1e-4 || color[3] <= 0.001 {
            return;
        }
        self.instances.push(SdfInstance {
            p0: [cx, cy],
            p1: [radius, thickness * 0.5],
            params: [start_rad, sweep_rad, 0.0, aspect_y],
            color,
            kind: 3,
            _pad: [0; 3],
        });
    }

    #[inline]
    pub fn sector(
        &mut self,
        cx: f32,
        cy: f32,
        radius: f32,
        start_rad: f32,
        sweep_rad: f32,
        aspect_y: f32,
        color: [f32; 4],
    ) {
        if radius <= 0.2 || sweep_rad.abs() <= 1e-4 || color[3] <= 0.001 {
            return;
        }
        self.instances.push(SdfInstance {
            p0: [cx, cy],
            p1: [radius, 1.0],
            params: [start_rad, sweep_rad, 1.0, aspect_y],
            color,
            kind: 3,
            _pad: [0; 3],
        });
    }

    #[inline]
    pub fn triangle(&mut self, a: [f32; 2], b: [f32; 2], c: [f32; 2], color: [f32; 4]) {
        if color[3] <= 0.001 {
            return;
        }
        let ab = [b[0] - a[0], b[1] - a[1]];
        let ac = [c[0] - a[0], c[1] - a[1]];
        let area_twice = ab[0] * ac[1] - ab[1] * ac[0];
        if !area_twice.is_finite() || area_twice.abs() <= 1e-3 {
            return;
        }
        self.instances.push(SdfInstance {
            p0: a,
            p1: b,
            params: [c[0], c[1], 0.75, 0.0],
            color,
            kind: 4,
            _pad: [0; 3],
        });
    }

    #[inline]
    pub fn quad(&mut self, a: [f32; 2], b: [f32; 2], c: [f32; 2], d: [f32; 2], color: [f32; 4]) {
        self.triangle(a, b, c, color);
        self.triangle(a, c, d, color);
    }

    /// Filled convex polygon using triangle fan around centroid/first vertex.
    pub fn polygon(&mut self, pts: &[[f32; 2]], color: [f32; 4]) {
        if pts.len() < 3 || color[3] <= 0.001 {
            return;
        }
        for i in 1..pts.len() - 1 {
            self.triangle(pts[0], pts[i], pts[i + 1], color);
        }
    }

    pub fn polyline_closed(&mut self, pts: &[[f32; 2]], thickness: f32, color: [f32; 4]) {
        if pts.len() < 2 {
            return;
        }
        for i in 0..pts.len() {
            let a = pts[i];
            let b = pts[(i + 1) % pts.len()];
            self.line(a[0], a[1], b[0], b[1], thickness, color);
        }
    }
}

pub struct SdfRenderer {
    uniform_buf: wgpu::Buffer,
    bind_group: wgpu::BindGroup,
    hdr_alpha_pipeline: wgpu::RenderPipeline,
    hdr_add_pipeline: wgpu::RenderPipeline,
    ui_alpha_pipeline: wgpu::RenderPipeline,
    ui_add_pipeline: wgpu::RenderPipeline,
    instance_buf: wgpu::Buffer,
    instance_cap: usize,
}

impl SdfRenderer {
    pub fn new(
        device: &wgpu::Device,
        hdr_format: wgpu::TextureFormat,
        ui_format: wgpu::TextureFormat,
        width: u32,
        height: u32,
    ) -> Self {
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("sdf_shader"),
            source: wgpu::ShaderSource::Wgsl(include_str!("sdf_shader.wgsl").into()),
        });

        let uniform = ScreenUniform {
            resolution: [width.max(1) as f32, height.max(1) as f32],
            _pad: [0.0; 2],
        };
        let uniform_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("sdf_screen_uniform"),
            size: std::mem::size_of::<ScreenUniform>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let _ = uniform;

        let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("sdf_bgl"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::VERTEX,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            }],
        });

        let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("sdf_bg"),
            layout: &bgl,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: uniform_buf.as_entire_binding(),
            }],
        });

        let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("sdf_layout"),
            bind_group_layouts: &[&bgl],
            push_constant_ranges: &[],
        });

        let inst_attrs = [
            wgpu::VertexAttribute {
                offset: 0,
                shader_location: 0,
                format: wgpu::VertexFormat::Float32x2,
            },
            wgpu::VertexAttribute {
                offset: 8,
                shader_location: 1,
                format: wgpu::VertexFormat::Float32x2,
            },
            wgpu::VertexAttribute {
                offset: 16,
                shader_location: 2,
                format: wgpu::VertexFormat::Float32x4,
            },
            wgpu::VertexAttribute {
                offset: 32,
                shader_location: 3,
                format: wgpu::VertexFormat::Float32x4,
            },
            wgpu::VertexAttribute {
                offset: 48,
                shader_location: 4,
                format: wgpu::VertexFormat::Uint32,
            },
        ];

        let make_pipeline = |label: &str, format: wgpu::TextureFormat, blend: wgpu::BlendState| {
            device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                label: Some(label),
                layout: Some(&layout),
                vertex: wgpu::VertexState {
                    module: &shader,
                    entry_point: Some("vs_main"),
                    buffers: &[wgpu::VertexBufferLayout {
                        array_stride: std::mem::size_of::<SdfInstance>() as u64,
                        step_mode: wgpu::VertexStepMode::Instance,
                        attributes: &inst_attrs,
                    }],
                    compilation_options: Default::default(),
                },
                fragment: Some(wgpu::FragmentState {
                    module: &shader,
                    entry_point: Some("fs_main"),
                    targets: &[Some(wgpu::ColorTargetState {
                        format,
                        blend: Some(blend),
                        write_mask: wgpu::ColorWrites::ALL,
                    })],
                    compilation_options: Default::default(),
                }),
                primitive: wgpu::PrimitiveState::default(),
                depth_stencil: None,
                multisample: wgpu::MultisampleState::default(),
                multiview: None,
                cache: None,
            })
        };

        let additive_blend = wgpu::BlendState {
            color: wgpu::BlendComponent {
                src_factor: wgpu::BlendFactor::SrcAlpha,
                dst_factor: wgpu::BlendFactor::One,
                operation: wgpu::BlendOperation::Add,
            },
            alpha: wgpu::BlendComponent::OVER,
        };

        let hdr_alpha_pipeline =
            make_pipeline("sdf_hdr_alpha", hdr_format, wgpu::BlendState::ALPHA_BLENDING);
        let hdr_add_pipeline = make_pipeline("sdf_hdr_add", hdr_format, additive_blend);
        let ui_alpha_pipeline =
            make_pipeline("sdf_ui_alpha", ui_format, wgpu::BlendState::ALPHA_BLENDING);
        let ui_add_pipeline = make_pipeline("sdf_ui_add", ui_format, additive_blend);

        let initial_cap = 16_384;
        let instance_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("sdf_instances"),
            size: (initial_cap * std::mem::size_of::<SdfInstance>()) as u64,
            usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });

        Self {
            uniform_buf,
            bind_group,
            hdr_alpha_pipeline,
            hdr_add_pipeline,
            ui_alpha_pipeline,
            ui_add_pipeline,
            instance_buf,
            instance_cap: initial_cap,
        }
    }

    pub fn upload_and_draw(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        width: u32,
        height: u32,
        hdr_view: &wgpu::TextureView,
        hdr_alpha: &SdfBatch,
        hdr_add: &SdfBatch,
        encoder: &mut wgpu::CommandEncoder,
        clear_hdr: Option<wgpu::Color>,
    ) -> (usize, usize) {
        self.upload_resolution(queue, width, height);
        let a_len = hdr_alpha.instances.len();
        let b_len = hdr_add.instances.len();
        let total = a_len + b_len;
        if total == 0 && clear_hdr.is_none() {
            return (0, 0);
        }
        self.ensure_capacity(device, total);
        if a_len > 0 {
            queue.write_buffer(
                &self.instance_buf,
                0,
                bytemuck::cast_slice(&hdr_alpha.instances),
            );
        }
        if b_len > 0 {
            let offset = (a_len * std::mem::size_of::<SdfInstance>()) as u64;
            queue.write_buffer(
                &self.instance_buf,
                offset,
                bytemuck::cast_slice(&hdr_add.instances),
            );
        }

        let load = match clear_hdr {
            Some(c) => wgpu::LoadOp::Clear(c),
            None => wgpu::LoadOp::Load,
        };
        let mut rpass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("sdf_hdr_pass"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: hdr_view,
                resolve_target: None,
                ops: wgpu::Operations {
                    load,
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: None,
            occlusion_query_set: None,
            timestamp_writes: None,
        });
        if a_len > 0 {
            rpass.set_pipeline(&self.hdr_alpha_pipeline);
            rpass.set_bind_group(0, &self.bind_group, &[]);
            rpass.set_vertex_buffer(0, self.instance_buf.slice(..));
            rpass.draw(0..6, 0..a_len as u32);
        }
        if b_len > 0 {
            rpass.set_pipeline(&self.hdr_add_pipeline);
            rpass.set_bind_group(0, &self.bind_group, &[]);
            rpass.set_vertex_buffer(0, self.instance_buf.slice(..));
            rpass.draw(0..6, (a_len as u32)..((a_len + b_len) as u32));
        }
        (0, a_len + b_len)
    }

    pub fn draw_ui_pass<'a>(
        &'a mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        width: u32,
        height: u32,
        ui_view: &wgpu::TextureView,
        ui_alpha: &SdfBatch,
        ui_add: &SdfBatch,
        encoder: &mut wgpu::CommandEncoder,
    ) {
        self.upload_resolution(queue, width, height);
        let a_len = ui_alpha.instances.len();
        let b_len = ui_add.instances.len();
        let total = a_len + b_len;
        if total == 0 {
            return;
        }
        self.ensure_capacity(device, total);
        if a_len > 0 {
            queue.write_buffer(&self.instance_buf, 0, bytemuck::cast_slice(&ui_alpha.instances));
        }
        if b_len > 0 {
            let offset = (a_len * std::mem::size_of::<SdfInstance>()) as u64;
            queue.write_buffer(&self.instance_buf, offset, bytemuck::cast_slice(&ui_add.instances));
        }
        let mut rpass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("sdf_ui_pass"),
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
        if a_len > 0 {
            rpass.set_pipeline(&self.ui_alpha_pipeline);
            rpass.set_bind_group(0, &self.bind_group, &[]);
            rpass.set_vertex_buffer(0, self.instance_buf.slice(..));
            rpass.draw(0..6, 0..a_len as u32);
        }
        if b_len > 0 {
            rpass.set_pipeline(&self.ui_add_pipeline);
            rpass.set_bind_group(0, &self.bind_group, &[]);
            rpass.set_vertex_buffer(0, self.instance_buf.slice(..));
            rpass.draw(0..6, (a_len as u32)..((a_len + b_len) as u32));
        }
    }

    /// Wait: two separate instance buffers (or sub-ranges in one combined buffer per frame!)
    /// prevent overwrite between HDR pass and UI pass when submitted in the same CommandEncoder!
    pub fn draw_combined_world_and_ui(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        width: u32,
        height: u32,
        hdr_view: &wgpu::TextureView,
        ui_view: &wgpu::TextureView,
        hdr_alpha: &SdfBatch,
        hdr_add: &SdfBatch,
        ui_alpha: &SdfBatch,
        ui_add: &SdfBatch,
        encoder_world: &mut wgpu::CommandEncoder,
        encoder_ui: &mut wgpu::CommandEncoder,
        clear_hdr: wgpu::Color,
    ) {
        self.upload_resolution(queue, width, height);
        let h_a = hdr_alpha.instances.len();
        let h_b = hdr_add.instances.len();
        let u_a = ui_alpha.instances.len();
        let u_b = ui_add.instances.len();
        let total = h_a + h_b + u_a + u_b;
        self.ensure_capacity(device, total.max(1));

        let stride = std::mem::size_of::<SdfInstance>();
        if h_a > 0 {
            queue.write_buffer(&self.instance_buf, 0, bytemuck::cast_slice(&hdr_alpha.instances));
        }
        if h_b > 0 {
            queue.write_buffer(
                &self.instance_buf,
                (h_a * stride) as u64,
                bytemuck::cast_slice(&hdr_add.instances),
            );
        }
        if u_a > 0 {
            queue.write_buffer(
                &self.instance_buf,
                ((h_a + h_b) * stride) as u64,
                bytemuck::cast_slice(&ui_alpha.instances),
            );
        }
        if u_b > 0 {
            queue.write_buffer(
                &self.instance_buf,
                ((h_a + h_b + u_a) * stride) as u64,
                bytemuck::cast_slice(&ui_add.instances),
            );
        }

        {
            let mut rpass = encoder_world.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("sdf_hdr_pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: hdr_view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(clear_hdr),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                occlusion_query_set: None,
                timestamp_writes: None,
            });
            rpass.set_bind_group(0, &self.bind_group, &[]);
            rpass.set_vertex_buffer(0, self.instance_buf.slice(..));
            if h_a > 0 {
                rpass.set_pipeline(&self.hdr_alpha_pipeline);
                rpass.draw(0..6, 0..h_a as u32);
            }
            if h_b > 0 {
                rpass.set_pipeline(&self.hdr_add_pipeline);
                rpass.draw(0..6, (h_a as u32)..((h_a + h_b) as u32));
            }
        }

        if u_a + u_b > 0 {
            let mut rpass = encoder_ui.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("sdf_ui_pass"),
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
            rpass.set_bind_group(0, &self.bind_group, &[]);
            rpass.set_vertex_buffer(0, self.instance_buf.slice(..));
            let base = (h_a + h_b) as u32;
            if u_a > 0 {
                rpass.set_pipeline(&self.ui_alpha_pipeline);
                rpass.draw(0..6, base..(base + u_a as u32));
            }
            if u_b > 0 {
                rpass.set_pipeline(&self.ui_add_pipeline);
                rpass.draw(0..6, (base + u_a as u32)..(base + (u_a + u_b) as u32));
            }
        }
    }

    /// Encode ONLY the HDR world pass assuming `queue.write_buffer` already populated `[0..h_a+h_b]`
    /// and then UI pass reads `[h_a+h_b..]` cleanly in the SAME `CommandEncoder`!
    pub fn record_world_pass(
        &self,
        hdr_view: &wgpu::TextureView,
        h_a: usize,
        h_b: usize,
        encoder: &mut wgpu::CommandEncoder,
        clear_hdr: wgpu::Color,
    ) {
        let mut rpass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("sdf_hdr_pass"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: hdr_view,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Clear(clear_hdr),
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: None,
            occlusion_query_set: None,
            timestamp_writes: None,
        });
        rpass.set_bind_group(0, &self.bind_group, &[]);
        rpass.set_vertex_buffer(0, self.instance_buf.slice(..));
        if h_a > 0 {
            rpass.set_pipeline(&self.hdr_alpha_pipeline);
            rpass.draw(0..6, 0..h_a as u32);
        }
        if h_b > 0 {
            rpass.set_pipeline(&self.hdr_add_pipeline);
            rpass.draw(0..6, (h_a as u32)..((h_a + h_b) as u32));
        }
    }

    pub fn prepare_buffers(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        width: u32,
        height: u32,
        hdr_alpha: &SdfBatch,
        hdr_add: &SdfBatch,
        ui_alpha: &SdfBatch,
        ui_add: &SdfBatch,
    ) -> (usize, usize, usize, usize) {
        self.upload_resolution(queue, width, height);
        let h_a = hdr_alpha.instances.len();
        let h_b = hdr_add.instances.len();
        let u_a = ui_alpha.instances.len();
        let u_b = ui_add.instances.len();
        let total = h_a + h_b + u_a + u_b;
        self.ensure_capacity(device, total.max(1));
        let stride = std::mem::size_of::<SdfInstance>();
        if h_a > 0 {
            queue.write_buffer(&self.instance_buf, 0, bytemuck::cast_slice(&hdr_alpha.instances));
        }
        if h_b > 0 {
            queue.write_buffer(
                &self.instance_buf,
                (h_a * stride) as u64,
                bytemuck::cast_slice(&hdr_add.instances),
            );
        }
        if u_a > 0 {
            queue.write_buffer(
                &self.instance_buf,
                ((h_a + h_b) * stride) as u64,
                bytemuck::cast_slice(&ui_alpha.instances),
            );
        }
        if u_b > 0 {
            queue.write_buffer(
                &self.instance_buf,
                ((h_a + h_b + u_a) * stride) as u64,
                bytemuck::cast_slice(&ui_add.instances),
            );
        }
        (h_a, h_b, u_a, u_b)
    }

    pub fn record_ui_pass(
        &self,
        ui_view: &wgpu::TextureView,
        offset_base: usize,
        u_a: usize,
        u_b: usize,
        encoder: &mut wgpu::CommandEncoder,
    ) {
        if u_a + u_b == 0 {
            return;
        }
        let mut rpass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("sdf_ui_pass"),
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
        rpass.set_bind_group(0, &self.bind_group, &[]);
        rpass.set_vertex_buffer(0, self.instance_buf.slice(..));
        let base = offset_base as u32;
        if u_a > 0 {
            rpass.set_pipeline(&self.ui_alpha_pipeline);
            rpass.draw(0..6, base..(base + u_a as u32));
        }
        if u_b > 0 {
            rpass.set_pipeline(&self.ui_add_pipeline);
            rpass.draw(0..6, (base + u_a as u32)..(base + (u_a + u_b) as u32));
        }
    }

    fn upload_resolution(&self, queue: &wgpu::Queue, width: u32, height: u32) {
        let uniform = ScreenUniform {
            resolution: [width.max(1) as f32, height.max(1) as f32],
            _pad: [0.0; 2],
        };
        queue.write_buffer(&self.uniform_buf, 0, bytemuck::bytes_of(&uniform));
    }

    fn ensure_capacity(&mut self, device: &wgpu::Device, needed: usize) {
        if needed <= self.instance_cap {
            return;
        }
        let next_cap = needed.next_power_of_two().max(16_384);
        self.instance_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("sdf_instances"),
            size: (next_cap * std::mem::size_of::<SdfInstance>()) as u64,
            usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        self.instance_cap = next_cap;
    }
}
