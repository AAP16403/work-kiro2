use serde::Serialize;

use plouto_rs::render::models3d::{draw_boss_model, draw_enemy_model, draw_player_pod};
use plouto_rs::render::sdf::{SdfBatch, SdfInstance};
use plouto_rs::sim::config::{enemy_color, ISO_SCALE_X, ISO_SCALE_Y};
use plouto_rs::sim::enemy::{Enemy, EnemySubState};
use plouto_rs::sim::math::Vec2;
use plouto_rs::sim::skins::DEFAULT_PALETTE;

#[derive(Serialize)]
struct DrawInstance {
    kind: u32,
    p0: [f32; 2],
    p1: [f32; 2],
    params: [f32; 4],
    color: [f32; 4],
}

#[derive(Serialize)]
struct EnemyView {
    label: &'static str,
    center: [f32; 2],
    instances: Vec<DrawInstance>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    let behavior = args.next().unwrap_or_else(|| "tank".to_string());
    let output = args
        .next()
        .unwrap_or_else(|| format!("release/{behavior}_model_review.json"));
    let model_scale = args
        .next()
        .map(|value| value.parse::<f32>())
        .transpose()?
        .unwrap_or(1.25);
    let review_pose = args.next().unwrap_or_default();
    let headings = [
        ("RIGHT", Vec2::new(1.0, 0.0)),
        ("UP-RIGHT", Vec2::new(1.0, 1.0)),
        ("UP", Vec2::new(0.0, 1.0)),
        ("UP-LEFT", Vec2::new(-1.0, 1.0)),
        ("LEFT", Vec2::new(-1.0, 0.0)),
        ("DOWN-LEFT", Vec2::new(-1.0, -1.0)),
        ("DOWN", Vec2::new(0.0, -1.0)),
        ("DOWN-RIGHT", Vec2::new(1.0, -1.0)),
    ];
    let mut views = Vec::with_capacity(headings.len());
    for (index, (label, screen_heading)) in headings.into_iter().enumerate() {
        let sx = screen_heading.x / ISO_SCALE_X;
        let sy = screen_heading.y / ISO_SCALE_Y;
        let facing = Vec2::new(sx + sy, sy - sx);
        let mut enemy = Enemy::new(8300 + index as u64, Vec2::ZERO, 100, 80.0, &behavior);
        let windup = match behavior.as_str() {
            "tank" => {
                enemy.ai.push_t = 0.52;
                enemy.vel = Vec2::new(76.0, 0.0);
                enemy.attack_cd = 0.16;
                0.0
            }
            "chaser" => {
                enemy.ai.lunge_windup = 0.18;
                enemy.ai.lunge_t = 0.1;
                enemy.vel = Vec2::new(170.0, 0.0);
                0.82
            }
            "ranged" => {
                enemy.ai.sub_state = EnemySubState::RangedWindup;
                enemy.ai.sub_timer = 0.06;
                0.82
            }
            "sniper" => {
                enemy.ai.sub_state = EnemySubState::SniperWindup;
                enemy.ai.sub_timer = 0.18;
                0.8
            }
            "charger" => {
                enemy.ai.sub_state = EnemySubState::ChargerWindup;
                enemy.ai.state_timer = Some(0.1);
                0.8
            }
            "spitter" => {
                enemy.ai.sub_state = EnemySubState::SpitterWindup;
                enemy.ai.sub_timer = 0.08;
                0.79
            }
            "flyer" => {
                enemy.ai.sub_state = EnemySubState::FlyerWindup;
                enemy.ai.state_timer = Some(0.08);
                enemy.vel = Vec2::new(120.0, 0.0);
                0.82
            }
            "engineer" => {
                enemy.ai.sub_state = EnemySubState::EngineerWindup;
                enemy.ai.sub_timer = 0.08;
                0.85
            }
            "swarm" => {
                enemy.vel = Vec2::new(118.0, 0.0);
                0.0
            }
            "egg_sac" => {
                enemy.ai.hatch_timer = 0.48;
                0.0
            }
            "boss_laser" => {
                enemy.ai.sub_state = EnemySubState::LaserCharge;
                enemy.ai.sub_timer = 0.12;
                enemy.ai.phase = 2;
                enemy.ai.charge_dir = Vec2::new(0.4, -1.0).normalized();
                0.86
            }
            "boss_swarmqueen" => match review_pose.as_str() {
                "brood" => {
                    enemy.ai.sub_state = EnemySubState::QueenBroodTelegraph;
                    0.86
                }
                "swarm" => {
                    enemy.ai.sub_state = EnemySubState::QueenSwarmTelegraph;
                    0.86
                }
                "volley" => {
                    enemy.ai.sub_state = EnemySubState::QueenVolleyTelegraph;
                    0.86
                }
                _ => 0.0,
            },
            "boss_womb_core" if review_pose == "pulse" => {
                enemy.ai.sub_state = EnemySubState::WombPulseTelegraph;
                0.9
            }
            "boss_eclipse_archon" => match review_pose.as_str() {
                "charge" => {
                    enemy.ai.sub_state = EnemySubState::EclipseCharge;
                    0.9
                }
                "burst" => {
                    enemy.ai.sub_state = EnemySubState::EclipseBurst;
                    0.0
                }
                "escape" => {
                    enemy.ai.sub_state = EnemySubState::EclipseEscape;
                    0.0
                }
                _ => 0.0,
            },
            _ => 0.0,
        };
        let center = [
            (index % 4) as f32 * 280.0 + 140.0,
            (index / 4) as f32 * 224.0 + 122.0,
        ];
        // Keep a continuously rotating bomber at its labeled heading in the
        // review sheet; attack strobe is checked separately by its render test.
        let time = if behavior == "bomber" { 0.0 } else { 0.8 };
        let mut alpha = SdfBatch::default();
        let mut add = SdfBatch::default();
        if behavior == "player" {
            draw_player_pod(
                &mut alpha,
                &mut add,
                center,
                facing,
                Vec2::ZERO,
                model_scale,
                0.0,
                0.0,
                time,
                1.0,
                false,
                false,
                false,
                0,
                false,
                true,
                &DEFAULT_PALETTE,
            );
        } else if behavior.starts_with("boss_") {
            draw_boss_model(
                &enemy,
                &mut alpha,
                &mut add,
                center,
                facing,
                model_scale,
                time,
                windup,
                enemy_color(&behavior, false),
                false,
            );
        } else {
            draw_enemy_model(
                &enemy,
                &mut alpha,
                &mut add,
                center,
                facing,
                model_scale,
                0.0,
                0.0,
                time,
                windup,
                1.0,
                enemy_color(&behavior, false),
                false,
            );
        }
        let instances = alpha
            .instances
            .iter()
            // Screen-space glows and telegraph rings are not mesh geometry.
            // The review sheet should show only the real rotating 3D model.
            .filter(|instance| instance.kind == 4)
            .map(copy_instance)
            .collect();
        views.push(EnemyView { label, center, instances });
    }
    if let Some(parent) = std::path::Path::new(&output).parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(output, serde_json::to_vec_pretty(&views)?)?;
    Ok(())
}

fn copy_instance(instance: &SdfInstance) -> DrawInstance {
    DrawInstance {
        kind: instance.kind,
        p0: instance.p0,
        p1: instance.p1,
        params: instance.params,
        color: instance.color,
    }
}
