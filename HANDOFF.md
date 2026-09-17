# force-jv880 — v0.9 handoff

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
  remains. This is an **accepted, known limitation for now**, matching
  force-maze's own long-standing tradeoff — a full fix needs an adaptive
  controller, already tried once in this project and reverted because
  live-tuning against a noisy backlog signal gave inconsistent results.
  Revisiting it properly needs a long, carefully-logged (not live-trial-
  and-error) measurement session — flagged, not attempted again yet.

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
