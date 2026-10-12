# Changelog

## Unreleased

This release adds meta progression (skins, achievements and the Hangar), new power-ups, opt-in
mutators, daily runs, arena events, two elite affixes, a boss rage phase, a deterministic run
recorder, accessibility options and a set of developer tools. It also reworks enemy telegraphs,
screen shake and the Game Over screen, and fixes the bugs listed under Fixes.

### Gameplay

**Runs and balance**

- Auto-fire starts ON for every run. LMB still toggles it.
- Player damage scales the whole shot, so multi-pellet and bonus damage follow the same numbers.
  At the base damage of 10 nothing changes.
- The damage pickup adds +1 base damage (it used to add +4).
- Weapons have a rank based on expected single-target damage per second. Weapon pickups equip
  only an upgrade; otherwise they give a +20 shield top-up.
- Each wave clear has a 50% chance to roll a weapon, and it is equipped only if it outranks your
  current one. Boss weapon drops are always upgrades.
- Past wave 5 the enemy head count grows by 1 every 3 waves (first at wave 8), up to +8 enemies.
- The shield caps at 120 (SHIELD_MAX) everywhere: pickups, the HUD shield bar and the weapon
  top-up.
- Sustained attack cooldowns for spitters, ranged enemies, tanks, engineers and bombers use half
  of the wave's spawn attack multiplier. Bosses keep their own cooldowns.
- Boss rewards no longer offer perks that would do nothing, such as shield at its cap or dash at
  its floor.
- Ultra charge capacity is per run. You start with 2, and permanent Ultra rewards raise it to at
  most 4.

**Enemy telegraphs**

- Flyers hold still for a 0.45 s windup before a dash and lock the dash target during it.
- Chasers plant for a 0.22 s windup before a lunge, with a locked direction.
- Chargers redraw their aim line during the windup and lock onto the charge point.
- Brutes fix their charge direction when the telegraph starts and draw a red charge lane, clipped
  at the arena wall.
- Boss laser warnings last 0.30 s (was 0.22 s). Womb core warnings are a violet ring, and
  thunder warnings are clearer.

**Game Over and runs**

- The Game Over screen shows a run summary: survival time, kills, best combo, leaderboard rank,
  and the points needed to pass the entry above.
- NEW HIGH shows only on a strict improvement. A tied score does not count, and a first run of
  0 points does not count.
- Keyboard replay: ENTER, Return, Keypad Enter or R retries; ESC or M goes to the main menu.
- Input is locked for 1.0 s while the summary reveals (GAME_OVER_REVEAL_S).

**Power-ups (new)**

- Ricochet (8 s): player bullets bounce once off the arena edge instead of being removed.
- Homing (6 s): player bullets steer gently toward the nearest live enemy within 260 units.
- Time Slow (4 s): enemies and enemy bullets move at half speed. You move at full speed.
- Magnet (10 s): the pickup magnet radius is tripled and pickups are pulled in faster.
- Drone (12 s, rare): a drone orbits you and fires every 0.6 s at the nearest enemy within 300
  units. Picking up another drone refreshes the timer; it does not stack.

**Mutators (new, opt-in)**

Mutators change the rules of one run. Pick them on the title screen as toggle chips. The combined
score multiplier shows on the Game Over screen.

- Glass Cannon: your damage x1.5, max HP 60%.
- Bullet Hell: enemy bullets fly 25% faster, and each volley has one extra bullet.
- Drift: less acceleration and more momentum.
- Frenzy: enemies move 20% faster and waves are 25% larger, still under the wave cap.
- Iron Man: no pickups spawn, but shields recharge slowly over time.

**Skins, Hangar and achievements (new)**

- Eight or more skins recolour your ship and its bullets. Each skin has an unlock rule (score,
  wave, bosses defeated, kills, or an achievement). The default skin keeps the original look.
- The Hangar is the fifth button on the title screen. It shows skin cards with live previews, the
  unlock rule and whether each skin is locked, unlocked or selected. Click an unlocked skin to
  select it. An achievements gallery lists each achievement and whether you have earned it.
- About 20 achievements, including First Blood, Boss Hunter, No-Damage Wave, Elite Slayer, a 6x
  combo and surviving ten waves. Newly earned achievements appear as toasts.

**Daily run (new)**

- One seeded run per local date. Every player gets the same seed and the same mutator on that
  date. A daily run cannot be combined with other mutators.
- Each date keeps its own best score and wave. The Game Over screen shows today's best and whether
  this run beat it. Daily runs add nothing to progress beyond their own record and normal
  achievements.

**Arena events (new)**

- From wave 4 on, about one in three non-boss waves has an arena event. A wave never gets more
  than one, and boss waves never get one.
- Meteor Shower: three impact zones, each marked 1.5 s before it lands and each dealing area
  damage.
- Solar Flare: a rotating beam sweeps a sector of the arena after a 2 s warning.
- Nebula Cloud: for 8 s, enemies near the cloud gain shields. The cloud is visible.

**Elite affixes (new)**

- Splitter: on death the elite splits into two smaller enemies of the same class at half HP. A
  split does not split again.
- Reflector: every 3 s it reflects the next player bullet that hits it, sending the same damage
  back as an enemy projectile.
- Volatile, Swift and Shielded are unchanged. Elite kills give the 2.5x elite score multiplier.

**Boss rage (new)**

- At 35% HP each boss enters rage. Its attack cooldowns shrink by 25%, and each volley gets one
  extra projectile or pulse. A rage banner and a warning sound mark the change.
- Boss kills end with a camera flash and a victory fanfare.

**Options (Gameplay)**

- Difficulty: Easy, Normal or Hard. The change applies to the next run.
- Arena size: saved when you release the slider.
- Mutators: toggle chips on the title screen, saved in user_settings.json.

### Visuals

**Screen shake and motion**

- Shake impulses stack, and the total is capped (SHAKE_CAP), so long fights no longer pile up
  unlimited shake.
- Player damage shakes by the HP you lost (2 to 8 px), after shields. Hits absorbed by a shield
  add no shake.
- Option: Screen Shake Full, Reduced or Off. Cycle it in Settings. The default is Full. The
  setting saves when you change it.
- Option: Reduced motion (default off) turns off shake, pulses, shimmer and parallax drift in one
  switch. The config default is REDUCE_MOTION = False.

**Characters, projectiles and effects**

- The player is a pod-robot character with an idle bob, squash and stretch, a dash stretch, a
  blink about every three seconds, and a worried face below 30% HP. The config flag USE_PLAYER_ART
  (default on) switches back to the old ship drawing.
- Each weapon has its own bullet look, trail and impact. Critical hits leave a gold trail, and
  enemy bullets are red-orange so you can tell them apart.
- Glow effects (projectile heads, pickups, enemy eyes, the thruster and the dash afterimage) draw
  from a capped glow pool. The config flag ENABLE_GLOW (default on) turns them off.
- A parallax starfield sits behind the arena, and the arena rim pulses with combat intensity.
- Enemies squash when hit and spring back. Below 30% HP a red vignette fades in and pulses slowly.
- Ultra fires with a white flash tinted by its variant colour.
- Floating damage numbers, a boss health bar with a damage trail, centre-screen banners for wave
  start, wave clear and boss arrival, and kill bursts and pickup rings.

**HUD and menus**

- The HUD uses the shared UI theme. It shows a radial Ultra gauge with the charge count, a weapon
  chip with a colour swatch and crit chance, a skin badge, and a toast stack for achievements.
- The status line is priority-fitted. The boss segment shows the boss name, low-priority segments
  drop out with a "+N" count, and the line ends with AUTO ON or AUTO OFF.
- The title screen has a redesigned logo with a shimmer, a tagline, key hints, a starfield
  background and a horizon line. The main menu has a controls footer.
- The reward menu shows animated cards and supports keyboard selection with 1, 2, 3 and ENTER.
- The Guide has entries for every new system: the Hangar and skins, achievements, mutators, the
  new power-ups, the drone, arena events, the Splitter and Reflector affixes, boss rage and the
  daily run.

**Accessibility options**

- Option: Colour-blind safe enemy palette (default off). It swaps the enemy colours for a palette
  that stays distinguishable under deuteranopia and protanopia.
- Option: High-contrast HUD (default off). It puts a dark plate behind every HUD number and
  raises text brightness.
- Settings can be used from the keyboard. Arrow keys move focus across the controls and ENTER
  activates them. Mouse behaviour is unchanged.

### Audio

- Audio system: pooled voices, per-sound rate limits, crossfading music, and ducking on pause and
  reward screens. The game runs silently if no audio device is found.
- The existing 32 sound effects and two music loops (menu and battle) are rendered by
  tools/synth_sfx.py and tools/synth_music.py.
- 21 new sound effects, written to `assets/audio/sfx_<name>.wav`: `ricochet`, `homing_lock`,
  `time_slow_on`, `time_slow_off`, `magnet`, `drone_spawn`, `drone_fire`, `event_warn`,
  `meteor_impact`, `flare_sweep`, `nebula_hum`, `toast`, `achievement`, `daily_record`, `reflect`,
  `split`, `rage_warn`, `victory_fanfare`, `skin_select`, `mutator_toggle` and `hangar_move`.
  Each one is rendered offline at 22050 Hz mono 16-bit with a peak at or below 0.75, and the output
  is deterministic.
- Rare power-ups use the rare pickup sound and ring.
- Option: Music and SFX volumes. They are saved to user_settings.json when you leave Settings.

### Tools

- tools/bench.py: a headless, seeded benchmark for waves 1, 8, 15, 22 and 29. It records per-frame
  update and draw times and the top 15 cProfile entries, writes a JSON report to --out, and prints
  a summary. A benchmark mode compares forced 20 and 30 enemy waves with and without the parallel
  path.
- tools/playtest.py: a headless bot plays seeded runs at easy, normal and hard. It checks invariants
  every frame, detects softlocks (no damage dealt for 60 s of game time while enemies remain), and
  writes a JSON report. It exits non-zero on a crash, an invariant violation or a softlock.
- tools/screens.py: captures the title, settings, Guide pages, a combat frame, the pause menu, the
  reward menu, the Game Over screen and the Hangar at 980x620 and 1920x1080. It reports overlapping
  labels in overlaps.json and exits non-zero on overlaps unless --allow-overlaps is passed.
- tools/smoke_exe.ps1: starts dist\Plouto\Plouto.exe, checks that it is still running after a wait,
  stops it, and checks that every WAV the code uses is bundled.
- tools/balance_sim.py: offline balance tables built from the real weapon, enemy and wave code. It
  covers damage per second and time to clear a wave for waves 1 to 30, power-up value outliers, and
  the score and difficulty effect of each skin and mutator. --csv writes the same data to a CSV.
- replay.py: records a run's seed, difficulty, skin, mutators and per-step inputs, and replays them
  to the same state hash. Option: recording (default off) is turned on in Settings or with a flag.
- parallel.py: a process pool and batch enemy steering. Large waves use it only above a measured
  threshold, and the results match the serial path exactly.
- tools/synth_sfx.py and tools/synth_music.py accept --jobs N and write byte-identical files.
- requirements.txt pins the tested pyglet version. build_all.bat installs from it and no longer
  upgrades pyglet on every build.
- kiro2_game.spec bundles every asset folder the game reads, and a check fails if the code opens a
  file the build does not include.
- The browser build (vercel_site/) mirrors the balance, cooldown, reward, Game Over and elite score
  rules.

### Fixes

**Menus and settings**

- The Easy, Normal and Hard buttons no longer raise an error. The highlight updates on click.
- The arena size slider no longer crashes. It saves once on release instead of on every drag tick,
  so the room is rebuilt once per drag.
- The reward menu no longer shows "--" placeholder cards. With fewer than three choices it shows
  only the real cards, centred.
- The Elites entry in the Guide builds its 2.5x clause from config.ELITE_SCORE_MULT.
- Clicks during the Game Over input lock no longer play the click sound.

**Combat and enemies**

- Bosses no longer die from contact. They hurt the player and push them clear.
- Hatched egg sacs no longer block a wave from clearing.
- The womb core pulse lasts long enough to hurt after it arms.
- A firerate pickup can no longer slow the player.
- Ultra respects shields and elite death effects.
- The swarm queen respects its add cap.
- Elite kills apply ELITE_SCORE_MULT on desktop and in the browser build.
- The chaser lunge cooldown no longer counts its windup twice.
- Formation coordination no longer moves flyers, chasers or chargers during their windup or cooldown,
  so a stop is a real stop.
- Bullet hits shake in proportion to their damage, and fixed shake at player-hit sites is removed so
  player damage owns the shake.
- Flak no longer becomes a permanent top weapon that waves 5 and 6 can lock in. Flak fires three
  pellets.
- The shield caps read SHIELD_MAX everywhere. No literal 120 cap remains.

**Rendering and performance**

- Screen shake uses its own random source, so drawing effects no longer change run state.
- Depth sorting uses the unshaken position, so shake no longer moves shapes between batch groups
  on every frame. Projectiles are created in their batch group.
- The map floor frees its old shapes on rebuild, so no ghost floor or GPU leak remains. Scanlines
  and the background grid survive resizes.
- The wave chip text stays inside its border, and the pause hint moved out of the score panel.
- Per-frame rewrites of unchanged particle colours, map opacities and visual geometry are removed
  where profiling showed them.

**Save data**

- progress.json, user_settings.json and high_scores.json carry a version field. Older and
  unversioned files migrate, and loading never raises.
- Every save goes through one atomic write (temp file, flush, then replace).
- A corrupt file is renamed to <name>.corrupt-<n> once, and the game starts with defaults. The bad
  data is kept, not overwritten.
