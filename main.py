"""Unified entrypoint for desktop and Android builds.

Buildozer/python-for-android expects a top-level ``main.py`` in the app source
directory. This launcher keeps desktop and Android entrypoints in sync.
"""

from __future__ import annotations

import os


def _run_android() -> None:
    from android.main import Kiro2AndroidApp

    Kiro2AndroidApp().run()


def _run_desktop() -> None:
    from game import main as game_main

    game_main()


if __name__ == "__main__":
    if "ANDROID_ARGUMENT" in os.environ or os.environ.get("KIVY_BUILD") == "1":
        _run_android()
    else:
        _run_desktop()

