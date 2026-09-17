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

Usage:
    python3 scripts/build_xtk.py [--track-name "JV880 CTRL"] [--out "addon/Force JV880 Control.xtk"]
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED_PATH = HERE / "xtk-seed.json"
HEADER = "ACVS\n3.3.0.0\nSerialisableTrackData\njson\nLinux\n"

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track-name", default="JV880 CTRL",
                     help='must match the MIDI track name exactly once loaded on the Force, and '
                          'src/jv_host.cpp\'s --control-channel must match that track\'s output '
                          'MIDI channel (default: "JV880 CTRL")')
    ap.add_argument("--out", default=str(HERE.parent / "addon" / "Force JV880 Control.xtk"))
    ap.add_argument("--template-name", default="Force JV880 Control")
    args = ap.parse_args()

    if not SEED_PATH.exists():
        sys.exit(f"seed file missing: {SEED_PATH}")

    doc = json.loads(SEED_PATH.read_text())

    program = doc["data"]["program"]
    program["customQLinks"] = [
        make_qlink(label, cc, args.track_name)
        for (_key, label, cc) in KNOBS
    ]

    # Self-referential name fields -- everywhere the seed said "Harpie 4T
    # Control" (its own template name), swap in ours. Leave targetData's
    # "track" fields alone -- those were just set above and mean something
    # different (the *destination* MIDI track name).
    def rename(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "name" and isinstance(v, str) and v.startswith("Harpie 4T Control"):
                    obj[k] = v.replace("Harpie 4T Control", args.template_name)
                else:
                    rename(v)
        elif isinstance(obj, list):
            for item in obj:
                rename(item)

    rename(doc)

    body = HEADER + json.dumps(doc, indent=4)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(out_path, "wb", mtime=0) as f:
        f.write(body.encode("utf-8"))

    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")
    print(f"Q-Link bank: {len(program['customQLinks'])} knobs, track name '{args.track_name}'")
    print("Load it on the Force onto a MIDI track literally named "
          f"'{args.track_name}' -- the CC targets are bound by track NAME, not by track index.")
    print("jv_host must be started with --control-channel matching that track's output channel "
          "(default 1) for any of this to actually reach jv880_plugin.cpp.")


if __name__ == "__main__":
    main()
