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
    next_shot_time: float = 0.0
    recoil: float = 0.0
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
    # Boost / Overdrive system (LSHIFT)
    boost_energy: float = 100.0
    boost_max_energy: float = 100.0
    is_boosting: bool = False
    infinite_boost_until: float = 0.0
    boost_recharge_rate: float = 22.0
    boost_drain_rate: float = 28.0
    crit_chance_bonus: float = 0.0
    crit_mult_bonus: float = 0.0
    damage_flash_timer: float = 0.0


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


def update_boost(
    player: Player,
    dt: float,
    boost_requested: bool,
    current_time: float,
    has_infinite: bool = False,
) -> bool:
    """Update player boost state and energy. Returns whether player is actively boosting."""
    is_inf = has_infinite or (current_time < getattr(player, "infinite_boost_until", 0.0))
    drain = float(getattr(player, "boost_drain_rate", 28.0))
    recharge = float(getattr(player, "boost_recharge_rate", 22.0))
    max_energy = float(getattr(player, "boost_max_energy", 100.0))

    # Hysteresis: sustained boost can drain down to 0; starting boost requires >= 12 energy
    can_start = is_inf or (player.boost_energy >= 12.0)
    can_sustain = is_inf or (player.boost_energy > 0.0)

    if boost_requested and ((player.is_boosting and can_sustain) or (not player.is_boosting and can_start)):
        player.is_boosting = True
        if not is_inf:
            player.boost_energy = max(0.0, player.boost_energy - drain * dt)
            if player.boost_energy <= 0.0:
                player.is_boosting = False
    else:
        player.is_boosting = False
        if player.boost_energy < max_energy:
            player.boost_energy = min(max_energy, player.boost_energy + recharge * dt)

    return player.is_boosting


def format_boost_hud(player: Player, current_time: float, has_infinite: bool = False) -> str:
    """Return a short HUD string for boost status."""
    is_inf = has_infinite or (current_time < getattr(player, "infinite_boost_until", 0.0))
    if is_inf:
        left = max(0.0, getattr(player, "infinite_boost_until", 0.0) - current_time)
        return f"BOOST [INF {left:.0f}s]" if left > 0 else "BOOST [INF]"
    if player.is_boosting:
        return f"BOOSTING {int(player.boost_energy)}%"
    return f"Boost {int(player.boost_energy)}%"


