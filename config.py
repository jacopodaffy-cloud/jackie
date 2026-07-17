"""Configuration for Jarvis.

All settings load from environment variables (optionally a local .env file).
Nothing here is secret except the API key, which never gets committed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make console output Unicode-safe on Windows. The logs use emojis (⚙️, 🤖, →);
# the legacy cp1252 console would raise UnicodeEncodeError without this.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

# --- Base directory ---------------------------------------------------------
# When packaged into an .exe (PyInstaller), keep .env / workspace NEXT TO the
# executable so the user's saved API key persists between launches. In dev,
# use the source folder.
if getattr(sys, "frozen", False):
    _ROOT = Path(sys.executable).resolve().parent
else:
    _ROOT = Path(__file__).resolve().parent

# --- Load .env if present (tiny parser, no hard dependency) -----------------
_ENV_FILE = _ROOT / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# --- LLM brain --------------------------------------------------------------
# Jarvis talks to any OpenAI-compatible chat endpoint. Pick a provider, paste
# that provider's API key, and go. OpenRouter is the recommended default: ONE
# free key gives access to Qwen3, GLM, DeepSeek and Llama, with fallback.
#
# Each provider: label, endpoint URL, which env var holds its key, where to get
# a key, and a default model fallback chain (tried top to bottom).
PROVIDERS = {
    "claudecode": {
        # Runs the LOCAL Claude Code CLI — authenticates with your Claude
        # subscription login (one-time `claude` -> /login). NO API key at all.
        # Backend-only: the browser can't spawn a local process, so lite mode
        # can't use this provider.
        "label": "Claude Code — your Claude subscription (no API key)",
        "url": "",
        "key_env": "",
        "key_url": "https://claude.com/claude-code",
        "models": ["default"],   # your Claude Code default; or sonnet / opus / haiku
        "kind": "claude-cli",
    },
    "openrouter": {
        "label": "OpenRouter — FREE (Qwen3 + GLM + DeepSeek + Llama)",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key_env": "OPENROUTER_API_KEY",
        "key_url": "https://openrouter.ai/keys",
        "models": [
            "qwen/qwen3-235b-a22b:free",           # Qwen3 (the "Gwen 3" you meant)
            "z-ai/glm-4.5-air:free",                # GLM  (the "GLM-Z" you meant)
            "deepseek/deepseek-chat-v3.1:free",
            "meta-llama/llama-3.3-70b-instruct:free",
        ],
    },
    "gemini": {
        "label": "Google Gemini — FREE (gemini flash)",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "key_env": "GEMINI_API_KEY",
        "key_url": "https://aistudio.google.com/apikey",
        "models": ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"],
    },
    "groq": {
        "label": "Groq — FREE (Llama, ultra-fast)",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key_env": "GROQ_API_KEY",
        "key_url": "https://console.groq.com/keys",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
    },
    "claude": {
        # Anthropic's native Messages API (not OpenAI-shaped) — brain._chat and
        # the web UI branch on kind="anthropic" to speak its protocol.
        "label": "Claude — Anthropic (Opus 4.8, the strongest brain)",
        "url": "https://api.anthropic.com/v1/messages",
        "key_env": "ANTHROPIC_API_KEY",
        "key_url": "https://console.anthropic.com/settings/keys",
        "models": ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"],
        "kind": "anthropic",
    },
    "zai": {
        "label": "Z.ai — GLM (glm-4.6 / glm-4.5)",
        "url": "https://api.z.ai/api/paas/v4/chat/completions",
        "key_env": "ZAI_API_KEY",
        "key_url": "https://z.ai/manage-apikey/apikey-list",
        "models": ["glm-4.6", "glm-4.5", "glm-4.5-air"],
    },
    "deepseek": {
        "label": "DeepSeek — deepseek-chat",
        "url": "https://api.deepseek.com/chat/completions",
        "key_env": "DEEPSEEK_API_KEY",
        "key_url": "https://platform.deepseek.com/api_keys",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "qwen": {
        "label": "Qwen — Alibaba Model Studio (DashScope)",
        "url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
        "key_env": "QWEN_API_KEY",
        "key_url": "https://bailian.console.alibabacloud.com/",
        "models": ["qwen-plus", "qwen-max", "qwen3-235b-a22b"],
    },
}

PROVIDER = _get("JARVIS_PROVIDER", "openrouter")
if PROVIDER not in PROVIDERS:
    PROVIDER = "openrouter"

# Optional overrides (advanced / self-hosted): force a base URL or model list.
BASE_URL_OVERRIDE = _get("JARVIS_BASE_URL")
MODELS_OVERRIDE = [m.strip() for m in _get("JARVIS_MODELS", "").split(",") if m.strip()]

TEMPERATURE = float(_get("JARVIS_TEMPERATURE", "0.3"))
MAX_STEPS = int(_get("JARVIS_MAX_STEPS", "14"))
HTTP_TIMEOUT = int(_get("JARVIS_HTTP_TIMEOUT", "120"))


def resolve():
    """Return the active provider's LIVE settings, read fresh from the env.

    Reading fresh each call means the GUI's Save button updates behaviour
    without a restart. Returns (url, api_key, models, provider_key).
    """
    provider = _get("JARVIS_PROVIDER", "openrouter")
    if provider not in PROVIDERS:
        provider = "openrouter"
    prov = PROVIDERS[provider]
    url = _get("JARVIS_BASE_URL") or prov["url"]
    # Keyless providers (claude-cli) report a placeholder so the UI's
    # "has key" checks light up green — there is genuinely nothing to paste.
    key = _get(prov["key_env"]) if prov["key_env"] else "subscription"
    override = [m.strip() for m in _get("JARVIS_MODELS", "").split(",") if m.strip()]
    models = override or prov["models"]
    return url, key, models, provider


# Back-compat: some code / docs still reference these.
OPENROUTER_API_KEY = _get("OPENROUTER_API_KEY")
_ru, _rk, MODELS, _rp = resolve()


def save_settings(updates: dict) -> None:
    """Merge key=value pairs into the .env file, preserving existing lines.

    Used by the GUI's 'Save' button so the API key is stored on disk and picked
    up on the next launch. .env is gitignored, so keys never reach GitHub.
    """
    existing = {}
    order = []
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                k = k.strip()
                if k not in existing:
                    order.append(k)
                existing[k] = v.strip()
    for k, v in updates.items():
        if k not in existing:
            order.append(k)
        existing[k] = str(v)
        os.environ[k] = str(v)  # take effect immediately, this run
    lines = ["# Jarvis settings — auto-managed. Safe to edit. Never commit this file."]
    lines += [f"{k}={existing[k]}" for k in order]
    _ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

# --- Voice / audio ----------------------------------------------------------
SAMPLE_RATE = int(_get("JARVIS_SAMPLE_RATE", "16000"))
WAKE_WORD = _get("JARVIS_WAKE_WORD", "jackie").lower()
SPEAK_REPLIES = _get("JARVIS_SPEAK", "1") != "0"           # TTS out loud
TTS_RATE = int(_get("JARVIS_TTS_RATE", "180"))

# Clap detection tuning
CLAP_MIN_GAP = float(_get("JARVIS_CLAP_MIN_GAP", "0.12"))  # seconds between claps
CLAP_MAX_GAP = float(_get("JARVIS_CLAP_MAX_GAP", "0.90"))
CLAP_THRESHOLD = float(_get("JARVIS_CLAP_THRESHOLD", "0.01"))  # abs min peak (0..1)
CLAP_REFRACTORY = float(_get("JARVIS_CLAP_REFRACTORY", "0.08"))
CLAP_RATIO = float(_get("JARVIS_CLAP_RATIO", "5"))  # spike = RATIO × noise floor

# Speech-to-text language for the free Google recognizer.
STT_LANGUAGE = _get("JARVIS_STT_LANG", "en-US")

# --- Safety / power ---------------------------------------------------------
# The workspace is where Jarvis writes generated code, games, notes, etc.
WORKSPACE = Path(_get("JARVIS_WORKSPACE", str(_ROOT / "workspace")))
WORKSPACE.mkdir(parents=True, exist_ok=True)

# Local database for long-term memory, tasks and notifications (never committed).
DATA_DIR = Path(_get("JARVIS_DATA_DIR", str(_ROOT / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# When True, shell commands flagged as dangerous are blocked outright.
# When False, Jarvis has "max power" and will run them. Your call.
BLOCK_DANGEROUS = _get("JARVIS_BLOCK_DANGEROUS", "1") != "0"

# Patterns that are always refused (irreversible, catastrophic).
DANGEROUS_PATTERNS = [
    r"format\s+[a-z]:",
    r"\bdiskpart\b",
    r"\bdel\b.*\\windows",
    r"rmdir\s+/s.*\\windows",
    r"remove-item.*c:\\windows",
    r"rm\s+-rf\s+/",
    r"\bcipher\s+/w",
    r"\bmkfs\b",
    r":\(\)\s*\{\s*:\|:",   # fork bomb
]
