#!/usr/bin/env python3
"""Alfred: save and restore window layouts via System Events (Accessibility).

Usage:
  layout.py list "<query>"   script-filter JSON: saved layouts, or a "save as" row
  layout.py save <name>      snapshot every visible window (app, title, frame)
  layout.py apply <name>     move/resize windows back to the saved frames
  layout.py delete <name>

Layouts are JSON files in LAYOUT_DIR (workflow variable `layouts_dir`,
default: the `layouts/` folder next to this script, so they live in dotfiles).

Matching on apply: per app, windows are matched by exact title, then by
title prefix/substring, then by order among the still-unmatched windows, so
browsers and editors whose titles change still get their frames back.
Apps that are not running are launched first (`launch_missing`, default on).
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUT_DIR = (os.environ.get("layouts_dir") or "").strip() or os.path.join(HERE, "layouts")
LAUNCH_MISSING = (os.environ.get("launch_missing") or "1").strip() not in ("0", "false", "")
SEP = "␟"  # unit separator, never in titles
BUNDLE_SKIP = {"com.apple.finder.desktop", "com.runningwithcrayons.Alfred"}

SNAPSHOT_AS = f'''
set sep to "{SEP}"
set out to ""
tell application "System Events"
  repeat with p in (application processes whose visible is true and background only is false)
    set pname to name of p
    set bid to ""
    try
      set bid to bundle identifier of p
    end try
    set i to 0
    repeat with w in windows of p
      set i to i + 1
      try
        if subrole of w is "AXStandardWindow" then
          set {{x, y}} to position of w
          set {{wd, ht}} to size of w
          set mini to false
          try
            set mini to value of attribute "AXMinimized" of w
          end try
          set out to out & pname & sep & bid & sep & (name of w) & sep & x & sep & y & sep & wd & sep & ht & sep & mini & sep & i & linefeed
        end if
      end try
    end repeat
  end repeat
end tell
return out
'''


def osascript(script, timeout=60):
    r = subprocess.run(["osascript", "-"], input=script, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "osascript failed")
    return r.stdout


def _as_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title, message):
    try:
        subprocess.run(["osascript", "-e", f"display notification {_as_str(message)} with title {_as_str(title)}"],
                       check=False, timeout=5)
    except Exception:
        pass


def snapshot():
    wins = []
    for line in osascript(SNAPSHOT_AS).splitlines():
        parts = line.split(SEP)
        if len(parts) != 9:
            continue
        app, bid, title, x, y, w, h, mini, idx = parts
        if bid in BUNDLE_SKIP:
            continue
        wins.append({
            "app": app, "bundle": bid, "title": title,
            "x": int(float(x)), "y": int(float(y)), "w": int(float(w)), "h": int(float(h)),
            "minimized": mini == "true", "index": int(idx),
        })
    return wins


# --- storage -----------------------------------------------------------------

def safe_name(name):
    name = re.sub(r"[/\\:]", "-", name.strip())
    return name


def path_for(name):
    return os.path.join(LAYOUT_DIR, safe_name(name) + ".json")


def load(name):
    with open(path_for(name), encoding="utf-8") as f:
        return json.load(f)


def saved_layouts():
    if not os.path.isdir(LAYOUT_DIR):
        return []
    out = []
    for fn in sorted(os.listdir(LAYOUT_DIR)):
        if fn.endswith(".json"):
            p = os.path.join(LAYOUT_DIR, fn)
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                out.append((fn[:-5], d, os.path.getmtime(p)))
            except Exception:
                continue
    return out


# --- commands ----------------------------------------------------------------

def cmd_save(name):
    wins = snapshot()
    if not wins:
        notify("Vindusoppsett", "Fant ingen vinduer å lagre")
        return 1
    os.makedirs(LAYOUT_DIR, exist_ok=True)
    data = {"name": name, "saved": time.strftime("%Y-%m-%d %H:%M"), "windows": wins}
    with open(path_for(name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    apps = sorted({w["app"] for w in wins})
    notify(f"Lagret «{name}»", f"{len(wins)} vinduer · {', '.join(apps)}")
    return 0


def _match(saved, current):
    """Pair saved windows with current windows of the same app. Returns [(saved, current)]."""
    pairs = []
    by_app = {}
    for c in current:
        by_app.setdefault(c["app"], []).append(c)
    for app, saved_wins in _group(saved).items():
        pool = list(by_app.get(app, []))
        # 1) exact title
        for s in saved_wins:
            for c in pool:
                if c["title"] == s["title"]:
                    pairs.append((s, c)); pool.remove(c); s["_done"] = True; break
        # 2) prefix / substring (longest common start, at least 8 chars)
        for s in [s for s in saved_wins if not s.get("_done")]:
            best, best_len = None, 0
            for c in pool:
                n = _common_prefix(s["title"], c["title"])
                if n >= 8 and n > best_len:
                    best, best_len = c, n
            if best:
                pairs.append((s, best)); pool.remove(best); s["_done"] = True
        # 3) order among what is left
        for s in [s for s in saved_wins if not s.get("_done")]:
            if pool:
                pairs.append((s, pool.pop(0))); s["_done"] = True
    return pairs


def _group(wins):
    g = {}
    for w in wins:
        g.setdefault(w["app"], []).append(dict(w))
    return g


def _common_prefix(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _launch_missing(saved, current):
    running = {c["app"] for c in current}
    launched = []
    for app, bid in sorted({(w["app"], w["bundle"]) for w in saved}):
        if app in running:
            continue
        cmd = ["open", "-g", "-b", bid] if bid else ["open", "-g", "-a", app]
        if subprocess.run(cmd, capture_output=True).returncode == 0:
            launched.append(app)
    if launched:
        time.sleep(3)
    return launched


def cmd_apply(name):
    try:
        data = load(name)
    except FileNotFoundError:
        notify("Vindusoppsett", f"Fant ikke oppsettet «{name}»")
        return 1
    saved = data["windows"]
    current = snapshot()
    if LAUNCH_MISSING:
        if _launch_missing(saved, current):
            current = snapshot()
    pairs = _match(saved, current)

    # One AppleScript for everything: set position, then size, twice (some
    # apps clamp the first attempt when the window is on another display).
    lines = ['tell application "System Events"']
    for s, c in pairs:
        ref = f'window {c["index"]} of application process {_as_str(c["app"])}'
        lines.append("try")
        if c["minimized"] and not s["minimized"]:
            lines.append(f'set value of attribute "AXMinimized" of {ref} to false')
        if s["minimized"]:
            lines.append(f'set value of attribute "AXMinimized" of {ref} to true')
        else:
            for _ in range(2):
                lines.append(f'set position of {ref} to {{{s["x"]}, {s["y"]}}}')
                lines.append(f'set size of {ref} to {{{s["w"]}, {s["h"]}}}')
        lines.append("end try")
    lines.append("end tell")
    osascript("\n".join(lines), timeout=120)

    missing = sorted({s["app"] for s in saved if not s.get("_done")})
    msg = f"{len(pairs)} av {len(saved)} vinduer plassert"
    if missing:
        msg += f" · mangler: {', '.join(missing)}"
    notify(f"Oppsett «{name}»", msg)
    return 0


def cmd_delete(name):
    try:
        os.remove(path_for(name))
        notify("Vindusoppsett", f"Slettet «{name}»")
    except FileNotFoundError:
        notify("Vindusoppsett", f"Fant ikke «{name}»")
    return 0


def cmd_list(query):
    q = query.strip()
    items = []
    m = re.match(r"^(?:lagre|save)\s+(.+)$", q, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        exists = os.path.exists(path_for(name))
        items.append({
            "title": f"Lagre nåværende vinduer som «{name}»",
            "subtitle": "Overskriver eksisterende oppsett" if exists else "Nytt oppsett fra vinduene slik de står nå",
            "arg": name, "variables": {"action": "save"}, "icon": {"path": "icon.png"},
        })
    else:
        for name, d, mtime in saved_layouts():
            if q and q.lower() not in name.lower():
                continue
            wins = d.get("windows", [])
            apps = []
            for w in wins:
                if w["app"] not in apps:
                    apps.append(w["app"])
            items.append({
                "uid": f"layout-{name}", "title": name,
                "subtitle": f"{len(wins)} vinduer · {', '.join(apps[:6])}{' …' if len(apps) > 6 else ''} · lagret {d.get('saved', '')}",
                "arg": name, "variables": {"action": "apply"},
                "mods": {
                    "cmd": {"subtitle": f"Overskriv «{name}» med vinduene slik de står nå", "variables": {"action": "save"}},
                    "alt": {"subtitle": f"Slett «{name}»", "variables": {"action": "delete"}},
                },
                "icon": {"path": "icon.png"},
            })
        if not items:
            items.append({
                "title": f"Lagre nåværende vinduer som «{q}»" if q else "Ingen oppsett lagret ennå",
                "subtitle": "Enter lagrer" if q else "Skriv «rydd lagre <navn>» for å lagre vinduene slik de står nå",
                "arg": q, "valid": bool(q), "variables": {"action": "save"}, "icon": {"path": "icon.png"},
            })
    print(json.dumps({"items": items}, ensure_ascii=False))
    return 0


def main(argv):
    if len(argv) < 2:
        print("usage: layout.py list|save|apply|delete <arg>", file=sys.stderr)
        return 2
    cmd, arg = argv[1], " ".join(argv[2:])
    if cmd == "list":
        return cmd_list(arg)
    if not arg.strip():
        notify("Vindusoppsett", "Mangler navn på oppsett")
        return 1
    return {"save": cmd_save, "apply": cmd_apply, "delete": cmd_delete}[cmd](arg.strip())


if __name__ == "__main__":
    sys.exit(main(sys.argv))
