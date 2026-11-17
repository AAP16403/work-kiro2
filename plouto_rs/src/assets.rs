use std::path::{Path, PathBuf};

/// Locate an asset file or directory (such as `assets/audio`, `assets/fonts/Orbitron-Bold.ttf`,
/// or `assets/laser-gun_38685.ico`) across CWD, workspace root, or executable ancestor directories.
pub fn resolve_asset(rel: &str) -> Option<PathBuf> {
    let mut bases: Vec<PathBuf> = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        for anc in cwd.ancestors().take(4) {
            bases.push(anc.to_path_buf());
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            for anc in dir.ancestors().take(5) {
                bases.push(anc.to_path_buf());
            }
        }
    }
    for base in bases {
        let candidate = base.join(rel);
        if candidate.exists() {
            return Some(candidate);
        }
    }
    None
}

fn repository_root_from(start: &Path) -> Option<PathBuf> {
    start.ancestors().take(6).find_map(|ancestor| {
        (ancestor.join("Cargo.toml").is_file()
            && ancestor.join("plouto_rs").is_dir()
            && ancestor.join("assets").is_dir())
        .then(|| ancestor.to_path_buf())
    })
}

fn user_data_directory() -> Option<PathBuf> {
    if let Some(path) = std::env::var_os("PLOUTO_DATA_DIR").filter(|value| !value.is_empty()) {
        return Some(PathBuf::from(path));
    }

    #[cfg(target_os = "windows")]
    {
        if let Some(base) = std::env::var_os("LOCALAPPDATA").filter(|value| !value.is_empty()) {
            return Some(PathBuf::from(base).join("Plouto"));
        }
    }

    #[cfg(target_os = "macos")]
    {
        if let Some(home) = std::env::var_os("HOME").filter(|value| !value.is_empty()) {
            return Some(PathBuf::from(home).join("Library/Application Support/Plouto"));
        }
    }

    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        if let Some(base) = std::env::var_os("XDG_DATA_HOME").filter(|value| !value.is_empty()) {
            return Some(PathBuf::from(base).join("plouto"));
        }
        if let Some(home) = std::env::var_os("HOME").filter(|value| !value.is_empty()) {
            return Some(PathBuf::from(home).join(".local/share/plouto"));
        }
    }

    None
}

fn legacy_data_directories() -> Vec<PathBuf> {
    let mut bases = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        bases.extend(cwd.ancestors().take(4).filter(|path| path.join("assets").is_dir()).map(Path::to_path_buf));
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            bases.extend(dir.ancestors().take(6).filter(|path| path.join("assets").is_dir()).map(Path::to_path_buf));
        }
    }
    let mut unique = Vec::with_capacity(bases.len());
    for base in bases {
        if !unique.contains(&base) {
            unique.push(base);
        }
    }
    unique
}

fn migrate_legacy_data_file(destination: &Path, filename: &str) {
    if destination.exists() {
        return;
    }
    let Some(parent) = destination.parent() else {
        return;
    };
    if std::fs::create_dir_all(parent).is_err() {
        return;
    }
    for legacy_dir in legacy_data_directories() {
        let legacy = legacy_dir.join(filename);
        if legacy == destination || !legacy.is_file() {
            continue;
        }
        let Ok(temp) = tempfile::Builder::new().prefix(".plouto-migrate-").tempfile_in(parent) else {
            return;
        };
        if std::fs::copy(&legacy, temp.path()).is_ok() && temp.persist(destination).is_ok() {
            break;
        }
    }
}

/// Resolve writable profile files. Development checkouts stay beside their Rust workspace;
/// installed builds use the operating system's user-data folder and copy legacy portable
/// profiles forward once. Set `PLOUTO_PORTABLE=1` to keep the profile beside the executable,
/// or `PLOUTO_DATA_DIR` to select an explicit writable location.
pub fn resolve_data_file(filename: &str) -> PathBuf {
    if let Some(data_dir) = std::env::var_os("PLOUTO_DATA_DIR").filter(|value| !value.is_empty()) {
        let destination = PathBuf::from(data_dir).join(filename);
        migrate_legacy_data_file(&destination, filename);
        return destination;
    }

    if std::env::var_os("PLOUTO_PORTABLE").is_some_and(|value| value == "1") {
        if let Ok(exe) = std::env::current_exe() {
            if let Some(dir) = exe.parent() {
                let destination = dir.join(filename);
                migrate_legacy_data_file(&destination, filename);
                return destination;
            }
        }
    }

    if cfg!(debug_assertions) {
        let development_root = std::env::current_dir()
            .ok()
            .and_then(|cwd| repository_root_from(&cwd))
            .or_else(|| {
                std::env::current_exe()
                    .ok()
                    .and_then(|exe| exe.parent().and_then(repository_root_from))
            });
        if let Some(root) = development_root {
            return root.join(filename);
        }
    }

    if let Some(data_dir) = user_data_directory() {
        let destination = data_dir.join(filename);
        migrate_legacy_data_file(&destination, filename);
        return destination;
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            return dir.join(filename);
        }
    }
    Path::new(filename).to_path_buf()
}
