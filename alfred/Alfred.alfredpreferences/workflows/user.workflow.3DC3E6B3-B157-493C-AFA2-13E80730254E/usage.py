#!/usr/bin/env python3
"""Alfred Script Filter: viser Claude-forbruk (rate limits) slik /usage gjør i Claude Code.

Leser OAuth-tokenet Claude Code lagrer i nøkkelringen og spør samme endepunkt
som Claude Code bruker. Kjøres av Alfred med: /usr/bin/python3 usage.py
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

BAR_WIDTH = 20
LABELS = {
    "five_hour": "Current session",
    "seven_day": "All models",
    "seven_day_opus": "Opus",
    "seven_day_sonnet": "Sonnet",
    "seven_day_fable": "Fable",
    "extra_usage": "Extra usage",
}
ORDER = ["five_hour", "seven_day"]
ICON = {"type": "fileicon", "path": "/Applications/Claude.app"}


def emit(items, cache=True):
    out = {"items": items}
    if cache:
        out["cache"] = {"seconds": 30, "loosereload": True}
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0)


def fail(title, subtitle=""):
    emit([{"title": title, "subtitle": subtitle, "valid": False}], cache=False)


def token():
    try:
        raw = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        fail("Fant ikke Claude Code-innlogging i nøkkelringen", "Logg inn i Claude Code først (claude → /login)")
    try:
        return json.loads(raw)["claudeAiOauth"]["accessToken"]
    except (ValueError, KeyError, TypeError):
        fail("Uventet format på nøkkelring-oppføringen", "Kjør /login i Claude Code på nytt")


def fetch():
    fixture = os.environ.get("CLAUDE_USAGE_FIXTURE")
    if fixture:
        with open(fixture) as f:
            return json.load(f)
    req = urllib.request.Request(
        "https://api.anthropic.com/api/oauth/usage",
        headers={
            "Authorization": "Bearer " + token(),
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "alfred-claude-usage/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            fail("Tokenet er utløpt", "Åpne Claude Code, så fornyes det automatisk")
        fail("HTTP %d fra Anthropic" % e.code, e.read().decode(errors="replace")[:200])
    except (urllib.error.URLError, TimeoutError) as e:
        fail("Fikk ikke kontakt med api.anthropic.com", str(e))


def parse_ts(value):
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def reset_text(value):
    ts = parse_ts(value)
    if ts is None:
        return ""
    now = datetime.now(timezone.utc)
    delta = ts - now
    secs = int(delta.total_seconds())
    if secs <= 0:
        return "Resets now"
    if secs < 24 * 3600:
        hrs, rem = divmod(secs, 3600)
        mins = rem // 60
        if hrs:
            return "Resets in %d hr %d min" % (hrs, mins)
        return "Resets in %d min" % mins
    local = ts.astimezone()
    return "Resets " + local.strftime("%a %-I:%M %p")


def bar(pct):
    filled = max(0, min(BAR_WIDTH, round(pct / 100 * BAR_WIDTH)))
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def label(key):
    return LABELS.get(key, key.replace("_", " ").capitalize())


KIND_LABELS = {
    "session": "Current session",
    "weekly_all": "All models",
}
SEVERITY_NOTE = {"warning": "⚠️ Nærmer seg grensen", "critical": "🛑 Grensen er nådd"}


def limit_label(lim):
    kind = lim.get("kind", "")
    if kind in KIND_LABELS:
        return KIND_LABELS[kind]
    scope = lim.get("scope") or {}
    for part in ("model", "surface"):
        name = (scope.get(part) or {}).get("display_name")
        if name:
            return name
    return kind.replace("_", " ").capitalize()


def make_item(name, pct, resets_at, severity="normal"):
    item = {
        "title": "%-16s %s  %d%% used" % (name, bar(pct), round(pct)),
        "subtitle": " · ".join(s for s in (reset_text(resets_at), SEVERITY_NOTE.get(severity, "")) if s),
        "arg": "%s: %d%%" % (name, round(pct)),
        "valid": False,
    }
    if os.path.exists(ICON["path"]):
        item["icon"] = ICON
    return item


def items_from_limits(limits):
    items = []
    for lim in limits:
        pct = float(lim.get("percent") or 0)
        items.append(make_item(limit_label(lim), pct, lim.get("resets_at"), lim.get("severity") or "normal"))
    return items


def items_from_buckets(data):
    """Fallback for eldre svarformat uten "limits"-liste."""
    buckets = {k: v for k, v in data.items() if isinstance(v, dict) and v.get("utilization") is not None}
    keys = [k for k in ORDER if k in buckets] + sorted(k for k in buckets if k not in ORDER)
    return [make_item(label(k), float(buckets[k]["utilization"]), buckets[k].get("resets_at")) for k in keys]


def main():
    data = fetch()
    limits = data.get("limits")
    items = items_from_limits(limits) if isinstance(limits, list) and limits else items_from_buckets(data)

    extra = data.get("extra_usage") or {}
    if extra.get("is_enabled") and extra.get("utilization") is not None:
        items.append(make_item("Extra usage", float(extra["utilization"]), None))

    if not items:
        fail("Fant ingen forbruksdata i svaret", "Nøkler: " + ", ".join(sorted(data.keys())))
    emit(items)


if __name__ == "__main__":
    main()
