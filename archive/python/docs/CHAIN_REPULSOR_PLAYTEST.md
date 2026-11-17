# Chain Lightning and Repulsor: playtest checklist

Build: `build\staging_dist\Plouto\Plouto.exe` (from `main` at 538f746). Each step says what to expect.
Note the wave and the HUD status line, then tick the box or write what you saw.

## Chain Lightning

- [ ] **Pickup.** Find the Chain pickup (a zigzag ring of dots with a `Z` glyph). Picking it up shows
      a chain timer on the HUD, about 8 seconds.
- [ ] **Arc on a bullet kill.** With enemies within about 160 world units, kill one with a normal shot.
      A bright jagged arc runs from the dead enemy to the nearest other enemy in range, and fades in about 0.2 s.
- [ ] **Damage.** That neighbour loses about 30% of your damage, rounded half up (damage 10 gives 3).
- [ ] **Chain through a pack.** Kill the neighbour too: another arc goes out. An enemy this chain has already
      hit is never hit again by it.
- [ ] **Other kill types.** Kill an enemy with the laser, the vortex or a ram. Each one should throw an arc too.
- [ ] **Refresh.** Pick up a second Chain while the timer runs. It resets to about 8 seconds, with no stacking.
- [ ] **Expiry.** Let the timer run out. Kills after that throw no arcs.
- [ ] **Reduced motion** (Settings). The arc shape holds still, and it still fades.

## Repulsor

- [ ] **Shockwave.** Pick up a Repulsor while it is ready. The shockwave fires on the next frame: a ring grows out
      from the ship, and enemy bullets within about 220 px are pushed outward. Slow bullets, under 150 px/s, are removed.
- [ ] **Stun.** Enemies within 220 px freeze for 1.5 seconds: no movement, no shooting, with dust puffs. Then they resume.
- [ ] **Cooldown.** The HUD status line counts down about 12 seconds (e.g. `Repulsor 7s`).
- [ ] **Stored charge.** Pick up a second Repulsor during the cooldown. It must not fire early. The status
      line shows the charge (e.g. `Repulsor 7s x2`). When the cooldown ends, the stored charge fires.
- [ ] **Charge cap.** Pick up three during one cooldown. Only two charges are kept (`x2`).
- [ ] **Stunned contact.** Let a stunned enemy (not a boss) touch you. It should not deal contact damage.
- [ ] **Reduced motion.** The ring holds its full size instead of growing, and no dust is drawn.

## Report back

For anything that does not match, write:

- the wave and the time since the run started,
- what you expected, and what you saw,
- whether you were on reduced motion.
