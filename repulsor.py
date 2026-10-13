"""Repulsor: a pickup that fires an instant shockwave from the player, then cools down.

Picking one up on a ready Repulsor fires it on the next frame. The shockwave pushes every enemy bullet
within REPULSOR_RANGE outward, removes the ones slower than REPULSOR_CLEAR_SPEED, and stuns every enemy in
that range for REPULSOR_STUN_SECONDS. A shot starts a REPULSOR_COOLDOWN_SECONDS cooldown.

A pickup during the cooldown never fires early. It stores one charge, up to REPULSOR_MAX_CHARGES, and each
stored charge fires when the cooldown ends, one per cooldown.

State lives on the player as ``player.repulsor_state``, created by the first pickup. The shockwave reads and
writes the run lists it is given (``s.projectiles``, ``s.enemies``), so it never touches the simulation outside
its range. A stunned enemy keeps its stun in ``enemy.stun_until`` (run clock). The caller skips an enemy's
update while ``is_stunned`` is true.

Visuals go through the particle system's pooled ring and dust, so no new draw path is needed. With reduced
motion the ring holds its full size instead of growing, and the dust puff is not drawn.
"""

import math
from dataclasses import dataclass

import config
import motion
from utils import Vec2


@dataclass
class RepulsorState:
    """Per-player Repulsor state. The shockwave fires when ``fire_pending`` is set or a charge is due."""
    cooldown_until: float = 0.0  # run-clock time the current cooldown ends
    charges: int = 0             # pickups stored during a cooldown; each one fires when the cooldown ends
    fire_pending: bool = False   # a pickup on a ready Repulsor: fires on the next update()


def state_of(player) -> RepulsorState:
    """The player's Repulsor state, created on first use."""
    st = getattr(player, "repulsor_state", None)
    if st is None:
        st = RepulsorState()
        player.repulsor_state = st
    return st


def pickup(player, now: float) -> None:
    """A Repulsor pickup. On a ready Repulsor it fires next frame; otherwise it stores one charge, up to the cap."""
    st = state_of(player)
    now = float(now)
    if now >= st.cooldown_until and not st.fire_pending:
        st.fire_pending = True
        st.cooldown_until = now + float(config.REPULSOR_COOLDOWN_SECONDS)
    else:
        st.charges = min(int(config.REPULSOR_MAX_CHARGES), st.charges + 1)


def update(player, s, now: float, particles=None) -> int:
    """Once per frame. Fires the pending shockwave, or a stored charge when the cooldown has ended.

    Returns 1 when a shockwave fired this frame, else 0. Idle frames for a player who never picked one up
    allocate nothing.
    """
    st = getattr(player, "repulsor_state", None)
    if st is None:
        return 0
    now = float(now)
    if st.fire_pending:
        st.fire_pending = False
        fire(player, s, now, particles)
        return 1
    if st.charges > 0 and now >= st.cooldown_until:
        st.charges -= 1
        st.cooldown_until = now + float(config.REPULSOR_COOLDOWN_SECONDS)
        fire(player, s, now, particles)
        return 1
    return 0


def fire(player, s, now: float, particles=None) -> tuple[int, int, int]:
    """Fire one shockwave now. Returns (enemy bullets removed, enemy bullets kept in range, enemies stunned).

    Every enemy bullet kept in range leaves the player at least REPULSOR_PUSH_SPEED outward, so the count is the
    number the shockwave pushed. Player shots are never touched. ``s.projectiles`` is edited in place.
    """
    origin = player.pos
    reach = float(config.REPULSOR_RANGE)
    r2 = reach * reach
    clear = float(config.REPULSOR_CLEAR_SPEED)
    push = float(config.REPULSOR_PUSH_SPEED)
    stun_until = float(now) + float(config.REPULSOR_STUN_SECONDS)
    reduced = motion.reduced()

    removed = pushed = 0
    kept = []
    for p in s.projectiles:
        if p.owner != "enemy" or _dist_sq(p.pos, origin) > r2:
            kept.append(p)
            continue
        if p.vel.length() < clear:
            removed += 1
            continue
        # Outward radial speed of at least `push`. A shot already moving away fast keeps its own velocity.
        dx = p.pos.x - origin.x
        dy = p.pos.y - origin.y
        d = math.sqrt(dx * dx + dy * dy)
        if d > 1e-6:
            rx, ry = dx / d, dy / d
        else:
            rx, ry = 1.0, 0.0
        radial = p.vel.x * rx + p.vel.y * ry
        if radial < push:
            add = push - radial
            p.vel = Vec2(p.vel.x + rx * add, p.vel.y + ry * add)
        pushed += 1
        kept.append(p)
    if removed or pushed:
        s.projectiles[:] = kept

    stunned = 0
    for e in s.enemies:
        if e.hp <= 0 or getattr(e, "_is_dead", False):
            continue
        if _dist_sq(e.pos, origin) > r2:
            continue
        e.stun_until = max(float(getattr(e, "stun_until", 0.0)), stun_until)
        e.vel = Vec2(0.0, 0.0)
        stunned += 1
        if particles is not None and not reduced:
            particles.emit(
                e.pos, config.REPULSOR_COLOR, count=int(config.REPULSOR_DUST_COUNT),
                speed=float(config.REPULSOR_DUST_SPEED), life=float(config.REPULSOR_DUST_SECONDS), size=2.0,
            )

    if particles is not None:
        particles.add_ground_ring(
            origin, config.REPULSOR_COLOR, reach, float(config.REPULSOR_RING_SECONDS), grow=not reduced,
        )
    return removed, pushed, stunned


def is_stunned(enemy, now: float) -> bool:
    """True while an enemy is stunned at run time ``now``. Stunned enemies do not move or act."""
    return float(now) < float(getattr(enemy, "stun_until", 0.0))


def hud_text(player, now: float) -> str:
    """Status-line text for the cooldown, e.g. 'Repulsor 7s' or 'Repulsor 7s x2'. Empty when ready with no charge."""
    st = getattr(player, "repulsor_state", None)
    if st is None:
        return ""
    left = float(st.cooldown_until) - float(now)
    text = f"Repulsor {math.ceil(left)}s" if left > 0.0 else "Repulsor"
    if st.charges > 0:
        text += f" x{st.charges}"
    elif left <= 0.0:
        return ""
    return text


def _dist_sq(a: Vec2, b: Vec2) -> float:
    dx = a.x - b.x
    dy = a.y - b.y
    return dx * dx + dy * dy
