#!/usr/bin/env python3
"""Alfred script filter: list every printing/artwork of one MTG card.

Chained from mtg_search.py via Cmd+Enter — receives the card's oracle_id
as the "oracle_id" workflow variable (set as an item variable upstream;
positional args don't survive a modifier-gated script filter chain the
same way) and lists each printing (different set, art, frame) as its own
row with its own artwork as the icon, so you can flip through versions
with the arrow keys and Quick Look (Cmd+Y) each one's actual art.
Enter opens that specific printing's Scryfall page. Shift+Enter adds that
exact printing to the MTG – Ønskeliste vault note (mtg_wishlist.py).
"""
import json
import os
import sys
import urllib.error

from scryfall_common import (
    download_icon,
    fetch_json,
    http_error_item,
    info_item,
    oracle_text,
    original_image,
    price_text,
    wishlist_variables,
)

API = "https://api.scryfall.com/cards/search"
MAX_RESULTS = 30


def build_item(card):
    name = card.get("name", "?")
    set_name = card.get("set_name", "")
    set_code = (card.get("set") or "").upper()
    released = card.get("released_at", "")[:4]
    price = price_text(card)
    collector = card.get("collector_number", "")
    frame_bits = []
    if card.get("promo"):
        frame_bits.append("promo")
    if card.get("full_art"):
        frame_bits.append("full art")
    if card.get("border_color") not in (None, "black"):
        frame_bits.append(f"{card['border_color']} border")
    frame = ", ".join(frame_bits)

    subtitle = "  ·  ".join(
        p for p in [f"{set_name} ({set_code})", released, f"#{collector}", price, frame] if p
    )

    text = oracle_text(card)
    large_text = f"{name}\n{set_name} ({set_code}), {released} — #{collector}\n\n{text}\n\nPris: {price}"

    item = {
        "uid": card.get("id"),
        "title": name,
        "subtitle": subtitle,
        "arg": card.get("scryfall_uri", ""),
        "variables": wishlist_variables(card),
        "valid": True,
        "text": {"copy": text, "largetype": large_text},
        "mods": {
            "shift": {
                "subtitle": "⇧ ↵  Legg til denne versjonen i MTG-ønskeliste",
                "valid": True,
            },
        },
    }
    img = original_image(card)
    if img:
        item["quicklookurl"] = img
    # Keyed by the printing's own id (each printing has a distinct id and
    # its own artwork), unlike mtg_search.py's per-card icon cache.
    icon_path = download_icon(card, key=card.get("id"))
    if icon_path:
        item["icon"] = {"path": icon_path}
    return item


def main():
    # oracle_id arrives as a workflow variable (set upstream in mtg_search.py's
    # item), not as $1 — argv is kept only as a fallback.
    oracle_id = (os.environ.get("oracle_id") or "").strip()
    if not oracle_id and len(sys.argv) > 1:
        oracle_id = sys.argv[1].strip()
    if not oracle_id:
        print(json.dumps({"items": [info_item("Mangler kort-id", "Kjør dette via mtg-søket, ikke direkte")]}))
        return

    url = f"{API}?q=oracleid%3A{oracle_id}&unique=prints&order=released&dir=asc"
    try:
        data = fetch_json(url)
    except urllib.error.HTTPError as e:
        print(json.dumps({"items": [http_error_item(e, "Ingen versjoner funnet")]}))
        return
    except Exception as e:
        print(json.dumps({"items": [info_item("Nettverksfeil", str(e))]}))
        return

    cards = (data.get("data") or [])[:MAX_RESULTS]
    items = [build_item(c) for c in cards] or [info_item("Ingen versjoner funnet")]
    print(json.dumps({"items": items}))


if __name__ == "__main__":
    main()
