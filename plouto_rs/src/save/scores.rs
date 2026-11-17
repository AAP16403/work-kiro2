use chrono::Local;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::BTreeMap;
use std::path::Path;

use crate::save::atomic::{
    create_if_missing, load_versioned, save_versioned, value_to_i64, HIGH_SCORES_VERSION,
    VERSION_KEY,
};
use crate::sim::score::{ScoreTracker, MAX_HIGH_SCORES};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HighScoreEntry {
    pub score: i32,
    pub wave: i32,
    pub kills: i32,
    pub best_combo: f32,
    pub date: String,
    #[serde(flatten)]
    pub extra: BTreeMap<String, Value>,
}

#[derive(Debug, Clone)]
pub struct ScoreBoard {
    pub version: i64,
    pub boards: BTreeMap<String, Vec<HighScoreEntry>>,
    pub extra: BTreeMap<String, Value>,
}

impl Default for ScoreBoard {
    fn default() -> Self {
        Self {
            version: HIGH_SCORES_VERSION,
            boards: BTreeMap::new(),
            extra: BTreeMap::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SubmitOutcome {
    pub is_new_best: bool,
    pub rank: usize,
    pub points_to_next: Option<i32>,
    pub saved: bool,
}

fn clean_board(entries: &[Value]) -> Vec<HighScoreEntry> {
    let mut out = Vec::new();
    for item in entries {
        let Value::Object(obj) = item else {
            continue;
        };
        let Some(score_i64) = obj.get("score").and_then(value_to_i64) else {
            continue;
        };
        let wave = obj.get("wave").and_then(value_to_i64).unwrap_or(0) as i32;
        let kills = obj.get("kills").and_then(value_to_i64).unwrap_or(0) as i32;
        let best_combo = obj
            .get("best_combo")
            .and_then(|v| v.as_f64())
            .filter(|f| f.is_finite())
            .unwrap_or(1.0) as f32;
        let date = obj
            .get("date")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        let known = ["score", "wave", "kills", "best_combo", "date"];
        let mut extra = BTreeMap::new();
        for (k, v) in obj {
            if !known.contains(&k.as_str()) {
                extra.insert(k.clone(), v.clone());
            }
        }
        out.push(HighScoreEntry {
            score: score_i64.clamp(0, i32::MAX as i64) as i32,
            wave,
            kills,
            best_combo,
            date,
            extra,
        });
    }
    out
}

fn migrate_high_scores(mut map: Map<String, Value>, _version: i64) -> Map<String, Value> {
    let keys: Vec<String> = map
        .keys()
        .filter(|k| k.as_str() != VERSION_KEY)
        .cloned()
        .collect();
    for key in keys {
        if let Some(Value::Array(arr)) = map.get(&key) {
            let cleaned = clean_board(arr);
            let serialized = cleaned
                .into_iter()
                .filter_map(|e| serde_json::to_value(e).ok())
                .collect();
            map.insert(key, Value::Array(serialized));
        }
    }
    map
}

pub fn load_high_scores(path: &Path) -> ScoreBoard {
    let map = load_versioned(path, HIGH_SCORES_VERSION, migrate_high_scores, Map::new);
    let mut sb = ScoreBoard::default();
    if let Some(v) = map.get(VERSION_KEY).and_then(value_to_i64) {
        sb.version = v.max(HIGH_SCORES_VERSION);
    }
    for (k, v) in map {
        if k == VERSION_KEY {
            continue;
        }
        match v {
            Value::Array(arr) => {
                sb.boards.insert(k, clean_board(&arr));
            }
            other => {
                sb.extra.insert(k, other);
            }
        }
    }
    sb
}

pub fn save_high_scores(path: &Path, sb: &ScoreBoard) -> bool {
    let mut map = Map::new();
    for (k, v) in &sb.extra {
        map.insert(k.clone(), v.clone());
    }
    map.insert(
        VERSION_KEY.to_string(),
        Value::Number(sb.version.max(HIGH_SCORES_VERSION).into()),
    );
    for (diff, entries) in &sb.boards {
        let arr: Vec<Value> = entries
            .iter()
            .filter_map(|e| serde_json::to_value(e).ok())
            .collect();
        map.insert(diff.clone(), Value::Array(arr));
    }
    save_versioned(path, &map, HIGH_SCORES_VERSION)
}

pub fn ensure_high_scores_file(path: &Path) -> bool {
    create_if_missing(path, &Map::new(), HIGH_SCORES_VERSION)
}

pub fn top_score(path: &Path, difficulty: &str) -> i32 {
    let sb = load_high_scores(path);
    sb.boards
        .get(difficulty)
        .and_then(|v| v.first())
        .map(|e| e.score)
        .unwrap_or(0)
}

pub fn submit_score(
    path: &Path,
    tracker: &mut ScoreTracker,
    wave: i32,
    date_override: Option<&str>,
) -> SubmitOutcome {
    let mut sb = load_high_scores(path);
    let entries = sb.boards.entry(tracker.difficulty.clone()).or_default();
    let prev_best = entries.iter().map(|e| e.score).max().unwrap_or(0);

    let date_str = match date_override {
        Some(s) => s.to_string(),
        None => Local::now().format("%Y-%m-%d %H:%M").to_string(),
    };
    let round_combo = (tracker.best_combo * 100.0).round() / 100.0;

    // Tag the newly inserted entry via an index wrapper so equal scores sort strictly after older ones
    // (preserving Python's list.sort reverse=True tie-breaking semantics) while locating it accurately.
    let mut tagged: Vec<(bool, HighScoreEntry)> =
        entries.drain(..).map(|e| (false, e)).collect();
    tagged.push((
        true,
        HighScoreEntry {
            score: tracker.score,
            wave,
            kills: tracker.kills,
            best_combo: round_combo,
            date: date_str,
            extra: BTreeMap::new(),
        },
    ));
    tagged.sort_by(|a, b| b.1.score.cmp(&a.1.score));
    tagged.truncate(MAX_HIGH_SCORES);

    let mut rank = 0usize;
    let mut points_to_next = None;
    for (idx, (is_new, _)) in tagged.iter().enumerate() {
        if *is_new {
            rank = idx + 1;
            break;
        }
    }
    if rank > 1 {
        let above = tagged[rank - 2].1.score;
        points_to_next = Some(above - tracker.score + 1);
    }

    *entries = tagged.into_iter().map(|(_, e)| e).collect();
    tracker.last_rank = rank;
    tracker.last_points_to_next = points_to_next;

    let saved = save_high_scores(path, &sb);
    SubmitOutcome {
        is_new_best: tracker.score > prev_best,
        rank,
        points_to_next,
        saved,
    }
}
