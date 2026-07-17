"""Jarvis desktop app — a real window you open like any program.

Paste your API key, click Save, then either clap-to-wake (mic) or type a command.
No terminal needed. Built on Tkinter (ships with Python), so nothing extra to install.
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

import brain
import config
import ears
import voice

APP_TITLE = "🤖 Jackie 1.0 — Desktop Agent"


class JarvisApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("780x660")
        root.minsize(680, 560)

        # label -> provider-key lookup for the dropdown
        self.labels = {v["label"]: k for k, v in config.PROVIDERS.items()}
        _, _, _, current_provider = config.resolve()

        self.provider_var = tk.StringVar(value=config.PROVIDERS[current_provider]["label"])
        self.key_var = tk.StringVar()
        self.model_var = tk.StringVar(value=os.environ.get("JARVIS_MODELS", ""))
        self.link_var = tk.StringVar()
        self.speak_var = tk.BooleanVar(value=config.SPEAK_REPLIES)
        self.status_var = tk.StringVar()

        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.run_lock = threading.Lock()
        self.log_queue: queue.Queue[str] = queue.Queue()

        self._build_ui()
        self._on_provider_change()

        # Route all stdout/stderr (agent + tool logs) into the on-screen console.
        sys.stdout = self  # type: ignore[assignment]
        sys.stderr = self  # type: ignore[assignment]
        self.root.after(80, self._drain)

        self._log("Welcome. Pick a provider, paste your API key, and press Save.")
        self._log(f"Microphone: {'available ✅' if ears.audio_available() else 'not found ⚠️  (use the text box)'}")
        self._refresh_status()

    # ---- UI construction --------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        header = ttk.Label(self.root, text="J A R V I S", font=("Segoe UI", 20, "bold"))
        header.pack(anchor="w", padx=12, pady=(12, 0))
        ttk.Label(
            self.root,
            text="Clap-to-wake voice agent that controls your PC. Powered by free AI models.",
            foreground="#6b7280",
        ).pack(anchor="w", padx=12)

        # --- settings card ---
        card = ttk.LabelFrame(self.root, text="  Connection  ")
        card.pack(fill="x", **pad)

        row1 = ttk.Frame(card)
        row1.pack(fill="x", padx=8, pady=6)
        ttk.Label(row1, text="AI provider:", width=12).pack(side="left")
        combo = ttk.Combobox(
            row1, textvariable=self.provider_var, values=list(self.labels.keys()),
            state="readonly",
        )
        combo.pack(side="left", fill="x", expand=True)
        combo.bind("<<ComboboxSelected>>", self._on_provider_change)

        row2 = ttk.Frame(card)
        row2.pack(fill="x", padx=8, pady=6)
        ttk.Label(row2, text="API key:", width=12).pack(side="left")
        self.key_entry = ttk.Entry(row2, textvariable=self.key_var, show="•")
        self.key_entry.pack(side="left", fill="x", expand=True)
        self.show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="show", variable=self.show_var,
                        command=self._toggle_show).pack(side="left", padx=6)

        row3 = ttk.Frame(card)
        row3.pack(fill="x", padx=8, pady=6)
        ttk.Label(row3, text="Model:", width=12).pack(side="left")
        ttk.Entry(row3, textvariable=self.model_var).pack(side="left", fill="x", expand=True)
        ttk.Label(row3, text="(optional — blank = provider default)",
                  foreground="#9ca3af").pack(side="left", padx=6)

        row4 = ttk.Frame(card)
        row4.pack(fill="x", padx=8, pady=6)
        ttk.Button(row4, text="💾  Save", command=self._save).pack(side="left")
        ttk.Button(row4, text="🔌  Test key", command=self._test_key).pack(side="left", padx=6)
        ttk.Checkbutton(row4, text="Speak replies aloud", variable=self.speak_var,
                        command=self._toggle_speak).pack(side="left", padx=6)
        link = ttk.Label(row4, textvariable=self.link_var, foreground="#2563eb", cursor="hand2")
        link.pack(side="right")
        link.bind("<Button-1>", lambda _e: webbrowser.open(self.link_var.get()))

        # --- controls ---
        ctrl = ttk.Frame(self.root)
        ctrl.pack(fill="x", **pad)
        self.start_btn = ttk.Button(ctrl, text="🎧  Start clap-to-wake", command=self._start_clap)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(ctrl, text="⏹  Stop", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        ttk.Label(ctrl, textvariable=self.status_var, foreground="#6b7280").pack(side="right")

        # --- console ---
        consframe = ttk.LabelFrame(self.root, text="  Jackie console  ")
        consframe.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.console = tk.Text(consframe, wrap="word", height=12, bg="#0b1020",
                               fg="#d1fae5", insertbackground="#d1fae5",
                               font=("Consolas", 10), state="disabled")
        self.console.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        sb = ttk.Scrollbar(consframe, command=self.console.yview)
        sb.pack(side="right", fill="y")
        self.console.configure(yscrollcommand=sb.set)

        # --- command box ---
        cmd = ttk.Frame(self.root)
        cmd.pack(fill="x", padx=10, pady=(0, 12))
        self.cmd_var = tk.StringVar()
        entry = ttk.Entry(cmd, textvariable=self.cmd_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self._send_text())
        ttk.Button(cmd, text="Send  ➤", command=self._send_text).pack(side="left", padx=6)

    # ---- console plumbing (stdout redirect) -------------------------------
    def write(self, s: str):  # file-like, called by print()
        if s:
            self.log_queue.put(s)

    def flush(self):
        pass

    def _log(self, msg: str):
        self.log_queue.put(msg + "\n")

    def _drain(self):
        try:
            while True:
                chunk = self.log_queue.get_nowait()
                self.console.configure(state="normal")
                self.console.insert("end", chunk)
                self.console.see("end")
                self.console.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(80, self._drain)

    # ---- settings handlers ------------------------------------------------
    def _provider_key(self) -> str:
        return self.labels[self.provider_var.get()]

    def _on_provider_change(self, *_):
        prov = config.PROVIDERS[self._provider_key()]
        self.key_var.set(os.environ.get(prov["key_env"], ""))
        self.link_var.set(f"Get a key ↗  {prov['key_url']}")
        self._refresh_status()

    def _toggle_show(self):
        self.key_entry.configure(show="" if self.show_var.get() else "•")

    def _toggle_speak(self):
        config.SPEAK_REPLIES = self.speak_var.get()

    def _save(self):
        provider = self._provider_key()
        prov = config.PROVIDERS[provider]
        updates = {
            "JARVIS_PROVIDER": provider,
            "JARVIS_MODELS": self.model_var.get().strip(),
            "JARVIS_SPEAK": "1" if self.speak_var.get() else "0",
        }
        key = self.key_var.get().strip()
        if key:
            updates[prov["key_env"]] = key
        config.SPEAK_REPLIES = self.speak_var.get()
        config.save_settings(updates)
        self._log(f"💾 Saved. Provider: {provider}. Key stored in jarvis/.env (never committed).")
        self._refresh_status()

    def _test_key(self):
        self._save()
        threading.Thread(target=self._test_key_worker, daemon=True).start()

    def _test_key_worker(self):
        self._log("🔌 Testing connection to the model...")
        try:
            out = brain._chat([{"role": "user", "content": "Reply with exactly one word: online"}])
            self._log(f"✅ Model responded: {out.strip()[:120]}")
        except Exception as exc:
            self._log(f"❌ {exc}")

    def _refresh_status(self):
        _, key, models, provider = config.resolve()
        state = "key set ✅" if key else "no key ✗"
        self.status_var.set(f"{provider} · {state} · model: {models[0] if models else '-'}")

    # ---- run controls -----------------------------------------------------
    def _start_clap(self):
        if self.worker and self.worker.is_alive():
            return
        if not ears.audio_available():
            self._log("⚠️  No microphone found — type your command in the box below instead.")
            return
        self.stop_event.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.worker = threading.Thread(target=self._clap_loop, daemon=True)
        self.worker.start()

    def _clap_loop(self):
        self._log("🎧 Listening... clap twice to wake Jackie.")
        while not self.stop_event.is_set():
            triggered = ears.wait_for_double_clap(self.stop_event)
            if not triggered:
                break
            voice.say("Yes?")
            command = ears.listen_command()
            if not command:
                voice.say("I didn't catch that.")
                continue
            self._run_goal(command)
        self.root.after(0, self._reset_buttons)

    def _reset_buttons(self):
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def _stop(self):
        self.stop_event.set()
        self._log("⏹ Stopped listening.")

    def _send_text(self):
        goal = self.cmd_var.get().strip()
        if not goal:
            return
        self.cmd_var.set("")
        self._log(f"💬 You: {goal}")
        threading.Thread(target=self._run_goal, args=(goal,), daemon=True).start()

    def _run_goal(self, goal: str):
        if not self.run_lock.acquire(blocking=False):
            self._log("⏳ Jackie is already working on something — one task at a time.")
            return
        try:
            brain.Agent(on_say=voice.say).run(goal)
        except Exception as exc:
            voice.say(f"Something went wrong: {exc}")
        finally:
            self.run_lock.release()


def main():
    root = tk.Tk()
    JarvisApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
