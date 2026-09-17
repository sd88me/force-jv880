#!/bin/sh
############################################################
# ForceJV880 — deliberately a no-op.
#
# This addon does not arm any LD_PRELOAD tap or auto-start jv_host at boot
# - that's ForceAudioIn's job (see its own README.md), and jv_host is only
# ever started on demand via the nodeServer Modules page (/moduler), never
# at boot. NSMODULE.json also sets AUTOLAUNCHABLE:false for this reason.
#
# This file still exists, as a harmless stub, only because nodeServer's
# moduler endpoint names its own optional "Autoload" copy target after
# PROCESSNAME (run_jv_host.sh) - if that toggle is ever set despite
# AUTOLAUNCHABLE:false, having this file present and inert is safer than
# it failing to find a file to copy. It intentionally does nothing at all,
# on every invocation, "kill" included.
############################################################
exit 0
