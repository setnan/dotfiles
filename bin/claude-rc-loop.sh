#!/bin/zsh
# Holder `claude remote-control` (server mode) i live. Kjøres inne i tmux-økten «rc»,
# startet av claude-rc-start.sh (launchd på macOS, systemd --user på Linux).
#
# Konfig leses fra ~/.config/claude-rc/config ved hver runde, så endringer tas uten omstart:
#   dir=/sti/til/arbeidsmappe     # mappen økter starter i (må være godkjent manuelt først)
#   name=Mac                      # navnet maskinen får i Claude-appen
#   capacity=8                    # maks samtidige økter
#
# Server mode avslutter selv etter rundt ti minutter uten nett; da starter løkka den på
# nytt, og et vanlig `claude remote-control` henter tilbake øktene innen fire timer.
set -u
conf="${XDG_CONFIG_HOME:-$HOME/.config}/claude-rc/config"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
# Disse skrur Remote Control av eller tvinger API-nøkkel, så de skal aldri arve inn her.
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL \
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC DISABLE_GROWTHBOOK
if [[ "$(uname)" == Darwin ]]; then
  log="$HOME/Library/Logs/claude-rc.log"
else
  log="${XDG_STATE_HOME:-$HOME/.local/state}/claude-rc.log"
fi
mkdir -p "${log:h}"

say() { print -r -- "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$log"; }

while true; do
  dir="" name="" capacity=""
  if [[ -r "$conf" ]]; then
    source "$conf"
  else
    say "mangler $conf – venter 60 s"; sleep 60; continue
  fi
  : "${name:=$(hostname -s)}" "${capacity:=8}"
  if [[ -z "$dir" ]] || ! cd "$dir"; then
    say "dir='$dir' finnes ikke – venter 60 s"; sleep 60; continue
  fi
  say "starter claude remote-control --name '$name' --capacity $capacity i $dir"
  claude remote-control --name "$name" --capacity "$capacity"
  say "remote-control avsluttet (kode $?) – restarter om 15 s"
  sleep 15
done
