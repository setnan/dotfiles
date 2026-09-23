#!/usr/bin/env python3
"""Alfred script action: append the selected MTG card to the Obsidian wishlist note.

Triggered via Shift+Enter from mtg_search.py or mtg_prints.py. Reads card
details from workflow variables (set on the selected item upstream — this
is what actually survives a modifier-gated connection, not the positional
arg) and appends a checklist line to the vault note below, skipping
duplicates by Scryfall URL. Tick the checkbox off in Obsidian once bought.
"""
import datetime
import os
import re
import subprocess

NOTE_PATH = (
    "/Users/simonetnan/Documents/Koderiet/RSA/md/SE-v2/Efforts/Areas/"
    "Privilege/MTG/MTG – Ønskeliste.md"
)

TEMPLATE = """---
up: "[[MTG – Draft og The Hobbit (HOB)]]"
created: {created}
modified: {modified}
tags:
  - mtg
  - ønskeliste
---

# MTG – Ønskeliste

Kort jeg vurderer å kjøpe. Kryss av når kjøpt.

"""


def _as_quote(s):
    """Quote a string as an AppleScript string literal (double quotes, not repr())."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title, message):
    try:
        script = f"display notification {_as_quote(message)} with title {_as_quote(title)}"
        subprocess.run(["osascript", "-e", script], check=False, timeout=5)
    except Exception:
        pass


def now_stamp():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")


def today():
    return datetime.date.today().isoformat()


def load_note():
    if not os.path.exists(NOTE_PATH):
        return TEMPLATE.format(created=today(), modified=now_stamp())
    with open(NOTE_PATH, encoding="utf-8") as f:
        return f.read()


def set_modified(content, stamp):
    if re.search(r"(?m)^modified:.*$", content):
        return re.sub(r"(?m)^modified:.*$", f"modified: {stamp}", content, count=1)
    # Note existed before this script ever touched it and has no modified
    # field yet — add one right after created: inside the frontmatter block.
    return re.sub(r"(?m)^(created:.*)$", rf"\1\nmodified: {stamp}", content, count=1)


def main():
    name = (os.environ.get("name") or "").strip()
    scryfall_uri = (os.environ.get("scryfall_uri") or "").strip()

    if not name or not scryfall_uri:
        notify("MTG Ønskeliste", "Mangler kortdata — prøv igjen fra søket")
        return

    content = load_note()

    if scryfall_uri in content:
        notify("MTG Ønskeliste", f'"{name}" står allerede på listen')
        return

    set_name = os.environ.get("set_name", "")
    set_code = os.environ.get("set_code", "")
    collector_number = os.environ.get("collector_number", "")
    price = os.environ.get("price_usd", "")

    set_bit = " ".join(
        p
        for p in [
            set_name,
            f"({set_code})" if set_code else "",
            f"#{collector_number}" if collector_number else "",
        ]
        if p
    )

    bits = [f"**{name}**"]
    if set_bit:
        bits.append(set_bit)
    if price:
        bits.append(f"${price}")
    bits.append(f"[Scryfall]({scryfall_uri})")
    bits.append(f"lagt til {today()}")

    line = "- [ ] " + "  ·  ".join(bits) + "\n"

    content = set_modified(content, now_stamp())
    if not content.endswith("\n"):
        content += "\n"
    content += line

    os.makedirs(os.path.dirname(NOTE_PATH), exist_ok=True)
    with open(NOTE_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    notify("MTG Ønskeliste", f'"{name}" lagt til')


if __name__ == "__main__":
    main()
