[app]
title = Kiro2
package.name = kiro2
package.domain = org.example

# Point Buildozer at the repo root, but run this entrypoint.
source.dir = ..
source.include_exts = py,md,txt,png,jpg,jpeg,ico
source.exclude_dirs = .git,.venv,build,dist,__pycache__
entrypoint = android/main.py

requirements = python3,kivy
orientation = landscape
fullscreen = 1

android.permissions = VIBRATE
android.api = 33
android.minapi = 24

# Helps keep APK size down (optional; remove if you hit device-specific issues)
android.arch = arm64-v8a

# Buildozer/SDK defaults are fine for a debug build.
