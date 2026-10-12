#!/usr/bin/env python3
"""Pure-stdlib sound-effect synthesizer for PLOUTO.

Renders every recipe registered below into mono, 22050 Hz, 16-bit PCM WAV
files at assets/audio/sfx_<name>.wav under the project root. Uses only math,
struct, wave, random, os and sys. Output is deterministic: every sound seeds
its own random.Random from its name.

Run from the project root:
    .venv\\Scripts\\python.exe tools\\synth_sfx.py

Prints a table of name, duration (s), peak (0..1) and RMS (0..1) per file.
"""

import math
import os
import random
import struct
import sys
import wave

SR = 22050
TWO_PI = 2.0 * math.pi
MAX_PEAK = 0.75
PCM_FULL = 32767

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT_ROOT, "assets", "audio")


# ---------------------------------------------------------------------------
# Basic helpers
# ---------------------------------------------------------------------------

def n_samples(seconds):
    return max(1, int(round(seconds * SR)))


def midi_hz(midi):
    """Equal-tempered frequency of a MIDI note number (A4 = 69 = 440 Hz)."""
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def _as_fn(value):
    """Wrap a constant as a t -> value callable (t in seconds)."""
    if callable(value):
        return value
    return lambda t, v=value: v


def sweep(f0, f1, dur, curve="exp"):
    """Frequency (or cutoff) curve from f0 to f1 over dur seconds, then holds f1."""
    def fn(t):
        u = min(1.0, max(0.0, t / dur))
        if curve == "exp":
            return f0 * (f1 / f0) ** u
        return f0 + (f1 - f0) * u
    return fn


def vib(fn, rate, depth):
    """Adds vibrato (rate in Hz, relative depth) to a frequency curve."""
    base = _as_fn(fn)
    return lambda t: base(t) * (1.0 + depth * math.sin(TWO_PI * rate * t))


def siren(lo, hi, period):
    """Triangle-shaped glide between lo and hi Hz, one up-and-down per period."""
    def fn(t):
        u = (t / period) % 1.0
        tri = 1.0 - abs(2.0 * u - 1.0)  # 0 -> 1 -> 0
        return lo + (hi - lo) * tri
    return fn


def _wave(kind, phase):
    p = phase - math.floor(phase)
    if kind == "sine":
        return math.sin(TWO_PI * p)
    if kind == "tri":
        return 1.0 - 4.0 * abs(p - 0.5)
    if kind == "square":
        return 1.0 if p < 0.5 else -1.0
    if kind == "saw":
        return 2.0 * p - 1.0
    raise ValueError("unknown oscillator: %r" % (kind,))


def osc(n, freq, kind="sine"):
    """n samples of an oscillator. freq is Hz or a t -> Hz callable."""
    f_fn = _as_fn(freq)
    out = [0.0] * n
    phase = 0.0
    for i in range(n):
        out[i] = _wave(kind, phase)
        phase += f_fn(i / SR) / SR
    return out


def white(n, rng):
    return [rng.uniform(-1.0, 1.0) for _ in range(n)]


def lowpass(x, fc):
    """One-pole lowpass. fc is Hz or a t -> Hz callable."""
    f_fn = _as_fn(fc)
    y = 0.0
    out = [0.0] * len(x)
    for i, v in enumerate(x):
        a = 1.0 - math.exp(-TWO_PI * f_fn(i / SR) / SR)
        y += a * (v - y)
        out[i] = y
    return out


def highpass(x, fc):
    """One-pole highpass, built as the input minus its lowpass."""
    low = lowpass(x, fc)
    return [v - l for v, l in zip(x, low)]


def env_adsr(n, attack=0.002, decay=0.1, sustain=0.0, release=0.005):
    """Linear attack, exponential decay toward sustain (decay is a time
    constant in seconds), and a linear release fade over the last `release`
    seconds so every sound ends at zero (no clicks)."""
    a = max(1, int(round(attack * SR)))
    r = max(1, int(round(release * SR)))
    out = [0.0] * n
    for i in range(n):
        if i < a:
            v = (i + 1) / float(a)
        elif decay > 0.0:
            v = sustain + (1.0 - sustain) * math.exp(-((i - a) / float(SR)) / decay)
        else:
            v = sustain
        if i >= n - r:
            v *= max(0.0, (n - i - 1) / float(r))
        out[i] = v
    return out


def mul(*arrays):
    """Sample-wise product of equal-length lists."""
    return [math.prod(vals) for vals in zip(*arrays)]


def am(n, rate, depth):
    """Amplitude LFO (tremolo) moving between (1 - depth) and 1."""
    return [1.0 - depth + depth * (0.5 + 0.5 * math.sin(TWO_PI * rate * i / SR))
            for i in range(n)]


def add_at(buf, sig, t0=0.0, gain=1.0):
    """Mix sig into buf (a list, grown as needed) starting at t0 seconds."""
    start = int(round(t0 * SR))
    end = start + len(sig)
    if end > len(buf):
        buf.extend([0.0] * (end - len(buf)))
    for i, v in enumerate(sig):
        buf[start + i] += gain * v
    return buf


# ---------------------------------------------------------------------------
# Voices
# ---------------------------------------------------------------------------

def noise_env(dur, rng, attack, decay, lp=None, hp=None, sustain=0.0, release=0.005):
    """Filtered white noise with an envelope."""
    n = n_samples(dur)
    x = white(n, rng)
    if lp is not None:
        x = lowpass(x, lp)
    if hp is not None:
        x = highpass(x, hp)
    return mul(x, env_adsr(n, attack, decay, sustain, release))


def tone_env(dur, freq, kind, attack, decay, sustain=0.0, release=0.005, lp=None):
    """Oscillator with an envelope, optionally lowpassed."""
    n = n_samples(dur)
    x = osc(n, freq, kind)
    if lp is not None:
        x = lowpass(x, lp)
    return mul(x, env_adsr(n, attack, decay, sustain, release))


def chime(buf, t0, freq, dur, decay, gain=1.0):
    """Bell-like note: sine plus a quieter octave partial, exponential decay."""
    n = n_samples(dur)
    env = env_adsr(n, 0.002, decay, 0.0, 0.02)
    body = osc(n, freq, "sine")
    partial = osc(n, freq * 2.0, "sine")
    add_at(buf, [(b + 0.25 * p) * e for b, p, e in zip(body, partial, env)], t0, gain)


def synth_note(buf, t0, freq, dur, decay, gain=1.0, kind="saw", fc=2400.0, detune=0.004):
    """Lowpassed oscillator pair (slightly detuned) with a decaying envelope."""
    n = n_samples(dur)
    body = osc(n, freq, kind)
    if detune:
        second = osc(n, freq * (1.0 + detune), kind)
        body = [0.5 * (a + b) for a, b in zip(body, second)]
    body = lowpass(body, fc)
    add_at(buf, mul(body, env_adsr(n, 0.006, decay, 0.0, 0.02)), t0, gain)


def boom(buf, rng, t0, scale, length=0.5):
    """Explosion: lowpass-swept noise over a falling sub-bass thump."""
    add_at(buf, noise_env(length, rng, 0.001, length * 0.3,
                          lp=sweep(2200, 160, length * 0.6)), t0, 0.9 * scale)
    add_at(buf, tone_env(length, sweep(100, 32, length * 0.7), "sine",
                         0.002, length * 0.4), t0, 1.0 * scale)


# ---------------------------------------------------------------------------
# Output stage
# ---------------------------------------------------------------------------

def finish(buf, level, drive):
    """Peak-normalise, soft-clip with tanh(drive * x), then scale so the
    peak equals `level` (a fraction of full scale)."""
    if not buf:
        raise ValueError("empty buffer")
    peak = 0.0
    for v in buf:
        if not math.isfinite(v):
            raise ValueError("non-finite sample")
        if abs(v) > peak:
            peak = abs(v)
    if peak <= 0.0:
        raise ValueError("silent buffer")
    x = [v / peak for v in buf]
    if drive > 1.0:
        k = math.tanh(drive)
        x = [math.tanh(drive * v) / k for v in x]
    peak2 = max(abs(v) for v in x)
    return [v * (level / peak2) for v in x]


def to_pcm16(x):
    out = []
    for v in x:
        s = int(round(v * PCM_FULL))
        out.append(max(-PCM_FULL, min(PCM_FULL, s)))
    return out


def write_wav(path, samples):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(struct.pack("<%dh" % len(samples), *samples))


def seed_for(name):
    seed = 0
    for ch in name:
        seed = (seed * 131 + ord(ch)) & 0x7FFFFFFF
    return seed


# ---------------------------------------------------------------------------
# Recipe registry
# ---------------------------------------------------------------------------

SOUNDS = []


def sound(name, level=0.70, drive=1.0):
    """Registers a recipe: fn(rng) -> float buffer, peaked at `level`."""
    def register(fn):
        SOUNDS.append((name, fn, level, drive))
        return fn
    return register


# ---- Player weapons -------------------------------------------------------

@sound("shot_basic", level=0.70, drive=1.6)
def _shot_basic(rng):
    buf = []
    # Square pitch drop through a falling lowpass: the core "pew".
    add_at(buf, tone_env(0.12, sweep(1100, 180, 0.12), "square", 0.001, 0.04,
                         lp=sweep(5000, 900, 0.10)), 0.0, 1.0)
    add_at(buf, tone_env(0.12, sweep(560, 150, 0.12), "sine", 0.001, 0.05), 0.0, 0.5)
    add_at(buf, noise_env(0.012, rng, 0.0005, 0.004, hp=3000.0), 0.0, 0.6)
    return buf


@sound("shot_spread", level=0.72, drive=1.4)
def _shot_spread(rng):
    buf = []
    add_at(buf, tone_env(0.20, sweep(260, 70, 0.20), "tri", 0.002, 0.07), 0.0, 0.8)
    add_at(buf, noise_env(0.20, rng, 0.001, 0.035, lp=sweep(3500, 400, 0.15)), 0.0, 1.0)
    # Four pellet ticks spread over the first ~50 ms.
    for k in range(4):
        add_at(buf, noise_env(0.02, rng, 0.0005, 0.006, hp=2500.0), 0.005 + 0.012 * k, 0.35)
    return buf


@sound("shot_rapid", level=0.62, drive=1.3)
def _shot_rapid(rng):
    buf = []
    add_at(buf, tone_env(0.06, sweep(1500, 520, 0.06), "square", 0.0005, 0.018,
                         lp=sweep(6000, 1500, 0.05)), 0.0, 0.7)
    add_at(buf, noise_env(0.012, rng, 0.0003, 0.004, hp=4000.0), 0.0, 0.5)
    return buf


@sound("shot_heavy", level=0.72, drive=2.0)
def _shot_heavy(rng):
    buf = []
    add_at(buf, tone_env(0.25, sweep(190, 45, 0.25), "sine", 0.002, 0.09), 0.0, 1.0)
    add_at(buf, tone_env(0.18, sweep(420, 110, 0.18), "saw", 0.001, 0.06,
                         lp=sweep(1800, 300, 0.18)), 0.0, 0.5)
    # Detuned second saw for a fatter, slightly out-of-tune body.
    add_at(buf, tone_env(0.18, sweep(426, 112, 0.18), "saw", 0.001, 0.06,
                         lp=sweep(1800, 300, 0.18)), 0.0, 0.3)
    add_at(buf, noise_env(0.06, rng, 0.0005, 0.02, lp=2500.0), 0.0, 0.6)
    return buf


@sound("shot_plasma", level=0.70, drive=1.4)
def _shot_plasma(rng):
    buf = []
    f_main = vib(sweep(330, 1100, 0.20), 28.0, 0.03)
    f_det = vib(sweep(337, 1122, 0.20), 28.0, 0.03)
    add_at(buf, tone_env(0.22, f_main, "tri", 0.005, 0.10, release=0.02), 0.0, 0.8)
    add_at(buf, tone_env(0.22, f_det, "tri", 0.005, 0.10, release=0.02), 0.0, 0.5)
    add_at(buf, noise_env(0.22, rng, 0.01, 0.10, hp=sweep(2000, 6000, 0.20)), 0.0, 0.25)
    return buf


@sound("shot_railgun", level=0.72, drive=1.8)
def _shot_railgun(rng):
    buf = []
    add_at(buf, noise_env(0.02, rng, 0.0002, 0.006, hp=3000.0), 0.0, 1.0)  # crack
    add_at(buf, noise_env(0.04, rng, 0.0002, 0.012, hp=2000.0), 0.0, 0.6)
    add_at(buf, tone_env(0.25, sweep(2000, 600, 0.25), "sine", 0.002, 0.10), 0.0, 0.6)
    add_at(buf, tone_env(0.25, sweep(1400, 900, 0.25), "sine", 0.003, 0.14), 0.0, 0.35)
    add_at(buf, tone_env(0.12, sweep(150, 60, 0.12), "sine", 0.001, 0.05), 0.0, 0.6)
    return buf


@sound("shot_flak", level=0.70, drive=1.5)
def _shot_flak(rng):
    buf = []
    add_at(buf, noise_env(0.20, rng, 0.001, 0.05, lp=sweep(2600, 500, 0.12)), 0.0, 0.9)
    add_at(buf, tone_env(0.08, sweep(520, 180, 0.08), "tri", 0.001, 0.035), 0.0, 0.7)
    add_at(buf, noise_env(0.10, rng, 0.02, 0.05, hp=1500.0), 0.03, 0.3)  # air burst
    add_at(buf, tone_env(0.05, 1100.0, "sine", 0.001, 0.012), 0.0, 0.25)
    return buf


# ---- Enemy and hazard sounds ----------------------------------------------

@sound("enemy_shot", level=0.60, drive=1.3)
def _enemy_shot(rng):
    buf = []
    add_at(buf, tone_env(0.14, sweep(400, 150, 0.14), "saw", 0.002, 0.045,
                         lp=sweep(1600, 350, 0.12)), 0.0, 0.8)
    add_at(buf, tone_env(0.14, sweep(204, 76, 0.14), "square", 0.002, 0.05, lp=900.0), 0.0, 0.3)
    add_at(buf, noise_env(0.02, rng, 0.0005, 0.006, lp=2000.0), 0.0, 0.3)
    return buf


@sound("enemy_bomb", level=0.68, drive=1.2)
def _enemy_bomb(rng):
    buf = []
    n = n_samples(0.36)
    trem = am(n, 14.0, 0.25)
    env = env_adsr(n, 0.01, 0.5, 0.6, 0.06)
    fall = vib(sweep(1000, 170, 0.36), 9.0, 0.02)
    add_at(buf, mul(osc(n, fall, "sine"), trem, env), 0.0, 0.8)
    add_at(buf, mul(osc(n, sweep(1010, 175, 0.36), "tri"), trem, env), 0.0, 0.35)
    # Impact thud when the bomb lands.
    add_at(buf, tone_env(0.14, sweep(120, 40, 0.14), "sine", 0.001, 0.07), 0.36, 0.9)
    add_at(buf, noise_env(0.06, rng, 0.0005, 0.02, lp=900.0), 0.36, 0.5)
    return buf


@sound("laser_charge", level=0.62, drive=1.2)
def _laser_charge(rng):
    buf = []
    n = n_samples(0.5)
    env = env_adsr(n, 0.35, 0.3, 0.8, 0.05)  # slow swell = charging up
    rise = lowpass(osc(n, sweep(180, 1500, 0.5), "saw"), sweep(600, 4000, 0.5))
    add_at(buf, mul(rise, env), 0.0, 0.6)
    add_at(buf, mul(osc(n, sweep(360, 3000, 0.5), "sine"), env), 0.0, 0.3)
    add_at(buf, mul(highpass(white(n, rng), sweep(3000, 7000, 0.5)), env), 0.0, 0.12)
    return buf


@sound("hit", level=0.62, drive=1.2)
def _hit(rng):
    buf = []
    add_at(buf, noise_env(0.05, rng, 0.0003, 0.012, lp=3500.0), 0.0, 1.0)
    add_at(buf, tone_env(0.05, sweep(320, 170, 0.05), "sine", 0.0005, 0.015), 0.0, 0.8)
    return buf


@sound("hit_crit", level=0.72, drive=1.5)
def _hit_crit(rng):
    buf = []
    add_at(buf, noise_env(0.05, rng, 0.0003, 0.012, lp=4000.0), 0.0, 0.9)
    add_at(buf, tone_env(0.05, sweep(320, 170, 0.05), "sine", 0.0005, 0.015), 0.0, 0.6)
    add_at(buf, tone_env(0.10, sweep(700, 1400, 0.05), "tri", 0.001, 0.05), 0.0, 0.5)
    add_at(buf, tone_env(0.08, 2100.0, "sine", 0.001, 0.03), 0.0, 0.3)
    add_at(buf, noise_env(0.02, rng, 0.0003, 0.006, hp=4000.0), 0.0, 0.3)
    return buf


@sound("kill", level=0.72, drive=1.6)
def _kill(rng):
    buf = []
    add_at(buf, noise_env(0.35, rng, 0.001, 0.09, lp=sweep(2600, 250, 0.2)), 0.0, 0.7)
    add_at(buf, tone_env(0.30, sweep(640, 110, 0.30), "square", 0.001, 0.11,
                         lp=sweep(2200, 300, 0.30)), 0.0, 0.6)
    add_at(buf, tone_env(0.08, sweep(1200, 1800, 0.08), "sine", 0.001, 0.03), 0.0, 0.25)
    return buf


@sound("kill_big", level=0.74, drive=2.0)
def _kill_big(rng):
    buf = []
    add_at(buf, noise_env(0.70, rng, 0.002, 0.20, lp=sweep(1800, 180, 0.40)), 0.0, 0.7)
    add_at(buf, tone_env(0.70, sweep(120, 35, 0.60), "sine", 0.002, 0.25), 0.0, 1.0)
    add_at(buf, tone_env(0.40, sweep(420, 90, 0.40), "saw", 0.002, 0.18,
                         lp=sweep(1500, 250, 0.40)), 0.0, 0.55)
    add_at(buf, tone_env(0.10, sweep(900, 1500, 0.10), "tri", 0.001, 0.06), 0.0, 0.3)
    return buf


@sound("explode", level=0.74, drive=2.5)
def _explode(rng):
    buf = []
    add_at(buf, noise_env(0.60, rng, 0.001, 0.20, lp=sweep(3000, 180, 0.35)), 0.0, 1.0)
    add_at(buf, tone_env(0.50, sweep(95, 28, 0.50), "sine", 0.002, 0.28), 0.0, 1.1)
    add_at(buf, noise_env(0.60, rng, 0.02, 0.25, lp=500.0), 0.0, 0.3)
    # Crackle: random short bursts over the first quarter second.
    for _ in range(8):
        t0 = 0.01 + 0.25 * rng.random()
        add_at(buf, noise_env(0.02, rng, 0.0003, 0.006, hp=2000.0), t0, 0.2)
    return buf


@sound("hurt", level=0.66, drive=1.4)
def _hurt(rng):
    buf = []
    add_at(buf, tone_env(0.25, vib(sweep(560, 220, 0.25), 12.0, 0.04), "tri",
                         0.004, 0.12), 0.0, 0.8)
    add_at(buf, tone_env(0.25, vib(sweep(588, 231, 0.25), 12.0, 0.04), "saw",
                         0.004, 0.12, lp=1500.0), 0.0, 0.35)
    add_at(buf, noise_env(0.06, rng, 0.001, 0.03, lp=1000.0), 0.0, 0.4)
    return buf


@sound("shield_hit", level=0.62, drive=1.2)
def _shield_hit(rng):
    buf = []
    add_at(buf, tone_env(0.14, sweep(1100, 1700, 0.06), "sine", 0.001, 0.07), 0.0, 0.8)
    add_at(buf, tone_env(0.20, sweep(2200, 1900, 0.20), "sine", 0.001, 0.08), 0.0, 0.4)
    add_at(buf, tone_env(0.20, 1650.0, "tri", 0.002, 0.11), 0.0, 0.3)
    add_at(buf, noise_env(0.05, rng, 0.0005, 0.015, hp=4000.0), 0.0, 0.4)
    return buf


@sound("contact", level=0.72, drive=1.6)
def _contact(rng):
    buf = []
    add_at(buf, tone_env(0.15, sweep(190, 80, 0.15), "square", 0.001, 0.05,
                         lp=sweep(900, 250, 0.12)), 0.0, 0.9)
    add_at(buf, noise_env(0.10, rng, 0.0005, 0.03, lp=sweep(700, 300, 0.08)), 0.0, 0.6)
    add_at(buf, tone_env(0.04, 120.0, "sine", 0.001, 0.04), 0.0, 0.5)
    return buf


# ---- Pickups, abilities, UI -----------------------------------------------

@sound("pickup", level=0.66, drive=1.0)
def _pickup(rng):
    buf = []
    for k, midi in enumerate((69, 72, 76)):  # A4 C5 E5: A minor arpeggio
        chime(buf, 0.05 * k, midi_hz(midi), 0.22, 0.09, 0.8)
    return buf


@sound("pickup_rare", level=0.70, drive=1.0)
def _pickup_rare(rng):
    buf = []
    for k, midi in enumerate((69, 72, 76, 81)):  # A4 C5 E5 A5 arpeggio
        chime(buf, 0.06 * k, midi_hz(midi), 0.40, 0.22, 0.6)
    for midi in (69, 72, 76):  # A minor chord ringing under the arpeggio
        synth_note(buf, 0.24, midi_hz(midi), 0.36, 0.25, gain=0.22, kind="tri", fc=3000.0)
    add_at(buf, noise_env(0.20, rng, 0.002, 0.05, hp=6000.0), 0.18, 0.12)  # sparkle
    return buf


@sound("dash", level=0.62, drive=1.0)
def _dash(rng):
    buf = []
    n = n_samples(0.22)
    x = white(n, rng)
    x = lowpass(x, sweep(500, 4000, 0.12))  # brightens as the dash goes
    x = highpass(x, 250.0)
    add_at(buf, mul(x, env_adsr(n, 0.04, 0.10, 0.0, 0.05)), 0.0, 1.0)
    add_at(buf, tone_env(0.20, sweep(180, 420, 0.20), "tri", 0.03, 0.12), 0.0, 0.3)
    return buf


@sound("boost", level=0.66, drive=1.3)
def _boost(rng):
    buf = []
    n = n_samples(0.35)
    env = env_adsr(n, 0.02, 0.25, 0.5, 0.06)
    add_at(buf, mul(lowpass(osc(n, sweep(220, 880, 0.35), "saw"), sweep(500, 3500, 0.30)), env),
           0.0, 0.7)
    add_at(buf, mul(lowpass(osc(n, sweep(224, 888, 0.35), "square"), 900.0), env), 0.0, 0.3)
    add_at(buf, mul(lowpass(white(n, rng), sweep(800, 4000, 0.35)), env), 0.0, 0.25)
    return buf


@sound("ultra_fire", level=0.74, drive=2.2)
def _ultra_fire(rng):
    buf = []
    add_at(buf, tone_env(0.70, sweep(110, 38, 0.50), "sine", 0.002, 0.25), 0.0, 1.0)
    add_at(buf, tone_env(0.50, sweep(1500, 200, 0.45), "square", 0.003, 0.20,
                         sustain=0.3, release=0.10, lp=sweep(3500, 300, 0.45)), 0.0, 0.55)
    add_at(buf, tone_env(0.50, sweep(1512, 204, 0.45), "saw", 0.003, 0.20,
                         sustain=0.3, release=0.10, lp=sweep(3500, 300, 0.45)), 0.0, 0.3)
    add_at(buf, noise_env(0.70, rng, 0.002, 0.25, lp=sweep(4500, 300, 0.40)), 0.0, 0.7)
    add_at(buf, tone_env(0.08, sweep(600, 2400, 0.08), "tri", 0.001, 0.05), 0.0, 0.3)
    return buf


@sound("ultra_ready", level=0.70, drive=1.0)
def _ultra_ready(rng):
    buf = []
    for k, midi in enumerate((69, 73, 76, 81)):  # A4 C#5 E5 A5: A major arpeggio
        synth_note(buf, 0.07 * k, midi_hz(midi), 0.30, 0.15, gain=0.45, kind="saw", fc=2600.0)
    for midi in (69, 73, 76):  # A major chord to close
        synth_note(buf, 0.30, midi_hz(midi), 0.30, 0.25, gain=0.25, kind="saw", fc=2600.0)
    return buf


@sound("wave_clear", level=0.70, drive=1.0)
def _wave_clear(rng):
    buf = []
    for k, midi in enumerate((69, 73, 76, 81)):  # A4 C#5 E5 A5: ascending A major
        synth_note(buf, 0.11 * k, midi_hz(midi), 0.37, 0.22, gain=0.45, kind="tri", fc=3000.0)
    for midi in (69, 73, 76):  # chord under the top note
        synth_note(buf, 0.33, midi_hz(midi), 0.37, 0.28, gain=0.22, kind="saw", fc=2600.0)
    return buf


@sound("boss_warn", level=0.72, drive=1.6)
def _boss_warn(rng):
    buf = []
    n = n_samples(1.6)
    f_siren = siren(430.0, 830.0, 0.8)  # two full up-and-down glides
    wobble = am(n, 6.0, 0.15)
    env = env_adsr(n, 0.02, 0.0, 1.0, 0.08)

    def detuned(t):
        return 1.006 * f_siren(t)

    sq = lowpass(osc(n, f_siren, "square"), 1800.0)
    add_at(buf, mul(sq, wobble, env), 0.0, 0.6)
    add_at(buf, mul(osc(n, f_siren, "sine"), wobble, env), 0.0, 0.5)
    add_at(buf, mul(osc(n, detuned, "sine"), wobble, env), 0.0, 0.35)
    return buf


@sound("boss_die", level=0.74, drive=2.0)
def _boss_die(rng):
    buf = []
    # Staggered explosions across the death sequence.
    for t0, scale in ((0.0, 1.0), (0.35, 0.8), (0.70, 0.9), (1.05, 0.7), (1.30, 0.6)):
        boom(buf, rng, t0, scale)
    # Long descending rumble with a noisy tail.
    add_at(buf, tone_env(1.6, sweep(260, 38, 1.6), "tri", 0.01, 0.6,
                         sustain=0.2, release=0.3), 0.0, 0.35)
    add_at(buf, noise_env(1.8, rng, 0.02, 0.5, lp=sweep(900, 120, 1.2)), 0.0, 0.45)
    return buf


@sound("reward_open", level=0.66, drive=1.0)
def _reward_open(rng):
    buf = []
    add_at(buf, noise_env(0.02, rng, 0.0005, 0.005, hp=3000.0), 0.0, 0.4)  # latch click
    for k, midi in enumerate((69, 72, 76, 81)):  # A4 C5 E5 A5: rising A minor run
        chime(buf, 0.03 + 0.07 * k, midi_hz(midi), 0.36, 0.18, 0.6)
    return buf


@sound("game_over", level=0.66, drive=1.0)
def _game_over(rng):
    buf = []
    # Falling A natural minor phrase A4 G4 F4 E4, the last note held.
    for k, midi in enumerate((69, 67, 65, 64)):
        dur = 0.55 if k == 3 else 0.42
        synth_note(buf, 0.33 * k, midi_hz(midi), dur, 0.30, gain=0.5,
                   kind="tri", fc=1800.0, detune=0.006)
    # Sinking sub glide underneath.
    add_at(buf, tone_env(1.5, sweep(220, 55, 1.5), "sine", 0.02, 0.8,
                         sustain=0.3, release=0.2), 0.0, 0.4)
    return buf


@sound("ui_click", level=0.45, drive=1.0)
def _ui_click(rng):
    buf = []
    add_at(buf, tone_env(0.04, sweep(1800, 900, 0.03), "square", 0.0003, 0.008, lp=4000.0), 0.0, 0.6)
    add_at(buf, noise_env(0.01, rng, 0.0002, 0.003, hp=3000.0), 0.0, 0.4)
    return buf


@sound("ui_hover", level=0.32, drive=1.0)
def _ui_hover(rng):
    buf = []
    add_at(buf, tone_env(0.05, sweep(1250, 1400, 0.05), "sine", 0.002, 0.012), 0.0, 1.0)
    add_at(buf, tone_env(0.03, 2500.0, "sine", 0.001, 0.006), 0.0, 0.2)
    return buf


@sound("spawn_in", level=0.62, drive=1.3)
def _spawn_in(rng):
    buf = []
    add_at(buf, tone_env(0.35, sweep(160, 980, 0.30), "sine", 0.04, 0.12,
                         sustain=0.3, release=0.05), 0.0, 0.7)
    add_at(buf, tone_env(0.35, sweep(320, 1960, 0.30), "tri", 0.04, 0.12,
                         sustain=0.3, release=0.05, lp=3000.0), 0.0, 0.25)
    add_at(buf, noise_env(0.30, rng, 0.10, 0.10, hp=sweep(1500, 6000, 0.30),
                          sustain=0.2, release=0.05), 0.0, 0.2)
    add_at(buf, tone_env(0.05, 1500.0, "sine", 0.001, 0.02), 0.30, 0.3)  # materialise pop
    return buf


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def render(name, fn, level, drive):
    """Renders one recipe, writes its WAV, and returns (duration, peak, rms)."""
    rng = random.Random(seed_for(name))
    samples = to_pcm16(finish(fn(rng), level, drive))
    write_wav(os.path.join(OUT_DIR, "sfx_%s.wav" % name), samples)
    count = len(samples)
    peak = max(abs(s) for s in samples) / float(PCM_FULL)
    rms = math.sqrt(sum(s * s for s in samples) / float(count)) / PCM_FULL
    return count / float(SR), peak, rms


def main():
    if len(set(name for name, _, _, _ in SOUNDS)) != len(SOUNDS):
        raise SystemExit("duplicate sound name in registry")
    os.makedirs(OUT_DIR, exist_ok=True)
    rows = []
    for name, fn, level, drive in SOUNDS:
        if level > MAX_PEAK:
            raise SystemExit("level for %s exceeds %.2f" % (name, MAX_PEAK))
        dur, peak, rms = render(name, fn, level, drive)
        if peak > MAX_PEAK:
            raise SystemExit("peak for %s is %.3f" % (name, peak))
        rows.append((name, dur, peak, rms))
    print("%-14s %9s %8s %8s" % ("name", "dur_s", "peak", "rms"))
    for name, dur, peak, rms in rows:
        print("%-14s %9.3f %8.3f %8.4f" % (name, dur, peak, rms))
    print("wrote %d files to %s" % (len(rows), OUT_DIR))
    return 0


if __name__ == "__main__":
    sys.exit(main())
