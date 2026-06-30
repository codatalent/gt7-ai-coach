"""Telemetry parsing and the small maths/unit helpers used everywhere.

A decrypted GT7 packet is a fixed binary layout; ``parse`` pulls out the fields
the coach cares about. The rest are pure helpers (unit conversions, distance,
time formatting) kept dependency-free so they're trivial to unit-test.
"""

import struct


# ── UNIT CONVERSIONS ─────────────────────────────────────────────────────────
def kmh_to_mph(kmh):
    return kmh * 0.621371


def mph_to_ms(mph):
    return mph * 0.44704


# ── GEOMETRY ─────────────────────────────────────────────────────────────────
def dist(x1, z1, x2, z2):
    """Planar distance between two (x, z) track coordinates."""
    return ((x1 - x2) ** 2 + (z1 - z2) ** 2) ** 0.5


def time_to_corner(distance_m, speed_mph):
    """Seconds until the car reaches a point ``distance_m`` ahead at ``speed_mph``."""
    if speed_mph < 6:
        return 999
    return distance_m / mph_to_ms(speed_mph)


# ── TIME FORMATTING ──────────────────────────────────────────────────────────
def format_time(ms):
    """Milliseconds → ``M:SS.mmm`` lap-time string."""
    if ms <= 0:
        return "--:--.---"
    s    = ms / 1000.0
    mins = int(s // 60)
    secs = s % 60
    return f"{mins}:{secs:06.3f}"


def format_time_s(seconds):
    """Seconds → a spoken-friendly duration (e.g. '1 minute 42.3')."""
    mins = int(seconds // 60)
    secs = seconds % 60
    return f"{mins} minute {secs:.1f}" if mins > 0 else f"{secs:.1f} seconds"


# ── PACKET PARSING ───────────────────────────────────────────────────────────
def parse(d):
    """Extract the coaching fields from a decrypted GT7 telemetry packet."""
    return {
        "lap":      struct.unpack("h", d[0x74:0x76])[0],
        "speed":    kmh_to_mph(struct.unpack("f", d[0x4C:0x50])[0] * 3.6),
        "brake":    struct.unpack("B", d[0x92:0x93])[0] / 2.55,
        "throttle": struct.unpack("B", d[0x91:0x92])[0] / 2.55,
        "steering": struct.unpack("f", d[0x94:0x98])[0],
        "pos_x":    struct.unpack("f", d[0x04:0x08])[0],
        "pos_z":    struct.unpack("f", d[0x0C:0x10])[0],
        "last_lap": struct.unpack("i", d[0x7C:0x80])[0],
    }


def get_f(p, k):
    """Read field ``k`` from a packet (parsed dict or CSV row) as a float."""
    v = p[k]
    return v if isinstance(v, float) else float(v)
