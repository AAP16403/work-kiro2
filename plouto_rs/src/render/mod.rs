pub mod bloom;
pub mod floor;
pub mod models3d;
pub mod particles;
pub mod player_art;
pub mod powerup_art;
pub mod sdf;
pub mod text;
pub mod world;

use std::sync::Arc;

use winit::window::Window;

use crate::render::bloom::{BloomPostProcess, PostFxUniform};
use crate::render::sdf::{SdfBatch, SdfRenderer};
use crate::render::text::{TextBatch, TextRenderer};

pub struct GpuContext {
    pub surface: wgpu::Surface<'static>,
    pub device: wgpu::Device,
    pub queue: wgpu::Queue,
    pub config: wgpu::SurfaceConfiguration,
    pub size: (u32, u32),
}

impl GpuContext {
    pub fn new(window: Arc<Window>) -> Result<Self, String> {
        let size = window.inner_size();
        let w = size.width.max(1);
        let h = size.height.max(1);

        let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
            backends: wgpu::Backends::PRIMARY,
            ..Default::default()
        });
        let surface = instance
            .create_surface(window)
            .map_err(|e| format!("create wgpu surface failed: {e}"))?;

        let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            compatible_surface: Some(&surface),
            force_fallback_adapter: false,
        }))
        .ok_or_else(|| "no suitable GPU adapter found".to_string())?;

        let (device, queue) = pollster::block_on(adapter.request_device(
            &wgpu::DeviceDescriptor {
                label: Some("plouto_gpu"),
                required_features: wgpu::Features::empty(),
                required_limits: wgpu::Limits::default(),
                memory_hints: wgpu::MemoryHints::Performance,
            },
            None,
        ))
        .map_err(|e| format!("request_device failed: {e}"))?;

        let caps = surface.get_capabilities(&adapter);
        let format = caps
            .formats
            .iter()
            .copied()
            .find(|f| f.is_srgb())
            .unwrap_or(caps.formats[0]);

        let present_mode = if caps.present_modes.contains(&wgpu::PresentMode::Mailbox) {
            wgpu::PresentMode::Mailbox
        } else if caps.present_modes.contains(&wgpu::PresentMode::AutoVsync) {
            wgpu::PresentMode::AutoVsync
        } else {
            wgpu::PresentMode::Fifo
        };

        let config = wgpu::SurfaceConfiguration {
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            format,
            width: w,
            height: h,
            present_mode,
            alpha_mode: caps.alpha_modes[0],
            view_formats: vec![],
            desired_maximum_frame_latency: 2,
        };
        surface.configure(&device, &config);

        Ok(Self {
            surface,
            device,
            queue,
            config,
            size: (w, h),
        })
    }

    pub fn resize(&mut self, width: u32, height: u32) {
        let w = width.max(1);
        let h = height.max(1);
        if w == self.size.0 && h == self.size.1 {
            return;
        }
        self.size = (w, h);
        self.config.width = w;
        self.config.height = h;
        self.surface.configure(&self.device, &self.config);
    }
}

pub struct FrameRenderer {
    pub sdf: SdfRenderer,
    pub bloom: BloomPostProcess,
    pub text: TextRenderer,
    pub world_alpha: SdfBatch,
    pub world_add: SdfBatch,
    pub ui_alpha: SdfBatch,
    pub ui_add: SdfBatch,
    pub ui_text: TextBatch,
}

impl FrameRenderer {
    pub fn new(gpu: &GpuContext) -> Result<Self, String> {
        let (w, h) = gpu.size;
        let ui_format = gpu.config.format;
        let bloom = BloomPostProcess::new(&gpu.device, ui_format, w, h);
        let sdf = SdfRenderer::new(&gpu.device, bloom.hdr_format, ui_format, w, h);
        let text = TextRenderer::new(&gpu.device, ui_format)?;
        Ok(Self {
            sdf,
            bloom,
            text,
            world_alpha: SdfBatch::with_capacity(4096),
            world_add: SdfBatch::with_capacity(4096),
            ui_alpha: SdfBatch::with_capacity(1024),
            ui_add: SdfBatch::with_capacity(512),
            ui_text: TextBatch::default(),
        })
    }

    pub fn resize(&mut self, gpu: &GpuContext) {
        self.bloom.resize(&gpu.device, gpu.size.0, gpu.size.1);
    }

    pub fn begin_frame(&mut self) {
        self.world_alpha.clear();
        self.world_add.clear();
        self.ui_alpha.clear();
        self.ui_add.clear();
        self.ui_text.clear();
    }

    pub fn submit_frame(&mut self, gpu: &mut GpuContext, postfx: PostFxUniform) -> Result<(), String> {
        let output = match gpu.surface.get_current_texture() {
            Ok(tex) => tex,
            Err(wgpu::SurfaceError::Lost | wgpu::SurfaceError::Outdated) => {
                gpu.surface.configure(&gpu.device, &gpu.config);
                return Ok(());
            }
            Err(wgpu::SurfaceError::Timeout) => return Ok(()),
            Err(e) => return Err(format!("acquire swapchain image failed: {e}")),
        };
        let swap_view = output
            .texture
            .create_view(&wgpu::TextureViewDescriptor::default());

        let (w, h) = gpu.size;
        let (h_a, h_b, u_a, u_b) = self.sdf.prepare_buffers(
            &gpu.device,
            &gpu.queue,
            w,
            h,
            &self.world_alpha,
            &self.world_add,
            &self.ui_alpha,
            &self.ui_add,
        );

        let mut encoder = gpu
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("plouto_frame"),
            });

        // 1. Render World Alpha + Additive HDR SDFs into Rgba16Float scene
        self.sdf.record_world_pass(
            &self.bloom.hdr_view,
            h_a,
            h_b,
            &mut encoder,
            wgpu::Color {
                r: 0.005,
                g: 0.008,
                b: 0.018,
                a: 1.0,
            },
        );

        // 2. Bloom chain + AdvancedFX composite onto Swapchain
        self.bloom
            .execute(&gpu.device, &gpu.queue, &mut encoder, &swap_view, postfx);

        // 3. Crisp UI/HUD SDFs + Popups + Orbitron/Rajdhani Text directly on Swapchain
        self.sdf
            .record_ui_pass(&swap_view, h_a + h_b, u_a, u_b, &mut encoder);
        self.text.prepare_and_record(
            &gpu.device,
            &gpu.queue,
            w,
            h,
            &self.ui_text,
            &swap_view,
            &mut encoder,
        );

        gpu.queue.submit(Some(encoder.finish()));
        output.present();
        Ok(())
    }
}
