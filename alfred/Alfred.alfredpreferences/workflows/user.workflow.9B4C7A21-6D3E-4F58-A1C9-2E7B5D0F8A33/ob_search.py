#!/usr/bin/env python3
"""Alfred script filter: search notes in the Obsidian vault by title/path, then by content.

Usage: ob_search.py [query]
Vault path/name can be overridden with the workflow variables vault_path / vault_name.
"""
import datetime
import json
import os
import subprocess
import sys

VAULT_PATH = os.environ.get("vault_path") or "/Users/simonetnan/Documents/Koderiet/RSA/md/SE-v2"
VAULT_NAME = os.environ.get("vault_name") or os.path.basename(VAULT_PATH.rstrip("/"))
OBSIDIAN_APP = "/Applications/Obsidian.app"
SKIP_DIRS = {".obsidian", ".trash", ".git", "node_modules"}
MAX_ITEMS = 40


def notes():
    out = []
    for root, dirs, files in os.walk(VAULT_PATH):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not f.endswith(".md"):
                continue
            full = os.path.join(root, f)
            try:
                mtime = os.path.getmtime(full)
            except OSError:
                continue
            out.append((os.path.relpath(full, VAULT_PATH), full, mtime))
    return out


def content_matches(query):
    """Relative paths of notes whose body contains every query word (case-insensitive)."""
    words = query.split()
    if not words:
        return set()
    cmd = ["/usr/bin/grep", "-rl", "--null", "-i", "-F", "--include=*.md"]
    for d in SKIP_DIRS:
        cmd.append(f"--exclude-dir={d}")
    cmd += ["-e", words[0], VAULT_PATH]
    try:
        found = subprocess.run(cmd, capture_output=True, timeout=5).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        return set()
    paths = [p for p in found.split("\0") if p]
    for word in words[1:]:
        if not paths:
            break
        try:
            res = subprocess.run(["/usr/bin/grep", "-l", "--null", "-i", "-F", "-e", word] + paths,
                                 capture_output=True, timeout=5).stdout.decode("utf-8", "replace")
        except (OSError, subprocess.TimeoutExpired):
            return set()
        paths = [p for p in res.split("\0") if p]
    return {os.path.relpath(p, VAULT_PATH) for p in paths}


def item(rel, full, mtime, query, via):
    name = os.path.splitext(os.path.basename(rel))[0]
    folder = os.path.dirname(rel) or "/"
    when = datetime.datetime.fromtimestamp(mtime).strftime("%d.%m.%Y %H:%M")
    sub = f"{folder} · endret {when}" + (" · treff i innhold" if via == "content" else "")
    return {
        "uid": rel,
        "title": name,
        "subtitle": sub,
        "arg": full,
        "type": "file",
        "quicklookurl": full,
        "icon": {"type": "fileicon", "path": OBSIDIAN_APP},
        "variables": {"file": rel[:-3], "path": full, "query": query, "action": "open"},
        "text": {"copy": f"[[{name}]]", "largetype": rel},
        "mods": {
            "cmd": {"subtitle": f"Søk «{query}» i Obsidian" if query else "Åpne Obsidian-søk"},
            "alt": {"subtitle": "Vis filen i Finder"},
        },
    }


def search_item(query):
    return {
        "title": f"Søk «{query}» i Obsidian" if query else "Åpne Obsidian",
        "subtitle": f"Fulltekstsøk i {VAULT_NAME}" if query else VAULT_NAME,
        "arg": query,
        "icon": {"type": "fileicon", "path": OBSIDIAN_APP},
        "variables": {"query": query, "action": "search"},
    }


def main():
    query = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    words = query.lower().split()
    all_notes = notes()
    items = []
    if not words:
        recent = sorted(all_notes, key=lambda n: -n[2])[:MAX_ITEMS]
        items = [item(rel, full, mtime, query, "recent") for rel, full, mtime in recent]
        items.append(search_item(query))
    else:
        def rank(rel):
            name = os.path.splitext(os.path.basename(rel))[0].lower()
            if name == query.lower():
                return 0
            if name.startswith(words[0]):
                return 1
            if all(w in name for w in words):
                return 2
            return 3
        by_name = [(rel, full, mtime) for rel, full, mtime in all_notes
                   if all(w in rel.lower() for w in words)]
        by_name.sort(key=lambda n: (rank(n[0]), -n[2]))
        seen = {n[0] for n in by_name}
        items = [item(rel, full, mtime, query, "name") for rel, full, mtime in by_name[:MAX_ITEMS]]
        if len(items) < MAX_ITEMS:
            hits = content_matches(query)
            extra = [(rel, full, mtime) for rel, full, mtime in all_notes if rel in hits and rel not in seen]
            extra.sort(key=lambda n: -n[2])
            items += [item(rel, full, mtime, query, "content") for rel, full, mtime in extra[:MAX_ITEMS - len(items)]]
        items.append(search_item(query))
    json.dump({"items": items}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
