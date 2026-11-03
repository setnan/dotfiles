#!/usr/bin/env python3
"""Alfred: oppsummer utklippstavlen med Claude, kjapt og «dummet ned», til HTML + tekst.

`sum [ekstra instruks]` leser utklippstavlen og ber Claude (standard Sonnet, for
fart) om et sammendrag man forstår at a glance: det viktigste, en forenkling
nesten alle skjønner, og en analogi. Finnes det en analogi i teksten fra før,
gjengis den; ellers lages en hvis innholdet er abstrakt.

Resultatet skrives til `sum_html` (sum.html), en ferdig stilet side (Catppuccin,
følger lys/mørk) som laster seg selv på nytt hvert sekund, så et åpent vindu
alltid viser siste sammendrag. Fila overskrives først når svaret er klart (ingen
«jobber»-status, brukeren vil bare ha resultatet). Er `sum_path` satt, skrives
samme innhold også som Markdown dit (valgfritt, av som standard).
`sum vis` åpner HTML-sida i et eget nettleservindu (Brave/Chrome app-modus).

Claude får i tillegg et lite kontekstbrief om hva brukeren jobber med, hentet fra
Claude-aktiviteten på maskinen de siste `sum_context`-timene (standard 24, 0 =
av): arbeidsloggen i ~/Logs, claude-mem-databasen og Claude Code sin
history.jsonl. Briefen bygges i minnet ved hver kjøring og lagres aldri.

Skriver én linje til stdout (til Alfred-varselet). Test uten utklippstavle:
    echo "tekst" | python3 summarize.py --stdin [instruks]
    python3 summarize.py --show-context     # bare briefen, til kontroll
"""
import datetime as dt
import html
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys

DEFAULT_HTML = "~/Documents/Summary/sum.html"
DEFAULT_MODEL = "sonnet"
DEFAULT_CONTEXT_HOURS = 24
TIMEOUT = 180
MAX_CHARS = 60_000  # lang nok for en artikkel, kort nok til å holde farten oppe

SYSTEM = (
    "Du får en tekst brukeren har kopiert. Skriv et sammendrag på norsk bokmål som kan "
    "leses på ti sekunder, i enkel Markdown (`## OVERSKRIFT`, punkter med `- `, URL-er fra "
    "teksten som rene lenker). Vær kort: hele svaret under 150 ord (tabeller og diagrammer unntatt). Struktur:\n"
    "## DET VIKTIGSTE\n2–4 punkter på én linje hver.\n\n"
    "## FORENKLET\n2–3 setninger som forklarer kjernen så nesten alle forstår det, uten "
    "fagord. Som om du forklarer det til en nysgjerrig 12-åring.\n\n"
    "## ANALOGI\nFinnes det en analogi, et bilde eller et eksempel i teksten fra før: gjengi "
    "den kort. Hvis ikke, og innholdet er abstrakt eller teknisk: lag én hverdagsanalogi på "
    "2–3 setninger. Er innholdet konkret og enkelt, dropp seksjonen.\n\n"
    "VISUELT, bare når det gjør innholdet raskere å forstå (aldri pynt):\n"
    "- Tall som sammenlignes (andeler, beløp, antall per kategori, 2–8 rader): et søylediagram i "
    "en kodeblokk med språk `chart`, én rad per linje som `Navn: tall enhet`, valgfri første "
    "linje `tittel: …`. Eksempel:\n```chart\ntittel: Markedsandel 2025\nApple: 28 %\nSamsung: 20 %\n```\n"
    "- Flere egenskaper per ting: en Markdown-tabell (maks 5 kolonner, 6 rader).\n"
    "- 1–3 nøkkeltall som er hele poenget: en kodeblokk med språk `tall`, én per linje som "
    "`42 % | hva tallet betyr`.\n"
    "- Rekkefølge/prosess: nummerert liste.\n"
    "Bruk bare tall som faktisk står i teksten. Tabeller og diagrammer teller ikke mot ordgrensen.\n\n"
    "Ingen innledning, ingen avslutning, ingen kommentarer om teksten. Er teksten kode, en "
    "feilmelding eller en logg: si hva den gjør eller hva som er galt, og hva man bør gjøre. "
    "Svar på språket brukerens ekstra instruks ber om, ellers norsk.\n\n"
    "Du kan få et KONTEKSTBRIEF om hva brukeren jobber med. Bruk det bare til å velge hva som "
    "er viktigst. Henger teksten tydelig sammen med noe i briefen, avslutt med\n"
    "## RELEVANS FOR DEG\nén setning. Ellers utelat seksjonen. Gjengi aldri briefen."
)

LOGS = pathlib.Path(os.path.expanduser("~/Logs"))
CLAUDE_MEM_DB = pathlib.Path(os.path.expanduser("~/.claude-mem/claude-mem.db"))
HISTORY = pathlib.Path(os.path.expanduser("~/.claude/history.jsonl"))

ICONS = {"DET VIKTIGSTE": "★", "FORENKLET": "☼", "ANALOGI": "⌘", "RELEVANS FOR DEG": "➜"}


# ---------- kontekstbrief ----------

def _clip(text, n):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _section(md, heading):
    key = f"## {heading}"
    if key not in md:
        return ""
    return md.split(key, 1)[1].split("\n## ", 1)[0].strip()


def context_worklog(since):
    lines = []
    if not LOGS.is_dir():
        return lines
    entries = [f for f in LOGS.rglob("*.md") if "/." not in str(f) and f.stat().st_mtime >= since.timestamp()]
    for f in sorted(entries, key=lambda f: f.stat().st_mtime, reverse=True)[:8]:
        md = f.read_text(encoding="utf-8", errors="replace")
        meta = {}
        head = md.split("---", 2)
        if len(head) >= 3:
            for line in head[1].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
        goal = _clip(_section(md, "Mål"), 160)
        left = _clip(_section(md, "Gjenstår"), 120)
        lines.append(f"- {meta.get('prosjekt', '?')}: {meta.get('tittel', f.stem)}"
                     + (f" | mål: {goal}" if goal and goal != "–" else "")
                     + (f" | gjenstår: {left}" if left and left != "–" else ""))
    return lines


def context_claude_mem(since):
    out = []
    if not CLAUDE_MEM_DB.is_file():
        return out
    try:
        db = sqlite3.connect(f"file:{CLAUDE_MEM_DB}?mode=ro", uri=True)
        epoch = int(since.timestamp() * 1000)
        for project, request, nxt in db.execute(
                "select project, request, next_steps from session_summaries "
                "where created_at_epoch >= ? order by created_at_epoch desc limit 6", (epoch,)):
            out.append(f"- {project}: {_clip(request, 140)}" + (f" | neste: {_clip(nxt, 100)}" if nxt else ""))
        for project, typ, title in db.execute(
                "select project, type, title from observations "
                "where created_at_epoch >= ? order by created_at_epoch desc limit 20", (epoch,)):
            out.append(f"- ({project}, {typ}) {_clip(title, 110)}")
    except sqlite3.Error:
        pass
    return out


def context_history(since):
    out = []
    if not HISTORY.is_file():
        return out
    try:
        tail = HISTORY.read_bytes()[-300_000:].decode("utf-8", errors="replace").splitlines()
    except OSError:
        return out
    seen = set()
    for line in reversed(tail):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("timestamp", 0) / 1000 < since.timestamp():
            break
        text = _clip(d.get("display", ""), 120)
        if not text or text.startswith("/") or text in seen:
            continue
        seen.add(text)
        out.append(f"- {pathlib.Path(d.get('project', '')).name or '?'}: {text}")
        if len(out) >= 15:
            break
    return out


def context_brief(hours):
    if hours <= 0:
        return ""
    since = dt.datetime.now() - dt.timedelta(hours=hours)
    parts = []
    for title, lines, budget in (
        ("Arbeidslogg (økter med Claude Code, nyeste først)", context_worklog(since), 1600),
        ("Claude-minne", context_claude_mem(since), 1400),
        ("Siste forespørsler til Claude Code", context_history(since), 900),
    ):
        body = ""
        for line in lines:
            if len(body) + len(line) + 1 > budget:
                break
            body += line + "\n"
        if body:
            parts.append(f"{title}:\n{body.rstrip()}")
    if not parts:
        return ""
    return f"KONTEKSTBRIEF – brukerens Claude-aktivitet siste {hours} timer\n\n" + "\n\n".join(parts)


# ---------- Markdown → HTML ----------

_INLINE = [
    (re.compile(r"`([^`]+)`"), lambda m: f"<code>{m.group(1)}</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), lambda m: f"<strong>{m.group(1)}</strong>"),
    (re.compile(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])"), lambda m: f"<em>{m.group(1)}</em>"),
    (re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)"), lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>'),
    (re.compile(r'(?<!["\'>=])(https?://[^\s<>()\]]+[^\s<>()\].,;:!?])'), lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>'),
]


def inline(text):
    text = html.escape(text, quote=False)
    for rx, fn in _INLINE:
        text = rx.sub(fn, text)
    return text


def _num(text):
    """Første tall i strengen som float (norsk/engelsk desimal), ellers None."""
    m = re.search(r"-?\d+(?:[.,]\d+)?", text.replace(" ", "").replace(" ", ""))
    if not m:
        return None
    return float(m.group(0).replace(",", "."))


def render_chart(lines):
    title, rows = "", []
    for line in lines:
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        if label.strip().lower() in ("tittel", "title") and not rows:
            title = value.strip()
            continue
        n = _num(value)
        if n is not None:
            rows.append((label.strip(), value.strip(), n))
    if not rows:
        return "<pre>" + html.escape("\n".join(lines)) + "</pre>"
    top = max(abs(n) for _, _, n in rows) or 1
    out = ['<div class="chart">']
    if title:
        out.append(f'<div class="chart-title">{inline(title)}</div>')
    for label, value, n in rows[:8]:
        pct = max(1.5, 100 * abs(n) / top)
        out.append('<div class="row"><div class="lbl">%s</div>'
                   '<div class="track"><div class="bar" style="width:%.1f%%"></div></div>'
                   '<div class="val">%s</div></div>' % (inline(label), pct, inline(value)))
    out.append("</div>")
    return "\n".join(out)


def render_stats(lines):
    tiles = []
    for line in lines:
        value, label = (line.split("|", 1) if "|" in line else (line, ""))
        if value.strip():
            tiles.append(f'<div class="stat"><div class="v">{inline(value.strip())}</div>'
                         f'<div class="l">{inline(label.strip())}</div></div>')
    return '<div class="stats">' + "".join(tiles[:4]) + "</div>" if tiles else ""


def render_table(lines):
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    if not rows:
        return ""
    head, body = rows[0], rows[1:]
    out = ["<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"]
    for r in body:
        cells = "".join(f'<td class="{"n" if _num(c) is not None and len(c) < 14 else ""}">{inline(c)}</td>' for c in r)
        out.append(f"<tr>{cells}</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def md_to_html(md):
    """Enkel konverterer for det Claude skriver: ##-overskrifter, punkter, nummererte
    lister, avsnitt, Markdown-tabeller og kodeblokker (`chart`, `tall`, annet som <pre>)."""
    sections, cur, buf = [], None, []
    list_tag = None

    def flush_list():
        nonlocal list_tag
        if list_tag:
            buf.append(f"</{list_tag}>")
            list_tag = None

    def flush_section():
        flush_list()
        if cur is not None or buf:
            sections.append((cur, "\n".join(buf)))

    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        fence = re.match(r"^\s*```\s*(\w*)\s*$", line)
        if fence:
            lang = fence.group(1).lower()
            block = []
            i += 1
            while i < len(lines) and not re.match(r"^\s*```\s*$", lines[i]):
                block.append(lines[i].rstrip())
                i += 1
            i += 1
            flush_list()
            if lang == "chart":
                buf.append(render_chart(block))
            elif lang in ("tall", "stats", "stat"):
                buf.append(render_stats(block))
            else:
                buf.append("<pre>" + html.escape("\n".join(block)) + "</pre>")
            continue
        if line.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            flush_list()
            buf.append(render_table(block))
            continue
        m = re.match(r"^#{1,3}\s+(.*)$", line)
        if m:
            flush_section()
            cur, buf = m.group(1).strip(), []
            i += 1
            continue
        m = re.match(r"^\s*[-*•]\s+(.*)$", line)
        if m:
            if list_tag != "ul":
                flush_list()
                buf.append("<ul>")
                list_tag = "ul"
            buf.append(f"<li>{inline(m.group(1))}</li>")
            i += 1
            continue
        m = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if m:
            if list_tag != "ol":
                flush_list()
                buf.append("<ol>")
                list_tag = "ol"
            buf.append(f"<li>{inline(m.group(1))}</li>")
            i += 1
            continue
        flush_list()
        if line.strip():
            buf.append(f"<p>{inline(line.strip())}</p>")
        i += 1
    flush_section()

    out = []
    for title, body in sections:
        if title is None:
            out.append(f'<section class="card">{body}</section>')
            continue
        key = title.upper().strip(" :")
        icon = ICONS.get(key, "•")
        out.append(f'<section class="card"><h2><span class="ico">{icon}</span>{html.escape(title)}</h2>{body}</section>')
    return "\n".join(out)


HTML = """<!doctype html>
<html lang="no"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="1">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sammendrag</title>
<style>
:root {{ --base:#eff1f5; --mantle:#e6e9ef; --surface:#ccd0da; --text:#4c4f69; --sub:#6c6f85;
        --mauve:#8839ef; --lavender:#7287fd; --green:#40a02b; --red:#d20f39; --bar:#8839ef; }}
@media (prefers-color-scheme: dark) {{
:root {{ --base:#1e1e2e; --mantle:#181825; --surface:#313244; --text:#cdd6f4; --sub:#a6adc8;
        --mauve:#cba6f7; --lavender:#b4befe; --green:#a6e3a1; --red:#f38ba8; --bar:#9f74d9; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0 auto; max-width:760px; padding:22px 26px 40px; background:var(--base); color:var(--text);
       font:16px/1.5 -apple-system, "SF Pro Text", "Helvetica Neue", sans-serif; }}
header {{ display:flex; gap:12px; align-items:baseline; flex-wrap:wrap; margin-bottom:14px;
         font:13px "JetBrainsMono Nerd Font", "JetBrains Mono", ui-monospace, monospace; color:var(--sub); }}
header .t {{ color:var(--mauve); font-weight:700; letter-spacing:.06em; }}
.state {{ display:inline-flex; align-items:center; gap:8px; }}
.state::before {{ content:""; width:9px; height:9px; border-radius:50%; background:var(--green); }}
.state.err::before {{ background:var(--red); }}
.card {{ background:var(--mantle); border:1px solid var(--surface); border-radius:14px;
        padding:14px 18px 6px; margin:0 0 12px; }}
h2 {{ margin:0 0 6px; font-size:12px; letter-spacing:.12em; text-transform:uppercase; color:var(--mauve); }}
h2 .ico {{ display:inline-block; width:1.4em; opacity:.8 }}
p, ul {{ margin:0 0 10px }} ul {{ padding-left:1.15em }} li {{ margin:2px 0 }}
li::marker {{ color:var(--sub) }}
a {{ color:var(--lavender); text-decoration:underline; text-underline-offset:2px }}
code {{ font:0.92em "JetBrainsMono Nerd Font", "JetBrains Mono", ui-monospace, monospace;
       color:var(--lavender); background:var(--surface); padding:1px 5px; border-radius:5px }}
strong {{ color:var(--text) }}
ol {{ padding-left:1.3em }}
pre {{ font:13px/1.45 "JetBrainsMono Nerd Font", "JetBrains Mono", ui-monospace, monospace; background:var(--surface);
      padding:10px 12px; border-radius:8px; overflow-x:auto; margin:0 0 10px }}
table {{ border-collapse:collapse; width:100%; margin:2px 0 12px; font-size:14.5px }}
th, td {{ text-align:left; padding:6px 10px; border-bottom:1px solid var(--surface); vertical-align:top }}
th {{ color:var(--sub); font-weight:600; font-size:12px; letter-spacing:.06em; text-transform:uppercase }}
td.n {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap }}
tr:last-child td {{ border-bottom:0 }}
.chart {{ margin:4px 0 12px }}
.chart-title {{ color:var(--sub); font-size:13px; margin-bottom:6px }}
.row {{ display:grid; grid-template-columns:minmax(80px,30%) 1fr auto; gap:10px; align-items:center; margin:5px 0 }}
.lbl {{ font-size:14px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }}
.track {{ height:10px; background:var(--surface); border-radius:0 4px 4px 0 }}
.bar {{ height:100%; background:var(--bar); border-radius:0 4px 4px 0; min-width:2px }}
.val {{ font-size:13px; color:var(--sub); font-variant-numeric:tabular-nums; white-space:nowrap }}
.stats {{ display:flex; gap:10px; flex-wrap:wrap; margin:4px 0 12px }}
.stat {{ flex:1 1 120px; background:var(--surface); border-radius:10px; padding:10px 12px }}
.stat .v {{ font-size:24px; font-weight:700; color:var(--mauve); font-variant-numeric:tabular-nums; line-height:1.15 }}
.stat .l {{ font-size:12.5px; color:var(--sub); margin-top:2px }}
</style></head>
<body>
<header><span class="t">SAMMENDRAG</span><span class="state {state}">{status}</span><span>{meta}</span></header>
{body}
</body></html>
"""


# ---------- I/O ----------

def find_claude():
    for cand in (os.environ.get("CLAUDE_BIN", ""), os.path.expanduser("~/.local/bin/claude"),
                 "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        if cand and os.access(cand, os.X_OK):
            return cand
    return "claude"


def paths():
    page = pathlib.Path(os.path.expanduser(os.environ.get("sum_html", "").strip() or DEFAULT_HTML))
    txt_env = os.environ.get("sum_path", "").strip()
    txt = pathlib.Path(os.path.expanduser(txt_env)) if txt_env else None
    for p in (txt, page):
        if p is not None:
            p.parent.mkdir(parents=True, exist_ok=True)
    return txt, page


def clipboard():
    return subprocess.run(["/usr/bin/pbpaste"], capture_output=True, text=True).stdout


def publish(txt, page, header, md, state, status, meta=""):
    if txt is not None:
        txt.write_text(f"# {header}\n\n{md.rstrip()}\n", encoding="utf-8")
    page.write_text(HTML.format(state=state, status=html.escape(status), meta=html.escape(meta),
                                body=md_to_html(md)), encoding="utf-8")


def open_window(page):
    url = page.resolve().as_uri()
    for app in ("Brave Browser", "Google Chrome", "Chromium", "Microsoft Edge"):
        if pathlib.Path(f"/Applications/{app}.app").is_dir():
            subprocess.Popen(["/usr/bin/open", "-na", app, "--args", f"--app={url}", "--window-size=620,760"])
            return f"Åpner sammendraget i {app}"
    subprocess.Popen(["/usr/bin/open", str(page)])
    return "Åpner sammendraget i nettleseren"


def main():
    args = sys.argv[1:]
    try:
        hours = int(os.environ.get("sum_context", "").strip() or DEFAULT_CONTEXT_HOURS)
    except ValueError:
        hours = DEFAULT_CONTEXT_HOURS
    if "--show-context" in args:
        print(context_brief(hours) or "(ingen kontekst)")
        return 0
    txt, page = paths()
    use_stdin = "--stdin" in args
    extra = " ".join(a for a in args if a != "--stdin").strip()
    if extra.lower() in ("vis", "åpne", "open", "show"):
        if not page.exists():
            publish(txt, page, "Ingen sammendrag ennå", "Kopier en tekst og kjør `sum`.", "ok", "klar")
        print(open_window(page))
        return 0

    text = (sys.stdin.read() if use_stdin else clipboard()).strip()
    if not text:
        print("Utklippstavlen er tom")
        return 1
    truncated = ""
    if len(text) > MAX_CHARS:
        text, truncated = text[:MAX_CHARS], f", kuttet til {MAX_CHARS}"

    model = os.environ.get("sum_model", "").strip() or DEFAULT_MODEL
    started = dt.datetime.now()
    meta = f"{started.strftime('%H:%M')} · {len(text)} tegn{truncated} · {model}"

    prompt = "TEKSTEN SOM SKAL OPPSUMMERES:\n" + text
    if extra:
        prompt = f"Ekstra instruks fra brukeren: {extra}\n\n" + prompt
    brief = context_brief(hours)
    if brief:
        prompt = brief + "\n\n" + prompt
    cmd = [find_claude(), "-p", "--tools", "", "--no-session-persistence", "--strict-mcp-config",
           "--setting-sources", "", "--disable-slash-commands", "--model", model,
           "--system-prompt", SYSTEM, prompt]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        publish(txt, page, f"SAMMENDRAG · {meta} · FEIL", f"Claude svarte ikke innen {TIMEOUT} sekunder.", "err", "feil", meta)
        print("Claude svarte ikke i tide")
        return 1
    except OSError as e:
        publish(txt, page, f"SAMMENDRAG · {meta} · FEIL", f"Fant ikke claude: {e}", "err", "feil", meta)
        print("Fant ikke claude-kommandoen")
        return 1

    out = r.stdout.strip()
    if r.returncode != 0 or not out:
        err = out or r.stderr.strip() or f"claude feilet (kode {r.returncode})"
        publish(txt, page, f"SAMMENDRAG · {meta} · FEIL", err, "err", "feil", meta)
        print("Sammendraget feilet, se fila")
        return 1

    secs = (dt.datetime.now() - started).total_seconds()
    meta = f"{meta} · {secs:.1f} s"
    publish(txt, page, f"SAMMENDRAG · {meta}", out, "ok", "klar", meta)
    print(f"Sammendrag klart ({secs:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
