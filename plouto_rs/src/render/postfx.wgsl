struct PostFxUniform {
    resolution: vec2<f32>,
    texel_size: vec2<f32>,
    time: f32,
    fx_strength: f32,
    combat_intensity: f32,
    low_hp_danger: f32,
    boss_active: f32,
    reduce_motion: f32,
    hit_flash: f32,
    ultra_flash: f32,
    dash_pulse: f32,
    boost_pulse: f32,
    boss_flash: f32,
    fade_alpha: f32,
    threshold: f32,
    bloom_intensity: f32,
    is_srgb_output: f32,
    _pad: f32,
};

@group(0) @binding(0)
var t_src: texture_2d<f32>;
@group(0) @binding(1)
var t_bloom: texture_2d<f32>;
@group(0) @binding(2)
var s_linear: sampler;
@group(0) @binding(3)
var<uniform> u_fx: PostFxUniform;

struct VsOut {
    @builtin(position) clip_pos: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_fullscreen(@builtin(vertex_index) vidx: u32) -> VsOut {
    // Big triangle covering clip space cleanly
    var pos = vec2<f32>(-1.0, -1.0);
    if (vidx == 1u) {
        pos = vec2<f32>(3.0, -1.0);
    } else if (vidx == 2u) {
        pos = vec2<f32>(-1.0, 3.0);
    }
    var out: VsOut;
    out.clip_pos = vec4<f32>(pos, 0.0, 1.0);
    // Texture UV: (0,0) top-left, (1,1) bottom-right in WGPU texture coords
    out.uv = vec2<f32>(pos.x * 0.5 + 0.5, 0.5 - pos.y * 0.5);
    return out;
}

@fragment
fn fs_bright_downsample(in: VsOut) -> @location(0) vec4<f32> {
    let ts = u_fx.texel_size;
    let c0 = textureSampleLevel(t_src, s_linear, in.uv + vec2<f32>(-ts.x, -ts.y) * 0.5, 0.0).rgb;
    let c1 = textureSampleLevel(t_src, s_linear, in.uv + vec2<f32>( ts.x, -ts.y) * 0.5, 0.0).rgb;
    let c2 = textureSampleLevel(t_src, s_linear, in.uv + vec2<f32>(-ts.x,  ts.y) * 0.5, 0.0).rgb;
    let c3 = textureSampleLevel(t_src, s_linear, in.uv + vec2<f32>( ts.x,  ts.y) * 0.5, 0.0).rgb;
    let col = (c0 + c1 + c2 + c3) * 0.25;

    let lum = max(col.r, max(col.g, col.b));
    let knee = u_fx.threshold * 0.35 + 1e-4;
    let soft = clamp(lum - (u_fx.threshold - knee), 0.0, 2.0 * knee);
    let rq = (soft * soft) / (4.0 * knee);
    let contrib = max(rq, lum - u_fx.threshold) / max(lum, 1e-4);
    return vec4<f32>(col * clamp(contrib, 0.0, 4.0), 1.0);
}

@fragment
fn fs_downsample(in: VsOut) -> @location(0) vec4<f32> {
    let ts = u_fx.texel_size;
    let c = textureSampleLevel(t_src, s_linear, in.uv, 0.0).rgb * 4.0;
    let a = textureSampleLevel(t_src, s_linear, in.uv + vec2<f32>(-ts.x, -ts.y), 0.0).rgb;
    let b = textureSampleLevel(t_src, s_linear, in.uv + vec2<f32>( ts.x, -ts.y), 0.0).rgb;
    let d = textureSampleLevel(t_src, s_linear, in.uv + vec2<f32>(-ts.x,  ts.y), 0.0).rgb;
    let e = textureSampleLevel(t_src, s_linear, in.uv + vec2<f32>( ts.x,  ts.y), 0.0).rgb;
    return vec4<f32>((c + a + b + d + e) * 0.125, 1.0);
}

@fragment
fn fs_upsample(in: VsOut) -> @location(0) vec4<f32> {
    let ts = u_fx.texel_size;
    var sum = vec3<f32>(0.0);
    sum += textureSampleLevel(t_src, s_linear, in.uv + vec2<f32>(-ts.x, -ts.y), 0.0).rgb;
    sum += textureSampleLevel(t_src, s_linear, in.uv + vec2<f32>( 0.0,  -ts.y), 0.0).rgb * 2.0;
    sum += textureSampleLevel(t_src, s_linear, in.uv + vec2<f32>( ts.x, -ts.y), 0.0).rgb;
    sum += textureSampleLevel(t_src, s_linear, in.uv + vec2<f32>(-ts.x,  0.0), 0.0).rgb * 2.0;
    sum += textureSampleLevel(t_src, s_linear, in.uv, 0.0).rgb * 4.0;
    sum += textureSampleLevel(t_src, s_linear, in.uv + vec2<f32>( ts.x,  0.0), 0.0).rgb * 2.0;
    sum += textureSampleLevel(t_src, s_linear, in.uv + vec2<f32>(-ts.x,  ts.y), 0.0).rgb;
    sum += textureSampleLevel(t_src, s_linear, in.uv + vec2<f32>( 0.0,  ts.y), 0.0).rgb * 2.0;
    sum += textureSampleLevel(t_src, s_linear, in.uv + vec2<f32>( ts.x,  ts.y), 0.0).rgb;
    return vec4<f32>(sum * (1.0 / 16.0), 1.0);
}

fn hash12(p: vec2<f32>) -> f32 {
    var p3 = fract(vec3<f32>(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

@fragment
fn fs_composite(in: VsOut) -> @location(0) vec4<f32> {
    let scene = textureSampleLevel(t_src, s_linear, in.uv, 0.0).rgb;
    let bloom = textureSampleLevel(t_bloom, s_linear, in.uv, 0.0).rgb;

    var col = scene + bloom * (u_fx.bloom_intensity * u_fx.fx_strength);

    // Highlight soft-shoulder tone map preserving mid-tone indie palette fidelity
    let mx = max(col.r, max(col.g, col.b));
    let mapped = col * (1.08 / (1.0 + mx * 0.16));
    let white_bleed = clamp((mx - 1.3) * 0.18, 0.0, 0.45);
    col = mix(mapped, vec3<f32>(max(mapped.r, max(mapped.g, mapped.b))), white_bleed);

    // Edge distance from center (0 center, ~1.41 corners)
    let center_d = in.uv * 2.0 - 1.0;
    let edge = length(center_d * vec2<f32>(0.92, 1.05));

    // Dynamic atmospheric vignette & AdvancedFX overlays
    let vig_base = 0.14 + 0.12 * u_fx.combat_intensity * u_fx.fx_strength;
    let vig = 1.0 - smoothstep(0.62, 1.48, edge) * vig_base;
    col *= vig;

    // Subtle scanlines & film grain when advanced_fx enabled
    if (u_fx.fx_strength > 0.01) {
        let px_y = in.uv.y * u_fx.resolution.y;
        let scan = 1.0 - 0.025 * u_fx.fx_strength * (0.5 + 0.5 * sin(px_y * 1.5708));
        col *= scan;

        let t_seed = select(floor(u_fx.time * 24.0) * 0.07, 0.0, u_fx.reduce_motion > 0.5);
        let grain = (hash12(in.uv * u_fx.resolution + t_seed * 131.0) - 0.5) * 0.014 * u_fx.fx_strength;
        col += vec3<f32>(grain);
    }

    // Low HP danger edge tint
    if (u_fx.low_hp_danger > 0.001) {
        let danger_mask = smoothstep(0.55, 1.35, edge) * u_fx.low_hp_danger;
        col = mix(col, vec3<f32>(0.72, 0.04, 0.10), clamp(danger_mask * 0.52, 0.0, 0.65));
    }

    // Boss atmosphere top/bottom pressure tint
    if (u_fx.boss_active > 0.001) {
        let band = smoothstep(0.58, 1.0, abs(center_d.y)) * u_fx.boss_active;
        col = mix(col, vec3<f32>(0.22, 0.03, 0.14), clamp(band * 0.22 * u_fx.fx_strength, 0.0, 0.35));
    }

    // Gameplay reaction flashes
    if (u_fx.hit_flash > 0.001) {
        let edge_hit = smoothstep(0.35, 1.35, edge) * u_fx.hit_flash;
        col = mix(col, vec3<f32>(0.90, 0.10, 0.16), clamp(edge_hit * 0.55, 0.0, 0.65));
    }
    if (u_fx.dash_pulse > 0.001) {
        let edge_d = smoothstep(0.50, 1.35, edge) * u_fx.dash_pulse;
        col += vec3<f32>(0.18, 0.55, 0.85) * edge_d * 0.45;
    }
    if (u_fx.boost_pulse > 0.001) {
        let edge_b = smoothstep(0.52, 1.38, edge) * u_fx.boost_pulse;
        col += vec3<f32>(0.85, 0.38, 0.08) * edge_b * 0.40;
    }
    if (u_fx.ultra_flash > 0.001) {
        col += vec3<f32>(0.95, 0.80, 0.48) * (u_fx.ultra_flash * 0.32);
    }
    if (u_fx.boss_flash > 0.001) {
        col += vec3<f32>(1.0, 0.92, 0.78) * (u_fx.boss_flash * 0.42);
    }

    // Screen transition curtain fade
    col *= (1.0 - clamp(u_fx.fade_alpha, 0.0, 1.0));
    col = max(col, vec3<f32>(0.0));

    if (u_fx.is_srgb_output < 0.5) {
        col = pow(col, vec3<f32>(1.0 / 2.2));
    }
    return vec4<f32>(col, 1.0);
}
