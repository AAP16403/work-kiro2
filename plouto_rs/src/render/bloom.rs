use bytemuck::{Pod, Zeroable};

pub const BLOOM_MIPS: usize = 4;

#[repr(C)]
#[derive(Clone, Copy, Debug, Pod, Zeroable)]
pub struct PostFxUniform {
    pub resolution: [f32; 2],
    pub texel_size: [f32; 2],
    pub time: f32,
    pub fx_strength: f32,
    pub combat_intensity: f32,
    pub low_hp_danger: f32,
    pub boss_active: f32,
    pub reduce_motion: f32,
    pub hit_flash: f32,
    pub ultra_flash: f32,
    pub dash_pulse: f32,
    pub boost_pulse: f32,
    pub boss_flash: f32,
    pub fade_alpha: f32,
    pub threshold: f32,
    pub bloom_intensity: f32,
    pub is_srgb_output: f32,
    pub _pad: f32,
}

impl Default for PostFxUniform {
    fn default() -> Self {
        Self {
            resolution: [980.0, 620.0],
            texel_size: [1.0 / 980.0, 1.0 / 620.0],
            time: 0.0,
            fx_strength: 0.7,
            combat_intensity: 0.0,
            low_hp_danger: 0.0,
            boss_active: 0.0,
            reduce_motion: 0.0,
            hit_flash: 0.0,
            ultra_flash: 0.0,
            dash_pulse: 0.0,
            boost_pulse: 0.0,
            boss_flash: 0.0,
            fade_alpha: 0.0,
            threshold: 0.72,
            bloom_intensity: 0.62,
            is_srgb_output: 1.0,
            _pad: 0.0,
        }
    }
}

struct MipLevel {
    _texture: wgpu::Texture,
    view: wgpu::TextureView,
    width: u32,
    height: u32,
    uniform_buf: wgpu::Buffer,
}

pub struct BloomPostProcess {
    pub hdr_format: wgpu::TextureFormat,
    hdr_texture: wgpu::Texture,
    pub hdr_view: wgpu::TextureView,
    mips: Vec<MipLevel>,
    sampler: wgpu::Sampler,
    bgl: wgpu::BindGroupLayout,
    bright_pipeline: wgpu::RenderPipeline,
    down_pipeline: wgpu::RenderPipeline,
    up_pipeline: wgpu::RenderPipeline,
    composite_pipeline: wgpu::RenderPipeline,
    composite_uniform_buf: wgpu::Buffer,
    width: u32,
    height: u32,
    is_srgb_output: bool,
}

impl BloomPostProcess {
    pub fn new(
        device: &wgpu::Device,
        ui_format: wgpu::TextureFormat,
        width: u32,
        height: u32,
    ) -> Self {
        let hdr_format = wgpu::TextureFormat::Rgba16Float;
        let width = width.max(1);
        let height = height.max(1);
        let is_srgb_output = ui_format.is_srgb();

        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("postfx_shader"),
            source: wgpu::ShaderSource::Wgsl(include_str!("postfx.wgsl").into()),
        });

        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("postfx_linear"),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            mipmap_filter: wgpu::FilterMode::Linear,
            address_mode_u: wgpu::AddressMode::ClampToEdge,
            address_mode_v: wgpu::AddressMode::ClampToEdge,
            ..Default::default()
        });

        let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("postfx_bgl"),
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
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
                wgpu::BindGroupLayoutEntry {
                    binding: 3,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
            ],
        });

        let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("postfx_layout"),
            bind_group_layouts: &[&bgl],
            push_constant_ranges: &[],
        });

        let make_pipe = |label: &str,
                         fs_entry: &str,
                         format: wgpu::TextureFormat,
                         blend: Option<wgpu::BlendState>| {
            device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                label: Some(label),
                layout: Some(&layout),
                vertex: wgpu::VertexState {
                    module: &shader,
                    entry_point: Some("vs_fullscreen"),
                    buffers: &[],
                    compilation_options: Default::default(),
                },
                fragment: Some(wgpu::FragmentState {
                    module: &shader,
                    entry_point: Some(fs_entry),
                    targets: &[Some(wgpu::ColorTargetState {
                        format,
                        blend,
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

        let additive = Some(wgpu::BlendState {
            color: wgpu::BlendComponent {
                src_factor: wgpu::BlendFactor::One,
                dst_factor: wgpu::BlendFactor::One,
                operation: wgpu::BlendOperation::Add,
            },
            alpha: wgpu::BlendComponent::OVER,
        });

        let bright_pipeline = make_pipe("postfx_bright", "fs_bright_downsample", hdr_format, None);
        let down_pipeline = make_pipe("postfx_down", "fs_downsample", hdr_format, None);
        let up_pipeline = make_pipe("postfx_up", "fs_upsample", hdr_format, additive);
        let composite_pipeline = make_pipe("postfx_comp", "fs_composite", ui_format, None);

        let composite_uniform_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("postfx_comp_uniform"),
            size: std::mem::size_of::<PostFxUniform>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });

        let (hdr_texture, hdr_view, mips) = Self::alloc_targets(device, hdr_format, width, height);

        Self {
            hdr_format,
            hdr_texture,
            hdr_view,
            mips,
            sampler,
            bgl,
            bright_pipeline,
            down_pipeline,
            up_pipeline,
            composite_pipeline,
            composite_uniform_buf,
            width,
            height,
            is_srgb_output,
        }
    }

    pub fn resize(&mut self, device: &wgpu::Device, width: u32, height: u32) {
        let w = width.max(1);
        let h = height.max(1);
        if w == self.width && h == self.height {
            return;
        }
        self.width = w;
        self.height = h;
        let (hdr_texture, hdr_view, mips) = Self::alloc_targets(device, self.hdr_format, w, h);
        self.hdr_texture = hdr_texture;
        self.hdr_view = hdr_view;
        self.mips = mips;
    }

    fn alloc_targets(
        device: &wgpu::Device,
        format: wgpu::TextureFormat,
        width: u32,
        height: u32,
    ) -> (wgpu::Texture, wgpu::TextureView, Vec<MipLevel>) {
        let hdr_tex = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("hdr_scene"),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
            view_formats: &[],
        });
        let hdr_view = hdr_tex.create_view(&wgpu::TextureViewDescriptor::default());

        let mut mips = Vec::with_capacity(BLOOM_MIPS);
        let mut mw = (width / 2).max(1);
        let mut mh = (height / 2).max(1);
        for i in 0..BLOOM_MIPS {
            let tex = device.create_texture(&wgpu::TextureDescriptor {
                label: Some(&format!("bloom_mip_{i}")),
                size: wgpu::Extent3d {
                    width: mw,
                    height: mh,
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format,
                usage: wgpu::TextureUsages::RENDER_ATTACHMENT
                    | wgpu::TextureUsages::TEXTURE_BINDING,
                view_formats: &[],
            });
            let view = tex.create_view(&wgpu::TextureViewDescriptor::default());
            let uniform_buf = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some(&format!("bloom_mip_uniform_{i}")),
                size: std::mem::size_of::<PostFxUniform>() as u64,
                usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
            mips.push(MipLevel {
                _texture: tex,
                view,
                width: mw,
                height: mh,
                uniform_buf,
            });
            mw = (mw / 2).max(1);
            mh = (mh / 2).max(1);
        }

        (hdr_tex, hdr_view, mips)
    }

    fn make_bg(
        &self,
        device: &wgpu::Device,
        src: &wgpu::TextureView,
        bloom: &wgpu::TextureView,
        ubuf: &wgpu::Buffer,
    ) -> wgpu::BindGroup {
        device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None,
            layout: &self.bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(src),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(bloom),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::Sampler(&self.sampler),
                },
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: ubuf.as_entire_binding(),
                },
            ],
        })
    }

    pub fn execute(
        &self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        encoder: &mut wgpu::CommandEncoder,
        swapchain_view: &wgpu::TextureView,
        mut params: PostFxUniform,
    ) {
        params.resolution = [self.width as f32, self.height as f32];
        params.texel_size = [1.0 / (self.width as f32), 1.0 / (self.height as f32)];
        params.is_srgb_output = if self.is_srgb_output { 1.0 } else { 0.0 };

        // 1. Bright pass + downsample -> mip 0
        if params.fx_strength > 0.01 && !self.mips.is_empty() {
            let mut u0 = params;
            u0.texel_size = [1.0 / (self.width as f32), 1.0 / (self.height as f32)];
            queue.write_buffer(&self.mips[0].uniform_buf, 0, bytemuck::bytes_of(&u0));
            let bg0 = self.make_bg(
                device,
                &self.hdr_view,
                &self.hdr_view,
                &self.mips[0].uniform_buf,
            );
            {
                let mut rp = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: Some("bloom_bright"),
                    color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                        view: &self.mips[0].view,
                        resolve_target: None,
                        ops: wgpu::Operations {
                            load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                            store: wgpu::StoreOp::Store,
                        },
                    })],
                    depth_stencil_attachment: None,
                    occlusion_query_set: None,
                    timestamp_writes: None,
                });
                rp.set_pipeline(&self.bright_pipeline);
                rp.set_bind_group(0, &bg0, &[]);
                rp.draw(0..3, 0..1);
            }

            // 2. Progressive downsample chain
            for i in 1..self.mips.len() {
                let prev = &self.mips[i - 1];
                let curr = &self.mips[i];
                let mut ui = params;
                ui.texel_size = [1.0 / (prev.width as f32), 1.0 / (prev.height as f32)];
                queue.write_buffer(&curr.uniform_buf, 0, bytemuck::bytes_of(&ui));
                let bg = self.make_bg(device, &prev.view, &prev.view, &curr.uniform_buf);
                let mut rp = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: Some("bloom_down"),
                    color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                        view: &curr.view,
                        resolve_target: None,
                        ops: wgpu::Operations {
                            load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                            store: wgpu::StoreOp::Store,
                        },
                    })],
                    depth_stencil_attachment: None,
                    occlusion_query_set: None,
                    timestamp_writes: None,
                });
                rp.set_pipeline(&self.down_pipeline);
                rp.set_bind_group(0, &bg, &[]);
                rp.draw(0..3, 0..1);
            }

            // 3. Progressive upsample additive tent filter
            for i in (1..self.mips.len()).rev() {
                let src = &self.mips[i];
                let dst = &self.mips[i - 1];
                let mut ui = params;
                ui.texel_size = [1.0 / (src.width as f32), 1.0 / (src.height as f32)];
                queue.write_buffer(&src.uniform_buf, 0, bytemuck::bytes_of(&ui));
                let bg = self.make_bg(device, &src.view, &src.view, &src.uniform_buf);
                let mut rp = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: Some("bloom_up"),
                    color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                        view: &dst.view,
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
                rp.set_pipeline(&self.up_pipeline);
                rp.set_bind_group(0, &bg, &[]);
                rp.draw(0..3, 0..1);
            }
        }

        // 4. Composite onto swapchain
        queue.write_buffer(&self.composite_uniform_buf, 0, bytemuck::bytes_of(&params));
        let bloom_view = self
            .mips
            .first()
            .map(|m| &m.view)
            .unwrap_or(&self.hdr_view);
        let bg_comp = self.make_bg(device, &self.hdr_view, bloom_view, &self.composite_uniform_buf);
        let mut rp = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("postfx_composite"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: swapchain_view,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: None,
            occlusion_query_set: None,
            timestamp_writes: None,
        });
        rp.set_pipeline(&self.composite_pipeline);
        rp.set_bind_group(0, &bg_comp, &[]);
        rp.draw(0..3, 0..1);
    }
}
