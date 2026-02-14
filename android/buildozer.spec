[app]
title = Kiro2
package.name = kiro2
package.domain = org.example
version = 0.1

# Point Buildozer at repo root (must contain a top-level main.py).
source.dir = ..
source.include_exts = py,md,txt,png,jpg,jpeg,ico
source.exclude_dirs = .git,.venv,build,dist,__pycache__

requirements = python3,kivy==2.2.1
orientation = landscape
fullscreen = 1

android.permissions = VIBRATE
android.api = 33
android.minapi = 24

# Helps keep APK size down (optional; remove if you hit device-specific issues)
android.archs = arm64-v8a

# Pin python-for-android to a stable release (master can break unexpectedly).
p4a.branch = v2024.01.21

# Buildozer/SDK defaults are fine for a debug build.

[buildozer]
# Keep p4a/build cache in a path without spaces (required when repo path has spaces).
build_dir = /tmp/kiro2_buildozer
