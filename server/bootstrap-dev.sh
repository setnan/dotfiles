#!/usr/bin/env bash
# Bootstrap for utviklingsserveren «etnandev-dev» (Ubuntu 24.04, Gigahost). Idempotent.
#
#   Som root, første gang:   curl -fsSL <rå-url til denne fila> | bash -s -- root
#   Som dev, etterpå:        ~/bootstrap-dev.sh dev
#
# root-delen: pakker, swap, unattended-upgrades, bruker «dev» uten sudo med linger,
#             Tailscale, ufw som bare slipper inn på tailscale0.
# dev-delen:  mise (Erlang/Elixir/Node), Postgres-rolle, 1Password CLI, Claude Code,
#             ~/bin-skript, tmux.conf, systemd --user-enhet for Remote Control.
#
# Det som IKKE skjer her, fordi det krever et menneske: `tailscale up`, `claude auth login`,
# første `claude remote-control` (tillit + spawn-modus), 1Password service account-token,
# SSH-nøkkel inn på pushin.eu. Se «EtnanDev – Serveroppsett steg for steg», steg 10.
set -euo pipefail

DEV_USER="${DEV_USER:-dev}"
DOTFILES_RAW="${DOTFILES_RAW:-https://raw.githubusercontent.com/setnan/dotfiles/main}"

root_part() {
  [[ $EUID -eq 0 ]] || { echo "kjør root-delen som root" >&2; exit 1; }
  hostnamectl set-hostname etnandev-dev
  timedatectl set-timezone Europe/Oslo
  export DEBIAN_FRONTEND=noninteractive
  apt-get update && apt-get upgrade -y
  apt-get install -y ufw unattended-upgrades curl git tmux build-essential \
    autoconf libssl-dev libncurses-dev libwxgtk3.2-dev libgl1-mesa-dev libglu1-mesa-dev \
    unixodbc-dev xsltproc fop libxml2-utils inotify-tools postgresql postgresql-contrib \
    gnupg ca-certificates
  dpkg-reconfigure -f noninteractive unattended-upgrades

  if ! swapon --show | grep -q /swapfile; then
    fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi

  id "$DEV_USER" &>/dev/null || adduser --disabled-password --gecos "" "$DEV_USER"
  mkdir -p "/home/$DEV_USER/.ssh"
  [[ -f /root/.ssh/authorized_keys ]] && cp -n /root/.ssh/authorized_keys "/home/$DEV_USER/.ssh/"
  chown -R "$DEV_USER:$DEV_USER" "/home/$DEV_USER/.ssh" && chmod 700 "/home/$DEV_USER/.ssh"
  loginctl enable-linger "$DEV_USER"

  # Postgres: lokal rolle for tester, bare på localhost.
  sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='$DEV_USER'" | grep -q 1 \
    || sudo -u postgres psql -c "CREATE ROLE $DEV_USER LOGIN SUPERUSER PASSWORD 'postgres';"

  # 1Password CLI fra offisielt apt-repo.
  if ! command -v op &>/dev/null; then
    curl -sS https://downloads.1password.com/linux/keys/1password.asc \
      | gpg --dearmor -o /usr/share/keyrings/1password-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/1password-archive-keyring.gpg] https://downloads.1password.com/linux/debian/$(dpkg --print-architecture) stable main" \
      > /etc/apt/sources.list.d/1password.list
    apt-get update && apt-get install -y 1password-cli
  fi

  command -v tailscale &>/dev/null || curl -fsSL https://tailscale.com/install.sh | sh

  ufw default deny incoming
  ufw default allow outgoing
  ufw allow in on tailscale0
  ufw --force enable

  cp "$0" "/home/$DEV_USER/bootstrap-dev.sh" 2>/dev/null || true
  chown "$DEV_USER:$DEV_USER" "/home/$DEV_USER/bootstrap-dev.sh" 2>/dev/null || true
  cat <<MSG

root-delen ferdig. Nå:
  1. tailscale up            (logg inn, slå av key expiry i admin-panelet)
  2. Sjekk at du kommer inn over tailnettet: ssh $DEV_USER@etnandev-dev
  3. Som $DEV_USER: ~/bootstrap-dev.sh dev
MSG
}

dev_part() {
  [[ $EUID -ne 0 ]] || { echo "kjør dev-delen som $DEV_USER, ikke root" >&2; exit 1; }
  mkdir -p ~/bin ~/src ~/.config/claude-rc ~/.config/systemd/user ~/.config/environment.d

  # mise for Erlang, Elixir og Node.
  command -v mise &>/dev/null || curl -fsSL https://mise.run | sh
  export PATH="$HOME/.local/bin:$HOME/.local/share/mise/shims:$PATH"
  grep -q 'mise activate' ~/.bashrc || echo 'eval "$(~/.local/bin/mise activate bash)"' >> ~/.bashrc
  mise use -g erlang@latest elixir@latest node@lts

  # Claude Code (native installer) og innlogging gjøres manuelt etterpå.
  command -v claude &>/dev/null || curl -fsSL https://claude.ai/install.sh | bash

  for f in claude-rc-loop.sh claude-rc-start.sh; do
    curl -fsSL "$DOTFILES_RAW/bin/$f" -o ~/bin/$f && chmod +x ~/bin/$f
  done
  curl -fsSL "$DOTFILES_RAW/tmux.conf" -o ~/.tmux.conf
  curl -fsSL "$DOTFILES_RAW/server/claude-rc.service" -o ~/.config/systemd/user/claude-rc.service
  sed -i 's|/usr/bin/tmux|'"$(command -v tmux)"'|' ~/.config/systemd/user/claude-rc.service

  [[ -f ~/.config/claude-rc/config ]] || cat > ~/.config/claude-rc/config <<CONF
dir=$HOME/src
name=EtnanDev
capacity=8
CONF
  [[ -f ~/.ssh/id_ed25519 ]] || ssh-keygen -t ed25519 -N "" -C "etnandev-dev" -f ~/.ssh/id_ed25519

  systemctl --user daemon-reload
  cat <<MSG

dev-delen ferdig. Gjenstår manuelt:
  1. Offentlig nøkkel inn på pushin.eu:  cat ~/.ssh/id_ed25519.pub
  2. git clone av repoene til ~/src
  3. claude auth login                  (claude.ai-kontoen, lenke + kode)
  4. cd ~/src && claude remote-control --name EtnanDev   → svar y, y, 1, så Ctrl+C
  5. claude → /config → push-varsler på
  6. 1Password: echo 'OP_SERVICE_ACCOUNT_TOKEN=…' > ~/.config/environment.d/op.conf && chmod 600 …
  7. systemctl --user enable --now claude-rc && tmux attach -t rc
MSG
}

case "${1:-}" in
  root) root_part ;;
  dev)  dev_part ;;
  *) echo "bruk: $0 root | dev" >&2; exit 1 ;;
esac
