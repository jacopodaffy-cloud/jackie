"""Jackie background listener — hotkeys + clap wake. Keep this running.

WHAT OPENS JACKIE: pressing the open hotkey (default  L ) — and NOTHING else.
The old behavior (boot opens a window, any double clap opens a window) was the
"app opens by itself" bug: sharp noises near the mic re-opened the dashboard
right after you closed it. Now:

  - at boot the BACKEND starts silently (so the phone app and the L key are
    instant) but NO window opens;
  - a double clap only wakes the dashboard when it is ALREADY open — with it
    closed, claps do nothing but leave a note in the log;
  - the mic hotkey (default  T ) turns background listening off/on.

Hotkeys are configurable in .env: JARVIS_HOTKEY_OPEN=l, JARVIS_HOTKEY_MIC=t
(single letters fire while typing anywhere — combos like "ctrl+alt+l" work
too and don't). Everything is logged to logs/clap_launcher.log.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

import config  # noqa: E402  (loads .env: port, clap tuning, hotkeys)
import ears    # noqa: E402

PORT = int(os.environ.get("JARVIS_PORT") or os.environ.get("PORT") or "8791")
URL = f"http://127.0.0.1:{PORT}/"
LOG = ROOT / "logs" / "clap_launcher.log"
REARM_SECONDS = 300   # reopen the mic stream every 5 min (survives device changes)

HOTKEY_OPEN = (os.environ.get("JARVIS_HOTKEY_OPEN") or "l").strip().lower()
HOTKEY_MIC = (os.environ.get("JARVIS_HOTKEY_MIC") or "t").strip().lower()

_last_spawn = 0.0
_last_open = 0.0
mic_on = threading.Event()
mic_on.set()
pause_evt = threading.Event()   # set = clap detection must stand down


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line)
    try:
        LOG.parent.mkdir(exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def backend_up() -> bool:
    try:
        with urlopen(URL + "api/status", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def ui_state() -> dict:
    """One /api/status call → {'open': bool, 'listening': bool}.

    open      = a dashboard page polled the backend recently (tab exists,
                foreground OR minimized).
    listening = that page's own microphone is actively listening — then its
                mic is in charge and we stand down (his TTS through the
                speakers must not look like claps here).
    """
    try:
        import json as _json
        with urlopen(URL + "api/status", timeout=1.5) as r:
            j = _json.load(r)
        ago = j.get("ui_seconds_ago")
        listen_ago = j.get("listening_seconds_ago")
        return {"open": ago is not None and ago < 20,
                "listening": listen_ago is not None and listen_ago < 15}
    except Exception:
        return {"open": False, "listening": False}


def notify_clap() -> bool:
    """Tell the open dashboard a clap happened — it wakes up and listens."""
    try:
        from urllib.request import Request
        with urlopen(Request(URL + "api/clap", data=b"{}",
                             headers={"Content-Type": "application/json"}),
                     timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def open_ui(url: str) -> None:
    """Prefer Microsoft Edge — its free 'Natural' voices sound human.
    Set JARVIS_BROWSER=default in .env for the system default browser."""
    if os.environ.get("JARVIS_BROWSER", "edge").lower() == "edge":
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", "msedge", url],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            log(f"opened Edge at {url}")
            return
        except Exception as exc:
            log(f"Edge launch failed ({exc}) — falling back to default browser")
    webbrowser.open(url)
    log(f"opened default browser at {url}")


def start_backend_silently() -> bool:
    """Make sure server.py is running WITHOUT opening any window.
    Returns True once the backend answers."""
    global _last_spawn
    if backend_up():
        return True
    # Never spawn a second server while one may still be starting (a cold
    # first start can take a while) — double keypresses used to stack them.
    if time.monotonic() - _last_spawn > 60:
        _last_spawn = time.monotonic()
        venv_py = ROOT / ".venv" / "Scripts" / "pythonw.exe"
        exe = str(venv_py) if venv_py.exists() else sys.executable
        env = dict(os.environ)
        env["JARVIS_NO_BROWSER"] = "1"     # the server must NEVER self-open here
        log("starting the backend (silent — no window)")
        subprocess.Popen([exe, str(ROOT / "server.py")], cwd=str(ROOT), env=env)
    for _ in range(60):
        time.sleep(0.5)
        if backend_up():
            return True
    log("backend still not answering after 30s")
    return False


def open_dashboard(source: str) -> None:
    """The ONLY code path that opens a Jackie window — the open hotkey."""
    global _last_open
    if time.monotonic() - _last_open < 2:   # debounce key repeat
        return
    _last_open = time.monotonic()
    start_backend_silently()
    if ui_state()["open"]:
        notify_clap()
        log(f"{source}: dashboard already open — woke it up instead of opening a duplicate")
        return
    open_ui(URL)


def on_clap() -> None:
    """Claps NEVER open a window (that was the auto-open bug): they only wake
    the dashboard when it is already open on screen."""
    if backend_up() and ui_state()["open"]:
        notify_clap()
        log("double clap — dashboard is open, sent it the wake-up signal")
    else:
        log(f"double clap heard — dashboard closed; press {HOTKEY_OPEN.upper()} "
            "to open it (clap-open is disabled by design)")


def register_hotkeys() -> bool:
    try:
        import keyboard
    except Exception as exc:
        log(f"⚠ hotkeys unavailable ({exc}) — pip install keyboard")
        return False

    def do_open():
        threading.Thread(target=open_dashboard, args=("hotkey",), daemon=True).start()

    def do_mic():
        def worker():
            if ui_state()["open"]:
                return          # dashboard open: T there toggles ITS microphone
            if mic_on.is_set():
                mic_on.clear()
                log(f"microphone OFF — press {HOTKEY_MIC.upper()} to turn it back on")
            else:
                mic_on.set()
                log("microphone ON — clap detection armed")
        threading.Thread(target=worker, daemon=True).start()

    keyboard.add_hotkey(HOTKEY_OPEN, do_open, suppress=False)
    keyboard.add_hotkey(HOTKEY_MIC, do_mic, suppress=False)
    log(f"hotkeys ready — {HOTKEY_OPEN.upper()} opens Jackie, "
        f"{HOTKEY_MIC.upper()} toggles the mic "
        "(customize: JARVIS_HOTKEY_OPEN / JARVIS_HOTKEY_MIC in .env)")
    return True


def _pause_watcher() -> None:
    """Keeps pause_evt in sync: detection stands down while the mic hotkey is
    off OR while an open dashboard is listening with its own microphone.
    wait_for_double_clap() takes pause_evt as its stop_event, so a pause takes
    effect within a couple of audio blocks — not after the 5-minute re-arm."""
    was_paused = None
    while True:
        try:
            listening = ui_state()["listening"]
            paused = (not mic_on.is_set()) or listening
            if paused:
                pause_evt.set()
            else:
                pause_evt.clear()
            if paused != was_paused:
                if paused and listening:
                    log("dashboard is listening — its mic is in charge, pausing here")
                elif not paused and was_paused is not None:
                    log("background clap detection re-armed")
                was_paused = paused
        except Exception:
            pass
        time.sleep(3)


def main() -> None:
    register_hotkeys()

    # Boot: bring the backend up SILENTLY. Jackie's window only ever opens
    # from the open hotkey. (Set JARVIS_BOOT_OPEN=1 to opt back in to a
    # window at every boot.)
    if backend_up():
        log("boot: backend already running")
    else:
        log("boot: starting the backend silently")
        start_backend_silently()
    if os.environ.get("JARVIS_BOOT_OPEN", "0") == "1":
        open_dashboard("boot (JARVIS_BOOT_OPEN=1)")

    # At logon the audio stack can lag behind us — retry instead of dying.
    waited = 0
    while not ears.audio_available():
        if waited == 0:
            log("no microphone yet — waiting for the audio device (retrying)")
        if waited >= 600:
            log("no microphone after 10 minutes — clap wake off; "
                f"the {HOTKEY_OPEN.upper()} hotkey still works")
            break
        time.sleep(15)
        waited += 15

    threading.Thread(target=_pause_watcher, daemon=True).start()

    if not ears.audio_available():
        while True:            # hotkeys must keep working even with no mic
            time.sleep(60)

    # Lock onto a microphone that actually hears something.
    idx, name, peak = ears.rescan_device()
    log(f"microphone: {name} (peak {peak:.4f})")

    log(f"armed — double-clap wakes the OPEN dashboard; {HOTKEY_OPEN.upper()} opens it "
        f"(threshold={config.CLAP_THRESHOLD}, ratio={config.CLAP_RATIO}x, "
        f"re-arm every {REARM_SECONDS}s)")
    print("   (Ctrl+C to quit. Tip: 'Clap Test.bat' shows what the mic hears.)")
    mic_was_dead = None
    while True:
        try:
            if pause_evt.is_set():
                time.sleep(2)
                continue
            # Health check each cycle: a hardware-muted mic (Fn key) delivers
            # flatline and NOTHING can hear claps — try the other input
            # devices, and say so in the log either way.
            level = ears.probe_level(1.5)
            mic_dead = level < 0.002
            if mic_dead:
                idx, name, peak = ears.rescan_device()
                if peak >= 0.002:
                    log(f"default mic was silent — switched to: {name} (peak {peak:.4f})")
                    mic_dead = False
                    level = peak
            if mic_dead != mic_was_dead:
                if mic_dead:
                    log(f"⚠ every mic is nearly ZERO (max={level:.4f}) — hardware mute? "
                        "Press the Fn mic key, then check with Clap Test.bat")
                else:
                    log(f"mic is alive (max={level:.4f}, device: {ears.current_device_name()}) "
                        "— clap detection active")
                mic_was_dead = mic_dead
            # pause_evt doubles as the stop_event: a pause (mic hotkey off, or
            # the dashboard started listening) interrupts the wait within
            # ~100 ms instead of waiting out the 5-minute re-arm.
            if ears.wait_for_double_clap(stop_event=pause_evt,
                                         max_seconds=REARM_SECONDS):
                on_clap()
                time.sleep(4)  # cooldown while the dashboard reacts
        except KeyboardInterrupt:
            log("stopped by user")
            return
        except Exception as exc:
            log(f"error: {exc} — retrying in 3s")
            time.sleep(3)


if __name__ == "__main__":
    main()
