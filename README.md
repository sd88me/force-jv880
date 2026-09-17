# force-jv880

Port of [`schwung-jv880`](https://github.com/charlesvestal/schwung-jv880)'s
**Mini-JV** — a Roland JV-880 PCM rompler emulation (based on
[mini-jv880](https://github.com/giulioz/mini-jv880)/
[Nuked-SC55](https://github.com/nukeykt/Nuked-SC55)), originally a native DSP
synth module for Ableton Move — to the **Akai Force** running
[MockbaMod](https://github.com/MockbaTheBorg/MockbaMod).

Like [`force-maze`](https://github.com/sd88me/force-maze), this is a real
**audio DSP synth**: it renders actual samples and mixes them into what the
Force's own app reads from its audio-in capture device, so the voice comes
out on a normal Audio-In track.

## Why JV-880 and not Osirus (Virus)

This project first attempted porting `schwung-virus`'s **Osirus** module
(Gearmulator's DSP56300 JIT emulator running real Virus firmware). That
port is **not viable on the Force**: Gearmulator's JIT compiler only has
native codegen backends for x64 and aarch64, the Force is 32-bit armv7, and
the `Jit` class is an unconditional member of `DSP` — even code paths that
would never execute on an unsupported architecture still have to link,
which they don't (confirmed via a real, reproduced link failure). Fixing
that would mean patching the vendored Gearmulator library's own class
structure, not just writing a host shim, and even then real-time
performance on the Force's weaker Cortex-A17 was an open, likely-unfavorable
question (Gearmulator's own docs say even *JIT-compiled* execution on the
Move's faster Cortex-A72 barely holds real-time for the lightest model).

Mini-JV has no such problem: it's a plain, portable C++ interpreter (an
H8/300 MCU emulator + PCM rendering), no JIT anywhere, and the upstream
README already reports ~38% CPU on Move's own CM4 — real headroom rather
than a JIT-dependent margin. Measured directly on this Force
(`tools/render_test`, cross-compiled for armv7, run on-device against real
ROMs): **2.81x real-time**.

## How it works

```
Mockba JV880:In (virtual MIDI port, notes + CC)
        │
        ▼
jv_host  ──renders──▶  jv880_plugin.cpp + mcu.cpp/mcu_opcodes.cpp/pcm.cpp
        │               (Schwung's plugin API v2 wrapper + DSP core)
        ▼  (float32 stereo, shared-memory ring: forceAudioInject.h)
forceAudioIn.so  (LD_PRELOAD'd into /usr/bin/MPC)
        │  interposes snd_pcm_readi - mixes the ring's audio into whatever
        │  MPC reads from its capture device
        ▼
Audio-In track on the Force
```

`jv_host` is a standalone process playing the role Move's chain host plays
for `jv880_plugin.cpp` (see `src/jv_host.cpp`'s header comment) - same
porting pattern `force-acid`/`force-maze` use: RtMidi in, a timer thread
standing in for the SPI audio callback, its render output going into a
shared-memory ring.

Unlike `maze_voice.c` (which force-maze links completely verbatim),
`jv880_plugin.cpp` is Move's own host-integration layer, not a clean
"DSP core" — it's ~5000 lines including genuine reusable business logic
(patch/param/performance mapping, NVRAM layout) *and* Move-specific
real-time-thread plumbing. It's linked directly (like `maze_voice.c` is)
rather than reimplemented from scratch, but with **two deliberate,
in-place-documented exceptions**:

1. **Both of its internal `SCHED_FIFO` requests are removed**, not just
   trusted to fail closed. This device has a confirmed, documented incident
   (MockbaMod's own `gotchas.md`) where a background render thread
   requesting real-time scheduling caused pads/buttons to go unresponsive
   and WiFi to drop, with clean-looking diagnostics right up until it
   happened - and this process runs as root here, so `CAP_SYS_NICE` is
   available and a bare "request refused" fallback isn't a real guarantee.
2. **One AArch64-only NEON intrinsic** (`vaddvq_f32`, in the vendored
   resampler) is replaced with the portable pairwise-add sequence that works
   identically on ARMv7 and AArch64 - a genuine portability bug in the
   original code (Move's own target is aarch64, so this path was never
   exercised on 32-bit ARM), unrelated to the porting itself.

Both edits are marked in-place with a `MockbaMod/Force port` comment.

`forceAudioIn.so` is the general-purpose audio-injection mechanism this repo
depends on rather than bundling - see
[`force-audioin`](https://github.com/sd88me/force-audioin) - deployed as its
own standalone MockbaMod addon (`ForceAudioIn`), so several voice addons can
share one tap.

## Layout

```
src/
  mcu.cpp/.h, mcu_opcodes.cpp/.h, pcm.cpp/.h, lcd.h   verbatim DSP core
  resampler_fixed.h    verbatim except the one NEON portability fix above
  jv880_plugin.cpp     Schwung's v2 plugin wrapper, verbatim except the two
                       SCHED_FIFO removals above
  jv_host.cpp          this port's own host shim (new code)
  plugin_api_v1.h      Schwung's plugin ABI (MIT-licensed for external use)
  rtmidi/              vendored RtMidi (same copy force-maze/force-acid use)
  forceAudioInject.h   shared-memory ring layout, vendored from ForceAudioIn
  module.json/help.json/ui.js/... other schwung-jv880 metadata, for reference
  web_ui.html          the module's own remote editor, reused verbatim (see web/)
scripts/
  Dockerfile/build.sh  native-armhf-under-QEMU build (Debian bookworm - see
                       Dockerfile for why, not the stretch base other ports
                       in this project use)
  build_xtk.py/xtk-seed.json   Q-Link .xtk template generator
addon/                the engine addon (jv_host + module.json + roms/)
web/                  the web panel addon (server.py bridge + web_ui.html +
                      remote-shim.js, served at the path web_ui.html already
                      expects for its transport - zero edits to web_ui.html)
nodeserver-integration/   home-page redirect module + ENDPOINTS.js snippet
tools/render_test/   headless render benchmark, used to measure the 2.81x
                      real-time number above (from schwung-jv880 upstream)
```

## ROMs

Not included - copyrighted Roland firmware. You need your own JV-880
**v1.0.0** ROM dump (v1.0.1 does not work): `jv880_rom1.bin`,
`jv880_rom2.bin`, `jv880_waverom1.bin`, `jv880_waverom2.bin`, and optionally
`jv880_nvram.bin`. Place them in `addon/roms/` before building/deploying.

## Building

```
./scripts/build.sh
```

Requires Docker (builds an armhf/QEMU image automatically). Output:
`dist/ForceJV880/`, a ready-to-copy addon folder (minus your ROM files).

## Status

Deployed and verified end-to-end on the live Force: both addons enabled,
ROM files in place, engine started via the web panel's Start button (real
ROM loading, real ALSA MIDI port, `forceAudioIn.so` attached, healthy
render-thread diagnostics), a test note and a test param-set both
succeeded. Three real bugs were found and fixed only at this on-device
stage (a web-panel port collision with a fourth existing addon, a
`chain_params` response truncated at 8192 bytes, a `forceAudioIn` mix-slot
collision with `force-maze`) - see DESIGN.md for details. Not yet checked:
whether the `.xtk` template renders correctly on the physical touchscreen,
or real audible sound quality/patch behavior.
