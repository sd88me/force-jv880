/* Served by server.py at /static/schwung-remote-api.js -- web_ui.html loads
 * this path unmodified (see its own <script src> tag) expecting it to
 * define window.schwungRemote, exactly the way Move's own manager iframe
 * would. This replaces that postMessage-based API with fetch() calls to
 * this addon's own small bridge server (server.py), which in turn talks to
 * jv_host's Unix control socket (SET/GET/NOTE/DESCRIBE) -- same shape as
 * force-maze's web/index.html shim, just factored out to its own file since
 * web_ui.html loads it as an external <script src> rather than inlining it.
 *
 * Move namespaces params per chain component ("synth:cutoff" etc); there's
 * only ever one instance here, so the "synth:" prefix is stripped before it
 * reaches the server.
 */
(function () {
  "use strict";
  var P = "synth:";
  function stripPrefix(key) { return key.indexOf(P) === 0 ? key.slice(P.length) : key; }

  window.schwungRemote = {
    getParam: function (key) {
      return fetch("/param?key=" + encodeURIComponent(stripPrefix(key)))
        .then(function (r) { return r.ok ? r.text() : undefined; })
        .catch(function () { return undefined; });
    },

    setParam: function (key, val) {
      fetch("/param", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: stripPrefix(key), value: String(val) }),
      }).catch(function () {});
    },

    /* web_ui.html's boot() calls this separately from getParam -- it's not
     * just another key, it's the whole param/knob registry (mode, ranges,
     * per-tone metadata, etc: jv880_plugin.cpp's own get_param("chain_params"),
     * >40KB of JSON) that ingestChainParams() uses to build every panel
     * below. This was missing entirely in the first version of this shim:
     * window.schwungRemote existed (so the `|| {...}` fallback in
     * web_ui.html's own code never kicked in), but had no getChainParams
     * property, so `await remote.getChainParams()` threw immediately and
     * boot() bailed out silently -- headers rendered (static HTML) but no
     * panel ever got built. Bridges to /describe, the server.py endpoint
     * already sized for this payload (see DESIGN.md's 8192-byte truncation
     * bug writeup -- that was the *startup* fetch inside jv_host.cpp itself;
     * this is the separate *browser-side* fetch of the same data, and needed
     * its own fix here). */
    getChainParams: function () {
      return fetch("/describe")
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; });
    },

    /* No push mechanism in v1. Unlike force-maze's Maze Voice, Mini-JV DOES
     * have a physical Q-Link CC control channel (see jv_host's PARAMS[]
     * table) in addition to this web panel, so a knob turned on the Force's
     * own hardware while this page is open will NOT be reflected here live
     * -- reload the page (or add a "Sync" action that re-runs the seed()
     * getParam pass below) to pick up out-of-band changes. Worth revisiting
     * with real polling if that turns out to matter in practice. */
    onParamChange: function () {},
  };
})();
