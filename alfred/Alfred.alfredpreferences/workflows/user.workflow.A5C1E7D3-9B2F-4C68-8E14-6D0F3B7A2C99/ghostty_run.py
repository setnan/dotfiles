#!/usr/bin/env python3
"""Open a new Ghostty tab, cd into a directory and run a command.

Usage: ghostty_run.py '{"dir": "/path", "args": ["claude", "prompt"]}'

Ghostty has no CLI for opening tabs on macOS, so the command is written to a
one-shot script in the workflow cache and Ghostty is driven with System
Events: activate, Cmd+T (Cmd+N if no window is open, nothing if Ghostty was
just launched), then `source '<script>'` + Return is typed into the new tab.
The script removes itself before running the command, and the shell stays
open after the command exits.
"""
import json
import os
import shlex
import subprocess
import sys
import uuid

CACHE_DIR = os.environ.get("alfred_workflow_cache") or os.path.expanduser("~/Library/Caches/no.etnan.claude")


def osa(script):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
    return r.stdout.strip()


def as_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main():
    spec = json.loads(sys.argv[1])
    d, args = spec["dir"], spec["args"]
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"run-{uuid.uuid4().hex[:8]}.sh")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"cd {shlex.quote(d)} || return\n")
        f.write(f"rm -f {shlex.quote(path)}\n")
        f.write("clear\n")
        f.write(" ".join(shlex.quote(a) for a in args) + "\n")
    os.chmod(path, 0o700)

    running = osa('tell application "System Events" to (name of processes) contains "ghostty"') == "true"
    windows = int(osa('tell application "System Events" to tell process "ghostty" to count windows') or 0) if running else 0
    typed = as_str(f" source {shlex.quote(path)}")
    if not running:
        new_surface = ""  # launching Ghostty opens its first window by itself
    elif windows == 0:
        new_surface = 'keystroke "n" using command down'
    else:
        new_surface = 'keystroke "t" using command down'
    osa(f'''
        tell application "Ghostty" to activate
        tell application "System Events"
            repeat 50 times
                if (exists process "ghostty") and frontmost of process "ghostty" then exit repeat
                delay 0.1
            end repeat
            {new_surface}
            tell process "ghostty"
                repeat 50 times
                    if (count of windows) > 0 then exit repeat
                    delay 0.1
                end repeat
            end tell
            delay {0.9 if not running else 0.35}
            keystroke {typed}
            key code 36
        end tell
    ''')


if __name__ == "__main__":
    main()
