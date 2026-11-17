use crate::sim::config::BOSS_WAVE_EVERY;

pub const KILL_POINTS: &[(&str, i32)] = &[
    ("chaser", 100),
    ("ranged", 150),
    ("swarm", 60),
    ("charger", 175),
    ("tank", 250),
    ("spitter", 175),
    ("flyer", 150),
    ("engineer", 200),
    ("bomber", 200),
    ("sniper", 225),
    ("boss_thunder", 2000),
    ("boss_laser", 2000),
    ("boss_trapmaster", 2500),
    ("boss_swarmqueen", 2500),
    ("boss_brute", 2200),
    ("boss_abyss_gaze", 3000),
    ("boss_womb_core", 3000),
    ("boss_eclipse_archon", 3200),
];

pub fn kill_points_for(behavior: &str) -> i32 {
    KILL_POINTS
        .iter()
        .find(|(k, _)| *k == behavior)
        .map(|(_, v)| *v)
        .unwrap_or(100)
}

pub const WAVE_CLEAR_BASE: i32 = 500;
pub const WAVE_CLEAR_PER_WAVE: i32 = 150;
pub const BOSS_WAVE_BONUS: i32 = 3000;

pub const COMBO_DECAY_DELAY: f32 = 2.0;
pub const COMBO_DECAY_RATE: f32 = 1.0;
pub const COMBO_INCREMENT: f32 = 0.25;
pub const COMBO_MAX: f32 = 8.0;
pub const MAX_HIGH_SCORES: usize = 5;

pub fn combo_window_fraction(elapsed: f32, window: f32) -> f32 {
    if window <= 0.0 {
        return 0.0;
    }
    (1.0 - elapsed / window).clamp(0.0, 1.0)
}

#[derive(Debug, Clone)]
pub struct ScoreTracker {
    pub score: i32,
    pub combo: f32,
    pub score_mult: f32,
    pub combo_timer: f32,
    pub difficulty: String,
    pub kills: i32,
    pub best_combo: f32,
    pub last_rank: usize,
    pub last_points_to_next: Option<i32>,
}

impl ScoreTracker {
    pub fn new(difficulty: &str, score_mult: f32) -> Self {
        Self {
            score: 0,
            combo: 1.0,
            score_mult,
            combo_timer: 0.0,
            difficulty: difficulty.to_string(),
            kills: 0,
            best_combo: 1.0,
            last_rank: 0,
            last_points_to_next: None,
        }
    }

    pub fn on_enemy_kill(&mut self, behavior: &str, multiplier: f32) -> i32 {
        let base = kill_points_for(behavior) as f32;
        let points = (base * self.combo * multiplier * self.score_mult) as i32;
        self.score += points;
        self.kills += 1;

        self.combo = (self.combo + COMBO_INCREMENT).min(COMBO_MAX);
        self.best_combo = self.best_combo.max(self.combo);
        self.combo_timer = 0.0;
        points
    }

    pub fn on_wave_clear(&mut self, wave: i32) -> i32 {
        let is_boss = wave % BOSS_WAVE_EVERY == 0;
        let mut bonus = WAVE_CLEAR_BASE + wave * WAVE_CLEAR_PER_WAVE;
        if is_boss {
            bonus += BOSS_WAVE_BONUS;
        }
        let awarded = ((bonus as f32) * self.combo * self.score_mult) as i32;
        self.score += awarded;
        awarded
    }

    pub fn on_player_hit(&mut self) {
        self.combo = 1.0;
        self.combo_timer = 0.0;
    }

    pub fn update(&mut self, dt: f32) {
        self.combo_timer += dt;
        if self.combo_timer >= COMBO_DECAY_DELAY && self.combo > 1.0 {
            self.combo = (self.combo - COMBO_DECAY_RATE * dt).max(1.0);
        }
    }

    pub fn combo_window_left(&self) -> f32 {
        if self.combo <= 1.0 {
            return 0.0;
        }
        combo_window_fraction(self.combo_timer, COMBO_DECAY_DELAY)
    }
}
