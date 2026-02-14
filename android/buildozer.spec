[app]
# App identity
title = Kiro2
package.name = kiro2
package.domain = org.example
version = 0.1.0

# Project layout:
# - ../main.py is the launcher
# - ../android/main.py is Android runtime implementation
source.dir = ..
source.include_exts = py,kv,png,jpg,jpeg,ico,ttf,txt,md,json,atlas,wav,mp3,ogg
source.exclude_dirs = .git,.venv,build,dist,__pycache__,android/.buildozer,android/.venv_buildozer,android/bin
source.exclude_patterns = **/__pycache__/*,**/*.pyc,**/*.pyo,android/_logs/*,android/_artifacts/*,android/_wsl_backups/*,Untitled-1.py

# Runtime deps
requirements = python3,kivy==2.2.1

# Display
orientation = landscape
fullscreen = 1

# Android target
android.permissions = VIBRATE
android.api = 33
android.minapi = 24
android.archs = arm64-v8a

# python-for-android
p4a.branch = v2024.01.21

[buildozer]
# Use a Linux path without spaces when building in WSL/Linux.
build_dir = /tmp/kiro2_buildozer
