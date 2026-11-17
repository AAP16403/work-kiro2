use std::collections::HashMap;
use std::fs::{self, File};
use std::io::BufReader;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use rand::Rng;
use rodio::buffer::SamplesBuffer;
use rodio::{Decoder, OutputStream, OutputStreamHandle, Sink, Source};

use crate::assets::resolve_asset;
use crate::sim::state::SimEvent;

pub const DEFAULT_MUSIC_VOLUME: f32 = 0.5;
pub const DEFAULT_SFX_VOLUME: f32 = 0.8;
pub const DEFAULT_MAX_VOICES: usize = 24;
const MIN_PITCH: f32 = 0.05;
const VOICE_MARGIN: Duration = Duration::from_millis(250);

/// (name, volume, pitch_jitter, min_gap_seconds) verbatim from Python `audio_cues.py`.
pub const CUE_SPECS: &[(&str, f32, f32, f32)] = &[
    ("ricochet", 0.55, 0.06, 0.05),
    ("homing_lock", 0.55, 0.00, 0.25),
    ("time_slow_on", 0.80, 0.00, 0.50),
    ("time_slow_off", 0.70, 0.00, 0.50),
    ("magnet", 0.60, 0.00, 0.30),
    ("drone_spawn", 0.60, 0.03, 0.50),
    ("drone_fire", 0.40, 0.05, 0.12),
    ("event_warn", 0.80, 0.00, 1.00),
    ("meteor_impact", 0.80, 0.05, 0.40),
    ("flare_sweep", 0.55, 0.00, 0.80),
    ("nebula_hum", 0.40, 0.00, 6.00),
    ("toast", 0.50, 0.00, 0.25),
    ("achievement", 0.80, 0.00, 0.50),
    ("daily_record", 0.80, 0.00, 1.00),
    ("reflect", 0.55, 0.06, 0.08),
    ("split", 0.60, 0.06, 0.30),
    ("rage_warn", 0.80, 0.00, 2.00),
    ("victory_fanfare", 0.85, 0.00, 2.00),
    ("skin_select", 0.50, 0.00, 0.10),
    ("mutator_toggle", 0.50, 0.00, 0.08),
    ("hangar_move", 0.40, 0.00, 0.06),
];

#[derive(Clone)]
struct DecodedClip {
    channels: u16,
    sample_rate: u32,
    samples: Arc<[f32]>,
    duration_s: f32,
}

impl DecodedClip {
    fn from_wav(path: &Path) -> Option<Self> {
        let file = File::open(path).ok()?;
        let decoder = Decoder::new(BufReader::new(file)).ok()?;
        let channels = decoder.channels().max(1);
        let sample_rate = decoder.sample_rate().max(8000);
        let samples: Vec<f32> = decoder.convert_samples::<f32>().collect();
        if samples.is_empty() {
            return None;
        }
        let duration_s = samples.len() as f32 / (channels as f32 * sample_rate as f32);
        Some(Self {
            channels,
            sample_rate,
            samples: Arc::from(samples.into_boxed_slice()),
            duration_s,
        })
    }

    fn source(&self) -> SamplesBuffer<f32> {
        SamplesBuffer::new(self.channels, self.sample_rate, self.samples.as_ref())
    }
}

#[derive(Default)]
struct SoundBank {
    sfx: HashMap<String, Option<DecodedClip>>,
    music: HashMap<String, Option<DecodedClip>>,
}

struct VoiceEntry {
    sink: Sink,
    expires: Instant,
}

struct MusicTrack {
    sink: Sink,
    gain: f32,
    target: f32,
    rate: f32,
}

fn clamp01(v: f32, default: f32) -> f32 {
    if !v.is_finite() {
        default
    } else {
        v.clamp(0.0, 1.0)
    }
}

fn approach(value: f32, target: f32, rate: f32, dt: f32) -> f32 {
    if rate <= 0.0 {
        return target;
    }
    let step = rate * dt;
    if value < target {
        (value + step).min(target)
    } else {
        (value - step).max(target)
    }
}

pub struct AudioManager {
    pub sfx_volume: f32,
    pub music_volume: f32,
    pub available: bool,
    pub max_voices: usize,

    _stream: Option<OutputStream>,
    stream_handle: Option<OutputStreamHandle>,
    audio_dir: Option<PathBuf>,
    bank: Arc<Mutex<SoundBank>>,

    voices: Vec<VoiceEntry>,
    last_played: HashMap<String, Instant>,
    tracks: Vec<MusicTrack>,
    pending_music: Option<(String, f32)>,
    current_music: Option<String>,
    duck_level: f32,
    duck_target: f32,
    duck_rate: f32,
    start_instant: Instant,
}

impl AudioManager {
    pub fn new(sfx_volume: f32, music_volume: f32) -> Self {
        Self::with_options(sfx_volume, music_volume, DEFAULT_MAX_VOICES, false)
    }

    pub fn new_silent(sfx_volume: f32, music_volume: f32) -> Self {
        Self::with_options(sfx_volume, music_volume, DEFAULT_MAX_VOICES, true)
    }

    pub fn with_options(
        sfx_volume: f32,
        music_volume: f32,
        max_voices: usize,
        force_silent: bool,
    ) -> Self {
        let audio_dir = resolve_asset("assets/audio");
        let bank = Arc::new(Mutex::new(SoundBank::default()));

        let (stream, handle, available) = if force_silent {
            (None, None, false)
        } else {
            match OutputStream::try_default() {
                Ok((s, h)) => (Some(s), Some(h), true),
                Err(_) => (None, None, false),
            }
        };

        if let Some(dir) = audio_dir.clone() {
            if available {
                let bank_clone = Arc::clone(&bank);
                std::thread::spawn(move || preload_all_audio(&dir, &bank_clone));
            }
        }

        Self {
            sfx_volume: clamp01(sfx_volume, DEFAULT_SFX_VOLUME),
            music_volume: clamp01(music_volume, DEFAULT_MUSIC_VOLUME),
            available,
            max_voices: max_voices.max(1),
            _stream: stream,
            stream_handle: handle,
            audio_dir,
            bank,
            voices: Vec::with_capacity(DEFAULT_MAX_VOICES),
            last_played: HashMap::new(),
            tracks: Vec::new(),
            pending_music: None,
            current_music: None,
            duck_level: 1.0,
            duck_target: 1.0,
            duck_rate: 0.0,
            start_instant: Instant::now(),
        }
    }

    pub fn set_volumes(&mut self, music: Option<f32>, sfx: Option<f32>) {
        if let Some(m) = music {
            self.music_volume = clamp01(m, self.music_volume);
        }
        if let Some(s) = sfx {
            self.sfx_volume = clamp01(s, self.sfx_volume);
        }
        self.apply_music_volumes();
    }

    pub fn duck(&mut self, factor: f32, fade: f32) {
        let f = fade.max(0.0);
        self.duck_target = clamp01(factor, 1.0);
        self.duck_rate = if f > 0.0 { 1.0 / f } else { 0.0 };
        if self.duck_rate <= 0.0 {
            self.duck_level = self.duck_target;
        }
        self.apply_music_volumes();
    }

    pub fn play(&mut self, name: &str, volume: f32, pitch_jitter: f32, min_gap: f32) {
        let gap = if min_gap.is_finite() && min_gap > 0.0 {
            min_gap
        } else {
            0.0
        };
        let now = Instant::now();
        if gap > 0.0 {
            if let Some(prev) = self.last_played.get(name) {
                if now.saturating_duration_since(*prev).as_secs_f32() < gap {
                    return;
                }
            }
        }

        if !self.available {
            if gap > 0.0 {
                self.last_played.insert(name.to_string(), now);
            }
            return;
        }

        let eff_vol = clamp01(self.sfx_volume * volume, 0.0);
        if eff_vol <= 0.0 {
            return;
        }

        self.prune_voices(now);
        if self.voices.len() >= self.max_voices {
            return;
        }

        let Some(clip) = self.get_or_load_sfx(name) else {
            return;
        };
        let Some(handle) = &self.stream_handle else {
            return;
        };
        let Ok(sink) = Sink::try_new(handle) else {
            return;
        };

        let jitter = if pitch_jitter.is_finite() {
            pitch_jitter.abs()
        } else {
            0.0
        };
        let pitch = if jitter > 0.0 {
            let mut rng = rand::thread_rng();
            (1.0 + rng.gen_range(-jitter..=jitter)).max(MIN_PITCH)
        } else {
            1.0
        };

        sink.set_volume(eff_vol);
        sink.set_speed(pitch);
        sink.append(clip.source());

        let dur = Duration::from_secs_f32((clip.duration_s / pitch).max(0.0));
        self.voices.push(VoiceEntry {
            sink,
            expires: now + dur + VOICE_MARGIN,
        });
        if gap > 0.0 {
            self.last_played.insert(name.to_string(), now);
        }
    }

    pub fn cue(&mut self, name: &str, scale: f32) {
        let Some(&(_, vol, jitter, min_gap)) = CUE_SPECS.iter().find(|&&(k, _, _, _)| k == name)
        else {
            return;
        };
        self.play(name, vol * scale, jitter, min_gap);
    }

    pub fn play_pickup(&mut self, kind: &str, rare: bool) {
        let clip = if rare { "pickup_rare" } else { "pickup" };
        self.play(clip, 0.7, 0.03, 0.0);
        match kind {
            "magnet" => self.cue("magnet", 1.0),
            "time_slow" => self.cue("time_slow_on", 1.0),
            _ => {}
        }
    }

    pub fn play_elite_death(&mut self, affix: &str) {
        if affix == "splitter" {
            self.cue("split", 1.0);
        }
    }

    pub fn play_music(&mut self, name: Option<&str>, fade: f32) {
        let Some(track_name) = name.filter(|s| !s.is_empty()) else {
            self.stop_music(fade);
            return;
        };
        if self.current_music.as_deref() == Some(track_name) {
            return;
        }
        if !self.available {
            self.current_music = Some(track_name.to_string());
            return;
        }
        let fade_s = if fade.is_finite() && fade > 0.0 { fade } else { 0.0 };
        if !self.start_music_track(track_name, fade_s) {
            self.pending_music = Some((track_name.to_string(), fade_s));
        } else {
            self.pending_music = None;
        }
    }

    pub fn stop_music(&mut self, fade: f32) {
        self.current_music = None;
        self.pending_music = None;
        let rate = if fade.is_finite() && fade > 0.0 {
            1.0 / fade
        } else {
            0.0
        };
        self.fade_out_tracks(rate);
    }

    pub fn update(&mut self, dt: f32) {
        if !self.available {
            return;
        }
        if let Some((name, fade_s)) = self.pending_music.clone() {
            if self.start_music_track(&name, fade_s) {
                self.pending_music = None;
            }
        }
        let step = if dt.is_finite() && dt > 0.0 { dt } else { 0.0 };
        self.prune_voices(Instant::now());

        let mut i = 0;
        while i < self.tracks.len() {
            if (self.tracks[i].gain - self.tracks[i].target).abs() > 1e-5 {
                let target = self.tracks[i].target;
                let rate = self.tracks[i].rate;
                self.tracks[i].gain = approach(self.tracks[i].gain, target, rate, step);
            }
            if self.tracks[i].target <= 0.0 && self.tracks[i].gain <= 0.0 {
                let tr = self.tracks.swap_remove(i);
                tr.sink.stop();
            } else {
                i += 1;
            }
        }
        if (self.duck_level - self.duck_target).abs() > 1e-5 {
            self.duck_level = approach(self.duck_level, self.duck_target, self.duck_rate, step);
        }
        self.apply_music_volumes();
    }

    /// Dispatch deterministic simulation events into audio playback cleanly.
    pub fn handle_sim_events(&mut self, events: &[SimEvent]) {
        for ev in events {
            match ev {
                SimEvent::Audio {
                    clip,
                    volume,
                    pitch_jitter,
                    min_gap,
                } => self.play(clip, *volume, *pitch_jitter, *min_gap),
                SimEvent::AudioCue(name) => self.cue(name, 1.0),
                _ => {}
            }
        }
    }

    pub fn active_voice_count(&self) -> usize {
        self.voices.len()
    }

    pub fn current_music_name(&self) -> Option<&str> {
        self.current_music.as_deref()
    }

    pub fn elapsed_s(&self) -> f32 {
        self.start_instant.elapsed().as_secs_f32()
    }

    fn start_music_track(&mut self, name: &str, fade_s: f32) -> bool {
        let clip = {
            let guard = self.bank.lock().ok();
            guard.and_then(|b| b.music.get(name).and_then(|c| c.clone()))
        }
        .or_else(|| self.try_sync_load_music(name));

        let Some(clip) = clip else {
            return false;
        };
        let Some(handle) = &self.stream_handle else {
            return false;
        };
        let Ok(sink) = Sink::try_new(handle) else {
            return false;
        };
        let rate = if fade_s > 0.0 { 1.0 / fade_s } else { 0.0 };
        let initial_gain = if rate > 0.0 { 0.0 } else { 1.0 };

        sink.set_volume(clamp01(self.music_volume * initial_gain * self.duck_level, 0.0));
        sink.append(clip.source().repeat_infinite());

        self.fade_out_tracks(rate);
        self.tracks.push(MusicTrack {
            sink,
            gain: initial_gain,
            target: 1.0,
            rate,
        });
        self.current_music = Some(name.to_string());
        self.apply_music_volumes();
        true
    }

    fn fade_out_tracks(&mut self, rate: f32) {
        if rate <= 0.0 {
            for tr in self.tracks.drain(..) {
                tr.sink.stop();
            }
            return;
        }
        for tr in &mut self.tracks {
            if tr.target > 0.0 {
                tr.target = 0.0;
                tr.rate = rate;
            }
        }
    }

    fn apply_music_volumes(&self) {
        for tr in &self.tracks {
            let vol = clamp01(self.music_volume * tr.gain * self.duck_level, 0.0);
            tr.sink.set_volume(vol);
        }
    }

    fn prune_voices(&mut self, now: Instant) {
        self.voices
            .retain(|v| !v.sink.empty() && now < v.expires);
    }

    fn get_or_load_sfx(&self, name: &str) -> Option<DecodedClip> {
        if let Ok(guard) = self.bank.lock() {
            if let Some(cached) = guard.sfx.get(name) {
                return cached.clone();
            }
        }
        let dir = self.audio_dir.as_ref()?;
        let path = dir.join(format!("sfx_{name}.wav"));
        let decoded = DecodedClip::from_wav(&path);
        if let Ok(mut guard) = self.bank.lock() {
            guard.sfx.insert(name.to_string(), decoded.clone());
        }
        decoded
    }

    fn try_sync_load_music(&self, name: &str) -> Option<DecodedClip> {
        let filename = match name {
            "menu" => "music_menu.wav",
            "battle" => "music_battle.wav",
            _ => return None,
        };
        let dir = self.audio_dir.as_ref()?;
        let path = dir.join(filename);
        let decoded = DecodedClip::from_wav(&path);
        if let Ok(mut guard) = self.bank.lock() {
            guard.music.insert(name.to_string(), decoded.clone());
        }
        decoded
    }
}

fn preload_all_audio(dir: &Path, bank: &Arc<Mutex<SoundBank>>) {
    // Load menu music first so title music can begin immediately.
    for (key, file) in [("menu", "music_menu.wav"), ("battle", "music_battle.wav")] {
        let decoded = DecodedClip::from_wav(&dir.join(file));
        if let Ok(mut guard) = bank.lock() {
            guard.music.entry(key.to_string()).or_insert(decoded);
        }
    }

    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    let mut paths: Vec<PathBuf> = entries
        .filter_map(|e| e.ok().map(|de| de.path()))
        .filter(|p| {
            p.file_name()
                .and_then(|n| n.to_str())
                .is_some_and(|n| n.starts_with("sfx_") && n.ends_with(".wav"))
        })
        .collect();
    paths.sort();

    for path in paths {
        let Some(stem) = path.file_stem().and_then(|s| s.to_str()) else {
            continue;
        };
        let key = stem.strip_prefix("sfx_").unwrap_or(stem).to_string();
        let already = bank
            .lock()
            .ok()
            .is_some_and(|b| b.sfx.contains_key(&key));
        if already {
            continue;
        }
        let decoded = DecodedClip::from_wav(&path);
        if let Ok(mut guard) = bank.lock() {
            guard.sfx.entry(key).or_insert(decoded);
        }
    }
}
