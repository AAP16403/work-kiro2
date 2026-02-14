"""Unified entrypoint for desktop and Android builds.

Buildozer/python-for-android expects a top-level ``main.py`` in the app source
directory. This launcher keeps desktop and Android entrypoints in sync.
"""

from __future__ import annotations

import importlib.util
import os
import sys


def _is_android_runtime() -> bool:
    if sys.platform == "android":
        return True
    # Avoid false positives on desktop shells that may export one marker.
    android_argument = os.environ.get("ANDROID_ARGUMENT", "").strip()
    android_private = os.environ.get("ANDROID_PRIVATE", "").strip()
    if not android_argument or not android_private:
        return False
    return android_private.startswith("/data/") or android_argument.startswith("/data/")


def _run_android() -> None:
    repo_root = os.path.dirname(os.path.abspath(__file__))
    for p in (repo_root,):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)

    android_main_path = os.path.join(repo_root, "android", "main.py")
    if not os.path.isfile(android_main_path):
        raise FileNotFoundError(f"Android entrypoint missing: {android_main_path}")
    spec = importlib.util.spec_from_file_location("kiro2_android_main", android_main_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load Android entrypoint: {android_main_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.Kiro2AndroidApp().run()


def _run_desktop() -> None:
    from game import main as game_main

    game_main()


if __name__ == "__main__":
    if _is_android_runtime():
        _run_android()
    else:
        _run_desktop()
