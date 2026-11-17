//! Explicit graphics check: cargo test -p plouto_rs --test boss_gpu -- --ignored
use plouto_rs::render::bloom::{BloomPostProcess, PostFxUniform};
use plouto_rs::render::sdf::{SdfBatch, SdfRenderer};
use plouto_rs::render::text::{TextBatch, TextRenderer};
use plouto_rs::render::world::WorldRenderer;
use plouto_rs::sim::enemy::{BossPersona, Enemy, EnemySubState};
use plouto_rs::sim::math::Vec2;
use plouto_rs::sim::state::{RunSetup, SimInput, SimState};
use plouto_rs::sim::step::step;

#[test]
#[ignore = "requires a graphics adapter; run explicitly when checking rendering crashes"]
fn all_boss_attacks_render_on_the_gpu_in_every_phase() {
    let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor::default());
    let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions::default()))
        .expect("graphics adapter required for this explicit smoke test");
    eprintln!("Testing boss rendering on {:?}", adapter.get_info());
    let (device, queue) = pollster::block_on(adapter.request_device(
        &wgpu::DeviceDescriptor::default(), None,
    )).expect("graphics device");
    let format = wgpu::TextureFormat::Rgba8UnormSrgb;
    let mut bloom = BloomPostProcess::new(&device, format, 640, 400);
    let mut sdf = SdfRenderer::new(&device, bloom.hdr_format, format, 640, 400);
    let mut text_renderer = TextRenderer::new(&device, format).expect("fonts");
    let output = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("boss smoke output"),
        size: wgpu::Extent3d { width: 640, height: 400, depth_or_array_layers: 1 },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
        view_formats: &[],
    });
    let view = output.create_view(&Default::default());
    for behavior in ["boss_thunder", "boss_laser", "boss_trapmaster", "boss_swarmqueen",
        "boss_brute", "boss_abyss_gaze", "boss_womb_core", "boss_eclipse_archon"] {
        for phase in 0..3 {
            for persona in [BossPersona::Aggressive, BossPersona::Cautious, BossPersona::Trickster] {
                let mut state = SimState::new(RunSetup::default());
                state.wave = 10;
                state.wave_active = true;
                state.player.hp = 1_000_000;
                state.player.max_hp = state.player.hp;
                state.player.pos = Vec2::new(-150.0, 0.0);
                let hp = [3000, 1500, 800][phase as usize];
                let mut boss = Enemy::new(state.alloc_id(), Vec2::new(150.0, 0.0), hp, 75.0, behavior);
                boss.ai.boss_initialized = true;
                boss.ai.boss_max_hp = 3000;
                boss.ai.phase = phase;
                boss.ai.persona = persona;
                boss.attack_cd = 0.0;
                if behavior == "boss_laser" {
                    boss.ai.sub_state = EnemySubState::LaserCharge;
                    boss.ai.sub_timer = 0.75;
                }
                boss.ai.charge_dir = Vec2::new(-1.0, 0.0);
                state.enemies.push(boss);
                let mut world = WorldRenderer::new();
                let mut wa = SdfBatch::default();
                let mut wb = SdfBatch::default();
                let mut ua = SdfBatch::default();
                let ub = SdfBatch::default();
                let mut text = TextBatch::default();
                let mut saw_attack = false;
                for frame in 0..240 {
                    world.capture_prev(&state);
                    let events = step(&mut state, &SimInput::default(), 1.0 / 60.0);
                    world.on_step_post(&state, &events, 640.0, 400.0);
                    world.particles.tick(1.0 / 60.0);
                    saw_attack |= state.enemies[0].ai.sub_state == EnemySubState::LaserAttack;
                    if frame % 30 != 0 { continue; }
                    wa.clear(); wb.clear(); ua.clear(); text.clear();
                    world.draw_world(&state, 1.0, 640.0, 400.0, Vec2::new(-1.0, 0.0), None,
                        false, &mut wa, &mut wb, &mut ua, &mut text, 1.0);
                    for batch in [&wa, &wb, &ua] {
                        assert!(batch.instances.iter().all(|inst| inst.p0.iter().chain(inst.p1.iter())
                            .chain(inst.params.iter()).chain(inst.color.iter()).all(|n| n.is_finite())),
                            "non-finite render geometry: {behavior}, phase={phase}, frame={frame}");
                    }
                    device.push_error_scope(wgpu::ErrorFilter::Validation);
                    let (ha, hb, a, b) = sdf.prepare_buffers(&device, &queue, 640, 400, &wa, &wb, &ua, &ub);
                    let mut encoder = device.create_command_encoder(&Default::default());
                    sdf.record_world_pass(&bloom.hdr_view, ha, hb, &mut encoder, wgpu::Color::BLACK);
                    bloom.execute(&device, &queue, &mut encoder, &view, PostFxUniform::default());
                    sdf.record_ui_pass(&view, ha + hb, a, b, &mut encoder);
                    text_renderer.prepare_and_record(&device, &queue, 640, 400, &text, &view, &mut encoder);
                    queue.submit(Some(encoder.finish()));
                    device.poll(wgpu::Maintain::Wait);
                    assert!(pollster::block_on(device.pop_error_scope()).is_none(),
                        "GPU validation failed: phase={phase}, persona={persona:?}, frame={frame}");
                }
                if behavior == "boss_laser" {
                    assert!(saw_attack, "smoke test must exercise an actual laser attack");
                }
            }
        }
    }
    // Verify rebuilding the bloom targets after a display change as well.
    bloom.resize(&device, 320, 200);
}
