#!/usr/bin/env python3
"""Alfred script filter: search contacts by name, phone, e-mail or organisation."""
import json
import sys

from contacts_common import CONTACTS_APP, digits, display_name, load_contacts

MAX_ITEMS = 40


def score(c, words):
    name = display_name(c).lower()
    first, last = c["first"].lower(), c["last"].lower()
    hay_text = " ".join([name, c["nick"], c["org"], c["job"]] +
                        [e for e, _ in c["emails"]]).lower()
    hay_digits = " ".join(digits(p) for p, _ in c["phones"])
    total = 0
    for w in words:
        wd = digits(w)
        if wd and len(wd) >= 3 and wd in hay_digits:
            total += 3
        elif w in hay_text:
            if first.startswith(w) or last.startswith(w) or name.startswith(w):
                total += 4
            elif any(part.startswith(w) for part in name.split()):
                total += 3
            else:
                total += 1
        else:
            return 0
    return total


def item_for(c):
    name = display_name(c)
    phone = c["phones"][0][0] if c["phones"] else ""
    email = c["emails"][0][0] if c["emails"] else ""
    bits = []
    if phone:
        bits.append(phone + (f" (+{len(c['phones']) - 1})" if len(c["phones"]) > 1 else ""))
    if email:
        bits.append(email)
    if c["org"] and c["org"] != name:
        bits.append(c["org"])
    return {
        "title": name,
        "subtitle": " · ".join(bits) or "Ingen telefon eller e-post registrert",
        "arg": c["uid"],
        "icon": {"type": "fileicon", "path": CONTACTS_APP},
        "variables": {"uid": c["uid"], "name": name, "phone": phone, "email": email},
        "text": {"copy": phone or email or name, "largetype": "\n".join([name] + bits)},
        "mods": {"cmd": {"subtitle": f"Åpne {name} i Kontakter"}},
    }


def main():
    query = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if not query:
        json.dump({"items": [{"title": "Søk i kontakter",
                              "subtitle": "Skriv navn, telefonnummer, e-post eller firma",
                              "valid": False,
                              "icon": {"type": "fileicon", "path": CONTACTS_APP}}]}, sys.stdout)
        return
    words = query.split()
    scored = [(score(c, words), c) for c in load_contacts()]
    scored = [(s, c) for s, c in scored if s > 0]
    scored.sort(key=lambda sc: (-sc[0], display_name(sc[1]).lower()))
    items = [item_for(c) for _, c in scored[:MAX_ITEMS]]
    if not items:
        items = [{"title": "Ingen kontakter matcher", "subtitle": query, "valid": False,
                  "icon": {"type": "fileicon", "path": CONTACTS_APP}}]
    json.dump({"items": items}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
