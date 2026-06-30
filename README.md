# GT7 AI Coach

A live AI race engineer for **Gran Turismo 7**. It reads the game's telemetry off your PlayStation in real time, compares each lap to your last one, and talks to you on "team radio" through your Mac, calling out where you're losing time about two seconds before each corner.

It's tuned for the Porsche 911 GT3 R around **Laguna Seca**. Formula 1, this is not.

## What it does

- **Reads live telemetry** off the PS5 over your home network (UDP, ~60 packets/second: speed, throttle, brake, steering, position).
- **Decrypts the stream** (GT7 encrypts the packets with a Salsa20 cipher).
- **Maps you to the track** — every corner at Laguna Seca is a coordinate, so it always knows which corner is next.
- **Compares lap to lap** — minimum speed, entry speed and braking point versus your previous lap, to find where you're slow.
- **Coaches you out loud** — a calm AI race engineer voice (via the Anthropic API) delivers one short cue per corner, timed to land just before you arrive. Capped to the 2–3 corners costing you the most time, so it doesn't babble.
- **Warm-up + lap summaries** — first two laps are silent baseline laps, coaching goes live from lap 3, with a one-line lap-time call at the line.
- **Crash detection** — if it sees a big sudden speed drop it stops coaching and checks you're OK before carrying on.

The lap analysis is *pipelined*: it crunches the first half of the lap while you're still driving the second, so the next lap's coaching is ready the moment you cross the line.

## Requirements

- **macOS** (uses the built-in `say`, `afplay` and `afinfo` tools for speech and audio).
- **Python 3.9+**
- A **PlayStation 5** running Gran Turismo 7, on the same local network as your Mac.
- An **Anthropic API key** (this makes live API calls, billed per use).

## Setup

```bash
pip install -r requirements.txt
```

Set your environment variables:

```bash
export ANTHROPIC_API_KEY="your-key-here"
export PS5_IP="192.168.1.xxx"   # your PS5's IP on the local network
```

You can find your PS5's IP under **Settings → Network → Connection Status** on the console.

## Run

```bash
python3 gt7_coach.py
```

Start a session in GT7 at Laguna Seca. The coach sends a heartbeat to the game, the telemetry starts flowing, and you'll hear an intro, then live coaching from lap 3.

`gt7_compare.py` is a small standalone helper for comparing recorded laps.

## Notes & limitations

- **One track, one car.** The corner map is hardcoded for Laguna Seca and the pace model assumes the 911 GT3 R. Other tracks need new corner coordinates.
- **macOS only** for now, because of the native speech/audio tools.
- The Anthropic model id in the code may need updating to a current model.
- No data leaves your machine except the lap stats sent to the Anthropic API to generate the spoken cues.

## How it started

I wanted to get quicker at Gran Turismo, found out the PS5 broadcasts the game's telemetry over wifi, and wondered if I could wire that up to an AI and have it coach me. This is the result. I'm not an engineer by trade, so it was very much an iterative process. It works, and I'm faster with it than without it.

## License

MIT — see [LICENSE](LICENSE).
