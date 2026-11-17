//! Achievement definitions, per-run statistics and lifetime totals.
//!
//! Wiring summary (who calls what):
//! - `RunStats` lives in `SimState::run_stats` and is hashed into the replay fingerprint
//!   (`sim/replay.rs`, Debug of `run_stats`). Any field change needs `SIMULATION_RULES_VERSION` bumped.
//! - `AchTotals` is the lifetime view. Build it from `ProgressData` before evaluating, or use
//!   `AchTotals::projected` to preview a run that has not been saved yet.
//! - `check_condition` / `progress_of` expect `totals` that ALREADY include the run being judged
//!   (i.e. after `AchTotals::absorb`). For a live preview, pass `totals.projected(&run)`.
//! - Achievement ids are persisted in players' progress.json. Never rename or remove an id.

use crate::sim::config::{MAP_CIRCLE, MAP_CROSS, MAP_DIAMOND, MAP_DONUT};
use crate::sim::score::COMBO_MAX;

/// Boss behavior names (as passed to `on_boss_kind`). Order defines the bit positions in
/// `RunStats::boss_kinds`, so append only; reordering changes the replay fingerprint.
pub const BOSS_KINDS: &[&str] = &[
    "boss_brute",
    "boss_laser",
    "boss_thunder",
    "boss_trapmaster",
    "boss_swarmqueen",
    "boss_womb_core",
    "boss_abyss_gaze",
    "boss_eclipse_archon",
];

/// Arena shapes (`SimState::map_type` values). Bit positions in `RunStats::arenas_cleared`.
pub const ARENA_SHAPES: &[&str] = &[MAP_CIRCLE, MAP_DONUT, MAP_CROSS, MAP_DIAMOND];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AchCondition {
    /// Per-run integer stat (see `run_value` for keys).
    RunAtLeast(&'static str, i64),
    /// Per-run float stat, threshold stored in thousandths (see `run_float` for keys).
    RunFloatAtLeast(&'static str, u32),
    /// Lifetime stat (see `total_value` for keys).
    TotalAtLeast(&'static str, i64),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AchCategory {
    Combat,
    Survival,
    Bosses,
    Mastery,
    Career,
}

impl AchCategory {
    pub const ALL: [AchCategory; 5] = [
        AchCategory::Combat,
        AchCategory::Survival,
        AchCategory::Bosses,
        AchCategory::Mastery,
        AchCategory::Career,
    ];

    pub fn label(self) -> &'static str {
        match self {
            AchCategory::Combat => "Combat",
            AchCategory::Survival => "Survival",
            AchCategory::Bosses => "Bosses",
            AchCategory::Mastery => "Mastery",
            AchCategory::Career => "Career",
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct AchievementDef {
    pub id: &'static str,
    pub name: &'static str,
    pub description: &'static str,
    pub cond: AchCondition,
    pub category: AchCategory,
    /// Secret achievements hide name and description until earned (see `shown_name`).
    pub secret: bool,
}

pub const ACHIEVEMENTS: &[AchievementDef] = &[
    // ---- Original 20 (ids and names must never change) ----
    AchievementDef {
        id: "first_blood",
        name: "First Blood",
        description: "Destroy your first enemy in a run.",
        cond: AchCondition::RunAtLeast("kills", 1),
        category: AchCategory::Combat,
        secret: false,
    },
    AchievementDef {
        id: "massacre",
        name: "Massacre",
        description: "Destroy 50 enemies in one run.",
        cond: AchCondition::RunAtLeast("kills", 50),
        category: AchCategory::Combat,
        secret: false,
    },
    AchievementDef {
        id: "giant_slayer",
        name: "Giant Slayer",
        description: "Defeat a boss in a single run.",
        cond: AchCondition::RunAtLeast("boss_kills", 1),
        category: AchCategory::Bosses,
        secret: false,
    },
    AchievementDef {
        id: "boss_hunter",
        name: "Boss Hunter",
        description: "Defeat 3 bosses across all runs.",
        cond: AchCondition::TotalAtLeast("bosses_defeated", 3),
        category: AchCategory::Bosses,
        secret: false,
    },
    AchievementDef {
        id: "bossbreaker",
        name: "Bossbreaker",
        description: "Defeat 15 bosses across all runs.",
        cond: AchCondition::TotalAtLeast("bosses_defeated", 15),
        category: AchCategory::Bosses,
        secret: false,
    },
    AchievementDef {
        id: "no_damage_wave",
        name: "Untouchable",
        description: "Clear a wave without taking health damage. Shield blocks don't count.",
        cond: AchCondition::RunAtLeast("perfect_waves", 1),
        category: AchCategory::Survival,
        secret: false,
    },
    AchievementDef {
        id: "flawless_five",
        name: "Flawless Five",
        description: "Clear 5 waves untouched in one run.",
        cond: AchCondition::RunAtLeast("perfect_waves", 5),
        category: AchCategory::Survival,
        secret: false,
    },
    AchievementDef {
        id: "elite_slayer",
        name: "Elite Slayer",
        description: "Destroy 5 elite enemies in one run.",
        cond: AchCondition::RunAtLeast("elite_kills", 5),
        category: AchCategory::Combat,
        secret: false,
    },
    AchievementDef {
        id: "combo_6x",
        name: "Combo x6",
        description: "Reach a 6x kill combo.",
        cond: AchCondition::RunFloatAtLeast("best_combo", 6000),
        category: AchCategory::Combat,
        secret: false,
    },
    AchievementDef {
        id: "combo_max",
        name: "Maxed Out",
        description: "Reach the top kill combo.",
        cond: AchCondition::RunFloatAtLeast("best_combo", (COMBO_MAX * 1000.0) as u32),
        category: AchCategory::Combat,
        secret: false,
    },
    AchievementDef {
        id: "survive_ten_waves",
        name: "Survivor",
        description: "Survive ten waves in one run.",
        cond: AchCondition::RunAtLeast("waves_cleared", 10),
        category: AchCategory::Survival,
        secret: false,
    },
    AchievementDef {
        id: "into_the_deep",
        name: "Into the Deep",
        description: "Reach wave 10.",
        cond: AchCondition::RunAtLeast("wave", 10),
        category: AchCategory::Survival,
        secret: false,
    },
    AchievementDef {
        id: "deep_space",
        name: "Deep Space",
        description: "Reach wave 20.",
        cond: AchCondition::RunAtLeast("wave", 20),
        category: AchCategory::Survival,
        secret: false,
    },
    AchievementDef {
        id: "edge_of_stars",
        name: "Edge of the Stars",
        description: "Reach wave 30.",
        cond: AchCondition::RunAtLeast("wave", 30),
        category: AchCategory::Survival,
        secret: false,
    },
    AchievementDef {
        id: "marathon",
        name: "Marathon",
        description: "Survive five minutes in one run.",
        cond: AchCondition::RunFloatAtLeast("survived_s", 300_000),
        category: AchCategory::Survival,
        secret: false,
    },
    AchievementDef {
        id: "five_digits",
        name: "Five Digits",
        description: "Score 10,000 in one run.",
        cond: AchCondition::RunAtLeast("score", 10000),
        category: AchCategory::Mastery,
        secret: false,
    },
    AchievementDef {
        id: "stellar_score",
        name: "Stellar Score",
        description: "Score 50,000 in one run.",
        cond: AchCondition::RunAtLeast("score", 50000),
        category: AchCategory::Mastery,
        secret: false,
    },
    AchievementDef {
        id: "centurion",
        name: "Centurion",
        description: "Destroy 100 enemies across all runs.",
        cond: AchCondition::TotalAtLeast("total_kills", 100),
        category: AchCategory::Career,
        secret: false,
    },
    AchievementDef {
        id: "exterminator",
        name: "Exterminator",
        description: "Destroy 1,000 enemies across all runs.",
        cond: AchCondition::TotalAtLeast("total_kills", 1000),
        category: AchCategory::Career,
        secret: false,
    },
    AchievementDef {
        id: "veteran",
        name: "Veteran",
        description: "Play 10 runs.",
        cond: AchCondition::TotalAtLeast("runs_played", 10),
        category: AchCategory::Career,
        secret: false,
    },
    // ---- Added in the wave-9 expansion (new ids only) ----
    AchievementDef {
        id: "dash_master",
        name: "Dash Master",
        description: "Dash 100 times in one run.",
        cond: AchCondition::RunAtLeast("dashes", 100),
        category: AchCategory::Mastery,
        secret: false,
    },
    AchievementDef {
        id: "overdrive",
        name: "Overdrive",
        description: "Fire 5 ultras in one run.",
        cond: AchCondition::RunAtLeast("ultra_uses", 5),
        category: AchCategory::Combat,
        secret: false,
    },
    AchievementDef {
        id: "overkill",
        name: "Overkill",
        description: "Destroy 25 enemies with ultras in one run.",
        cond: AchCondition::RunAtLeast("ultra_kills", 25),
        category: AchCategory::Combat,
        secret: false,
    },
    AchievementDef {
        id: "scavenger",
        name: "Scavenger",
        description: "Collect 25 pickups in one run.",
        cond: AchCondition::RunAtLeast("pickups", 25),
        category: AchCategory::Mastery,
        secret: false,
    },
    AchievementDef {
        id: "shield_wall",
        name: "Shield Wall",
        description: "Block 10 hits with your shield in one run.",
        cond: AchCondition::RunAtLeast("shield_blocks", 10),
        category: AchCategory::Survival,
        secret: false,
    },
    AchievementDef {
        id: "triple_threat",
        name: "Triple Threat",
        description: "Defeat 3 bosses in one run.",
        cond: AchCondition::RunAtLeast("boss_kills", 3),
        category: AchCategory::Bosses,
        secret: false,
    },
    AchievementDef {
        id: "every_boss",
        name: "Boss Collector",
        description: "Defeat every kind of boss at least once across all runs.",
        cond: AchCondition::TotalAtLeast("boss_kinds_seen", BOSS_KINDS.len() as i64),
        category: AchCategory::Bosses,
        secret: false,
    },
    AchievementDef {
        id: "world_tour",
        name: "World Tour",
        description: "Clear a wave in every arena shape across all runs.",
        cond: AchCondition::TotalAtLeast("arenas_cleared", ARENA_SHAPES.len() as i64),
        category: AchCategory::Mastery,
        secret: false,
    },
    AchievementDef {
        id: "daily_driver",
        name: "Daily Driver",
        description: "Finish a daily challenge run.",
        cond: AchCondition::TotalAtLeast("daily_runs", 1),
        category: AchCategory::Career,
        secret: false,
    },
    AchievementDef {
        id: "mutant",
        name: "Mutant",
        description: "Reach wave 10 with at least one mutator active.",
        cond: AchCondition::RunAtLeast("wave_mutated", 10),
        category: AchCategory::Mastery,
        secret: false,
    },
    AchievementDef {
        id: "purist",
        name: "Purist",
        description: "Reach wave 15 without firing an ultra.",
        cond: AchCondition::RunAtLeast("wave_no_ultra", 15),
        category: AchCategory::Mastery,
        secret: false,
    },
    AchievementDef {
        id: "endurance",
        name: "Endurance",
        description: "Survive ten minutes in one run.",
        cond: AchCondition::RunFloatAtLeast("survived_s", 600_000),
        category: AchCategory::Survival,
        secret: false,
    },
    AchievementDef {
        id: "five_thousand",
        name: "Five Thousand",
        description: "Destroy 5,000 enemies across all runs.",
        cond: AchCondition::TotalAtLeast("total_kills", 5000),
        category: AchCategory::Career,
        secret: false,
    },
    AchievementDef {
        id: "old_hand",
        name: "Old Hand",
        description: "Play 50 runs.",
        cond: AchCondition::TotalAtLeast("runs_played", 50),
        category: AchCategory::Career,
        secret: false,
    },
    AchievementDef {
        id: "clean_sweep",
        name: "Clean Sweep",
        description: "Clear 10 waves untouched in one run.",
        cond: AchCondition::RunAtLeast("perfect_waves", 10),
        category: AchCategory::Survival,
        secret: true,
    },
];

/// Ids that shipped in the original 20-achievement release. Saved progress depends on them.
pub const LEGACY_ACHIEVEMENT_IDS: &[&str] = &[
    "first_blood",
    "massacre",
    "giant_slayer",
    "boss_hunter",
    "bossbreaker",
    "no_damage_wave",
    "flawless_five",
    "elite_slayer",
    "combo_6x",
    "combo_max",
    "survive_ten_waves",
    "into_the_deep",
    "deep_space",
    "edge_of_stars",
    "marathon",
    "five_digits",
    "stellar_score",
    "centurion",
    "exterminator",
    "veteran",
];

pub fn get_achievement(id: &str) -> Option<&'static AchievementDef> {
    ACHIEVEMENTS.iter().find(|a| a.id == id)
}

pub fn name_of(id: &str) -> &str {
    get_achievement(id).map(|a| a.name).unwrap_or(id)
}

/// Name to show for a definition. Secret achievements read "???" until earned.
pub fn shown_name(def: &AchievementDef, earned: bool) -> &'static str {
    if def.secret && !earned {
        "???"
    } else {
        def.name
    }
}

/// Description to show for a definition. Secret achievements hide their text until earned.
pub fn shown_description(def: &AchievementDef, earned: bool) -> &'static str {
    if def.secret && !earned {
        "Secret achievement. Keep playing to find out how."
    } else {
        def.description
    }
}

/// Per-run statistics. Hashed into the replay fingerprint: any change to fields or to
/// the recording rules requires `SIMULATION_RULES_VERSION` to be bumped.
#[derive(Debug, Clone)]
pub struct RunStats {
    pub kills: i32,
    pub elite_kills: i32,
    pub boss_kills: i32,
    /// Hits that removed health. Only `on_player_hit` increments this.
    pub hits_taken: i32,
    /// Health damage taken (shield-absorbed damage is not included).
    pub damage_taken: i32,
    pub waves_cleared: i32,
    pub perfect_waves: i32,
    pub best_combo: f32,
    /// Set by `finish`.
    pub wave: i32,
    /// Set by `finish`.
    pub score: i32,
    /// Set by `finish`.
    pub survived_s: f32,
    pub finished: bool,
    /// Successful dashes.
    pub dashes: i32,
    /// Ultras fired.
    pub ultra_uses: i32,
    /// Enemies destroyed by an ultra (in addition to the normal `on_kill`).
    pub ultra_kills: i32,
    /// Pickups collected.
    pub pickups: i32,
    /// Hits fully or partly absorbed by the shield without health loss.
    pub shield_blocks: i32,
    /// Number of mutators active in this run (set by `set_run_context`).
    pub mutator_count: i32,
    /// True for a daily challenge run (set by `set_run_context`).
    pub daily: bool,
    /// Bitmask over `BOSS_KINDS`: bosses killed this run.
    pub boss_kinds: u32,
    /// Bitmask over `ARENA_SHAPES`: arena shapes that had at least one wave cleared this run.
    pub arenas_cleared: u32,
    hits_at_last_clear: i32,
}

impl Default for RunStats {
    fn default() -> Self {
        Self::new()
    }
}

impl RunStats {
    pub fn new() -> Self {
        Self {
            kills: 0,
            elite_kills: 0,
            boss_kills: 0,
            hits_taken: 0,
            damage_taken: 0,
            waves_cleared: 0,
            perfect_waves: 0,
            best_combo: 1.0,
            wave: 0,
            score: 0,
            survived_s: 0.0,
            finished: false,
            dashes: 0,
            ultra_uses: 0,
            ultra_kills: 0,
            pickups: 0,
            shield_blocks: 0,
            mutator_count: 0,
            daily: false,
            boss_kinds: 0,
            arenas_cleared: 0,
            hits_at_last_clear: 0,
        }
    }

    /// Every enemy death credited to the player. Call from `kill_enemy_by_id` (step.rs), not
    /// for contact suicides or hatch removals. `boss` is `behavior.starts_with("boss_")`.
    /// Pair it with `on_boss_kind` for boss kills and `on_ultra_kill` for ultra kills.
    pub fn on_kill(&mut self, elite: bool, boss: bool, combo: f32) {
        self.kills = self.kills.saturating_add(1);
        if elite {
            self.elite_kills = self.elite_kills.saturating_add(1);
        }
        if boss {
            self.boss_kills = self.boss_kills.saturating_add(1);
        }
        self.best_combo = self.best_combo.max(combo);
    }

    /// Call ONLY for a hit that removed health (`health_damage > 0`, after shield absorb).
    /// Shield-only blocks must go to `on_shield_block` so they keep the Untouchable streak.
    /// Non-positive amounts are ignored.
    pub fn on_player_hit(&mut self, health_damage: i32) {
        if health_damage <= 0 {
            return;
        }
        self.hits_taken = self.hits_taken.saturating_add(1);
        self.damage_taken = self.damage_taken.saturating_add(health_damage);
    }

    /// Call when the shield absorbs a hit and no health is lost (`shield_damage > 0 &&
    /// health_damage == 0`). Does not break the Untouchable streak.
    pub fn on_shield_block(&mut self) {
        self.shield_blocks = self.shield_blocks.saturating_add(1);
    }

    /// Call when a dash is performed (`trigger_dash` in step.rs, when `perform_dash` returns true).
    pub fn on_dash(&mut self) {
        self.dashes = self.dashes.saturating_add(1);
    }

    /// Call where an ultra charge is spent (ultra activation in step.rs).
    pub fn on_ultra_use(&mut self) {
        self.ultra_uses = self.ultra_uses.saturating_add(1);
    }

    /// Call for each enemy killed by an ultra, alongside `on_kill` for that same kill.
    pub fn on_ultra_kill(&mut self) {
        self.ultra_kills = self.ultra_kills.saturating_add(1);
    }

    /// Call where a pickup is applied (`apply_powerup` site in step.rs).
    pub fn on_pickup(&mut self) {
        self.pickups = self.pickups.saturating_add(1);
    }

    /// Call with the behavior name of a boss that died (e.g. "boss_brute"), alongside `on_kill`.
    /// Unknown names are ignored.
    pub fn on_boss_kind(&mut self, behavior: &str) {
        set_bit(&mut self.boss_kinds, BOSS_KINDS, behavior);
    }

    /// Call from the wave-clear path with `state.map_type` (for example MAP_DONUT).
    /// Pair it with `on_wave_clear`. Unknown shapes are ignored.
    pub fn on_arena_clear(&mut self, map_type: &str) {
        set_bit(&mut self.arenas_cleared, ARENA_SHAPES, map_type);
    }

    /// Call once at run start (or at settle, before `finish`). `mutator_count` is the number of
    /// active mutators; `daily` is true for daily challenge runs.
    pub fn set_run_context(&mut self, mutator_count: i32, daily: bool) {
        self.mutator_count = mutator_count.max(0);
        self.daily = daily;
    }

    /// Call when a wave clears (step.rs wave-clear block). Counts a perfect wave when no health
    /// hit happened since the previous clear.
    pub fn on_wave_clear(&mut self) {
        self.waves_cleared = self.waves_cleared.saturating_add(1);
        if self.hits_taken == self.hits_at_last_clear {
            self.perfect_waves = self.perfect_waves.saturating_add(1);
        }
        self.hits_at_last_clear = self.hits_taken;
    }

    /// Boss kinds killed this run, in `BOSS_KINDS` order.
    pub fn boss_kind_names(&self) -> Vec<&'static str> {
        names_in(BOSS_KINDS, self.boss_kinds)
    }

    /// Arena shapes cleared this run, in `ARENA_SHAPES` order.
    pub fn arena_names(&self) -> Vec<&'static str> {
        names_in(ARENA_SHAPES, self.arenas_cleared)
    }

    /// Call once when the run settles (death or quit), before evaluating achievements.
    /// Only the first call has an effect.
    pub fn finish(&mut self, score: i32, wave: i32, survived_s: f32, best_combo: Option<f32>) {
        if self.finished {
            return;
        }
        self.finished = true;
        self.score = score;
        self.wave = wave;
        self.survived_s = survived_s;
        if let Some(c) = best_combo {
            self.best_combo = self.best_combo.max(c);
        }
    }
}

/// Lifetime totals used by `TotalAtLeast` conditions and the progress bars.
/// Built from `ProgressData` by the save layer. Fields are pub so it can be filled directly.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct AchTotals {
    pub best_wave: i32,
    pub best_score: i32,
    pub total_kills: i32,
    pub bosses_defeated: i32,
    pub runs_played: i32,
    pub daily_runs: i32,
    /// Distinct boss behavior names killed at least once (subset of `BOSS_KINDS`).
    pub bosses_seen: Vec<String>,
    /// Distinct arena shapes with at least one cleared wave (subset of `ARENA_SHAPES`).
    pub arenas_cleared: Vec<String>,
}

impl AchTotals {
    /// Merge a finished run into the totals. Call exactly once per settled run.
    pub fn absorb(&mut self, run: &RunStats) {
        self.best_wave = self.best_wave.max(run.wave);
        self.best_score = self.best_score.max(run.score);
        self.total_kills = self.total_kills.saturating_add(run.kills);
        self.bosses_defeated = self.bosses_defeated.saturating_add(run.boss_kills);
        self.runs_played = self.runs_played.saturating_add(1);
        if run.daily {
            self.daily_runs = self.daily_runs.saturating_add(1);
        }
        for name in run.boss_kind_names() {
            if !self.bosses_seen.iter().any(|s| s == name) {
                self.bosses_seen.push(name.to_string());
            }
        }
        for name in run.arena_names() {
            if !self.arenas_cleared.iter().any(|s| s == name) {
                self.arenas_cleared.push(name.to_string());
            }
        }
    }

    /// Totals as they would be after `absorb(run)`, without changing self. For live previews.
    pub fn projected(&self, run: &RunStats) -> AchTotals {
        let mut t = self.clone();
        t.absorb(run);
        t
    }
}

fn set_bit(mask: &mut u32, list: &[&str], name: &str) {
    if let Some(i) = list.iter().position(|n| *n == name) {
        if i < 32 {
            *mask |= 1u32 << i;
        }
    }
}

fn names_in(list: &'static [&'static str], mask: u32) -> Vec<&'static str> {
    list.iter()
        .enumerate()
        .filter(|(i, _)| *i < 32 && (mask >> *i) & 1 == 1)
        .map(|(_, n)| *n)
        .collect()
}

/// Value of a per-run integer stat. `None` for an unknown key.
fn run_value(key: &str, run: &RunStats) -> Option<i64> {
    let v = match key {
        "kills" => run.kills as i64,
        "elite_kills" => run.elite_kills as i64,
        "boss_kills" => run.boss_kills as i64,
        "waves_cleared" => run.waves_cleared as i64,
        "perfect_waves" => run.perfect_waves as i64,
        "wave" => run.wave as i64,
        "score" => run.score as i64,
        "dashes" => run.dashes as i64,
        "ultra_uses" => run.ultra_uses as i64,
        "ultra_kills" => run.ultra_kills as i64,
        "pickups" => run.pickups as i64,
        "shield_blocks" => run.shield_blocks as i64,
        // Wave reached, only when at least one mutator was active.
        "wave_mutated" => {
            if run.mutator_count > 0 {
                run.wave as i64
            } else {
                0
            }
        }
        // Wave reached, only when no ultra was fired.
        "wave_no_ultra" => {
            if run.ultra_uses == 0 {
                run.wave as i64
            } else {
                0
            }
        }
        _ => return None,
    };
    Some(v)
}

/// Value of a per-run float stat. `None` for an unknown key.
fn run_float(key: &str, run: &RunStats) -> Option<f32> {
    match key {
        "best_combo" => Some(run.best_combo),
        "survived_s" => Some(run.survived_s),
        _ => None,
    }
}

/// Value of a lifetime stat. `None` for an unknown key.
fn total_value(key: &str, t: &AchTotals) -> Option<i64> {
    let v = match key {
        "best_wave" => t.best_wave as i64,
        "best_score" => t.best_score as i64,
        "total_kills" => t.total_kills as i64,
        "bosses_defeated" => t.bosses_defeated as i64,
        "runs_played" => t.runs_played as i64,
        "daily_runs" => t.daily_runs as i64,
        "boss_kinds_seen" => t.bosses_seen.len() as i64,
        "arenas_cleared" => t.arenas_cleared.len() as i64,
        _ => return None,
    };
    Some(v)
}

/// (current, target) in the condition's units. Float conditions use thousandths.
/// `None` when the key is unknown.
fn evaluate_cond(cond: AchCondition, run: &RunStats, totals: &AchTotals) -> Option<(i64, i64)> {
    match cond {
        AchCondition::RunAtLeast(k, v) => run_value(k, run).map(|c| (c, v)),
        AchCondition::RunFloatAtLeast(k, thousandths) => run_float(k, run)
            .map(|c| (((c * 1000.0).round()) as i64, thousandths as i64)),
        AchCondition::TotalAtLeast(k, v) => total_value(k, totals).map(|c| (c, v)),
    }
}

fn target_of(cond: AchCondition) -> i64 {
    match cond {
        AchCondition::RunAtLeast(_, v) | AchCondition::TotalAtLeast(_, v) => v,
        AchCondition::RunFloatAtLeast(_, thousandths) => thousandths as i64,
    }
}

/// True when the condition is met. `totals` must already include `run` (see module docs).
/// Unknown keys never unlock (no panic); `every_key_is_known` in the tests guards this.
pub fn check_condition(cond: AchCondition, run: &RunStats, totals: &AchTotals) -> bool {
    evaluate_cond(cond, run, totals)
        .map(|(current, target)| current >= target)
        .unwrap_or(false)
}

/// False for conditions that can become false again later in the same run. `wave_no_ultra`
/// is one: firing an ultra after wave 15 spoils it. Live previews skip these, so a mid-run
/// toast is never shown for an unlock the settled run would not grant.
pub fn can_regress(cond: AchCondition) -> bool {
    matches!(cond, AchCondition::RunAtLeast("wave_no_ultra", _))
}

/// (current, target) for progress bars. Units match the condition (float conditions in
/// thousandths). `current` is not capped, so clamp it in the UI. Unknown keys give (0, target).
pub fn progress_of(def: &AchievementDef, run: &RunStats, totals: &AchTotals) -> (i64, i64) {
    evaluate_cond(def.cond, run, totals).unwrap_or((0, target_of(def.cond)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_key_is_known() {
        let run = RunStats::new();
        let totals = AchTotals::default();
        for def in ACHIEVEMENTS.iter() {
            assert!(
                evaluate_cond(def.cond, &run, &totals).is_some(),
                "unknown stat key in achievement {}",
                def.id
            );
        }
    }

    #[test]
    fn ids_are_unique_and_legacy_ids_present() {
        for (i, a) in ACHIEVEMENTS.iter().enumerate() {
            for b in ACHIEVEMENTS.iter().skip(i + 1) {
                assert_ne!(a.id, b.id, "duplicate id {}", a.id);
            }
        }
        for id in LEGACY_ACHIEVEMENT_IDS {
            assert!(get_achievement(id).is_some(), "legacy id removed: {}", id);
        }
        assert_eq!(LEGACY_ACHIEVEMENT_IDS.len(), 20);
    }

    #[test]
    fn health_hit_breaks_untouched_streak_but_shield_block_does_not() {
        let mut r = RunStats::new();
        r.on_shield_block();
        r.on_wave_clear();
        assert_eq!(r.perfect_waves, 1);
        r.on_player_hit(3);
        r.on_wave_clear();
        assert_eq!(r.perfect_waves, 1);
        assert_eq!(r.hits_taken, 1);
        assert_eq!(r.damage_taken, 3);
        assert_eq!(r.shield_blocks, 1);
    }

    #[test]
    fn lifetime_boss_and_arena_tracking() {
        let mut run = RunStats::new();
        run.on_boss_kind("boss_brute");
        run.on_boss_kind("boss_brute");
        run.on_boss_kind("not_a_boss");
        run.on_arena_clear(MAP_DONUT);
        run.finish(100, 3, 10.0, None);
        let mut totals = AchTotals::default();
        totals.absorb(&run);
        assert_eq!(totals.bosses_seen, vec!["boss_brute".to_string()]);
        assert_eq!(totals.arenas_cleared, vec![MAP_DONUT.to_string()]);
        assert_eq!(totals.runs_played, 1);
        let mut run2 = RunStats::new();
        run2.on_boss_kind("boss_brute");
        run2.finish(0, 0, 0.0, None);
        totals.absorb(&run2);
        assert_eq!(totals.bosses_seen.len(), 1);
        assert_eq!(totals.runs_played, 2);
    }

    #[test]
    fn purist_can_regress_and_is_not_live_safe() {
        let cond = AchCondition::RunAtLeast("wave_no_ultra", 15);
        assert!(can_regress(cond));
        assert!(!can_regress(AchCondition::RunAtLeast("wave", 15)));
        let mut run = RunStats::new();
        run.finish(0, 15, 0.0, None);
        assert!(check_condition(cond, &run, &AchTotals::default()));
        run.on_ultra_use();
        assert!(!check_condition(cond, &run, &AchTotals::default()));
    }

    #[test]
    fn mutant_and_purist_use_run_context() {
        let mut run = RunStats::new();
        run.set_run_context(1, false);
        run.finish(0, 10, 0.0, None);
        assert!(check_condition(
            AchCondition::RunAtLeast("wave_mutated", 10),
            &run,
            &AchTotals::default()
        ));
        let mut none = RunStats::new();
        none.finish(0, 15, 0.0, None);
        assert!(!check_condition(
            AchCondition::RunAtLeast("wave_mutated", 10),
            &none,
            &AchTotals::default()
        ));
        assert!(check_condition(
            AchCondition::RunAtLeast("wave_no_ultra", 15),
            &none,
            &AchTotals::default()
        ));
    }
}
