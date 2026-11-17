# Gamepad support

Status: implemented on 2026-11-17. Not tested on real hardware. No human play-test has been done. Values below are read from the code at that date.

Crate: `plouto_rs` (Rust, wgpu/winit). Pad input uses `gilrs = "0.11"` (`plouto_rs/Cargo.toml`).

## 1. Supported controllers

- Any device that gilrs 0.11 reports as a gamepad. Which models work depends on gilrs's own device mapping. No specific model has been tested.
- Force feedback is needed for vibration. A pad without force feedback is accepted for input and gets no vibration. The code checks `is_ff_supported()` and does nothing otherwise.
- Analog triggers are read from the gilrs `LeftTrigger2` / `RightTrigger2` button data. A pad that exposes its triggers only as an axis has no analog trigger value. The code deliberately has no Z-axis fallback, because an axis with a non-zero rest value would read as half-pressed. On such a pad, use RB / LB for fire and boost.
- Button names in the UI follow the Xbox layout: A, B, Y, Start, RT, LT, RB, LB. These are the labels the code uses (`ui`/`glyphs`), not a claim about every pad's printed labels.

## 2. Bindings

### 2.1 Gameplay (`AppScreen::Playing`)

| Input | Action | Where it is handled |
|---|---|---|
| Left stick | Move. Radial deadzone applied. Keyboard movement wins if any move key is held. | `app.rs` `build_sim_input`, `mapping::stick_to_move` |
| Right stick | Aim. Sets a virtual aim point (see section 3). | `build_sim_input`, `mapping::stick_to_aim_dir` |
| Right stick pushed past 0.5 (after deadzone) | Fire (held) | `build_sim_input`, `AIM_FIRE_THRESHOLD` |
| RT (right trigger above 0.35) | Fire (held) | snapshot, `TRIGGER_THRESHOLD` |
| RB (`RightBumper`) | Fire (held) | `build_sim_input` |
| A (`South`) | Dash. Mapped to the Space key. | `pad_button_key` |
| LT (left trigger above 0.35) | Boost (held) | snapshot, `TRIGGER_THRESHOLD` |
| LB (`LeftBumper`) | Boost (held) | `build_sim_input` |
| Y (`North`) | Ultra. Mapped to the Q key. | `pad_button_key` |
| Start (`Start`) | Pause (Escape key) | `pad_button_key` |
| B (`East`) | Nothing while playing | `pad_button_key` |
| D-pad, left stick menu direction | Nothing while playing. Menu navigation is suppressed in `Playing`. | `pump_gamepad` |

### 2.2 Menus and sub-screens (anything other than `Playing`)

| Input | Action | Where it is handled |
|---|---|---|
| D-pad | 4-way navigation (sent as Arrow keys) | `pump_gamepad`, `dpad_dir` |
| Left stick | 4-way navigation when the raw magnitude is above 0.6. Dominant axis wins. Ties go to vertical. No deadzone is applied to this check. | `mapping::stick_to_nav` |
| A (`South`) | Confirm (Enter). Counts as "confirm held" for the game-over screen. | `pad_button_key`, `is_confirm_held` |
| B (`East`) | Back (Escape) on sub-screens, pause, game over, and boss reward. Ignored on the main menu so it cannot quit the app. | `pad_button_key` |
| Start (`Start`) | Back (Escape) on any screen except the main menu. Ignored on the main menu. | `pad_button_key` |

D-pad and left stick share one repeat path. If both are active, the D-pad direction is used. Navigation is also suppressed while a screen fade is active.

### 2.3 Menu navigation repeat (`mapping::NavRepeat`)

- A new direction fires at once.
- If the same direction is still held after 0.35 s (`NAV_INITIAL_DELAY`), it repeats.
- After the first repeat, it repeats every 0.12 s (`NAV_REPEAT_INTERVAL`).
- Releasing the stick or D-pad (`None`) resets the state.
- The frame delta is clamped to 0..0.1 s in `pump_gamepad`.

## 3. Aiming model

- The right stick sets a direction. The position is `aim_point = player.pos + last_aim_dir * AIM_DISTANCE`, where `AIM_DISTANCE = 260.0` world units.
- `last_aim_dir` starts at (1, 0).
- While the right stick is inside the deadzone, `stick_to_aim_dir` returns `None` and `last_aim_dir` is kept. The aim point holds still after the stick is released.
- In gamepad mode, the virtual aim point is written back to `mouse_screen` each sim step (converted with `to_iso_cam`). The reticle and camera follow it. `aim_world` in `SimInput` is set to this point.
- Moving the mouse (or any key or click) switches to keyboard/mouse mode. Aiming then returns to the cursor.

## 4. Deadzone and thresholds

Exact constants from the code.

| Name | Value | File | Use |
|---|---|---|---|
| `DEFAULT_DEADZONE` | 0.18 | `input/mapping.rs` and `save/settings.rs` | Default stick deadzone |
| `GAMEPAD_DEADZONE_MIN` | 0.05 | `save/settings.rs` | Lower bound of the setting, and the wrap value |
| `GAMEPAD_DEADZONE_MAX` | 0.5 | `save/settings.rs` | Upper bound of the setting |
| `GAMEPAD_DEADZONE_STEP` | 0.02 | `ui/screens.rs` | One settings step. Values are rounded to 0.01. |
| `TRIGGER_THRESHOLD` | 0.35 | `input/mapping.rs` | Trigger counts as pressed (fire, boost, device switch) |
| `AIM_FIRE_THRESHOLD` | 0.5 | `input/mapping.rs` | Right stick after deadzone counts as fire. Also used on raw stick magnitude for device switching. |
| `CLAIM_AXIS_THRESHOLD` | 0.5 | `input/gamepad.rs` | Axis movement that claims the active pad |
| `NAV_THRESHOLD` | 0.6 | `input/mapping.rs` | Left stick magnitude for menu direction. Raw value, no deadzone. |
| `NAV_INITIAL_DELAY` | 0.35 s | `input/mapping.rs` | Hold time before menu repeat starts |
| `NAV_REPEAT_INTERVAL` | 0.12 s | `input/mapping.rs` | Menu repeat interval |

### 4.1 Radial deadzone (`apply_radial_deadzone`)

- `mag = sqrt(x² + y²)`. If `mag` is not finite, the result is (0, 0).
- `dz` is clamped to 0..0.99. A non-finite `dz` uses `DEFAULT_DEADZONE`.
- If `mag <= dz`, the result is (0, 0).
- Otherwise, `out_mag = min((mag - dz) / (1 - dz), 1)`. The direction is kept.

The deadzone is applied to the move stick and the aim stick. It is not applied to the menu nav check or to the device-switch checks, which use raw values.

### 4.2 Stick and trigger values

- Stick values are clamped to -1..1. Y is positive upward.
- Triggers are read from gilrs button data and clamped to 0..1.

## 5. Device auto-switching

The active device is `InputDevice::KeyboardMouse` or `InputDevice::Gamepad` (`input/glyphs.rs`). It drives the controls hint, the confirm and back labels, and whether gamepad mode applies in gameplay (`gamepad_mode()` = gamepad support on AND device is Gamepad).

Switches to **Gamepad** when any of these happen (and gamepad support is on):

- A pad button is pressed (any button, even one with no mapping) or released.
- Raw left or right stick magnitude is above 0.5.
- Either trigger is above 0.35.
- A D-pad direction or a left-stick menu direction is active.

Switches to **KeyboardMouse** when any of these happen:

- A keyboard key is pressed.
- A mouse button is pressed.
- The cursor moves more than 4 px (squared distance above 16).
- The active pad disconnects.

Does **not** switch device:

- A pad that is only connected or plugged in (`PadEvent::Connected`). An idle pad must not take over aiming.
- Pad events while gamepad support is off. These are drained and ignored.

The pad claim rule is separate. The active pad is the most recent one that sends a button press, or an axis move beyond 0.5. At startup, the first connected pad becomes active.

When gamepad support is off, the menu receives `KeyboardMouse` regardless of the last device.

## 6. Vibration

### 6.1 When it plays

Vibration plays only when all of these hold:

- Gamepad support is on.
- `gamepad_vibration` is on.
- The device is `Gamepad`.
- The active pad supports force feedback.

It is requested in `step` for each sim substep (up to `MAX_SUBSTEPS = 4` per frame). Only the single strongest request from that substep's events is kept.

### 6.2 Event table (`input/rumble.rs`)

`strong` is the low-frequency motor. `weak` is the high-frequency motor. All values are clamped to 0..1.

`frac = clamp((health_damage + 0.5 * shield_damage) / PLAYER_HP, 0, 1)`, with `PLAYER_HP = 100`.

| Event | strong | weak | duration |
|---|---|---|---|
| Player hit, shield only (no health damage) | 0 | 0.25 + 1.5 * frac | 80 ms |
| Player hit, health damage, frac >= 0.2 | 0.45 + 0.55 * frac | 0.6 + 0.4 * frac | 200 + 150 * min(frac, 1) ms |
| Player hit, health damage, frac < 0.2 | 0 | 0.3 + 2.0 * frac | 80 ms |
| Player killed (killing blow, not rejected) | 1.0 | 0.85 | 450 ms |
| `GameOver` | 1.0 | 1.0 | 500 ms |
| `BossDeath` | 1.0 | 0.9 | 600 ms |
| Banner whose title starts with "PHASE" | 0.8 | 0.6 | 450 ms |
| Shockwave with `max_radius >= 150` | 0.4 + 0.4 * t | 0.4 + 0.3 * t | 250 ms, where `t = clamp((max_radius - 150) / 250)` |
| `KillBurst` with `big: true` | 0.2 | 0.35 | 120 ms |

Other damage results (enemy damage, rejected hits) produce no vibration.

Selection: the candidate with the largest `max(strong, weak)` wins. On a tie, the earlier event keeps the slot.

### 6.3 Rate limiting

- Only one rumble plays at a time. Each new request stops the running effect.
- In `App::request_rumble`, while a rumble is still running (`now < rumble_until`), a request with strength `max(strong, weak)` less than or equal to the running one is dropped. A stronger request replaces it.
- When the running rumble's duration ends, any request plays.
- `RUMBLE_STOP` (zero strength, zero duration) stops the motors. It is sent by `clear_transient_input`, which runs from `enter_screen` (`app.rs:251`) and from the run-start path (`app.rs:376`).
- In `GamepadManager::rumble`, a zero request only stops the current effect. The effect plays with `Repeat::For(duration)` and a flat envelope.

## 7. Settings

File: `user_settings.json`. It lives in the data directory from `resolve_data_file`. The `PLOUTO_DATA_DIR` environment variable overrides that directory (`assets.rs`).

| Key | Type | Default | Load behaviour | Save behaviour |
|---|---|---|---|---|
| `gamepad_enabled` | bool | `true` | Read with default `true` | Written as bool |
| `gamepad_vibration` | bool | `true` | Read with default `true` | Written as bool |
| `gamepad_deadzone` | number | `0.18` | Finite values clamped to 0.05..0.5. Other values use the default. | Clamped to 0.05..0.5. A non-finite value is written as 0.18. |

- Unknown keys are kept and written back.
- All three keys are in the known-keys list, so they are not stored as extra keys.
- Save uses the versioned writer and merges with the file's existing keys.

Settings UI (`ui/screens.rs`), row 4 of the left column, "controller options":

- Chip "Gamepad: ON/OFF": toggles `gamepad_enabled`.
- Chip "Vibration: ON/OFF": toggles `gamepad_vibration`.
- Chip "Deadzone: 0.xx": a mouse click advances by one step, wrapping from 0.50 back to 0.05. Keyboard or pad adjust moves one step (0.02) per input, clamped to 0.05..0.50.

## 8. Replay compatibility

- The pad feeds the same `SimInput` as the keyboard and mouse. `build_sim_input` produces `move_dir`, `aim_world`, `fire_held`, `boost_held`, `dash_pressed`, and `ultra_pressed`. Recording stores these inputs.
- A recording made with a pad replays without a pad. Playback reads `SimInput` only.
- Rumble and device state are not part of the simulation and are not recorded.
- The current `SIMULATION_RULES_VERSION` is 13 (`sim/replay.rs`). Replays recorded before the current rules version are rejected for version mismatch (`replay.rs`, the check for `rules_version`).
- `--replay` playback never grants achievements. `--record` runs skip progress writes.

## 9. Code map

| File | Responsibility |
|---|---|
| `plouto_rs/Cargo.toml` | `gilrs = "0.11"` dependency |
| `plouto_rs/src/input/mod.rs` | Declares the `gamepad`, `mapping`, `rumble`, `glyphs` modules |
| `plouto_rs/src/input/gamepad.rs` | `GamepadManager`: gilrs setup and polling, active-pad claim, `PadButton`, `PadEvent`, `PadSnapshot` cache, trigger reads, force-feedback effect (`rumble`). Never panics; inert if gilrs fails to start. |
| `plouto_rs/src/input/mapping.rs` | Pure helpers: radial deadzone, `stick_to_move`, `stick_to_aim_dir`, `stick_to_nav`, `NavRepeat`, and the constants in section 4 |
| `plouto_rs/src/input/rumble.rs` | `RumbleRequest`, `rumble_for_events` (event table in section 6.2). No gilrs dependency. |
| `plouto_rs/src/input/glyphs.rs` | `InputDevice`, control hint text, confirm and back labels |
| `plouto_rs/src/app.rs` | `pump_gamepad` (events, device switching, menu nav), `pad_button_key`, `dpad_dir`, `gamepad_mode`, `build_sim_input` (aim point and fire/boost), `request_rumble` and `RUMBLE_STOP`, `clear_transient_input`, rumble call in the sim loop, device reset on mouse and key input |
| `plouto_rs/src/save/settings.rs` | `gamepad_enabled`, `gamepad_vibration`, `gamepad_deadzone`: defaults, load clamping, save clamping, known-key list |
| `plouto_rs/src/ui/screens.rs` | Settings rows and chips, deadzone step and cycle (`GAMEPAD_DEADZONE_STEP`), click handling |
| `plouto_rs/src/sim/replay.rs` | Current `SIMULATION_RULES_VERSION = 13` and the version check |
| `plouto_rs/src/assets.rs` | `resolve_data_file` (location of `user_settings.json`) |

## 10. Known limitations

- Not tested on real hardware. No human play-test has been done.
- Pads that expose triggers only as an axis have no analog trigger. Use RB / LB instead.
- Menu navigation and the device-switch checks use raw stick values, not the deadzone-applied values. A stick that drifts above 0.6 (nav) or 0.5 (switch) can still act.
- A pad that is only connected does not switch the device. The first real input is needed.
- B does nothing during play, and Y does nothing in menus. This is the current mapping, not a bug, but it is unlisted in the on-screen hint.
- The on-screen hint (`controls_hint`) lists only the gameplay bindings. It does not show menu bindings.
- Vibration is best effort. Pads without force feedback, or with force feedback reported unreliably, may give no or partial output. Nothing reports this to the player.
- The gamepad path has no dedicated automated test listed in the verified facts.
- Open policy questions (not gamepad-specific): abandoned or quit runs count toward `runs_played`-based achievements, and daily retries count as runs.

## 11. Manual test checklist (human, with a real pad)

Setup: start a fresh save or move `user_settings.json` aside. Confirm the defaults in section 7 on first run.

Connection and device switching
- [ ] Pad plugged in before launch: no device switch on startup. Keyboard hint still shows.
- [ ] Press any pad button: menu hint and labels switch to the pad (A, B, Start).
- [ ] Press a key: labels switch back to keyboard (Enter, Esc).
- [ ] Move the mouse more than a few pixels: switches back to keyboard.
- [ ] Unplug the pad during the menu: device returns to keyboard. No crash.
- [ ] Replug the pad: no switch until a button or stick is used.

Menus
- [ ] D-pad moves focus in all four directions on the main menu, settings, hangar, and guide.
- [ ] Left stick moves focus. Holding a direction repeats after about 0.35 s, then about every 0.12 s.
- [ ] A confirms. B backs out of settings, hangar, guide, and pause. B does nothing on the main menu and does not quit.
- [ ] Start backs out of sub-screens. Start does nothing on the main menu.

Gameplay
- [ ] Left stick moves the ship smoothly with the 0.18 default deadzone. Small drift does not move the ship.
- [ ] Right stick aims. The reticle and camera follow the aim point about 260 units ahead.
- [ ] Releasing the right stick keeps the last aim direction.
- [ ] Right stick pushed firmly fires. Pushing lightly does not fire unless the stick passes 0.5.
- [ ] RT fires. RB fires.
- [ ] A dashes. Y uses ultra. LT and LB boost.
- [ ] Start pauses. The pause menu opens and resumes correctly.
- [ ] B does nothing while playing.
- [ ] D-pad and left stick do not move menu focus during play.

Settings
- [ ] Gamepad ON/OFF chip: OFF disables all pad input, including menu nav and rumble. ON restores it.
- [ ] Vibration ON/OFF chip: OFF stops all rumble. ON restores it.
- [ ] Deadzone chip click: 0.18 to 0.20 to ... to 0.50, then wraps to 0.05.
- [ ] Deadzone adjust with keyboard or pad: changes by 0.02 per step, stays within 0.05..0.50.
- [ ] Changes persist after restart. Check `user_settings.json` for `gamepad_enabled`, `gamepad_vibration`, `gamepad_deadzone`.
- [ ] Setting `gamepad_deadzone` to 0.9 or a string in the file loads as clamped or default values.

Vibration (pad with force feedback)
- [ ] Small hit: short light pulse (about 80 ms).
- [ ] Heavy hit (20 percent or more of max HP): longer, stronger rumble (200 to 350 ms).
- [ ] Shield-only hit: short light tick.
- [ ] Death: strong rumble (500 ms).
- [ ] Boss phase banner ("PHASE II" or "PHASE III"): rumble.
- [ ] Boss defeated: strong rumble (600 ms).
- [ ] A stronger hit replaces a running rumble. A weaker one during a rumble is dropped.
- [ ] Vibration does not play when the device is keyboard/mouse.

Replay
- [ ] Record a run with a pad, then replay it with the pad disconnected. The run replays the same.
- [ ] A replay file from before rules version 13 is rejected.

Pads without force feedback and pads with analog-axis triggers
- [ ] Pad without force feedback: no crash, no vibration, input works.
- [ ] Pad with triggers as axes: RT and LT do not respond. RB and LB do.
