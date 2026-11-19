#!/usr/bin/env python3
"""Alfred Script Filter: viser Codex-forbruk (rate limits) slik /status gjør i Codex CLI.

Leser tokenet Codex CLI lagrer i ~/.codex/auth.json (ChatGPT-innlogging) og spør
samme endepunkt som Codex bruker. Kjøres av Alfred med: /usr/bin/python3 usage.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BAR_WIDTH = 20
AUTH = os.path.join(os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex")), "auth.json")
URL = "https://chatgpt.com/backend-api/wham/usage"


def emit(items, cache=True):
    out = {"items": items}
    if cache:
        out["cache"] = {"seconds": 30, "loosereload": True}
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0)


def fail(title, subtitle=""):
    emit([{"title": title, "subtitle": subtitle, "valid": False}], cache=False)


def credentials():
    try:
        with open(AUTH) as f:
            tokens = json.load(f).get("tokens") or {}
    except FileNotFoundError:
        fail("Fant ikke ~/.codex/auth.json", "Logg inn i Codex først (codex login)")
    except ValueError:
        fail("Klarte ikke å lese ~/.codex/auth.json")
    if not tokens.get("access_token"):
        fail("Ingen ChatGPT-innlogging i Codex", "Codex bruker API-nøkkel; rate limits gjelder bare ChatGPT-planer")
    return tokens["access_token"], tokens.get("account_id")


def fetch():
    fixture = os.environ.get("CODEX_USAGE_FIXTURE")
    if fixture:
        with open(fixture) as f:
            return json.load(f)
    access, account = credentials()
    headers = {
        "Authorization": "Bearer " + access,
        "User-Agent": "alfred-codex-usage/1.0",
        "originator": "codex_cli_rs",
    }
    if account:
        headers["ChatGPT-Account-Id"] = account
    try:
        with urllib.request.urlopen(urllib.request.Request(URL, headers=headers), timeout=10) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            fail("Tokenet er utløpt", "Kjør codex en gang, så fornyes det automatisk")
        fail("HTTP %d fra chatgpt.com" % e.code, e.read().decode(errors="replace")[:200])
    except (urllib.error.URLError, TimeoutError) as e:
        fail("Fikk ikke kontakt med chatgpt.com", str(e))


def reset_text(window):
    reset_at = window.get("reset_at")
    if reset_at is None and window.get("reset_after_seconds") is not None:
        reset_at = time.time() + window["reset_after_seconds"]
    if reset_at is None:
        return ""
    ts = datetime.fromtimestamp(reset_at, tz=timezone.utc)
    secs = int((ts - datetime.now(timezone.utc)).total_seconds())
    if secs <= 0:
        return "Resets now"
    if secs < 24 * 3600:
        hrs, rem = divmod(secs, 3600)
        mins = rem // 60
        return "Resets in %d hr %d min" % (hrs, mins) if hrs else "Resets in %d min" % mins
    return "Resets " + ts.astimezone().strftime("%a %-I:%M %p")


def bar(pct):
    filled = max(0, min(BAR_WIDTH, round(pct / 100 * BAR_WIDTH)))
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def window_label(window, fallback):
    secs = window.get("limit_window_seconds")
    if secs == 18000:
        return "Current session"
    if secs == 604800:
        return "Weekly"
    if secs:
        hrs = secs / 3600
        return "%d-hour" % hrs if hrs < 48 else "%d-day" % (hrs / 24)
    return fallback


def make_item(name, window, note=""):
    pct = float(window.get("used_percent") or 0)
    return {
        "title": "%-16s %s  %d%% used" % (name, bar(pct), round(pct)),
        "subtitle": " · ".join(s for s in (reset_text(window), note) if s),
        "arg": "%s: %d%%" % (name, round(pct)),
        "valid": False,
    }


def items_for(limit, prefix=""):
    items = []
    if not isinstance(limit, dict):
        return items
    note = "🛑 Grensen er nådd" if limit.get("limit_reached") else ""
    for key, fallback in (("primary_window", "Primary"), ("secondary_window", "Secondary")):
        window = limit.get(key)
        if isinstance(window, dict):
            items.append(make_item(prefix + window_label(window, fallback), window, note))
    return items


def main():
    data = fetch()
    items = items_for(data.get("rate_limit"))
    items += items_for(data.get("code_review_rate_limit"), "Review ")
    for extra in data.get("additional_rate_limits") or []:
        if isinstance(extra, dict):
            name = extra.get("limit_name") or extra.get("metered_feature") or "Extra"
            items += items_for(extra.get("rate_limit") or extra, name + " ")

    credits = data.get("credits") or {}
    if credits.get("has_credits"):
        bal = "unlimited" if credits.get("unlimited") else credits.get("balance")
        items.append({"title": "Credits: %s" % bal, "valid": False})

    if not items:
        fail("Fant ingen forbruksdata i svaret", "Nøkler: " + ", ".join(sorted(data.keys())))
    plan = data.get("plan_type")
    if plan:
        items[0]["subtitle"] = " · ".join(s for s in (items[0]["subtitle"], "ChatGPT " + plan.capitalize()) if s)
    emit(items)


if __name__ == "__main__":
    main()
