# 💜 Jackie — your personal AI assistant

An Iron-Man-style AI assistant with a living **energy orb** that reacts to your
voice, live system stats, weather, news, tasks, camera with hand-gesture
control — and a real agent brain that can **do things on your computer**:
run commands, open apps, write code and files.

Say **"Hey Jackie"**, **double-clap your hands** (works even with quiet claps —
dual-channel transient detection), or just type.

> ⚡ With the backend running, an LLM gets genuine control of your machine.
> Read the **Safety** section before turning off the guardrails.

---

## 📱 Use Jackie on your phone (like Hey Google)

Open **<https://jacopodaffy-cloud.github.io/jackie/>** on your phone, then:

- **Android / Chrome**: menu ⋮ → **Add to Home screen** → *Install*
- **iPhone / Safari**: Share → **Add to Home Screen**

Jackie installs as a real app (icon, full screen, works offline). Tap the mic,
speak, and she answers out loud. On the phone she runs in *lite mode*: chatting
needs a free API key (Settings ⚙ → OpenRouter → paste the key). Computer
control only works on the PC where the backend runs.

*In italiano: apri il link sul telefono, poi "Aggiungi a schermata Home" —
Jackie si installa come un'app vera. Tocca il microfono e parlale.*

## 🖥️ Full power on Windows

```
git clone https://github.com/jacopodaffy-cloud/jackie.git
cd jackie
Jackie.bat            # first run creates the venv and installs everything
```

- **`Jackie.bat`** — opens the dashboard with full computer control.
- **`Jackie Clap Listener.bat`** — background listener: double-clap anywhere
  and Jackie opens. Put a shortcut to it in `shell:startup` (run
  `pythonw clap_launcher.py` for a windowless start) and Jackie greets you at
  every boot.
- **`Clap Test.bat`** — see exactly what your microphone hears and calibrate.
- **`Mic Check.bat`** — full microphone diagnosis (privacy, mute, levels).

Voice replies sound most human in **Microsoft Edge** (free neural "Natural"
voices) — Jackie opens there by default.

## 🧠 Brains (pick one in Settings)

| Provider | Key | Notes |
|---|---|---|
| **Claude Code** | none — uses your Claude login | strongest agent, backend only |
| OpenRouter | free key | Qwen3, GLM, DeepSeek, Llama with fallback |
| Gemini / Groq / Claude API / Z.ai / DeepSeek / Qwen | free/paid key | browser-friendly ones work on the phone too |

## 🎙️ Listening, deeply

- **Double-clap detection** runs on TWO channels: amplitude + high-pass
  transient. Quiet claps trigger it; fans, music and speech don't.
- If the default mic is dead (hardware mute), Jackie **probes every input
  device** and locks onto one that hears the room. Force one with
  `JARVIS_INPUT_DEVICE` in `.env`.
- The dashboard and the background listener coordinate: exactly **one** of
  them listens at any time, and a clap heard in the background **wakes the
  open dashboard** instead of spawning duplicate windows.

## 🛡️ Safety

Dangerous shell patterns (formatting drives, deleting Windows, fork bombs) are
always blocked; destructive actions require your confirmation. Set
`JARVIS_BLOCK_DANGEROUS=0` in `.env` only if you accept the risk. Your `.env`,
memory, logs and conversations stay local — they are gitignored.

---

Built with Python (stdlib server), vanilla JS, Web Audio, MediaPipe and a
free-model agent loop. No frameworks, no build step.
