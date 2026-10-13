"""Sound effects and music for PLOUTO.

Assets are read from assets/audio/: sfx_<name>.wav for effects and
music_menu.wav / music_battle.wav for music. Missing files are skipped.
Every pyglet call is guarded so audio problems never reach the game loop.

Volume settings persist in user_settings.json (project root, or next to the
executable in a frozen build) under the keys "music_volume" and "sfx_volume".
"""

import atexit
import math
import multiprocessing
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor

from savefile import load_settings, update_settings


def _resource_path(*parts: str) -> str:
    """Resolve paths for both source and PyInstaller (_MEIPASS) runtime."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


_AUDIO_DIR = _resource_path("assets", "audio")
_MUSIC_FILES = {"menu": "music_menu.wav", "battle": "music_battle.wav"}

_DEFAULT_MUSIC_VOLUME = 0.5
_DEFAULT_SFX_VOLUME = 0.8
_DEFAULT_MAX_VOICES = 24
_MIN_PITCH = 0.05
# Extra time a voice may live past its expected end before it is force-released.
_VOICE_MARGIN = 0.25


def _settings_path() -> str:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "user_settings.json")


_SETTINGS_PATH = _settings_path()
_RNG = random.Random()
_warned_paths = set()


def _finite(value, default: float) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


def _clamp01(value, default: float) -> float:
    f = _finite(value, default)
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def _approach(value: float, target: float, rate: float, dt: float) -> float:
    """Move value toward target at rate (per second); rate <= 0 snaps."""
    if rate <= 0.0:
        return target
    step = rate * dt
    if value < target:
        return min(target, value + step)
    return max(target, value - step)


def _warn_missing(path: str) -> None:
    if path not in _warned_paths:
        _warned_paths.add(path)
        print(f"Warning: audio file missing: {path}")


def _safe_delete(player) -> None:
    try:
        player.delete()
    except Exception:
        pass


def _safe_stop_delete(player) -> None:
    try:
        player.pause()
    except Exception:
        pass
    _safe_delete(player)


class _MusicTrack:
    __slots__ = ("player", "gain", "target", "rate")

    def __init__(self, player, gain: float, target: float, rate: float) -> None:
        self.player = player
        self.gain = gain
        self.target = target
        self.rate = rate


_TOOL_SCRIPTS = frozenset({"bench.py", "playtest.py", "screens.py", "balance_sim.py"})


def _silent_requested() -> bool:
    """Tests and tool scripts use pyglet's silent driver, so no sound reaches the speakers.

    The AudioManager logic still runs (voices, min_gap, volumes), so the audio tests keep their
    coverage. PLOUTO_SILENT=1 forces the same for any run.
    """
    if os.environ.get("PLOUTO_SILENT", "0") not in ("", "0"):
        return True
    script = os.path.basename(sys.argv[0] or "")
    return script.startswith("test_") or script in _TOOL_SCRIPTS


class AudioManager:
    """Plays sound effects (voices) and crossfading looped music.

    Call update(dt) once per rendered frame. When `available` is False
    (pyglet audio driver failed to start, or only the silent driver is
    present), every method is a no-op.
    """

    def __init__(self, sfx_volume: float = 0.8, music_volume: float = 0.5, max_voices: int = 24) -> None:
        self.sfx_volume = _clamp01(sfx_volume, _DEFAULT_SFX_VOLUME)
        self.music_volume = _clamp01(music_volume, _DEFAULT_MUSIC_VOLUME)
        self.max_voices = max(1, int(_finite(max_voices, _DEFAULT_MAX_VOICES)))

        self.available = False
        self._media = None
        self._voices = []
        self._sfx_cache = {}
        self._music_cache = {}
        self._last_played = {}
        self._tracks = []
        self._music_name = None
        self._duck_level = 1.0
        self._duck_target = 1.0
        self._duck_rate = 0.0

        silent = _silent_requested()
        try:
            from pyglet import media

            if silent:
                import pyglet

                pyglet.options["audio"] = ("silent",)
            driver = media.get_audio_driver()
            # pyglet substitutes a silent driver when no real output opens. Silent mode keeps the
            # same code path on purpose: the logic runs, nothing is played.
            if driver is not None and (silent or "silent" not in type(driver).__module__):
                self._media = media
                self.available = True
        except Exception:
            self.available = False
            self._media = None

    # ----- sound effects -------------------------------------------------

    def play(self, name: str, volume: float = 1.0, pitch_jitter: float = 0.0, min_gap: float = 0.0) -> None:
        """Play sfx_<name>.wav. Dropped if at max_voices or within min_gap of the last play."""
        if not self.available:
            return
        try:
            gap = max(0.0, _finite(min_gap, 0.0))
            now = time.monotonic()
            if gap > 0.0:
                last = self._last_played.get(name)
                if last is not None and now - last < gap:
                    return

            effective = _clamp01(self.sfx_volume * _finite(volume, 1.0), 0.0)
            if effective <= 0.0:
                return

            if len(self._voices) >= self.max_voices:
                self._prune_voices()
                if len(self._voices) >= self.max_voices:
                    return

            source = self._load(self._sfx_cache, name, os.path.join(_AUDIO_DIR, f"sfx_{name}.wav"))
            if source is None:
                return

            jitter = abs(_finite(pitch_jitter, 0.0))
            pitch = 1.0
            if jitter > 0.0:
                pitch = max(_MIN_PITCH, 1.0 + _RNG.uniform(-jitter, jitter))

            player = source.play()
            player.volume = effective
            player.pitch = pitch
            length = max(0.0, _finite(getattr(source, "duration", 0.0), 0.0))
            self._voices.append((player, now + length / pitch + _VOICE_MARGIN))
            if gap > 0.0:
                self._last_played[name] = now
        except Exception:
            pass

    # ----- music ---------------------------------------------------------

    def play_music(self, name: str | None, fade: float = 0.8) -> None:
        """Crossfade to music "menu" or "battle". None or "" fades music out.

        Requesting the track already playing is a no-op. An unknown or
        missing track leaves the current music untouched.
        """
        if not self.available:
            return
        try:
            if not name:
                self.stop_music(fade)
                return
            if name == self._music_name:
                return
            source = self._music_source(name)
            if source is None:
                return

            fade = max(0.0, _finite(fade, 0.0))
            rate = 1.0 / fade if fade > 0.0 else 0.0

            player = self._media.Player()
            try:
                player.queue(source)
                player.loop = True
                player.volume = 0.0
                player.play()
            except Exception:
                _safe_stop_delete(player)
                return

            self._fade_out_tracks(rate)
            self._tracks.append(_MusicTrack(player, 0.0 if rate > 0.0 else 1.0, 1.0, rate))
            self._music_name = name
            self._apply_music_volumes()
        except Exception:
            pass

    def stop_music(self, fade: float = 0.8) -> None:
        if not self.available:
            return
        try:
            fade = max(0.0, _finite(fade, 0.0))
            self._music_name = None
            self._fade_out_tracks(1.0 / fade if fade > 0.0 else 0.0)
        except Exception:
            pass

    def duck(self, factor: float = 0.35, fade: float = 0.25) -> None:
        """Scale music volume toward factor over fade seconds. duck(1.0) restores."""
        if not self.available:
            return
        try:
            fade = max(0.0, _finite(fade, 0.0))
            self._duck_target = _clamp01(factor, 1.0)
            self._duck_rate = 1.0 / fade if fade > 0.0 else 0.0
            if self._duck_rate <= 0.0:
                self._duck_level = self._duck_target
            self._apply_music_volumes()
        except Exception:
            pass

    def set_volumes(self, music: float | None = None, sfx: float | None = None) -> None:
        """Set music and/or sfx volume (0..1, clamped). Music changes apply immediately."""
        if music is not None:
            self.music_volume = _clamp01(music, self.music_volume)
        if sfx is not None:
            self.sfx_volume = _clamp01(sfx, self.sfx_volume)
        if self.available:
            self._apply_music_volumes()

    def update(self, dt: float) -> None:
        """Advance fades and prune finished voices. Call once per rendered frame."""
        if not self.available:
            return
        try:
            step = max(0.0, _finite(dt, 0.0))
            self._prune_voices()
            for track in list(self._tracks):
                if track.gain != track.target:
                    track.gain = _approach(track.gain, track.target, track.rate, step)
                if track.target <= 0.0 and track.gain <= 0.0:
                    self._drop_track(track)
            if self._duck_level != self._duck_target:
                self._duck_level = _approach(self._duck_level, self._duck_target, self._duck_rate, step)
            self._apply_music_volumes()
        except Exception:
            pass

    # ----- internals -----------------------------------------------------

    def _load(self, cache: dict, key: str, path: str):
        """Load and cache a streaming=False source. Misses are remembered.

        A music file the startup preload decoded is taken from it (joining that job first). Any
        other file, and a preload that failed, is loaded here with media.load, as before.
        """
        if key in cache:
            return cache[key]
        source = None
        if not os.path.isfile(path):
            _warn_missing(path)
        else:
            source = _take_preloaded(path)
            if source is None:
                try:
                    source = self._media.load(path, streaming=False)
                except Exception:
                    source = None
        cache[key] = source
        return source

    def _music_source(self, name: str):
        filename = _MUSIC_FILES.get(name)
        if filename is None:
            return None
        return self._load(self._music_cache, name, os.path.join(_AUDIO_DIR, filename))

    def _fade_out_tracks(self, rate: float) -> None:
        for track in list(self._tracks):
            if track.target <= 0.0:
                continue
            if rate > 0.0:
                track.target = 0.0
                track.rate = rate
            else:
                self._drop_track(track)

    def _drop_track(self, track: _MusicTrack) -> None:
        try:
            self._tracks.remove(track)
        except ValueError:
            pass
        _safe_stop_delete(track.player)

    def _apply_music_volumes(self) -> None:
        for track in self._tracks:
            try:
                track.player.volume = _clamp01(
                    self.music_volume * track.gain * self._duck_level, 0.0
                )
            except Exception:
                pass

    def _prune_voices(self) -> None:
        """Release voices that finished. EOS is delivered through the pyglet app
        loop, so a voice also expires by its known length as a fallback."""
        now = time.monotonic()
        alive = []
        for player, expires in self._voices:
            try:
                is_playing = bool(player.playing)
            except Exception:
                is_playing = False
            if is_playing and now < expires:
                alive.append((player, expires))
            else:
                _safe_delete(player)
        self._voices = alive


# ----- startup preload -----------------------------------------------------
#
# start_preload() reads and decodes the menu music WAV in one spawn-context worker process while the
# game is still importing and building its window. The worker runs only stdlib ``wave`` code (no
# pyglet import). The pyglet source object is built on the main thread by _take_preloaded(), which
# joins the worker job. A worker failure returns None, and the caller then does the same
# media.load it did before, so a missing or unreadable file is handled as it was without preload.

# Off by default. Measured in wave 4: starting the worker costs the main thread about 30 ms, while the
# decode it moves is about 3 ms, so the default startup is not made faster. See test_w4_loading.py.
PRELOAD_STARTUP_MUSIC = False
_JOIN_TIMEOUT_S = 10.0
_preload_pool = None
_preload = {}  # path -> Future of _decode_wav_worker(path)
_atexit_registered = False


def _decode_wav_worker(path: str):
    """Worker entry point: read a WAV file's PCM frames with the stdlib wave module.

    Returns (channels, sample_size_bits, sample_rate, pcm_bytes), or None for any file that
    pyglet's WAV decoder would refuse. None sends the caller to the synchronous load.
    """
    try:
        import wave

        with wave.open(path, "rb") as wav:
            channels, sampwidth, framerate, nframes, _comptype, _compname = wav.getparams()
            if channels not in (1, 2) or sampwidth not in (1, 2):
                return None
            data = wav.readframes(nframes)
        return (channels, sampwidth * 8, framerate, data)
    except Exception:
        return None


def _static_source_from_pcm(channels: int, sample_size: int, sample_rate: int, data: bytes):
    """Build the pyglet StaticSource that media.load returns for the same decoded PCM.

    StaticSource.__init__ only decodes; its result is the three fields set here.
    """
    from pyglet.media.codecs.base import AudioFormat, StaticSource

    audio_format = AudioFormat(channels=channels, sample_size=sample_size, sample_rate=sample_rate)
    source = StaticSource.__new__(StaticSource)
    source.audio_format = audio_format
    source._data = data
    source._duration = len(data) / audio_format.bytes_per_second
    return source


def start_preload() -> bool:
    """Start the background decode of the menu music WAV. Call once at startup, under the entry guard.

    Returns True when the worker was started. Never raises; on failure every load stays synchronous.
    Does nothing (returns False) while PRELOAD_STARTUP_MUSIC is off.
    """
    global _preload_pool, _atexit_registered
    if not PRELOAD_STARTUP_MUSIC:
        return False
    if _preload_pool is not None:
        return True
    paths = [os.path.join(_AUDIO_DIR, _MUSIC_FILES["menu"])]  # the menu's music is the only one needed at startup
    paths = [p for p in paths if os.path.isfile(p)]  # a missing file is reported on first load, as before
    if not paths:
        return False
    pool = None
    try:
        pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        futures = {p: pool.submit(_decode_wav_worker, p) for p in paths}
    except Exception:
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)
        return False
    _preload_pool = pool
    _preload.update(futures)
    if not _atexit_registered:
        atexit.register(shutdown_preload)
        _atexit_registered = True
    return True


def shutdown_preload() -> None:
    """Stop the preload worker. Safe to call again; also runs at interpreter exit."""
    global _preload_pool
    pool = _preload_pool
    _preload_pool = None
    _preload.clear()
    if pool is not None:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


def _take_preloaded(path: str):
    """Return the pyglet source decoded for path by the preload, or None.

    None means nothing was preloaded for path, or its job failed or timed out. The caller then
    loads the file synchronously. Once the last job is taken, the worker is shut down.
    """
    future = _preload.pop(path, None)
    source = None
    if future is not None:
        try:
            pcm = future.result(timeout=_JOIN_TIMEOUT_S)
            if pcm is not None:
                source = _static_source_from_pcm(*pcm)
        except Exception:
            source = None
    if not _preload:
        shutdown_preload()
    return source


# ----- settings persistence ----------------------------------------------

def _coerce_volume(value, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return _clamp01(value, default)


def load_audio_settings() -> tuple[float, float]:
    """Return (music, sfx) volumes from user_settings.json. Never raises."""
    music, sfx = _DEFAULT_MUSIC_VOLUME, _DEFAULT_SFX_VOLUME
    try:
        data = load_settings(_SETTINGS_PATH)
        music = _coerce_volume(data.get("music_volume"), music)
        sfx = _coerce_volume(data.get("sfx_volume"), sfx)
    except Exception:
        pass
    return music, sfx


def save_audio_settings(music: float, sfx: float) -> None:
    """Write music/sfx volumes to user_settings.json, keeping other keys. Never raises."""
    try:
        update_settings(_SETTINGS_PATH, {
            "music_volume": _coerce_volume(music, _DEFAULT_MUSIC_VOLUME),
            "sfx_volume": _coerce_volume(sfx, _DEFAULT_SFX_VOLUME),
        })
    except Exception:
        pass
