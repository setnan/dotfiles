#!/usr/bin/env python3
"""Alfred script filter: list running processes, unresponsive apps first.

Usage: kill_list.py [query]
"""
import ctypes
import json
import os
import re
import subprocess
import sys
import time
from ctypes import POINTER, byref, c_bool, c_char_p, c_float, c_int, c_uint32, c_void_p

AX_TIMEOUT = 0.4          # seconds an app gets to answer an accessibility request
AX_CANNOT_COMPLETE = -25204
MAX_ITEMS = 150
GENERIC_ICON = ("/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/"
                "ExecutableBinaryIcon.icns")


# --------------------------------------------------------------------------- AX
def make_ax_probe():
    """Return (trusted, probe) where probe(pid) -> 'hung' | 'ok' | 'noax'.

    A hung GUI app owns an accessibility server but never answers, so the
    request runs into the timeout with kAXErrorCannotComplete. Processes
    without an AX server (helpers, daemons) return the same error instantly,
    which is how the two are told apart.
    """
    try:
        app_services = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        core_foundation = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    except OSError:
        return False, None

    app_services.AXIsProcessTrusted.restype = c_bool
    app_services.AXUIElementCreateApplication.restype = c_void_p
    app_services.AXUIElementCreateApplication.argtypes = [c_int]
    app_services.AXUIElementSetMessagingTimeout.restype = c_int
    app_services.AXUIElementSetMessagingTimeout.argtypes = [c_void_p, c_float]
    app_services.AXUIElementCopyAttributeValue.restype = c_int
    app_services.AXUIElementCopyAttributeValue.argtypes = [c_void_p, c_void_p, POINTER(c_void_p)]
    core_foundation.CFStringCreateWithCString.restype = c_void_p
    core_foundation.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, c_uint32]
    core_foundation.CFRelease.argtypes = [c_void_p]

    if not app_services.AXIsProcessTrusted():
        return False, None

    k_ax_windows = core_foundation.CFStringCreateWithCString(None, b"AXWindows", 0x08000100)

    def probe(pid):
        element = app_services.AXUIElementCreateApplication(pid)
        app_services.AXUIElementSetMessagingTimeout(element, AX_TIMEOUT)
        value = c_void_p()
        started = time.monotonic()
        err = app_services.AXUIElementCopyAttributeValue(element, k_ax_windows, byref(value))
        elapsed = time.monotonic() - started
        if value.value:
            core_foundation.CFRelease(value)
        core_foundation.CFRelease(element)
        if err == 0:
            return "ok"
        if err == AX_CANNOT_COMPLETE and elapsed >= AX_TIMEOUT * 0.8:
            return "hung"
        return "noax"

    return True, probe


# ---------------------------------------------------------------------- processes
def list_processes():
    out = subprocess.run(
        ["/bin/ps", "-axo", "pid=,pcpu=,rss=,stat=,user=,comm="],
        capture_output=True, text=True, check=False,
    ).stdout
    procs = []
    for line in out.splitlines():
        parts = line.strip().split(None, 5)
        if len(parts) < 6:
            continue
        pid, cpu, rss, stat, user, comm = parts
        try:
            pid = int(pid)
        except ValueError:
            continue
        procs.append({
            "pid": pid,
            "cpu": float(cpu) if cpu.replace(".", "", 1).isdigit() else 0.0,
            "rss_kb": int(rss) if rss.isdigit() else 0,
            "stat": stat,
            "user": user,
            "comm": comm,
        })
    return procs


def gui_pids():
    """PIDs LaunchServices knows as running applications (what can hang in the GUI sense)."""
    try:
        out = subprocess.run(["/usr/bin/lsappinfo", "list"], capture_output=True, text=True,
                             timeout=3, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return {int(m) for m in re.findall(r"^\s*pid = (\d+)", out, re.MULTILINE)}


def annotate(proc):
    comm = proc["comm"]
    proc["name"] = os.path.basename(comm.rstrip("/")) or comm
    proc["app_path"] = None
    proc["app_name"] = None
    proc["is_app"] = False
    proc["is_helper"] = False

    idx = comm.find(".app/")
    if idx != -1:
        app_path = comm[: idx + 4]
        proc["app_path"] = app_path
        proc["app_name"] = os.path.basename(app_path)[:-4]
        nested = comm.count(".app/") > 1 or ".appex/" in comm or ".xpc/" in comm
        main_binary = comm.startswith(app_path + "/Contents/MacOS/")
        if main_binary and not nested:
            system_dir = app_path.startswith(("/System/Library/", "/Library/", "/usr/"))
            proc["is_app"] = not system_dir
        else:
            proc["is_helper"] = True


def human_mem(kb):
    if kb >= 1024 * 1024:
        return f"{kb / 1024 / 1024:.1f} GB"
    if kb >= 1024:
        return f"{kb / 1024:.0f} MB"
    return f"{kb} kB"


def matches(proc, words):
    haystack = " ".join(filter(None, [
        proc["name"], proc["app_name"] or "", str(proc["pid"]), proc["comm"], proc["user"],
    ])).lower()
    return all(word in haystack for word in words)


def build_items(query):
    words = query.lower().split()
    procs = list_processes()
    me = os.getpid()
    procs = [p for p in procs if p["pid"] not in (0, me)]
    for proc in procs:
        annotate(proc)

    trusted, probe = make_ax_probe()
    candidates = gui_pids() if probe else None
    for proc in procs:
        state = proc["stat"][:1]
        if state == "T":
            proc["problem"] = "stoppet"
        elif state == "Z":
            proc["problem"] = "zombie"
        else:
            proc["problem"] = None
        if candidates is None:
            is_candidate = bool(proc["app_path"]) and not proc["is_helper"]
        else:
            is_candidate = proc["pid"] in candidates
        if proc["problem"] is None and probe and is_candidate:
            if probe(proc["pid"]) == "hung":
                proc["problem"] = "svarer ikke"

    groups = {}
    for proc in procs:
        if proc["app_path"]:
            groups.setdefault(proc["app_path"], []).append(proc["pid"])

    def tier(proc):
        if proc["problem"]:
            return 0
        if proc["is_app"]:
            return 1
        return 2

    filtered = [p for p in procs if matches(p, words)] if words else procs
    filtered.sort(key=lambda p: (tier(p), -p["cpu"], -p["rss_kb"], p["name"].lower()))

    items = []
    for proc in filtered[:MAX_ITEMS]:
        pid = proc["pid"]
        name = proc["name"]
        title = f"⚠️ {name} – {proc['problem']}" if proc["problem"] else name
        bits = [f"PID {pid}", f"{proc['cpu']:.1f} % CPU", human_mem(proc["rss_kb"]), proc["user"]]
        if proc["is_helper"] and proc["app_name"]:
            bits.append(f"del av {proc['app_name']}")
        subtitle = " · ".join(bits)

        icon_path = proc["app_path"] or (proc["comm"] if os.path.exists(proc["comm"]) else GENERIC_ICON)
        group_pids = groups.get(proc["app_path"], [pid]) if proc["app_path"] else [pid]
        group_label = proc["app_name"] or name

        item = {
            "title": title,
            "subtitle": subtitle,
            "arg": str(pid),
            "icon": {"type": "fileicon", "path": icon_path},
            "variables": {
                "pid": str(pid),
                "name": name,
                "group_name": group_label,
                "group_pids": " ".join(str(p) for p in group_pids),
            },
            "text": {
                "copy": str(pid),
                "largetype": f"{name}\nPID {pid}\n{proc['comm']}",
            },
            "mods": {
                "cmd": {"subtitle": f"Tvangsavslutt {name} (kill -9)"},
                "alt": {"subtitle": f"Avslutt hele {group_label} ({len(group_pids)} prosesser)"},
            },
        }
        items.append(item)

    if not items:
        items.append({
            "title": "Ingen prosesser matcher",
            "subtitle": query,
            "valid": False,
            "icon": {"path": GENERIC_ICON},
        })

    if not trusted:
        items.append({
            "title": "Kan ikke oppdage hengende apper",
            "subtitle": "Gi Alfred tilgang under Personvern og sikkerhet → Tilgjengelighet. Enter åpner innstillingen.",
            "arg": "open-accessibility-settings",
            "variables": {"action": "open_ax_settings"},
            "icon": {"path": "/System/Library/PreferencePanes/Security.prefPane/Contents/Resources/Security.icns"},
        })

    return items


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    items = build_items(query.strip())
    json.dump({"items": items}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
