"""Airthings-målinger i Alfred: `air` viser siste verdier fra Wave Plus.

Client ID og Client Secret ligger i macOS-nøkkelringen (tjeneste
airthings-api, kontoer client-id og client-secret), aldri i repoet.
Svar fra API-et mellomlagres i 5 minutter, sensoren måler uansett bare
hvert 5. minutt og API-et har kvote per time. Skyen er bare så fersk som
siste synk fra telefonen, så når bin/airthings-ble (launchd) har lest
sensoren over Bluetooth de siste 15 minuttene, brukes de tallene i stedet.
`air !` ber jobben lese med en gang.

    python3 airthings.py [filter]   Alfred-JSON («7», «uke», «1.10-15.10» gir luftrapport)
    python3 airthings.py --report [tidsrom]   bare rapportvalg (nøkkelordet luftrapport)
    python3 airthings.py --raw      rå API-svar (feilsøking)
"""

import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

TOKEN_URL = "https://accounts-api.airthings.com/v1/token"
API = "https://consumer-api.airthings.com/v1"
DASHBOARD = "https://dashboard.airthings.com/"
KEYCHAIN_SERVICE = "airthings-api"
CACHE_TTL = 300
BLE_MAX_AGE = 15 * 60  # bruk Bluetooth-tall fra bin/airthings-ble når de er ferskere enn dette
BLE_JOB = "dev.etnan.airthings-ble"

CACHE_DIR = os.environ.get("alfred_workflow_cache") or os.path.expanduser(
    "~/Library/Caches/com.runningwithcrayons.Alfred/Workflow Data/no.etnan.airthings")

# nøkkel: (navn, enhet, grenser) – grenser er [(maks, nivå)], siste gjelder resten
SENSORS = {
    "radon": ("Radon", "Bq/m³", [(100, 0), (150, 1), (None, 2)]),
    "co2": ("CO₂", "ppm", [(800, 0), (1000, 1), (None, 2)]),
    "voc": ("VOC", "ppb", [(250, 0), (2000, 1), (None, 2)]),
    "temp": ("Temperatur", "°C", None),
    "humidity": ("Luftfuktighet", "%", None),
    "pressure": ("Lufttrykk", "hPa", None),
    "pm25": ("PM2,5", "µg/m³", [(10, 0), (25, 1), (None, 2)]),
    "pm1": ("PM1", "µg/m³", [(10, 0), (25, 1), (None, 2)]),
    "battery": ("Batteri", "%", [(10, 2), (25, 1), (None, 0)]),
}

ALIASES = {
    "radonshorttermavg": "radon", "radonshortterm": "radon", "radon": "radon",
    "co2": "co2", "voc": "voc", "temp": "temp", "temperature": "temp",
    "humidity": "humidity", "hum": "humidity", "pressure": "pressure",
    "pm25": "pm25", "pm2.5": "pm25", "pm1": "pm1", "battery": "battery",
    "batterypercentage": "battery",
}

SEARCH = {"luft": None, "fukt": "humidity", "temperatur": "temp", "trykk": "pressure",
          "batteri": "battery", "co2": "co2", "radon": "radon", "voc": "voc", "pm": "pm25"}

LEVEL_TEXT = ["bra", "middels", "dårlig"]

# vises når Shift holdes inne
ABOUT = {
    "radon": "Radioaktiv gass fra grunnen – se på langtidssnittet",
    "co2": "Stiger når folk er i rommet – høyt gir tretthet og hodepine",
    "voc": "Gasser fra maling, møbler, matlaging og rengjøring",
    "temp": "Komfortabel innetemperatur er 18–25 °C",
    "humidity": "Under 30 % gir tørr luft, over 60 % øker faren for mugg",
    "pressure": "Fallende trykk betyr ofte dårligere vær",
    "pm25": "Svevestøv fra trafikk, vedfyring og matlaging",
    "pm1": "De minste partiklene i svevestøv",
}

# undertittel per måling og nivå (temperatur og lufttrykk har bare ett eller to nivåer)
HINTS = {
    "radon": ["Bra · under 100 Bq/m³", "Middels · 100–150 Bq/m³ – følg med over tid", "Høyt · over 150 Bq/m³ – vurder tiltak"],
    "co2": ["Bra · under 800 ppm", "Middels · 800–1 000 ppm – luft gjerne ut", "Dårlig · over 1 000 ppm – luft ut"],
    "voc": ["Bra · under 250 ppb", "Middels · 250–2 000 ppb – luft gjerne ut", "Høyt · over 2 000 ppb – luft ut"],
    "temp": ["Bra · 18–25 °C", "Utenfor 18–25 °C"],
    "humidity": ["Bra · 30–60 %", "Litt utenfor 30–60 %", "For tørt eller fuktig · bør være 30–60 %"],
    "pressure": ["Normalt rundt 1 013 hPa ved havnivå"],
    "pm25": ["Bra · under 10 µg/m³", "Middels · 10–25 µg/m³", "Dårlig · over 25 µg/m³"],
    "pm1": ["Bra · under 10 µg/m³", "Middels · 10–25 µg/m³", "Dårlig · over 25 µg/m³"],
}


class AirthingsError(Exception):
    pass


def keychain(account):
    try:
        return subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
            capture_output=True, text=True, check=True).stdout.strip()
    except subprocess.CalledProcessError:
        raise AirthingsError(f"Mangler «{account}» i nøkkelringen (tjeneste {KEYCHAIN_SERVICE})")


def cache_path(name):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, name)


def read_cache(name, ttl):
    try:
        with open(cache_path(name)) as f:
            data = json.load(f)
        if time.time() - data["at"] < ttl:
            return data["value"]
    except (OSError, ValueError, KeyError):
        pass
    return None


def write_cache(name, value):
    with open(cache_path(name), "w") as f:
        json.dump({"at": time.time(), "value": value}, f)
    os.chmod(cache_path(name), 0o600)


def http(url, headers, body=None):
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise AirthingsError(f"HTTP {e.code} fra {url.split('/')[2]}: {detail}")
    except urllib.error.URLError as e:
        raise AirthingsError(f"Får ikke kontakt med Airthings: {e.reason}")


def token():
    cached = read_cache("token.json", 10**9)
    if cached and cached["expires"] - time.time() > 300:
        return cached["header"]
    basic = base64.b64encode(f"{keychain('client-id')}:{keychain('client-secret')}".encode()).decode()
    data = http(TOKEN_URL, {"Authorization": f"Basic {basic}", "Content-Type": "application/json"},
                json.dumps({"grant_type": "client_credentials"}).encode())
    header = f"{data.get('token_type', 'Bearer')} {data['access_token']}"
    write_cache("token.json", {"header": header, "expires": time.time() + int(data.get("expires_in", 3600))})
    return header


def api(path):
    return http(API + path, {"Authorization": token(), "Accept": "application/json"})


def fetch(force=False):
    cached = None if force else read_cache("data.json", CACHE_TTL)
    if cached:
        return cached
    accounts = api("/accounts")
    acc = accounts["accounts"][0]["id"]
    data = {"devices": api(f"/accounts/{acc}/devices"),
            "sensors": api(f"/accounts/{acc}/sensors?unit=metric")}
    write_cache("data.json", data)
    return data


def normalize(result):
    """Gjør om ett resultat til {sensor: (verdi, enhet)} uansett format."""
    values = {}
    raw = result.get("sensors", result.get("data", result))
    if isinstance(raw, list):
        for s in raw:
            key = ALIASES.get(str(s.get("sensorType", s.get("type", ""))).lower())
            if key and s.get("value") is not None:
                values[key] = (float(s["value"]), s.get("unit"))
    elif isinstance(raw, dict):
        for k, v in raw.items():
            key = ALIASES.get(k.lower())
            if key and isinstance(v, (int, float)):
                values[key] = (float(v), None)
    for k in ("batteryPercentage", "battery"):
        if isinstance(result.get(k), (int, float)):
            values["battery"] = (float(result[k]), "%")
    return values


def level(key, value):
    if key == "humidity":
        return 0 if 30 <= value <= 60 else 1 if 25 <= value <= 70 else 2
    if key == "temp":
        return 0 if 18 <= value <= 25 else 1
    limits = SENSORS[key][2]
    if not limits:
        return None
    for maks, lvl in limits:
        if maks is None or value < maks:
            return lvl


def fnum(x):
    s = f"{x:.1f}" if abs(x) < 100 and x != int(x) else f"{x:,.0f}".replace(",", " ")
    return s.replace(".", ",")


def parse_time(ts):
    """ISO-tid fra API/Bluetooth (UTC uten tidssone) -> aware datetime."""
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def read_ble():
    """Ferske verdier fra bin/airthings-ble, eller None hvis for gamle/mangler."""
    try:
        with open(os.path.join(CACHE_DIR, "ble.json")) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if (datetime.now(timezone.utc) - parse_time(data.get("recorded"))).total_seconds() > BLE_MAX_AGE:
        return None
    values = data.get("values", {})
    sensors = [{"sensorType": k, "value": v} for k, v in values.items()]
    return {"recorded": data["recorded"], "sensors": sensors, "radon_lt": values.get("radonLongTermAvg")}


def kick_ble():
    """Ber launchd-jobben lese sensoren nå (Alfred selv har ikke Bluetooth-tilgang).

    Returnerer True mens vi venter på svaret, så Alfred kan kjøre filteret på nytt."""
    stamp = cache_path("ble-kick")
    try:
        kicked = os.path.getmtime(stamp)
    except OSError:
        kicked = 0
    if time.time() - kicked > 60:
        subprocess.run(["launchctl", "kickstart", f"gui/{os.getuid()}/{BLE_JOB}"], capture_output=True)
        open(stamp, "w").close()
        kicked = time.time()
    try:
        done = os.path.getmtime(os.path.join(CACHE_DIR, "ble.json")) >= kicked
    except OSError:
        done = False
    return not done and time.time() - kicked < 40


def ago(ts):
    if not ts:
        return ""
    t = parse_time(ts)
    if t.year == 1:
        return ""
    mins = int((datetime.now(timezone.utc) - t).total_seconds() // 60)
    rel = "nå nettopp" if mins < 1 else f"{mins} min siden" if mins < 120 else f"{mins // 60} t {mins % 60} min siden"
    return f"målt kl. {t.astimezone():%H:%M} ({rel})"


def clock(ts):
    t = parse_time(ts)
    return "–" if t.year == 1 else f"kl. {t.astimezone():%H:%M}"


def extended(key, ble, cloud):
    """Shift-undertittel: forklaring, langtidssnitt for radon og begge kildene."""
    label, unit = SENSORS[key][0], SENSORS[key][1]
    parts = [ABOUT.get(key, label)]
    if key == "radon" and ble and ble.get("radon_lt") is not None:
        parts.append(f"langtidssnitt {fnum(ble['radon_lt'])} {unit}")
    if ble:
        b = next((x["value"] for x in ble["sensors"] if ALIASES.get(x["sensorType"].lower()) == key), None)
        if b is not None:
            parts.append(f"Bluetooth {fnum(b)} {clock(ble['recorded'])}")
    if cloud and key in cloud["values"]:
        parts.append(f"sky {fnum(cloud['values'][key][0])} {clock(cloud['recorded'])}")
    return " · ".join(parts)


def device_names(devices):
    names = {}
    for d in devices.get("devices", []):
        sn = d.get("serialNumber") or d.get("id")
        names[sn] = d.get("name") or d.get("segment", {}).get("name") or d.get("type") or sn
    return names


PERIOD_WORDS = {"dag": 1, "døgn": 1, "uke": 7, "måned": 30, "mnd": 30, "kvartal": 90, "år": 365}
DATE = r"(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?"


def parse_period(q):
    """«7», «30 dager», «uke», «1.10-15.10» -> (start, slutt, beskrivelse) eller None."""
    now = datetime.now().astimezone().replace(second=0, microsecond=0)
    m = re.fullmatch(r"(\d{1,4})\s*(d|dag|dager|døgn)?", q)
    if m or q in PERIOD_WORDS:
        n = int(m.group(1)) if m else PERIOD_WORDS[q]
        return now - timedelta(days=n), now, ("siste døgn" if n == 1 else f"siste {n} dager")
    m = re.fullmatch(DATE + r"\s*[-–]\s*" + DATE, q)
    if m:
        def day(d, mo, y):
            y = int(y) + (2000 if y and len(y) == 2 else 0) if y else now.year
            return datetime(y, int(mo), int(d)).astimezone()
        try:
            a, b = day(*m.groups()[:3]), day(*m.groups()[3:])
        except ValueError:
            return None
        if a > now:
            a = a.replace(year=a.year - 1)
        b = min(b + timedelta(days=1), now)
        return (a, b, f"{a:%d.%m.%Y} – {(b - timedelta(minutes=1)):%d.%m.%Y}") if a < b else None
    return None


def report_items(q):
    period = parse_period(q)
    if not period:
        return []
    start, end, label = period
    return [{
        "title": f"Lag luftrapport: {label}",
        "subtitle": f"{start:%d.%m %H:%M} – {end:%d.%m %H:%M} · PDF med sammendrag og grafer, lagres i Nedlastinger",
        "icon": {"path": "icon.png"},
        "arg": "report",
        "variables": {"action": "report", "start": start.isoformat(), "end": end.isoformat()},
        "mods": {"cmd": {"valid": False, "subtitle": "Enter lager rapporten"},
                 "shift": {"valid": False, "subtitle": "Historikk fra skyen, fylt inn med Bluetooth-målinger etter siste synk"}},
    }]


def report_suggestions():
    out = []
    for q in ("1", "7", "30", "90"):
        item = report_items(q)[0]
        item["autocomplete"] = q
        out.append(item)
    out.append({"title": "Eget tidsrom: f.eks. 1.10-15.10", "subtitle": "Skriv fra- og til-dato (begge dager tas med)",
                "valid": False, "autocomplete": "1.10-15.10"})
    return out


def items(query, report_only=False):
    q = query.strip().lower()
    if report_only:
        return (report_items(q) or report_suggestions()), False
    if parse_period(q):
        return report_items(q), False
    force = q.startswith("!")
    q = q.lstrip("!").strip()
    want = SEARCH.get(q, ALIASES.get(q)) if q else None
    waiting = kick_ble() if force else False
    ble = read_ble()
    try:
        data = fetch(force)
    except AirthingsError:
        if not ble:
            raise
        data = {"devices": {}, "sensors": {"results": []}}
    names = device_names(data["devices"])
    results = data["sensors"].get("results", [])
    cloud = {}
    if results:
        cloud = {"values": normalize(results[0]), "recorded": results[0].get("recorded")}
    if ble:
        # Bluetooth-tallene gjelder sensoren i nærheten; kontoen har én Wave Plus
        if not results:
            results = [{"serialNumber": None}]
        if parse_time(ble["recorded"]) > parse_time(results[0].get("recorded")):
            results[0] = {**results[0], "sensors": ble["sensors"], "recorded": ble["recorded"], "source": "Bluetooth"}
    out = []
    for r in results:
        sn = r.get("serialNumber") or r.get("sn")
        name = names.get(sn, sn or "Wave Plus")
        vals = normalize(r)
        when = ago(r.get("recorded") or r.get("time"))
        when = f"{when} via {r.get('source', 'sky')}" if when else ""
        order = [k for k in SENSORS if k in vals and k != "battery"]
        lvls = [level(k, vals[k][0]) for k in order]
        worst = max([x for x in lvls if x is not None], default=0)
        short = " · ".join(f"{SENSORS[k][0]} {fnum(vals[k][0])} {SENSORS[k][1]}" for k in order)
        battery = f"batteri {fnum(vals['battery'][0])} %" if "battery" in vals else ""
        if not want:
            bad = [SENSORS[k][0] for k, lv in zip(order, lvls) if lv]
            status = f"{' og '.join(bad)} {LEVEL_TEXT[worst]}" if bad else "god luft"
            out.append({
                "title": f"{name} – {status}",
                "subtitle": " · ".join(x for x in (when[:1].upper() + when[1:], battery) if x),
                "icon": {"path": f"icons/{worst}.png"},
                "arg": DASHBOARD,
                "text": {"copy": short, "largetype": f"{name}\n{short}"},
                "mods": {"cmd": {"arg": short, "subtitle": "Kopier alle verdiene"},
                         "shift": {"arg": DASHBOARD, "subtitle": " · ".join(x for x in (
                             f"Skyen sist synket {clock(cloud.get('recorded'))}" if cloud else "Ingen data fra skyen",
                             f"Bluetooth lest {clock(ble['recorded'])}" if ble else "Ikke lest over Bluetooth siste 15 min",
                             ) if x)}},
            })
        for k, lv in zip(order, lvls):
            if want and k != want:
                continue
            label, unit = SENSORS[k][0], SENSORS[k][1]
            txt = f"{fnum(vals[k][0])} {unit}"
            sub = HINTS[k][lv] if lv is not None else HINTS[k][0]
            if want and when:
                sub += f" · {when}"
            out.append({
                "title": f"{label}   {txt}",
                "subtitle": sub,
                "icon": {"path": f"icons/{'n' if lv is None else lv}.png"},
                "arg": DASHBOARD,
                "text": {"copy": txt, "largetype": f"{label}: {txt}"},
                "mods": {"cmd": {"arg": f"{label}: {txt}", "subtitle": "Kopier verdien"},
                         "shift": {"arg": DASHBOARD, "subtitle": extended(k, ble, cloud)}},
            })
    if waiting:
        out.insert(0, {"title": "Leser sensoren over Bluetooth …", "subtitle": "Oppdateres av seg selv når svaret kommer", "valid": False})
    if not out:
        out.append({"title": "Ingen målinger funnet", "subtitle": "Kjør airthings.py --raw for å se svaret fra API-et",
                    "arg": DASHBOARD})
    return out, waiting


if __name__ == "__main__":
    if "--raw" in sys.argv:
        print(json.dumps(fetch(force=True), indent=2, ensure_ascii=False))
        sys.exit()
    rerun = False
    try:
        args = [x for x in sys.argv[1:] if x != "--report"]
        result, rerun = items(args[0] if args else "", report_only="--report" in sys.argv)
    except AirthingsError as e:
        result = [{"title": "Airthings: " + str(e), "subtitle": "Enter åpner dashboardet", "arg": DASHBOARD}]
    except Exception as e:
        result = [{"title": "Feil i airthings.py", "subtitle": f"{type(e).__name__}: {e}", "valid": False}]
    print(json.dumps({"items": result, **({"rerun": 2} if rerun else {})}, ensure_ascii=False))
