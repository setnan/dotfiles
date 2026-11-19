#!/usr/bin/env python3
"""Tidsføring per kunde/prosjekt i ett Obsidian-notat.

Notatet er kilden til sannhet:
  - hvert prosjekt er en `## overskrift` (normalisert til små bokstaver)
  - øktene står som tabellrader under overskriften, med en sumrad per dag
  - hva som kjører nå står i frontmatter (`aktiv`, `startet`)
Slett en overskrift, så forsvinner prosjektet. Gi det et navn som slutter på
`-archived` (eller `-arkivert`), så vises det ikke lenger i forslagene.

Klokkeslett kan legges til på slutten når du glemte å starte/stoppe:
  8 · 80 · 800 · 0800 · 8:00 → 08:00     81 → 08:10     815 → 08:15     12 → 12:00
Prosjektet som kjørte avsluttes da på samme tidspunkt.

Bruk:
  tid.py filter [tekst]        Alfred Script Filter for `start`
  tid.py stopfilter [tid]      Alfred Script Filter for `stop`
  tid.py lunchfilter [tid]     Alfred Script Filter for `lunch`/`lu`
  tid.py editfilter [tekst]    Alfred Script Filter for `edit`
  tid.py start <prosjekt> [tid]
  tid.py stop [tid]
  tid.py pause [prosjekt] [tid]   pause det som kjører; «pause» igjen fortsetter
  tid.py pausefilter [tekst]   Alfred Script Filter for `pause`
  tid.py lunch [tid]           = start lunsjprosjektet (env lunch_project, standard «intern»)
  tid.py edit <prosjekt> <fra> - <til>   rett dagens rad, f.eks. «edit acme 815 - 11»
  tid.py do <fritekst>         «start acme 8», «Globex 0930», «lu», «stop 1700», «edit acme 815-11»
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

DEFAULT_PATH = "~/Documents/Obsidian/Vault/Calendar/Records/Timetracking.md"
ARCHIVED = re.compile(r"[-_ ](archived|arkivert)$")
HEADING = re.compile(r"^##\s+(.+?)\s*$")
ROW = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(\d{1,2}:\d{2})\s*\|\s*(\d{1,2}:\d{2})\s*\|\s*(\d+):(\d{2})\s*\|")
SUM_ROW = re.compile(r"^\|\s*\d{4}-\d{2}-\d{2}\s*\|\s*\*\*Sum\*\*")
TABLE_HEAD = "| Dato | Start | Slutt | Tid |\n| --- | --- | --- | --- |\n"
MIN_SECONDS = 60  # økter under ett minutt (feiltrykk, raskt bytte) logges ikke

TEMPLATE = """\
---
created:
modified:
aktiv:
startet:
pauset:
---
# Timetracking

Dagssummen per prosjekt rundes opp til nærmeste kvarter. Føres fra Alfred: `start <prosjekt> [tid]` starter (og avslutter det som kjører), `lu`/`lunch`
starter lunsjprosjektet, `pause` pauser/fortsetter, `stop [tid]` stopper, `edit <prosjekt> 815 - 11` retter dagens rad.
Tid er valgfri: 8, 815, 0930, 13:45.
Hvert prosjekt er en overskrift under. Gi et prosjekt navnet `<navn>-archived` for å skjule
det fra forslagene, eller slett overskriften for å fjerne det.
"""


class Feil(Exception):
    """Ugyldig input eller konflikt – vises til brukeren, ingenting lagres."""


def note_path() -> Path:
    return Path(os.environ.get("timetracking_path") or DEFAULT_PATH).expanduser()


def normalize(name: str) -> str:
    return " ".join(name.strip().lower().split())


LUNCH_PROJECT = normalize(os.environ.get("lunch_project") or "intern")


def now() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


# ---------- klokkeslett ----------

def parse_time(tok: str) -> time | None:
    tok = tok.strip()
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", tok)
    if m:
        h, mm = int(m.group(1)), int(m.group(2))
    elif re.fullmatch(r"\d{1,4}", tok):
        n = len(tok)
        if n == 1:
            h, mm = int(tok), 0
        elif n == 2:
            v = int(tok)
            h, mm = (v, 0) if v <= 23 else (int(tok[0]), int(tok[1]) * 10)
        elif n == 3:
            h, mm = int(tok[0]), int(tok[1:])
        else:
            h, mm = int(tok[:2]), int(tok[2:])
    else:
        return None
    if h > 23 or mm > 59:
        return None
    return time(h, mm)


def split_time(text: str) -> tuple[str, time | None]:
    """«acme 0800» → ("acme", 08:00). Et ord som ikke er et klokkeslett blir stående."""
    words = text.split()
    if words:
        t = parse_time(words[-1])
        if t is not None:
            return " ".join(words[:-1]), t
    return text, None


def at_today(t: time | None) -> datetime | None:
    if t is None:
        return None
    dt = datetime.combine(date.today(), t)
    if dt > now() + timedelta(minutes=1):
        raise Feil(f"{t:%H:%M} er fram i tid")
    return dt


# ---------- notatet ----------

class Note:
    def __init__(self, path: Path):
        self.path = path
        self.text = path.read_text(encoding="utf-8") if path.exists() else TEMPLATE

    # frontmatter
    def _fm(self) -> tuple[int, int] | None:
        if not self.text.startswith("---\n"):
            return None
        end = self.text.find("\n---", 4)
        return (4, end) if end != -1 else None

    def get(self, key: str) -> str:
        span = self._fm()
        if not span:
            return ""
        m = re.search(rf"^{key}:[ \t]*(.*)$", self.text[span[0]:span[1]], re.M)
        return m.group(1).strip().strip('"') if m else ""

    def set(self, key: str, value: str) -> None:
        span = self._fm()
        if not span:
            self.text = f"---\n{key}: {value}\n---\n" + self.text
            return
        fm = self.text[span[0]:span[1]]
        line = f"{key}: {value}".rstrip()
        if re.search(rf"^{key}:.*$", fm, re.M):
            fm = re.sub(rf"^{key}:.*$", lambda _: line, fm, count=1, flags=re.M)
        else:
            fm = fm.rstrip("\n") + f"\n{line}"
        self.text = self.text[:span[0]] + fm + self.text[span[1]:]

    # rader
    def rows(self):
        """(linjenr, prosjekt, dato, start, slutt, sekunder) for hver øktrad."""
        current = None
        in_code = False
        for i, line in enumerate(self.text.split("\n")):
            if line.startswith("```"):
                in_code = not in_code
            if in_code:
                continue
            m = HEADING.match(line)
            if m:
                current = normalize(m.group(1))
                continue
            if current:
                r = ROW.match(line)
                if r:
                    d = date.fromisoformat(r.group(1))
                    yield (i, current, d, _clock(d, r.group(2)), _clock(d, r.group(3)),
                           int(r.group(4)) * 3600 + int(r.group(5)) * 60)

    def projects(self) -> dict[str, list[tuple[date, int]]]:
        """{navn: [(dato, sekunder), …]} i rekkefølgen de står i notatet."""
        out: dict[str, list[tuple[date, int]]] = {}
        for line in self.text.split("\n"):
            m = HEADING.match(line)
            if m:
                out.setdefault(normalize(m.group(1)), [])
        for _, p, d, _, _, secs in self.rows():
            out[p].append((d, secs))
        return out

    def _section(self, lines: list[str], project: str) -> tuple[int, int] | None:
        for i, line in enumerate(lines):
            m = HEADING.match(line)
            if m and normalize(m.group(1)) == project:
                end = len(lines)
                for j in range(i + 1, len(lines)):
                    if lines[j].startswith("## ") or lines[j].startswith("# "):
                        end = j
                        break
                return i, end
        return None

    def add_row(self, project: str, row: str) -> None:
        lines = self.text.split("\n")
        sec = self._section(lines, project)
        if sec is None:
            self.text = self.text.rstrip("\n") + f"\n\n## {project}\n\n{TABLE_HEAD}{row}\n"
            return
        start, end = sec
        last_row = None
        for j in range(start + 1, end):
            if lines[j].startswith("|"):
                last_row = j
        if last_row is not None:
            lines.insert(last_row + 1, row)
        else:
            insert = start + 1
            block = ["", *TABLE_HEAD.rstrip("\n").split("\n"), row]
            if end > start + 1 and lines[start + 1].strip() == "":
                block = block[1:]
                insert = start + 2
            lines[insert:insert] = block
        self.text = "\n".join(lines)

    def ensure_heading(self, project: str) -> None:
        if project not in self.projects():
            self.text = self.text.rstrip("\n") + f"\n\n## {project}\n\n{TABLE_HEAD.rstrip()}\n"

    def trim_overlaps(self, t: datetime) -> list[str]:
        """Rader i dag som slutter etter t, kuttes til t. En rad som *starter* etter t er en
        konflikt som må rettes for hånd – da kastes Feil og ingenting endres."""
        lines = self.text.split("\n")
        notes = []
        for i, p, d, s, e, _ in list(self.rows()):
            if d != t.date() or e <= t:
                continue
            if s >= t:
                raise Feil(f"{t:%H:%M} overlapper med {p} {s:%H:%M}–{e:%H:%M} – rett i Obsidian")
            secs = int((t - s).total_seconds())
            lines[i] = _row(p, d, s, t, secs) if secs >= MIN_SECONDS else None
            notes.append(f"{p} kuttet til {t:%H:%M}")
        self.text = "\n".join(line for line in lines if line is not None)
        return notes

    def refresh_sums(self) -> None:
        """Én sumrad nederst i hver dag per prosjekt, rundet opp til nærmeste kvarter (t:mm og desimal)."""
        lines = [line for line in self.text.split("\n") if not SUM_ROW.match(line)]
        self.text = "\n".join(lines)
        last: dict[tuple[str, date], int] = {}
        total: dict[tuple[str, date], int] = {}
        for i, p, d, _, _, secs in self.rows():
            last[(p, d)] = i
            total[(p, d)] = total.get((p, d), 0) + secs
        for (p, d), i in sorted(last.items(), key=lambda kv: kv[1], reverse=True):
            q = round_up(total[(p, d)])
            lines.insert(i + 1, f"| {d.isoformat()} | **Sum** | | **{fmt(q)}** ({dec(q)} t) |")
        self.text = "\n".join(lines)

    def stamp(self) -> None:
        """`created` (dato, settes én gang) og `modified` (dato og tid) øverst i frontmatter."""
        created = self.get("created") or date.today().isoformat()
        self.set("created", "")
        self.set("modified", "")
        span = self._fm()
        fm = self.text[span[0]:span[1]]
        fm = "\n".join(line for line in fm.split("\n") if not re.match(r"^(created|modified):", line))
        top = f"created: {created}\nmodified: {now():%Y-%m-%dT%H:%M}"
        fm = top + ("\n" + fm if fm.strip() else "")
        self.text = self.text[:span[0]] + fm + self.text[span[1]:]

    def save(self) -> None:
        self.refresh_sums()
        self.stamp()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".timetracking-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(self.text if self.text.endswith("\n") else self.text + "\n")
        os.replace(tmp, self.path)


def _clock(d: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    if h == 24:
        return datetime.combine(d + timedelta(days=1), time(0, m))
    return datetime.combine(d, time(h, m))


def _row(project: str, d: date, s: datetime, e: datetime, secs: int) -> str:
    end_label = "24:00" if e.date() > d else e.strftime("%H:%M")
    return f"| {d.isoformat()} | {s:%H:%M} | {end_label} | {fmt(secs)} |"


# ---------- logikk ----------

QUARTER = 15  # dagssummen per prosjekt rundes opp til nærmeste kvarter


def round_up(seconds: int) -> int:
    """Opp til nærmeste kvarter: 1:32 → 1:45, 1:30 → 1:30, 0:01 → 0:15."""
    m = int(round(seconds / 60))
    return -(-m // QUARTER) * QUARTER * 60


def fmt(seconds: int) -> str:
    m = int(round(seconds / 60))
    return f"{m // 60}:{m % 60:02d}"


def dec(seconds: int) -> str:
    return f"{round(seconds / 60) / 60:.2f}".replace(".", ",")


def running(note: Note) -> tuple[str, datetime] | None:
    name, started = normalize(note.get("aktiv")), note.get("startet")
    if not name or not started:
        return None
    try:
        return name, datetime.fromisoformat(started).replace(second=0, microsecond=0)
    except ValueError:
        return None


def close_running(note: Note, end: datetime) -> str | None:
    """Skriver rad(er) for økta som kjører (deles ved midnatt) og nullstiller frontmatter."""
    r = running(note)
    note.set("aktiv", "")
    note.set("startet", "")
    if not r:
        return None
    name, start = r
    if end < start:
        return f"{name} forkastet (startet {start:%H:%M}, etter {end:%H:%M})"
    if (end - start).total_seconds() < MIN_SECONDS:
        return f"{name}: under ett minutt, ikke logget"
    total = 0
    seg = start
    while seg < end:
        midnight = datetime.combine(seg.date() + timedelta(days=1), time())
        seg_end = min(end, midnight)
        secs = int((seg_end - seg).total_seconds())
        note.add_row(name, _row(name, seg.date(), seg, seg_end, secs))
        total += secs
        seg = seg_end
    return f"{name} {start:%H:%M}–{end:%H:%M} ({fmt(total)})"


def start(text: str) -> str:
    name, t = split_time(text)
    project = normalize(name)
    if not project:
        raise Feil("Skriv et prosjektnavn: start <prosjekt> [tid]")
    note = Note(note_path())
    at = at_today(t)
    when = at or now()
    r = running(note)

    if r and r[0] == project:
        if at is None:
            return f"{project} kjører allerede (siden {r[1]:%H:%M})"
        trimmed = note.trim_overlaps(when)
        note.set("startet", when.isoformat())
        note.save()
        return f"▶ {project} starttid flyttet til {when:%H:%M}" + _extra(trimmed)

    stopped = close_running(note, when)
    trimmed = note.trim_overlaps(when)
    resumed = normalize(note.get("pauset")) == project
    note.set("pauset", "")
    note.ensure_heading(project)
    note.set("aktiv", project)
    note.set("startet", when.isoformat())
    note.save()
    msg = f"▶ {project} {'fortsetter' if resumed else 'fra'} {when:%H:%M}"
    if stopped:
        msg += f" · avsluttet {stopped}"
    return msg + _extra(trimmed)


def lunch(text: str) -> str:
    _, t = split_time(text)
    return "🍽 Lunsj · " + start(f"{LUNCH_PROJECT} {t:%H:%M}" if t else LUNCH_PROJECT)


def stop(text: str = "") -> str:
    _, t = split_time(text)
    note = Note(note_path())
    r = running(note)
    paused = normalize(note.get("pauset"))
    if not r and paused:
        note.set("pauset", "")
        note.save()
        return f"■ {paused} var på pause, nå stoppet\n{day_summary(note)}"
    if not r:
        return "Ingen timer kjører"
    end = at_today(t) or now()
    if end < r[1]:
        raise Feil(f"{end:%H:%M} er før {r[0]} startet ({r[1]:%H:%M})")
    msg = close_running(note, end)
    note.save()
    return f"■ Stoppet {msg}\n{day_summary(note)}"


def pause(text: str = "") -> str:
    """Pauser prosjektet som kjører (raden avsluttes), eller fortsetter det som er pauset."""
    name, t = split_time(text)
    want = normalize(name)
    note = Note(note_path())
    r = running(note)
    paused = normalize(note.get("pauset"))
    if r:
        if want and want not in r[0]:
            raise Feil(f"{r[0]} kjører, ikke {want}")
        end = at_today(t) or now()
        if end < r[1]:
            raise Feil(f"{end:%H:%M} er før {r[0]} startet ({r[1]:%H:%M})")
        closed = close_running(note, end)
        note.set("pauset", r[0])
        note.save()
        return f"⏸ {r[0]} på pause fra {end:%H:%M} · {closed} · «pause» igjen fortsetter"
    if paused:
        if want and want not in paused:
            raise Feil(f"{paused} er på pause, ikke {want}")
        return start(f"{paused} {t:%H:%M}" if t else paused)
    raise Feil("Ingen timer kjører eller er på pause")


def day_summary(note: Note, d: date | None = None) -> str:
    d = d or date.today()
    per: dict[str, int] = {}
    for _, p, rd, _, _, secs in note.rows():
        if rd == d:
            per[p] = per.get(p, 0) + secs
    if not per:
        return "Ingenting ført i dag"
    per = {p: round_up(s) for p, s in per.items()}
    parts = [f"{p} {fmt(s)} ({dec(s)})" for p, s in per.items()]
    tot = sum(per.values())
    return f"I dag: {' · '.join(parts)} · totalt {fmt(tot)} ({dec(tot)} t)"


def _extra(notes: list[str]) -> str:
    return (" · " + ", ".join(notes)) if notes else ""


# ---------- rette dagens rader ----------

def parse_range(text: str) -> tuple[str, time, time]:
    """«acme 815 - 11» / «acme 815-11» / «acme 815 11» → ("acme", 08:15, 11:00)."""
    m = re.match(r"^(.*?)\s+(\S+?)\s*-\s*(\S+)\s*$", text.strip())
    if m and parse_time(m.group(2)) and parse_time(m.group(3)):
        return m.group(1), parse_time(m.group(2)), parse_time(m.group(3))
    words = text.split()
    if len(words) >= 3 and parse_time(words[-2]) and parse_time(words[-1]):
        return " ".join(words[:-2]), parse_time(words[-2]), parse_time(words[-1])
    raise Feil("Bruk: edit <prosjekt> <fra> - <til>, f.eks. «edit acme 815 - 11»")


def resolve_project(note: Note, name: str) -> str:
    """Eksakt navn, ellers et entydig delnavn blant prosjekter som ikke er arkivert."""
    q = normalize(name)
    projects = note.projects()
    if q in projects:
        return q
    hits = [p for p in projects if q and q in p and not ARCHIVED.search(p)]
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise Feil(f"«{q}» passer flere: {', '.join(hits)}")
    raise Feil(f"Fant ikke prosjektet «{q}»")


def pick_row(rows, s: datetime, e: datetime):
    """Raden som overlapper mest med s–e; ellers den som starter nærmest s."""
    def overlap(r):
        return max(0, (min(r[4], e) - max(r[3], s)).total_seconds())
    best = max(rows, key=lambda r: (overlap(r), -abs((r[3] - s).total_seconds())))
    return best


def plan_edit(note: Note, text: str):
    name, a, b = parse_range(text)
    project = resolve_project(note, name)
    today = date.today()
    s, e = datetime.combine(today, a), datetime.combine(today, b)
    if e <= s:
        raise Feil(f"Slutt {e:%H:%M} må være etter start {s:%H:%M}")
    if e > now() + timedelta(minutes=1):
        raise Feil(f"{e:%H:%M} er fram i tid")
    rows = [r for r in note.rows() if r[1] == project and r[2] == today]
    old = pick_row(rows, s, e) if rows else None
    return project, s, e, old


def edit(text: str) -> str:
    note = Note(note_path())
    project, s, e, old = plan_edit(note, text)
    secs = int((e - s).total_seconds())
    new = _row(project, s.date(), s, e, secs)
    if old:
        lines = note.text.split("\n")
        lines[old[0]] = new
        note.text = "\n".join(lines)
        msg = f"✎ {project} {old[3]:%H:%M}–{old[4]:%H:%M} → {s:%H:%M}–{e:%H:%M} ({fmt(secs)})"
    else:
        note.add_row(project, new)
        msg = f"✎ {project} {s:%H:%M}–{e:%H:%M} ({fmt(secs)}) lagt til"
    note.save()
    return msg + "\n" + day_summary(note)


def do(text: str) -> str:
    words = text.split()
    low = [w.lower() for w in words]
    if not low:
        raise Feil("Bruk «start <prosjekt> [tid]», «<prosjekt> [tid]», «lu [tid]» eller «stop [tid]»")
    if low[0] in ("stop", "stopp"):
        return stop(" ".join(words[1:]))
    if low[0] in ("pause", "fortsett"):
        return pause(" ".join(words[1:]))
    if low[0] in ("lu", "lunch", "lunsj"):
        return lunch(" ".join(words[1:]))
    if low[0] == "start":
        return start(" ".join(words[1:]))
    if low[0] in ("edit", "rett"):
        return edit(" ".join(words[1:]))
    # «Globex start 0930» / «Globex start» / «Globex 0930»
    if "start" in low[1:]:
        k = low.index("start", 1)
        return start(" ".join(words[:k] + words[k + 1:]))
    name, t = split_time(text)
    if t is not None and name:
        return start(text)
    raise Feil("Forstod ikke – bruk «start <prosjekt> [tid]», «<prosjekt> 0930», «lu» eller «stop»")


# ---------- Alfred ----------

def totals(entries: list[tuple[date, int]], extra: int = 0) -> tuple[int, int]:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    d = sum(s for dt, s in entries if dt == today) + extra
    w = sum(s for dt, s in entries if dt >= week_start) + extra
    return d, w


def alfred(items: list[dict]) -> None:
    print(json.dumps({"items": items}, ensure_ascii=False))


def _time_or_error(text: str) -> tuple[str, datetime | None, dict | None]:
    name, t = split_time(text)
    try:
        return name, at_today(t), None
    except Feil as e:
        return name, None, {"title": str(e), "subtitle": "Tid må være nå eller tidligere i dag", "valid": False}


def start_filter(query: str) -> None:
    note = Note(note_path())
    name, at, err = _time_or_error(query)
    if err:
        return alfred([err])
    if at:
        probe = Note(note.path)
        probe.text = note.text
        try:
            probe.trim_overlaps(at)
        except Feil as e:
            return alfred([{"title": str(e), "subtitle": "Velg et annet tidspunkt", "valid": False}])
    q = normalize(name)
    tsuf = f" {at:%H:%M}" if at else ""
    projects = note.projects()
    r = running(note)
    cur = now()

    paused = normalize(note.get("pauset"))

    def last_used(item):
        n, entries = item
        if r and r[0] == n:
            return date.max
        if n == paused:
            return date.max - timedelta(days=1)
        return max((dt for dt, _ in entries), default=date.min)

    items = []
    for n, entries in sorted(projects.items(), key=last_used, reverse=True):
        if ARCHIVED.search(n) or (q and q not in n):
            continue
        is_running = r is not None and r[0] == n
        live = int((cur - r[1]).total_seconds()) if is_running else 0
        d, w = totals(entries, live)
        stats = f"i dag {fmt(d)} · denne uka {fmt(w)}"
        if is_running and at:
            title, sub, valid = f"● {n}", f"Flytt starttid fra {r[1]:%H:%M} til {at:%H:%M} · {stats}", True
        elif is_running:
            title, sub, valid = f"● {n}", f"Kjører siden {r[1]:%H:%M} · {stats}", False
        elif n == paused:
            title, valid = f"⏸ {n}", True
            sub = f"På pause · Enter fortsetter {(at or cur):%H:%M} · {stats}"
        else:
            title, valid = n, True
            sub = (f"Fra {at:%H:%M}" if at else "Start nå") + (f" · avslutter {r[0]} {(at or cur):%H:%M}" if r else "") + f" · {stats}"
        items.append({"uid": n, "title": title, "subtitle": sub, "arg": n + tsuf,
                      "autocomplete": n + " ", "valid": valid})
    if q and q not in projects:
        items.append({
            "title": f"Nytt prosjekt: {q}" + (f" fra {at:%H:%M}" if at else ""),
            "subtitle": "Legges til i Timetracking og startes" + (f" · avslutter {r[0]}" if r else ""),
            "arg": q + tsuf,
        })
    if not items:
        items.append({"title": "Ingen prosjekter ennå", "subtitle": "Skriv et navn (og evt. tid, f.eks. «acme 8»)", "valid": False})
    alfred(items)


def stop_filter(query: str) -> None:
    note = Note(note_path())
    _, at, err = _time_or_error(query)
    if err:
        return alfred([err])
    r = running(note)
    if not r:
        return alfred([{"title": "Ingen timer kjører", "subtitle": day_summary(note), "valid": False}])
    name, started = r
    end = at or now()
    if end < started:
        return alfred([{"title": f"{end:%H:%M} er før {name} startet ({started:%H:%M})", "valid": False}])
    secs = int((end - started).total_seconds())
    d, _ = totals(note.projects().get(name, []), secs)
    alfred([{"title": f"Stopp {name}" + (f" kl. {at:%H:%M}" if at else ""),
             "subtitle": f"{started:%H:%M}–{end:%H:%M} ({fmt(secs)}) · i dag {fmt(d)} ({dec(d)} t)",
             "arg": f"{at:%H:%M}" if at else ""}])


def lunch_filter(query: str) -> None:
    note = Note(note_path())
    _, at, err = _time_or_error(query)
    if err:
        return alfred([err])
    r = running(note)
    when = at or now()
    if r and r[0] == LUNCH_PROJECT and not at:
        return alfred([{"title": f"Lunsj/{LUNCH_PROJECT} kjører allerede", "subtitle": f"Siden {r[1]:%H:%M}", "valid": False}])
    if at:
        probe = Note(note.path)
        probe.text = note.text
        try:
            probe.trim_overlaps(at)
        except Feil as e:
            return alfred([{"title": str(e), "subtitle": "Velg et annet tidspunkt", "valid": False}])
    sub = f"Starter {LUNCH_PROJECT} {when:%H:%M}" + (f" · avslutter {r[0]}" if r and r[0] != LUNCH_PROJECT else "")
    alfred([{"title": "Lunsj" + (f" fra {at:%H:%M}" if at else ""), "subtitle": sub,
             "arg": f"{at:%H:%M}" if at else ""}])


def edit_filter(query: str) -> None:
    note = Note(note_path())
    today = date.today()
    try:
        project, s, e, old = plan_edit(note, query)
    except Feil as err:
        # Fortsatt underveis i skrivingen: vis prosjektene med dagens rader.
        name = normalize(re.split(r"\s+\d", query.strip(), maxsplit=1)[0]) if query.strip() else ""
        items = []
        for p, entries in note.projects().items():
            if ARCHIVED.search(p) or (name and name not in p):
                continue
            rows = [r for r in note.rows() if r[1] == p and r[2] == today]
            sub = ("I dag: " + ", ".join(f"{r[3]:%H:%M}–{r[4]:%H:%M}" for r in rows)) if rows else "Ingen rad i dag – edit legger til en"
            items.append({"title": p, "subtitle": sub, "autocomplete": p + " ", "valid": False})
        if query.strip() and any(ch.isdigit() for ch in query):
            items.insert(0, {"title": str(err), "subtitle": "edit <prosjekt> <fra> - <til>", "valid": False})
        return alfred(items or [{"title": "Ingen prosjekter", "valid": False}])
    secs = int((e - s).total_seconds())
    if old:
        title = f"{project}: {old[3]:%H:%M}–{old[4]:%H:%M} → {s:%H:%M}–{e:%H:%M}"
    else:
        title = f"{project}: legg til {s:%H:%M}–{e:%H:%M}"
    alfred([{"title": title, "subtitle": f"{fmt(secs)} ({dec(secs)} t) · bare dagens rader kan rettes her", "arg": query}])


def pause_filter(query: str) -> None:
    note = Note(note_path())
    name, at, err = _time_or_error(query)
    if err:
        return alfred([err])
    r = running(note)
    paused = normalize(note.get("pauset"))
    when = at or now()
    if r:
        secs = int((when - r[1]).total_seconds())
        if when < r[1]:
            return alfred([{"title": f"{when:%H:%M} er før {r[0]} startet ({r[1]:%H:%M})", "valid": False}])
        return alfred([{"title": f"Pause {r[0]}" + (f" fra {at:%H:%M}" if at else ""),
                        "subtitle": f"Avslutter økta {r[1]:%H:%M}–{when:%H:%M} ({fmt(secs)}) · «pause» igjen fortsetter",
                        "arg": query}])
    if paused:
        return alfred([{"title": f"Fortsett {paused}" + (f" fra {at:%H:%M}" if at else ""),
                        "subtitle": "Ny økt starter " + f"{when:%H:%M}", "arg": query}])
    alfred([{"title": "Ingen timer kjører eller er på pause", "subtitle": "Start med «start <prosjekt>»", "valid": False}])


def main(argv: list[str]) -> None:
    cmd, rest = (argv[0], " ".join(argv[1:])) if argv else ("", "")
    filters = {"filter": start_filter, "stopfilter": stop_filter, "lunchfilter": lunch_filter, "editfilter": edit_filter, "pausefilter": pause_filter}
    actions = {"start": start, "stop": stop, "lunch": lunch, "edit": edit, "pause": pause, "do": do}
    if cmd in filters:
        filters[cmd](rest)
    elif cmd in actions:
        try:
            print(actions[cmd](rest))
        except Feil as e:
            print(f"⚠ {e}")
            sys.exit(0)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
