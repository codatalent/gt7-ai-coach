"""Configuration loader for the GT7 AI Coach.

Settings live in an external ``config.yaml`` so you never have to edit code to
change your PS5's IP, the model, or the cue timings. This module loads that file
(if present), overlays it on the built-in defaults, and exposes the result as
plain module-level constants so the rest of the package can just
``from .config import PS5_IP`` as before.

Resolution order (later wins):
    1. the DEFAULTS below
    2. config.yaml  (searched: $GT7_CONFIG, the repo root, the current dir)
    3. the GT7_PS5_IP environment variable (handy override for the one setting
       that changes most often)

Things that are protocol constants or canned content rather than user settings
— the Salsa20 key, the engineer's phrases — stay defined here in code.
"""

import os
from pathlib import Path

# ── DEFAULTS ─────────────────────────────────────────────────────────────────
DEFAULTS = {
    "ps5_ip": "192.168.1.248",
    "model":  "claude-opus-4-5",
    "cue": {
        "lead_time": 2.5,
        "fallback_duration": 3.5,
        "max_per_lap": 3,
        "next_n_corners": 2,
    },
    "ports": {"send": 33739, "recv": 33740},
    "crash": {"min_speed_mph": 37, "drop_mph": 50, "cooldown_s": 15},
}


def _deep_merge(base, override):
    """Recursively overlay ``override`` onto a copy of ``base``."""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _find_config_file():
    """Locate config.yaml: explicit env path, then repo root, then CWD."""
    env_path = os.environ.get("GT7_CONFIG")
    candidates = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path(__file__).resolve().parent.parent / "config.yaml")
    candidates.append(Path.cwd() / "config.yaml")
    for c in candidates:
        if c.is_file():
            return c
    return None


def _load():
    """Build the effective settings dict from defaults + config.yaml + env."""
    cfg  = dict(DEFAULTS)
    path = _find_config_file()
    if path:
        try:
            import yaml
            with open(path) as fh:
                loaded = yaml.safe_load(fh) or {}
            cfg = _deep_merge(cfg, loaded)
        except ImportError:
            print("[config] PyYAML not installed — using built-in defaults. "
                  "Run: pip install -r requirements.txt")
        except Exception as e:
            print(f"[config] Could not read {path} ({e}) — using built-in defaults.")
    else:
        print("[config] No config.yaml found — using built-in defaults. "
              "Copy config.example.yaml to config.yaml to customise.")

    # Single-setting env override for the value that changes most often.
    if os.environ.get("GT7_PS5_IP"):
        cfg["ps5_ip"] = os.environ["GT7_PS5_IP"]
    return cfg


_cfg = _load()

# ── NETWORK ──────────────────────────────────────────────────────────────────
PS5_IP    = _cfg["ps5_ip"]
SEND_PORT = _cfg["ports"]["send"]
RECV_PORT = _cfg["ports"]["recv"]

# GT7 simulator-interface key. The first 32 bytes are the Salsa20 key.
# This is a fixed protocol constant, not a user setting.
KEY = b"Simulator Interface Packet GT7 ver 0.0"

# ── AI MODEL ─────────────────────────────────────────────────────────────────
MODEL = _cfg["model"]

# ── CUE TIMING ───────────────────────────────────────────────────────────────
CUE_LEAD_TIME    = _cfg["cue"]["lead_time"]
CUE_DURATION     = _cfg["cue"]["fallback_duration"]
MAX_CUES_PER_LAP = _cfg["cue"]["max_per_lap"]
NEXT_N_CORNERS   = _cfg["cue"]["next_n_corners"]

# ── CRASH DETECTION ──────────────────────────────────────────────────────────
CRASH_MIN_SPEED = _cfg["crash"]["min_speed_mph"]
CRASH_DROP      = _cfg["crash"]["drop_mph"]
CRASH_COOLDOWN  = _cfg["crash"]["cooldown_s"]

# ── ENGINEER VOICE ───────────────────────────────────────────────────────────
# Canned content rather than settings, so these stay in code.
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
