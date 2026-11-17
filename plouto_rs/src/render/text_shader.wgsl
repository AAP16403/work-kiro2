struct ScreenUniform {
    resolution: vec2<f32>,
    _pad: vec2<f32>,
};

@group(0) @binding(0)
var<uniform> u_screen: ScreenUniform;
@group(0) @binding(1)
var t_atlas: texture_2d<f32>;
@group(0) @binding(2)
var s_atlas: sampler;

struct GlyphInst {
    @location(0) rect: vec4<f32>, // x0, y0 (bot-left), x1, y1 (top-right)
    @location(1) uv: vec4<f32>,   // u0, v0 (top), u1, v1 (bot)
    @location(2) color: vec4<f32>,
};

struct VsOut {
    @builtin(position) clip_pos: vec4<f32>,
    @location(0) uv: vec2<f32>,
    @location(1) color: vec4<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) vidx: u32, inst: GlyphInst) -> VsOut {
    var c = vec2<f32>(0.0, 0.0);
    switch (vidx) {
        case 0u: { c = vec2<f32>(0.0, 0.0); }
        case 1u: { c = vec2<f32>(1.0, 0.0); }
        case 2u: { c = vec2<f32>(1.0, 1.0); }
        case 3u: { c = vec2<f32>(0.0, 0.0); }
        case 4u: { c = vec2<f32>(1.0, 1.0); }
        default: { c = vec2<f32>(0.0, 1.0); }
    }

    let pos = vec2<f32>(mix(inst.rect.x, inst.rect.z, c.x), mix(inst.rect.y, inst.rect.w, c.y));
    let ndc = (pos / max(u_screen.resolution, vec2<f32>(1.0))) * 2.0 - 1.0;

    // c.y = 0 (bottom of quad) -> v1 (bottom of glyph); c.y = 1 (top) -> v0 (top of glyph)
    let uv = vec2<f32>(mix(inst.uv.x, inst.uv.z, c.x), mix(inst.uv.w, inst.uv.y, c.y));

    var out: VsOut;
    out.clip_pos = vec4<f32>(ndc, 0.0, 1.0);
    out.uv = uv;
    out.color = inst.color;
    return out;
}

@fragment
fn fs_main(in: VsOut) -> @location(0) vec4<f32> {
    let cov = textureSampleLevel(t_atlas, s_atlas, in.uv, 0.0).r;
    let a = cov * in.color.a;
    if (a <= 0.002) {
        discard;
    }
    return vec4<f32>(in.color.rgb, a);
}
