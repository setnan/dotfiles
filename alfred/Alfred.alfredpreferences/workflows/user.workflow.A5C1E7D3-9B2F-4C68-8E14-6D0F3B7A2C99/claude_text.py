#!/usr/bin/env python3
"""Headless Claude for Alfred: `claude_text.py <mode> "<text>"`.

Modes: ask (short answer), fiks (proofread), oversett (translate no↔en),
forklar (explain). Runs `claude -p` with no tools, no MCP servers and no
session persistence, so it uses the Claude Code login but can touch nothing.
Model from env `ask_model` (ask) / `text_model` (the rest), see user config.
Prints the answer; on failure prints the error so it shows in Alfred.
"""
import os
import subprocess
import sys

CLAUDE = next(
    (p for p in (os.environ.get("claude_bin", ""), os.path.expanduser("~/.local/bin/claude"),
                 "/opt/homebrew/bin/claude", "/usr/local/bin/claude") if p and os.path.exists(p)),
    "claude",
)

SYSTEM = {
    "ask": (
        "Du er en kjapp assistent i Alfred-launcheren. Svar på samme språk som spørsmålet "
        "(norsk bokmål om det er norsk). Vær presis og kort: helst én til tre setninger, "
        "maks fem. Ren tekst uten markdown, overskrifter eller punktlister."
    ),
    "fiks": (
        "Du er korrekturleser. Rett stavefeil, grammatikk og tegnsetting i teksten. Behold "
        "språket (norsk eller engelsk), tonen, formateringen og linjeskiftene. Ikke legg til, "
        "fjern eller omformuler innhold ut over det som trengs for å rette feil. Svar KUN med "
        "den rettede teksten, uten forklaring, innledning eller anførselstegn."
    ),
    "oversett": (
        "Du er oversetter. Er teksten på norsk, oversett til naturlig engelsk. Er den på et "
        "annet språk, oversett til norsk bokmål. Behold tone, formatering og linjeskift. "
        "Svar KUN med oversettelsen, uten forklaring eller anførselstegn."
    ),
    "forklar": (
        "Forklar kort og klart på norsk bokmål hva teksten betyr eller gjør. Er det kode, en "
        "kommando eller en feilmelding: si hva den gjør eller hva som er galt, og hva man bør "
        "gjøre. Maks fem setninger, ren tekst uten markdown."
    ),
}


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in SYSTEM:
        print("Bruk: claude_text.py <ask|fiks|oversett|forklar> <tekst>")
        return 1
    mode = sys.argv[1]
    text = " ".join(sys.argv[2:]).strip()
    if not text:
        print("Ingen tekst")
        return 1
    model = os.environ.get("ask_model" if mode == "ask" else "text_model", "").strip() or (
        "haiku" if mode == "ask" else "sonnet"
    )
    cmd = [
        CLAUDE, "-p", "--tools", "", "--no-session-persistence", "--strict-mcp-config",
        "--setting-sources", "", "--disable-slash-commands", "--model", model,
        "--system-prompt", SYSTEM[mode], text,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        print("Claude svarte ikke innen 3 minutter")
        return 1
    except OSError as e:
        print(f"Fant ikke claude: {e}")
        return 1
    out = r.stdout.strip()
    if r.returncode != 0 or not out:
        print(out or r.stderr.strip() or f"claude feilet (kode {r.returncode})")
        return 1
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
