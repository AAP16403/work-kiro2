"""Thin launcher for the game.

The full game implementation lives in `game.py`. This file stays as the stable
entrypoint for running locally and for the existing PyInstaller spec.
"""

from game import main


if __name__ == "__main__":
    main()
a