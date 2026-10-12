"""Score tracking, combo system, and high-score persistence."""

import os
import time as _time

import config
from savefile import (
    HIGH_SCORES_VERSION,
    board_entries,
    load_versioned,
    migrate_high_scores,
    save_versioned,
)

# ---------------------------------------------------------------------------
# Point values per enemy type (base, before combo multiplier)
# ---------------------------------------------------------------------------
KILL_POINTS: dict[str, int] = {
    "chaser": 100,
    "ranged": 150,
    "swarm": 60,
    "charger": 175,
    "tank": 250,
    "spitter": 175,
    "flyer": 150,
    "engineer": 200,
    "bomber": 200,
    # Bosses
    "boss_thunder": 2000,
    "boss_laser": 2000,
    "boss_trapmaster": 2500,
    "boss_swarmqueen": 2500,
    "boss_brute": 2200,
    "boss_abyss_gaze": 3000,
    "boss_womb_core": 3000,
}

WAVE_CLEAR_BASE = 500
WAVE_CLEAR_PER_WAVE = 150
BOSS_WAVE_BONUS = 3000

# Combo constants
COMBO_DECAY_DELAY = 2.0        # seconds of no kills before combo starts decaying
COMBO_DECAY_RATE = 1.0         # combo lost per second during decay
COMBO_INCREMENT = 0.25         # combo added per kill
COMBO_MAX = 8.0                # max combo multiplier

HIGH_SCORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "high_scores.json")
MAX_HIGH_SCORES = 5


class ScoreTracker:
    """Tracks score, combo multiplier, and high scores for a single run."""

    def __init__(self, difficulty: str = "normal"):
        self.score: int = 0
        self.combo: float = 1.0
        self._combo_timer: float = 0.0  # time since last kill
        self.difficulty: str = difficulty
        self.kills: int = 0
        self.best_combo: float = 1.0
        # Set by submit_score: 1-based board position (0 = off the board) and the
        # points still needed to pass the entry directly above (None if #1 or off-board).
        self.last_rank: int = 0
        self.last_points_to_next: int | None = None

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def on_enemy_kill(self, behavior: str, multiplier: float = 1.0) -> int:
        """Record an enemy kill.  Returns points awarded."""
        base = KILL_POINTS.get(behavior, 100)
        points = int(base * self.combo * multiplier)
        self.score += points
        self.kills += 1

        # Build combo
        self.combo = min(COMBO_MAX, self.combo + COMBO_INCREMENT)
        self.best_combo = max(self.best_combo, self.combo)
        self._combo_timer = 0.0
        return points

    def on_wave_clear(self, wave: int) -> int:
        """Award wave-clear bonus.  Returns bonus points."""
        is_boss = wave % config.BOSS_WAVE_EVERY == 0
        bonus = WAVE_CLEAR_BASE + wave * WAVE_CLEAR_PER_WAVE
        if is_boss:
            bonus += BOSS_WAVE_BONUS
        bonus = int(bonus * self.combo)
        self.score += bonus
        return bonus

    def on_player_hit(self) -> None:
        """Reset combo on player damage."""
        self.combo = 1.0
        self._combo_timer = 0.0

    # ------------------------------------------------------------------
    # Per-frame update (combo decay)
    # ------------------------------------------------------------------

    def update(self, dt: float) -> None:
        self._combo_timer += dt
        if self._combo_timer >= COMBO_DECAY_DELAY and self.combo > 1.0:
            self.combo = max(1.0, self.combo - COMBO_DECAY_RATE * dt)

    # ------------------------------------------------------------------
    # High-score persistence
    # ------------------------------------------------------------------

    @staticmethod
    def load_high_scores() -> dict:
        """Load high scores from disk.  Returns {difficulty: [{score, wave, date}, ...], "version": N}.

        Never raises: a missing file reads as an empty board, and a corrupt file is renamed to
        high_scores.json.corrupt-<n> and reads as an empty board.
        """
        return load_versioned(HIGH_SCORE_FILE, HIGH_SCORES_VERSION, migrate_high_scores, dict)

    @staticmethod
    def save_high_scores(data: dict) -> None:
        """Persist high scores to disk atomically. A failed write leaves the previous file in place."""
        save_versioned(HIGH_SCORE_FILE, data, HIGH_SCORES_VERSION)

    def submit_score(self, wave: int) -> bool:
        """Submit the current run score and place it on the board.

        Returns True only for a strict new best.  A run that merely ties the current
        top score (including a 0-point first run) is not a new high score.  Also sets
        ``last_rank`` and ``last_points_to_next`` for the Game Over screen.
        """
        data = self.load_high_scores()
        entries = board_entries(data, self.difficulty)
        prev_best = max((int(e.get("score", 0)) for e in entries), default=0)

        entry = {
            "score": self.score,
            "wave": wave,
            "kills": self.kills,
            "best_combo": round(self.best_combo, 2),
            "date": _time.strftime("%Y-%m-%d %H:%M"),
        }
        entries.append(entry)
        # Stable sort: an equal score lands below the older entry, so a tie never takes #1.
        entries.sort(key=lambda e: e["score"], reverse=True)
        entries = entries[:MAX_HIGH_SCORES]
        data[self.difficulty] = entries
        self.save_high_scores(data)

        # Locate this run by identity (equal scores compare equal, so value lookup is ambiguous).
        self.last_rank = 0
        self.last_points_to_next = None
        for index, e in enumerate(entries):
            if e is entry:
                self.last_rank = index + 1
                break
        if self.last_rank > 1:
            above_score = int(entries[self.last_rank - 2]["score"])
            # +1 so a tie reads as one point to beat the entry above.
            self.last_points_to_next = above_score - self.score + 1

        return self.score > prev_best

    def get_high_score(self) -> int:
        """Return the current top high score for this difficulty."""
        data = self.load_high_scores()
        entries = board_entries(data, self.difficulty)
        if entries:
            return int(entries[0].get("score", 0))
        return 0
