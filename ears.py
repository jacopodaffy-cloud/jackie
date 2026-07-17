"""Jarvis's ears: clap-to-wake detection and speech-to-text.

Everything mic-related lives here and degrades gracefully:
  - If no microphone / audio backend, clap + STT are disabled and Jarvis
    falls back to typed input (see jarvis.py).
  - STT uses the free Google Web Speech recognizer (needs internet, no key).
"""
from __future__ import annotations

import io
import os
import sys
import time
import wave

import config

try:
    import numpy as np
    import sounddevice as sd

    _AUDIO_OK = True
except Exception as _exc:  # pragma: no cover
    _AUDIO_OK = False
    _AUDIO_IMPORT_ERROR = _exc


def audio_available() -> bool:
    if not _AUDIO_OK:
        return False
    try:
        sd.check_input_settings(samplerate=config.SAMPLE_RATE, channels=1)
        return True
    except Exception:
        pass
    # The DEFAULT input may be broken while another mic works fine — any
    # usable input device counts (rescan_device() will find the live one).
    try:
        return any(d.get("max_input_channels", 0) > 0 and _hostapi_ok(d)
                   for d in sd.query_devices())
    except Exception:
        return False


# --------------------------------------------------------------------------
# Input-device selection — the default mic sometimes flatlines (Fn mute /
# Realtek driver wedge) while another input (webcam, headset) hears fine.
# We probe the candidates and lock onto whichever one actually works.
# --------------------------------------------------------------------------
_dev = {"idx": None, "name": "default"}   # None = system default device


def _hostapi_ok(dev_info) -> bool:
    # PortAudio crashes on WDM-KS devices on some machines — MME/WASAPI only.
    try:
        name = sd.query_hostapis(dev_info["hostapi"])["name"]
    except Exception:
        return False
    return "MME" in name or "WASAPI" in name


def _peak_of(device, seconds: float) -> float:
    """Loudest peak one device delivers; -1 when it can't be opened / stalls."""
    import queue
    q: "queue.Queue[float]" = queue.Queue(maxsize=256)

    def _cb(indata, frames, t, status):
        try:
            q.put_nowait(float(np.max(np.abs(indata))) if len(indata) else 0.0)
        except queue.Full:
            pass

    try:
        with sd.InputStream(device=device, samplerate=config.SAMPLE_RATE,
                            channels=1, blocksize=int(config.SAMPLE_RATE * 0.03),
                            dtype="float32", callback=_cb):
            peak = 0.0
            t0 = time.monotonic()
            while time.monotonic() - t0 < seconds:
                try:
                    peak = max(peak, q.get(timeout=0.8))
                except queue.Empty:
                    return -1.0        # stream stalled
            return peak
    except Exception:
        return -1.0


def current_device():
    """Device to pass to InputStream (None = system default)."""
    return _dev["idx"]


def current_device_name() -> str:
    return _dev["name"]


def rescan_device(min_level: float = 0.0015, probe_seconds: float = 0.9):
    """Probe every usable input device and lock onto one that hears the room.

    Returns (index, name, peak). Called at startup and whenever the current
    device flatlines. Set JARVIS_INPUT_DEVICE in .env (index or name part)
    to force a specific microphone.
    """
    if not _AUDIO_OK:
        return None, "none", -1.0
    candidates = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0 and _hostapi_ok(d):
                candidates.append((i, d.get("name", f"#{i}")))
    except Exception:
        pass
    forced = (os.environ.get("JARVIS_INPUT_DEVICE") or "").strip()
    if forced:
        for i, name in candidates:
            if forced == str(i) or forced.lower() in name.lower():
                _dev.update(idx=i, name=name)
                return i, name, _peak_of(i, probe_seconds)
    best_idx, best_name = None, "default"
    best_peak = _peak_of(None, probe_seconds)
    if best_peak < min_level:          # default is deaf — try everything else
        for i, name in candidates:
            p = _peak_of(i, probe_seconds)
            if p > best_peak:
                best_idx, best_name, best_peak = i, name, p
            if p >= min_level * 4:     # clearly alive — good enough, stop here
                break
    _dev.update(idx=best_idx, name=best_name)
    return best_idx, best_name, best_peak


def _open_input(**kw):
    """InputStream on the chosen device, falling back to the default if the
    chosen one vanished (unplugged USB mic, device renumbering)."""
    try:
        return sd.InputStream(device=_dev["idx"], **kw)
    except Exception:
        if _dev["idx"] is None:
            raise
        _dev.update(idx=None, name="default")
        return sd.InputStream(device=None, **kw)


# --------------------------------------------------------------------------
# Clap-to-wake
# --------------------------------------------------------------------------
class ClapDetector:
    """Streaming double-clap detector. Feed one (amp, hp) pair per ~30 ms
    block; feed() returns True the instant a double clap completes.

    TWO channels make quiet claps detectable without false alarms:
      amp — plain peak amplitude of the block;
      hp  — peak of the first difference (a one-tap high-pass): a clap is a
            sharp broadband SNAP, so its sample-to-sample jump is huge even
            when its amplitude is small, while fans, music and voices ramp
            smoothly and barely move this channel.
    Each channel has its own slow noise floor; an onset is a spike RATIO×
    above its floor that also jumps sharply (>2.2× the previous block)."""

    def __init__(self):
        self.amp_floor = 0.01
        self.hp_floor = 0.004
        self.prev_amp = 0.0
        self.prev_hp = 0.0
        self.last_onset = 0.0
        self.first_clap = 0.0

    def feed(self, amp: float, hp: float, now: float) -> bool:
        ratio = config.CLAP_RATIO
        amp_thr = max(config.CLAP_THRESHOLD, min(self.amp_floor * ratio, 0.45))
        hp_thr = max(config.CLAP_THRESHOLD * 0.6, min(self.hp_floor * ratio, 0.35))
        spike = ((amp > amp_thr and amp > self.prev_amp * 2.2)
                 or (hp > hp_thr and hp > self.prev_hp * 2.2))
        fired = False
        if spike and (now - self.last_onset) > config.CLAP_REFRACTORY:
            if self.first_clap and (config.CLAP_MIN_GAP
                                    <= now - self.first_clap
                                    <= config.CLAP_MAX_GAP):
                self.first_clap = 0.0
                fired = True
            else:
                self.first_clap = now
            self.last_onset = now
        elif self.first_clap and (now - self.first_clap) > config.CLAP_MAX_GAP:
            self.first_clap = 0.0  # window expired, reset
        # Slow noise floors learned from sub-threshold blocks only.
        if amp < amp_thr:
            self.amp_floor = 0.95 * self.amp_floor + 0.05 * amp
        if hp < hp_thr:
            self.hp_floor = 0.95 * self.hp_floor + 0.05 * hp
        self.prev_amp = amp
        self.prev_hp = hp
        return fired


def block_features(block) -> tuple:
    """(amp, hp) of one float32 audio block — shared by listener + tester."""
    if block is None or not len(block):
        return 0.0, 0.0
    flat = np.asarray(block, dtype="float32").ravel()
    amp = float(np.max(np.abs(flat)))
    hp = float(np.max(np.abs(np.diff(flat)))) if len(flat) > 1 else 0.0
    return amp, hp


def wait_for_double_clap(stop_event=None, max_seconds: float = 0.0) -> bool:
    """Block until a double clap is heard. Returns True when triggered.

    Pass a threading.Event as stop_event to make it interruptible (the GUI's
    Stop button uses this); it returns False when the event is set.
    Pass max_seconds > 0 to return False after that long — callers re-arm with
    a FRESH stream, so a mic that changed/glitched gets picked up again.
    """
    if not audio_available():
        return False

    # Callback + queue instead of blocking stream.read(): a mic that stops
    # delivering audio (device switched, unplugged, grabbed exclusively) used
    # to freeze this function FOREVER — now the queue read times out and we
    # return False so the caller re-arms with a fresh stream.
    import queue

    block = int(config.SAMPLE_RATE * 0.03)  # ~30 ms blocks
    feats: "queue.Queue[tuple]" = queue.Queue(maxsize=256)

    def _on_audio(indata, frames, t, status):  # runs on PortAudio's thread
        try:
            feats.put_nowait(block_features(indata))
        except queue.Full:
            pass

    det = ClapDetector()
    started_at = time.monotonic()

    print("👂 Listening for a double clap to wake Jackie...  (Ctrl+C to quit)")
    with _open_input(
        samplerate=config.SAMPLE_RATE, channels=1, blocksize=block,
        dtype="float32", callback=_on_audio,
    ):
        while True:
            if stop_event is not None and stop_event.is_set():
                return False
            now = time.monotonic()
            if max_seconds and now - started_at > max_seconds:
                return False
            try:
                amp, hp = feats.get(timeout=3.0)
            except queue.Empty:
                print("[ears] mic stream stalled — re-arming with a fresh stream")
                return False
            if det.feed(amp, hp, time.monotonic()):
                return True


# --------------------------------------------------------------------------
# Record a command (stop on silence) and transcribe it
# --------------------------------------------------------------------------
def _record_until_silence(max_seconds: float = 8.0, silence_hold: float = 0.9):
    block = int(config.SAMPLE_RATE * 0.03)
    frames = []
    started = False
    speech_floor = 0.02
    last_voice = time.monotonic()
    start = time.monotonic()

    with _open_input(
        samplerate=config.SAMPLE_RATE, channels=1, blocksize=block, dtype="int16"
    ) as stream:
        while True:
            data, _ = stream.read(block)
            frames.append(data.copy())
            amp = float(np.max(np.abs(data.astype("float32") / 32768.0)))
            now = time.monotonic()
            if amp > speech_floor:
                started = True
                last_voice = now
            if started and (now - last_voice) > silence_hold:
                break
            if (now - start) > max_seconds:
                break

    if not frames:
        return b""
    pcm = np.concatenate(frames, axis=0).astype("int16").tobytes()
    return pcm


def _pcm_to_wav_bytes(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(config.SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


def probe_level(seconds: float = 1.5) -> float:
    """Sample the mic briefly and return the loudest peak heard (0..1).
    Used by the clap launcher to log when the mic looks hardware-muted."""
    if not audio_available():
        return -1.0
    import queue

    q: "queue.Queue[float]" = queue.Queue(maxsize=256)

    def _cb(indata, frames, t, status):
        try:
            q.put_nowait(float(np.max(np.abs(indata))) if len(indata) else 0.0)
        except queue.Full:
            pass

    peak = 0.0
    try:
        with _open_input(
            samplerate=config.SAMPLE_RATE, channels=1,
            blocksize=int(config.SAMPLE_RATE * 0.03), dtype="float32", callback=_cb,
        ):
            t0 = time.monotonic()
            while time.monotonic() - t0 < seconds:
                try:
                    peak = max(peak, q.get(timeout=1.0))
                except queue.Empty:
                    return -1.0  # stalled
    except Exception:
        return -1.0
    return peak


def stt_wav_bytes(wav_bytes: bytes, language: str | None = None) -> str:
    """Transcribe a WAV payload (16-bit PCM) — used by the web UI's
    server-side dictation fallback (/api/stt). Returns '' when unintelligible."""
    if not wav_bytes:
        return ""
    import speech_recognition as sr

    recognizer = sr.Recognizer()
    with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
        audio = recognizer.record(source)
    try:
        return recognizer.recognize_google(audio, language=language or config.STT_LANGUAGE)
    except sr.UnknownValueError:
        return ""


def listen_command() -> str:
    """Record a spoken command and return the transcribed text ('' on failure)."""
    if not audio_available():
        return ""
    print("🎙️  Listening... speak your command.")
    pcm = _record_until_silence()
    if not pcm:
        return ""

    try:
        import speech_recognition as sr
    except Exception as exc:
        print(f"[ears] speech_recognition unavailable: {exc}", file=sys.stderr)
        return ""

    wav = _pcm_to_wav_bytes(pcm)
    recognizer = sr.Recognizer()
    with sr.AudioFile(io.BytesIO(wav)) as source:
        audio = recognizer.record(source)
    try:
        text = recognizer.recognize_google(audio, language=config.STT_LANGUAGE)
        print(f"🗣️  You said: {text}")
        return text
    except sr.UnknownValueError:
        print("[ears] Could not understand the audio.")
        return ""
    except sr.RequestError as exc:
        print(f"[ears] STT request failed (offline?): {exc}", file=sys.stderr)
        return ""
