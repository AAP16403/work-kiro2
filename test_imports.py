"""Quick test to verify all imports and basic functionality."""

import sys
print("Testing imports...")

try:
    from config import SCREEN_W, SCREEN_H, FPS, ROOM_RADIUS
    print("✓ config.py")
except Exception as e:
    print(f"✗ config.py: {e}")
    sys.exit(1)

try:
    from utils import Vec2, to_iso
    print("✓ utils.py")
except Exception as e:
    print(f"✗ utils.py: {e}")
    sys.exit(1)

try:
    from player import Player
    p = Player(pos=Vec2(0, 0))
    print("✓ player.py")
except Exception as e:
    print(f"✗ player.py: {e}")
    sys.exit(1)

try:
    from enemy import update_enemy
    print("✓ enemy.py")
except Exception as e:
    print(f"✗ enemy.py: {e}")
    sys.exit(1)

try:
    from projectile import Projectile
    print("✓ projectile.py")
except Exception as e:
    print(f"✗ projectile.py: {e}")
    sys.exit(1)

try:
    from powerup import apply_powerup
    print("✓ powerup.py")
except Exception as e:
    print(f"✗ powerup.py: {e}")
    sys.exit(1)

try:
    from level import GameState, spawn_wave
    print("✓ level.py")
except Exception as e:
    print(f"✗ level.py: {e}")
    sys.exit(1)

try:
    from map import Room
    print("✓ map.py")
except Exception as e:
    print(f"✗ map.py: {e}")
    sys.exit(1)

try:
    from weapons import get_weapon_for_wave, spawn_weapon_projectiles, WEAPONS
    w = get_weapon_for_wave(1)
    print(f"✓ weapons.py - Got weapon: {w.name}")
except Exception as e:
    print(f"✗ weapons.py: {e}")
    sys.exit(1)

try:
    from particles import ParticleSystem, Particle
    print("✓ particles.py")
except Exception as e:
    print(f"✗ particles.py: {e}")
    sys.exit(1)

print("\n✓ All imports successful!")
print("\nTesting weapon system:")
for wave in [1, 2, 3, 4, 5, 6, 7, 8]:
    weapon = get_weapon_for_wave(wave)
    print(f"  Wave {wave}: {weapon.name} (dmg={weapon.damage}, rate={weapon.fire_rate})")

print("\nTesting projectile spawning:")
player_pos = Vec2(0, 0)
aim_dir = Vec2(1, 0).normalized()
weapon = get_weapon_for_wave(5)
projectiles = spawn_weapon_projectiles(player_pos, aim_dir, weapon, 0.0, 10)
print(f"  Spawned {len(projectiles)} projectile(s) with {weapon.name}")

print("\n✓ All tests passed!")
