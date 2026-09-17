// Redirects nodeServer's /forcejv880 to the standalone Force JV-880 web
// panel (a separate process/port -- see web/server.py). A real HTTP
// redirect, not a rendered <a href>, deliberately: home.js's own link
// renderer runs every URL through the legacy global escape(), which mangles
// the colons in an absolute "http://host:port" URL (turns them into %3A,
// producing a broken link). Redirecting server-side here sidesteps that bug
// entirely instead of trying to patch home.js. Same pattern as
// force-acid's forcedacid.js / force-maze's forcemaze.js.
//
// NOTE: the target IP is hardcoded below. If the Force's IP changes (no
// DHCP reservation set), update it here -- see ENDPOINTS.js's entry for
// "JV-880".
module.exports = { INIT };

function INIT(req, res) {
    res.writeHead(302, { Location: "http://192.168.1.187:8306/" });
    res.end();
}
