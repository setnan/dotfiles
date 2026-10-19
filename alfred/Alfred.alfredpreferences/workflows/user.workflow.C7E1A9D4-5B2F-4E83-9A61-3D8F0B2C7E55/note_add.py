#!/usr/bin/env python3
"""Alfred: append a quick note as a checklist item to the Obsidian inbox note.

Usage: note_add.py <section> "<text>"      (env: note_path)

Keyword `n <tekst>` / `note <tekst>` in Alfred appends `- [ ] <tekst>` under
`## Notater` in the inbox note (+/Innboks.md in the SE-v2 vault). If the
heading is missing it is created above the first existing `## ` heading so
quick notes land at the top. Keyword `h <tekst>` / `handleliste <tekst>` runs
the same script with an empty section against +/Handel.md, which appends the
item at the end of the file. In that mode a trailing number is a quantity:
`Laktosefri melk 2` (or `x2`, `2x`, `2 stk`) becomes `Laktosefri melk x2`.
Comma-separated input (`melk 2, brød, egg 12`) becomes one item per part.

The target file comes from the `note_path` env var, set per action in
info.plist from the user-configuration variables (innboks_path, handel_path).
"""
import datetime
import os
import re
import subprocess
import sys

DEFAULT_NOTE = (
    "/Users/simonetnan/Documents/Koderiet/RSA/md/SE-v2/+/Innboks.md"
)

TEMPLATE = """---
up:
  - "[[Add]]"
created: {created}
updated: {created}
tags:
  - innboks
---

"""


def now_stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def set_updated(content, stamp):
    """Set `updated: <stamp>` in the frontmatter, directly below `created:`.

    Replaces an existing `updated:` line, otherwise inserts one after
    `created:` (or as the last frontmatter line if there is no `created:`).
    Content without frontmatter gets a minimal block prepended.
    """
    lines = content.split("\n")
    end = frontmatter_end(lines)
    if end == 0:
        return "\n".join(["---", f"updated: {stamp}", "---", ""] + lines)
    fm = lines[:end]
    for i, l in enumerate(fm):
        if re.match(r"^updated:", l):
            fm[i] = f"updated: {stamp}"
            break
    else:
        at = next((i + 1 for i, l in enumerate(fm) if re.match(r"^created:", l)), end - 1)
        fm.insert(at, f"updated: {stamp}")
    return "\n".join(fm + lines[end:])


def _as_quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title, message):
    try:
        script = f"display notification {_as_quote(message)} with title {_as_quote(title)}"
        subprocess.run(["osascript", "-e", script], check=False, timeout=5)
    except Exception:
        pass


def load(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return TEMPLATE.format(created=now_stamp())


def frontmatter_end(lines):
    """Index of the first line after the YAML frontmatter block (0 if none)."""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return i + 1
    return 0


QTY_RE = re.compile(r"^(?P<name>.+?)\s+(?:x\s*)?(?P<qty>\d+)\s*(?:x|stk\.?)?$", re.IGNORECASE)


def with_quantity(text):
    """`Laktosefri melk 2` / `melk x2` / `melk 2 stk` → `Laktosefri melk x2`."""
    m = QTY_RE.match(text)
    if not m:
        return text
    return f"{m.group('name').strip()} x{int(m.group('qty'))}"


def append_at_end(content, item):
    lines = content.split("\n")
    while lines and lines[-1].strip() == "":
        lines.pop()
    # Blank line before the item unless we are continuing a list.
    if lines and not re.match(r"^\s*[-*+]\s", lines[-1]):
        lines.append("")
    lines.append(item)
    lines.append("")
    return "\n".join(lines)


def insert_item(content, section, item):
    if not section:
        return append_at_end(content, item)
    lines = content.split("\n")
    heading = f"## {section}"
    heading_re = re.compile(r"^##\s")

    # Locate the target section.
    start = next((i for i, l in enumerate(lines) if l.strip() == heading), None)

    if start is None:
        # Create the section above the first existing H2, or at the end.
        first_h2 = next(
            (i for i, l in enumerate(lines) if heading_re.match(l)), None
        )
        block = [heading, "", item, ""]
        if first_h2 is None:
            while lines and lines[-1].strip() == "":
                lines.pop()
            if lines:
                lines.append("")
            lines.extend(block[:-1])
            lines.append("")
        else:
            lines[first_h2:first_h2] = block
        return "\n".join(lines)

    # Section exists: append after its last non-empty line, before the next H2.
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if heading_re.match(lines[i]):
            end = i
            break
    last = end - 1
    while last > start and lines[last].strip() == "":
        last -= 1
    if last == start:
        # Empty section: heading, blank line, item.
        lines[start + 1 : start + 1] = ["", item]
    else:
        lines.insert(last + 1, item)
    return "\n".join(lines)


def main():
    if len(sys.argv) < 3:
        notify("Innboks", "Ingen tekst å legge til")
        return 1
    section = sys.argv[1].strip()
    text = " ".join(sys.argv[2:]).strip()
    if not text:
        notify("Innboks", "Ingen tekst å legge til")
        return 1

    path = (os.environ.get("note_path") or "").strip() or DEFAULT_NOTE

    # Comma-separated input becomes one checklist item per part.
    texts = [t.strip() for t in text.split(",") if t.strip()]
    if not section:  # shopping-list mode: trailing number = quantity
        texts = [with_quantity(t) for t in texts]

    content = load(path)
    for t in texts:
        content = insert_item(content, section, f"- [ ] {t}")
    content = set_updated(content, now_stamp())
    if not content.endswith("\n"):
        content += "\n"

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    title = os.path.splitext(os.path.basename(path))[0]
    notify(f"{title} → {section}" if section else title, " · ".join(texts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
