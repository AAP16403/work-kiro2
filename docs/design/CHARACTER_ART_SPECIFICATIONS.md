# Character Art Specifications

**Prepared:** 2026-11-16  
**Last checked against code: 2026-11-17**  
**Purpose:** Lock reference identity and 3D presentation constraints before later art changes.  
**Evidence:** Local reference art inspected by alpha-mask bounds and Rust model-source review (`plouto_rs/src/render/models3d/`, `render/world.rs`, `render/player_art.rs`, `sim/config.rs`). Offline eight-heading sheets were reviewed at the in-world draw scales for the player, regular enemies and bosses. Final GPU appearance is not certified by those sheets.

## Shared model rules

- The files in `assets/artwork/characters/` are the character identity source. A model may add readable 3D structure, but must preserve the reference's primary silhouette, scale hierarchy, palette and signature detail.
- Source artwork ratios below are raster silhouette width ÷ height measured after binarizing alpha at `>200`. Some image files include a few high-alpha bloom pixels. Treat the value as a reference envelope, not a target screen-space ratio at every heading.
- Model coordinates use local `+X` as the nose/forward axis, `±Y` as the sides and `+Z` as vertical. Combat movement and aim supply the model heading. The fixed isometric camera must be allowed to hide the face or rear detail when the heading turns away; do not pin facial details to the screen.
- All characters use projected 3D meshes. Model volume must remain readable through the fixed isometric camera and material shading. Use a grounded soft ellipse for the shadow and retain triangle geometry along the model silhouette.
- Emissive materials identify an eye, core, engine, weapon edge or warning detail. Keep dark armor and shell panels visible under the glow, especially on bosses. The bloom pass must not become the silhouette.
- The circular simulation radius defines gameplay contact and targeting bounds independently from the rendered model and its shadow. Current presentation scale:
  - Player: the real 3D pod uses `PLAYER_ART_SCALE = 1.34` in `render/player_art.rs`, a 5.5% uniform increase from 1.27. `PLAYER_RADIUS = 4.8` remains intentionally much smaller than the hull for a forgiving player hurtbox; do not inflate it to match the model without a separate fairness review.
  - Ordinary enemies: `r_vis` starts from the collision radius (`e.radius`, floored at 11) and receives spawn, windup and hit-squash factors. The model and its grounded shadow use `model_r = r_vis × ENEMY_MODEL_VISUAL_SCALE`, with `ENEMY_MODEL_VISUAL_SCALE = 1.43` in `render/models3d/mod.rs` and applied in `render/world.rs`. This is a 10% increase over the previous 1.30 presentation scale; simulation radii are unchanged in this rendering pass. Model tips and wings can extend beyond the circular hit area, while the central hull stays the aiming/contact reference.
  - Bosses: the nominal visual radius remains `BOSS_RADIUS × 1.05`; meshes use `r / 34.0 × boss_model_visual_scale(behavior)` in `render/models3d/mod.rs`. Most bosses use `BOSS_MODEL_VISUAL_SCALE = 1.08`; Storm Sovereign remains at 1.0 because its fitted 3D reach already fills its 40-unit target. The shadow radius follows the matching scale. Boss-specific hit radii remain independent; crowns, wings, weapons and crystals may extend beyond their gameplay body area.
  - Egg sac: the visual nominal radius is `16 × pulse`; its collision radius is 16.0 in `enemy_radius()`.
  - Any size edit must preserve collision fairness and stay in arena bounds.
- Review each model at eight horizontal headings and at idle, attack tell, attack and recovery. For boss heading sheets, include the same damaged/core and reduced-motion states. Source-only heading sheets do not certify final GPU bloom, occlusion or motion.

## Player pod

| Reference | Artwork ratio | Silhouette and attachment locks | Current simulation / presentation scale |
| --- | ---: | --- | --- |
| `player-classic-pod.png` | 1.065 | Compact rounded pod, upright dome, dark forward visor with cyan rim, two oval eyes, small coral cheeks, top gold beacon, bilateral side thrusters, rear main engine. Keep the antenna attached at `+Z`, face on the `+X` ellipsoid cap, side engines at `±Y`, and exhaust at `−X`. | `PLAYER_RADIUS = 4.8`; model hull radii are `(17.2, 18.2, 14.8)` before `PLAYER_ART_SCALE = 1.34`. The gameplay face rotates with yaw and is hidden when the pod turns away. The smaller hurtbox is deliberate. |

The face should read as an inset visor on a rounded, moderately tall pod. Avoid a near-spherical bloom that erases the hull and avoid flattening the vertical axis. The viewport angle and heading decide when the face is visible; the face does not remain visible from behind.

## Regular enemy roster

| Behavior | Reference artwork | Reference ratio | Identity locks | Collision radius |
| --- | --- | ---: | --- | ---: |
| Chaser | `enemy-chaser.png` | 0.921 | Long graphite arrowhead, central dark canopy, swept wings, cyan leading edge, restrained amber marks, one dominant rear engine. | 13.65 |
| Bomber | `enemy-bomber.png` | 1.165 | Four diagonal bomb arms remain distinct around a central furnace; amber bomb caps and cyan edge lights. Keep the body centered and the four arms visible from all headings. | 13.65 default |
| Ranged | `enemy-ranged.png` | 0.947 | Pointed gunship, broad swept shoulders, twin raised forward cannon wells, cyan reactor, amber rear engine. Both cannon bores share aim. | 13.65 |
| Sniper | `enemy-sniper.png` | 0.488 | Narrow, long, high-aspect rail craft; single central barrel, purple lock signature and compact hull. Do not thicken it into a generic gunship. | 13.65 |
| Tank | `enemy-tank.png` | 1.160 | Heavy squat armored chassis, broad shoulder mass, twin forward cannons, cyan furnace and planted legs. Its large silhouette must match its slow durable role. | 17.5 |
| Charger | `enemy-charger.png` | 1.084 | Narrow forward ram, paired articulated claws and rear turbines. During windup claws fold toward the lane; during charge they extend in the locked direction. | 17.0 |
| Spitter | `enemy-spitter.png` | 0.722 | Pointed armored bio-gunship with paired acid reservoirs, vivid acid green, and a clear front attack axis. | 13.65 |
| Flyer | `enemy-flyer.png` | 1.727 | Broad crescent wing span, narrow central fuselage, visible turbine ends and cyan lift trail. Wing flap stays attached to the two hinges. | 13.86 |
| Engineer | `enemy-engineer.png` | 1.318 | Rounded repair mech with a plated brow, amber optic, two articulated pincers, and a green repair signature. | 14.7 |
| Swarm fighter | `enemy-swarm.png` | 1.043 | Small swept fighter with paired wing slashes and a warm red/orange eye. Keep its body compact and distinct from the larger Flyer. | 12.3 |
| Egg sac | No individual file; interim 3D asset in `models3d/enemies/egg_sac.rs` | Not measured | Low, anchored sac with a visible central egg/core, pink/red segmentation, and a readable hatch pulse. The Brood Matriarch artwork is the only current thematic reference. A dedicated artwork reference is missing. | 16.0 |

Regular enemy collision radii are the final values from `enemy_radius()` in `config.rs`: Tank 17.5, Charger 17.0, Egg sac 16.0, Engineer 14.7, Flyer 13.86, Sniper, Spitter, Ranged, Chaser and Bomber 13.65, and Swarm 12.3. Temporary elite modifiers change health and abilities, not model identity.

## Boss roster

Most bosses use `BOSS_RADIUS = 33.6`; selected bosses have role-specific radii in `enemy_radius()`. Their unique crown, wings, ring, weapon or core may extend beyond the gameplay body circle; that extension must be visually clear and must not be mistaken for an unseen larger hitbox. For Brood Matriarch, the wing membranes now spread 20% farther from their shoulder hinges to bring its broad wing silhouette closer to the 1.481 source-art width-to-height ratio. The wings remain non-colliding presentation geometry.

| Behavior | Reference artwork | Reference ratio | Primary silhouette / color identity | Required pose identity |
| --- | --- | ---: | --- | --- |
| Storm Sovereign (`boss_thunder`) | `boss-storm-sovereign.png` | 0.964 | Upright electrical sovereign; bright blue-white storm crown and controlled violet/cyan arcs. | Ring charge visibly gathers; teleport-out/in remains a discrete spatial move; lightning lanes read as separate warned spokes. |
| Prisma Overlord (`boss_laser`) | `boss-prisma-overlord.png` | 1.098 | Symmetric prism eye and distinct opened armor wings; cool cyan/purple planes with a controlled core. | Charge folds the wings; final wing fan opens before release and matches its five projectile lanes. |
| Forge Warden (`boss_trapmaster`) | `boss-forge-warden.png` | 1.248 | Furnace and heavy arm silhouette, copper/orange highlights with dark plate structure. | Arms load the spike tell; marks remain on the committed floor positions. |
| Brood Matriarch (`boss_swarmqueen`) | `boss-brood-matriarch.png` | 1.481 | Broad red/violet wing span, large body, egg/brood structures and warm core. | Brood, summon and volley poses stay separately identifiable; summon marks sit at their actual legal spawn targets. |
| Gorgon Juggernaut (`boss_brute`) | `boss-gorgon-juggernaut.png` | 1.518 | Wide armored bruiser with oversized forward mass, warm red/orange identity and heavy limbs. | Locked charge direction, impact pulse and short recovery must read through the whole body, including on inner arena boundaries. |
| Ocular Abyss (`boss_abyss_gaze`) | `boss-ocular-abyss.png` | 1.529 | Wide dark eye/void body, narrow cool emissive details and readable weapon appendages. | Radial/fan warnings only appear when matching damage is emitted; no decorative phantom pulse ring. |
| Origin Nexus (`boss_womb_core`) | `boss-origin-nexus.png` | 1.044 | Compact centered red-pink core with a broad outer organic/ring structure. | Pulse ring and paired warning/damage traps remain centered and atomically matched. |
| Eclipse Archon (`boss_eclipse_archon`) | `boss-eclipse-archon.png` | 1.094 | Dark event horizon inside separated violet crown armor, cyan-green corona and satellites. The central dark core must remain visible. | Crown/ring spread maps to locked charge/burst state; all volleys keep one safe gap aligned to the 3D model. |

The boss appearance table names the artwork that anchors each source-built mesh. It does not claim that every current polygon has been approved against the corresponding image in a final GPU capture.

## Palette and glow limits

| Family | Shell rule | Emissive rule |
| --- | --- | --- |
| Player | Rounded steel-blue / cyan shell with dark visor and warm small accents. | Cyan visor/engines and gold beacon remain discrete details; avoid filling the face with white light. |
| Regular enemy | Graphite or dark-metal structure plus one role-coded accent: amber, cyan, magenta, green, violet or coral. | Glow follows physical parts and remains subordinate to dark plate edges. Attack charge may brighten the actual muzzle/core. |
| Boss | Preserve each artwork's distinct large color family and armor breaks. | Core, ring and weapon sources remain separate draw elements; an attack glow may not replace the underlying hull. |
| Projectiles and explosions | Preserve a readable core/edge and role color against the arena. | Bloom and shockwaves stay separate from collision geometry and warning geometry. |

## Editing and review checklist

1. Compare the matching source artwork before editing any mesh.
2. Preserve its width/length and mass hierarchy before adding small detail.
3. Keep every attachment on the physical model and transform it with the same yaw/pitch/roll as the hull.
4. Confirm eight headings so the face may naturally disappear and attached parts stay aligned with the model through every turn.
5. Compare the model against its collision circle and grounded shadow at gameplay scale.
6. Inspect glow over dark geometry, final GPU blend, and reduced-motion pose only with an explicitly requested visual/game review.

## Current structure and remaining review

The character renderer is already split into `render/models3d/player.rs`, `render/models3d/enemies/` and `render/models3d/bosses/`, with shared projection and geometry helpers. Current presentation constants, world-scale helpers, and cached eight-heading preview-fit helpers live in `render/models3d/mod.rs`; the camera, scale application, and grounded shadows are in `render/world.rs`.

This pass raises ordinary enemy render scale from 1.30 to 1.43, raises most modeled bosses by 8% while keeping Storm Sovereign within its existing 40-unit reach target, widens Brood Matriarch's wings 20% around each hinge, and uniformly enlarges the player pod by 5.5%. Simulation hit radii were not changed here. The player retains its small, deliberate hurtbox. Offline sheets verify mesh rotation and silhouette construction, but final GPU blend, bloom, and on-screen scale still need a later visual review. Section 6 of `../plans/ENEMY_AI_PLAN.md` remains the render-state contract: rendering may read simulation state but must not write it.

## Source references

- Reference images: `assets/artwork/characters/`
- 3D geometry and articulation: `plouto_rs/src/render/models3d/`
- Enemy and boss draw scale, shadows and boss call site: `plouto_rs/src/render/world.rs`
- Player model: `plouto_rs/src/render/player_art.rs`
- Gameplay radius: `plouto_rs/src/sim/config.rs`
- Isometric heading and pose: `plouto_rs/src/render/world.rs`
- Planned render read contract: `docs/plans/ENEMY_AI_PLAN.md`, section 6
