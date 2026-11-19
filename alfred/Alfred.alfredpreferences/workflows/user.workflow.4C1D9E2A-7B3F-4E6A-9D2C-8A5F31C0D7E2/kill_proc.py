#!/usr/bin/env python3
"""Alfred script action: terminate the process(es) chosen in kill_list.py.

Usage: kill_proc.py term|kill|group
Reads pid, name, group_name, group_pids (and optionally action) from the
workflow variables Alfred exposes as environment variables. Prints a
one-line status for the notification node.
"""
import os
import signal
import subprocess
import sys
import time


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def send(pid, sig):
    """Return None on success, otherwise an error description."""
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return "finnes ikke lenger"
    except PermissionError:
        return "ingen tilgang (eies av en annen bruker – bruk sudo kill i terminalen)"
    except OSError as exc:
        return exc.strerror
    return None


def wait_gone(pids, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not any(alive(p) for p in pids):
            return True
        time.sleep(0.1)
    return not any(alive(p) for p in pids)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "term"
    env = os.environ

    if env.get("action") == "open_ax_settings":
        subprocess.run(["/usr/bin/open",
                        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])
        print("Legg til Alfred under Tilgjengelighet, så oppdages hengende apper.")
        return

    try:
        pid = int(env.get("pid", ""))
    except ValueError:
        print("Ingen prosess valgt.")
        return
    name = env.get("name") or str(pid)

    if mode == "group":
        pids = [int(p) for p in env.get("group_pids", "").split() if p.isdigit()] or [pid]
        label = env.get("group_name") or name
        errors = {p: send(p, signal.SIGTERM) for p in pids}
        failed = {p: e for p, e in errors.items() if e and e != "finnes ikke lenger"}
        if failed:
            print(f"Kunne ikke avslutte alt av {label}: " + "; ".join(f"PID {p}: {e}" for p, e in failed.items()))
            return
        gone = wait_gone(pids, 2.0)
        print(f"Avsluttet {label} ({len(pids)} prosesser)" if gone
              else f"Ba {label} om å avslutte ({len(pids)} prosesser) – Cmd+Enter for å tvinge")
        return

    if mode == "kill":
        err = send(pid, signal.SIGKILL)
        if err:
            print(f"Kunne ikke tvangsavslutte {name} (PID {pid}): {err}")
        else:
            wait_gone([pid], 1.0)
            print(f"Tvangsavsluttet {name} (PID {pid})")
        return

    err = send(pid, signal.SIGTERM)
    if err:
        print(f"Kunne ikke avslutte {name} (PID {pid}): {err}")
        return
    if wait_gone([pid], 2.0):
        print(f"Avsluttet {name} (PID {pid})")
    else:
        print(f"Ba {name} (PID {pid}) om å avslutte – bruk Cmd+Enter for å tvinge")


if __name__ == "__main__":
    main()
