#!/usr/bin/env python3
"""Bytt macOS mellom lys og mørk modus via System Events.

Bruk: appearance.py light|dark|toggle|auto

light/dark/toggle slår samtidig av macOS sitt «Auto»-utseende, ellers
tilbakestiller macOS valget ved neste vekking/opplåsing. `auto` slår det
på igjen.
"""
import subprocess
import sys

AUTO_KEY = "AppleInterfaceStyleSwitchesAutomatically"


def set_auto(enabled: bool) -> None:
    subprocess.run(
        ["/usr/bin/defaults", "write", "-g", AUTO_KEY, "-bool",
         "true" if enabled else "false"],
        check=False,
    )


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
    elif mode == "auto":
        set_auto(True)
        print("Automatisk utseende (følger tid på døgnet)")
        return
    else:
        print(f"Ukjent modus: {mode}")
        sys.exit(1)
    set_auto(False)
    osascript(f"set dark mode to {'true' if target else 'false'}")
    print("Mørk modus" if target else "Lys modus")


if __name__ == "__main__":
    main()
