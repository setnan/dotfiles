#!/usr/bin/env python3
"""Alfred Script Filter: `cc [mappe] [prompt]` – start Claude Code i et prosjekt.

Lists directories from zoxide (most used first). The first word of the query
filters the list; everything after it becomes the prompt that Claude Code is
started with. If the first word matches no directory the whole query is the
prompt. Enter → `claude "<prompt>"` in a new Ghostty tab (ghostty_run.py),
Cmd+Enter → `claude --continue "<prompt>"` (continue the latest session there).
"""
import json
import os
import subprocess
import sys

HOME = os.path.expanduser("~")
ZOXIDE = next(
    (p for p in ("/opt/homebrew/bin/zoxide", "/usr/local/bin/zoxide") if os.path.exists(p)),
    "zoxide",
)


def zoxide_dirs():
    try:
        out = subprocess.run([ZOXIDE, "query", "-l"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        out = ""
    dirs = [l.strip() for l in out.splitlines() if l.strip()]
    for extra in (os.path.join(HOME, ".dotfiles"), HOME):
        if extra not in dirs:
            dirs.append(extra)
    seen, result = set(), []
    for d in dirs:
        key = d.lower()
        if key in seen or not os.path.isdir(d):
            continue
        seen.add(key)
        result.append(d)
    return result


def short(path):
    return "~" + path[len(HOME):] if path == HOME or path.startswith(HOME + "/") else path


def matches(dirs, filt):
    f = filt.lower()
    starts = [d for d in dirs if os.path.basename(d).lower().startswith(f)]
    contains = [d for d in dirs if d not in starts and f in d.lower()]
    return starts + contains


def item(d, prompt, continue_prompt=False):
    name = os.path.basename(d) or d
    if d == HOME:
        name = "~"
    args = ["claude"] + ([prompt] if prompt else [])
    cont = ["claude", "--continue"] + ([prompt] if prompt else [])
    what = f'claude "{prompt}"' if prompt else "claude"
    return {
        "uid": d,
        "title": name,
        "subtitle": f"{short(d)}  ·  {what} i ny Ghostty-fane",
        "arg": json.dumps({"dir": d, "args": args}),
        "icon": {"type": "fileicon", "path": d},
        "mods": {
            "cmd": {
                "subtitle": f"{short(d)}  ·  claude --continue (fortsett siste økt her)",
                "arg": json.dumps({"dir": d, "args": cont}),
            }
        },
    }


def main():
    query = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    dirs = zoxide_dirs()
    first, _, rest = query.partition(" ")
    hits = matches(dirs, first) if first else dirs
    if first and not hits:  # no directory matched: the whole query is the prompt
        hits, rest = dirs, query
    prompt = rest.strip()
    items = [item(d, prompt) for d in hits[:40]]
    if not items:
        items = [{"title": "Ingen mapper funnet", "subtitle": "zoxide har ingen treff", "valid": False}]
    print(json.dumps({"items": items}, ensure_ascii=False))


if __name__ == "__main__":
    main()
