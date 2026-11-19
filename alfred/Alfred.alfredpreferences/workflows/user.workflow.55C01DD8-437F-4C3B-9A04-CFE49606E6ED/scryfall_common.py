"""Shared Scryfall API helpers for the MTG Card Search Alfred workflow."""
import json
import os
import urllib.error
import urllib.request

HEADERS = {
    "User-Agent": "AlfredMTGSearch/1.0 (personal Alfred workflow)",
    "Accept": "application/json",
}


def cache_dir():
    d = os.environ.get("alfred_workflow_cache") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".cache"
    )
    os.makedirs(d, exist_ok=True)
    return d


def fetch_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=6) as r:
        return json.loads(r.read().decode("utf-8"))


def face_image_uris(card):
    return card.get("image_uris") or (card.get("card_faces") or [{}])[0].get("image_uris") or {}


def download_icon(card, key=None):
    """Cache the small artwork for this exact printing as a local icon file.

    `key` lets callers disambiguate multiple printings of the same card
    (which share the same Scryfall card id would not apply here, since each
    printing has its own id) — by default the printing's own id is used.
    """
    url = face_image_uris(card).get("small")
    if not url:
        return None
    path = os.path.join(cache_dir(), f"{key or card.get('id')}.png")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=6) as r, open(path, "wb") as f:
            f.write(r.read())
        return path
    except Exception:
        return None


def large_image(card):
    uris = face_image_uris(card)
    return uris.get("normal") or uris.get("large")


def original_image(card):
    """Highest-resolution render Scryfall has for this printing (~745×1040 PNG)."""
    uris = face_image_uris(card)
    return uris.get("png") or uris.get("large") or uris.get("normal")


def oracle_text(card):
    if card.get("oracle_text"):
        return card["oracle_text"]
    faces = card.get("card_faces") or []
    return "\n//\n".join(f.get("oracle_text", "") for f in faces if f.get("oracle_text"))


def mana_cost(card):
    if card.get("mana_cost"):
        return card["mana_cost"]
    faces = card.get("card_faces") or []
    return " // ".join(f.get("mana_cost", "") for f in faces if f.get("mana_cost"))


def price_text(card):
    p = card.get("prices") or {}
    if p.get("usd"):
        return f"${p['usd']}"
    if p.get("usd_foil"):
        return f"${p['usd_foil']} (foil)"
    return "pris ukjent"


def info_item(title, subtitle=""):
    return {"title": title, "subtitle": subtitle, "valid": False}


def wishlist_variables(card):
    """Workflow variables carrying one printing's data to mtg_wishlist.py.

    Alfred exposes an item's "variables" as environment variables to any
    downstream script/action reached via a connection, including a
    modifier-gated one (e.g. Shift+Enter) — this is what actually survives
    the chain, unlike the positional arg.
    """
    p = card.get("prices") or {}
    price = p.get("usd") or p.get("usd_foil") or ""
    return {
        "name": card.get("name", ""),
        "set_name": card.get("set_name", ""),
        "set_code": (card.get("set") or "").upper(),
        "collector_number": card.get("collector_number", ""),
        "price_usd": price,
        "scryfall_uri": card.get("scryfall_uri", ""),
        "oracle_id": card.get("oracle_id") or "",
    }


def http_error_item(e, not_found_title="Ingen treff", not_found_subtitle=""):
    if e.code == 404:
        return info_item(not_found_title, not_found_subtitle)
    if e.code == 429:
        return info_item("For mange forespørsler til Scryfall", "Vent et par sekunder og prøv igjen")
    return info_item("Scryfall-feil", str(e))
