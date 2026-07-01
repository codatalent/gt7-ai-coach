"""The AI brain — turns lap data into spoken coaching.

Three jobs, all delegated to Claude as the in-character race engineer "Leighton":
    generate_intro        — the start-of-session welcome and read of recent form
    generate_lap_summary  — the one-line radio call at the end of each lap
    analyse_corners       — the corner-by-corner cues, picking the worst corners

Each function returns plain text (or a {corner: cue} dict) ready for the audio
layer to speak.
"""

import json
import os

import anthropic

from .config import MODEL
from .telemetry import format_time, format_time_s
from .track import get_corner_stats, get_brake_dist
from .storage import get_session_stats


def _client():
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ── LAP 1 INTRO ──────────────────────────────────────────────────────────────
def generate_intro(laps):
    """Build the start-of-session radio intro from previous-session laps.

    Fires before the first lap is complete, so the circuit isn't known yet —
    the coach learns the track from lap 1 and reads the corners from lap 3.
    """
    fastest_ms, total_laps = get_session_stats(laps)
    fastest_str = format_time(fastest_ms) if fastest_ms else "no time on record"

    if laps:
        prompt = f"""You are Leighton, a GT3 race engineer. Your driver is Nick.

Nick is starting a new session in the Porsche 911 GT3 R.

Previous session stats:
- Total laps completed: {total_laps}
- Fastest lap: {fastest_str}

Give Nick a lap 1 introduction — 4 to 6 sentences. Include:
- A warm greeting by name
- His fastest lap time and total laps completed
- That you'll read the track on the opening lap, run two warm-up laps, then coaching goes live from lap three
- An encouraging send-off

Warm, professional race engineer tone. Natural, like team radio at the start of a session.
Respond with ONLY the spoken text."""
    else:
        prompt = """You are Leighton, a GT3 race engineer. Your driver is Nick.

Nick is starting a session in the Porsche 911 GT3 R on a circuit you haven't seen before. No previous data exists.

Give him a warm welcome — 3 to 4 sentences. Tell him you'll learn the track on his opening lap, run two warm-up laps to build a baseline, then coaching goes live from lap three, and wish him luck.

Respond with ONLY the spoken text."""

    msg = _client().messages.create(
        model=MODEL, max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


# ── LAP SUMMARY ──────────────────────────────────────────────────────────────
def generate_lap_summary(lap_a, lap_b, lap_num, lap_time, best_lap):
    """One-sentence end-of-lap radio call (lap time + good/not)."""
    is_pb     = best_lap is not None and lap_time < best_lap
    delta_str = (f"{abs(lap_time - best_lap):.1f} seconds "
                 f"{'faster, personal best' if is_pb else 'off the best'}") if best_lap else ""

    prompt = f"""You are Leighton, a GT3 race engineer. Your driver is Nick.

Nick just completed lap {lap_num}. Lap time: {format_time_s(lap_time)}. {delta_str}

Give a ONE sentence radio call — lap time and good or not. Max 15 words.
Good example: "Good lap Nick, one forty two, that's a personal best."
Bad example: "Tough one, one forty five, half a second off your best."
Respond with ONLY the spoken text."""

    msg = _client().messages.create(
        model=MODEL, max_tokens=60,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


# ── CORNER CUE GENERATION ────────────────────────────────────────────────────
def analyse_corners(lap_a, lap_b, lap_num, corner_keys, half_label, corners):
    """Compare two laps over a subset of corners and generate spoken cues.

    ``corners`` is the learned track's corner map ({key: {pos, radius, name}}).
    Returns a {corner_key: cue_text} dict for the (up to two) corners in this
    half where the driver lost the most time.
    """
    print(f"\nAnalysing {half_label} corners...")
    corner_data = {}
    deltas      = {}

    for name in corner_keys:
        corner = corners[name]
        sa     = get_corner_stats(lap_a, corner)
        sb     = get_corner_stats(lap_b, corner)
        if sa and sb:
            speed_delta   = round(sb["min_speed_mph"] - sa["min_speed_mph"], 1)
            bda           = get_brake_dist(sa, corner)
            bdb           = get_brake_dist(sb, corner)
            brake_delta_m = round(bda - bdb, 1) if bda and bdb else None
            corner_data[name] = {
                "corner_name":     corner["name"],
                "min_speed_mph":   sb["min_speed_mph"],
                "speed_delta_mph": speed_delta,
                "brake_delta_m":   brake_delta_m,
            }
            deltas[name] = speed_delta

    if not deltas:
        return {}

    # Pick worst corner(s) from this half — max 2 cues per half
    max_cues      = 2
    priority      = sorted(deltas, key=lambda k: deltas[k])[:max_cues]
    priority_data = {k: corner_data[k] for k in priority if k in corner_data}
    print(f"  Priority ({half_label}): {priority}")

    prompt = f"""You are Leighton, a GT3 race engineer. Your driver is Nick.

{half_label} corners needing attention on lap {lap_num} — speeds in mph, brake delta in metres (positive = braked later = better):
{json.dumps(priority_data, indent=2)}

Generate one short cue per corner (max 12 words) spoken just before Nick arrives.

Rules:
- ALWAYS start with the corner_name
- If brake_delta_m is available, say how many metres earlier or later to brake
- Use mph for speed references
- Team radio tone
- Use Nick in at most one cue

Respond ONLY with a JSON object using the corner KEY, no markdown:
{{
  "CORNER_KEY": "cue text"
}}"""

    msg = _client().messages.create(
        model=MODEL, max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    raw  = msg.content[0].text.strip().strip("```json").strip("```").strip()
    cues = json.loads(raw)
    print(f"  Cues ({half_label}):")
    for c, t in cues.items():
        print(f"    {c}: {t}")
    return cues
