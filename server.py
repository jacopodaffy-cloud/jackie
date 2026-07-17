"""Jarvis backend — serves the holographic web UI and gives it full PC control.

Runs a tiny local web server (Python stdlib only) that:
  - serves the web/ front-end,
  - exposes /api/* for settings, system stats, key testing, and the agent.

Open Jarvis.exe (or `py server.py`) and it launches the UI in your browser.
When this backend is running, the UI unlocks real computer control; opened as a
plain file it still works as a chat + dashboard (lite mode).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import brain
import config
import memory
import tools

# ---- locate the web/ folder (works both in dev and inside the .exe) --------
def _resource(*parts) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


WEB_DIR = _resource("web")
_CTYPES = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
           ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon",
           ".json": "application/json", ".webmanifest": "application/manifest+json"}

# ---- optional system stats via psutil (graceful fallback) ------------------
try:
    import psutil

    psutil.cpu_percent(interval=None)  # prime the first reading
    _HAS_PSUTIL = True
except Exception:
    _HAS_PSUTIL = False


# network rate needs a previous sample; GPU polling is cached and disabled
# after the first failure (no NVIDIA card / no nvidia-smi).
_net_prev = {"t": 0.0, "sent": 0, "recv": 0}
_gpu = {"t": 0.0, "val": None, "dead": False}
_alert_last: dict = {}   # threshold-alert cooldowns, key -> monotonic seconds


def _net_rates() -> tuple:
    try:
        io = psutil.net_io_counters()
        now = time.monotonic()
        if not _net_prev["t"] or now <= _net_prev["t"]:
            up = down = 0.0
        else:
            dt = now - _net_prev["t"]
            up = max(0.0, (io.bytes_sent - _net_prev["sent"]) / dt / 1024)
            down = max(0.0, (io.bytes_recv - _net_prev["recv"]) / dt / 1024)
        _net_prev.update(t=now, sent=io.bytes_sent, recv=io.bytes_recv)
        return round(up, 1), round(down, 1)   # KB/s
    except Exception:
        return None, None


def _gpu_stats():
    """utilization % via nvidia-smi, cached 5s; None when unavailable."""
    if _gpu["dead"]:
        return None
    now = time.monotonic()
    if now - _gpu["t"] < 5:
        return _gpu["val"]
    try:
        import subprocess
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        util, mem_used, mem_total = (float(x) for x in out.stdout.strip().split("\n")[0].split(","))
        _gpu["val"] = {"util": util, "mem_used_mb": mem_used, "mem_total_mb": mem_total}
    except Exception:
        _gpu["val"] = None
        _gpu["dead"] = True
    _gpu["t"] = now
    return _gpu["val"]


def _maybe_alert(key: str, cond: bool, text: str, level: str = "warn",
                 cooldown: float = 1800) -> None:
    """Post a dashboard notification when cond holds, at most once per cooldown."""
    now = time.monotonic()
    if cond and now - _alert_last.get(key, -cooldown) >= cooldown:
        _alert_last[key] = now
        memory.notify(text, level)


def system_stats() -> dict:
    if not _HAS_PSUTIL:
        return {"cpu": 0, "ram_pct": 0, "ram_used_gb": None,
                "disk_used_gb": None, "disk_total_gb": None, "load": 0, "psutil": False}
    vm = psutil.virtual_memory()
    drive = os.environ.get("SystemDrive", "C:") + "\\"
    try:
        du = psutil.disk_usage(drive)
        disk_used, disk_total, disk_pct = du.used / 1e9, du.total / 1e9, du.percent
    except Exception:
        disk_used = disk_total = disk_pct = None
    cpu = psutil.cpu_percent(interval=None)
    try:
        batt = psutil.sensors_battery()
        battery = {"pct": round(batt.percent), "plugged": batt.power_plugged} if batt else None
    except Exception:
        battery = None
    net_up, net_down = _net_rates()
    try:
        boot_uptime = time.time() - psutil.boot_time()
    except Exception:
        boot_uptime = None

    # Continuous monitoring — notify only when necessary (30-min cooldown each).
    _maybe_alert("cpu", cpu >= 92, f"CPU usage is critical: {round(cpu)}%.")
    _maybe_alert("ram", vm.percent >= 92, f"Memory usage is critical: {round(vm.percent)}%.")
    _maybe_alert("disk", bool(disk_pct and disk_pct >= 90),
                 f"System drive is {round(disk_pct or 0)}% full.", "alert")
    _maybe_alert("battery", bool(battery and not battery["plugged"] and battery["pct"] <= 20),
                 f"Battery at {battery['pct'] if battery else 0}% — connect the charger.", "alert")

    return {
        "cpu": cpu,
        "ram_pct": vm.percent,
        "ram_used_gb": vm.used / 1e9,
        "disk_used_gb": disk_used,
        "disk_total_gb": disk_total,
        "load": min(100, cpu * 0.7 + vm.percent * 0.3),
        "battery": battery,
        "net_up_kbs": net_up,
        "net_down_kbs": net_down,
        "gpu": _gpu_stats(),
        "boot_uptime": boot_uptime,
        "psutil": True,
    }


# ---- free news feed (Google News RSS, proxied to dodge browser CORS) --------
_news_cache = {"t": 0.0, "items": []}

# Last time the dashboard page talked to us (it polls /api/stats). The clap
# launcher reads ui_seconds_ago from /api/status to avoid opening ANOTHER
# window while you're already using Jackie, and listening_seconds_ago to
# pause its own mic ONLY while a page is actively listening (its poll says
# listening=1). A clap heard by the launcher while a page is open is queued
# in _clap and delivered on the page's next poll, waking it up.
_last_ui = {"t": 0.0}
_last_listen = {"t": 0.0}
_clap = {"t": 0.0}


def get_news() -> list:
    now = time.monotonic()
    if _news_cache["items"] and now - _news_cache["t"] < 600:
        return _news_cache["items"]
    import requests
    import xml.etree.ElementTree as ET
    url = os.environ.get(
        "JARVIS_NEWS_URL", "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en")
    r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (Jarvis)"})
    r.raise_for_status()
    items = []
    for it in ET.fromstring(r.content).iter("item"):
        title = (it.findtext("title") or "").strip()
        src = it.find("source")
        source = src.text.strip() if src is not None and src.text else ""
        # Google News titles end with " - Source"; drop the duplicate suffix.
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        # Some outlets register verbose names ("ABC News - Breaking News, …").
        source = source.split(" - ")[0][:28]
        items.append({
            "title": title,
            "link": (it.findtext("link") or "").strip(),
            "source": source,
            "date": (it.findtext("pubDate") or "").strip(),
        })
        if len(items) >= 12:
            break
    if items:
        _news_cache.update(t=now, items=items)
    return items


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # keep the console quiet
        pass

    # ---- helpers ----
    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode("utf-8"))

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    # ---- static files ----
    def _serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        safe = os.path.normpath(path).lstrip("\\/")
        full = os.path.join(WEB_DIR, safe)
        if not full.startswith(WEB_DIR) or not os.path.isfile(full):
            self._send(404, b"Not found", "text/plain")
            return
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            self._send(200, f.read(), _CTYPES.get(ext, "application/octet-stream"))

    # ---- routes ----
    def do_GET(self):
        if self.path.startswith("/api/status"):
            _, key, models, provider = config.resolve()
            now = time.monotonic()
            ago = now - _last_ui["t"] if _last_ui["t"] else None
            listen_ago = now - _last_listen["t"] if _last_listen["t"] else None
            return self._json({"backend": True, "provider": provider,
                               "has_key": bool(key), "models": models,
                               "ui_seconds_ago": round(ago, 1) if ago is not None else None,
                               "listening_seconds_ago": round(listen_ago, 1) if listen_ago is not None else None})
        if self.path.startswith("/api/stats"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            listening = q.get("listening", ["0"])[0] == "1"
            now = time.monotonic()
            _last_ui["t"] = now
            if listening:
                _last_listen["t"] = now
            out = system_stats()
            # Deliver a pending clap (heard by the background launcher) to the
            # listening tab — or to any tab when none is listening yet.
            if _clap["t"] and now - _clap["t"] < 12:
                someone_listening = bool(_last_listen["t"]) and now - _last_listen["t"] < 10
                if listening or not someone_listening:
                    out["clap"] = True
                    _clap["t"] = 0.0
            return self._json(out)
        if self.path.startswith("/api/news"):
            try:
                return self._json({"items": get_news()})
            except Exception as exc:
                return self._json({"items": [], "error": str(exc)[:200]})
        if self.path.startswith("/api/tasks"):
            return self._json({"tasks": memory.tasks()})
        if self.path.startswith("/api/notifications"):
            return self._json({"items": memory.notifications()})
        return self._serve_static(self.path.split("?")[0])

    def do_POST(self):
        if self.path.startswith("/api/settings"):
            d = self._read_json()
            updates = {}
            if d.get("provider"):
                updates["JARVIS_PROVIDER"] = d["provider"]
            if d.get("key"):
                prov = config.PROVIDERS.get(d.get("provider", "openrouter"), config.PROVIDERS["openrouter"])
                if prov["key_env"]:  # keyless providers (claude-cli) have nothing to store
                    updates[prov["key_env"]] = d["key"]
            if "model" in d:
                updates["JARVIS_MODELS"] = d.get("model", "")
            if "speak" in d:
                updates["JARVIS_SPEAK"] = "1" if d["speak"] else "0"
            if d.get("stt_lang"):
                updates["JARVIS_STT_LANG"] = d["stt_lang"]
            if updates:
                config.save_settings(updates)
            return self._json({"ok": True})

        if self.path.startswith("/api/test"):
            try:
                out = brain._chat([{"role": "user", "content": "Reply with one word: online"}])
                return self._json({"ok": True, "message": "Connected — " + out.strip()[:60]})
            except Exception as exc:
                return self._json({"ok": False, "message": str(exc)[:200]})

        if self.path.startswith("/api/tasks"):
            d = self._read_json()
            action = d.get("action")
            if action == "add" and (d.get("text") or "").strip():
                memory.add_task(d["text"])
            elif action == "toggle":
                memory.set_task_done(d.get("id"), bool(d.get("done", True)))
            elif action == "delete":
                memory.remove_task_by_id(d.get("id"))
            return self._json({"tasks": memory.tasks()})

        if self.path.startswith("/api/notifications"):
            if self._read_json().get("action") == "clear":
                memory.clear_notifications()
            return self._json({"items": memory.notifications()})

        if self.path.startswith("/api/clap"):
            # The background clap launcher heard a double clap while the
            # dashboard is already open: queue a wake-up for the page instead
            # of opening a duplicate window.
            _clap["t"] = time.monotonic()
            return self._json({"ok": True})

        if self.path.startswith("/api/stt"):
            # Server-side speech-to-text: the page records raw WAV and posts it
            # here, so voice input works even in browsers with broken/absent
            # SpeechRecognition (e.g. Edge). Free Google recognizer, no key.
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n) if n else b""
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            lang = (q.get("lang", [""])[0] or "").strip() or None
            try:
                import ears
                return self._json({"text": ears.stt_wav_bytes(raw, lang)})
            except Exception as exc:
                return self._json({"text": "", "error": str(exc)[:200]})

        if self.path.startswith("/api/chat"):
            _last_ui["t"] = time.monotonic()
            msg = (self._read_json().get("message") or "").strip()
            if not msg:
                return self._json({"events": [], "error": "empty message"})
            events = []
            agent = brain.Agent(
                on_say=lambda s: events.append({"type": "say", "text": s}),
                on_tool=lambda name, obs: events.append({"type": "tool", "text": f"{name} → {obs[:180]}"}),
            )
            try:
                agent.run(msg)
                return self._json({"events": events})
            except Exception as exc:
                return self._json({"events": events, "error": str(exc)[:300]})

        self._send(404, b"Not found", "text/plain")


def open_ui(url: str) -> None:
    """Open the dashboard, preferring Microsoft Edge: its free 'Natural'
    neural voices are what make Jackie sound human. Set JARVIS_BROWSER=default
    in .env to use the system default browser instead."""
    if os.environ.get("JARVIS_BROWSER", "edge").lower() == "edge":
        try:
            import subprocess
            subprocess.Popen(
                ["cmd", "/c", "start", "", "msedge", url],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return
        except Exception:
            pass
    webbrowser.open(url)


def _find_port(start=8765) -> int:
    import socket
    for p in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start


def main():
    try:
        env_port = os.environ.get("JARVIS_PORT") or os.environ.get("PORT")
        port = int(env_port) if env_port else _find_port()
        # allow_reuse_address=False: on Windows the default (True) lets a second
        # instance silently double-bind the same port — replies then come from a
        # random instance (often stale code). Fail loudly instead.
        ThreadingHTTPServer.allow_reuse_address = False
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        url = f"http://127.0.0.1:{port}/"
        if not os.environ.get("JARVIS_NO_BROWSER"):
            threading.Thread(target=lambda: (time.sleep(0.6), open_ui(url)), daemon=True).start()
        print(f"JACKIE 1.0 backend running at {url}  (Ctrl+C to stop)")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        # Windowed .exe has no console — leave a breadcrumb next to the app.
        try:
            with open(config._ROOT / "jarvis_error.log", "w", encoding="utf-8") as f:
                f.write(repr(exc))
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
