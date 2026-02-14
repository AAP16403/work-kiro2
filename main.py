"""Unified entrypoint for desktop and Android builds.

Buildozer/python-for-android expects a top-level ``main.py`` in the app source
directory. This launcher keeps desktop and Android entrypoints in sync.
"""

from __future__ import annotations

import os
import sys


def _is_android_runtime() -> bool:
    if sys.platform == "android":
        return True
    android_markers = (
        "ANDROID_ARGUMENT",
        "ANDROID_PRIVATE",
        "P4A_BOOTSTRAP",
        "KIVY_BUILD",
    )
    return any(os.environ.get(k) for k in android_markers)


def _run_android() -> None:
    from android.main import Kiro2AndroidApp

    Kiro2AndroidApp().run()


def _run_desktop() -> None:
    from game import main as game_main

    game_main()


if __name__ == "__main__":
    if _is_android_runtime():
        _run_android()
    else:
        _run_desktop()
