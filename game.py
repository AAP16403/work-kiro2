# Pyglet isometric room survival prototype
# Controls: WASD/Arrows move, LMB toggles auto-fire, SPACE dash, LSHIFT boost, ESC menu.
# Install: py -m pip install pyglet

import math
import random

import pyglet

import config
# pyglet reads debug_gl when pyglet.gl loads, so this must come before the shapes import below.
pyglet.options["debug_gl"] = bool(config.PYGLET_DEBUG_GL)
from pyglet import shapes

pyglet.options["shadow_window"] = False

import config
import audio_cues
import daily
import replay
import parallel
from config import SCREEN_W, SCREEN_H, FPS, MAP_CIRCLE, ENEMY_COLORS

from map import Room
from level import GameState as GameStateData, get_difficulty_mods, spawn_loot_on_enemy_death

from utils import set_view_size, compute_room_radius, Vec2, clamp_to_map, enemy_behavior_name, iso_to_world, dist, point_segment_distance

from visuals import Visuals, GroupCache
from skin_apply import default_run_skin, read_run_skin
from weapons import get_weapon_for_wave, get_effective_fire_rate

from particles import ParticleSystem
from audio import AudioManager, load_audio_settings, save_audio_settings
import shake_prefs
import access_prefs
from popups import DamagePopups
from menu import (
    Menu,
    SettingsMenu,
    GuideMenu,
    PauseMenu,
    GameOverMenu,
    UI_FONT_META,
)
from rpg import (
    BossRewardMenu,
    recompute_temp_mods,
    advance_temp_rewards,
    apply_temp_reward as rpg_apply_temp,
    apply_perm_reward as rpg_apply_perm,
    roll_boss_rewards as rpg_roll_rewards
)
from hazards import LaserBeam
from layout import generate_obstacles
from logic import BalanceLogic
import mutators
from mutators import RunRules
from player import Player, perform_dash

from fsm import StateMachine
from advanced_fx import AdvancedFX
from score import ScoreTracker
from achievements import RunStats
import progress as meta_progress
from hud import HUD, current_skin_name
from states import (
    MenuState,
    SettingsState,
    GuideState,
    PlayingState,
    PausedState,
    BossRewardState,
    GameOverState,
    HangarState,
    add_shake,
)





# ============================
# Main Game Class
# ============================
class Game(pyglet.window.Window):
    """Main game window and logic."""

    def __init__(self, record_runs: bool = False):
        # Run recording (replay.py) is off unless asked for: the --record flag turns it on for every run.
        self.record_runs = bool(record_runs)
        self.recorder = None  # replay.Recorder while a run plays and recording is on
        self.forced_seed = None  # set by replay.start_run so a replay gets the recorded seed
        super().__init__(width=SCREEN_W, height=SCREEN_H, caption="PLOUTO // Stellar Survival", vsync=True)
        for event_name in ("on_activate", "on_deactivate"):
            type(self).register_event_type(event_name)
        set_view_size(self.width, self.height)
        self._display_size = self._get_display_size()
        if self._display_size:
            dw, dh = self._display_size
            if self.width > dw or self.height > dh:
                self.set_size(min(self.width, dw), min(self.height, dh))
        self._update_room_radius_from_view()
        
        music_vol, sfx_vol = load_audio_settings()
        self.audio = AudioManager(sfx_volume=sfx_vol, music_volume=music_vol)
        self.popups = None
        self._hitstop = 0.0

        shake_level = shake_prefs.load_shake_level(default="full")
        config.SHAKE_SCALE = shake_prefs.shake_scale_for_level(shake_level)
        # Accessibility options: saved values become the runtime flags before any menu or HUD is built.
        access = access_prefs.apply(access_prefs.load_access_settings())

        self.settings = {
            "difficulty": "normal",
            "window_size": (self.width, self.height),
            "fullscreen": True,
            "arena_margin": float(getattr(config, "ARENA_MARGIN", 0.97)),
            "advanced_fx": bool(getattr(config, "ENABLE_ADVANCED_FX", True)),
            "shake_level": shake_level,
            "reduced_shake": shake_prefs.shake_level_is_reduced(shake_level),
            "map_type": MAP_CIRCLE,
            "music_volume": music_vol,
            "sfx_volume": sfx_vol,
        }
        self.settings.update(access)
        self._windowed_size = (self.width, self.height)

        # Opt-in run mutators: the title-screen selection (saved), and the snapshot the current run plays with.
        self.mutator_ids: tuple[str, ...] = mutators.load_selection()
        self.run_mutators: tuple[str, ...] = ()
        self.run_rules: RunRules = RunRules()
        self._shield_regen_carry = 0.0

        # Menu system
        self.main_menu = Menu(
            self.width,
            self.height,
            mutator_ids=self.mutator_ids,
            on_mutator_toggle=self._toggle_mutator,
        )
        self.settings_menu = SettingsMenu(
            self.width,
            self.height,
            self._on_settings_change,
            display_size=self._display_size,
            advanced_fx_enabled=bool(self.settings.get("advanced_fx", True)),
            shake_level=shake_level,
            map_type=self.settings.get("map_type", MAP_CIRCLE),
            music_volume=music_vol,
            sfx_volume=sfx_vol,
            reduced_motion=access[access_prefs.REDUCED_MOTION_KEY],
            colorblind_palette=access[access_prefs.COLORBLIND_KEY],
            high_contrast_hud=access[access_prefs.HIGH_CONTRAST_KEY],
        )
        self.guide_menu = GuideMenu(self.width, self.height)
        self.pause_menu = PauseMenu(self.width, self.height)
        self.rpg_menu = BossRewardMenu(self.width, self.height, self._apply_temp_reward, self._apply_perm_reward)
        self.game_over_menu = GameOverMenu(self.width, self.height)
        self.hangar_menu = None  # built on the first visit to the Hangar (see states.HangarState)

        # Game objects (will be initialized when game starts)
        self.batch = None
        self.groups = None
        self.room = None
        self.state = None
        self.player = None
        self.visuals = None
        self.particle_system = None
        self.run_skin = default_run_skin()  # replaced with the selected skin at each run start

        self.keys = pyglet.window.key.KeyStateHandler()
        self.push_handlers(self.keys)

        self.mouse_xy = (self.width / 2, self.height / 2)
        self.mouse_down = False
        self._rmb_down = False
        self.auto_shoot = True  # Auto-fire starts ON for every run; LMB toggles it
        # Daily challenge (daily.py): the local date of the active daily run, None for a normal run, and the
        # mutator ids that run is built with. A daily run has exactly one mutator, chosen by its date.
        self.daily_date: str | None = None
        self.run_mutator_ids: tuple[str, ...] = ()
        # Achievements earned by the last finished run. The next run's HUD shows them as toasts.
        self._pending_achievement_ids: list[str] = []
        # progress.json location for the daily record; None means the store's default. Tests point it at a temp file.
        self.progress_path: str | None = None
        self.balance = BalanceLogic(fps=float(FPS))
        self._fixed_dt = self.balance.fixed_dt
        self._frame_dt_cap = self.balance.frame_dt_cap
        self._max_catchup_steps = self.balance.max_catchup_steps
        self._accumulator = 0.0
        self._render_time = 0.0
        self.advanced_fx = AdvancedFX(self.width, self.height)
        self.advanced_fx.enabled = bool(self.settings.get("advanced_fx", True))

        # Cached UI labels to avoid per-frame allocations.
        self._pause_hint = pyglet.text.Label(
            "Press ESC to pause",
            font_name=UI_FONT_META,
            font_size=11,
            x=self.width - 10,
            y=10,
            anchor_x="right",
            anchor_y="bottom",
            color=(168, 186, 206, 210),
        )

        pyglet.clock.schedule_interval(self.update, 1.0 / FPS)

        self.fsm = StateMachine(MenuState(self))
        self.fsm.add_state(SettingsState(self))
        self.fsm.add_state(GuideState(self))
        self.fsm.add_state(HangarState(self))
        self.fsm.add_state(PlayingState(self))
        self.fsm.add_state(PausedState(self))
        self.fsm.add_state(BossRewardState(self))
        self.fsm.add_state(GameOverState(self))
        self._enable_startup_fullscreen()

    def _enable_startup_fullscreen(self) -> None:
        """Start in fullscreen while preserving the current windowed size."""
        self.settings["window_size"] = (self.width, self.height)
        self._windowed_size = (self.width, self.height)
        self.settings_menu.window_size_idx = len(self.settings_menu.window_sizes) - 1
        self._on_settings_change({"fullscreen": True, "window_size": self._windowed_size})

    def _reset_input_flags(self) -> None:
        self.mouse_down = False
        self._rmb_down = False

    def _get_display_size(self):
        try:
            display = pyglet.canvas.get_display()
            screen = display.get_default_screen()
            return (int(screen.width), int(screen.height))
        except Exception:
            return None

    def _update_room_radius_from_view(self):
        margin = float(getattr(config, "ARENA_MARGIN", 0.92))
        config.ROOM_RADIUS = compute_room_radius(self.width, self.height, margin=margin)

    def _prune_dead_weak_handlers(self) -> None:
        """Remove collected WeakMethod handlers to prevent pyglet assertions on dispatch."""
        from pyglet.event import WeakMethod

        stack = getattr(self, "_event_stack", None)
        if not stack:
            return

        for frame in list(stack):
            if not isinstance(frame, dict):
                continue
            for event_name, handler in list(frame.items()):
                if isinstance(handler, WeakMethod) and handler() is None:
                    del frame[event_name]

    def dispatch_event(self, *args):
        self._prune_dead_weak_handlers()
        try:
            return super().dispatch_event(*args)
        except AssertionError:
            if args and args[0] in ("on_activate", "on_deactivate"):
                return False
            raise
    
    def _init_game(self, mutator_ids=None):
        """Initialize game objects. The run plays with mutator_ids (default: the title-screen selection), fixed until the next run."""
        # Start Game and Try Again both begin with auto-fire on (the Guide and status line say so).
        self.auto_shoot = True
        self.batch = pyglet.graphics.Batch()
        self.groups = GroupCache()
        self.room = Room(self.batch, self.width, self.height, map_type=self.settings.get("map_type", MAP_CIRCLE))

        # The only place mutators are applied: the run keeps this snapshot for its whole duration. A daily run
        # keeps its one mutator through Try Again (run_mutator_ids); every other run uses the title selection.
        if mutator_ids is None:
            mutator_ids = self.run_mutator_ids if self.daily_date else self.mutator_ids
        self.run_mutators = mutators.normalize_selection(mutator_ids)
        self.run_rules = mutators.apply_mutators(self.run_mutators)

        difficulty = str(self.settings.get("difficulty", "normal")).lower()
        self.state = GameStateData(
            difficulty=difficulty,
            map_type=self.settings.get("map_type", MAP_CIRCLE),
            rules=self.run_rules,
        )
        # Deterministic RNG for this run (seed stored on state for reproducibility). A daily run seeds the run RNG
        # and the module RNG (enemy AI and boss picks draw from it) with the date's seed, so every player gets the same setup.
        run_seed = daily.daily_seed(self.daily_date) if self.daily_date else None
        if self.forced_seed is not None:  # a replay plays the recorded seed (replay.start_run)
            run_seed = int(self.forced_seed)
        self.state.init_rng(run_seed)
        if run_seed is not None:
            random.seed(run_seed)
        # The skin selected in progress is read once per run start and drives the ship, shots, trails and dash.
        # It is read before the recorder so the recording stores the same skin id the run uses.
        self.run_skin = read_run_skin()
        # Record this run when recording is on. The recorder is attached here, before the first step.
        self.recorder = None
        if self.record_runs and self.forced_seed is None:
            self.recorder = replay.Recorder(
                self.state.seed, difficulty, skin=self.run_skin.skin_id, mutators=self.run_mutators,
            )

        # Base per-wave head count lives in logic.py's difficulty table (the wave ramp is applied in level.spawn_wave).
        self.state.max_enemies = int(get_difficulty_mods(difficulty).get("max_enemies", 12))
        if difficulty == "easy":
            self._incoming_damage_mult = 0.85
        elif difficulty == "hard":
            self._incoming_damage_mult = 1.15
        else:
            self._incoming_damage_mult = 1.0
        if config.ENABLE_OBSTACLES:
            self.state.layout_seed = self.state.rng.randint(0, 1_000_000_000)
            self.state.layout_segment = 0
            self.state.obstacles = generate_obstacles(
                self.state.layout_seed, self.state.layout_segment, config.ROOM_RADIUS, difficulty=self.state.difficulty
            )
        else:
            self.state.obstacles = []
        self.player = Player(pos=Vec2(0.0, 0.0))
        self.player.current_weapon = get_weapon_for_wave(1)
        self.player.max_hp = mutators.scaled_max_hp(self.player.max_hp, self.run_rules)
        self.player.hp = self.player.max_hp
        self._shield_regen_carry = 0.0
        self._active_temp_rewards: list[dict] = []
        self._run_permanent_rewards: list[str] = []
        self._last_reward_temp_key = ""
        self._last_reward_perm_key = ""
        self._pickup_magnet_bonus = 0.0
        self._temp_damage_mult = 1.0
        self._temp_speed_mult = 1.0
        self._temp_fire_rate_mult = 1.0
        self._temp_incoming_damage_mult = 1.0
        self._ultra_cd_mult = 1.0
        self._temp_crit_chance_bonus = 0.0
        self._temp_crit_mult_bonus = 0.0
        self._temp_boost_inf = False
        self._dash_cd_mult = 1.0
        self._dash_cd_difficulty = float(get_difficulty_mods(difficulty).get("dash_cd", 1.0))

        self.visuals = Visuals(self.batch, self.groups)
        self.visuals.apply_skin(self.run_skin)
        self.visuals.make_player()

        self.particle_system = ParticleSystem(self.batch)
        self.popups = DamagePopups()
        self._hitstop = 0.0

        self.score = ScoreTracker(
            difficulty=difficulty,
            score_mult=mutators.combined_score_multiplier(self.run_mutators),
        )
        self.run_stats = RunStats()
        self.hud = HUD(self.width, self.height)
        self.hud.on_toast = self._play_toast_cue
        self.hud.set_skin_name(current_skin_name())
        if self._pending_achievement_ids:
            self.hud.push_achievement_toasts(self._pending_achievement_ids)
            self._pending_achievement_ids = []

    def _start_daily_run(self, today=None):
        """Start the daily run for the local date (or for ``today`` when a test passes one).

        The run uses the date's seed and exactly one mutator, the one daily.daily_mutator picks, so it never
        stacks with other mutators. Try Again replays the same daily until the player leaves to the menu.
        """
        date_iso = daily.today_iso(today)
        self.daily_date = date_iso
        self.run_mutator_ids = (daily.daily_mutator(date_iso),)
        # The daily run plays with its own one-mutator list, not the saved title-screen selection.
        self._init_game(mutator_ids=self.run_mutator_ids)

    def _effective_player_damage(self) -> int:
        if not self.player:
            return 0
        # Half-up rounding (not round(), which is banker's rounding at .5) so the 1.28 Overdrive multiplier lands predictably.
        run_rules = getattr(self, "run_rules", None)
        run_mult = float(run_rules.player_damage_mult) if run_rules is not None else 1.0  # Glass Cannon and other run rules
        return max(1, math.floor(float(self.player.damage) * float(getattr(self, "_temp_damage_mult", 1.0)) * run_mult + 0.5))

    def _effective_player_speed(self) -> float:
        if not self.player:
            return 0.0
        return float(self.player.speed) * float(getattr(self, "_temp_speed_mult", 1.0))

    def _effective_player_fire_rate(self) -> float:
        if not self.player:
            return 0.28
        return max(0.08, float(self.player.fire_rate) * float(getattr(self, "_temp_fire_rate_mult", 1.0)))

    def _effective_crit_chance(self) -> float:
        if not self.player:
            return 0.0
        return float(getattr(self.player, "crit_chance_bonus", 0.0)) + float(getattr(self, "_temp_crit_chance_bonus", 0.0))

    def _effective_crit_mult(self) -> float:
        if not self.player:
            return 0.0
        return float(getattr(self.player, "crit_mult_bonus", 0.0)) + float(getattr(self, "_temp_crit_mult_bonus", 0.0))

    def _has_infinite_boost(self) -> bool:
        if not self.player:
            return False
        cur_t = getattr(self.state, "time", 0.0) if self.state else 0.0
        return bool(getattr(self, "_temp_boost_inf", False)) or (cur_t < float(getattr(self.player, "infinite_boost_until", 0.0)))

    def _recompute_temp_reward_mods(self) -> None:
        mods = recompute_temp_mods(getattr(self, "_active_temp_rewards", []))
        self._temp_damage_mult = mods["damage"]
        self._temp_speed_mult = mods["speed"]
        self._temp_fire_rate_mult = mods["fire_rate"]
        self._pickup_magnet_bonus = mods["magnet"]
        self._temp_incoming_damage_mult = mods["incoming_damage"]
        self._ultra_cd_mult = mods["ultra_cd"]
        self._temp_crit_chance_bonus = float(mods.get("crit_chance", 0.0))
        self._temp_crit_mult_bonus = float(mods.get("crit_mult", 0.0))
        self._temp_boost_inf = bool(mods.get("boost_inf", False))

    def _advance_temp_rewards(self) -> None:
        if not getattr(self, "_active_temp_rewards", None):
            return
        self._active_temp_rewards = advance_temp_rewards(self._active_temp_rewards)
        self._recompute_temp_reward_mods()



    def _roll_boss_rewards(self) -> None:
        if not self.player:
            return
        temp_opts, perm_opts = rpg_roll_rewards(
            self._active_temp_rewards, self._last_reward_temp_key, self._last_reward_perm_key,
            player=self.player, dash_cd_mult=self._dash_cd_mult,
        )
        self.rpg_menu.begin(temp_opts, perm_opts)
        self.audio.play("reward_open", volume=0.8)

    def _apply_temp_reward(self, key: str, duration: int) -> None:
        if not self.player:
            return
        k = str(key or "").strip().lower()
        rpg_apply_temp(self._active_temp_rewards, k, duration)
        self._last_reward_temp_key = k
        self.audio.play("pickup_rare", volume=0.8)
        if k == "temp_ultra_flux":
            self.player.ultra_charges = min(int(self.player.ultra_max_charges), int(self.player.ultra_charges) + 1)
        if self.particle_system:
            self.particle_system.add_powerup_collection(self.player.pos, (255, 235, 170))
        if self.state:
            add_shake(self.state, 5.0)
        self._recompute_temp_reward_mods()

    def _apply_perm_reward(self, key: str) -> None:
        if not self.player:
            return
        k = str(key or "").strip().lower()
        self._dash_cd_mult, applied = rpg_apply_perm(
            self.player, self._run_permanent_rewards, k,
            self._dash_cd_mult,
        )
        if not applied:
            return
        self._last_reward_perm_key = k
        self.audio.play("pickup_rare", volume=0.8)
        if self.particle_system:
            self.particle_system.add_powerup_collection(self.player.pos, (200, 235, 255))
        if self.state:
            add_shake(self.state, 6.0)

    def _regen_layout(self, segment: int | None = None):
        if not config.ENABLE_OBSTACLES:
            if self.state:
                self.state.obstacles = []
            return
        if not self.state:
            return
        if segment is None:
            segment = int(getattr(self.state, "layout_segment", 0))
        # Drop visuals for old obstacles.
        if self.visuals:
            for ob in list(getattr(self.state, "obstacles", [])):
                self.visuals.drop_obstacle(ob)
        self.state.layout_segment = int(segment)
        self.state.obstacles = generate_obstacles(
            int(getattr(self.state, "layout_seed", 0)),
            self.state.layout_segment,
            config.ROOM_RADIUS,
            difficulty=getattr(self.state, "difficulty", "normal"),
        )

    def _damage_player(self, amount: int):
        if self.player.invincibility_timer > 0:
            return
        if amount <= 0:
            return
        if getattr(self.player, "is_boosting", False):
            reduction = float(getattr(config, "BOOST_DAMAGE_REDUCTION", 0.35))
            amount = max(1, int(round(amount * (1.0 - reduction))))
        mult = getattr(self, "_incoming_damage_mult", 1.0) * getattr(self, "_temp_incoming_damage_mult", 1.0)
        if mult != 1.0:
            amount = max(1, int(round(amount * mult)))
        run = getattr(self, "run_stats", None)
        if run is not None:
            run.on_player_hit(amount)  # every landed hit counts, even one the shield fully absorbs
        if self.player.shield > 0:
            absorbed = min(self.player.shield, amount)
            self.player.shield -= absorbed
            amount -= absorbed
            if absorbed > 0 and self.particle_system:
                self.particle_system.add_shield_hit(self.player.pos, absorbed)
            if absorbed > 0:
                self.audio.play("shield_hit", volume=0.6, pitch_jitter=0.05, min_gap=0.05)
        if amount > 0:
            self.player.hp -= amount
            self.player.damage_flash_timer = 0.12
            self.audio.play("hurt", volume=0.9, pitch_jitter=0.04, min_gap=0.08)
            if self.popups:
                self.popups.spawn(self.player.pos, f"-{amount}", color=(255, 110, 110), big=amount >= 20)
            if amount >= 25:
                self._hitstop = max(self._hitstop, 0.05)
            if getattr(self, "advanced_fx", None):
                self.advanced_fx.trigger_hit(min(1.0, 0.28 + amount * 0.03))
            state = getattr(self, "state", None)
            if state is not None:
                # Shake scales with the HP that actually got through the shield (shield hits add none).
                hp_shake = float(config.SHAKE_PLAYER_HIT_BASE) + amount * float(config.SHAKE_PLAYER_HIT_PER_HP)
                hp_shake = max(float(config.SHAKE_PLAYER_HIT_BASE), min(float(config.SHAKE_PLAYER_HIT_MAX), hp_shake))
                add_shake(state, hp_shake)
            if getattr(self, 'score', None):
                self.score.on_player_hit()

    def _use_ultra(self):
        if not self.state or not self.player:
            return

        s = self.state
        if getattr(self.player, "ultra_charges", 0) <= 0:
            return
        if s.time < getattr(self.player, "ultra_cd_until", 0.0):
            return

        world_mouse = iso_to_world(self.mouse_xy)
        aim = (world_mouse - self.player.pos).normalized()
        if aim.length() <= 1e-6:
            aim = Vec2(1.0, 0.0)

        muzzle = self.player.pos + aim * 14.0
        dmg = int(config.ULTRA_DAMAGE_BASE + self._effective_player_damage() * config.ULTRA_DAMAGE_MULT)
        beam_thickness = float(config.ULTRA_BEAM_THICKNESS)
        beam_ttl = float(config.ULTRA_BEAM_TTL)

        def _hit_enemy(e, amount: int):
            # Shared damage/kill path: respects shields, elite affixes and the kill guard.
            PlayingState._damage_enemy(self, s, e, int(amount))
            behavior_name = enemy_behavior_name(e)
            enemy_color = ENEMY_COLORS.get(behavior_name, (200, 200, 200))
            if self.particle_system:
                self.particle_system.add_hit_particles(e.pos, enemy_color)
            if e.hp <= 0:
                PlayingState._kill_enemy(self, s, e)

        def _spawn_player_beam(start: Vec2, direction: Vec2, length: float, damage: int, thickness: float, color):
            end = start + direction * length
            beam = LaserBeam(
                start=start,
                end=end,
                damage=int(damage),
                thickness=float(thickness),
                ttl=beam_ttl,
                owner="player",
                color=tuple(color),
            )
            s.lasers.append(beam)
            if self.particle_system:
                self.particle_system.add_laser_beam(start, end, color=beam.color)
            hit_r = float(thickness) * 0.5
            for e in list(s.enemies):
                if point_segment_distance(e.pos, start, end) <= hit_r + self._enemy_radius(e):
                    _hit_enemy(e, int(damage))

        # Cycle variants for built-in variety while preserving predictable control.
        variant = int(getattr(self.player, "ultra_variant_idx", 0)) % 3
        self.player.ultra_variant_idx = (variant + 1) % 3
        flash_r = 120.0  # Ultra flash radius for the beam variants; the shockwave variant uses its blast radius

        if variant == 0:
            # Classic piercing beam.
            _spawn_player_beam(
                muzzle,
                aim,
                length=config.ROOM_RADIUS * 2.05,
                damage=dmg,
                thickness=beam_thickness,
                color=tuple(config.ULTRA_BEAM_COLOR),
            )
            add_shake(s, 12.0)
        elif variant == 1:
            # Tri-beam spread for multi-target pressure.
            for deg in (-16.0, 0.0, 16.0):
                a = math.radians(deg)
                c = math.cos(a)
                si = math.sin(a)
                d = Vec2(aim.x * c - aim.y * si, aim.x * si + aim.y * c).normalized()
                _spawn_player_beam(
                    muzzle,
                    d,
                    length=config.ROOM_RADIUS * 1.9,
                    damage=int(dmg * 0.72),
                    thickness=beam_thickness * 0.8,
                    color=(255, 180, 180),
                )
            add_shake(s, 14.0)
        else:
            # Shockwave + forward finisher beam.
            blast_r = 160.0
            flash_r = blast_r
            blast_dmg = int(dmg * 0.58)
            for e in list(s.enemies):
                if dist(e.pos, self.player.pos) <= blast_r:
                    _hit_enemy(e, blast_dmg)
            if self.particle_system:
                self.particle_system.add_shockwave(self.player.pos, (255, 220, 180), max_radius=blast_r)
                self.particle_system.add_powerup_collection(self.player.pos, (255, 220, 180))
            _spawn_player_beam(
                muzzle,
                aim,
                length=config.ROOM_RADIUS * 1.55,
                damage=int(dmg * 0.62),
                thickness=beam_thickness * 0.7,
                color=(255, 210, 120),
            )
            add_shake(s, 16.0)  # capped at SHAKE_CAP (14) like every other stacked impulse

        if getattr(self, "visuals", None):
            # White flash tinted by this variant's colour, layered over the shockwave ring.
            flash_color = (tuple(config.ULTRA_BEAM_COLOR), (255, 180, 180), (255, 220, 180))[variant]
            self.visuals.trigger_ultra_flash(self.player.pos, flash_color, flash_r, s.time)
        self.audio.play("ultra_fire", volume=0.9)
        self._hitstop = max(self._hitstop, 0.06)
        self.player.ultra_charges = max(0, int(self.player.ultra_charges) - 1)
        self.player.ultra_cd_until = s.time + float(config.ULTRA_COOLDOWN) * float(getattr(self, "_ultra_cd_mult", 1.0))
        if getattr(self, "advanced_fx", None):
            self.advanced_fx.trigger_ultra(1.0)

    def _dash(self):
        if not self.state or not self.player:
            return
        if self.recorder is not None and self._is_playing():
            self.recorder.note_dash(self)  # the dash reads the keys and aim it is made with, so note them now
        world_mouse = iso_to_world(self.mouse_xy)
        did_dash = perform_dash(
            self.player, self.state.time, self.balance,
            float(getattr(self, "_dash_cd_difficulty", 1.0)),
            float(getattr(self, "_dash_cd_mult", 1.0)),
            self._input_dir(), world_mouse,
        )
        if did_dash:
            self.audio.play("dash", volume=0.7, pitch_jitter=0.05)
            self.particle_system.add_dash_effect(self.player.pos, self.player.dash_direction, color=self.run_skin.dash_color)
            if getattr(self, "advanced_fx", None):
                self.advanced_fx.trigger_dash(0.7)

    def _enemy_radius(self, enemy) -> float:
        return self.balance.enemy_radius(enemy_behavior_name(enemy))

    def _player_radius(self) -> float:
        return self.balance.player_radius

    def _projectile_radius(self, projectile) -> float:
        ptype = str(getattr(projectile, "projectile_type", "bullet"))
        return self.balance.projectile_radius(ptype)

    @staticmethod
    def _ultra_variant_name(player) -> str:
        names = ("Beam", "Tri-Beam", "Shockwave")
        idx = int(getattr(player, "ultra_variant_idx", 0)) % len(names)
        return names[idx]

    def _persist_audio_settings(self):
        """Write the current music/SFX volumes to user_settings.json (called when leaving Settings)."""
        save_audio_settings(float(self.settings.get("music_volume", 0.5)), float(self.settings.get("sfx_volume", 0.8)))

    def _toggle_mutator(self, mutator_id: str) -> None:
        """Title-screen chip click: switch one mutator on or off and save the selection."""
        self.mutator_ids = mutators.toggle_selection(self.mutator_ids, mutator_id)
        mutators.save_selection(self.mutator_ids)
        self.main_menu.set_mutator_selection(self.mutator_ids)
        audio_cues.cue(self.audio, "mutator_toggle")

    def _play_toast_cue(self) -> None:
        """Called by the HUD each time a toast is queued."""
        audio_cues.cue(self.audio, "toast")

    def _quit_game(self):
        """Quit the game."""
        self._persist_audio_settings()
        self._schedule_app_close()

    def _schedule_app_close(self):
        def _close(_dt):
            self.close()
            pyglet.app.exit()
        pyglet.clock.schedule_once(_close, 0)

    @staticmethod
    def _coerce_bool(value, default: bool = True) -> bool:
        """Parse common bool-ish values safely (including string forms)."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {"1", "true", "yes", "on", "enabled"}:
                return True
            if v in {"0", "false", "no", "off", "disabled"}:
                return False
        return bool(default)
    
    def _shake_level_from_settings(self, value: dict):
        """Return the shake level named in a settings dict, or None when it names none.

        ``shake_level`` (Full / Reduced / Off) wins. The legacy ``reduced_shake`` boolean still maps
        to Reduced or Full so older callers keep working.
        """
        level = value.get("shake_level")
        if isinstance(level, str) and level in config.SHAKE_LEVELS:
            return level
        reduced = value.get("reduced_shake")
        if reduced is not None:
            return "reduced" if self._coerce_bool(reduced, default=False) else "full"
        return None

    def _apply_accessibility(self, value: dict) -> None:
        """Apply the Accessibility options named in a settings dict. Saves them when one changed, and mirrors them into the menu and the HUD."""
        named = {key: value[key] for key in access_prefs.ACCESS_KEYS if key in value}
        before = access_prefs.current()
        after = access_prefs.apply(named)
        self.settings.update(after)
        if after != before:
            access_prefs.save_access_settings(after)
        if getattr(self, "settings_menu", None):
            self.settings_menu.set_accessibility(after)
        if getattr(self, "hud", None):
            self.hud.set_high_contrast(after[access_prefs.HIGH_CONTRAST_KEY])

    def _on_settings_change(self, value):
        """Callback for settings changes."""
        if not isinstance(value, dict):
            return
        previous_shake_level = shake_prefs.normalize_shake_level(self.settings.get("shake_level"))
        self.settings.update(value)
        if any(key in value for key in access_prefs.ACCESS_KEYS):
            self._apply_accessibility(value)
        if "music_volume" in value or "sfx_volume" in value:
            self.audio.set_volumes(music=value.get("music_volume"), sfx=value.get("sfx_volume"))
        advanced_fx = value.get("advanced_fx")
        if advanced_fx is not None:
            fx_enabled = self._coerce_bool(advanced_fx, default=bool(getattr(config, "ENABLE_ADVANCED_FX", True)))
            self.settings["advanced_fx"] = fx_enabled
            config.ENABLE_ADVANCED_FX = fx_enabled
            if getattr(self, "advanced_fx", None):
                self.advanced_fx.enabled = fx_enabled
            if getattr(self, "settings_menu", None):
                self.settings_menu.advanced_fx = fx_enabled
                self.settings_menu._refresh_fx_button_text()
        # Must run before the fullscreen early return below, which would skip it.
        shake_level = self._shake_level_from_settings(value)
        if shake_level is not None:
            self.settings["shake_level"] = shake_level
            self.settings["reduced_shake"] = shake_prefs.shake_level_is_reduced(shake_level)
            config.SHAKE_SCALE = shake_prefs.shake_scale_for_level(shake_level)
            if shake_level != previous_shake_level:
                shake_prefs.save_shake_level(shake_level)
            if getattr(self, "settings_menu", None):
                self.settings_menu.shake_level = shake_level
                self.settings_menu._refresh_shake_button_text()
        fullscreen = value.get("fullscreen")
        arena_margin = value.get("arena_margin")
        if arena_margin is not None:
            config.ARENA_MARGIN = float(arena_margin)
            self._update_room_radius_from_view()
            if self.room:
                self.room.rebuild(map_type=self.settings.get("map_type"))
            if self.player:
                # clamp_to_map not imported here, but usually this just resets pos if out of bounds.
                # simpler to just let next update loop handle it or ignore.
                pass
        
        map_type = value.get("map_type")
        if map_type:
            self.settings["map_type"] = map_type
            if self.room:
                self.room.rebuild(map_type=map_type)
            # If in game, we should update state too?
            if self.state:
                self.state.map_type = map_type

        if fullscreen is True:
            if not self.fullscreen:
                self._windowed_size = (self.width, self.height)
            self.set_fullscreen(True)
            return

        if fullscreen is False and self.fullscreen:
            self.set_fullscreen(False)

        size = value.get("window_size")
        if size is None and not self.fullscreen:
            size = self._windowed_size
        if size and isinstance(size, (tuple, list)) and len(size) == 2:
            w, h = int(size[0]), int(size[1])
            if self._display_size:
                dw, dh = self._display_size
                w = min(w, dw)
                h = min(h, dh)
            if w > 0 and h > 0 and (w != self.width or h != self.height):
                self.set_size(w, h)

    def on_resize(self, width, height):
        super().on_resize(width, height)
        is_fullscreen = bool(getattr(self, "fullscreen", False))
        self.settings["fullscreen"] = is_fullscreen
        if not is_fullscreen:
            self.settings["window_size"] = (width, height)
            self._windowed_size = (width, height)
        if not isinstance(self.fsm.current_state, PlayingState):
            self.mouse_xy = (width / 2, height / 2)
        set_view_size(width, height)
        self._update_room_radius_from_view()

        self.main_menu.resize(width, height)
        self.settings_menu.resize(width, height)
        self.guide_menu.resize(width, height)
        self.pause_menu.resize(width, height)
        self.rpg_menu.resize(width, height)
        self.game_over_menu.resize(width, height)
        if getattr(self, "hangar_menu", None) is not None:
            self.hangar_menu.resize(width, height)

        if getattr(self, "_pause_hint", None):
            self._pause_hint.x = width - 10
            self._pause_hint.y = 10
        if getattr(self, "hud", None):
            self.hud.layout(width, height)

        if self.room:
            self.room.resize(width, height)
        if self.state:
            if config.ENABLE_OBSTACLES:
                self._regen_layout(getattr(self.state, "layout_segment", 0))
        if getattr(self, "advanced_fx", None):
            self.advanced_fx.resize(width, height)
    
    def _return_to_menu(self):
        """Return to main menu."""
        # Leaving to the menu ends any daily run, so the next run is a normal one.
        self.daily_date = None
        self.run_mutator_ids = ()
        # Clean up game objects
        if self.batch:
            self.batch = None
        self.groups = None
        self.room = None
        self.state = None
        self.player = None
        self.visuals = None
        self.particle_system = None
        self.popups = None
        self._hitstop = 0.0

    def _finish_meta_run(self):
        """End this run's meta stats and save progress.json once. Returns the summary, or None.

        Safe to call more than once: only the first call for a run writes, so death, pause-quit
        and window close can all call it.
        """
        run = getattr(self, "run_stats", None)
        if run is None or run.finished or not self.state:
            return None
        score_obj = getattr(self, "score", None)
        run.finish(
            score=int(score_obj.score) if score_obj else 0,
            wave=int(self.state.wave),
            survived=float(self.state.time),
            best_combo=float(score_obj.best_combo) if score_obj else None,
        )
        # The run's progress goes to the same file the daily record uses (progress_path, or the store default).
        self.last_run_summary = meta_progress.end_run(run, path=self.progress_path)
        self._pending_achievement_ids.extend(self.last_run_summary.get("new_achievements", []))
        if self.last_run_summary.get("new_achievements"):
            audio_cues.cue(self.audio, "achievement")
        if self.recorder is not None:
            # --record: keep the finished run's inputs and hashes in replays/last_run.json.
            replay.save_recording(self.recorder.recording(), replay.DEFAULT_PATH)
            self.recorder = None
        return self.last_run_summary

    def on_mouse_motion(self, x, y, dx, dy):
        self.mouse_xy = (x, y)
        self.fsm.on_mouse_motion(x, y, dx, dy)

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        self.fsm.on_mouse_drag(x, y, dx, dy, buttons, modifiers)

    def on_mouse_press(self, x, y, button, modifiers):
        state = self.fsm.current_state
        # A click inside the Game Over input lock is ignored by the state, so it must not play a sound either.
        game_over_locked = isinstance(state, GameOverState) and not state.accepts_input()
        if not isinstance(state, PlayingState) and not game_over_locked:
            self.audio.play("ui_click", volume=0.6)
        self.fsm.on_mouse_press(x, y, button, modifiers)

    def on_mouse_release(self, x, y, button, modifiers):
        self.fsm.on_mouse_release(x, y, button, modifiers)
    
    def on_key_press(self, symbol, modifiers):
        """Handle key presses."""
        self.fsm.on_key_press(symbol, modifiers)

    def on_close(self):
        """Handle window close event."""
        self._finish_meta_run()  # a run still in progress is saved rather than lost
        parallel.close_batcher()  # the steering pool's worker processes stop with the window
        self._schedule_app_close()
        return True

    def _move_player(self, desired_vel: Vec2, dt: float) -> None:
        """Step the player toward desired_vel. Stock steering is instant; the Drift mutator eases it."""
        self.player.move_vel = mutators.steer_velocity(self.player.move_vel, desired_vel, dt, self.run_rules)
        self.player.pos = self.player.pos + self.player.move_vel * dt

    def _tick_shield_regen(self, dt: float) -> None:
        """Passive shield recharge from the run's rules (Iron Man). A no-op for every other run."""
        if not self.player:
            return
        self._shield_regen_carry = mutators.tick_shield_regen(
            self.player, self._shield_regen_carry, dt, self.run_rules, float(config.SHIELD_MAX),
        )

    def _input_dir(self) -> Vec2:
        """Get input direction from keyboard.
        
        Isometric controls:
        W: Northeast, S: Southwest, A: Northwest, D: Southeast
        """
        k = pyglet.window.key
        d = Vec2(0.0, 0.0)
        # W: Move northeast (x+, y+)
        if self.keys[k.W] or self.keys[k.UP]:
            d.x += 1
            d.y += 1
        # S: Move southwest (x-, y-)
        if self.keys[k.S] or self.keys[k.DOWN]:
            d.x -= 1
            d.y -= 1
        # A: Move northwest (x-, y+)
        if self.keys[k.A] or self.keys[k.LEFT]:
            d.x -= 1
            d.y += 1
        # D: Move southeast (x+, y-)
        if self.keys[k.D] or self.keys[k.RIGHT]:
            d.x += 1
            d.y -= 1
        return d

    def update(self, dt: float):
        """Update game logic."""
        frame_dt = max(0.0, min(float(dt), self._frame_dt_cap))
        self._render_time += frame_dt
        self.audio.update(frame_dt)
        if self.popups:
            self.popups.update(frame_dt)
        if getattr(self, "hud", None):
            self.hud.tick(frame_dt)
        self._accumulator += frame_dt
        steps = 0
        while self._accumulator >= self._fixed_dt and steps < self._max_catchup_steps:
            self._fixed_step()
            self._accumulator -= self._fixed_dt
            steps += 1
        if steps >= self._max_catchup_steps:
            # Drop extra accumulated time to avoid spiral-of-death stalls.
            self._accumulator = 0.0

    def _is_playing(self) -> bool:
        return type(self.fsm.current_state).__name__ == "PlayingState"

    def _fixed_step(self):
        """One fixed simulation step. While a run is recorded, its inputs are noted before the step and its hash after."""
        rec = self.recorder
        recording_now = rec is not None and self._is_playing()
        if recording_now:
            rec.before_step(self)
        self.fsm.update(self._fixed_dt)
        if recording_now:
            rec.after_step(self)

    def on_draw(self):
        """Render the game."""
        self.clear()
        self.fsm.draw()
        ci = float(getattr(getattr(self, "room", None), "combat_intensity", 0.0))
        hp_ratio = 1.0
        boss_active = False
        if getattr(self, "player", None):
            hp_max = max(1, int(getattr(self.player, "max_hp", 100)))
            hp_ratio = max(0.0, min(1.0, float(getattr(self.player, "hp", hp_max)) / float(hp_max)))
        if getattr(self, "state", None):
            boss_active = any(enemy_behavior_name(e).startswith("boss_") for e in getattr(self.state, "enemies", []))
        self.advanced_fx.render(self._render_time, ci, hp_ratio=hp_ratio, boss_active=boss_active)


def main():
    """Start the game. ``--record`` saves every finished run's inputs to replays/last_run.json (off by default)."""
    import sys
    record = "--record" in sys.argv[1:]
    try:
        _ = Game(record_runs=record)
        pyglet.app.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print("Fatal error:", e)
        raise


if __name__ == "__main__":
    main()
