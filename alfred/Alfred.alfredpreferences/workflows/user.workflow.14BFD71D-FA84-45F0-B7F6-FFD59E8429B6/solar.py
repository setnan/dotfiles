# /// script
# requires-python = ">=3.11"
# dependencies = ["pint>=0.24"]
# ///
"""Fysikkalkulator for Alfred: `sol s=120km t=1.5h` -> v = 80 km/t.

Skriv variabler som navn=verdi[enhet]. Alle formler som kan løses med det
du har oppgitt vises, også i to-tre ledd (m, dT, P -> Q -> t). Verdier uten
enhet tolkes i SI (eller standardenheten til variabelen).
"""

import json
import math
import re
import sys

import pint

ureg = pint.UnitRegistry(cache_folder=":auto:")
ureg.define("hk = 735.49875 * watt")
ureg.define("kr = [valuta]")
ureg.define("øre = 0.01 * kr")
Q_ = ureg.Quantity

G0 = Q_(9.80665, "m/s**2")

# navn: (beskrivelse, standardenhet)
VARS = {
    "s": ("strekning", "m"),
    "t": ("tid", "s"),
    "v": ("fart", "m/s"),
    "v0": ("startfart", "m/s"),
    "a": ("akselerasjon", "m/s**2"),
    "m": ("masse", "kg"),
    "F": ("kraft", "N"),
    "E": ("energi", "J"),
    "Ek": ("kinetisk energi", "J"),
    "Ep": ("potensiell energi", "J"),
    "W": ("arbeid", "J"),
    "Q": ("varme", "J"),
    "h": ("høyde", "m"),
    "P": ("effekt", "W"),
    "U": ("spenning", "V"),
    "I": ("strøm", "A"),
    "R": ("motstand", "ohm"),
    "p": ("trykk", "Pa"),
    "A": ("areal", "m**2"),
    "rho": ("tetthet", "kg/m**3"),
    "V": ("volum", "m**3"),
    "f": ("frekvens", "Hz"),
    "T": ("periode", "s"),
    "lambda": ("bølgelengde", "m"),
    "cp": ("spesifikk varmekapasitet", "J/(kg*K)"),
    "dT": ("temperaturendring", "K"),
    "mu": ("friksjonstall", "dimensionless"),
    "tr": ("reaksjonstid", "s"),
    "sb": ("stopplengde", "m"),
    "pris": ("strømpris", "kr/kWh"),
    "kost": ("kostnad", "kr"),
}

ALIASES = {
    "strekning": "s", "distanse": "s", "tid": "t", "fart": "v", "hastighet": "v",
    "startfart": "v0", "v_0": "v0", "akselerasjon": "a", "masse": "m",
    "kraft": "F", "energi": "E", "arbeid": "W", "varme": "Q", "høyde": "h",
    "effekt": "P", "spenning": "U", "strøm": "I", "motstand": "R",
    "trykk": "p", "areal": "A", "tetthet": "rho", "ρ": "rho", "volum": "V",
    "frekvens": "f", "periode": "T", "λ": "lambda", "bølgelengde": "lambda",
    "c": "cp", "varmekapasitet": "cp", "ΔT": "dT", "dt": "dT", "μ": "mu",
    "friksjon": "mu", "reaksjonstid": "tr", "kostnad": "kost",
}

# Variabler som summeres når de oppgis flere ganger (snittfart over etapper)
SUMMABLE = {"s", "t"}

UNIT_ALIASES = {
    "km/t": "km/h", "kmt": "km/h", "kmh": "km/h", "kph": "km/h",
    "timer": "h", "time": "h", "sek": "s", "døgn": "day", "tonn": "t",
    "knop": "knot", "kwh": "kWh", "kw": "kW", "kwt": "kWh", "mah": "mA*h",
    "ah": "A*h", "kr/kwh": "kr/kWh", "øre/kwh": "øre/kWh", "ohm": "ohm",
    "liter": "L", "l": "L",
}


def num(s):
    return float(s.replace(",", "."))


# --- formler ---------------------------------------------------------------
# Hver formel: familie, mål, uttrykk, påkrevde inndata, valgfrie standardverdier
# (verdi, merknad), funksjon. chain=False betyr at resultatet ikke brukes videre.

def F(family, target, expr, inputs, fn, defaults=None, chain=True, direct=False, kw=""):
    # direct=True: bare oppgitte verdier brukes som inndata, ikke utregnede
    return dict(family=family, target=target, expr=expr, inputs=inputs,
                fn=fn, defaults=defaults or {}, chain=chain, direct=direct, kw=kw)


REST = (Q_(0, "m/s"), "fra ro")
FORMULAS = [
    F("Fart", "v", "v = s / t", ["s", "t"], lambda d: d["s"] / d["t"], kw="snittfart hastighet"),
    F("Fart", "s", "s = v · t", ["v", "t"], lambda d: d["v"] * d["t"], kw="strekning"),
    F("Fart", "t", "t = s / v", ["s", "v"], lambda d: d["s"] / d["v"], kw="tid reisetid"),

    F("Akselerasjon", "a", "a = (v − v₀) / t", ["v", "t"], lambda d: (d["v"] - d["v0"]) / d["t"], {"v0": REST}, direct=True),
    F("Akselerasjon", "v", "v = v₀ + a · t", ["a", "t"], lambda d: d["v0"] + d["a"] * d["t"], {"v0": REST}),
    F("Akselerasjon", "t", "t = (v − v₀) / a", ["v", "a"], lambda d: (d["v"] - d["v0"]) / d["a"], {"v0": REST}),
    F("Akselerasjon", "s", "s = v₀ · t + ½ · a · t²", ["a", "t"],
      lambda d: d["v0"] * d["t"] + 0.5 * d["a"] * d["t"] ** 2, {"v0": REST}),
    F("Akselerasjon", "v", "v = √(v₀² + 2 · a · s)", ["a", "s"],
      lambda d: (d["v0"] ** 2 + 2 * d["a"] * d["s"]) ** 0.5, {"v0": REST}),

    F("Fritt fall", "t", "t = √(2h / g)", ["h"], lambda d: (2 * d["h"] / G0) ** 0.5, chain=False, kw="fall"),
    F("Fritt fall", "v", "v = √(2 · g · h)", ["h"], lambda d: (2 * G0 * d["h"]) ** 0.5, chain=False, kw="fall nedslag"),

    F("Stopplengde", "sb", "sb = v · tr + v² / (2 · μ · g)", ["v"],
      lambda d: d["v"] * d["tr"] + d["v"] ** 2 / (2 * d["mu"] * G0),
      {"mu": (Q_(0.8), "μ = 0,8 tørr asfalt"), "tr": (Q_(1, "s"), "tr = 1 s")},
      chain=False, direct=True, kw="brems bremselengde stopp"),

    F("Newtons 2. lov", "F", "F = m · a", ["m", "a"], lambda d: d["m"] * d["a"], kw="kraft"),
    F("Newtons 2. lov", "a", "a = F / m", ["F", "m"], lambda d: d["F"] / d["m"]),
    F("Newtons 2. lov", "m", "m = F / a", ["F", "a"], lambda d: d["F"] / d["a"]),

    F("Kinetisk energi", "Ek", "Ek = ½ · m · v²", ["m", "v"], lambda d: 0.5 * d["m"] * d["v"] ** 2, kw="bevegelsesenergi"),
    F("Kinetisk energi", "v", "v = √(2 · Ek / m)", ["Ek", "m"], lambda d: (2 * d["Ek"] / d["m"]) ** 0.5),
    F("Kinetisk energi", "m", "m = 2 · Ek / v²", ["Ek", "v"], lambda d: 2 * d["Ek"] / d["v"] ** 2),

    F("Potensiell energi", "Ep", "Ep = m · g · h", ["m", "h"], lambda d: d["m"] * G0 * d["h"], kw="stillingsenergi"),
    F("Potensiell energi", "h", "h = Ep / (m · g)", ["Ep", "m"], lambda d: d["Ep"] / (d["m"] * G0)),
    F("Potensiell energi", "m", "m = Ep / (g · h)", ["Ep", "h"], lambda d: d["Ep"] / (G0 * d["h"])),

    F("Arbeid", "W", "W = F · s", ["F", "s"], lambda d: d["F"] * d["s"]),
    F("Arbeid", "F", "F = W / s", ["W", "s"], lambda d: d["W"] / d["s"]),
    F("Arbeid", "s", "s = W / F", ["W", "F"], lambda d: d["W"] / d["F"]),

    F("Effekt og energi", "E", "E = P · t", ["P", "t"], lambda d: d["P"] * d["t"], kw="lading forbruk"),
    F("Effekt og energi", "t", "t = E / P", ["E", "P"], lambda d: d["E"] / d["P"], kw="ladetid lading"),
    F("Effekt og energi", "P", "P = E / t", ["E", "t"], lambda d: d["E"] / d["t"]),
    F("Effekt og energi", "P", "P = W / t", ["W", "t"], lambda d: d["W"] / d["t"]),
    F("Effekt og energi", "P", "P = F · v", ["F", "v"], lambda d: d["F"] * d["v"]),

    F("Strømkostnad", "kost", "kost = E · pris", ["E", "pris"], lambda d: d["E"] * d["pris"], kw="strømpris pris kostnad"),
    F("Strømkostnad", "E", "E = kost / pris", ["kost", "pris"], lambda d: d["kost"] / d["pris"]),

    F("Ohms lov", "U", "U = R · I", ["R", "I"], lambda d: d["R"] * d["I"], kw="elektrisitet"),
    F("Ohms lov", "I", "I = U / R", ["U", "R"], lambda d: d["U"] / d["R"]),
    F("Ohms lov", "R", "R = U / I", ["U", "I"], lambda d: d["U"] / d["I"]),

    F("Elektrisk effekt", "P", "P = U · I", ["U", "I"], lambda d: d["U"] * d["I"], kw="elektrisitet watt"),
    F("Elektrisk effekt", "I", "I = P / U", ["P", "U"], lambda d: d["P"] / d["U"], kw="sikring ampere"),
    F("Elektrisk effekt", "U", "U = P / I", ["P", "I"], lambda d: d["P"] / d["I"]),
    F("Elektrisk effekt", "P", "P = U² / R", ["U", "R"], lambda d: d["U"] ** 2 / d["R"]),
    F("Elektrisk effekt", "P", "P = I² · R", ["I", "R"], lambda d: d["I"] ** 2 * d["R"]),

    F("Trykk", "p", "p = F / A", ["F", "A"], lambda d: d["F"] / d["A"]),
    F("Trykk", "F", "F = p · A", ["p", "A"], lambda d: d["p"] * d["A"]),
    F("Trykk", "A", "A = F / p", ["F", "p"], lambda d: d["F"] / d["p"]),
    F("Hydrostatisk trykk", "p", "p = ρ · g · h", ["rho", "h"], lambda d: d["rho"] * G0 * d["h"], kw="vanntrykk dykking"),

    F("Tetthet", "rho", "ρ = m / V", ["m", "V"], lambda d: d["m"] / d["V"], direct=True, kw="densitet"),
    F("Tetthet", "m", "m = ρ · V", ["V"], lambda d: d["rho"] * d["V"],
      {"rho": (Q_(1000, "kg/m**3"), "ρ = 1000 kg/m³ (vann)")}),
    F("Tetthet", "V", "V = m / ρ", ["m", "rho"], lambda d: d["m"] / d["rho"], direct=True),

    F("Bølger", "v", "v = f · λ", ["f", "lambda"], lambda d: d["f"] * d["lambda"], kw="lyd lys"),
    F("Bølger", "f", "f = v / λ", ["v", "lambda"], lambda d: d["v"] / d["lambda"]),
    F("Bølger", "lambda", "λ = v / f", ["v", "f"], lambda d: d["v"] / d["f"]),
    F("Periode", "T", "T = 1 / f", ["f"], lambda d: 1 / d["f"]),
    F("Periode", "f", "f = 1 / T", ["T"], lambda d: 1 / d["T"]),

    F("Oppvarming", "Q", "Q = m · c · ΔT", ["m", "dT"], lambda d: d["m"] * d["cp"] * d["dT"],
      {"cp": (Q_(4186, "J/(kg*K)"), "c = 4186 J/(kg·K) (vann)")}, kw="varme koke"),
    F("Oppvarming", "dT", "ΔT = Q / (m · c)", ["Q", "m"], lambda d: d["Q"] / (d["m"] * d["cp"]),
      {"cp": (Q_(4186, "J/(kg*K)"), "c = 4186 J/(kg·K) (vann)")}),
    F("Oppvarming", "t", "t = Q / P", ["Q", "P"], lambda d: d["Q"] / d["P"], kw="koketid oppvarmingstid"),
]

EXAMPLES = {
    "Fart": "s=120km t=1.5h",
    "Akselerasjon": "v=100km/h t=4s",
    "Fritt fall": "h=20m",
    "Stopplengde": "v=80km/h mu=0.7",
    "Newtons 2. lov": "m=1200kg a=3",
    "Kinetisk energi": "m=1200kg v=100km/h",
    "Potensiell energi": "m=80kg h=10m",
    "Arbeid": "F=500N s=20m",
    "Effekt og energi": "E=60kWh P=11kW",
    "Strømkostnad": "P=2kW t=3h pris=1.2",
    "Ohms lov": "U=230V R=50ohm",
    "Elektrisk effekt": "P=2000W U=230V",
    "Trykk": "F=700N A=0.05m²",
    "Hydrostatisk trykk": "rho=1000 h=10m",
    "Tetthet": "m=500g V=0.4L",
    "Bølger": "f=440Hz v=343m/s",
    "Periode": "f=50Hz",
    "Oppvarming": "V=1L dT=80 P=2kW",
}

CONSTANTS = [
    ("c", "lyshastighet", Q_(299792458, "m/s")),
    ("g", "tyngdeakselerasjon", G0),
    ("G", "gravitasjonskonstant", Q_(6.67430e-11, "m**3/(kg*s**2)")),
    ("lydfart", "lydfart i luft, 20 °C", Q_(343, "m/s")),
    ("planck", "Plancks konstant", Q_(6.62607015e-34, "J*s")),
    ("e", "elementærladning", Q_(1.602176634e-19, "C")),
    ("NA", "Avogadros tall", Q_(6.02214076e23, "1/mol")),
    ("kB", "Boltzmanns konstant", Q_(1.380649e-23, "J/K")),
    ("vann", "varmekapasitet vann", Q_(4186, "J/(kg*K)")),
]


# --- formatering -----------------------------------------------------------

def fnum(x, sig=4):
    if x == 0 or not math.isfinite(x):
        return "0" if x == 0 else str(x)
    if abs(x) >= 1e9 or abs(x) < 1e-4:
        m, e = f"{x:.{sig - 1}e}".split("e")
        m = m.rstrip("0").rstrip(".").replace(".", ",")
        return f"{m}·10^{int(e)}"
    decimals = max(0, sig - 1 - math.floor(math.log10(abs(x))))
    s = f"{x:,.{decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(",", " ").replace(".", ",")


def ustr(q):
    u = f"{q.units:~P}"
    if u == "h":
        return "t"
    return u.replace("km/h", "km/t")


def qstr(q):
    return f"{fnum(q.magnitude)} {ustr(q)}".strip()


def human_time(sec):
    if sec < 60:
        return f"{fnum(sec)} s"
    parts = []
    for size, name in ((86400, "døgn"), (3600, "t"), (60, "min"), (1, "s")):
        n = int(sec // size)
        if n or (parts and size == 1 and False):
            parts.append(f"{n} {name}")
            sec -= n * size
        if len(parts) == 2:
            break
    return " ".join(parts)


def dim_is(q, ref):
    return q.dimensionality == ureg.parse_units(ref).dimensionality


def fmt(q):
    """Returnerer (hovedvisning, [alternativer]) for en størrelse."""
    q = q.to_base_units() if not dim_is(q, "kr") else q.to("kr")
    if dim_is(q, "m/s"):
        return qstr(q.to("km/h")), [qstr(q.to("m/s"))]
    if dim_is(q, "s"):
        sec = q.to("s").magnitude
        alts = [qstr(q.to("s"))] if sec >= 60 else []
        if sec >= 3600:
            alts.append(qstr(q.to("h")))
        elif sec >= 60:
            alts.append(qstr(q.to("min")))
        return human_time(sec), alts
    if dim_is(q, "m"):
        mm = q.to("m").magnitude
        main = q.to("km") if abs(mm) >= 1000 else q.to("m") if abs(mm) >= 1 else q.to("cm") if abs(mm) >= 0.01 else q.to_compact()
        return qstr(main), [] if main.units == ureg.m else [qstr(q.to("m"))]
    if dim_is(q, "kg"):
        kg = q.to("kg").magnitude
        main = q.to("t") if abs(kg) >= 1000 else q.to("kg") if abs(kg) >= 1 else q.to("g")
        return qstr(main).replace(" t", " tonn"), [] if main.units == ureg.kg else [qstr(q.to("kg"))]
    if dim_is(q, "J"):
        if q.to("J").magnitude >= 3.6e6:
            return qstr(q.to("kWh")), [qstr(q.to("J").to_compact())]
        return qstr(q.to("J").to_compact()), [qstr(q.to("kWh")), qstr(q.to("kcal"))]
    if dim_is(q, "W"):
        return qstr(q.to("W").to_compact()), [qstr(q.to("hk"))]
    if dim_is(q, "Pa"):
        return qstr(q.to("Pa").to_compact()), [qstr(q.to("bar"))]
    if dim_is(q, "m**3"):
        return qstr(q.to("L")), [qstr(q.to("m**3"))]
    if dim_is(q, "m/s**2"):
        return qstr(q.to("m/s**2")), [f"{fnum(q.to('m/s**2').magnitude / G0.magnitude)} g"]
    if dim_is(q, "kg/m**3"):
        return qstr(q.to("kg/m**3")), [qstr(q.to("g/cm**3"))]
    if dim_is(q, "kr"):
        return f"{fnum(q.to('kr').magnitude)} kr", []
    if dim_is(q, "kr/kWh"):
        return qstr(q.to("kr/kWh")), []
    if dim_is(q, "K"):
        return qstr(q.to("K")).replace(" K", " K (°C)"), []
    for ref in ("V", "A", "ohm", "N", "Hz", "m**2"):
        if dim_is(q, ref):
            return qstr(q.to(ref).to_compact()), []
    if q.dimensionless:
        return fnum(q.to("").magnitude), []
    return qstr(q.to_compact()), []


# --- parsing ---------------------------------------------------------------

ASSIGN = re.compile(r"([A-Za-zÆØÅæøåρλμΔ_][\wρλμΔ]*)\s*=\s*")
VALUE = re.compile(r"^([-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?)\s*([^\s=]*)")


def norm_unit(var, u):
    u = u.replace("²", "**2").replace("³", "**3").replace("·", "*")
    low = u.lower()
    if var in ("t", "T", "tr") and low == "t":
        return "h"
    if var == "dT" and low in ("c", "°c", "°", "k"):
        return "K"
    if var == "a" and u == "g":
        return "standard_gravity"
    if var == "mu" and u == "%":
        return "percent"
    return UNIT_ALIASES.get(low, u)


def parse_query(q):
    given, counts, errors, words = {}, {}, [], []
    matches = list(ASSIGN.finditer(q))
    pos = 0
    for i, mt in enumerate(matches):
        words += q[pos:mt.start()].split()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(q)
        raw_name, chunk = mt.group(1), q[mt.end():end]
        pos = end
        name = raw_name if raw_name in VARS else ALIASES.get(raw_name, ALIASES.get(raw_name.lower()))
        vm = VALUE.match(chunk)
        if not vm:
            if chunk.strip():
                errors.append((raw_name, f"forstår ikke verdien «{chunk.strip()}»"))
            continue
        words += chunk[vm.end():].split()
        if not name:
            errors.append((raw_name, "ukjent variabel – skriv «sol» for å se oversikten"))
            continue
        number, unit = vm.group(1), vm.group(2)
        try:
            value = num(number)
            unit = norm_unit(name, unit) if unit else VARS[name][1]
            qty = Q_(value, unit) if unit != "dimensionless" else Q_(value)
        except Exception:
            errors.append((raw_name, f"ukjent enhet «{vm.group(2)}»"))
            continue
        want = Q_(1, VARS[name][1])
        if name == "V" and dim_is(qty, "V"):
            name, want = "U", Q_(1, "V")
        if qty.dimensionality != want.dimensionality:
            errors.append((raw_name, f"{qstr(qty)} er ikke en {VARS[name][0]} (forventer f.eks. {VARS[name][1].replace('**2', '²').replace('**3', '³')})"))
            continue
        counts[name] = counts.get(name, 0) + 1
        if name in given and name in SUMMABLE:
            given[name] = given[name] + qty
        else:
            given[name] = qty
    words += q[pos:].split() if not matches else []
    return given, counts, errors, words


# --- løsning ---------------------------------------------------------------

def solve(given):
    known = {k: (v, 0, [], True) for k, v in given.items()}  # verdi, dybde, merknader, kan kjedes
    results = []
    for depth in range(3):
        new = {}
        for f in FORMULAS:
            if f["target"] in given:
                continue
            if depth > 0 and (f["direct"] or f["target"] in known or f["target"] in new):
                continue
            ins = f["inputs"]
            if not all(k in known and (known[k][3] or depth == 0 and known[k][1] == 0) for k in ins):
                continue
            if depth > 0 and all(known[k][1] == 0 for k in ins):
                continue  # allerede regnet ut i første runde
            if depth > 0 and not any(known[k][1] == depth for k in ins):
                continue
            d = {k: known[k][0] for k in ins}
            notes = [n for k in ins for n in known[k][2]]
            for k, (val, note) in f["defaults"].items():
                if k in known and known[k][1] == 0:
                    d[k] = known[k][0]
                else:
                    d[k] = val
                    notes.append(note)
            try:
                res = f["fn"](d)
                res = res.to(VARS[f["target"]][1]) if VARS[f["target"]][1] != "dimensionless" else res.to("")
                if not math.isfinite(float(res.magnitude)):
                    continue
            except (ZeroDivisionError, ValueError, pint.errors.PintError):
                continue
            via = [k for k in ins if known[k][1] > 0]
            results.append(dict(f=f, value=res, inputs=d, notes=list(dict.fromkeys(notes)), via=via, depth=depth))
            if f["target"] not in new and f["target"] not in known:
                new[f["target"]] = (res, depth + 1, notes, f["chain"])
        if not new:
            break
        known.update(new)
    return results


def var_label(k):
    return {"lambda": "λ", "rho": "ρ", "mu": "μ", "dT": "ΔT", "v0": "v₀"}.get(k, k)


def result_item(r):
    f, target = r["f"], r["f"]["target"]
    main, alts = fmt(r["value"])
    tl = var_label(target)
    used = ", ".join(f"{var_label(k)} = {fmt(v)[0]}" for k, v in r["inputs"].items())
    full = f"{f['expr']}  med {used}  ⇒  {tl} = {main}"
    sub = [f"{f['family']} · {f['expr']}"]
    if alts:
        sub.append(" = ".join(alts))
    if r["via"]:
        sub.append("via " + ", ".join(var_label(v) for v in r["via"]))
    if r["notes"]:
        sub.append(", ".join(r["notes"]))
    return {
        "title": f"{tl} = {main}   ({VARS[target][0]})",
        "subtitle": " · ".join(sub),
        "arg": main,
        "text": {"copy": main, "largetype": f"{tl} = {main}"},
        "mods": {
            "cmd": {"arg": full, "subtitle": "Kopier hele utregningen: " + full},
            "alt": {"arg": f"{tl} = {main}", "subtitle": "Vis i stor tekst"},
        },
    }


def given_item(given, counts):
    parts = []
    for k, v in given.items():
        s = f"{var_label(k)} = {fmt(v)[0]}"
        if counts.get(k, 1) > 1:
            s += f" (sum av {counts[k]})"
        parts.append(s)
    return {"title": "Oppgitt: " + ", ".join(parts), "subtitle": "Ingen formel passer ennå – se forslagene under", "valid": False}


def near_misses(given, query):
    """Formler som bare mangler én variabel."""
    seen, items = set(), []
    for f in FORMULAS:
        if f["target"] in given:
            continue
        missing = [k for k in f["inputs"] if k not in given]
        if len(missing) == 1 and len(f["inputs"]) > 1 and (f["family"], missing[0]) not in seen:
            seen.add((f["family"], missing[0]))
            k = missing[0]
            items.append({
                "title": f"Legg til {var_label(k)} ({VARS[k][0]}) for å regne ut {var_label(f['target'])}",
                "subtitle": f"{f['family']} · {f['expr']}",
                "autocomplete": f"{query.rstrip()} {k}=",
                "valid": False,
            })
    return items[:8]


def cheatsheet(words):
    items = []
    filt = " ".join(words).lower()
    for fam, ex in EXAMPLES.items():
        fs = [f for f in FORMULAS if f["family"] == fam]
        hay = " ".join([fam] + [f["kw"] for f in fs] + [VARS[f["target"]][0] for f in fs] + [f["target"] for f in fs]).lower()
        if filt and not all(w in hay for w in filt.split()):
            continue
        varnames = sorted({k for f in fs for k in f["inputs"] + [f["target"]]}, key=list(VARS).index)
        items.append({
            "title": f"{fam}:  " + "   ".join(f["expr"] for f in fs[:3]),
            "subtitle": "  ".join(f"{var_label(k)} {VARS[k][0]}" for k in varnames) + f"  · ⇥ eksempel: {ex}",
            "autocomplete": ex,
            "valid": False,
        })
    return items


def constant_items(words):
    out = []
    for w in words:
        for key, desc, q in CONSTANTS:
            if w == key or (len(w) > 2 and w.lower() in desc.lower()):
                txt = f"{fnum(q.magnitude, 6)} {ustr(q)}"
                out.append({"title": f"{key} = {txt}", "subtitle": desc, "arg": txt,
                            "text": {"copy": txt, "largetype": f"{key} = {txt}"},
                            "mods": {"cmd": {"arg": f"{key} = {txt}"}, "alt": {"arg": f"{key} = {txt}"}}})
    return out


CONVERT = re.compile(r"^\s*([-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?)\s*(\S*)\s+(?:til|to|i|in)\s+(\S+)\s*$")


def conversion(q):
    m = CONVERT.match(q)
    if not m:
        return []
    value, src, dst = num(m.group(1)), m.group(2) or "", m.group(3)
    try:
        src = UNIT_ALIASES.get(src.lower(), src).replace("²", "**2").replace("³", "**3")
        dst_u = UNIT_ALIASES.get(dst.lower(), dst).replace("²", "**2").replace("³", "**3")
        res = Q_(value, src).to(dst_u)
    except Exception as e:
        return [{"title": "Kan ikke konvertere", "subtitle": str(e), "valid": False}]
    txt = qstr(res)
    return [{"title": f"{fnum(value)} {m.group(2)} = {txt}", "subtitle": "Enhetskonvertering", "arg": txt,
             "text": {"copy": txt, "largetype": txt},
             "mods": {"cmd": {"arg": f"{fnum(value)} {m.group(2)} = {txt}"}, "alt": {"arg": txt}}}]


def main(q):
    q = q.strip()
    if not q:
        return [{"title": "Fysikk: skriv variabler, f.eks. s=120km t=1.5h",
                 "subtitle": "Uten enhet = SI · flere s= og t= gir snittfart · «80 km/h til m/s» konverterer",
                 "valid": False}] + cheatsheet([])
    if "=" not in q:
        conv = conversion(q)
        if conv:
            return conv
        words = q.split()
        return constant_items(words) + cheatsheet(words) or [
            {"title": "Fant ingen formel eller konstant", "subtitle": "Prøv f.eks. «fart», «brems», «lading» eller «c»", "valid": False}]

    given, counts, errors, words = parse_query(q)
    items = [{"title": f"{name}: {msg}", "subtitle": "Rett opp verdien", "valid": False} for name, msg in errors]
    results = solve(given)
    if words:
        w = [x.lower() for x in words]
        results = [r for r in results if all(x in (r["f"]["family"] + " " + r["f"]["kw"] + " " + VARS[r["f"]["target"]][0]).lower() for x in w)]
    results.sort(key=lambda r: (r["depth"], bool(r["notes"])))
    items += [result_item(r) for r in results]
    if not results and given:
        items += [given_item(given, counts)] + near_misses(given, q)
    if "s" in given and "t" in given and counts.get("s", 1) > 1:
        for it in items:
            if it.get("title", "").startswith("v ="):
                it["subtitle"] = f"Snittfart over {counts['s']} etapper · " + it["subtitle"]
    return items or [{"title": "Skriv en verdi etter =", "valid": False}]


if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        items = main(query)
    except Exception as e:  # vis feilen i Alfred i stedet for å svelge den
        items = [{"title": "Feil i solar.py", "subtitle": f"{type(e).__name__}: {e}", "valid": False}]
    print(json.dumps({"items": items}, ensure_ascii=False))
