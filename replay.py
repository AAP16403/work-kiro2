"""Run recording and replay.

A recording keeps what a run needs to be played again: the seed, difficulty, skin and mutator selection,
and, for every fixed simulation step, the inputs that step read (movement keys, boost, aim, fire, ultra
and any dash pressed just before it). Each step also stores a hash of the game state after it, so a replay
on a fresh game can show whether it followed the recorded run, and where it first stopped matching.

The state hash covers the player's position and HP, the score, the wave, the enemy and projectile counts
and the run's RNG state. A change in any of them after the first difference shows up at that step.

Recording is off by default. Start the game with ``--record`` (or build ``Game(record_runs=True)``) and the
recording of each finished run is written to ``replays/last_run.json``. Replays run the game's own fixed
step (``Game._fixed_step``) without drawing, so they are deterministic for a given seed and input list.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

import pyglet

FORMAT_VERSION = 1

# Keys that drive a run: the movement keys Game._input_dir reads, and boost (LSHIFT, RSHIFT).
# A key's bit in a recorded mask is its position in this tuple.
INPUT_KEY_NAMES = ("W", "A", "S", "D", "UP", "DOWN", "LEFT", "RIGHT", "LSHIFT", "RSHIFT")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(PROJECT_ROOT, "replays", "last_run.json")


def _key_codes() -> tuple:
    k = pyglet.window.key
    return tuple(getattr(k, name) for name in INPUT_KEY_NAMES)


class ReplayKeys(dict):
    """A plain key table for recording and replay: the recorded key states, False for every other key.

    pyglet's KeyStateHandler is fed by window events and does not take assignments, so a run that is
    recorded or replayed swaps it for this table (see keys_swapped) and puts the handler back afterwards.
    """

    def __missing__(self, key):
        return False


class KeysSwapped:
    """Context manager: game.keys is a ReplayKeys table inside the block, and the live handler outside it."""

    def __init__(self, game):
        self.game = game
        self.live = None
        self.table = ReplayKeys()

    def __enter__(self) -> ReplayKeys:
        self.live = self.game.keys
        self.game.keys = self.table
        return self.table

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.game.keys = self.live
        return False


def keys_mask(keys) -> int:
    """The held input keys as a bit mask, in INPUT_KEY_NAMES order."""
    mask = 0
    for i, code in enumerate(_key_codes()):
        if keys[code]:
            mask |= 1 << i
    return mask


def apply_keys_mask(keys, mask: int) -> None:
    """Set every input key from a recorded mask. Keys outside INPUT_KEY_NAMES are left alone."""
    for i, code in enumerate(_key_codes()):
        keys[code] = bool(mask & (1 << i))


@dataclass(frozen=True)
class Dash:
    """A dash request, with the keys and aim it was made with (the dash reads both)."""

    keys: int
    aim_x: float
    aim_y: float


@dataclass(frozen=True)
class Step:
    """The inputs of one fixed simulation step, read just before the step runs."""

    keys: int
    aim_x: float
    aim_y: float
    fire: bool
    ultra: bool
    dashes: tuple = ()  # dash requests made after the previous step and before this one, in order

    def to_json(self) -> list:
        return [
            self.keys, self.aim_x, self.aim_y, int(self.fire), int(self.ultra),
            [[d.keys, d.aim_x, d.aim_y] for d in self.dashes],
        ]

    @classmethod
    def from_json(cls, row) -> "Step":
        keys, aim_x, aim_y, fire, ultra, dashes = row
        return cls(
            keys=int(keys), aim_x=float(aim_x), aim_y=float(aim_y), fire=bool(fire), ultra=bool(ultra),
            dashes=tuple(Dash(int(k), float(x), float(y)) for k, x, y in dashes),
        )


@dataclass
class Recording:
    """Everything needed to replay one run, plus the state hash after each step."""

    seed: int
    difficulty: str
    skin: str
    mutators: tuple
    steps: list
    hashes: list

    def to_json(self) -> dict:
        return {
            "format": FORMAT_VERSION,
            "seed": self.seed,
            "difficulty": self.difficulty,
            "skin": self.skin,
            "mutators": list(self.mutators),
            "steps": [step.to_json() for step in self.steps],
            "hashes": list(self.hashes),
        }

    @classmethod
    def from_json(cls, data: dict) -> "Recording":
        if int(data.get("format", 0)) != FORMAT_VERSION:
            raise ValueError(f"unsupported replay format {data.get('format')!r}")
        return cls(
            seed=int(data["seed"]),
            difficulty=str(data["difficulty"]),
            skin=str(data.get("skin", "classic")),
            mutators=tuple(str(m) for m in data.get("mutators", [])),
            steps=[Step.from_json(row) for row in data["steps"]],
            hashes=[str(h) for h in data["hashes"]],
        )


def state_hash(game) -> str:
    """A hash of the gameplay state that a replay must reproduce exactly."""
    s = game.state
    p = game.player
    score = game.score.score if getattr(game, "score", None) is not None else 0
    text = repr((
        float(p.pos.x), float(p.pos.y), float(p.hp), int(score), int(s.wave),
        len(s.enemies), len(s.projectiles), s.rng.getstate(),
    ))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Recorder:
    """Collects a run's inputs and state hashes while it plays. Attach it as ``game.recorder``.

    Game._fixed_step calls before_step and after_step around each playing step, and Game._dash calls
    note_dash, so the recorder sees every input the simulation reads.
    """

    def __init__(self, seed: int, difficulty: str, skin: str = "classic", mutators=()):
        self.seed = int(seed)
        self.difficulty = str(difficulty)
        self.skin = str(skin)
        self.mutators = tuple(str(m) for m in mutators)
        self.steps: list = []
        self.hashes: list = []
        self._dashes: list = []
        self._pending = None

    def note_dash(self, game) -> None:
        self._dashes.append(Dash(keys_mask(game.keys), float(game.mouse_xy[0]), float(game.mouse_xy[1])))

    def before_step(self, game) -> None:
        x, y = game.mouse_xy
        self._pending = (
            keys_mask(game.keys), float(x), float(y),
            bool(game.mouse_down), bool(getattr(game, "_rmb_down", False)),
        )

    def after_step(self, game) -> None:
        keys, x, y, fire, ultra = self._pending
        self.steps.append(Step(keys, x, y, fire, ultra, tuple(self._dashes)))
        self._dashes = []
        self.hashes.append(state_hash(game))

    def recording(self) -> Recording:
        return Recording(self.seed, self.difficulty, self.skin, self.mutators, list(self.steps), list(self.hashes))


@dataclass
class ReplayResult:
    ok: bool
    first_mismatch: int | None  # index of the first step whose state hash differs from the recording
    hashes: list  # hashes of the steps the replay ran


def start_run(game, seed, difficulty: str, mutators=()) -> None:
    """Begin a fresh playing run with the given seed, difficulty and mutator selection."""
    from states import GameStateName  # imported here: states imports game-side modules that must not load first

    game.settings["difficulty"] = str(difficulty)
    game.daily_date = None
    game.recorder = None
    game.forced_seed = None if seed is None else int(seed)
    try:
        game._init_game(mutator_ids=tuple(mutators))
    finally:
        game.forced_seed = None
    game.fsm.set_state(GameStateName.PLAYING)


def record_scripted(game, seed, difficulty: str, mutators, steps: int, script, skin: str = "classic") -> Recording:
    """Play ``steps`` fixed steps of a fresh run. ``script(index, game)`` sets the inputs of each step."""
    start_run(game, seed, difficulty, mutators)
    recorder = Recorder(game.state.seed, difficulty, skin, game.run_mutators)
    game.recorder = recorder
    try:
        with KeysSwapped(game):
            for index in range(int(steps)):
                script(index, game)
                game._fixed_step()
    finally:
        game.recorder = None
    return recorder.recording()


def replay(game, recording: Recording) -> ReplayResult:
    """Play ``recording`` on ``game`` and compare the state hash after each step with the recorded one.

    Stops at the first step that differs, so ``first_mismatch`` names the step where the replay
    left the recorded run.
    """
    start_run(game, recording.seed, recording.difficulty, recording.mutators)
    hashes: list = []
    first_mismatch = None
    with KeysSwapped(game) as keys:
        for index, step in enumerate(recording.steps):
            for dash in step.dashes:
                apply_keys_mask(keys, dash.keys)
                game.mouse_xy = (dash.aim_x, dash.aim_y)
                game._dash()
            apply_keys_mask(keys, step.keys)
            game.mouse_xy = (step.aim_x, step.aim_y)
            game.mouse_down = step.fire
            game._rmb_down = step.ultra
            game._fixed_step()
            digest = state_hash(game)
            hashes.append(digest)
            if index < len(recording.hashes) and digest != recording.hashes[index]:
                first_mismatch = index
                break
    ok = first_mismatch is None and len(hashes) == len(recording.steps)
    return ReplayResult(ok, first_mismatch, hashes)


def save_recording(recording: Recording, path: str = DEFAULT_PATH) -> bool:
    """Write a recording as JSON through a temporary file. Returns False on failure and never raises."""
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(recording.to_json(), fh, separators=(",", ":"))
        os.replace(tmp, path)
        return True
    except (OSError, TypeError, ValueError):
        return False


def load_recording(path: str = DEFAULT_PATH) -> Recording:
    with open(path, "r", encoding="utf-8") as fh:
        return Recording.from_json(json.load(fh))
