# force-jv880 — v0.9 handoff

## UPDATE 2026-09-17: RATE_CORRECTION measured correct — crackle's cause is still open

Ran a real 20-minute unattended measurement on the live device (current
production binary, untouched, engine idle the whole time -- no notes
played) with a liveness check every 30s and the full 5s backlog log
pulled afterward, to replace guessing from short live spot checks.
Linear-fit result on the post-transient data (first 90s excluded):
**+0.1ppm residual drift** -- essentially zero, on top of the already-
deployed ~1021ppm `RATE_CORRECTION`. No startup transient either: backlog
started around ~150 frames and stayed there the entire 20 minutes (this
project doesn't have force-dx7's ~15-20 minute startup-decay behavior --
see its own HANDOFF.md, same measurement session).

**This rules out RATE_CORRECTION miscalibration as the residual "vinyl
crackle" cause** described below -- the constant is correct, confirmed by
measurement, not just re-assumed. Since this test ran fully idle (no MIDI
input at all) and stayed rock-stable, the crackle is more likely tied to
something that only shows up under actual note-triggered load (voice
allocation, envelope computation spikes, etc.) than to steady-state clock
drift. Any future investigation should reproduce it live while actually
playing notes/patches, not during an idle soak.

## What's done and verified
- Full engine: mcu.cpp/mcu_opcodes.cpp/pcm.cpp vendored verbatim.
  jv880_plugin.cpp vendored with two documented edits: both `SCHED_FIFO`
  requests removed, one AArch64-only NEON intrinsic bug fixed for ARMv7.
  One added get_param key: `patch_list` (bulk patch names, wasn't exposed
  upstream) and `ring_diag` (underrun_count/min_buffer_level, added during
  the crackle investigation below).
- Host shim, ForceAudioIn integration (mix-slot 1, deliberately not 0 —
  that's force-maze's default), RtMidi, control socket.
- Web UI: full chain_params exposed (148 params — every DX7-... no wait,
  JV-880's own full per-tone/part editing), bank (ROM expansion) + patch
  browsing with real names, engine start/stop button.
- `.xtk` Q-Link template generated (14 knobs) — NOT yet checked on a real
  screen.
- Clock-drift wobble/crackle: `RATE_CORRECTION` fix applied (same constant
  proven in force-maze, ~1000ppm compensation) — user confirmed this
  helped but a residual "vinyl crackle" (occasional backlog-trim clicks)
  remains. **2026-09-17: the long measurement session this note asked for
  has now happened (see UPDATE at top of this file)** — `RATE_CORRECTION`
  itself is confirmed correct (+0.1ppm residual over 20 idle minutes), so
  an adaptive controller for clock drift isn't the fix needed here. The
  crackle's real cause is still open; next step is reproducing it under
  actual note/patch load, not idle drift.

## Outstanding work for v1.0 (not yet done)
- **Web UI sync bug**: knobs don't refresh when switching patches via the
  dropdown (same bug/likely same root cause as force-dx7 — worth fixing
  both together). Need a "reseed everything after patch change" call.
- **nodeServer integration not yet applied**: `nodeserver-integration/`
  has the redirect module + README instructions ready, but nobody has
  actually copied `forcejv880.js` into a live nodeServer install or added
  the `ENDPOINTS.js` entry yet.
- Real audible patch-quality review beyond spot-checking.
- `.xtk` template never confirmed rendering correctly on the physical
  touchscreen (same open item as every port in this project).
- Deeper clock-drift fix (see above) — parked, not a quick follow-up.

## New naming-convention requests (cross-project, see also force-dx7)
- Rename this addon's virtual MIDI port from `Mockba JV880:In` to
  `JV880 In (Mockba)` — change in `jv_host.cpp`'s `client` default / RtMidi
  port name.
- On nodeServer, wherever this addon's name is displayed (NSMODULE.json's
  `NAME`, the home-page ENDPOINTS.js entry's `NAME`), drop the leading
  "Force" — should read "JV-880", not "Force JV-880". Scope of this rename
  across the OTHER addons (acid/maze/maze-seq) wasn't explicitly confirmed
  — check with the user before renaming those too.
