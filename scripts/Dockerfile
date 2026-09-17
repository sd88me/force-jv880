# Build environment for force-jv880 — Akai Force is ARM 32-bit hard-float
# (ELF 32-bit LSB, ARM EABI5, /lib/ld-linux-armhf.so.3, "GNU/Linux 3.2.0").
#
# Native armhf build *under QEMU* (docker run --platform linux/arm/v7 needs
# binfmt_misc for arm registered on the host - Docker Desktop ships this; on
# a bare dockerd, run once:
#   docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
#
# Base image is Debian bookworm, NOT the older arm32v7/debian:stretch this
# project's other ports (force-acid/force-maze) use. Checked directly
# against this specific Force over SSH: its real ceiling is glibc 2.39 /
# GLIBCXX 3.4.32 (`strings /lib/libc.so.6`, `strings
# /usr/lib/libstdc++.so.6.0.32`) - much newer than stretch's glibc 2.24, and
# this port's DSP core (jv880_plugin.cpp/mcu.cpp) needs a compiler new
# enough for its C++11/C++17 mix and NEON intrinsics; bookworm's g++ 12 /
# cmake 3.25 comfortably clears both bookworm's own glibc 2.36 ceiling and
# this device's real one. Re-check the device's own ceiling before reusing
# this image for a different Force firmware build.
FROM debian:bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        g++ \
        libasound2-dev \
        file \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
