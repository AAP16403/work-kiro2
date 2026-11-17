"""
A simple finite state machine (FSM) implementation.
"""

class State:
    """Base class for a state in the FSM."""
    def __init__(self, game):
        self.game = game

    def enter(self):
        """Code to execute when entering this state."""
        pass

    def exit(self):
        """Code to execute when exiting this state."""
        pass

    def update(self, dt: float):
        """Update game logic for this state."""
        pass

    def draw(self):
        """Render the screen for this state."""
        pass

    def on_mouse_press(self, x, y, button, modifiers):
        """Handle mouse presses."""
        pass

    def on_mouse_release(self, x, y, button, modifiers):
        """Handle mouse releases."""
        pass

    def on_mouse_motion(self, x, y, dx, dy):
        """Handle mouse motion."""
        pass
    
    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        """Handle mouse drag."""
        pass

    def on_key_press(self, symbol, modifiers):
        """Handle key presses."""
        pass


from enum import Enum


def _normalize_state_name(state_name) -> str:
    """Normalize the given state identifier into a string key."""
    if isinstance(state_name, Enum):
        return state_name.value
    if isinstance(state_name, type) and issubclass(state_name, State):
        return state_name.__name__
    if isinstance(state_name, State):
        return state_name.__class__.__name__
    return str(state_name)


class StateMachine:
    """A simple finite state machine."""
    def __init__(self, initial_state: State):
        self.current_state = None
        self._states = {}
        if initial_state:
            self.add_state(initial_state)
            self.set_state(initial_state)

    def add_state(self, state: State):
        """Adds a state to the machine."""
        self._states[_normalize_state_name(state)] = state

    def set_state(self, state_name):
        """Transitions to a new state."""
        state_name = _normalize_state_name(state_name)
        if self.current_state:
            self.current_state.exit()
        
        new_state = self._states.get(state_name)
        if new_state:
            self.current_state = new_state
            self.current_state.enter()
        else:
            raise ValueError(f"State '{state_name}' not found.")

    def update(self, dt: float):
        if self.current_state:
            self.current_state.update(dt)

    def draw(self):
        if self.current_state:
            self.current_state.draw()

    def on_mouse_press(self, x, y, button, modifiers):
        if self.current_state:
            self.current_state.on_mouse_press(x, y, button, modifiers)

    def on_mouse_release(self, x, y, button, modifiers):
        if self.current_state:
            self.current_state.on_mouse_release(x, y, button, modifiers)

    def on_mouse_motion(self, x, y, dx, dy):
        if self.current_state:
            self.current_state.on_mouse_motion(x, y, dx, dy)
    
    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        if self.current_state:
            self.current_state.on_mouse_drag(x, y, dx, dy, buttons, modifiers)

    def on_key_press(self, symbol, modifiers):
        if self.current_state:
            self.current_state.on_key_press(symbol, modifiers)
