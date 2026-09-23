#!/usr/bin/env python3
"""Alfred script filter: search Magic: The Gathering cards via the Scryfall API.

Keyword: mtg
Enter opens the card's Scryfall page (image, price, oracle text, mechanics).
Cmd+Enter drills into every printing/artwork of that exact card (mtg_prints.py).
Cmd+C copies the oracle text. Cmd+L (Large Type) shows name/cost/type/text/
keywords/price inline. Cmd+Y quicklooks the card image at full resolution
(the PNG render, not the smaller default preview size) — Alfred's docs say
Shift should also trigger it, but that didn't work on this machine.
"""
import json
import sys
import time
import urllib.error
import urllib.parse

from scryfall_common import (
    download_icon,
    fetch_json,
    http_error_item,
    info_item,
    mana_cost,
    oracle_text,
    original_image,
    price_text,
    wishlist_variables,
)

API = "https://api.scryfall.com/cards/search"
MIN_QUERY_LEN = 3
MAX_RESULTS = 12


def build_item(card):
    name = card.get("name", "?")
    type_line = card.get("type_line", "")
    cost = mana_cost(card)
    price = price_text(card)
    set_name = card.get("set_name", "")
    text = oracle_text(card)
    keywords = ", ".join(card.get("keywords") or [])

    subtitle = "  ·  ".join(p for p in [cost, type_line, price, set_name] if p)

    large_text = f"{name}\n{cost}\n{type_line}\n\n{text}"
    if keywords:
        large_text += f"\n\nMekanikker: {keywords}"
    large_text += f"\n\nPris: {price}  ·  {set_name}"

    variables = wishlist_variables(card)
    oracle_id = variables["oracle_id"]

    item = {
        "uid": card.get("id"),
        "title": name,
        "subtitle": subtitle,
        "arg": oracle_id,
        # Workflow variables (not the positional arg) are what actually
        # survives a modifier-gated connection into a chained script/action's
        # environment — confirmed via debug logging. mtg_prints.py reads
        # oracle_id from the environment, the default Enter action reads
        # scryfall_uri, and Shift+Enter's wishlist action reads the rest.
        "variables": variables,
        "autocomplete": name,
        "valid": True,
        "text": {"copy": text, "largetype": large_text},
    }
    img = original_image(card)
    if img:
        item["quicklookurl"] = img
    icon_path = download_icon(card)
    if icon_path:
        item["icon"] = {"path": icon_path}

    item["mods"] = {
        "shift": {
            "subtitle": "⇧ ↵  Legg til i MTG-ønskeliste",
            "valid": True,
        },
    }
    if oracle_id:
        item["mods"]["cmd"] = {
            "subtitle": "⌘ ↵  Bla gjennom alle versjoner/artverk av dette kortet",
            "valid": True,
        }
    return item


def main():
    query = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if len(query) < MIN_QUERY_LEN:
        print(json.dumps({"items": [info_item("Skriv minst 3 bokstaver av kortnavnet", "Søker på Scryfall")]}))
        return

    # Debounce: Alfred kills this process and reruns the script on every
    # keystroke. Sleeping briefly before hitting the network means fast
    # typing only ever lets the *last* keystroke's run reach Scryfall,
    # instead of firing one request per letter and tripping its rate limit.
    time.sleep(0.3)

    url = f"{API}?q={urllib.parse.quote(query)}&unique=cards&order=name"
    try:
        data = fetch_json(url)
    except urllib.error.HTTPError as e:
        print(json.dumps({"items": [http_error_item(e, "Ingen treff", f'Fant ingen kort som matcher "{query}"')]}))
        return
    except Exception as e:
        print(json.dumps({"items": [info_item("Nettverksfeil", str(e))]}))
        return

    cards = (data.get("data") or [])[:MAX_RESULTS]
    items = [build_item(c) for c in cards] or [info_item("Ingen treff")]
    print(json.dumps({"items": items}))


if __name__ == "__main__":
    main()
