#!/bin/sh
# ForceJV880 AddOn Manager (MockbaMod convention).
#   sh manage.sh ENABLE | DISABLE | UNINSTALL
#
# Ported Schwung "Mini-JV" DSP synth (Roland JV-880 PCM rompler emulation,
# via mini-jv880/Nuked-SC55). jv_host renders it via its native v2 plugin API
# and writes audio into a shared-memory ring that the separate ForceAudioIn
# addon's forceAudioIn.so (LD_PRELOAD'd into MPC) mixes into what MPC reads
# from its capture device.
#
# This addon does NOT touch LD_PRELOAD or restart acvs - ForceAudioIn owns
# arming the shared tap exclusively (enable it separately, once; see its own
# README.md). jv_host itself is started/stopped entirely from the nodeServer
# Modules page (/moduler) - never from this script, and never at boot (see
# NSMODULE.json - Autoload is deliberately unavailable). ENABLE/DISABLE here
# only control whether the addon's files are present.

appname=jv_host
appTitle="Force JV-880"
appDir=ForceJV880

mmPath=$(cat /dev/shm/.mmPath)
. $mmPath/MockbaMod/env.sh

runDir="$mmPath/AddOns"
installroot="$runDir/$appDir"
mode=$1

echo "
***********************************************************
*   $appTitle AddOn Manager for MockbaMod
***********************************************************
"

STOP() {
    for p in $(ps 2>/dev/null | grep "[j]v_host" | awk '{print $1}'); do
        kill -9 $p 2>/dev/null
    done
}

if [ "$mode" = "UNINSTALL" ]; then
    STOP
    rm -rf "$installroot" 2>/dev/null
    echo "<<<< $appTitle uninstalled."
    exit 0
fi

if [ "$mode" = "DISABLE" ]; then
    STOP
    echo "$appTitle's jv_host stopped (files kept - this addon has no boot-time footprint to remove)."
    exit 0
fi

if [ "$mode" = "ENABLE" ]; then
    echo "$appTitle enabled. Make sure the separate ForceAudioIn addon is"
    echo "also enabled (its own manage.sh ENABLE) - it arms the shared tap"
    echo "this addon needs. Start the voice itself from the nodeServer"
    echo "Modules page (/moduler), not from here."
    echo
    echo "You must also place your own JV-880 v1.0.0 ROM files (not"
    echo "included - copyrighted Roland firmware) in:"
    echo "  $installroot/roms/jv880_rom1.bin"
    echo "  $installroot/roms/jv880_rom2.bin"
    echo "  $installroot/roms/jv880_waverom1.bin"
    echo "  $installroot/roms/jv880_waverom2.bin"
    echo "  $installroot/roms/jv880_nvram.bin   (optional)"
    exit 0
fi

echo "Usage: sh manage.sh ENABLE | DISABLE | UNINSTALL"
echo
echo "Status:"
ps 2>/dev/null | grep -q "[j]v_host" && echo "  voice: RUNNING" || echo "  voice: stopped"
echo "  start/stop from the nodeServer Modules page (/moduler) - requires"
echo "  the separate ForceAudioIn addon to be enabled first."
echo "  web UI is a separate addon - see web/manage.sh (survives this being disabled)"
echo "  logs: /tmp/forceAudioIn.log (mix tap, in the ForceAudioIn addon), /tmp/jv_host.log (synth)"
echo "  control socket: /tmp/jv880_ctrl.sock"
