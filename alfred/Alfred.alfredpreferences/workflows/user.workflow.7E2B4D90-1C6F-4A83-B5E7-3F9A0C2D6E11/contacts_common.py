"""Shared helpers for the Kontakter Alfred workflow: read macOS Contacts databases directly."""
import glob
import os
import re
import sqlite3

AB_DIR = os.path.expanduser("~/Library/Application Support/AddressBook")
CONTACTS_APP = "/System/Applications/Contacts.app"

LABELS = {
    "_$!<Mobile>!$_": "Mobil", "_$!<Home>!$_": "Hjem", "_$!<Work>!$_": "Jobb",
    "_$!<Main>!$_": "Hoved", "_$!<Other>!$_": "Annet", "_$!<iPhone>!$_": "iPhone",
    "_$!<HomeFAX>!$_": "Faks hjem", "_$!<WorkFAX>!$_": "Faks jobb", "_$!<Pager>!$_": "Personsøker",
    "_$!<School>!$_": "Skole", "_$!<HomePage>!$_": "Hjemmeside",
}


def label(raw):
    if not raw:
        return ""
    return LABELS.get(raw, raw.replace("_$!<", "").replace(">!$_", ""))


def databases():
    paths = glob.glob(os.path.join(AB_DIR, "Sources", "*", "AddressBook-v22.abcddb"))
    root = os.path.join(AB_DIR, "AddressBook-v22.abcddb")
    if os.path.exists(root):
        paths.append(root)
    return paths


def _connect(path):
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def _contact_entity(cur):
    row = cur.execute("SELECT Z_ENT FROM Z_PRIMARYKEY WHERE Z_NAME = 'ABCDContact'").fetchone()
    return row[0] if row else None


def load_contacts():
    """Return a list of dicts: uid, first, last, org, nick, job, phones, emails, addresses, urls."""
    contacts = {}
    for path in databases():
        try:
            con = _connect(path)
            cur = con.cursor()
            ent = _contact_entity(cur)
            if ent is None:
                continue
            rows = cur.execute(
                "SELECT Z_PK, ZUNIQUEID, ZFIRSTNAME, ZLASTNAME, ZMIDDLENAME, ZNICKNAME, ZORGANIZATION, ZJOBTITLE "
                "FROM ZABCDRECORD WHERE Z_ENT = ?", (ent,)).fetchall()
            by_pk = {}
            for pk, uid, first, last, middle, nick, org, job in rows:
                if not uid:
                    continue
                c = {"uid": uid, "first": first or "", "last": last or "", "middle": middle or "",
                     "nick": nick or "", "org": org or "", "job": job or "",
                     "phones": [], "emails": [], "addresses": [], "urls": []}
                by_pk[pk] = c
                contacts[uid] = c
            for owner, number, lab in cur.execute(
                    "SELECT ZOWNER, ZFULLNUMBER, ZLABEL FROM ZABCDPHONENUMBER ORDER BY Z_PK"):
                if owner in by_pk and number:
                    by_pk[owner]["phones"].append((number.strip(), label(lab)))
            for owner, addr, lab in cur.execute(
                    "SELECT ZOWNER, ZADDRESS, ZLABEL FROM ZABCDEMAILADDRESS ORDER BY Z_PK"):
                if owner in by_pk and addr:
                    by_pk[owner]["emails"].append((addr.strip(), label(lab)))
            for owner, street, zipc, city, country, lab in cur.execute(
                    "SELECT ZOWNER, ZSTREET, ZZIPCODE, ZCITY, ZCOUNTRYNAME, ZLABEL FROM ZABCDPOSTALADDRESS ORDER BY Z_PK"):
                if owner in by_pk:
                    parts = [p.strip() for p in (street or "", " ".join(filter(None, [zipc, city])), country or "") if p and p.strip()]
                    if parts:
                        by_pk[owner]["addresses"].append((", ".join(p.replace("\n", ", ") for p in parts), label(lab)))
            try:
                for owner, url, lab in cur.execute(
                        "SELECT ZOWNER, ZURL, ZLABEL FROM ZABCDURLADDRESS ORDER BY Z_PK"):
                    if owner in by_pk and url:
                        by_pk[owner]["urls"].append((url.strip(), label(lab)))
            except sqlite3.Error:
                pass
            con.close()
        except sqlite3.Error:
            continue
    return list(contacts.values())


def display_name(c):
    name = " ".join(p for p in (c["first"], c["middle"], c["last"]) if p).strip()
    return name or c["org"] or c["nick"] or "(uten navn)"


def digits(s):
    return re.sub(r"\D", "", s or "")


def find_contact(uid):
    for c in load_contacts():
        if c["uid"] == uid:
            return c
    return None
