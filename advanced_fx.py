"""Optional advanced post-FX overlay using moderngl.

This module is additive: it renders on top of the existing pyglet pipeline.
If moderngl is unavailable or context setup fails, it safely disables itself.
"""

from __future__ import annotations

from array import array
import logging
import math

import config
import pyglet
from pyglet import shapes

try:
    import moderngl  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    moderngl = None


LOG = logging.getLogger(__name__)


class AdvancedFX:
    """Fullscreen post-process overlay for subtle high-end polish."""

    def __init__(self, width: int, height: int) -> None:
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.enabled = bool(getattr(config, "ENABLE_ADVANCED_FX", True))
        self._use_gl_backend = moderngl is not None
        self._ctx = None
        self._prog = None
        self._vbo = None
        self._vao = None
        self._ready = False
        self.last_error = ""
        self._hit_flash = 0.0
        self._ultra_flash = 0.0
        self._dash_pulse = 0.0
        self._fb_main = None
        self._fb_edge = None

    def resize(self, width: int, height: int) -> None:
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        if self._ctx is not None:
            self._ctx.viewport = (0, 0, self.width, self.height)
        if self._fb_main is not None:
            self._fb_main.width = self.width
            self._fb_main.height = self.height
        if self._fb_edge is not None:
            self._fb_edge.width = self.width
            self._fb_edge.height = self.height

    def _ensure_ready(self) -> bool:
        if not self.enabled or not self._use_gl_backend:
            return False
        if self._ready:
            return True
        try:
            self._ctx = moderngl.create_context()
            self._ctx.viewport = (0, 0, self.width, self.height)
            self._ctx.enable(moderngl.BLEND)
            self._ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)
            self._prog = self._ctx.program(
                vertex_shader="""
                    #version 330
                    in vec2 in_pos;
                    in vec2 in_uv;
                    out vec2 v_uv;
                    void main() {
                        v_uv = in_uv;
                        gl_Position = vec4(in_pos, 0.0, 1.0);
                    }
                """,
                fragment_shader="""
                    #version 330
                    in vec2 v_uv;
                    out vec4 fragColor;
                    uniform float u_time;
                    uniform float u_intensity;
                    uniform float u_hit_flash;
                    uniform float u_ultra_flash;
                    uniform float u_dash_pulse;
                    uniform float u_hp_danger;
                    uniform float u_boss_pressure;
                    uniform vec2 u_resolution;

                    float hash(vec2 p) {
                        return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
                    }

                    void main() {
                        vec2 uv = v_uv;
                        vec2 centered = uv * 2.0 - 1.0;
                        float dist = dot(centered, centered);
                        float vignette = smoothstep(1.15, 0.22, dist);
                        float grain = (hash(uv * u_resolution + vec2(u_time * 61.0, u_time * 31.0)) - 0.5) * 0.12;
                        float scan = sin((uv.y * u_resolution.y) * 0.018 + u_time * 2.6) * 0.012;
                        float radial = smoothstep(1.0, 0.25, dist);
                        float corePulse = sin(u_time * 9.0) * 0.5 + 0.5;
                        float bossBand = sin(u_time * 3.3 + uv.y * 14.0) * 0.5 + 0.5;
                        float alpha = clamp((1.0 - vignette) * 0.18 + abs(scan) + abs(grain), 0.0, 1.0) * u_intensity;
                        alpha += u_hit_flash * (0.22 + 0.35 * radial);
                        alpha += u_ultra_flash * (0.18 + 0.45 * corePulse);
                        alpha += u_dash_pulse * (0.08 + 0.12 * (1.0 - abs(centered.x)));
                        alpha += u_boss_pressure * (0.04 + 0.08 * bossBand);
                        alpha += u_hp_danger * (0.06 + 0.12 * (1.0 - radial));
                        vec3 tint = vec3(0.03, 0.05, 0.08) + vec3(0.08, 0.06, 0.02) * (0.5 + 0.5 * sin(u_time * 0.3));
                        tint = mix(tint, vec3(0.55, 0.12, 0.12), u_hit_flash * 0.85);
                        tint = mix(tint, vec3(0.90, 0.62, 0.22), u_ultra_flash * 0.75);
                        tint = mix(tint, vec3(0.14, 0.30, 0.50), u_dash_pulse * 0.55);
                        tint = mix(tint, vec3(0.42, 0.10, 0.10), u_hp_danger * 0.60);
                        tint = mix(tint, vec3(0.20, 0.10, 0.28), u_boss_pressure * 0.40);
                        fragColor = vec4(tint, alpha);
                    }
                """,
            )
            quad = array(
                "f",
                [
                    -1.0,
                    -1.0,
                    0.0,
                    0.0,
                    1.0,
                    -1.0,
                    1.0,
                    0.0,
                    -1.0,
                    1.0,
                    0.0,
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                ],
            )
            self._vbo = self._ctx.buffer(quad.tobytes())
            self._vao = self._ctx.vertex_array(self._prog, [(self._vbo, "2f 2f", "in_pos", "in_uv")])
            self._ready = True
            return True
        except Exception as exc:  # pragma: no cover - platform/driver dependent
            self.last_error = str(exc)
            self.enabled = False
            LOG.warning("AdvancedFX disabled: %s", exc)
            return False

    def _ensure_fallback(self) -> None:
        if self._fb_main is not None:
            return
        # Rectangle overlays drawn directly in on_draw as a no-dependency fallback.
        self._fb_main = shapes.Rectangle(0, 0, self.width, self.height, color=(20, 35, 55))
        self._fb_main.opacity = 0
        self._fb_edge = shapes.Rectangle(0, 0, self.width, self.height, color=(120, 30, 30))
        self._fb_edge.opacity = 0

    def _render_fallback(self, time_s: float, combat_intensity: float, hp_ratio: float, boss_active: bool) -> None:
        self._ensure_fallback()
        ci = max(0.0, min(1.0, float(combat_intensity)))
        hp = max(0.0, min(1.0, float(hp_ratio)))
        hp_danger = (1.0 - hp) ** 1.7
        pulse = 0.5 + 0.5 * math.sin(float(time_s) * 2.4)
        base_alpha = int(10 + 28 * ci + 34 * self._ultra_flash + 26 * self._dash_pulse)
        danger_alpha = int(12 + 70 * hp_danger + (22 if boss_active else 0))
        self._fb_main.color = (24, 42, 70) if self._ultra_flash < 0.2 else (90, 62, 26)
        self._fb_main.opacity = max(0, min(160, base_alpha))
        self._fb_edge.opacity = max(0, min(170, int(danger_alpha * (0.6 + 0.4 * pulse) + self._hit_flash * 80)))
        self._fb_main.draw()
        self._fb_edge.draw()

    def trigger_hit(self, strength: float = 1.0) -> None:
        self._hit_flash = max(self._hit_flash, max(0.0, min(1.0, float(strength))))

    def trigger_ultra(self, strength: float = 1.0) -> None:
        self._ultra_flash = max(self._ultra_flash, max(0.0, min(1.0, float(strength))))

    def trigger_dash(self, strength: float = 1.0) -> None:
        self._dash_pulse = max(self._dash_pulse, max(0.0, min(1.0, float(strength))))

    def render(self, time_s: float, combat_intensity: float, hp_ratio: float = 1.0, boss_active: bool = False) -> None:
        if not self.enabled:
            return
        intensity = max(0.0, min(1.0, float(combat_intensity)))
        hp = max(0.0, min(1.0, float(hp_ratio)))
        hp_danger = (1.0 - hp) ** 1.7
        boss_pressure = 0.85 * intensity if bool(boss_active) else 0.0

        # Decay reactive event pulses.
        self._hit_flash = max(0.0, self._hit_flash - 0.055)
        self._ultra_flash = max(0.0, self._ultra_flash - 0.030)
        self._dash_pulse = max(0.0, self._dash_pulse - 0.065)

        if not self._ensure_ready():
            self._render_fallback(time_s, combat_intensity, hp_ratio, boss_active)
            return

        base = float(getattr(config, "ADVANCED_FX_STRENGTH", 0.55))
        u_intensity = max(0.0, min(1.0, base * (0.45 + 0.55 * intensity)))
        try:
            # Pyglet draw calls can alter GL state between frames. Re-assert blend
            # state here so the fullscreen FX quad layers over the scene instead of
            # replacing it.
            self._ctx.screen.use()
            self._ctx.enable(moderngl.BLEND)
            self._ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)
            self._ctx.viewport = (0, 0, self.width, self.height)
            self._prog["u_time"].value = float(time_s)
            self._prog["u_intensity"].value = u_intensity
            self._prog["u_hit_flash"].value = self._hit_flash
            self._prog["u_ultra_flash"].value = self._ultra_flash
            self._prog["u_dash_pulse"].value = self._dash_pulse
            self._prog["u_hp_danger"].value = hp_danger
            self._prog["u_boss_pressure"].value = boss_pressure
            self._prog["u_resolution"].value = (float(self.width), float(self.height))
            self._vao.render(moderngl.TRIANGLE_STRIP)
        except Exception as exc:  # pragma: no cover - context/device dependent
            self.last_error = str(exc)
            self.enabled = False
            LOG.warning("AdvancedFX render disabled: %s", exc)
