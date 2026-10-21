#!/usr/bin/env python3
"""Alfred: append a quick note as a checklist item to the Obsidian inbox note.

Usage: note_add.py <section> "<text>"      (env: note_path)

Keyword `n <tekst>` / `note <tekst>` in Alfred appends `- [ ] <tekst>` under
`## Notater` in the inbox note (+/Innboks.md in the vault). If the
heading is missing it is created above the first existing `## ` heading so
quick notes land at the top. Keyword `h <tekst>` / `handleliste <tekst>` runs
the same script with an empty section against +/Handel.md (shopping mode).
There the item goes under `## Handleliste`, or under a store sub-heading
inside it when a store keyword is given: `Glutenfri musli obs 3` →
`- [ ] Glutenfri musli x3` under `### Obs`. Keywords (case-insensitive, first
or last word of an item): obs, kiwi, meny, rema → Rema 1000, claes/clas → Clas Ohlson,
bil → Biltema, t → Thansen, farma/apo → Apotek, sunn → Sunnkost. A leading
keyword applies to every comma-separated part (`obs melk, brød` → both under
Obs). Store-less items land above the first `###`; a missing store heading is
created at the end of the Handleliste section. A trailing number is a quantity:
`Laktosefri melk 2` (or `x2`, `2x`, `2 stk`) becomes `Laktosefri melk x2`.
Comma-separated input (`melk 2, brød, egg 12`) becomes one item per part.
URLs in either mode become markdown links. The label comes from, in order:
quoted text before the URL (`sjekk ut "Argus" https://x` → `sjekk ut
[Argus](https://x)`); the words before the URL minus a leading phrase from
LEAD_PHRASES (`sjekk ut Argus https://x` → the same; `kult verktøy https://x`
→ `[kult verktøy](https://x)`); otherwise `owner/repo` for GitHub or the page
`<title>` (3 s timeout), falling back to host and path.

The target file comes from the `note_path` env var, set per action in
info.plist from the user-configuration variables (innboks_path, handel_path).
"""
import datetime
import html
import os
import re
import subprocess
import sys
import urllib.request

DEFAULT_NOTE = os.path.expanduser("~/Documents/Obsidian/Vault/+/Innboks.md")

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


SHOP_SECTION = "Handleliste"  # items without a store keyword go here

# keyword (lower-case) → heading. Keep keywords single words.
STORES = {
    "obs": "Obs",
    "kiwi": "Kiwi",
    "meny": "Meny",
    "rema": "Rema 1000",
    "claes": "Clas Ohlson",
    "clas": "Clas Ohlson",
    "bil": "Biltema",
    "t": "Thansen",
    "farma": "Apotek",
    "apo": "Apotek",
    "sunn": "Sunnkost",
}


def split_store(text):
    """Strip a store keyword from the first or last word of `text`.

    Returns (text_without_keyword, store_heading or None). The quantity, if
    any, is kept at the end so `musli obs 3` and `obs musli 3` both work.
    """
    m = QTY_RE.match(text)
    name, qty = (m.group("name").strip(), m.group("qty")) if m else (text, None)
    words = name.split()
    store = None
    if len(words) > 1 and words[-1].lower() in STORES:
        store = STORES[words[-1].lower()]
        words = words[:-1]
    elif len(words) > 1 and words[0].lower() in STORES:
        store = STORES[words[0].lower()]
        words = words[1:]
    name = " ".join(words)
    if qty is not None:
        name = f"{name} {qty}"
    return name, store


def shopping_items(text):
    """Split shopping input into [(store_heading_or_None, item_text)] pairs.

    A store keyword leading the whole query sets the default store for every
    comma-separated part; a part can still name its own store.
    """
    parts = [t.strip() for t in text.split(",") if t.strip()]
    default = None
    if parts:
        first = parts[0].split()
        if len(first) > 1 and first[0].lower() in STORES:
            default = STORES[first[0].lower()]
            parts[0] = " ".join(first[1:])
    out = []
    for part in parts:
        name, store = split_store(part)
        out.append((store or default, with_quantity(name)))
    return out


def find_section(lines, heading, level, lo=0, hi=None):
    """(start, end) of the section whose heading line equals `heading`.

    `end` is exclusive: the next heading of level <= `level` within
    lines[lo:hi], or `hi`. None if the heading is not found.
    """
    hi = len(lines) if hi is None else hi
    start = next((i for i in range(lo, hi) if lines[i].strip() == heading), None)
    if start is None:
        return None
    boundary = re.compile(r"^#{1,%d}\s" % level)
    end = next((i for i in range(start + 1, hi) if boundary.match(lines[i])), hi)
    return start, end


def insert_shopping(content, store, item):
    """Shopping mode: `## Handleliste` holds store-less items directly and
    one `### <store>` sub-section per store (created at the end of the
    Handleliste section when first used)."""
    lines = content.rstrip("\n").split("\n")
    sec = find_section(lines, f"## {SHOP_SECTION}", 2)
    if sec is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"## {SHOP_SECTION}", ""]
        sec = (len(lines) - 2, len(lines))
    start, end = sec
    if store:
        sub = find_section(lines, f"### {store}", 3, start + 1, end)
        if sub is None:
            pos = end
            while pos > start + 1 and lines[pos - 1].strip() == "":
                pos -= 1
            lines[pos:pos] = ["", f"### {store}", ""]
            start, end = pos + 1, pos + 3
        else:
            start, end = sub
    else:
        # Only the part of Handleliste above its first store sub-heading.
        end = next(
            (i for i in range(start + 1, end) if re.match(r"^###\s", lines[i])), end
        )
    last = end - 1
    while last > start and lines[last].strip() == "":
        last -= 1
    if last == start:
        lines[start + 1 : start + 1] = ["", item]
        at = start + 2
    else:
        lines.insert(last + 1, item)
        at = last + 1
    if at + 1 < len(lines) and lines[at + 1].startswith("#"):
        lines.insert(at + 1, "")  # keep a blank line before the next heading
    return "\n".join(lines) + "\n"


URL_RE = re.compile(r"https?://[^\s<>()\[\]]+")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
TRAILING_PUNCT = ".,;:!?'\""


def fetch_title(url, timeout=3):
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) AlfredInnboks/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if "html" not in (r.headers.get("Content-Type") or ""):
                return None
            raw = r.read(200_000)
        m = TITLE_RE.search(raw.decode("utf-8", "replace"))
        if not m:
            return None
        title = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
        return title or None
    except Exception:
        return None


def link_label(url):
    """Short label for a URL: `owner/repo` for GitHub, else page title or host/path."""
    m = re.match(r"https?://(?:www\.)?github\.com/([^/?#]+)/([^/?#]+)", url)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    title = fetch_title(url)
    if title:
        return title[:80]
    bare = re.sub(r"^https?://(?:www\.)?", "", url).rstrip("/")
    return bare[:80]


# Phrases that stay as plain text in front of a link instead of becoming
# its label: `sjekk ut Argus https://…` → `sjekk ut [Argus](https://…)`.
LEAD_PHRASES = (
    "sjekk ut", "sjekk", "les", "se på", "se", "test", "prøv", "husk",
    "og", "samt", "eller",
)
QUOTED_RE = re.compile(r'"([^"]+)"|“([^”]+)”|«([^»]+)»')


def label_from_segment(segment):
    """(label or None, text to keep before the link) for the text that
    precedes a URL."""
    seg = segment.strip()
    q = QUOTED_RE.search(seg)
    if q:
        label = next(g for g in q.groups() if g is not None).strip()
        keep = (seg[: q.start()] + " " + seg[q.end() :]).strip()
        return (label or None), keep
    low = seg.lower()
    for ph in sorted(LEAD_PHRASES, key=len, reverse=True):
        if low == ph:
            return None, seg
        if low.startswith(ph + " "):
            rest = seg[len(ph) + 1 :].strip()
            return (rest or None), seg[: len(ph)]
    return (seg or None), ""


def linkify(text):
    """Replace bare URLs in `text` with `[label](url)` markdown links, taking
    the label from the preceding text when it provides one."""
    out = []
    pos = 0
    for m in URL_RE.finditer(text):
        url = m.group(0)
        trail = ""
        while url and url[-1] in TRAILING_PUNCT:
            trail = url[-1] + trail
            url = url[:-1]
        label, keep = label_from_segment(text[pos : m.start()])
        if label is None:
            label = link_label(url)
        label = label.replace("]", "\\]")
        lead = ("" if pos == 0 else " ") + keep + (" " if keep else "")
        if pos == 0 and not keep:
            lead = ""
        out.append(f"{lead}[{label}]({url}){trail}")
        pos = m.end()
    out.append(text[pos:])
    return "".join(out).strip()


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
    content = load(path)
    if section:
        pairs = [(section, linkify(t.strip())) for t in text.split(",") if t.strip()]
        for sec, t in pairs:
            content = insert_item(content, sec, f"- [ ] {t}")
    else:  # shopping mode: store keywords → ### sub-heading, trailing number = qty
        pairs = [(store, linkify(t)) for store, t in shopping_items(text)]
        for store, t in pairs:
            content = insert_shopping(content, store, f"- [ ] {t}")
        pairs = [(store or SHOP_SECTION, t) for store, t in pairs]
    content = set_updated(content, now_stamp())
    if not content.endswith("\n"):
        content += "\n"

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    title = os.path.splitext(os.path.basename(path))[0]
    sections = list(dict.fromkeys(sec for sec, _ in pairs))
    notify(f"{title} → {' / '.join(sections)}", " · ".join(t for _, t in pairs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
