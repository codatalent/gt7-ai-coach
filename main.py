"""GT7 AI Coach — runnable entry point.

Wires the package together: opens the telemetry socket, starts the audio worker
and the background intro/warm-up/heartbeat threads, then runs the main loop that
reads packets, tracks laps and sectors, fires the pipelined corner analysis, and
plays coaching cues for the next corners.

Run with:  python main.py
Requires:  ANTHROPIC_API_KEY in the environment, and your PS5_IP set in
           gt7_coach/config.py.
"""

import socket
import threading
import time

from gt7_coach.config import (
    PS5_IP, SEND_PORT, RECV_PORT,
    CUE_LEAD_TIME, CUE_DURATION, NEXT_N_CORNERS, WARMUP_CHAT,
)
from gt7_coach.crypto import decrypt
from gt7_coach.telemetry import parse, dist, time_to_corner
from gt7_coach.track import CORNERS, SECTORS, CORNER_ORDER, FIRST_HALF, SECOND_HALF
from gt7_coach.audio import (
    start_audio_worker, play_file, speak, speak_immediate, get_audio_duration,
    generate_audio,
)
from gt7_coach.coach import generate_intro, generate_lap_summary, analyse_corners
from gt7_coach.crash import check_for_crash
from gt7_coach.storage import load_previous_laps

# ── SHARED STATE ─────────────────────────────────────────────────────────────
# Mutated across the main loop and the background analysis threads, so it lives
# at module level guarded by analysis_lock for the cue dicts.
current_lap      = None
lap_data         = []
lap_history      = {}
cue_state        = {}
sector_state     = {}
corner_passed    = set()
active_cues      = {}   # merged first + second half cues for the current lap
cue_durations    = {}
coaching_active  = False
analysis_lock    = threading.Lock()
lap_start_time   = None
best_lap         = None
best_sectors     = {}
session_start    = time.time()
warmup_spoken    = []
s2_triggered     = False  # has first-half analysis been triggered this lap

previous_laps    = []


# ── BACKGROUND THREADS ───────────────────────────────────────────────────────
def send_heartbeat(sock):
    """Keep the PS5 sending telemetry by pinging it ten times a second."""
    while True:
        sock.sendto(b"A", (PS5_IP, SEND_PORT))
        threading.Event().wait(0.1)


def deliver_intro():
    """Generate and speak the start-of-session intro once data has settled."""
    time.sleep(3)
    intro = generate_intro(previous_laps)
    print(f"[Intro] {intro}")
    speak_immediate(intro)


def warmup_chatter():
    """Gentle radio chatter on laps 1-2 before coaching goes live."""
    while True:
        if current_lap is not None and current_lap > 2:
            break
        elapsed = time.time() - session_start
        for t, line in WARMUP_CHAT:
            if elapsed >= t and t not in warmup_spoken:
                warmup_spoken.append(t)
                speak(line)
                print(f"  [Leighton] {line}")
        time.sleep(2)


def get_next_corners(passed_set, n=NEXT_N_CORNERS):
    return [c for c in CORNER_ORDER if c not in passed_set][:n]


# ── PIPELINED ANALYSIS ───────────────────────────────────────────────────────
def run_first_half(lap_a, lap_b, lap_num):
    """Triggered at S2 crossing — analyses T1-T4, ready on the Andretti straight."""
    global active_cues, cue_durations, coaching_active
    try:
        cues  = analyse_corners(lap_a, lap_b, lap_num, FIRST_HALF, "first half")
        files = generate_audio(cues, lap_num, suffix="_fh")
        durs  = {c: get_audio_duration(f) for c, f in files.items()}
        with analysis_lock:
            active_cues.update(files)
            cue_durations.update(durs)
            coaching_active = True
        print(f"  First half cues ready for lap {lap_num + 1}")
    except Exception as e:
        print(f"  First half analysis error: {e}")


def run_second_half_and_summary(lap_a, lap_b, lap_num, lap_time):
    """Triggered at lap end — analyses T5-T9 and delivers the lap summary."""
    global active_cues, cue_durations, best_lap
    try:
        # Lap summary first
        summary = generate_lap_summary(lap_a, lap_b, lap_num, lap_time, best_lap)
        print(f"Summary: {summary}")
        speak_immediate(summary)

        if best_lap is None or lap_time < best_lap:
            best_lap = lap_time

        cues  = analyse_corners(lap_a, lap_b, lap_num, SECOND_HALF, "second half")
        files = generate_audio(cues, lap_num, suffix="_sh")
        durs  = {c: get_audio_duration(f) for c, f in files.items()}
        with analysis_lock:
            active_cues.update(files)
            cue_durations.update(durs)
        print(f"  Second half cues ready for lap {lap_num + 1}")
    except Exception as e:
        print(f"  Second half analysis error: {e}")


# ── MAIN LOOP ────────────────────────────────────────────────────────────────
def main():
    global current_lap, lap_data, lap_start_time, cue_state, corner_passed
    global sector_state, s2_triggered, active_cues, cue_durations, coaching_active
    global previous_laps

    start_audio_worker()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", RECV_PORT))
    sock.settimeout(10)
    threading.Thread(target=send_heartbeat, args=(sock,), daemon=True).start()

    previous_laps = load_previous_laps()
    threading.Thread(target=deliver_intro, daemon=True).start()
    threading.Thread(target=warmup_chatter, daemon=True).start()

    print("GT7 AI Coach — Leighton is ready for Nick")
    print("Laps 1-2: Recording silently | Lap 3+: Coaching active")
    print("First half cues pipeline after S2 | Second half after lap end\n")

    while True:
        try:
            data, addr = sock.recvfrom(4096)
            d     = decrypt(data)
            p     = parse(d)
            x, z  = p["pos_x"], p["pos_z"]
            speed = p["speed"]
            now   = time.time()

            check_for_crash(speed, now)

            # ── LAP CHANGE ────────────────────────────────────────────────────
            if p["lap"] != current_lap:
                if current_lap is not None and len(lap_data) > 500:
                    lap_time_val = p["last_lap"] / 1000.0 if p["last_lap"] > 0 else 0
                    lap_history[current_lap] = lap_data

                    if current_lap >= 2 and (current_lap - 1) in lap_history:
                        threading.Thread(
                            target=run_second_half_and_summary,
                            args=(lap_history[current_lap - 1], lap_history[current_lap],
                                  current_lap, lap_time_val),
                            daemon=True
                        ).start()

                current_lap    = p["lap"]
                lap_data       = []
                lap_start_time = now
                cue_state      = {name: False for name in CORNERS}
                corner_passed  = set()
                sector_state   = {s: False for s in SECTORS}
                s2_triggered   = False
                # Clear cues at lap start — a fresh set is built by the pipeline
                with analysis_lock:
                    active_cues   = {}
                    cue_durations = {}

                if current_lap > 0:
                    speak(f"Lap {current_lap}")
                    print(f"\nLap {current_lap}")
                print(f"  {'Recording silently' if current_lap <= 2 else 'Coaching active'}")

            lap_data.append(p)

            # ── SECTOR TIMING + S2 PIPELINE TRIGGER ───────────────────────────
            if lap_start_time and current_lap > 0:
                for sname, sector in SECTORS.items():
                    cx, cz = sector["pos"]
                    if dist(x, z, cx, cz) < sector["radius"] and not sector_state[sname]:
                        sector_state[sname] = True
                        elapsed = now - lap_start_time
                        if elapsed < 1.0:
                            continue

                        delta_str = ""
                        if sname in best_sectors:
                            delta = elapsed - best_sectors[sname]
                            if delta < 0:
                                delta_str = f", {abs(delta):.1f} up"
                                best_sectors[sname] = elapsed
                            else:
                                delta_str = f", {delta:.1f} down"
                        else:
                            best_sectors[sname] = elapsed

                        snum = list(SECTORS.keys()).index(sname) + 1
                        speak(f"Sector {snum}, {elapsed:.1f}{delta_str}")
                        print(f"  [S{snum}] {elapsed:.1f}s{delta_str}")

                        # S2 crossing — trigger first-half analysis immediately
                        if sname == "S2" and not s2_triggered and current_lap >= 2:
                            if (current_lap - 1) in lap_history and current_lap in lap_history or len(lap_data) > 100:
                                s2_triggered = True
                                lap_b_so_far = list(lap_data)  # snapshot of current lap so far
                                prev         = lap_history.get(current_lap - 1, [])
                                if prev:
                                    threading.Thread(
                                        target=run_first_half,
                                        args=(prev, lap_b_so_far, current_lap),
                                        daemon=True
                                    ).start()
                                    print("  [Pipeline] First half analysis triggered at S2")

            # ── MARK CORNERS PASSED ───────────────────────────────────────────
            for name, corner in CORNERS.items():
                if dist(x, z, corner["pos"][0], corner["pos"][1]) < corner["radius"]:
                    corner_passed.add(name)

            # ── SMART CORNER CUES — next 2 only ───────────────────────────────
            if coaching_active and active_cues:
                next_corners = get_next_corners(corner_passed)
                for name in next_corners:
                    if name not in active_cues or cue_state.get(name):
                        continue
                    corner = CORNERS[name]
                    cx, cz = corner["pos"]
                    d_to   = dist(x, z, cx, cz)
                    ttc    = time_to_corner(d_to, speed)
                    dur    = cue_durations.get(name, CUE_DURATION)
                    if ttc <= dur + CUE_LEAD_TIME:
                        cue_state[name] = True
                        play_file(active_cues[name])
                        print(f"  [{name}] cue — {d_to:.0f}m, {ttc:.1f}s away")

            print(f"Lap: {p['lap']} | {speed:.1f} mph | Pos: ({x:.0f}, {z:.0f})", end="\r")

        except KeyboardInterrupt:
            print("\nLeighton signing off. Good session Nick.")
            break


if __name__ == "__main__":
    main()
