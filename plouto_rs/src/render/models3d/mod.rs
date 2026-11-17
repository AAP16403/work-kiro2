//! Small, shaded 3D meshes modeled from the character artwork in
//! `assets/artwork/characters`. The arena stays isometric, while these meshes
//! rotate and bank in world space and are projected through the same camera.
//!
//! Layout: `geom` holds the mesh primitives, `project` the camera and shading,
//! `player` the pod, `enemies` and `bosses` one module per role or boss.
mod bosses;
mod enemies;
mod geom;
mod player;
mod project;

use std::f32::consts::FRAC_PI_2;
use std::sync::OnceLock;

use crate::render::sdf::{linear_rgba_f, mix_rgb, SdfBatch};
use crate::sim::config::ISO_SCALE_Y;
use crate::sim::enemy::{Enemy, EnemySubState};
use crate::sim::math::Vec2;

use self::geom::*;
use self::player::{player_yaw, project_player_point, PodMesh};
use self::project::*;

pub use self::player::draw_player_pod;

/// Presentation scale above the simulation radius for regular 3D enemy models.
pub const ENEMY_MODEL_VISUAL_SCALE: f32 = 1.43;
/// Small presence increase for most modeled boss silhouettes; collision stays simulation-owned.
pub const BOSS_MODEL_VISUAL_SCALE: f32 = 1.08;

/// Storm Sovereign already fills its 40-unit collision envelope, so keep its
/// art at the fitted scale while the other boss models receive the 8% increase.
pub fn boss_model_visual_scale(behavior: &str) -> f32 {
    if behavior == "boss_thunder" { 1.0 } else { BOSS_MODEL_VISUAL_SCALE }
}

/// Reference dimensions used by the in-world regular-enemy renderer.
/// Kept here so world rendering and model previews can share the same fit.
pub fn enemy_model_reference_radius(behavior: &str) -> f32 {
    match behavior {
        "chaser" => 22.0,
        "bomber" => 17.0,
        "ranged" => 20.0,
        "sniper" => 27.0,
        "tank" => 28.0,
        "charger" => 26.6,
        "spitter" => 32.0,
        "flyer" => 21.3,
        "engineer" => 22.0,
        "swarm" => 15.3,
        "egg_sac" => 14.0,
        _ => 20.0,
    }
}

/// Resolve the model scale used at a given regular enemy world-space radius.
pub fn enemy_model_scale(behavior: &str, visual_radius: f32) -> f32 {
    ENEMY_MODEL_VISUAL_SCALE * visual_radius / enemy_model_reference_radius(behavior)
}

/// Resolve the model scale used by a boss at its nominal visual radius.
pub fn boss_model_scale(behavior: &str, visual_radius: f32) -> f32 {
    visual_radius / 34.0 * boss_model_visual_scale(behavior)
}

/// Fit an enemy model's full rotated silhouette inside a UI preview radius.
/// Extents include the idle articulated geometry at eight headings and are cached.
pub fn enemy_model_preview_fit_scale(behavior: &str, target_radius: f32) -> Option<f32> {
    model_preview_fit_scale(behavior, target_radius)
}

/// Boss counterpart to [`enemy_model_preview_fit_scale`].
pub fn boss_model_preview_fit_scale(behavior: &str, target_radius: f32) -> Option<f32> {
    model_preview_fit_scale(behavior, target_radius)
}

/// Player pod counterpart to [`enemy_model_preview_fit_scale`].
pub fn player_model_preview_fit_scale(target_radius: f32) -> Option<f32> {
    model_preview_fit_scale("player", target_radius)
}

fn model_preview_fit_scale(behavior: &str, target_radius: f32) -> Option<f32> {
    if !target_radius.is_finite() || target_radius <= 0.0 {
        return None;
    }
    MODEL_PREVIEW_EXTENTS
        .get_or_init(build_model_preview_extents)
        .iter()
        .find_map(|(key, extent)| (*key == behavior).then_some(target_radius / extent.max(1e-3)))
}

/// Inputs for one regular enemy's articulated pose. Mirrors the parameters of the
/// former single-function animated pose builder, so call sites only change shape.
#[derive(Clone, Copy)]
pub(crate) struct EnemyAnim<'a> {
    pub(crate) behavior: &'a str,
    pub(crate) time: f32,
    pub(crate) seed: f32,
    pub(crate) windup: f32,
    pub(crate) reduce_motion: bool,
    pub(crate) tank_push: f32,
    pub(crate) move_speed: f32,
    pub(crate) tank_attack: f32,
    pub(crate) charger_dashing: bool,
}

static POD_MESH: OnceLock<PodMesh> = OnceLock::new();
static CHASER_MESH: OnceLock<Mesh> = OnceLock::new();
static BOMBER_MESH: OnceLock<Mesh> = OnceLock::new();
static RANGED_MESH: OnceLock<Mesh> = OnceLock::new();
static SNIPER_MESH: OnceLock<Mesh> = OnceLock::new();
static TANK_MESH: OnceLock<Mesh> = OnceLock::new();
static CHARGER_MESH: OnceLock<Mesh> = OnceLock::new();
static SPITTER_MESH: OnceLock<Mesh> = OnceLock::new();
static FLYER_MESH: OnceLock<Mesh> = OnceLock::new();
static ENGINEER_MESH: OnceLock<Mesh> = OnceLock::new();
static SWARM_MESH: OnceLock<Mesh> = OnceLock::new();
static EGG_SAC_MESH: OnceLock<Mesh> = OnceLock::new();
static BOSS_BRUTE_MESH: OnceLock<Mesh> = OnceLock::new();
static BOSS_LASER_MESH: OnceLock<Mesh> = OnceLock::new();
static BOSS_TRAPMASTER_MESH: OnceLock<Mesh> = OnceLock::new();
static BOSS_SWARMQUEEN_MESH: OnceLock<Mesh> = OnceLock::new();
static BOSS_THUNDER_MESH: OnceLock<Mesh> = OnceLock::new();
static BOSS_ABYSS_MESH: OnceLock<Mesh> = OnceLock::new();
static BOSS_WOMB_MESH: OnceLock<Mesh> = OnceLock::new();
static BOSS_ECLIPSE_MESH: OnceLock<Mesh> = OnceLock::new();
static MODEL_PREVIEW_EXTENTS: OnceLock<Vec<(&'static str, f32)>> = OnceLock::new();

fn pod_mesh() -> &'static PodMesh { POD_MESH.get_or_init(player::build_pod_mesh) }
fn chaser_mesh() -> &'static Mesh { CHASER_MESH.get_or_init(enemies::chaser::build_mesh) }
fn bomber_mesh() -> &'static Mesh { BOMBER_MESH.get_or_init(enemies::bomber::build_mesh) }
fn ranged_mesh() -> &'static Mesh { RANGED_MESH.get_or_init(enemies::ranged::build_mesh) }
fn sniper_mesh() -> &'static Mesh { SNIPER_MESH.get_or_init(enemies::sniper::build_mesh) }
fn tank_mesh() -> &'static Mesh { TANK_MESH.get_or_init(enemies::tank::build_mesh) }
fn charger_mesh() -> &'static Mesh { CHARGER_MESH.get_or_init(enemies::charger::build_mesh) }
fn spitter_mesh() -> &'static Mesh { SPITTER_MESH.get_or_init(enemies::spitter::build_mesh) }
fn flyer_mesh() -> &'static Mesh { FLYER_MESH.get_or_init(enemies::flyer::build_mesh) }
fn engineer_mesh() -> &'static Mesh { ENGINEER_MESH.get_or_init(enemies::engineer::build_mesh) }
fn swarm_mesh() -> &'static Mesh { SWARM_MESH.get_or_init(enemies::swarm::build_mesh) }
fn egg_sac_mesh() -> &'static Mesh { EGG_SAC_MESH.get_or_init(enemies::egg_sac::build_mesh) }
fn boss_mesh(behavior: &str) -> Option<&'static Mesh> {
    Some(match behavior {
        "boss_brute" => BOSS_BRUTE_MESH.get_or_init(bosses::brute::build_mesh),
        "boss_laser" => BOSS_LASER_MESH.get_or_init(bosses::laser::build_mesh),
        "boss_trapmaster" => BOSS_TRAPMASTER_MESH.get_or_init(bosses::trapmaster::build_mesh),
        "boss_swarmqueen" => BOSS_SWARMQUEEN_MESH.get_or_init(bosses::swarmqueen::build_mesh),
        "boss_thunder" => BOSS_THUNDER_MESH.get_or_init(bosses::thunder::build_mesh),
        "boss_abyss_gaze" => BOSS_ABYSS_MESH.get_or_init(bosses::abyss::build_mesh),
        "boss_womb_core" => BOSS_WOMB_MESH.get_or_init(bosses::womb::build_mesh),
        "boss_eclipse_archon" => BOSS_ECLIPSE_MESH.get_or_init(bosses::eclipse::build_mesh),
        _ => return None,
    })
}

/// Articulated parts for a regular enemy role; each role owns its branch in `enemies`.
fn animated_enemy_parts(a: &EnemyAnim<'_>) -> Mesh {
    match a.behavior {
        "chaser" => enemies::chaser::animated_parts(a),
        "bomber" => enemies::bomber::animated_parts(a),
        "ranged" => enemies::ranged::animated_parts(a),
        "sniper" => enemies::sniper::animated_parts(a),
        "tank" => enemies::tank::animated_parts(a),
        "charger" => enemies::charger::animated_parts(a),
        "spitter" => enemies::spitter::animated_parts(a),
        "flyer" => enemies::flyer::animated_parts(a),
        "engineer" => enemies::engineer::animated_parts(a),
        "swarm" => enemies::swarm::animated_parts(a),
        "egg_sac" => enemies::egg_sac::animated_parts(a),
        _ => Mesh::default(),
    }
}

/// Articulated parts for a boss; each boss owns its branch in `bosses`.
fn animated_boss_parts(e: &Enemy, time: f32, windup: f32, reduce_motion: bool) -> Mesh {
    match e.behavior.as_str() {
        "boss_brute" => bosses::brute::animated_parts(e, time, windup, reduce_motion),
        "boss_laser" => bosses::laser::animated_parts(e, time, windup, reduce_motion),
        "boss_trapmaster" => bosses::trapmaster::animated_parts(e, time, windup, reduce_motion),
        "boss_swarmqueen" => bosses::swarmqueen::animated_parts(e, time, windup, reduce_motion),
        "boss_thunder" => bosses::thunder::animated_parts(e, time, windup, reduce_motion),
        "boss_abyss_gaze" => bosses::abyss::animated_parts(e, time, windup, reduce_motion),
        "boss_womb_core" => bosses::womb::animated_parts(e, time, windup, reduce_motion),
        "boss_eclipse_archon" => bosses::eclipse::animated_parts(e, time, windup, reduce_motion),
        _ => Mesh::default(),
    }
}

fn build_model_preview_extents() -> Vec<(&'static str, f32)> {
    let mut result = Vec::with_capacity(20);
    result.push(("player", mesh_projected_extent(&pod_mesh().mesh)));

    for behavior in [
        "chaser", "bomber", "ranged", "sniper", "tank", "charger", "spitter", "flyer", "engineer", "swarm", "egg_sac",
    ] {
        let Some(source) = enemy_mesh_for_preview(behavior) else { continue; };
        let mut mesh = Mesh { faces: source.faces.clone() };
        let articulated = animated_enemy_parts(&EnemyAnim {
            behavior,
            time: 0.0,
            seed: 0.0,
            windup: 0.0,
            reduce_motion: true,
            tank_push: 0.0,
            move_speed: 0.0,
            tank_attack: 0.0,
            charger_dashing: false,
        });
        mesh.faces.extend(articulated.faces);
        result.push((behavior, mesh_projected_extent(&mesh)));
    }

    for behavior in [
        "boss_thunder", "boss_laser", "boss_trapmaster", "boss_swarmqueen", "boss_brute", "boss_abyss_gaze", "boss_womb_core", "boss_eclipse_archon",
    ] {
        let Some(source) = boss_mesh(behavior) else { continue; };
        let mut mesh = Mesh { faces: source.faces.clone() };
        let enemy = Enemy::new(0, Vec2::ZERO, 100, 80.0, behavior);
        let articulated = animated_boss_parts(&enemy, 0.0, 0.0, true);
        mesh.faces.extend(articulated.faces);
        result.push((behavior, mesh_projected_extent(&mesh)));
    }
    result
}

fn enemy_mesh_for_preview(behavior: &str) -> Option<&'static Mesh> {
    Some(match behavior {
        "chaser" => chaser_mesh(),
        "bomber" => bomber_mesh(),
        "ranged" => ranged_mesh(),
        "sniper" => sniper_mesh(),
        "tank" => tank_mesh(),
        "charger" => charger_mesh(),
        "spitter" => spitter_mesh(),
        "flyer" => flyer_mesh(),
        "engineer" => engineer_mesh(),
        "swarm" => swarm_mesh(),
        "egg_sac" => egg_sac_mesh(),
        _ => return None,
    })
}

fn mesh_projected_extent(mesh: &Mesh) -> f32 {
    let mut extent = 0.0_f32;
    for heading in 0..8 {
        let yaw = heading as f32 * (FRAC_PI_2 / 2.0);
        for pitch in [-0.08_f32, 0.0, 0.08] {
            for roll in [-0.2_f32, 0.0, 0.2] {
                for face in &mesh.faces {
                    for vertex in [face.a, face.b, face.c] {
                        let projected = project_world_iso(rotate_world_model(vertex, pitch, roll, yaw), 0.0, 0.0, 1.0);
                        extent = extent.max(projected[0].hypot(projected[1]));
                    }
                }
            }
        }
    }
    extent.max(1e-3)
}

pub fn draw_boss_model(
    e: &Enemy,
    alpha: &mut SdfBatch,
    add: &mut SdfBatch,
    center: [f32; 2],
    facing: Vec2,
    scale: f32,
    time: f32,
    windup: f32,
    color: [u8; 3],
    reduce_motion: bool,
) -> bool {
    let Some(mesh) = boss_mesh(e.behavior.as_str()) else { return false; };
    let facing = if e.behavior == "boss_eclipse_archon"
        && matches!(
            e.ai.sub_state,
            EnemySubState::EclipseCharge | EnemySubState::EclipseBurst
        )
    {
        let volley = if e.ai.sub_state == EnemySubState::EclipseBurst {
            (e.ai.gun_idx as i32).min(e.ai.phase.max(0))
        } else {
            0
        };
        let safe_ang = crate::sim::bosses::eclipse_safe_angle(e, volley);
        Vec2::new(safe_ang.cos(), safe_ang.sin())
    } else {
        facing
    };
    let signature = match e.behavior.as_str() {
        "boss_brute" | "boss_trapmaster" => [255, 149, 54],
        "boss_laser" => [255, 82, 226],
        "boss_abyss_gaze" => [65, 218, 255],
        "boss_swarmqueen" => [255, 105, 205],
        "boss_thunder" => [110, 218, 255],
        "boss_womb_core" => [255, 105, 168],
        "boss_eclipse_archon" => [60, 255, 204],
        _ => [120, 244, 219],
    };
    let rage = e.ai.rage;
    let signature = if rage { mix_rgb(signature, [255, 54, 78], 0.46) } else { signature };
    let phase_mix = e.ai.phase.clamp(0, 2) as f32 * 0.055;
    let mut colors = [
        mix_rgb(mix_rgb(color, [24, 29, 45], 0.5), signature, phase_mix),
        mix_rgb(mix_rgb(color, [198, 209, 225], 0.42), signature, phase_mix * 0.35),
        [7, 11, 22],
        mix_rgb(color, signature, 0.62),
        signature,
        mix_rgb(signature, [245, 255, 255], 0.42),
        mix_rgb(signature, [255, 247, 216], 0.28),
        if e.behavior == "boss_brute" { [231, 207, 167] } else { mix_rgb(color, signature, 0.38) },
    ];
    if e.behavior == "boss_laser" {
        colors = [
            [42, 22, 76],
            [159, 104, 217],
            [13, 8, 29],
            [199, 63, 244],
            [58, 224, 255],
            [255, 227, 255],
            [255, 56, 221],
            [147, 249, 255],
        ];
    } else if e.behavior == "boss_brute" {
        // Keep the Juggernaut's armor gunmetal and its warning color amber,
        // matching the character concept even under alternate color palettes.
        colors[0] = mix_rgb([62, 66, 77], color, 0.14);
        colors[1] = mix_rgb([158, 156, 153], color, 0.12);
        colors[2] = [22, 21, 24];
        colors[3] = [138, 83, 50];
        colors[4] = [255, 134, 40];
        colors[5] = [255, 190, 88];
        colors[6] = [242, 190, 106];
    } else if e.behavior == "boss_trapmaster" {
        colors[0] = [108, 76, 45];
        colors[1] = [178, 137, 83];
        colors[2] = [28, 23, 20];
        colors[3] = [167, 94, 35];
        colors[4] = [255, 119, 39];
        colors[5] = [255, 210, 125];
        colors[6] = [255, 177, 71];
        colors[7] = [231, 184, 116];
    } else if e.behavior == "boss_abyss_gaze" {
        colors = [
            [39, 26, 65],
            [123, 96, 153],
            [10, 8, 25],
            [163, 48, 221],
            [243, 57, 248],
            [225, 241, 255],
            [45, 205, 255],
            [195, 143, 245],
        ];
    } else if e.behavior == "boss_thunder" {
        let storm_glow = if rage { mix_rgb([48, 211, 255], [255, 87, 99], 0.36) } else { [48, 211, 255] };
        colors = [
            [31, 45, 68],
            [117, 139, 167],
            [9, 16, 31],
            [194, 147, 61],
            storm_glow,
            [225, 250, 255],
            mix_rgb(storm_glow, [192, 245, 255], 0.18),
            [242, 202, 112],
        ];
    } else if e.behavior == "boss_swarmqueen" {
        let brood_glow = if rage { mix_rgb([255, 55, 190], [255, 72, 80], 0.35) } else { [255, 55, 190] };
        colors = [
            [66, 39, 85],
            [177, 112, 159],
            [22, 14, 31],
            [232, 167, 75],
            brood_glow,
            [255, 218, 244],
            [255, 122, 222],
            [248, 218, 239],
        ];
    } else if e.behavior == "boss_womb_core" {
        let heart_glow = if rage { mix_rgb([255, 48, 163], [255, 74, 102], 0.38) } else { [255, 48, 163] };
        colors = [
            [47, 37, 61],
            [128, 91, 132],
            [18, 13, 28],
            [194, 76, 151],
            heart_glow,
            [255, 177, 225],
            [255, 105, 186],
            [91, 212, 226],
        ];
    } else if e.behavior == "boss_eclipse_archon" {
        let eclipse_glow = if rage { mix_rgb([60, 255, 204], [255, 65, 198], 0.34) } else { [60, 255, 204] };
        colors = [
            [25, 28, 48],
            [104, 105, 143],
            [5, 7, 17],
            [139, 44, 221],
            eclipse_glow,
            [223, 255, 249],
            [255, 76, 225],
            [156, 229, 255],
        ];
    }
    let bob = if reduce_motion { 0.0 } else { (time * 1.8 + e.seed).sin() * 0.035 };
    let pitch = if e.behavior == "boss_brute" {
        let attack_lean = match e.ai.sub_state {
            EnemySubState::BruteCharge => 0.18,
            EnemySubState::BruteTelegraph => windup * 0.14,
            _ => 0.0,
        };
        bob + attack_lean
    } else if e.behavior == "boss_thunder" {
        bob + if reduce_motion { 0.0 } else { time * 0.12 } - windup * 0.025
    } else if reduce_motion {
        0.0
    } else {
        bob - windup * 0.018
    };
    let roll = if reduce_motion {
        0.0
    } else if matches!(e.behavior.as_str(), "boss_womb_core" | "boss_eclipse_archon") {
        (time * 0.72 + e.seed).sin() * 0.13
    } else {
        (time * 1.2 + e.seed).sin() * 0.045
    };
    let yaw = player_yaw(facing) + if reduce_motion {
        0.0
    } else {
        match e.behavior.as_str() {
            "boss_trapmaster" => time * 0.55 + FRAC_PI_2,
            "boss_womb_core" => time * 0.48,
            "boss_eclipse_archon" => -time * if rage { 1.1 } else { 0.62 },
            _ => 0.0,
        }
    };
    let articulated = animated_boss_parts(e, time, windup, reduce_motion);
    draw_meshes_combined(&[mesh, &articulated], alpha, center, facing, scale, pitch, roll, yaw, &colors, 1.0, false, true);

    let pulse = if reduce_motion { 1.0 } else { 0.84 + 0.16 * (time * 4.8 + e.seed).sin() };
    let core_local = match e.behavior.as_str() {
        "boss_brute" => V3::new(27.5, 0.0, 11.5),
        "boss_laser" => V3::new(20.1, 0.0, 3.5),
        "boss_trapmaster" => V3::new(0.0, -16.0, 5.0),
        "boss_swarmqueen" => V3::new(18.4, 0.0, 12.3),
        "boss_thunder" => V3::ZERO,
        "boss_abyss_gaze" => V3::new(0.0, -13.8, 0.0),
        "boss_womb_core" => V3::new(0.0, 0.0, 6.5),
        "boss_eclipse_archon" => V3::ZERO,
        _ => V3::new(0.0, 0.0, 14.5),
    };
    let core = project_player_point(core_local, center, scale, pitch, roll, yaw);
    let core_radius = match e.behavior.as_str() {
        "boss_brute" => 3.2,
        "boss_laser" => 6.0,
        "boss_trapmaster" => 4.8,
        "boss_swarmqueen" => 5.6,
        "boss_thunder" => 5.0,
        "boss_abyss_gaze" => 9.2,
        "boss_womb_core" => 6.0,
        "boss_eclipse_archon" => 0.0,
        _ => 5.0,
    } * scale;
    let eye_visibility = if e.behavior == "boss_abyss_gaze" {
        let camera_view = V3::new(-1.0, -1.0, (2.0 * ISO_SCALE_Y) / 0.82).normalized();
        rotate_world_model(V3::new(0.0, -1.0, 0.0), pitch, roll, yaw)
            .normalized()
            .dot(camera_view)
            .clamp(0.0, 1.0)
    } else {
        1.0
    };
    if e.behavior == "boss_brute" {
        for side in [-1.0_f32, 1.0] {
            let eye = project_player_point(V3::new(28.1, side * 4.1, 12.2), center, scale, pitch, roll, yaw);
            add.circle(eye[0], eye[1], 1.45 * scale * pulse, linear_rgba_f(signature, 0.88, 1.38 + windup * 0.18));
            add.circle(eye[0], eye[1], 0.46 * scale, linear_rgba_f([255, 240, 196], 0.94, 1.2));
        }
    } else if e.behavior != "boss_eclipse_archon" && eye_visibility > 0.035 {
        add.circle(core[0], core[1], core_radius * pulse * (1.0 + windup * 0.12), linear_rgba_f(signature, 0.88 * eye_visibility, 1.42 + windup * 0.2));
        add.circle(core[0], core[1], core_radius * pulse * 0.38, linear_rgba_f([255, 255, 242], 0.92 * eye_visibility, 1.25));
    }
    if e.behavior == "boss_abyss_gaze" && eye_visibility > 0.08 {
        let pupil = project_player_point(V3::new(0.0, -13.8, 0.0), center, scale, pitch, roll, yaw);
        add.ellipse(pupil[0], pupil[1], 1.5 * scale, 6.2 * scale, 0.0, linear_rgba_f([8, 13, 31], 0.96 * eye_visibility, 1.0));
        if !reduce_motion {
            let glint = project_player_point(V3::new(-3.2, -13.2, 3.4), center, scale, pitch, roll, yaw);
            add.circle(glint[0], glint[1], 1.15 * scale, linear_rgba_f([245, 255, 255], 0.9 * eye_visibility, 1.2));
        }
    }
    if e.ai.sub_state == EnemySubState::EclipseCharge {
        let f_yaw = player_yaw(facing);
        for side in [-1.0_f32, 1.0] {
            // Local rails are the +/-0.42 rad edges of the same fixed sector
            // omitted by the radial projectile pattern.
            let start = project_player_point(V3::new(17.0, side * 7.6, 2.0), center, scale, pitch, roll, f_yaw);
            let end = project_player_point(V3::new(48.0, side * 20.2, 0.0), center, scale, pitch, roll, f_yaw);
            add.line(start[0], start[1], end[0], end[1], 2.2, linear_rgba_f([198, 255, 244], 0.7, 1.25));
        }
    }
    true
}

pub fn draw_enemy_model(
    e: &Enemy,
    alpha: &mut SdfBatch,
    add: &mut SdfBatch,
    center: [f32; 2],
    facing: Vec2,
    scale: f32,
    pitch: f32,
    roll: f32,
    time: f32,
    windup: f32,
    opacity: f32,
    color: [u8; 3],
    reduce_motion: bool,
) -> bool {
    let behavior = e.behavior.as_str();
    let mesh = match behavior {
        "chaser" => chaser_mesh(),
        "bomber" => bomber_mesh(),
        "ranged" => ranged_mesh(),
        "sniper" => sniper_mesh(),
        "tank" => tank_mesh(),
        "charger" => charger_mesh(),
        "spitter" => spitter_mesh(),
        "flyer" => flyer_mesh(),
        "engineer" => engineer_mesh(),
        "swarm" => swarm_mesh(),
        "egg_sac" => egg_sac_mesh(),
        _ => return false,
    };
    let signature = match behavior {
        "chaser" => [74, 211, 249],
        "sniper" => [236, 95, 255],
        "spitter" => [181, 255, 76],
        "flyer" => [110, 220, 255],
        "engineer" => [91, 255, 191],
        "swarm" => [255, 105, 76],
        "egg_sac" => [255, 113, 131],
        "tank" => [56, 226, 244],
        "bomber" | "charger" => [255, 157, 63],
        "ranged" => [255, 142, 51],
        _ => [90, 225, 255],
    };
    let colors = if behavior == "tank" {
        [
            [56, 65, 79],
            [126, 137, 153],
            [13, 20, 30],
            [255, 143, 55],
            [50, 222, 241],
            [196, 255, 255],
            [118, 255, 250],
            [255, 207, 112],
        ]
    } else if behavior == "chaser" {
        [
            [42, 54, 71],
            [120, 135, 153],
            [8, 14, 24],
            [255, 116, 62],
            [62, 205, 241],
            [205, 248, 255],
            [255, 224, 170],
            [244, 126, 96],
        ]
    } else if behavior == "bomber" {
        [
            [40, 50, 64],
            [112, 126, 145],
            [8, 14, 23],
            [255, 137, 48],
            [255, 158, 54],
            [255, 218, 133],
            [255, 234, 166],
            [72, 205, 228],
        ]
    } else if behavior == "ranged" {
        [
            [38, 48, 63],
            [112, 127, 147],
            [8, 14, 24],
            [255, 134, 48],
            [58, 214, 239],
            [207, 249, 255],
            [92, 235, 248],
            [255, 197, 111],
        ]
    } else if behavior == "sniper" {
        [
            [39, 45, 63],
            [118, 128, 148],
            [9, 10, 22],
            [238, 87, 252],
            [74, 210, 240],
            [245, 204, 255],
            [229, 62, 244],
            [255, 154, 255],
        ]
    } else if behavior == "charger" {
        [
            [40, 48, 62],
            [118, 130, 148],
            [8, 13, 22],
            [255, 137, 48],
            [64, 212, 237],
            [255, 238, 201],
            [255, 177, 64],
            [255, 222, 151],
        ]
    } else if behavior == "spitter" {
        [
            [39, 49, 60],
            [116, 134, 146],
            [8, 15, 22],
            [187, 255, 42],
            [67, 215, 236],
            [229, 255, 151],
            [170, 255, 25],
            [235, 255, 92],
        ]
    } else if behavior == "flyer" {
        [
            [40, 49, 63],
            [116, 132, 151],
            [8, 14, 24],
            [255, 128, 58],
            [60, 211, 239],
            [255, 232, 196],
            [255, 142, 68],
            [255, 190, 127],
        ]
    } else if behavior == "engineer" {
        [
            [58, 70, 85],
            [137, 151, 168],
            [12, 18, 28],
            [255, 145, 52],
            [60, 214, 237],
            [255, 230, 171],
            [255, 184, 62],
            [255, 213, 132],
        ]
    } else if behavior == "swarm" {
        [
            [42, 51, 66],
            [122, 136, 153],
            [8, 14, 24],
            [255, 112, 82],
            [66, 214, 241],
            [255, 222, 181],
            [255, 104, 74],
            [255, 182, 143],
        ]
    } else if behavior == "egg_sac" {
        [
            [48, 38, 53],
            [132, 99, 116],
            [18, 14, 27],
            [255, 104, 131],
            [245, 91, 119],
            [255, 226, 188],
            [255, 140, 112],
            [203, 169, 157],
        ]
    } else {
        [
            mix_rgb(color, [29, 36, 49], 0.48),
            mix_rgb(color, [215, 226, 237], 0.34),
            [9, 14, 24],
            mix_rgb(signature, color, 0.22),
            signature,
            mix_rgb(signature, [255, 255, 255], 0.48),
            mix_rgb(signature, [255, 245, 205], 0.34),
            mix_rgb(color, signature, 0.34),
        ]
    };
    let yaw = player_yaw(facing);
    let tank_attack = if behavior == "tank" && e.ai.sub_state == EnemySubState::TankWindup {
        windup.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let egg_hatch = if behavior == "egg_sac" {
        (1.0 - (e.ai.hatch_timer / e.ai.max_hatch_timer.max(0.1)).clamp(0.0, 1.0)).clamp(0.0, 1.0)
    } else {
        0.0
    };
    let pose_windup = if behavior == "egg_sac" { egg_hatch } else { windup };
    let articulated = animated_enemy_parts(&EnemyAnim {
        behavior,
        time,
        seed: e.seed,
        windup: pose_windup,
        reduce_motion,
        tank_push: e.ai.push_t,
        move_speed: e.vel.length(),
        tank_attack,
        charger_dashing: e.ai.charger_dashing,
    });
    if matches!(behavior, "chaser" | "flyer" | "swarm" | "egg_sac" | "engineer" | "tank" | "ranged" | "sniper" | "charger" | "spitter") {
        draw_meshes_combined(&[mesh, &articulated], alpha, center, facing, scale, pitch, roll, yaw, &colors, opacity, false, true);
    } else {
        draw_meshes_combined(&[mesh], alpha, center, facing, scale, pitch, roll, yaw, &colors, opacity, false, true);
    }

    let pulse = if reduce_motion { 1.0 } else { 0.84 + 0.16 * (time * 11.0 + e.seed).sin() };
    let exhaust_color = match behavior {
        "sniper" => [225, 82, 255],
        "flyer" => [94, 214, 255],
        _ => signature,
    };
    if matches!(behavior, "chaser" | "bomber" | "charger" | "flyer") {
        let rear_x = match behavior {
            "flyer" => -14.5,
            "charger" => -25.0,
            _ => -17.0,
        };
        let exhaust = project_player_point(V3::new(rear_x, 0.0, 0.2), center, scale, pitch, roll, yaw);
        if behavior == "flyer" {
            let thrust = (e.vel.length() / 145.0).clamp(0.0, 1.0);
            for side in [-1.0_f32, 1.0] {
                let nozzle = project_player_point(V3::new(-15.4, side * 11.0, 1.5), center, scale, pitch, roll, yaw);
                add.ellipse_glow(nozzle[0], nozzle[1], (2.0 + thrust) * scale * pulse, 1.45 * scale, 1.5, linear_rgba_f([72, 215, 246], opacity * (0.08 + thrust * 0.05), 1.05));
            }
        } else if behavior != "charger" {
            add.ellipse_glow(exhaust[0], exhaust[1], 3.0 * scale * pulse, 1.9 * scale * pulse, 1.7, linear_rgba_f(exhaust_color, opacity * 0.14, 1.15));
        }
        if behavior == "charger" {
            let thrust = if e.ai.charger_dashing { 1.0 } else { 0.0 };
            for side in [-1.0_f32, 1.0] {
                let flame = project_player_point(V3::new(-25.0, side * 12.5, 1.0), center, scale, pitch, roll, yaw);
                add.ellipse_glow(flame[0], flame[1], (1.8 + thrust * 1.3) * scale * pulse, 1.3 * scale, 1.45, linear_rgba_f([255, 145, 60], opacity * (0.05 + thrust * 0.07), 1.02));
            }
            if e.ai.charger_dashing || e.ai.sub_state == EnemySubState::ChargerCharging {
                let nose = project_player_point(V3::new(31.0, 0.0, 15.0), center, scale, pitch, roll, yaw);
                add.ellipse_glow(nose[0], nose[1], 5.2 * scale, 2.4 * scale, 1.55, linear_rgba_f([255, 145, 70], opacity * 0.12, 1.05));
            }
        }
    }
    if behavior == "flyer" && (e.ai.sub_state == EnemySubState::FlyerWindup || windup > 0.0) {
        let nose = project_player_point(V3::new(27.0, 0.0, 7.0), center, scale, pitch, roll, yaw);
        add.circle(nose[0], nose[1], (1.8 + windup * 1.8) * scale, linear_rgba_f([255, 215, 164], opacity * (0.55 + windup * 0.3), 1.12));
    }
    if behavior == "bomber" {
        let strobe_hz = if e.ai.sub_state == EnemySubState::BomberWindup { 16.0 } else { 5.5 };
        let strobe = if reduce_motion { 0.72 } else { 0.48 + 0.52 * (time * strobe_hz).sin().abs() };
        let core = project_player_point(V3::new(0.0, 0.0, 7.7), center, scale, pitch, roll, yaw);
        add.ellipse_glow(core[0], core[1], 7.0 * scale * (0.9 + 0.1 * strobe), 5.3 * scale, 1.6, linear_rgba_f([255, 145, 48], opacity * 0.13, 1.18));
        add.circle(core[0], core[1], 3.6 * scale * (0.9 + 0.1 * strobe), linear_rgba_f([255, 222, 126], opacity * (0.58 + 0.32 * strobe), 1.32));
    }
    if behavior == "chaser" && (e.ai.lunge_windup > 0.0 || e.ai.lunge_t > 0.0) {
        let nose = project_player_point(V3::new(20.0, 0.0, 2.5), center, scale, pitch, roll, yaw);
        add.circle(nose[0], nose[1], (2.0 + windup * 2.3) * scale, linear_rgba_f([255, 190, 112], opacity * 0.9, 1.4));
    }
    if behavior == "ranged" || behavior == "sniper" {
        let w = windup.clamp(0.0, 1.0);
        // Glow sits on the same fitted barrel mouth the mesh uses (ranged) or the rail tip (sniper).
        let muzzles: Vec<V3> = if behavior == "sniper" {
            vec![V3::new(33.0 + w * 4.0, 0.0, 7.3)]
        } else {
            vec![enemies::ranged::muzzle_point(-1.0, w), enemies::ranged::muzzle_point(1.0, w)]
        };
        for muzzle in muzzles {
            let p = project_player_point(muzzle, center, scale, pitch, roll, yaw);
            let charge = windup.max(if behavior == "sniper" { (1.0 - (e.attack_cd / 0.6).clamp(0.0, 1.0)) * 0.35 } else { (1.0 - (e.attack_cd / 0.45).clamp(0.0, 1.0)) * 0.3 });
            if behavior == "ranged" {
                add.ellipse_glow(p[0], p[1], (2.0 + charge * 1.8) * scale, (1.6 + charge) * scale, 1.35, linear_rgba_f(signature, opacity * (0.07 + 0.10 * charge), 1.0));
            } else {
                add.ellipse_glow(p[0], p[1], (2.4 + charge * 2.3) * scale, (1.6 + charge * 1.2) * scale, 1.4, linear_rgba_f(signature, opacity * (0.06 + 0.12 * charge), 1.0));
            }
            add.circle(p[0], p[1], (1.7 + charge * 2.3) * scale, linear_rgba_f(mix_rgb(signature, [255, 255, 255], 0.36), opacity * (0.48 + 0.42 * charge), 1.35));
        }
    }
    if behavior == "tank" {
        let core = project_player_point(V3::new(-0.3, 0.0, 14.5), center, scale, pitch, roll, yaw);
        add.ellipse_glow(core[0], core[1], 7.1 * scale * pulse, 5.0 * scale * pulse, 1.5, linear_rgba_f([74, 238, 250], opacity * 0.18, 1.18));
        add.circle(core[0], core[1], 3.8 * scale * pulse, linear_rgba_f([148, 255, 255], opacity * 0.84, 1.2));
        let recoil = tank_attack * 4.2;
        for side in [-1.0_f32, 1.0] {
            let muzzle = project_player_point(V3::new(31.0 - recoil, side * 11.3, 15.6 + tank_attack * 0.75), center, scale, pitch, roll, yaw);
            add.ellipse_glow(muzzle[0], muzzle[1], (2.5 + tank_attack * 2.2) * scale, 1.8 * scale, 1.45, linear_rgba_f([255, 157, 61], opacity * (0.10 + tank_attack * 0.30), 1.2));
            add.circle(muzzle[0], muzzle[1], (1.4 + tank_attack * 1.0) * scale, linear_rgba_f([255, 223, 164], opacity * (0.28 + tank_attack * 0.58), 1.08));
        }
        if e.ai.push_t > 0.0 {
            let surge = (e.ai.push_t / 0.65).clamp(0.0, 1.0);
            let ring_alpha = if reduce_motion { 0.24 } else { 0.18 + 0.16 * (time * 18.0).sin().abs() };
            alpha.ring(center[0], center[1], 40.0 * scale, 29.0 * scale, 1.4 * scale, linear_rgba_f([255, 159, 67], opacity * ring_alpha * surge, 1.0));
            add.arc(center[0], center[1], 40.0 * scale, 2.0 * scale, if reduce_motion { 0.0 } else { time * 2.4 }, 1.6 + surge * 2.6, linear_rgba_f([255, 211, 133], opacity * 0.68 * surge, 1.2));
            for side in [-1.0_f32, 1.0] {
                let vent = project_player_point(V3::new(-25.0, side * 9.0, 5.2), center, scale, pitch, roll, yaw);
                add.ellipse_glow(vent[0], vent[1], (3.5 + surge * 3.0) * scale, 2.1 * scale, 1.5, linear_rgba_f([255, 149, 58], opacity * (0.16 + surge * 0.18), 1.2));
            }
        }
    }
    if behavior == "spitter" {
        let sac_pulse = if reduce_motion { 1.0 } else { 0.86 + 0.14 * (time * 5.2 + e.seed).sin() };
        let charge = windup.clamp(0.0, 1.0);
        for side in [-1.0_f32, 1.0] {
            let sac = project_player_point(V3::new(-4.5, side * 13.8, 8.2 + charge * 1.2), center, scale, pitch, roll, yaw);
            add.ellipse_glow(sac[0], sac[1], (3.0 + charge) * scale, 2.2 * scale, 1.35, linear_rgba_f([168, 255, 32], opacity * (0.07 + charge * 0.05), 1.0));
            add.circle(sac[0], sac[1], (1.8 + charge * 0.55) * scale * sac_pulse, linear_rgba_f([232, 255, 157], opacity * (0.62 + charge * 0.22), 1.12));
        }
    }
    if behavior == "engineer" {
        if e.ai.support_pulse > 0.0 {
            let pulse = (e.ai.support_pulse / 0.8).clamp(0.0, 1.0);
            add.arc(
                center[0],
                center[1],
                17.0 * scale,
                1.5 * scale,
                if reduce_motion { 0.0 } else { time * 2.8 },
                2.3,
                linear_rgba_f([95, 245, 195], opacity * (0.35 + 0.45 * pulse), 1.35),
            );
        }
        if e.ai.sub_state == EnemySubState::EngineerWindup || windup > 0.0 {
            let core = project_player_point(V3::new(10.8, 0.0, 2.1), center, scale, pitch, roll, yaw);
            add.circle(core[0], core[1], (3.0 + windup * 2.5) * scale, linear_rgba_f([180, 255, 229], opacity * 0.85, 1.35));
        }
    }
    if behavior == "swarm" {
        let pulse = if reduce_motion { 1.0 } else { 0.86 + 0.14 * (time * 8.0 + e.seed).sin().abs() };
        let eye = project_player_point(V3::new(19.4, 0.0, 8.0), center, scale, pitch, roll, yaw);
        add.ellipse_glow(eye[0], eye[1], 3.0 * scale, 2.2 * scale, 1.35, linear_rgba_f([255, 104, 74], opacity * 0.055 * pulse, 1.0));
        add.circle(eye[0], eye[1], 1.6 * scale * pulse, linear_rgba_f([255, 216, 176], opacity * 0.84, 1.2));
    }
    if behavior == "egg_sac" {
        let urgency = (1.0 - (e.ai.hatch_timer / e.ai.max_hatch_timer.max(0.1)).clamp(0.0, 1.0)).max(0.15);
        let egg_col = mix_rgb([255, 95, 125], [255, 220, 140], urgency);
        let core = project_player_point(V3::new(13.0, 0.0, 4.0), center, scale, pitch, roll, yaw);
        add.ellipse_glow(core[0], core[1], (3.2 + urgency * 1.8) * scale, (2.0 + urgency) * scale, 1.5, linear_rgba_f(egg_col, opacity * (0.08 + urgency * 0.10), 1.05));
        add.circle(core[0], core[1], (2.2 + urgency * 1.4) * scale, linear_rgba_f(egg_col, opacity * (0.56 + urgency * 0.28), 1.2));
    }
    true
}
