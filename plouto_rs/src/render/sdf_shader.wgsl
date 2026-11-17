struct ScreenUniform {
    resolution: vec2<f32>,
    _pad: vec2<f32>,
};

@group(0) @binding(0)
var<uniform> u_screen: ScreenUniform;

struct InstanceInput {
    @location(0) p0: vec2<f32>,
    @location(1) p1: vec2<f32>,
    @location(2) params: vec4<f32>,
    @location(3) color: vec4<f32>,
    @location(4) kind: u32,
};

struct VertexOut {
    @builtin(position) clip_pos: vec4<f32>,
    @location(0) world_pos: vec2<f32>,
    @location(1) p0: vec2<f32>,
    @location(2) p1: vec2<f32>,
    @location(3) params: vec4<f32>,
    @location(4) color: vec4<f32>,
    @location(5) @interpolate(flat) kind: u32,
};

fn rot2(p: vec2<f32>, angle: f32) -> vec2<f32> {
    let c = cos(angle);
    let s = sin(angle);
    return vec2<f32>(p.x * c - p.y * s, p.x * s + p.y * c);
}

@vertex
fn vs_main(
    @builtin(vertex_index) vidx: u32,
    inst: InstanceInput,
) -> VertexOut {
    var bmin = vec2<f32>(0.0);
    var bmax = vec2<f32>(0.0);
    let pad = 4.0;

    if (inst.kind == 0u) {
        // Ellipse / disc / ring / radial glow
        let stroke = max(inst.params.y, 0.0) * 0.5;
        let rot = inst.params.x;
        let c = abs(cos(rot));
        let s = abs(sin(rot));
        let rx = abs(inst.p1.x) + stroke;
        let ry = abs(inst.p1.y) + stroke;
        let ext = vec2<f32>(rx * c + ry * s + pad, rx * s + ry * c + pad);
        bmin = inst.p0 - ext;
        bmax = inst.p0 + ext;
    } else if (inst.kind == 1u) {
        // Capsule / line
        let r = abs(inst.params.x) + max(inst.params.y, 0.0) + pad;
        bmin = min(inst.p0, inst.p1) - vec2<f32>(r);
        bmax = max(inst.p0, inst.p1) + vec2<f32>(r);
    } else if (inst.kind == 2u) {
        // Oriented rounded rect
        let rot = inst.params.x;
        let stroke = max(inst.params.z, 0.0) * 0.5;
        let soft = max(inst.params.w, 0.0);
        let c = abs(cos(rot));
        let s = abs(sin(rot));
        let hw = abs(inst.p1.x) + stroke + soft + pad;
        let hh = abs(inst.p1.y) + stroke + soft + pad;
        let ext = vec2<f32>(hw * c + hh * s, hw * s + hh * c);
        bmin = inst.p0 - ext;
        bmax = inst.p0 + ext;
    } else if (inst.kind == 3u) {
        // Arc / sector
        let r = abs(inst.p1.x) + abs(inst.p1.y) + pad;
        let ay = select(inst.params.w, 1.0, inst.params.w <= 0.0);
        let ext = vec2<f32>(r, r * max(ay, 1.0));
        bmin = inst.p0 - ext;
        bmax = inst.p0 + ext;
    } else {
        // Triangle (p0, p1, params.xy)
        let v2 = inst.params.xy;
        let soft = max(inst.params.z, 0.0);
        bmin = min(min(inst.p0, inst.p1), v2) - vec2<f32>(pad + soft);
        bmax = max(max(inst.p0, inst.p1), v2) + vec2<f32>(pad + soft);
    }

    // Quad vertices from vidx 0..5
    var corner = vec2<f32>(0.0, 0.0);
    switch (vidx) {
        case 0u: { corner = vec2<f32>(0.0, 0.0); }
        case 1u: { corner = vec2<f32>(1.0, 0.0); }
        case 2u: { corner = vec2<f32>(1.0, 1.0); }
        case 3u: { corner = vec2<f32>(0.0, 0.0); }
        case 4u: { corner = vec2<f32>(1.0, 1.0); }
        default: { corner = vec2<f32>(0.0, 1.0); }
    }

    let pos = mix(bmin, bmax, corner);
    let ndc = (pos / max(u_screen.resolution, vec2<f32>(1.0))) * 2.0 - 1.0;

    var out: VertexOut;
    out.clip_pos = vec4<f32>(ndc, 0.0, 1.0);
    out.world_pos = pos;
    out.p0 = inst.p0;
    out.p1 = inst.p1;
    out.params = inst.params;
    out.color = inst.color;
    out.kind = inst.kind;
    return out;
}

fn sd_segment(p: vec2<f32>, a: vec2<f32>, b: vec2<f32>) -> f32 {
    let pa = p - a;
    let ba = b - a;
    let denom = max(dot(ba, ba), 1e-6);
    let h = clamp(dot(pa, ba) / denom, 0.0, 1.0);
    return length(pa - ba * h);
}

fn sd_triangle(p: vec2<f32>, p0: vec2<f32>, p1: vec2<f32>, p2: vec2<f32>) -> f32 {
    let e0 = p1 - p0;
    let e1 = p2 - p1;
    let e2 = p0 - p2;
    let area2 = e0.x * (p2.y - p0.y) - e0.y * (p2.x - p0.x);
    if (abs(area2) <= 1e-4) {
        // Ellipsoid tip triangles can collapse after projection; treat them
        // as empty instead of passing zero-area geometry to the SDF pass.
        return 1e6;
    }
    let v0 = p - p0;
    let v1 = p - p1;
    let v2 = p - p2;
    let pq0 = v0 - e0 * clamp(dot(v0, e0) / max(dot(e0, e0), 1e-6), 0.0, 1.0);
    let pq1 = v1 - e1 * clamp(dot(v1, e1) / max(dot(e1, e1), 1e-6), 0.0, 1.0);
    let pq2 = v2 - e2 * clamp(dot(v2, e2) / max(dot(e2, e2), 1e-6), 0.0, 1.0);
    let s = sign(e0.x * e2.y - e0.y * e2.x);
    let d0 = vec2<f32>(dot(pq0, pq0), s * (v0.x * e0.y - v0.y * e0.x));
    let d1 = vec2<f32>(dot(pq1, pq1), s * (v1.x * e1.y - v1.y * e1.x));
    let d2 = vec2<f32>(dot(pq2, pq2), s * (v2.x * e2.y - v2.y * e2.x));
    let dm = min(min(d0, d1), d2);
    return -sqrt(dm.x) * sign(dm.y);
}

@fragment
fn fs_main(in: VertexOut) -> @location(0) vec4<f32> {
    var cov = 0.0;
    let p = in.world_pos;

    if (in.kind == 0u) {
        let local = rot2(p - in.p0, -in.params.x);
        let r = max(abs(in.p1), vec2<f32>(0.25));
        let q = local / r;
        let k1 = length(q);
        let softness = in.params.z;

        if (softness > 1.0) {
            // Radial power falloff glow matching Python `(1 - r)^p`
            cov = pow(clamp(1.0 - k1, 0.0, 1.0), softness);
        } else {
            let k2 = length(q / r);
            var d = -min(r.x, r.y);
            if (k1 > 1e-4 && k2 > 1e-5) {
                d = (k1 * (k1 - 1.0)) / k2;
            }
            let stroke = in.params.y;
            if (stroke > 0.0) {
                d = abs(d) - stroke * 0.5;
            }
            let aa = max(0.65, softness);
            cov = clamp(0.5 - d / aa, 0.0, 1.0);
        }
    } else if (in.kind == 1u) {
        let d = sd_segment(p, in.p0, in.p1) - abs(in.params.x);
        let aa = max(0.65, in.params.y);
        cov = clamp(0.5 - d / aa, 0.0, 1.0);
    } else if (in.kind == 2u) {
        let local = rot2(p - in.p0, -in.params.x);
        let rad = min(max(in.params.y, 0.0), min(in.p1.x, in.p1.y));
        let q = abs(local) - in.p1 + vec2<f32>(rad);
        var d = length(max(q, vec2<f32>(0.0))) + min(max(q.x, q.y), 0.0) - rad;
        let stroke = in.params.z;
        if (stroke > 0.0) {
            d = abs(d) - stroke * 0.5;
        }
        let aa = max(0.65, in.params.w);
        cov = clamp(0.5 - d / aa, 0.0, 1.0);
    } else if (in.kind == 3u) {
        let ay = select(in.params.w, 1.0, in.params.w <= 0.0);
        let local = vec2<f32>(p.x - in.p0.x, (p.y - in.p0.y) / ay);
        let radius = max(abs(in.p1.x), 0.5);
        let half_thick = max(abs(in.p1.y), 0.5);
        let tau = 6.283185307;
        let sweep = clamp(abs(in.params.y), 0.0, tau);
        if (sweep <= 1e-4) {
            discard;
        }
        let start = in.params.x;
        let mid = start + select(-sweep * 0.5, sweep * 0.5, in.params.y >= 0.0);
        let pr = rot2(local, -mid);
        let rlen = length(pr);
        let half_sw = sweep * 0.5;
        let ang = abs(atan2(pr.y, pr.x));

        var d = 0.0;
        if (in.params.z > 0.5) {
            // Filled wedge sector
            if (sweep >= tau - 1e-3) {
                d = rlen - radius;
            } else {
                let end_dir = vec2<f32>(cos(half_sw), sin(half_sw));
                let pm = vec2<f32>(pr.x, abs(pr.y));
                let radial_d = rlen - radius;
                let line_d = length(pm - end_dir * clamp(dot(pm, end_dir), 0.0, radius));
                let inside = ang <= half_sw && rlen <= radius;
                d = select(min(max(radial_d, 0.0), line_d), max(radial_d, -line_d), inside);
            }
        } else {
            // Ring arc
            if (sweep >= tau - 1e-3 || ang <= half_sw) {
                d = abs(rlen - radius) - half_thick;
            } else {
                let ep = vec2<f32>(cos(half_sw), sin(half_sw)) * radius;
                let pm = vec2<f32>(pr.x, abs(pr.y));
                d = length(pm - ep) - half_thick;
            }
        }
        // Account for vertical ellipse foreshortening on AA
        let d_px = d * min(1.0, ay);
        cov = clamp(0.5 - d_px / 0.75, 0.0, 1.0);
    } else {
        let d = sd_triangle(p, in.p0, in.p1, in.params.xy);
        let aa = max(0.65, in.params.z);
        cov = clamp(0.5 - d / aa, 0.0, 1.0);
    }

    let alpha = cov * in.color.a;
    if (alpha <= 0.001) {
        discard;
    }
    return vec4<f32>(in.color.rgb, alpha);
}
