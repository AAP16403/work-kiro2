"""Save files stay local (wave 8, saves-untracked).

high_scores.json is no longer tracked by git. The three local save files (progress.json, user_settings.json
and high_scores.json), replays/, quarantined corrupt copies and atomic-write temp files are all ignored, so a
game run never leaves a modified tracked file behind.

The checks:

- git: the index lists no save file, and every save file, replay, quarantined copy and temp file is ignored;
- build_all.bat: the save backup list names the same three files, and the script does not depend on git or on
  the tracked high_scores.json beyond that list;
- load: a missing file reads as defaults, and a corrupt file reads as defaults, is moved aside and never crashes;
- save: the first save creates the file, with the defaults or with the data it was given.

Every file write goes to a temporary folder. run_all() checks that the real save files in the project root are
unchanged at the end. Plain functions that print [PASS] lines, run from run_all().
"""

import hashlib
import json
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager

import achievements
import audio
import progress
import score as score_mod
from score import ScoreTracker

HERE = os.path.dirname(os.path.abspath(__file__))
SAVE_FILES = ("high_scores.json", "progress.json", "user_settings.json")
IGNORED_PATHS = (
    "high_scores.json",
    "progress.json",
    "user_settings.json",
    "replays/last_run.json",
    "high_scores.json.corrupt-1",
    ".high_scores-a1b2c3d4.tmp",
    ".progress-a1b2c3d4.tmp",
    ".user_settings-a1b2c3d4.tmp",
)
DEFAULT_VOLUMES = (0.5, 0.8)  # (music, sfx) when no settings file is readable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def _sandbox():
    """A temp folder with all three save paths redirected into it. The real paths are restored on exit."""
    saved = (audio._SETTINGS_PATH, score_mod.HIGH_SCORE_FILE, progress.PROGRESS_FILE)
    with tempfile.TemporaryDirectory(prefix="plouto_saves_untracked_") as tmp:
        audio._SETTINGS_PATH = os.path.join(tmp, "user_settings.json")
        score_mod.HIGH_SCORE_FILE = os.path.join(tmp, "high_scores.json")
        progress.PROGRESS_FILE = os.path.join(tmp, "progress.json")
        try:
            yield tmp
        finally:
            audio._SETTINGS_PATH, score_mod.HIGH_SCORE_FILE, progress.PROGRESS_FILE = saved


def _git(*args):
    """Run git in the project root. Returns (exit code, stdout)."""
    done = subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, timeout=120)
    return done.returncode, done.stdout


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _read_text(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _digest(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# ---------------------------------------------------------------------------
# git and build_all.bat
# ---------------------------------------------------------------------------

def test_index_does_not_track_high_scores():
    rc, listing = _git("ls-files")
    assert rc == 0, "git ls-files must run in the project root"
    tracked = listing.splitlines()
    for name in SAVE_FILES:
        assert name not in tracked, f"{name} must not be tracked by git"
    print("[PASS] test_index_does_not_track_high_scores passed (git ls-files lists no save file)")


def test_save_files_replays_and_leftovers_are_ignored():
    for rel in IGNORED_PATHS:
        rc, _ = _git("check-ignore", "-q", "--", rel)
        assert rc == 0, f"{rel} must be ignored by .gitignore"
    print("[PASS] test_save_files_replays_and_leftovers_are_ignored passed (three saves, replays/, .corrupt-n and temp files are ignored)")


def test_build_backup_list_names_the_same_files():
    with open(os.path.join(HERE, "build_all.bat"), "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    match = re.search(r'^set "SAVE_FILES=([^"]*)"', text, re.MULTILINE)
    assert match, "build_all.bat must define SAVE_FILES"
    assert sorted(match.group(1).split()) == sorted(SAVE_FILES), f"backup list changed: {match.group(1)}"
    assert text.count("for %%F in (%SAVE_FILES%)") == 2, "the list must drive both the backup and the restore"
    assert re.search(r"\bgit\b", text, re.IGNORECASE) is None, "build_all.bat must not depend on git"
    assert text.count("high_scores") == 1, "high_scores.json is named only in the backup list"
    print("[PASS] test_build_backup_list_names_the_same_files passed (backup and restore use progress.json, user_settings.json, high_scores.json; no git dependency)")


# ---------------------------------------------------------------------------
# Load: missing and corrupt files
# ---------------------------------------------------------------------------

def test_missing_files_load_defaults():
    with _sandbox() as tmp:
        assert ScoreTracker.load_high_scores() == {}, "a missing board reads as an empty board"
        assert ScoreTracker("normal").get_high_score() == 0
        assert progress.load() == progress.default_progress(), "a missing progress file reads as defaults"
        assert audio.load_audio_settings() == DEFAULT_VOLUMES, "missing settings read as the default volumes"
        assert os.listdir(tmp) == [], f"a read must not create files: {os.listdir(tmp)}"
    print("[PASS] test_missing_files_load_defaults passed (empty board, default progress, default volumes, no file created by a read)")


def test_corrupt_files_load_defaults_without_crashing():
    cases = (
        ("high_scores.json", '{"normal": [{"score": 12'),
        ("progress.json", '{"best_wave": 4, "best_sc'),
        ("user_settings.json", '{"music_volume": 0.3, "sfx_vol'),
    )
    with _sandbox() as tmp:
        for name, bad in cases:
            _write_text(os.path.join(tmp, name), bad)

        assert ScoreTracker.load_high_scores() == {}, "a corrupt board reads as an empty board"
        assert ScoreTracker("normal").get_high_score() == 0
        assert progress.load() == progress.default_progress(), "a corrupt progress file reads as defaults"
        assert audio.load_audio_settings() == DEFAULT_VOLUMES, "corrupt settings read as the default volumes"

        for name, bad in cases:
            path = os.path.join(tmp, name)
            assert not os.path.exists(path), f"{name} must be moved aside"
            assert _read_text(path + ".corrupt-1") == bad, f"{name}: the bad bytes must be kept"

        # A second read finds no file and does not rename anything again.
        assert ScoreTracker.load_high_scores() == {}
        assert progress.load() == progress.default_progress()
        assert audio.load_audio_settings() == DEFAULT_VOLUMES
        assert sorted(os.listdir(tmp)) == sorted(f"{name}.corrupt-1" for name, _ in cases), os.listdir(tmp)

        # A valid JSON file whose top level is not an object is corrupt too, and gets the next free number.
        _write_text(os.path.join(tmp, "progress.json"), "[1, 2, 3]")
        assert progress.load() == progress.default_progress(), "a non-object progress file reads as defaults"
        assert _read_text(os.path.join(tmp, "progress.json.corrupt-2")) == "[1, 2, 3]"
    print("[PASS] test_corrupt_files_load_defaults_without_crashing passed (defaults for all three, bad bytes kept as .corrupt-1, no second rename, non-object gets .corrupt-2)")


# ---------------------------------------------------------------------------
# Save: the first save creates the file
# ---------------------------------------------------------------------------

def test_first_save_creates_each_file():
    with _sandbox() as tmp:
        tracker = ScoreTracker("normal")
        tracker.score = 250
        assert tracker.submit_score(3) is True
        high = os.path.join(tmp, "high_scores.json")
        assert os.path.isfile(high), "the first submitted score must create high_scores.json"
        data = _read_json(high)
        assert data["version"] == 1 and data["normal"][0]["score"] == 250

        stats = achievements.RunStats()
        stats.finish(score=500, wave=2, survived=12.0)
        result = progress.end_run(stats)
        assert result["saved"] is True, "the first ended run must save"
        prog = os.path.join(tmp, "progress.json")
        assert os.path.isfile(prog), "the first ended run must create progress.json"
        assert _read_json(prog)["best_score"] == 500 and _read_json(prog)["runs_played"] == 1

        audio.save_audio_settings(0.25, 0.75)
        settings = os.path.join(tmp, "user_settings.json")
        assert os.path.isfile(settings), "the first volume change must create user_settings.json"
        assert _read_json(settings)["music_volume"] == 0.25
    print("[PASS] test_first_save_creates_each_file passed (high_scores.json, progress.json and user_settings.json each created by their first save)")


def test_default_saves_write_the_defaults():
    with _sandbox() as tmp:
        ScoreTracker.save_high_scores({})
        assert _read_json(os.path.join(tmp, "high_scores.json")) == {"version": 1}, "an empty board is the default"
        assert ScoreTracker("normal").get_high_score() == 0

        prog = os.path.join(tmp, "progress.json")
        assert progress.save(progress.default_progress(), prog) is True
        assert _read_json(prog) == progress.default_progress(), "the saved file is the default record"
        assert progress.load() == progress.default_progress()

        audio.save_audio_settings(*DEFAULT_VOLUMES)
        settings = _read_json(os.path.join(tmp, "user_settings.json"))
        assert settings["version"] == 1 and (settings["music_volume"], settings["sfx_volume"]) == DEFAULT_VOLUMES
        assert audio.load_audio_settings() == DEFAULT_VOLUMES
    print("[PASS] test_default_saves_write_the_defaults passed (empty board, default progress and default volumes are written as the first files)")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all():
    real_before = {name: _digest(os.path.join(HERE, name)) for name in SAVE_FILES}

    test_index_does_not_track_high_scores()
    test_save_files_replays_and_leftovers_are_ignored()
    test_build_backup_list_names_the_same_files()
    test_missing_files_load_defaults()
    test_corrupt_files_load_defaults_without_crashing()
    test_first_save_creates_each_file()
    test_default_saves_write_the_defaults()

    real_after = {name: _digest(os.path.join(HERE, name)) for name in SAVE_FILES}
    assert real_before == real_after, "a test changed a real save file in the project root"
    print("\nALL SAVES-UNTRACKED TESTS PASSED")


if __name__ == "__main__":
    run_all()
