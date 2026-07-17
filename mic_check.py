"""Full microphone diagnosis — run me when audio input is dead.

Usage:  .venv\\Scripts\\python.exe mic_check.py   (or double-click Mic Check.bat)

Checks, in order: Windows privacy consent, endpoint mute/volume, every input
device's real signal level, and prints a plain-language VERDICT with the fix.
Jackie's agent runs this when you tell him the microphone doesn't work.

Design note: pycaw (COM) and PortAudio crash when mixed in one process, and
PortAudio can segfault on exotic devices — so the main process orchestrates
only, and every native check runs in its own subprocess.
"""
from __future__ import annotations

import subprocess
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _child(args: list, timeout: int = 15) -> str:
    try:
        out = subprocess.run(
            [sys.executable, __file__] + args,
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        if out.returncode != 0 and not (out.stdout or "").strip():
            return f"(check crashed, exit {out.returncode})"
        return (out.stdout or "").strip()
    except subprocess.TimeoutExpired:
        return "(check hung)"


# ---------------- child modes (each touches ONE native library) --------------

def _endpoint_child() -> None:
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    dev = AudioUtilities.GetMicrophone()
    vol = cast(dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None),
               POINTER(IAudioEndpointVolume))
    muted = bool(vol.GetMute())
    level = vol.GetMasterVolumeLevelScalar() * 100
    print(f"Default endpoint: muted={muted} level={level:.0f}%")
    if muted:
        vol.SetMute(0, None)
        print("-> was muted in Windows: UNMUTED it now.")
    if level < 100:
        vol.SetMasterVolumeLevelScalar(1.0, None)
        print("-> raised level to 100%.")


def _list_child() -> None:
    import sounddevice as sd

    seen = set()
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] < 1:
            continue
        api = sd.query_hostapis(d["hostapi"])["name"]
        if api not in ("MME", "Windows WASAPI"):
            continue  # DirectSound duplicates MME; WDM-KS can crash PortAudio
        key = d["name"][:28]
        if key in seen:
            continue
        seen.add(key)
        print(f"DEV|{i}|{d['name'][:44]}")


def _probe_child(dev_index: int) -> None:
    import queue

    import numpy as np
    import sounddevice as sd

    d = sd.query_devices(dev_index)
    q: "queue.Queue[float]" = queue.Queue(maxsize=256)

    def cb(indata, frames, t, status):
        try:
            q.put_nowait(float(np.max(np.abs(indata))))
        except queue.Full:
            pass

    peak = 0.0
    with sd.InputStream(device=dev_index, samplerate=int(d["default_samplerate"]),
                        channels=1, blocksize=1024, dtype="float32", callback=cb):
        t0 = time.monotonic()
        while time.monotonic() - t0 < 2.0:
            try:
                peak = max(peak, q.get(timeout=1.0))
            except queue.Empty:
                print("PEAK STALLED")
                return
    print(f"PEAK {peak:.4f}")


# ---------------- parent: orchestration only ---------------------------------

def check_privacy() -> bool:
    import winreg

    ok = True
    base = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
    for sub, label in [(base, "Microphone access (global)"),
                       (base + r"\NonPackaged", "Desktop apps access")]:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as k:
                val = winreg.QueryValueEx(k, "Value")[0]
            print(f"  {label}: {val}")
            if val != "Allow":
                ok = False
        except OSError:
            print(f"  {label}: (not set)")
    return ok


def main() -> None:
    print("=== JACKIE MIC CHECK ===")
    print("\n1) Windows privacy:")
    privacy_ok = check_privacy()

    print("\n2) Endpoint state:")
    for line in _child(["--endpoint"]).splitlines():
        print("  " + line)

    print("\n3) Real signal per input device (2s each — make some noise NOW):")
    best = 0.0
    for row in _child(["--list"]).splitlines():
        if not row.startswith("DEV|"):
            continue
        _, idx, name = row.split("|", 2)
        res = _child(["--probe", idx], timeout=10)
        line = next((l for l in res.splitlines() if l.startswith("PEAK")), "")
        if line == "PEAK STALLED":
            verdict = "STALLED (no audio delivered)"
        elif line:
            peak = float(line.split()[1])
            best = max(best, peak)
            verdict = f"peak={peak:.4f}" + ("  <-- ALIVE" if peak > 0.005 else "  (silent)")
        else:
            verdict = res or "(no result)"
        print(f"  [{idx}] {name}: {verdict}")

    print("\n=== VERDICT ===")
    if not privacy_ok:
        print("Microphone privacy is BLOCKED: Settings > Privacy & security >")
        print("Microphone -> enable global access AND desktop apps access.")
    elif best > 0.005:
        print(f"THE MICROPHONE IS ALIVE (best peak {best:.3f}) — audio input works.")
        print("If Jackie still can't hear you, reload his page (F5) and retry.")
    else:
        print(f"ALL devices deliver silence (best peak {best:.4f}) even at 100% volume")
        print("with privacy allowed. This is BELOW Windows — in order of likelihood:")
        print("  1. Hardware mute key: press the keyboard key with the microphone")
        print("     icon (often F4 or Fn+F4; a LED usually shows when muted).")
        print("  2. Realtek driver wedged: REBOOT the PC (fixes it 9 times out of 10).")
        print("  3. Device disabled in BIOS or broken mic array (rare).")
        print("Verify afterwards: Settings > System > Sound > Input — speak and watch")
        print("the level bar move. Then run me again.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--endpoint":
        _endpoint_child()
    elif len(sys.argv) > 1 and sys.argv[1] == "--list":
        _list_child()
    elif len(sys.argv) > 2 and sys.argv[1] == "--probe":
        _probe_child(int(sys.argv[2]))
    else:
        main()
