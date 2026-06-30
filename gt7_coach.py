import socket
import struct
import threading
import subprocess
import queue
import time
import json
import os
import glob
import csv
import anthropic
from Crypto.Cipher import Salsa20

PS5_IP    = os.environ.get("PS5_IP", "192.168.1.100")  # set the PS5_IP env var to your console's LAN IP
SEND_PORT = 33739
RECV_PORT = 33740
key       = b"Simulator Interface Packet GT7 ver 0.0"

# ── CORNER DEFINITIONS ────────────────────────────────────────────────────────
# Split into two halves for pipelined analysis
# First half analysed after S2 (Corkscrew) — ready on the Andretti straight
# Second half analysed at lap end

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

CUE_LEAD_TIME    = 2.5
CUE_DURATION     = 3.5
MAX_CUES_PER_LAP = 3   # across both halves combined
NEXT_N_CORNERS   = 2

CRASH_PHRASES = [
    "Nick, are you alright? Take a breath, no rush.",
    "Hey, don't worry about that. Car can be fixed. You okay?",
    "Nick, stay calm. Tell me you're okay when you can.",
    "These things happen. Take your time, no pressure.",
    "Box if you need to. What's the damage looking like?",
]

WARMUP_CHAT = [
    (30,  "No rush on lap one, just get some heat in the tyres."),
    (60,  "How's the car feeling? We'll start coaching from lap three."),
    (90,  "Brakes should be coming in nicely now."),
    (120, "Good, keep it smooth. One more lap and we're live."),
]

# ── UTILITIES ──────────────────────────────────────────────────────────────────
def kmh_to_mph(kmh):
    return kmh * 0.621371

def mph_to_ms(mph):
    return mph * 0.44704

def dist(x1, z1, x2, z2):
    return ((x1 - x2)**2 + (z1 - z2)**2) ** 0.5

def format_time(ms):
    if ms <= 0:
        return "--:--.---"
    s    = ms / 1000.0
    mins = int(s // 60)
    secs = s % 60
    return f"{mins}:{secs:06.3f}"

def format_time_s(seconds):
    mins = int(seconds // 60)
    secs = seconds % 60
    return f"{mins} minute {secs:.1f}" if mins > 0 else f"{secs:.1f} seconds"

# ── AUDIO ──────────────────────────────────────────────────────────────────────
audio_queue = queue.Queue()

def audio_worker():
    while True:
        item = audio_queue.get()
        if item is None:
            break
        if os.path.exists(item):
            subprocess.run(["afplay", item])
        else:
            subprocess.run(["say", "-v", "Daniel", "-r", "175", item])
        audio_queue.task_done()

threading.Thread(target=audio_worker, daemon=True).start()

def play_file(filename):
    if audio_queue.qsize() < 2:
        audio_queue.put(filename)

def speak(text):
    if audio_queue.qsize() < 2:
        audio_queue.put(text)

def speak_immediate(text):
    audio_queue.put(text)

def get_audio_duration(filename):
    try:
        result = subprocess.run(["afinfo", filename], capture_output=True, text=True)
        for line in result.stdout.split("\n"):
            if "estimated duration" in line:
                return float(line.split(":")[1].strip().split(" ")[0])
    except:
        pass
    return CUE_DURATION

# ── CRYPTO ─────────────────────────────────────────────────────────────────────
def decrypt(data):
    oiv = data[0x40:0x44]
    iv1 = int.from_bytes(oiv, byteorder="little")
    iv2 = iv1 ^ 0xDEADBEAF
    iv  = bytearray()
    iv.extend(iv2.to_bytes(4, "little"))
    iv.extend(iv1.to_bytes(4, "little"))
    return Salsa20.new(key[0:32], bytes(iv)).decrypt(data)

def parse(d):
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
    v = p[k]
    return v if isinstance(v, float) else float(v)

def time_to_corner(distance_m, speed_mph):
    if speed_mph < 6:
        return 999
    return distance_m / mph_to_ms(speed_mph)

# ── CORNER STATS ───────────────────────────────────────────────────────────────
def get_corner_stats(rows, corner):
    cx, cz  = corner["pos"]
    packets = [p for p in rows if dist(get_f(p,"pos_x"), get_f(p,"pos_z"), cx, cz) < corner["radius"]]
    if not packets:
        return None
    speeds = [get_f(p,"speed") for p in packets]
    brakes = [get_f(p,"brake") for p in packets]
    brake_pos = None
    for p in packets:
        if get_f(p,"brake") > 20:
            brake_pos = (get_f(p,"pos_x"), get_f(p,"pos_z"))
            break
    return {
        "min_speed_mph":   round(min(speeds), 1),
        "entry_speed_mph": round(next((get_f(p,"speed") for p in packets if get_f(p,"brake") > 20), speeds[0]), 1),
        "max_brake":       round(max(brakes), 1),
        "brake_pos":       brake_pos,
    }

def get_brake_dist(stats, corner):
    if not stats or not stats.get("brake_pos"):
        return None
    bp = stats["brake_pos"]
    return dist(bp[0], bp[1], corner["pos"][0], corner["pos"][1])

# ── PREVIOUS SESSION DATA ──────────────────────────────────────────────────────
def load_previous_laps():
    files = sorted(glob.glob("lap_*.csv"))
    laps  = []
    for f in files:
        with open(f) as fh:
            rows = list(csv.DictReader(fh))
        if len(rows) > 500:
            laps.append(rows)
    return laps

def get_session_stats(laps):
    """Return fastest time in ms and total lap count from previous session files."""
    fastest_ms   = None
    total_laps   = len(laps)
    for lap in laps:
        last_lap_ms = next((int(float(p["last_lap"])) for p in reversed(lap) if float(p.get("last_lap", 0)) > 0), 0)
        if last_lap_ms > 0:
            if fastest_ms is None or last_lap_ms < fastest_ms:
                fastest_ms = last_lap_ms
    return fastest_ms, total_laps

# ── LAP 1 INTRO ───────────────────────────────────────────────────────────────
def generate_intro(laps):
    fastest_ms, total_laps = get_session_stats(laps)
    fastest_str = format_time(fastest_ms) if fastest_ms else "no time on record"

    if laps:
        # Build corner summary from best recent laps
        summaries = []
        for lap in laps[-3:]:
            cs = {}
            for name, corner in CORNERS.items():
                s = get_corner_stats(lap, corner)
                if s:
                    cs[name] = {"corner_name": corner["name"], "min_speed_mph": s["min_speed_mph"]}
            summaries.append(cs)

        prompt = f"""You are Leighton, a GT3 race engineer. Your driver is Nick.

Nick is starting a new session at Laguna Seca in the Porsche 911 GT3 R.

Previous session stats:
- Total laps completed: {total_laps}
- Fastest lap: {fastest_str}

Corner speed data from last {len(summaries)} laps (mph):
{json.dumps(summaries, indent=2)}

Give Nick a lap 1 introduction — 5 to 7 sentences. Include:
- A warm greeting by name
- His fastest lap time and total laps completed
- A brief read of which corners are strong and which need work
- One or two specific things to focus on this session
- An encouraging send-off

Warm, professional race engineer tone. Natural, like team radio at the start of a session.
Respond with ONLY the spoken text."""
    else:
        prompt = """You are Leighton, a GT3 race engineer. Your driver is Nick.

Nick is starting his first ever session at Laguna Seca in the Porsche 911 GT3 R. No previous data exists.

Give him a warm welcome — 3 to 4 sentences. Tell him you'll be building a baseline today, two warm-up laps then coaching goes live, and wish him luck.

Respond with ONLY the spoken text."""

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg    = client.messages.create(model="claude-opus-4-5", max_tokens=300,
                                     messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text.strip()

# ── LAP SUMMARY ───────────────────────────────────────────────────────────────
def generate_lap_summary(lap_a, lap_b, lap_num, lap_time, best_lap):
    is_pb     = best_lap is not None and lap_time < best_lap
    delta_str = (f"{abs(lap_time - best_lap):.1f} seconds "
                 f"{'faster, personal best' if is_pb else 'off the best'}") if best_lap else ""

    prompt = f"""You are Leighton, a GT3 race engineer. Your driver is Nick.

Nick just completed lap {lap_num}. Lap time: {format_time_s(lap_time)}. {delta_str}

Give a ONE sentence radio call — lap time and good or not. Max 15 words.
Good example: "Good lap Nick, one forty two, that's a personal best."
Bad example: "Tough one, one forty five, half a second off your best."
Respond with ONLY the spoken text."""

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg    = client.messages.create(model="claude-opus-4-5", max_tokens=60,
                                     messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text.strip()

# ── CORNER CUE GENERATION ─────────────────────────────────────────────────────
def analyse_corners(lap_a, lap_b, lap_num, corner_keys, half_label):
    """Generate cues for a specific subset of corners."""
    print(f"\nAnalysing {half_label} corners...")
    corner_data = {}
    deltas      = {}

    for name in corner_keys:
        corner = CORNERS[name]
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

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg    = client.messages.create(model="claude-opus-4-5", max_tokens=200,
                                     messages=[{"role": "user", "content": prompt}])
    raw  = msg.content[0].text.strip().strip("```json").strip("```").strip()
    cues = json.loads(raw)
    print(f"  Cues ({half_label}):")
    for c, t in cues.items():
        print(f"    {c}: {t}")
    return cues

def generate_audio(cues, lap_num, suffix=""):
    files = {}
    for corner, cue in cues.items():
        filename = f"cue_{corner}_lap{lap_num}{suffix}.aiff"
        subprocess.run(["say", "-v", "Daniel", "-r", "175", cue, "-o", filename])
        files[corner] = filename
    return files

# ── NETWORK ────────────────────────────────────────────────────────────────────
def send_heartbeat(sock):
    while True:
        sock.sendto(b"A", (PS5_IP, SEND_PORT))
        threading.Event().wait(0.1)

# ── CRASH DETECTION ────────────────────────────────────────────────────────────
speed_history   = []
last_crash_time = 0
crash_idx       = 0

def check_for_crash(speed, now):
    global last_crash_time, crash_idx
    speed_history.append((now, speed))
    while speed_history and now - speed_history[0][0] > 1.0:
        speed_history.pop(0)
    if len(speed_history) < 10:
        return
    hi = max(s for _, s in speed_history)
    lo = min(s for _, s in speed_history)
    if hi > 37 and (hi - lo) > 50:
        if now - last_crash_time > 15:
            last_crash_time = now
            phrase = CRASH_PHRASES[crash_idx % len(CRASH_PHRASES)]
            crash_idx += 1
            with audio_queue.mutex:
                audio_queue.queue.clear()
            speak_immediate(phrase)
            print(f"\n  [CRASH] {phrase}")

# ── SETUP ──────────────────────────────────────────────────────────────────────
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("", RECV_PORT))
sock.settimeout(10)
threading.Thread(target=send_heartbeat, args=(sock,), daemon=True).start()

previous_laps = load_previous_laps()

def deliver_intro():
    time.sleep(3)
    intro = generate_intro(previous_laps)
    print(f"[Intro] {intro}")
    speak_immediate(intro)

threading.Thread(target=deliver_intro, daemon=True).start()

# ── STATE ──────────────────────────────────────────────────────────────────────
current_lap      = None
lap_data         = []
lap_history      = {}
cue_state        = {}
sector_state     = {}
corner_passed    = set()
active_cues      = {}   # merged first + second half cues
cue_durations    = {}
coaching_active  = False
analysis_lock    = threading.Lock()
lap_start_time   = None
best_lap         = None
best_sectors     = {}
session_start    = time.time()
warmup_spoken    = []
s2_triggered     = False  # has first-half analysis been triggered this lap

def warmup_chatter():
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

threading.Thread(target=warmup_chatter, daemon=True).start()

def get_next_corners(passed_set, n=NEXT_N_CORNERS):
    return [c for c in CORNER_ORDER if c not in passed_set][:n]

# ── PIPELINED ANALYSIS ─────────────────────────────────────────────────────────
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
    """Triggered at lap end — analyses T5-T9 and delivers lap summary."""
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

# ── MAIN LOOP ──────────────────────────────────────────────────────────────────
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

        # ── LAP CHANGE ────────────────────────────────────────────────────────
        if p["lap"] != current_lap:
            if current_lap is not None and len(lap_data) > 500:
                lap_time_val = p["last_lap"] / 1000.0 if p["last_lap"] > 0 else 0
                lap_history[current_lap] = lap_data

                if current_lap >= 2 and (current_lap - 1) in lap_history:
                    threading.Thread(
                        target=run_second_half_and_summary,
                        args=(lap_history[current_lap-1], lap_history[current_lap],
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
            # Clear cues at lap start — fresh set will be built by pipeline
            with analysis_lock:
                active_cues   = {}
                cue_durations = {}

            if current_lap > 0:
                speak(f"Lap {current_lap}")
                print(f"\nLap {current_lap}")
            print(f"  {'Recording silently' if current_lap <= 2 else 'Coaching active'}")

        lap_data.append(p)

        # ── SECTOR TIMING + S2 PIPELINE TRIGGER ───────────────────────────────
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

                    # S2 crossing — trigger first half analysis immediately
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

        # ── MARK CORNERS PASSED ───────────────────────────────────────────────
        for name, corner in CORNERS.items():
            if dist(x, z, corner["pos"][0], corner["pos"][1]) < corner["radius"]:
                corner_passed.add(name)

        # ── SMART CORNER CUES — next 2 only ───────────────────────────────────
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
