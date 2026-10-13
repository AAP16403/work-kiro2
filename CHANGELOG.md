# Changelog

## Unreleased

This release adds meta progression (skins, achievements and the Hangar), five new power-ups including
the rare Drone, opt-in mutators, daily runs, arena events, two elite affixes, a boss rage phase, a
deterministic run recorder, accessibility options and a set of developer tools. It also reworks enemy
telegraphs, screen shake and the Game Over screen. It includes the swarm work merged on main since
af8449a. The fixes are listed under Fixes, and the parts that are missing or only partly done are
listed under Known gaps at the end.

### Gameplay

**Runs and balance**

- Auto-fire starts ON for every run. LMB still toggles it.
- Player damage scales the whole shot, so multi-pellet and bonus damage follow the same numbers. At
  the base damage of 10 nothing changes.
- The damage pickup adds +1 base damage (it used to add +4).
- Each weapon has a rank: its expected single-target damage per second. A weapon pickup equips only
  if it outranks your current weapon; otherwise it gives a +20 shield top-up.
- Each wave clear has a 50% chance to roll a weapon, and it is equipped only if it outranks your
  current one.
- Boss kills drop a weapon pickup, which is an upgrade when a higher-ranked weapon is available and a
  +20 shield top-up otherwise. Boss kills also drop one heal, shield or laser pickup.
- Past wave 5 the regular enemy head count grows by 1 every 3 waves (first at wave 8), up to +8
  enemies.
- The shield caps at 120 (SHIELD_MAX) everywhere: pickups, the HUD shield bar and the weapon top-up.
- Sustained attack cooldowns for spitters, ranged enemies, tanks, engineers and bombers use half of
  the wave's spawn attack multiplier. Bosses keep their own cooldowns.
- Boss rewards skip perks that would do nothing, such as shield at its cap, dash at its floor or Ultra
  at its hard cap.
- Ultra charge capacity is per run. You start with 2, and permanent Ultra rewards raise it to at most
  4.

**Enemy telegraphs**

- Flyers hold still for a 0.45 s windup before a dash and lock the dash target during it.
- Chasers plant for a 0.22 s windup before a lunge, and the lunge direction is locked when the windup
  starts.
- Chargers redraw their aim line during the windup and lock onto the point the line shows.
- Brute bosses fix their charge direction when the telegraph starts and draw a red charge lane, clipped
  at the arena wall.
- Boss laser warnings last 0.30 s (was 0.22 s). Womb core warnings are a violet ring.

**Game Over and runs**

- The Game Over screen shows a run summary: survival time, kills, best combo, leaderboard rank, and the
  points needed to pass the entry above.
- NEW HIGH SCORE shows only on a strict improvement. A tied score does not count, and a first run of 0
  points does not count.
- Keyboard: ENTER, Return, Keypad Enter or R retries; ESC or M goes to the main menu.
- Input is locked for 1.0 s while the summary reveals (GAME_OVER_REVEAL_S). Clicks in that window are
  ignored.

**Power-ups (new)**

- Ricochet (8 s): player bullets bounce once off the arena edge. A bullet that has bounced and reaches
  the edge again is removed.
- Homing (6 s): player bullets steer toward the nearest live enemy within 260 units, with the turn rate
  capped at 2.4 rad/s.
- Time Slow (4 s): enemies, their attacks and enemy projectiles run at half speed. You and your bullets
  stay at full speed.
- Magnet (10 s): the pickup magnet radius is tripled and pickups are pulled in 1.5x faster.
- Drone (12 s, rare): one drone orbits you and fires every 0.6 s at the nearest enemy within 300 units.
  Its shots use your damage, crits and boss damage. Picking up another drone refreshes the timer; it
  does not stack.
- Homing, Time Slow and Drone are rare; Ricochet and Magnet are common. Re-picking a timed power-up
  refreshes its timer.

**Mutators (new, opt-in)**

Mutators change the rules of one run. Pick them on the title screen as toggle chips. The combined score
multiplier of the run is shown on the Game Over screen.

- Glass Cannon (score x1.25): your damage x1.5, and max HP 60%.
- Bullet Hell (score x1.20): enemy shots fly 25% faster, and every volley gets one extra shot.
- Drift (score x1.10): steering eases in, and the ship slides for a while after you let go.
- Frenzy (score x1.30): enemies move 20% faster, and each wave has 25% more enemies before the wave
  cap. On normal the cap binds from wave 6, so the extra enemies show in waves 1 to 5.
- Iron Man (score x1.15): no pickups spawn, but your shield recharges at 2 points per second.

**Skins, Hangar and achievements (new)**

- Ten skins recolour your ship, its bullets and its trails. The default skin keeps the original look.
  Each skin has an unlock rule: a best score of 5,000 or 25,000, wave 10, 250 total kills, 2 or 5
  bosses defeated, or the Combo x6, Elite Slayer or Untouchable achievement.
- The Hangar is the fifth button on the title screen. It shows a card for each skin with a live preview,
  its unlock rule and a LOCKED, UNLOCKED or SELECTED chip. Click an unlocked card, or press ENTER on it,
  to select it and save the choice. Locked cards are refused.
- The achievements tab lists all 20 achievements as EARNED or LOCKED, with the date earned. They include
  First Blood, Boss Hunter, Untouchable (a wave cleared without taking a hit), Elite Slayer, Combo x6 and
  Survivor (ten waves in one run). Newly earned achievements appear as toasts.

**Daily run (new)**

- One seeded run per local date. Every player gets the same seed and the same mutator, which is picked
  from the five mutators by the date's seed. A daily run cannot be combined with other mutators.
- Start it with the Daily Run button on the title screen. Try Again replays the same day's run until
  you return to the menu.
- Each date keeps its own best score and wave in progress.json. The Game Over screen shows today's best
  and whether this run beat it. Only a strictly higher score replaces the record.
- A daily run also counts toward your lifetime totals and achievements, like any other run. See Known
  gaps.

**Arena events (new)**

- From wave 4 on, about one in three non-boss waves has an arena event, chosen from the run seed. A wave
  never gets more than one, and boss waves never get one.
- Meteor Shower: three impact zones, each marked 1.5 s before it lands and each dealing area damage.
- Solar Flare: a sector is marked for 2 s, then a rotating beam sweeps across it.
- Nebula Cloud: after a 1 s warning, the visible cloud lasts 8 s, and enemies inside it gain shield.
- With Reduced motion the flare sweep and the cloud pulse stop. The warnings and the damage stay.

**Elite affixes (new)**

- Splitter: on death the elite splits into two smaller enemies of the same class at half HP, placed
  around the death spot. A copy has no affix, so it never splits again.
- Reflector: every 3 s it sends the next player bullet that hits it back as an enemy shot with the same
  damage, with a flash and a sound.
- Volatile, Swift and Shielded are unchanged. Elite kills give the 2.5x elite score multiplier.

**Boss rage (new)**

- At 35% HP each boss enters rage, once. Its attack cooldowns shrink by 25%, and each volley gets one
  extra projectile or pulse. A rage banner and a warning sound mark the change.
- Boss kills end with a camera-style flash and a victory fanfare.

### Visuals

**Screen shake and motion**

- Shake impulses stack, and the total is capped at 14 px (SHAKE_CAP), so long fights do not pile up
  unlimited shake.
- Weapon hits in one frame add at most 3 px, and bigger hits scale with their damage.
- Player damage shakes by 2 to 8 px, in proportion to the HP that got through the shield (2 px plus
  0.25 px per HP, capped at 8 px). Hits absorbed by a shield add no shake.
- Screen Shake has Full, Reduced (half strength) and Off. The default is Full. See Options.
- Reduced motion turns off shake, pulses, shimmer and parallax drift in one switch. See Options.

**Characters, projectiles and effects**

- The player is a pod-robot character with an idle bob, squash and stretch, a dash stretch, a blink about
  every three seconds, and a worried face below 30% HP. USE_PLAYER_ART (default on) switches back to the
  old ship drawing.
- Each weapon has its own bullet look, trail and impact: a Basic Gun tracer, Spread Shot pellets, Rapid
  Fire dashes, a Heavy Cannon slug with smoke, a Plasma Rifle orb with a ring afterimage, a Hyper Railgun
  streak, and Flak Battery shells that burst. Critical shots leave a gold trail, and enemy shots are
  red-orange. Unknown weapon names use the basic style.
- Glow effects (projectile heads, pickups, enemy eyes, the thruster and the dash afterimage) draw from a
  capped pool of 96 quads. ENABLE_GLOW (default on) turns them off.
- A three-layer parallax starfield sits behind the arena, and the arena rim pulses with combat intensity.
- Enemies squash when hit and spring back. Below 30% HP a red vignette fades in and pulses slowly.
- Ultra fires with a white flash tinted by its variant colour, drawn over the shockwave ring.
- Floating damage numbers, a boss health bar with a damage trail, kill bursts and pickup rings.

**HUD, title and menus**

- The HUD uses the shared UI theme. It shows a radial Ultra gauge with the charge count (it pulses at
  full charge unless Reduced motion is on), a weapon chip with a colour swatch and crit chance, a skin
  chip, and a toast stack for achievements, one toast at a time for 2.5 s each.
- The status line is priority-fitted. The boss segment keeps the boss name, low-priority segments drop
  out with a "+N" count, and the line ends with AUTO ON or AUTO OFF.
- Centre-screen banners mark wave start, wave clear, boss arrival and boss rage.
- The title screen has a shimmering wordmark, a tagline, six buttons (Start Game, Daily Run, Guide,
  Settings, Hangar, Quit), a row of mutator chips, a row of key hints, a starfield and a horizon line.
  Reduced motion stops the shimmer and the bobbing.
- The reward menu shows animated cards. Keys 1, 2 and 3 highlight a card, and ENTER or SPACE confirms
  it. With fewer than three choices it shows only the real cards, centred.
- The Hangar has a skin grid (4 columns at 980x620, 5 at 1920x1080) and an achievements tab. Arrow keys
  move the cursor and wrap at the edges, TAB switches tabs, ENTER selects and ESC goes back.
- The Guide has entries for every new system: the Hangar and skins, achievements, the five mutators, the
  new power-ups and the drone, arena events, the Splitter and Reflector affixes, boss rage and the daily
  run. Its numbers come from config and from the definitions in the code.

### Audio

- Audio system: pooled voices (24 by default), a minimum gap between repeats of the same sound,
  crossfading music, and ducking on pause and reward screens. The game runs silently if no audio device
  is found.
- The 32 existing sound effects and two music loops (menu and battle) are rendered by tools/synth_sfx.py
  and tools/synth_music.py.
- 21 new sound effects, written to `assets/audio/sfx_<name>.wav`: `ricochet`, `homing_lock`,
  `time_slow_on`, `time_slow_off`, `magnet`, `drone_spawn`, `drone_fire`, `event_warn`, `meteor_impact`,
  `flare_sweep`, `nebula_hum`, `toast`, `achievement`, `daily_record`, `reflect`, `split`, `rage_warn`,
  `victory_fanfare`, `skin_select`, `mutator_toggle` and `hangar_move`. Each one plays on its own event.
  Each is 22050 Hz mono 16-bit, with a peak between 0.46 and 0.74 and deterministic output.
- Rare power-ups play the rare pickup sound and the pickup ring. Time Slow and Magnet then play their
  own cue.

### Tools

- tools/bench.py: a headless, seeded benchmark of the enemy AI update on forced waves. It defaults to 20
  and 30 mixed enemies (--wave). It times a serial loop, an inline batch and a pooled batch, and reports
  medians over --repeats. --out writes a JSON report with those medians and the top 15 cProfile entries.
- tools/bench_frames.py: the frame-loop benchmark for waves 1, 8, 15, 22 and 29. A seeded scripted bot
  plays a hidden 980x620 window, Game.update and on_draw are timed per frame, and SHA-256 digests check
  determinism. It writes a JSON report (--out) and can compare against an earlier one (--compare).
- tools/bench_steer.py: compares serial, inline-batch and pooled steering. The measured crossover is
  about 24 live enemies: the pool is slower at 8 and 16, and 1.6x to 2.9x faster at 32.
- tools/playtest.py: a headless bot plays seeded runs at easy, normal and hard. It checks invariants after
  every fixed step, and detects softlocks (60 s of game time with no enemy losing HP or shield, being
  killed or leaving). It writes a JSON report (--out) and exits 1 on a crash, an invariant break or a
  softlock.
- tools/screens.py: captures the title, settings, every Guide tab's pages, a combat frame, and the pause,
  reward, Game Over and Hangar screens at 980x620 and 1920x1080. It reports overlapping text labels in
  overlaps.json, and exits 1 on overlaps unless --allow-overlaps is passed.
- tools/balance_sim.py: offline balance tables from the real weapon, enemy and wave code. It covers damage
  per second and time to clear a standard wave for waves 1 to 30, the value of each power-up pickup with
  outliers more than 40% from the median, and the score multiplier and difficulty effect of each skin and
  mutator. Markdown goes to stdout; --csv PATH writes a CSV.
- tools/smoke_exe.ps1: starts dist\Plouto\Plouto.exe, waits -WaitSeconds (default 8), checks that the
  process is still running, stops it, and checks that the build holds every asset the code opens,
  including the WAV files in assets\audio. It exits 0 or 1.
- replay.py: records a run's seed, difficulty, skin, mutators and per-step inputs, and replays them to the
  same state hash. Recording is off by default; the --record flag saves each finished run to
  replays/last_run.json.
- parallel.py: a spawn-context process pool for batch enemy steering, and a thread-based loader for asset
  reads. Batch steering is off by default (PARALLEL_STEER_ENABLED = False). When it is on, it runs at 32
  or more live enemies (PARALLEL_STEER_MIN_ENEMIES), and its results match the serial path exactly.
- tools/synth_sfx.py and tools/synth_music.py accept --jobs N and write files byte-identical to the serial
  run.
- requirements.txt pins the tested pyglet version and the build packages. build_all.bat installs from it
  and no longer upgrades pyglet on every build. It also runs asset_manifest.py before PyInstaller.
- kiro2_game.spec bundles the assets/fonts and assets/audio folders. asset_manifest.verify_bundle runs
  before the build, so the build fails if the code opens a file the bundle does not include.
- vercel_site/ (the browser build) mirrors the weapon upgrade rule, the wave head-count ramp, the boss
  reward filter and the elite score multiplier. The rest of this release is not mirrored (see Known gaps).

### Options

- Difficulty: Easy, Normal or Hard, in Settings. The change applies to the next run.
- Arena size: saved when you release the slider.
- Screen Shake: Full, Reduced or Off. Cycle it in Settings; it saves when you change it. The default is
  Full.
- Reduced motion (default off): one switch that turns off shake, pulses, shimmer and parallax drift.
  The config default is REDUCE_MOTION = False.
- Colour-blind safe enemy palette (default off): swaps the enemy colours for a palette that stays
  distinguishable under deuteranopia and protanopia.
- High-contrast HUD (default off): a dark plate behind every HUD number, and brighter HUD text.
- Advanced FX: an On or Off toggle in Settings.
- Music and SFX volumes: sliders, saved to user_settings.json when you leave Settings.
- Mutators: toggle chips on the title screen, saved in user_settings.json.
- Settings can be used from the keyboard: arrow keys move focus, ENTER activates, and Left and Right
  adjust a grabbed slider. Mouse behaviour is unchanged.
- Config flags in config.py: USE_PLAYER_ART, ENABLE_GLOW, ENABLE_PARALLAX_STARS, ENABLE_DASH_AFTERIMAGE
  and ENABLE_RIM_PULSE all default on. PARALLEL_STEER_ENABLED defaults off.

### Fixes

**Menus and settings**

- The Easy, Normal and Hard buttons no longer raise an error. The highlight updates on click.
- The arena size slider no longer crashes. It saves once on release instead of on every drag tick, so
  the room is rebuilt once per drag.
- The reward menu no longer shows "--" placeholder cards. With fewer than three choices it shows only
  the real cards.
- The Guide's Elites entry builds its 2.5x clause from config.ELITE_SCORE_MULT.
- Clicks during the Game Over input lock no longer play the click sound.
- The Game Over screen no longer draws the HUD boost panel through its title.
- Guide rows at 980x620 no longer overlap: three rows per page, with the name, threat and lore lines
  placed so they do not collide.
- The Hangar shows readable unlock text instead of a raw rule, and its cards no longer overlap their
  previews.
- The HUD panels no longer show a solid shine bar across the labels and chip text.

**Combat and enemies**

- Bosses never die from contact. They hurt the player and push them clear.
- Enemies that leave a fight without a kill, such as hatched egg sacs, no longer block a wave from
  clearing.
- A firerate pickup can no longer slow the player. It only lowers the fire-rate interval.
- Ultra respects shields and elite death effects.
- The swarm queen respects its add cap.
- Elite kills apply ELITE_SCORE_MULT on desktop and in the browser build.
- The chaser lunge cooldown no longer counts its windup twice.
- Formation coordination no longer moves flyers, chasers or chargers during their windup or cooldown, so
  a stop is a real stop.
- Bullet hits shake in proportion to their damage. The fixed shake at player-hit sites is removed, so
  player damage owns the shake.
- Flak no longer becomes a permanent top weapon that waves 5 and 6 can lock in. It is held back until
  wave 7, and it fires three pellets.
- The shield caps read SHIELD_MAX everywhere. No literal 120 cap remains.

**Rendering and performance**

- Screen shake uses its own random source, so drawing effects no longer change run state.
- Depth sorting uses the unshaken position, so shake no longer moves shapes between batch groups on every
  frame.
- The map floor frees its old shapes on rebuild, so no ghost floor or GPU leak remains. Scanlines and the
  background grid survive resizes.
- The wave chip text stays inside its border, and the pause hint moved out of the score panel.
- Per-frame rewrites of unchanged particle colours, map opacities and shape geometry are removed. The
  particle check compared RGBA with RGB, so every live dot was rewritten each frame.

**Save data**

- progress.json, user_settings.json and high_scores.json carry a version field. Older and unversioned
  files migrate, and loading never raises.
- Every save goes through one atomic write (a temp file in the same folder, flush, then os.replace).
- A corrupt file is renamed to <name>.corrupt-<n> once, and the game starts with defaults. The bad data is
  kept, not overwritten.

### Known gaps

- Daily runs are not progress-free. A daily run counts toward lifetime totals (runs played, kills, best
  wave and best score) and can unlock skins, like any other run. The brief asked for only the daily
  record and normal achievements.
- Run recording has no Settings toggle. Only the --record flag turns it on.
- ThreadedLoader in parallel.py is implemented and tested, but no startup path reads assets through it.
- The browser build (vercel_site/) does not have Ricochet, Homing, Time Slow, Drone, Splitter, Reflector,
  boss rage, sustained cooldown scaling, the Game Over input lock, Screen Shake, mutators, daily runs,
  arena events, the Hangar or achievements.
- Frenzy's larger spawn count shows only in waves 1 to 5 on normal, because the wave cap binds from wave 6.
- The scene ring's radius is still rewritten every frame. A fix needs a geometry rewrite, which was not done.
