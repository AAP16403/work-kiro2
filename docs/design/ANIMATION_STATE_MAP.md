# Animation State Map

**Prepared:** 2026-11-16  
**Last checked against code: 2026-11-17**  
**Evidence:** Source inspection only (`plouto_rs/src/render/world.rs`, `render/models3d.rs`, `render/player_art.rs`, `sim/enemy.rs`, `sim/behaviors.rs`, `sim/bosses.rs`, `sim/step.rs`). The game was not launched and no tests were run in this pass. Spot checks covered the claims most likely to drift; the regular-enemy table was not checked line by line.

## Timing contract

- Gameplay poses consume the authoritative simulation state, not an independently maintained animation cooldown.
- Regular enemy animation time is `e.t`, which advances by `enemy_dt` each step (`sim/step.rs`). Boss articulation uses the same enemy clock. During Time Slow, attack telegraphs, their poses and enemy-local motion slow together.
- Reduced motion sets that clock to 0 for both regular enemies and bosses (`render/world.rs`, `et = if rm { 0.0 } else { e.t }`). Every time-driven sway, flap, orbit and pulse therefore stops. Windup values still come from simulation state, so telegraphs remain visible.
- `windup` is normalized from the active `EnemySubState` timer and its named duration (`enemy_windup_strength` in `render/world.rs`). Each floor warning uses the same locked target, heading or lane consumed by the attack resolution.
- Player hull, visor, eyes, antenna, side thrusters and exhaust are transformed by the same 3D heading and isometric camera. Facial details are culled when the face turns away; no face is drawn as a screen-space overlay.

## Player pod

| State | Model / detail response |
| --- | --- |
| Cruise | Slight 3D hover and restrained engine pulse driven by the pod's motion clock (`motion_t`). |
| Turn | Complete pod yaw follows player facing; the visor, beacon, side engines and rear engine rotate as one mesh. |
| Boost | Three physical exhaust tongues extend from the rear, lengths 7, 11 and 7 units; the central tongue is longest. Exhaust glow is brighter and warmer. |
| Hit / concern | Existing face expression and hull flash use player visual state; the worried face shows at 30% HP or less. Rear and side parts retain the same world transform. |
| Shield | A restrained outer ring, a faint fill, and an orbit arc indicate active shield without covering the hull. |
| Laser | Weapon state adds a small ring to the pod's physical center. |
| Reduced motion | Engine pulse, boost flicker, eye movement (gaze target fixed at zero) and shield pulse are frozen; heading and ability state remain visible. **Not frozen:** the shield orbit arc in `draw_player_pod` still advances with time. This does not match the other reduced-motion rules. It is a code item to decide, not a stated design choice. |

## Regular enemy states

| Enemy | Idle / traversal | Telegraph / committed attack | Recovery / role cue |
| --- | --- | --- | --- |
| Chaser | Its arrowhead follows velocity with a short turn blend and low pitch/roll. | Nose core brightens during the lunge windup and stays aligned to the committed lunge vector. | Lunge indicator clears when its actual windup/run state ends. |
| Bomber | Symmetric four-arm mine layer keeps a stable heading with its actual movement direction; central furnace strobe remains subdued. | Body core strobe accelerates and the amber floor ring grows around its locked blast center and full blast radius. | Fuse projectile and its own warning finish on the shared fuse clock. |
| Ranged | Pointed gunship tracks its target lane with a mild yaw blend. | Both cannon wells lift and draw back from the normalized charge value; muzzle light grows with the same progress. | Muzzle charge falls when windup ends and attack cooldown begins. |
| Sniper | Long rail craft tracks its actual aim vector. | Barrel extends and brightens with lock progress; floor reticle uses the locked point, and its color changes at lock. | Lock reticle disappears when the windup leaves the sniper state. |
| Tank | Planted chassis remains heavy; visual core stays cool. | Cannons recoil and muzzle charge grows from tank windup; brace vents and ring express the timed push. | Push ring fades from `push_t`; cannon recoil resets with windup. |
| Charger | Articulated claws and turbines follow heading. | Claws curl toward its locked lane, then reach forward during charge; thrust rises only in the charging state. | Recovery restores the claw pose without moving the already committed aim direction. |
| Spitter | Paired acid sacs breathe subtly. | Both reservoir bubbles rise and enlarge from normalized windup; the head marker remains attached to the model. | Acid core and floor warning end with the projectile launch state. |
| Flyer | Both wings flap around their physical hinges; lift engines respond to speed. | Nose light and attack marker brighten during the actual windup. | Wing cycle returns to idle; reduced motion holds a clear neutral wing pose. |
| Engineer | Two pincer arms sway around fixed shoulders. | Pincers lift and close from actual windup while the floor support radius charges at the exact selected destination. | Charge marker and arm pose clear after the repair shot is emitted. |
| Swarm fighter | Small wings follow its flock movement clock; orbit lane remains separate from facing. | Eye and body accents sharpen as its own swarm controller moves through encircle, surge telegraph, surge and regroup. | Same-subgroup formation supplies its destination; general enemy formations do not pull it out of the swarm lane. |
| Egg sac | Low anchored body uses a slow neutral pulse. | Core urgency and sac squash rise from hatch countdown (4.0 s in phase 0, 3.0 s after); exact legal summon positions use the boss AI's saved target list. | On hatch, the sac is marked dead and spawns three swarm fighters around its position, subject to the non-boss cap. The sac is also removed if its health reaches zero. |

## Boss poses and attack cues

Boss model functions read the live `EnemySubState`, phase, rage flag, locked heading and normalized windup. These are high-level art contracts, not extra gameplay timers.

| Boss | Distinct pose sequence |
| --- | --- |
| Storm Sovereign | Teleport-out → arrival → ring charge → strike. Storm lanes are visible before damage and fan out by phase. |
| Prisma Overlord | Beam charge → sweep; final phase folds the wings during warning, opens them for the matching five-lane fan, then recovers. |
| Forge Warden | Arms load during the spike-array telegraph; floor spike markers match the chosen pattern positions. |
| Brood Matriarch | Brood, swarm and volley telegraphs each have a different wing/forearm pose; summon indicators mark the exact legal, separated spawn points. |
| Gorgon Juggernaut | Locks a world direction, leans into charge, hits the boundary or target lane, then holds the impact pulse and recovery. A second rush goes back through a separate telegraph state. |
| Ocular Abyss | Aim and fan rails brighten during the real salvo; every visible ring or rail is matched to damage geometry. The non-damaging phantom radial cue is removed. |
| Origin Nexus | Core compresses toward the pulse; warning and damage rings share a committed location and are inserted atomically. |
| Eclipse Archon | Crown opens on charge/burst, then turns toward the locked direction; armor blades, orbit rings and safe-gap cue rotate as one world heading. |

Boss phase transitions cancel an unlaunched telegraph, clear its linked beam where applicable, reset the new phase with a brief recovery floor (0.35 s), and let launched hazards finish under their existing warning. Death removes hazards owned by that boss; surviving adds retain their own attacks.

## Current render integration

Today the render code reads `EnemySubState`, the per-role `e.ai` fields listed above, `e.t`, and `windup` derived from those. It does not read a single attack-phase value.

Character geometry is modularized under `render/models3d/player.rs`, `render/models3d/enemies/`, and `render/models3d/bosses/`. The regular-enemy and boss poses still read their named simulation substates and timers directly; rendering does not yet consume one shared `Enemy::attack_phase()` value. Keep the state inputs listed in this document consistent with the source. `../plans/ENEMY_AI_PLAN.md` records the broader current AI/render boundary. Render code may read simulation state for presentation, but must never write it.

## Review checklist

- Compare silhouettes at all eight headings with the relevant entry in `docs/design/CHARACTER_ART_SPECIFICATIONS.md`.
- Confirm the rendered face can disappear naturally, model attachments share the model transform, and projected mesh silhouettes remain stable across headings.
- Compare attack progress and floor geometry with the corresponding state timer and resolved damage location.
- Review reduced-motion poses with the same attack states; a static pose must still tell the player where damage will occur.
- Final GPU review, bloom/occlusion judgment and in-game animation review remain deferred until the user requests that review.
