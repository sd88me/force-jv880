#!/usr/bin/env python3
"""Build addon/Force JV880 Control.xtk -- a Force track template that
pre-assigns Q-Link knobs (Force's physical knob bank) to jv_host's CC map
(src/jv_host.cpp's PARAMS[] table), so loading it onto a MIDI track gets
you named, correctly-ranged knobs instead of hand MIDI-learning each one.
The web panel (web/web_ui.html) covers every chain_param including deep
per-tone editing; this template covers the 14 that fit a physical Q-Link
bank (one bank is 16 knobs -- Mini-JV's chain_params all fit with 2 spare).

Format background (reverse-engineered, not documented by Akai/InMusic - see
docs/capture-xtk.md and force-acid/force-maze's own build_xtk.py, which this
is adapted from): a .xtk is

    <5-line ASCII header>\n<gzip-compressed JSON>

    ACVS
    3.3.0.0
    SerialisableTrackData
    json
    Linux

scripts/xtk-seed.json is the JSON body of a real captured template
(Harpie4T's own control track, pulled from a live MockbaMod Force) - generic
Force/mixer/pad-bank boilerplate, reused byte-for-byte here (same file
force-acid/force-maze both reuse) except for `data.program.customQLinks`
(rebuilt below) and self-referential name fields.

CAVEAT, same as force-acid's/force-maze's: NOT YET CONFIRMED to load
correctly in the Force's UI (nobody has clicked through and looked at it on
a real screen). Load it once and check: knob names show up, ranges look
right. See docs/capture-xtk.md.

LEFTOVER-DATA FIX (ported from force-acid's own build_xtk.py, found there by
on-device inspection): the shared seed's `customQLinks` was always fully
overwritten, but `data.program.customisable.mapping` (127 entries) was not
-- it's a leftover automation-parameter-name catalog from a *different*
addon's own generator engine (its `name` fields read like "1 Mode 0-25 (1
Cluster 0-59)"), and `midiInputRoute`/`midiOutputRoute` pointed at
"Mockba Harpie 4T" / referenced that same donor addon's own ALSA client,
not this project's ("Mockba JV880", see src/jv_host.cpp's --client default).
`blank_mapping()`/`fix_midi_routes()` below scrub both; `audit()` refuses to
build if any leftover donor-addon string survives.

Usage:
    python3 scripts/build_xtk.py                            # -> addon/Force JV880 Control.xtk (+ .xtk.json)
    python3 scripts/build_xtk.py --track-name "MY TRACK"     # if you don't use "JV880 CTRL"
    python3 scripts/build_xtk.py --pack path/to/edited.json --out "addon/Force JV880 Control.xtk"
        # skip seed/KNOBS generation entirely -- just re-pack an already-assembled
        # (and possibly hand-edited) JSON dump back into .xtk framing.
"""
import argparse
import gzip
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED_PATH = HERE / "xtk-seed.json"
HOST_PARAMS_PATH = HERE.parent / "src" / "jv_host.cpp"
HEADER = "ACVS\n3.3.0.0\nSerialisableTrackData\njson\nLinux\n"

PARAMS_LINE_RE = re.compile(r'\{\s*"(\w+)"\s*,.*,\s*(-?\d+)\s*\}')


def parse_host_params(host_path):
    """Parse (key, cc) pairs straight out of the host's own PARAMS[] table
    -- so the mapping table below can never silently drift from what the
    host actually listens for, the same principle as KNOBS but for every CC
    the host has, not just the 16 that fit on the Q-Link bank. Returns
    [(key, cc), ...] in table order.
    """
    text = Path(host_path).read_text()
    m = re.search(r"static const ParamSpec PARAMS\[\]\s*=\s*\{(.*?)\n\};", text, re.DOTALL)
    if not m:
        sys.exit(f"couldn't find PARAMS[] table in {host_path}")
    entries = []
    for line in m.group(1).splitlines():
        em = PARAMS_LINE_RE.match(line.strip())
        if em:
            entries.append((em.group(1), int(em.group(2))))
    return entries


def label_from_key(key):
    """Auto-derived display label for CCs outside the curated KNOBS list --
    everything the web GUI exposes that the 16-knob Q-Link bank has no room
    for. Deliberately not hand-maintained (unlike KNOBS's labels), so it
    can't drift from the host's own key names either."""
    return key.upper().replace("_", " ")

# Sentinel automationIndex the file's own schema already uses for "this slot
# has no automation target" -- see LEFTOVER-DATA FIX above.
UNUSED_AUTOMATION_INDEX = 2147483647

# Strings that must never survive into the built .xtk -- anything from a
# donor addon's own captured state that isn't ours. Checked by audit() after
# every build so a future seed swap/re-capture can't silently reintroduce
# this same leak.
FORBIDDEN_SUBSTRINGS = ["RiffMaker", "Harpie"]


def display_order(items):
    """Force lays a Q-Link bank's 16 slots into an on-screen 4x4 grid
    bottom-up: array index 0 renders bottom-left, index 15 top-right
    (confirmed on real hardware -- both the Q-Link assign editor and the
    track overview page agree on this). To make the grid read top-to-bottom
    in the same order KNOBS lists them, reverse the array in blocks of 4
    (one block per display row); columns within a row keep their order.
    With fewer than 16 items (this addon has 14), the two unused slots
    land at the end of the top row rather than at the very end of the
    array -- not separately hardware-confirmed, but the direct
    extrapolation of the confirmed 16-item rule.

    Side effect, unavoidable: this also changes which physical Q-Link knob
    number is bound to which parameter (whatever ends up at array index 0
    becomes hardware Q-Link knob 1), since screen position and array index
    are the same thing on this device. There's no way to change the visual
    order without also changing that binding.
    """
    cols = 4
    rows = 4  # a Q-Link bank is always 16 physical slots / 4 rows
    slots = [None] * (rows * cols)
    for d, item in enumerate(items):
        row, col = divmod(d, cols)
        slots[(rows - 1 - row) * cols + col] = item
    return [x for x in slots if x is not None]

# (key, label, cc) - must match src/jv_host.cpp's PARAMS[] table exactly
# (key names, CC numbers) or the knob will move but nothing will happen on
# the device. All 14 of Mini-JV's chain_params (module.json) are plain
# linear int ranges -- no momentary triggers, unlike force-acid's
# Generate/Mutate -- so there's no "momentary" column here.
KNOBS = [
    ("mode",                          "MODE",       20),
    ("preset",                        "PRESET",     21),
    ("performance",                   "PERF",       22),
    ("octave_transpose",              "OCTAVE",     23),
    ("macro_cutoff",                  "CUTOFF",     24),
    ("macro_resonance",               "RESONANCE",  25),
    ("macro_attack",                  "ATTACK",     26),
    ("macro_decay",                   "DECAY",      27),
    ("macro_sustain",                 "SUSTAIN",    28),
    ("macro_release",                 "RELEASE",    29),
    ("macro_tvf_env_depth",           "TVF ENV",    30),
    ("macro_lfo_depth",               "LFO DEPTH",  31),
    ("nvram_patchCommon_reverblevel", "REVERB",     32),
    ("nvram_patchCommon_choruslevel", "CHORUS",     33),
]
assert len(KNOBS) <= 16, "one Q-Link bank is only 16 knobs"

FULL_RANGE = {"min": 0.0, "max": 1.0, "stride": 0.0, "deadspot": 0.0, "skew": 1.0}
INPUT_RANGE = {"min": 0.0, "max": 1.0, "stride": 0.0, "deadspot": 2.0, "skew": 1.0}


def make_qlink(label, cc, track_name):
    return {
        "name": label,
        "controlType": 0,
        "targetData": [{
            "version": 1,
            "parameter": cc,
            "track": track_name,
            "insertParamIndex": {"initialized": False},
            "instrumentIndex": 257,
            "paramType": 1,
            "controlInputRange": dict(INPUT_RANGE),
            "parameterRange": dict(FULL_RANGE),
            "behaviour": 0,
        }],
        "momentary": 0,
        "controlValue": 0.0,
    }


def blank_mapping(doc):
    """Rebuild data.program.customisable.mapping from KNOBS -- see
    LEFTOVER-DATA FIX.

    REAL-HARDWARE FINDING: this table, not customQLinks, is what the
    Force's on-screen custom-knob page actually renders. automationIndex is
    a MIDI CC number (the donor addon's own real CC scheme), and `name` is
    that CC's display label. Confirmed by comparing a live screenshot of an
    unmodified donor track (correct custom names) against ours (showing
    "CC 24", "CC 29" etc. with the donor's own leftover *values*) -- Force
    falls back to a built-in MIDI-standard name (CC 11 = "Expression") or a
    bare "CC <n>" label whenever `name` is empty, which is what merely
    blanking `name` on every entry produced. See force-acid's build_xtk.py
    for the full writeup.

    The only correct fix is to actually populate this table with our own CC
    numbers and labels, and blank every other slot to the file's own
    "unused slot" shape (automationIndex sentinel, name/value empty) so no
    donor CCs or names survive either.

    COVERAGE: this table has 127 slots and isn't limited to one Q-Link
    bank's 16 knobs the way customQLinks is -- the web GUI exposes every CC
    the host listens to, so this on-screen page should too. The first 16
    slots get the Q-Link-covered CCs in KNOBS, reordered for correct
    top-to-bottom reading on page 1 (hardware-confirmed -- see
    display_order()); every other CC the host has (parsed straight out of
    its own PARAMS[] table via parse_host_params(), never hand-copied, so
    it can't drift) fills the remaining slots after that, in the host's own
    table order. Whether the same bottom-up-per-page quirk applies to pages
    beyond the first isn't hardware-confirmed -- if page 2+ reads bottom-up
    on a real screen too, apply display_order() to chunks of those as well.
    """
    mapping = doc["data"]["program"]["customisable"]["mapping"]
    for entry in mapping:
        entry["automationIndex"] = UNUSED_AUTOMATION_INDEX
        entry["value"] = 0.0
        entry["name"] = ""
    for slot, (_key, label, cc) in zip(mapping, display_order(KNOBS)):
        slot["automationIndex"] = cc
        slot["name"] = label
        slot["value"] = 0.0

    knob_ccs = {k[2] for k in KNOBS}
    extra = [(key, cc) for key, cc in parse_host_params(HOST_PARAMS_PATH) if cc not in knob_ccs]
    for slot, (key, cc) in zip(mapping[len(KNOBS):], extra):
        slot["automationIndex"] = cc
        slot["name"] = label_from_key(key)
        slot["value"] = 0.0


def fix_midi_routes(doc, control_channel):
    """Point data.midiInputRoute/midiOutputRoute at this project's own ALSA
    ports instead of the leftover donor addon's own. See LEFTOVER-DATA FIX.

    CORRECTED: the client name jv_host.cpp passes to RtMidi ("Mockba
    JV880") is NOT what actually shows up in ALSA/mido's port list on real
    hardware -- confirmed live (mido.get_output_names()/get_input_names(),
    same investigation that fixed web/server.py's identical bug --
    force-acid's web/server.py has the full story in its own
    IN_PORT_MATCH/OUT_PORT_MATCH comment): MockbaMod reorders it into
    "JV880:In (Mockba)" / "JV880:Out (Mockba)" (an ephemeral numeric
    client:port suffix follows, e.g. "... 139:0", not included here since
    it's assigned fresh every boot). The previous version of this function
    used "Mockba JV880" verbatim, which was never actually correct on this
    device.

    STILL UNCONFIRMED: whether Force's own route-matching needs the literal
    "(Mockba)" suffix, does prefix matching, or something else. `deviceId`
    (e.g. "137-0") looks like a cached, per-boot-ephemeral ALSA client:port
    number -- reset to "0-0" here as a clearly-unresolved placeholder on
    the assumption Force re-resolves routes by deviceName when the cached
    id doesn't match anything live -- not verified against real firmware
    behavior.
    """
    ch0 = control_channel - 1  # jv_host.cpp/--control-channel are 1-based; the numeric
                                # outputChannel field itself is 0-based.
    client = "JV880"

    in_route = doc["data"]["midiInputRoute"]
    in_route["inputPort"]["deviceName"] = f"{client}:In (Mockba)"
    in_route["inputPort"]["deviceId"] = "0-0"
    in_route["inputChannel"] = ch0

    out_route = doc["data"]["midiOutputRoute"]
    out_route["outputPort"]["deviceName"] = f"{client}:Out (Mockba)"
    out_route["outputPort"]["deviceId"] = "0-0"
    out_route["outputChannel"] = ch0


def rename(obj, template_name):
    """Self-referential name fields -- everywhere the seed said "Harpie 4T
    Control" (its own template name), swap in ours. Leave targetData's
    "track" fields alone -- those were just set above and mean something
    different (the *destination* MIDI track name)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "name" and isinstance(v, str) and v.startswith("Harpie 4T Control"):
                obj[k] = v.replace("Harpie 4T Control", template_name)
            else:
                rename(v, template_name)
    elif isinstance(obj, list):
        for item in obj:
            rename(item, template_name)


def audit(doc):
    """Scan the final doc for leftover donor-addon strings. Returns a list of
    JSON-path strings where something forbidden was found (empty = clean)."""
    hits = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{path}/{k}")
        elif isinstance(o, list):
            for i, item in enumerate(o):
                walk(item, f"{path}[{i}]")
        elif isinstance(o, str):
            for bad in FORBIDDEN_SUBSTRINGS:
                if bad in o:
                    hits.append(f"{path} = {o!r}")
    walk(doc, "")
    return hits


def build_doc(track_name, template_name, control_channel):
    if not SEED_PATH.exists():
        sys.exit(f"seed file missing: {SEED_PATH}")
    doc = json.loads(SEED_PATH.read_text())

    program = doc["data"]["program"]
    program["customQLinks"] = [
        make_qlink(label, cc, track_name)
        for (_key, label, cc) in KNOBS
    ]
    blank_mapping(doc)
    fix_midi_routes(doc, control_channel)
    rename(doc, template_name)
    return doc


def write_xtk(doc, out_path):
    body = HEADER + json.dumps(doc, indent=4)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(out_path, "wb", mtime=0) as f:
        f.write(body.encode("utf-8"))


def write_json(doc, out_path):
    """Always emitted alongside the .xtk -- the human-reviewable form. Edit
    this file and re-run with --pack to rebuild without touching this
    script's generation logic."""
    out_path.write_text(json.dumps(doc, indent=2) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track-name", default="JV880 CTRL",
                     help='must match the MIDI track name exactly once loaded on the Force, and '
                          'src/jv_host.cpp\'s --control-channel must match that track\'s output '
                          'MIDI channel (default: "JV880 CTRL")')
    ap.add_argument("--out", default=str(HERE.parent / "addon" / "Force JV880 Control.xtk"))
    ap.add_argument("--template-name", default=None,
                     help="self-referential name Force gives the NEW track it creates when "
                          "loading this .xtk (Force's track-template loader always creates a "
                          "new track, never merges onto one you already have) -- defaults to "
                          "--track-name so the created track is already correctly named and "
                          "self-targets without a manual rename step; override only if you "
                          "want the loaded track to have a different display name than the "
                          "Q-Link targets bind to")
    ap.add_argument("--control-channel", type=int, default=1,
                     help="1-16, must match jv_host's --control-channel (default 1) -- "
                          "used for this track's MIDI I/O route, not the Q-Link CC targets")
    ap.add_argument("--pack", metavar="JSON_PATH",
                     help="skip seed/KNOBS generation -- wrap this already-assembled "
                          "JSON file (e.g. a previous build's --out .json, hand-edited) "
                          "into .xtk framing instead")
    args = ap.parse_args()

    out_path = Path(args.out)
    json_path = out_path.with_suffix(out_path.suffix + ".json")

    if args.pack:
        pack_path = Path(args.pack)
        if not pack_path.exists():
            sys.exit(f"--pack file missing: {pack_path}")
        doc = json.loads(pack_path.read_text())
        print(f"packing {pack_path} (skipping seed/KNOBS generation)")
    else:
        template_name = args.template_name or args.track_name
        doc = build_doc(args.track_name, template_name, args.control_channel)

    hits = audit(doc)
    if hits:
        print("WARNING: leftover donor-addon strings survived into the build:", file=sys.stderr)
        for h in hits:
            print(f"  {h}", file=sys.stderr)
        sys.exit(1)

    write_xtk(doc, out_path)
    write_json(doc, json_path)

    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")
    print(f"wrote {json_path} (reviewable JSON -- edit + --pack it to rebuild)")
    if not args.pack:
        program = doc["data"]["program"]
        print(f"Q-Link bank: {len(program['customQLinks'])} knobs, track name '{args.track_name}'")
        print("Load it on the Force onto a MIDI track literally named "
              f"'{args.track_name}' -- the CC targets are bound by track NAME, not by track index.")
        print("jv_host must be started with --control-channel matching that track's output channel "
              "(default 1) for any of this to actually reach jv880_plugin.cpp.")


if __name__ == "__main__":
    main()
