use std::collections::HashSet;
use std::fs::File;
use std::io::BufReader;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};

use winit::application::ApplicationHandler;
use winit::dpi::LogicalSize;
use winit::event::{ElementState, KeyEvent, MouseButton, WindowEvent};
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop};
use winit::keyboard::{KeyCode, PhysicalKey};
use winit::window::{Fullscreen, Icon, Window, WindowAttributes, WindowId};

use crate::assets::{resolve_asset, resolve_data_file};
use crate::audio::AudioManager;
use crate::input::gamepad::{GamepadManager, PadButton, PadEvent, PadSnapshot};
use crate::input::glyphs::InputDevice;
use crate::input::mapping::{
    apply_radial_deadzone, stick_to_aim_dir, stick_to_move, stick_to_nav, NavDir4, NavRepeat,
    AIM_DISTANCE, AIM_FIRE_THRESHOLD, TRIGGER_THRESHOLD,
};
use crate::input::rumble::{rumble_for_events, RumbleRequest};
use crate::render::bloom::PostFxUniform;
use crate::render::text::{AlignX, AlignY, FontId};
use crate::render::world::WorldRenderer;
use crate::render::{FrameRenderer, GpuContext};
use crate::save::progress::{
    end_run, ensure_progress_file, evaluate_live, load_progress, totals_of, EndRunSummary,
    ProgressData, RunContext,
};
use crate::save::scores::{ensure_high_scores_file, submit_score, top_score, SubmitOutcome};
use crate::save::settings::{load_settings, save_settings, UserSettings};
use crate::sim::achievements::{
    name_of, progress_of, AchCondition, AchTotals, AchievementDef, RunStats, ACHIEVEMENTS,
};
use crate::sim::config::RuntimeConfig;
use crate::sim::daily::{challenge_for_date, today_iso, DailyResult, DAILY_ARENA_MARGIN};
use crate::sim::math::Vec2;
use crate::sim::replay::Recorder;
use crate::sim::skins::get_skin;
use crate::sim::state::{RunSetup, SimInput, SimState};
use crate::sim::step::{apply_boss_perm_reward, apply_boss_temp_reward, step};
use crate::ui::hangar::{HangarAction, HangarScreen, NavDir};
use crate::ui::hud::HudState;
use crate::ui::screens::{
    AppScreen, BossRewardAction, BossRewardScreen, GameOverAction, GameOverScreen, GuideAction,
    GuideScreen, MenuAction, MenuScreen, PauseAction, PauseScreen, ScreenFade, SettingsAction,
    SettingsScreen,
};
use crate::ui::theme::{draw_panel, pt_px, ui_scale, UiRect, ACCENT, PANEL, TEXT};

const FIXED_DT: f32 = 1.0 / 60.0;
const MAX_SUBSTEPS: usize = 4;
/// Seconds between mid-run achievement checks (a check also runs when the wave changes).
const LIVE_CHECK_S: f32 = 0.5;
const RUMBLE_STOP: RumbleRequest = RumbleRequest {
    strong: 0.0,
    weak: 0.0,
    duration_ms: 0,
};

#[derive(Debug, Clone, Default)]
pub struct AppConfig {
    pub record_path: Option<PathBuf>,
}

pub fn run_desktop_game(config: AppConfig) -> Result<(), String> {
    let event_loop = EventLoop::new().map_err(|e| format!("create event loop failed: {e}"))?;
    event_loop.set_control_flow(ControlFlow::Poll);
    let mut app = PloutoApp::new(config);
    event_loop
        .run_app(&mut app)
        .map_err(|e| format!("event loop error: {e}"))
}

fn load_window_icon() -> Option<Icon> {
    let path = resolve_asset("laser-gun_38685.ico")?;
    let file = File::open(path).ok()?;
    let dir = ico::IconDir::read(BufReader::new(file)).ok()?;
    let entry = dir
        .entries()
        .iter()
        .max_by_key(|e| (e.width() as u32) * (e.height() as u32))?;
    let image = entry.decode().ok()?;
    let w = image.width();
    let h = image.height();
    let rgba = image.rgba_data().to_vec();
    Icon::from_rgba(rgba, w, h).ok()
}

struct PloutoApp {
    config: AppConfig,
    window: Option<Arc<Window>>,
    gpu: Option<GpuContext>,
    renderer: Option<FrameRenderer>,

    settings_path: PathBuf,
    progress_path: PathBuf,
    scores_path: PathBuf,

    settings: UserSettings,
    runtime_cfg: RuntimeConfig,
    progress: ProgressData,
    audio: AudioManager,

    screen: AppScreen,
    fade: ScreenFade,
    world: WorldRenderer,
    hud: HudState,
    menu: MenuScreen,
    settings_ui: SettingsScreen,
    guide: GuideScreen,
    hangar: HangarScreen,
    pause_ui: PauseScreen,
    boss_reward_ui: BossRewardScreen,
    game_over_ui: GameOverScreen,

    sim: Option<SimState>,
    recorder: Option<Recorder>,
    pending_temp_choice: Option<(&'static str, i32)>,
    game_over_settled: bool,
    /// Achievement ids already toasted during the current run (mid-run unlocks).
    live_toasted: Vec<&'static str>,
    /// Seconds since the last mid-run achievement check.
    live_check_acc: f32,
    /// Wave number seen at the last mid-run achievement check.
    live_check_wave: i32,

    keys: HashSet<KeyCode>,
    mouse_screen: [f32; 2],
    mouse_left_down: bool,
    dash_queued: bool,
    ultra_queued: bool,
    accumulator: f32,

    last_frame: Instant,
    elapsed_t: f32,
    show_perf_overlay: bool,
    fps_smooth: f32,
    sim_ms_smooth: f32,

    daily_date: String,
    daily_mut_id: String,

    gamepad: GamepadManager,
    nav_repeat: NavRepeat,
    input_device: InputDevice,
    last_aim_dir: Vec2,
    last_os_cursor: Option<[f32; 2]>,
    pad_last_t: Instant,
    /// When the currently playing rumble ends, used to rate-limit requests.
    rumble_until: Option<Instant>,
    /// Strength of the currently playing rumble (max of strong and weak).
    rumble_strength: f32,
}

impl PloutoApp {
    fn new(config: AppConfig) -> Self {
        let settings_path = resolve_data_file("user_settings.json");
        let progress_path = resolve_data_file("progress.json");
        let scores_path = resolve_data_file("high_scores.json");

        ensure_progress_file(&progress_path);
        ensure_high_scores_file(&scores_path);

        let settings = load_settings(&settings_path);
        let progress = load_progress(&progress_path);

        let mut runtime_cfg = RuntimeConfig::from_defaults();
        settings.apply_to_runtime(&mut runtime_cfg);

        let mut audio = AudioManager::new(settings.sfx_volume, settings.music_volume);
        audio.play_music(Some("menu"), 0.6);

        let settings_ui = SettingsScreen::new(
            settings.clone(),
            runtime_cfg.enable_advanced_fx,
            runtime_cfg.use_player_art,
        );
        let daily_date = today_iso();
        let daily_mut_id = challenge_for_date(&daily_date)
            .expect("UTC today is a valid daily challenge date")
            .mutator_id
            .to_string();

        Self {
            config,
            window: None,
            gpu: None,
            renderer: None,
            settings_path,
            progress_path,
            scores_path,
            settings,
            runtime_cfg,
            progress,
            audio,
            screen: AppScreen::Menu,
            fade: ScreenFade::new(),
            world: WorldRenderer::new(),
            hud: HudState::new(),
            menu: MenuScreen::new(),
            settings_ui,
            guide: GuideScreen::new(),
            hangar: HangarScreen::new(),
            pause_ui: PauseScreen::new(),
            boss_reward_ui: BossRewardScreen::new(),
            game_over_ui: GameOverScreen::new(),
            sim: None,
            recorder: None,
            pending_temp_choice: None,
            game_over_settled: false,
            live_toasted: Vec::new(),
            live_check_acc: 0.0,
            live_check_wave: 0,
            keys: HashSet::new(),
            mouse_screen: [490.0, 310.0],
            mouse_left_down: false,
            dash_queued: false,
            ultra_queued: false,
            accumulator: 0.0,
            last_frame: Instant::now(),
            elapsed_t: 0.0,
            show_perf_overlay: false,
            fps_smooth: 60.0,
            sim_ms_smooth: 0.0,
            daily_date,
            daily_mut_id,
            gamepad: GamepadManager::new(),
            nav_repeat: NavRepeat::new(),
            input_device: InputDevice::default(),
            last_aim_dir: Vec2::new(1.0, 0.0),
            last_os_cursor: None,
            pad_last_t: Instant::now(),
            rumble_until: None,
            rumble_strength: 0.0,
        }
    }

    fn view_size(&self) -> (u32, u32) {
        self.gpu.as_ref().map(|g| g.size).unwrap_or((1280, 720))
    }

    fn sync_cursor_visibility(&self) {
        if let Some(win) = &self.window {
            win.set_cursor_visible(self.screen != AppScreen::Playing);
        }
    }

    fn enter_screen(&mut self, next: AppScreen) {
        self.clear_transient_input();
        self.screen = next;
        match next {
            AppScreen::Menu => {
                self.menu.replay_intro(self.settings.reduced_motion);
                self.flush_recorder();
                self.sim = None;
                self.audio.duck(1.0, 0.2);
                self.audio.play_music(Some("menu"), 0.5);
                self.daily_date = today_iso();
                self.daily_mut_id = challenge_for_date(&self.daily_date)
                    .expect("UTC today is a valid daily challenge date")
                    .mutator_id
                    .to_string();
                self.progress = load_progress(&self.progress_path);
            }
            AppScreen::Hangar => {
                self.hangar.open(&self.progress_path);
            }
            AppScreen::Guide => {
                self.guide.open();
            }
            AppScreen::Settings => {
                self.settings_ui.settings = self.settings.clone();
                self.settings_ui.enable_advanced_fx = self.runtime_cfg.enable_advanced_fx;
                self.settings_ui.use_player_art = self.runtime_cfg.use_player_art;
            }
            AppScreen::Paused => {
                self.pause_ui.open();
                self.audio.duck(0.38, 0.25);
            }
            AppScreen::Playing => {
                self.audio.duck(1.0, 0.25);
            }
            AppScreen::BossReward => {
                self.audio.duck(0.45, 0.25);
            }
            AppScreen::GameOver => {
                self.audio.duck(1.0, 0.2);
                self.audio.play_music(Some("game_over"), 0.35);
            }
        }
        self.sync_cursor_visibility();
    }

    fn clear_transient_input(&mut self) {
        self.keys.clear();
        self.mouse_left_down = false;
        self.dash_queued = false;
        self.ultra_queued = false;
        self.nav_repeat = NavRepeat::new();
        self.rumble_until = None;
        self.rumble_strength = 0.0;
        self.gamepad.rumble(RUMBLE_STOP);
    }

    /// Plays a rumble request unless a stronger one is still running. Equal or
    /// weaker requests are dropped while the current one plays, so per-frame
    /// events (repeated hits, several sim substeps) do not restart the motors.
    fn request_rumble(&mut self, req: RumbleRequest) {
        let now = Instant::now();
        let strength = req.strong.max(req.weak);
        let busy = matches!(self.rumble_until, Some(t) if now < t);
        if busy && strength <= self.rumble_strength {
            return;
        }
        self.rumble_until = Some(now + Duration::from_millis(u64::from(req.duration_ms)));
        self.rumble_strength = strength;
        self.gamepad.rumble(req);
    }

    fn transition_menu_screen(&mut self, next: AppScreen) {
        self.audio.cue("menu_click", 0.85);
        if let Some((target, _)) = self.fade.trigger(next, false, self.settings.reduced_motion) {
            self.enter_screen(target);
        }
    }

    fn start_run(&mut self, daily: bool) {
        self.flush_recorder();
        self.progress = load_progress(&self.progress_path);
        let (view_w, view_h) = self.view_size();

        let (seed, mutator_ids, daily_date, difficulty, map_type, arena_margin) = if daily {
            let today = today_iso();
            let challenge = challenge_for_date(&today)
                .expect("UTC today is a valid daily challenge date");
            (
                challenge.seed,
                vec![challenge.mutator_id.to_string()],
                Some(challenge.date_iso),
                challenge.difficulty.to_string(),
                challenge.map_type.to_string(),
                DAILY_ARENA_MARGIN,
            )
        } else {
            let s = rand::random::<u64>() | 1;
            (
                s,
                self.settings.mutators.clone(),
                None,
                self.settings.difficulty.clone(),
                self.settings.map_type.clone(),
                self.settings.arena_margin,
            )
        };

        let mut rt = RuntimeConfig::from_defaults();
        self.settings.apply_to_runtime(&mut rt);
        rt.arena_margin = arena_margin;
        rt.enable_advanced_fx = self.settings_ui.enable_advanced_fx;
        rt.use_player_art = self.settings_ui.use_player_art;
        self.runtime_cfg = rt.clone();

        let setup = RunSetup {
            seed,
            difficulty,
            map_type,
            skin_id: self.progress.selected_skin.clone(),
            mutator_ids,
            daily_date,
            view_w,
            view_h,
            arena_margin,
            auto_shoot: self.settings.auto_shoot,
            runtime: rt,
        };

        let state = SimState::new(setup);
        self.world.reset(&state);
        self.hud.reset();

        if self.config.record_path.is_some() {
            self.recorder = Some(Recorder::from_state(&state, view_w, view_h));
        }
        self.sim = Some(state);
        self.pending_temp_choice = None;
        self.game_over_settled = false;
        self.live_toasted.clear();
        self.live_check_acc = 0.0;
        self.live_check_wave = 0;
        self.clear_transient_input();
        self.accumulator = 0.0;
        self.audio.duck(1.0, 0.25);
        self.audio.play_music(Some("game"), 0.45);
        self.screen = AppScreen::Playing;
        self.sync_cursor_visibility();
    }

    fn flush_recorder(&mut self) {
        if let (Some(rec), Some(path), Some(sim)) = (
            self.recorder.take(),
            self.config.record_path.as_ref(),
            self.sim.as_ref(),
        ) {
            if let Err(err) = rec.save_to_file(sim, path) {
                eprintln!("[replay] failed to write {}: {err}", path.display());
            }
        }
    }

    /// Death: settles the run and shows the game-over screen.
    fn settle_game_over(&mut self) {
        let Some(res) = self.settle_run() else {
            return;
        };
        let confirm_held = self.is_confirm_held();
        self.game_over_ui.open(
            res.score,
            res.wave,
            res.survived_s,
            res.kills,
            res.best_combo,
            &res.outcome,
            &res.mutator_ids,
            res.daily.as_ref(),
            &res.unlocked,
            &res.near,
            confirm_held,
        );
        self.enter_screen(AppScreen::GameOver);
    }

    /// The player left a run without dying (pause-menu quit or window close). The run counts
    /// like a death, but no game-over screen follows. Does nothing when there is no unsettled run.
    fn abandon_run(&mut self) {
        let _ = self.settle_run();
    }

    /// Pause-menu quit: settles the run, then goes to the main menu.
    fn quit_run_to_menu(&mut self) {
        self.abandon_run();
        self.enter_screen(AppScreen::Menu);
    }

    /// Settles the current run exactly once: finishes its stats, submits the high score, saves
    /// progress and queues unlock toasts. Returns `None` when there is no run or it already settled.
    fn settle_run(&mut self) -> Option<RunSettlement> {
        if self.game_over_settled || self.sim.is_none() {
            return None;
        }
        self.game_over_settled = true;

        // The recording is written before `finish`, so its hash matches a replay that never
        // calls `finish` itself. On death the sim has already finished, and `finish` is idempotent.
        self.flush_recorder();

        // Progress as it was before this run, for near-miss totals.
        let progress_before = self.progress.clone();
        let skip_progress = self.config.record_path.is_some();

        let sim = self.sim.as_mut()?;
        sim.run_stats.finish(
            sim.score.score,
            sim.wave,
            sim.time,
            Some(sim.score.best_combo),
        );
        let outcome = submit_score(&self.scores_path, &mut sim.score, sim.wave, None);

        // Mutator count and daily flag come from the run, not from the replay-hashed RunStats.
        let ctx = RunContext {
            daily_date: sim.daily_date.clone(),
            mutators: sim.mutators.clone(),
        };
        let mut view = sim.run_stats.clone();
        let mutator_count = if ctx.mutators.is_empty() {
            view.mutator_count
        } else {
            ctx.mutators.len().min(i32::MAX as usize) as i32
        };
        view.set_run_context(mutator_count, ctx.daily_date.is_some());

        let score = sim.score.score;
        let wave = sim.wave;
        let survived_s = sim.time;
        let kills = sim.score.kills;
        let best_combo = sim.score.best_combo;
        let mutator_ids = sim.mutators.clone();

        // Recording runs are developer captures, so they do not write the player's progress.
        let summary = if skip_progress {
            None
        } else {
            Some(end_run(&sim.run_stats, &ctx, &self.progress_path))
        };

        let mut unlocked: Vec<String> = Vec::new();
        let mut daily: Option<DailyResult> = None;
        if let Some(summary) = summary {
            let EndRunSummary {
                saved,
                progress,
                new_achievements,
                new_skins,
                daily: daily_outcome,
            } = summary;
            if saved {
                self.progress = progress;
                for id in new_achievements {
                    unlocked.push(name_of(id).to_string());
                    // Mid-run toasts already announced this one.
                    if !self.live_toasted.contains(&id) {
                        self.hud.toasts.push("Achievement Unlocked", name_of(id));
                    }
                }
                for skin_id in new_skins {
                    let sname = get_skin(skin_id).map(|s| s.name).unwrap_or(skin_id);
                    self.hud.toasts.push("Skin Unlocked", sname);
                }
                daily = daily_outcome;
            } else {
                self.hud.toasts.push(
                    "Progress Not Saved",
                    "progress.json could not be written. Check the file and its folder.",
                );
            }
        }

        let totals = totals_of(&progress_before).projected(&view);
        let near = near_misses(&view, &totals, &self.progress.achievements);

        Some(RunSettlement {
            score,
            wave,
            survived_s,
            kills,
            best_combo,
            outcome,
            mutator_ids,
            daily,
            unlocked,
            near,
        })
    }

    /// Mid-run unlocks: checks the live run every `LIVE_CHECK_S` seconds and when the wave
    /// changes, and toasts each newly earned achievement once. Only runs while playing.
    fn check_live_unlocks(&mut self, dt: f32) {
        // Recording runs never save progress, so they announce no unlocks.
        if self.config.record_path.is_some() {
            return;
        }
        self.live_check_acc += dt;
        let Some(sim) = self.sim.as_ref() else {
            return;
        };
        let wave = sim.wave;
        if self.live_check_acc < LIVE_CHECK_S && wave == self.live_check_wave {
            return;
        }
        self.live_check_acc = 0.0;
        self.live_check_wave = wave;

        let mut run = sim.run_stats.clone();
        run.wave = wave;
        run.score = sim.score.score;
        run.survived_s = sim.time;
        run.best_combo = run.best_combo.max(sim.score.best_combo);
        let ctx = RunContext {
            daily_date: sim.daily_date.clone(),
            mutators: sim.mutators.clone(),
        };

        for id in evaluate_live(&run, &ctx, &self.progress) {
            if self.live_toasted.contains(&id) {
                continue;
            }
            self.live_toasted.push(id);
            self.hud.toasts.push("Achievement Unlocked", name_of(id));
        }
    }

    fn is_confirm_held(&self) -> bool {
        self.keys.contains(&KeyCode::Enter)
            || self.keys.contains(&KeyCode::NumpadEnter)
            || self.keys.contains(&KeyCode::Space)
            || self.pad_held(PadButton::South)
    }

    /// Gamepad support is on in the settings.
    fn gamepad_on(&self) -> bool {
        self.settings.gamepad_enabled
    }

    /// Gamepad support is on and the pad is the active input device.
    fn gamepad_mode(&self) -> bool {
        self.gamepad_on() && self.input_device == InputDevice::Gamepad
    }

    /// Snapshot of the pad, or neutral values when gamepad support is off.
    fn pad_snapshot(&self) -> PadSnapshot {
        if self.gamepad_on() {
            self.gamepad.snapshot()
        } else {
            PadSnapshot::default()
        }
    }

    fn pad_held(&self, b: PadButton) -> bool {
        self.gamepad_on() && self.gamepad.is_held(b)
    }

    /// Reads gamepad events, then feeds the menu navigation repeat and the
    /// button-to-key translation. Runs from `about_to_wait`, which has the
    /// event loop that `handle_key_press` needs.
    fn pump_gamepad(&mut self, event_loop: &ActiveEventLoop) {
        let now = Instant::now();
        let dt = (now - self.pad_last_t).as_secs_f32().clamp(0.0, 0.1);
        self.pad_last_t = now;

        // Always drain gilrs, even while disabled, so stale presses do not
        // queue up and fire the moment support is switched back on.
        let events = self.gamepad.poll();
        if !self.gamepad_on() {
            return;
        }

        for ev in events {
            match ev {
                PadEvent::Pressed(btn) => {
                    self.input_device = InputDevice::Gamepad;
                    let playing = self.screen == AppScreen::Playing;
                    let on_menu = self.screen == AppScreen::Menu;
                    if let Some(code) = pad_button_key(btn, playing, on_menu) {
                        self.handle_key_press(code, false, event_loop);
                    }
                }
                // Connected does not switch device: an idle pad that is merely
                // plugged in (or reported at startup) must not take over aiming.
                PadEvent::Released(_) => {
                    self.input_device = InputDevice::Gamepad;
                }
                PadEvent::Connected(_) => {}
                PadEvent::Disconnected => {
                    self.input_device = InputDevice::KeyboardMouse;
                }
            }
        }

        let pad = self.gamepad.snapshot();
        if stick_mag(pad.left) > AIM_FIRE_THRESHOLD
            || stick_mag(pad.right) > AIM_FIRE_THRESHOLD
            || pad.left_trigger > TRIGGER_THRESHOLD
            || pad.right_trigger > TRIGGER_THRESHOLD
        {
            self.input_device = InputDevice::Gamepad;
        }

        if self.screen == AppScreen::Playing || self.fade.active {
            self.nav_repeat.update(None, dt);
            return;
        }

        // D-pad and left stick both drive menu navigation through one repeat path,
        // so a D-pad press is never handled twice.
        let dir = dpad_dir(&pad).or_else(|| stick_to_nav(pad.left));
        if dir.is_some() {
            self.input_device = InputDevice::Gamepad;
        }
        if let Some(d) = self.nav_repeat.update(dir, dt) {
            let code = match d {
                NavDir4::Up => KeyCode::ArrowUp,
                NavDir4::Down => KeyCode::ArrowDown,
                NavDir4::Left => KeyCode::ArrowLeft,
                NavDir4::Right => KeyCode::ArrowRight,
            };
            self.handle_key_press(code, false, event_loop);
        }
    }

    fn apply_settings_change(
        &mut self,
        resize_window: Option<(u32, u32)>,
        toggle_fullscreen: Option<bool>,
        arena_resized: bool,
    ) {
        self.settings = self.settings_ui.settings.clone();
        self.settings.apply_to_runtime(&mut self.runtime_cfg);
        self.runtime_cfg.enable_advanced_fx = self.settings_ui.enable_advanced_fx;
        self.runtime_cfg.use_player_art = self.settings_ui.use_player_art;

        self.audio
            .set_volumes(Some(self.settings.music_volume), Some(self.settings.sfx_volume));
        save_settings(&self.settings_path, &self.settings);

        if let Some(win) = &self.window {
            if let Some(fs) = toggle_fullscreen {
                win.set_fullscreen(if fs {
                    Some(Fullscreen::Borderless(None))
                } else {
                    None
                });
            }
            if let Some((w, h)) = resize_window {
                let _ = win.request_inner_size(LogicalSize::new(w, h));
            }
        }

        let (w, h) = self.view_size();
        if let Some(sim) = &mut self.sim {
            sim.runtime = self.runtime_cfg.clone();
            sim.auto_shoot = self.settings.auto_shoot;
            if arena_resized {
                sim.on_view_resized(w, h, self.settings.arena_margin);
            }
        }
    }

    fn build_sim_input(&mut self, state: &SimState, view_w: u32, view_h: u32) -> SimInput {
        let mut mx = 0.0_f32;
        let mut my = 0.0_f32;
        if self.keys.contains(&KeyCode::KeyA) || self.keys.contains(&KeyCode::ArrowLeft) {
            mx -= 1.0;
        }
        if self.keys.contains(&KeyCode::KeyD) || self.keys.contains(&KeyCode::ArrowRight) {
            mx += 1.0;
        }
        if self.keys.contains(&KeyCode::KeyW) || self.keys.contains(&KeyCode::ArrowUp) {
            my += 1.0;
        }
        if self.keys.contains(&KeyCode::KeyS) || self.keys.contains(&KeyCode::ArrowDown) {
            my -= 1.0;
        }
        let mut move_dir = if mx != 0.0 || my != 0.0 {
            Vec2::new(mx, my).normalized()
        } else {
            Vec2::ZERO
        };

        let mut aim_world = crate::sim::math::iso_to_world_cam(
            self.mouse_screen[0],
            self.mouse_screen[1],
            self.world.cam_world,
            view_w as f32,
            view_h as f32,
        );
        let mut boost_held = self.keys.contains(&KeyCode::ShiftLeft)
            || self.keys.contains(&KeyCode::ShiftRight);
        let mut fire_held = self.mouse_left_down || state.auto_shoot;

        if self.gamepad_mode() {
            let pad = self.pad_snapshot();
            let dz = self.settings.gamepad_deadzone;
            // Keyboard movement wins when a key is held, otherwise the left stick.
            if mx == 0.0 && my == 0.0 {
                move_dir = stick_to_move(pad.left, dz);
            }
            // The aim direction holds its last value while the right stick is centred.
            if let Some(dir) = stick_to_aim_dir(pad.right, dz) {
                self.last_aim_dir = dir;
            }
            let aim_point = state.player.pos + self.last_aim_dir * AIM_DISTANCE;
            let (sx, sy) = crate::sim::math::to_iso_cam(
                aim_point,
                self.world.cam_world,
                view_w as f32,
                view_h as f32,
                Vec2::ZERO,
            );
            // Keep the reticle and camera code following the virtual aim point.
            self.mouse_screen = [sx, sy];
            aim_world = aim_point;

            let r = apply_radial_deadzone(pad.right, dz);
            if stick_mag(r) > AIM_FIRE_THRESHOLD
                || pad.right_trigger > TRIGGER_THRESHOLD
                || self.pad_held(PadButton::RightBumper)
            {
                fire_held = true;
            }
            if pad.left_trigger > TRIGGER_THRESHOLD || self.pad_held(PadButton::LeftBumper) {
                boost_held = true;
            }
        }

        let dash_pressed = std::mem::take(&mut self.dash_queued);
        let ultra_pressed = std::mem::take(&mut self.ultra_queued);

        SimInput {
            move_dir,
            aim_world,
            fire_held,
            boost_held,
            dash_pressed,
            ultra_pressed,
        }
    }

    fn step_frame(&mut self) {
        let now = Instant::now();
        let raw_dt = (now - self.last_frame).as_secs_f32();
        self.last_frame = now;
        let dt = raw_dt.clamp(0.0, 0.1);
        self.elapsed_t += dt;

        if raw_dt > 0.0001 {
            let inst_fps = (1.0 / raw_dt).clamp(5.0, 1000.0);
            self.fps_smooth += (inst_fps - self.fps_smooth) * 0.12;
        }

        self.audio.update(dt);

        if self.screen == AppScreen::Menu {
            let utc_today = today_iso();
            if self.daily_date != utc_today {
                let challenge = challenge_for_date(&utc_today)
                    .expect("UTC today is a valid daily challenge date");
                self.daily_date = challenge.date_iso;
                self.daily_mut_id = challenge.mutator_id.to_string();
            }
        }

        if let Some((target, daily)) = self.fade.update(dt) {
            match target {
                AppScreen::Playing => self.start_run(daily),
                other => self.enter_screen(other),
            }
        }

        let (view_w, view_h) = self.view_size();
        let rm = self.settings.reduced_motion;
        self.menu.input_device = if self.gamepad_on() {
            self.input_device
        } else {
            InputDevice::KeyboardMouse
        };

        match self.screen {
            AppScreen::Menu => {
                self.menu.update(dt, view_w, view_h, rm);
            }
            AppScreen::Settings => {
                self.settings_ui.update(dt, view_w, view_h);
            }
            AppScreen::Guide => {
                self.guide.update(dt, view_w, view_h, rm);
            }
            AppScreen::Hangar => {
                self.hangar.update(dt, view_w, view_h, rm);
            }
            AppScreen::Paused => {
                self.pause_ui.update(dt, view_w, view_h, rm);
            }
            AppScreen::BossReward => {
                self.boss_reward_ui.update(dt, view_w, view_h, rm);
            }
            AppScreen::GameOver => {
                self.world.tick_visual_dt(dt);
                if let (Some(sim), Some(gpu)) = (&self.sim, &self.gpu) {
                    let (vw, vh) = gpu.size;
                    self.world.update_camera(sim, vw as f32, vh as f32, None, dt);
                }
                if let Some(sim) = &self.sim {
                    self.hud.update(sim, dt);
                }
                let held = self.is_confirm_held();
                self.game_over_ui.update(dt, view_w, view_h, held, rm);
            }
            AppScreen::Playing => {
                self.accumulator = (self.accumulator + dt).min(FIXED_DT * (MAX_SUBSTEPS as f32));
                let mut steps = 0usize;
                let sim_t0 = Instant::now();

                while self.accumulator >= FIXED_DT && steps < MAX_SUBSTEPS {
                    let Some(mut sim) = self.sim.take() else {
                        break;
                    };
                    let input = self.build_sim_input(&sim, view_w, view_h);
                    self.world.capture_prev(&sim);
                    let events = step(&mut sim, &input, FIXED_DT);
                    if let Some(rec) = &mut self.recorder {
                        rec.push_frame_with_state(&input, &sim);
                    }
                    self.audio.handle_sim_events(&events);
                    if self.gamepad_mode() && self.settings.gamepad_vibration {
                        if let Some(req) = rumble_for_events(&events) {
                            self.request_rumble(req);
                        }
                    }
                    self.world
                        .on_step_post(&sim, &events, view_w as f32, view_h as f32);

                    let boss_offer = sim.pending_boss_reward.clone();
                    let is_over = sim.game_over;
                    self.sim = Some(sim);
                    self.accumulator -= FIXED_DT;
                    steps += 1;

                    // A run that ended on this step never offers a boss reward.
                    if is_over {
                        self.settle_game_over();
                        break;
                    }
                    if let Some(offer) = boss_offer {
                        let (active_temp, run_perms) = self
                            .sim
                            .as_ref()
                            .map(|state| {
                                (
                                    state.active_temp_rewards.clone(),
                                    state.run_permanent_rewards.clone(),
                                )
                            })
                            .unwrap_or_default();
                        self.boss_reward_ui.open_with_context(
                            &offer.temp_options,
                            &offer.perm_options,
                            &active_temp,
                            &run_perms,
                        );
                        self.enter_screen(AppScreen::BossReward);
                        break;
                    }
                }

                if self.screen == AppScreen::Playing {
                    self.check_live_unlocks(dt);
                }

                let sim_ms = sim_t0.elapsed().as_secs_f32() * 1000.0;
                self.sim_ms_smooth += (sim_ms - self.sim_ms_smooth) * 0.15;

                self.world.tick_visual_dt(dt);
                if let (Some(sim), Some(gpu)) = (&self.sim, &self.gpu) {
                    let (vw, vh) = gpu.size;
                    self.world.update_camera(sim, vw as f32, vh as f32, Some(self.mouse_screen), dt);
                }
                if let Some(sim) = &self.sim {
                    self.hud.update(sim, dt);
                }
            }
        }

        self.render_frame();
    }

    fn render_frame(&mut self) {
        let Some(gpu) = self.gpu.as_mut() else {
            return;
        };
        let Some(renderer) = self.renderer.as_mut() else {
            return;
        };

        let (view_w, view_h) = gpu.size;
        let wf = view_w as f32;
        let hf = view_h as f32;
        let rm = self.settings.reduced_motion;

        renderer.begin_frame();

        let mut post_state = crate::render::world::WorldPostState {
            combat_intensity: 0.0,
            low_hp_danger: 0.0,
            boss_active: 0.0,
        };

        let is_world_screen = matches!(
            self.screen,
            AppScreen::Playing | AppScreen::Paused | AppScreen::BossReward | AppScreen::GameOver
        );

        if is_world_screen {
            if let Some(sim) = &self.sim {
                let alpha = if self.screen == AppScreen::Playing {
                    (self.accumulator / FIXED_DT).clamp(0.0, 1.0)
                } else {
                    1.0
                };
                let aim_world = crate::sim::math::iso_to_world_cam(
                    self.mouse_screen[0],
                    self.mouse_screen[1],
                    self.world.cam_world,
                    wf,
                    hf,
                );
                let aim_delta = aim_world - sim.player.pos;
                let aim_dir = if aim_delta.length_squared() > 1e-6 {
                    aim_delta.normalized()
                } else {
                    Vec2::new(1.0, 0.0)
                };

                let show_reticle = self.screen == AppScreen::Playing;
                let s = ui_scale(view_w, view_h);
                post_state = self.world.draw_world(
                    sim,
                    alpha,
                    wf,
                    hf,
                    aim_dir,
                    Some(self.mouse_screen),
                    show_reticle,
                    &mut renderer.world_alpha,
                    &mut renderer.world_add,
                    &mut renderer.ui_alpha,
                    &mut renderer.ui_text,
                    s,
                );
                self.hud.draw_with_badges(
                    sim,
                    self.world.particles.banners.front(),
                    view_w,
                    view_h,
                    &mut renderer.ui_alpha,
                    Some(&mut renderer.ui_add),
                    &mut renderer.ui_text,
                    &renderer.text.fonts,
                );
            }
        } else {
            self.world.draw_menu_backdrop(
                &mut renderer.world_alpha,
                &mut renderer.world_add,
                wf,
                hf,
                1.0 / 60.0,
                rm,
            );
        }

        // Foreground UI Screens
        match self.screen {
            AppScreen::Menu => {
                let best = top_score(&self.scores_path, &self.settings.difficulty);
                let daily_entry = self.progress.daily.get(&self.daily_date);
                self.menu.draw(
                    &mut renderer.ui_alpha,
                    &mut renderer.ui_add,
                    &mut renderer.ui_text,
                    &renderer.text.fonts,
                    view_w,
                    view_h,
                    best,
                    &self.settings.difficulty,
                    &self.daily_date,
                    &self.daily_mut_id,
                    daily_entry,
                    &self.settings.mutators,
                    rm,
                );
            }
            AppScreen::Settings => {
                self.settings_ui.draw(
                    &mut renderer.ui_alpha,
                    &mut renderer.ui_text,
                    view_w,
                    view_h,
                );
            }
            AppScreen::Guide => {
                self.guide.draw(
                    &mut renderer.ui_alpha,
                    &mut renderer.ui_add,
                    &mut renderer.ui_text,
                    &renderer.text.fonts,
                    view_w,
                    view_h,
                    self.settings.colorblind_palette,
                );
            }
            AppScreen::Hangar => {
                self.hangar.draw(
                    &mut renderer.ui_alpha,
                    &mut renderer.ui_add,
                    &mut renderer.ui_text,
                    &renderer.text.fonts,
                    view_w,
                    view_h,
                );
            }
            AppScreen::Paused => {
                self.pause_ui.draw(
                    &mut renderer.ui_alpha,
                    &mut renderer.ui_text,
                    view_w,
                    view_h,
                );
            }
            AppScreen::BossReward => {
                self.boss_reward_ui.draw(
                    &mut renderer.ui_alpha,
                    &mut renderer.ui_add,
                    &mut renderer.ui_text,
                    &renderer.text.fonts,
                    view_w,
                    view_h,
                    rm,
                );
            }
            AppScreen::GameOver => {
                self.game_over_ui.draw(
                    &mut renderer.ui_alpha,
                    &mut renderer.ui_text,
                    view_w,
                    view_h,
                    rm,
                );
            }
            AppScreen::Playing => {}
        }

        // Optional F3 performance corner overlay
        if self.show_perf_overlay {
            let s = ui_scale(view_w, view_h);
            let box_w = 178.0 * s;
            let box_h = 26.0 * s;
            let r = UiRect::new(wf - box_w - 14.0 * s, 14.0 * s, box_w, box_h);
            draw_panel(&mut renderer.ui_alpha, r, 5.0 * s, 1.2, PANEL, 220, ACCENT, 130, 0.0);
            let entities = self.sim.as_ref().map(|st| st.enemies.len() + st.projectiles.len()).unwrap_or(0);
            renderer.ui_text.draw(
                format!("{:.0} FPS · sim {:.2}ms · {entities} ent", self.fps_smooth, self.sim_ms_smooth),
                FontId::Regular,
                pt_px(9.5, s, 8.0),
                r.x + r.w * 0.5,
                r.y + r.h * 0.5,
                AlignX::Center,
                AlignY::Center,
                TEXT,
                245,
                false,
            );
        }

        // Build PostFx uniform & submit GPU pass
        let fl = &self.world.particles.flashes;
        let postfx = PostFxUniform {
            resolution: [wf, hf],
            texel_size: [1.0 / wf.max(1.0), 1.0 / hf.max(1.0)],
            time: self.elapsed_t,
            fx_strength: if self.runtime_cfg.enable_advanced_fx {
                self.runtime_cfg.advanced_fx_strength
            } else {
                0.0
            },
            combat_intensity: post_state.combat_intensity,
            low_hp_danger: post_state.low_hp_danger,
            boss_active: post_state.boss_active,
            reduce_motion: if rm { 1.0 } else { 0.0 },
            hit_flash: fl.hit_flash,
            ultra_flash: fl.ultra_flash,
            dash_pulse: fl.dash_pulse,
            boost_pulse: fl.boost_pulse,
            boss_flash: fl.boss_flash,
            fade_alpha: self.fade.alpha,
            threshold: 0.72,
            bloom_intensity: if self.runtime_cfg.enable_glow { 0.62 } else { 0.14 },
            is_srgb_output: if gpu.config.format.is_srgb() { 1.0 } else { 0.0 },
            _pad: 0.0,
        };

        if let Err(err) = renderer.submit_frame(gpu, postfx) {
            eprintln!("[render] frame submit warning: {err}");
        }
    }

    fn toggle_fullscreen(&mut self) {
        self.settings.fullscreen = !self.settings.fullscreen;
        if let Some(win) = &self.window {
            win.set_fullscreen(if self.settings.fullscreen {
                Some(Fullscreen::Borderless(None))
            } else {
                None
            });
        }
        save_settings(&self.settings_path, &self.settings);
    }

    fn handle_mouse_press(&mut self, button: MouseButton, event_loop: &ActiveEventLoop) {
        if self.fade.active {
            return;
        }
        let (view_w, view_h) = self.view_size();
        let [mx, my] = self.mouse_screen;

        match button {
            MouseButton::Left => {
                self.mouse_left_down = true;
                match self.screen {
                    AppScreen::Playing => {}
                    AppScreen::Menu => {
                        match self.menu.on_mouse_press(
                            mx,
                            my,
                            view_w,
                            view_h,
                            &self.settings.mutators,
                        ) {
                            MenuAction::Play => {
                                if let Some((t, d)) = self.fade.trigger(AppScreen::Playing, false, self.settings.reduced_motion) {
                                    let _ = t;
                                    self.start_run(d);
                                }
                            }
                            MenuAction::PlayDaily => {
                                if let Some((t, d)) = self.fade.trigger(AppScreen::Playing, true, self.settings.reduced_motion) {
                                    let _ = t;
                                    self.start_run(d);
                                }
                            }
                            MenuAction::OpenHangar => {
                                self.transition_menu_screen(AppScreen::Hangar);
                            }
                            MenuAction::OpenSettings => {
                                self.transition_menu_screen(AppScreen::Settings);
                            }
                            MenuAction::OpenGuide => {
                                self.transition_menu_screen(AppScreen::Guide);
                            }
                            MenuAction::Quit => {
                                event_loop.exit();
                            }
                            MenuAction::MutatorsChanged(next) => {
                                self.settings.mutators = next;
                                save_settings(&self.settings_path, &self.settings);
                                self.audio.cue("menu_click", 1.0);
                            }
                            MenuAction::None => {}
                        }
                    }
                    AppScreen::Settings => {
                        match self.settings_ui.on_mouse_press(mx, my, view_w, view_h) {
                            SettingsAction::Back => {
                                self.transition_menu_screen(AppScreen::Menu);
                            }
                            SettingsAction::Changed {
                                resize_window,
                                toggle_fullscreen,
                                arena_resized,
                            } => {
                                self.apply_settings_change(resize_window, toggle_fullscreen, arena_resized);
                            }
                            SettingsAction::None => {}
                        }
                    }
                    AppScreen::Guide => {
                        if self.guide.on_mouse_press(
                            mx,
                            my,
                            view_w,
                            view_h,
                            self.settings.colorblind_palette,
                        ) == GuideAction::Back
                        {
                            self.transition_menu_screen(AppScreen::Menu);
                        }
                    }
                    AppScreen::Hangar => {
                        match self.hangar.on_mouse_press(
                            mx,
                            my,
                            view_w,
                            view_h,
                            Some(&self.progress_path),
                        ) {
                            HangarAction::Back => self.transition_menu_screen(AppScreen::Menu),
                            HangarAction::SkinEquipped(_) => self.audio.cue("skin_select", 1.0),
                            HangarAction::Moved => self.audio.cue("hangar_move", 1.0),
                            HangarAction::LockedRefused => self.audio.cue("menu_deny", 1.0),
                            HangarAction::None => {}
                        }
                    }
                    AppScreen::Paused => match self.pause_ui.on_mouse_press(mx, my, view_w, view_h) {
                        PauseAction::Resume => self.enter_screen(AppScreen::Playing),
                        PauseAction::QuitToMenu => self.quit_run_to_menu(),
                        PauseAction::None => {}
                    },
                    AppScreen::BossReward => {
                        let act = self.boss_reward_ui.on_mouse_press(mx, my, view_w, view_h);
                        self.apply_boss_reward_action(act);
                    }
                    AppScreen::GameOver => match self.game_over_ui.on_mouse_press(mx, my, view_w, view_h) {
                        GameOverAction::Retry => {
                            let daily = self.sim.as_ref().and_then(|s| s.daily_date.as_ref()).is_some();
                            if let Some((_, d)) = self.fade.trigger(AppScreen::Playing, daily, self.settings.reduced_motion) {
                                self.start_run(d);
                            }
                        }
                        GameOverAction::QuitToMenu => {
                            if let Some((t, _)) = self.fade.trigger(AppScreen::Menu, false, self.settings.reduced_motion) {
                                self.enter_screen(t);
                            }
                        }
                        GameOverAction::None => {}
                    },
                }
            }
            MouseButton::Right => {
                if self.screen == AppScreen::Playing {
                    self.ultra_queued = true;
                }
            }
            _ => {}
        }
    }

    fn apply_boss_reward_action(&mut self, act: BossRewardAction) {
        let (view_w, view_h) = self.view_size();
        match act {
            BossRewardAction::TempPicked { key, duration } => {
                self.pending_temp_choice = Some((key, duration));
                if let Some(sim) = &mut self.sim {
                    let evs = apply_boss_temp_reward(sim, key, duration);
                    self.audio.handle_sim_events(&evs);
                    self.world
                        .on_step_post(sim, &evs, view_w as f32, view_h as f32);
                }
            }
            BossRewardAction::PermPicked { key } => {
                let mut applied = false;
                if let Some(sim) = &mut self.sim {
                    let evs = apply_boss_perm_reward(sim, key);
                    applied = sim.pending_boss_reward.is_none();
                    if applied {
                        if let (Some(rec), Some((tk, td))) = (&mut self.recorder, self.pending_temp_choice.take()) {
                            rec.push_reward_with_state(tk, td, key, sim);
                        }
                        self.audio.handle_sim_events(&evs);
                        self.world
                            .on_step_post(sim, &evs, view_w as f32, view_h as f32);
                    }
                }
                if applied {
                    self.enter_screen(AppScreen::Playing);
                }
            }
            BossRewardAction::None => {}
        }
    }

    fn handle_key_press(&mut self, code: KeyCode, is_repeat: bool, event_loop: &ActiveEventLoop) {
        if self.fade.active || is_repeat {
            return;
        }
        if code == KeyCode::F11 {
            self.toggle_fullscreen();
            return;
        }
        if code == KeyCode::F3 {
            self.show_perf_overlay = !self.show_perf_overlay;
            return;
        }
        let (view_w, view_h) = self.view_size();
        let confirm = matches!(code, KeyCode::Enter | KeyCode::NumpadEnter);
        let esc = code == KeyCode::Escape;

        match self.screen {
            AppScreen::Playing => match code {
                KeyCode::Space => self.dash_queued = true,
                KeyCode::KeyQ => self.ultra_queued = true,
                KeyCode::Escape => self.enter_screen(AppScreen::Paused),
                _ => {}
            },
            AppScreen::Paused => {
                let mv = if matches!(code, KeyCode::ArrowUp | KeyCode::KeyW) {
                    -1
                } else if matches!(code, KeyCode::ArrowDown | KeyCode::KeyS) {
                    1
                } else {
                    0
                };
                match self.pause_ui.on_key(mv, confirm, esc) {
                    PauseAction::Resume => self.enter_screen(AppScreen::Playing),
                    PauseAction::QuitToMenu => self.quit_run_to_menu(),
                    PauseAction::None => {}
                }
            }
            AppScreen::Menu => {
                let delta = if matches!(code, KeyCode::ArrowUp | KeyCode::KeyW) {
                    -1
                } else if matches!(code, KeyCode::ArrowDown | KeyCode::KeyS) {
                    1
                } else {
                    0
                };
                let horizontal = if matches!(code, KeyCode::ArrowLeft | KeyCode::KeyA) {
                    -1
                } else if matches!(code, KeyCode::ArrowRight | KeyCode::KeyD) {
                    1
                } else {
                    0
                };
                match self.menu.on_key_nav(
                    delta,
                    horizontal,
                    confirm,
                    &self.settings.mutators,
                ) {
                    MenuAction::Play => {
                        if let Some((_, d)) = self.fade.trigger(AppScreen::Playing, false, self.settings.reduced_motion) {
                            self.start_run(d);
                        }
                    }
                    MenuAction::PlayDaily => {
                        if let Some((_, d)) = self.fade.trigger(AppScreen::Playing, true, self.settings.reduced_motion) {
                            self.start_run(d);
                        }
                    }
                    MenuAction::OpenHangar => self.transition_menu_screen(AppScreen::Hangar),
                    MenuAction::OpenSettings => self.transition_menu_screen(AppScreen::Settings),
                    MenuAction::OpenGuide => self.transition_menu_screen(AppScreen::Guide),
                    MenuAction::Quit => event_loop.exit(),
                    MenuAction::MutatorsChanged(next) => {
                        self.settings.mutators = next;
                        save_settings(&self.settings_path, &self.settings);
                        self.audio.cue("menu_click", 1.0);
                    }
                    _ => {
                        if esc {
                            event_loop.exit();
                        }
                    }
                }
            }
            AppScreen::Settings => {
                let dx = if matches!(code, KeyCode::ArrowLeft | KeyCode::KeyA) {
                    -1
                } else if matches!(code, KeyCode::ArrowRight | KeyCode::KeyD) {
                    1
                } else {
                    0
                };
                let dy = if matches!(code, KeyCode::ArrowUp | KeyCode::KeyW) {
                    1
                } else if matches!(code, KeyCode::ArrowDown | KeyCode::KeyS) {
                    -1
                } else {
                    0
                };
                match self.settings_ui.on_key_nav(dx, dy, confirm, esc) {
                    SettingsAction::Back => self.transition_menu_screen(AppScreen::Menu),
                    SettingsAction::Changed {
                        resize_window,
                        toggle_fullscreen,
                        arena_resized,
                    } => self.apply_settings_change(resize_window, toggle_fullscreen, arena_resized),
                    SettingsAction::None => {}
                }
            }
            AppScreen::Guide => {
                let pd = if matches!(code, KeyCode::ArrowLeft | KeyCode::KeyA) {
                    -1
                } else if matches!(code, KeyCode::ArrowRight | KeyCode::KeyD) {
                    1
                } else {
                    0
                };
                if self.guide.on_key(
                    pd,
                    code == KeyCode::Tab,
                    esc,
                    view_w,
                    view_h,
                    self.settings.colorblind_palette,
                ) == GuideAction::Back
                {
                    self.transition_menu_screen(AppScreen::Menu);
                }
            }
            AppScreen::Hangar => {
                let dir = match code {
                    KeyCode::ArrowLeft | KeyCode::KeyA => Some(NavDir::Left),
                    KeyCode::ArrowRight | KeyCode::KeyD => Some(NavDir::Right),
                    KeyCode::ArrowUp | KeyCode::KeyW => Some(NavDir::Up),
                    KeyCode::ArrowDown | KeyCode::KeyS => Some(NavDir::Down),
                    _ => None,
                };
                match self.hangar.on_nav(
                    dir,
                    confirm,
                    code == KeyCode::Tab,
                    esc,
                    view_w,
                    view_h,
                    Some(&self.progress_path),
                ) {
                    HangarAction::Back => self.transition_menu_screen(AppScreen::Menu),
                    HangarAction::SkinEquipped(_) => self.audio.cue("skin_select", 1.0),
                    HangarAction::Moved => self.audio.cue("hangar_move", 1.0),
                    HangarAction::LockedRefused => self.audio.cue("menu_deny", 1.0),
                    HangarAction::None => {}
                }
            }
            AppScreen::BossReward => {
                let num = match code {
                    KeyCode::Digit1 | KeyCode::Numpad1 => Some(0),
                    KeyCode::Digit2 | KeyCode::Numpad2 => Some(1),
                    KeyCode::Digit3 | KeyCode::Numpad3 => Some(2),
                    _ => None,
                };
                let dd = if matches!(code, KeyCode::ArrowLeft | KeyCode::KeyA | KeyCode::ArrowUp | KeyCode::KeyW) {
                    -1
                } else if matches!(code, KeyCode::ArrowRight | KeyCode::KeyD | KeyCode::ArrowDown | KeyCode::KeyS) {
                    1
                } else {
                    0
                };
                let act = self.boss_reward_ui.on_key(num, dd, confirm);
                self.apply_boss_reward_action(act);
            }
            AppScreen::GameOver => {
                if confirm || code == KeyCode::Space {
                    if self.game_over_ui.on_confirm_key() == GameOverAction::Retry {
                        let daily = self.sim.as_ref().and_then(|s| s.daily_date.as_ref()).is_some();
                        if let Some((_, d)) = self.fade.trigger(AppScreen::Playing, daily, self.settings.reduced_motion) {
                            self.start_run(d);
                        }
                    }
                } else if esc {
                    self.enter_screen(AppScreen::Menu);
                }
            }
        }
    }
}

impl ApplicationHandler for PloutoApp {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        if self.window.is_some() {
            return;
        }
        let (dw, dh) = self.settings.display_size.unwrap_or((1280, 720));
        let mut attrs = WindowAttributes::default()
            .with_title("PLOUTO — Stellar Survival")
            .with_inner_size(LogicalSize::new(dw, dh))
            .with_min_inner_size(LogicalSize::new(800, 520));
        if self.settings.fullscreen {
            attrs = attrs.with_fullscreen(Some(Fullscreen::Borderless(None)));
        }
        if let Some(icon) = load_window_icon() {
            attrs = attrs.with_window_icon(Some(icon));
        }

        let win = Arc::new(
            event_loop
                .create_window(attrs)
                .expect("failed to create application window"),
        );
        let gpu = GpuContext::new(win.clone()).expect("failed to initialize wgpu context");
        let renderer = FrameRenderer::new(&gpu).expect("failed to initialize GPU renderer");

        self.mouse_screen = [gpu.size.0 as f32 * 0.5, gpu.size.1 as f32 * 0.5];
        self.window = Some(win);
        self.gpu = Some(gpu);
        self.renderer = Some(renderer);
        self.last_frame = Instant::now();
    }

    fn window_event(
        &mut self,
        event_loop: &ActiveEventLoop,
        _window_id: WindowId,
        event: WindowEvent,
    ) {
        match event {
            WindowEvent::CloseRequested => {
                self.abandon_run();
                self.flush_recorder();
                event_loop.exit();
            }
            WindowEvent::Resized(new_size) => {
                if new_size.width > 0 && new_size.height > 0 {
                    if let (Some(gpu), Some(renderer)) = (self.gpu.as_mut(), self.renderer.as_mut()) {
                        gpu.resize(new_size.width, new_size.height);
                        renderer.resize(gpu);
                        if let Some(sim) = &mut self.sim {
                            sim.on_view_resized(
                                new_size.width,
                                new_size.height,
                                self.settings.arena_margin,
                            );
                        }
                    }
                }
            }
            WindowEvent::CursorMoved { position, .. } => {
                let raw = [position.x as f32, position.y as f32];
                if let Some(prev) = self.last_os_cursor {
                    let dx = raw[0] - prev[0];
                    let dy = raw[1] - prev[1];
                    if dx * dx + dy * dy > 16.0 {
                        self.input_device = InputDevice::KeyboardMouse;
                    }
                }
                self.last_os_cursor = Some(raw);
                let (w, h) = self.view_size();
                let sx = (position.x as f32).clamp(0.0, w as f32);
                // Convert top-left OS coordinates into bottom-up (+y up) Pyglet/SDF space
                let sy = ((h as f32) - (position.y as f32)).clamp(0.0, h as f32);
                self.mouse_screen = [sx, sy];
                match self.screen {
                    AppScreen::Menu => self.menu.on_mouse_move(sx, sy),
                    AppScreen::Settings => {
                        if let SettingsAction::Changed {
                            resize_window,
                            toggle_fullscreen,
                            arena_resized,
                        } = self.settings_ui.on_mouse_move(sx, sy, w, h)
                        {
                            self.apply_settings_change(resize_window, toggle_fullscreen, arena_resized);
                        }
                    }
                    AppScreen::Guide => self.guide.on_mouse_move(sx, sy),
                    AppScreen::Hangar => self.hangar.on_mouse_move(sx, sy),
                    AppScreen::Paused => self.pause_ui.on_mouse_move(sx, sy),
                    AppScreen::BossReward => self.boss_reward_ui.on_mouse_move(sx, sy),
                    AppScreen::GameOver => self.game_over_ui.on_mouse_move(sx, sy),
                    AppScreen::Playing => {}
                }
            }
            WindowEvent::MouseInput { state, button, .. } => match state {
                ElementState::Pressed => {
                    self.input_device = InputDevice::KeyboardMouse;
                    self.handle_mouse_press(button, event_loop);
                }
                ElementState::Released => {
                    if button == MouseButton::Left {
                        self.mouse_left_down = false;
                        self.settings_ui.on_mouse_release();
                    }
                }
            },
            WindowEvent::KeyboardInput {
                event:
                    KeyEvent {
                        physical_key: PhysicalKey::Code(code),
                        state,
                        repeat,
                        ..
                    },
                ..
            } => match state {
                ElementState::Pressed => {
                    self.input_device = InputDevice::KeyboardMouse;
                    let already_down = !self.keys.insert(code);
                    self.handle_key_press(code, repeat || already_down, event_loop);
                }
                ElementState::Released => {
                    self.keys.remove(&code);
                }
            },
            WindowEvent::RedrawRequested => {
                self.step_frame();
            }
            _ => {}
        }
    }

    fn about_to_wait(&mut self, event_loop: &ActiveEventLoop) {
        self.pump_gamepad(event_loop);
        if let Some(win) = &self.window {
            win.request_redraw();
        }
    }
}

/// What the game-over screen needs from a settled run.
struct RunSettlement {
    score: i32,
    wave: i32,
    survived_s: f32,
    kills: i32,
    best_combo: f32,
    outcome: SubmitOutcome,
    mutator_ids: Vec<String>,
    daily: Option<DailyResult>,
    /// Display names of the achievements this run unlocked.
    unlocked: Vec<String>,
    /// Display lines for the closest locked achievements.
    near: Vec<String>,
}

/// Up to two locked, non-secret achievements closest to unlocking, as display lines.
/// `totals` must already include `run`.
fn near_misses(run: &RunStats, totals: &AchTotals, earned: &[String]) -> Vec<String> {
    let mut close: Vec<(f64, &AchievementDef, i64, i64)> = ACHIEVEMENTS
        .iter()
        .filter(|d| !d.secret && !earned.iter().any(|e| e == d.id))
        .filter_map(|d| {
            let (cur, target) = progress_of(d, run, totals);
            if target > 0 && cur > 0 && cur < target {
                Some((cur as f64 / target as f64, d, cur, target))
            } else {
                None
            }
        })
        .collect();
    close.sort_by(|a, b| b.0.total_cmp(&a.0));
    close
        .into_iter()
        .take(2)
        .map(|(_, d, cur, target)| format!("{}: {}", d.name, progress_text(d.cond, cur, target)))
        .collect()
}

/// "current / target" for an achievement condition. Float conditions are stored in
/// thousandths of a second, so they are shown in seconds.
fn progress_text(cond: AchCondition, cur: i64, target: i64) -> String {
    let cur = cur.min(target);
    match cond {
        AchCondition::RunFloatAtLeast("survived_s", _) => {
            format!("{} / {}", clock_text(cur), clock_text(target))
        }
        AchCondition::RunFloatAtLeast(_, _) => {
            format!("{:.1}x / {:.1}x", cur as f32 / 1000.0, target as f32 / 1000.0)
        }
        _ => format!("{cur} / {target}"),
    }
}

/// m:ss for a thousandths-of-a-second value.
fn clock_text(thousandths: i64) -> String {
    let secs = (thousandths / 1000).max(0);
    format!("{}:{:02}", secs / 60, secs % 60)
}

/// Button-to-key translation for the non-stick bindings. D-pad and the left
/// stick are handled by the navigation repeat, so they map to nothing here.
fn pad_button_key(btn: PadButton, playing: bool, on_menu: bool) -> Option<KeyCode> {
    match btn {
        PadButton::South => Some(if playing { KeyCode::Space } else { KeyCode::Enter }),
        PadButton::North if playing => Some(KeyCode::KeyQ),
        // B backs out of sub-screens. On the main menu it would quit the app,
        // so it is ignored there (Escape on the keyboard still quits).
        PadButton::East if !playing && !on_menu => Some(KeyCode::Escape),
        // Start pauses a run and backs out of sub-screens; on the main menu it
        // would quit the app, so it is ignored there.
        PadButton::Start if !on_menu => Some(KeyCode::Escape),
        _ => None,
    }
}

fn dpad_dir(pad: &PadSnapshot) -> Option<NavDir4> {
    let held = |b: PadButton| pad.held.get(b as usize).copied().unwrap_or(false);
    if held(PadButton::DPadUp) {
        Some(NavDir4::Up)
    } else if held(PadButton::DPadDown) {
        Some(NavDir4::Down)
    } else if held(PadButton::DPadLeft) {
        Some(NavDir4::Left)
    } else if held(PadButton::DPadRight) {
        Some(NavDir4::Right)
    } else {
        None
    }
}

fn stick_mag(v: [f32; 2]) -> f32 {
    (v[0] * v[0] + v[1] * v[1]).sqrt()
}
