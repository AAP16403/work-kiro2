"""Player entity and related functionality."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from config import PLAYER_HP, PLAYER_SPEED, PLAYER_DAMAGE, PLAYER_FIRE_RATE
from utils import Vec2

if TYPE_CHECKING:
    from weapons import Weapon
    from logic import BalanceLogic


@dataclass
class Player:
    """Player entity."""
    pos: Vec2
    max_hp: int = PLAYER_HP
    hp: int = PLAYER_HP
    shield: int = 0
    speed: float = PLAYER_SPEED
    damage: int = PLAYER_DAMAGE
    fire_rate: float = PLAYER_FIRE_RATE
    last_shot: float = 0.0
    laser_until: float = 0.0
    vortex_until: float = 0.0
    vortex_radius: float = 70.0
    vortex_dps: float = 38.0
    ultra_charges: int = 0
    ultra_cd_until: float = 0.0
    ultra_variant_idx: int = 0
    current_weapon: "Weapon" = field(default=None)  # Will be set in Game.__init__
    is_dashing: bool = False
    dash_timer: float = 0.0
    dash_cooldown: float = 0.0
    dash_direction: Vec2 = field(default_factory=lambda: Vec2(0, 0))
    dash_speed: float = 800.0
    dash_charges: int = 1
    dash_max_charges: int = 1
    invincibility_timer: float = 0.0


# ---------------------------------------------------------------------------
# Dash helpers
# ---------------------------------------------------------------------------


def compute_dash_cd(balance: "BalanceLogic", diff_mod: float, perm_mod: float) -> float:
    """Return the effective dash cooldown in seconds."""
    return float(balance.dash_cooldown) * float(diff_mod) * float(perm_mod)


def perform_dash(
    player: Player,
    time: float,
    balance: "BalanceLogic",
    diff_mod: float,
    perm_mod: float,
    input_dir: Vec2,
    mouse_world: Vec2,
) -> bool:
    """Try to execute a dash. Returns True if a dash was performed."""
    if player.dash_charges <= 0 or player.is_dashing:
        return False

    player.is_dashing = True
    player.dash_timer = 0.15
    player.dash_charges = max(0, player.dash_charges - 1)

    # Start recharge timer only if this was the first charge consumed
    if player.dash_charges == player.dash_max_charges - 1:
        player.dash_cooldown = time + compute_dash_cd(balance, diff_mod, perm_mod)

    player.invincibility_timer = 0.15

    if input_dir.length() > 0:
        player.dash_direction = input_dir.normalized()
    else:
        player.dash_direction = (mouse_world - player.pos).normalized()

    return True


def recharge_dash(
    player: Player,
    time: float,
    balance: "BalanceLogic",
    diff_mod: float,
    perm_mod: float,
) -> None:
    """Tick dash charge recharging. Call once per update frame."""
    if player.dash_charges >= player.dash_max_charges:
        return
    if time < player.dash_cooldown:
        return

    player.dash_charges = min(player.dash_max_charges, player.dash_charges + 1)

    # If still below max, start the next recharge timer
    if player.dash_charges < player.dash_max_charges:
        player.dash_cooldown = time + compute_dash_cd(balance, diff_mod, perm_mod)


def format_dash_hud(player: Player, current_time: float) -> str:
    """Return a short HUD string for dash status, or '' when nothing to show."""
    charges = int(player.dash_charges)
    max_ch = int(player.dash_max_charges)
    cd_left = max(0.0, float(player.dash_cooldown) - current_time)

    if charges < max_ch and cd_left > 0:
        return f"Dash {charges}/{max_ch} {cd_left:.1f}s"
    if max_ch > 1:
        return f"Dash {charges}/{max_ch}"
    return ""

