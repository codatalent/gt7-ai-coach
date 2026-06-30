"""Text-to-speech output and cue playback.

A single background worker thread pulls from a queue and either plays a
pre-rendered ``.aiff`` cue file (``afplay``) or speaks raw text live (``say``).
Keeping playback on its own thread means the main telemetry loop never blocks
waiting for audio. The queue is intentionally shallow (``play``/``speak`` drop
new items when it backs up) so coaching always reflects the current corner
rather than a stale backlog.
"""

import os
import queue
import subprocess
import threading

from .config import CUE_DURATION

audio_queue = queue.Queue()


def _audio_worker():
    while True:
        item = audio_queue.get()
        if item is None:
            break
        if os.path.exists(item):
            subprocess.run(["afplay", item])
        else:
            subprocess.run(["say", "-v", "Daniel", "-r", "175", item])
        audio_queue.task_done()


def start_audio_worker():
    """Start the background playback thread. Call once at startup."""
    threading.Thread(target=_audio_worker, daemon=True).start()


def play_file(filename):
    """Queue a pre-rendered cue file, dropping it if audio is already backed up."""
    if audio_queue.qsize() < 2:
        audio_queue.put(filename)


def speak(text):
    """Queue spoken text, dropping it if audio is already backed up."""
    if audio_queue.qsize() < 2:
        audio_queue.put(text)


def speak_immediate(text):
    """Queue spoken text unconditionally (used for intros and crash checks)."""
    audio_queue.put(text)


def clear_queue():
    """Drop everything pending — used so a crash check interrupts coaching."""
    with audio_queue.mutex:
        audio_queue.queue.clear()


def get_audio_duration(filename):
    """Measure a rendered cue's length so cues can be timed to land on the corner."""
    try:
        result = subprocess.run(["afinfo", filename], capture_output=True, text=True)
        for line in result.stdout.split("\n"):
            if "estimated duration" in line:
                return float(line.split(":")[1].strip().split(" ")[0])
    except Exception:
        pass
    return CUE_DURATION


def generate_audio(cues, lap_num, suffix=""):
    """Render each cue to an ``.aiff`` file via ``say``; return {corner: filename}."""
    files = {}
    for corner, cue in cues.items():
        filename = f"cue_{corner}_lap{lap_num}{suffix}.aiff"
        subprocess.run(["say", "-v", "Daniel", "-r", "175", cue, "-o", filename])
        files[corner] = filename
    return files
