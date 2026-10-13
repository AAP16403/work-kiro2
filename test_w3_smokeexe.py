"""Wave 3 "smokeexe" tests: asset coverage, the PyInstaller spec, the exe smoke script and pinned build deps.

Run from the project root:  .venv\\Scripts\\python.exe test_w3_smokeexe.py
Each test prints a [PASS] line. Nothing here touches the real high_scores.json, user_settings.json or
dist folder: anything that writes or deletes files works on temporary copies.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

import asset_manifest

ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(ROOT, "kiro2_game.spec")
SMOKE = os.path.join(ROOT, "tools", "smoke_exe.ps1")
REQUIREMENTS = os.path.join(ROOT, "requirements.txt")
BUILD_BAT = os.path.join(ROOT, "build_all.bat")
REAL_EXE = os.path.join(ROOT, "dist", "Plouto", "Plouto.exe")
POWERSHELL = "powershell.exe"
SYSTEM_EXITS_AT_ONCE = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "hostname.exe")

_IGNORE_WHEN_COPYING = shutil.ignore_patterns(
    ".git", ".venv", ".claude", "dist", "build", "__pycache__", "vercel_site", "*.log",
    "user_settings.json", "high_scores.json",
)


class _Blob:
    """Stands in for PyInstaller's Analysis/PYZ/EXE/COLLECT results: any attribute is None."""

    def __getattr__(self, name):
        return None


def _exec_spec(spec_path, specpath):
    """Run kiro2_game.spec with PyInstaller's build objects stubbed. Returns {name: (args, kwargs)}."""
    calls = {}

    def make(name):
        def ctor(*args, **kwargs):
            calls[name] = (args, kwargs)
            return _Blob()
        return ctor

    namespace = {"__file__": spec_path, "SPECPATH": specpath}
    namespace.update({name: make(name) for name in ("Analysis", "PYZ", "EXE", "COLLECT")})
    with open(spec_path, "r", encoding="utf-8-sig") as fh:
        code = compile(fh.read(), spec_path, "exec")
    saved_path = list(sys.path)
    try:
        exec(code, namespace)
    finally:
        sys.path[:] = saved_path
    return calls


def _spec_datas(specpath):
    calls = _exec_spec(os.path.join(specpath, "kiro2_game.spec"), specpath)
    return calls["Analysis"][1]["datas"]


def _copy_project(dest):
    shutil.copytree(ROOT, dest, ignore=_IGNORE_WHEN_COPYING, dirs_exist_ok=True)
    return dest


def _run_smoke(*args):
    cmd = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", SMOKE, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=240)


def _has_pyinstaller():
    try:
        import PyInstaller.utils.hooks  # noqa: F401
    except ImportError:
        return False
    return True


def test_sound_names_resolve_from_literals_conditionals_and_tables():
    src = (
        "audio.play(\"hit_crit\" if crit else \"hit\", volume=0.5)\n"
        "audio.play(_SHOT_SFX.get(name, \"shot_basic\"), volume=0.4)\n"
        "audio.play(name=\"ui_click\")\n"
        "player.play()\n"
        "_SHOT_SFX = {\"Basic Gun\": \"shot_basic\", \"Flak\": \"shot_flak\"}\n"
        "audio.play(dynamic_name)\n"
    )
    tmp = tempfile.mkdtemp(prefix="w3_sfx_")
    try:
        with open(os.path.join(tmp, "game_fake.py"), "w", encoding="utf-8") as fh:
            fh.write(src)
        names, unresolved = asset_manifest.scan_sound_names(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    expected = {"hit_crit", "hit", "shot_basic", "shot_flak", "ui_click"}
    assert names == expected, f"sound names {sorted(names)} != {sorted(expected)}"
    line = src.splitlines().index("audio.play(dynamic_name)") + 1
    assert unresolved == [f"game_fake.py:{line}"], f"unresolved sites {unresolved}"
    print("[PASS] test_sound_names_resolve_from_literals_conditionals_and_tables passed "
          "(conditional, get-default, keyword and table names resolved; dynamic name flagged)")


def test_current_tree_references_resolve_and_are_bundled():
    refs, unresolved = asset_manifest.referenced_assets(ROOT)
    assert not unresolved, f"play() arguments that are not literal names: {unresolved}"
    for must in (
        "assets/fonts/Orbitron-Variable.ttf",
        "assets/audio/music_menu.wav",
        "assets/audio/music_battle.wav",
        "assets/audio/sfx_hit.wav",
        "assets/audio/sfx_hit_crit.wav",
        "assets/audio/sfx_shot_basic.wav",
        "assets/audio/sfx_game_over.wav",
    ):
        assert must in refs, f"{must} is opened by the code but not found by the scan"
    report = asset_manifest.verify_bundle(asset_manifest.bundle_datas(ROOT), ROOT)
    assert not report["missing_on_disk"] and not report["not_bundled"]
    print(f"[PASS] test_current_tree_references_resolve_and_are_bundled passed "
          f"({len(refs)} opened assets, all on disk and bundled)")


def test_spec_bundles_every_file_in_each_asset_folder():
    if not _has_pyinstaller():
        print("[SKIP requires-pyinstaller] spec bundling test (PyInstaller is not installed)")
        return
    datas = _spec_datas(ROOT)
    dests = {dest for _, dest in datas}
    assert dests == set(asset_manifest.ASSET_FOLDERS), f"bundle folders {dests}"
    on_disk = set()
    for folder in asset_manifest.ASSET_FOLDERS:
        folder_path = os.path.join(ROOT, *folder.split("/"))
        for name in os.listdir(folder_path):
            if os.path.isfile(os.path.join(folder_path, name)):
                on_disk.add(f"{folder}/{name}")
    bundled = asset_manifest.bundled_assets(datas)
    assert bundled == on_disk, f"bundled {sorted(bundled ^ on_disk)} differ from the folders"
    print(f"[PASS] test_spec_bundles_every_file_in_each_asset_folder passed "
          f"({len(bundled)} files bundled, equal to the asset folders on disk)")


def test_spec_build_fails_when_a_referenced_asset_is_missing_from_the_tree():
    if not _has_pyinstaller():
        print("[SKIP requires-pyinstaller] spec failure test (PyInstaller is not installed)")
        return
    tmp = tempfile.mkdtemp(prefix="w3_spec_")
    try:
        copy = _copy_project(os.path.join(tmp, "project"))
        victim = os.path.join(copy, "assets", "audio", "sfx_hit.wav")
        os.remove(victim)
        try:
            _exec_spec(os.path.join(copy, "kiro2_game.spec"), copy)
        except RuntimeError as exc:
            message = str(exc)
        else:
            raise AssertionError("spec built although assets/audio/sfx_hit.wav is missing")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert "assets/audio/sfx_hit.wav" in message and "missing from the source tree" in message, message
    print("[PASS] test_spec_build_fails_when_a_referenced_asset_is_missing_from_the_tree passed "
          "(spec raised and named the missing WAV)")


def test_coverage_flags_a_referenced_asset_dropped_from_the_bundle():
    datas = asset_manifest.bundle_datas(ROOT)
    dropped = [entry for entry in datas if entry[0].replace("\\", "/").endswith("assets/fonts/Rajdhani-SemiBold.ttf")]
    assert dropped, "test precondition: the font must be bundled first"
    trimmed = [entry for entry in datas if entry not in dropped]
    try:
        asset_manifest.verify_bundle(trimmed, ROOT)
    except RuntimeError as exc:
        assert "not bundled by the spec: assets/fonts/Rajdhani-SemiBold.ttf" in str(exc), str(exc)
    else:
        raise AssertionError("verify_bundle passed although a font the code opens is not bundled")
    report = asset_manifest.coverage(trimmed, ROOT)
    assert report["not_bundled"] == ["assets/fonts/Rajdhani-SemiBold.ttf"], report["not_bundled"]
    print("[PASS] test_coverage_flags_a_referenced_asset_dropped_from_the_bundle passed "
          "(verify_bundle raised and named the font)")


def test_coverage_cli_passes_on_current_tree_and_lists_assets():
    listed = subprocess.run([sys.executable, os.path.join(ROOT, "asset_manifest.py"), "--list"],
                            capture_output=True, text=True, timeout=120)
    assert listed.returncode == 0, listed.stderr
    lines = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
    assert "assets/audio/music_battle.wav" in lines and "assets/fonts/Orbitron-Variable.ttf" in lines, lines
    checked = subprocess.run([sys.executable, os.path.join(ROOT, "asset_manifest.py")],
                             capture_output=True, text=True, timeout=120)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "OK: every asset the code opens" in checked.stdout, checked.stdout
    print(f"[PASS] test_coverage_cli_passes_on_current_tree_and_lists_assets passed "
          f"({len(lines)} assets listed, check exit 0)")


def test_smoke_script_is_valid_powershell():
    if not os.path.isfile(SMOKE):
        raise AssertionError(f"missing {SMOKE}")
    script = (
        "$e=$null; $t=$null; "
        "[void][System.Management.Automation.Language.Parser]::ParseFile($env:W3_SMOKE_PS1, [ref]$t, [ref]$e); "
        "if ($e -and $e.Count -gt 0) { $e | ForEach-Object { Write-Output $_.Message }; exit 1 }; "
        "Write-Output 'PARSE_OK'"
    )
    env = dict(os.environ, W3_SMOKE_PS1=SMOKE)
    result = subprocess.run([POWERSHELL, "-NoProfile", "-Command", script],
                            capture_output=True, text=True, timeout=120, env=env)
    assert result.returncode == 0 and "PARSE_OK" in result.stdout, result.stdout + result.stderr
    print("[PASS] test_smoke_script_is_valid_powershell passed (tools/smoke_exe.ps1 parses)")


def test_smoke_fails_with_exit_1_when_there_is_no_build():
    tmp = tempfile.mkdtemp(prefix="w3_nobuild_")
    try:
        result = _run_smoke("-DistDir", tmp, "-WaitSeconds", "1")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert result.returncode == 1, f"exit {result.returncode}: {result.stdout}{result.stderr}"
    assert "no build at" in result.stdout, result.stdout
    print("[PASS] test_smoke_fails_with_exit_1_when_there_is_no_build passed (exit 1, no exe)")


def test_smoke_fails_with_exit_1_when_the_process_exits_early():
    tmp = tempfile.mkdtemp(prefix="w3_early_")
    try:
        dist = os.path.join(tmp, "dist")
        os.makedirs(dist)
        shutil.copy2(SYSTEM_EXITS_AT_ONCE, os.path.join(dist, "Plouto.exe"))  # prints a name and exits 0
        shutil.copytree(os.path.join(ROOT, "assets"), os.path.join(dist, "_internal", "assets"))
        result = _run_smoke("-DistDir", dist, "-WaitSeconds", "6")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert result.returncode == 1, f"exit {result.returncode}: {result.stdout}{result.stderr}"
    assert "exited within" in result.stdout, result.stdout
    assert "ASSETS OK" in result.stdout, result.stdout
    print("[PASS] test_smoke_fails_with_exit_1_when_the_process_exits_early passed "
          "(asset check passed, dead process gave exit 1)")


def test_smoke_fails_when_an_asset_is_missing_from_the_build():
    if not os.path.isfile(SYSTEM_EXITS_AT_ONCE):
        raise AssertionError("hostname.exe is needed as a stand-in exe")
    tmp = tempfile.mkdtemp(prefix="w3_missing_")
    try:
        dist = os.path.join(tmp, "dist")
        os.makedirs(dist)
        shutil.copy2(SYSTEM_EXITS_AT_ONCE, os.path.join(dist, "Plouto.exe"))
        shutil.copytree(os.path.join(ROOT, "assets"), os.path.join(dist, "_internal", "assets"))
        os.remove(os.path.join(dist, "_internal", "assets", "audio", "sfx_shot_flak.wav"))
        result = _run_smoke("-DistDir", dist, "-WaitSeconds", "1")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert result.returncode == 1, f"exit {result.returncode}: {result.stdout}{result.stderr}"
    assert "missing from build: _internal\\assets\\audio\\sfx_shot_flak.wav" in result.stdout, result.stdout
    print("[PASS] test_smoke_fails_when_an_asset_is_missing_from_the_build passed "
          "(missing WAV named, exit 1, exe never started)")


def test_smoke_passes_against_the_built_exe_when_present():
    if not os.path.isfile(REAL_EXE):
        print("[SKIP no-build] smoke run against dist\\Plouto\\Plouto.exe (run build_all.bat first)")
        return
    result = _run_smoke("-WaitSeconds", "6")
    assert result.returncode == 0, f"exit {result.returncode}: {result.stdout}{result.stderr}"
    assert "SMOKE PASS" in result.stdout, result.stdout
    print("[PASS] test_smoke_passes_against_the_built_exe_when_present passed "
          "(built Plouto.exe alive after 6 s, exit 0)")


def test_requirements_pin_the_tested_pyglet_and_build_installs_from_them():
    with open(REQUIREMENTS, "r", encoding="utf-8") as fh:
        pins = {}
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            match = re.fullmatch(r"([A-Za-z0-9_.\-]+)==([0-9][A-Za-z0-9.+\-]*)", line)
            assert match, f"requirements.txt line is not an exact pin: {line!r}"
            pins[match.group(1).lower()] = match.group(2)
    assert pins.get("pyglet") == "2.1.19", f"pyglet pin is {pins.get('pyglet')!r}, expected 2.1.19"
    for needed in ("pyinstaller", "moderngl"):
        assert needed in pins, f"{needed} is not pinned"

    with open(BUILD_BAT, "r", encoding="utf-8-sig") as fh:
        bat = fh.read()
    assert "pip install -r requirements.txt" in bat, "build_all.bat must install from requirements.txt"
    assert not re.search(r"pip install\s+-U", bat), "build_all.bat must not upgrade packages"
    assert "pyglet pyinstaller moderngl" not in bat, "build_all.bat still installs unpinned packages"
    assert bat.index("asset_manifest.py") < bat.index("Building executable"), \
        "build_all.bat must check asset coverage before PyInstaller runs"
    print(f"[PASS] test_requirements_pin_the_tested_pyglet_and_build_installs_from_them passed "
          f"(pins: {', '.join(f'{k}=={v}' for k, v in sorted(pins.items()))})")


def main():
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    failures = 0
    for fn in tests:
        try:
            fn()
        except Exception as exc:  # report every failing test, then exit non-zero
            failures += 1
            print(f"[FAIL] {fn.__name__}: {exc}")
    if failures:
        print(f"{failures} of {len(tests)} W3 smokeexe tests FAILED")
        return 1
    print(f"ALL {len(tests)} W3 SMOKEEXE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
