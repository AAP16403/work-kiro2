"""Test the menu system imports."""

import sys

print("Testing menu system imports...")

try:
    from menu import Menu, SettingsMenu, MenuButton
    print("OK: menu.py imported successfully")
except Exception as e:
    print(f"FAIL: menu.py import failed: {e}")
    sys.exit(1)

try:
    from config import SCREEN_W, SCREEN_H
    menu = Menu(SCREEN_W, SCREEN_H)
    settings = SettingsMenu(SCREEN_W, SCREEN_H, lambda x: None)
    print("OK: Menu and SettingsMenu instantiated successfully")
except Exception as e:
    print(f"FAIL: Menu instantiation failed: {e}")
    sys.exit(1)

print("\nOK: Menu system ready!")
