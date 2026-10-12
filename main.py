"""Desktop entrypoint."""


if __name__ == "__main__":
    # freeze_support() makes a PyInstaller build's spawned pool workers exit here instead of
    # starting a second game window. It does nothing in a normal run.
    import multiprocessing

    multiprocessing.freeze_support()

    # Imported under the guard on purpose: spawned pool workers re-import this file as
    # __mp_main__ and should not pay for pyglet and the game (see parallel.py).
    from game import main as game_main

    game_main()
