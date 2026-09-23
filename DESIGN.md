# Design notes

## How it works

```
Mockba JV880:In (virtual MIDI port, notes + CC)
        │
        ▼
jv_host  ──renders──▶  jv880_plugin.cpp + mcu.cpp/mcu_opcodes.cpp/pcm.cpp
        │               (Schwung's plugin API v2 wrapper + DSP core)
        ▼  (float32 stereo, shared-memory ring: forceAudioInject.h)
forceAudioJack.so  (LD_PRELOAD'd into /usr/bin/MPC)
        │  interposes snd_pcm_readi - mixes the ring's audio into whatever
        │  MPC reads from its capture device
        ▼
Audio-In track on the Force
```

`jv_host` is a standalone process playing the role Move's chain host plays
for `jv880_plugin.cpp` (see `src/jv_host.cpp`'s header comment) — same
porting pattern `force-acid`/`force-maze` use: RtMidi in, a timer thread
standing in for the SPI audio callback, its render output going into a
shared-memory ring.

Unlike `maze_voice.c` (which force-maze links completely verbatim),
`jv880_plugin.cpp` is Move's own host-integration layer, not a clean
"DSP core" — it's ~5000 lines including genuine reusable business logic
(patch/param/performance mapping, NVRAM layout) *and* Move-specific
real-time-thread plumbing. It's linked directly (like `maze_voice.c` is)
rather than reimplemented from scratch, but with two deliberate,
in-place-documented exceptions: both internal `SCHED_FIFO` requests removed,
and one AArch64-only NEON intrinsic replaced (see below). Both edits are
marked in-place with a `MockbaMod/Force port` comment.

`forceAudioJack.so` is the general-purpose audio-injection mechanism this
repo depends on rather than bundling — see
[`force-audio-jack`](https://github.com/sd88me/force-audio-jack) — deployed
as its own standalone MockbaMod addon (`ForceAudioJack`), so several voice
addons can share one tap.

## Feasibility

Measured directly on the Force (ARMv7, Cortex-A17 quad-core @ 1.8GHz,
Rockchip): `tools/render_test` (upstream's own headless benchmark,
cross-compiled for ARMv7 via Docker/QEMU bookworm) against real ROMs,
patch 0, melody sequence, 10s render: **2.81x real-time** (native x86_64
dev-machine reference: 13.83x — not predictive of the Force, included only
as a sanity check that the interpreter path itself isn't broken).

Compare to the abandoned Osirus (Virus/Gearmulator) attempt: that port
never got a working ARMv7 binary at all (a real link failure,
`JitOps::decode_cccc` undefined — Gearmulator's JIT only supports x64/
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

Two options were considered for the Force port: dropping `CAP_SYS_NICE` at
shim startup and relying on the existing fallback paths to fail closed, or
removing both call sites directly. The capability-drop route was rejected —
only one of the two call sites was fully read and confirmed to degrade
safely; the other involves more intricate priority-inheritance logic that
wasn't independently verified to behave safely if the initial request never
succeeds, and this device has a confirmed, documented incident (MockbaMod's
own `gotchas.md`) where a background render thread requesting real-time
scheduling caused pads/buttons to go unresponsive and WiFi to drop, with
clean-looking diagnostics right up until it happened — and this process runs
as root here, so `CAP_SYS_NICE` is available and a bare "request refused"
fallback isn't a real guarantee. Both `SCHED_FIFO` requests are removed
directly instead, fully verifiable by inspection rather than by trusting an
assumed fallback path. Both edits are marked in `src/jv880_plugin.cpp` with
a `MockbaMod/Force port` comment referencing this file.

## NEON portability fix

`resampler_fixed.h`'s NEON path (guarded by `__ARM_NEON`, with a portable
scalar fallback for anything else) used `vaddvq_f32` for a horizontal sum
across a `float32x4_t` — an AArch64-only intrinsic. `__ARM_NEON` is defined
on ARMv7 NEON too, so this path compiled but failed to *link* on ARMv7
(confirmed via a real cross-build attempt). Replaced with the portable
`vget_low_f32`/`vget_high_f32`/`vadd_f32`/`vpadd_f32` pairwise-add sequence,
which is part of the common NEON intrinsic set on both ARMv7 and AArch64 —
same SIMD path, same performance characteristics, just implemented with
instructions that exist on both architectures. A pure portability bug fix,
unrelated to the Force port's own design decisions; Move's own target
(aarch64) never exercised the broken path.

## Toolchain: bookworm, not stretch

This project's other ports (`force-acid`, `force-maze`) use
`arm32v7/debian:stretch` under QEMU. This port uses `debian:bookworm`
instead, after checking the live Force's actual library ceiling directly
over SSH (`strings /lib/libc.so.6` / `strings
/usr/lib/libstdc++.so.6.0.32`): **glibc 2.39 / GLIBCXX 3.4.32** — far newer
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
equivalent — Mini-JV's `chain_params` includes full per-tone metadata for
all 4 tones plus part/performance levels, and empirically exceeded a 16KB
buffer. Sized to 128KB, generously above the observed need.

## ROM loading is asynchronous

Unlike `maze_voice.c` (synchronous), `jv880_plugin.cpp`'s `create_instance`
returns immediately and does ROM/patch loading on its own background thread
(`v2_load_thread_func`). `render_block`/`on_midi` are already guarded to
no-op until that finishes; `jv_host` polls `get_param(inst,
"loading_complete", ...)` (bounded to ~5s) before fetching `chain_params`,
to avoid racing that thread.

## Web panel engine start/stop

Following `force-acid/web/server.py`'s pattern (not `force-maze`'s, which
has no such button): `web/server.py` has `engine_start()`/`engine_stop()`/
`engine_present()`, a `/engine` POST endpoint, and a small self-contained
"Engine: [status] [Start] [Stop]" bar inserted as a sibling of
`web_ui.html`'s own `<div id="app">` (marked in-place as a MockbaMod/Force
port addition, not part of upstream schwung-jv880 — Move's own host manages
plugin lifecycle invisibly, the Force needs an explicit control since
jv_host is a separate OS process). Does not touch any of the vendored
knob/wire-math markup.

## Known limitations

- **ROM version.** Only JV-880 firmware **v1.0.0** works; v1.0.1 does not.
  `jv880_nvram.bin` is optional (the engine falls back to a zeroed NVRAM
  buffer and persists it itself once you save a patch/performance) — the
  four other ROM files (rom1, rom2, waverom1, waverom2) are required.
- **Web panel port collision (resolved).** The web panel was originally
  going to use 8305 (the next slot after force-acid's 8303/force-maze's
  8304), but a fourth addon already installed on the live device,
  `ForceMazeSeq`, was already listening there (`OSError: [Errno 98] Address
  already in use`, confirmed via `netstat -tnl` on the actual target
  device). Moved to **8306**, confirmed free. Lesson for future ports:
  check the live device's actual listening ports, not just the ports known
  from sibling repos on disk.
- **`/describe` truncation at 8192 bytes (resolved).** `web/server.py`'s
  `ctrl_request()` originally did a single `s.recv(8192)` — fine for
  force-maze/force-acid's much smaller `chain_params`, but Mini-JV's
  (>40KB) silently truncated mid-JSON. `jv_host` closes the control
  connection after every response (see `jv_host.cpp`'s `ctrl_server_loop`),
  so the fix loops `recv()` until EOF instead of trusting one call to
  return everything.
- **Mix-slot collision with force-maze (resolved).** `forceAudioJack.log`
  on the live device showed slot 0 already repeatedly used by force-maze's
  own `maze_host` (its default too). `jv_host`'s own compiled-in default is
  still 0 (fine for a standalone invocation), but `web/server.py`'s
  `engine_start()` and `addon/NSMODULE.json`'s Modules-page arguments now
  explicitly pass `--mix-slot 1`, so the two voices can run simultaneously
  without fighting over the same shared-memory segment name.
- **`.xtk` Q-Link template unverified on a physical touchscreen.** Generated
  and structurally correct, but not yet confirmed rendering correctly on
  real Force hardware (same open caveat `force-acid`/`force-maze` have).
- **Real audible sound quality and patch behaviour not fully verified.**
  On-device testing confirmed the data path and process health (ROM/patch
  loading, MIDI note round-trips, param sets, stable render-thread
  diagnostics with no ring drops), but not a full listening review across
  patches and expansion cards.
