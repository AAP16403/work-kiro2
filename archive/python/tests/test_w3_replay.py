"""Run replay tests (wave 3, replay).

A recorded run is played again on a fresh game: its state hash after every step must match the recording.
A change to one input in the middle of the run must be caught at that step. Recording is off by default.

Every file these tests write (high scores, progress, the replay file) goes to a temp folder, so the real
files in the project root are never touched.
"""

import dataclasses
import json
import math
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pyglet  # noqa: E402

import replay  # noqa: E402
import score as score_mod  # noqa: E402
from game import Game  # noqa: E402

STEPS = 600
CHANGE_AT = 300
SEED = 4242
_TMP = tempfile.mkdtemp(prefix="w3_replay_")


def _script(index, game):
    """A fixed input script for one step: the movement keys in turn, boost now and then, a moving aim,
    auto-fire held, and a dash at two fixed steps. Pure function of the step index."""
    k = pyglet.window.key
    phase = (index // 45) % 4
    game.keys[k.W] = phase == 0
    game.keys[k.D] = phase == 1
    game.keys[k.S] = phase == 2
    game.keys[k.A] = phase == 3
    game.keys[k.LSHIFT] = (index % 120) < 20
    game.mouse_down = True
    game.mouse_xy = (640 + 200 * math.cos(index * 0.05), 360 + 200 * math.sin(index * 0.05))
    if index in (150, 400):
        game._dash()


def _isolate(game):
    """Point every save file of the game at the temp folder for this run."""
    score_mod.HIGH_SCORE_FILE = os.path.join(_TMP, "board.json")
    replay.DEFAULT_PATH = os.path.join(_TMP, "last_run.json")
    game.progress_path = os.path.join(_TMP, "progress.json")


def _record(game):
    return replay.record_scripted(game, SEED, "normal", (), STEPS, _script)


def _with_changed_input(recording, index):
    """A copy of ``recording`` where step ``index`` holds the D key's opposite (a different move)."""
    step = recording.steps[index]
    changed = dataclasses.replace(step, keys=step.keys ^ (1 << 3))  # bit 3 is D, see replay.INPUT_KEY_NAMES
    steps = list(recording.steps)
    steps[index] = changed
    return replay.Recording(
        recording.seed, recording.difficulty, recording.skin, recording.mutators, steps, list(recording.hashes),
    )


def test_600_step_round_trip(g):
    _isolate(g)
    recorded = _record(g)
    assert len(recorded.steps) == STEPS and len(recorded.hashes) == STEPS, (len(recorded.steps), len(recorded.hashes))
    # Through JSON, the way --record writes it, so the replay reads exactly what was saved.
    loaded = replay.Recording.from_json(json.loads(json.dumps(recorded.to_json())))
    result = replay.replay(g, loaded)
    assert result.ok, f"replay diverged at step {result.first_mismatch}"
    assert result.hashes == recorded.hashes, "replayed state hashes differ from the recording"
    print(f"[PASS] test_600_step_round_trip passed ({STEPS} steps replayed, every state hash matches)")


def test_mid_run_input_change_is_detected(g):
    _isolate(g)
    recorded = _record(g)
    changed = _with_changed_input(recorded, CHANGE_AT)
    result = replay.replay(g, changed)
    assert result.first_mismatch is not None, "a changed input at step 300 went unnoticed"
    assert result.first_mismatch == CHANGE_AT, f"caught at step {result.first_mismatch}, expected {CHANGE_AT}"
    print(f"[PASS] test_mid_run_input_change_is_detected passed (input changed at step {CHANGE_AT}, "
          f"first mismatch at step {result.first_mismatch})")


def test_recording_is_off_by_default(g):
    _isolate(g)
    assert g.record_runs is False, "recording must be off unless --record or record_runs=True is given"
    replay.start_run(g, SEED, "normal", ())
    assert g.recorder is None, "a run started without --record must not carry a recorder"
    print("[PASS] test_recording_is_off_by_default passed (no recorder without --record)")


def test_recording_file_round_trip(g):
    _isolate(g)
    recorded = _record(g)
    path = os.path.join(_TMP, "round_trip.json")
    assert replay.save_recording(recorded, path), "save_recording must succeed in a temp folder"
    loaded = replay.load_recording(path)
    assert loaded.to_json() == recorded.to_json(), "a saved recording must load back unchanged"
    print("[PASS] test_recording_file_round_trip passed (save and load keep every step and hash)")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_600_step_round_trip(g)
        test_mid_run_input_change_is_detected(g)
        test_recording_is_off_by_default(g)
        test_recording_file_round_trip(g)
    finally:
        g.close()
    print("\nALL W3 REPLAY TESTS PASSED")


if __name__ == "__main__":
    run_all()
