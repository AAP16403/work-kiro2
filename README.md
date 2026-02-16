# PLOUTO (Stellar Survival)

Fast-paced isometric wave survival built with `pyglet`.

## Current Highlights

- Fullscreen startup and scaled modern menus
- Enemy squad coordination and role-based formation behavior
- Boss waves every 5 waves, with rebalanced boss patterns
- Ultra system (right-click) with variant cycling and spawn pity rules
- Boss reward RPG flow:
  - 3 temporary card choices (2-3 waves)
  - then 3 permanent run-boost choices

## Run (Dev)

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip pyglet pyinstaller
.\.venv\Scripts\python.exe main.py
```

Or:

```powershell
py main.py
```

## Controls

- `WASD` / Arrow keys: move
- Hold `LMB`: fire
- `RMB`: Ultra (needs Ultra charge)
- `Q`: Ultra (keyboard shortcut)
- `ESC`: pause/menu

## Boss Rewards (RPG)

After each boss kill:

1. Pick one **Temporary Card** (lasts 2-3 waves)
2. Pick one **Permanent Run Boost** (lasts until run ends)

Temporary effects auto-expire by wave count. Permanent effects stack for the current run only.

## Build Windows EXE

Use one-step build:

```bat
build_all.bat
```

What it does:

1. Ensures `.venv` exists
2. Installs/updates `pip`, `pyglet`, `pyinstaller`
3. Runs syntax validation
4. Builds with PyInstaller (`kiro2_game.spec`)
5. Creates `dist\Plouto.zip`

Outputs:

- Folder: `dist\Plouto\`
- EXE: `dist\Plouto\Plouto.exe`
- ZIP: `dist\Plouto.zip`

## Important Files

- `main.py`: entry point
- `game.py`: game loop, FSM states, RPG reward integration
- `rpg.py`: boss reward menu and card selection UI
- `enemy.py`: enemy AI and boss behavior logic
- `level.py`: wave/boss spawn rules, powerup spawn logic
- `menu.py`: main/settings/pause/game-over menus
- `kiro2_game.spec`: PyInstaller config
- `build_all.bat`: full build script
