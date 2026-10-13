"""Wave 4 "loading" tests: the optional startup preload of the menu music (audio.start_preload).

Covers: the worker's decode equals pyglet's synchronous load for every shipped WAV; the loader's result
through the join path, through a failed job and through the game's own menu music equals the synchronous
load; a missing or unreadable file is handled as it was before; the preload is off by default; the
worker process ends with the app; the entry script starts the preload under its __main__ guard.

Run from the project root:  .venv\\Scripts\\python.exe test_w4_loading.py
Each test prints a [PASS] line. The Game-level test opens a hidden window, as the other suites do.
"""

import ast
import contextlib
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from concurrent.futures import Future

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import audio  # noqa: E402
import pyglet  # noqa: E402
import pyglet.media  # noqa: E402

AUDIO_DIR = audio._AUDIO_DIR
MENU_WAV = os.path.join(AUDIO_DIR, "music_menu.wav")
_WORKER_EXIT_S = 20.0


@contextlib.contextmanager
def _preload_flag(value: bool):
    """Set PRELOAD_STARTUP_MUSIC for a block and stop any worker it started."""
    saved = audio.PRELOAD_STARTUP_MUSIC
    audio.PRELOAD_STARTUP_MUSIC = value
    try:
        yield
    finally:
        audio.shutdown_preload()
        audio.PRELOAD_STARTUP_MUSIC = saved


class _CountingMedia:
    """Stands in for pyglet.media and counts synchronous load calls."""

    def __init__(self, real):
        self._real = real
        self.loads = 0

    def load(self, *args, **kwargs):
        self.loads += 1
        return self._real.load(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _manager():
    """An AudioManager whose loader is usable even where no audio device opened."""
    am = audio.AudioManager()
    if am._media is None:
        am._media = pyglet.media
    return am


def _sync_source(path):
    return pyglet.media.load(path, streaming=False)


def _same_source(a, b) -> bool:
    """True when two pyglet StaticSource objects hold the same format, bytes and duration."""
    if a is None or b is None:
        return a is b
    fa, fb = a.audio_format, b.audio_format
    same_format = (fa.channels, fa.sample_size, fa.sample_rate, fa.bytes_per_second) == (
        fb.channels, fb.sample_size, fb.sample_rate, fb.bytes_per_second)
    return same_format and a._data == b._data and a.duration == b.duration


def _load_captured(am, key: str, path: str):
    """Run the manager's loader with a fresh missing-file memory and return (source, printed text)."""
    audio._warned_paths.discard(path)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        source = am._load({}, key, path)
    return source, buf.getvalue()


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        still_active = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_default_is_off_and_start_does_nothing():
    assert audio.PRELOAD_STARTUP_MUSIC is False, "the preload must ship switched off"
    assert audio.start_preload() is False
    assert audio._preload_pool is None and not audio._preload
    print("[PASS] test_default_is_off_and_start_does_nothing passed (flag off, no worker, no futures)")


def test_worker_decode_matches_sync_load_for_every_shipped_wav():
    paths = sorted(glob.glob(os.path.join(AUDIO_DIR, "*.wav")))
    assert paths, "no shipped WAV files found"
    for path in paths:
        pcm = audio._decode_wav_worker(path)
        assert pcm is not None, f"worker refused a shipped file: {path}"
        built = audio._static_source_from_pcm(*pcm)
        assert _same_source(built, _sync_source(path)), f"worker decode differs from media.load: {path}"
    print(f"[PASS] test_worker_decode_matches_sync_load_for_every_shipped_wav passed ({len(paths)} files identical)")


def test_preloaded_menu_music_equals_sync_load_and_skips_media_load():
    with _preload_flag(True):
        assert audio.start_preload() is True
        assert MENU_WAV in audio._preload, "menu music was not queued on the worker"
        am = _manager()
        counting = _CountingMedia(am._media)
        am._media = counting
        source = am._load({}, "menu", MENU_WAV)  # joins the worker job
        assert counting.loads == 0, "menu music was decoded on the main thread anyway"
        assert _same_source(source, _sync_source(MENU_WAV)), "preloaded menu music differs from media.load"
        assert MENU_WAV not in audio._preload
    print("[PASS] test_preloaded_menu_music_equals_sync_load_and_skips_media_load passed "
          "(joined result identical, zero main-thread decodes)")


def test_game_menu_music_comes_from_preload_and_matches_sync():
    from game import Game

    with _preload_flag(True):
        assert audio.start_preload() is True
        g = Game()  # MenuState.enter plays the menu music, which joins the preload job
        try:
            if not g.audio.available:
                print("[SKIP requires-audio-device] test_game_menu_music_comes_from_preload_and_matches_sync")
                return
            cached = g.audio._music_cache.get("menu")
            assert cached is not None, "menu music was not loaded at startup"
            assert _same_source(cached, _sync_source(MENU_WAV)), "startup menu music differs from media.load"
            assert audio._preload_pool is None, "worker still running after its last job was taken"
        finally:
            g.set_visible(False)
            g.close()
    print("[PASS] test_game_menu_music_comes_from_preload_and_matches_sync passed "
          "(startup menu music identical, worker gone before the first frame)")


def test_missing_file_is_reported_as_before():
    tmp = tempfile.mkdtemp(prefix="w4_empty_")
    saved_dir = audio._AUDIO_DIR
    try:
        # With the preload on and the menu music absent, the worker is not started and the load warns as before.
        audio._AUDIO_DIR = tmp
        missing_menu = os.path.join(tmp, "music_menu.wav")
        missing_sfx = os.path.join(AUDIO_DIR, "sfx_no_such_sound_w4.wav")
        expected = "Warning: audio file missing: %s\n"
        with _preload_flag(True):
            assert audio.start_preload() is False, "a worker was started for a file that is not there"
            am = _manager()
            src_on, out_on = _load_captured(am, "menu", missing_menu)
        with _preload_flag(False):
            am = _manager()
            src_off, out_off = _load_captured(am, "menu", missing_menu)
        assert src_on is None and src_off is None
        assert out_on == out_off == expected % missing_menu, f"warning text changed: {out_on!r} / {out_off!r}"
    finally:
        audio._AUDIO_DIR = saved_dir
        shutil.rmtree(tmp, ignore_errors=True)

    with _preload_flag(True):
        audio.start_preload()
        am = _manager()
        src_on, out_on = _load_captured(am, "sfx", missing_sfx)
    with _preload_flag(False):
        am = _manager()
        src_off, out_off = _load_captured(am, "sfx", missing_sfx)
    assert src_on is None and src_off is None
    assert out_on == out_off == expected % missing_sfx, f"warning text changed: {out_on!r} / {out_off!r}"
    print("[PASS] test_missing_file_is_reported_as_before passed (same single warning, same None, with and without preload)")


def test_unreadable_files_load_the_same_with_and_without_preload():
    tmp = tempfile.mkdtemp(prefix="w4_bad_")
    try:
        garbage = os.path.join(tmp, "garbage.wav")
        with open(garbage, "wb") as fh:
            fh.write(b"this is not a RIFF file at all")
        wide = os.path.join(tmp, "wide24.wav")
        with wave.open(wide, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(3)
            w.setframerate(22050)
            w.writeframes(b"\x00\x00\x00" * 100)

        assert audio._decode_wav_worker(garbage) is None
        assert audio._decode_wav_worker(wide) is None, "24-bit PCM must be refused like pyglet refuses it"
        results = {}
        for path in (garbage, wide):
            with _preload_flag(False):
                results[(path, "off")] = _load_captured(_manager(), "x", path)
            with _preload_flag(True):
                audio.start_preload()  # real worker, but this path is not in its queue
                results[(path, "on")] = _load_captured(_manager(), "x", path)
        for path in (garbage, wide):
            off_src, off_out = results[(path, "off")]
            on_src, on_out = results[(path, "on")]
            assert (on_src is None) == (off_src is None), f"source presence differs for {path}"
            assert on_out == off_out, f"printed output differs for {path}: {on_out!r} vs {off_out!r}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("[PASS] test_unreadable_files_load_the_same_with_and_without_preload passed "
          "(garbage and 24-bit files: same result and output)")


def test_failed_job_falls_back_to_synchronous_load():
    for outcome in ("none", "exception"):
        with _preload_flag(False):  # no real worker: the queued future is set by hand
            fut = Future()
            if outcome == "none":
                fut.set_result(None)
            else:
                fut.set_exception(RuntimeError("worker died"))
            audio._preload[MENU_WAV] = fut
            am = _manager()
            counting = _CountingMedia(am._media)
            am._media = counting
            source = am._load({}, "menu", MENU_WAV)
            assert counting.loads == 1, f"a {outcome} job did not fall back to media.load"
            assert _same_source(source, _sync_source(MENU_WAV))
            assert MENU_WAV not in audio._preload
    print("[PASS] test_failed_job_falls_back_to_synchronous_load passed (None result and raised error both load synchronously)")


def test_start_failure_leaves_every_load_synchronous():
    real = audio.ProcessPoolExecutor

    def broken(*args, **kwargs):
        raise OSError("no worker processes available")

    audio.ProcessPoolExecutor = broken
    try:
        with _preload_flag(True):
            assert audio.start_preload() is False
            assert audio._preload_pool is None and not audio._preload
            am = _manager()
            source = am._load({}, "menu", MENU_WAV)
            assert _same_source(source, _sync_source(MENU_WAV))
    finally:
        audio.ProcessPoolExecutor = real
    print("[PASS] test_start_failure_leaves_every_load_synchronous passed (pool creation error is swallowed)")


def test_shutdown_stops_the_worker_and_is_repeatable():
    with _preload_flag(True):
        assert audio.start_preload() is True
        procs = list(audio._preload_pool._processes.values())
        assert procs, "no worker process was started"
        audio.shutdown_preload()
        audio.shutdown_preload()  # second call is a no-op
        for proc in procs:
            proc.join(_WORKER_EXIT_S)
        assert all(not proc.is_alive() for proc in procs), "worker still alive after shutdown"
        assert audio._preload_pool is None and not audio._preload
    print(f"[PASS] test_shutdown_stops_the_worker_and_is_repeatable passed ({len(procs)} worker, exited, repeat safe)")


def test_worker_process_ends_with_the_app():
    # A child interpreter starts the preload and exits without taking the job. The exit hook must stop the
    # worker, so the child returns on its own and no worker process is left behind.
    code = (
        "import json, audio\n"
        "audio.PRELOAD_STARTUP_MUSIC = True\n"
        "assert audio.start_preload() is True\n"
        "pids = [p.pid for p in audio._preload_pool._processes.values()]\n"
        "print(json.dumps(pids), flush=True)\n"
    )
    started = time.monotonic()
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    elapsed = time.monotonic() - started
    assert proc.returncode == 0, f"child failed: {proc.stderr[-1500:]}"
    pids = json.loads([ln for ln in proc.stdout.splitlines() if ln.startswith("[")][-1])
    assert pids, "child started no worker"
    deadline = time.monotonic() + _WORKER_EXIT_S
    alive = list(pids)
    while alive and time.monotonic() < deadline:
        alive = [pid for pid in alive if _pid_alive(pid)]
        if alive:
            time.sleep(0.1)
    assert not alive, f"worker processes outlived the app: {alive}"
    print(f"[PASS] test_worker_process_ends_with_the_app passed (child exited in {elapsed:.1f} s, "
          f"{len(pids)} worker gone)")


def test_entry_script_starts_preload_under_main_guard():
    with open(os.path.join(ROOT, "main.py"), encoding="utf-8-sig") as fh:
        tree = ast.parse(fh.read())
    guard = None
    for node in tree.body:
        if isinstance(node, ast.If) and "__main__" in ast.dump(node.test):
            guard = node
    assert guard is not None, "main.py has no __main__ guard"
    calls = [n for n in ast.walk(guard) if isinstance(n, ast.Call)]
    names = [ast.unparse(c.func) for c in calls]
    assert "audio.start_preload" in names, "main.py does not start the preload under its guard"
    assert names.index("audio.start_preload") < names.index("game_main"), "preload must start before the game runs"
    print("[PASS] test_entry_script_starts_preload_under_main_guard passed (main.py starts it before game_main())")


def run_all():
    tests = (
        test_default_is_off_and_start_does_nothing,
        test_worker_decode_matches_sync_load_for_every_shipped_wav,
        test_preloaded_menu_music_equals_sync_load_and_skips_media_load,
        test_game_menu_music_comes_from_preload_and_matches_sync,
        test_missing_file_is_reported_as_before,
        test_unreadable_files_load_the_same_with_and_without_preload,
        test_failed_job_falls_back_to_synchronous_load,
        test_start_failure_leaves_every_load_synchronous,
        test_shutdown_stops_the_worker_and_is_repeatable,
        test_worker_process_ends_with_the_app,
        test_entry_script_starts_preload_under_main_guard,
    )
    for test in tests:
        test()
    print("\nALL WAVE 4 LOADING TESTS PASSED")


if __name__ == "__main__":
    run_all()
