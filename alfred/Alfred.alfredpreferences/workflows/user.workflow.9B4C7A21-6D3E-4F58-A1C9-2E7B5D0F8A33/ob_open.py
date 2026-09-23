#!/usr/bin/env python3
"""Alfred script action: open a note, run a vault search, or reveal the file.

Usage: ob_open.py open|search|reveal   (reads file/path/query/action/vault_* from env)
"""
import os
import subprocess
import sys
import urllib.parse

VAULT_PATH = os.environ.get("vault_path") or "/Users/simonetnan/Documents/Koderiet/RSA/md/SE-v2"
VAULT_NAME = os.environ.get("vault_name") or os.path.basename(VAULT_PATH.rstrip("/"))


def q(s):
    return urllib.parse.quote(s, safe="")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "open"
    env = os.environ
    if mode == "open" and env.get("action") == "search":
        mode = "search"
    if mode == "reveal" and env.get("path"):
        subprocess.run(["/usr/bin/open", "-R", env["path"]])
    elif mode == "search":
        query = env.get("query", "")
        url = f"obsidian://search?vault={q(VAULT_NAME)}" + (f"&query={q(query)}" if query else "")
        subprocess.run(["/usr/bin/open", url])
    else:
        file = env.get("file", "")
        url = f"obsidian://open?vault={q(VAULT_NAME)}" + (f"&file={q(file)}" if file else "")
        subprocess.run(["/usr/bin/open", url])


if __name__ == "__main__":
    main()
