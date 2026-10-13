# Animation rework and optimization: plan

Status: planned, not started. The batch launches after workflow `wf_657ad88e-ba8` (tests, fix, docs, report) finishes, because it needs a clean base.

## Why

User feedback, in order:

1. Some shooting effects lag the game badly, in particular the auto blast and the small-range bomb types.
2. The small-range bomb (Flak Battery) needs a full rework.
3. Everything looks static and solid. The game needs fluidity and expression.
4. A full animation rework, in depth, with effects and optimization.
5. Weapon pickups need timers. They are permanent today.
6. Speed, damage and fire-rate boosts stay permanent. The user clarified this; do not change them.

## Decisions

- **Weapon pickup timers:** a weapon pickup equips the weapon for `WEAPON_PICKUP_SECONDS` (default 20, in config.py). On expiry the player reverts to the weapon they had before. The upgrade-only rule still applies. The HUD weapon chip shows a countdown.
- **Wave-clear weapon upgrades stay permanent.** They are rewards, not pickups. Open question for the user.
- **"Auto blast"** is read as the Rapid Fire auto-fire stream. Confirm with the user.
- **"Small-range bomb"** is read as the Flak Battery. Its damage numbers stay unless the rework needs a change.
- Gameplay numbers stay the same, except the weapon timers. Determinism tests must still pass.

## Stages and agents (10 agents)

### Stage 0: foundation (1 agent)

- Writes `anim.py`: tween, spring, easing, time-based stepping, and fixed-size object pools. No per-frame allocation.
- Writes `test_w4_anim.py`.
- Branch: `wave4/base`.

### Stage 1: implementers (6 agents in parallel, one worktree each)

Each agent owns the files listed. Each writes its own `test_w4_<key>.py`.

| Key | Owns | Work |
|---|---|---|
| player | player_art.py, the player functions in visuals.py | idle, banking into movement, aim look, thruster flicker, dash afterimage, hit stagger, death |
| enemies | the enemy functions in visuals.py | spawn-in, per-type idle bob, attack wind-up, hit spring, dissolve on death. No gameplay changes. Telegraphs stay visible. |
| fx | projectile_art.py, particles.py, glow.py | trails, muzzle flashes, impacts, shockwaves. Pooled. Flak Battery rework. Auto-fire cost reduced. |
| ui | hud.py, hud_widgets.py, popups.py, menu transition code | banner easing, popup motion, screen transitions, title motion. Respects REDUCE_MOTION. |
| perf | map.py, starfield.py, batching in the draw path | driven by `tools/bench.py` at waves 1, 15 and 29. Removes per-frame allocations. Batches draw calls. |
| weapontimer | powerup.py, player.py, the weapon branch in states.py update, the HUD weapon chip | the timed weapon pickup described above |

### Stage 2: integrate (1 agent)

- Merges the six `wave4/*` branches into `goal/animation`, starting from `wave4/base`.
- Resolves conflicts, mainly in visuals.py and states.py.
- Runs the test files that cover the changed areas.

### Stage 3: verify (2 agents in parallel)

- Agent 1 runs every test file and `tools/bench.py` at waves 1, 15 and 29, and compares against the baseline.
- Agent 2 captures screens at 980x620 and 1920x1080 and checks them for clipping, overlap and motion.

## Acceptance

- Every test file exits 0 with no SKIP lines.
- Determinism tests still pass.
- Median frame time at waves 1, 15 and 29 is not worse than the baseline. Report the measured numbers; do not claim targets that were not measured.
- No per-frame allocation in the new hot paths.
- REDUCE_MOTION disables the ambient motion and keeps the telegraphs.
- The screens at both sizes show no clipping. The motion is described from the captures, not assumed.

## Risks

- visuals.py is touched by the player, enemies and fx agents. Expect merge conflicts there and in states.py.
- Animation can hide gameplay telegraphs. The telegraphs stay on top.
- Performance numbers depend on the machine. Report them as measured on this machine only.

## Status

- [ ] Workflow wf_657ad88e-ba8 finished
- [ ] Stage 0 foundation
- [ ] Stage 1 implementers
- [ ] Stage 2 integrate
- [ ] Stage 3 verify
- [ ] Committed on goal/animation
- [ ] `main` fast-forwarded locally (not pushed)

## Weapon pickup timers (confirmed plan)

- A weapon pickup equips its weapon for `WEAPON_PICKUP_SECONDS` (config.py, default 20).
- On expiry the player reverts to the weapon held before the pickup.
- A second weapon pickup while one is active replaces it and restarts the timer. The upgrade-only rule still applies, so a lower-ranked pickup never downgrades the player.
- The HUD weapon chip shows the countdown, in the same style as the other timers.
- Wave-clear weapon upgrades stay permanent by default. Changing that is one constant, if the user asks for it.
- Owner: the `weapontimer` agent. Files: powerup.py, player.py, the weapon branch in states.py update, the HUD weapon chip.

## Optimization: measured baseline

Source: `scratchpad/bench_after.json`, run 2026-10-13 00:33, before the consolidated branch. pyglet 2.1.19, `pyglet_debug_gl` false, window 980x620, 600 frames per wave. Times are per-frame medians and p95 in ms.

| wave | update median | draw median | draw p95 | total median |
|---|---|---|---|---|
| 1 | 2.77 | 25.35 | 38.90 | 28.12 |
| 8 | 6.04 | 28.41 | 43.13 | 34.46 |
| 15 | 2.59 | 26.54 | 41.68 | 29.13 |
| 22 | 7.95 | 32.09 | 45.82 | 40.04 |
| 29 | 10.82 | 34.16 | 53.14 | 44.98 |

- Draw dominates. It takes 25 to 34 ms per frame, against 3 to 11 ms for update.
- The profile puts `visuals.sync_scene` at about half of the cumulative draw time (80 s of 151 s).
- These numbers predate the consolidated branch. Re-measure on `goal/consolidated` before claiming any improvement.

Hot spots found by grep (not yet profiled on the consolidated branch):

- `visuals.py`: 104 shape constructions and 9 `.delete()` calls. This is create and delete churn.
- `map.py`: 30 shape constructions. `_rebuild_floor` builds polygons on every rebuild, and background orbs and grid lines are built the same way.
- `hud.py`: 13 shape and label constructions.
- `projectile_art.py`: the `_impact_*` functions and `flak_detonation` create particles on every hit.
- `popups.py` already pools its items, with no constructions.

Optimization targets. Each one is measured before and after; none is claimed in advance:

1. Pool the per-entity shapes in `visuals.sync_scene`. Set position, colour and radius each frame instead of creating and deleting.
2. Build the static map layers (background, grid, floor) once per arena into their own batch, and rebuild only when the arena changes.
3. Enforce the existing particle caps (`particle_soft_cap` 450, `particle_hard_cap` 650) and drop low-priority effects first.
4. Give per-hit impacts a pooled particle list, so a hit creates no new shapes.
5. In the HUD, keep the Labels and update their text only when the value changes.

Acceptance: the draw median at waves 1, 15 and 29 goes down. Report before and after from `tools/bench.py` on the same machine with `pyglet_debug_gl` false. No per-frame allocation in the pools.

## Multi-core: what it can and cannot do

### Current state

- `parallel.py` has a spawn-context process pool (`SteerBatcher`), wired into the enemy update.
- `PARALLEL_STEER_ENABLED = False` in config.py. It is off by default.
- Reason: batched steering gives different results from the serial path over a run. Turning it on changes gameplay.
- Measured by the wave 2 implementer, median ms at 20 and 30 enemies:

| path | 20 enemies | 30 enemies |
|---|---|---|
| serial | 4.09 | 7.50 |
| inline batch | 4.19 | 6.62 |
| process pool | 6.18 | 7.52 |

- The process pool is slower at 20 enemies and no faster at 30. The inter-process cost is larger than the steering it saves at these counts.

### Why multi-core cannot fix the main bottleneck

- The draw path (25 to 34 ms median at baseline) runs on the main thread and calls OpenGL. Worker processes cannot submit draws.
- Simulation (update, 3 to 11 ms) is the only part that could move off the main thread, and it is not the bottleneck.

### Where multi-core can help

1. **Asset loading.** File reads release the GIL, so threads help with I/O. Pure-Python decoding does not release it, so use processes for decoding. Only the GPU upload stays on the main thread.
2. **Procedural geometry.** A worker computes the floor polygon points and the orb positions and returns plain tuples. The main thread creates the shapes from them.
3. **Offline tooling.** The synth and bench tools can use processes freely, since they don't touch the window.

### Decision needed

- Keep batch steering off. This matches the current gameplay and is the recommendation.
- Or enable it and accept that results differ from the serial path.

### Acceptance for any multi-core change

- Measured on this machine with `tools/bench.py`.
- No gameplay change unless the user approves it.
- Determinism tests pass with batch steering off.

## Multi-core batch (launched as workflow wf_9dce6374-411)

Branches and worktrees, all from `goal/consolidated` at ef93c82:

| branch | worktree | owner | work |
|---|---|---|---|
| wave5/steer | mc-steer | build:steer | persistent worker processes and shared-memory arrays for batched steering. No per-frame pickling. Threshold set from measurement. Flag stays off. |
| wave5/geometry | mc-geometry | build:geometry | arena geometry calculation moved to `geometry_build.py`, computed in a worker for the next arena. Vertex data must match exactly. |
| wave5/loading | mc-loading | build:loading | WAV decode moved to a process pool at startup. Pyglet resource creation stays on the main thread. |
| wave5/integration | mc-integration | integrate | merges the three branches |
| (detached) | mc-baseline | measure:bench | baseline, for comparison |

Stages: build (3 agents), integrate (1), test (3, all 43 files), measure (1, alone).

Acceptance:

- Default gameplay unchanged. `frame_digests` in the bench JSON must match between baseline and integration while the parallel flag is off.
- Every test file exits 0.
- Steering: measured serial against pooled at 20, 30 and 60 enemies. The threshold must come from the measurement.
- Geometry: vertex data identical for waves 1, 8, 15, 22 and 29. Rebuild times reported before and after.
- Loading: startup time reported before and after.

Expected reality, to check against the numbers and not to claim in advance: the draw step (25 to 34 ms median) is main-thread OpenGL and is not affected by any of these three. The steering pool can only help if the crossover is below the enemy counts a real wave reaches. Gains are most likely in simulation spikes, arena rebuilds and startup.

Decision still open: enabling batched steering by default changes gameplay results, so it stays off until the user approves.

## Batch status: wf_d40f1ba7-c16 (animation, bomb, optimization, weapon timers, steering pool)

Base: main 63cab47 via wave4/base. Stages and branches:

- Foundation (1): wave4/base, anim.py and test_w4_anim.py.
- Implement (6, parallel, each in its own worktree): wave4/player, wave4/enemies, wave4/fx (auto-fire lag, Flak Battery rework, per-weapon bullet effects), wave4/ui, wave4/perf (draw-path churn, static map batch, HUD label updates), wave4/weapontimer.
- Integrate (1): wave4/integration. Enables the steering pool with a stable per-run ordering index in place of id(enemy), so batched runs repeat. PARALLEL_STEER_ENABLED becomes True with a comment giving the reason.
- Verify (1): all test files in four parallel groups, then bench before and after on the same machine.
- Visual (1): screens before and after at 980x620 and 1920x1080, each PNG inspected.

Not claimed in advance. Results go into this file when the batch reports.

Known from earlier measurements, left off by default:

- Arena geometry worker (wave5/geometry): no measurable gain. Off.
- Asset preload (wave5/loading): no measurable gain. Off.
