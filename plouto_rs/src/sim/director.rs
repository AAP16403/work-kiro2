use crate::sim::enemy::{AttackDenialReason, Enemy, EnemyRole, EnemySubState};

const MAX_ATTACK_WAIT_SECONDS: f32 = 1.6;
const FORCED_ATTACK_STAGGER_SECONDS: f32 = 0.35;
const REGULAR_SAME_ROLE_STAGGER: f32 = 0.20;
const BOSS_SAME_ROLE_STAGGER: f32 = 0.28;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AttackCategory {
    Melee = 0,
    Ranged = 1,
    Special = 2,
}

pub fn attack_category_for_role(role: EnemyRole) -> AttackCategory {
    match role {
        EnemyRole::Chaser | EnemyRole::Charger | EnemyRole::Flyer | EnemyRole::Swarm => {
            AttackCategory::Melee
        }
        EnemyRole::Ranged | EnemyRole::Sniper | EnemyRole::Spitter | EnemyRole::Tank => {
            AttackCategory::Ranged
        }
        EnemyRole::Bomber | EnemyRole::Engineer | EnemyRole::EggSac | EnemyRole::Boss => {
            AttackCategory::Special
        }
    }
}

/// Persisted attack director timing state (zero `HashMap`, fixed `[f32; 12]` by `EnemyRole::index`).
#[derive(Debug, Clone, PartialEq)]
pub struct AttackDirectorState {
    pub last_start_by_role: [f32; 12],
    pub last_forced_start: f32,
}

impl Default for AttackDirectorState {
    fn default() -> Self {
        Self {
            last_start_by_role: [-1_000.0; 12],
            last_forced_start: -1_000.0,
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct AttackProposal {
    pub enemy_idx: usize,
    pub enemy_id: u64,
    pub spawn_index: i64,
    pub role: EnemyRole,
    pub category: AttackCategory,
    pub weight: u8,
    pub range_ok: bool,
    pub on_screen: bool,
    pub sniper_visible: bool,
    pub denied_t: f32,
    pub attack_range: f32,
    pub dist_to_player: f32,
}

/// Deterministic two-pass threat-aware attack director.
/// Pass 1 collects proposals from ready behaviors without vector-order bias.
/// Pass 2 scores and sorts proposals by `(score desc, spawn_index asc)` and grants slots.
#[derive(Debug, Clone)]
pub struct AttackDirector {
    pub active_weight: u8,
    pub budget: u8,
    pub boss_present: bool,
    active_categories: [bool; 3],
    proposals: Vec<AttackProposal>,
}

impl AttackDirector {
    pub fn new(enemies: &[Enemy], breathing_room_left: f32, skill_coordination: f32) -> Self {
        let mut live_non_boss = 0usize;
        let mut boss_present = false;
        let mut active_weight: u8 = 0;
        let mut active_categories = [false; 3];

        for enemy in enemies.iter().filter(|e| !e.is_dead && e.hp > 0) {
            if enemy.is_boss() {
                boss_present = true;
            } else {
                live_non_boss += 1;
            }
            let w = active_attack_weight(enemy);
            if w > 0 {
                active_weight = active_weight.saturating_add(w);
                let cat = attack_category_for_role(enemy.role);
                active_categories[cat as usize] = true;
            }
        }

        let base_budget: f32 = if boss_present || live_non_boss < 5 {
            2.0
        } else if live_non_boss < 12 {
            4.0
        } else {
            6.0
        };
        let mut budget = (base_budget * skill_coordination).round().max(2.0) as u8;
        if breathing_room_left > 0.0 {
            budget = budget.saturating_sub(1).max(1);
        }

        Self {
            active_weight,
            budget,
            boss_present,
            active_categories,
            proposals: Vec::with_capacity(16),
        }
    }

    pub fn propose(&mut self, proposal: AttackProposal) {
        self.proposals.push(proposal);
    }

    pub fn resolve(
        &mut self,
        enemies: &mut [Enemy],
        dir_state: &mut AttackDirectorState,
        enemy_time: f32,
        enemy_dt: f32,
        _breathing_room_left: f32,
        _coordination: f32,
    ) {
        if self.proposals.is_empty() {
            return;
        }

        let any_on_screen = self.proposals.iter().any(|p| p.on_screen);
        let active_cats = self.active_categories;
        let mut scored: Vec<(f32, AttackProposal)> = self
            .proposals
            .drain(..)
            .map(|p| {
                let on_screen = if p.on_screen { 1.0 } else { 0.0 };
                let in_range = if p.range_ok { 1.0 } else { 0.0 };
                let denied = (p.denied_t / MAX_ATTACK_WAIT_SECONDS).min(1.0);
                let category_idle = if !active_cats[p.category as usize] { 1.0 } else { 0.0 };
                let score = 3.0 * on_screen + 2.0 * in_range + 1.5 * denied + 1.0 * category_idle;
                (score, p)
            })
            .collect();

        scored.sort_by(|(sa, pa), (sb, pb)| {
            sb.total_cmp(sa)
                .then_with(|| pa.spawn_index.cmp(&pb.spawn_index))
                .then_with(|| pa.enemy_id.cmp(&pb.enemy_id))
        });

        let same_role_stagger = if self.boss_present {
            BOSS_SAME_ROLE_STAGGER
        } else {
            REGULAR_SAME_ROLE_STAGGER
        };
        let mut granted_weight: u8 = 0;
        let mut forced_grants: u8 = 0;
        let dt = enemy_dt.max(0.0);

        for (_, p) in scored {
            if p.enemy_idx >= enemies.len() {
                continue;
            }
            let role_idx = p.role.index();
            let last_role_start = dir_state.last_start_by_role[role_idx];
            let staggered = last_role_start > -999.0 && (enemy_time - last_role_start) < same_role_stagger;
            let within_budget = self
                .active_weight
                .saturating_add(granted_weight)
                .saturating_add(p.weight)
                <= self.budget;
            let offscreen_blocked = any_on_screen
                && !p.on_screen
                && !(p.role == EnemyRole::Sniper && p.sniper_visible);
            let forced = p.denied_t >= MAX_ATTACK_WAIT_SECONDS
                && forced_grants == 0
                && (enemy_time - dir_state.last_forced_start) >= FORCED_ATTACK_STAGGER_SECONDS
                && (p.on_screen || p.dist_to_player <= 1.2 * p.attack_range);

            if (within_budget && !staggered && !offscreen_blocked) || forced {
                granted_weight = granted_weight.saturating_add(p.weight);
                if forced && (!within_budget || staggered || offscreen_blocked) {
                    forced_grants = forced_grants.saturating_add(1);
                    dir_state.last_forced_start = enemy_time;
                    enemies[p.enemy_idx].ai.last_forced_attack_started_at = enemy_time;
                }
                dir_state.last_start_by_role[role_idx] = enemy_time;
                let enemy = &mut enemies[p.enemy_idx];
                enemy.ai.director_granted = true;
                enemy.ai.attack_denied_t = 0.0;
                enemy.ai.attack_denial_reason = None;
                enemy.ai.last_attack_started_at = enemy_time;
            } else {
                let enemy = &mut enemies[p.enemy_idx];
                enemy.ai.director_granted = false;
                enemy.ai.attack_denied_t += dt;
                enemy.ai.attack_denial_reason = Some(if staggered {
                    AttackDenialReason::SameTypeStagger
                } else {
                    AttackDenialReason::CommitmentBudget
                });
            }
        }
    }
}

pub fn active_attack_weight(enemy: &Enemy) -> u8 {
    let committed = match enemy.role {
        EnemyRole::Chaser => enemy.ai.lunge_windup > 0.0 || enemy.ai.lunge_t > 0.0,
        EnemyRole::Charger => matches!(
            enemy.ai.sub_state,
            EnemySubState::ChargerWindup | EnemySubState::ChargerCharging
        ),
        EnemyRole::Flyer => matches!(
            enemy.ai.sub_state,
            EnemySubState::FlyerWindup | EnemySubState::FlyerDashing
        ),
        EnemyRole::Sniper => enemy.ai.sub_state == EnemySubState::SniperWindup,
        EnemyRole::Bomber => enemy.ai.sub_state == EnemySubState::BomberWindup,
        EnemyRole::Tank => enemy.ai.sub_state == EnemySubState::TankWindup,
        EnemyRole::Ranged => enemy.ai.sub_state == EnemySubState::RangedWindup,
        EnemyRole::Spitter => enemy.ai.sub_state == EnemySubState::SpitterWindup,
        EnemyRole::Engineer => enemy.ai.sub_state == EnemySubState::EngineerWindup,
        _ => false,
    };
    if !committed {
        0
    } else if matches!(
        enemy.role,
        EnemyRole::Charger | EnemyRole::Spitter | EnemyRole::Sniper
    ) {
        2
    } else {
        1
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sim::math::Vec2;

    #[test]
    fn weight_two_sniper_and_charger_can_attack_in_small_wave() {
        let mut sniper = Enemy::new(1, Vec2::new(260.0, 0.0), 50, 80.0, "sniper");
        sniper.spawn_index = 0;
        let mut enemies = vec![sniper];
        let mut state = AttackDirectorState::default();
        let mut director = AttackDirector::new(&enemies, 0.0, 0.95);
        assert!(director.budget >= 2);
        director.propose(AttackProposal {
            enemy_idx: 0,
            enemy_id: 1,
            spawn_index: 0,
            role: EnemyRole::Sniper,
            category: AttackCategory::Ranged,
            weight: 2,
            range_ok: true,
            on_screen: true,
            sniper_visible: true,
            denied_t: 0.0,
            attack_range: 740.0,
            dist_to_player: 260.0,
        });
        director.resolve(&mut enemies, &mut state, 1.0, 1.0 / 60.0, 0.0, 0.95);
        assert!(enemies[0].ai.director_granted);
    }

    #[test]
    fn on_screen_proposal_beats_off_screen_proposal_regardless_of_vec_order() {
        let mut off = Enemy::new(10, Vec2::new(700.0, 0.0), 50, 80.0, "ranged");
        off.spawn_index = 0;
        let mut on = Enemy::new(11, Vec2::new(180.0, 0.0), 50, 80.0, "ranged");
        on.spawn_index = 1;
        let mut enemies = vec![off, on];
        let mut state = AttackDirectorState::default();
        let mut director = AttackDirector::new(&enemies, 0.0, 1.0);

        // Propose off-screen first, on-screen second.
        director.propose(AttackProposal {
            enemy_idx: 0,
            enemy_id: 10,
            spawn_index: 0,
            role: EnemyRole::Ranged,
            category: AttackCategory::Ranged,
            weight: 1,
            range_ok: true,
            on_screen: false,
            sniper_visible: false,
            denied_t: 0.0,
            attack_range: 330.0,
            dist_to_player: 700.0,
        });
        director.propose(AttackProposal {
            enemy_idx: 1,
            enemy_id: 11,
            spawn_index: 1,
            role: EnemyRole::Ranged,
            category: AttackCategory::Ranged,
            weight: 1,
            range_ok: true,
            on_screen: true,
            sniper_visible: false,
            denied_t: 0.0,
            attack_range: 330.0,
            dist_to_player: 180.0,
        });
        director.resolve(&mut enemies, &mut state, 1.0, 1.0 / 60.0, 0.0, 1.0);
        assert!(!enemies[0].ai.director_granted);
        assert!(enemies[1].ai.director_granted);
    }
}
