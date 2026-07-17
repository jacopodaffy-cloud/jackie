"""Text-to-speech so Jarvis can talk back.

Uses pyttsx3 (offline, Windows SAPI5). Falls back to silent/print mode if the
engine can't start, so nothing here ever crashes the agent.
"""
from __future__ import annotations

import sys
import threading

import config

_engine = None
_lock = threading.Lock()


def _get_engine():
    global _engine
    if _engine is not None:
        return _engine
    try:
        import pyttsx3

        _engine = pyttsx3.init()
        _engine.setProperty("rate", config.TTS_RATE)
    except Exception as exc:  # pragma: no cover - depends on host audio stack
        print(f"[voice] TTS unavailable ({exc}); running in text-only mode.", file=sys.stderr)
        _engine = False
    return _engine


def say(text: str) -> None:
    """Speak text out loud (and always echo to the console)."""
    text = (text or "").strip()
    if not text:
        return
    print(f"\n🤖 Jackie: {text}")
    if not config.SPEAK_REPLIES:
        return
    engine = _get_engine()
    if not engine:
        return
    # pyttsx3 is not thread-safe; serialise access.
    with _lock:
        try:
            engine.say(text)
            engine.runAndWait()
        except Exception:
            pass
