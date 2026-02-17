"""Centralized gameplay balance tuning logic."""

from __future__ import annotations

from dataclasses import dataclass, field
import random


@dataclass
class BalanceLogic:
    """Single source of truth for gameplay tuning values."""

    fps: float = 60.0

    # Simulation pacing
    frame_dt_cap: float = 0.25
    max_catchup_steps: int = 6
    sim_dt_cap: float = 1.0 / 30.0

    # Hitboxes
    player_radius: float = 14.0
    boss_radius: float = 24.0
    default_enemy_radius: float = 12.0
    enemy_radii: dict[str, float] = field(
        default_factory=lambda: {
            "tank": 16.0,
            "swarm": 9.0,
            "flyer": 11.0,
            "engineer": 13.0,
            "charger": 13.0,
            "spitter": 12.0,
            "ranged": 12.0,
            "chaser": 12.0,
        }
    )
    projectile_radii: dict[str, float] = field(
        default_factory=lambda: {
            "bomb": 10.0,
            "missile": 7.0,
            "plasma": 5.5,
            "spread": 4.8,
            "bullet": 4.5,
        }
    )

    # Damage interactions
    enemy_contact_damage: int = 10
    tank_death_blast_radius: float = 70.0
    tank_death_blast_damage: int = 15
    bomb_blast_radius: float = 72.0
    bomb_blast_min_damage: int = 10

    # Pickups
    magnet_radius_normal: float = 150.0
    magnet_radius_special: float = 190.0
    pickup_radius_normal: float = 16.0
    pickup_radius_special: float = 20.0
    pickup_pull_base_speed: float = 220.0
    pickup_pull_nearby_gain: float = 2.0

    # Dash
    dash_cooldown: float = 1.5

    @property
    def fixed_dt(self) -> float:
        return 1.0 / max(1.0, float(self.fps))

    def enemy_radius(self, behavior_name: str) -> float:
        b = str(behavior_name or "")
        if b.startswith("boss_"):
            return self.boss_radius
        return float(self.enemy_radii.get(b, self.default_enemy_radius))

    def projectile_radius(self, projectile_type: str) -> float:
        return float(self.projectile_radii.get(str(projectile_type or "bullet"), self.projectile_radii["bullet"]))

    def bomb_blast_damage(self, projectile_damage: int) -> int:
        return max(int(self.bomb_blast_min_damage), int(projectile_damage))

    def pickup_magnet_radius(self, powerup_kind: str, magnet_bonus: float) -> float:
        is_special = str(powerup_kind) in ("weapon", "ultra")
        base = self.magnet_radius_special if is_special else self.magnet_radius_normal
        return base + float(magnet_bonus)

    def pickup_radius(self, powerup_kind: str) -> float:
        is_special = str(powerup_kind) in ("weapon", "ultra")
        return self.pickup_radius_special if is_special else self.pickup_radius_normal

    def pickup_pull_speed(self, magnet_radius: float, distance_to_player: float) -> float:
        return self.pickup_pull_base_speed + (float(magnet_radius) - float(distance_to_player)) * self.pickup_pull_nearby_gain


@dataclass(frozen=True)
class EnemyClass:
    """Defines an enemy class/group that can appear in wave compositions."""

    key: str
    members: tuple[str, ...]
    unlock_wave: int
    weight: float


@dataclass
class EnemySpawnPlan:
    """Resolved plan for a wave spawn composition."""

    total_count: int
    behavior_counts: dict[str, int]
    combo_value: int
    combo_text: str


class EnemySpawnLogic:
    """Enemy composition planner with grouped classes and combo scoring."""

    def __init__(self) -> None:
        self.enemy_classes: tuple[EnemyClass, ...] = (
            EnemyClass("frontline", ("chaser", "charger"), unlock_wave=1, weight=3.0),
            EnemyClass("gunline", ("ranged",), unlock_wave=1, weight=2.2),
            EnemyClass("explosive", ("bomber",), unlock_wave=2, weight=1.6),
            EnemyClass("swarmers", ("swarm",), unlock_wave=3, weight=1.7),
            EnemyClass("control", ("engineer",), unlock_wave=4, weight=1.2),
            EnemyClass("bruisers", ("tank",), unlock_wave=5, weight=1.0),
            EnemyClass("pressure", ("spitter", "flyer"), unlock_wave=7, weight=1.3),
        )
        self.member_weights: dict[str, float] = {
            "chaser": 1.0,
            "charger": 0.9,
            "ranged": 1.0,
            "bomber": 1.0,
            "swarm": 1.0,
            "engineer": 1.0,
            "tank": 1.0,
            "spitter": 1.0,
            "flyer": 0.8,
        }
        self.threat_value: dict[str, int] = {
            "chaser": 1,
            "ranged": 2,
            "charger": 2,
            "bomber": 2,
            "swarm": 1,
            "engineer": 3,
            "tank": 4,
            "spitter": 3,
            "flyer": 3,
            "boss_thunder": 20,
            "boss_laser": 20,
            "boss_trapmaster": 22,
            "boss_swarmqueen": 22,
            "boss_brute": 24,
            "boss_abyss_gaze": 28,
            "boss_womb_core": 30,
        }
        # Prevent wave plans from collapsing into a single class too often.
        self.max_class_share: float = 0.6

    @staticmethod
    def _spawn_mod(difficulty: str) -> float:
        d = str(difficulty or "normal").lower()
        if d == "easy":
            return 0.85
        if d == "hard":
            return 1.12
        return 1.0

    def _base_count(self, wave: int, difficulty: str, cap: int) -> int:
        wave_i = max(1, int(wave))
        cap_i = max(1, int(cap))
        base = 4 + int(wave_i * 1.4)
        scaled = int(base * self._spawn_mod(difficulty))
        return max(1, min(cap_i, max(1, scaled)))

    def _active_classes(self, wave: int) -> list[EnemyClass]:
        return [c for c in self.enemy_classes if int(wave) >= int(c.unlock_wave)]

    @staticmethod
    def _unique_classes_target(wave: int, active_count: int) -> int:
        target = 1 + min(2, max(0, (int(wave) - 1) // 3))
        return max(1, min(active_count, target))

    def _pick_member(self, enemy_class: EnemyClass) -> str:
        names = list(enemy_class.members)
        weights = [max(0.05, self.member_weights.get(n, 1.0)) for n in names]
        return random.choices(names, weights=weights, k=1)[0]

    def plan_wave(self, wave: int, difficulty: str, cap: int) -> EnemySpawnPlan:
        total = self._base_count(wave, difficulty, cap)
        active = self._active_classes(wave)
        if not active:
            active = [EnemyClass("fallback", ("chaser",), unlock_wave=1, weight=1.0)]

        uniq_target = self._unique_classes_target(wave, len(active))
        selected: list[EnemyClass] = []
        pool = list(active)
        while pool and len(selected) < uniq_target:
            cls_weights = [max(0.1, c.weight) for c in pool]
            picked = random.choices(pool, weights=cls_weights, k=1)[0]
            selected.append(picked)
            pool.remove(picked)
        if not selected:
            selected = [active[0]]

        counts_by_class = {c.key: 1 for c in selected}
        remaining = max(0, total - len(selected))
        max_per_class = max(1, int(round(total * self.max_class_share)))
        for _ in range(remaining):
            selectable = [c for c in selected if counts_by_class.get(c.key, 0) < max_per_class]
            if not selectable:
                selectable = selected
            pick = random.choices(selectable, weights=[max(0.1, c.weight) for c in selectable], k=1)[0]
            counts_by_class[pick.key] += 1

        class_by_key = {c.key: c for c in selected}
        behavior_counts: dict[str, int] = {}
        for class_key, count in counts_by_class.items():
            cls = class_by_key[class_key]
            for _ in range(count):
                b = self._pick_member(cls)
                behavior_counts[b] = behavior_counts.get(b, 0) + 1

        combo_value = sum(self.threat_value.get(b, 1) * n for b, n in behavior_counts.items())
        parts = [f"{b[:3].upper()}x{n}" for b, n in sorted(behavior_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:4]]
        combo_text = " ".join(parts)
        return EnemySpawnPlan(
            total_count=total,
            behavior_counts=behavior_counts,
            combo_value=int(combo_value),
            combo_text=combo_text,
        )

    def boss_combo_value(self, boss_behavior: str) -> int:
        return int(self.threat_value.get(str(boss_behavior or ""), 20))


@dataclass(frozen=True)
class EnemyStatProfile:
    """Base stat scaling profile by behavior."""

    hp_offset: float = 0.0
    hp_mult: float = 1.0
    speed_mult: float = 1.0
    attack_mult: float = 1.0
    boss_base_hp: float | None = None
    boss_wave_hp_gain: float | None = None


class EnemyTuningLogic:
    """Centralized tuning for difficulty, boss rotation, and enemy stat formulas."""

    def __init__(self) -> None:
        self.difficulty_modifiers: dict[str, dict[str, float]] = {
            "easy": {"spawn": 0.85, "hp": 0.88, "speed": 0.92, "powerup": 1.15, "boss_hp": 0.92, "dash_cd": 0.9},
            "normal": {"spawn": 1.0, "hp": 1.0, "speed": 1.0, "powerup": 1.0, "boss_hp": 1.0, "dash_cd": 1.0},
            "hard": {"spawn": 1.12, "hp": 1.16, "speed": 1.08, "powerup": 0.9, "boss_hp": 1.08, "dash_cd": 1.12},
        }
        self.enemy_profiles: dict[str, EnemyStatProfile] = {
            "chaser": EnemyStatProfile(hp_offset=0.0, hp_mult=1.0, speed_mult=1.32, attack_mult=1.0),
            "bomber": EnemyStatProfile(hp_offset=-8.0, hp_mult=1.0, speed_mult=1.2, attack_mult=1.0),
            "ranged": EnemyStatProfile(hp_offset=-5.0, hp_mult=1.0, speed_mult=0.85, attack_mult=1.2),
            "charger": EnemyStatProfile(hp_offset=10.0, hp_mult=1.0, speed_mult=1.05, attack_mult=0.8),
            "swarm": EnemyStatProfile(hp_offset=0.0, hp_mult=0.5, speed_mult=1.45, attack_mult=0.5),
            "tank": EnemyStatProfile(hp_offset=0.0, hp_mult=2.0, speed_mult=0.55, attack_mult=0.9),
            "spitter": EnemyStatProfile(hp_offset=-3.0, hp_mult=1.0, speed_mult=0.9, attack_mult=1.5),
            "flyer": EnemyStatProfile(hp_offset=-7.0, hp_mult=1.0, speed_mult=1.55, attack_mult=0.7),
            "engineer": EnemyStatProfile(hp_offset=6.0, hp_mult=1.0, speed_mult=0.75, attack_mult=1.1),
            "boss_thunder": EnemyStatProfile(speed_mult=0.9, attack_mult=1.8, boss_base_hp=150.0, boss_wave_hp_gain=32.0),
            "boss_laser": EnemyStatProfile(speed_mult=1.1, attack_mult=1.8, boss_base_hp=135.0, boss_wave_hp_gain=28.0),
            "boss_trapmaster": EnemyStatProfile(speed_mult=0.85, attack_mult=1.7, boss_base_hp=170.0, boss_wave_hp_gain=30.0),
            "boss_swarmqueen": EnemyStatProfile(speed_mult=0.95, attack_mult=1.7, boss_base_hp=155.0, boss_wave_hp_gain=26.0),
            "boss_brute": EnemyStatProfile(speed_mult=1.05, attack_mult=1.9, boss_base_hp=190.0, boss_wave_hp_gain=34.0),
            "boss_abyss_gaze": EnemyStatProfile(speed_mult=1.0, attack_mult=2.05, boss_base_hp=210.0, boss_wave_hp_gain=32.0),
            "boss_womb_core": EnemyStatProfile(speed_mult=0.9, attack_mult=2.15, boss_base_hp=240.0, boss_wave_hp_gain=36.0),
        }
        self.spawn_attack_cd_ranges: dict[str, tuple[float, float]] = {
            "default": (0.2, 1.0),
            "engineer": (0.6, 1.4),
            "boss": (0.6, 1.6),
        }
        self.boss_intro: tuple[str, ...] = (
            "boss_thunder",
            "boss_laser",
            "boss_trapmaster",
            "boss_swarmqueen",
            "boss_brute",
        )
        self.boss_late: tuple[str, ...] = ("boss_abyss_gaze", "boss_womb_core")
        self.boss_legacy_mix_chance: float = 0.28
        self.boss_legacy_pool_start_idx: int = 2
        self.boss_hp_growth_base: float = 1.14
        self.boss_hp_growth_per_wave: float = 0.007
        self.boss_hp_growth_max: float = 1.75

    def difficulty_mods(self, difficulty: str) -> dict[str, float]:
        d = str(difficulty or "normal").lower()
        return dict(self.difficulty_modifiers.get(d, self.difficulty_modifiers["normal"]))

    def get_boss_for_wave(self, wave: int) -> str:
        idx = max(0, int(wave) // 5 - 1)
        if idx < len(self.boss_intro):
            return self.boss_intro[idx]
        if random.random() < float(self.boss_legacy_mix_chance):
            pool = self.boss_intro[self.boss_legacy_pool_start_idx :]
            return random.choice(pool) if pool else self.boss_intro[-1]
        return self.boss_late[(idx - len(self.boss_intro)) % len(self.boss_late)]

    def enemy_stats(self, behavior: str, wave: int, difficulty: str = "normal") -> tuple[int, float, float]:
        mods = self.difficulty_mods(difficulty)
        b = str(behavior or "")
        wave_i = max(1, int(wave))
        profile = self.enemy_profiles.get(b, EnemyStatProfile())

        base_hp = 22.0 + float(wave_i) * 5.0
        base_speed = 55.0 + float(wave_i) * 2.0
        is_boss = b.startswith("boss_")

        if is_boss and profile.boss_base_hp is not None and profile.boss_wave_hp_gain is not None:
            hp = float(profile.boss_base_hp) + float(wave_i) * float(profile.boss_wave_hp_gain)
        elif b == "swarm":
            hp = max(8.0, (base_hp * profile.hp_mult) + profile.hp_offset)
        else:
            hp = (base_hp + profile.hp_offset) * profile.hp_mult

        speed = base_speed * profile.speed_mult
        atk = profile.attack_mult

        hp_mult = mods["boss_hp"] if is_boss else mods["hp"]
        hp *= float(hp_mult)
        if is_boss:
            growth = float(self.boss_hp_growth_base) + float(self.boss_hp_growth_per_wave) * float(wave_i)
            hp *= min(float(self.boss_hp_growth_max), growth)
        hp_int = max(1, int(hp))
        speed_final = float(speed) * float(mods["speed"])
        atk_mult = max(0.5, min(2.5, float(atk)))
        return hp_int, speed_final, atk_mult

    def spawn_attack_cd_range(self, behavior: str) -> tuple[float, float]:
        b = str(behavior or "")
        if b.startswith("boss_"):
            return self.spawn_attack_cd_ranges["boss"]
        return self.spawn_attack_cd_ranges.get(b, self.spawn_attack_cd_ranges["default"])
