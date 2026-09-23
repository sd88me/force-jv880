#!/usr/bin/env python3
"""Mini-JV (JV-880) web control panel — serves the module's own web_ui.html
(reused verbatim from schwung-jv880) plus a small transport shim
(remote-shim.js, served at the path web_ui.html already expects,
/static/schwung-remote-api.js) and bridges its knob/switch/button actions
to jv_host's Unix control socket (SET/GET/DESCRIBE/NOTE — see
src/jv_host.cpp's header comment for the protocol).

Deliberately stdlib-only (http.server + socket): no pip install step needed
on-device, matching this project's other web panels (force-acid/web/server.py,
force-maze/web/server.py, ~/.claude/skills/mockbamod-module-creator/
references/web-gui.md).

Run: python3 server.py [--port N] [--ctrl-sock PATH]
"""
import json
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

WEB_DIR = Path(__file__).resolve().parent
ADDON_DIR = WEB_DIR.parent          # .../AddOns/ForceJV880 on a deployed device
ENGINE_BIN = ADDON_DIR / "jv_host"
CTRL_SOCK = "/tmp/jv880_ctrl.sock"
SOCK_TIMEOUT = 1.0
CONTROL_CHANNEL = "1"               # must match the .xtk template's track output channel
# ForceAudioJack's forceAudioJack.log shows slot 0 already repeatedly used by
# force-maze's own maze_host (its own default too) on this device -- default
# to a different slot so running both voices at once doesn't collide. Change
# together with NSMODULE.json's --mix-slot argument if you change this.
MIX_SLOT = "1"


def ctrl_request(line: str):
    """Send one line to jv_host's control socket, return its reply (or
    None if the engine isn't reachable). One connection per request —
    these are user-interaction-rate calls (knob turns, button presses),
    nowhere near the audio thread, so the per-call connect cost is fine.
    `with` guarantees the socket closes on every exit path (see
    force-maze/web/server.py's own note on an earlier fd-leak bug here)."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(SOCK_TIMEOUT)
            s.connect(CTRL_SOCK)
            s.sendall((line.strip("\n") + "\n").encode("utf-8"))
            # jv_host closes the connection after every single response (see
            # jv_host.cpp's ctrl_server_loop), so it's safe -- and, for a
            # payload bigger than one recv() call returns, NECESSARY -- to
            # read until EOF rather than trust one recv() to have it all.
            # chain_params here is >8KB (see DESIGN.md); a single bounded
            # recv(8192) silently truncated it before this fix, which
            # produced invalid JSON at exactly the 8192-byte boundary.
            chunks = []
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            reply = b"".join(chunks)
            return reply.decode("utf-8", errors="replace").strip("\n")
    except OSError:
        return None


def engine_present():
    return ctrl_request("DESCRIBE") is not None


def engine_start():
    """Spawn jv_host directly (same args NSMODULE.json's Modules-page toggle
    uses), like force-acid/web/server.py's own engine_start(). ROM loading +
    warmup can take a few seconds on real hardware before the control socket
    even starts listening (see jv_host.cpp: chain_params isn't fetched, and
    the socket isn't bound, until after an internal loading_complete poll) -
    poll longer than a bare port-registration check would need."""
    if engine_present():
        return True, "already running"
    if not ENGINE_BIN.exists():
        return False, f"binary not found: {ENGINE_BIN}"
    args = [str(ENGINE_BIN), "--module-dir", str(ADDON_DIR),
            "--ctrl-sock", CTRL_SOCK, "--control-channel", CONTROL_CHANNEL,
            "--mix-slot", MIX_SLOT]
    try:
        # manage.sh's own status text documents /tmp/jv_host.log as where
        # the synth's runtime diagnostics (ring backlog/drops, wake-gap
        # stats -- see jv_host.cpp's timer_loop) end up; keep that true.
        log = open("/tmp/jv_host.log", "ab")
        proc = subprocess.Popen(args, stdout=log, stderr=log,
                                 stdin=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:
        return False, str(e)
    # Reap it whenever it exits (killall from /engine stop, a crash, or the
    # process outliving this server) -- otherwise it zombies forever, since
    # nothing else waits on it.
    threading.Thread(target=proc.wait, daemon=True).start()
    for _ in range(40):  # up to ~12s for ROM load + warmup + socket bind
        time.sleep(0.3)
        if engine_present():
            return True, "started"
    return False, "launched but control socket did not come up in time"


def engine_stop():
    # jv_host is a distinctively-named native binary (unlike e.g. python3,
    # which this device runs many unrelated instances of) -- killall here
    # can't take down anything but this engine, matching force-acid's own
    # engine_stop() for the same reason.
    subprocess.run(["killall", "jv_host"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True, "stopped"


class Handler(BaseHTTPRequestHandler):
    server_version = "JV880Web/0.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[jv880-web] " + (fmt % args) + "\n")

    def _text(self, code, body, ctype="text/plain; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._text(code, json.dumps(obj), "application/json; charset=utf-8")

    def _file(self, relpath, ctype):
        path = WEB_DIR / relpath
        try:
            data = path.read_bytes()
        except OSError:
            self.send_error(404, "not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._file("web_ui.html", "text/html; charset=utf-8")
            return

        if path == "/static/schwung-remote-api.js":
            self._file("remote-shim.js", "application/javascript; charset=utf-8")
            return

        if path == "/param":
            qs = parse_qs(urlparse(self.path).query)
            key = (qs.get("key") or [""])[0]
            if not key:
                self._text(400, "missing key")
                return
            reply = ctrl_request(f"GET {key}")
            if reply is None:
                self._text(503, "engine not running")
            elif reply == "ERR":
                self._text(404, "unknown param")
            else:
                self._text(200, reply)
            return

        if path == "/describe":
            reply = ctrl_request("DESCRIBE")
            if reply is None:
                self._json(503, {})
            else:
                # already JSON text from jv880_plugin.cpp's own chain_params
                self._text(200, reply, "application/json; charset=utf-8")
            return

        if path == "/status":
            self._json(200, {"engine_running": engine_present()})
            return

        self.send_error(404, "not found")

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "bad json"})
            return

        if path == "/param":
            key, value = body.get("key"), body.get("value")
            if not key or value is None:
                self._json(400, {"ok": False, "error": "missing key/value"})
                return
            reply = ctrl_request(f"SET {key} {value}")
            self._json(200 if reply == "OK" else 503, {"ok": reply == "OK"})
            return

        if path == "/note":
            note = int(body.get("note", 60))
            vel = int(body.get("velocity", 100))
            reply = ctrl_request(f"NOTE {note} {vel}")
            self._json(200 if reply == "OK" else 503, {"ok": reply == "OK"})
            return

        if path == "/engine":
            action = body.get("action")
            if action == "start":
                ok, msg = engine_start()
            elif action == "stop":
                ok, msg = engine_stop()
            else:
                self._json(400, {"ok": False, "error": "action must be start|stop"})
                return
            self._json(200 if ok else 503, {"ok": ok, "message": msg})
            return

        self.send_error(404, "not found")


def main():
    global CTRL_SOCK
    port = 8306  # next free slot after force-acid's 8303, force-maze's 8304, and ForceMazeSeq's 8305; see gotchas.md on port collisions
    args = sys.argv[1:]
    if "--port" in args:
        port = int(args[args.index("--port") + 1])
    if "--ctrl-sock" in args:
        CTRL_SOCK = args[args.index("--ctrl-sock") + 1]

    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"[jv880-web] serving on http://0.0.0.0:{port}  (control socket: {CTRL_SOCK})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
