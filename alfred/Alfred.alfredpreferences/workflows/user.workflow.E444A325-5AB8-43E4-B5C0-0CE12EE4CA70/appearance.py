#!/usr/bin/env python3
"""Bytt macOS mellom lys og mørk modus via System Events.

Bruk: appearance.py light|dark|toggle
"""
import subprocess
import sys


def osascript(expr: str) -> str:
    res = subprocess.run(
        ["/usr/bin/osascript", "-e",
         f'tell application "System Events" to tell appearance preferences to {expr}'],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        msg = res.stderr.strip() or "ukjent feil"
        if "1743" in msg or "not allowed" in msg.lower():
            msg = ("Alfred mangler tilgang til System Events. Gi tilgang under "
                   "Systeminnstillinger → Personvern og sikkerhet → Automatisering.")
        print(msg)
        sys.exit(1)
    return res.stdout.strip()


def is_dark() -> bool:
    return osascript("get dark mode") == "true"


def main() -> None:
    mode = (sys.argv[1] if len(sys.argv) > 1 else "toggle").strip().lower()
    if mode == "toggle":
        target = not is_dark()
    elif mode in ("dark", "mørk", "mork"):
        target = True
    elif mode in ("light", "lys"):
        target = False
    else:
        print(f"Ukjent modus: {mode}")
        sys.exit(1)
    osascript(f"set dark mode to {'true' if target else 'false'}")
    print("Mørk modus" if target else "Lys modus")


if __name__ == "__main__":
    main()
