#!/usr/bin/env python3
"""Script filter: viser lys/mørk-valg med gjeldende modus markert."""
import json
import subprocess
import sys


def is_dark():
    res = subprocess.run(
        ["/usr/bin/osascript", "-e",
         'tell application "System Events" to tell appearance preferences to get dark mode'],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        return None
    return res.stdout.strip() == "true"


def item(title, subtitle, arg, icon, uid):
    return {
        "uid": uid,
        "title": title,
        "subtitle": subtitle,
        "arg": arg,
        "icon": {"path": icon},
        "autocomplete": title,
    }


def main():
    query = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    dark = is_dark()
    items = []

    if dark is None:
        items.append({
            "title": "Får ikke lest utseende-innstillingen",
            "subtitle": "Gi Alfred tilgang til System Events under Personvern og sikkerhet → Automatisering",
            "arg": "toggle",
            "icon": {"path": "toggle.png"},
        })
    else:
        current = "mørk" if dark else "lys"
        items.append(item(
            "Bytt til lys modus" if dark else "Bytt til mørk modus",
            f"Nå: {current} modus",
            "toggle", "light.png" if dark else "dark.png", "toggle",
        ))
        items.append(item(
            "Lys modus",
            "Aktiv nå" if not dark else "Bytt til lyst utseende",
            "light", "light.png", "light",
        ))
        items.append(item(
            "Mørk modus",
            "Aktiv nå" if dark else "Bytt til mørkt utseende",
            "dark", "dark.png", "dark",
        ))

    if query:
        def match(it):
            hay = (it["title"] + " " + it["subtitle"] + " " + it["arg"]).lower()
            return all(w in hay for w in query.split())
        items = [it for it in items if match(it)] or items

    json.dump({"items": items}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
