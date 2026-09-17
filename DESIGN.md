# Design notes

## Feasibility

Measured directly on the Force (armv7, Cortex-A17 quad-core @ 1.8GHz,
Rockchip): `tools/render_test` (upstream's own headless benchmark, cross-compiled
for armv7 via Docker/QEMU bookworm) against real ROMs, patch 0, melody
sequence, 10s render: **2.81x real-time** (native x86_64 dev-machine
reference: 13.83x - not predictive of the Force, included only as a
sanity check that the interpreter path itself isn't broken).

Compare to the abandoned Osirus (Virus/Gearmulator) attempt: that port
never got a working armv7 binary at all (a real link failure,
`JitOps::decode_cccc` undefined - Gearmulator's JIT only supports x64/
aarch64, and the `Jit` class is unconditionally compiled into `DSP` even on
architectures where it's never called). Mini-JV has no JIT dependency of
any kind, so this class of problem doesn't apply.

## SCHED_FIFO removal

`jv880_plugin.cpp` (vendored from schwung-jv880) makes two explicit
`SCHED_FIFO` requests as part of its own threading design:

1. Its background "emu thread" (the one doing the actual MCU stepping) is
   created via a `pthread_attr_t` requesting `SCHED_FIFO` at
   `JV880_EMU_RT_PRIORITY`, with a fallback to a plain `pthread_create` if
   refused.
2. That same thread's setup function (`v2_emu_thread_setup`) separately
   requests `SCHED_FIFO` priority 45 on itself, again with a
   log-and-continue fallback if refused.

Two options were considered for the Force port:

- **Drop `CAP_SYS_NICE` at shim startup**, relying on the existing
  fallback paths to fail closed. Rejected: only one of the two call sites
  (the priority-45 one) was fully read and confirmed to degrade safely;
  the other involves more intricate priority-inheritance logic (a thread
  created from `create_instance`, which itself may be running with
  inherited real-time priority from Move's own SPI callback) that wasn't
  independently verified to behave safely if the initial request never
  succeeds. Given this device's own confirmed incident history with
  `SCHED_FIFO` (see MockbaMod's `gotchas.md`), relying on unverified
  fallback behavior wasn't acceptable.
- **Remove both call sites directly** (the option actually taken). Requires
  reading and understanding the code being changed either way, so it isn't
  more work than making the capability-drop trick actually correct - and
  it's fully verifiable by inspection rather than by trusting an assumed
  fallback path.

Both edits are marked in `src/jv880_plugin.cpp` with a `MockbaMod/Force
port` comment explaining why, referencing this file.

## NEON portability fix

`resampler_fixed.h`'s NEON path (guarded by `__ARM_NEON`, with a portable
scalar fallback for anything else) used `vaddvq_f32` for a horizontal sum
across a `float32x4_t` - an AArch64-only intrinsic. `__ARM_NEON` is defined
on ARMv7 NEON too, so this compiled-selected path but failed to *link* on
armv7 (confirmed via a real cross-build attempt). Replaced with the
portable `vget_low_f32`/`vget_high_f32`/`vadd_f32`/`vpadd_f32` pairwise-add
sequence, which is part of the common NEON intrinsic set on both ARMv7 and
AArch64 - same SIMD path, same performance characteristics, just
implemented with instructions that exist on both architectures. This is a
pure portability bug fix, unrelated to the Force port's own design
decisions; Move's own target (aarch64) never exercised the broken path.

## Toolchain: bookworm, not stretch

This project's other ports (`force-acid`, `force-maze`) use
`arm32v7/debian:stretch` under QEMU. This port uses `debian:bookworm`
instead, after checking the live Force's actual library ceiling directly
over SSH (`strings /lib/libc.so.6` / `strings
/usr/lib/libstdc++.so.6.0.32`): **glibc 2.39 / GLIBCXX 3.4.32** - far newer
than stretch's glibc 2.24, and comfortably clearing bookworm's own (glibc
2.36). This device's firmware has moved on since the stretch convention was
established for the other ports; bookworm's g++ 12 / cmake 3.25 were also
needed here (stretch ships g++ 6.3 / cmake 3.7.2, too old for this
codebase's C++17 use and CMake requirements in the one avenue explored
before settling on a plain-gcc build with no CMake at all). Worth
re-checking the device's real ceiling before assuming either base image for
a future port, rather than defaulting to whichever one an earlier port used.

## chain_params buffer size

`jv_host`'s one-time startup fetch of `chain_params` (for the web panel's
`/describe`) needs a much larger buffer than force-maze/force-acid's
equivalent - Mini-JV's `chain_params` includes full per-tone metadata for
all 4 tones plus part/performance levels, and empirically exceeded a 16KB
buffer (silently returned nothing rather than truncating - caught by a
local QEMU smoke test against real ROMs before ever touching the live
device). Sized to 128KB, generously above the observed need.

## ROM loading is asynchronous - a real race, caught locally

Unlike `maze_voice.c` (synchronous), `jv880_plugin.cpp`'s
`create_instance` returns immediately and does ROM/patch loading on its own
background thread (`v2_load_thread_func`). `render_block`/`on_midi` are
already guarded to no-op until that finishes, but `jv_host`'s original
one-shot `chain_params` fetch immediately after `create_instance` raced
that thread and always lost, in the same local smoke test that caught the
buffer-size issue above. Fixed by polling `get_param(inst,
"loading_complete", ...)` (bounded to ~5s) before fetching `chain_params`.

## Web panel engine start/stop (added after initial local verification)

Following `force-acid/web/server.py`'s pattern (not `force-maze`'s, which
has no such button): added `engine_start()`/`engine_stop()`/`engine_present()`
to `web/server.py`, a `/engine` POST endpoint, and a small self-contained
"Engine: [status] [Start] [Stop]" bar inserted as a sibling of `web_ui.html`'s
own `<div id="app">` (marked in-place as a MockbaMod/Force port addition,
not part of upstream schwung-jv880 - Move's own host manages plugin
lifecycle invisibly, the Force needs an explicit control since jv_host is a
separate OS process). Does not touch any of the vendored knob/wire-math
markup.

## On-device deployment - three more real bugs found and fixed

Deploying and testing on the actual Force (not just QEMU) surfaced three
issues no amount of local/QEMU testing would have caught:

1. **Web panel port collision.** Picked 8306... no, initially picked 8305
   (next slot after force-acid's 8303/force-maze's 8304, the only two ports
   visible from this dev machine's own checkout) - but a fourth existing
   addon on the live device, `ForceMazeSeq`, was already listening on 8305
   (confirmed via `netstat -tnl` after the web panel crashed with `OSError:
   [Errno 98] Address already in use`). Moved to **8306**, confirmed free.
   Lesson: `netstat -tnl` on the actual target device before picking a port
   number, not just a grep of the ports known from local sibling repos -
   sibling repos on disk don't reflect every addon actually installed.
2. **`/describe` truncated at exactly 8192 bytes.** `web/server.py`'s
   `ctrl_request()` did a single `s.recv(8192)` - fine for force-maze/
   force-acid's much smaller `chain_params`, but Mini-JV's (>40KB) silently
   truncated mid-JSON. jv_host closes the control connection after every
   response (see `jv_host.cpp`'s `ctrl_server_loop`), so the fix is to loop
   `recv()` until EOF rather than trust one call to return everything.
3. **Mix-slot collision risk.** `forceAudioIn.log` on the live device showed
   slot 0 repeatedly used by `force-maze`'s own `maze_host` (its default
   too). `jv_host`'s own compiled-in default is still 0 (fine for a
   standalone invocation), but `web/server.py`'s `engine_start()` and
   `addon/NSMODULE.json`'s Modules-page arguments now explicitly pass
   `--mix-slot 1`, so the two voices can run simultaneously without
   fighting over the same shared-memory segment name.

Also fixed along the way: `engine_start()` was discarding jv_host's stdout/
stderr to `/dev/null`, even though `manage.sh`'s own status text already
promised a log at `/tmp/jv_host.log` - now actually writes there.

## Status - on-device verified

Deployed and fully verified on the live Force (192.168.1.187):
`manage.sh ENABLE` for both the engine and web panel addons, ROM files in
place, engine started via the new web panel button's backend
(`POST /engine {"action":"start"}`), confirmed: real ROM/patch-cache
loading, real ALSA virtual MIDI port (`Mockba JV880:In`) registered,
`forceAudioIn.so` attached to `/forceAudioInject1` with no collision, a
`/note` trigger and a `/param` set both round-tripped `ok`, and the render
thread's own periodic diagnostics are healthy (max wake gap ~4ms, zero ring
drops, stable ~100-165 frame backlog over 15,000+ wakes).

Not yet checked: whether the `.xtk` template actually renders correctly on
the physical Force touchscreen (same open caveat `force-acid`/`force-maze`
have - needs someone to load it and look) and any judgment on real audible
sound quality/patch behavior (this session verified the data path and
process health, not what it actually sounds like).
