[app]
title = Kiro2
package.name = kiro2
package.domain = org.example
version = 0.1.0

source.dir = ..
source.include_exts = py,kv,png,jpg,jpeg,ico,ttf,txt,md,json,atlas,wav,mp3,ogg
source.exclude_dirs = .git,.venv,build,dist,__pycache__,android/.buildozer,android/.venv_buildozer,android/bin
source.exclude_patterns = **/__pycache__/*,**/*.pyc,**/*.pyo,android/_logs/*,android/_artifacts/*,android/_wsl_backups/*,Untitled-1.py

requirements = python3,kivy==2.2.1

orientation = landscape
fullscreen = 1

android.permissions = VIBRATE
android.api = 33
android.minapi = 24
android.archs = arm64-v8a

p4a.branch = v2024.01.21

[buildozer]
