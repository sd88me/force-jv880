#!/usr/bin/env bash
# Assemble AddOns/ForceJV880/ - addon/ + the engine (build/jv_host) + web/ -
# the one folder the device needs.
#   scripts/package.sh [version]    -> dist-zip/ForceJV880-<version>.zip, to unzip
#                                      onto the SD card root. Leaves out
#                                      your ROMs in addon/roms/.
#   scripts/package.sh --stage DIR  -> DIR/AddOns/ForceJV880, local files included;
#                                      scripts/deploy.sh copies this to the device.
# Uses the committed build/jv_host - run scripts/build.sh (and commit the
# result) first if the sources changed.
# .github/workflows/release.yml runs this for every published release.
set -euo pipefail
cd "${PKG_ROOT:-$(dirname "$0")/..}"
if [ "${1:-}" = --stage ]; then
  STAGE="${2:?usage: scripts/package.sh --stage DIR}"; VER=
else
  VER="${1:-$(git describe --tags --always)}"
  STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
fi
A="$STAGE/AddOns/ForceJV880"
rm -rf "$A"; mkdir -p "$STAGE/AddOns"
cp -r addon "$A"
cp build/jv_host "$A/jv_host"
cp -r web "$A/web"
find "$A" \( -name __pycache__ -prune -o -name '*.pyc' -o -name .gitkeep \) -exec rm -rf {} +
chmod 0755 "$A"/*.sh "$A"/web/*.sh "$A/jv_host"
[ -n "$VER" ] || exit 0

[ -d "$A/roms" ] && find "$A/roms" -mindepth 1 -delete
OUT="$PWD/dist-zip"; mkdir -p "$OUT"
rm -f "$OUT/ForceJV880-$VER.zip"
python3 -c "import shutil,sys; shutil.make_archive(sys.argv[1], 'zip', sys.argv[2], 'AddOns')" "$OUT/ForceJV880-$VER" "$STAGE"
python3 -m zipfile -l "$OUT/ForceJV880-$VER.zip"
