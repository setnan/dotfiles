#!/usr/bin/env python3
"""Alfred: oppsummer utklippstavlen med Claude og skriv resultatet til en tekstfil.

`sum [ekstra instruks]` leser utklippstavlen, ber Claude (standard Opus) om det
viktigste, en forenkling og, hvis innholdet er abstrakt, en kort analogi, og
skriver svaret til fila i `sum_path` (Alfred-variabel). Fila overskrives hver
gang: den er et midlertidig dokument brukeren har åpent og sjekker fortløpende.
Mens Claude jobber står det en statuslinje i fila, så man ser at noe skjer.

Claude får i tillegg et kontekstbrief om hva brukeren jobber med, hentet fra
Claude-aktiviteten på maskinen de siste `sum_context`-timene (standard 72, 0 =
av): arbeidsloggen i ~/Logs, claude-mem-databasen (observasjoner og
øktsammendrag) og Claude Code sin history.jsonl. Briefen bygges i minnet ved
hver kjøring og skrives aldri til disk eller repo.

Skriver én linje til stdout (til Alfred-varselet). Test uten utklippstavle:
    echo "tekst" | python3 summarize.py --stdin [instruks]
    python3 summarize.py --show-context     # bare briefen, til kontroll
"""
import datetime as dt
import json
import os
import pathlib
import sqlite3
import subprocess
import sys

DEFAULT_PATH = "~/Documents/Summary/sum.txt"
DEFAULT_MODEL = "opus"
TIMEOUT = 240
MAX_CHARS = 120_000  # ca. 30k tokens; mer enn nok for en artikkel

SYSTEM = (
    "Du får en tekst brukeren har kopiert. Skriv et sammendrag på norsk bokmål, som ren "
    "tekst med enkle overskrifter i store bokstaver (ingen markdown-tegn som #, * eller `). "
    "Struktur:\n"
    "DET VIKTIGSTE\n3–6 korte punkter med bindestrek. Konkret, ingen fyll.\n\n"
    "FORENKLET\n2–4 setninger som forklarer kjernen slik at en oppvakt 15-åring forstår det. "
    "Bytt ut sjargong med vanlige ord.\n\n"
    "ANALOGI\nBare hvis innholdet er abstrakt eller teknisk: én kort hverdagsanalogi der "
    "problemet og løsningen forklares (3–5 setninger). Er innholdet konkret, dropp hele "
    "seksjonen.\n\n"
    "Ingen innledning, ingen avslutning, ingen kommentarer om teksten. Er teksten kode, en "
    "feilmelding eller en logg: si hva den gjør eller hva som er galt, og hva man bør gjøre. "
    "Svar på samme språk som brukerens eventuelle ekstra instruks ber om, ellers norsk.\n\n"
    "Du kan få et KONTEKSTBRIEF om hva brukeren jobber med for tiden (fra Claude-aktivitet på "
    "maskinen). Bruk det til å velge hva som er viktigst og til ordvalg. Henger teksten tydelig "
    "sammen med noe i briefen, avslutt med seksjonen\nRELEVANS FOR DEG\n1–3 setninger om "
    "hvordan dette angår det brukeren holder på med. Ellers utelat seksjonen. Gjengi aldri "
    "briefen, og ikke oppsummer briefen i stedet for teksten."
)

LOGS = pathlib.Path(os.path.expanduser("~/Logs"))
CLAUDE_MEM_DB = pathlib.Path(os.path.expanduser("~/.claude-mem/claude-mem.db"))
HISTORY = pathlib.Path(os.path.expanduser("~/.claude/history.jsonl"))
CONTEXT_MAX = 7000  # tegn


def _clip(text, n):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _section(md, heading):
    """Innholdet under `## <heading>` i en loggoppføring."""
    key = f"## {heading}"
    if key not in md:
        return ""
    body = md.split(key, 1)[1]
    body = body.split("\n## ", 1)[0]
    return body.strip()


def context_worklog(since):
    lines = []
    if not LOGS.is_dir():
        return lines
    entries = []
    for f in LOGS.rglob("*.md"):
        if "/." in str(f) or f.stat().st_mtime < since.timestamp():
            continue
        entries.append(f)
    for f in sorted(entries, key=lambda f: f.stat().st_mtime, reverse=True)[:12]:
        md = f.read_text(encoding="utf-8", errors="replace")
        head = md.split("---", 2)
        meta = {}
        if len(head) >= 3:
            for line in head[1].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
        goal = _clip(_section(md, "Mål"), 220)
        done = _clip(_section(md, "Gjort"), 300)
        left = _clip(_section(md, "Gjenstår"), 160)
        lines.append(f"- [{meta.get('dato', '')[:16]}] {meta.get('prosjekt', '?')}: {meta.get('tittel', f.stem)}"
                     + (f"\n  Mål: {goal}" if goal and goal != "–" else "")
                     + (f"\n  Gjort: {done}" if done and done != "–" else "")
                     + (f"\n  Gjenstår: {left}" if left and left != "–" else ""))
    return lines


def context_claude_mem(since):
    out = []
    if not CLAUDE_MEM_DB.is_file():
        return out
    try:
        db = sqlite3.connect(f"file:{CLAUDE_MEM_DB}?mode=ro", uri=True)
        epoch = int(since.timestamp() * 1000)
        rows = db.execute(
            "select project, request, completed, next_steps from session_summaries "
            "where created_at_epoch >= ? order by created_at_epoch desc limit 8", (epoch,)).fetchall()
        for project, request, completed, nxt in rows:
            out.append(f"- {project}: {_clip(request, 160)}"
                       + (f" | gjort: {_clip(completed, 160)}" if completed else "")
                       + (f" | neste: {_clip(nxt, 120)}" if nxt else ""))
        rows = db.execute(
            "select project, type, title, subtitle from observations "
            "where created_at_epoch >= ? order by created_at_epoch desc limit 30", (epoch,)).fetchall()
        for project, typ, title, subtitle in rows:
            out.append(f"- ({project}, {typ}) {_clip(title, 110)}" + (f": {_clip(subtitle, 120)}" if subtitle else ""))
    except sqlite3.Error:
        pass
    return out


def context_history(since):
    out = []
    if not HISTORY.is_file():
        return out
    try:
        tail = HISTORY.read_bytes()[-400_000:].decode("utf-8", errors="replace").splitlines()
    except OSError:
        return out
    seen = set()
    for line in reversed(tail):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        ts = d.get("timestamp", 0) / 1000
        if ts < since.timestamp():
            break
        text = _clip(d.get("display", ""), 140)
        if not text or text.startswith("/") or text in seen:
            continue
        seen.add(text)
        out.append(f"- {pathlib.Path(d.get('project', '')).name or '?'}: {text}")
        if len(out) >= 25:
            break
    return out


def context_brief(hours):
    if hours <= 0:
        return ""
    since = dt.datetime.now() - dt.timedelta(hours=hours)
    parts = []
    # Hver kilde får sin egen ramme, så ikke arbeidsloggen alene fyller briefen.
    for title, lines, budget in (
        ("Arbeidslogg (økter med Claude Code, nyeste først)", context_worklog(since), 3200),
        ("Claude-minne (øktsammendrag og observasjoner)", context_claude_mem(since), 2400),
        ("Siste forespørsler til Claude Code", context_history(since), 1400),
    ):
        if not lines:
            continue
        body = ""
        for line in lines:
            if len(body) + len(line) + 1 > budget:
                break
            body += line + "\n"
        if body:
            parts.append(f"{title}:\n{body.rstrip()}")
    if not parts:
        return ""
    brief = f"KONTEKSTBRIEF – brukerens Claude-aktivitet siste {hours} timer\n\n" + "\n\n".join(parts)
    return brief if len(brief) <= CONTEXT_MAX else brief[:CONTEXT_MAX] + "\n…(kuttet)"


def find_claude():
    for cand in (
        os.environ.get("CLAUDE_BIN", ""),
        os.path.expanduser("~/.local/bin/claude"),
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ):
        if cand and os.access(cand, os.X_OK):
            return cand
    return "claude"


def target():
    raw = os.environ.get("sum_path", "").strip() or DEFAULT_PATH
    p = pathlib.Path(os.path.expanduser(raw))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def clipboard():
    r = subprocess.run(["/usr/bin/pbpaste"], capture_output=True, text=True)
    return r.stdout


def write(path, header, body):
    path.write_text(f"{header}\n{'─' * 60}\n{body.rstrip()}\n", encoding="utf-8")


def main():
    args = sys.argv[1:]
    try:
        hours = int(os.environ.get("sum_context", "").strip() or 72)
    except ValueError:
        hours = 72
    if "--show-context" in args:
        print(context_brief(hours) or "(ingen kontekst)")
        return 0
    use_stdin = "--stdin" in args
    extra = " ".join(a for a in args if a != "--stdin").strip()
    text = (sys.stdin.read() if use_stdin else clipboard()).strip()
    if not text:
        print("Utklippstavlen er tom")
        return 1
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
        truncated = f" (kuttet til {MAX_CHARS} tegn)"
    else:
        truncated = ""

    path = target()
    model = os.environ.get("sum_model", "").strip() or DEFAULT_MODEL
    started = dt.datetime.now()
    stamp = started.strftime("%Y-%m-%d %H:%M")
    first = text.splitlines()[0][:70]
    write(path, f"SAMMENDRAG · {stamp} · jobber … ({len(text)} tegn{truncated}, {model})",
          f"Kilde: {first}\n\nClaude skriver sammendraget nå. Fila oppdateres når det er klart.")

    prompt = "TEKSTEN SOM SKAL OPPSUMMERES:\n" + text
    if extra:
        prompt = f"Ekstra instruks fra brukeren: {extra}\n\n" + prompt
    brief = context_brief(hours)
    if brief:
        prompt = brief + "\n\n" + prompt
    cmd = [
        find_claude(), "-p", "--tools", "", "--no-session-persistence", "--strict-mcp-config",
        "--setting-sources", "", "--disable-slash-commands", "--model", model,
        "--system-prompt", SYSTEM, prompt,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        write(path, f"SAMMENDRAG · {stamp} · FEIL", f"Claude svarte ikke innen {TIMEOUT // 60} minutter.")
        print("Claude svarte ikke i tide")
        return 1
    except OSError as e:
        write(path, f"SAMMENDRAG · {stamp} · FEIL", f"Fant ikke claude: {e}")
        print("Fant ikke claude-kommandoen")
        return 1

    out = r.stdout.strip()
    if r.returncode != 0 or not out:
        err = out or r.stderr.strip() or f"claude feilet (kode {r.returncode})"
        write(path, f"SAMMENDRAG · {stamp} · FEIL", err)
        print("Sammendraget feilet, se fila")
        return 1

    secs = (dt.datetime.now() - started).total_seconds()
    write(path, f"SAMMENDRAG · {stamp} · {len(text)} tegn inn{truncated} · {model} · {secs:.0f} s", out)
    print(f"Sammendrag klart ({secs:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
