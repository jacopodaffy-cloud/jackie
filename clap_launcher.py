"""Jackie clap launcher — keep this running in the background.

Double-clap anywhere near the PC and the Jackie dashboard opens, backend
included, ready to hear "Hey Jackie". Start it with
"Jackie Clap Listener.bat" (a shortcut in shell:startup runs it at boot).

Everything it does is logged to logs/clap_launcher.log — if clapping ever
seems dead, read that file (or run "Clap Test.bat" to calibrate).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

import config  # noqa: E402  (loads .env: port, clap tuning)
import ears    # noqa: E402

PORT = int(os.environ.get("JARVIS_PORT") or os.environ.get("PORT") or "8791")
URL = f"http://127.0.0.1:{PORT}/"
LOG = ROOT / "logs" / "clap_launcher.log"
REARM_SECONDS = 300   # reopen the mic stream every 5 min (survives device changes)

_last_spawn = 0.0


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
    listening = that page's own microphone is actively listening — only then
                must WE stay quiet (its mic handles wake words and claps,
                and TTS through the speakers must not look like claps here).
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


def launch() -> None:
    """Open the dashboard; start the backend first if it isn't running.
    If the dashboard is already open, wake IT up instead of opening a
    duplicate window (duplicate tabs used to fight over the microphone)."""
    global _last_spawn
    if backend_up():
        if ui_state()["open"]:
            if notify_clap():
                log("dashboard already open — sent it the clap wake-up signal")
            else:
                log("dashboard already open — NOT opening another window")
            return
        log("backend already up — opening UI")
        open_ui(URL)
        return
    # Never spawn a second server while one may still be starting (a cold
    # first start can take a while) — double claps used to stack instances.
    if time.monotonic() - _last_spawn > 60:
        _last_spawn = time.monotonic()
        venv_py = ROOT / ".venv" / "Scripts" / "pythonw.exe"
        exe = str(venv_py) if venv_py.exists() else sys.executable
        log("backend down — starting server.py")
        # server.py opens the browser by itself once it's up (in Edge too).
        subprocess.Popen([exe, str(ROOT / "server.py")], cwd=str(ROOT))
    else:
        log("backend down but a server is already starting — waiting")
    for _ in range(60):
        time.sleep(0.5)
        if backend_up():
            log("server is up")
            return
    log("server still not answering after 30s — opening UI anyway")
    open_ui(URL)


def boot_backend() -> None:
    """Make sure Jackie is open and ready the moment the PC starts.
    Set JARVIS_BOOT_OPEN=0 in .env to go back to clap-to-open only."""
    if os.environ.get("JARVIS_BOOT_OPEN", "1") == "0":
        return
    if backend_up():
        log("boot: backend already running")
        return
    log("boot: starting the Jackie backend + dashboard")
    launch()


def main() -> None:
    boot_backend()

    # At logon the audio stack can lag behind us — retry instead of dying.
    waited = 0
    while not ears.audio_available():
        if waited == 0:
            log("no microphone yet — waiting for the audio device (retrying)")
        if waited >= 600:
            log("FATAL: no microphone after 10 minutes — clap detection off "
                "(the dashboard itself still works)")
            sys.exit(1)
        time.sleep(15)
        waited += 15

    # Lock onto a microphone that actually hears something.
    idx, name, peak = ears.rescan_device()
    log(f"microphone: {name} (peak {peak:.4f})")

    log(f"armed — double-clap to open {URL} "
        f"(threshold={config.CLAP_THRESHOLD}, re-arm every {REARM_SECONDS}s)")
    print("   (Ctrl+C to quit. Tip: 'Clap Test.bat' shows what the mic hears.)")
    mic_was_dead = None
    page_was_listening = None
    while True:
        try:
            # Pause ONLY while a dashboard page is actively listening with its
            # own microphone — then IT handles wake words and claps, and his
            # TTS voice must not be mistaken for claps here. A tab that is
            # merely open (or minimized) does NOT pause us: the page's own
            # detector can't run in a hidden tab, so we stay on duty and send
            # it a wake-up signal when we hear the clap.
            if ui_state()["listening"]:
                if page_was_listening is not True:
                    log("dashboard is listening — its mic is in charge, pausing here")
                    page_was_listening = True
                time.sleep(5)
                continue
            if page_was_listening is not False:
                if page_was_listening is True:
                    log("dashboard mic idle/off — background clap detection re-armed")
                page_was_listening = False
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
            # max_seconds makes this return periodically so the mic stream is
            # reopened fresh — a changed/glitched audio device heals itself.
            if ears.wait_for_double_clap(max_seconds=REARM_SECONDS):
                log("double clap detected — launching")
                launch()
                time.sleep(4)  # cooldown while the dashboard reacts
        except KeyboardInterrupt:
            log("stopped by user")
            return
        except Exception as exc:
            log(f"error: {exc} — retrying in 3s")
            time.sleep(3)


if __name__ == "__main__":
    main()
