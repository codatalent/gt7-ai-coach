# GT7 AI Coach

A live, AI race engineer for Gran Turismo 7. It reads the game's telemetry off
the PlayStation in real time, works out which corners you're losing time in, and
speaks a calm coaching cue into your ear about two seconds before you get there.

Built by a recruiter, not an engineer, as a "is this actually possible?" project.
It turned out to be possible. The story behind it is
[here on LinkedIn](https://www.linkedin.com/in/nickyockney).

> **Status:** working prototype. It now **learns any circuit** from a single
> lap and remembers it — no more hand-typed corners. Tuned around the Porsche 911
> GT3 R. See [Roadmap](#roadmap).

## Demo

<!-- TODO: drop a 10-20s screen capture here.
     A GT7 clip with the coach's audio calling a corner shows it best.
     Record, save as docs/demo.gif, then swap the line below in. -->

_A short clip of the coach calling a corner mid-lap will live here._

## How it works

The PS5 broadcasts GT7's telemetry over the local network as an encrypted UDP
stream, roughly 60 packets a second. Each packet is a snapshot of speed,
throttle, brake, steering and position on track. Turning that into coaching takes
a few steps:

1. **Decrypt** — the stream is encrypted with a Salsa20 cipher. The first job is
   deriving the key and IV and decrypting each packet in real time.
2. **Parse** — pull the fields that matter (speed, brake, position, lap number)
   out of the fixed binary layout.
3. **Locate** — match the car's coordinates against a map of the circuit. Each
   corner is a point with a radius, so the system always knows which corner is
   coming and which one just passed. That map isn't typed in — it's **learned
   from your opening lap** (see [Learning a track](#learning-a-track)) and saved,
   so any circuit works and it's only learned once.
4. **Compare** — for each corner, work out minimum speed, entry speed and where
   braking began, then compare against the previous lap to find the delta.
5. **Coach** — Claude turns the worst two or three corners into one calm line of
   team radio each, timed to land about 2.5 seconds before the corner. Any later
   and it's useless, any earlier and you've forgotten it.

Two details that make it feel right:

- **Pipelined analysis.** The lap is split in half. The first half is analysed
  around the midpoint while you're still driving the second, so coaching for the
  next lap is ready the moment you cross the line instead of arriving late.
- **Crash detection.** A rolling one-second window of speed catches a big sudden
  drop, stops the coaching, and checks you're okay before picking back up.

Your opening lap is the **learn lap** — it maps the circuit (or recognises one
you've driven before). The next two laps it stays quiet and records a baseline.
Coaching goes live from lap three.

## Learning a track

The corner map used to be typed in by hand for one circuit. Now the coach builds
it from telemetry:

- **On your first lap**, it reads the speed trace, finds the corners (the places
  you slow and turn), orders them, splits them into two halves for the pipeline,
  and drops three sector gates. That's the track learned — it takes one lap.
- **It saves the map** to `tracks/` and tags it with a geometry fingerprint (lap
  length plus the track's overall size). Next time you drive that circuit it's
  recognised automatically and loaded instantly — you never learn it twice.
- **Names are generic** at first (Turn 1, Turn 2…). Each track is a small JSON
  file in `tracks/`, so you can rename corners once and it sticks ("Corkscrew"
  beats "Turn 5").

Give it one clean, representative opening lap — a spin or an off will give it a
scrappy map. If it can't map a lap it says so and stays quiet rather than coach
off a bad map. Detection thresholds (corner sensitivity, spacing) live under
`track:` in `config.yaml` if you ever need to nudge them.

## Setup

Requires macOS (it uses the built-in `say` and `afplay` for the voice) and Python
3.10+. On Apple Silicon, use a native arm64 Python.

```bash
git clone https://github.com/codatalent/gt7-ai-coach.git
cd gt7-ai-coach

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY="sk-ant-..."
```

Then point it at your console. Copy the example config and set your PS5's IP:

```bash
cp config.example.yaml config.yaml
# edit config.yaml — set ps5_ip to your PlayStation's IP on your network
```

`config.yaml` holds everything you'd normally want to change (IP, model, cue
timings, crash thresholds) and is gitignored so your settings stay local. Leave
anything out and it falls back to the built-in defaults. In a pinch you can also
override just the IP with `GT7_PS5_IP=192.168.1.50 python main.py`.

## Run

Start GT7, load Laguna Seca in the 911 GT3 R, then:

```bash
python main.py
```

Leighton (the engineer) introduces the session, chats through the warm-up laps,
and starts coaching from lap three. Press `Ctrl-C` to stop.

## Project structure

```
gt7_coach/
  config.py      All tunable settings — PS5 IP, ports, cue timings, phrases
  crypto.py      Salsa20 decryption of the telemetry stream
  telemetry.py   Packet parsing + unit/maths helpers
  track.py       The circuit map (corners, sectors) + corner-stat extraction
  audio.py       Text-to-speech queue and cue playback
  coach.py       The Claude-backed intro, lap summaries and corner cues
  crash.py       Rolling-window crash detection
  storage.py     Loading previous laps from CSV for the session intro
main.py          Entry point — wires it together and runs the main loop
config.example.yaml  Template config — copy to config.yaml and edit
tools/
  lap_compare.py A standalone offline lap-vs-lap comparator
```

## Roadmap

- **~~Learn any track.~~** ✅ Done — the circuit map is now learned from your
  opening lap and saved, instead of typed in by hand.
- **Named corners out of the box.** Auto-name well-known corners instead of the
  generic Turn 1, Turn 2… so the radio calls sound native on famous circuits.
- **Learn the driver.** Pick up your style over time rather than only comparing
  you against your own last lap.
- **Coach towards a perfect lap.** Pull in reference data so it can coach you
  towards an ideal line, not just your previous best.

## A note on the stack

Nothing exotic: Python, a UDP socket pulling telemetry off the PS5, Salsa20 to
decrypt it, Claude as the brain that turns lap data into coaching, and the Mac's
built-in text-to-speech for the voice in your ear.

## Licence

MIT. Use it, break it, make it quicker.
