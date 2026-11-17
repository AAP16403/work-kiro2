# Android Version — Layout and Implementation Plan

**Status (2026-11-17):** Plan only. Nothing in this document is implemented. It turns the layout proposal in [`design/ANDROID_LAYOUT_HYPOTHESIS.md`](../design/ANDROID_LAYOUT_HYPOTHESIS.md) into build steps, and adds what that proposal leaves out: the menu screens, the DPI and safe-area layout system, and the Android port work the layout depends on.

**Mockups:** [`design/android_ui/android_ui_mockups.html`](../design/android_ui/android_ui_mockups.html) shows every screen described below. The matching desktop redesign is in [`design/desktop_ui/desktop_ui_mockups.html`](../design/desktop_ui/desktop_ui_mockups.html).

**Goal:** a landscape Android build of PLOUTO with twin-stick touch controls. Every screen should be usable by touch alone on a 6" phone, the combat area should stay clear, and the desktop build and the deterministic simulation should not change.

---

## 1. What the code does today (and what blocks Android)

| Area | Current behavior | Android consequence | Where |
| --- | --- | --- | --- |
| Entry point | `main.rs` binary: `fn main()`, CLI args, `run_desktop_game` | Android needs a `cdylib` with `android_main(AndroidApp)`. CLI record/replay are desktop-only. | `src/main.rs`, `src/app.rs:68` |
| Window lifecycle | `resumed()` creates the window, GPU and renderer once, and returns early after that. There is no `suspended()`. | Android destroys the native window when the app goes to the background. The surface must be dropped on `suspended` and recreated on `resumed`. | `src/app.rs:1484` |
| UI scale | `ui_scale(w,h) = min(w/980, h/620).clamp(0.85, 1.85)` works in **raw pixels** and ignores DPI | On a 2400×1080 phone, s = 1.74, so 14 pt text is about 32 px, or about 2 mm tall. That is unreadable. The layout needs density-aware scaling. | `src/ui/theme.rs:15` |
| Reference canvas | Every screen's `layout()` assumes a canvas of about 980×620 units | A landscape phone is about 800×360 dp. A 620-unit-tall menu either doesn't fit or shrinks to an illegible size. Menus need **compact layouts**, not just a different scale. | `ui/screens.rs` `fn layout` ×5, `ui/hangar.rs` |
| HUD anchors | Hull, Shield and Boost panel at **bottom-left** (248×112 units); buffs and relics are stacked above it | The panel sits where the move stick goes and has to move to the top-left (see §3). | `src/ui/hud.rs:1163` |
| Input | Keyboard, mouse and gilrs gamepad go through `build_sim_input` into `SimInput` | There are no touch events. `SimInput` is already the right boundary, so touch becomes a third adapter. | `src/app.rs:704`, `sim/state.rs:34` |
| UI hit testing | `on_mouse_move` / `on_mouse_press(x, y, w, h)` on each screen, in y-up coordinates | These can be reused for taps. Menus have no scrolling, no drag gestures and no hit-slop. | `ui/screens.rs`, `ui/hangar.rs` |
| Assets | `resolve_asset` searches up from the working directory and the exe path; fonts and audio use `fs::read` / `fs::read_dir` | APK assets are not on the filesystem. They need the AssetManager or must be extracted on first launch. | `src/assets.rs:5`, `render/text.rs:158`, `audio/mod.rs:488` |
| Data dir | `%LOCALAPPDATA%`, macOS, XDG and `PLOUTO_DATA_DIR` | Should use `AndroidApp::internal_data_path()`. | `src/assets.rs:37` |
| GPU | `Backends::PRIMARY`, default limits, prefers Mailbox, bloom uses an `Rgba16Float` render target | Vulkan is fine on most phones. On a GLES fallback, `Rgba16Float` may not be renderable, so a bloom fallback is needed. Mailbox is rarely offered on Android, but the existing Fifo fallback handles that. | `render/mod.rs:34`, `render/bloom.rs:85` |
| Audio | rodio 0.20 (cpal) | cpal on Android uses AAudio/Oboe, which needs `libc++_shared.so` packaged. Audio must pause on `suspended`. | `audio/mod.rs` |
| Gamepad | gilrs 0.11 | Android support is unverified. Gate it with `cfg` if it doesn't build; Android pads also arrive as key events through winit. | `input/gamepad.rs` |
| Toolchain on this PC | Only `x86_64-pc-windows-msvc` installed; no Android SDK/NDK; Java 8 | Needs `aarch64-linux-android` (+ `x86_64-linux-android` for the emulator), NDK r26+, SDK 34, JDK 17 and `cargo-ndk`. | — |

**Constraint that must not change:** combat, timers, cooldowns and replays stay inside the deterministic sim. Touch only produces `SimInput`. `SIMULATION_RULES_VERSION` (13) is **not** bumped for input-only touch work.

---

## 2. Layout system (the foundation for every screen)

### 2.1 `LayoutFrame` replaces `(view_w, view_h)` in UI code

New module `src/ui/frame.rs`:

```rust
pub struct LayoutFrame {
    pub size_px: (f32, f32),     // full framebuffer
    pub safe: UiRect,            // px, y-up, after cutout + gesture insets
    pub px_per_dp: f32,          // 1.0 on desktop (96 dpi baseline), from winit scale_factor on Android
    pub class: FormClass,        // Desktop | PhoneCompact | Phone | Tablet
    pub hud_s: f32,              // scale for HUD widgets
    pub menu_s: f32,             // scale for menu layouts
    pub touch: bool,             // draw touch controls / touch-first menus
}
```

- **Desktop:** `px_per_dp = 1`, `safe` = the full window, `hud_s = menu_s = ui_scale(w,h)`. This must reproduce the current numbers exactly, so desktop rendering is unchanged.
- **Android:** `px_per_dp = window.scale_factor()`. `w_dp = safe.w / px_per_dp`, `h_dp = safe.h / px_per_dp`.
  - `hud_s = px_per_dp × hud_size_pref` (default 1.0). One HUD reference unit equals one dp, and the HUD is anchored to corners.
  - `menu_s = px_per_dp × clamp(min(w_dp/980, h_dp/620) × 1.35, 0.8, 1.25)`. The text floor is 12 sp in the compact variant (`pt_px(..., min_pt)` gets a dp-aware minimum).
- **Form classes** (by `h_dp` of the landscape safe area):
  - `PhoneCompact`: below 400 dp (most phones, about 340–390 dp).
  - `Phone`: 400–599 dp.
  - `Tablet`: 600 dp or more. Desktop-like layouts are allowed, centered at a maximum width of 1100 dp.

Migration rule: each `layout(view_w, view_h)` becomes `layout(&LayoutFrame)`. Inside, `s` comes from the frame, and positions use `frame.safe` instead of `0..w`. This step is mechanical and screen-by-screen, and desktop output must stay pixel-identical (checked with the existing UI tests plus new layout tests).

### 2.2 Safe area

- Insets come from the platform layer (§6.3): display cutout ∪ system bars ∪ the mandatory system-gesture insets. They are recomputed on `Resized`, `ScaleFactorChanged` and resume.
- An extra 16 dp margin is kept from cutouts. Nothing interactive goes within 24 dp of the left or right edge (back-gesture zone) or the bottom 24 dp (home gesture).
- The arena and world rendering still use the **full** framebuffer. Only HUD and UI respect `safe`.

### 2.3 Touch target rules (enforced by tests)

- Every tappable `UiRect` is at least 48×48 dp, using a hit rect padded by up to 8 dp if the visual is smaller.
- Adjacent targets are at least 8 dp apart.
- In-combat action buttons have a 60 dp hit target or larger.

---

## 3. Combat screen layout (landscape)

This is based on the hypothesis document, revised after the HTML mockups (`docs/design/android_ui/android_ui_mockups.html`). The status band is one 52 dp row. Touch controls are anchored **in dp from their bottom corner**, not by screen percentage, so the thumb cluster stays together on tablets. Sizes are in dp at `hud_size_pref = 1.0`.

```text
┌──────────────────────────── SAFE AREA (e.g. 780×350 dp) ──────────────────────────┐
│ ┌HULL ████████ 82┐ WAVE 12 · 48,210                                     x3.4  [II] │
│ └SHLD ███▒▒▒▒ 40─┘ [⚡AUTO] ◆◆◇ +3  RAILGUN ▮▮▮▯                                    │
│                          [ BOSS ██████████ PHASE II ]   (only during a boss)      │
│                           ( ☄ METEOR SHOWER · 6s )                               │
│                                (combat — kept clear)                             │
│                                                                                  │
│                                                         (DASH)    (ULTRA ●●○)    │
│     ╭─────╮                                                 (BOOST ◔)            │
│    (  ◉   )  move (floating)                                  ╭─────╮            │
│     ╰─────╯                                                  (  ◎   ) aim/fire   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

| Element | Anchor | Size (dp) | Notes |
| --- | --- | --- | --- |
| Vitals panel (Hull + Shield; Boost moves to its button) | top-left, inset 8 | 196×52 | Moves from the current bottom-left 248×112 panel. Desktop keeps bottom-left; the anchor is chosen by `frame.touch`. |
| Wave · Score line | right of the vitals, first line | 1 line, 13 sp | The score shortens to "48.2k" when space is tight. |
| Auto-fire chip | right of the vitals, second line | 28 dp visual, 48 dp hit | Toggles `settings.auto_shoot` through `apply_settings_change`, which persists it and updates `sim.auto_shoot`, the same path Settings already uses (`app.rs:697`). |
| Buff and relic badges | second line, after the Auto-fire chip | 26 dp icons, max 6 visible plus a "+N" chip | Tapping "+N" while paused opens the full list. During combat it is display-only. |
| Weapon and reload | end of the second line | 1 line | Gameplay-relevant, so it is never hidden. The skin label is dropped on touch. |
| Arena event / status line | centered just below the status band, or below the boss bar during a boss | 1 line, fades | |
| Boss bar | centered just below the status band, only during a boss | 34% of safe width × 14 | |
| Combo | top-right, left of pause | 56×32 | Collapses to the number alone if it would touch the boss bar. |
| Pause | top-right corner | 48×48 | Android Back during a run also pauses. |
| Move stick zone | left 40% × bottom 65% | ring Ø160, knob Ø64 | Floating by default. The stick spawns where the thumb lands and is clamped so the ring stays inside the safe rect. |
| Aim/fire stick zone | right 40% × bottom 55%, minus the button cluster | ring Ø160 | Floating. |
| Dash | 245 dp from right, 162 dp from bottom | Ø60 (hit 68) | Tap. Shows a live cooldown radial. |
| Boost | 163 dp from right, 226 dp from bottom | Ø60 (hit 68) | Hold. Shows a live energy ring. |
| Ultra | 57 dp from right, 176 dp from bottom | Ø64 (hit 72) | Tap. Charge pips use the existing `ultra_cooldown_fraction` radial. |

**Mirrored preset** (left-handed) mirrors x for the sticks and button cluster only. Top HUD stays put, except pause stays top-right.

**Fixed-stick mode** draws the ring at its anchor at 25% opacity, and the stick zone becomes the ring plus 24 dp.

**Opacity/size prefs:** controls default to 55% opacity, which rises to 90% while pressed. A size multiplier of 0.8–1.3 applies to the sticks and buttons.

**Reduced motion:** turns off ready-pulses on Dash and Ultra and uses a static outline instead.

### 3.1 Aim, fire and camera

- The aim direction comes from the right stick vector, then `aim_world = player.pos + dir × AIM_DISTANCE (260)`. This is the same path the gamepad uses (`app.rs:740-757`), so the reticle and camera code keep working.
- If Auto-fire is on, the player fires continuously, and the aim holds its last direction after release, as the gamepad does.
- If Auto-fire is off, the player fires while the stick deflection is above `AIM_FIRE_THRESHOLD` (0.5).
- **Optional aim assist** (off by default, setting `touch_aim_assist`): when the stick is released and auto-fire is on, nudge the aim toward the nearest enemy inside a 25° cone. This is done in the adapter by reading `SimState` read-only. It is a later phase and needs a design sign-off, because it changes difficulty.

### 3.2 Camera framing on phones

The camera currently follows the mouse look-ahead (`update_camera(..., Some(mouse_screen))`). On touch, the look-ahead uses the virtual aim point, capped at 15% of the safe height, so the thumbs don't hide the incoming side. Arena zoom: `PhoneCompact` needs a slightly wider field of view, so `settings.arena_margin` gets a touch default, decided by a side-by-side capture. A new sim rule is **not** needed, because `on_view_resized` already handles different view sizes.

---

## 4. Menu and screen layouts (touch-first variants)

General rules for `PhoneCompact` and `Phone`:
- One primary action per row, at least 48 dp tall.
- Content that exceeds the safe height scrolls vertically, with a drag gesture, inertia and edge fades.
- The Back button is a 48 dp "‹" in the top-left of the safe rect on every non-main screen. Android Back does the same thing.
- Hover states are replaced by pressed states. A tap fires on **release inside the same target**, and is cancelled if the finger moved more than 10 dp, so scroll drags don't trigger taps.
- Tablet and Desktop keep the current layouts, re-anchored to `safe`.

| Screen | Current shape | PhoneCompact layout |
| --- | --- | --- |
| **Main menu** (`MenuScreen`) | Centered column of buttons, a mutator chip row and a title | Two panes. Left 45%: title and best score. Right 55%: Play, Daily, Hangar, Settings, Guide, and Quit (hidden on Android, where the OS handles exit). The mutator chips become a horizontally scrolling row under Play, with chips of at least 48 dp. |
| **Settings** (`SettingsScreen`) | Two fixed columns of chips and sliders (`screens.rs:1407`) | A tab rail on the left (Gameplay / Audio / Display / Controls / Accessibility) and a scrolling list on the right. Sliders are full-row with 48 dp-tall drag tracks. Desktop-only items (window size, fullscreen) are hidden on Android. A new **Controls → Touch** section (§5.3) includes a "Customize layout" editor. |
| **Touch layout editor** (new) | — | Shows a live preview of the combat HUD. Users drag the sticks and buttons within allowed zones, which snap and are blocked from overlapping each other or the top HUD band. There is a Reset button and a mirror toggle. The result is stored as normalized offsets in settings. This is phase 4 and optional for the first release. |
| **Hangar** (`hangar.rs`) | Tabs (Skins / Upgrades / Achievements) and a grid | Tabs become a top segmented control. The grid has 2 rows and scrolls horizontally on PhoneCompact, or vertically on Phone. A tap opens a detail sheet that slides from the right with a 48 dp Equip/Buy button. The Achievements tab is a vertical list with progress bars. |
| **Field Guide** (`GuideScreen`) | Four tabs, a list and Prev/Next | Master/detail. On the left is a scrolling list of entries (36% width); on the right, the detail scrolls. The tabs stay as a segmented control. Prev/Next are removed on touch. |
| **Pause** (`PauseScreen`) | Two centered buttons | Resume (large, center), Settings and Quit to menu. Quit to menu needs a confirm tap. The full buff/relic list goes here (it was the "+N" chip). |
| **Boss reward** (`BossRewardScreen`, `card_rects` `screens.rs:3089`) | Horizontal cards | Three cards across the safe width (about 240 dp each on 780 dp). Card text has a 13 sp minimum. A tap selects and a second tap or a "Take" button confirms, which prevents a mid-combat stray tap from choosing. Input is locked for 400 ms after the screen opens. |
| **Game over** (`GameOverScreen`) | Stats panel and buttons | Stats on the left, with new unlocks and "almost there" on the right, and Retry / Menu buttons pinned at the bottom of the safe rect. The same 400 ms input lock applies. |
| **Fade / transitions** | Unchanged | — |

**Stray-tap protection:** any screen that opens automatically during combat (boss reward, game over) ignores pointers that were already down when it appeared.

---

## 5. Input architecture

### 5.1 `src/input/touch.rs` (new, platform-independent, unit-tested)

```rust
pub enum TouchPhase { Down, Move, Up, Cancel }
pub struct TouchEvent { pub id: u64, pub phase: TouchPhase, pub pos_px: [f32; 2] /* y-up */ }

pub struct TouchControls { /* pointer→owner map, stick origins, per-button state */ }
pub enum Owner { MoveStick, AimStick, Dash, Boost, Ultra, Pause, AutoFire, Ui }

impl TouchControls {
    pub fn on_event(&mut self, ev: &TouchEvent, layout: &TouchLayout);   // ownership on Down only
    pub fn cancel_all(&mut self);                                       // focus loss/suspend/rotate/pause
    pub fn sample(&mut self) -> TouchSample;                            // per sim step
}
pub struct TouchSample {
    pub move_vec: [f32; 2], pub aim_vec: Option<[f32; 2]>, pub aim_mag: f32,
    pub boost_held: bool, pub dash_edge: bool, pub ultra_edge: bool,
    pub pause_tap: bool, pub autofire_tap: bool,
}
```

- Ownership is decided on `Down` by hit-testing in priority order: buttons, then pause/auto-fire, then stick zones. The pointer keeps that owner until `Up` or `Cancel`. A third or later finger can only claim free buttons.
- `dash_edge` and `ultra_edge` are produced once per `Down`, and are queued into the existing `dash_queued` / `ultra_queued` so the sim sees them exactly once.
- The radial deadzone reuses `input::mapping::apply_radial_deadzone` with `settings.touch_deadzone` (default 0.18).
- `TouchLayout` (where the zones are) is computed from `LayoutFrame` and settings in `ui/touch_hud.rs`. The same struct drives drawing and hit-testing, so they can't disagree.

### 5.2 App integration (`app.rs`)

- Add `InputDevice::Touch`. Any touch `Down` switches to it, and `CursorMoved` or a key switches back. This mirrors the gamepad logic.
- `WindowEvent::Touch(t)`:
  - In `Playing`, it goes to `TouchControls`.
  - On menu screens, it goes to a small `TapTracker` that turns press, move and release into `on_mouse_move` + `on_mouse_press` on release, with a 10 dp slop, and into `on_scroll(dy)` for drags. The existing mouse handlers are reused, so no screen logic is duplicated.
- `build_sim_input` gets a touch branch next to the gamepad branch. Precedence: keyboard > gamepad > touch, but only the active device contributes analog values.
- Back key (`KeyCode::BrowserBack` / `NamedKey::GoBack` from winit on Android) maps to the Escape path, except on the main menu, where it shows an "Exit?" confirm.
- `cancel_all()` runs in `clear_transient_input()`, on `Focused(false)`, `suspended`, `Resized` and `enter_screen(Paused)`.
- **Replays:** touch is turned into `SimInput` before the recorder, so recording and replay format don't change. Desktop-only CLI recording is unaffected.

### 5.3 New settings (`save/settings.rs`)

| Key | Type / default | Notes |
| --- | --- | --- |
| `touch_handedness` | `"right"` | `"right"` / `"left"` (mirrored) |
| `touch_stick_mode` | `"floating"` | `"floating"` / `"fixed"` |
| `touch_control_scale` | 1.0 | 0.8–1.3 |
| `touch_control_opacity` | 0.55 | 0.3–0.9 |
| `touch_deadzone` | 0.18 | 0.05–0.4 |
| `touch_haptics` | true | Short vibration on Dash, Ultra and damage. Uses the rumble request path through a platform hook. |
| `hud_size` | 1.0 | 0.85–1.25. Applies to `hud_s` on all platforms. |
| `touch_layout_offsets` | `{}` | From the layout editor. |

These are stored with serde defaults so old settings files load. Bump settings `version` and add a migration test. Desktop ignores the touch keys.

---

## 6. Android platform port

### 6.1 Build layout

```text
plouto_rs/
  Cargo.toml          crate-type = ["rlib", "cdylib"]; android-only deps under [target.'cfg(target_os="android")'.dependencies]
  src/lib.rs          #[cfg(target_os="android")] #[no_mangle] fn android_main(app: AndroidApp)
  src/platform/       mod.rs (trait Platform), desktop.rs, android.rs
android/              Gradle project (Kotlin DSL)
  app/src/main/AndroidManifest.xml
  app/src/main/java/.../MainActivity.kt   extends GameActivity
  app/src/main/assets/                    ← copied from repo assets/ at build time
  app/src/main/jniLibs/<abi>/libplouto_rs.so  ← from cargo-ndk
tools/build_android.ps1
```

- **Activity:** use `GameActivity` (winit feature `android-game-activity`) rather than `NativeActivity`. It gives proper window insets, IME-free key input and better touch event handling.
- **Toolchain:**
  - `rustup target add aarch64-linux-android x86_64-linux-android`
  - `cargo install cargo-ndk`
  - NDK r26+, SDK platform 34, JDK 17
  - `minSdk 26` (AAudio), `targetSdk 34`
- **ABIs:** `arm64-v8a` (release) and `x86_64` (emulator). Skip 32-bit.
- **Manifest:**
  - `screenOrientation="sensorLandscape"`
  - `configChanges` set to orientation|screenSize|screenLayout|keyboardHidden|density, so the activity is not recreated
  - `layoutInDisplayCutoutMode="always"`
  - immersive sticky (set in `MainActivity.onWindowFocusChanged`)
  - `android:hasFragileUserData` off
  - `VIBRATE` permission
  - `<uses-feature android:name="android.hardware.vulkan.version" required="false">`

### 6.2 Platform abstraction (`src/platform/`)

| Concern | Desktop | Android |
| --- | --- | --- |
| Data dir | existing `user_data_directory()` | `app.internal_data_path()` |
| Assets | `resolve_asset` + `fs::read` | `AssetManager::open` → `Vec<u8>`; directory listing through `open_dir` for audio preload |
| Insets | none (full window) | GameActivity window insets → `LayoutFrame.safe` |
| Haptics | gilrs rumble | JNI `Vibrator`/`VibrationEffect` (small Kotlin helper called through `jni`) |
| Logging / crash | `crash.log` + stderr | `android_logger` + `crash.log` in internal data |
| Exit | `event_loop.exit()` | `activity.finish()` through `AndroidApp` |

Asset loading changes: add `assets::read_asset(rel) -> Option<Vec<u8>>` and `assets::list_asset_dir(rel)`. Switch `render/text.rs` FontPack and `audio/mod.rs` preload to use them. `audio::DecodedClip::from_wav` takes bytes (hound can read from `Cursor`). The desktop behavior stays the same.

### 6.3 Lifecycle

- `suspended()`: `cancel_all` touch, pause the run (enter `Paused`), save settings and progress, stop audio output (drop or pause the rodio stream), and drop the `wgpu::Surface`. Keep the device and the renderer's GPU resources.
- `resumed()`: recreate the window surface if the device exists (split `GpuContext::new` into `new_device` + `attach_surface`), recompute `LayoutFrame`, and resume audio. The game stays on Pause until the user taps Resume.
- `Focused(false)` / `Occluded(true)`: pause the run and stop rendering, so the game doesn't use battery in the background.
- Low-memory events are ignored for now.

### 6.4 Rendering and performance

- Use `Backends::VULKAN | GL` on Android. When the adapter is GL, check `Rgba16Float` render-attachment support. If it is missing, fall back to `Rgba8Unorm` bloom or turn bloom off (a `RenderQuality` flag).
- Frame pacing: Fifo present mode with a 60 fps target. Add an optional 30 fps battery-saver setting.
- Add a quality preset (Low / Med / High) that controls bloom passes, particle caps, and `render_scale` 0.67–1.0 (render offscreen, then upscale). Default to Med on Android. The UI and text always render at native resolution.
- Rayon: limit the pool to `min(4, cores-1)` on Android to reduce thermal throttling.
- gilrs: try building it for Android. If it fails, put it behind `#[cfg(not(target_os = "android"))]` and route Android gamepad keys through winit `KeyboardInput` (Android reports pads as key events plus `AXIS_*`).

---

## 7. Work breakdown (parallelizable)

`plouto_rs/` is **not tracked in git**, so worktrees won't contain it. Parallel agents must work in the main checkout with **non-overlapping file ownership**, with one integrator merging `app.rs`. The dependencies below set the order.

| # | Workstream | Owns files | Depends on | Done when |
| --- | --- | --- | --- | --- |
| A1 | `LayoutFrame` + form classes + dp scale | `ui/frame.rs` (new), `ui/theme.rs`, `ui/mod.rs` | — | Desktop `LayoutFrame` returns identical `s`. Unit tests cover the 4 classes. |
| A2 | Touch input core | `input/touch.rs` (new), `input/mod.rs` | — | Tests: multi-pointer ownership, edge-once Dash/Ultra, Boost release on cancel, deadzone parity, mirror. |
| A3 | Settings additions + migration | `save/settings.rs` | — | Old files load. Round-trip test. Version bumped. |
| A4 | Asset/data abstraction (desktop impl only first) | `assets.rs`, `render/text.rs`, `audio/mod.rs` (loading only) | — | Fonts and audio load through `read_asset`. Existing tests pass. |
| A5 | Android scaffold | `android/**`, `tools/build_android.ps1`, `Cargo.toml` target section, `src/platform/**`, `lib.rs` `android_main` | A4 | An APK builds and shows the main menu on the emulator. |
| B1 | Touch HUD layout + drawing | `ui/touch_hud.rs` (new) | A1, A2 | Renders sticks and buttons from live sim state. Layout tests show no overlap across 6 viewport fixtures. |
| B2 | Combat HUD re-anchoring for touch | `ui/hud.rs` | A1 | Vitals top-left on touch, desktop unchanged. Collapse rules for long scores and badges. |
| B3 | Menu + Pause + Game over compact layouts | `ui/screens.rs` (Menu, Pause, GameOver, BossReward sections) | A1 | Tests show 48 dp targets and nothing outside safe on fixtures. Tap-lock on auto-opened screens. |
| B4 | Settings + Guide compact layouts + scrolling | `ui/screens.rs` (Settings, Guide sections), `ui/scroll.rs` (new) | A1, A3 | Scroll with inertia. New Controls → Touch section. |
| B5 | Hangar compact layout | `ui/hangar.rs` | A1 | Grid scroll, detail sheet, achievements list. |
| C1 | App integration | `app.rs` | A1–A3, B1 | Touch → `SimInput`, TapTracker, Back key, cancel on lifecycle. Auto-fire chip persists. |
| C2 | Lifecycle + GPU surface split + render quality | `render/mod.rs`, `render/bloom.rs`, platform resume/suspend | A5 | Background/foreground 20× with no crash and no stuck input. GL fallback renders. |
| D1 | Desktop touch emulator (dev tool) | `src/bin/touch_preview.rs` or `--touch-sim` flag in app | B1, C1 | The desktop window runs at a given dp size, scale and inset with mouse-as-finger and multi-touch hotkeys, for fast iteration without a device. |
| D2 | Layout editor (optional, phase 4) | `ui/touch_editor.rs` (new) | B1, B4 | Drag controls with snapping and overlap blocking, persisted. |

B3 and B4 both edit `ui/screens.rs`. Either split screens.rs into per-screen files first (a small, mechanical, pre-B refactor that also helps parallel work), or run B3 and B4 one after the other.

### Viewport fixtures for layout tests (`tests/android_layout.rs`)

| Name | px | density | insets (px, l/t/r/b) | ≈ dp |
| --- | --- | --- | --- | --- |
| phone_16x9 | 1920×1080 | 2.625 | 0/0/0/63 | 731×387 |
| phone_20x9_cutout | 2400×1080 | 2.75 | 110/0/0/66 | 833×369 |
| phone_small | 1600×720 | 2.0 | 0/0/0/48 | 800×336 |
| phone_tall_21x9 | 2520×1080 | 3.0 | 120/0/120/63 | 760×339 |
| tablet_10in | 2560×1600 | 2.0 | 0/48/0/48 | 1280×752 |
| foldable_open | 2208×1840 | 2.625 | 0/0/0/60 | 841×678 |

Assertions per fixture and per screen:
- every interactive rect is inside `safe` and at least 48 dp
- no two interactive rects overlap
- text is at least 12 sp
- in combat, no persistent control enters the central 32%×40% "clear box"

---

## 8. Phases and milestones

| Phase | Contents | Exit criteria |
| --- | --- | --- |
| **0. Toolchain spike** (½–1 day) | Install the SDK, NDK, JDK 17 and targets. Build a hello-wgpu winit GameActivity APK. Then build `plouto_rs` for `aarch64-linux-android` with the platform stubs, to find out whether gilrs, rodio and cpal compile. | List of crates that need `cfg` gating. APK clears the screen on the emulator. |
| **1. Foundations** | A1–A5 in parallel | Desktop tests are green and desktop output is unchanged. The APK shows the main menu with readable text. |
| **2. Combat on touch** | B1, B2, C1, D1 | A full run is playable on the emulator and one real phone. Touch traces show no stuck boost or fire. |
| **3. Menus on touch** | B3, B4, B5, C2 | Every screen can be reached and used by touch. Back works everywhere. The suspend/resume soak passes. |
| **4. Polish** | D2, haptics, quality presets, aim-assist decision, icon/splash | Device matrix pass (§9). |
| **5. Release** | Signed AAB, `tools/build_android.ps1` integrated with `build_all.bat` as an optional step, store listing assets | Release checklist. Internal testing track. |

---

## 9. Validation

- **Headless (CI-able):**
  - `cargo test -p plouto_rs` (unchanged suite)
  - new `touch.rs` unit tests
  - `android_layout.rs` fixtures
  - a desktop-parity test asserting that `LayoutFrame::desktop(w,h).menu_s == ui_scale(w,h)` for a sweep of sizes
- **Determinism:** record a run on desktop, then replay it in an Android build (`cargo test` on the device through `cargo ndk test`, or a debug-menu replay). The hash must match.
- **Device matrix** (minimum): one 16:9 mid-range phone, one 20:9 phone with a punch-hole, one tablet or foldable, plus the emulator for GL fallback (`-gpu swiftshader_indirect`).
- **Scenarios:** the 7 interaction scenarios in the hypothesis doc §7, plus:
  - suspend/resume 20×
  - rotate 180° (sensorLandscape flip) mid-run
  - notification shade during a boss
  - Back on every screen
  - low-battery 30 fps mode
  - 15-minute thermal run, logging frame time p95
- **Performance targets** (mid-range, Med quality): 60 fps with p95 frame time ≤ 16.7 ms at wave 20 with a boss. No thermal throttle within 10 minutes.

---

## 10. Risks and open questions

1. **Readability vs. field of view:** at about 360 dp tall, the arena may feel cramped. This needs capture comparisons of `arena_margin` and camera zoom on PhoneCompact before the HUD is tuned.
2. **GL fallback quality:** devices without Vulkan 1.1 may lose bloom. Decide whether to support them or require Vulkan (`required="true"`), which drops about 5–10% of devices.
3. **gilrs/cpal on Android:** unverified until Phase 0. cpal's Oboe backend needs `libc++_shared.so` in `jniLibs`.
4. **Aim assist** changes balance. It is a product decision, off by default.
5. **Hangar purchases:** this plan assumes no real-money store. If one is ever added, it needs Play Billing, which is outside this plan.
6. **Settings file sharing:** desktop and Android settings files are independent. Cloud sync is out of scope.
7. **`screens.rs` size (3,900 lines):** splitting it before Phase 3 is recommended. Otherwise B3 and B4 have to run one after the other.
