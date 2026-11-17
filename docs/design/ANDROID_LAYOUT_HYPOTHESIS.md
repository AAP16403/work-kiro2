# Android Touch Layout Hypothesis

**Status:** Layout and interaction proposal only. Android touch input and an Android release target are not implemented or verified.

**Reference:** The supplied “Android Touch Control UI/UX Schematic” image. It is treated as a visual layout reference; labels and numeric values in the image are not assumed to match the current game code.

## 1. Product question

Can PLOUTO's open-arena, twin-stick combat work on a landscape Android phone without placing permanent controls or HUD panels over the center of the fight?

### Primary hypothesis

Use the lower-left corner for movement, the lower-right corner for aim and fire, and the space just above the right stick for Dash, Boost, and Ultra. Keep health and run status along the upper-left edge, a boss meter centered at the top only during boss fights, and combo/pause at the upper-right. The center remains available for ships, shots, hazards, and attack telegraphs.

The layout should scale from 16:9 to 20:9 by anchoring controls to the safe-area corners, not by stretching their touch targets. The extra width on 20:9 belongs mostly to the combat view.

## 2. What the current Rust code supports

The simulation already accepts the combat actions this layout needs through `SimInput`: a movement vector, a world-space aim point, held fire, held boost, a one-step Dash press, and a one-step Ultra press. The desktop app builds that input from the keyboard/mouse; gamepad code maps two sticks and buttons to the same shape. Auto-fire is separate: it is the persisted app setting `settings.auto_shoot` copied into `SimState::auto_shoot`, not a `SimInput` field. The current in-run HUD shows an “AUTO-FIRE OFF” status but has no run-time toggle. A touch quick-toggle therefore needs an app/settings-layer action as well as the ordinary `SimInput` adapter; it must update the persisted setting and take effect immediately.

The current HUD also carries information omitted from the reference schematic: weapon name and firing/reload progress, skin label, active temporary-effect and relic badges, and the arena-event/status line. The proposed combat layout must preserve the gameplay-relevant weapon and active-effect information. The cosmetic skin label can be collapsed first if the safe area is crowded. The existing HUD does not currently draw touch action buttons or a Dash cooldown gauge; those are proposed mobile controls backed by live simulation state, not existing widgets.

Relevant source:

- `plouto_rs/src/sim/state.rs` — `SimInput` fields.
- `plouto_rs/src/app.rs` — `build_sim_input`, current keyboard/mouse/gamepad mapping.
- `plouto_rs/src/input/mapping.rs` — gamepad deadzone and aim/fire threshold helpers.
- `plouto_rs/src/ui/hud.rs` — health, shield, boost, Dash, Ultra, combo, boss, and pause presentation.

The source currently handles mouse movement/buttons and gamepad input. No touch-event handler or Android-specific build configuration was found in the Rust app. Therefore the layout below is not an implementation claim.

## 3. Landscape screen map

All anchors below are percentages of the **usable safe-area rectangle**, after Android cutout and system-gesture insets. Sizes are in Android density-independent pixels (dp), not physical pixels. These are starting values for a prototype, not measurements from users.

```text
┌──────────────────────────── SAFE AREA ─────────────────────────────┐
│ [HULL] [SHIELD]  WAVE / SCORE     [BOSS HP + PHASE, when active]  xN II │
│ [AUTO-FIRE: ON/OFF]                                                  │
│                                                                      │
│                                                                      │
│                                                                      │
│  MOVE ZONE                                      [DASH] [BOOST]       │
│  floating stick                                  [ULTRA]             │
│                                                                      │
│  left thumb                                      AIM / FIRE ZONE      │
│                                                  right thumb          │
└──────────────────────────────────────────────────────────────────────┘
```

The schematic is deliberately sparse in the middle. It does not hide combat-owned telegraphs: boss warnings and floor markers remain visible where their attacks occur. It means only that persistent touch controls and decorative HUD elements should not occupy the central combat area.

| Element | Initial anchor | Starting size and behavior |
| --- | --- | --- |
| Safe-area margin | All edges | At least 16 dp from cutouts; avoid Android back-gesture edges for essential controls. Recompute after rotation, immersive-mode, and fold changes. |
| Hull and shield | Upper-left, about 3% x / 4% y | Compact paired bars with readable numbers or clear fill; keep labels short. |
| Wave and score | Upper-left, directly below hull/shield | One compact line; allow score truncation before covering the arena. |
| Auto-fire toggle | Below the upper-left status block | At least a 48 dp hit target. Persist the setting and show its state clearly. |
| Weapon and active run status | A compact secondary strip inside the top safe area, below the main status block when space allows | Keep the current weapon name and reload progress, plus active power-up/relic and arena-event cues. Collapse the skin label before hiding gameplay-relevant effects; ensure any collapsed badges can be inspected without covering combat. |
| Boss health and phase | Top center, only during a boss encounter | About 30–38% of safe width; 14–18 dp bar plus a short phase label. No empty placeholder outside boss fights. |
| Combo | Upper-right, left of pause | Compact multiplier and a short decay cue; hide or collapse before overlapping the boss meter. |
| Pause | Upper-right safe corner | At least a 48 dp hit target. Android Back should pause first during a run rather than immediately exit. |
| Movement stick | Center near 18% x / 81% y | Floating by default: a touch beginning in the left activation zone establishes the stick center. Clamp the thumb vector to a circular outer ring. Stick diameter starts around 152–192 dp. |
| Aim/fire stick | Center near 82% x / 81% y | Floating by default in the right activation zone. It controls aim independently from movement; matching the movement stick's size makes the two-thumb layout legible. |
| Dash | Above and inward from the aim stick, near 70% x / 59% y | Tap action; show ready/cooldown from live game state. Start around 56–68 dp visual size with a 60 dp or larger hit target. |
| Boost | Above the aim stick, near 81% x / 49% y | Hold action. Show current energy as a ring or short bar tied to live energy, not as a fixed timer. |
| Ultra | To the right of Dash and above the aim stick, near 92% x / 60% y | Tap action; show charge pips and the existing radial cooldown progression. Show unavailable/ready states distinctly. |

The action-button cluster must remain outside the active center of the right stick. If the safe area becomes too narrow, reduce gaps and shift the cluster upward before shrinking primary touch targets. On a tablet or foldable, retain the edge anchors and leave the center hinge/arena clear.

## 4. Touch interaction model

### 4.1 Two independent sticks

1. A touch beginning in the left activation zone claims movement until that same pointer ends or is cancelled. It maps to an eight-way/full analog vector; it must not jump to a second finger.
2. A touch beginning in the right activation zone claims aim. Its direction is independent of movement and is converted to the world-space aim point expected by `SimInput`.
3. Each control keeps its Android pointer ID for its full press. A third finger can hold Boost or tap Dash/Ultra while both sticks remain active.
4. A finger starting on a button belongs to that button, even if it later drifts over a stick zone. Hit zones should not overlap; the control that receives `ACTION_DOWN` retains ownership until `ACTION_UP` or `ACTION_CANCEL`.
5. Clamp stick vectors at the ring boundary. Start with the existing gamepad radial deadzone of 0.18 for parity; expose a small, understandable deadzone setting if device testing shows that users need a different value. The image's 0.15 is a candidate to compare, not a current game setting.

### 4.2 Aim and fire

- The right stick changes aim direction. Its endpoint should not be treated as a literal world coordinate; the touch adapter converts direction through the current camera transform into an `aim_world` point. The gamepad path currently uses a virtual point 260 world units from the player, which is a useful initial reference for this adapter.
- With Auto-fire on, the player fires at the current aim direction without requiring the right stick to be held continuously. Touching and dragging the right zone still moves aim. The quick-toggle updates the persisted `auto_shoot` setting through the app layer; it is not encoded as a special `SimInput` flag.
- With Auto-fire off, deliberate right-stick deflection fires when the normalized input exceeds the current gamepad aim/fire threshold (0.5). This keeps behavior familiar across gamepad and touch.
- Render the aim cue at the actual world aim point. Do not leave a bright cursor locked under the player's thumb or add a permanent center reticle that obscures incoming attacks.

### 4.3 Actions and truthful cooldowns

- Dash and Ultra generate one press edge on touch-down; holding a finger must not repeat them every frame.
- Boost remains held only while its owning pointer is down. Releasing, pausing, losing focus, receiving `ACTION_CANCEL`, or rotating the device clears it immediately.
- Dash visuals read the actual remaining cooldown. Do not hard-code the `1.5s` shown in the reference image because the current cooldown varies with difficulty and upgrades.
- Boost visuals read current energy and recharge state. Disable or dim the action only when the game rules say a boost cannot start.
- Ultra keeps charge pips and uses the existing cooldown fraction for its radial fill. Never substitute a countdown number that can disagree with the simulation.
- When a tap cannot activate an ability, retain a visible unavailable state rather than giving no feedback.

### 4.4 Touch cancellation and app lifecycle

On pause, Android interruption, window focus loss, app backgrounding, device rotation, or touch cancellation, clear every held touch state and release Boost/fire. Do not synthesize Dash or Ultra presses when a cancelled contact is removed. Rebuild the safe-area anchors after orientation or window-inset changes.

## 5. Responsive rules

### 5.1 Phone layouts

- The first Android prototype targets landscape gameplay. Do not rotate the arena and controls independently during a run; if rotation is supported, pause, relayout, and resume only after all contacts are released.
- At 16:9, protect the central combat viewport. At 20:9, keep the same dp-sized controls and use the additional width for world view rather than larger controls.
- Scale HUD text and control diameters in dp, with a lower bound for legibility and an upper bound that preserves separation. Do not scale every element by raw framebuffer pixels.
- Keep the left and right activation zones broad enough for imperfect thumb placement, but keep actual buttons out of the bottom system-navigation strip and side back-gesture regions.

### 5.2 Handedness and accessibility

- Offer a mirrored preset: movement on the right, aim/fire and action buttons on the left. Keep top HUD and pause anchored to the safe area.
- Offer fixed-stick and floating-stick modes. Fixed mode keeps a persistent low-opacity origin; floating mode reveals the origin and outer ring only while active, with a faint idle anchor if discoverability needs it.
- Provide control-size and control-opacity adjustments. Visual states must not rely on hue alone; combine icon, outline/fill, and charge/cooldown shape.
- Respect the game's reduced-motion setting for control pulses. Do not add continuous button animation that competes with boss telegraphs.

### 5.3 Menus, pause, and run rewards

The combat layout does not solve menus. Android menus, pause, settings, reward choices, and game-over screens need their own safe-area layouts, vertically scrollable when needed. Use at least 48 dp touch targets, visible pressed/selected states, and a single confirmation per tap. Keep Back behavior consistent: close an open dialog, then return to the prior screen; during active gameplay it opens pause.

## 6. Proposed implementation boundary

Keep touch parsing in the application/input layer. A future `input/touch.rs` (or an equivalent module) should own pointer IDs, zone capture, deadzones, vector clamping, and cancellation. It should produce the same `SimInput` fields used by keyboard/mouse and gamepad. Combat timers, movement, damage, cooldowns, and replay rules remain owned by the deterministic simulation.

The UI layer should receive normalized safe-area geometry and live simulation state. It should draw controls from the actual state source: hull/shield values, boost energy, Dash cooldown, Ultra charges/cooldown, boss state, and pause. It must not duplicate cooldown constants or create touch-only versions of gameplay rules.

Before committing to an Android build, verify the full dependency and window stack on the intended Android targets, including `winit`, `wgpu`, persistence paths, and any desktop-only input or audio dependencies. This layout document adds no sound work.

## 7. Validation plan for a future Android prototype

No mobile validation has been performed. Once an Android target and touch adapter exist, evaluate at least one narrow 16:9 phone, one 20:9 phone with a cutout, and one larger/tablet or foldable viewport. Validate both handedness presets and fixed/floating sticks.

### Required interaction scenarios

1. Move in all directions while independently aiming and firing in all directions.
2. Switch Auto-fire during a run; verify the state is obvious and the chosen policy takes effect immediately.
3. Hold Boost while steering and aiming; release, pause, background, rotate, and cancel contacts; confirm no stuck boost or fire remains.
4. Tap Dash and Ultra with another stick held; verify one activation per tap and live cooldown/charge presentation.
5. Trigger a boss bar, combo, level-up/reward view, and urgent warning; verify no important cue is cut off by notches, gesture insets, controls, or the player's fingers.
6. Use Android Back, app switching, and notification shade interruptions; verify pause/resume and input clearing.
7. Check one-handed reach, accidental button presses, thumb occlusion, text size, and reduced-motion behavior with real players.

### Evidence to collect

- Screenshot captures at the target aspect ratios and insets, with actual HUD and worst-case enemy/effect density.
- Touch traces proving simultaneous pointer ownership and correct `ACTION_CANCEL` cleanup.
- Task completion and mis-activation observations for movement, aim/fire, Boost, Dash, Ultra, pause, and reward selection.
- Battery, thermal, frame-time, and GPU measurements on representative Android hardware.

Treat the measurements as a usability review, not a pass/fail claim derived from a desktop render. Do not tune final positions from the schematic alone.

## 8. Initial decision summary

| Decision | Hypothesis | Confidence before mobile review |
| --- | --- | --- |
| Gameplay orientation | Landscape is the best first target for independent twin-stick control. | Medium |
| Stick arrangement | Floating dual sticks anchored to broad left/right zones will fit varied phone sizes. | Low; requires thumb-reach review |
| Fire policy | Auto-fire on by default, with right-stick deflection firing when Auto-fire is off. | Medium; maps to current gamepad policy |
| Action placement | Dash, Boost, and Ultra above the right stick will remain reachable without covering the center. | Low; requires device and hand-size review |
| Status placement | Vitals left, boss bar center only when active, combo/pause right. | Medium; requires notched-device and long-label captures |
| Simulation coupling | Touch only adapts input; deterministic combat rules remain unchanged. | High; matches current `SimInput` boundary |

**Next product decision:** build a touch-only layout prototype after confirming Android target/toolchain support. Tune safe-area margins and stick sizes from real-device captures and thumb-reach feedback before shipping Android controls.
