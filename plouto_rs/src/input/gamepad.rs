//! Gamepad input through gilrs.
//!
//! `GamepadManager` tracks a single active pad (the most recently used one),
//! translates gilrs events into `PadEvent`s and caches a `PadSnapshot` that is
//! refreshed on every `poll()`. Nothing here panics: if gilrs cannot start the
//! manager is inert and every query returns neutral values.

use gilrs::ff::{BaseEffect, BaseEffectType, Effect, EffectBuilder, Envelope, Repeat, Replay, Ticks};
use gilrs::{Axis, Button, EventType, GamepadId, Gilrs};

use crate::input::rumble::RumbleRequest;

/// Stick magnitude needed before an axis movement steals the active pad.
/// Keeps stick drift on an idle pad from hijacking input.
const CLAIM_AXIS_THRESHOLD: f32 = 0.5;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum PadButton {
    South,
    East,
    West,
    North,
    LeftBumper,
    RightBumper,
    Start,
    Select,
    DPadUp,
    DPadDown,
    DPadLeft,
    DPadRight,
}

/// Every `PadButton`, in enum order. `PadSnapshot::held` is indexed the same way.
const PAD_BUTTONS: [PadButton; 12] = [
    PadButton::South,
    PadButton::East,
    PadButton::West,
    PadButton::North,
    PadButton::LeftBumper,
    PadButton::RightBumper,
    PadButton::Start,
    PadButton::Select,
    PadButton::DPadUp,
    PadButton::DPadDown,
    PadButton::DPadLeft,
    PadButton::DPadRight,
];

impl PadButton {
    fn from_gilrs(b: Button) -> Option<PadButton> {
        Some(match b {
            Button::South => PadButton::South,
            Button::East => PadButton::East,
            Button::West => PadButton::West,
            Button::North => PadButton::North,
            // gilrs names the shoulder buttons LeftTrigger/RightTrigger;
            // the analog triggers are LeftTrigger2/RightTrigger2.
            Button::LeftTrigger => PadButton::LeftBumper,
            Button::RightTrigger => PadButton::RightBumper,
            Button::Start => PadButton::Start,
            Button::Select => PadButton::Select,
            Button::DPadUp => PadButton::DPadUp,
            Button::DPadDown => PadButton::DPadDown,
            Button::DPadLeft => PadButton::DPadLeft,
            Button::DPadRight => PadButton::DPadRight,
            _ => return None,
        })
    }

    fn to_gilrs(self) -> Button {
        match self {
            PadButton::South => Button::South,
            PadButton::East => Button::East,
            PadButton::West => Button::West,
            PadButton::North => Button::North,
            PadButton::LeftBumper => Button::LeftTrigger,
            PadButton::RightBumper => Button::RightTrigger,
            PadButton::Start => Button::Start,
            PadButton::Select => Button::Select,
            PadButton::DPadUp => Button::DPadUp,
            PadButton::DPadDown => Button::DPadDown,
            PadButton::DPadLeft => Button::DPadLeft,
            PadButton::DPadRight => Button::DPadRight,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum PadEvent {
    Pressed(PadButton),
    Released(PadButton),
    /// The active pad changed or appeared; carries its display name.
    Connected(String),
    /// The active pad went away.
    Disconnected,
}

#[derive(Debug, Clone, Copy, Default)]
pub struct PadSnapshot {
    pub connected: bool,
    /// Raw left stick, x right +, y UP +, range -1..1.
    pub left: [f32; 2],
    /// Raw right stick, same convention.
    pub right: [f32; 2],
    /// 0..1
    pub left_trigger: f32,
    /// 0..1
    pub right_trigger: f32,
    /// Indexed by `PadButton as usize` in enum order.
    pub held: [bool; 12],
}

pub struct GamepadManager {
    gilrs: Option<Gilrs>,
    active: Option<GamepadId>,
    snap: PadSnapshot,
    rumble_effect: Option<Effect>,
}

impl GamepadManager {
    /// Never panics. If gilrs fails to initialise, the manager is inert.
    pub fn new() -> Self {
        let gilrs = match Gilrs::new() {
            Ok(g) => Some(g),
            Err(_) => None,
        };
        Self {
            gilrs,
            active: None,
            snap: PadSnapshot::default(),
            rumble_effect: None,
        }
    }

    /// Drains gilrs events since the last call, updates the active pad and
    /// refreshes the cached snapshot.
    pub fn poll(&mut self) -> Vec<PadEvent> {
        let mut out = Vec::new();
        let mut gilrs = match self.gilrs.take() {
            Some(g) => g,
            None => return out,
        };

        while let Some(ev) = gilrs.next_event() {
            let id = ev.id;
            match ev.event {
                EventType::Connected => {
                    if self.active.is_none() {
                        self.set_active(&gilrs, id, &mut out);
                    }
                }
                EventType::Disconnected => {
                    if self.active == Some(id) {
                        self.active = None;
                        out.push(PadEvent::Disconnected);
                    }
                }
                EventType::ButtonPressed(btn, _) => {
                    self.claim(&gilrs, id, &mut out);
                    if self.active == Some(id) {
                        if let Some(pb) = PadButton::from_gilrs(btn) {
                            out.push(PadEvent::Pressed(pb));
                        }
                    }
                }
                EventType::ButtonReleased(btn, _) => {
                    if self.active == Some(id) {
                        if let Some(pb) = PadButton::from_gilrs(btn) {
                            out.push(PadEvent::Released(pb));
                        }
                    }
                }
                EventType::AxisChanged(_, value, _) => {
                    if value.abs() > CLAIM_AXIS_THRESHOLD {
                        self.claim(&gilrs, id, &mut out);
                    }
                }
                _ => {}
            }
        }

        self.refresh_snapshot(&gilrs);
        self.gilrs = Some(gilrs);
        out
    }

    pub fn snapshot(&self) -> PadSnapshot {
        self.snap
    }

    pub fn is_held(&self, b: PadButton) -> bool {
        self.snap.held[b as usize]
    }

    /// Best effort. Replaces any running rumble. Silently does nothing when the
    /// active pad is missing or does not support force feedback.
    pub fn rumble(&mut self, req: RumbleRequest) {
        if let Some(old) = self.rumble_effect.take() {
            let _ = old.stop();
        }

        let strong = req.strong.clamp(0.0, 1.0);
        let weak = req.weak.clamp(0.0, 1.0);
        if (strong <= 0.0 && weak <= 0.0) || req.duration_ms == 0 {
            return;
        }

        let active = match self.active {
            Some(id) => id,
            None => return,
        };
        let gilrs = match self.gilrs.as_mut() {
            Some(g) => g,
            None => return,
        };
        let supported = match gilrs.connected_gamepad(active) {
            Some(gp) => gp.is_ff_supported(),
            None => false,
        };
        if !supported {
            return;
        }

        let dur = Ticks::from_ms(req.duration_ms);
        let ids = [active];
        let mut builder = EffectBuilder::new();
        if strong > 0.0 {
            builder.add_effect(BaseEffect {
                kind: BaseEffectType::Strong {
                    magnitude: to_u16(strong),
                },
                scheduling: Replay {
                    after: Ticks::default(),
                    play_for: dur,
                    with_delay: Ticks::default(),
                },
                envelope: flat_envelope(),
            });
        }
        if weak > 0.0 {
            builder.add_effect(BaseEffect {
                kind: BaseEffectType::Weak {
                    magnitude: to_u16(weak),
                },
                scheduling: Replay {
                    after: Ticks::default(),
                    play_for: dur,
                    with_delay: Ticks::default(),
                },
                envelope: flat_envelope(),
            });
        }
        builder.gamepads(&ids).repeat(Repeat::For(dur));

        if let Ok(effect) = builder.finish(gilrs) {
            if effect.play().is_ok() {
                self.rumble_effect = Some(effect);
            }
        }
    }

    /// Makes `id` the active pad if it is not already, emitting `Connected`.
    fn claim(&mut self, gilrs: &Gilrs, id: GamepadId, out: &mut Vec<PadEvent>) {
        if self.active != Some(id) {
            self.set_active(gilrs, id, out);
        }
    }

    fn set_active(&mut self, gilrs: &Gilrs, id: GamepadId, out: &mut Vec<PadEvent>) {
        self.active = Some(id);
        let name = match gilrs.connected_gamepad(id) {
            Some(gp) => gp.name().to_string(),
            None => String::new(),
        };
        out.push(PadEvent::Connected(name));
    }

    fn refresh_snapshot(&mut self, gilrs: &Gilrs) {
        let mut snap = PadSnapshot::default();
        if let Some(id) = self.active {
            if let Some(gp) = gilrs.connected_gamepad(id) {
                snap.connected = true;
                snap.left = [
                    gp.value(Axis::LeftStickX).clamp(-1.0, 1.0),
                    gp.value(Axis::LeftStickY).clamp(-1.0, 1.0),
                ];
                snap.right = [
                    gp.value(Axis::RightStickX).clamp(-1.0, 1.0),
                    gp.value(Axis::RightStickY).clamp(-1.0, 1.0),
                ];
                snap.left_trigger = trigger_value(&gp, Button::LeftTrigger2);
                snap.right_trigger = trigger_value(&gp, Button::RightTrigger2);
                for (i, pb) in PAD_BUTTONS.iter().enumerate() {
                    snap.held[i] = gp.is_pressed(pb.to_gilrs());
                }
            }
        }
        self.snap = snap;
    }
}

impl Default for GamepadManager {
    fn default() -> Self {
        Self::new()
    }
}

/// Reads an analog trigger as 0..1 from its trigger button value, otherwise 0.
/// There is deliberately no Z-axis fallback: axes with a non-zero or unknown
/// rest value read as half-pressed at rest, which fires auto fire and boost.
fn trigger_value(gp: &gilrs::Gamepad<'_>, btn: Button) -> f32 {
    match gp.button_data(btn) {
        Some(data) => data.value().clamp(0.0, 1.0),
        None => 0.0,
    }
}

fn flat_envelope() -> Envelope {
    Envelope {
        attack_length: Ticks::default(),
        attack_level: 1.0,
        fade_length: Ticks::default(),
        fade_level: 1.0,
    }
}

fn to_u16(v: f32) -> u16 {
    (v.clamp(0.0, 1.0) * u16::MAX as f32).round() as u16
}
