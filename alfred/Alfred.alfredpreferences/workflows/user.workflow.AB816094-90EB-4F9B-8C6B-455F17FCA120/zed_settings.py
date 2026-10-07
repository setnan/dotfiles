#!/usr/bin/env python3
"""Endre innstillinger i Zed sin settings.json fra Alfred.

Bruk:
  zed_settings.py list [query]     script filter-JSON
  zed_settings.py copilot on|off|toggle

settings.json er JSONC (kommentarer, avsluttende komma), så verdiene byttes
med en presis tekst-erstatning i stedet for å skrive hele filen på nytt.
Skriver til symlink-målet slik at symlinken til dotfiles beholdes.
"""
import json
import os
import re
import sys

SETTINGS = os.path.realpath(os.path.expanduser("~/.config/zed/settings.json"))

BLOCK_RE = re.compile(r'"edit_predictions"\s*:\s*\{')
PROVIDER_RE = re.compile(r'("provider"\s*:\s*")([^"]*)(")')


def read():
    with open(SETTINGS, encoding="utf-8") as f:
        return f.read()


def write(text):
    # Skriv på plass (ikke rename) så filrettigheter og symlink beholdes
    with open(SETTINGS, "w", encoding="utf-8") as f:
        f.write(text)


def block_span(text):
    """Returner (start, slutt) for innholdet i edit_predictions-blokken."""
    m = BLOCK_RE.search(text)
    if not m:
        return None
    depth, i = 1, m.end()
    in_str = False
    while i < len(text) and depth:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return m.end(), i - 1


def get_provider(text):
    span = block_span(text)
    if not span:
        return None
    m = PROVIDER_RE.search(text, *span)
    return m.group(2) if m else None


def set_provider(text, value):
    span = block_span(text)
    if span:
        m = PROVIDER_RE.search(text, *span)
        if m:
            return text[:m.start(2)] + value + text[m.end(2):]
        # Blokken finnes, men uten provider: legg den først i blokken
        start = span[0]
        return text[:start] + f'\n    "provider": "{value}",' + text[start:]
    # Ingen blokk: legg den til rett etter første {
    brace = text.index("{")
    return (text[:brace + 1]
            + f'\n  "edit_predictions": {{\n    "provider": "{value}"\n  }},'
            + text[brace + 1:])


def copilot(action):
    text = read()
    on = get_provider(text) == "copilot"
    target = {"on": True, "off": False, "toggle": not on}.get(action)
    if target is None:
        print(f"Ukjent handling: {action}")
        sys.exit(1)
    if target != on:
        write(set_provider(text, "copilot" if target else "none"))
    print("Copilot autocomplete på" if target else "Copilot autocomplete av")


def list_items(query):
    try:
        provider = get_provider(read())
    except OSError as e:
        items = [{
            "title": "Fant ikke Zed sin settings.json",
            "subtitle": str(e),
            "valid": False,
            "icon": {"path": "icon.png"},
        }]
    else:
        on = provider == "copilot"
        now = "på" if on else f"av (provider: {provider or 'ikke satt'})"
        items = [{
            "uid": "copilot",
            "title": f"Copilot autocomplete: slå {'av' if on else 'på'}",
            "subtitle": f"Nå: {now}",
            "arg": "copilot toggle",
            "autocomplete": "copilot",
            "match": "copilot autocomplete edit predictions",
            "icon": {"path": "icon.png"},
        }]

    if query:
        words = query.lower().split()
        hit = [it for it in items
               if all(w in (it["title"] + " " + it.get("match", "")).lower() for w in words)]
        items = hit or items

    json.dump({"items": items}, sys.stdout, ensure_ascii=False)


def main():
    # Alfred sender arg som én streng («copilot toggle»)
    args = " ".join(sys.argv[1:]).split()
    if not args or args[0] == "list":
        list_items(" ".join(args[1:]).strip())
    elif args[0] == "copilot":
        copilot(args[1] if len(args) > 1 else "toggle")
    else:
        print(f"Ukjent kommando: {' '.join(args)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
