use chrono::Utc;
use sha2::{Digest, Sha256};

use crate::sim::config::ARENA_MARGIN_DEFAULT;
use crate::sim::mutators::MUTATORS;

pub const SEED_SALT: &str = "ploto-daily-v1";
pub const DAILY_DIFFICULTY: &str = "normal";
pub const DAILY_MAP_TYPE: &str = "circle";
pub const DAILY_ARENA_MARGIN: f32 = ARENA_MARGIN_DEFAULT;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DailyChallenge {
    pub date_iso: String,
    pub seed: u64,
    pub mutator_id: &'static str,
    pub difficulty: &'static str,
    pub map_type: &'static str,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DailyResult {
    pub date_iso: String,
    pub run_score: i32,
    pub run_wave: i32,
    pub best_score: i32,
    pub best_wave: i32,
    pub previous_score: Option<i32>,
    pub changed: bool,
    pub new_best: bool,
}

pub fn is_daily_run(daily_date: Option<&str>) -> bool {
    daily_date.and_then(|date| normalise_date(date).ok()).is_some()
}

pub fn today_iso() -> String {
    Utc::now().date_naive().format("%Y-%m-%d").to_string()
}

pub fn normalise_date(date_iso: &str) -> Result<String, String> {
    chrono::NaiveDate::parse_from_str(date_iso, "%Y-%m-%d")
        .map(|d| d.format("%Y-%m-%d").to_string())
        .map_err(|_| format!("expected YYYY-MM-DD, got {date_iso:?}"))
}

pub fn daily_seed(date_iso: &str) -> Result<u64, String> {
    let norm = normalise_date(date_iso)?;
    let key = format!("{SEED_SALT}|{norm}");
    let digest = Sha256::digest(key.as_bytes());
    let mut bytes = [0u8; 8];
    bytes.copy_from_slice(&digest[..8]);
    Ok(u64::from_be_bytes(bytes))
}

pub fn mutator_pool() -> Vec<&'static str> {
    let mut ids: Vec<&'static str> = MUTATORS.iter().map(|m| m.id).collect();
    ids.sort_unstable();
    ids
}

pub fn daily_mutator(date_iso: &str) -> Result<&'static str, String> {
    let pool = mutator_pool();
    if pool.is_empty() {
        return Err("daily mutator pool is empty".to_string());
    }
    let seed = daily_seed(date_iso)?;
    Ok(pool[(seed % (pool.len() as u64)) as usize])
}

pub fn challenge_for_date(date_iso: &str) -> Result<DailyChallenge, String> {
    let date_iso = normalise_date(date_iso)?;
    let seed = daily_seed(&date_iso)?;
    let mutator_id = daily_mutator(&date_iso)?;
    Ok(DailyChallenge {
        date_iso,
        seed,
        mutator_id,
        difficulty: DAILY_DIFFICULTY,
        map_type: DAILY_MAP_TYPE,
    })
}
