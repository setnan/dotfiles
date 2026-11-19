#!/bin/zsh
# Starter tmux-økten «rc» med claude-rc-loop.sh hvis den ikke allerede finnes.
# Trygg å kjøre flere ganger (ny innlogging, launchctl kickstart, systemctl restart).
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
tmux has-session -t rc 2>/dev/null && exit 0
exec tmux new-session -d -s rc "$HOME/bin/claude-rc-loop.sh"
