#!/usr/bin/env python3
"""Build a Dash docset from docs.fly.io and register it in Dash.

Fetches every page in the docs sitemap, keeps only the article content,
and indexes pages (Guide), flyctl commands (Command), command flags
(Option) and h2 headings (Section). Re-run to refresh the docset.

    build-fly-docset.py            # build + install into Dash (keyword fly:)
    build-fly-docset.py --limit 20 # quick test build
"""
import argparse
import html
import os
import plistlib
import re
import shutil
import sqlite3
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urljoin

SITE = "https://docs.fly.io"
NAME = "Fly.io"
BUNDLE = "fly"
KEYWORD = "fly"
OUT_DIR = os.path.expanduser("~/Library/Application Support/Dash/Generated")
DOCSET = os.path.join(OUT_DIR, f"{NAME}.docset")
DASH_APP = "/Applications/Setapp/Dash.app"
UA = "Mozilla/5.0 (Macintosh) fly-docset-builder/1.0"

CSS = """
:root { color-scheme: light dark; --fg:#1f2328; --bg:#fff; --muted:#59636e; --border:#d1d9e0; --code-bg:#f6f8fa; --link:#0969da; --accent:#7c3aed; }
@media (prefers-color-scheme: dark) { :root { --fg:#e6edf3; --bg:#0d1117; --muted:#9198a1; --border:#3d444d; --code-bg:#161b22; --link:#4493f8; --accent:#a78bfa; } }
html { font: 15px/1.6 -apple-system, "SF Pro Text", "Helvetica Neue", sans-serif; color:var(--fg); background:var(--bg); }
body { max-width: 52rem; margin: 0 auto; padding: 1.5rem 2rem 4rem; }
.eyebrow { color:var(--accent); font-size:.8rem; font-weight:600; text-transform:uppercase; letter-spacing:.04em; margin:0 0 .25rem; }
h1 { font-size:2rem; line-height:1.2; margin:0 0 .5rem; }
h2 { font-size:1.4rem; margin:2rem 0 .75rem; padding-bottom:.25rem; border-bottom:1px solid var(--border); }
h3 { font-size:1.15rem; margin:1.5rem 0 .5rem; }
h4 { font-size:1rem; margin:1.25rem 0 .5rem; }
h1 > div.absolute, h2 > div.absolute, h3 > div.absolute, h4 > div.absolute, h5 > div.absolute, h6 > div.absolute { display:none; }
a { color:var(--link); text-decoration:none; } a:hover { text-decoration:underline; }
p, ul, ol, table, pre, blockquote { margin: 0 0 1rem; }
span[data-as="p"] { display:block; margin:0 0 1rem; }
ul, ol { padding-left: 1.5rem; }
li { margin:.25rem 0; }
code { font: .875em ui-monospace, "SF Mono", Menlo, monospace; background:var(--code-bg); padding:.1em .35em; border-radius:4px; }
pre { background:var(--code-bg); border:1px solid var(--border); border-radius:6px; padding:.85rem 1rem; overflow:auto; line-height:1.45; }
pre code { background:none; padding:0; font-size:.85rem; white-space:pre; }
pre span[style] { color: inherit !important; }
table { border-collapse:collapse; width:100%; font-size:.95em; }
th, td { border:1px solid var(--border); padding:.4rem .6rem; text-align:left; vertical-align:top; }
th { background:var(--code-bg); }
img { max-width:100%; height:auto; }
blockquote { border-left:3px solid var(--border); margin-left:0; padding-left:1rem; color:var(--muted); }
hr { border:0; border-top:1px solid var(--border); margin:2rem 0; }
button, .hidden, [aria-hidden="true"].opacity-0, .sr-only { display:none !important; }
[class*="callout"] { border:1px solid var(--border); border-left:4px solid var(--accent); border-radius:6px; padding:.75rem 1rem; margin:0 0 1rem; }
[class*="callout"] > * { display:inline; }
[class*="callout"] p:first-child { margin-top:0; } [class*="callout"] p:last-child { margin-bottom:0; }
a.card, div.card { display:block; border:1px solid var(--border); border-radius:8px; padding:.85rem 1rem; margin:0 0 .75rem; color:inherit; }
a.card:hover { border-color:var(--accent); text-decoration:none; }
a.card h2, a.card h3 { margin:0 0 .25rem; border:0; padding:0; font-size:1rem; }
[role="tablist"] { display:flex; gap:.25rem; border-bottom:1px solid var(--border); margin:1rem 0 0; }
[role="tab"] { padding:.4rem .75rem; font-weight:600; color:var(--muted); }
[role="tab"][aria-selected="true"], [role="tab"][data-state="active"] { color:var(--fg); border-bottom:2px solid var(--accent); }
[role="tabpanel"] { padding:.75rem 0 0; }
details { border:1px solid var(--border); border-radius:6px; padding:.5rem .85rem; margin:0 0 .75rem; }
summary { cursor:pointer; font-weight:600; }
.code-block-header, [class*="code-block"] > div:first-child:not(:only-child) { font-size:.8rem; color:var(--muted); }
svg { max-width:1.25em; max-height:1.25em; vertical-align:middle; }
.footer { margin-top:3rem; font-size:.8rem; color:var(--muted); border-top:1px solid var(--border); padding-top:.75rem; }
"""

TAG_RE = re.compile(r"<[^>]+>")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def fetch(url, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                log(f"  ! {url}: {e}")
                return None


def text_of(fragment):
    t = html.unescape(TAG_RE.sub("", fragment))
    return re.sub(r"\s+", " ", t.replace("​", "")).strip()


def extract_div(page, id_):
    """Return the inner HTML of <div ... id="id_">, matching nested divs."""
    m = re.search(r'<div\b[^>]*\bid="%s"[^>]*>' % re.escape(id_), page)
    if not m:
        return None
    pos = m.end()
    depth = 1
    for tok in re.finditer(r"<div\b[^>]*>|</div>", page[pos:]):
        depth += 1 if tok.group(0).startswith("<div") else -1
        if depth == 0:
            return page[pos : pos + tok.start()]
    return page[pos:]


def load_sitemap():
    xml = fetch(f"{SITE}/sitemap.xml").decode()
    urls = re.findall(r"<loc>([^<]+)</loc>", xml)
    paths = []
    for u in urls:
        p = u.replace(SITE, "").strip("/")
        paths.append(p)
    if "" not in paths:
        paths.insert(0, "")
    return sorted(set(paths), key=lambda p: (p != "", p))


def load_redirects():
    raw = fetch("https://raw.githubusercontent.com/superfly/docs/main/docs.json")
    if not raw:
        return {}
    import json

    try:
        d = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}
    return {
        r["source"].strip("/"): r["destination"].strip("/")
        for r in d.get("redirects", [])
        if isinstance(r.get("source"), str) and isinstance(r.get("destination"), str)
    }


class Site:
    def __init__(self, paths, redirects):
        self.paths = set(paths)
        self.redirects = redirects

    def file_for(self, path):
        return "index.html" if path == "" else path + ".html"

    def resolve(self, target):
        """Map a root-relative link target to a local file, or None."""
        t = target.strip("/")
        if t.endswith("/index"):
            t = t[: -len("/index")]
        for _ in range(5):
            if t in self.paths:
                return self.file_for(t)
            nxt = self.redirects.get(t)
            if nxt is None or nxt == t:
                break
            t = nxt.strip("/")
        return None

    def rewrite_links(self, body, page_path):
        page_dir = os.path.dirname(self.file_for(page_path))

        def href(m):
            attr, url = m.group(1), m.group(2)
            if url.startswith("/") and not url.startswith("//"):
                path, _, frag = url.partition("#")
                local = self.resolve(path) if attr == "href" else None
                if local:
                    rel = os.path.relpath(local, page_dir) if page_dir else local
                    return f'{attr}="{rel}{"#" + frag if frag else ""}"'
                return f'{attr}="{SITE}{url}"'
            return m.group(0)

        return re.sub(r'\b(href|src|srcset)="([^"]*)"', href, body)


def dash_anchor(type_, name):
    return f'<a name="//apple_ref/cpp/{type_}/{quote(name, safe="")}" class="dashAnchor"></a>'


def process(site, path, page):
    """Return (html, entries) for one page; entries are (name, type, path)."""
    file = site.file_for(path)
    m = re.search(r'<h1\b[^>]*id="page-title"[^>]*>(.*?)</h1>', page, re.S)
    title = text_of(m.group(1)) if m else None
    if not title:
        m = re.search(r"<title>(.*?)</title>", page, re.S)
        title = text_of(m.group(1)).replace(" - Fly.io", "") if m else path
    m = re.search(r'class="eyebrow[^"]*"[^>]*>(.*?)</div>', page, re.S)
    eyebrow = text_of(m.group(1)) if m else ""
    body = extract_div(page, "content")
    is_api = False
    if body is None:
        # OpenAPI reference pages have no #content div; use the whole content
        # area minus the page header (which only repeats the title).
        body = extract_div(page, "content-area") or ""
        body = re.sub(r"<header\b.*?</header>", "", body, count=1, flags=re.S)
        is_api = bool(body)
        if not body:
            log(f"  ! no content: {path}")
    body = re.sub(r"<script\b.*?</script>", "", body, flags=re.S)

    is_command = (
        path.startswith("flyctl/") and title.startswith("fly ") and "Usage" in body
    ) or eyebrow == "Commands"
    page_type = "Command" if is_command else "Guide"
    entries = [(title, page_type, file)]
    if is_api:
        pm = re.search(r'class="method-pill[^"]*"[^>]*>(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)</div>(.*?)Try it', body, re.S)
        if pm:
            endpoint = text_of(pm.group(2)).replace(" ", "")
            entries.append((f"{pm.group(1)} {endpoint}", "Request", file))

    # h2 sections -> Section entries + Dash TOC anchors
    generic = {"Usage", "Options", "Global Options", "See Also"}

    def heading(m):
        tag, attrs, inner = m.group(1), m.group(2), m.group(3)
        idm = re.search(r'\bid="([^"]+)"', attrs)
        name = text_of(inner)
        if not idm or not name or idm.group(1).startswith(("_R_", ":R", "_r_")):
            return m.group(0)
        if tag == "h2" and not (is_command and name in generic):
            entries.append((name, "Section", f"{file}#{idm.group(1)}"))
        return dash_anchor("Section", name) + m.group(0)

    body = re.sub(r"<(h[23])\b([^>]*)>(.*?)</\1>", heading, body, flags=re.S)

    # flyctl flags -> Option entries
    if is_command:
        om = re.search(r'<h2\b[^>]*id="options"[^>]*>.*?<pre\b[^>]*>(.*?)</pre>', body, re.S)
        if om:
            seen = set()
            for line in html.unescape(TAG_RE.sub("", om.group(1))).splitlines():
                fm = re.match(r"^\s*(?:-\w,\s+)?(--[\w-]+)", line)
                if fm and fm.group(1) not in seen:
                    seen.add(fm.group(1))
                    entries.append((f"{title} {fm.group(1)}", "Option", f"{file}#options"))

    body = site.rewrite_links(body, page_path=path)
    depth = file.count("/")
    css = "../" * depth + "style.css"
    eyebrow_html = f'<div class="eyebrow">{html.escape(eyebrow)}</div>' if eyebrow else ""
    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(title)}</title>
<link rel="stylesheet" href="{css}">
</head><body>
{dash_anchor(page_type, title)}
{eyebrow_html}<h1>{html.escape(title)}</h1>
{body}
<div class="footer">Source: <a href="{SITE}/{path}">{SITE}/{path}</a></div>
</body></html>
"""
    return doc, entries


def write_icons(root):
    ico = fetch(f"{SITE}/images/logo/favicon.ico")
    tmp = os.path.join(root, "favicon.ico")
    ok = False
    if ico:
        with open(tmp, "wb") as f:
            f.write(ico)
        for name, size in (("icon.png", 16), ("icon@2x.png", 32)):
            r = subprocess.run(
                ["sips", "-s", "format", "png", "-z", str(size), str(size), tmp, "--out", os.path.join(root, name)],
                capture_output=True,
            )
            ok = r.returncode == 0 and os.path.exists(os.path.join(root, name))
        os.remove(tmp)
    if not ok:
        for name, url in (
            ("icon.png", "https://fly.io/phx/ui/images/favicon/favicon-16x16-6963a8113fc4dc87910c17c4279a9bd4.png"),
            ("icon@2x.png", "https://fly.io/phx/ui/images/favicon/favicon-32x32-803ad2058b86df3f8a9f8af1505a59d2.png"),
        ):
            data = fetch(url)
            if data:
                with open(os.path.join(root, name), "wb") as f:
                    f.write(data)


def build(limit=None, workers=16):
    paths = load_sitemap()
    if limit:
        paths = paths[:limit]
    redirects = load_redirects()
    site = Site(paths, redirects)
    log(f"{len(paths)} pages, {len(redirects)} redirects")

    tmp = DOCSET + ".build"
    shutil.rmtree(tmp, ignore_errors=True)
    docs = os.path.join(tmp, "Contents", "Resources", "Documents")
    os.makedirs(docs)
    with open(os.path.join(docs, "style.css"), "w") as f:
        f.write(CSS)

    def work(path):
        raw = fetch(f"{SITE}/{path}")
        if raw is None:
            return path, None
        return path, process(site, path, raw.decode("utf-8", "replace"))

    all_entries = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for path, result in ex.map(work, paths):
            done += 1
            if done % 100 == 0:
                log(f"  {done}/{len(paths)}")
            if result is None:
                continue
            doc, entries = result
            target = os.path.join(docs, site.file_for(path))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w") as f:
                f.write(doc)
            all_entries.extend(entries)

    db = sqlite3.connect(os.path.join(tmp, "Contents", "Resources", "docSet.dsidx"))
    db.execute("CREATE TABLE searchIndex(id INTEGER PRIMARY KEY, name TEXT, type TEXT, path TEXT)")
    db.execute("CREATE UNIQUE INDEX anchor ON searchIndex (name, type, path)")
    db.executemany("INSERT OR IGNORE INTO searchIndex(name, type, path) VALUES (?, ?, ?)", all_entries)
    db.commit()
    counts = dict(db.execute("SELECT type, count(*) FROM searchIndex GROUP BY type").fetchall())
    db.close()

    with open(os.path.join(tmp, "Contents", "Info.plist"), "wb") as f:
        plistlib.dump(
            {
                "CFBundleIdentifier": BUNDLE,
                "CFBundleName": NAME,
                "DocSetPlatformFamily": BUNDLE,
                "DashDocSetFamily": "dashtoc",
                "DashDocSetKeyword": KEYWORD,
                "DashDocSetFallbackURL": SITE + "/",
                "dashIndexFilePath": "index.html",
                "isDashDocset": True,
                "isJavaScriptEnabled": False,
            },
            f,
        )
    write_icons(tmp)

    shutil.rmtree(DOCSET, ignore_errors=True)
    os.rename(tmp, DOCSET)
    log(f"built {DOCSET}: {counts}")
    return DOCSET


def installed_in_dash():
    r = subprocess.run(["defaults", "read", "com.kapeli.dashdoc"], capture_output=True, text=True)
    return f"Generated/{NAME}.docset" in r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only build the first N pages (testing)")
    ap.add_argument("--no-install", action="store_true", help="skip opening the docset in Dash")
    args = ap.parse_args()
    build(limit=args.limit)
    if args.no_install:
        return
    if installed_in_dash():
        log("already registered in Dash; it will pick up the rebuilt files")
    else:
        app = DASH_APP if os.path.exists(DASH_APP) else "Dash"
        subprocess.run(["open", "-a", app, DOCSET])
        log(f"opened in Dash; keyword should become '{KEYWORD}:' (Dash > Settings > Docsets)")


if __name__ == "__main__":
    main()
