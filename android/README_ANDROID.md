# Android shipping (APK) for this game

This repo’s main game uses **pyglet**, which is great on desktop, but it’s not a drop-in “export to Android” runtime.

What’s included here is an **Android-friendly Kivy entrypoint** (`android/main.py`) that reuses the existing *pure-Python gameplay logic* (`enemy.py`, `level.py`, `weapons.py`, etc.) and provides:
- Touch movement (left side virtual stick)
- Touch aiming (right side virtual stick)
- Auto-shoot while aiming (no fire button)
- ULTRA button (when you have charges)
- Upgrade picks every 3 waves (simple UI)

## About “same visuals as PC”

The desktop version’s rendering/particles/UI are built with **pyglet** (`visuals.py`, `particles.py`, `menu.py`, etc.). Android builds here use **Kivy**, so the gameplay logic stays the same, but the rendering is a Kivy canvas approximation.

If you want the Android build to look *identical* to PC, we’ll need to **re-implement the pyglet visuals/particles/UI in Kivy** (or move both platforms to a shared engine). The current Android port prioritizes portability and shipping an APK.

## Build an APK (recommended: Linux/WSL)

### Option A: One command from Windows

From the repo root:

```bat
android\\build_apk.bat
```

If your WSL distro is Ubuntu/Debian and you want the script to install prerequisites first:

```bat
android\\build_apk.bat setup
```

If you don’t have WSL/Ubuntu installed yet:

```bat
android\\build_apk.bat installwsl
```

If WSL errors while listing/installing distros, try:

```bat
android\\build_apk.bat fixwsl
```

If you need to update WSL:

```bat
android\\build_apk.bat updatewsl
```

If `wsl -l` fails with “BasePath” errors (broken distro registration):

```bat
android\\build_apk.bat repairlxss
```

Or for a release build:

```bat
android\\build_apk.bat release
```

This uses **WSL** to run Buildozer.

### Option C: Build in GitHub Actions (no local WSL needed)

If local WSL is broken or you just want a cloud build:
- Push the repo to GitHub
- Run the workflow: `Build Android APK (Buildozer)`
- Download the `kiro2-apk` artifact (APK)

### Option B: Run directly inside Linux/WSL

1) Install Buildozer prerequisites (Ubuntu/WSL):

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git zip unzip openjdk-17-jdk \
  build-essential autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev \
  libtinfo6 cmake libffi-dev libssl-dev
python3 -m venv android/.venv_buildozer
android/.venv_buildozer/bin/python -m pip install -U pip setuptools wheel
android/.venv_buildozer/bin/python -m pip install -U buildozer cython
```

2) Build:

```bash
cd android
buildozer -v android debug
```

3) Install the APK:
- Output is typically under `android/bin/`
- You can install via `adb install -r <apk>`

## Notes

- The build scripts try to auto-install missing prerequisites on Ubuntu/Debian (`apt-get`) and will prompt for your WSL sudo password if needed.
- The visuals in `android/main.py` are intentionally lightweight (Kivy canvas shapes) so the game stays portable.
- If you want “true shipping” (Play Store, signing, bundles), we can extend the `buildozer.spec` for release builds + signing and add asset packaging.
