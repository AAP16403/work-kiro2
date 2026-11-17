use crate::sim::achievements::name_of as achievement_name;
use crate::sim::config::{NEON_SURGE_UNLOCK_WAVE, OBSIDIAN_UNLOCK_SCORE};

pub const DEFAULT_SKIN_ID: &str = "classic";
pub const LEGACY_GLOW2: [u8; 3] = [80, 120, 220];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Palette {
    pub body: [u8; 3],
    pub accent: [u8; 3],
    pub eye: [u8; 3],
    pub glow: [u8; 3],
    pub trail: [u8; 3],
    pub bullet: [u8; 3],
    pub cheek: [u8; 3],
}

pub const DEFAULT_PALETTE: Palette = Palette {
    body: [132, 224, 255],
    accent: [255, 206, 90],
    eye: [16, 24, 46],
    glow: [100, 220, 255],
    trail: [130, 210, 255],
    bullet: [235, 240, 255],
    cheek: [255, 140, 175],
};

pub const LEGACY_PALETTE: Palette = Palette {
    body: [132, 224, 255],
    accent: [10, 200, 255],
    eye: [255, 255, 255],
    glow: [60, 140, 220],
    trail: [130, 210, 255],
    bullet: [255, 245, 190],
    cheek: [255, 140, 175],
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UnlockRule {
    Default,
    Score(i32),
    Wave(i32),
    Bosses(i32),
    Kills(i32),
    Achievement(&'static str),
}

#[derive(Debug, Clone, Copy)]
pub struct SkinDef {
    pub id: &'static str,
    pub name: &'static str,
    pub description: &'static str,
    pub palette: Palette,
    pub unlock: UnlockRule,
}

pub const SKINS: &[SkinDef] = &[
    SkinDef {
        id: "classic",
        name: "Classic Pod",
        description: "The original cyan pod. Always unlocked.",
        palette: DEFAULT_PALETTE,
        unlock: UnlockRule::Default,
    },
    SkinDef {
        id: "ember",
        name: "Ember Pod",
        description: "A hot orange shell that glows like a reactor core.",
        palette: Palette {
            body: [255, 170, 110],
            accent: [255, 110, 60],
            eye: [255, 245, 220],
            glow: [255, 120, 50],
            trail: [255, 160, 80],
            bullet: [255, 190, 110],
            cheek: [255, 150, 120],
        },
        unlock: UnlockRule::Score(5000),
    },
    SkinDef {
        id: "frost",
        name: "Frost Pod",
        description: "Pale ice-blue plating with cold white trails.",
        palette: Palette {
            body: [210, 240, 255],
            accent: [150, 220, 255],
            eye: [40, 80, 140],
            glow: [170, 230, 255],
            trail: [200, 240, 255],
            bullet: [220, 250, 255],
            cheek: [255, 190, 215],
        },
        unlock: UnlockRule::Wave(10),
    },
    SkinDef {
        id: "verdant",
        name: "Verdant Pod",
        description: "Leaf-green hull that leaves a soft mint haze.",
        palette: Palette {
            body: [150, 240, 160],
            accent: [80, 200, 120],
            eye: [30, 70, 40],
            glow: [120, 255, 150],
            trail: [140, 255, 170],
            bullet: [190, 255, 200],
            cheek: [255, 170, 190],
        },
        unlock: UnlockRule::Kills(250),
    },
    SkinDef {
        id: "solar",
        name: "Solar Pod",
        description: "Gold plating that blazes like a sunrise.",
        palette: Palette {
            body: [255, 235, 150],
            accent: [255, 200, 60],
            eye: [90, 50, 10],
            glow: [255, 220, 90],
            trail: [255, 230, 120],
            bullet: [255, 245, 180],
            cheek: [255, 170, 110],
        },
        unlock: UnlockRule::Bosses(2),
    },
    SkinDef {
        id: "storm",
        name: "Storm Pod",
        description: "Slate-blue hull with lightning-yellow sparks.",
        palette: Palette {
            body: [120, 140, 200],
            accent: [255, 235, 80],
            eye: [255, 255, 255],
            glow: [90, 170, 255],
            trail: [150, 210, 255],
            bullet: [255, 250, 140],
            cheek: [255, 150, 200],
        },
        unlock: UnlockRule::Bosses(5),
    },
    SkinDef {
        id: "void",
        name: "Void Pod",
        description: "Violet shell that pulls light into its trail.",
        palette: Palette {
            body: [110, 70, 160],
            accent: [190, 120, 255],
            eye: [255, 240, 255],
            glow: [170, 90, 255],
            trail: [200, 140, 255],
            bullet: [230, 190, 255],
            cheek: [255, 140, 210],
        },
        unlock: UnlockRule::Achievement("combo_6x"),
    },
    SkinDef {
        id: "neon",
        name: "Neon Pod",
        description: "Hot pink hull with aqua accents.",
        palette: Palette {
            body: [255, 120, 220],
            accent: [120, 255, 240],
            eye: [25, 20, 40],
            glow: [255, 80, 200],
            trail: [120, 255, 240],
            bullet: [255, 160, 240],
            cheek: [255, 200, 240],
        },
        unlock: UnlockRule::Achievement("elite_slayer"),
    },
    SkinDef {
        id: "crimson",
        name: "Crimson Pod",
        description: "Deep red armour for those who push the score.",
        palette: Palette {
            body: [235, 70, 80],
            accent: [120, 20, 30],
            eye: [255, 230, 230],
            glow: [255, 60, 70],
            trail: [255, 110, 110],
            bullet: [255, 150, 150],
            cheek: [255, 150, 160],
        },
        unlock: UnlockRule::Score(25000),
    },
    SkinDef {
        id: "ghost",
        name: "Ghost Pod",
        description: "Near-white shell that fades into the starfield.",
        palette: Palette {
            body: [235, 240, 250],
            accent: [170, 180, 200],
            eye: [60, 70, 90],
            glow: [200, 210, 235],
            trail: [220, 225, 240],
            bullet: [250, 250, 255],
            cheek: [250, 180, 200],
        },
        unlock: UnlockRule::Achievement("no_damage_wave"),
    },
    SkinDef {
        id: "neon_surge",
        name: "Neon Surge Pod",
        description: "Electric lime shell that crackles with magenta sparks.",
        palette: Palette {
            body: [190, 255, 70],
            accent: [255, 60, 190],
            eye: [20, 22, 34],
            glow: [150, 255, 60],
            trail: [190, 255, 110],
            bullet: [235, 255, 160],
            cheek: [255, 110, 210],
        },
        unlock: UnlockRule::Wave(NEON_SURGE_UNLOCK_WAVE),
    },
    SkinDef {
        id: "obsidian",
        name: "Obsidian Pod",
        description: "Volcanic glass with a violet sheen and a cold cyan glint.",
        palette: Palette {
            body: [132, 124, 164],
            accent: [120, 240, 255],
            eye: [226, 232, 255],
            glow: [150, 100, 255],
            trail: [160, 120, 255],
            bullet: [210, 190, 255],
            cheek: [255, 110, 170],
        },
        unlock: UnlockRule::Score(OBSIDIAN_UNLOCK_SCORE),
    },
];

pub fn get_skin(id: &str) -> Option<&'static SkinDef> {
    SKINS.iter().find(|s| s.id == id)
}

pub fn palette_for(skin_id: &str) -> Palette {
    get_skin(skin_id).map(|s| s.palette).unwrap_or(DEFAULT_PALETTE)
}

pub fn aura_outer(palette: Palette) -> [u8; 3] {
    let base = LEGACY_PALETTE.glow;
    [
        (LEGACY_GLOW2[0] as i32 + palette.glow[0] as i32 - base[0] as i32).clamp(0, 255) as u8,
        (LEGACY_GLOW2[1] as i32 + palette.glow[1] as i32 - base[1] as i32).clamp(0, 255) as u8,
        (LEGACY_GLOW2[2] as i32 + palette.glow[2] as i32 - base[2] as i32).clamp(0, 255) as u8,
    ]
}

#[derive(Debug, Clone)]
pub struct RunSkin {
    pub skin_id: String,
    pub palette: Palette,
}

impl Default for RunSkin {
    fn default() -> Self {
        Self {
            skin_id: DEFAULT_SKIN_ID.to_string(),
            palette: DEFAULT_PALETTE,
        }
    }
}

impl RunSkin {
    pub fn from_skin_id(id: &str) -> Self {
        match get_skin(id) {
            Some(s) => Self {
                skin_id: s.id.to_string(),
                palette: s.palette,
            },
            None => Self::default(),
        }
    }

    pub fn is_default(&self) -> bool {
        self.skin_id == DEFAULT_SKIN_ID
    }

    pub fn ship_palette(&self) -> Palette {
        if self.is_default() {
            LEGACY_PALETTE
        } else {
            self.palette
        }
    }

    pub fn shot_palette(&self) -> Option<Palette> {
        if self.is_default() {
            None
        } else {
            Some(self.palette)
        }
    }

    pub fn dash_color(&self) -> Option<[u8; 3]> {
        if self.is_default() {
            None
        } else {
            Some(self.palette.trail)
        }
    }
}

pub fn format_thousands(n: i32) -> String {
    let s = n.abs().to_string();
    let mut out = String::with_capacity(s.len() + 4);
    for (i, ch) in s.chars().rev().enumerate() {
        if i > 0 && i % 3 == 0 {
            out.push(',');
        }
        out.push(ch);
    }
    if n < 0 {
        out.push('-');
    }
    out.chars().rev().collect()
}

pub fn unlock_rule_text(rule: UnlockRule) -> String {
    match rule {
        UnlockRule::Default => "Always unlocked".to_string(),
        UnlockRule::Score(v) => format!("Score {} in one run", format_thousands(v)),
        UnlockRule::Wave(v) => format!("Reach wave {v}"),
        UnlockRule::Bosses(v) => format!("Defeat {v} bosses across all runs"),
        UnlockRule::Kills(v) => format!("Destroy {} enemies across all runs", format_thousands(v)),
        UnlockRule::Achievement(id) => format!("Earn the {} achievement", achievement_name(id)),
    }
}

pub fn unlock_hint(skin: &SkinDef) -> String {
    unlock_rule_text(skin.unlock)
}
