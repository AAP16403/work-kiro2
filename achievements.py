"""Achievements and per-run statistics.

Public API:

    ACHIEVEMENTS                   tuple of Achievement(id, name, description, check), about 20 of them
    get(achievement_id) -> Achievement | None
    name_of(achievement_id) -> str   display name, or the id itself when unknown
    evaluate(run_stats, progress) -> list[str]
        Checks every achievement that is not yet in progress["achievements"]. Each one whose
        condition holds is appended to that list, and its id is returned. Ids come back in
        catalogue order and never repeat across calls.
    RunStats
        Counters for one run. The game updates it through on_kill, on_player_hit,
        on_wave_clear and finish, then reads it with to_dict().

``run_stats`` may be a RunStats or the dict from RunStats.to_dict(). ``progress`` is the dict
from progress.load(). Conditions read lifetime totals (total_kills, bosses_defeated, ...) from
progress, so progress.end_run merges a run into the totals before it calls evaluate.

Importing this module does no I/O.
"""

from dataclasses import dataclass
from typing import Callable

from score import COMBO_MAX


@dataclass(frozen=True)
class Achievement:
    """One achievement. ``check(run, progress)`` returns True once the condition holds."""

    id: str
    name: str
    description: str
    check: Callable[[dict, dict], bool]


def _run(key: str, at_least: float) -> Callable[[dict, dict], bool]:
    """Condition: a per-run statistic reaches ``at_least``."""
    return lambda run, progress: float(run.get(key, 0)) >= float(at_least)


def _total(key: str, at_least: float) -> Callable[[dict, dict], bool]:
    """Condition: a lifetime total in progress reaches ``at_least``."""
    return lambda run, progress: float(progress.get(key, 0)) >= float(at_least)


ACHIEVEMENTS: tuple[Achievement, ...] = (
    Achievement("first_blood", "First Blood", "Destroy your first enemy in a run.", _run("kills", 1)),
    Achievement("massacre", "Massacre", "Destroy 50 enemies in one run.", _run("kills", 50)),
    Achievement("giant_slayer", "Giant Slayer", "Defeat a boss in a single run.", _run("boss_kills", 1)),
    Achievement("boss_hunter", "Boss Hunter", "Defeat 3 bosses across all runs.", _total("bosses_defeated", 3)),
    Achievement("bossbreaker", "Bossbreaker", "Defeat 15 bosses across all runs.", _total("bosses_defeated", 15)),
    Achievement("no_damage_wave", "Untouchable", "Clear a wave without taking a hit.", _run("perfect_waves", 1)),
    Achievement("flawless_five", "Flawless Five", "Clear 5 waves untouched in one run.", _run("perfect_waves", 5)),
    Achievement("elite_slayer", "Elite Slayer", "Destroy 5 elite enemies in one run.", _run("elite_kills", 5)),
    Achievement("combo_6x", "Combo x6", "Reach a 6x kill combo.", _run("best_combo", 6.0)),
    Achievement("combo_max", "Maxed Out", "Reach the top kill combo.", _run("best_combo", float(COMBO_MAX))),
    Achievement("survive_ten_waves", "Survivor", "Survive ten waves in one run.", _run("waves_cleared", 10)),
    Achievement("into_the_deep", "Into the Deep", "Reach wave 10.", _run("wave", 10)),
    Achievement("deep_space", "Deep Space", "Reach wave 20.", _run("wave", 20)),
    Achievement("edge_of_stars", "Edge of the Stars", "Reach wave 30.", _run("wave", 30)),
    Achievement("marathon", "Marathon", "Survive five minutes in one run.", _run("survived_s", 300.0)),
    Achievement("five_digits", "Five Digits", "Score 10,000 in one run.", _run("score", 10000)),
    Achievement("stellar_score", "Stellar Score", "Score 50,000 in one run.", _run("score", 50000)),
    Achievement("centurion", "Centurion", "Destroy 100 enemies across all runs.", _total("total_kills", 100)),
    Achievement("exterminator", "Exterminator", "Destroy 1,000 enemies across all runs.", _total("total_kills", 1000)),
    Achievement("veteran", "Veteran", "Play 10 runs.", _total("runs_played", 10)),
)

_BY_ID = {a.id: a for a in ACHIEVEMENTS}


def get(achievement_id) -> Achievement | None:
    """Return the achievement with this id, or None."""
    return _BY_ID.get(achievement_id) if isinstance(achievement_id, str) else None


def name_of(achievement_id) -> str:
    """Display name for an achievement id. Unknown ids come back unchanged."""
    found = get(achievement_id)
    return found.name if found is not None else str(achievement_id)


def evaluate(run_stats, progress: dict) -> list[str]:
    """Mark every newly earned achievement in ``progress`` and return their ids.

    Already-earned achievements are skipped, so calling this twice with the same run
    returns an empty list the second time.
    """
    run = run_stats.to_dict() if hasattr(run_stats, "to_dict") else dict(run_stats)
    earned = progress.setdefault("achievements", [])
    new_ids: list[str] = []
    for ach in ACHIEVEMENTS:
        if ach.id in earned:
            continue
        if ach.check(run, progress):
            earned.append(ach.id)
            new_ids.append(ach.id)
    return new_ids


class RunStats:
    """Counters for one run.

    Hooks: states.PlayingState._kill_enemy calls on_kill, game.Game._damage_player calls
    on_player_hit, the wave-clear block in states.PlayingState.update calls on_wave_clear,
    and game.Game._finish_meta_run calls finish once when the run ends.
    """

    def __init__(self) -> None:
        self.kills = 0
        self.elite_kills = 0
        self.boss_kills = 0
        self.hits_taken = 0          # every hit that reached the player, shield-absorbed ones included
        self.damage_taken = 0        # post-multiplier damage of those hits, before shields
        self.waves_cleared = 0
        self.perfect_waves = 0       # waves cleared with no hit since the previous clear
        self.best_combo = 1.0
        self.wave = 0                # wave reached, set by finish()
        self.score = 0               # set by finish()
        self.survived_s = 0.0        # set by finish()
        self.finished = False
        self._hits_at_last_clear = 0

    def on_kill(self, *, elite: bool = False, boss: bool = False, combo: float = 1.0) -> None:
        """Count one enemy kill. ``combo`` is the combo multiplier after this kill."""
        self.kills += 1
        if elite:
            self.elite_kills += 1
        if boss:
            self.boss_kills += 1
        self.best_combo = max(self.best_combo, float(combo))

    def on_player_hit(self, amount: int = 1) -> None:
        """Count one hit that landed on the player."""
        self.hits_taken += 1
        self.damage_taken += max(0, int(amount))

    def on_wave_clear(self, wave: int) -> None:
        """Count a cleared wave. It is perfect when nothing hit the player since the previous clear."""
        self.waves_cleared += 1
        if self.hits_taken == self._hits_at_last_clear:
            self.perfect_waves += 1
        self._hits_at_last_clear = self.hits_taken

    def finish(self, *, score: int, wave: int, survived: float, best_combo: float | None = None) -> None:
        """Record the end-of-run values. Only the first call has any effect."""
        if self.finished:
            return
        self.finished = True
        self.score = int(score)
        self.wave = int(wave)
        self.survived_s = float(survived)
        if best_combo is not None:
            self.best_combo = max(self.best_combo, float(best_combo))

    def to_dict(self) -> dict:
        """Plain-dict snapshot, the form evaluate() and progress.end_run read."""
        return {
            "kills": self.kills,
            "elite_kills": self.elite_kills,
            "boss_kills": self.boss_kills,
            "hits_taken": self.hits_taken,
            "damage_taken": self.damage_taken,
            "waves_cleared": self.waves_cleared,
            "perfect_waves": self.perfect_waves,
            "best_combo": self.best_combo,
            "wave": self.wave,
            "score": self.score,
            "survived_s": self.survived_s,
        }
