//! Controller and keyboard labels for menus and HUD hints.

/// Which input device the player is currently using.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum InputDevice {
    #[default]
    KeyboardMouse,
    Gamepad,
}

/// One-line controls summary for menus.
pub fn controls_hint(d: InputDevice) -> &'static str {
    match d {
        InputDevice::KeyboardMouse => {
            "WASD Move  |  Click Shoot  |  Space Dash  |  Shift Boost  |  Q / RMB Ultra  |  Arrows + Enter Menu"
        }
        InputDevice::Gamepad => {
            "L-Stick Move  |  R-Stick Aim  |  RT Fire  |  A Dash  |  LT Boost  |  Y Ultra  |  Start Pause"
        }
    }
}

/// Label for the confirm action.
pub fn confirm_label(d: InputDevice) -> &'static str {
    match d {
        InputDevice::KeyboardMouse => "Enter",
        InputDevice::Gamepad => "A",
    }
}

/// Label for the back / cancel action.
pub fn back_label(d: InputDevice) -> &'static str {
    match d {
        InputDevice::KeyboardMouse => "Esc",
        InputDevice::Gamepad => "B",
    }
}
