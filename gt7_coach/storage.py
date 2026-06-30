"""Loading previous-session lap data from CSV.

The coach's start-of-session intro reads back recent laps (fastest time, total
laps, per-corner speeds) from ``lap_*.csv`` files in the working directory.
"""

import csv
import glob


def load_previous_laps():
    """Load every ``lap_*.csv`` with a meaningful number of packets (> 500)."""
    files = sorted(glob.glob("lap_*.csv"))
    laps  = []
    for f in files:
        with open(f) as fh:
            rows = list(csv.DictReader(fh))
        if len(rows) > 500:
            laps.append(rows)
    return laps


def get_session_stats(laps):
    """Return (fastest_time_ms, total_lap_count) from previous session files."""
    fastest_ms = None
    total_laps = len(laps)
    for lap in laps:
        last_lap_ms = next((int(float(p["last_lap"])) for p in reversed(lap) if float(p.get("last_lap", 0)) > 0), 0)
        if last_lap_ms > 0:
            if fastest_ms is None or last_lap_ms < fastest_ms:
                fastest_ms = last_lap_ms
    return fastest_ms, total_laps
