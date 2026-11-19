#!/usr/bin/env python3
"""Alfred script filter: list phone numbers, e-mails and addresses for one contact (uid from env)."""
import json
import os
import sys
import urllib.parse

from contacts_common import CONTACTS_APP, digits, display_name, find_contact


def main():
    uid = os.environ.get("uid", "")
    query = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    c = find_contact(uid) if uid else None
    if not c:
        json.dump({"items": [{"title": "Fant ikke kontakten", "valid": False}]}, sys.stdout)
        return
    name = display_name(c)
    items = []

    def add(title, sub, value, url):
        items.append({
            "title": title, "subtitle": sub, "arg": value,
            "icon": {"type": "fileicon", "path": CONTACTS_APP},
            "variables": {"uid": uid, "name": name, "value": value, "url": url},
            "text": {"copy": value, "largetype": f"{name}\n{value}"},
            "mods": {"cmd": {"subtitle": sub.split(" · ")[-1]},
                     "alt": {"subtitle": f"Åpne {name} i Kontakter"}},
        })

    for number, lab in c["phones"]:
        add(number, f"{lab or 'Telefon'} · Enter kopierer · Cmd ringer (FaceTime)",
            number, "tel:" + digits(number) if not number.startswith("+") else "tel:+" + digits(number))
    for addr, lab in c["emails"]:
        add(addr, f"{lab or 'E-post'} · Enter kopierer · Cmd skriver ny e-post", addr, "mailto:" + addr)
    for addr, lab in c["addresses"]:
        add(addr, f"{lab or 'Adresse'} · Enter kopierer · Cmd åpner i Kart",
            addr, "https://maps.apple.com/?q=" + urllib.parse.quote(addr))
    for url, lab in c["urls"]:
        link = url if "://" in url else "https://" + url
        add(url, f"{lab or 'Nettside'} · Enter kopierer · Cmd åpner", url, link)
    if c["org"] and c["org"] != name:
        add(c["org"], "Firma · Enter kopierer", c["org"], "addressbook://" + uid)
    if not items:
        items.append({"title": name, "subtitle": "Ingen felter registrert · Alt+Enter åpner i Kontakter",
                      "arg": name, "variables": {"uid": uid, "name": name, "value": name, "url": "addressbook://" + uid},
                      "icon": {"type": "fileicon", "path": CONTACTS_APP}})
    if query:
        items = [i for i in items if query in (i["title"] + " " + i["subtitle"]).lower()] or items
    json.dump({"items": items}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
