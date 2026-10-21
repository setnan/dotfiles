#!/usr/bin/env python3
"""Alfred Script Filter: `cr [søk]` – gjenoppta en Claude Code-økt.

Reads ~/.claude/history.jsonl (one line per prompt: display, timestamp,
project, sessionId), groups by session, newest first. The title is the
session's AI title from ~/.claude/projects/<encoded project>/<session>.jsonl
when present (cached by file size), otherwise the first prompt. Enter →
`claude --resume <id>` in the project directory in a new Ghostty tab.
"""
import datetime
import json
import mmap
import os
import re
import sys

HOME = os.path.expanduser("~")
HISTORY = os.path.join(HOME, ".claude", "history.jsonl")
PROJECTS = os.path.join(HOME, ".claude", "projects")
CACHE_DIR = os.environ.get("alfred_workflow_cache") or os.path.join(HOME, "Library", "Caches", "no.etnan.claude")
CACHE = os.path.join(CACHE_DIR, "titles.json")
LIMIT = 40
MD = ("jan", "feb", "mar", "apr", "mai", "jun", "jul", "aug", "sep", "okt", "nov", "des")


def encoded(project):
    return re.sub(r"[^A-Za-z0-9-]", "-", project)


def session_file(project, sid):
    return os.path.join(PROJECTS, encoded(project), f"{sid}.jsonl")


def sessions():
    found = {}
    try:
        with open(HISTORY, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                sid, project = d.get("sessionId"), d.get("project")
                if not sid or not project:
                    continue
                e = found.setdefault(sid, {"sid": sid, "project": project, "first": d.get("display", ""), "n": 0})
                e["n"] += 1
                e["last"] = d.get("timestamp", 0)
    except OSError:
        pass
    rows = sorted(found.values(), key=lambda e: -e.get("last", 0))
    return [e for e in rows if os.path.exists(session_file(e["project"], e["sid"]))][:LIMIT]


def load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except OSError:
        pass


def ai_title(path):
    """Last `aiTitle` value in the session file, or None."""
    try:
        with open(path, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            if size == 0:
                return None
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
                i = m.rfind(b'"aiTitle"')
                if i < 0:
                    return None
                chunk = m[i : i + 600].decode("utf-8", "replace")
    except (OSError, ValueError):
        return None
    mt = re.search(r'"aiTitle"\s*:\s*"((?:[^"\\]|\\.)*)"', chunk)
    if not mt:
        return None
    try:
        return json.loads('"' + mt.group(1) + '"').strip() or None
    except ValueError:
        return None


def clean_prompt(text):
    text = re.sub(r"\[(Image|Pasted text) #\d+[^\]]*\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:80] + ("…" if len(text) > 80 else "")


def when(ts_ms):
    t = datetime.datetime.fromtimestamp(ts_ms / 1000)
    today = datetime.date.today()
    if t.date() == today:
        return f"i dag {t:%H:%M}"
    if t.date() == today - datetime.timedelta(days=1):
        return f"i går {t:%H:%M}"
    return f"{t.day}. {MD[t.month - 1]} {t:%H:%M}"


def main():
    query = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    cache = load_cache()
    dirty = False
    items = []
    for e in sessions():
        path = session_file(e["project"], e["sid"])
        size = os.path.getsize(path)
        c = cache.get(e["sid"])
        if c and c[0] == size:
            title = c[1]
        else:
            title = ai_title(path)
            cache[e["sid"]] = [size, title]
            dirty = True
        title = title or clean_prompt(e["first"]) or e["sid"][:8]
        proj = os.path.basename(e["project"]) or e["project"]
        hay = f"{title} {proj} {e['first']}".lower()
        if query and not all(w in hay for w in query.split()):
            continue
        n = e["n"]
        items.append({
            "uid": e["sid"],
            "title": title,
            "subtitle": f"{proj}  ·  {when(e['last'])}  ·  {n} {'melding' if n == 1 else 'meldinger'}",
            "arg": json.dumps({"dir": e["project"], "args": ["claude", "--resume", e["sid"]]}),
            "icon": {"type": "fileicon", "path": e["project"]},
            "match": hay,
        })
    if dirty:
        save_cache(cache)
    if not items:
        items = [{"title": "Ingen økter funnet", "subtitle": "Ingen treff i ~/.claude/history.jsonl", "valid": False}]
    print(json.dumps({"items": items}, ensure_ascii=False))


if __name__ == "__main__":
    main()
