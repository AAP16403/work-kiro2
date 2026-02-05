# Isometric Room Survival - Game Structure

## Project Organization

The game code is now organized into separate, modular files for better maintainability and clarity.

### Core Files:

#### **config.py**
- All game configuration constants
- Screen dimensions (SCREEN_W, SCREEN_H, FPS)
- Game balance values (PLAYER_SPEED, PLAYER_HP, PLAYER_DAMAGE, etc.)
- Colors for UI and environment
- Isometric projection settings (ISO_SCALE_X, ISO_SCALE_Y)

#### **utils.py**
- `Vec2` class - 2D vector math with operations
- Isometric conversion functions: `to_iso()`, `iso_to_world()`
- Helper functions: `clamp_to_room()`, `random_spawn_edge()`, `dist()`

#### **player.py**
- `Player` dataclass with stats and controls
- Player attributes: position, HP, speed, damage, fire_rate

#### **enemy.py**
- `Enemy` dataclass with behavior types
- `update_enemy()` function for AI behavior
- Three enemy types: "chaser", "ranged", "charger"

#### **projectile.py**
- `Projectile` dataclass for bullets
- Attributes: position, velocity, damage, TTL, owner

#### **powerup.py**
- `PowerUp` dataclass for collectible items
- `apply_powerup()` function to apply effects to player
- Types: "heal", "damage", "speed", "firerate"

#### **level.py**
- `GameState` dataclass - central game state
- `spawn_wave()` - creates enemy waves with increasing difficulty
- `maybe_spawn_powerup()` - random powerup spawning

#### **map.py**
- `Room` class - manages the game map
- Isometric floor rendering with grid
- Handles background and environment visuals
- Fixed: Uses `thickness` instead of deprecated `width` parameter

#### **visuals.py**
- `GroupCache` class - manages rendering depth sorting
- `RenderHandle` class - manages visual objects
- `Visuals` class - complete rendering system
  - Player sprite creation and updates
  - Enemy sprite management (color-coded by type)
  - Projectile rendering
  - PowerUp visual effects with symbols

#### **Untitled-1.py** (Main Game)
- `Game` class inheriting from `pyglet.window.Window`
- Game loop and event handling
- Input processing (keyboard, mouse)
- Collision detection
- Game state updates
- Rendering coordination
- Entry point: `main()` function

## Running the Game

```bash
python Untitled-1.py
```

## Build a Windows executable (.exe)

Use PyInstaller to bundle the game into a distributable Windows build.

1) Create a venv (once):

```powershell
py -m venv .venv
```

2) Install dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -U pip pyglet pyinstaller
```

3) Build:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

Or run the one-step script:

```bat
build_all.bat
```

Output:
- Folder: `.\dist\Kiro2Game\`
- Executable: `.\dist\Kiro2Game\Kiro2Game.exe`

## Controls

- **WASD** or **Arrow Keys** - Move around the room
- **Hold Left Mouse Button** - Shoot at enemies

## Game Features

- **Isometric Perspective** - Depth-sorted rendering
- **Wave-Based Combat** - Difficulty increases per wave
- **Three Enemy Types**:
  - Chaser (red) - rushes the player
  - Ranged (blue) - keeps distance and fires
  - Charger (orange) - charges in bursts
- **Four PowerUp Types**:
  - Heal (green +) - restores 25 HP
  - Damage (red !) - increases attack power
  - Speed (blue >) - increases movement speed
  - Fire Rate (yellow *) - faster shooting

## Dependencies

- pyglet 2.1.13+ (for rendering and windowing)

## Error Fixes Applied

1. **Changed `OrderedGroup` import** - Updated to use `Group` from `pyglet.graphics`
2. **Fixed `Line.thickness` parameter** - Changed from deprecated `width` to `thickness`
3. **Resolved circular imports** - Used TYPE_CHECKING for forward references
