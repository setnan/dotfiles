#!/usr/bin/env python3
"""Alfred: maskinstatus – disk, minne, CPU, prosesser, strøm, nett og mobil-riggen.

  stats.py list [filter]   Script Filter (oppdaterer seg selv hvert 2. sekund)
  stats.py <handling>      Enter: open:<app/url> åpner, kill:<pid> avslutter en prosess

CPU-bruk regnes som differansen i prosessortikk siden forrige kjøring (lagres i
workflowens cache-mappe), så første visning måler over et kort øyeblikk.
"""
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import time

GB = 1024 ** 3
PATH = "/opt/homebrew/bin:/usr/sbin:/usr/bin:/bin:/sbin"
ACTIVITY = "/System/Applications/Utilities/Activity Monitor.app"
DISKUTIL = "/System/Applications/Utilities/Disk Utility.app"


def sh(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5,
                              env={**os.environ, "PATH": PATH}).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def sysctl(name):
    return sh("sysctl", "-n", name)


def bar(p, w=10):
    f = max(0, min(w, round(p * w / 100)))
    return "▰" * f + "▱" * (w - f)


def gb(b):
    return f"{b / GB:.1f}".replace(".", ",")


def icon(name):
    return {"path": f"icons/{name}.png"}


def item(title, sub, ic, arg="", match="", copy=None, **kw):
    it = {"title": title, "subtitle": sub, "icon": icon(ic), "arg": arg, "valid": bool(arg),
          "match": f"{title} {match}", "text": {"copy": copy or f"{title} – {sub}", "largetype": f"{title}\n{sub}"}}
    it.update(kw)
    return it


# ---- målinger -------------------------------------------------------------

def disks():
    data_dev = None
    out = []
    mounts = ["/System/Volumes/Data"] + [f"/Volumes/{v}" for v in sorted(os.listdir("/Volumes"))]
    for m in mounts:
        lines = sh("df", "-k", m).splitlines()
        if len(lines) < 2 or not lines[1].startswith("/dev/disk"):
            continue
        dev = re.sub(r"s\d.*$", "", lines[1].split()[0].replace("/dev/", ""))
        if m == "/System/Volumes/Data":
            data_dev = dev
        elif dev == data_dev:
            continue  # det interne volumet under et annet navn
        u = shutil.disk_usage(m)
        if u.total < 4 * GB:
            continue  # åpne .dmg-er
        out.append(("Intern disk" if m == "/System/Volumes/Data" else os.path.basename(m), u))
    return out


def memory():
    vm = sh("vm_stat")
    ps = int(re.search(r"page size of (\d+)", vm).group(1))
    pg = {k.strip().strip('"'): int(v.strip(" .")) for k, v in re.findall(r"^([^:\n]+):\s+(\d+)\.", vm, re.M)}
    app = (pg["Anonymous pages"] - pg["Pages purgeable"]) * ps
    wired = pg["Pages wired down"] * ps
    comp = pg["Pages occupied by compressor"] * ps
    cache = pg["File-backed pages"] * ps
    total = int(sysctl("hw.memsize"))
    swap = re.search(r"used = ([\d.]+)M", sysctl("vm.swapusage"))
    return {"total": total, "used": app + wired + comp, "app": app, "wired": wired, "comp": comp,
            "cache": cache, "pressure": 100 - int(sysctl("kern.memorystatus_level") or 100),
            "swap": float(swap.group(1)) * 1024 ** 2 if swap else 0}


def cpu_ticks():
    """Summerte (bruker+system+nice, total) tikk for alle kjerner via host_processor_info."""
    lib = ctypes.CDLL("/usr/lib/libSystem.dylib")
    lib.mach_host_self.restype = ctypes.c_uint
    lib.mach_task_self.restype = ctypes.c_uint
    count, info, n = ctypes.c_uint(), ctypes.POINTER(ctypes.c_int)(), ctypes.c_uint()
    if lib.host_processor_info(lib.mach_host_self(), 2, ctypes.byref(count), ctypes.byref(info), ctypes.byref(n)):
        return None
    busy = total = 0
    for i in range(count.value):
        u, s, idle, nice = (info[i * 4 + k] & 0xFFFFFFFF for k in range(4))
        busy += u + s + nice
        total += u + s + idle + nice
    lib.vm_deallocate(lib.mach_task_self(), ctypes.cast(info, ctypes.c_void_p), ctypes.c_size_t(n.value * 4))
    return busy, total


def cpu_percent():
    cache = os.path.join(os.environ.get("alfred_workflow_cache", "/tmp/no.etnan.stats"), "cpu.json")
    now = cpu_ticks()
    if not now:
        return None
    prev = None
    try:
        with open(cache) as f:
            prev = json.load(f)
        if time.time() - prev["t"] > 30:
            prev = None
    except (OSError, ValueError, KeyError):
        pass
    if not prev:
        time.sleep(0.3)
        prev, now = {"busy": now[0], "total": now[1]}, cpu_ticks()
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w") as f:
        json.dump({"busy": now[0], "total": now[1], "t": time.time()}, f)
    dt = now[1] - prev["total"]
    return 100 * (now[0] - prev["busy"]) / dt if dt > 0 else 0


def top_procs(key, n=3):
    col = "rss" if key == "mem" else "pcpu"
    rows = []
    for line in sh("ps", "-Aceo", f"pid=,{col}=,comm=").splitlines():
        pid, val, name = line.split(None, 2)
        rows.append((float(val), int(pid), name))
    return sorted(rows, reverse=True)[:n]


def uptime():
    boot = int(re.search(r"sec = (\d+)", sysctl("kern.boottime")).group(1))
    s = int(time.time()) - boot
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    return (f"{d} d " if d else "") + f"{h} t {m} min"


def battery():
    out = sh("pmset", "-g", "batt")
    m = re.search(r"(\d+)%;\s*([^;]+);\s*([^;\n]+)", out)
    if not m:
        return None
    pct, state, rest = int(m.group(1)), m.group(2).strip(), m.group(3).replace(" present: true", "").strip()
    state = {"charging": "lader", "discharging": "på batteri", "charged": "fulladet",
             "AC attached": "lader ikke", "finishing charge": "lader"}.get(state, state)
    rest = "" if rest in ("not charging", "(no estimate)") else rest.replace(" remaining", " igjen")
    ac = "AC Power" in out
    return pct, state, rest, ac


def tailscale_ip():
    for exe in ("tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        ip = sh(exe, "ip", "-4")
        if ip:
            return ip.splitlines()[0]
    return None


# ---- Script Filter --------------------------------------------------------

def level(p, warn=75, crit=90):
    return " ⚠︎" if p >= crit else (" ·" if p >= warn else "")


def list_items():
    items = []
    cpu = cpu_percent()
    load = sysctl("vm.loadavg").strip("{} ").split()[:3]
    ncpu = sysctl("hw.ncpu")
    if cpu is not None:
        items.append(item(f"CPU {cpu:.0f} %{level(cpu)}  {bar(cpu)}",
                          f"{ncpu} kjerner · last {' '.join(load)} · Enter: Aktivitetsmonitor",
                          "cpu", f"open:{ACTIVITY}", "cpu prosessor last"))

    m = memory()
    p = 100 * m["used"] / m["total"]
    items.append(item(f"Minne {gb(m['used'])} av {gb(m['total'])} GB ({p:.0f} %){level(p, 85, 95)}  {bar(p)}",
                      f"app {gb(m['app'])} · kablet {gb(m['wired'])} · komprimert {gb(m['comp'])} · cache {gb(m['cache'])} GB",
                      "memory", f"open:{ACTIVITY}", "minne ram memory"))
    pr = m["pressure"]
    tilstand = "kritisk" if pr >= 80 else "forhøyet" if pr >= 50 else "normal"
    items.append(item(f"Minnetrykk {tilstand} ({pr} %)  {bar(pr)}",
                      f"swap {gb(m['swap'])} GB brukt · høyt trykk betyr at Macen må komprimere/bytte til disk",
                      "pressure", f"open:{ACTIVITY}", "minne trykk pressure swap ram"))

    for name, u in disks():
        p = 100 * u.used / u.total
        items.append(item(f"{name}: {gb(u.free)} GB ledig{level(p)}  {bar(p)}",
                          f"{gb(u.used)} av {gb(u.total)} GB brukt ({p:.0f} %) · Enter: Lagring i Systeminnstillinger",
                          "disk", "open:x-apple.systempreferences:com.apple.settings.Storage", "disk lagring plass ssd",
                          mods={"cmd": {"subtitle": "Åpne Diskverktøy", "arg": f"open:{DISKUTIL}", "valid": True}}))

    for val, pid, name in top_procs("mem"):
        items.append(item(f"{name}  {gb(val * 1024)} GB", f"Mest minne · pid {pid} · Enter: Aktivitetsmonitor · ⌥: avslutt",
                          "proc", f"open:{ACTIVITY}", "prosess process topp minne ram",
                          mods={"alt": {"subtitle": f"Avslutt {name} (pid {pid})", "arg": f"kill:{pid}", "valid": True}}))
    for val, pid, name in top_procs("cpu"):
        items.append(item(f"{name}  {val:.0f} % CPU", f"Mest CPU · pid {pid} · Enter: Aktivitetsmonitor · ⌥: avslutt",
                          "proc", f"open:{ACTIVITY}", "prosess process topp cpu",
                          mods={"alt": {"subtitle": f"Avslutt {name} (pid {pid})", "arg": f"kill:{pid}", "valid": True}}))

    b = battery()
    lungo = "(Lungo)" in sh("pmset", "-g", "assertions")
    awake = "Lungo holder Macen våken" if lungo else "Lungo av"
    if b:
        pct, state, rest, ac = b
        items.append(item(f"Batteri {pct} % · {state}{' · ' + rest if rest else ''}",
                          f"{'Strømadapter' if ac else 'Batteri'} · {awake} · Enter: Batteri-innstillinger",
                          "battery", "open:x-apple.systempreferences:com.apple.Battery-Settings.extension",
                          "batteri strøm battery lader lungo"))

    lan = sh("ipconfig", "getifaddr", "en0") or "–"
    ts = tailscale_ip()
    items.append(item(f"Nett: LAN {lan} · Tailscale {ts or 'nede'}",
                      "Enter kopierer Tailscale-IP" if ts else "Tailscale svarer ikke",
                      "network", f"copy:{ts}" if ts else "", "nett ip tailscale lan network wifi",
                      copy=ts or lan))

    rc = subprocess.run(["tmux", "has-session", "-t", "=rc"], capture_output=True,
                        env={**os.environ, "PATH": PATH}).returncode == 0 if shutil.which("tmux", path=PATH) else False
    mosh = len(sh("pgrep", "-x", "mosh-server").split())
    claude = len(sh("pgrep", "-x", "claude").split())
    sess = [s for s in sh("tmux", "ls", "-F", "#S").split() if s != "rc"]
    items.append(item(f"Rigg: Remote Control {'kjører' if rc else 'nede'} · mosh {mosh} · claude {claude}",
                      f"tmux: {' '.join(sess) if sess else 'ingen andre økter'}", "rig", "",
                      "rigg mosh tmux claude remote mobil"))

    host = sh("scutil", "--get", "ComputerName") or os.uname().nodename
    items.append(item(f"{host} · oppe {uptime()}",
                      f"macOS {sh('sw_vers', '-productVersion')} · {sysctl('machdep.cpu.brand_string')}",
                      "uptime", "", "oppetid uptime macos versjon maskin"))

    print(json.dumps({"rerun": 2, "items": items}, ensure_ascii=False))


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "list"
    if arg == "list":
        return list_items()
    kind, _, val = arg.partition(":")
    if kind == "open":
        subprocess.run(["open", val])
    elif kind == "copy":
        subprocess.run(["pbcopy"], input=val, text=True)
    elif kind == "kill":
        subprocess.run(["kill", val])


if __name__ == "__main__":
    sys.exit(main() or 0)
