"""Jarvis — a clap-to-wake, voice-controlled desktop agent.

Modes:
  py jarvis.py                 Clap twice to wake, then speak a command (voice).
  py jarvis.py --text          Type commands instead of speaking (no mic needed).
  py jarvis.py do "GOAL"       Run a single goal and exit (great for scripting).
  py jarvis.py --no-clap       Voice mode but skip clap; press Enter to talk.

Try:  py jarvis.py do "build a snake game in html and open it in my browser"
"""
from __future__ import annotations

import sys

import brain
import config
import voice
from ears import audio_available, listen_command, wait_for_double_clap

BANNER = r"""
     _   _    ____  __     __  _____  ____
    | | / \  |  _ \ \ \   / / |_   _|/ ___|
 _  | |/ _ \ | |_) | \ \ / /    | |  \___ \
| |_| / ___ \|  _ <   \ V /     | |   ___) |
 \___/_/   \_\_| \_\   \_/      |_|  |____/
        Jarvis  ·  your desktop agent
"""


def _handle(goal: str) -> None:
    goal = (goal or "").strip()
    if not goal:
        return
    if goal.lower() in {"exit", "quit", "stop", "goodbye", "shut down"}:
        voice.say("Powering down. Goodbye.")
        raise SystemExit(0)
    agent = brain.Agent(on_say=voice.say)
    try:
        agent.run(goal)
    except Exception as exc:
        voice.say(f"Something went wrong: {exc}")


def run_once(goal: str) -> None:
    print(BANNER)
    _handle(goal)


def run_text_loop() -> None:
    print(BANNER)
    voice.say("Text mode ready. Type a command, or 'exit'.")
    while True:
        try:
            goal = input("\n💬 You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        _handle(goal)


def run_voice_loop(use_clap: bool = True) -> None:
    print(BANNER)
    if not audio_available():
        print("⚠️  No working microphone/audio backend detected — switching to text mode.")
        return run_text_loop()

    voice.say("Jarvis online.")
    while True:
        try:
            if use_clap:
                if not wait_for_double_clap():
                    print("⚠️  Clap detection unavailable — switching to text mode.")
                    return run_text_loop()
                voice.say("Yes?")
            else:
                input("\nPress Enter, then speak... ")

            command = listen_command()
            if not command:
                voice.say("I didn't catch that.")
                continue
            _handle(command)
        except KeyboardInterrupt:
            print()
            voice.say("Goodbye.")
            break


def main(argv: list[str]) -> None:
    args = argv[1:]

    if args and args[0] == "do":
        return run_once(" ".join(args[1:]))
    if "--text" in args:
        return run_text_loop()
    if "--no-clap" in args:
        return run_voice_loop(use_clap=False)
    return run_voice_loop(use_clap=True)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except KeyboardInterrupt:
        pass
