#!/usr/bin/env python3
"""Procedural music for PLOUTO. Pure standard library (math, struct, wave, random, os, sys).

Writes two seamless loops to assets/audio/ as mono, 22050 Hz, 16-bit PCM WAV:

  music_menu.wav    ambient. Detuned triangle/saw pad chords that move once per bar,
                    a low drone, a sparse arpeggio. 70 BPM, 7 bars = 24.000 s. A minor.
  music_battle.wav  synthwave. Sawtooth bass on eighths through a ~600 Hz one-pole
                    lowpass, kick on each quarter, snare on beats 2 and 4, offbeat
                    hi-hats, 16th-note triangle arpeggio, 4-bar lead motifs.
                    Am - F - C - G (two bars each). 127.5 BPM, 17 bars = 32.000 s.

Tempo note: 128 BPM cannot give a whole number of 4/4 bars close to 32 s
(17 bars = 31.875 s, 18 bars = 33.750 s). 127.5 BPM makes 17 bars exactly 32.000 s.
Change BATTLE["bpm"] and BATTLE["bars"] to trade this off (for example 120 BPM, 16 bars).

Loop seam: every event sits on an integer sample grid derived from musical beats,
the loop length is an exact whole number of bars, every note carries its own
fade-out so it ends inside its buffer, and add_at() refuses to write past the loop end.
The drone and LFO frequencies are whole cycles per loop, so they are periodic.

Run from the project root:  .venv\\Scripts\\python.exe tools\\synth_music.py
"""

import math
import os
import random
import struct
import sys
import wave

SR = 22050
TWO_PI = 2.0 * math.pi
HALF_PI = 0.5 * math.pi
FULL_SCALE = 32767

MENU = {"name": "music_menu", "bpm": 70.0, "bars": 7, "peak": 0.65, "seconds": 24.0}
BATTLE = {"name": "music_battle", "bpm": 127.5, "bars": 17, "peak": 0.78, "seconds": 32.0}


# ----------------------------------------------------------------- timing helpers
def beats_to_samples(bpm, beats):
    """Musical position in beats (quarter notes) to the nearest sample index."""
    return int(round(beats * 60.0 * SR / bpm))


def secs_to_samples(sec):
    return int(round(sec * SR))


def whole_cycles(freq, loop_seconds):
    """Nudge a frequency so it completes an integer number of cycles per loop."""
    return round(freq * loop_seconds) / loop_seconds


def clip(start, n, total):
    """Length of a note of n samples starting at `start`, clipped to the loop end."""
    return max(0, min(n, total - start))


def midi_hz(m):
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


def detune_hz(f, cents):
    return f * 2.0 ** (cents / 1200.0)


# ----------------------------------------------------------------- oscillators (phase 0 at start)
def osc_sine(freq, n):
    w = TWO_PI * freq / SR
    return [math.sin(w * i) for i in range(n)]


def osc_tri(freq, n):
    inc = freq / SR
    return [4.0 * abs((i * inc) % 1.0 - 0.5) - 1.0 for i in range(n)]


def osc_saw(freq, n):
    inc = freq / SR
    return [2.0 * ((i * inc) % 1.0) - 1.0 for i in range(n)]


def osc_square(freq, n):
    inc = freq / SR
    return [1.0 if (i * inc) % 1.0 < 0.5 else -1.0 for i in range(n)]


def lowpass(x, cutoff_hz):
    """One-pole lowpass with state starting at zero."""
    a = 1.0 - math.exp(-TWO_PI * cutoff_hz / SR)
    y = 0.0
    out = []
    push = out.append
    for v in x:
        y += a * (v - y)
        push(y)
    return out


def mul(a, b):
    return [x * y for x, y in zip(a, b)]


def scale(a, k):
    return [x * k for x in a]


# ----------------------------------------------------------------- envelopes
_env_cache = {}


def decay_env(n, tau, attack=0.003, fade=0.012):
    """exp(-t/tau) with a linear attack from 0 and a linear fade to exactly 0 at the
    last sample. Every note is shaped with this, so it always ends inside its buffer."""
    key = (n, tau, attack, fade)
    cached = _env_cache.get(key)
    if cached is not None:
        return cached
    na = max(1, int(attack * SR))
    nf = max(1, int(fade * SR))
    out = []
    for i in range(n):
        v = math.exp(-i / (tau * SR))
        if i < na:
            v *= i / na
        rem = n - 1 - i
        if rem < nf:
            v *= rem / nf
        out.append(v)
    _env_cache[key] = out
    return out


def pad_envelope(start, n, attack_n, rel_start, rel_n):
    """Attack ramp from 0 at `start`, cosine release beginning at absolute index rel_start."""
    out = []
    for j in range(n):
        i = start + j
        a = 1.0 if j >= attack_n else math.sin(HALF_PI * j / attack_n)
        if i < rel_start:
            r = 1.0
        else:
            r = math.cos(HALF_PI * min(1.0, (i - rel_start) / rel_n))
        out.append(a * r)
    return out


# ----------------------------------------------------------------- mixing / output
def add_at(bus, start, buf):
    """Add buf into bus at start. Refuses anything that would run past the loop end."""
    end = start + len(buf)
    if start < 0 or end > len(bus):
        raise ValueError("note [%d, %d) overruns the loop (%d samples)" % (start, end, len(bus)))
    bus[start:end] = [a + b for a, b in zip(bus[start:end], buf)]


def to_pcm16(x, peak_target):
    """Scale the mix so its peak equals peak_target (fraction of full scale), then round to int16."""
    if not all(map(math.isfinite, x)):
        raise ValueError("non-finite sample in mix")
    m = max(max(x), -min(x))
    if m <= 0.0:
        raise ValueError("silent mix")
    k = peak_target / m * FULL_SCALE
    ints = [round(v * k) for v in x]
    # peak_target < 1, so every value is already inside +-FULL_SCALE; checked, not clamped.
    if max(ints) > FULL_SCALE or min(ints) < -FULL_SCALE:
        raise ValueError("PCM overflow")
    return ints


def write_wav(path, pcm):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    chunks = []
    step = 32768
    for k in range(0, len(pcm), step):
        part = pcm[k:k + step]
        chunks.append(struct.pack("<%dh" % len(part), *part))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(chunks))


def analyse(path):
    """Read the written file back and measure it (numbers come from disk, not memory)."""
    with wave.open(path, "rb") as w:
        ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if (ch, sw, rate) != (1, 2, SR):
        raise RuntimeError("bad WAV format in %s: channels=%d width=%d rate=%d" % (path, ch, sw, rate))
    vals = struct.unpack("<%dh" % n, raw)
    peak = max(map(abs, vals)) / FULL_SCALE
    rms = math.sqrt(sum(v * v for v in vals) / n) / FULL_SCALE
    jump = abs(vals[-1] - vals[0]) / FULL_SCALE
    return {"dur": n / rate, "peak": peak, "rms": rms, "bytes": os.path.getsize(path), "jump": jump}


# ----------------------------------------------------------------- menu (ambient)
# One entry per bar: (pad voicing Hz, arpeggio tones Hz). A minor, slow movement.
MENU_CHORDS = [
    ([220.00, 261.63, 329.63], [440.00, 523.25, 659.26, 880.00]),  # Am
    ([174.61, 220.00, 261.63], [349.23, 440.00, 523.25, 698.46]),  # F
    ([196.00, 261.63, 329.63], [392.00, 523.25, 659.26, 783.99]),  # C
    ([196.00, 246.94, 293.66], [392.00, 493.88, 587.33, 783.99]),  # G
    ([220.00, 261.63, 329.63], [440.00, 523.25, 659.26, 880.00]),  # Am
    ([174.61, 220.00, 261.63], [349.23, 440.00, 523.25, 698.46]),  # F
    ([164.81, 196.00, 246.94], [329.63, 392.00, 493.88, 659.26]),  # Em, resolves to Am at the seam
]


def pad_voice(freqs, n):
    """Per voice: two triangles detuned by +-6 cents, plus one saw, summed and lowpassed at 1.4 kHz."""
    mix = [0.0] * n
    for f in freqs:
        for cents in (-6.0, 6.0):
            mix = [a + 0.10 * b for a, b in zip(mix, osc_tri(detune_hz(f, cents), n))]
        mix = [a + 0.05 * b for a, b in zip(mix, osc_saw(f, n))]
    return lowpass(mix, 1400.0)


def render_menu(cfg):
    bpm, bars = cfg["bpm"], cfg["bars"]
    if len(MENU_CHORDS) != bars:
        raise ValueError("MENU_CHORDS must have one entry per bar")
    N = beats_to_samples(bpm, 4 * bars)
    bar = beats_to_samples(bpm, 4)
    loop_s = N / SR

    # Drone: 55 Hz sine + 110 Hz triangle, slow 3-cycle swell. All whole cycles per loop.
    s_low = osc_sine(whole_cycles(55.0, loop_s), N)
    s_high = osc_tri(whole_cycles(110.0, loop_s), N)
    swell = osc_sine(whole_cycles(1.0 / 8.0, loop_s), N)
    drone = [(0.20 * a + 0.07 * b) * (0.75 + 0.25 * c) for a, b, c in zip(s_low, s_high, swell)]

    # Pad: one chord per bar, cross-faded over 1 s (attack of a chord overlaps release of the last).
    # Each chord lasts one bar plus a 1 s release, except the final chord, which releases exactly
    # at the loop end so no tail crosses the seam. Identical chords and envelopes are reused.
    pad = [0.0] * N
    attack_n = secs_to_samples(1.0)
    rel_n = secs_to_samples(1.0)
    last = bars - 1
    voice_memo = {}
    env_memo = {}
    for k, (voicing, _tones) in enumerate(MENU_CHORDS):
        start = bar * k
        if k < last:
            rel_off, n = bar, bar + rel_n
        else:
            rel_off, n = bar - rel_n, bar
        env_key = (n, rel_off)
        if env_key not in env_memo:
            env_memo[env_key] = pad_envelope(0, n, attack_n, rel_off, rel_n)
        voice_key = (tuple(voicing), n)
        if voice_key not in voice_memo:
            voice_memo[voice_key] = pad_voice(voicing, n)
        add_at(pad, start, mul(voice_memo[voice_key], env_memo[env_key]))

    # Sparse arpeggio: three eighth-note slots per bar, triangle voice, 0.42 s decay.
    arp = [0.0] * N
    order = (0, 2, 1, 3)
    count = 0
    for b in range(bars):
        tones = MENU_CHORDS[b][1]
        for slot in (0, 3, 5):
            t0 = beats_to_samples(bpm, 4 * b + 0.5 * slot)
            n = clip(t0, secs_to_samples(1.4), N)
            tri = osc_tri(tones[order[count % 4]], n)
            count += 1
            add_at(arp, t0, scale(mul(tri, decay_env(n, 0.42, attack=0.004, fade=0.02)), 0.25))

    return [d + p + a for d, p, a in zip(drone, pad, arp)]


# ----------------------------------------------------------------- battle (synthwave)
BATTLE_CHORDS = ("Am", "F", "C", "G")  # two bars each, repeating
BASS_HZ = {"Am": 110.00, "F": 87.31, "C": 130.81, "G": 98.00}
ARP_TONES_HZ = {
    "Am": [440.00, 523.25, 659.26, 880.00],
    "F": [349.23, 440.00, 523.25, 698.46],
    "C": [392.00, 523.25, 659.26, 783.99],
    "G": [392.00, 493.88, 587.33, 783.99],
}
ARP_PATTERN = (0, 1, 2, 3, 2, 1, 2, 1)  # indexes into the 4 chord tones, repeated twice per bar

# Lead motifs: 4 groups of 4 bars. Each entry is (MIDI note, length in eighth notes).
# Every bar must sum to 8 eighths (checked at render time).
LEAD_GROUPS = [
    [  # group 1: bars 1-4 (Am, F, C, G)
        [(69, 1), (72, 1), (76, 2), (74, 1), (72, 1), (69, 2)],
        [(72, 1), (77, 1), (81, 2), (79, 1), (77, 1), (72, 2)],
        [(76, 1), (72, 1), (67, 2), (72, 1), (76, 1), (79, 2)],
        [(71, 1), (74, 1), (79, 2), (76, 1), (74, 1), (71, 2)],
    ],
    [  # group 2: bars 5-8
        [(76, 2), (74, 1), (72, 1), (69, 2), (72, 1), (76, 1)],
        [(77, 1), (77, 1), (72, 2), (69, 2), (72, 2)],
        [(72, 1), (76, 1), (79, 1), (76, 1), (72, 2), (67, 2)],
        [(79, 2), (77, 1), (74, 1), (71, 2), (74, 2)],
    ],
    [  # group 3: bars 9-12
        [(81, 1), (79, 1), (76, 1), (74, 1), (72, 2), (76, 2)],
        [(72, 2), (76, 1), (77, 1), (81, 2), (77, 2)],
        [(79, 1), (84, 1), (79, 2), (76, 1), (72, 1), (67, 2)],
        [(74, 2), (71, 1), (74, 1), (79, 2), (74, 2)],
    ],
    [  # group 4: bars 13-16
        [(69, 2), (72, 1), (76, 1), (81, 2), (76, 2)],
        [(81, 1), (77, 1), (72, 1), (77, 1), (81, 2), (84, 2)],
        [(79, 2), (76, 1), (72, 1), (67, 2), (72, 2)],
        [(74, 1), (71, 1), (74, 1), (79, 1), (83, 2), (79, 2)],
    ],
]


def make_kick():
    """Sine sweep 110 -> 45 Hz (time constant 35 ms), 0.11 s amplitude decay, 0.32 s long."""
    n = secs_to_samples(0.32)
    tau_f = 0.035
    body = []
    for i in range(n):
        t = i / SR
        phase = TWO_PI * (45.0 * t + 65.0 * tau_f * (1.0 - math.exp(-t / tau_f)))
        body.append(math.sin(phase))
    return mul(body, decay_env(n, 0.11, attack=0.0005, fade=0.02))


def make_snare(rng):
    """Highpassed noise burst plus a short 185 Hz body tone."""
    n = secs_to_samples(0.22)
    noise = [rng.uniform(-1.0, 1.0) for _ in range(n)]
    lp = lowpass(noise, 1800.0)
    hiss = [a - b for a, b in zip(noise, lp)]
    noise_part = mul(hiss, decay_env(n, 0.065, attack=0.0005, fade=0.02))
    body_part = mul(osc_sine(185.0, n), decay_env(n, 0.035, attack=0.0005, fade=0.02))
    return [0.8 * a + 0.4 * b for a, b in zip(noise_part, body_part)]


def make_hat(rng):
    """Very short first-difference highpassed noise."""
    n = secs_to_samples(0.06)
    noise = [rng.uniform(-1.0, 1.0) for _ in range(n)]
    hp = [noise[0]] + [noise[i] - noise[i - 1] for i in range(1, n)]
    return mul(hp, decay_env(n, 0.018, attack=0.0002, fade=0.012))


def render_battle(cfg):
    bpm, bars = cfg["bpm"], cfg["bars"]
    N = beats_to_samples(bpm, 4 * bars)
    rng = random.Random(20261012)

    def chord_at(bar_index):
        return BATTLE_CHORDS[(bar_index // 2) % 4]

    # Bass: sawtooth on eighths, octave up on the offbeat, one-pole lowpass at 600 Hz.
    bass = [0.0] * N
    for j in range(bars * 8):
        f = BASS_HZ[chord_at(j // 8)] * (2.0 if j % 2 else 1.0)
        t0 = beats_to_samples(bpm, 0.5 * j)
        t1 = beats_to_samples(bpm, 0.5 * (j + 1))
        n = clip(t0, int((t1 - t0) * 0.92), N)
        env = decay_env(n, 0.6, attack=0.002, fade=0.01)
        add_at(bass, t0, [0.30 * s * e for s, e in zip(lowpass(osc_saw(f, n), 600.0), env)])

    # Kick on every quarter.
    kick_template = scale(make_kick(), 0.85)
    kick = [0.0] * N
    for j in range(bars * 4):
        add_at(kick, beats_to_samples(bpm, j), kick_template)

    # Snare on beats 2 and 4.
    snare_template = scale(make_snare(rng), 0.32)
    snare = [0.0] * N
    for j in range(bars * 4):
        if j % 4 in (1, 3):
            add_at(snare, beats_to_samples(bpm, j), snare_template)

    # Offbeat hi-hats (the "and" of every beat), four noise variants cycled.
    hats = [scale(make_hat(rng), 0.12) for _ in range(4)]
    hat_bus = [0.0] * N
    for j in range(bars * 4):
        add_at(hat_bus, beats_to_samples(bpm, j + 0.5), hats[j % 4])

    # 16th-note arpeggio over the chord tones, triangle voice, 0.045 s decay.
    arp = [0.0] * N
    arp_len = secs_to_samples(0.12)
    for g in range(bars * 16):
        b, k = divmod(g, 16)
        tones = ARP_TONES_HZ[chord_at(b)]
        t0 = beats_to_samples(bpm, 0.25 * g)
        n = clip(t0, arp_len, N)
        tri = osc_tri(tones[ARP_PATTERN[k % 8]], n)
        env = decay_env(n, 0.045, attack=0.0005, fade=0.012)
        add_at(arp, t0, [0.10 * t * e for t, e in zip(tri, env)])

    # Lead: square voice through a 2.8 kHz lowpass. Motif changes every 4 bars.
    # The lead rests on the last bar (bar 17), giving the loop a breath before the seam.
    lead = [0.0] * N
    for b in range(bars - 1):
        group, bar_in_group = (b // 4) % 4, b % 4
        motif = LEAD_GROUPS[group][bar_in_group]
        if sum(eighths for _m, eighths in motif) != 8:
            raise ValueError("lead bar %d does not sum to 8 eighths" % b)
        e = 0
        for midi, eighths in motif:
            t0 = beats_to_samples(bpm, 4 * b + 0.5 * e)
            t1 = beats_to_samples(bpm, 4 * b + 0.5 * (e + eighths))
            n = clip(t0, int((t1 - t0) * 0.92), N)
            env = decay_env(n, 0.5, attack=0.004, fade=0.02)
            sig = lowpass(osc_square(midi_hz(midi), n), 2800.0)
            add_at(lead, t0, [0.14 * s * v for s, v in zip(sig, env)])
            e += eighths

    return [k + s + h + b + a + l for k, s, h, b, a, l in zip(kick, snare, hat_bus, bass, arp, lead)]


# ----------------------------------------------------------------- main
def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(root, "assets", "audio")
    results = []
    for cfg, render in ((MENU, render_menu), (BATTLE, render_battle)):
        path = os.path.join(out_dir, cfg["name"] + ".wav")
        write_wav(path, to_pcm16(render(cfg), cfg["peak"]))
        results.append((cfg, path, analyse(path)))

    print("%-14s %9s %7s %7s %10s %12s" % ("name", "dur_s", "peak", "rms", "bytes", "seam_jump"))
    failed = False
    for cfg, path, info in results:
        print("%-14s %9.4f %7.4f %7.4f %10d %12.6f" % (
            cfg["name"], info["dur"], info["peak"], info["rms"], info["bytes"], info["jump"]))
        if abs(info["dur"] - cfg["seconds"]) > 0.05 or info["peak"] > 0.8:
            failed = True
            print("  CHECK FAILED: %s" % path)
    for cfg, path, _info in results:
        print(path)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
