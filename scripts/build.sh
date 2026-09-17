#!/usr/bin/env bash
# Build force-jv880's engine (jv_host) for armhf, native-under-QEMU via
# Docker (see Dockerfile for why bookworm, not the stretch base this
# project's other ports use). Set CROSS_PREFIX to skip Docker if you
# already have a real armhf toolchain (e.g. building on a Pi).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
IMAGE_NAME="force-jv880-builder"

if [ -z "${CROSS_PREFIX:-}" ] && [ ! -f "/.dockerenv" ]; then
    echo "=== Force JV-880 Build (via Docker/QEMU armhf) ==="
    if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
        echo "Building Docker image (first time only)..."
        docker build --platform linux/arm/v7 -t "$IMAGE_NAME" -f "$SCRIPT_DIR/Dockerfile" "$REPO_ROOT"
    fi
    docker run --rm --platform linux/arm/v7 \
        -v "$REPO_ROOT:/build" \
        -w /build \
        "$IMAGE_NAME" \
        ./scripts/build.sh
    echo "=== Done: dist/ForceJV880/jv_host ==="
    exit 0
fi

cd "$REPO_ROOT"
mkdir -p build dist/ForceJV880 dist/ForceJV880/web

echo "Compiling resampler helpers..."
gcc -O2 -c -fPIC src/resample/resample.c      -Isrc/resample -o build/resample.o
gcc -O2 -c -fPIC src/resample/resamplesubs.c  -Isrc/resample -o build/resamplesubs.o
gcc -O2 -c -fPIC src/resample/filterkit.c     -Isrc/resample -o build/filterkit.o

echo "Compiling RtMidi..."
g++ -O2 -c -fPIC -std=c++14 -D__LINUX_ALSA__ src/rtmidi/RtMidi.cpp -o build/RtMidi.o -Isrc/rtmidi

echo "Compiling jv_host (DSP core + host shim)..."
g++ -Ofast -fPIC -std=c++11 \
    -mcpu=cortex-a17 -mfpu=neon-vfpv4 -mfloat-abi=hard \
    -DNDEBUG \
    src/jv_host.cpp src/jv880_plugin.cpp src/mcu.cpp src/mcu_opcodes.cpp src/pcm.cpp \
    build/resample.o build/resamplesubs.o build/filterkit.o build/RtMidi.o \
    -o build/jv_host \
    -Isrc -Isrc/resample -Isrc/rtmidi \
    -lasound -lpthread -lrt

echo "Packaging..."
cp build/jv_host dist/ForceJV880/jv_host
cp src/module.json dist/ForceJV880/module.json
cp src/help.json dist/ForceJV880/help.json
cp addon/manage.sh addon/run_jv_host.sh addon/NSMODULE.json dist/ForceJV880/
mkdir -p dist/ForceJV880/roms
cp web/web_ui.html web/remote-shim.js web/server.py web/manage.sh web/run_jv880_web.sh dist/ForceJV880/web/

echo ""
echo "=== Build Complete ==="
echo "Output: dist/ForceJV880/"
echo ""
echo "NOTE: You need to provide your own JV-880 v1.0.0 ROM files in"
echo "dist/ForceJV880/roms/ before jv_host will start:"
echo "  - jv880_rom1.bin"
echo "  - jv880_rom2.bin"
echo "  - jv880_waverom1.bin"
echo "  - jv880_waverom2.bin"
echo "  - jv880_nvram.bin (optional)"
