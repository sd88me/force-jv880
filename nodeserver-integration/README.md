# nodeServer integration

Not part of the `ForceJV880` addon itself - these patch the **nodeServer**
addon (a separate, shared MockbaMod addon), which is what actually renders
the Modules page and the home-page quick-links. `force-acid`/`force-maze`
did the equivalent (`api/endpoints/forceacid.js`/`forcemaze.js`, an
`ENDPOINTS.js` entry each) directly against a live nodeServer install
without versioning it anywhere - this folder exists so the same patch for
JV-880 doesn't get silently lost the same way.

## Modules page (`/moduler`) - no patch needed

Automatic: nodeServer's `moduler` endpoint (`api/endpoints/moduler/index.js`)
scans every `AddOns/*/NSMODULE.json` and lists whatever it finds, with
start/stop + autolaunch-toggle controls driven entirely by that file. Once
`addon/NSMODULE.json` is deployed inside `AddOns/ForceJV880/`, "Force
JV-880" just appears there - see that file's own `DESCRIPTION` for the one
caveat (toggling RUNNING there starts/stops `jv_host` only, it doesn't arm
the LD_PRELOAD tap or restart `acvs`).

`NSMODULE.json`'s `ARGUMENTS` already split every flag and its value into
separate array entries (`moduler`'s spawn call does `JSN.ARGUMENTS.map(A =>
A.VALUE)` and passes that straight to `spawn()`, so each `VALUE` becomes ONE
argv entry, not shell-split - a value like `"--module-dir /path"` would
otherwise arrive as one unparseable string).

## Home page quick-link - two files to add

1. Copy `forcejv880.js` to nodeServer's `app/api/endpoints/forcejv880.js`.
2. Add this entry to `app/api/ENDPOINTS.js`'s exported array (after the
   "Force Maze Voice" entry is a reasonable place):

```js
    {
        // Force JV-880 runs its own standalone server (not an in-process
        // nodeServer module -- see force-jv880/web/server.py). URL/PARAM
        // stay a plain relative path on purpose (home.js's escape() call
        // mangles absolute "http://host:port" URLs -- see forcejv880.js);
        // clicking this link hits nodeServer's own /forcejv880 route, which
        // forcejv880.js immediately 302-redirects out to the real panel.
        NAME: "Force JV-880",
        PATH: "./api/endpoints/forcejv880.js",
        PARAM: "/forcejv880",
        URL: "/forcejv880",
        HIDDEN: false,
        HOME: true,
        TARGET: "FORCEJV880"
    },
```

3. Restart nodeServer for the new route to be picked up (it does not need
   `acvs`/MPC touched at all - a plain process kill+relaunch of nodeServer's
   own `server.js`, or `run_nodeserver.sh kill` then re-run).

Both files target port **8306** (Force JV-880's web panel - the next free
slot after force-acid's 8303 and force-maze's 8304) - if you ever change
`web/server.py --port`, update `forcejv880.js`'s redirect target to match.
