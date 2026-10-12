"""Save-data robustness tests (wave 3, saferobust).

Covers the three save formats: progress.json, user_settings.json and high_scores.json. Every test points
audio._SETTINGS_PATH and score.HIGH_SCORE_FILE at a temp folder, so the real files in the project root are
never read or written. run_all() checks that the real files are unchanged at the end.
"""

import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager

import audio
import savefile
import score as score_mod
import shake_prefs
from savefile import (
    HIGH_SCORES_VERSION,
    PROGRESS_VERSION,
    USER_SETTINGS_VERSION,
    atomic_write_json,
    board_entries,
    load_settings,
    load_versioned,
    migrate_high_scores,
    migrate_progress,
    save_versioned,
    update_settings,
)
from score import ScoreTracker

HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT_FILES = ("high_scores.json", "user_settings.json", "progress.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def _sandbox():
    """Temp folder with the settings and board paths redirected into it. Restores the real paths on exit."""
    saved_settings = audio._SETTINGS_PATH
    saved_board = score_mod.HIGH_SCORE_FILE
    with tempfile.TemporaryDirectory(prefix="plouto_saferobust_") as tmp:
        audio._SETTINGS_PATH = os.path.join(tmp, "user_settings.json")
        score_mod.HIGH_SCORE_FILE = os.path.join(tmp, "high_scores.json")
        try:
            yield tmp
        finally:
            audio._SETTINGS_PATH = saved_settings
            score_mod.HIGH_SCORE_FILE = saved_board


@contextmanager
def _patched_replace(fn):
    real = os.replace
    os.replace = fn
    try:
        yield
    finally:
        os.replace = real


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _write_bytes(path, raw):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(raw)


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


def _names(folder):
    return sorted(os.listdir(folder))


def _progress_default():
    return {"version": PROGRESS_VERSION, "best_wave": 0, "best_score": 0, "total_kills": 0, "runs_played": 0}


def _entry(score, wave=3, kills=4, combo=2.0, date="2026-01-01 00:00"):
    return {"score": score, "wave": wave, "kills": kills, "best_combo": combo, "date": date}


# ---------------------------------------------------------------------------
# Atomic write helper
# ---------------------------------------------------------------------------

def test_atomic_write_replaces_within_the_same_folder():
    with _sandbox() as tmp:
        path = os.path.join(tmp, "sample.json")
        seen = []
        real = os.replace

        def spy(src, dst):
            seen.append((os.path.dirname(os.path.abspath(src)), os.path.dirname(os.path.abspath(dst))))
            return real(src, dst)

        with _patched_replace(spy):
            assert atomic_write_json(path, {"a": 1}) is True
        assert len(seen) == 1, f"one os.replace per write, got {len(seen)}"
        assert seen[0][0] == seen[0][1] == os.path.abspath(tmp), "the temp file must sit beside the target"
        assert _read_json(path) == {"a": 1}
        assert _names(tmp) == ["sample.json"], f"no temp file may be left behind: {_names(tmp)}"
    print("[PASS] test_atomic_write_replaces_within_the_same_folder passed (temp file beside target, one os.replace, no leftovers)")


def test_failed_replace_keeps_the_previous_file():
    with _sandbox() as tmp:
        path = os.path.join(tmp, "sample.json")
        _write_text(path, '{"keep": true}')

        def refuse(src, dst):
            raise PermissionError("target is locked")

        with _patched_replace(refuse):
            assert atomic_write_json(path, {"keep": False}) is False
        assert _read_text(path) == '{"keep": true}', "a failed write must leave the old file intact"
        assert _names(tmp) == ["sample.json"], f"the temp file must be removed on failure: {_names(tmp)}"
    print("[PASS] test_failed_replace_keeps_the_previous_file passed (old bytes kept, temp removed, returns False)")


def test_unserialisable_data_keeps_the_previous_file():
    with _sandbox() as tmp:
        path = os.path.join(tmp, "sample.json")
        _write_text(path, '{"keep": true}')
        assert atomic_write_json(path, {"bad": object()}) is False
        assert _read_text(path) == '{"keep": true}'
        assert _names(tmp) == ["sample.json"]
    print("[PASS] test_unserialisable_data_keeps_the_previous_file passed (serialising first means no partial file)")


def test_every_writer_goes_through_the_helper():
    for name in ("audio.py", "shake_prefs.py", "score.py"):
        with open(os.path.join(HERE, name), "r", encoding="utf-8") as fh:
            src = fh.read()
        assert "os.replace(" not in src, f"{name} must not call os.replace itself"
        assert "json.dump(" not in src, f"{name} must not write JSON itself"
        assert not re.search(r"open\([^)]*[\"']w", src), f"{name} must not open a file for writing"
    with open(savefile.__file__, "r", encoding="utf-8") as fh:
        assert "os.replace(" in fh.read(), "the one atomic helper lives in savefile.py"
    print("[PASS] test_every_writer_goes_through_the_helper passed (audio, shake_prefs and score only write via savefile)")


# ---------------------------------------------------------------------------
# user_settings.json
# ---------------------------------------------------------------------------

def test_unversioned_settings_from_the_current_build_migrate():
    with _sandbox() as tmp:
        path = audio._SETTINGS_PATH
        _write_text(path, json.dumps({
            "music_volume": 0.3, "sfx_volume": 0.6, "shake_level": "reduced", "reduced_shake": True,
        }))
        music, sfx = audio.load_audio_settings()
        assert abs(music - 0.3) < 1e-9 and abs(sfx - 0.6) < 1e-9, (music, sfx)
        assert shake_prefs.load_shake_level() == "reduced"
        assert "version" not in _read_json(path), "loading must not rewrite the file"

        audio.save_audio_settings(0.25, 0.75)
        data = _read_json(path)
        assert data["version"] == USER_SETTINGS_VERSION == 1
        assert list(data)[0] == "version", "the version key leads the file"
        assert data["music_volume"] == 0.25 and data["sfx_volume"] == 0.75
        assert data["shake_level"] == "reduced" and data["reduced_shake"] is True, "a volume save keeps the shake keys"
        assert _names(tmp) == ["user_settings.json"]
    print("[PASS] test_unversioned_settings_from_the_current_build_migrate passed (v0 read, saved as v1, shake keys kept)")


def test_legacy_reduced_shake_only_file_migrates_to_a_level():
    with _sandbox():
        path = audio._SETTINGS_PATH
        _write_text(path, json.dumps({"reduced_shake": True, "music_volume": 0.4}))
        assert load_settings(path)["shake_level"] == "reduced", "the oldest builds only wrote reduced_shake"
        assert shake_prefs.load_shake_level() == "reduced"
        assert shake_prefs.save_shake_level("off") is None
        data = _read_json(path)
        assert data["version"] == 1 and data["shake_level"] == "off" and data["reduced_shake"] is True
        assert data["music_volume"] == 0.4, "saving the shake level keeps the audio volume"
    print("[PASS] test_legacy_reduced_shake_only_file_migrates_to_a_level passed (reduced_shake maps to shake_level, then v1)")


def test_settings_update_keeps_unknown_keys():
    with _sandbox():
        path = audio._SETTINGS_PATH
        _write_text(path, json.dumps({"music_volume": 0.3, "custom_key": "keep me"}))
        assert update_settings(path, {"reduced_shake": False}) is True
        data = _read_json(path)
        assert data["custom_key"] == "keep me", "keys this build does not know must survive a save"
        assert data["reduced_shake"] is False and data["music_volume"] == 0.3 and data["version"] == 1
    print("[PASS] test_settings_update_keeps_unknown_keys passed (shared helper keeps every other key)")


def test_settings_corrupt_file_is_renamed_once_and_starts_with_defaults():
    with _sandbox() as tmp:
        path = audio._SETTINGS_PATH
        bad = '{"music_volume": 0.3, "sfx_vol'
        _write_text(path, bad)
        assert audio.load_audio_settings() == (0.5, 0.8), "a corrupt file must start the game on defaults"
        assert not os.path.exists(path), "the corrupt file must be moved aside"
        assert _read_text(os.path.join(tmp, "user_settings.json.corrupt-1")) == bad, "the bad bytes must be kept"
        assert shake_prefs.load_shake_level() == "full"
        assert audio.load_audio_settings() == (0.5, 0.8)
        assert _names(tmp) == ["user_settings.json.corrupt-1"], f"renamed only once: {_names(tmp)}"
        audio.save_audio_settings(0.2, 0.9)
        assert audio.load_audio_settings() == (0.2, 0.9), "a save after recovery writes a clean file"
    print("[PASS] test_settings_corrupt_file_is_renamed_once_and_starts_with_defaults passed (defaults, bad bytes kept as .corrupt-1, no overwrite of the bad file)")


def test_settings_missing_directory_reads_defaults_and_save_creates_it():
    with _sandbox() as tmp:
        audio._SETTINGS_PATH = os.path.join(tmp, "missing", "deeper", "user_settings.json")
        assert audio.load_audio_settings() == (0.5, 0.8), "a missing folder must read as defaults"
        assert shake_prefs.load_shake_level() == "full"
        assert not os.path.isdir(os.path.dirname(audio._SETTINGS_PATH)), "a read must not create folders"
        audio.save_audio_settings(0.1, 0.2)
        assert audio.load_audio_settings() == (0.1, 0.2)
        assert _read_json(audio._SETTINGS_PATH)["version"] == 1
    print("[PASS] test_settings_missing_directory_reads_defaults_and_save_creates_it passed (no raise, folder created on save)")


def test_newer_settings_version_is_kept_not_downgraded():
    with _sandbox():
        path = audio._SETTINGS_PATH
        _write_text(path, json.dumps({"version": 9, "music_volume": 0.2, "future": [1, 2]}))
        assert audio.load_audio_settings() == (0.2, 0.8), "a newer file is read best effort"
        assert load_settings(path)["version"] == 9
        assert update_settings(path, {"sfx_volume": 0.4}) is True
        data = _read_json(path)
        assert data["version"] == 9, "saving must never lower a newer version"
        assert data["future"] == [1, 2], "keys from a newer build must survive"
        assert not any(".corrupt" in n for n in _names(os.path.dirname(path))), "a newer file is valid, not corrupt"
    print("[PASS] test_newer_settings_version_is_kept_not_downgraded passed (version 9 kept, unknown keys kept, not quarantined)")


# ---------------------------------------------------------------------------
# high_scores.json
# ---------------------------------------------------------------------------

def test_high_scores_with_extra_keys_load_migrate_and_keep_extras():
    with _sandbox():
        path = score_mod.HIGH_SCORE_FILE
        _write_text(path, json.dumps({
            "normal": [
                _entry(500, wave=4, kills=9, combo=2.0),
                "junk",
                {"wave": 2},
                {"score": "120", "wave": 1, "kills": 1, "best_combo": 1.0, "date": "x"},
            ],
            "hard": "not a board",
            "weekly": {"tag": "x"},
            "notes": 7,
        }))
        normal = ScoreTracker("normal")
        assert normal.get_high_score() == 500, "the extras must not hide the real top score"
        assert ScoreTracker("hard").get_high_score() == 0, "a non-list board reads as empty"

        normal.score = 600
        normal.kills = 12
        assert normal.submit_score(5) is True and normal.last_rank == 1
        data = _read_json(path)
        assert data["version"] == 1 and list(data)[0] == "version"
        assert [e["score"] for e in data["normal"]] == [600, 500, 120], "malformed entries are dropped, numeric strings kept"
        assert data["weekly"] == {"tag": "x"} and data["notes"] == 7, "extra keys survive a save"
        assert data["hard"] == "not a board", "a non-list value is an extra and is left alone"
        assert not any(".corrupt" in n for n in _names(os.path.dirname(path))), "extra keys are not corruption"
    print("[PASS] test_high_scores_with_extra_keys_load_migrate_and_keep_extras passed (malformed entries dropped, extras kept, version 1)")


def test_unversioned_high_scores_board_migrates_on_first_save():
    with _sandbox():
        path = score_mod.HIGH_SCORE_FILE
        _write_text(path, json.dumps({"normal": [_entry(300)]}))
        assert ScoreTracker("normal").get_high_score() == 300
        t = ScoreTracker("normal")
        t.score = 100
        assert t.submit_score(2) is False and t.last_rank == 2
        data = _read_json(path)
        assert data["version"] == HIGH_SCORES_VERSION == 1
        assert [e["score"] for e in data["normal"]] == [300, 100]
    print("[PASS] test_unversioned_high_scores_board_migrates_on_first_save passed (unversioned board stamped v1 on save)")


def test_high_scores_missing_directory_reads_empty_and_save_creates_it():
    with _sandbox() as tmp:
        score_mod.HIGH_SCORE_FILE = os.path.join(tmp, "no_such_dir", "high_scores.json")
        assert ScoreTracker.load_high_scores() == {}, "a missing folder reads as an empty board"
        assert ScoreTracker("normal").get_high_score() == 0
        t = ScoreTracker("normal")
        t.score = 250
        assert t.submit_score(3) is True
        assert os.path.exists(score_mod.HIGH_SCORE_FILE), "the save must create the folder and the file"
        assert _read_json(score_mod.HIGH_SCORE_FILE)["normal"][0]["score"] == 250
    print("[PASS] test_high_scores_missing_directory_reads_empty_and_save_creates_it passed (no raise, folder created)")


def test_corrupt_high_scores_is_kept_and_the_run_still_saves():
    with _sandbox() as tmp:
        path = score_mod.HIGH_SCORE_FILE
        bad = "[1, 2"
        _write_text(path, bad)
        t = ScoreTracker("normal")
        t.score = 250
        assert t.submit_score(3) is True, "a corrupt board must not block a new score"
        assert _read_text(os.path.join(tmp, "high_scores.json.corrupt-1")) == bad, "the bad board must be kept"
        data = _read_json(path)
        assert data["version"] == 1 and data["normal"][0]["score"] == 250
    print("[PASS] test_corrupt_high_scores_is_kept_and_the_run_still_saves passed (bad board renamed, run saved on a clean board)")


def test_board_entries_drop_malformed_rows():
    cleaned = board_entries({"normal": [_entry(5), "x", None, {"score": None}, {"score": True}, {"score": 7.9}]}, "normal")
    assert [e["score"] for e in cleaned] == [5, 7], cleaned
    assert board_entries({"normal": "text"}, "normal") == []
    assert board_entries({}, "normal") == []
    migrated = migrate_high_scores({"normal": [{"score": float("nan")}, _entry(9)]}, 0)
    assert [e["score"] for e in migrated["normal"]] == [9], "NaN scores are dropped"
    print("[PASS] test_board_entries_drop_malformed_rows passed (bools, NaN, None and non-dict rows never reach the scorer)")


# ---------------------------------------------------------------------------
# progress.json (the format; progress.py is the owner, see the guarded test below)
# ---------------------------------------------------------------------------

def test_truncated_progress_is_quarantined_and_starts_with_defaults():
    with _sandbox() as tmp:
        path = os.path.join(tmp, "progress.json")
        truncated = '{"best_wave": 4, "best_score": 1200, "total_k'
        _write_text(path, truncated)
        got = load_versioned(path, PROGRESS_VERSION, migrate_progress, _progress_default)
        assert got == _progress_default(), got
        assert not os.path.exists(path), "the truncated file must be moved aside"
        assert _read_text(path + ".corrupt-1") == truncated, "the truncated bytes must be kept"
        again = load_versioned(path, PROGRESS_VERSION, migrate_progress, _progress_default)
        assert again == _progress_default()
        assert not os.path.exists(path + ".corrupt-2"), "a corrupt file is renamed once, not on every load"
        assert save_versioned(path, dict(_progress_default(), best_wave=5), PROGRESS_VERSION) is True
        assert load_versioned(path, PROGRESS_VERSION, migrate_progress, _progress_default)["best_wave"] == 5
    print("[PASS] test_truncated_progress_is_quarantined_and_starts_with_defaults passed (defaults, bad bytes kept as .corrupt-1, renamed once)")


def test_unversioned_progress_migrates_to_version_one():
    with _sandbox() as tmp:
        path = os.path.join(tmp, "progress.json")
        _write_text(path, json.dumps({"best_wave": 7, "total_kills": 40}))
        got = load_versioned(path, PROGRESS_VERSION, migrate_progress, _progress_default)
        assert got["version"] == PROGRESS_VERSION == 1 and got["best_wave"] == 7 and got["total_kills"] == 40
        assert list(got)[0] == "version"
        assert not any(".corrupt" in n for n in _names(tmp))
    print("[PASS] test_unversioned_progress_migrates_to_version_one passed (unversioned read as v0, stamped v1, values kept)")


def test_progress_module_uses_savefile_when_present():
    try:
        import progress  # noqa: F401  (owned by wave 1)
    except ImportError:
        print("[SKIP requires-wave1] progress.py is not in this worktree; progress.load_progress must call savefile.load_versioned, checked at integration")
        return
    with _sandbox() as tmp:
        path = os.path.join(tmp, "progress.json")
        _write_text(path, '{"best_wave": 4, "best_sc')
        got = progress.load_progress(path)
        assert isinstance(got, dict), "load_progress never raises and returns a dict"
        assert not os.path.exists(path) and os.path.exists(path + ".corrupt-1"), "a truncated progress.json must be quarantined"
    print("[PASS] test_progress_module_uses_savefile_when_present passed (progress.py quarantines a truncated file)")


# ---------------------------------------------------------------------------
# Corruption edge cases shared by every format
# ---------------------------------------------------------------------------

def test_second_corrupt_file_gets_the_next_number():
    with _sandbox() as tmp:
        path = audio._SETTINGS_PATH
        _write_text(path, "{ first")
        load_settings(path)
        _write_text(path, "{ second")
        load_settings(path)
        assert _read_text(path + ".corrupt-1") == "{ first"
        assert _read_text(path + ".corrupt-2") == "{ second", "a later corrupt file must not overwrite an earlier one"
        assert _names(tmp) == ["user_settings.json.corrupt-1", "user_settings.json.corrupt-2"]
    print("[PASS] test_second_corrupt_file_gets_the_next_number passed (earlier quarantines are never overwritten)")


def test_non_object_empty_and_binary_files_are_corrupt():
    cases = {
        "list": b"[1, 2, 3]",
        "empty": b"",
        "binary": b"\xff\xfe\x00\x01garbage",
    }
    with _sandbox() as tmp:
        for label, raw in cases.items():
            path = os.path.join(tmp, f"{label}.json")
            _write_bytes(path, raw)
            got = load_versioned(path, USER_SETTINGS_VERSION, savefile.migrate_user_settings, dict)
            assert got == {}, f"{label}: must read as defaults, got {got}"
            assert not os.path.exists(path), f"{label}: must be quarantined"
            with open(path + ".corrupt-1", "rb") as fh:
                assert fh.read() == raw, f"{label}: bytes must be kept"
    print("[PASS] test_non_object_empty_and_binary_files_are_corrupt passed (list, empty and non-UTF-8 files are quarantined)")


def test_invalid_version_counts_as_unversioned_and_is_not_quarantined():
    with _sandbox() as tmp:
        path = audio._SETTINGS_PATH
        for raw_version in ('"two"', "true", "-3", "1.5"):
            _write_text(path, '{"version": %s, "music_volume": 0.6}' % raw_version)
            assert audio.load_audio_settings()[0] == 0.6, raw_version
            assert load_settings(path)["version"] == 1, raw_version
        assert not any(".corrupt" in n for n in _names(tmp)), "an odd version is not corruption"
    print("[PASS] test_invalid_version_counts_as_unversioned_and_is_not_quarantined passed (string, bool, negative and float versions read as v0)")


def test_quarantine_falls_back_to_copy_when_rename_is_refused():
    with _sandbox() as tmp:
        path = audio._SETTINGS_PATH
        raw = '{"music_volume": 0.3, "sfx_'
        _write_text(path, raw)

        def refuse(src, dst):
            raise PermissionError("rename refused")

        with _patched_replace(refuse):
            assert audio.load_audio_settings() == (0.5, 0.8)
        assert _read_text(path + ".corrupt-1") == raw, "the bad bytes must survive even when rename is refused"
    print("[PASS] test_quarantine_falls_back_to_copy_when_rename_is_refused passed (copy keeps the bad bytes)")


def test_format_versions_are_all_one():
    assert PROGRESS_VERSION == 1 and USER_SETTINGS_VERSION == 1 and HIGH_SCORES_VERSION == 1
    print("[PASS] test_format_versions_are_all_one passed (progress, user_settings and high_scores at version 1)")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _summary():
    print("\nFile format report (saferobust):")
    print("  progress.json      version 1 | v0 (unversioned) and newer files migrate or pass through | truncated, non-object or undecodable -> progress.json.corrupt-<n>, defaults")
    print("  user_settings.json version 1 | v0 migrates, reduced_shake-only files derive shake_level | corrupt -> user_settings.json.corrupt-<n>, defaults")
    print("  high_scores.json   version 1 | v0 migrates, malformed rows dropped, extra keys kept | corrupt -> high_scores.json.corrupt-<n>, empty board")


def run_all():
    real_before = {name: _digest(os.path.join(HERE, name)) for name in _ROOT_FILES}

    test_atomic_write_replaces_within_the_same_folder()
    test_failed_replace_keeps_the_previous_file()
    test_unserialisable_data_keeps_the_previous_file()
    test_every_writer_goes_through_the_helper()
    test_unversioned_settings_from_the_current_build_migrate()
    test_legacy_reduced_shake_only_file_migrates_to_a_level()
    test_settings_update_keeps_unknown_keys()
    test_settings_corrupt_file_is_renamed_once_and_starts_with_defaults()
    test_settings_missing_directory_reads_defaults_and_save_creates_it()
    test_newer_settings_version_is_kept_not_downgraded()
    test_high_scores_with_extra_keys_load_migrate_and_keep_extras()
    test_unversioned_high_scores_board_migrates_on_first_save()
    test_high_scores_missing_directory_reads_empty_and_save_creates_it()
    test_corrupt_high_scores_is_kept_and_the_run_still_saves()
    test_board_entries_drop_malformed_rows()
    test_truncated_progress_is_quarantined_and_starts_with_defaults()
    test_unversioned_progress_migrates_to_version_one()
    test_progress_module_uses_savefile_when_present()
    test_second_corrupt_file_gets_the_next_number()
    test_non_object_empty_and_binary_files_are_corrupt()
    test_invalid_version_counts_as_unversioned_and_is_not_quarantined()
    test_quarantine_falls_back_to_copy_when_rename_is_refused()
    test_format_versions_are_all_one()

    real_after = {name: _digest(os.path.join(HERE, name)) for name in _ROOT_FILES}
    assert real_before == real_after, "a test changed a real save file in the project root"
    _summary()
    print("\nALL SAVE-DATA ROBUSTNESS TESTS PASSED")


if __name__ == "__main__":
    run_all()
