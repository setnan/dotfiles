#!/usr/bin/env python3
"""Alfred: oversikt over alle kodeord, som notat i vaulten og som HTML-side.

`aak` åpner siden som ble bygd sist. `hentak` (argumentet `hent`) leser alle workflows
og egne nettsøk, oppdaterer tabellen i notatet og bygger siden på nytt. Bare tabellen
mellom markørene skrives om, og kolonnen Notater beholdes per kodeord.

Valg: --no-open (ikke åpne), --out <sti>. Notatet settes med variabelen ja_note.
"""
import html
import os
import pathlib
import plistlib
import re
import subprocess
import sys
from datetime import date, datetime

DEFAULT_NOTE = "~/Documents/Obsidian/Vault/Alfred – kodeord.md"
BUNDLE = "no.etnan.ja"
START, END = "<!-- ja:start -->", "<!-- ja:end -->"
HEADER = "| Kodeord | Tekst etter | Workflow | Gjør | Notater |"
RULE = "|---|---|---|---|---|"
ARG = {0: "må", 1: "valgfri", 2: ""}
WEB = "Nettsøk"
ACTIONS = "Universal Actions"
VAR = re.compile(r"\{var:([^}]+)\}")
MODS = ((262144, "⌃"), (524288, "⌥"), (131072, "⇧"), (1048576, "⌘"))


def load(path):
    try:
        with open(path, "rb") as f:
            return plistlib.load(f)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None


def variables(info, folder):
    values = {v.get("variable"): (v.get("config") or {}).get("default", "")
              for v in info.get("userconfigurationconfig") or []}
    values.update(load(folder / "prefs.plist") or {})
    values.update(info.get("variables") or {})
    return values


def fill(text, values):
    return VAR.sub(lambda m: str(values.get(m.group(1), "")), str(text or "")).replace("{query}", "…").strip()


def describe(config, values):
    title = fill(config.get("text") or config.get("title"), values)
    sub = fill(config.get("subtext"), values)
    if title and sub and sub != title:
        return f"{title}: {sub}"
    return title or sub


def hotkey(config):
    key = config.get("hotstring")
    if not key:
        return None
    mods = int(config.get("hotmod") or 0)
    return "".join(s for bit, s in MODS if mods & bit) + str(key).upper()


def collect(root):
    """Gir rader (kodeord, tekst etter, workflow, gjør) fra alle workflows og nettsøk."""
    rows = {}

    def add(word, arg, workflow, what):
        rows.setdefault((word, workflow), (word, arg, workflow, what))

    for plist in sorted((root / "workflows").glob("*/info.plist")):
        info = load(plist)
        if not info or info.get("disabled"):
            continue
        values = variables(info, plist.parent)
        name = info.get("name") or plist.parent.name
        for obj in info.get("objects") or []:
            config, kind = obj.get("config") or {}, obj.get("type", "")
            if "keyword" in config and kind.endswith((".keyword", ".scriptfilter", ".listfilter")):
                word = fill(config["keyword"], values)
                if word:
                    add(word, ARG.get(config.get("argumenttype", 2), ""), name, describe(config, values))
            elif kind.endswith("trigger.hotkey") and hotkey(config):
                add(hotkey(config), "", name, "Hurtigtast")
            elif kind.endswith("trigger.action") and config.get("name"):
                add(config["name"], "", ACTIONS, name)

    web = load(root / "preferences/features/websearch/prefs.plist") or {}
    for site in (web.get("customSites") or {}).values():
        if site.get("enabled", True) and site.get("keyword"):
            add(site["keyword"], "må", WEB, str(site.get("text") or "").replace("{query}", "…"))
    last = {WEB: 1, ACTIONS: 2}
    return sorted(rows.values(), key=lambda r: (last.get(r[2], 0), r[2].lower(), r[0].lower()))


def split_row(line):
    cells, cur, in_code, i = [], "", False, 0
    line = line.strip()
    line = line[1:] if line.startswith("|") else line
    line = line[:-1] if line.endswith("|") and not line.endswith("\\|") else line
    while i < len(line):
        if line[i] == "\\" and line[i + 1:i + 2] == "|":
            cur += "|"
            i += 2
            continue
        if line[i] == "`":
            in_code = not in_code
        if line[i] == "|" and not in_code:
            cells.append(cur.strip())
            cur = ""
        else:
            cur += line[i]
        i += 1
    cells.append(cur.strip())
    return cells


def cell(text):
    return re.sub(r"\s+", " ", str(text)).replace("|", "\\|").strip()


def existing_notes(text):
    """Notater brukeren har skrevet, per (kodeord, workflow)."""
    notes = {}
    if START in text and END in text:
        for line in text.split(START, 1)[1].split(END, 1)[0].split("\n"):
            cells = split_row(line) if line.startswith("|") else []
            if len(cells) >= 5 and cells[0] != "Kodeord" and set(cells[0]) - set("-") and cells[4]:
                notes[(cells[0].strip("`"), cells[2])] = cells[4]
    return notes


NEW_NOTE = """---
up: "[[Alfred – launcher]]"
created: {today}
tags:
  - alfred
  - oppslagsverk
---

# Alfred – kodeord

Alle kodeordene i Alfred. `aak` viser dem som HTML, `hentak` oppdaterer tabellen og siden. Tabellen skrives om, men det du skriver i kolonnen Notater blir stående.

"""


def write_note(path, rows):
    text = path.read_text(encoding="utf-8") if path.exists() else NEW_NOTE.format(today=date.today().isoformat())
    notes = existing_notes(text)
    lines = [HEADER, RULE]
    merged = []
    for word, arg, workflow, what in rows:
        note = notes.get((word, workflow), "")
        merged.append((word, arg, workflow, what, note))
        lines.append(f"| `{cell(word)}` | {arg} | {cell(workflow)} | {cell(what)} | {note.replace('|', chr(92) + '|')} |")
    table = START + "\n" + "\n".join(lines) + "\n" + END
    if START in text and END in text:
        head, rest = text.split(START, 1)
        new = head + table + rest.split(END, 1)[1]
    else:
        new = text.rstrip("\n") + "\n\n" + table + "\n"
    if new != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")
    return merged


def esc(text):
    return html.escape(str(text), quote=True)


def render(rows, source):
    cards, toc, groups = [], [], {}
    for row in rows:
        groups.setdefault(row[2], []).append(row)
    for i, (workflow, items) in enumerate(groups.items()):
        body = []
        for word, arg, _, what, note in items:
            hint = f' <span class="arg">+ tekst{" (valgfri)" if arg == "valgfri" else ""}</span>' if arg else ""
            extra = f'<div class="note">{esc(note)}</div>' if note else ""
            body.append(f'<div class="row f"><div class="l"><code>{esc(word)}</code>{hint}</div>'
                        f'<div class="r">{esc(what)}{extra}</div></div>')
        cards.append(f'<section class="card" id="s{i}"><h2>{esc(workflow)}</h2>{"".join(body)}</section>')
        toc.append(f'<a href="#s{i}">{esc(workflow)}</a>')
    return (PAGE.replace("%TOC%", "".join(toc)).replace("%CARDS%", "".join(cards))
            .replace("%COUNT%", str(len(rows))).replace("%SOURCE%", esc(source))
            .replace("%WHEN%", datetime.now().strftime("%d.%m.%Y %H:%M")))


PAGE = """<!doctype html>
<html lang="no"><head><meta charset="utf-8"><title>Alfred-kodeord</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{color-scheme:light dark;--bg:#eff1f5;--card:#fff;--line:#dce0e8;--text:#4c4f69;--dim:#6c6f85;--accent:#8839ef;--chip:#e6e9ef}
@media(prefers-color-scheme:dark){:root{--bg:#1e1e2e;--card:#181825;--line:#313244;--text:#cdd6f4;--dim:#a6adc8;--accent:#cba6f7;--chip:#313244}}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:120px}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 -apple-system,system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);padding:14px 20px 10px;border-bottom:1px solid var(--line)}
.top{display:flex;gap:14px;align-items:center}h1{font-size:18px;margin:0;color:var(--accent)}
#q{flex:1;font:inherit;padding:7px 11px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--text);outline:none}#q:focus{border-color:var(--accent)}
nav{display:flex;flex-wrap:wrap;gap:4px 12px;margin-top:9px;font-size:12px}nav a{color:var(--dim);text-decoration:none}nav a:hover{color:var(--accent)}
main{columns:2 420px;column-gap:14px;padding:14px 20px}
.card{break-inside:avoid;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:0 0 14px}
h2{font-size:15px;margin:0 0 6px;color:var(--accent)}
.row{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,3fr);gap:10px;padding:4px 0;border-top:1px solid var(--line)}h2+.row{border-top:0}
.r{color:var(--dim)}.note{color:var(--text);margin-top:2px}.arg{color:var(--dim);font-size:12px}
code{font:12px/1.4 ui-monospace,Menlo,monospace;overflow-wrap:anywhere;border-radius:4px;padding:1px 4px;background:var(--chip);color:var(--accent);cursor:pointer}code:hover{outline:1px solid var(--accent)}
.hide{display:none!important}#none{display:none;padding:30px 20px;color:var(--dim)}footer{padding:0 20px 18px;color:var(--dim);font-size:12px}
#toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:var(--accent);color:var(--bg);padding:6px 14px;border-radius:8px;font-size:13px;opacity:0;transition:opacity .15s;pointer-events:none}#toast.on{opacity:1}
</style></head><body>
<header><div class="top"><h1>Alfred</h1><input id="q" autofocus placeholder="Søk i %COUNT% kodeord…" aria-label="Søk"></div><nav>%TOC%</nav></header>
<main>%CARDS%</main><div id="none">Ingen treff.</div>
<footer>Bygd %WHEN%, tabellen ligger i %SOURCE%. Klikk på et kodeord for å kopiere det.</footer>
<div id="toast" role="status"></div>
<script>
var q=document.getElementById('q'),toast=document.getElementById('toast'),none=document.getElementById('none'),t;
function apply(){var w=q.value.toLowerCase().split(/\\s+/).filter(Boolean),any=false;
document.querySelectorAll('.card').forEach(function(c){var hit=c.querySelector('h2').textContent.toLowerCase(),v=false;
c.querySelectorAll('.f').forEach(function(e){var s=(hit+' '+e.textContent).toLowerCase(),m=w.every(function(x){return s.indexOf(x)>=0});e.classList.toggle('hide',!m);v=v||m});
c.classList.toggle('hide',!v);any=any||v});none.style.display=any?'none':'block'}
q.addEventListener('input',apply);
document.addEventListener('keydown',function(e){if(e.key==='Escape'){q.value='';apply();q.focus()}});
function say(m){toast.textContent=m;toast.classList.add('on');clearTimeout(t);t=setTimeout(function(){toast.classList.remove('on')},1100)}
function fallback(s){var a=document.createElement('textarea');a.value=s;document.body.appendChild(a);a.select();var ok=document.execCommand('copy');a.remove();return ok}
document.addEventListener('click',function(e){var c=e.target.closest('code');if(!c)return;var s=c.textContent;
if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(s).then(function(){say('Kopiert: '+s)},function(){say(fallback(s)?'Kopiert: '+s:'Kunne ikke kopiere')})}else{say(fallback(s)?'Kopiert: '+s:'Kunne ikke kopiere')}});
</script></body></html>
"""


def open_window(page):
    url = page.resolve().as_uri()
    for app in ("Brave Browser", "Google Chrome", "Chromium", "Microsoft Edge"):
        if pathlib.Path(f"/Applications/{app}.app").is_dir():
            subprocess.Popen(["/usr/bin/open", "-na", app, "--args", f"--app={url}", "--window-size=1100,860"])
            return
    subprocess.Popen(["/usr/bin/open", str(page)])


def output_path(args):
    if "--out" in args:
        return pathlib.Path(args[args.index("--out") + 1]).expanduser()
    cache = os.environ.get("alfred_workflow_cache") or f"~/Library/Caches/com.runningwithcrayons.Alfred/Workflow Data/{BUNDLE}"
    return pathlib.Path(cache).expanduser() / "ja.html"


def build(page):
    note = pathlib.Path(os.environ.get("ja_note", "").strip() or DEFAULT_NOTE).expanduser()
    root = pathlib.Path(__file__).resolve().parents[2]
    rows = collect(root)
    if not rows:
        return "Fant ingen kodeord"
    merged = write_note(note, rows)
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(render(merged, note.name), encoding="utf-8")
    return len(merged)


def main():
    args = sys.argv[1:]
    page = output_path(args)
    if "hent" in args:
        result = build(page)
        print(f"Oppdatert: {result} kodeord" if isinstance(result, int) else result)
        return 0
    if not page.exists():
        result = build(page)
        if not isinstance(result, int):
            print(result)
            return 0
    if "--no-open" not in args:
        open_window(page)
    return 0


if __name__ == "__main__":
    sys.exit(main())
