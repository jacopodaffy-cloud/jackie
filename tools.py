"""The hands of Jarvis: tools that actually control the computer.

Each tool is a plain function taking keyword args and returning a short string
(the "observation" the model sees next). Keep returns compact — they go back
into the LLM context.
"""
from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import config
import memory

_MAX_OUTPUT = 4000


def _clip(text: str, limit: int = _MAX_OUTPUT) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def _resolve(path: str) -> Path:
    """Resolve a path. Relative paths land inside the Jarvis workspace."""
    p = Path(path)
    if not p.is_absolute():
        p = config.WORKSPACE / p
    return p


# --------------------------------------------------------------------------
# Shell / apps
# --------------------------------------------------------------------------
def _is_dangerous(command: str) -> bool:
    low = command.lower()
    return any(re.search(pat, low) for pat in config.DANGEROUS_PATTERNS)


def run_shell(command: str = "", **_) -> str:
    """Run a PowerShell command and return combined stdout/stderr."""
    command = (command or "").strip()
    if not command:
        return "ERROR: empty command."
    if config.BLOCK_DANGEROUS and _is_dangerous(command):
        return "REFUSED: that command is flagged as destructive and BLOCK_DANGEROUS is on."
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True,
            text=True,
            timeout=180,
            # Hidden console: the backend runs windowless (pythonw) — without
            # this every shell command flashes a window AND grandchild
            # processes can die with STATUS_CONTROL_C_EXIT on console teardown.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 180s."
    except Exception as exc:
        return f"ERROR: {exc}"
    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
    out = out.strip() or "(no output)"
    return _clip(f"exit={proc.returncode}\n{out}")


def open_app(name: str = "", **_) -> str:
    """Open an application, file, or URL via Start-Process (e.g. 'notepad', 'chrome')."""
    name = (name or "").strip()
    if not name:
        return "ERROR: no app name."
    safe = name.replace("'", "''")
    return run_shell(f"Start-Process '{safe}'")


def open_url(url: str = "", **_) -> str:
    """Open a URL in the default browser."""
    url = (url or "").strip()
    if not url:
        return "ERROR: no url."
    if not re.match(r"^[a-zA-Z]+://", url):
        url = "https://" + url
    safe = url.replace("'", "''")
    return run_shell(f"Start-Process '{safe}'")


# --------------------------------------------------------------------------
# Files (great for building games / code)
# --------------------------------------------------------------------------
def write_file(path: str = "", content: str = "", **_) -> str:
    """Create or overwrite a text file. Relative paths go in the workspace."""
    if not path:
        return "ERROR: no path."
    target = _resolve(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except Exception as exc:
        return f"ERROR: {exc}"
    return f"Wrote {len(content)} chars to {target}"


def read_file(path: str = "", **_) -> str:
    if not path:
        return "ERROR: no path."
    target = _resolve(path)
    try:
        return _clip(target.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return f"ERROR: {exc}"


def list_dir(path: str = ".", **_) -> str:
    target = _resolve(path or ".")
    try:
        items = sorted(os.listdir(target))
    except Exception as exc:
        return f"ERROR: {exc}"
    return _clip("\n".join(items) or "(empty)")


# --------------------------------------------------------------------------
# GUI automation (type / hotkeys / mouse / screenshot)
# --------------------------------------------------------------------------
def _pyautogui():
    import pyautogui

    pyautogui.FAILSAFE = False
    return pyautogui


def type_text(text: str = "", **_) -> str:
    """Type text at the current cursor position."""
    try:
        _pyautogui().typewrite(text, interval=0.01)
    except Exception as exc:
        return f"ERROR: {exc}"
    return f"Typed {len(text)} chars."


def press_keys(keys: str = "", **_) -> str:
    """Press a hotkey combo, e.g. 'ctrl s' or 'alt tab' or 'win r'."""
    parts = [k.strip() for k in re.split(r"[+\s]+", keys) if k.strip()]
    if not parts:
        return "ERROR: no keys."
    try:
        _pyautogui().hotkey(*parts)
    except Exception as exc:
        return f"ERROR: {exc}"
    return f"Pressed {'+'.join(parts)}."


def click(x=None, y=None, **_) -> str:
    """Click the mouse. With x,y click there; otherwise click current position."""
    try:
        pg = _pyautogui()
        if x is not None and y is not None:
            pg.click(int(x), int(y))
            return f"Clicked at {x},{y}."
        pg.click()
        return "Clicked."
    except Exception as exc:
        return f"ERROR: {exc}"


def screenshot(path: str = "screenshot.png", **_) -> str:
    """Capture the screen to a PNG in the workspace."""
    target = _resolve(path)
    try:
        img = _pyautogui().screenshot()
        target.parent.mkdir(parents=True, exist_ok=True)
        img.save(target)
    except Exception as exc:
        return f"ERROR: {exc}"
    return f"Saved screenshot to {target}"


# --------------------------------------------------------------------------
# Registry + spec text for the system prompt
# --------------------------------------------------------------------------
REGISTRY = {
    "run_shell": run_shell,
    "open_app": open_app,
    "open_url": open_url,
    "write_file": write_file,
    "read_file": read_file,
    "list_dir": list_dir,
    "type_text": type_text,
    "press_keys": press_keys,
    "click": click,
    "screenshot": screenshot,
    # long-term memory + personal organizer (memory.py, local JSON database)
    "remember": memory.remember,
    "recall": memory.recall,
    "forget": memory.forget,
    "add_task": memory.add_task,
    "complete_task": memory.complete_task,
    "list_tasks": memory.list_tasks,
    "notify": memory.notify,
}

TOOLS_SPEC = textwrap.dedent(
    """\
    - run_shell(command): Run a PowerShell command on Windows. Your most powerful
      tool: install software (winget), manage files, query the system, launch
      anything. Returns exit code + output.
    - open_app(name): Launch an app/file/URL, e.g. name="notepad", "calc", "chrome".
    - open_url(url): Open a web page in the default browser.
    - write_file(path, content): Create/overwrite a text file. Relative paths are
      saved in the Jarvis workspace. Use this to build games, scripts, HTML, etc.
    - read_file(path): Read a text file back.
    - list_dir(path): List a directory (default: workspace).
    - type_text(text): Type text via the keyboard at the current cursor.
    - press_keys(keys): Press a hotkey, e.g. keys="ctrl s", "alt tab", "win r".
    - click(x, y): Click the mouse (optionally at coordinates).
    - screenshot(path): Save a PNG screenshot to the workspace.
    - remember(fact, category): Store a durable fact about the owner in
      long-term memory. category: preference|project|contact|habit|schedule|note.
    - recall(query): Search long-term memory (empty query = recent facts).
    - forget(match): Delete memories containing the text.
    - add_task(text): Add a task/reminder to the owner's dashboard task list.
    - complete_task(match): Mark a task done (by id or matching text).
    - list_tasks(): Show the owner's current tasks.
    - notify(text, level): Post a card to the dashboard notification center.
      level: info|warn|alert. Use sparingly — only when genuinely useful.
    """
)


def call(name: str, args: dict) -> str:
    fn = REGISTRY.get(name)
    if not fn:
        return f"ERROR: unknown tool '{name}'. Valid tools: {', '.join(REGISTRY)}"
    if not isinstance(args, dict):
        args = {}
    try:
        return fn(**args)
    except TypeError as exc:
        return f"ERROR: bad arguments for {name}: {exc}"
    except Exception as exc:
        return f"ERROR while running {name}: {exc}"
