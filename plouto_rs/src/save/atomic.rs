use serde_json::{Map, Value};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use tempfile::Builder;

pub const VERSION_KEY: &str = "version";
pub const PROGRESS_VERSION: i64 = 1;
pub const USER_SETTINGS_VERSION: i64 = 1;
pub const HIGH_SCORES_VERSION: i64 = 1;

/// Atomically serialize and write a JSON object to `path` via a temp file + sync + rename.
pub fn atomic_write_json(path: &Path, data: &Map<String, Value>) -> bool {
    let serialized = match serde_json::to_string_pretty(&Value::Object(data.clone())) {
        Ok(s) => s,
        Err(_) => return false,
    };

    let abs = if path.is_absolute() {
        path.to_path_buf()
    } else {
        match std::env::current_dir() {
            Ok(cwd) => cwd.join(path),
            Err(_) => return false,
        }
    };
    let Some(parent) = abs.parent() else {
        return false;
    };
    if fs::create_dir_all(parent).is_err() {
        return false;
    }

    let stem = abs
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("save");
    let prefix = format!(".{stem}-");
    let mut tmp = match Builder::new()
        .prefix(&prefix)
        .suffix(".tmp")
        .tempfile_in(parent)
    {
        Ok(f) => f,
        Err(_) => return false,
    };

    if tmp.as_file_mut().write_all(serialized.as_bytes()).is_err() {
        return false;
    }
    if tmp.as_file_mut().write_all(b"\n").is_err() {
        return false;
    }
    if tmp.as_file_mut().flush().is_err() {
        return false;
    }
    if tmp.as_file_mut().sync_all().is_err() {
        return false;
    }

    tmp.persist(&abs).is_ok()
}

/// Rename a corrupt save file to `<path>.corrupt-<n>` (first free n). Never panics.
pub fn quarantine(path: &Path) -> Option<PathBuf> {
    if !path.exists() {
        return None;
    }
    let mut n = 1usize;
    let base = path.as_os_str().to_string_lossy();
    loop {
        let candidate = PathBuf::from(format!("{base}.corrupt-{n}"));
        if !candidate.exists() {
            if fs::rename(path, &candidate).is_ok() {
                return Some(candidate);
            }
            if fs::copy(path, &candidate).is_ok() {
                return Some(candidate);
            }
            return None;
        }
        n += 1;
    }
}

fn read_version(map: &Map<String, Value>) -> i64 {
    match map.get(VERSION_KEY) {
        Some(Value::Number(n)) => n.as_i64().filter(|&v| v >= 0).unwrap_or(0),
        _ => 0,
    }
}

fn with_version(mut map: Map<String, Value>, version: i64) -> Map<String, Value> {
    map.insert(VERSION_KEY.to_string(), Value::Number(version.into()));
    map
}

/// Load a versioned JSON object file, running `migrate(map, version)` or quarantining corrupt bytes.
pub fn load_versioned<M, D>(path: &Path, current: i64, migrate: M, default_map: D) -> Map<String, Value>
where
    M: FnOnce(Map<String, Value>, i64) -> Map<String, Value>,
    D: Fn() -> Map<String, Value>,
{
    let raw = match fs::read(path) {
        Ok(b) => b,
        Err(_) => return default_map(),
    };

    let Ok(text) = std::str::from_utf8(&raw) else {
        quarantine(path);
        return default_map();
    };
    let clean_text = text.strip_prefix('\u{FEFF}').unwrap_or(text);

    let parsed: Value = match serde_json::from_str(clean_text) {
        Ok(v) => v,
        Err(_) => {
            quarantine(path);
            return default_map();
        }
    };
    let Value::Object(obj) = parsed else {
        quarantine(path);
        return default_map();
    };

    let file_version = read_version(&obj);
    let migrated = migrate(obj, file_version);
    with_version(migrated, current.max(file_version))
}

/// Write `data` with version stamped (`>= current`, preserving higher future versions).
pub fn save_versioned(path: &Path, data: &Map<String, Value>, current: i64) -> bool {
    let existing = read_version(data);
    let stamp = current.max(existing);
    let stamped = with_version(data.clone(), stamp);
    atomic_write_json(path, &stamped)
}

/// Write `data` only if nothing exists at `path`. Never overwrites existing or corrupt files.
pub fn create_if_missing(path: &Path, data: &Map<String, Value>, current: i64) -> bool {
    if path.exists() {
        return false;
    }
    save_versioned(path, data, current)
}

/// Finite non-negative integer extraction compatible with Python's json number handling.
pub fn value_to_i64(v: &Value) -> Option<i64> {
    match v {
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Some(i)
            } else if let Some(u) = n.as_u64() {
                i64::try_from(u).ok()
            } else if let Some(f) = n.as_f64() {
                if f.is_finite() { Some(f as i64) } else { None }
            } else {
                None
            }
        }
        _ => None,
    }
}

pub fn value_to_bool(v: &Value, default: bool) -> bool {
    match v {
        Value::Bool(b) => *b,
        Value::Number(n) => match n.as_i64() {
            Some(0) => false,
            Some(1) => true,
            _ => default,
        },
        _ => default,
    }
}
