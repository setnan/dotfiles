#!/usr/bin/env python3
"""Alfred: hold Macen våken med Lungo, og trygg lukking av lokket med Clamshell (begge Setapp).

  koffein.py list [filter]   Script Filter: tre valg med nåværende tilstand i undertekst
  koffein.py awake           Lungo på
  koffein.py lid             Lungo på + Clamshell armert for lukking (auto re-arm)
  koffein.py off             Lungo av + Clamshell avarmert

Ingen av appene har et URL-skjema som virker (testet 2026-10-22), så begge styres via
System Events på menylinje-ikonet: Lungo togglet med venstreklikk (krever «Activate on
left-click» i Lungo), Clamshell via menyvalgene «Arm for Next Close» og «Cancel Automatic
Re-arm». Tilstand leses fra `pmset -g assertions` (Lungo) og ikonets description (Clamshell).
Alfred trenger tilgang under Tilgjengelighet.
"""
import json
import subprocess
import sys

LUNGO, CLAM = "Lungo", "Clamshell"


def osa(script):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=20)
    return r.stdout.strip()


def running(app):
    return subprocess.run(["pgrep", "-x", app], capture_output=True).returncode == 0


def launch(app):
    subprocess.run(["open", "-g", "-a", app], check=False)
    for _ in range(20):
        if running(app) and osa(f'tell application "System Events" to tell process "{app}" to count menu bar items of menu bar 2') not in ("", "0"):
            return True
        subprocess.run(["sleep", "0.5"])
    return running(app)


def lungo_on():
    out = subprocess.run(["pmset", "-g", "assertions"], capture_output=True, text=True).stdout
    return "(Lungo)" in out


def lungo_click():
    osa(f'tell application "System Events" to tell process "{LUNGO}" to click menu bar item 1 of menu bar 2')


def clam_desc():
    return osa(f'tell application "System Events" to tell process "{CLAM}" to get description of menu bar item 1 of menu bar 2')


def clam_armed():
    return "not armed" not in clam_desc().lower()


def clam_menu(item):
    """Åpne Clamshell-menyen og klikk `item`; Escape hvis valget mangler."""
    osa(f'''
    tell application "System Events" to tell process "{CLAM}"
        set mi to menu bar item 1 of menu bar 2
        click mi
        delay 0.6
        try
            click menu item "{item}" of menu 1 of mi
        on error
            key code 53
        end try
    end tell''')


def set_lungo(want):
    if not launch(LUNGO):
        return "Lungo starter ikke"
    if lungo_on() != want:
        lungo_click()
        subprocess.run(["sleep", "1"])
    return None if lungo_on() == want else "Lungo byttet ikke tilstand"


def set_clam(want):
    if not launch(CLAM):
        return "Clamshell starter ikke"
    if clam_armed() != want:
        clam_menu("Arm for Next Close" if want else "Cancel Automatic Re-arm")
        subprocess.run(["sleep", "1.5"])
    return None if clam_armed() == want else "Clamshell byttet ikke tilstand"


def notify(title, msg):
    q = lambda s: '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    osa(f"display notification {q(msg)} with title {q(title)}")


def status_line():
    l = "Lungo: våken" if (running(LUNGO) and lungo_on()) else "Lungo: av"
    if running(CLAM):
        d = clam_desc()
        c = "Clamshell: armert" if "not armed" not in d.lower() else "Clamshell: av"
        if "paused" in d.lower():
            c += " (pauset, ekstern skjerm)"
    else:
        c = "Clamshell: kjører ikke"
    return f"{l} · {c}"


def list_items():
    st = status_line()
    items = [
        {"title": "Hold Macen våken", "subtitle": f"Lungo på · nå: {st}", "arg": "awake",
         "match": "våken vaken awake koffein caffein"},
        {"title": "Hold våken og trygg lukking av lokk", "subtitle": f"Lungo på + Clamshell armert · nå: {st}",
         "arg": "lid", "match": "lokk lid clamshell lukk begge"},
        {"title": "Av: la Macen sove igjen", "subtitle": f"Lungo av + Clamshell avarmert · nå: {st}", "arg": "off",
         "match": "av off sov stopp"},
    ]
    print(json.dumps({"items": items}, ensure_ascii=False))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "list"
    if mode == "list":
        return list_items()
    errors = []
    if mode == "awake":
        errors += [e for e in (set_lungo(True),) if e]
        title = "Koffein: våken"
    elif mode == "lid":
        errors += [e for e in (set_lungo(True), set_clam(True)) if e]
        title = "Koffein: våken + lokk"
    elif mode == "off":
        errors += [e for e in (set_lungo(False), set_clam(False)) if e]
        title = "Koffein: av"
    else:
        print("Bruk: koffein.py list|awake|lid|off"); return 1
    notify(title, " · ".join(errors) if errors else status_line())
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main() or 0)
