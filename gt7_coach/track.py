"""Circuit map and corner-stat extraction.

Currently hard-coded to Laguna Seca in the Porsche 911 GT3 R. Each corner is an
(x, z) coordinate with a radius; the car is "in" a corner when it's inside that
radius. The lap is split into two halves so the first half can be analysed
mid-lap (pipelined) while the driver is still on the second half.

(Teaching the coach new tracks automatically — rather than hand-typing these
coordinates — is the planned next step.)
"""

from .telemetry import dist, get_f

# Split into two halves for pipelined analysis:
#   First half  analysed after S2 (Corkscrew) — ready on the Andretti straight
#   Second half analysed at lap end
CORNER_ORDER = [
    "T1", "T2", "T3", "T4",                                        # first half
    "T5_Corkscrew", "T6_Corkscrew_exit", "T7", "T8_Rainey", "T9_Andretti"  # second half
]

FIRST_HALF  = ["T1", "T2", "T3", "T4"]
SECOND_HALF = ["T5_Corkscrew", "T6_Corkscrew_exit", "T7", "T8_Rainey", "T9_Andretti"]

CORNERS = {
    "T1":                {"pos": (-384.5, 68.2),  "radius": 40, "name": "Turn 1"},
    "T2":                {"pos": (-323.3, 27.7),  "radius": 40, "name": "Turn 2"},
    "T3":                {"pos": (-58.2, 338.0),  "radius": 40, "name": "Turn 3"},
    "T4":                {"pos": (243.9, 450.8),  "radius": 40, "name": "Turn 4"},
    "T5_Corkscrew":      {"pos": (385.9, 67.5),   "radius": 40, "name": "Corkscrew"},
    "T6_Corkscrew_exit": {"pos": (404.6, -43.6),  "radius": 40, "name": "Corkscrew exit"},
    "T7":                {"pos": (353.4, -231.5), "radius": 40, "name": "Turn 7"},
    "T8_Rainey":         {"pos": (155.2, -263.6), "radius": 40, "name": "Rainey"},
    "T9_Andretti":       {"pos": (-38.9, -420.0), "radius": 40, "name": "Andretti hairpin"},
}

SECTORS = {
    "S1": {"pos": (-58.2, 338.0),   "radius": 50},
    "S2": {"pos": (385.9, 67.5),    "radius": 50},   # Corkscrew — trigger first-half analysis
    "S3": {"pos": (-278.0, -244.0), "radius": 50},
}


def get_corner_stats(rows, corner):
    """Summarise a single corner from a lap's packets (min/entry speed, braking)."""
    cx, cz  = corner["pos"]
    packets = [p for p in rows if dist(get_f(p, "pos_x"), get_f(p, "pos_z"), cx, cz) < corner["radius"]]
    if not packets:
        return None
    speeds = [get_f(p, "speed") for p in packets]
    brakes = [get_f(p, "brake") for p in packets]
    brake_pos = None
    for p in packets:
        if get_f(p, "brake") > 20:
            brake_pos = (get_f(p, "pos_x"), get_f(p, "pos_z"))
            break
    return {
        "min_speed_mph":   round(min(speeds), 1),
        "entry_speed_mph": round(next((get_f(p, "speed") for p in packets if get_f(p, "brake") > 20), speeds[0]), 1),
        "max_brake":       round(max(brakes), 1),
        "brake_pos":       brake_pos,
    }


def get_brake_dist(stats, corner):
    """Distance from where braking began to the corner apex, or None."""
    if not stats or not stats.get("brake_pos"):
        return None
    bp = stats["brake_pos"]
    return dist(bp[0], bp[1], corner["pos"][0], corner["pos"][1])
