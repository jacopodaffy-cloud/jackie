"""Long-term memory for Jarvis — a tiny local JSON database.

Three stores, all plain JSON files in config.DATA_DIR (gitignored, lives next
to the exe so it persists between launches):

  memory.json         durable facts about the owner (preferences, projects,
                      contacts, habits, schedules) that personalize Jarvis
  tasks.json          the owner's task / reminder list (shown on the dashboard)
  notifications.json  cards for the dashboard notification center
  conversations.jsonl append-only log of every exchange

Everything returns short strings suitable as tool observations.
"""
from __future__ import annotations

import json
import threading
import time

import config

_LOCK = threading.Lock()

MEMORY_FILE = config.DATA_DIR / "memory.json"
TASKS_FILE = config.DATA_DIR / "tasks.json"
NOTES_FILE = config.DATA_DIR / "notifications.json"
CONVO_FILE = config.DATA_DIR / "conversations.jsonl"

CATEGORIES = ("preference", "project", "contact", "habit", "schedule", "note")

_MAX_FACTS = 400
_MAX_TASKS = 200
_MAX_NOTES = 50


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save(path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


# --------------------------------------------------------------------------
# Facts (the "become personalized over time" part)
# --------------------------------------------------------------------------
def remember(fact: str = "", category: str = "note", **_) -> str:
    fact = (fact or "").strip()
    if not fact:
        return "ERROR: nothing to remember."
    category = (category or "note").strip().lower()
    if category not in CATEGORIES:
        category = "note"
    with _LOCK:
        facts = _load(MEMORY_FILE, [])
        if any(f["fact"].lower() == fact.lower() for f in facts):
            return "Already remembered."
        facts.append({"fact": fact, "category": category, "ts": time.time()})
        _save(MEMORY_FILE, facts[-_MAX_FACTS:])
    return f"Remembered ({category}): {fact}"


def recall(query: str = "", **_) -> str:
    facts = _load(MEMORY_FILE, [])
    if not facts:
        return "(memory is empty)"
    q = (query or "").strip().lower()
    hits = [f for f in facts if q in f["fact"].lower()] if q else facts[-20:]
    if not hits:
        return f"No memory matches '{query}'."
    return "\n".join(f"[{f['category']}] {f['fact']}" for f in hits[-20:])


def forget(match: str = "", **_) -> str:
    match = (match or "").strip().lower()
    if not match:
        return "ERROR: say what to forget."
    with _LOCK:
        facts = _load(MEMORY_FILE, [])
        keep = [f for f in facts if match not in f["fact"].lower()]
        removed = len(facts) - len(keep)
        if removed:
            _save(MEMORY_FILE, keep)
    return f"Forgot {removed} fact(s)." if removed else f"No memory matches '{match}'."


def digest(max_chars: int = 1500) -> str:
    """Compact newest-first summary of stored facts, injected into the system
    prompt each run so the agent gets more personalized over time."""
    facts = _load(MEMORY_FILE, [])
    lines, used = [], 0
    for f in reversed(facts):
        line = f"- [{f['category']}] {f['fact']}"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def log_conversation(user: str, reply: str) -> None:
    """Append one exchange to the conversation log. Never raises."""
    try:
        entry = {"ts": time.time(), "user": user[:500], "jarvis": reply[:500]}
        with _LOCK, open(CONVO_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------
# Tasks / reminders
# --------------------------------------------------------------------------
def tasks() -> list:
    return _load(TASKS_FILE, [])


def add_task(text: str = "", **_) -> str:
    text = (text or "").strip()
    if not text:
        return "ERROR: empty task."
    with _LOCK:
        items = _load(TASKS_FILE, [])
        items.append({"id": int(time.time() * 1000), "text": text,
                      "done": False, "ts": time.time()})
        _save(TASKS_FILE, items[-_MAX_TASKS:])
    return f"Task added: {text}"


def _find_task(items: list, match) -> dict | None:
    m = str(match or "").strip().lower()
    for t in items:
        if str(t["id"]) == m:
            return t
    for t in items:
        if m and m in t["text"].lower():
            return t
    return None


def complete_task(match: str = "", **_) -> str:
    with _LOCK:
        items = _load(TASKS_FILE, [])
        t = _find_task(items, match)
        if not t:
            return f"No task matches '{match}'."
        t["done"] = True
        _save(TASKS_FILE, items)
    return f"Task done: {t['text']}"


def delete_task(match: str = "", **_) -> str:
    with _LOCK:
        items = _load(TASKS_FILE, [])
        t = _find_task(items, match)
        if not t:
            return f"No task matches '{match}'."
        items.remove(t)
        _save(TASKS_FILE, items)
    return f"Task removed: {t['text']}"


def list_tasks(**_) -> str:
    items = tasks()
    if not items:
        return "(no tasks)"
    return "\n".join(
        f"{'[x]' if t['done'] else '[ ]'} #{t['id']} {t['text']}" for t in items
    )


def set_task_done(task_id, done: bool) -> list:
    """UI helper: toggle by exact id, return the updated list."""
    with _LOCK:
        items = _load(TASKS_FILE, [])
        for t in items:
            if str(t["id"]) == str(task_id):
                t["done"] = bool(done)
        _save(TASKS_FILE, items)
    return items


def remove_task_by_id(task_id) -> list:
    with _LOCK:
        items = [t for t in _load(TASKS_FILE, []) if str(t["id"]) != str(task_id)]
        _save(TASKS_FILE, items)
    return items


# --------------------------------------------------------------------------
# Notifications (dashboard notification center)
# --------------------------------------------------------------------------
def notify(text: str = "", level: str = "info", **_) -> str:
    text = (text or "").strip()
    if not text:
        return "ERROR: empty notification."
    if level not in ("info", "warn", "alert"):
        level = "info"
    with _LOCK:
        items = _load(NOTES_FILE, [])
        items.append({"id": int(time.time() * 1000), "ts": time.time(),
                      "text": text[:300], "level": level})
        _save(NOTES_FILE, items[-_MAX_NOTES:])
    return f"Notification posted: {text[:80]}"


def notifications() -> list:
    return list(reversed(_load(NOTES_FILE, [])))


def clear_notifications() -> None:
    with _LOCK:
        _save(NOTES_FILE, [])
