# General shell config (PATH and core environment)

# Homebrew
if [ -x /opt/homebrew/bin/brew ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

export PATH="$HOME/bin:$HOME/.local/bin:/usr/local/bin:/usr/sbin:/sbin:$PATH"

# bun
export BUN_INSTALL="$HOME/.bun"
[ -d "$BUN_INSTALL/bin" ] && export PATH="$BUN_INSTALL/bin:$PATH"

# Postgres client tools (psql, pg_dump). Homebrew keeps postgresql@18
# keg-only, so its bin directory is not linked into /opt/homebrew/bin.
[ -d /opt/homebrew/opt/postgresql@18/bin ] && export PATH="/opt/homebrew/opt/postgresql@18/bin:$PATH"

# Editor
export EDITOR=micro
export VISUAL=micro
