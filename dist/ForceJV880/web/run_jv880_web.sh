#!/bin/sh
############################################################
# Copy this file to $mmPath/AddOns to launch automatically
# at boot (manage.sh ENABLE does that for you).
############################################################
#
# Runs the Force JV-880 web control panel (server.py). Independent of the
# engine's own addon/manage.sh/run_jv_host.sh - the engine only ever starts
# on demand via the nodeServer Modules page, but the *panel* can be up and
# reachable at all times, same as force-acid/force-maze's own web panels
# (this is a direct copy of that pattern).
#
# PID-file based kill, not `killall python3` or a `pgrep -f` name match:
# this device runs other python3 processes (nodeServer's tooling, force-
# acid's and force-maze's own web panels), and a name-based kill would take
# those down too.

mmPath=$(cat /dev/shm/.mmPath)
. $mmPath/MockbaMod/env.sh

APPDIR="$mmPath/AddOns/ForceJV880/web"
PIDFILE="$APPDIR/.jv880_web.pid"

if [ "$1" = "kill" ]; then
    if [ -f "$PIDFILE" ]; then
        kill "$(cat "$PIDFILE")" 2>/dev/null
        rm -f "$PIDFILE"
    fi
else
    cd "$APPDIR" || exit 1
    python3 server.py --port 8306 --ctrl-sock /tmp/jv880_ctrl.sock >/tmp/jv880_web.log 2>&1 &
    echo $! > "$PIDFILE"
fi
