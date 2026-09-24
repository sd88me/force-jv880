#!/usr/bin/env bash
# Build the SD-card release zip: dist-zip/ForceJV880-<version>.zip, unpacking to
#   AddOns/ForceJV880/        addon/ + the prebuilt engine (build/jv_host) + web/
# Unzip it onto the SD card root. Uses the committed build/jv_host - run
# scripts/build.sh (and commit the result) first if the sources changed.
# .github/workflows/release.yml runs this for every published release.
set -euo pipefail
cd "${PKG_ROOT:-$(dirname "$0")/..}"
VER="${1:-$(git describe --tags --always)}"
OUT="$PWD/dist-zip"
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
A="$STAGE/AddOns/ForceJV880"
mkdir -p "$STAGE/AddOns" "$OUT"
cp -r addon "$A"
cp build/jv_host "$A/jv_host"
cp -r web "$A/web"
find "$STAGE" \( -name __pycache__ -prune -o -name '*.pyc' -o -name .gitkeep \) -exec rm -rf {} +
chmod 0755 "$A"/*.sh "$A"/web/*.sh "$A/jv_host"
rm -f "$OUT/ForceJV880-$VER.zip"
python3 -c "import shutil,sys; shutil.make_archive(sys.argv[1], 'zip', sys.argv[2], 'AddOns')" "$OUT/ForceJV880-$VER" "$STAGE"
python3 -m zipfile -l "$OUT/ForceJV880-$VER.zip"
