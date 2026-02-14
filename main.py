"""Unified entrypoint for desktop and Android builds.

Buildozer/python-for-android expects a top-level ``main.py`` in the app source
directory. This launcher keeps desktop and Android entrypoints in sync.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import traceback


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
    repo_root = os.path.dirname(os.path.abspath(__file__))
    android_dir = os.path.join(repo_root, "android")
    for p in (android_dir, repo_root):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)

    candidates = (
        os.path.join(repo_root, "android_main.py"),
        os.path.join(android_dir, "main.py"),
    )
    existing = [p for p in candidates if os.path.isfile(p)]
    if not existing:
        raise FileNotFoundError(
            "Android entrypoint not found. Tried: "
            + ", ".join(candidates)
        )

    errors: list[str] = []
    for android_main_path in existing:
        try:
            spec = importlib.util.spec_from_file_location("kiro2_android_main", android_main_path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Unable to load Android entrypoint: {android_main_path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.Kiro2AndroidApp().run()
            return
        except Exception:
            errors.append(
                f"\n--- failed candidate: {android_main_path} ---\n"
                + traceback.format_exc()
            )

    raise RuntimeError(
        "All Android entrypoints failed."
        + "".join(errors)
    )


def _run_desktop() -> None:
    from game import main as game_main

    game_main()


if __name__ == "__main__":
    if _is_android_runtime():
        _run_android()
    else:
        _run_desktop()
