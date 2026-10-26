# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib>=3.9"]
# ///
"""Luftrapport som PDF for et tidsrom: sammendrag, funn og grafer per måling.

    report.py START END [--no-open]    ISO-tider i lokal tid, f.eks. 2026-10-19T21:00

Historikk hentes fra Airthings sitt eldre API (ext-api), som har målinger
tilbake til sensoren ble satt opp. Skyen er bare oppdatert til siste synk fra
telefonen, så resten fylles inn fra bin/airthings-ble sin logg når den finnes.
"""

import csv
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

import airthings as at  # noqa: E402

EXT = "https://ext-api.airthings.com/v1"
ORDER = ["radon", "co2", "voc", "temp", "humidity", "pressure"]
API_KEYS = {"radonShortTermAvg": "radon", "co2": "co2", "voc": "voc", "temp": "temp",
            "humidity": "humidity", "pressure": "pressure"}
WEEKDAYS = ["man", "tir", "ons", "tor", "fre", "lør", "søn"]
COLORS = ["#2e9e5b", "#e0b02a", "#d64541"]
LINE = "#2b6c8f"
OUT_DIR = os.environ.get("REPORT_DIR") or os.path.expanduser("~/Downloads")

# Fargede bånd i grafene: (fra, til, nivå)
BANDS = {
    "radon": [(0, 100, 0), (100, 150, 1), (150, None, 2)],
    "co2": [(0, 800, 0), (800, 1000, 1), (1000, None, 2)],
    "voc": [(0, 250, 0), (250, 2000, 1), (2000, None, 2)],
    "temp": [(None, 18, 1), (18, 25, 0), (25, None, 1)],
    "humidity": [(None, 25, 2), (25, 30, 1), (30, 60, 0), (60, 70, 1), (70, None, 2)],
}


def resolution(days):
    return "" if days <= 2 else "HOUR" if days <= 120 else "DAY"


def fetch_cloud(start, end):
    auth = {"Authorization": at.token()}
    dev = at.http(f"{EXT}/devices", auth)["devices"][0]
    sn, name = dev["id"], dev.get("segment", {}).get("name") or "Wave Plus"
    res = resolution((end - start).total_seconds() / 86400)
    fmt = "%Y-%m-%dT%H:%M:%S"
    data, cursor = defaultdict(list), None
    while True:
        url = (f"{EXT}/devices/{sn}/samples?start={start.astimezone(timezone.utc):{fmt}}"
               f"&end={end.astimezone(timezone.utc):{fmt}}")
        if res:
            url += f"&resolution={res}"
        if cursor:
            url += f"&cursor={cursor}"
        page = at.http(url, auth)
        for k, v in page.get("data", {}).items():
            data[k].extend(v)
        cursor = page.get("cursor")
        if not cursor:
            break
    series = {key: [] for key in ORDER}
    for i, ts in enumerate(data.get("time", [])):
        t = datetime.fromtimestamp(ts, timezone.utc).astimezone()
        for api_key, key in API_KEYS.items():
            vals = data.get(api_key)
            if vals and i < len(vals) and vals[i] is not None:
                series[key].append((t, float(vals[i])))
    return name, res, series


def merge_ble(series, res, start, end):
    """Legger til Bluetooth-målinger etter siste tidspunkt fra skyen."""
    path = os.path.join(at.CACHE_DIR, "ble-history.csv")
    last = max((s[-1][0] for s in series.values() if s), default=start)
    try:
        rows = list(csv.DictReader(open(path)))
    except OSError:
        return 0
    buckets = defaultdict(lambda: defaultdict(list))
    for row in rows:
        t = at.parse_time(row["time"]).astimezone()
        if not (last < t <= end and t >= start):
            continue
        if res == "HOUR":
            t = t.replace(minute=0, second=0, microsecond=0)
        elif res == "DAY":
            t = t.replace(hour=0, minute=0, second=0, microsecond=0)
        for api_key, key in API_KEYS.items():
            if row.get(api_key):
                buckets[t][key].append(float(row[api_key]))
    for t in sorted(buckets):
        for key, vals in buckets[t].items():
            series[key].append((t, mean(vals)))
    return len(buckets)


# --- analyse ---------------------------------------------------------------

def fnum(x):
    return at.fnum(x)


def stats(key, pts):
    vals = [v for _, v in pts]
    lv = [at.level(key, v) for v in vals]
    share = [lv.count(i) / len(lv) * 100 for i in range(3)] if lv[0] is not None else None
    tmin = min(pts, key=lambda p: p[1])
    tmax = max(pts, key=lambda p: p[1])
    return {"mean": mean(vals), "min": tmin, "max": tmax, "share": share, "levels": lv}


def when(t):
    return f"{WEEKDAYS[t.weekday()]} {t:%d.%m} kl. {t:%H:%M}"


def findings(st, series, step_hours):
    out = []
    for key in ORDER:
        if key not in st:
            continue
        s, label, unit = st[key], at.SENSORS[key][0], at.SENSORS[key][1]
        if key in ("co2", "voc") and s["share"] and s["share"][2] > 0:
            bad = [t for (t, _), lv in zip(series[key], s["levels"]) if lv == 2]
            hours = defaultdict(int)
            for t in bad:
                hours[t.hour] += 1
            top = sorted(sorted(hours, key=hours.get, reverse=True)[:3])
            limit = "1 000 ppm" if key == "co2" else "2 000 ppb"
            out.append(f"{label} var over {limit} i ca. {fnum(len(bad) * step_hours)} t "
                       f"({fnum(s['share'][2])} % av tiden), oftest rundt kl. {', '.join(f'{h:02d}' for h in top)}.")
        if key in ("co2", "voc", "radon"):
            t, v = s["max"]
            out.append(f"Høyeste {label}: {fnum(v)} {unit} {when(t)}.")
        if key == "radon":
            m = s["mean"]
            verdict = ("under tiltaksnivået på 100 Bq/m³" if m < 100 else
                       "over tiltaksnivået på 100 Bq/m³ – vurder tiltak" if m < 200 else
                       "over grenseverdien på 200 Bq/m³ – tiltak anbefales")
            out.append(f"Snitt radon {fnum(m)} Bq/m³ er {verdict} (DSA). Radon bør vurderes over minst 2 måneder.")
        if key == "humidity" and s["share"]:
            dry = sum(1 for _, v in series[key] if v < 30) / len(series[key]) * 100
            wet = sum(1 for _, v in series[key] if v > 60) / len(series[key]) * 100
            if dry >= 5:
                out.append(f"Tørr luft (under 30 %) {fnum(dry)} % av tiden.")
            if wet >= 5:
                out.append(f"Fuktig luft (over 60 %) {fnum(wet)} % av tiden – følg med på mugg.")
        if key == "temp":
            out.append(f"Temperatur mellom {fnum(s['min'][1])} og {fnum(s['max'][1])} °C, snitt {fnum(s['mean'])} °C.")
    return out


def verdict(st):
    worst = 0
    for key in ("radon", "co2", "voc", "humidity"):
        if key in st and st[key]["share"]:
            sh = st[key]["share"]
            worst = max(worst, 2 if sh[2] > 10 else 1 if sh[1] + sh[2] > 20 else 0)
    return worst, ["God luft i perioden", "Stort sett god luft, men noen perioder å se på",
                   "Luften var dårlig en del av tiden"][worst]


# --- PDF -------------------------------------------------------------------

def setup():
    plt.rcParams.update({"font.family": "Helvetica Neue", "font.size": 9, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.edgecolor": "#999", "axes.titleweight": "bold",
                         "axes.titlesize": 11, "axes.titlelocation": "left"})


def date_axis(ax, days):
    if days <= 2:
        ax.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 3)))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    elif days <= 31:
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, round(days / 10))))
        ax.xaxis.set_major_formatter(plt.FuncFormatter(
            lambda x, _: (lambda d: f"{WEEKDAYS[d.weekday()]}\n{d:%d.%m}")(mdates.num2date(x).astimezone())))
    else:
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=10))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))


def page_summary(pdf, name, start, end, st, found, coverage, ble_points, series):
    fig = plt.figure(figsize=(8.27, 11.69))
    lvl, text = verdict(st)
    fig.text(0.07, 0.94, f"Luftrapport – {name}", fontsize=22, weight="bold")
    fig.text(0.07, 0.915, f"{start:%d.%m.%Y %H:%M} – {end:%d.%m.%Y %H:%M}  ·  Airthings Wave Plus", fontsize=10, color="#555")
    fig.patches.append(plt.Rectangle((0.07, 0.845), 0.86, 0.05, transform=fig.transFigure,
                                     color=COLORS[lvl], alpha=0.15, zorder=0))
    fig.text(0.09, 0.863, text, fontsize=14, weight="bold", color=COLORS[lvl])

    rows = []
    for key in ORDER:
        if key not in st:
            continue
        s, unit = st[key], at.SENSORS[key][1]
        sh = s["share"]
        rows.append([at.SENSORS[key][0], f"{fnum(s['mean'])} {unit}", f"{fnum(s['min'][1])}", f"{fnum(s['max'][1])}",
                     *([f"{fnum(x)} %" for x in sh] if sh else ["–", "–", "–"])])
    h = 0.026 * (len(rows) + 1)
    ax = fig.add_axes([0.07, 0.82 - h, 0.86, h])
    ax.axis("off")
    tbl = ax.table(cellText=rows, colLabels=["Måling", "Snitt", "Min", "Maks", "Bra", "Middels", "Dårlig"],
                   loc="upper left", cellLoc="left", colLoc="left",
                   colWidths=[0.22, 0.18, 0.11, 0.11, 0.12, 0.13, 0.13])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10)
    tbl.scale(1, 1.6)
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#ddd")
        cell.visible_edges = "B"
        if r == 0:
            cell.set_text_props(weight="bold")
        elif c in (4, 5, 6) and cell.get_text().get_text() not in ("–", "0 %"):
            cell.set_text_props(color=COLORS[c - 4], weight="bold" if c > 4 else "normal")

    y = 0.82 - h - 0.05
    fig.text(0.07, y, "Funn", fontsize=13, weight="bold")
    y -= 0.025
    for line in found:
        for i, part in enumerate(wrap(line, 95)):
            fig.text(0.09 if i else 0.07, y, ("• " if i == 0 else "  ") + part, fontsize=10)
            y -= 0.02
        y -= 0.006
    day_table(fig, y - 0.03, series)

    note = f"Datadekning {fnum(coverage)} % av perioden."
    if ble_points:
        note += f" {ble_points} {'måling' if ble_points == 1 else 'målinger'} etter siste synk til skyen er lest direkte over Bluetooth."
    fig.text(0.07, 0.07, note, fontsize=8, color="#777")
    fig.text(0.07, 0.055, "Grenser: Airthings (bra/middels/dårlig) og DSA for radon (tiltaksnivå 100, grenseverdi 200 Bq/m³).",
             fontsize=8, color="#777")
    pdf.savefig(fig)
    plt.close(fig)


def day_table(fig, top, series):
    """Snitt per dag (eller uke ved lange perioder) med fargede celler."""
    keys = [k for k in ("co2", "voc", "radon", "temp", "humidity") if k in series]
    fit = int((top - 0.1) / 0.019) - 1
    span = (series[keys[0]][-1][0] - series[keys[0]][0][0]).days
    weekly = span + 1 > fit
    groups = defaultdict(lambda: defaultdict(list))
    for k in keys:
        for t, v in series[k]:
            g = t.date() - timedelta(days=t.weekday()) if weekly else t.date()
            groups[g][k].append(v)
    days = sorted(groups)[-fit:]
    if not days or top < 0.15:
        return
    fig.text(0.07, top, "Uke for uke" if weekly else "Dag for dag", fontsize=13, weight="bold")
    rows, colors = [], []
    for d in days:
        label = f"uke {d.isocalendar()[1]}" if weekly else f"{WEEKDAYS[d.weekday()]} {d:%d.%m}"
        row, col = [label], ["white"]
        for k in keys:
            vals = groups[d].get(k)
            if not vals:
                row.append("–")
                col.append("white")
                continue
            m = mean(vals)
            peak = f" / {fnum(max(vals))}" if k in ("co2", "voc") else ""
            row.append(f"{fnum(m)}{peak}")
            lv = at.level(k, max(vals) if k in ("co2", "voc") else m)
            col.append(COLORS[lv] + "22" if lv else "white")
        rows.append(row)
        colors.append(col)
    names = {"co2": "CO₂ snitt / maks", "voc": "VOC snitt / maks", "radon": "Radon", "temp": "Temp °C", "humidity": "Fukt %"}
    h = 0.019 * (len(rows) + 1)
    ax = fig.add_axes([0.07, top - 0.015 - h, 0.86, h])
    ax.axis("off")
    tbl = ax.table(cellText=rows, colLabels=[""] + [names[k] for k in keys], cellColours=colors,
                   loc="upper left", cellLoc="left", colLoc="left")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8.5)
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#e5e5e5")
        if r == 0:
            cell.set_text_props(weight="bold")


def wrap(text, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return lines + [cur]


def page_charts(pdf, keys, series, st, days, step_hours):
    fig = plt.figure(figsize=(8.27, 11.69))
    gs = fig.add_gridspec(len(keys), 2, width_ratios=[3.2, 1], left=0.08, right=0.96, top=0.95, bottom=0.05,
                          hspace=0.45, wspace=0.18)
    for row, key in enumerate(keys):
        pts = series[key]
        label, unit = at.SENSORS[key][0], at.SENSORS[key][1]
        ts, vs = [t for t, _ in pts], [v for _, v in pts]
        ax = fig.add_subplot(gs[row, 0])
        lo, hi = min(vs), max(vs)
        pad = (hi - lo) * 0.15 or 1
        ylo, yhi = lo - pad, hi + pad
        for a, b, lv in BANDS.get(key, []):
            ax.axhspan(ylo if a is None else a, yhi if b is None else b, color=COLORS[lv], alpha=0.08, lw=0)
        # bryt linjen der det mangler målinger, i stedet for å trekke en rett strek over hullet
        steps = sorted(b[0] - a[0] for a, b in zip(pts, pts[1:])) or [timedelta(hours=step_hours)]
        gap = max(steps[len(steps) // 2], timedelta(hours=step_hours)) * 3
        pts_t, pts_v = [], []
        for i, (t, v) in enumerate(pts):
            if i and t - pts[i - 1][0] > gap:
                pts_t.append(t - (t - pts[i - 1][0]) / 2)
                pts_v.append(float("nan"))
            pts_t.append(t)
            pts_v.append(v)
        ax.plot(pts_t, pts_v, color=LINE, lw=1.1 if len(ts) < 400 else 0.7)
        lone = [i for i in range(len(pts_v)) if pts_v[i] == pts_v[i]
                and (i == 0 or pts_v[i - 1] != pts_v[i - 1]) and (i + 1 == len(pts_v) or pts_v[i + 1] != pts_v[i + 1])]
        ax.plot([pts_t[i] for i in lone], [pts_v[i] for i in lone], "o", color=LINE, ms=2.5)
        if days > 3:
            daily = defaultdict(list)
            for t, v in pts:
                daily[t.date()].append(v)
            dts = [datetime.combine(d, datetime.min.time()).astimezone() + timedelta(hours=12) for d in sorted(daily)]
            ax.plot(dts, [mean(daily[d]) for d in sorted(daily)], color="#333", lw=1.6, ls="--", label="døgnsnitt")
            ax.legend(loc="upper right", frameon=False, fontsize=8)
        ax.set_ylim(ylo, yhi)
        ax.set_xlim(ts[0], ts[-1])
        ax.set_title(f"{label} ({unit})   snitt {fnum(st[key]['mean'])} · maks {fnum(st[key]['max'][1])}")
        ax.grid(axis="y", color="#eee")
        date_axis(ax, days)

        if key == "pressure":  # følger været, ikke døgnet
            ax.set_position(gs[row, :].get_position(fig))
            continue
        prof = defaultdict(list)
        for t, v in pts:
            prof[t.hour].append(v)
        hours = sorted(prof)
        means = [mean(prof[h]) for h in hours]
        ax2 = fig.add_subplot(gs[row, 1])
        cols = [COLORS[at.level(key, m)] if at.level(key, m) is not None else LINE for m in means]
        ax2.bar(hours, means, color=cols, width=0.8, alpha=0.85)
        ax2.set_xticks([0, 6, 12, 18, 23])
        ax2.set_title("Døgnprofil", fontsize=9)
        lo2, hi2 = min(means), max(means)
        base = 0 if key in ("radon", "co2", "voc") else lo2 - (hi2 - lo2) * 0.3 - 0.01
        ax2.set_ylim(base, hi2 + (hi2 - lo2) * 0.1 + 0.01)
        ax2.set_xlabel("time på døgnet", fontsize=7)
        ax2.grid(axis="y", color="#eee")
    pdf.savefig(fig)
    plt.close(fig)


def notify(msg):
    esc = msg.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(["osascript", "-e", f'display notification "{esc}" with title "Luftrapport"'], capture_output=True)


def main():
    start = datetime.fromisoformat(sys.argv[1]).astimezone()
    end = datetime.fromisoformat(sys.argv[2]).astimezone()
    days = (end - start).total_seconds() / 86400
    name, res, series = fetch_cloud(start, end)
    ble_points = merge_ble(series, res, start, end)
    series = {k: v for k, v in series.items() if v}
    if not series:
        notify("Fant ingen målinger i perioden")
        return 1
    st = {k: stats(k, v) for k, v in series.items()}
    step_hours = {"": 5 / 60, "HOUR": 1, "DAY": 24}[res]
    expected = max(1, (end - start).total_seconds() / 3600 / step_hours)
    coverage = min(100, max(len(v) for v in series.values()) / expected * 100)

    setup()
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"Luftrapport {name} {start:%d.%m}–{end:%d.%m.%Y}.pdf")
    with PdfPages(path) as pdf:
        page_summary(pdf, name, start, end, st, findings(st, series, step_hours), coverage, ble_points, series)
        keys = [k for k in ORDER if k in series]
        for i in range(0, len(keys), 3):
            page_charts(pdf, keys[i:i + 3], series, st, days, step_hours)
        info = pdf.infodict()
        info["Title"] = f"Luftrapport {name}"
    if "--no-open" not in sys.argv:
        subprocess.run(["open", path])
    print(path)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except at.AirthingsError as e:
        notify(str(e))
        sys.exit(1)
