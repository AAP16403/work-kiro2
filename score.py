"""Score tracking, combo system, and high-score persistence."""

import json
import os
import time as _time

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

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def on_enemy_kill(self, behavior: str) -> int:
        """Record an enemy kill.  Returns points awarded."""
        base = KILL_POINTS.get(behavior, 100)
        points = int(base * self.combo)
        self.score += points
        self.kills += 1

        # Build combo
        self.combo = min(COMBO_MAX, self.combo + COMBO_INCREMENT)
        self.best_combo = max(self.best_combo, self.combo)
        self._combo_timer = 0.0
        return points

    def on_wave_clear(self, wave: int) -> int:
        """Award wave-clear bonus.  Returns bonus points."""
        is_boss = wave % 5 == 0
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
    def load_high_scores() -> dict[str, list[dict]]:
        """Load high scores from disk.  Returns {difficulty: [{score, wave, date}, ...]}."""
        try:
            with open(HIGH_SCORE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        return {}

    @staticmethod
    def save_high_scores(data: dict[str, list[dict]]) -> None:
        """Persist high scores to disk."""
        try:
            with open(HIGH_SCORE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def submit_score(self, wave: int) -> bool:
        """Submit the current run score.  Returns True if it's a new high score."""
        data = self.load_high_scores()
        entries = data.get(self.difficulty, [])

        entry = {
            "score": self.score,
            "wave": wave,
            "kills": self.kills,
            "best_combo": round(self.best_combo, 2),
            "date": _time.strftime("%Y-%m-%d %H:%M"),
        }
        entries.append(entry)
        entries.sort(key=lambda e: e["score"], reverse=True)
        entries = entries[:MAX_HIGH_SCORES]
        data[self.difficulty] = entries
        self.save_high_scores(data)

        # New high score if this entry is #1
        return entries[0]["score"] == self.score

    def get_high_score(self) -> int:
        """Return the current top high score for this difficulty."""
        data = self.load_high_scores()
        entries = data.get(self.difficulty, [])
        if entries:
            return int(entries[0].get("score", 0))
        return 0
