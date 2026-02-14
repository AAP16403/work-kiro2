# Git Push to APK Guide

## 1) One-time setup

1. Create a GitHub repository and push this project.
2. Confirm workflow file exists: `.github/workflows/android-apk.yml`.
3. Confirm Android spec exists: `android/buildozer.spec`.

## 2) Standard flow (push and auto-build APK)

1. Commit your changes:
```bash
git add .
git commit -m "Update game and android build"
```
2. Push to GitHub:
```bash
git push origin <branch>
```
3. Wait for workflow `Build Android APK` to finish in GitHub Actions.
4. Download artifact `kiro2-apk-debug` from the workflow run.

## 3) Online build in GitHub Actions (manual)

1. Open GitHub repository.
2. Go to `Actions`.
3. Select `Build Android APK`.
4. Click `Run workflow`.
5. Choose `build_mode`:
   - `debug` for testing
   - `release` for release packaging
6. Download artifact `kiro2-apk-<mode>` when finished.
7. If build fails, download `kiro2-android-logs` artifact and inspect logs.

## 4) Online build from git push (automatic)

This workflow auto-runs on push when you change:
- `android/**`
- `*.py` at repo root
- `.github/workflows/android-apk.yml`

Steps:
1. Commit and push.
2. Open `Actions` tab.
3. Open the latest `Build Android APK` run.
4. Download `kiro2-apk-debug` artifact.

## 5) Local build option (WSL/Windows)

1. Debug build:
```bat
android\build_apk.bat
```
2. Release build:
```bat
android\build_apk.bat release
```
3. Clean then build:
```bat
android\build_apk.bat debug 1
```

## 6) No hard-coded path overrides

Use environment variables instead of editing scripts:

1. Buildozer venv path:
```bash
export KIRO2_BUILDOZER_VENV=.venv_buildozer
```
2. Buildozer build directory:
```bash
export KIRO2_BUILDOZER_BUILD_DIR=/your/custom/builddir
```
3. WSL temporary symlink root (Windows cmd/powershell env):
```powershell
$env:KIRO2_WSL_LINK_ROOT="/tmp/your_repo_link_$env:USERNAME"
```

## 7) Clean rebuild when APK behaves stale

1. Remove previous app from device:
```bash
adb uninstall org.example.kiro2
```
2. Rebuild from clean:
```bat
android\build_apk.bat debug 1
```
3. Reinstall generated APK from `android/bin`.

## 8) Quick troubleshooting

1. WSL not available:
```bat
android\build_apk.bat installwsl
```
2. WSL broken:
```bat
android\build_apk.bat fixwsl
android\build_apk.bat updatewsl
android\build_apk.bat repairlxss
```
3. Build log location:
`android/_logs/*.log`
