"""Deterministic checks for the wave-3 sound design (audiov3).

Covers the 21 new synth recipes (format, peak, edges, determinism across two processes,
match with the committed WAVs), the cue table, an AST scan of every sound name the code
plays, the pickup and elite-death hooks in the real game, and AudioManager's voice budget
with min_gap. Cross-wave call sites that need the wave 1 or wave 2 modules print
[SKIP requires-wave1] or [SKIP requires-wave2] while those modules are absent.
"""

import ast
import contextlib
import hashlib
import importlib.util
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import audio as audio_mod  # noqa: E402
import audio_cues  # noqa: E402
from enemy import Enemy  # noqa: E402
from game import Game  # noqa: E402
from powerup import PowerUp  # noqa: E402
from states import GameStateName, PlayingState  # noqa: E402
from utils import Vec2  # noqa: E402

NEW_SOUNDS = (
    "ricochet", "homing_lock", "time_slow_on", "time_slow_off", "magnet", "drone_spawn",
    "drone_fire", "event_warn", "meteor_impact", "flare_sweep", "nebula_hum", "toast",
    "achievement", "daily_record", "reflect", "split", "rage_warn", "victory_fanfare",
    "skin_select", "mutator_toggle", "hangar_move",
)
# Cues whose owning feature lives in wave 1 or wave 2 (contract in scratchpad/goal/contracts.md).
WAVE1_CUES = ("ricochet", "homing_lock", "time_slow_off", "achievement", "skin_select",
              "mutator_toggle", "hangar_move")
WAVE2_CUES = ("drone_spawn", "drone_fire", "event_warn", "meteor_impact", "flare_sweep",
              "nebula_hum", "toast", "daily_record", "reflect", "rage_warn")
UNOWNED_CUES = ("victory_fanfare",)

SR = 22050
PCM_FULL = 32767
MAX_PEAK = 0.75
_SKIP_DIRS = {"vercel_site", "tools", "build", "dist", ".venv", ".claude", "__pycache__", "android"}


def _wav_path(name):
    return os.path.join(ROOT, "assets", "audio", "sfx_%s.wav" % name)


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _load_synth():
    spec = importlib.util.spec_from_file_location("synth_sfx", os.path.join(ROOT, "tools", "synth_sfx.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_samples(path):
    with wave.open(path, "rb") as w:
        n = w.getnframes()
        fmt = (w.getnchannels(), w.getsampwidth(), w.getframerate())
        samples = struct.unpack("<%dh" % n, w.readframes(n))
    return fmt, samples


def _project_sources():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in filenames:
            if fname.endswith(".py") and not fname.startswith("test_"):
                yield os.path.join(dirpath, fname)


def _parse(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return ast.parse(fh.read(), path)


def _string_constants(node):
    """String constants inside a call argument, skipping getattr() lookups (attribute names, not sounds)."""
    out = []

    def walk(n):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "getattr":
            return
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value:
            out.append(n.value)
        for child in ast.iter_child_nodes(n):
            walk(child)

    walk(node)
    return out


def _sound_names_in_code():
    """Every sound name passed to .play(), cue(), or held in a module-level *_SFX / *_CUES dict."""
    names = {}
    for path in _project_sources():
        tree = _parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_sound_play = (isinstance(func, ast.Attribute) and func.attr == "play" and bool(node.args)
                             and "audio" in ast.unparse(func.value).lower())
            if is_sound_play:
                for name in _string_constants(node.args[0]):
                    names.setdefault(name, os.path.basename(path))
            is_cue = (isinstance(func, ast.Attribute) and func.attr == "cue") or (
                isinstance(func, ast.Name) and func.id == "cue")
            if is_cue and len(node.args) >= 2:
                for name in _string_constants(node.args[1]):
                    names.setdefault(name, os.path.basename(path))
        for node in tree.body:
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.endswith(("_SFX", "_CUES")):
                    for value in node.value.values:
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            names.setdefault(value.value, os.path.basename(path))
    return names


def _cue_call_sites():
    """Names given to cue() in project code outside audio_cues.py."""
    found = set()
    for path in _project_sources():
        if os.path.basename(path) == "audio_cues.py":
            continue
        for node in ast.walk(_parse(path)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_cue = (isinstance(func, ast.Attribute) and func.attr == "cue") or (
                isinstance(func, ast.Name) and func.id == "cue")
            if is_cue and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                found.add(node.args[1].value)
    return found


# ----- recording and fake audio -------------------------------------------

class _RecordAudio:
    """Stands in for AudioManager and records every play call."""

    def __init__(self):
        self.calls = []

    def play(self, name, volume=1.0, pitch_jitter=0.0, min_gap=0.0):
        self.calls.append((name, volume, pitch_jitter, min_gap))

    def play_music(self, *args, **kwargs):
        pass

    def stop_music(self, *args, **kwargs):
        pass

    def duck(self, *args, **kwargs):
        pass

    def set_volumes(self, *args, **kwargs):
        pass

    def update(self, dt):
        pass

    def names(self):
        return [c[0] for c in self.calls]


class _BrokenAudio:
    def play(self, *args, **kwargs):
        raise RuntimeError("driver gone")


class _FakeMedia:
    def __init__(self):
        self.plays = []

    def load(self, path, streaming=False):
        return _FakeSource(self, os.path.basename(path))


class _FakeSource:
    def __init__(self, media, label, duration=0.5):
        self.media = media
        self.label = label
        self.duration = duration

    def play(self):
        self.media.plays.append(self.label)
        return _FakePlayer()


class _FakePlayer:
    def __init__(self):
        self.volume = 1.0
        self.pitch = 1.0
        self.playing = True

    def delete(self):
        self.playing = False

    def pause(self):
        self.playing = False


class _FakeClock:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t


@contextlib.contextmanager
def _fake_time(clock):
    saved = audio_mod.time
    audio_mod.time = clock
    try:
        yield
    finally:
        audio_mod.time = saved


def _fake_manager(max_voices=24):
    am = audio_mod.AudioManager(max_voices=max_voices)
    am.available = True
    am._media = _FakeMedia()
    return am


# ----- synth output -----------------------------------------------------------

def test_registry_holds_every_new_sound_once():
    synth = _load_synth()
    registry = [name for name, _, _, _ in synth.SOUNDS]
    assert len(registry) == len(set(registry)), "duplicate sound name in the synth registry"
    missing = [n for n in NEW_SOUNDS if n not in registry]
    assert not missing, f"sounds not registered in tools/synth_sfx.py: {missing}"
    print(f"[PASS] test_registry_holds_every_new_sound_once passed ({len(NEW_SOUNDS)} new, {len(registry)} total)")


def test_new_wavs_are_22k_mono_16bit_and_peak_capped():
    rows = []
    for name in NEW_SOUNDS:
        path = _wav_path(name)
        assert os.path.isfile(path), f"missing WAV for {name}: {path}"
        fmt, samples = _read_samples(path)
        assert fmt == (1, 2, SR), f"{name} format is {fmt}, expected mono 16-bit {SR} Hz"
        peak = max(abs(v) for v in samples) / float(PCM_FULL)
        assert 0.0 < peak <= MAX_PEAK + 1e-9, f"{name} peak {peak:.3f} outside (0, {MAX_PEAK}]"
        # No step at the file boundaries: percussive transients may start hard, but the first
        # sample must sit near zero and the final samples must have faded out.
        first = abs(samples[0]) / float(PCM_FULL) / peak
        tail = max(abs(v) for v in samples[-8:]) / float(PCM_FULL)
        assert first <= 0.10 and tail <= 0.02, f"{name} has a step at a boundary (first {first:.3f}, tail {tail:.3f})"
        rows.append((name, len(samples) / float(SR), peak))
    longest = max(rows, key=lambda r: r[1])
    print(f"[PASS] test_new_wavs_are_22k_mono_16bit_and_peak_capped passed ({len(rows)} files, "
          f"peak max {max(r[2] for r in rows):.3f}, longest {longest[0]} {longest[1]:.2f}s)")


def test_synth_output_is_deterministic_across_processes():
    synth_src = os.path.join(ROOT, "tools", "synth_sfx.py")
    runs = []
    for _ in range(2):
        work = tempfile.mkdtemp(prefix="w3sfx_")
        os.makedirs(os.path.join(work, "tools"))
        shutil.copy(synth_src, os.path.join(work, "tools", "synth_sfx.py"))
        proc = subprocess.run([sys.executable, os.path.join(work, "tools", "synth_sfx.py")],
                              capture_output=True, text=True, timeout=600)
        assert proc.returncode == 0, f"synth_sfx.py failed: {proc.stderr}"
        runs.append({n: _sha(os.path.join(work, "assets", "audio", "sfx_%s.wav" % n)) for n in
                     [name for name, _, _, _ in _load_synth().SOUNDS]})
    assert runs[0] == runs[1], "two runs of synth_sfx.py produced different bytes"
    committed = {n: _sha(_wav_path(n)) for n in runs[0]}
    diff = [n for n in runs[0] if runs[0][n] != committed[n]]
    assert not diff, f"synth output differs from the committed WAVs: {diff}"
    print(f"[PASS] test_synth_output_is_deterministic_across_processes passed "
          f"({len(runs[0])} files, two separate runs match, all match the committed WAVs)")


# ----- cue table and call sites ---------------------------------------------

def test_cue_table_covers_exactly_the_new_sounds():
    assert set(audio_cues.CUE_SPECS) == set(NEW_SOUNDS), "CUE_SPECS must list exactly the new sounds"
    for name, (volume, jitter, gap) in audio_cues.CUE_SPECS.items():
        assert 0.0 < volume <= 1.0, f"{name} volume {volume} out of range"
        assert 0.0 <= jitter <= 0.1, f"{name} pitch jitter {jitter} out of range"
        assert gap >= 0.0, f"{name} min_gap {gap} is negative"
    for table in (audio_cues.POWERUP_CUES, audio_cues.ELITE_DEATH_CUES):
        for value in table.values():
            assert value in audio_cues.CUE_SPECS, f"{value} is not a cue"
    print(f"[PASS] test_cue_table_covers_exactly_the_new_sounds passed ({len(NEW_SOUNDS)} cues with volume, jitter and min_gap)")


def test_every_sound_name_in_code_has_a_wav():
    names = _sound_names_in_code()
    missing = {n: where for n, where in names.items() if not os.path.isfile(_wav_path(n))}
    assert not missing, f"sound names used in code without a WAV: {missing}"
    print(f"[PASS] test_every_sound_name_in_code_has_a_wav passed ({len(names)} names found in code, all present)")


def test_repeated_cues_respect_min_gap():
    am = _fake_manager()
    clock = _FakeClock()
    with _fake_time(clock):
        for step in range(180):  # three seconds of drone fire, requested at 60 Hz
            clock.t = step / 60.0
            audio_cues.cue(am, "drone_fire")
            am.update(1.0 / 60.0)
        accepted = len(am._media.plays)
    limit = int(3.0 / audio_cues.CUE_SPECS["drone_fire"][2]) + 1
    assert 15 <= accepted <= limit, f"drone_fire accepted {accepted} plays in 3 s, expected 15..{limit}"
    print(f"[PASS] test_repeated_cues_respect_min_gap passed (drone_fire: {accepted} plays in 3 s, limit {limit})")


def test_all_cues_fit_the_voice_budget():
    am = _fake_manager(max_voices=24)
    clock = _FakeClock()
    with _fake_time(clock):
        for name in NEW_SOUNDS:
            audio_cues.cue(am, name)
        first_round = len(am._media.plays)
        for name in NEW_SOUNDS:  # the same burst again, a few milliseconds later
            clock.t = 0.01
            audio_cues.cue(am, name)
        total = len(am._media.plays)
        assert first_round == len(NEW_SOUNDS), f"first burst accepted {first_round} of {len(NEW_SOUNDS)}"
        assert total == len(NEW_SOUNDS), f"repeat burst inside min_gap was not dropped: {total} plays"
        assert total <= am.max_voices, f"{total} plays exceed max_voices {am.max_voices}"
    am2 = _fake_manager(max_voices=24)
    with _fake_time(_FakeClock()):
        for _ in range(40):  # same instant, no min_gap: the existing voice cap must hold
            am2.play("hit", min_gap=0.0)
        assert len(am2._media.plays) == 24, f"voice cap not enforced: {len(am2._media.plays)} voices"
    print(f"[PASS] test_all_cues_fit_the_voice_budget passed (21-cue burst accepted {first_round}, "
          f"repeat dropped, raw voice cap holds at {am2.max_voices})")


def test_nebula_hum_is_spaced_by_its_long_gap():
    am = _fake_manager()
    clock = _FakeClock()
    with _fake_time(clock):
        for step in range(10):
            clock.t = 0.5 * step
            audio_cues.cue(am, "nebula_hum")
        accepted = len(am._media.plays)
    assert accepted == 1, f"nebula_hum accepted {accepted} times within 5 s"
    print("[PASS] test_nebula_hum_is_spaced_by_its_long_gap passed (10 triggers in 5 s, 1 played)")


def test_cue_helper_is_silent_on_bad_input():
    rec = _RecordAudio()
    audio_cues.cue(None, "drone_fire")
    audio_cues.cue(rec, "not_a_cue")
    audio_cues.cue(_BrokenAudio(), "drone_fire")
    assert rec.calls == [], f"unexpected plays for unknown or None input: {rec.calls}"
    audio_cues.cue(rec, "drone_fire", scale=0.5)
    name, volume, jitter, gap = rec.calls[-1]
    assert name == "drone_fire" and abs(volume - 0.2) < 1e-9 and jitter == 0.05 and gap == 0.12, rec.calls[-1]
    print("[PASS] test_cue_helper_is_silent_on_bad_input passed (None, unknown name and raising driver are no-ops)")


# ----- game hooks ----------------------------------------------------------

def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _tick(g, frames=1):
    for _ in range(frames):
        g.dispatch_events()
        g.update(1.0 / 60.0)


def test_pickup_hook_plays_cue_for_new_kinds(g):
    s = _new_run(g)
    rec = _RecordAudio()
    g.audio = rec
    expected = (("magnet", "magnet"), ("time_slow", "time_slow_on"), ("heal", "pickup"), ("ultra", "pickup_rare"))
    for kind, sound in expected:
        rec.calls.clear()
        s.powerups = [PowerUp(pos=Vec2(g.player.pos.x, g.player.pos.y), kind=kind)]
        _tick(g)
        assert s.powerups == [], f"{kind} pickup was not collected"
        assert sound in rec.names(), f"{kind} pickup played {rec.names()}, expected {sound}"
    print("[PASS] test_pickup_hook_plays_cue_for_new_kinds passed "
          "(magnet and time_slow have their own cue; heal and ultra keep pickup and pickup_rare)")


def test_splitter_death_plays_split_and_others_do_not(g):
    s = _new_run(g)
    rec = _RecordAudio()
    g.audio = rec
    cases = (("splitter", True), ("volatile", False), ("", False))
    for affix, want_split in cases:
        rec.calls.clear()
        e = Enemy(pos=Vec2(200.0, 0.0), hp=0, speed=0.0, behavior="swarm",
                  is_elite=bool(affix), elite_affix=affix)
        s.enemies = [e]
        PlayingState._kill_enemy(g, s, e)
        got = "split" in rec.names()
        assert got == want_split, f"affix {affix!r}: split played={got}, expected {want_split} ({rec.names()})"
    print("[PASS] test_splitter_death_plays_split_and_others_do_not passed "
          "(splitter plays split; volatile and plain enemies do not)")


def test_every_cue_key_is_played_by_a_call_site():
    # A CUE_SPECS key counts as played only if a call site reaches it: a literal cue(audio, "name") in project
    # code, or one of the two tables that a call site drives (POWERUP_CUES through play_pickup, and
    # ELITE_DEATH_CUES through play_elite_death). Anything else is a sound that never plays.
    sites = _cue_call_sites()
    table_played = set(audio_cues.POWERUP_CUES.values()) | set(audio_cues.ELITE_DEATH_CUES.values())
    unplayed = sorted(set(audio_cues.CUE_SPECS) - sites - table_played)
    assert not unplayed, f"CUE_SPECS keys that no call site plays: {unplayed}"
    print(f"[PASS] test_every_cue_key_is_played_by_a_call_site passed "
          f"({len(audio_cues.CUE_SPECS)} cue keys, all reached by a call site)")


def test_owner_call_sites_for_waves_1_and_2():
    # Every cue of the new sound set must be played by a real event site. A missing hook fails the build;
    # it is never reported as a skip, because a skipped hook is a sound that never plays.
    sites = _cue_call_sites()
    missing = [name for name in WAVE1_CUES + WAVE2_CUES + UNOWNED_CUES if name not in sites]
    assert not missing, f"cues with no audio_cues.cue(audio, \"<name>\") call in project code: {missing}"
    print(f"[PASS] test_owner_call_sites_for_waves_1_and_2 passed "
          f"({len(WAVE1_CUES) + len(WAVE2_CUES) + len(UNOWNED_CUES)} cues each have a call site)")


def run_all():
    pure = (
        test_registry_holds_every_new_sound_once,
        test_new_wavs_are_22k_mono_16bit_and_peak_capped,
        test_synth_output_is_deterministic_across_processes,
        test_cue_table_covers_exactly_the_new_sounds,
        test_every_sound_name_in_code_has_a_wav,
        test_repeated_cues_respect_min_gap,
        test_all_cues_fit_the_voice_budget,
        test_nebula_hum_is_spaced_by_its_long_gap,
        test_cue_helper_is_silent_on_bad_input,
        test_every_cue_key_is_played_by_a_call_site,
    )
    for test in pure:
        test()
    g = Game()
    g.set_visible(False)
    try:
        test_pickup_hook_plays_cue_for_new_kinds(g)
        test_splitter_death_plays_split_and_others_do_not(g)
    finally:
        g.close()
    test_owner_call_sites_for_waves_1_and_2()
    print("\nALL WAVE 3 AUDIOV3 TESTS PASSED")


if __name__ == "__main__":
    run_all()
