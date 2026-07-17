"""The brain of Jarvis: an LLM agent loop over free OpenRouter models.

Uses a model-agnostic JSON action protocol (ReAct style) instead of relying on
native function-calling, so it works with almost any free chat model. Each turn
the model returns ONE JSON object choosing a tool or finishing.
"""
from __future__ import annotations

import json
import platform
from typing import Callable, Optional

import requests

import config
import memory
import tools

_PROMPT_TEMPLATE = f"""\
You are JACKIE (Jackie 1.0), an autonomous AI operating system in the style of
Iron Man's JARVIS, running on a real {platform.system()} computer that you operate
for its owner.
You are their executive assistant, software engineer and automation agent.
You get things DONE with tools — you do not just describe what to do.

MISSION, in priority order:
1. Achieve the owner's goal with minimum effort on their part.
2. Think before acting; after acting, verify the result before claiming success.
3. Keep working until the task is fully complete — never stop halfway.
4. Never fabricate results. If information is missing, obtain it with tools.
5. Speak like JARVIS: concise, natural, proactive, address the owner as "sir".

You control the machine ONLY through these tools:
{tools.TOOLS_SPEC}

PROTOCOL — every reply MUST be exactly ONE JSON object, nothing else, no markdown fences:
  To use a tool:
    {{"say": "<short spoken line, optional>", "action": "<tool_name>", "args": {{...}}}}
  To finish the task and report back:
    {{"say": "<final spoken summary>", "action": "final"}}

Rules:
- Output raw JSON only. No prose before or after. No ``` fences.
- Take ONE action per reply. You will be given the tool result, then continue.
- Break big goals into steps (e.g. building a game: write the file, then open it).
- Prefer write_file for code/games and run_shell for system tasks.
- Keep "say" lines short and natural, like a helpful assistant speaking aloud.
- When the goal is achieved, use action "final" with a concise summary.
- If a tool errors, read the error and adapt; don't repeat the same failing call.
- The working directory for relative file paths is the Jarvis workspace.
- DESTRUCTIVE operations (mass deletion, overwriting the owner's documents,
  shutdown/restart, closing unsaved work): do NOT execute. Use action "final"
  to describe what would happen and ask the owner to confirm first.
- AUDIO PROBLEMS: if the owner says the microphone, voice input or claps do
  not work, run  .venv\\Scripts\\python.exe mic_check.py  with run_shell, read
  its VERDICT section and explain the cause and fix in plain words.
- MEMORY: when you learn something durable about the owner (a preference,
  project, contact, habit, schedule), store it with remember(...). Use
  recall(query) when past context would help. When the owner mentions a todo
  or reminder, use add_task. Use notify only for genuinely useful warnings
  or proactive suggestions.

LONG-TERM MEMORY — facts learned in previous sessions. Use them to personalize:
{{memory_digest}}
"""


def build_system_prompt() -> str:
    """System prompt with the current long-term memory digest injected, so
    Jarvis gets more personalized every session."""
    return _PROMPT_TEMPLATE.replace(
        "{memory_digest}", memory.digest() or "(empty — nothing remembered yet)"
    )


# Back-compat for code/tests that import the constant.
SYSTEM_PROMPT = build_system_prompt()


def _extract_json(text: str) -> Optional[dict]:
    """Pull the first balanced JSON object out of a model reply."""
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            break
        start = text.find("{", start + 1)
    return None


def _anthropic_chat(url: str, api_key: str, model: str, messages: list) -> requests.Response:
    """One request against Anthropic's native Messages API.

    Differences from the OpenAI shape: auth via x-api-key, the system prompt is
    a top-level field, max_tokens is required, and no temperature (rejected on
    Opus 4.7+). Replies here are single JSON actions, so 4096 tokens is plenty.
    """
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [m for m in messages if m["role"] != "system"]
    return requests.post(
        url,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={"model": model, "max_tokens": 4096, "system": system, "messages": turns},
        timeout=config.HTTP_TIMEOUT,
    )


def _find_claude_cli() -> list:
    """Locate the Claude Code CLI; on Windows run its cli.js via node so we
    don't need cmd.exe (avoids shell quoting entirely)."""
    import shutil
    from pathlib import Path

    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError(
            "Claude Code CLI not found. Install it with "
            "`npm install -g @anthropic-ai/claude-code`, then run `claude` "
            "and /login once (no API key needed)."
        )
    p = Path(exe)
    if p.suffix.lower() in (".cmd", ".bat", ".ps1"):
        cli_js = p.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
        if cli_js.exists():
            return ["node", str(cli_js)]
        return ["cmd", "/c", str(p.with_suffix(".cmd"))]
    return [str(exe)]


def _claude_cli_chat(models: list, messages: list) -> str:
    """One completion through the local Claude Code CLI (subscription login,
    no API key). The transcript is flattened into a single stdin prompt and
    the CLI is used as a pure text generator — Jarvis's own tool loop stays
    in charge, so PC control keeps working exactly as with other providers."""
    import subprocess

    cmd = _find_claude_cli() + ["-p", "--output-format", "json", "--max-turns", "1"]
    model = next((m for m in models if m and m != "default"), "")
    if model:
        cmd += ["--model", model]

    parts = []
    has_system = False
    for m in messages:
        if m["role"] == "system":
            has_system = True
            parts.append(m["content"])
        else:
            who = "OWNER" if m["role"] == "user" else "JARVIS"
            parts.append(f"{who}:\n{m['content']}")
    tail = "Respond now with the next reply ONLY, as plain text. Do not use any tools."
    if has_system:
        tail += " Follow the PROTOCOL above exactly (one raw JSON object)."
    parts.append(tail)

    proc = subprocess.run(
        cmd,
        input="\n\n".join(parts),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(config.HTTP_TIMEOUT, 180),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        detail = (proc.stderr or proc.stdout or "no output").strip()[-300:]
        raise RuntimeError(f"Claude Code CLI error: {detail}")

    text = (data.get("result") or "").strip()
    if "Not logged in" in text:
        raise RuntimeError(
            "Claude Code is not logged in — open a terminal, run `claude`, "
            "type /login and sign in (one-time, no API key)."
        )
    if not text:
        raise RuntimeError(f"Claude Code returned an empty reply (subtype={data.get('subtype')}).")
    return text


def _chat(messages: list) -> str:
    """Call the active provider, trying each model until one answers."""
    url, api_key, models, provider = config.resolve()
    prov = config.PROVIDERS[provider]
    if prov.get("kind") == "claude-cli":
        return _claude_cli_chat(models, messages)
    if not api_key:
        raise RuntimeError(
            f"No API key set for provider '{provider}'. Paste your key in the "
            f"Jarvis app (or jarvis/.env). Get one at {prov['key_url']}"
        )
    anthropic = prov.get("kind") == "anthropic"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # OpenRouter uses these two for attribution; harmless elsewhere.
        "HTTP-Referer": "https://github.com/jacopodaffy-cloud/jarvis",
        "X-Title": "Jarvis Desktop Agent",
    }
    last_err = None
    for model in models:
        try:
            if anthropic:
                resp = _anthropic_chat(url, api_key, model, messages)
                if resp.status_code == 200:
                    data = resp.json()
                    text = "".join(
                        b.get("text", "") for b in data.get("content", [])
                        if b.get("type") == "text"
                    )
                    if text:
                        return text
                    last_err = f"{model}: empty reply (stop_reason={data.get('stop_reason')})"
                    continue
            else:
                resp = requests.post(
                    url,
                    headers=headers,
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": config.TEMPERATURE,
                    },
                    timeout=config.HTTP_TIMEOUT,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
            last_err = f"{model}: HTTP {resp.status_code} {resp.text[:200]}"
        except Exception as exc:  # network / json / etc — try next model
            last_err = f"{model}: {exc}"
    raise RuntimeError(f"All models failed. Last error: {last_err}")


class Agent:
    """Runs a single goal to completion using the tool loop."""

    def __init__(
        self,
        on_say: Optional[Callable[[str], None]] = None,
        on_tool: Optional[Callable[[str, str], None]] = None,
    ):
        self.on_say = on_say or (lambda s: None)
        # on_tool(name, observation) — lets a UI show each action Jarvis takes.
        self.on_tool = on_tool or (lambda name, obs: None)

    def run(self, goal: str) -> str:
        messages = [
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": goal},
        ]
        final = "Done."
        for step in range(config.MAX_STEPS):
            reply = _chat(messages)
            action = _extract_json(reply)

            if not action or "action" not in action:
                # Model spoke plainly instead of JSON — treat it as the answer.
                final = reply.strip() or final
                self.on_say(final)
                memory.log_conversation(goal, final)
                return final

            say = str(action.get("say", "")).strip()
            if say:
                self.on_say(say)

            name = action.get("action")
            if name == "final":
                memory.log_conversation(goal, say or final)
                return say or final

            args = action.get("args", {}) or {}
            print(f"   ⚙️  {name}({json.dumps(args, ensure_ascii=False)[:200]})")
            observation = tools.call(name, args)
            print(f"   → {observation[:300]}")
            self.on_tool(name, observation)

            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": f"TOOL_RESULT:\n{observation}"})

        note = "Reached the step limit. Stopping."
        self.on_say(note)
        memory.log_conversation(goal, note)
        return note
