"""Cue table and hooks for the sounds of the newer systems.

A cue is a sound name from the synth registry in tools/synth_sfx.py, played as
assets/audio/sfx_<name>.wav. CUE_SPECS holds the volume, pitch jitter and min_gap
each cue plays with, so a call site is one line:

    audio_cues.cue(game.audio, "drone_fire")

Repeated cues (drone fire, hums, warnings) rely on min_gap, so a burst cannot fill
AudioManager's max_voices budget. A missing audio manager, an unknown name or a
driver problem is a silent no-op: sound never reaches the game loop.

Event each cue marks:
    ricochet         a bullet bounces off a wall or an obstacle
    homing_lock      a homing shot locks onto its target
    time_slow_on     time slow starts (the time_slow pickup, see POWERUP_CUES)
    time_slow_off    time slow ends
    magnet           the magnet pickup is collected (see POWERUP_CUES)
    drone_spawn      a support drone appears
    drone_fire       a support drone fires
    event_warn       an arena event is announced
    meteor_impact    a meteor lands
    flare_sweep      a flare sweeps across the arena
    nebula_hum       a nebula event starts
    toast            a toast notification appears
    achievement      an achievement is earned
    daily_record     a daily-run record is set
    reflect          a shot is turned back by a reflector elite
    split            a splitter elite divides on death (see ELITE_DEATH_CUES)
    rage_warn        a boss enters rage
    victory_fanfare  a victory is reached
    skin_select      a ship skin is selected
    mutator_toggle   a mutator is switched on or off
    hangar_move      the hangar cursor moves to another ship
"""

# name -> (volume, pitch_jitter, min_gap). Volume is relative to the SFX setting.
CUE_SPECS = {
    "ricochet": (0.55, 0.06, 0.05),
    "homing_lock": (0.55, 0.00, 0.25),
    "time_slow_on": (0.80, 0.00, 0.50),
    "time_slow_off": (0.70, 0.00, 0.50),
    "magnet": (0.60, 0.00, 0.30),
    "drone_spawn": (0.60, 0.03, 0.50),
    "drone_fire": (0.40, 0.05, 0.12),
    "event_warn": (0.80, 0.00, 1.00),
    "meteor_impact": (0.80, 0.05, 0.40),
    "flare_sweep": (0.55, 0.00, 0.80),
    "nebula_hum": (0.40, 0.00, 6.00),
    "toast": (0.50, 0.00, 0.25),
    "achievement": (0.80, 0.00, 0.50),
    "daily_record": (0.80, 0.00, 1.00),
    "reflect": (0.55, 0.06, 0.08),
    "split": (0.60, 0.06, 0.30),
    "rage_warn": (0.80, 0.00, 2.00),
    "victory_fanfare": (0.85, 0.00, 2.00),
    "skin_select": (0.50, 0.00, 0.10),
    "mutator_toggle": (0.50, 0.00, 0.08),
    "hangar_move": (0.40, 0.00, 0.06),
}

# Power-up kinds that have a sound of their own. Every other kind keeps the pickup pair.
POWERUP_CUES = {
    "magnet": "magnet",
    "time_slow": "time_slow_on",
}

# Elite affix -> cue played when that elite dies.
ELITE_DEATH_CUES = {
    "splitter": "split",
}


def cue(audio, name: str, scale: float = 1.0) -> None:
    """Play a named cue with its table volume, pitch jitter and min_gap. Never raises."""
    spec = CUE_SPECS.get(name)
    if audio is None or spec is None:
        return
    volume, jitter, gap = spec
    try:
        audio.play(name, volume=volume * float(scale), pitch_jitter=jitter, min_gap=gap)
    except Exception:
        pass


def play_pickup(audio, kind: str, rare: bool) -> None:
    """Power-up pickup sound: the kind's own cue if it has one, else the usual pickup pair."""
    name = POWERUP_CUES.get(kind)
    if name is not None:
        cue(audio, name)
        return
    try:
        audio.play("pickup_rare" if rare else "pickup", volume=0.7, pitch_jitter=0.03)
    except Exception:
        pass


def play_elite_death(audio, enemy) -> None:
    """Cue for an elite whose affix has one, played when it dies. Other enemies are silent here."""
    name = ELITE_DEATH_CUES.get(getattr(enemy, "elite_affix", ""))
    if name is not None:
        cue(audio, name)
