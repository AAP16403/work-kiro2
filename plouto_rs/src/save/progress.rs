use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

use crate::save::atomic::{
    create_if_missing, load_versioned, save_versioned, value_to_i64, PROGRESS_VERSION, VERSION_KEY,
};
use crate::sim::achievements::{
    can_regress, check_condition, AchTotals, RunStats, ACHIEVEMENTS, ARENA_SHAPES, BOSS_KINDS,
};
use crate::sim::daily::{challenge_for_date, normalise_date, DailyResult};
use crate::sim::mutators::normalize_selection;
use crate::sim::replay::SIMULATION_RULES_VERSION;
use crate::sim::skins::{DEFAULT_SKIN_ID, SKINS, UnlockRule};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DailyEntry {
    pub score: i32,
    pub wave: i32,
    pub seed: Option<u64>,
    pub mutators: Vec<String>,
    pub rules_version: Option<u32>,
    pub history: Vec<DailyRecord>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DailyRecord {
    pub score: i32,
    pub wave: i32,
    pub seed: Option<u64>,
    pub mutators: Vec<String>,
    pub rules_version: Option<u32>,
}

#[derive(Debug, Clone)]
pub struct ProgressData {
    pub version: i64,
    pub best_wave: i32,
    pub best_score: i32,
    pub total_kills: i32,
    pub bosses_defeated: i32,
    pub runs_played: i32,
    pub unlocked_skins: Vec<String>,
    pub achievements: Vec<String>,
    pub selected_skin: String,
    pub daily: BTreeMap<String, DailyEntry>,
    /// Daily challenge runs settled (lifetime).
    pub daily_runs: i32,
    /// Boss behavior names killed at least once (subset of `BOSS_KINDS`).
    pub bosses_seen: Vec<String>,
    /// Arena shapes with at least one cleared wave (subset of `ARENA_SHAPES`).
    pub arenas_cleared: Vec<String>,
    pub extra: BTreeMap<String, Value>,
}

/// Settlement inputs that come from outside the simulation's `RunStats`.
/// Pass the same context to `end_run` and `evaluate_live`.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RunContext {
    /// Calendar date (ISO) of a daily challenge run. `None` for a normal run.
    pub daily_date: Option<String>,
    /// Names of the mutators active in the run. Only the count is used by achievements.
    /// An empty list leaves `RunStats::mutator_count` as the simulation set it.
    pub mutators: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct EndRunSummary {
    /// False when the write failed or `progress.json` was unreadable (nothing was written).
    /// The toasts should be held or replaced with a warning when this is false.
    pub saved: bool,
    pub progress: ProgressData,
    pub new_achievements: Vec<&'static str>,
    pub new_skins: Vec<&'static str>,
    /// Daily record outcome when the run was a daily challenge run.
    pub daily: Option<DailyResult>,
}

impl Default for ProgressData {
    fn default() -> Self {
        default_progress()
    }
}

/// Keys this module reads into typed fields. Everything else is kept in `extra`.
const KNOWN_KEYS: &[&str] = &[
    VERSION_KEY,
    "best_wave",
    "best_score",
    "total_kills",
    "bosses_defeated",
    "runs_played",
    "unlocked_skins",
    "achievements",
    "selected_skin",
    "daily",
    "daily_runs",
    "bosses_seen",
    "arenas_cleared",
];

pub fn default_progress() -> ProgressData {
    ProgressData {
        version: PROGRESS_VERSION,
        best_wave: 0,
        best_score: 0,
        total_kills: 0,
        bosses_defeated: 0,
        runs_played: 0,
        unlocked_skins: Vec::new(),
        achievements: Vec::new(),
        selected_skin: DEFAULT_SKIN_ID.to_string(),
        daily: BTreeMap::new(),
        daily_runs: 0,
        bosses_seen: Vec::new(),
        arenas_cleared: Vec::new(),
        extra: BTreeMap::new(),
    }
}

fn default_progress_map() -> Map<String, Value> {
    to_json_map(&default_progress())
}

fn coerce_non_neg_i32(map: &Map<String, Value>, key: &str, default: i32) -> i32 {
    match map.get(key).and_then(value_to_i64) {
        Some(v) if v >= 0 => v.min(i32::MAX as i64) as i32,
        _ => default,
    }
}

fn coerce_id_list(map: &Map<String, Value>, key: &str) -> Vec<String> {
    let Some(Value::Array(items)) = map.get(key) else {
        return Vec::new();
    };
    let mut seen = Vec::new();
    for item in items {
        if let Value::String(s) = item {
            if !s.is_empty() && !seen.contains(s) {
                seen.push(s.clone());
            }
        }
    }
    seen
}

/// Like `coerce_id_list`, but keeps only names in `known`. Unknown names are dropped so the
/// lifetime counts (`bosses_seen.len()`, `arenas_cleared.len()`) only count real entries.
fn coerce_known_names(map: &Map<String, Value>, key: &str, known: &[&str]) -> Vec<String> {
    coerce_id_list(map, key)
        .into_iter()
        .filter(|s| known.contains(&s.as_str()))
        .collect()
}

fn parse_daily(map: &Map<String, Value>) -> BTreeMap<String, DailyEntry> {
    let mut out = BTreeMap::new();
    let Some(Value::Object(table)) = map.get("daily") else {
        return out;
    };
    for (k, v) in table {
        let Ok(date_key) = normalise_date(k) else {
            continue;
        };
        let Value::Object(entry) = v else {
            continue;
        };
        let Some(record) = parse_daily_record(entry) else {
            continue;
        };
        let history = entry
            .get("history")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|value| value.as_object().and_then(parse_daily_record))
            .collect();
        out.insert(
            date_key,
            DailyEntry {
                score: record.score,
                wave: record.wave,
                seed: record.seed,
                mutators: record.mutators,
                rules_version: record.rules_version,
                history,
            },
        );
    }
    out
}

fn parse_daily_record(entry: &Map<String, Value>) -> Option<DailyRecord> {
    let score = entry.get("score").and_then(value_to_i64)?;
    let wave = entry.get("wave").and_then(value_to_i64).unwrap_or(0);
    let seed = entry
        .get("seed")
        .and_then(Value::as_u64);
    let mutators = entry
        .get("mutators")
        .and_then(Value::as_array)
        .map(|items| {
            normalize_selection(items.iter().filter_map(Value::as_str))
        })
        .unwrap_or_default();
    let rules_version = entry
        .get("rules_version")
        .and_then(value_to_i64)
        .and_then(|version| u32::try_from(version).ok());
    Some(DailyRecord {
        score: score.clamp(0, i32::MAX as i64) as i32,
        wave: wave.clamp(0, i32::MAX as i64) as i32,
        seed,
        mutators,
        rules_version,
    })
}

fn from_json_map(map: Map<String, Value>) -> ProgressData {
    let def = default_progress();
    let version = map
        .get(VERSION_KEY)
        .and_then(value_to_i64)
        .filter(|&v| v >= PROGRESS_VERSION)
        .unwrap_or(PROGRESS_VERSION);

    let selected_skin = match map.get("selected_skin") {
        Some(Value::String(s)) if !s.is_empty() => s.clone(),
        _ => def.selected_skin,
    };

    let daily = parse_daily(&map);

    let mut extra = BTreeMap::new();
    for (k, v) in &map {
        if !KNOWN_KEYS.contains(&k.as_str()) {
            extra.insert(k.clone(), v.clone());
        }
    }

    ProgressData {
        version,
        best_wave: coerce_non_neg_i32(&map, "best_wave", 0),
        best_score: coerce_non_neg_i32(&map, "best_score", 0),
        total_kills: coerce_non_neg_i32(&map, "total_kills", 0),
        bosses_defeated: coerce_non_neg_i32(&map, "bosses_defeated", 0),
        runs_played: coerce_non_neg_i32(&map, "runs_played", 0),
        unlocked_skins: coerce_id_list(&map, "unlocked_skins"),
        achievements: coerce_id_list(&map, "achievements"),
        selected_skin,
        daily,
        daily_runs: coerce_non_neg_i32(&map, "daily_runs", 0),
        bosses_seen: coerce_known_names(&map, "bosses_seen", BOSS_KINDS),
        arenas_cleared: coerce_known_names(&map, "arenas_cleared", ARENA_SHAPES),
        extra,
    }
}

fn to_json_map(data: &ProgressData) -> Map<String, Value> {
    let mut map = Map::new();
    for (k, v) in &data.extra {
        map.insert(k.clone(), v.clone());
    }
    map.insert(
        VERSION_KEY.to_string(),
        Value::Number(data.version.max(PROGRESS_VERSION).into()),
    );
    map.insert("best_wave".to_string(), Value::Number(data.best_wave.max(0).into()));
    map.insert("best_score".to_string(), Value::Number(data.best_score.max(0).into()));
    map.insert("total_kills".to_string(), Value::Number(data.total_kills.max(0).into()));
    map.insert(
        "bosses_defeated".to_string(),
        Value::Number(data.bosses_defeated.max(0).into()),
    );
    map.insert("runs_played".to_string(), Value::Number(data.runs_played.max(0).into()));
    map.insert("daily_runs".to_string(), Value::Number(data.daily_runs.max(0).into()));
    map.insert(
        "bosses_seen".to_string(),
        Value::Array(data.bosses_seen.iter().map(|s| Value::String(s.clone())).collect()),
    );
    map.insert(
        "arenas_cleared".to_string(),
        Value::Array(data.arenas_cleared.iter().map(|s| Value::String(s.clone())).collect()),
    );
    map.insert(
        "unlocked_skins".to_string(),
        Value::Array(
            data.unlocked_skins
                .iter()
                .map(|s| Value::String(s.clone()))
                .collect(),
        ),
    );
    map.insert(
        "achievements".to_string(),
        Value::Array(
            data.achievements
                .iter()
                .map(|s| Value::String(s.clone()))
                .collect(),
        ),
    );
    map.insert(
        "selected_skin".to_string(),
        Value::String(if data.selected_skin.is_empty() {
            DEFAULT_SKIN_ID.to_string()
        } else {
            data.selected_skin.clone()
        }),
    );
    if !data.daily.is_empty() {
        let mut dmap = Map::new();
        for (date, entry) in &data.daily {
            let mut em = daily_record_to_json(&DailyRecord {
                score: entry.score,
                wave: entry.wave,
                seed: entry.seed,
                mutators: entry.mutators.clone(),
                rules_version: entry.rules_version,
            });
            if !entry.history.is_empty() {
                em.insert(
                    "history".to_string(),
                    Value::Array(entry.history.iter().map(daily_record_to_json).map(Value::Object).collect()),
                );
            }
            dmap.insert(date.clone(), Value::Object(em));
        }
        map.insert("daily".to_string(), Value::Object(dmap));
    }
    map
}

fn daily_record_to_json(record: &DailyRecord) -> Map<String, Value> {
    let mut map = Map::new();
    map.insert("score".to_string(), Value::Number(record.score.max(0).into()));
    map.insert("wave".to_string(), Value::Number(record.wave.max(0).into()));
    if let Some(seed) = record.seed {
        map.insert("seed".to_string(), Value::Number(seed.into()));
    }
    if !record.mutators.is_empty() {
        map.insert(
            "mutators".to_string(),
            Value::Array(record.mutators.iter().cloned().map(Value::String).collect()),
        );
    }
    if let Some(version) = record.rules_version {
        map.insert("rules_version".to_string(), Value::Number(version.into()));
    }
    map
}

/// Load `progress.json` cleanly, quarantining corrupt JSON and preserving forward/unknown keys.
/// A missing or unreadable file yields defaults. Use `end_run` to settle a run, since it will not
/// overwrite an unreadable file.
pub fn load_progress(path: &Path) -> ProgressData {
    let map = load_versioned(path, PROGRESS_VERSION, |m, _| m, default_progress_map);
    from_json_map(map)
}

/// Atomically save `progress.json` into an existing directory. Returns `false` if dir missing.
pub fn save_progress(path: &Path, data: &ProgressData) -> bool {
    let Some(parent) = path.parent() else {
        return false;
    };
    if !parent.as_os_str().is_empty() && !parent.is_dir() {
        return false;
    }
    let map = to_json_map(data);
    save_versioned(path, &map, PROGRESS_VERSION)
}

/// Create `progress.json` with default values when absent. Never overwrites existing files.
pub fn ensure_progress_file(path: &Path) -> bool {
    let Some(parent) = path.parent() else {
        return false;
    };
    if !parent.as_os_str().is_empty() && !parent.is_dir() {
        return false;
    }
    create_if_missing(path, &default_progress_map(), PROGRESS_VERSION)
}

/// Lifetime totals as stored in `data`. Pass to `check_condition` after `AchTotals::absorb`.
pub fn totals_of(data: &ProgressData) -> AchTotals {
    AchTotals {
        best_wave: data.best_wave,
        best_score: data.best_score,
        total_kills: data.total_kills,
        bosses_defeated: data.bosses_defeated,
        runs_played: data.runs_played,
        daily_runs: data.daily_runs,
        bosses_seen: data.bosses_seen.clone(),
        arenas_cleared: data.arenas_cleared.clone(),
    }
}

/// The daily key for `ctx`, if it is a valid date. Invalid dates count as normal runs.
fn daily_key(ctx: &RunContext) -> Option<String> {
    ctx.daily_date
        .as_deref()
        .and_then(|d| normalise_date(d).ok())
}

/// Copy of `run` with the settlement context applied. The caller's `RunStats` is not changed,
/// so the replay fingerprint is unaffected.
fn prepared_run(run: &RunStats, ctx: &RunContext) -> RunStats {
    let mut r = run.clone();
    if !ctx.mutators.is_empty() {
        r.mutator_count = ctx.mutators.len().min(i32::MAX as usize) as i32;
    }
    if daily_key(ctx).is_some() {
        r.daily = true;
    }
    r
}

/// Merge a finished run into `data` in memory. Call once per settled run, after `finish`.
pub fn apply_run(data: &mut ProgressData, stats: &RunStats) {
    let mut totals = totals_of(data);
    totals.absorb(stats);
    data.best_wave = totals.best_wave;
    data.best_score = totals.best_score;
    data.total_kills = totals.total_kills;
    data.bosses_defeated = totals.bosses_defeated;
    data.runs_played = totals.runs_played;
    data.daily_runs = totals.daily_runs;
    data.bosses_seen = totals.bosses_seen;
    data.arenas_cleared = totals.arenas_cleared;
}

/// Evaluate every entry in `ACHIEVEMENTS` against `stats` and `data`; returns newly unlocked IDs.
/// `data` must already include the run (call `apply_run` first), so lifetime conditions see it.
pub fn evaluate_achievements(stats: &RunStats, data: &mut ProgressData) -> Vec<&'static str> {
    let totals = totals_of(data);
    let mut newly = Vec::new();
    for ach in ACHIEVEMENTS {
        if data.achievements.iter().any(|id| id == ach.id) {
            continue;
        }
        if check_condition(ach.cond, stats, &totals) {
            data.achievements.push(ach.id.to_string());
            newly.push(ach.id);
        }
    }
    newly
}

/// Achievements that would unlock if the run settled now, for mid-run toasts. Read-only: nothing
/// is saved and `data` is unchanged.
/// `stats` must hold live values: `wave`, `score` and `survived_s` are only set by `finish`, so
/// pass a copy with those fields filled from the live sim. The result repeats on every call until
/// the run settles, so the caller must announce each id once.
pub fn evaluate_live(stats: &RunStats, ctx: &RunContext, data: &ProgressData) -> Vec<&'static str> {
    let run = prepared_run(stats, ctx);
    let totals = totals_of(data).projected(&run);
    ACHIEVEMENTS
        .iter()
        .filter(|a| !data.achievements.iter().any(|id| id == a.id))
        // A condition that can regress must wait for settlement, or the toast would be false.
        .filter(|a| !can_regress(a.cond))
        .filter(|a| check_condition(a.cond, &run, &totals))
        .map(|a| a.id)
        .collect()
}

/// Check unlock conditions for every skin in `SKINS`; returns newly unlocked skin IDs.
pub fn refresh_skin_unlocks(data: &mut ProgressData) -> Vec<&'static str> {
    let mut newly = Vec::new();
    for skin in SKINS {
        let unlocked = match skin.unlock {
            UnlockRule::Default => true,
            UnlockRule::Score(v) => data.best_score >= v,
            UnlockRule::Wave(v) => data.best_wave >= v,
            UnlockRule::Bosses(v) => data.bosses_defeated >= v,
            UnlockRule::Kills(v) => data.total_kills >= v,
            UnlockRule::Achievement(id) => data.achievements.iter().any(|a| a == id),
        };
        if unlocked && !data.unlocked_skins.iter().any(|s| s == skin.id) {
            data.unlocked_skins.push(skin.id.to_string());
            newly.push(skin.id);
        }
    }
    newly
}

pub fn skin_is_unlocked(data: &ProgressData, skin_id: &str) -> bool {
    if skin_id == DEFAULT_SKIN_ID {
        return true;
    }
    data.unlocked_skins.iter().any(|s| s == skin_id)
}

/// True when `path` is absent or can be opened for reading. An unreadable file must not be
/// overwritten, because `load_progress` falls back to defaults in that case.
fn is_readable_or_absent(path: &Path) -> bool {
    !path.exists() || fs::File::open(path).is_ok()
}

/// Settle a finished run in one load/apply/evaluate/save cycle.
///
/// `run.finish(...)` must be called first, or score, wave and survived time are zero. Achievements
/// and daily records are computed from a copy of `run` with `ctx` applied. If `progress.json`
/// exists but cannot be read, nothing is written and `saved` is false.
pub fn end_run(run: &RunStats, ctx: &RunContext, path: &Path) -> EndRunSummary {
    if !is_readable_or_absent(path) {
        return EndRunSummary {
            saved: false,
            progress: load_progress(path),
            new_achievements: Vec::new(),
            new_skins: Vec::new(),
            daily: None,
        };
    }
    let run = prepared_run(run, ctx);
    let mut data = load_progress(path);
    apply_run(&mut data, &run);
    let new_achievements = evaluate_achievements(&run, &mut data);
    let new_skins = refresh_skin_unlocks(&mut data);
    let daily = daily_key(ctx).and_then(|key| {
        record_daily_run_with_metadata(
            &mut data,
            &key,
            run.score,
            run.wave,
            challenge_for_date(&key).ok().map(|challenge| challenge.seed),
            &ctx.mutators,
            Some(SIMULATION_RULES_VERSION),
        )
    });
    let saved = save_progress(path, &data);
    EndRunSummary {
        saved,
        progress: data,
        new_achievements,
        new_skins,
        daily,
    }
}

/// Read stored best `(score, wave)` for a calendar date if present.
pub fn best_for_date(data: &ProgressData, date_iso: &str) -> Option<(i32, i32)> {
    let key = normalise_date(date_iso).ok()?;
    data.daily.get(&key).map(|e| (e.score, e.wave))
}

/// Record a finished daily run into `data` in memory. Higher score wins; an equal score is broken
/// by the furthest wave reached.
pub fn record_daily_run(
    data: &mut ProgressData,
    date_iso: &str,
    score: i32,
    wave: i32,
) -> Option<DailyResult> {
    record_daily_run_with_metadata(data, date_iso, score, wave, None, &[], None)
}

fn record_daily_run_with_metadata(
    data: &mut ProgressData,
    date_iso: &str,
    score: i32,
    wave: i32,
    seed: Option<u64>,
    mutators: &[String],
    rules_version: Option<u32>,
) -> Option<DailyResult> {
    let key = normalise_date(date_iso).ok()?;
    let chosen_mutators = normalize_selection(mutators.iter().map(String::as_str));
    let previous = data.daily.get(&key).cloned();
    let metadata_matches = previous.as_ref().is_some_and(|old| {
        old.seed == seed && old.mutators == chosen_mutators && old.rules_version == rules_version
    });
    let previous_score = metadata_matches
        .then(|| previous.as_ref().map(|old| old.score))
        .flatten();
    let changed = if metadata_matches {
        previous.as_ref().is_none_or(|old| score > old.score || (score == old.score && wave > old.wave))
    } else {
        true
    };
    if changed {
        let mut history = previous.map_or_else(Vec::new, |old| {
            let mut history = old.history;
            if !metadata_matches {
                history.push(DailyRecord {
                    score: old.score,
                    wave: old.wave,
                    seed: old.seed,
                    mutators: old.mutators,
                    rules_version: old.rules_version,
                });
            }
            history
        });
        // Bound save growth while retaining a useful trail across balance revisions.
        if history.len() > 8 {
            let excess = history.len() - 8;
            history.drain(..excess);
        }
        data.daily.insert(
            key.clone(),
            DailyEntry {
                score,
                wave,
                seed,
                mutators: chosen_mutators,
                rules_version,
                history,
            },
        );
    }
    let best = data.daily.get(&key)?;
    Some(DailyResult {
        date_iso: key,
        run_score: score,
        run_wave: wave,
        best_score: best.score,
        best_wave: best.wave,
        previous_score,
        changed,
        new_best: changed,
    })
}
