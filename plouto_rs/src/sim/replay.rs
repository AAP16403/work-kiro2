use std::fs::File;
use std::io::{BufReader, BufWriter};
use std::path::Path;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::sim::math::Vec2;
use crate::sim::config::RuntimeConfig;
use crate::sim::state::{RunSetup, SimInput, SimState};
use crate::sim::step::{apply_boss_perm_reward, apply_boss_temp_reward, step};

pub const SIMULATION_RULES_VERSION: u32 = 13;
pub const REPLAY_CHECKPOINT_INTERVAL: usize = 300;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReplayFrame {
    pub dx: f32,
    pub dy: f32,
    pub aim_x: f32,
    pub aim_y: f32,
    pub fire: bool,
    pub boost: bool,
    pub dash: bool,
    pub ultra: bool,
}

impl From<&SimInput> for ReplayFrame {
    fn from(i: &SimInput) -> Self {
        Self {
            dx: i.move_dir.x,
            dy: i.move_dir.y,
            aim_x: i.aim_world.x,
            aim_y: i.aim_world.y,
            fire: i.fire_held,
            boost: i.boost_held,
            dash: i.dash_pressed,
            ultra: i.ultra_pressed,
        }
    }
}

impl From<&ReplayFrame> for SimInput {
    fn from(f: &ReplayFrame) -> Self {
        Self {
            move_dir: Vec2::new(f.dx, f.dy),
            aim_world: Vec2::new(f.aim_x, f.aim_y),
            fire_held: f.fire,
            boost_held: f.boost,
            dash_pressed: f.dash,
            ultra_pressed: f.ultra,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RewardChoiceRecord {
    pub frame: usize,
    pub temp_key: String,
    pub temp_duration: i32,
    pub perm_key: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReplayCheckpoint {
    /// Number of fixed simulation steps completed when this state was captured.
    pub frame: usize,
    pub hash: String,
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Recording {
    pub version: u32,
    #[serde(default)]
    pub rules_version: u32,
    pub seed: u64,
    pub difficulty: String,
    pub map_type: String,
    pub skin: String,
    pub mutators: Vec<String>,
    pub view_w: u32,
    pub view_h: u32,
    pub arena_margin: f32,
    #[serde(default)]
    pub enable_obstacles: bool,
    #[serde(default)]
    pub enable_destructible_crates: bool,
    #[serde(default = "default_true")]
    pub auto_shoot: bool,
    pub frames: Vec<ReplayFrame>,
    pub rewards: Vec<RewardChoiceRecord>,
    #[serde(default)]
    pub checkpoints: Vec<ReplayCheckpoint>,
    pub final_hash: String,
}

fn state_hash_v2(state: &SimState) -> String {
    let payload = format!(
        "{:.4},{:.4},{},{},{},{},{},{}",
        state.player.pos.x,
        state.player.pos.y,
        state.player.hp,
        state.score.score,
        state.wave,
        state.enemies.len(),
        state.projectiles.len(),
        state.rng.state_fingerprint(),
    );
    let mut hasher = Sha256::new();
    hasher.update(payload.as_bytes());
    format!("{:x}", hasher.finalize())
}

/// Historical version-3 fingerprint retained for existing replay files.
fn state_hash_v3(state: &SimState) -> String {
    let mut payload = format!(
        "{:.4},{:.4},{},{},{},{},{},{},{}|",
        state.player.pos.x,
        state.player.pos.y,
        state.player.hp,
        state.score.score,
        state.wave,
        state.enemies.len(),
        state.projectiles.len(),
        state.rng.state_fingerprint(),
        state.runtime.enable_destructible_crates,
    );
    for obstacle in &state.obstacles {
        payload.push_str(&format!(
            "{:08x},{:08x},{:08x},{},{},{};",
            obstacle.pos.x.to_bits(),
            obstacle.pos.y.to_bits(),
            obstacle.radius.to_bits(),
            obstacle.kind,
            obstacle.hp,
            obstacle.max_hp,
        ));
    }
    let mut hasher = Sha256::new();
    hasher.update(payload.as_bytes());
    format!("{:x}", hasher.finalize())
}

/// Canonical version-4 fingerprint. Tuple order below is the schema order;
/// entity vectors retain simulation order. The only map held in SimState is
/// sorted explicitly before hashing so HashMap iteration cannot vary by process.
pub fn state_hash(state: &SimState) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"plouto-simulation-state-v4|");
    hasher.update(SIMULATION_RULES_VERSION.to_le_bytes());
    hasher.update(state.rng.state_fingerprint().as_bytes());

    let sections = [
        format!(
            "{:?}",
            (
                state.time,
                state.wave,
                &state.difficulty,
                &state.map_type,
                state.seed,
                &state.daily_date,
                &state.mutators,
                state.rules,
                &state.run_skin,
                &state.runtime,
                state.auto_shoot,
                state.next_entity_id,
            )
        ),
        format!(
            "{:?}",
            (
                state.enemy_spawn_count,
                state.enemy_time,
                state.room_radius,
                state.arena_margin,
                state.layout_seed,
                state.layout_segment,
                &state.obstacles,
                &state.player,
                state.max_enemies,
            )
        ),
        format!(
            "{:?}",
            (
                &state.enemies,
                &state.projectiles,
                &state.powerups,
                &state.traps,
                &state.lasers,
                &state.thunders,
            )
        ),
        format!(
            "{:?}",
            (
                &state.drone,
                &state.chain,
                &state.repulsor,
                &state.afterburn.segments,
                state.afterburn.next_drop_at,
                &state.shards,
                &state.echo_rings,
                &state.swarm_brain,
                &state.arena_event,
                &state.pity,
            )
        ),
        format!(
            "{:?}",
            (&state.perception_mem, &state.formation, &state.director)
        ),
        format!(
            "{:?}",
            (
                state.wave_active,
                state.last_wave_clear,
                state.enemy_combo_value,
                &state.enemy_combo_text,
                state.hitstop,
                state.shake,
                state.time_slow_was_on,
            )
        ),
        format!(
            "{:?}",
            (
                state.fanfare_stamp,
                state.shield_regen_carry,
                &state.active_temp_rewards,
                &state.temp_mods,
                &state.run_permanent_rewards,
                &state.last_reward_temp_key,
                &state.last_reward_perm_key,
            )
        ),
        format!(
            "{:?}",
            (
                state.dash_cd_mult,
                state.dash_cd_difficulty,
                state.incoming_damage_mult,
                &state.pending_boss_reward,
                &state.score,
                &state.run_stats,
                &state.pending_reflects,
                &state.pending_player_damage,
                state.chain_hops_this_step,
                state.game_over,
            )
        ),
    ];
    for section in sections {
        hasher.update((section.len() as u64).to_le_bytes());
        hasher.update(section.as_bytes());
    }

    let mut afterburn_ticks: Vec<(u64, u32)> = state
        .afterburn
        .last_tick_by_enemy
        .iter()
        .map(|(&enemy_id, &tick)| (enemy_id, tick.to_bits()))
        .collect();
    afterburn_ticks.sort_unstable_by_key(|&(enemy_id, _)| enemy_id);
    hasher.update(format!("afterburn_ticks={afterburn_ticks:?}").as_bytes());
    format!("{:x}", hasher.finalize())
}

#[derive(Debug, Clone)]
pub struct Recorder {
    pub seed: u64,
    pub difficulty: String,
    pub map_type: String,
    pub skin: String,
    pub mutators: Vec<String>,
    pub view_w: u32,
    pub view_h: u32,
    pub arena_margin: f32,
    pub enable_obstacles: bool,
    pub enable_destructible_crates: bool,
    pub auto_shoot: bool,
    pub frames: Vec<ReplayFrame>,
    pub rewards: Vec<RewardChoiceRecord>,
    pub checkpoints: Vec<ReplayCheckpoint>,
}

impl Recorder {
    pub fn from_state(state: &SimState, view_w: u32, view_h: u32) -> Self {
        Self {
            seed: state.seed,
            difficulty: state.difficulty.clone(),
            map_type: state.map_type.clone(),
            skin: state.run_skin.skin_id.clone(),
            mutators: state.mutators.clone(),
            view_w,
            view_h,
            arena_margin: state.arena_margin,
            enable_obstacles: state.runtime.enable_obstacles,
            enable_destructible_crates: state.runtime.enable_destructible_crates,
            auto_shoot: state.auto_shoot,
            frames: Vec::with_capacity(4096),
            rewards: Vec::new(),
            checkpoints: Vec::new(),
        }
    }

    pub fn push_frame(&mut self, input: &SimInput) {
        self.frames.push(ReplayFrame::from(input));
    }

    pub fn push_frame_with_state(&mut self, input: &SimInput, state: &SimState) {
        self.push_frame(input);
        if self.frames.len() % REPLAY_CHECKPOINT_INTERVAL == 0 {
            self.store_checkpoint(self.frames.len(), state_hash(state));
        }
    }

    pub fn push_reward(&mut self, temp_key: &str, temp_duration: i32, perm_key: &str) {
        self.rewards.push(RewardChoiceRecord {
            frame: self.frames.len(),
            temp_key: temp_key.to_string(),
            temp_duration,
            perm_key: perm_key.to_string(),
        });
    }

    pub fn push_reward_with_state(
        &mut self,
        temp_key: &str,
        temp_duration: i32,
        perm_key: &str,
        state: &SimState,
    ) {
        self.push_reward(temp_key, temp_duration, perm_key);
        let frame = self.frames.len();
        if frame % REPLAY_CHECKPOINT_INTERVAL == 0 {
            self.store_checkpoint(frame, state_hash(state));
        }
    }

    fn store_checkpoint(&mut self, frame: usize, hash: String) {
        if let Some(checkpoint) = self.checkpoints.iter_mut().find(|item| item.frame == frame) {
            checkpoint.hash = hash;
        } else {
            self.checkpoints.push(ReplayCheckpoint { frame, hash });
            self.checkpoints.sort_unstable_by_key(|item| item.frame);
        }
    }

    pub fn finalize(mut self, state: &SimState) -> Recording {
        self.store_checkpoint(self.frames.len(), state_hash(state));
        Recording {
            version: 4,
            rules_version: SIMULATION_RULES_VERSION,
            seed: self.seed,
            difficulty: self.difficulty,
            map_type: self.map_type,
            skin: self.skin,
            mutators: self.mutators,
            view_w: self.view_w,
            view_h: self.view_h,
            arena_margin: self.arena_margin,
            enable_obstacles: self.enable_obstacles,
            enable_destructible_crates: self.enable_destructible_crates,
            auto_shoot: self.auto_shoot,
            frames: self.frames,
            rewards: self.rewards,
            checkpoints: self.checkpoints,
            final_hash: state_hash(state),
        }
    }

    pub fn save_to_file(self, state: &SimState, path: &Path) -> Result<Recording, String> {
        let rec = self.finalize(state);
        let file = File::create(path).map_err(|e| format!("create replay file: {e}"))?;
        let writer = BufWriter::new(file);
        serde_json::to_writer_pretty(writer, &rec)
            .map_err(|e| format!("serialize replay: {e}"))?;
        Ok(rec)
    }
}

pub fn load_recording(path: &Path) -> Result<Recording, String> {
    let file = File::open(path).map_err(|e| format!("open replay file: {e}"))?;
    let reader = BufReader::new(file);
    serde_json::from_reader(reader).map_err(|e| format!("parse replay: {e}"))
}

pub struct ReplayVerification {
    pub frames_run: usize,
    pub actual_hash: String,
    pub expected_hash: String,
    pub matches: bool,
    pub final_wave: i32,
    pub final_score: i32,
    pub first_mismatch_frame: Option<usize>,
    pub error: Option<String>,
}

/// Deterministically execute a `Recording` at 60 Hz fixed dt and verify `state_hash`.
pub fn replay_and_verify(rec: &Recording) -> ReplayVerification {
    if rec.version > 4 {
        return ReplayVerification {
            frames_run: 0,
            actual_hash: String::new(),
            expected_hash: rec.final_hash.clone(),
            matches: false,
            final_wave: 0,
            final_score: 0,
            first_mismatch_frame: None,
            error: Some(format!("unsupported replay format version {}", rec.version)),
        };
    }
    if rec.version >= 4 && rec.rules_version != SIMULATION_RULES_VERSION {
        return ReplayVerification {
            frames_run: 0,
            actual_hash: String::new(),
            expected_hash: rec.final_hash.clone(),
            matches: false,
            final_wave: 0,
            final_score: 0,
            first_mismatch_frame: None,
            error: Some(format!(
                "replay uses simulation rules {}, this build supports {}",
                rec.rules_version, SIMULATION_RULES_VERSION
            )),
        };
    }
    if rec.version >= 4 {
        let mut previous_frame = 0;
        for checkpoint in &rec.checkpoints {
            if checkpoint.frame < previous_frame || checkpoint.frame > rec.frames.len() {
                return ReplayVerification {
                    frames_run: 0,
                    actual_hash: String::new(),
                    expected_hash: rec.final_hash.clone(),
                    matches: false,
                    final_wave: 0,
                    final_score: 0,
                    first_mismatch_frame: None,
                    error: Some("replay checkpoints are not in valid frame order".to_string()),
                };
            }
            previous_frame = checkpoint.frame;
        }
    }

    let mut runtime = RuntimeConfig::from_defaults();
    // Replay files may come from older builds that included arena obstacles. Keep every Rust
    // replay on the current open-arena rules, regardless of the recorded legacy setting.
    runtime.enable_obstacles = false;
    // Preserve this serialized bit for deterministic state hashes. With obstacles disabled it
    // cannot restore crates or other cover into the arena.
    runtime.enable_destructible_crates = rec.enable_destructible_crates;
    let setup = RunSetup {
        seed: rec.seed,
        difficulty: rec.difficulty.clone(),
        map_type: rec.map_type.clone(),
        skin_id: rec.skin.clone(),
        mutator_ids: rec.mutators.clone(),
        view_w: rec.view_w,
        view_h: rec.view_h,
        arena_margin: rec.arena_margin,
        runtime,
        auto_shoot: rec.auto_shoot,
        ..RunSetup::default()
    };
    let mut state = SimState::new(setup);
    let fixed_dt = 1.0_f32 / 60.0_f32;
    let mut reward_cursor = 0usize;
    let mut checkpoint_cursor = 0usize;

    while reward_cursor < rec.rewards.len() && rec.rewards[reward_cursor].frame == 0 {
        let rw = &rec.rewards[reward_cursor];
        apply_boss_temp_reward(&mut state, &rw.temp_key, rw.temp_duration);
        apply_boss_perm_reward(&mut state, &rw.perm_key);
        reward_cursor += 1;
    }
    while rec.version >= 4
        && checkpoint_cursor < rec.checkpoints.len()
        && rec.checkpoints[checkpoint_cursor].frame == 0
    {
        let checkpoint = &rec.checkpoints[checkpoint_cursor];
        let actual = state_hash(&state);
        if actual != checkpoint.hash {
            return ReplayVerification {
                frames_run: 0,
                actual_hash: actual,
                expected_hash: checkpoint.hash.clone(),
                matches: false,
                final_wave: state.wave,
                final_score: state.score.score,
                first_mismatch_frame: Some(0),
                error: None,
            };
        }
        checkpoint_cursor += 1;
    }

    for (frame_idx, frame) in rec.frames.iter().enumerate() {
        while reward_cursor < rec.rewards.len() && rec.rewards[reward_cursor].frame == frame_idx {
            let rw = &rec.rewards[reward_cursor];
            apply_boss_temp_reward(&mut state, &rw.temp_key, rw.temp_duration);
            apply_boss_perm_reward(&mut state, &rw.perm_key);
            reward_cursor += 1;
        }
        let input = SimInput::from(frame);
        step(&mut state, &input, fixed_dt);
        let completed_frame = frame_idx + 1;
        while reward_cursor < rec.rewards.len()
            && rec.rewards[reward_cursor].frame == completed_frame
        {
            let rw = &rec.rewards[reward_cursor];
            apply_boss_temp_reward(&mut state, &rw.temp_key, rw.temp_duration);
            apply_boss_perm_reward(&mut state, &rw.perm_key);
            reward_cursor += 1;
        }
        while rec.version >= 4
            && checkpoint_cursor < rec.checkpoints.len()
            && rec.checkpoints[checkpoint_cursor].frame == completed_frame
        {
            let checkpoint = &rec.checkpoints[checkpoint_cursor];
            let actual = state_hash(&state);
            if actual != checkpoint.hash {
                return ReplayVerification {
                    frames_run: completed_frame,
                    actual_hash: actual,
                    expected_hash: checkpoint.hash.clone(),
                    matches: false,
                    final_wave: state.wave,
                    final_score: state.score.score,
                    first_mismatch_frame: Some(completed_frame),
                    error: None,
                };
            }
            checkpoint_cursor += 1;
        }
    }

    while reward_cursor < rec.rewards.len() {
        let rw = &rec.rewards[reward_cursor];
        apply_boss_temp_reward(&mut state, &rw.temp_key, rw.temp_duration);
        apply_boss_perm_reward(&mut state, &rw.perm_key);
        reward_cursor += 1;
    }

    let actual_hash = if rec.version >= 4 {
        state_hash(&state)
    } else if rec.version >= 3 {
        state_hash_v3(&state)
    } else {
        state_hash_v2(&state)
    };
    let matches = rec.final_hash.is_empty() || actual_hash == rec.final_hash;
    ReplayVerification {
        frames_run: rec.frames.len(),
        matches,
        actual_hash,
        expected_hash: rec.final_hash.clone(),
        final_wave: state.wave,
        final_score: state.score.score,
        first_mismatch_frame: if matches || rec.version < 4 {
            None
        } else {
            Some(rec.frames.len())
        },
        error: None,
    }
}
