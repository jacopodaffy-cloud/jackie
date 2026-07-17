"""Clap calibration — see exactly what your microphone hears.

Run "Clap Test.bat", clap a few times while it listens, and it tells you
whether your claps trigger the SAME detector Jackie uses live (amplitude +
transient channel), and what to tune in .env if they don't.
"""
from __future__ import annotations

import time

import numpy as np
import sounddevice as sd

import config
import ears

DURATION = 15  # seconds


def main() -> None:
    import queue

    idx, name, peak = ears.rescan_device()
    print(f"🎤 Microphone: {name}  (ambient peak {peak:.4f})")
    print(f"   Listening for {DURATION} seconds — CLAP A FEW TIMES NOW!")
    print(f"   Threshold {config.CLAP_THRESHOLD} · ratio {config.CLAP_RATIO}x\n")

    block = int(config.SAMPLE_RATE * 0.03)
    q: "queue.Queue[tuple]" = queue.Queue(maxsize=256)

    def _on_audio(indata, frames, t, status):
        try:
            q.put_nowait(ears.block_features(indata))
        except queue.Full:
            pass

    det = ears.ClapDetector()
    loud = 0.0
    hits = 0
    doubles = 0
    stalled = False
    t0 = time.monotonic()
    with ears._open_input(
        samplerate=config.SAMPLE_RATE, channels=1, blocksize=block,
        dtype="float32", callback=_on_audio,
    ):
        while time.monotonic() - t0 < DURATION:
            try:
                amp, hp = q.get(timeout=3.0)
            except queue.Empty:
                stalled = True
                print("!! The microphone stopped delivering audio (stalled stream).")
                break
            loud = max(loud, amp)
            before = det.first_clap
            fired = det.feed(amp, hp, time.monotonic())
            if det.first_clap and not before:
                hits += 1
                bar = "#" * min(60, int(amp * 300))
                print(f"CLAP  amp={amp:5.3f} hp={hp:5.3f} {bar}")
            if fired:
                doubles += 1
                print(">>> DOUBLE CLAP DETECTED — this would open Jackie <<<")

    if stalled:
        print("\nWindows is not sending audio to this app — check: Settings >")
        print("Privacy & security > Microphone, and that the right input device is default.")
        input("\nPress Enter to close.")
        return

    print(f"\nLoudest peak: {loud:.3f} · single claps seen: {hits} · doubles: {doubles}")
    if doubles:
        print("Detection WORKS — clap twice like that and Jackie opens. ✔")
    elif hits:
        print("Claps are heard but the second one is too early/late — clap twice")
        print(f"within {config.CLAP_MIN_GAP}–{config.CLAP_MAX_GAP}s.")
    elif loud <= 0.005:
        print("The microphone heard almost NOTHING — run 'Mic Check.bat'.")
    else:
        sug = max(0.004, round(loud * 0.4, 3))
        print(f"Claps did not register. FIX: in .env set JARVIS_CLAP_THRESHOLD={sug}")
        print("then restart the listener.")
    input("\nPress Enter to close.")


if __name__ == "__main__":
    main()
