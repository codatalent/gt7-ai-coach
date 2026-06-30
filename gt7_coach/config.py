"""Central configuration for the GT7 AI Coach.

Everything that you might reasonably want to change without touching code lives
here: the PS5's address, the telemetry ports, cue timings, and the engineer's
canned phrases. (A future step moves these into an external config file; for now
this single module is the one place to edit.)
"""

# ── NETWORK ──────────────────────────────────────────────────────────────────
PS5_IP    = "192.168.1.248"   # your PlayStation's IP on the local network
SEND_PORT = 33739             # heartbeat port the PS5 listens on
RECV_PORT = 33740             # port the telemetry stream arrives on

# GT7 simulator-interface key. The first 32 bytes are the Salsa20 key.
KEY = b"Simulator Interface Packet GT7 ver 0.0"

# ── AI MODEL ─────────────────────────────────────────────────────────────────
MODEL = "claude-opus-4-5"     # Anthropic model used for all coaching generation

# ── CUE TIMING ───────────────────────────────────────────────────────────────
CUE_LEAD_TIME    = 2.5   # seconds before the corner a cue should finish landing
CUE_DURATION     = 3.5   # fallback spoken-cue length if it can't be measured
MAX_CUES_PER_LAP = 3     # across both halves combined
NEXT_N_CORNERS   = 2     # only ever cue the next N corners ahead

# ── ENGINEER VOICE ───────────────────────────────────────────────────────────
# Spoken if a crash is detected — the coach checks you're okay before resuming.
CRASH_PHRASES = [
    "Nick, are you alright? Take a breath, no rush.",
    "Hey, don't worry about that. Car can be fixed. You okay?",
    "Nick, stay calm. Tell me you're okay when you can.",
    "These things happen. Take your time, no pressure.",
    "Box if you need to. What's the damage looking like?",
]

# (elapsed_seconds, line) — gentle warm-up chatter on laps 1-2 before coaching.
WARMUP_CHAT = [
    (30,  "No rush on lap one, just get some heat in the tyres."),
    (60,  "How's the car feeling? We'll start coaching from lap three."),
    (90,  "Brakes should be coming in nicely now."),
    (120, "Good, keep it smooth. One more lap and we're live."),
]
