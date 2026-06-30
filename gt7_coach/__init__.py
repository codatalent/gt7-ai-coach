"""GT7 AI Coach — a live, AI-driven race engineer for Gran Turismo 7.

Reads the PS5's encrypted telemetry stream over UDP, decrypts it, works out
where you're losing time corner by corner, and speaks a calm coaching cue into
your ear a couple of seconds before each corner.

Package layout:
    config      — all tunable constants in one place (IP, ports, timings, phrases)
    crypto      — Salsa20 decryption of the GT7 packet stream
    telemetry   — packet parsing + unit/maths helpers
    track       — circuit map (corners/sectors) + corner-stat extraction
    audio       — text-to-speech queue and cue playback
    coach       — the Claude-backed intro, lap summary and corner-cue generation
    crash       — rolling-window crash detection
    storage     — load previous CSV laps for the session intro

The runnable entry point lives in ``main.py`` at the repo root.
"""

__version__ = "1.3.0"
