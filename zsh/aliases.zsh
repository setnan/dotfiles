# Global aliases

alias zshrefresh="exec zsh"
alias reload='source "$ZDOTDIR/.zshrc"'   # last zshrc på nytt uten å starte skallet
alias uke='date +%V'
alias isodate="date +'%Y-%m-%dT%H:%M:%SZ'"

# Editor
alias m=micro
alias vim=micro

# ls via eza if available
if (( $+commands[eza] )); then
  alias ls='eza --icons --group-directories-first'
  alias l='eza -la --icons --group-directories-first'
  alias ll='eza -l --icons --group-directories-first'
  alias la='eza -la --icons --group-directories-first'
  alias lt='eza --tree --level=2 --icons --group-directories-first'
  alias lg='eza -l --git --icons --group-directories-first'                       # git-status per fil
  alias ltg='eza --tree --level=2 --git-ignore --icons --group-directories-first'  # tre uten gitignored støy
  alias lm='eza -la -s modified --icons --group-directories-first'                # nyeste nederst
fi

# Git
alias g=git
alias gs='g status'
alias gau='g add -u .'
alias gun='g reset HEAD'
alias gdc='g diff --cached'
alias gdn='g diff --no-index'   # diff to vilkårlige filer/mapper, uavhengig av git-historikk
alias gwtb='g worktree add -b'
alias gwta='g worktree add'
alias gwtr='g worktree remove'
alias gci='git checkout $(git branch | fzf)'
alias gcia='git checkout $(git branch -a | fzf)'
alias gdi='git branch -D $(git branch | fzf)'

# Elixir
alias mps='mix phx.server'
alias imps='iex -S mix phx.server'
alias mt='mix test'
alias mdg='mix deps.get'

# Tree
alias tree2='tree -L 2'
alias tree3='tree -L 3'
alias tree4='tree -L 4'

alias pfind='ps aux | grep'

alias todos='rg "TODO:"'

# Homebrew
alias bs="brew search"
alias bi="brew install"
alias b="brew"
alias bupg="brew upgrade"

# Docker
alias dcu="docker compose up"
alias dcd="docker compose down"
alias dcdb="docker compose up db"

# OSX or not
if [[ `uname` == "Darwin" ]]; then
  alias open=open
else
  alias open=xdg-open
fi

# Functions

# Serve current directory over http, default port 8080
function serve {
  local port="${1:-8080}"
  if (( $+commands[caddy] )); then
    caddy file-server --browse --listen ":$port"
  else
    python3 -m http.server "$port"
  fi
}
