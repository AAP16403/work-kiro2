use serde_json::{Map, Value};
use std::collections::BTreeMap;
use std::path::Path;

use crate::save::atomic::{
    load_versioned, save_versioned, value_to_bool, value_to_i64, USER_SETTINGS_VERSION,
    VERSION_KEY,
};
use crate::sim::config::{
    normalize_shake_level, shake_scale_for_level, RuntimeConfig, ARENA_MARGIN_DEFAULT,
    ARENA_MARGIN_MAX, ARENA_MARGIN_MIN,
};
use crate::sim::mutators::normalize_selection;

pub const DEFAULT_MUSIC_VOLUME: f32 = 0.5;
pub const DEFAULT_SFX_VOLUME: f32 = 0.8;
pub const DEFAULT_GAMEPAD_DEADZONE: f32 = 0.18;
pub const GAMEPAD_DEADZONE_MIN: f32 = 0.05;
pub const GAMEPAD_DEADZONE_MAX: f32 = 0.5;

#[derive(Debug, Clone)]
pub struct UserSettings {
    pub version: i64,
    pub music_volume: f32,
    pub sfx_volume: f32,
    pub shake_level: String,
    pub reduced_motion: bool,
    pub colorblind_palette: bool,
    pub high_contrast_hud: bool,
    pub difficulty: String,
    pub map_type: String,
    pub arena_margin: f32,
    pub auto_shoot: bool,
    pub fullscreen: bool,
    pub display_size: Option<(u32, u32)>,
    pub mutators: Vec<String>,
    pub gamepad_enabled: bool,
    pub gamepad_vibration: bool,
    pub gamepad_deadzone: f32,
    pub extra: BTreeMap<String, Value>,
}

impl Default for UserSettings {
    fn default() -> Self {
        Self {
            version: USER_SETTINGS_VERSION,
            music_volume: DEFAULT_MUSIC_VOLUME,
            sfx_volume: DEFAULT_SFX_VOLUME,
            shake_level: "full".to_string(),
            reduced_motion: false,
            colorblind_palette: false,
            high_contrast_hud: false,
            difficulty: "normal".to_string(),
            map_type: "circle".to_string(),
            arena_margin: ARENA_MARGIN_DEFAULT,
            auto_shoot: true,
            fullscreen: false,
            display_size: None,
            mutators: Vec::new(),
            gamepad_enabled: true,
            gamepad_vibration: true,
            gamepad_deadzone: DEFAULT_GAMEPAD_DEADZONE,
            extra: BTreeMap::new(),
        }
    }
}

impl UserSettings {
    pub fn apply_to_runtime(&self, runtime: &mut RuntimeConfig) {
        runtime.reduce_motion = self.reduced_motion;
        runtime.colorblind_palette = self.colorblind_palette;
        runtime.high_contrast_hud = self.high_contrast_hud;
        runtime.enable_obstacles = false;
        runtime.shake_scale = shake_scale_for_level(&self.shake_level);
        runtime.arena_margin = self.arena_margin.clamp(ARENA_MARGIN_MIN, ARENA_MARGIN_MAX);
    }
}

fn clamp01(v: Option<&Value>, default: f32) -> f32 {
    let Some(Value::Number(n)) = v else {
        return default;
    };
    let Some(f) = n.as_f64() else {
        return default;
    };
    if !f.is_finite() {
        return default;
    }
    (f as f32).clamp(0.0, 1.0)
}

fn migrate_user_settings(mut map: Map<String, Value>, _version: i64) -> Map<String, Value> {
    if !matches!(map.get("shake_level"), Some(Value::String(_))) {
        if let Some(legacy) = map.get("reduced_shake").and_then(|v| v.as_bool()) {
            let lvl = if legacy { "reduced" } else { "full" };
            map.insert("shake_level".to_string(), Value::String(lvl.to_string()));
        }
    }
    map
}

pub fn load_settings(path: &Path) -> UserSettings {
    let map = load_versioned(path, USER_SETTINGS_VERSION, migrate_user_settings, Map::new);
    let mut s = UserSettings::default();
    if let Some(v) = map.get(VERSION_KEY).and_then(value_to_i64) {
        s.version = v.max(USER_SETTINGS_VERSION);
    }
    s.music_volume = clamp01(map.get("music_volume"), DEFAULT_MUSIC_VOLUME);
    s.sfx_volume = clamp01(map.get("sfx_volume"), DEFAULT_SFX_VOLUME);
    if let Some(Value::String(lvl)) = map.get("shake_level") {
        s.shake_level = normalize_shake_level(lvl).to_string();
    } else if let Some(legacy) = map.get("reduced_shake").and_then(|v| v.as_bool()) {
        s.shake_level = if legacy { "reduced" } else { "full" }.to_string();
    }
    if let Some(v) = map.get("reduced_motion") {
        s.reduced_motion = value_to_bool(v, false);
    }
    if let Some(v) = map.get("colorblind_palette") {
        s.colorblind_palette = value_to_bool(v, false);
    }
    if let Some(v) = map.get("high_contrast_hud") {
        s.high_contrast_hud = value_to_bool(v, false);
    }
    if let Some(Value::String(d)) = map.get("difficulty") {
        let dl = d.trim().to_ascii_lowercase();
        if matches!(dl.as_str(), "easy" | "normal" | "hard") {
            s.difficulty = dl;
        }
    }
    if let Some(Value::String(m)) = map.get("map_type") {
        let ml = m.trim().to_ascii_lowercase();
        if matches!(ml.as_str(), "circle" | "donut" | "cross" | "diamond") {
            s.map_type = ml;
        }
    }
    if let Some(Value::Number(n)) = map.get("arena_margin") {
        if let Some(f) = n.as_f64().filter(|f| f.is_finite()) {
            s.arena_margin = (f as f32).clamp(ARENA_MARGIN_MIN, ARENA_MARGIN_MAX);
        }
    }
    if let Some(v) = map.get("auto_shoot") {
        s.auto_shoot = value_to_bool(v, true);
    }
    if let Some(v) = map.get("fullscreen") {
        s.fullscreen = value_to_bool(v, false);
    }
    if let Some(v) = map.get("gamepad_enabled") {
        s.gamepad_enabled = value_to_bool(v, true);
    }
    if let Some(v) = map.get("gamepad_vibration") {
        s.gamepad_vibration = value_to_bool(v, true);
    }
    if let Some(Value::Number(n)) = map.get("gamepad_deadzone") {
        if let Some(f) = n.as_f64().filter(|f| f.is_finite()) {
            s.gamepad_deadzone = (f as f32).clamp(GAMEPAD_DEADZONE_MIN, GAMEPAD_DEADZONE_MAX);
        }
    }
    if let Some(Value::Array(arr)) = map.get("display_size") {
        if arr.len() == 2 {
            if let (Some(w), Some(h)) = (value_to_i64(&arr[0]), value_to_i64(&arr[1])) {
                if w >= 640 && h >= 480 {
                    s.display_size = Some((w as u32, h as u32));
                }
            }
        }
    }
    if let Some(Value::Array(arr)) = map.get("mutators") {
        let raw_ids: Vec<&str> = arr.iter().filter_map(|v| v.as_str()).collect();
        s.mutators = normalize_selection(raw_ids);
    }

    let known = [
        VERSION_KEY,
        "music_volume",
        "sfx_volume",
        "shake_level",
        "reduced_shake",
        "reduced_motion",
        "colorblind_palette",
        "high_contrast_hud",
        "difficulty",
        "map_type",
        // Recognize and discard the removed setting so old files cannot re-enable cover.
        "enable_obstacles",
        "arena_margin",
        "auto_shoot",
        "fullscreen",
        "display_size",
        "mutators",
        "gamepad_enabled",
        "gamepad_vibration",
        "gamepad_deadzone",
    ];
    for (k, v) in map {
        if !known.contains(&k.as_str()) {
            s.extra.insert(k, v);
        }
    }
    s
}

/// Merge & save settings back atomically while keeping unknown keys and Python-compatible fields.
pub fn save_settings(path: &Path, settings: &UserSettings) -> bool {
    let mut map = load_versioned(path, USER_SETTINGS_VERSION, migrate_user_settings, Map::new);
    map.remove("enable_obstacles");
    for (k, v) in &settings.extra {
        map.insert(k.clone(), v.clone());
    }
    let shake = normalize_shake_level(&settings.shake_level);
    map.insert(
        VERSION_KEY.to_string(),
        Value::Number(settings.version.max(USER_SETTINGS_VERSION).into()),
    );
    map.insert(
        "music_volume".to_string(),
        serde_json::json!(settings.music_volume.clamp(0.0, 1.0)),
    );
    map.insert(
        "sfx_volume".to_string(),
        serde_json::json!(settings.sfx_volume.clamp(0.0, 1.0)),
    );
    map.insert("shake_level".to_string(), Value::String(shake.to_string()));
    map.insert("reduced_shake".to_string(), Value::Bool(shake != "full"));
    map.insert(
        "reduced_motion".to_string(),
        Value::Bool(settings.reduced_motion),
    );
    map.insert(
        "colorblind_palette".to_string(),
        Value::Bool(settings.colorblind_palette),
    );
    map.insert(
        "high_contrast_hud".to_string(),
        Value::Bool(settings.high_contrast_hud),
    );
    map.insert(
        "difficulty".to_string(),
        Value::String(settings.difficulty.clone()),
    );
    map.insert("map_type".to_string(), Value::String(settings.map_type.clone()));
    map.insert(
        "arena_margin".to_string(),
        serde_json::json!(settings.arena_margin.clamp(ARENA_MARGIN_MIN, ARENA_MARGIN_MAX)),
    );
    map.insert("auto_shoot".to_string(), Value::Bool(settings.auto_shoot));
    map.insert("fullscreen".to_string(), Value::Bool(settings.fullscreen));
    if let Some((w, h)) = settings.display_size {
        map.insert("display_size".to_string(), serde_json::json!([w, h]));
    }
    map.insert("gamepad_enabled".to_string(), Value::Bool(settings.gamepad_enabled));
    map.insert(
        "gamepad_vibration".to_string(),
        Value::Bool(settings.gamepad_vibration),
    );
    // A non-finite deadzone would serialise as null; write the default instead.
    let deadzone = if settings.gamepad_deadzone.is_finite() {
        settings
            .gamepad_deadzone
            .clamp(GAMEPAD_DEADZONE_MIN, GAMEPAD_DEADZONE_MAX)
    } else {
        DEFAULT_GAMEPAD_DEADZONE
    };
    map.insert("gamepad_deadzone".to_string(), serde_json::json!(deadzone));
    map.insert("mutators".to_string(), serde_json::json!(settings.mutators));
    save_versioned(path, &map, USER_SETTINGS_VERSION)
}

/// Apply arbitrary JSON changes onto `user_settings.json`, preserving every other key.
pub fn update_settings_keys(path: &Path, changes: &[(String, Value)]) -> bool {
    let mut map = load_versioned(path, USER_SETTINGS_VERSION, migrate_user_settings, Map::new);
    for (k, v) in changes {
        map.insert(k.clone(), v.clone());
    }
    save_versioned(path, &map, USER_SETTINGS_VERSION)
}
