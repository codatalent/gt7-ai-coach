"""Crash detection from a rolling speed window.

Keeps roughly one second of recent speed samples. A large, sudden drop while at
speed is treated as a crash: pending coaching is cleared and the engineer checks
the driver is okay, then stays quiet for a cooldown before resuming.
"""

import time

from .config import CRASH_PHRASES, CRASH_MIN_SPEED, CRASH_DROP, CRASH_COOLDOWN
from .audio import clear_queue, speak_immediate

_speed_history   = []
_last_crash_time = 0
_crash_idx       = 0


def check_for_crash(speed, now):
    """Feed one speed sample; speak a check-in if a crash is detected."""
    global _last_crash_time, _crash_idx
    _speed_history.append((now, speed))
    while _speed_history and now - _speed_history[0][0] > 1.0:
        _speed_history.pop(0)
    if len(_speed_history) < 10:
        return
    hi = max(s for _, s in _speed_history)
    lo = min(s for _, s in _speed_history)
    if hi > CRASH_MIN_SPEED and (hi - lo) > CRASH_DROP:
        if now - _last_crash_time > CRASH_COOLDOWN:
            _last_crash_time = now
            phrase = CRASH_PHRASES[_crash_idx % len(CRASH_PHRASES)]
            _crash_idx += 1
            clear_queue()
            speak_immediate(phrase)
            print(f"\n  [CRASH] {phrase}")
