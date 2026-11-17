"""Arena events: telegraphed set-piece hazards on non-boss waves.

Three events exist: Meteor Shower, Solar Flare and Nebula Cloud. Each one warns before it
deals damage. Damage reuses the existing hazard paths. Meteor impacts are Trap objects that
states.py already arms, ticks and clears. The flare beam is a LaserBeam that states.py draws
and removes. The nebula only changes enemy shields.

Schedules and layouts come from the run seed through per-wave RNGs. They never advance the
run's main RNG, so gameplay random draws are the same with or without an event.
"""

import math
import random
from dataclasses import dataclass, field

import audio_cues
import config
from hazards import LaserBeam, Trap
from utils import Vec2, dist_sq

EVENT_METEOR = "meteor_shower"
EVENT_FLARE = "solar_flare"
EVENT_NEBULA = "nebula_cloud"

FLARE_BEAM_COLOR = (255, 190, 90)
_METEOR_MIN_GAP = 90.0  # minimum spacing between meteor impact zones (world units)


@dataclass(frozen=True)
class EventSpec:
    id: str
    name: str
    description: str
    warn: float  # telegraph time before the event first does anything dangerous


EVENTS: list[EventSpec] = [
    EventSpec(
        EVENT_METEOR, "Meteor Shower",
        f"Three impact zones are marked {float(config.EVENT_METEOR_WARN):g} s ahead. Each one deals area damage.",
        float(config.EVENT_METEOR_WARN),
    ),
    EventSpec(
        EVENT_FLARE, "Solar Flare",
        f"A rotating beam sweeps a sector after a {float(config.EVENT_FLARE_WARN):g} s warning.",
        float(config.EVENT_FLARE_WARN),
    ),
    EventSpec(
        EVENT_NEBULA, "Nebula Cloud",
        f"For {float(config.EVENT_NEBULA_TTL):g} s, enemies near the cloud gain shield. The cloud stays visible.",
        float(config.EVENT_NEBULA_WARN),
    ),
]
_SPEC_BY_ID = {spec.id: spec for spec in EVENTS}


@dataclass
class _Impact:
    pos: Vec2
    mark_t: float
    trap: Trap | None = None


@dataclass
class ArenaEvent:
    """One running event. Lives on GameState.arena_event until it ends or the wave clears."""

    kind: str
    total: float  # seconds from the wave start until the event is over
    t: float = 0.0
    impacts: list[_Impact] = field(default_factory=list)  # meteor zones
    center: Vec2 = field(default_factory=lambda: Vec2(0.0, 0.0))  # nebula centre
    reach: float = 0.0  # flare beam length
    angle_start: float = 0.0
    angle_mid: float = 0.0
    angle_end: float = 0.0
    beam: LaserBeam | None = None  # flare beam, owned by GameState.lasers while the event runs
    hit_cd: float = 0.0  # flare: time until the beam can hit the player again
    fired: bool = False  # flare: the beam has gone live (one-shot flash)

    @property
    def spec(self) -> EventSpec:
        return _SPEC_BY_ID[self.kind]


def reduce_motion() -> bool:
    """True when Reduce Motion is on. Sweeps and cloud pulses stop, warnings and damage stay."""
    return bool(getattr(config, "REDUCE_MOTION", False))


def _rng(seed: int, wave: int, salt: str) -> random.Random:
    # String seeds are hashed with SHA-512, so these streams do not depend on PYTHONHASHSEED.
    return random.Random(f"arena-events:{int(seed)}:{int(wave)}:{salt}")


def schedule_for_wave(seed: int, wave: int) -> str | None:
    """Event id for this wave of a run with this seed, or None.

    Waves before EVENT_MIN_WAVE and boss waves (every fifth wave) never get one. Each other
    wave gets an event with probability EVENT_WAVE_CHANCE, and the event is chosen evenly.
    """
    wave = int(wave)
    if wave < int(config.EVENT_MIN_WAVE) or wave % 5 == 0:
        return None
    rng = _rng(seed, wave, "schedule")
    if rng.random() >= float(config.EVENT_WAVE_CHANCE):
        return None
    return EVENTS[rng.randrange(len(EVENTS))].id


def _sample_point(rng: random.Random, taken: list[Vec2], min_gap: float, reach: float) -> Vec2:
    """Uniform point in a disc of radius ``reach``, kept at least ``min_gap`` from ``taken`` when possible."""
    point = Vec2(0.0, 0.0)
    for _ in range(12):
        ang = rng.uniform(0.0, math.tau)
        rad = reach * math.sqrt(rng.random())
        point = Vec2(math.cos(ang) * rad, math.sin(ang) * rad)
        if all(dist_sq(point, q) >= min_gap * min_gap for q in taken):
            break
    return point


def _plan_meteor(rng: random.Random) -> ArenaEvent:
    warn = float(config.EVENT_METEOR_WARN)
    stagger = float(config.EVENT_METEOR_STAGGER)
    reach = float(config.ROOM_RADIUS) * 0.7
    impacts: list[_Impact] = []
    taken: list[Vec2] = []
    for i in range(max(1, int(config.EVENT_METEOR_IMPACTS))):
        pos = _sample_point(rng, taken, _METEOR_MIN_GAP, reach)
        taken.append(pos)
        impacts.append(_Impact(pos=pos, mark_t=i * stagger))
    total = impacts[-1].mark_t + warn + float(config.EVENT_METEOR_LIVE)
    return ArenaEvent(kind=EVENT_METEOR, total=total, impacts=impacts)


def _plan_flare(rng: random.Random) -> ArenaEvent:
    mid = rng.uniform(0.0, math.tau)
    half = math.radians(float(config.EVENT_FLARE_SECTOR_DEG)) * 0.5
    start, end = mid - half, mid + half
    if rng.random() < 0.5:
        start, end = end, start  # the sweep runs either way round
    reach = float(config.ROOM_RADIUS)
    warn = float(config.EVENT_FLARE_WARN)
    sweep = float(config.EVENT_FLARE_SWEEP)
    beam = LaserBeam(
        start=Vec2(0.0, 0.0),
        end=Vec2(math.cos(start) * reach, math.sin(start) * reach),
        damage=0,  # damage is applied by _update_flare, not by the generic laser loop
        thickness=float(config.EVENT_FLARE_THICKNESS),
        ttl=sweep,
        warn=warn,
        color=FLARE_BEAM_COLOR,
        owner="event",
    )
    return ArenaEvent(
        kind=EVENT_FLARE, total=warn + sweep, reach=reach,
        angle_start=start, angle_mid=mid, angle_end=end, beam=beam,
    )


def _plan_nebula(rng: random.Random) -> ArenaEvent:
    center = _sample_point(rng, [], 0.0, float(config.ROOM_RADIUS) * 0.5)
    total = float(config.EVENT_NEBULA_WARN) + float(config.EVENT_NEBULA_TTL)
    return ArenaEvent(kind=EVENT_NEBULA, total=total, center=center)


def plan_event(kind: str, seed: int, wave: int) -> ArenaEvent:
    """Build the layout of one event. The same kind, seed and wave always give the same layout."""
    rng = _rng(seed, wave, "layout")
    if kind == EVENT_METEOR:
        return _plan_meteor(rng)
    if kind == EVENT_FLARE:
        return _plan_flare(rng)
    if kind == EVENT_NEBULA:
        return _plan_nebula(rng)
    raise ValueError(f"unknown arena event: {kind!r}")


def begin_wave_event(state, game=None) -> ArenaEvent | None:
    """Roll and start this wave's event. Call once, right after spawn_wave."""
    end_wave_event(state, game)
    kind = schedule_for_wave(state.seed, state.wave)
    if kind is None:
        return None
    ev = plan_event(kind, state.seed, state.wave)
    if ev.beam is not None:
        state.lasers.append(ev.beam)
    state.arena_event = ev
    # Announce the event: the warning sound for every event, and the hum when a nebula starts.
    audio = getattr(game, "audio", None)
    audio_cues.cue(audio, "event_warn")
    if kind == EVENT_NEBULA:
        audio_cues.cue(audio, "nebula_hum")
    return ev


def update_arena_event(state, game, dt: float) -> None:
    ev = getattr(state, "arena_event", None)
    if ev is None:
        return
    ev.t += dt
    if ev.kind == EVENT_METEOR:
        _update_meteor(ev, state)
    elif ev.kind == EVENT_FLARE:
        _update_flare(ev, game, dt)
    elif ev.kind == EVENT_NEBULA:
        _update_nebula(ev, state)
    if ev.t >= ev.total:
        end_wave_event(state, game)


def end_wave_event(state, game=None) -> None:
    """Stop the running event and remove everything it put into the state. Safe to call when none runs."""
    ev = getattr(state, "arena_event", None)
    if ev is None:
        return
    state.arena_event = None
    visuals = getattr(game, "visuals", None)
    for imp in ev.impacts:
        if imp.trap is not None and _remove_identity(state.traps, imp.trap) and visuals is not None:
            visuals.drop_trap(imp.trap)
    if ev.beam is not None and _remove_identity(state.lasers, ev.beam) and visuals is not None:
        visuals.drop_laser(ev.beam)
    for e in state.enemies:
        if getattr(e, "_nebula_base", None) is not None:
            _release_nebula_shield(e)
    if visuals is not None:
        visuals.drop_arena_event(ev)


def _remove_identity(items: list, obj) -> bool:
    for i, item in enumerate(items):
        if item is obj:
            del items[i]
            return True
    return False


def _update_meteor(ev: ArenaEvent, state) -> None:
    warn = float(config.EVENT_METEOR_WARN)
    live = warn + float(config.EVENT_METEOR_LIVE)
    for imp in ev.impacts:
        if imp.trap is None and ev.t >= imp.mark_t:
            # The trap arms at its own t == armed_delay, which is the impact moment, and it hits
            # only while it is alive. states.py ticks it, applies the damage and removes it.
            imp.trap = Trap(
                pos=imp.pos,
                radius=float(config.EVENT_METEOR_RADIUS),
                damage=int(config.EVENT_METEOR_DAMAGE),
                ttl=live,
                armed_delay=warn,
                kind="meteor",
            )
            state.traps.append(imp.trap)


def _update_flare(ev: ArenaEvent, game, dt: float) -> None:
    warn = float(config.EVENT_FLARE_WARN)
    sweep = float(config.EVENT_FLARE_SWEEP)
    beam = ev.beam
    if reduce_motion():
        angle = ev.angle_mid
    elif ev.t < warn:
        angle = ev.angle_start
    else:
        frac = min(1.0, (ev.t - warn) / sweep)
        angle = ev.angle_start + (ev.angle_end - ev.angle_start) * frac
    # Move the existing endpoint in place. The beam is read every frame by visuals.sync_laser.
    beam.end.x = math.cos(angle) * ev.reach
    beam.end.y = math.sin(angle) * ev.reach
    if ev.t < warn or ev.t >= ev.total:
        return  # no damage during the warning, and none on the frame the sweep has finished
    if not ev.fired:
        ev.fired = True
        audio_cues.cue(getattr(game, "audio", None), "flare_sweep")
        particles = getattr(game, "particle_system", None)
        if particles is not None:
            particles.add_laser_beam(beam.start, beam.end, color=beam.color)
    ev.hit_cd = max(0.0, ev.hit_cd - dt)
    if ev.hit_cd > 0.0:
        return
    player_radius = float(game._player_radius())
    hit_r = float(config.EVENT_FLARE_THICKNESS) * 0.6 + player_radius * 0.35
    p = game.player.pos
    if segment_dist_sq(p.x, p.y, beam.start.x, beam.start.y, beam.end.x, beam.end.y) <= hit_r * hit_r:
        ev.hit_cd = float(config.EVENT_FLARE_TICK)
        game._damage_player(int(config.EVENT_FLARE_DAMAGE))


def segment_dist_sq(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Squared distance from point (px, py) to segment a-b, on plain floats so the per-frame path allocates nothing."""
    abx, aby = bx - ax, by - ay
    denom = abx * abx + aby * aby
    t = 0.0 if denom <= 0.0 else max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / denom))
    dx = ax + abx * t - px
    dy = ay + aby * t - py
    return dx * dx + dy * dy


def _update_nebula(ev: ArenaEvent, state) -> None:
    if ev.t < float(config.EVENT_NEBULA_WARN):
        return
    r2 = float(config.EVENT_NEBULA_RADIUS) ** 2
    shield = int(config.EVENT_NEBULA_SHIELD)
    for e in state.enemies:
        base = getattr(e, "_nebula_base", None)
        inside = dist_sq(e.pos, ev.center) <= r2
        if inside and base is None:
            e._nebula_base = int(e.shield)
            e.shield = max(int(e.shield), shield)
        elif base is not None and not inside:
            _release_nebula_shield(e)


def _release_nebula_shield(e) -> None:
    """Take back the shield the cloud added, keeping anything the enemy already had."""
    base = int(e._nebula_base)
    e.shield = min(int(e.shield), base)
    e._nebula_base = None


def event_banner_suffix(state) -> str:
    """Text appended to the wave banner subtitle when this wave has an event."""
    ev = getattr(state, "arena_event", None)
    if ev is None:
        return ""
    return f"  -  {ev.spec.name.upper()}"


def event_status_text(state) -> str:
    """Short status-line text: event name and seconds left. Empty when no event runs."""
    ev = getattr(state, "arena_event", None)
    if ev is None:
        return ""
    left = max(0.0, ev.total - ev.t)
    return f"{ev.spec.name.upper()} {left:.0f}s"
