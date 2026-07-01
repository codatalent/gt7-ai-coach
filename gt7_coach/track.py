"""Circuit map — learned from a lap, then saved and recognised automatically.

The coach used to carry a hand-typed corner map for a single circuit. It now
*learns* any track from one clean lap of telemetry: it finds the corners (the
places you brake and slow for an apex), orders them, splits them into two halves
for pipelined analysis, and drops three sector gates. The result — a ``TrackMap``
— is saved to ``tracks/`` and matched by a geometry fingerprint, so the next time
you drive that circuit it's recognised and loaded instantly. Learn once, never
again.

A corner is an (x, z) apex with a radius; the car is "in" a corner when it's
inside that radius. The lap is split into two halves so the first half can be
analysed mid-lap (pipelined) while the driver is still on the second half.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .config import (
    TRACKS_DIR, CORNER_RADIUS, SECTOR_RADIUS,
    MIN_CORNER_SEP_M, SPEED_SMOOTH_WINDOW, MIN_CORNER_PROMINENCE_MPH,
    TRACK_MATCH_LENGTH_TOL, TRACK_MATCH_EXTENT_TOL,
)
from .telemetry import dist, get_f


# ── THE MAP ──────────────────────────────────────────────────────────────────
@dataclass
class TrackMap:
    """A learned circuit: corners in order, split into halves, plus sector gates."""
    name:         str
    fingerprint:  dict           # {"length": m, "width": m, "height": m}
    corners:      dict           # key -> {"pos": [x, z], "radius": r, "name": str}
    corner_order: list           # ordered corner keys
    first_half:   list
    second_half:  list
    sectors:      dict           # "S1".."S3" -> {"pos": [x, z], "radius": r}

    def to_dict(self):
        return {
            "name": self.name, "fingerprint": self.fingerprint,
            "corners": self.corners, "corner_order": self.corner_order,
            "first_half": self.first_half, "second_half": self.second_half,
            "sectors": self.sectors,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            name=d["name"], fingerprint=d["fingerprint"], corners=d["corners"],
            corner_order=d["corner_order"], first_half=d["first_half"],
            second_half=d["second_half"], sectors=d["sectors"],
        )


# ── CORNER STATS (unchanged — used by the coach) ─────────────────────────────
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


# ── CORNER DETECTION ─────────────────────────────────────────────────────────
def _smooth(values, window):
    """Simple centred moving average — smooths telemetry noise before peak-finding."""
    if window < 2:
        return list(values)
    n    = len(values)
    half = window // 2
    out  = []
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        seg    = values[lo:hi]
        out.append(sum(seg) / len(seg))
    return out


def detect_corners(rows, *, corner_radius=None, sector_radius=None):
    """Find the corners in one lap of telemetry.

    A corner is a local *minimum* in speed with enough prominence — the car
    slows meaningfully, then speeds back up. We smooth the speed trace, find its
    troughs, keep only the prominent ones, and merge any that sit too close
    together (double-apex noise) by keeping the slower point.

    Returns (corners, corner_order, first_half, second_half, sectors).
    """
    corner_radius = corner_radius if corner_radius is not None else CORNER_RADIUS
    sector_radius = sector_radius if sector_radius is not None else SECTOR_RADIUS

    xs     = [get_f(p, "pos_x") for p in rows]
    zs     = [get_f(p, "pos_z") for p in rows]
    speeds = [get_f(p, "speed") for p in rows]
    n      = len(speeds)
    if n < 100:
        raise ValueError("Not enough telemetry to learn a track (need a full lap).")

    sm = _smooth(speeds, SPEED_SMOOTH_WINDOW)

    # Candidate troughs: points at or below their neighbours across a small window.
    half_win   = max(3, SPEED_SMOOTH_WINDOW // 2)
    candidates = []
    for i in range(half_win, n - half_win):
        window = sm[i - half_win:i + half_win + 1]
        if sm[i] <= min(window):
            candidates.append(i)

    # Prominence: from each trough, how far does speed climb on either side
    # before the next rise? A real corner rises by at least the threshold.
    prominent = []
    for i in candidates:
        left_rise  = max(sm[max(0, i - 60):i + 1]) - sm[i]
        right_rise = max(sm[i:min(n, i + 60) + 1]) - sm[i]
        if min(left_rise, right_rise) >= MIN_CORNER_PROMINENCE_MPH:
            prominent.append(i)

    # Merge troughs closer than the minimum separation — keep the slower one.
    merged = []
    for i in prominent:
        if merged and dist(xs[i], zs[i], xs[merged[-1]], zs[merged[-1]]) < MIN_CORNER_SEP_M:
            if sm[i] < sm[merged[-1]]:
                merged[-1] = i
        else:
            merged.append(i)

    if len(merged) < 2:
        raise ValueError(f"Only found {len(merged)} corner(s) — track not learned. "
                         "Drive one clean, representative lap.")

    # Build the ordered corner map.
    corners, order = {}, []
    for idx, i in enumerate(merged, start=1):
        key = f"C{idx}"
        corners[key] = {
            "pos":    [round(xs[i], 1), round(zs[i], 1)],
            "radius": corner_radius,
            "name":   f"Turn {idx}",
        }
        order.append(key)

    # Split into halves for the pipeline (first half analysed mid-lap at S2).
    split       = (len(order) + 1) // 2
    first_half  = order[:split]
    second_half = order[split:]

    # Sector gates sit on real apexes the car is guaranteed to pass. S2 is the
    # boundary between the halves — crossing it fires the first-half analysis.
    def apex_pos(key):
        return list(corners[key]["pos"])

    s1_key = order[max(0, len(order) // 3 - 1)]
    s2_key = first_half[-1]                       # end of first half → pipeline trigger
    s3_key = order[min(len(order) - 1, (2 * len(order)) // 3)]
    sectors = {
        "S1": {"pos": apex_pos(s1_key), "radius": sector_radius},
        "S2": {"pos": apex_pos(s2_key), "radius": sector_radius},
        "S3": {"pos": apex_pos(s3_key), "radius": sector_radius},
    }

    return corners, order, first_half, second_half, sectors


# ── FINGERPRINT + PERSISTENCE ────────────────────────────────────────────────
def fingerprint(rows):
    """A stable geometry signature of a lap: driven length + track extent.

    Racing line varies a little lap to lap, so these are matched with tolerance
    (see ``_matches``) rather than by exact equality.
    """
    xs = [get_f(p, "pos_x") for p in rows]
    zs = [get_f(p, "pos_z") for p in rows]
    length = 0.0
    for i in range(1, len(rows)):
        length += dist(xs[i], zs[i], xs[i - 1], zs[i - 1])
    return {
        "length": round(length, 1),
        "width":  round(max(xs) - min(xs), 1),
        "height": round(max(zs) - min(zs), 1),
    }


def _matches(fp_a, fp_b):
    """True if two fingerprints are the same circuit within tolerance."""
    def close(a, b, tol):
        bigger = max(abs(a), abs(b), 1.0)
        return abs(a - b) / bigger <= tol
    return (close(fp_a["length"], fp_b["length"], TRACK_MATCH_LENGTH_TOL)
            and close(fp_a["width"],  fp_b["width"],  TRACK_MATCH_EXTENT_TOL)
            and close(fp_a["height"], fp_b["height"], TRACK_MATCH_EXTENT_TOL))


def _tracks_dir():
    d = Path(TRACKS_DIR)
    if not d.is_absolute():
        d = Path(__file__).resolve().parent.parent / TRACKS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "track"


def load_saved_tracks():
    """Load every saved TrackMap from the tracks directory."""
    out = []
    for f in sorted(_tracks_dir().glob("*.json")):
        try:
            out.append((f, TrackMap.from_dict(json.loads(f.read_text()))))
        except Exception as e:
            print(f"[track] Skipping unreadable {f.name}: {e}")
    return out


def find_matching_track(fp):
    """Return a saved TrackMap whose fingerprint matches ``fp``, or None."""
    for _f, tm in load_saved_tracks():
        if _matches(fp, tm.fingerprint):
            return tm
    return None


def save_track(track_map):
    """Write a TrackMap to tracks/<slug>.json."""
    path = _tracks_dir() / f"{_slug(track_map.name)}.json"
    path.write_text(json.dumps(track_map.to_dict(), indent=2))
    return path


def learn_or_load(rows):
    """The one call the coach makes after the first lap.

    Fingerprint the lap; if we've driven this circuit before, load the saved
    map. Otherwise learn it from the lap, save it, and return it.

    Returns (track_map, was_recognised).
    """
    fp       = fingerprint(rows)
    existing = find_matching_track(fp)
    if existing:
        return existing, True

    corners, order, first_half, second_half, sectors = detect_corners(rows)
    n_existing = len(load_saved_tracks())
    name       = f"Track {n_existing + 1}"
    tm = TrackMap(
        name=name, fingerprint=fp, corners=corners, corner_order=order,
        first_half=first_half, second_half=second_half, sectors=sectors,
    )
    save_track(tm)
    return tm, False
