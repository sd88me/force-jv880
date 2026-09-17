/* jv_host.cpp — Force/MockbaMod runtime host for the ported Mini-JV (Roland
 * JV-880) DSP synth. Plays the role Move's chain host plays for
 * jv880_plugin.cpp, the same way maze_host.cpp does for maze_voice.c:
 *
 *   Move/Schwung host                     this shim
 *   -------------------------------------- --------------------------------
 *   dlopen(dsp.so), move_plugin_init_v2    links jv880_plugin.o etc directly,
 *                                          calls it directly (no dlopen)
 *   on_midi() per incoming note            RtMidi input callback -> on_midi()
 *   render_block() per SPI-callback block  wall-clock timer thread -> render_block()
 *   set_param(key, "64") from a knob       a local control socket, or CC on
 *                                          the control channel -> set_param()
 *   knob repaint via get_param             the web UI's /describe calls get_param
 *   int16 stereo out via the mailbox       float32 into ForceAudioIn's shared-
 *                                          memory ring (forceAudioInject.h) --
 *                                          forceAudioIn.so (LD_PRELOAD'd into
 *                                          /usr/bin/MPC) mixes it into what MPC
 *                                          reads from its capture device.
 *
 * jv880_plugin.cpp + mcu.cpp/mcu_opcodes.cpp/pcm.cpp are vendored verbatim
 * from schwung-jv880, with exactly two deliberate exceptions, both documented
 * in-place with a "MockbaMod/Force port" comment where they were made:
 *
 *   1. jv880_plugin.cpp's two SCHED_FIFO requests (its own background emu
 *      thread's creation, and that thread's own priority-45 self-request)
 *      are removed rather than relying on the existing "refused, falling
 *      back to SCHED_OTHER" paths to fail closed on their own -- this device
 *      has a confirmed, documented incident (see MockbaMod gotchas.md) where
 *      a background render thread requesting real-time scheduling caused
 *      pads/buttons to go unresponsive and WiFi to drop, with clean-looking
 *      diagnostics right up until it happened. Removed outright rather than
 *      trusted to fail safely, since this process runs as root on this
 *      device (CAP_SYS_NICE is available, so relying on the request simply
 *      being refused is not a guarantee here the way it might be for an
 *      unprivileged process).
 *   2. resampler_fixed.h's one horizontal-sum NEON intrinsic (vaddvq_f32) is
 *      AArch64-only; replaced with the portable NEON pairwise-add sequence
 *      that works identically on ARMv7 (this device) and AArch64 (Move's own
 *      target, where the bug was never exercised).
 *
 * jv880_plugin.cpp already resamples its native 64kHz DSP output to 44100Hz
 * internally (JV880_SAMPLE_RATE / MOVE_SAMPLE_RATE in the vendored file) and
 * already runs its own background "emu thread" that does the actual
 * real-time MCU stepping into an internal ring -- render_block() here is a
 * drain of whatever that thread has already produced, not a synchronous
 * render, so this shim's timer loop just needs to poll it often enough that
 * ForceAudioIn's own ring never starves, using the same elapsed-real-time
 * cadence force-acid/force-maze use (never assume a fixed callback period).
 *
 * Build: see scripts/build.sh (native armhf under QEMU, links -lasound
 * -lpthread -lrt, same toolchain as force-acid/force-maze).
 */

#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

#include "rtmidi/RtMidi.h"
#include "plugin_api_v1.h"
#include "forceAudioInject.h"

extern "C" plugin_api_v2_t *move_plugin_init_v2(const void *host);

/* ---------------------------------------------------------------------------
 * Globals
 * ------------------------------------------------------------------------- */
static std::atomic<bool> g_run{true};
static std::mutex        g_lock;        /* serialises every call into the core */
static plugin_api_v2_t  *g_api  = nullptr;
static void             *g_inst = nullptr;

static ai_shm_t *g_shm = nullptr;
static std::atomic<uint64_t> g_ring_drops{0};

static std::string g_chain_params_json;
static std::string g_ctrl_sock_path = "/tmp/jv880_ctrl.sock";
static bool         g_verbose = false;
static unsigned     g_mix_slot = 0;   /* which /forceAudioInjectN this instance owns */

/* ---------------------------------------------------------------------------
 * CC -> set_param, for a Force Q-Link-mapped MIDI track. All 14 of Mini-JV's
 * chain_params (module.json) fit in one Q-Link bank (16 knobs), so nothing
 * needs curating out to the web panel the way a bigger param set would.
 * Every one of these is integer-typed on the plugin side (v2_set_param uses
 * atoi() throughout -- confirmed by reading it, not assumed), unlike
 * force-maze's float params, so there is only one PARAMS kind here: a plain
 * linear int range formatted with no decimal point.
 *
 * "preset" and "performance" are capped to what a single 0-127 CC sweep can
 * address (the plugin itself supports more presets once expansion ROMs are
 * loaded, e.g. up to 192+) -- deeper preset/bank navigation is a web-panel
 * job, per track-templates.md's guidance for a param that doesn't fit one
 * knob's resolution. Q-Link still reaches the full base bank (0-127).
 * ------------------------------------------------------------------------- */
struct ParamSpec {
    const char *key;
    int         lo, hi;
    int         cc;
};
static const ParamSpec PARAMS[] = {
    { "mode",                          0,   1,   20 },  /* 0=Patch, 1=Performance */
    { "preset",                        0,   127, 21 },
    { "performance",                   0,   47,  22 },
    { "octave_transpose",             -4,   4,   23 },
    { "macro_cutoff",                  0,   127, 24 },
    { "macro_resonance",               0,   127, 25 },
    { "macro_attack",                  0,   127, 26 },
    { "macro_decay",                   0,   127, 27 },
    { "macro_sustain",                 0,   127, 28 },
    { "macro_release",                 0,   127, 29 },
    { "macro_tvf_env_depth",         -63,   63,  30 },
    { "macro_lfo_depth",             -63,   63,  31 },
    { "nvram_patchCommon_reverblevel", 0,   127, 32 },
    { "nvram_patchCommon_choruslevel", 0,   127, 33 },
};
static const int N_PARAMS = (int)(sizeof(PARAMS) / sizeof(PARAMS[0]));
static std::unordered_map<int, int> g_cc2param;  /* CC -> index into PARAMS, built at startup */
static int g_ctrl_ch = 0;                        /* 0-based; --control-channel is 1-16 */

static void apply_cc(int idx, int value /* 0..127 */) {
    const ParamSpec &p = PARAMS[idx];
    int v = p.lo + (int)std::lround((p.hi - p.lo) * (value / 127.0));
    char buf[16];
    std::snprintf(buf, sizeof(buf), "%d", v);
    { std::lock_guard<std::mutex> lk(g_lock); g_api->set_param(g_inst, p.key, buf); }
    if (g_verbose) fprintf(stderr, "[jv880] cc %d -> %s = %s\n", p.cc, p.key, buf);
}

/* ---------------------------------------------------------------------------
 * Shared-memory ring setup (producer side). Mini-JV is audio_out-only, mono
 * synth output panned by the plugin itself into stereo (chain_params has no
 * audio_in), same shape as force-maze's ring use.
 * ------------------------------------------------------------------------- */
static char g_shm_name[24];

static bool shm_setup() {
    ai_shm_name(g_mix_slot, g_shm_name, sizeof(g_shm_name));
    shm_unlink(g_shm_name);  /* we are the sole producer for this slot -- start clean */
    int fd = shm_open(g_shm_name, O_CREAT | O_RDWR, 0666);
    if (fd < 0) { perror("shm_open"); return false; }
    if (ftruncate(fd, AI_SHM_BYTES) != 0) { perror("ftruncate"); close(fd); return false; }
    void *m = mmap(nullptr, AI_SHM_BYTES, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (m == MAP_FAILED) { perror("mmap"); return false; }

    g_shm = (ai_shm_t *)m;
    memset(g_shm, 0, AI_SHM_BYTES);
    g_shm->rate = (uint32_t)MOVE_SAMPLE_RATE;  /* jv880_plugin.cpp already resamples to this */
    g_shm->channels = 2;
    g_shm->enabled = 1;
    g_shm->gain = 1.0f;
    g_shm->channel_mask = AI_CHAN_LR;
    __atomic_store_n(&g_shm->magic, AI_MAGIC, __ATOMIC_RELEASE);
    return true;
}

static void ring_push(const float *interleaved, uint32_t frames) {
    if (!g_shm) return;
    uint32_t head = g_shm->head;                                     /* sole producer */
    uint32_t tail = __atomic_load_n(&g_shm->tail, __ATOMIC_ACQUIRE);
    uint32_t space = (AI_RING_FRAMES - 1) - ((head - tail) & (AI_RING_FRAMES - 1));

    uint32_t take = frames;
    if (take > space) {
        take = space;
        g_ring_drops++;
    }
    for (uint32_t i = 0; i < take; i++) {
        uint32_t fr = (head + i) & (AI_RING_FRAMES - 1);
        float *dst = &g_shm->ring[(size_t)fr * AI_MAX_CH];
        dst[0] = interleaved[2 * i];
        dst[1] = interleaved[2 * i + 1];
    }
    __atomic_store_n(&g_shm->head, (head + take) & (AI_RING_FRAMES - 1), __ATOMIC_RELEASE);
    g_shm->frames_written += take;
}

/* ---------------------------------------------------------------------------
 * RtMidi input -- notes/other channel voice messages pass straight through
 * to on_midi (Patch mode listens on a single "basic channel", Performance
 * mode routes per-part internally -- see jv880_plugin.cpp), Control Change
 * on the control channel is intercepted for the Q-Link CC table above.
 * ------------------------------------------------------------------------- */
static void on_midi_cb(double /*dt*/, std::vector<unsigned char> *msg, void * /*ud*/) {
    if (!msg || msg->empty()) return;
    const uint8_t *b = msg->data();
    size_t len = msg->size();
    uint8_t status = b[0];
    uint8_t type = status & 0xF0;
    uint8_t chan = status & 0x0F;

    if (type == 0xB0 && len >= 3 && chan == (uint8_t)g_ctrl_ch) {
        auto it = g_cc2param.find(b[1]);
        if (it != g_cc2param.end()) apply_cc(it->second, b[2]);
        return;
    }

    std::lock_guard<std::mutex> lk(g_lock);
    g_api->on_midi(g_inst, b, (int)len, 0 /* MOVE_MIDI_SOURCE_INTERNAL */);
}

/* ---------------------------------------------------------------------------
 * Timer thread -- drains jv880_plugin.cpp's own already-real-time-computed
 * output (see the top-of-file note: its background "emu thread" does the
 * actual MCU stepping, render_block() here just pulls what's ready) into
 * ForceAudioIn's ring, at the true elapsed-wall-clock cadence rather than a
 * fixed period, same technique and same reasoning as force-acid/force-maze's
 * timer loops: sleep_for() jitter on a plain SCHED_OTHER thread means a fixed
 * "always ask for N frames" cadence silently falls behind real time.
 * ------------------------------------------------------------------------- */
static std::atomic<double>   g_max_wake_ms{0.0};
static std::atomic<uint64_t> g_late_wakes{0};
static std::atomic<uint64_t> g_total_wakes{0};

/* Clock-rate compensation: the Force's real ALSA-clocked capture consumes
 * samples very slightly faster than this software timer's notion of
 * elapsed time (measured ~1000ppm on this device -- see force-maze's own
 * maze_host.cpp, where this was originally derived and proven live).
 * Missing here until now -- jv_host.cpp/dx7_host.cpp were built from that
 * same timer-loop pattern but this one constant didn't get carried over,
 * which is the direct cause of the audible "wobble"/crackle reported on
 * both. Renders very slightly ahead of raw wall-clock time to match the
 * hardware's true rate instead of chasing it with an ever-growing buffer. */
constexpr double RATE_CORRECTION = 44100.0 / (44100.0 - 45.0);   /* ~1.00102 */

static void timer_loop() {
    constexpr int MAX_FRAMES = 4096;
    int16_t  pcm[MAX_FRAMES * 2];
    float    flt[MAX_FRAMES * 2];
    const auto period = std::chrono::microseconds(1500);

    using clock = std::chrono::steady_clock;
    auto prev = clock::now();
    auto last_stat = prev;

    while (g_run.load()) {
        std::this_thread::sleep_for(period);
        auto now = clock::now();
        double secs = std::chrono::duration<double>(now - prev).count();
        prev = now;

        double ms = secs * 1000.0;
        double seen_max = g_max_wake_ms.load();
        if (ms > seen_max) g_max_wake_ms.store(ms);
        g_total_wakes++;

        int frames = (int)std::lround(secs * MOVE_SAMPLE_RATE * RATE_CORRECTION);
        if (frames < 1) frames = 1;
        if (frames > 400) g_late_wakes++;
        if (frames > MAX_FRAMES) frames = MAX_FRAMES;

        {
            std::lock_guard<std::mutex> lk(g_lock);
            g_api->render_block(g_inst, pcm, frames);
        }
        for (int i = 0; i < frames * 2; i++) flt[i] = pcm[i] / 32768.0f;
        ring_push(flt, (uint32_t)frames);

        if (now - last_stat >= std::chrono::seconds(5)) {
            last_stat = now;
            uint32_t backlog = g_shm ? (uint32_t)((g_shm->head - __atomic_load_n(&g_shm->tail, __ATOMIC_ACQUIRE))
                                                   & (AI_RING_FRAMES - 1))
                                      : 0;
            fprintf(stderr, "[jv880] render thread: max wake gap %.1fms, %llu/%llu wakes > 9ms, ring drops %llu, "
                            "backlog %u frames\n",
                    g_max_wake_ms.load(),
                    (unsigned long long)g_late_wakes.load(), (unsigned long long)g_total_wakes.load(),
                    (unsigned long long)g_ring_drops.load(), backlog);
        }
    }
}

/* ---------------------------------------------------------------------------
 * Control socket -- same plain newline-terminated protocol as force-maze's
 * maze_host.cpp, one connection per request:
 *
 *   SET <key> <value>\n   -> "OK\n" or "ERR\n"
 *   GET <key>\n           -> "<value>\n" or "ERR\n"
 *   DESCRIBE\n            -> the module's chain_params JSON, one line
 *   NOTE <note> <vel>\n   -> trigger a note (web UI "audition" button)
 *
 * "mix.*" keys are host-level output-mix controls read by forceAudioIn.so
 * directly from the shared-memory struct (see forceAudioInject.h) -- handled
 * here rather than forwarded to g_api->set_param/get_param, which only knows
 * jv880_plugin.cpp's own chain_params and would just error on an unknown key.
 * ------------------------------------------------------------------------- */
static bool handle_mix_set(const std::string &key, const std::string &val) {
    if (key == "mix.enabled") {
        g_shm->enabled = (val == "1" || val == "true") ? 1u : 0u;
        return true;
    }
    if (key == "mix.gain") {
        g_shm->gain = std::strtof(val.c_str(), nullptr) / 100.0f;
        return true;
    }
    if (key == "mix.channel") {
        g_shm->channel_mask = (val == "L") ? AI_CHAN_L : (val == "R") ? AI_CHAN_R : AI_CHAN_LR;
        return true;
    }
    return false;
}
static bool handle_mix_get(const std::string &key, std::string &out) {
    if (key == "mix.enabled") { out = g_shm->enabled ? "1" : "0"; return true; }
    if (key == "mix.gain") {
        char b[32]; std::snprintf(b, sizeof(b), "%.1f", g_shm->gain * 100.0f);
        out = b; return true;
    }
    if (key == "mix.channel") {
        uint32_t m = g_shm->channel_mask;
        out = (m == AI_CHAN_L) ? "L" : (m == AI_CHAN_R) ? "R" : "L+R";
        return true;
    }
    return false;
}

static void handle_ctrl_line(int fd, const std::string &line) {
    char cmd[16] = {0}, key[64] = {0}, val[256] = {0};
    if (sscanf(line.c_str(), "%15s", cmd) != 1) { send(fd, "ERR\n", 4, 0); return; }

    if (!strcmp(cmd, "DESCRIBE")) {
        std::string reply = g_chain_params_json + "\n";
        send(fd, reply.c_str(), reply.size(), 0);
        return;
    }
    if (!strcmp(cmd, "SET") && sscanf(line.c_str(), "%*s %63s %255[^\n]", key, val) == 2) {
        if (handle_mix_set(key, val)) { send(fd, "OK\n", 3, 0); return; }
        std::lock_guard<std::mutex> lk(g_lock);
        g_api->set_param(g_inst, key, val);
        send(fd, "OK\n", 3, 0);
        return;
    }
    if (!strcmp(cmd, "GET") && sscanf(line.c_str(), "%*s %63s", key) == 1) {
        std::string mix_val;
        if (handle_mix_get(key, mix_val)) {
            std::string reply = mix_val + "\n";
            send(fd, reply.c_str(), reply.size(), 0);
            return;
        }
        // 256 bytes was fine for ordinary scalar params but silently
        // truncated the first large list-shaped key added here (patch_list,
        // same class of bug chain_params' own startup fetch hit -- see
        // DESIGN.md). Sized generously for any current or future bulk key.
        static char buf[65536];
        int n;
        { std::lock_guard<std::mutex> lk(g_lock);
          n = g_api->get_param(g_inst, key, buf, sizeof(buf)); }
        if (n <= 0) { send(fd, "ERR\n", 4, 0); return; }
        std::string reply(buf, n); reply += "\n";
        send(fd, reply.c_str(), reply.size(), 0);
        return;
    }
    if (!strcmp(cmd, "NOTE")) {
        int note = 60, vel = 100;
        sscanf(line.c_str(), "%*s %d %d", &note, &vel);
        uint8_t on[3]  = { 0x90, (uint8_t)note, (uint8_t)vel };
        uint8_t off[3] = { 0x80, (uint8_t)note, 0 };
        { std::lock_guard<std::mutex> lk(g_lock);
          g_api->on_midi(g_inst, on, 3, 0); }
        std::thread([off]() {
            std::this_thread::sleep_for(std::chrono::milliseconds(150));
            std::lock_guard<std::mutex> lk(g_lock);
            g_api->on_midi(g_inst, off, 3, 0);
        }).detach();
        send(fd, "OK\n", 3, 0);
        return;
    }
    send(fd, "ERR\n", 4, 0);
}

static void ctrl_server_loop(int lfd) {
    while (g_run.load()) {
        int cfd = accept(lfd, nullptr, nullptr);
        if (cfd < 0) continue;
        char buf[512];
        ssize_t n = recv(cfd, buf, sizeof(buf) - 1, 0);
        if (n > 0) {
            buf[n] = 0;
            std::string line(buf);
            size_t nl = line.find('\n');
            if (nl != std::string::npos) line.resize(nl);
            if (g_verbose) fprintf(stderr, "[jv880] ctrl: %s\n", line.c_str());
            handle_ctrl_line(cfd, line);
        }
        close(cfd);
    }
}

static int ctrl_socket_listen(const std::string &path) {
    unlink(path.c_str());
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return -1; }
    struct sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, path.c_str(), sizeof(addr.sun_path) - 1);
    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) { perror("bind"); close(fd); return -1; }
    chmod(path.c_str(), 0666);
    if (listen(fd, 8) != 0) { perror("listen"); close(fd); return -1; }
    return fd;
}

/* ---------------------------------------------------------------------------
 * main
 * ------------------------------------------------------------------------- */
static void on_signal(int) { g_run.store(false); }

static void usage(const char *me) {
    fprintf(stderr,
        "usage: %s [options]\n"
        "  -v                    verbose\n"
        "  --client NAME         ALSA client name       (default: Mockba JV880)\n"
        "  --module-dir PATH     dir containing module.json + roms/ (default: .)\n"
        "  --ctrl-sock PATH      control socket path     (default: /tmp/jv880_ctrl.sock)\n"
        "  --control-channel N   1-16, CC-in for the Q-Link track (default: 1)\n"
        "  --mix-slot N          voice slot 0..%d for forceAudioIn.so (default: 0) -\n"
        "                        each simultaneous voice needs a distinct slot\n",
        me, AI_MAX_VOICES - 1);
}

int main(int argc, char **argv) {
    std::string client = "Mockba JV880";
    std::string module_dir = ".";

    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if      (a == "-v")                        g_verbose = true;
        else if (a == "--client"     && i+1 < argc) client = argv[++i];
        else if (a == "--module-dir" && i+1 < argc) module_dir = argv[++i];
        else if (a == "--ctrl-sock"  && i+1 < argc) g_ctrl_sock_path = argv[++i];
        else if (a == "--control-channel" && i+1 < argc) g_ctrl_ch = (std::atoi(argv[++i]) - 1) & 0x0F;
        else if (a == "--mix-slot" && i+1 < argc) {
            int s = std::atoi(argv[++i]);
            if (s < 0 || s >= AI_MAX_VOICES) { usage(argv[0]); return 2; }
            g_mix_slot = (unsigned)s;
        }
        else { usage(argv[0]); return (a == "-h" || a == "--help") ? 0 : 2; }
    }

    for (int i = 0; i < N_PARAMS; i++) g_cc2param[PARAMS[i].cc] = i;

    if (!shm_setup()) { fprintf(stderr, "[jv880] shared memory setup failed\n"); return 1; }

    g_api = move_plugin_init_v2(nullptr);
    if (!g_api || g_api->api_version != 2) {
        fprintf(stderr, "[jv880] core init failed\n"); return 1;
    }
    g_inst = g_api->create_instance(module_dir.c_str(), nullptr);
    if (!g_inst) { fprintf(stderr, "[jv880] create_instance failed (ROMs missing from %s/roms/?)\n",
                           module_dir.c_str()); return 1; }

    /* ROM/patch loading happens on jv880_plugin.cpp's own background thread
     * (create_instance returns immediately -- confirmed by reading it, see
     * jv_host.cpp's top-of-file note). render_block/on_midi are already
     * guarded to no-op until that finishes, so the only thing THIS shim
     * needs to wait for is chain_params being populated, for the web
     * panel's /describe. Bounded (~5s) so a ROM problem degrades to an
     * empty chain_params rather than hanging startup forever. */
    {
        char buf[16];
        for (int waited_ms = 0; waited_ms < 5000; waited_ms += 100) {
            int n = g_api->get_param(g_inst, "loading_complete", buf, sizeof(buf));
            if (n > 0 && buf[0] == '1') break;
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
    }
    {
        /* chain_params here is much larger than force-maze/force-acid's own
         * (full per-tone metadata x4 tones, part/performance levels, etc.)
         * -- empirically needed more than 16KB; sized generously rather
         * than trimmed to the exact observed size. */
        static char buf[131072];
        int n = g_api->get_param(g_inst, "chain_params", buf, sizeof(buf));
        g_chain_params_json = (n > 0) ? std::string(buf, n) : std::string("{}");
        if (n <= 0)
            fprintf(stderr, "[jv880] warning: chain_params not found (module.json missing from %s, "
                             "or ROMs still loading after 5s -- check loading_status)\n",
                    module_dir.c_str());
    }

    RtMidiIn *in = nullptr;
    try {
        in = new RtMidiIn(RtMidi::UNSPECIFIED, client, 256);
        in->openVirtualPort("In");
        in->ignoreTypes(true, true, true);
        in->setCallback(&on_midi_cb, nullptr);
    } catch (RtMidiError &e) {
        fprintf(stderr, "[jv880] MIDI setup failed: %s\n", e.getMessage().c_str());
        return 1;
    }

    int lfd = ctrl_socket_listen(g_ctrl_sock_path);
    if (lfd < 0) { fprintf(stderr, "[jv880] control socket setup failed\n"); return 1; }

    std::signal(SIGINT, on_signal);
    std::signal(SIGTERM, on_signal);

    fprintf(stderr,
        "[jv880] up. port '%s:In'  ctrl socket %s  shm %s  ctrl ch %d\n"
        "[jv880] route a MIDI track to '%s:In' for notes and CC (Q-Link); audio\n"
        "[jv880] is mixed into the Force's capture input via ForceAudioIn (must be enabled).\n",
        client.c_str(), g_ctrl_sock_path.c_str(), g_shm_name, g_ctrl_ch + 1, client.c_str());

    std::thread timer(timer_loop);
    std::thread ctrl(ctrl_server_loop, lfd);

    while (g_run.load()) std::this_thread::sleep_for(std::chrono::milliseconds(100));

    timer.join();
    close(lfd);
    unlink(g_ctrl_sock_path.c_str());
    {
        std::lock_guard<std::mutex> lk(g_lock);
        g_api->destroy_instance(g_inst);
    }
    delete in;
    if (g_shm) { munmap(g_shm, AI_SHM_BYTES); shm_unlink(g_shm_name); }
    fprintf(stderr, "[jv880] bye\n");
    return 0;
}
