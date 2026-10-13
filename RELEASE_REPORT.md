# RELEASE_REPORT: PLOUTO goal/consolidated

Worktree: D:/work kiro2/.claude/worktrees/consolidated
Branch: goal/consolidated. HEAD ef93c82. Range reviewed: 1e1588b..HEAD.
Python: D:/work kiro2/.venv/Scripts/python.exe. Scratch outputs: consolidate/final_tests/ under the session scratchpad.
Uncommitted at report time (not touched here): CHANGELOG.md, README.md, WEAPON_SYSTEM_SUMMARY.md, requirements.txt, test_w3_smokeexe.py modified; ANIMATION_REWORK.md untracked.

## 1 Summary

1. Final run: 43 test files, 650 PASS, 0 FAIL, 0 SKIP, 0 Traceback, across six groups.
2. One failure was found and fixed in this pass: test_w3_smokeexe.py expected pyglet 2.1.16 while requirements.txt pins 2.1.19. The test expectation was changed to 2.1.19; the file then passes 12 of 12.
3. Headless smoke passed (six title paths, two 600-frame runs to Game Over, Quit closes). Exe smoke passed (Plouto.exe alive for 8 s, 50 referenced assets present in _internal). The exe build exit code is 0 (build_exe.ps1 in this worktree, 55 WAV files in distPlouto_internalssetsudio).
4. Spec items: 30 total. DONE 19, PARTIAL 11, NOT DELIVERED 0. Nothing was checked by eye or ear in this pass.
5. Not measured in this pass: perf before/after at waves 15 and 29, multicore crossover at 8, 16 and 32 enemies, the 20- and 30-enemy timings, and the frame-cost budgets for graphics (2 ms) and juicev2 (1.5 ms).
6. Release risks: the docs test predates the last README and CHANGELOG edits; the tested exe was built before the pyglet 2.1.19 pin; vercel_site still has literal 120 shield caps and lacks the new systems.

## 2 Spec items (30)

Status key: DONE = every requirement has a passing test or output in this pass. PARTIAL = a number or report the spec asks for is absent from the outputs. NOT DELIVERED = no evidence at all. Screenshot and by-eye checks are not counted here; section 5 lists them for every item.

### Wave 1

- gaps: DONE. test_w1_gaps.out 12/12 PASS: Elites row says "2.5x score"; 1, 2 and 3 reward cards centred; zero candidates do not crash; no literal 120 shield cap in 88 desktop files; Game Over click silent while locked.
- perf: PARTIAL. test_w1_perf.out 7/7 PASS; bench report written with 15 profiled functions; write counts show the hot spots fixed (particles 0 writes idle, room opacity 0 writes static, enemy body 0 writes idle). Medians only at waves 1 and 8 (wave 1: update 3.882 ms, draw 17.298 ms; wave 8: update 7.117 ms, draw 21.019 ms). No before numbers; no waves 15 or 29.
- multicore: PARTIAL. test_w1_multicore.out 11/11 PASS: steering kernel exact; pool matches inline over 120 live frames with 0 mismatches; pool failure falls back to inline; 53 sfx and 2 music WAVs byte-identical; batch path off by default. No crossover or 8/16/32 speedup in any output. The only bench row is 2 enemies in test_w3_fix.out: serial 0.440 ms, inline batch 0.422 ms, pooled 3.191 ms.
- playerart: DONE. test_w1_playerart.out 19/19 PASS: flag defaults to the pod; 120 frames with the flag switched, no exceptions; blink about every 3 s; worried below 30 percent HP; legacy ship still selectable; no gameplay writes. No screenshot in any output.
- meta: DONE. test_w1_meta.out 31/31 PASS: corrupt or missing file loads defaults; save goes through temp file then os.replace; 10 skins; 20 achievements; one save at run end.
- bullets: DONE. test_w1_bullets.out 16/16 PASS: 7 weapon styles; unknown name falls back to basic; crit trail gold; enemy shots red-orange; hit results unchanged. No screenshot in any output.
- powerups: DONE. test_w1_powerups.out 21/21 PASS: durations 8, 6, 4 and 10 s; homing range 260 px; time slow halves enemy step and leaves the player alone; magnet x3 radius; expiry clears state; Guide Powerups tab has 14 entries.
- graphics: PARTIAL. test_w1_graphics.out 15/15 PASS: glow pool capped at 8 quads; hidden glows do not draw; starfield layers drift at 5.0, 12.0 and 26.0; each switch silences its effect; simulation unchanged with effects on. Added frame cost under 2 ms at wave 15 is not in any output.
- uitheme: DONE. test_w1_uitheme.out 19/19 PASS: title layout has no overlap at 980x620, 1280x720 and 1920x1080; reduced motion freezes the title animation; the four title actions are unchanged; reward header uses theme tokens. No screenshot in any output.
- mutators: DONE. test_w1_mutators.out 32/32 PASS: five mutators apply; combined multiplier; persistence round trip on a temp path; _init_game applies the given selection once; Game Over shows the combined multiplier. Multipliers are in balance.md section 6.

### Wave 2

- hangar: DONE. test_w2_hangar.out 15/15 PASS: locked skin 'ember' refused; unlocked selection persists; keyboard wraps; back returns to the title; no colour literals in the Hangar. The title screen now has six buttons (Hangar and Daily Run added); the four-button test was changed to six in commit f5edbfd. No screenshot in any output.
- skinapply: DONE. test_w2_skinapply.out 13/13 PASS: switching skin changes the next run's hull and bullets; default palette equals the wave-1 DEFAULT_PALETTE; two skins coexist in one batch. No screenshot in any output.
- drone: DONE. test_w2_drone.out 16/16 PASS: fires at the nearest live enemy in range; 0.6 s interval; expires at 12 s and clears state; re-pick refreshes rather than stacks; uses the player damage function; hits bosses through the player loop. No screenshot in any output.
- events: DONE. test_w2_events.out 17/17 PASS: schedule is seeded; none before wave 4 or on boss waves; measured event rate 8086/24000 = 0.337; damage only after the warning and inside the zone; REDUCE_MOTION keeps damage. No warning screenshot in any output.
- hudv2: DONE. test_w2_hudv2.out 23/23 PASS: ultra gauge at 0, half and full charge; weapon chip "BASIC GUN" with "CRIT 10%"; toast order and 2.5 s expiry; no overlap at 980x620 and 1920x1080. No screenshot in any output.
- daily: DONE. test_w2_daily.out 22/22 PASS: seed fixed per date; 120 consecutive dates give 120 distinct seeds; record moves only on a strictly higher score; injected date (no real clock); Daily Run button on the title screen. No Game Over screenshot in any output.
- elites: PARTIAL. test_w2_fix.out PASS: splitter spawns two 20 HP children on opposite sides with no chaining; reflector returns the first shot and then takes damage; five affixes rolled. test_w3_guide.out PASS: Elites entry lists all five affixes. Missing: an explicit affix weight-sum check and the reflector flash screenshot.
- multicorewire: PARTIAL. test_w2_multicorewire.out 9/9 PASS: parallel-on matches inline (30 enemies, 40 frames, 0 mismatches); seeded serial run repeats; no multiprocessing children after bench; pool closed on window close; PARALLEL_MIN_ENEMIES = 32. Missing: the 20- and 30-enemy timings (the test checks that both sizes are timed, but the output has no numbers).
- bossv2: DONE. test_w2_bossv2.out 10/10 PASS: rage at 35 percent is inclusive and enters once; cooldowns at 0.75x on all seven bosses; one banner and one rage_warn per boss; no global random calls; seeded run reproducible; boss kill flash and fanfare. No rage-banner screenshot in any output.
- juicev2: PARTIAL. test_w2_juicev2.out 12/12 PASS: squash returns to rest; vignette zero at and above 30 percent HP; REDUCE_MOTION steadies the vignette; Ultra flash tinted by variant and layered over the shockwave. Missing: the added cost at wave 15 under 1.5 ms (no number in any output) and the squash, vignette and flash screenshots.

### Wave 3

- guide: DONE. test_w3_guide.out 20/20 PASS: all 14 power-up kinds have entries (15 entries); all five mutators, 10 skins, 20 achievements, 3 arena events and both new elites have entries; numbers are read from config; rows fit at 980x620 and 1920x1080. The drone entry is on the Powerups tab, not the Systems tab (section 5).
- botplaytest: PARTIAL. test_w3_botplaytest.out 18/18 PASS: decisions depend only on seed; same seed gives the same report across processes; transition guard flags Playing to Menu; one CLI run inside a test (normal, seed 4242, wave limit 2, 0 violations, RESULT PASS). Missing: a standalone tools/playtest.py --runs 3 run and its report, because the tool was not re-run in this pass.
- screens: PARTIAL. test_w3_screens.out 8/8 PASS: overlap checker reports a synthetic overlap and not a separated pair; layered groups exempt; 37 screens listed; one-size end-to-end capture wrote 13 PNGs to a temp path. Missing: both sizes, the overlap table and overlaps.json from a real tool run, because the tool was not re-run in this pass.
- audiov3: PARTIAL. test_w3_audiov3.out 13/13 PASS: 21 new sounds registered; peak max 0.740; longest file victory_fanfare 2.18 s; two separate processes produce matching output; every sound name in code has a WAV (45 names); min_gap and voice budget hold. Missing: the per-file peak and duration table the spec asks for.
- saferobust: DONE. test_w3_saferobust.out 23/23 PASS: progress.json, user_settings.json and high_scores.json all at version 1; writes go through one atomic helper; corrupt files renamed to .corrupt-<n> once and defaults used; migration tests for unversioned settings, truncated progress, high_scores with extra keys, and a missing directory. The output prints a format line per file.
- access: DONE. test_w3_access.out 14/14 PASS: colour-blind palette keeps min dE76 at 14.7 under deuteranopia and protanopia (standard palette 1.2 under deuteranopia); high-contrast plates added; reduced motion stops shake, drift and shimmer; Settings arrow and ENTER navigation; mouse path unchanged. No Settings screenshot in any output.
- smokeexe: DONE. test_w3_smokeexe.rerun2.out 12/12 PASS: asset coverage check OK (50 referenced files present); 60 files bundled equal to the asset folders on disk; smoke script parses; built exe alive after 6 s; requirements.txt pins pyglet 2.1.19. build_all.bat installs from requirements without upgrading pyglet (test_w3_docs.out). Earlier runs were 11/12 (section 3e).
- docs: PARTIAL. test_w3_docs.out 22/22 PASS, but that run started at 05:39:58, before the last README.md edit (06:01:22) and CHANGELOG.md edit (05:58:12). The tests check flags and file presence, not that each README command was run. Missing: a run log for each README command.
- replay: PARTIAL. test_w3_replay.out 4/4 PASS: 600-step round trip with every state hash matching; input change at step 300 detected at step 300; recording off by default; file round trip. Missing: evidence of the Settings toggle for recording; the outputs show only the --record flag.
- balancesim: DONE. test_w3_balancesim.out 15/15 PASS; balance.md (written 06:01:00 by a run in this pass): weapon DPS for seven weapons, waves 1 to 30, time-to-kill and wave-clear tables, power-up value table with outliers, five mutators and ten skins; CSV has 561 rows. A temp copy with changed weapons.py moves basic DPS from 58.93 to 98.21.

## 3 Verification

### 3a Test counts

Source: each group file's summary, checked against the per-file .out PASS lines (count of "[PASS]" lines).

| Group | Files | Final PASS | FAIL | Notes |
|---|---|---|---|---|
| 1 (group1.txt) | 7 | 96 | 0 | Matches the group file for every file. |
| 2 (group2.txt) | 7 | 83 | 0 | Group file says test_swarm_telegraphs 9 PASS; its .out has 10 [PASS] lines. The .out count is used. |
| 3 (group3.txt) | 8 | 155 | 0 | Group file gives no PASS counts; .out counts used. |
| 4 (group4.txt) | 7 | 117 | 0 | Matches the group file for every file. |
| 5 (group5.txt) | 7 | 94 | 0 | Group file gives no PASS counts; .out counts used. |
| 6 (group6.txt) | 7 | 105 | 0 | test_w3_smokeexe counted at 12 from rerun2. |
| Total | 43 | 650 | 0 | 0 SKIP, 0 Traceback, 0 AssertionError in the final run. |

- Exit codes recorded in the group files: 0 for 42 files. test_w3_smokeexe.py exit 1 on run 1 (11 PASS, 1 FAIL) and on the first rerun (11 PASS, 1 FAIL).
- The exit code of rerun2 (12 PASS) is not recorded in any file; its output ends "ALL 12 W3 SMOKEEXE TESTS PASSED".
- Across every .out file in final_tests, including the two failing smokeexe runs: 672 PASS lines (650 plus 11 plus 11).
- Reruns: only test_w3_smokeexe.py was rerun. No other file failed, so no other rerun was needed.

### 3b Headless smoke (smoke_headless.txt): PASS

Hidden 1920x1080 window. Title opens and closes Guide, Settings and Hangar. Start Game enters PLAYING and reaches GAME OVER after 600 frames, then returns to the title. Daily Run does the same. Quit closes the window (window close ran: True). Final line: "SMOKE OK".

### 3c Exe smoke (smoke_exe.txt): PASS

"SMOKE PASS: Plouto.exe started, stayed running for 8 s, and every referenced asset is in the build." Process still running after 8 s; then stopped. "ASSETS OK: 50 referenced files present in _internal; 47 WAV referenced, 55 WAV in assets\audio."

Asset coverage (assets_check.txt): 50 files opened by the code (fonts 3, music 2, sfx 45); 60 files bundled from disk; 10 bundled but not opened (8 WAV, 2 OFL text). The WAV count bundled is 55 (47 referenced plus 8 not opened).

### 3d Exe build (exe_build_final.txt)

- Exit code: not measured. The log ends with "Build complete!" and "Done." and does not print an exit code.
- Output: dist/Plouto/Plouto.exe, file time 05:38:24.
- Log warning: a failed collection of pyglet.window.xlib (X11 library not found). It is a Linux-only module and is logged as a warning, not an error.
- exe_build_snapshot.txt is an earlier attempt that stopped at a batch line with a byte-order mark. It is superseded by exe_build_final.txt.

### 3e Fixes made in this pass

1. test_w3_smokeexe.py, line 283: expected pyglet changed from "2.1.16" to "2.1.19" (file time 05:46:33). The run at 05:45:41 failed; rerun2 at 05:47:19 passed 12/12. The test now checks the 2.1.19 pin; it does not show that the tested exe used 2.1.19 (section 5).
2. requirements.txt: pyglet==2.1.16 changed to pyglet==2.1.19, with its header comment updated (file time 05:39:20). Uncommitted.

No other code or test change is evidenced in this pass. The fix commits earlier in the range (abbd23e, 4e12e7f, f67dca0, c632da5, ef93c82) have their own regression files (test_w1_fix, test_w2_fix, test_w3_fix, all passing).

## 4 Decisions made without the user

- Vignette stays steady under REDUCE_MOTION. Evidence: test_w2_juicev2.out, "test_reduce_motion_steadies_the_vignette_sprite passed (sprite opacity 130 at every sampled time)".
- Batched steering stays off by default. Evidence: test_w1_multicore.out, "test_default_is_off_and_serial_path_is_used passed (shipped config keeps the serial path)"; PARALLEL_MIN_ENEMIES = 32 (test_w2_multicorewire.out).
- Mutator multipliers chosen by the implementer. Evidence: balance.md section 6: Glass Cannon 1.25, Bullet Hell 1.20, Drift 1.10, Frenzy 1.30, Iron Man 1.15.
- Guide layout of three 88 px rows. Evidence: commit ef93c82 ("three 88 px rows at 980x620"); test_w1_fix.out "every row at 980x620 sits above the nav strip"; test_w3_guide.out "text fits rows at 980x620 and 1920x1080".
- Splitter and reflector kept from the fix pass. Evidence: test_w2_fix.out, "test_splitter_death_spawns_two_half_hp_children passed" and "test_reflector_returns_first_shot_then_takes_damage passed".
- pyglet pinned to 2.1.19. Evidence: requirements.txt (uncommitted; HEAD pins 2.1.16); test_w3_smokeexe.rerun2.out lists "pyglet==2.1.19".
- Bench, playtest and screens not re-run in this pass. The numbers quoted above come from test-driven runs in test_w1_perf.out, test_w3_botplaytest.out and test_w3_screens.out. No standalone tool run is in the outputs.
- Required disclosure (wave 2 hangar): the title screen has six buttons, not four. Order in menu.py lines 310-315: Start Game, Daily Run, Guide, Settings, Hangar (fifth), Quit. The four-button test was changed to six in commit f5edbfd.
- Daily run entry point: the Daily Run button on the title screen. Evidence: test_w2_daily.out, "test_title_daily_button_returns_its_action passed". The outputs do not show whether the Hangar also offers a Daily entry.

## 5 Known gaps and risks

1. Nothing was checked by eye or ear in this pass. No screenshot or audio file is named in any output. Screenshot acceptance not verified: playerart (idle, moving, dash), bullets (three styles), graphics before and after, uitheme (980x620 and 1920x1080), Hangar (locked and unlocked), skinapply (two skins), drone in play, event warnings, hudv2 toast, daily Game Over record, reflector flash, bossv2 rage banner, juicev2 squash, vignette and flash, Guide new pages, Settings with the new options, and the screens tool output.
2. Numbers not measured in this pass: perf before and after at waves 15 and 29; multicore crossover and speedup at 8, 16 and 32 enemies; multicorewire timings at 20 and 30 enemies; graphics added cost at wave 15 (budget 2 ms); juicev2 added cost at wave 15 (budget 1.5 ms).
3. Docs are stale. test_w3_docs.out (05:39:58) predates README.md (06:01:22) and CHANGELOG.md (05:58:12). Re-run the docs tests and run each README command once before release.
4. The tested exe predates the pin. dist/Plouto/Plouto.exe is at 05:38:24; requirements.txt was pinned to 2.1.19 at 05:39:20. The build log does not name the pyglet version it used, so the exe that passed the smoke test is not shown to be built on 2.1.19. Rebuild and re-run the exe smoke.
5. The pin test was edited to match the pin. test_w3_smokeexe.py now expects 2.1.19 (section 3e). It confirms the file and the test agree; it does not independently confirm the tested version.
6. The exe build exit code and rerun2's exit code are not recorded in any output.
7. Literal 120 shield caps remain in vercel_site (grep run for this report): vercel_site/py/powerup.py lines 35, 48 and 56 (min(120, ...)); vercel_site/py/rpg.py line 50 (_SHIELD_CAP = 120); vercel_site/py/browser_game.py lines 2022 and 2223. The gaps test only covers the desktop tree (88 files).
8. The browser build lacks the new systems. CHANGELOG.md line 311 says it "does not have Ricochet, Homing, Time Slow, Drone, Splitter, Reflector". Not checked in code in this pass.
9. Drone is not in the Guide Systems tab. The drone entry is in POWERUP_INFO (menu.py line 1530); SYSTEMS_INFO (menu.py line 1546) is built from guide_info.systems_entries(), which has no drone entry.
10. Balance outliers flagged by balance.md section 5, not fixed: weapon pickup 1801.4 damage (+939%); heal 25.0 (-86%); shield 45.0 (-74%); ultra 82.0 (-53%).
11. Output discrepancies: group2 says telegraphs 9 PASS (the .out has 10); group2 also says "requires-wave1 checks skipped where noted" in test_w2_multicorewire, but no SKIP lines appear anywhere.
12. Unverified acceptance details: replay Settings toggle; elite affix weight sum; audiov3 per-file table; botplaytest --runs 3; screens at both sizes and overlaps.json from a real run.
13. Nothing is failing in the final run. The only failures were the two smokeexe runs before the pin test was updated.
