/// Difficulty- and wave-scaled enemy AI skill profile.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AiSkill {
    pub reaction_s: f32,
    pub lead_quality: f32,
    pub dodge_chance: f32,
    pub dodge_reaction_s: f32,
    pub respects_iframes: bool,
    pub aim_jitter_deg: f32,
    pub coordination: f32,
    pub axis_turn_deg_s: f32,
    pub weave_mult: f32,
}

#[inline]
fn lerp(a: f32, b: f32, t: f32) -> f32 {
    a + (b - a) * t
}

/// Deterministic Easy / Normal / Hard w1 -> w20 linear ramp.
pub fn ai_skill(difficulty: &str, wave: i32) -> AiSkill {
    let t = ((wave.max(1) - 1) as f32 / 19.0).clamp(0.0, 1.0);
    match difficulty.to_ascii_lowercase().as_str() {
        "easy" => AiSkill {
            reaction_s: lerp(0.28, 0.18, t),
            lead_quality: lerp(0.35, 0.55, t),
            dodge_chance: lerp(0.20, 0.45, t),
            dodge_reaction_s: lerp(0.18, 0.12, t),
            respects_iframes: false,
            aim_jitter_deg: lerp(9.0, 5.5, t),
            coordination: lerp(0.70, 0.90, t),
            axis_turn_deg_s: lerp(45.0, 70.0, t),
            weave_mult: lerp(0.65, 0.90, t),
        },
        "hard" => AiSkill {
            reaction_s: lerp(0.12, 0.05, t),
            lead_quality: lerp(0.80, 1.00, t),
            dodge_chance: lerp(0.70, 0.92, t),
            dodge_reaction_s: lerp(0.08, 0.04, t),
            respects_iframes: true,
            aim_jitter_deg: lerp(3.0, 0.8, t),
            coordination: lerp(1.15, 1.40, t),
            axis_turn_deg_s: lerp(105.0, 145.0, t),
            weave_mult: lerp(1.10, 1.35, t),
        },
        _ => AiSkill {
            reaction_s: lerp(0.20, 0.10, t),
            lead_quality: lerp(0.60, 0.85, t),
            dodge_chance: lerp(0.45, 0.72, t),
            dodge_reaction_s: lerp(0.12, 0.07, t),
            respects_iframes: wave >= 6,
            aim_jitter_deg: lerp(5.5, 2.5, t),
            coordination: lerp(0.95, 1.15, t),
            axis_turn_deg_s: lerp(75.0, 110.0, t),
            weave_mult: lerp(0.90, 1.15, t),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ai_skill_ramps_monotonically_across_difficulties_and_waves() {
        let e1 = ai_skill("easy", 1);
        let e20 = ai_skill("easy", 20);
        let n1 = ai_skill("normal", 1);
        let n20 = ai_skill("normal", 20);
        let h1 = ai_skill("hard", 1);
        let h20 = ai_skill("hard", 20);

        assert!(e1.lead_quality < e20.lead_quality);
        assert!(n1.lead_quality < n20.lead_quality);
        assert!(h1.lead_quality < h20.lead_quality);
        assert!(e1.lead_quality < n1.lead_quality && n1.lead_quality < h1.lead_quality);
        assert!(e1.reaction_s > n1.reaction_s && n1.reaction_s > h1.reaction_s);
        assert!(e1.aim_jitter_deg > n1.aim_jitter_deg && n1.aim_jitter_deg > h1.aim_jitter_deg);
        assert!(h1.respects_iframes && !e20.respects_iframes);
    }
}
