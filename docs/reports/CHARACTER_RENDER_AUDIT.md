# Character Model Rendering Audit

**Date:** 2026-11-17  
**Scope:** Player pod, regular enemy models, boss models, world draw scales, and model-preview fitting.  
**Runtime:** The game window was not launched. Review used the source meshes and offline eight-heading render sheets.

## Result

The renderer keeps each character as a rotating 3D mesh and applies the same world-space heading and pose path used by combat rendering. The presentation pass makes the player, ordinary enemies, and most bosses read more clearly at gameplay scale, while retaining simulation-owned collision radii. Brood Matriarch's wing span now better matches its broad reference silhouette. Model previews use cached per-mesh fit values, so the dossier and menu spotlight can frame long and compact silhouettes without duplicating role-specific guesses.

## Changes

- **Player pod:** Increased the uniform model scale from `1.27` to `1.34` (+5.5%). The actual 3D body, yaw rotation, heading-dependent face visibility, banking, and pitch remain intact. Dash-ghost multipliers stay relative to the already-scaled pod dimensions, so the art scale is applied once. `PLAYER_RADIUS = 4.8` is unchanged; it remains a deliberately smaller player hurtbox.
- **Ordinary enemies:** Increased the world presentation factor from `1.30` to `1.43` (+10%). Per-role reference radii are now shared between `models3d` and `world` rendering. The grounded shadow follows the same enlarged presentation radius.
- **Bosses:** Increased modeled silhouettes by 8% through a shared scale function. Storm Sovereign keeps its prior fitted scale (`1.0`) to stay within its current 40-unit reach target; other modeled bosses use `1.08`. Boss ground shadows follow the corresponding scale.
- **Brood Matriarch:** Expanded wing spread by 20% around the shoulder hinges. Wing veins now derive their outer endpoint from the transformed outline so the raised detail remains attached when the wing is widened or folded.
- **Preview framing:** Added cached mesh-projection fit helpers for player, regular-enemy, and boss models. Their extents are measured over eight headings, with modest pitch and roll, and include each model's default articulated geometry. The menu/Guide workstream uses these shared helpers for its badge and spotlight frames.
- **Art specification:** Updated the documented model paths, reference dimensions, presentation scales, collision-radius notes, and heading review checklist. It records that appendages can extend beyond body hit circles, and that a CPU/offline sheet does not certify final GPU bloom or occlusion.

## Collision and scale relationship

No enemy, boss, or player simulation radius was changed in this rendering pass. Player art remains intentionally larger than its forgiving hurtbox. Enemy centers and role-specific gameplay radii remain authoritative for targeting and contact; decorative fins, weapons, wing tips, crowns, and other appendages can project outside those body areas. The enemy scale increase also enlarges existing silhouette tips, so the model and circular gameplay area are not claimed to have identical outlines. Brood Matriarch's expanded wings are presentation-only. Boss role radii remain defined by simulation.

## Visual evidence

The sheets show all eight horizontal headings at the current in-world model scales. The player face naturally disappears when the nose turns away; the meshes keep their three-dimensional form through the turn.

### Regular roster and player

![Player and regular enemy models at in-world scales across eight headings](../../release/character_render_regular_world_scale_review.png)

### Boss roster

![Boss models at in-world scales across eight headings](../../release/character_render_boss_world_scale_review.png)

These are offline CPU projections of model geometry. They confirm silhouette, heading rotation, proportions, and relative scale. They do not include the final GPU compositor, runtime camera crop, bloom, or combat animation capture.

## Checks

- `cargo test -p plouto_rs --lib body_reach_fits_hitbox_target -- --nocapture` — passed; Storm Sovereign's static model remains within its 40-unit fitted reach.
- `cargo test -p plouto_rs --lib every_enemy_preview_has_cached_fits_for_guide_and_spotlight_frames -- --nocapture` — passed; all roster keys resolve for both preview frame sizes.
- `cargo check -p plouto_rs --all-targets` — passed. It reports two dead-code warnings in `tests/ai_fairness.rs` for unused metrics and a helper.
- No gameplay session was started.

## Remaining visual review

The offline sheets do not certify GPU lighting, bloom interaction, depth/triangle raster behavior, or final camera framing on target devices. A later GPU capture can check these aspects if visual runtime review is requested.
